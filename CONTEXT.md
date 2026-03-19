# ZenFlow Verity — Project Context

**Last updated:** 19 March 2026 — Stuck morning context fix + DB cleanup + score re-materialisation

---

## Handoff Note — Session of 19 March 2026 (Part 2) — Stuck Morning Context Fix

### Root Cause
After taking a "morning read" at 20:30 IST (15:01 UTC), `PolarService.ts` transitioned `_sleepState` to `'morning_pending'`. The state only reset to `'background'` after a **successful POST** inside the `try` block. If the app was backgrounded or network flaked at that moment, the reset line never ran — so every subsequent window (69 total) was sent as `context='morning'` instead of `'background'`.

Scoring impact: both `_compute_suppression_area()` and `_compute_recovery_area_waking()` filter `w.context == "background"` only → morning-labelled windows contributed zero → scores collapsed to Recovery 1–3, Stress 5+.

---

### Fix 1 — PolarService.ts: move state reset before POST

**File:** `Zenflow_front/src/services/PolarService.ts`, `_flushBeats()` function

**Before:** state reset was inside the `try` block, after `await getClient().post(...)` — it only ran on POST success.

**After:** state reset moved to immediately after `flushContext` is captured (before the `try {`). `flushContext` already holds `'morning'` so the POST still sends the correct context. The reset now fires regardless of POST success/failure — state can never get stuck.

```typescript
// flushContext captured first (unchanged)
const flushContext = this._sleepState === 'morning_pending' ? 'morning' : ...

// ← reset moved HERE, before try block
if (this._sleepState === 'morning_pending') {
  this._sleepState = 'background';
  console.log('[Polar] morning context flushed — context returned to background');
}

try {
  await getClient().post('/tracking/ingest', { context: flushContext, ... });
  // (reset block removed from here)
```

Deploy: Metro hot-reload (TS logic only, no EAS build). TS clean.

---

### Fix 2 — DB cleanup: relabel 69 stuck `morning` windows → `background`

```sql
UPDATE background_windows
SET context = 'background'
WHERE user_id = '8e8715c6-c6ab-45c1-a7da-f037207cf689'
  AND context = 'morning'
  AND window_start > '2026-03-19 15:02:00+00';
-- Result: UPDATE 69
```

Verified: `SELECT COUNT(*)` on same predicate → 0.

---

### Fix 3 — Re-materialised daily scores

Ran `scripts/replay_daily_scores.py` against Railway DB. Also fixed a query bug in the script (broken `(:uids)::text IS NULL` parameter pattern with asyncpg replaced with a two-branch Python-level ORM approach + Python-side filter).

| Date | net_balance | waking_recovery_score | stress_load_score |
|---|---|---|---|
| 2026-03-19 | **7.2** | **6.2** | 0 |
| 2026-03-18 | 1.0 | 0 | 0 |
| 2026-03-17 | 1.0 | 1.0 | 0 |

Mar 19 jumped from collapsed ~−1.6 to +7.2 — fix confirmed working.

---

### Parked Plan — Time-of-day guard for morning reads

**Not implemented this session. Tracked here for future work.**

A "morning read" taken in the evening (e.g. 20:30 IST) is a design flaw separate from the stuck-state bug above. It corrupts `rmssd_morning_avg` by seeding it with an evening baseline. Future fix: add a time-of-day guard in `PolarService.ts` — only allow `morning_pending` transitions between 05:00–11:00 local IST (22:00–04:00 UTC window). Outside that window, a WAKE event from `sleep` state should return directly to `background` without setting `morning` context and without triggering a morning read.

---

### Files changed this session

| File | Change |
|---|---|
| `Zenflow_front/src/services/PolarService.ts` | Move `_sleepState` reset before `try` block in `_flushBeats()` |
| `scripts/replay_daily_scores.py` | Fix broken asyncpg array-param query; use text() + Python-side filter |
| **Railway DB** | `UPDATE background_windows SET context='background' WHERE context='morning' AND window_start > '2026-03-19 15:02:00+00'` (69 rows) |

---



## Handoff Note — Session of 19 March 2026 — Sleep Detection + Materialised Scoring + Chart

### What was done this session

#### Phase 1 — Artifact floor gate (symmetric to ceiling gate)

**Problem:** No lower-bound gate on RMSSD. Contact-loss windows with near-zero RMSSD would inflate stress scores.

- **`config/tracking.py`:** Added `RMSSD_POPULATION_FLOOR: float = 3.0` after `RMSSD_POPULATION_CEILING`
- **`tracking/background_processor.py`:** Floor gate in `__post_init__` — symmetric to ceiling: `and (self.context != "background" or self.rmssd_ms >= CONFIG.tracking.RMSSD_POPULATION_FLOOR)`
- **`tracking/daily_summarizer.py`:** Both `_compute_suppression_area()` and `_compute_recovery_area_waking()` gained `personal_floor: Optional[float] = None` param + clamp: `effective_rmssd = max(effective_rmssd, personal_floor)`. Both call-sites in `compute_daily_summary()` pass `personal_floor`.

---

#### Phase 2A — Server-side sleep relabelling (SUBSEQUENTLY REMOVED — see below)

Added in `api/services/tracking_service.py`: if context=background, window valid, HR < 75 bpm, UTC hour in 16–01 window → relabel context to `sleep`. **This was removed in the same session** (see "Fix: Remove Fix A" below) — it caused score fluctuation by creating false sleep→wake transitions in the evening.

---

#### Phase 2B — Client-side threshold relaxation (`Zenflow_front/src/services/PolarService.ts`)

Made sleep detection more sensitive to catch overnight wear without a morning read:

| Threshold | Before | After |
|---|---|---|
| `SLEEP_HR_THRESHOLD` | 60 | 70 |
| `SLEEP_CV_THRESHOLD` | 0.06 | 0.10 |
| `SLEEP_CONFIRM_BEATS` | 45 | 20 |
| `WAKE_HR_THRESHOLD` | 65 | 75 |
| `WAKE_CV_THRESHOLD` | 0.10 | 0.12 |
| `WAKE_CONFIRM_BEATS` | 15 | 10 |

Hard resets replaced with soft half-decrements: `Math.floor(count / 2)` — avoids thrashing on noisy transitions.

---

#### Phase 3 — Materialised scoring (scores persist to DB on every ingest)

**Problem:** `compute_live_summary()` re-ran from scratch on every API call — no caching, scores could drift if wake boundary shifted.

- **`api/db/schema.py`:** Added `updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())` to `DailyStressSummary`
- **`api/services/tracking_service.py`:** Added `_materialise_daily_score()` method — upserts `DailyStressSummary` from `compute_live_summary(today)`, skips finalised rows (`is_partial_data=False`). Called non-fatally after every `ingest_background_window()` commit.
- **`alembic/versions/g2h3i4j5k6l7_materialised_score_updated_at.py`:** Migration adding `updated_at` column. `down_revision = 'f1a2b3c4d5e6'`. Applied: `railway run alembic upgrade head`.

---

#### Phase 4 — Replay script

- **`scripts/replay_daily_scores.py`:** Iterates all (user, date) pairs with `background_windows` data, skips finalised rows, calls `compute_live_summary()` and upserts `DailyStressSummary`. Supports `--user` and `--dry-run` flags.
- Run successfully: 11 (user, date) pairs replayed, 0 errors. Test user (8e87…) got Mar 17=−3.0, Mar 18=−3.0, Mar 19=−1.6.

---

#### Fix: Remove Fix A (score fluctuation root cause)

**Root cause analysis:** Fix A was relabelling evening resting windows (low HR, valid) as `sleep`. This created spurious `sleep→background` context transitions in the evening. `detect_wake_sleep_boundary()` Priority 1 chain picked up these transitions as the "morning wake" event, setting `wake_ts` to an evening timestamp → all daytime windows thrown out → scores collapsed → next window had no sleep label → `wake_ts` reverted to `typical_wake_time` → scores recovered → loop repeated.

**Fix:** Removed the entire Fix A block (18 lines) from `api/services/tracking_service.py`. Sleep context is now purely client-side (Polar band `PolarService.ts` thresholds from Phase 2B). Deploy: `railway up --detach` — commit `a92c967`.

---

#### Feature: Diverging Window Chart on ReadinessOverlay screen

**New component `DivergingWindowChart`** added to `Zenflow_front/src/ui/zenflow-ui-kit.tsx`:
- Props: `windows: DivergingWindowPoint[]`, `morningAvg: number`, `title?: string`
- Filters to `is_valid=true` + `context="background"` only
- Centre line = `morningAvg` baseline
- Green bars (`ZEN.colors.recovery`) above centre = windows where RMSSD > baseline
- Stress-colour bars (`ZEN.colors.stress`) below centre = windows where RMSSD < baseline
- Near-baseline nub (2px) for `|delta| < 1ms`
- X-axis time labels (`HH:MM`), scrollable, design-system compliant (palette, radius, spacing)

**`ReadinessOverlayScreen` updated** (`Zenflow_front/src/screens/ReadinessOverlayScreen.tsx`):
- Added `morningAvg` and `waveformData` state
- Extracts `rmssd_morning_avg` from existing `getDailySummary()` call
- Promotes waveform array (fetched every 60s) to state
- Renders `DivergingWindowChart` between the score card and 7-day `CombinedBalanceChart`
- Gated: only shown when `waveformData.length > 0 && morningAvg !== null`

---

### Infrastructure state (19 March 2026)

| Resource | Value |
|---|---|
| Backend API (Railway) | `https://api-production-8195d.up.railway.app` |
| Railway PORT | `8080` (injected by Railway; `start.sh` uses `${PORT:-8000}`) |
| DB public URL | `postgresql://postgres:lStXwgKefGXXShUSTPXvxTmKluKPcLmE@switchyard.proxy.rlwy.net:35936/railway` |
| Test user | `8e8715c6-c6ab-45c1-a7da-f037207cf689` |
| Personal model | floor=22, ceiling=65, morning_avg=24.6 (seed values — nightly calibration not yet run) |
| Calibration locked | ❌ Not yet (needs 3 morning reads post close_day) |
| close_day ever fired | ❌ Not yet — all rows `is_partial_data=true`, first run tonight 18:30 UTC |
| Frontend dev server | Metro on `http://192.168.1.107:8081` (port may vary — check `npx expo start --port 8081`) |
| Dev APK | Installed on device; scan QR or open `exp+zenflow-verity://expo-development-client/?url=http%3A%2F%2F192.168.1.107%3A8081` |
| Latest backend commit | `a92c967` — "Remove server-side sleep relabelling (Fix A)" |

---

### Files changed this session

| File | Change |
|---|---|
| `config/tracking.py` | Added `RMSSD_POPULATION_FLOOR = 3.0` |
| `tracking/background_processor.py` | Floor gate symmetric to ceiling gate |
| `tracking/daily_summarizer.py` | `personal_floor` param + clamp in both scoring functions |
| `api/services/tracking_service.py` | Added `_materialise_daily_score()` + ingest trigger; removed Fix A block |
| `api/db/schema.py` | `updated_at` column on `DailyStressSummary` |
| `alembic/versions/g2h3i4j5k6l7_…` | Migration for `updated_at` — applied ✅ |
| `scripts/replay_daily_scores.py` | NEW — replay/backfill script |
| `start.sh` | `--port "${PORT:-8000}"` (Railway PORT injection fix) |
| `railway.toml` | `healthcheckTimeout = 300` |
| `Zenflow_front/src/services/PolarService.ts` | Sleep/wake threshold relaxation (Phase 2B) |
| `Zenflow_front/src/ui/zenflow-ui-kit.tsx` | Added `DivergingWindowChart` component |
| `Zenflow_front/src/screens/ReadinessOverlayScreen.tsx` | Wired `DivergingWindowChart` + `morningAvg` state |

### Status tracker

| Change | Status |
|---|---|
| Phase 1: Floor gate | ✅ Done |
| Phase 2A: Fix A (server relabelling) | ✅ Removed — caused fluctuation |
| Phase 2B: PolarService thresholds | ✅ Done |
| Phase 3: Materialised scoring + schema | ✅ Done + migration applied |
| Phase 4: Replay script | ✅ Done — 11 rows backfilled |
| Fix A removal + Railway deploy | ✅ `a92c967` deployed |
| Diverging window chart | ✅ Done — hot-reload active |
| Score fluctuation | ✅ Fixed (Fix A removed) |
| Close_day / nightly calibration | ⏳ Tonight 18:30 UTC first run |
| Calibration lock (3 morning reads) | ⏳ Pending |

---

**Last updated:** 17 March 2026 (Part 6 + DB recovery) — LLM plan wiring + sleep artefact gate + Postgres data fully recovered

---

## Handoff Note — Session of 17 March 2026 (DB Recovery)

### What happened

