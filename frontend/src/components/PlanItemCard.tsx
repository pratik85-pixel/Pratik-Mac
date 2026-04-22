import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import Svg, { Circle } from 'react-native-svg';
import { Ionicons } from '@expo/vector-icons';
import { Colors, Spacing, Radius } from '../theme';
import type { PlanItem } from '../types';

interface PlanItemCardProps {
  item: PlanItem;
  onPress?: () => void;
}

const RING_SIZE = 52;
const STROKE    = 4;
const R         = (RING_SIZE - STROKE * 2) / 2;
const CIRCUM    = 2 * Math.PI * R;

const CATEGORY_ICONS: Record<string, string> = {
  zenflow_session:     'radio-button-on',
  movement:            'walk',
  mindfulness:         'leaf',
  habitual_relaxation: 'musical-notes',
  sleep:               'moon',
  recovery_active:     'snow',
};

export default function PlanItemCard({ item, onPress }: PlanItemCardProps) {
  const isComplete = item.has_evidence === true;
  const progress   = isComplete ? 1 : Math.min(1, Math.max(0, item.adherence_score ?? 0));
  const dashOffset = CIRCUM * (1 - progress);
  const iconName   = CATEGORY_ICONS[item.category] ?? 'checkmark-circle-outline';

  const ringLabel = isComplete
    ? null
    : item.duration_minutes >= 60
      ? String(Math.floor(item.duration_minutes / 60)) + ':' + String(item.duration_minutes % 60).padStart(2, '0')
      : String(item.duration_minutes) + 'm';

  return (
    <TouchableOpacity
      onPress={onPress}
      activeOpacity={0.75}
      style={styles.row}
      accessibilityRole="button"
      accessibilityLabel={`${item.title}, ${isComplete ? 'completed' : `${item.duration_minutes} minutes`}`}
      accessibilityState={{ checked: isComplete }}
      accessibilityHint={isComplete ? 'Already done' : 'Tap to view details or mark complete'}
    >
      <View style={styles.iconWrap}>
        <Ionicons
          name={iconName as any}
          size={18}
          color={isComplete ? Colors.recovery : Colors.textMuted}
        />
      </View>

      <View style={styles.textWrap}>
        <Text
          style={[styles.title, isComplete && styles.titleDone]}
          numberOfLines={2}
        >
          {item.title}
        </Text>
        {item.target_start_time ? (
          <Text style={styles.sub}>
            {item.target_start_time}{item.target_end_time ? ' - ' + item.target_end_time : ''}
          </Text>
        ) : (
          <Text style={styles.sub}>{item.duration_minutes} min</Text>
        )}
      </View>

      <View style={styles.ringWrap}>
        {isComplete ? (
          <View style={styles.tickCircle}>
            <Ionicons name="checkmark" size={24} color={Colors.recovery} />
          </View>
        ) : (
          <View style={{ width: RING_SIZE, height: RING_SIZE }}>
            <Svg width={RING_SIZE} height={RING_SIZE}>
              <Circle
                cx={RING_SIZE / 2}
                cy={RING_SIZE / 2}
                r={R}
                stroke={Colors.surface3}
                strokeWidth={STROKE}
                fill="none"
              />
              <Circle
                cx={RING_SIZE / 2}
                cy={RING_SIZE / 2}
                r={R}
                stroke={Colors.recovery}
                strokeWidth={STROKE}
                fill="none"
                strokeDasharray={String(CIRCUM) + ' ' + String(CIRCUM)}
                strokeDashoffset={dashOffset}
                strokeLinecap="round"
                rotation="-90"
                origin={String(RING_SIZE / 2) + ', ' + String(RING_SIZE / 2)}
              />
            </Svg>
            {ringLabel !== null && (
              <View style={StyleSheet.absoluteFill} pointerEvents="none">
                <View style={styles.ringLabelWrap}>
                  <Text style={styles.ringLabel}>{ringLabel}</Text>
                </View>
              </View>
            )}
          </View>
        )}
      </View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection:     'row',
    alignItems:        'center',
    paddingVertical:   Spacing.md,
    gap:               Spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
  },
  iconWrap: {
    width:           32,
    height:          32,
    borderRadius:    Radius.sm,
    backgroundColor: Colors.surface2,
    alignItems:      'center',
    justifyContent:  'center',
  },
  textWrap: {
    flex: 1,
    gap:  3,
  },
  title: {
    fontSize:   15,
    fontWeight: '600',
    color:      Colors.text,
    lineHeight: 20,
  },
  titleDone: {
    color:              Colors.textSecondary,
    textDecorationLine: 'line-through',
  },
  sub: {
    fontSize: 12,
    color:    Colors.textMuted,
  },
  ringWrap: {
    alignItems:     'center',
    justifyContent: 'center',
    width:          RING_SIZE,
    height:         RING_SIZE,
  },
  tickCircle: {
    width:          RING_SIZE,
    height:         RING_SIZE,
    borderRadius:   RING_SIZE / 2,
    borderWidth:    STROKE,
    borderColor:    Colors.recovery,
    alignItems:     'center',
    justifyContent: 'center',
  },
  ringLabelWrap: {
    flex:           1,
    alignItems:     'center',
    justifyContent: 'center',
  },
  ringLabel: {
    fontSize:   10,
    fontWeight: '700',
    color:      Colors.text,
    textAlign:  'center',
  },
});
