# ZenFlow Verity — End-to-End Testing Plan

**Purpose:** Validate that the full system (baselining, tracking, tagging, coach, conversation, UUP) captures data correctly, builds the Unified User Profile accurately, and produces coherent coaching output — without hardware (band-free).

**Method:** One real user (you) exercising every endpoint in sequence via `http://localhost:8000/docs` (Swagger UI) or the test scripts listed below.

**What is excluded:** Session screens (already tested separately). Band-dependent WebSocket streams (deferred until Polar Verity Sense arrives).

---

## Pre-Flight

```bash
# Confirm PostgreSQL is running
psql postgresql://zenflow:zenflow@localhost:5432/zenflow_dev -c "SELECT 1;"

# Start API server
cd /Users/pratikbarman/Desktop/ZenFlow_Verity
source .venv/bin/activate
uvicorn api.main:app --reload --port 8000

# Open in browser
open http://localhost:8000/docs
```

---

## Phase 0 — Create Your User & Profile (Day 0, ~10 min)

| # | Endpoint | Payload | Expected result |
|---|---|---|---|
| 1 | `POST /user/register` | Basic auth payload | `user_id` returned — save it for all subsequent calls |
| 2 | `POST /user/{id}/personal-model` | Age, sex, height, weight, training history | Personal model persisted |
| 3 | `POST /user/{id}/psych-profile` | Social type, triggers, recovery style, discipline self-rating | Psych profile stored |
| 4 | `GET /profile/{id}/unified` | — | UUP exists; most fields `null`; `completeness_score` ≈ 0.15 |

**Checkpoint:** UUP has physio + psych skeleton. No behavioural data yet.

---

## Phase 1 — Simulate 7 Days of Tracking (~30 min)

Call `POST /tracking/daily-read` 7 times with these values (realistic variance):

```
Day 1:  { "rmssd": 42, "readiness_score": 68, "stress_score": 45 }
Day 2:  { "rmssd": 38, "readiness_score": 61, "stress_score": 58 }
Day 3:  { "rmssd": 51, "readiness_score": 74, "stress_score": 35 }
Day 4:  { "rmssd": 36, "readiness_score": 59, "stress_score": 65 }
Day 5:  { "rmssd": 44, "readiness_score": 70, "stress_score": 42 }
Day 6:  { "rmssd": 39, "readiness_score": 63, "stress_score": 55 }
Day 7:  { "rmssd": 48, "readiness_score": 72, "stress_score": 38 }
```

**After all 7 reads:**

- `GET /tracking/{id}/baseline-summary` → personal mean RMSSD, resilience range, stress profile should be computed
- `GET /profile/{id}/unified` → `physio` section should have `resting_rmssd`, `resilience_score`, `recovery_arc_speed` populated

---

## Phase 2 — Activity Tagging (~15 min)

Tag a mix of activities with realistic outcomes to build behavioural signal.

**High-positive performers (felt good / HRV improved):**
```
POST /tagging/tag  →  { "slug": "coherence_breathing", "felt_score": 8, "hrv_delta": +6 }
POST /tagging/tag  →  { "slug": "walking",             "felt_score": 7, "hrv_delta": +4 }
POST /tagging/tag  →  { "slug": "meditation",          "felt_score": 6, "hrv_delta": +3 }
POST /tagging/tag  →  { "slug": "music",               "felt_score": 7, "hrv_delta": +2 }
```

**Stress-correlated activities:**
```
POST /tagging/tag  →  { "slug": "work_sprint",  "felt_score": 4, "hrv_delta": -5 }
POST /tagging/tag  →  { "slug": "social_time",  "felt_score": 5, "hrv_delta": -2 }
```

**Verify:**
- `GET /tagging/{id}/model` → activity scoring table building; `coherence_breathing` = high positive, `work_sprint` = negative
- `GET /profile/{id}/unified` → `behaviour.top_calming_activities` should include `coherence_breathing`, `walking`

---

## Phase 3 — Coach Conversations (~30 min) — Core UUP Test

This is the most critical phase. Send messages designed to trigger each fact-extractor pattern.

Start a conversation: `POST /coach/stream/start`
Then send messages via the stream endpoint.

**Send these messages across 2–3 conversation turns:**

| Message | Expected extracted fact |
|---|---|
| `"I usually wake up around 6:30am"` | `schedule.wake_time` |
| `"I tend to work late into the evenings"` | `schedule.late_worker` |
| `"I don't really enjoy large group settings"` | `preference.prefers_small_groups` |
| `"My knees make it hard to do high-impact stuff"` | `preference.bad_knees` |
| `"I find that music really helps me decompress"` | `preference.likes_music` |
| `"I have a big presentation coming up Friday"` | `event.upcoming_stressor` |
| `"My main goal is to feel less reactive at work"` | `goal.reduce_reactivity` |
| `"I've been trying to drink less coffee lately"` | `health.reducing_caffeine` |

