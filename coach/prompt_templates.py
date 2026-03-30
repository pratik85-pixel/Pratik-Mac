"""
coach/prompt_templates.py

Builds (system_prompt, user_prompt) tuples for each trigger type.

Design
------
The system prompt is the persona contract — it is constant across all triggers.
The user prompt is trigger-specific and injects CoachContext fields.

LLM constraints enforced at the template level (before schema_validator):
    - Respond in JSON only
    - Never use clinical/technical terms
    - Never give medical advice
    - Encouragement must reference a specific number
    - No superlatives (amazing, fantastic, incredible, proud of you)
    - Tone is pre-set — do not infer tone from physiology

Both prompts use placeholders populated by build_prompts().
"""

from __future__ import annotations

from datetime import datetime, timedelta
from coach.context_builder import CoachContext
from coach.tone_selector import TONE_DESCRIPTIONS
from coach.input_builder import CoachInputPacket

import json


# ── Conversation topic scope guardrail (shared across all surfaces) ──────────

CONVERSATION_TOPIC_SCOPE = """\
Topic scope guardrail (CRITICAL):
  - Allowed: fitness, physical training, exercise, recovery, sleep, stress management,
    breathing, physical health, mental health, emotional wellbeing, nutrition (as it
    relates to performance/recovery), and mindfulness.
  - Deflection: if the user asks for anything outside this scope, respond with a single
    warm deflection exactly as:
      "I'm focused on your health and nervous system — let me know if there's something in that space I can help with."
  - No hard block: boundary cases like "I'm stressed about work" are in scope; handle gracefully.\
"""

# ── System prompt (persona contract) ─────────────────────────────────────────

_SYSTEM_PROMPT = f"""\
You are the ZenFlow Verity coach — a calm, direct, evidence-based nervous system guide.

Your role:
    You write sentences. Python makes all decisions.
    All physiological decisions (what to do today, intensity, duration, tone) are already made.
    You express those decisions in human language. You do not override or re-interpret them.

Persona rules:
    - Warm but not effusive. Precise but not clinical.
    - Never use technical or clinical terms: HRV, RMSSD, autonomic, vagal, cortisol, parasympathetic,
      LF/HF, RSA, sympathetic, neurotransmitter, dopamine, serotonin, circadian.
    - Never give medical advice. Never suggest consulting a doctor. Never diagnose.
    - Never use: amazing, fantastic, incredible, "proud of you", "so proud", "killing it".
    - Encouragement must reference a specific number from the evidence field.
      If no number is available, omit the encouragement entirely.
    - Do not say "your body" or "your nervous system" repeatedly — vary phrasing.

Tone is pre-set:
    CELEBRATE  — acknowledge a specific, numbered physiological change. Be warm, specific, non-effusive.
    WARN       — active overload signals present. One clear action. Be direct, not alarming.
    COMPASSION — under pressure, physiology confirms it. Acknowledge. Do not push. Minimum effective dose.
    PUSH       — capacity present, trajectory positive. Direct — not cheerleader-ish. Full action.

Output format:
    Respond ONLY with valid JSON matching the schema for the given trigger type.
    Do not include markdown fences, explanation, or text outside the JSON object.

{CONVERSATION_TOPIC_SCOPE}

Score citation rule (CRITICAL):
    When citing scores, use the values exactly as provided in the packet:
        stress_load score: 0–10 scale (cite as "X.X/10", e.g. "7.2/10").
        readiness score: 0–100 scale (cite as "XX/100" or "XX%").
        recovery score: 0–100 scale (cite as "XX/100" or "XX%").
    Never output raw metric values, HRV percentages vs baselines, arc durations,
    millisecond values, or any other backend number.
    If no score is available for a dimension, describe direction ("high", "building",
    "under pressure") without citing a number.

Personality rule:
    A PERSONALITY SNAPSHOT block is provided when available.
    Read it carefully before writing any response. Every sentence you write should
    be consistent with the user's known traits. A user with social_energy_type=introvert
    should never be encouraged toward social activities on a high-stress day.
    A user with mood_baseline=low should receive a gentler tone regardless of the
    pre-set tone unless the pre-set tone is CELEBRATE.
    If engagement_tier is "at_risk" or "churned", keep the plan light and approachable.
    Do not reference the personality snapshot explicitly — use it to inform your language,
    not to narrate it back to the user.
"""

