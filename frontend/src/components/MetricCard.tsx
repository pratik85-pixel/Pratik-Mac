import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { Colors, Spacing, Radius, Typography } from '../theme';

interface MetricCardProps {
  label: string;
  value: string | number;
  unit?: string;
  sub?: string;
  color?: string;
  onPress?: () => void;
}

export default function MetricCard({ label, value, unit, sub, color, onPress }: MetricCardProps) {
  const Container = onPress ? TouchableOpacity : View;
  return (
    <Container
      style={styles.card}
      onPress={onPress}
      activeOpacity={0.75}
    >
      <Text style={styles.label}>{label}</Text>
      <View style={styles.valueRow}>
        <Text style={[styles.value, color ? { color } : {}]}>{value}</Text>
        {unit ? <Text style={styles.unit}>{unit}</Text> : null}
      </View>
      {sub ? <Text style={styles.sub}>{sub}</Text> : null}
    </Container>
  );
}

const styles = StyleSheet.create({
  card: {
    flex: 1,
    backgroundColor: Colors.surface2,
    borderRadius: Radius.md,
    borderWidth: 1,
    borderColor: Colors.border,
    padding: Spacing.md,
    gap: 4,
  },
  label: {
    ...Typography.label,
    color: Colors.textMuted,
  },
  valueRow: { flexDirection: 'row', alignItems: 'baseline', gap: 3 },
  value: {
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: -0.5,
    color: Colors.text,
  },
  unit: {
    fontSize: 13,
    fontWeight: '500',
    color: Colors.textSecondary,
    marginBottom: 2,
  },
  sub: {
    ...Typography.bodySmall,
    color: Colors.textMuted,
    fontSize: 11,
  },
});
