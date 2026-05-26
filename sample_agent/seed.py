"""
Seed the Phoenix project with N anomalous Travel Planner runs.

This is the single command that replaces "run the agent three or four
times" in CONTRIBUTING.md step 5. Each run flips every injectable
failure mode on, rotates through a small set of queries so the
clusters look like real traffic rather than identical replays, and
ships traces to Phoenix via the same `_maybe_register_phoenix_tracing`
path the demo agent uses.

    python -m sample_agent.seed --count 5
    python -m sample_agent.seed --count 8 --inject hotels --query "Plan a Kyoto trip"
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from urllib.parse import urljoin

from dotenv import load_dotenv

from nengok.utils.gemini import GeminiQuotaError
from sample_agent.agent import (
    PHOENIX_PROJECT_NAME,
    _maybe_register_phoenix_tracing,
    build_itinerary,
)
from sample_agent.tools import failure_modes

QUOTA_RETRY_BUFFER_SECONDS = 1.0
QUOTA_RETRY_FALLBACK_SECONDS = 30.0

DEFAULT_QUERIES: tuple[str, ...] = (
    "Plan a 3-day trip from KL to Tokyo",
    "Plan a 2-day stopover in Singapore from KL",
    "Plan a 5-day Bangkok trip from Tokyo with a mid-range hotel",
    "Plan a 4-day Kyoto trip and name every hotel you recommend",
    "Plan a 3-day Auckland trip from Sydney and show the departure time",
    "Plan a 6-day Reykjavik trip from KL in January with clothing suggestions",
)


def _project_url(base_url: str, project_name: str) -> str:
    """Best-effort Phoenix UI URL for the project's traces page."""
    base = base_url.rstrip("/") + "/"
    return urljoin(base, f"projects/{project_name}")


def _run_once(query: str, run_index: int, total: int) -> bool:
    """Fire one run. On a 429 quota error, sleep the API-suggested delay and retry once."""
    print(f"[{run_index}/{total}] {query}", flush=True)
    try:
        build_itinerary(query)
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
            build_itinerary(query)
            return True
        except Exception as retry_exc:
            print(f"  retry failed: {retry_exc}", file=sys.stderr, flush=True)
            return False
    except Exception as exc:
        print(f"  failed: {exc}", file=sys.stderr, flush=True)
        return False


def main() -> int:
    load_dotenv(override=False)

    parser = argparse.ArgumentParser(description="Seed Phoenix with Travel Planner anomalies.")
    parser.add_argument("--count", type=int, default=5, help="How many runs to fire (default: 5).")
    parser.add_argument(
        "--inject",
        choices=["none", "flights", "weather", "hotels", "all"],
        default="all",
        help="Which failure modes to enable for the seed batch (default: all).",
    )
    parser.add_argument(
        "--query",
        default=None,
        help="Pin every run to this query instead of rotating through the default set.",
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
    failure_modes.configure(args.inject)

    queries = (args.query,) if args.query else DEFAULT_QUERIES

    succeeded = 0
    for i in range(args.count):
        query = queries[i % len(queries)]
        if _run_once(query, i + 1, args.count):
            succeeded += 1
        if args.sleep and i < args.count - 1:
            time.sleep(args.sleep)

    base_url = os.environ["PHOENIX_BASE_URL"]
    print()
    print(f"Seeded {succeeded}/{args.count} runs into Phoenix project '{PHOENIX_PROJECT_NAME}'.")
    print(f"Open: {_project_url(base_url, PHOENIX_PROJECT_NAME)}")
    print("Next: `nengok run` against the same project.")
    return 0 if succeeded == args.count else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
