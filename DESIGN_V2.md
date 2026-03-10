# ZenFlow Verity — Complete System Design (v2)

**Created:** March 2026  
**Status:** Final locked design — pre-implementation of coach + tagging modules  
**Tests passing:** 574

---

## Document Map

| Section | Status |
|---|---|
| 1. Product Vision | Locked |
| 2. Onboarding | Locked |
| 3. Hardware + Signal Processing | Locked |
| 4. Personal Model + Baselining | Locked |
| 5. Archetypes + NS Health Score | Locked |
| 6. Live ZenFlow Sessions | Locked |
| 7. All-Day Tracking (Stress / Recovery / Readiness) | Locked + Implemented |
| 8. Tagging System | Locked |
| 9. Activity Catalog | Locked |
| 10. AI Coach | Locked (daily plan structure TBD) |
| 11. **[TBD] Daily Plan Design** | Open — to be discussed |
| 12. Outcomes Engine | Locked |
| 13. API Layer | Locked |
| 14. UI & Experience Design | Locked |
| 15. Full User Journey | Locked |
| 16. Database Schema | Locked |
| 17. Directory Structure | Locked |
| 18. Configuration | Locked |

---

## 1. Product Vision

### The Reframe

The nervous system is not one of many health metrics. It is the substrate everything else runs on.

```
NERVOUS SYSTEM STATE
        │
        ├── Sleep quality          (high cortisol → poor deep sleep → low HRV tomorrow)
        ├── Stress resilience      (low vagal tone → threat response over-triggers)
        ├── Physical performance   (sympathetic dominance → poor recovery from exercise)
        ├── Cognitive clarity      (prefrontal-vagal coupling → focus, decision quality)
        ├── Emotional regulation   (ANS state → reactivity, patience, mood)
        └── Metabolic health       (chronic stress → cortisol → insulin → energy dysregulation)
```

ZenFlow's position: **"We fix the root cause. Everything else improves as a downstream consequence."**

This is scientifically defensible — HRV improvement is causally linked to better sleep, reduced anxiety, improved exercise recovery, and better emotional regulation. The nervous system is upstream of all of it.

### The Design Bet

ZenFlow doesn't need to track everything. It needs to **explain everything it tracks better than anyone else does.**

Same data as Fitbit. Completely different product. Fitbit says "Light sleep: 3h22m." ZenFlow says: *"Your deep sleep was cut short — that's the phase that clears stress hormones. You'll feel it by 2pm today."*

### Design Principles

1. **One screen, one idea.** Never more than one primary action per screen.
2. **No jargon in the UI.** Scientific terms live in tooltips only — never in main copy.
3. **Optimistic always.** Every insight is framed as an opportunity, never a warning.
4. **Instant gratification.** First meaningful insight within 24 hours. First archetype within 48 hours.
5. **The system decides.** Remove every decision from the user. They confirm, not choose.
6. **Progress is visible.** Journey map always accessible.
7. **Feel it first, prove it later.** Week 1 is about sensation. Week 4–6 is where data validates what they already feel.
8. **No HRV jargon in the UI. Ever.**

### Language Guide

| ❌ Never say | ✅ Say instead |
|---|---|
| HRV / RMSSD | Body rhythm, nervous system score |
| Coherence | In sync, heart-breath sync |
| Sympathetic dominance | Your body is on high alert |
| Parasympathetic | Your body is in rest mode |
| Vagal tone | Your calm system |
| Stress marker elevated | Your body is carrying some load |
| Low resilience | Your body needs a reset |
| RMSSD delta | Your body shifted after the session |

---

## 2. Onboarding

### Structure — 8 Screens, One Question Each, ~3 Minutes

Progress dots at top. Clean, white. No clutter.

**Screen 1 — Welcome:** "Your body is smarter than you think. We're going to prove it."

**Screen 2 — Main goal (single select):**
- I can't switch off
- I'm always tired
- I snap at small things
- I can't focus
- I sleep badly

**Screen 3 — Typical day (single select):**
- High-pressure work, back-to-back
- Active and on my feet
- Mostly desk-based
- Variable — no two days are the same

**Screen 4 — Movement enjoyed (multi-select):** Running, Cycling, Gym / strength, Swimming, Hiking / walks, Yoga / pilates, Team sports, Nothing yet

**Screen 5 — Lifestyle inputs (three sub-questions):**
- Alcohol: Rarely / Socially / Most evenings
- Caffeine: 1–2 morning cups / Several all day / Sensitive
- Sleep schedule: Consistent / Varies a lot

**Screen 6 — Decompress style (multi-select):** Exercise, Reading, Nature, Music, TV/streaming, Socialising, I just push through

**Screen 7 — The honest one:** "This app measures your body — not just your habits. It will notice things about you before you do. That's what makes it work."

**Screen 8 — Band connect:** Polar SDK BLE pairing flow, auto-detect, connect.

### What Onboarding Feeds Into

| Input | Used by |
|---|---|
| Movement enjoyed | Coach prescribes activities user actually enjoys |
| Alcohol/caffeine/sleep | Coach calibrates recovery expectations; nudge timing |
| Decompress style | Coach references personal preferences in language |
| "I just push through" | Flags Suppressor tendency → adjusts first archetype hypothesis |
| Typical day | Stress fingerprint prior → early pattern classification |

### What Is NOT Asked

- Diet or nutrition (changes coaching liability)
- Medical history (not a clinical product)
- Weight or fitness level (irrelevant — the band measures what matters)

---

## 3. Hardware + Signal Processing

### Hardware — Polar Verity Sense (Optical Armband)

| Stream | Rate | Used For |
|---|---|---|
| PPI | Event-driven | All HRV computation |
| PPG raw (3-channel) | 135Hz | SpO2, Perfusion Index, PAV breath |
| ACC | 52Hz | Movement debt, restlessness |
| Gyroscope | 52Hz | Pre-session settling, fidgeting |
| HR | 1Hz | Background context |

**Secondary inputs (passive):**
- Apple Health / Google Fit → steps, activity, sleep stages
- User self-report → 3 subjective questions every 3 days

### Bridge Layer (`bridge/` — Swift)

Responsibilities:
- BLE pairing and auto-reconnect via Polar SDK
- Per-beat artifact flagging (not silent removal — flag, let backend decide)
- Context tag per packet: `session | background | sleep | morning_read`
- Buffer during connection drop, flush on reconnect
- Apple Health ingestion via HealthKit

WebSocket packet format:
```json
{
  "stream": "ppi",
  "context": "background",
  "ts": 1741200000.123,
  "value": 847,
  "artifact": false
}
```

### Signal Processing Layer (`processing/` — Python)

**Rule: Deterministic. No AI. Same input always produces same output.**

| Module | Role |
|---|---|
| `ppi_processor.py` | RMSSD, SDNN, pNN50 from PPI stream |
| `rsa_analyzer.py` | Lomb-Scargle periodogram → RSA power at 0.1Hz |
| `coherence_scorer.py` | RSA peak dominance → coherence % per window |
| `breath_extractor.py` | EDR from RSA oscillation + PAV from PPG |
| `ppg_processor.py` | Perfusion Index, SpO2 from 3-channel PPG |
| `motion_analyzer.py` | Restlessness score from ACC + Gyro |
| `recovery_arc.py` | HRV trend event detection → arc duration |
| `artifact_handler.py` | Hold-last-good vs gap vs interpolate |

**Output schema:**
```json
{
  "metric": "rmssd",
  "value": 42.3,
  "confidence": 0.91,
  "context": "session",
  "window_ms": 60000,
  "ts": 1741200060.000
}
```

Every metric emits a confidence score (0.0–1.0). Metrics degrade gracefully on artifact — they never output silently wrong values.

### BPM Detection — No Accelerometer

Verity has no accelerometer for breath detection. BPM inferred from RSA oscillation in PPI series:

```
PPI series → Bandpass filter (0.07–0.40 Hz) → Detect peaks in filtered PPI
→ Period between peaks = one breath cycle → detected_bpm = 60 / period_seconds
```

Update cadence: ~5–10 seconds. Stage 0 users with weak RSA buffered by ring_entrainment first.

---

## 4. Personal Model + Baselining

### Role

Learns the individual user's physiological patterns over time. Everything is relative to *this user's own history* — no population norms.

### Personal Fingerprint

Built over first 7 days, updated continuously. Minimum 3 valid sessions for initial fingerprint.

```json
{
  "user_id": "u_123",
  "rmssd": {
    "floor": 28.1,
    "ceiling": 61.4,
    "weekday_avg": 38.2,
    "weekend_avg": 47.1,
    "morning_avg": 44.3
  },
  "recovery_arc_hours": { "mean": 1.4, "fast": 0.7, "slow": 3.1 },
  "stress_peak_day": "wednesday",
  "stress_peak_hour": 15,
  "coherence_floor": 0.31,
  "coherence_trainability": "moderate",
  "compliance_best_window": "19:00",
  "interoception_gap": -0.4,
  "archetype_primary": "hustler",
  "archetype_secondary": "loop_runner",
  "archetype_confidence": { "hustler": 0.72, "loop_runner": 0.41 },
  "model_version": 12,
  "last_updated": "2026-03-09",
  "stress_capacity_floor_rmssd": 28.1,
  "capacity_version": 3,
  "typical_wake_time": "07:15",
  "typical_sleep_time": "23:30"
}
```

### Onboarding Timeline (No 7-Day Wait)

| When | What user gets | Label |
|---|---|---|
| Day 1, after first morning read | Live waveform, HR, first rough stress reading | "Calibrating — learning your baseline" |
| End of Day 2 | Provisional stress/recovery scores | "Early estimate — gets more accurate daily" |
| Day 3 | First usable 3-day baseline | Scores shown normally, small "est." note |
| Day 14 | Stable floor, "(estimated)" removed | Full accuracy |
| Day 30+ | First auto-tagging suggestions | Pattern learning active |

Data is shown from Day 1. Progressive calibration is visible as improving accuracy — builds trust and engagement.

### Adaptive Capacity Updates

`stress_capacity_floor_rmssd` updates when the floor shifts >10% sustained over 7 days, or monthly. `capacity_version` increments on each update. Old scores remain recomputable (version-locked).

### Model Modules

| Module | Role |
|---|---|
| `baseline_builder.py` | 7-day onboarding → initial fingerprint |
| `personal_distributions.py` | Rolling 30-day RMSSD floor/ceiling/rhythms |
| `stress_fingerprint.py` | When/how/how fast stress accumulates |
| `recovery_profiler.py` | Arc speed class, trend over weeks |
| `coherence_tracker.py` | Coherence trainability, zone time |
| `compliance_tracker.py` | When does this user actually show up |
| `interoception_gap.py` | Subjective vs objective alignment |
| `archetype_classifier.py` | Fingerprint → archetype(s) with confidence |
| `model_store.py` | Persist + version personal model (SQLite / Postgres) |

---

## 5. Archetypes + NS Health Score

> **Role clarification:** The Stress/Recovery/Readiness framework (Section 7) is the daily user-facing output. The NS Health Score is **not shown on the home screen**. It runs as an internal engine that classifies patterns, determines Stage, gates practice tier prescriptions, and feeds CoachContext. Without it, the system cannot know what practice to prescribe, what pattern the user has, or when to unlock the next stage. The two frameworks are complementary — Stress/Recovery/Readiness tells the user how today went; NS Health Score + Stage tells the system what intervention to apply.

### Design Principle

**Score leads. Pattern supports. Name comes last as recognition.**

A person should read the description and think "that's exactly me" before they ever see the name.

### NS Health Score — 0 to 100

Five physiological dimensions, each 0–20, summing to 100.

| Dimension | Signal sources | Max |
|---|---|---|
| **Recovery Capacity** | `recovery_arc_class`, `sleep_recovery_efficiency` | 20 |
| **Baseline Resilience** | `rmssd_floor`, `rmssd_range`, `has_prior_practice` | 20 |
| **Coherence Capacity** | `coherence_floor`, `rsa_trainability`, `coherence_trainability` | 20 |
| **Chronobiological Fit** | `sleep_recovery_efficiency`, `rmssd_morning_avg / rmssd_floor` | 20 |
| **Load Management** | `lf_hf_resting`, `lf_hf_sleep`, `overnight_rmssd_delta_avg` | 20 |

### Stage System

| Stage | Score | Description |
|---|---|---|
| **0** | 0–34 | Foundation missing. Observation phase. No optimisation yet. |
| **1** | 35–54 | Pattern visible. Recovery incomplete. One intervention creates movement. |
| **2** | 55–69 | Foundation working. Adaptations visible. Ready to build intentionally. |
| **3** | 70–79 | Full functionality. Load managed. Resilient under normal conditions. |
| **4** | 80–89 | Performance zone. Every dimension above its functional floor. |
| **5** | 90–100 | Ceiling. Sustained, intelligent practice visibly reflected. |

Advancement is physiology-gated, not time-gated. Gate checks are in the Outcomes section.

### Seven Patterns

Each pattern has an evidence score (0.0–1.0) computed from weighted signals. Primary = highest score. Amplifier = second-highest if ≥ 0.20.

| Pattern | Core physiology signals | What it feels like |
|---|---|---|
| **The Over-Optimizer** | High LF/HF resting + slow recovery arcs + missing recovery gap | Trains hard, works hard. Nervous system never gets the signal it's safe to slow down. |
| **The Trend Chaser** | Low coherence + no prior practice + inconsistent data | Tries things. Nothing sticks. Data stays noisy because the variable keeps changing. |
| **The Hustler** | Load accumulates across week + slow arcs + moderate chrono fit | Monday fine. Thursday running on fumes. The problem is absence of recovery windows, not ambition. |
| **The Quiet Depleter** | Low RMSSD floor + narrow range + flat coherence | Nothing dramatically wrong. System has been running quiet and low for a while. Most don't know they're in it. |
| **The Night Warrior** | Low chrono fit + SRE < 0.90 + peak window ≥ 19:00 | Not a discipline problem — chronobiology. Their biology peaks when the world winds down. |
| **The Loop Runner** | Overnight RMSSD drops (should rise) + elevated LF/HF during sleep | The mind runs the overnight shift when the body needs repair mode. Sleep is not off time. |
| **The Purist** | Has prior practice + coherence capacity ≥ 10 | The practice is working. Data shows it. One dimension underdeveloped next to strong ones. |

