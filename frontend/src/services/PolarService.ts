/**
 * PolarService.ts
 *
 * BLE integration for Polar Verity Sense armband.
 *
 * What this does:
 *  1. Scans for a Polar Verity Sense device (name contains "Polar")
 *  2. Connects and starts PPI measurement via the Polar PMD BLE protocol
 *  3. Buffers incoming PPI beats in memory
 *  4. Every FLUSH_INTERVAL_MS, sends the buffered beats to POST /tracking/ingest
 *
 * Architecture:
 *  - Singleton class; access via the exported `polarService` instance
 *  - Emits status changes via `onStatusChange` callback
 *  - Emits individual beats via `onBeat` callback (for UI feedback)
 *  - Persists the last connected device ID to AsyncStorage for auto-reconnect
 *
 * Polar PMD BLE protocol (Verity Sense):
 *  Service UUID  : fb005c80-02e7-f387-1cad-8acd2d8df0c8
 *  Control Point : fb005c81-02e7-f387-1cad-8acd2d8df0c8  (write + notify)
 *  Data          : fb005c82-02e7-f387-1cad-8acd2d8df0c8  (notify only)
 *
 *  Start PPI: write [0x01, 0x03] to Control Point
 *    0x01 = START_MEASUREMENT, 0x03 = PPI measurement type
 *
 *  PPI data packet layout (per notification on Data char):
 *    byte 0     : 0x03 (measurement type = PPI)
 *    bytes 1-8  : timestamp, uint64 LE nanoseconds (not used — we use device clock)
 *    byte 9     : frame type = 0x00 (raw)
 *    then frames, each 6 bytes:
 *      byte  0  : HR (uint8, bpm)
 *      bytes 1-2: PPI interval (uint16 LE, ms)
 *      bytes 3-4: PPI error estimate (uint16 LE, ms)
 *      byte  5  : flags
 *                   bit0 = PP interval status (1 = cannot estimate interval — discard)
 *                   bit1 = blocker (1 = movement detected — discard)
 *                   bit2 = skin contact (1 = contact present; UNRELIABLE on Verity Sense — do not rely)
 *                   bit3 = skin contact supported
 *
 * Connection best-practices (react-native-ble-plx + Android GATT):
 *   - Use manager.connectToDevice(id) not device.connect() — the scanned Device instance
 *     is a lightweight advertisement wrapper; its native handle may be stale once scan stops.
 *   - Pass refreshGatt: 'OnConnected' to flush Android GATT service cache on every connect.
 *   - Cancel any existing GATT session before connecting to avoid stale-session conflicts.
 *   - Stop scan and wait one tick before connecting (Android race condition).
 *   - Verify PMD service actually appeared after discovery before writing to it.
 */

import { BleManager, Device, Characteristic, State, Subscription } from 'react-native-ble-plx';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { AppState, Platform, type AppStateStatus } from 'react-native';
import { getClient } from '../api/client';
import VIForegroundService from '@supersami/rn-foreground-service';
import * as base64 from 'base64-js';
import { log } from '../utils/log';
// ── Constants ─────────────────────────────────────────────────────────────────

const PMD_SERVICE      = 'fb005c80-02e7-f387-1cad-8acd2d8df0c8';
const PMD_CONTROL      = 'fb005c81-02e7-f387-1cad-8acd2d8df0c8';
const PMD_DATA         = 'fb005c82-02e7-f387-1cad-8acd2d8df0c8';

// Standard BLE Battery Service (0x180F) / Battery Level (0x2A19)
const BATTERY_SERVICE  = '0000180f-0000-1000-8000-00805f9b34fb';
const BATTERY_LEVEL    = '00002a19-0000-1000-8000-00805f9b34fb';

/** Start PPI measurement command bytes: START(0x02) + PPI type(0x03) */
const START_PPI_CMD    = 'AgM='; // Base64 for [0x02, 0x03]

const STORAGE_DEVICE_KEY = '@polar_device_id';
const FLUSH_FOREGROUND_MS  = 60_000;
const FLUSH_BACKGROUND_MS  = 3 * 60_000;
const FLUSH_SLEEP_MS       = 10 * 60_000;
const RECONNECT_BASE_DELAY_MS = 5_000;
const RECONNECT_MAX_DELAY_MS  = 120_000;
const DEFAULT_SCAN_TIMEOUT_MS = 30_000;
const RECONNECT_SCAN_TIMEOUT_MS = 8_000;
// Stable task ID used with VIForegroundService.add_task() — the native
// foreground service wakes the JS engine via HeadlessJsTaskService to run this,
// which survives Android Doze mode / JS thread suspension.
const FLUSH_TASK_ID      = 'zenflow_beat_flush';