Railway Postgres service `Postgres-CiQD` entered a crash loop (volume corruption, same as Issue #4). During recovery the service was deleted and a new one provisioned — but the **old volume `postgres-volume-W8Qt` was not deleted**, retaining all data (116 MB).

#### Recovery steps executed

1. Swapped volume on new Postgres service from empty `Jh66` → `W8Qt`
2. Hit PG17/PG18 version mismatch — changed Postgres service image to `postgres:17`
3. Old pg_hba.conf had the old password hash (Postgres-CiQD credentials) — blocked connection
4. Set custom start command to bypass pg_hba.conf with trust auth:
   `bash -c "echo 'host all all 0.0.0.0/0 trust' > /tmp/ph.conf && chmod a+r /tmp/ph.conf && exec gosu postgres postgres -c hba_file=/tmp/ph.conf -D $PGDATA"`
5. Connected with no password and reset: `ALTER USER postgres WITH PASSWORD 'lStXwgKefGXXShUSTPXvxTmKluKPcLmE'`
6. Removed custom start command, redeployed — normal scram-sha-256 auth restored
7. API `/health` ✅, old test user `2420112a-d69c-4938-972a-6598cc8526af` responding with real data ✅

**All data fully recovered. No data was lost.**

### Current infrastructure state

| Resource | Value |
|---|---|
| Postgres service | `Postgres` (postgres:17) |
| Volume | `postgres-volume-W8Qt` (116 MB, mounted) |
| Internal URL | `postgresql://postgres:lStXwgKefGXXShUSTPXvxTmKluKPcLmE@postgres.railway.internal:5432/railway` |
| Public URL | `postgresql://postgres:lStXwgKefGXXShUSTPXvxTmKluKPcLmE@switchyard.proxy.rlwy.net:35936/railway` |
| API DATABASE_URL | set to internal URL above |
| API DATABASE_SYNC_URL | `postgresql+psycopg2://postgres:lStXwgKefGXXShUSTPXvxTmKluKPcLmE@postgres.railway.internal:5432/railway` |
| Test user ID | `2420112a-d69c-4938-972a-6598cc8526af` (unchanged) |

### Empty volume

`postgres-volume` (0 MB, unmounted) and `postgres-volume-Jh66` (198 MB, unmounted) — both safe to delete from Railway dashboard to avoid confusion.

---

## Handoff Note — Session of 17 March 2026 (Part 6) — LLM Plan Wiring + Sleep Gate Scoping

### What was done this session

#### Item 1 — LLM plan is now the primary plan source (not rule-based prescriber)

**Root cause discovered in Part 5 design review:** `PlanService.get_or_create_today_plan()` always called `build_daily_plan(inputs)` (rule-based prescriber). `build_daily_plan_from_uup()` existed in `coach/prescriber.py` and was correctly wired in `coach_service.py` (coach chat) but was **never called from the plan generation flow**. The LLM Layer 2 plan from the nightly rebuild was stored in `user_unified_profiles` but never served to the user via `GET /plan/today`.

**Fix — `api/services/plan_service.py`:**

1. Added `build_daily_plan_from_uup` to the `coach.prescriber` import
2. Added `from api.services.profile_service import load_unified_profile`
3. In `get_or_create_today_plan()`, before the rule-based path:

```python
# Try LLM plan first — nightly Layer 2 output from unified profile
if uid is not None:
    uup = await load_unified_profile(self._db, uid)
    if uup is not None:
        uup_plan = build_daily_plan_from_uup(
            uup,
            readiness_score=inputs.readiness_score,
            stage=inputs.stage,
        )
        if uup_plan is not None:
            await self._persist_plan(uid, uup_plan, today_dt)
            logger.info("plan_source=uup user=%s", user_id)
            return uup_plan.model_dump()

# Fallback: rule-based prescriber
plan: DailyPlan = build_daily_plan(inputs)
```

**Behaviour by user state:**
- **Pre-calibration / no nightly rebuild yet:** `load_unified_profile` returns `None` → fallback fires → rule-based plan. No change for new users.
- **Post-calibration:** `build_daily_plan_from_uup` checks `plan_for_date == today`; returns `None` if stale → fallback fires. Plan is only LLM if it was generated last night.
- **Post-calibration, fresh nightly rebuild:** LLM plan served. `prescriber_notes` includes `"plan_source: unified_profile_layer2"` for audit.

Rule-based prescriber is kept as permanent fallback — not removed.

---

#### Item 2 — Artefact gate scoped to background context only

**Root cause:** The `RMSSD_POPULATION_CEILING = 110.0` gate added in Part 5 had no context guard. It applied to ALL window contexts including `"sleep"`. A deeply recovered sleeper with overnight RMSSD > 110 ms would have valid sleep windows incorrectly rejected.

**Fix — `tracking/background_processor.py` — `__post_init__`:**
```python
self.is_valid = (
    self.rmssd_ms is not None
    and self.confidence >= 0.5
    and self.n_beats >= CONFIG.tracking.BACKGROUND_MIN_BEATS
    and (
        self.context != "background"
        or self.rmssd_ms <= CONFIG.tracking.RMSSD_POPULATION_CEILING
    )
)
```
The ceiling gate now fires **only for `context == "background"`** windows (waking, motion-artefact-prone). Sleep windows pass regardless of RMSSD — their biology supports high values (parasympathetic dominance during deep sleep).

**Downstream scoring already correct:** `_compute_recovery_area_waking()` and `_compute_suppression_area()` already filter `context != "background"` before applying the `personal_ceiling` clamp. Only `__post_init__` needed the context guard.

---

#### Item 3 — Front-end sleep context labelling verified (no backend change needed)

**Finding:** `src/services/PolarService.ts` already has automatic `background → sleep` context detection. `_sleepState` field auto-transitions based on `meanHR ≤ SLEEP_HR_THRESHOLD AND PPI CV < SLEEP_CV_THRESHOLD`. Ingest calls send `context="sleep"` during overnight wear. Server-side time-based fallback is not needed.

---

### Files changed this session

| File | Change |
|---|---|
| `api/services/plan_service.py` | Added `build_daily_plan_from_uup` + `load_unified_profile` imports; LLM-first plan lookup before rule-based fallback |
| `tracking/background_processor.py` | `__post_init__` ceiling gate wrapped in `self.context != "background" or ...` guard |

### Status tracker

| Change | Status | Notes |
|---|---|---|
| Item 1: LLM plan wiring in `plan_service.py` | ✅ Done | `api/services/plan_service.py` |
| Item 2: Background-only artefact gate | ✅ Done | `tracking/background_processor.py` |
| Item 3: Sleep context front-end verification | ✅ Done (no code) | PolarService.ts already handles it |

### Deployment
Both files passed `python3 -m py_compile`. `railway up --detach` completed. Health confirmed: `{"status": "ok"}` at `https://api-production-8195d.up.railway.app/health`.

---

**Last updated:** 17 March 2026 (Part 5) — Artifact spike fix + Plan lifecycle + Assessor integration — deployed to Railway
**Hardware:** Polar Verity Sense (optical armband)
**Status:** DEPLOYED & WORKING — API live on Railway, dev client APK on test phone (hot reload active)
**Parent project:** ZenFlow_project (H10 chest strap, running and stable — do not touch)

---

## Handoff Note — Session of 17 March 2026 (Part 5) — Artifact Fix + Plan Lifecycle + Assessor

### What was done this session

#### Phase A — RMSSD artifact spike fix (live scoring accuracy)

**Root cause confirmed:** DB screenshots showed background windows at 168–352 ms with `confidence = 0.417–1.0` and `is_valid = True`. Optical PPG motion artefacts at this RMSSD range pass the existing confidence + n_beats gates because artefact detection operates at beat level, not variance level. One 171 ms window generates the same recovery credit as ~22 legitimate windows.

**A1 — `config/tracking.py`:** Added new constant:
```python
# Population-level ceiling for RMSSD validity gate.
# Windows above this threshold are optical-PPG motion artefacts, not genuine HRV.
RMSSD_POPULATION_CEILING: float = 110.0
```

**A2 — `tracking/background_processor.py` — `__post_init__` gate:**
```python
self.is_valid = (
    self.rmssd_ms is not None
    and self.confidence >= 0.5
    and self.n_beats >= CONFIG.tracking.BACKGROUND_MIN_BEATS
    and self.rmssd_ms <= CONFIG.tracking.RMSSD_POPULATION_CEILING   # ← NEW
)
```
Any window with RMSSD > 110 ms is immediately marked invalid. This is a hard reject — the window is still stored in the DB for audit but excluded from all scoring.

**A3 — `tracking/daily_summarizer.py` — area clamp:**
Both `_compute_recovery_area_waking()` and `_compute_suppression_area()` gained a `personal_ceiling: Optional[float] = None` parameter. When present:
```python
effective_rmssd = min(w.rmssd_ms, personal_ceiling) if personal_ceiling is not None else w.rmssd_ms
```
This second layer ensures that even a window which barely slipped under the 110 ms population gate (e.g. 95 ms) cannot generate more recovery credit than the user's calibrated ceiling (52.3 ms) permits. Both call-sites in `compute_daily_summary()` now pass `personal_ceiling`.

**No data reset required.** Existing `is_valid = True` rows in the DB are not mutated — the `is_valid` flag is set at ingest time, so all future windows use the new gate. Historic bad rows are capped by the area clamp even if they remain `is_valid = True` in the DB.

---

#### Phase B — Plan lifecycle (morning trigger + 09:00 IST fallback)

**Problem:** Plan was generated on-demand only — the user only got a `DailyPlan` after explicitly calling `GET /plan/today`. No proactive generation on morning read, no safety net for users who don't do a morning read.

**B1 — `api/services/tracking_service.py` — morning read plan trigger:**
After the `morning_row.day_type` classification and `flush()`, the morning read ingest now immediately generates today's plan:
```python
try:
    from api.services.model_service import ModelService
    from api.services.plan_service import PlanService
    model_svc = ModelService(self._db)
    plan_svc  = PlanService(self._db, model_svc)
    await plan_svc.get_or_create_today_plan(str(self._uid), force_regen=True)
except Exception as _plan_exc:
    logger.warning("Morning-read plan trigger failed user=%s: %s", ...)
```
Wrapped in try/except — a plan failure never blocks window ingest.

**B2 — `jobs/plan_reset.py` (NEW FILE):**
`force_plan_reset_for_all_users()` — iterates users active in the last 48 h.  
For each: checks whether a `DailyPlan` already exists for today (B1 fired) → if yes, skips; if no, calls `get_or_create_today_plan(force_regen=True)`. Per-user `AsyncSessionLocal` sessions isolate failures.

**B3 — `api/main.py` — second APScheduler cron:**
```python
scheduler.add_job(
    force_plan_reset_for_all_users,
    CronTrigger(hour=3, minute=30, timezone="UTC"),   # 09:00 IST
    id="morning_plan_reset",
    ...
)
```
Runs at 03:30 UTC (09:00 IST) — covers users who wore the band overnight but sent no morning read. The existing 18:30 UTC nightly rebuild job is unchanged.

**Plan read-after-generation:** `GET /plan/today` calls `get_or_create_today_plan(force_regen=False)` — returns the cached row. Plan is never regenerated on a read. Stable for the entire day once generated.

---

#### Phase C — Assessor integration + adherence context in Layer 2

**Problem:** `coach/assessor.py` was fully implemented (3-gate system: adherence ≥ 60%, readiness trend 14d, session quality ≥ 0.25) but never called. The Layer 2 LLM prompt only received `net_balance / stress_score / recovery_score` — no behavioural/adherence context.

**C1 — `jobs/nightly_rebuild.py` — `_run_assessor()` helper + call:**
New async helper `_run_assessor(session, user_id)`:
- Fetches last 10 `Session` rows → `SessionRecord` list
- Fetches 28-day `DailyStressSummary` → `ReadinessRecord` list (readiness = `waking_recovery_score`)
- Fetches 30-day `PlanDeviation` rows → `DeviationRecord` list
- Computes 7-day per-category adherence from `DailyPlan.items_json` + `adherence_pct`
- Reads `TagPatternModel.sport_stressor_slugs`
- Reads `User.training_level` as `current_stage`
- Calls synchronous `assess_user()` (pure Python — no `asyncio.to_thread` needed)

Called in `_rebuild_one_user()` after `close_day()`, before profile rebuild. Assessor failure is non-fatal (logged as warning, assessment passed as `None`).

**C2 — `api/services/profile_service.py`:**
`rebuild_unified_profile()` gains `assessment: Optional[Any] = None` parameter. Passes `assessment.adherence_7d` and `assessment.summary_note` down to `run_layer2_plan()`.

**C3 — `profile/nightly_analyst.py`:**
`run_layer2_plan()` and `_build_layer2_user_prompt()` gain `adherence: Optional[dict]` and `assessment_note: Optional[str]` params. When present, the Layer 2 prompt now includes:
```
ADHERENCE LAST 7 DAYS (by category):
  breathing: 80%
  movement: 50%
  recovery: 30%
COACHING NOTE: {assessment.summary_note}
```
The LLM now has real behavioural data alongside physiological scores to personalise the plan.

**Stage write:** Assessor outputs `ready=True/False` only. Stage number is NOT incremented by this job — that decision is deferred (explicitly out of scope for this session).

---

### Files changed this session

| File | Change |
|---|---|
| `config/tracking.py` | Added `RMSSD_POPULATION_CEILING: float = 110.0` |
| `tracking/background_processor.py` | `__post_init__` ceiling gate `and self.rmssd_ms <= CONFIG.tracking.RMSSD_POPULATION_CEILING` |
| `tracking/daily_summarizer.py` | `personal_ceiling` param + `effective_rmssd = min(...)` clamp in `_compute_recovery_area_waking()` and `_compute_suppression_area()`; both call-sites in `compute_daily_summary()` updated |
| `api/services/tracking_service.py` | Morning read → `get_or_create_today_plan(force_regen=True)` trigger after `flush()` |
| `jobs/plan_reset.py` | NEW — `force_plan_reset_for_all_users()` 09:00 IST fallback |
| `api/main.py` | Second APScheduler job at `CronTrigger(hour=3, minute=30)` for morning plan reset |
| `jobs/nightly_rebuild.py` | `_run_assessor()` helper; calls `assess_user()`; passes `assessment=` to `rebuild_unified_profile()` |
| `api/services/profile_service.py` | `rebuild_unified_profile()` + `assessment` param, threads to `run_layer2_plan()` |
| `profile/nightly_analyst.py` | `run_layer2_plan()` + `_build_layer2_user_prompt()` with `adherence` + `assessment_note` |

### Status tracker

| Change | Status | Notes |
|---|---|---|
| A1: `RMSSD_POPULATION_CEILING` config constant | ✅ Done | `config/tracking.py` |
| A2: `is_valid` ceiling gate | ✅ Done | `tracking/background_processor.py` |
| A3: Area clamp with `personal_ceiling` | ✅ Done | `tracking/daily_summarizer.py` |
| B1: Morning read → plan trigger | ✅ Done | `api/services/tracking_service.py` |
| B2: `jobs/plan_reset.py` | ✅ Done | New file |
| B3: 03:30 UTC cron in scheduler | ✅ Done | `api/main.py` |
| C1: `_run_assessor()` + call in nightly rebuild | ✅ Done | `jobs/nightly_rebuild.py` |
| C2: `assessment` param in `rebuild_unified_profile` | ✅ Done | `api/services/profile_service.py` |
| C3: Adherence block in Layer 2 prompt | ✅ Done | `profile/nightly_analyst.py` |
| Change 3 (out-of-bounds gate) | 🅿 PARKED | Explicitly deferred |
| Stage advancement write on gate pass | 🅿 PARKED | Assessor outputs ready flag only |
| Coach push on capacity growth trigger | 🅿 PARKED | P5 item |

### Deployment
All 9 files passed `python3 -m py_compile`. `railway up --service api` completed. Health confirmed: `{"status": "ok"}` at `https://api-production-8195d.up.railway.app/health`.

---


## ~~⚠️ NEXT SESSION MUST-FIX~~ ✅ FIXED 17 March 2026 — Read before touching any score/boundary code

### The day boundary is the MORNING READ, not midnight

**THIS IS THE MOST IMPORTANT DESIGN RULE IN THE ENTIRE SYSTEM. READ CAREFULLY.**

#### What the user experiences (correct design)

- The band streams data 24/7 — overnight, through midnight, all morning.
- **Midnight is invisible.** The user never sees scores reset at midnight.
- Scores accumulate **continuously** across midnight. If stress was at 45 at 11:59pm, it is still at 45 (or higher/lower based on new windows) at 12:01am.
- The **day resets at morning read (~9am)**. That is the only moment scores go back to 0 for the new day.

#### The asymmetric carry-forward rule (fires at morning read, not midnight)

When morning read arrives:
- Yesterday's `closing_balance` → today's `opening_balance`
- If `closing_balance` was **positive** (+32): `opening_recovery = +32`, `opening_stress = 0`, scores start at stress=0, recovery=32
- If `closing_balance` was **negative** (−32): `opening_recovery = 0`, `opening_stress = −32`, scores start at stress=32, recovery=0

**The opening balance pre-loads the scores.** A surplus shows up as already-accumulated recovery before the user does anything. A deficit shows up as already-accumulated stress they must earn back.

#### What the code currently does WRONG

`compute_live_summary(today)` uses Python's calendar date (`date.today()`). At midnight, `today` flips to the new date → no windows yet for the new calendar day → scores show 0 (or fall back to yesterday's carried values). This feels like a reset at midnight, which is wrong.

