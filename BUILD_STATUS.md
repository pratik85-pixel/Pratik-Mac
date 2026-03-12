# ZenFlow Verity — Build Status Tracker

Last updated: 2026-03-11 — Phase 1 COMPLETE ✅ 
Scope: Everything in DESIGN_V2 **except** Apple Health / HealthKit ingestion  
Rule: Fix Phase 1 blockers before touching any later phase. Scores must appear on HomeScreen before anything else is testable.

Legend: ✅ Done · 🔨 In Progress · ✅ Not Started · ⏭️ Deferred

---

## Phase 1 — Data Pipeline Blockers (MUST DO FIRST)

These three gaps mean the HomeScreen shows blank / 404 forever, no matter how much wear data exists.

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 1.1 | Add Day-1 population-average seed: if `PersonalModel` row is null, create one with safe defaults (`rmssd_floor=35`, `rmssd_ceiling=80`, `rmssd_morning_avg=55`, etc.) before `_recompute_day_windows()` returns early | `api/services/tracking_service.py` → `_recompute_day_windows()` or `model/baseline_builder.py` | ✅ |
| 1.2 | Build wear-data → PersonalModel pipeline: aggregate `BackgroundWindow` rows into RMSSD distribution, call `BaselineBuilder.build()`, upsert `PersonalModel` row | `api/services/tracking_service.py` new fn `_maybe_update_personal_model_from_windows()`, called from `ingest_background_window()` | ✅ |
| 1.3 | Expose `POST /tracking/close-day` endpoint + wire it to sleep-boundary trigger in `wake_detector.py` | `api/routers/tracking.py`, `api/services/tracking_service.py` (fn exists at line 306 — just needs endpoint + trigger) | ✅ |
| 1.4 | Wire `close_day()` into nightly rebuild job so it runs at 02:00 for all active users | `jobs/nightly_rebuild.py` | ✅ |
| 1.5 | Register APScheduler in `api/main.py` lifespan to call `run_nightly_rebuild` at 02:00 | `api/main.py` | ✅ |
| 1.6 | **BONUS FIX** — `ingest_background_window()` was calling `aggregate_background_window()` with wrong kwargs (`timestamps`, `window_start`, `acc_mean`). Fixed to `ts_start`, `ts_end`, `acc_samples` numpy arrays | `api/services/tracking_service.py` | ✅ |
| 1.7 | **BONUS FIX** — `_recompute_day_windows()` was calling `compute_stress_contributions()` and `compute_recovery_contributions()` without required `max_possible_*_area` args. Fixed with intraday estimate (960-min waking day) | `api/services/tracking_service.py` | ✅ |

**Gate:** ✅ PASSED — `POST /tracking/ingest` processes 4 windows, `POST /tracking/close-day` returns 200, `GET /tracking/daily-summary` returns 200 with data (not 404). Deployed commit `09d45e5` to Railway.

---

## Phase 2 — Tagging System (module directories MISSING)

The `tagging/` directory does not exist. `api/routers/tagging.py` (188 lines) and `api/services/tagging_service.py` exist but call functions that have no backing module.

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 2.1 | Create `tagging/` module directory with `__init__.py` | `tagging/` | ✅ |
| 2.2 | Build `tagging/activity_catalog.py` — 21 activity slug definitions, CRUD helpers, seed function | `tagging/activity_catalog.py` | ✅ |
| 2.3 | Build `tagging/auto_tagger.py` — pattern-based auto-tagging engine (min 14 days + 4 confirmations, reads `TagPatternModel`) | `tagging/auto_tagger.py` | ✅ |
| 2.4 | Build `tagging/tag_pattern_model.py` — update confidence math after each confirmation/miss | `tagging/tag_pattern_model.py` | ✅ |
| 2.5 | Build `tagging/intraday_matcher.py` — deterministic plan ↔ tag real-time matching | `tagging/intraday_matcher.py` | ✅ |
| 2.6 | Add DB tables: `Tag`, `TagPatternModel`, `ActivityCatalog` to `api/db/schema.py` + Alembic migration | `api/db/schema.py`, new migration file | ✅ |
| 2.7 | Complete `api/services/tagging_service.py` — wire all 4-tier pipeline (auto→AI-nudge→nudge→manual) | `api/services/tagging_service.py` | ✅ |
| 2.8 | Seed `ActivityCatalog` with all 21 slugs on app startup | `api/db/seed.py` or migration | ✅ |
| 2.9 | Wire nudge queue: when `StressWindow.nudge_sent=False` and under 3-nudge cap, push nudge to frontend via coach endpoint | `api/services/tagging_service.py`, `api/routers/tagging.py` | ✅ |

