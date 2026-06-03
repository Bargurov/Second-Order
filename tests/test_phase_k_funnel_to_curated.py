"""K13 — Phase-K funnel -> curated_observation bridge.

Pins the contract for ``scripts/phase_k_funnel_to_curated.py``, the missing
wiring K12 identified: it transforms frozen Phase-K *funnel* rows
(``candidates:`` / ``candidate_id`` / ``predicted_direction: positive|negative``,
no mechanism_description/prediction_rationale) into the curated-intake
``events:`` schema that ``curated_event_intake_apply`` consumes, AND creates
the ``curated_candidates`` row that ``curated_observation_promote`` requires.

Read-only by default; all DB writes here land on a throwaway temp DB.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
import uuid

import db
from scripts import phase_k_funnel_to_curated as bridge


def _funnel_row(**ov):
    base = {
        "candidate_id": "k-tar-05",
        "headline": "Trump announces intent to impose 25% Section 232 steel tariffs",
        "source_url": "https://www.federalregister.gov/example/steel-232",
        "source_publisher": "The White House / Federal Register",
        "event_date": "2018-03-01",
        "first_trading_date": "2018-03-01",
        "mechanism_family": "tariff",
        "mechanism_subtype": "metals_tariff",
        "primary_ticker": "NUE",
        "benchmark_ticker": "XME",
        "predicted_direction": "positive",
        "what_would_falsify": "NUE fails to outperform XME within 5d",
        "operator_notes": "clearest 232 beneficiary",
        "include_in_validation": True,
    }
    base.update(ov)
    return base


class TransformTest(unittest.TestCase):
    def test_tariff_positive_maps_to_up(self):
        ev, errs = bridge.transform_row(_funnel_row())
        self.assertEqual(errs, [])
        self.assertEqual(ev["event_id"], "k-tar-05")
        self.assertEqual(ev["predicted_direction"], "up")
        self.assertEqual(ev["mechanism_family"], "tariff")
        self.assertEqual(ev["primary_ticker"], "NUE")
        self.assertEqual(ev["benchmark_ticker"], "XME")
        self.assertTrue(ev["mechanism_description"].strip())
        self.assertTrue(ev["prediction_rationale"].strip())
        self.assertEqual(ev["mechanism_label_provenance"], "curated")

    def test_sanction_negative_maps_to_down(self):
        ev, errs = bridge.transform_row(_funnel_row(
            candidate_id="k-san-03", mechanism_family="sanction",
            mechanism_subtype="oil_sanction", primary_ticker="PBF",
            benchmark_ticker="XLE", predicted_direction="negative",
            source_url="https://home.treasury.gov/example/pdvsa"))
        self.assertEqual(errs, [])
        self.assertEqual(ev["predicted_direction"], "down")
        self.assertEqual(ev["mechanism_family"], "sanction")

    def test_missing_source_url_rejected(self):
        ev, errs = bridge.transform_row(_funnel_row(source_url=None))
        self.assertIsNone(ev)
        self.assertTrue(any("source_url" in e for e in errs))

    def test_missing_primary_ticker_rejected(self):
        ev, errs = bridge.transform_row(_funnel_row(primary_ticker=None))
        self.assertIsNone(ev)
        self.assertTrue(any("primary_ticker" in e for e in errs))

    def test_missing_event_date_rejected(self):
        ev, errs = bridge.transform_row(_funnel_row(event_date=None))
        self.assertIsNone(ev)
        self.assertTrue(any("event_date" in e for e in errs))

    def test_invalid_family_rejected(self):
        ev, errs = bridge.transform_row(_funnel_row(mechanism_family="not_a_family"))
        self.assertIsNone(ev)
        self.assertTrue(any("mechanism_family" in e for e in errs))

    def test_unmappable_direction_rejected(self):
        ev, errs = bridge.transform_row(_funnel_row(predicted_direction="ambiguous"))
        self.assertIsNone(ev)
        self.assertTrue(any("predicted_direction" in e for e in errs))

    def test_transformed_event_passes_curated_validator(self):
        from scripts.curated_event_validator import validate_curated_events
        ev, _ = bridge.transform_row(_funnel_row())
        rep = validate_curated_events([ev])
        self.assertTrue(rep.get("ok"), rep)


class PlanTest(unittest.TestCase):
    def test_excluded_rows_skipped_by_default(self):
        rows = [
            _funnel_row(),
            _funnel_row(candidate_id="k-tar-08", include_in_validation=False,
                        source_url="https://ex.gov/excluded"),
        ]
        p = bridge.plan_bridge(rows=rows)
        staged_ids = [e["event_id"] for e in p["to_stage"]]
        self.assertIn("k-tar-05", staged_ids)
        self.assertNotIn("k-tar-08", staged_ids)
        self.assertEqual(len(p["skipped"]), 1)

    def test_malformed_include_row_is_rejected_not_staged(self):
        rows = [_funnel_row(mechanism_family="bogus")]
        p = bridge.plan_bridge(rows=rows)
        self.assertFalse(p["ok"])
        self.assertEqual(len(p["to_stage"]), 0)
        self.assertEqual(len(p["rejected"]), 1)


class ApplyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = db.DB_FILE
        self._tmp = os.path.join(tempfile.gettempdir(), f"test_bridge_{uuid.uuid4().hex}.db")
        db.DB_FILE = self._tmp
        db.init_db()
        self._cleanup = [self._tmp]

    def tearDown(self) -> None:
        db.DB_FILE = self._orig
        for p in self._cleanup:
            try:
                os.remove(p)
            except OSError:
                pass

    def _bak(self):
        p = os.path.join(tempfile.gettempdir(), f"bridge_bak_{uuid.uuid4().hex}.db")
        self._cleanup.append(p)
        return p

    def _rows(self):
        return [
            _funnel_row(),
            _funnel_row(candidate_id="k-san-03", mechanism_family="sanction",
                        mechanism_subtype="oil_sanction", primary_ticker="PBF",
                        benchmark_ticker="XLE", predicted_direction="negative",
                        source_url="https://home.treasury.gov/example/pdvsa"),
        ]

    def _count(self, table, where=""):
        with sqlite3.connect(self._tmp) as c:
            return c.execute(f"SELECT COUNT(*) FROM {table} {where}").fetchone()[0]

    def test_dry_run_writes_nothing(self):
        bridge.apply_bridge(rows=self._rows(), db_path=self._tmp, confirm=False)
        self.assertEqual(self._count("events"), 0)
        self.assertEqual(self._count("curated_candidates"), 0)

    def test_write_requires_confirm_and_backup(self):
        rep = bridge.apply_bridge(rows=self._rows(), db_path=self._tmp,
                                  confirm=True, backup_path=None)
        self.assertFalse(rep.get("write_attempted"))
        self.assertEqual(self._count("events"), 0)

    def test_apply_stages_intake_and_candidates(self):
        rep = bridge.apply_bridge(rows=self._rows(), db_path=self._tmp,
                                  confirm=True, backup_path=self._bak())
        self.assertTrue(rep["write_attempted"])
        self.assertEqual(len(rep["staged"]), 2)
        # two curated_intake events + provenance + curated_candidates
        self.assertEqual(self._count("events", "WHERE stage='curated_intake'"), 2)
        self.assertEqual(self._count("event_provenance"), 2)
        self.assertEqual(self._count("curated_candidates"), 2)
        # curated_candidates carry a primary_ticker (the promote gate's need)
        with sqlite3.connect(self._tmp) as c:
            prims = [r[0] for r in c.execute(
                "SELECT primary_ticker FROM curated_candidates").fetchall()]
        self.assertCountEqual(prims, ["NUE", "PBF"])

    def test_idempotent_rerun(self):
        self.assertTrue(bridge.apply_bridge(rows=self._rows(), db_path=self._tmp,
                                            confirm=True, backup_path=self._bak())["write_attempted"])
        bridge.apply_bridge(rows=self._rows(), db_path=self._tmp,
                            confirm=True, backup_path=self._bak())
        self.assertEqual(self._count("events"), 2)
        self.assertEqual(self._count("curated_candidates"), 2)

    def test_bridge_then_promote_reaches_curated_observation(self):
        rows = self._rows()
        bridge.apply_bridge(rows=rows, db_path=self._tmp, confirm=True,
                            backup_path=self._bak())
        from scripts import curated_observation_promote as promote
        urls = {r["source_url"] for r in rows}
        prep = promote.apply_promotion(db_path=self._tmp, manifest=urls,
                                       confirm=True, backup_path=self._bak())
        self.assertTrue(prep["write_attempted"])
        self.assertEqual(prep["promoted_count"], 2)
        self.assertEqual(self._count("events", "WHERE stage='curated_observation'"), 2)
        self.assertEqual(self._count("curated_candidates", "WHERE status='promoted'"), 2)


if __name__ == "__main__":
    unittest.main()