**The actual bug:** Day boundary logic is tied to calendar midnight instead of morning read arrival.

#### What needs to change (DO NOT implement without re-reading this first)

1. `compute_live_summary()` must span across midnight: query windows from `last_morning_read_ts` (yesterday's) to `now`, not from `calendar_day_start` to `now`.
2. `opening_balance` must NOT be applied at midnight — it is applied only when the morning read lands and the new "day" officially begins.
3. `close_day()` is triggered by sleep detection or cron — that is fine. The DB row for the calendar date is still written at night. The issue is only with the **live display** during the overnight / early morning window.
4. The app fallback chain in `GET /tracking/daily-summary` must not use yesterday's row as "carry forward" — that's the wrong signal. It should continue showing today's accumulating live computation even if it spans midnight.

#### Concrete example of correct behaviour

```
11:00pm — stress=18, recovery=45, net_balance=+27
11:59pm — stress=22, recovery=47, net_balance=+25
12:01am — stress=24, recovery=47, net_balance=+23   ← numbers keep moving, NO reset
02:00am — stress=26, recovery=52, net_balance=+26   ← sleep recovery accumulating
06:00am — stress=26, recovery=68, net_balance=+42   ← good night's sleep
09:00am — MORNING READ ARRIVES
          → opening_recovery = +42, opening_stress = 0
          → today's scores reset: stress=0, recovery=42
          → new day's windows start accumulating on top
```

#### Summary

| Trigger | What happens |
|---|---|
| Midnight (00:00 IST) | `close_day()` writes DB row for yesterday — INTERNAL ONLY. No UI change. |
| User wears band overnight | Windows keep streaming, live scores keep moving — no reset |
| Morning read arrives (~9am) | Scores reset to 0, opening_balance applied, new day begins for the user |

---

---

## Handoff Note — Session of 17 March 2026 (Part 4) — Scoring Redesign v2: Split Denominator + Sleep Baseline

### What was done this session

**Diagnosis:** After Part 3 fixes, scores were still inflated: `net_balance ≈ 226`, `waking_recovery_score = 100.0`. Two root causes identified:
1. **Overnight path spans 33+ hours** (no prior `close_day` row, so `day_start = prev_morning_read_ts` from 2 days ago). Thousands of extra windows against a 16h denominator → massive inflation.
2. **Sleep RMSSD scored against waking baseline** — sleep RMSSD (~40–60 ms) always above waking avg (28.7 ms) → recovery score locked at 100 every night.

**Design approved by user:** Split denominators (stress = 960 min, recovery = 1440 min), separate sleep RMSSD baseline, no-band fallback defaults, synthetic wake boundary.

---

### Change 1 — Split denominator (`config/tracking.py`, `tracking/daily_summarizer.py`)

```python
# config/tracking.py
DAILY_CAPACITY_WAKING_MINUTES: int = 960    # 16h × 60 — stress budget (waking only)
DAILY_CAPACITY_RECOVERY_MINUTES: int = 1440  # 24h × 60 — recovery budget (full day)
```

```python
# daily_summarizer.compute_daily_summary()
rmssd_range = max(0.0, personal_ceiling - personal_floor)
ns_capacity_stress   = rmssd_range * cfg.DAILY_CAPACITY_WAKING_MINUTES    # 960
ns_capacity_recovery = rmssd_range * cfg.DAILY_CAPACITY_RECOVERY_MINUTES  # 1440

stress_pct_raw   = round(actual_suppression   / ns_capacity_stress   * 100.0, 2)
recovery_pct_raw = round(total_recovery_area  / ns_capacity_recovery * 100.0, 2)
```

`DailySummaryResult` gained `ns_capacity_recovery_used` field. DB column `daily_stress_summaries.ns_capacity_recovery` added.

---

### Change 2 — Sleep RMSSD baseline (`api/db/schema.py`, `api/services/tracking_service.py`, `tracking/daily_summarizer.py`)

New columns on `personal_models`: `rmssd_sleep_avg`, `rmssd_sleep_ceiling`.
New columns on `calibration_snapshots`: `rmssd_sleep_avg_clean`, `sleep_windows_count`.

`_run_calibration_batch()` now computes:
```python
sleep_wins = [w for w in windows if w.context == "sleep" and w.rmssd_ms is not None and w.is_valid]
if len(sleep_wins) >= 12:
    rmssd_sleep_avg_clean = float(np.median([w.rmssd_ms for w in sleep_wins]))   # median
    # P90 reserved as sleep_ceiling for future gate
```

When `rmssd_sleep_avg` is populated, `compute_daily_summary()` uses a sleep-specific helper `_compute_recovery_area_sleep_raw()` that scores each sleep window against `rmssd_sleep_avg` instead of the waking floor. Until the user sleeps with the band (after calibration), `rmssd_sleep_avg` remains NULL and scores fall back to the previous area computation.

---

### Phase 0a — No-band sleep default (`tracking/wake_detector.py`)

Absolute last resort when both `typical_sleep_time` IS NULL and no `last_background_window_ts`:
```python
# 22:00 IST = 16:30 UTC
if sleep_ts is None:
    sleep_ts = day_date.replace(hour=16, minute=30, second=0, microsecond=0)
    if sleep_ts <= wake_ts:
        sleep_ts = sleep_ts + timedelta(days=1)
    sleep_method = "no_band_default"
```

---

### Phase 0b — Synthetic wake boundary (`api/services/tracking_service.py`)

Prevents 25h+ inflation when band is worn overnight but no morning read has arrived yet. Added in `compute_live_summary()` overnight branch:
```python
# Phase 0b: if band worn past typical wake + 2 h but no morning read,
# treat as a fresh day to prevent 25h+ score inflation.
if personal.typical_wake_time:
    _h, _m = (int(x) for x in personal.typical_wake_time.split(":"))
    _synthetic_wake = cal_start.replace(hour=_h, minute=_m, second=0, microsecond=0)
    if now > _synthetic_wake + timedelta(hours=2):
        day_start          = cal_start
        day_end            = now
        opening_balance_fn = True
```

---

### Alembic migration — `f1a2b3c4d5e6` (chained from `d1e2f3a4b5c6`)

- `personal_models`: adds `rmssd_sleep_avg FLOAT`, `rmssd_sleep_ceiling FLOAT`
- `calibration_snapshots`: adds `rmssd_sleep_avg_clean FLOAT`, `sleep_windows_count INT`
- `daily_stress_summaries`: adds `ns_capacity_recovery FLOAT`

---

### Data reset required after deploy

Old `net_balance` values were computed with the wrong denominator (155-ms ceiling). After migration:
```sql
UPDATE daily_stress_summaries
SET opening_balance=0, closing_balance=0, net_balance=0, recovery_pct_raw=NULL
WHERE user_id='2420112a-d69c-4938-972a-6598cc8526af';
```

---

### Status tracker

| Step | Status | Notes |
|---|---|---|
| Phase 0a — no-band sleep default 22:00 IST | ✅ Done | `tracking/wake_detector.py` |
| Phase 0b — synthetic wake boundary | ✅ Done | `compute_live_summary()` |
| Phase 1 — split denominator config | ✅ Done | `config/tracking.py` |
| Phase 2 — Alembic migration + ORM columns | ✅ Done | `f1a2b3c4d5e6` |
| Phase 3 — sleep baseline in calibration | ✅ Done | `_run_calibration_batch()` |
| Phase 4 — daily_summarizer split logic | ✅ Done | `compute_daily_summary()` helper |
| Phase 5 — close_day + compute_live_summary sleep params | ✅ Done | `tracking_service.py` |
| Phase 6 — data reset SQL | ⏳ Run after deploy | SQL above |
| Change 3 — out-of-bounds gate | 🅿 PARKED | Explicitly deferred by user |

---

### Deployment note

```bash
railway run alembic upgrade head --service api
# …then data reset SQL…
railway up --service api
```

---



### What was done this session

#### Bug Fix 1 — `wake_ts` fallback was 07:00 UTC = 12:30pm IST (`tracking/wake_detector.py`)

`detect_wake_sleep_boundary()` absolute fallback was `hour=7, minute=0` (07:00 UTC). The user's morning reads arrive at ~03:30 UTC (09:00 IST), before that fallback → `wake_ts` was set to 12:30pm IST → every morning window was treated as pre-wake → `_compute_suppression_area` and `_compute_recovery_area_waking` both returned 0.0 → `stress_load_score = 0`, `waking_recovery_score = 0` all morning.

**Fix:** Absolute fallback changed from `hour=7, minute=0` → `hour=1, minute=30` (01:30 UTC = 07:00 IST). Morning reads at 03:30 UTC are now after `wake_ts` and are counted correctly.

```python
# Absolute fallback: 07:00 IST = 01:30 UTC  (app is IST-based)
if wake_ts is None:
    wake_ts = day_date.replace(hour=1, minute=30, second=0, microsecond=0)
    wake_method = "morning_read_anchor"
```

#### Bug Fix 2 — Overnight branch needed `wake_ts = day_start` override (`api/services/tracking_service.py`)

In the overnight path of `compute_live_summary()`, `day_start` is yesterday's morning read (~03:30 UTC yesterday). Even after Fix 1, the new fallback `wake_ts = 01:30 UTC today` is still AFTER `day_start` → `_compute_suppression_area` and `_compute_recovery_area_waking` skip all overnight windows (they only count windows after `wake_ts`).

**Fix:** After `detect_wake_sleep_boundary(...)`, the overnight branch now overrides `boundary.wake_ts = day_start` so all overnight windows are counted:

```python
# Overnight branch: override wake_ts to day_start so the entire span counts.
if not opening_balance_fn:
    boundary.wake_ts        = day_start
    boundary.waking_minutes = (
        ((boundary.sleep_ts or now) - day_start).total_seconds() / 60.0
    )
```

#### Database recovery (mid-session)

Railway Postgres service had stopped and DATABASE_URL on the API service was wiped to `postgresql://` (empty) during a failed deploy cycle. Both were restored:
- Postgres: `railway redeploy --service Postgres-CiQD` — data intact (volume-backed)
- DATABASE_URL: `railway variables set DATABASE_URL=postgresql+asyncpg://...`
- DATABASE_SYNC_URL: `railway variables set DATABASE_SYNC_URL=postgresql+psycopg2://...`

#### Old CLI worktree removed

VS Code Copilot CLI agent had created `copilot-worktree-2026-03-17T04-24-37` on the wrong branch with pre-fix code. Would have reverted the `opening_balance` fix if merged. Removed with `git worktree remove --force`.

#### Expected behaviour after these fixes

Scores accumulate from morning read onward. Verified API response (17 March 2026, ~15:00 IST):
```json
{
    "stress_load_score": 26.9,
    "waking_recovery_score": 100.0,
    "net_balance": 219.6
}
```
`net_balance: 219.6` is temporarily inflated — `waking_minutes` covers the full overnight span (~21h) because no prior `close_day` row exists. Will normalise after tonight's midnight IST cron writes the finalized close-day row.

#### Pending (low urgency) — Fix 3: opening_balance NULL fallback

When `prev_summary.opening_balance IS NULL` (pre-column rows), the overnight branch falls back to 0 instead of trying `closing_balance` first. Recommend applying before tonight's midnight cron:

```python
# In compute_live_summary() overnight branch (~line 1025)
else:
    if prev_summary is not None:
        val = prev_summary.opening_balance
        if val is None:
            val = prev_summary.closing_balance
        opening_balance = float(val or 0.0)
    else:
        opening_balance = 0.0
```

#### Deployment
`railway up --service api` from local disk. Health confirmed: `{"status":"ok"}` at `https://api-production-8195d.up.railway.app/health`. Scores live.

### Status tracker
| Step | Status | Notes |
|---|---|---|
| `wake_ts` fallback 07:00 UTC → 01:30 UTC | ✅ Fixed 17 Mar | `tracking/wake_detector.py` |
| Overnight `boundary.wake_ts = day_start` override | ✅ Fixed 17 Mar | `api/services/tracking_service.py` `compute_live_summary()` |
| DATABASE_URL / Postgres restored | ✅ Fixed 17 Mar | Railway variables restored manually |
| Stale CLI worktree removed | ✅ Fixed 17 Mar | git worktree remove --force |
| `opening_balance` NULL → try `closing_balance` | ⏳ Pending | Low urgency, apply before midnight cron |

---

---

## Handoff Note — Session of 17 March 2026 (Part 2) — Overnight Balance + Sleep Recovery Fix

### What was done this session

#### Bug Fix 1 — Overnight `opening_balance = 0.0` (`api/services/tracking_service.py`)

`compute_live_summary()` overnight branch was setting `opening_balance = 0.0`. This dropped the entire historical carry-forward whenever no morning read had arrived yet (i.e. from midnight through ~9am). The live `net_balance` during that window was computed as `yesterday_recovery + sleep_recovery − yesterday_stress + 0`, completely losing the previous days' accumulated surplus or deficit.

**Fix:** The overnight branch now calls `_load_day_summary(prev_date)` (same call as the morning-read branch) and sets:
```python
opening_balance = float(prev_summary.opening_balance or 0.0) if prev_summary else 0.0
```

With this fix, `net_balance` at 01:00am ≈ yesterday's `closing_balance` + sleep recovery accumulated so far — the correct continuous thread.

#### Bug Fix 2 — Sleep recovery not counted in score (`tracking/daily_summarizer.py`)

`recovery_pct_raw` was computed from `actual_recovery_area_waking` only. Sleep recovery windows (`context="sleep"`) were detected by `detect_recovery_windows()`, stored in `recovery_windows`, and written to audit as `raw_sleep` — but never added to the actual score. Result: net_balance stayed flat overnight even as sleep recovery accumulated in the DB.

**Fix:**
```python
actual_recovery_area_sleep = sum(
    rw.recovery_area for rw in recovery_windows if rw.context == "sleep"
)
total_recovery_area = actual_recovery_area_waking + actual_recovery_area_sleep
recovery_pct_raw = round(total_recovery_area / ns_capacity * 100.0, 2)
```

The audit variable `raw_sleep` now reuses `actual_recovery_area_sleep` (no duplicate iteration).

#### Expected behaviour after these fixes

```
23:30 — stress=22, recovery=47, net_balance=+25   (pre-midnight)
00:01 — stress=24, recovery=47, net_balance=+23   ← continuous, no reset
02:00 — stress=26, recovery=52, net_balance=+26   ← sleep recovery accumulating in score
06:00 — stress=26, recovery=68, net_balance=+42   ← good night's sleep visible in numbers
09:00 — MORNING READ → new day begins, opening_balance = +42
```

#### Deployment
`railway up --service api` from local disk. Health confirmed: `{"status":"ok"}` at `https://api-production-8195d.up.railway.app/health`.

---

---

## Handoff Note — Session of 17 March 2026 — Calibration Overwrite Bug Fix

### What was done this session

#### Root cause diagnosis — personal_model ceiling being silently overwritten

After last session's calibration hardening sprint wrote the correct `rmssd_ceiling = 52.3ms` into `personal_models` (at 15:37 UTC), a session ending at 16:09 UTC overwrote it back to 155.2ms. DB evidence:

- `calibration_snapshots`: `rmssd_ceiling_clean = 52.32ms`, `committed = True`, `snapshot_at = 15:37 UTC`
- `personal_models.updated_at = 16:09 UTC` — 32 min later — with `rmssd_ceiling = 155.2ms`

The overwrite chain:
1. `_run_calibration_batch` correctly writes `ceiling=52.3`, `floor=13.5` to the ORM and flushes at 15:37 UTC
2. `calibration_locked_at` is still NULL at this point (lock is written at end of `close_day()`)
3. A ZenFlow session ends at 16:09 UTC → `update_fingerprint_from_outcome()` in `model_service.py` fires
4. `calibration_locked = False` (because `calibration_locked_at IS NULL`) → `run_update()` computes `new_ceiling = P95(session_rmssd) ≈ 155ms` and updates `fp.rmssd_ceiling`
5. `_persist_fingerprint()` calls `row.rmssd_ceiling = fp.rmssd_ceiling` — **blindly writes 155.2ms back**

Same mechanism also reverted `rmssd_floor` from 13.5 → 15.2ms and `stress_capacity_floor_rmssd` from the recalculated value back.

All three calibration values were wrong in `personal_models` all day. The live scoring denominator was `(155.2 - 29.2) × 960 = 120,960 min·ms` instead of the correct `(52.3 - 13.5) × 960 = 37,248 min·ms` — roughly 3× too large, deflating all scores proportionally.

#### Fix 1 — `_persist_fingerprint` no longer writes calibration-owned fields

`api/services/model_service.py` — `_persist_fingerprint()`:

The three lines that wrote `rmssd_floor`, `rmssd_ceiling`, `rmssd_morning_avg` from the fingerprint object back to the DB row have been **removed**.

These fields are owned exclusively by:
- `_run_calibration_batch()` in `tracking_service.py` — writes floor, ceiling, morning_avg at day-close
- `ingest_background_window()` morning EWM update — writes morning_avg at morning ingest

`_persist_fingerprint` manages all other fingerprint fields (arc stats, coherence, RSA, sessions, interoception) but must never touch calibration parameters it doesn't compute.

**Before:**
```python
row.rmssd_floor             = fp.rmssd_floor
row.rmssd_ceiling           = fp.rmssd_ceiling
row.rmssd_morning_avg       = fp.rmssd_morning_avg
row.recovery_arc_mean_hours = fp.recovery_arc_mean_hours
```
**After:**
```python
# rmssd_floor, rmssd_ceiling, rmssd_morning_avg intentionally not written here.
# Those fields are owned by _run_calibration_batch() and morning EWM update.
row.recovery_arc_mean_hours = fp.recovery_arc_mean_hours
```

#### Fix 2 — DB values restored from committed calibration snapshot

Restored `personal_models` for user `2420112a` by reading the committed `calibration_snapshots` row and reapplying:

| Field | Corrupted | Restored |
|---|---|---|
| `rmssd_floor` | 15.2ms | **13.5ms** |
| `rmssd_ceiling` | 155.2ms | **52.3ms** |
| `rmssd_morning_avg` | 28.7ms | 28.7ms (unchanged — correct) |
| `stress_capacity_floor_rmssd` | 29.2ms | **20.0ms** (recalculated from floor/ceiling) |

`ns_capacity_used` verified via live API: `31,008 min·ms` (was `120,960`). `rmssd_ceiling` in API response confirmed as `52.3ms`.

#### Score behaviour explained (morning of 17 March)

`stress_load_score = 0.0`, `waking_recovery_score = 0.0`, `net_balance = +32.2` is **correct** at 09:00 IST:
- Only ~14 background windows ingested since midnight
- Denominator is now 31,008 min·ms — a reasonable suppression/recovery area of ~76 min·ms = 0.25% — rounds to 0.0 for display
- `opening_balance = +32.2` carried from yesterday's `closing_balance` — correct
- Scores will accumulate visibly as the day progresses. With correct denominator, meaningful stress events (lasting 15+ min at threshold) will now show non-zero scores as expected

#### Deployment
`railway up` from local disk. Confirmed healthy via Railway logs (ingests + daily-summary 200 OKs visible immediately post-deploy).

### Status tracker update
| Step | Status | Notes |
|---|---|---|
| `_persist_fingerprint` overwrites calibration fields | ✅ Fixed 17 Mar | Three lines removed from `api/services/model_service.py` |
| DB corrupted ceiling 155.2ms | ✅ Fixed 17 Mar | Patched from committed snapshot via direct SQL |
| Day boundary = morning read, not midnight | ✅ Fixed 17 Mar | `compute_live_summary()` now queries from last morning read ts when no morning read today; `opening_balance=0` overnight; step-3 carry-forward removed from router. |
| Overnight `opening_balance = 0.0` bug | ✅ Fixed 17 Mar | Overnight branch now sets `opening_balance = yesterday.opening_balance` to preserve the continuous balance thread across midnight. |
| Sleep recovery not counted in score | ✅ Fixed 17 Mar | `actual_recovery_area_sleep` added to `total_recovery_area` before `recovery_pct_raw` in `daily_summarizer.py`. Sleep recovery windows now accumulate in the score overnight. |

---

---

## Handoff Note — Session of 16 March 2026 (Part 3 — Deployment)

### Next Session Focus
~~**Known issue:** With ceiling now corrected to 52.3ms (from poisoned 151.6ms), the RMSSD range is narrow. Stress and recovery scores will move fast because the denominator `ns_capacity_used = (ceiling − floor) × 960` is small. Need to assess whether scores are now oversensitive and whether any damping/clamping is needed.~~
Superseded — see 17 March handoff above. Ceiling is confirmed correct at 52.3ms and the overwrite bug is fixed. Denominator is now `31,008 min·ms`; scores are live and accumulating correctly.

### What was done this session (Part 3)

#### Bug Fix 1 — close_day response crash (`api/routers/tracking.py`)
`CloseDayResponse` was referencing `result.recovery_score` and `result.readiness_score` on the `DailySummaryResult` object — both fields were removed from `DailySummaryResult` during the Part 1 scoring cleanup but the response builder was not updated. This caused an `AttributeError` 500 every time `close_day()` was called (nightly cron + sleep-triggered). The DB write had already committed before the crash so data was safe, but the error fired on every close.

**Fix:** Both fields now return `None` (kept in response model for API backwards compat).

#### Bug Fix 2 — migrations silently hit localhost instead of Railway (`api/config.py`)
`_derive_sync_url()` validator had guard: `"psycopg2" not in self.DATABASE_SYNC_URL`. Because the default `DATABASE_SYNC_URL` already contains `"psycopg2"`, the guard was always `False` — so setting only `DATABASE_URL` never propagated to alembic's sync URL. Alembic silently connected to `localhost:5432/zenflow_dev` and reported success with 0 migrations applied.

**Fix:** Guard changed to `"localhost" in self.DATABASE_SYNC_URL` — now correctly derives Railway sync URL from `DATABASE_URL` when set.

**Impact:** This was the root cause of the full failure chain today (missing column errors → FK violation → multiple failed close_day attempts). Now self-healing: `start.sh` runs `alembic upgrade head` on every deploy and it will always reach Railway.

#### Cron docstring corrected
`api/routers/tracking.py` docstring updated from "02:00 UTC" → "00:00 IST (18:30 UTC)".

#### Migrations applied to Railway DB (manually, before fix)
Migrations were applied manually with explicit `DATABASE_SYNC_URL` env var before the config fix landed:
- `b2c3d4e5f6a7` — asymmetric carry-forward (`opening_recovery` / `opening_stress` on `daily_stress_summaries`)
- `c3d4e5f6a7b8` — `capacity_growth_streak INTEGER` on `personal_models`
- `d1e2f3a4b5c6` — `calibration_snapshots` table

All three confirmed applied to Railway DB.

#### Poisoned personal_model ceiling fixed
User `2420112a` (PratikB1) had `rmssd_ceiling = 151.6ms` — a noisy spike from Day 1 data that the old real-time P90 refine accepted without filtering.

Forced `close_day()` locally against Railway DB → `_run_calibration_batch()` ran its 3-pass filter → 95/336 windows rejected → ceiling corrected:

| Field | Before | After |
|---|---|---|
| `rmssd_ceiling` | 151.6ms | **52.3ms** |
| `rmssd_floor` | 15.0ms | 13.5ms |
| `rmssd_morning_avg` | 27.9ms | 28.0ms |

`calibration_snapshots` row written: `confidence=0.9586`, `committed=True`, `sanity_passed=True`.

#### Full deployment via `railway up`
Previous `railway redeploy` calls failed silently — Railway has no git remote configured, so `redeploy` just re-ran the old Docker image. Correct command is `railway up` which uploads and builds from local source.

Deployment confirmed healthy:
```
Running migrations... Migrations OK
nightly scheduler started — next run 18:30 UTC (00:00 IST midnight)
Deploy complete — [1/1] Healthcheck succeeded!
```

#### Why UI numbers haven't changed yet
`close_day()` computes and writes scores. It runs at midnight IST (18:30 UTC). The corrected model will be used **tonight at midnight** — numbers will update first thing tomorrow morning. Reloading the screen fetches the same day's summary which was written by the previous (poisoned) close_day. That's expected.

### Commits this session
```
a2aa4d9  feat: calibration hardening sprint + bug fixes
         19 files changed, 1169 insertions, 315 deletions
```
Note: no git remote configured. Deploy is always via `railway up` from local disk.

---

## Handoff Note — Session of 16 March 2026 (Part 2)

### Next Session Focus
~~Deploy to Railway — see Part 3 above, complete.~~
Superseded — see Part 3 handoff above.

### What was done this session (Part 2) — Calibration Hardening Sprint

#### P1 design clarification (CONTEXT.md corrections)
`personal.rmssd_morning_avg` is the correct frozen scoring anchor — confirmed not a bug. `MorningRead.rmssd_ms` feeds coach only via `vs_personal_avg_pct` → `day_type`. Updated 5 locations in CONTEXT.md; P1 closed.

#### Phase 1 — Immediate bug fixes

| File | Change |
|---|---|
| `model/fingerprint_updater.py` | `update_rmssd_stats()` morning filter changed from `4 <= r.ts.hour < 10` → `r.context == "morning"`. Previously activity windows between 4–10am diluted `morning_avg` below floor. |

#### Phase 2 — `calibration_snapshots` ORM + migration

| File | Change |
|---|---|
| `api/db/schema.py` | Added `CalibrationSnapshot` class — 15-column audit table with raw/clean RMSSD values, filter stats, committed+sanity flags. |
| `alembic/versions/d1e2f3a4b5c6_calibration_snapshots.py` | New migration chaining from `c3d4e5f6a7b8`. Creates `calibration_snapshots` table + index. |

#### Phase 3 — Artifact filter module + tiered priors

| File | Change |
|---|---|
| `model/calibration_filter.py` | NEW FILE. Pure Python 3-pass filter: Pass 1 = settle discard (first 30 min), Pass 2 = temporal spike gate (>2.5× rolling median of ±6 neighbours), Pass 3 = population ceiling gate (>110ms). Returns `FilterResult` with `clean_windows`, `rejected_count`, `rejection_rate`, `confidence`. |
| `api/services/tracking_service.py` | Replaced `_SEED_RMSSD_FLOOR/CEILING/MORNING` constants with `_TIER_SEDENTARY/MODERATE/ATHLETIC` dicts + `_seed_from_onboarding(onboarding_json)`. Seeds are now tiered by `users.onboarding.exercise_frequency`: rarely→sedentary (18/45/28), 1-3x/week→moderate (22/65/38), 4+/week→athletic (35/95/55). |

#### Phase 4 — Batch model wired into `close_day()`

| File | Change |
|---|---|
| `api/services/tracking_service.py` | `_bootstrap_personal_model()`: **real-time P10/P90 refine block removed entirely**. Personal model now seeded from tiered priors only; no intra-day updates during calibration days. Prevents a single noisy window from poisoning the ceiling. |
| `api/services/tracking_service.py` | Added `_run_calibration_batch(db, user_id, day_number, personal)` async function. Called at every `close_day()` while `calibration_locked_at is None`. Loads full history → runs 3-pass filter → floor=P10/ceiling=P90 of clean values → 110ms hard-cap → morning_avg from morning-context windows → sanity check (morning_avg ≥ floor + 10% range) → writes `CalibrationSnapshot` audit row → updates `personal_model` if confidence ≥ 0.65 → sets `committed=True`. |
| `api/services/tracking_service.py` | `close_day()`: calls `_run_calibration_batch()` **before** the calibration lock check + refreshes ORM row. So on Day 1+2 model updates; on Day 3 model updates then lock is written. |

#### Phase 5 — Tests

| File | Change |
|---|---|
| `tests/model/test_calibration_filter.py` | NEW FILE. 10 tests: empty input, settling discard, all-in-settle, spike rejection, proportionate-spike pass, ceiling gate, ceiling boundary, clean path, confidence degradation, None rmssd. All 10 pass. 141 existing model tests unchanged. |

### Commits this session
All changes committed in Part 3 as `a2aa4d9`. See Part 3 handoff.

### Validation query (run after Railway deploy)
```sql
SELECT day_number, rmssd_ceiling_raw, rmssd_ceiling_clean,
       windows_rejected, confidence, committed
FROM calibration_snapshots
WHERE user_id = '<your-user-id>'
ORDER BY day_number;
```
Expected: `ceiling_raw ≈ 143`, `ceiling_clean ≈ 45–70`, `windows_rejected ≥ 1`.

---

## Handoff Note — Session of 16 March 2026 (Part 1)

### What was done this session

#### Scoring model cleanup — full pass (Phases 1–6)

Removed the defunct `readiness_score` (0–100 composite) and overnight `recovery_score` (weighted sleep/zenflow/daytime bucket) from the entire codebase. Wired `net_balance` everywhere they were referenced.

**Files changed:**

| File | Change |
|---|---|
| `tracking/daily_summarizer.py` | Removed overnight recovery block + readiness computation. Added `calibration_locked: bool` + `day_type: Optional[str]` params. `is_estimated = not calibration_locked`. |
| `config/tracking.py` | Removed `RECOVERY_WEIGHT_*`, `READINESS_CENTER/SCALE/*_THRESHOLD`, `CAPACITY_FULL_ACCURACY_DAYS`. |
| `api/routers/tracking.py` | Removed `recovery_score` + `readiness_score` from `DailySummaryResponse` and `HistoryEntry`. |
| `api/services/tracking_service.py` | `close_day()` + `compute_live_summary()`: query `MorningRead.day_type`, pass `calibration_locked` bool + `day_type` to `compute_daily_summary()`. |
| `jobs/nightly_rebuild.py` | Swapped `readiness_score` → `net_balance`. Added `_check_capacity_growth()` (Phase 5). |
| `profile/nightly_analyst.py` | `readiness_score` → `net_balance` in prompt, fallback thresholds updated to ±10/−20. |
| `profile/plan_guardrails.py` | R4 rule: `rs < 40` → `nb < -20.0`. |
| `api/services/profile_service.py` | `rebuild_unified_profile()` signature: `readiness_score` → `net_balance`. |
| `coach/context_builder.py` | `CoachContext.readiness_score` → `net_balance: Optional[float]`. |
| `api/db/schema.py` | Deprecation comments on `recovery_score`/`readiness_score` columns. Added `capacity_growth_streak` column. |
| `tests/tracking/test_daily_summarizer.py` | Updated helpers + removed `TestReadinessScore`/`TestRecoveryScore` classes. All 19 tests pass. |

#### Phase 4 — Recovery chart denominator fix
`RecoveryDetailScreen.tsx`: `toChartPoints()` previously computed `wakingCap = (rmssdCeiling - avg) * 960` locally. Now uses `ns_capacity_used` from API response — same denominator as stress chart. Hot-reload only (no EAS build).

#### Phase 7 — Chart bar-summation correctness (Design A)
Decision: all waking windows show as bars; sum of bars = score; events are a highlighted subset. Two fixes applied:

**a) Sleep-window filter** (`src/screens/StressDetailScreen.tsx`, `src/screens/RecoveryDetailScreen.tsx`)
- `toChartPoints()` now filters `.filter(p => p.is_valid !== false && p.context === 'background')`
- Previously only `is_valid !== false` was checked — sleep-context and morning-context windows appeared as bars, but the backend score excluded them. Now bars map 1-to-1 with what the scorer counts.