**Dialled-In:** Not a pattern in the same sense. Reached when all five dimensions are above their midpoints and score clears 68. Pattern name changes. Coaching focus shifts from fixing gaps to optimising strengths.

**`dialled_in`** overrides all others when its evidence score ≥ 0.75.

Pattern is `UNCLASSIFIED` if `overall_confidence < 0.35`.

### Primary + Amplifier Display

> "You're an **Over-Optimizer**. Your **Loop Runner** pattern is amplifying this — the mind is running overnight when the body needs to be in repair mode."

### Output Types (from `archetypes/`)

**`NSHealthProfile`** — from `scorer.py`:
```python
@dataclass
class NSHealthProfile:
    total_score:         int           # 0–100
    stage:               int           # 0–5
    stage_target:        int           # next stage threshold
    recovery_capacity:   int           # 0–20
    baseline_resilience: int           # 0–20
    coherence_capacity:  int           # 0–20
    chrono_fit:          int           # 0–20
    load_management:     int           # 0–20
    primary_pattern:     str           # e.g. "over_optimizer"
    amplifier_pattern:   Optional[str]
    pattern_scores:      dict
    trajectory:          str           # "improving"|"stable"|"declining"
    stage_focus:         list[str]     # 2–3 coaching actions
```

**`NSNarrative`** — from `narrative.py`:
```python
@dataclass
class NSNarrative:
    headline:            str
    body:                str
    pattern_name:        str           # shown AFTER body — recognition, not diagnosis
    amplifier_note:      str
    dimension_insights:  dict[str, str]
    stage_description:   str
    stage_focus:         list[str]
    evolution_note:      str
```

---

## 6. Live ZenFlow Sessions

### Practice Taxonomy

Seven practices across three tiers, enforced by stage gates.

#### Tier 1 — Signal Establishment (Stage 0–1)

| Practice | `practice_type` | Description |
|---|---|---|
| Ring entrainment | `ring_entrainment` | Pacer at current BPM. No step-down. User learns to follow the ring. Stage 0 first 1–2 sessions only. |
| PRF discovery | `prf_discovery` | Step-down from current BPM → 6 BPM. Gates A/B/C determine drop. PRF = BPM at first Gate C pass. Stored in PersonalFingerprint. |
| Resonance hold | `resonance_hold` | Pacer fixed at stored PRF. No step-down. Daily workhorse from Stage 1 onward. |

#### Tier 2 — Technique Expansion (Stage 2–3)

| Practice | `practice_type` | Description |
|---|---|---|
| Box breathing | `box_breathing` | Equal inhale-pause-exhale-pause ratio. Prescribed on high acute stress. Recovery tool, not PRF training. |
| Plexus step-down | `plexus_step_down` | Step-down with attention anchor directed to a body plexus area. |
| Plexus hold | `plexus_hold` | Fixed PRF + attention anchor. Prescribed once PRF is stable. |

#### Tier 3 — Internalization (Stage 4–5)

| Practice | `practice_type` | Description |
|---|---|---|
| Silent meditation | `silent_meditation` | No pacer, no ring timing. System records if coherence at PRF frequency emerges without cueing. |

### The Ring — Pure Timing Contract

```python
@dataclass
class PacerConfig:
    target_bpm:             float
    inhale_sec:             float
    pause_after_inhale_sec: float
    exhale_sec:             float
    pause_after_exhale_sec: float
    step_down_enabled:      bool = False
    step_down_from_bpm:     float = 12.0
    step_down_to_bpm:       float = 6.0
    step_down_increment:    float = 0.5
    attention_anchor:       Optional[str] = None
    # None | "belly" | "heart" | "solar" | "root" | "brow"
```

The attention anchor is orthogonal — any pacer config can have any anchor.

### Step-Down Gates

```
Gate A — BPM match:
    |detected_bpm - target_bpm| ≤ 1.5

Gate B — Stability:
    N consecutive windows all passing Gate A
    N = STEP_DOWN_STABILITY_WINDOWS (config default: 3)

Gate C — RSA quality:
    coherence ≥ 0.65 (zone 3+)
    rsa_peak_frequency × 60 within ±1.5 BPM of target

PRF = target_bpm when all three gates first pass simultaneously
```

### Prescription Logic

| Stage | PRF status | load_score | → practice_type |
|---|---|---|---|
| 0 | unknown | any | `ring_entrainment` (first 2), then `prf_discovery` |
| 0–1 | unknown | any | `prf_discovery` |
| 1 | found | < 0.65 | `resonance_hold` |
| 1 | found | ≥ 0.65 | `box_breathing` |
| 2–3 | confirmed | any | `plexus_hold` (or `plexus_step_down` if re-calibrating) |
| 2–3 | confirmed | ≥ 0.65 | `box_breathing` (overrides plexus) |
| 4–5 | confirmed | < 0.65 | `silent_meditation` |
| 4–5 | confirmed | ≥ 0.65 | `resonance_hold` (fallback) |

### Session Outcome Schema

```python
@dataclass
class SessionOutcome:
    session_id:              str
    session_date:            date
    duration_minutes:        int
    practice_type:           str
    attention_anchor:        Optional[str]
    coherence_avg:           Optional[float]   # 0.0–1.0 mean across windows
    coherence_peak:          Optional[float]
    time_in_zone_3_plus:     Optional[float]   # fraction in zone 3 or 4
    session_score:           Optional[float]   # composite 0.0–1.0
    pre_rmssd_ms:            Optional[float]   # session-start 2-min window
    post_rmssd_ms:           Optional[float]
    rmssd_delta_ms:          Optional[float]   # post − pre
    rmssd_delta_pct:         Optional[float]   # delta / personal floor
    arc_completed:           bool
    arc_duration_hours:      Optional[float]
    morning_rmssd_ms:        Optional[float]   # reference only
    windows_valid:           int
    windows_total:           int
    data_quality:            float
    notes:                   list[str]
```

**Session score formula:**
```
session_score = (coherence_avg × 0.40) + (coherence_peak × 0.30) + (time_in_zone_3_plus × 0.30)
```

Three components because a session averaging 0.5 but peaking at 0.9 is different from one that averages 0.5 and never breaks 0.6.

---

## 7. All-Day Tracking (Stress / Recovery / Readiness)

**Status: Locked and Implemented. 574 tests passing.**

### The Core Insight

The autonomic nervous system is a continuous waveform, not a daily number. Stress and recovery are not episodes — they are the normal rhythm of a living system. The right representation is a **continuous waveform**. The score is a summary of that waveform.

### The Three Daily Numbers

Every day the user sees three numbers and one sentence.

```
STRESS LOAD         72             (yesterday — how much ANS stress accumulated)
RECOVERY            85             (yesterday AM → today AM — how much body recharged)
TODAY'S READINESS   71             (net position, calibrated by morning read)
```

### Stress Load (0–100)

How much autonomic stress accumulated from wake to sleep.
- 100 = RMSSD suppressed to personal floor for entire waking day
- 0 = RMSSD never dropped below personal average

**Formula:**
```
waking_minutes = sleep_onset_ts - wake_ts

max_possible_suppression_area =
    (personal_morning_avg_rmssd - personal_rmssd_floor) × waking_minutes

actual_suppression_area =
    Σ max(0, personal_morning_avg_rmssd - window_rmssd) × window_duration_minutes
    for each 5-min BackgroundWindow during waking hours

stress_load = (actual_suppression_area / max_possible_suppression_area) × 100
```

### Recovery Score (0–100)

How much recovery credit deposited from yesterday's morning read to this morning's read. Window deliberately includes sleep — the primary recovery mechanism.

**Weighted contributions:**
- Sleep: weight 0.50 (largest recovery mechanism)
- ZenFlow sessions: weight 0.25
- Daytime recovery windows: weight 0.25

### Readiness (0–100)

Net position, calibrated by today's morning physiological read.

```
net_prior = recovery_score - stress_load         # e.g. 85 - 72 = +13
readiness_prior = 50 + (net_prior / 2)           # centres at 50 → 56.5
morning_calibration = morning_rmssd / personal_morning_avg_rmssd
readiness = clamp(readiness_prior × morning_calibration, 0, 100)
```

The morning read has final say. A net-positive score with a suppressed morning RMSSD produces a lower readiness — the sensor reports the ground truth.

### Day Types (Readiness-Based)

| Day type | Readiness | Physical prescription |
|---|---|---|
| Green day | ≥ 70 | Full training, cardio or strength |
| Yellow day | 45–69 | Light movement only — walk, gentle yoga |
| Red day | < 45 | Rest. ZenFlow session still on (5 min, speeds recovery). |

### Background Window Granularity

5-minute aggregates of background-context HRV. Rationale:
- Enough beats for stable RMSSD (≥ 30 beats at resting 60bpm)
- Fine enough for event detection (10-min spike = 2 windows)
- Produces 144 rows/day for 12h waking day — manageable

### Stress Event Detection Algorithm

**Three conditions must all be met:**
1. RMSSD < 85% of personal morning average (threshold breach)
2. Breach sustained for ≥ 10 minutes (2 consecutive 5-min windows)
3. Rate-of-change > 10% per window OR sustained suppression (acute spike OR chronic load)

**Merge rule:** Adjacent breach sequences with gap ≤ 5 min are merged into one event.

**Minimum contribution for nudge:** 3% of daily stress capacity.

**Physical vs emotional differentiation:**
- ACC/Gyro mean above `MOTION_ACTIVE_THRESHOLD` → `tag_candidate = "physical_load"`
- Low/no motion → `tag_candidate = "stress_event"`
- User confirmation converts candidate to confirmed tag.

### Recovery Window Detection Algorithm

A sustained period where RMSSD is at or above personal morning average for ≥ 15 minutes (3 consecutive 5-min windows).

**Auto-tag rules (high confidence, no user input):**
- ZenFlow session → "zenflow_session"
- Sleep-context windows → "sleep"
- Post-stress-window uplift → "post_stress_recovery"
- Other → "recovery_window" (gentle prompt to user)

### Nudge Design — Spike-Triggered, Post-Event

**Maximum 3 tagging nudges per day** — hard cap.

- Always post-event (sent after stress window closes, not during)
- User has context and is calm enough to respond accurately

**Significant spike override:** If a single event contributes > 25% of daily capacity, one nudge fires even if the 3-nudge cap was reached.

**Nudge tone:**
- Not alarming: "Active period around 3:15pm — workout or something else?"
- Never pressuring: "Tag?" not "Please tag this event"
- Recovery nudge (softer): "Your body settled around 5:30pm — what helped?"

### Wake/Sleep Boundary Detection (3-Priority Chain)

**Wake time (priority order):**
1. `"sleep_transition"` — bridge context changes sleep→background
2. `"historical_pattern"` — `PersonalModel.typical_wake_time` (rolling 14-day median)
3. `"morning_read_anchor"` — morning read timestamp

**Sleep time (priority order):**
1. `"sleep_transition"` — background→sleep context
2. `"historical_pattern"` — `PersonalModel.typical_sleep_time` (rolling 14-day median)
3. `"last_background"` — last active background window + 30-min buffer

**Gap handling:**
- < 30 min: continuity assumed, no note
- 30 min – 2 hr: shown as "device not worn" in itemized view, score partial
- > 2 hr: grey block on waveform, score footnoted as "partial data"

### Tracking Layer Modules

| Module | Role |
|---|---|
| `background_processor.py` | Raw background metrics → 5-min BackgroundWindow aggregates |
| `stress_detector.py` | BackgroundWindow stream → StressWindow events |
| `recovery_detector.py` | BackgroundWindow stream → RecoveryWindow events |
| `daily_summarizer.py` | All windows → DailyStressSummary (3 scores) |
| `wake_detector.py` | Wake/sleep boundary from context transitions + history |

---

## 8. Tagging System

### Purpose

Tags connect physiological events (stress windows, recovery windows) to the human activities that caused them. Over time, the tag database builds a personal pattern model that enables auto-tagging, coach prescriptions informed by real activity data, and adherence tracking.

### Scenario A — Event Detected (Priority Chain)

When a stress window or recovery window is detected, attribution flows through a priority chain:

**Tier 1 — Auto-model tag (Day 14+)**
- Conditions: confidence ≥ 0.75, ≥ 4 prior confirmations for this pattern
- Source label: `"auto_model"`
- Shown in UI with lighter colour and ✓ confirmation option
- User can override → override updates the pattern (degrades confidence)

**Tier 2 — AI-initiated conversation**
- Fires when auto-model confidence < 0.75 OR pattern < 4 confirmations
- Proactive message from Conversationalist into the coaching chat
- Example: "Your body had an active period around 3pm — were you working out?"
- User responds in chat → tag created with source `"ai_conversation"`

**Tier 3 — Nudge push notification (2h timeout from Tier 2)**
- If no response to AI message within 2 hours
- Push notification: "Active period around 3:15pm — workout or something else?"
- 4-tap Tag Sheet: Workout / Work/calls / Argument-difficult / Walk-nature
- Source: `"nudge_tap"`

**Tier 4 — Manual tag from itemized view (retroactive up to 7 days)**
- User opens Stress Detail or Recovery Detail screen
- Taps untagged event → Tag Sheet bottom sheet
- Source: `"manual_itemized"`

