# ZenFlow Verity — Product Design Thinking

**Created:** 5 March 2026  
**Status:** Design phase — pre-development

---

## Point 1: Nervous System as the Root, Everything Else as Branches

The reframe that makes this intellectually coherent:

**The nervous system is not one of many health metrics. It is the substrate everything else runs on.**

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

ZenFlow's position is not "we track your nervous system." It's: **"We fix the root cause. Everything else improves as a downstream consequence."**

This is a much stronger product claim. And it's scientifically defensible. HRV improvement is causally linked to better sleep, reduced anxiety, improved exercise recovery, and better emotional regulation — in that direction. The nervous system is upstream.

The training approach is focused on fixing the nervous system — but from an outcome perspective, every aspect must be looked at: sleep, stress, movement, cognitive performance, emotional regulation. The metrics lie without the full context. Sleep, stress, movement, and nervous system health are not separate systems. Poor sleep degrades HRV directly. Sedentary behaviour worsens stress recovery. You cannot give someone a meaningful nervous system fitness score while ignoring that they slept 4 hours and sat still all day.

---

## Point 2: The AI Coach Architecture

The most important product design decision in the whole system. Hardcoded logic produces a machine. A real coach does something fundamentally different:

**A coach has a mental model of you specifically, and updates it continuously.**

### Three Layers of Intelligence

**Layer 1 — Sensor Layer (dumb but precise)**
Raw signal processing. PPI → RMSSD. PPG → SpO2. This is deterministic code. Has to be.

**Layer 2 — Personal Model (learns you)**
A continuously updated profile of this specific user:
- Their RMSSD distribution (not population norms — *their* floor, ceiling, typical weekday, typical weekend)
- Their stress fingerprint (when in the week does their HRV degrade? how fast do they recover?)
- Their response to training (does coherence practice actually shift their RMSSD? by how much? over what timeframe?)
- Their compliance patterns (do they do sessions when nudged at 7pm? or 8am?)
- Their subjective-objective gap (do they *feel* worse before their HRV shows it, or after?)

This layer answers: **"What is normal for this person, and what is a deviation?"**

**Layer 3 — Coach Layer (synthesizes + communicates)**
Takes the personal model output and produces:
- Today's one-sentence synthesis ("You're running on fumes from a hard week — this is the right day for a short session, not a hard one")
- The specific recommended action
- The *reason* in their language, based on their history ("Last time your HRV looked like this was the Tuesday before you said you felt burned out")
- Encouragement that references their actual arc ("Three weeks ago your coherence floor was 31%. Yesterday you hit 67%. That's not luck — that's your nervous system changing.")

The coach layer is where an LLM with your personal physiological history as context becomes genuinely powerful. It is not generating generic wellness advice. It is reading *your specific data* and narrating what it means for *you today*.

### What "Not a Machine" Requires

- **Temporal memory:** the coach references the past specifically. "Last Thursday your HRV crashed after your 3pm meeting. Watch that window today."
- **Causal reasoning:** not just "your HRV is low" but "your HRV is low *because* you slept 5.5 hours two nights in a row"
- **Tone calibration:** reads whether you need a push or compassion today. A user with low resilience AND a hard external week doesn't need to be told to "try harder." They need to be told "this is expected, here's the minimum effective dose."
- **Celebrates real change:** finds the specific, non-generic proof of improvement and surfaces it. Not "great job!" but "your recovery arc shortened by 48 minutes this month. That's a measurable biological change."

---

## Point 3: NS Health Score and Pattern Recognition

Nobody has ever shown a user a mirror of their nervous system in language they recognise.

The breakthrough is not the number. The breakthrough is what the number means — and the story that sits behind it.

### Design Principle: Score Leads, Pattern Supports, Name Comes Last

The NS Health Score is shown first. It is the truth. The personality pattern description is shown second — it explains *why* the score is where it is. The pattern name (The Over-Optimizer, The Hustler etc.) is shown last, as recognition — not as a label you are assigned.

