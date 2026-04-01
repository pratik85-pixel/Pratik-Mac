import TopHeader from '../components/TopHeader';
import { ArrowLeft, MoreHorizontal } from 'lucide-react-native';
import React, { useCallback, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import ScreenWrapper from '../components/ScreenWrapper';
import SectionHeader from '../components/SectionHeader';
import MetricCard from '../components/MetricCard';
import EmptyState from '../components/EmptyState';
import { Colors, Spacing, Typography, Radius } from '../theme';
import { useOutcomes } from '../hooks/useOutcomes';
import type { ReportCard } from '../types';
import type { ProfileStackParamList } from '../navigation/AppNavigator';

function gradeColor(grade: string) {
  if (grade?.startsWith('A')) return Colors.recovery;
  if (grade?.startsWith('B')) return Colors.readiness;
  if (grade?.startsWith('C')) return Colors.zone4;
  return Colors.stress;
}

export default function ReportCardScreen() {
  const nav = useNavigation<NativeStackNavigationProp<ProfileStackParamList>>();
  const { weekly, longitudinal, loading, refreshOutcomes } = useOutcomes();

  useFocusEffect(useCallback(() => { refreshOutcomes(); }, [refreshOutcomes]));

  const card = weekly; // use weekly data as the report card

  return (
    <ScreenWrapper>
      <TopHeader
        title="Weekly Report Card"
        leftIcon={<ArrowLeft size={18} color="rgba(255,255,255,0.7)" />}
        rightIcon={<MoreHorizontal size={18} color="rgba(255,255,255,0.7)" />}
        onLeftPress={() => nav.goBack()}
      />

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={Colors.readiness} /></View>
      ) : !card ? (
        <EmptyState icon="ribbon-outline" title="No report yet" message="A full week of data is needed to generate your first report card." />
      ) : (
        <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
          {/* Overall grade */}
          <View style={styles.gradeCard}>
            <Text style={styles.gradeLabel}>OVERALL</Text>
            <Text style={[styles.grade, { color: gradeColor(card.overall_grade ?? '') }]}>
              {card.overall_grade ?? '—'}
            </Text>
            {card.overall_insight && (
              <Text style={styles.gradeInsight}>{card.overall_insight}</Text>
            )}
          </View>

          {/* Metric breakdown */}
          <SectionHeader title="THIS WEEK" />
          <View style={styles.metrics}>
            <MetricCard
              label="Avg Stress"
              value={card.avg_stress_load != null ? Math.round(card.avg_stress_load) : '—'}
              color={Colors.stress}
              sub="lower is better"
            />
            <MetricCard
              label="Avg Recovery"
              value={card.avg_recovery_score != null ? Math.round(card.avg_recovery_score) : '—'}
              color={Colors.recovery}
              sub="higher is better"
            />
          </View>
          <View style={styles.metrics}>
            <MetricCard
              label="Avg Readiness"
              value={card.avg_readiness_score != null ? Math.round(card.avg_readiness_score) : '—'}
              color={Colors.readiness}
            />
            <MetricCard
              label="Active Days"
              value={card.active_days ?? '—'}
              unit="days"
            />
          </View>

          {/* Domain insights */}
          {card.domain_grades && (
            <>
              <SectionHeader title="DOMAIN BREAKDOWN" />
              <View style={styles.domainList}>
                {Object.entries(card.domain_grades).map(([domain, grade]: [string, any]) => (
                  <View key={domain} style={styles.domainRow}>
                    <Text style={styles.domainLabel}>{domain.replace(/_/g, ' ')}</Text>
                    <Text style={[styles.domainGrade, { color: gradeColor(grade) }]}>{grade}</Text>
                  </View>
                ))}
              </View>
            </>
          )}

          {/* Longitudinal Trend */}
          {longitudinal && (
            <>
              <SectionHeader title="LONG TERM TREND" />
              <View style={[styles.gradeCard, { alignItems: 'flex-start' }]}>
                {longitudinal.trend_direction && (
                   <Text style={[styles.domainGrade, { color: Colors.text }]}>Trend: {longitudinal.trend_direction}</Text>
                )}
                {longitudinal.longitudinal_insight ? (
                  <Text style={[styles.gradeInsight, { textAlign: 'left', marginTop: 4 }]}>
                    {longitudinal.longitudinal_insight}
                  </Text>
                ) : (
                  <Text style={styles.gradeInsight}>Keep tracking to see long term trends.</Text>
                )}
              </View>
            </>
          )}
        </ScrollView>
      )}
    </ScreenWrapper>
  );
}

const styles = StyleSheet.create({
  nav: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: Spacing.md, paddingVertical: Spacing.sm,
    borderBottomWidth: 1, borderBottomColor: Colors.border,
  },
  back: { padding: 6 },
  navTitle: { ...Typography.sectionTitle, fontSize: 16, color: Colors.text },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  scroll: { padding: Spacing.lg, gap: Spacing.lg, paddingBottom: 40 },
  gradeCard: {
    backgroundColor: Colors.surface2, borderRadius: Radius.lg,
    borderWidth: 1, borderColor: Colors.border, padding: Spacing.lg,
    alignItems: 'center', gap: 8,
  },
  gradeLabel: { ...Typography.label, color: Colors.textMuted, fontSize: 10 },
  grade: { fontSize: 72, fontWeight: '800', letterSpacing: -3 },
  gradeInsight: { fontSize: 14, color: Colors.textSecondary, textAlign: 'center', fontStyle: 'italic' },
  metrics: { flexDirection: 'row', gap: Spacing.sm },
  domainList: {
    backgroundColor: Colors.surface2, borderRadius: Radius.md,
    borderWidth: 1, borderColor: Colors.border, overflow: 'hidden',
  },
  domainRow: {
    flexDirection: 'row', justifyContent: 'space-between',
    paddingHorizontal: Spacing.md, paddingVertical: Spacing.sm,
    borderBottomWidth: 1, borderBottomColor: Colors.borderFaint,
  },
  domainLabel: { fontSize: 14, color: Colors.textSecondary, textTransform: 'capitalize' },
  domainGrade: { fontSize: 16, fontWeight: '700' },
});
