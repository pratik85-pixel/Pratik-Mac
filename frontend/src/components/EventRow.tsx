import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Colors, Spacing, Radius, Typography } from '../theme';
import type { StressWindow, RecoveryWindow } from '../types';

interface EventRowProps {
  type: 'stress' | 'recovery';
  event: StressWindow | RecoveryWindow;
  onTagPress?: () => void;
}

function formatTime(iso: string) {
  const d = new Date(iso);
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
}

function slugToLabel(slug: string | null): string {
  if (!slug) return '';
  return slug.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function EventRow({ type, event, onTagPress }: EventRowProps) {
  const isStress = type === 'stress';
  const se = event as StressWindow;
  const re = event as RecoveryWindow;

  const contribution = isStress
    ? se.stress_contribution_pct
    : re.recovery_contribution_pct;

  const tag = isStress ? se.tag : re.tag;
  const candidate = isStress ? se.tag_candidate : null;
  const untagged = !tag;
  const showTagCta = untagged && onTagPress;

  const barColor = isStress ? Colors.stress : Colors.recovery;
  const barWidth = Math.min(100, contribution ?? 0);

  return (
    <View style={styles.row}>
      {/* Time + duration */}
      <View style={styles.timeCol}>
        <Text style={styles.time}>{formatTime(event.started_at)}</Text>
        <Text style={styles.duration}>{Math.round(event.duration_minutes)}m</Text>
      </View>

      {/* Bar + label */}
      <View style={styles.body}>
        <View style={styles.barTrack}>
          <View style={[styles.barFill, { width: `${barWidth}%` as any, backgroundColor: barColor }]} />
        </View>
        <View style={styles.labelRow}>
          {tag ? (
            <Text style={[styles.tag, { color: barColor }]}>{slugToLabel(tag)}</Text>
          ) : candidate ? (
            <Text style={styles.candidate}>{slugToLabel(candidate)}</Text>
          ) : null}
          {contribution != null && (
            <Text style={styles.pct}>{Math.round(contribution)}%</Text>
          )}
        </View>
      </View>

      {/* Tag CTA */}
      {showTagCta ? (
        <TouchableOpacity onPress={onTagPress} style={styles.tagCta}>
          <Text style={styles.tagCtaText}>Tag?</Text>
        </TouchableOpacity>
      ) : (
        <View style={styles.iconCol}>
          <Ionicons
            name={tag ? 'checkmark-circle' : 'ellipse-outline'}
            size={16}
            color={tag ? barColor : Colors.textMuted}
          />
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: Spacing.sm,
    gap: Spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderFaint,
  },
  timeCol: { width: 52, alignItems: 'flex-start' },
  time: { ...Typography.bodySmall, fontSize: 12, color: Colors.textSecondary },
  duration: { ...Typography.labelSmall, color: Colors.textMuted, marginTop: 2, textTransform: 'none' },
  body: { flex: 1, gap: 5 },
  barTrack: {
    height: 3,
    backgroundColor: Colors.surface2,
    borderRadius: 2,
    overflow: 'hidden',
  },
  barFill: { height: '100%', borderRadius: 2 },
  labelRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  tag: { fontSize: 12, fontWeight: '500' },
  candidate: { fontSize: 12, color: Colors.textMuted, fontStyle: 'italic' },
  pct: { ...Typography.labelSmall, color: Colors.textMuted, textTransform: 'none' },
  tagCta: {
    backgroundColor: Colors.surface2,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: Radius.full,
    borderWidth: 1,
    borderColor: Colors.readiness,
  },
  tagCtaText: { fontSize: 11, color: Colors.readiness, fontWeight: '600' },
  iconCol: { width: 20, alignItems: 'center' },
});