A person should read the description and think "that's exactly me" before they ever see the name.

### The NS Health Score — 0 to 100

Computed from five physiological dimensions. Each is 0–20. They sum to 100.

| Dimension | What it measures | Top signal |
|---|---|---|
| **Recovery Capacity** | How fast and fully the nervous system returns to baseline | Recovery arc class + sleep recovery efficiency |
| **Baseline Resilience** | How strong the resting nervous system floor is | RMSSD floor, range (ceiling − floor) |
| **Coherence Capacity** | How well the system responds to guided breathing practice | Coherence floor + RSA trainability |
| **Chronobiological Fit** | Alignment between biology and daily schedule | Sleep recovery efficiency + morning RMSSD quality |
| **Load Management** | Whether accumulated weekly stress is staying manageable | LF/HF resting + sleep LF/HF + overnight RMSSD delta |

### Stage System

The score maps to a stage. Stages are not a progress bar toward "Dialled-In" — they describe what the system is currently capable of and what intervention is appropriate.

| Stage | Score | What it means |
|---|---|---|
| **0** | 0–34 | Foundation missing. Observation phase. No optimisation yet. |
| **1** | 35–54 | Pattern visible. Recovery incomplete. One intervention creates movement. |
| **2** | 55–69 | Foundation working. Adaptations visible. Ready to build intentionally. |
| **3** | 70–79 | Full functionality. Load managed. Resilient under normal conditions. |
| **4** | 80–89 | Performance zone. Every dimension above its functional floor. |
| **5** | 90–100 | Ceiling. Sustained, intelligent practice is visibly reflected. |

### The Seven Patterns

Patterns are detected from physiological evidence, not archetypes. Each pattern has an evidence score (0.0–1.0). The highest-scoring pattern is primary. The second-highest is shown as an amplifier if it scores ≥ 0.20.

| Pattern | What the physiology shows | What it feels like |
|---|---|---|
| **The Over-Optimizer** | LF/HF elevated at rest. Recovery arcs slow. Potential is there — it's the recovery gap that's missing. | Trains hard, works hard. Doesn't realise the nervous system never gets the signal it's safe to slow down. |
| **The Trend Chaser** | Low coherence capacity. No prior practice. Inconsistent data — the system keeps changing the input. | Tries things. Nothing sticks. Data stays noisy because the variable keeps changing. |
| **The Hustler** | Load accumulates across the week. Arcs slow. Chronotype okay — mornings are fine. It's the week that costs. | Monday fine. Wednesday manageable. Thursday running on fumes. The problem is the absence of recovery windows, not ambition. |
| **The Quiet Depleter** | RMSSD floor low. Range narrow. No crisis signal. Just flat and under-powered. | Nothing dramatic wrong. The system has just been running quiet and low for a while. Most people in this pattern don't know they're in it. |
| **The Night Warrior** | Mornings weak. Sleep recovery efficiency below 0.90. Best window at 19:00+. | Not a discipline problem — it's chronobiology. Their biology peaks when the world is winding down. Fighting it costs recovery quality. |
| **The Loop Runner** | Overnight RMSSD drops (should rise). LF/HF elevated during sleep. | The mind runs the overnight shift when the body needs to be in repair mode. Sleep is not off time for them — it's just a different kind of active. |
| **The Purist** | Has prior practice. Coherence responding. One dimension underdeveloped next to strong ones. | The practice is working. The data shows it. The gap is biological — usually one dimension the practice doesn't reach. |

**Dialled-In** is not a pattern in the same sense. It is the state the system arrives at when all five dimensions are above their midpoints and the score clears 68. When a user enters Dialled-In territory, the pattern name changes. The coaching focus shifts from fixing gaps to optimising strengths.

### Primary and Amplifier

A user has one primary pattern and optionally one amplifier.

The amplifier is the second-highest scoring pattern, shown only when it clears the evidence threshold. It explains compound dynamics that the primary pattern alone doesn't capture.

