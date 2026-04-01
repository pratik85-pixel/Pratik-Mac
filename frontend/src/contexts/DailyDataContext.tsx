/**
 * DailyDataContext
 *
 * Single source of truth for today's live data across all Home-stack screens.
 * Replaces three independent polling loops (HomeScreen 60s, StressWindows 5m,
 * RecoveryWindows 5m) with one shared fetch + single 60-second cycle.
 *
 * Foreground detection: fires an immediate refresh when the user returns to the
 * app after it was backgrounded (e.g. opened after 2 hours).
 */

import React, {
  createContext,
  useContext,
  useCallback,
  useEffect,
  useRef,
  useMemo,
  useReducer,
} from 'react';
import { AppState, AppStateStatus } from 'react-native';
import {
  getToday,
  getStressWindows,
  getRecoveryWindows,
  getWaveform,
  getStressState,
  getMorningRecap,
} from '../api/tracking';
import { getMorningBrief } from '../api/coach';
import { getPlanHomeStatus } from '../api/plan';
import type {
  DailySummaryResponse,
  StressWindow,
  RecoveryWindow,
  WaveformPoint,
  StressStateResponse,
  MorningRecapResponse,
  MorningBriefResponse,
  PlanHomeStatus,
} from '../types';
import { polarService } from '../services/PolarService';

// ─── helpers ──────────────────────────────────────────────────────────────────

function safeFallbackDayKey(): string {
  // Last-resort fallback only. In normal operation we derive the day key from
  // /tracking/daily-summary.summary_date (backend-local day boundary).
  return new Date().toISOString().split('T')[0];
}

// ─── context shape ────────────────────────────────────────────────────────────

interface DailyDataState {
  summary:         DailySummaryResponse | null;
  stressWindows:   StressWindow[];
  recoveryWindows: RecoveryWindow[];
  waveform:        WaveformPoint[];
  /** Live zone + trend from GET /tracking/stress-state */
  stressState:     StressStateResponse | null;
  morningRecap:    MorningRecapResponse | null;
  morningBrief:    MorningBriefResponse | null;
  planHome:        PlanHomeStatus | null;
  loading:         boolean;
  error:           string | null;
  /** Refetch daily data. Pass `{ clearCoach: true }` on pull-to-refresh to drop stale coach/plan before fetch. */
  refresh:         (opts?: { clearCoach?: boolean }) => Promise<void>;
  /** Patch a single stress window in-place (e.g. after user confirms a tag). */
  patchStressWindow: (id: string, patch: Partial<StressWindow>) => void;
}

const DailyDataContext = createContext<DailyDataState>({
  summary: null,
  stressWindows: [],
  recoveryWindows: [],
  waveform: [],
  stressState: null,
  morningRecap: null,
  morningBrief: null,
  planHome: null,
  loading: false,
  error: null,
  refresh: async () => {},
  patchStressWindow: () => {},
});

// ─── provider ─────────────────────────────────────────────────────────────────

