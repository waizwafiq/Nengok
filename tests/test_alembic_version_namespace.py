"""
Guard the Nengok Alembic bookkeeping namespace.

Nengok writes its revision rows to `nengok_alembic_version` so that it
can share a database with an application that already runs Alembic on
the default `alembic_version` table. The behaviour tests at the top
exercise the upgrade flow; the static check at the bottom walks every
`context.configure(...)` and `MigrationContext.configure(...)` call
site in the SDK and refuses any call that does not pin the namespaced
table name.
"""

from __future__ import annotations

import ast
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from nengok.state.alembic_runner import (
    DEFAULT_ALEMBIC_VERSION_TABLE,
    KNOWN_NENGOK_REVISIONS,
    NENGOK_ALEMBIC_VERSION_TABLE,
    current_revision,
    upgrade_head,
)

SDK_FILES_REQUIRING_NAMESPACE: tuple[Path, ...] = (
    Path("nengok/state/alembic/env.py"),
    Path("nengok/state/alembic_runner.py"),
)


@pytest.fixture
def sqlite_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'state.db').as_posix()}")
    yield engine
    engine.dispose()


def _table_names(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_fresh_upgrade_writes_only_to_namespaced_bookkeeping(sqlite_engine: Engine) -> None:
    upgrade_head(sqlite_engine)

    tables = _table_names(sqlite_engine)
    assert NENGOK_ALEMBIC_VERSION_TABLE in tables
    assert DEFAULT_ALEMBIC_VERSION_TABLE not in tables


def test_foreign_alembic_version_is_left_untouched(sqlite_engine: Engine) -> None:
    """An operator's own Alembic bookkeeping must survive Nengok's upgrade."""
    foreign_revision = "deadbeefcafe"
    assert foreign_revision not in KNOWN_NENGOK_REVISIONS

    with sqlite_engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE alembic_version ("
                "version_num VARCHAR(32) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
        )
        conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
            {"rev": foreign_revision},
        )

    upgrade_head(sqlite_engine)

    tables = _table_names(sqlite_engine)
    assert DEFAULT_ALEMBIC_VERSION_TABLE in tables
    assert NENGOK_ALEMBIC_VERSION_TABLE in tables

    with sqlite_engine.connect() as conn:
        foreign_rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
    assert {row.version_num for row in foreign_rows} == {foreign_revision}


def test_legacy_nengok_alembic_version_is_reconciled(sqlite_engine: Engine) -> None:
    """A previous-install `alembic_version` with Nengok ids migrates into the namespace."""
    upgrade_head(sqlite_engine)
    head_revision = current_revision(sqlite_engine)
    assert head_revision in KNOWN_NENGOK_REVISIONS

    with sqlite_engine.begin() as conn:
        conn.execute(text(f"DROP TABLE {NENGOK_ALEMBIC_VERSION_TABLE}"))
        conn.execute(
            text(
                "CREATE TABLE alembic_version ("
                "version_num VARCHAR(32) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
        )
        conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
            {"rev": head_revision},
        )

    upgrade_head(sqlite_engine)

    tables = _table_names(sqlite_engine)
    assert NENGOK_ALEMBIC_VERSION_TABLE in tables
    assert DEFAULT_ALEMBIC_VERSION_TABLE not in tables
    assert current_revision(sqlite_engine) == head_revision


def test_existing_namespaced_bookkeeping_is_honored_on_next_upgrade(sqlite_engine: Engine) -> None:
    upgrade_head(sqlite_engine)
    first_revision = current_revision(sqlite_engine)

    upgrade_head(sqlite_engine)
    assert current_revision(sqlite_engine) == first_revision

    tables = _table_names(sqlite_engine)
    assert NENGOK_ALEMBIC_VERSION_TABLE in tables
    assert DEFAULT_ALEMBIC_VERSION_TABLE not in tables


