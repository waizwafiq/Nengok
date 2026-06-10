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

import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from pydantic import ValidationError

from nengok.agents.triage import TriageVerdict, run_triage, triage_disabled_reason
from nengok.config import NengokConfig
from nengok.core.cost import CostTracker
from nengok.core.diagnoser.clusterer import Clusterer
from nengok.core.diagnoser.cross_agent import CrossAgentLinker
from nengok.core.diagnoser.hypothesizer import Hypothesizer
from nengok.core.diagnoser.matcher import ClusterMatcher
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
    CycleRecord,
    CycleResult,
    CycleStatus,
    ExperimentResult,
    FixArtifact,
    VerificationOutcome,
)
from nengok.core.verifier.artifact_writer import ArtifactWriter
from nengok.core.verifier.gate import VerifierGate
from nengok.errors import (
    NotifierLoadError,
    OptionalDependencyError,
    PhoenixTimeoutError,
    TriageError,
)
from nengok.notifiers.dispatcher import NotifierDispatcher
from nengok.notifiers.events import EscalationEvent, ExperimentSummary, FixProposedEvent
from nengok.phoenix.client import PhoenixWrapper
from nengok.phoenix.mcp import MCPError
from nengok.runners.agent_runner import register_runner
from nengok.runners.loader import load_runner
from nengok.server import metrics
from nengok.state.store import StateStore, cluster_from_row
from nengok.utils.gemini import GeminiCallError
from nengok.utils.logging import get_logger, run_context
from nengok.utils.tracing import get_tracer, register_meta_tracer, set_attributes

logger = get_logger(__name__)


