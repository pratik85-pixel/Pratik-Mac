"""
archetypes/narrative.py

Converts an NSHealthProfile into plain-language coaching narrative.

Design:
    The narrative has three layers:
        1. Headline    — one sentence displayed above the score.
        2. Body        — two to three sentences about what the pattern means for this person.
        3. Pattern name — shown AFTER body as recognition, not diagnosis.

    The pattern name comes last on purpose. The person should recognise themselves in the
    body copy before seeing the label. The label is just a useful shorthand.

    Templates are keyed by (pattern, stage_band) to vary tone as the user progresses.
    Amplifier pattern gets a short standalone note if active.
    Dimension insights are generated programmatically from dimension scores.

Stage bands:
    early     → stage 0–1
    building  → stage 2–3
    optimise  → stage 4–5
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from archetypes.scorer import NSHealthProfile


# ── Output dataclass ───────────────────────────────────────────────────────────

@dataclass
class NSNarrative:
    """Plain-language coaching narrative derived from NSHealthProfile."""

    headline:           str               # 1 sentence above the score
    body:               str               # 2–3 sentences — the personal story
    pattern_name:       str               # short label shown AFTER the body
    amplifier_note:     str               # describes active amplifier if present ("" if none)
    dimension_insights: dict[str, str]    # per-dimension 1-sentence explanations
    stage_description:  str               # what this stage looks like
    stage_focus:        list[str]         # copied from NSHealthProfile for convenience
    evolution_note:     str               # what reaching the next stage unlocks


# ── Public API ─────────────────────────────────────────────────────────────────

def compute_narrative(profile: NSHealthProfile) -> NSNarrative:
    """
    Generate NSNarrative from an NSHealthProfile.

    Parameters
    ----------
    profile : NSHealthProfile
        Output of compute_ns_health_profile().

    Returns
    -------
    NSNarrative
    """
    band = _stage_band(profile.stage)
    key  = (profile.primary_pattern, band)

    headline      = _HEADLINE.get(key, _HEADLINE.get((profile.primary_pattern, "early"), _HEADLINES_FALLBACK))
    body          = _BODY.get(key, _BODY.get((profile.primary_pattern, "early"), _BODY_FALLBACK))
    pattern_name  = _PATTERN_NAMES.get(profile.primary_pattern, "Your Pattern")
    amplifier_note = _amplifier_note(profile.amplifier_pattern, profile.stage)
    dim_insights   = _dimension_insights(profile)
    stage_desc     = _STAGE_DESCRIPTIONS[profile.stage]
    evolution_note = _evolution_note(profile.stage)

    return NSNarrative(
        headline          = headline,
        body              = body,
        pattern_name      = pattern_name,
        amplifier_note    = amplifier_note,
        dimension_insights = dim_insights,
        stage_description = stage_desc,
        stage_focus       = profile.stage_focus,
        evolution_note    = evolution_note,
    )


# ── Pattern display names ──────────────────────────────────────────────────────

_PATTERN_NAMES: dict[str, str] = {
    "over_optimizer":  "The Over-Optimizer",
    "trend_chaser":    "The Trend Chaser",
    "hustler":         "The Hustler",
    "quiet_depleter":  "The Quiet Depleter",
    "night_warrior":   "The Night Warrior",
    "loop_runner":     "The Loop Runner",
    "purist":          "The Purist",
    "dialled_in":      "Dialled-In",
    "UNCLASSIFIED":    "Your Pattern",
}


# ── Stage bands ────────────────────────────────────────────────────────────────

def _stage_band(stage: int) -> str:
    if stage <= 1:
        return "early"
    if stage <= 3:
        return "building"
    return "optimise"


# ── Headlines ──────────────────────────────────────────────────────────────────

_HEADLINES_FALLBACK = "Your nervous system has more capacity than it is currently using."

_HEADLINE: dict[tuple[str, str], str] = {

    # Over-Optimizer
    ("over_optimizer", "early"):
        "Your body is absorbing the load. It is not getting the signal that it is safe to recover.",
    ("over_optimizer", "building"):
        "Your recovery gap is closing. The system is finding its rhythm.",
    ("over_optimizer", "optimise"):
        "The hard work and the recovery are finally aligned. This is what performance looks like.",

    # Trend Chaser
    ("trend_chaser", "early"):
        "You have not found your thing yet. That is fine — the data will find it for you.",
    ("trend_chaser", "building"):
        "You are building something consistent. The signal is getting cleaner.",
    ("trend_chaser", "optimise"):
        "Consistency became your superpower. The rest followed.",

    # Hustler
    ("hustler", "early"):
        "The week is costing you more than you are realising. Your body is keeping the tab.",
    ("hustler", "building"):
        "The load is the same. Your recovery is getting better. That changes everything.",
    ("hustler", "optimise"):
        "You proved you can carry the load without it carrying you.",

    # Quiet Depleter
    ("quiet_depleter", "early"):
        "Nothing dramatic is wrong. The system has just been running quiet and low for a while.",
    ("quiet_depleter", "building"):
        "The floor is rising. Quiet improvement, exactly the way you work.",
    ("quiet_depleter", "optimise"):
        "Steady has turned into strong. The long game is the right game.",

    # Night Warrior
    ("night_warrior", "early"):
        "Your biology peaks when the world is winding down. That is real, not an excuse.",
    ("night_warrior", "building"):
        "Your schedule and your chronotype are starting to agree.",
    ("night_warrior", "optimise"):
        "You built your best life around your actual biology. That is the whole game.",

    # Loop Runner
    ("loop_runner", "early"):
        "Your mind is running the overnight shift when your body needs to be in repair mode.",
    ("loop_runner", "building"):
        "The overnight signal is improving. Your brain is starting to let go.",
    ("loop_runner", "optimise"):
        "Sleep is working. Real recovery is happening. You can feel the difference.",

    # Purist
    ("purist", "early"):
        "You have a practice. Now let the data show you where it is not reaching.",
    ("purist", "building"):
        "Your foundation is solid. The gap is small and specific.",
    ("purist", "optimise"):
        "Refinement is your mode now. The big levers are all pulled.",

    # Dialled-In
    ("dialled_in", "early"):
        "You are at the floor of peak territory. Everything is aligned.",
    ("dialled_in", "building"):
        "You are in the optimise phase. Performance gains are fully accessible.",
    ("dialled_in", "optimise"):
        "This is what it looks like when nervous system health becomes a competitive advantage.",

    # Unclassified
    ("UNCLASSIFIED", "early"):
        "Your pattern is taking shape. A few more days of data and the picture will be clear.",
    ("UNCLASSIFIED", "building"):
        "The data is consistent. Your pattern will surface soon.",
    ("UNCLASSIFIED", "optimise"):
        "You are doing something right. The system will confirm which part shortly.",
}


# ── Body copy ──────────────────────────────────────────────────────────────────

_BODY_FALLBACK = (
    "Your nervous system is building a picture of itself. "
    "The score reflects what the data can confirm so far. "
    "Keep the morning read habit — that is where this gets interesting."
)

_BODY: dict[tuple[str, str], str] = {

    # Over-Optimizer — early
    ("over_optimizer", "early"): (
        "You push hard — gym, runs, long hours. "
        "Your nervous system stays switched on long after the effort ends. "
        "You are not unfit. You are under-recovered."
    ),
    # Over-Optimizer — building
    ("over_optimizer", "building"): (
        "You have started giving your nervous system the signal that it is safe to slow down. "
        "The arcs are completing faster. The morning reads are climbing. "
        "The training is not the problem — the missing recovery window was."
    ),
    # Over-Optimizer — optimise
    ("over_optimizer", "optimise"): (
        "You trained your system to absorb hard effort and return to baseline faster. "
        "That is not just fitness — it is the highest-leverage adaptation available. "
        "Most people never get here because they resist the rest."
    ),

    # Trend Chaser — early
    ("trend_chaser", "early"): (
        "You have tried things — maybe yoga, maybe the Wim Hof protocol, maybe morning runs. "
        "Nothing has stuck long enough to actually change your number. "
        "The intervention is not the problem. The consistency is."
    ),
    # Trend Chaser — building
    ("trend_chaser", "building"): (
        "Something is working now. The data is getting cleaner because you have stopped changing variables. "
        "This is what nervous system adaptation looks like — slow, steady, and unmistakable. "
        "The noise is reducing because you are listening."
    ),
    # Trend Chaser — optimise
    ("trend_chaser", "optimise"): (
        "The consistency that felt boring turned out to be the entire strategy. "
        "Your nervous system adapted because it finally got the same signal every day. "
        "You are not chasing anything anymore."
    ),

    # Hustler — early
    ("hustler", "early"): (
        "The week loads up slowly. Monday is fine. Wednesday is manageable. "
        "By Thursday your nervous system is running on fumes, but you keep going. "
        "The problem is not ambition — it is the absence of deliberate recovery time."
    ),
    # Hustler — building
    ("hustler", "building"): (
        "The weekly debt is clearing faster because you have built in the stops. "
        "Thursday is no longer the lowest point of the week. "
        "The output has not changed — the cost of it has."
    ),
    # Hustler — optimise
    ("hustler", "optimise"): (
        "High output and high recovery coexist. Not many people discover this is possible. "
        "Your nervous system is no longer the limiting factor in what you can do. "
        "The capacity was always there — you just had to stop borrowing from it."
    ),

    # Quiet Depleter — early
    ("quiet_depleter", "early"): (
        "Nothing dramatic is wrong. You are not in crisis. "
        "But the numbers tell a quiet story: the floor has dropped slowly over time, "
        "and the system has less range than it should."
    ),
    # Quiet Depleter — building
    ("quiet_depleter", "building"): (
        "The floor is rising. Not dramatically — that is not how this works. "
        "But the morning reads are more consistent, the range is widening slightly. "
        "Your nervous system is remembering what it was capable of."
    ),
    # Quiet Depleter — optimise
    ("quiet_depleter", "optimise"): (
        "Steady was the right approach. The system needed time and gentle input, not intensity. "
        "The floor you have now is stronger than the one you had when you started. "
        "That is the whole victory."
    ),

    # Night Warrior — early
    ("night_warrior", "early"): (
        "Your mornings are not your best time. That is not a discipline problem — it is chronobiology. "
        "Your nervous system peaks in the evening, and fighting that is costing you recovery quality. "
        "The fix is not forcing early mornings. It is building around your actual window."
    ),
    # Night Warrior — building
    ("night_warrior", "building"): (
        "You have started aligning your schedule with your biology instead of against it. "
        "The evening practice is working because that is when your system is ready. "
        "The morning reads are stabilising because you stopped apologising for your chronotype."
    ),
    # Night Warrior — optimise
    ("night_warrior", "optimise"): (
        "Your peak window is fully leveraged. "
        "Most people try to become morning people and fail indefinitely. "
        "You built a better system instead."
    ),

    # Loop Runner — early
    ("loop_runner", "early"): (
        "Your overnight data shows your nervous system is working during sleep instead of recovering. "
        "The thoughts running at 2am are not coincidental — the LF/HF signal during sleep confirms it. "
        "Sleep is not off time for you right now. It is just a different kind of active."
    ),
    # Loop Runner — building
    ("loop_runner", "building"): (
        "The pre-sleep protocol is changing the overnight signal. "
        "Your RMSSD is no longer dropping during sleep — it is starting to hold or rise. "
        "The mind is learning to let go before the body has to do it for it."
    ),
    # Loop Runner — optimise
    ("loop_runner", "optimise"): (
        "Sleep is doing what sleep is supposed to do. "
        "The overnight RMSSD is rising consistently. The morning reads reflect real restoration. "
        "You have solved the hardest nervous system problem — the one that happens while you're unconscious."
    ),

    # Purist — early
    ("purist", "early"): (
        "You have a practice and it is doing something — the coherence data confirms it. "
        "The gap is not in your discipline. It is in the one dimension your current approach does not reach. "
        "The data will show you exactly which one."
    ),
    # Purist — building
    ("purist", "building"): (
        "Your coherence is strong. Your baseline is respectable. "
        "The remaining gap is biological — load management or recovery arc, not technique. "
        "One physical layer added to your existing practice will close it."
    ),
    # Purist — optimise
    ("purist", "optimise"): (
        "Practice plus data plus movement. "
        "You have all three dimensions working together now. "
        "This is what nervous system fitness looks like when all the channels are open."
    ),

    # Dialled-In — all bands
    ("dialled_in", "early"): (
        "All five dimensions are above their midpoints. "
        "Recovery is fast, load is managed, and the practice is holding the system stable. "
        "You are at the entry point — what comes next is optimisation, not recovery."
    ),
    ("dialled_in", "building"): (
        "You are in the performance window. "
        "Your recovery can handle increased load. Your coherence is high. Your morning reads are strong. "
        "This is the phase where most people find their ceiling — and you are not at it yet."
    ),
    ("dialled_in", "optimise"): (
        "90+ is rare enough that the data rarely gets here. "
        "Your nervous system is running at the top of its accessible range. "
        "The work now is maintenance and exploration, not recovery."
    ),

    # Unclassified
    ("UNCLASSIFIED", "early"): (
        "The system needs a few more days of consistent data to read your pattern. "
        "That is not a problem — it is the process working correctly. "
        "Morning reads every day are the only task right now."
    ),
    ("UNCLASSIFIED", "building"): (
        "Your pattern is close to surfacing. The data is clean enough to see the shape. "
        "Keep the consistency — the picture sharpens with each morning read."
    ),
    ("UNCLASSIFIED", "optimise"): (
        "The data is consistent and your score is strong. "
        "Your specific pattern will clarify shortly. "
        "The practices that got you here are working — do not change them."
    ),
}


# ── Amplifier notes ────────────────────────────────────────────────────────────

_AMPLIFIER_NOTES: dict[str, str] = {
    "over_optimizer": (
        "Your Over-Optimizer pattern is adding fuel to this — "
        "the deliberate training load is compounding the baseline stress."
    ),
    "trend_chaser": (
        "A Trend Chaser thread is also visible — "
        "the inconsistency in the data suggests your practice is still searching for its form."
    ),
    "hustler": (
        "A Hustler pattern is amplifying this — "
        "work demands are stacking on top of the primary signal."
    ),
    "quiet_depleter": (
        "A Quiet Depleter current is running underneath — "
        "the slow floor drop is compounding what you are already managing."
    ),
    "night_warrior": (
        "A Night Warrior pattern is active alongside this — "
        "the chronotype mismatch is adding friction to your recovery window."
    ),
    "loop_runner": (
        "Your Loop Runner pattern is compounding this — "
        "the mind is running overnight when the body needs to be in repair mode."
    ),
    "purist": (
        "A Purist tendency is also present — "
        "your existing practice is providing some buffer against the primary signal."
    ),
}


def _amplifier_note(amplifier: Optional[str], stage: int) -> str:
    if amplifier is None:
        return ""
    return _AMPLIFIER_NOTES.get(amplifier, "")


# ── Dimension insights ─────────────────────────────────────────────────────────

_DIM_NAMES = {
    "recovery_capacity":   "Recovery Capacity",
    "baseline_resilience": "Baseline Resilience",
    "coherence_capacity":  "Coherence Capacity",
    "chrono_fit":          "Chronobiological Fit",
    "load_management":     "Load Management",
}

def _dimension_insight(dim: str, score: int) -> str:
    """Generate a one-sentence insight from a dimension name and 0–20 score."""
    tier = "low" if score <= 7 else ("moderate" if score <= 13 else "strong")

    _insights = {
        "recovery_capacity": {
            "low":      "Your nervous system is slow to return to baseline after physical or mental effort.",
            "moderate": "Recovery is happening, but not as fast or fully as it could be.",
            "strong":   "Your system resets quickly after load. This is a significant physiological asset.",
        },
        "baseline_resilience": {
            "low":      "Your resting nervous system floor is lower than optimal — the system has less reserve.",
            "moderate": "Your resting baseline is in the functional range, with room to build upwards.",
            "strong":   "Your floor is high and your ceiling is wide. This is the hallmark of a resilient system.",
        },
        "coherence_capacity": {
            "low":      "Your system is not yet responding strongly to guided practice. The potential is there — the practice needs time.",
            "moderate": "You are responding to practice. Consistency will deepen this signal.",
            "strong":   "Guided practice is clearly working at a physiological level. This is your primary adaptive lever.",
        },
        "chrono_fit": {
            "low":      "Your mornings are not your best time biologically — the data shows your system is not fully restored by waking.",
            "moderate": "Your chronobiological alignment is partially working. One schedule adjustment could unlock the rest.",
            "strong":   "Your sleep and daily schedule are aligned with your biology. You are waking into recovery, not debt.",
        },
        "load_management": {
            "low":      "The accumulated weekly stress is not clearing between cycles. The LF/HF balance at rest confirms it.",
            "moderate": "Load is manageable but accumulating. One more recovery buffer per week would shift this significantly.",
            "strong":   "Your sympathovagal balance at rest is healthy. Load is not outpacing your recovery capacity.",
        },
    }

    return _insights.get(dim, {}).get(tier, f"{_DIM_NAMES.get(dim, dim)}: {score}/20.")


def _dimension_insights(profile: NSHealthProfile) -> dict[str, str]:
    breakdown = profile.dimension_breakdown()
    return {dim: _dimension_insight(dim, score) for dim, score in breakdown.items()}


# ── Stage descriptions ─────────────────────────────────────────────────────────

_STAGE_DESCRIPTIONS: dict[int, str] = {
    0: (
        "Stage 0 is the starting point. "
        "The nervous system does not yet have enough consistent input to build a strong pattern. "
        "The work here is not optimisation — it is foundation-laying."
    ),
    1: (
        "Stage 1 is the most common entry zone. "
        "The system has a recognisable pattern but recovery is incomplete and load is not yet managed. "
        "One or two well-placed interventions make a measurable difference at this stage."
    ),
    2: (
        "Stage 2 means the foundation is there and the first adaptations are visible. "
        "Consistency is working. The score is stable enough to start building on intentionally. "
        "This is the zone where most people find the intervention that actually fits them."
    ),
    3: (
        "Stage 3 is full functionality. "
        "Recovery arcs are completing, load is managed, and the system is resilient under normal conditions. "
        "The focus shifts from fixing weak points to optimising strengths."
    ),
    4: (
        "Stage 4 is the performance zone. "
        "Every dimension is above its functional floor. The system handles load without accumulating debt. "
        "Athletes, practitioners, and people serious about long-term health typically live here."
    ),
    5: (
        "Stage 5 is the ceiling of what consistent effort produces. "
        "All five dimensions are operating near their physiological maximum. "
        "This level is rare and reflects sustained, intelligent practice over time."
    ),
}


# ── Evolution notes ────────────────────────────────────────────────────────────

_EVOLUTION_NOTES: dict[int, str] = {
    0: (
        "Stage 1 unlocks once your morning reads are consistent and at least one dimension crosses its midpoint. "
        "That is the only target right now."
    ),
    1: (
        "Stage 2 comes from two or three dimensions moving past 10/20 and staying there for at least two weeks. "
        "Pick your lowest dimension from the breakdown. That is the work."
    ),
    2: (
        "Stage 3 requires all five dimensions above their midpoints and the total clearing 70. "
        "You are closer than you think — look at your two lowest scores."
    ),
    3: (
        "Stage 4 is about depth, not breadth. "
        "At least two dimensions need to reach 15+ before the total moves into the 80s. "
        "Physical load capacity and load management are usually the unlock."
    ),
    4: (
        "Stage 5 requires all dimensions operating near ceiling, which means both structural fitness "
        "and consistent practice running simultaneously. This is a multi-month arc."
    ),
    5: (
        "You are at the ceiling stage. "
        "The work now is maintenance and exploration — not climbing."
    ),
}


def _evolution_note(stage: int) -> str:
    return _EVOLUTION_NOTES.get(stage, _EVOLUTION_NOTES[5])
