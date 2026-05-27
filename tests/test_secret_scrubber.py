"""Defense-in-depth coverage of the redacting log filter."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator

import pytest

from nengok.utils.logging import configure_logging, get_logger


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


def _last_message(buffer: io.StringIO) -> str:
    lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
    return json.loads(lines[-1])["message"]


SECRET_VALUE = "AIzaSyD1234567890abcdefghijklmnopqrstuvwx"
BEARER_VALUE = "abc123xyzdef456"
PASSWORD_VALUE = "hunter2-very-long"
COOKIE_TOKEN = "tok_9F8E7D6C5B4A39281"


@pytest.mark.parametrize(
    ("template", "leak"),
    [
        (f"api_key={SECRET_VALUE}", SECRET_VALUE),
        (f"api-key: {SECRET_VALUE}", SECRET_VALUE),
        (f"API_KEY = {SECRET_VALUE}", SECRET_VALUE),
        (f"token={COOKIE_TOKEN}", COOKIE_TOKEN),
        (f"secret={PASSWORD_VALUE}", PASSWORD_VALUE),
        (f"password={PASSWORD_VALUE}", PASSWORD_VALUE),
        (f"authorization=Bearer {BEARER_VALUE}", BEARER_VALUE),
    ],
)
def test_filter_scrubs_each_pattern(json_handler: io.StringIO, template: str, leak: str) -> None:
    logger = get_logger("nengok.scrubber")
    logger.info(template)

    message = _last_message(json_handler)
    assert leak not in message, f"raw secret leaked through filter: {message}"
    assert "<redacted>" in message


def test_filter_scrubs_value_passed_as_lazy_argument(json_handler: io.StringIO) -> None:
    logger = get_logger("nengok.scrubber")
    logger.info("upstream call %s", f"api_key={SECRET_VALUE}")

    message = _last_message(json_handler)
    assert SECRET_VALUE not in message
    assert "api_key=<redacted>" in message


def test_filter_keeps_non_secret_messages_untouched(json_handler: io.StringIO) -> None:
    logger = get_logger("nengok.scrubber")
    logger.info("clustered 12 spans into 3 groups")

    message = _last_message(json_handler)
    assert message == "clustered 12 spans into 3 groups"


def test_filter_is_case_insensitive(json_handler: io.StringIO) -> None:
    logger = get_logger("nengok.scrubber")
    logger.info(f"AUTHORIZATION = Bearer {BEARER_VALUE}")

    message = _last_message(json_handler)
    assert BEARER_VALUE not in message
    assert "AUTHORIZATION=<redacted>" in message
