import { getClient } from './client';
import { wrap, type W } from './core';
import type { DailyPlan, PlanHomeStatus } from '../types';

/** Plan headline for Home (anchor + adherence). */
export async function getPlanHomeStatus(): Promise<W<PlanHomeStatus | null>> {
  try {
    const r = await getClient().get<PlanHomeStatus>('/plan/home-status', {
      params: { _: Date.now() },
    });
    return wrap(r.data);
  } catch {
    return wrap(null);
  }
}

export async function getTodayPlan(): Promise<W<DailyPlan | null>> {
  try {
    const r = await getClient().get<DailyPlan>('/plan/today', {
      params: { _: Date.now() },
    });
    return wrap(r.data);
  } catch {
    return wrap(null);
  }
}

export async function submitCheckIn(
  reactivity: number,
  focus: number,
  recovery: number,
): Promise<void> {
  await getClient().post('/plan/check-in', { reactivity, focus, recovery });
}

export async function triggerTodayPlan(): Promise<W<any>> {
  const r = await getClient().post<any>('/plan/trigger-today');
  return wrap(r.data);
}

export async function markPlanItemComplete(itemId: string): Promise<void> {
  await getClient().patch(`/plan/items/${itemId}/complete`);
}