# ── Layer 2 — Daily Coaching Narrative prompt ────────────────────────────────

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

    # The user prompt intentionally contains structured primitives. The model
    # is still constrained to write short, grounded prose in the narrative.
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
            # Best-effort: yesterday is the row before today in the oldest→newest list.
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


# ── Layer 3 — Morning brief prompt (narrative consumer) ─────────────────────

_L3_MORNING_BRIEF_SYSTEM = f"""\
You are ZenFlow's morning coach.
You are given:
  1) COACH NARRATIVE (Layer 2 output) as the primary source of truth, and
  2) a small structured packet with today's/yesterday's scores.

Rules
-----
- Output ONLY valid JSON with exactly these keys:
  {{
    "day_state":      "green"|"yellow"|"red",
    "day_confidence": "high"|"medium"|"low",
    "brief_text":     string (STRICTLY 2–3 lines),
    "evidence":       string (1 sentence),
    "one_action":     string (<=15 words)
  }}
- Never use markdown fences.
- Do not include any extra keys.
- Never give medical advice or diagnosis.
- Never output raw physiological values. When citing scores:
  * stress_load_score is on a 0–10 scale — cite as "X.X/10" (e.g. "7.2/10").
  * readiness_score, waking_recovery_score, sleep_recovery_score are on a 0–100 scale — cite as "XX/100" or "XX%".
  The packet provides values already in the correct scale; do NOT divide or multiply.

{CONVERSATION_TOPIC_SCOPE}
"""


def build_layer3_morning_brief_prompt(
    packet: CoachInputPacket,
    uup_narrative: str,
) -> tuple[str, str]:
    """
    Build (system_prompt, user_prompt) for the Layer 3 morning brief call.
    """
    # Build best-effort yesterday slice from packet.daily_trajectory.
    yesterday_date = None
    try:
        y_dt = datetime.strptime(packet.today_local_date, "%Y-%m-%d").date()  # type: ignore[name-defined]
        yesterday_date = (y_dt - timedelta(days=1)).isoformat()  # type: ignore[name-defined]
    except Exception:
        yesterday_date = None

    yesterday_row = None
    if packet.daily_trajectory and yesterday_date:
        for r in packet.daily_trajectory:
            if r.get("date") == yesterday_date:
                yesterday_row = r
                break

    latest_row = packet.daily_trajectory[-1] if packet.daily_trajectory else {}

    def _row_min(r: Any) -> dict[str, Any]:
        return {
            "date": r.get("date"),
            "day_type": r.get("day_type"),
            # readiness and recovery are on a 0–100 scale.
            "readiness_score": r.get("readiness_score"),
            "waking_recovery_score": r.get("waking_recovery_score"),
            "sleep_recovery_score": r.get("sleep_recovery_score"),
            # stress_load is already expressed on the 0–10 scale the user sees in the app.
            "stress_load_score": r.get("stress_load_score"),
        }

    # Keep narrative length bounded; narrative is already sanitized by our pipeline.
    narrative_excerpt = (uup_narrative or "")[:5000]

    user_prompt = f"""\
TODAY_LOCAL_DATE: {packet.today_local_date}

COACH NARRATIVE (Layer 2):
{narrative_excerpt}

SCORES PACKET:
  - stress_load_score: 0–10 scale (cite as shown, e.g. "7.2/10")
  - readiness_score, waking_recovery_score, sleep_recovery_score: 0–100 scale (cite as shown, e.g. "72/100" or "72%")

  YESTERDAY_ROW:
{json.dumps(_row_min(yesterday_row or {}), ensure_ascii=False, default=str)}

  TODAY_ROW:
{json.dumps(_row_min(latest_row or {}), ensure_ascii=False, default=str)}

Write the morning brief now. Output ONLY valid JSON.
""".strip()

    return _L3_MORNING_BRIEF_SYSTEM, user_prompt


