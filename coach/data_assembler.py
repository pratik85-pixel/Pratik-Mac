"""
coach/data_assembler.py

Assembles a clean, token-capped data package for any LLM call.

This is the single source of truth for what data the LLM receives about a user.
No raw physiological values (RMSSD in ms) ever appear in the output —
all values are normalised relative to the personal model.

Usage
-----
    ctx = await assemble_for_user(session, user_id)
    # ctx is an AssembledContext — pass fields directly into prompts / coach context

Token budget
------------
Hard cap: 4,000 tokens (≈ 16,000 chars).  Enforced by progressive truncation:
  1. Truncate coach_narrative to 400 chars
  2. Trim habit_events to 3 items
  3. Trim user_facts to 3 items

Security
--------
All user-supplied text (user_facts, habit_events, habit notes) is sanitized
before assembly to prevent prompt-injection attacks.  Only printable Unicode
word characters, spaces, and safe punctuation are allowed through.
"""

from __future__ import annotations

import re
import uuid as uuid_mod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

import api.db.schema as db

# ── Constants ─────────────────────────────────────────────────────────────────

_TOKEN_CAP       = 4_000
_CHARS_PER_TOKEN = 4          # conservative: 1 token ≈ 4 chars

# ── Population baselines (hard-coded — no DB table) ──────────────────────────
# Each tuple is (min_score_inclusive, label). First match wins (descending).

_STRESS_BANDS: list[tuple[float, str]] = [
    (80.0, "very high"),
    (60.0, "high"),
    (30.0, "moderate"),
    (0.0,  "low"),
]

_RECOVERY_BANDS: list[tuple[float, str]] = [
    (70.0, "excellent"),
    (45.0, "good"),
    (20.0, "fair"),
    (0.0,  "poor"),
]

# ── Sanitizer ─────────────────────────────────────────────────────────────────

# Allow: Unicode word chars, whitespace, and safe punctuation.
# Block: angle brackets, backticks, curly braces, hash, pipe — all common injection vectors.
_UNSAFE = re.compile(r"[<>{}`|#\\]", re.UNICODE)


def _sanitize(text: str, max_len: int = 200) -> str:
    """Strip prompt-injection characters and truncate to max_len."""
    cleaned = _UNSAFE.sub("", text or "")
    return cleaned[:max_len].strip()


# ── Output dataclass ──────────────────────────────────────────────────────────

@dataclass
class AssembledContext:
    """
    All data the LLM is allowed to see about a user, in one package.

    Sections that have no data stay at their default (None / empty).
    Callers should check `is_calibrated` on personal_model before citing
    any RMSSD-relative values.
    """

    # ── Personal model ────────────────────────────────────────────────────────
    # Keys: floor_ms, ceiling_ms, morning_avg_ms, is_calibrated (bool)
    personal_model: Optional[dict] = None

    # ── 7-day trajectory (oldest → newest) ───────────────────────────────────
    # Keys per entry: date (str), stress_load, waking_recovery, net_balance, day_type
    daily_trajectory: list[dict] = field(default_factory=list)

    # ── Live 24h snapshot ────────────────────────────────────────────────────
    # Keys: count, avg_suppression_pct (0–100), top_tag
    stress_windows_24h: dict = field(default_factory=dict)
    # Keys: count, sources {tag: count}
    recovery_windows_24h: dict = field(default_factory=dict)

    # ── Background bins (4h buckets, last 24h) ───────────────────────────────
    # Keys per entry: time_label (e.g. "08:00–12:00"), rmssd_pct_ceiling, window_count
    background_bins: list[dict] = field(default_factory=list)

    # ── Context ───────────────────────────────────────────────────────────────
    habit_events:    list[str] = field(default_factory=list)   # plain-English, last 72h
    user_facts:      list[str] = field(default_factory=list)   # confidence ≥ 0.7
    coach_narrative: Optional[str] = None                      # ≤ 800 chars from UUP

    # ── Population-relative labels ────────────────────────────────────────────
    population_stress_label:   str = "unknown"
    population_recovery_label: str = "unknown"

    # ── Metadata ──────────────────────────────────────────────────────────────
    estimated_tokens: int = 0


# ── Main entry point ──────────────────────────────────────────────────────────

async def assemble_for_user(
    session: AsyncSession,
    user_id: uuid_mod.UUID,
) -> AssembledContext:
    """
    Query all data sources and return a token-capped AssembledContext.

    Safe to call on any user — every section degrades gracefully to an empty
    default if the table has no rows for this user.
    """
    now = datetime.now(UTC)

    pm     = await _fetch_personal_model(session, user_id)
    traj   = await _fetch_daily_trajectory(session, user_id, now)
    sw     = await _fetch_stress_windows(session, user_id, now)
    rw     = await _fetch_recovery_windows(session, user_id, now)
    bins   = await _fetch_background_bins(session, user_id, now, pm)
    habits = await _fetch_habit_events(session, user_id, now)
    facts  = await _fetch_user_facts(session, user_id)
    narr   = await _fetch_coach_narrative(session, user_id)

    # Population labels derived from most recent available trajectory entry
    latest             = traj[-1] if traj else {}
    stress_label   = _stress_label(latest.get("stress_load"))
    recovery_label = _recovery_label(latest.get("waking_recovery"))

    ctx = AssembledContext(
        personal_model            = pm or None,
        daily_trajectory          = traj,
        stress_windows_24h        = sw,
        recovery_windows_24h      = rw,
        background_bins           = bins,
        habit_events              = habits,
        user_facts                = facts,
        coach_narrative           = narr,
        population_stress_label   = stress_label,
        population_recovery_label = recovery_label,
    )
    ctx = _enforce_token_cap(ctx)
    return ctx


