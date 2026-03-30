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
GET  /tracking/stress-state            — stress now (zone) + trend + optional cohort (Phase 2–3, 7)
GET  /tracking/morning-recap           — yesterday summary + show/ack (Phase 5)
POST /tracking/morning-recap/ack       — dismiss morning recap for a date
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import get_db, AsyncSessionLocal
from api.services.tracking_service import TrackingService
from api.rate_limiter import ingest_limiter
from tracking.cycle_boundaries import local_today
from tracking.locked_metrics_contract import contract_metadata_for_row

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tracking", tags=["tracking"])


# ── Dependencies ───────────────────────────────────────────────────────────────

async def _user_id(x_user_id: Annotated[str, Header()]) -> str:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header required")
    return x_user_id


async def _tracking_svc(
    request: Request,
    user_id: str = Depends(_user_id),
    db: AsyncSession = Depends(get_db),
) -> TrackingService:
    llm_client = getattr(request.app.state, "llm_client", None)
    return TrackingService(
        db_session=db,
        user_id=user_id,
        session_factory=AsyncSessionLocal,
        llm_client=llm_client,
    )


# ── Response models ────────────────────────────────────────────────────────────

class DailySummaryResponse(BaseModel):
    summary_date:          str
    stress_load_score:     Optional[float]
    recovery_score:        Optional[float] = None
    waking_recovery_score: Optional[float] = None
    sleep_recovery_score:  Optional[float] = None
    sleep_recovery_night_date: Optional[str] = None   # YYYY-MM-DD (previous night)
    sleep_recovery_subtext: Optional[str] = None      # UI hint for date context
    net_balance:           Optional[float] = None
    day_type:              Optional[str]
    calibration_days:      int
    is_estimated:          bool
    is_partial_data:       bool
    wake_ts:               Optional[str]
    sleep_ts:              Optional[str]
    waking_minutes:        Optional[float]
    # Chart denominator fields — needed by frontend to compute per-window score delta
    ns_capacity_used:      Optional[float] = None   # (ceiling - floor) × 960
    rmssd_morning_avg:     Optional[float] = None   # personal morning baseline (ms)
    rmssd_ceiling:         Optional[float] = None   # personal RMSSD ceiling (ms)
    # Phase 1 — locked metrics contract (does not alter numeric scores)
    metrics_contract_id:   str = "zenflow_locked_v1"
    score_confidence:      Literal["high", "medium", "low"] = "high"
    score_confidence_reasons: list[str] = []
    summary_source:        Literal["live_compute", "persisted_row"] = "persisted_row"
    # Deterministic plain-English explanation of WHY these specific scores are what they are.
    # Use this for "Why this score?" UI sections on historical/daily summary screens.
    # This is NOT the LLM morning brief — it is always date-specific and score-grounded.
    score_explanation:     Optional[str] = None


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
    summary_date:          str
    stress_load_score:     Optional[float]
    recovery_score:        Optional[float] = None
    waking_recovery_score: Optional[float]
    sleep_recovery_score:  Optional[float] = None
    sleep_recovery_night_date: Optional[str] = None   # YYYY-MM-DD (previous night)
    sleep_recovery_subtext: Optional[str] = None      # UI hint for date context
    net_balance:           Optional[float]
    day_type:              Optional[str]
    is_estimated:          bool
    is_partial_data:       Optional[bool] = None
    metrics_contract_id:   str = "zenflow_locked_v1"
    score_confidence:      Literal["high", "medium", "low"] = "high"
    score_confidence_reasons: list[str] = []
    summary_source:        Literal["live_compute", "persisted_row"] = "persisted_row"


class CohortInsightResponse(BaseModel):
    enabled: bool
    band: Optional[str] = None  # below_typical | typical | above_typical
    disclaimer: str = ""


class StressStateResponse(BaseModel):
    """
    Home hero: zone + trend. Zone ids map to Calm / Steady / Activated / Depleted.
    """

    stress_now_zone: Optional[str] = None       # calm | steady | activated | depleted
    stress_now_index: Optional[float] = None  # 0 = calm vs ref, 1 = at floor
    stress_now_percent: Optional[float] = None  # secondary display 0–100
    trend: str                                # easing | stable | building | unclear
    confidence: str                           # high | medium | low
    reference_type: str = "morning_avg"
    as_of: Optional[str] = None               # ISO timestamp of last window used
    rmssd_smoothed_ms: Optional[float] = None
    zone_cut_index_low: Optional[float] = None
    zone_cut_index_mid: Optional[float] = None
    zone_cut_index_high: Optional[float] = None
    morning_reference_ms: Optional[float] = None
    time_of_day_reference_ms: Optional[float] = None
    cohort: Optional[CohortInsightResponse] = None


