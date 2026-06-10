"""
Pairwise clustering quality scores against the labeled golden set.

Precision, recall, and F1 over span pairs, implemented in plain Python
so the metric stays dependency-free. A pair counts as predicted-linked
when both spans land in the same predicted cluster, and as truly
linked when they share an `expected_cluster` label.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from itertools import combinations
from pathlib import Path

from pydantic import BaseModel

from nengok.core.types import AnomalousSpan, AnomalySignal, Cluster, TraceSpan

CLUSTERING_GOLDEN_PATH = Path(__file__).resolve().parents[3] / "golden_dataset" / "clustering_golden.json"


class ClusteringScore(BaseModel):
    precision: float
    recall: float
    f1: float
    span_count: int


def pairwise_scores(predicted: Mapping[str, str], expected: Mapping[str, str]) -> ClusteringScore:
    """
    Score predicted span groupings against expected labels.

    Only spans present in both mappings participate, so a clusterer
    that drops spans loses recall through the missing pairs rather
    than crashing the scorer.
    """
    spans = sorted(set(predicted) & set(expected))
    predicted_pairs = {(a, b) for a, b in combinations(spans, 2) if predicted[a] == predicted[b]}
    expected_pairs = {(a, b) for a, b in combinations(sorted(expected), 2) if expected[a] == expected[b]}

    true_positives = len(predicted_pairs & expected_pairs)
    precision = true_positives / len(predicted_pairs) if predicted_pairs else 0.0
    recall = true_positives / len(expected_pairs) if expected_pairs else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return ClusteringScore(
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        span_count=len(spans),
    )


def score_clusters(clusters: list[Cluster], expected: Mapping[str, str]) -> ClusteringScore:
    """Score real `Cluster` output by flattening it into a span-to-name mapping."""
    predicted: dict[str, str] = {}
    for cluster in clusters:
        for span_id in cluster.member_span_ids:
            predicted[span_id] = cluster.name
    return pairwise_scores(predicted, expected)


def load_clustering_golden(
    path: Path = CLUSTERING_GOLDEN_PATH,
) -> tuple[list[AnomalousSpan], dict[str, str]]:
    """Return the golden spans as `AnomalousSpan`s plus the expected labels."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    anomalies: list[AnomalousSpan] = []
    expected: dict[str, str] = {}
    for row in payload["spans"]:
        anomalies.append(
            AnomalousSpan(
                span=TraceSpan(
                    span_id=row["span_id"],
                    trace_id=f"golden-{row['span_id']}",
                    name=row["operation"],
                    input_value=row["input"],
                    output_value=row["output"],
                ),
                signals=[AnomalySignal(signal) for signal in row["signals"]],
            )
        )
        expected[row["span_id"]] = row["expected_cluster"]
    return anomalies, expected
