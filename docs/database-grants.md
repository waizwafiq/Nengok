# Database grants and isolation

Nengok runs as a guest in the operator's database. Every table it
creates starts with the `nengok_` prefix (including Alembic's
bookkeeping at `nengok_alembic_version`) so the SDK cannot stamp ids
over a table the operator already owns. This file documents the
least-privilege grant story per dialect and the optional Postgres
schema isolation knob.

Per-dialect grant snippets and the `nengok doctor` privilege probe
land in a follow-up change and will be added below as they ship.

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