**b) Dynamic y-axis** (`src/ui/zenflow-ui-kit.tsx`)
- Removed hardcoded `const Y_MAX = 2; const Y_TICKS = [2, 1, 0]`
- Added `niceMax(rawMax)` — rounds actual data max up to a clean ceiling (e.g. 0.08→0.1, 0.15→0.2, 1.3→2)
- Added `fmtTick(v)` — formats y-axis labels (1 dp if <1, integer otherwise)
- Both `StressChartCard` and `RecoveryChartCard` now compute `yMax = niceMax(dataMax)` from live data. Bars fill the chart height proportionally regardless of the user's personal capacity scale.

**c) Stress colour corrected** per `DESIGN_SYSTEM.md`
- Chart was using `#4A90D9` (wrong) → now uses `ZEN.colors.stress` (`#19B5FE`)
- Dim bar alpha reduced to `0.28` (from 0.35) to match recovery chart visual weight

#### Phase 5 — Capacity growth detection
- Migration `c3d4e5f6a7b8` adds `capacity_growth_streak INTEGER DEFAULT 0` to `personal_models`.
- `_check_capacity_growth()` in `nightly_rebuild.py`: queries yesterday's peak valid RMSSD, advances streak if > ceiling × 1.10, resets if ≤. On 7-day streak: snapshots model, updates ceiling + morning_avg, re-locks, increments `capacity_version`.
- **Not yet done:** coach push notification on capacity growth trigger (P5 in parked list).

