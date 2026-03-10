"""
archetypes/scorer.py

Converts a PersonalFingerprint into an NSHealthProfile.

Design:
    Score leads. Personality pattern supports.

    The score is a weighted composite of 5 physiological dimensions,
    each 0–20, summing to 0–100. The pattern (Over-Optimizer, Hustler
    etc.) is detected from dimension scores + raw fingerprint signals.
    It supports the coaching narrative — it does NOT drive the score.

    Score → Stage → Focus actions → Narrative (in narrative.py)

Five dimensions:
    1. Recovery Capacity    — How fast and fully does the system return to baseline?
    2. Baseline Resilience  — How strong is the resting nervous system floor?
    3. Coherence Capacity   — How well does the system respond to guided practice?
    4. Chronobiological Fit — Is the person living in alignment with their biological clock?
    5. Load Management      — Is the accumulated weekly stress load staying manageable?

Pattern detection:
    Each pattern gets an evidence score (0.0–1.0) from weighted signals.
    Primary = highest. Amplifier = second-highest if score >= AMPLIFIER_THRESHOLD.
    At low overall_confidence (<0.4) pattern is UNCLASSIFIED.

References:
    NS Health Score concept finalised 7 March 2026 —  conversation with product owner.
    PersonalFingerprint defined in model/baseline_builder.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from model.baseline_builder import PersonalFingerprint


# ── Constants ──────────────────────────────────────────────────────────────────

_AMPLIFIER_THRESHOLD = 0.20   # secondary pattern must score >= this to surface
_MIN_CONFIDENCE_FOR_PATTERN = 0.35  # below this → UNCLASSIFIED

STAGE_THRESHOLDS = {
    0: (0,  34),
    1: (35, 54),
    2: (55, 69),
    3: (70, 79),
    4: (80, 89),
    5: (90, 100),
}

STAGE_TARGETS = {
    0: 40,
    1: 55,
    2: 70,
    3: 80,
    4: 90,
    5: 100,
}


# ── Output dataclass ───────────────────────────────────────────────────────────

@dataclass
class NSHealthProfile:
    """
    The complete nervous system health profile for a user.

    The score is the truth. The pattern is the story.
    """

    # ── Score ──────────────────────────────────────────────────────────────────
    total_score:         int               # 0–100
    stage:               int               # 0–5
    stage_target:        int               # next stage threshold

    # ── Five dimensions (each 0–20) ─────────────────────────────────────────
    recovery_capacity:   int               # recovery arc speed + sleep efficiency
    baseline_resilience: int               # RMSSD floor strength + ceiling range
    coherence_capacity:  int               # RSA trainability + coherence floor
    chrono_fit:          int               # sleep recovery efficiency + morning alignment
    load_management:     int               # LF/HF resting + weekly balance

    # ── Pattern layer ─────────────────────────────────────────────────────────
    primary_pattern:     str               # e.g. "over_optimizer", "UNCLASSIFIED"
    amplifier_pattern:   Optional[str]     # second pattern if active, else None
    pattern_scores:      dict              # all raw pattern evidence scores

    # ── Trajectory (populated after first score; None until then) ─────────────
    score_7d_delta:      Optional[int]  = None
    score_30d_delta:     Optional[int]  = None
    trajectory:          str            = "stable"   # "improving"|"stable"|"declining"

    # ── Coaching ──────────────────────────────────────────────────────────────
    stage_focus:         list[str]      = field(default_factory=list)   # 2–3 actions
    weeks_in_stage:      int            = 0

    # ── Meta ──────────────────────────────────────────────────────────────────
    overall_confidence:  float          = 0.0
    data_hours:          float          = 0.0

    def dimension_breakdown(self) -> dict:
        return {
            "recovery_capacity":   self.recovery_capacity,
            "baseline_resilience": self.baseline_resilience,
            "coherence_capacity":  self.coherence_capacity,
            "chrono_fit":          self.chrono_fit,
            "load_management":     self.load_management,
        }


# ── Public API ─────────────────────────────────────────────────────────────────

def compute_ns_health_profile(
    fp: PersonalFingerprint,
    score_7d_delta: Optional[int] = None,
    score_30d_delta: Optional[int] = None,
    weeks_in_stage: int = 0,
) -> NSHealthProfile:
    """
    Compute NSHealthProfile from a PersonalFingerprint.

    Parameters
    ----------
    fp : PersonalFingerprint
        Output of BaselineBuilder.build() — may have None fields.
    score_7d_delta : int | None
        Score change over last 7 days (from previous profile snapshot).
    score_30d_delta : int | None
        Score change over last 30 days.
    weeks_in_stage : int
        How many weeks the user has been in their current stage.

    Returns
    -------
    NSHealthProfile
    """
    rc  = _score_recovery_capacity(fp)
    br  = _score_baseline_resilience(fp)
    cc  = _score_coherence_capacity(fp)
    cf  = _score_chrono_fit(fp)
    lm  = _score_load_management(fp)

    total = rc + br + cc + cf + lm
    stage = _compute_stage(total)

    pattern_scores = _compute_pattern_scores(fp, rc, br, cc, cf, lm)
    primary, amplifier = _select_patterns(pattern_scores, fp.overall_confidence)

    trajectory = _compute_trajectory(score_7d_delta)
    focus      = _stage_focus(stage, primary)

    return NSHealthProfile(
        total_score        = total,
        stage              = stage,
        stage_target       = STAGE_TARGETS[stage],
        recovery_capacity  = rc,
        baseline_resilience= br,
        coherence_capacity = cc,
        chrono_fit         = cf,
        load_management    = lm,
        primary_pattern    = primary,
        amplifier_pattern  = amplifier,
        pattern_scores     = pattern_scores,
        score_7d_delta     = score_7d_delta,
        score_30d_delta    = score_30d_delta,
        trajectory         = trajectory,
        stage_focus        = focus,
        weeks_in_stage     = weeks_in_stage,
        overall_confidence = fp.overall_confidence,
        data_hours         = fp.data_hours_available,
    )


# ── Dimension scoring ──────────────────────────────────────────────────────────

def _score_recovery_capacity(fp: PersonalFingerprint) -> int:
    """
    How fast and fully does the nervous system return to its resting baseline?

    Primary signals:
      - recovery_arc_class → base score  (FAST=16, NORMAL=11, SLOW=6, COMPRESSED=2)
      - sleep_recovery_efficiency        (morning > evening = good)
      - n_incomplete arcs                (penalty)
    """
    # Base from arc class
    arc_class = fp.recovery_arc_class
    if arc_class is None:
        base = 9  # unknown — neutral mid-point
    elif arc_class == "fast":
        base = 16
    elif arc_class == "normal":
        base = 11
    elif arc_class == "slow":
        base = 6
    elif arc_class in ("compressed", "incomplete"):
        base = 2
    else:
        base = 9

    # Sleep recovery efficiency adjustment
    sre = fp.sleep_recovery_efficiency
    if sre is not None:
        if sre >= 1.20:
            base += 4
        elif sre >= 1.08:
            base += 2
        elif sre >= 0.92:
            base += 0
        elif sre >= 0.80:
            base -= 2
        else:
            base -= 4

    return max(0, min(20, base))


def _score_baseline_resilience(fp: PersonalFingerprint) -> int:
    """
    How strong is the resting nervous system floor?

    Primary signals:
      - rmssd_floor       (absolute floor in ms)
      - rmssd_range       (ceiling − floor; wider = more adaptive capacity)
      - has_prior_practice (small bonus)
    """
    floor = fp.rmssd_floor

    if floor is None:
        base = 8
    elif floor >= 55:
        base = 18
    elif floor >= 45:
        base = 14
    elif floor >= 35:
        base = 10
    elif floor >= 25:
        base = 6
    else:
        base = 3

    # Range bonus: person has high ceiling relative to floor = adaptive capacity
    rng = fp.rmssd_range
    if rng is not None:
        if rng >= 30:
            base += 2
        elif rng >= 20:
            base += 1

    # Prior practice means vagal tone has been cultivated
    if fp.has_prior_practice:
        base += 1

    return max(0, min(20, base))


def _score_coherence_capacity(fp: PersonalFingerprint) -> int:
    """
    How well does the nervous system respond to guided practice?

    Primary signals:
      - coherence_floor     (resting coherence level)
      - rsa_trainability    (how much does guided practice elevate RSA?)
      - coherence_trainability
    """
    floor = fp.coherence_floor

    if floor is None:
        base = 7
    elif floor >= 0.55:
        base = 16
    elif floor >= 0.45:
        base = 13
    elif floor >= 0.35:
        base = 10
    elif floor >= 0.25:
        base = 7
    else:
        base = 4

    # RSA trainability bonus
    rsa_t = fp.rsa_trainability
    if rsa_t == "high":
        base += 4
    elif rsa_t == "moderate":
        base += 2

    # Coherence trainability bonus
    coh_t = fp.coherence_trainability
    if coh_t == "high":
        base += 2
    elif coh_t == "moderate":
        base += 1

    return max(0, min(20, base))


def _score_chrono_fit(fp: PersonalFingerprint) -> int:
    """
    Is the person's biology aligned with their daily schedule?

    High score = mornings recover well, window matches life.
    Low score = fighting chronotype (Night Warrior) or poor sleep quality.

    Primary signals:
      - sleep_recovery_efficiency   (morning RMSSD / evening RMSSD)
      - rmssd_morning_avg relative to rmssd_floor
    """
    sre = fp.sleep_recovery_efficiency

    if sre is None:
        base = 10
    elif sre >= 1.25:
        base = 18
    elif sre >= 1.12:
        base = 15
    elif sre >= 1.00:
        base = 12
    elif sre >= 0.88:
        base = 8
    elif sre >= 0.75:
        base = 5
    else:
        base = 2

    # Morning avg relative to personal floor: are mornings actually strong?
    m_avg = fp.rmssd_morning_avg
    m_floor = fp.rmssd_floor
    if m_avg is not None and m_floor is not None and m_floor > 0:
        ratio = m_avg / m_floor
        if ratio >= 1.20:
            base += 2
        elif ratio >= 1.05:
            base += 1
        elif ratio < 0.90:
            base -= 2

    return max(0, min(20, base))


def _score_load_management(fp: PersonalFingerprint) -> int:
    """
    Is the accumulated weekly stress staying manageable?

    Primary signals:
      - lf_hf_resting      (sympathovagal balance at rest)
      - lf_hf_sleep        (sympathovagal balance during sleep)
      - overnight_rmssd_delta_avg (is sleep actively recovering or degrading?)
    """
    lf_hf = fp.lf_hf_resting

    if lf_hf is None:
        base = 10
    elif lf_hf <= 1.3:
        base = 18
    elif lf_hf <= 1.7:
        base = 14
    elif lf_hf <= 2.1:
        base = 9
    elif lf_hf <= 2.6:
        base = 5
    else:
        base = 2

    # Sleep LF/HF: high = sympathetic active overnight = load not clearing
    lf_hf_sl = fp.lf_hf_sleep
    if lf_hf_sl is not None:
        if lf_hf_sl <= 1.5:
            base += 2
        elif lf_hf_sl >= 2.2:
            base -= 3

    # Overnight delta: negative = RMSSD dropping during sleep (bad)
    ond = fp.overnight_rmssd_delta_avg
    if ond is not None:
        if ond >= 5.0:
            base += 2
        elif ond < 0:
            base -= 2

    return max(0, min(20, base))


# ── Stage computation ──────────────────────────────────────────────────────────

def _compute_stage(total: int) -> int:
    for stage, (lo, hi) in STAGE_THRESHOLDS.items():
        if lo <= total <= hi:
            return stage
    return 5


# ── Pattern detection ──────────────────────────────────────────────────────────

def _compute_pattern_scores(
    fp: PersonalFingerprint,
    rc: int, br: int, cc: int, cf: int, lm: int,
) -> dict[str, float]:
    """
    Score each pattern 0.0–1.0 based on evidence strength.

    Each pattern's signals are weighted. Score = weighted sum / sum-of-weights.
    Signals are boolean evidence flags (True = 1, False = 0).
    The result is NOT a probability — it's an evidence index.
    """
    scores = {}

    # ── Over-Optimizer ────────────────────────────────────────────────────────
    # Core signal: high training load visible in autonomic data, but recovery ignored.
    # Their RMSSD potential exists (not depleted) — it's specifically the recovery gap.
    #
    # Evidence:
    #   - Load management low        (training stress accumulating)        w=0.35
    #   - Recovery capacity low      (not recovering between loads)        w=0.25
    #   - Baseline resilience moderate+ (potential is there — fit person)  w=0.20
    #   - LF/HF resting elevated     (sympathetic dominant at rest)        w=0.20
    oo_signals = {
        "load_low":         (lm <= 10,           0.35),
        "recovery_low":     (rc <= 10,           0.25),
        "resilience_mod":   (br >= 8,            0.20),   # NOT fully depleted
        "lf_hf_high":       (_safe_gt(fp.lf_hf_resting, 1.8), 0.20),
    }
    scores["over_optimizer"] = _weighted_evidence(oo_signals)

    # ── Trend Chaser ──────────────────────────────────────────────────────────
    # No sustained practice. Mid-range baseline. Low coherence engagement.
    # Often identified from onboarding via no prior practice + no consistent pattern.
    #
    #   - Coherence capacity low     (no practice depth)                   w=0.35
    #   - No prior practice          (onboarding signal)                   w=0.30
    #   - Resilience not depleted    (not in crisis — just undiscovered)   w=0.20
    #   - Low overall confidence     (data inconsistent — no habit)        w=0.15
    tc_signals = {
        "coherence_low":    (cc <= 9,                    0.35),
        "no_practice":      (not fp.has_prior_practice,  0.30),
        "resilience_ok":    (6 <= br <= 13,              0.20),
        "low_confidence":   (fp.overall_confidence < 0.6, 0.15),
    }
    scores["trend_chaser"] = _weighted_evidence(tc_signals)

    # ── Hustler ───────────────────────────────────────────────────────────────
    # Work/life demands drive slow load accumulation. Mornings okay. Arcs slow.
    # Distinguished from Over-Optimizer: the loading is external, not voluntary training.
    #
    #   - Load management low        (weekly accumulation)                 w=0.30
    #   - Recovery capacity low      (slow arcs)                          w=0.30
    #   - Chrono fit moderate        (not night warrior — mornings ok)     w=0.20
    #   - Coherence capacity low     (no recovery practice)                w=0.20
    hu_signals = {
        "load_low":         (lm <= 10,           0.30),
        "recovery_low":     (rc <= 11,           0.30),
        "chrono_ok":        (cf >= 8,            0.20),   # mornings not terrible
        "coherence_low":    (cc <= 10,           0.20),
    }
    scores["hustler"] = _weighted_evidence(hu_signals)

    # ── Quiet Depleter ────────────────────────────────────────────────────────
    # Slow baseline erosion. Floor low. Ceiling low. No crisis visible.
    # The system is flat — not reactive, not damaged, just under-powered.
    #
    #   - Baseline resilience low    (floor has eroded)                   w=0.35
    #   - Recovery capacity moderate (no crashes, just flatness)          w=0.20
    #   - Coherence capacity low     (system not responding)              w=0.20
    #   - Narrow rmssd range         (ceiling-floor gap is minimal)       w=0.25
    rng = fp.rmssd_range
    qd_signals = {
        "resilience_low":   (br <= 9,                              0.35),
        "recovery_flat":    (rc <= 11,                             0.20),
        "coherence_low":    (cc <= 9,                              0.20),
        "narrow_range":     (rng is not None and rng < 16,         0.25),
    }
    scores["quiet_depleter"] = _weighted_evidence(qd_signals)

    # ── Night Warrior ─────────────────────────────────────────────────────────
    # Chronotype mismatch. Evening is their peak. Mornings are genuinely poor.
    # Sleep recovery efficiency is low because mornings never reach their potential.
    #
    #   - Chrono fit low             (morning alignment is off)            w=0.40
    #   - SRE < 0.90                 (mornings worse than pre-sleep)       w=0.35
    #   - Best window in evening     (peak is 20:00–23:00)                 w=0.25
    bwh = fp.best_window_hour
    nw_signals = {
        "chrono_low":       (cf <= 9,                              0.40),
        "sre_low":          (_safe_lt(fp.sleep_recovery_efficiency, 0.90), 0.35),
        "evening_peak":     (bwh is not None and bwh >= 19,        0.25),
    }
    scores["night_warrior"] = _weighted_evidence(nw_signals)

    # ── Loop Runner ───────────────────────────────────────────────────────────
    # Mind runs overnight. Overnight RMSSD drops instead of rising.
    # LF/HF during sleep is elevated. Distinct from Night Warrior: the hour matters less
    # than the fact that sleep is not safe recovery time.
    #
    #   - Overnight RMSSD delta < 0  (dropping during sleep)              w=0.40
    #   - LF/HF sleep elevated       (sympathetic active overnight)       w=0.35
    #   - Chrono fit low             (sleep is not restoring)             w=0.25
    lr_signals = {
        "ond_negative":     (_safe_lt(fp.overnight_rmssd_delta_avg, 0), 0.40),
        "lf_hf_sleep_high": (_safe_gt(fp.lf_hf_sleep, 1.75),            0.35),
        "chrono_low":       (cf <= 10,                                   0.25),
    }
    scores["loop_runner"] = _weighted_evidence(lr_signals)

    # ── Purist ────────────────────────────────────────────────────────────────
    # Has practice. Coherence capacity moderate+. Doesn't need rescue — needs refinement.
    # The gap is usually one underdeveloped dimension next to a strong one.
    #
    #   - Has prior practice         (they practice something)             w=0.40
    #   - Coherence capacity mod+    (practice is working)                 w=0.35
    #   - Baseline resilience mod+   (not in crisis)                       w=0.25
    pu_signals = {
        "has_practice":     (fp.has_prior_practice,   0.40),
        "coherence_mod":    (cc >= 10,                0.35),
        "resilience_mod":   (br >= 8,                 0.25),
    }
    scores["purist"] = _weighted_evidence(pu_signals)

    # ── Dialled-In ────────────────────────────────────────────────────────────
    # The destination phenotype. All dimensions above their midpoints.
    # Fast arcs. Strong floor. Good chrono alignment. Manageable load.
    #
    #   - Total score >= 68          (overall threshold)                   w=0.40
    #   - Recovery capacity strong   (fast arcs, good sleep efficiency)    w=0.25
    #   - Load management strong     (sympathovagal balance healthy)       w=0.20
    #   - Chrono fit strong          (mornings working)                    w=0.15
    di_signals = {
        "score_high":       ((rc+br+cc+cf+lm) >= 68,  0.40),
        "recovery_strong":  (rc >= 14,                0.25),
        "load_strong":      (lm >= 14,                0.20),
        "chrono_strong":    (cf >= 12,                0.15),
    }
    scores["dialled_in"] = _weighted_evidence(di_signals)

    return scores


def _select_patterns(
    pattern_scores: dict[str, float],
    confidence: float,
) -> tuple[str, Optional[str]]:
    """Return (primary, amplifier). Amplifier is None if score < threshold.

    Special rule: dialled_in is aspirational — it overrides all others when its
    evidence score clears 0.75. A person who is physiologically dialled_in should
    see that label, not a sub-pattern label that happens to also score high.
    """
    if confidence < _MIN_CONFIDENCE_FOR_PATTERN:
        return "UNCLASSIFIED", None

    sorted_patterns = sorted(pattern_scores.items(), key=lambda x: x[1], reverse=True)

    # dialled_in priority override
    if pattern_scores.get("dialled_in", 0.0) >= 0.75:
        primary = "dialled_in"
        amplifier = None
        return primary, amplifier

    primary = sorted_patterns[0][0]

    amplifier = None
    for pattern, score in sorted_patterns[1:]:
        if score >= _AMPLIFIER_THRESHOLD and pattern != primary:
            amplifier = pattern
            break

    return primary, amplifier


# ── Trajectory ─────────────────────────────────────────────────────────────────

def _compute_trajectory(score_7d_delta: Optional[int]) -> str:
    if score_7d_delta is None:
        return "stable"
    if score_7d_delta >= 3:
        return "improving"
    if score_7d_delta <= -3:
        return "declining"
    return "stable"


# ── Stage focus actions ────────────────────────────────────────────────────────

# Two to three concrete actions per (stage, pattern) pair.
# These are shown to the user as the coaching prescription.

_STAGE_FOCUS: dict[tuple[int, str], list[str]] = {

    # ── Stage 0 (foundation missing) ─────────────────────────────────────────
    (0, "over_optimizer"): [
        "Start with one thing only: a 5-minute morning read, every day, before chai or training.",
        "Take one complete rest day this week. Zero training. See what your number does.",
        "Nothing else changes yet — you're building a reference point first.",
    ],
    (0, "trend_chaser"): [
        "One 5-minute morning read, at the same time every day. That's the whole task.",
        "Don't change your habits yet. You need a baseline before you can improve anything.",
        "Notice how your number differs on days you feel good versus not.",
    ],
    (0, "hustler"): [
        "Morning read first — before email, before news. Even 5 minutes gives you data.",
        "Identify your hardest day of the week. That's where the score is leaking most.",
        "Nothing else until you have a consistent morning read habit.",
    ],
    (0, "quiet_depleter"): [
        "One gentle 10-minute breathing session daily — not intense, low effort.",
        "Protect your sleep window. 7–8 hours minimum, consistent time.",
        "Morning read every day. You're learning what your floor actually is.",
    ],
    (0, "night_warrior"): [
        "Morning read immediately after waking — even if the score looks low, the data matters.",
        "Don't fight your evening peak. That's when your breathing sessions should happen.",
        "No changes to schedule yet — just observe your pattern.",
    ],
    (0, "loop_runner"): [
        "Pre-sleep protocol starts tonight — 10 minutes of breathing, no screens.",
        "Before sleep, write down 3 things on your mind. Externalise before lying down.",
        "Morning read every day — your overnight data is the key signal.",
    ],
    (0, "purist"): [
        "Your practice is working in some dimensions. The data will show you which one it's missing.",
        "Add a morning read — your existing practice plus this data is a powerful combination.",
        "Identify the one dimension in your score breakdown that is lowest. That's your gap.",
    ],
    (0, "dialled_in"): [
        "Maintain your current practices — your foundation is solid.",
        "Explore what natural activities (outside formal sessions) elevate your coherence.",
        "Your optimisation window is now open — this is the phase to build on.",
    ],
    (0, "UNCLASSIFIED"): [
        "Not enough data yet to read your pattern. Keep doing the morning reads.",
        "3–5 days of consistent data will let the system understand your baseline.",
        "Nothing to change yet — you're in the observation phase.",
    ],

    # ── Stage 1 (35–54) ───────────────────────────────────────────────────────
    (1, "over_optimizer"): [
        "Protect one complete rest day per week from all training — no substitutes.",
        "Add a 10-minute breathing session after every hard training block.",
        "When morning read is below your personal average two days in a row, reduce training load that day.",
    ],
    (1, "trend_chaser"): [
        "You have a morning read habit now — that's the foundation. Add one guided breathing session per day.",
        "Give one practice 3 weeks without changing it. Watch what the number does.",
        "Don't add anything new until your score moves. Consistency beats variety here.",
    ],
    (1, "hustler"): [
        "Set a hard stop time for work on 3 days per week. Non-negotiable.",
        "10-minute breathing session before sleep — do it before even considering whether you feel like it.",
        "Check your morning read before checking your phone. Make it the first data point of the day.",
    ],
    (1, "quiet_depleter"): [
        "One 10-minute breathing session daily — keep it low effort, make it consistent.",
        "Sleep window is your highest-leverage intervention: protect 7.5 hours every night.",
        "Morning read every day — you're establishing what your floor actually is.",
    ],
    (1, "night_warrior"): [
        "Stop scheduling anything requiring full cognition before 10am where possible.",
        "Evening breathing session, 9–10pm — this is your primary recovery window.",
        "Morning read immediately after waking, even if the score is low. Trend matters more than number.",
    ],
    (1, "loop_runner"): [
        "Pre-sleep breathing protocol is your single highest-leverage intervention right now.",
        "No screens 30 minutes before sleep — replace with the breathing session, not nothing.",
        "Before lying down: write or voice-note what is on your mind. Externalise the loop.",
    ],
    (1, "purist"): [
        "Your practice is your strength — the data confirms it. Now find the dimension it is not reaching.",
        "Add 15 minutes of low-intensity movement (walk, not yoga) on alternate days.",
        "Your load management score is likely your gap — check the breakdown.",
    ],
    (1, "dialled_in"): [
        "You are at the floor of the Dialled-In range — protect what you have built.",
        "One strength or cardio session this week designed around your best natural window.",
        "Morning read consistency is what cements this stage.",
    ],
    (1, "UNCLASSIFIED"): [
        "Keep collecting morning reads — 7 days of data will unlock your pattern.",
        "One breathing session to try — 10 minutes, nasal breath, comfortable pace.",
        "No pressure to change habits yet. Observation first.",
    ],

    # ── Stage 2 (55–69) ───────────────────────────────────────────────────────
    (2, "over_optimizer"): [
        "The recovery gap is closing. Now calibrate training load against morning read — if red, reduce that day.",
        "Add a second breathing session on your hardest training day — pre or post session.",
        "Explore your coherence activity map. What non-training activities elevate you?",
    ],
    (2, "trend_chaser"): [
        "You have a consistent practice now. Add one physical session per week — walk or light cardio.",
        "Try a slightly longer session (15 minutes) and see how your score responds.",
        "You are ready to experiment with timing — morning vs evening sessions.",
    ],
    (2, "hustler"): [
        "Your mid-week degradation is reducing. Protect Thursday — it is still your vulnerable day.",
        "Add a midday 5-minute breathing reset on your heaviest work days.",
        "Consider one lunchtime walk per week. Movement breaks the load accumulation cycle.",
    ],
    (2, "quiet_depleter"): [
        "Your floor is rising. Add one strength session per week — low intensity, 20–30 minutes.",
        "Extend your breathing sessions to 15 minutes — your system is ready for more.",
        "Track which days your score is highest. Start building around those patterns.",
    ],
    (2, "night_warrior"): [
        "Your evening window is your competitive advantage — build your best practice there.",
        "Experiment with a slightly earlier wake time (30 minutes) and see if the morning read improves.",
        "Your schedule alignment is the next unlock — one calendar change per week.",
    ],
    (2, "loop_runner"): [
        "Your overnight recovery is improving. Now extend the pre-sleep protocol to 15 minutes.",
        "Add a midday breathing reset on days with back-to-back meetings.",
        "Watch your overnight RMSSD delta — when it goes positive, you will feel the difference.",
    ],
    (2, "purist"): [
        "Strong coherence + moderate everything else. The gap is physical — add progressive cardio.",
        "Try calibrating your practice to your best time-of-day window — timing amplifies the effect.",
        "You are close to Stage 3. The last gap is usually load management or baseline floor.",
    ],
    (2, "dialled_in"): [
        "Increase session intensity — your recovery can handle more now.",
        "Introduce progressive overload in movement: one harder session per week.",
        "Your coherence elevators are identifiable now — use them deliberately on low-score days.",
    ],
    (2, "UNCLASSIFIED"): [
        "Keep the morning read habit going — your pattern is becoming clearer.",
        "One breathing session per day. Consistency over intensity.",
        "The system is learning you. Trust the process.",
    ],

    # ── Stage 3 (70–79) ───────────────────────────────────────────────────────
    (3, "over_optimizer"): [
        "Recovery is no longer your gap. Now build intelligently: train to your morning read.",
        "Experiment with periodisation — hard weeks followed by lighter weeks.",
        "Your coherence activity map is rich now. Use natural elevators as recovery tools.",
    ],
    (3, "hustler"): [
        "The weekly debt is mostly cleared. Protect the Thursday pattern actively now.",
        "Add a strength session — your nervous system is ready for structured physical load.",
        "Explore which work patterns drive the biggest LF/HF shift. That is your blind spot.",
    ],
    (3, "quiet_depleter"): [
        "Your floor has risen significantly. Now train it upwards — progressive strength 2x/week.",
        "Morning reads should be feeling reliably better now — track the streak.",
        "Your range is widening — this is the system coming alive.",
    ],
    (3, "night_warrior"): [
        "Your chronotype is understood now. Build the full plan around your real peak.",
        "Add strength training at your best window time — this is where adaptation happens fastest.",
        "Morning reads are stabilising — you are no longer fighting your own biology.",
    ],
    (3, "loop_runner"): [
        "Overnight recovery is normalising. Now focus on what feeds the loop: reduce pre-sleep inputs.",
        "Add a midday physical session — movement interrupts rumination cycles.",
        "Explore journaling as a structured loop discharge, not just before sleep.",
    ],
    (3, "dialled_in"): [
        "You are in the optimise phase. Performance gains are now accessible.",
        "Introduce a high-intensity session once per week — your recovery can handle it.",
        "Track which activities produce your highest natural coherence. Build your week around them.",
    ],
    (3, "UNCLASSIFIED"): [
        "At this stage, your pattern should be clear. Check the pattern breakdown.",
        "Maintain current practices — your system is functioning well.",
        "Focus on the lowest dimension in your breakdown — that is the unlock.",
    ],

    # ── Stage 4+ (80–100) — universal ─────────────────────────────────────────
    (4, "dialled_in"): [
        "You are in peak territory. Progressive physical overload is the next frontier.",
        "Explore advanced breathwork — extended exhales, box breathing, or CO2 tolerance work.",
        "Your natural coherence activity map is your most powerful tool now.",
    ],
    (5, "dialled_in"): [
        "90+ is rare. Maintain with curiosity, not rigidity.",
        "Focus on teaching others — explaining the system reinforces your own understanding.",
        "Your data is now a reference point for what full NS health looks like.",
    ],
}

# Fallback for missing (stage, pattern) combos
_DEFAULT_FOCUS = [
    "Maintain your current practices consistently.",
    "Focus on the lowest dimension in your score breakdown.",
    "Morning read every day — it is your most important data point.",
]


def _stage_focus(stage: int, pattern: str) -> list[str]:
    # Try exact match first
    key = (stage, pattern)
    if key in _STAGE_FOCUS:
        return _STAGE_FOCUS[key]
    # Fall back to UNCLASSIFIED for this stage
    key_unc = (stage, "UNCLASSIFIED")
    if key_unc in _STAGE_FOCUS:
        return _STAGE_FOCUS[key_unc]
    # Final fallback
    return _DEFAULT_FOCUS


# ── Helpers ────────────────────────────────────────────────────────────────────

def _weighted_evidence(signals: dict[str, tuple[bool, float]]) -> float:
    """Weighted average of boolean evidence flags. Returns 0.0–1.0."""
    total_weight = sum(w for _, (_, w) in signals.items())
    if total_weight == 0:
        return 0.0
    weighted_sum = sum(w for _, (flag, w) in signals.items() if flag)
    return round(weighted_sum / total_weight, 3)


def _safe_gt(val: Optional[float], threshold: float) -> bool:
    return val is not None and val > threshold


def _safe_lt(val: Optional[float], threshold: float) -> bool:
    return val is not None and val < threshold
