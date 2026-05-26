"""
Entry point for the retrieval-augmented Q&A demo agent.

Usage:

    python -m sample_agent.qa_agent.agent --question "What is Nengok?"
    python -m sample_agent.qa_agent.agent --question "..." --inject retriever
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from nengok.utils.gemini import call_gemini

PROMPT_PATH = Path(__file__).parent / "prompts" / "qa.md"
DEFAULT_MODEL = "gemini-2.5-flash"
PHOENIX_PROJECT_NAME = "qa-agent"

CORPUS: tuple[tuple[str, str], ...] = (
    (
        "nengok-overview",
        "Nengok is a pip-installable SDK that watches an Arize Phoenix project, "
        "clusters failure patterns from anomalous traces, generates regression "
        "tests, and proposes prompt fixes for human approval.",
    ),
    (
        "phoenix-overview",
        "Arize Phoenix is an open-source LLM observability platform. It stores "
        "traces, supports OpenInference instrumentation, and exposes datasets "
        "and experiments through a Python SDK.",
    ),
    (
        "human-in-the-loop",
        "Nengok never auto-applies a fix. Every proposed prompt change lands in "
        "the local artifacts directory and waits for a one-click approve or "
        "reject in the dashboard.",
    ),
    (
        "data-egress",
        "Trace data never leaves the user's infrastructure. Nengok runs locally "
        "next to the Phoenix instance, calls the user's Gemini key directly, "
        "and writes fix artifacts to the local filesystem.",
    ),
    (
        "evaluator-policy",
        "Nengok runs code-first evaluators on every experiment. Subjective "
        "criteria like coherence and intent match are the only checks that "
        "reach an LLM-as-Judge.",
    ),
)


def retrieve(question: str, *, drop_context: bool) -> list[tuple[str, str]]:
    """
    Naive substring retriever over the in-memory CORPUS.

    When ``drop_context`` is True, returns an empty list. That is the
    injected failure mode that lets Gemini hallucinate from memory
    despite the prompt instructing it to refuse.
    """
    if drop_context:
        return []
    needles = [_normalize_token(token) for token in question.split()]
    needles = [n for n in needles if len(n) > 3]
    matches: list[tuple[str, str]] = []
    for snippet_id, body in CORPUS:
        body_lower = body.lower()
        if any(needle in body_lower for needle in needles):
            matches.append((snippet_id, body))
    return matches[:3]


def _normalize_token(token: str) -> str:
    return "".join(ch for ch in token.lower() if ch.isalnum() or ch == "-")


def answer_question(question: str, *, prompt: str | None = None, drop_context: bool = False) -> dict:
    """
    Look up snippets, then ask Gemini to compose an answer that quotes
    at least one of them. Returns the structured trace payload that
    Phoenix sees on the LLM span.
    """
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is not installed; the QA agent needs it to call Gemini. "
            'Reinstall with: pip install -e ".[dev,phoenix,gemini]"'
        ) from exc

    snippets = retrieve(question, drop_context=drop_context)
    system_prompt = prompt if prompt is not None else PROMPT_PATH.read_text(encoding="utf-8")
    rendered_snippets = "\n".join(f"[{sid}] {body}" for sid, body in snippets) or "(none)"
    user_prompt = f"Question: {question}\n\n" f"--- SNIPPETS ---\n{rendered_snippets}\n--- END SNIPPETS ---"

    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    answer = call_gemini(
        client,
        model=os.environ.get("QA_AGENT_MODEL", DEFAULT_MODEL),
        contents=[{"role": "user", "parts": [{"text": system_prompt + "\n\n" + user_prompt}]}],
        env_var_hint="QA_AGENT_MODEL",
        role_hint="QA Agent",
    )

    return {
        "question": question,
        "snippets": snippets,
        "answer": answer,
        "prompt_source": "injected" if prompt is not None else PROMPT_PATH.name,
    }


def _maybe_register_phoenix_tracing() -> None:
    try:
        from phoenix.otel import register
    except ImportError as exc:
        raise RuntimeError(
            "arize-phoenix-otel is not installed but PHOENIX_BASE_URL is set. "
            'Reinstall with: pip install -e ".[dev,phoenix,gemini]"'
        ) from exc

    try:
        from openinference.instrumentation.google_genai import GoogleGenAIInstrumentor
    except ImportError as exc:
        raise RuntimeError(
            "openinference-instrumentation-google-genai is not installed. "
            'Reinstall with: pip install -e ".[dev,phoenix,gemini]"'
        ) from exc

    tracer_provider = register(project_name=PHOENIX_PROJECT_NAME, auto_instrument=True)
    instrumentor = GoogleGenAIInstrumentor()
    if not instrumentor.is_instrumented_by_opentelemetry:
        instrumentor.instrument(tracer_provider=tracer_provider)


def main() -> None:
    load_dotenv(override=False)

    if os.environ.get("PHOENIX_BASE_URL"):
        _maybe_register_phoenix_tracing()
    else:
        print(
            "WARNING: PHOENIX_BASE_URL is not set. This run will not emit traces to Phoenix.",
            file=sys.stderr,
        )

    parser = argparse.ArgumentParser(description="QA demo agent.")
    parser.add_argument("--question", default="What is Nengok?")
    parser.add_argument(
        "--inject",
        choices=["none", "retriever"],
        default="none",
        help="Toggle the retriever-drop failure mode.",
    )
    args = parser.parse_args()

    result = answer_question(args.question, drop_context=(args.inject == "retriever"))
    print(result)


if __name__ == "__main__":  # pragma: no cover
    main()
