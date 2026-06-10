"""
Propose a prompt-level fix for one cluster.

The proposer loads the active baseline prompt (from a bundled file for
the sample agent, from Phoenix prompt management otherwise, or from
``config.baseline_prompt_path`` as a fallback), then asks Gemini for a
tight diff that targets the cluster's failure mode without rewriting
the whole prompt.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from nengok.config import NengokConfig
from nengok.core.cost import CostTracker
from nengok.core.fixer.loaders import (
    BaselinePromptLoader,
    load_baseline_prompt_loader,
)
from nengok.core.observer.redactor import Redactor
from nengok.core.types import Cluster, PromptProposal, TraceSpan
from nengok.errors import BaselinePromptError
from nengok.phoenix.client import PhoenixWrapper
from nengok.utils.gemini import RetryPolicy, call_gemini
from nengok.utils.logging import get_logger

logger = get_logger(__name__)

MAX_PROPOSER_EXEMPLARS = 3

GeminiTextCall = Callable[[str], str]

_CODE_FENCE_OPEN = re.compile(r"^```(?:json)?\s*", re.IGNORECASE)
_CODE_FENCE_CLOSE = re.compile(r"\s*```\s*$")


class _GeminiProposal(BaseModel):
    proposed_prompt: str
    rationale: str


@dataclass
class PromptProposer:
    config: NengokConfig
    phoenix: PhoenixWrapper | None = None
    gemini_call: GeminiTextCall | None = None
    cost_tracker: CostTracker | None = None
    redactor: Redactor | None = None
    baseline_loader: BaselinePromptLoader | None = None

    def propose(self, cluster: Cluster, *, baseline_prompt: str | None = None) -> PromptProposal:
        """
        Propose a prompt-level fix for ``cluster``.

        ``baseline_prompt`` lets callers (the orchestrator) inject a
        baseline they already loaded for upstream stages so the proposer
        does not re-read it from disk or Phoenix.
        """
        baseline = baseline_prompt if baseline_prompt is not None else self.load_baseline_prompt()
        exemplars = self._load_exemplars(cluster)
        draft = self._call_gemini_proposer(cluster=cluster, baseline=baseline, exemplars=exemplars)
        return PromptProposal(
            cluster_id=cluster.cluster_id,
            baseline_prompt=baseline,
            proposed_prompt=draft.proposed_prompt,
            rationale=draft.rationale,
        )

    def load_baseline_prompt(self, project: str | None = None) -> str:
        """
        Resolve the agent's current prompt via the configured loader.

        The default loader walks the bundled sample-agent file, then
        Phoenix prompt management, then ``config.baseline_prompt_path``.
        Users override ``config.baseline_prompt_loader`` to plug in
        their own source. ``project`` defaults to the configured single
        project; multi-project cycles pass each project explicitly.
        """
        resolved_project = project or self.config.project_identifier
        loader = self.baseline_loader or load_baseline_prompt_loader(
            self.config.baseline_prompt_loader,
            config=self.config,
            phoenix=self.phoenix,
        )
        resolved = loader.load(resolved_project)
        if resolved:
            return resolved

        raise BaselinePromptError(
            f"No baseline prompt resolved for project "
            f"'{resolved_project}'. Either register a prompt in "
            "Phoenix Prompt Management under that name, or set "
            '`baseline_prompt_path = "/path/to/prompt.md"` in '
            "`~/.nengok/config.toml`. The sample agent at "
            "`travel-planner-agent` ships with a bundled prompt and needs no setup.",
            project_identifier=resolved_project,
        )

    def _load_exemplars(self, cluster: Cluster) -> list[TraceSpan]:
        if self.phoenix is None or not cluster.exemplar_span_ids:
            return []
        wanted = cluster.exemplar_span_ids[:MAX_PROPOSER_EXEMPLARS]
        return self.phoenix.get_spans_by_ids(
            project_identifier=cluster.project or self.config.project_identifier,
            span_ids=wanted,
        )

    def _call_gemini_proposer(
        self,
        *,
        cluster: Cluster,
        baseline: str,
        exemplars: list[TraceSpan],
    ) -> _GeminiProposal:
        redactor = self.redactor or Redactor.from_config(self.config)
        prompt = _build_proposer_prompt(
            cluster=cluster,
            baseline=baseline,
            exemplars=exemplars,
            char_budget=self.config.cluster_trace_char_budget,
            redactor=redactor,
        )
        gemini = self.gemini_call or self._default_gemini_call
        raw = gemini(prompt)
        try:
            return _GeminiProposal.model_validate_json(_strip_code_fence(raw))
        except ValidationError:
            logger.warning(
                "Proposer response failed validation for cluster=%s; retrying once",
                cluster.cluster_id,
            )
            retry_prompt = (
                prompt + "\n\nReturn ONLY valid JSON matching the schema. "
                "No prose, no markdown, no code fence."
            )
            retry = gemini(retry_prompt)
            return _GeminiProposal.model_validate_json(_strip_code_fence(retry))

    def _default_gemini_call(self, prompt: str) -> str:
        from nengok.utils.genai_client import build_genai_client

        client = build_genai_client(self.config, role="Prompt Proposer")
        from google.genai import types

        return call_gemini(
            client,
            model=self.config.diagnoser_model,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_GeminiProposal,
            ),
            env_var_hint="NENGOK_DIAGNOSER_MODEL",
            role_hint="Prompt Proposer",
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
    exemplars: list[TraceSpan],
    char_budget: int,
    *,
    redactor: Redactor,
) -> list[dict[str, Any]]:
    return [
        {
            "span_id": span.span_id,
            "input": redactor.redact(_trim(span.input_value, char_budget)),
            "output": redactor.redact(_trim(span.output_value, char_budget)),
        }
        for span in exemplars
    ]


def _build_proposer_prompt(
    *,
    cluster: Cluster,
    baseline: str,
    exemplars: list[TraceSpan],
    char_budget: int,
    redactor: Redactor,
) -> str:
    hypothesis = cluster.hypothesis
    hypothesis_block = (
        json.dumps(hypothesis.model_dump(), indent=2)
        if hypothesis is not None
        else "(no hypothesis available)"
    )
    rows = _exemplar_rows(exemplars[:MAX_PROPOSER_EXEMPLARS], char_budget, redactor=redactor)
    schema_hint = json.dumps(_GeminiProposal.model_json_schema(), indent=2)

    return (
        "You are proposing a minimal prompt edit to fix one failure mode in an "
        "LLM agent.\n\n"
        f"Cluster: {cluster.name}\n"
        f"Description: {cluster.description}\n\n"
        "Root-cause hypothesis (JSON):\n"
        f"{hypothesis_block}\n\n"
        "Baseline prompt:\n"
        "----- BEGIN PROMPT -----\n"
        f"{baseline}\n"
        "----- END PROMPT -----\n\n"
        f"Exemplar failures (JSON list):\n{json.dumps(rows, indent=2, default=str)}\n\n"
        "Add or change the smallest possible guardrail or instruction that fixes "
        "this failure mode. Do not rewrite the prompt. Keep all other instructions "
        "intact. Return the FULL updated prompt in `proposed_prompt` and a short "
        "human-readable explanation in `rationale`.\n\n"
        f"Return ONLY a JSON object matching this schema:\n{schema_hint}\n"
    )