def test_two_alembic_environments_coexist_in_one_sqlite_file(tmp_path: Path) -> None:
    """Hand-rolled second Alembic env keeps its `alembic_version` table."""
    db_path = tmp_path / "state.db"
    foreign_root = tmp_path / "foreign_alembic"
    foreign_versions = foreign_root / "versions"
    foreign_versions.mkdir(parents=True)
    (foreign_root / "env.py").write_text(
        textwrap.dedent(
            """
            from alembic import context
            from sqlalchemy import engine_from_config, pool

            config = context.config

            def _run(connection):
                context.configure(connection=connection)
                with context.begin_transaction():
                    context.run_migrations()

            connectable = engine_from_config(
                config.get_section(config.config_ini_section, {}),
                prefix="sqlalchemy.",
                poolclass=pool.NullPool,
            )
            with connectable.connect() as connection:
                _run(connection)
            """
        ).strip()
        + "\n"
    )
    (foreign_root / "script.py.mako").write_text(
        textwrap.dedent(
            """
            \"\"\"${message}\"\"\"
            revision = ${repr(up_revision)}
            down_revision = ${repr(down_revision)}
            branch_labels = ${repr(branch_labels)}
            depends_on = ${repr(depends_on)}

            def upgrade():
                pass

            def downgrade():
                pass
            """
        ).strip()
        + "\n"
    )
    (foreign_versions / "abc123_foreign.py").write_text(
        textwrap.dedent(
            """
            revision = "abc123_foreign"
            down_revision = None
            branch_labels = None
            depends_on = None

            def upgrade():
                pass

            def downgrade():
                pass
            """
        ).strip()
        + "\n"
    )

    foreign_cfg = Config()
    foreign_cfg.set_main_option("script_location", str(foreign_root))
    foreign_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(foreign_cfg, "head")

    nengok_engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        upgrade_head(nengok_engine)
        tables = _table_names(nengok_engine)
    finally:
        nengok_engine.dispose()

    assert DEFAULT_ALEMBIC_VERSION_TABLE in tables
    assert NENGOK_ALEMBIC_VERSION_TABLE in tables


class _ConfigureVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.offenders: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        target = self._is_configure_target(node.func)
        if target is not None:
            keywords = {kw.arg: kw.value for kw in node.keywords}
            literal = self._string_literal(keywords.get("version_table"))
            if literal != NENGOK_ALEMBIC_VERSION_TABLE and not self._has_namespaced_opts(
                keywords.get("opts")
            ):
                self.offenders.append((node.lineno, target))
        self.generic_visit(node)

    @staticmethod
    def _is_configure_target(func: ast.expr) -> str | None:
        if not isinstance(func, ast.Attribute) or func.attr != "configure":
            return None
        if isinstance(func.value, ast.Name) and func.value.id in {"context", "MigrationContext"}:
            return func.value.id
        return None

    @staticmethod
    def _string_literal(node: ast.expr | None) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name) and node.id == "NENGOK_ALEMBIC_VERSION_TABLE":
            return NENGOK_ALEMBIC_VERSION_TABLE
        return None

    def _has_namespaced_opts(self, node: ast.expr | None) -> bool:
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=False):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "version_table"
                    and self._string_literal(value) == NENGOK_ALEMBIC_VERSION_TABLE
                ):
                    return True
        return isinstance(node, ast.Name) and node.id == "opts"


def test_every_configure_call_site_pins_the_namespaced_version_table() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    offenders: list[tuple[Path, int, str]] = []
    for relative_path in SDK_FILES_REQUIRING_NAMESPACE:
        path = repo_root / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"))
        visitor = _ConfigureVisitor()
        visitor.visit(tree)
        offenders.extend((path, lineno, target) for lineno, target in visitor.offenders)
    assert offenders == [], (
        "Found context.configure / MigrationContext.configure call sites without "
        f"version_table='{NENGOK_ALEMBIC_VERSION_TABLE}': {offenders}"
    )
