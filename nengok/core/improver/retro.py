"""
Clustering retro: Nengok reads its own outcomes and proposes a better
clustering prompt.

The metrics come from plain code over the state store; one
``config.diagnoser_model`` critique call turns the numbers plus the
worst examples into a proposed prompt amendment. Advice is proposed,
never auto-applied: a reviewer activates it from the dashboard, and
``_build_clusterer_prompt`` appends only the active amendment.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from nengok.config import NengokConfig
from nengok.core.cost import CostTracker
from nengok.core.diagnoser._text import strip_code_fence
from nengok.core.observer.redactor import Redactor
from nengok.state.store import StateStore
from nengok.utils.gemini import RetryPolicy, call_gemini
from nengok.utils.logging import get_logger

logger = get_logger(__name__)

GeminiTextCall = Callable[[str], str]

RETRO_WINDOW_DAYS = 30
MAX_PROMPT_AMENDMENT_CHARS = 1_200
MAX_WORST_EXAMPLES = 5

_NEGATIVE_FEEDBACK_KINDS = frozenset(
    {"duplicate_cluster", "mixed_root_causes", "not_a_failure", "merge_wrong", "fix_rejected"}
)


class ClusteringAdvice(BaseModel):
    observations: list[str]
    prompt_amendment: str
    expected_effect: str


class RetroResult(BaseModel):
    advice_id: str
    observations: list[str]
    prompt_amendment: str
    expected_effect: str
    metrics: dict[str, Any]
    report_path: str


@dataclass
class ClusteringRetro:
    config: NengokConfig
    store: StateStore
    gemini_call: GeminiTextCall | None = None
    cost_tracker: CostTracker | None = None
    redactor: Redactor | None = None

    def run(self, *, project: str | None = None) -> RetroResult:
        """
        One retro pass: gather, measure, critique, propose.

        Store reads finish before the Gemini call fires, so the
        transaction guard from `call_gemini` never trips.
        """
        since = datetime.now(UTC) - timedelta(days=RETRO_WINDOW_DAYS)
        clusters = self.store.list_clusters_between(since=since)
        feedback = self.store.list_cluster_feedback_between(since=since)
        cycles = self.store.list_cycles_between(since=since)
        links = self.store.list_cluster_links_between(since=since)

        metrics = compute_metrics(clusters=clusters, feedback=feedback, cycles=cycles, links=links)
        worst = self._worst_examples(clusters, feedback)
        advice = self._critique(metrics=metrics, worst_examples=worst)

        metrics_payload = json.dumps(
            {
                "metrics": metrics,
                "observations": advice.observations,
                "expected_effect": advice.expected_effect,
            }
        )
        advice_id = self.store.record_clustering_advice(
            project=project,
            prompt_amendment=advice.prompt_amendment,
            metrics_json=metrics_payload,
        )

        report_path = _write_retro_report(
            artifacts_dir=self.config.artifacts_dir,
            metrics=metrics,
            advice=advice,
            advice_id=advice_id,
            project=project,
        )
        logger.info("Retro proposed advice %s (report: %s)", advice_id, report_path)
        return RetroResult(
            advice_id=advice_id,
            observations=advice.observations,
            prompt_amendment=advice.prompt_amendment,
            expected_effect=advice.expected_effect,
            metrics=metrics,
            report_path=str(report_path),
        )

    def _worst_examples(self, clusters: list[dict], feedback: list[dict]) -> list[dict[str, str]]:
        redactor = self.redactor or Redactor.from_config(self.config)
        by_id = {row["cluster_id"]: row for row in clusters}
        examples: list[dict[str, str]] = []
        for row in feedback:
            if row.get("kind") not in _NEGATIVE_FEEDBACK_KINDS:
                continue
            cluster = by_id.get(row.get("cluster_id"), {})
            examples.append(
                {
                    "kind": str(row.get("kind")),
                    "cluster_name": redactor.redact(str(cluster.get("name") or row.get("cluster_id"))),
                    "cluster_description": redactor.redact(str(cluster.get("description") or "")),
                    "reviewer_note": redactor.redact(str(row.get("detail") or "")),
                }
            )
            if len(examples) >= MAX_WORST_EXAMPLES:
                break
        return examples

    def _critique(self, *, metrics: dict[str, Any], worst_examples: list[dict[str, str]]) -> ClusteringAdvice:
        prompt = _build_critique_prompt(metrics=metrics, worst_examples=worst_examples)
        gemini = self.gemini_call or self._default_gemini_call
        raw = gemini(prompt)
        try:
            advice = ClusteringAdvice.model_validate_json(strip_code_fence(raw))
        except ValidationError:
            logger.warning("Retro critique failed validation; retrying once")
            retry = gemini(
                prompt + "\n\nReturn ONLY valid JSON matching the schema. No prose, no code fence."
            )
            advice = ClusteringAdvice.model_validate_json(strip_code_fence(retry))
        if len(advice.prompt_amendment) > MAX_PROMPT_AMENDMENT_CHARS:
            advice = advice.model_copy(
                update={"prompt_amendment": advice.prompt_amendment[:MAX_PROMPT_AMENDMENT_CHARS]}
            )
        return advice

    def _default_gemini_call(self, prompt: str) -> str:
        from nengok.utils.genai_client import build_genai_client

        client = build_genai_client(self.config, role="Clustering Retro")
        from google.genai import types

        return call_gemini(
            client,
            model=self.config.diagnoser_model,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ClusteringAdvice,
            ),
            env_var_hint="NENGOK_DIAGNOSER_MODEL",
            role_hint="Clustering Retro",
            retry_policy=RetryPolicy.from_config(self.config),
            cost_tracker=self.cost_tracker,
        )


def score_amendment_against_golden(
    config: NengokConfig,
    amendment: str | None,
    *,
    gemini_call: GeminiTextCall | None = None,
    cost_tracker: CostTracker | None = None,
):
    """Run the clusterer over the labeled golden set with `amendment` applied."""
    from nengok.core.diagnoser.clusterer import Clusterer
    from nengok.core.evaluators.clustering_score import load_clustering_golden, score_clusters

    anomalies, expected = load_clustering_golden()
    clusterer = Clusterer(
        config=config,
        gemini_call=gemini_call,
        cost_tracker=cost_tracker,
        advice_amendment=amendment,
    )
    return score_clusters(clusterer.cluster(anomalies), expected)


def apply_golden_scores(
    *,
    store: StateStore,
    result: RetroResult,
    current: Any,
    proposed: Any,
) -> bool:
    """
    Record golden-set scores against the advice row and the retro report.

    Returns whether the proposed amendment is recommended. An amendment
    that scores worse than the incumbent stays recorded but carries the
    `not recommended` flag, so a reviewer sees the regression before
    activating it.
    """
    recommended = proposed.f1 >= current.f1
    payload = {
        "metrics": result.metrics,
        "observations": result.observations,
        "expected_effect": result.expected_effect,
        "golden": {
            "current_f1": current.f1,
            "proposed_f1": proposed.f1,
            "current_precision": current.precision,
            "proposed_precision": proposed.precision,
            "current_recall": current.recall,
            "proposed_recall": proposed.recall,
            "recommended": recommended,
        },
    }
    store.update_advice_metrics(advice_id=result.advice_id, metrics_json=json.dumps(payload))

    verdict = "recommended" if recommended else "not recommended"
    report = Path(result.report_path)
    lines = [
        "",
        "## Golden-set scores",
        "",
        f"- current prompt F1: {current.f1:.3f} "
        f"(precision {current.precision:.3f}, recall {current.recall:.3f})",
        f"- proposed amendment F1: {proposed.f1:.3f} "
        f"(precision {proposed.precision:.3f}, recall {proposed.recall:.3f})",
        f"- verdict: {verdict}",
        "",
    ]
    with report.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return recommended


def compute_metrics(
    *,
    clusters: list[dict],
    feedback: list[dict],
    cycles: list[dict],
    links: list[dict],
) -> dict[str, Any]:
    """Quality numbers computed without an LLM, over the retro window."""
    discovered = sum(int(c.get("clusters_discovered") or 0) for c in cycles)
    merged = sum(int(c.get("clusters_merged") or 0) for c in cycles)
    duplicate_rate = merged / discovered if discovered else 0.0

    kinds: dict[str, int] = {}
    for row in feedback:
        kind = str(row.get("kind"))
        kinds[kind] = kinds.get(kind, 0) + 1
    decided = sum(kinds.values())

    escalated = sum(1 for c in clusters if c.get("status") == "escalated")
    escalation_rate = escalated / len(clusters) if clusters else 0.0

    sizes = [
        len(json.loads(c.get("member_spans_json") or "[]")) for c in clusters if c.get("member_spans_json")
    ]
    median_size = statistics.median(sizes) if sizes else 0

    spends = [int(c.get("gemini_tokens") or 0) for c in cycles]
    tokens_per_cycle = statistics.mean(spends) if spends else 0.0

    return {
        "window_days": RETRO_WINDOW_DAYS,
        "clusters_in_window": len(clusters),
        "cycles_in_window": len(cycles),
        "duplicate_cluster_rate": round(duplicate_rate, 4),
        "rejection_counts_by_kind": kinds,
        "decided_feedback_count": decided,
        "escalation_rate": round(escalation_rate, 4),
        "median_cluster_size": median_size,
        "gemini_tokens_per_cycle": round(tokens_per_cycle, 1),
        "cross_agent_links": len(links),
    }


def _build_critique_prompt(*, metrics: dict[str, Any], worst_examples: list[dict[str, str]]) -> str:
    schema_hint = json.dumps(ClusteringAdvice.model_json_schema(), indent=2)
    return (
        "You are reviewing the clustering quality of an LLM failure-monitoring "
        "system. The clusterer groups anomalous agent traces by root cause; "
        "reviewers then approve, reject, or correct its output.\n\n"
        f"Quality metrics over the last {metrics.get('window_days')} days:\n"
        f"{json.dumps(metrics, indent=2)}\n\n"
        f"Worst reviewer-flagged examples (redacted):\n"
        f"{json.dumps(worst_examples, indent=2)}\n\n"
        "Propose ONE short amendment to append to the clustering prompt that "
        "would reduce the failure patterns above. Keep `prompt_amendment` "
        f"under {MAX_PROMPT_AMENDMENT_CHARS} characters; it must read as "
        "direct instructions to the clustering model. Summarize what you saw "
        "in `observations` and the change you expect in `expected_effect`.\n\n"
        f"Return ONLY a JSON object matching this schema:\n{schema_hint}\n"
    )


def _write_retro_report(
    *,
    artifacts_dir: Path,
    metrics: dict[str, Any],
    advice: ClusteringAdvice,
    advice_id: str,
    project: str | None,
) -> Path:
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    target_dir = artifacts_dir / "improvement" / stamp
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / "retro.md"

    observation_lines = "\n".join(f"- {item}" for item in advice.observations) or "- (none)"
    lines = [
        "# Clustering retro",
        "",
        f"- advice_id: `{advice_id}`",
        f"- project: `{project or 'all'}`",
        "- status: proposed (a reviewer must activate it)",
        "",
        "## Metrics",
        "",
        "```json",
        json.dumps(metrics, indent=2),
        "```",
        "",
        "## Observations",
        "",
        observation_lines,
        "",
        "## Proposed prompt amendment",
        "",
        "```",
        advice.prompt_amendment,
        "```",
        "",
        "## Expected effect",
        "",
        advice.expected_effect,
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
