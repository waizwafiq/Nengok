"""
Cross-agent cluster detection: when two monitored agents fail for the
same upstream reason, link the clusters instead of presenting them as
unrelated.

Candidate pairs come from cheap plain-code heuristics (shared
implicated tools, overlapping anomaly-signal profiles, name token
overlap); one ``config.judge_model`` call per surviving pair confirms
or denies the link.
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


class _LinkVerdict(BaseModel):
    linked: bool
    confidence: float
    rationale: str


class ClusterLink(BaseModel):
    cluster_id_a: str
    cluster_id_b: str
    confidence: float
    rationale: str


@dataclass
class CrossAgentLinker:
    config: NengokConfig
    gemini_call: GeminiTextCall | None = None
    cost_tracker: CostTracker | None = None

    def link(self, clusters: list[Cluster]) -> list[ClusterLink]:
        """
        Return judge-confirmed links between clusters in different projects.

        The heuristic pass is free; each surviving pair costs one Flash
        call, capped at ``config.cluster_link_max_pairs`` per cycle.
        """
        candidates = _candidate_pairs(clusters)
        cap = self.config.cluster_link_max_pairs
        if len(candidates) > cap:
            logger.info(
                "Cross-agent linker: %d candidate pair(s) over the %d-pair cap; dropping %d",
                len(candidates),
                cap,
                len(candidates) - cap,
            )
            candidates = candidates[:cap]

        links: list[ClusterLink] = []
        for first, second in candidates:
            verdict = self._judge(first, second)
            if verdict is None:
                continue
            if verdict.linked and verdict.confidence >= self.config.cluster_link_threshold:
                links.append(
                    ClusterLink(
                        cluster_id_a=first.cluster_id,
                        cluster_id_b=second.cluster_id,
                        confidence=verdict.confidence,
                        rationale=verdict.rationale,
                    )
                )
        return links

    def _judge(self, first: Cluster, second: Cluster) -> _LinkVerdict | None:
        prompt = _build_link_prompt(first, second)
        gemini = self.gemini_call or self._default_gemini_call
        raw = gemini(prompt)
        try:
            return _LinkVerdict.model_validate_json(strip_code_fence(raw))
        except ValidationError:
            logger.warning(
                "Link verdict failed validation for %s vs %s; treating as not linked",
                first.cluster_id,
                second.cluster_id,
            )
            return None

    def _default_gemini_call(self, prompt: str) -> str:
        from nengok.utils.genai_client import build_genai_client

        client = build_genai_client(self.config, role="Cross-Agent Linker")
        from google.genai import types

        return call_gemini(
            client,
            model=self.config.judge_model,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_LinkVerdict,
            ),
            env_var_hint="NENGOK_JUDGE_MODEL",
            role_hint="Cross-Agent Linker",
            retry_policy=RetryPolicy.from_config(self.config),
            cost_tracker=self.cost_tracker,
        )


def _candidate_pairs(clusters: list[Cluster]) -> list[tuple[Cluster, Cluster]]:
    """
    Score every cross-project pair by cheap heuristics, best first.

    A pair qualifies when it shares an implicated tool, overlaps on
    anomaly signals, or overlaps on name tokens. Pairs hitting more
    heuristics sort earlier so the per-cycle cap drops the weakest.
    """
    scored: list[tuple[int, tuple[Cluster, Cluster]]] = []
    for i, first in enumerate(clusters):
        for second in clusters[i + 1 :]:
            if not first.project or not second.project or first.project == second.project:
                continue
            score = _pair_score(first, second)
            if score > 0:
                scored.append((score, (first, second)))
    scored.sort(key=lambda item: -item[0])
    return [pair for _score, pair in scored]


def _pair_score(first: Cluster, second: Cluster) -> int:
    score = 0
    if _implicated_tools(first) & _implicated_tools(second):
        score += 1
    if set(first.signals) & set(second.signals):
        score += 1
    if _name_tokens(first.name) & _name_tokens(second.name):
        score += 1
    return score


def _implicated_tools(cluster: Cluster) -> set[str]:
    if cluster.hypothesis is None:
        return set()
    return set(cluster.hypothesis.implicated_tools)


def _name_tokens(name: str) -> set[str]:
    return {token for token in name.split("-") if token}


def _cluster_block(cluster: Cluster) -> dict[str, object]:
    return {
        "project": cluster.project,
        "name": cluster.name,
        "description": cluster.description,
        "hypothesis_summary": cluster.hypothesis.summary if cluster.hypothesis else "(none)",
        "implicated_tools": sorted(_implicated_tools(cluster)),
        "signals": cluster.signals,
    }


def _build_link_prompt(first: Cluster, second: Cluster) -> str:
    schema_hint = json.dumps(_LinkVerdict.model_json_schema(), indent=2)
    return (
        "Two monitored LLM agents each produced a failure cluster. Decide "
        "whether both clusters trace back to the same upstream cause (a "
        "shared tool, a schema change in a common API, a shared dependency).\n\n"
        f"Cluster A:\n{json.dumps(_cluster_block(first), indent=2)}\n\n"
        f"Cluster B:\n{json.dumps(_cluster_block(second), indent=2)}\n\n"
        "Similar symptoms alone do not make a link; name the shared upstream "
        "in `rationale` when you confirm one. Report confidence between 0 and 1.\n\n"
        f"Return ONLY a JSON object matching this schema:\n{schema_hint}\n"
    )
