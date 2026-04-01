"""
coach/prompt_templates.py

Builds (system_prompt, user_prompt) tuples for each trigger type.

Architecture (Phase 4+)
-----------------------
- One shared persona (`_VERITY_PERSONA`) replaces multiple rule-heavy system prompts.
- Layer 2 coach narrative is the primary “context file” — injected up to NARRATIVE_MAX_CHARS.
- Per-trigger user prompts describe the task + JSON shape + a few guardrails.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import json

from coach.context_builder import CoachContext
from coach.input_builder import CoachInputPacket
from coach.tone_selector import TONE_DESCRIPTIONS


# ── Shared constants ───────────────────────────────────────────────────────────

# Match Layer 2 injection across morning/plan/nudge and CoachContext-driven prompts.
NARRATIVE_MAX_CHARS = 8000


# ── Single shared persona (Layer 3 + conversation via build_prompts) ─────────

_VERITY_PERSONA = """\
You are Verity — ZenFlow's personal health coach.
You are warm, direct, honest, and human. You know this user from their profile narrative.
Never use clinical or technical terms (for example HRV, RMSSD, vagal, cortisol, autonomic, parasympathetic).
Never give medical advice or diagnose.
When the user shares something personal — a preference, habit, or feeling — acknowledge it naturally before anything else. Treat known facts as memory.
If the topic drifts to finance, legal advice, or unrelated hobbies, redirect gently and differently each time — never use a fixed script.
Output only valid JSON when the user prompt asks for JSON. No markdown fences around JSON.
"""


# ── Layer 2 — Daily Coaching Narrative prompt ─────────────────────────────────

_LAYER2_NARRATIVE_SYSTEM = """\
You are ZenFlow's daily coaching narrative writer.

Your job:
  1) Read the user's personality snapshot inputs and today's physiological context.
  2) Write ONE coherent internal narrative the coach will read.

Non-negotiable rules
--------------------
- No medical/technical terms. If unsure, write "Insufficient data".
- Never suggest clinical treatment or diagnose.
- Be grounded: every major statement must map to a provided data signal.
- Use simple Indian English. Short sentences.
- The output MUST use EXACTLY the section headers below and in the same order.
- Bullet points MUST start with "•" and be 1 sentence each.

Output headers (exact, ordered):
PHYSIO PROFILE
YESTERDAY RECAP
SUBJECTIVE ALIGNMENT
BEHAVIORAL SIGNALS
LONGITUDINAL SIGNALS
WHAT THEY LIKE / WHAT HELPS
READINESS VERDICT
WATCH TODAY
"""


def build_layer2_narrative_prompt(packet: CoachInputPacket) -> tuple[str, str]:
    """
    Build (system_prompt, user_prompt) for the single comprehensive Layer 2 call.
    """

    def _json(x: Any, *, max_chars: int = 6000) -> str:
        raw = json.dumps(x, ensure_ascii=False, default=str)
        return raw if len(raw) <= max_chars else raw[:max_chars] + "…"

    today_row = None
    yesterday_row = None
    if packet.daily_trajectory:
        for r in packet.daily_trajectory:
            if r.get("date") == packet.today_local_date:
                today_row = r
        if packet.daily_trajectory:
            if today_row is not None:
                idx = packet.daily_trajectory.index(today_row)
                if idx - 1 >= 0:
                    yesterday_row = packet.daily_trajectory[idx - 1]
            elif len(packet.daily_trajectory) >= 2:
                today_row = packet.daily_trajectory[-1]
                yesterday_row = packet.daily_trajectory[-2]

    return (
        _LAYER2_NARRATIVE_SYSTEM,
        f"""\
USER_ID: {packet.user_id}
TODAY_LOCAL_DATE: {packet.today_local_date}

PERSONAL_MODEL:
{_json(packet.personal_model)}

DAILY_TRAJECTORY_14D:
{_json(packet.daily_trajectory)}

TODAY_ROW (best-effort):
{_json(today_row)}

YESTERDAY_ROW (best-effort):
{_json(yesterday_row)}

MORNING_READS_7D:
{_json(packet.morning_reads)}

STRESS_WINDOWS_48H:
{_json(packet.stress_windows_48h)}

RECOVERY_WINDOWS_48H:
{_json(packet.recovery_windows_48h)}

