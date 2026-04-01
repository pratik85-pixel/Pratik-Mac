/**
 * BandWearSessionListScreen
 * Shows all closed band-wear sessions grouped by date.
 * Each row taps through to BandWearSessionDetailScreen.
 */

import React, { useCallback, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity,
  ActivityIndicator, SectionList,
} from 'react-native';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { ChevronLeft } from 'lucide-react-native';
import EmptyState from '../components/EmptyState';
import { getBandSessionHistory, type BandSessionSummary } from '../api/bandSessions';
import type { HistoryStackParamList } from '../navigation/AppNavigator';
import { ZEN, ZenScreen, SectionCard } from '../ui/zenflow-ui-kit';

// ─── Zone helpers ─────────────────────────────────────────────────────────────

type ZoneTone = 'excellent' | 'good' | 'normal' | 'low' | 'critical';

const ZONE_COLORS: Record<ZoneTone, string> = {
  excellent: '#39E27D',
  good:      '#7BE8A5',
  normal:    '#F2D14C',
  low:       '#FF9E5E',
  critical:  '#FF6B6B',
};

const ZONE_LABELS: Record<ZoneTone, string> = {
  excellent: '↑ Excellent',
  good:      '↑ Good',
  normal:    '→ Normal',
  low:       '↓ Low',
  critical:  '↓ Critical',
};

