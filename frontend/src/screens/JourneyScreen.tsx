import React, { useCallback, useState } from 'react';
import TopHeader from '../components/TopHeader';
import { ArrowLeft, MoreHorizontal } from 'lucide-react-native';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import EmptyState from '../components/EmptyState';
import { Colors } from '../theme';
import { getArchetype } from '../api/user';
import type { ArchetypeProfile } from '../types';
import type { ProfileStackParamList } from '../navigation/AppNavigator';
import {
  ZenScreen, ZEN,
} from '../ui/zenflow-ui-kit';

const MILESTONES = [
  { stage: 1, label: 'First reading',          req: '1 day of data',          icon: 'play-circle-outline' },
  { stage: 2, label: 'Pattern emerging',        req: '7 days of data',          icon: 'trending-up-outline' },
  { stage: 3, label: 'Coherence breakthrough',  req: 'First recovery window tagged', icon: 'radio-button-on-outline' },
  { stage: 4, label: 'Consistent practice',     req: '21 days active',           icon: 'ribbon-outline' },
  { stage: 5, label: 'Mastery',                 req: 'Stage 5 archetype confirmed', icon: 'trophy-outline' },
];

export default function JourneyScreen() {
  const nav = useNavigation<NativeStackNavigationProp<ProfileStackParamList>>();
  const [archetype, setArchetype] = useState<ArchetypeProfile | null>(null);
  const [loading, setLoading] = useState(true);

  useFocusEffect(useCallback(() => { load(); }, []));

  const load = async () => {
    setLoading(true);
    try {
      const res = await getArchetype();
      setArchetype(res.data);
    } catch {}
    finally { setLoading(false); }
  };

  const currentStage = archetype?.stage ?? 0;

  return (
    <ZenScreen scrollable={false}>
      <TopHeader
        title="Practice Journey"
        leftIcon={<ArrowLeft size={18} color="rgba(255,255,255,0.7)" />}
        rightIcon={<MoreHorizontal size={18} color="rgba(255,255,255,0.7)" />}
        onLeftPress={() => nav.goBack()}
      />

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={Colors.readiness} /></View>
      ) : (
        <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
          <Text style={styles.intro}>
            ZenFlow tracks your nervous system practice as a journey — each stage unlocks deeper insights.
          </Text>

        <Text style={styles.sectionTitle}>MILESTONES</Text>
          <View style={styles.timeline}>
            {MILESTONES.map((m, i) => {
              const isComplete = m.stage <= currentStage;
              const isCurrent  = m.stage === currentStage + 1;
              const isLocked   = m.stage > currentStage + 1;
              return (
                <View key={m.stage} style={styles.milestone}>
                  {/* Connector line */}
                  {i < MILESTONES.length - 1 && (
                    <View style={[styles.connector, isComplete && styles.connectorActive]} />
                  )}
                  {/* Icon circle */}
                  <View
                    style={[
                      styles.iconCircle,
                      isComplete && styles.iconCircleComplete,
                      isCurrent && styles.iconCircleCurrent,
                    ]}
                  >
                    <Ionicons
                      name={isComplete ? 'checkmark' : m.icon as any}
                      size={18}
                      color={isComplete ? Colors.black : isCurrent ? Colors.readiness : Colors.textMuted}
                    />
                  </View>
                  {/* Text */}
                  <View style={styles.milestoneText}>
                    <Text style={[styles.milestoneLabel, isLocked && styles.locked]}>
                      {m.label}
                    </Text>
                    <Text style={styles.milestoneReq}>{m.req}</Text>
                  </View>
                </View>
              );
            })}
          </View>
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
  sectionTitle: { fontSize: 11, textTransform: 'uppercase', letterSpacing: 2.4, color: ZEN.colors.textMuted, marginBottom: 8, paddingHorizontal: 20 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  scroll: { padding: 20, gap: 24, paddingBottom: 40 },
  intro: { fontSize: 14, color: ZEN.colors.textSecondary, lineHeight: 22, fontStyle: 'italic' },
  timeline: { gap: 0 },
  milestone: {
    flexDirection: 'row', alignItems: 'flex-start',
    gap: 16, paddingBottom: 24, position: 'relative',
  },
  connector: {
    position: 'absolute', left: 17, top: 36, bottom: 0, width: 2,
    backgroundColor: ZEN.colors.surfaceSoft, zIndex: -1,
  },
  connectorActive: { backgroundColor: ZEN.colors.recovery },
  iconCircle: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: ZEN.colors.surface, borderWidth: 1, borderColor: ZEN.colors.border,
    alignItems: 'center', justifyContent: 'center',
  },
  iconCircleComplete: { backgroundColor: ZEN.colors.recovery, borderColor: ZEN.colors.recovery },
  iconCircleCurrent: { borderColor: ZEN.colors.readiness },
  milestoneText: { flex: 1, paddingTop: 6, gap: 3 },
  milestoneLabel: { fontSize: 15, fontWeight: '600', color: ZEN.colors.white },
  locked: { color: ZEN.colors.textMuted },
  milestoneReq: { fontSize: 12, color: ZEN.colors.textMuted },
});
