import React, { useCallback, useEffect, useMemo, useState } from 'react';
import TopHeader from '../components/TopHeader';
import { ArrowLeft, ArrowRight } from 'lucide-react-native';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, RefreshControl,
} from 'react-native';
import { useNavigation, useRoute, useFocusEffect } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import EmptyState from '../components/EmptyState';
import { getWaveform, getDailySummary, getRecoveryWindows } from '../api/tracking';
import { useDailyData } from '../contexts/DailyDataContext';
import type { WaveformPoint, RecoveryWindow } from '../types';
import type { HistoryStackParamList } from '../navigation/AppNavigator';
import {
  ZEN,
  ZenScreen,
  SectionCard,
  SurfaceCard,
  SectionEyebrow,
  ScoreRing,
  RecoveryChartCard,
  type ChartPoint,
} from '../ui/zenflow-ui-kit';

// ─── helpers ──────────────────────────────────────────────────────────────────

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
}

function toChartPoints(
  waveform: WaveformPoint[],
  windows: RecoveryWindow[],
  morningAvg: number | null,
  nsCapacity: number | null,
): ChartPoint[] {
  if (!waveform.length) return [];
  const avg = morningAvg ?? 0;
  const points = waveform.filter(p => p.is_valid !== false);
  if (!points.length || !windows.length) {
    return points.map(p => {
      const rmssd = p.rmssd_ms ?? avg;
      const value = Math.max(0, rmssd - avg);
      return {
        time: fmtTime(p.window_start),
        isoTime: p.window_start,
        value,
        isEvent: false,
        isSleep: p.context !== 'background',
      };
    });
  }

  const sortedWindows = [...windows].sort(
    (a, b) => Date.parse(a.started_at) - Date.parse(b.started_at),
  );
  let wi = 0;
  let current = sortedWindows[wi] ?? null;

  return points.map(p => {
    const ts = Date.parse(p.window_start);
    while (current && Date.parse(current.ended_at) <= ts && wi < sortedWindows.length - 1) {
      wi += 1;
      current = sortedWindows[wi] ?? null;
    }
    const isEvent = !!(
      current &&
      ts >= Date.parse(current.started_at) &&
      ts < Date.parse(current.ended_at)
    );
    const rmssd = p.rmssd_ms ?? avg;
    const value = Math.max(0, rmssd - avg);
    return {
      time: fmtTime(p.window_start),
      isoTime: p.window_start,
      value,
      isEvent,
      isSleep: p.context !== 'background',
    };
  });
}

// ─── Screen ───────────────────────────────────────────────────────────────────

