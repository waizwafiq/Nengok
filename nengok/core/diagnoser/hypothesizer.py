"""
Generate a root-cause hypothesis for one cluster.

Per the proposal's "code-first, LLM-second" rule, this stage is one of
the few places where Gemini's reasoning is irreplaceable: the task
is to read 3-5 exemplar traces and propose what went wrong upstream.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from nengok.config import NengokConfig
from nengok.core.cost import CostTracker
from nengok.core.observer.redactor import Redactor
from nengok.core.types import Cluster, RootCauseHypothesis, TraceSpan
from nengok.errors import MissingApiKeyError
from nengok.phoenix.client import PhoenixWrapper
from nengok.utils.gemini import RetryPolicy, call_gemini
from nengok.utils.logging import get_logger

logger = get_logger(__name__)

GeminiTextCall = Callable[[str], str]

_CODE_FENCE_OPEN = re.compile(r"^```(?:json)?\s*", re.IGNORECASE)
_CODE_FENCE_CLOSE = re.compile(r"\s*```\s*$")


@dataclass
class Hypothesizer:
    config: NengokConfig
    phoenix: PhoenixWrapper | None = None
    gemini_call: GeminiTextCall | None = None
    cost_tracker: CostTracker | None = None
    redactor: Redactor | None = None

    def hypothesize(
        self,
        cluster: Cluster,
        *,
        current_prompt: str | None = None,
    ) -> RootCauseHypothesis:
        """Return a structured root-cause hypothesis for ``cluster``."""
        exemplars = self._load_exemplars(cluster)
        return self._call_gemini_diagnoser(
            cluster=cluster,
            exemplars=exemplars,
            current_prompt=current_prompt,
        )

    def _load_exemplars(self, cluster: Cluster) -> list[TraceSpan]:
        if not self.phoenix or not cluster.exemplar_span_ids:
            return []
        return self.phoenix.get_spans_by_ids(
            project_identifier=self.config.project_identifier,
            span_ids=cluster.exemplar_span_ids,
        )

    def _call_gemini_diagnoser(
        self,
        *,
        cluster: Cluster,
        exemplars: list[TraceSpan],
        current_prompt: str | None,
    ) -> RootCauseHypothesis:
        """
        Ask Gemini for a structured root-cause hypothesis.

        Production calls pass ``response_schema=RootCauseHypothesis`` so
        the API enforces JSON shape. We still validate with Pydantic to
        catch drift, and retry once with a stricter reminder when the
        first response fails ``ValidationError``.
        """
        redactor = self.redactor or Redactor.from_config(self.config)
        prompt = _build_diagnoser_prompt(
            cluster=cluster,
            exemplars=exemplars,
            current_prompt=current_prompt,
            char_budget=self.config.cluster_trace_char_budget,
            redactor=redactor,
        )
        gemini = self.gemini_call or self._default_gemini_call
        raw = gemini(prompt)
        try:
            return RootCauseHypothesis.model_validate_json(_strip_code_fence(raw))
        except ValidationError:
            logger.warning(
                "Hypothesizer response failed validation for cluster=%s; retrying once",
                cluster.cluster_id,
            )
            retry_prompt = (
                prompt + "\n\nReturn ONLY valid JSON matching the schema. "
                "No prose, no markdown, no code fence."
            )
            retry = gemini(retry_prompt)
            return RootCauseHypothesis.model_validate_json(_strip_code_fence(retry))

    def _default_gemini_call(self, prompt: str) -> str:
        api_key = self.config.google_api_key or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise MissingApiKeyError(
                "Hypothesizer needs a Gemini API key. Set `GOOGLE_API_KEY` in your "
                'environment (or `.env`), or write `google_api_key = "..."` into '
                "`~/.nengok/config.toml`. Get a key at https://aistudio.google.com/app/apikey.",
                role="Hypothesizer",
            )
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        return call_gemini(
            client,
            model=self.config.diagnoser_model,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=RootCauseHypothesis,
            ),
            env_var_hint="NENGOK_DIAGNOSER_MODEL",
            role_hint="Hypothesizer",
            retry_policy=RetryPolicy.from_config(self.config),
            cost_tracker=self.cost_tracker,
        )


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    without_open = _CODE_FENCE_OPEN.sub("", stripped, count=1)
    return _CODE_FENCE_CLOSE.sub("", without_open).strip()


def _trim(value: str | None, budget: int) -> str:
    if not value:
        return ""
    if len(value) <= budget:
        return value
    return value[:budget] + "...<truncated>"


def _exemplar_rows(
    cluster: Cluster,
    exemplars: list[TraceSpan],
    char_budget: int,
    *,
    redactor: Redactor,
) -> list[dict[str, Any]]:
    by_id = {span.span_id: span for span in exemplars}
    rows: list[dict[str, Any]] = []
    for span_id in cluster.exemplar_span_ids:
        span = by_id.get(span_id)
        if span is None:
            rows.append({"span_id": span_id, "note": "exemplar not retrievable from Phoenix"})
            continue
        rows.append(
            {
                "span_id": span.span_id,
                "operation": span.name,
                "status_code": span.status_code,
                "latency_ms": span.latency_ms,
                "input": redactor.redact(_trim(span.input_value, char_budget)),
                "output": redactor.redact(_trim(span.output_value, char_budget)),
                "attributes": span.attributes,
            }
        )
    return rows


def _build_diagnoser_prompt(
    *,
    cluster: Cluster,
    exemplars: list[TraceSpan],
    current_prompt: str | None,
    char_budget: int,
    redactor: Redactor,
) -> str:
    schema_hint = json.dumps(RootCauseHypothesis.model_json_schema(), indent=2)
    rows = _exemplar_rows(cluster, exemplars, char_budget, redactor=redactor)
    prompt_block = current_prompt.strip() if current_prompt else "(baseline prompt not provided)"

    return (
        "You are diagnosing a single failure cluster from an LLM agent's "
        "production traces.\n\n"
        f"Cluster name: {cluster.name}\n"
        f"Cluster description: {cluster.description}\n\n"
        "Current agent prompt:\n"
        "----- BEGIN PROMPT -----\n"
        f"{prompt_block}\n"
        "----- END PROMPT -----\n\n"
        f"Exemplar traces (JSON list):\n{json.dumps(rows, indent=2, default=str)}\n\n"
        "Identify the upstream cause. Name the tools or instructions most likely "
        "responsible in `implicated_tools`. Be specific; avoid vague hedging.\n\n"
        f"Return ONLY a JSON object matching this schema:\n{schema_hint}\n"
    )