// ── Sleep / wake inference (HR + PPI coefficient of variation) ────────────────
// The Polar sensor provides no sleep state. We infer it from:
//   1. Mean HR sustained at or below SLEEP_HR_THRESHOLD
//   2. PPI coefficient of variation (stddev/mean) below SLEEP_CV_THRESHOLD
//      (CV drops when rhythm is highly regular — parasympathetic sleep dominance)
// Both conditions must hold across a rolling window of SLEEP_STATS_WINDOW beats
// for SLEEP_CONFIRM_BEATS consecutive rolling-window evaluations to register a
// transition. Wake detection fires when EITHER threshold is broken.
const SLEEP_HR_THRESHOLD  = 70;    // bpm — floor for nocturnal HR
const SLEEP_CV_THRESHOLD  = 0.10;  // PPI coefficient of variation — very regular rhythm
const SLEEP_STATS_WINDOW  = 30;    // beats in rolling stats buffer (~3–4 min at 50 bpm)
const SLEEP_CONFIRM_BEATS = 20;    // consecutive passing checks needed → ~2 min confirmation
const SLEEP_EARLIEST_HOUR = 21;    // 9 pm — no sleep inference before this hour
const WAKE_HR_THRESHOLD   = 75;    // bpm — sustained rise signals arousal (sleep → background)
const WAKE_CV_THRESHOLD   = 0.12;  // PPI CV — irregular rhythm signals wake
const WAKE_CONFIRM_BEATS  = 10;    // consecutive checks → ~2 min confirmation

// ── Types ─────────────────────────────────────────────────────────────────────

export type PolarStatus =
  | 'idle'
  | 'bluetooth_off'
  | 'scanning'
  | 'connecting'
  | 'connected'
  | 'streaming'
  | 'no_signal'         // streaming but zero valid beats after 90 s — likely poor skin contact
  | 'error';

export interface BeatBuffer {
  ppi_ms:   number;
  ts:       number;       // unix epoch seconds
  artifact: boolean;
}

// ── Service class ─────────────────────────────────────────────────────────────

class PolarService {
  private manager:            BleManager | null    = null;
  private device:             Device | null      = null;
  private ppiSubscription:    Subscription | null = null;
  private controlSubscription: Subscription | null = null;   // PMD_CONTROL indications — CCCD must be set before firmware accepts commands
  private disconnectSub:      Subscription | null = null;   // onDeviceDisconnected — stored to prevent listener accumulation on reconnect
  private flushTimer:         ReturnType<typeof setInterval> | null = null;
  private reconnectTimer:     ReturnType<typeof setTimeout>  | null = null;
  private scanTimeout:        ReturnType<typeof setTimeout>  | null = null;

  private beats:        BeatBuffer[] = [];
  private _status:       PolarStatus  = 'idle';
  private _beatCount:    number       = 0;
  private _blockedCount: number       = 0;   // frames discarded: blocker flag (bit1) set
  private _packetCount:  number       = 0;   // raw PPI frames seen (blocked+valid+invalid)
  private _deviceId:     string | null = null; // stored separately so we keep it after device ref may go stale
  private _lastFlushAt:  Date | null  = null;
  // Tracks when we last triggered a flush from the BLE callback path.
  // Separate from _lastFlushAt (which is set only on successful API POST).
  // Used to throttle the callback-driven flush to once per FLUSH_INTERVAL_MS.
  private _lastCallbackFlushAt: number = 0;
  private _noSignalTimer: ReturnType<typeof setTimeout> | null = null;
  private static readonly NO_SIGNAL_TIMEOUT_MS = 90_000;
  // Option B: track whether the foreground service is already running so
  // BLE reconnects never call startForegroundService() a second time.
  private _serviceRunning = false;
  private _flushIntervalMs = FLUSH_FOREGROUND_MS;
  private _flushInflight: Promise<void> | null = null;
  private _reconnectAttempt = 0;
  private _appState: AppStateStatus = AppState.currentState;
  private _appStateSub: { remove: () => void } | null = null;

  // ── Sleep state machine ───────────────────────────────────────────────────
  private _sleepState: 'background' | 'sleep' = 'background';
  private _sleepWindowBeats: Array<{ hr: number; ppi: number }> = [];
  private _sleepCandidateCount = 0;
  private _wakeCandidateCount  = 0;

  // ── Multi-listener pub/sub ────────────────────────────────────────────────
  private _statusListeners = new Set<(status: PolarStatus) => void>();
  private _beatListeners   = new Set<(ppi_ms: number, hr_bpm: number) => void>();
  private _flushListeners  = new Set<(beats_sent: number) => void>();
  private _batteryListeners = new Set<(pct: number | null) => void>();
  private _batteryPct: number | null = null;
  private _batterySub: Subscription | null = null;
  private _batteryTimer: ReturnType<typeof setInterval> | null = null;

  /** Subscribe to status changes. Returns an unsubscribe function. */
  subscribeStatus(fn: (status: PolarStatus) => void): () => void {
    this._statusListeners.add(fn);
    return () => this._statusListeners.delete(fn);
  }

  /** Subscribe to individual beats. Returns an unsubscribe function. */
  subscribeBeat(fn: (ppi_ms: number, hr_bpm: number) => void): () => void {
    this._beatListeners.add(fn);
    return () => this._beatListeners.delete(fn);
  }

