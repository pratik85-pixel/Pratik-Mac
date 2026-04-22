import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, RefreshControl, Modal, Pressable,
} from 'react-native';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import {
  Wind, Moon, Dumbbell, Brain, Leaf, Coffee, Activity,
  Sparkles, Clock, CheckCircle, Circle,
  ArrowLeft, ArrowRight,
} from 'lucide-react-native';
import TopHeader from '../components/TopHeader';
import EmptyState from '../components/EmptyState';
import { useDailyData } from '../contexts/DailyDataContext';
import { getTodayPlan, markPlanItemComplete } from '../api/plan';
import { getMorningBrief } from '../api/coach';
import { getMorningRecap } from '../api/tracking';
import type { DailyPlan, MorningBriefResponse, MorningRecapResponse, PlanItem } from '../types';
import {
  ZEN, ZenScreen, SurfaceCard, SectionEyebrow,
} from '../ui/zenflow-ui-kit';

// ─── Time helpers ──────────────────────────────────────────────────────────────

const toMins = (hhmm: string): number => {
  const h = parseInt(hhmm.slice(0, 2), 10);
  const m = parseInt(hhmm.slice(3, 5), 10) || 0;
  return h * 60 + m;
};

const fmtTime = (hhmm: string): string => {
  const h = parseInt(hhmm.slice(0, 2), 10);
  const m = parseInt(hhmm.slice(3, 5), 10) || 0;
  const suffix = h < 12 ? 'AM' : 'PM';
  const hour = h % 12 || 12;
  return m === 0 ? `${hour} ${suffix}` : `${hour}:${String(m).padStart(2, '0')} ${suffix}`;
};

const timeOfDay = (hhmm: string | null): string => {
  if (!hhmm) return '';
  const h = parseInt(hhmm.slice(0, 2), 10);
  if (h < 9)  return 'Morning';
  if (h < 12) return 'Late Morning';
  if (h < 14) return 'Midday';
  if (h < 17) return 'Afternoon';
  if (h < 20) return 'Evening';
  return 'Night';
};

// ─── Category icon mapping ─────────────────────────────────────────────────────

function CategoryIcon({ slug, size = 22, color = 'rgba(255,255,255,0.80)' }: { slug: string; size?: number; color?: string }) {
  const s = (slug ?? '').toLowerCase();
  if (s.includes('breath') || s.includes('wind') || s.includes('pranas')) return <Wind size={size} color={color} />;
  if (s.includes('sleep') || s.includes('rest') || s.includes('nap'))     return <Moon size={size} color={color} />;
  if (s.includes('strength') || s.includes('gym') || s.includes('lift'))  return <Dumbbell size={size} color={color} />;
  if (s.includes('meditat') || s.includes('mindful'))                     return <Brain size={size} color={color} />;
  if (s.includes('recover') || s.includes('nature'))                      return <Leaf size={size} color={color} />;
  if (s.includes('coffee') || s.includes('caffein') || s.includes('lifestyle')) return <Coffee size={size} color={color} />;
  return <Activity size={size} color={color} />;
}

// ─── Priority helpers ──────────────────────────────────────────────────────────

const priorityColor = (p: PlanItem['priority']): string => {
  if (p === 'must_do')      return ZEN.colors.recovery;
  if (p === 'recommended')  return 'rgba(255,255,255,0.55)';
  return 'rgba(255,255,255,0.30)';
};

const priorityLabel = (p: PlanItem['priority']): string => {
  if (p === 'must_do')     return 'MUST DO';
  if (p === 'recommended') return 'RECOMMENDED';
  return 'OPTIONAL';
};

function hasCoachBriefContent(b: MorningBriefResponse | null | undefined): boolean {
  if (!b) return false;
  return [b.brief_text, b.evidence, b.one_action].some(
    (s) => (s ?? '').trim().length > 0,
  );
}

// ─── Activity Row ──────────────────────────────────────────────────────────────

