import { getClient } from './client';
import { wrap, type W } from './core';

export interface BandSessionSummary {
  id:               string;
  started_at:       string;
  ended_at:         string | null;
  is_closed:        boolean;
  duration_minutes: number | null;
  stress_pct:       number | null;
  recovery_pct:     number | null;
  net_balance:      number | null;
  has_sleep_data:   boolean;
  opening_balance:  number;
  avg_rmssd_ms:     number | null;
  avg_hr_bpm:       number | null;
}

export interface BandSessionStressEvent {
  window_id:    string;
  window_start: string;
  rmssd_ms:     number | null;
  hr_bpm:       number | null;
  tag:          string | null;
}

export interface BandSessionRecoveryEvent {
  window_id:    string;
  window_start: string;
  rmssd_ms:     number | null;
  hr_bpm:       number | null;
}

export interface PersonalBaseline {
  rmssd_avg:  number | null;
  rmssd_ceil: number | null;
  hr_floor:   number | null;
}

export interface BandSessionMetrics {
  stress_events:    BandSessionStressEvent[];
  recovery_events:  BandSessionRecoveryEvent[];
  rmssd_sparkline:  number[];
  personal:         PersonalBaseline;
}

export interface BandSessionPlanItem {
  item_id:      string;
  title:        string;
  priority:     string;
  completed_at: string;
}

export interface BandSessionPlan {
  items:          BandSessionPlanItem[];
  adherence_pct:  number | null;
  has_plan:       boolean;
}

export async function getBandSessionHistory(limit = 20): Promise<W<BandSessionSummary[]>> {
  const r = await getClient().get<BandSessionSummary[]>('/band-sessions/history', { params: { limit } });
  return wrap(r.data ?? []);
}

export async function getBandSessionMetrics(sessionId: string): Promise<W<BandSessionMetrics>> {
  const r = await getClient().get<BandSessionMetrics>(`/band-sessions/${sessionId}/metrics`);
  return wrap(r.data);
}

export async function getBandSessionPlan(sessionId: string): Promise<W<BandSessionPlan>> {
  const r = await getClient().get<BandSessionPlan>(`/band-sessions/${sessionId}/plan`);
  return wrap(r.data);
}

