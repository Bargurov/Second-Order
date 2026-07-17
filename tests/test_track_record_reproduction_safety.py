"""Reproduction-safety contract for the advertised OR-rule ledger command.

The Evidence Overview reviewer guide and the research-record memo display
one canonical read-only reproduction command for the any-support OR-rule
track-record ledger (``ACCEPTED_CORPUS.orRuleRepro`` in
``frontend/src/lib/accepted-corpus.ts``).  A command presented to
reviewers as read-only must be demonstrably non-mutating.

Contract under test:

* the advertised command never calls ``db.init_db()`` (which creates a
  missing database, renames a schema-mismatched archive to ``.bak``, and
  runs ALTER TABLE migrations) — it runs the dedicated read-only report
  script over an explicit ``mode=ro`` SQLite URI connection;
* a missing source database fails clearly and is NEVER created;
* a malformed source file fails clearly and is left byte-identical;
* the source database fingerprint (SHA-256, size, mtime) and its sidecar
  inventory (no ``-wal`` / ``-shm`` / ``-journal`` / ``.bak``) are
  unchanged by a successful run — including against an "outdated"
  ``PRAGMA user_version`` that ``init_db`` would have migrated;
* output is deterministic for identical input;
* the ledger the script reports is exactly ``db.compute_track_record``'s
  aggregation (shared pure aggregator — no drift between the app ledger
  and the reviewer command);
* the script imports no provider, network, or paid module.

Every fixture here is a self-made temporary database: the canonical
suite never conditions on a local ``events.db``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402

SCRIPT = ROOT / "scripts" / "track_record_report.py"
ACCEPTED_CORPUS_TS = ROOT / "frontend" / "src" / "lib" / "accepted-corpus.ts"


def _advertised_or_rule_command() -> str:
    """The OR-rule reproduction command exactly as displayed to reviewers.

    Parsed from the tracked ``ACCEPTED_CORPUS.orRuleRepro`` constant so the
    tested command and the displayed command can never drift apart.
    Handles a single- or double-quoted literal, optionally split across
    lines / concatenated by ``+``.
    """
    text = ACCEPTED_CORPUS_TS.read_text(encoding="utf-8")
    literal = r"(?:\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')"
    m = re.search(
        rf"orRuleRepro:\s*({literal}(?:\s*\+\s*{literal})*)",
        text,
    )
    if m is None:
        raise AssertionError(
            "ACCEPTED_CORPUS.orRuleRepro not found in accepted-corpus.ts")
    parts = [
        chunk[1:-1].replace('\\"', '"').replace("\\'", "'")
        for chunk in re.findall(literal, m.group(1))
    ]
    return "".join(parts)


def _fingerprint(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return (hashlib.sha256(path.read_bytes()).hexdigest(),
            stat.st_size, stat.st_mtime_ns)


def _listing(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


def _run_script(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # The report must bind only to --db-path: an inherited override or a
    # dotenv-loaded provider key must not change its behavior.
    env["EVENTS_DB_FILE"] = ""
    env["OPENAI_API_KEY"] = ""
    env["ANTHROPIC_API_KEY"] = ""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=str(cwd or ROOT), env=env,
    )


def _make_fixture_db(path: Path) -> None:
    """A tiny but real events archive exercising every ledger bucket.

    Deliberately stamped ``PRAGMA user_version = 1`` (an "outdated"
    schema version): ``init_db`` would rename this file to ``.bak`` and
    rebuild it, so surviving the run byte-identical proves the report
    never routes through initialization or migration.
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE events ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " timestamp TEXT NOT NULL,"
            " headline TEXT NOT NULL,"
            " stage TEXT NOT NULL,"
            " persistence TEXT NOT NULL,"
            " market_tickers TEXT DEFAULT '[]',"
            " rating TEXT DEFAULT NULL,"
            " revisit_snapshots TEXT DEFAULT '[]')"
        )
        conn.execute(
            "CREATE TABLE event_hygiene ("
            " event_id INTEGER PRIMARY KEY,"
            " override_class TEXT)"
        )
        rows = [
            # id 1 — one supporting ticker: any-supporting bucket.
            ("2026-01-05T00:00:00", "supporting event", "realized", "short",
             json.dumps([{"symbol": "AAA", "direction_tag": "supports"}]),
             None, "[]"),
            # id 2 — contradicting only: contradicted bucket.
            ("2026-01-06T00:00:00", "contradicted event", "realized", "short",
             json.dumps([{"symbol": "BBB", "direction_tag": "contradicts"}]),
             None, "[]"),
            # id 3 — no directional evidence: unresolved bucket.
            ("2026-01-07T00:00:00", "unresolved event", "realized", "short",
             json.dumps([{"symbol": "CCC"}]), None, "[]"),
            # id 4 — curated intake stub: excluded (non-thesis stage).
            ("2026-01-08T00:00:00", "curated stub", "curated_intake", "short",
             "[]", None, "[]"),
            # id 5 — synthetic seed: excluded via event_hygiene.
            ("2026-01-09T00:00:00", "seed row", "realized", "short",
             json.dumps([{"symbol": "DDD", "direction_tag": "supports"}]),
             None, "[]"),
        ]
        conn.executemany(
            "INSERT INTO events (timestamp, headline, stage, persistence,"
            " market_tickers, rating, revisit_snapshots)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        conn.execute(
            "INSERT INTO event_hygiene (event_id, override_class)"
            " VALUES (5, 'synthetic_seed')")
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
    finally:
        conn.close()


