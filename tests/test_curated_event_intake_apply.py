"""D1B — guarded curated-event intake writer.

Pins the write-path contract for ``scripts/curated_event_intake_apply.py``.
The writer takes validated curated YAML events (via the D1A loader +
validator) and persists each as one ``events`` row plus one matching
``event_provenance`` row, without ever touching legacy rows or
fabricating analysis output.

Contract under test
-------------------
* Dry-run is the default and writes nothing.
* Writing requires the full flag triple: ``--write`` + ``--confirm`` +
  ``--backup-path``; any missing leg is a refusal that writes nothing.
* ``backup_path`` must differ from the target DB path.
* Each accepted event inserts one ``events`` row AND one
  ``event_provenance`` row in a single all-or-nothing transaction;
  a mid-write error rolls back both.
* ``event_provenance.source_url`` is the all-time idempotency key —
  re-running the same YAML inserts nothing the second time, and an
  intra-batch duplicate ``source_url`` inserts once.
* Intake guards reject a source_url-less event, an official /
  regulator / exchange ``source_type`` without ``source_url``, a
  source-anchored event (``source_published_at`` set) without
  ``source_url``, and an out-of-vocabulary
  ``mechanism_label_provenance``.
* ``predicted_direction`` / ``prediction_rationale`` are validated by
  the reused validator but are NOT persisted (no directional framing).
* An LLM-inferred mechanism label is stored verbatim (never upgraded to
  ``curated``); source-anchoring is derived from url + published_at and
  is orthogonal to the mechanism-label provenance.
* Legacy rows (no provenance row) are never mutated or source-anchored.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
import uuid
from io import StringIO
from unittest.mock import patch

import yaml

import db
from scripts import curated_event_intake_apply as cli


def _curated_event(**overrides) -> dict:
    """A single fully-valid curated event dict (string event_date)."""
    base = {
        "event_id":              1,
        "event_date":            "2026-04-06",
        "headline":              "Federal Reserve Board announces section 23A "
                                 "exemption for Example Bank, N.A.",
        "source_url":            "https://www.federalreserve.gov/newsevents/"
                                 "pressreleases/orders20260406a.htm",
        "primary_ticker":        "MS",
        "benchmark_ticker":      "SPY",
        "mechanism_family":      "bank_regulatory_capital_relief",
        "mechanism_description": "A section 23A exemption permits "
                                 "intra-affiliate transactions that would "
                                 "otherwise hit the bank's capital limit.",
        "predicted_direction":   "up",
        "prediction_rationale":  "Capital relief at the bank subsidiary lifts "
                                 "buyback capacity over a multi-day window.",
        "curator_notes":         "Hand-reviewed against Fed press release.",
    }
    base.update(overrides)
    return base


class CuratedEventIntakeApplyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_db_file = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_intake_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        self._cleanup_paths: list[str] = [self._tmp]

    def tearDown(self) -> None:
        db.DB_FILE = self._orig_db_file
        for path in self._cleanup_paths:
            try:
                os.remove(path)
            except OSError:
                pass

    # ----- helpers --------------------------------------------------------
    def _write_yaml(self, events: list[dict]) -> str:
        path = os.path.join(
            tempfile.gettempdir(), f"curated_{uuid.uuid4().hex}.yaml",
        )
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump({"events": events}, fh, sort_keys=False,
                           allow_unicode=True)
        self._cleanup_paths.append(path)
        return path

    def _backup_path(self) -> str:
        path = os.path.join(
            tempfile.gettempdir(), f"intake_backup_{uuid.uuid4().hex}.db",
        )
        self._cleanup_paths.append(path)
        return path

    def _count(self, table: str) -> int:
        with sqlite3.connect(self._tmp) as conn:
            try:
                return conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            except sqlite3.OperationalError:
                return 0

    def _row(self, table: str, pk: int) -> dict | None:
        with sqlite3.connect(self._tmp) as conn:
            conn.row_factory = sqlite3.Row
            r = conn.execute(
                f"SELECT * FROM {table} WHERE id = ?", (pk,)
            ).fetchone()
            return dict(r) if r is not None else None

    def _apply(self, events, **kw):
        kw.setdefault("db_path", self._tmp)
        return cli.apply_curated_intake(events=events, **kw)

    # ----- dry-run --------------------------------------------------------
    def test_dry_run_writes_nothing(self) -> None:
        path = self._write_yaml([_curated_event()])
        code = cli.main(
            ["--yaml", path, "--db-path", self._tmp, "--json"],
            out=StringIO(),
        )
        self.assertEqual(code, 0)
        self.assertEqual(self._count("events"), 0)
        self.assertEqual(self._count("event_provenance"), 0)

    # ----- flag gating ----------------------------------------------------
    def test_write_without_confirm_exits_two_and_writes_nothing(self) -> None:
        path = self._write_yaml([_curated_event()])
        code = cli.main(
            ["--yaml", path, "--db-path", self._tmp, "--write"],
            out=StringIO(),
        )
        self.assertEqual(code, 2)
        self.assertEqual(self._count("events"), 0)
        self.assertEqual(self._count("event_provenance"), 0)

    def test_confirm_without_backup_path_exits_two_and_writes_nothing(self) -> None:
        path = self._write_yaml([_curated_event()])
        code = cli.main(
            ["--yaml", path, "--db-path", self._tmp, "--write", "--confirm"],
            out=StringIO(),
        )
        self.assertEqual(code, 2)
        self.assertEqual(self._count("events"), 0)
        self.assertEqual(self._count("event_provenance"), 0)

    def test_refuses_when_backup_path_equals_db_path(self) -> None:
        report = self._apply(
            [_curated_event()], confirm=True, backup_path=self._tmp,
        )
        self.assertFalse(report["write_attempted"])
        self.assertIsNotNone(report["refuse_reason"])
        self.assertEqual(self._count("events"), 0)
        self.assertEqual(self._count("event_provenance"), 0)

    # ----- happy write path -----------------------------------------------
    def test_write_inserts_event_and_provenance_together(self) -> None:
        backup = self._backup_path()
        report = self._apply(
            [_curated_event()], confirm=True, backup_path=backup,
        )
        self.assertTrue(report["write_attempted"])
        self.assertEqual(report["inserted_count"], 1)
        self.assertEqual(self._count("events"), 1)
        self.assertEqual(self._count("event_provenance"), 1)
        self.assertTrue(os.path.exists(backup), "backup snapshot not created")

        with sqlite3.connect(self._tmp) as conn:
            conn.row_factory = sqlite3.Row
            ev = conn.execute("SELECT * FROM events").fetchone()
            pv = conn.execute("SELECT * FROM event_provenance").fetchone()
        # the provenance row points 1:1 at the freshly inserted event
        self.assertEqual(pv["event_id"], ev["id"])
        self.assertEqual(pv["source_url"], _curated_event()["source_url"])
        self.assertEqual(pv["intake_path"], "curated_yaml")
        self.assertEqual(pv["mechanism_label_provenance"], "curated")
        # honest 1:1 columns only
        self.assertEqual(ev["headline"], _curated_event()["headline"])
        self.assertEqual(ev["event_date"], "2026-04-06")
        self.assertEqual(ev["mechanism_family"],
                         "bank_regulatory_capital_relief")
        self.assertEqual(ev["stage"], "curated_intake")
        self.assertEqual(ev["persistence"], "unscored")

    def test_source_url_idempotent_across_runs(self) -> None:
        r1 = self._apply(
            [_curated_event()], confirm=True, backup_path=self._backup_path(),
        )
        self.assertEqual(r1["inserted_count"], 1)

        r2 = self._apply(
            [_curated_event()], confirm=True, backup_path=self._backup_path(),
        )
        self.assertEqual(r2["inserted_count"], 0)
        self.assertFalse(r2["write_attempted"])
        self.assertEqual(len(r2["skipped_existing"]), 1)
        # still exactly one of each — no duplicate
        self.assertEqual(self._count("events"), 1)
        self.assertEqual(self._count("event_provenance"), 1)

    def test_duplicate_source_url_within_batch_inserts_once(self) -> None:
        report = self._apply(
            [_curated_event(event_id=1), _curated_event(event_id=2)],
            confirm=True, backup_path=self._backup_path(),
        )
        self.assertEqual(report["inserted_count"], 1)
        self.assertEqual(len(report["skipped_existing"]), 1)
        self.assertEqual(self._count("events"), 1)
        self.assertEqual(self._count("event_provenance"), 1)

    # ----- rollback -------------------------------------------------------
    def test_rollback_on_simulated_provenance_error(self) -> None:
        backup = self._backup_path()
        with patch.object(
            cli, "_insert_provenance_row",
            side_effect=RuntimeError("simulated provenance insert failure"),
        ):
            report = self._apply(
                [_curated_event()], confirm=True, backup_path=backup,
            )
        self.assertFalse(report["write_attempted"])
        self.assertTrue(report.get("error"))
        # the events insert in the same transaction rolled back too
        self.assertEqual(self._count("events"), 0)
        self.assertEqual(self._count("event_provenance"), 0)

    # ----- intake guards --------------------------------------------------
    def test_official_source_type_without_source_url_rejected(self) -> None:
        report = self._apply(
            [_curated_event(source_type="official", source_url="")],
            confirm=True, backup_path=self._backup_path(),
        )
        self.assertFalse(report["write_attempted"])
        self.assertIsNotNone(report["refuse_reason"])
        self.assertTrue(report["rejected"])
        self.assertEqual(self._count("events"), 0)
        self.assertEqual(self._count("event_provenance"), 0)

    def test_source_anchored_without_source_url_rejected(self) -> None:
        report = self._apply(
            [_curated_event(source_url="", source_published_at="2026-04-06")],
            confirm=True, backup_path=self._backup_path(),
        )
        self.assertFalse(report["write_attempted"])
        self.assertIsNotNone(report["refuse_reason"])
        self.assertTrue(report["rejected"])
        self.assertEqual(self._count("events"), 0)
        self.assertEqual(self._count("event_provenance"), 0)

    def test_invalid_mechanism_label_provenance_rejected(self) -> None:
        report = self._apply(
            [_curated_event(mechanism_label_provenance="totally_made_up")],
            confirm=True, backup_path=self._backup_path(),
        )
        self.assertFalse(report["write_attempted"])
        self.assertIsNotNone(report["refuse_reason"])
        flat = [e for r in report["rejected"] for e in r["errors"]]
        self.assertTrue(
            any("mechanism_label_provenance" in e for e in flat),
            f"expected a mechanism_label_provenance guard error, got {flat!r}",
        )
        self.assertEqual(self._count("events"), 0)
        self.assertEqual(self._count("event_provenance"), 0)

    def test_llm_inferred_mechanism_stored_verbatim_not_source_anchored_label(
        self,
    ) -> None:
        report = self._apply(
            [_curated_event(
                mechanism_label_provenance="model",
                source_published_at="2026-04-06",
            )],
            confirm=True, backup_path=self._backup_path(),
        )
        self.assertTrue(report["write_attempted"])
        with sqlite3.connect(self._tmp) as conn:
            conn.row_factory = sqlite3.Row
            pv = conn.execute("SELECT * FROM event_provenance").fetchone()
        # mechanism-label provenance stored verbatim, never upgraded
        self.assertEqual(pv["mechanism_label_provenance"], "model")
        # source-anchoring is derived from url + published_at, orthogonal
        # to the mechanism label
        self.assertEqual(db.derive_provenance_status(pv), "source_anchored")

    # ----- predicted_direction NOT persisted ------------------------------
    def test_predicted_direction_validated_but_not_persisted(self) -> None:
        report = self._apply(
            [_curated_event(predicted_direction="down")],
            confirm=True, backup_path=self._backup_path(),
        )
        self.assertTrue(report["write_attempted"])
        with sqlite3.connect(self._tmp) as conn:
            conn.row_factory = sqlite3.Row
            ev = conn.execute("SELECT * FROM events").fetchone()
            pv = conn.execute("SELECT * FROM event_provenance").fetchone()
        # no column anywhere carries the direction or rationale
        self.assertNotIn("predicted_direction", ev.keys())
        self.assertNotIn("predicted_direction", pv.keys())
        self.assertNotIn("prediction_rationale", ev.keys())
        # analysis-output fields stay at schema defaults (nothing fabricated)
        self.assertEqual(ev["market_tickers"], "[]")
        self.assertEqual(ev["proof_status"], "{}")
        # the rationale text is not smuggled into notes
        self.assertNotIn("buyback capacity", ev["notes"] or "")

    # ----- legacy rows untouched ------------------------------------------
    def test_no_legacy_row_mutation(self) -> None:
        with sqlite3.connect(self._tmp) as conn:
            cur = conn.execute(
                "INSERT INTO events (timestamp, headline, stage, persistence) "
                "VALUES (?, ?, ?, ?)",
                ("2026-01-01T00:00:00Z", "legacy headline",
                 "realized", "structural"),
            )
            legacy_id = int(cur.lastrowid)
            conn.commit()
        before = self._row("events", legacy_id)

        report = self._apply(
            [_curated_event()], confirm=True, backup_path=self._backup_path(),
        )
        self.assertTrue(report["write_attempted"])

        after = self._row("events", legacy_id)
        self.assertEqual(before, after, "legacy row was mutated")
        # the legacy event is never retroactively source-anchored
        self.assertIsNone(db.get_event_provenance(legacy_id))
        self.assertEqual(db.provenance_status_for_event(legacy_id),
                         "unrecorded")
        # the curated event still landed with its own provenance row
        self.assertEqual(self._count("events"), 2)
        self.assertEqual(self._count("event_provenance"), 1)


if __name__ == "__main__":
    unittest.main()
