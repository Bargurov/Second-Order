"""K3 — guarded curated_intake -> curated_observation promotion.

Pins the write-path contract for ``scripts/curated_observation_promote.py``.
The promoter takes a frozen-ledger manifest of source_urls and turns each
matching ``curated_intake`` row into a counted ``curated_observation`` row,
WITHOUT fabricating a thesis and without ever computing a return.

Contract under test
-------------------
* Dry-run is the default and writes nothing.
* Writing requires the full flag triple: ``--write`` + ``--confirm`` +
  ``--backup-path``; any missing leg is a refusal that writes nothing.
* ``backup_path`` must differ from the target DB path.
* A row is promotable only when ALL gates pass: stage == ``curated_intake``,
  ``event_provenance.mechanism_label_provenance == "curated"``,
  ``mechanism_family`` in ``FAMILY_IDS``, a matching ``curated_candidates``
  row carries a non-empty ``primary_ticker``, and the row's ``source_url`` is
  in the frozen-ledger manifest.
* Promotion sets ``events.stage = curated_observation``,
  ``events.market_tickers = [{"symbol": primary, "role": "primary"}]``,
  ``event_provenance.intake_path = curated_promoted``, and
  ``curated_candidates.status = promoted``.
* Idempotent: a re-run promotes nothing (the row is no longer curated_intake).

Read-only / temp-DB only: every test builds a throwaway events.db.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
import uuid

import db
from mechanism_family import FAMILY_IDS
from scripts import curated_observation_promote as promote


class CuratedObservationPromoteTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_db_file = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_promote_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        self._cleanup = [self._tmp]

    def tearDown(self) -> None:
        db.DB_FILE = self._orig_db_file
        for p in self._cleanup:
            try:
                os.remove(p)
            except OSError:
                pass

    # ----- helpers --------------------------------------------------------
    def _backup_path(self) -> str:
        p = os.path.join(tempfile.gettempdir(), f"promote_bak_{uuid.uuid4().hex}.db")
        self._cleanup.append(p)
        return p

    def _make_intake_row(
        self, *, stage: str = "curated_intake",
        mechanism_family: str = "tariff",
        label_provenance: str = "curated",
        primary_ticker: str | None = "X",
        source_url: str | None = None,
        with_candidate: bool = True,
    ) -> tuple[int, str]:
        """Insert a curated_intake events row + provenance (+ optional
        curated_candidates row).  Returns (event_id, source_url)."""
        url = source_url or f"https://example.gov/release/{uuid.uuid4().hex}"
        with sqlite3.connect(self._tmp) as conn:
            cur = conn.execute(
                "INSERT INTO events (timestamp, headline, stage, persistence, "
                "market_tickers, event_date, mechanism_family) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("2018-03-08T12:00:00", "Section 232 steel proclamation",
                 stage, "unscored", "[]", "2018-03-08", mechanism_family),
            )
            event_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO event_provenance (event_id, source_type, "
                "source_publisher, source_url, source_published_at, "
                "mechanism_label_provenance, intake_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, "official", "USTR", url, "2018-03-08T12:00:00",
                 label_provenance, "curated_yaml", "2018-03-08T12:00:00"),
            )
            if with_candidate:
                conn.execute(
                    "INSERT INTO curated_candidates (source_event_id, event_date, "
                    "headline, source_url, primary_ticker, benchmark_ticker, "
                    "mechanism_family, status, source, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (event_id, "2018-03-08", "Section 232 steel proclamation",
                     url, primary_ticker, "XME", mechanism_family,
                     "draft", "curated_tariff", "2018-03-08T12:00:00"),
                )
            conn.commit()
        return event_id, url

    def _event(self, event_id: int) -> dict:
        with sqlite3.connect(self._tmp) as conn:
            conn.row_factory = sqlite3.Row
            r = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
            return dict(r) if r else {}

    def _scalar(self, sql: str, params: tuple) -> object:
        with sqlite3.connect(self._tmp) as conn:
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else None

    # ----- dry-run / guard ------------------------------------------------
    def test_dry_run_default_writes_nothing(self) -> None:
        eid, url = self._make_intake_row()
        report = promote.plan_promotion(db_path=self._tmp, manifest={url})
        self.assertEqual(report["to_promote_count"], 1)
        self.assertEqual(self._event(eid)["stage"], "curated_intake")  # untouched

    def test_write_requires_confirm_and_backup(self) -> None:
        eid, url = self._make_intake_row()
        # confirm without backup_path -> refuse
        report = promote.apply_promotion(
            db_path=self._tmp, manifest={url}, confirm=True, backup_path=None,
        )
        self.assertFalse(report["write_attempted"])
        self.assertTrue(report["refuse_reason"])
        self.assertEqual(self._event(eid)["stage"], "curated_intake")

    def test_backup_must_differ_from_target(self) -> None:
        eid, url = self._make_intake_row()
        report = promote.apply_promotion(
            db_path=self._tmp, manifest={url}, confirm=True, backup_path=self._tmp,
        )
        self.assertFalse(report["write_attempted"])
        self.assertTrue(report["refuse_reason"])
        self.assertEqual(self._event(eid)["stage"], "curated_intake")

    # ----- happy path -----------------------------------------------------
    def test_happy_path_promotes_row(self) -> None:
        eid, url = self._make_intake_row(primary_ticker="X")
        bak = self._backup_path()
        report = promote.apply_promotion(
            db_path=self._tmp, manifest={url}, confirm=True, backup_path=bak,
        )
        self.assertTrue(report["write_attempted"])
        self.assertEqual(report["promoted_count"], 1)
        self.assertTrue(os.path.exists(bak))

        ev = self._event(eid)
        self.assertEqual(ev["stage"], db.CURATED_OBSERVATION_STAGE)
        tickers = json.loads(ev["market_tickers"])
        self.assertEqual(tickers[0]["symbol"], "X")
        self.assertEqual(tickers[0]["role"], "primary")
        self.assertEqual(ev["mechanism_family"], "tariff")  # preserved

        self.assertEqual(
            self._scalar("SELECT intake_path FROM event_provenance WHERE event_id=?", (eid,)),
            "curated_promoted",
        )
        self.assertEqual(
            self._scalar("SELECT status FROM curated_candidates WHERE source_event_id=?", (eid,)),
            "promoted",
        )

    def test_idempotent_rerun_promotes_nothing(self) -> None:
        eid, url = self._make_intake_row()
        bak = self._backup_path()
        promote.apply_promotion(db_path=self._tmp, manifest={url}, confirm=True, backup_path=bak)
        # second run: row is now curated_observation, nothing to promote
        report = promote.plan_promotion(db_path=self._tmp, manifest={url})
        self.assertEqual(report["to_promote_count"], 0)

    # ----- gates ----------------------------------------------------------
    def test_rejects_non_curated_label_provenance(self) -> None:
        eid, url = self._make_intake_row(label_provenance="model")
        report = promote.plan_promotion(db_path=self._tmp, manifest={url})
        self.assertEqual(report["to_promote_count"], 0)
        self.assertEqual(len(report["rejected"]), 1)

    def test_rejects_family_not_in_family_ids(self) -> None:
        self.assertNotIn("not_a_real_family", FAMILY_IDS)
        eid, url = self._make_intake_row(mechanism_family="not_a_real_family")
        report = promote.plan_promotion(db_path=self._tmp, manifest={url})
        self.assertEqual(report["to_promote_count"], 0)
        self.assertEqual(len(report["rejected"]), 1)

    def test_rejects_missing_curated_candidate_primary(self) -> None:
        eid, url = self._make_intake_row(with_candidate=False)
        report = promote.plan_promotion(db_path=self._tmp, manifest={url})
        self.assertEqual(report["to_promote_count"], 0)
        self.assertEqual(len(report["rejected"]), 1)

    def test_rejects_non_curated_intake_stage(self) -> None:
        eid, url = self._make_intake_row(stage="realized")
        report = promote.plan_promotion(db_path=self._tmp, manifest={url})
        self.assertEqual(report["to_promote_count"], 0)
        self.assertEqual(len(report["rejected"]), 1)

    def test_row_not_in_manifest_is_not_promoted(self) -> None:
        eid, url = self._make_intake_row()
        report = promote.plan_promotion(db_path=self._tmp, manifest=set())
        self.assertEqual(report["to_promote_count"], 0)
        self.assertEqual(len(report["rejected"]), 0)  # simply not selected

    def test_rejected_batch_refuses_to_write(self) -> None:
        eid, url = self._make_intake_row(label_provenance="model")
        bak = self._backup_path()
        report = promote.apply_promotion(
            db_path=self._tmp, manifest={url}, confirm=True, backup_path=bak,
        )
        self.assertFalse(report["write_attempted"])
        self.assertEqual(self._event(eid)["stage"], "curated_intake")


if __name__ == "__main__":
    unittest.main()
