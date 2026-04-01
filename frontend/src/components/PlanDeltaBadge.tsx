import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

interface PlanDeltaBadgeProps {
  count?: number;
}

export default function PlanDeltaBadge({ count = 0 }: PlanDeltaBadgeProps) {
  if (count === 0) return null;

  return (
    <View style={styles.container}>
      <Text style={styles.text}>{count > 99 ? '99+' : count}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: '#4A90E2',
    minWidth: 20,
    height: 20,
    borderRadius: 10,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 6,
    alignSelf: 'flex-start',
  },
  text: {
    color: '#FFF',
    fontSize: 12,
    fontWeight: 'bold',
  }
});
