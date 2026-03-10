"""
tagging/tagging_service.py

Business logic for all tagging operations.

Responsibilities
----------------
- Tag a window (stress or recovery) — user-confirmed or auto-tagged
- Fetch untagged windows for the Tag Sheet nudge queue
- Run the auto-tagger pass: find eligible untagged windows and apply tags
- Update the user's TagPatternModel after each confirmation
- Build per-user TagPatternModel from scratch (for new users / recompute)

Design contract
---------------
All DB I/O is done via the caller-provided session objects.
This module contains pure Python business logic only.
DB models are imported from api.db.schema — type hints only, not called directly.

The caller (api/services/tagging_service.py) wraps all these functions in
async SQLAlchemy sessions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from tagging.activity_catalog import CATALOG, get_activity, is_valid_slug
from tagging.auto_tagger import (
    AUTO_TAG_THRESHOLD,
    SuggestionResult,
    TagEvent,
    suggest_tag,
)
from tagging.tag_pattern_model import (
    SportEvent,
    UserTagPatternModel,
    build_user_pattern_model,
    update_pattern_model,
)


# ── Input / output types ──────────────────────────────────────────────────────

@dataclass
class WindowRef:
    """
    Minimal reference to a stress or recovery window for tagging operations.

    window_id      — UUID as string
    window_type    — "stress" | "recovery"
    started_at     — window start datetime
    tag            — current tag (None = untagged)
    tag_source     — current tag_source
    suppression_pct — stress depth; None for recovery windows
    """
    window_id:       str
    window_type:     str
    started_at:      datetime
    tag:             Optional[str]
    tag_source:      Optional[str]
    suppression_pct: Optional[float] = None


@dataclass
class TagResult:
    """Result of a tagging operation."""
    success:     bool
    window_id:   str
    tag_applied: Optional[str]
    tag_source:  str              # "user_confirmed" | "auto_tagged"
    error:       Optional[str]   = None


@dataclass
class AutoTagPass:
    """
    Summary of an auto-tag pass across one day's untagged windows.

    tagged_count    — number of windows auto-tagged
    skipped_count   — number of windows below threshold
    results         — per-window SuggestionResult for auditing
    """
    tagged_count:  int
    skipped_count: int
    results:       list[tuple[str, SuggestionResult]]


@dataclass
class PatternModelBuildResult:
    """Result of building/rebuilding the user's pattern model."""
    user_id:   str
    model:     UserTagPatternModel
    patterns_built: int
    sport_stressors: list[str]


# ── Tag validation ────────────────────────────────────────────────────────────

def validate_tag(slug: str, window_type: str) -> tuple[bool, str]:
    """
    Validate that a proposed tag slug is appropriate for the window type.

    Returns (is_valid, error_message).
    """
    if not is_valid_slug(slug):
        return False, f"Unknown activity slug: '{slug}'"

    act = get_activity(slug)
    if act is None:
        return False, f"Activity not found: '{slug}'"

    # Recovery windows should only receive recovery-type activities
    if window_type == "recovery" and act.stress_or_recovery == "stress":
        return (
            False,
            f"'{slug}' is a stress activity — cannot tag a recovery window with it.",
        )

    # Stress windows should receive stress or mixed activities
    if window_type == "stress" and act.stress_or_recovery == "recovery":
        return (
            False,
            f"'{slug}' is a recovery activity — cannot tag a stress window with it.",
        )

    return True, ""


# ── Apply tag ─────────────────────────────────────────────────────────────────

def apply_user_tag(
    window: WindowRef,
    slug: str,
) -> TagResult:
    """
    Apply a user-confirmed tag to a window.

    Returns TagResult.  The caller is responsible for persisting
    window.tag = slug and window.tag_source = "user_confirmed".
    """
    valid, err = validate_tag(slug, window.window_type)
    if not valid:
        return TagResult(success=False, window_id=window.window_id, tag_applied=None,
                         tag_source="user_confirmed", error=err)
    return TagResult(
        success=True,
        window_id=window.window_id,
        tag_applied=slug,
        tag_source="user_confirmed",
    )


# ── Auto-tag pass ─────────────────────────────────────────────────────────────

