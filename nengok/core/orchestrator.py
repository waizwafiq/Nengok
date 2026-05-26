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

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from nengok.config import NengokConfig
from nengok.core.cost import CostTracker
from nengok.core.diagnoser.clusterer import Clusterer
from nengok.core.diagnoser.hypothesizer import Hypothesizer
from nengok.core.fixer.experiment_runner import ExperimentRunner
from nengok.core.fixer.prompt_proposer import PromptProposer
from nengok.core.fixer.test_generator import TestGenerator
from nengok.core.incidents import write_incident
from nengok.core.observer.anomaly_filter import AnomalyFilter
from nengok.core.observer.redactor import Redactor
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
from nengok.errors import PhoenixTimeoutError
from nengok.phoenix.client import PhoenixWrapper
from nengok.state.store import StateStore
from nengok.utils.logging import get_logger, run_context
from nengok.utils.tracing import get_tracer, register_meta_tracer, set_attributes

logger = get_logger(__name__)


@dataclass
class Orchestrator:
    config: NengokConfig

    _traced: ClassVar[bool] = False
    current_stage: str | None = None

    def __post_init__(self) -> None:
        self._phoenix = PhoenixWrapper(self.config)
        self._state = StateStore(self.config.state_db_path)

        self._redactor = Redactor.from_config(self.config)

        self._sampler = SpanSampler(self._phoenix, self.config)
        self._anomaly_filter = AnomalyFilter()
        self._clusterer = Clusterer(self.config, redactor=self._redactor)
        self._hypothesizer = Hypothesizer(self.config, phoenix=self._phoenix, redactor=self._redactor)

        self._test_generator = TestGenerator(self.config)
        self._prompt_proposer = PromptProposer(self.config, phoenix=self._phoenix, redactor=self._redactor)
        self._experiment_runner = ExperimentRunner(self._phoenix, self.config)

        self._gate = VerifierGate(self.config)
        self._artifact_writer = ArtifactWriter(self.config.artifacts_dir, redactor=self._redactor)

    def run_once(self, *, dry_run: bool = False) -> CycleResult:
        """One full Observer -> Diagnoser -> Fixer -> Verifier pass."""
        self._ensure_traced()
        tracer = get_tracer()

        run_id = uuid.uuid4().hex[:12]
        started_at = datetime.now(UTC)

        cost_tracker = self._fresh_cost_tracker()
        self._attach_cost_tracker(cost_tracker)

        with (
            run_context(run_id=run_id),
            tracer.start_as_current_span("nengok.cycle") as cycle_span,
        ):
            logger.info(
                "Cycle start (project=%s, dry_run=%s)",
                self.config.project_identifier,
                dry_run,
            )
            set_attributes(
                cycle_span,
                {
                    "nengok.project": self.config.project_identifier,
                    "nengok.dry_run": dry_run,
                },
            )

            with (
                run_context(stage="observer"),
                tracer.start_as_current_span("observer") as observer_span,
            ):
                self.current_stage = "observer"
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
                self._state.record_cycle_usage(
                    cycle_id=run_id,
                    started_at=started_at,
                    ended_at=datetime.now(UTC),
                    gemini_tokens=cost_tracker.tokens_used,
                    gemini_dollars=cost_tracker.dollars_used,
                )
                return CycleResult(clusters_detected=0, fixes_proposed=0, escalations=0)

            baseline_prompt = self._prompt_proposer.load_baseline_prompt()

            with (
                run_context(stage="diagnoser"),
                tracer.start_as_current_span("diagnoser") as diagnoser_span,
            ):
                self.current_stage = "diagnoser"
                raw_clusters = self._clusterer.cluster(new_anomalies)
                clusters: list[Cluster] = []
                for raw in raw_clusters:
                    hypothesis = self._hypothesizer.hypothesize(raw, current_prompt=baseline_prompt)
                    clusters.append(
                        raw.model_copy(update={"hypothesis": hypothesis, "status": ClusterStatus.DIAGNOSED})
                    )
                    self._state.upsert_cluster(
                        clusters[-1],
                        first_seen=_earliest_span_time(clusters[-1], new_anomalies),
                    )
                set_attributes(diagnoser_span, {"nengok.diagnoser.cluster_count": len(clusters)})
                logger.info("Diagnoser: %d clusters with hypotheses", len(clusters))

            signal_counts = _signal_counts_by_cluster(clusters, new_anomalies)

            artifacts: list[FixArtifact] = []
            escalations = 0
            over_budget = False

            for index, cluster in enumerate(clusters):
                assert cluster.hypothesis is not None

                if self._is_over_budget(cost_tracker):
                    over_budget = True
                    skipped = [c.cluster_id for c in clusters[index:]]
                    self._record_over_budget(
                        cost_tracker=cost_tracker,
                        skipped_cluster_ids=skipped,
                    )
                    break

                cluster_attrs = _cluster_span_attrs(cluster, signal_counts)

                try:
                    with (
                        run_context(stage="fixer", cluster_id=cluster.cluster_id),
                        tracer.start_as_current_span("fixer") as fixer_span,
                    ):
                        self.current_stage = "fixer"
                        set_attributes(fixer_span, cluster_attrs)
                        cases = self._test_generator.generate(cluster)
                        proposal = self._prompt_proposer.propose(cluster, baseline_prompt=baseline_prompt)
                        set_attributes(fixer_span, {"nengok.fixer.case_count": len(cases)})

                        if dry_run:
                            logger.info("Dry run: skipping experiment for cluster '%s'", cluster.name)
                            continue

                        result = self._experiment_runner.run(cluster=cluster, cases=cases, proposal=proposal)
                        self._state.record_experiment(cluster_id=cluster.cluster_id, result=result)

                    with (
                        run_context(stage="verifier", cluster_id=cluster.cluster_id),
                        tracer.start_as_current_span("verifier") as verifier_span,
                    ):
                        self.current_stage = "verifier"
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
                except PhoenixTimeoutError as exc:
                    escalations += 1
                    self._state.mark_status(cluster.cluster_id, ClusterStatus.ESCALATED)
                    self._record_phoenix_timeout(cluster=cluster, exc=exc)
                    logger.warning(
                        "Cluster '%s' escalated: phoenix_timeout (%s, %.1fs)",
                        cluster.name,
                        exc.method,
                        exc.timeout_seconds,
                    )

            finished_at = datetime.now(UTC)
            set_attributes(
                cycle_span,
                {
                    "nengok.cycle.clusters_detected": len(clusters),
                    "nengok.cycle.fixes_proposed": len(artifacts),
                    "nengok.cycle.escalations": escalations,
                    "nengok.cycle.duration_s": (finished_at - started_at).total_seconds(),
                    "nengok.cycle.gemini_tokens": cost_tracker.tokens_used,
                    "nengok.cycle.gemini_dollars": cost_tracker.dollars_used,
                    "nengok.cycle.over_budget": over_budget,
                },
            )
            logger.info(
                "Cycle complete in %.1fs (tokens=%d, $=%.4f, over_budget=%s)",
                (finished_at - started_at).total_seconds(),
                cost_tracker.tokens_used,
                cost_tracker.dollars_used,
                over_budget,
            )

            self._state.record_cycle_usage(
                cycle_id=run_id,
                started_at=started_at,
                ended_at=finished_at,
                gemini_tokens=cost_tracker.tokens_used,
                gemini_dollars=cost_tracker.dollars_used,
            )

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

    def _fresh_cost_tracker(self) -> CostTracker:
        return CostTracker(
            input_dollars_per_million=self.config.gemini_input_dollars_per_million,
            output_dollars_per_million=self.config.gemini_output_dollars_per_million,
        )

    def _attach_cost_tracker(self, cost_tracker: CostTracker) -> None:
        self._clusterer.cost_tracker = cost_tracker
        self._hypothesizer.cost_tracker = cost_tracker
        self._test_generator.cost_tracker = cost_tracker
        self._prompt_proposer.cost_tracker = cost_tracker

    def _is_over_budget(self, cost_tracker: CostTracker) -> bool:
        return cost_tracker.is_over_budget(self.config.gemini_cycle_token_budget)

    def _record_over_budget(
        self,
        *,
        cost_tracker: CostTracker,
        skipped_cluster_ids: list[str],
    ) -> None:
        body_lines = [
            f"- tokens_used: {cost_tracker.tokens_used}",
            f"- token_budget: {self.config.gemini_cycle_token_budget}",
            f"- dollars_used: {cost_tracker.dollars_used:.4f}",
            f"- skipped_cluster_count: {len(skipped_cluster_ids)}",
            "",
            "Skipped clusters:",
        ]
        for cluster_id in skipped_cluster_ids:
            body_lines.append(f"  - `{cluster_id}`")
        body_lines.append("")
        body_lines.append(
            "The cycle aborted before processing the remaining clusters because "
            "the configured `gemini_cycle_token_budget` was exceeded. Raise the "
            "budget in `~/.nengok/config.toml` to let more clusters through per "
            "cycle, or investigate why a single cluster spent this many tokens."
        )
        write_incident(
            artifacts_dir=self.config.artifacts_dir,
            filename="over-budget.md",
            title="Cycle aborted: Gemini cost budget exceeded",
            body="\n".join(body_lines),
        )
        logger.warning(
            "Cycle aborted: %d tokens used (budget=%d, $=%.4f); %d cluster(s) skipped",
            cost_tracker.tokens_used,
            self.config.gemini_cycle_token_budget,
            cost_tracker.dollars_used,
            len(skipped_cluster_ids),
        )

    def _record_phoenix_timeout(self, *, cluster: Cluster, exc: PhoenixTimeoutError) -> None:
        body_lines = [
            f"- cluster_id: `{cluster.cluster_id}`",
            f"- cluster_name: `{cluster.name}`",
            f"- phoenix_method: `{exc.method}`",
            f"- configured_timeout_seconds: {exc.timeout_seconds:.1f}",
        ]
        if exc.observed_seconds is not None:
            body_lines.append(f"- observed_seconds: {exc.observed_seconds:.1f}")
        body_lines.append("")
        body_lines.append(
            "Phoenix did not respond inside the configured budget. The cluster is "
            "marked escalated for human review. Raise `phoenix_*_timeout_seconds` "
            "in `~/.nengok/config.toml` to give Phoenix more time, or investigate "
            "why this call ran long."
        )
        write_incident(
            artifacts_dir=self.config.artifacts_dir,
            filename=f"phoenix-timeout-{cluster.cluster_id}.md",
            title=f"Phoenix timeout while processing cluster {cluster.name}",
            body="\n".join(body_lines),
        )


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


def _earliest_span_time(cluster: Cluster, anomalies: list[AnomalousSpan]) -> datetime | None:
    by_span_id = {a.span.span_id: a.span.started_at for a in anomalies}
    times = [t for span_id in cluster.member_span_ids if (t := by_span_id.get(span_id)) is not None]
    return min(times) if times else None


def _cluster_span_attrs(cluster: Cluster, signal_counts: dict[str, dict[str, int]]) -> dict[str, object]:
    attrs: dict[str, object] = {
        "nengok.cluster.id": cluster.cluster_id,
        "nengok.cluster.name": cluster.name,
        "nengok.cluster.member_count": len(cluster.member_span_ids),
    }
    for signal_name, count in signal_counts.get(cluster.cluster_id, {}).items():
        attrs[f"nengok.cluster.signal.{signal_name}"] = count
    return attrs
