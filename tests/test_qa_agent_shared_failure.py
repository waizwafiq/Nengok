"""The QA agent's flights_schema failure rides the shared mock flights API."""

from __future__ import annotations

from sample_agent.qa_agent.agent import _flight_status_snippet
from sample_agent.tools import failure_modes


def test_snippet_carries_the_drifted_departure_time() -> None:
    failure_modes.configure("none")

    snippet_id, body = _flight_status_snippet()

    assert snippet_id == "flight-status"
    assert "tool.flights.search" in body
    assert "{'hour': 14, 'minute': 30}" in body


def test_snippet_restores_the_callers_failure_toggles() -> None:
    failure_modes.configure("weather")
    try:
        _flight_status_snippet()
        active = failure_modes.state()
        assert active.weather_unit_mismatch is True
        assert active.flights_schema_drift is False
    finally:
        failure_modes.configure("none")
