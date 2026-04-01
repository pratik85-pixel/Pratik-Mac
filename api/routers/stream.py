"""
api/routers/stream.py

WebSocket endpoint for live hardware stream from the bridge.

Protocol
--------
Client → Server (first message — handshake):
    {"type": "handshake", "user_id": "<id>", "session_id": "<id>"}

Client → Server (subsequent messages — PPI batch):
    {"type": "ppi", "ppi_ms": [800, 820, ...], "timestamps_s": [0.0, 0.8, ...]}

Server → Client (after each PPI batch):
    {"type": "metrics", "session_id": "...", "elapsed_s": 45.0,
     "coherence": 0.72, "zone": 3, "rmssd_ms": 52.1,
     "breath_bpm": 6.0, "windows_so_far": 2, "prf_bpm": 6.5}

Server → Client (on error):
    {"type": "error", "detail": "..."}

Server → Client (on handshake ack):
    {"type": "ack", "session_id": "..."}
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.services.session_service import SessionService

logger  = logging.getLogger(__name__)
router  = APIRouter()


def _get_session_service(ws: WebSocket) -> SessionService:
    return ws.app.state.session_service


@router.websocket("/ws/stream")
async def stream_endpoint(websocket: WebSocket) -> None:
    """
    Live PPI stream receiver.
    One WebSocket connection = one active session.
    """
    await websocket.accept()
    svc: SessionService = _get_session_service(websocket)

    session_id: Optional[str] = None
    user_id: Optional[str] = None
    handshake_done = False

    try:
        async for raw in websocket.iter_text():
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "detail": "invalid JSON"})
                continue

            msg_type = msg.get("type", "")

            # ── Handshake ──────────────────────────────────────────────────────
            if msg_type == "handshake":
                if handshake_done:
                    await websocket.send_json({"type": "error", "detail": "already handshaked"})
                    continue

                session_id = msg.get("session_id")
                user_id = msg.get("user_id")
                if not session_id or not user_id or not svc.is_active(session_id):
                    await websocket.send_json({
                        "type":   "error",
                        "detail": "valid user_id + session_id required",
                    })
                    continue
                owner = svc.get_active_session_owner(session_id)
                if owner != user_id:
                    await websocket.send_json({
                        "type": "error",
                        "detail": "session does not belong to this user",
                    })
                    continue

                handshake_done = True
                await websocket.send_json({"type": "ack", "session_id": session_id})
                logger.info("ws_handshake session=%s user=%s", session_id, user_id)
                continue

            # ── PPI batch ─────────────────────────────────────────────────────
            if msg_type == "ppi":
                if not handshake_done or session_id is None:
                    await websocket.send_json({"type": "error", "detail": "handshake required"})
                    continue

                ppi_ms: list[float]       = [float(x) for x in msg.get("ppi_ms", [])]
                timestamps_s: list[float] = [float(x) for x in msg.get("timestamps_s", [])]

                if not ppi_ms or len(ppi_ms) != len(timestamps_s):
                    await websocket.send_json({
                        "type":   "error",
                        "detail": "ppi_ms and timestamps_s must be equal-length non-empty lists",
                    })
                    continue

                metrics = await asyncio.to_thread(
                    svc.ingest_ppi,
                    session_id,
                    ppi_ms,
                    timestamps_s,
                    user_id,
                )
                if metrics is None:
                    await websocket.send_json({"type": "error", "detail": "session not found"})
                    continue

                await websocket.send_json({
                    "type":           "metrics",
                    "session_id":     metrics.session_id,
                    "elapsed_s":      round(metrics.elapsed_s, 1),
                    "coherence":      round(metrics.coherence, 3) if metrics.coherence is not None else None,
                    "zone":           metrics.zone,
                    "rmssd_ms":       round(metrics.rmssd_ms, 1)  if metrics.rmssd_ms  is not None else None,
                    "breath_bpm":     round(metrics.breath_bpm, 2) if metrics.breath_bpm is not None else None,
                    "windows_so_far": metrics.windows_so_far,
                    "prf_bpm":        metrics.prf_bpm,
                })
                continue

            # ── Ping (keep-alive) ─────────────────────────────────────────────
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            await websocket.send_json({"type": "error", "detail": f"unknown type: {msg_type}"})

    except WebSocketDisconnect:
        logger.info("ws_disconnect session=%s", session_id)
    except Exception as exc:
        logger.exception("ws_error session=%s: %s", session_id, exc)
        try:
            await websocket.send_json({"type": "error", "detail": "internal error"})
        except Exception:
            pass
