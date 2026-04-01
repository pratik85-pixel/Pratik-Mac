// Shared TypeScript types for the ZenFlow Verity app

// ── Auth ──────────────────────────────────────────────────────────────────────
export interface StoredUser {
  userId: string;
  name: string;
  apiBase: string;
}

// ── Daily Summary ─────────────────────────────────────────────────────────────
export type ScoreConfidenceLevel = 'high' | 'medium' | 'low';
export type SummarySource = 'live_compute' | 'persisted_row';

export interface DailySummaryResponse {
  summary_date: string;
  stress_load_score: number | null;
  recovery_score: number | null;
  waking_recovery_score?: number | null;
  sleep_recovery_score?: number | null;
  sleep_recovery_night_date?: string | null;
  sleep_recovery_subtext?: string | null;
  net_balance?: number | null;
  readiness_score: number | null;
  day_type: 'green' | 'yellow' | 'red' | 'GREEN' | 'YELLOW' | 'RED' | null;
  calibration_days: number;
  is_estimated: boolean;
  is_partial_data: boolean;
  wake_ts: string | null;
  sleep_ts: string | null;
  waking_minutes: number | null;
  synthesis_sentence: string | null;
  untagged_stress_count?: number;
  untagged_recovery_count?: number;
  // Chart denominator fields
  ns_capacity_used?: number | null;
  rmssd_morning_avg?: number | null;
  rmssd_ceiling?: number | null;
  /** Phase 1 — API contract id for locked metrics (no formula change). */
  metrics_contract_id?: string;
  score_confidence?: ScoreConfidenceLevel;
  score_confidence_reasons?: string[];
  summary_source?: SummarySource;
}

/** GET /tracking/stress-state — live zone + trend (readiness UX) */
export interface CohortInsight {
  enabled: boolean;
  band: 'below_typical' | 'typical' | 'above_typical' | null;
  disclaimer: string;
}

export interface StressStateResponse {
  stress_now_zone: 'calm' | 'steady' | 'activated' | 'depleted' | string | null;
  stress_now_index: number | null;
  stress_now_percent: number | null;
  trend: 'easing' | 'stable' | 'building' | 'unclear' | string;
  confidence: 'high' | 'medium' | 'low' | string;
  reference_type: string;
  as_of: string | null;
  rmssd_smoothed_ms: number | null;
  zone_cut_index_low: number | null;
  zone_cut_index_mid: number | null;
  zone_cut_index_high: number | null;
  morning_reference_ms: number | null;
  time_of_day_reference_ms: number | null;
  cohort: CohortInsight | null;
}

/** GET /tracking/morning-recap */
export interface MorningRecapSummaryBlock {
  stress_load_score: number | null;
  recovery_score?: number | null;
  waking_recovery_score: number | null;
  sleep_recovery_score?: number | null;
  sleep_recovery_night_date?: string | null;
  sleep_recovery_subtext?: string | null;
  net_balance: number | null;
  day_type: string | null;
  is_estimated: boolean;
  is_partial_data: boolean;
  sleep_recovery_area: number | null;
  closing_balance: number | null;
  metrics_contract_id?: string;
  score_confidence?: ScoreConfidenceLevel;
  score_confidence_reasons?: string[];
  summary_source?: SummarySource;
}

export interface MorningRecapResponse {
  for_date: string;
  should_show: boolean;
  acknowledged_for_date: boolean;
  summary: MorningRecapSummaryBlock | null;
}

/** GET /coach/morning-brief */
export interface MorningBriefResponse {
  day_state: string | null;
  day_confidence: string | null;
  brief_text: string | null;
  evidence: string | null;
  one_action: string | null;
  generated_for: string | null;
  is_stale: boolean;
  plan: Array<Record<string, any>>;
  avoid_items: Array<Record<string, any>>;
}

/** GET /plan/home-status */
export interface PlanHomeStatus {
  has_plan: boolean;
  plan_date: string | null;
  anchor_intention: string | null;
  anchor_slug: string | null;
  items_total: number;
  items_completed: number;
  adherence_pct: number | null;
  on_track: boolean | null;
  day_type: string | null;
}

// ── Tracking ─────────────────────────────────────────────────────────────────
export interface WaveformPoint {
  window_start: string;
  window_end: string;
  rmssd_ms: number | null;
  hr_bpm: number | null;
  context: string;
  is_valid: boolean;
}

export interface StressWindow {
  id: string;
  started_at: string;
  ended_at: string;
  duration_minutes: number;
  rmssd_min_ms: number | null;
  suppression_pct: number | null;
  stress_contribution_pct: number | null;
  tag: string | null;
  tag_candidate: string | null;
  tag_source: string | null;
  nudge_sent: boolean;
  nudge_responded: boolean;
}

export interface RecoveryWindow {
  id: string;
  started_at: string;
  ended_at: string;
  duration_minutes: number;
  rmssd_avg_ms: number | null;
  recovery_contribution_pct: number | null;
  tag: string | null;
  tag_source: string | null;
}

// ── Plan ─────────────────────────────────────────────────────────────────────
export interface PlanItem {
  id: string;
  category: string;
  activity_type_slug: string;
  title: string;
  target_start_time: string | null;
  target_end_time: string | null;
  duration_minutes: number;
  priority: 'must_do' | 'recommended' | 'optional';
  rationale: string;
  has_evidence: boolean;
  adherence_score: number | null;
  confirmed?: boolean;
}

