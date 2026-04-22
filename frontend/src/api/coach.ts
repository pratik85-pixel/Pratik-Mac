import { getClient } from './client';
import { wrap, type W } from './core';
import type {
  CoachReply,
  ConversationTurn,
  MorningBriefResponse,
  YesterdaySummaryResponse,
} from '../types';

export async function getMorningBrief(): Promise<W<MorningBriefResponse | null>> {
  try {
    const r = await getClient().get<MorningBriefResponse>('/coach/morning-brief', {
      params: { _: Date.now() },
    });
    return wrap(r.data);
  } catch {
    return wrap(null);
  }
}

export async function getYesterdaySummary(): Promise<
  W<YesterdaySummaryResponse | null>
> {
  try {
    const r = await getClient().get<YesterdaySummaryResponse>(
      '/coach/yesterday-summary',
      { params: { _: Date.now() } },
    );
    return wrap(r.data);
  } catch {
    return wrap(null);
  }
}

export async function getNudge(): Promise<W<{ message: string; nudge?: string }>> {
  const r = await getClient().get('/coach/nudge');
  return wrap(r.data);
}

export async function sendConversationTurn(
  message: string,
  conversationId?: string,
): Promise<W<CoachReply>> {
  const r = await getClient().post<CoachReply>('/coach/conversation', {
    message,
    conversation_id: conversationId ?? null,
  });
  return wrap(r.data);
}

export async function getConversationHistory(): Promise<W<{
  turns: ConversationTurn[];
  conversation_id?: string;
}>> {
  const r = await getClient().get<any>('/coach/conversation/history');
  const turns: ConversationTurn[] = r.data?.turns ?? (Array.isArray(r.data) ? r.data : []);
  return wrap({ turns, conversation_id: r.data?.conversation_id as string | undefined });
}

export async function closeConversation(conversationId: string): Promise<void> {
  await getClient().delete(`/coach/conversation/${conversationId}`);
}

