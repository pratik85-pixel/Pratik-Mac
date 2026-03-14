"""
model/capacity_snapshot.py

CapacitySnapshot: a frozen point-in-time calibration record.

When calibration_days reaches BASELINE_STABLE_DAYS (3), the current
rmssd_floor, rmssd_ceiling, and rmssd_morning_avg are snapshotted here
and frozen. After that, the daily summarizer uses these snapshot values
as its denominators — not the live PersonalModel fields.

Capacity grows only when:
  1. New observed range exceeds snapshot range by >= CAPACITY_GROWTH_THRESHOLD_PCT (10%)
  2. This condition holds for >= CAPACITY_GROWTH_CONFIRM_DAYS (7) consecutive days
  3. Coach fires a user notification: "Your nervous system has been building strength"
  4. A new CapacitySnapshot is created with trigger="capacity_growth"

Triggers:
  - "initial_calibration"  : first snapshot after 3+ days of wear
  - "capacity_growth"      : range grew >10% for 7+ consecutive days
  - "manual_reset"         : user/admin explicitly reset calibration
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class CapacitySnapshot:
    """
    Frozen calibration snapshot.

    All scoring denominators (ns_capacity = (ceiling - floor) x 960 min)
    are derived from these frozen values.
    """
    snapshot_id:        str           # UUID
    user_id:            str           # UUID — owner
    taken_at:           datetime      # when this snapshot was created
    version:            int           # increments with each new snapshot

    # ── Frozen baseline values ────────────────────────────────────────────────
    rmssd_floor:        float         # ms — personal minimum at snapshot time
    rmssd_ceiling:      float         # ms — personal maximum at snapshot time
    rmssd_morning_avg:  float         # ms — morning reference threshold

    # ── Derived capacity (stored for quick access) ────────────────────────────
    # ns_capacity_960 = (ceiling - floor) x 960
    # Used as the denominator for both stress% and recovery% calculations.
    ns_capacity_960:    float = 0.0

    # ── Trigger context ───────────────────────────────────────────────────────
    trigger:            str = "initial_calibration"    # see module docstring

    # ── Optional: previous snapshot for audit trail ───────────────────────────
    previous_snapshot_id: Optional[str] = None
    previous_range:       Optional[float] = None   # ceiling - floor before this update

    def __post_init__(self) -> None:
        self.ns_capacity_960 = round(
            (self.rmssd_ceiling - self.rmssd_floor) * 960.0, 2
        )

    @property
    def rmssd_range(self) -> float:
        """ceiling - floor in ms."""
        return round(self.rmssd_ceiling - self.rmssd_floor, 1)

    @classmethod
    def from_personal_model(
        cls,
        snapshot_id: str,
        user_id: str,
        rmssd_floor: float,
        rmssd_ceiling: float,
        rmssd_morning_avg: float,
        version: int,
        trigger: str = "initial_calibration",
        previous_snapshot_id: Optional[str] = None,
        previous_range: Optional[float] = None,
    ) -> "CapacitySnapshot":
        """Convenience constructor from PersonalModel fields."""
        return cls(
            snapshot_id=snapshot_id,
            user_id=user_id,
            taken_at=datetime.utcnow(),
            version=version,
            rmssd_floor=rmssd_floor,
            rmssd_ceiling=rmssd_ceiling,
            rmssd_morning_avg=rmssd_morning_avg,
            trigger=trigger,
            previous_snapshot_id=previous_snapshot_id,
            previous_range=previous_range,
        )
