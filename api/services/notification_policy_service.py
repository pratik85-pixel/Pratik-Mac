"""
api/services/notification_policy_service.py

Notification Policy Engine (v1).

Builds user notification feed and applies actions for:
  - event_trigger (actionable)
  - nudge (informational)
  - check_in (actionable)
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import api.db.schema as db
from api.services.push_service import send_expo_push_for_user
from api.services.tagging_service import TaggingService
from api.utils import parse_uuid

from tracking.cycle_boundaries import product_calendar_timezone, utc_instant_bounds_for_local_calendar_date

EVENT_STRESS_TAG_OPTIONS = [
    "work_calls",
    "commute",
    "caffeine",
    "argument",
    "workout",
    "other",
]
EVENT_RECOVERY_TAG_OPTIONS = [
    "walk",
    "reading_music",
    "social_family",
    "zenflow_session",
    "breath_work",
    "other",
]


class NotificationPolicyService:
    def __init__(
        self,
        db_session: AsyncSession,
        user_id: str,
        llm_client: Optional[Any] = None,
    ):
        self._db = db_session
        self._uid_raw = user_id
        self._uid = parse_uuid(user_id)
        self._tagging = TaggingService(db_session)
        self._llm_client = llm_client

    async def get_feed(
        self,
        limit: int = 20,
        cursor: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> dict[str, Any]:
        if self._uid is None:
            return {"items": [], "next_cursor": None, "server_time": datetime.now(UTC).isoformat()}

        await self._sync_event_trigger_notifications(since=since)
        await self._sync_checkin_notifications()
        await self._sync_nudge_notifications()
        await self._expire_time_based_notifications()

        q = (
            select(db.NotificationEvent)
            .where(db.NotificationEvent.user_id == self._uid)
            .where(db.NotificationEvent.status == "unread")
            .order_by(db.NotificationEvent.created_at.desc())
        )
        if since is not None:
            q = q.where(db.NotificationEvent.created_at >= since)
        cursor_dt = _parse_cursor(cursor)
        if cursor_dt is not None:
            q = q.where(db.NotificationEvent.created_at < cursor_dt)

        rows = (await self._db.execute(q.limit(limit + 1))).scalars().all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = rows[-1].created_at.isoformat() if has_more and rows else None

        return {
            "items": [self._event_to_feed_item(r) for r in rows],
            "next_cursor": next_cursor,
            "server_time": datetime.now(UTC).isoformat(),
        }

    async def apply_action(
        self,
        *,
        notification_id: str,
        action_type: str,
        payload: Optional[dict[str, Any]] = None,
        acted_at: Optional[datetime] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        if self._uid is None:
            return {"ok": False, "error": {"code": "unauthorized", "message": "Invalid X-User-Id", "details": {}}}

        notif_uuid = parse_uuid(notification_id)
        if notif_uuid is None:
            return {"ok": False, "error": {"code": "validation_error", "message": "notification_id must be UUID", "details": {}}}

        if idempotency_key:
            existing_action = await self._load_action_by_idempotency(idempotency_key)
            if existing_action is not None:
                notif = await self._db.get(db.NotificationEvent, existing_action.notification_id)
                return {
                    "ok": True,
                    "notification_id": notification_id,
                    "new_status": notif.status if notif is not None else "acted",
                    "effects": {"idempotent_replay": True},
                }

        notif = await self._db.get(db.NotificationEvent, notif_uuid)
        if notif is None or notif.user_id != self._uid:
            return {"ok": False, "error": {"code": "not_found", "message": "Notification not found", "details": {}}}

        if notif.status in ("acted", "dismissed", "expired"):
            return {
                "ok": False,
                "error": {"code": "conflict", "message": f"Notification already {notif.status}", "details": {}},
            }

        payload = payload or {}
        effects: dict[str, Any] = {}

        if action_type == "tag_event":
            selected_tag = str(payload.get("selected_tag") or "").strip()
            window_id = str(payload.get("window_id") or "").strip()
            window_type = str(payload.get("window_type") or "").strip()
            if not selected_tag or not window_id or window_type not in ("stress", "recovery"):
                return {
                    "ok": False,
                    "error": {
                        "code": "validation_error",
                        "message": "window_id, window_type, selected_tag are required for tag_event",
                        "details": {},
                    },
                }
            tag_res = await self._tagging.tag_window(
                user_id=self._uid_raw,
                window_id=window_id,
                window_type=window_type,
                slug=selected_tag,
            )
            if not tag_res.success:
                return {"ok": False, "error": {"code": "bad_request", "message": tag_res.error or "Tag failed", "details": {}}}
            notif.status = "acted"
            notif.acted_at = acted_at or datetime.now(UTC)
            effects = {"tag_saved": True}
        elif action_type == "submit_checkin":
            ok, msg = await self._store_checkin_from_payload(payload)
            if not ok:
                return {"ok": False, "error": {"code": "validation_error", "message": msg, "details": {}}}
            notif.status = "acted"
            notif.acted_at = acted_at or datetime.now(UTC)
            effects = {"checkin_saved": True, "coach_refresh_queued": True}
        elif action_type == "dismiss":
            notif.status = "dismissed"
            notif.acted_at = acted_at or datetime.now(UTC)
            effects = {"dismissed": True}
        else:
            return {"ok": False, "error": {"code": "validation_error", "message": "Unknown action_type", "details": {}}}

        action_row = db.NotificationAction(
            notification_id=notif.id,
            user_id=self._uid,
            action_type=action_type,
            request_json={"notification_id": notification_id, "action_type": action_type, "payload": payload},
            idempotency_key=idempotency_key,
        )
        self._db.add(action_row)
        await self._db.commit()

        return {
            "ok": True,
            "notification_id": notification_id,
            "new_status": notif.status,
            "effects": effects,
        }

    async def submit_checkin(
        self,
        *,
        notification_id: str,
        responses: dict[str, Any],
        submitted_at: Optional[datetime] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        return await self.apply_action(
            notification_id=notification_id,
            action_type="submit_checkin",
            payload=responses,
            acted_at=submitted_at,
            idempotency_key=idempotency_key,
        )

    async def dismiss(
        self,
        *,
        notification_id: str,
        dismissed_at: Optional[datetime] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        return await self.apply_action(
            notification_id=notification_id,
            action_type="dismiss",
            payload={},
            acted_at=dismissed_at,
            idempotency_key=idempotency_key,
        )

    async def _sync_event_trigger_notifications(self, since: Optional[datetime]) -> None:
        if self._uid is None:
            return

        lookback = since or (datetime.now(UTC) - timedelta(days=3))
        stress_rows_changed = False

        stress_rows = (
            await self._db.execute(
                select(db.StressWindow)
                .where(db.StressWindow.user_id == self._uid)
                .where(db.StressWindow.tag.is_(None))
                .where(db.StressWindow.started_at >= lookback)
                .order_by(db.StressWindow.started_at.desc())
                .limit(500)
            )
        ).scalars().all()

        rec_rows = (
            await self._db.execute(
                select(db.RecoveryWindow)
                .where(db.RecoveryWindow.user_id == self._uid)
                .where(db.RecoveryWindow.tag.is_(None))
                .where(db.RecoveryWindow.context == "background")
                .where(db.RecoveryWindow.started_at >= lookback)
                .order_by(db.RecoveryWindow.started_at.desc())
                .limit(500)
            )
        ).scalars().all()

        for s in stress_rows:
            dedupe = self._event_window_dedupe_key(
                window_type="stress",
                started_at=s.started_at,
                ended_at=s.ended_at,
            )
            notif = await self._create_notification_if_missing(
                dedupe_key=dedupe,
                category="event_trigger",
                priority="high",
                requires_action=True,
                title="Tag this stress event",
                body="Detected stress event. Select the closest trigger.",
                deeplink=f"zenflow://tag-event?window_type=stress&window_id={s.id}",
                payload_json={
                    "window_id": str(s.id),
                    "window_type": "stress",
                    "suggested_tag": s.tag_candidate,
                    "tag_options": EVENT_STRESS_TAG_OPTIONS,
                },
                expires_at=s.started_at + timedelta(days=7),
            )
            # Keep StressWindow nudge flags in sync with notification creation.
            # Even if the notification already existed (dedupe hit), this backfills
            # legacy rows where nudge_sent was never persisted.
            if notif is not None and not bool(getattr(s, "nudge_sent", False)):
                s.nudge_sent = True
                stress_rows_changed = True

        for r in rec_rows:
            dedupe = self._event_window_dedupe_key(
                window_type="recovery",
                started_at=r.started_at,
                ended_at=r.ended_at,
            )
            await self._create_notification_if_missing(
                dedupe_key=dedupe,
                category="event_trigger",
                priority="normal",
                requires_action=True,
                title="Tag this recovery event",
                body="Detected recovery event. Select the closest recovery source.",
                deeplink=f"zenflow://tag-event?window_type=recovery&window_id={r.id}",
                payload_json={
                    "window_id": str(r.id),
                    "window_type": "recovery",
                    "suggested_tag": None,
                    "tag_options": EVENT_RECOVERY_TAG_OPTIONS,
                },
                expires_at=r.started_at + timedelta(days=7),
            )

        if stress_rows_changed:
            await self._db.commit()

    async def _sync_checkin_notifications(self) -> None:
        if self._uid is None:
            return
        tz = product_calendar_timezone()
        now_ist = datetime.now(tz)
        today = now_ist.date()
        day_start_utc, day_end_utc = utc_instant_bounds_for_local_calendar_date(today)

        has_checkin = (
            await self._db.execute(
                select(db.CheckIn.id)
                .where(db.CheckIn.user_id == self._uid)
                .where(db.CheckIn.created_at >= day_start_utc)
                .where(db.CheckIn.created_at < day_end_utc)
                .limit(1)
            )
        ).scalar_one_or_none() is not None

        primary_key = f"checkin:{today.isoformat()}:primary"
        reminder_key = f"checkin:{today.isoformat()}:reminder"
        if has_checkin:
            await self._expire_unread_by_dedupe_prefix(f"checkin:{today.isoformat()}:")
            return

        if not (18 <= now_ist.hour < 22):
            return

        primary = await self._find_notification_by_dedupe(primary_key)
        if primary is None:
            await self._create_notification_if_missing(
                dedupe_key=primary_key,
                category="check_in",
                priority="critical",
                requires_action=True,
                title="Daily check-in (30 sec)",
                body="This helps coach personalize tomorrow better.",
                deeplink="zenflow://checkin",
                payload_json={"question_set": "v1_daily_evening"},
                expires_at=day_end_utc,
            )
            return

        reminder = await self._find_notification_by_dedupe(reminder_key)
        if reminder is None and primary.created_at <= datetime.now(UTC) - timedelta(minutes=90):
            await self._create_notification_if_missing(
                dedupe_key=reminder_key,
                category="check_in",
                priority="high",
                requires_action=True,
                title="Reminder: daily check-in",
                body="Quick check-in keeps your profile accurate.",
                deeplink="zenflow://checkin",
                payload_json={"question_set": "v1_daily_evening", "reminder": True},
                expires_at=day_end_utc,
            )

    async def _sync_nudge_notifications(self) -> None:
        if self._uid is None:
            return
        tz = product_calendar_timezone()
        now_ist = datetime.now(tz)
        today = now_ist.date()
        day_start_utc, day_end_utc = utc_instant_bounds_for_local_calendar_date(today)

        nudge_rows = (
            await self._db.execute(
                select(db.NotificationEvent)
                .where(db.NotificationEvent.user_id == self._uid)
                .where(db.NotificationEvent.category == "nudge")
                .where(db.NotificationEvent.created_at >= day_start_utc)
                .where(db.NotificationEvent.created_at < day_end_utc)
                .order_by(db.NotificationEvent.created_at.desc())
            )
        ).scalars().all()
        if len(nudge_rows) >= 2:
            return
        if nudge_rows and nudge_rows[0].created_at >= datetime.now(UTC) - timedelta(minutes=60):
            return

        # Fetch UUP narrative/watch bullets for personalization (if present)
        uup_row = (
            await self._db.execute(
                select(db.UserUnifiedProfile).where(db.UserUnifiedProfile.user_id == self._uid)
            )
        ).scalar_one_or_none()

        coach_watch = list(getattr(uup_row, "coach_watch_notes", None) or [])
        uup_narrative = getattr(uup_row, "coach_narrative", None)
        narrative_exists = bool(uup_narrative)

        def _watch_snippet(idx: int) -> str:
            if idx < 0 or idx >= len(coach_watch):
                return ""
            return str(coach_watch[idx])[:160]

        # Build Layer 1 packet once if we will call LLM.
        packet = None
        if self._llm_client is not None and narrative_exists:
            try:
                from coach.input_builder import build_coach_input_packet
                packet = await build_coach_input_packet(self._db, self._uid)
            except Exception:
                packet = None

        async def _render_nudge(
            *,
            trigger_type: str,
            trigger_context: dict[str, Any],
            fallback_message: str,
        ) -> str:
            if self._llm_client is None or packet is None or not uup_narrative:
                return fallback_message
            try:
                from coach.prompt_templates import build_layer3_nudge_prompt

                sys_prompt, user_prompt = build_layer3_nudge_prompt(
                    packet=packet,
                    uup_narrative=uup_narrative,
                    trigger_type=trigger_type,
                    trigger_context=trigger_context,
                )
                raw = self._llm_client.chat(sys_prompt, user_prompt)
                cleaned = raw.strip()
                cleaned = re.sub(r"^```(?:json)?\\n?", "", cleaned)
                cleaned = re.sub(r"\\n?```$", "", cleaned)
                m = re.search(r"\\{.*\\}", cleaned, re.DOTALL)
                if not m:
                    return fallback_message
                obj = json.loads(m.group(0))
                msg = obj.get("message")
                if not msg:
                    return fallback_message
                return str(msg)[:400]
            except Exception:
                return fallback_message

        # Gate: today plan existence is used by multiple triggers.
        plan_row = (
            await self._db.execute(
                select(db.DailyPlan)
                .where(db.DailyPlan.user_id == self._uid)
                .where(db.DailyPlan.plan_date >= day_start_utc)
                .where(db.DailyPlan.plan_date < day_end_utc)
                .order_by(db.DailyPlan.generated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if plan_row is None and not narrative_exists:
            return

        # ── Trigger evaluation (T1..T5) — create at most one notification. ──
        created = 0

        # T2 — Stress off limits
        try:
            cutoff_3h = datetime.now(UTC) - timedelta(hours=3)
            stress_windows_3h = (
                await self._db.execute(
                    select(db.StressWindow.id)
                    .where(db.StressWindow.user_id == self._uid)
                    .where(db.StressWindow.started_at >= cutoff_3h)
                )
            ).scalars().all()
            stress_windows_3h = len(stress_windows_3h)

            latest_summary = (
                await self._db.execute(
                    select(db.DailyStressSummary)
                    .where(db.DailyStressSummary.user_id == self._uid)
                    .where(db.DailyStressSummary.summary_date >= day_start_utc)
                    .where(db.DailyStressSummary.summary_date < day_end_utc)
                    .order_by(db.DailyStressSummary.computed_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            stress_score = getattr(latest_summary, "stress_load_score", None) if latest_summary else None
            if (stress_score is not None and float(stress_score) > 75) or stress_windows_3h >= 2:
                fallback = (
                    "Stress is running high right now. Take 5–10 minutes for breathing + gentle movement."
                    + (f" { _watch_snippet(0)}" if _watch_snippet(0) else "")
                )
                body = await _render_nudge(
                    trigger_type="stress_alert",
                    trigger_context={
                        "stress_score": stress_score,
                        "stress_windows_last_3h": stress_windows_3h,
                    },
                    fallback_message=fallback,
                )
                await self._create_notification_if_missing(
                    dedupe_key=f"nudge:T2:stress:{today.isoformat()}",
                    category="nudge",
                    priority="high",
                    requires_action=False,
                    title="Stress check",
                    body=body,
                    deeplink="zenflow://plan",
                    payload_json={"trigger": "stress_alert"},
                    expires_at=day_end_utc,
                )
                created += 1
        except Exception:
            pass

        # T4 — Sleep reminder (typical_sleep_time - 45 minutes)
        if created < 1:
            try:
                pm_row = (
                    await self._db.execute(
                        select(db.PersonalModel).where(db.PersonalModel.user_id == self._uid)
                    )
                ).scalar_one_or_none()
                typical_sleep = getattr(pm_row, "typical_sleep_time", None) if pm_row else None
                if typical_sleep:
                    h_str, m_str = str(typical_sleep).split(":")
                    sleep_h = int(h_str)
                    sleep_m = int(m_str)
                    typical_sleep_dt = now_ist.replace(
                        hour=sleep_h, minute=sleep_m, second=0, microsecond=0
                    )
                    if (
                        now_ist >= typical_sleep_dt - timedelta(minutes=45)
                        and now_ist <= typical_sleep_dt + timedelta(minutes=60)
                    ):
                        open_session = (
                            await self._db.execute(
                                select(db.BandWearSession)
                                .where(db.BandWearSession.user_id == self._uid)
                                .where(db.BandWearSession.is_closed.is_(False))
                                .order_by(db.BandWearSession.started_at.desc())
                                .limit(1)
                            )
                        ).scalar_one_or_none()
                        has_sleep_data = bool(getattr(open_session, "has_sleep_data", False)) if open_session else False
                        if not has_sleep_data:
                            fallback = (
                                "Time to wind down for sleep. Do your usual calm routine now and keep screens low."
                                + (f" { _watch_snippet(1)}" if _watch_snippet(1) else "")
                            )
                            body = await _render_nudge(
                                trigger_type="sleep_reminder",
                                trigger_context={
                                    "typical_sleep_time": typical_sleep,
                                },
                                fallback_message=fallback,
                            )
                            await self._create_notification_if_missing(
                                dedupe_key=f"nudge:T4:sleep:{today.isoformat()}",
                                category="nudge",
                                priority="high",
                                requires_action=False,
                                title="Wind down",
                                body=body,
                                deeplink="zenflow://sleep",
                                payload_json={"trigger": "sleep_reminder"},
                                expires_at=day_end_utc,
                            )
                            created += 1
            except Exception:
                pass

        # T1 — Plan item incomplete
        if created < 1 and plan_row is not None:
            try:
                items = list(plan_row.items_json or [])
                pending = [i for i in items if not bool(i.get("has_evidence"))]
                if pending:
                    first = pending[0]
                    slug = str(first.get("activity_type_slug") or first.get("id") or "activity")
                    fallback = (
                        "Quick reminder: "
                        + (first.get("title") or "your next activity")
                        + ". Keep momentum for the rest of the day."
                    )
                    if _watch_snippet(2):
                        fallback += f" {_watch_snippet(2)}"
                    body = await _render_nudge(
                        trigger_type="plan_incomplete",
                        trigger_context={
                            "pending_slug": slug,
                            "pending_title": first.get("title"),
                            "priority": first.get("priority"),
                        },
                        fallback_message=fallback,
                    )
                    await self._create_notification_if_missing(
                        dedupe_key=f"nudge:T1:plan:{today.isoformat()}:{slug}",
                        category="nudge",
                        priority="normal",
                        requires_action=False,
                        title="Plan nudge",
                        body=body,
                        deeplink="zenflow://plan",
                        payload_json={"trigger": "plan_incomplete", "slug": slug},
                        expires_at=day_end_utc,
                    )
                    created += 1
            except Exception:
                pass

        # T3 — Morning ready (6–9 IST)
        if created < 1 and plan_row is not None:
            try:
                if 6 <= now_ist.hour <= 9 and narrative_exists:
                    fallback = "Your plan is ready. Put your band on and start your first block."
                    if _watch_snippet(0):
                        fallback += f" {_watch_snippet(0)}"
                    body = await _render_nudge(
                        trigger_type="morning_ready",
                        trigger_context={},
                        fallback_message=fallback,
                    )
                    await self._create_notification_if_missing(
                        dedupe_key=f"nudge:T3:morning_ready:{today.isoformat()}",
                        category="nudge",
                        priority="normal",
                        requires_action=False,
                        title="Your day is ready",
                        body=body,
                        deeplink="zenflow://plan",
                        payload_json={"trigger": "morning_ready"},
                        expires_at=day_end_utc,
                    )
                    created += 1
            except Exception:
                pass

        # T5 — Post-session motivational (session ended in last 5 minutes)
        if created < 1:
            try:
                cutoff_5m = datetime.now(UTC) - timedelta(minutes=5)
                recent_session = (
                    await self._db.execute(
                        select(db.Session)
                        .where(db.Session.user_id == self._uid)
                        .where(db.Session.ended_at.isnot(None))
                        .where(db.Session.ended_at >= cutoff_5m)
                        .order_by(db.Session.ended_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if recent_session and recent_session.ended_at:
                    fallback = "Great session. Now do a calm cool-down and let your recovery catch up."
                    if _watch_snippet(1):
                        fallback += f" {_watch_snippet(1)}"
                    body = await _render_nudge(
                        trigger_type="post_session",
                        trigger_context={
                            "session_id": str(recent_session.id),
                            "session_score": getattr(recent_session, "session_score", None),
                            "ended_at": recent_session.ended_at.isoformat(),
                        },
                        fallback_message=fallback,
                    )
                    await self._create_notification_if_missing(
                        dedupe_key=f"nudge:T5:post_session:{recent_session.id}",
                        category="nudge",
                        priority="normal",
                        requires_action=False,
                        title="Nice session",
                        body=body,
                        deeplink="zenflow://plan",
                        payload_json={"trigger": "post_session"},
                        expires_at=day_end_utc,
                    )
                    created += 1
            except Exception:
                pass

    async def _expire_time_based_notifications(self) -> None:
        if self._uid is None:
            return
        now = datetime.now(UTC)
        rows = (
            await self._db.execute(
                select(db.NotificationEvent)
                .where(db.NotificationEvent.user_id == self._uid)
                .where(db.NotificationEvent.status == "unread")
                .where(db.NotificationEvent.expires_at.is_not(None))
                .where(db.NotificationEvent.expires_at < now)
            )
        ).scalars().all()
        if not rows:
            return
        for r in rows:
            r.status = "expired"
            r.acted_at = now
        await self._db.commit()

    async def _load_action_by_idempotency(self, key: str) -> Optional[db.NotificationAction]:
        if self._uid is None:
            return None
        q = (
            select(db.NotificationAction)
            .where(db.NotificationAction.user_id == self._uid)
            .where(db.NotificationAction.idempotency_key == key)
            .limit(1)
        )
        return (await self._db.execute(q)).scalar_one_or_none()

    async def _find_notification_by_dedupe(self, dedupe_key: str) -> Optional[db.NotificationEvent]:
        if self._uid is None:
            return None
        q = (
            select(db.NotificationEvent)
            .where(db.NotificationEvent.user_id == self._uid)
            .where(db.NotificationEvent.dedupe_key == dedupe_key)
            .order_by(db.NotificationEvent.created_at.desc())
            .limit(1)
        )
        return (await self._db.execute(q)).scalar_one_or_none()

    async def _create_notification_if_missing(
        self,
        *,
        dedupe_key: str,
        category: str,
        priority: str,
        requires_action: bool,
        title: str,
        body: str,
        deeplink: Optional[str],
        payload_json: dict[str, Any],
        expires_at: Optional[datetime],
    ) -> Optional[db.NotificationEvent]:
        if self._uid is None:
            return None
        existing = await self._find_notification_by_dedupe(dedupe_key)
        if existing is not None:
            return existing
        row = db.NotificationEvent(
            user_id=self._uid,
            category=category,
            priority=priority,
            status="unread",
            requires_action=requires_action,
            title=title,
            body=body,
            deeplink=deeplink,
            dedupe_key=dedupe_key,
            payload_json=payload_json,
            expires_at=expires_at,
        )
        self._db.add(row)
        try:
            await self._db.commit()
        except IntegrityError:
            # Concurrent poll/sync requests can race on the same dedupe key.
            # Roll back and return canonical row so we never emit duplicate notifications.
            await self._db.rollback()
            return await self._find_notification_by_dedupe(dedupe_key)
        await self._db.refresh(row)
        # Best-effort push dispatch for background/terminated delivery.
        # Failures are logged and do not affect feed creation.
        await send_expo_push_for_user(
            self._db,
            user_uuid=self._uid,
            title=title,
            body=body,
            data={
                "notification_id": str(row.id),
                "category": category,
                "deeplink": deeplink,
                "payload": payload_json,
            },
        )
        return row

    async def _expire_unread_by_dedupe_prefix(self, prefix: str) -> None:
        if self._uid is None:
            return
        rows = (
            await self._db.execute(
                select(db.NotificationEvent)
                .where(db.NotificationEvent.user_id == self._uid)
                .where(db.NotificationEvent.status == "unread")
                .where(db.NotificationEvent.dedupe_key.like(f"{prefix}%"))
            )
        ).scalars().all()
        if not rows:
            return
        now = datetime.now(UTC)
        for r in rows:
            r.status = "expired"
            r.acted_at = now
        await self._db.commit()

    async def _store_checkin_from_payload(self, payload: dict[str, Any]) -> tuple[bool, str]:
        if self._uid is None:
            return False, "Invalid user"
        try:
            reactivity_0_10 = int(payload.get("reactivity"))
            focus_0_10 = int(payload.get("focus"))
            recovery_0_10 = int(payload.get("recovery"))
        except Exception:
            return False, "reactivity, focus, recovery must be integers"

        if not (0 <= reactivity_0_10 <= 10 and 0 <= focus_0_10 <= 10 and 0 <= recovery_0_10 <= 10):
            return False, "reactivity, focus, recovery must be in range 0..10"

        def to_1_5(v: int) -> int:
            return max(1, min(5, int(round(v / 2.0))))

        row = db.CheckIn(
            user_id=self._uid,
            reactivity=to_1_5(reactivity_0_10),
            focus=to_1_5(focus_0_10),
            recovery=to_1_5(recovery_0_10),
        )
        self._db.add(row)
        return True, "ok"

    @staticmethod
    def _event_window_dedupe_key(
        *,
        window_type: str,
        started_at: Optional[datetime],
        ended_at: Optional[datetime],
    ) -> str:
        """
        Stable dedupe for event-trigger notifications.
        Stress/recovery rows are periodically recomputed (delete+insert), so row IDs
        are not stable. We key by normalized window times instead.
        """
        def _norm(dt: Optional[datetime]) -> str:
            if dt is None:
                return "none"
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC).replace(microsecond=0).isoformat()

        return f"event:{window_type}:{_norm(started_at)}:{_norm(ended_at)}"

    def _event_to_feed_item(self, row: db.NotificationEvent) -> dict[str, Any]:
        payload = row.payload_json or {}
        return {
            "id": str(row.id),
            "category": row.category,
            "priority": row.priority,
            "title": row.title,
            "body": row.body,
            "requires_action": row.requires_action,
            "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "dedupe_key": row.dedupe_key,
            "deeplink": row.deeplink,
            "payload": payload,
            "actions": _actions_for_category(row.category),
        }


def _actions_for_category(category: str) -> list[dict[str, str]]:
    if category == "event_trigger":
        return [
            {"id": "act_tag", "action_type": "tag_event", "label": "Tag now"},
            {"id": "act_dismiss", "action_type": "dismiss", "label": "Later"},
        ]
    if category == "check_in":
        return [
            {"id": "act_checkin", "action_type": "submit_checkin", "label": "Check in"},
            {"id": "act_dismiss", "action_type": "dismiss", "label": "Later"},
        ]
    return [{"id": "act_dismiss", "action_type": "dismiss", "label": "Dismiss"}]


def _parse_cursor(cursor: Optional[str]) -> Optional[datetime]:
    if not cursor:
        return None
    try:
        dt = datetime.fromisoformat(cursor.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _utc_day_bounds_for_ist(d: date) -> tuple[datetime, datetime]:
    """IST calendar day d → [start, end) UTC (delegates to cycle_boundaries)."""
    return utc_instant_bounds_for_local_calendar_date(d)
