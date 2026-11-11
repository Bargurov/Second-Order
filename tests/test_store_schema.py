"""Store schemas 1-4: explicit migration, untouched rows, read-only reads, foreign-database rejection."""
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from second_order.evaluation import evaluate
from second_order.store import (SCHEMA_1_SQL, SCHEMA_1_TABLES, SCHEMA_2_SQL, SCHEMA_2_TABLES, SCHEMA_3_SQL,
                                SCHEMA_3_TABLES, SCHEMA_4_TABLES, append_only_triggers, connect_read_only, freeze,
                                freeze_with_action, migrate_store, open_store, read_evaluations, record_assessment,
                                save_evaluation, store_schema, user_tables)
from fred_fixtures import FakeFred, datasets
from store_records import stored_before_policy_b
from test_core import START, hypothesis, series, snapshot
from test_daily import cmt_hypothesis, ny
from test_fred import run_import

ROOT = Path(__file__).resolve().parent.parent


def schema_1_store(path: Path) -> None:
    """A store exactly as written before schema 2, holding one hypothesis and one evaluation."""
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA_1_SQL + append_only_triggers(sorted(SCHEMA_1_TABLES)))
    hyp, now = hypothesis(), START + timedelta(days=800)
    identity = freeze(connection, hyp, now)
    save_evaluation(connection, identity, evaluate(hyp, {"yield:us10y": series()}, START + timedelta(days=700)), now)
    connection.close()


def schema_2_store(path: Path) -> dict:
    """A store exactly as schema 2 wrote it, holding a FRED snapshot and a hypothesis bound to it. Returns the IDs."""
    connection = sqlite3.connect(path)
    connection.executescript("BEGIN;" + SCHEMA_1_SQL + SCHEMA_2_SQL + append_only_triggers(sorted(SCHEMA_2_TABLES))
                             + "INSERT INTO store_meta VALUES ('schema_version', '2'); COMMIT;")
    connection.execute("PRAGMA foreign_keys = ON")
    baseline = run_import(connection, FakeFred(datasets(date(2025, 5, 30)), date(2025, 6, 2)), date(2025, 6, 2),
                          START.replace(year=2025, month=6, day=2, hour=22))["snapshot_id"]
    frozen = ny(2025, 6, 3, 9, 30)
    identity = stored_before_policy_b(connection, cmt_hypothesis(ny(2025, 6, 3, 9), frozen), frozen, baseline)
    connection.close()
    return {"baseline": baseline, "hypothesis": identity}


def rows(path: Path, tables=SCHEMA_1_TABLES) -> dict:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return {table: list(connection.execute(f"SELECT * FROM {table} ORDER BY rowid")) for table in tables}
    finally:
        connection.close()


