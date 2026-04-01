/**
 * BandWearSessionDetailScreen
 * Full detail view for a single band-wear session.
 * 4 collapsible sections:
 *   1. Overview   — timeline bar, net balance hero, metric tiles
 *   2. Key Events — stress/recovery event dots + rows
 *   3. Plan Adherence — progress bar + completed items
 *   4. Sleep Analysis — RMSSD sparkline + sleep tiles
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity,
  ActivityIndicator, ScrollView,
} from 'react-native';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { ChevronLeft, ChevronDown, ChevronUp } from 'lucide-react-native';
import Svg, { Path, Line } from 'react-native-svg';
import { LinearGradient } from 'expo-linear-gradient';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  getBandSessionMetrics, getBandSessionPlan,
  type BandSessionMetrics, type BandSessionPlan, type PersonalBaseline,
} from '../api/bandSessions';
import type { HistoryStackParamList } from '../navigation/AppNavigator';
import { ZEN } from '../ui/zenflow-ui-kit';

// ─── Types ────────────────────────────────────────────────────────────────────

type RouteT = RouteProp<HistoryStackParamList, 'BandWearSessionDetail'>;

type ZoneTone = 'excellent' | 'good' | 'normal' | 'low' | 'critical';

// ─── Zone helpers ─────────────────────────────────────────────────────────────

const ZONE_COLORS: Record<ZoneTone, string> = {
  excellent: '#39E27D',
  good:      '#7BE8A5',
  normal:    '#F2D14C',
  low:       '#FF9E5E',
  critical:  '#FF6B6B',
};

const ZONE_BG: Record<ZoneTone, string> = {
  excellent: 'rgba(57,226,125,0.12)',
  good:      'rgba(123,232,165,0.12)',
  normal:    'rgba(242,209,76,0.12)',
  low:       'rgba(255,158,94,0.12)',
  critical:  'rgba(255,107,107,0.12)',
};

const ZONE_BORDER: Record<ZoneTone, string> = {
  excellent: 'rgba(57,226,125,0.28)',
  good:      'rgba(123,232,165,0.28)',
  normal:    'rgba(242,209,76,0.28)',
  low:       'rgba(255,158,94,0.28)',
  critical:  'rgba(255,107,107,0.28)',
};

const ZONE_ARROWS: Record<ZoneTone, string> = {
  excellent: '↑',
  good:      '↑',
  normal:    '→',
  low:       '↓',
  critical:  '↓',
};

function netBalanceZone(net: number | null): ZoneTone {
  if (net === null) return 'normal';
  if (net >= 25)  return 'excellent';
  if (net >= 10)  return 'good';
  if (net >= -5)  return 'normal';
  if (net >= -20) return 'low';
  return 'critical';
}

function stressZone(pct: number | null): ZoneTone {
  if (pct === null) return 'normal';
  if (pct >= 60) return 'critical';
  if (pct >= 45) return 'low';
  if (pct >= 30) return 'normal';
  if (pct >= 15) return 'good';
  return 'excellent';
}

function recoveryZone(pct: number | null): ZoneTone {
  if (pct === null) return 'normal';
  if (pct >= 55) return 'excellent';
  if (pct >= 40) return 'good';
  if (pct >= 25) return 'normal';
  if (pct >= 10) return 'low';
  return 'critical';
}

function rmssdZone(val: number | null, baseline: PersonalBaseline | null): ZoneTone {
  if (val === null) return 'normal';
  const avg = baseline?.rmssd_avg ?? val;
  const ratio = val / avg;
  if (ratio >= 1.15) return 'excellent';
  if (ratio >= 1.00) return 'good';
  if (ratio >= 0.85) return 'normal';
  if (ratio >= 0.70) return 'low';
  return 'critical';
}

function hrZone(val: number | null, baseline: PersonalBaseline | null): ZoneTone {
  if (val === null) return 'normal';
  const floor = baseline?.hr_floor ?? val;
  const ratio = floor / val; // lower HR relative to floor = better
  if (ratio >= 1.10) return 'excellent';
  if (ratio >= 0.95) return 'good';
  if (ratio >= 0.85) return 'normal';
  if (ratio >= 0.75) return 'low';
  return 'critical';
}

function adherenceZone(pct: number | null): ZoneTone {
  if (pct === null) return 'normal';
  if (pct >= 90) return 'excellent';
  if (pct >= 70) return 'good';
  if (pct >= 50) return 'normal';
  if (pct >= 25) return 'low';
  return 'critical';
}

// ─── Formatting helpers ───────────────────────────────────────────────────────

function fmtTime(iso: string) {
  return new Date(iso).toLocaleTimeString('en-IN', {
    hour: '2-digit', minute: '2-digit', hour12: true,
  });
}

function fmtDuration(mins: number | null) {
  if (mins === null) return '—';
  const h = Math.floor(mins / 60);
  const m = Math.round(mins % 60);
  if (h === 0) return `${m}m`;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function Pill({ tone, label }: { tone: ZoneTone; label: string }) {
  return (
    <View style={[
      pill.wrap,
      { backgroundColor: ZONE_BG[tone], borderColor: ZONE_BORDER[tone] },
    ]}>
      <Text style={[pill.text, { color: ZONE_COLORS[tone] }]}>{label}</Text>
    </View>
  );
}

const pill = StyleSheet.create({
  wrap: {
    borderRadius: 999, borderWidth: 1,
    paddingHorizontal: 10, paddingVertical: 4,
    alignSelf: 'flex-start',
  },
  text: { fontSize: 11, fontWeight: '600' },
});

// ─── CollapsibleSection ───────────────────────────────────────────────────────

interface CollapsibleSectionProps {
  title: string;
  right?: React.ReactNode;
  defaultExpanded?: boolean;
  children: React.ReactNode;
}

function CollapsibleSection({
  title, right, defaultExpanded = false, children,
}: CollapsibleSectionProps) {
  const [open, setOpen] = useState(defaultExpanded);

  return (
    <View style={cs.card}>
      <TouchableOpacity
        style={cs.header}
        onPress={() => setOpen(v => !v)}
        activeOpacity={0.75}
      >
        <Text style={cs.title}>{title.toUpperCase()}</Text>
        <View style={cs.rightGroup}>
          {right}
          {open
            ? <ChevronUp   size={14} color={ZEN.colors.textMuted} />
            : <ChevronDown size={14} color={ZEN.colors.textMuted} />
          }
        </View>
      </TouchableOpacity>
      {open && <View style={cs.body}>{children}</View>}
    </View>
  );
}

const cs = StyleSheet.create({
  card: {
    borderRadius: 24,
    borderWidth: 1,
    borderColor: ZEN.colors.borderStrong,
    backgroundColor: ZEN.colors.surface,
    padding: 16,
    marginBottom: 10,
  },
  header: {
    flexDirection: 'row', alignItems: 'center',
    justifyContent: 'space-between',
  },
  title: {
    fontSize: 11,
    textTransform: 'uppercase',
    letterSpacing: 2.2,
    color: ZEN.colors.textMuted,
  },
  rightGroup: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
  },
  body: { marginTop: 16 },
});

// ─── TimelineBar ──────────────────────────────────────────────────────────────

function TimelineBar({
  events,
  startedAt,
  endedAt,
  hasSleep,
}: {
  events: BandSessionMetrics | null;
  startedAt: string;
  endedAt: string | null;
  hasSleep: boolean;
}) {
  const start = new Date(startedAt).getTime();
  const end   = endedAt ? new Date(endedAt).getTime() : Date.now();
  const span  = end - start;

  const stressColor   = '#19B5FE';
  const recoveryColor = '#39E27D';
  const sleepColor    = 'rgba(255,255,255,0.15)';

  return (
    <View>
      <View style={tb.bar}>
        {events?.stress_events.map(e => {
          const pct = ((new Date(e.window_start).getTime() - start) / span) * 100;
          return (
            <View
              key={e.window_id}
              style={[tb.segment, {
                left: `${Math.max(0, Math.min(100, pct))}%` as any,
                width: '4%',
                backgroundColor: stressColor,
                opacity: 0.85,
              }]}
            />
          );
        })}
        {events?.recovery_events.map(e => {
          const pct = ((new Date(e.window_start).getTime() - start) / span) * 100;
          return (
            <View
              key={e.window_id}
              style={[tb.segment, {
                left: `${Math.max(0, Math.min(100, pct))}%` as any,
                width: '4%',
                backgroundColor: recoveryColor,
                opacity: 0.85,
              }]}
            />
          );
        })}
        {hasSleep && (
          <View style={[tb.segment, {
            right: 0, width: '20%',
            backgroundColor: sleepColor,
          }]} />
        )}
      </View>
      <View style={tb.labels}>
        <Text style={tb.labelText}>{fmtTime(startedAt)}</Text>
        {endedAt && <Text style={tb.labelText}>{fmtTime(endedAt)}</Text>}
      </View>
    </View>
  );
}

const tb = StyleSheet.create({
  bar: {
    height: 20,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: ZEN.colors.border,
    backgroundColor: 'rgba(255,255,255,0.04)',
    overflow: 'hidden',
    position: 'relative',
  },
  segment: {
    position: 'absolute',
    top: 0,
    bottom: 0,
  },
  labels: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 6,
  },
  labelText: { fontSize: 11, color: ZEN.colors.textMuted },
});

// ─── MetricTile ───────────────────────────────────────────────────────────────

function MetricTile({
  label, value, zoneLabel, tone,
}: {
  label: string; value: string; zoneLabel: string; tone: ZoneTone;
}) {
  return (
    <View style={mt.tile}>
      <Text style={mt.label}>{label.toUpperCase()}</Text>
      <Text style={mt.value}>{value}</Text>
      <View style={mt.pillRow}>
        <Pill tone={tone} label={zoneLabel} />
      </View>
    </View>
  );
}

const mt = StyleSheet.create({
  tile: {
    flex: 1,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: ZEN.colors.border,
    backgroundColor: ZEN.colors.surfaceSoft,
    padding: 14,
    gap: 6,
  },
  label: {
    fontSize: 10, textTransform: 'uppercase',
    letterSpacing: 2.2, color: ZEN.colors.textMuted,
  },
  value: {
    fontSize: 28, fontWeight: '600',
    letterSpacing: -1, color: ZEN.colors.white,
  },
  pillRow: { marginTop: 2 },
});

// ─── MiniTile ────────────────────────────────────────────────────────────────

function MiniTile({
  label, value, sub, zoneLabel, tone, muted = false,
}: {
  label: string; value: string; sub: string;
  zoneLabel: string; tone: ZoneTone; muted?: boolean;
}) {
  return (
    <View style={min.tile}>
      <Text style={min.label}>{label.toUpperCase()}</Text>
      <Text style={[min.value, muted && { color: ZEN.colors.textSecondary }]}>{value}</Text>
      <Text style={min.sub}>{sub}</Text>
      <View style={{ marginTop: 4 }}>
        <Pill tone={tone} label={zoneLabel} />
      </View>
    </View>
  );
}

const min = StyleSheet.create({
  tile: {
    flex: 1,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: ZEN.colors.border,
    backgroundColor: ZEN.colors.surfaceSoft,
    padding: 12,
    gap: 4,
  },
  label: {
    fontSize: 10, textTransform: 'uppercase',
    letterSpacing: 2, color: ZEN.colors.textMuted,
  },
  value: { fontSize: 20, fontWeight: '600', letterSpacing: -0.5, color: ZEN.colors.white },
  sub:   { fontSize: 11, color: ZEN.colors.textMuted },
});

// ─── RmssSparkline ────────────────────────────────────────────────────────────

function RmssdSparkline({ points }: { points: number[] }) {
  if (points.length < 2) {
    return (
      <View style={sp.empty}>
        <Text style={sp.emptyText}>No signal data</Text>
      </View>
    );
  }

  const W = 288, H = 72;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;

  const coords = points.map((v, i) => ({
    x: (i / (points.length - 1)) * W,
    y: H - ((v - min) / range) * (H - 12) - 6,
  }));

  const d = coords.reduce((acc, p, i) => {
    if (i === 0) return `M${p.x.toFixed(1)} ${p.y.toFixed(1)}`;
    const prev = coords[i - 1];
    const cx = (prev.x + p.x) / 2;
    return `${acc} C${cx.toFixed(1)} ${prev.y.toFixed(1)},${cx.toFixed(1)} ${p.y.toFixed(1)},${p.x.toFixed(1)} ${p.y.toFixed(1)}`;
  }, '');

  const mid = H - ((((max + min) / 2) - min) / range) * (H - 12) - 6;

  return (
    <View style={sp.wrap}>
      <Svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`}>
        <Line
          x1="0" y1={mid.toFixed(1)}
          x2={W.toString()} y2={mid.toFixed(1)}
          stroke="rgba(255,255,255,0.22)"
          strokeDasharray="5 5"
          strokeWidth="1"
        />
        <Path d={d} fill="none" stroke="#39E27D" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      </Svg>
    </View>
  );
}

const sp = StyleSheet.create({
  wrap: {
    borderRadius: 18, borderWidth: 1,
    borderColor: ZEN.colors.border,
    backgroundColor: ZEN.colors.surfaceSoft,
    padding: 12, overflow: 'hidden',
  },
  empty: { padding: 20, alignItems: 'center' },
  emptyText: { fontSize: 12, color: ZEN.colors.textMuted },
});

// ─── Main screen ──────────────────────────────────────────────────────────────

export default function BandWearSessionDetailScreen() {
  const nav   = useNavigation();
  const route = useRoute<RouteT>();
  const {
    sessionId, startedAt, endedAt, durationMinutes,
    stressPct, recoveryPct, netBalance,
    hasSleepData, avgRmssdMs, avgHrBpm,
  } = route.params;

  const [metrics, setMetrics] = useState<BandSessionMetrics | null>(null);
  const [plan,    setPlan]    = useState<BandSessionPlan | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const [mRes, pRes] = await Promise.all([
          getBandSessionMetrics(sessionId),
          getBandSessionPlan(sessionId),
        ]);
        if (active) {
          setMetrics(mRes.data);
          setPlan(pRes.data);
        }
      } catch {}
      finally { if (active) setLoading(false); }
    })();
    return () => { active = false; };
  }, [sessionId]);

  const netTone  = netBalanceZone(netBalance);
  const netColor = ZONE_COLORS[netTone];
  const sign     = netBalance !== null && netBalance > 0 ? '+' : '';
  const netStr   = netBalance !== null ? `${sign}${netBalance.toFixed(1)}` : '—';

  const stressTone   = stressZone(stressPct);
  const recoveryTone = recoveryZone(recoveryPct);
  const baseline     = metrics?.personal ?? null;
  const rmssdTone    = rmssdZone(avgRmssdMs, baseline);
  const hrTone       = hrZone(avgHrBpm, baseline);

  const rmssdUsual = baseline?.rmssd_avg ? `Usual: ${Math.round(baseline.rmssd_avg)}ms` : 'No baseline';
  const hrUsual    = baseline?.hr_floor   ? `Usual: ${Math.round(baseline.hr_floor)} bpm` : 'No baseline';

  const stressEvents   = metrics?.stress_events   ?? [];
  const recoveryEvents = metrics?.recovery_events ?? [];
  const sparkline      = metrics?.rmssd_sparkline ?? [];

  // Sleep duration from timestamps
  let sleepDur = '—';
  let sleepRmssd = '—';
  if (hasSleepData && metrics) {
    sleepRmssd = avgRmssdMs !== null ? `${Math.round(avgRmssdMs)}ms` : '—';
  }

  const eyebrow = (() => {
    const d = new Date(startedAt);
    return d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' });
  })();

  const eventCount = stressEvents.length + recoveryEvents.length + (hasSleepData ? 1 : 0);

  return (
    <LinearGradient
      colors={[ZEN.colors.bgTop, ZEN.colors.bgMid, ZEN.colors.bgBottom]}
      locations={[0, 0.42, 1]}
      style={{ flex: 1 }}
    >
      <SafeAreaView style={{ flex: 1 }} edges={['top', 'bottom']}>
        {/* Header */}
        <View style={d.header}>
          <TouchableOpacity style={d.backBtn} onPress={() => nav.goBack()} activeOpacity={0.8}>
            <ChevronLeft size={20} color={ZEN.colors.textNear} />
          </TouchableOpacity>
          <View style={d.headerCenter}>
            <Text style={d.eyebrow}>{eyebrow}</Text>
            <Text style={d.title}>{fmtDuration(durationMinutes)} Session</Text>
          </View>
          <View style={d.backBtn} />
        </View>

        {loading ? (
          <View style={d.loader}>
            <ActivityIndicator color={ZEN.colors.recovery} />
          </View>
        ) : (
          <ScrollView
            contentContainerStyle={d.scroll}
            showsVerticalScrollIndicator={false}
          >
            {/* ── Section 1: Overview ─────────────────────────────────── */}
            <CollapsibleSection
              title="Overview"
              defaultExpanded
              right={
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                  <Text style={{ fontSize: 14, fontWeight: '600', color: netColor }}>{netStr}</Text>
                  <Pill tone={netTone} label={`${ZONE_ARROWS[netTone]} ${netTone.charAt(0).toUpperCase() + netTone.slice(1)}`} />
                </View>
              }
            >
              {/* Timeline */}
              <TimelineBar
                events={metrics}
                startedAt={startedAt}
                endedAt={endedAt}
                hasSleep={hasSleepData}
              />

              {/* Net Balance hero */}
              <View style={d.balanceHero}>
                <Text style={d.balanceEyebrow}>NET BALANCE</Text>
                <View style={d.balanceRow}>
                  <Text style={[d.balanceValue, { color: netColor }]}>{netStr}</Text>
                  <Pill
                    tone={netTone}
                    label={`${ZONE_ARROWS[netTone]} ${netTone.charAt(0).toUpperCase() + netTone.slice(1)}`}
                  />
                </View>
                <Text style={d.balanceSub}>
                  {netBalance !== null && netBalance > 5
                    ? 'Recovery ahead — strong session'
                    : netBalance !== null && netBalance < -5
                    ? 'Stress-leaning — monitor recovery'
                    : 'Balanced — good regulation'}
                </Text>
              </View>

              {/* Stress / Recovery tiles */}
              <View style={d.tileRow}>
                <MetricTile
                  label="Stress"
                  value={stressPct !== null ? `${Math.round(stressPct)}%` : '—'}
                  zoneLabel={`${ZONE_ARROWS[stressTone]} ${stressTone.charAt(0).toUpperCase() + stressTone.slice(1)}`}
                  tone={stressTone}
                />
                <MetricTile
                  label="Recovery"
                  value={recoveryPct !== null ? `${Math.round(recoveryPct)}%` : '—'}
                  zoneLabel={`${ZONE_ARROWS[recoveryTone]} ${recoveryTone.charAt(0).toUpperCase() + recoveryTone.slice(1)}`}
                  tone={recoveryTone}
                />
              </View>

              {/* RMSSD / HR / SPO2 mini tiles */}
              <View style={[d.tileRow, { marginTop: 10 }]}>
                <MiniTile
                  label="RMSSD"
                  value={avgRmssdMs !== null ? `${Math.round(avgRmssdMs)}ms` : '—'}
                  sub={rmssdUsual}
                  zoneLabel={`${ZONE_ARROWS[rmssdTone]} ${rmssdTone.charAt(0).toUpperCase() + rmssdTone.slice(1)}`}
                  tone={rmssdTone}
                />
                <MiniTile
                  label="HR AVG"
                  value={avgHrBpm !== null ? `${Math.round(avgHrBpm)} bpm` : '—'}
                  sub={hrUsual}
                  zoneLabel={`${ZONE_ARROWS[hrTone]} ${hrTone.charAt(0).toUpperCase() + hrTone.slice(1)}`}
                  tone={hrTone}
                />
                <MiniTile
                  label="SPO2"
                  value="—"
                  sub="Coming soon"
                  zoneLabel="—"
                  tone="normal"
                  muted
                />
              </View>
            </CollapsibleSection>

            {/* ── Section 2: Key Events ───────────────────────────────── */}
            <CollapsibleSection
              title="Key Events"
              right={<Text style={d.secRight}>{eventCount} events</Text>}
            >
              {eventCount === 0 ? (
                <Text style={d.emptyNote}>No tagged events for this session.</Text>
              ) : (
                <>
                  {/* Dot strip */}
                  <View style={d.dotStrip}>
                    {stressEvents.map(e => (
                      <View key={e.window_id} style={d.dotWrap}>
                        <View style={[d.dot, { backgroundColor: '#19B5FE' }]} />
                        <Text style={d.dotLabel}>{fmtTime(e.window_start)}</Text>
                        {e.tag ? <Text style={d.dotTag}>{e.tag}</Text> : null}
                      </View>
                    ))}
                    {recoveryEvents.map(e => (
                      <View key={e.window_id} style={d.dotWrap}>
                        <View style={[d.dot, { backgroundColor: '#39E27D' }]} />
                        <Text style={d.dotLabel}>{fmtTime(e.window_start)}</Text>
                      </View>
                    ))}
                    {hasSleepData && (
                      <View style={d.dotWrap}>
                        <Text style={d.dotMoon}>🌙</Text>
                      </View>
                    )}
                  </View>
                </>
              )}
            </CollapsibleSection>

            {/* ── Section 3: Plan Adherence ───────────────────────────── */}
            <CollapsibleSection
              title="Plan Adherence"
              right={
                plan?.has_plan ? (
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                    <Text style={d.secRight}>
                      {plan.adherence_pct !== null ? `${Math.round(plan.adherence_pct)}%` : '—'}
                    </Text>
                    {plan.adherence_pct !== null && (
                      <Pill
                        tone={adherenceZone(plan.adherence_pct)}
                        label={`${ZONE_ARROWS[adherenceZone(plan.adherence_pct)]} ${adherenceZone(plan.adherence_pct).charAt(0).toUpperCase() + adherenceZone(plan.adherence_pct).slice(1)}`}
                      />
                    )}
                  </View>
                ) : (
                  <Text style={d.secRight}>No plan</Text>
                )
              }
            >
              {!plan?.has_plan ? (
                <Text style={d.emptyNote}>No plan was active during this session.</Text>
              ) : plan.items.length === 0 ? (
                <Text style={d.emptyNote}>No completed items for this session.</Text>
              ) : (
                <>
                  {/* Bar */}
                  <View style={d.adBar}>
                    <View style={[d.adFill, {
                      width: `${Math.min(100, plan.adherence_pct ?? 0)}%`,
                      backgroundColor: ZONE_COLORS[adherenceZone(plan.adherence_pct)],
                    }]} />
                  </View>
                  {/* Items */}
                  <View style={{ gap: 10, marginTop: 12 }}>
                    {plan.items.map(item => (
                      <View key={item.item_id} style={d.planItem}>
                        <Text style={d.planMark}>☑</Text>
                        <Text style={d.planTitle}>{item.title}</Text>
                        <View style={[d.planBadge, { backgroundColor: 'rgba(57,226,125,0.12)', borderColor: 'rgba(57,226,125,0.28)' }]}>
                          <Text style={[d.planBadgeText, { color: '#39E27D' }]}>
                            {item.priority?.replace(/_/g, ' ') ?? 'Done'}
                          </Text>
                        </View>
                      </View>
                    ))}
                  </View>
                </>
              )}
            </CollapsibleSection>

            {/* ── Section 4: Sleep Analysis ───────────────────────────── */}
            {hasSleepData && (
              <CollapsibleSection
                title="Sleep Analysis"
                right={<Text style={d.secRight}>{sleepDur}</Text>}
              >
                <RmssdSparkline points={sparkline} />
                <View style={d.sleepRow}>
                  <Text style={d.sleepStat}>
                    Avg RMSSD · <Text style={d.sleepVal}>{sleepRmssd}</Text>
                  </Text>
                  {avgRmssdMs !== null && (
                    <Pill
                      tone={rmssdZone(avgRmssdMs, baseline)}
                      label={`${ZONE_ARROWS[rmssdZone(avgRmssdMs, baseline)]} ${rmssdZone(avgRmssdMs, baseline).charAt(0).toUpperCase() + rmssdZone(avgRmssdMs, baseline).slice(1)}`}
                    />
                  )}
                  <Text style={d.sleepStat}>
                    Duration · <Text style={d.sleepVal}>{sleepDur}</Text>
                  </Text>
                </View>
                <View style={d.stagingPlaceholder}>
                  <Text style={d.stagingText}>Sleep staging · Coming soon</Text>
                </View>
              </CollapsibleSection>
            )}
          </ScrollView>
        )}
      </SafeAreaView>
    </LinearGradient>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const d = StyleSheet.create({
  header: {
    flexDirection: 'row', alignItems: 'center',
    paddingHorizontal: 16, paddingTop: 8, paddingBottom: 12, gap: 8,
  },
  backBtn: {
    width: 40, height: 40, borderRadius: 20,
    borderWidth: 1, borderColor: ZEN.colors.borderStrong,
    backgroundColor: ZEN.colors.surface,
    alignItems: 'center', justifyContent: 'center',
  },
  headerCenter: { flex: 1, alignItems: 'center' },
  eyebrow: { fontSize: 10, textTransform: 'uppercase', letterSpacing: 2.4, color: ZEN.colors.textMuted },
  title:   { fontSize: 22, fontWeight: '600', letterSpacing: -0.5, color: ZEN.colors.white, marginTop: 4 },

  loader: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  scroll: { paddingHorizontal: 16, paddingBottom: 40 },

  balanceHero: { marginTop: 16, alignItems: 'center' },
  balanceEyebrow: { fontSize: 10, textTransform: 'uppercase', letterSpacing: 2.4, color: ZEN.colors.textMuted },
  balanceRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 8 },
  balanceValue: { fontSize: 34, fontWeight: '600', letterSpacing: -1.5 },
  balanceSub: { fontSize: 13, color: ZEN.colors.textSecondary, marginTop: 6 },

  tileRow: { flexDirection: 'row', gap: 10, marginTop: 16 },

  secRight: { fontSize: 12, color: ZEN.colors.textSecondary },
  emptyNote: { fontSize: 13, color: ZEN.colors.textMuted, textAlign: 'center', paddingVertical: 8 },

  dotStrip: {
    flexDirection: 'row', flexWrap: 'wrap', gap: 12,
    borderRadius: 18, borderWidth: 1,
    borderColor: ZEN.colors.border,
    backgroundColor: ZEN.colors.surfaceSoft,
    padding: 12,
  },
  dotWrap: { alignItems: 'center', gap: 4 },
  dot:     { width: 10, height: 10, borderRadius: 5 },
  dotLabel: { fontSize: 11, color: ZEN.colors.textSecondary },
  dotTag:   { fontSize: 10, color: ZEN.colors.textMuted },
  dotMoon:  { fontSize: 18 },

  adBar: {
    height: 12, borderRadius: 999,
    backgroundColor: 'rgba(255,255,255,0.08)', overflow: 'hidden',
  },
  adFill: { height: '100%', borderRadius: 999 },

  planItem: {
    flexDirection: 'row', alignItems: 'center', gap: 10,
  },
  planMark:  { fontSize: 16, color: '#39E27D' },
  planTitle: { flex: 1, fontSize: 13, color: ZEN.colors.textBody },
  planBadge: {
    borderRadius: 999, borderWidth: 1,
    paddingHorizontal: 8, paddingVertical: 3,
  },
  planBadgeText: { fontSize: 10, textTransform: 'uppercase', letterSpacing: 1 },

  sleepRow: {
    flexDirection: 'row', alignItems: 'center',
    justifyContent: 'space-between', marginTop: 10,
  },
  sleepStat: { fontSize: 13, color: ZEN.colors.textSecondary },
  sleepVal:  { color: ZEN.colors.white },

  stagingPlaceholder: {
    marginTop: 12, borderRadius: 14, borderWidth: 1,
    borderColor: ZEN.colors.border, borderStyle: 'dashed',
    paddingVertical: 14, alignItems: 'center',
  },
  stagingText: { fontSize: 12, color: ZEN.colors.textMuted },
});
