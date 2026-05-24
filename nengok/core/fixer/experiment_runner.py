"""
Run the baseline + fix experiments for a single cluster.

This stage is the single most Phoenix-coupled piece of the loop. It
uses the Python SDK (not MCP) per the project rule "Phoenix SDK for
writes, MCP for reads" and runs a dry-run sanity check before
committing to the full dataset.
"""

from __future__ import annotations

from dataclasses import dataclass

from nengok.config import NengokConfig
from nengok.core.evaluators.code_evals import default_code_evaluators
from nengok.core.evaluators.llm_judges import default_judges
from nengok.core.types import Cluster, ExperimentResult, PromptProposal, RegressionTestCase
from nengok.phoenix.client import PhoenixWrapper
from nengok.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ExperimentRunner:
    phoenix: PhoenixWrapper
    config: NengokConfig

    def run(
        self,
        *,
        cluster: Cluster,
        cases: list[RegressionTestCase],
        proposal: PromptProposal,
    ) -> ExperimentResult:
        dataset_name = f"{cluster.name}-regression"
        dataset_ref = self.phoenix.create_dataset(name=dataset_name, cases=cases)

        evaluators = [*default_code_evaluators(), *default_judges(self.config)]

        baseline = self.phoenix.run_experiment(
            dataset_ref=dataset_ref,
            prompt=proposal.baseline_prompt,
            evaluators=evaluators,
            experiment_name=f"{cluster.cluster_id}-baseline",
            dry_run=self.config.dry_run_samples,
        )
        fix = self.phoenix.run_experiment(
            dataset_ref=dataset_ref,
            prompt=proposal.proposed_prompt,
            evaluators=evaluators,
            experiment_name=f"{cluster.cluster_id}-fix",
            dry_run=self.config.dry_run_samples,
        )
        golden_baseline, golden_fix = self.phoenix.run_golden_comparison(
            baseline_prompt=proposal.baseline_prompt,
            proposed_prompt=proposal.proposed_prompt,
            evaluators=evaluators,
        )

        return ExperimentResult(
            experiment_name=f"{cluster.cluster_id}-fix",
            experiment_id=fix.experiment_id,
            dataset_name=dataset_name,
            baseline_pass_rate=baseline.pass_rate,
            fix_pass_rate=fix.pass_rate,
            golden_baseline_pass_rate=golden_baseline.pass_rate,
            golden_fix_pass_rate=golden_fix.pass_rate,
            per_case=fix.per_case,
        )
