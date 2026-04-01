import React, { useCallback, useState } from 'react';
import TopHeader from '../components/TopHeader';
import { ArrowLeft, MoreHorizontal } from 'lucide-react-native';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import ProgressBar from '../components/ProgressBar';
import EmptyState from '../components/EmptyState';
import { Colors } from '../theme';
import { getArchetype, getFingerprint } from '../api/user';
import type { ArchetypeProfile, Fingerprint } from '../types';
import type { ProfileStackParamList } from '../navigation/AppNavigator';
import {
  ZenScreen, SectionEyebrow, SectionCard, SurfaceCard, ZEN,
} from '../ui/zenflow-ui-kit';

const DIMENSION_LABELS: Record<string, string> = {
  stress_reactivity:        'Stress Reactivity',
  recovery_efficiency:      'Recovery Efficiency',
  coherence_adaptability:   'Coherence Adaptability',
  lifestyle_alignment:      'Lifestyle Alignment',
  self_awareness:           'Self-Awareness',
};

const STAGE_LABELS = ['Baseline', 'Emerging', 'Developing', 'Consistent', 'Mastery'];

export default function ArchetypeScreen() {
  const nav = useNavigation<NativeStackNavigationProp<ProfileStackParamList>>();
  const [archetype, setArchetype] = useState<ArchetypeProfile | null>(null);
  const [fingerprint, setFingerprint] = useState<Fingerprint | null>(null);
  const [loading, setLoading] = useState(true);

  useFocusEffect(useCallback(() => { load(); }, []));

  const load = async () => {
    setLoading(true);
    try {
      const [aRes, fRes] = await Promise.all([getArchetype(), getFingerprint()]);
      setArchetype(aRes.data);
      setFingerprint(fRes.data);
    } catch {}
    finally { setLoading(false); }
  };

  return (
    <ZenScreen scrollable={false}>
      <TopHeader
        title="Archetype"
        leftIcon={<ArrowLeft size={18} color="rgba(255,255,255,0.7)" />}
        rightIcon={<MoreHorizontal size={18} color="rgba(255,255,255,0.7)" />}
        onLeftPress={() => nav.goBack()}
      />

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={Colors.coach} /></View>
      ) : !archetype ? (
        <EmptyState icon="stats-chart-outline" title="Archetype building..." message="Needs 5+ days of data." />
      ) : (
        <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
          {/* Pattern name */}
          <View style={styles.patternCard}>
            <Text style={styles.patternLabel}>YOUR PATTERN</Text>
            <Text style={styles.patternName}>{archetype.primary_pattern ?? 'Unknown'}</Text>
            {archetype.trajectory && (
              <Text style={styles.trajectory}>Trajectory: {archetype.trajectory}</Text>
            )}
          </View>

          {/* Stage bar */}
          <View style={styles.stageBlock}>
            <Text style={styles.sectionTitle}>PRACTICE STAGE</Text>
            <View style={styles.stageRow}>
              {STAGE_LABELS.map((label, i) => (
                <View key={i} style={styles.stageChip}>
                  <View
                    style={[
                      styles.stageDot,
                      i + 1 <= (archetype.stage ?? 0) && styles.stageDotActive,
                    ]}
                  />
                  <Text style={[
                    styles.stageLabel,
                    i + 1 === archetype.stage && { color: Colors.coach },
                  ]}>{label}</Text>
                </View>
              ))}
            </View>
          </View>

          {/* Dimension scores */}
        {archetype.dimension_scores && (
            <>
              <Text style={styles.sectionTitle}>5 DIMENSIONS</Text>
              <View style={styles.dims}>
                {Object.entries(archetype.dimension_scores).map(([key, val]) => (
                  <View key={key} style={styles.dimRow}>
                    <Text style={styles.dimLabel}>{DIMENSION_LABELS[key] ?? key}</Text>
                    <View style={styles.dimBar}>
                      <ProgressBar value={(val as number) * 10} color={Colors.coach} height={5} />
                    </View>
                    <Text style={styles.dimScore}>{(val as number).toFixed(1)}</Text>
                  </View>
                ))}
              </View>
            </>
          )}

          {/* Fingerprint summary */}
          {fingerprint?.stress_profile && (
            <>
              <Text style={styles.sectionTitle}>STRESS FINGERPRINT</Text>
              <View style={styles.fpCard}>
                <Text style={styles.fpText}>
                  Peak stress: {fingerprint.stress_profile.peak_hours?.join(', ') ?? 'unknown'} UTC
                </Text>
                <Text style={styles.fpText}>
                  Top trigger: {fingerprint.stress_profile.top_trigger ?? 'building...'}
                </Text>
              </View>
            </>
          )}
        </ScrollView>
      )}
    </ZenScreen>
  );
}

const styles = StyleSheet.create({
  nav: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 20, paddingBottom: 16, marginBottom: 4,
    borderBottomWidth: 1, borderBottomColor: ZEN.colors.border,
  },
  navTitle: { fontSize: 16, fontWeight: '600', color: ZEN.colors.white },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  scroll: { padding: 20, gap: 20, paddingBottom: 40 },
  patternCard: {
    backgroundColor: 'rgba(242,209,76,0.08)', borderRadius: 20,
    borderWidth: 1, borderColor: ZEN.colors.readiness + '44', padding: 20, gap: 6,
  },
  patternLabel: { fontSize: 10, textTransform: 'uppercase', letterSpacing: 2, color: ZEN.colors.readiness },
  patternName: { fontSize: 28, fontWeight: '800', letterSpacing: -1, color: ZEN.colors.readiness },
  trajectory: { fontSize: 13, color: ZEN.colors.textMuted, fontStyle: 'italic' },
  stageBlock: { gap: 8 },
  stageRow: { flexDirection: 'row', justifyContent: 'space-between' },
  stageChip: { alignItems: 'center', gap: 5 },
  stageDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: ZEN.colors.surfaceSoft },
  stageDotActive: { backgroundColor: ZEN.colors.readiness },
  stageLabel: { fontSize: 9, color: ZEN.colors.textMuted, textAlign: 'center' },
  dims: { gap: 12 },
  dimRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  dimLabel: { width: 140, fontSize: 12, color: ZEN.colors.textSecondary },
  dimBar: { flex: 1 },
  dimScore: { width: 30, fontSize: 12, color: ZEN.colors.textMuted, textAlign: 'right' },
  sectionTitle: { fontSize: 11, textTransform: 'uppercase', letterSpacing: 2.4, color: ZEN.colors.textMuted, marginBottom: 8 },
  fpCard: {
    backgroundColor: ZEN.colors.surface, borderRadius: 16,
    borderWidth: 1, borderColor: ZEN.colors.border, padding: 16, gap: 6,
  },
  fpText: { fontSize: 14, color: ZEN.colors.textSecondary },
});
