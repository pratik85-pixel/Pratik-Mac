import pytest
from tagging.intraday_matcher import IntradayMatcher
from coach.assessor import assess_daily_adherence

class MockLLMClient:
    def estimate_adherence(self, item):
        return 0.5

def test_intraday_matcher():
    matcher = IntradayMatcher()
    plan_items = \
    [
        {"activity_target": "morning_meditation", "has_evidence": False},
        {"activity_slug": "evening_walk", "has_evidence": False}
    ]
    assert matcher.match(plan_items, "morning_meditation") is True
    assert plan_items[0]["has_evidence"] is True
    assert matcher.match(plan_items, "morning_meditation") is False
    assert matcher.match(plan_items, "evening_walk") is True
    assert plan_items[1]["has_evidence"] is True
    assert matcher.match(plan_items, "random_activity") is False

def test_assess_daily_adherence():
    plan_items = [
        {"Activity_target": "meditation", "has_evidence": True},
        {"activity_target": "running", "deviation_reason": "Raining"},
        {"activity_target": "reading", "has_evidence": False}
    ]
    assessed = assess_daily_adherence(plan_items)
    assert assessed[0]["adherence_score"] == 1.0
    assert assessed[1]["adherence_score"] == 0.0
    assert assessed[2]["adherence_score"] == 0.0
    
    plan_items_llm = [{"activity_target": "reading", "has_evidence": False}]
    llm_client = MockLLMClient()
    assessed_llm = assess_daily_adherence(plan_items_llm, llm_client=llm_client)
    assert assessed_llm[0]["adherence_score"] == 0.5
