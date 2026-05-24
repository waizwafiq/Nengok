"""
Propose a prompt-level fix for one cluster.

The proposer reads the active prompt version from Phoenix, formats a
diagnosis-aware prompt for Gemini, and returns a PromptProposal whose
`proposed_prompt` field will be A/B tested against `baseline_prompt`.
"""

from __future__ import annotations

from dataclasses import dataclass

from nengok.config import NengokConfig
from nengok.core.types import Cluster, PromptProposal
from nengok.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PromptProposer:
    config: NengokConfig

    def propose(self, cluster: Cluster) -> PromptProposal:
        baseline = self._load_baseline_prompt(cluster)
        proposed = self._call_gemini_proposer(cluster=cluster, baseline=baseline)
        return PromptProposal(
            cluster_id=cluster.cluster_id,
            baseline_prompt=baseline,
            proposed_prompt=proposed.proposed_prompt,
            rationale=proposed.rationale,
        )

    def _load_baseline_prompt(self, cluster: Cluster) -> str:
        return "You are a helpful AI assistant. Be concise and accurate."

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
