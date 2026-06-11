"""
Seed the Phoenix project with N anomalous Travel Planner runs.

This is the single command that replaces "run the agent three or four
times" in CONTRIBUTING.md step 5. Each run flips every injectable
failure mode on, composes its query from a phrase mixer (intent
template x destination x duration x budget x time reference) so the
traffic reads like real users rather than identical replays, and
ships traces to Phoenix via the same `_maybe_register_phoenix_tracing`
path the demo agent uses.

    python -m sample_agent.seed --count 5
    python -m sample_agent.seed --count 8 --inject hotels --query "Plan a Kyoto trip"
"""

from __future__ import annotations

import argparse
import os
import random
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

_DESTINATIONS: tuple[str, ...] = ("Tokyo", "Singapore", "Bangkok", "Kyoto", "Auckland", "Reykjavik")
_DESTINATION_WEIGHTS: tuple[int, ...] = (25, 1, 1, 1, 1, 1)
_ORIGINS: tuple[str, ...] = ("KL", "Kuala Lumpur", "Singapore", "Sydney", "Penang")
_DURATIONS: tuple[str, ...] = (
    "a weekend",
    "two days",
    "3 days",
    "three nights",
    "four nights",
    "5 days",
    "a week",
    "10 days",
    "just one night",
)
_BUDGETS: tuple[str, ...] = (
    "under 300 USD a night",
    "mid-range",
    "on a tight budget",
    "around 250 a night",
    "price is no issue",
    "as cheap as possible",
    "around 400 a night for something nicer",
)
_WHENS: tuple[str, ...] = (
    "next Friday",
    "next month",
    "this weekend",
    "in January",
    "in two weeks",
    "tomorrow",
    "over the holidays",
    "early next week",
)
_COMPANIONS: tuple[str, ...] = (
    "solo",
    "with my family",
    "with two kids",
    "with my partner",
    "for work",
)

_TEMPLATE_FAMILIES: tuple[tuple[str, ...], ...] = (
    (
        "Plan {duration} in {dest} from {origin}",
        "Help me plan {duration} in {dest}, flying out of {origin}",
        "I want to spend {duration} in {dest} {when}, build the itinerary",
        "{dest} for {duration} from {origin}: flights, hotel, and weather please",
        "Put together a {dest} trip from {origin}, about {duration}",
        "Organize {duration} in {dest} for me, departing {origin} {when}",
        "I'm going to {dest} {when}, traveling {companion}. Plan {duration} for me",
        "First time in {dest}: {duration}, from {origin}, traveling {companion}",
        "Surprise itinerary please: {dest}, {duration}, leaving {origin} {when}",
        "We're doing {dest} {when}. {duration}, full plan with flights and a hotel",
    ),
    (
        "Find me a flight from {origin} to {dest} {when} and show the exact departure time",
        "When does the next {origin} to {dest} flight leave?",
        "Just flights: {origin} to {dest} {when}, show me the schedule",
        "I need the departure time for a {dest} flight out of {origin}",
        "Book me a flight from {origin} to {dest} {when}, no hotel needed",
        "What time does the {origin}-{dest} flight depart {when}?",
        "Flying {origin} to {dest} {when}, traveling {companion}. Exact departure time please",
    ),
    (
        "Recommend a {dest} hotel {budget} for {duration}",
        "Where should I stay in {dest}? Staying {duration}, {budget}",
        "Looking for a {dest} hotel for {duration}, {budget}",
        "Which {dest} hotel gives the best value for {duration}?",
        "Got hotel suggestions for {dest}? There {duration}, {budget}",
        "Help me choose between {dest} hotels for {duration}",
        "Need a {dest} hotel {when}, staying {duration}, traveling {companion}, {budget}",
        "Pick me one {dest} hotel: {duration}, {budget}, and explain why",
        "Best area to stay in {dest} for {duration}? I'm traveling {companion}",
        "Compare two {dest} hotels by price for {duration}",
    ),
    (
        "What's the weather in {dest} {when} and what should I pack?",
        "Is {dest} cold {when}? I need packing advice",
        "Give me the {dest} weather outlook {when}, I'm deciding what to wear",
        "Heading to {dest} {when}, what should I wear?",
        "Packing for {dest} {when}, traveling {companion}. What goes in the bag?",
        "Do I need an umbrella in {dest} {when}?",
    ),
    (
        "One full day in {dest}: build me a schedule around the weather",
        "Plan a day trip in {dest} with morning and evening weather",
        "I have a long layover in {dest} {when}, what can I fit in?",
        "Six hours free in {dest} {when}, traveling {companion}. What's doable?",
    ),
    (
        "{dest} {duration} hotel + flights",
        "cheap hotel {dest} {duration}",
        "{dest} flight time {when}?",
        "what to pack {dest} {when}",
        "{origin} to {dest} {when}, what time and how much",
        "{dest} itinerary {duration}, go",
    ),
)

_TYPO_SWAPS: tuple[tuple[str, str], ...] = (
    ("weather", "wether"),
    ("tomorrow", "tmrw"),
    ("weekend", "wknd"),
    ("flight", "fligth"),
    ("Recommend", "Reccomend"),
    ("itinerary", "itinarary"),
)
_CASUAL_PREFIXES: tuple[str, ...] = ("hey, ", "hi - ", "ok so ", "quick one: ", "umm ")
_CASUAL_SUFFIXES: tuple[str, ...] = (" pls", " thanks!", " thx", " asap", "??")


def _roughen(query: str, rng: random.Random) -> str:
    """
    Make a query read like real user input.

    Roughly half the queries stay polished; the rest pick up the kind of
    noise production traffic actually has: lowercase, a typo, a casual
    opener, or a dangling "pls".
    """
    if rng.random() < 0.5:
        return query
    if rng.random() < 0.4:
        query = query.lower()
    if rng.random() < 0.35:
        old, new = rng.choice(_TYPO_SWAPS)
        if old in query:
            query = query.replace(old, new, 1)
        elif old.lower() in query:
            query = query.replace(old.lower(), new.lower(), 1)
    if rng.random() < 0.3:
        query = rng.choice(_CASUAL_PREFIXES) + query
    if rng.random() < 0.3:
        query = query.rstrip(".?!") + rng.choice(_CASUAL_SUFFIXES)
    return query


def _random_query(rng: random.Random) -> str:
    """Compose one user-style query from the phrase mixer."""
    dest = rng.choices(_DESTINATIONS, weights=_DESTINATION_WEIGHTS, k=1)[0]
    origins = [origin for origin in _ORIGINS if origin != dest] or list(_ORIGINS)
    parts = {
        "dest": dest,
        "origin": rng.choice(origins),
        "duration": rng.choice(_DURATIONS),
        "budget": rng.choice(_BUDGETS),
        "when": rng.choice(_WHENS),
        "companion": rng.choice(_COMPANIONS),
    }
    family = rng.choice(_TEMPLATE_FAMILIES)
    return _roughen(rng.choice(family).format(**parts), rng)


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

    rng = random.Random()

    succeeded = 0
    for i in range(args.count):
        query = args.query if args.query else _random_query(rng)
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