**After closing each conversation:**
- `GET /profile/{id}/facts` → 6–8 facts present with `confidence` values (first mention = 0.5)
- `GET /profile/{id}/unified` → `user_facts` populated; facts referenced in `coach_narrative`

**Confidence bump test:** Send a second conversation that repeats one of the above facts (e.g., "Yeah, my knees are still a problem"). After closing:
- `GET /profile/{id}/facts` → repeated fact's `confidence` should bump from 0.5 → 0.7

---

## Phase 4 — Morning Brief (~10 min)

```json
POST /coach/morning-brief
{
  "user_id": "{your_id}",
  "include_uup": true
}
```

**Quality checklist — the brief MUST:**
- [ ] Reference your actual RMSSD / readiness (not generic placeholder values)
- [ ] Include a daily plan with slugs from your tagging model (coherence_breathing, walking, etc.)
- [ ] Mention at least one UUP-derived nuance (e.g., "Your knees are a factor — walking over running")
- [ ] Show `engagement_tier` in the response payload

**If the brief is generic and could apply to anyone:** data is not flowing into the coach context. Debug path:
1. Check `coach_service.py` → `build_coach_context()` call — are `uup_narrative` and `user_facts` non-null?
2. Check `conversation_service.py` → `close_and_persist()` — were facts actually written to DB?
3. Check `profile_service.py` → `load_facts()` — is the query returning rows?

---

## Phase 5 — Daily Plan Inspection (~5 min)

```
GET /plan/daily?user_id={id}&date=today
```

**Assert:**
- Plan items correspond to activities that scored well in Phase 2 tagging model
- No invalid slugs present (R1 guardrail working)
- If simulated readiness was 59 (Day 4): `work_sprint` should NOT appear (R4 guardrail)
- If simulated readiness was 74 (Day 3): `work_sprint` CAN appear

---

## Phase 6 — UUP Completeness Audit (~10 min)

```
GET /profile/{id}/unified
```

Expected state after Phases 0–5:

| Layer | Min expected | Key fields to check |
|---|---|---|
| `physio` | ✅ Full | `resting_rmssd`, `resilience_score`, `recovery_arc_speed` |
| `psych` | ✅ Full | `discipline_index`, `social_energy_type`, `anxiety_sensitivity` |
| `behaviour` | ✅ ≥ 3 activities | `top_calming_activities`, `decompress_via` |
| `engagement` | ✅ "medium" or "high" | `engagement_tier`, `sessions_last7` |
| `user_facts` | ✅ ≥ 6 facts | Each has `category`, `fact_key`, `confidence` |
| `coach_narrative` | ✅ Non-null paragraph | Reads as personalised, not generic |
| `plan_for_date` | ✅ Today's plan | `items[]` with slugs, reasons |

**`completeness_score` target: ≥ 0.65** after all phases. Any lower → identify which layer is incomplete and trace back.

---

## Phase 7 — Day 2 Evolution Check (~10 min)

Validate that the UUP evolves correctly over time:

1. Send another `POST /tracking/daily-read` with fresh values
2. Send a follow-up conversation repeating a signal ("Still struggling with coffee in the mornings")
3. `GET /profile/{id}/facts` → repeated fact confidence bumped
4. `GET /profile/{id}/unified` → `engagement_tier` reflects accumulated history
5. `GET /plan/daily` → plan reflects updated readiness, not yesterday's

---

## Pass / Fail Criteria

### Hard pass (system must do all of these)
- [ ] UUP `completeness_score` ≥ 0.65 after Phase 6
- [ ] ≥ 6 facts extracted from natural conversation messages
- [ ] Confidence bumps correctly on repeated signals
- [ ] Morning brief references actual user data (RMSSD, activity preferences, a fact)
- [ ] R4 guardrail correctly blocks `work_sprint` on low-readiness days
- [ ] No 500 errors across any phase

### Qualitative pass (human judgement)
- [ ] Does `behaviour.top_calming_activities` match what you actually find calming?
- [ ] Does `coach_narrative` read as personalised — could it only apply to you?
- [ ] Does the daily plan feel appropriate for the day's simulated readiness?
- [ ] Are the extracted facts accurate sentences from your actual messages?

If any qualitative check fails, that's the prioritisation signal:
- Wrong activities → review tag scoring weights in `tagging/`
- Generic narrative → review LLM prompt in `profile/nightly_analyst.py`
- Wrong facts → review regex patterns in `profile/fact_extractor.py`
- Wrong plan → review guardrail logic in `profile/plan_guardrails.py`

---

## Parallel Build Track

| Week | Testing | Frontend |
|---|---|---|
| Week 1 | Phases 0–3 (manual, via /docs) | Auth + Morning Brief screen |
| Week 2 | Phases 4–7 | Activity feed + UUP dashboard |
| Pre-band | — | Session screen placeholder ("Band required") |
| Day band arrives | Band validation session | Wire WebSocket → session screen |