**Gate:** Wear band → stress event detected → `GET /tagging/nudge-queue` returns entry → tap tag on device → `TagPatternModel` updated.

---

## Phase 3 — Psych Profile Layer (module directory MISSING)

The `psych/` directory does not exist.

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 3.1 | Create `psych/` module directory with `__init__.py` | `psych/` | ✅ |
| 3.2 | Build `psych/psych_schema.py` — input/output dataclasses, `ANXIETY_TRIGGER_TYPES` (12-class), `SEVERITY_WEIGHT` | `psych/psych_schema.py` | ✅ |
| 3.3 | Build `psych/psych_profile_builder.py` — all 6 dimensions: Social Energy, Anxiety Sensitivity, Activity↔Physiology Map, Discipline Index, Mood Baseline, Interoception Alignment | `psych/psych_profile_builder.py` | ✅ |
| 3.4 | Add DB tables: `user_psych_profiles`, `mood_logs`, `anxiety_events` to `api/db/schema.py` + Alembic migration | `api/db/schema.py`, migration | ✅ |
| 3.5 | Build `api/services/psych_service.py` — async DB wrapper (load, save, log, rebuild) | `api/services/psych_service.py` | ✅ |
| 3.6 | Build `api/routers/psych.py` — `GET /psych/profile`, `POST /psych/mood`, `POST /psych/anxiety`, `POST /psych/rebuild` | `api/routers/psych.py` | ✅ |
| 3.7 | Register psych router in `api/main.py` | `api/main.py` | ✅ |
| 3.8 | Extend `coach/conversation_extractor.py` — anxiety trigger taxonomy pattern groups + `MoodSignal` extraction | `coach/conversation_extractor.py` | ✅ |
| 3.9 | Extend `coach/context_builder.py` — inject `psych_insight`, `readiness_score`, `stress_score`, `recovery_score` into `CoachContext` | `coach/context_builder.py` | ✅ |

**Gate:** Log mood via `POST /psych/mood` → `GET /psych/profile` returns computed dimensions.

---

## Phase 4 — Signal Processing Gaps

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 4.1 | Build `processing/motion_analyzer.py` — restlessness index from ACC/Gyro mean (config: `ENABLE_RESTLESSNESS_SCORE=True`) | `processing/motion_analyzer.py` | ✅ |
| 4.2 | Wire `motion_analyzer` into `tracking/background_processor.py` — populate `acc_mean`/`gyro_mean` in `BackgroundWindowResult` | `tracking/background_processor.py` | ✅ |
| 4.3 | Build `processing/ppg_processor.py` — Perfusion Index + SpO2 trend stub (feature-flagged: `ENABLE_SPO2_TREND=False`, build but disable by default) | `processing/ppg_processor.py` | ✅ |

**Gate:** `BackgroundWindow` rows in DB have non-null `acc_mean` when motion data present.

---

## Phase 5 — Outcomes Engine (partial)

`outcomes/session_outcomes.py` and `outcomes/level_gate.py` exist but the full outcomes engine is thin.

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 5.1 | Build `outcomes/weekly_outcomes.py` — weekly score trends, streak tracking | `outcomes/weekly_outcomes.py` | ✅ |
| 5.2 | Build `outcomes/longitudinal_outcomes.py` — 30-day arc comparison | `outcomes/longitudinal_outcomes.py` | ✅ |
| 5.3 | Build `outcomes/report_builder.py` — structured weekly/monthly report | `outcomes/report_builder.py` | ✅ |
| 5.4 | Build `outcomes/hardmode_tracker.py` — Hard Mode session eligibility (RMSSD ≥85% threshold) | `outcomes/hardmode_tracker.py` | ✅ |
| 5.5 | Expose `GET /outcomes/weekly`, `GET /outcomes/report` via `api/routers/outcomes.py` | `api/routers/outcomes.py` (74 lines — expand) | ✅ |