  /** Subscribe to flush events. Returns an unsubscribe function. */
  subscribeFlush(fn: (beats_sent: number) => void): () => void {
    this._flushListeners.add(fn);
    return () => this._flushListeners.delete(fn);
  }

  /** Subscribe to battery level updates (0–100). Returns an unsubscribe function. */
  subscribeBattery(fn: (pct: number | null) => void): () => void {
    this._batteryListeners.add(fn);
    // fire immediately with current value
    try { fn(this._batteryPct); } catch {}
    return () => this._batteryListeners.delete(fn);
  }

  get batteryPct(): number | null {
    return this._batteryPct;
  }

  /** Total valid beats buffered/sent this session. */
  get beatCount(): number { return this._beatCount; }

  /** Raw PPI frames seen (includes blocked + range-rejected). */
  get packetCount(): number { return this._packetCount; }

  /** Frames discarded due to blocked flag (no skin contact). */
  get blockedCount(): number { return this._blockedCount; }

  /** Timestamp of last successful flush to the API. */
  get lastFlushAt(): Date | null { return this._lastFlushAt; }

  // ── Init ──────────────────────────────────────────────────────────────────

  /**
   * Call once on app startup (after onboarding completes).
   * Sets up BLE manager and starts scanning.
   */
  async start(): Promise<void> {
    if (this.manager) return;           // already started

    this.manager = new BleManager();
    this._appStateSub?.remove();
    this._appStateSub = AppState.addEventListener('change', (st) => {
      this._appState = st;
      this._updateFlushSchedule();
      if (st === 'active') {
        // Catch up server-side scores quickly when user returns.
        this.flushNow().catch(() => {});
      }
    });

    // Wait for BT to be powered on
    this.manager.onStateChange((state) => {
      if (state === State.PoweredOn) {
        this._startScan(DEFAULT_SCAN_TIMEOUT_MS);
      } else if (state === State.PoweredOff) {
        this._setStatus('bluetooth_off');
        this._scheduleReconnect();
      }
    }, true);
  }

  /** Stop everything — call on app background / unmount. */
  stop(): void {
    this._clearTimers();
    this.ppiSubscription?.remove();
    this.ppiSubscription = null;
    this.controlSubscription?.remove();
    this.controlSubscription = null;
    this._batterySub?.remove();
    this._batterySub = null;
    this.disconnectSub?.remove();
    this.disconnectSub = null;
    this._stopForegroundService();
    this.device?.cancelConnection().catch(() => {});
    this.manager?.destroy();
    this.manager = null;
    this.device  = null;
    this._appStateSub?.remove();
    this._appStateSub = null;
    this._setStatus('idle');
  }

  get status(): PolarStatus {
    return this._status;
  }

  get deviceName(): string | null {
    return this.device?.name ?? null;
  }

  /** Force-flush the beat buffer right now (e.g. on app foreground). */
  async flushNow(): Promise<void> {
    await this._flushBeats();
  }

  // ── Scan ──────────────────────────────────────────────────────────────────

  private async _startScan(scanWindowMs: number): Promise<void> {
    if (!this.manager) return;

    this._setStatus('scanning');

    const savedId = await AsyncStorage.getItem(STORAGE_DEVICE_KEY);

    // Clear any existing scan timeout
    if (this.scanTimeout) clearTimeout(this.scanTimeout);

    this.scanTimeout = setTimeout(() => {
      this.manager?.stopDeviceScan();
      // Only go to error if we never found the device; reschedule scan
      if (this._status === 'scanning') {
        this._setStatus('error');
        this._scheduleReconnect();
      }
    }, scanWindowMs);

    // Scan ALL devices — Polar Verity Sense does NOT include the PMD service
    // UUID in its advertising packets, so filtering by service UUID finds nothing.
    // Filter by device name instead once we get results.
    this.manager.startDeviceScan(
      null,                              // ← no service filter
      { allowDuplicates: false },
      async (error, scannedDevice) => {
        if (error) {
          console.warn('[Polar] scan error:', error.message);
          return;
        }
        if (!scannedDevice) return;

        const name = scannedDevice.name ?? '';
        const matchesSaved = savedId && scannedDevice.id === savedId;
        const matchesName  = name.toLowerCase().includes('polar');

        if (!matchesSaved && !matchesName) return;

        // Found our Polar device — stop scan and connect.
        // Wait one JS tick after stopDeviceScan before connecting to avoid an
        // Android race condition where the scan teardown isn't fully flushed.
        this.manager?.stopDeviceScan();
        if (this.scanTimeout) {
          clearTimeout(this.scanTimeout);
          this.scanTimeout = null;
        }

        await new Promise<void>((r) => setTimeout(r, 0));
        await this._connectToDevice(scannedDevice);
      },
    );
  }

  // ── Connect ───────────────────────────────────────────────────────────────

