import { AppState, AppStateStatus, Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import Constants from 'expo-constants';
import { getNotificationFeed, registerDeviceToken } from '../api/notifications';

const SEEN_NOTIFICATION_IDS_KEY = 'seen_notification_ids_v1';
const POLL_MS = 60_000;

class NotificationService {
  private started = false;
  private timer: ReturnType<typeof setInterval> | null = null;
  private appStateSub: { remove: () => void } | null = null;
  private seen = new Set<string>();
  private seenLoaded = false;
  private notificationsModule: any | null = null;
  private notificationsUnavailable = false;
  private pollInFlight = false;
  private bootstrapped = false;

  private getNotificationsModule(): any | null {
    if (this.notificationsUnavailable) return null;
    if (this.notificationsModule) return this.notificationsModule;
    try {
      // Lazy-require avoids startup crash on binaries built without expo-notifications.
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      this.notificationsModule = require('expo-notifications');
      return this.notificationsModule;
    } catch (e) {
      this.notificationsUnavailable = true;
      console.warn('[Notifications] expo-notifications native module unavailable; skipping alerts');
      return null;
    }
  }

  async start() {
    if (this.started) return;
    this.started = true;

    const Notifications = this.getNotificationsModule();
    if (!Notifications) return;

    Notifications.setNotificationHandler({
      handleNotification: async (notification: any) => {
        const triggerType = notification?.request?.trigger?.type;
        const isForegroundPush = AppState.currentState === 'active' && triggerType === 'push';
        // Prevent duplicate foreground alerts for the same event:
        // push (server) + local poll notification.
        if (isForegroundPush) {
          return {
            shouldShowAlert: false,
            shouldShowBanner: false,
            shouldShowList: false,
            shouldPlaySound: false,
            shouldSetBadge: false,
          };
        }
        return {
          shouldShowAlert: true,
          shouldShowBanner: true,
          shouldShowList: true,
          shouldPlaySound: true,
          shouldSetBadge: false,
        };
      },
    });

    await this.ensureSeenLoaded();
    await this.registerPushTokenBestEffort();
    await this.pollFeedAndNotify();

    this.timer = setInterval(() => {
      void this.pollFeedAndNotify();
    }, POLL_MS);

    this.appStateSub = AppState.addEventListener('change', (next: AppStateStatus) => {
      if (next === 'active') void this.pollFeedAndNotify();
    });
  }

  stop() {
    this.started = false;
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.appStateSub?.remove();
    this.appStateSub = null;
    this.bootstrapped = false;
  }

  private async ensureSeenLoaded() {
    if (this.seenLoaded) return;
    this.seenLoaded = true;
    try {
      const raw = await AsyncStorage.getItem(SEEN_NOTIFICATION_IDS_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      if (Array.isArray(parsed)) {
        parsed.forEach((id) => {
          if (typeof id !== 'string') return;
          const v = id.trim();
          if (!v) return;
          // Backward compatibility: old cache stored plain notification IDs.
          if (v.startsWith('k:') || v.startsWith('id:')) {
            this.seen.add(v);
            return;
          }
          this.seen.add(`id:${v}`);
        });
      }
    } catch {}
  }

  private async persistSeen() {
    try {
      const list = Array.from(this.seen).slice(-400);
      await AsyncStorage.setItem(SEEN_NOTIFICATION_IDS_KEY, JSON.stringify(list));
    } catch {}
  }

  private async registerPushTokenBestEffort() {
    const Notifications = this.getNotificationsModule();
    if (!Notifications) return;
    try {
      const perm = await Notifications.getPermissionsAsync();
      let granted = perm.granted || perm.ios?.status === Notifications.IosAuthorizationStatus.PROVISIONAL;
      if (!granted) {
        const req = await Notifications.requestPermissionsAsync();
        granted = req.granted || req.ios?.status === Notifications.IosAuthorizationStatus.PROVISIONAL;
      }
      if (!granted) return;

      const projectId =
        Constants.expoConfig?.extra?.eas?.projectId
        ?? Constants.easConfig?.projectId
        ?? undefined;
      const tokenRes = await Notifications.getExpoPushTokenAsync(projectId ? { projectId } : undefined);
      const token = tokenRes?.data;
      if (!token) return;
      await registerDeviceToken(token, Platform.OS);
    } catch (e) {
      console.warn('[Notifications] token registration failed', e);
    }
  }

  private async pollFeedAndNotify() {
    if (this.pollInFlight) return;
    this.pollInFlight = true;
    const Notifications = this.getNotificationsModule();
    try {
      const res = await getNotificationFeed({ limit: 30 });
      const items = res.data?.items ?? [];
      const keyOf = (it: any): string => {
        const dedupe = String(it?.dedupe_key ?? '').trim();
        if (dedupe) return `k:${dedupe}`;
        const id = String(it?.id ?? '').trim();
        return id ? `id:${id}` : '';
      };
      if (!this.bootstrapped) {
        // First successful poll should establish baseline only.
        // Do not alert for historical unread backlog on app refresh/restart.
        items.forEach((it) => {
          const key = keyOf(it);
          if (key) this.seen.add(key);
        });
        this.bootstrapped = true;
        await this.persistSeen();
        return;
      }
      const fresh = items.filter((it) => {
        const key = keyOf(it);
        return key.length > 0 && !this.seen.has(key);
      });
      if (fresh.length === 0) return;

      // Mark seen before scheduling so retries do not spam.
      fresh.forEach((it) => {
        const key = keyOf(it);
        if (key) this.seen.add(key);
      });
      await this.persistSeen();

      // Local alert pipeline (v2): visible while app is running.
      if (Notifications && AppState.currentState === 'active') {
        for (const it of [...fresh].reverse()) {
          await Notifications.scheduleNotificationAsync({
            content: {
              title: it.title || 'ZenFlow',
              body: it.body || 'You have a new notification.',
              data: {
                notification_id: it.id,
                deeplink: it.deeplink ?? undefined,
                category: it.category,
              },
            },
            trigger: null,
          });
        }
      }
    } catch (e) {
      console.warn('[Notifications] feed poll failed', e);
    } finally {
      this.pollInFlight = false;
    }
  }
}

export const notificationService = new NotificationService();