BACKGROUND_BINS_24H:
{_json(packet.background_bins_24h)}

CHECK_INS_7D:
{_json(packet.check_ins_7d)}

HABIT_EVENTS_72H:
{_json(packet.habit_events_72h)}

ANXIETY_EVENTS_14D:
{_json(packet.anxiety_events_14d)}

CONVERSATION_EVENTS_3D:
{_json(packet.conversation_events_3d)}

USER_FACTS:
{_json(packet.user_facts)}

TAG_PATTERN:
{_json(packet.tag_pattern)}

USER_HABITS:
{_json(packet.user_habits)}

SESSIONS_14D:
{_json(packet.sessions_14d)}

PLAN_DEVIATIONS_30D:
{_json(packet.plan_deviations_30d)}

ADHERENCE_30D:
{_json(packet.adherence_30d)}

EXISTING_UUP_NARRATIVE (previous narrative for continuity; can be empty):
{_json(packet.uup.get("previous_coach_narrative"), max_chars=2000)}
""".strip(),
    )


# ── Layer 3 — Morning brief ───────────────────────────────────────────────────


def build_layer3_morning_brief_prompt(
    packet: CoachInputPacket,
    uup_narrative: str,
) -> tuple[str, str]:
    """
    Build (system_prompt, user_prompt) for the Layer 3 morning brief call.
    """
    yesterday_date = None
    try:
        y_dt = datetime.strptime(packet.today_local_date, "%Y-%m-%d").date()
        yesterday_date = (y_dt - timedelta(days=1)).isoformat()
    except Exception:
        yesterday_date = None

    yesterday_row = None
    if packet.daily_trajectory and yesterday_date:
        for r in packet.daily_trajectory:
            if r.get("date") == yesterday_date:
                yesterday_row = r
                break

    def _row_min(r: Any) -> dict[str, Any]:
        # Omit deprecated readiness_score — cite stress + recovery only (matches app).
        return {
            "date": r.get("date"),
            "day_type": r.get("day_type"),
            "waking_recovery_score": r.get("waking_recovery_score"),
            "sleep_recovery_score": r.get("sleep_recovery_score"),
            "stress_load_score": r.get("stress_load_score"),
        }

    narrative_excerpt = (uup_narrative or "")[:NARRATIVE_MAX_CHARS]

    user_prompt = f"""\
TODAY_LOCAL_DATE: {packet.today_local_date}

USER PROFILE — read first (Layer 2 narrative):
{narrative_excerpt}

DAY_STATE DECISION RULE:
  - Determine "day_state" from YESTERDAY_ROW only.
  - Do NOT use today's data to choose day_state.
  - You may still write brief/evidence/action for today.

DATA NOTES:
  - stress_load_score: 0–10 scale — cite as "X.X/10"
  - waking_recovery_score, sleep_recovery_score: 0–100 — cite as "XX%" or "XX/100"

YESTERDAY_ROW:
{json.dumps(_row_min(yesterday_row or {}), ensure_ascii=False, default=str)}

TASK: Write the morning brief — how today looks for this person and the one most important thing to do.
Do not cite readiness as a single number. Use stress and recovery signals instead.

OUTPUT — valid JSON only, exactly these keys:
{{
  "day_state": "green"|"yellow"|"relaxed"|"red",
  "day_confidence": "high"|"medium"|"low",
  "brief_text": "2–3 short lines in plain language",
  "evidence": "one sentence — the main signal behind your read",
  "one_action": "one specific thing for today (15 words max)"
}}
""".strip()

    return _VERITY_PERSONA, user_prompt


# ── Layer 3 — Plan brief + donts ────────────────────────────────────────────────


def build_layer3_plan_brief_prompt(
    packet: CoachInputPacket,
    uup_narrative: str,
    plan_items: list[dict[str, Any]],
) -> tuple[str, str]:
    narrative_excerpt = (uup_narrative or "")[:NARRATIVE_MAX_CHARS]
    user_prompt = f"""\
TODAY_LOCAL_DATE: {packet.today_local_date}

USER PROFILE (Layer 2 narrative):
{narrative_excerpt}

TODAY PLAN ITEMS:
{json.dumps(plan_items, ensure_ascii=False, default=str)[:5000]}

