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
import ProgressBar from '../components/ProgressBar';
import EmptyState from '../components/EmptyState';
import { Colors, Spacing, Typography, Radius } from '../theme';
import { getUnifiedProfile, rebuildProfile } from '../api/profile';
import { getName } from '../store/auth';
import type { UnifiedProfile } from '../types';
import type { ProfileStackParamList } from '../navigation/AppNavigator';

export default function ProfileScreen() {
  const nav = useNavigation<NativeStackNavigationProp<ProfileStackParamList>>();
  const [profile, setProfile] = useState<UnifiedProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [rebuilding, setRebuilding] = useState(false);
  const [storedName, setStoredName] = useState<string>('You');

  useFocusEffect(useCallback(() => { load(); getName().then(n => { if (n) setStoredName(n); }); }, []));

  const load = async () => {
    setLoading(true);
    try {
      const res = await getUnifiedProfile();
      setProfile(res.data);
    } catch (e: any) {
      if (e?.response?.status === 404) {
        // No profile yet — trigger an initial build
        try {
          setRebuilding(true);
          await rebuildProfile();
          const res2 = await getUnifiedProfile();
          setProfile(res2.data);
        } catch {}
        finally { setRebuilding(false); }
      }
    }
    finally { setLoading(false); }
  };

  const navItem = (label: string, screen: keyof ProfileStackParamList, icon: string) => (
    <TouchableOpacity
      key={label}
      style={styles.navRow}
      onPress={() => nav.navigate(screen as any)}
      activeOpacity={0.75}
    >
      <Ionicons name={icon as any} size={18} color={Colors.textSecondary} />
      <Text style={styles.navLabel}>{label}</Text>
      <Ionicons name="chevron-forward" size={16} color={Colors.textMuted} style={styles.chevron} />
    </TouchableOpacity>
  );

  return (
    <ScreenWrapper>
      <View style={styles.header}>
        <Text style={styles.title}>Profile</Text>
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={Colors.readiness} /></View>
      ) : rebuilding ? (
        <View style={styles.center}>
          <ActivityIndicator color={Colors.readiness} />
          <Text style={{ color: Colors.textMuted, marginTop: Spacing.sm, fontSize: 13 }}>Building your profile…</Text>
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
          {!profile && (
            <EmptyState icon="person-outline" title="Profile not found" message="Wear your band for a few sessions — your profile builds automatically." />
          )}
          {profile && (
          <>
          {/* Name + archetype */}
          <View style={styles.idCard}>
            <Text style={styles.userName}>{profile.archetype_primary ? storedName : storedName}</Text>
            {profile.archetype_primary && (
              <Text style={styles.archetype}>{profile.archetype_primary}</Text>
            )}
            <Text style={styles.stage}>Day {profile.days_active ?? 0} · Level {profile.training_level ?? 1}</Text>
          </View>

          {/* Completeness */}
          <View style={styles.completenessBlock}>
            <SectionHeader title="PROFILE COMPLETENESS" />
            <View style={styles.completenessRow}>
              <Text style={styles.completenessNum}>
                {Math.round((profile.data_confidence ?? profile.completeness_score ?? 0) * 100)}%
              </Text>
              <ProgressBar
                value={(profile.data_confidence ?? profile.completeness_score ?? 0) * 100}
                color={Colors.readiness}
                height={4}
              />
            </View>
          </View>

          {/* Key facts */}
          {(profile.facts?.length ?? 0) > 0 && (
            <>
              <SectionHeader title="WHAT WE KNOW" />
              <View style={styles.factsList}>
                {(profile.facts ?? []).slice(0, 6).map((f: any, i: number) => (
                  <View key={i} style={styles.factRow}>
                    <Ionicons name="checkmark-circle" size={14} color={Colors.recovery} />
                    <Text style={styles.factText}>{typeof f === 'string' ? f : f.statement ?? f.fact ?? JSON.stringify(f)}</Text>
                  </View>
                ))}
              </View>
            </>
          )}

          {profile.coach_narrative ? (
            <>
              <SectionHeader title="COACH NARRATIVE" />
              <View style={styles.narrativeCard}>
                <Text style={styles.narrativeText}>{profile.coach_narrative}</Text>
              </View>
            </>
          ) : null}

          {/* Navigation links */}
          <SectionHeader title="EXPLORE" />
          <View style={styles.navGroup}>
            {navItem('Archetype & Patterns', 'Archetype', 'stats-chart-outline')}
            {navItem('Practice Journey', 'Journey', 'map-outline')}
            {navItem('Weekly Report Card', 'ReportCard', 'ribbon-outline')}
            {navItem('Daily Check-In', 'CheckIn', 'create-outline')}
          </View>
          </>
          )}

          {/* Always-visible nav */}
          <SectionHeader title="APP" />
          <View style={styles.navGroup}>
            {navItem('Settings', 'Settings', 'settings-outline')}
          </View>
        </ScrollView>
      )}
    </ScreenWrapper>
  );
}

const styles = StyleSheet.create({
  header: { paddingHorizontal: Spacing.lg, paddingTop: Spacing.lg, paddingBottom: Spacing.sm },
  title: { ...Typography.title, color: Colors.text },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  scroll: { padding: Spacing.lg, gap: Spacing.lg, paddingBottom: 40 },
  idCard: {
    backgroundColor: Colors.surface2, borderRadius: Radius.lg,
    borderWidth: 1, borderColor: Colors.border,
    padding: Spacing.lg, gap: 6,
  },
  userName: { fontSize: 26, fontWeight: '700', letterSpacing: -0.5, color: Colors.text },
  archetype: { fontSize: 15, fontWeight: '500', color: Colors.coach },
  stage: { ...Typography.bodySmall, color: Colors.textMuted },
  completenessBlock: { gap: Spacing.sm },
  completenessRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md },
  completenessNum: { fontSize: 18, fontWeight: '700', color: Colors.readiness, width: 48 },
  factsList: { gap: 8 },
  factRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  factText: { flex: 1, fontSize: 14, color: Colors.textSecondary, lineHeight: 20 },
  narrativeCard: {
    backgroundColor: Colors.surface2,
    borderRadius: Radius.lg,
    borderWidth: 1,
    borderColor: Colors.border,
    padding: Spacing.md,
  },
  narrativeText: { fontSize: 14, color: Colors.textSecondary, lineHeight: 21 },
  navGroup: {
    backgroundColor: Colors.surface2, borderRadius: Radius.lg,
    borderWidth: 1, borderColor: Colors.border, overflow: 'hidden',
  },
  navRow: {
    flexDirection: 'row', alignItems: 'center',
    paddingHorizontal: Spacing.md, paddingVertical: Spacing.md,
    borderBottomWidth: 1, borderBottomColor: Colors.borderFaint, gap: Spacing.sm,
  },
  navLabel: { flex: 1, fontSize: 15, fontWeight: '500', color: Colors.textSecondary },
  chevron: { marginLeft: 'auto' },
});
