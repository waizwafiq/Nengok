"""
Runtime switches for the three injectable failures in the demo agent.

Each failure is a real bug class Nengok has detected in production
agents: schema drift, unit mismatch, and intermittent timeout that
gets papered over by a hallucination.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FailureToggles:
    flights_schema_drift: bool = False
    weather_unit_mismatch: bool = False
    hotels_timeout: bool = False


_active = FailureToggles()


def configure(mode: str) -> None:
    """
    Set the active failure modes by name.

        configure("none")     # all off
        configure("flights")  # only the flights schema drift
        configure("all")      # turn every injectable failure on
    """
    global _active
    if mode == "none":
        _active = FailureToggles()
    elif mode == "flights":
        _active = FailureToggles(flights_schema_drift=True)
    elif mode == "weather":
        _active = FailureToggles(weather_unit_mismatch=True)
    elif mode == "hotels":
        _active = FailureToggles(hotels_timeout=True)
    elif mode == "all":
        _active = FailureToggles(
            flights_schema_drift=True,
            weather_unit_mismatch=True,
            hotels_timeout=True,
        )
    else:
        raise ValueError(f"Unknown failure mode: {mode!r}")


def state() -> FailureToggles:
    return _active
