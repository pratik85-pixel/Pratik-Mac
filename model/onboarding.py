"""
model/onboarding.py

Pydantic models for all onboarding answers.

These are collected once during onboarding (screens 4–8 of the UI), stored as
JSON in users.onboarding, and used to:
  1. Seed the initial archetype hypothesis before any sensor data exists.
  2. Flag confounds that should suppress data confidence (caffeine window,
     post-exercise suppression, pre-existing practice baseline adjustment).
  3. Prime the AI coach context (what stresses them, how they decompress,
     cultural defaults like tea drinking).

India-aware: we model tea separately from coffee because the caffeine-
L-theanine combination has a different autonomic profile than coffee alone.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────────────

class ExerciseFrequency(str, Enum):
    DAILY      = "daily"           # 6–7x per week
    OFTEN      = "often"           # 4–5x per week
    REGULAR    = "regular"         # 2–3x per week
    OCCASIONAL = "occasional"      # once a week
    RARELY     = "rarely"          # less than once a week

class WorkoutDuration(str, Enum):
    UNDER_30  = "under_30"
    MINS_30_45 = "30_45"
    MINS_45_60 = "45_60"
    MINS_60_90 = "60_90"
    OVER_90   = "over_90"

class MindfulnessPractice(str, Enum):
    NEVER      = "never"
    TRIED_STOPPED = "tried_stopped"   # tried it but stopped
    OCCASIONAL = "occasional"          # a few times a month
    REGULAR    = "regular"             # daily or near-daily

class CoffeeIntake(str, Enum):
    RARELY    = "rarely"
    ONE       = "one"              # 1 cup/day
    TWO_THREE = "two_three"        # 2–3 cups/day
    FOUR_PLUS = "four_plus"        # 4+ cups/day

class TeaIntake(str, Enum):
    RARELY    = "rarely"
    ONE_TWO   = "one_two"          # 1–2 cups/day (chaai or green)
    THREE_FOUR= "three_four"       # 3–4 cups/day
    FIVE_PLUS = "five_plus"        # 5+ cups/day

class AlcoholFrequency(str, Enum):
    NEVER      = "never"
    OCCASIONAL = "occasional"      # special occasions only
    WEEKENDS   = "weekends"        # weekend-only
    FEW_WEEK   = "few_per_week"    # a few times a week
    DAILY      = "daily"

class ScreenTime(str, Enum):
    UNDER_4  = "under_4"           # < 4 hrs/day
    FOUR_SIX = "4_6"
    SIX_EIGHT= "6_8"
    EIGHT_TEN= "8_10"
    OVER_10  = "over_10"

class ScreenCutoff(str, Enum):
    AT_SLEEP    = "at_sleep"       # right before sleep
    MINS_30     = "30_min"
    HOUR_1      = "1_hour"
    HOURS_2_PLUS= "2_hours_plus"

class TypicalDay(str, Enum):
    DESK_HEAVY  = "desk_heavy"     # mostly seated, computer
    ON_FEET     = "on_feet"        # physically moving all day
    MIXED       = "mixed"          # combination
    IRREGULAR   = "irregular"      # shifts, travel, unpredictable

class MorningFeel(str, Enum):
    SHARP       = "sharp"          # alert immediately
    OKAY        = "okay"           # okay but need a moment
    GROGGY      = "groggy"         # groggy but functional within 30 min
    SLOW        = "slow"           # really slow, need 1+ hr
    VARIES      = "varies"         # wildly inconsistent


# ── Movement preferences (multi-select) ───────────────────────────────────────

class MovementType(str, Enum):
    GYM_WEIGHTS = "gym_weights"
    RUNNING     = "running"
    CYCLING     = "cycling"
    YOGA        = "yoga"
    PILATES     = "pilates"
    SPORTS      = "sports"         # cricket, badminton, football, etc.
    MARTIAL_ARTS= "martial_arts"
    WALKING     = "walking"
    DANCE       = "dance"
    SWIMMING    = "swimming"


# ── Stress drivers (multi-select) ─────────────────────────────────────────────

class StressDriver(str, Enum):
    WORK_DEADLINES  = "work_deadlines"
    PERFORMANCE     = "performance"     # meetings, reviews, presentations
    SOCIAL_PRESSURE = "social_pressure"
    HEALTH_ANXIETY  = "health_anxiety"
    FINANCES        = "finances"
    RELATIONSHIPS   = "relationships"
    FAMILY          = "family"
    UNCERTAINTY     = "uncertainty"     # not knowing what's coming


# ── Decompression style (multi-select) ────────────────────────────────────────

class DecompressStyle(str, Enum):
    EXERCISE         = "exercise"
    ALONE_QUIETLY    = "alone_quietly"
    MUSIC            = "music"
    CREATIVE_WORK    = "creative_work"   # art, writing, cooking, instruments
    SOCIAL           = "social"
    GAMING           = "gaming"
    SCREENS_PASSIVE  = "screens_passive" # TV, reels, YouTube
    NATURE           = "nature"
    JOURNALING       = "journaling"
    PRAYER_SPIRITUAL = "prayer_spiritual"


# ── Main onboarding model ──────────────────────────────────────────────────────

class OnboardingAnswers(BaseModel):
    """
    Complete set of onboarding answers.

    Stored as JSON in users.onboarding.
    All fields are Optional — onboarding is progressive and can be partially
    completed. The archetype seeder handles missing fields gracefully.
    """

    # ── Physical ──────────────────────────────────────────────────────────────
    wake_time:             Optional[str]   = Field(None, description="HH:MM, e.g. '06:30'")
    exercise_frequency:    Optional[ExerciseFrequency]  = None
    movement_types:        list[MovementType]            = Field(default_factory=list)
    workout_duration:      Optional[WorkoutDuration]    = None

    # ── Mind practice ─────────────────────────────────────────────────────────
    mindfulness_practice:  Optional[MindfulnessPractice] = None
    # If they practice: what kind? (free text or multi-select, stored as list)
    practice_types:        list[str]                     = Field(
        default_factory=list,
        description="e.g. ['meditation', 'pranayama', 'yoga_nidra']"
    )

    # ── Stimulants ────────────────────────────────────────────────────────────
    coffee_intake:         Optional[CoffeeIntake]        = None
    coffee_latest_time:    Optional[str]                 = Field(
        None, description="Latest coffee time as HH:MM, e.g. '14:00'"
    )
    tea_intake:            Optional[TeaIntake]           = None
    tea_type:              Optional[str]                 = Field(
        None, description="'chai' | 'green' | 'black' | 'herbal'"
    )
    alcohol_frequency:     Optional[AlcoholFrequency]    = None

    # ── Digital load ──────────────────────────────────────────────────────────
    screen_time:           Optional[ScreenTime]          = None
    screen_cutoff:         Optional[ScreenCutoff]        = None

    # ── Work & lifestyle ──────────────────────────────────────────────────────
    typical_day:           Optional[TypicalDay]          = None

    # ── Stress & recovery ─────────────────────────────────────────────────────
    stress_drivers:        list[StressDriver]            = Field(default_factory=list)
    decompress_style:      list[DecompressStyle]         = Field(default_factory=list)

    # ── Subjective baseline ───────────────────────────────────────────────────
    morning_feel:          Optional[MorningFeel]         = None
    # 1 (terrible) to 5 (great) — used as seed for interoception gap calculation
    sleep_quality_self_report: Optional[int]             = Field(
        None, ge=1, le=5,
        description="Self-reported sleep quality: 1=terrible, 5=great"
    )


# ── Confound profile (derived, not asked) ─────────────────────────────────────

class ConfoundProfile(BaseModel):
    """
    Derived from OnboardingAnswers. Tells the model which readings to
    flag / apply reduced confidence to.
    """

    # Hours of caffeine suppression window after intake
    # Coffee: 4–6 hrs. Tea (chai): 2–3 hrs. Green tea: 2–3 hrs (less caffeine).
    caffeine_suppression_hours: float = 4.0

    # Post-exercise RMSSD suppression window (hrs)
    post_exercise_suppression_hours: float = 0.0

    # Whether to apply elevated coherence floor expectation (they already practise)
    has_prior_practice: bool = False

    # Expected RMSSD bonus from prior practice (ms — applied to ceiling estimate)
    practice_rmssd_bonus_ms: float = 0.0

    @classmethod
    def from_onboarding(cls, ob: OnboardingAnswers) -> "ConfoundProfile":
        # ── Caffeine window ───────────────────────────────────────────────────
        if ob.coffee_intake in (CoffeeIntake.TWO_THREE, CoffeeIntake.FOUR_PLUS):
            caffeine_hours = 6.0
        elif ob.coffee_intake == CoffeeIntake.ONE:
            caffeine_hours = 5.0
        elif ob.tea_intake in (TeaIntake.THREE_FOUR, TeaIntake.FIVE_PLUS):
            caffeine_hours = 3.0   # chai: moderate caffeine + L-theanine buffer
        elif ob.tea_intake == TeaIntake.ONE_TWO:
            caffeine_hours = 2.0
        else:
            caffeine_hours = 0.0

        # ── Post-exercise window ──────────────────────────────────────────────
        if ob.workout_duration in (WorkoutDuration.MINS_60_90, WorkoutDuration.OVER_90):
            exercise_window = 2.0
        elif ob.workout_duration in (WorkoutDuration.MINS_45_60,):
            exercise_window = 1.5
        else:
            exercise_window = 1.0

        # ── Prior practice ────────────────────────────────────────────────────
        has_prior = ob.mindfulness_practice in (
            MindfulnessPractice.REGULAR, MindfulnessPractice.OCCASIONAL
        )
        practice_bonus = (
            8.0  if ob.mindfulness_practice == MindfulnessPractice.REGULAR
            else 3.0 if ob.mindfulness_practice == MindfulnessPractice.OCCASIONAL
            else 0.0
        )

        return cls(
            caffeine_suppression_hours=caffeine_hours,
            post_exercise_suppression_hours=exercise_window,
            has_prior_practice=has_prior,
            practice_rmssd_bonus_ms=practice_bonus,
        )


# ── Archetype seed (derived, not asked) ───────────────────────────────────────

class ArchetypeSeed(BaseModel):
    """
    Initial archetype probability weights derived from onboarding alone.
    These are priors — sensor data will confirm or override them over 48 hours.

    Values are relative weights (0.0–1.0), not probabilities. They are
    normalised by the archetype classifier.
    """
    wire:           float = 0.0
    ruminator:      float = 0.0
    flickerer:      float = 0.0
    shallow_sleeper: float = 0.0
    slow_burner:    float = 0.0
    suppressor:     float = 0.0
    responder:      float = 0.0
    workaholic:     float = 0.0

    @classmethod
    def from_onboarding(cls, ob: OnboardingAnswers) -> "ArchetypeSeed":
        weights = {
            "wire": 0.0, "ruminator": 0.0, "flickerer": 0.0,
            "shallow_sleeper": 0.0, "slow_burner": 0.0,
            "suppressor": 0.0, "responder": 0.0, "workaholic": 0.0,
        }

        # Stress drivers → Wire / Workaholic / Ruminator
        if StressDriver.WORK_DEADLINES in ob.stress_drivers:
            weights["workaholic"] += 0.3
            weights["wire"]       += 0.2
        if StressDriver.PERFORMANCE in ob.stress_drivers:
            weights["workaholic"] += 0.2
        if StressDriver.HEALTH_ANXIETY in ob.stress_drivers:
            weights["ruminator"]  += 0.4
        if StressDriver.UNCERTAINTY in ob.stress_drivers:
            weights["ruminator"]  += 0.3
            weights["flickerer"]  += 0.2
        if StressDriver.RELATIONSHIPS in ob.stress_drivers:
            weights["suppressor"] += 0.2
        if StressDriver.FAMILY in ob.stress_drivers:
            weights["suppressor"] += 0.2

        # Morning feel → Shallow Sleeper / Slow Burner
        if ob.morning_feel == MorningFeel.SLOW:
            weights["shallow_sleeper"] += 0.4
            weights["slow_burner"]     += 0.3
        elif ob.morning_feel == MorningFeel.GROGGY:
            weights["shallow_sleeper"] += 0.2
            weights["slow_burner"]     += 0.2
        elif ob.morning_feel == MorningFeel.SHARP:
            weights["responder"]       += 0.2

        # Sleep quality self-report → Shallow Sleeper
        if ob.sleep_quality_self_report is not None:
            if ob.sleep_quality_self_report <= 2:
                weights["shallow_sleeper"] += 0.4
            elif ob.sleep_quality_self_report >= 4:
                weights["responder"]       += 0.1

        # Exercise frequency → Responder / Slow Burner
        if ob.exercise_frequency in (ExerciseFrequency.DAILY, ExerciseFrequency.OFTEN):
            weights["responder"]   += 0.3
        elif ob.exercise_frequency == ExerciseFrequency.RARELY:
            weights["slow_burner"] += 0.2
            weights["wire"]        += 0.1

        # Prior mindfulness → Responder
        if ob.mindfulness_practice == MindfulnessPractice.REGULAR:
            weights["responder"]   += 0.4
        elif ob.mindfulness_practice == MindfulnessPractice.OCCASIONAL:
            weights["responder"]   += 0.15

        # High screen time + late cutoff → Shallow Sleeper / Wire
        if ob.screen_time in (ScreenTime.EIGHT_TEN, ScreenTime.OVER_10):
            weights["wire"]            += 0.15
        if ob.screen_cutoff == ScreenCutoff.AT_SLEEP:
            weights["shallow_sleeper"] += 0.2

        # Decompression style — alone quietly / creative → Ruminator / Suppressor
        if DecompressStyle.ALONE_QUIETLY in ob.decompress_style:
            weights["suppressor"] += 0.1
        if DecompressStyle.JOURNALING in ob.decompress_style:
            weights["ruminator"]  += 0.1

        return cls(**weights)
