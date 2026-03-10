"""
model/activity_coherence_tracker.py

Build a personal map of which activities naturally elevate or drain coherence.

Core insight:
    Coherence is not only produced during guided breathing sessions. It
    fluctuates continuously with what the user is doing. Certain activities
    (painting, cooking, walking, deep solo work) reliably produce coherent
    nervous system states. Others (long video calls, passive scrolling) reliably
    collapse it.

    This module identifies those patterns from continuous background coherence
    capture + user activity tags.

How activity tags are collected:
    1. Passive: when coherence spike is detected (>15% above personal baseline
       sustained for 10+ minutes), a single question is pushed to the user:
       "Your nervous system was unusually settled just now. What were you doing?"
    2. Active: end-of-day prompt (configurable) — "What did you do between 3–4pm?"
    3. From Health Connect: exercise sessions are auto-tagged.
    4. From conversation extraction: coach conversation may surface tags implicitly.

Data model:
    ActivityCoherenceObservation — one tagged coherence reading
    ActivityProfile              — aggregated stats per activity
    CoherenceActivityMap         — the full personal map (elevators + drains)
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ── Canonical activity tags ────────────────────────────────────────────────────
# These are the choices shown in the "what were you doing?" prompt.
# Free text is mapped to these by the conversation extractor.

ACTIVITY_TAGS = {
    # Natural elevators (typically)
    "cooking":           "Cooking or baking",
    "walking":           "Walking (outdoors or indoors)",
    "running":           "Running",
    "yoga":              "Yoga or stretching",
    "creative_work":     "Creative work (art, writing, music, design)",
    "music_listening":   "Listening to music",
    "music_playing":     "Playing an instrument",
    "reading":           "Reading (not on screen)",
    "nature":            "Being outdoors / in nature",
    "exercise":          "Exercise / gym workout",
    "meditation":        "Meditation or breathwork",
    "prayer":            "Prayer or spiritual practice",
    "social_quality":    "Conversation with someone you enjoy",
    "journaling":        "Journaling or writing",

    # Natural drains (typically)
    "video_calls":       "Video calls / online meetings",
    "commuting":         "Commuting (driving or transit)",
    "social_media":      "Social media / reels / scrolling",
    "email":             "Email or messages",
    "passive_screens":   "Watching TV / YouTube / OTT",
    "gaming":            "Gaming",
    "desk_work":         "Focused desk work / coding / writing docs",
    "stressful_convo":   "Stressful conversation or conflict",
    "news":              "Reading news / current events",

    # Ambiguous — direction depends on the person
    "eating":            "Eating a meal",
    "social_large":      "Social gathering / party",
    "shopping":          "Shopping (in person or online)",
    "childcare":         "Caring for children or elders",
    "rest_idle":         "Resting / doing nothing",
}


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class ActivityCoherenceObservation:
    """
    One coherence reading tagged with an activity.

    Multiple readings can belong to the same activity window —
    e.g. 6 × 10-second windows during a 1-minute walk.
    """
    ts:               datetime
    activity_tag:     str           # must be a key in ACTIVITY_TAGS
    coherence:        float         # 0.0–1.0
    duration_minutes: float         # how long the activity lasted (estimated)
    confidence:       float         # coherence measurement confidence 0.0–1.0
    source:           str           # "passive_spike" | "eod_prompt" | "health_connect" | "conversation"
    notes:            Optional[str] = None


@dataclass
class ActivityProfile:
    """
    Aggregated coherence statistics for one activity.
    Built from n ≥ 3 observations (configurable MIN_OBS).
    """
    activity_tag:   str
    activity_label: str             # human-readable from ACTIVITY_TAGS
    coherence_avg:  float
    coherence_std:  float
    coherence_min:  float
    coherence_max:  float
    n_obs:          int
    confidence:     float           # grows with n_obs; saturates at 1.0 at n=20
    direction:      str             # "elevator" | "drain" | "neutral"


@dataclass
class CoherenceActivityMap:
    """
    The full personal activity × coherence map for one user.
    Stored in PersonalModel.fingerprint_json["activity_map"].
    """
    elevators:     list[ActivityProfile]   # sorted by coherence_avg desc
    drains:        list[ActivityProfile]   # sorted by coherence_avg asc
    neutral:       list[ActivityProfile]   # within ±NEUTRAL_BAND of grand mean
    grand_mean:    float                   # personal baseline coherence
    n_total_obs:   int
    last_updated:  datetime

    @property
    def top_elevator(self) -> Optional[ActivityProfile]:
        return self.elevators[0] if self.elevators else None

    @property
    def top_drain(self) -> Optional[ActivityProfile]:
        return self.drains[0] if self.drains else None

    def to_dict(self) -> dict:
        return {
            "elevators":   [_profile_to_dict(p) for p in self.elevators],
            "drains":      [_profile_to_dict(p) for p in self.drains],
            "neutral":     [_profile_to_dict(p) for p in self.neutral],
            "grand_mean":  round(self.grand_mean, 4),
            "n_total_obs": self.n_total_obs,
            "last_updated": self.last_updated.isoformat(),
        }


# ── Constants ──────────────────────────────────────────────────────────────────
_MIN_OBS = 3           # minimum observations to include an activity in the map
_NEUTRAL_BAND = 0.05   # ±0.05 of grand mean → neutral (not elevator or drain)
_CONFIDENCE_SATURATION = 20  # n_obs at which confidence reaches 1.0


# ── Core computation ───────────────────────────────────────────────────────────

def compute_activity_map(
    observations: list[ActivityCoherenceObservation],
    reference_coherence: Optional[float] = None,
) -> CoherenceActivityMap:
    """
    Build a CoherenceActivityMap from a list of tagged observations.

    Parameters
    ----------
    observations : list[ActivityCoherenceObservation]
        All tagged coherence readings for a user.
    reference_coherence : float | None
        Personal baseline coherence (e.g. from PersonalModel.coherence_floor).
        If None, uses the grand mean of all observations.

    Returns
    -------
    CoherenceActivityMap
    """
    if not observations:
        return CoherenceActivityMap(
            elevators=[], drains=[], neutral=[],
            grand_mean=0.0, n_total_obs=0,
            last_updated=datetime.utcnow(),
        )

    # Filter to minimum confidence threshold
    valid = [o for o in observations if o.confidence >= 0.4]
    if not valid:
        return CoherenceActivityMap(
            elevators=[], drains=[], neutral=[],
            grand_mean=0.0, n_total_obs=0,
            last_updated=datetime.utcnow(),
        )

    # Grand mean (weighted by confidence)
    weights = np.array([o.confidence for o in valid])
    coherences = np.array([o.coherence for o in valid])
    grand_mean = float(np.average(coherences, weights=weights))
    if reference_coherence is not None:
        grand_mean = reference_coherence

    # Group by activity
    from collections import defaultdict
    by_activity: dict[str, list[ActivityCoherenceObservation]] = defaultdict(list)
    for obs in valid:
        by_activity[obs.activity_tag].append(obs)

    profiles: list[ActivityProfile] = []
    for tag, obs_list in by_activity.items():
        if len(obs_list) < _MIN_OBS:
            continue
        profile = _build_profile(tag, obs_list, grand_mean)
        profiles.append(profile)

    elevators = sorted(
        [p for p in profiles if p.direction == "elevator"],
        key=lambda p: p.coherence_avg, reverse=True
    )
    drains = sorted(
        [p for p in profiles if p.direction == "drain"],
        key=lambda p: p.coherence_avg
    )
    neutral = [p for p in profiles if p.direction == "neutral"]

    return CoherenceActivityMap(
        elevators=elevators,
        drains=drains,
        neutral=neutral,
        grand_mean=round(grand_mean, 4),
        n_total_obs=len(valid),
        last_updated=datetime.utcnow(),
    )


def update_activity_map(
    existing_map: CoherenceActivityMap,
    new_observations: list[ActivityCoherenceObservation],
    all_observations: list[ActivityCoherenceObservation],
) -> CoherenceActivityMap:
    """
    Recompute the activity map from all observations (existing + new).
    """
    return compute_activity_map(
        all_observations,
        reference_coherence=existing_map.grand_mean,
    )


def detect_coherence_spike(
    coherence_values: np.ndarray,
    timestamps: np.ndarray,
    personal_baseline: float,
    spike_threshold: float = 0.15,
    min_duration_windows: int = 6,     # 6 × 10-sec = 60 seconds sustained
) -> list[tuple[float, float]]:
    """
    Detect windows of elevated coherence that should trigger an activity prompt.

    Parameters
    ----------
    coherence_values : np.ndarray
        Continuous coherence values (e.g. 10-sec windows).
    timestamps : np.ndarray
        Corresponding timestamps (Unix seconds).
    personal_baseline : float
        User's personal resting coherence.
    spike_threshold : float
        Fractional rise above baseline to count as spike (default 0.15 = 15%).
    min_duration_windows : int
        Minimum consecutive above-threshold windows to trigger prompt.

    Returns
    -------
    list of (start_ts, end_ts) for detected spikes.
    """
    threshold = personal_baseline * (1.0 + spike_threshold)
    above = coherence_values >= threshold

    spikes = []
    run_start = None
    run_count = 0

    for i, is_above in enumerate(above):
        if is_above:
            if run_start is None:
                run_start = i
            run_count += 1
        else:
            if run_count >= min_duration_windows and run_start is not None:
                spikes.append((float(timestamps[run_start]), float(timestamps[i - 1])))
            run_start = None
            run_count = 0

    # Handle run ending at array end
    if run_count >= min_duration_windows and run_start is not None:
        spikes.append((float(timestamps[run_start]), float(timestamps[-1])))

    return spikes


# ── Internal helpers ───────────────────────────────────────────────────────────

def _build_profile(
    tag: str,
    observations: list[ActivityCoherenceObservation],
    grand_mean: float,
) -> ActivityProfile:
    values = np.array([o.coherence for o in observations])
    avg = float(np.mean(values))
    std = float(np.std(values))
    conf = min(1.0, len(observations) / _CONFIDENCE_SATURATION)

    if avg >= grand_mean + _NEUTRAL_BAND:
        direction = "elevator"
    elif avg <= grand_mean - _NEUTRAL_BAND:
        direction = "drain"
    else:
        direction = "neutral"

    return ActivityProfile(
        activity_tag=tag,
        activity_label=ACTIVITY_TAGS.get(tag, tag),
        coherence_avg=round(avg, 4),
        coherence_std=round(std, 4),
        coherence_min=round(float(values.min()), 4),
        coherence_max=round(float(values.max()), 4),
        n_obs=len(observations),
        confidence=round(conf, 3),
        direction=direction,
    )


def _profile_to_dict(p: ActivityProfile) -> dict:
    return {
        "activity_tag":   p.activity_tag,
        "activity_label": p.activity_label,
        "coherence_avg":  p.coherence_avg,
        "coherence_std":  p.coherence_std,
        "n_obs":          p.n_obs,
        "confidence":     p.confidence,
        "direction":      p.direction,
    }
