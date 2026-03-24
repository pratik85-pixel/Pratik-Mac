"""
profile/profile_updater.py

DataAssembler-powered profile update — injects real physiological data
into the Layer 1 LLM prompt so the coach narrative is grounded in the
user's actual RMSSD trajectory, windows, and personal model.

Architecture
------------
  The key fix: wrap the llm_client in a thin proxy (_PhysioClient) that
  prepends the PHYSIOLOGICAL SNAPSHOT block to Layer 1's user prompt.
  Layer 1 is detected via its system prompt ("psychological analyst").
  Layer 2 ("planning engine") receives the real scores from DataAssembler.

  Flow:
    run_profile_update()
      → assemble_for_user()         # pulls trajectory, windows, personal model
      → _build_physio_block()       # formats the snapshot in plain text
      → _PhysioClient(client, block) # wraps client — intercepts Layer 1 chat()
      → rebuild_unified_profile()   # Layer 1 (with physio) → Layer 2 → save

Key guarantees
--------------
- NEVER writes empty narrative: nightly_analyst._fallback_narrative() is
  always called on LLM failure, so a deterministic string is always saved.
- No raw ms values reach the LLM: only population-relative labels,
  %-ceiling values, and 0–100 scores from AssembledContext.
- Prompt injection attack surface: DataAssembler._sanitize() blocks
  user-controlled strings before they arrive here.

Entry point
-----------
    profile = await run_profile_update(session, user_id, llm_client, assessment)

Wire point: jobs/nightly_rebuild.py — replaces rebuild_unified_profile() call.
"""
from __future__ import annotations

import logging
import uuid as uuid_mod
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from coach.data_assembler import AssembledContext, assemble_for_user
from api.services.profile_service import rebuild_unified_profile
from profile.profile_schema import UnifiedProfile

log = logging.getLogger(__name__)


# ── LLM proxy ─────────────────────────────────────────────────────────────────

class _PhysioClient:
    """
    Thin wrapper around any llm_client.

    Prepends the PHYSIOLOGICAL SNAPSHOT block to Layer 1's user prompt only.
    Detection uses the system prompt string:
      Layer 1 system → contains "psychological analyst"
      Layer 2 system → contains "planning engine"

    All other attributes are proxied to the real client.
    """

    def __init__(self, real_client: Any, physio_block: str) -> None:
        self._real         = real_client
        self._physio_block = physio_block

    def chat(self, system: str, user: str) -> str:
        if "psychological analyst" in system:
            return self._real.chat(system, self._physio_block + "\n\n" + user)
        return self._real.chat(system, user)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_profile_update(
    session:    AsyncSession,
    user_id:    uuid_mod.UUID,
    llm_client: Optional[Any] = None,
    assessment: Optional[Any] = None,
) -> UnifiedProfile:
    """
    Full profile update with real physiological context injected into Layer 1.

    Steps:
      1. assemble_for_user()  → trajectory, windows, personal model
      2. Extract today's scores from trajectory (more accurate than a plain
         DailyStressSummary lookup because DataAssembler weighs 7 days)
      3. _build_physio_block() → plain-text snapshot
      4. Wrap llm_client with _PhysioClient (Layer 1 intercept)
      5. rebuild_unified_profile() → Layer 1 (physio-aware) → Layer 2 → save

    On LLM failure at any stage:
      nightly_analyst._fallback_narrative() always produces a deterministic
      string — no empty or partial narrative is ever committed to the DB.
    """
    # Step 1 — assemble real context
    ctx = await assemble_for_user(session, user_id)

    # Step 2 — extract scores (latest day in trajectory)
    latest         = ctx.daily_trajectory[-1] if ctx.daily_trajectory else {}
    net_balance    = latest.get("net_balance")
    stress_score   = latest.get("stress_load")
    recovery_score = latest.get("waking_recovery")

    stress_int   = int(round(stress_score))   if stress_score   is not None else None
    recovery_int = int(round(recovery_score)) if recovery_score is not None else None

    # Step 3 — build physio block (no raw ms values)
    physio_block = _build_physio_block(ctx)

    # Step 4 — wrap client (None-safe: fallback path in nightly_analyst handles no client)
    wrapped = _PhysioClient(llm_client, physio_block) if llm_client is not None else None

    # Step 5 — full rebuild with physio-aware Layer 1
    profile = await rebuild_unified_profile(
        session,
        user_id,
        llm_client=wrapped,
        net_balance=net_balance,
        stress_score=stress_int,
        recovery_score=recovery_int,
        assessment=assessment,
    )

    log.info(
        "profile_update OK user=%s v=%d tokens=%d stress=%s recovery=%s net=%s",
        user_id,
        profile.narrative_version,
        ctx.estimated_tokens,
        stress_int,
        recovery_int,
        f"{net_balance:+.1f}" if net_balance is not None else "None",
    )
    return profile


