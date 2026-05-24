"""Mock flights API. Toggle the schema-drift failure via `failure_modes`."""

from __future__ import annotations

from typing import Any

from sample_agent.tools.failure_modes import state


def search_flights(*, origin: str, destination: str) -> list[dict[str, Any]]:
    departure_time: Any = "14:30"
    if state().flights_schema_drift:
        departure_time = {"hour": 14, "minute": 30}

    return [
        {
            "flight_no": "MH88",
            "origin": origin,
            "destination": destination,
            "departure_time": departure_time,
            "price_usd": 612.0,
        }
    ]
