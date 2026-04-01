import { getClient } from './client';
import { wrap, type W } from './core';

export interface SessionHistoryItem {
  session_id:       string;
  started_at:       string;
  ended_at:         string | null;
  duration_minutes: number | null;
  practice_type:    string | null;
  session_score:    number | null;
  coherence_avg:    number | null;
  is_open:          boolean;
}

export async function getCurrentSession(): Promise<W<SessionHistoryItem | null>> {
  const r = await getClient().get<{ session: SessionHistoryItem | null }>('/session/current');
  return wrap(r.data.session);
}

export async function getSessionHistory(limit: number = 20): Promise<W<SessionHistoryItem[]>> {
  const r = await getClient().get<SessionHistoryItem[]>('/session/history', { params: { limit } });
  return wrap(r.data ?? []);
}

export async function endSession(sessionId: string): Promise<W<any>> {
  const r = await getClient().post<any>(`/session/${sessionId}/end`, {});
  return wrap(r.data);
}

export interface StartSessionResponse {
  session_id:       string;
  practice_type:    string;
  pacer:            Record<string, unknown> | null;
  duration_minutes: number;
  gates_required:   boolean;
  prf_target_bpm:   number | null;
  session_notes:    string[];
  tier:             number;
}

export interface StartSessionParams {
  prf_status?:       string;   // \"PRF_UNKNOWN\" | \"PRF_FOUND\" | \"PRF_CONFIRMED\"
  stored_prf_bpm?:   number;
  session_type?:     string;   // \"full\" | \"rest\" | \"background\"
  load_score?:       number;   // 0.0–1.0
  attention_anchor?: string;   // \"heart\" | \"belly\" | ...
  duration_minutes?: number;
}

export async function startSession(params: StartSessionParams = {}): Promise<W<StartSessionResponse>> {
  const r = await getClient().post<StartSessionResponse>('/session/start', params);
  return wrap(r.data);
}

