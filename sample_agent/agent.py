"""
Entry point for the Travel Planner demo.

Usage:

    python -m sample_agent.agent --query "Plan a 3-day trip from KL to Tokyo"
    python -m sample_agent.agent --inject all
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from sample_agent.tools import failure_modes, flights, hotels, weather

PROMPT_PATH = Path(__file__).parent / "prompts" / "travel_planner.md"
DEFAULT_MODEL = "gemini-2.5-flash"
PHOENIX_PROJECT_NAME = "travel-planner-agent"


def build_itinerary(query: str, *, prompt: str | None = None) -> dict:
    """
    Plan an itinerary by calling the three mock tools and asking Gemini
    to compose them into a multi-day plan.

    Tool outputs and the system prompt are passed verbatim to Gemini so
    the injected failure modes (schema drift, unit mismatch, hotels
    timeout) surface as anomalies on the LLM span Phoenix records.

    When ``prompt`` is supplied, that string replaces the bundled
    baseline. The Phoenix experiment runner uses this to compare a
    candidate fix against the on-disk prompt without touching the file.
    """
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is not installed; the sample agent needs it to call Gemini. "
            'Reinstall with: pip install -e ".[dev,phoenix,gemini]"'
        ) from exc

    flights_data: object
    hotels_error: str | None = None
    try:
        hotels_data = hotels.search_hotels(city="Tokyo", nights=3)
    except hotels.HotelsTimeoutError as exc:
        hotels_data = []
        hotels_error = str(exc)

    flights_data = flights.search_flights(origin="KUL", destination="HND")
    weather_data = weather.get_forecast(city="Tokyo")

    system_prompt = prompt if prompt is not None else PROMPT_PATH.read_text(encoding="utf-8")
    tool_payload = {
        "flights": flights_data,
        "weather": weather_data,
        "hotels": hotels_data,
        "hotels_error": hotels_error,
    }
    user_prompt = (
        f"User query: {query}\n\n"
        f"Tool outputs (JSON):\n{json.dumps(tool_payload, indent=2)}\n\n"
        "Compose a short itinerary that cites each tool result. If a tool "
        "returned an unexpected schema, unit, or error, flag it explicitly."
    )

    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    response = client.models.generate_content(
        model=os.environ.get("SAMPLE_AGENT_MODEL", DEFAULT_MODEL),
        contents=[{"role": "user", "parts": [{"text": system_prompt + "\n\n" + user_prompt}]}],
    )

    return {
        "query": query,
        "flights": flights_data,
        "weather": weather_data,
        "hotels": hotels_data,
        "hotels_error": hotels_error,
        "itinerary": response.text,
        "prompt_source": "injected" if prompt is not None else PROMPT_PATH.name,
    }


def main() -> None:
    load_dotenv(override=False)

    if os.environ.get("PHOENIX_BASE_URL"):
        _maybe_register_phoenix_tracing()
    else:
        print(
            "WARNING: PHOENIX_BASE_URL is not set. This run will not emit traces to Phoenix. "
            "Copy .env.example to .env (or export PHOENIX_BASE_URL in your shell) and rerun.",
            file=sys.stderr,
        )

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

    result = build_itinerary(args.query)
    print(result)


def _maybe_register_phoenix_tracing() -> None:
    """
    Wire OpenInference traces into Phoenix when PHOENIX_BASE_URL is set.

    Both dependencies are required for the sample agent's traces to
    reach Phoenix. A silent return here used to be the failure mode
    reported in step 6 of CONTRIBUTING.md: the Gemini call still ran,
    but no span shipped, the ``travel-planner-agent`` project never
    got created, and ``nengok run`` 404d on its first span fetch.
    """
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
            "Without it, the Gemini call emits no spans, the 'travel-planner-agent' "
            "project never gets created in Phoenix, and 'nengok run' will 404. "
            'Reinstall with: pip install -e ".[dev,phoenix,gemini]"'
        ) from exc

    tracer_provider = register(project_name=PHOENIX_PROJECT_NAME, auto_instrument=True)

    # `auto_instrument=True` relies on package metadata to pick up
    # openinference-instrumentation-google-genai, which has been flaky when
    # the genai client is imported lazily inside build_itinerary. The
    # explicit instrument() call guarantees the LLM span shows up in Phoenix.
    instrumentor = GoogleGenAIInstrumentor()
    if not instrumentor.is_instrumented_by_opentelemetry:
        instrumentor.instrument(tracer_provider=tracer_provider)


if __name__ == "__main__":  # pragma: no cover
    main()
