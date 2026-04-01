"""
Shared text sanitization utilities for coach prompt inputs.
"""

from __future__ import annotations

import re
from typing import Optional

# Block common prompt-injection/control delimiters while preserving normal prose.
_UNSAFE = re.compile(r"[<>{}`|#\\]", re.UNICODE)


def sanitize_text(text: Optional[str], *, max_len: int = 200) -> str:
    """Remove unsafe characters and truncate to max_len."""
    cleaned = _UNSAFE.sub("", (text or "")).strip()
    if not cleaned:
        return ""
    return cleaned[:max_len]
