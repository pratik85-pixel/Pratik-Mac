# ZenFlow Verity — System Architecture

**Created:** 5 March 2026  
**Status:** Design phase — pre-development

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ZENFLOW VERITY                               │
│                                                                     │
│  [HARDWARE]──[BRIDGE]──[PROCESSING]──[PERSONAL MODEL]──[AI COACH]  │
│                                    ↕                     ↕         │
│                              [OUTCOMES]            [UI / CLIENT]   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Configuration Architecture (`config/`)

### The Core Problem

A single value like `RSA_WINDOW_SECONDS = 60` is not just a processing parameter. It propagates through the entire system:

```
RSA_WINDOW_SECONDS
        │
        ├── processing/rsa_analyzer.py          (window size for Lomb-Scargle)
        ├── processing/coherence_scorer.py       (coherence computed per same window)
        ├── model/coherence_tracker.py           (stored per-window, affects distribution)
        ├── outcomes/session_outcomes.py         (session score is avg of N windows)
        └── outcomes/level_gate.py              (level threshold based on window count)
```

Changing it without knowing this chain causes silent inconsistencies — processing changes but outcomes don't, or the model stores data at a different granularity than outcomes expect.

### Design Rules

1. **All configuration lives in `config/` only.** No magic numbers anywhere else in the codebase.
2. **Every config value is typed** (Pydantic BaseSettings). If a value is wrong type or out of bounds, it fails at startup — not silently at runtime.
3. **Every config value has a `# downstream:` comment** listing which modules depend on it. Changing a value forces the developer to read what breaks.
4. **Config is versioned.** When thresholds change, the version increments. Sessions store the config version they were computed with — so a level gate recalculation on old data uses the right thresholds.
5. **Environment overrides via `.env`.** Defaults are production-safe. Dev/test can override without touching source.
6. **Feature flags are config too.** Experimental features (PAV breath, SpO2) are gated by flag — not by commenting out code.

### Directory Structure

```
config/
├── __init__.py                 # Exports single CONFIG object — the only import any module needs
├── base.py                     # All config definitions with types, defaults, downstream comments
├── processing.py               # Signal processing parameters
├── model.py                    # Personal model parameters
├── scoring.py                  # Coherence, zone, level gate thresholds
├── coach.py                    # LLM settings, tone thresholds
├── features.py                 # Feature flags
├── environments/
│   ├── development.env
│   ├── staging.env
│   └── production.env
└── versions.py                 # Config version registry — maps version → snapshot of thresholds
```

### Config Domains

#### `config/processing.py` — Signal Processing

```python
class ProcessingConfig(BaseSettings):

    # ── PPI / HRV ──────────────────────────────────────────────────────
    # downstream: ppi_processor, rsa_analyzer, coherence_scorer,
    #             model/coherence_tracker, outcomes/session_outcomes
    RSA_WINDOW_SECONDS: int = 60

    # downstream: ppi_processor (RMSSD rolling window)
    # downstream: model/personal_distributions (distribution granularity)
    RMSSD_WINDOW_SECONDS: int = 60

    # downstream: artifact_handler (how many consecutive bad beats = pause)
    ARTIFACT_MAX_CONSECUTIVE_BEATS: int = 4

    # downstream: breath_extractor (RSA method), rsa_analyzer
    RSA_FREQ_LOW_HZ: float = 0.08
    RSA_FREQ_HIGH_HZ: float = 0.12

    # downstream: ppi_processor (outlier rejection)
    PPI_MIN_MS: int = 300
    PPI_MAX_MS: int = 2000

    # ── PPG ────────────────────────────────────────────────────────────
    # downstream: ppg_processor (PI calculation window)
    PPG_PI_WINDOW_SECONDS: int = 10

    # downstream: ppg_processor (SpO2 — 3-channel ratio window)
    SPO2_WINDOW_SECONDS: int = 30

    # downstream: ppg_processor, breath_extractor (PAV method)
    PAV_WINDOW_BEATS: int = 20

    # ── ACC / Gyro ──────────────────────────────────────────────────────
    # downstream: motion_analyzer (restlessness score window)
    RESTLESSNESS_WINDOW_SECONDS: int = 30

    # downstream: motion_analyzer (movement debt accumulation)
    # downstream: api/services/session_service (pre-session restlessness check)
    SEDENTARY_THRESHOLD_MINUTES: int = 90
```

#### `config/scoring.py` — Thresholds & Level Gates

```python
class ScoringConfig(BaseSettings):

    # ── Coherence Zones ─────────────────────────────────────────────────
    # downstream: coherence_scorer, outcomes/session_outcomes,
    #             archetypes/classifier, ui (ZoneIndicator colours)
    ZONE_1_MIN: float = 0.20   # Settling
    ZONE_2_MIN: float = 0.40   # Engaged
    ZONE_3_MIN: float = 0.60   # Coherent
    ZONE_4_MIN: float = 0.80   # Flow

    # ── Session Scoring ─────────────────────────────────────────────────
    # downstream: outcomes/session_outcomes, outcomes/level_gate
    # Session score = weighted avg of zone time × coherence depth
    ZONE_WEIGHTS: dict = {1: 0.1, 2: 0.3, 3: 0.6, 4: 1.0}

    # ── Level Gates ─────────────────────────────────────────────────────
    # downstream: outcomes/level_gate, archetypes/plan_prescriber
    LEVEL_1_COHERENCE_AVG_THRESHOLD: float = 0.60
    LEVEL_1_MIN_SESSIONS: int = 6

    LEVEL_2_ZONE3_CONTINUOUS_MINUTES: float = 4.0
    LEVEL_2_QUALIFYING_SESSIONS: int = 3

    LEVEL_3_HARDMODE_MIN_SESSIONS: int = 5

    # ── Resilience Score ────────────────────────────────────────────────
    # downstream: outcomes/weekly_outcomes, model/personal_distributions
    # Resilience = RMSSD / personal_ceiling × 100
    RESILIENCE_PERSONAL_WINDOW_DAYS: int = 30

    # ── Recovery Arc ────────────────────────────────────────────────────
    # downstream: recovery_arc, model/recovery_profiler
    # Arc = time from stress event to return within X% of baseline
    RECOVERY_ARC_RETURN_THRESHOLD_PCT: float = 0.90

    # ── Hardmode Trigger ────────────────────────────────────────────────
    # downstream: outcomes/hardmode_tracker, api/services/session_service
    # Hardmode triggered when RMSSD < this % of personal floor
    HARDMODE_RMSSD_THRESHOLD_PCT: float = 0.85
```

#### `config/model.py` — Personal Model Parameters

```python
class ModelConfig(BaseSettings):

    # ── Baseline Onboarding ─────────────────────────────────────────────
    # downstream: model/baseline_builder
    BASELINE_DAYS: int = 7
    BASELINE_MIN_VALID_SESSIONS: int = 3

    # ── Rolling Distributions ───────────────────────────────────────────
    # downstream: model/personal_distributions (how far back to look)
    # downstream: outcomes/weekly_outcomes (same window must align)
    DISTRIBUTION_ROLLING_DAYS: int = 30

    # ── Archetype Classification ────────────────────────────────────────
    # downstream: archetypes/classifier
    # How many days of data before archetype is declared confident
    ARCHETYPE_MIN_DAYS: int = 14
    ARCHETYPE_CONFIDENCE_THRESHOLD: float = 0.65

    # ── Interoception Gap ───────────────────────────────────────────────
    # downstream: model/interoception_gap, archetypes/classifier (Suppressor)
    # Gap = pearson r between subjective score and objective RMSSD
    INTEROCEPTION_GAP_SUPPRESSOR_THRESHOLD: float = -0.3

    # ── Subjective Check-in ─────────────────────────────────────────────
    # downstream: api/routers/plan (check-in scheduling)
    # downstream: model/interoception_gap (cadence of subjective data)
    CHECKIN_CADENCE_DAYS: int = 3
```

#### `config/coach.py` — AI Coach Parameters

```python
class CoachConfig(BaseSettings):

    # downstream: coach/coach_api (which model to call)
    LLM_MODEL: str = "gpt-4o"
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 400

    # ── Tone Selection ──────────────────────────────────────────────────
    # downstream: coach/tone_selector
    # Compassion tone triggers when readiness < this threshold
    TONE_COMPASSION_READINESS_THRESHOLD: int = 60
    # Celebrate tone triggers when milestone detected with this min delta
    TONE_CELEBRATE_COHERENCE_DELTA: float = 0.15
    # Warn tone triggers when RMSSD below personal floor by this %
    TONE_WARN_RMSSD_DROP_PCT: float = 0.25

    # ── Memory ──────────────────────────────────────────────────────────
    # downstream: coach/memory_store (how many past messages to inject as context)
    COACH_CONTEXT_HISTORY_MESSAGES: int = 5

    # downstream: coach/milestone_detector
    MILESTONE_MIN_ARC_IMPROVEMENT_PCT: float = 0.20
    MILESTONE_MIN_COHERENCE_DELTA: float = 0.15
```

#### `config/features.py` — Feature Flags

```python
class FeatureFlags(BaseSettings):

    # Experimental breath detection from PPG — off until validated on real Verity data
    ENABLE_PAV_BREATH: bool = False

    # SpO2 trend in-session — off until 3-channel PPG pipeline validated
    ENABLE_SPO2_TREND: bool = False

    # Hardmode sessions — off until Level 3 reached
    ENABLE_HARDMODE_SESSIONS: bool = True

    # Gyro-based restlessness score — on (Verity has gyro, H10 didn't)
    ENABLE_RESTLESSNESS_SCORE: bool = True

    # AI coach — can be disabled to fall back to rule-based messages
    ENABLE_AI_COACH: bool = True

    # 30-day baseline re-run
    ENABLE_MONTHLY_REBASELINE: bool = True
```

