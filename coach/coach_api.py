"""
coach/coach_api.py

Pipeline orchestrator — the single entry point for generating coaching output.

Pipeline
--------
    plan_replanner   →  context_builder  →  tone_selector
          ↓
    prompt_templates  →  LLM  →  schema_validator  →  safety_filter
          ↓
    output (or local_engine fallback, or static fallback)

LLM call contract:
    - JSON mode / structured output only (tool_use or response_format=json_object)
    - Max 2 retries on validation failure
    - On retry exhaustion: local_engine fallback
    - Never exposes "fallback" indicator to user

Offline / always-offline:
    - If llm_client is None: local_engine runs directly, no retries
    - Caller passes llm_client=None for offline sessions

Design principle:
    "The LLM writes sentences. Python makes all decisions."
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

from coach.context_builder import CoachContext
from coach.prompt_templates import build_prompts
from coach.schema_validator import validate_output
from coach.safety_filter import screen_text
from coach.local_engine import generate_local_output
from archetypes.scorer import NSHealthProfile


logger = logging.getLogger(__name__)


# ── Constants ──────────────────────────────────────────────────────────────────

MAX_RETRIES = 2
_SOURCE_LLM          = "llm"
_SOURCE_LOCAL_ENGINE = "local_engine"
_SOURCE_STATIC       = "static"


# ── LLMClient protocol (duck-typed) ──────────────────────────────────────────

# The llm_client is any object with:
#     .chat(system: str, user: str) -> str   (returns raw JSON string)
#
# This keeps coach_api.py independent of the specific LLM provider.


# ── Public API ────────────────────────────────────────────────────────────────

def generate_response(
    ctx: CoachContext,
    profile: NSHealthProfile,
    llm_client: Optional[Any] = None,
) -> dict:
    """
    Generate coaching output for the given CoachContext.

    Parameters
    ----------
    ctx : CoachContext
        Fully assembled context from context_builder.build_coach_context().
    profile : NSHealthProfile
        Current scoring profile — passed to local_engine for stage_focus.
    llm_client : Any | None
        LLM client instance. None → always use local_engine (offline mode).

    Returns
    -------
    dict
        Cleaned, validated output matching the trigger_type schema.
        "source" field is stripped before this dict is returned.
    """
    # ── Offline mode ──────────────────────────────────────────────────────────
    if llm_client is None:
        logger.debug("coach_api: offline mode — using local_engine")
        output = generate_local_output(ctx, profile)
        output.pop("source", None)
        return output

    # ── LLM mode with retry loop ──────────────────────────────────────────────
    system_prompt, user_prompt = build_prompts(ctx)
    last_errors: list[str] = []

    for attempt in range(1, MAX_RETRIES + 2):  # attempts: 1, 2 (retry), 3 (→ fallback)
        if attempt > MAX_RETRIES + 1:
            break

        try:
            raw_text = llm_client.chat(system_prompt, user_prompt)
        except Exception as exc:
            logger.warning("coach_api: LLM call failed on attempt %d: %s", attempt, exc)
            break

        # Parse JSON
        try:
            raw_dict = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            logger.warning("coach_api: JSON parse failed on attempt %d: %s", attempt, exc)
            last_errors = ["json_parse_error"]
            continue

        # Screen LLM output for safety
        all_text = " ".join(str(v) for v in raw_dict.values() if isinstance(v, str))
        safety = screen_text(all_text)
        if not safety.is_safe:
            logger.warning(
                "coach_api: safety triggered in LLM output (attempt %d): %s",
                attempt, safety.category,
            )
            # Safety trigger — do not retry; return handoff
            return _safety_payload(ctx.trigger_type, safety.handoff_message)

        # Validate schema
        valid, cleaned, errors = validate_output(raw_dict, ctx.trigger_type, ctx)
        last_errors = errors

        if "medical_advice" in " ".join(errors):
            logger.warning("coach_api: medical advice in LLM output (attempt %d)", attempt)
            return _safety_payload(ctx.trigger_type, "")

        if valid:
            logger.debug("coach_api: valid output on attempt %d", attempt)
            cleaned.pop("source", None)
            return cleaned

        logger.info("coach_api: validation failed attempt %d: %s", attempt, errors)
        # Inject error context into next attempt's user prompt
        user_prompt = _inject_retry_context(user_prompt, errors)

    # ── Fallback: local_engine ────────────────────────────────────────────────
    logger.info(
        "coach_api: LLM exhausted (%d attempts), errors=%s — falling back to local_engine",
        MAX_RETRIES, last_errors,
    )
    output = generate_local_output(ctx, profile)
    output.pop("source", None)
    return output


# ── Helpers ───────────────────────────────────────────────────────────────────

def _inject_retry_context(user_prompt: str, errors: list[str]) -> str:
    """
    Append a retry note to the user prompt so the LLM understands what failed.

    Only the last error category is surfaced — avoids polluting the prompt.
    """
    if not errors:
        return user_prompt

    # Show only the category part (before colon) of the first error
    first_category = errors[0].split(":")[0]

    note = (
        f"\n\nPREVIOUS ATTEMPT FAILED — reason: {first_category}. "
        "Please re-read the constraints and generate a corrected response. "
        "Output JSON only."
    )
    return user_prompt + note


def _safety_payload(trigger_type: str, handoff_message: str) -> dict:
    """
    Return a safe-handoff payload in the correct schema shape for the trigger_type.
    The content is the handoff message rather than any coaching content.
    """
    msg = handoff_message or (
        "I want to make sure you have the right support. "
        "Please reach out to someone — call or text 988 if you're in the US."
    )

    # All trigger types have at least summary + follow_up_question or reply
    if trigger_type == "conversation_turn":
        return {"reply": msg, "plan_delta": None, "follow_up_question": None}
    return {
        "summary":           msg,
        "action":            "",
        "follow_up_question": None,
    }