> "You're an **Over-Optimizer**. Your **Loop Runner** pattern is amplifying this — the mind is running overnight when the body needs to be in repair mode."

### Why This Design Works

1. **Recognition creates engagement.** The pattern description resonates before the label is shown. The user feels seen, not diagnosed.

2. **The score creates agency.** It is a number that can move. Five dimensions tell the user exactly which gap to close. There is always one clear answer to "what do I do?"

3. **Evolution is the payoff.** After eight weeks the system says: "Your recovery arc has shortened 40 minutes. Your load management score has moved from 4 to 11. You came in as a Hustler. You are becoming Dialled-In." Not a number going up — an identity shifting.

4. **The amplifier tells the compound story.** Real nervous systems are not one thing. The amplifier handles overlap without confusion.

---

## How All Three Points Connect Into One System

```
INPUT SIGNALS (hardware)
        ↓
PERSONAL MODEL (AI layer — learns your specific patterns)
        ↓
NS HEALTH SCORE (0–100 across 5 dimensions)
        ↓
PATTERN (who your nervous system is, in human language — score leads, name follows)
        ↓
STAGE (0–5 — what the system currently supports)
        ↓
COACHING VOICE (LLM narrates your data, in your language, about you)
        ↓
OUTCOMES (session + weekly + 30-day proof)
        ↓
MODEL UPDATES (score moves, pattern evolves, plan adapts)
        ↓
repeat — forever
```

The nervous system is the root. The score is the honest measure of it. The pattern is the human story that makes it recognisable. The coaching voice is what makes it feel like a person, not a dashboard.

---

## Complete Metric Stack — Three Pillars

Every metric is written in plain language. No jargon. No axis labels. A report from your body.

### Pillar 1: Recovery
*How well did your body restore itself?*

| Metric | Plain Meaning | Source |
|---|---|---|
| **Sleep HRV** | "Your nervous system did most of its repair between 2–4am. This is your deepest recovery window." | PPI overnight |
| **Sleep stages** | "You spent 94 mins in deep sleep — enough to clear mental fatigue. REM was short, which may affect mood today." | PPI + ACC (movement) |
| **Recovery arc** | "After yesterday's stress, your HRV took 2.3 hours to return to your baseline. Your average is 1.4h — today was harder." | PPI continuous |
| **Morning readiness** | "Your body woke up at 71% of its normal capacity. Manageable day — don't schedule your hardest work before noon." | 5-min morning read |
| **Sleep consistency** | "You went to bed at wildly different times this week. Irregular sleep is the single biggest suppressor of your HRV." | Time-series |

### Pillar 2: Stress & Nervous System
*What state is your nervous system in right now?*

| Metric | Plain Meaning | Source |
|---|---|---|
| **Resilience score** | "Your nervous system is running at 68/100 today. That's slightly below your personal average of 74." | RMSSD vs personal baseline |
| **Stress accumulation** | "Your stress has been building since Tuesday. You haven't had a recovery window long enough to fully clear it." | Daytime HRV trend |
| **Coherence (session)** | "During your session, your heart and breath synchronised 73% of the time. That's your best score this week." | RSA from PPI |
| **Perfusion Index** | "Right now your body is in a mild threat state — blood is being redirected away from your hands and feet. This is what stress feels like physically." | PPG AC/DC ratio |
| **Sympathetic load** | "Your body has been in fight-or-flight for most of the afternoon. Your baseline won't recover until you give it a deliberate down-regulation window." | HRV + PI combined |
| **Reactivity** | "Small stressors are hitting you harder than usual today. Your nervous system has less buffer than normal." | RMSSD floor deviation |

### Pillar 3: Physical Vitality
*Is your body being used and fuelled well?*

