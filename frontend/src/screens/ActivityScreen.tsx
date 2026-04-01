import React, { useCallback, useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, ScrollView, RefreshControl, SectionList,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import {
  ZEN,
  ZenScreen,
  SectionCard,
  SectionEyebrow,
} from '../ui/zenflow-ui-kit';
import EmptyState from '../components/EmptyState';
import {
  dismissNotification,
  getNotificationFeed,
} from '../api/notifications';
import { getNudgeWindows, getTagHistory } from '../api/tagging';
import { getTodayPlan } from '../api/plan';
import type { NudgeWindow, TagHistoryItem, DailyPlan, PlanItem, NotificationFeedItem } from '../types';

type ActivityType = 'all' | 'notification' | 'trigger' | 'nudge' | 'completion' | 'checkin' | 'recovery';
type ActivityItem = {
  id: string;
  title: string;
  time: string;
  subTime: string;
  icon: string;
  type: Exclude<ActivityType, 'all'>;
  ts: number;
  notificationId?: string;
  dismissible?: boolean;
};

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '--:--';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '--:--';
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
}

function tagLabel(tag: string | null | undefined): string {
  if (!tag) return 'Stress Trigger';
  return tag.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function ActivityScreen() {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<ActivityType>('all');
  const [tags, setTags] = useState<TagHistoryItem[]>([]);
  const [nudges, setNudges] = useState<NudgeWindow[]>([]);
  const [plan, setPlan] = useState<DailyPlan | null>(null);
  const [notifications, setNotifications] = useState<NotificationFeedItem[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [feedRes, tagRes, nudgeRes, planRes] = await Promise.allSettled([
        getNotificationFeed({ limit: 30 }),
        getTagHistory(40),
        getNudgeWindows(),
        getTodayPlan(),
      ]);
      if (feedRes.status === 'fulfilled') setNotifications(feedRes.value.data?.items ?? []);
      if (tagRes.status === 'fulfilled') setTags(tagRes.value.data ?? []);
      if (nudgeRes.status === 'fulfilled') setNudges(nudgeRes.value.data ?? []);
      if (planRes.status === 'fulfilled') setPlan(planRes.value.data ?? null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const items = useMemo<ActivityItem[]>(() => {
    const out: ActivityItem[] = [];
    const seenIds = new Set<string>();
    const uniqueId = (base: string): string => {
      const root = base.trim().length > 0 ? base : 'activity-item';
      if (!seenIds.has(root)) {
        seenIds.add(root);
        return root;
      }
      let i = 1;
      let next = `${root}-${i}`;
      while (seenIds.has(next)) {
        i += 1;
        next = `${root}-${i}`;
      }
      seenIds.add(next);
      return next;
    };

    notifications.forEach((n, idx) => {
      const created = n.created_at ? new Date(n.created_at).getTime() : 0;
      const baseNotifId = n.id ?? `${n.category ?? 'notif'}-${created}-${idx}`;
      out.push({
        id: uniqueId(`notif-${baseNotifId}`),
        title: n.title || 'Notification',
        time: fmtTime(n.created_at),
        subTime: n.body ?? n.category ?? 'Unread',
        icon: n.category === 'event_trigger' ? '🔔' : n.category === 'check_in' ? '📝' : '💡',
        type: 'notification',
        ts: created || Date.now(),
        notificationId: n.id,
        dismissible: true,
      });
    });

    tags.forEach((t, idx) => {
      const isStress = t.window_type === 'stress';
      const baseTagId = t.id ?? `${t.window_type ?? 'tag'}-${t.started_at ?? 'na'}-${t.tag ?? 'untagged'}-${idx}`;
      out.push({
        id: uniqueId(`tag-${String(baseTagId)}`),
        title: isStress ? tagLabel(t.tag) : 'Recovery Event',
        time: fmtTime(t.started_at),
        subTime: isStress ? 'Peak stress' : 'Recovered',
        icon: isStress ? '⚡' : '🌿',
        type: isStress ? 'trigger' : 'recovery',
        ts: new Date(t.started_at).getTime() || 0,
      });
    });

    nudges.forEach((n, idx) => {
      const baseNudgeId = `${n.window_id ?? 'nudge'}-${n.started_at ?? 'na'}-${idx}`;
      out.push({
        id: uniqueId(`nudge-${baseNudgeId}`),
        title: 'Breathing Nudge',
        time: fmtTime(n.started_at),
        subTime: 'Suggested',
        icon: '🫁',
        type: 'nudge',
        ts: new Date(n.started_at).getTime() || 0,
      });
    });

    const planItems: PlanItem[] = plan?.items ?? [];
    planItems.filter((x) => x.has_evidence).forEach((p, idx) => {
      const basePlanId = p.id ?? `${p.title ?? 'plan'}-${p.target_start_time ?? p.target_end_time ?? 'na'}-${idx}`;
      out.push({
        id: uniqueId(`plan-${String(basePlanId)}`),
        title: p.title,
        time: fmtTime(p.target_end_time ?? p.target_start_time),
        subTime: 'Completed',
        icon: '✅',
        type: 'completion',
        ts: new Date(p.target_end_time ?? p.target_start_time ?? '').getTime() || 0,
      });
    });

    if (plan && plan.check_in_pending === false) {
      out.push({
        id: uniqueId('checkin-today'),
        title: 'Energy Check In',
        time: '--:--',
        subTime: 'Logged',
        icon: '📝',
        type: 'checkin',
        ts: Date.now() - 60_000,
      });
    }

    return out.sort((a, b) => b.ts - a.ts);
  }, [notifications, tags, nudges, plan]);

  const onTapItem = useCallback(async (item: ActivityItem) => {
    if (item.type !== 'notification' || !item.notificationId || !item.dismissible) return;
    try {
      await dismissNotification(item.notificationId);
      setNotifications(prev => prev.filter(n => n.id !== item.notificationId));
    } catch {}
  }, []);

  const filtered = useMemo(
    () => (filter === 'all' ? items : items.filter((i) => i.type === filter)),
    [items, filter],
  );

  const todayStart = new Date();
  todayStart.setHours(0, 0, 0, 0);
  const todayItems = filtered.filter((i) => i.ts >= todayStart.getTime());
  const earlierItems = filtered.filter((i) => i.ts < todayStart.getTime());

  const sections = useMemo(() => {
    const out: Array<{ title: string; data: ActivityItem[] }> = [];
    if (todayItems.length > 0) out.push({ title: 'Today', data: todayItems });
    if (earlierItems.length > 0) out.push({ title: 'Earlier', data: earlierItems });
    return out;
  }, [todayItems, earlierItems]);

  return (
    <ZenScreen scrollable={false}>
      <SectionList
        sections={sections}
        keyExtractor={(item) => item.id}
        stickySectionHeadersEnabled={false}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => { setRefreshing(true); load(); }}
            tintColor={ZEN.colors.readiness}
          />
        }
        ListHeaderComponent={
          <>
            <View style={s.headerRow}>
              <View>
                <SectionEyebrow>Activity</SectionEyebrow>
                <Text style={s.title}>Events & Nudges</Text>
              </View>
            </View>

            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.filterRow}>
              {[
                ['all', 'All'],
                ['notification', 'Inbox'],
                ['trigger', 'Triggers'],
                ['nudge', 'Nudges'],
                ['recovery', 'Recovery'],
                ['checkin', 'Check-ins'],
                ['completion', 'Completed'],
              ].map(([key, label]) => {
                const active = filter === key;
                return (
                  <TouchableOpacity
                    key={key}
                    onPress={() => setFilter(key as ActivityType)}
                    style={[s.tabPill, active && s.tabPillActive]}
                  >
                    <Text style={[s.tabPillText, active && s.tabPillTextActive]}>{label}</Text>
                  </TouchableOpacity>
                );
              })}
            </ScrollView>

            {loading ? (
              <View style={s.center}><ActivityIndicator color={ZEN.colors.readiness} /></View>
            ) : filtered.length === 0 ? (
              <EmptyState
                icon="notifications-outline"
                title="No activity yet"
                message="Inbox, triggers, nudges, completions and check-ins appear here."
              />
            ) : null}
          </>
        }
        renderSectionHeader={({ section }) => (
          <View style={s.sectionHeader}>
            <Text style={s.groupLabel}>{section.title}</Text>
          </View>
        )}
        renderItem={({ item }) => (
          <SectionCard style={s.itemCard}>
            <View style={s.itemRow}>
              <View style={s.leftRow}>
                <View style={s.iconBox}><Text style={s.iconText}>{item.icon}</Text></View>
                <View style={s.itemTextCol}>
                  <Text style={s.itemTitle} numberOfLines={1}>{item.title}</Text>
                  <Text style={s.itemSub} numberOfLines={1}>{item.subTime}</Text>
                </View>
              </View>
              <TouchableOpacity onPress={() => { void onTapItem(item); }} activeOpacity={0.75}>
                <Text style={s.itemTime}>{item.type === 'notification' ? 'Dismiss' : item.time}</Text>
              </TouchableOpacity>
            </View>
          </SectionCard>
        )}
        SectionSeparatorComponent={() => <View style={{ height: 10 }} />}
        ItemSeparatorComponent={() => <View style={{ height: 8 }} />}
        contentContainerStyle={s.listContent}
      />
    </ZenScreen>
  );
}

