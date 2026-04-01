import { getClient } from './client';
import { wrap, type W } from './core';
import type { UserProfile, ArchetypeProfile, Fingerprint } from '../types';

export async function getUserProfile(): Promise<W<UserProfile>> {
  const r = await getClient().get<UserProfile>('/user/profile');
  return wrap(r.data);
}

export async function getArchetype(): Promise<W<ArchetypeProfile>> {
  const r = await getClient().get<ArchetypeProfile>('/user/archetype');
  return wrap(r.data);
}

export async function getFingerprint(): Promise<W<Fingerprint | null>> {
  try {
    const r = await getClient().get<Fingerprint>('/user/fingerprint');
    return wrap(r.data);
  } catch {
    return wrap(null);
  }
}

export async function getHabits(): Promise<W<any>> {
  const r = await getClient().get('/user/habits');
  return wrap(r.data);
}

export async function updateHabits(habits: Record<string, any>): Promise<void> {
  await getClient().put('/user/habits', habits);
}

