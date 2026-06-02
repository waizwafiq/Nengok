"""
Regression: a DATABASE_URL password must never reach a log or paste buffer.

The check forces a SQLAlchemy connection failure with a sentinel
password embedded in the URL, then asserts the sentinel does not
appear in any captured `caplog` record, the exception's `__str__`,
the redacted `nengok config show` output, or a logger.info call that
includes the URL verbatim.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.exc import SQLAlchemyError

from nengok.cli_helpers import format_config_for_display
from nengok.config import NengokConfig
from nengok.state.connection import ConnectionFactory
from nengok.utils.logging import configure_logging, get_logger

SENTINEL_PASSWORD = "s3cret-canary-9b3f"


@pytest.fixture
def base_config(tmp_path: Path) -> NengokConfig:
    return NengokConfig(
        phoenix_base_url="http://localhost:6006",
        google_api_key="ai-studio-test-key",
        project_identifier="test-project",
        state_db_path=tmp_path / "state.db",
        database_url=(f"postgresql+psycopg://nengok:{SENTINEL_PASSWORD}@no-such-host.invalid:5432/app"),
    )


@pytest.fixture
def json_log_buffer() -> Iterator[io.StringIO]:
    buffer = io.StringIO()
    root = logging.getLogger()
    prior_handlers = root.handlers[:]
    prior_level = root.level

    configure_logging(json_format=True, level="DEBUG")
    handler = root.handlers[0]
    handler.stream = buffer

    try:
        yield buffer
    finally:
        root.handlers = prior_handlers
        root.setLevel(prior_level)


def test_sentinel_password_does_not_leak_through_logger(
    base_config: NengokConfig, json_log_buffer: io.StringIO
) -> None:
    logger = get_logger("nengok.test.url")
    logger.info("connecting to %s", base_config.database_url)

    output = json_log_buffer.getvalue()
    for line in output.splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        assert SENTINEL_PASSWORD not in record["message"], record
    assert SENTINEL_PASSWORD not in output


def test_sentinel_password_does_not_leak_through_format_config_for_display(
    base_config: NengokConfig,
) -> None:
    rendered = format_config_for_display(base_config)
    assert SENTINEL_PASSWORD not in rendered
    assert "***" in rendered or "<redacted>" in rendered or "postgresql" not in rendered


def test_sentinel_password_does_not_leak_through_connection_failure(
    base_config: NengokConfig, caplog: pytest.LogCaptureFixture
) -> None:
    config = replace(
        base_config,
        database_url=(f"postgresql+psycopg://nengok:{SENTINEL_PASSWORD}@no-such-host.invalid:5432/app"),
    )
    factory = ConnectionFactory(config)

    captured_exc_str: str | None = None
    try:
        with caplog.at_level(logging.DEBUG):
            with factory.connection() as connection:
                connection.execute("SELECT 1")  # pragma: no cover
    except SQLAlchemyError as exc:
        captured_exc_str = str(exc)
    except Exception as exc:
        captured_exc_str = str(exc)
    finally:
        factory.dispose()

    assert captured_exc_str is not None, "expected a connection failure to inspect"
    assert SENTINEL_PASSWORD not in captured_exc_str

    for record in caplog.records:
        assert SENTINEL_PASSWORD not in record.getMessage(), record
        if record.exc_text:
            assert SENTINEL_PASSWORD not in record.exc_text
