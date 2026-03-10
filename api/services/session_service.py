"""
api/services/session_service.py

Orchestrates the live session processing pipeline.

Design
------
- One `LiveSession` object per active user session, held in memory while the
  session runs. DB write happens only on session end.
- PPI batches arrive via WebSocket and are accumulated into a rolling buffer.
- Every `WINDOW_SECONDS` of new data, a coherence window is computed.
- On session end, `SessionOutcome` is computed from the accumulated windows
  and the pre/post window PPI metrics.
- Thread-safety: designed for single-threaded asyncio use. Multiple concurrent
  sessions are isolated by session_id.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Optional

import numpy as np

from processing.artifact_handler import filter_ppi_stream
from processing.coherence_scorer import compute_coherence, CoherenceResult
from processing.ppi_processor import compute_ppi_metrics, PPIMetrics
from processing.breath_rate_estimator import estimate_breath_rate
from outcomes.session_outcomes import compute_session_outcome, SessionOutcome
from sessions.session_schema import PracticeSession
from api.config import get_settings

logger = logging.getLogger(__name__)
_cfg   = get_settings()

# Beats to consider a "pre" or "post" window (≈ 2 min at 60 BPM)
_BOUNDARY_BEATS = 120


@dataclass
class LiveMetrics:
    """Real-time metrics snapshot — pushed to the UI on each ingest cycle."""
    session_id:     str
    elapsed_s:      float
    coherence:      Optional[float]   # None until first full window
    zone:           Optional[int]     # 1–4
    rmssd_ms:       Optional[float]
    breath_bpm:     Optional[float]
    windows_so_far: int
    prf_bpm:        Optional[float]   # target PRF (or None for entrainment)


@dataclass
class LiveSession:
    session_id: str
    user_id:    str
    practice:   PracticeSession
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Accumulating PPI buffers (raw — not yet artifact-filtered)
    ppi_ms:     list[float] = field(default_factory=list)
    timestamps: list[float] = field(default_factory=list)

    # Coherence windows computed so far
    coherence_windows: list[CoherenceResult] = field(default_factory=list)

    # Track how many beats have been consumed into windows
    _last_window_beat_idx: int = field(default=0, repr=False)

    # Latest snapshot ready to push
    last_metrics: Optional[LiveMetrics] = field(default=None, repr=False)


class SessionService:
    """
    Singleton service — one instance shared across all requests.
    Register in `app.state.session_service` at startup.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, LiveSession] = {}
        self._outcomes: dict[str, SessionOutcome] = {}   # outcome cache post-end
        self._window_beats = _cfg.MIN_BEATS_PER_WINDOW
        self._window_s     = _cfg.WINDOW_SECONDS
        self._hop_s        = _cfg.WINDOW_SECONDS - _cfg.WINDOW_OVERLAP_SECONDS

    # ── Session lifecycle ──────────────────────────────────────────────────────

    def start_session(self, user_id: str, practice: PracticeSession) -> str:
        sid = str(uuid.uuid4())
        self._sessions[sid] = LiveSession(
            session_id=sid,
            user_id=user_id,
            practice=practice,
        )
        logger.info(
            "session_start user=%s session=%s practice=%s",
            user_id, sid, practice.practice_type,
        )
        return sid

    def end_session(
        self,
        session_id: str,
        morning_rmssd_ms: Optional[float] = None,
        personal_floor_rmssd: Optional[float] = None,
    ) -> Optional[SessionOutcome]:
        live = self._sessions.pop(session_id, None)
        if live is None:
            return None

        if not live.ppi_ms:
            logger.warning("session_end session=%s — no PPI data, skipping outcome", session_id)
            return None

        ended_at   = datetime.now(UTC)
        duration_s = (ended_at - live.started_at).total_seconds()

        ppi_arr = np.array(live.ppi_ms, dtype=float)
        clean, _, _ = filter_ppi_stream(ppi_arr, np.zeros_like(ppi_arr))

        # Pre/post window metrics (~2-min boundary windows)
        pre_metrics:  Optional[PPIMetrics] = None
        post_metrics: Optional[PPIMetrics] = None

        if len(clean) >= _BOUNDARY_BEATS:
            pre_metrics  = compute_ppi_metrics(clean[:_BOUNDARY_BEATS])
            post_metrics = compute_ppi_metrics(clean[-_BOUNDARY_BEATS:])

        outcome = compute_session_outcome(
            live.coherence_windows,
            session_id=session_id,
            duration_minutes=max(1, int(duration_s / 60)),
            session_type=live.practice.practice_type,
            practice_type=live.practice.practice_type,
            attention_anchor=live.practice.attention_anchor,
            pre_window_metrics=pre_metrics,
            post_window_metrics=post_metrics,
            morning_rmssd_ms=morning_rmssd_ms,
            personal_floor_rmssd=personal_floor_rmssd,
        )

        logger.info(
            "session_end session=%s score=%.2f windows=%d dur_min=%d",
            session_id, outcome.session_score,
            len(live.coherence_windows), int(duration_s / 60),
        )
        # Cache for post-session coach retrieval (coach router calls get_cached_outcome)
        self._outcomes[session_id] = outcome
        return outcome

    # ── Real-time PPI ingestion ────────────────────────────────────────────────

    def ingest_ppi(
        self,
        session_id:   str,
        ppi_ms:       list[float],
        timestamps_s: list[float],
    ) -> Optional[LiveMetrics]:
        """
        Accept a batch of raw PPI values and their timestamps.
        Triggers a new coherence window if enough data has accumulated
        since the last window.
        Returns an updated LiveMetrics snapshot.
        """
        live = self._sessions.get(session_id)
        if live is None:
            return None

        live.ppi_ms.extend(ppi_ms)
        live.timestamps.extend(timestamps_s)

        total_beats = len(live.ppi_ms)

        # Slide a new window every time we accumulate `_window_s` seconds of
        # new beats past the last window boundary.
        if total_beats >= self._window_beats:
            beats_since = total_beats - live._last_window_beat_idx
            if beats_since >= self._window_beats:
                start = max(0, total_beats - self._window_beats)
                chunk_ppi = np.array(live.ppi_ms[start:], dtype=float)
                chunk_ts  = np.array(live.timestamps[start:], dtype=float)

                clean_ppi, clean_ts, artifact_flags = filter_ppi_stream(chunk_ppi, chunk_ts)
                artifact_rate = float(artifact_flags.mean()) if len(artifact_flags) else 0.0

                if len(clean_ppi) >= self._window_beats:
                    try:
                        cr = compute_coherence(clean_ppi, clean_ts, artifact_rate=artifact_rate)
                        live.coherence_windows.append(cr)
                        live._last_window_beat_idx = total_beats
                    except Exception as exc:
                        logger.warning("coherence_error session=%s: %s", session_id, exc)

        # ── Build live snapshot ───────────────────────────────────────────────
        latest_cr = live.coherence_windows[-1] if live.coherence_windows else None
        coherence = latest_cr.coherence if latest_cr else None
        zone      = latest_cr.zone      if latest_cr else None

        rmssd: Optional[float] = None
        if total_beats >= 10:
            recent = np.array(live.ppi_ms[-60:], dtype=float)
            diffs  = np.diff(recent)
            if len(diffs):
                rmssd = float(np.sqrt(np.mean(diffs ** 2)))

        breath_bpm: Optional[float] = None
        if total_beats >= _cfg.MIN_BEATS_PER_WINDOW:
            br = estimate_breath_rate(
                np.array(live.ppi_ms, dtype=float),
                np.array(live.timestamps, dtype=float),
            )
            if br.is_valid():
                breath_bpm = br.bpm

        elapsed = (live.timestamps[-1] - live.timestamps[0]) if len(live.timestamps) > 1 else 0.0

        live.last_metrics = LiveMetrics(
            session_id     = session_id,
            elapsed_s      = elapsed,
            coherence      = coherence,
            zone           = zone,
            rmssd_ms       = rmssd,
            breath_bpm     = breath_bpm,
            windows_so_far = len(live.coherence_windows),
            prf_bpm        = live.practice.prf_target_bpm,
        )
        return live.last_metrics

    def get_live_metrics(self, session_id: str) -> Optional[LiveMetrics]:
        live = self._sessions.get(session_id)
        return live.last_metrics if live else None

    def is_active(self, session_id: str) -> bool:
        return session_id in self._sessions

    def active_count(self) -> int:
        return len(self._sessions)

    def get_cached_outcome(self, session_id: str) -> Optional[SessionOutcome]:
        """Return the cached SessionOutcome after end_session() is called."""
        return self._outcomes.get(session_id)
