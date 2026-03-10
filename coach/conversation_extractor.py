"""
coach/conversation_extractor.py

Extracts HabitSignals from free-text user messages.

Design
------
Runs in parallel to the LLM call — does not block the user response.
Extracted signals are added to ConversationState.accumulated_signals and,
at session close, written back to the main signal tables with a lower
confidence weight than physiological data.

Extraction is regex-based and intentionally conservative.
False negatives (missing a signal) are acceptable.
False positives (fabricating a signal the user didn't report) are not.

Confidence weight: 0.4 (vs 1.0 for Apple Health data, 0.7 for manual log).
This means extracted signals shift the load_score, but less aggressively.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from coach.plan_replanner import HabitSignal
from profile.fact_extractor import extract_facts, ExtractedFact


# ── Pattern sets ──────────────────────────────────────────────────────────────

_ALCOHOL_PATTERNS = [
    (r"\b(had\s+a\s+few|few\s+drinks?|couple\s+of\s+drinks?|a\s+glass\s+of\s+wine|wine|beer|drinking|drank)\b", "light"),
    (r"\b(quite\s+a\s+bit\s+to\s+drink|several\s+drinks?|a\s+few\s+beers|drank\s+(a\s+lot|last\s+night))\b", "moderate"),
    (r"\b(heavy\s+night|got\s+drunk|really\s+drank|lots\s+of\s+drinks?|lots\s+to\s+drink|big\s+night\s+out)\b", "heavy"),
]

_LATE_NIGHT_PATTERNS = [
    (r"\b(stayed\s+up\s+late|up\s+late|late\s+night|went\s+to\s+bed\s+late|late\s+to\s+bed)\b", "moderate"),
    (r"\b(up\s+(until|till)\s+(2|3|4|midnight|1am|2am|3am))\b", "heavy"),
]

_STRESS_PATTERNS = [
    (r"\b(stressed|stressful|anxious|anxiety|worried|work\s+stress|a\s+lot\s+on|overwhelmed)\b", "moderate"),
    (r"\b(very\s+stressed|really\s+anxious|huge\s+amount\s+of\s+stress|panic|panicking)\b", "heavy"),
]

_EXERCISE_PATTERNS = [
    (r"\b(worked\s+out|went\s+(for\s+a\s+run|to\s+the\s+gym)|training|exercised|hard\s+session)\b", "moderate"),
    (r"\b(really\s+hard\s+workout|long\s+run|heavy\s+training|race|competition|hiit|crossfit)\b", "heavy"),
]

_MISSED_SESSION_PATTERNS = [
    (r"\b(missed\s+(my\s+)?session|skipped\s+(my\s+)?session|didn'?t\s+do\s+(my\s+)?session|forgot)\b", "light"),
]

_POSITIVE_PATTERNS = [
    (r"\b(feeling\s+good|feel\s+great|had\s+a\s+good\s+sleep|slept\s+(well|great)|rested|energised|energized)\b", "light"),
]

# ── Lifestyle activity patterns ───────────────────────────────────────────────
# Maps to activity slugs in the catalog for proactive follow-up tracking.

_SPORTS_PATTERNS = [
    (r"\b(played|game|match|practice|training)\b.*\b(tennis|pickleball|basketball|football|soccer|cricket|squash|badminton|volleyball|rugby|hockey)\b", "moderate"),
    (r"\b(tennis|pickleball|basketball|football|soccer|cricket|squash|badminton|volleyball|rugby|hockey)\b.*\b(game|match|played|session)\b", "moderate"),
    (r"\b(had\s+a\s+(game|match)|went\s+to\s+play)\b", "light"),
    (r"\b(really\s+hard\s+game|intense\s+(match|game|practice)|competitive\s+(game|match))\b", "heavy"),
]

_SOCIAL_PATTERNS = [
    (r"\b(went\s+out|catch\s+up|caught\s+up|dinner\s+(out|with)|drinks?\s+(with|out)|friends?\s+(tonight|last\s+night|yesterday)|social(ised|ized|ising|izing))\b", "light"),
    (r"\b(big\s+night\s+out|party|birthday|event\s+out|late\s+night\s+out)\b", "moderate"),
]

_COLD_SHOWER_PATTERNS = [
    (r"\b(cold\s+shower|cold\s+plunge|cold\s+dip|ice\s+bath|cold\s+water|wim\s+hof)\b", "light"),
]

_ENTERTAINMENT_PATTERNS = [
    (r"\b(watched\s+a\s+(movie|film|show|series)|netflix|disney\+|streaming|tv\s+show|episode|binge)\b", "light"),
    (r"\b(played\s+(video\s+)?games?|gaming|xbox|playstation|ps[4-5])\b", "light"),
]

_NATURE_PATTERNS = [
    (r"\b(walk\s+in\s+(nature|the\s+park|the\s+woods?|the\s+forest)|hike?|trail\s+run|park\s+run|parkrun|outdoor\s+walk)\b", "light"),
    (r"\b(nature\s+walk|went\s+to\s+(the\s+)?beach|sat\s+outside|time\s+outside|fresh\s+air)\b", "light"),
]

# ── Anxiety trigger taxonomy patterns ─────────────────────────────────────────
# Maps to ANXIETY_TRIGGER_TYPES in psych/psych_schema.py

_ANXIETY_TRIGGER_PATTERNS: list[tuple[str, str]] = [
    # deadline
    (r"\b(deadline|due\s+date|submission|deliver(able)?|behind\s+schedule|running\s+out\s+of\s+time)\b", "deadline"),
    # work_overload
    (r"\b(too\s+much\s+(work|to\s+do)|work(ing)?\s+overtime|overwhelmed\s+with\s+work|swamped|packed\s+day|no\s+time\s+for)\b", "work_overload"),
    # performance
    (r"\b(presentation|public\s+speaking|interview|exam|test|evaluation|performance\s+review|audition|pitch)\b", "performance"),
    # social_pressure
    (r"\b(people\s+pleasing|what\s+(they|he|she|others?)\s+think|judged|fitting\s+in|awkward\s+around|social\s+media|comparison)\b", "social_pressure"),
    # confrontation
    (r"\b(argument|fight|confrontation|conflict|disagree(ment)?|he\s+said\s+she\s+said|falling\s+out|tense\s+conversation)\b", "confrontation"),
    # relationship
    (r"\b(relationship\s+(issues?|problems?|stress)|partner|girlfriend|boyfriend|breakup|divorce|family\s+stress|parent|sibling)\b", "relationship"),
    # financial
    (r"\b(money|finances?|bills?|debt|rent|mortgage|savings?|budget|afford|expenses?|financial\s+stress)\b", "financial"),
    # health_worry
    (r"\b(worried\s+about\s+(my\s+)?(health|symptoms?|body)|doctor|diagnosis|not\s+feeling\s+well|sick|illness|pain\s+that\s+won'?t)\b", "health_worry"),
    # crowds
    (r"\b(crowded|crowds?|busy\s+place|packed\s+(room|venue|train|bus)|too\s+many\s+people|public\s+transport)\b", "crowds"),
    # uncertainty
    (r"\b(don'?t\s+know\s+what'?s\s+(going\s+to\s+)?happen|uncertain|unclear|no\s+plan|waiting\s+to\s+hear|limbo|unknown\s+result)\b", "uncertainty"),
    # change
    (r"\b(big\s+change|moving|new\s+(job|city|role)|transition|restructure|reorganis|reorg|change\s+at\s+work)\b", "change"),
]

# ── Mood signal patterns ──────────────────────────────────────────────────────
# Each maps to an inferred 1-5 score for mood, energy, and anxiety

_MOOD_POSITIVE_HIGH = re.compile(
    r"\b(amazing|fantastic|brilliant|on\s+top\s+of\s+the\s+world|best\s+i'?ve\s+felt|incredible|pumped|buzzing)\b",
    re.IGNORECASE,
)
_MOOD_POSITIVE_LOW = re.compile(
    r"\b(feeling\s+(good|great|positive|okay|alright|decent|fine)|not\s+bad|pretty\s+good|well\s+rested)\b",
    re.IGNORECASE,
)
_MOOD_NEUTRAL = re.compile(
    r"\b(average|okay|so[- ]so|manageable|getting\s+by|meh|nothing\s+special)\b",
    re.IGNORECASE,
)
_MOOD_NEGATIVE_LOW = re.compile(
    r"\b(a\s+bit\s+(low|down|flat|tired|off)|not\s+(great|feeling\s+it|my\s+best)|dragging)\b",
    re.IGNORECASE,
)
_MOOD_NEGATIVE_HIGH = re.compile(
    r"\b(terrible|awful|really\s+(bad|down|struggling|low)|can'?t\s+cope|exhausted\s+and\s+miserable|burned\s+out)\b",
    re.IGNORECASE,
)

_ENERGY_HIGH = re.compile(
    r"\b(lots?\s+of\s+energy|energised|energized|fired\s+up|ready\s+to\s+go|high\s+energy|full\s+of\s+energy)\b",
    re.IGNORECASE,
)
_ENERGY_LOW = re.compile(
    r"\b(drained|no\s+energy|exhausted|fatigued|wiped\s+out|sluggish|lethargic|running\s+on\s+empty|zero\s+energy)\b",
    re.IGNORECASE,
)

_ANXIETY_HIGH = re.compile(
    r"\b(panicking|panic\s+attack|really\s+anxious|very\s+anxious|highly\s+anxious|heart\s+racing\s+with\s+(worry|anxiety)|can'?t\s+stop\s+worrying)\b",
    re.IGNORECASE,
)
_ANXIETY_MOD = re.compile(
    r"\b(anxious|anxiousness|anxiety|a\s+bit\s+anxious|nervous|on\s+edge|unsettled|uneasy|worried)\b",
    re.IGNORECASE,
)

# Hours-ago estimation from temporal language
_RECENCY_MAP: list[tuple[re.Pattern, float]] = [
    (re.compile(r"\blast\s+night\b|\btonight\b|\btoday\b|\bthis\s+morning\b", re.IGNORECASE), 8.0),
    (re.compile(r"\byesterday\b", re.IGNORECASE), 24.0),
    (re.compile(r"\btwo\s+nights?\s+ago\b|\b2\s+nights?\s+ago\b", re.IGNORECASE), 48.0),
    (re.compile(r"\bthree\s+nights?\s+ago\b|\b3\s+nights?\s+ago\b", re.IGNORECASE), 72.0),
]

_DEFAULT_HOURS_AGO = 12.0  # conservative default if no temporal language found

_CONFIDENCE = 0.4  # lower weight than Apple Health (1.0) or manual log (0.7)


# ── ExtractionResult ──────────────────────────────────────────────────────────

@dataclass
class MoodSignal:
    """
    Mood-state inferred from free-text language.

    All scores are 1–5 (matching MoodLog schema).
    None means the text gave no reliable signal for that dimension.
    """
    mood_score:    Optional[float]
    energy_score:  Optional[float]
    anxiety_score: Optional[float]


@dataclass
class ExtractionResult:
    signals:              list[HabitSignal]
    signal_labels:        list[str]           # plain English for ConversationState
    confidence:           float = _CONFIDENCE
    anxiety_trigger_type: Optional[str] = field(default=None)  # from ANXIETY_TRIGGER_TYPES
    mood_signal:          Optional[MoodSignal] = field(default=None)
    extracted_facts:      list[ExtractedFact] = field(default_factory=list)


# ── Public API ────────────────────────────────────────────────────────────────

def extract_signals_from_message(
    message: str,
    existing_signals: Optional[list[str]] = None,
) -> ExtractionResult:
    """
    Extract HabitSignals from a single user message.

    Parameters
    ----------
    message : str
        Raw user message text.
    existing_signals : list[str] | None
        Already-accumulated signal labels from prior turns — prevents duplicates.

    Returns
    -------
    ExtractionResult
    """
    if not message or not message.strip():
        return ExtractionResult(signals=[], signal_labels=[])

    existing = set(existing_signals or [])
    found: list[HabitSignal] = []
    labels: list[str] = []

    hours_ago = _estimate_hours_ago(message)

    _extract_group(message, _ALCOHOL_PATTERNS,       "alcohol",           hours_ago, found, labels, existing)
    _extract_group(message, _LATE_NIGHT_PATTERNS,    "late_night",        hours_ago, found, labels, existing)
    _extract_group(message, _STRESS_PATTERNS,        "stressful_event",   hours_ago, found, labels, existing)
    _extract_group(message, _EXERCISE_PATTERNS,      "exercise_heavy",    hours_ago, found, labels, existing)
    _extract_group(message, _MISSED_SESSION_PATTERNS,"missed_session",    hours_ago, found, labels, existing)
    _extract_group(message, _POSITIVE_PATTERNS,      "positive_state",    hours_ago, found, labels, existing)
    # ── Lifestyle activity signals (catalog follow-up) ──────────────────────
    _extract_group(message, _SPORTS_PATTERNS,        "sports_activity",   hours_ago, found, labels, existing)
    _extract_group(message, _SOCIAL_PATTERNS,        "social_time",       hours_ago, found, labels, existing)
    _extract_group(message, _COLD_SHOWER_PATTERNS,   "cold_shower",       hours_ago, found, labels, existing)
    _extract_group(message, _ENTERTAINMENT_PATTERNS, "entertainment",     hours_ago, found, labels, existing)
    _extract_group(message, _NATURE_PATTERNS,        "nature_time",       hours_ago, found, labels, existing)

    # ── Anxiety trigger type ─────────────────────────────────────────────────
    anxiety_trigger_type = _extract_anxiety_trigger(message)

    # ── Mood signal ──────────────────────────────────────────────────────────
    mood_signal = _extract_mood_signal(message)

    return ExtractionResult(
        signals=found,
        signal_labels=labels,
        confidence=_CONFIDENCE,
        anxiety_trigger_type=anxiety_trigger_type,
        mood_signal=mood_signal,
        extracted_facts=extract_facts(message),
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _estimate_hours_ago(message: str) -> float:
    """Estimate hours_ago from temporal language in message."""
    for pattern, hours in _RECENCY_MAP:
        if pattern.search(message):
            return hours
    return _DEFAULT_HOURS_AGO


def _extract_anxiety_trigger(message: str) -> Optional[str]:
    """
    Return the first matching anxiety trigger type, or None.
    Order of patterns in _ANXIETY_TRIGGER_PATTERNS encodes priority.
    """
    for raw_pattern, trigger_type in _ANXIETY_TRIGGER_PATTERNS:
        compiled = re.compile(raw_pattern, re.IGNORECASE)
        if compiled.search(message):
            return trigger_type
    return None


def _extract_mood_signal(message: str) -> Optional[MoodSignal]:
    """
    Infer mood_score, energy_score, anxiety_score (1–5) from language.
    Returns None when no signal is found at all.
    """
    mood_score: Optional[float] = None
    if _MOOD_POSITIVE_HIGH.search(message):
        mood_score = 5.0
    elif _MOOD_POSITIVE_LOW.search(message):
        mood_score = 4.0
    elif _MOOD_NEUTRAL.search(message):
        mood_score = 3.0
    elif _MOOD_NEGATIVE_LOW.search(message):
        mood_score = 2.0
    elif _MOOD_NEGATIVE_HIGH.search(message):
        mood_score = 1.0

    energy_score: Optional[float] = None
    if _ENERGY_HIGH.search(message):
        energy_score = 5.0
    elif _ENERGY_LOW.search(message):
        energy_score = 1.0

    anxiety_score: Optional[float] = None
    if _ANXIETY_HIGH.search(message):
        anxiety_score = 5.0
    elif _ANXIETY_MOD.search(message):
        anxiety_score = 3.0

    if mood_score is None and energy_score is None and anxiety_score is None:
        return None

    return MoodSignal(
        mood_score    = mood_score,
        energy_score  = energy_score,
        anxiety_score = anxiety_score,
    )


def _extract_group(
    message: str,
    patterns: list[tuple[str, str]],
    event_type: str,
    hours_ago: float,
    found: list[HabitSignal],
    labels: list[str],
    existing: set[str],
) -> None:
    """Try each pattern in the group. First match wins — heaviest severity takes priority."""
    best_severity: Optional[str] = None

    # Check heaviest first (patterns are ordered light → heavy so reverse)
    for raw_pattern, severity in reversed(patterns):
        compiled = re.compile(raw_pattern, re.IGNORECASE)
        if compiled.search(message):
            best_severity = severity
            break

    if best_severity is None:
        return

    label = f"{event_type}_{best_severity}_{int(hours_ago)}h"
    if label in existing:
        return

    found.append(HabitSignal(
        event_type = event_type,
        severity   = best_severity,
        hours_ago  = hours_ago,
        source     = "conversation",
    ))
    short_label = f"{event_type.replace('_', ' ')} ({best_severity}) ~{int(hours_ago)}h ago"
    labels.append(short_label)