| Metric | Plain Meaning | Source |
|---|---|---|
| **Resting heart rate** | "Your resting HR is 58 bpm — lower than your 30-day average of 62. A downward trend here means your cardiovascular fitness is improving." | PPI / HR |
| **Heart rate recovery** | "After your last active session, your heart rate dropped 22 bpm in the first minute. Athletes drop 30+. This is trainable." | HR post-exertion |
| **Movement debt** | "You've been sitting for 4.2 hours straight. Your HRV actively degrades after 90 mins of stillness — movement is medicine right now." | ACC |
| **Exercise HRV effect** | "Your HRV is 18% higher on days you exercise moderately. Today is a good day to move." | HRV × activity correlation |
| **SpO2 trend** | "Your blood oxygen stayed above 96% throughout your breathing session — your lungs are efficiently feeding your nervous system." | PPG 3-channel |
| **Cardiovascular load** | "Yesterday's exercise put a moderate load on your heart. Your body is using tonight's sleep to adapt — this is how fitness is built." | HR zone time |

### The Unifying Sentence
At the top of the app, above all three pillars, one synthesis:

> "Your body is under moderate load today. Prioritise your 6pm training session and protect your sleep window."

Not three separate dashboards. One synthesis. The system knows that sleep + stress + movement interact, and it tells you what that means for today's one decision.

---

## The Design Bet

ZenFlow doesn't need to track everything. It needs to **explain everything it tracks better than anyone else does.**

Fitbit tracks sleep stages. Nobody feels anything when they see "Light: 3h22m." ZenFlow tracks sleep stages and says: *"Your deep sleep was cut short — that's the phase that clears stress hormones. You'll feel it by 2pm today."*

Same data. Completely different product.

---

## Point 4: Daily Tracking — All-Day Wear + Stress/Recovery Framework

*Added 9 March 2026. Supersedes the 5-dimension NS Health Score as the daily user-facing output. The 5-dimension score continues to run internally and powers the personal model, archetype engine, and coach prescription — it is no longer a primary user-facing number.*

---

### The Core Insight: ANS Is a Continuous Waveform, Not a Daily Number

The autonomic nervous system is not in a state — it is in constant oscillation. The sympathetic nervous system (the accelerator) and the parasympathetic (the brake) are pressing and releasing continuously throughout the day and night. Stress and recovery are not episodes — they are the normal rhythm of a living system.

The product implication: the right representation is a **continuous waveform**, not a daily score. The score appears as a summary of that waveform. The waveform is the truth.

---

### The Three Daily Numbers

Every day the user sees three numbers and one sentence.

```
┌─────────────────────────────────────┐
│  MONDAY, 9 MARCH                    │
│                                     │
│  STRESS LOAD         72             │
│  [████████░░]  peaked at 3pm        │
│                                     │
│  RECOVERY            85             │
│  [█████████░]  sleep did the work   │
│                                     │
│  TODAY'S READINESS   71             │
│  [███████░░░]  strong start         │
│                                     │
│  "You absorbed a hard day and came  │
│   back close to full. You're ready  │
│   for today."                       │
└─────────────────────────────────────┘
```

**Stress Load (0–100):** How much autonomic stress accumulated from wake to sleep yesterday.
- 100 = RMSSD suppressed to personal floor for the entire waking day (maximum possible)
- 0 = RMSSD never dropped below personal average
- The score is the integral of RMSSD suppression below personal morning average, normalized against personal capacity
- Direction: higher = more stress absorbed

**Recovery (0–100):** How much recovery the body accumulated from yesterday's morning read to this morning's read. Window deliberately includes sleep — the primary recovery mechanism.
- Contributions: ZenFlow sessions, sleep (largest), detected daytime recovery windows
- Each contribution is tagged (workout recovery, sleep, walk, session) where identifiable
- Direction: higher = more recovery credit deposited

**Today's Readiness (0–100):** The net position, calibrated by this morning's physiological read.
```
net_prior = recovery_score - stress_score      # e.g. 85 - 72 = +13
readiness_prior = 50 + (net_prior / 2)         # centers at 50 → 56.5
morning_calibration = morning_rmssd / personal_morning_avg_rmssd
readiness = readiness_prior × morning_calibration
```
The morning read has final say. A net-positive score with a suppressed morning RMSSD will produce a lower readiness than the math alone suggests — because the sensor is reporting the ground truth.

