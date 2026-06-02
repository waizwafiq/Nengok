"""
Engine and connection management for the Nengok state store.

The factory accepts a `NengokConfig`, builds one SQLAlchemy `Engine`
sized for a guest tenant (10 connections at peak), and hands out
`Connection` context managers. Every other module in `state/` reads
through this layer so the dialect-portable migrations stay portable.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.engine.url import URL
from sqlalchemy.pool import ConnectionPoolEntry

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

    from nengok.config import NengokConfig

logger = logging.getLogger(__name__)

DEFAULT_POOL_SIZE = 5
DEFAULT_MAX_OVERFLOW = 5
DEFAULT_POOL_RECYCLE_SECONDS = 1800

_LOOPBACK_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1", ""})

_in_transaction: ContextVar[bool] = ContextVar("nengok_in_transaction", default=False)


def in_transaction() -> bool:
    """Return True if the current task is inside `ConnectionFactory.begin()`."""
    return _in_transaction.get()


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

    @contextmanager
    def begin(self) -> Iterator[Connection]:
        """
        Open a transactional connection and flag the task as in-transaction.

        Code inside the `with` block can call `connection.execute(...)` for
        writes; the transaction commits on exit and rolls back on exception.
        `call_gemini()` raises if invoked under this flag because a 45s
        Gemini timeout inside an open transaction would hold a row lock
        against the operator's pool.
        """
        token = _in_transaction.set(True)
        try:
            with self.engine().begin() as conn:
                yield conn
        finally:
            _in_transaction.reset(token)

    def _build_engine(self) -> Engine:
        url_str = self._config.database_url
        if not url_str:
            raise RuntimeError(
                "ConnectionFactory requires NengokConfig.database_url to be resolved. "
                "Call NengokConfig.load() so the env/toml/sqlite default resolution runs."
            )
        url = make_url(url_str)
        if url.drivername.startswith("sqlite"):
            logger.info("SQLite: local file (no network); state at %s", url.database)
            engine = create_engine(
                url,
                pool_pre_ping=True,
                future=True,
            )
            _attach_sqlite_pragmas(engine)
            return engine

        url = _apply_tls_posture(
            url,
            allow_plaintext=bool(getattr(self._config, "database_allow_plaintext", False)),
        )
        return create_engine(
            url,
            pool_size=DEFAULT_POOL_SIZE,
            max_overflow=DEFAULT_MAX_OVERFLOW,
            pool_pre_ping=True,
            pool_recycle=DEFAULT_POOL_RECYCLE_SECONDS,
            future=True,
        )


def _is_loopback(host: str | None) -> bool:
    if host is None:
        return True
    return host.lower() in _LOOPBACK_HOSTS


def _apply_tls_posture(url: URL, *, allow_plaintext: bool) -> URL:
    """
    Append the dialect-appropriate TLS hint when the URL targets a remote host.

    For Postgres the hint is `sslmode=require`; for MySQL the equivalent is
    routed through PyMySQL's `ssl` query parameter. The function leaves the
    URL alone when the caller already set an `sslmode` / `ssl` parameter,
    when the host is a loopback address, or when the operator opted into
    plaintext via `database_allow_plaintext`.
    """
    host = url.host
    driver = url.drivername
    if _is_loopback(host):
        logger.info("%s TLS: loopback host (%s); no rewrite applied", driver, host or "<none>")
        return url

    if allow_plaintext:
        logger.warning(
            "%s plaintext connection enabled for host '%s' "
            "via database_allow_plaintext; not appending TLS hint",
            driver,
            host,
        )
        return url

    query = dict(url.query)
    if driver.startswith("postgresql"):
        if any(key.lower() == "sslmode" for key in query):
            logger.info("Postgres TLS: existing sslmode preserved for host '%s'", host)
            return url
        query["sslmode"] = "require"
        logger.info("Postgres TLS: require (host '%s')", host)
        return url.set(query=query)

    if driver.startswith("mysql"):
        if any(key.lower() in {"ssl", "ssl_disabled", "ssl_ca", "ssl_verify_cert"} for key in query):
            logger.info("MySQL TLS: existing ssl parameter preserved for host '%s'", host)
            return url
        query["ssl"] = "true"
        logger.info("MySQL TLS: enabled (host '%s')", host)
        return url.set(query=query)

    logger.info("TLS: %s dialect not handled; URL left unchanged", driver)
    return url


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
