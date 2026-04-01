import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import { Colors, Spacing, Typography, Radius } from '../../theme';

const BULLETS = [
  "Your heart rhythm — beat-to-beat variation that reflects nervous system state",
  "Stress load, not stress feelings — the body signal, not your interpretation",
  "Recovery quality — how well your nervous system resets overnight and during the day",
  "Readiness — a composite of both, telling you how much capacity you have today",
];

export default function Step7Honest() {
  const nav = useNavigation<NativeStackNavigationProp<any>>();
  const route = useRoute<any>();

  return (
    <View style={styles.root}>
      <View style={styles.header}>
        <Text style={styles.step}>6 of 7</Text>
        <Text style={styles.title}>Here's what this app actually measures</Text>
        <Text style={styles.sub}>
          Not mood. Not subjective wellness. Physiological signal.
        </Text>
      </View>

      <View style={styles.bullets}>
        {BULLETS.map((b, i) => (
          <View key={i} style={styles.bullet}>
            <Ionicons name="checkmark-circle" size={18} color={Colors.recovery} style={styles.bulletIcon} />
            <Text style={styles.bulletText}>{b}</Text>
          </View>
        ))}
      </View>

      <View style={styles.note}>
        <Text style={styles.noteText}>
          The signal is real. What you do with it is still up to you.
        </Text>
      </View>

      <TouchableOpacity
        style={styles.cta}
        onPress={() => nav.navigate('Step8Name', route.params)}
        activeOpacity={0.8}
      >
        <Text style={styles.ctaText}>I'm in</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1, backgroundColor: Colors.black,
    paddingHorizontal: Spacing.lg, paddingTop: 80, paddingBottom: 56, gap: Spacing.xl,
  },
  header: { gap: 8 },
  step: { ...Typography.label, color: Colors.textMuted },
  title: { fontSize: 26, fontWeight: '700', letterSpacing: -0.7, color: Colors.text, lineHeight: 32 },
  sub: { ...Typography.bodySmall, color: Colors.textSecondary },
  bullets: { gap: Spacing.md },
  bullet: { flexDirection: 'row', gap: Spacing.sm, alignItems: 'flex-start' },
  bulletIcon: { marginTop: 2 },
  bulletText: { flex: 1, fontSize: 15, color: Colors.textSecondary, lineHeight: 22, fontWeight: '400' },
  note: {
    backgroundColor: Colors.surface2, borderRadius: Radius.md,
    borderWidth: 1, borderColor: Colors.border,
    padding: Spacing.md,
  },
  noteText: { ...Typography.body, color: Colors.text, fontStyle: 'italic', textAlign: 'center' },
  cta: { backgroundColor: Colors.readiness, borderRadius: 14, paddingVertical: 18, alignItems: 'center' },
  ctaText: { fontSize: 17, fontWeight: '700', color: Colors.black },
});
