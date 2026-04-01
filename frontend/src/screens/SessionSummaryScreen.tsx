import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import type { HomeStackParamList } from '../navigation/AppNavigator';
import {
  ZEN,
  ZenScreen,
  BackBtn,
  SectionCard,
  SectionEyebrow,
  ScoreRing,
} from '../ui/zenflow-ui-kit';

type RouteParams = RouteProp<HomeStackParamList, 'SessionSummary'>;

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true });
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' });
}

export default function SessionSummaryScreen() {
  const nav    = useNavigation();
  const route  = useRoute<RouteParams>();
  const params = route.params;

  const {
    started_at,
    ended_at,
    duration_minutes,
    practice_type,
    session_score,
    coherence_avg,
    is_open,
  } = params;

  const scoreDisplay = session_score !== null ? Math.round(session_score) : null;
  const scoreProgress = session_score !== null ? Math.min(1, session_score / 100) : 0;
  const coherencePct  = coherence_avg !== null ? Math.round(coherence_avg * 100) : null;

  const durationLabel = duration_minutes !== null
    ? `${Math.round(duration_minutes)} min`
    : is_open ? 'In progress' : '—';

  const practiceLabel = practice_type
    ? practice_type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
    : 'Session';

  return (
    <ZenScreen scrollable>
      <View style={s.header}>
        <BackBtn onPress={() => nav.goBack()} />
        <View style={s.headerMeta}>
          <Text style={s.dateLabel}>{formatDate(started_at)}</Text>
          <Text style={s.timeRange}>
            {formatTime(started_at)}{ended_at ? ` – ${formatTime(ended_at)}` : ' (open)'}
          </Text>
        </View>
      </View>

      <SectionCard>
        <SectionEyebrow>{practiceLabel}</SectionEyebrow>

        {/* Score ring */}
        <View style={s.ringRow}>
          <ScoreRing
            value={scoreDisplay}
            suffix=""
            progress={scoreProgress}
            color={ZEN.colors.recovery}
            size={140}
            stroke={10}
          />
          <View style={s.ringMeta}>
            <Text style={s.metaLabel}>Duration</Text>
            <Text style={s.metaValue}>{durationLabel}</Text>
            {coherencePct !== null && (
              <>
                <Text style={[s.metaLabel, { marginTop: 12 }]}>Coherence</Text>
                <Text style={s.metaValue}>{coherencePct}%</Text>
              </>
            )}
          </View>
        </View>
      </SectionCard>

      {is_open && (
        <View style={s.openBanner}>
          <Text style={s.openBannerText}>Session still streaming — score updates after it ends</Text>
        </View>
      )}
    </ZenScreen>
  );
}

const s = StyleSheet.create({
  header: {
    flexDirection:  'row',
    alignItems:     'center',
    gap:            12,
    paddingBottom:  8,
  },
  headerMeta: {
    flex: 1,
  },
  dateLabel: {
    fontSize:     12,
    color:        ZEN.colors.textMuted,
    fontWeight:   '600',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  timeRange: {
    fontSize:   17,
    fontWeight: '700',
    color:      ZEN.colors.textNear,
    marginTop:  2,
  },
  ringRow: {
    flexDirection:  'row',
    alignItems:     'center',
    gap:            24,
    paddingTop:     12,
    justifyContent: 'center',
  },
  ringMeta: {
    flex: 1,
  },
  metaLabel: {
    fontSize:   11,
    fontWeight: '600',
    color:      ZEN.colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  metaValue: {
    fontSize:   22,
    fontWeight: '700',
    color:      ZEN.colors.textNear,
    marginTop:  2,
  },
  openBanner: {
    marginTop:        8,
    paddingHorizontal: 16,
    paddingVertical:  12,
    borderRadius:     10,
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderWidth:     1,
    borderColor:     'rgba(255,255,255,0.10)',
  },
  openBannerText: {
    fontSize:  13,
    color:     ZEN.colors.textMuted,
    textAlign: 'center',
  },
});
