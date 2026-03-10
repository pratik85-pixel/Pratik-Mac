"""
model/baseline_builder.py

Build the first personal fingerprint from 48 hours of sensor data
+ onboarding answers.

Called once:
    - Triggered at CONFIG.model.BASELINE_FIRST_SNAPSHOT_HOURS (6hrs) for an
      early first look.
    - Re-run at CONFIG.model.BASELINE_FULL_HOURS (48hrs) for the full baseline.

Input:
    - List of MetricReading (time-stamped metric values from the processing pipeline)
    - OnboardingAnswers
    - ConfoundProfile (derived from onboarding)

Output:
    - PersonalFingerprint dataclass — pure Python, no ORM dependency.
      The API layer maps this to the PersonalModel ORM row.

Design:
    - Every computation is annotated with the config value it depends on, so
      if a config threshold changes the system knows which fields to recompute.
    - Confidence scores are propagated — if only 8hrs of data exist, the
      fingerprint is valid but most fields have confidence < 0.6.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from config import CONFIG
from model.onboarding import OnboardingAnswers, ConfoundProfile
from model.recovery_arc_detector import detect_arcs, summarise_arcs, ArcClass


# ── Input type (decoupled from ORM) ───────────────────────────────────────────

@dataclass
class MetricReading:
    """
    One metric value as produced by the processing pipeline.
    Mirrors the Metric ORM row but is a plain dataclass for testability.
    """
    name:       str          # "rmssd" | "coherence" | "rsa_power" | "lf_hf" | "hr"
    value:      float
    confidence: float        # 0.0–1.0
    context:    str          # "session" | "background" | "sleep" | "morning_read"
    ts:         datetime


# ── Output type ───────────────────────────────────────────────────────────────

@dataclass
class PersonalFingerprint:
    """
    The complete personal model assembled from 48hr data + onboarding.

    Field-level confidence: each Optional[float] is None when insufficient
    data exists. Callers should check before trusting.
    """

    # ── RMSSD range (personal tank) ───────────────────────────────────────────
    rmssd_floor:          Optional[float] = None   # ms — personal depleted state
    rmssd_ceiling:        Optional[float] = None   # ms — personal peak
    rmssd_range:          Optional[float] = None   # ceiling − floor
    rmssd_morning_avg:    Optional[float] = None   # avg of morning reads
    rmssd_overnight_rise: Optional[float] = None   # morning − evening ratio

    # ── Recovery arc ──────────────────────────────────────────────────────────
    recovery_arc_mean_hours:  Optional[float] = None
    recovery_arc_fast_hours:  Optional[float] = None
    recovery_arc_slow_hours:  Optional[float] = None
    recovery_arc_class:       Optional[str]   = None

    # ── RSA ───────────────────────────────────────────────────────────────────
    rsa_resting_avg:      Optional[float] = None   # RSA power at rest
    rsa_guided_avg:       Optional[float] = None   # RSA power during guided sessions
    rsa_trainability_delta: Optional[float] = None  # guided − resting
    rsa_trainability:     Optional[str]   = None   # "low"|"moderate"|"high"

    # ── Coherence ─────────────────────────────────────────────────────────────
    coherence_floor:      Optional[float] = None   # resting coherence
    coherence_trainability: Optional[str] = None   # "low"|"moderate"|"high"
    coherence_session1_start: Optional[float] = None
    coherence_session1_peak:  Optional[float] = None

    # ── Temporal patterns ─────────────────────────────────────────────────────
    best_window_hour:     Optional[int]   = None   # 0–23 — hour of day with highest RMSSD
    worst_window_hour:    Optional[int]   = None   # 0–23 — hour of day with lowest RMSSD
    stress_peak_hour:     Optional[int]   = None   # when RMSSD drops are most frequent
    best_natural_window_start: Optional[str] = None  # "HH:MM"

    # ── Sleep proxy ───────────────────────────────────────────────────────────
    sleep_recovery_efficiency: Optional[float] = None  # morning/evening RMSSD ratio
    overnight_rmssd_delta_avg: Optional[float] = None  # morning − pre-sleep avg

    # ── LF/HF sympathovagal balance ───────────────────────────────────────────
    lf_hf_resting:        Optional[float] = None
    lf_hf_sleep:          Optional[float] = None

    # ── Interoception ─────────────────────────────────────────────────────────
    # First data point — Pearson r between subjective morning feel and RMSSD
    interoception_first_r:    Optional[float] = None

    # ── Archetype seed (from onboarding alone) ────────────────────────────────
    archetype_weights:    dict = field(default_factory=dict)

    # ── Confounds ─────────────────────────────────────────────────────────────
    caffeine_suppression_hours: float = 0.0
    has_prior_practice:         bool  = False

    # ── Metadata ──────────────────────────────────────────────────────────────
    data_hours_available:  float = 0.0   # how much data was processed
    overall_confidence:    float = 0.0   # 0.0–1.0 — governs how much to trust this snapshot
    config_version:        int   = 1
    built_at:              datetime = field(default_factory=datetime.utcnow)

    def is_ready(self) -> bool:
        """True if enough data to trust the primary metrics."""
        return (
            self.overall_confidence >= 0.5
            and self.rmssd_floor is not None
            and self.rmssd_ceiling is not None
        )


# ── Builder ───────────────────────────────────────────────────────────────────

class BaselineBuilder:
    """
    Assembles a PersonalFingerprint from raw metric readings + onboarding.

    Usage:
        builder = BaselineBuilder(readings, onboarding)
        fingerprint = builder.build()
    """

    # Confidence threshold — readings below this are skipped
    _MIN_READING_CONFIDENCE = 0.4

    # Morning window: 04:00–10:00 local (readings in this hour range = morning)
    _MORNING_HOUR_START = 4
    _MORNING_HOUR_END   = 10

    # Evening window for sleep proxy: 21:00–01:00
    _EVENING_HOUR_START = 21

    def __init__(
        self,
        readings: list[MetricReading],
        onboarding: Optional[OnboardingAnswers] = None,
    ) -> None:
        self.readings = [r for r in readings if r.confidence >= self._MIN_READING_CONFIDENCE]
        self.onboarding = onboarding
        self.confounds = (
            ConfoundProfile.from_onboarding(onboarding)
            if onboarding else ConfoundProfile()
        )

        # Sort by timestamp once — all methods use this order
        self.readings.sort(key=lambda r: r.ts)

    def build(self) -> PersonalFingerprint:
        fp = PersonalFingerprint(
            caffeine_suppression_hours=self.confounds.caffeine_suppression_hours,
            has_prior_practice=self.confounds.has_prior_practice,
            config_version=CONFIG.version,
        )

        if not self.readings:
            return fp

        # ── Data availability ─────────────────────────────────────────────────
        ts_range = (self.readings[-1].ts - self.readings[0].ts).total_seconds() / 3600.0
        fp.data_hours_available = round(ts_range, 1)

        # ── RMSSD metrics ─────────────────────────────────────────────────────
        self._build_rmssd(fp)

        # ── RSA metrics ───────────────────────────────────────────────────────
        self._build_rsa(fp)

        # ── Coherence metrics ─────────────────────────────────────────────────
        self._build_coherence(fp)

        # ── Temporal patterns ─────────────────────────────────────────────────
        self._build_temporal(fp)

        # ── Sleep proxy ───────────────────────────────────────────────────────
        self._build_sleep_proxy(fp)

        # ── LF/HF ─────────────────────────────────────────────────────────────
        self._build_lf_hf(fp)

        # ── Recovery arc ──────────────────────────────────────────────────────
        self._build_recovery_arc(fp)

        # ── Onboarding-derived fields ─────────────────────────────────────────
        if self.onboarding:
            from model.onboarding import ArchetypeSeed
            seed = ArchetypeSeed.from_onboarding(self.onboarding)
            fp.archetype_weights = seed.model_dump()

        # ── Overall confidence ────────────────────────────────────────────────
        fp.overall_confidence = self._compute_overall_confidence(fp)

        return fp

    # ── Private builders ──────────────────────────────────────────────────────

    def _rmssd(self, context: Optional[str] = None) -> np.ndarray:
        readings = [r for r in self.readings if r.name == "rmssd"]
        if context:
            readings = [r for r in readings if r.context == context]
        return np.array([r.value for r in readings], dtype=np.float64)

    def _build_rmssd(self, fp: PersonalFingerprint) -> None:
        all_rmssd = self._rmssd()
        if len(all_rmssd) < 5:
            return

        # Floor / ceiling: use 5th and 95th percentile (robust to outliers)
        fp.rmssd_floor   = round(float(np.percentile(all_rmssd, 5)),  1)
        fp.rmssd_ceiling = round(float(np.percentile(all_rmssd, 95)), 1)
        fp.rmssd_range   = round(fp.rmssd_ceiling - fp.rmssd_floor, 1)

        # Morning average
        morning_readings = [
            r for r in self.readings
            if r.name == "rmssd"
            and self._MORNING_HOUR_START <= r.ts.hour < self._MORNING_HOUR_END
        ]
        if morning_readings:
            fp.rmssd_morning_avg = round(
                float(np.mean([r.value for r in morning_readings])), 1
            )

    def _build_rsa(self, fp: PersonalFingerprint) -> None:
        # Resting RSA: background context, not during sessions
        resting = [r for r in self.readings if r.name == "rsa_power" and r.context == "background"]
        session = [r for r in self.readings if r.name == "rsa_power" and r.context == "session"]

        if resting:
            fp.rsa_resting_avg = round(float(np.mean([r.value for r in resting])), 6)

        if session:
            fp.rsa_guided_avg = round(float(np.mean([r.value for r in session])), 6)

        if fp.rsa_resting_avg is not None and fp.rsa_guided_avg is not None:
            delta = fp.rsa_guided_avg - fp.rsa_resting_avg
            fp.rsa_trainability_delta = round(delta, 6)
            # Classify trainability relative to resting
            if fp.rsa_resting_avg > 0:
                pct_rise = delta / fp.rsa_resting_avg
                fp.rsa_trainability = (
                    "high"     if pct_rise >= 0.50 else
                    "moderate" if pct_rise >= 0.20 else
                    "low"
                )
            # Adjust for prior practice — trained practitioners start with higher floor
            if self.confounds.has_prior_practice:
                # Their trainability floor is already elevated; don't penalise them
                if fp.rsa_trainability == "low":
                    fp.rsa_trainability = "moderate"

    def _build_coherence(self, fp: PersonalFingerprint) -> None:
        resting_coh = [
            r for r in self.readings
            if r.name == "coherence" and r.context == "background"
        ]
        if resting_coh:
            fp.coherence_floor = round(
                float(np.percentile([r.value for r in resting_coh], 25)), 4
            )

        # Session 1 coherence (start and peak)
        session_coh = sorted(
            [r for r in self.readings if r.name == "coherence" and r.context == "session"],
            key=lambda r: r.ts,
        )
        if session_coh:
            fp.coherence_session1_start = round(float(session_coh[0].value), 4)
            fp.coherence_session1_peak  = round(
                float(max(r.value for r in session_coh)), 4
            )

            if fp.coherence_floor is not None and fp.coherence_session1_peak is not None:
                delta_coh = fp.coherence_session1_peak - fp.coherence_floor
                fp.coherence_trainability = (
                    "high"     if delta_coh >= 0.25 else
                    "moderate" if delta_coh >= 0.10 else
                    "low"
                )

    def _build_temporal(self, fp: PersonalFingerprint) -> None:
        rmssd_readings = [r for r in self.readings if r.name == "rmssd"]
        if not rmssd_readings:
            return

        # Bucket by hour of day
        by_hour: dict[int, list[float]] = {}
        for r in rmssd_readings:
            h = r.ts.hour
            by_hour.setdefault(h, []).append(r.value)

        if len(by_hour) < 3:
            return

        hour_avgs = {h: float(np.mean(vals)) for h, vals in by_hour.items()}

        best_hour  = max(hour_avgs, key=lambda h: hour_avgs[h])
        worst_hour = min(hour_avgs, key=lambda h: hour_avgs[h])

        fp.best_window_hour  = best_hour
        fp.worst_window_hour = worst_hour
        fp.best_natural_window_start = f"{best_hour:02d}:00"

    def _build_sleep_proxy(self, fp: PersonalFingerprint) -> None:
        """
        Sleep recovery efficiency = avg morning RMSSD / avg evening RMSSD.
        > 1.0 = sleep recovered you. < 1.0 = you woke up more depleted.
        """
        morning_vals = [
            r.value for r in self.readings
            if r.name == "rmssd"
            and self._MORNING_HOUR_START <= r.ts.hour < self._MORNING_HOUR_END
        ]
        evening_vals = [
            r.value for r in self.readings
            if r.name == "rmssd"
            and r.ts.hour >= self._EVENING_HOUR_START
        ]

        if morning_vals and evening_vals:
            morning_avg = float(np.mean(morning_vals))
            evening_avg = float(np.mean(evening_vals))
            if evening_avg > 0:
                fp.sleep_recovery_efficiency = round(morning_avg / evening_avg, 3)
                fp.overnight_rmssd_delta_avg  = round(morning_avg - evening_avg, 1)

    def _build_lf_hf(self, fp: PersonalFingerprint) -> None:
        resting_lf_hf = [
            r for r in self.readings
            if r.name == "lf_hf" and r.context == "background"
        ]
        sleep_lf_hf = [
            r for r in self.readings
            if r.name == "lf_hf" and r.context == "sleep"
        ]
        if resting_lf_hf:
            fp.lf_hf_resting = round(float(np.median([r.value for r in resting_lf_hf])), 3)
        if sleep_lf_hf:
            fp.lf_hf_sleep = round(float(np.median([r.value for r in sleep_lf_hf])), 3)

    def _build_recovery_arc(self, fp: PersonalFingerprint) -> None:
        rmssd_readings = sorted(
            [r for r in self.readings if r.name == "rmssd"],
            key=lambda r: r.ts,
        )
        if len(rmssd_readings) < 8:
            return

        values = np.array([r.value for r in rmssd_readings], dtype=np.float64)
        ts_sec = np.array([r.ts.timestamp() for r in rmssd_readings], dtype=np.float64)

        arcs = detect_arcs(values, ts_sec)
        summary = summarise_arcs(arcs)

        fp.recovery_arc_mean_hours = summary.mean_hours
        fp.recovery_arc_fast_hours = summary.fast_hours
        fp.recovery_arc_slow_hours = summary.slow_hours
        fp.recovery_arc_class      = summary.arc_class.value if summary.arc_class else None

    def _compute_overall_confidence(self, fp: PersonalFingerprint) -> float:
        """
        Composite confidence based on how many key fields are populated
        and how many hours of data exist.
        """
        required_fields = [
            fp.rmssd_floor, fp.rmssd_ceiling,
            fp.coherence_floor,
            fp.best_window_hour,
        ]
        populated = sum(1 for f in required_fields if f is not None)
        field_score = populated / len(required_fields)

        # Scale with data hours (saturates at 48hrs)
        duration_score = min(1.0, fp.data_hours_available / CONFIG.model.BASELINE_FULL_HOURS)

        return round(field_score * 0.5 + duration_score * 0.5, 3)
