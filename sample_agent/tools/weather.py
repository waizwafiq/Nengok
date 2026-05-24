"""Mock weather API. Toggle the unit-mismatch failure via `failure_modes`."""

from __future__ import annotations

from typing import Any

from sample_agent.tools.failure_modes import state


def get_forecast(*, city: str) -> dict[str, Any]:
    if state().weather_unit_mismatch:
        temperature = 18.0
        unit = "C"
    else:
        temperature = 64.4
        unit = "F"

    return {
        "city": city,
        "temperature": temperature,
        "unit": unit,
        "summary": "Partly cloudy",
    }
