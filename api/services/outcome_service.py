from typing import List, Dict, Any
from outcomes.weekly_outcomes import compute_weekly_summary
from outcomes.longitudinal_outcomes import calculate_longitudinal_arc
from outcomes.report_builder import generate_outcome_report

class OutcomeService:
    def get_weekly_summary(self, data: List[Dict[str, Any]]):
        return compute_weekly_summary(data)
    
    def get_longitudinal_arc(self, recent_30: List[Dict[str, Any]], previous_30: List[Dict[str, Any]]):
        return calculate_longitudinal_arc(recent_30, previous_30)
        
    def get_outcome_report(self, weekly_data: List[Dict[str, Any]], recent_30: List[Dict[str, Any]], previous_30: List[Dict[str, Any]]):
        return generate_outcome_report(weekly_data, recent_30, previous_30)
