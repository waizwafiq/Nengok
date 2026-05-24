"""
LLM-as-Judge evaluators.

These are reserved for subjective dimensions where no programmatic
check is possible: coherence, helpfulness, intent-match. Per the
project rule, structural checks live in `code_evals.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nengok.config import NengokConfig


@dataclass(frozen=True)
class JudgeSpec:
    """A vendor-neutral description of an LLM-as-Judge evaluator."""

    name: str
    prompt_template: str
    choices: dict[str, float]
    model: str


COHERENCE_PROMPT = (
    "You are an impartial reviewer. Read the user's input and the "
    "assistant's response, then decide whether the response is "
    "internally coherent and on-topic.\n\n"
    "INPUT:\n{{input}}\n\n"
    "RESPONSE:\n{{output}}\n\n"
    'Respond with exactly one word: "coherent" or "incoherent".'
)

INTENT_MATCH_PROMPT = (
    "Compare the assistant's response to the user's intent. Did the "
    "response address what the user actually asked for?\n\n"
    "INPUT:\n{{input}}\n\n"
    "RESPONSE:\n{{output}}\n\n"
    'Respond with exactly one word: "match" or "miss".'
)


def default_judges(config: NengokConfig) -> list[JudgeSpec]:
    return [
        JudgeSpec(
            name="coherence",
            prompt_template=COHERENCE_PROMPT,
            choices={"coherent": 1.0, "incoherent": 0.0},
            model=config.judge_model,
        ),
        JudgeSpec(
            name="intent_match",
            prompt_template=INTENT_MATCH_PROMPT,
            choices={"match": 1.0, "miss": 0.0},
            model=config.judge_model,
        ),
    ]


def _ensure_phoenix_judge(spec: JudgeSpec) -> Any:
    """
    Convert a JudgeSpec into a `phoenix.evals.ClassificationEvaluator`.

    Wrapped in a private helper so the rest of Nengok stays decoupled
    from `arize-phoenix-evals` until the SDK is actually used; tests
    that touch `JudgeSpec` do not need the optional extra installed.
    """
    try:
        from phoenix.evals import LLM, ClassificationEvaluator
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "arize-phoenix-evals is not installed. " "Install it via `pip install nengok[phoenix]`."
        ) from exc

    return ClassificationEvaluator(
        name=spec.name,
        prompt_template=spec.prompt_template,
        choices=spec.choices,
        llm=LLM(provider="google", model=spec.model),
    )
