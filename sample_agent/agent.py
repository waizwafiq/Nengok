"""
Entry point for the Travel Planner demo.

Usage:

    python -m sample_agent.agent --query "Plan a 3-day trip from KL to Tokyo"
    python -m sample_agent.agent --inject all
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from sample_agent.tools import failure_modes, flights, hotels, weather

PROMPT_PATH = Path(__file__).parent / "prompts" / "travel_planner.md"


def build_itinerary(query: str) -> dict:
    """
    Stand-in for the LLM call.

    The hackathon-time implementation replaces this body with a real
    Gemini call via Google ADK. The shape of the return value mirrors
    what the agent emits today so the rest of the pipeline is stable.
    """
    flights_data = flights.search_flights(origin="KUL", destination="HND")
    weather_data = weather.get_forecast(city="Tokyo")
    hotels_data = hotels.search_hotels(city="Tokyo", nights=3)

    return {
        "query": query,
        "flights": flights_data,
        "weather": weather_data,
        "hotels": hotels_data,
        "prompt_source": PROMPT_PATH.name,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Travel Planner demo agent.")
    parser.add_argument("--query", default="Plan a 3-day trip from KL to Tokyo")
    parser.add_argument(
        "--inject",
        choices=["none", "flights", "weather", "hotels", "all"],
        default="none",
        help="Toggle injectable failure modes for this run.",
    )
    args = parser.parse_args()

    failure_modes.configure(args.inject)

    if os.environ.get("PHOENIX_BASE_URL"):
        _maybe_register_phoenix_tracing()

    result = build_itinerary(args.query)
    print(result)


def _maybe_register_phoenix_tracing() -> None:
    """Wire OpenInference traces into Phoenix if the env vars are set."""
    try:
        from phoenix.otel import register
    except ImportError:
        return
    register(project_name="travel-planner-agent", auto_instrument=True)


if __name__ == "__main__":  # pragma: no cover
    main()