### The Single Import Pattern

Every module imports config from one place only:

```python
# In any module, anywhere in the codebase:
from config import CONFIG

# Usage:
window = CONFIG.processing.RSA_WINDOW_SECONDS
threshold = CONFIG.scoring.ZONE_3_MIN
enabled = CONFIG.features.ENABLE_PAV_BREATH
```

`config/__init__.py` assembles all domains into one object:

```python
# config/__init__.py
from config.processing import ProcessingConfig
from config.scoring import ScoringConfig
from config.model import ModelConfig
from config.coach import CoachConfig
from config.features import FeatureFlags

class ZenFlowConfig:
    processing: ProcessingConfig = ProcessingConfig()
    scoring: ScoringConfig = ScoringConfig()
    model: ModelConfig = ModelConfig()
    coach: CoachConfig = CoachConfig()
    features: FeatureFlags = FeatureFlags()

CONFIG = ZenFlowConfig()
```

### Config Versioning

When thresholds change, the version increments. Sessions store which config version computed them — enabling correct recalculation on old data if needed.

```python
# config/versions.py
CONFIG_VERSION = 3

VERSION_HISTORY = {
    1: {"RSA_WINDOW_SECONDS": 30, "ZONE_3_MIN": 0.55},   # initial
    2: {"RSA_WINDOW_SECONDS": 60, "ZONE_3_MIN": 0.55},   # window doubled after Verity data
    3: {"RSA_WINDOW_SECONDS": 60, "ZONE_3_MIN": 0.60},   # zone 3 raised after cohort review
}
```

Every session record stores `config_version: int`. Every outcome stores `config_version: int`. If thresholds change, old data is not silently re-evaluated under new rules.

---

## Layer 0: Hardware

**Device:** Polar Verity Sense (optical armband)

| Stream | Rate | Used For |
|---|---|---|
| PPI | Event-driven | All HRV computation |
| PPG raw (3-channel) | 135Hz | SpO2, Perfusion Index, PAV breath |
| ACC | 52Hz | Movement debt, restlessness |
| Gyroscope | 52Hz | Pre-session settling, fidgeting |
| HR | 1Hz | Background context |

**Secondary inputs (passive ingestion):**
- Apple Health / Google Fit → steps, activity, sleep stages (where device can't provide)
- User self-report → 3 subjective questions every 3 days (in-app)

---

## Layer 1: Hardware Bridge (`bridge/`)

**Language:** Swift (Polar BLE SDK)  
**Role:** Connect to device, stream raw data, forward over WebSocket

```
bridge/
├── PolarConnector.swift       # BLE pairing, device management, reconnect logic
├── StreamRouter.swift         # Routes PPI / PPG / ACC / Gyro to correct handlers
├── ArtifactFilter.swift       # Detects and removes motion artifact in PPI/PPG
├── WebSocketEmitter.swift     # Emits clean streams to backend over WS
└── HealthKitIngester.swift    # Pulls Apple Health data (sleep, steps, activity)
```

**Responsibilities:**
- Maintain BLE connection and auto-reconnect
- Per-beat artifact flagging (not silent removal — flag bad beats, let backend decide)
- Emit context tag with each packet: `session | background | sleep | morning_read`
- Buffer during connection drop, flush on reconnect

**WebSocket message format:**
```json
{
  "stream": "ppi",
  "context": "session",
  "ts": 1741200000.123,
  "value": 847,
  "artifact": false
}
```

---

## Layer 2: Signal Processing (`processing/`)

**Language:** Python  
**Role:** Raw signals → clean physiological metrics  
**Rule:** Deterministic. No AI here. Same input always produces same output.

```
processing/
├── ppi_processor.py           # RMSSD, SDNN, pNN50 from PPI stream
├── rsa_analyzer.py            # Lomb-Scargle periodogram → RSA power at 0.1Hz
├── coherence_scorer.py        # RSA peak dominance → coherence % per window
├── breath_extractor.py        # EDR from RSA oscillation + PAV from PPG (dual method)
├── ppg_processor.py           # Perfusion Index, SpO2 trend from 3-channel PPG
├── motion_analyzer.py         # Restlessness score from ACC + Gyro
├── recovery_arc.py            # HRV trend event detection → arc duration
└── artifact_handler.py        # Shared logic: hold-last-good vs gap vs interpolate
```

**Key design rules:**
- Every metric emits a **confidence score** alongside its value (0.0–1.0)
- Metrics degrade gracefully on artifact — they do not output silently wrong values
- context tag from bridge determines which metrics are computed (no breath during background wear, no restlessness during sleep)

**Output schema (example):**
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

---

## Layer 3: Personal Model (`model/`)

**Language:** Python  
**Role:** Learns the individual user's physiological patterns over time  
**Rule:** No population norms. Everything relative to *this user's* own history.

```
model/
├── baseline_builder.py        # 7-day onboarding → build initial fingerprint
├── personal_distributions.py  # Rolling distributions: RMSSD floor/ceiling, daily rhythm
├── stress_fingerprint.py      # When/how/how fast stress accumulates for this user
├── recovery_profiler.py       # Recovery arc speed class, trend over weeks
├── coherence_tracker.py       # Coherence trainability, zone time distribution
├── compliance_tracker.py      # When does this user actually show up? Best nudge windows
├── interoception_gap.py       # Subjective vs objective alignment — are they a Suppressor?
├── archetype_classifier.py    # Maps fingerprint → archetype(s) with confidence weights
└── model_store.py             # Persist + version personal model per user (SQLite / Postgres)
```

**Personal fingerprint (built over 7 days, updated continuously):**
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
  "archetype_primary": "wire",
  "archetype_secondary": "slow_burner",
  "archetype_confidence": { "wire": 0.72, "slow_burner": 0.41 },
  "model_version": 12,
  "last_updated": "2026-03-05"
}
```

---

## Layer 4: Archetype Engine (`archetypes/`)

**Language:** Python  
**Role:** Compute NS Health Score from `PersonalFingerprint` → produce scoring profile + plain-language coaching narrative

```
archetypes/
├── scorer.py                  # PersonalFingerprint → NSHealthProfile (score + pattern)
├── narrative.py               # NSHealthProfile → NSNarrative (headlines, body, insights)
└── __init__.py                # Public API: compute_ns_health_profile, compute_narrative
```

### NS Health Score design

The score (0–100) is a weighted composite of 5 physiological dimensions, each 0–20.
**The score leads. The personality pattern supports. The pattern name comes last as recognition.**

| Dimension | Signal sources | Max |
|---|---|---|
| **Recovery Capacity** | `recovery_arc_class`, `sleep_recovery_efficiency` | 20 |
| **Baseline Resilience** | `rmssd_floor`, `rmssd_range`, `has_prior_practice` | 20 |
| **Coherence Capacity** | `coherence_floor`, `rsa_trainability`, `coherence_trainability` | 20 |
| **Chronobiological Fit** | `sleep_recovery_efficiency`, `rmssd_morning_avg / rmssd_floor` | 20 |
| **Load Management** | `lf_hf_resting`, `lf_hf_sleep`, `overnight_rmssd_delta_avg` | 20 |

### Stage system

| Stage | Score band | Description |
|---|---|---|
| 0 | 0–34 | Foundation missing. Observation only. |
| 1 | 35–54 | Pattern present. Recovery incomplete. One intervention unlocks movement. |
| 2 | 55–69 | Foundation working. Adaptations visible. Ready to build deliberately. |
| 3 | 70–79 | Full functionality. Load managed. Resilient under normal conditions. |
| 4 | 80–89 | Performance zone. All dimensions above floor. |
| 5 | 90–100 | Ceiling. All dimensions near physiological maximum. |

### Pattern detection

Each pattern receives an evidence score (0.0–1.0) from weighted signals. Primary = highest score.
Amplifier = second-highest if ≥ 0.20 threshold.
Pattern is `UNCLASSIFIED` if `overall_confidence < 0.35`.

`dialled_in` overrides all others when its evidence score ≥ 0.75.

| Pattern | Core signals |
|---|---|
| `over_optimizer` | High LF/HF resting + low load management + low recovery capacity |
| `trend_chaser` | Low coherence + no prior practice + inconsistent data |
| `hustler` | Low load + slow recovery arcs + moderate chrono fit |
| `quiet_depleter` | Low RMSSD floor + narrow range + flat coherence |
| `night_warrior` | Low chrono fit + SRE < 0.90 + peak window ≥ 19:00 |
| `loop_runner` | Negative overnight RMSSD delta + elevated LF/HF during sleep |
| `purist` | Has prior practice + coherence capacity ≥ 10 |
| `dialled_in` | Total ≥ 68 + recovery ≥ 14 + load management ≥ 14 |

### Key output types

**`NSHealthProfile`** (from `scorer.py`):
```python
@dataclass
class NSHealthProfile:
    total_score:         int                # 0–100
    stage:               int                # 0–5
    stage_target:        int                # next stage threshold
    recovery_capacity:   int                # 0–20
    baseline_resilience: int                # 0–20
    coherence_capacity:  int                # 0–20
    chrono_fit:          int                # 0–20
    load_management:     int                # 0–20
    primary_pattern:     str                # e.g. "over_optimizer"
    amplifier_pattern:   Optional[str]      # secondary pattern if active
    pattern_scores:      dict               # all raw pattern evidence scores
    trajectory:          str                # "improving"|"stable"|"declining"
    stage_focus:         list[str]          # 2–3 coaching actions