class MorningRecapSummaryBlock(BaseModel):
    stress_load_score: Optional[float] = None
    recovery_score: Optional[float] = None
    waking_recovery_score: Optional[float] = None
    sleep_recovery_score: Optional[float] = None
    sleep_recovery_night_date: Optional[str] = None   # YYYY-MM-DD (previous night)
    sleep_recovery_subtext: Optional[str] = None      # UI hint for date context
    net_balance: Optional[float] = None
    day_type: Optional[str] = None
    is_estimated: bool = False
    is_partial_data: bool = False
    sleep_recovery_area: Optional[float] = None
    closing_balance: Optional[float] = None
    metrics_contract_id: str = "zenflow_locked_v1"
    score_confidence: Literal["high", "medium", "low"] = "high"
    score_confidence_reasons: list[str] = []
    summary_source: Literal["live_compute", "persisted_row"] = "persisted_row"
    # Deterministic plain-English explanation of WHY these scores are what they are.
    # Use this for "Why this score?" sections — NOT the LLM morning brief.
    score_explanation: Optional[str] = None


class MorningRecapResponse(BaseModel):
    for_date: str
    should_show: bool
    acknowledged_for_date: bool
    summary: Optional[MorningRecapSummaryBlock] = None


class MorningRecapAckRequest(BaseModel):
    for_date: str  # YYYY-MM-DD


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


def _sleep_recovery_context(summary_date: Optional[date]) -> tuple[Optional[str], Optional[str]]:
    """Return (night_date_iso, subtext) for sleep recovery display context."""
    if summary_date is None:
        return None, None
    night_date = (summary_date - timedelta(days=1)).isoformat()
    return night_date, f"For night of {night_date}"


# ── Score explanation builder (deterministic — used for "Why this score?") ────

def _build_score_explanation(
    stress_load_score: Optional[float],   # raw 0–100 from DB
    waking_recovery_score: Optional[float],  # 0–100
    sleep_recovery_score: Optional[float],   # 0–100 or None
    day_type: Optional[str] = None,
) -> str:
    """
    Return a 1–3 sentence plain-English explanation of WHY today's numbers are
    what they are.  This is deterministic (no LLM) and date-specific.

    stress_load is converted to 0–10 for citation to match the app display.
    recovery/sleep remain as percentages (0–100).
    """
    parts: list[str] = []

    # ── Stress load ─────────────────────────────────────────────────────────
    if stress_load_score is not None:
        sl = round(float(stress_load_score) / 10.0, 1)
        if stress_load_score >= 75:
            parts.append(
                f"Stress load was high at {sl}/10 — your nervous system was under "
                "significant pressure for much of the day."
            )
        elif stress_load_score >= 45:
            parts.append(
                f"Stress load was moderate at {sl}/10, indicating your system was "
                "working through a meaningful but manageable amount of stress."
            )
        else:
            parts.append(
                f"Stress load was low at {sl}/10, reflecting a well-managed day "
                "for your nervous system."
            )

    # ── Waking recovery ─────────────────────────────────────────────────────
    if waking_recovery_score is not None:
        wr = round(float(waking_recovery_score))
        if wr < 20:
            parts.append(
                f"Waking recovery was low at {wr}% — your system hadn't had enough "
                "restorative windows during active hours to rebuild capacity."
            )
        elif wr < 50:
            parts.append(
                f"Waking recovery was still rebuilding at {wr}%, meaning your "
                "system had some restoration but not a full recharge."
            )
        else:
            parts.append(
                f"Waking recovery was solid at {wr}%, showing your system was "
                "stabilising well across the day."
            )

    # ── Sleep recovery ───────────────────────────────────────────────────────
    if sleep_recovery_score is None:
        parts.append(
            "Sleep recovery data isn't available for this day — "
            "the band may not have been worn during sleep."
        )
    elif sleep_recovery_score < 20:
        parts.append(
            f"Sleep recovery was low at {round(float(sleep_recovery_score))}%, "
            "suggesting limited overnight HRV restoration."
        )
    elif sleep_recovery_score >= 60:
        parts.append(
            f"Sleep recovery was strong at {round(float(sleep_recovery_score))}%, "
            "indicating good overnight restoration."
        )

    return "  ".join(parts) if parts else "Score data is limited for this day."


