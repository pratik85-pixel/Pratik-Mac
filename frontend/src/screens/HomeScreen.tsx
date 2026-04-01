import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity,
  ActivityIndicator, Animated, RefreshControl, Modal,
} from 'react-native';
import { Bluetooth, BatteryFull } from 'lucide-react-native';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import EmptyState from '../components/EmptyState';
import { useDailyData } from '../contexts/DailyDataContext';
import type { HomeStackParamList } from '../navigation/AppNavigator';
import type { MorningBriefResponse, StressWindow, RecoveryWindow } from '../types';
import { getName } from '../store/auth';
import { polarService } from '../services/PolarService';
import { getCurrentSession, endSession, type SessionHistoryItem } from '../api/session';
import { tagWindow } from '../api/tagging';
import {
  ZEN,
  ZenScreen,
  SectionCard,
  SectionEyebrow,
  StressEventRow,
  RecoveryEventRow,
  TagBottomSheet,
} from '../ui/zenflow-ui-kit';
import { ArcGauge } from '../ui/ArcGauge';

const STRESS_OPTIONS = [
  'Workout', 'Work / calls', 'Argument',
  'Commute', 'Caffeine', 'Poor sleep', 'Other physical',
];

const RECOVERY_OPTIONS = [
  'Walk / nature', 'Reading / music', 'Social / family',
  'ZenFlow session', 'Nap', 'Breath work',
];

// ─── helpers ──────────────────────────────────────────────────────────────────

function getTodayLabel(): string {
  return new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
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
      return ZEN.colors.textMuted;
  }
}

function dayStateFromReadiness(value: number | null): 'green' | 'yellow' | 'relaxed' | 'red' {
  const safe = Math.max(0, Math.min(100, value ?? 50));
  if (safe > 75) return 'green';
  if (safe >= 50) return 'yellow';
  if (safe >= 25) return 'relaxed';
  return 'red';
}

function dayStateColor(state: 'green' | 'yellow' | 'relaxed' | 'red'): string {
  if (state === 'green') return ZEN.colors.recovery;
  if (state === 'red') return '#FF5A5F';
  if (state === 'relaxed') return ZEN.colors.readiness;
  return ZEN.colors.readiness;
}

function dayTypeLabelFromState(state: 'green' | 'yellow' | 'relaxed' | 'red'): string {
  if (state === 'green') return 'High intensity day';
  if (state === 'yellow') return 'Moderate day';
  if (state === 'relaxed') return 'Relaxed day';
  return 'Red day';
}

function sleepScoreFromArea(area: number | null | undefined): number | null {
  if (area == null || area <= 0) return null;
  // Fallback only when backend sleep_recovery_score is unavailable.
  return Math.round(Math.min(100, Math.max(0, area / 4)));
}

function normalizePercent(v: number | null | undefined): number {
  if (v == null || !Number.isFinite(v)) return 0;
  return Math.max(0, Math.min(100, Number(v)));
}

function normalizePercentScore(v: number | null | undefined): number | null {
  if (v == null || !Number.isFinite(v)) return null;
  const n = Number(v);
  return Math.max(0, Math.min(100, n));
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '--:--';
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
}

function readinessFromSignals(
  sleepRecovery: number | null,
  wakingRecovery: number | null,
  stressLoad: number | null,
): number | null {
  const components: Array<{ value: number; weight: number }> = [];
  if (sleepRecovery != null) components.push({ value: sleepRecovery, weight: 0.45 });
  if (wakingRecovery != null) components.push({ value: wakingRecovery, weight: 0.35 });
  if (stressLoad != null) components.push({ value: 100 - stressLoad, weight: 0.20 });
  if (!components.length) return null;
  const weightSum = components.reduce((s, c) => s + c.weight, 0);
  const weighted = components.reduce((s, c) => s + (c.value * c.weight), 0) / weightSum;
  return Math.round(Math.max(0, Math.min(100, weighted)));
}

/** True when API returned a non-empty brief (strict empty → all null). */
function hasCoachBriefContent(mb: MorningBriefResponse | null | undefined): boolean {
  if (!mb) return false;
  return [mb.brief_text, mb.evidence, mb.one_action].some(
    (s) => (s ?? '').trim().length > 0,
  );
}

// ─── Screen ───────────────────────────────────────────────────────────────────

