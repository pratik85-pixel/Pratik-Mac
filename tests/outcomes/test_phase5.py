from outcomes.weekly_outcomes import compute_weekly_summary
from outcomes.longitudinal_outcomes import calculate_longitudinal_arc
from outcomes.report_builder import build_structured_report
from outcomes.hardmode_tracker import is_hard_mode_eligible

def test_weekly_summary():
    data = [
        {"stress": 40.0, "recovery": 80.0, "readiness": 90.0, "streak": 1},
        {"stress": 50.0, "recovery": 70.0, "readiness": 85.0, "streak": 2}
    ]
    summary = compute_weekly_summary(data)
    assert summary.avg_stress == 45.0
    assert summary.avg_recovery == 75.0
    assert summary.avg_readiness == 87.5
    assert summary.longest_streak == 2

def test_longitudinal_arc():
    recent = [{"stress": 30.0, "recovery": 90.0, "readiness": 90.0}]
    prev = [{"stress": 50.0, "recovery": 70.0, "readiness": 70.0}]
    arc = calculate_longitudinal_arc(recent, prev)
    assert arc.trend_direction == "improving"
    assert arc.stress_shift_pct == -40.0
    
def test_report_builder():
    recent = [{"stress": 30.0, "recovery": 90.0, "readiness": 90.0, "streak": 4}]
    prev = [{"stress": 50.0, "recovery": 70.0, "readiness": 70.0}]
    report = build_structured_report(recent, recent, prev)
    assert "weekly_summary" in report
    assert "insight_note" in report
    assert report["insight_note"].startswith("Recent trend is improving")
    
def test_hardmode_tracker():
    assert is_hard_mode_eligible(85.0) is True
    assert is_hard_mode_eligible(84.9) is False
