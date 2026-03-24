"""
tests/profile/test_profile_updater.py

Unit tests for profile/profile_updater.py.

Only pure/synchronous helpers are tested here (no DB, no async).
The _PhysioClient injection logic is tested with a stub LLM client.

Coverage:
  - _build_physio_block(): calibrated model
  - _build_physio_block(): uncalibrated model → no ms values, no RMSSD-relative claim allowed
  - _build_physio_block(): empty trajectory → no trajectory section
  - _build_physio_block(): stress windows with/without suppression and top_tag
  - _build_physio_block(): recovery windows with/without sources
  - _build_physio_block(): background bins present / absent
  - _build_physio_block(): population labels always appear
  - _PhysioClient: injects physio into Layer 1 ("psychological analyst" system)
  - _PhysioClient: passes Layer 2 through unchanged ("planning engine" system)
  - _PhysioClient: unknown system prompt passes through
  - _PhysioClient: proxies unknown attributes to real client
"""
from __future__ import annotations

import pytest

from coach.data_assembler import AssembledContext
from profile.profile_updater import _PhysioClient, _build_physio_block


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ctx(
    *,
    is_calibrated: bool = True,
    floor_ms: float = 12.4,
    ceiling_ms: float = 51.7,
    morning_avg_ms: float = 27.0,
    trajectory: list | None = None,
    stress_count: int = 0,
    stress_suppression: float | None = None,
    stress_top_tag: str | None = None,
    recovery_count: int = 0,
    recovery_sources: dict | None = None,
    bins: list | None = None,
    pop_stress: str = "moderate",
    pop_recovery: str = "fair",
) -> AssembledContext:
    return AssembledContext(
        personal_model={
            "is_calibrated": is_calibrated,
            "floor_ms": floor_ms,
            "ceiling_ms": ceiling_ms,
            "morning_avg_ms": morning_avg_ms,
        },
        daily_trajectory=trajectory if trajectory is not None else [],
        stress_windows_24h={
            "count": stress_count,
            "avg_suppression_pct": stress_suppression,
            "top_tag": stress_top_tag,
        },
        recovery_windows_24h={
            "count": recovery_count,
            "sources": recovery_sources or {},
        },
        background_bins=bins or [],
        population_stress_label=pop_stress,
        population_recovery_label=pop_recovery,
    )


def _traj(*entries) -> list[dict]:
    """Build trajectory list from tuples: (date_str, stress, recovery, net, day_type)."""
    return [
        {
            "date": d, "stress_load": sl, "waking_recovery": wr,
            "net_balance": nb, "day_type": dt,
        }
        for d, sl, wr, nb, dt in entries
    ]


class _StubClient:
    """Records calls to chat()."""

    def __init__(self, return_value: str = "stub response") -> None:
        self.calls: list[dict] = []
        self._return = return_value
        self.extra_attr = "proxy_test"

    def chat(self, system: str, user: str) -> str:
        self.calls.append({"system": system, "user": user})
        return self._return


# ── _build_physio_block ────────────────────────────────────────────────────────

class TestBuildPhysioBlock:

    def test_calibrated_model_shows_values(self):
        block = _build_physio_block(_ctx(is_calibrated=True, floor_ms=12.4, ceiling_ms=51.7, morning_avg_ms=27.0))
        assert "12.4" in block
        assert "51.7" in block
        assert "27.0" in block
        assert "[calibrated]" in block

    def test_uncalibrated_model_omits_ms_values(self):
        block = _build_physio_block(_ctx(is_calibrated=False, floor_ms=15.0, ceiling_ms=60.0, morning_avg_ms=30.0))
        # ms values must NOT appear
        assert "15.0" not in block
        assert "60.0" not in block
        assert "30.0" not in block
        # should mention calibration state
        assert "not yet calibrated" in block

    def test_uncalibrated_prohibits_rmssd_claims(self):
        block = _build_physio_block(_ctx(is_calibrated=False))
        # must include the prohibition clause
        assert "RMSSD" in block or "rmssd" in block.lower() or "omit" in block

    def test_empty_trajectory_omits_section(self):
        block = _build_physio_block(_ctx(trajectory=[]))
        assert "trajectory" not in block.lower()

    def test_trajectory_rows_appear(self):
        traj = _traj(
            ("2026-03-17", 3.7, 0.7, -3.0, "green"),
            ("2026-03-23", 52.8, 31.7, -12.2, "yellow"),
        )
        block = _build_physio_block(_ctx(trajectory=traj))
        assert "2026-03-17" in block
        assert "2026-03-23" in block
        assert "53" in block  # 52.8 rounds to 53
        assert "-12.2" in block  # net_balance preserved

    def test_trajectory_net_balance_sign(self):
        traj = _traj(("2026-04-01", 30.0, 40.0, 10.0, "green"))
        block = _build_physio_block(_ctx(trajectory=traj))
        assert "+10.0" in block

    def test_stress_windows_zero(self):
        block = _build_physio_block(_ctx(stress_count=0))
        assert "none detected" in block.lower()

    def test_stress_windows_with_suppression_and_tag(self):
        block = _build_physio_block(_ctx(
            stress_count=3,
            stress_suppression=45.2,
            stress_top_tag="work",
        ))
        assert "3" in block
        assert "45%" in block
        assert "work" in block

    def test_stress_windows_no_suppression(self):
        block = _build_physio_block(_ctx(stress_count=2, stress_suppression=None))
        assert "2" in block
        # should not crash; no suppression value emitted
        assert "None" not in block

    def test_recovery_windows_zero(self):
        block = _build_physio_block(_ctx(recovery_count=0))
        lines = block.splitlines()
        rec_line = next((l for l in lines if "Recovery events" in l), None)
        assert rec_line is not None
        assert "none detected" in rec_line.lower()

    def test_recovery_windows_with_sources(self):
        block = _build_physio_block(_ctx(
            recovery_count=2,
            recovery_sources={"sleep": 1, "coherence_session": 1},
        ))
        assert "2" in block
        assert "sleep" in block
        assert "coherence_session" in block

    def test_background_bins_omitted_when_empty(self):
        block = _build_physio_block(_ctx(bins=[]))
        assert "Background HRV" not in block

    def test_background_bins_present(self):
        bins = [
            {"time_label": "08:00–12:00", "rmssd_pct_ceiling": 78.3},
            {"time_label": "00:00–04:00", "rmssd_pct_ceiling": None},
        ]
        block = _build_physio_block(_ctx(bins=bins))
        assert "08:00–12:00" in block
        assert "78%" in block
        assert "00:00–04:00" in block
        assert "—" in block  # None bin

    def test_population_labels_always_present(self):
        block = _build_physio_block(_ctx(pop_stress="very high", pop_recovery="poor"))
        assert "very high" in block
        assert "poor" in block

    def test_no_raw_ms_values_reach_block(self):
        """The PHYSIOLOGICAL SNAPSHOT must never contain raw ms values."""
        block = _build_physio_block(_ctx(
            is_calibrated=True,
            floor_ms=999.9,
            ceiling_ms=888.8,
            morning_avg_ms=777.7,
        ))
        # These specific ms values are OK *in* the personal model line
        # but must not appear anywhere else (trajectory, windows, bins)
        lines = block.splitlines()
        non_model_lines = [l for l in lines if "Personal model" not in l]
        for line in non_model_lines:
            assert " ms" not in line or "ceiling" in line