```

**`NSNarrative`** (from `narrative.py`):
```python
@dataclass
class NSNarrative:
    headline:            str                # 1 sentence above the score
    body:                str                # 2–3 sentences — personal story
    pattern_name:        str                # "The Over-Optimizer" — shown AFTER body
    amplifier_note:      str                # describes active amplifier ("" if none)
    dimension_insights:  dict[str, str]     # per-dimension 1-sentence explanations
    stage_description:   str               # what this stage looks like
    stage_focus:         list[str]          # 2–3 specific actions
    evolution_note:      str               # what reaching next stage unlocks
```

---

## Layer 5: AI Coach (`coach/`)

**Language:** Python  
**Role:** Synthesize personal model + current state → coaching output in plain English  
**Engine:** LLM (GPT-4o or Claude Sonnet) with structured context injection

```
coach/
├── context_builder.py         # Assembles CoachContext: all metrics as personal-baseline-relative strings
├── tone_selector.py           # Deterministic tone selection — PUSH | COMPASSION | CELEBRATE | WARN
├── plan_replanner.py          # Daily prescription: recomputed every morning from current state + signals
├── prompt_templates.py        # Per-trigger templates with pre-framing constraints for LLM
├── coach_api.py               # Pipeline orchestrator: context → tone → template → LLM → validate → output
├── schema_validator.py        # Post-generation enforcement: word counts, blocklist, specificity rules
├── safety_filter.py           # Clinical language scan on all input AND output — non-negotiable guardrail
├── milestone_detector.py      # Detects meaningful change events → feeds CELEBRATE tone + specific evidence
├── memory_store.py            # Conversation state persistence + rolling 300-word summary
├── conversation.py            # Turn-taking state machine — manages session lifecycle
├── conversation_extractor.py  # User message → structured model signals (parallel to LLM response)
└── local_engine.py            # Offline fallback — deterministic templates, no LLM required
```

### Design principle

**The LLM writes sentences. Python makes all decisions.**

Every coaching decision — what to recommend, what tone to use, whether to push or console, what signals are relevant — is made by deterministic Python logic before the LLM is ever called. The LLM's only job is to assemble pre-digested, personal-baseline-relative information into language that sounds like a person said it specifically to you.

```
Trigger fires
      │
      ▼
plan_replanner.py         ← daily prescription: session type, intensity, timing, reason_tag
      │
      ▼
context_builder.py        ← all metrics → personal-relative strings (never raw numbers to LLM)
      │
      ├── milestone_detector.py   ← parallel: any significant change events?
      │
      ▼
tone_selector.py          ← PUSH | COMPASSION | CELEBRATE | WARN (deterministic, pre-LLM)
      │
      ▼
prompt_templates.py       ← trigger type → template with pre-framing constraints
      │
      ▼
LLM call (JSON mode)      ← structured output enforced at API level
      │
      ▼
schema_validator.py       ← word counts, blocklist, specificity check
      │  fails? → retry ×2 → fallback to static template
      ▼
safety_filter.py          ← scans both input and LLM output
      │
      ▼
CoachOutput               ← returned to API layer
```

### Personalization architecture

The LLM never sees raw sensor values. `context_builder.py` converts every metric into a personal-baseline-relative statement derived from `PersonalFingerprint`:

```python
# context_builder.py — conversion examples
today_rmssd_vs_avg   = "-21% vs your average"           # NOT "34.1ms"
today_vs_floor       = "12% above your floor"           # floor = personal safety anchor
load_trend           = "load building since Tuesday"     # NOT "lf_hf_resting = 2.1"
recovery_note        = "arcs completing in ~2.2hrs vs your 1.8hr average"
```

All comparisons are against `PersonalFingerprint` fields — not population norms. A user with `rmssd_floor = 68ms` and one with `rmssd_floor = 24ms` get different references for "you're near your floor", because "their floor" is their own computed 5th percentile.

### Daily plan recomputed each morning — no weekly document

`plan_replanner.py` runs fresh every morning when a morning read arrives. The output is not a modification of a stored plan — it is a new prescription derived from current state:

```python
@dataclass
class DailyPrescription:
    session_type:       str    # "breathing_only" | "full" | "active_recovery" | "rest"
    session_duration:   int    # minutes
    session_intensity:  str    # "low" | "moderate" | "high"
    session_window:     str    # "19:00–21:00"
    physical_load:      str    # "reduce" | "maintain" | "can_increase"
    reason_tag:         str    # feeds context_builder ("alcohol_recovery_compound", etc.)
    load_score:         float  # 0.0–1.0 composite pressure score
```

**Load score logic — stacked signals:**
```python
load_score = (
    alcohol_within_24h       * 0.30 +
    below_floor_severity     * 0.35 +
    consecutive_low_reads    * 0.20 +
    weekly_load_flag         * 0.15
)
# ≥ 0.65 → "rest"
# ≥ 0.40 → "breathing_only"
# else   → stage-appropriate plan at reduced intensity
```

The `stage_focus` from `NSHealthProfile` is the ceiling — the current state is the floor. The prescription lives between them, recomputed daily.

### Tone selection — deterministic, pre-LLM

The LLM is not asked to infer tone from the data. Tone is selected by Python before the LLM is called and injected as a hard constraint, not a suggestion.

| Tone | Condition |
|---|---|
| `CELEBRATE` | Milestone detected OR NS score +5 in 7 days — overrides all others |
| `WARN` | 2+ consecutive below-floor reads OR lf_hf_resting > 2.8 trending up — overrides PUSH |
| `COMPASSION` | Score declining AND (external stressor flagged OR 2+ below-floor reads) |
| `PUSH` | Trajectory improving + capacity present + no warn/celebrate condition |

Only one tone per message. `CELEBRATE` beats everything. `WARN` beats `PUSH`. `COMPASSION` and `PUSH` are mutually exclusive.

### CoachContext — what the LLM sees

```python
@dataclass
class CoachContext:
    # ── Identity (static between fingerprint rebuilds) ──────────────────────
    user_name:              str
    pattern_label:          str        # "Over-Optimizer"
    pattern_summary:        str        # 1-sentence description
    stage_in_words:         str        # "Stage 1 — recovery completing but slowly"
    weeks_in_stage:         int

    # ── Today (personal-relative strings — no raw numbers) ──────────────────
    today_rmssd_vs_avg:     str        # "-21% vs your average"
    today_rmssd_vs_floor:   str        # "12% above your floor"
    morning_read_quality:   str        # "good" | "borderline" | "low"
    consecutive_low_days:   int

    # ── 7-day trend ─────────────────────────────────────────────────────────
    score_7d_delta:         Optional[int]
    trajectory:             str        # "improving" | "stable" | "declining"
    load_trend:             str        # plain English
    sessions_this_week:     int
    last_session_ago_days:  Optional[int]
    recovery_pattern_note:  str        # "arcs completing in ~2.2hrs vs your 1.8hr avg"

    # ── Habit events (last 72h — specificity filtered) ───────────────────────
    recent_habit_events:    list[str]  # ["alcohol event 2 nights ago (moderate)"]
    sleep_note:             str
    schedule_context:       str

    # ── Milestone (if detected since last session) ───────────────────────────
    milestone:              Optional[str]
    milestone_evidence:     Optional[str]  # specific number to reference if celebrating

    # ── Conversation memory ──────────────────────────────────────────────────
    last_user_said:         Optional[str]
    conversation_summary:   Optional[str]  # max 300 words — updated after each turn
    extracted_signals:      list[str]

    # ── Trigger + prescription ───────────────────────────────────────────────
    trigger_type:           str        # "morning_brief" | "post_session" | "nudge" | etc.
    tone:                   str        # set before context assembly
    prescription:           DailyPrescription  # what to recommend today
    session_data:           Optional[dict]     # post_session trigger only
```

### Output schemas — rigid, per trigger

The LLM produces JSON. Every field has a word limit. The UI renders fields individually — no text dumps.

**`morning_brief`:**
```json
{
  "trigger": "morning_brief",
  "tone": "compassion",
  "summary": "20–45 words — current state in personal terms",
  "physiological_context": "20–40 words — what the body is doing and why",
  "action": "10–28 words — one specific action with time",
  "action_time": "HH:MM",
  "action_duration_min": 10,
  "encouragement": "specific number or delta required — blank if none exists",
  "check_in_question": "one open question, max 20 words"
}
```

**`post_session`:**
```json
{
  "trigger": "post_session",
  "tone": "celebrate",
  "summary": "what happened in this session specifically",
  "session_insight": "what the data shows about how practice is working",
  "pattern_connection": "how session links to their specific pattern",
  "next_session_note": "one timing or approach note",
  "session_score": 73
}
```

**`nudge`:**
```json
{
  "trigger": "nudge",
  "tone": "warn",
  "signal": "what the body is showing — personal-relative",
  "action": "one action, max 28 words",
  "reason": "why now — pattern-specific"
}
```

**`weekly_review`:**
```json
{
  "trigger": "weekly_review",
  "tone": "celebrate",
  "week_headline": "the most significant measurable change this week",
  "what_worked": "specific session or day that produced the best signal",
  "what_to_watch": "the one pattern that needs attention next week",
  "next_week_focus": "one specific action for next week",
  "score_delta": "+4 since last week",
  "dimension_that_moved": "Recovery Capacity: 4 → 7"
}
```

**`conversation_turn`:**
```json
{
  "trigger": "conversation_turn",
  "tone": "compassion",
  "response": "conversational reply — heard and directed",
  "plan_delta": {
    "session_priority": "elevated",
    "physical_load_adjustment": "reduce",
    "session_time_override": null
  },
  "extracted_model_signal": "chronic_work_stress confirmed — 14 day window",
  "follow_up_question": "one question or null to close the conversation"
}
```

### Framework enforcement — four independent layers

A single layer failure must not reach the user.

**Layer A — Persona contract (system prompt, injected on every call):**
```
Who you are:
  A coach who understands physiology but speaks like a person.
  You have this user's physiological history and reference it specifically.

