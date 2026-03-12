from outcomes.weekly_outcomes import compute_weekly_summary, WeeklyOutcomeSummary
from outcomes.longitudinal_outcomes import calculate_longitudinal_arc, LongitudinalArc
from typing import List, Dict, Any

def build_structured_report(
    weekly_data: List[Dict[str, Any]], 
    recent_30: List[Dict[str, Any]], 
    previous_30: List[Dict[str, Any]]
) -> Dict[str, Any]:
    weekly_summary = compute_weekly_summary(weekly_data)
    longitudinal_arc = calculate_longitudinal_arc(recent_30, previous_30)
    
    insight_note = f"Recent trend is {longitudinal_arc.trend_direction}."
    if longitudinal_arc.trend_direction == "improving" and weekly_summary.longest_streak > 3:
        insight_note += " Great streak matching longitudinal improvement!"
    elif longitudinal_arc.trend_direction == "declining":
        insight_note += " Time to focus on recovery."
    
    return {
        "weekly_summary": weekly_summary,
        "longitudinal_arc": longitudinal_arc,
        "insight_note": insight_note
    }
generate_outcome_report = build_structured_report
