"""
Live clustering-quality gate: run the real Gemini clusterer against the
labeled golden set and require pairwise F1 at or above the configured
floor. Slow and quota-consuming, so it stays behind the harness skip
guard and the `slow` marker like every other live test here.
"""

from __future__ import annotations

import pytest

from nengok.config import NengokConfig
from nengok.core.diagnoser.clusterer import Clusterer
from nengok.core.evaluators.clustering_score import load_clustering_golden, score_clusters


@pytest.mark.slow
def test_gemini_clusterer_meets_the_quality_floor(phoenix_config: NengokConfig) -> None:
    anomalies, expected = load_clustering_golden()

    clusters = Clusterer(config=phoenix_config).cluster(anomalies)
    score = score_clusters(clusters, expected)

    assert score.span_count > 0, "clusterer dropped every golden span"
    assert score.f1 >= phoenix_config.clustering_quality_floor, (
        f"Golden-set pairwise F1 {score.f1:.3f} fell below the "
        f"clustering_quality_floor of {phoenix_config.clustering_quality_floor:.2f} "
        f"(precision={score.precision:.3f}, recall={score.recall:.3f})."
    )
