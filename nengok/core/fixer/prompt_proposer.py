"""
Propose a prompt-level fix for one cluster.

The proposer loads the active baseline prompt (from a bundled file for
the sample agent, from Phoenix prompt management otherwise, or from
``config.baseline_prompt_path`` as a fallback), then asks Gemini for a
tight diff that targets the cluster's failure mode without rewriting
the whole prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nengok.config import NengokConfig
from nengok.core.types import Cluster, PromptProposal
from nengok.phoenix.client import PhoenixWrapper
from nengok.utils.logging import get_logger

logger = get_logger(__name__)

SAMPLE_AGENT_PROJECT = "travel-planner-agent"
SAMPLE_AGENT_PROMPT_PATH = (
    Path(__file__).resolve().parents[3] / "sample_agent" / "prompts" / "travel_planner.md"
)


@dataclass
class PromptProposer:
    config: NengokConfig
    phoenix: PhoenixWrapper | None = None

    def propose(self, cluster: Cluster) -> PromptProposal:
        baseline = self._load_baseline_prompt()
        proposed = self._call_gemini_proposer(cluster=cluster, baseline=baseline)
        return PromptProposal(
            cluster_id=cluster.cluster_id,
            baseline_prompt=baseline,
            proposed_prompt=proposed.proposed_prompt,
            rationale=proposed.rationale,
        )

    def _load_baseline_prompt(self) -> str:
        """
        Resolve the agent's current prompt, in this precedence:

          1. Bundled file for the sample agent.
          2. Phoenix prompt management lookup by project identifier.
          3. ``config.baseline_prompt_path`` fallback.
        """
        if self.config.project_identifier == SAMPLE_AGENT_PROJECT:
            return SAMPLE_AGENT_PROMPT_PATH.read_text(encoding="utf-8")

        if self.phoenix is not None:
            remote = self.phoenix.get_prompt_version(name=self.config.project_identifier)
            if remote is not None:
                return remote

        if self.config.baseline_prompt_path is not None:
            return self.config.baseline_prompt_path.read_text(encoding="utf-8")

        raise RuntimeError(
            f"No baseline prompt for project '{self.config.project_identifier}'. "
            "Register one in Phoenix prompt management or set "
            "config.baseline_prompt_path."
        )

    def _call_gemini_proposer(self, *, cluster: Cluster, baseline: str) -> _ProposalDraft:
        logger.debug("Proposer placeholder for cluster=%s", cluster.cluster_id)
        return _ProposalDraft(
            proposed_prompt=baseline
            + "\n\n# Guardrail (auto-proposed by Nengok)\n# (no rewrite generated yet)",
            rationale=f"Pending fix proposal for cluster '{cluster.name}'.",
        )


@dataclass
class _ProposalDraft:
    proposed_prompt: str
    rationale: str