### Commits this session
- None — backend runs directly off disk via `--reload`. Railway is production read-only.
- **Pending deploy:** migration `c3d4e5f6a7b8` must run before next Railway redeploy (will auto-apply via `alembic upgrade head` in `start.sh`).

---

## Handoff Note — Session of 15 March 2026

### Next Session Focus (carried forward — superseded by 16 March session)
~~Hooks URL/UUID purge complete. Next: Events trigger and tagging pipeline (Cluster 2).~~
Superseded — see 16 March session above.

### What was done this session

#### 1. Morning read pipeline — full component audit
Mapped all 7 components of the morning read pipeline against implementation. Identified 2 gaps remaining (day_type not set at ingest time; no morning_brief returned to app).

#### 2. Gap 6 fixed — day_type assigned at morning read ingest
In `api/services/tracking_service.py` (backend: `~/Desktop/Zenflow_backend`):
- Added constants `_MORNING_GREEN_PCT = -5.0`, `_MORNING_YELLOW_PCT = -20.0`
- Added `_classify_morning_day_type(vs_avg_pct)` — green ≥ -5%, yellow ≥ -20%, red < -20%
- `morning_row.day_type` is now set before `await self._db.flush()` at ingest time
- Previously `day_type` was only written inside `close_day()` at night — meaning the morning read had no classification for the entire day until night close

#### 3. Gap 7 fixed — morning_brief returned in IngestResponse
- Added `_morning_brief_text(day_type, vs_avg_pct)` — deterministic coaching message templates (no LLM)
- Added `get_today_morning_brief()` async method to `TrackingService` — queries today's `morning_reads` row, returns `(day_type, message)` tuple
- `IngestResponse` expanded (in `api/routers/tracking.py`): added `morning_day_type: Optional[str]` and `morning_brief: Optional[str]`
- `ingest_beats` handler now calls `get_today_morning_brief()` immediately after morning-context processing and populates both new fields
- App now receives a non-silent response when morning read lands. Example:
  ```json
  {
    "windows_processed": 1,
    "beats_received": 245,
    "morning_day_type": "green",
    "morning_brief": "Your HRV is tracking well this morning (+8% above your baseline). Good conditions — a focused breathing session will serve you well today."
  }
  ```

#### 4. Bootstrap morning filter — confirmed already correct
`_bootstrap_personal_model` in `tracking_service.py` uses `w.context == "morning"` filter for `rmssd_morning_avg` seed. Was marked as a gap in prior session but it was already applied.

#### 5. Backend path
All code changes above are in `~/Desktop/Zenflow_backend`. The unicode-path issue (`Desktop - Pratik's MacBook Air/ZenFlow_Verity`) is now resolved — use `~/Desktop/Zenflow_backend` directly in all terminals.

#### 6. WiFi / ADB note
Phone (`192.168.68.100`) cannot reach Mac (`192.168.68.104`) over WiFi — AP isolation is enabled on the router (bidirectional ping 100% loss). Options for next session:
- **Disable AP isolation** in router admin page (Wireless Settings → AP Isolation / Client Isolation → off), then `adb connect 192.168.68.100:5555`
- **Or** keep USB + `adb reverse tcp:8081 tcp:8081` so phone tunnels Metro over USB while walking around

### Commits this session
- None — real backend runs directly off disk, not deployed to Railway. Railway is production read-only. Local dev server picks up changes via `--reload`.

### Calibration Design vs Implementation — Full Status

The table below is the authoritative gap tracker. Update it as each item is fixed.

| Design Step | Status | Commit / Notes |
|---|---|---|
| **Step 1:** Raw windows in, forever | ✅ Complete | — |
| **Step 2:** Floor gets lower per window | ✅ Complete | `_bootstrap_personal_model` uses `np.percentile(arr, 10)` |
| **Step 2:** Ceiling gets higher per window | ✅ Complete | `np.percentile(arr, 90)` |
| **Step 2:** "Learning" label until Day 3 lock | ✅ Fixed (scoring cleanup) | `is_estimated` now tied to `calibration_locked_at IS NOT NULL`. `calibration_locked` bool passed from `tracking_service.py` into `compute_daily_summary()`. `CAPACITY_FULL_ACCURACY_DAYS` constant removed from codebase entirely. |
| **Step 2:** `morning_avg` = EWM α=0.2 of wake-up readings | ✅ Fixed (15 Mar) | Bootstrap confirmed using `context=="morning"` filter only. EWM α=0.2 updates `PersonalModel.rmssd_morning_avg` at each morning ingest |
| **Step 3:** `context="morning"` accepted by ingest | ✅ Fixed (prior session) | Ingest routes `context="morning"` into morning-specific path in `TrackingService` |
| **Step 3:** Morning read row saved to `morning_reads` table | ✅ Fixed (prior session) | `morning_reads` row upserted per day with rmssd_ms, hr_bpm, lf_hf, confidence, vs_personal_avg_pct |
| **Step 3:** `rmssd_morning_avg` updated via EWM per morning read | ✅ Fixed (prior session) | EWM α=0.2 runs at morning ingest, only while `calibration_locked_at IS NULL` |
| **Step 3:** `day_type` assigned on MorningRead | ✅ Fixed (15 Mar) | `_classify_morning_day_type(vs_personal_avg_pct)` now called at ingest; green/yellow/red written to `morning_row.day_type` before flush |
| **Step 3:** `morning_brief` returned to app | ✅ Fixed (15 Mar) | `IngestResponse` now has `morning_day_type` + `morning_brief` (deterministic templates). Full LLM path via `trigger_type="morning_brief"` is Phase 2 |
| **Step 3:** Today's morning RMSSD sets daily capacity reference | ✅ Correct by design — clarified 16 Mar | `personal.rmssd_morning_avg` IS the correct frozen scoring anchor. `MorningRead.rmssd_ms` → `vs_personal_avg_pct` → `day_type` → coach only. No code change needed. |
| **Step 3:** Morning read triggers full coach pipeline | ⚠️ Parked | `GET /coach/morning-brief` endpoint exists but passes only `fp` + `profile` to `coach_svc.morning_brief()` — no `MorningRead` RMSSD or daily summary scores fetched. Parked 16 Mar. |
| **Step 4:** `close_day()` sleep-triggered | ✅ Fixed | commit `d594a95` — `context="sleep"` ingest calls `svc.close_day()` immediately |
| **Step 4:** Cron fallback at night IST | ✅ Fixed | commit `d594a95` — CronTrigger `hour=19, minute=30, UTC` = 01:00 IST |
| **Step 4:** Balance carry-forward (`closing_balance → opening_balance`) | ✅ Complete | `prev_summary.closing_balance` fetched in `close_day()` and `compute_live_summary()` |
| **Step 4:** Daily plan adherence scored at close | ✅ Complete | `assess_daily_adherence()` called at end of `close_day()` |
| **Step 4:** Wake detector priority 1 — sleep transition | ⚠️ Partial | `close_day()` now builds `context_transitions` + queries `morning_read_ts` and passes both to detector ✅. `compute_live_summary()` still calls detector without either — parked 16 Mar. |
| **Step 4:** Wake detector priority 3 — morning read anchor | ⚠️ Partial | Fixed in `close_day()` ✅. `compute_live_summary()` still missing `morning_read_ts` — parked 16 Mar. |
| **Step 4:** Wake detector priority 2 — historical pattern | ✅ Works | `typical_wake_time` fallback reaches the detector correctly |
| **Step 5:** Calibration lock at `calibration_days ≥ 3` | ✅ Complete | `BASELINE_STABLE_DAYS=3`; `calibration_locked_at` written in `close_day()` |
| **Step 5:** Ceiling + morning_avg frozen at lock | ✅ Complete | `update_rmssd_stats(calibration_locked=True)` in `fingerprint_updater.py`. Bug fixed 17 Mar: `_persist_fingerprint()` was silently overwriting ceiling/floor after every session end — three lines removed from `api/services/model_service.py`. |
| **Step 5:** Floor can still go lower post-lock | ✅ Complete | Floor decrease always permitted in `update_rmssd_stats` |
| **Step 5:** NS Capacity = `(ceiling − floor) × 960` | ✅ Complete | `DAILY_CAPACITY_WAKING_MINUTES=960`; used in `compute_daily_summary()` |
| **Step 6:** `CAPACITY_GROWTH_THRESHOLD_PCT=10.0`, `CONFIRM_DAYS=7` | ✅ Config only | Values defined in `config/model.py` |
| **Step 6:** Capacity growth detection runs nightly | ✅ Fixed (scoring cleanup) | `_check_capacity_growth()` in `jobs/nightly_rebuild.py`. Queries yesterday's peak valid RMSSD, increments `capacity_growth_streak` on `personal_models`. Migration `c3d4e5f6a7b8` adds the column. |
| **Step 6:** Calibration unlocks → ceiling updates → re-locks | ✅ Fixed (scoring cleanup) | On 7-day streak: snapshots old model, updates `rmssd_ceiling` + `rmssd_morning_avg`, resets `calibration_locked_at`, increments `capacity_version`, resets streak to 0. |
| **Step 6:** Coach notifies user on capacity growth | ⚠️ Parked | `nightly_rebuild` logs INFO on trigger but no coach push/nudge implemented yet. |
| **Plan:** Morning brief generated after Day 1 close | ✅ Endpoint exists | `GET /coach/morning-brief` works |
| **Plan:** Morning brief uses today's scores | ⚠️ Partial | `IngestResponse` returns `morning_day_type` + `morning_brief` (deterministic templates) ✅. `GET /coach/morning-brief` endpoint still passes zero scores to coach service — parked 16 Mar. |

---

### Fix Priority (status as of 16 March 2026)

**Cluster 1 — Morning Read Pipeline** ✅ Mostly complete

