import React, { ReactNode } from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { Colors, Spacing, Typography } from '../theme';

interface SectionHeaderProps {
  title: string;
  action?: string;
  onAction?: () => void;
  children?: ReactNode;
}

export default function SectionHeader({ title, action, onAction, children }: SectionHeaderProps) {
  return (
    <View style={styles.row}>
      <Text style={styles.title}>{title}</Text>
      <View style={styles.right}>
        {children}
        {action && onAction ? (
          <TouchableOpacity onPress={onAction} activeOpacity={0.7}>
            <Text style={styles.action}>{action}</Text>
          </TouchableOpacity>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: Spacing.sm,
  },
  title: {
    ...Typography.label,
    color: Colors.textMuted,
    fontSize: 11,
  },
  right: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm },
  action: {
    fontSize: 12,
    fontWeight: '600',
    color: Colors.readiness,
    letterSpacing: 0.2,
  },
});
