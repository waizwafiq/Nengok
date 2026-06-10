"""Text helpers shared by the diagnoser's Gemini call sites."""

from __future__ import annotations

import re

_CODE_FENCE_OPEN = re.compile(r"^```(?:json)?\s*", re.IGNORECASE)
_CODE_FENCE_CLOSE = re.compile(r"\s*```\s*$")


def strip_code_fence(text: str) -> str:
    """Drop a single ```json fence the model may wrap its response in."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    without_open = _CODE_FENCE_OPEN.sub("", stripped, count=1)
    return _CODE_FENCE_CLOSE.sub("", without_open).strip()


def trim(value: str | None, budget: int) -> str:
    """Cap ``value`` at ``budget`` characters with an explicit truncation marker."""
    if not value:
        return ""
    if len(value) <= budget:
        return value
    return value[:budget] + "...<truncated>"
