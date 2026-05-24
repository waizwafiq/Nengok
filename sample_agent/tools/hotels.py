"""Mock hotels API. Toggle the intermittent timeout via `failure_modes`."""

from __future__ import annotations

import random
from typing import Any

from sample_agent.tools.failure_modes import state

TIMEOUT_RATE = 0.4


class HotelsTimeoutError(TimeoutError):
    """Raised when the mock endpoint simulates a timeout."""


def search_hotels(*, city: str, nights: int) -> list[dict[str, Any]]:
    if state().hotels_timeout and random.random() < TIMEOUT_RATE:
        raise HotelsTimeoutError(f"hotels API timed out for {city}")

    return [
        {
            "hotel_name": "Park Hyatt Tokyo",
            "city": city,
            "nights": nights,
            "price_usd_per_night": 420.0,
        },
        {
            "hotel_name": "Cerulean Tower Tokyu",
            "city": city,
            "nights": nights,
            "price_usd_per_night": 280.0,
        },
    ]