function ActivityRow({ item, onPress }: { item: PlanItem; onPress: () => void }) {
  const slug = item.activity_type_slug ?? item.category ?? '';
  const pColor = priorityColor(item.priority);
  const iconTint = item.has_evidence ? 'rgba(255,255,255,0.30)' : pColor;

  return (
    <TouchableOpacity style={row.wrap} activeOpacity={0.72} onPress={onPress}>
      <View style={[row.iconBox, { borderColor: item.has_evidence ? 'rgba(255,255,255,0.08)' : `${pColor}44` }]}>
        <CategoryIcon slug={slug} size={20} color={iconTint} />
      </View>

      <View style={row.mid}>
        <Text style={[row.title, item.has_evidence && row.titleDone]} numberOfLines={1}>
          {item.title}
        </Text>
        <Text style={[row.sub, { color: item.has_evidence ? 'rgba(255,255,255,0.25)' : pColor }]}>
          {priorityLabel(item.priority)}
          {item.target_start_time ? `  ·  ${fmtTime(item.target_start_time)}` : ''}
          {`  ·  ${item.duration_minutes}m`}
        </Text>
      </View>

      <View style={row.status}>
        {item.has_evidence
          ? <CheckCircle size={20} color={ZEN.colors.recovery} />
          : <Circle size={20} color="rgba(255,255,255,0.18)" />}
      </View>
    </TouchableOpacity>
  );
}

// ─── Activity Detail Sheet ─────────────────────────────────────────────────────

interface SheetProps {
  item: PlanItem;
  onClose: () => void;
  onComplete: (id: string) => void;
  completing: boolean;
}

function ActivitySheet({ item, onClose, onComplete, completing }: SheetProps) {
  const slug   = item.activity_type_slug ?? item.category ?? '';
  const pColor = priorityColor(item.priority);

  return (
    <Modal transparent visible animationType="slide" onRequestClose={onClose}>
      <Pressable style={sh.overlay} onPress={onClose} />
      <View style={sh.sheet}>
        <View style={sh.handle} />

        {/* ── Hero ── */}
        <View style={sh.hero}>
          <View style={[sh.heroIconBox, { borderColor: `${pColor}44` }]}>
            <CategoryIcon slug={slug} size={28} color={pColor} />
          </View>
          <View style={sh.heroText}>
            <Text style={sh.heroTitle} numberOfLines={2}>{item.title}</Text>
            <View style={sh.heroBadgeRow}>
              <Text style={[sh.heroPriority, { color: pColor }]}>
                {priorityLabel(item.priority)}
              </Text>
              {item.has_evidence && (
                <View style={sh.donePill}>
                  <CheckCircle size={11} color={ZEN.colors.recovery} />
                  <Text style={sh.donePillText}>DONE</Text>
                </View>
              )}
            </View>
          </View>
        </View>

        <View style={sh.divider} />

        {/* ── WHEN & HOW LONG ── */}
        <SectionEyebrow>When &amp; How Long</SectionEyebrow>
        <View style={sh.whenRow}>
          <View style={sh.whenChip}>
            <Clock size={13} color={ZEN.colors.textMuted} />
            <Text style={sh.whenText}>{item.duration_minutes} min</Text>
          </View>
          {item.target_start_time && (
            <View style={sh.whenChip}>
              <Sparkles size={13} color={ZEN.colors.textMuted} />
              <Text style={sh.whenText}>
                {timeOfDay(item.target_start_time)}  ·  {fmtTime(item.target_start_time)}
              </Text>
            </View>
          )}
        </View>

        {/* ── WHY THIS MATTERS ── */}
        {!!item.rationale && (
          <>
            <SectionEyebrow>Why This Matters</SectionEyebrow>
            <Text style={sh.rationale}>{item.rationale}</Text>
          </>
        )}

        {/* ── BEST TIME ── */}
        {!!item.target_start_time && (
          <>
            <SectionEyebrow>Best Time To Do This</SectionEyebrow>
            <View style={sh.bestRow}>
              <Leaf size={15} color={ZEN.colors.recovery} />
              <Text style={sh.bestText}>
                {timeOfDay(item.target_start_time)}
                {parseInt(item.target_start_time.slice(0, 2), 10) < 12
                  ? `  —  before ${fmtTime(item.target_start_time)}`
                  : `  —  around ${fmtTime(item.target_start_time)}`}
              </Text>
            </View>
          </>
        )}

        {/* ── CTA ── */}
        <View style={sh.cta}>
          {item.has_evidence ? (
            <View style={sh.completedRow}>
              <CheckCircle size={20} color={ZEN.colors.recovery} />
              <Text style={sh.completedText}>Completed</Text>
            </View>
          ) : (
            <TouchableOpacity
              style={[sh.completeBtn, completing && sh.completeBtnDim]}
              activeOpacity={0.85}
              onPress={() => onComplete(item.id)}
              disabled={completing}
            >
              <CheckCircle size={18} color="#000" />
              <Text style={sh.completeBtnText}>
                {completing ? 'Marking…' : 'Mark as Complete'}
              </Text>
            </TouchableOpacity>
          )}
        </View>
      </View>
    </Modal>
  );
}

