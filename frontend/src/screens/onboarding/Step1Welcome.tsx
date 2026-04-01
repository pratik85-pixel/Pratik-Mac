import React from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { LinearGradient } from 'expo-linear-gradient';
import { Colors, Spacing, Typography } from '../../theme';

export default function Step1Welcome() {
  const nav = useNavigation<NativeStackNavigationProp<any>>();
  return (
    <View style={styles.root}>
      <View style={styles.top}>
        <Text style={styles.headline}>Your body is{'\n'}smarter than{'\n'}you think.</Text>
        <Text style={styles.sub}>
          ZenFlow reads your nervous system in real time —
          not steps or calories, but the actual signal underneath your stress and energy.
        </Text>
      </View>
      <View style={styles.bottom}>
        <Text style={styles.hint}>Heart signal only. No band needed to start.</Text>
        <TouchableOpacity style={styles.cta} onPress={() => nav.navigate('Step2Goal')} activeOpacity={0.8}>
          <Text style={styles.ctaText}>Let's begin</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: Colors.black,
    paddingHorizontal: Spacing.lg,
    paddingTop: 100,
    paddingBottom: 56,
    justifyContent: 'space-between',
  },
  top: { gap: Spacing.lg },
  headline: {
    fontSize: 44,
    fontWeight: '800',
    letterSpacing: -2,
    color: Colors.text,
    lineHeight: 50,
  },
  sub: {
    ...Typography.body,
    color: Colors.textSecondary,
    lineHeight: 24,
    maxWidth: 320,
  },
  bottom: { gap: Spacing.md },
  hint: {
    ...Typography.bodySmall,
    color: Colors.textMuted,
    textAlign: 'center',
  },
  cta: {
    backgroundColor: Colors.readiness,
    borderRadius: 14,
    paddingVertical: 18,
    alignItems: 'center',
  },
  ctaText: {
    fontSize: 17,
    fontWeight: '700',
    color: Colors.black,
    letterSpacing: 0.3,
  },
});
