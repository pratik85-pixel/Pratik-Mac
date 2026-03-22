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

from coach.context_builder import CoachContext
from coach.tone_selector import TONE_DESCRIPTIONS


# ── System prompt (persona contract) ─────────────────────────────────────────

_SYSTEM_PROMPT = """\
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

Score citation rule (CRITICAL):
    When citing a number in your JSON response, you MUST use one of:
        readiness score (0–100), stress score (0–100), or recovery score (0–100).
    Never output raw metric values, HRV percentages vs baselines, arc durations,
    millisecond values, or any other backend number. Use only the provided scores.
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


def _build_conversation_turn(ctx: CoachContext, tone_desc: str) -> str:
    conv_block = ""
    if ctx.conversation_summary:
        conv_block = f"CONVERSATION SO FAR (summary):\n    {ctx.conversation_summary}\n"

    signals_block = ""
    if ctx.extracted_signals:
        signals_block = "EXTRACTED SIGNALS:\n" + "\n".join(
            f"    - {s}" for s in ctx.extracted_signals
        ) + "\n"

    score_line = ""
    parts = []
    if ctx.readiness_score is not None:
        parts.append(f"readiness {ctx.readiness_score}/100")
    if ctx.stress_score is not None:
        parts.append(f"stress {ctx.stress_score}/100")
    if ctx.recovery_score is not None:
        parts.append(f"recovery {ctx.recovery_score}/100")
    if parts:
        score_line = "CURRENT SCORES: " + ", ".join(parts) + "\n"

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
{personality_block}{facts_block}{engagement_block}{conv_block}{signals_block}{score_line}{psych_line}
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
    "post_session":      _build_post_session,
    "nudge":             _build_nudge,
    "weekly_review":     _build_weekly_review,
    "conversation_turn": _build_conversation_turn,
}
