import React, { useCallback, useEffect, useRef, useState } from 'react';
import TopHeader from '../components/TopHeader';
import { ArrowLeft, Heart, Activity, Wind, Droplets } from 'lucide-react-native';
import {
  View, Text, StyleSheet, ActivityIndicator, RefreshControl,
} from 'react-native';
import { useNavigation, useRoute, useFocusEffect } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { getDailySummary, getWaveform } from '../api/tracking';
import type { WaveformPoint } from '../types';
import type { HomeStackParamList } from '../navigation/AppNavigator';
import { useDailyData } from '../contexts/DailyDataContext';
import {
  ZEN,
  ZenScreen,
  SurfaceCard,
  SectionEyebrow,
  ScoreRing,
  DivergingWindowChart,
  type DivergingWindowPoint,
} from '../ui/zenflow-ui-kit';

function avg(arr: number[]): number | null {
  if (!arr.length) return null;
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}

export default function ReadinessOverlayScreen() {
  const nav  = useNavigation<NativeStackNavigationProp<HomeStackParamList>>();
  const { params } = useRoute<any>();
  const daily = useDailyData();
  const [todayKey] = useState<string>(() => daily.summary?.summary_date ?? new Date().toISOString().split('T')[0]);
  const [date] = useState<string>(() => params?.date ?? todayKey);
  const isToday = date === todayKey;

  const [stressScore, setStressScore]       = useState<number | null>(null);
  const [recoveryScore, setRecoveryScore]   = useState<number | null>(null);
  const [netBalance, setNetBalance]         = useState<number | null>(null);
  const [loading, setLoading]               = useState(true);
  const [morningAvg, setMorningAvg]         = useState<number | null>(null);
  const [waveformData, setWaveformData]     = useState<DivergingWindowPoint[]>([]);

  // Live biometric tiles (refreshed every 60s from waveform)
  const [avgHR, setAvgHR]   = useState<number | null>(null);
  const [avgHRV, setAvgHRV] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchWaveformMetrics = useCallback(async () => {
    if (isToday) return; // today uses context waveform; no extra polling
    try {
      const res = await getWaveform(date);
      const pts: WaveformPoint[] = res.data ?? [];
      setWaveformData(pts);
      const hrs   = pts.map(p => p.hr_bpm).filter((v): v is number => v !== null);
      const hrsvs = pts.map(p => p.rmssd_ms).filter((v): v is number => v !== null);
      const h = avg(hrs);
      const v = avg(hrsvs);
      if (h !== null) setAvgHR(Math.round(h));
      if (v !== null) setAvgHRV(Math.round(v));
    } catch {}
  }, [date, isToday]);

  useFocusEffect(useCallback(() => {
    load();
    fetchWaveformMetrics();
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = isToday ? null : setInterval(fetchWaveformMetrics, 60_000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [date, isToday]));

  const load = async () => {
    setLoading(true);
    try {
      if (isToday) {
        const d = daily.summary as any;
        setStressScore(d?.stress_load_score ?? null);
        setRecoveryScore(d?.recovery_score ?? d?.waking_recovery_score ?? null);
        setNetBalance(d?.net_balance ?? null);
        setMorningAvg(d?.rmssd_morning_avg ?? null);
        return;
      }
      const sRes = await getDailySummary(date);
      const d = sRes.data as any;
      setStressScore(d?.stress_load_score ?? null);
      setRecoveryScore(d?.recovery_score ?? d?.waking_recovery_score ?? null);
      setNetBalance(d?.net_balance ?? null);
      setMorningAvg(d?.rmssd_morning_avg ?? null);
    } catch {}
    finally { setLoading(false); }
  };

  // For today, derive waveform + live averages from context instead of polling endpoints.
  useEffect(() => {
    if (!isToday) return;
    const pts = (daily.waveform ?? []) as unknown as WaveformPoint[];
    setWaveformData(pts as any);
    const hrs   = pts.map(p => p.hr_bpm).filter((v): v is number => v !== null);
    const hrsvs = pts.map(p => p.rmssd_ms).filter((v): v is number => v !== null);
    const h = avg(hrs);
    const v = avg(hrsvs);
    setAvgHR(h !== null ? Math.round(h) : null);
    setAvgHRV(v !== null ? Math.round(v) : null);
  }, [isToday, daily.waveform]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      if (isToday) {
        await daily.refresh();
      } else {
        await Promise.all([load(), fetchWaveformMetrics()]);
      }
    } finally {
      setRefreshing(false);
    }
  }, [fetchWaveformMetrics, isToday, daily.refresh]);

  const balance      = netBalance !== null ? Math.round(netBalance) : null;
  const balanceSign  = balance !== null ? (balance >= 0 ? '+' + balance : String(balance)) : '—';
  const balanceProgress = netBalance !== null ? (netBalance + 100) / 200 : 0.5;
  const balanceColor = (netBalance ?? 0) >= 0 ? ZEN.colors.recovery : ZEN.colors.stress;
  const balanceLabel = balance === null ? '—'
    : balance >= 30  ? 'Recovery surplus'
    : balance >= 5   ? 'Slight surplus'
    : balance >= -5  ? 'Balanced'
    : balance >= -30 ? 'Mild stress debt'
    : 'High stress debt';

  return (
    <ZenScreen
      scrollable
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={ZEN.colors.readiness}
        />
      }
    >
      <TopHeader
        eyebrow="Balance"
        title="Net Balance"
        leftIcon={<ArrowLeft size={18} color={ZEN.colors.textNear} />}
        onLeftPress={() => nav.goBack()}
      />

      {loading ? (
        <View style={s.center}>
          <ActivityIndicator color={ZEN.colors.readiness} size="large" />
        </View>
      ) : (
        <>
          {/* ── 1. Score ── */}
          <SurfaceCard style={s.scoreCard}>
            <View style={s.ringRow}>
              <ScoreRing
                value={balanceSign}
                suffix=""
                progress={balanceProgress}
                color={balanceColor}
                size={136}
                stroke={10}
              />
            </View>
            <Text style={[s.balanceLabel, { color: balanceColor }]}>{balanceLabel}</Text>
            <Text style={s.synthesis}>
              {(netBalance ?? 0) >= 0
                ? 'Recovery is outpacing stress. Good conditions for a productive day.'
                : 'Stress load is ahead of recovery. Prioritise rest and conservation.'}
            </Text>
            {/* Sub-scores */}
            <View style={s.subRow}>
              <View style={s.subItem}>
                <Text style={[s.subNum, { color: ZEN.colors.stress }]}>
                  {stressScore !== null ? Math.round(stressScore) : '—'}
                </Text>
                <Text style={s.subLabel}>Stress</Text>
              </View>
              <View style={s.subDivider} />
              <View style={s.subItem}>
                <Text style={[s.subNum, { color: ZEN.colors.recovery }]}>
                  {recoveryScore !== null ? Math.round(recoveryScore) : '—'}
                </Text>
                <Text style={s.subLabel}>Recovery</Text>
              </View>
            </View>
          </SurfaceCard>

          {/* ── 2. Intraday diverging window chart ── */}
          {waveformData.length > 0 && morningAvg !== null && (
            <DivergingWindowChart
              windows={waveformData}
              morningAvg={morningAvg}
            />
          )}

          {/* ── 3. Live biometric tiles ── */}
          <View style={s.tilesSection}>
            <Text style={[s.tilesEyebrow, { fontSize: 10, textTransform: 'uppercase', letterSpacing: 2, color: ZEN.colors.textMuted }]}>Live averages</Text>
            <View style={s.tilesGrid}>
              <MetricTile label="Heart Rate" value={avgHR !== null ? String(avgHR) : '—'} unit="bpm" color={ZEN.colors.stress} icon={Heart} />
              <MetricTile label="HRV · RMSSD" value={avgHRV !== null ? String(avgHRV) : '—'} unit="ms" color={ZEN.colors.recovery} icon={Activity} />
              <MetricTile label="Resp. Rate" value="—" unit="br/min" color={ZEN.colors.readiness} note="Phase 2" icon={Wind} />
              <MetricTile label="Blood O₂" value="—" unit="SpO₂ %" color="rgba(150,180,255,0.9)" note="Phase 2" icon={Droplets} />
            </View>
          </View>
        </>
      )}
    </ZenScreen>
  );
}

