"""
profile/fact_extractor.py

Extracts structured durable facts from conversation text.

Called at conversation close by conversation_service.py.
Facts are persisted to the user_facts table and surfaced in coach_narrative
under CONVERSATION FACTS.

Extraction taxonomy
-------------------
  person     — relationships / people in the user's life
               "has a daughter", "wife is a teacher", "works with a friend named Sam"
  preference — likes, dislikes, strong opinions
               "hates cold showers", "loves hiking", "doesn't drink coffee"
  schedule   — recurring time patterns
               "works from home Wednesdays", "early riser", "gym on Tuesdays"
  event      — upcoming or recent one-off events
               "big presentation Thursday", "holiday next week", "just moved house"
  goal       — stated aspirations
               "wants to run a 5k", "trying to lose weight", "wants better sleep"
  belief     — self-reported views about themselves or the product
               "doesn't think meditation works for him", "thinks he's an introvert"
  health     — medical / physical facts
               "gets migraines when sleep-deprived", "bad knees, can't run"

Design
------
Pattern matching runs first (cheap, deterministic).  Each match produces a
candidate ExtractedFact with a polarity and initial confidence of 0.5.
If the same fact is extracted again in a future conversation, confidence +0.2.
If user explicitly confirms ("yes that's right", "exactly"), confidence bumped to 0.9.

No LLM call is made in this module — it runs synchronously.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# ── Extracted fact candidate ──────────────────────────────────────────────────

@dataclass
class ExtractedFact:
    category:   str           # "person"|"preference"|"schedule"|"event"|"goal"|"belief"|"health"
    fact_text:  str           # human-readable, max 200 chars
    fact_key:   Optional[str] # structured key for deduplication
    fact_value: Optional[str] # structured value
    polarity:   str           # "positive"|"negative"|"neutral"
    confidence: float = 0.5


# ── Regex pattern tables ──────────────────────────────────────────────────────

# Each entry: (category, polarity, compiled_regex, fact_key_template, fact_value_template)
# Use groups in regex: group(1) = primary entity, group(2) = detail (optional)

_PERSON_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("daughter",         re.compile(r"\b(?:my\s+)?daughter\b", re.I),          "family.daughter"),
    ("son",              re.compile(r"\b(?:my\s+)?son\b", re.I),               "family.son"),
    ("wife",             re.compile(r"\b(?:my\s+)?wife\b", re.I),              "family.wife"),
    ("husband",          re.compile(r"\b(?:my\s+)?husband\b", re.I),           "family.husband"),
    ("partner",          re.compile(r"\b(?:my\s+)?partner\b", re.I),           "family.partner"),
    ("kids",             re.compile(r"\b(?:my\s+)?kids?\b", re.I),             "family.kids"),
    ("parents",          re.compile(r"\b(?:my\s+)?(?:mum|mom|dad|father|mother|parents)\b", re.I), "family.parents"),
    ("colleague_friend", re.compile(r"\bfriend\s+(?:at|from)\s+work\b", re.I), "social.work_friend"),
]

_PREFERENCE_PATTERNS: list[tuple[str, str, re.Pattern, str, str]] = [
    # (key, polarity, regex, fact_key, fact_value)
    ("cold_shower_hate", "negative",
     re.compile(r"\bhate\s+(?:cold\s+showers?|the\s+cold\s+shower)\b", re.I),
     "activity.cold_shower", "dislike"),
    ("cold_shower_like", "positive",
     re.compile(r"\b(?:love|enjoy|like)\s+(?:cold\s+showers?)\b", re.I),
     "activity.cold_shower", "like"),
    ("no_meditation", "negative",
     re.compile(r"\b(?:meditation\s+(?:doesn'?t|does\s+not)\s+work|not\s+into\s+meditation|don'?t\s+meditate)\b", re.I),
     "activity.meditation", "dislike"),
    ("likes_nature", "positive",
     re.compile(r"\b(?:love|enjoy|like)\s+(?:being\s+)?(?:outside|outdoors|nature|hiking|walking)\b", re.I),
     "activity.nature", "like"),
    ("likes_music", "positive",
     re.compile(r"\b(?:love|enjoy|like)\s+(?:music|listening|playlist)\b", re.I),
     "activity.music", "like"),
    ("no_alcohol", "positive",
     re.compile(r"\b(?:don'?t\s+drink|stopped\s+drinking|quit\s+alcohol|sober)\b", re.I),
     "habit.alcohol", "abstain"),
    ("drinks_coffee", "neutral",
     re.compile(r"\b(?:love|need|can'?t\s+function\s+without)\s+(?:my\s+)?coffee\b", re.I),
     "habit.caffeine", "high"),
    ("no_coffee", "positive",
     re.compile(r"\b(?:don'?t\s+drink\s+coffee|quit\s+coffee|off\s+coffee|no\s+caffeine)\b", re.I),
     "habit.caffeine", "none"),
    ("likes_running", "positive",
     re.compile(r"\b(?:love|enjoy|like)\s+running\b", re.I),
     "activity.running", "like"),
    ("bad_knees", "negative",
     re.compile(r"\bbad\s+(?:knee|knees)\b", re.I),
     "health.knees", "injury"),
    ("introvert_self", "neutral",
     re.compile(r"\b(?:i'?m\s+(?:an\s+)?introvert|quite\s+introverted)\b", re.I),
     "personality.social", "introvert"),
    ("extrovert_self", "neutral",
     re.compile(r"\b(?:i'?m\s+(?:an\s+)?extrovert|quite\s+extroverted)\b", re.I),
     "personality.social", "extrovert"),
]

_SCHEDULE_PATTERNS: list[tuple[str, re.Pattern, str, str]] = [
    # (fact_key, regex, polarity, template)
    ("work.wfh", re.compile(
        r"\bwork(?:ing)?\s+from\s+home\s+(?:on\s+)?(?P<day>monday|tuesday|wednesday|thursday|friday|mondays|tuesdays|wednesdays|thursdays|fridays)\b",
        re.I), "neutral", "works from home on {day}"),
    ("schedule.gym", re.compile(
        r"\bgym\s+(?:on\s+)?(?P<day>monday|tuesday|wednesday|thursday|friday|saturday|sunday|mondays|tuesdays|wednesdays|thursdays|fridays|saturdays|sundays)\b",
        re.I), "positive", "gym on {day}"),
    ("schedule.early_riser", re.compile(
        r"\b(?:i'?m\s+(?:an?\s+)?early\s+riser|wake\s+up\s+early|up\s+(?:by|at)\s+[56]\s*(?:am|:00))\b",
        re.I), "neutral", "early riser"),
    ("schedule.night_owl", re.compile(
        r"\b(?:night\s+owl|go\s+to\s+bed\s+late|sleep\s+(?:late|after\s+midnight))\b",
        re.I), "neutral", "night owl"),
    ("schedule.busy_morning", re.compile(
        r"\bmornings?\s+(?:are\s+)?(?:busy|hectic|crazy|packed)\b",
        re.I), "negative", "busy mornings"),
]

_EVENT_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    # (fact_key, regex, polarity)
    ("event.presentation",
     re.compile(r"\b(?:big\s+)?presentation\b", re.I), "neutral"),
    ("event.meeting_important",
     re.compile(r"\b(?:important|big|major)\s+(?:meeting|call|interview)\b", re.I), "neutral"),
    ("event.holiday",
     re.compile(r"\b(?:holiday|vacation|trip|travel)\s+(?:next\s+week|coming\s+up|this\s+week|soon)\b", re.I), "positive"),
    ("event.moved_house",
     re.compile(r"\b(?:just\s+)?(?:moved|moving)\s+(?:house|apartment|flat)\b", re.I), "neutral"),
    ("event.new_job",
     re.compile(r"\b(?:new\s+job|started\s+a?\s+new\s+(?:role|position)|just\s+started\s+(?:a\s+new)?\s+job)\b", re.I), "positive"),
    ("event.planning_cycle",
     re.compile(r"\b(?:planning\s+cycle|quarterly|q[1-4]\s+planning|annual\s+review)\b", re.I), "neutral"),
]

_GOAL_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("goal.run_5k",
     re.compile(r"\b(?:want\s+to\s+run\s+a?\s*5\s*k|training\s+for\s+(?:a\s+)?5k)\b", re.I), "positive"),
    ("goal.lose_weight",
     re.compile(r"\b(?:trying\s+to\s+lose\s+weight|lose\s+(?:a\s+few\s+)?kilos?|lose\s+(?:some\s+)?weight)\b", re.I), "positive"),
    ("goal.better_sleep",
     re.compile(r"\b(?:want\s+(?:to\s+)?(?:sleep\s+better|better\s+sleep)|improve\s+(?:my\s+)?sleep)\b", re.I), "positive"),
    ("goal.less_stress",
     re.compile(r"\b(?:want\s+to\s+(?:be\s+)?less\s+stressed|reduce\s+(?:my\s+)?stress|manage\s+(?:my\s+)?stress\s+better)\b", re.I), "positive"),
    ("goal.run_marathon",
     re.compile(r"\b(?:want\s+to\s+run\s+a\s+marathon|training\s+for\s+(?:a\s+)?marathon)\b", re.I), "positive"),
]

_HEALTH_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("health.migraines",
     re.compile(r"\b(?:get|have|suffer\s+from)\s+migraines?\b", re.I), "negative"),
    ("health.back_pain",
     re.compile(r"\bback\s+pain\b", re.I), "negative"),
    ("health.anxiety_diagnosed",
     re.compile(r"\b(?:i\s+have|diagnosed\s+with)\s+anxiety\b", re.I), "negative"),
    ("health.poor_sleep_chronic",
     re.compile(r"\b(?:always|chronically|never)\s+(?:tired|exhausted|sleep\s+(?:badly|poorly))\b", re.I), "negative"),
]

# Confirmation signals — if any of these appear alongside another fact extraction,
# bump the confidence of the fact extracted in the same message to 0.9
_CONFIRMATION_PATTERNS = re.compile(
    r"\b(?:yes(?:\s+that'?s?\s+(?:right|correct|exactly))?|exactly|correct|"
    r"that'?s?\s+right|spot\s+on|absolutely|definitely|you(?:'?re|\s+are)\s+right)\b",
    re.I,
)


# ── Public API ────────────────────────────────────────────────────────────────

def extract_facts(message: str) -> list[ExtractedFact]:
    """
    Extract structured facts from a single conversation message.

    Returns a list of ExtractedFact candidates.  May be empty.
    Caller is responsible for deduplication against existing UserFact rows.
    """
    facts: list[ExtractedFact] = []
    is_confirmation = bool(_CONFIRMATION_PATTERNS.search(message))

    # People
    for label, pattern, fact_key in _PERSON_PATTERNS:
        if pattern.search(message):
            f = ExtractedFact(
                category="person",
                fact_text=f"mentioned {label.replace('_', ' ')}",
                fact_key=fact_key,
                fact_value=label,
                polarity="neutral",
            )
            if is_confirmation:
                f.confidence = 0.9
            facts.append(f)

    # Preferences
    for key, polarity, pattern, fact_key, fact_value in _PREFERENCE_PATTERNS:
        if pattern.search(message):
            readable = fact_key.split(".")[-1].replace("_", " ")
            action   = "likes" if polarity == "positive" else ("dislikes" if polarity == "negative" else "mentioned")
            f = ExtractedFact(
                category="preference",
                fact_text=f"{action} {readable}",
                fact_key=fact_key,
                fact_value=fact_value,
                polarity=polarity,
            )
            if is_confirmation:
                f.confidence = 0.9
            facts.append(f)

    # Schedule
    for fact_key, pattern, polarity, template in _SCHEDULE_PATTERNS:
        m = pattern.search(message)
        if m:
            try:
                day = m.group("day").lower()
                fact_text = template.format(day=day)
            except (IndexError, KeyError):
                fact_text = template
            f = ExtractedFact(
                category="schedule",
                fact_text=fact_text[:200],
                fact_key=fact_key,
                fact_value=fact_text,
                polarity=polarity,
            )
            if is_confirmation:
                f.confidence = 0.9
            facts.append(f)

    # Events
    for fact_key, pattern, polarity in _EVENT_PATTERNS:
        if pattern.search(message):
            label = fact_key.split(".")[-1].replace("_", " ")
            f = ExtractedFact(
                category="event",
                fact_text=f"mentioned {label}",
                fact_key=fact_key,
                fact_value=label,
                polarity=polarity,
            )
            if is_confirmation:
                f.confidence = 0.9
            facts.append(f)

    # Goals
    for fact_key, pattern, polarity in _GOAL_PATTERNS:
        if pattern.search(message):
            label = fact_key.split(".")[-1].replace("_", " ")
            f = ExtractedFact(
                category="goal",
                fact_text=f"goal: {label}",
                fact_key=fact_key,
                fact_value=label,
                polarity=polarity,
            )
            if is_confirmation:
                f.confidence = 0.9
            facts.append(f)

    # Health
    for fact_key, pattern, polarity in _HEALTH_PATTERNS:
        if pattern.search(message):
            label = fact_key.split(".")[-1].replace("_", " ")
            f = ExtractedFact(
                category="health",
                fact_text=f"health note: {label}",
                fact_key=fact_key,
                fact_value=label,
                polarity=polarity,
            )
            if is_confirmation:
                f.confidence = 0.9
            facts.append(f)

    return facts


def merge_with_existing(
    extracted: list[ExtractedFact],
    existing: list[dict],
) -> tuple[list[ExtractedFact], list[str]]:
    """
    Merge newly extracted facts with existing DB facts.

    Returns:
      (new_facts_to_insert, existing_ids_to_update_confidence)

    Deduplication key: (category, fact_key).
    If an existing fact matches: bump its confidence by +0.2 (max 1.0).
    If no match: it's a new fact to insert.
    """
    existing_map: dict[str, dict] = {
        f"{r.get('category')}.{r.get('fact_key')}": r
        for r in existing
        if r.get("fact_key")
    }

    new_facts: list[ExtractedFact] = []
    update_ids: list[str] = []

    for ef in extracted:
        dedup_key = f"{ef.category}.{ef.fact_key}"
        if dedup_key in existing_map:
            update_ids.append(str(existing_map[dedup_key]["id"]))
        else:
            new_facts.append(ef)

    return new_facts, update_ids