What you never do:
  - Prescribe, diagnose, or suggest medical action
  - Use generalities: "great work", "keep it up", "you're doing amazing"
  - Use clinical terms: cortisol, parasympathetic, LF/HF, vagal tone, autonomic
  - Encourage without a specific number — if no delta exists, encouragement is empty
  - Give more than one action
  - Ask more than one question

Language rules:
  - B2 level maximum — no specialist vocabulary
  - Present tense: "your body is..." not "your HRV suggests..."
  - Reference personal baseline, not population norms
  - Short sentences. No compound clauses.

Tone is a constraint, not a suggestion. If tone = "compassion", you do not push.
If tone = "push", you do not console.
```

**Layer B — JSON mode:** LLM called with function_calling / tool_use — output is schema-typed at the API level.

**Layer C — schema_validator.py:**

| Check | Rule | On failure |
|---|---|---|
| Schema conformance | All required fields present | Retry ×2 → static fallback |
| `summary` word count | 20–45 words | Retry |
| `action` word count | 10–28 words | Retry |
| Clinical term blocklist | 40-term list scanned | Retry |
| `encouragement` specificity | Must contain a digit if non-empty | Blank field (no retry) |
| Superlative filter | "amazing", "fantastic", "proud of you" | Blank or retry |
| Medical advice pattern | "see a doctor", "consult a professional" | Safety route |

**Layer D — template pre-framing:** Before context is passed to LLM, each trigger prepends constraints:
```
Trigger: morning_brief | Tone: COMPASSION | Stage: 1
Constraint: action must relate to recovery — no physical load increase
Encouragement evidence (if milestone): "coherence floor 0.28 → 0.41 over 3 weeks"
```
The LLM only fills in language — what to talk about is already decided.

### Offline — three-tier fallback

**Tier 1 — Pre-computed (default):** Morning brief is computed server-side 30 minutes after morning read arrives, pushed to device, cached. Covers >95% of offline scenarios.

**Tier 2 — `local_engine.py`:** Deterministic template engine reading local DB. Uses `stage_focus` from `NSHealthProfile` + `DailyPrescription` reason tag. No LLM. Structurally identical output, lower specificity.

**Tier 3 — Sessions always offline:** All session recording, PPI processing, RSA, coherence — entirely local. Nothing about a session requires network. Queues and syncs on reconnect.

### Conversation architecture

```python
@dataclass
class ConversationState:
    conversation_id:      str
    user_id:              str
    turn_index:           int
    started_at:           datetime
    trigger_context:      str      # what started the conversation
    rolling_summary:      str      # max 300 words — replaces full history after turn 3
    accumulated_signals:  list[str]
    plan_delta_net:       dict     # net plan changes across all turns
    safety_triggered:     bool     # latches True, exits conversation permanently
```

Each turn runs two parallel processes:
1. **LLM call** — generates conversational response using rolling context
2. **`conversation_extractor.py`** — extracts structured signals from user's message (does not block response)

The extractor writes to the same signal tables as physiological data. A user saying "I've been stressed for two weeks" updates `stress_fingerprint` via the same interface as HRV sensor data — lower confidence weight, same schema.

Rolling summary replaces full history after 3 turns — bounds LLM context budget regardless of conversation length.

Voice processing is entirely on-device (Apple Speech → text). Audio never leaves the device. Coach returns text → device does TTS (local offline, ElevenLabs if online).

**Conversation closes when:**
- User dismisses
- 5 minutes of no input
- Safety filter fires (immediate warm handoff, locked for session)
- Coach returns `follow_up_question: null` (natural completion)

### Three conversation modes

| Mode | Trigger | Purpose |
|---|---|---|
| **Morning check-in** | Coach-initiated with morning brief | One open question — plan adjusts if context warrants |
| **Reactive** | User-initiated anytime | "I feel stressed", "I can't do this today" — heard + plan adjusted |
| **Post-session debrief** | Coach-prompted after session | Pairs subjective with objective — builds interoception model |

### Voice architecture

| Component | Technology | Reason |
|---|---|---|
| Speech → text | Apple Speech (on-device) | Audio never leaves device |
| LLM processing | GPT-4o / Claude Sonnet | Text only — no audio transmitted |
| Text → speech | AVSpeechSynthesizer (offline) / ElevenLabs (online) | Warm fallback always available |

---

## Habit & Lifestyle Data (`model/habits.py`)

**Purpose:** Capture lifestyle inputs that sensors cannot detect but coaching can act on.

**Collected during onboarding (8 screens, ~3 minutes):**

```python
class UserHabits(BaseModel):
    # Movement
    movement_enjoyed: list[str]       # ["running", "hiking", "yoga", ...]
    exercise_frequency: str           # "rarely" | "sometimes" | "regularly"

    # Recovery habits
    alcohol: str                      # "never" | "socially" | "most_evenings"
    caffeine: str                     # "light" | "heavy" | "sensitive"
    smoking: str                      # "no" | "occasionally" | "daily"
    sleep_schedule: str               # "consistent" | "variable"

    # Stress context
    typical_day: str                  # "back_to_back" | "active" | "desk" | "variable"
    stress_drivers: list[str]         # ["too_much_to_do", "difficult_people", ...]

    # Decompress style
    decompress_via: list[str]         # ["exercise", "reading", "nature", ...]
```

**Runtime habit event logging (via conversation extractor + Apple Health):**

```python
class HabitEvent(BaseModel):
    event_type: str     # "alcohol", "exercise", "late_night", "stressful_event"
    ts: datetime
    source: str         # "conversation" | "apple_health" | "manual"
    severity: str       # "light" | "moderate" | "heavy" (for alcohol, exercise load)
    notes: str          # extracted from conversation if applicable
```

Habit events are correlated with next-day HRV automatically. Over weeks, the model learns the specific impact of each habit on *this user's* physiology — e.g. "two drinks degrades your recovery by 18% the following morning" — and the coaching voice becomes specific about it.

---

## Layer 5.5: Sessions (`sessions/`)

**Language:** Python
**Role:** Translate a DailyPrescription into a concrete, device-ready session — including the ring timing contract, the step-down state machine, and practice-to-stage gating.

This layer sits between the coach (which decides *what kind* of session to do) and the API (which delivers the session config to the device). It knows nothing about HRV scoring or user archetypes — it only knows practices, pacing, and gates.

```
sessions/
├── __init__.py
├── practice_registry.py      # Canonical practice list + stage gates + description
├── pacer_config.py           # PacerConfig dataclass — the ring's timing contract
├── step_down_controller.py   # Gate A/B/C logic — when to step BPM down, when PRF is found
├── session_prescriber.py     # (stage, load_signal, prf_status) → PracticeSession
└── session_schema.py         # PracticeSession — the full device-ready session contract
```

### Practice taxonomy

Seven practices across three tiers. Stage gates are enforced by `session_prescriber.py`.

#### Tier 1 — Signal establishment (Stage 0–1)

| Practice | `practice_type` | Description |
|---|---|---|
| Ring entrainment | `ring_entrainment` | Pacer at detected current BPM. No step-down. No gate. User learns to follow the ring. Stage 0, first 1–2 sessions only. |
| PRF discovery | `prf_discovery` | Step-down from current BPM toward 6 BPM. Gates A/B/C determine when to drop. PRF = BPM at first Gate C pass. Stored in PersonalFingerprint. |
| Resonance hold | `resonance_hold` | Pacer fixed at stored PRF. No step-down. The daily workhorse from Stage 1 onward. |

#### Tier 2 — Technique expansion (Stage 2–3)

| Practice | `practice_type` | Description |
|---|---|---|
| Box breathing | `box_breathing` | Pacer: equal inhale-pause-exhale-pause ratio (configurable). Prescribed on high acute stress signal. Not a PRF training session — a recovery tool. |
| Plexus step-down | `plexus_step_down` | Same as PRF discovery but with an attention anchor. BPM steps down while user directs attention to a body plexus area. |
| Plexus hold | `plexus_hold` | Fixed PRF + attention anchor. Prescribed once PRF is stable. |

#### Tier 3 — Internalization (Stage 4–5)

| Practice | `practice_type` | Description |
|---|---|---|
| Silent meditation | `silent_meditation` | No pacer, no ring timing. System passively records whether coherence at PRF frequency emerges without external cueing. |

### The ring as a pure timing config

The ring (haptic/audio) is unchanged in character across all practices. Only the timing parameters change:

```python
@dataclass
class PacerConfig:
    target_bpm:             float           # current breathing rate to pace
    inhale_sec:             float           # derived from BPM + ratio
    pause_after_inhale_sec: float
    exhale_sec:             float
    pause_after_exhale_sec: float
    step_down_enabled:      bool = False
    step_down_from_bpm:     float = 12.0    # where to start
    step_down_to_bpm:       float = 6.0     # where to stop (or stored PRF)
    step_down_increment:    float = 0.5     # BPM drop per step
    attention_anchor:       Optional[str] = None
    # None | "belly" | "heart" | "solar" | "root" | "brow"
