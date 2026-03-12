class IntradayMatcher:
    def match(self, plan_items: list, new_tag: str) -> bool:
        for item in plan_items:
            if new_tag == item.get('activity_target') or new_tag == item.get('activity_slug'):
                if not item.get('has_evidence'):
                    item['has_evidence'] = True
                    return True
        return False