// ─── Screen ───────────────────────────────────────────────────────────────────

export default function PlanScreen() {
  const nav = useNavigation<NativeStackNavigationProp<any>>();
  const { morningRecap, refresh: refreshDaily } = useDailyData();
  /** Matches backend strict recap: no yesterday summary → no plan / coach guidance. */
  const noStrictYesterday = morningRecap != null && morningRecap.summary == null;
  const morningRecapRef = useRef(morningRecap);
  useEffect(() => {
    morningRecapRef.current = morningRecap;
  }, [morningRecap]);

  const [plan, setPlan]               = useState<DailyPlan | null>(null);
  const [loading, setLoading]         = useState(true);
  const [refreshing, setRefreshing]   = useState(false);
  const [selected, setSelected]       = useState<PlanItem | null>(null);
  const [completing, setCompleting]   = useState(false);
  const [avoidItems, setAvoidItems]   = useState<
    Array<{ slug_or_label?: string; label?: string; reason?: string }>
  >([]);
  const [coachGuidance, setCoachGuidance] = useState<string[]>([]);
  const [strictBlocked, setStrictBlocked] = useState(false);

  /** After async plan/brief fetch, drop UI if recap says no strict yesterday (fixes race vs setPlan). */
  const applyStrictGate = useCallback((mrInput?: MorningRecapResponse | null) => {
    const mr = mrInput !== undefined ? mrInput : morningRecapRef.current;
    const blocked = mr == null || mr.summary == null;
    setStrictBlocked(blocked);
    if (blocked) {
      setPlan(null);
      setCoachGuidance([]);
      setAvoidItems([]);
      return true;
    }
    return false;
  }, []);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const [recapRes, planRes, briefRes] = await Promise.allSettled([
        getMorningRecap(),
        getTodayPlan(),
        getMorningBrief(),
      ]);
      const recapData = recapRes.status === 'fulfilled' ? (recapRes.value.data ?? null) : null;
      if (applyStrictGate(recapData)) return;

      let planData: DailyPlan | null = null;
      if (planRes.status === 'fulfilled') {
        const d = planRes.value.data;
        if (d?.items?.length) {
          planData = d;
          setPlan(d);
        } else {
          setPlan(null);
        }
      } else {
        setPlan(null);
      }

      // Prefer the plan's own forward-looking brief + single avoid_item.
      // Only fall back to the morning brief lines if /plan/today did not
      // return its own guidance payload yet.
      const planBrief = (planData?.brief ?? '').trim();
      const planAvoid = (planData?.avoid_items ?? []) as Array<{
        slug_or_label?: string;
        label?: string;
        reason?: string;
      }>;

      if (planBrief.length > 0) {
        setCoachGuidance([planBrief]);
        setAvoidItems(planAvoid);
      } else if (briefRes.status === 'fulfilled') {
        const brief = briefRes.value.data;
        const avoid = (brief?.avoid_items ?? []) as Array<{
          slug_or_label?: string;
          reason?: string;
        }>;
        if (!hasCoachBriefContent(brief)) {
          setCoachGuidance([]);
          setAvoidItems([]);
        } else {
          // Legacy fallback — ONE line from the brief, not three, so the plan
          // section does not visually echo the morning brief.
          const line = (brief?.brief_text ?? '').trim();
          setCoachGuidance(line ? [line] : []);
          setAvoidItems(planAvoid.length > 0 ? planAvoid : avoid);
        }
      } else {
        setCoachGuidance([]);
        setAvoidItems(planAvoid);
      }
    } catch {}
    finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [applyStrictGate]);

  useFocusEffect(useCallback(() => {
    void load();
  }, [load]));

  useEffect(() => {
    if (morningRecap != null && morningRecap.summary == null) {
      setPlan(null);
      setCoachGuidance([]);
      setAvoidItems([]);
      setStrictBlocked(true);
    }
    if (morningRecap?.summary != null) {
      setStrictBlocked(false);
    }
  }, [morningRecap]);

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await refreshDaily({ clearCoach: true });
    } catch {}
    await load(true);
  };

  const allItems = useMemo(() => {
    if (!plan?.items) return [];
    const mustDo      = plan.items.filter(i => i.priority === 'must_do');
    const recommended = plan.items.filter(i => i.priority === 'recommended');
    const optional    = plan.items.filter(i => i.priority === 'optional');
    return [...mustDo, ...recommended, ...optional];
  }, [plan]);

  const handleComplete = async (id: string) => {
    if (completing) return;
    setCompleting(true);
    // Optimistic update
    const patch = (items: PlanItem[]) =>
      items.map(i => i.id === id ? { ...i, has_evidence: true } : i);
    setPlan(prev => prev ? { ...prev, items: patch(prev.items) } : prev);
    setSelected(prev => prev?.id === id ? { ...prev, has_evidence: true } : prev);
    try {
      await markPlanItemComplete(id);
    } catch {
      // Revert on failure
      const revert = (items: PlanItem[]) =>
        items.map(i => i.id === id ? { ...i, has_evidence: false } : i);
      setPlan(prev => prev ? { ...prev, items: revert(prev.items) } : prev);
      setSelected(prev => prev?.id === id ? { ...prev, has_evidence: false } : prev);
    } finally {
      setCompleting(false);
    }
  };

  const completed = allItems.filter(i => i.has_evidence).length;
  const total     = allItems.length;
  const donts = avoidItems;

  return (
    <ZenScreen scrollable={false}>
      <TopHeader
        eyebrow="Today"
        title="My Plan"
        leftIcon={<ArrowLeft size={16} color="rgba(255,255,255,0.75)" />}
        onLeftPress={() => nav.getParent()?.navigate('TodayTab' as any)}
        rightIcon={<ArrowRight size={16} color="rgba(255,255,255,0.75)" />}
        onRightPress={() => nav.getParent()?.navigate('CoachTab' as any)}
      />

      {loading ? (
        <View style={s.center}>
          <ActivityIndicator color={ZEN.colors.recovery} size="large" />
        </View>
      ) : strictBlocked || noStrictYesterday || !plan || allItems.length === 0 ? (
        <EmptyState
          icon="today-outline"
          title="No plan yet"
          message={
            noStrictYesterday
              ? 'Plan and coach guidance need a valid yesterday summary from your band.'
              : 'Your plan generates based on today\'s stress and recovery data.'
          }
        />
      ) : (
        <ScrollView
          contentContainerStyle={s.scroll}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor={ZEN.colors.recovery}
            />
          }
        >
          {/* ── Plan activities ── */}
          <SurfaceCard style={s.listCard}>
            <View style={s.listHeader}>
              <SectionEyebrow>Today's Prescription</SectionEyebrow>
              <View style={s.countBadge}>
                <Text style={s.countText}>{completed}/{total}</Text>
              </View>
            </View>

            {/* Adherence progress bar */}
            {total > 0 && (
              <View style={s.adherenceWrap}>
                <View style={s.adherenceTrack}>
                  <View
                    style={[
                      s.adherenceFill,
                      { width: `${Math.round((plan.adherence_pct != null ? plan.adherence_pct : (completed / total * 100)))}%` as any },
                    ]}
                  />
                </View>
                <Text style={s.adherencePct}>
                  {Math.round(plan.adherence_pct != null ? plan.adherence_pct : (completed / total * 100))}% adherence
                </Text>
              </View>
            )}

            {plan.check_in_pending && (
              <TouchableOpacity
                style={s.checkInRow}
                activeOpacity={0.75}
                onPress={() => nav.navigate('HistoryTab' as any, { screen: 'CheckIn' } as any)}
              >
                <Text style={s.checkInText}>⚡ Quick check-in available</Text>
              </TouchableOpacity>
            )}

            <View style={s.divider} />

            {allItems.map((item, idx) => (
              <View key={item.id}>
                <ActivityRow item={item} onPress={() => setSelected(item)} />
                {idx < allItems.length - 1 && <View style={s.rowDivider} />}
              </View>
            ))}
          </SurfaceCard>

          <SurfaceCard style={s.coachCard}>
            <SectionEyebrow>Coach Guidance</SectionEyebrow>
            {coachGuidance.length > 0 ? (
              coachGuidance.map((line, idx) => (
                <Text key={`guide-${idx}`} style={s.coachLine}>{line}</Text>
              ))
            ) : (
              <Text style={s.coachEmpty}>
                No coach guidance until yesterday has valid band data.
              </Text>
            )}
            {donts.length > 0 ? (
              <>
                <Text style={s.coachDontsTitle}>Don&apos;t</Text>
                {donts.slice(0, 1).map((item, idx) => {
                  const label = item.slug_or_label ?? item.label ?? 'Avoid major trigger';
                  const reason = (item.reason ?? '').trim();
                  return (
                    <Text key={`coach-dont-${idx}`} style={s.coachDontItem}>
                      {'\u2022'} {label}
                      {reason ? ` — ${reason}` : ''}
                    </Text>
                  );
                })}
              </>
            ) : null}
          </SurfaceCard>
        </ScrollView>
      )}

      {/* ── Activity detail sheet ── */}
      {selected && (
        <ActivitySheet
          item={selected}
          onClose={() => setSelected(null)}
          onComplete={handleComplete}
          completing={completing}
        />
      )}
    </ZenScreen>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