const s = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingTop: 48 },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    marginBottom: 10,
  },
  title: {
    marginTop: 6,
    fontSize: 22,
    fontWeight: '600',
    letterSpacing: -0.5,
    color: ZEN.colors.white,
  },
  filterRow: { gap: 8, paddingBottom: 4, marginBottom: 10 },
  listContent: { paddingBottom: 24 },
  sectionHeader: { paddingTop: 6, paddingBottom: 4 },
  tabPill: {
    borderRadius: 999,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.10)',
    backgroundColor: 'rgba(255,255,255,0.05)',
    paddingHorizontal: 12,
    paddingVertical: 7,
  },
  tabPillActive: {
    borderColor: 'rgba(255,255,255,0.18)',
    backgroundColor: 'rgba(255,255,255,0.10)',
  },
  tabPillText: {
    fontSize: 11,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    color: ZEN.colors.textMuted,
    fontWeight: '700',
  },
  tabPillTextActive: { color: ZEN.colors.white },
  groupLabel: {
    fontSize: 11,
    textTransform: 'uppercase',
    letterSpacing: 2,
    color: ZEN.colors.textMuted,
    marginBottom: 2,
  },
  itemCard: { paddingVertical: 10 },
  itemRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
  leftRow: { flexDirection: 'row', alignItems: 'center', gap: 10, flex: 1 },
  iconBox: {
    width: 40,
    height: 40,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.10)',
    backgroundColor: 'rgba(255,255,255,0.04)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconText: { fontSize: 18 },
  itemTextCol: { flex: 1, gap: 2 },
  itemTitle: { fontSize: 14, color: ZEN.colors.white, fontWeight: '600' },
  itemSub: { fontSize: 12, color: ZEN.colors.textMuted },
  itemTime: { fontSize: 13, color: ZEN.colors.textMuted, minWidth: 44, textAlign: 'right' },
});