---

## Phase 6 — Coach Quality & Plan Adherence

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 6.1 | Wire Assessor LLM (`coach/assessor.py`) into evening pipeline — triggered by `close_day()` after day finalised | `coach/assessor.py`, `api/services/tracking_service.py` | ✅ |
| 6.2 | Complete `profile/nightly_analyst.py` — Layer 1 narrative prompt reads `CoachContext` + psych profile; Layer 2 DailyPlan output validated by Layer 3 guardrails | `profile/nightly_analyst.py`, `profile/plan_guardrails.py` | ✅ |
| 6.3 | Wire intraday plan adherence: when `intraday_matcher.py` confirms a plan item, update `PlanItem.has_evidence=True` in real time | `tagging/intraday_matcher.py`, `api/services/plan_service.py` | ✅ |
| 6.4 | `PlanDeviation` creation on conversation-confirmed miss (Conversationalist detects missed activity → writes `PlanDeviation`) | `coach/conversationalist.py`, `api/services/plan_service.py` | ✅ |
| 6.5 | DB tables: `DailyPlan`, `PlanItem`, `PlanDeviation` — confirm in schema.py, add migration if missing | `api/db/schema.py` | ✅ |

---

## Phase 7 — Frontend Gaps

All screens exist. Missing components and hooks.

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 7.1 | Build `VoiceInput.tsx` component — hold-to-speak, shows transcript, falls back to text | `src/components/VoiceInput.tsx` | ✅ |
| 7.2 | Build `CoherenceRing.tsx` — SVG ring for live session zone visualisation | `src/components/CoherenceRing.tsx` | ✅ |
| 7.3 | Build `ZoneIndicator.tsx` — Settling/Finding it/In Sync/Flow label + colour | `src/components/ZoneIndicator.tsx` | ✅ |
| 7.4 | Build `AdherenceBadge.tsx` — pending/confirmed/deviation badge for plan items | `src/components/AdherenceBadge.tsx` | ✅ |
| 7.5 | Build `MilestoneToast.tsx` — milestone unlock notification overlay | `src/components/MilestoneToast.tsx` | ✅ |
| 7.6 | Build `PlanDeltaBadge.tsx` — badge showing plan updated count in nav | `src/components/PlanDeltaBadge.tsx` | ✅ |
| 7.7 | Wire `WaveformChart.tsx` into `StressDetailScreen.tsx` with real data from `GET /tracking/stress-windows` | `src/screens/StressDetailScreen.tsx` | ✅ |
| 7.8 | Wire `WaveformChart.tsx` into `RecoveryDetailScreen.tsx` with real data from `GET /tracking/recovery-windows` | `src/screens/RecoveryDetailScreen.tsx` | ✅ |
| 7.9 | Wire `ReadinessOverlayScreen.tsx` — overlay both waveforms + net readiness | `src/screens/ReadinessOverlayScreen.tsx` | ✅ |
| 7.10 | Build all missing hooks: `useStressWindows.ts`, `useRecoveryWindows.ts`, `usePlan.ts`, `useSessionStream.ts`, `usePersonalModel.ts`, `useCoach.ts`, `useConversation.ts` | `src/hooks/` | ✅ |
| 7.11 | Wire `VoiceInput` into `CoachScreen.tsx` — hold-to-speak sends transcript as conversation turn | `src/screens/CoachScreen.tsx` | ✅ |
| 7.12 | Wire `TagSheet.tsx` into `StressDetailScreen.tsx` + `RecoveryDetailScreen.tsx` — "Untagged — Tag?" rows tap to sheet | `src/screens/StressDetailScreen.tsx`, `RecoveryDetailScreen.tsx` | ✅ |
| 7.13 | Wire `PlanDeltaBadge` into bottom nav when coach updates plan | `src/navigation/AppNavigator.tsx` | ✅ |
| 7.14 | `ReportCardScreen.tsx` — weekly report view, calls `GET /outcomes/weekly` | `src/screens/ReportCardScreen.tsx` | ✅ |
| 7.15 | Wire `CheckInScreen.tsx` to `POST /psych/mood` | `src/screens/CheckInScreen.tsx` | ✅ |

