"""
coach/safety_filter.py

Safety screening for both user input and LLM output.

Design
------
Two passes:
    1. User input (before it reaches the LLM)
    2. LLM output (before it reaches the user)

On trigger: is_safe=False is returned. The caller (coach_api.py) must:
    - Call memory_store.latch_safety(conversation_id) — one-way latch
    - Return the handoff_message to the user immediately
    - Close the conversation session
    - NOT retry the LLM

Pattern coverage:
    - Hopelessness
    - Worthlessness / self-criticism
    - Self-harm ideation
    - Suicidal ideation
    - Crisis language

The filter is deliberately high-sensitivity and low-specificity.
A false positive that closes a conversation is acceptable.
A false negative that misses a crisis is not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# ── Safety patterns ───────────────────────────────────────────────────────────
# Patterns are checked case-insensitively against the full text.
# Partial-word matches are intentional for catching fragments.

_SELF_HARM_PATTERNS: list[str] = [
    r"\bhurt myself\b",
    r"\bcut myself\b",
    r"\bself.harm",
    r"\bself.injur",
    r"\bwant to die\b",
    r"\bwish i was dead\b",
    r"\bwish i were dead\b",
    r"\bkill myself\b",
    r"\bend my life\b",
    r"\bending my life\b",
    r"\bend it all\b",
    r"\bnot worth living\b",
    r"\bworthless\b",
    r"\bno reason to live\b",
    r"\bno point in living\b",
    r"\bsuicid",
    r"\boverdos",
    r"\bcan't go on\b",
    r"\bcant go on\b",
]

_HOPELESSNESS_PATTERNS: list[str] = [
    r"\bnothing will ever\b",
    r"\balways be this way\b",
    r"\bno hope\b",
    r"\bgive up on everything\b",
    r"\bgiven up on life\b",
    r"\bcompletely hopeless\b",
]

_ALL_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in (_SELF_HARM_PATTERNS + _HOPELESSNESS_PATTERNS)
]

# ── Response ───────────────────────────────────────────────────────────────────

_HANDOFF_MESSAGE = (
    "I want to make sure you have the right support right now. "
    "Please reach out to a crisis line — in the US, text or call 988. "
    "In the UK, call 116 123 (Samaritans). "
    "If you're in immediate danger, please call emergency services."
)

_CATEGORY_SELF_HARM    = "self_harm"
_CATEGORY_HOPELESSNESS = "hopelessness"


# ── SafetyResult dataclass ────────────────────────────────────────────────────

@dataclass
class SafetyResult:
    """
    Output of a safety scan.

    is_safe         — False triggers immediate handoff, no LLM
    category        — "self_harm" | "hopelessness" | None
    matched_pattern — first matching pattern string (for logging) | None
    handoff_message — message to show the user on unsafe result
    """
    is_safe:         bool
    category:        Optional[str]
    matched_pattern: Optional[str]
    handoff_message: str


# ── Public API ────────────────────────────────────────────────────────────────

def screen_text(text: str) -> SafetyResult:
    """
    Screen a string for crisis or self-harm content.

    Parameters
    ----------
    text : str
        User message or LLM output to screen.

    Returns
    -------
    SafetyResult
        is_safe=True if no pattern matched; is_safe=False on any match.
    """
    if not text or not text.strip():
        return SafetyResult(
            is_safe         = True,
            category        = None,
            matched_pattern = None,
            handoff_message = "",
        )

    for pattern in _ALL_PATTERNS:
        if pattern.search(text):
            category = (
                _CATEGORY_SELF_HARM
                if any(pattern.pattern == p for p in _compile_patterns(_SELF_HARM_PATTERNS))
                else _CATEGORY_HOPELESSNESS
            )
            return SafetyResult(
                is_safe         = False,
                category        = category,
                matched_pattern = pattern.pattern,
                handoff_message = _HANDOFF_MESSAGE,
            )

    return SafetyResult(
        is_safe         = True,
        category        = None,
        matched_pattern = None,
        handoff_message = "",
    )


def _compile_patterns(raw: list[str]) -> set[str]:
    """Return the compiled .pattern strings for a list of raw patterns."""
    return {re.compile(p, re.IGNORECASE).pattern for p in raw}
