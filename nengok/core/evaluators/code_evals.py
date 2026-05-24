"""
Code-based evaluators.

These are the default-pass evaluators applied to every experiment. They
cover objectively verifiable criteria (schema, presence, format) — the
kinds of checks where an LLM-as-Judge would only add bias.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

CodeEvaluator = Callable[[Any, Any], bool]


def output_is_present(output: Any, expected: Any) -> bool:
    """Reject empty / null outputs."""
    del expected
    if output is None:
        return False
    if isinstance(output, str) and not output.strip():
        return False
    return True


def output_is_valid_json(output: Any, expected: Any) -> bool:
    """When the dataset's expected slot says `is_json: true`, the output must parse."""
    del expected
    if not isinstance(output, str):
        return True
    try:
        json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return False
    return True


def contains_expected_substring(output: Any, expected: Any) -> bool:
    """Pass if `expected["contains"]` appears in the rendered output."""
    if not isinstance(expected, dict):
        return True
    needle = expected.get("contains")
    if not needle:
        return True
    return needle in str(output)


def default_code_evaluators() -> list[CodeEvaluator]:
    return [output_is_present, output_is_valid_json, contains_expected_substring]
