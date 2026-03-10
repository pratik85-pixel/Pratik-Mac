"""
tagging/tag_pattern_model.py

User-level tag pattern model.

Builds and updates per-(user, tag) pattern summaries that the auto-tagger
uses to classify unconfirmed stress/recovery windows.

The model is a lightweight in-memory representation built from the confirmed
events stored in the DB (StressWindow.tag / RecoveryWindow.tag).
Persisting the model back to DB is handled by api/services/tagging_service.py
writing to the TagPatternModel table.

Key responsibilities
--------------------
- Maintain per-tag confirmed_count, hour_histogram, weekday_counts
- Determine auto_tag_eligible (confirmed_count >= AUTOTAG_MIN_CONFIRMED)
- Track sport_stressor_slugs — sports activities that consistently drive high
  stress_contribution_pct (>= SPORT_STRESS_THRESHOLD) + slow next-day recovery
- Expose a serialisable dict for DB storage
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from tagging.auto_tagger import (
    AUTOTAG_MIN_CONFIRMED,
    TagEvent,
    TagPattern,
    build_patterns,
)


# ── Constants ─────────────────────────────────────────────────────────────────

SPORT_STRESS_THRESHOLD:         float = 0.60   # stress_contribution_pct to flag a sport
SPORT_SLOW_RECOVERY_THRESHOLD:  float = 1.20   # next-day recovery arc ≥ 120% of personal avg
SPORT_MIN_EVENTS:               int   = 3      # minimum sport events before flagging


# ── UserTagPatternModel ───────────────────────────────────────────────────────

@dataclass
class UserTagPatternModel:
    """
    In-memory representation of a user's tag pattern model.

    Attributes
    ----------
    user_id : str
    patterns : dict[str, TagPattern]
        Keyed by tag slug.  Only patterns with confirmed_count >=
        AUTOTAG_MIN_CONFIRMED are kept.
    sport_stressor_slugs : list[str]
        Sports that consistently produce high stress_contribution_pct + slow
        next-day recovery.  Used by prescriber and CoachContext.
    auto_tag_eligible_slugs : frozenset[str]
        Tags where auto-tagging is permitted (enough confirmed events).
    """
    user_id:                  str
    patterns:                 dict[str, TagPattern] = field(default_factory=dict)
    sport_stressor_slugs:     list[str]             = field(default_factory=list)
    auto_tag_eligible_slugs:  frozenset[str]        = field(default_factory=frozenset)

    def to_dict(self) -> dict:
        """Serialise to JSON-safe dict for DB (TagPatternModel.model_json column)."""
        return {
            "user_id": self.user_id,
            "patterns": {
                tag: {
                    "tag":             p.tag,
                    "window_type":     p.window_type,
                    "confirmed_count": p.confirmed_count,
                    "hour_histogram":  {str(k): v for k, v in p.hour_histogram.items()},
                    "weekday_counts":  {str(k): v for k, v in p.weekday_counts.items()},
                    "avg_suppression": p.avg_suppression,
                }
                for tag, p in self.patterns.items()
            },
            "sport_stressor_slugs": self.sport_stressor_slugs,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UserTagPatternModel":
        """Deserialise from a DB-stored JSON dict (inverse of to_dict)."""
        raw_patterns: dict = data.get("patterns", {})
        patterns: dict[str, TagPattern] = {}
        for tag, pd in raw_patterns.items():
            patterns[tag] = TagPattern(
                tag=pd["tag"],
                window_type=pd["window_type"],
                confirmed_count=pd["confirmed_count"],
                hour_histogram={int(k): v for k, v in pd.get("hour_histogram", {}).items()},
                weekday_counts={int(k): v for k, v in pd.get("weekday_counts", {}).items()},
                avg_suppression=pd.get("avg_suppression"),
            )
        sport_stressors: list[str] = data.get("sport_stressor_slugs", [])
        eligible = frozenset(
            tag for tag, p in patterns.items()
            if p.confirmed_count >= AUTOTAG_MIN_CONFIRMED
        )
        return cls(
            user_id=data.get("user_id", ""),
            patterns=patterns,
            sport_stressor_slugs=sport_stressors,
            auto_tag_eligible_slugs=eligible,
        )


# ── SportEvent input type ─────────────────────────────────────────────────────

@dataclass
class SportEvent:
    """
    Single sport activity event for sport stressor analysis.

    sport_slug         — activity slug (e.g. "sports", "running")
    stress_contrib_pct — stress_contribution_pct from linked StressWindow (0–100)
    recovery_arc_hours — next-morning recovery arc duration in hours (None if unknown)
    personal_arc_avg   — user's personal_model recovery_arc_mean_hours
    """
    sport_slug:          str
    stress_contrib_pct:  float
    recovery_arc_hours:  Optional[float] = None
    personal_arc_avg:    Optional[float] = None


# ── Public API ────────────────────────────────────────────────────────────────

def build_user_pattern_model(
    user_id: str,
    confirmed_events: list[TagEvent],
    sport_events: Optional[list[SportEvent]] = None,
) -> UserTagPatternModel:
    """
    Build a fresh UserTagPatternModel from confirmed tag events.

    Parameters
    ----------
    user_id : str
    confirmed_events : list[TagEvent]
        All confirmed tagged events for this user.
    sport_events : list[SportEvent] | None
        Sport activity events for stressor detection.

    Returns
    -------
    UserTagPatternModel
    """
    patterns = build_patterns(confirmed_events)
    eligible = frozenset(
        tag for tag, p in patterns.items()
        if p.confirmed_count >= AUTOTAG_MIN_CONFIRMED
    )
    stressors = _detect_sport_stressors(sport_events or [])
    return UserTagPatternModel(
        user_id=user_id,
        patterns=patterns,
        sport_stressor_slugs=stressors,
        auto_tag_eligible_slugs=eligible,
    )


def update_pattern_model(
    model: UserTagPatternModel,
    new_event: TagEvent,
) -> UserTagPatternModel:
    """
    Incrementally add a single new confirmed event to an existing model.

    Returns a new UserTagPatternModel (does not mutate the input).
    """
    # Rebuild entirely — set is small enough to be fast; avoids mutation bugs
    existing_events = _reconstruct_events_from_model(model)
    existing_events.append(new_event)
    return build_user_pattern_model(
        user_id=model.user_id,
        confirmed_events=existing_events,
        sport_events=None,  # sport stressors updated separately
    )


def add_sport_event(
    model: UserTagPatternModel,
    sport_events: list[SportEvent],
) -> UserTagPatternModel:
    """Recompute sport stressor list with additional events."""
    all_sport_events = list(sport_events)
    stressors = _detect_sport_stressors(all_sport_events)
    return UserTagPatternModel(
        user_id=model.user_id,
        patterns=model.patterns,
        sport_stressor_slugs=stressors,
        auto_tag_eligible_slugs=model.auto_tag_eligible_slugs,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _detect_sport_stressors(sport_events: list[SportEvent]) -> list[str]:
    """
    Return sport slugs that consistently produce high stress + slow recovery.

    A sport is flagged when SPORT_MIN_EVENTS or more events all show:
      stress_contrib_pct >= SPORT_STRESS_THRESHOLD * 100
      AND (recovery_arc_hours / personal_arc_avg) >= SPORT_SLOW_RECOVERY_THRESHOLD
          (if recovery data is available)
    """
    if not sport_events:
        return []

    # Group by slug
    by_slug: dict[str, list[SportEvent]] = {}
    for ev in sport_events:
        by_slug.setdefault(ev.sport_slug, []).append(ev)

    stressors: list[str] = []
    for slug, events in by_slug.items():
        if len(events) < SPORT_MIN_EVENTS:
            continue

        high_stress_count = sum(
            1 for ev in events
            if ev.stress_contrib_pct >= SPORT_STRESS_THRESHOLD * 100
        )
        # Only flag if majority of events are high-stress
        if high_stress_count < len(events) * 0.6:
            continue

        # Check recovery if data available
        arc_events = [
            ev for ev in events
            if ev.recovery_arc_hours is not None and ev.personal_arc_avg is not None
        ]
        if arc_events:
            slow_count = sum(
                1 for ev in arc_events
                if ev.recovery_arc_hours / ev.personal_arc_avg >= SPORT_SLOW_RECOVERY_THRESHOLD
            )
            if slow_count < len(arc_events) * 0.6:
                continue  # recovery is not consistently slow

        stressors.append(slug)

    return stressors


def _reconstruct_events_from_model(model: UserTagPatternModel) -> list[TagEvent]:
    """
    Approximate reconstruction of confirmed events from the summary histograms.
    Used when incrementally updating the model with a single new event.

    Expands histograms back to individual synthetic events (count copies per bin).
    This is accurate for pattern purposes since we only care about frequency,
    not individual event identity.
    """
    events: list[TagEvent] = []
    for tag, pat in model.patterns.items():
        # Expand hour_histogram × weekday_counts into synthetic events
        total = pat.confirmed_count
        hours = sorted(pat.hour_histogram.items())
        weekdays = sorted(pat.weekday_counts.items())

        # Interleave hours and weekdays proportionally
        h_cycle = _expand_histogram(hours, total)
        w_cycle = _expand_histogram(weekdays, total)

        for i in range(total):
            events.append(TagEvent(
                hour=h_cycle[i % len(h_cycle)],
                weekday=w_cycle[i % len(w_cycle)],
                tag=tag,
                window_type=pat.window_type,
                suppression_pct=pat.avg_suppression,
            ))
    return events


def _expand_histogram(items: list[tuple[int, int]], total: int) -> list[int]:
    """Expand a (value, count) histogram into a flat list of values."""
    result: list[int] = []
    for val, count in items:
        result.extend([val] * count)
    # Pad or trim to total
    if len(result) < total:
        result.extend([result[0]] * (total - len(result)))
    return result[:total]