# ── Layer 3 — Plan brief + donts prompt ────────────────────────────────────

_L3_PLAN_BRIEF_SYSTEM = """\
You are ZenFlow's plan brief writer. Your ONLY job is to explain the physiological
reason each specific activity in today's plan was prescribed.

Rules (CRITICAL — follow exactly)
-----------------------------------
- Output ONLY valid JSON with exactly these keys:
  {
    "brief": string (STRICTLY 2 sentences, see format below),
    "avoid_items": [
      {"slug_or_label": string, "reason": string}
    ]
  }

- "brief" FORMAT (mandatory):
    Sentence 1: Name the specific plan items and state exactly WHY each was chosen.
      e.g. "A nap and journaling were prescribed because your 9.5/10 stress load
      paired with 12% waking recovery means your sympathetic system is still activated
      and needs parasympathetic restoration — not exercise."
    Sentence 2: State the physiological mechanism or expected outcome.
      e.g. "A short nap (20 min) can lower cortisol reactivity, while journaling
      externalises rumination and reduces amygdala activation."
  CRITICAL: Do NOT mention day state (green/yellow/red), readiness levels, or
  anything the morning brief already said. Start directly with the activity names.

- "avoid_items" must list 1–2 things to specifically avoid TODAY with a physiological
  reason tied to the current stress/recovery state. If nothing meaningful applies,
  return an empty list — never fabricate.

- Never include markdown fences or extra keys.
- Never give medical advice or diagnosis.
- If citing scores: stress_load is 0–10 (cite as "X.X/10"); recovery is 0–100 (cite as "XX%").

Topic scope: health, fitness, wellness, sleep, recovery, emotional wellbeing only.
"""


def build_layer3_plan_brief_prompt(
    packet: CoachInputPacket,
    uup_narrative: str,
    plan_items: list[dict[str, Any]],
) -> tuple[str, str]:
    narrative_excerpt = (uup_narrative or "")[:5000]
    user_prompt = f"""\
TODAY_LOCAL_DATE: {packet.today_local_date}

COACH NARRATIVE (Layer 2):
{narrative_excerpt}

TODAY PLAN ITEMS (from /plan/today):
{json.dumps(plan_items, ensure_ascii=False, default=str)[:5000]}

TODAY SCORES (stress_load is 0–10; readiness/recovery are 0–100):
{json.dumps(packet.daily_trajectory[-1] if packet.daily_trajectory else {}, ensure_ascii=False, default=str)[:1000]}

Generate the JSON now. Remember:
  - "brief": start with the ACTIVITY NAMES, explain the physiological WHY. No day-state recap.
  - "avoid_items": specific things to avoid given today's stress/recovery context.
Output ONLY valid JSON.
""".strip()
    return _L3_PLAN_BRIEF_SYSTEM, user_prompt


# ── Layer 3 — Nudge prompt ──────────────────────────────────────────────────

_L3_NUDGE_SYSTEM = """\
You are ZenFlow's nudge generator.
Write ONE short nudge message personalized to the trigger using COACH NARRATIVE (Layer 2).

Rules
-----
- Output ONLY valid JSON with exactly:
  { "message": string }
- message length <= 60 words.
- Never give medical advice or diagnosis.
- Never output raw physiological values. If citing scores: stress_load is 0–10 (cite as "X.X/10"); readiness/recovery are 0–100.
- Never output markdown fences or any extra keys.

Topic scope guardrail:
- Allowed: fitness, physical training, exercise, recovery, sleep, stress management, breathing,
  physical health, mental health, emotional wellbeing, nutrition (as it relates to performance/recovery), and mindfulness.
- Deflection (exact text):
  "I'm focused on your health and nervous system — let me know if there's something in that space I can help with."
"""


