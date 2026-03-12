import json

from typing import Dict, List
from tagging.auto_tagger import TagPattern

class TagPatternLearner:
    def update_model(self, pattern_model, confirmed: bool, evt_time, hr_bump, rmssd_drop):
        model_data = pattern_model.model_json if pattern_model.model_json else {}
        patterns_built = pattern_model.patterns_built or 0
        if confirmed:
            pattern_model.patterns_built = patterns_built + 1
            pass

class UserTagPatternModel:
    def __init__(self, user_id: str = "", patterns: Dict[str, TagPattern] = None, sport_stressor_slugs: List[str] = None, auto_tag_eligible_slugs: frozenset = None):
        self.user_id = user_id
        self.patterns = patterns if patterns is not None else {}
        self.sport_stressor_slugs = sport_stressor_slugs if sport_stressor_slugs is not None else []
        self.auto_tag_eligible_slugs = auto_tag_eligible_slugs if auto_tag_eligible_slugs is not None else frozenset()

    @classmethod
    def from_dict(cls, data):
        user_id = data.get("user_id", "")
        sport_stressor_slugs = data.get("sport_stressor_slugs", [])
        
        patterns = {}
        for k, v in data.get("patterns", {}).items():
            hour_hist = {int(hk): hv for hk, hv in v.get("hour_histogram", {}).items()}
            weekday_counts = {int(wk): wv for wk, wv in v.get("weekday_counts", {}).items()}
            # Reconstruct the dict to properly instantiate TagPattern
            pattern_data = {
                "tag": v.get("tag", ""),
                "window_type": v.get("window_type", ""),
                "confirmed_count": v.get("confirmed_count", 0),
                "avg_suppression": v.get("avg_suppression", 0.0),
                "hour_histogram": hour_hist,
                "weekday_counts": weekday_counts
            }
            patterns[k] = TagPattern(**pattern_data)
            
        auto_tag_eligible_slugs = set()
        for k, p in patterns.items():
            if p.confirmed_count >= 3:
                auto_tag_eligible_slugs.add(p.tag)

        return cls(
            user_id=user_id,
            patterns=patterns,
            sport_stressor_slugs=sport_stressor_slugs,
            auto_tag_eligible_slugs=frozenset(auto_tag_eligible_slugs)
        )
        
    def to_dict(self):
        return {
            "user_id": self.user_id,
            "patterns": {
                k: {
                    "tag": v.tag,
                    "window_type": v.window_type,
                    "confirmed_count": v.confirmed_count,
                    "hour_histogram": v.hour_histogram,
                    "weekday_counts": v.weekday_counts,
                    "avg_suppression": v.avg_suppression
                } for k, v in self.patterns.items()
            },
            "sport_stressor_slugs": self.sport_stressor_slugs,
            "auto_tag_eligible_slugs": list(self.auto_tag_eligible_slugs)
        }