TODAY ROW (stress/recovery context):
{json.dumps(packet.daily_trajectory[-1] if packet.daily_trajectory else {}, ensure_ascii=False, default=str)[:1500]}

TASK: Explain WHY each plan item fits this person today. Do not repeat the morning brief or restate green/yellow/red. Start with the activity names.
"avoid_items": 1–2 things to ease off today with a short reason. Labels must be plain English (e.g. "intense exercise") — no underscores or slugs.

OUTPUT JSON only, exactly:
{{
  "brief": "exactly 2 sentences: (1) name activities and why prescribed, (2) mechanism or expected benefit in plain words",
  "avoid_items": [ {{"label": "plain English", "reason": "short reason"}} ]
}}
""".strip()
    return _VERITY_PERSONA, user_prompt


# ── Layer 3 — Nudge ───────────────────────────────────────────────────────────


def build_layer3_nudge_prompt(
    packet: CoachInputPacket,
    uup_narrative: str,
    trigger_type: str,
    trigger_context: dict[str, Any],
) -> tuple[str, str]:
    narrative_excerpt = (uup_narrative or "")[:NARRATIVE_MAX_CHARS]
    user_prompt = f"""\
TODAY_LOCAL_DATE: {packet.today_local_date}
TRIGGER_TYPE: {trigger_type}

USER PROFILE (Layer 2 narrative):
{narrative_excerpt}

TRIGGER_CONTEXT:
{json.dumps(trigger_context, ensure_ascii=False, default=str)[:2000]}

TODAY SNAPSHOT (if scores present: stress 0–10 as X.X/10; recovery 0–100):
{json.dumps(packet.daily_trajectory[-1] if packet.daily_trajectory else {}, ensure_ascii=False, default=str)[:800]}

TASK: One short nudge for this person and this trigger. At most 60 words in "message".

OUTPUT JSON only: {{ "message": "<string>" }}
""".strip()
    return _VERITY_PERSONA, user_prompt


# ── Trigger-specific user prompt templates (CoachContext path) ─────────────────


def build_prompts(ctx: CoachContext) -> tuple[str, str]:
    """
    Build (system_prompt, user_prompt) for the given CoachContext.
    """
    tone_desc = TONE_DESCRIPTIONS.get(ctx.tone, "")
    user_prompt = _TRIGGER_BUILDERS[ctx.trigger_type](ctx, tone_desc)
    return _VERITY_PERSONA, user_prompt


def _user_profile_block(ctx: CoachContext) -> str:
    if not ctx.uup_narrative:
        return "USER PROFILE (Layer 2 narrative): not available yet.\n\n"
    excerpt = (ctx.uup_narrative or "")[:NARRATIVE_MAX_CHARS]
    return (
        "USER PROFILE — who this person is (Layer 2 narrative; read before responding):\n"
        f"{excerpt}\n\n"
    )


def _build_post_session(ctx: CoachContext, tone_desc: str) -> str:
    session = ctx.session_data or {}
    coherence_peak = session.get("coherence_peak", "unavailable")
    arc_completed = session.get("arc_completed", "unavailable")
    arc_vs_personal = session.get("arc_vs_personal", "")
    duration_min = session.get("duration_minutes", "?")

    return f"""\
{_user_profile_block(ctx)}TRIGGER: post_session
TONE: {ctx.tone}
TONE GUIDE: {tone_desc}

USER PATTERN (short):
    Pattern: {ctx.pattern_label}
    {ctx.stage_in_words}

SESSION DATA (personal-relative):
    Duration: {duration_min} minutes
    Coherence peak: {coherence_peak}
    Arc completed: {arc_completed}
    Arc vs personal average: {arc_vs_personal}

7-DAY CONTEXT:
    Trajectory: {ctx.trajectory}
    Sessions this week: {ctx.sessions_this_week}
    Recovery note: {ctx.recovery_pattern_note}

TASK: Reflect this session in plain language. Cite a number when one is available; otherwise stay directional.