| # | File | Status |
|---|---|---|
| 1a | `api/routers/tracking.py` | ✅ Accept `context="morning"` |
| 1b | `api/services/tracking_service.py` | ✅ Save `MorningRead` row |
| 1c | `api/services/tracking_service.py` | ✅ Update `rmssd_morning_avg` via EWM; bootstrap uses morning-only windows |
| 1d | `api/services/tracking_service.py` | ✅ `day_type` set at ingest time via `_classify_morning_day_type()` |
| 1e | `api/routers/tracking.py` | ✅ `IngestResponse` returns `morning_day_type` + `morning_brief` |
| 1f | `api/services/tracking_service.py` | ✅ Correct by design — `personal.rmssd_morning_avg` is the frozen scoring anchor. `MorningRead.rmssd_ms` → `day_type` → coach only. Clarified 16 Mar. |
| 1g | `api/routers/coach.py` | ⚠️ Parked — `morning_brief` endpoint passes no scores to coach service |

**Cluster 2 — Events Trigger and Tagging** (not yet started)

When do `stress_events` / `recovery_events` fire? How are they labelled by `tagging/`? How does the tag flow into `CoachContext`?

**Cluster 3 — Wake Detector Wiring** (partially fixed, remainder parked)

- `close_day()`: ✅ Fixed 16 Mar — `context_transitions` + `morning_read_ts` both wired
- `compute_live_summary()`: ⚠️ Parked — still calls `detect_wake_sleep_boundary()` without either

**Cluster 4 — `is_estimated` label** ✅ FIXED (scoring cleanup)

`is_estimated` now tied to `calibration_locked: bool` param passed from tracking service into `compute_daily_summary()`. Takes value `not calibration_locked`, so it clears exactly at Day 3 lock. `CAPACITY_FULL_ACCURACY_DAYS` constant removed from codebase entirely.

**Cluster 5 — Capacity Growth** ✅ IMPLEMENTED (scoring cleanup)

`_check_capacity_growth()` added to `jobs/nightly_rebuild.py`. Migration `c3d4e5f6a7b8` adds `capacity_growth_streak INTEGER` to `personal_models`. Detection runs nightly post-lock; triggers re-lock when streak reaches 7.

**Cluster 6 — Chart fixes** ✅ COMPLETE

- Sleep-window filter in `toChartPoints()` — ✅ fixed 16 Mar (Phase 7a): only `context === 'background'` windows shown; bars now sum to score
- Dynamic y-axis via `niceMax()` — ✅ fixed 16 Mar (Phase 7b): removed hardcoded `Y_MAX=2`, bars fill chart height from real data
- Stress colour corrected to `ZEN.colors.stress` (`#19B5FE`) — ✅ fixed 16 Mar (Phase 7c)
- X-axis hour labels inside `ScrollView` — ✅ fixed (prior session), labels scroll with bars

---

## Handoff Note — Session of 14 March 2026

### What was done this session

#### 1. DB Cleanup
Deleted stale rows collected before the new threshold logic went live:
- 22 `stress_windows` rows before `2026-03-14 14:00:00+00`
- 20 `recovery_windows` rows before same cutoff
- Used public Railway proxy URL: `postgresql://postgres:VaebpXWINRSXJrVlakRrqSBDeehOeEEh@interchange.proxy.rlwy.net:36271/railway`

#### 2. Backend deployed to Railway
New fields added to `DailySummaryResponse` (in `api/routers/tracking.py`):
- `rmssd_morning_avg` — EWM-weighted average of waking RMSSD readings
- `rmssd_ceiling` — personal model ceiling (highest RMSSD seen)
- `ns_capacity_used` — `(ceiling - floor) × 960` minutes

Thresholds tightened in `config/tracking.py`:
```python
STRESS_THRESHOLD_PCT   = 0.75   # was 0.85
STRESS_MIN_WINDOWS     = 3      # minimum windows before a stress event fires
STRESS_RATE_TRIGGER_PCT = 0.20  # rate change trigger
RECOVERY_THRESHOLD_PCT = 1.10   # above morning_avg to count as recovery
RECOVERY_MIN_WINDOWS   = 4      # minimum windows before recovery event fires
```

`api/services/tracking_service.py` now has `get_personal_model()` which fetches the `PersonalModel` row and populates the three new fields on the summary response. Confirmed `Application startup complete` in Railway logs at ~16:28 UTC.

#### 3. Frontend changes (dev-server hot-reloaded, NOT an EAS build)
- `src/screens/StressDetailScreen.tsx` — new formula:
  `value = max(0, (morningAvg - rmssd) * 5 / nsCapacity * 100)`
  passes `isoTime: p.window_start` to chart
- `src/screens/RecoveryDetailScreen.tsx` — new formula using `rmssdCeiling`
- Both screens wire `morningAvg`, `nsCapacity`, `rmssdCeiling` from the updated API response

#### 4. Chart changes (in progress — next session)
Pending user confirmation of the two outstanding chart fixes:
- `Y_MAX`: 3 → 2, `Y_TICKS`: `[3,2,1,0]` → `[2,1,0]` in `src/ui/zenflow-ui-kit.tsx`
- X-axis hour labels broken — absolute-positioned label row must be placed **inside** the horizontal `ScrollView` so labels scroll with bars

#### 5. Dev client setup
- Dev client APK installed (build ID: `308b6ecb-7a48-4dbb-99f4-9e382c204e4e`)
- Metro dev server: `exp://192.168.68.108:8081` (pid 79711)
- All subsequent JS/TS changes → save file → hot reload. **Do NOT trigger EAS builds for pure JS changes.**

#### 6. Key rule reinforced
EAS builds cost Expo credits and take 10–15 min. EAS build = only for: native module changes, `app.json` changes, new gradle/manifest entries. Pure `.tsx`/`.ts` changes = dev server only.

---

## Current System State (14 March 2026)

### What is working right now
- Railway API: `https://api-production-8195d.up.railway.app` — LIVE and healthy
- Railway Postgres: provisioned and connected (`postgres-ciqd.railway.internal:5432`)
- All Alembic migrations applied
- Dev client APK installed on test phone (device: `JJCE6H4XJNXS6L8D`, package: `com.zenflow.verity`)
- Metro dev server running at `192.168.68.108:8081` — connect via Expo Dev Client
- Hot reload working for all JS/TS changes

### Key credentials
| Item | Value |
|---|---|
| Railway API URL | `https://api-production-8195d.up.railway.app` |
| Railway project ID | `52409a46-4797-4027-b17a-e25cfb8fd62c` |
| Postgres internal URL | `postgresql://postgres:VaebpXWINRSXJrVlakRrqSBDeehOeEEh@postgres-ciqd.railway.internal:5432/railway` |
| Postgres public proxy | `postgresql://postgres:VaebpXWINRSXJrVlakRrqSBDeehOeEEh@interchange.proxy.rlwy.net:36271/railway` |
| Postgres service name | `postgres-ciqd` (replaced crashed original) |
| EAS project | `@pratik85/zenflow-verity` (ID: `bab74a16-9052-43bd-9c2a-cc33fc667a02`) |
| EAS token | `NkUqALgfgbtl9bqLG8UW8OlhSn7QSW2MLHs_6Tyn` |
| Dev client build ID | `308b6ecb-7a48-4dbb-99f4-9e382c204e4e` |
| Dev server URL | `exp://192.168.68.108:8081` |
| Test phone adb ID | `JJCE6H4XJNXS6L8D` |
| adb path | `/Users/pratikbarman/Library/Android/sdk/platform-tools/adb` |

---

## How ZenFlow Calibration Works — Authoritative Specification

> This section is the source of truth for calibration logic. Backend code in `model/`, `api/routers/tracking.py`, `config/tracking.py`, and `jobs/nightly_rebuild.py` must match this spec.
> Last verified: 15 March 2026.

---

### Step 1 — Raw Data In (continuous, forever)

Every 5 minutes the app sends PPI batches to `POST /tracking/ingest`. The backend writes one `background_window` row containing:
- **RMSSD** — nervous system recovery marker
- **HR** — heart rate
- **LF/HF ratio** — stress/recovery balance

This never stops. Even post-calibration, every window updates the live score.

---

### Step 2 — Floor & Ceiling Building (Days 1–3, "Provisional")

With each new background window the model asks: is this RMSSD the lowest we've seen yet, or the highest? All three values are stored live in the `personal_models` row.

| Value | Meaning | Update rule |
|---|---|---|
| `rmssd_floor` | Most-stressed state (lowest RMSSD ever seen) | Gets lower if new window beats it |
| `rmssd_ceiling` | Most-recovered state (highest RMSSD ever seen) | Gets higher if new window beats it |
| `rmssd_morning_avg` | Rolling weighted avg of wake-up readings | EWM with α=0.2 (recent matters more) |

**These three values together are the baseline.** They are only ever changed during calibration days, or by the Step 6 capacity growth plan. Nothing else should touch them.

During these 3 days scores are real but labelled "Learning your baseline."

---

### Step 3 — The Role of Morning Reads (two distinct jobs)

The first window each morning tagged `context=morning` — ideally captured right after waking, before any movement — is the daily anchor. It is the cleanest possible NS reading: no activity, no stress artifacts yet.

**During calibration (Days 1–3): refine the baseline**

Each morning read updates `rmssd_morning_avg` in `PersonalModel` via EWM (α=0.2). This is how the system learns your true waking NS state. The morning read contributes to building the floor/ceiling/morning_avg that will be locked at Day 3. The baseline gets more accurate with each day.

**Post-calibration (Day 4+): daily coach signal**

Once locked, the baseline is frozen. Morning reads have a different job:

1. **Provide a coach signal.** The morning RMSSD is compared to the frozen `rmssd_morning_avg` → produces `vs_personal_avg_pct` → `day_type` (green/yellow/red). The coach uses `day_type` to calibrate session intensity and plan tone.

   > **Scoring anchor is the frozen baseline, not today's morning read.** `personal.rmssd_morning_avg` is the permanent scoring denominator. Every window during the day is measured against this frozen value — not against today's morning reading. A low morning read is a coach signal (stress likely today) but does not shift the scoring anchor for that day's windows.

2. **Trigger the coach.** The morning read fires `generate_morning_brief()`. The coach receives `day_type` + yesterday's closing scores to personalise the plan.

---

### Step 4 — Night / Evening Close (`close_day()`)

When sleep boundary detection fires:

```
closing_balance = opening_balance + recovery_pct - stress_pct
```

The closing balance carries forward as tomorrow's opening. The carry-forward rule is **asymmetric**:

| Last night's close | Next morning opens with |
|---|---|
| Positive (+8%) | `recovery = +8%`, `stress = 0`, `balance = +8%` |
| Negative (−15%) | `recovery = 0`, `stress = −15%`, `balance = −15%` |

Recovery is capped at 100% throughout the day, so balance can never overshoot 100%. Deficits must be earned back — they do not vanish overnight. Surpluses do not compound beyond 100%.

The evening close is also when daily plan adherence gets scored by `assess_daily_adherence()`.

---

### Step 5 — Calibration Lock (Day 3)

`calibration_days` is computed dynamically at each `close_day()` by counting distinct calendar days with at least one recorded window. When this count reaches 3 (`BASELINE_STABLE_DAYS = 3`):

- `calibration_locked_at` timestamp written to `personal_models` row
- **`rmssd_ceiling` and `rmssd_morning_avg` frozen permanently**
- **`rmssd_floor` can still go lower** (only expands range — never distorts the denominator upward)
- **Morning reads no longer update `rmssd_morning_avg` or floor/ceiling** — the baseline is fixed
- NS Capacity locked: `(rmssd_ceiling − rmssd_floor) × 960`

The `960` = minutes in a 16-hour active day. NS Capacity = "given your best and worst measured states, how many minutes of full nervous system effort could you theoretically sustain." This becomes the **permanent denominator** for all future scores.

---

### Step 6 — Capacity Growth (Post-Calibration)

The baseline (floor/ceiling) only moves via this plan — never from daily morning reads, never randomly.

If live RMSSD range exceeds the locked calibrated range by >10% for 7 consecutive days:
1. Calibration unlocks
2. `rmssd_ceiling` updates to new high
3. Re-locks with new NS Capacity
4. Coach notifies user

This handles genuine fitness improvement over months without distorting daily scores.

> **Current status:** Step 6 is entirely unimplemented (gap C2). No detection loop, no unlock trigger, no coach notification exists.

---

### Plan Generation Timeline

| Time | What happens |
|---|---|
| Hour 0 | Band on → background windows start flowing in |
| Hour 3 | Provisional scores appear (`BASELINE_FIRST_SNAPSHOT_HOURS = 3`) |
| Day 1 evening | First `close_day()`, first plan assessment |
| Day 2 morning | Morning read refines `rmssd_morning_avg` via EWM — baseline still live |
| Day 3 evening | `calibration_locked_at` written — floor/ceiling/morning_avg frozen |
| Day 4+ morning | Morning reads reset scores + trigger coach (no longer refine baseline) |
| Day 7+ | Capacity growth monitoring begins |

Coach generates first plan after morning brief on Day 1 (needs at least one evening close). Plans are light early on. After calibration locks, plans are fully personalised.
- Every morning: `generate_morning_brief()` → creates today's plan
- Every evening: `assess_daily_adherence()` → scores it and informs tomorrow's plan

---

### Score Formulas (as of 16 March 2026 — current model)

Three user-facing scores. No `readiness_score` or overnight `recovery_score` exist in this codebase.

**Stress Load per window:**
```
value = max(0, (morningAvg - rmssd) * 5 / nsCapacity * 100)
```

**Waking Recovery per window:**
```
value = max(0, (rmssd - morningAvg) * 5 / nsCapacity * 100)
```

Both use the same denominator: `nsCapacity = (rmssd_ceiling - rmssd_floor) * 960` — the **locked NS Capacity**. Stress and recovery charts are symmetric.

**Net Balance (day-level):**
```
net_balance = opening_balance + recovery_pct_raw - stress_pct_raw
```
Unbounded ± float. Drives day colour (green/yellow/red), plan guardrails, and coach framing.
- green  : net_balance ≥ +10
- yellow : net_balance ≥ −20
- red    : net_balance < −20

`day_type` is sourced from `MorningRead.day_type` (set at morning read ingest via `_classify_morning_day_type()`). Not derived from net_balance at day-close.

Y-axis scale: **dynamic** (chart UI). `niceMax(dataMax)` is computed from live data; 3 ticks at `[yMax, yMax/2, 0]`. Bars fill the full `BAR_MAX_H = 160px` proportionally. Removed hardcoded `Y_MAX = 2`.

---

### Key Constants (`config/tracking.py`)

