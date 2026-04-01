import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import * as Haptics from 'expo-haptics';
import { Colors, Spacing, Typography, Radius } from '../../theme';

const OPTIONS = [
  { id: 'breathing',     label: 'Breathing exercises', emoji: '🌬️' },
  { id: 'reading',       label: 'Reading',             emoji: '📚' },
  { id: 'music',         label: 'Music',               emoji: '🎵' },
  { id: 'walking',       label: 'Walking',             emoji: '🚶' },
  { id: 'meditation',    label: 'Meditation',          emoji: '🧘' },
  { id: 'social',        label: 'Talking to someone',  emoji: '💬' },
  { id: 'nothing_works', label: "Nothing works",       emoji: '😮‍💨' },
];

export default function Step6Decompress() {
  const nav = useNavigation<NativeStackNavigationProp<any>>();
  const route = useRoute<any>();
  const [selected, setSelected] = useState<string[]>([]);

  const toggle = (id: string) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setSelected((prev) =>
      id === 'nothing_works'
        ? ['nothing_works']
        : prev.includes(id)
          ? prev.filter((x) => x !== id)
          : [...prev.filter((x) => x !== 'nothing_works'), id],
    );
  };

  const next = () => {
    if (selected.length > 0)
      nav.navigate('Step7Honest', { ...route.params, decompress: selected });
  };

  return (
    <View style={styles.root}>
      <View style={styles.header}>
        <Text style={styles.step}>5 of 7</Text>
        <Text style={styles.title}>How do you decompress?</Text>
        <Text style={styles.sub}>We'll suggest these at the right moments.</Text>
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
    paddingHorizontal: Spacing.lg, paddingTop: 80, paddingBottom: 56, gap: Spacing.lg,
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
