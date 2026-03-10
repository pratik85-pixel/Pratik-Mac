"""
api/utils.py

Shared utility helpers for the API layer.
"""
from __future__ import annotations

import uuid
from typing import Optional


def parse_uuid(value: str) -> Optional[uuid.UUID]:
    """
    Parse a string into a UUID, returning None for invalid or missing values.
    Prevents unhandled ValueError 500s when non-UUID user identifiers are used
    (e.g. plain strings in tests or early-registration flows).
    """
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return None