---

### Personal Stress Capacity — Adaptive Baseline

**Definition:** 100% stress capacity = RMSSD suppressed to personal floor for the entire waking day.

Formula:
```
waking_minutes = sleep_onset_ts - wake_ts

max_possible_suppression_area =
    (personal_morning_avg_rmssd - personal_rmssd_floor) × waking_minutes

actual_suppression_area =
    Σ max(0, personal_morning_avg_rmssd - rmssd_window) × window_duration_minutes
    for each 5-min BackgroundWindow during waking hours

stress_load = (actual_suppression_area / max_possible_suppression_area) × 100
```

**Adaptive updates:** The personal floor (`stress_capacity_floor_rmssd`) updates on a schedule — monthly, or when the floor shifts >10% sustained over 7 days. Each `DailyStressSummary` row stores `capacity_version` so old scores remain recomputable and comparable. A user whose fitness improves and whose floor rises will see their capacity re-baselined — their old scores stay interpretable under the version they were computed with.

---

### The Continuous Waveform

When the user taps the Stress number, they see:

```
RMSSD (vs your personal average)

1.4 │                    ╭──╮
1.2 │             ╭──╮  ╭╯  ╰──────╮
1.0 ┼─────────────╯  ╰──╯          ╰────────  ← personal average (your baseline)
0.8 │    ╭──╮                             ╭──
0.6 │╮  ╭╯  ╰─────────────────────────╮  ╯
0.4 ││  │                             ╰──╮
0.2 │╰──╯                                │
    └──────────────────────────────────────
    7am  9am  11am  1pm  3pm  5pm  7pm
         ↑              ↑
         [Morning run]  [Work stress — untagged]
```

Above the personal average line = recovery territory. Below = stress territory.
The shaded area below the line is the stress debt. The shaded area above is the recovery credit.
The daily Stress Load score is literally the normalized integral of the below-line area.

Tagged events appear as labeled bands on the waveform. Untagged significant spikes appear as bands with a "Tag?" prompt. Each band is tappable — opens the itemized detail view.

---

### Event Detection on the Waveform

A **stress spike** is detected when:
- RMSSD drops at rate > 10% per 5-min window (rate-of-change trigger) AND
- Falls below 85% of personal morning average AND
- Remains below threshold for ≥ 10 minutes

Adjacent qualifying windows with gap < 5 minutes are merged into one event.
Minimum event size to trigger a nudge prompt: contribution > 3% of daily stress capacity.

Physical vs emotional differentiation:
- ACC/Gyro elevated during the window → tagged as `physical_load_candidate`
- Low/no motion → tagged as `stress_event_candidate`
- User confirmation converts candidate tags to confirmed tags

A **recovery window** is detected when:
- RMSSD rises back through the personal average line AND
- Sustains above average for ≥ 15 minutes

ZenFlow sessions and sleep are auto-tagged with full confidence.
Other recovery windows prompt: `"Your body settled around 6pm — what were you doing?"`

---

### Real-Time Nudges (Spike-Triggered, Not Calendar-Based)

**Maximum 3 tagging nudges per day** — hard cap, never exceeded.

Nudge timing: **always post-event**, never during. When the stress window closes (RMSSD recovered) — not while the user is still in the spike. The user has context and is calm enough to respond accurately.

Quick-tag options (4 taps max):
- Workout
- Work / calls
- Argument / difficult interaction
- Skip (event stays untagged, still contributes to score)

The system notes whether the user responded — over time, response rate informs auto-tagging confidence.

**Significant spike override rule:** On days where a very large spike occurs (contribution > 25% of daily capacity), one nudge may fire even if the 3-nudge cap was reached — because a single large event is more informative than three small ones.

---

### Itemized Views — The Credit Card Analysis