  private async _connectToDevice(device: Device): Promise<void> {
    if (!this.manager) return;
    this._setStatus('connecting');

    const deviceId = device.id;
    this._deviceId = deviceId;

    // ── GATT-retry loop ───────────────────────────────────────────────────
    // Android GATT cache can return an empty service list even after a fresh
    // discoverAllServicesAndCharacteristics().  refreshGatt:'OnConnected' is
    // supposed to fix this but is silently ignored on non-rooted devices.
    // Work-around: full disconnect → 2 s delay → reconnect, up to MAX_GATT_ATTEMPTS.
    const MAX_GATT_ATTEMPTS = 3;

    let connected!: Device;
    let lastErr: Error = new Error('GATT: no attempts made');

    for (let attempt = 1; attempt <= MAX_GATT_ATTEMPTS; attempt++) {
      try {
        // Cancel any stale GATT session before connecting (Gap 5).
        try { await this.manager.cancelDeviceConnection(deviceId); } catch { /* not connected — ok */ }

        // Wait 300 ms after cancel so Android releases the GATT slot cleanly.
        await new Promise<void>((r) => setTimeout(r, 300));

        // Gap 1 + 2: Use manager.connectToDevice (not device.connect).
        // autoConnect:true → Android Bluetooth hardware stack registers a background
        // connection at radio level. The OS reconnects whenever the peripheral
        // advertises, independent of the JS thread — essential for background BLE
        // (how Garmin Connect / Polar Beat maintain connection when app is minimized).
        // NOTE: timeout is mutually exclusive with autoConnect on Android GATT; omit it.
        // refreshGatt:'OnConnected' may be ignored on locked-down Android builds;
        // the retry loop above is the reliable fallback.
        const conn = await this.manager.connectToDevice(deviceId, {
          autoConnect:  true,           // Android radio-level reconnect — survives JS thread death
          refreshGatt:  'OnConnected',
        });

        await conn.discoverAllServicesAndCharacteristics();

        // Gap 6: Verify the PMD service was actually discovered.
        const services = await conn.services();
        const uuids = services.map((s) => s.uuid.toLowerCase());
        log.debug(`[Polar] attempt ${attempt}/${MAX_GATT_ATTEMPTS} — discovered services: [${uuids.join(', ')}]`);

        const hasPmd = uuids.some((u) => u === PMD_SERVICE.toLowerCase());
        if (!hasPmd) {
          // Full disconnect so next attempt gets a clean GATT slot.
          try { await this.manager.cancelDeviceConnection(deviceId); } catch { }
          const waitMs = attempt * 2_000;   // 2 s, 4 s
          console.warn(`[Polar] PMD service absent on attempt ${attempt} — waiting ${waitMs} ms before retry`);
          await new Promise<void>((r) => setTimeout(r, waitMs));
          lastErr = new Error(`PMD service not found after GATT discovery (attempt ${attempt})`);
          continue;   // retry
        }

        // Log characteristics under PMD service so we can verify DATA/CONTROL UUIDs
        try {
          const chars = await conn.characteristicsForService(PMD_SERVICE);
          const charUuids = chars.map((c) => `${c.uuid}(w=${c.isWritableWithResponse},n=${c.isNotifiable},i=${c.isIndicatable})`);
          log.debug(`[Polar] PMD characteristics: [${charUuids.join(', ')}]`);
        } catch (e: any) {
          console.warn('[Polar] could not enumerate PMD characteristics:', e?.message);
        }

        connected = conn;
        break;        // success
      } catch (err: any) {
        lastErr = err;
        console.warn(`[Polar] connect attempt ${attempt} error:`, err?.message ?? err);
        try { await this.manager.cancelDeviceConnection(deviceId); } catch { }
        if (attempt < MAX_GATT_ATTEMPTS) {
          await new Promise<void>((r) => setTimeout(r, attempt * 2_000));
        }
      }
    }

    if (!connected) {
      console.warn('[Polar] all GATT attempts exhausted:', lastErr?.message);
      throw lastErr;
    }

    try {
      this.device = connected;
      this._reconnectAttempt = 0;

      // Save device ID for future auto-reconnect
      await AsyncStorage.setItem(STORAGE_DEVICE_KEY, deviceId);

      // Gap 7: Store the disconnect subscription so we can remove it before re-registering.
      // Without this, every reconnect stacks another listener, eventually firing
      // _scheduleReconnect() N times in parallel and deadlocking the BLE scanner.
      this.disconnectSub?.remove();
      this.disconnectSub = this.manager.onDeviceDisconnected(deviceId, (_err, _dev) => {
        log.debug('[Polar] disconnected — will retry');
        this.ppiSubscription?.remove();
        this.ppiSubscription = null;
        this.controlSubscription?.remove();
        this.controlSubscription = null;
        // Option B: do NOT stop the foreground service on BLE disconnect.
        // Stopping and restarting while backgrounded triggers an
        // IllegalStateException on Android 12+. The service stays alive
        // through the reconnect cycle and only stops on user-initiated stop().
        this._setStatus('error');
        this._scheduleReconnect();
      });

      await this._startPpiStream(connected);
    } catch (err: any) {
      console.warn('[Polar] connect failed:', err?.message ?? err);
      this._setStatus('error');
      this._scheduleReconnect();
    }
  }

  // ── Foreground service ────────────────────────────────────────────────────