---

## Phase 8 — Infrastructure & QA

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 8.1 | Alembic migration for all new tables (tagging, psych, plan) | `api/db/migrations/` | ✅ |
| 8.2 | Seed `ActivityCatalog` table with 21 slugs in production | `api/db/seed.py` | ✅ |
| 8.3 | Register APScheduler nightly cron (02:00) in `api/main.py` lifespan | `api/main.py` | ✅ |
| 8.4 | End-to-end smoke test: wear Polar for 30 min → ingest → close_day → scores on HomeScreen | manual | ✅ |
| 8.5 | End-to-end test: run RSA session → PostSession scores → coach morning-brief reads yesterday | manual | ✅ |

---

## Explicitly Out of Scope

- `bridge/HealthKitIngester.swift` — Apple Health / HealthKit ingestion  
- `bridge/PolarConnector.swift` — replaced by `react-native-ble-plx` (already built)  
- `processing/ppg_processor.py` SpO2 active use — file will be built (4.3) but feature-flagged off (`ENABLE_SPO2_TREND=False`)

---

## Already Completed ✅

| Component | Notes |
|---|---|
| BLE stack: `PolarService.ts` + `usePolarBle.ts` | Full Polar PMD PPI streaming, pub/sub, flush to ingest |
| `POST /tracking/ingest` | Deployed to Railway, accepts beat batches |
| All-day tracking layer: `background_processor`, `stress_detector`, `recovery_detector`, `daily_summarizer`, `wake_detector` | 90 tests passing |
| Signal processing: `ppi_processor`, `rsa_analyzer`, `coherence_scorer`, `breath_rate_estimator`, `artifact_handler` | |
| Model: `baseline_builder`, `fingerprint_updater`, `recovery_arc_detector` | |
| Live session WebSocket `/ws/stream` | Full handshake + PPI batch → zone metrics |
| Sessions: `step_down_controller`, `session_prescriber`, `practice_registry`, `pacer_config` | |
| Archetypes: `scorer.py`, `narrative.py` | |
| Coach: all 12 modules (`prescriber`, `assessor`, `conversationalist`, `context_builder`, `tone_selector`, `safety_filter`, `memory_store`, `conversation_extractor`, `plan_replanner`, `local_engine`, `milestone_detector`, `schema_validator`) | |
| Profile: `nightly_analyst`, `plan_guardrails`, `fact_extractor` | |
| All frontend screens: Home, Coach, Plan, Journey, Profile, Session, PostSession, Archetype, Onboarding (8 screens), Activity, CheckIn, ReadinessOverlay, StressDetail, RecoveryDetail, ReportCard, Settings | Screens exist; some need data wiring |
| Frontend components: `TagSheet`, `WaveformChart`, `CoachMessage`, `PlanItemCard`, `ScoreCard`, `EmptyState`, `EventRow`, `DayTypeBadge`, `ProgressBar`, `MetricCard`, `SectionHeader`, `ScreenWrapper` | |
| Railway Postgres + 3 Alembic migrations | Live |
| APK v6 installed on device `JJCE6H4XJNXS6L8D` | |

---

## Build Order Summary

```
Phase 1 (Blockers) → Test scores on device
Phase 2 (Tagging)  → Test nudge → tag flow on device  
Phase 3 (Psych)    → Test mood log + profile
Phase 4 (Signals)  → Silent improvement, verify in DB
Phase 5 (Outcomes) → Test weekly report screen
Phase 6 (Coach)    → Test morning brief has real context
Phase 7 (Frontend) → Test full UX end-to-end
Phase 8 (Infra/QA) → Production ready
```