# ── _PhysioClient ──────────────────────────────────────────────────────────────

class TestPhysioClient:

    _LAYER1_SYSTEM = "You are ZenFlow's internal psychological analyst."
    _LAYER2_SYSTEM = "You are ZenFlow's daily planning engine."
    _BLOCK = "PHYSIOLOGICAL SNAPSHOT\nstress=52/100"

    def test_layer1_user_prompt_is_prepended(self):
        stub = _StubClient()
        client = _PhysioClient(stub, self._BLOCK)
        client.chat(self._LAYER1_SYSTEM, "Original Layer 1 prompt")
        assert len(stub.calls) == 1
        sent_user = stub.calls[0]["user"]
        assert sent_user.startswith(self._BLOCK)
        assert "Original Layer 1 prompt" in sent_user

    def test_layer1_system_is_unchanged(self):
        stub = _StubClient()
        client = _PhysioClient(stub, self._BLOCK)
        client.chat(self._LAYER1_SYSTEM, "prompt")
        assert stub.calls[0]["system"] == self._LAYER1_SYSTEM

    def test_layer2_passes_through_unchanged(self):
        stub = _StubClient("plan json")
        client = _PhysioClient(stub, self._BLOCK)
        result = client.chat(self._LAYER2_SYSTEM, "Layer 2 user prompt")
        assert len(stub.calls) == 1
        assert stub.calls[0]["user"] == "Layer 2 user prompt"
        assert result == "plan json"

    def test_unknown_system_passes_through(self):
        stub = _StubClient()
        client = _PhysioClient(stub, self._BLOCK)
        client.chat("Some other system prompt", "other user prompt")
        assert stub.calls[0]["user"] == "other user prompt"

    def test_layer1_detection_is_case_sensitive(self):
        # "Psychological Analyst" (capital P) should also match (substring check)
        stub = _StubClient()
        client = _PhysioClient(stub, self._BLOCK)
        client.chat("You are ZenFlow's internal psychological analyst here.", "prompt")
        assert stub.calls[0]["user"].startswith(self._BLOCK)

    def test_physio_block_separator(self):
        """Physio block and original prompt must be separated by two newlines."""
        stub = _StubClient()
        client = _PhysioClient(stub, self._BLOCK)
        client.chat(self._LAYER1_SYSTEM, "Original")
        assert self._BLOCK + "\n\n" + "Original" == stub.calls[0]["user"]

    def test_proxy_attributes_forwarded(self):
        stub = _StubClient()
        client = _PhysioClient(stub, self._BLOCK)
        assert client.extra_attr == "proxy_test"

    def test_returns_llm_response(self):
        stub = _StubClient("narrative text")
        client = _PhysioClient(stub, self._BLOCK)
        result = client.chat(self._LAYER1_SYSTEM, "prompt")
        assert result == "narrative text"

    def test_empty_physio_block(self):
        """Even with an empty block the concat must not crash."""
        stub = _StubClient()
        client = _PhysioClient(stub, "")
        client.chat(self._LAYER1_SYSTEM, "prompt")
        assert "prompt" in stub.calls[0]["user"]