/** Screen */
const s = StyleSheet.create({
  center:    { flex: 1, alignItems: 'center', justifyContent: 'center' },
  scroll:    { paddingBottom: 120, gap: 12 },

  listCard:  { gap: 0, padding: 20 },
  listHeader:{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 },

  countBadge: {
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: 20,
    backgroundColor: 'rgba(78,205,196,0.12)', borderWidth: 1,
    borderColor: 'rgba(78,205,196,0.25)',
  },
  countText: { fontSize: 12, fontWeight: '600', color: ZEN.colors.recovery, letterSpacing: 0.5 },

  divider:    { height: 1, backgroundColor: 'rgba(255,255,255,0.06)', marginBottom: 8 },
  rowDivider: { height: 1, backgroundColor: 'rgba(255,255,255,0.05)', marginHorizontal: 0 },

  adherenceWrap: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 12 },
  adherenceTrack: {
    flex: 1, height: 4, borderRadius: 2,
    backgroundColor: 'rgba(255,255,255,0.08)', overflow: 'hidden',
  },
  adherenceFill: {
    height: '100%', borderRadius: 2,
    backgroundColor: ZEN.colors.recovery,
  },
  adherencePct: { fontSize: 11, color: ZEN.colors.textMuted, minWidth: 70, textAlign: 'right' },
  coachCard: { gap: 8, padding: 16 },
  coachLine: { fontSize: 13, lineHeight: 19, color: ZEN.colors.textNear },
  coachEmpty: { fontSize: 13, lineHeight: 19, color: ZEN.colors.textMuted, fontStyle: 'italic' },
  coachDontsTitle: {
    marginTop: 4,
    fontSize: 12,
    color: ZEN.colors.stress,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.7,
  },
  coachDontItem: { fontSize: 12, lineHeight: 18, color: ZEN.colors.textMuted },

  checkInRow: {
    borderRadius: 12, borderWidth: 1,
    borderColor: 'rgba(200,180,255,0.22)', backgroundColor: 'rgba(140,100,255,0.08)',
    padding: 12, marginBottom: 12,
  },
  checkInText: { fontSize: 14, color: ZEN.colors.textLabel },
});

