import TopHeader from '../components/TopHeader';
import { ArrowLeft, MoreHorizontal } from 'lucide-react-native';
import React from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
} from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { PlanItem } from '../types';
import {
  ZEN,
  ZenScreen,
  SurfaceCard,
  SectionEyebrow,
  HealthLineChart,
  HealthMetricCard,
  type HealthMetric,
} from '../ui/zenflow-ui-kit';

// Placeholder waveform — in future this will be real overnight biometric data
const PLACEHOLDER_WAVE = [62, 78, 76, 74, 73, 72, 72, 71, 71, 72, 71, 70, 70, 71, 70];

function categoryLabel(cat: string): string {
  const m: Record<string, string> = {
    zenflow_session:     'ZenFlow Session',
    movement:            'Movement',
    mindfulness:         'Mindfulness',
    habitual_relaxation: 'Relaxation',
    sleep:               'Sleep',
    recovery_active:     'Active Recovery',
  };
  return m[cat] ?? cat;
}

function deriveMetrics(item: PlanItem): HealthMetric[] {
  const adh =
    item.adherence_score !== null && item.adherence_score !== undefined
      ? Math.round(item.adherence_score * 100)
      : null;

  return [
    {
      label: 'Duration',
      value: String(item.duration_minutes),
      unit: 'min',
      status: item.has_evidence ? '✓ completed' : 'Not yet done',
      statusOk: item.has_evidence,
    },
    {
      label: 'Adherence',
      value: adh !== null ? String(adh) : '—',
      unit: '%',
      status: adh !== null ? (adh >= 80 ? '✓ on track' : '! below target') : 'No data yet',
      statusOk: adh !== null && adh >= 80,
    },
    {
      label: 'Priority',
      value: item.priority === 'must_do' ? 'Must Do'
           : item.priority === 'recommended' ? 'Rec.' : 'Opt.',
      unit: '',
      status: item.priority === 'must_do' ? '! high priority' : '✓ flexible',
      statusOk: item.priority !== 'must_do',
    },
    {
      label: 'Category',
      value: categoryLabel(item.category ?? ''),
      unit: '',
      status: item.has_evidence ? '✓ evidence logged' : 'Pending',
      statusOk: item.has_evidence,
    },
  ];
}

