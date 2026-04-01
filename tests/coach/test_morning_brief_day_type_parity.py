from __future__ import annotations

import uuid

from coach.input_builder import CoachInputPacket
from coach.morning_brief import (
    _expected_day_state_from_recap_summary,
    _parse_brief_json,
    _retry_and_enforce_day_state_parity,
)
from coach.prompt_templates import build_layer3_morning_brief_prompt


def _packet() -> CoachInputPacket:
    return CoachInputPacket(
        user_id=str(uuid.uuid4()),
        today_local_date="2026-03-31",
        daily_trajectory=[
            {
                "date": "2026-03-30",
                "day_type": "yellow",
                "waking_recovery_score": 80.0,
                "sleep_recovery_score": 70.0,
                "stress_load_score": 4.0,
            }
        ],
    )


def test_prompt_day_state_uses_yesterday_only_and_relaxed_enum() -> None:
    _, user_prompt = build_layer3_morning_brief_prompt(_packet(), "narrative")
    assert "YESTERDAY_ROW:" in user_prompt
    assert "TODAY_ROW:" not in user_prompt
    assert '"day_state": "green"|"yellow"|"relaxed"|"red"' in user_prompt
    assert "Determine \"day_state\" from YESTERDAY_ROW only." in user_prompt


def test_parse_brief_json_accepts_relaxed() -> None:
    raw = """{
      "day_state": "relaxed",
      "day_confidence": "high",
      "brief_text": "ok",
      "evidence": "ok",
      "one_action": "ok"
    }"""
    out = _parse_brief_json(raw)
    assert out is not None
    assert out["day_state"] == "relaxed"


def test_expected_day_state_from_recap_summary() -> None:
    summary = {
        "stress_load_score": 55.0,      # 5.5 / 10
        "waking_recovery_score": 80.0,
        "sleep_recovery_score": 70.0,
    }
    # 0.45*70 + 0.30*80 + 0.25*(10-5.5)*10 = 31.5 + 24 + 11.25 = 66.75 => yellow
    assert _expected_day_state_from_recap_summary(summary) == "yellow"


class _DummyLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls = 0

    def chat(self, _sys: str, _user: str) -> str:
        idx = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        return self._responses[idx]


def test_retry_then_autocorrect_when_mismatch_persists() -> None:
    llm = _DummyLLM(
        responses=[
            """{"day_state":"red","day_confidence":"high","brief_text":"b","evidence":"e","one_action":"a"}"""
        ]
    )
    out = _retry_and_enforce_day_state_parity(
        result={
            "day_state": "red",
            "day_confidence": "high",
            "brief_text": "b",
            "evidence": "e",
            "one_action": "a",
        },
        expected_day_state="yellow",
        llm_client=llm,
        sys_prompt="sys",
        user_prompt="user",
        user_id=uuid.uuid4(),
    )
    assert llm.calls == 1
    assert out["day_state"] == "yellow"


def test_retry_accepts_expected_day_state() -> None:
    llm = _DummyLLM(
        responses=[
            """{"day_state":"yellow","day_confidence":"medium","brief_text":"b2","evidence":"e2","one_action":"a2"}"""
        ]
    )
    out = _retry_and_enforce_day_state_parity(
        result={
            "day_state": "red",
            "day_confidence": "high",
            "brief_text": "b",
            "evidence": "e",
            "one_action": "a",
        },
        expected_day_state="yellow",
        llm_client=llm,
        sys_prompt="sys",
        user_prompt="user",
        user_id=uuid.uuid4(),
    )
    assert llm.calls == 1
    assert out["day_state"] == "yellow"
    assert out["brief_text"] == "b2"
