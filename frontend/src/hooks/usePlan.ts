import { getClient } from '../api/client';
import { AppState } from 'react-native';
import { useState, useCallback, useEffect, useRef } from 'react';
import type { DailyPlan } from '../types';

type UsePlanOptions = {
  enabled?: boolean;
  pollIntervalMs?: number;
};

export const usePlan = (opts?: UsePlanOptions) => {
  const enabled = opts?.enabled ?? true;
  const pollIntervalMs = opts?.pollIntervalMs ?? 300_000;
  const [data, setData] = useState<DailyPlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inflight = useRef<Promise<void> | null>(null);
  const lastFetchedAt = useRef<number>(0);

  const fetchPlan = useCallback(async () => {
    if (!enabled) return;
    // Collapse concurrent callers into one request
    if (inflight.current) return inflight.current;

    const p = (async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getClient().get('/plan/today');
      setData((res.data ?? null) as DailyPlan | null);
      lastFetchedAt.current = Date.now();
    } catch (err: any) {
      setError(err.message || 'Unknown error');
    } finally {
      setLoading(false);
    }
    })();

    inflight.current = p;
    try {
      await p;
    } finally {
      inflight.current = null;
    }
    // NOTE: `enabled` is included in the deps so toggling the option from
    // false → true rebuilds the callback and the fetch actually runs.
  }, [enabled]);

  const confirmItem = useCallback(async (id: string) => {
    try {
      await getClient().patch(`/plan/items/${id}/complete`);
      await fetchPlan();
    } catch (err: any) {
      setError(err.message || 'Unknown error');
    }
  }, [fetchPlan]);

  useEffect(() => {
    if (!enabled) return;
    fetchPlan();
  }, [enabled, fetchPlan]);

  useEffect(() => {
    if (!enabled) return;
    if (!pollIntervalMs) return;

    let cancelled = false;
    const tick = () => {
      if (cancelled) return;
      if (AppState.currentState !== 'active') return;
      // Avoid pointless refreshes if something else already refreshed very recently
      if (Date.now() - lastFetchedAt.current < Math.min(45_000, pollIntervalMs / 2)) return;
      fetchPlan();
    };

    const id = setInterval(tick, pollIntervalMs);
    const sub = AppState.addEventListener('change', st => {
      if (st === 'active') tick();
    });
    return () => {
      cancelled = true;
      clearInterval(id);
      sub.remove();
    };
  }, [enabled, pollIntervalMs, fetchPlan]);

  return { plan: data, loading, error, refreshPlan: fetchPlan, confirmItem };
};