```

The attention anchor is orthogonal — any pacer config can have any attention anchor.

### BPM detection — no accelerometer

The OG app used the accelerometer to directly detect the breath cycle. Verity has no accelerometer. BPM is inferred from the RSA oscillation in the PPI series:

```
PPI series (one value per beat)
        ↓
Bandpass filter: 0.07–0.40 Hz  (covers 4–24 BPM breathing range)
        ↓
Detect local peaks in filtered PPI
        ↓
Period between consecutive peaks = one breath cycle
        ↓
detected_bpm = 60 / period_seconds
```

Implemented in `processing/breath_rate_estimator.py`.
Update cadence: ~5–10 seconds (vs accelerometer ~2–5 seconds). Fast enough for step-down gate decisions — which are already buffered by Gate B stability requirement.

Limitation: Stage 0 users with very weak RSA may produce noisy estimates. Mitigated by: `ring_entrainment` (no Gate A) runs first, building enough RSA signal quality before step-down begins.

### Step-down gates — exactly from OG app design

```
Gate A — BPM match:
    |detected_bpm - target_bpm| ≤ 1.5

Gate B — Stability:
    N consecutive windows all passing Gate A
    N = STEP_DOWN_STABILITY_WINDOWS (config, default 3)

Gate C — RSA quality:
    coherence ≥ 0.65  (zone 3+)
    rsa_peak_frequency × 60 within ±1.5 BPM of target

PRF = target_bpm when all three gates first pass simultaneously
```

`rsa_r > 0.3` from the OG app was a correlation coefficient between accelerometer breath wave and PPI oscillation. Our `coherence ≥ 0.65` subsumes it — no new metric needed.

### Prescription logic

```python
def prescribe_session(
    stage: int,
    prf_status: str,          # "unknown" | "found" | "confirmed"
    session_type: str,        # load label from DailyPrescription
    load_score: float,
    attention_anchor: Optional[str] = None,
) -> PracticeSession
```

| Stage | PRF status | load_score | → practice_type |
|---|---|---|---|
| 0 | unknown | any | `ring_entrainment` (first 2 sessions), then `prf_discovery` |
| 0–1 | unknown | any | `prf_discovery` |
| 1 | found | < 0.65 | `resonance_hold` |
| 1 | found | ≥ 0.65 (high stress) | `box_breathing` |
| 2–3 | confirmed | any | `plexus_hold` (or `plexus_step_down` if re-calibrating) |
| 2–3 | confirmed | ≥ 0.65 | `box_breathing` (overrides plexus) |
| 4–5 | confirmed | < 0.65 | `silent_meditation` |
| 4–5 | confirmed | ≥ 0.65 | `resonance_hold` (fallback — no silent meditation under load) |

### What flows downstream

`PracticeSession` is what the API sends to the device:

```python
@dataclass
class PracticeSession:
    practice_type:     str             # from taxonomy above
    pacer:             Optional[PacerConfig]   # None for silent_meditation
    attention_anchor:  Optional[str]
    duration_minutes:  int
    gates_required:    bool            # True for prf_discovery + plexus_step_down
    prf_target_bpm:    Optional[float] # set when gates_required=True — stop step-down here
    session_notes:     list[str]       # plain English instructions for UI
```

`DailyPrescription` in `coach/plan_replanner.py` gains:
```python
practice_type:     str        # forwarded from PracticeSession
attention_anchor:  Optional[str]
```

`SessionOutcome` in `outcomes/session_outcomes.py` gains:
```python
practice_type:     str        # stored so outcomes can be stratified by practice
attention_anchor:  Optional[str]
```

---

## Layer 5.6: All-Day Tracking (`tracking/`)

*Added 9 March 2026. Sits between the background processing stream and the outcomes/coach layers. Converts continuous background HRV data into the daily Stress/Recovery/Readiness framework.*

**Language:** Python
**Role:** Background stream → aggregated windows → event detection → daily Stress Load + Recovery score + Readiness
**Rule:** No AI here. Deterministic signal processing + threshold-based event detection. Same input always produces same output.

```
tracking/
├── __init__.py                # Public API: compute_daily_summary, get_stress_windows, get_recovery_windows
├── background_processor.py   # Raw background metrics → 5-min BackgroundWindow aggregates
├── stress_detector.py        # BackgroundWindow stream → StressWindow events (spike detection)
├── recovery_detector.py      # BackgroundWindow stream → RecoveryWindow events (uplift detection)
├── daily_summarizer.py       # All windows → DailyStressSummary (stress + recovery + readiness scores)
└── wake_detector.py          # Determine wake/sleep boundary from context transitions + history
```

### Design principle

The tracking layer is a pure consumer of background data. It reads from:
- `BackgroundWindow` rows (5-min HRV aggregates written by `background_processor.py`)
- `PersonalModel` (personal floor, ceiling, morning average — the normalization reference)
- `DailyStressSummary` (prior day's scores — for readiness calculation)

It writes to:
- `BackgroundWindow` (populated by `background_processor.py`)
- `StressWindow` (populated by `stress_detector.py`)
- `RecoveryWindow` (populated by `recovery_detector.py`)
- `DailyStressSummary` (finalized by `daily_summarizer.py` at day close)

The personal model is **read only** by the tracking layer — it never modifies it.

### Background window granularity

```
BackgroundWindow granularity: 5 minutes

Why 5 min:
  - Enough beats for stable RMSSD (≥ 30 beats at resting 60bpm)
  - Fine-grained enough for event detection (a 10-min spike resolves as 2 windows)
  - Produces 144 rows/day for a 12h waking day — manageable
  - Not so fine that noise dominates (1-min windows are too noisy for RMSSD)
```

### Stress event detection algorithm

```python
# stress_detector.py
# Fires when a 5-min window sequence meets all three conditions:

def detect_stress_window(
    windows: list[BackgroundWindow],
    personal_morning_avg: float,    # from PersonalModel.rmssd_morning_avg
    personal_floor: float,          # from PersonalModel.rmssd_floor
) -> list[StressWindow]:

    # Condition 1 — threshold breach
    # RMSSD < 85% of personal morning average
    THRESHOLD_PCT = 0.85

    # Condition 2 — minimum duration
    # Must breach threshold for ≥ 10 minutes (2 consecutive 5-min windows)
    MIN_BREACH_WINDOWS = 2

    # Condition 3 — rate of change (acute spike) OR sustained suppression
    # Rate: RMSSD dropped > 10% in a single 5-min window
    RATE_TRIGGER_PCT = 0.10

    # Merge rule: adjacent breach sequences with gap ≤ 5 min are one event
    MAX_MERGE_GAP_MINUTES = 5

    # Minimum contribution to warrant a nudge prompt
    MIN_NUDGE_CONTRIBUTION_PCT = 0.03   # 3% of daily stress capacity
```

**Physical vs emotional differentiation:**
- ACC/Gyro mean above `MOTION_ACTIVE_THRESHOLD` during window → `tag_candidate = "physical_load"`
- Motion at/below threshold → `tag_candidate = "stress_event"`
- User confirmation converts candidate to confirmed tag

### Recovery window detection algorithm

```python
# recovery_detector.py
# A recovery window is a sustained period where RMSSD is above personal morning average

RECOVERY_THRESHOLD_PCT = 1.00   # at or above personal morning average
MIN_RECOVERY_DURATION_WINDOWS = 3   # 15 minutes minimum

# Auto-tag rules (high confidence, no user input needed):
# ZenFlow session → "zenflow_session"
# context="sleep" windows → "sleep"
# Post-stress-window uplift → "post_stress_recovery"
# Other → "recovery_window" (prompts user to tag, optional)
```

### Daily score computation

```python
# daily_summarizer.py

def compute_stress_load(
    stress_windows: list[StressWindow],
    wake_ts: datetime,
    sleep_ts: datetime,
    personal_morning_avg: float,
    personal_floor: float,
) -> float:
    """
    Stress Load = actual suppression area / max possible suppression area × 100

    max_possible_suppression_area =
        (personal_morning_avg - personal_floor) × waking_minutes

    actual_suppression_area =
        Σ max(0, personal_morning_avg - window_rmssd) × 5 min
        for each BackgroundWindow during waking hours
    """

def compute_recovery_score(
    recovery_windows: list[RecoveryWindow],
    sleep_windows: list[BackgroundWindow],
    zenflow_sessions: list[SessionOutcome],
    personal_morning_avg: float,
    personal_ceiling: float,
) -> float:
    """
    Recovery = recovery credit area / max possible recovery area × 100

    Weighted contributions:
      Sleep    → weight 0.50  (largest recovery mechanism)
      ZenFlow  → weight 0.25  (confirmed, high-quality recovery)
      Daytime  → weight 0.25  (tagged or untagged recovery windows)
    """

def compute_readiness(
    stress_load: float,
    recovery_score: float,
    morning_rmssd: float,
    personal_morning_avg: float,
) -> float:
    """
    net_prior = recovery_score - stress_load
    readiness_prior = 50 + (net_prior / 2)
    morning_calibration = morning_rmssd / personal_morning_avg
    readiness = clamp(readiness_prior × morning_calibration, 0, 100)
    """
```

### Wake/sleep boundary detection

```python
# wake_detector.py

