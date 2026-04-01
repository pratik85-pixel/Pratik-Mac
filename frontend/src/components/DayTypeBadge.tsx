import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Colors, Radius, Typography } from '../theme';

type DayType = 'GREEN' | 'YELLOW' | 'RED' | string;

interface DayTypeBadgeProps {
  dayType: DayType;
  small?: boolean;
}

const CONFIG: Record<string, { color: string; bg: string; label: string }> = {
  GREEN:  { color: Colors.recovery,  bg: Colors.recoveryDim,  label: 'Green Day'  },
  YELLOW: { color: Colors.zone4,     bg: '#2D2200',           label: 'Yellow Day' },
  RED:    { color: Colors.stress,    bg: Colors.stressDim,    label: 'Red Day'    },
};

function getConfig(dayType: DayType) {
  const upper = dayType?.toUpperCase();
  return CONFIG[upper] ?? { color: Colors.textMuted, bg: Colors.surface2, label: dayType ?? 'Unknown' };
}

export default function DayTypeBadge({ dayType, small }: DayTypeBadgeProps) {
  const cfg = getConfig(dayType);
  return (
    <View
      style={[
        styles.badge,
        { backgroundColor: cfg.bg, borderColor: cfg.color + '55' },
        small && styles.small,
      ]}
    >
      <Text style={[styles.text, { color: cfg.color }, small && styles.smallText]}>
        {cfg.label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    paddingHorizontal: 12,
    paddingVertical: 5,
    borderRadius: Radius.full,
    borderWidth: 1,
    alignSelf: 'flex-start',
  },
  small: { paddingHorizontal: 8, paddingVertical: 3 },
  text: {
    ...Typography.label,
    fontSize: 11,
  },
  smallText: { fontSize: 10 },
});
