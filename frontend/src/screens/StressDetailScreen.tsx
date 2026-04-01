import React, { useCallback, useMemo, useState } from 'react';
import TopHeader from '../components/TopHeader';
import { ArrowLeft, ArrowRight } from 'lucide-react-native';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, RefreshControl,
} from 'react-native';
import { useNavigation, useRoute, useFocusEffect } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import * as Haptics from 'expo-haptics';
import EmptyState from '../components/EmptyState';
import { getWaveform, getDailySummary, getStressWindows } from '../api/tracking';
import { useDailyData } from '../contexts/DailyDataContext';
import type { WaveformPoint, StressWindow } from '../types';
import type { HistoryStackParamList } from '../navigation/AppNavigator';
import {
  ZEN,
  ZenScreen,
  SectionCard,
  SurfaceCard,
  SectionEyebrow,
  ScoreRing,
  StressChartCard,
  type ChartPoint,
} from '../ui/zenflow-ui-kit';

// ─── helpers ──────────────────────────────────────────────────────────────────

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
}

function fmtActivityTime(iso: string | null | undefined): string {
  if (!iso) return '--:--';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '--:--';
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
}

function tagLabel(tag: string | null | undefined): string {
  if (!tag) return 'Stress Trigger';
  return tag.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function zoneAccent(zone: string | null | undefined): string {
  switch (zone) {
    case 'calm':
      return ZEN.colors.recovery;
    case 'steady':
      return ZEN.colors.readiness;
    case 'activated':
      return '#E8A849';
    case 'depleted':
      return ZEN.colors.stress;
    default:
      return ZEN.colors.stress;
  }
}

function toChartPoints(
  waveform: WaveformPoint[],
  windows: StressWindow[],
  morningAvg: number | null,
  nsCapacity: number | null,
): ChartPoint[] {
  if (!waveform.length) return [];
  const avg = morningAvg ?? 0;

  // Stress chart intentionally excludes sleep-context bars:
  // only daytime/background activity + stress events are shown.
  const points = waveform.filter(p => p.is_valid !== false && p.context === 'background');
  if (!points.length || !windows.length) {
    return points.map(p => {
      const rmssd = p.rmssd_ms ?? avg;
      const value = avg > 0 ? Math.max(0, avg - rmssd) : 0;
      return {
        time: fmtTime(p.window_start),
        isoTime: p.window_start,
        value,
        isEvent: false,
        isSleep: false,
      };
    });
  }

  // O(N+M) sweep: assume waveform points are already in time order; sort windows.
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
    const value = avg > 0 ? Math.max(0, avg - rmssd) : 0;
    return {
      time: fmtTime(p.window_start),
      isoTime: p.window_start,
      value,
      isEvent,
      isSleep: false,
    };
  });
}

// ─── Screen ───────────────────────────────────────────────────────────────────