  private async _startForegroundService(): Promise<void> {
    if (Platform.OS !== 'android') return;
    // Option B: service stays running for the lifetime of the session.
    // Only start it once — reconnects after BLE drops must not call start() again
    // because Android 12+ throws IllegalStateException when trying to start a
    // foreground service while the app is backgrounded.
    if (this._serviceRunning) {
      // Service already running — ensure the flush task is still registered
      // (it may have been cleared if the module was hot-reloaded).
      VIForegroundService.add_task(() => this._flushBeats(), {
        delay:  this._flushIntervalMs,
        onLoop: true,
        taskId: FLUSH_TASK_ID,
      });
      return;
    }
    try {
      await (VIForegroundService as any).start({
        id: 1001,
        title: 'ZenFlow',
        message: 'Collecting heart data…',
        icon: 'ic_notification',
        // ServiceType is required by @supersami/rn-foreground-service v2.2.5+.
        // 'connectedDevice' matches the foregroundServiceType declared in
        // AndroidManifest.xml via the withForegroundService Expo plugin.
        ServiceType: 'connectedDevice',
      });
      this._serviceRunning = true;
      // Register the beat flush as a native-managed recurring task.
      // The native foreground service wakes the JS engine via
      // HeadlessJsTaskService on a 500 ms heartbeat and runs any registered
      // tasks when their delay expires — this survives Android Doze mode and
      // JS thread suspension that kills a plain setInterval.
      VIForegroundService.add_task(() => this._flushBeats(), {
        delay:  this._flushIntervalMs,
        onLoop: true,
        taskId: FLUSH_TASK_ID,
      });
    } catch (err: any) {
      console.warn('[Polar] foreground service start failed:', err?.message ?? err);
    }
  }

  private async _stopForegroundService(): Promise<void> {
    if (Platform.OS !== 'android') return;
    try {
      VIForegroundService.remove_task(FLUSH_TASK_ID);
      await VIForegroundService.stop();
      this._serviceRunning = false;
    } catch {
      // ignore — service may not be running
    }
  }

  // ── PPI Stream ────────────────────────────────────────────────────────────

  private async _startPpiStream(device: Device): Promise<void> {
    this._setStatus('connected');
    await this._startForegroundService();

    // ── Pre-Step: Request higher MTU ─────────────────────────────────────────
    // Polar PMD packets are larger than the default 20-byte payload. If we don't
    // request a larger MTU (like 232), the firmware successfully starts streaming
    // internally but drops the packets because they can't fit over the air.
    if (Platform.OS === 'android') {
      try {
        log.debug('[Polar] negotiating MTU to 256 for PMD stream…');
        await device.requestMTU(256);
        log.debug('[Polar] MTU negotiation successful');
      } catch (err: any) {
        // Not a hard blocker — some devices may refuse or already be large enough
        console.warn('[Polar] MTU request failed:', err?.message ?? err);
      }
    }

    // ── Step 1: Subscribe to PMD_CONTROL (fb005c81) indications ────────────
    // Polar firmware requires the host to enable indications on the Control
    // Point CCCD (descriptor 0x2902 = 0x0002) BEFORE it will accept any
    // command written to it. Without this, START_PPI is silently ignored.
    log.debug('[Polar] subscribing to PMD_CONTROL indications…');
    this.controlSubscription = device.monitorCharacteristicForService(
      PMD_SERVICE,
      PMD_CONTROL,
      (error, characteristic) => {
        if (error) {
          console.warn('[Polar] control indication error:', error.message, error.errorCode ?? '');
          return;
        }
        log.debug('[Polar] control point indication received — value:', characteristic?.value ?? 'null');
      },
    );
    log.debug('[Polar] PMD_CONTROL subscription set up:', !!this.controlSubscription);

    // ── Step 1b: Wait 500ms for fb005c81 CCCD descriptor write to complete ──
    // Android GATT queue is serial — only one descriptor write can be
    // in-flight at a time. Logcat confirmed that when both monitor() calls
    // fire 2ms apart, only ONE btif_gattc_write_char_descr is sent over-the-
    // air; the second is silently dropped. This pause lets the first complete
    // its round-trip before we queue the second descriptor write.
    log.debug('[Polar] waiting 500ms for PMD_CONTROL CCCD to settle…');
    await new Promise<void>((r) => setTimeout(r, 500));

    // ── Step 2: Subscribe to PMD_DATA (fb005c82) notifications ─────────────
    log.debug('[Polar] subscribing to PMD_DATA notifications…');
    this.ppiSubscription = device.monitorCharacteristicForService(
      PMD_SERVICE,
      PMD_DATA,
      (error, characteristic) => {
        if (error) {
          console.warn('[Polar] data notify error:', error.message, error.errorCode ?? '');
          // Reconnect on BLE-level errors (device disconnected mid-stream etc.)
          if (error.errorCode === 201 || error.errorCode === 205) {
            this._setStatus('error');
            this._scheduleReconnect();
          }
          return;
        }
        if (characteristic?.value) {
          log.debug('[Polar] callback fired — value len:', characteristic.value.length);
          this._parsePpiPacket(characteristic.value);
        } else {
          console.warn('[Polar] data notify: characteristic or value is null');
        }
      },
    );
    log.debug('[Polar] PMD_DATA subscription set up:', !!this.ppiSubscription);

    // ── Step 3: Wait 500ms for fb005c82 CCCD descriptor write to complete ──
    // The 500ms inter-subscription gap above handled fb005c81. Now give the
    // PMD_DATA CCCD write its own settle window before we issue START_PPI.
    log.debug('[Polar] waiting 500ms for PMD_DATA CCCD to settle…');
    await new Promise<void>((r) => setTimeout(r, 500));

    // ── Step 4: Write START_PPI to the Control Point ────────────────────────
    try {
      await device.writeCharacteristicWithResponseForService(
        PMD_SERVICE,
        PMD_CONTROL,
        START_PPI_CMD,
      );
      log.debug('[Polar] START_PPI written to control point');
    } catch (err: any) {
      // Non-fatal — some Polar firmware returns an indication but also an ATT error.
      console.warn('[Polar] control point write failed:', err?.message ?? err);
    }

    this._setStatus('streaming');

    // Battery level monitoring (non-fatal if unsupported)
    this._startBatteryMonitoring(device).catch(() => {});

    // Start flush timer
    this._updateFlushSchedule();

    // Watchdog: if no valid beats arrive within 90 s, switch to 'no_signal'
    // so the UI can tell the user to re-seat the sensor.
    this._startNoSignalWatchdog();
  }

