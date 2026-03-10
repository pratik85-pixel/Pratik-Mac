"""
coach — AI coaching layer.

Public surface
--------------
    from coach.plan_replanner      import compute_daily_prescription, DailyPrescription, HabitSignal
    from coach.tone_selector       import select_tone
    from coach.context_builder     import build_coach_context, CoachContext
    from coach.milestone_detector  import detect_milestone, Milestone
    from coach.memory_store        import MemoryStore, ConversationState
    from coach.safety_filter       import screen_text, SafetyResult
    from coach.schema_validator    import validate_output
    from coach.prompt_templates    import build_prompts
    from coach.conversation_extractor import extract_signals_from_message
    from coach.local_engine        import generate_local_output
    from coach.coach_api           import generate_response
    from coach.conversation        import ConversationManager

Design: "The LLM writes sentences. Python makes all decisions."
"""

from coach.plan_replanner          import compute_daily_prescription, DailyPrescription, HabitSignal
from coach.tone_selector           import select_tone
from coach.context_builder         import build_coach_context, CoachContext
from coach.milestone_detector      import detect_milestone, Milestone
from coach.memory_store            import MemoryStore, ConversationState
from coach.safety_filter           import screen_text, SafetyResult
from coach.schema_validator        import validate_output
from coach.prompt_templates        import build_prompts
from coach.conversation_extractor  import extract_signals_from_message, ExtractionResult
from coach.local_engine            import generate_local_output
from coach.coach_api               import generate_response
from coach.conversation            import ConversationManager

__all__ = [
    "compute_daily_prescription", "DailyPrescription", "HabitSignal",
    "select_tone",
    "build_coach_context", "CoachContext",
    "detect_milestone", "Milestone",
    "MemoryStore", "ConversationState",
    "screen_text", "SafetyResult",
    "validate_output",
    "build_prompts",
    "extract_signals_from_message", "ExtractionResult",
    "generate_local_output",
    "generate_response",
    "ConversationManager",
]
