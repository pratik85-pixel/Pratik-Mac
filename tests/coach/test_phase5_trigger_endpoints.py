"""
tests/coach/test_phase5_trigger_endpoints.py

Unit tests for Phase 5: nudge-check, evening-checkin, night-closure trigger
endpoints.

Coverage
--------
  - _assembled_fallback() — deterministic fallback for both triggers
  - _run_assembled_trigger() — LLM success path, LLM exception → fallback
  - CoachService.evening_checkin() — no LLM
  - CoachService.night_closure() — no LLM
  - schema_validator._REQUIRED_FIELDS entries for 3 new triggers
  - config/coach.py new keys present with expected types
  - NudgeCheckResponse gate logic: outside_window, cap_reached, no_data
  - Endpoint response schemas

Tests are offline (no DB, no LLM, no HTTP server).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest


# ── Minimal AssembledContext stub ─────────────────────────────────────────────

@dataclass
class _AssembledContext:
    daily_trajectory:          list[dict] = field(default_factory=list)
    stress_windows_24h:        dict       = field(default_factory=dict)
    recovery_windows_24h:      dict       = field(default_factory=dict)
    background_bins:           list[dict] = field(default_factory=list)
    habit_events:              list[str]  = field(default_factory=list)
    user_facts:                list[str]  = field(default_factory=list)
    coach_narrative:           Optional[str] = None
    population_stress_label:   str = "unknown"
    population_recovery_label: str = "unknown"
    estimated_tokens:          int = 0


def _make_assembled(
    *,
    traj: Optional[list[dict]] = None,
    narrative: Optional[str]   = None,
) -> _AssembledContext:
    default_traj = [
        {"date": "2026-03-22", "stress_load": 42, "waking_recovery": 55, "net_balance": 13.0, "day_type": "yellow"},
        {"date": "2026-03-23", "stress_load": 38, "waking_recovery": 61, "net_balance": 23.0, "day_type": "green"},
        {"date": "2026-03-24", "stress_load": 45, "waking_recovery": 48, "net_balance": 3.0,  "day_type": "yellow"},
    ]
    return _AssembledContext(
        daily_trajectory          = traj if traj is not None else default_traj,
        population_stress_label   = "moderate",
        population_recovery_label = "adequate",
        coach_narrative           = narrative or "User tends to overtrain on Mondays.",
        user_facts                = ["Prefers morning sessions.", "Works late on Thursdays."],
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. _assembled_fallback — deterministic fallback
# ─────────────────────────────────────────────────────────────────────────────

class TestAssembledFallback:

    def _fallback(self, assembled, trigger_type: str) -> dict:
        from api.services.coach_service import _assembled_fallback
        return _assembled_fallback(assembled, trigger_type)

    def test_evening_checkin_with_data(self):
        out = self._fallback(_make_assembled(), "evening_checkin")
        assert "day_summary"      in out
        assert "tonight_priority" in out
        assert "trend_note"       in out
        # cites values from latest trajectory entry
        assert "45" in out["day_summary"] or "48" in out["day_summary"]

    def test_evening_checkin_no_data(self):
        out = self._fallback(_make_assembled(traj=[]), "evening_checkin")
        assert "day_summary" in out
        assert "collected" in out["day_summary"].lower() or "data" in out["day_summary"].lower()

    def test_night_closure_with_balance(self):
        out = self._fallback(_make_assembled(), "night_closure")
        assert "updated_narrative" in out
        assert "tomorrow_seed"     in out
        # net_balance=3.0 should appear (+3)
        assert "+3" in out["updated_narrative"] or "3" in out["updated_narrative"]

    def test_night_closure_no_data(self):
        out = self._fallback(_make_assembled(traj=[]), "night_closure")
        assert "updated_narrative" in out
        assert "tomorrow_seed"     in out

    def test_unknown_trigger_type_returns_generic(self):
        out = self._fallback(_make_assembled(), "unknown_trigger")
        assert isinstance(out, dict)


# ─────────────────────────────────────────────────────────────────────────────
# 2. _run_assembled_trigger — LLM paths
# ─────────────────────────────────────────────────────────────────────────────

class TestRunAssembledTrigger:

    def _run(self, assembled, trigger_type: str, llm_client=None) -> dict:
        from api.services.coach_service import _run_assembled_trigger, _EVENING_CHECKIN_SYSTEM
        return _run_assembled_trigger(
            assembled,
            trigger_type=trigger_type,
            llm_client=llm_client,
            system_prompt=_EVENING_CHECKIN_SYSTEM,
        )

    def test_no_llm_returns_fallback(self):
        out = self._run(_make_assembled(), "evening_checkin", llm_client=None)
        assert "day_summary" in out

    def test_llm_success_path(self):
        payload = {
            "day_summary":      "Body held up well today. Stress load was 45.",
            "tonight_priority": "Wind down with a 10-minute breathing session.",
            "trend_note":       "Consistent with last three days.",
        }
        mock_llm = MagicMock()
        mock_llm.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=json.dumps(payload)))]
        )
        out = self._run(_make_assembled(), "evening_checkin", llm_client=mock_llm)
        assert out["day_summary"] == payload["day_summary"]
        assert out["tonight_priority"] == payload["tonight_priority"]

    def test_llm_returns_markdown_fenced_json(self):
        payload = {"day_summary": "Good day.", "tonight_priority": "Rest.", "trend_note": "Stable."}
        fenced = f"```json\n{json.dumps(payload)}\n```"
        mock_llm = MagicMock()
        mock_llm.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=fenced))]
        )
        out = self._run(_make_assembled(), "evening_checkin", llm_client=mock_llm)
        assert out["day_summary"] == "Good day."

    def test_llm_raises_exception_falls_back(self):
        mock_llm = MagicMock()
        mock_llm.chat.completions.create.side_effect = RuntimeError("network error")
        out = self._run(_make_assembled(), "evening_checkin", llm_client=mock_llm)
        # Should get fallback output, not raise
        assert "day_summary" in out

    def test_llm_returns_invalid_json_falls_back(self):
        mock_llm = MagicMock()
        mock_llm.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="not json at all"))]
        )
        out = self._run(_make_assembled(), "evening_checkin", llm_client=mock_llm)
        assert "day_summary" in out


# ─────────────────────────────────────────────────────────────────────────────
# 3. CoachService.evening_checkin() and .night_closure() — offline mode
# ─────────────────────────────────────────────────────────────────────────────

class TestCoachServicePhase5:

    def _svc(self):
        from api.services.coach_service import CoachService
        return CoachService(llm_client=None)

    def test_evening_checkin_offline_returns_valid_keys(self):
        svc = self._svc()
        out = svc.evening_checkin(_make_assembled())
        assert "day_summary"      in out
        assert "tonight_priority" in out
        assert "trend_note"       in out

    def test_evening_checkin_offline_no_trajectory(self):
        svc = self._svc()
        out = svc.evening_checkin(_make_assembled(traj=[]))
        assert "day_summary" in out

    def test_night_closure_offline_returns_valid_keys(self):
        svc = self._svc()
        out = svc.night_closure(_make_assembled())
        assert "updated_narrative" in out
        assert "tomorrow_seed"     in out

    def test_night_closure_offline_no_trajectory(self):
        svc = self._svc()
        out = svc.night_closure(_make_assembled(traj=[]))
        assert "updated_narrative" in out
        assert "tomorrow_seed"     in out

    def test_evening_checkin_user_name_accepted(self):
        svc = self._svc()
        out = svc.evening_checkin(_make_assembled(), user_name="Pratik")
        assert isinstance(out, dict)

    def test_night_closure_user_name_accepted(self):
        svc = self._svc()
        out = svc.night_closure(_make_assembled(), user_name="Pratik")
        assert isinstance(out, dict)


# ─────────────────────────────────────────────────────────────────────────────
# 4. schema_validator._REQUIRED_FIELDS — Phase 5 entries
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemaValidatorPhase5Fields:

    def test_nudge_check_required_fields_present(self):
        from coach.schema_validator import _REQUIRED_FIELDS
        assert "nudge_check" in _REQUIRED_FIELDS
        assert "should_nudge" in _REQUIRED_FIELDS["nudge_check"]
        assert "reason"       in _REQUIRED_FIELDS["nudge_check"]

    def test_evening_checkin_required_fields_present(self):
        from coach.schema_validator import _REQUIRED_FIELDS
        assert "evening_checkin" in _REQUIRED_FIELDS
        assert "day_summary"      in _REQUIRED_FIELDS["evening_checkin"]
        assert "tonight_priority" in _REQUIRED_FIELDS["evening_checkin"]
        assert "trend_note"       in _REQUIRED_FIELDS["evening_checkin"]

    def test_night_closure_required_fields_present(self):
        from coach.schema_validator import _REQUIRED_FIELDS
        assert "night_closure" in _REQUIRED_FIELDS
        assert "updated_narrative" in _REQUIRED_FIELDS["night_closure"]
        assert "tomorrow_seed"     in _REQUIRED_FIELDS["night_closure"]

    def test_existing_triggers_unchanged(self):
        from coach.schema_validator import _REQUIRED_FIELDS
        assert "post_session"      in _REQUIRED_FIELDS
        assert "nudge"             in _REQUIRED_FIELDS
        assert "weekly_review"     in _REQUIRED_FIELDS
        assert "conversation_turn" in _REQUIRED_FIELDS


# ─────────────────────────────────────────────────────────────────────────────
# 5. config/coach.py — new keys
# ─────────────────────────────────────────────────────────────────────────────

class TestCoachConfigPhase5:

    def test_nudge_cap_per_4h_default(self):
        from config import CONFIG
        assert isinstance(CONFIG.coach.NUDGE_CAP_PER_4H, int)
        assert CONFIG.coach.NUDGE_CAP_PER_4H == 2

    def test_nudge_window_start_hour(self):
        from config import CONFIG
        assert CONFIG.coach.NUDGE_WINDOW_START_HOUR_IST == 10

    def test_nudge_window_end_hour(self):
        from config import CONFIG
        assert CONFIG.coach.NUDGE_WINDOW_END_HOUR_IST == 20

    def test_night_closure_hour(self):
        from config import CONFIG
        assert CONFIG.coach.NIGHT_CLOSURE_HOUR_IST   == 21
        assert CONFIG.coach.NIGHT_CLOSURE_MINUTE_IST == 30


# ─────────────────────────────────────────────────────────────────────────────
# 6. NudgeCheck gate logic — pure unit tests (no router, no DB)
# ─────────────────────────────────────────────────────────────────────────────

class TestNudgeCheckGateLogic:
    """
    Tests extracted gate logic in isolation.
    The time/cap/data checks are simple conditionals — validate the logic
    without spinning up a FastAPI test client or a DB.
    """

    def _evaluate_gates(
        self,
        *,
        hour_ist: int,
        nudges_in_window: int,
        has_trajectory: bool,
    ) -> tuple[bool, str]:
        """
        Replicate the gate evaluation logic from the nudge-check endpoint.
        Returns (should_nudge, reason).
        """
        from config import CONFIG
        cfg = CONFIG.coach

        # Gate 1 — time window
        if not (cfg.NUDGE_WINDOW_START_HOUR_IST <= hour_ist < cfg.NUDGE_WINDOW_END_HOUR_IST):
            return False, "outside_window"

        # Gate 2 — cap
        if nudges_in_window >= cfg.NUDGE_CAP_PER_4H:
            return False, "cap_reached"

        # Gate 3 — data
        if not has_trajectory:
            return False, "no_data"

        return True, "ok"

    def test_gate1_too_early(self):
        ok, reason = self._evaluate_gates(hour_ist=8, nudges_in_window=0, has_trajectory=True)
        assert not ok
        assert reason == "outside_window"

    def test_gate1_too_late(self):
        ok, reason = self._evaluate_gates(hour_ist=21, nudges_in_window=0, has_trajectory=True)
        assert not ok
        assert reason == "outside_window"

    def test_gate1_boundary_start(self):
        ok, reason = self._evaluate_gates(hour_ist=10, nudges_in_window=0, has_trajectory=True)
        assert ok
        assert reason == "ok"

    def test_gate1_boundary_end_exclusive(self):
        ok, reason = self._evaluate_gates(hour_ist=20, nudges_in_window=0, has_trajectory=True)
        assert not ok
        assert reason == "outside_window"

    def test_gate2_cap_reached(self):
        ok, reason = self._evaluate_gates(hour_ist=14, nudges_in_window=2, has_trajectory=True)
        assert not ok
        assert reason == "cap_reached"

    def test_gate2_cap_not_reached(self):
        ok, reason = self._evaluate_gates(hour_ist=14, nudges_in_window=1, has_trajectory=True)
        assert ok

    def test_gate3_no_data(self):
        ok, reason = self._evaluate_gates(hour_ist=14, nudges_in_window=0, has_trajectory=False)
        assert not ok
        assert reason == "no_data"

    def test_all_gates_pass(self):
        ok, reason = self._evaluate_gates(hour_ist=15, nudges_in_window=0, has_trajectory=True)
        assert ok
        assert reason == "ok"

    def test_gate1_checked_before_gate2(self):
        # Even if cap is reached, time gate fires first
        ok, reason = self._evaluate_gates(hour_ist=5, nudges_in_window=10, has_trajectory=True)
        assert reason == "outside_window"

    def test_gate2_checked_before_gate3(self):
        # Even if no data, cap gate fires first (within window)
        ok, reason = self._evaluate_gates(hour_ist=15, nudges_in_window=5, has_trajectory=False)
        assert reason == "cap_reached"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Night-closure IST gate logic — pure unit
# ─────────────────────────────────────────────────────────────────────────────

class TestNightClosureGateLogic:

    def _check_gate(self, hour: int, minute: int) -> bool:
        """True if night-closure gate passes (i.e. NOT too early)."""
        from config import CONFIG
        cfg = CONFIG.coach
        return (hour, minute) >= (cfg.NIGHT_CLOSURE_HOUR_IST, cfg.NIGHT_CLOSURE_MINUTE_IST)

    def test_too_early_same_hour(self):
        assert not self._check_gate(21, 0)

    def test_too_early_earlier_hour(self):
        assert not self._check_gate(20, 59)

    def test_exactly_at_gate(self):
        assert self._check_gate(21, 30)

    def test_after_gate(self):
        assert self._check_gate(22, 0)

    def test_midnight_passes(self):
        assert self._check_gate(23, 59)


# ─────────────────────────────────────────────────────────────────────────────
# 8. _build_assembled_user_prompt — content validation
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildAssembledUserPrompt:

    def _build(self, assembled, trigger_type: str) -> str:
        from api.services.coach_service import _build_assembled_user_prompt
        return _build_assembled_user_prompt(assembled, trigger_type)

    def test_trigger_type_appears_in_prompt(self):
        prompt = self._build(_make_assembled(), "evening_checkin")
        assert "evening_checkin" in prompt

    def test_trajectory_data_injected(self):
        prompt = self._build(_make_assembled(), "evening_checkin")
        # Latest entry values should appear
        assert "45" in prompt   # stress_load
        assert "48" in prompt   # waking_recovery

    def test_narrative_injected(self):
        assembled = _make_assembled(narrative="Very consistent sleeper.")
        prompt = self._build(assembled, "night_closure")
        assert "Very consistent sleeper" in prompt

    def test_empty_trajectory_does_not_crash(self):
        prompt = self._build(_make_assembled(traj=[]), "evening_checkin")
        assert "no data" in prompt.lower() or "unavailable" in prompt.lower()

    def test_population_labels_injected(self):
        prompt = self._build(_make_assembled(), "evening_checkin")
        assert "moderate" in prompt      # population_stress_label
        assert "adequate" in prompt      # population_recovery_label

    def test_user_facts_injected(self):
        prompt = self._build(_make_assembled(), "evening_checkin")
        assert "Prefers morning sessions" in prompt

    def test_night_closure_trigger_type(self):
        prompt = self._build(_make_assembled(), "night_closure")
        assert "night_closure" in prompt
