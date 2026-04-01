import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ViewStyle } from 'react-native';
import { Colors, Spacing, Radius, Typography } from '../theme';

type Variant = 'stress' | 'recovery' | 'readiness';

interface ScoreCardProps {
  variant: Variant;
  value: number | null;
  label: string;
  sub?: string;
  isEstimated?: boolean;
  onPress?: () => void;
  style?: ViewStyle;
  large?: boolean;
}

const VARIANT_CONFIG = {
  stress: {
    color: Colors.stress,
    dimBg: Colors.stressDim,
    border: '#4D1A17',
  },
  recovery: {
    color: Colors.recovery,
    dimBg: Colors.recoveryDim,
    border: '#0D3320',
  },
  readiness: {
    color: Colors.readiness,
    dimBg: Colors.readinessDim,
    border: '#0D2040',
  },
};

export default function ScoreCard({
  variant,
  value,
  label,
  sub,
  isEstimated,
  onPress,
  style,
  large = false,
}: ScoreCardProps) {
  const cfg = VARIANT_CONFIG[variant];
  const displayValue = value != null ? Math.round(value) : '—';

  return (
    <TouchableOpacity
      onPress={onPress}
      activeOpacity={onPress ? 0.7 : 1}
      style={[styles.card, { borderColor: cfg.border }, style]}
    >
      <Text style={[styles.label]}>{label}</Text>
      <Text style={[styles.score, { color: cfg.color }, large && styles.scoreLarge]}>
        {displayValue}
      </Text>
      {isEstimated && <Text style={styles.estimated}>est.</Text>}
      {sub ? <Text style={styles.sub}>{sub}</Text> : null}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  card: {
    flex: 1,
    backgroundColor: Colors.surface1,
    borderRadius: Radius.lg,
    borderWidth: 1,
    padding: Spacing.md,
    alignItems: 'center',
    gap: 4,
  },
  label: {
    ...Typography.label,
    textAlign: 'center',
  },
  score: {
    fontSize: 52,
    fontWeight: '700',
    letterSpacing: -2,
  },
  scoreLarge: {
    fontSize: 72,
    letterSpacing: -3,
  },
  estimated: {
    ...Typography.labelSmall,
    color: Colors.textMuted,
  },
  sub: {
    ...Typography.bodySmall,
    textAlign: 'center',
    color: Colors.textMuted,
    fontSize: 11,
    marginTop: 2,
  },
});
