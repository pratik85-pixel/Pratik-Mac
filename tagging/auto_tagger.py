import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

AUTO_TAG_THRESHOLD = 0.8
AUTOTAG_MIN_CONFIRMED = 3
HOUR_BAND_WIDTH = 2

@dataclass
class TagEvent:
    hour: int
    weekday: int
    window_type: str
    tag: Optional[str] = None
    suppression_pct: Optional[float] = None

@dataclass
class TagPattern:
    tag: str = ''
    confirmed_count: int = 0
    hour_histogram: Dict[int, int] = field(default_factory=dict)
    weekday_counts: Dict[int, int] = field(default_factory=dict)
    avg_suppression: float = 0.0
    window_type: str = ''

@dataclass
class SuggestionResult:
    best_tag: Optional[str]
    eligible: bool
    confidence: float
    all_scores: Dict[str, float] = field(default_factory=dict)

def _hour_score(hour: int, histogram: Dict[int, int]) -> float:
    if not histogram:
        return 0.0
    
    total_events = sum(histogram.values())
    if total_events == 0:
        return 0.0
        
    score = 0.0
    for h, count in histogram.items():
        diff = abs(hour - h)
        if diff > 12:
            diff = 24 - diff
            
        if diff == 0:
            score += count * 1.0
        elif diff <= HOUR_BAND_WIDTH:
            weight = 1.0 - (diff / (HOUR_BAND_WIDTH + 1))
            score += count * weight
            
    return score / total_events

def _weekday_score(weekday: int, counts: Dict[int, int]) -> float:
    if not counts:
        return 0.0
    total_events = sum(counts.values())
    if total_events == 0:
        return 0.0
    
    count = counts.get(weekday, 0)
    return count / total_events

def build_patterns(events: List[TagEvent]) -> Dict[str, TagPattern]:
    patterns: Dict[str, TagPattern] = {}
    
    for event in events:
        if not event.tag:
            continue
            
        if event.tag not in patterns:
            patterns[event.tag] = TagPattern(window_type=event.window_type)
            
        pattern = patterns[event.tag]
        pattern.confirmed_count += 1
        
        pattern.hour_histogram[event.hour] = pattern.hour_histogram.get(event.hour, 0) + 1
        pattern.weekday_counts[event.weekday] = pattern.weekday_counts.get(event.weekday, 0) + 1
        
    final_patterns = {}
    for tag, pattern in patterns.items():
        if pattern.confirmed_count >= AUTOTAG_MIN_CONFIRMED:
            tag_events = [e for e in events if e.tag == tag and e.suppression_pct is not None]
            if tag_events:
                pattern.avg_suppression = sum(e.suppression_pct for e in tag_events) / len(tag_events)
            final_patterns[tag] = pattern
            
    return final_patterns

def suggest_tag(candidate: TagEvent, patterns: Dict[str, TagPattern]) -> SuggestionResult:
    if not patterns:
        return SuggestionResult(best_tag=None, eligible=False, confidence=0.0)
        
    best_tag = None
    best_score = 0.0
    all_scores = {}
    
    for tag, pattern in patterns.items():
        if candidate.window_type != pattern.window_type:
            all_scores[tag] = 0.0
            continue
            
        h_score = _hour_score(candidate.hour, pattern.hour_histogram)
        w_score = _weekday_score(candidate.weekday, pattern.weekday_counts)
        
        # simple weighting: weight tests say "different hour reduces confidence", let's use equal or some weight
        score = (h_score * 0.7) + (w_score * 0.3)
        all_scores[tag] = score
        
        if score > best_score:
            best_score = score
            best_tag = tag
            
    eligible = best_score >= AUTO_TAG_THRESHOLD
    if eligible and best_tag:
        return SuggestionResult(best_tag=best_tag, eligible=True, confidence=best_score, all_scores=all_scores)
    return SuggestionResult(best_tag=best_tag if best_score > 0 else None, eligible=False, confidence=best_score, all_scores=all_scores)

class AutoTagger:
    """Pattern-based auto-tagging engine"""
    
    def predict_tag(self, user_id: str, start_time: datetime.datetime, end_time: datetime.datetime, hr_bump: float, rmssd_drop: float) -> Optional[str]:
        # TODO: Implement probabilistic matching using TagPatternModel
        return None