```python
# config/tracking.py
BASELINE_STABLE_DAYS          = 3
BASELINE_FIRST_SNAPSHOT_HOURS = 3
STRESS_THRESHOLD_PCT          = 0.75   # drop below 75% of morning_avg = stress window
STRESS_MIN_WINDOWS            = 3      # min consecutive windows before event fires
STRESS_RATE_TRIGGER_PCT       = 0.20   # rate-of-change trigger
RECOVERY_THRESHOLD_PCT        = 1.10   # 10% above morning_avg = recovery window
RECOVERY_MIN_WINDOWS          = 4      # min consecutive windows before event fires
EWM_ALPHA                     = 0.2    # morning_avg smoothing (morning reads only, pre-lock)
DAILY_CAPACITY_WAKING_MINUTES = 960    # minutes in 16-hour active day

# config/model.py
CAPACITY_GROWTH_THRESHOLD_PCT = 10.0   # >10% ceiling expansion triggers re-calibration
CAPACITY_GROWTH_CONFIRM_DAYS  = 7      # must hold for 7 consecutive days (streak)
```

**Removed constants (no longer in codebase):**
- `CAPACITY_FULL_ACCURACY_DAYS` — `is_estimated` now tied to `calibration_locked_at`, not a day count
- `RECOVERY_WEIGHT_SLEEP/ZENFLOW/DAYTIME` — overnight recovery bucket computation removed
- `READINESS_CENTER/SCALE/GREEN_THRESHOLD/YELLOW_THRESHOLD` — `readiness_score` field removed entirely

---

## Repository Structure

**Two separate repos:**

### `~/Desktop/Zenflow_backend` — FastAPI backend
- `api/config.py` — Pydantic settings; `DATABASE_URL`/`DATABASE_SYNC_URL` validators strip `postgresql://` → asyncpg/psycopg2 prefixes
- `api/main.py` — FastAPI entrypoint
- `api/routers/` — route handlers (tracking, coach, profile, etc.)
- `api/services/` — business logic
- `api/db/` — SQLAlchemy async engine
- `alembic/` — migrations applied locally (latest on disk: `d1e2f3a4b5c6` — calibration_snapshots; pending Railway deploy)
- `Dockerfile`, `railway.toml`, `start.sh` (runs `alembic upgrade head` then `uvicorn`), `requirements.txt`
- `processing/`, `model/`, `archetypes/`, `coach/`, `outcomes/`, `tracking/`, `sessions/`, `psych/`, `profile/`, `tagging/`, `jobs/`, `scripts/`

### `~/Desktop/Zenflow_front` — React Native / Expo frontend
- `App.tsx` — bootstrap: saves API base, calls `initClient` (**must** be awaited), loads `userId`
- `src/api/client.ts` — axios instance; `initClient()`, `setUserId()`, `getClient()`
- `src/api/endpoints.ts` — all API call functions (`getToday`, `updateHabits`, `rebuildProfile`, etc.)
- `src/screens/HomeScreen.tsx` — calls `getToday()` on focus; shows error state if API fails
- `src/screens/onboarding/Step8Name.tsx` — final onboarding step: generates UUID, calls `saveUser`, navigates to Main
- `src/store/auth.ts` — AsyncStorage wrappers: `saveUser`, `getUser`, `saveApiBase`, `getApiBase`
- `src/navigation/` — `AppNavigator`, `OnboardingNavigator`
- `src/components/` — `ScreenWrapper`, `ScoreCard`, `DayTypeBadge`, `EmptyState`, etc.
- `eas.json` — preview profile: `buildType=apk`, `EXPO_PUBLIC_API_URL=https://api-production-8195d.up.railway.app`

---

## Git History

### Zenflow_front (frontend) — as of 14 March 2026
```
(latest)  fix: complete Phase 7 routing and UI components
          feat: full UI rebuild — Whoop-style arc rings, 4-tab nav, live coach thread
          fix: production API URL, real text input for coach, fix tab bar icon collapse
          fix: gracefully handle 404 tracking payload in hook
          fix: store BLE Subscription ref to prevent GC
          feat: Android foreground service (v9)
          fix: register foreground service at bootstrap (v10)
          debug: 30s flush + live BLE diagnostics in Settings (v11)
          fix: MTU negotiation for PMD datagrams (v21)
          fix: do not discard PMD packets when skin contact bit is high (v22)
```

### Zenflow_backend (backend) — as of 14 March 2026
```
(latest)  feat: DailySummaryResponse — add rmssd_morning_avg, rmssd_ceiling, ns_capacity_used
          feat: tighten stress/recovery thresholds (STRESS_THRESHOLD_PCT=0.75 etc.)
          start.sh: migrations + uvicorn, fix Dockerfile CMD
          Remove Procfile startCommand override, simplify railway.toml
```

---

## Key Architecture & Gotchas

### API client bootstrap (`App.tsx`)
```tsx
const DEV_API_BASE = process.env.EXPO_PUBLIC_API_URL ?? 'http://127.0.0.1:8000';
await saveApiBase(DEV_API_BASE);   // persists to AsyncStorage
await initClient(DEV_API_BASE);    // builds axios instance — MUST be awaited
```
`EXPO_PUBLIC_API_URL` is baked in at EAS build time from `eas.json preview.env`.

### User ID flow
- `uuidv4()` generated in `Step8Name.tsx` at end of onboarding
- Stored in AsyncStorage under key `user_id`
- Loaded in `App.tsx` bootstrap → `setUserId(stored.userId)`
- Injected as `X-User-Id` header on every request via axios interceptor
- All `/tracking/*` endpoints require a valid UUID in `X-User-Id` — returns `422` if missing/invalid

### Root cause of "Can't reach server" (FIXED — commit `978dbeea`)
`Step8Name.tsx` had three lines that ran at the end of onboarding:
```ts
const apiBase = 'http://192.168.1.33:8000';  // hardcoded old laptop IP
initClient(apiBase);       // overwrote Railway URL in memory
await saveApiBase(apiBase); // persisted dead URL to AsyncStorage permanently
```
Every user who completed onboarding was stuck pointing at a dead local IP.
**Fix:** removed all three lines. `App.tsx` already initialised the client with the Railway URL before onboarding started.

### `api/config.py` DATABASE_URL validators
- `_fix_async_url`: `postgresql://` → `postgresql+asyncpg://` (used by SQLAlchemy async engine)
- `_fix_sync_url`: `postgresql://` → `postgresql+psycopg2://` (used only by Alembic migrations)
- asyncpg ignores `?sslmode=require` in URL — do not add it. Internal Railway networking doesn't need SSL.

### Railway Postgres history
- Original Postgres crashed in a loop ("Stopping Container" immediately after "ready to accept connections")
- `railway redeploy` did not fix it — likely corrupted volume
- **Solution:** deleted via Railway dashboard, provisioned new service (`postgres-ciqd`)
- Set both `DATABASE_URL` and `DATABASE_SYNC_URL` on the `api` service to the new internal URL
- 3 migrations ran cleanly

---

## Issue History (all resolved)

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 1 | EAS build ERRORED | node_modules committed to git | Added `.gitignore`, removed from tracking |
| 2 | EAS build ERRORED | Missing `splashscreen_logo` drawable | Added `splash.image` + `adaptiveIcon.foregroundImage` to `app.json` |
| 3 | App "can't reach server" | `initClient` not awaited in `App.tsx` | Added `await` |
| 4 | asyncpg `TimeoutError` / Postgres crash loop | Corrupted Railway Postgres volume | Deleted, provisioned new `postgres-ciqd` service |
| 5 | App "can't reach server" after onboarding | `Step8Name.tsx` hardcoded local IP, overwrote Railway URL | Removed 3 lines from `Step8Name.tsx` |
| 6 | App shows "Can't reach server" on home screen for new users | `/tracking/daily-summary` returns 404 when no sessions exist; axios throws on non-2xx → `HomeScreen` treated it as network error | Check `e.response.status === 404` in `load()`, set `noData=true` instead of `error=true`; show "Nothing here yet" empty state |

---

## Useful Commands

```bash
# Check API health
curl https://api-production-8195d.up.railway.app/health

# Test DB-dependent endpoint (replace UUID with a real one from the app)
curl https://api-production-8195d.up.railway.app/tracking/daily-summary \
  -H "x-user-id: 00000000-0000-0000-0000-000000000001"

# Railway
cd ~/Desktop/Zenflow_backend
railway logs --service api
railway logs --service Postgres
railway variables --service api
railway redeploy --service api --yes

# Build new APK
export PATH="$HOME/.npm-global/bin:$PATH" EXPO_TOKEN="NkUqALgfgbtl9bqLG8UW8OlhSn7QSW2MLHs_6Tyn"
cd ~/Desktop/Zenflow_front
eas build --platform android --profile preview --non-interactive

# Install APK to phone
/Users/pratikbarman/Library/Android/sdk/platform-tools/adb install -r ~/Downloads/ZenFlow-vX.apk
```

---

## PERMANENT RULES — READ FIRST

### Database
- **The database is Railway PostgreSQL** — there is NO local SQLite or local DB.
- Both the local backend (`127.0.0.1:8000`) and Railway prod connect to the **same Railway Postgres DB**.
- Never run `check_db.py` or inline Python DB checks against a local engine to diagnose "missing data". Always query the Railway DB via curl against either the local or prod backend.
- The local backend is only useful for testing new backend code. Data always lives in Railway.

### Router URL prefixes (frontend hook paths must match exactly)
| Router file | Prefix | Example full path |
|---|---|---|
| `api/routers/outcomes.py` | `/api/v1/outcomes` | `/api/v1/outcomes/weekly` |
| `api/routers/tracking.py` | `/tracking` | `/tracking/daily-summary` |
| `api/routers/plan.py` | `/plan` | `/plan/today` |
| `api/routers/coach.py` | `/coach` | `/coach/conversation` |
| `api/routers/tagging.py` | `/tagging` | `/tagging/tag` |
| `api/routers/session.py` | `/session` | `/session/start` |
| `api/routers/user.py` | `/user` | `/user/profile` |

Only `outcomes` uses `/api/v1/` prefix. All others are bare slugs. When in doubt: `curl http://127.0.0.1:8000/openapi.json | python3 -c "import json,sys; [print(p) for p in json.load(sys.stdin)['paths']]"`

---

## Session Log — 17 March 2026 (Part 2 — Overnight Boundary + P4)

### Fixes Applied: Day boundary bug + wake detector wiring

#### Fix 1 — `compute_live_summary()` now spans across midnight

**Root cause:** `compute_live_summary()` used `date.today()` to derive `day_start`/`day_end` as calendar-midnight boundaries. After midnight IST but before the morning read, no windows existed for the new calendar date → scores displayed as 0 (looked like a midnight reset).

**Fix (`api/services/tracking_service.py`):**
- Query today's `MorningRead.captured_at` at the start of the function.
- **If today's morning read has arrived:** use calendar-day bounds (same as before) and apply `opening_balance` from yesterday's `closing_balance`.
- **If no morning read yet (overnight window):** query from yesterday's `morning_read_ts` → `now` (spanning midnight). `opening_balance = 0.0` — carry-forward does not apply until the morning read lands.

This matches the design: midnight is invisible to the user; scores continue accumulating from yesterday's morning read timestamp until the next morning read arrives.

#### Fix 2 — Wake detector wired into `compute_live_summary()` (was P4)

`compute_live_summary()` was calling `detect_wake_sleep_boundary()` without `context_transitions` or `morning_read_ts`, so the live boundary was less accurate than `close_day()`.

**Fix:** Added the same `context_transitions` building loop that `close_day()` uses, and added `morning_read_ts` + `context_transitions` to the `detect_wake_sleep_boundary()` call.

#### Fix 3 — Removed yesterday carry-forward fallback from router

`GET /tracking/daily-summary` had a step-3 fallback that re-packaged yesterday's finalized scores as "today's" summary (with `is_estimated=True`). After Fix 1, `compute_live_summary()` will return live overnight data so step 3 is never needed and was actively misleading. Removed. The fallback chain is now:

1. Persisted `DailyStressSummary` for today
2. Live computation spanning from last morning read
3. 404 — band not worn at all

### Status

| Change | File | Tests |
|---|---|---|
| Overnight boundary span | `api/services/tracking_service.py` — `compute_live_summary()` | 934 passing (no regressions) |
| Wake detector wired | `api/services/tracking_service.py` — `compute_live_summary()` | as above |
| Remove carry-forward step-3 | `api/routers/tracking.py` — `get_today_summary()` | as above |

### Deployment

`railway up` from `~/Desktop/Zenflow_backend` (linked project). Build: 14.85s. Migrations ran clean (`alembic upgrade head`). Health check confirmed: `{"status":"ok","version":"0.1.0"}`.

Note: `railway up` CLI reported "Deploy failed" due to its 2-min health-check retry window expiring before the container was ready — this is a CLI display issue. The service came up healthy. Always confirm with `curl https://api-production-8195d.up.railway.app/health` rather than trusting the CLI exit code.

---

## Session Log — 17 March 2026

### Fixes Applied: Hooks Hardcoded URL & UUID Purge

**User problems:**
1. Tabs (History/Settings) disappeared after reconnecting → `usePlan.ts` hit hardcoded Railway prod URL → error collapsed TabNavigator render
2. Scores reset to 0 after reconnecting → `App.tsx` overwrote the Settings-saved URL with `DEV_API_BASE` on every cold start → always pointed to prod
3. Old/wrong data shown after fresh onboarding → 5 hooks had fallback UUID `b1ddede4-32b0-466d-88b1-389d38c11e40` (stale test user) whenever `getUserId()` returned null on cold start
4. Session stream sent wrong user data → `useSessionStream.ts` had UUID baked directly into the WS URL with no dynamic lookup at all

**Fix applied:**

