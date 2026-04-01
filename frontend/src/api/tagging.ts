import { getClient } from './client';
import { wrap, type W } from './core';
import type { TagHistoryItem, NudgeWindow } from '../types';

// tagWindow accepts an object so call-sites can use named fields.
export interface TagWindowArgs {
  window_id: string;
  window_type: 'stress' | 'recovery';
  tag: string;
}

export async function tagWindow(args: TagWindowArgs): Promise<void> {
  await getClient().post('/tagging/tag', {
    window_id: args.window_id,
    window_type: args.window_type,
    slug: args.tag,
  });
}

export async function getTagHistory(limit: number = 20): Promise<W<TagHistoryItem[]>> {
  const r = await getClient().get<any>('/tagging/tags', { params: { limit } });
  const tags: TagHistoryItem[] = r.data?.tags ?? (Array.isArray(r.data) ? r.data : []);
  return wrap(tags);
}

export async function getNudgeWindows(): Promise<W<NudgeWindow[]>> {
  const r = await getClient().get<any>('/tagging/nudge');
  const windows: NudgeWindow[] =
    r.data?.nudge_queue
    ?? r.data?.windows
    ?? (Array.isArray(r.data) ? r.data : []);
  return wrap(windows);
}

