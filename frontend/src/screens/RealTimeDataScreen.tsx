import React, { useMemo, useCallback, useState } from 'react';
import { View, Text, StyleSheet, RefreshControl, ActivityIndicator } from 'react-native';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { ArrowLeft, ArrowRight } from 'lucide-react-native';
import TopHeader from '../components/TopHeader';
import { useDailyData } from '../contexts/DailyDataContext';
import type { HomeStackParamList } from '../navigation/AppNavigator';
import type { WaveformPoint, StressWindow, RecoveryWindow } from '../types';
import {
  ZEN,
  ZenScreen,
  SectionCard,
  SectionEyebrow,
  StressChartCard,
  RecoveryChartCard,
  type ChartPoint,
} from '../ui/zenflow-ui-kit';

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '--:--';
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
}

function normalizePercentScore(v: number | null | undefined): number | null {
  if (v == null || !Number.isFinite(v)) return null;
  const n = Number(v);
  return Math.max(0, Math.min(100, n));
}

function todayISO(): string {
  return new Date().toISOString().split('T')[0];
}

function fmtLastUpdated(ts: number | null): string {
  if (!ts) return '—';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
}

function toStressChartPoints(
  waveform: WaveformPoint[],
  windows: StressWindow[],
  morningAvg: number | null,
): ChartPoint[] {
  if (!waveform.length) return [];
  const avg = morningAvg ?? 0;
  const points = waveform.filter(p => p.is_valid !== false && p.context === 'background');
  if (!points.length) return [];
  if (!windows.length) {
    return points.map(p => {
      const pointIso = p.window_end || p.window_start;
      const rmssd = p.rmssd_ms ?? avg;
      const value = avg > 0 ? Math.max(0, avg - rmssd) : 0;
      return { time: fmtTime(pointIso), isoTime: pointIso, value, isEvent: false, isSleep: false };
    });
  }

  // O(N+M) sweep over sorted windows.
  const sortedWindows = [...windows].sort(
    (a, b) => Date.parse(a.started_at) - Date.parse(b.started_at),
  );
  let wi = 0;
  let current = sortedWindows[wi] ?? null;

  return points.map(p => {
    const pointIso = p.window_end || p.window_start;
    const ts = Date.parse(pointIso);
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
      time: fmtTime(pointIso),
      isoTime: pointIso,
      value,
      isEvent,
      isSleep: false,
    };
  });
}

function toRecoveryChartPoints(
  waveform: WaveformPoint[],
  windows: RecoveryWindow[],
  morningAvg: number | null,
  opts: { contextMode: 'waking' | 'sleep' },
): ChartPoint[] {
  if (!waveform.length) return [];
  const avg = morningAvg ?? 0;
  const filter =
    opts.contextMode === 'waking'
      ? (p: WaveformPoint) => p.is_valid !== false && p.context === 'background'
      : (p: WaveformPoint) => p.is_valid !== false && p.context !== 'background';

  const points = waveform.filter(filter);
  if (!points.length) return [];
  if (!windows.length) {
    return points.map(p => {
      const pointIso = p.window_end || p.window_start;
      const rmssd = p.rmssd_ms ?? avg;
      const value = Math.max(0, rmssd - avg);
      return { time: fmtTime(pointIso), isoTime: pointIso, value, isEvent: false, isSleep: opts.contextMode === 'sleep' };
    });
  }

  const sortedWindows = [...windows].sort(
    (a, b) => Date.parse(a.started_at) - Date.parse(b.started_at),
  );
  let wi = 0;
  let current = sortedWindows[wi] ?? null;

  return points.map(p => {
    const pointIso = p.window_end || p.window_start;
    const ts = Date.parse(pointIso);
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
      time: fmtTime(pointIso),
      isoTime: pointIso,
      value,
      isEvent,
      isSleep: opts.contextMode === 'sleep',
    };
  });
}

