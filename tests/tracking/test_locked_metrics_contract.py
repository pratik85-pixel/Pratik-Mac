"""Phase 1 — locked metrics contract (no scoring changes)."""

from tracking.locked_metrics_contract import (
    METRICS_CONTRACT_ID,
    classify_score_confidence,
    contract_metadata_for_row,
)


def test_metrics_contract_id_stable():
    assert METRICS_CONTRACT_ID == "zenflow_locked_v1"


def test_classify_confidence_partial_is_low():
    conf, reasons = classify_score_confidence(
        is_estimated=False,
        is_partial_data=True,
        calibration_days=5,
    )
    assert conf == "low"
    assert "partial_day" in reasons


def test_classify_confidence_estimated_is_medium_when_not_partial():
    conf, reasons = classify_score_confidence(
        is_estimated=True,
        is_partial_data=False,
        calibration_days=2,
    )
    assert conf == "medium"
    assert "calibration_incomplete" in reasons


def test_classify_confidence_high_when_locked_and_complete():
    conf, reasons = classify_score_confidence(
        is_estimated=False,
        is_partial_data=False,
        calibration_days=5,
    )
    assert conf == "high"
    assert reasons == []


def test_contract_metadata_for_row_shape():
    d = contract_metadata_for_row(
        is_estimated=True,
        is_partial_data=False,
        calibration_days=1,
        summary_source="persisted_row",
    )
    assert d["metrics_contract_id"] == METRICS_CONTRACT_ID
    assert d["score_confidence"] == "medium"
    assert d["summary_source"] == "persisted_row"
    assert isinstance(d["score_confidence_reasons"], list)

