"""
api/routers/tracking.py

All-day tracking endpoints.

GET  /tracking/daily-summary           — today's three numbers
GET  /tracking/daily-summary/{date}    — a specific date (YYYY-MM-DD)
GET  /tracking/waveform/{date}         — 5-min RMSSD waveform for date
GET  /tracking/stress-windows/{date}   — detected stress events for date
GET  /tracking/recovery-windows/{date} — detected recovery events for date
POST /tracking/tag-window              — user-confirmed tag on a stress/recovery window
GET  /tracking/history                 — readiness trend (last N days, default 28)
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import get_db
from api.services.tracking_service import TrackingService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tracking", tags=["tracking"])


# ── Dependencies ───────────────────────────────────────────────────────────────

async def _user_id(x_user_id: Annotated[str, Header()]) -> str:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header required")
    return x_user_id


async def _tracking_svc(
    user_id: str = Depends(_user_id),
    db: AsyncSession = Depends(get_db),
) -> TrackingService:
    return TrackingService(db_session=db, user_id=user_id)


# ── Response models ────────────────────────────────────────────────────────────

class DailySummaryResponse(BaseModel):
    summary_date:      str
    stress_load_score: Optional[float]
    recovery_score:    Optional[float]
    readiness_score:   Optional[float]
    day_type:          Optional[str]
    calibration_days:  int
    is_estimated:      bool
    is_partial_data:   bool
    wake_ts:           Optional[str]
    sleep_ts:          Optional[str]
    waking_minutes:    Optional[float]


class WaveformPoint(BaseModel):
    window_start: str
    window_end:   str
    rmssd_ms:     Optional[float]
    hr_bpm:       Optional[float]
    context:      str
    is_valid:     bool


class StressWindowResponse(BaseModel):
    id:              str
    started_at:      str
    ended_at:        str
    duration_minutes: float
    rmssd_min_ms:    Optional[float]
    suppression_pct: Optional[float]
    stress_contribution_pct: Optional[float]
    tag:             Optional[str]
    tag_candidate:   Optional[str]
    tag_source:      Optional[str]
    nudge_sent:      bool
    nudge_responded: bool


class RecoveryWindowResponse(BaseModel):
    id:              str
    started_at:      str
    ended_at:        str
    duration_minutes: float
    context:         str
    rmssd_avg_ms:    Optional[float]
    recovery_contribution_pct: Optional[float]
    tag:             Optional[str]
    tag_source:      Optional[str]
    zenflow_session_id: Optional[str]


class TagWindowRequest(BaseModel):
    window_id:   str
    window_type: str   # "stress" | "recovery"
    tag:         str


class HistoryEntry(BaseModel):
    summary_date:      str
    readiness_score:   Optional[float]
    stress_load_score: Optional[float]
    recovery_score:    Optional[float]
    day_type:          Optional[str]
    is_estimated:      bool


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_date(date_str: str) -> date:
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid date format: {date_str!r}. Expected YYYY-MM-DD."
        )


def _fmt_ts(ts: Optional[datetime]) -> Optional[str]:
    return ts.isoformat() if ts else None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/daily-summary", response_model=DailySummaryResponse)
async def get_today_summary(
    svc: TrackingService = Depends(_tracking_svc),
) -> DailySummaryResponse:
    """Return the three numbers (stress / recovery / readiness) for today."""
    today = datetime.now(UTC).date()
    row   = await svc.get_daily_summary(today)
    if row is None:
        raise HTTPException(status_code=404, detail="No summary available for today yet.")
    return _build_summary_response(row)


@router.get("/daily-summary/{date_str}", response_model=DailySummaryResponse)
async def get_summary_by_date(
    date_str: str,
    svc: TrackingService = Depends(_tracking_svc),
) -> DailySummaryResponse:
    """Return the three numbers for a specific date (YYYY-MM-DD)."""
    target = _parse_date(date_str)
    row    = await svc.get_daily_summary(target)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No summary found for {date_str}.")
    return _build_summary_response(row)


@router.get("/waveform/{date_str}", response_model=list[WaveformPoint])
async def get_waveform(
    date_str: str,
    svc: TrackingService = Depends(_tracking_svc),
) -> list[WaveformPoint]:
    """
    Return the chronological 5-min RMSSD waveform for the given date.
    All windows are returned (both valid and invalid) so the client can
    render data-gap segments. The client should grey-out is_valid=False points.
    """
    target  = _parse_date(date_str)
    windows = await svc.get_waveform(target)
    return [
        WaveformPoint(
            window_start = w.window_start.isoformat(),
            window_end   = w.window_end.isoformat(),
            rmssd_ms     = w.rmssd_ms,
            hr_bpm       = w.hr_bpm,
            context      = w.context,
            is_valid     = w.is_valid,
        )
        for w in windows
    ]


@router.get("/stress-windows/{date_str}", response_model=list[StressWindowResponse])
async def get_stress_windows(
    date_str: str,
    svc: TrackingService = Depends(_tracking_svc),
) -> list[StressWindowResponse]:
    """Return all detected stress windows for the given date, sorted by start time."""
    target  = _parse_date(date_str)
    windows = await svc.get_stress_windows(target)
    return [
        StressWindowResponse(
            id               = str(w.id),
            started_at       = w.started_at.isoformat(),
            ended_at         = w.ended_at.isoformat(),
            duration_minutes = w.duration_minutes,
            rmssd_min_ms     = w.rmssd_min_ms,
            suppression_pct  = w.suppression_pct,
            stress_contribution_pct = w.stress_contribution_pct,
            tag              = w.tag,
            tag_candidate    = w.tag_candidate,
            tag_source       = w.tag_source,
            nudge_sent       = w.nudge_sent,
            nudge_responded  = w.nudge_responded,
        )
        for w in sorted(windows, key=lambda w: w.started_at)
    ]


@router.get("/recovery-windows/{date_str}", response_model=list[RecoveryWindowResponse])
async def get_recovery_windows(
    date_str: str,
    svc: TrackingService = Depends(_tracking_svc),
) -> list[RecoveryWindowResponse]:
    """Return all detected recovery windows for the given date, sorted by start time."""
    target  = _parse_date(date_str)
    windows = await svc.get_recovery_windows(target)
    return [
        RecoveryWindowResponse(
            id               = str(w.id),
            started_at       = w.started_at.isoformat(),
            ended_at         = w.ended_at.isoformat(),
            duration_minutes = w.duration_minutes,
            context          = w.context,
            rmssd_avg_ms     = w.rmssd_avg_ms,
            recovery_contribution_pct = w.recovery_contribution_pct,
            tag              = w.tag,
            tag_source       = w.tag_source,
            zenflow_session_id = str(w.zenflow_session_id) if w.zenflow_session_id else None,
        )
        for w in sorted(windows, key=lambda w: w.started_at)
    ]


# ── Ingest (from BLE bridge / app) ───────────────────────────────────────────

class BeatSample(BaseModel):
    ppi_ms:   float
    ts:       float          # unix epoch seconds (float)
    artifact: bool = False


class IngestRequest(BaseModel):
    beats:     list[BeatSample]
    context:   str   = "background"   # "background" | "sleep"
    acc_mean:  Optional[float] = None
    gyro_mean: Optional[float] = None


class IngestResponse(BaseModel):
    windows_processed: int
    beats_received:    int


@router.post("/ingest", response_model=IngestResponse)
async def ingest_beats(
    body: IngestRequest,
    svc:  TrackingService = Depends(_tracking_svc),
) -> IngestResponse:
    """
    Accept a batch of raw PPI beats from the mobile app's BLE bridge.

    The app calls this endpoint every ~5 minutes with all beats collected since
    the last flush.  Beats are split into WINDOW_MINUTES-wide windows here;
    each complete window is processed by the tracking pipeline and written to
    BackgroundWindow.

    No PersonalModel is required — windows are always stored.  Stress / recovery
    detection is a no-op (returns early) until the personal baseline is built.
    """
    if not body.beats:
        return IngestResponse(windows_processed=0, beats_received=0)

    context = body.context if body.context in ("background", "sleep") else "background"

    # Sort by timestamp
    beats = sorted(body.beats, key=lambda b: b.ts)

    WINDOW_SEC = 300  # 5 minutes

    # Group beats into 5-min buckets anchored to the first beat
    bucket_start_ts = beats[0].ts
    buckets: list[list[BeatSample]] = []
    current: list[BeatSample] = []

    for beat in beats:
        if beat.ts - bucket_start_ts >= WINDOW_SEC and current:
            buckets.append(current)
            current = []
            bucket_start_ts = beat.ts
        current.append(beat)

    if current:
        buckets.append(current)

    windows_processed = 0
    for bucket in buckets:
        ppi_vals = [b.ppi_ms for b in bucket]
        ts_vals  = [b.ts for b in bucket]
        win_start = datetime.fromtimestamp(bucket[0].ts, tz=UTC)
        win_end   = datetime.fromtimestamp(bucket[-1].ts, tz=UTC)

        try:
            await svc.ingest_background_window(
                ppi_ms       = ppi_vals,
                timestamps   = ts_vals,
                window_start = win_start,
                window_end   = win_end,
                context      = context,
                acc_mean     = body.acc_mean,
                gyro_mean    = body.gyro_mean,
            )
            windows_processed += 1
        except Exception:
            logger.exception("ingest_background_window failed for window %s", win_start)

    return IngestResponse(windows_processed=windows_processed, beats_received=len(beats))


@router.post("/tag-window", status_code=204, response_model=None)
async def tag_window(
    body: TagWindowRequest,
    svc: TrackingService = Depends(_tracking_svc),
) -> Response:
    """
    Apply a user-confirmed tag to a stress or recovery window.
    The tag replaces any existing tag_candidate and sets tag_source = "user_confirmed".
    """
    try:
        await svc.update_window_tag(
            window_id   = body.window_id,
            window_type = body.window_type,
            tag         = body.tag,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return Response(status_code=204)


@router.get("/history", response_model=list[HistoryEntry])
async def get_history(
    days: int = 28,
    svc: TrackingService = Depends(_tracking_svc),
) -> list[HistoryEntry]:
    """
    Return readiness / stress / recovery trend for the last N days (default 28).
    Ordered newest-first. Used by the History view sparklines.
    """
    if not 1 <= days <= 365:
        raise HTTPException(status_code=422, detail="`days` must be between 1 and 365.")
    rows = await svc.get_history(days=days)
    return [
        HistoryEntry(
            summary_date      = row.summary_date.date().isoformat() if row.summary_date else "",
            readiness_score   = row.readiness_score,
            stress_load_score = row.stress_load_score,
            recovery_score    = row.recovery_score,
            day_type          = row.day_type,
            is_estimated      = row.is_estimated,
        )
        for row in rows
    ]


# ── Private builder ────────────────────────────────────────────────────────────

def _build_summary_response(row) -> DailySummaryResponse:
    return DailySummaryResponse(
        summary_date      = row.summary_date.date().isoformat() if row.summary_date else "",
        stress_load_score = row.stress_load_score,
        recovery_score    = row.recovery_score,
        readiness_score   = row.readiness_score,
        day_type          = row.day_type,
        calibration_days  = row.calibration_days or 0,
        is_estimated      = row.is_estimated,
        is_partial_data   = row.is_partial_data,
        wake_ts           = _fmt_ts(row.wake_ts),
        sleep_ts          = _fmt_ts(row.sleep_ts),
        waking_minutes    = row.waking_minutes,
    )
