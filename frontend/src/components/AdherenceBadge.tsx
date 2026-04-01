import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

export type AdherenceStatus = 'pending' | 'confirmed' | 'deviation';

interface AdherenceBadgeProps {
  status?: AdherenceStatus;
}

export default function AdherenceBadge({ status = 'pending' }: AdherenceBadgeProps) {
  const getConfig = () => {
    switch (status) {
      case 'confirmed':
        return { label: 'On Track', color: '#4CAF50', bg: '#E8F5E9', icon: 'checkmark-circle' as const };
      case 'deviation':
        return { label: 'Adjusted', color: '#F44336', bg: '#FFEBEE', icon: 'shuffle' as const };
      case 'pending':
      default:
        return { label: 'Pending', color: '#9E9E9E', bg: '#F5F5F5', icon: 'time-outline' as const };
    }
  };

  const { label, color, bg, icon } = getConfig();

  return (
    <View style={[styles.container, { backgroundColor: bg }]}>
      <Ionicons name={icon} size={14} color={color} style={styles.icon} />
      <Text style={[styles.text, { color }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 8,
    alignSelf: 'flex-start',
  },
  icon: {
    marginRight: 4,
  },
  text: {
    fontSize: 11,
    fontWeight: '600',
    textTransform: 'uppercase',
  }
});