OUTPUT JSON:
{{
  "summary": "<20–45 words — what the session showed>",
  "observation": "<10–35 words — what the data supported>",
  "reinforcement": "<10–35 words — optional encouragement; include a digit if you cite a metric, else leave empty>",
  "next_session": "<1 sentence — when and what next>",
  "follow_up_question": "<short question, or null>"
}}
"""


def _build_morning_brief(ctx: CoachContext, tone_desc: str) -> str:
    stress_s = ctx.stress_score
    stress_10 = (
        round(stress_s / 10.0, 1) if stress_s is not None else None
    )
    recovery = ctx.recovery_score if ctx.recovery_score is not None else "unavailable"
    balance = ctx.net_balance if ctx.net_balance is not None else "unavailable"
    stress_line = (
        f"{stress_10}/10" if stress_10 is not None else "unavailable"
    )
    return f"""\
{_user_profile_block(ctx)}TRIGGER: morning_brief
TONE: {ctx.tone}
TONE GUIDE: {tone_desc}

USER PATTERN:
    Pattern: {ctx.pattern_label}
    {ctx.stage_in_words}

TODAY'S SCORES (cite these if you use numbers):
    Stress load: {stress_line}
    Waking recovery: {recovery}/100
    Net balance: {balance}

7-DAY CONTEXT:
    Trajectory: {ctx.trajectory}
    Load trend: {ctx.load_trend}
    Recovery note: {ctx.recovery_pattern_note}
    Sessions this week: {ctx.sessions_this_week}

PRESCRIPTION:
    Session type: {ctx.prescription.session_type}
    Duration: {ctx.prescription.session_duration} minutes
    Window: {ctx.prescription.session_window}

OUTPUT JSON:
{{
  "summary": "<20–45 words — morning state in plain language>",
  "observation": "<10–35 words — what today implies>",
  "action": "<10–28 words — one clear move>",
  "window": "<1 short sentence — when to act>",
  "encouragement": "<optional — include a digit if non-empty>",
  "follow_up_question": "<short question, or null>"
}}
"""


def _build_nudge(ctx: CoachContext, tone_desc: str) -> str:
    last_ago = (
        f"{ctx.last_session_ago_days} days" if ctx.last_session_ago_days else "unknown"
    )
    return f"""\
{_user_profile_block(ctx)}TRIGGER: nudge
TONE: {ctx.tone}
TONE GUIDE: {tone_desc}

USER PATTERN:
    Pattern: {ctx.pattern_label}
    {ctx.stage_in_words}

CURRENT STATE:
    Read quality: {ctx.morning_read_quality}
    Load trend: {ctx.load_trend}
    Last session: {last_ago} ago
    Consecutive low days: {ctx.consecutive_low_days}

PRESCRIPTION:
    Session type: {ctx.prescription.session_type}
    Duration: {ctx.prescription.session_duration} minutes
    Window: {ctx.prescription.session_window}

OUTPUT JSON:
{{
  "summary": "<20–45 words — brief check-in>",
  "action": "<10–28 words — single clear action>",
  "follow_up_question": "<short question, or null>"
}}
"""


def _build_weekly_review(ctx: CoachContext, tone_desc: str) -> str:
    dims = ""
    if ctx.session_data and "dimension_breakdown" in ctx.session_data:
        for d, v in ctx.session_data["dimension_breakdown"].items():
            dims += f"    {d.replace('_',' ')}: {v}/20\n"

    milestone_block = ""
    if ctx.milestone and ctx.milestone_evidence:
        milestone_block = f"""
MILESTONE:
    {ctx.milestone} — {ctx.milestone_evidence}
"""

    return f"""\
{_user_profile_block(ctx)}TRIGGER: weekly_review
TONE: {ctx.tone}
TONE GUIDE: {tone_desc}

USER PATTERN:
    Pattern: {ctx.pattern_label} — {ctx.pattern_summary}
    {ctx.stage_in_words} ({ctx.weeks_in_stage} weeks in stage)

7-DAY SUMMARY:
    Score delta: {ctx.score_7d_delta if ctx.score_7d_delta is not None else 'insufficient data'}
    Trajectory: {ctx.trajectory}
    Load trend: {ctx.load_trend}
    Sessions: {ctx.sessions_this_week}
    Recovery note: {ctx.recovery_pattern_note}

