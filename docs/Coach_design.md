# ZenFlow Coach — How It Works

---

## 1. How does the coach work?

The coach runs in three layers. Think of it like a doctor who reads your full chart once in the morning, then writes personalized notes throughout the day.

### Layer 1 — All your data in one place (`coach/input_builder.py`)

Every time the coach needs to say something, it first assembles a "data packet" called a `CoachInputPacket`. This pulls from every table in the database:

| What | Where it comes from |
|---|---|
| Your nervous system profile (floor, ceiling, morning avg HRV) | `PersonalModel` |
| Last 14 days of stress, recovery, readiness scores | `DailyStressSummary` |
| Last 7 morning reads | `MorningRead` |
| Stress events in the last 48 hours | `StressWindow` |
| Recovery events in the last 48 hours | `RecoveryWindow` |
| Last 7 check-ins (how you felt — reactivity, focus, recovery) | `CheckIn` |
| Habits in the last 72 hours (alcohol, exercise, late night etc.) | `HabitEvent` |
| Your lifestyle baseline (exercise frequency, caffeine, stress drivers) | `UserHabits` |
| Last 14 days of daily plans and adherence | `DailyPlan` |
| Last 30 days of skipped plan items and reasons | `PlanDeviation` |
| Last 14 days of anxiety/stress triggers | `AnxietyEvent` |
| Your personality profile (streak, anxiety sensitivity, mood baseline) | `UserPsychProfile` |
| Confirmed facts about you from past conversations | `UserFact` |
| Last 3 days of conversation history | `ConversationEvent` |
| Your engagement profile (band days worn, sessions done, preferred tone) | `UserUnifiedProfile` |

No raw HRV numbers ever reach the LLM. Everything is converted to 0–100 scores or plain English labels (e.g. "stress is high", "recovery trending down") before being sent.

### Layer 2 — One comprehensive narrative written once a day (`jobs/nightly_rebuild.py`)

Every morning at **6:30 AM IST**, the system takes the full data packet and makes **one LLM call** that writes a structured internal coaching document. This is stored as `UUP.coach_narrative` and answers:

- **PHYSIO PROFILE** — Who is this person's nervous system? What is their floor/ceiling/morning avg trend?
- **YESTERDAY RECAP** — How did yesterday go? Stress events, tagged triggers, recovery, readiness.
- **SUBJECTIVE ALIGNMENT** — What did they report in check-ins? Does it match the physiology?
- **BEHAVIORAL SIGNALS** — Are they wearing the band? Following the plan? What are they skipping?
- **LONGITUDINAL SIGNALS** — Is their system improving over weeks? Stress reducing? Recovery faster?
- **WHAT THEY LIKE / WHAT HELPS** — Which activities reliably help them recover? What drives their stress?
- **READINESS VERDICT** — Should they push, maintain, or protect today?
- **WATCH TODAY** — 3–5 specific bullets the coach must keep in mind for all interactions today.

This narrative is the **single source of truth** for the entire day. Every surface — morning brief, plan, nudges, conversation — reads from it. No separate data assembly happens again.

### Layer 3 — Personalized outputs from the narrative (all consumer surfaces)

Each surface takes the narrative + a small context snippet and runs a **short, focused prompt** to produce its specific output. One source, many surfaces.

---

## 2. How often is the personalized narrative triggered?

| Trigger | When | Notes |
|---|---|---|
| **Scheduled nightly rebuild** | Every day at **6:30 AM IST** (01:00 UTC) | Runs for all active users. Writes `coach_narrative` + stamps `coach_narrative_date = today`. |
| **Inline regen in morning brief** | When `GET /coach/morning-brief` is called and `coach_narrative_date` ≠ today | If the scheduled job hasn't run yet (e.g. new user, server issue), the morning brief triggers a fresh Layer 2 call inline before producing the brief. |
| **Idempotency guard** | If `coach_narrative_date == today`, the job is skipped | One narrative per user per day. No double LLM calls. |

Active users = users with at least one session or morning read in the last 30 days. Inactive users are skipped.

---

## 3. How does the morning brief, plan, and plan dos/don'ts work?

### Morning Brief (`GET /coach/morning-brief`)

1. The app calls this endpoint when the user wakes up.
2. The backend checks: **is today's brief already stored?** (`morning_brief_generated_for == today_ist`)
3. If yes → return it instantly. No LLM call.
4. If no → check if today's narrative exists. If not, regen Layer 2 inline. Then run the **Layer 3 morning-brief prompt** against the narrative.
5. The prompt produces a JSON with: `day_state` (green/yellow/red), `day_confidence`, `brief_text` (2–3 lines), `evidence` (what data drove the assessment), `one_action` (one clear thing to do today).
6. Result is stored in `UUP` so the next app open is instant.

**What makes it personalized:** The narrative already knows the user's physiology pattern, yesterday's stress events, their typical recovery style, and today's readiness verdict. The brief just expresses that in 2–3 readable lines.

### Plan (`GET /plan/today`)

1. The plan is generated by `plan_service.py` using the **readiness score** for today.
2. Readiness determines the plan shape:
   - **Green day (readiness ≥ 70)** → Push plan: full ZenFlow session + recommended activity
   - **Yellow day (45–69)** → Maintain plan: shorter session + gentle movement
   - **Red day (< 45)** → Protect plan: recovery-only, no hard exertion
3. Plan guardrails (`profile/plan_guardrails.py`) validate the LLM-suggested plan items against hard physiological rules (e.g. no hard training on 3 consecutive high-stress days).
4. The plan response also includes a `brief` field — a 2-sentence Layer 3 explanation of **why today's plan is what it is**, grounded in yesterday's physiology from the narrative.

