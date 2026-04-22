/**
 * ActivityCard — WHOOP-style card for a stress/recovery event.
 *
 * Layout mirrors the reference:
 *   [icon badge] [name + sub]  [time range]  |
 *
 * If the event is untagged a "Tag →" CTA is rendered underneath.
 */
import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { Colors, Radius, Spacing } from '../theme';
import type { StressWindow, RecoveryWindow } from '../types';

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt12(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
}

function slugToLabel(slug: string | null | undefined): string {
  if (!slug) return '';
  return slug.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function durStr(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}`;
  return `${m}m`;
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface ActivityCardProps {
  type: 'stress' | 'recovery';
  event: StressWindow | RecoveryWindow;
  onTagPress?: () => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function ActivityCard({ type, event, onTagPress }: ActivityCardProps) {
  const isStress = type === 'stress';
  const se = event as StressWindow;
  const re = event as RecoveryWindow;

  const tag = isStress ? se.tag : re.tag;
  const untagged = !tag;

  const accentColor = isStress ? Colors.stress : Colors.recovery;
  const badgeBg = isStress ? '#3A1A1A' : '#0D2B1A';

  const contribution = isStress ? se.stress_contribution_pct : re.recovery_contribution_pct;
  const durationMins = event.duration_minutes ?? 0;

  // Badge text: contribution % or duration string
  const badgeText = contribution != null
    ? `${Math.round(contribution)}%`
    : durStr(durationMins);

  // Icon inside badge
  const iconName: React.ComponentProps<typeof Ionicons>['name'] = isStress
    ? (tag ? 'flame' : 'flash-outline')
    : (tag === 'sleep' || tag === 'walk' ? 'moon' : 'leaf');

  // Event label
  const eventLabel = tag
    ? slugToLabel(tag).toUpperCase()
    : isStress
    ? 'UNTAGGED SPIKE'
    : 'UNTAGGED REST';

  return (
    <View style={[styles.card, { borderLeftColor: accentColor }]}>
      {/* Badge */}
      <View style={[styles.badge, { backgroundColor: badgeBg }]}>
        <Ionicons name={iconName} size={14} color={accentColor} style={{ marginBottom: 2 }} />
        <Text style={[styles.badgeText, { color: accentColor }]}>{badgeText}</Text>
      </View>

      {/* Middle: label + sub */}
      <View style={styles.body}>
        <Text style={[styles.eventLabel, untagged && styles.untaggedLabel]} numberOfLines={1}>
          {eventLabel}
        </Text>
        <Text style={styles.duration}>{durStr(durationMins)}</Text>
      </View>

      {/* Right: time range */}
      <View style={styles.timeCol}>
        <Text style={styles.time}>{fmt12(event.started_at)}</Text>
        <Text style={styles.time}>{fmt12(event.ended_at)}</Text>
      </View>

      {/* Tag CTA if untagged */}
      {untagged && onTagPress && (
        <TouchableOpacity
          onPress={() => {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
            onTagPress();
          }}
          style={[styles.tagCta, { borderColor: accentColor }]}
          activeOpacity={0.75}
          accessibilityRole="button"
          accessibilityLabel="Tag this activity"
          accessibilityHint="Opens the tagging sheet to label this window"
        >
          <Text style={[styles.tagCtaText, { color: accentColor }]}>Tag</Text>
          <Ionicons name="chevron-forward" size={11} color={accentColor} />
        </TouchableOpacity>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1A1A20',
    borderRadius: Radius.md,
    borderLeftWidth: 3,
    padding: Spacing.md,
    gap: Spacing.sm,
    marginBottom: 8,
  },
  badge: {
    width: 52,
    height: 52,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  badgeText: {
    fontSize: 13,
    fontWeight: '700',
    letterSpacing: -0.3,
  },
  body: {
    flex: 1,
    gap: 3,
  },
  eventLabel: {
    fontSize: 13,
    fontWeight: '700',
    color: '#FFFFFF',
    letterSpacing: 0.4,
  },
  untaggedLabel: {
    color: '#888',
  },
  duration: {
    fontSize: 11,
    color: '#555',
    fontWeight: '500',
  },
  timeCol: {
    alignItems: 'flex-end',
    gap: 3,
  },
  time: {
    fontSize: 11,
    color: '#777',
    fontWeight: '500',
  },
  tagCta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 2,
    borderWidth: 1,
    borderRadius: Radius.full,
    paddingHorizontal: 10,
    paddingVertical: 4,
    marginLeft: 4,
  },
  tagCtaText: {
    fontSize: 11,
    fontWeight: '700',
  },
});