@dataclass
class Orchestrator:
    config: NengokConfig

    _traced: ClassVar[bool] = False
    current_stage: str | None = None

    def __post_init__(self) -> None:
        self._ensure_runner_registered()
        self._triage_active = self._resolve_triage_active()
        self._phoenix = PhoenixWrapper(self.config)
        self._state = StateStore(self.config.state_db_path, schema=self.config.database_schema)

        self._redactor = Redactor.from_config(self.config)

        self._sampler = SpanSampler(self._phoenix, self.config)
        self._anomaly_filter = AnomalyFilter()
        self._clusterer = Clusterer(self.config, redactor=self._redactor)
        self._matcher = ClusterMatcher(self.config)
        self._linker = CrossAgentLinker(self.config)
        self._hypothesizer = Hypothesizer(self.config, phoenix=self._phoenix, redactor=self._redactor)

        self._test_generator = TestGenerator(self.config)
        self._prompt_proposer = PromptProposer(self.config, phoenix=self._phoenix, redactor=self._redactor)
        self._experiment_runner = ExperimentRunner(self._phoenix, self.config)

        self._gate = VerifierGate(self.config)
        self._artifact_writer = ArtifactWriter(self.config.artifacts_dir, redactor=self._redactor)
        self._notifier_dispatcher = self._build_notifier_dispatcher()

    def _ensure_runner_registered(self) -> None:
        """
        Load the config-driven runner for every monitored project.

        Each project resolves through ``config.runner_spec_for``, so a
        mapped entry in ``agent_runners`` wins over the shared
        ``agent_runner`` fallback. Projects with neither rely on the
        imperative :func:`register_runner` API instead. Failures here
        surface as :class:`AgentRunnerLoadError` before any Phoenix
        calls fire, so a typo in a dotted path is caught at startup
        rather than mid-experiment.
        """
        for project in self.config.resolved_project_identifiers():
            spec = self.config.runner_spec_for(project)
            if not spec:
                continue
            runner = load_runner(spec, self.config.agent_runner_kwargs)
            register_runner(project, runner)

    def _resolve_triage_active(self) -> bool:
        """
        Decide once per process whether the ADK triage gate runs.

        When triage is on in config but cannot run (missing adk extra,
        no npx on PATH), warn a single time at startup and continue
        without it instead of warning on every cycle.
        """
        if not self.config.triage_enabled:
            return False
        reason = triage_disabled_reason(self.config)
        if reason is None:
            return True
        logger.warning(
            "Triage is enabled in config but cannot run: %s. "
            "Continuing without triage for the rest of this process.",
            reason,
        )
        return False

    def run_once(self, *, dry_run: bool = False) -> CycleResult:
        """One full Observer -> Diagnoser -> Fixer -> Verifier pass."""
        self._ensure_traced()
        tracer = get_tracer()

        run_id = uuid.uuid4().hex[:12]
        started_at = datetime.now(UTC)

        cost_tracker = self._fresh_cost_tracker()
        self._attach_cost_tracker(cost_tracker)

        cycle_status = CycleStatus.OK
        clusters_discovered = 0
        clusters_processed = 0

        try:
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

                triage_verdict = self._decide_triage()
                if triage_verdict is not None and not triage_verdict.investigate:
                    set_attributes(
                        cycle_span,
                        {
                            "nengok.triage.investigate": False,
                            "nengok.triage.reason": triage_verdict.reason,
                        },
                    )
                    self._persist_cycle(
                        cycle_id=run_id,
                        started_at=started_at,
                        ended_at=datetime.now(UTC),
                        status=CycleStatus.SKIPPED_BY_TRIAGE,
                        clusters_processed=0,
                        clusters_discovered=0,
                        cost_tracker=cost_tracker,
                    )
                    return CycleResult(clusters_detected=0, fixes_proposed=0, escalations=0)

                projects = self._projects_for_cycle(triage_verdict)
                set_attributes(cycle_span, {"nengok.projects": ", ".join(projects)})

                artifacts: list[FixArtifact] = []
                escalations = 0
                clusters: list[Cluster] = []
                all_new_anomalies: list[AnomalousSpan] = []
                baselines: dict[str, str] = {}
                merged_count = 0

                for project in projects:
                    with (
                        run_context(stage="observer"),
                        tracer.start_as_current_span("observer") as observer_span,
                    ):
                        self.current_stage = "observer"
                        set_attributes(observer_span, {"nengok.project": project})
                        spans = self._sampler.sample(
                            project_identifier=project,
                            window_minutes=(
                                triage_verdict.window_minutes if triage_verdict is not None else None
                            ),
                        )
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
                            "Observer[%s]: %d spans -> %d anomalies -> %d new after dedup",
                            project,
                            len(spans),
                            len(anomalies),
                            len(new_anomalies),
                        )

                    if not new_anomalies:
                        continue
                    all_new_anomalies.extend(new_anomalies)
                    baselines[project] = self._prompt_proposer.load_baseline_prompt(project)

                    with (
                        run_context(stage="diagnoser"),
                        tracer.start_as_current_span("diagnoser") as diagnoser_span,
                    ):
                        self.current_stage = "diagnoser"
                        set_attributes(diagnoser_span, {"nengok.project": project})
                        self._clusterer.feedback = self._state.list_cluster_feedback(
                            project, self.config.clustering_feedback_examples
                        )
                        active_advice = self._state.get_active_advice(project)
                        self._clusterer.advice_amendment = (
                            active_advice["prompt_amendment"] if active_advice else None
                        )
                        raw_clusters = self._clusterer.cluster(new_anomalies)
                        clusters_discovered += len(raw_clusters)
                        known = [
                            c
                            for c in (cluster_from_row(row) for row in self._state.list_clusters())
                            if c.project in (None, project)
                        ]
                        known_by_id = {c.cluster_id: c for c in known}

                        diagnosed_here = 0
                        for raw in raw_clusters:
                            raw = raw.model_copy(update={"project": project})
                            match_id = self._matcher.match(raw, known)
                            prior = known_by_id.get(match_id) if match_id is not None else None
                            merged = raw if prior is None else _merge_into_existing(raw, prior)
                            if prior is not None:
                                merged_count += 1

                            decision = self._apply_identity_policy(
                                merged=merged,
                                prior=prior,
                                anomalies=new_anomalies,
                                baseline_prompt=baselines[project],
                            )
                            if decision is not None:
                                clusters.append(decision)
                                diagnosed_here += 1
                            elif prior is not None and prior.status is ClusterStatus.APPROVED:
                                escalations += 1

                        set_attributes(
                            diagnoser_span,
                            {
                                "nengok.diagnoser.cluster_count": diagnosed_here,
                                "nengok.diagnoser.merged_count": merged_count,
                            },
                        )
                        logger.info(
                            "Diagnoser[%s]: %d clusters with hypotheses (%d merged this cycle)",
                            project,
                            diagnosed_here,
                            merged_count,
                        )

                if clusters:
                    with (
                        run_context(stage="linker"),
                        tracer.start_as_current_span("linker") as linker_span,
                    ):
                        self.current_stage = "linker"
                        links_created = self._run_cross_agent_linker(clusters)
                        set_attributes(linker_span, {"nengok.linker.links_created": links_created})

                signal_counts = _signal_counts_by_cluster(clusters, all_new_anomalies)

                for index, cluster in enumerate(clusters):
                    assert cluster.hypothesis is not None

                    if self._is_over_budget(cost_tracker):
                        cycle_status = CycleStatus.OVER_BUDGET
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
                            cluster_baseline = baselines.get(
                                cluster.project or self.config.project_identifier
                            )
                            proposal = self._prompt_proposer.propose(
                                cluster, baseline_prompt=cluster_baseline
                            )
                            set_attributes(fixer_span, {"nengok.fixer.case_count": len(cases)})

                            if dry_run:
                                logger.info("Dry run: skipping experiment for cluster '%s'", cluster.name)
                                clusters_processed += 1
                                continue

                            result = self._experiment_runner.run(
                                cluster=cluster, cases=cases, proposal=proposal
                            )
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
                                if self._notifier_dispatcher:
                                    self._notifier_dispatcher.dispatch(
                                        self._build_fix_proposed_event(cluster, result, artifact)
                                    )
                            else:
                                escalations += 1
                                self._state.mark_status(cluster.cluster_id, ClusterStatus.ESCALATED)
                                logger.warning(
                                    "Cluster '%s' escalated: %s",
                                    cluster.name,
                                    verification.outcome.value,
                                )
                        clusters_processed += 1
                    except PhoenixTimeoutError as exc:
                        escalations += 1
                        clusters_processed += 1
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
                        "nengok.cycle.over_budget": cycle_status is CycleStatus.OVER_BUDGET,
                    },
                )
                logger.info(
                    "Cycle complete in %.1fs (tokens=%d, $=%.4f, status=%s)",
                    (finished_at - started_at).total_seconds(),
                    cost_tracker.tokens_used,
                    cost_tracker.dollars_used,
                    cycle_status.value,
                )

                self._persist_cycle(
                    cycle_id=run_id,
                    started_at=started_at,
                    ended_at=finished_at,
                    status=cycle_status,
                    clusters_processed=clusters_processed,
                    clusters_discovered=clusters_discovered,
                    cost_tracker=cost_tracker,
                    clusters_merged=merged_count,
                    projects=projects,
                )

                return CycleResult(
                    clusters_detected=len(clusters),
                    fixes_proposed=len(artifacts),
                    escalations=escalations,
                    artifacts=artifacts,
                )
        except Exception as exc:
            self._persist_cycle(
                cycle_id=run_id,
                started_at=started_at,
                ended_at=datetime.now(UTC),
                status=CycleStatus.FAILED,
                clusters_processed=clusters_processed,
                clusters_discovered=clusters_discovered,
                cost_tracker=cost_tracker,
                error_message=f"{type(exc).__name__}: {exc}",
            )
            raise

    def _apply_identity_policy(
        self,
        *,
        merged: Cluster,
        prior: Cluster | None,
        anomalies: list[AnomalousSpan],
        baseline_prompt: str | None,
    ) -> Cluster | None:
        """
        Persist the matched cluster under the status policy and return the
        diagnosed cluster when the fixer should run, else None.

        REJECTED / DISMISSED re-accrete silently (the no-re-alert promise
        from proposal Section 3.3 Step 7). APPROVED means the approved fix
        did not hold: escalate with reason `fix_regressed` and notify.
        FIX_PROPOSED / ESCALATED attach spans and keep their status. The
        rest run the hypothesizer unless held below `min_cluster_size`.
        """
        if prior is not None and prior.status in (ClusterStatus.REJECTED, ClusterStatus.DISMISSED):
            self._persist_identity(merged.model_copy(update={"status": prior.status}), anomalies)
            logger.info(
                "Cluster '%s' re-accreted silently (status=%s); a reviewer already declined it",
                merged.name,
                prior.status.value,
            )
            return None

        if prior is not None and prior.status is ClusterStatus.APPROVED:
            escalated = merged.model_copy(update={"status": ClusterStatus.ESCALATED})
            self._persist_identity(escalated, anomalies)
            self._notify_fix_regressed(escalated)
            logger.warning(
                "Cluster '%s' escalated: fix_regressed (approved fix did not hold)",
                merged.name,
            )
            return None

        if prior is not None and prior.status in (ClusterStatus.FIX_PROPOSED, ClusterStatus.ESCALATED):
            self._persist_identity(merged.model_copy(update={"status": prior.status}), anomalies)
            return None

        if len(merged.member_span_ids) < self.config.min_cluster_size:
            self._persist_identity(merged.model_copy(update={"status": ClusterStatus.OPEN}), anomalies)
            logger.info(
                "Cluster '%s' held back: %d member(s) below min_cluster_size=%d",
                merged.name,
                len(merged.member_span_ids),
                self.config.min_cluster_size,
            )
            return None

        hypothesis = self._hypothesizer.hypothesize(
            merged,
            current_prompt=baseline_prompt,
            linked_summaries=self._linked_hypothesis_summaries(merged.cluster_id),
        )
        diagnosed = merged.model_copy(update={"hypothesis": hypothesis, "status": ClusterStatus.DIAGNOSED})
        self._persist_identity(diagnosed, anomalies)
        return diagnosed

    def _persist_identity(self, cluster: Cluster, anomalies: list[AnomalousSpan]) -> None:
        self._state.upsert_cluster(cluster, first_seen=_earliest_span_time(cluster, anomalies))
        self._state.assign_spans_to_cluster(cluster.member_span_ids, cluster.cluster_id)

    def _linked_hypothesis_summaries(self, cluster_id: str) -> list[str]:
        """Return sibling hypothesis summaries from confirmed cross-agent links."""
        summaries: list[str] = []
        for row in self._state.list_cluster_links(cluster_id):
            hypothesis_json = row.get("linked_hypothesis_json")
            if not hypothesis_json:
                continue
            try:
                summary = json.loads(hypothesis_json).get("summary")
            except (json.JSONDecodeError, AttributeError):
                continue
            if summary:
                label = f"{row.get('linked_project') or 'unknown-project'} / {row.get('linked_name')}"
                summaries.append(f"[{label}] {summary}")
        return summaries

    def _run_cross_agent_linker(self, cycle_clusters: list[Cluster]) -> int:
        """
        Confirm cross-project links for this cycle's clusters.

        The candidate pool is this cycle's diagnosed clusters plus every
        active cluster the store touched inside the lookback window. The
        store reads close before the judge calls fire, honoring the
        no-Gemini-inside-a-transaction rule.
        """
        since = datetime.now(UTC) - timedelta(days=self.config.cluster_link_lookback_days)
        recent = [cluster_from_row(row) for row in self._state.list_recent_active_clusters(since=since)]
        pool: dict[str, Cluster] = {c.cluster_id: c for c in recent}
        pool.update({c.cluster_id: c for c in cycle_clusters})

        projects = {c.project for c in pool.values() if c.project}
        if len(projects) < 2:
            return 0

        links = self._linker.link(list(pool.values()))
        created = 0
        for link in links:
            link_id = self._state.insert_cluster_link(
                cluster_id_a=link.cluster_id_a,
                cluster_id_b=link.cluster_id_b,
                confidence=link.confidence,
                rationale=link.rationale,
            )
            if link_id is not None:
                created += 1
                logger.info(
                    "Cross-agent link confirmed: %s <-> %s (confidence=%.2f)",
                    link.cluster_id_a,
                    link.cluster_id_b,
                    link.confidence,
                )
        return created

    def _notify_fix_regressed(self, cluster: Cluster) -> None:
        if not self._notifier_dispatcher:
            return
        dashboard_url = (
            f"{self.config.slack_dashboard_base_url.rstrip('/')}/clusters/{cluster.cluster_id}"
            if self.config.slack_dashboard_base_url
            else None
        )
        self._notifier_dispatcher.dispatch(
            EscalationEvent(
                cluster_id=cluster.cluster_id,
                cluster_name=cluster.name,
                status=ClusterStatus.ESCALATED.value,
                reason="fix_regressed",
                dashboard_url=dashboard_url,
            )
        )

    def _decide_triage(self) -> TriageVerdict | None:
        """
        Run the ADK triage gate and return its verdict, or None when off.

        Any failure inside the agent (schema violation, timeout, MCP
        subprocess death, Gemini error, missing extra) falls back to an
        investigate-everything verdict so the deterministic pipeline the
        cycle ran before this phase still executes. The `triage_path`
        field on the log line is the discriminator a reviewer can grep
        to confirm the ADK path ran versus the fallback.
        """
        if not self._triage_active:
            return None
        tracer = get_tracer()
        with (
            run_context(stage="triage"),
            tracer.start_as_current_span("triage") as triage_span,
        ):
            self.current_stage = "triage"
            started = time.perf_counter()
            triage_path = "adk"
            try:
                verdict = run_triage(self.config)
            except (
                ValidationError,
                TimeoutError,
                MCPError,
                GeminiCallError,
                OptionalDependencyError,
                TriageError,
            ) as exc:
                triage_path = "fallback"
                metrics.triage_errors_total.labels(error_class=type(exc).__name__).inc()
                logger.warning(
                    "Triage failed (%s); falling back to the deterministic anomaly filter",
                    type(exc).__name__,
                    exc_info=exc,
                )
                fallback_projects = self.config.resolved_project_identifiers()
                verdict = TriageVerdict(
                    investigate=True,
                    project=fallback_projects[0],
                    projects=fallback_projects,
                    window_minutes=self.config.triage_lookback_minutes,
                    reason="triage_fallback",
                )
            duration_s = time.perf_counter() - started
            metrics.triage_duration_seconds.observe(duration_s)
            metrics.triage_total.labels(
                path=triage_path,
                outcome="investigate" if verdict.investigate else "skip",
            ).inc()
            set_attributes(
                triage_span,
                {
                    "nengok.triage.path": triage_path,
                    "nengok.triage.investigate": verdict.investigate,
                    "nengok.triage.project": verdict.project,
                    "nengok.triage.window_minutes": verdict.window_minutes,
                    "nengok.triage.duration_s": duration_s,
                },
            )
            logger.info(
                "Triage decided: triage_path=%s investigate=%s project=%s window_minutes=%d reason=%s",
                triage_path,
                verdict.investigate,
                verdict.project,
                verdict.window_minutes,
                verdict.reason,
                extra={
                    "event": "triage_decided",
                    "triage_path": triage_path,
                    "investigate": verdict.investigate,
                    "project": verdict.project,
                    "window_minutes": verdict.window_minutes,
                    "reason": verdict.reason,
                },
            )
            return verdict

    def _ensure_traced(self) -> None:
        """Register the meta-tracer once per process."""
        if Orchestrator._traced:
            return
        register_meta_tracer()
        Orchestrator._traced = True

    def _persist_cycle(
        self,
        *,
        cycle_id: str,
        started_at: datetime,
        ended_at: datetime,
        status: CycleStatus,
        clusters_processed: int,
        clusters_discovered: int,
        cost_tracker: CostTracker,
        clusters_merged: int = 0,
        projects: list[str] | None = None,
        error_message: str | None = None,
    ) -> None:
        self._state.record_cycle(
            CycleRecord(
                cycle_id=cycle_id,
                started_at=started_at,
                ended_at=ended_at,
                status=status,
                clusters_processed=clusters_processed,
                clusters_discovered=clusters_discovered,
                clusters_merged=clusters_merged,
                gemini_tokens=cost_tracker.tokens_used,
                gemini_dollars=cost_tracker.dollars_used,
                error_message=error_message,
                projects=projects or [],
            )
        )

    def _projects_for_cycle(self, verdict: TriageVerdict | None) -> list[str]:
        """
        Decide which projects this cycle observes.

        Without a verdict every configured project runs. A verdict
        narrows the cycle to the projects it names (the Phase 16
        contract lets triage redirect the Observer, so the names are
        trusted verbatim); an empty verdict list falls back to the full
        configured set so a confused verdict cannot silence the cycle.
        """
        configured = self.config.resolved_project_identifiers()
        if verdict is None:
            return configured
        requested = [p for p in (verdict.projects or [verdict.project]) if p]
        return requested or configured

    def _fresh_cost_tracker(self) -> CostTracker:
        return CostTracker(
            input_dollars_per_million=self.config.gemini_input_dollars_per_million,
            output_dollars_per_million=self.config.gemini_output_dollars_per_million,
        )

    def _attach_cost_tracker(self, cost_tracker: CostTracker) -> None:
        self._clusterer.cost_tracker = cost_tracker
        self._matcher.cost_tracker = cost_tracker
        self._linker.cost_tracker = cost_tracker
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

    def _build_notifier_dispatcher(self) -> NotifierDispatcher | None:
        if not self.config.notifiers:
            return None
        try:
            return NotifierDispatcher.from_config(config=self.config, store=self._state)
        except NotifierLoadError as exc:
            logger.error("Notifier configuration error: %s", exc)
            raise

    def _build_fix_proposed_event(
        self,
        cluster: Cluster,
        result: ExperimentResult,
        artifact: FixArtifact,
    ) -> FixProposedEvent:
        h = cluster.hypothesis
        raw_summary = h.summary if h else None
        summary = self._redactor.redact(raw_summary) if raw_summary else None
        if summary and len(summary) > self.config.slack_max_summary_chars:
            summary = summary[: self.config.slack_max_summary_chars]

        dashboard_url = (
            f"{self.config.slack_dashboard_base_url.rstrip('/')}/clusters/{cluster.cluster_id}"
            if self.config.slack_dashboard_base_url
            else None
        )

        return FixProposedEvent(
            cluster_id=cluster.cluster_id,
            cluster_name=cluster.name,
            status=ClusterStatus.FIX_PROPOSED.value,
            hypothesis_summary=summary,
            experiment_summary=ExperimentSummary(
                baseline_pass_rate=result.baseline_pass_rate,
                fix_pass_rate=result.fix_pass_rate,
                golden_baseline_pass_rate=result.golden_baseline_pass_rate,
                golden_fix_pass_rate=result.golden_fix_pass_rate,
            ),
            artifact_manifest_ref=str(artifact.prompt_path).replace("prompt.md", "manifest.json"),
            dashboard_url=dashboard_url,
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


def _merge_into_existing(raw: Cluster, prior: Cluster) -> Cluster:
    """Adopt the prior cluster's id and union members and signals into it."""
    member_ids = list(dict.fromkeys([*prior.member_span_ids, *raw.member_span_ids]))
    return raw.model_copy(
        update={
            "cluster_id": prior.cluster_id,
            "member_span_ids": member_ids,
            "signals": sorted(set(prior.signals) | set(raw.signals)),
            "created_at": prior.created_at,
        }
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
