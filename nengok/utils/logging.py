"""
Structured logging for Nengok.

We deliberately avoid a heavy logging dependency. `structlog` would be
nicer but pulling it in just for colored output isn't worth the
transitive footprint for a pip-installable SDK.
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def configure_logging(*, verbose: bool = False) -> None:
    """Idempotent root-logger setup."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for noisy in ("httpx", "httpcore", "urllib3", "openinference"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
