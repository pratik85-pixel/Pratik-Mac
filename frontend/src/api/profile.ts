import { getClient } from './client';
import { wrap, type W } from './core';
import type { UnifiedProfile, UserFact } from '../types';

export async function getUnifiedProfile(): Promise<W<UnifiedProfile>> {
  const r = await getClient().get<UnifiedProfile>('/profile/unified');
  return wrap(r.data);
}

export async function getFacts(): Promise<W<UserFact[]>> {
  const r = await getClient().get<any>('/profile/facts');
  const facts: UserFact[] = r.data?.facts ?? (Array.isArray(r.data) ? r.data : []);
  return wrap(facts);
}

export async function rebuildProfile(): Promise<void> {
  await getClient().post('/profile/rebuild');
}

