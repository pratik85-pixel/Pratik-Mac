from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

def test_get_weekly_outcomes():
    response = client.get("/api/v1/outcomes/weekly", headers={"x-user-id": "test"})
    assert response.status_code == 200
    data = response.json()
    assert "avg_stress" in data
    assert "avg_recovery" in data
    assert "avg_readiness" in data
    assert "longest_streak" in data

def test_get_longitudinal_outcomes():
    response = client.get("/api/v1/outcomes/longitudinal", headers={"x-user-id": "test"})
    assert response.status_code == 200
    data = response.json()
    assert "trend_direction" in data
    assert "stress_shift_pct" in data
    assert "recovery_shift_pct" in data
    assert "readiness_shift_pct" in data
