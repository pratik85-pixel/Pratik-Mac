import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import * as Haptics from 'expo-haptics';
import { Colors, Spacing, Typography, Radius } from '../../theme';

type Opt = { id: string; label: string; opts: string[] };

const QUESTIONS: Opt[] = [
  {
    id: 'alcohol',
    label: 'How often do you drink alcohol?',
    opts: ['Never', '1–2x a week', '3–5x a week', 'Daily'],
  },
  {
    id: 'caffeine',
    label: 'Daily caffeine intake?',
    opts: ['None', '1 cup', '2–3 cups', '4+ cups'],
  },
  {
    id: 'sleep',
    label: 'Typical sleep?',
    opts: ['Under 6h', '6–7h', '7–8h', '8h+'],
  },
];

export default function Step5Lifestyle() {
  const nav = useNavigation<NativeStackNavigationProp<any>>();
  const route = useRoute<any>();
  const [answers, setAnswers] = useState<Record<string, string>>({});

  const pick = (qid: string, val: string) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setAnswers((prev) => ({ ...prev, [qid]: val }));
  };

  const allDone = QUESTIONS.every((q) => answers[q.id]);

  const next = () => {
    if (allDone) nav.navigate('Step6Decompress', { ...route.params, lifestyle: answers });
  };

  return (
    <View style={styles.root}>
      <View style={styles.header}>
        <Text style={styles.step}>4 of 7</Text>
        <Text style={styles.title}>A few lifestyle questions</Text>
        <Text style={styles.sub}>Honest answers build a better baseline — no judgment.</Text>
      </View>

      <View style={styles.questions}>
        {QUESTIONS.map((q) => (
          <View key={q.id} style={styles.qBlock}>
            <Text style={styles.qLabel}>{q.label}</Text>
            <View style={styles.opts}>
              {q.opts.map((o) => (
                <TouchableOpacity
                  key={o}
                  style={[styles.opt, answers[q.id] === o && styles.optSelected]}
                  onPress={() => pick(q.id, o)}
                  activeOpacity={0.75}
                >
                  <Text style={[styles.optText, answers[q.id] === o && styles.optTextSelected]}>{o}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
        ))}
      </View>

      <TouchableOpacity
        style={[styles.cta, !allDone && styles.ctaDisabled]}
        onPress={next}
        disabled={!allDone}
        activeOpacity={0.8}
      >
        <Text style={styles.ctaText}>Next</Text>
      </TouchableOpacity>
    </View>
  );
}

const s = StyleSheet;
const styles = s.create({
  root: {
    flex: 1, backgroundColor: Colors.black,
    paddingHorizontal: Spacing.lg, paddingTop: 80, paddingBottom: 56, gap: Spacing.lg,
  },
  header: { gap: 6 },
  step: { ...Typography.label, color: Colors.textMuted },
  title: { fontSize: 28, fontWeight: '700', letterSpacing: -0.8, color: Colors.text },
  sub: { ...Typography.bodySmall, color: Colors.textSecondary },
  questions: { flex: 1, gap: Spacing.lg },
  qBlock: { gap: Spacing.sm },
  qLabel: { fontSize: 14, fontWeight: '600', color: Colors.textSecondary },
  opts: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  opt: {
    paddingHorizontal: 14, paddingVertical: 9,
    backgroundColor: Colors.surface2, borderRadius: Radius.full,
    borderWidth: 1, borderColor: Colors.border,
  },
  optSelected: { borderColor: Colors.readiness, backgroundColor: Colors.readinessDim },
  optText: { fontSize: 13, fontWeight: '500', color: Colors.textSecondary },
  optTextSelected: { color: Colors.readiness },
  cta: { backgroundColor: Colors.readiness, borderRadius: 14, paddingVertical: 18, alignItems: 'center' },
  ctaDisabled: { opacity: 0.35 },
  ctaText: { fontSize: 17, fontWeight: '700', color: Colors.black },
});
