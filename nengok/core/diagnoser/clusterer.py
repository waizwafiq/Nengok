"""
Group anomalous spans into named failure clusters.

The hackathon scope uses Gemini-only clustering — the model receives
all anomalous traces and returns a JSON list of clusters. HDBSCAN as a
coarse first pass is documented as a stretch goal in the proposal.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from nengok.config import NengokConfig
from nengok.core.types import AnomalousSpan, Cluster, ClusterStatus
from nengok.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Clusterer:
    config: NengokConfig

    def cluster(self, anomalies: list[AnomalousSpan]) -> list[Cluster]:
        """Return one Cluster per detected failure mode."""
        if not anomalies:
            return []

        groups = self._call_gemini_clusterer(anomalies)

        now = datetime.now(timezone.utc)
        clusters: list[Cluster] = []
        for group in groups:
            members = [a.span.span_id for a in group.members]
            exemplars = members[: min(5, len(members))]
            clusters.append(
                Cluster(
                    cluster_id=str(uuid.uuid4()),
                    name=group.name,
                    description=group.description,
                    status=ClusterStatus.OPEN,
                    member_span_ids=members,
                    exemplar_span_ids=exemplars,
                    hypothesis=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        return clusters

    def _call_gemini_clusterer(self, anomalies: list[AnomalousSpan]) -> list[_RawGroup]:
        """
        Placeholder Gemini call.

        In the implementation pass this prompts `gemini-3.1-pro-preview`
        with the anomalous traces and parses a JSON response. Until that
        is wired up, we degrade to a single all-up cluster so the rest
        of the pipeline can be exercised end-to-end.
        """
        logger.debug("Falling back to single-cluster grouping (Gemini call not yet wired)")
        return [
            _RawGroup(
                name="unclassified-failures",
                description="All anomalous spans, pending Gemini cluster naming.",
                members=anomalies,
            )
        ]


@dataclass
class _RawGroup:
    name: str
    description: str
    members: list[AnomalousSpan]