DIMENSION SCORES:
{dims if dims else '    unavailable'}
{milestone_block}
OUTPUT JSON:
{{
  "summary": "<20–45 words — weekly state in plain English>",
  "week_narrative": "<30–80 words — what the week showed, no clinical terms>",
  "dimension_spotlight": "<1–2 sentences on the most notable dimension change>",
  "encouragement": "<optional — cite milestone evidence number if milestone, else omit>",
  "action": "<10–28 words — single priority for the coming week>",
  "follow_up_question": "<string, or null>"
}}
"""


def _build_physio_section(ctx: CoachContext) -> str:
    """
    TODAY'S PHYSIO for conversation turns. Stress load is shown on 0–10 to match the app.
    """
    score_parts = []
    if ctx.stress_score is not None:
        stress_10 = round(float(ctx.stress_score) / 10.0, 1)
        score_parts.append(f"stress load: {stress_10}/10")
    if ctx.recovery_score is not None:
        score_parts.append(f"waking recovery: {ctx.recovery_score}/100")
    if ctx.net_balance is not None:
        sign = "+" if ctx.net_balance >= 0 else ""
        score_parts.append(f"balance: {sign}{ctx.net_balance:.1f}")

    if not score_parts:
        return ""

    lines = ["TODAY'S PHYSIO:"]
    lines.append("    " + " | ".join(score_parts))

    if ctx.trajectory and ctx.trajectory not in ("", "unknown"):
        lines.append(f"    7-day direction: {ctx.trajectory}")

    if ctx.avoid_items:
        avoid_strs = [
            a.get("reason") or a.get("slug_or_label") or a.get("label", "")
            for a in ctx.avoid_items[:2]
        ]
        avoid_strs = [s for s in avoid_strs if s]
        if avoid_strs:
            lines.append("    Ease off today: " + "; ".join(avoid_strs))

    return "\n".join(lines) + "\n"


def _build_conversation_turn(ctx: CoachContext, tone_desc: str) -> str:
    conv_block = ""
    if ctx.conversation_summary:
        conv_block = f"CONVERSATION SO FAR (summary):\n    {ctx.conversation_summary}\n"

    signals_block = ""
    if ctx.extracted_signals:
        signals_block = "EXTRACTED SIGNALS:\n" + "\n".join(
            f"    - {s}" for s in ctx.extracted_signals
        ) + "\n"

    physio_block = _build_physio_section(ctx)

    psych_line = f"PSYCH INSIGHT: {ctx.psych_insight}\n" if ctx.psych_insight else ""

    facts_block = ""
    if ctx.user_facts:
        facts_str = ", ".join(ctx.user_facts[:10])
        facts_block = f"WHAT YOU ALREADY KNOW (confirmed facts):\n    {facts_str}\n\n"

    new_block = ""
    if ctx.newly_extracted_facts:
        new_block = "WHAT THEY JUST SHARED (this message — acknowledge if present):\n    " + (
            "; ".join(ctx.newly_extracted_facts[:8])
        ) + "\n\n"

    engagement_block = ""
    if ctx.engagement_tier in ("at_risk", "churned"):
        engagement_block = (
            f"ENGAGEMENT: User is '{ctx.engagement_tier}' — keep the reply warm and low-friction.\n"
        )

    last_said = ctx.last_user_said or "(no user message)"

    return f"""\
{_user_profile_block(ctx)}TRIGGER: conversation_turn
TONE: {ctx.tone}
TONE GUIDE: {tone_desc} (emotion guide, not a script)

{facts_block}{new_block}{engagement_block}{conv_block}{signals_block}{physio_block}{psych_line}
USER JUST SAID:
    "{last_said}"

CURRENT PRESCRIPTION:
    {ctx.prescription.session_type} — {ctx.prescription.session_duration}min — {ctx.prescription.reason_tag}

HOW TO RESPOND:
    - Reply in your own words; match the user's energy (short if brief, fuller if they asked something real).
    - If they shared something new, acknowledge it first.
    - Ask a natural follow-up question unless the user has explicitly wrapped up (said bye, thanks, done, etc.).
    - Do not re-introduce yourself.

OUTPUT JSON only:
{{
  "reply": "<natural coach reply>",
  "follow_up_question": "<string or null>"
}}
"""


# ── Dispatch table ────────────────────────────────────────────────────────────

_TRIGGER_BUILDERS = {
    "morning_brief":     _build_morning_brief,
    "post_session":      _build_post_session,
    "nudge":             _build_nudge,
    "weekly_review":     _build_weekly_review,
    "conversation_turn": _build_conversation_turn,
}
