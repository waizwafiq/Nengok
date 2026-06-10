"""
Seed the Phoenix project with N anomalous QA-agent runs.

Each run rotates through a small bank of questions and a small bank of
failure modes so the resulting clusters look like real production
traffic rather than identical replays. Use this as the QA-agent
equivalent of ``python -m sample_agent.seed`` before invoking
``nengok run`` against the ``qa-agent`` project.

    python -m sample_agent.qa_agent.seed --count 5
    python -m sample_agent.qa_agent.seed --count 8 --inject hallucination
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from urllib.parse import urljoin

from dotenv import load_dotenv

from nengok.utils.gemini import GeminiQuotaError
from sample_agent.qa_agent.agent import (
    FAILURE_CHOICES,
    PHOENIX_PROJECT_NAME,
    FailureMode,
    _maybe_register_phoenix_tracing,
    answer_question,
)

QUOTA_RETRY_BUFFER_SECONDS = 1.0
QUOTA_RETRY_FALLBACK_SECONDS = 30.0

DEFAULT_QUESTIONS: tuple[str, ...] = (
    "What is Nengok?",
    "How does Nengok handle human approval for proposed prompt fixes?",
    "Where do Nengok artifacts get written and who can read them?",
    "Which LLM observability platform does Nengok rely on?",
    "What does OpenInference provide for LLM tracing?",
    "How does Nengok decide between a code evaluator and an LLM-as-Judge?",
    "When does flight MH88 from KUL to NRT depart?",
)

ROTATING_FAILURES: tuple[FailureMode, ...] = (
    "retriever",
    "hallucination",
    "wrong_attribution",
    "flights_schema",
)


def _project_url(base_url: str, project_name: str) -> str:
    base = base_url.rstrip("/") + "/"
    return urljoin(base, f"projects/{project_name}")


def _run_once(question: str, failure: FailureMode, run_index: int, total: int) -> bool:
    print(f"[{run_index}/{total}] ({failure}) {question}", flush=True)
    try:
        answer_question(question, failure=failure)
        return True
    except GeminiQuotaError as exc:
        wait_seconds = (exc.retry_after_seconds or QUOTA_RETRY_FALLBACK_SECONDS) + QUOTA_RETRY_BUFFER_SECONDS
        quota_label = f" [{exc.quota_id}]" if exc.quota_id else ""
        print(
            f"  quota exhausted{quota_label}; pausing {wait_seconds:.0f}s and retrying",
            file=sys.stderr,
            flush=True,
        )
        time.sleep(wait_seconds)
        try:
            answer_question(question, failure=failure)
            return True
        except Exception as retry_exc:
            print(f"  retry failed: {retry_exc}", file=sys.stderr, flush=True)
            return False
    except Exception as exc:
        print(f"  failed: {exc}", file=sys.stderr, flush=True)
        return False


def main() -> int:
    load_dotenv(override=False)

    parser = argparse.ArgumentParser(description="Seed Phoenix with QA-agent anomalies.")
    parser.add_argument("--count", type=int, default=5, help="How many runs to fire (default: 5).")
    parser.add_argument(
        "--inject",
        choices=[*FAILURE_CHOICES, "rotate"],
        default="rotate",
        help="Which failure mode to enable. `rotate` cycles through every mode.",
    )
    parser.add_argument(
        "--question",
        default=None,
        help="Pin every run to this question instead of rotating through the default bank.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Seconds to sleep between runs (default: 0). Useful if Gemini rate-limits.",
    )
    args = parser.parse_args()

    if args.count < 1:
        print("error: --count must be at least 1", file=sys.stderr)
        return 2

    if not os.environ.get("PHOENIX_BASE_URL"):
        print(
            "error: PHOENIX_BASE_URL is not set. Copy .env.example to .env or export it, then retry.",
            file=sys.stderr,
        )
        return 2
    if not os.environ.get("GOOGLE_API_KEY"):
        print("error: GOOGLE_API_KEY is not set. Add it to .env and retry.", file=sys.stderr)
        return 2

    _maybe_register_phoenix_tracing()

    questions = (args.question,) if args.question else DEFAULT_QUESTIONS
    if args.inject == "rotate":
        failures: tuple[FailureMode, ...] = ROTATING_FAILURES
    else:
        failures = (args.inject,)

    succeeded = 0
    for i in range(args.count):
        question = questions[i % len(questions)]
        failure = failures[i % len(failures)]
        if _run_once(question, failure, i + 1, args.count):
            succeeded += 1
        if args.sleep and i < args.count - 1:
            time.sleep(args.sleep)

    base_url = os.environ["PHOENIX_BASE_URL"]
    print()
    print(f"Seeded {succeeded}/{args.count} runs into Phoenix project '{PHOENIX_PROJECT_NAME}'.")
    print(f"Open: {_project_url(base_url, PHOENIX_PROJECT_NAME)}")
    print("Next: `nengok run --project qa-agent` against the same Phoenix.")
    return 0 if succeeded == args.count else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