/** Activity Row */
const row = StyleSheet.create({
  wrap: {
    flexDirection: 'row', alignItems: 'center',
    paddingVertical: 14, gap: 14,
  },
  iconBox: {
    width: 40, height: 40, borderRadius: 12,
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderWidth: 1,
    alignItems: 'center', justifyContent: 'center',
  },
  mid:       { flex: 1, gap: 3 },
  title:     { fontSize: 15, fontWeight: '500', color: 'rgba(255,255,255,0.92)', letterSpacing: -0.2 },
  titleDone: { color: 'rgba(255,255,255,0.35)', textDecorationLine: 'line-through' },
  sub:       { fontSize: 11, fontWeight: '600', letterSpacing: 0.8, textTransform: 'uppercase' },
  status:    { paddingLeft: 4 },
});

/** Activity Sheet */
const sh = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.45)' },
  sheet: {
    backgroundColor: ZEN.colors.bgMid,
    borderTopLeftRadius: 28, borderTopRightRadius: 28,
    borderTopWidth: 1, borderColor: ZEN.colors.border,
    padding: 24, paddingBottom: 40,
  },
  handle: {
    alignSelf: 'center', marginBottom: 20,
    width: 48, height: 5, borderRadius: 3,
    backgroundColor: 'rgba(255,255,255,0.15)',
  },

  // Hero
  hero:       { flexDirection: 'row', alignItems: 'flex-start', gap: 16, marginBottom: 20 },
  heroIconBox: {
    width: 56, height: 56, borderRadius: 16,
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderWidth: 1, alignItems: 'center', justifyContent: 'center',
  },
  heroText:    { flex: 1, gap: 6, paddingTop: 2 },
  heroTitle:   { fontSize: 20, fontWeight: '600', letterSpacing: -0.5, color: ZEN.colors.white },
  heroBadgeRow:{ flexDirection: 'row', alignItems: 'center', gap: 8 },
  heroPriority:{ fontSize: 11, fontWeight: '700', letterSpacing: 1.2, textTransform: 'uppercase' },
  donePill:    {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: 12,
    backgroundColor: 'rgba(78,205,196,0.12)',
    borderWidth: 1, borderColor: 'rgba(78,205,196,0.25)',
  },
  donePillText:{ fontSize: 10, fontWeight: '700', letterSpacing: 1, color: ZEN.colors.recovery },

  divider: { height: 1, backgroundColor: 'rgba(255,255,255,0.07)', marginBottom: 16 },

  // When
  whenRow:  { flexDirection: 'row', gap: 10, flexWrap: 'wrap', marginTop: 8, marginBottom: 16 },
  whenChip: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 12,
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderWidth: 1, borderColor: 'rgba(255,255,255,0.08)',
  },
  whenText: { fontSize: 14, color: 'rgba(255,255,255,0.75)' },

  // Why
  rationale: {
    fontSize: 15, lineHeight: 23, color: 'rgba(255,255,255,0.72)',
    marginTop: 8, marginBottom: 16,
  },

  // Best time
  bestRow:  { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 8, marginBottom: 20 },
  bestText: { fontSize: 14, color: 'rgba(255,255,255,0.65)' },

  // CTA
  cta: { marginTop: 4 },
  completeBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10,
    height: 52, borderRadius: 16, backgroundColor: ZEN.colors.recovery,
  },
  completeBtnDim: { opacity: 0.55 },
  completeBtnText: { fontSize: 16, fontWeight: '700', color: '#000', letterSpacing: 0.3 },

  completedRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, paddingVertical: 16 },
  completedText: { fontSize: 16, fontWeight: '600', color: ZEN.colors.recovery },
});
