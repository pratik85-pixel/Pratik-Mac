from dataclasses import dataclass
from typing import List, Dict, Any

@dataclass
class WeeklyOutcomeSummary:
    avg_stress: float
    avg_recovery: float
    avg_readiness: float
    longest_streak: int

def compute_weekly_summary(data: List[Dict[str, Any]]) -> WeeklyOutcomeSummary:
    if not data:
        return WeeklyOutcomeSummary(0.0, 0.0, 0.0, 0)
    
    stress = [d.get("stress", 0.0) for d in data if "stress" in d]
    recovery = [d.get("recovery", 0.0) for d in data if "recovery" in d]
    readiness = [d.get("readiness", 0.0) for d in data if "readiness" in d]
    
    avg_stress = sum(stress) / len(stress) if stress else 0.0
    avg_recovery = sum(recovery) / len(recovery) if recovery else 0.0
    avg_readiness = sum(readiness) / len(readiness) if readiness else 0.0
    
    current_streak = 0
    max_streak = 0
    for d in data:
        if d.get("streak", 0) > 0:
            current_streak = d.get("streak")
        else:
            current_streak += 1 if d.get("completed_day", False) else 0
        
        if current_streak > max_streak:
            max_streak = current_streak
            
    return WeeklyOutcomeSummary(
        avg_stress=avg_stress,
        avg_recovery=avg_recovery,
        avg_readiness=avg_readiness,
        longest_streak=max_streak
    )