export default function StressDetailScreen() {
  const nav = useNavigation<NativeStackNavigationProp<HistoryStackParamList>>();
  const { params } = useRoute<any>();
  const [date] = useState<string>(() => params?.date ?? new Date().toISOString().split('T')[0]);
  const [todayISO] = useState<string>(() => new Date().toISOString().split('T')[0]);
  const isToday = date === todayISO;

  // ── Context data (today only) ──────────────────────────────────────────
  const ctx = useDailyData();
  // Destructure stable references — ctx object recreates every render but these are stable
  const { refresh: ctxRefresh, patchStressWindow } = ctx;

  // ── Local state (used for historical dates) ────────────────────────────
  const [localWaveform,  setLocalWaveform]  = useState<WaveformPoint[]>([]);
  const [localWindows,   setLocalWindows]   = useState<StressWindow[]>([]);
  const [localScore,     setLocalScore]     = useState<number | null>(null);
  const [localMorningAvg, setLocalMorningAvg] = useState<number | null>(null);
  const [localNsCap,     setLocalNsCap]     = useState<number | null>(null);
  const [localLoading,   setLocalLoading]   = useState(false);
  const [refreshing,     setRefreshing]     = useState(false);

  // Derive displayed values: today reads from context, history reads local state
  const waveform   = isToday ? ctx.waveform        : localWaveform;
  const baseEvents = isToday ? ctx.stressWindows   : localWindows;
  const events     = baseEvents;
  const score      = isToday ? (ctx.summary?.stress_load_score ?? null)    : localScore;
  const morningAvg = isToday ? (ctx.summary?.rmssd_morning_avg ?? null)    : localMorningAvg;
  const nsCapacity = isToday ? (ctx.summary?.ns_capacity_used ?? null)     : localNsCap;
  const loading    = isToday ? ctx.loading : localLoading;

  // Historical fetch (only runs when viewing a past date)
  const loadHistorical = useCallback(async () => {
    setLocalLoading(true);
    try {
      const [wRes, sRes, swRes] = await Promise.all([
        getWaveform(date),
        getDailySummary(date),
        getStressWindows(date),
      ]);
      setLocalWaveform(wRes.data ?? []);
      setLocalScore(sRes.data?.stress_load_score ?? null);
      setLocalMorningAvg(sRes.data?.rmssd_morning_avg ?? null);
      setLocalNsCap(sRes.data?.ns_capacity_used ?? null);
      setLocalWindows(swRes.data ?? []);
    } catch { /* show empty state */ }
    finally { setLocalLoading(false); }
  }, [date]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    if (isToday) ctxRefresh();
    else loadHistorical();
    setTimeout(() => setRefreshing(false), 1000);
  }, [isToday, ctxRefresh, loadHistorical]);

  useFocusEffect(
    useCallback(() => {
      if (isToday) ctxRefresh();
      else loadHistorical();
    }, [isToday, ctxRefresh, loadHistorical]),
  );

  // Clear the optimistic override only after underlying data refreshes from server
  // (removed — tags are now patched directly into ctx.stressWindows)

  // After a tag action: for today re-run context refresh; for history reload locally
  const chartData = useMemo(
    () => toChartPoints(waveform, events, morningAvg, nsCapacity),
    [waveform, events, morningAvg, nsCapacity],
  );
  const scoreText   = score !== null
    ? (score >= 70 ? 'Elevated' : score >= 40 ? 'Moderate' : 'Low')
    : '—';
  const score10 = score !== null ? Math.round((Math.max(0, Math.min(100, score)) / 10) * 10) / 10 : null;
  const progress    = score !== null ? Math.min(1, Math.max(0, score / 100)) : 0;
  const goalLoad =
    ctx.planHome?.day_type === 'green'
      ? 70
      : ctx.planHome?.day_type === 'yellow'
        ? 55
        : 45;
  const stressRingColor =
    score != null && score >= goalLoad
      ? ZEN.colors.stress
      : zoneAccent(ctx.stressState?.stress_now_zone);

  return (
    <ZenScreen
      scrollable
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={ZEN.colors.stress}
        />
      }
    >
      {/* ── Header ─────────────────────────────────────────────────── */}
      <TopHeader
        eyebrow="Stress"
        title="Load Monitor"
        leftIcon={<ArrowLeft size={18} color={ZEN.colors.textNear} />}
        rightIcon={<ArrowRight size={18} color={ZEN.colors.textNear} />}
        onLeftPress={() => nav.goBack()}
        onRightPress={() => nav.goBack()}
      />

      {loading ? (
        <View style={s.center}>
          <ActivityIndicator color={ZEN.colors.stress} size="large" />
        </View>
      ) : (
        <>
          {/* ── Score summary card ──────────────────────────────────── */}
          <SectionCard style={s.summaryCard}>
            <View style={s.summaryRow}>
              {/* Ring */}
              <ScoreRing
                value={score10 !== null ? score10.toFixed(1) : null}
                suffix="/10"
                progress={progress}
                color={stressRingColor}
                size={92}
              />
              {/* Text */}
              <View style={s.summaryText}>
                <SectionEyebrow>Daily stress load</SectionEyebrow>
                <Text style={s.statusBadge}>{scoreText}</Text>
                <Text style={s.summaryDesc}>
                  {score !== null && score >= 70
                    ? 'Above your typical range — prioritise recovery today.'
                    : score !== null && score >= 40
                    ? 'Within normal range. Steady as it goes.'
                    : 'Low today. Good conditions for deep work or hard training.'}
                </Text>
              </View>
            </View>
          </SectionCard>

          {/* ── Chart ──────────────────────────────────────────────── */}
          {chartData.length > 1 ? (
            <StressChartCard data={chartData} />
          ) : (
            <SurfaceCard style={s.emptyChart}>
              <EmptyState
                icon="pulse-outline"
                title="No waveform today"
                message="5-minute windows appear as data comes in."
              />
            </SurfaceCard>
          )}

        </>
      )}
    </ZenScreen>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const s = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingVertical: 80 },

  header: {
    flexDirection:   'row',
    alignItems:      'center',
    justifyContent:  'space-between',
    marginBottom:    16,
  },
  headerBtn: {
    width:           40,
    height:          40,
    borderRadius:    20,
    borderWidth:     1,
    borderColor:     'rgba(255,255,255,0.15)',
    backgroundColor: 'rgba(255,255,255,0.05)',
    alignItems:      'center',
    justifyContent:  'center',
  },
  headerBtnText: { fontSize: 20, color: ZEN.colors.textNear },
  headerCenter:  { alignItems: 'center' },
  headerEyebrow: {
    fontSize:      10,
    textTransform: 'uppercase',
    letterSpacing: 3,
    color:        ZEN.colors.textMuted,
  },
  headerTitle: {
    marginTop:    4,
    fontSize:     16,
    fontWeight:   '600',
    letterSpacing: -0.3,
    color:        ZEN.colors.white,
  },

  summaryCard: { marginBottom: 0 },
  summaryRow: {
    flexDirection: 'row',
    alignItems:    'center',
    gap:           20,
  },
  summaryText: { flex: 1, gap: 6 },
  statusBadge: {
    fontSize:   22,
    fontWeight: '600',
    color:     ZEN.colors.stress,
  },
  summaryDesc: {
    fontSize:   13,
    lineHeight: 20,
    color:     ZEN.colors.textSecondary,
  },

  emptyChart: { alignItems: 'center', justifyContent: 'center' },

});
