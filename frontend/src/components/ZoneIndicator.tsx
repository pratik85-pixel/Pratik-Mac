import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

export type ZoneType = 'Settling' | 'Finding it' | 'In Sync' | 'Flow';

interface ZoneIndicatorProps {
  zone?: ZoneType;
}

export default function ZoneIndicator({ zone = 'Settling' }: ZoneIndicatorProps) {
  const getZoneStyles = () => {
    switch (zone) {
      case 'Flow':
        return { bg: '#E8F5E9', text: '#2E7D32', icon: 'leaf-outline' as const };
      case 'In Sync':
        return { bg: '#E3F2FD', text: '#1565C0', icon: 'water-outline' as const };
      case 'Finding it':
        return { bg: '#FFF3E0', text: '#EF6C00', icon: 'search-outline' as const };
      case 'Settling':
      default:
        return { bg: '#F5F5F5', text: '#616161', icon: 'body-outline' as const };
    }
  };

  const { bg, text, icon } = getZoneStyles();

  return (
    <View style={[styles.container, { backgroundColor: bg }]}>
      <Ionicons name={icon} size={14} color={text} style={styles.icon} />
      <Text style={[styles.text, { color: text }]}>{zone}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 16,
    alignSelf: 'flex-start',
  },
  icon: {
    marginRight: 4,
  },
  text: {
    fontSize: 12,
    fontWeight: '600',
    letterSpacing: 0.3,
  }
});
