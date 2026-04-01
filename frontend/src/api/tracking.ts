import { getClient } from './client';
import { wrap, type W } from './core';
import type {
  DailySummaryResponse,
  WaveformPoint,
  StressWindow,
  RecoveryWindow,
  StressStateResponse,
  MorningRecapResponse,
} from '../types';

export async function getToday(): Promise<W<DailySummaryResponse>> {
  const r = await getClient().get<DailySummaryResponse>('/tracking/daily-summary', {
    params: { _: Date.now() },
  });
  return wrap(r.data);
}

export async function getDailySummary(date: string): Promise<W<DailySummaryResponse>> {
  const r = await getClient().get<DailySummaryResponse>(`/tracking/daily-summary/${date}`);
  return wrap(r.data);
}

export async function getWaveform(date: string): Promise<W<WaveformPoint[]>> {
  const r = await getClient().get<WaveformPoint[]>(`/tracking/waveform/${date}`, {
    params: { _: Date.now() },
  });
  return wrap(r.data ?? []);
}

export async function getStressWindows(date: string): Promise<W<StressWindow[]>> {
  const r = await getClient().get<StressWindow[]>(`/tracking/stress-windows/${date}`, {
    params: { _: Date.now() },
  });
  return wrap(r.data ?? []);
}

export async function getRecoveryWindows(date: string): Promise<W<RecoveryWindow[]>> {
  const r = await getClient().get<RecoveryWindow[]>(`/tracking/recovery-windows/${date}`, {
    params: { _: Date.now() },
  });
  return wrap(r.data ?? []);
}

export async function getHistory(days: number = 14): Promise<W<DailySummaryResponse[]>> {
  const r = await getClient().get<any>('/tracking/history', { params: { days } });
  const arr: DailySummaryResponse[] = r.data?.history ?? (Array.isArray(r.data) ? r.data : []);
  return wrap(arr);
}

/** Live stress zone + trend (readiness UX). Returns null if route missing or error. */
export async function getStressState(includeCohort = false): Promise<W<StressStateResponse | null>> {
  try {
    const r = await getClient().get<StressStateResponse>('/tracking/stress-state', {
      params: { include_cohort: includeCohort },
    });
    return wrap(r.data);
  } catch {
    return wrap(null);
  }
}

export async function getMorningRecap(): Promise<W<MorningRecapResponse | null>> {
  try {
    const r = await getClient().get<MorningRecapResponse>('/tracking/morning-recap', {
      params: { _: Date.now() },
    });
    return wrap(r.data);
  } catch {
    return wrap(null);
  }
}

export async function ackMorningRecap(forDate: string): Promise<void> {
  await getClient().post('/tracking/morning-recap/ack', { for_date: forDate });
}