### Plan Dos and Don'ts

- **Dos** = the plan items themselves (must_do, recommended, optional).
- **Don'ts** (`avoid_items`) = 1–2 specific things to avoid today, derived from the narrative by a Layer 3 prompt. Example: "Avoid heavy training — 3 consecutive high-stress days." Stored in `UUP.avoid_items_json` and returned alongside the plan.

---

## 4. How does conversation work?

### The flow

1. User sends a message to `POST /coach/conversation`.
2. `ConversationService.process_turn()` is called.
3. Before building the prompt, it assembles:
   - Today's live physio scores (stress, recovery) from the DB
   - The full `UUP.coach_narrative` (Layer 2 output)
   - Confirmed user facts from past conversations
   - Any avoid-items from today's plan
4. All of this is injected into the **conversation system prompt** as a `PERSONALITY + TODAY` context block.
5. The LLM writes a reply grounded in the user's known traits and today's physiological state.
6. Both the user message and coach reply are stored as `ConversationEvent` rows.
7. At conversation close, extracted lifestyle signals (alcohol, exercise, late night etc.) are stored as `HabitEvent` rows, and new facts about the user are stored as `UserFact` rows — feeding the next day's narrative.

### Topic guardrail

Every conversation system prompt includes `CONVERSATION_TOPIC_SCOPE` — a hard rule:

- **Allowed:** fitness, physical training, exercise, recovery, sleep, stress management, breathing, physical health, mental health, emotional wellbeing, nutrition (performance/recovery context), mindfulness.
- **Off-topic deflection:** "I'm focused on your health and nervous system — let me know if there's something in that space I can help with."
- Boundary cases like "I'm stressed about work" are **in scope** — work stress is a health topic.

### Memory and continuity

- The last 3 days of conversation turns are included in the Layer 2 narrative prompt each morning, so the coach "remembers" what you talked about.
- Confirmed facts (confidence ≥ 0.7) are included in every conversation context — the coach knows you have a daughter named Aria, you hate cold showers, or you have a big presentation Thursday.

---

## 5. How do real-time nudges work?

Nudges are **event-driven**, not scheduled. Each of the 5 triggers fires when a specific condition is detected in live data. Every nudge is personalized using `UUP.coach_narrative`.

### The 5 triggers

| # | Trigger | ID | When it fires | De-dupe / cap |
|---|---|---|---|---|
| T1 | **Plan item incomplete** | `plan_incomplete` | A `must_do` or `recommended` item has `has_evidence=False` by ~2 hours before typical sleep time | Once per item per day |
| T2 | **Stress off limits** | `stress_alert` | `stress_load_score > 75` OR 2+ stress windows detected in the last 3 hours | Max 2 per day; 3-hour cooldown |
| T3 | **Morning ready** | `morning_ready` | Layer 2 narrative has been generated for today; tells user to put the band on and start the day | Once per day, 6:30–7:30 AM IST |
| T4 | **Sleep reminder** | `sleep_reminder` | `typical_sleep_time - 45 min` (from `PersonalModel`) and band is still in background context (not sleep yet) | Once per night |
| T5 | **Post-session motivational** | `post_session` | A ZenFlow session just completed (`ended_at` within last 5 min) | Once per session |

### How each nudge is generated

Every trigger:
1. Reads `UUP.coach_narrative` (truncated to 800 chars if needed).
2. Packages a `trigger_context` dict with trigger-specific facts:
   - T1: which item was skipped, why it matters today
   - T2: current stress score, top stress tag
   - T5: session score, duration, coherence avg
3. Calls a **Layer 3 nudge prompt** — one short LLM call.
4. Output: one message, ≤ 60 words, grounded in the user's narrative.
5. Stored as a `NotificationEvent` row. De-dupe key prevents sending the same nudge twice.

If `coach_narrative_date ≠ today` (narrative is stale), the system falls back to a static template instead of calling the LLM — so nudges always fire on time even if the morning rebuild was delayed.

### General nudge gate (`GET /coach/nudge`)

There is also a general mid-day nudge check with three gates:
1. **Time window gate** — only fires between `NUDGE_WINDOW_START_HOUR_IST` and `NUDGE_WINDOW_END_HOUR_IST` (configurable in `config/`).
2. **Cap gate** — max `NUDGE_CAP_PER_4H` nudges in any rolling 4-hour window.
3. **Data gate** — requires at least one day of trajectory data.

All three must pass before a nudge is generated and sent.

---

## Architecture summary

```
All data sources (HRV, stress, recovery, plans, check-ins, habits, facts...)
        ↓
    Layer 1: CoachInputPacket  (input_builder.py)
        ↓
    Layer 2: Comprehensive narrative  (nightly_rebuild.py @ 6:30 AM IST)
             stored in UUP.coach_narrative
        ↓
    ┌──────────────────────────────────────────────────────┐
    │  Layer 3 — same narrative, different prompt per surface  │
    ├──────────────────────────────────────────────────────┤
    │  Morning brief    → GET /coach/morning-brief         │
    │  Plan brief       → GET /plan/today (brief field)    │
    │  Plan don'ts      → GET /plan/today (avoid_items)    │
    │  Nudge T1–T5      → notification_policy_service.py   │
    │  Conversation     → POST /coach/conversation         │
    └──────────────────────────────────────────────────────┘
```

One narrative. Five surfaces. Zero repeated data assembly.
