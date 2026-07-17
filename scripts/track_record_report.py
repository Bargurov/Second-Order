"""Read-only any-support OR-rule track-record ledger report.

The canonical reviewer reproduction path for the accepted-archive OR-rule
outcome ledger (the ``db.compute_track_record`` figures shown on the
Evidence Overview page and in the research-record memo):

    python scripts/track_record_report.py --db-path events.db --json

Safety contract (tests/test_track_record_reproduction_safety.py):

* the events database is opened over an explicit SQLite read-only URI
  (``mode=ro``) - never through database initialization, so no creation,
  renaming, ``.bak`` rebuild, ``PRAGMA`` stamping, or ALTER TABLE
  migration can ever touch the source;
* a missing source path fails clearly and is never created;
* a malformed source fails clearly and is left byte-identical;
* the report emits a source-integrity block (SHA-256 before / after)
  proving the source was unchanged by the run;
* the ledger itself is ``db.track_record_from_rows`` - the exact pure
  aggregation behind ``db.compute_track_record`` - so this command and
  the app ledger cannot drift apart;
* no provider, network, LLM, or paid module is imported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_rows(db_path: Path) -> tuple[list, frozenset]:
    """Read the ledger rows over a read-only connection.

    Mirrors ``db.compute_track_record``'s query exactly, including the
    fallback for ancient databases without ``revisit_snapshots``.
    """
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        try:
            rows = conn.execute(
                "SELECT market_tickers, rating, revisit_snapshots, stage, id "
                "FROM events"
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                raise
            rows = conn.execute(
                "SELECT market_tickers, rating, stage, id FROM events"
            ).fetchall()
            rows = [(r[0], r[1], None, r[2], r[3]) for r in rows]
        synthetic = db.synthetic_seed_ids(conn)
        return rows, synthetic
    finally:
        conn.close()


def build_report(db_path: Path) -> dict:
    """Build the read-only OR-rule ledger report. Never mutates the source."""
    sha_before = _sha256(db_path)
    rows, synthetic = _load_rows(db_path)
    ledger = db.track_record_from_rows(rows, synthetic)
    sha_after = _sha256(db_path)
    return {
        "report": "track_record_report",
        "ledger_rule": "any-support OR-rule (db.compute_track_record)",
        "read_only": True,
        "connection": "sqlite mode=ro URI; no initialization, no "
                      "migration, no schema stamping",
        "source_integrity": {
            "sha256_before": sha_before,
            "sha256_after": sha_after,
            "unchanged": sha_before == sha_after,
        },
        "synthetic_seed_excluded": len(synthetic),
        "track_record": ledger,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only any-support OR-rule track-record ledger.")
    parser.add_argument("--db-path", required=True,
                        help="Path to the events database (opened mode=ro; "
                             "never created, migrated, or renamed).")
    parser.add_argument("--json", action="store_true",
                        help="Emit the report as JSON (canonical form).")
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    if not db_path.is_file():
        print(f"error: events database not found: {db_path} "
              "(read-only report; the source is never created)",
              file=sys.stderr)
        return 2

    try:
        report = build_report(db_path)
    except sqlite3.Error as exc:
        print(f"error: not a usable events database: {db_path} ({exc})",
              file=sys.stderr)
        return 2

    print(json.dumps(report, indent=None if args.json else 2,
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