EXPECTED_FIXTURE_LEDGER = {
    "total": 3, "validated": 1, "any_supporting_count": 1,
    "contradicted": 1, "unresolved": 1,
}


class TestAdvertisedCommandContract(unittest.TestCase):
    """The displayed command must BE the safe read-only implementation."""

    def test_advertised_command_never_initializes_the_archive(self):
        command = _advertised_or_rule_command()
        self.assertNotIn(
            "init_db", command,
            "the reviewer-facing OR-rule reproduction command routes "
            "through db.init_db(), which creates / renames / migrates "
            "the source archive — not a read-only reproduction path")

    def test_advertised_command_is_the_tracked_read_only_script(self):
        command = _advertised_or_rule_command()
        self.assertIn("scripts/track_record_report.py", command)
        self.assertIn("--db-path", command)
        self.assertIn("--json", command)
        self.assertTrue(
            SCRIPT.exists(),
            "advertised script scripts/track_record_report.py is not "
            "tracked next to the command that displays it")


class TestScriptSourceSafety(unittest.TestCase):
    """Static guards on the report implementation itself."""

    def test_script_opens_read_only_and_never_initializes(self):
        self.assertTrue(SCRIPT.exists(), "read-only report script missing")
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("mode=ro", source)
        self.assertIn("uri=True", source)
        self.assertNotIn("init_db", source)

    def test_script_imports_no_provider_or_network_module(self):
        self.assertTrue(SCRIPT.exists(), "read-only report script missing")
        source = SCRIPT.read_text(encoding="utf-8")
        for banned in ("requests", "urllib", "httpx", "yfinance",
                       "market_data", "news_fetch", "analyze_event",
                       "openai", "anthropic", "load_dotenv"):
            self.assertNotRegex(
                source, rf"(?m)^\s*(?:import|from)\s+{banned}\b",
                f"read-only report must not import {banned}")


class TestMissingAndMalformedSources(unittest.TestCase):
    def test_missing_source_db_is_never_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            missing = tmp_path / "events.db"
            proc = _run_script("--db-path", str(missing), "--json")
            self.assertNotEqual(proc.returncode, 0,
                                "missing source must fail, not fabricate "
                                "an empty ledger")
            self.assertIn("not found", (proc.stderr + proc.stdout).lower())
            self.assertEqual(_listing(tmp_path), [],
                             "missing-source run must create nothing "
                             "(no events.db, no sidecars)")

    def test_malformed_source_fails_clearly_and_stays_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bogus = tmp_path / "events.db"
            bogus.write_bytes(b"this is not a sqlite database at all\n" * 64)
            before = _fingerprint(bogus)
            proc = _run_script("--db-path", str(bogus), "--json")
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("not a usable events database",
                          (proc.stderr + proc.stdout).lower())
            self.assertEqual(_fingerprint(bogus), before)
            self.assertEqual(_listing(tmp_path), ["events.db"])


class TestReadOnlyLedgerRun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.db_path = self.dir / "events.db"
        _make_fixture_db(self.db_path)

    def test_successful_run_leaves_source_and_sidecars_untouched(self):
        before = _fingerprint(self.db_path)
        proc = _run_script("--db-path", str(self.db_path), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            _fingerprint(self.db_path), before,
            "source SHA-256 / size / mtime changed under a command "
            "advertised as read-only")
        self.assertEqual(
            _listing(self.dir), ["events.db"],
            "read-only run must leave no -wal / -shm / -journal / .bak "
            "beside the source")

    def test_outdated_user_version_is_reported_not_migrated(self):
        proc = _run_script("--db-path", str(self.db_path), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(version, 1,
                         "user_version drifted: the report routed through "
                         "schema initialization / migration")
        self.assertFalse((self.dir / "events.db.bak").exists(),
                         "outdated fixture was renamed to .bak — the "
                         "init_db rebuild path ran")

    def test_ledger_matches_compute_track_record_aggregation(self):
        proc = _run_script("--db-path", str(self.db_path), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        ledger = payload["track_record"]
        for key, expected in EXPECTED_FIXTURE_LEDGER.items():
            self.assertEqual(ledger.get(key), expected,
                             f"{key}: {ledger.get(key)!r} != {expected!r}")
        # Same pure aggregator as the app ledger — recomputed in-process
        # over the same rows, read via a mode=ro connection.
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT market_tickers, rating, revisit_snapshots, stage,"
                " id FROM events").fetchall()
            synthetic = db.synthetic_seed_ids(conn)
        finally:
            conn.close()
        self.assertEqual(ledger, db.track_record_from_rows(rows, synthetic))

    def test_integrity_block_proves_source_unchanged(self):
        proc = _run_script("--db-path", str(self.db_path), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        integrity = payload["source_integrity"]
        self.assertTrue(integrity["unchanged"])
        self.assertEqual(integrity["sha256_before"],
                         integrity["sha256_after"])
        self.assertEqual(integrity["sha256_before"],
                         hashlib.sha256(
                             self.db_path.read_bytes()).hexdigest())
        self.assertTrue(payload["read_only"])

    def test_deterministic_output_for_identical_input(self):
        first = _run_script("--db-path", str(self.db_path), "--json")
        second = _run_script("--db-path", str(self.db_path), "--json")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first.stdout, second.stdout,
                         "identical input must produce byte-identical "
                         "output")


if __name__ == "__main__":
    unittest.main()
