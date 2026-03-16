"""
model/fingerprint_updater.py

Incrementally update a PersonalFingerprint after the baseline window.

After the initial baseline:
  - Every new session adds to the RSA trainability trend.
  - Every morning read updates rmssd_morning_avg (initial calibration only).
  - Every new RMSSD drop adds to the recovery arc stats.
  - Activity coherence tags update the activity map.
  - Check-ins (3-day cadence) update interoception_gap.

Phase 10 change:
  - rmssd_floor, rmssd_ceiling, and rmssd_morning_avg are FROZEN once calibration
    is complete (calibration_locked=True). This prevents silent denominator drift.
  - Capacity is only updated when new range exceeds current by >=10% for 7+ days
    AND coach fires a user notification. That trigger happens outside this module.
  - Pass calibration_locked=True to update_rmssd_stats after calibration_days >= 3.

Design:
  - All updates are additive and non-destructive.
  - The fingerprint carries the config_version it was built under.
  - If CONFIG_VERSION changes, a full rebuild is triggered (not an update).
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from config import CONFIG
from model.baseline_builder import MetricReading, PersonalFingerprint
from model.recovery_arc_detector import detect_arcs, summarise_arcs
from model.activity_coherence_tracker import (
    ActivityCoherenceObservation,
    compute_activity_map,
    CoherenceActivityMap,
)


@dataclass
class UpdateResult:
    """What changed in this update pass."""
    fields_updated:       list[str]
    confidence_before:    float
    confidence_after:     float
    arc_events_added:     int
    activity_obs_added:   int
    updated_at:           datetime


def update_rmssd_stats(
    fp: PersonalFingerprint,
    new_readings: list[MetricReading],
    rolling_days: Optional[int] = None,
    calibration_locked: bool = False,
) -> list[str]:
    """
    Update RMSSD floor/ceiling/morning_avg from new readings.

    Parameters
    ----------
    fp : PersonalFingerprint
        The personal fingerprint to update in-place.
    new_readings : list[MetricReading]
        New readings from the current session or background window.
    rolling_days : int, optional
        Rolling window for distribution stats.
    calibration_locked : bool
        When True (calibration_days >= 3), the ceiling and morning_avg are FROZEN.
        No EWM updates to morning_avg; no ceiling ratchet upward.
        Floor can still lower (expands capacity, doesn't distort denominators).
        Capacity grows only via explicit capacity-increase trigger
        (>10% range growth x 7 days + coach notification).

    Returns list of field names that changed.
    """
    rolling = rolling_days or CONFIG.model.DISTRIBUTION_ROLLING_DAYS
    changed = []

    rmssd = [r for r in new_readings if r.name == "rmssd" and r.confidence >= 0.4]
    if not rmssd:
        return changed

    values = np.array([r.value for r in rmssd], dtype=np.float64)
    new_floor   = float(np.percentile(values, 5))
    new_ceiling = float(np.percentile(values, 95))

    # ── Floor: always allowed to decrease (expands capacity safely)
    if fp.rmssd_floor is None or new_floor < fp.rmssd_floor:
        fp.rmssd_floor = round(new_floor, 1)
        changed.append("rmssd_floor")

    # ── Ceiling: FROZEN after calibration to prevent denominator drift
    if not calibration_locked:
        if fp.rmssd_ceiling is None or new_ceiling > fp.rmssd_ceiling:
            fp.rmssd_ceiling = round(new_ceiling, 1)
            changed.append("rmssd_ceiling")

    if fp.rmssd_floor is not None and fp.rmssd_ceiling is not None:
        new_range = round(fp.rmssd_ceiling - fp.rmssd_floor, 1)
        if fp.rmssd_range != new_range:
            fp.rmssd_range = new_range
            changed.append("rmssd_range")

    # ── Morning average: FROZEN after calibration
    # EWM updates only happen during the initial calibration window (calibration_days < 3).
    # After that, morning_avg is the frozen snapshot used as the scoring threshold.
    if not calibration_locked:
        morning_vals = [
            r.value for r in rmssd
            if r.context == "morning"
        ]
        if morning_vals and fp.rmssd_morning_avg is not None:
            alpha = 0.2   # weight of new observation
            new_morning = float(np.mean(morning_vals))
            fp.rmssd_morning_avg = round(
                alpha * new_morning + (1 - alpha) * fp.rmssd_morning_avg, 1
            )
            changed.append("rmssd_morning_avg")
        elif morning_vals:
            fp.rmssd_morning_avg = round(float(np.mean(morning_vals)), 1)
            changed.append("rmssd_morning_avg")

    return changed


def update_recovery_arc(
    fp: PersonalFingerprint,
    new_readings: list[MetricReading],
) -> tuple[list[str], int]:
    """
    Recompute recovery arc stats from new RMSSD readings.
    Returns (changed_fields, n_new_arcs).
    """
    changed = []
    rmssd_readings = sorted(
        [r for r in new_readings if r.name == "rmssd" and r.confidence >= 0.4],
        key=lambda r: r.ts,
    )
    if len(rmssd_readings) < 8:
        return changed, 0

    values = np.array([r.value for r in rmssd_readings], dtype=np.float64)
    ts_sec = np.array([r.ts.timestamp() for r in rmssd_readings], dtype=np.float64)
    arcs = detect_arcs(values, ts_sec)
    summary = summarise_arcs(arcs)

    if summary.n_events == 0:
        return changed, 0

    if fp.recovery_arc_mean_hours is None:
        fp.recovery_arc_mean_hours = summary.mean_hours
        fp.recovery_arc_fast_hours = summary.fast_hours
        fp.recovery_arc_slow_hours = summary.slow_hours
        fp.recovery_arc_class      = summary.arc_class.value
        changed.extend(["recovery_arc_mean_hours", "recovery_arc_fast_hours",
                         "recovery_arc_slow_hours", "recovery_arc_class"])
    else:
        # EWM blend with existing values
        alpha = 0.25
        if summary.mean_hours is not None:
            fp.recovery_arc_mean_hours = round(
                alpha * summary.mean_hours + (1 - alpha) * fp.recovery_arc_mean_hours, 2
            )
            changed.append("recovery_arc_mean_hours")
        fp.recovery_arc_class = summary.arc_class.value
        changed.append("recovery_arc_class")

    return changed, summary.n_events


def update_coherence_stats(
    fp: PersonalFingerprint,
    new_readings: list[MetricReading],
) -> list[str]:
    """Update coherence floor from new background readings."""
    changed = []
    bg_coh = [
        r for r in new_readings
        if r.name == "coherence" and r.context == "background" and r.confidence >= 0.4
    ]
    if not bg_coh:
        return changed

    new_floor = float(np.percentile([r.value for r in bg_coh], 25))
    if fp.coherence_floor is None:
        fp.coherence_floor = round(new_floor, 4)
        changed.append("coherence_floor")
    else:
        # Slow update — floor should only drift gradually
        alpha = 0.1
        fp.coherence_floor = round(
            alpha * new_floor + (1 - alpha) * fp.coherence_floor, 4
        )
        changed.append("coherence_floor")

    return changed


def update_interoception_gap(
    fp: PersonalFingerprint,
    check_in_scores: list[float],   # subjective scores 1–5 → normalised 0–1
    rmssd_same_day: list[float],    # paired objective RMSSD values
) -> list[str]:
    """
    Update Pearson r between subjective check-in scores and same-day RMSSD.
    Requires at least 3 paired observations.
    """
    changed = []
    if len(check_in_scores) < 3 or len(rmssd_same_day) < 3:
        return changed

    n = min(len(check_in_scores), len(rmssd_same_day))
    r = float(np.corrcoef(check_in_scores[:n], rmssd_same_day[:n])[0, 1])

    if not np.isnan(r):
        if fp.interoception_first_r is None:
            fp.interoception_first_r = round(r, 3)
        else:
            alpha = 0.2
            fp.interoception_first_r = round(
                alpha * r + (1 - alpha) * fp.interoception_first_r, 3
            )
        changed.append("interoception_first_r")

    return changed


def run_update(
    fp: PersonalFingerprint,
    new_readings: list[MetricReading],
    new_activity_obs: Optional[list[ActivityCoherenceObservation]] = None,
    all_activity_obs: Optional[list[ActivityCoherenceObservation]] = None,
    check_in_scores: Optional[list[float]] = None,
    rmssd_same_day: Optional[list[float]] = None,
    calibration_locked: bool = False,
) -> UpdateResult:
    """
    Run all update passes and return a summary of what changed.

    Parameters
    ----------
    fp : PersonalFingerprint
        The fingerprint to update in-place.
    new_readings : list[MetricReading]
        New metric readings since last update.
    new_activity_obs : list | None
        New activity-tagged coherence observations.
    all_activity_obs : list | None
        All historical activity observations (needed to recompute activity map).
    check_in_scores : list | None
        Normalised subjective scores (0–1) from recent check-ins.
    rmssd_same_day : list | None
        Paired objective RMSSD values for same check-in days.
    calibration_locked : bool
        When True, ceiling and morning_avg are frozen (Phase 10).
        Floor may still decrease.  Pass True once calibration_days ≥ BASELINE_STABLE_DAYS.

    Returns
    -------
    UpdateResult
    """
    confidence_before = fp.overall_confidence
    all_changed: list[str] = []
    n_arcs = 0
    n_activity = 0

    # RMSSD stats — respect calibration lock
    all_changed.extend(update_rmssd_stats(fp, new_readings, calibration_locked=calibration_locked))

    # Recovery arc
    arc_fields, n_arcs = update_recovery_arc(fp, new_readings)
    all_changed.extend(arc_fields)

    # Coherence floor
    all_changed.extend(update_coherence_stats(fp, new_readings))

    # Interoception
    if check_in_scores and rmssd_same_day:
        all_changed.extend(
            update_interoception_gap(fp, check_in_scores, rmssd_same_day)
        )

    # Recompute overall confidence
    fp.overall_confidence = _recompute_confidence(fp)
    if fp.overall_confidence != confidence_before:
        all_changed.append("overall_confidence")

    return UpdateResult(
        fields_updated=list(set(all_changed)),
        confidence_before=confidence_before,
        confidence_after=fp.overall_confidence,
        arc_events_added=n_arcs,
        activity_obs_added=n_activity,
        updated_at=datetime.utcnow(),
    )


def _recompute_confidence(fp: PersonalFingerprint) -> float:
    required = [fp.rmssd_floor, fp.rmssd_ceiling, fp.coherence_floor, fp.best_window_hour]
    populated = sum(1 for f in required if f is not None)
    field_score = populated / len(required)
    duration_score = min(1.0, fp.data_hours_available / CONFIG.model.BASELINE_FULL_HOURS)
    return round(field_score * 0.5 + duration_score * 0.5, 3)
