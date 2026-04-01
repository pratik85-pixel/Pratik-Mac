import React, { useCallback, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, FlatList,
} from 'react-native';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MoreHorizontal } from 'lucide-react-native';
import TopHeader from '../components/TopHeader';
import { getSessionHistory, type SessionHistoryItem } from '../api/session';
import { getHistory } from '../api/tracking';
import type { HistoryStackParamList } from '../navigation/AppNavigator';
import {
  ZEN,
  ZenScreen,
  SectionCard,
  CombinedBalanceChart,
  type BalanceDayPoint,
} from '../ui/zenflow-ui-kit';

function fmtDayLabel(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString('en-US', { weekday: 'short' }) + ' ' + d.getDate();
}

export default function HistoryScreen() {
  const nav = useNavigation<NativeStackNavigationProp<HistoryStackParamList>>();
  const [sessions, setSessions]       = useState<SessionHistoryItem[]>([]);
  const [loading, setLoading]         = useState(true);
  const [historyData, setHistoryData] = useState<BalanceDayPoint[]>([]);
  const [averages, setAverages] = useState<{ stress10: number | null; waking: number | null; readiness: number | null }>({
    stress10: null,
    waking: null,
    readiness: null,
  });

  useFocusEffect(useCallback(() => { load(); }, []));

  const load = async () => {
    setLoading(true);
    try {
      const [res, hRes] = await Promise.all([
        getSessionHistory(30),
        getHistory(7),
      ]);
      setSessions(res.data ?? []);
      const days: BalanceDayPoint[] = (hRes.data ?? []).map((item: any) => ({
        label:    fmtDayLabel(item.summary_date),
        stress:   item.stress_load_score ?? null,
        recovery: item.recovery_score ?? item.waking_recovery_score ?? null,
      }));
      setHistoryData(days);
      const samples = hRes.data ?? [];
      const stressVals = samples
        .map((item: any) => item?.stress_load_score)
        .filter((v: any) => v != null && Number.isFinite(v))
        .map((v: number) => v / 10);
      const wakingVals = samples
        .map((item: any) => item?.waking_recovery_score ?? item?.recovery_score)
        .filter((v: any) => v != null && Number.isFinite(v));
      const readinessVals = samples
        .map((item: any) => item?.readiness_score)
        .filter((v: any) => v != null && Number.isFinite(v));
      const avg = (arr: number[]) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null);
      setAverages({
        stress10: avg(stressVals),
        waking: avg(wakingVals),
        readiness: avg(readinessVals),
      });
    } catch {}
    finally { setLoading(false); }
  };

  const renderSession = ({ item }: { item: SessionHistoryItem }) => {
    const start  = new Date(item.started_at);
    const dateLabel = start.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' });
    const timeLabel = start.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true });
    const dur    = item.duration_minutes !== null ? `${Math.round(item.duration_minutes)} min` : '—';
    const score  = item.session_score !== null ? `${Math.round(item.session_score)}` : '—';
    const pType  = item.practice_type
      ? item.practice_type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
      : 'Session';

    return (
      <TouchableOpacity
        style={s.sessionRow}
        activeOpacity={0.75}
        onPress={() => nav.navigate('SessionSummary', item)}
      >
        <View style={s.sessionLeft}>
          <Text style={s.sessionDate}>{dateLabel}</Text>
          <Text style={s.sessionTime}>{timeLabel} · {dur}</Text>
          <Text style={s.sessionType}>{pType}</Text>
        </View>
        <View style={s.sessionRight}>
          <Text style={s.sessionScore}>{score}</Text>
          <Text style={s.sessionScoreLabel}>score</Text>
        </View>
        <Text style={s.sessionArrow}>›</Text>
      </TouchableOpacity>
    );
  };

  return (
    <ZenScreen scrollable={false}>
      <FlatList
        data={loading ? [] : sessions}
        keyExtractor={(item) => item.session_id}
        renderItem={renderSession}
        showsVerticalScrollIndicator={false}
        ItemSeparatorComponent={() => <View style={s.separator} />}
        contentContainerStyle={s.listContent}
        ListHeaderComponent={
          <>
            <TopHeader
              eyebrow="Executive Analytics"
              title="Performance History"
              rightIcon={<MoreHorizontal size={18} color="rgba(255,255,255,0.7)" />}
            />

            <CombinedBalanceChart
              data={historyData}
              title="7-Day Stress vs Recovery"
              stressDisplayScale="0-10"
            />

            <View style={s.metricsRow}>
              <SectionCard style={s.metricCard}>
                <Text style={s.metricLabel}>Avg Stress Load</Text>
                <Text style={s.metricValue}>
                  {averages.stress10 == null ? '—' : `${averages.stress10.toFixed(1)}`}
                  <Text style={s.metricSuffix}> /10</Text>
                </Text>
              </SectionCard>
              <SectionCard style={s.metricCard}>
                <Text style={s.metricLabel}>Avg Waking Recovery</Text>
                <Text style={s.metricValue}>
                  {averages.waking == null ? '—' : `${Math.round(averages.waking)}`}
                  <Text style={s.metricSuffix}> /100</Text>
                </Text>
              </SectionCard>
              <SectionCard style={s.metricCard}>
                <Text style={s.metricLabel}>Avg Readiness</Text>
                <Text style={s.metricValue}>
                  {averages.readiness == null ? '—' : `${Math.round(averages.readiness)}`}
                  <Text style={s.metricSuffix}> /100</Text>
                </Text>
              </SectionCard>
            </View>

            {loading ? (
              <View style={s.center}>
                <ActivityIndicator color={ZEN.colors.readiness} />
              </View>
            ) : null}

            {!loading && sessions.length === 0 ? (
              <SectionCard>
                <Text style={{ color: ZEN.colors.textMuted }}>No sessions yet.</Text>
              </SectionCard>
            ) : null}
          </>
        }
        ListFooterComponent={
          <SectionCard style={s.profileSection}>
            <TouchableOpacity
              style={s.profileRow}
              activeOpacity={0.75}
              onPress={() => nav.navigate('BandWearSessionList' as any)}
            >
              <View style={s.profileText}>
                <Text style={s.profileLabel}>Band Sessions</Text>
                <Text style={s.profileSub}>Wear-period history &amp; insights</Text>
              </View>
              <Text style={s.profileArrow}>›</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={s.profileRow}
              activeOpacity={0.75}
              onPress={() => nav.navigate('Settings' as any)}
            >
              <View style={s.profileText}>
                <Text style={[s.profileLabel, { color: ZEN.colors.textLabel }]}>Settings</Text>
                <Text style={s.profileSub}>Device, diagnostics</Text>
              </View>
              <Text style={s.profileArrow}>›</Text>
            </TouchableOpacity>
          </SectionCard>
        }
      />
    </ZenScreen>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const s = StyleSheet.create({
  center: { paddingVertical: 60, alignItems: 'center' },
  metricsRow: {
    gap: 10,
    marginBottom: 12,
  },
  listContent: { paddingBottom: 24 },
  metricCard: {
    borderRadius: 18,
    paddingVertical: 12,
    paddingHorizontal: 14,
    gap: 4,
  },
  metricLabel: {
    fontSize: 10,
    color: ZEN.colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 1.4,
  },
  metricValue: {
    fontSize: 28,
    fontWeight: '800',
    color: ZEN.colors.white,
    letterSpacing: -0.8,
  },
  metricSuffix: {
    fontSize: 12,
    color: ZEN.colors.textMuted,
    fontWeight: '500',
  },

  sessionRow: {
    flexDirection: 'row',
    alignItems:    'center',
    paddingHorizontal: 16,
    paddingVertical:   14,
  },
  sessionLeft:  { flex: 1, gap: 2 },
  sessionDate: {
    fontSize:   13,
    fontWeight: '600',
    color:      ZEN.colors.textPrimary,
  },
  sessionTime: {
    fontSize: 12,
    color:    ZEN.colors.textMuted,
    marginTop: 1,
  },
  sessionType: {
    fontSize: 11,
    color:    ZEN.colors.recovery,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginTop: 2,
  },
  sessionRight: {
    alignItems:  'center',
    marginRight: 8,
  },
  sessionScore: {
    fontSize:   20,
    fontWeight: '700',
    color:      ZEN.colors.textPrimary,
  },
  sessionScoreLabel: {
    fontSize: 10,
    color:    ZEN.colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  sessionArrow: {
    fontSize: 20,
    color:    ZEN.colors.textMuted,
  },
  separator: {
    height:     1,
    marginLeft: 16,
    backgroundColor: ZEN.colors.border,
  },

  profileSection: { gap: 0, marginBottom: 12 },
  profileRow: {
    flexDirection: 'row', alignItems: 'center',
    paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: ZEN.colors.border,
  },
  profileText: { flex: 1, gap: 2 },
  profileLabel: { fontSize: 15, fontWeight: '600', color: ZEN.colors.white },
  profileSub:   { fontSize: 12, color: ZEN.colors.textMuted },
  profileArrow: { fontSize: 20, color: ZEN.colors.textMuted },
});
