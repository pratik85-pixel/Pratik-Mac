import React from 'react';
import { View, StyleSheet } from 'react-native';
import { Colors, Radius } from '../theme';

interface ProgressBarProps {
  value: number; // 0–100
  color?: string;
  height?: number;
  trackColor?: string;
}

export default function ProgressBar({
  value,
  color = Colors.readiness,
  height = 4,
  trackColor = Colors.surface2,
}: ProgressBarProps) {
  const pct = Math.min(100, Math.max(0, value));
  return (
    <View style={[styles.track, { height, backgroundColor: trackColor }]}>
      <View
        style={[
          styles.fill,
          { width: `${pct}%` as any, height, backgroundColor: color },
        ]}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  track: {
    borderRadius: Radius.full,
    overflow: 'hidden',
    width: '100%',
  },
  fill: {
    borderRadius: Radius.full,
  },
});