def detect_wake_time(
    context_transitions: list[ContextTransition],  # from bridge stream
    personal_model: PersonalModel,
    morning_read_ts: Optional[datetime],
) -> tuple[datetime, str]:   # (wake_ts, detection_method)
    """
    Priority chain:
    1. "sleep_transition"  — bridge context changes sleep→background
    2. "historical_pattern" — PersonalModel.typical_wake_time (rolling 14-day median)
    3. "morning_read_anchor" — morning read timestamp
    """

def detect_sleep_time(
    context_transitions: list[ContextTransition],
    personal_model: PersonalModel,
    last_background_window_ts: Optional[datetime],
) -> tuple[datetime, str]:
    """
    Priority chain:
    1. "sleep_transition"  — background→sleep context
    2. "historical_pattern" — PersonalModel.typical_sleep_time (rolling 14-day median)
    3. "last_background"   — last active background window + 30min buffer
    """
```

### New schema tables required

**`BackgroundWindow`** — 5-min HRV aggregate during background wear:
```python
# One row per 5-minute window during background or sleep context
# The raw material for all tracking computations
fields: user_id, window_start, window_end, context,
        rmssd_ms, hr_bpm, lf_hf, confidence,
        acc_mean, gyro_mean,       # motion for physical detection
        n_beats, artifact_rate
```

**`StressWindow`** — detected stress event:
```python
# One row per detected stress episode
fields: user_id, started_at, ended_at, duration_minutes,
        rmssd_min_ms,             # lowest point in window
        suppression_pct,          # how far below personal avg
        stress_contribution_pct,  # % of that day's stress load this window caused
        tag,                      # null | "physical_load" | "stress_event" | "workout" | ...
        tag_source,               # "auto_detected" | "user_confirmed" | "auto_tagged"
        tag_candidate,            # pre-confirmation label
        nudge_sent,               # bool — user was prompted
        nudge_responded           # bool
```

**`RecoveryWindow`** — detected recovery episode:
```python
# One row per detected recovery window
fields: user_id, started_at, ended_at, duration_minutes,
        rmssd_avg_ms,
        recovery_contribution_pct,  # % of that day's recovery score
        tag,                        # "sleep" | "zenflow_session" | "walk" | "recovery_window" | ...
        tag_source,                 # "auto_confirmed" | "user_confirmed" | "auto_tagged"
        zenflow_session_id          # FK if linked to a ZenFlow session
```

**`DailyStressSummary`** — one row per user per day:
```python
# Finalized at day close (sleep detection or midnight fallback)
# Updated intraday with running totals
fields: user_id, summary_date,
        wake_ts, sleep_ts, wake_detection_method, sleep_detection_method,
        stress_load_score,          # 0–100
        recovery_score,             # 0–100
        readiness_score,            # 0–100 (finalized next morning after morning read)
        raw_suppression_area,       # actual computation input (for recompute)
        raw_recovery_area,          # actual computation input
        capacity_floor_used,        # which PersonalModel floor was active
        capacity_version,           # PersonalModel.capacity_version at computation time
        top_stress_window_id,       # FK — biggest single stress event
        top_recovery_window_id,     # FK — biggest single recovery event
        is_partial_data,            # True if >2h gap in background stream
        calibration_days,           # how many days of baseline when computed (1–∞)
        is_estimated                # True if calibration_days < 14
```

### PersonalModel additions required

```python
# Two new fields on PersonalModel:
stress_capacity_floor_rmssd: float   # currently active personal floor for stress normalization
capacity_version: int                # increments on each adaptive update
typical_wake_time: str               # "HH:MM" — rolling 14-day median
typical_sleep_time: str              # "HH:MM" — rolling 14-day median
```

### New config section: `config/tracking.py`

```python
class TrackingConfig(BaseSettings):

    # ── Background Window ───────────────────────────────────────────────
    # downstream: tracking/background_processor (window granularity)
    BACKGROUND_WINDOW_MINUTES: int = 5

    # ── Stress Detection ────────────────────────────────────────────────
    # downstream: tracking/stress_detector
    STRESS_THRESHOLD_PCT: float = 0.85    # RMSSD < 85% of personal morning avg
    STRESS_MIN_WINDOWS: int = 2           # ≥ 10 minutes at threshold
    STRESS_MERGE_GAP_MINUTES: int = 5     # merge adjacent events with gap ≤ this
    STRESS_RATE_TRIGGER_PCT: float = 0.10 # 10% drop per window triggers spike check
    STRESS_MIN_NUDGE_CONTRIBUTION: float = 0.03  # 3% of daily capacity

    # ── Recovery Detection ───────────────────────────────────────────────
    # downstream: tracking/recovery_detector
    RECOVERY_THRESHOLD_PCT: float = 1.00  # at or above personal morning avg
    RECOVERY_MIN_WINDOWS: int = 3         # ≥ 15 minutes above threshold

    # ── Recovery Score Weights ───────────────────────────────────────────
    # downstream: tracking/daily_summarizer
    RECOVERY_WEIGHT_SLEEP: float = 0.50
    RECOVERY_WEIGHT_ZENFLOW: float = 0.25
    RECOVERY_WEIGHT_DAYTIME: float = 0.25

    # ── Readiness Formula ────────────────────────────────────────────────
    # downstream: tracking/daily_summarizer
    READINESS_CENTER: float = 50.0        # readiness_prior centers at 50
    READINESS_SCALE: float = 0.50         # (net / 2) → ±25 range before calibration

    # ── Capacity Baseline ────────────────────────────────────────────────
    # downstream: tracking/daily_summarizer, model/personal_distributions
    CAPACITY_UPDATE_FLOOR_SHIFT_PCT: float = 0.10   # 10% shift triggers update check
    CAPACITY_UPDATE_MIN_SUSTAINED_DAYS: int = 7     # must sustain before updating
    CAPACITY_FULL_ACCURACY_DAYS: int = 14           # days before "estimated" drops

    # ── Nudge Cap ────────────────────────────────────────────────────────
    # downstream: api/services/nudge_service
    MAX_TAGGING_NUDGES_PER_DAY: int = 3
    NUDGE_SIGNIFICANT_SPIKE_OVERRIDE_PCT: float = 0.25  # spike > 25% cap → override

    # ── Gap Handling ─────────────────────────────────────────────────────
    # downstream: tracking/background_processor
    GAP_CONTINUITY_MINUTES: int = 30     # gaps < this assumed continuous
    GAP_PARTIAL_DATA_MINUTES: int = 120  # gaps > this mark day as partial

    # ── Motion Thresholds ────────────────────────────────────────────────
    # downstream: tracking/stress_detector (physical vs emotional classification)
    MOTION_ACTIVE_THRESHOLD: float = 0.3   # ACC mean above this = movement detected

    # ── Auto-tag Pattern Minimum ─────────────────────────────────────────
    # downstream: tracking/auto_tagger (future)
    AUTOTAG_MIN_CONFIRMED_EVENTS: int = 4  # need ≥ 4 confirmed events in same pattern
    AUTOTAG_MIN_DAYS: int = 28             # at least 4 weeks of data
```

---

## Layer 6: Outcomes Engine (`outcomes/`)

**Language:** Python  
**Role:** Compute whether the training plan is working, at three timescales

```
outcomes/
├── session_outcomes.py   # Per-session: coherence depth, pre/post RMSSD delta, session score
├── level_gate.py         # Physiology-gated stage advancement criteria — not time-based
└── __init__.py           # Public API
```

*`weekly_outcomes.py`, `longitudinal_outcomes.py`, `report_builder.py` are deferred to API phase.*

---

### Design decisions

**Pre/post delta source:**
- `pre_rmssd_ms` = last 2 minutes of signal before guided breathing begins (session-start window)
- `post_rmssd_ms` = last 2 minutes of the session
- Morning read stored as `morning_rmssd_ms` (context only — not used in computing the delta)
- Rationale: morning read is hours earlier and reflects sleep recovery, not session readiness

**Session score formula** (composite, 0.0–1.0):
```
session_score = (coherence_avg × 0.40) + (coherence_peak × 0.30) + (time_in_zone_3_plus × 0.30)
```
- `coherence_avg` — mean coherence across all valid windows (breadth)
- `coherence_peak` — highest coherence window (ceiling hit)
- `time_in_zone_3_plus` — fraction of windows in zone 3 or 4 (sustained quality)

Three components because a session that averages 0.5 but peaks at 0.9 is
different from one that averages 0.5 and never breaks 0.6.

**Model write-back:**
Session outcomes stores results only. `api/services/model_service.py` recomputes
`PersonalFingerprint` from all stored sessions on a schedule. Session outcomes does not
directly mutate the fingerprint — clean separation.

---

### `SessionOutcome` schema

```python
@dataclass
class SessionOutcome:
    session_id:              str
    session_date:            date
    duration_minutes:        int
    session_type:            str        # "breathing_only"|"full"|"active_recovery"|"rest"

    # Coherence quality
    coherence_avg:           Optional[float]   # 0.0–1.0 mean across windows
    coherence_peak:          Optional[float]   # highest window
    time_in_zone_3_plus:     Optional[float]   # fraction of windows in zone 3 or 4
    session_score:           Optional[float]   # composite 0.0–1.0

    # Pre/post RMSSD
    pre_rmssd_ms:            Optional[float]   # session-start 2-min window
    post_rmssd_ms:           Optional[float]   # session-end 2-min window
    rmssd_delta_ms:          Optional[float]   # post − pre (positive = improved)
    rmssd_delta_pct:         Optional[float]   # delta / (personal floor) — personal-relative

    # Recovery arc
    arc_completed:           bool
    arc_duration_hours:      Optional[float]

    # Context
    morning_rmssd_ms:        Optional[float]   # reference only
    windows_valid:           int
    windows_total:           int
    data_quality:            float             # fraction of valid windows
    notes:                   list[str]
