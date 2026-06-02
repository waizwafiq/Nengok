"""
Static linter for Alembic revisions: stay inside the nengok_ namespace.

Every revision file under `nengok/state/alembic/versions/` is parsed
with `ast`. Any `op.create_table`, `op.drop_table`, `op.rename_table`,
or `op.execute(<str>)` that names a table outside the `nengok_` prefix
fails this test. Raw SQL that issues `DROP DATABASE`, `DROP SCHEMA`,
or `TRUNCATE` against an unprefixed table is rejected outright.

A short allowlist names the historical revisions that predate the
prefix (created the original `clusters`/`approvals`/... tables, or
performed the one-shot rename to `nengok_*`). New revisions must
comply unconditionally; CI fails any PR that adds one outside the
namespace.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

NENGOK_TABLE_PREFIX = "nengok_"

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "nengok" / "state" / "alembic" / "versions"

PRE_NAMESPACE_REVISIONS: frozenset[str] = frozenset(
    {
        "0001_initial_schema",
        "0002_rename_approval_columns",
        "0003_extend_cycle_history",
        "0004_prefix_tables_with_nengok",
    }
)

_TABLE_OPS: frozenset[str] = frozenset({"create_table", "drop_table", "rename_table"})

_FORBIDDEN_GLOBAL_DDL = re.compile(r"\b(DROP\s+DATABASE|DROP\s+SCHEMA)\b", re.IGNORECASE)
_TRUNCATE_TARGET = re.compile(
    r"\bTRUNCATE\s+(?:TABLE\s+)?[`\"]?([A-Za-z_][A-Za-z0-9_]*)[`\"]?", re.IGNORECASE
)


class _Offence:
    __slots__ = ("path", "lineno", "kind", "detail")

    def __init__(self, path: Path, lineno: int, kind: str, detail: str) -> None:
        self.path = path
        self.lineno = lineno
        self.kind = kind
        self.detail = detail

    def __repr__(self) -> str:
        return f"{self.path.name}:{self.lineno} [{self.kind}] {self.detail}"


class _NamespaceVisitor(ast.NodeVisitor):
    """Collect every op.<TABLE_OP> and op.execute(...) target that escapes the namespace."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self.offences: list[_Offence] = []

    def visit_Call(self, node: ast.Call) -> None:
        target = self._op_attr(node.func)
        if target in _TABLE_OPS:
            self._check_table_op(node, target)
        elif target == "execute":
            self._check_execute(node)
        elif target == "batch_alter_table":
            self._check_batch(node)
        self.generic_visit(node)

    @staticmethod
    def _op_attr(func: ast.expr) -> str | None:
        if not isinstance(func, ast.Attribute):
            return None
        if not (isinstance(func.value, ast.Name) and func.value.id == "op"):
            return None
        return func.attr

    def _check_table_op(self, node: ast.Call, attr: str) -> None:
        names = self._first_string_args(node, attr)
        for name in names:
            if not name.startswith(NENGOK_TABLE_PREFIX):
                self.offences.append(
                    _Offence(self._path, node.lineno, f"op.{attr}", f"unprefixed table {name!r}")
                )

    def _check_batch(self, node: ast.Call) -> None:
        if not node.args:
            return
        first = self._string_literal(node.args[0])
        if first is not None and not first.startswith(NENGOK_TABLE_PREFIX):
            self.offences.append(
                _Offence(
                    self._path,
                    node.lineno,
                    "op.batch_alter_table",
                    f"unprefixed table {first!r}",
                )
            )

    def _check_execute(self, node: ast.Call) -> None:
        if not node.args:
            return
        sql = self._string_literal(node.args[0])
        if sql is None:
            return
        if _FORBIDDEN_GLOBAL_DDL.search(sql):
            self.offences.append(
                _Offence(self._path, node.lineno, "op.execute", f"forbidden DDL in raw SQL: {sql!r}")
            )
        for match in _TRUNCATE_TARGET.finditer(sql):
            table = match.group(1)
            if not table.startswith(NENGOK_TABLE_PREFIX):
                self.offences.append(
                    _Offence(
                        self._path,
                        node.lineno,
                        "op.execute",
                        f"TRUNCATE of unprefixed table {table!r}",
                    )
                )

    @staticmethod
    def _string_literal(node: ast.expr | None) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None

    def _first_string_args(self, node: ast.Call, attr: str) -> list[str]:
        if not node.args:
            return []
        if attr == "rename_table":
            return [
                value for value in (self._string_literal(arg) for arg in node.args[:2]) if value is not None
            ]
        first = self._string_literal(node.args[0])
        return [first] if first is not None else []