  // ── PPI Packet Parser ─────────────────────────────────────────────────────

  private _parsePpiPacket(base64Value: string): void {
    try {
      const bytes = base64.toByteArray(base64Value);

      log.debug(`[Polar] raw packet bytes[0]=0x${bytes[0].toString(16)} len=${bytes.length}`);

      // Byte 0: measurement type. Must be 0x03 for PPI.
      if (bytes[0] !== 0x03) {
        console.warn(`[Polar] unexpected measurement type 0x${bytes[0].toString(16)} — expected 0x03`);
        return;
      }

      // Bytes 1-8: timestamp (skip — we use Date.now())
      // Byte 9: frame type (0x00 = raw)
      const frameOffset = 10;

      // Each PPI frame = 6 bytes
      for (let i = frameOffset; i + 6 <= bytes.length; i += 6) {
        this._packetCount++;

        const hr_bpm  = bytes[i];                              // uint8, bpm
        const ppi_ms  = bytes[i + 1] | (bytes[i + 2] << 8);   // uint16 LE, ms
        // bytes[i+3..4] = error estimate (ignored)
        const flags   = bytes[i + 5];

        // Gap 3: Correct Polar PMD flag bits (per official Polar BLE SDK docs):
        //   bit0 = PP interval status / Blocker: 1 = invalid interval / movement detected
        //   bit1 = skin contact status: 1 = contact present, 0 = poor/no contact
        //   bit2 = skin contact supported
        const intervalInvalid = (flags & 0x01) !== 0;  // bit0

        if (intervalInvalid) {
          this._blockedCount++;
          const reason = 'interval invalid/movement';
          log.debug(
            `[Polar] frame discarded (${reason}) — discarded: ${this._blockedCount}/${this._packetCount}`,
          );
          continue;
        }

        // Skip zero or physiologically impossible intervals
        if (ppi_ms === 0 || ppi_ms < 300 || ppi_ms > 2000) continue;

        const beat: BeatBuffer = {
          ppi_ms,
          ts:       Date.now() / 1000,
          artifact: false,
        };
        this.beats.push(beat);
        this._updateSleepState(hr_bpm, ppi_ms);
        this._beatCount++;

        // First valid beat cancels the no-signal watchdog (and reverts 'no_signal' to 'streaming')
        this._cancelNoSignalWatchdog();

        this._beatListeners.forEach((fn) => fn(ppi_ms, hr_bpm));
      }

      // ── Callback-driven flush (primary background flush path) ─────────────
      // setInterval and add_task timers are frozen when the Android JS thread
      // is put to sleep by the OS between BLE wakeups. The BLE notification
      // callback (this function) is the ONLY thing that reliably wakes the JS
      // thread in background. So we flush here, throttled to once per
      // FLUSH_INTERVAL_MS, ensuring data reaches the backend on the first BLE
      // wakeup after 60 s of background collection instead of waiting for a
      // frozen timer that may never fire.
      const now = Date.now();
      if (
        this.beats.length > 0 &&
        now - this._lastCallbackFlushAt >= this._flushIntervalMs
      ) {
        this._lastCallbackFlushAt = now;
        // Fire async without awaiting — _flushBeats is safe to call concurrently
        // (second call exits immediately via beats.length === 0 guard)
        this._flushBeats().catch(() => {});
      }
    } catch (parseErr: any) {
      console.warn('[Polar] packet parse error:', parseErr?.message ?? parseErr);
    }
  }

  // ── Flush ─────────────────────────────────────────────────────────────────

