"""
api/services/coach_service.py

Assembles coaching context and generates coaching output for all trigger types.

Trigger types handled
---------------------
    "post_session"     — immediately after a session ends
    "nudge"            — mid-day motivational / reminder
    "weekly_review"    — end-of-week synthesis
    "evening_checkin"  — end-of-day physio synthesis (Phase 5)
    "night_closure"    — tomorrow morning-brief seed (Phase 5)

All calls are synchronous wrappers around the coach layer.
The LLM client is injected so the service can run in offline mode during tests.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import TYPE_CHECKING, Any, Optional

from archetypes.scorer import NSHealthProfile
from coach.context_builder import build_coach_context
from coach.tone_selector import select_tone
from coach.coach_api import generate_response
from coach.milestone_detector import detect_milestone
from coach.plan_replanner import (
    compute_daily_prescription,
    DailyPrescription,
    HabitSignal,
)
from coach.prescriber import DailyPlan, plan_to_items_json, build_daily_plan_from_uup
from model.baseline_builder import PersonalFingerprint
from outcomes.session_outcomes import SessionOutcome

if TYPE_CHECKING:
    from coach.data_assembler import AssembledContext

logger = logging.getLogger(__name__)

# ── Phase 5 inline LLM prompts ───────────────────────────────────────────────
# These are minimal system prompts for assembled-context triggers.
# They reuse the same output-format rules as the main coach system prompt.

_EVENING_CHECKIN_SYSTEM = """\
You are the ZenFlow Verity coach. The user's day is wrapping up.
Write a brief, grounded evening check-in from the data provided.

Rules
-----
- Plain language only. No clinical terms (HRV, RMSSD, cortisol, autonomic, etc.)
- No medical advice. No disclaimers.
- day_summary: 1-2 sentences. What the body showed today. Cite one number if available.
- tonight_priority: 1 short sentence. Single clearest action for tonight.
- trend_note: 1 sentence. Whether today fits or breaks the recent pattern.

Output ONLY valid JSON — no markdown fences, no commentary:
{
  "day_summary":       "...",
  "tonight_priority":  "...",
  "trend_note":        "..."
}
"""

_NIGHT_CLOSURE_SYSTEM = """\
You are the ZenFlow Verity coach. The user's day is complete.
Generate a tomorrow-seed sentence that will prime the morning brief,
and a brief updated narrative for the user's profile.

Rules
-----
- Plain language only. No clinical terms (HRV, RMSSD, cortisol, autonomic, etc.)
- No medical advice. No disclaimers.
- updated_narrative: 2-3 sentences. How today changes the understanding of this user.
- tomorrow_seed: 1 sentence (≤20 words). What the morning brief should lead with tomorrow.

Output ONLY valid JSON — no markdown fences, no commentary:
{
  "updated_narrative": "...",
  "tomorrow_seed":     "..."
}
"""


# ── Assembled-trigger helper ──────────────────────────────────────────────────

def _build_assembled_user_prompt(assembled: "AssembledContext", trigger_type: str) -> str:
    """Build a minimal user prompt from AssembledContext for Phase 5 triggers."""
    traj = assembled.daily_trajectory
    latest = traj[-1] if traj else {}
    stress  = latest.get("stress_load",     "unavailable")
    recov   = latest.get("waking_recovery", "unavailable")
    balance = latest.get("net_balance",     "unavailable")
    day_type = latest.get("day_type",       "unavailable")

    traj_summary = (
        ", ".join(
            f"{e.get('date','?')} s={e.get('stress_load','?')} r={e.get('waking_recovery','?')}"
            for e in traj[-7:]
        )
        if traj else "no data"
    )

    stress_label   = assembled.population_stress_label
    recovery_label = assembled.population_recovery_label
    narrative      = assembled.coach_narrative or "none"
    facts          = "\n".join(f"- {f}" for f in assembled.user_facts[:5]) or "none"

    return f"""\
TRIGGER: {trigger_type}

TODAY
    Stress load: {stress} (population: {stress_label})
    Waking recovery: {recov} (population: {recovery_label})
    Net balance: {balance}
    Day type: {day_type}

7-DAY TRAJECTORY (oldest→newest):
    {traj_summary}

PROFILE NARRATIVE:
{narrative}

