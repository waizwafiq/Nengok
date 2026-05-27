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


SAMPLE_GEMINI_KEY = "AIzaSyD1234567890abcdefghijklmnopqrstuvwx"
SAMPLE_BEARER = "abc123xyzdef456"
SAMPLE_PHRASE = "hunter2-very-long"
SAMPLE_OPAQUE = "tok_9F8E7D6C5B4A39281"


@pytest.mark.parametrize(
    ("template", "leak"),
    [
        (f"api_key={SAMPLE_GEMINI_KEY}", SAMPLE_GEMINI_KEY),
        (f"api-key: {SAMPLE_GEMINI_KEY}", SAMPLE_GEMINI_KEY),
        (f"API_KEY = {SAMPLE_GEMINI_KEY}", SAMPLE_GEMINI_KEY),
        (f"token={SAMPLE_OPAQUE}", SAMPLE_OPAQUE),
        (f"secret={SAMPLE_PHRASE}", SAMPLE_PHRASE),
        (f"password={SAMPLE_PHRASE}", SAMPLE_PHRASE),
        (f"authorization=Bearer {SAMPLE_BEARER}", SAMPLE_BEARER),
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
    logger.info("upstream call %s", f"api_key={SAMPLE_GEMINI_KEY}")

    message = _last_message(json_handler)
    assert SAMPLE_GEMINI_KEY not in message
    assert "api_key=<redacted>" in message


def test_filter_keeps_non_secret_messages_untouched(json_handler: io.StringIO) -> None:
    logger = get_logger("nengok.scrubber")
    logger.info("clustered 12 spans into 3 groups")

    message = _last_message(json_handler)
    assert message == "clustered 12 spans into 3 groups"


def test_filter_is_case_insensitive(json_handler: io.StringIO) -> None:
    logger = get_logger("nengok.scrubber")
    logger.info(f"AUTHORIZATION = Bearer {SAMPLE_BEARER}")

    message = _last_message(json_handler)
    assert SAMPLE_BEARER not in message
    assert "AUTHORIZATION=<redacted>" in message