export interface DailyPlan {
  id: string;
  plan_date: string;
  items: PlanItem[];
  check_in_pending?: boolean;
  adherence_pct?: number | null;
  plan_updated_count?: number;
}

// ── Coach ─────────────────────────────────────────────────────────────────────
export interface CoachReply {
  conversation_id: string;
  turn_index: number;
  session_open: boolean;
  safety_fired: boolean;
  reply: string | null;
  message: string;           // alias used by UI (reply ?? follow_up)
  follow_up: string | null;
  handoff_message: string;
  is_synthesis?: boolean;
}

export interface ConversationTurn {
  role: 'user' | 'coach';
  content: string;
  ts: string | null;
  plan_adjusted: boolean;
  // history endpoint variants
  user_message?: string;
  assistant_message?: string;
}

// ── User / Profile ────────────────────────────────────────────────────────────
export interface UserProfile {
  user_id: string;
  name: string;
  training_level: string | null;
  archetype_primary: string | null;
  archetype_secondary: string | null;
  archetype_confidence: number | null;
  archetype_updated_at: string | null;
  member_since: string | null;
}

export interface ArchetypeProfile {
  stage: number;
  total_score: number;
  trajectory: string;
  primary_pattern: string;
  amplifier_pattern: string | null;
  dimension_scores: Record<string, number>;
  stage_focus: string[];
  weeks_in_stage: number;
}

export interface Fingerprint {
  rmssd_floor_ms: number | null;
  rmssd_ceiling_ms: number | null;
  rmssd_morning_avg_ms: number | null;
  coherence_floor: number | null;
  coherence_trainability: string | null;
  recovery_arc_mean_hours: number | null;
  stress_peak_hour: number | null;
  overall_confidence: number | null;
  best_window: string | null;         // "HH:MM" — already returned by /user/fingerprint
  typical_wake_time: string | null;   // "HH:MM" — populated by B1 backend work
  typical_sleep_time: string | null;  // "HH:MM" — populated by B1 backend work
  // UI-friendly nested view
  stress_profile?: {
    peak_hours?: number[];
    top_trigger?: string | null;
  };
}

// ── Unified Profile ───────────────────────────────────────────────────────────
export interface UserFact {
  fact_id: string;
  category: string;
  fact_key: string;
  fact_text: string;
  confidence: number;
}

export interface UnifiedProfile {
  user_id: string;
  archetype_primary: string | null;
  archetype_secondary: string | null;
  training_level: number;
  days_active: number;
  data_confidence: number;
  coach_narrative?: string | null;
  physio?: Record<string, any>;
  psych?: Record<string, any>;
  behaviour?: {
    top_calming_activities: string[];
    top_stress_activities: string[];
    movement_enjoyed: string[];
    decompress_via: string[];
  };
  engagement?: {
    engagement_tier: string;
    sessions_last7: number;
    sessions_last30: number;
    morning_read_streak: number;
  };
  coach?: Record<string, any>;
  suggested_plan?: any[];
  // legacy / convenience fields kept for components
  name?: string;
  completeness_score?: number;
  days_tracked?: number;
  archetype?: {
    primary_pattern?: string;
    stage?: number;
    trajectory?: string;
    dimension_scores?: Record<string, number>;
  };
  facts?: (UserFact | string)[];
  user_facts?: UserFact[];
}

// ── Outcomes ──────────────────────────────────────────────────────────────────
export interface ReportCard {
  user_id: string;
  week_start: string;
  overall_grade?: string;
  overall_insight?: string;
  avg_stress_load?: number | null;
  avg_recovery_score?: number | null;
  avg_readiness_score?: number | null;
  active_days?: number;
  domain_grades?: Record<string, string>;
  resilience_score: number | null;
  recovery_avg: number | null;
  session_count: number;
  top_pattern: string | null;
  narrative: string | null;
}

// ── Tagging ───────────────────────────────────────────────────────────────────
export interface TagHistoryItem {
  id: string;
  window_id: string;
  window_type: 'stress' | 'recovery';
  started_at: string;
  tag: string;
  tag_source: string;
  suppression_pct?: number | null;
}

export interface NudgeWindow {
  window_id: string;
  window_type: 'stress' | 'recovery';
  started_at: string;
  duration_minutes: number;
  tag_candidate: string | null;
}

// ── Notifications ─────────────────────────────────────────────────────────────
export interface NotificationActionDef {
  id: string;
  action_type: string;
  label: string;
}

export interface NotificationFeedItem {
  id: string;
  category: 'event_trigger' | 'nudge' | 'check_in' | string;
  priority: 'critical' | 'high' | 'normal' | string;
  title: string;
  body: string | null;
  requires_action: boolean;
  status: 'unread' | 'acted' | 'dismissed' | 'expired' | string;
  created_at: string | null;
  expires_at: string | null;
  dedupe_key: string | null;
  deeplink: string | null;
  payload: Record<string, any>;
  actions: NotificationActionDef[];
}

export interface NotificationFeedResponse {
  items: NotificationFeedItem[];
  next_cursor: string | null;
  server_time: string;
}

// ── Onboarding ────────────────────────────────────────────────────────────────
export interface OnboardingAnswers {
  mainGoal: string;
  typicalDay: string;
  movementEnjoyed: string[];
  alcohol: string;
  caffeine: string;
  sleepSchedule: string;
  decompressStyle: string[];
  name: string;
}
