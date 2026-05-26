"""
Generate regression test cases targeted at a single failure cluster.

These cases are written to Phoenix as a Dataset (by the experiment
runner) and also persisted locally to the artifacts directory after
verification.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from nengok.config import NengokConfig
from nengok.core.types import Cluster, RegressionTestCase
from nengok.utils.gemini import call_gemini
from nengok.utils.logging import get_logger

logger = get_logger(__name__)

MIN_REGRESSION_CASES = 5
MAX_REGRESSION_CASES = 20

GeminiTextCall = Callable[[str], str]

_CODE_FENCE_OPEN = re.compile(r"^```(?:json)?\s*", re.IGNORECASE)
_CODE_FENCE_CLOSE = re.compile(r"\s*```\s*$")


class _GeminiCase(BaseModel):
    input: dict[str, Any]
    expected: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class _GeminiCaseList(BaseModel):
    cases: list[_GeminiCase]


@dataclass
class TestGenerator:
    config: NengokConfig
    gemini_call: GeminiTextCall | None = None

    def generate(self, cluster: Cluster) -> list[RegressionTestCase]:
        """Return 5-20 RegressionTestCase rows for the given cluster."""
        cases = self._call_gemini_test_generator(cluster)
        capped = cases[:MAX_REGRESSION_CASES]
        logger.info("Generated %d regression cases for cluster '%s'", len(capped), cluster.name)
        return [self._materialize(case, cluster) for case in capped]

    def _materialize(self, case: _GeminiCase, cluster: Cluster) -> RegressionTestCase:
        metadata = dict(case.metadata)
        metadata.update(
            {
                "cluster_id": cluster.cluster_id,
                "cluster_name": cluster.name,
                "failure_signal": cluster.name,
                "generator_model": self.config.diagnoser_model,
            }
        )
        return RegressionTestCase(
            case_id=str(uuid.uuid4()),
            input=case.input,
            expected=case.expected,
            metadata=metadata,
        )

    def _call_gemini_test_generator(self, cluster: Cluster) -> list[_GeminiCase]:
        """
        Ask Gemini for 5-20 regression cases. Retry once with a larger
        ask when the first response is short; log and proceed if the
        retry is still under the minimum.
        """
        first = self._ask_gemini(cluster, target=MIN_REGRESSION_CASES)
        if len(first) >= MIN_REGRESSION_CASES:
            return first

        logger.warning(
            "Test generator returned %d < %d cases for cluster '%s'; retrying with larger ask",
            len(first),
            MIN_REGRESSION_CASES,
            cluster.name,
        )
        retry = self._ask_gemini(cluster, target=MAX_REGRESSION_CASES)
        chosen = retry if len(retry) > len(first) else first
        if len(chosen) < MIN_REGRESSION_CASES:
            logger.warning(
                "Test generator still under minimum (%d < %d) after retry; proceeding",
                len(chosen),
                MIN_REGRESSION_CASES,
            )
        return chosen

    def _ask_gemini(self, cluster: Cluster, *, target: int) -> list[_GeminiCase]:
        prompt = _build_generator_prompt(
            cluster=cluster,
            target=target,
            char_budget=self.config.cluster_trace_char_budget,
        )
        gemini = self.gemini_call or self._default_gemini_call
        raw = gemini(prompt)
        try:
            return _GeminiCaseList.model_validate_json(_strip_code_fence(raw)).cases
        except ValidationError:
            logger.warning(
                "Test generator response failed validation for cluster=%s; retrying once",
                cluster.cluster_id,
            )
            retry_prompt = (
                prompt + "\n\nReturn ONLY valid JSON matching the schema above. "
                "No prose, no markdown, no code fence."
            )
            retry = gemini(retry_prompt)
            return _GeminiCaseList.model_validate_json(_strip_code_fence(retry)).cases

    def _default_gemini_call(self, prompt: str) -> str:
        from google import genai
        from google.genai import types

        api_key = self.config.google_api_key or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Gemini test generator needs GOOGLE_API_KEY in the environment "
                "or google_api_key in the Nengok config."
            )
        client = genai.Client(api_key=api_key)
        # response_schema is omitted on purpose: _GeminiCase has dict[str, Any]
        # fields, and Pydantic v2 emits `additionalProperties` for those, which
        # the Gemini Developer API rejects (only Vertex/Enterprise mode accepts
        # it). The prompt already embeds the schema and _ask_gemini retries
        # once on a ValidationError, so reliability stays roughly equivalent.
        return call_gemini(
            client,
            model=self.config.diagnoser_model,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
            env_var_hint="NENGOK_DIAGNOSER_MODEL",
            role_hint="Test Generator",
        )


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    without_open = _CODE_FENCE_OPEN.sub("", stripped, count=1)
    return _CODE_FENCE_CLOSE.sub("", without_open).strip()


def _build_generator_prompt(*, cluster: Cluster, target: int, char_budget: int) -> str:
    hypothesis = cluster.hypothesis
    hypothesis_block = (
        json.dumps(hypothesis.model_dump(), indent=2)
        if hypothesis is not None
        else "(no hypothesis available)"
    )
    schema_hint = json.dumps(_GeminiCaseList.model_json_schema(), indent=2)
    description = cluster.description[:char_budget]

    return (
        "You are writing regression tests for one specific failure mode in an "
        "LLM agent.\n\n"
        f"Cluster: {cluster.name}\n"
        f"Description: {description}\n\n"
        "Root-cause hypothesis (JSON):\n"
        f"{hypothesis_block}\n\n"
        f"Generate between {MIN_REGRESSION_CASES} and {MAX_REGRESSION_CASES} regression "
        f"test cases (aim for {target}). Each case must reproduce the failure mode "
        "above. Vary the inputs so the suite has coverage, not duplicates.\n\n"
        "Each case has three keys:\n"
        "  - `input`: a JSON object the agent would receive\n"
        "  - `expected`: a JSON object describing what a passing response looks like\n"
        "  - `metadata`: free-form JSON object (may be empty)\n\n"
        f"Return ONLY a JSON object matching this schema:\n{schema_hint}\n"
    )
