import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import * as Haptics from 'expo-haptics';
import { Colors, Spacing, Typography, Radius } from '../../theme';

const OPTIONS = [
  { id: 'desk_heavy',  label: 'Desk-heavy',    desc: 'Long meetings, screen time, deadlines' },
  { id: 'on_my_feet',  label: 'On my feet',     desc: 'Physical work, retail, care, trades' },
  { id: 'mixed',       label: 'Mixed',          desc: 'Some desk, some moving around' },
  { id: 'studying',    label: 'Studying',       desc: 'Academic pressure, exams, projects' },
];

export default function Step3TypicalDay() {
  const nav = useNavigation<NativeStackNavigationProp<any>>();
  const route = useRoute<any>();
  const [selected, setSelected] = useState<string | null>(null);

  const pick = (id: string) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setSelected(id);
  };

  const next = () => {
    if (selected) nav.navigate('Step4Movement', { ...route.params, dayType: selected });
  };

  return (
    <View style={styles.root}>
      <View style={styles.header}>
        <Text style={styles.step}>2 of 7</Text>
        <Text style={styles.title}>What's your typical day like?</Text>
        <Text style={styles.sub}>This shapes how we interpret your stress patterns.</Text>
      </View>

      <View style={styles.list}>
        {OPTIONS.map((opt) => (
          <TouchableOpacity
            key={opt.id}
            style={[styles.option, selected === opt.id && styles.optionSelected]}
            onPress={() => pick(opt.id)}
            activeOpacity={0.75}
          >
            <Text style={[styles.optionLabel, selected === opt.id && styles.optionLabelSelected]}>
              {opt.label}
            </Text>
            <Text style={styles.optionDesc}>{opt.desc}</Text>
          </TouchableOpacity>
        ))}
      </View>

      <TouchableOpacity
        style={[styles.cta, !selected && styles.ctaDisabled]}
        onPress={next}
        disabled={!selected}
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
  list: { flex: 1, gap: Spacing.sm },
  option: {
    backgroundColor: Colors.surface2, borderRadius: Radius.md,
    borderWidth: 1, borderColor: Colors.border,
    padding: Spacing.md, gap: 4,
  },
  optionSelected: { borderColor: Colors.readiness, backgroundColor: Colors.readinessDim },
  optionLabel: { fontSize: 16, fontWeight: '600', color: Colors.text },
  optionLabelSelected: { color: Colors.readiness },
  optionDesc: { ...Typography.bodySmall, color: Colors.textMuted },
  cta: { backgroundColor: Colors.readiness, borderRadius: 14, paddingVertical: 18, alignItems: 'center' },
  ctaDisabled: { opacity: 0.35 },
  ctaText: { fontSize: 17, fontWeight: '700', color: Colors.black },
});