export default function HomeScreen() {
  const nav = useNavigation<NativeStackNavigationProp<HomeStackParamList>>();
  const {
    summary: data,
    loading,
    error,
    refresh,
    stressState,
    morningRecap,
    morningBrief,
    planHome,
    stressWindows,
    recoveryWindows,
    patchStressWindow,
  } = useDailyData();
  const [refreshing, setRefreshing] = useState(false);
  const noData = !data && !loading && !error;
  const [name, setName] = useState('');
  const [polarStatus, setPolarStatus] = useState(polarService.status);
  const [batteryPct, setBatteryPct] = useState<number | null>(polarService.batteryPct);
  const [openSession, setOpenSession] = useState<SessionHistoryItem | null>(null);
  const [isOutlookExpanded, setIsOutlookExpanded] = useState(false);
  const [isMyDayOpen, setIsMyDayOpen] = useState(false);
  const [tagTarget, setTagTarget] = useState<{ type: 'stress' | 'recovery'; w: StressWindow | RecoveryWindow } | null>(null);
  const [isTagSheetOpen, setTagSheetOpen] = useState(false);
  const batteryPulseAnim = useRef(new Animated.Value(1)).current;

  // (options moved to module scope)

  // ── Polar status dot ─────────────────────────────────────────────────────
  const pulseAnim = useRef(new Animated.Value(1)).current;
  const dotColor  = polarStatus === 'streaming'
    ? ZEN.colors.recovery
    : (polarStatus === 'scanning' || polarStatus === 'connecting' || polarStatus === 'connected')
    ? ZEN.colors.readiness
    : '#FF4D4F';

  const batteryColor =
    batteryPct == null
      ? ZEN.colors.textMuted
      : batteryPct >= 30
        ? ZEN.colors.recovery
        : batteryPct >= 10
          ? ZEN.colors.readiness
          : '#FF4D4F';

  useEffect(() => {
    if (polarStatus === 'streaming') {
      const anim = Animated.loop(
        Animated.sequence([
          Animated.timing(pulseAnim, { toValue: 0.25, duration: 600, useNativeDriver: true }),
          Animated.timing(pulseAnim, { toValue: 1,    duration: 600, useNativeDriver: true }),
        ])
      );
      anim.start();
      return () => anim.stop();
    } else {
      pulseAnim.setValue(1);
    }
  }, [polarStatus]);

  useEffect(() => {
    if (batteryPct != null && batteryPct < 10) {
      const anim = Animated.loop(
        Animated.sequence([
          Animated.timing(batteryPulseAnim, { toValue: 0.25, duration: 650, useNativeDriver: true }),
          Animated.timing(batteryPulseAnim, { toValue: 1,    duration: 650, useNativeDriver: true }),
        ])
      );
      anim.start();
      return () => anim.stop();
    } else {
      batteryPulseAnim.setValue(1);
    }
  }, [batteryPct]);

  const loadSideEffects = useCallback(async () => {
    // Check for any session that was never formally closed
    try {
      const r = await getCurrentSession();
      const s = r.data;
      if (s?.is_open) {
        const ageH = (Date.now() - new Date(s.started_at).getTime()) / 3_600_000;
        if (ageH < 24) setOpenSession(s);
      }
    } catch {}
  }, []);

  useFocusEffect(useCallback(() => {
    // Trigger a context refresh so data is fresh when screen comes into focus
    refresh();
    loadSideEffects();
    setPolarStatus(polarService.status);
    const unsub = polarService.subscribeStatus((s) => setPolarStatus(s));
    const unsubBatt = polarService.subscribeBattery((pct) => setBatteryPct(pct));
    // Polling is handled by DailyDataContext — no local interval needed
    return () => { unsub(); unsubBatt(); };
  }, [refresh, loadSideEffects]));

  useEffect(() => {
    getName().then((n) => setName(n ?? ''));
  }, []);

  const onRefresh = () => {
    setRefreshing(true);
    refresh({ clearCoach: true });
    loadSideEffects().finally(() => setRefreshing(false));
  };

  const greeting = () => {
    const h = new Date().getHours();
    if (h < 12) return `Good morning${name ? `, ${name}` : ''}`;
    if (h < 18) return `Good afternoon${name ? `, ${name}` : ''}`;
    return `Good evening${name ? `, ${name}` : ''}`;
  };

  // ── Data snapshots used by UI guards ──────────────────────────────────────
  const d = (data ?? {}) as any;
  const rawStressScore = d.stress_load_score ?? d.stress_summary?.daily_load ?? null;
  const stressScore = normalizePercentScore(rawStressScore);
  // Trust backend sleep_recovery_score directly.
  // null  → no validated sleep boundary → show "—"
  // number → valid score, show it (even if 0)
  const sleepRecoveryScoreRaw = morningRecap?.summary?.sleep_recovery_score ?? null;
  const sleepRecoveryForReadiness = normalizePercentScore(sleepRecoveryScoreRaw);
  // Home 3-ring card uses today's live values for consistency.
  const currentSleepRecovery = normalizePercentScore(d.sleep_recovery_score);
  const recapStressForReadiness = normalizePercentScore(morningRecap?.summary?.stress_load_score ?? null);
  const recapWakingForReadiness = normalizePercentScore(morningRecap?.summary?.waking_recovery_score ?? null);
  const currentWakingRecovery = normalizePercentScore(d.waking_recovery_score);
  const todayReadiness = readinessFromSignals(
    sleepRecoveryForReadiness,
    recapWakingForReadiness,
    recapStressForReadiness,
  );
  const todayReadinessSafe = todayReadiness == null ? null : Math.max(0, Math.min(100, Number(todayReadiness)));
  const stressScore10 = stressScore == null ? null : Math.round((Math.max(0, Math.min(100, stressScore)) / 10) * 10) / 10;
  // Home now shows waking recovery explicitly (no legacy combined fallback).
  const currentRecoveryCombined = currentWakingRecovery;
  const dominanceSide = useMemo<'stress' | 'recovery' | null>(() => {
    const LOOKBACK_MS = 20 * 60 * 1000; // last 20 mins = 4 x 5-min windows
    const THRESHOLD = 0.2;
    const MIN_SIGNAL_SUM = 6;
    const now = Date.now();
    const cutoff = now - LOOKBACK_MS;

    const stressRecent = (stressWindows ?? []).reduce((sum, w) => {
      const ts = Date.parse(w.ended_at || w.started_at);
      if (!Number.isFinite(ts) || ts < cutoff || ts > now) return sum;
      const v = Number(w.stress_contribution_pct ?? 0);
      return sum + (Number.isFinite(v) ? Math.max(0, v) : 0);
    }, 0);

    const recoveryRecent = (recoveryWindows ?? []).reduce((sum, w) => {
      const ts = Date.parse(w.ended_at || w.started_at);
      if (!Number.isFinite(ts) || ts < cutoff || ts > now) return sum;
      const v = Number(w.recovery_contribution_pct ?? 0);
      return sum + (Number.isFinite(v) ? Math.max(0, v) : 0);
    }, 0);

    const total = stressRecent + recoveryRecent;
    if (total < MIN_SIGNAL_SUM) return null;

    const dominance = (recoveryRecent - stressRecent) / (total + 1e-6);
    if (dominance >= THRESHOLD) return 'recovery';
    if (dominance <= -THRESHOLD) return 'stress';
    return null;
  }, [stressWindows, recoveryWindows]);

  // ── Loading ──────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <ZenScreen scrollable={false}>
        <View style={s.center}>
          <ActivityIndicator color={ZEN.colors.readiness} size="large" />
        </View>
      </ZenScreen>
    );
  }

  // ── Empty / no device ────────────────────────────────────────────────────
  if (noData || (!error && !data)) {
    const bandStreaming  = polarStatus === 'streaming';
    const bandConnecting = polarStatus === 'scanning' || polarStatus === 'connecting' || polarStatus === 'connected';
    const btOff          = polarStatus === 'bluetooth_off';

    // When band is streaming but no API data yet, fall through to dashboard
    // so the user sees — placeholders instead of a dead-end calibrating screen
    if (!bandStreaming) {
      const icon = btOff ? 'bluetooth-outline'
        : bandConnecting  ? 'radio-outline'
        : 'watch-outline';

      const title = btOff ? 'Turn on Bluetooth'
        : bandConnecting   ? 'Finding your band…'
        : 'Wear your band to start';

      const message = btOff
        ? 'ZenFlow needs Bluetooth to connect to your Polar band.'
        : bandConnecting
        ? 'Connecting to your Polar band. Keep it on your arm.'
        : `Put on your Polar band and open Bluetooth. ZenFlow will connect automatically${name ? `, ${name}` : ''}.`;

      return (
        <ZenScreen>
          <EmptyState icon={icon} title={title} message={message} />
          <TouchableOpacity onPress={() => refresh({ clearCoach: true })} style={s.retryBtn}>
            <Text style={s.retryText}>Refresh</Text>
          </TouchableOpacity>
        </ZenScreen>
      );
    }
    // bandStreaming + no data: fall through to dashboard with null scores
  }

  // ── Error ────────────────────────────────────────────────────────────────
  if (error) {
    return (
      <ZenScreen>
        <EmptyState
          icon="cloud-offline-outline"
          title="Can't reach server"
          message="Check your internet connection and try again."
        />
        <TouchableOpacity onPress={() => refresh({ clearCoach: true })} style={s.retryBtn}>
          <Text style={s.retryText}>Try again</Text>
        </TouchableOpacity>
      </ZenScreen>
    );
  }

  // ── Data ─────────────────────────────────────────────────────────────────
  const goalLoad =
    planHome?.day_type === 'green'
      ? 70
      : planHome?.day_type === 'yellow'
        ? 55
        : 45;
  const recoveryGoal =
    planHome?.day_type === 'green'
      ? 70
      : planHome?.day_type === 'yellow'
        ? 62
        : 55;
  const ringColor = stressState?.stress_now_zone ? zoneAccent(stressState.stress_now_zone) : ZEN.colors.stress;
  const stressRingColor =
    stressScore != null && stressScore >= goalLoad ? ZEN.colors.stress : ringColor;
  const recoveryRingColor =
    currentRecoveryCombined != null && currentRecoveryCombined >= recoveryGoal
      ? ZEN.colors.recovery
      : ZEN.colors.readiness;
  /** When recap has no yesterday row, ignore stale morningBrief from cache/order of responses. */
  const noStrictYesterday = morningRecap != null && morningRecap.summary == null;
  const hasBrief = !noStrictYesterday && hasCoachBriefContent(morningBrief);
  const briefTextRaw = (morningBrief?.brief_text ?? '').trim();
  const briefText = briefTextRaw
    .replace(/opening balance/gi, 'readiness')
    .replace(/net balance/gi, 'readiness')
    .replace(/balance/gi, 'readiness');
  const readinessSafe = Math.max(0, Math.min(100, todayReadinessSafe ?? 50));
  const todayDayState = dayStateFromReadiness(todayReadinessSafe);
  const normalizedState = String(morningBrief?.day_state ?? planHome?.day_type ?? '').trim().toLowerCase();
  const coachDayState =
    normalizedState === 'green' || normalizedState === 'yellow' || normalizedState === 'relaxed' || normalizedState === 'red'
      ? normalizedState
      : null;
  // UI contract: readiness label/color must follow readiness score tiers.
  // Only fall back to coach/plan state when readiness score is unavailable.
  const displayDayState = todayReadinessSafe != null ? todayDayState : (coachDayState ?? 'yellow');
  const dayTypeLabel = dayTypeLabelFromState(displayDayState);
  const dayIconColor = dayStateColor(displayDayState);
  const fallbackBrief =
    `Today is a ${displayDayState} day. Your readiness score is ${readinessSafe}. ` +
    `Strain target is ${goalLoad}. Your body is signaling this effort is appropriate today.`;
  const briefBody = !hasBrief
    ? 'No coach brief yet. Wear your band so yesterday can be summarized and today\'s guidance can unlock.'
    : (/net balance/i.test(briefText) || /readiness[^0-9-]*-/.test(briefText))
      ? fallbackBrief
      : `${briefText} ${(morningBrief?.evidence ?? '').replace(/net balance/gi, 'readiness').replace(/balance/gi, 'readiness')}`.trim();
  const confidenceHeartColor =
    stressState?.confidence === 'low'
      ? '#FF5A5F'
      : stressState?.confidence === 'medium'
        ? '#F2D14C'
        : '#39E27D';
  const pipelineScoreConfidence = data?.score_confidence;
  const myDayCount = (stressWindows?.length ?? 0) + (recoveryWindows?.length ?? 0);

  const combinedEvents = (() => {
    const stress = (stressWindows ?? []).map(w => ({
      key: `stress:${String((w as any).id)}`,
      type: 'stress' as const,
      started_at: String((w as any).started_at),
      window: w,
    }));
    const recovery = (recoveryWindows ?? []).map(w => ({
      key: `recovery:${String((w as any).id)}`,
      type: 'recovery' as const,
      started_at: String((w as any).started_at),
      window: w,
    }));
    return [...stress, ...recovery].sort((a, b) =>
      (new Date(b.started_at).getTime() || 0) - (new Date(a.started_at).getTime() || 0)
    );
  })();

  const openTagSheet = (type: 'stress' | 'recovery', w: StressWindow | RecoveryWindow) => {
    setTagTarget({ type, w });
    setTagSheetOpen(true);
  };

  const handleTagSelect = async (slug: string) => {
    if (!tagTarget) return;
    const { type, w } = tagTarget;
    setTagTarget(null);
    setTagSheetOpen(false);
    try {
      await tagWindow({ window_id: String((w as any).id), window_type: type, tag: slug });
      if (type === 'stress') {
        patchStressWindow(String((w as any).id), { tag: slug, tag_source: 'user_confirmed' } as any);
      }
      refresh();
    } catch (e) {
      const err: any = e;
      console.error('[Home] tagWindow failed:', err?.response?.status, err?.response?.data ?? err?.message ?? err);
      refresh();
    }
  };

  return (
    <ZenScreen
      scrollable
      scrollEnabled={isMyDayOpen || isOutlookExpanded}
      style={s.scroll}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={ZEN.colors.readiness}
        />
      }
    >
      {/* ── Header row ────────────────────────────────────────────── */}
      <View style={s.headerRow}>
        <View>
          <Text style={s.eyebrow}>{getTodayLabel()}</Text>
          <Text style={s.greeting}>{greeting()}</Text>
        </View>
        <View style={s.headerRight}>
          <Animated.View style={[s.polarIconWrap, { opacity: polarStatus === 'streaming' ? pulseAnim : 1 }]}>
            <Bluetooth size={20} color={dotColor} strokeWidth={2.2} />
          </Animated.View>
          <Animated.View style={{ opacity: batteryPct != null && batteryPct < 10 ? batteryPulseAnim : 1 }}>
            <View style={s.batteryRow}>
              <BatteryFull size={18} color={batteryColor} strokeWidth={2.2} />
              <Text style={[s.batteryText, { color: batteryColor }]}>
                {batteryPct == null ? '--%' : `${Math.round(batteryPct)}%`}
              </Text>
              {batteryPct != null && batteryPct < 10 ? (
                <Text style={s.batteryRecharge}>Recharge</Text>
              ) : null}
            </View>
          </Animated.View>
        </View>
      </View>

      {/* ── Collecting banner (shown when band streaming but no scores yet) ── */}
      {!data && polarStatus === 'streaming' && (
        <View style={s.collectingBanner}>
          <Text style={s.collectingText}>⏳ Collecting data — scores appear once your first session is processed</Text>
        </View>
      )}

      {/* ── Today's outlook (readiness + coach brief) ───────────────────────── */}
      <TouchableOpacity activeOpacity={0.9} onPress={() => nav.navigate('MorningSummary')}>
        <SectionCard style={[s.outlookCard, isOutlookExpanded ? s.outlookCardExpanded : null]}>
          <View style={s.outlookTopRow}>
            <View style={s.outlookTitleBlock}>
              <SectionEyebrow>TODAY'S OUTLOOK</SectionEyebrow>
              <Text style={s.outlookSubtext}>basis yesterday&apos;s data</Text>
            </View>
            <TouchableOpacity
              style={s.outlookExpandBtn}
              activeOpacity={0.8}
              onPress={(e) => {
                e.stopPropagation?.();
                setIsOutlookExpanded(v => !v);
              }}
            >
              <Text style={s.outlookExpandChevron}>{isOutlookExpanded ? '⌃' : '⌄'}</Text>
            </TouchableOpacity>
          </View>

          <View style={s.readinessCenter}>
            <ArcGauge
              value={todayReadinessSafe}
              color={dayStateColor(todayDayState)}
              size={97}
              stroke={6}
              valueFontSize={19}
              displayValue={todayReadinessSafe == null ? '—' : `${Math.round(todayReadinessSafe)}`}
              displaySuffix={todayReadinessSafe == null ? undefined : '/100'}
            />
            <Text style={s.dayTypeLabel}>{dayTypeLabel}</Text>
          </View>

          <Text style={s.briefMain} numberOfLines={isOutlookExpanded ? undefined : 7}>
            {briefBody}
          </Text>
        </SectionCard>
      </TouchableOpacity>

      {/* ── Right now: live stress zone + trend (new API) ── */}
      {stressState ? (
        <TouchableOpacity activeOpacity={0.9} onPress={() => nav.navigate('RealTimeData')}>
          <SectionCard style={[s.nowCard, { borderLeftColor: zoneAccent(stressState.stress_now_zone), borderLeftWidth: 3 }]}>
          <View style={s.nowTopRow}>
            <View style={s.nowTopRowSide} />
            {pipelineScoreConfidence && pipelineScoreConfidence !== 'high' ? (
              <Text style={s.nowConfidenceCenter} numberOfLines={1}>
                {pipelineScoreConfidence === 'low'
                  ? 'Calibrating Baseline'
                  : 'Calibrating Baseline'}
              </Text>
            ) : null}
            <View style={s.nowTopRowSideEnd}>
              <View style={[s.nowLivePill, { borderColor: 'rgba(255,255,255,0.18)' }]}>
                <Text style={[s.liveBadgeText, { color: confidenceHeartColor }]}>LIVE</Text>
              </View>
            </View>
          </View>
          <View style={s.currentDualRingRow}>
            <View style={s.currentRingCell}>
              <ArcGauge
                value={stressScore}
                color={stressRingColor}
                size={84}
                stroke={6}
                goal={goalLoad}
                valueFontSize={18}
                displayValue={stressScore10 == null ? '—' : `${stressScore10.toFixed(1)}`}
                displaySuffix="/10"
              />
              <Text style={s.currentRingLabel}>Stress{'\n'}load</Text>
              {dominanceSide === 'stress' ? <View style={s.dominanceBar} /> : null}
            </View>
            <View style={s.currentRingCell}>
              <ArcGauge value={currentRecoveryCombined} color={recoveryRingColor} size={84} stroke={6} goal={recoveryGoal} valueFontSize={18} />
              <Text style={s.currentRecoveryLabel}>Waking{'\n'}recovery</Text>
              {dominanceSide === 'recovery' ? <View style={s.dominanceBar} /> : null}
            </View>
            <View style={s.currentRingCell}>
              <ArcGauge
                value={currentSleepRecovery}
                color={ZEN.colors.readiness}
                size={84}
                stroke={6}
                valueFontSize={18}
                displayValue={currentSleepRecovery == null ? '—' : `${Math.round(currentSleepRecovery)}%`}
              />
              <Text style={s.currentSleepLabel}>Sleep{'\n'}recovery</Text>
            </View>
          </View>
          </SectionCard>
        </TouchableOpacity>
      ) : null}

      {/* ── My day (expandable taggable events) ─────────────────────────────── */}
      <SectionCard style={s.myDayCard}>
        <TouchableOpacity
          style={s.myDayHeader}
          activeOpacity={0.82}
          onPress={() => setIsMyDayOpen(v => !v)}
        >
          <SectionEyebrow>MY DAY</SectionEyebrow>
          <View style={s.myDayRight}>
            <Text style={s.myDayCount}>{myDayCount}</Text>
            <Text style={s.myDayChevron}>{isMyDayOpen ? '⌃' : '⌄'}</Text>
          </View>
        </TouchableOpacity>

        {isMyDayOpen ? (
          <View style={s.myDayBody}>
            {combinedEvents.length === 0 ? (
              <Text style={s.myDayEmpty}>No events yet today.</Text>
            ) : (
              <View style={s.myDayList}>
                {combinedEvents.map(ev => {
                  if (ev.type === 'stress') {
                    const w = ev.window as StressWindow;
                    const row = {
                      id: String((w as any).id),
                      time: fmtTime(String((w as any).started_at)),
                      label: (w as any).tag_candidate ?? (w as any).tag ?? 'Unnamed event',
                      contribution: Math.round((w as any).stress_contribution_pct ?? 0),
                      tagged: (w as any).tag !== null && (w as any).tag !== undefined,
                      tagLabel: (w as any).tag ?? undefined,
                      onTag: (w as any).tag ? undefined : () => openTagSheet('stress', w),
                    };
                    return <StressEventRow key={ev.key} event={row as any} />;
                  }
                  const w = ev.window as RecoveryWindow;
                  const row = {
                    id: String((w as any).id),
                    time: fmtTime(String((w as any).started_at)),
                    label: (w as any).tag ?? 'Rest window',
                    contribution: Math.round((w as any).recovery_contribution_pct ?? 0),
                    tagged: (w as any).tag !== null && (w as any).tag !== undefined,
                    tagLabel: (w as any).tag ?? undefined,
                    onTag: (w as any).tag ? undefined : () => openTagSheet('recovery', w),
                  };
                  return <RecoveryEventRow key={ev.key} event={row as any} />;
                })}
              </View>
            )}
          </View>
        ) : null}
      </SectionCard>

      <TagBottomSheet
        visible={isTagSheetOpen && tagTarget != null}
        options={tagTarget?.type === 'stress' ? STRESS_OPTIONS : RECOVERY_OPTIONS}
        eventLabel={tagTarget?.type === 'stress' ? 'Stress Event' : 'Recovery Window'}
        eventTime={tagTarget?.w ? fmtTime(String((tagTarget.w as any).started_at)) : ''}
        onSelect={handleTagSelect}
        onSkip={() => { setTagTarget(null); setTagSheetOpen(false); }}
      />

      {/* ── Open session modal ───────────────────────────────────── */}
      <Modal
        visible={openSession !== null}
        transparent
        animationType="fade"
        onRequestClose={() => setOpenSession(null)}
      >
        <View style={s.modalOverlay}>
          <View style={s.modalCard}>
            <Text style={s.modalTitle}>Session still open</Text>
            <Text style={s.modalBody}>
              You started a session at{' '}
              {openSession ? new Date(openSession.started_at).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true }) : ''}{' '}
              and it was never closed.
            </Text>
            <TouchableOpacity
              style={s.modalBtnPrimary}
              onPress={() => {
                const id = openSession?.session_id;
                setOpenSession(null);
                if (id) (nav as any).navigate('SessionSummary', { sessionId: id });
              }}
            >
              <Text style={s.modalBtnPrimaryText}>Resume</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={s.modalBtnSecondary}
              onPress={async () => {
                const id = openSession?.session_id;
                setOpenSession(null);
                if (id) {
                  try { await endSession(id); } catch {}
                  refresh();
                }
              }}
            >
              <Text style={s.modalBtnSecondaryText}>End it now</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={() => setOpenSession(null)} style={s.modalDismiss}>
              <Text style={s.modalDismissText}>Dismiss</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

    </ZenScreen>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const s = StyleSheet.create({
  // keep home non-scroll by default (scrollEnabled toggles on expand)
  scroll: { gap: 6, paddingBottom: 12, flexGrow: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },

  polarDot: {
    width:        12,
    height:       12,
    borderRadius: 6,
    marginTop:    10,
  },
  polarIconWrap: {
    width: 24,
    height: 24,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 4,
  },
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  batteryRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  batteryText: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.2,
  },
  batteryRecharge: {
    fontSize: 10,
    color: '#FF4D4F',
    fontWeight: '700',
    marginLeft: 4,
  },

  headerRow: {
    flexDirection:  'row',
    alignItems:     'flex-start',
    justifyContent: 'space-between',
    marginBottom:   0,
  },
  eyebrow: {
    fontSize:      11,
    textTransform: 'uppercase',
    letterSpacing: 2.6,
    color:        ZEN.colors.textMuted,
  },
  greeting: {
    marginTop:     0,
    fontSize:      15,
    fontWeight:    '600',
    letterSpacing: -0.5,
    color:         ZEN.colors.white,
  },
  iconBtn: {
    width:           40,
    height:          40,
    borderRadius:    20,
    borderWidth:     1,
    borderColor:     'rgba(255,255,255,0.15)',
    backgroundColor: 'rgba(255,255,255,0.05)',
    alignItems:      'center',
    justifyContent:  'center',
    marginTop:       8,
  },
  iconBtnText: { fontSize: 16, color: ZEN.colors.textNear },

  retryBtn: {
    marginHorizontal: 32,
    marginTop:        16,
    borderRadius:     20,
    borderWidth:      1,
    borderColor:      ZEN.colors.borderStrong,
    backgroundColor:  ZEN.colors.surfaceStrong,
    paddingVertical:  14,
    alignItems:       'center',
  },
  retryText: {
    fontSize:   15,
    fontWeight: '600',
    color:     ZEN.colors.readiness,
  },
  collectingBanner: {
    marginHorizontal: 16,
    marginBottom:     12,
    paddingHorizontal: 14,
    paddingVertical:   10,
    borderRadius:      10,
    backgroundColor:  'rgba(255,255,255,0.07)',
    borderWidth:       1,
    borderColor:      'rgba(255,255,255,0.12)',
  },
  collectingText: {
    fontSize:   13,
    color:      ZEN.colors.textMuted,
    lineHeight: 18,
  },

  readinessCard: {
    gap: 8,
    paddingVertical: 10,
  },
  readinessTopRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  outlookCard: { gap: 10, paddingVertical: 12, minHeight: 308 },
  outlookCardExpanded: { minHeight: 360 },
  outlookTopRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  outlookTitleBlock: { gap: 2 },
  outlookSubtext: {
    fontSize: 10,
    color: ZEN.colors.textMuted,
    letterSpacing: 0.2,
    marginTop: -2,
  },
  outlookExpandBtn: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    alignItems: 'flex-end',
    justifyContent: 'center',
  },
  outlookExpandChevron: {
    fontSize: 16,
    color: ZEN.colors.textMuted,
    marginTop: -2,
    fontWeight: '700',
  },
  readinessCenter: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingTop: 2,
    gap: 8,
  },
  readinessLabel: {
    fontSize: 12,
    color: ZEN.colors.textSecondary,
    textTransform: 'uppercase',
    letterSpacing: 1.1,
  },
  confidenceHint: {
    marginTop: 4,
    paddingHorizontal: 8,
    fontSize: 11,
    lineHeight: 16,
    color: ZEN.colors.textMuted,
    textAlign: 'center',
  },
  dayTypeLabel: {
    marginTop: 2,
    fontSize: 12,
    color: ZEN.colors.textSecondary,
    textAlign: 'center',
  },

  recapCard: { gap: 10, paddingVertical: 12, borderColor: 'rgba(120,180,255,0.22)' },
  recapHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  recapHeaderActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  recapAckBtn: {
    borderRadius: 999,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.14)',
    backgroundColor: 'rgba(255,255,255,0.06)',
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  recapAckText: {
    fontSize: 10,
    color: ZEN.colors.textNear,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    fontWeight: '700',
  },
  recapCollapseText: {
    fontSize: 18,
    color: ZEN.colors.textNear,
    fontWeight: '700',
    lineHeight: 20,
  },
  nowLivePill: {
    minWidth: 24,
    minHeight: 24,
    alignItems: 'center',
    justifyContent: 'center',
  },
  liveBadgeText: {
    fontSize: 11,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.7,
  },
  yesterdayRings: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 8,
  },
  yRingCell: { alignItems: 'center', flex: 1, gap: 6 },
  yRingLabel: {
    fontSize: 11,
    color: ZEN.colors.textSecondary,
    textTransform: 'uppercase',
    letterSpacing: 0.9,
  },
  yesterdayFootnote: {
    fontSize: 11,
    color: ZEN.colors.textMuted,
    lineHeight: 16,
    marginTop: 2,
  },
  nowCard: { gap: 8, paddingVertical: 8 },
  nowTopRow: {
    flexDirection: 'row',
    alignItems: 'center',
    width: '100%',
    minHeight: 20,
  },
  nowTopRowSide: {
    flex: 1,
    minWidth: 0,
  },
  nowTopRowSideEnd: {
    flex: 1,
    minWidth: 0,
    alignItems: 'flex-end',
    justifyContent: 'center',
  },
  nowConfidenceCenter: {
    flexShrink: 1,
    fontSize: 11,
    lineHeight: 16,
    color: ZEN.colors.textMuted,
    textAlign: 'center',
  },
  currentDualRingRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: 6,
    marginTop: 2,
    marginBottom: 2,
  },
  currentRingCell: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'flex-start',
    gap: 6,
  },
  currentRingLabel: {
    fontSize: 11,
    color: ZEN.colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    textAlign: 'center',
    lineHeight: 14,
  },
  currentRecoveryLabel: {
    fontSize: 11,
    color: ZEN.colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    textAlign: 'center',
    lineHeight: 14,
  },
  currentSleepLabel: {
    fontSize: 11,
    color: ZEN.colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    textAlign: 'center',
    lineHeight: 14,
  },
  dominanceBar: {
    width: 52,
    height: 3,
    borderRadius: 3,
    backgroundColor: ZEN.colors.recovery,
    marginTop: 2,
  },
  coachCard: { gap: 8, paddingVertical: 14 },
  coachLine: {
    fontSize: 14,
    lineHeight: 21,
    color: ZEN.colors.textBody,
  },
  // briefCardFixed/briefTopRow replaced by outlookCard/outlookTopRow
  briefMain: {
    fontSize: 13,
    lineHeight: 21,
    color: ZEN.colors.white,
  },
  morningSummaryBtn: {
    marginTop: -2,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: ZEN.colors.border,
    backgroundColor: ZEN.colors.surfaceSoft,
    paddingHorizontal: 14,
    paddingVertical: 13,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  morningSummaryEyebrow: {
    fontSize: 11,
    textTransform: 'uppercase',
    letterSpacing: 1.4,
    color: ZEN.colors.textNear,
    fontWeight: '700',
  },
  morningSummaryRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  morningSummaryHint: {
    fontSize: 11,
    color: ZEN.colors.textMuted,
  },
  morningSummaryArrow: {
    fontSize: 18,
    color: ZEN.colors.stress,
    lineHeight: 18,
  },

  // ── My day (expandable) ─────────────────────────────────────────
  myDayCard: { gap: 10, paddingVertical: 8, marginBottom: 10 },
  myDayHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  myDayRight: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  myDayCount: { fontSize: 13, fontWeight: '500', color: ZEN.colors.textNear },
  myDayChevron: { fontSize: 14, color: ZEN.colors.textMuted, marginTop: -1, fontWeight: '500' },
  myDayBody: { gap: 10 },
  myDayEmpty: { fontSize: 13, color: ZEN.colors.textMuted, lineHeight: 18 },
  myDayList: { gap: 8 },

  // ── Open session modal ────────────────────────────────────────
  modalOverlay: {
    flex:            1,
    backgroundColor: 'rgba(0,0,0,0.72)',
    justifyContent:  'center',
    alignItems:      'center',
    paddingHorizontal: 24,
  },
  modalCard: {
    width:           '100%',
    borderRadius:    24,
    backgroundColor: ZEN.colors.surface,
    borderWidth:     1,
    borderColor:     'rgba(255,255,255,0.12)',
    padding:         24,
    gap:             12,
  },
  modalTitle: {
    fontSize:   18,
    fontWeight: '700',
    color:      ZEN.colors.white,
    letterSpacing: -0.3,
  },
  modalBody: {
    fontSize:   14,
    lineHeight: 22,
    color:      ZEN.colors.textSecondary,
  },
  modalBtnPrimary: {
    marginTop:       4,
    borderRadius:    14,
    backgroundColor: ZEN.colors.readiness,
    paddingVertical: 14,
    alignItems:      'center',
  },
  modalBtnPrimaryText: {
    fontSize:   15,
    fontWeight: '700',
    color:      '#000',
  },
  modalBtnSecondary: {
    borderRadius:    14,
    borderWidth:     1,
    borderColor:     ZEN.colors.borderStrong,
    paddingVertical: 14,
    alignItems:      'center',
  },
  modalBtnSecondaryText: {
    fontSize:   15,
    fontWeight: '600',
    color:      ZEN.colors.white,
  },
  modalDismiss: {
    paddingVertical: 8,
    alignItems:      'center',
  },
  modalDismissText: {
    fontSize: 14,
    color:    ZEN.colors.textMuted,
  },
});
