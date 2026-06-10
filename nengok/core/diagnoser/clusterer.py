"""
Group anomalous spans into named failure clusters.

The hackathon scope uses Gemini-only clustering: the model receives all
anomalous traces and returns a JSON list of clusters. HDBSCAN as a
coarse first pass is documented as a stretch goal in the proposal.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from nengok.config import NengokConfig
from nengok.core.cost import CostTracker
from nengok.core.diagnoser._text import strip_code_fence, trim
from nengok.core.observer.redactor import Redactor
from nengok.core.types import AnomalousSpan, Cluster, ClusterStatus
from nengok.utils.gemini import RetryPolicy, call_gemini
from nengok.utils.logging import get_logger

logger = get_logger(__name__)

MAX_CLUSTER_NAME_LENGTH = 40
_NAME_INVALID_CHARS = re.compile(r"[^a-z0-9-]+")
_NAME_DASH_RUN = re.compile(r"-+")

GeminiTextCall = Callable[[str], str]


def _normalize_name(raw: str) -> str:
    """
    Coerce a Gemini-suggested cluster name into a stable lookup key.

    Output is lowercase kebab, max 40 characters, no whitespace and no
    runs of more than one dash. Falls back to ``unnamed-cluster`` when
    the input collapses to an empty string.
    """
    lowered = raw.strip().lower()
    kebabbed = _NAME_INVALID_CHARS.sub("-", lowered)
    collapsed = _NAME_DASH_RUN.sub("-", kebabbed).strip("-")
    if not collapsed:
        return "unnamed-cluster"
    return collapsed[:MAX_CLUSTER_NAME_LENGTH].rstrip("-")


class _NamedGroup(BaseModel):
    name: str
    description: str
    member_span_ids: list[str]


class _GeminiClustererResponse(BaseModel):
    clusters: list[_NamedGroup]


@dataclass
class _RawGroup:
    name: str
    description: str
    members: list[AnomalousSpan]


@dataclass
class Clusterer:
    config: NengokConfig
    gemini_call: GeminiTextCall | None = None
    cost_tracker: CostTracker | None = None
    redactor: Redactor | None = None
    feedback: list[dict] = field(default_factory=list)
    advice_amendment: str | None = None

    def cluster(self, anomalies: list[AnomalousSpan]) -> list[Cluster]:
        """Return one Cluster per detected failure mode."""
        if not anomalies:
            return []

        groups = self._call_gemini_clusterer(anomalies)

        now = datetime.now(UTC)
        clusters: list[Cluster] = []
        for group in groups:
            members = [a.span.span_id for a in group.members]
            exemplars = _select_exemplars(group.members)
            signals = sorted({s.value for member in group.members for s in member.signals})
            clusters.append(
                Cluster(
                    cluster_id=str(uuid.uuid4()),
                    name=_normalize_name(group.name),
                    description=group.description,
                    status=ClusterStatus.OPEN,
                    member_span_ids=members,
                    exemplar_span_ids=exemplars,
                    hypothesis=None,
                    created_at=now,
                    updated_at=now,
                    signals=signals,
                )
            )
        return clusters

    def _call_gemini_clusterer(self, anomalies: list[AnomalousSpan]) -> list[_RawGroup]:
        """
        Ask Gemini to group anomalous spans into named failure clusters.

        The prompt includes each span's id, operation name, trimmed
        input/output, attributes, and anomaly signals. Production calls
        pass ``response_schema=_GeminiClustererResponse`` so the API
        enforces JSON shape; Pydantic still validates to catch drift and
        the call retries once with a stricter reminder on failure. Span
        ids the model omits from every group are silently dropped.
        """
        redactor = self.redactor or Redactor.from_config(self.config)
        prompt = _build_clusterer_prompt(
            anomalies,
            self.config.cluster_trace_char_budget,
            redactor=redactor,
            feedback=self.feedback,
            advice_amendment=self.advice_amendment,
        )
        gemini = self.gemini_call or self._default_gemini_call
        raw = gemini(prompt)
        try:
            response = _GeminiClustererResponse.model_validate_json(strip_code_fence(raw))
        except ValidationError:
            logger.warning("Clusterer response failed validation; retrying once")
            retry_prompt = (
                prompt + "\n\nReturn ONLY valid JSON matching the schema. "
                "No prose, no markdown, no code fence."
            )
            retry = gemini(retry_prompt)
            response = _GeminiClustererResponse.model_validate_json(strip_code_fence(retry))

        by_span_id = {a.span.span_id: a for a in anomalies}
        groups: list[_RawGroup] = []
        for ng in response.clusters:
            members = [by_span_id[sid] for sid in ng.member_span_ids if sid in by_span_id]
            if not members:
                logger.debug("Gemini cluster %r resolved to zero local members; skipping", ng.name)
                continue
            groups.append(_RawGroup(name=ng.name, description=ng.description, members=members))
        return groups

    def _default_gemini_call(self, prompt: str) -> str:
        from nengok.utils.genai_client import build_genai_client

        client = build_genai_client(self.config, role="Clusterer")
        from google.genai import types

        return call_gemini(
            client,
            model=self.config.diagnoser_model,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_GeminiClustererResponse,
            ),
            env_var_hint="NENGOK_DIAGNOSER_MODEL",
            role_hint="Clusterer",
            retry_policy=RetryPolicy.from_config(self.config),
            cost_tracker=self.cost_tracker,
        )


MAX_EXEMPLARS = 5


def _select_exemplars(members: list[AnomalousSpan], limit: int = MAX_EXEMPLARS) -> list[str]:
    """
    Pick exemplar span ids spread across distinct signal sets and operations.

    Round-robins over each (signal set, operation name) profile in
    first-seen order so the hypothesizer sees the cluster's variety
    rather than its head.
    """
    buckets: dict[tuple[tuple[str, ...], str], list[str]] = {}
    for anomaly in members:
        key = (tuple(sorted(s.value for s in anomaly.signals)), anomaly.span.name)
        buckets.setdefault(key, []).append(anomaly.span.span_id)

    exemplars: list[str] = []
    queues = list(buckets.values())
    while queues and len(exemplars) < limit:
        for queue in list(queues):
            if len(exemplars) >= limit:
                break
            exemplars.append(queue.pop(0))
            if not queue:
                queues.remove(queue)
    return exemplars


_FEEDBACK_INSTRUCTIONS: dict[str, str] = {
    "mixed_root_causes": (
        "A reviewer flagged cluster '{name}' as mixing different root causes; "
        "split groups like it instead of lumping symptoms together."
    ),
    "duplicate_cluster": (
        "A reviewer flagged cluster '{name}' as a duplicate; reuse established "
        "failure-mode names rather than inventing near-identical ones."
    ),
    "not_a_failure": (
        "A reviewer said spans grouped under '{name}' are not failures; "
        "leave healthy spans out of every cluster."
    ),
    "merge_wrong": (
        "A machine merge into '{name}' was wrong; only group spans that share " "one root cause."
    ),
    "fix_rejected": "A reviewer rejected the proposed fix for cluster '{name}'.",
    "cluster_dismissed": "A reviewer dismissed cluster '{name}' without a fix.",
    "fix_approved": "The fix for cluster '{name}' was approved; that grouping was right.",
}


def _feedback_block(feedback: list[dict], redactor: Redactor) -> str:
    """
    Render reviewer corrections as short instructions, redacted.

    This is the bridge that closes the loop from `nengok_approvals`
    into the next cycle's clustering decisions.
    """
    lines: list[str] = []
    for row in feedback:
        template = _FEEDBACK_INSTRUCTIONS.get(str(row.get("kind")))
        if template is None:
            continue
        name = str(row.get("cluster_name") or row.get("cluster_id") or "unknown")
        instruction = template.format(name=name)
        detail = str(row.get("detail") or "").strip()
        if detail:
            instruction += f" Reviewer note: {detail}"
        lines.append("- " + redactor.redact(instruction))
    if not lines:
        return ""
    return "Past corrections from human reviewers:\n" + "\n".join(lines) + "\n\n"


def _build_clusterer_prompt(
    anomalies: list[AnomalousSpan],
    char_budget: int,
    *,
    redactor: Redactor,
    feedback: list[dict] | None = None,
    advice_amendment: str | None = None,
) -> str:
    rows: list[dict[str, Any]] = [
        {
            "span_id": a.span.span_id,
            "operation": a.span.name,
            "input": redactor.redact(trim(a.span.input_value, char_budget)),
            "output": redactor.redact(trim(a.span.output_value, char_budget)),
            "attributes": a.span.attributes,
            "signals": [s.value for s in a.signals],
        }
        for a in anomalies
    ]

    schema_hint = json.dumps(
        {
            "clusters": [
                {
                    "name": "kebab-case-name",
                    "description": "what these failures have in common",
                    "member_span_ids": ["..."],
                }
            ]
        },
        indent=2,
    )

    advice_block = ""
    if advice_amendment:
        advice_block = f"Operator-approved clustering guidance:\n{advice_amendment}\n\n"

    return (
        "You are clustering anomalous LLM agent traces by failure mode for a "
        "monitoring system.\n\n"
        "Group the spans below so each cluster contains traces that share the "
        "same likely root cause. Pick short, descriptive names. Every span "
        "must end up in exactly one cluster.\n\n"
        f"{advice_block}"
        f"{_feedback_block(feedback or [], redactor)}"
        f"Return ONLY a JSON object that matches this shape:\n{schema_hint}\n\n"
        f"Anomalous spans (JSON list):\n{json.dumps(rows, indent=2, default=str)}\n"
    )
