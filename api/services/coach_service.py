"""
api/services/coach_service.py

Assembles coaching context and generates coaching output for all trigger types.

Trigger types handled
---------------------
    "morning_brief"    — first screen of the day
    "post_session"     — immediately after a session ends
    "nudge"            — mid-day motivational / reminder
    "weekly_review"    — end-of-week synthesis

All calls are synchronous wrappers around the coach layer.
The LLM client is injected so the service can run in offline mode during tests.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

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
from coach.assessor import (
    UserAssessment,
    SessionRecord,
    ReadinessRecord,
    DeviationRecord,
    ConversationSignal,
    assess_user,
)
from coach.prescriber import DailyPlan, plan_to_items_json, build_daily_plan_from_uup
from model.baseline_builder import PersonalFingerprint
from outcomes.session_outcomes import SessionOutcome

logger = logging.getLogger(__name__)


class CoachService:
    """
    Stateless service — one instance per app, shared across requests.
    Inject `llm_client=None` for offline / test mode.
    """

    def __init__(self, llm_client: Optional[Any] = None) -> None:
        self._llm = llm_client

    # ── Public trigger methods ─────────────────────────────────────────────────

    def morning_brief(
        self,
        fingerprint:           PersonalFingerprint,
        profile:               NSHealthProfile,
        *,
        user_name:             str = "there",
        morning_rmssd_ms:      Optional[float] = None,
        habit_signals:         Optional[list[HabitSignal]] = None,
        sessions_this_week:    int = 0,
        last_session_ago_days: Optional[int] = None,
        consecutive_low_reads: int = 0,
        assessment:            Optional[UserAssessment] = None,
        daily_plan:            Optional[DailyPlan] = None,
        readiness_score:       Optional[int] = None,
        stress_score:          Optional[int] = None,
        recovery_score:        Optional[int] = None,
        psych_insight:         Optional[str] = None,
        unified_profile:       Optional[Any] = None,
        uup_narrative:         Optional[str] = None,
        user_facts:            Optional[list[str]] = None,
        engagement_tier:       Optional[str] = None,
    ) -> dict:
        # ── Prescription: prefer UUP plan if available for today ──────────────
        effective_daily_plan = daily_plan
        if unified_profile is not None and daily_plan is None:
            uup_plan = build_daily_plan_from_uup(
                unified_profile,
                readiness_score=float(readiness_score or 50),
                stage=getattr(profile, "stage", 1),
            )
            if uup_plan is not None:
                effective_daily_plan = uup_plan

        # Pull UUP narrative / facts / engagement if not explicitly provided
        if unified_profile is not None:
            if uup_narrative is None:
                uup_narrative = getattr(unified_profile, "coach_narrative", None)
            if engagement_tier is None:
                eng = getattr(unified_profile, "engagement", None)
                if eng:
                    engagement_tier = getattr(eng, "engagement_tier", None)
            if user_facts is None:
                facts = getattr(unified_profile, "user_facts", [])
                user_facts = [f.fact_text for f in facts] if facts else []

        prescription = self._prescription(profile, habit_signals or [])
        milestone    = detect_milestone(profile, fingerprint)
        tone         = select_tone(
            profile,
            milestone_detected=milestone is not None,
            consecutive_low_reads=consecutive_low_reads,
        )

        extra_signals: list[str] = []
        if assessment is not None:
            extra_signals.append(f"assessment: {assessment.summary_note}")
            if assessment.level_gate.ready:
                extra_signals.append(
                    f"level_gate: ready to advance to stage {assessment.level_gate.next_stage}"
                )
            if assessment.recurring_deviations:
                extra_signals.append(
                    f"recurring_skips: {', '.join(assessment.recurring_deviations)}"
                )
        if effective_daily_plan is not None:
            must_do_labels = [item.display for item in effective_daily_plan.must_do]
            if must_do_labels:
                extra_signals.append(f"today_must_do: {', '.join(must_do_labels)}")

        ctx = build_coach_context(
            profile,
            fingerprint,
            trigger_type="morning_brief",
            tone=tone,
            prescription=prescription,
            user_name=user_name,
            morning_rmssd_ms=morning_rmssd_ms,
            habit_signals=habit_signals,
            consecutive_low_reads=consecutive_low_reads,
            sessions_this_week=sessions_this_week,
            last_session_ago_days=last_session_ago_days,
            milestone=milestone.label if milestone else None,
            milestone_evidence=milestone.evidence if milestone else None,
            extracted_signals=extra_signals if extra_signals else None,
            readiness_score=readiness_score,
            stress_score=stress_score,
            recovery_score=recovery_score,
            psych_insight=psych_insight,
            uup_narrative=uup_narrative,
            user_facts=user_facts,
            engagement_tier=engagement_tier,
        )
        return generate_response(ctx, profile, llm_client=self._llm)

    def post_session(
        self,
        fingerprint:        PersonalFingerprint,
        profile:            NSHealthProfile,
        outcome:            SessionOutcome,
        *,
        user_name:          str = "there",
        habit_signals:      Optional[list[HabitSignal]] = None,
        sessions_this_week: int = 0,
        assessment:         Optional[UserAssessment] = None,
        readiness_score:    Optional[int] = None,
        stress_score:       Optional[int] = None,
        recovery_score:     Optional[int] = None,
        psych_insight:      Optional[str] = None,
    ) -> dict:
        prescription = self._prescription(profile, habit_signals or [])
        milestone    = detect_milestone(profile, fingerprint)
        tone         = select_tone(profile, milestone_detected=milestone is not None)

        extra_signals: list[str] = []
        if assessment is not None:
            extra_signals.append(f"assessment: {assessment.summary_note}")

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
            readiness_score=readiness_score,
            stress_score=stress_score,
            recovery_score=recovery_score,
            psych_insight=psych_insight,
        )
        return generate_response(ctx, profile, llm_client=self._llm)

    def nudge(
        self,
        fingerprint:   PersonalFingerprint,
        profile:       NSHealthProfile,
        *,
        user_name:     str = "there",
        habit_signals: Optional[list[HabitSignal]] = None,
        assessment:    Optional[UserAssessment] = None,
        readiness_score: Optional[int] = None,
        stress_score:    Optional[int] = None,
        recovery_score:  Optional[int] = None,
        psych_insight:   Optional[str] = None,
    ) -> dict:
        prescription = self._prescription(profile, habit_signals or [])
        tone         = select_tone(profile)

        extra_signals: list[str] = []
        if assessment is not None:
            extra_signals.append(f"assessment: {assessment.summary_note}")

        ctx = build_coach_context(
            profile,
            fingerprint,
            trigger_type="nudge",
            tone=tone,
            prescription=prescription,
            user_name=user_name,
            habit_signals=habit_signals,
            extracted_signals=extra_signals if extra_signals else None,
            readiness_score=readiness_score,
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
        assessment:         Optional[UserAssessment] = None,
    ) -> dict:
        prescription = self._prescription(profile, [])
        milestone    = detect_milestone(profile, fingerprint)
        tone         = select_tone(profile, milestone_detected=milestone is not None)

        extra_signals: list[str] = []
        if assessment is not None:
            extra_signals.append(f"assessment: {assessment.summary_note}")
            extra_signals.append(f"learning_state: {assessment.learning_state}")
            if assessment.level_gate.ready:
                extra_signals.append(
                    f"level_gate: ready to advance to stage {assessment.level_gate.next_stage}"
                )

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

    # ── Assessment helper ──────────────────────────────────────────────────────

    @staticmethod
    def build_assessment(
        current_stage: int,
        session_records: list[SessionRecord],
        readiness_records: list[ReadinessRecord],
        deviation_records: Optional[list[DeviationRecord]] = None,
        conversation_signals: Optional[list[ConversationSignal]] = None,
        sport_stressor_slugs: Optional[list[str]] = None,
    ) -> UserAssessment:
        """
        Run the 3-gate assessor and return a full UserAssessment.

        All inputs are plain dataclass types — no DB handles needed.
        Callers (routers/background tasks) are responsible for loading data.
        """
        return assess_user(
            current_stage=current_stage,
            session_records=session_records,
            readiness_records=readiness_records,
            deviation_records=deviation_records,
            conversation_signals=conversation_signals,
            sport_stressors=sport_stressor_slugs,
        )

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _prescription(
        self,
        profile:  NSHealthProfile,
        signals:  list[HabitSignal],
    ) -> DailyPrescription:
        return compute_daily_prescription(profile, habit_signals=signals)
