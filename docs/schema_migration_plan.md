# Schema Migration Discipline Plan

Second Order currently uses SQLite with code-managed schema creation and small `ALTER TABLE` upgrades. That is workable while the archive is local and small, but hand-rolled alters become risky as the app gains more saved analyses, mover records, registry state, and market snapshots.

## Why Hand-Rolled Alters Are Risky

- They are easy to run twice unless every migration is idempotent.
- They can hide partial failures when one column/table change succeeds and the next fails.
- They make it hard to know which archive version a local database is on.
- They often lack rollback notes, so recovering a broken local archive becomes guesswork.
- They can drift between developer machines, CI fixtures, and user archives.

## When To Introduce Migrations

Use the current lightweight path only for tiny additive changes that are covered by tests and safe to re-run.

Introduce a migration table or Alembic when any of these become true:

- A schema change modifies existing data or backfills derived values.
- A change renames, drops, or splits a table/column.
- Multiple database files must stay compatible across app versions.
- Migration order matters.
- The archive becomes important enough that restore drills and rollback notes are required.

A simple `schema_migrations` table is enough for the next step. Alembic becomes worth it once migrations are frequent, branching, or need richer tooling.

## Future DB Change Rules

For every future database schema change:

1. Assign a schema version or migration id.
2. Add a migration script or clearly isolated migration function.
3. Take an archive backup before running the migration on a real local DB.
4. Include a rollback note, even if rollback means "restore backup."
5. Add tests for fresh database creation and upgrade from the prior shape.
6. Keep migrations idempotent where possible.
7. Do not silently rewrite or discard archive records.

This is a plan only. No Alembic setup is being implemented yet.