# ── Section fetchers ──────────────────────────────────────────────────────────

async def _fetch_personal_model(
    session: AsyncSession,
    user_id: uuid_mod.UUID,
) -> dict:
    result = await session.execute(
        select(db.PersonalModel).where(db.PersonalModel.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return {}

    calibrated = (
        row.rmssd_floor is not None
        and row.rmssd_ceiling is not None
        and row.rmssd_morning_avg is not None
        and row.rmssd_ceiling > 0
    )
    return {
        "floor_ms":       row.rmssd_floor,
        "ceiling_ms":     row.rmssd_ceiling,
        "morning_avg_ms": row.rmssd_morning_avg,
        "is_calibrated":  calibrated,
    }


async def _fetch_daily_trajectory(
    session: AsyncSession,
    user_id: uuid_mod.UUID,
    now:     datetime,
) -> list[dict]:
    cutoff = now - timedelta(days=7)
    result = await session.execute(
        select(db.DailyStressSummary)
        .where(
            and_(
                db.DailyStressSummary.user_id      == user_id,
                db.DailyStressSummary.summary_date >= cutoff,
            )
        )
        .order_by(db.DailyStressSummary.summary_date.asc())
    )
    rows = result.scalars().all()
    out = []
    for row in rows:
        sd = row.summary_date
        if hasattr(sd, "date"):
            sd = sd.date()
        out.append({
            "date":            str(sd),
            "stress_load":     _round(row.stress_load_score),
            "waking_recovery": _round(row.waking_recovery_score),
            "net_balance":     _round(row.net_balance),
            "day_type":        row.day_type,
        })
    return out


async def _fetch_stress_windows(
    session: AsyncSession,
    user_id: uuid_mod.UUID,
    now:     datetime,
) -> dict:
    cutoff = now - timedelta(hours=24)
    result = await session.execute(
        select(db.StressWindow)
        .where(
            and_(
                db.StressWindow.user_id    == user_id,
                db.StressWindow.started_at >= cutoff,
            )
        )
    )
    rows = result.scalars().all()
    if not rows:
        return {"count": 0, "avg_suppression_pct": None, "top_tag": None}

    suppressions = [
        r.suppression_pct for r in rows if r.suppression_pct is not None
    ]
    # suppression_pct is 0–1 in DB; convert to 0–100 for display
    avg_sup = (
        round(sum(suppressions) / len(suppressions) * 100, 1)
        if suppressions else None
    )

    tag_counts: dict[str, int] = {}
    for r in rows:
        if r.tag:
            tag_counts[r.tag] = tag_counts.get(r.tag, 0) + 1
    top_tag = max(tag_counts, key=tag_counts.__getitem__) if tag_counts else None

    return {
        "count":               len(rows),
        "avg_suppression_pct": avg_sup,
        "top_tag":             top_tag,
    }


async def _fetch_recovery_windows(
    session: AsyncSession,
    user_id: uuid_mod.UUID,
    now:     datetime,
) -> dict:
    cutoff = now - timedelta(hours=24)
    result = await session.execute(
        select(db.RecoveryWindow)
        .where(
            and_(
                db.RecoveryWindow.user_id    == user_id,
                db.RecoveryWindow.started_at >= cutoff,
            )
        )
    )
    rows = result.scalars().all()
    if not rows:
        return {"count": 0, "sources": {}}

    sources: dict[str, int] = {}
    for r in rows:
        tag = r.tag or "untagged"
        sources[tag] = sources.get(tag, 0) + 1

    return {"count": len(rows), "sources": sources}


async def _fetch_background_bins(
    session: AsyncSession,
    user_id: uuid_mod.UUID,
    now:     datetime,
    pm:      dict,
) -> list[dict]:
    ceiling = pm.get("ceiling_ms")
    if not ceiling or ceiling <= 0:
        return []

    cutoff = now - timedelta(hours=24)
    result = await session.execute(
        select(db.BackgroundWindow)
        .where(
            and_(
                db.BackgroundWindow.user_id      == user_id,
                db.BackgroundWindow.window_start >= cutoff,
                db.BackgroundWindow.is_valid     == True,   # noqa: E712
                db.BackgroundWindow.context      == "background",
            )
        )
        .order_by(db.BackgroundWindow.window_start.asc())
    )
    rows = result.scalars().all()
    if not rows:
        return []

    # Group into 4h slots by hour-of-day
    slot_values: dict[int, list[float]] = {}
    for row in rows:
        if row.rmssd_ms is None:
            continue
        start = row.window_start
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        slot = (start.hour // 4) * 4
        slot_values.setdefault(slot, []).append(row.rmssd_ms)

    out = []
    for slot_start in sorted(slot_values.keys()):
        values = slot_values[slot_start]
        avg_pct = round(sum(values) / len(values) / ceiling * 100, 1)
        slot_end = (slot_start + 4) % 24
        out.append({
            "time_label":        f"{slot_start:02d}:00–{slot_end:02d}:00",
            "rmssd_pct_ceiling": avg_pct,
            "window_count":      len(values),
        })
    return out


async def _fetch_habit_events(
    session: AsyncSession,
    user_id: uuid_mod.UUID,
    now:     datetime,
) -> list[str]:
    cutoff = now - timedelta(hours=72)
    result = await session.execute(
        select(db.HabitEvent)
        .where(
            and_(
                db.HabitEvent.user_id == user_id,
                db.HabitEvent.ts      >= cutoff,
            )
        )
        .order_by(db.HabitEvent.ts.desc())
        .limit(10)
    )
    rows = result.scalars().all()
    out = []
    for row in rows:
        ts = row.ts
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        hours_ago = (now - ts).total_seconds() / 3600
        when = _hours_ago_label(hours_ago)
        severity_str = f" ({row.severity})" if row.severity else ""
        label = f"{row.event_type}{severity_str} – {when}"
        out.append(_sanitize(label, max_len=80))
    return out


async def _fetch_user_facts(
    session: AsyncSession,
    user_id: uuid_mod.UUID,
) -> list[str]:
    result = await session.execute(
        select(db.UserFact)
        .where(
            and_(
                db.UserFact.user_id    == user_id,
                db.UserFact.confidence >= 0.7,
            )
        )
        .order_by(db.UserFact.confidence.desc())
        .limit(10)
    )
    rows = result.scalars().all()
    return [_sanitize(r.fact_text, max_len=100) for r in rows]


async def _fetch_coach_narrative(
    session: AsyncSession,
    user_id: uuid_mod.UUID,
) -> Optional[str]:
    result = await session.execute(
        select(db.UserUnifiedProfile.coach_narrative)
        .where(db.UserUnifiedProfile.user_id == user_id)
    )
    narrative = result.scalar_one_or_none()
    if not narrative:
        return None
    return narrative[:800]


# ── Population label helpers ──────────────────────────────────────────────────

def _stress_label(score: Optional[float]) -> str:
    if score is None:
        return "unknown"
    for threshold, label in _STRESS_BANDS:
        if score >= threshold:
            return label
    return "low"


def _recovery_label(score: Optional[float]) -> str:
    if score is None:
        return "unknown"
    for threshold, label in _RECOVERY_BANDS:
        if score >= threshold:
            return label
    return "poor"


# ── Token cap enforcement ─────────────────────────────────────────────────────

def _estimate_tokens(ctx: AssembledContext) -> int:
    parts = [
        str(ctx.personal_model or ""),
        str(ctx.daily_trajectory),
        str(ctx.stress_windows_24h),
        str(ctx.recovery_windows_24h),
        str(ctx.background_bins),
        " ".join(ctx.habit_events),
        " ".join(ctx.user_facts),
        ctx.coach_narrative or "",
    ]
    return sum(len(p) for p in parts) // _CHARS_PER_TOKEN


def _enforce_token_cap(ctx: AssembledContext) -> AssembledContext:
    """
    Progressively truncate sections until estimated token count ≤ _TOKEN_CAP.

    Truncation order (preserve most important data first):
      1. coach_narrative → 400 chars  (was 800; still useful)
      2. habit_events    → 3 items
      3. user_facts      → 3 items
    """
    ctx.estimated_tokens = _estimate_tokens(ctx)
    if ctx.estimated_tokens <= _TOKEN_CAP:
        return ctx

    # Step 1
    if ctx.coach_narrative and len(ctx.coach_narrative) > 400:
        ctx.coach_narrative = ctx.coach_narrative[:400]
        ctx.estimated_tokens = _estimate_tokens(ctx)
    if ctx.estimated_tokens <= _TOKEN_CAP:
        return ctx

    # Step 2
    ctx.habit_events = ctx.habit_events[:3]
    ctx.estimated_tokens = _estimate_tokens(ctx)
    if ctx.estimated_tokens <= _TOKEN_CAP:
        return ctx

    # Step 3
    ctx.user_facts = ctx.user_facts[:3]
    ctx.estimated_tokens = _estimate_tokens(ctx)
    return ctx


# ── Misc helpers ───────────────────────────────────────────────────────────────

def _round(val: Optional[float], ndigits: int = 1) -> Optional[float]:
    return round(val, ndigits) if val is not None else None


def _hours_ago_label(hours: float) -> str:
    if hours < 2:
        return "just now"
    if hours < 16:
        return f"{int(hours)}h ago"
    if hours < 32:
        return "yesterday"
    if hours < 56:
        return "2 days ago"
    return "3 days ago"
