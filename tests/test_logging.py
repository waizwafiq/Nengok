"""JSON logging, run_context tagging, and secret redaction."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator

import pytest

from nengok.utils.logging import configure_logging, get_logger, run_context


@pytest.fixture
def json_handler() -> Iterator[io.StringIO]:
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


@pytest.fixture
def gcp_handler() -> Iterator[io.StringIO]:
    buffer = io.StringIO()
    root = logging.getLogger()
    prior_handlers = root.handlers[:]
    prior_level = root.level

    configure_logging(log_format="gcp", level="DEBUG")
    handler = root.handlers[0]
    handler.stream = buffer

    try:
        yield buffer
    finally:
        root.handlers = prior_handlers
        root.setLevel(prior_level)


def _last_json_line(buffer: io.StringIO) -> dict[str, object]:
    lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
    return json.loads(lines[-1])


def test_json_format_includes_required_fields(json_handler: io.StringIO) -> None:
    logger = get_logger("nengok.test")
    logger.info("hello")
    record = _last_json_line(json_handler)

    assert record["message"] == "hello"
    assert record["level"] == "INFO"
    assert record["logger"] == "nengok.test"
    assert "timestamp" in record


def test_run_context_tags_records(json_handler: io.StringIO) -> None:
    logger = get_logger("nengok.test")
    with run_context(run_id="r-1", stage="observer"):
        logger.info("inside")
    logger.info("outside")

    lines = [json.loads(line) for line in json_handler.getvalue().splitlines() if line.strip()]
    inside = next(r for r in lines if r["message"] == "inside")
    outside = next(r for r in lines if r["message"] == "outside")

    assert inside["run_id"] == "r-1"
    assert inside["stage"] == "observer"
    assert outside.get("run_id") is None
    assert outside.get("stage") is None


def test_nested_context_inherits_outer_run_id(json_handler: io.StringIO) -> None:
    logger = get_logger("nengok.test")
    with run_context(run_id="cycle-1"):
        with run_context(stage="diagnoser", cluster_id="c-7"):
            logger.info("nested")

    record = _last_json_line(json_handler)
    assert record["run_id"] == "cycle-1"
    assert record["stage"] == "diagnoser"
    assert record["cluster_id"] == "c-7"


def test_redacting_filter_scrubs_api_key_in_message(json_handler: io.StringIO) -> None:
    logger = get_logger("nengok.test")
    logger.info("api_key=AIzaSyD1234567890abcdefghijklmnopqrstuvwx")

    record = _last_json_line(json_handler)
    assert "AIzaSyD" not in record["message"]
    assert "api_key=<redacted>" in record["message"]


def test_redacting_filter_scrubs_bearer_token_arg(json_handler: io.StringIO) -> None:
    logger = get_logger("nengok.test")
    logger.info("call %s", "authorization=Bearer abc123")

    record = _last_json_line(json_handler)
    assert "abc123" not in record["message"]
    assert "authorization=<redacted>" in record["message"]


def test_gcp_format_emits_severity_not_level(gcp_handler: io.StringIO) -> None:
    logger = get_logger("nengok.test")
    logger.warning("watch out")
    record = _last_json_line(gcp_handler)

    assert record["severity"] == "WARNING"
    assert record["message"] == "watch out"
    assert record["logger"] == "nengok.test"
    assert "level" not in record
    assert "levelname" not in record


def test_gcp_format_maps_info_severity(gcp_handler: io.StringIO) -> None:
    logger = get_logger("nengok.test")
    logger.info("hello")
    record = _last_json_line(gcp_handler)
    assert record["severity"] == "INFO"


def test_gcp_format_still_redacts_secrets(gcp_handler: io.StringIO) -> None:
    logger = get_logger("nengok.test")
    logger.info("token=Bearer sekret-value-123")
    record = _last_json_line(gcp_handler)
    assert "sekret-value-123" not in record["message"]
    assert "token=<redacted>" in record["message"]