**Stress detail view** (tap Stress Load):
- Waveform at top
- Below: table of all detected stress windows sorted by contribution
  - Time window
  - Duration
  - Contribution (% of daily total, shown as a bar)
  - Tag (text label + icon, or "Untagged — tap to tag")

**Recovery detail view** (tap Recovery):
- Recovery waveform (same signal, above-line regions highlighted)
- Below: table of all recovery contributions
  - Source: Sleep, ZenFlow session, Walk, or "Recovery window"
  - Duration
  - Contribution (% of daily recovery total, shown as a bar)

**Readiness overlay** (tap Today's Readiness):
- Both waveforms overlaid on the same graph
- Below-baseline = red fill (stress debt)
- Above-baseline = green fill (recovery credit)
- Net area = net position before morning read calibration
- Morning read shown as a point: "Your body confirmed this at 7:14am"

---

### Auto-Tagging — Pattern Learning Over Time

The tagging system builds a personal pattern database. After 4–6 weeks of tagged events, the system begins auto-tagging with confidence labels:

- Monday 10am stress spikes consistently tagged "Work / calls" → auto-tag with `"Likely: Work / calls"`
- Post-5pm recovery windows consistently tagged "Walk" → auto-tag with `"Likely: Walk"`
- Large morning spikes on days with heavy ACC movement → auto-tag `"Likely: Workout"`

Auto-tags are shown differently in the UI (lighter colour, with a ✓ confirmation option). The user can override. Auto-tags that are overridden update the pattern — exactly like a credit card company learning your spending categories.

---

### Day Boundary — Wake + Sleep Detection

**Wake time detection (priority order):**
1. Sleep context → background context transition in the hardware stream
2. PersonalModel `typical_wake_time` (rolling median of last 14 days of detected transitions)
3. Morning read timestamp (user picked up phone, must be awake)

**Sleep time detection (priority order):**
1. Background context → sleep context transition
2. PersonalModel `typical_sleep_time` (rolling median of last 14 days)
3. Last background window timestamp before a >3h gap (assumed sleep)

Wake and sleep times are stored on each `DailyStressSummary` row with a `detection_method` tag so data quality is always known.

**Gap handling in background stream:**
- < 30 min: continuity assumed, no note
- 30 min – 2 hr: gap shown as "device not worn" in itemized view, score partial
- > 2 hr: significant gap, grey block on waveform, score footnoted as "partial data"

---

### Onboarding — Fast Start, No 7-Day Wait

| When | What user gets | Label |
|---|---|---|
| Day 1, after first morning read | Live waveform, HR, first rough stress reading | "Calibrating — learning your baseline" |
| End of Day 2 | Provisional stress/recovery scores | "Early estimate — gets more accurate daily" |
| Day 3 | First usable 3-day baseline, normalized scores | Scores shown normally, small "est." note |
| Day 14 | Stable floor, "(estimated)" label removed | Full accuracy |
| Day 30+ | First auto-tagging suggestions appear | Pattern learning active |

The data is shown from day 1 — never hidden. The progressive calibration is visible to the user as improving accuracy, which is itself a signal that builds trust and engagement.

---

### How This Feeds the Coach

The tracking layer outputs to a `DailyStressSummary` row each day. The coach layer reads:

- `stress_load_score` — how hard was yesterday
- `recovery_score` — how well did the body recover
- `readiness_score` — today's starting position
- `top_stress_trigger` — what drove stress (physical / cognitive / untagged)
- `top_recovery_source` — what drove recovery (sleep / session / activity / untagged)
- `consecutive_net_negative_days` — chronic load counter (3+ negative days shifts coach to recovery prescription)

This replaces and extends the current `load_trend` and `consecutive_low_days` fields in `CoachContext`. The coach now knows not just that the system is under load, but *where the load came from* and *what recovery mechanisms are active for this user*.

---

*This file captures design thinking from 5 March 2026. NS Health Score + Pattern system redesigned 7 March 2026. All-day tracking + Stress/Recovery/Readiness framework added 9 March 2026.*
