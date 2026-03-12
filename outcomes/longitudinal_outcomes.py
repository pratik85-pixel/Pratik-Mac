from dataclasses import dataclass
from typing import List, Dict, Any

@dataclass
class LongitudinalArc:
    trend_direction: str
    stress_shift_pct: float
    recovery_shift_pct: float
    readiness_shift_pct: float

def calculate_longitudinal_arc(recent_30: List[Dict[str, Any]], previous_30: List[Dict[str, Any]]) -> LongitudinalArc:
    def avg(lst, key):
        vals = [d.get(key, 0.0) for d in lst if key in d]
        return sum(vals) / len(vals) if vals else 0.0

    r_stress = avg(recent_30, "stress")
    r_recovery = avg(recent_30, "recovery")
    r_readiness = avg(recent_30, "readiness")
    
    p_stress = avg(previous_30, "stress")
    p_recovery = avg(previous_30, "recovery")
    p_readiness = avg(previous_30, "readiness")

    s_shift = ((r_stress - p_stress) / p_stress * 100) if p_stress > 0 else 0.0
    r_shift = ((r_recovery - p_recovery) / p_recovery * 100) if p_recovery > 0 else 0.0
    rd_shift = ((r_readiness - p_readiness) / p_readiness * 100) if p_readiness > 0 else 0.0

    # Trend logic: Improving if recovery & readiness go up and stress goes down
    overall_improvement = r_shift + rd_shift - s_shift
    if overall_improvement > 5.0:
        trend = "improving"
    elif overall_improvement < -5.0:
        trend = "declining"
    else:
        trend = "stable"

    return LongitudinalArc(
        trend_direction=trend,
        stress_shift_pct=s_shift,
        recovery_shift_pct=r_shift,
        readiness_shift_pct=rd_shift
    )
