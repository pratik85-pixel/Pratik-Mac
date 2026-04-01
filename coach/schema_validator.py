"""
coach/schema_validator.py

Validates LLM JSON output against the expected output schema for each trigger type.

Design
------
Four validation concerns in priority order:
    1. Schema conformance    — required keys present, types correct
    2. Length constraints    — summary 20–45 words, action 10–28 words
    3. Clinical term block   — 40+ terms must not appear in any field
    4. Specificity rules     — encouragement without a digit is blanked (no retry)

Failures produce:
    - (False, cleaned_output, [error_strings]) if fixable (clean and pass)
    - (True, cleaned_output, [])  if all checks pass (possibly with blanked fields)
    - (False, {}, [error_strings]) if not fixable → caller should retry (max 2)

Medical advice patterns:
    - Detected → returned as special error "medical_advice" → caller uses safety route
"""

from __future__ import annotations

import re
from typing import Any, Optional

from coach.context_builder import CoachContext


# ── Required schema fields per trigger type ────────────────────────────────────

_REQUIRED_FIELDS: dict[str, set[str]] = {
    "morning_brief": {
        "summary",
        "observation",
        "action",
        "window",
        "encouragement",
        "follow_up_question",
    },
    "post_session":  {"summary", "observation", "reinforcement", "next_session", "follow_up_question"},
    "nudge":         {"summary", "action", "follow_up_question"},
    "weekly_review": {"summary", "week_narrative", "dimension_spotlight", "action", "follow_up_question"},
    "conversation_turn": {"reply", "follow_up_question"},
    # Phase 5 triggers
    "nudge_check":       {"should_nudge", "reason"},
    "evening_checkin":   {"day_summary", "tonight_priority", "trend_note"},
    "night_closure":     {"updated_narrative", "tomorrow_seed"},
}

# ── Word length constraints ────────────────────────────────────────────────────

_WORD_LIMITS: dict[str, tuple[int, int]] = {
    "summary":     (20, 45),
    "observation": (10, 35),
    "action":      (10, 28),
    # conversation_turn "reply" — no fixed cap (human-like length)
    "reinforcement": (10, 35),
    "week_narrative": (30, 80),
}

# ── Clinical term blocklist ────────────────────────────────────────────────────

_CLINICAL_TERMS: frozenset[str] = frozenset({
    "cortisol", "parasympathetic", "sympathetic", "lf/hf", "lf hf",
    "vagal tone", "vagal", "autonomic", "dopamine", "serotonin",
    "norepinephrine", "noradrenaline", "adrenaline", "epinephrine",
    "hrv", "rmssd", "sdnn", "pnn50", "baroreceptor", "baroreflex",
    "homeostasis", "allostasis", "homeostatic", "allostatic",
    "circadian", "ultradian", "infradian",
    "polyvagal", "dorsal vagal", "ventral vagal",
    "neurotransmitter", "endorphin", "oxytocin",
    "hypothalamic", "pituitary", "adrenal", "hpa axis", "amygdala",
    "prefrontal", "hippocampus",
    "tidal volume", "respiratory sinus arrhythmia", "rsa",
    "spindle", "slow wave sleep", "rem rebound",
    "lactate threshold", "vo2 max", "anaerobic threshold",
})

# ── Superlative / empty-praise patterns ───────────────────────────────────────

_SUPERLATIVE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bamazing\b", re.IGNORECASE),
    re.compile(r"\bfantastic\b", re.IGNORECASE),
    re.compile(r"\bincredible\b", re.IGNORECASE),
    re.compile(r"\bproud of you\b", re.IGNORECASE),
    re.compile(r"\bso proud\b", re.IGNORECASE),
    re.compile(r"\bwonderful\b", re.IGNORECASE),
    re.compile(r"\bbrilliant work\b", re.IGNORECASE),
    re.compile(r"\bkilling it\b", re.IGNORECASE),
    re.compile(r"\bkilled it\b", re.IGNORECASE),
]

# ── Medical advice patterns ────────────────────────────────────────────────────

