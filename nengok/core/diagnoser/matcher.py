"""
Cross-cycle cluster identity: decide whether a fresh cluster is a
recurrence of one the store already knows.

Pass 1 is plain code: an exact match on the normalized kebab name.
Pass 2 asks ``config.judge_model`` whether a near-miss candidate (one
sharing at least one anomaly signal) describes the same failure, and
accepts at ``config.cluster_match_threshold`` confidence. Callers pass
only same-project clusters in ``existing``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from nengok.config import NengokConfig
from nengok.core.cost import CostTracker
from nengok.core.diagnoser._text import strip_code_fence
from nengok.core.types import Cluster
from nengok.utils.gemini import RetryPolicy, call_gemini
from nengok.utils.logging import get_logger

logger = get_logger(__name__)

GeminiTextCall = Callable[[str], str]


class _MatchVerdict(BaseModel):
    same_failure: bool
    confidence: float


@dataclass
class ClusterMatcher:
    config: NengokConfig
    gemini_call: GeminiTextCall | None = None
    cost_tracker: CostTracker | None = None

    def match(self, candidate: Cluster, existing: list[Cluster]) -> str | None:
        """
        Return the existing ``cluster_id`` to adopt, or None for a new cluster.

        The name pass is free; the judge pass costs one Flash call per
        near-miss and stops at the first confirmed match.
        """
        for row in existing:
            if row.name == candidate.name:
                logger.info(
                    "Matcher: candidate '%s' adopts cluster %s by exact name",
                    candidate.name,
                    row.cluster_id,
                )
                return row.cluster_id

        candidate_signals = set(candidate.signals)
        near_misses = [row for row in existing if candidate_signals & set(row.signals)]
        for row in near_misses:
            verdict = self._judge(candidate, row)
            if verdict is None:
                continue
            if verdict.same_failure and verdict.confidence >= self.config.cluster_match_threshold:
                logger.info(
                    "Matcher: candidate '%s' adopts cluster %s by judge (confidence=%.2f)",
                    candidate.name,
                    row.cluster_id,
                    verdict.confidence,
                )
                return row.cluster_id
        return None

    def _judge(self, candidate: Cluster, existing: Cluster) -> _MatchVerdict | None:
        prompt = _build_match_prompt(candidate, existing)
        gemini = self.gemini_call or self._default_gemini_call
        raw = gemini(prompt)
        try:
            return _MatchVerdict.model_validate_json(strip_code_fence(raw))
        except ValidationError:
            logger.warning(
                "Matcher verdict failed validation for candidate '%s' vs %s; treating as no match",
                candidate.name,
                existing.cluster_id,
            )
            return None

    def _default_gemini_call(self, prompt: str) -> str:
        from nengok.utils.genai_client import build_genai_client

        client = build_genai_client(self.config, role="Cluster Matcher")
        from google.genai import types

        return call_gemini(
            client,
            model=self.config.judge_model,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_MatchVerdict,
            ),
            env_var_hint="NENGOK_JUDGE_MODEL",
            role_hint="Cluster Matcher",
            retry_policy=RetryPolicy.from_config(self.config),
            cost_tracker=self.cost_tracker,
        )


def _cluster_block(cluster: Cluster) -> dict[str, str | list[str]]:
    return {
        "name": cluster.name,
        "description": cluster.description,
        "hypothesis_summary": cluster.hypothesis.summary if cluster.hypothesis else "(none)",
        "signals": cluster.signals,
    }


def _build_match_prompt(candidate: Cluster, existing: Cluster) -> str:
    schema_hint = json.dumps(_MatchVerdict.model_json_schema(), indent=2)
    return (
        "You are deciding whether two failure clusters from an LLM agent "
        "monitoring system describe the same underlying failure mode.\n\n"
        f"Cluster A (new this cycle):\n{json.dumps(_cluster_block(candidate), indent=2)}\n\n"
        f"Cluster B (known from earlier cycles):\n{json.dumps(_cluster_block(existing), indent=2)}\n\n"
        "Same symptom wording is not enough; judge whether the likely root "
        "cause is the same. Report your confidence between 0 and 1.\n\n"
        f"Return ONLY a JSON object matching this schema:\n{schema_hint}\n"
    )
