import { getClient } from './client';
import { wrap, type W } from './core';
import type { NotificationFeedResponse } from '../types';

export async function getNotificationFeed(
  params?: { limit?: number; cursor?: string; since?: string },
): Promise<W<NotificationFeedResponse>> {
  const r = await getClient().get<NotificationFeedResponse>('/v1/notifications/feed', {
    params: {
      limit: params?.limit ?? 20,
      cursor: params?.cursor,
      since: params?.since,
      _: Date.now(),
    },
  });
  return wrap({
    items: r.data?.items ?? [],
    next_cursor: r.data?.next_cursor ?? null,
    server_time: r.data?.server_time ?? new Date().toISOString(),
  });
}

export async function dismissNotification(notificationId: string): Promise<void> {
  await getClient().post('/v1/notifications/dismiss', { notification_id: notificationId });
}

export async function registerDeviceToken(token: string, platform?: string): Promise<void> {
  await getClient().post('/v1/notifications/device-token', {
    token,
    platform: platform ?? undefined,
  });
}