### Scenario B — No Event Detected (Plan Adherence Check)

When a DailyPlan has an item and **no matching event is detected**, the Conversationalist asks once.

**Flow:**
1. Intraday Plan Matcher fires at target_end_time + 30min: "Did you complete your [activity]?"
2. Two options: ✓ Done / ✗ Not today
3. If **"Done"** → retrospective tag created; source `"retrospective"`. System notes signal-absent pattern for TagPatternModel learning.
4. If **"Not today"** → `PlanDeviation` record created. Coach can ask brief reason (or skip — see deviation section).
5. If **no response within 2 hours** → nudge fires once
6. If **still no response** → evening Assessor infers miss. Deviation logged as `source = "assessor_inferred"`.

**Design principle: "Don't be too nosy."** One ask, one nudge, then the Assessor handles at end-of-day. The system never harasses.

### Tag Schema

```python
class Tag(Base):
    id:                     str           # UUID
    user_id:                str
    activity_type_slug:     str           # FK → ActivityCatalog.slug
    started_at:             datetime
    ended_at:               datetime
    source:                 str           # "auto_model" | "ai_conversation" | "nudge_tap"
                                          # | "manual_itemized" | "manual_plan" | "retrospective"
    confidence:             float         # 0.0–1.0 (auto_model only; 1.0 for manual)
    linked_stress_window_id:  Optional[str]   # FK → StressWindow
    linked_recovery_window_id: Optional[str]  # FK → RecoveryWindow
    linked_plan_item_id:    Optional[str]     # FK → PlanItem
    linked_session_id:      Optional[str]     # FK → SessionOutcome
    user_confirmed:         bool
    deviation_reason:       Optional[str]     # free text from user
    deviation_category:     Optional[str]     # "time_constraint"|"fatigue"|"external"|"motivation"
```

### TagPatternModel

The system's learned database of when/what this user does.

```python
class TagPatternModel(Base):
    id:                 str
    user_id:            str
    activity_type_slug: str       # FK → ActivityCatalog.slug
    day_of_week:        int       # 0 = Monday, 6 = Sunday
    hour_of_day:        int       # 0–23 (local time)
    confirmation_count: int       # number of confirmed events at this pattern
    miss_count:         int       # number of inferred misses
    confidence:         float     # grows with confirmations, decays with misses
    last_confirmed_at:  datetime
    last_missed_at:     Optional[datetime]
    is_suspended:       bool      # True when drift detection fires
```

**Pattern confidence mechanics:**
- Each confirmation: `confidence = min(1.0, confidence + 0.15)`
- Each miss: `confidence = max(0.0, confidence - 0.10)`
- Minimum for auto-tagging: confidence ≥ 0.75 AND confirmation_count ≥ 4

**Pattern drift detection:**
- 3 consecutive misses at same pattern slot → `is_suspended = True`
- Conversationalist asks: "I noticed you haven't been doing [activity] at [time] lately — has something changed?"
- User confirms change → pattern updated or retired
- User confirms still relevant → suspension lifted

**Auto-tag threshold: Day 14 minimum (lowered from 28), 4 confirmations minimum.**

---

## 9. Activity Catalog

### Purpose

A seed reference table of activities the coach and tagging system can work with. The LLM can propose new activity types to add; additions require engineering review before seeding.

### ActivityCatalog Schema

```python
class ActivityCatalog(Base):
    slug:                   str   # Primary key — unique identifier
    display_name:           str   # Human-readable name shown in UI
    category:               str   # See categories below
    stress_or_recovery:     str   # "stress" | "recovery" | "mixed"
    metric_schema:          dict  # Per-activity measurable fields
    evidence_signals:       list  # What tracking signals count as adherence
    requires_session:       bool  # True if ZenFlow session = adherence
    typical_duration_minutes: int
    recoverable_signal:     bool  # False for outdoor/non-wrist (can miss ACC signal)
```

### Categories

| Value | Description |
|---|---|
| `movement` | Physical exercise — elevates HR, typically stress-tagged |
| `zenflow_session` | Guided coherence breathing session in-app |
| `mindfulness` | Non-ZenFlow mindfulness practice (meditation apps, etc.) |
| `habitual_relaxation` | Activities that produce recovery signal (reading, music, etc.) |
| `sleep` | Sleep and nap |
| `recovery_active` | Active recovery — low intensity movement, stretching, cold exposure |

### Seed Catalog

| Slug | Display | Category | Stress/Recovery | Recoverable |
|---|---|---|---|---|
| `running` | Running | movement | stress | True |
| `weight_training` | Weight training | movement | stress | True |
| `cycling` | Cycling | movement | stress | False |
| `swimming` | Swimming | movement | stress | False |
| `walking` | Walking | movement | mixed | True |
| `yoga` | Yoga | recovery_active | recovery | True |
| `coherence_breathing` | ZenFlow session | zenflow_session | recovery | True |
| `meditation` | Meditation | mindfulness | recovery | True |
| `book_reading` | Reading | habitual_relaxation | recovery | True |
| `music` | Music / listening | habitual_relaxation | recovery | True |
| `journaling` | Journaling | mindfulness | recovery | True |
| `cold_shower` | Cold shower | recovery_active | recovery | True |
| `nap` | Nap | sleep | recovery | True |
| `sleep` | Sleep | sleep | recovery | True |
| `work_sprint` | Work block | movement | stress | True |
| `commute` | Commute | movement | mixed | True |
| `hiking` | Hiking | movement | mixed | False |
| `social_time` | Social time | habitual_relaxation | recovery | False |
| `entertainment` | Movie / TV | habitual_relaxation | recovery | False |
| `nature_time` | Time in nature | recovery_active | recovery | True |
| `sports` | Sports / games | movement | stress | True |

> **`social_time` / `entertainment`:** No sensor signal — coach asks proactively ("Did you go out last night?") to build context and relationship, not to tag.
>
> **`nature_time`:** Low ACC movement + recovery window likely present. Prescribable as genuine recovery.
>
> **`sports`:** User-defined via onboarding `movement_enjoyed` (pickleball, tennis, basketball, etc.). If consistently drives high `stress_contribution_pct` + slow next-day recovery → enters CoachContext as known stressor → next prescription adapts.

### evidence_signals and metric_schema (examples)

**running** — `metric_schema`: `{duration_min, distance_km, hr_zone}`. `evidence_signals`: `["acc_high_motion", "hr_elevated", "stress_window_present"]`

**coherence_breathing** — `metric_schema`: `{duration_min, coherence_avg, session_score}`. `evidence_signals`: `["linked_session_id"]`. `requires_session: true`

**book_reading** — `metric_schema`: `{duration_min}`. `evidence_signals`: `["low_motion", "recovery_window_present"]`. `recoverable_signal: true`

---

## 10. AI Coach

### Architecture Principle

**The LLM writes sentences. Python makes all decisions.**

Every coaching decision — what to recommend, what tone, whether to push or console, what signals are relevant — is made by deterministic Python logic before the LLM is called. The LLM assembles pre-digested, personal-baseline-relative information into language that sounds like a person said it specifically to you.

### Three LLM Jobs

| Job | Trigger | Input | Output |
|---|---|---|---|
| **Prescriber** | Morning (on morning read arrival, or 7am) | CoachContext | DailyPlan (Pydantic-validated JSON) |
| **Assessor** | Evening (sleep boundary or 10pm) | DailyPlan items + full evidence bundle | Adherence scores (0.0–1.0) + reasoning + deviation records |
| **Conversationalist** | Every user message + proactive triggers | CoachContext + conversation history | Reply text + sidecar JSON |

**Fallback:**
- Prescriber LLM failure → archetype template fills DailyPlan
- Assessor LLM failure → all items marked `adherence_score = null`, retry next morning
- Conversationalist LLM failure → "I'm having trouble right now. Check back in a moment." (local template)

### Two Loops

**Intraday loop (event-driven):**
- Tag confirmed → Intraday Plan Matcher fires → plan item ticked → adherence % updated
- Conversation turn → Conversationalist responds + optional plan delta

**Daily loop (scheduled):**
- Morning: Prescriber generates DailyPlan
- Evening: Assessor evaluates plan adherence from evidence bundle

### CoachContext Packet

The full context assembled before any LLM call.

```python
@dataclass
class CoachContext:
    # ── Identity ──────────────────────────────────────────────────────────
    user_name:              str
    archetype_primary:      str           # "hustler"
    pattern_label:          str           # "The Hustler"
    pattern_summary:        str           # 1-sentence description
    stage_in_words:         str           # "Stage 1 — recovery completing but slowly"
    weeks_in_stage:         int
    flexibility_setting:    str           # "high" | "medium" | "low"

    # ── Today (personal-relative strings — no raw numbers) ────────────────
    today_rmssd_vs_avg:     str           # "-21% vs your average"
    today_rmssd_vs_floor:   str           # "12% above your floor"
    morning_read_quality:   str           # "good" | "borderline" | "low"
    readiness_score:        int           # 0–100
    day_type:               str           # "green" | "yellow" | "red"

    # ── Rolling summaries (window = flexibility setting) ──────────────────
    rolling_summaries:      list[DailyStressSummary]  # N days (high=3, medium=7, low=14)
    consecutive_low_days:   int
    load_trend:             str           # plain English

    # ── Current plan ──────────────────────────────────────────────────────
    current_plan:           Optional[DailyPlan]

    # ── Recent tags (confirmed, from rolling window) ───────────────────────
    recent_tags:            list[Tag]

    # ── Conversation context ───────────────────────────────────────────────
    conversation_history:   list[dict]    # last N turns
    rolling_summary:        Optional[str] # max 300 words after turn 3

    # ── Adherence trend ───────────────────────────────────────────────────
    adherence_trend:        dict          # {per_category_7d: dict, trend_direction}

    # ── Habit events (last 72h) ────────────────────────────────────────────
    recent_habit_events:    list[str]     # ["alcohol event 2 nights ago (moderate)"]

    # ── Milestone (if detected) ────────────────────────────────────────────
    milestone:              Optional[str]
    milestone_evidence:     Optional[str]  # specific number if celebrating

    # ── Trigger + tone ────────────────────────────────────────────────────
    trigger_type:           str           # "morning_brief" | "plan_assessment" | etc.
    tone:                   str           # "push" | "compassion" | "celebrate" | "warn"
```

**Rolling window per flexibility setting:**
| Setting | Rolling window | Plan rigidity | Adaptation speed |
|---|---|---|---|
| High | 3 days | Soft targets, recommended | Single-day feedback shifts plan |
| Medium | 7 days | Mix must-do + recommended | 2–3 day trend needed |
| Low | 14 days | More must-do | Consistent pattern required |

### Tone Selection — Deterministic, Pre-LLM

| Tone | Condition |
|---|---|
| `CELEBRATE` | Milestone detected OR NS score +5 in 7 days — overrides all others |
| `WARN` | 2+ consecutive below-floor reads OR lf_hf_resting > 2.8 trending up |
| `COMPASSION` | Score declining AND (external stressor flagged OR 2+ below-floor reads) |
| `PUSH` | Trajectory improving + capacity present + no warn/celebrate condition |

One tone per message. `CELEBRATE` beats everything. `WARN` beats `PUSH`. `COMPASSION` and `PUSH` are mutually exclusive.

### DailyPlan Schema

```python
@dataclass
class DailyPlan:
    id:                     str
    user_id:                str
    plan_date:              date
    generated_by_llm:       str           # model + prompt version
    flexibility_setting:    str           # snapshot of user's setting at time of generation
    context_snapshot_id:    str           # FK → CoachContext snapshot stored for auditability
    items:                  list[PlanItem]

@dataclass
class PlanItem:
    id:                     str
    category:               str           # "movement" | "zenflow_session" | "mindfulness"
                                          # | "habitual_relaxation" | "sleep" | "recovery_active"
    activity_type_slug:     str           # FK → ActivityCatalog.slug
    title:                  str           # human-readable: "Evening run" or "ZenFlow session"
    target_start_time:      Optional[str] # "HH:MM"
    target_end_time:        Optional[str] # "HH:MM"
    duration_minutes:       int
    priority:               str           # "must_do" | "recommended" | "optional"
    rationale:              str           # 1 sentence — why this item today
    evidence_signals:       list[str]     # what will count as adherence
    adherence_result:       Optional[AdherenceResult]  # filled by Assessor at day-end
```

**DailyPlan guardrails (enforced by schema validator before LLM response is accepted):**
- Maximum items: [TBD — see Section 11]
- Each item must reference a valid ActivityCatalog slug
- `must_do` items capped at [TBD]
- `rationale` max 25 words
- `target_start_time` required for `must_do` items, optional for `recommended`

### Adherence Result Schema

```python
@dataclass
class AdherenceResult:
    plan_item_id:           str
    adherence_score:        float         # 0.0–1.0 — subjective/partial, not binary
    confirmed_tags:         list[str]     # tag IDs that count as adherence evidence
    assessor_reasoning:     str           # 1–2 sentences explaining the score
    deviation_id:           Optional[str] # FK → PlanDeviation if one was created
```

**Adherence scoring is subjective and partial (0.0–1.0), not binary.** A 20-minute walk on a green day when 30 minutes was prescribed scores ~0.7, not 0.0 or 1.0. The Assessor uses the full evidence bundle — tags, session outcomes, conversation context — and applies judgment to arrive at a score with reasoning.

### PlanDeviation Schema

```python
@dataclass
class PlanDeviation:
    id:                     str
    plan_item_id:           str
    user_id:                str
    deviation_date:         date
    reason_text:            Optional[str]  # from user conversation or assessor
    reason_category:        str           # "time_constraint" | "fatigue" | "external" | "motivation"
    source:                 str           # "conversation" | "user_tag" | "assessor_inferred"
    impact_on_tomorrow:     Optional[str] # brief plain-English note for Prescriber context
```

