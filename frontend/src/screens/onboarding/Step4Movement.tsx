import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import * as Haptics from 'expo-haptics';
import { Colors, Spacing, Typography, Radius } from '../../theme';

const OPTIONS = [
  { id: 'running',  label: 'Running',  emoji: '🏃' },
  { id: 'cycling',  label: 'Cycling',  emoji: '🚴' },
  { id: 'gym',      label: 'Gym',      emoji: '🏋️' },
  { id: 'swimming', label: 'Swimming', emoji: '🏊' },
  { id: 'hiking',   label: 'Hiking',   emoji: '🥾' },
  { id: 'yoga',     label: 'Yoga',     emoji: '🧘' },
  { id: 'sports',   label: 'Team sports', emoji: '⚽' },
  { id: 'nothing',  label: 'Not much', emoji: '😴' },
];

export default function Step4Movement() {
  const nav = useNavigation<NativeStackNavigationProp<any>>();
  const route = useRoute<any>();
  const [selected, setSelected] = useState<string[]>([]);

  const toggle = (id: string) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setSelected((prev) =>
      id === 'nothing'
        ? ['nothing']
        : prev.includes(id)
          ? prev.filter((x) => x !== id)
          : [...prev.filter((x) => x !== 'nothing'), id],
    );
  };

  const next = () => {
    if (selected.length > 0)
      nav.navigate('Step5Lifestyle', { ...route.params, movement: selected });
  };

  return (
    <View style={styles.root}>
      <View style={styles.header}>
        <Text style={styles.step}>3 of 7</Text>
        <Text style={styles.title}>How do you move?</Text>
        <Text style={styles.sub}>Select all that apply. We'll use this to recognise exercise stress spikes.</Text>
      </View>

      <View style={styles.grid}>
        {OPTIONS.map((opt) => {
          const on = selected.includes(opt.id);
          return (
            <TouchableOpacity
              key={opt.id}
              style={[styles.chip, on && styles.chipSelected]}
              onPress={() => toggle(opt.id)}
              activeOpacity={0.75}
            >
              <Text style={styles.chipEmoji}>{opt.emoji}</Text>
              <Text style={[styles.chipLabel, on && styles.chipLabelSelected]}>{opt.label}</Text>
            </TouchableOpacity>
          );
        })}
      </View>

      <TouchableOpacity
        style={[styles.cta, selected.length === 0 && styles.ctaDisabled]}
        onPress={next}
        disabled={selected.length === 0}
        activeOpacity={0.8}
      >
        <Text style={styles.ctaText}>Next</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1, backgroundColor: Colors.black,
    paddingHorizontal: Spacing.lg, paddingTop: 80, paddingBottom: 56,
    gap: Spacing.lg,
  },
  header: { gap: 6 },
  step: { ...Typography.label, color: Colors.textMuted },
  title: { fontSize: 28, fontWeight: '700', letterSpacing: -0.8, color: Colors.text },
  sub: { ...Typography.bodySmall, color: Colors.textSecondary },
  grid: { flex: 1, flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm },
  chip: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
    backgroundColor: Colors.surface2, borderRadius: Radius.full,
    borderWidth: 1, borderColor: Colors.border,
    paddingHorizontal: 16, paddingVertical: 12,
  },
  chipSelected: { borderColor: Colors.readiness, backgroundColor: Colors.readinessDim },
  chipEmoji: { fontSize: 18 },
  chipLabel: { fontSize: 14, fontWeight: '500', color: Colors.textSecondary },
  chipLabelSelected: { color: Colors.readiness },
  cta: { backgroundColor: Colors.readiness, borderRadius: 14, paddingVertical: 18, alignItems: 'center' },
  ctaDisabled: { opacity: 0.35 },
  ctaText: { fontSize: 17, fontWeight: '700', color: Colors.black },
});