USER FACTS:
{facts}
"""


def _llm_invoke_json(
    llm_client: Any,
    system_prompt: str,
    user_prompt: str,
) -> dict:
    """
    Support both ZenFlow's duck-typed `llm_client.chat(system, user) -> str`
    and OpenAI-style `llm_client.chat.completions.create(...)`.
    """
    chat_fn = getattr(llm_client, "chat", None)
    if callable(chat_fn):
        raw_text = chat_fn(system_prompt, user_prompt)
        raw_text = re.sub(r"^```[a-z]*\n?", "", raw_text.strip())
        raw_text = re.sub(r"\n?```$", "", raw_text.strip())
        return json.loads(raw_text)
    # OpenAI client path (Phase 5 inline prompts)
    response = llm_client.chat.completions.create(
        model="gpt-4o",
        temperature=0.6,
        max_tokens=300,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
    )
    raw_text = response.choices[0].message.content or ""
    raw_text = re.sub(r"^```[a-z]*\n?", "", raw_text.strip())
    raw_text = re.sub(r"\n?```$", "", raw_text.strip())
    return json.loads(raw_text)


def _run_assembled_trigger(
    assembled: "AssembledContext",
    *,
    trigger_type: str,
    llm_client: Optional[Any],
    system_prompt: str,
    user_name: str = "there",
) -> dict:
    """
    Run an assembled-context trigger through the LLM (or deterministic fallback).

    Returns a dict matching the output schema for trigger_type.
    """
    user_prompt = _build_assembled_user_prompt(assembled, trigger_type)

    if llm_client is None:
        return _assembled_fallback(assembled, trigger_type)

    try:
        return _llm_invoke_json(llm_client, system_prompt, user_prompt)
    except Exception as exc:
        logger.warning("assembled_trigger LLM failed trigger=%s: %s", trigger_type, exc)
        return _assembled_fallback(assembled, trigger_type)


def _assembled_fallback(assembled: "AssembledContext", trigger_type: str) -> dict:
    """Deterministic fallback when LLM is unavailable."""
    traj = assembled.daily_trajectory
    latest = traj[-1] if traj else {}
    stress  = latest.get("stress_load",     None)
    recov   = latest.get("waking_recovery", None)
    balance = latest.get("net_balance",     None)

    if trigger_type == "evening_checkin":
        if stress is not None and recov is not None:
            s_str = f"Stress load reached {stress}, recovery at {recov}."
        else:
            s_str = "Physio data is still being collected."
        return {
            "day_summary":      s_str,
            "tonight_priority": "A short wind-down routine will help the system reset overnight.",
            "trend_note":       "Today's data will inform tomorrow's morning brief.",
        }
    if trigger_type == "night_closure":
        if balance is not None:
            b_str = f"Today's net balance was {balance:+.0f}." if isinstance(balance, (int, float)) else f"Today's net balance: {balance}."
        else:
            b_str = "Today's data is being tallied."
        return {
            "updated_narrative": f"{b_str} The pattern from today will be reflected in tomorrow's plan.",
            "tomorrow_seed":     "Start tomorrow with a baseline check before committing to intensity.",
        }
    # Generic
    return {"summary": "Check-in noted.", "action": "Resume your plan tomorrow."}




class CoachService:
    """
    Stateless service — one instance per app, shared across requests.
    Inject `llm_client=None` for offline / test mode.
    """

    def __init__(self, llm_client: Optional[Any] = None) -> None:
        self._llm = llm_client

    # ── Public trigger methods ─────────────────────────────────────────────────

    def post_session(
        self,
        fingerprint:        PersonalFingerprint,
        profile:            NSHealthProfile,
        outcome:            SessionOutcome,
        *,
        user_name:          str = "there",
        habit_signals:      Optional[list[HabitSignal]] = None,
        sessions_this_week: int = 0,
        stress_score:       Optional[int] = None,
        recovery_score:     Optional[int] = None,
        psych_insight:      Optional[str] = None,
    ) -> dict:
        prescription = self._prescription(profile, habit_signals or [])
        milestone    = detect_milestone(profile, fingerprint)
        tone         = select_tone(profile, milestone_detected=milestone is not None)

        extra_signals: list[str] = []

        session_data = {
            "score":         outcome.session_score,
            "coherence_avg": outcome.coherence_avg,
            "coherence_peak": outcome.coherence_peak,
            "zone_time_pct": {
                "z1": outcome.zone_1_seconds,
                "z2": outcome.zone_2_seconds,
                "z3": outcome.zone_3_seconds,
                "z4": outcome.zone_4_seconds,
            },
            "rmssd_pre_ms":  outcome.rmssd_pre_ms,
            "rmssd_post_ms": outcome.rmssd_post_ms,
            "arc_completed": outcome.arc_completed,
            "practice_type": outcome.practice_type,
        }

        ctx = build_coach_context(
            profile,
            fingerprint,
            trigger_type="post_session",
            tone=tone,
            prescription=prescription,
            user_name=user_name,
            habit_signals=habit_signals,
            sessions_this_week=sessions_this_week,
            milestone=milestone.label if milestone else None,
            milestone_evidence=milestone.evidence if milestone else None,
            session_data=session_data,
            extracted_signals=extra_signals if extra_signals else None,
            stress_score=stress_score,
            recovery_score=recovery_score,
            psych_insight=psych_insight,
        )
        return generate_response(ctx, profile, llm_client=self._llm)

    def morning_brief(
        self,
        fingerprint:        PersonalFingerprint,
        profile:            NSHealthProfile,
        *,
        user_name:          str = "there",
        habit_signals:      Optional[list[HabitSignal]] = None,
        sessions_this_week: int = 0,
        stress_score:       Optional[int] = None,
        recovery_score:     Optional[int] = None,
        psych_insight:      Optional[str] = None,
        net_balance:        Optional[float] = None,
    ) -> dict:
        """On-demand morning brief via standard coach pipeline (tests + tooling)."""
        prescription = self._prescription(profile, habit_signals or [])
        milestone    = detect_milestone(profile, fingerprint)
        tone         = select_tone(profile, milestone_detected=milestone is not None)

        ctx = build_coach_context(
            profile,
            fingerprint,
            trigger_type="morning_brief",
            tone=tone,
            prescription=prescription,
            user_name=user_name,
            habit_signals=habit_signals,
            sessions_this_week=sessions_this_week,
            milestone=milestone.label if milestone else None,
            milestone_evidence=milestone.evidence if milestone else None,
            stress_score=stress_score,
            recovery_score=recovery_score,
            psych_insight=psych_insight,
            net_balance=net_balance,
        )
        return generate_response(ctx, profile, llm_client=self._llm)

    def nudge(
        self,
        fingerprint:   PersonalFingerprint,
        profile:       NSHealthProfile,
        *,
        user_name:     str = "there",
        habit_signals: Optional[list[HabitSignal]] = None,
        stress_score:    Optional[int] = None,
        recovery_score:  Optional[int] = None,
        psych_insight:   Optional[str] = None,
    ) -> dict:
        prescription = self._prescription(profile, habit_signals or [])
        tone         = select_tone(profile)

        extra_signals: list[str] = []

        ctx = build_coach_context(
            profile,
            fingerprint,
            trigger_type="nudge",
            tone=tone,
            prescription=prescription,
            user_name=user_name,
            habit_signals=habit_signals,
            extracted_signals=extra_signals if extra_signals else None,
            stress_score=stress_score,
            recovery_score=recovery_score,
            psych_insight=psych_insight,
        )
        return generate_response(ctx, profile, llm_client=self._llm)

    def weekly_review(
        self,
        fingerprint:        PersonalFingerprint,
        profile:            NSHealthProfile,
        *,
        user_name:          str = "there",
        sessions_this_week: int = 0,
    ) -> dict:
        prescription = self._prescription(profile, [])
        milestone    = detect_milestone(profile, fingerprint)
        tone         = select_tone(profile, milestone_detected=milestone is not None)

        extra_signals: list[str] = []

        ctx = build_coach_context(
            profile,
            fingerprint,
            trigger_type="weekly_review",
            tone=tone,
            prescription=prescription,
            user_name=user_name,
            sessions_this_week=sessions_this_week,
            milestone=milestone.label if milestone else None,
            milestone_evidence=milestone.evidence if milestone else None,
            extracted_signals=extra_signals if extra_signals else None,
        )
        return generate_response(ctx, profile, llm_client=self._llm)

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _prescription(
        self,
        profile:  NSHealthProfile,
        signals:  list[HabitSignal],
    ) -> DailyPrescription:
        return compute_daily_prescription(profile, habit_signals=signals)

    # ── Phase 5 assembled-context triggers ───────────────────────────────────
    # These bypasses CoachContext / prompt_templates and build minimal inline
    # prompts from AssembledContext — appropriate for data synthesis triggers
    # that do not require a prescription or fingerprint.

    def evening_checkin(
        self,
        assembled: "AssembledContext",
        *,
        user_name: str = "there",
    ) -> dict:
        """
        Synthesise today's physio trajectory into a brief evening check-in.

        Returns dict with keys: day_summary, tonight_priority, trend_note.
        """
        return _run_assembled_trigger(
            assembled,
            trigger_type="evening_checkin",
            llm_client=self._llm,
            system_prompt=_EVENING_CHECKIN_SYSTEM,
            user_name=user_name,
        )

    def night_closure(
        self,
        assembled: "AssembledContext",
        *,
        user_name: str = "there",
    ) -> dict:
        """
        Generate a tomorrow seed and updated narrative for the morning brief.

        Returns dict with keys: updated_narrative, tomorrow_seed.
        """
        return _run_assembled_trigger(
            assembled,
            trigger_type="night_closure",
            llm_client=self._llm,
            system_prompt=_NIGHT_CLOSURE_SYSTEM,
            user_name=user_name,
        )