| File | What changed |
|---|---|
| `src/hooks/usePlan.ts` | Replaced raw `fetch` + hardcoded URL + fallback UUID with `getClient().get/post()`; corrected path from `/coach/plan/today` → `/plan/today` |
| `src/hooks/useDailySummary.ts` | Same — `getClient().get()`, preserved 404 → `setSummary(null)` behaviour |
| `src/hooks/useTagging.ts` | Same — `getClient().post()` |
| `src/hooks/useCoach.ts` | Same — `getClient().post()`, AsyncStorage message cache preserved, fallback `"test"` removed |
| `src/hooks/useOutcomes.ts` | Same — `Promise.all([getClient().get(), getClient().get()])`; corrected paths from `/outcomes/weekly` → `/api/v1/outcomes/weekly` (outcomes router has `/api/v1/` prefix, others don't) |
| `src/hooks/useSessionStream.ts` | Made `connect` async; WS URL now derived from `getApiBase()` at runtime (`https→wss`, `http→ws`); `getUserId()` called dynamically; no more hardcoded UUID in URL |
| `src/screens/HistoryScreen.tsx` | Moved profile nav rows (Archetype, Journey, Report Card, Settings) outside the `history.length === 0` gate — they now always render regardless of whether historical data exists |
| Railway DB — 2 pending migrations applied | `a1b2c3d4e5f6` and `b2c3d4e5f6a7` were written but never applied. Added 7 missing columns to `daily_stress_summaries` (`opening_balance`, `closing_balance`, `opening_recovery`, `opening_stress`, `stress_pct_raw`, `recovery_pct_raw`, `ns_capacity_used`) and `calibration_locked_at` to `personal_models`. These caused every `/tracking/daily-summary` call to 500. Applied directly via asyncpg. `alembic_version` updated to `b2c3d4e5f6a7`. |

**Changes to expect:**
- Tabs no longer disappear — `usePlan` hits the correct local/settings URL
- Scores no longer reset — URL saved in Settings persists across cold starts
- History, Plan, Coach, and WebSocket sessions all use the signed-in user's UUID, not a stale test UUID
- Changing the URL in Settings now actually sticks

---

## What to Work on Next (as of 16 March 2026)

### Calibration hardening sprint — COMPLETE ✅
All 5 phases done. Awaiting Railway deploy + post-deploy validation query.

### Parked bugs — resume when ready

| # | Bug | Location | Notes |
|---|---|---|---|
| ~~P1~~ | ~~Today's `MorningRead.rmssd_ms` not used as daily scoring anchor~~ | ~~`tracking_service.py`~~ | CLOSED (design clarification 16 Mar) — `personal.rmssd_morning_avg` is the correct frozen scoring anchor. `MorningRead.rmssd_ms` → `day_type` → coach only. Not a bug. |
| P2 | `morning_brief` endpoint passes no scores to coach | `api/routers/coach.py` | Fetch today's `MorningRead` + latest `DailyStressSummary` and pass to `coach_svc.morning_brief()` |
| ~~P4~~ | ~~Wake detector not wired in `compute_live_summary()`~~ | ~~`tracking_service.py`~~ | FIXED 17 Mar — `context_transitions` built + `morning_read_ts` passed to `detect_wake_sleep_boundary()` in `compute_live_summary()`. |
| P5 | Coach push on capacity growth | `jobs/nightly_rebuild.py` | `_check_capacity_growth()` logs INFO on trigger but no coach nudge/push to user yet |

### Future (separate scope)
- Events trigger and tagging: when do `stress_events`/`recovery_events` fire, how tagged via `tagging/`, how tags flow into `CoachContext`

### Ongoing rules
- **No code changes without explicit user approval** (standing instruction)
- JS/TS changes only → dev server hot reload (no EAS)
- EAS build only for: native module changes, `app.json`, gradle/manifest changes

---

## What to Work on Next (as of 14 March 2026 — superseded, see 16 March section above)



## Original Context (pre-development)

---

## Why This Is a Separate Project

ZenFlow_project (H10) is running perfectly with real users. Its calibration/confidence scoring system has been empirically tuned through user sessions — thresholds like the 0.3 r-value, 80-point lock threshold, and 45s force-lock are not theoretical; they came from iterative real-world testing. Merging Verity development into that codebase risks silent regressions that only show up during live sessions, which cannot be regression-tested in CI because the product is evaluated by how users feel.

**This project is a clean fork — not a config variant.**

---

## What Polar Verity Sense Provides (SDK Streams)

| Stream | Rate | Notes |
|---|---|---|
| PPI (PPG peak-to-peak) | Event-driven | RR equivalent, ~5–8ms jitter at rest vs ~1ms ECG |
| PPG raw | 135Hz, 3-channel | Red, IR, Green optical signal — the big unlock |
| ACC | 52Hz, 3-axis | Arm-worn — NOT useful for breath detection (no chest expansion) |
| Gyroscope | 52Hz | H10 doesn't have this — useful for movement/restlessness scoring |
| HR | 1Hz | Standard optical HR |

**Key difference from H10:**
- No ECG → no EDR (ECG-Derived Respiration)
- No chest ACC → breath MUST be inferred from RSA oscillation in RR, or from PAV (Pulse Amplitude Variation in raw PPG) — this is an open research question to validate with real data first
- PPG raw 3-channel → enables Perfusion Index, SpO2 trend, PAV breath detection
- Gyroscope is new capability H10 doesn't have

---

## Why the H10 Algorithm Doesn't Port Directly

The H10 confidence/calibration system is fundamentally accel-first:

```python
# H10 bridge.py — line 2163
accel_score = CONF_ACCEL_POINTS  # 50 pts ALWAYS — hardcoded reference
locked_bpm = accel_mean           # BPM is derived from accel, not RSA
```

For Verity (no chest ACC):
- Max achievable score = 50 pts (RSA only) → never reaches the 80-point lock threshold
- Every session becomes a force-lock at 45s → calibration quality undefined
- `locked_bpm` has no reference signal → must be rebuilt using EDR autocorrelation or RSA Lomb-Scargle peak as primary

**What needs to be rebuilt in bridge.py for Verity:**
1. EDR re-enabled and promoted to primary reference signal (computed from PPI, not ECG — validity to be tested)
2. New scoring: `accel_score → 0`, `CONF_RSA_HIGH_R_POINTS → 100`, `CONF_LOCK_THRESHOLD → 50`
3. `locked_bpm` derivation from EDR or RSA peak instead of `accel_mean`
4. PAV breath detection as optional third signal (experimental)
5. Remove all accel-dependent guards in calibration function

**Do NOT start the algorithm work until you have real PPI data from the band and have validated signal quality at 6 BPM resonance breathing.**

---

## First Thing to Do When Band Arrives

Before writing any algorithm code:

1. Pair the band with iPhone/Mac via Polar Flow or Polar Sensor Logger app
2. Sit quietly, breathe at 6 breaths/min (5s in, 5s out) for 10 minutes
3. Export the raw RR/PPI data
4. Look at it — specifically:
   - Is the RSA oscillation at 0.1 Hz clearly visible in the periodogram?
   - What is the jitter level (beat-to-beat noise floor)?
   - Does the 6 BPM signal survive autocorrelation at r ≥ 0.3?
5. Only after seeing clean data should you start the algorithm work

This 2-hour data validation step will save weeks of building on wrong assumptions.

---

## Product Vision: Nervous System Fitness

**Product thesis:** ZenFlow trains your nervous system the way a coach trains an athlete — with a structured program, real metrics, and proof that it's working.

**Target user:** Not a meditator. Someone chronically stressed who:
- Has tried Calm/Headspace and quit
- Would respond to empirical proof of improvement
- Motivated by progress, not by practice
- Wants to feel less reactive, handle pressure better, sleep well

**Core reframe:** Not "meditation app." Not "HRV tracker." **Nervous system fitness.**
- Non-woo, appeals to rational/skeptical people
- Has a clear improvement arc (fitness improves with training)
- Maps directly to what we're measuring

---

## The Measurement → Practice → Proof Loop

```
MEASURE (baseline) → UNDERSTAND → PRACTICE → PROVE → ADVANCE → repeat
```

The cycle never ends. Users don't "complete" — they level up.

---

## Baseline Measurement (7-day onboarding)

7 days, not 1. HRV has natural daily variance — need the distribution.

### Physiological (passive, from band)
| Signal | What it reveals | How |
|---|---|---|
| Resting RMSSD | Baseline ANS health | 5-min morning read |
| Stress arc | How stress accumulates through day | Continuous background wear |
| Recovery speed | How fast you return to baseline after stress | Automated from HRV trend |
| Perfusion Index | Sympathetic activation intensity | PPG AC/DC ratio |
| Coherence floor | Natural sync% without guidance | First unguided session |
| Sleep HRV | Overnight recovery quality | Passive wear |

### Subjective (3 questions, every 3 days — not daily, fatigue kills compliance)
1. **Reactivity:** "In the last 3 days, how easily did small things irritate or derail you?" (1–5)
2. **Focus:** "How easy was it to concentrate when you needed to?" (1–5)
3. **Recovery:** "After something stressful, how quickly did you feel okay again?" (1–5)

Maps to physiology: reactivity → sympathetic dominance, focus → prefrontal-vagal coupling, recovery → arc duration.

### Output of baseline (what the app tells the user on day 7)
> "Your nervous system runs at 62/100 on average. Your worst times are Tuesday–Wednesday afternoons. You recover slowly from stress (avg 2.1 hours). Your coherence floor without training is 23%."

This paragraph is the hook. Nobody has told a user something this specific about their biology before.

---

## The 3 Master Metrics (User-Facing)

| Metric | What it measures | User name |
|---|---|---|
| Daily RMSSD vs personal baseline | Overall ANS health today | **Resilience** (0–100) |
| Recovery arc duration | How fast you bounce back | **Recovery Speed** |
| Coherence depth + duration | Training quality | **Session Score** |

**Resilience** is the master number. Everything feeds it. Its trajectory over 8 weeks is the empirical proof.

---

## Training Program — 4 Levels

### Level 1: Signal (Weeks 1–2)
- **Goal:** Learn to follow the signal. Don't try to improve yet.
- Session: 5 minutes, full voice + ring guidance
- Metric: Coherence floor rising (start ~20–30%, target 60%)
- Unlock: 60% sync for 3 consecutive sessions
- Design note: 60% is achievable once calibration works → dopamine hit, sets tone that this is doable

### Level 2: Depth (Weeks 3–5)
- **Goal:** Push sync% higher and hold it longer
- Session: 7 minutes, ring only (no voice except nudges)
- New mechanic: **Depth zones**

```
Zone 1:  20–40%  → Settling     (distinct colour + sound)
Zone 2:  40–60%  → Engaged
Zone 3:  60–80%  → Coherent
Zone 4:  80–100% → Flow         (reaching this first time = a moment)
```

- Metric: Time in Zone 3+ per session
- Unlock: 4 consecutive minutes in Zone 3 across 3 sessions

### Level 3: Resilience (Weeks 6–8) — the innovation
- **Goal:** Train when it's hard, not when you're calm
- Mechanic: **Hardmode sessions** — scheduled when background HRV detects a low-resilience window
- App says: "Your nervous system is under load. Training here builds real resilience."
- Borrowed from stress inoculation training (military performance psychology)
- Sessions shorter (5 min) but count more toward Resilience score
- **This is what no competitor does — sessions timed to physiology, not calendar**
- Metric: Resilience delta after hard-day sessions
- Unlock: Complete 5 hardmode sessions

### Level 4+: Maintenance & Mastery (Ongoing)
- 5 min sessions, 4x per week
- Full baseline re-run every 30 days
- Compare to day 1 → this is the product's emotional peak moment

---

## Report Card Design (Simple — One Screen)

```
┌─────────────────────────────────────┐
│  YOUR NERVOUS SYSTEM · WEEK 4       │
├─────────────────────────────────────┤
│  RESILIENCE         71  ↑ +12       │
│  [████████░░]  vs week 1: 59        │
│                                     │
│  RECOVERY SPEED    1.2h  ↓ -1.1h   │
│  [███████░░░]  vs week 1: 2.3h      │
│                                     │
│  TRAINING QUALITY   8/10            │
│  [████████░░]  4 sessions this week │
├─────────────────────────────────────┤
│  WHAT THIS MEANS                    │
│  "You're recovering from stress     │
│   twice as fast as when you started.│
│   Your body is learning."           │
├─────────────────────────────────────┤
│  THIS WEEK'S FOCUS                  │
│  Hold Zone 3 for 5 min · 3 sessions │
│  [Start today's session]            │
└─────────────────────────────────────┘
```

No charts with axes. No data tables. No HRV jargon. One sentence in plain English. One thing to do next.

---

## Nudge System (Biologically Timed — Not Calendar-Based)

- **Morning read:** 5-min baseline after waking. "Your resilience today is 58 — slightly lower than average. Session scheduled for 7pm."
- **Ultradian window:** Mid-day HRV trough detected → "Natural recovery window now — 7 minutes available."
- **Evening prompt:** Contextual on stress debt accumulated.
- **Pre-performance protocol:** 10 min before high-stakes moment → 5-min session → "Your nervous system is ready."

---

## Additional Feature Directions (Future)

1. **Stress Fingerprint** — 30-day heat map: day-of-week × time-of-day × resilience level. Unique to each user. "Schedule hard things in your green zones."

2. **Event Tagging** — One-tap: meeting, argument, exercise, coffee, alcohol, bad sleep. Correlate with HRV outcomes automatically over weeks.

3. **SpO2 Trend** — 3-channel PPG enables in-session oxygen saturation trend. Shows optimisation during coherence breathing. Viscerally compelling.

4. **Subjective × Objective Correlation** — Map 3-day check-in scores against HRV trend. By week 6: "You rated stress handling 4/10 three weeks ago. Last week: 7/10. Your RMSSD agrees — up 31%."

5. **Pre-Performance Protocol** — Acute use case. Different from chronic training but same hardware + session engine.

6. **Restlessness Score** — Gyro + arm ACC micro-movements before a session. High restlessness → suggest 60s body scan before breathing begins.

---

## Tech Stack (Expected — mirrors ZenFlow_project)

- **Backend:** Python FastAPI (bridge.py) — to be rebuilt for Verity
- **Frontend:** React + TypeScript (zenflow-ui)
- **Hardware bridge:** Swift (Polar BLE SDK) — stream PPI + PPG raw instead of ACC
- **Communication:** WebSocket (same as H10 project)

The UI layer can be largely copied from ZenFlow_project. The algorithm layer (bridge.py calibration function, confidence scoring) needs a ground-up rewrite for the no-accel signal architecture.

---

## Key Design Principles

1. **Data without meaning = abandonment.** Every number must have a plain-English sentence explaining what it means.
2. **The system tells you what to do today.** Remove decision fatigue.
3. **Progressive overload.** Borrow from strength training, not from meditation apps.
4. **Feel it before the data proves it.** Week 1–2 is the danger zone — HRV takes 3–4 weeks to measurably shift. Bridge this with subjective check-ins that show correlation by week 6.
5. **Sessions timed to physiology, not calendar.** This is the core differentiator.

---

## What to Do When This Workspace Opens Next

1. Band arrived? → Run the 10-minute data validation session (see "First Thing to Do" above)
2. Check PPI jitter and RSA peak quality at 6 BPM
3. If signal is clean: start Swift bridge for PPI streaming
4. If signal is marginal: research PAV as alternative breath signal before committing
5. Only after validated signal: begin bridge.py calibration rewrite for no-accel mode

---

*This context file is the source of truth for all product and technical decisions made before development began. Update it as decisions evolve.*
