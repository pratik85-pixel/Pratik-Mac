from __future__ import annotations

import uuid

from coach.input_builder import CoachInputPacket
from coach.prompt_templates import (
    build_layer3_morning_brief_prompt,
    build_layer3_plan_brief_prompt,
    build_layer3_yesterday_summary_prompt,
)


def _packet_with_today_and_yesterday() -> CoachInputPacket:
    return CoachInputPacket(
        user_id=str(uuid.uuid4()),
        today_local_date="2026-03-31",
        daily_trajectory=[
            {
                "date": "2026-03-30",
                "day_type": "yellow",
                "readiness_score": 66.0,
                "waking_recovery_score": 80.0,
                "sleep_recovery_score": 70.0,
                "stress_load_score": 4.0,
                "adherence_pct": 60.0,
            },
            {
                "date": "2026-03-31",
                "day_type": "green",
                "readiness_score": 86.0,
                "waking_recovery_score": None,
                "sleep_recovery_score": None,
                "stress_load_score": None,
                "adherence_pct": None,
            },
        ],
        plan_deviations_30d=[],
        adherence_30d={},
    )


def test_layer3_morning_brief_prompt_has_week_context_and_no_intraday() -> None:
    _, user_prompt = build_layer3_morning_brief_prompt(_packet_with_today_and_yesterday(), "narrative")
    assert "WEEK_CONTEXT_7D" in user_prompt
    assert "Do NOT mention intraday/live numbers" in user_prompt
    assert "readiness_score" in user_prompt
    assert '"day_state": "green"|"yellow"|"relaxed"|"red"' in user_prompt


def test_layer3_plan_brief_prompt_has_yesterday_context_and_readiness_allowed() -> None:
    packet = _packet_with_today_and_yesterday()
    _, user_prompt = build_layer3_plan_brief_prompt(
        packet,
        "narrative",
        plan_items=[{"title": "Gym", "activity_type_slug": "sports"}],
    )
    assert "MORNING CONTEXT" in user_prompt
    assert "Do NOT mention intraday/live numbers" in user_prompt
    assert "YESTERDAY SUMMARY CONTEXT" in user_prompt
    assert "TODAY BASELINE" in user_prompt
    assert '"brief"' in user_prompt
    assert '"avoid_items"' in user_prompt


def test_layer3_yesterday_summary_prompt_has_4_keys() -> None:
    _, user_prompt = build_layer3_yesterday_summary_prompt(_packet_with_today_and_yesterday(), "narrative")
    assert '"weekly_trend"' in user_prompt
    assert '"yesterday_stress"' in user_prompt
    assert '"yesterday_recovery"' in user_prompt
    assert '"yesterday_adherence"' in user_prompt

