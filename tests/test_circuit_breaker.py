"""Per-stage circuit breaker behavior."""

from __future__ import annotations

from datetime import timedelta

from nengok.core.circuit_breaker import CircuitBreaker


def test_opens_after_threshold_consecutive_failures() -> None:
    breaker = CircuitBreaker(threshold=3, backoff_seconds=60)
    exc = RuntimeError("boom")

    assert breaker.record_failure("observer", exc) is False
    assert breaker.record_failure("observer", exc) is False
    assert breaker.record_failure("observer", exc) is True
    assert breaker.is_open
    assert breaker.open_stage == "observer"


def test_success_resets_counts() -> None:
    breaker = CircuitBreaker(threshold=3, backoff_seconds=60)
    breaker.record_failure("observer", RuntimeError("a"))
    breaker.record_failure("observer", RuntimeError("b"))
    breaker.record_success("observer")
    assert breaker.record_failure("observer", RuntimeError("c")) is False


def test_failures_are_counted_per_stage() -> None:
    breaker = CircuitBreaker(threshold=3, backoff_seconds=60)
    breaker.record_failure("observer", RuntimeError("a"))
    breaker.record_failure("diagnoser", RuntimeError("b"))
    breaker.record_failure("observer", RuntimeError("c"))

    assert not breaker.is_open
    assert breaker.record_failure("observer", RuntimeError("d")) is True
    assert breaker.open_stage == "observer"


def test_time_until_close_starts_at_backoff() -> None:
    breaker = CircuitBreaker(threshold=1, backoff_seconds=60)
    breaker.record_failure("observer", RuntimeError("a"))
    remaining = breaker.time_until_close()
    assert remaining > timedelta(seconds=55)
    assert remaining <= timedelta(seconds=60)


def test_close_clears_state() -> None:
    breaker = CircuitBreaker(threshold=1, backoff_seconds=60)
    breaker.record_failure("observer", RuntimeError("a"))
    breaker.close()
    assert not breaker.is_open
    assert breaker.open_stage is None
    assert breaker.time_until_close() == timedelta(0)


def test_recent_failures_capped_at_three() -> None:
    breaker = CircuitBreaker(threshold=10, backoff_seconds=60)
    for i in range(5):
        breaker.record_failure("observer", RuntimeError(f"e{i}"))
    failures = list(breaker.recent_failures())
    assert len(failures) == 3
    assert failures[0].message == "e2"
    assert failures[-1].message == "e4"
