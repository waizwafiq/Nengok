"""
Engine and connection management for the Nengok state store.

The factory accepts a `NengokConfig`, builds one SQLAlchemy `Engine`
sized for a guest tenant (10 connections at peak), and hands out
`Connection` context managers. Every other module in `state/` reads
through this layer so the dialect-portable migrations stay portable.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import ConnectionPoolEntry

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

    from nengok.config import NengokConfig

DEFAULT_POOL_SIZE = 5
DEFAULT_MAX_OVERFLOW = 5
DEFAULT_POOL_RECYCLE_SECONDS = 1800


class ConnectionFactory:
    """
    Build and cache the engine for a single Nengok process.

    The engine is created lazily on first access so importing the
    module does no I/O. `connection()` hands out a short-lived
    `Connection` for read traffic; transactional writes use the
    `begin()` wrapper from Phase 14.3.
    """

    def __init__(self, config: NengokConfig) -> None:
        self._config = config
        self._engine: Engine | None = None

    def engine(self) -> Engine:
        """Return the lazily-built engine, creating it on first call."""
        if self._engine is None:
            self._engine = self._build_engine()
        return self._engine

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        """Yield a SQLAlchemy `Connection` from the engine's pool."""
        with self.engine().connect() as conn:
            yield conn

    def dispose(self) -> None:
        """Drop the pool. Safe to call from teardown paths."""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def _build_engine(self) -> Engine:
        url_str = self._config.database_url
        if not url_str:
            raise RuntimeError(
                "ConnectionFactory requires NengokConfig.database_url to be resolved. "
                "Call NengokConfig.load() so the env/toml/sqlite default resolution runs."
            )
        url = make_url(url_str)
        if url.drivername.startswith("sqlite"):
            engine = create_engine(
                url,
                pool_pre_ping=True,
                future=True,
            )
            _attach_sqlite_pragmas(engine)
            return engine
        return create_engine(
            url,
            pool_size=DEFAULT_POOL_SIZE,
            max_overflow=DEFAULT_MAX_OVERFLOW,
            pool_pre_ping=True,
            pool_recycle=DEFAULT_POOL_RECYCLE_SECONDS,
            future=True,
        )


def _attach_sqlite_pragmas(engine: Engine) -> None:
    """Turn on WAL and foreign keys for every SQLite connection."""

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(
        dbapi_connection: Any,
        _connection_record: ConnectionPoolEntry,
    ) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.close()