export default function RealTimeDataScreen() {
  const nav = useNavigation<NativeStackNavigationProp<HomeStackParamList>>();
  const ctx = useDailyData();
  const { refresh: refreshDaily } = ctx;

  const [refreshing, setRefreshing] = useState(false);

  const summary = ctx.summary;
  const stressScore = normalizePercentScore(summary?.stress_load_score ?? null);
  const stress10 = stressScore == null ? null : Math.round((stressScore / 10) * 10) / 10;
  const wakingRecovery = normalizePercentScore(summary?.waking_recovery_score ?? null);
  const sleepRecovery = normalizePercentScore(summary?.sleep_recovery_score ?? null);

  const morningAvg = summary?.rmssd_morning_avg ?? null;
  const today = summary?.summary_date ?? todayISO();

  const stressChart = useMemo(() => {
    return toStressChartPoints(ctx.waveform, ctx.stressWindows, morningAvg);
  }, [ctx.waveform, ctx.stressWindows, morningAvg]);

  const wakingRecoveryChart = useMemo(() => {
    return toRecoveryChartPoints(ctx.waveform, ctx.recoveryWindows, morningAvg, { contextMode: 'waking' });
  }, [ctx.waveform, ctx.recoveryWindows, morningAvg]);

  const sleepRecoveryChart = useMemo(() => {
    // For sleep-only chart, do not overlay “recovery windows” as events unless we explicitly model them as sleep windows.
    // Also scope to today's date so we don't accidentally show prior-night spillover on the wrong day.
    const wfToday = (ctx.waveform ?? []).filter(p =>
      String(p.window_start ?? '').slice(0, 10) === today
    );

    const firstBackgroundTs = wfToday
      .filter(p => p.is_valid !== false && p.context === 'background')
      .reduce<number | null>((minTs, p) => {
        const ts = Date.parse(String(p.window_start ?? ''));
        if (!Number.isFinite(ts)) return minTs;
        return minTs == null ? ts : Math.min(minTs, ts);
      }, null);

    const sleepUntilReset = wfToday.filter(p => {
      if (p.is_valid === false) return false;
      if (p.context === 'background') return false;
      if (firstBackgroundTs == null) return true;
      const ts = Date.parse(String(p.window_start ?? ''));
      return Number.isFinite(ts) && ts < firstBackgroundTs;
    });

    return toRecoveryChartPoints(sleepUntilReset, [], morningAvg, { contextMode: 'sleep' });
  }, [ctx.waveform, morningAvg, today]);

  const lastUpdatedAt = useMemo(() => {
    const pts = ctx.waveform ?? [];
    let maxTs: number | null = null;
    for (const p of pts) {
      const iso = (p as any).window_end ?? p.window_start;
      const ts = Date.parse(String(iso ?? ''));
      if (!Number.isFinite(ts)) continue;
      if (maxTs == null || ts > maxTs) maxTs = ts;
    }
    return maxTs;
  }, [ctx.waveform]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    refreshDaily().finally(() => setRefreshing(false));
  }, [refreshDaily]);

  useFocusEffect(useCallback(() => {
    refreshDaily();
  }, [refreshDaily]));

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
      <TopHeader
        title="TODAY'S LIVE SCORES"
        subtitle={`Last updated: ${fmtLastUpdated(lastUpdatedAt)}`}
        leftIcon={<ArrowLeft size={18} color={ZEN.colors.textNear} />}
        onLeftPress={() => nav.goBack()}
        rightIcon={<ArrowRight size={18} color={ZEN.colors.textNear} />}
        onRightPress={() => (nav.getParent() as any)?.navigate('PlanTab')}
      />

      {ctx.loading && !summary ? (
        <View style={s.center}>
          <ActivityIndicator color={ZEN.colors.stress} size="large" />
        </View>
      ) : (
        <View style={s.content}>
          <View style={s.sectionHeaderRow}>
            <SectionEyebrow>Stress real-time data</SectionEyebrow>
            <Text style={s.sectionScore}>{stress10 != null ? `${stress10.toFixed(1)}/10` : '—'}</Text>
          </View>
          {stressChart.length > 1 ? (
            <StressChartCard data={stressChart} />
          ) : (
            <SectionCard style={s.emptyCard}>
              <Text style={s.emptyText}>No stress waveform yet.</Text>
            </SectionCard>
          )}

          <View style={s.sectionHeaderRow}>
            <SectionEyebrow>Waking recovery graph</SectionEyebrow>
            <Text style={s.sectionScore}>{wakingRecovery != null ? `${Math.round(wakingRecovery)}/100` : '—'}</Text>
          </View>
          {wakingRecoveryChart.length > 1 ? (
            <RecoveryChartCard data={wakingRecoveryChart} legend={{ recoveryWindow: true, regularActivity: true, sleep: false }} />
          ) : (
            <SectionCard style={s.emptyCard}>
              <Text style={s.emptyText}>No waking recovery waveform yet.</Text>
            </SectionCard>
          )}

          <View style={s.sectionHeaderRow}>
            <SectionEyebrow>Sleep recovery graph</SectionEyebrow>
            <Text style={s.sectionScore}>{sleepRecovery != null ? `${Math.round(sleepRecovery)}/100` : '—'}</Text>
          </View>
          <Text style={s.sleepStagesHint}>Sleep stages (REM/Deep) coming soon</Text>
          {sleepRecoveryChart.length > 1 ? (
            <RecoveryChartCard data={sleepRecoveryChart} legend={{ recoveryWindow: false, regularActivity: false, sleep: true }} />
          ) : (
            <SectionCard style={s.emptyCard}>
              <Text style={s.emptyText}>No sleep recovery waveform yet.</Text>
            </SectionCard>
          )}
        </View>
      )}
    </ZenScreen>
  );
}

const s = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingVertical: 80 },
  content: { gap: 12, paddingBottom: 40 },
  sectionHeaderRow: {
    marginTop: 8,
    marginBottom: -4,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  sectionScore: { fontSize: 12, color: ZEN.colors.textMuted, fontWeight: '700' },
  sleepStagesHint: { fontSize: 11, color: ZEN.colors.textMuted, marginTop: -2, marginBottom: -2 },
  emptyCard: { alignItems: 'center', justifyContent: 'center', paddingVertical: 18 },
  emptyText: { fontSize: 13, color: ZEN.colors.textMuted },
});