_MEDICAL_ADVICE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bconsult\s+(a|your)\s+(doctor|physician|cardiologist|specialist)\b", re.IGNORECASE),
    re.compile(r"\bseek\s+medical\b", re.IGNORECASE),
    re.compile(r"\bmedical\s+attention\b", re.IGNORECASE),
    re.compile(r"\bdiagnos", re.IGNORECASE),
    re.compile(r"\bsymptoms?\s+of\b", re.IGNORECASE),
    re.compile(r"\bprescri", re.IGNORECASE),
    re.compile(r"\btreat(ment)?\s+(for|of)\b", re.IGNORECASE),
]


# ── Public API ────────────────────────────────────────────────────────────────

def validate_output(
    raw: dict,
    trigger_type: str,
    context: Optional[CoachContext] = None,
) -> tuple[bool, dict, list[str]]:
    """
    Validate and optionally clean LLM JSON output.

    Parameters
    ----------
    raw : dict
        Raw parsed JSON from LLM.
    trigger_type : str
        "morning_brief" | "post_session" | "nudge" | "weekly_review" | "conversation_turn"
    context : CoachContext | None
        If provided, used for encouragement specificity check.

    Returns
    -------
    (valid, cleaned_output, errors)
        valid          — False means retry if retry budget permits
        cleaned_output — may have fields blanked (not retried)
        errors         — list of error strings for logging
    """
    errors: list[str] = []
    cleaned = dict(raw)

    # 1. Schema conformance
    required = _REQUIRED_FIELDS.get(trigger_type, set())
    missing = required - set(cleaned.keys())
    if missing:
        errors.append(f"missing_fields:{','.join(sorted(missing))}")
        return False, {}, errors

    # 2. Medical advice check (route to safety, no retry)
    for field_name, value in cleaned.items():
        if isinstance(value, str) and _has_medical_advice(value):
            errors.append(f"medical_advice_in:{field_name}")
            return False, cleaned, errors

    # 3. Superlative filter — ALWAYS runs (cleaning pass, does not cause retry)
    for field_name, value in list(cleaned.items()):
        if isinstance(value, str):
            cleaned_val, hit = _strip_superlatives(value)
            if hit:
                errors.append(f"superlative_blanked:{field_name}")
                cleaned[field_name] = cleaned_val

    # 4. Encouragement specificity — ALWAYS runs (cleaning pass, does not cause retry)
    for field_name in ("reinforcement", "encouragement"):
        if field_name in cleaned and isinstance(cleaned[field_name], str):
            val = cleaned[field_name]
            if val and not any(ch.isdigit() for ch in val):
                errors.append(f"specificity_blanked:{field_name}")
                cleaned[field_name] = ""

    # 5. Clinical term check (retry on failure)
    clinical_hit = _find_clinical_term(cleaned)
    if clinical_hit:
        errors.append(f"clinical_term:{clinical_hit}")
        return False, cleaned, errors

    # 6. Length constraints (retry on failure)
    for field_name, (min_w, max_w) in _WORD_LIMITS.items():
        if field_name in cleaned and isinstance(cleaned[field_name], str):
            word_count = len(cleaned[field_name].split())
            if word_count < min_w or word_count > max_w:
                errors.append(f"length:{field_name}:{word_count}w (expected {min_w}–{max_w})")
                return False, cleaned, errors

    return True, cleaned, errors


# ── Internal helpers ──────────────────────────────────────────────────────────

def _find_clinical_term(output: dict) -> Optional[str]:
    """Return the first clinical term found anywhere in the output, or None."""
    all_text = " ".join(
        str(v) for v in output.values() if isinstance(v, str)
    ).lower()
    for term in _CLINICAL_TERMS:
        if term in all_text:
            return term
    return None


def _has_medical_advice(text: str) -> bool:
    """True if text contains a medical advice pattern."""
    for pattern in _MEDICAL_ADVICE_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _strip_superlatives(text: str) -> tuple[str, bool]:
    """
    Remove superlative phrases from text.

    Returns (cleaned_text, True_if_anything_was_removed).
    """
    hit = False
    for pattern in _SUPERLATIVE_PATTERNS:
        new_text = pattern.sub("", text)
        if new_text != text:
            hit = True
            text = new_text
    return text.strip(), hit


def _word_count(text: str) -> int:
    return len(text.split())