  private _desiredFlushIntervalMs(): number {
    if (this._sleepState === 'sleep') return FLUSH_SLEEP_MS;
    if (this._appState === 'active') return FLUSH_FOREGROUND_MS;
    return FLUSH_BACKGROUND_MS;
  }

  private _updateFlushSchedule(): void {
    const desired = this._desiredFlushIntervalMs();
    this._flushIntervalMs = desired;

    // setInterval runs on both platforms as a baseline flush mechanism.
    if (this.flushTimer) clearInterval(this.flushTimer);
    this.flushTimer = setInterval(() => this._flushBeats(), desired);

    // Update the Android foreground-service task delay if running.
    if (Platform.OS === 'android' && this._serviceRunning) {
      try {
        VIForegroundService.remove_task(FLUSH_TASK_ID);
        VIForegroundService.add_task(() => this._flushBeats(), {
          delay: desired,
          onLoop: true,
          taskId: FLUSH_TASK_ID,
        });
      } catch {
        // ignore
      }
    }
  }

  private async _flushBeats(): Promise<void> {
    if (this._flushInflight) return this._flushInflight;
    if (this.beats.length === 0) return;

    const payload = [...this.beats];
    this.beats = [];             // clear buffer optimistically

    const flushContext = this._sleepState === 'sleep' ? 'sleep' : 'background';

    const p = (async () => {
      try {
        await getClient().post('/tracking/ingest', {
          beats:     payload,
          context:   flushContext,
          acc_mean:  null,
          gyro_mean: null,
        });
        this._lastFlushAt = new Date();
        this._flushListeners.forEach((fn) => fn(payload.length));
      } catch (err: any) {
        // Put beats back on failure so they don't get lost
        this.beats = [...payload, ...this.beats];
        console.warn('[Polar] flush failed:', err?.message ?? err);
      }
    })();

    this._flushInflight = p;
    try {
      await p;
    } finally {
      this._flushInflight = null;
    }
  }

  // ── No-signal watchdog ────────────────────────────────────────────────────

  /**
   * Start a 90-second countdown. If no valid beats arrive by then while
   * the service is in 'streaming', emit 'no_signal' so the UI can tell
   * the user to re-seat the sensor.
   */
  private _startNoSignalWatchdog(): void {
    this._cancelNoSignalWatchdog();
    this._noSignalTimer = setTimeout(() => {
      this._noSignalTimer = null;
      if (this._beatCount === 0 && (this._status === 'streaming' || this._status === 'no_signal')) {
        console.warn('[Polar] no_signal: 90 s elapsed with zero valid beats — check sensor placement');
        this._setStatus('no_signal');
      }
    }, PolarService.NO_SIGNAL_TIMEOUT_MS);
  }

  /** Cancel the watchdog. If status was 'no_signal', revert to 'streaming'. */
  private _cancelNoSignalWatchdog(): void {
    if (this._noSignalTimer) {
      clearTimeout(this._noSignalTimer);
      this._noSignalTimer = null;
    }
    if (this._status === 'no_signal') {
      this._setStatus('streaming');
    }
  }

  // ── Reconnect ─────────────────────────────────────────────────────────────

  private _scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    const attempt = this._reconnectAttempt;
    const pow = Math.min(5, attempt); // cap exponential growth
    const base = Math.min(RECONNECT_MAX_DELAY_MS, RECONNECT_BASE_DELAY_MS * (2 ** pow));
    const jitter = 0.2 * base * (Math.random() - 0.5) * 2; // ±20%
    const delay = Math.max(RECONNECT_BASE_DELAY_MS, Math.round(base + jitter));
    this._reconnectAttempt += 1;

    this.reconnectTimer = setTimeout(async () => {
      this.reconnectTimer = null;
      if (!this.manager) return;
      const btState = await this.manager.state();
      if (btState === State.PoweredOn) {
        await this._startScan(RECONNECT_SCAN_TIMEOUT_MS);
      } else {
        this._scheduleReconnect();
      }
    }, delay);
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  private _setStatus(s: PolarStatus): void {
    this._status = s;
    this._statusListeners.forEach((fn) => fn(s));
  }

  private _clearTimers(): void {
    if (this.flushTimer)      { clearInterval(this.flushTimer);   this.flushTimer      = null; }
    if (this.reconnectTimer)  { clearTimeout(this.reconnectTimer); this.reconnectTimer  = null; }
    if (this.scanTimeout)     { clearTimeout(this.scanTimeout);    this.scanTimeout     = null; }
    if (this._noSignalTimer)  { clearTimeout(this._noSignalTimer); this._noSignalTimer  = null; }
    if (this._batteryTimer)   { clearInterval(this._batteryTimer); this._batteryTimer   = null; }
  }

  private _setBatteryPct(pct: number | null): void {
    this._batteryPct = pct;
    this._batteryListeners.forEach((fn) => fn(pct));
  }

  private async _readBatteryLevel(dev: Device): Promise<void> {
    const c = await dev.readCharacteristicForService(BATTERY_SERVICE, BATTERY_LEVEL);
    const v = c?.value;
    if (!v) return;
    const bytes = base64.toByteArray(v);
    const pct = bytes?.length ? Number(bytes[0]) : NaN;
    if (!Number.isFinite(pct)) return;
    this._setBatteryPct(Math.max(0, Math.min(100, pct)));
  }