### Intraday Plan Matcher (Deterministic — Not LLM)

Fires when a tag is confirmed. Matches against DailyPlan items by:
1. `activity_type_slug` match (exact or same category if slug not found)
2. Time proximity — confirmed tag time within ±90 minutes of `target_start_time`

On match:
- Marks PlanItem as "has_evidence"
- Updates running adherence % displayed in plan view
- Triggers Conversationalist confirmation if match is high confidence ("Your run just ticked off your movement block for today.")

On Scenario B (no detection, plan item time passed):
- Fires at `target_end_time + 30min`
- Conversationalist asks once
- 2h timeout → nudge
- Evening: Assessor handles

### Plan Update Ownership

| Change type | Who decides | User sees |
|---|---|---|
| Minor timing adjustment | Coach, silent | Small "updated" badge |
| Routine swap within category | Coach, silent + informs | Chat message from Coach |
| Significant change (e.g., rest day replacing training day) | Coach proposes | One-tap approval prompt |
| User-requested change | User initiates in chat | Plan updates with confirmation |

### Conversationalist — Sidecar JSON

Every Conversationalist response includes a sidecar alongside natural language:

```json
{
  "reply": "Got it. I've moved your session to before your presentation — not this evening. 5 minutes will change how you show up.",
  "sidecar": {
    "tag": null,
    "deviation": null,
    "plan_signal": {
      "item_id": "item_abc",
      "action": "reschedule",
      "new_start_time": "08:45"
    },
    "confidence": 0.92
  }
}
```

The sidecar is processed by the API layer to update DailyPlan, create Tags, or create PlanDeviations without additional LLM calls.

### Framework Enforcement — Four Independent Layers

**Layer A — Persona contract (system prompt, every call):**
```
Who you are: A coach who understands physiology but speaks like a person.
You have this user's physiological history and reference it specifically.

What you never do:
- Prescribe, diagnose, or suggest medical action
- Use generalities: "great work", "keep it up", "you're doing amazing"
- Use clinical terms: cortisol, parasympathetic, LF/HF, vagal tone, autonomic
- Give encouragement without a specific number — if no delta exists, leave it blank
- Give more than one action
- Ask more than one question

Language rules:
- B2 level maximum
- Present tense: "your body is..." not "your HRV suggests..."
- Reference personal baseline, not population norms
- Short sentences. No compound clauses.

Tone is a constraint, not a suggestion. If tone = compassion, you do not push.
```

**Layer B — JSON mode:** LLM called with function_calling / tool_use — schema-typed at API level.

**Layer C — `schema_validator.py`:**

| Check | Rule | On failure |
|---|---|---|
| Schema conformance | All required fields present | Retry ×2 → static fallback |
| `summary` word count | 20–45 words | Retry |
| `action` word count | 10–28 words | Retry |
| Clinical term blocklist | 40-term scan | Retry |
| `encouragement` specificity | Must contain a digit if non-empty | Blank field |
| Superlative filter | "amazing", "fantastic", "proud of you" | Blank or retry |
| Medical advice pattern | "see a doctor" | Safety route |

**Layer D — Template pre-framing:** Before context is passed, each trigger prepends constraints:
```
Trigger: morning_brief | Tone: COMPASSION | Stage: 1
Constraint: action must relate to recovery — no physical load increase
Encouragement evidence (if milestone): "coherence floor 0.28 → 0.41 over 3 weeks"
```

### Safety Filter (Non-Negotiable)

`safety_filter.py` scans ALL input AND output. Clinical distress signals (hopelessness, harm-related language) trigger immediate warm handoff:

> "I hear you. What you're describing sounds like more than stress — and that matters. ZenFlow can support your physical recovery, but for what you're feeling right now, talking to someone directly would help more. [Find support →]"

Conversation locks for session after safety trigger fires.

### Conversation Architecture

```python
@dataclass
class ConversationState:
    conversation_id:      str
    user_id:              str
    turn_index:           int
    started_at:           datetime
    trigger_context:      str
    rolling_summary:      str         # max 300 words — replaces full history after turn 3
    accumulated_signals:  list[str]
    plan_delta_net:       dict
    safety_triggered:     bool
```

Each turn runs two parallel processes:
1. **LLM call** → conversational response
2. **`conversation_extractor.py`** → structured signals from user message (does not block response)

Extractor writes to signal tables. "I've been stressed for two weeks" updates `stress_fingerprint` — lower confidence weight, same schema as HRV data.

**Voice:** Apple Speech → text (on-device, audio never leaves device). Coach returns text → TTS via AVSpeechSynthesizer (offline) or ElevenLabs (online).

**Conversation closes when:**
- User dismisses
- 5 minutes no input
- Safety filter fires
- Coach returns `follow_up_question: null`

### Offline — Three-Tier Fallback

**Tier 1 — Pre-computed (default):** Morning brief computed server-side 30 min after morning read arrives, pushed + cached. Covers >95% of offline scenarios.

**Tier 2 — `local_engine.py`:** Deterministic template engine from `stage_focus` + `DailyPrescription` reason tag. No LLM. Structurally identical output, lower specificity.

**Tier 3 — Sessions always offline:** All recording, PPI processing, RSA, coherence — entirely local. Queues + syncs on reconnect.

---

## 11. Daily Plan Design

### Philosophy

Plans are personal and enjoyable, not clinical protocols. The coach prescribes what matches this user's preferences from onboarding (`movement_enjoyed`, `decompress_via`). A plan feels like a personal coach wrote it specifically for you — because that's the only way someone follows it.

The coach proactively follows up on lifestyle items conversationally — not for tagging, for the relationship and pattern learning. "Did you go out last night? How was it?" is a question a friend asks. It builds the model without feeling like data collection.

**Sports overload learning:** If a `sports` activity consistently produces high `stress_contribution_pct` with slow next-day recovery, it enters CoachContext as a known stressor. The next prescription adapts: "No games today — yesterday pushed your system hard."

**Alcohol + social context:** Contextually intelligent, not prohibitive. The coach doesn't moralize or restrict. If a pattern correlates with degraded readiness, it surfaces that connection specifically and without judgment — once.

---

### Plan Inputs (25 total)

**Fixed profile (rarely changes):**
1. Archetype primary pattern
2. Stage (0–5) — gates practice tier
3. Flexibility setting (high / medium / low)
4. Movement preferences from onboarding (`movement_enjoyed`)
5. Decompress preferences from onboarding (`decompress_via`)
6. `compliance_best_window` (PersonalModel)
7. `interoception_gap`
8. PRF status + current unlocked practice type
9. `stage_focus` from NSHealthProfile

**Today's physiological state:**
10. Readiness score
11. Day type (green / yellow / red)
12. Morning RMSSD quality (good / borderline / low)
13. Today's RMSSD vs personal morning average (%)

**Rolling history (window = flexibility setting):**
14. DailyStressSummary rolling N days (high=3, medium=7, low=14)
15. `consecutive_net_negative_days`
16. Yesterday's top stress trigger
17. Yesterday's top recovery source

**Behavioral signals:**
18. Confirmed tags last 7 days
19. Adherence trend per category last 7 days
20. Deviation `reason_category` history
21. Day of week
22. Available time windows (wake / sleep times + known commitments)

**Recent context:**
23. Habit events last 72h
24. Conversation signals accumulated
25. `plan_delta_net` from recent conversations

---

### Plan Structure by Day Type

```
GREEN DAY (Readiness ≥ 70) — 3 items
  must_do    │ ZenFlow session (full, ~20 min)
  recommended│ Physical activity OR sport (from preferences)
  optional   │ Enjoyable recovery (cold shower, social time, entertainment, nature)

YELLOW DAY (Readiness 45–69) — 2–3 items
  must_do    │ ZenFlow session (shorter, ~10 min)
  recommended│ Light movement only (walk, yoga) OR enjoyable social / passive recovery
  optional   │ Passive enjoyment (movie, time with friends)

RED DAY (Readiness < 45) — 2 items
  must_do    │ ZenFlow session (minimum, ~5 min)
  recommended│ Genuine rest — cold shower, movie, dinner out, something enjoyable
```

---

### Prescriber Rules

- ZenFlow session is always `must_do` — even on red days. Minimum 5-min coherence breathing is the minimum effective dose for ANS recovery.
- No physical intensity increase when `consecutive_net_negative_days ≥ 3`.
- No two high-intensity physical items in a single day.
- If `reason_category = "time_constraint"` recurs 3+ times → reduce duration targets, do not cancel the activity.
- If adherence < 50% on a category for 7 days → deprioritize that category. The plan was too ambitious.
- Sports are prescribed from `movement_enjoyed`. If a sport slug consistently drives high `stress_contribution_pct` + slow next-day recovery → flagged in CoachContext → next day prescription omits it with explanation.

---

### Scientific Basis

1. **HRV-guided training** (Buchheit, Plews, Kiviniemi) — prescribing exercise when HRV is suppressed impairs adaptation. ZenFlow day type directly implements this protocol.
2. **Minimum effective dose** — even a 5-min coherence breathing session measurably accelerates ANS recovery. Never skip; always scale down.
3. **Social connection and HRV recovery** — social bonding measurably improves HRV recovery via the oxytocin pathway. Social time is a genuine recovery prescription.
4. **Vagal rebound post cold exposure** — cold shower produces the strongest vagal rebound available outside a ZenFlow session.
5. **Progressive overload in ANS training** — stage gates ensure practice difficulty increases only when capacity has been demonstrated.

---

## 12. Outcomes Engine

### Level Gate Criteria (Adherence + Readiness-Gated, Not Physiology-Gated)

> **Why this exists:** Every ZenFlow practice prescription is stage-gated (Section 6). A Stage 0 user gets `ring_entrainment`. A Stage 2 user gets `plexus_hold`. A Stage 4 user gets `silent_meditation`. The level gate is the only mechanism that advances a user through tiers — it directly drives the Journey Map's locked/unlocked state, the morning "Stage Unlocked" screen, and the coach's plan composition. Without it, practice progression never happens.

Stage advancement reflects demonstrated habit and nervous system improvement — not rigid physiological thresholds. Three gates must all pass simultaneously.

---

#### Gate 1 — Adherence (primary)

≥ 60% of prescribed ZenFlow sessions completed in the last 10 prescribed sessions.

Advancement cannot happen if the user hasn't been showing up. This is the single most predictive gate.

---

#### Gate 2 — Readiness Trend (primary)

14-day rolling average readiness ≥ 5 points higher than the prior 14-day average.

Confirms the nervous system is actually improving — not just having good days. Captures the compound effect of consistent practice on baseline ANS tone.

---

#### Gate 3 — Session Quality (soft check — not a hard block)

Average session score ≥ 0.25 across qualifying sessions.

Not a hard blocker. If failing, triggers a coach conversation: "Let's look at what's happening in your sessions." The goal is diagnosis, not punishment.

---

#### Minimum Session Floor (safety only — absolute floor, not primary gate)

| Transition | Min sessions (floor only) |
|---|---|
| 0 → 1 | 2 |
| 1 → 2 | 6 |
| 2 → 3 | 12 |
| 3 → 4 | 18 |
| 4 → 5 | 24 |

A user cannot advance on 2 sessions even if both are perfect. But adherence and readiness trend are the primary test — the floor counts prevent advancement on statistically insufficient data only.

---

#### Conversation Signal Suppression

Conversation signals (e.g., user said "I'm overwhelmed" recently) can only **suppress** advancement — they never trigger it. A gate hold is surfaced to the user via a coach message.

---

`LevelGateResult` returns: `ready: bool`, `current_stage: int`, `criteria_met: dict[str, bool]`, `blocking: list[str]`.

### Model Write-Back

Session outcomes stores results only. `api/services/model_service.py` recomputes `PersonalFingerprint` from all stored sessions on a schedule. Session outcomes never directly mutates the fingerprint.

---

## 13. API Layer

### Endpoints (Complete)

| Method | Path | Description |
|---|---|---|
| `WS` | `/ws/stream` | Live hardware stream from bridge |
| `POST` | `/session/start` | Begin guided session |
| `POST` | `/session/end` | End session, trigger outcome computation |
| `GET` | `/session/{id}/result` | Session outcome + score |
| `GET` | `/coach/morning-brief` | Today's personalised synthesis + action |
| `GET` | `/coach/post-session` | Post-session coaching message + score |
| `POST` | `/coach/conversation` | Send user voice/text input, receive reply + plan delta |
| `GET` | `/coach/conversation/history` | Past conversation turns |
| `GET` | `/user/profile` | User profile + preferences |
| `GET` | `/user/archetype` | Current archetype + evolution history |
| `GET` | `/user/habits` | User habit profile |
| `PUT` | `/user/habits` | Update habit profile |
| `GET` | `/outcomes/report-card` | Weekly report card |
| `GET` | `/outcomes/weekly` | Weekly outcome metrics |
| `GET` | `/outcomes/monthly` | 30-day progress |
| `GET` | `/plan/today` | Today's DailyPlan |
| `GET` | `/plan/week` | Week's planned items |
| `POST` | `/plan/check-in` | Submit 3-day subjective self-report |
| `POST` | `/plan/approve-change` | Approve a significant plan change proposed by coach |
| `GET` | `/tracking/daily-summary` | Today's Stress Load, Recovery, Readiness + waveform |
| `GET` | `/tracking/daily-summary/{date}` | Historical day's summary |
| `GET` | `/tracking/waveform/{date}` | Full 5-min BackgroundWindow series |
| `GET` | `/tracking/stress-windows/{date}` | All stress events for a day |
| `GET` | `/tracking/recovery-windows/{date}` | All recovery contributions |
| `POST` | `/tracking/tag-window` | User submits or updates a tag |
| `GET` | `/tracking/history` | Multi-day summary (date range) |
| `GET` | `/tagging/tags` | User's tag history |
| `POST` | `/tagging/tag` | Create or update a tag manually |
| `GET` | `/tagging/patterns` | TagPatternModel entries for user |

