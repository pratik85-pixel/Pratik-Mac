"""
tests/model/test_activity_coherence_tracker.py

Tests for model/activity_coherence_tracker.py

Covers:
  - compute_activity_map returns elevators/drains correctly
  - Activities below MIN_OBS threshold are excluded
  - Elevator direction: coherence_avg > grand_mean + NEUTRAL_BAND
  - Drain direction: coherence_avg < grand_mean - NEUTRAL_BAND
  - Neutral within band
  - Grand mean accuracy
  - Confidence grows with n_obs
  - detect_coherence_spike detects sustained elevations
  - detect_coherence_spike ignores brief spikes
  - CoherenceActivityMap.top_elevator / top_drain
  - to_dict round-trip
"""

import numpy as np
import pytest
from datetime import datetime, timedelta

from model.activity_coherence_tracker import (
    compute_activity_map,
    detect_coherence_spike,
    ActivityCoherenceObservation,
    CoherenceActivityMap,
    ActivityProfile,
    _MIN_OBS,
    _NEUTRAL_BAND,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_obs(
    activity_tag: str,
    coherence: float,
    n: int = 5,
    base_ts: datetime = None,
    source: str = "eod_prompt",
    confidence: float = 0.9,
) -> list[ActivityCoherenceObservation]:
    if base_ts is None:
        base_ts = datetime(2025, 1, 1, 12, 0, 0)
    return [
        ActivityCoherenceObservation(
            ts=base_ts + timedelta(days=i),
            activity_tag=activity_tag,
            coherence=coherence,
            duration_minutes=20.0,
            confidence=confidence,
            source=source,
        )
        for i in range(n)
    ]


# ── Basic map construction ─────────────────────────────────────────────────────

class TestComputeActivityMap:

    def test_empty_returns_empty_map(self):
        result = compute_activity_map([])
        assert isinstance(result, CoherenceActivityMap)
        assert result.elevators == []
        assert result.drains == []

    def test_elevator_classified_correctly(self):
        grand_mean = 0.40
        # cooking at 0.60 → elevator (0.60 > 0.40 + 0.05)
        obs = make_obs("cooking", coherence=0.60, n=5)
        result = compute_activity_map(obs, reference_coherence=grand_mean)
        assert any(p.activity_tag == "cooking" and p.direction == "elevator"
                   for p in result.elevators)

    def test_drain_classified_correctly(self):
        grand_mean = 0.40
        # video_calls at 0.25 → drain (0.25 < 0.40 - 0.05)
        obs = make_obs("video_calls", coherence=0.25, n=5)
        result = compute_activity_map(obs, reference_coherence=grand_mean)
        assert any(p.activity_tag == "video_calls" and p.direction == "drain"
                   for p in result.drains)

    def test_neutral_classified_correctly(self):
        grand_mean = 0.40
        # eating at 0.42 → neutral (within ±0.05 of 0.40)
        obs = make_obs("eating", coherence=0.42, n=5)
        result = compute_activity_map(obs, reference_coherence=grand_mean)
        assert any(p.activity_tag == "eating" and p.direction == "neutral"
                   for p in result.neutral)

    def test_below_min_obs_excluded(self):
        """Activity with only 2 observations (< MIN_OBS=3) should be excluded."""
        obs = make_obs("cooking", coherence=0.70, n=_MIN_OBS - 1)
        result = compute_activity_map(obs, reference_coherence=0.40)
        assert len(result.elevators) == 0

    def test_exactly_min_obs_included(self):
        obs = make_obs("cooking", coherence=0.70, n=_MIN_OBS)
        result = compute_activity_map(obs, reference_coherence=0.40)
        assert len(result.elevators) >= 1


# ── Grand mean ────────────────────────────────────────────────────────────────

class TestGrandMean:

    def test_grand_mean_computed_when_no_reference(self):
        obs = (
            make_obs("cooking",     coherence=0.60, n=5) +
            make_obs("video_calls", coherence=0.30, n=5)
        )
        result = compute_activity_map(obs)
        # Grand mean should be between 0.30 and 0.60
        assert 0.30 < result.grand_mean < 0.60

    def test_reference_overrides_grand_mean(self):
        obs = make_obs("cooking", coherence=0.60, n=5)
        result = compute_activity_map(obs, reference_coherence=0.50)
        assert result.grand_mean == pytest.approx(0.50, abs=1e-4)


# ── Elevator ordering ─────────────────────────────────────────────────────────

class TestOrdering:

    def test_elevators_sorted_descending(self):
        obs = (
            make_obs("cooking",      coherence=0.65, n=5) +
            make_obs("walking",      coherence=0.55, n=5) +
            make_obs("music_playing",coherence=0.75, n=5)
        )
        result = compute_activity_map(obs, reference_coherence=0.35)
        elevs = result.elevators
        for i in range(len(elevs) - 1):
            assert elevs[i].coherence_avg >= elevs[i + 1].coherence_avg

    def test_drains_sorted_ascending(self):
        obs = (
            make_obs("video_calls",  coherence=0.20, n=5) +
            make_obs("social_media", coherence=0.15, n=5) +
            make_obs("email",        coherence=0.25, n=5)
        )
        result = compute_activity_map(obs, reference_coherence=0.45)
        drains = result.drains
        for i in range(len(drains) - 1):
            assert drains[i].coherence_avg <= drains[i + 1].coherence_avg

    def test_top_elevator_has_highest_coherence(self):
        obs = (
            make_obs("cooking",       coherence=0.65, n=5) +
            make_obs("music_playing", coherence=0.80, n=5)
        )
        result = compute_activity_map(obs, reference_coherence=0.35)
        assert result.top_elevator is not None
        assert result.top_elevator.activity_tag == "music_playing"

    def test_top_drain_has_lowest_coherence(self):
        obs = (
            make_obs("video_calls",  coherence=0.20, n=5) +
            make_obs("social_media", coherence=0.12, n=5)
        )
        result = compute_activity_map(obs, reference_coherence=0.45)
        assert result.top_drain is not None
        assert result.top_drain.activity_tag == "social_media"


# ── Confidence ────────────────────────────────────────────────────────────────

class TestActivityConfidence:

    def test_confidence_grows_with_n_obs(self):
        obs3  = make_obs("cooking", coherence=0.65, n=3)
        obs10 = make_obs("cooking", coherence=0.65, n=10)
        obs20 = make_obs("cooking", coherence=0.65, n=20)

        r3  = compute_activity_map(obs3,  reference_coherence=0.35)
        r10 = compute_activity_map(obs10, reference_coherence=0.35)
        r20 = compute_activity_map(obs20, reference_coherence=0.35)

        # Get the cooking profile
        def get_profile(result):
            all_profiles = result.elevators + result.drains + result.neutral
            return next((p for p in all_profiles if p.activity_tag == "cooking"), None)

        p3  = get_profile(r3)
        p10 = get_profile(r10)
        p20 = get_profile(r20)

        assert p3 is not None and p10 is not None and p20 is not None
        assert p3.confidence <= p10.confidence <= p20.confidence

    def test_low_measurement_confidence_filtered(self):
        bad_obs = make_obs("cooking", coherence=0.80, n=10, confidence=0.2)
        result = compute_activity_map(bad_obs, reference_coherence=0.35)
        # Low confidence observations should be filtered out
        # Result should have no elevators (all filtered)
        assert len(result.elevators) == 0


# ── to_dict ───────────────────────────────────────────────────────────────────

class TestToDict:

    def test_to_dict_has_required_keys(self):
        obs = make_obs("cooking", coherence=0.65, n=5)
        result = compute_activity_map(obs, reference_coherence=0.35)
        d = result.to_dict()
        for key in ("elevators", "drains", "neutral", "grand_mean", "n_total_obs", "last_updated"):
            assert key in d

    def test_to_dict_elevators_is_list(self):
        obs = make_obs("cooking", coherence=0.65, n=5)
        result = compute_activity_map(obs, reference_coherence=0.35)
        d = result.to_dict()
        assert isinstance(d["elevators"], list)


# ── detect_coherence_spike ─────────────────────────────────────────────────────

class TestDetectCoherenceSpike:

    def test_sustained_spike_detected(self):
        n = 30
        coherence = np.full(n, 0.40)
        coherence[10:20] = 0.70   # 75% above baseline, 10 windows
        ts = np.linspace(0, 300, n)
        spikes = detect_coherence_spike(
            coherence, ts, personal_baseline=0.40,
            min_duration_windows=6
        )
        assert len(spikes) >= 1

    def test_brief_spike_not_detected(self):
        n = 30
        coherence = np.full(n, 0.40)
        coherence[10:13] = 0.70   # only 3 windows — below min_duration=6
        ts = np.linspace(0, 300, n)
        spikes = detect_coherence_spike(
            coherence, ts, personal_baseline=0.40,
            min_duration_windows=6
        )
        assert len(spikes) == 0

    def test_spike_below_threshold_not_detected(self):
        n = 30
        coherence = np.full(n, 0.40)
        coherence[10:20] = 0.45   # only 12.5% rise (threshold = 15%)
        ts = np.linspace(0, 300, n)
        spikes = detect_coherence_spike(
            coherence, ts, personal_baseline=0.40,
            spike_threshold=0.15,
            min_duration_windows=6
        )
        assert len(spikes) == 0

    def test_spike_returns_start_end_ts(self):
        n = 30
        coherence = np.full(n, 0.40)
        coherence[10:20] = 0.70
        ts = np.linspace(0.0, 290.0, n)
        spikes = detect_coherence_spike(coherence, ts, personal_baseline=0.40)
        if spikes:
            start, end = spikes[0]
            assert start < end

    def test_flat_signal_no_spikes(self):
        coherence = np.full(50, 0.40)
        ts = np.linspace(0, 500, 50)
        spikes = detect_coherence_spike(coherence, ts, personal_baseline=0.40)
        assert spikes == []
