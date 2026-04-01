import React, { useMemo } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { ArrowLeft, Settings } from 'lucide-react-native';
import TopHeader from '../components/TopHeader';
import { useDailyData } from '../contexts/DailyDataContext';
import type { HomeStackParamList } from '../navigation/AppNavigator';
import { ZEN, ZenScreen, SectionCard, SectionEyebrow } from '../ui/zenflow-ui-kit';
import { ArcGauge } from '../ui/ArcGauge';

function sleepScoreFromArea(area: number | null | undefined): number | null {
  if (area == null || area <= 0) return null;
  return Math.round(Math.min(100, Math.max(0, area / 4)));
}

function normalizePercentScore(v: number | null | undefined): number | null {
  if (v == null || !Number.isFinite(v)) return null;
  const n = Number(v);
  return Math.max(0, Math.min(100, n));
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

function fmtDate(dateIso?: string | null): string {
  if (!dateIso) return '';
  const d = new Date(dateIso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

export default function MorningSummaryScreen() {
  const nav = useNavigation<NativeStackNavigationProp<HomeStackParamList>>();
  const { morningRecap, morningBrief, planHome } = useDailyData();
  const summary = morningRecap?.summary;

  // If recap isn't ready, do not fall back to "today" — show a stable placeholder.
  if (!morningRecap?.for_date || summary == null) {
    return (
      <ZenScreen scrollable={false}>
        <TopHeader
          eyebrow="Yesterday Summary"
          title="YESTERDAY SUMMARY"
          subtitle=""
          leftIcon={<ArrowLeft size={18} color={ZEN.colors.textNear} />}
          onLeftPress={() => nav.goBack()}
          rightIcon={<Settings size={18} color={ZEN.colors.textNear} />}
        />
        <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={s.content}>
          <SectionCard style={s.whyCard}>
            <SectionEyebrow>Recap generating…</SectionEyebrow>
            <Text style={s.whyBody}>
              Wear your band in the morning so last night can be closed and yesterday’s summary can populate.
            </Text>
          </SectionCard>
        </ScrollView>
      </ZenScreen>
    );
  }

  const stressRaw = summary?.stress_load_score ?? null;
  const stressScore = normalizePercentScore(stressRaw);
  const stress10 = stressScore == null ? null : Math.round((stressScore / 10) * 10) / 10;
  // Trust backend sleep_recovery_score directly.
  // null  → no validated sleep boundary → show "—"
  // number → valid score, show it (even if 0)
  const sleepRecoveryScoreRaw = summary?.sleep_recovery_score ?? null;
  const sleepRecovery = normalizePercentScore(sleepRecoveryScoreRaw);
  const wakingRecovery = normalizePercentScore(summary?.waking_recovery_score);
  const readiness = readinessFromSignals(
    sleepRecovery,
    wakingRecovery,
    stressScore,
  );
  const dateText = useMemo(() => fmtDate(morningRecap?.for_date), [morningRecap?.for_date]);
  const recapDateIso = morningRecap.for_date;
  const sleepRecoveryNightHint = useMemo(() => {
    // Yesterday Summary contract: show (yesterday)-1 as plain date.
    if (!morningRecap?.for_date) return '';
    const base = new Date(`${morningRecap.for_date}T00:00:00`);
    if (Number.isNaN(base.getTime())) return '';
    const prior = new Date(base);
    prior.setDate(base.getDate() - 1);
    return prior.toLocaleDateString('en-US', { day: 'numeric', month: 'short' });
  }, [morningRecap?.for_date]);

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

  const ringColor = ZEN.colors.stress;
  const stressRingColor =
    stressScore != null && stressScore >= goalLoad ? ZEN.colors.stress : ringColor;
  const recoveryRingColor =
    wakingRecovery != null && wakingRecovery >= recoveryGoal
      ? ZEN.colors.recovery
      : ZEN.colors.readiness;

  const stressState = stress10 == null ? '—' : stress10 >= 7 ? 'Elevated load' : stress10 >= 4.5 ? 'Moderate load' : 'Low load';
  const sleepState = sleepRecovery == null ? 'No sleep recovery yet' : sleepRecovery >= 70 ? 'Sleep reset held well' : 'Sleep reset was limited';
  const wakingState = wakingRecovery == null ? 'No waking recovery yet' : wakingRecovery >= 65 ? 'Waking recovery is stable' : 'Waking recovery is still rebuilding';

  return (
    <ZenScreen scrollable={false}>
      <TopHeader
        eyebrow="Yesterday Summary"
        title="YESTERDAY SUMMARY"
        subtitle={dateText ? `(${dateText})` : ''}
        leftIcon={<ArrowLeft size={18} color={ZEN.colors.textNear} />}
        onLeftPress={() => nav.goBack()}
        rightIcon={<Settings size={18} color={ZEN.colors.textNear} />}
      />

      <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={s.content}>
        {/* Parity with Home: three metric rings — Stress, Waking, Sleep */}
        <SectionCard style={[s.nowCard, { borderLeftColor: ZEN.colors.readiness, borderLeftWidth: 3 }]}>
          <View style={s.nowTopRow}>
            <View />
            <View style={[s.recapPill, { borderColor: 'rgba(255,255,255,0.18)' }]}>
              <Text style={[s.recapBadgeText, { color: ZEN.colors.textMuted }]}>RECAP</Text>
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
                displayValue={stress10 == null ? '—' : `${stress10.toFixed(1)}`}
                displaySuffix="/10"
              />
              <Text style={s.currentRingLabel}>Stress{'\n'}load</Text>
            </View>
            <View style={s.currentRingCell}>
              <ArcGauge
                value={wakingRecovery}
                color={recoveryRingColor}
                size={84}
                stroke={6}
                goal={recoveryGoal}
                valueFontSize={18}
              />
              <Text style={s.currentRecoveryLabel}>Waking{'\n'}recovery</Text>
            </View>
            <View style={s.currentRingCell}>
              <ArcGauge
                value={sleepRecovery}
                color={ZEN.colors.readiness}
                size={84}
                stroke={6}
                valueFontSize={18}
                displayValue={sleepRecovery == null ? '—' : `${Math.round(sleepRecovery)}%`}
              />
              <Text style={s.currentSleepLabel}>Sleep{'\n'}recovery</Text>
            </View>
          </View>
        </SectionCard>

        <SectionCard style={s.whyCard}>
          <SectionEyebrow>Why this score?</SectionEyebrow>
          <View style={s.whyItem}>
            <Text style={s.whyTitle}>{sleepState}</Text>
            <Text style={s.whyBody}>Sleep recovery contributes to your baseline reset before the day begins.</Text>
          </View>
          <View style={s.whyItem}>
            <Text style={s.whyTitle}>{wakingState}</Text>
            <Text style={s.whyBody}>Waking recovery captures how well your system stabilizes through daytime windows.</Text>
          </View>
          <View style={s.whyItem}>
            <Text style={s.whyTitle}>{stressState}</Text>
            <Text style={s.whyBody}>Stress load on a 0-10 scale is shown separately from recovery to avoid false subtraction.</Text>
          </View>
          {morningBrief?.brief_text ? (
            <Text style={s.briefLine} numberOfLines={4}>
              {morningBrief.brief_text}
            </Text>
          ) : null}
        </SectionCard>

        <SectionCard style={s.breakdownCard}>
          <SectionEyebrow>Metric Breakdown</SectionEyebrow>
          <View style={s.row}>
            <Text style={s.rowLabel}>Stress Load</Text>
            <Text style={s.rowValue}>{stress10 == null ? '—' : `${stress10.toFixed(1)} / 10`}</Text>
          </View>
          <View style={s.row}>
            <Text style={s.rowLabel}>Sleep Recovery</Text>
            <Text style={s.rowValue}>{sleepRecovery == null ? '—' : `${Math.round(sleepRecovery)} / 100`}</Text>
          </View>
          <Text style={s.sleepHintText}>{sleepRecoveryNightHint}</Text>
          <View style={s.row}>
            <Text style={s.rowLabel}>Waking Recovery</Text>
            <Text style={s.rowValue}>{wakingRecovery == null ? '—' : `${Math.round(wakingRecovery)} / 100`}</Text>
          </View>
          <View style={[s.row, s.lastRow]}>
            <Text style={s.rowLabel}>Readiness</Text>
            <Text style={s.rowValue}>{readiness == null ? '—' : `${Math.round(readiness)} / 100`}</Text>
          </View>
        </SectionCard>
      </ScrollView>
    </ZenScreen>
  );
}

const s = StyleSheet.create({
  content: {
    paddingBottom: 40,
    gap: 12,
  },
  readinessCard: {
    gap: 10,
    paddingVertical: 14,
  },
  readinessTopRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  recapPill: {
    minWidth: 24,
    minHeight: 24,
    alignItems: 'center',
    justifyContent: 'center',
  },
  recapBadgeText: {
    fontSize: 11,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.7,
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
  nowCard: { gap: 10, paddingVertical: 16 },
  nowTopRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  currentDualRingRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: 6,
    marginTop: 4,
    marginBottom: 6,
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
  whyCard: {
    gap: 8,
  },
  whyItem: {
    paddingTop: 2,
    gap: 4,
  },
  whyTitle: {
    color: ZEN.colors.textNear,
    fontSize: 14,
    fontWeight: '600',
  },
  whyBody: {
    color: ZEN.colors.textSecondary,
    fontSize: 12,
    lineHeight: 18,
  },
  briefLine: {
    marginTop: 2,
    color: ZEN.colors.textMuted,
    fontSize: 12,
    lineHeight: 18,
  },
  breakdownCard: {
    gap: 2,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 11,
    borderBottomWidth: 1,
    borderBottomColor: ZEN.colors.border,
  },
  lastRow: {
    borderBottomWidth: 0,
    paddingBottom: 2,
  },
  rowLabel: {
    color: ZEN.colors.textSecondary,
    fontSize: 13,
    fontWeight: '600',
  },
  rowValue: {
    color: ZEN.colors.white,
    fontSize: 14,
    fontWeight: '700',
  },
  sleepHintText: {
    marginTop: -4,
    marginBottom: 6,
    fontSize: 11,
    color: ZEN.colors.textMuted,
  },
});