function netBalanceZone(net: number | null): ZoneTone {
  if (net === null) return 'normal';
  if (net >= 25)  return 'excellent';
  if (net >= 10)  return 'good';
  if (net >= -5)  return 'normal';
  if (net >= -20) return 'low';
  return 'critical';
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function groupByDate(sessions: BandSessionSummary[]) {
  const map: Record<string, BandSessionSummary[]> = {};
  sessions.forEach(s => {
    const d = new Date(s.started_at);
    const key = d.toLocaleDateString('en-IN', {
      weekday: 'short', day: 'numeric', month: 'short',
    });
    if (!map[key]) map[key] = [];
    map[key].push(s);
  });
  return Object.entries(map).map(([title, data]) => ({ title, data }));
}

function fmtTime(iso: string) {
  return new Date(iso).toLocaleTimeString('en-IN', {
    hour: '2-digit', minute: '2-digit', hour12: true,
  });
}

function fmtDuration(mins: number | null) {
  if (mins === null) return '—';
  const h = Math.floor(mins / 60);
  const m = Math.round(mins % 60);
  if (h === 0) return `${m}m`;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

// ─── SessionRow ───────────────────────────────────────────────────────────────

interface SessionRowProps {
  item: BandSessionSummary;
  onPress: () => void;
}

function SessionRow({ item, onPress }: SessionRowProps) {
  const tone  = netBalanceZone(item.net_balance);
  const color = ZONE_COLORS[tone];
  const label = ZONE_LABELS[tone];
  const sign  = item.net_balance !== null && item.net_balance > 0 ? '+' : '';
  const balStr = item.net_balance !== null ? `${sign}${item.net_balance.toFixed(1)}` : '—';

  const start = fmtTime(item.started_at);
  const end   = item.ended_at ? fmtTime(item.ended_at) : '…';
  const dur   = fmtDuration(item.duration_minutes);

  const rmssdStr   = item.avg_rmssd_ms   !== null ? `${Math.round(item.avg_rmssd_ms)}ms`  : '—';
  const stressStr  = item.stress_pct     !== null ? `${Math.round(item.stress_pct)}%`      : '—';
  const recStr     = item.recovery_pct   !== null ? `${Math.round(item.recovery_pct)}%`    : '—';

  return (
    <TouchableOpacity style={s.row} activeOpacity={0.75} onPress={onPress}>
      {/* Time range + duration */}
      <View style={s.rowTop}>
        <Text style={s.timeRange}>
          {start}
          <Text style={s.timeArrow}> → </Text>
          {end}
        </Text>
        <Text style={s.dur}>{dur}</Text>
      </View>

      {/* Zone pill + sleep moon */}
      <View style={s.rowMid}>
        <View style={[s.pill, {
          backgroundColor: `${color}22`,
          borderColor:      `${color}44`,
        }]}>
          <Text style={[s.pillText, { color }]}>{label}</Text>
          <Text style={[s.pillBalance, { color: `${color}CC` }]}>{balStr}</Text>
        </View>
        {item.has_sleep_data
          ? <Text style={s.moon}>🌙</Text>
          : <Text style={s.moonDot}>·</Text>
        }
      </View>

      {/* Micro stats */}
      <View style={s.rowBot}>
        <Text style={s.stat}>RMSSD · <Text style={s.statVal}>{rmssdStr}</Text></Text>
        <Text style={s.stat}>Stress · <Text style={s.statVal}>{stressStr}</Text></Text>
        <Text style={s.stat}>Rec · <Text style={s.statVal}>{recStr}</Text></Text>
        <Text style={s.chevron}>›</Text>
      </View>
    </TouchableOpacity>
  );
}

// ─── Main screen ──────────────────────────────────────────────────────────────

export default function BandWearSessionListScreen() {
  const nav = useNavigation<NativeStackNavigationProp<HistoryStackParamList>>();
  const [sessions, setSessions] = useState<BandSessionSummary[]>([]);
  const [loading, setLoading]   = useState(true);

  useFocusEffect(useCallback(() => {
    let active = true;
    (async () => {
      setLoading(true);
      try {
        const res = await getBandSessionHistory(40);
        if (active) setSessions(res.data ?? []);
      } catch {}
      finally { if (active) setLoading(false); }
    })();
    return () => { active = false; };
  }, []));

  const sections = groupByDate(sessions);

  return (
    <ZenScreen scrollable={false}>
      {/* Header */}
      <View style={s.header}>
        <TouchableOpacity style={s.backBtn} onPress={() => nav.goBack()} activeOpacity={0.8}>
          <ChevronLeft size={20} color={ZEN.colors.textNear} />
        </TouchableOpacity>
        <View style={s.headerCenter}>
          <Text style={s.eyebrow}>BAND</Text>
          <Text style={s.title}>Sessions</Text>
        </View>
        <View style={s.backBtn} />
      </View>

      {loading ? (
        <View style={s.center}>
          <ActivityIndicator color={ZEN.colors.recovery} />
        </View>
      ) : sessions.length === 0 ? (
        <EmptyState
          icon="time-outline"
          title="No sessions recorded yet"
          message="Wear your band for 90+ minutes to create your first session."
        />
      ) : (
        <SectionList
          sections={sections}
          keyExtractor={(item) => item.id}
          contentContainerStyle={s.list}
          showsVerticalScrollIndicator={false}
          stickySectionHeadersEnabled={false}
          renderSectionHeader={({ section }) => (
            <View style={s.dateHeader}>
              <Text style={s.dateLabel}>{section.title}</Text>
            </View>
          )}
          renderItem={({ item }) => (
            <SessionRow
              item={item}
              onPress={() =>
                nav.navigate('BandWearSessionDetail', {
                  sessionId:       item.id,
                  startedAt:       item.started_at,
                  endedAt:         item.ended_at,
                  durationMinutes: item.duration_minutes,
                  stressPct:       item.stress_pct,
                  recoveryPct:     item.recovery_pct,
                  netBalance:      item.net_balance,
                  hasSleepData:    item.has_sleep_data,
                  avgRmssdMs:      item.avg_rmssd_ms,
                  avgHrBpm:        item.avg_hr_bpm,
                })
              }
            />
          )}
          SectionSeparatorComponent={() => <View style={{ height: 8 }} />}
          ItemSeparatorComponent={() => <View style={{ height: 10 }} />}
        />
      )}
    </ZenScreen>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const s = StyleSheet.create({
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 12,
    gap: 8,
  },
  backBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: ZEN.colors.borderStrong,
    backgroundColor: ZEN.colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerCenter: { flex: 1, alignItems: 'center' },
  eyebrow: {
    fontSize: 10,
    textTransform: 'uppercase',
    letterSpacing: 2.4,
    color: ZEN.colors.textMuted,
  },
  title: {
    fontSize: 22,
    fontWeight: '600',
    letterSpacing: -0.5,
    color: ZEN.colors.white,
    marginTop: 4,
  },

  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },

  list: { paddingHorizontal: 16, paddingBottom: 40 },

  dateHeader: { paddingVertical: 8 },
  dateLabel: {
    fontSize: 11,
    textTransform: 'uppercase',
    letterSpacing: 2.2,
    color: ZEN.colors.textMuted,
  },

  row: {
    borderRadius: 22,
    borderWidth: 1,
    borderColor: ZEN.colors.borderStrong,
    backgroundColor: ZEN.colors.surface,
    paddingHorizontal: 16,
    paddingVertical: 16,
    gap: 10,
  },

  rowTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  timeRange: {
    fontSize: 14,
    fontWeight: '500',
    color: ZEN.colors.textBody,
    letterSpacing: -0.3,
  },
  timeArrow: { color: ZEN.colors.textMuted },
  dur: { fontSize: 13, color: ZEN.colors.textSecondary },

  rowMid: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    borderRadius: 999,
    borderWidth: 1,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  pillText:    { fontSize: 14, fontWeight: '500' },
  pillBalance: { fontSize: 13 },
  moon:    { fontSize: 18 },
  moonDot: { fontSize: 16, color: ZEN.colors.textMuted },

  rowBot: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  stat:    { fontSize: 12, color: ZEN.colors.textSecondary },
  statVal: { color: ZEN.colors.textBody },
  chevron: { fontSize: 18, color: ZEN.colors.textMuted },
});