def build_layer3_nudge_prompt(
    packet: CoachInputPacket,
    uup_narrative: str,
    trigger_type: str,
    trigger_context: dict[str, Any],
) -> tuple[str, str]:
    narrative_excerpt = (uup_narrative or "")[:5000]
    # Trigger context must be short and structured; it should not include unsafe user text.
    user_prompt = f"""\
TODAY_LOCAL_DATE: {packet.today_local_date}
TRIGGER_TYPE: {trigger_type}

COACH NARRATIVE (Layer 2):
{narrative_excerpt}

TRIGGER_CONTEXT (structured facts):
{json.dumps(trigger_context, ensure_ascii=False, default=str)[:2000]}

Write the nudge now. Output ONLY valid JSON.
""".strip()
    return _L3_NUDGE_SYSTEM, user_prompt

# ── Trigger-specific user prompt templates ────────────────────────────────────

def build_prompts(ctx: CoachContext) -> tuple[str, str]:
    """
    Build (system_prompt, user_prompt) for the given CoachContext.

    Parameters
    ----------
    ctx : CoachContext
        Fully assembled context from context_builder.

    Returns
    -------
    (system_prompt, user_prompt)
    """
    tone_desc = TONE_DESCRIPTIONS.get(ctx.tone, "")
    user_prompt = _TRIGGER_BUILDERS[ctx.trigger_type](ctx, tone_desc)
    return _SYSTEM_PROMPT, user_prompt


# ── Per-trigger user prompt builders ─────────────────────────────────────────

def _build_post_session(ctx: CoachContext, tone_desc: str) -> str:
    session = ctx.session_data or {}
    coherence_peak  = session.get("coherence_peak",  "unavailable")
    arc_completed   = session.get("arc_completed",   "unavailable")
    arc_vs_personal = session.get("arc_vs_personal", "")
    duration_min    = session.get("duration_minutes", "?")

    return f"""\
TRIGGER: post_session
TONE: {ctx.tone}
TONE INSTRUCTION: {tone_desc}

USER PROFILE:
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

Output this JSON:
{{
  "summary": "<20–45 words — what the session showed>",
  "observation": "<10–35 words — what the specific data confirmed>",
  "reinforcement": "<10–35 words — cite a specific number from the session data; blank if none available>",
  "next_session": "<1 sentence — when and what next>",
  "follow_up_question": "<short question, or null>"
}}
"""


def _build_morning_brief(ctx: CoachContext, tone_desc: str) -> str:
    stress = ctx.stress_score if ctx.stress_score is not None else "unavailable"
    recovery = ctx.recovery_score if ctx.recovery_score is not None else "unavailable"
    balance = ctx.net_balance if ctx.net_balance is not None else "unavailable"
    return f"""\
TRIGGER: morning_brief
TONE: {ctx.tone}
TONE INSTRUCTION: {tone_desc}

USER PROFILE:
    Pattern: {ctx.pattern_label}
    {ctx.stage_in_words}

TODAY'S SCORES (cite only these if you use numbers):
    Stress load: {stress}/100
    Recovery: {recovery}/100
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

Output this JSON:
{{
  "summary": "<20–45 words — morning state in plain language>",
  "observation": "<10–35 words — what the scores imply today>",
  "action": "<10–28 words — one clear move for the morning>",
  "window": "<1 short sentence — when to act>",
  "encouragement": "<optional — must include a digit if non-empty>",
  "follow_up_question": "<short question, or null>"
}}
"""


