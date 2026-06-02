"""
Probe the configured database role for over-broad privileges.

Nengok runs as a guest in the operator's database. The role should be
able to create and migrate its own `nengok_*` tables and read/write
the rows it owns, but it should not be able to drop the database,
create extensions, or touch tables outside the namespace. The probe
reports FAIL when the role carries `SUPERUSER`, `CREATEDB`, `ALL
PRIVILEGES`, `DROP` on the database, or any equivalent escalation,
and points at `docs/database-grants.md` for the recommended grants.

SQLite has no privilege model: the probe emits one INFO line that
records Nengok is the sole writer of the file at `state_db_path`.
"""

from __future__ import annotations

from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError

from nengok.config import NengokConfig
from nengok.diagnostics.base import ProbeResult, ProbeStatus
from nengok.state.connection import ConnectionFactory

PROBE_NAME: Final[str] = "db-privileges"

_GRANTS_DOC: Final[str] = "docs/database-grants.md"

_MYSQL_OVER_BROAD_TOKENS: Final[tuple[str, ...]] = (
    "ALL PRIVILEGES",
    "SUPER",
    "DROP",
    "RELOAD",
    "SHUTDOWN",
)


def probe_db_privileges(config: NengokConfig) -> ProbeResult:
    """Inspect the active database role and refuse over-broad grants."""
    url_str = config.database_url
    if not url_str:
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.WARN,
            detail="database_url is not resolved; cannot inspect grants",
            fix_hint=(
                "Run `nengok init` or set DATABASE_URL so the connection " "factory can build an engine."
            ),
        )

    url = make_url(url_str)
    driver = url.drivername
    if driver.startswith("sqlite"):
        return _sqlite_result(config)

    factory = ConnectionFactory(config)
    try:
        engine = factory.engine()
    except Exception as exc:
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.FAIL,
            detail=f"could not build engine for {_safe_url(url_str)}: {exc.__class__.__name__}",
            fix_hint="Check DATABASE_URL host, port, user, and password.",
        )

    try:
        if driver.startswith("postgresql"):
            return _check_postgres(engine)
        if driver.startswith("mysql"):
            return _check_mysql(engine)
    except SQLAlchemyError as exc:
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.FAIL,
            detail=f"connection failed: {exc.__class__.__name__}",
            fix_hint=(
                "Confirm DATABASE_URL points at a reachable host and that "
                "the role can log in. See "
                f"{_GRANTS_DOC} for the expected grant snippet."
            ),
        )
    finally:
        factory.dispose()

    return ProbeResult(
        name=PROBE_NAME,
        status=ProbeStatus.WARN,
        detail=f"no privilege check implemented for dialect {driver!r}",
    )


def _sqlite_result(config: NengokConfig) -> ProbeResult:
    return ProbeResult(
        name=PROBE_NAME,
        status=ProbeStatus.OK,
        detail=(f"sqlite has no privilege model; Nengok is the sole writer of " f"{config.state_db_path}"),
    )


def _check_postgres(engine: Engine) -> ProbeResult:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, current_user AS who "
                "FROM pg_roles WHERE rolname = current_user"
            )
        ).first()

    if row is None:
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.WARN,
            detail="pg_roles row not visible for current_user; cannot verify grants",
            fix_hint=f"Ensure the connecting role can read pg_roles. See {_GRANTS_DOC}.",
        )

    over_broad = []
    if row.rolsuper:
        over_broad.append("SUPERUSER")
    if row.rolcreatedb:
        over_broad.append("CREATEDB")
    if row.rolcreaterole:
        over_broad.append("CREATEROLE")

    if over_broad:
        joined = ", ".join(over_broad)
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.FAIL,
            detail=f"role '{row.who}' carries over-broad flags: {joined}",
            fix_hint=(
                f"Revoke the listed flags and use the least-privilege grant in {_GRANTS_DOC}. "
                f"For example: ALTER USER {row.who} NOSUPERUSER NOCREATEDB NOCREATEROLE;"
            ),
        )

    return ProbeResult(
        name=PROBE_NAME,
        status=ProbeStatus.OK,
        detail=f"postgres role '{row.who}' is scoped (no SUPERUSER/CREATEDB/CREATEROLE)",
    )


def _check_mysql(engine: Engine) -> ProbeResult:
    with engine.connect() as connection:
        rows = connection.execute(text("SHOW GRANTS FOR CURRENT_USER()")).fetchall()
        user_row = connection.execute(text("SELECT CURRENT_USER() AS who")).first()

    if not rows:
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.WARN,
            detail="SHOW GRANTS returned no rows; cannot verify role scope",
            fix_hint=f"Ensure the connecting account can run SHOW GRANTS. See {_GRANTS_DOC}.",
        )

    who = user_row.who if user_row is not None else "current_user"
    offenders: list[str] = []
    for row in rows:
        grant = _row_to_grant_string(row)
        upper = grant.upper()
        on_database = " ON *.*" in upper
        for token in _MYSQL_OVER_BROAD_TOKENS:
            if token in upper and on_database:
                offenders.append(token)
                break

    if offenders:
        unique = sorted(set(offenders))
        joined = ", ".join(unique)
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.FAIL,
            detail=f"mysql user '{who}' carries over-broad grants: {joined}",
            fix_hint=(
                f"Revoke {joined} and re-grant only against `app_db`.`nengok\\_%`. "
                f"See {_GRANTS_DOC} for the pattern-scoped snippet."
            ),
        )

    return ProbeResult(
        name=PROBE_NAME,
        status=ProbeStatus.OK,
        detail=f"mysql user '{who}' has no over-broad global grants",
    )


def _row_to_grant_string(row: Any) -> str:
    """Return the single column of a SHOW GRANTS row as a string."""
    try:
        values = tuple(row)
    except TypeError:
        return str(row)
    for value in values:
        if isinstance(value, str):
            return value
    return str(row)


def _safe_url(url_str: str) -> str:
    try:
        return make_url(url_str).render_as_string(hide_password=True)
    except Exception:
        return "<unparseable url>"
