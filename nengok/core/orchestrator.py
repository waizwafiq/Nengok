"""
The top-level loop: Observer -> Diagnoser -> Fixer -> Verifier.

Each stage is a small object with a single public method. The
orchestrator wires them together and is the only place that knows
how a full cycle composes. That makes the loop easy to unit-test by
swapping any stage for a fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from nengok.config import NengokConfig
from nengok.core.diagnoser.clusterer import Clusterer
from nengok.core.diagnoser.hypothesizer import Hypothesizer
from nengok.core.fixer.experiment_runner import ExperimentRunner
from nengok.core.fixer.prompt_proposer import PromptProposer
from nengok.core.fixer.test_generator import TestGenerator
from nengok.core.observer.anomaly_filter import AnomalyFilter
from nengok.core.observer.sampler import SpanSampler
from nengok.core.types import (
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

logger = get_logger(__name__)


@dataclass
class Orchestrator:
    config: NengokConfig

    def __post_init__(self) -> None:
        self._phoenix = PhoenixWrapper(self.config)
        self._state = StateStore(self.config.state_db_path)

        self._sampler = SpanSampler(self._phoenix, self.config)
        self._anomaly_filter = AnomalyFilter()
        self._clusterer = Clusterer(self.config)
        self._hypothesizer = Hypothesizer(self.config, phoenix=self._phoenix)

        self._test_generator = TestGenerator(self.config)
        self._prompt_proposer = PromptProposer(self.config)
        self._experiment_runner = ExperimentRunner(self._phoenix, self.config)

        self._gate = VerifierGate(self.config)
        self._artifact_writer = ArtifactWriter(self.config.artifacts_dir)

    def run_once(self, *, dry_run: bool = False) -> CycleResult:
        """One full Observer -> Diagnoser -> Fixer -> Verifier pass."""
        started_at = datetime.now(UTC)
        logger.info("Cycle start (project=%s, dry_run=%s)", self.config.project_identifier, dry_run)

        spans = self._sampler.sample()
        anomalies = self._anomaly_filter.filter(spans)
        new_anomalies = self._state.deduplicate(anomalies)
        logger.info(
            "Observer: %d spans -> %d anomalies -> %d new after dedup",
            len(spans),
            len(anomalies),
            len(new_anomalies),
        )

        if not new_anomalies:
            return CycleResult(clusters_detected=0, fixes_proposed=0, escalations=0)

        raw_clusters = self._clusterer.cluster(new_anomalies)
        clusters: list[Cluster] = []
        for raw in raw_clusters:
            hypothesis = self._hypothesizer.hypothesize(raw)
            clusters.append(
                raw.model_copy(update={"hypothesis": hypothesis, "status": ClusterStatus.DIAGNOSED})
            )
            self._state.upsert_cluster(clusters[-1])

        logger.info("Diagnoser: %d clusters with hypotheses", len(clusters))

        artifacts: list[FixArtifact] = []
        escalations = 0

        for cluster in clusters:
            assert cluster.hypothesis is not None

            cases = self._test_generator.generate(cluster)
            proposal = self._prompt_proposer.propose(cluster)

            if dry_run:
                logger.info("Dry run: skipping experiment for cluster '%s'", cluster.name)
                continue

            result = self._experiment_runner.run(cluster=cluster, cases=cases, proposal=proposal)
            verification = self._gate.evaluate(result)

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
        logger.info("Cycle complete in %.1fs", (finished_at - started_at).total_seconds())

        return CycleResult(
            clusters_detected=len(clusters),
            fixes_proposed=len(artifacts),
            escalations=escalations,
            artifacts=artifacts,
        )