```

---

### Level gate criteria (physiology-gated, not time-gated)

Stage advancement can take 1 week or 8. The gate checks physiology, not calendar.

| Stage | Min sessions | Coherence criterion | Score criterion | Additional |
|---|---|---|---|---|
| 0 → 1 | 2 | data_quality_avg ≥ 0.50 | total_score ≥ 35 | Can produce stable signal |
| 1 → 2 | 6 | coherence_avg_last3 ≥ 0.40 | total_score ≥ 55 | rmssd_delta positive ≥ 50% of sessions |
| 2 → 3 | 12 | coherence_avg_last3 ≥ 0.55 | total_score ≥ 70 | arc_completed ≥ 50% of sessions |
| 3 → 4 | 18 | coherence_peak_avg ≥ 0.70 | total_score ≥ 80 | rmssd_delta positive ≥ 60% of sessions |
| 4 → 5 | 24 | coherence_peak_avg ≥ 0.80 | total_score ≥ 90 | arc_duration shortening vs first 6 sessions |

`LevelGateResult` returns: `ready: bool`, `current_stage: int`,
`criteria_met: dict[str, bool]`, `blocking: list[str]`.

---

## Layer 7: API Bridge (`api/`)

**Language:** Python (FastAPI)  
**Role:** Single backend entry point. Connects all layers. Serves UI and mobile client.

```
api/
├── main.py                    # FastAPI app init, middleware, CORS
├── routers/
│   ├── stream.py              # WebSocket endpoint — receives bridge data, routes to processing
│   ├── session.py             # POST /session/start, /session/end, GET /session/{id}/result
│   ├── user.py                # GET /user/profile, /user/fingerprint, /user/archetype
│   ├── coach.py               # GET /coach/morning-brief, /coach/post-session, /coach/nudge
│   ├── conversation.py        # POST /coach/conversation — real-time voice/text exchange
│   ├── outcomes.py            # GET /outcomes/weekly, /outcomes/monthly, /outcomes/report-card
│   └── plan.py                # GET /plan/today, /plan/week, POST /plan/check-in
├── services/
│   ├── session_service.py         # Orchestrates processing pipeline during a live session
│   ├── model_service.py           # CRUD for personal model, fingerprint updates
│   ├── coach_service.py           # Assembles context, calls coach layer, returns message
│   ├── conversation_service.py    # Manages conversation state, calls extractor, triggers replan
│   └── outcome_service.py         # Runs outcome computations on schedule + on demand
├── db/
│   ├── schema.py              # SQLAlchemy models
│   ├── migrations/            # Alembic
│   └── seed.py                # Dev data
└── config.py                  # Env vars, feature flags, LLM config
```

**Key API endpoints:**

| Method | Path | Description |
|---|---|---|
| `WS` | `/ws/stream` | Live hardware stream from bridge |
| `POST` | `/session/start` | Begin guided session |
| `POST` | `/session/end` | End session, trigger outcome computation |
| `GET` | `/coach/morning-brief` | Today's personalised synthesis + action |
| `GET` | `/coach/post-session` | Post-session coaching message + score |
| `POST` | `/coach/conversation` | Send user voice/text input, receive coach response + plan delta |
| `GET` | `/coach/conversation/history` | Retrieve past conversation turns for context display |
| `GET` | `/user/archetype` | Current archetype + evolution history |
| `GET` | `/user/habits` | User habit profile |
| `PUT` | `/user/habits` | Update habit profile (after onboarding or user edit) |
| `GET` | `/outcomes/report-card` | Weekly report card (one-screen format) |
| `GET` | `/plan/today` | Today's prescribed session + timing |
| `POST` | `/plan/check-in` | Submit 3-day subjective self-report |
| `GET` | `/tracking/daily-summary` | Today's Stress Load, Recovery, Readiness scores + waveform data |
| `GET` | `/tracking/daily-summary/{date}` | Historical day's summary |
| `GET` | `/tracking/waveform/{date}` | Full 5-min BackgroundWindow series for waveform rendering |
| `GET` | `/tracking/stress-windows/{date}` | All stress events for a day (tagged + untagged) |
| `GET` | `/tracking/recovery-windows/{date}` | All recovery contributions for a day |
| `POST` | `/tracking/tag-window` | User submits or updates a tag on a stress/recovery window |
| `GET` | `/tracking/history` | Multi-day summary for history view (date range) |

---

## Layer 8: UI Client (`ui/`)

**Language:** React + TypeScript  
**Role:** The only layer the user sees. Must feel personal, warm, simple.

```
ui/
├── src/
│   ├── screens/
│   │   ├── MorningBrief.tsx       # First screen of the day — one synthesis sentence + action
│   │   ├── Session.tsx            # Live session: ring visualiser, coherence%, zone indicator
│   │   ├── PostSession.tsx        # Coach message + session score + one insight
│   │   ├── ReportCard.tsx         # Weekly report — 3 metrics, plain English, one next step
│   │   ├── Archetype.tsx          # "This is who your nervous system is" — full profile view
│   │   ├── Journey.tsx            # Timeline: archetype evolution + milestone moments
│   │   ├── CheckIn.tsx            # 3-question subjective self-report (every 3 days)
│   │   └── CoachConversation.tsx  # Voice/text coach chat — morning, reactive, post-session modes
│   ├── components/
│   │   ├── CoherenceRing.tsx      # The core session visual — ring fills with coherence%
│   │   ├── ResilienceBar.tsx      # Today's resilience vs personal average
│   │   ├── ZoneIndicator.tsx      # Zone 1–4 colour + sound feedback during session
│   │   ├── MetricCard.tsx         # Reusable: metric name + plain-English meaning + value
│   │   ├── CoachMessage.tsx       # Styled coach voice — renders summary + reason + action
│   │   ├── MilestoneToast.tsx     # Celebration moment — surfaces real physiological change
│   │   ├── VoiceInput.tsx         # Push-to-talk voice capture → sends transcript to API
│   │   └── PlanDeltaBadge.tsx     # Shows when today's plan changed due to conversation
│   ├── hooks/
│   │   ├── useSessionStream.ts    # WebSocket connection to live session data
│   │   ├── usePersonalModel.ts    # Fetches + caches user fingerprint
│   │   ├── useCoach.ts            # Fetches coach messages, handles loading states
│   │   └── useConversation.ts     # Manages conversation turn state, voice recording, transcript
│   ├── store/
│   │   └── sessionStore.ts        # Zustand store for live session state
│   └── api/
│       └── client.ts              # Typed API client — all backend calls in one place
```

**UI design rules:**
- No HRV jargon visible to user. Ever.
- Every number has a plain-English sentence. No orphaned metrics.
- One action per screen. No decision fatigue.
- Coach voice is always first-person about the user ("your", "you"), never generic.
- Milestone moments get their own full-screen treatment — not a badge, a narrative.

---

## Full Data Flow — Live Session

```
[Polar Verity Sense]
        │  BLE
        ▼
[bridge/PolarConnector.swift]
        │  artifact-flagged PPI/PPG/ACC/Gyro packets
        ▼
[api/routers/stream.py]  ← WebSocket
        │  routes by stream type
        ▼
[processing/]  (ppi_processor, rsa_analyzer, coherence_scorer, ppg_processor)
        │  metrics + confidence scores
        ▼
[api/services/session_service.py]  (orchestrates, holds session state)
        │  real-time coherence%, zone, RMSSD
        ▼
[ui/hooks/useSessionStream.ts]  ← WebSocket push
        │
        ▼
[ui/screens/Session.tsx]  (CoherenceRing, ZoneIndicator)

─── session ends ───

[outcomes/session_outcomes.py]  (pre/post delta, session score)
        │
        ▼
[model/personal_distributions.py]  (update fingerprint)
        │
        ▼
[archetypes/evolution_tracker.py]  (check archetype drift)
        │
        ▼
[coach/coach_api.py]  (generate post-session message)
        │
        ▼
[ui/screens/PostSession.tsx]  (CoachMessage, MilestoneToast if triggered)
```

---

## Full Data Flow — Morning Brief

```
[Scheduled trigger: on app open, or 7am background task]
        │
        ▼
[api/routers/coach.py → GET /coach/morning-brief]
        │
        ▼
[coach/context_builder.py]
  pulls: last night's sleep HRV, morning RMSSD read,
         stress trend from yesterday, this week's sessions,
         archetype, recent milestones
        │
        ▼
[coach/tone_selector.py]  (compassion / push / celebrate / warn)
        │
        ▼
[coach/coach_api.py]  → LLM call with structured context
        │
        ▼
[ui/screens/MorningBrief.tsx]
  shows: one synthesis sentence
         physiological reason
         today's recommended action
         optional: milestone moment