export default function RecoveryDetailScreen() {
  const nav = useNavigation<NativeStackNavigationProp<HistoryStackParamList>>();
  const { params } = useRoute<any>();
  const [date] = useState<string>(() => params?.date ?? new Date().toISOString().split('T')[0]);
  const [todayISO] = useState<string>(() => new Date().toISOString().split('T')[0]);
  const isToday = date === todayISO;

  // ── Context data (today only) ──────────────────────────────────────────
  const ctx = useDailyData();
  // Destructure stable references — ctx object recreates every render but these are stable
  const { refresh: ctxRefresh } = ctx;

  // ── Local state (used for historical dates) ────────────────────────────
  const [localWaveform,   setLocalWaveform]   = useState<WaveformPoint[]>([]);
  const [localWindows,    setLocalWindows]    = useState<RecoveryWindow[]>([]);
  const [localScore,      setLocalScore]      = useState<number | null>(null);
  const [localMorningAvg, setLocalMorningAvg] = useState<number | null>(null);
  const [localNsCap,      setLocalNsCap]      = useState<number | null>(null);
  const [localLoading,    setLocalLoading]    = useState(false);

  const [eventsOverride,  setEventsOverride]  = useState<RecoveryWindow[] | null>(null);
  const [refreshing,      setRefreshing]      = useState(false);

  // Derive displayed values: today reads from context, history reads local state
  const waveform   = isToday ? ctx.waveform           : localWaveform;
  const baseEvents = isToday ? ctx.recoveryWindows     : localWindows;
  const events     = eventsOverride ?? baseEvents;
  const score      = isToday
    ? (ctx.summary?.recovery_score ?? ctx.summary?.waking_recovery_score ?? null)
    : localScore;
  const morningAvg = isToday ? (ctx.summary?.rmssd_morning_avg ?? null) : localMorningAvg;
  const nsCapacity = isToday ? (ctx.summary?.ns_capacity_used ?? null)  : localNsCap;
  const loading    = isToday ? ctx.loading : localLoading;

  // Historical fetch (only runs when viewing a past date)
  const loadHistorical = useCallback(async () => {
    setLocalLoading(true);
    try {
      const [wRes, sRes, rwRes] = await Promise.all([
        getWaveform(date),
        getDailySummary(date),
        getRecoveryWindows(date),
      ]);
      setLocalWaveform(wRes.data ?? []);
      setLocalScore(sRes.data?.recovery_score ?? sRes.data?.waking_recovery_score ?? null);
      setLocalMorningAvg(sRes.data?.rmssd_morning_avg ?? null);
      setLocalNsCap(sRes.data?.ns_capacity_used ?? null);
      setLocalWindows(rwRes.data ?? []);
    } catch {}
    finally { setLocalLoading(false); }
  }, [date]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    if (isToday) ctxRefresh();
    else loadHistorical();
    setTimeout(() => setRefreshing(false), 1000);
  }, [isToday, ctxRefresh, loadHistorical]);

  useFocusEffect(useCallback(() => {
    if (isToday) ctxRefresh();
    else loadHistorical();
  }, [isToday, ctxRefresh, loadHistorical]));

  // Clear the optimistic override only after underlying data refreshes from server
  useEffect(() => { setEventsOverride(null); }, [baseEvents]);

  const chartData = useMemo(
    () => toChartPoints(waveform, events, morningAvg, nsCapacity),
    [waveform, events, morningAvg, nsCapacity],
  );
  const scoreText  = score !== null
    ? (score >= 70 ? 'Recovered well' : score >= 40 ? 'Partial recovery' : 'Low recovery')
    : '—';
  const progress   = score !== null ? Math.min(1, Math.max(0, score / 100)) : 0;
  const scoreDesc  = score !== null && score >= 70
    ? 'Strong overnight restoration. Good conditions for effort today.'
    : score !== null && score >= 40
    ? 'Partial recovery. Moderate effort is fine — avoid peak exertion.'
    : 'Low recovery. Prioritise rest, keep intensity light today.';

  return (
    <ZenScreen
      scrollable
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={ZEN.colors.recovery}
        />
      }
    >
      {/* Header */}
      <TopHeader
        eyebrow="Recovery"
        title="Waking + Sleep"
        leftIcon={<ArrowLeft size={18} color={ZEN.colors.textNear} />}
        onLeftPress={() => nav.goBack()}
        rightIcon={<ArrowRight size={18} color={ZEN.colors.textNear} />}
        onRightPress={() => (nav.getParent() as any)?.navigate('PlanTab')}
      />

      {loading ? (
        <View style={s.center}>
          <ActivityIndicator color={ZEN.colors.recovery} size="large" />
        </View>
      ) : (
        <>
          {/* Summary card */}
          <SectionCard style={s.summaryCard}>
            <View style={s.summaryRow}>
              <ScoreRing
                value={score !== null ? Math.round(score) : null}
                progress={progress}
                color={ZEN.colors.recovery}
                size={92}
              />
              <View style={s.summaryText}>
                <SectionEyebrow>Waking recovery</SectionEyebrow>
                <Text style={s.statusBadge}>{scoreText}</Text>
                <Text style={s.summaryDesc}>{scoreDesc}</Text>
              </View>
            </View>
          </SectionCard>

          {/* Chart — outside summary card to prevent nesting overlap */}
          {chartData.length > 1
            ? <RecoveryChartCard data={chartData} />
            : (
              <SurfaceCard style={s.emptyChart}>
                <EmptyState
                  icon="moon-outline"
                  title="No recovery data"
                  message="Recovery windows appear after rest periods."
                />
              </SurfaceCard>
            )
          }

        </>
      )}
    </ZenScreen>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const s = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingVertical: 80 },

  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 },
  headerBtn: {
    width: 40, height: 40, borderRadius: 20, borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.15)', backgroundColor: 'rgba(255,255,255,0.05)',
    alignItems: 'center', justifyContent: 'center',
  },
  headerBtnText: { fontSize: 20, color: ZEN.colors.textNear },
  headerCenter:  { alignItems: 'center' },
  headerEyebrow: { fontSize: 10, textTransform: 'uppercase', letterSpacing: 3, color: ZEN.colors.textMuted },
  headerTitle:   { marginTop: 4, fontSize: 16, fontWeight: '600', letterSpacing: -0.3, color: ZEN.colors.white },

  summaryCard: { marginBottom: 0 },
  summaryRow:  { flexDirection: 'row', alignItems: 'center', gap: 20 },
  summaryText: { flex: 1, gap: 6 },
  statusBadge: { fontSize: 22, fontWeight: '600', color: ZEN.colors.recovery },
  summaryDesc: { fontSize: 13, lineHeight: 20, color: ZEN.colors.textSecondary },

  emptyChart: { alignItems: 'center' },

});