def _revision_id(tree: ast.Module) -> str | None:
    """Return the literal `revision: str = "..."` assignment from a revision module."""
    for node in tree.body:
        target_name: str | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value = node.value
        elif (
            isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
        ):
            target_name = node.targets[0].id
            value = node.value
        if target_name == "revision" and isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return None


def _iter_revision_files() -> list[Path]:
    return sorted(p for p in VERSIONS_DIR.glob("*.py") if p.name != "__init__.py")


def test_versions_directory_is_discovered() -> None:
    files = _iter_revision_files()
    assert files, f"No Alembic revisions found under {VERSIONS_DIR}"


@pytest.mark.parametrize("revision_path", _iter_revision_files(), ids=lambda p: p.stem)
def test_revision_stays_in_nengok_namespace(revision_path: Path) -> None:
    tree = ast.parse(revision_path.read_text(encoding="utf-8"))
    revision_id = _revision_id(tree)
    visitor = _NamespaceVisitor(revision_path)
    visitor.visit(tree)

    if revision_id in PRE_NAMESPACE_REVISIONS:
        return

    assert visitor.offences == [], (
        f"Migration {revision_path.name} touches tables outside the "
        f"`{NENGOK_TABLE_PREFIX}` namespace or issues forbidden DDL. "
        "Nengok is a guest in the operator's database; every table it "
        "creates or alters must start with the prefix. Offences: "
        + "; ".join(repr(o) for o in visitor.offences)
    )


def _lint_source(source: str, *, path: Path | None = None) -> list[_Offence]:
    tree = ast.parse(source)
    visitor = _NamespaceVisitor(path or Path("<synthetic>"))
    visitor.visit(tree)
    return visitor.offences


def test_linter_catches_unprefixed_create_table() -> None:
    bad = "from alembic import op\n" "def upgrade():\n" "    op.create_table('clusters')\n"
    offences = _lint_source(bad)
    assert offences, "linter should reject op.create_table('clusters')"
    assert "create_table" in offences[0].kind
    assert "clusters" in offences[0].detail


def test_linter_catches_unprefixed_rename_target() -> None:
    bad = "from alembic import op\n" "def upgrade():\n" "    op.rename_table('nengok_x', 'users')\n"
    offences = _lint_source(bad)
    assert offences, "linter should reject rename target outside the namespace"
    assert "users" in offences[0].detail


def test_linter_catches_truncate_unprefixed_table() -> None:
    bad = "from alembic import op\n" "def upgrade():\n" "    op.execute('TRUNCATE customers')\n"
    offences = _lint_source(bad)
    assert offences, "linter should reject TRUNCATE of an unprefixed table"


def test_linter_catches_drop_schema_raw_sql() -> None:
    bad = "from alembic import op\n" "def upgrade():\n" "    op.execute('DROP SCHEMA public CASCADE')\n"
    offences = _lint_source(bad)
    assert offences, "linter should reject DROP SCHEMA"


def test_linter_accepts_namespaced_table_ops() -> None:
    good = (
        "from alembic import op\n"
        "def upgrade():\n"
        "    op.create_table('nengok_new_thing')\n"
        "    op.execute('TRUNCATE TABLE nengok_seen_spans')\n"
    )
    assert _lint_source(good) == []


def _scan_for_global_ddl(revision_path: Path) -> list[_Offence]:
    found: list[_Offence] = []
    tree = ast.parse(revision_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "op"
            and func.attr == "execute"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            continue
        sql = node.args[0].value
        if _FORBIDDEN_GLOBAL_DDL.search(sql):
            found.append(_Offence(revision_path, node.lineno, "op.execute", f"forbidden DDL: {sql!r}"))
    return found


def test_forbidden_global_ddl_is_rejected_for_every_revision() -> None:
    """`DROP DATABASE` / `DROP SCHEMA` are never acceptable, even in legacy migrations."""
    offences: list[_Offence] = []
    for revision_path in _iter_revision_files():
        offences.extend(_scan_for_global_ddl(revision_path))
    assert offences == [], (
        "`DROP DATABASE` and `DROP SCHEMA` are forbidden in every Alembic "
        f"revision Nengok ships: {offences}"
    )