def run_auto_tag_pass(
    user_model: UserTagPatternModel,
    untagged_windows: list[WindowRef],
) -> AutoTagPass:
    """
    Apply auto-tags to untagged windows that match known user patterns.

    Only windows whose (time-of-day, weekday, window-type) matches a known
    pattern at >= AUTO_TAG_THRESHOLD confidence are tagged.

    Parameters
    ----------
    user_model : UserTagPatternModel
        The user's current pattern model.
    untagged_windows : list[WindowRef]
        Windows that have tag=None or tag_source="auto_detected".

    Returns
    -------
    AutoTagPass
        Contains per-window suggestion results.  The caller must persist
        the tag changes to DB for eligible windows.
    """
    if not user_model.patterns:
        return AutoTagPass(tagged_count=0, skipped_count=len(untagged_windows), results=[])

    tagged = 0
    skipped = 0
    results: list[tuple[str, SuggestionResult]] = []

    for window in untagged_windows:
        candidate = TagEvent(
            hour=window.started_at.hour,
            weekday=window.started_at.weekday(),
            tag=None,
            window_type=window.window_type,
            suppression_pct=window.suppression_pct,
        )
        suggestion = suggest_tag(candidate, user_model.patterns)
        results.append((window.window_id, suggestion))

        if suggestion.eligible:
            # Validate before flagging as auto-tagged
            valid, _ = validate_tag(suggestion.best_tag, window.window_type)  # type: ignore
            if valid:
                tagged += 1
            else:
                skipped += 1
        else:
            skipped += 1

    return AutoTagPass(tagged_count=tagged, skipped_count=skipped, results=results)


# ── Pattern model build ───────────────────────────────────────────────────────

def build_pattern_model_from_windows(
    user_id: str,
    confirmed_stress_windows: list[WindowRef],
    confirmed_recovery_windows: list[WindowRef],
    sport_events: Optional[list[SportEvent]] = None,
) -> PatternModelBuildResult:
    """
    Build a fresh UserTagPatternModel from confirmed windows.

    Parameters
    ----------
    user_id : str
    confirmed_stress_windows : list[WindowRef]
        StressWindows with tag != None and tag_source in
        {"user_confirmed", "auto_tagged"}.
    confirmed_recovery_windows : list[WindowRef]
        RecoveryWindows with tag != None.
    sport_events : list[SportEvent] | None
        Sport activity events for stressor detection.

    Returns
    -------
    PatternModelBuildResult
    """
    events: list[TagEvent] = []

    for w in confirmed_stress_windows:
        if w.tag:
            events.append(TagEvent(
                hour=w.started_at.hour,
                weekday=w.started_at.weekday(),
                tag=w.tag,
                window_type="stress",
                suppression_pct=w.suppression_pct,
            ))

    for w in confirmed_recovery_windows:
        if w.tag:
            events.append(TagEvent(
                hour=w.started_at.hour,
                weekday=w.started_at.weekday(),
                tag=w.tag,
                window_type="recovery",
                suppression_pct=None,
            ))

    model = build_user_pattern_model(
        user_id=user_id,
        confirmed_events=events,
        sport_events=sport_events,
    )

    return PatternModelBuildResult(
        user_id=user_id,
        model=model,
        patterns_built=len(model.patterns),
        sport_stressors=model.sport_stressor_slugs,
    )


def update_model_after_confirmation(
    model: UserTagPatternModel,
    confirmed_window: WindowRef,
) -> UserTagPatternModel:
    """
    Incrementally update the pattern model after a user confirms a tag.

    Faster than full rebuild — suitable for real-time update on user confirm.
    """
    if not confirmed_window.tag:
        return model

    new_event = TagEvent(
        hour=confirmed_window.started_at.hour,
        weekday=confirmed_window.started_at.weekday(),
        tag=confirmed_window.tag,
        window_type=confirmed_window.window_type,
        suppression_pct=confirmed_window.suppression_pct,
    )
    return update_pattern_model(model, new_event)


# ── Nudge queue ───────────────────────────────────────────────────────────────

def get_nudge_queue(
    windows: list[WindowRef],
    max_items: int = 3,
) -> list[WindowRef]:
    """
    Return the N most important untagged windows for the Tag Sheet nudge.

    Priority order:
      1. Windows with high suppression_pct (most informative to the user)
      2. Longer duration implied by suppression depth
      3. Most recent first as tiebreaker

    Parameters
    ----------
    windows : list[WindowRef]
        All untagged windows for the user today / this session.
    max_items : int
        Maximum number of items to surface (default 3 for Tag Sheet).
    """
    untagged = [w for w in windows if w.tag is None]
    # Sort: high suppression first, then most recent
    untagged.sort(
        key=lambda w: (
            -(w.suppression_pct or 0.0),
            -w.started_at.timestamp(),
        )
    )
    return untagged[:max_items]