```

---

## Directory Structure (Complete)

```
ZenFlow_Verity/
├── config/                    # Central configuration — single source of truth
│   ├── __init__.py            # Exports single CONFIG object
│   ├── base.py                # ZenFlowConfig assembler
│   ├── processing.py          # Signal processing parameters
│   ├── model.py               # Personal model parameters
│   ├── scoring.py             # Coherence, zone, level gate thresholds
│   ├── tracking.py            # All-day tracking thresholds (stress/recovery detection)
│   ├── coach.py               # LLM settings, tone thresholds
│   ├── features.py            # Feature flags
│   ├── versions.py            # Config version registry
│   └── environments/
│       ├── development.env
│       ├── staging.env
│       └── production.env
│
├── bridge/                    # Swift — BLE + hardware streaming
│   ├── PolarConnector.swift
│   ├── StreamRouter.swift
│   ├── ArtifactFilter.swift
│   ├── WebSocketEmitter.swift
│   └── HealthKitIngester.swift
│
├── processing/                # Python — raw signals → metrics
│   ├── ppi_processor.py
│   ├── rsa_analyzer.py
│   ├── coherence_scorer.py
│   ├── breath_extractor.py
│   ├── ppg_processor.py
│   ├── motion_analyzer.py
│   ├── recovery_arc.py
│   └── artifact_handler.py
│
├── tracking/                  # Python — all-day HRV → stress/recovery/readiness
│   ├── __init__.py            # Public API: compute_daily_summary, get windows
│   ├── background_processor.py  # Raw background metrics → 5-min BackgroundWindow rows
│   ├── stress_detector.py       # BackgroundWindow stream → StressWindow events
│   ├── recovery_detector.py     # BackgroundWindow stream → RecoveryWindow events
│   ├── daily_summarizer.py      # Windows → DailyStressSummary (stress + recovery + readiness)
│   └── wake_detector.py         # Wake/sleep boundary from context transitions + history
│
├── model/                     # Python — personal physiological model
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
├── archetypes/                # Python — NS Health Score engine
│   ├── scorer.py              # PersonalFingerprint → NSHealthProfile
│   ├── narrative.py           # NSHealthProfile → NSNarrative
│   └── __init__.py            # Public API
│
├── coach/                     # Python — AI coach (LLM layer) + conversation
│   ├── context_builder.py
│   ├── prompt_templates.py
│   ├── tone_selector.py
│   ├── coach_api.py
│   ├── memory_store.py
│   ├── milestone_detector.py
│   ├── conversation.py
│   ├── conversation_extractor.py
│   ├── plan_replanner.py
│   └── safety_filter.py
│
├── outcomes/                  # Python — outcome computation
│   ├── session_outcomes.py
│   ├── weekly_outcomes.py
│   ├── longitudinal_outcomes.py
│   ├── hardmode_tracker.py
│   ├── stress_fingerprint_map.py
│   ├── report_builder.py
│   └── level_gate.py
│
├── api/                       # Python FastAPI — backend
│   ├── main.py
│   ├── routers/
│   │   ├── stream.py
│   │   ├── session.py
│   │   ├── user.py
│   │   ├── coach.py
│   │   ├── outcomes.py
│   │   ├── plan.py
│   │   └── tracking.py        # Stress/recovery/readiness + tagging endpoints
│   ├── services/
│   │   ├── session_service.py
│   │   ├── model_service.py
│   │   ├── coach_service.py
│   │   ├── conversation_service.py
│   │   ├── outcome_service.py
│   │   └── tracking_service.py  # Orchestrates tracking layer, writes windows + summaries
│   ├── db/
│   │   ├── schema.py          # ORM models (incl. BackgroundWindow, StressWindow, RecoveryWindow, DailyStressSummary)
│   │   ├── migrations/
│   │   └── seed.py
│   └── config.py
│
├── ui/                        # React + TypeScript — client
│   ├── src/
│   │   ├── screens/
│   │   │   ├── Home.tsx               # Three numbers + synthesis sentence
│   │   │   ├── StressDetail.tsx       # Waveform + itemized stress events
│   │   │   ├── RecoveryDetail.tsx     # Recovery graph + itemized contributions
│   │   │   ├── ReadinessOverlay.tsx   # Both waveforms overlaid + net position
│   │   │   ├── MorningBrief.tsx
│   │   │   ├── Session.tsx
│   │   │   ├── PostSession.tsx
│   │   │   ├── ReportCard.tsx
│   │   │   ├── Archetype.tsx
│   │   │   ├── Journey.tsx
│   │   │   ├── CheckIn.tsx
│   │   │   └── CoachConversation.tsx
│   │   ├── components/
│   │   │   ├── StressWaveform.tsx     # Continuous RMSSD/baseline graph, event bands
│   │   │   ├── RecoveryWaveform.tsx   # Recovery credit graph
│   │   │   ├── ScoreCard.tsx          # Single score tile (Stress/Recovery/Readiness)
│   │   │   ├── EventRow.tsx           # One tagged/untagged event row in itemized view
│   │   │   ├── TagSheet.tsx           # Bottom sheet — 4-option quick tag UI
│   │   │   ├── CoherenceRing.tsx
│   │   │   ├── ResilienceBar.tsx
│   │   │   ├── ZoneIndicator.tsx
│   │   │   ├── MetricCard.tsx
│   │   │   ├── CoachMessage.tsx
│   │   │   ├── MilestoneToast.tsx
│   │   │   ├── VoiceInput.tsx
│   │   │   └── PlanDeltaBadge.tsx
│   │   ├── hooks/
│   │   │   ├── useDailySummary.ts     # Fetches today's 3 scores + waveform
│   │   │   ├── useStressWindows.ts    # Fetches stress event list for a date
│   │   │   ├── useRecoveryWindows.ts  # Fetches recovery contribution list
│   │   │   ├── useSessionStream.ts
│   │   │   ├── usePersonalModel.ts
│   │   │   ├── useCoach.ts
│   │   │   └── useConversation.ts
│   │   ├── store/
│   │   │   └── sessionStore.ts
│   │   └── api/
│   │       └── client.ts
│   └── package.json
│
├── tests/                     # All test suites
│   ├── processing/
│   ├── model/
│   ├── coach/
│   ├── tracking/              # Tests for all tracking/ modules
│   └── api/
│
├── CONTEXT.md
├── PRODUCT_DESIGN.md
├── ARCHITECTURE.md
└── UI_DESIGN.md
```
│
├── bridge/                    # Swift — BLE + hardware streaming
│   ├── PolarConnector.swift
│   ├── StreamRouter.swift
│   ├── ArtifactFilter.swift
│   ├── WebSocketEmitter.swift
│   └── HealthKitIngester.swift
│
├── processing/                # Python — raw signals → metrics
│   ├── ppi_processor.py
│   ├── rsa_analyzer.py
│   ├── coherence_scorer.py
│   ├── breath_extractor.py
│   ├── ppg_processor.py
│   ├── motion_analyzer.py
│   ├── recovery_arc.py
│   └── artifact_handler.py
│
├── model/                     # Python — personal physiological model
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
├── archetypes/                # Python — NS Health Score engine
│   ├── scorer.py              # PersonalFingerprint → NSHealthProfile
│   ├── narrative.py           # NSHealthProfile → NSNarrative
│   └── __init__.py            # Public API
│
├── coach/                     # Python — AI coach (LLM layer) + conversation
│   ├── context_builder.py
│   ├── prompt_templates.py
│   ├── tone_selector.py
│   ├── coach_api.py
│   ├── memory_store.py
│   ├── milestone_detector.py
│   ├── conversation.py            # Turn-taking, session state, mode detection
│   ├── conversation_extractor.py  # Freeform text → structured model signals
│   ├── plan_replanner.py          # Adjust today's plan from conversation context
│   └── safety_filter.py           # Clinical language detection → professional resource exit
│
├── outcomes/                  # Python — outcome computation
│   ├── session_outcomes.py
│   ├── weekly_outcomes.py
│   ├── longitudinal_outcomes.py
│   ├── hardmode_tracker.py
│   ├── stress_fingerprint_map.py
│   ├── report_builder.py
│   └── level_gate.py
│
├── api/                       # Python FastAPI — backend
│   ├── main.py
│   ├── routers/
│   │   ├── stream.py
│   │   ├── session.py
│   │   ├── user.py
│   │   ├── coach.py
│   │   ├── outcomes.py
│   │   └── plan.py
│   ├── services/
│   │   ├── session_service.py
│   │   ├── model_service.py
│   │   ├── coach_service.py
│   │   └── outcome_service.py
│   ├── db/
│   │   ├── schema.py
│   │   ├── migrations/
│   │   └── seed.py
│   └── config.py
│
├── ui/                        # React + TypeScript — client
│   ├── src/
│   │   ├── screens/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── store/
│   │   └── api/
│   └── package.json
│
├── CONTEXT.md                 # Hardware + algorithm decisions
├── PRODUCT_DESIGN.md          # Product philosophy + metric stack + archetypes
└── ARCHITECTURE.md            # This file
```

---

## Boundaries — What Each Layer Is Responsible For

| Layer | Owns | Does NOT own |
|---|---|---|
| `config/` | All thresholds, windows, flags — typed + versioned | Nothing else. Pure data. |
| `bridge/` | Clean signal delivery | Any computation or interpretation |
| `processing/` | Deterministic metric computation | Personalisation, history, AI |
| `tracking/` | All-day HRV aggregation → stress/recovery/readiness scores | Raw signal processing, coaching |
| `model/` | This user's patterns over time | Real-time computation, UI |
| `archetypes/` | Identity + prescription logic | Raw signals, UI rendering |
| `coach/` | Language, tone, narrative, conversation, plan replanning | Metric computation |
| `outcomes/` | Did the plan work? | What to do next (that's coach) |
| `api/` | Orchestration + routing | Business logic (lives in services) |
| `ui/` | What the user sees and feels | Any physiological logic |

**Golden rule:** No module defines its own constants. If a number appears in any module outside of `config/`, it is a bug.

---

*This architecture file is the source of truth for system design decisions. Update as the system evolves.*