class StoreSchemaTests(unittest.TestCase):
    def test_new_store_is_schema_4_and_every_table_is_append_only(self):
        connection = open_store()
        try:
            self.assertEqual(user_tables(connection), SCHEMA_4_TABLES)
            self.assertEqual(store_schema(connection), 4)
            self.assertEqual(connection.execute("SELECT value FROM store_meta WHERE key='schema_version'").fetchone(),
                             ("4",))
            triggers = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
            for table in SCHEMA_4_TABLES:
                self.assertLessEqual({f"{table}_no_update", f"{table}_no_delete"}, triggers, table)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE store_meta SET value='3'")
        finally:
            connection.close()

    def test_schema_1_store_requires_explicit_migration_and_reads_never_migrate(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.db"
            schema_1_store(path)
            before = snapshot(Path(folder))
            with self.assertRaisesRegex(ValueError, "store migrate"):
                open_store(str(path))
            self.assertEqual(len(read_evaluations(str(path))), 1)
            self.assertEqual(snapshot(Path(folder)), before)

    def test_migration_adds_tables_preserves_rows_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.db"
            schema_1_store(path)
            original = rows(path)
            result = subprocess.run([sys.executable, "-m", "second_order", "store", "migrate", "--db", str(path)],
                                    cwd=ROOT, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["preserved_rows"], {"evaluations": 1, "hypotheses": 1})
            self.assertEqual(rows(path), original)
            connection = open_store(str(path))
            try:
                self.assertEqual(user_tables(connection), SCHEMA_4_TABLES)
                meta = dict(connection.execute("SELECT key, value FROM store_meta"))
                self.assertEqual((meta["schema_version"], meta["migrated_from_schema"]), ("4", "1"))
            finally:
                connection.close()
            before = snapshot(Path(folder))
            self.assertFalse(migrate_store(str(path))["migrated"])
            self.assertEqual(snapshot(Path(folder)), before)

    def test_a_schema_2_store_is_read_and_written_as_before_and_upgraded_only_explicitly(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "store.db"
            ids = schema_2_store(path)
            original = rows(path, SCHEMA_2_TABLES)
            before = snapshot(Path(folder))
            reader = connect_read_only(str(path))  # Reads accept schema 2 and never migrate.
            try:
                self.assertEqual(store_schema(reader), 2)
            finally:
                reader.close()
            self.assertEqual(snapshot(Path(folder)), before)
            writer = open_store(str(path))  # Existing writers keep working on schema 2 ...
            try:
                with self.assertRaisesRegex(ValueError, "no freeze-action table"):  # ... but not interface freezes.
                    freeze_with_action(writer, cmt_hypothesis(ny(2025, 6, 3, 9), ny(2025, 6, 3, 9, 30)),
                                       ny(2025, 6, 3, 9, 30), ids["baseline"], "a" * 64, {})
                self.assertEqual(store_schema(writer), 2)
            finally:
                writer.close()
            self.assertEqual(rows(path, SCHEMA_2_TABLES), original)
            result = migrate_store(str(path))
            self.assertEqual((result["migrated"], result["migrated_from_schema"]), (True, 2))
            after = rows(path, SCHEMA_4_TABLES)
            for table in SCHEMA_2_TABLES - {"store_meta"}:  # Every earlier row, hypothesis and snapshot unchanged.
                self.assertEqual(after[table], original[table], table)
            self.assertLessEqual(set(original["store_meta"]), set(after["store_meta"]))
            self.assertEqual((after["freeze_actions"], after["assessment_actions"]), ([], []))
            self.assertEqual({row[0] for row in after["hypotheses"]}, {ids["hypothesis"]})
            self.assertEqual({row[0] for row in after["market_snapshots"]}, {ids["baseline"]})
            meta = dict(after["store_meta"])
            self.assertEqual((meta["schema_version"], meta["schema_4_migrated_from_schema"]), ("2", "2"))
            moved = snapshot(Path(folder))
            self.assertFalse(migrate_store(str(path))["migrated"])  # Idempotent: nothing written again.
            self.assertEqual(snapshot(Path(folder)), moved)

    def test_a_schema_3_store_writes_as_before_refuses_assessments_and_is_upgraded_only_explicitly(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "store.db"
            connection = sqlite3.connect(path)
            connection.executescript("BEGIN;" + SCHEMA_1_SQL + SCHEMA_2_SQL + SCHEMA_3_SQL
                                     + append_only_triggers(sorted(SCHEMA_3_TABLES))
                                     + "INSERT INTO store_meta VALUES ('schema_version', '3'); COMMIT;")
            connection.close()
            writer = open_store(str(path))  # Schema 3 stays writable, freezes included ...
            try:
                self.assertEqual(store_schema(writer), 3)
                with self.assertRaisesRegex(ValueError, "upgrade it to schema 4"):  # ... but not assessments.
                    record_assessment(writer, "a" * 64, {"hypothesis_id": "a" * 64, "as_of": "2025-06-01T00:00:00+00:00"},
                                      ny(2025, 6, 2, 9), "b" * 64, {}, [])
            finally:
                writer.close()
            original = rows(path, SCHEMA_3_TABLES)
            result = migrate_store(str(path))
            self.assertEqual((result["migrated"], result["migrated_from_schema"]), (True, 3))
            after = rows(path, SCHEMA_4_TABLES)
            for table in SCHEMA_3_TABLES - {"store_meta"}:
                self.assertEqual(after[table], original[table], table)
            meta = dict(after["store_meta"])
            self.assertEqual((meta["schema_version"], meta["schema_4_migrated_from_schema"]), ("3", "3"))
            moved = snapshot(Path(folder))
            self.assertFalse(migrate_store(str(path))["migrated"])
            self.assertEqual(snapshot(Path(folder)), moved)

    def test_foreign_databases_are_refused_by_every_path_without_change(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "v1.db"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE events(id INTEGER)")
            connection.commit()
            connection.close()
            before = snapshot(Path(folder))
            for action in (migrate_store, read_evaluations, open_store):
                with self.subTest(action=action.__name__), self.assertRaises(ValueError):
                    action(str(path))
            self.assertEqual(snapshot(Path(folder)), before)
            with self.assertRaises(ValueError):
                migrate_store(str(Path(folder) / "missing.db"))
            self.assertFalse((Path(folder) / "missing.db").exists())


if __name__ == "__main__":
    unittest.main()
