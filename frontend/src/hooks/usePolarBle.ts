import { getUserId } from '../store/auth';
/**
 * usePolarBle.ts
 *
 * React hook that wraps the PolarService singleton.
 * Handles Android runtime BLE permissions and exposes reactive state.
 *
 * Usage:
 *   const { status, deviceName, beatsToday } = usePolarBle(hasUser);
 */

import { useEffect, useRef, useState } from 'react';
import { Platform, PermissionsAndroid } from 'react-native';
import { polarService, type PolarStatus } from '../services/PolarService';

export interface PolarBleState {
  status:      PolarStatus;
  deviceName:  string | null;
  beatsToday:  number;
  liveHr:      number | null;
}

/**
 * @param enabled – only starts scanning when true (pass `hasUser` from App state)
 */
export function usePolarBle(enabled: boolean): PolarBleState {
  const [status, setStatus]         = useState<PolarStatus>(polarService.status);
  const [deviceName, setDeviceName] = useState<string | null>(polarService.deviceName);
  const [beatsToday, setBeatsToday] = useState(0);
  const [liveHr, setLiveHr]         = useState<number | null>(null);
  const started = useRef(false);
  const beatCountRef = useRef(0);
  const liveHrRef = useRef<number | null>(null);
  const uiTickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!enabled) return;
    if (started.current) return;
    started.current = true;

    async function init() {
      // Android 12+ needs BLUETOOTH_SCAN + BLUETOOTH_CONNECT at runtime.
      // Android < 12 needs ACCESS_FINE_LOCATION.
      if (Platform.OS === 'android') {
        await requestAndroidBlePermissions();
      }

      polarService.subscribeStatus((s) => {
        setStatus(s);
        setDeviceName(polarService.deviceName);
      });

      polarService.subscribeBeat((_ppi, hr) => {
        beatCountRef.current += 1;
        if (hr > 0) liveHrRef.current = hr;
      });

      // Throttle UI updates: keep per-beat collection, but update React state
      // at a fixed cadence to reduce renders and CPU usage.
      uiTickRef.current = setInterval(() => {
        setBeatsToday(beatCountRef.current);
        setLiveHr(liveHrRef.current);
      }, 1_000);

      await polarService.start();
    }

    init().catch((e) => console.warn('[usePolarBle] init error:', e));

    return () => {
      // Don't stop the service on unmount — it's a background singleton.
      // Callbacks are intentionally kept registered (singleton lifecycle).
      if (uiTickRef.current) {
        clearInterval(uiTickRef.current);
        uiTickRef.current = null;
      }
    };
  }, [enabled]);

  return { status, deviceName, beatsToday, liveHr };
}

// ── Android permissions ───────────────────────────────────────────────────────

async function requestAndroidBlePermissions(): Promise<void> {
  const api = Platform.Version as number;

  if (api >= 31) {
    // Android 12+ (API 31+)
    await PermissionsAndroid.requestMultiple([
      PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN,
      PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT,
    ]);
  } else {
    // Android < 12: BLE scanning requires location permission
    await PermissionsAndroid.request(
      PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION,
    );
  }
}
