# Database grants and isolation

Nengok runs as a guest in the operator's database. Every table it
creates starts with the `nengok_` prefix (including Alembic's
bookkeeping at `nengok_alembic_version`) so the SDK cannot stamp ids
over a table the operator already owns. This file documents the
least-privilege grant story per dialect, the optional Postgres
schema isolation knob, the connection pool sizing, and the backup
contract.

## Postgres: least-privilege grant snippet

The Nengok role needs to create and migrate its own tables inside
the configured database, plus read/write the rows it owns. It must
not be allowed to drop the database, create extensions, or touch
tables outside the `nengok_` prefix. The snippet below provisions
exactly that:

```sql
CREATE USER nengok_runtime WITH PASSWORD '<set-a-strong-one>';

GRANT CONNECT ON DATABASE app_db TO nengok_runtime;
GRANT CREATE, USAGE ON SCHEMA public TO nengok_runtime;

GRANT SELECT, INSERT, UPDATE, DELETE
    ON ALL TABLES IN SCHEMA public TO nengok_runtime;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nengok_runtime;
```

Do NOT grant `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `ALL PRIVILEGES`,
or write access to tables outside the `nengok_*` prefix. The
`nengok doctor` privilege probe inspects the role at runtime and
fails the install when any of those flags are set.

If you would rather audit every Nengok object through a single
schema, see the Optional Postgres schema isolation section below.

## MySQL: least-privilege grant snippet

MySQL has no real schema-vs-database distinction, so the grant is
scoped to the application database and pattern-matched on the
`nengok_` prefix. The pattern grant means new revisions land with
the right privileges without re-running `GRANT`.

```sql
CREATE USER 'nengok_runtime'@'%' IDENTIFIED BY '<set-a-strong-one>';

GRANT CREATE, ALTER, INDEX, REFERENCES,
      INSERT, UPDATE, DELETE, SELECT
    ON `app_db`.`nengok\_%` TO 'nengok_runtime'@'%';

FLUSH PRIVILEGES;
```

Do NOT grant `ALL PRIVILEGES`, `SUPER`, `DROP` on the database
itself, `RELOAD`, or `SHUTDOWN`. The `nengok doctor` privilege
probe runs `SHOW GRANTS FOR CURRENT_USER()` and fails the install
when any of those flags appear.

## SQLite

SQLite has no privilege model. The file at `~/.nengok/state.db`
(or wherever `DATABASE_URL` points) is owned and written by the
process that runs Nengok. The doctor probe emits one INFO line on
SQLite installs to record that Nengok is the sole writer.

## Optional Postgres schema isolation

Set `database_schema = "nengok"` (or any other schema name) in
`~/.nengok/config.toml`, or export `NENGOK_DATABASE_SCHEMA=nengok`,
to route every Nengok table and the Alembic bookkeeping table into
a dedicated Postgres schema rather than `public`. SQLite ignores the
setting (the dialect has no schema concept). MySQL treats schemas as
databases; pointing `database_schema` at a separate MySQL database is
not the supported path, route `DATABASE_URL` at that database instead.

The trade-off is operational rather than functional. Schema isolation
makes the Nengok footprint trivial to audit (`\dn` followed by
`\dt nengok.*` shows everything in one place) and trivial to revoke
(`DROP SCHEMA nengok CASCADE`). The cost is one extra grant step on
provisioning: the Nengok role needs `USAGE` on the schema in addition
to the standard CRUD grants. For Postgres:

```sql
CREATE SCHEMA IF NOT EXISTS nengok;
GRANT USAGE, CREATE ON SCHEMA nengok TO nengok_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA nengok TO nengok_runtime;
ALTER DEFAULT PRIVILEGES IN SCHEMA nengok
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nengok_runtime;
```

The schema must exist before `nengok db migrate` runs; Alembic does
not create it. Leaving `database_schema` unset keeps Nengok in the
default search path with no extra grant required.

## Connection pool sizing

`ConnectionFactory` builds one SQLAlchemy engine per process with
`pool_size=5` and `max_overflow=5`, so Nengok holds at most ten
connections at peak against whatever pool you share. Operators
sharing a database with their own application should size the
upstream pool with that ceiling in mind. The pool recycles every
1800 seconds and pre-pings each checkout so a connection idled out
by a proxy gets discarded before the next query runs.

SQLite is single-file and bypasses pool sizing; the file is opened
fresh per process and WAL mode keeps reads non-blocking against a
single writer.

## TLS posture

For non-loopback Postgres URLs without an `sslmode` query parameter,
`ConnectionFactory` appends `sslmode=require` so the connection
fails closed on a server that does not present TLS. For MySQL the
PyMySQL equivalent (`ssl={"ssl": True}`) is enabled. SQLite is a
local file and has no network surface to encrypt.

Operators on an internal-only test network can opt out by setting
`database_allow_plaintext = true` in `~/.nengok/config.toml` (or
`NENGOK_DATABASE_ALLOW_PLAINTEXT=1`). Nengok logs a WARNING that
names the host on every startup with the opt-out active, so a
misconfigured production deployment is loud rather than silent.

## Long-running transactions and Gemini

Nengok never calls Gemini from inside an open transaction. The
`ConnectionFactory.begin()` wrapper sets a process-local flag and
`call_gemini()` raises at the call site if the flag is true. The
reason is operational: a 45-second Gemini timeout inside
`with engine.begin():` would hold a row lock against the operator's
pool for that full window. Code paths that need both must close the
transaction, call Gemini, then open a new transaction for the
result.

## Nengok does not back up your database

Nengok owns no backup story. Durability, point-in-time recovery,
and disaster recovery for the rows under `nengok_*` are the
operator's responsibility, on the same plan that protects the rest
of the database. The audit export at `nengok export` writes a
JSON or CSV snapshot of the bookkeeping rows, but that is an audit
artifact, not a backup target. It does not contain experiment
per-case payloads, artifact contents, or schema state.

For the hosted Cloud Run demo, Cloud SQL automated backups cover
the Nengok rows because the SDK shares the application database.
For self-hosted setups, follow your dialect's official guidance:

- Postgres: <https://www.postgresql.org/docs/current/backup.html>
- MySQL: <https://dev.mysql.com/doc/refman/8.0/en/backup-and-recovery.html>
- SQLite: <https://www.sqlite.org/backup.html>
