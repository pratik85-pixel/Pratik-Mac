"""
tagging/auto_tagger.py

Deterministic auto-tagging for StressWindows and RecoveryWindows.

Design
------
Auto-tagging fires after a user has confirmed >= AUTOTAG_MIN_CONFIRMED events
for a (window_type, tag) pair.  Time-of-day and weekday patterns are used to
classify future unconfirmed windows without requiring user input.

Two steps:
  1. build_pattern() — compute time/weekday histogram from confirmed events
  2. suggest_tag()   — score an unconfirmed window against all known patterns

The output is always a SuggestionResult.  Callers apply the tag only when
confidence >= AUTO_TAG_THRESHOLD.  They always set tag_source="auto_tagged".

Thresholds (from config):
    AUTOTAG_MIN_CONFIRMED  = 3   minimum confirmed events to build a pattern
    AUTO_TAG_THRESHOLD     = 0.60 minimum confidence to auto-apply
    HOUR_BAND_WIDTH        = 2   ±hours for time-of-day match
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from tagging.activity_catalog import CATALOG, get_activity


# ── Constants ─────────────────────────────────────────────────────────────────

AUTOTAG_MIN_CONFIRMED: int  = 3
AUTO_TAG_THRESHOLD:    float = 0.60
HOUR_BAND_WIDTH:       int  = 2   # ± hours for time-of-day match


# ── Input / Output types ──────────────────────────────────────────────────────

@dataclass
class TagPattern:
    """
    Per-(user, tag, window_type) learned pattern.

    hour_histogram   — dict mapping hour (0–23) → confirmed count
    weekday_counts   — dict mapping weekday (0=Mon … 6=Sun) → confirmed count
    confirmed_count  — total confirmed events in this pattern
    avg_suppression  — for stress windows: mean suppression_pct across confirmed events
    """
    tag:              str
    window_type:      str           # "stress" | "recovery"
    confirmed_count:  int
    hour_histogram:   dict[int, int]
    weekday_counts:   dict[int, int]
    avg_suppression:  Optional[float] = None   # stress windows only


@dataclass
class TagEvent:
    """
    Single confirmed (or candidate) window event — input to auto-tagger.

    hour         — hour-of-day the window started (0–23)
    weekday      — 0=Mon … 6=Sun
    tag          — confirmed tag (None for candidate to be classified)
    window_type  — "stress" | "recovery"
    suppression_pct — stress signal depth (0–1); None for recovery windows
    """
    hour:           int
    weekday:        int
    tag:            Optional[str]
    window_type:    str
    suppression_pct: Optional[float] = None


@dataclass
class SuggestionResult:
    """
    Outcome of suggest_tag() for a single candidate window.

    best_tag        — highest-scoring tag slug, or None if below threshold
    confidence      — 0.0–1.0 match score
    all_scores      — {tag: score} for all evaluated patterns
    eligible        — True if confidence >= AUTO_TAG_THRESHOLD
    """
    best_tag:   Optional[str]
    confidence: float
    all_scores: dict[str, float]
    eligible:   bool


# ── Pattern building ──────────────────────────────────────────────────────────

def build_patterns(
    confirmed_events: list[TagEvent],
) -> dict[str, TagPattern]:
    """
    Build per-tag patterns from a list of confirmed events.

    Parameters
    ----------
    confirmed_events : list[TagEvent]
        All confirmed tagged events for a single user.  Must have tag != None.

    Returns
    -------
    dict[str, TagPattern]
        Keyed by tag slug.  Only patterns with confirmed_count >= AUTOTAG_MIN_CONFIRMED
        are included (others are not reliable enough for auto-tagging).
    """
    # Accumulate
    accum: dict[str, dict] = {}
    for ev in confirmed_events:
        if ev.tag is None:
            continue
        if ev.tag not in accum:
            accum[ev.tag] = {
                "count": 0,
                "hour_hist": {},
                "weekday_counts": {},
                "window_type": ev.window_type,
                "suppress_sum": 0.0,
                "suppress_n": 0,
            }
        a = accum[ev.tag]
        a["count"] += 1
        a["hour_hist"][ev.hour] = a["hour_hist"].get(ev.hour, 0) + 1
        a["weekday_counts"][ev.weekday] = a["weekday_counts"].get(ev.weekday, 0) + 1
        if ev.suppression_pct is not None:
            a["suppress_sum"] += ev.suppression_pct
            a["suppress_n"] += 1

    # Filter and convert
    patterns: dict[str, TagPattern] = {}
    for tag, a in accum.items():
        if a["count"] < AUTOTAG_MIN_CONFIRMED:
            continue
        avg_supp = (a["suppress_sum"] / a["suppress_n"]) if a["suppress_n"] else None
        patterns[tag] = TagPattern(
            tag=tag,
            window_type=a["window_type"],
            confirmed_count=a["count"],
            hour_histogram=a["hour_hist"],
            weekday_counts=a["weekday_counts"],
            avg_suppression=avg_supp,
        )
    return patterns


# ── Tag suggestion ────────────────────────────────────────────────────────────

def suggest_tag(
    candidate: TagEvent,
    patterns: dict[str, TagPattern],
) -> SuggestionResult:
    """
    Score a candidate window against all known patterns.

    Scoring model (0.0–1.0 per pattern):
        0.50 — time-of-day match (within ± HOUR_BAND_WIDTH hours, smoothed)
        0.30 — weekday match (same weekday has > 50% of pattern weight)
        0.20 — window-type match (must match; 0 if mismatch)

    Parameters
    ----------
    candidate : TagEvent
        The unconfirmed event to classify.
    patterns : dict[str, TagPattern]
        Built by build_patterns() from confirmed events.

    Returns
    -------
    SuggestionResult
    """
    if not patterns:
        return SuggestionResult(best_tag=None, confidence=0.0, all_scores={}, eligible=False)

    scores: dict[str, float] = {}
    for tag, pat in patterns.items():
        # Window-type gate
        if pat.window_type != candidate.window_type:
            scores[tag] = 0.0
            continue

        score = 0.0

        # Time-of-day component (0.50 weight)
        hour_score = _hour_score(candidate.hour, pat.hour_histogram)
        score += 0.50 * hour_score

        # Weekday component (0.30 weight)
        weekday_score = _weekday_score(candidate.weekday, pat.weekday_counts)
        score += 0.30 * weekday_score

        # Window-type match bonus (0.20 weight) — already gated above
        score += 0.20

        scores[tag] = round(score, 4)

    if not scores:
        return SuggestionResult(best_tag=None, confidence=0.0, all_scores={}, eligible=False)

    best_tag = max(scores, key=lambda t: scores[t])
    best_conf = scores[best_tag]
    eligible = best_conf >= AUTO_TAG_THRESHOLD

    return SuggestionResult(
        best_tag=best_tag if eligible else None,
        confidence=best_conf,
        all_scores=scores,
        eligible=eligible,
    )


# ── Scoring helpers ───────────────────────────────────────────────────────────

def _hour_score(candidate_hour: int, hour_histogram: dict[int, int]) -> float:
    """
    Score how well the candidate hour matches the pattern histogram.

    Uses a band-match: hours within ± HOUR_BAND_WIDTH receive decaying weight.
    Returns a 0.0–1.0 value representing fraction of pattern weight in-band.
    """
    if not hour_histogram:
        return 0.0
    total = sum(hour_histogram.values())
    if total == 0:
        return 0.0

    in_band = 0
    for h, count in hour_histogram.items():
        dist = min(abs(candidate_hour - h), 24 - abs(candidate_hour - h))  # wrap-around
        if dist <= HOUR_BAND_WIDTH:
            decay = 1.0 - (dist / (HOUR_BAND_WIDTH + 1))
            in_band += count * decay

    return min(in_band / total, 1.0)


def _weekday_score(candidate_weekday: int, weekday_counts: dict[int, int]) -> float:
    """
    Score how well the candidate weekday matches the pattern.

    Returns 1.0 if the candidate weekday holds the majority of pattern weight,
    scaled down proportionally otherwise.
    """
    if not weekday_counts:
        return 0.0
    total = sum(weekday_counts.values())
    if total == 0:
        return 0.0
    return round(weekday_counts.get(candidate_weekday, 0) / total, 4)