export function DailyDataProvider({ children }: { children: React.ReactNode }) {
  type DataOnly = Omit<DailyDataState, 'refresh' | 'patchStressWindow'>;

  const initial: DataOnly = {
    summary: null,
    stressWindows: [],
    recoveryWindows: [],
    waveform: [],
    stressState: null,
    morningRecap: null,
    morningBrief: null,
    planHome: null,
    loading: false,
    error: null,
  };

  type Action =
    | { type: 'fetch_start'; clearCoach?: boolean }
    | { type: 'fetch_finish'; next: Partial<DataOnly> }
    | { type: 'patch_stress_window'; id: string; patch: Partial<StressWindow> };

  function reducer(state: DataOnly, action: Action): DataOnly {
    if (action.type === 'fetch_start') {
      return {
        ...state,
        loading: true,
        error: null,
        ...(action.clearCoach ? { morningBrief: null, planHome: null } : null),
      };
    }
    if (action.type === 'fetch_finish') {
      return {
        ...state,
        ...action.next,
        loading: false,
      };
    }
    if (action.type === 'patch_stress_window') {
      return {
        ...state,
        stressWindows: state.stressWindows.map((w) =>
          w.id === action.id ? { ...w, ...action.patch } : w,
        ),
      };
    }
    return state;
  }

  const [data, dispatch] = useReducer(reducer, initial);

  /** Monotonic id so overlapping fetches don't apply stale results after a newer refresh. */
  const fetchSeq = useRef(0);

  const fetchAll = useCallback(async (opts?: { clearCoach?: boolean }) => {
    const seq = ++fetchSeq.current;
    dispatch({ type: 'fetch_start', clearCoach: opts?.clearCoach });

    try {
      // Fetch the backend-derived day key first, then use it for date-scoped endpoints.
      const sumRes = await Promise.allSettled([getToday()]);
      const sum = sumRes[0];
      const summary = sum.status === 'fulfilled' ? (sum.value.data ?? null) : null;
      const dayKey = summary?.summary_date ?? safeFallbackDayKey();

      const [swRes, rwRes, wvRes, ssRes, mrRes, mbRes, phRes] = await Promise.allSettled([
        getStressWindows(dayKey),
        getRecoveryWindows(dayKey),
        getWaveform(dayKey),
        getStressState(false),
        getMorningRecap(),
        getMorningBrief(),
        getPlanHomeStatus(),
      ]);

      if (seq !== fetchSeq.current) return;

      const next: Partial<DataOnly> = {};

      if (sum.status === 'fulfilled') {
        next.summary = summary;
      } else {
        const err = (sum as any).reason;
        if (err?.response?.status !== 404) {
          next.error = err?.message ?? 'Failed to load summary';
        } else {
          next.summary = null;
        }
      }

      next.stressWindows = swRes.status === 'fulfilled' ? (swRes.value.data ?? []) : [];
      next.recoveryWindows = rwRes.status === 'fulfilled' ? (rwRes.value.data ?? []) : [];
      next.waveform = wvRes.status === 'fulfilled' ? (wvRes.value.data ?? []) : [];
      next.stressState = ssRes.status === 'fulfilled' ? (ssRes.value.data ?? null) : null;
      next.morningRecap = mrRes.status === 'fulfilled' ? (mrRes.value.data ?? null) : null;
      next.morningBrief = mbRes.status === 'fulfilled' ? (mbRes.value.data ?? null) : null;
      next.planHome = phRes.status === 'fulfilled' ? (phRes.value.data ?? null) : null;

      dispatch({ type: 'fetch_finish', next });
    } finally {
      // loading is cleared by fetch_finish when results apply; keep current state on stale fetches
    }
  }, []);

  const refresh = useCallback((opts?: { clearCoach?: boolean }) => {
    return fetchAll(opts);
  }, [fetchAll]);

  // Initial fetch
  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  // Poll at a calmer cadence; still refresh on app foreground and flush events.
  useEffect(() => {
    const id = setInterval(fetchAll, 60_000);
    return () => clearInterval(id);
  }, [fetchAll]);

  // Foreground detection: immediate refresh when app becomes active.
  // The subscribeFlush listener below handles the authoritative post-flush update;
  // this fires first as a fast refresh for any scores already on the backend.
  useEffect(() => {
    let lastState: AppStateStatus = AppState.currentState;

    const sub = AppState.addEventListener('change', (nextState: AppStateStatus) => {
      if (lastState !== 'active' && nextState === 'active') {
        fetchAll();
      }
      lastState = nextState;
    });

    return () => sub.remove();
  }, [fetchAll]);

  // Score refresh triggered by beat flush completion.
  // Fires immediately after beats land on the backend (flush POST succeeds),
  // ensuring the displayed scores reflect the just-processed data without
  // waiting for the 60-second polling interval.
  useEffect(() => {
    const unsub = polarService.subscribeFlush(() => {
      fetchAll();
    });
    return unsub;
  }, [fetchAll]);

  const patchStressWindow = useCallback((id: string, patch: Partial<StressWindow>) => {
    dispatch({ type: 'patch_stress_window', id, patch });
  }, []);

  const value = useMemo<DailyDataState>(() => ({
    summary: data.summary,
    stressWindows: data.stressWindows,
    recoveryWindows: data.recoveryWindows,
    waveform: data.waveform,
    stressState: data.stressState,
    morningRecap: data.morningRecap,
    morningBrief: data.morningBrief,
    planHome: data.planHome,
    loading: data.loading,
    error: data.error,
    refresh,
    patchStressWindow,
  }), [data, refresh, patchStressWindow]);

  return (
    <DailyDataContext.Provider
      value={value}
    >
      {children}
    </DailyDataContext.Provider>
  );
}

// ─── hook ─────────────────────────────────────────────────────────────────────

export function useDailyData(): DailyDataState {
  return useContext(DailyDataContext);
}
