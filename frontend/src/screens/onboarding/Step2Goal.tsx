import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import * as Haptics from 'expo-haptics';
import { Colors, Spacing, Typography, Radius } from '../../theme';

const OPTIONS = [
  { id: 'cant_switch_off', label: "Can't switch off", desc: "Mind races even after the day ends" },
  { id: 'tired',           label: 'Always tired',      desc: "Sleep doesn't seem to help" },
  { id: 'snap',            label: 'Snap easily',        desc: "Little things trigger a big reaction" },
  { id: 'cant_focus',      label: "Can't focus",        desc: "Scattered, no deep work" },
  { id: 'poor_sleep',      label: 'Poor sleep',         desc: "Hard to fall or stay asleep" },
];

export default function Step2Goal() {
  const nav = useNavigation<NativeStackNavigationProp<any>>();
  const [selected, setSelected] = useState<string | null>(null);

  const pick = (id: string) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setSelected(id);
  };

  const next = () => {
    if (selected) nav.navigate('Step3TypicalDay', { goal: selected });
  };

  return (
    <View style={styles.root}>
      <View style={styles.header}>
        <Text style={styles.step}>1 of 7</Text>
        <Text style={styles.title}>What brings you here?</Text>
        <Text style={styles.sub}>Pick the one that feels most true right now.</Text>
      </View>

      <ScrollView style={styles.list} contentContainerStyle={{ gap: Spacing.sm }} showsVerticalScrollIndicator={false}>
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
      </ScrollView>

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
  },
  header: { gap: 6, marginBottom: Spacing.lg },
  step: { ...Typography.label, color: Colors.textMuted },
  title: { fontSize: 28, fontWeight: '700', letterSpacing: -0.8, color: Colors.text },
  sub: { ...Typography.bodySmall, color: Colors.textSecondary },
  list: { flex: 1 },
  option: {
    backgroundColor: Colors.surface2, borderRadius: Radius.md,
    borderWidth: 1, borderColor: Colors.border,
    padding: Spacing.md, gap: 4,
  },
  optionSelected: { borderColor: Colors.readiness, backgroundColor: Colors.readinessDim },
  optionLabel: { fontSize: 16, fontWeight: '600', color: Colors.text },
  optionLabelSelected: { color: Colors.readiness },
  optionDesc: { ...Typography.bodySmall, color: Colors.textMuted },
  cta: { backgroundColor: Colors.readiness, borderRadius: 14, paddingVertical: 18, alignItems: 'center', marginTop: Spacing.md },
  ctaDisabled: { opacity: 0.35 },
  ctaText: { fontSize: 17, fontWeight: '700', color: Colors.black },
});
