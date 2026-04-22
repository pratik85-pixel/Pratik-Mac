"""
api/services/ingest_pipeline.py

Background-beat ingest pipeline.

Moved out of `api/routers/tracking.py` so the router stays a thin IO shell
and the business logic (bucketing beats into windows, error aggregation)
is directly testable.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# 5 minutes: matches the historical WINDOW_MINUTES contract used by the
# tracking pipeline. Keep this in sync with `tracking.window_processor`.
WINDOW_SEC = 300


@dataclass(frozen=True)
class BeatLike:
    """Shape-compatible with api.routers.tracking.BeatSample."""
    ts: float
    ppi_ms: float


class _TrackingServiceLike(Protocol):  # pragma: no cover
    _uid: Any

    async def ingest_background_window(
        self,
        *,
        ppi_ms: list[float],
        timestamps: list[float],
        window_start: datetime,
        window_end: datetime,
        context: str,
        acc_mean: float | None,
        gyro_mean: float | None,
    ) -> Any: ...


def bucket_beats(beats: list[BeatLike]) -> list[list[BeatLike]]:
    """
    Split sorted beats into ≤ WINDOW_SEC-wide buckets anchored on the first
    beat of each bucket. Pure function — safe to unit test without a DB.
    """
    if not beats:
        return []
    buckets: list[list[BeatLike]] = []
    current: list[BeatLike] = []
    bucket_start_ts = beats[0].ts
    for beat in beats:
        if beat.ts - bucket_start_ts >= WINDOW_SEC and current:
            buckets.append(current)
            current = []
            bucket_start_ts = beat.ts
        current.append(beat)
    if current:
        buckets.append(current)
    return buckets


async def ingest_beat_batch(
    svc: _TrackingServiceLike,
    *,
    beats: list[BeatLike],
    context: str = "background",
    acc_mean: float | None = None,
    gyro_mean: float | None = None,
) -> tuple[int, int]:
    """
    Bucket + push beats into the tracking service. Returns
    ``(windows_processed, beats_received)``.

    Each window is a separate awaited call; errors on one window do not abort
    the rest (they are logged and counted as failures).
    """
    if not beats:
        return 0, 0

    context = context if context in ("background", "sleep") else "background"
    # Defensive sort — caller should send sorted data but we mustn't rely on it.
    sorted_beats = sorted(beats, key=lambda b: b.ts)

    windows_processed = 0
    for bucket in bucket_beats(sorted_beats):
        ppi_vals = [b.ppi_ms for b in bucket]
        ts_vals  = [b.ts for b in bucket]
        win_start = datetime.fromtimestamp(bucket[0].ts, tz=UTC)
        win_end   = datetime.fromtimestamp(bucket[-1].ts, tz=UTC)
        try:
            await svc.ingest_background_window(
                ppi_ms=ppi_vals,
                timestamps=ts_vals,
                window_start=win_start,
                window_end=win_end,
                context=context,
                acc_mean=acc_mean,
                gyro_mean=gyro_mean,
            )
            windows_processed += 1
        except Exception:
            logger.exception("ingest_background_window failed for window %s", win_start)

    uid_hash = hashlib.sha256(str(svc._uid).encode()).hexdigest()[:12]
    logger.info(
        "INGEST uid_hash=%s context=%s windows_processed=%d beats=%d",
        uid_hash, context, windows_processed, len(sorted_beats),
    )

    return windows_processed, len(sorted_beats)