### Services

| Service | Responsibility |
|---|---|
| `session_service.py` | Orchestrates processing pipeline during live session |
| `model_service.py` | CRUD for personal model, fingerprint updates |
| `coach_service.py` | Assembles CoachContext, calls LLM jobs, returns output |
| `conversation_service.py` | Manages conversation state, extractor, plan deltas |
| `outcome_service.py` | Runs outcome computations on schedule + on demand |
| `tracking_service.py` | Orchestrates tracking layer, writes windows + summaries |
| `tagging_service.py` | Tag CRUD, TagPatternModel updates, auto-tag logic |
| `plan_service.py` | DailyPlan CRUD, plan item updates, deviation records |

---

## 14. UI & Experience Design

### Key Screens Summary

#### Home Screen (Daily)

Three numbers + one sentence. Nothing else above the fold.

```
┌─────────────────────────────────┐
│  Good morning, Pratik.   07:34  │
├─────────────────────────────────┤
│  YESTERDAY                      │
│  ┌─────────┐ ┌─────────┐        │
│  │ STRESS  │ │RECOVERY │        │
│  │   72    │ │   85    │        │
│  │peaked 3p│ │sleep did│        │
│  └─────────┘ └─────────┘        │
│           TODAY                 │
│    ┌─────────────────┐          │
│    │   READINESS     │          │
│    │       71        │          │
│    │   strong start  │          │
│    └─────────────────┘          │
│  "You absorbed a hard day       │
│   and came back close to full." │
├─────────────────────────────────┤
│  TODAY'S SESSION                │
│  ◉  Breathing · Best at 7pm    │
│  [ Start now ]                  │
└─────────────────────────────────┘
```

Tapping any number → its detail screen.

#### Stress Detail Screen

- Waveform: RMSSD normalized to personal average (1.0 line = your average)
- Below-line shaded fill = stress debt area
- Colour bands for each labeled event
- Itemized table sorted by contribution %, largest first
- Untagged rows show "Untagged — Tag?" in accent colour → taps to Tag Sheet
- "Smaller events" row collapses events below 5% contribution

#### Recovery Detail Screen

- Same waveform style, above-line area filled green
- Sleep contribution shown first (dominant mechanism)
- ZenFlow sessions auto-tagged with session icon
- Untagged recovery windows: "What were you doing?" (warmer framing)

#### Readiness Overlay Screen

- Both waveforms overlaid: red fill below baseline, green fill above
- Net position: +/− number with plain label
- Morning read as calibration event marker
- One sentence explaining what the number means

#### Tag Sheet (Bottom Sheet)

- Context-adaptive 4 options (stress vs recovery window)
- "Skip for now" always available
- No text input — one tap confirms and closes

#### Plan View (New)