# ── Physio block builder (also used directly by tests) ────────────────────────

def _build_physio_block(ctx: AssembledContext) -> str:
    """
    Format the PHYSIOLOGICAL SNAPSHOT block prepended to Layer 1's user prompt.

    Rules:
    - is_calibrated=False → say "not yet calibrated"; NEVER say "ms" or RMSSD values
    - Empty daily_trajectory → omit the trajectory section entirely (not "Unknown")
    - Stress/recovery windows always shown, even if count=0
    - Background bins shown only if present (they're optional)
    - Population labels always appear at the end
    """
    lines = [
        "=" * 62,
        "PHYSIOLOGICAL SNAPSHOT  (real-time — do NOT conflate with",
        "long-term profile traits listed below this block)",
        "=" * 62,
    ]

    # Personal model
    pm = ctx.personal_model
    if pm and pm.get("is_calibrated"):
        lines.append(
            f"Personal model: floor={pm['floor_ms']:.1f} ms  "
            f"ceiling={pm['ceiling_ms']:.1f} ms  "
            f"morning_avg={pm['morning_avg_ms']:.1f} ms  [calibrated]"
        )
    else:
        lines.append(
            "Personal model: not yet calibrated — "
            "omit all RMSSD-relative claims this session"
        )

    # 7-day trajectory (oldest → newest)
    if ctx.daily_trajectory:
        lines.append("7-day trajectory (oldest → newest):")
        for row in ctx.daily_trajectory:
            sl   = row.get("stress_load")
            wr   = row.get("waking_recovery")
            nb   = row.get("net_balance")
            dt   = row.get("day_type") or "—"
            sl_s = f"{sl:.0f}" if sl is not None else "?"
            wr_s = f"{wr:.0f}" if wr is not None else "?"
            nb_s = f"{nb:+.1f}" if nb is not None else "?"
            lines.append(
                f"  {row['date']}: stress={sl_s}/100  "
                f"recovery={wr_s}/100  net={nb_s}  [{dt}]"
            )
    # (no section if no data — avoid "Unknown throughout")

    # Stress windows (last 24h)
    sw    = ctx.stress_windows_24h
    count = sw.get("count", 0)
    if count > 0:
        sup   = sw.get("avg_suppression_pct")
        tag   = sw.get("top_tag")
        extra = ""
        if sup is not None:
            extra += f"  avg suppression {sup:.0f}%"
        if tag:
            extra += f"  most common: {tag}"
        lines.append(f"Stress events (last 24h): {count}{extra}")
    else:
        lines.append("Stress events (last 24h): none detected")

    # Recovery windows (last 24h)
    rw     = ctx.recovery_windows_24h
    rcount = rw.get("count", 0)
    if rcount > 0:
        sources = rw.get("sources", {})
        src_str = "  ".join(
            f"{k}×{v}"
            for k, v in sorted(sources.items(), key=lambda kv: -kv[1])
        )
        lines.append(f"Recovery events (last 24h): {rcount}  ({src_str})")
    else:
        lines.append("Recovery events (last 24h): none detected")

    # Background HRV bins (optional)
    if ctx.background_bins:
        lines.append("Background HRV (% of personal ceiling, by time of day):")
        for b in ctx.background_bins:
            pct = b.get("rmssd_pct_ceiling")
            lbl = b.get("time_label", "?")
            if pct is not None:
                lines.append(f"  {lbl}: {pct:.0f}%")
            else:
                lines.append(f"  {lbl}: —")

    # Population labels (always last)
    lines.append(
        f"Population: stress = {ctx.population_stress_label}"
        f"  |  recovery = {ctx.population_recovery_label}"
    )
    lines.append("=" * 62)

    return "\n".join(lines)