# ── Daily summary builder (Phase 1 contract metadata — scores unchanged) ─────

def _pipeline_meta(
    row: object,
    summary_source: Literal["live_compute", "persisted_row"],
) -> dict:
    """Phase 1 contract fields — derived from existing flags only; scores unchanged."""
    return contract_metadata_for_row(
        is_estimated=bool(getattr(row, "is_estimated", False)),
        is_partial_data=bool(getattr(row, "is_partial_data", False)),
        calibration_days=int(getattr(row, "calibration_days", 0) or 0),
        summary_source=summary_source,
    )


def _build_summary_response(
    row,
    personal=None,
    *,
    summary_source: Literal["live_compute", "persisted_row"] = "persisted_row",
) -> DailySummaryResponse:
    summary_local_date = row.summary_date.date() if getattr(row, "summary_date", None) else None
    sleep_night_date, sleep_subtext = _sleep_recovery_context(summary_local_date)

    # Sleep recovery is only meaningful when a validated sleep boundary (sleep_ts) exists.
    # Return None when boundary is missing so the UI can show "—" instead of 0%.
    sleep_recovery_score = None
    if getattr(row, "sleep_ts", None) is not None:
        if getattr(row, "sleep_recovery_score", None) is not None:
            sleep_recovery_score = getattr(row, "sleep_recovery_score", None)
        elif getattr(row, "ns_capacity_recovery", None) and row.ns_capacity_recovery > 0:
            raw_sleep = getattr(row, "raw_recovery_area_sleep", 0.0) or 0.0
            sleep_recovery_score = round(
                max(0.0, min(100.0, (raw_sleep / row.ns_capacity_recovery) * 100.0)),
                1,
            )

    meta = _pipeline_meta(row, summary_source)
    waking_rec = getattr(row, 'waking_recovery_score', None)
    return DailySummaryResponse(
        summary_date          = row.summary_date.date().isoformat() if row.summary_date else "",
        stress_load_score     = row.stress_load_score,
        recovery_score        = waking_rec,
        waking_recovery_score = waking_rec,
        sleep_recovery_score  = sleep_recovery_score,
        sleep_recovery_night_date = sleep_night_date,
        sleep_recovery_subtext = sleep_subtext,
        net_balance           = getattr(row, 'net_balance', None),
        day_type              = row.day_type,
        calibration_days      = row.calibration_days or 0,
        is_estimated          = row.is_estimated,
        is_partial_data       = row.is_partial_data,
        wake_ts               = _fmt_ts(getattr(row, 'wake_ts', None)),
        sleep_ts              = _fmt_ts(getattr(row, 'sleep_ts', None)),
        waking_minutes        = getattr(row, 'waking_minutes', None),
        ns_capacity_used      = getattr(row, 'ns_capacity_used', None),
        rmssd_morning_avg     = personal.rmssd_morning_avg if personal else None,
        rmssd_ceiling         = personal.rmssd_ceiling if personal else None,
        score_explanation     = _build_score_explanation(
            stress_load_score=row.stress_load_score,
            waking_recovery_score=waking_rec,
            sleep_recovery_score=sleep_recovery_score,
            day_type=row.day_type,
        ),
        **meta,
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/daily-summary", response_model=DailySummaryResponse)
async def get_today_summary(
    svc: TrackingService = Depends(_tracking_svc),
) -> DailySummaryResponse:
    """
    Return the three numbers (stress / recovery / readiness) for today.

    Day boundary is the MORNING READ, not calendar midnight.
    compute_live_summary() spans from yesterday's morning read when no
    morning read has arrived yet, so scores keep accumulating overnight.

    Fallback chain:
    1. Persisted DailyStressSummary row for today (finalized or partial).
    2. Live on-the-fly computation spanning from last morning read (no DB write).
    3. 404 — band not worn at all yet.

    "Today" uses STRESS_STATE_TIMEZONE (IST) so Home matches History labels and
    materialised rows keyed by IST calendar date.
    """
    today = local_today()

    personal = await svc.get_personal_model()

    # 1. Live computation (always preferred for today — avoids stale midnight rows)
    live = await svc.compute_live_summary(today)
    if live is not None:
        return _build_summary_response(live, personal, summary_source="live_compute")

    # 2. Fallback: persisted summary (finalized row or manually written)
    row = await svc.get_daily_summary(today)
    if row is not None:
        return _build_summary_response(row, personal, summary_source="persisted_row")

    raise HTTPException(status_code=404, detail="No summary available yet.")


@router.get("/daily-summary/{date_str}", response_model=DailySummaryResponse)
async def get_summary_by_date(
    date_str: str,
    svc: TrackingService = Depends(_tracking_svc),
) -> DailySummaryResponse:
    """Return the three numbers for a specific date (YYYY-MM-DD)."""
    target   = _parse_date(date_str)
    personal = await svc.get_personal_model()
    row = await svc.get_daily_summary(target)
    src: Literal["live_compute", "persisted_row"] = "persisted_row"
    if row is None:
        row = await svc.compute_live_summary(target)
        src = "live_compute"
    if row is None:
        raise HTTPException(status_code=404, detail=f"No summary found for {date_str}.")
    return _build_summary_response(row, personal, summary_source=src)


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
    windows_processed:  int
    beats_received:     int


@router.post("/ingest", response_model=IngestResponse)
async def ingest_beats(
    body:    IngestRequest,
    user_id: str           = Depends(_user_id),
    svc:     TrackingService = Depends(_tracking_svc),
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
    ingest_limiter.check(user_id)
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
    first_win_start: Optional[datetime] = None
    for bucket in buckets:
        ppi_vals = [b.ppi_ms for b in bucket]
        ts_vals  = [b.ts for b in bucket]
        win_start = datetime.fromtimestamp(bucket[0].ts, tz=UTC)
        win_end   = datetime.fromtimestamp(bucket[-1].ts, tz=UTC)

        if first_win_start is None:
            first_win_start = win_start

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

    logger.info("INGEST uid=%s context=%s windows_processed=%d beats=%d", svc._uid, context, windows_processed, len(beats))

    return IngestResponse(
        windows_processed=windows_processed,
        beats_received=len(beats),
    )


@router.get("/stress-state", response_model=StressStateResponse)
async def get_stress_state(
    include_cohort: bool = False,
    svc: TrackingService = Depends(_tracking_svc),
) -> StressStateResponse:
    """
    Smoothed point-in-time stress vs personal reference + short trend.

    Uses last ~8h of 5-min background windows for \"now\"; up to 28d history
    for personal percentile zone cutpoints. When enough same DOW/hour samples
    exist, blends in a time-of-day RMSSD median (see ``reference_type``).

    ``include_cohort=true`` returns a ``cohort`` block only if the user opted in
    via onboarding ``compare_to_peers: true`` (Phase 7 — approximate, disclaimer).
    """
    r = await svc.get_stress_state(include_cohort=include_cohort)
    cohort: Optional[CohortInsightResponse] = None
    if include_cohort:
        cohort = CohortInsightResponse(
            enabled=r.cohort_enabled,
            band=r.cohort_band,
            disclaimer=r.cohort_disclaimer,
        )
    return StressStateResponse(
        stress_now_zone=r.stress_now_zone,
        stress_now_index=r.stress_now_index,
        stress_now_percent=r.stress_now_percent,
        trend=r.trend,
        confidence=r.confidence,
        reference_type=r.reference_type,
        as_of=r.as_of,
        rmssd_smoothed_ms=r.rmssd_smoothed_ms,
        zone_cut_index_low=r.zone_cut_index_low,
        zone_cut_index_mid=r.zone_cut_index_mid,
        zone_cut_index_high=r.zone_cut_index_high,
        morning_reference_ms=r.morning_reference_ms,
        time_of_day_reference_ms=r.time_of_day_reference_ms,
        cohort=cohort,
    )


@router.get("/morning-recap", response_model=MorningRecapResponse)
async def get_morning_recap(
    svc: TrackingService = Depends(_tracking_svc),
) -> MorningRecapResponse:
    """Yesterday (IST) daily summary for the morning close card."""
    raw = await svc.get_morning_recap()
    blk = raw.get("summary")
    summary = MorningRecapSummaryBlock(**blk) if blk else None
    if summary is not None:
        recap_date = _parse_date(raw["for_date"])
        sleep_night_date, sleep_subtext = _sleep_recovery_context(recap_date)
        summary.sleep_recovery_night_date = sleep_night_date
        summary.sleep_recovery_subtext = sleep_subtext
        summary.score_explanation = _build_score_explanation(
            stress_load_score=summary.stress_load_score,
            waking_recovery_score=summary.waking_recovery_score,
            sleep_recovery_score=summary.sleep_recovery_score,
            day_type=summary.day_type,
        )
    return MorningRecapResponse(
        for_date=raw["for_date"],
        should_show=raw["should_show"],
        acknowledged_for_date=raw["acknowledged_for_date"],
        summary=summary,
    )


@router.post("/morning-recap/ack")
async def ack_morning_recap(
    body: MorningRecapAckRequest,
    svc: TrackingService = Depends(_tracking_svc),
) -> dict:
    """Mark morning recap as seen for ``for_date`` (usually yesterday, IST)."""
    fd = _parse_date(body.for_date)
    await svc.ack_morning_recap(fd)
    return {"ok": True, "for_date": body.for_date}


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
    entries = [
        HistoryEntry(
            summary_date=row.summary_date.date().isoformat() if row.summary_date else "",
            stress_load_score=row.stress_load_score,
            recovery_score=getattr(row, "waking_recovery_score", None),
            waking_recovery_score=getattr(row, "waking_recovery_score", None),
            sleep_recovery_score=(
                (
                    getattr(row, "sleep_recovery_score", None)
                    if getattr(row, "sleep_recovery_score", None) is not None
                    else (
                        round(
                            max(
                                0.0,
                                min(
                                    100.0,
                                    (((getattr(row, "raw_recovery_area_sleep", 0.0) or 0.0) / row.ns_capacity_recovery) * 100.0),
                                ),
                            ),
                            1,
                        )
                        if getattr(row, "ns_capacity_recovery", None) and row.ns_capacity_recovery > 0
                        else None
                    )
                )
                if getattr(row, "sleep_ts", None) is not None
                else None
            ),
            sleep_recovery_night_date=_sleep_recovery_context(row.summary_date.date() if row.summary_date else None)[0],
            sleep_recovery_subtext=_sleep_recovery_context(row.summary_date.date() if row.summary_date else None)[1],
            net_balance=getattr(row, "net_balance", None),
            day_type=row.day_type,
            is_estimated=row.is_estimated,
            is_partial_data=getattr(row, "is_partial_data", None),
            **_pipeline_meta(row, "persisted_row"),
        )
        for row in rows
    ]

    # Keep History in lockstep with the morning-reset cycle (not midnight rollover).
    # Derive effective "today" from the same recap day anchor used by Home recap.
    recap = await svc.get_morning_recap()
    recap_for_date = _parse_date(recap["for_date"])
    cycle_today_local = recap_for_date + timedelta(days=1)

    # Overlay live summary for the active cycle day.
    # Stored rows can lag behind the latest open-session recomputation.
    live_today = await svc.compute_live_summary(cycle_today_local)
    if live_today is not None:
        today_key = cycle_today_local.isoformat()
        replaced = False
        for i, e in enumerate(entries):
            if e.summary_date == today_key:
                entries[i] = HistoryEntry(
                    summary_date=today_key,
                    stress_load_score=live_today.stress_load_score,
                    recovery_score=live_today.waking_recovery_score,
                    waking_recovery_score=live_today.waking_recovery_score,
                    sleep_recovery_score=getattr(live_today, 'sleep_recovery_score', None),
                    sleep_recovery_night_date=_sleep_recovery_context(cycle_today_local)[0],
                    sleep_recovery_subtext=_sleep_recovery_context(cycle_today_local)[1],
                    net_balance=live_today.net_balance,
                    day_type=live_today.day_type,
                    is_estimated=live_today.is_estimated,
                    is_partial_data=live_today.is_partial_data,
                    **_pipeline_meta(live_today, "live_compute"),
                )
                replaced = True
                break
        if not replaced:
            entries.insert(
                0,
                HistoryEntry(
                    summary_date=today_key,
                    stress_load_score=live_today.stress_load_score,
                    recovery_score=live_today.waking_recovery_score,
                    waking_recovery_score=live_today.waking_recovery_score,
                    sleep_recovery_score=getattr(live_today, 'sleep_recovery_score', None),
                    sleep_recovery_night_date=_sleep_recovery_context(cycle_today_local)[0],
                    sleep_recovery_subtext=_sleep_recovery_context(cycle_today_local)[1],
                    net_balance=live_today.net_balance,
                    day_type=live_today.day_type,
                    is_estimated=live_today.is_estimated,
                    is_partial_data=live_today.is_partial_data,
                    **_pipeline_meta(live_today, "live_compute"),
                ),
            )
    return entries