Shows today's DailyPlan items. Each item shows:
- Activity title + icon
- Target time window
- Priority badge (must_do / recommended / optional)
- Adherence status (pending / confirmed / deviation)
- Rationale sentence (coach's one-sentence reason)

Green checkmark appears when Intraday Plan Matcher confirms evidence. Items tick in real-time as tags come in.

**Tapping a confirmed plan item → Activity Detail View.**

Each activity category has its own detail view showing the metrics that are meaningful for that type:

| Category | Metrics shown |
|---|---|
| **ZenFlow session** (any practice type) | Deeplinks to PostSession screen — sync %, zone time breakdown, before → after RMSSD shift, "Your body shifted in X minutes" |
| **Running / cycling / hiking** | Duration, ACC exertion signal, estimated HR zone from HRV, stress or recovery contribution % to day total, "Your body handled it [well / hard — here's why]" |
| **Weight training** | Duration, estimated HR zone, post-session recovery arc initiated (if detected), stress contribution % |
| **Swimming / outdoor cardio** (non-wrist GPS) | Duration only (no ACC signal), estimated load from HR trend, note: "Signal limited — band not on wrist" |
| **Walking** | Duration, ACC step pattern, recovery contribution % if RMSSD was above average during window |
| **Yoga / meditation / mindfulness** | Duration, recovery window generated (duration + contribution %), RMSSD trend during activity |
| **Reading / music / habitual relaxation** | Duration, recovery window linked (if detected), recovery contribution % |
| **Nap** | Duration, RMSSD recovery during nap, recovery contribution % |
| **Sleep** | Sleep duration, recovery contribution % (largest source), note on quality: "Deep restore" / "Light rest" / "Fragmented" based on overnight RMSSD pattern |
| **Work sprint** | Duration, stress contribution %, position on waveform (shown as a band on mini-waveform), any linked recovery window that followed |

For categories with a linked `StressWindow` or `RecoveryWindow`, tapping the detail shows a mini waveform cropped to that activity's time window, so the user can see their body's actual response to that specific thing.

#### History View

Multi-day summary: stress bars, recovery bars, readiness dots. Tap any day → full day detail.

#### Live Session Screen

```
Ring visualizer → BREATHE IN / BREATHE OUT label
In sync %   Zone indicator (Settling / Finding it / In Sync / Flow)
Time remaining   Per-session sync chart at bottom
```

Zones: Zone 1 = Settling (warm grey), Zone 2 = Finding it (soft blue), Zone 3 = In Sync (calm green), Zone 4 = Flow (deep green / gold)

#### Post-Session Screen

- Sync % + bar + "your best this week" context
- Before → After body state comparison
- Coach sentence referencing progress vs N sessions ago
- Tomorrow's plan note

#### Archetype Screen

**Where it fits:** Accessed from a Profile tab (secondary navigation), not the main daily flow. Primary surfaces: (a) the 48-hour reveal (Act 3 — "We've spent 48 hours with your nervous system"), (b) anytime via Profile, (c) the 30-day comparison moment when pattern evolution is shown.

- Pattern name + one-paragraph description first — recognition before numbers
- Five-dimension breakdown shown as bars (Recovery Capacity / Baseline Resilience / Coherence Capacity / Chrono Fit / Load Management) — each with a plain-English sentence
- Amplifier pattern note if present
- Evolution arc: "You came in as a Hustler. You are becoming Dialled-In." (Day 30+)
- Current Stage + what unlocks next

The Archetype Screen is the product's identity layer — the emotional proof that the system knows you specifically.

#### Journey Map Screen

**Where it fits:** Accessible from a Progress tab (alongside multi-day History view). Shows ZenFlow practice progression only — not stress/recovery scores (those are in History). Primary value: practice stage transparency and milestone tracking.

- Current ZenFlow practice stage (0–5), position marked, what tier you're in (Signal / Depth / Internalization)
- Stage unlock criteria: what's met ✓ / what's remaining
- Milestones: completed ✓ / in-progress ◉ / locked 🔒
  - First session, PRF found, first Gate C pass, Stage 1 unlocked, first Flow state, 30-day arc, etc.
- Each stage shows: name, practice type available, what changes, what unlocks next
- Tapping a completed stage shows the date it was unlocked and key session that triggered it

#### Coach Conversation Screen

Persistent icon in bottom nav. Available anytime.

Three modes:
- **Morning check-in:** Coach initiates after morning brief. One open question. Plan updates if context warrants.
- **Reactive:** User initiates any time. "I feel stressed," "I can't do this today" — heard + plan adjusted.
- **Post-session debrief:** Coach prompts after session. Pairs subjective with objective.

Plan-update badge shows when user conversation changes their actual day in real-time.

Voice input: hold-to-speak (never always-on). Transcript shown before response. Text always available.

#### Science Credibility — Three-Layer Rule

- **Layer 1 (user sees):** "Your body is in good sync today."
- **Layer 2 (on tap):** "Measured by Heart Rate Variability (HRV) — used in sports science and clinical research."
- **Layer 3 (deeper tap):** Full clinical explanation. Never forced. Always there for skeptics.

### What the UI Never Does

- Shows a number without a plain-English sentence
- Uses HRV, RMSSD, coherence, or sympathetic in main copy
- Shows more than one primary action per screen
- Punishes missed sessions (always forward-looking)
- Gives the user a decision to make — system recommends, user confirms
- Uses always-on listening
- Lets conversation become therapy — always ends with a clear action or handoff

---

## 15. Full User Journey

### Morning to Night — A Typical Day

**6:50am** — Morning read (band worn overnight). Bridge detects sleep→background context transition. Wake time recorded.

**7:00am** — `DailyStressSummary` partially populated with last night's sleep windows + prior day final scores.

**7:05am** — Prescriber LLM fires. Reads CoachContext (readiness, rolling summaries, recent tags, archetype). Generates DailyPlan.

**7:10am** — User opens app. Home screen shows: yesterday's Stress 72, Recovery 85, today's Readiness 71, one synthesis sentence. Plan items visible below.

**7:12am** — Morning check-in conversation. Coach: "Your body recharged well last night. Big day today?" User: "Yes, big presentation at 9am." Coach: "I've moved your session to 8:45am — 5 minutes before your presentation changes how you show up." Plan badge updates.

**8:45am** — ZenFlow session. 5 minutes, resonance_hold. Post-session screen shows sync %, before/after state shift.

**10:30am–11:15am** — Work block. Background windows detect RMSSD suppression below 85% of morning avg for 3 consecutive windows. `StressWindow` created: `tag_candidate = "stress_event"`.

**11:20am** — Stress window closes (RMSSD recovers). Nudge 1 fires: "Active period around 10:30am — what was happening?" User taps "Work / calls." Tag confirmed: `source = "nudge_tap"`. `TagPatternModel` updated.

**1:00pm** — Recovery window detected (lunch break, RMSSD above avg for 20 min). No nudge needed (under 3-nudge cap). Auto-tagged `"post_stress_recovery"` based on timing pattern.

**3:15pm** — Second stress spike. `StressWindow` created. Auto-model fires because this pattern (Mon/Wed/Fri 3pm work stress) has 5 prior confirmations with confidence 0.81. Auto-tagged `"work_sprint"` with lighter colour, ✓ confirmation option in app.

**5:30pm** — Recovery window (RMSSD above avg, low motion). Recovery nudge: "Your body settled around 5:30pm — what helped?" User taps "Walk / nature." Tag confirmed.

**7:00pm** — Intraday Plan Matcher notices: evening run planned at 6:30pm–7:00pm, no tag confirmed. Conversationalist asks: "Did you get your run in?" — User: "No, ran out of time." `PlanDeviation` created: `reason_category = "time_constraint"`, `source = "conversation"`.

**10:00pm** — Sleep boundary detected (background→sleep context). `DailyStressSummary` finalized: stress_load computed. Assessor LLM fires on day's plan items. Evening run: no tag + user-confirmed deviation → `adherence_score = 0.0`. ZenFlow session: confirmed session with score 0.71 → `adherence_score = 1.0`. Work blocks: partially present (confirmed stress tags) → `adherence_score = 0.9`.

**10:15pm** — `DailyStressSummary` fully populated. Ready for next morning's Prescriber context.

**Next morning** — Readiness finalized after morning read. Tomorrow's DailyPlan generated with yesterday's deviation (missed run) as context. Coach may propose a walk instead if readiness is lower.

### The 30-Day Arc

| Period | What changes |
|---|---|
| Days 1–2 | Band connected, onboarding complete, provisional scores with "est." note |
| Day 3 | First usable baseline, first archetype hypothesis |
| Day 7 | Fingerprint stable, archetype confidence ≥ 0.65 displayed |
| Day 14 | "estimated" removed from scores. Auto-tagging eligible (Day 14 + 4 confirmations). |
| Day 21 | TagPatternModel has enough data for most common activity slots |
| Day 30 | 30-day comparison reveal — the emotional peak. Scores vs Day 1, pattern evolution. |

---

## 16. Database Schema

### Tables

**`users`**
- `id`, `name`, `email`, `created_at`, `flexibility_setting`

**`user_habits`** (onboarding data)
- `user_id`, `movement_enjoyed`, `exercise_frequency`, `alcohol`, `caffeine`, `smoking`, `sleep_schedule`, `typical_day`, `stress_drivers`, `decompress_via`

**`personal_model`** (one row per user, updated continuously)
- `user_id`, `rmssd_floor`, `rmssd_ceiling`, `rmssd_weekday_avg`, `rmssd_weekend_avg`, `rmssd_morning_avg`
- `recovery_arc_hours_mean`, `recovery_arc_hours_fast`, `recovery_arc_hours_slow`
- `stress_peak_day`, `stress_peak_hour`
- `coherence_floor`, `coherence_trainability`, `compliance_best_window`, `interoception_gap`
- `archetype_primary`, `archetype_secondary`, `archetype_confidence_json`
- `stress_capacity_floor_rmssd`, `capacity_version`
- `typical_wake_time`, `typical_sleep_time`
- `prf_bpm`, `prf_status`, `stage`
- `model_version`, `last_updated`

**`background_windows`** (5-min HRV aggregates)
- `id`, `user_id`, `window_start`, `window_end`, `context`
- `rmssd_ms`, `hr_bpm`, `lf_hf`, `confidence`
- `acc_mean`, `gyro_mean`, `n_beats`, `artifact_rate`

**`stress_windows`** (detected stress events)
- `id`, `user_id`, `started_at`, `ended_at`, `duration_minutes`
- `rmssd_min_ms`, `suppression_pct`, `stress_contribution_pct`
- `tag`, `tag_source`, `tag_candidate`
- `nudge_sent`, `nudge_responded`

**`recovery_windows`** (detected recovery events)
- `id`, `user_id`, `started_at`, `ended_at`, `duration_minutes`
- `rmssd_avg_ms`, `recovery_contribution_pct`
- `tag`, `tag_source`
- `zenflow_session_id` (FK, nullable)

**`daily_stress_summaries`** (one per user per day)
- `id`, `user_id`, `summary_date`
- `wake_ts`, `sleep_ts`, `wake_detection_method`, `sleep_detection_method`
- `stress_load_score`, `recovery_score`, `readiness_score`
- `raw_suppression_area`, `raw_recovery_area`
- `capacity_floor_used`, `capacity_version`
- `top_stress_window_id`, `top_recovery_window_id`
- `is_partial_data`, `calibration_days`, `is_estimated`

**`sessions`** (live ZenFlow session records)
- `id`, `user_id`, `started_at`, `ended_at`, `practice_type`, `attention_anchor`, `duration_minutes`
- `pacer_config_json`

**`session_outcomes`**
- `id`, `session_id`, `session_date`, `duration_minutes`, `practice_type`, `attention_anchor`
- `coherence_avg`, `coherence_peak`, `time_in_zone_3_plus`, `session_score`
- `pre_rmssd_ms`, `post_rmssd_ms`, `rmssd_delta_ms`, `rmssd_delta_pct`
- `arc_completed`, `arc_duration_hours`, `morning_rmssd_ms`
- `windows_valid`, `windows_total`, `data_quality`
- `config_version`

**`activity_catalog`** (seed table)
- `slug` (PK), `display_name`, `category`, `stress_or_recovery`
- `metric_schema_json`, `evidence_signals_json`
- `requires_session`, `typical_duration_minutes`, `recoverable_signal`

**`tags`**
- `id`, `user_id`, `activity_type_slug` (FK → activity_catalog)
- `started_at`, `ended_at`
- `source`, `confidence`
- `linked_stress_window_id` (nullable FK), `linked_recovery_window_id` (nullable FK)
- `linked_plan_item_id` (nullable FK), `linked_session_id` (nullable FK)
- `user_confirmed`, `deviation_reason`, `deviation_category`

**`tag_pattern_models`**
- `id`, `user_id`, `activity_type_slug` (FK → activity_catalog)
- `day_of_week`, `hour_of_day`
- `confirmation_count`, `miss_count`, `confidence`
- `last_confirmed_at`, `last_missed_at`, `is_suspended`

**`daily_plans`**
- `id`, `user_id`, `plan_date`
- `generated_by_llm`, `flexibility_setting`, `context_snapshot_id`

**`plan_items`**
- `id`, `plan_id` (FK → daily_plans), `category`, `activity_type_slug` (FK)
- `title`, `target_start_time`, `target_end_time`, `duration_minutes`
- `priority`, `rationale`, `evidence_signals_json`
- `has_evidence`, `adherence_score`, `assessor_reasoning`

**`plan_deviations`**
- `id`, `plan_item_id` (FK), `user_id`, `deviation_date`
- `reason_text`, `reason_category`, `source`, `impact_on_tomorrow`

**`conversations`**
- `id`, `user_id`, `trigger_context`, `started_at`, `ended_at`
- `rolling_summary`, `accumulated_signals_json`, `plan_delta_net_json`
- `safety_triggered`

**`conversation_turns`**
- `id`, `conversation_id` (FK), `turn_index`, `role` ("user"|"coach")
- `content`, `tone`, `sidecar_json`, `created_at`

**`archetype_history`** (snapshots on change)
- `id`, `user_id`, `recorded_at`
- `primary_pattern`, `amplifier_pattern`, `total_score`, `stage`

**`habit_events`** (runtime lifestyle events)
- `id`, `user_id`, `event_type`, `ts`, `source`, `severity`, `notes`

---

## 17. Directory Structure

```
ZenFlow_Verity/
├── config/
│   ├── __init__.py
│   ├── base.py
│   ├── processing.py
│   ├── model.py
│   ├── scoring.py
│   ├── tracking.py
│   ├── coach.py
│   ├── features.py
│   ├── versions.py
│   └── environments/
│       ├── development.env
│       ├── staging.env
│       └── production.env
│
├── bridge/                    (Swift — BLE + hardware streaming)
│   ├── PolarConnector.swift
│   ├── StreamRouter.swift
│   ├── ArtifactFilter.swift
│   ├── WebSocketEmitter.swift
│   └── HealthKitIngester.swift
│
├── processing/                (Python — deterministic signal processing)
│   ├── ppi_processor.py
│   ├── rsa_analyzer.py
│   ├── coherence_scorer.py
│   ├── breath_extractor.py
│   ├── ppg_processor.py
│   ├── motion_analyzer.py
│   ├── recovery_arc.py
│   ├── breath_rate_estimator.py
│   └── artifact_handler.py
│
├── tracking/                  (Python — IMPLEMENTED ✓)
│   ├── __init__.py
│   ├── background_processor.py
│   ├── stress_detector.py
│   ├── recovery_detector.py
│   ├── daily_summarizer.py
│   └── wake_detector.py
│
├── model/                     (Python — personal physiological model)
│   ├── baseline_builder.py
│   ├── personal_distributions.py
│   ├── stress_fingerprint.py
│   ├── recovery_profiler.py
│   ├── coherence_tracker.py
│   ├── compliance_tracker.py
│   ├── interoception_gap.py
│   ├── archetype_classifier.py
│   └── model_store.py
│
├── archetypes/                (Python — NS Health Score engine)
│   ├── scorer.py
│   ├── narrative.py
│   └── __init__.py
│
├── sessions/                  (Python — session prescriber + pacer)
│   ├── __init__.py
│   ├── practice_registry.py
│   ├── pacer_config.py
│   ├── step_down_controller.py
│   ├── session_prescriber.py
│   └── session_schema.py
│
├── tagging/                   (Python — NOT YET IMPLEMENTED)
│   ├── __init__.py
│   ├── tag_service.py         # tag CRUD + confirmation logic
│   ├── pattern_model.py       # TagPatternModel update + confidence math
│   ├── auto_tagger.py         # Pattern-based auto-tagging engine
│   ├── intraday_matcher.py    # Deterministic plan ↔ tag matching
│   └── activity_catalog.py   # Catalog CRUD + seed helpers
│
├── coach/                     (Python — NOT YET FULLY IMPLEMENTED)
│   ├── __init__.py
│   ├── context_builder.py     # Assembles CoachContext
│   ├── prompt_templates.py    # Per-trigger templates
│   ├── tone_selector.py       # Deterministic tone selection
│   ├── coach_api.py           # Pipeline orchestrator
│   ├── schema_validator.py    # Post-generation enforcement
│   ├── safety_filter.py       # Clinical language detection
│   ├── milestone_detector.py  # Meaningful change events
│   ├── memory_store.py        # Conversation state persistence
│   ├── conversation.py        # Turn-taking state machine
│   ├── conversation_extractor.py  # User text → structured signals
│   ├── prescriber.py          # Prescriber LLM job (DailyPlan generation)
│   ├── assessor.py            # Assessor LLM job (evening adherence eval)
│   ├── conversationalist.py   # Conversationalist LLM job + sidecar
│   ├── plan_replanner.py      # Daily prescription + plan update logic
│   └── local_engine.py        # Offline fallback
│
├── outcomes/                  (Python — outcome computation)
│   ├── session_outcomes.py
│   ├── weekly_outcomes.py
│   ├── longitudinal_outcomes.py
│   ├── hardmode_tracker.py
│   ├── report_builder.py
│   └── level_gate.py
│
├── api/
│   ├── main.py
│   ├── routers/
│   │   ├── stream.py
│   │   ├── session.py
│   │   ├── user.py
│   │   ├── coach.py
│   │   ├── outcomes.py
│   │   ├── plan.py
│   │   ├── tracking.py        (IMPLEMENTED ✓)
│   │   └── tagging.py         (NOT YET IMPLEMENTED)
│   ├── services/
│   │   ├── session_service.py
│   │   ├── model_service.py
│   │   ├── coach_service.py
│   │   ├── conversation_service.py
│   │   ├── outcome_service.py
│   │   ├── tracking_service.py  (IMPLEMENTED ✓)
│   │   ├── tagging_service.py
│   │   └── plan_service.py
│   ├── db/
│   │   ├── schema.py          (tracking tables IMPLEMENTED ✓)
│   │   ├── migrations/
│   │   └── seed.py
│   └── config.py
│
├── ui/                        (React + TypeScript)
│   └── src/
│       ├── screens/
│       │   ├── Home.tsx
│       │   ├── StressDetail.tsx
│       │   ├── RecoveryDetail.tsx
│       │   ├── ReadinessOverlay.tsx
│       │   ├── PlanView.tsx
│       │   ├── MorningBrief.tsx
│       │   ├── Session.tsx
│       │   ├── PostSession.tsx
│       │   ├── ReportCard.tsx
│       │   ├── Archetype.tsx
│       │   ├── Journey.tsx
│       │   ├── CheckIn.tsx
│       │   └── CoachConversation.tsx
│       ├── components/
│       │   ├── StressWaveform.tsx
│       │   ├── RecoveryWaveform.tsx
│       │   ├── ScoreCard.tsx
│       │   ├── EventRow.tsx
│       │   ├── TagSheet.tsx
│       │   ├── PlanItemCard.tsx
│       │   ├── AdherenceBadge.tsx
│       │   ├── CoherenceRing.tsx
│       │   ├── ZoneIndicator.tsx
│       │   ├── MetricCard.tsx
│       │   ├── CoachMessage.tsx
│       │   ├── MilestoneToast.tsx
│       │   ├── VoiceInput.tsx
│       │   └── PlanDeltaBadge.tsx
│       ├── hooks/
│       │   ├── useDailySummary.ts
│       │   ├── useStressWindows.ts
│       │   ├── useRecoveryWindows.ts
│       │   ├── usePlan.ts
│       │   ├── useSessionStream.ts
│       │   ├── usePersonalModel.ts
│       │   ├── useCoach.ts
│       │   └── useConversation.ts
│       └── api/
│           └── client.ts
│
├── tests/
│   ├── processing/
│   ├── model/
│   ├── tracking/              (90 tests — IMPLEMENTED ✓)
│   ├── tagging/
│   ├── coach/
│   └── api/
│
├── CONTEXT.md
├── PRODUCT_DESIGN.md
├── ARCHITECTURE.md
├── UI_DESIGN.md
└── DESIGN_V2.md               ← this file
```

---

## 18. Configuration

### Design Rules

1. All configuration lives in `config/` only. No magic numbers anywhere else.
2. Every config value is typed (Pydantic BaseSettings). Wrong type fails at startup.
3. Every config value has a `# downstream:` comment listing dependent modules.
4. Config is versioned. Sessions store which version computed them.
5. Environment overrides via `.env`. Defaults are production-safe.
6. Feature flags are config too.

### Single Import Pattern

```python
from config import CONFIG

window = CONFIG.processing.RSA_WINDOW_SECONDS
threshold = CONFIG.scoring.ZONE_3_MIN
enabled = CONFIG.features.ENABLE_PAV_BREATH
```

### Key Config Values

**`config/processing.py`**
```
RSA_WINDOW_SECONDS:                60
RMSSD_WINDOW_SECONDS:              60
ARTIFACT_MAX_CONSECUTIVE_BEATS:    4
RSA_FREQ_LOW_HZ:                   0.08
RSA_FREQ_HIGH_HZ:                  0.12
PPI_MIN_MS:                        300
PPI_MAX_MS:                        2000
```

**`config/scoring.py`**
```
ZONE_1_MIN:                        0.20
ZONE_2_MIN:                        0.40
ZONE_3_MIN:                        0.60
ZONE_4_MIN:                        0.80
ZONE_WEIGHTS:                      {1: 0.1, 2: 0.3, 3: 0.6, 4: 1.0}
LEVEL_1_COHERENCE_AVG_THRESHOLD:   0.60
RECOVERY_ARC_RETURN_THRESHOLD_PCT: 0.90
HARDMODE_RMSSD_THRESHOLD_PCT:      0.85
```

**`config/tracking.py`**
```
BACKGROUND_WINDOW_MINUTES:         5
STRESS_THRESHOLD_PCT:              0.85
STRESS_MIN_WINDOWS:                2
STRESS_MERGE_GAP_MINUTES:          5
STRESS_RATE_TRIGGER_PCT:           0.10
STRESS_MIN_NUDGE_CONTRIBUTION:     0.03
RECOVERY_THRESHOLD_PCT:            1.00
RECOVERY_MIN_WINDOWS:              3
RECOVERY_WEIGHT_SLEEP:             0.50
RECOVERY_WEIGHT_ZENFLOW:           0.25
RECOVERY_WEIGHT_DAYTIME:           0.25
READINESS_CENTER:                  50.0
READINESS_SCALE:                   0.50
MAX_TAGGING_NUDGES_PER_DAY:        3
NUDGE_SIGNIFICANT_SPIKE_OVERRIDE_PCT: 0.25
GAP_CONTINUITY_MINUTES:            30
GAP_PARTIAL_DATA_MINUTES:          120
MOTION_ACTIVE_THRESHOLD:           0.3
AUTOTAG_MIN_CONFIRMED_EVENTS:      4
AUTOTAG_MIN_DAYS:                  14
```

**`config/coach.py`**
```
LLM_MODEL:                         "gpt-4o"
LLM_TEMPERATURE:                   0.7
LLM_MAX_TOKENS:                    400
TONE_COMPASSION_READINESS_THRESHOLD: 60
COACH_CONTEXT_HISTORY_MESSAGES:    5
MILESTONE_MIN_ARC_IMPROVEMENT_PCT: 0.20
```

**`config/model.py`**
```
BASELINE_DAYS:                     7
BASELINE_MIN_VALID_SESSIONS:       3
DISTRIBUTION_ROLLING_DAYS:         30
ARCHETYPE_MIN_DAYS:                14
ARCHETYPE_CONFIDENCE_THRESHOLD:    0.65
CAPACITY_FULL_ACCURACY_DAYS:       14
```

**`config/features.py`**
```
ENABLE_PAV_BREATH:                 False   (experimental)
ENABLE_SPO2_TREND:                 False   (experimental)
ENABLE_HARDMODE_SESSIONS:          True
ENABLE_RESTLESSNESS_SCORE:         True
ENABLE_AI_COACH:                   True
ENABLE_MONTHLY_REBASELINE:         True
```

---

## Implementation Status

### Implemented (574 tests passing)

| Component | Files | Tests |
|---|---|---|
| tracking/ | background_processor, stress_detector, recovery_detector, daily_summarizer, wake_detector | 90 |
| config/tracking.py | TrackingConfig (28 parameters) | — |
| api/db/schema.py | PersonalModel + 4 new tables | — |
| api/services/tracking_service.py | TrackingService | — |
| api/routers/tracking.py | 7 endpoints | — |
| api/main.py | tracking router registered | — |

### Not Yet Implemented

| Component | Depends on |
|---|---|
| `tagging/` — all modules | tracking tables (done) |
| `api/db/schema.py` — Tag, TagPatternModel, ActivityCatalog, DailyPlan, PlanItem, PlanDeviation tables | tagging design (done) |
| `coach/prescriber.py` | Daily Plan design (TBD Section 11) |
| `coach/assessor.py` | DailyPlan schema (done) |
| `coach/conversationalist.py` | CoachContext (done), sidecar schema (done) |
| `coach/context_builder.py` (expanded) | CoachContext packet (done) |
| `api/routers/tagging.py` | tagging module |
| `api/routers/plan.py` (expanded) | DailyPlan schema |
| `api/services/tagging_service.py` | tagging module |
| `api/services/plan_service.py` | coach module |

---

## Section 15 — Psychological Profile Layer

### 15.1 Overview

The psychological profile captures what physiology alone cannot: *why* stress is rising, *what* calms this specific person down, and *whether* they can feel their own state accurately.

It is built entirely from **inferred signals** — no questionnaires, no explicit prompts. Every dimension is computed from tagged behavioural events correlated with physiological data.

**Coach language rule (inviolable):** The coach NEVER uses RMSSD, RSA, LF/HF, suppression_pct, or any backend metric in conversations. All user-facing numbers are expressed as:
- **Readiness score** (0–100)  
- **Stress score** (0–100)  
- **Recovery score** (0–100)

---

### 15.2 The Six Dimensions

#### Dimension 1: Social Energy Type
**Inference method:** Mean recovery-score delta across all `social_time`-tagged windows.

| Delta | Classification |
|-------|---------------|
| > +4  | Extrovert — social elevates recovery |
| –4 to +4 | Ambivert — social is neutral |
| < –4  | Introvert — social costs energy |

Requires ≥ 3 social_time events for classification. Below threshold: `"unknown"`.

**Coach value:** Prevents prescribing social_time on recovery days for introverts. Suggests social time before high-demand days for extroverts.

---

#### Dimension 2: Anxiety Sensitivity & Trigger Taxonomy
**Inference method:** Mean stress_score at recorded `AnxietyEvent` timestamps, normalised to 0–1.

**Trigger types (12-class taxonomy):**
```
deadline, social_pressure, financial, health_worry, performance,
confrontation, crowds, uncertainty, work_overload, relationship,
change, unknown
```

**Ranking formula:** `strength = (count / total_events) × avg_severity_weight`, normalised so strongest = 1.0.

Triggers are extracted by `conversation_extractor.py` via pattern groups, then stored as `AnxietyEvent` rows.

---

#### Dimension 3: Activity ↔ Physiology Map
**Inference method:** Group `TaggedActivityRecord` rows by slug, compute mean recovery-score delta per activity.

- **top_calming_activities** — activities where `score_delta > 0` (recovery windows with user-confirmed tags), sorted by `avg_score_delta` descending
- **top_stress_activities** — activities where `score_delta < 0` (stress windows), sorted by `abs(avg_score_delta)` descending

Minimum 3 tagged events per activity for inclusion.

**Primary recovery style** is inferred from the top calming slug:

| Slug | Style |
|------|-------|
| social_time | social |
| nature_time | nature |
| cold_shower, cold_plunge | physical |
| nap, sleep | sleep |
| meditation, journaling | mindfulness |
| book_reading, music, entertainment | solo_passive |
| movement category | physical |

---

#### Dimension 4: Discipline Index (0–100)
**Formula:**
```
base = Σ(weight_i × completion_i) / Σ(weight_i) × 100

where:
  completion_i = completed_i / planned_i  (per day)
  weight_i     = 1.0 + (i / n)          (linearly escalates, most recent = 2×)
```

Requires ≥ 7 plan days. Result capped at 100.

**Coach value:** Low discipline_index (<60) → coach de-emphasises challenge, focuses on consistency nudges.

---

#### Dimension 5: Mood Baseline
**Formula:** Rolling average of `MoodLog.mood_score` over last 14 records.

| Average | Label |
|---------|-------|
| ≥ 3.8 | "high" |
| 2.5–3.8 | "moderate" |
| < 2.5 | "low" |

Mood scores are inferred from conversation language by `conversation_extractor.py` (`MoodSignal` dataclass) and from manual mood logs via `POST /psych/mood`.

---

#### Dimension 6: Interoception Alignment
**Formula:** Pearson r between `MoodLog.mood_score` and `DailyStressSummary.readiness_score` over the most recent 14+ paired records.

| r range | Meaning |
|---------|---------|
| 0.6–1.0 | High alignment — user accurately perceives their state |
| 0.2–0.6 | Partial alignment |
| –0.2–0.2 | Misaligned — subjective and physiological don't track |
| < –0.2 | Inverse — user often reports opposite of what body shows |

**Coach value:** Low alignment → coach centres sessions on internal awareness. Insight injected into morning_brief via `psych_insight` field.

---

### 15.3 Data Confidence Model

```
confidence = mean(
  min(social_events / 10, 1.0),
  min(tagged_activities / 20, 1.0),
  min(anxiety_events / 5, 1.0),
  min(mood_records / 14, 1.0),
  min(plan_adherence_days / 28, 1.0),
)
```

At confidence < 0.3, the profile exists but coach_insight defaults to a safe fallback string. Dimensions are individually labelled `"unknown"` until their own minimums are met — a partial profile is always better than no profile.

---

### 15.4 Coach Language Rules

1. **Scores only.** In every JSON response field, the only numbers the coach may cite are:
   - `readiness score (0–100)`
   - `stress score (0–100)`
   - `recovery score (0–100)`

2. **No backend metrics in responses.** RMSSD, RSA, LF/HF, suppression_pct, arc durations, and percentage-vs-baseline values are backend-only and must never appear in user-facing text. This constraint is enforced in the system prompt.

3. **psych_insight injection.** The pre-built `coach_insight` string from `PsychProfile` is injected into every morning brief and conversation turn via `CoachContext.psych_insight`. It is a single plain-English sentence — no jargon, no metrics.

4. **Social type language.**
   - Introvert: "protect solo time the day after group activities"
   - Extrovert: "social time consistently lifts your recovery score"
   - (Never says: "your HRV during social windows showed...")

---

### 15.5 New DB Tables

#### `user_psych_profiles`
One row per user. Rebuilt on demand (POST /psych/rebuild) or incrementally.

Key columns: `social_energy_type`, `social_hrv_delta_avg`, `anxiety_sensitivity`, `top_anxiety_triggers` (JSON), `top_calming_activities` (JSON), `top_stress_activities` (JSON), `primary_recovery_style`, `discipline_index`, `streak_current/best`, `mood_baseline`, `mood_score_avg`, `interoception_alignment`, `data_confidence`.

#### `mood_logs`
One row per log entry (multiple per day possible). Scores 1–5 for mood/energy/anxiety/social_desire, plus 0–100 physiological snapshot scores (readiness/stress/recovery at log time).

#### `anxiety_events`
Structured anxiety trigger records. Linked to closest `StressWindow` within ±30min. Stores `trigger_type` (12-class taxonomy), `severity`, `stress_score_at_event`, `recovery_score_drop`, `resolution_activity`, `resolved`.

---

### 15.6 New API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /psych/profile` | Current computed PsychProfile |
| `POST /psych/mood` | Log mood/energy/anxiety state (1–5 scale) |
| `POST /psych/anxiety` | Log structured anxiety trigger event |
| `POST /psych/rebuild` | Recompute full profile from all available data |

---

### 15.7 Implementation Files

| File | Role |
|------|------|
| `psych/psych_schema.py` | Input/output dataclasses, ANXIETY_TRIGGER_TYPES, SEVERITY_WEIGHT |
| `psych/psych_profile_builder.py` | All computation functions, `build_psych_profile()`, `_build_coach_insight()` |
| `api/services/psych_service.py` | Async DB wrapper (load, save, log, rebuild) |
| `api/routers/psych.py` | REST endpoints |
| `alembic/versions/0002_psych_profile.py` | DB migration for 3 new tables |
| `coach/conversation_extractor.py` *(extended)* | Anxiety trigger taxonomy patterns, MoodSignal extraction |
| `tagging/activity_catalog.py` *(extended)* | `social_energy_effect` field on ActivityDefinition |
| `coach/context_builder.py` *(extended)* | `readiness_score`, `stress_score`, `recovery_score`, `psych_insight` in CoachContext |
| `coach/prompt_templates.py` *(extended)* | Score citation rule in system prompt; score/psych blocks in morning_brief + conversation_turn |
| `api/services/coach_service.py` *(extended)* | Score + psych_insight params on all trigger methods |
| `tests/psych/test_psych_profile_builder.py` | 45 tests covering all builder functions + extractor extensions |

---

---

## Section 16 — Unified User Profile (UUP) Layer

### 16.1 Overview

The Unified User Profile is the single persisted personality model for each user. It is:

- **Rebuilt nightly** — triggered by `jobs/nightly_rebuild.py`, runs after midnight for all active users.
- **Developer-readable** — the `coach_narrative` field is a structured multi-section document that both the AI coach and engineers can inspect to understand how ZenFlow sees a user.
- **Three-layer architecture** — data aggregation → LLM narrative + plan → deterministic guardrails.
- **Primary coach context lens** — every AI coach call reads the UUP first rather than querying 6 tables independently.

Before this layer, `coach/context_builder.py` was the only link between domain data and the AI coach — but it was ephemeral (no persistence). The UUP makes this model persistent, versioned, and auditable.

---

### 16.2 Three-Layer Architecture

| Layer | What it does | Who writes it | File |
|-------|-------------|----------------|------|
| Layer 1 | Structured multi-section **narrative** | LLM (Analyst persona) | `profile/nightly_analyst.py` |
| Layer 2 | LLM-generated **daily plan** (list of PlanItems) | LLM (Planning Engine persona) | `profile/nightly_analyst.py` |
| Layer 3 | Deterministic **guardrails** — validate and correct Layer 2 output | Pure Python | `profile/plan_guardrails.py` |

The layers run sequentially each night: Layer 1 → Layer 2 (reads Layer 1 narrative) → Layer 3 (validates Layer 2 output).

---

### 16.3 The Narrative (Layer 1)

The `coach_narrative` field is a structured document written by the LLM using only scores (0–100), labels, and counts — never raw physiological values. It contains 8 required sections:

| Section | Contents |
|---------|----------|
| `PERSONALITY SNAPSHOT` | Header: `v{version} — {date}` |
| `PHYSIOLOGICAL TRAITS` | PRF BPM/status, coherence trainability, recovery arc speed, stress peak pattern, sleep efficiency |
| `PSYCHOLOGICAL TRAITS` | Social energy type, anxiety sensitivity, top triggers, discipline index, streak, mood baseline, interoception alignment |
| `BEHAVIOURAL PATTERNS` | Top calming/stressing activities, movement preferences, decompression style |
| `ENGAGEMENT PROFILE` | Band wear (last7/30), morning read streak + rate, session counts, conversation count, nudge response rate, engagement tier + trend. **Honest about declining engagement and what would re-engage the user.** |
| `CONVERSATION FACTS` | Durable personal facts extracted from conversation (relationships, preferences, schedule, events, goals, health) |
| `COACH RELATIONSHIP` | Preferred tone, best nudge window, last insight delivered |
| `WHAT CHANGED SINCE v{N}` | Concrete data changes since last narrative version, not impressions |
| `WATCH TODAY` | 1–3 actionable coach considerations for tomorrow |

**Key constraint:** The narrative is passed to the AI coach at every call. The coach is instructed to use it as context but **not to narrate it back to the user** (it's an internal lens, not a script).

---

### 16.4 The Plan (Layer 2)

Layer 2 receives the Layer 1 narrative + today's physiological scores + a list of valid activity slugs, and outputs a JSON array of plan items:

```json
[
  {"slug": "breathing", "priority": "must_do", "duration_min": 10,
   "reason": "Your recovery score is 45 — one anchoring session keeps the streak alive."},
  {"slug": "walking",   "priority": "recommended", "duration_min": 20,
   "reason": "Walking is your top calming activity (8x, avg +7.2 pts recovery)."}
]
```

**Engagement feedback loop:** Layer 2 is explicitly prompted to adjust plan complexity based on `engagement_tier`:
- `at_risk` / `churned` → light, frictionless plan (short breathing / music / book) that minimises drop-off risk while rebuilding the habit
- `high` → richer plan with performance and recovery variety
- `low` / `medium` → balanced plan respecting available energy

Layer 2 output is **not committed directly** — it passes through Layer 3 guardrails first.

---

### 16.5 Guardrails (Layer 3)

Eight deterministic rules applied sequentially in `profile/plan_guardrails.py`. Every guardrail decision is logged in `plan_guardrail_notes`:

| Rule | Condition | Action |
|------|-----------|--------|
| R1 | Unknown slug | Remove item |
| R2 | Duration outside per-slug bounds | Clamp to min/max |
| R3 | Too many `must_do` items | Demote excess to `recommended` (max 1 if `discipline_index < 40`, max 2 otherwise) |
| R4 | Red day (`readiness < 40`) | Remove `work_sprint`, `sports`, `cold_shower` |
| R5 | Introvert + `stress_score > 70` | Remove `social_time` |
| R6 | Total items > 6 | Truncate (must_do first, then recommended, then optional) |
| R7 | `at_risk`/`churned` with no frictionless item | Inject 5-min `breathing` |
| R8 | Plan is empty after all rules | Inject fallback 10-min `breathing` |

---

### 16.6 Engagement Profile

The engagement measurement combines **band + app signals** into a single tier:

| Metric | Source | Weight |
|--------|--------|--------|
| Band wear days last 7/30 | `BackgroundWindow` | Describes physio data quality |
| Morning read streak | `MorningRead` | Consecutive reads going backwards |
| Sessions last 7/30 days | `Session` | Core engagement |
| Conversations last 7 days | `ConversationEvent` | Coaching depth |
| Nudge response rate (30d) | `CoachMessage.user_reaction` | Content relevance |
| Days since last app interaction | Max(sessions, reads) | Churn signal |

#### Engagement Tier Logic

```
days_since >= 14          →  "churned"
days_since >= 7           →  "at_risk"
sessions_last7 >= 5 AND morning_read_rate >= 0.8  →  "high"
sessions_last7 >= 2 OR morning_read_rate >= 0.5   →  "medium"
else                      →  "low"
```

**Engagement trend** is computed by comparing current vs previous session + read rate composite score: `improving`, `stable`, or `declining`.

---

### 16.7 Durable Facts (UserFact)

Personal facts extracted from conversation text by `profile/fact_extractor.py`.

| Category | Examples |
|----------|---------|
| `person` | "has a daughter named Aria", "wife is a teacher" |
| `preference` | "hates cold showers", "loves hiking" |
| `schedule` | "works from home Wednesdays", "early riser" |
| `event` | "big presentation Thursday", "just moved house" |
| `goal` | "wants to run a 5k by June", "trying to lose weight" |
| `belief` | "doesn't think meditation works for him" |
| `health` | "gets migraines when sleep-deprived", "bad knees" |

**Confidence lifecycle:**
- First extraction → 0.5
- Re-mentioned in later conversation → +0.2 (max 1.0)
- User explicitly confirms ("yes exactly") → bumped to 0.9
- Manual coach entry → starts at 0.7
- Facts below 0.3 confidence are excluded from coach context

Facts with `confidence >= 0.3` are injected into the coach as `KNOWN FACTS ABOUT THIS USER` in the conversation prompt.

---

### 16.8 Coach Integration

Three fields added to `CoachContext` (in `coach/context_builder.py`):

| Field | Type | Source | Usage |
|-------|------|---------|-------|
| `uup_narrative` | `str \| None` | `UserUnifiedProfile.coach_narrative` | Injected as `PERSONALITY SNAPSHOT` block in all coach prompts |
| `user_facts` | `list[str]` | Top-8 facts by confidence | Injected as `KNOWN FACTS` block |
| `engagement_tier` | `str \| None` | `EngagementProfile.engagement_tier` | Modifies plan language (minimal/frictionless for at_risk/churned) |

Three blocks injected into every coach prompt (`coach/prompt_templates.py`):

```
PERSONALITY SNAPSHOT (read before responding; do not narrate back to user):
...narrative[:1200]...

KNOWN FACTS ABOUT THIS USER:
  - has a daughter
  - works from home on Wednesdays

ENGAGEMENT NOTE: User is 'at_risk' — keep plan minimal and frictionless.
```

**System prompt rule added:**
> Use the PERSONALITY SNAPSHOT consistently across turns. Introvert + high stress → do not suggest social activities. `mood_baseline=low` → gentler tone. `at_risk`/`churned` → light and approachable. Do NOT narrate the snapshot back to the user.

---

### 16.9 Morning Brief Plan Wiring

`coach/prescriber.py` now exports `build_daily_plan_from_uup(unified_profile, ...)` which converts a UUP `suggested_plan` into a `DailyPlan` (prescriber format). 

`api/services/coach_service.py`'s `morning_brief()` now:
1. Accepts `unified_profile: Optional[Any]` parameter
2. If UUP has a plan for today (`plan_for_date == today`), converts it to `DailyPlan` via `build_daily_plan_from_uup()`
3. Falls back to deterministic `compute_daily_prescription()` if no UUP plan exists
4. Passes `uup_narrative`, `user_facts`, `engagement_tier` to `build_coach_context()`

---

### 16.10 Fact Extraction Pipeline

Conversation facts flow through four steps:

1. **Per-turn extraction** (`coach/conversation_extractor.py`) — `ExtractionResult.extracted_facts` populated by `profile.fact_extractor.extract_facts(message)` on every user turn
2. **Accumulation** (`coach/conversation.py`) — facts stored in `ConversationState.accumulated_facts` (list of dicts) via `MemoryStore.add_facts()`
3. **Persistence at close** (`api/services/conversation_service.py`) — `close_and_persist()` deduplicates against existing facts and calls `profile_service.log_fact()` for new ones or `bump_fact_confidence()` for re-mentions
4. **Nightly rebuild** (`jobs/nightly_rebuild.py`) — facts are loaded into the UnifiedProfile and surfaced in Layer 1 narrative

---

### 16.11 Nightly Rebuild Job

`jobs/nightly_rebuild.py` runs for all active users (session or morning read in last 30 days):

```
1. Detect active users (union of Session + MorningRead last 30d)
2. For each user:
   a. Load today's DailyStressSummary scores
   b. Fetch all domain data (personal model, psych, habits, tags, facts, engagement)
   c. build_unified_profile() → UnifiedProfile (pure Python)
   d. run_layer1_narrative() → LLM narrative
   e. run_layer2_plan() → LLM plan
   f. validate_plan() → Layer 3 guardrails
   g. Save to user_unified_profiles (upsert)
   h. Increment streak (check yesterday's DailyPlan.adherence_pct)
3. Return job summary (total / succeeded / failed / skipped / duration)
```

Each user gets a fresh `AsyncSession` — one failure does not block others.

---

### 16.12 API Endpoints

Base path: `/profile/`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/profile/unified` | `X-User-Id` | Return full unified profile as JSON dict |
| `POST` | `/profile/rebuild` | `X-User-Id` | Trigger on-demand rebuild (synchronous) |
| `GET` | `/profile/facts` | `X-User-Id` | List facts with `min_confidence` filter (default 0.3) |
| `POST` | `/profile/facts` | `X-User-Id` | Manually add a fact (confidence starts at 0.7) |
| `GET` | `/profile/engagement` | `X-User-Id` | Live engagement counts from DB |

The `POST /profile/rebuild` response:
```json
{
  "narrative_version": 4,
  "data_confidence": 0.71,
  "engagement_tier": "medium",
  "plan_item_count": 3,
  "guardrail_notes": ["R2_duration_floor: breathing 8→10min"]
}
```

---

### 16.13 New DB Tables

#### `user_unified_profiles`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `user_id` | UUID FK → users | Unique (one profile per user) |
| `coach_narrative` | Text | Layer 1 output |
| `previous_narrative` | Text | Previous version for delta computation |
| `narrative_version` | Integer | Increments on each nightly rebuild |
| `physio_*` | Various | Physiological traits snapshot |
| `psych_*` | Various | Psychological traits snapshot |
| `behaviour_*` | JSONB | Top calming/stressing activities |
| `engagement_*` | Various | Full EngagementProfile fields |
| `suggested_plan_json` | JSONB | Layer 2 plan (post-guardrails) |
| `plan_for_date` | Date | Plan validity date |
| `plan_guardrail_notes` | JSONB | R1–R8 audit log |
| `data_confidence` | Float | 0–1 composite confidence |
| `last_computed_at` | Timestamp | Last rebuild time |

#### `user_facts`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `user_id` | UUID FK → users | |
| `category` | String(30) | person/preference/schedule/event/goal/belief/health |
| `fact_text` | String(200) | Human-readable extracted text |
| `fact_key` | String(60) | Deduplication key (e.g. `family.daughter`) |
| `fact_value` | String(200) | Structured value |
| `polarity` | String(10) | positive/negative/neutral |
| `confidence` | Float | 0–1, starts 0.5, max 1.0 |
| `source_conversation_id` | UUID nullable | Traceability |
| `user_confirmed` | Boolean | Explicit user confirmation |

Indexes: `ix_user_facts_user`, `ix_user_facts_user_category`.

Migration: `alembic/versions/0003_unified_profile.py`

---

### 16.14 Data Confidence Model

Composite confidence is a weighted average of 6 dimension saturation scores:

| Dimension | Weight | Saturation condition |
|-----------|--------|----------------------|
| Physio | 0.20 | `prf_bpm` + `coherence_trainability` + `recovery_arc_speed` set |
| Psych | 0.25 | `discipline_index` + `anxiety_sensitivity` + `social_energy_type` set |
| Behaviour | 0.15 | `movement_enjoyed` + `decompress_via` non-empty |
| Engagement | 0.20 | `sessions_last7` > 0 + `morning_read_rate_30d` set |
| Coach relationship | 0.10 | `preferred_tone` + `nudge_response_rate` set |
| Facts | 0.10 | Any confirmed facts present (confidence ≥ 0.7) |

---

### 16.15 Implementation Files

| File | Role |
|------|------|
| `profile/__init__.py` | Package init |
| `profile/profile_schema.py` | UnifiedProfile, PlanItem, EngagementProfile, UserFactRecord + all sub-dataclasses |
| `profile/unified_profile_builder.py` | Pure Python assembly from domain data; `_compute_confidence()` |
| `profile/fact_extractor.py` | Regex-based extraction of 7 fact categories; `merge_with_existing()` |
| `profile/nightly_analyst.py` | Layer 1 + Layer 2 LLM calls + fallback generators + JSON parser |
| `profile/plan_guardrails.py` | Layer 3 — 8 deterministic rules; `validate_plan()` |
| `api/services/profile_service.py` | Async DB wrapper: load/save/rebuild/facts/engagement |
| `api/routers/profile.py` | REST endpoints (5 endpoints) |
| `jobs/__init__.py` | Package init |
| `jobs/nightly_rebuild.py` | Nightly scheduler; active user detection; per-user pipeline; streak increment |
| `alembic/versions/0003_unified_profile.py` | Migration for 2 new tables |
| `coach/context_builder.py` *(extended)* | `uup_narrative`, `user_facts`, `engagement_tier` in CoachContext + build_coach_context() |
| `coach/prompt_templates.py` *(extended)* | PERSONALITY SNAPSHOT + KNOWN FACTS + ENGAGEMENT NOTE blocks; personality system rule |
| `coach/prescriber.py` *(extended)* | `build_daily_plan_from_uup()` — converts UUP plan to DailyPlan format |
| `api/services/coach_service.py` *(extended)* | `morning_brief()` accepts `unified_profile`, `uup_narrative`, `user_facts`, `engagement_tier` |
| `coach/conversation_extractor.py` *(extended)* | `extracted_facts` field on ExtractionResult; calls `extract_facts()` per turn |
| `coach/conversation.py` *(extended)* | Accumulates extracted facts in ConversationState via `add_facts()` |
| `coach/memory_store.py` *(extended)* | `accumulated_facts: list[dict]` on ConversationState; `add_facts()` on MemoryStore |
| `api/services/conversation_service.py` *(extended)* | Persists facts at conversation close; deduplication via `merge_with_existing()` |
| `api/db/schema.py` *(extended)* | UserUnifiedProfile + UserFact ORM models; User relationships |
| `api/main.py` *(extended)* | `app.include_router(profile.router)` |
| `tests/profile/test_unified_profile_builder.py` | Builder tests — construction, physio/psych/behaviour/engagement/confidence/facts |
| `tests/profile/test_fact_extractor.py` | Fact extraction tests — all 6 pattern categories, confirmation bump, deduplication |
| `tests/profile/test_plan_guardrails.py` | All 8 guardrail rules individually + combined scenarios |
| `tests/profile/test_nightly_analyst.py` | Fallback narrative sections, fallback plan (red/yellow/green), JSON parser, LLM error handling |

---

## Next Steps

1. **Nightly cron** — Wire `jobs/nightly_rebuild.py` into a system scheduler (cron or APScheduler at startup).
2. **Morning brief integration** — Update the coach router to load the UUP for each user and pass it to `morning_brief()`.
3. **Engagement auto-log** — Increment `last_app_interaction_days` logic when a morning read or session arrives.
4. **Auto-tag pass** — Implement the `_auto_tag_pass()` stub in `nightly_rebuild.py` to update `UserTagPatternModel` based on UUP analysis.
5. **MoodLog auto-write** — At conversation close, if `ExtractionResult.mood_signal` is not None, auto-write a `MoodLog` row.
6. **AnxietyEvent auto-write** — At conversation close, if `ExtractionResult.anxiety_trigger_type` is not None and a StressWindow exists within 30 min, create an `AnxietyEvent` row.
7. **Narrative diffing** — Implement WHAT CHANGED SINCE section with structured field-level diffs not just "incremental rebuild".
8. **Confidence decay** — Implement weekly job to decay `UserFact.confidence` by -0.05/week for unconfirmed facts.
9. **Profile versioning UI** — Developer dashboard to inspect UUP narrative versions side-by-side.

---

*This document is the single source of truth for ZenFlow Verity design. All prior documents (ARCHITECTURE.md, PRODUCT_DESIGN.md, UI_DESIGN.md) remain as detailed source material but this file supersedes them for implementation decisions.*

