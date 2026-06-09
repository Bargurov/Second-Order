"""AP3a — read-only drift validator for the event_hygiene synthetic_seed exclusion.

Runs against any DB path (a copy, or the EVENTS_DB_FILE-bound DB) and checks the
keep-and-flag invariants:
  * how many ``event_hygiene`` ``synthetic_seed`` flags exist;
  * NO synthetic_seed id is counted in the accepted-corpus (coverage) set;
  * every synthetic_seed row is still retrievable by id (kept in the archive);
  * the resulting accepted denominators (track-record total / coverage denom).

Pure read: the data reads use read-only connections and no events/price_cache
row is mutated.  ``ok`` is True when nothing leaked into the accepted set and
every flagged row is still retrievable.

CLI: ``python -m tools.synthetic_seed_hygiene_validation [db_path]`` — exits 0
when ``ok``, 1 otherwise.  Without an arg it uses the EVENTS_DB_FILE binding.
"""
from __future__ import annotations

import db
from scripts import event_study_coverage_report as cov


def validate(db_path: str | None = None) -> dict:
    """Return the synthetic_seed exclusion drift report for ``db_path``."""
    orig = db.DB_FILE
    try:
        if db_path is not None:
            db.DB_FILE = db_path
        db.init_db()  # idempotent (CREATE IF NOT EXISTS); sets _db_ready, no row writes
        path = db.get_db_path()

        synthetic = db.synthetic_seed_ids()
        accepted_events, _excluded = cov._load_events(path)
        accepted_ids = {e["id"] for e in accepted_events}

        leaked = sorted(int(i) for i in synthetic if i in accepted_ids)
        not_retrievable = sorted(int(i) for i in synthetic if db.load_event_by_id(i) is None)
        tr = db.compute_track_record()

        return {
            "db_path": path,
            "synthetic_seed_count": len(synthetic),
            "synthetic_seed_ids": sorted(int(i) for i in synthetic),
            "leaked_into_accepted": leaked,        # MUST be [] — none counted as accepted
            "not_retrievable": not_retrievable,    # MUST be [] — all still in the archive
            "track_record_total": tr.get("total"),
            "coverage_denom": len(accepted_events),
            "ok": not leaked and not not_retrievable,
        }
    finally:
        if db_path is not None:
            db.DB_FILE = orig
            db.init_db()


if __name__ == "__main__":  # pragma: no cover - thin CLI
    import json
    import sys

    report = validate(db_path=(sys.argv[1] if len(sys.argv) > 1 else None))
    print(json.dumps(report, indent=2))
    sys.exit(0 if report["ok"] else 1)