export default function CompletedActivityDetailScreen() {
  const nav   = useNavigation<NativeStackNavigationProp<any>>();
  const route = useRoute<any>();
  const item: PlanItem = route.params?.item;

  if (!item) {
    return (
      <ZenScreen scrollable>
        <TopHeader
          title="Activity Detail"
          leftIcon={<ArrowLeft size={18} color="rgba(255,255,255,0.7)" />}
          rightIcon={<MoreHorizontal size={18} color="rgba(255,255,255,0.7)" />}
          onLeftPress={() => nav.goBack()}
        />
        <Text style={s.notFoundText}>Activity not found</Text>
      </ZenScreen>
    );
  }

  const metrics = deriveMetrics(item);

  return (
    <ZenScreen scrollable>
      <TopHeader
        eyebrow="Activity Detail"
        title={item.title}
        leftIcon={<ArrowLeft size={18} color="rgba(255,255,255,0.7)" />}
        rightIcon={<MoreHorizontal size={18} color="rgba(255,255,255,0.7)" />}
        onLeftPress={() => nav.goBack()}
      />

      {/* ── Overview card ── */}
      <SurfaceCard style={s.overviewCard}>
        {/* Centered score ring */}
        <View style={s.ringRow}>
          <View style={s.ringCircle}>
            <Text style={s.ringValue}>
              {item.adherence_score !== null && item.adherence_score !== undefined
                ? Math.round(item.adherence_score * 100)
                : item.has_evidence ? 100 : '—'}
            </Text>
            <Text style={s.ringUnit}>%</Text>
          </View>
        </View>

        {/* Sparkline chart */}
        <HealthLineChart values={PLACEHOLDER_WAVE} />

        {/* Footer */}
        <View style={s.overviewFooter}>
          <SectionEyebrow>{categoryLabel(item.category ?? 'Activity')}</SectionEyebrow>
          {item.rationale ? (
            <Text style={s.rationaleText}>{item.rationale}</Text>
          ) : null}
        </View>
      </SurfaceCard>

      {/* ── 2-column metrics grid ── */}
      <View style={s.metricsGrid}>
        {metrics.map((m, i) => (
          <HealthMetricCard key={i} metric={m} />
        ))}

        {/* Share report card — last grid cell */}
        <View style={s.shareCard}>
          <Text style={s.shareEyebrow}>Share your report</Text>
          <Text style={s.shareTitle}>Health Report →</Text>
          <Text style={s.shareBody}>
            Export a printable summary for your doctor, trainer, or wellness journal.
          </Text>
        </View>
      </View>

      {/* ── Coach rationale ── */}
      {item.rationale ? (
        <SurfaceCard style={s.notesCard}>
          <SectionEyebrow>Coach rationale</SectionEyebrow>
          <Text style={s.notesText}>{item.rationale}</Text>
        </SurfaceCard>
      ) : null}
    </ZenScreen>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const s = StyleSheet.create({
  notFoundText: { fontSize: 16, color: ZEN.colors.textLabel, padding: 20 },

  header: {
    flexDirection: 'row', alignItems: 'flex-start',
    justifyContent: 'space-between', marginBottom: 16,
  },
  headerBtn: {
    width: 40, height: 40, borderRadius: 20, borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.15)', backgroundColor: 'rgba(255,255,255,0.05)',
    alignItems: 'center', justifyContent: 'center',
  },
  headerBtnText: { fontSize: 20, color: ZEN.colors.textNear },
  headerCenter:  { flex: 1, alignItems: 'center' },
  eyebrow: { fontSize: 10, textTransform: 'uppercase', letterSpacing: 3, color: ZEN.colors.textMuted },
  title:   { marginTop: 4, fontSize: 16, fontWeight: '600', letterSpacing: -0.3, color: ZEN.colors.white, textAlign: 'center' },

  overviewCard:   { padding: 14, gap: 12, marginBottom: 12 },
  ringRow:        { alignItems: 'center' },
  ringCircle:     {
    width: 96, height: 96, borderRadius: 48, borderWidth: 1,
    borderColor: ZEN.colors.border, backgroundColor: 'rgba(0,0,0,0.25)',
    alignItems: 'center', justifyContent: 'center',
    flexDirection: 'row', gap: 2,
  },
  ringValue:      { fontSize: 34, fontWeight: '600', letterSpacing: -1.5, color: ZEN.colors.white },
  ringUnit:       { fontSize: 14, color: ZEN.colors.textMuted, alignSelf: 'flex-end', marginBottom: 8 },
  overviewFooter: { gap: 4 },
  rationaleText:  { fontSize: 13, color: ZEN.colors.textLabel, lineHeight: 20 },

  metricsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginBottom: 12 },

  shareCard: {
    flex: 1, minWidth: '45%', borderRadius: 18, borderWidth: 1,
    borderColor: ZEN.colors.border, backgroundColor: ZEN.colors.surface, padding: 14,
  },
  shareEyebrow: { fontSize: 10, textTransform: 'uppercase', letterSpacing: 1.6, color: ZEN.colors.textMuted },
  shareTitle:   { marginTop: 10, fontSize: 17, fontWeight: '500', letterSpacing: -0.4, color: 'rgba(255,255,255,0.92)' },
  shareBody:    { marginTop: 6, fontSize: 12, lineHeight: 18, color: ZEN.colors.textLabel },

  notesCard: { gap: 6, marginBottom: 12 },
  notesText: { fontSize: 14, color: ZEN.colors.textLabel, lineHeight: 22 },
});