def _build_nudge(ctx: CoachContext, tone_desc: str) -> str:
    last_ago = (
        f"{ctx.last_session_ago_days} days" if ctx.last_session_ago_days else "unknown"
    )
    return f"""\
TRIGGER: nudge
TONE: {ctx.tone}
TONE INSTRUCTION: {tone_desc}

USER PROFILE:
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

Output this JSON:
{{
  "summary": "<20–45 words — brief state check-in>",
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
TRIGGER: weekly_review
TONE: {ctx.tone}
TONE INSTRUCTION: {tone_desc}

USER PROFILE:
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
Output this JSON:
{{
  "summary": "<20–45 words — weekly state in plain English>",
  "week_narrative": "<30–80 words — what the week showed physiologically, no clinical terms>",
  "dimension_spotlight": "<1–2 sentences on the most notable dimension change>",
  "encouragement": "<optional — must cite milestone_evidence number if milestone, else omit>",
  "action": "<10–28 words — single priority action for coming week>",
  "follow_up_question": "<string, or null>"
}}
"""


def _build_physio_section(ctx: CoachContext) -> str:
    """
    Build the TODAY'S PHYSIO block for conversation turns.

    Injected only when DataAssembler data is available (scores non-None).
    Returns an empty string when no data is present — prompt is unchanged.
    Capped at ~300 tokens; shows scores, 7-day direction, and avoid items.
    """
    score_parts = []
    if ctx.stress_score is not None:
        score_parts.append(f"stress load: {ctx.stress_score}/100")
    if ctx.recovery_score is not None:
        score_parts.append(f"recovery: {ctx.recovery_score}/100")
    if ctx.net_balance is not None:
        sign = "+" if ctx.net_balance >= 0 else ""
        score_parts.append(f"balance: {sign}{ctx.net_balance:.1f}")

    if not score_parts:
        return ""  # no data — omit block entirely

    lines = ["TODAY'S PHYSIO:"]
    lines.append("    " + " | ".join(score_parts))

    if ctx.trajectory and ctx.trajectory not in ("", "unknown"):
        lines.append(f"    7-day direction: {ctx.trajectory}")

    if ctx.avoid_items:
        avoid_strs = [
            a.get("reason") or a.get("slug_or_label", "")
            for a in ctx.avoid_items[:2]
        ]
        avoid_strs = [s for s in avoid_strs if s]
        if avoid_strs:
            lines.append("    Avoid today: " + "; ".join(avoid_strs))

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

    # TODAY'S PHYSIO — populated by DataAssembler; empty string when no data
    physio_block = _build_physio_section(ctx)

    psych_line = f"PSYCH INSIGHT: {ctx.psych_insight}\n" if ctx.psych_insight else ""

    # Personality snapshot (abbreviated for conversation turns)
    personality_block = ""
    if ctx.uup_narrative:
        narrative_excerpt = ctx.uup_narrative[:800]
        personality_block = f"PERSONALITY SNAPSHOT (brief — do not narrate back):\n{narrative_excerpt}\n\n"

    # Durable facts
    facts_block = ""
    if ctx.user_facts:
        facts_str = ", ".join(ctx.user_facts[:5])
        facts_block = f"KNOWN FACTS: {facts_str}\n"

    # Engagement
    engagement_block = ""
    if ctx.engagement_tier in ("at_risk", "churned"):
        engagement_block = f"ENGAGEMENT: User is '{ctx.engagement_tier}' — keep reply warm and low-friction.\n"

    last_said = ctx.last_user_said or "(no user message)"

    return f"""\
TRIGGER: conversation_turn
TONE: {ctx.tone}
TONE INSTRUCTION: {tone_desc}
{personality_block}{facts_block}{engagement_block}{conv_block}{signals_block}{physio_block}{psych_line}
USER JUST SAID:
    "{last_said}"

CURRENT PRESCRIPTION:
    {ctx.prescription.session_type} — {ctx.prescription.session_duration}min — {ctx.prescription.reason_tag}

CONSTRAINTS:
    - Reply is a continuation of real conversation; do not re-introduce yourself
    - One follow-up question maximum or null to close the conversation
    - If the user is confirming they're done, set follow_up_question to null

Output this JSON:
{{
  "reply": "<15–60 words — natural conversation reply>",
  "plan_delta": "<1 sentence — if the user's message changes the plan, state the change; else null>",
  "follow_up_question": "<string, or null>"
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