// ── MetricTile ────────────────────────────────────────────────────────────────
function MetricTile({
  label, value, unit, color, note, icon: Icon,
}: { label: string; value: string; unit: string; color: string; note?: string; icon?: React.ComponentType<any> }) {
  return (
    <SurfaceCard style={s.tile}>
      {Icon && <Icon size={16} color={color} style={{ marginBottom: 6 }} />}
      <Text style={s.tileLabel}>{label}</Text>
      <Text style={[s.tileValue, { color }]}>{value}</Text>
      <Text style={s.tileUnit}>{note ?? unit}</Text>
    </SurfaceCard>
  );
}

const s = StyleSheet.create({
  center:       { flex: 1, alignItems: 'center', justifyContent: 'center', paddingVertical: 80 },
  // Score card
  scoreCard:    { gap: 8 },
  ringRow:      { alignItems: 'center', marginBottom: 4 },
  balanceLabel: { fontSize: 18, fontWeight: '600', textAlign: 'center' },
  synthesis:    { fontSize: 13, color: ZEN.colors.textLabel, lineHeight: 20, textAlign: 'center' },
  subRow:       { flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
                  marginTop: 8, gap: 0 },
  subItem:      { alignItems: 'center', flex: 1 },
  subNum:       { fontSize: 26, fontWeight: '700', letterSpacing: -0.5 },
  subLabel:     { marginTop: 2, fontSize: 11, color: ZEN.colors.textMuted,
                  textTransform: 'uppercase', letterSpacing: 1.4 },
  subDivider:   { width: 1, height: 36, backgroundColor: ZEN.colors.border, marginHorizontal: 8 },
  // Tiles
  tilesSection: { marginTop: 4 },
  tilesEyebrow: { marginBottom: 10 },
  tilesGrid:    { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  tile:         { flex: 1, minWidth: '44%', gap: 4, alignItems: 'flex-start' },
  tileLabel:    { fontSize: 11, color: ZEN.colors.textMuted, textTransform: 'uppercase',
                  letterSpacing: 1.4, marginBottom: 2 },
  tileValue:    { fontSize: 32, fontWeight: '700', letterSpacing: -1 },
  tileUnit:     { fontSize: 11, color: ZEN.colors.textMuted, marginTop: 2 },
});
