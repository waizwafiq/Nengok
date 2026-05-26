"""Test fixtures referenced by test_redactor.py for the callable escape hatch."""

from __future__ import annotations


def upper_redactor(text: str) -> str:
    return text.upper()
