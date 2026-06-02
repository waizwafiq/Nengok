# Configuration reference

Nengok reads configuration from three places, in order of precedence:

1. Process environment variables (`DATABASE_URL`, `GOOGLE_API_KEY`, `PHOENIX_BASE_URL`, ...).
2. The TOML file at `~/.nengok/config.toml`.
3. Hardcoded defaults compiled into [nengok/config.py](../nengok/config.py).

Constructor overrides on `NengokConfig.load(...)` win over all three when the SDK is embedded as a library. `nengok init` writes the TOML, `nengok config show` renders the resolved values with secrets masked.

This page covers the database settings landed in Phase 14. The full configuration walkthrough (Phoenix wiring, Gemini models, redaction, dashboard auth, notifiers) lives in the broader docs tree and cross-links back here for the database story.

Operators who run Nengok over SSH and would rather approve fixes from the terminal can launch the Textual TUI via `nengok review`. Install it as `pip install "nengok[tui]"` and see [docs/tui-review.md](tui-review.md) for keybindings, the audit-log contract (every TUI decision is recorded with `source='tui'`), and screenshots.

## State backend selection

By default a fresh `pip install nengok && nengok run` writes cluster state to `~/.nengok/state.db` (SQLite). No docker, no `DATABASE_URL`, no wizard step. The default is intentional: every command in the README quickstart works on a laptop with nothing else installed.

Pointing state at a database you already run is one environment variable away. Set `DATABASE_URL` and re-run `nengok init` (or restart `nengok run`). The TOML key `database_url` accepts the same value if you prefer to keep it off the shell environment, and the env var wins when both are present.

```bash
# SQLite, the zero-setup default. No DATABASE_URL needed.
nengok run

# Postgres via the recommended psycopg 3 driver.
export DATABASE_URL="postgresql+psycopg://nengok:secret@db.internal/nengok"
nengok db migrate
nengok run

# MySQL via PyMySQL.
export DATABASE_URL="mysql+pymysql://nengok:secret@db.internal/nengok"
nengok db migrate
nengok run
```

## Supported dialect matrix

| Dialect (SQLAlchemy URL prefix) | Driver | Typical use |
|---|---|---|
| `sqlite` | stdlib | Default. Single-process, single-machine. |
| `postgresql` or `postgresql+psycopg` | [psycopg 3](https://www.psycopg.org/psycopg3/) | Multi-pod deploys, shared Cloud SQL. |
| `mysql` or `mysql+pymysql` | [PyMySQL](https://pypi.org/project/PyMySQL/) | When the operator already runs MySQL. |

Anything outside that set is rejected at config-load with a `ConfigError`, so a typo in the driver name surfaces before the orchestrator starts. The canonical set lives in `SUPPORTED_DATABASE_DIALECTS` inside [nengok/config.py](../nengok/config.py).

MongoDB and other document stores are not supported. The schema is foreign-key heavy and the dashboard aggregations are SQL, so Nengok would either have to reimplement joins in application code or ship a degraded dashboard. Neither trade-off is on the v0.1 roadmap.

## Database-related settings

| Key (TOML) | Env var | Default | What it controls |
|---|---|---|---|
| `database_url` | `DATABASE_URL` | `sqlite:///~/.nengok/state.db` | Backend selection. Env wins over TOML. |
| `database_allow_plaintext` | `NENGOK_DATABASE_ALLOW_PLAINTEXT` | `false` | Skip the TLS rewrite for non-loopback hosts. Internal test networks only. |
| `database_schema` | `NENGOK_DATABASE_SCHEMA` | unset (`public` on Postgres) | Postgres-only. Confines every Nengok table and the Alembic bookkeeping to the named schema. |

TLS posture is handled automatically. For non-loopback Postgres URLs without an explicit `sslmode`, `ConnectionFactory` appends `sslmode=require`; MySQL gets the PyMySQL `ssl=true` equivalent; loopback hosts are left alone. Setting `database_allow_plaintext = true` skips the rewrite and logs a WARNING that names the host on every startup, so a misconfigured production deployment is loud rather than silent.

The engine is built once per process with `pool_size=5` and `max_overflow=5`, so Nengok holds at most ten connections at peak against a database it shares with your application.

## Table namespace

Every Nengok table starts with the `nengok_` prefix (`nengok_clusters`, `nengok_approvals`, `nengok_experiments`, `nengok_cycles`, `nengok_seen_spans`, `nengok_approval_audit`). Alembic's own bookkeeping is namespaced too (`nengok_alembic_version`) so Nengok does not collide with the operator's existing schema or with their own `alembic_version` table when `DATABASE_URL` points at a database it shares with their application. The CI linter at [tests/test_migration_namespace.py](../tests/test_migration_namespace.py) rejects any migration that creates, renames, drops, or `op.execute`s DDL touching a table outside that prefix.

## Least-privilege grants

The Nengok role does not need superuser, `CREATE DATABASE`, or `DROP DATABASE` rights. The dialect-specific least-privilege snippets, the Postgres `database_schema` isolation trade-off, the connection pool sizing, and the explicit backup contract (Nengok does not back up your database; operators own durability and recovery) all live in [docs/database-grants.md](database-grants.md). `nengok doctor` runs the privilege probe at startup and refuses to launch when the role holds over-broad grants.

## Migrations

Schema lives in [nengok/state/alembic/versions/](../nengok/state/alembic/versions/) as Alembic revisions written with `op.create_table(...)` and dialect-portable types (`sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')` for JSON columns, `sa.DateTime(timezone=True)` for timestamps), so the same revision applies cleanly on SQLite, Postgres, and MySQL. The store calls `alembic upgrade head` on first connect.

Three CLI helpers wrap the migrator: `nengok db migrate` runs `alembic upgrade head`, `nengok db status` lists every packaged revision and marks the live one, and `nengok db check` exits 1 when the live revision does not match the packaged head (a good CI gate for the state package).

## Verifying the resolved configuration

`nengok config show` prints every resolved value with secrets masked, so the output is safe to paste into a support ticket. `DATABASE_URL` renders as `postgresql://user:****@host:5432/db`, API keys render as `prefix****suffix`. Every Nengok process also writes one INFO line on startup that names the version, the config path actually read, the redactor state, and the Phoenix base URL.
