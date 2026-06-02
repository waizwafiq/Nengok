"""
A 45-second Gemini timeout inside an open transaction would hold a row
lock against the operator's pool. The guard catches the call at the
source: `call_gemini()` raises `RuntimeError` when the current task is
inside `ConnectionFactory.begin()`. The tests below cover the happy
path (outside any transaction), the guarded path (inside `begin()`),
and the regression case where a code path forgets to close the
transaction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nengok.config import NengokConfig
from nengok.state.connection import ConnectionFactory, in_transaction
from nengok.utils.gemini import call_gemini


class _FakeClientNoop:
    """Stand-in for a Gemini client; the guard fires before reaching this."""

    class models:
        @staticmethod
        def generate_content(**_kwargs: Any) -> Any:
            class _Resp:
                text = "ok"

                class usage_metadata:
                    prompt_token_count = 1
                    candidates_token_count = 1

            return _Resp()


@pytest.fixture
def factory(tmp_path: Path) -> ConnectionFactory:
    config = NengokConfig(
        phoenix_base_url="http://localhost:6006",
        google_api_key="ai-studio-test-key",
        project_identifier="test-project",
        state_db_path=tmp_path / "state.db",
        database_url=f"sqlite:///{(tmp_path / 'state.db').as_posix()}",
    )
    return ConnectionFactory(config)


def test_call_gemini_succeeds_outside_transaction(factory: ConnectionFactory) -> None:
    assert in_transaction() is False
    result = call_gemini(
        _FakeClientNoop(),
        model="gemini-test",
        contents="hello",
    )
    assert result == "ok"
    factory.dispose()


def test_call_gemini_raises_inside_begin(factory: ConnectionFactory) -> None:
    with factory.begin():
        assert in_transaction() is True
        with pytest.raises(RuntimeError, match="inside a database transaction"):
            call_gemini(
                _FakeClientNoop(),
                model="gemini-test",
                contents="hello",
            )
    factory.dispose()


def test_transaction_flag_resets_after_begin_exits(factory: ConnectionFactory) -> None:
    with factory.begin():
        assert in_transaction() is True
    assert in_transaction() is False
    call_gemini(_FakeClientNoop(), model="gemini-test", contents="hello")
    factory.dispose()


def test_transaction_flag_resets_after_exception(factory: ConnectionFactory) -> None:
    """Regression: a code path that raises inside `begin()` still resets the flag."""
    try:
        with factory.begin():
            raise ValueError("simulated failure inside the transaction")
    except ValueError:
        pass
    assert in_transaction() is False
    call_gemini(_FakeClientNoop(), model="gemini-test", contents="hello")
    factory.dispose()
