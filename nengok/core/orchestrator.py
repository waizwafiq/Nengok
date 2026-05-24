"""
The top-level loop: Observer -> Diagnoser -> Fixer -> Verifier.

Each stage is a small object with a single public method. The
orchestrator wires them together and is the only place that knows
how a full cycle composes. That makes the loop easy to unit-test by
swapping any stage for a fake.

Every cycle is also traced into the ``nengok-meta-agent`` Phoenix
project via ``nengok.utils.tracing`` so a developer can replay the
loop's own decisions span by span. Section 5.4 of the proposal asks
for this self-observability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from nengok.config import NengokConfig
from nengok.core.diagnoser.clusterer import Clusterer
from nengok.core.diagnoser.hypothesizer import Hypothesizer
from nengok.core.fixer.experiment_runner import ExperimentRunner
from nengok.core.fixer.prompt_proposer import PromptProposer
from nengok.core.fixer.test_generator import TestGenerator
from nengok.core.observer.anomaly_filter import AnomalyFilter
from nengok.core.observer.sampler import SpanSampler
from nengok.core.types import (
    AnomalousSpan,
    Cluster,
    ClusterStatus,
    CycleResult,
    FixArtifact,
    VerificationOutcome,
)
from nengok.core.verifier.artifact_writer import ArtifactWriter
from nengok.core.verifier.gate import VerifierGate
from nengok.phoenix.client import PhoenixWrapper
from nengok.state.store import StateStore
from nengok.utils.logging import get_logger
from nengok.utils.tracing import get_tracer, register_meta_tracer, set_attributes

logger = get_logger(__name__)


@dataclass
class Orchestrator:
    config: NengokConfig

    _traced: ClassVar[bool] = False

    def __post_init__(self) -> None:
        self._phoenix = PhoenixWrapper(self.config)
        self._state = StateStore(self.config.state_db_path)

        self._sampler = SpanSampler(self._phoenix, self.config)
        self._anomaly_filter = AnomalyFilter()
        self._clusterer = Clusterer(self.config)
        self._hypothesizer = Hypothesizer(self.config, phoenix=self._phoenix)

        self._test_generator = TestGenerator(self.config)
        self._prompt_proposer = PromptProposer(self.config, phoenix=self._phoenix)
        self._experiment_runner = ExperimentRunner(self._phoenix, self.config)

        self._gate = VerifierGate(self.config)
        self._artifact_writer = ArtifactWriter(self.config.artifacts_dir)

    def run_once(self, *, dry_run: bool = False) -> CycleResult:
        """One full Observer -> Diagnoser -> Fixer -> Verifier pass."""
        self._ensure_traced()
        tracer = get_tracer()

        started_at = datetime.now(UTC)
        logger.info("Cycle start (project=%s, dry_run=%s)", self.config.project_identifier, dry_run)

        with tracer.start_as_current_span("nengok.cycle") as cycle_span:
            set_attributes(
                cycle_span,
                {
                    "nengok.project": self.config.project_identifier,
                    "nengok.dry_run": dry_run,
                },
            )

            with tracer.start_as_current_span("observer") as observer_span:
                spans = self._sampler.sample()
                anomalies = self._anomaly_filter.filter(spans)
                new_anomalies = self._state.deduplicate(anomalies)
                set_attributes(
                    observer_span,
                    {
                        "nengok.observer.span_count": len(spans),
                        "nengok.observer.anomaly_count": len(anomalies),
                        "nengok.observer.new_anomaly_count": len(new_anomalies),
                    },
                )
                logger.info(
                    "Observer: %d spans -> %d anomalies -> %d new after dedup",
                    len(spans),
                    len(anomalies),
                    len(new_anomalies),
                )

            if not new_anomalies:
                return CycleResult(clusters_detected=0, fixes_proposed=0, escalations=0)

            with tracer.start_as_current_span("diagnoser") as diagnoser_span:
                raw_clusters = self._clusterer.cluster(new_anomalies)
                clusters: list[Cluster] = []
                for raw in raw_clusters:
                    hypothesis = self._hypothesizer.hypothesize(raw)
                    clusters.append(
                        raw.model_copy(update={"hypothesis": hypothesis, "status": ClusterStatus.DIAGNOSED})
                    )
                    self._state.upsert_cluster(clusters[-1])
                set_attributes(diagnoser_span, {"nengok.diagnoser.cluster_count": len(clusters)})
                logger.info("Diagnoser: %d clusters with hypotheses", len(clusters))

            signal_counts = _signal_counts_by_cluster(clusters, new_anomalies)

            artifacts: list[FixArtifact] = []
            escalations = 0

            for cluster in clusters:
                assert cluster.hypothesis is not None

                cluster_attrs = _cluster_span_attrs(cluster, signal_counts)

                with tracer.start_as_current_span("fixer") as fixer_span:
                    set_attributes(fixer_span, cluster_attrs)
                    cases = self._test_generator.generate(cluster)
                    proposal = self._prompt_proposer.propose(cluster)
                    set_attributes(fixer_span, {"nengok.fixer.case_count": len(cases)})

                    if dry_run:
                        logger.info("Dry run: skipping experiment for cluster '%s'", cluster.name)
                        continue

                    result = self._experiment_runner.run(cluster=cluster, cases=cases, proposal=proposal)

                with tracer.start_as_current_span("verifier") as verifier_span:
                    set_attributes(verifier_span, cluster_attrs)
                    verification = self._gate.evaluate(result)
                    set_attributes(
                        verifier_span,
                        {"nengok.verifier.outcome": verification.outcome.value},
                    )

                    if verification.outcome is VerificationOutcome.PASSED:
                        artifact = self._artifact_writer.write(
                            cluster=cluster,
                            cases=cases,
                            proposal=proposal,
                            verification=verification,
                        )
                        artifacts.append(artifact)
                        self._state.mark_status(cluster.cluster_id, ClusterStatus.FIX_PROPOSED)
                    else:
                        escalations += 1
                        self._state.mark_status(cluster.cluster_id, ClusterStatus.ESCALATED)
                        logger.warning(
                            "Cluster '%s' escalated: %s",
                            cluster.name,
                            verification.outcome.value,
                        )

            finished_at = datetime.now(UTC)
            set_attributes(
                cycle_span,
                {
                    "nengok.cycle.clusters_detected": len(clusters),
                    "nengok.cycle.fixes_proposed": len(artifacts),
                    "nengok.cycle.escalations": escalations,
                    "nengok.cycle.duration_s": (finished_at - started_at).total_seconds(),
                },
            )
            logger.info("Cycle complete in %.1fs", (finished_at - started_at).total_seconds())

            return CycleResult(
                clusters_detected=len(clusters),
                fixes_proposed=len(artifacts),
                escalations=escalations,
                artifacts=artifacts,
            )

    def _ensure_traced(self) -> None:
        """Register the meta-tracer once per process."""
        if Orchestrator._traced:
            return
        register_meta_tracer()
        Orchestrator._traced = True


def _signal_counts_by_cluster(
    clusters: list[Cluster], anomalies: list[AnomalousSpan]
) -> dict[str, dict[str, int]]:
    """
    Return, per cluster id, how many member spans carry each anomaly signal.

    The cluster's ``member_span_ids`` reference the span ids inside
    ``anomalies``; we walk that join once so each fixer/verifier span
    can be tagged without recomputing.
    """
    by_span_id = {a.span.span_id: a.signals for a in anomalies}
    out: dict[str, dict[str, int]] = {}
    for cluster in clusters:
        counts: dict[str, int] = {}
        for span_id in cluster.member_span_ids:
            for signal in by_span_id.get(span_id, []):
                counts[signal.value] = counts.get(signal.value, 0) + 1
        out[cluster.cluster_id] = counts
    return out


def _cluster_span_attrs(cluster: Cluster, signal_counts: dict[str, dict[str, int]]) -> dict[str, object]:
    attrs: dict[str, object] = {
        "nengok.cluster.id": cluster.cluster_id,
        "nengok.cluster.name": cluster.name,
        "nengok.cluster.member_count": len(cluster.member_span_ids),
    }
    for signal_name, count in signal_counts.get(cluster.cluster_id, {}).items():
        attrs[f"nengok.cluster.signal.{signal_name}"] = count
    return attrs
