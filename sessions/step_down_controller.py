"""
sessions/step_down_controller.py

Gate A / B / C logic from the OG app — decides when to step the target BPM
down and when a PRF has been confirmed.

OG app design (preserved exactly)
-----------------------------------
Gate A — BPM match:
    |detected_bpm - target_bpm| ≤ GATE_A_TOLERANCE_BPM  (default 1.5)

Gate B — Stability:
    N consecutive windows all passing Gate A
    N = GATE_B_STABILITY_WINDOWS  (default 3)

Gate C — RSA quality:
    coherence ≥ GATE_C_COHERENCE_MIN  (default 0.65, = zone 3)

PRF confirmed when all three gates pass simultaneously at the same BPM.

The original RSA_r > 0.3 threshold (correlation between accelerometer breath
wave and PPI oscillation) is fully covered by coherence ≥ 0.65 — no new
metric needed.

Usage
-----
Instantiate StepDownController at session start.
For each new analysis window call `.update()`.
Read `.should_step_down` to know when to drop target BPM.
Read `.prf_found` and `.confirmed_prf_bpm` once PRF is locked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from processing.breath_rate_estimator import BreathRateEstimate
from processing.coherence_scorer import CoherenceResult


# ── Defaults (override via CONFIG in production) ───────────────────────────────
_GATE_A_TOLERANCE_BPM    = 1.5
_GATE_B_STABILITY_WINDOWS = 3
_GATE_C_COHERENCE_MIN    = 0.65


# ── Per-window evaluation ─────────────────────────────────────────────────────

@dataclass
class GateEvaluation:
    """Result of evaluating all three gates for one analysis window."""
    target_bpm:    float
    detected_bpm:  Optional[float]
    gate_a:        bool   # BPM within tolerance
    gate_b:        bool   # sufficient consecutive gate_a passes
    gate_c:        bool   # coherence above threshold
    all_pass:      bool   # A AND B AND C
    consecutive_a: int    # running count at time of evaluation


# ── Controller ────────────────────────────────────────────────────────────────

@dataclass
class StepDownController:
    """
    Stateful controller for one step-down session.

    Parameters
    ----------
    start_bpm : float
        BPM to begin at. Typically estimated current user breathing rate, or 12.0.
    stop_bpm : float
        BPM to stop stepping at. Stored PRF if known, else 6.0.
    increment : float
        BPM to drop per step. Default 0.5.
    gate_a_tolerance : float
        Acceptable BPM deviation for Gate A.
    gate_b_windows : int
        Consecutive Gate A passes required before triggering Gate B.
    gate_c_coherence : float
        Minimum coherence for Gate C.
    """
    start_bpm:        float
    stop_bpm:         float         = 6.0
    increment:        float         = 0.5
    gate_a_tolerance: float         = _GATE_A_TOLERANCE_BPM
    gate_b_windows:   int           = _GATE_B_STABILITY_WINDOWS
    gate_c_coherence: float         = _GATE_C_COHERENCE_MIN

    # ── Runtime state (not constructor params) ────────────────────────────────
    _current_bpm:     float         = field(init=False)
    _consecutive_a:   int           = field(init=False, default=0)
    _prf_found:       bool          = field(init=False, default=False)
    _confirmed_bpm:   Optional[float] = field(init=False, default=None)
    _history:         list[GateEvaluation] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self._current_bpm   = self.start_bpm
        self._consecutive_a = 0
        self._prf_found     = False
        self._confirmed_bpm = None
        self._history       = []

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def current_bpm(self) -> float:
        """Current target BPM being paced."""
        return self._current_bpm

    @property
    def prf_found(self) -> bool:
        """True once all three gates have passed at the same BPM."""
        return self._prf_found

    @property
    def confirmed_prf_bpm(self) -> Optional[float]:
        """The confirmed PRF, or None if not yet found."""
        return self._confirmed_bpm

    @property
    def at_floor(self) -> bool:
        """True if current_bpm has reached stop_bpm."""
        return self._current_bpm <= self.stop_bpm

    @property
    def history(self) -> list[GateEvaluation]:
        return list(self._history)

    @property
    def should_step_down(self) -> bool:
        """
        True if Gate B passed on the latest window (gates A+B met, even if C
        not yet) AND we have not yet found PRF AND we are not at floor.

        Interpretation: user is stably at the current rate — drop to next step.
        Gate C passing at gate_b_windows means PRF is found (not just step-down).
        """
        if self._prf_found or self.at_floor:
            return False
        if not self._history:
            return False
        latest = self._history[-1]
        # Step down when A+B pass but C has NOT yet passed (user is at rate but 
        # not yet in resonance — keep going down)
        return latest.gate_b and not latest.gate_c

    # ── Main update ───────────────────────────────────────────────────────────

    def update(
        self,
        breath_estimate: BreathRateEstimate,
        coherence_result: CoherenceResult,
    ) -> GateEvaluation:
        """
        Evaluate gates for one analysis window and update controller state.

        Parameters
        ----------
        breath_estimate : BreathRateEstimate
            Output of estimate_breath_rate() for this window.
        coherence_result : CoherenceResult
            Output of compute_coherence() for this window.

        Returns
        -------
        GateEvaluation
            The evaluation result including all gate states.
        """
        detected_bpm = breath_estimate.bpm if breath_estimate.is_valid() else None

        # Gate A — BPM match
        gate_a = (
            detected_bpm is not None
            and abs(detected_bpm - self._current_bpm) <= self.gate_a_tolerance
        )

        # Update consecutive Gate A counter
        if gate_a:
            self._consecutive_a += 1
        else:
            self._consecutive_a = 0

        # Gate B — stability
        gate_b = self._consecutive_a >= self.gate_b_windows

        # Gate C — RSA quality
        gate_c = (
            coherence_result.is_valid()
            and coherence_result.coherence is not None
            and coherence_result.coherence >= self.gate_c_coherence
        )

        all_pass = gate_a and gate_b and gate_c

        evaluation = GateEvaluation(
            target_bpm    = self._current_bpm,
            detected_bpm  = detected_bpm,
            gate_a        = gate_a,
            gate_b        = gate_b,
            gate_c        = gate_c,
            all_pass      = all_pass,
            consecutive_a = self._consecutive_a,
        )
        self._history.append(evaluation)

        # PRF found when all three gates pass
        if all_pass and not self._prf_found:
            self._prf_found   = True
            self._confirmed_bpm = self._current_bpm

        return evaluation

    def step_down(self) -> float:
        """
        Drop target BPM by one increment.

        Should only be called when should_step_down is True.
        Resets the Gate A consecutive counter.

        Returns
        -------
        float
            New target BPM after stepping down.
        """
        new_bpm = max(self.stop_bpm, self._current_bpm - self.increment)
        self._current_bpm   = new_bpm
        self._consecutive_a = 0    # reset stability counter at new target
        return new_bpm

    def force_prf(self, bpm: float) -> None:
        """
        Manually confirm a PRF (e.g. when re-using a stored value).
        Marks the session as PRF-found immediately.
        """
        self._prf_found     = True
        self._confirmed_bpm = bpm
        self._current_bpm   = bpm
