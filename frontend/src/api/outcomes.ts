import { getClient } from './client';
import { wrap, type W } from './core';
import type { ReportCard } from '../types';

export async function getReportCard(): Promise<W<ReportCard>> {
  const r = await getClient().get<ReportCard>('/outcomes/report-card');
  return wrap(r.data);
}