  private async _startBatteryMonitoring(dev: Device): Promise<void> {
    // reconnect-safe clear
    this._batterySub?.remove();
    this._batterySub = null;
    if (this._batteryTimer) { clearInterval(this._batteryTimer); this._batteryTimer = null; }

    // Read once immediately
    try { await this._readBatteryLevel(dev); } catch {}

    // Try notifications; if they fail, fall back to polling.
    try {
      this._batterySub = dev.monitorCharacteristicForService(
        BATTERY_SERVICE,
        BATTERY_LEVEL,
        (_err, ch) => {
          const v = ch?.value;
          if (!v) return;
          try {
            const bytes = base64.toByteArray(v);
            const pct = bytes?.length ? Number(bytes[0]) : NaN;
            if (!Number.isFinite(pct)) return;
            this._setBatteryPct(Math.max(0, Math.min(100, pct)));
          } catch {}
        },
      );
    } catch {
      // ignore
    }

    // Backstop polling (battery rarely changes; keep it light)
    this._batteryTimer = setInterval(() => {
      this._readBatteryLevel(dev).catch(() => {});
    }, 10 * 60_000);
  }

  // ── Sleep / wake inference ────────────────────────────────────────────────
  /**
   * Called for every valid accepted beat. Maintains a rolling window of the last
   * SLEEP_STATS_WINDOW beats and runs the sleep-state machine.
   *
   * State transitions:
   *   background → sleep          : meanHR ≤ SLEEP_HR_THRESHOLD AND PPI CV < SLEEP_CV_THRESHOLD
   *                                 for SLEEP_CONFIRM_BEATS consecutive window evaluations,
   *                                 only when hour ≥ SLEEP_EARLIEST_HOUR (9 pm) or hour < 10.
   *   sleep → background          : meanHR > WAKE_HR_THRESHOLD OR CV > WAKE_CV_THRESHOLD
   *                                 for WAKE_CONFIRM_BEATS consecutive evaluations.
   */
  private _updateSleepState(hr_bpm: number, ppi_ms: number): void {
    // Maintain rolling window for HR + PPI stats
    this._sleepWindowBeats.push({ hr: hr_bpm, ppi: ppi_ms });
    if (this._sleepWindowBeats.length > SLEEP_STATS_WINDOW) {
      this._sleepWindowBeats.shift();
    }
    // Need a full window before making any inference
    if (this._sleepWindowBeats.length < SLEEP_STATS_WINDOW) return;

    const hrs    = this._sleepWindowBeats.map(b => b.hr);
    const ppis   = this._sleepWindowBeats.map(b => b.ppi);
    const meanHr  = hrs.reduce((a, v) => a + v, 0)  / hrs.length;
    const meanPpi = ppis.reduce((a, v) => a + v, 0) / ppis.length;
    const sdPpi   = Math.sqrt(ppis.reduce((sum, v) => sum + (v - meanPpi) ** 2, 0) / ppis.length);
    const cv      = meanPpi > 0 ? sdPpi / meanPpi : 1.0;

    if (this._sleepState === 'background') {
      // Time gate: only infer sleep in the overnight window (9 pm → 9:59 am)
      const hour = new Date().getHours();
      const inSleepWindow = hour >= SLEEP_EARLIEST_HOUR || hour < 10;

      if (inSleepWindow && meanHr <= SLEEP_HR_THRESHOLD && cv < SLEEP_CV_THRESHOLD) {
        this._sleepCandidateCount++;
        if (this._sleepCandidateCount >= SLEEP_CONFIRM_BEATS) {
          this._sleepState          = 'sleep';
          this._sleepCandidateCount = 0;
          this._wakeCandidateCount  = 0;
          log.debug(`[Polar] sleep onset detected — avgHR=${meanHr.toFixed(0)} CV=${cv.toFixed(3)}`);
        }
      } else {
        // Soft decrement: preserve partial progress rather than full reset
        this._sleepCandidateCount = Math.floor(this._sleepCandidateCount / 2);
      }
    } else if (this._sleepState === 'sleep') {
      // Exit sleep when HR or CV rises — user woke up, return to background
      if (meanHr > WAKE_HR_THRESHOLD || cv > WAKE_CV_THRESHOLD) {
        this._wakeCandidateCount++;
        if (this._wakeCandidateCount >= WAKE_CONFIRM_BEATS) {
          this._sleepState          = 'background';
          this._wakeCandidateCount  = 0;
          this._sleepCandidateCount = 0;
          log.debug(`[Polar] wake detected — sleep→background avgHR=${meanHr.toFixed(0)} CV=${cv.toFixed(3)}`);
        }
      } else {
        this._wakeCandidateCount = Math.floor(this._wakeCandidateCount / 2);
      }
    }
  }
}

// ── Singleton export ──────────────────────────────────────────────────────────

export const polarService = new PolarService();
