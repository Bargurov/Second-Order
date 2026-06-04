"""Tests for ``scripts/data_hygiene_report.py`` (H6).

Read-only data-hygiene report that classifies every analysis-stage archive
row into synthetic_seed / synthetic_test / real_duplicate / real_unique and
emits honest coverage denominators. Pins:

* the pure per-row classifier keys on exact seed headline + ``test-model``
  fingerprint — never on lack of ticker;
* ``classify_rows`` collapses repeated real headlines into real_duplicate and
  counts distinct real events once;
* a live-like fixture (the 8 seed/test groups summing to 71) classifies as
  71 synthetic (58 seed + 13 test);
* curated_intake (NON_ANALYSIS_STAGES) is excluded from the analysis-stage
  denominator and disclosed;
* the report writes nothing (fixture hash unchanged) and restores db.DB_FILE;
* every payload carries an explicit non-claims block.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402
from scripts import data_hygiene_report as report  # noqa: E402


# ---------------------------------------------------------------------------
# Pure per-row classifier
# ---------------------------------------------------------------------------


class ClassifySyntheticTests(unittest.TestCase):
    _REAL_MODEL = "claude-sonnet-4-20250514"

    def test_seed_headline_is_synthetic_seed(self):
        self.assertEqual(
            report.classify_synthetic("OPEC slashes output by 2 mbpd", self._REAL_MODEL),
            "synthetic_seed",
        )

    def test_test_headline_is_synthetic_test(self):
        self.assertEqual(
            report.classify_synthetic("Test headline", "test-model"), "synthetic_test"
        )

    def test_macro_shock_is_synthetic_test(self):
        # "Macro shock test event" is a literal test artifact even though it
        # was run through the real model.
        self.assertEqual(
            report.classify_synthetic("Macro shock test event", self._REAL_MODEL),
            "synthetic_test",
        )

    def test_test_model_fingerprint_overrides_real_looking_headline(self):
        self.assertEqual(
            report.classify_synthetic("A perfectly real looking headline", "test-model"),
            "synthetic_test",
        )

    def test_real_headline_is_not_synthetic(self):
        # The real recurring "AP News: OPEC members…" must NOT collide with the
        # seed "OPEC slashes output by 2 mbpd".
        self.assertIsNone(
            report.classify_synthetic(
                "AP News: OPEC members discuss extending output cuts", self._REAL_MODEL
            )
        )

    def test_lack_of_ticker_is_irrelevant_to_classifier(self):
        # A real macro headline with no ticker is still NOT synthetic — the
        # classifier never sees ticker data.
        self.assertIsNone(
            report.classify_synthetic(
                "Bank of England faces the 'most difficult combination'", self._REAL_MODEL
            )
        )

    def test_seed_headline_is_stripped(self):
        self.assertEqual(
            report.classify_synthetic("  OPEC slashes output by 2 mbpd  ", self._REAL_MODEL),
            "synthetic_seed",
        )


# ---------------------------------------------------------------------------
# Pure cross-row classifier (duplicate detection)
# ---------------------------------------------------------------------------


def _row(eid, headline, model="claude-sonnet-4-20250514", date="2026-04-10"):
    return {"id": eid, "headline": headline, "model": model, "event_date": date}


class ClassifyRowsTests(unittest.TestCase):
    def _cats(self, rows):
        return {r["id"]: r["category"] for r in report.classify_rows(rows)}

    def test_repeated_real_headline_is_real_duplicate(self):
        rows = [_row(1, "Real story A"), _row(2, "Real story A", date="2026-04-11")]
        cats = self._cats(rows)
        self.assertEqual(cats[1], "real_duplicate")
        self.assertEqual(cats[2], "real_duplicate")

    def test_singleton_real_headline_is_real_unique(self):
        cats = self._cats([_row(1, "A unique real story")])
        self.assertEqual(cats[1], "real_unique")

    def test_seed_rows_classify_synthetic_not_duplicate(self):
        rows = [_row(1, "OPEC slashes output by 2 mbpd"),
                _row(2, "OPEC slashes output by 2 mbpd", date="2026-04-11")]
        cats = self._cats(rows)
        self.assertEqual(cats[1], "synthetic_seed")
        self.assertEqual(cats[2], "synthetic_seed")

    def test_mixed_set_counts(self):
        rows = [
            _row(1, "OPEC slashes output by 2 mbpd"),
            _row(2, "Test headline", model="test-model"),
            _row(3, "Real dup", date="2026-04-10"),
            _row(4, "Real dup", date="2026-04-11"),
            _row(5, "Real singleton"),
        ]
        out = report.classify_rows(rows)
        cats = {r["id"]: r["category"] for r in out}
        self.assertEqual(cats, {
            1: "synthetic_seed", 2: "synthetic_test",
            3: "real_duplicate", 4: "real_duplicate", 5: "real_unique",
        })


# ---------------------------------------------------------------------------
# Fixture-DB summarize (read-only)
# ---------------------------------------------------------------------------


# Live-like synthetic distribution (sums to 71: 58 seed + 13 test).
_SEED_FIXTURE = [
    ("OPEC slashes output by 2 mbpd", 21, "claude-sonnet-4-20250514"),
    ("Tech CEO steps down", 13, "claude-sonnet-4-20250514"),
    ("Turkey lira weakens", 6, "claude-sonnet-4-20250514"),
    ("Turkey lira weakens as reserves slip further", 6, "claude-sonnet-4-20250514"),
    ("Fed speakers rotate", 6, "claude-sonnet-4-20250514"),
    ("Fed speakers rotate on inflation commentary", 6, "claude-sonnet-4-20250514"),
    ("Macro shock test event", 12, "claude-sonnet-4-20250514"),
    ("Test headline", 1, "test-model"),
]


class SummarizeFixtureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.gettempdir()) / f"hygiene_fix_{uuid.uuid4().hex[:8]}.db"
        conn = sqlite3.connect(str(self.tmp))
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, headline TEXT, "
            "event_date TEXT, stage TEXT, market_tickers TEXT, model TEXT)"
        )
        conn.execute(
            "CREATE TABLE price_cache (ticker TEXT, date TEXT, close REAL, volume REAL, "
            "auto_adjust INTEGER, fetched_at TEXT, source_provider TEXT, "
            "PRIMARY KEY(ticker,date,auto_adjust))"
        )
        day = 7
        def ins(headline, stage, mt, model):
            nonlocal day
            d = f"2026-04-{day:02d}"; day = day + 1 if day < 27 else 7
            conn.execute(
                "INSERT INTO events (headline,event_date,stage,market_tickers,model) "
                "VALUES (?,?,?,?,?)", (headline, d, stage, mt, model))
        # 71 synthetic
        for headline, n, model in _SEED_FIXTURE:
            for _ in range(n):
                ins(headline, "realized", "[]", model)
        # real: 3 unique (1 with ticker, 2 no-ticker macro), 1 dup group x2 (ticker),
        # 1 dup group x2 (no ticker)
        ins("Real unique with ticker", "realized", '[{"symbol":"AAPL"}]', "claude-sonnet-4-20250514")
        ins("Bank of England faces difficulty", "realized", "[]", "claude-sonnet-4-20250514")
        ins("Mexico captures cartel leader", "realized", "[]", "claude-sonnet-4-20250514")
        ins("AP News: OPEC members discuss extending output cuts", "realized", '[{"symbol":"XLE"}]', "claude-sonnet-4-20250514")
        ins("AP News: OPEC members discuss extending output cuts", "realized", '[{"symbol":"XLE"}]', "claude-sonnet-4-20250514")
        ins("US tariff refund system launches", "realized", "[]", "claude-sonnet-4-20250514")
        ins("US tariff refund system launches", "realized", "[]", "claude-sonnet-4-20250514")
        # 1 curated_intake stub (excluded from analysis-stage denominator)
        ins("Curated stub headline", "curated_intake", "[]", None)
        conn.commit(); conn.close()
        self._db_file_saved = db.DB_FILE

    def tearDown(self):
        db.DB_FILE = self._db_file_saved
        try:
            self.tmp.unlink()
        except OSError:
            pass

    def _sha(self):
        return hashlib.sha256(self.tmp.read_bytes()).hexdigest()

    def test_synthetic_and_denominator_counts(self):
        before = self._sha()
        rep = report.summarize_data_hygiene(db_path=str(self.tmp))
        # no write
        self.assertEqual(before, self._sha(), "report mutated the fixture DB")
        self.assertEqual(db.DB_FILE, self._db_file_saved, "db.DB_FILE not restored")

        self.assertEqual(rep["archive_raw_total"], 79)            # 78 analysis + 1 curated
        self.assertEqual(rep["analysis_stage_total"], 78)         # 71 synth + 7 real
        self.assertEqual(rep["curated_intake_excluded_count"], 1)
        self.assertEqual(rep["synthetic_total"], 71)
        self.assertEqual(rep["synthetic_seed_count"], 58)
        self.assertEqual(rep["synthetic_test_count"], 13)
        self.assertEqual(rep["real_row_total"], 7)
        # distinct real events: "Real unique with ticker", "Bank of England…",
        # "Mexico…", "AP News: OPEC…", "US tariff refund…" = 5
        self.assertEqual(rep["distinct_real_event_total"], 5)
        self.assertEqual(rep["real_duplicate_rows"], 4)           # 2 + 2
        self.assertEqual(rep["real_duplicate_groups_count"], 2)
        self.assertEqual(rep["redundant_real_duplicate_rows"], 2)

    def test_real_unique_no_primary_examples_and_non_claims(self):
        rep = report.summarize_data_hygiene(db_path=str(self.tmp))
        heads = {e["headline"] for e in rep["real_unique_no_primary_examples"]}
        self.assertIn("Bank of England faces difficulty", heads)
        self.assertIn("Mexico captures cartel leader", heads)
        self.assertNotIn("Real unique with ticker", heads)        # has a ticker
        nc = rep["non_claims"]
        self.assertTrue(nc["does_not_touch_phase1_phase2_fdr_pools"])
        self.assertTrue(nc["does_not_delete_or_mutate_rows"])
        self.assertTrue(nc["classification_is_heuristic_and_auditable"])
        # Post-K: the frozen-157 "denominator of record" key is gone; the
        # corrected, can't-go-stale stance is machine-readable in its place.
        self.assertNotIn("denominator_of_record_remains_157", nc)
        self.assertTrue(nc["analysis_stage_denominator_is_dynamic"])
        self.assertTrue(nc["thesis_denominator_separate_from_analysis_stage"])

    def test_coverage_ratios_shape(self):
        rep = report.summarize_data_hygiene(db_path=str(self.tmp))
        cr = rep["coverage_ratios"]
        for key in ("archive_row_level", "real_row_level", "distinct_real_event_level"):
            self.assertIn("numerator", cr[key])
            self.assertIn("denominator", cr[key])
            self.assertIn("value", cr[key])
        # On an empty price_cache fixture nothing is compute-ready.
        self.assertEqual(rep["compute_ready_rows"], 0)
        self.assertEqual(cr["archive_row_level"]["denominator"], 78)
        self.assertEqual(cr["real_row_level"]["denominator"], 7)
        self.assertEqual(cr["distinct_real_event_level"]["denominator"], 5)

    def test_real_recurring_headline_is_not_synthetic(self):
        # The script's core honesty guarantee: the real recurring
        # "AP News: OPEC members…" must NOT collide with the seed
        # "OPEC slashes output by 2 mbpd" — it is a real_duplicate.
        rep = report.summarize_data_hygiene(db_path=str(self.tmp))
        target = "AP News: OPEC members discuss extending output cuts"
        synth_heads = {g["headline"] for g in rep["synthetic_groups"]}
        dup_heads = {g["headline"] for g in rep["duplicate_groups"]}
        self.assertNotIn(target, synth_heads)
        self.assertIn(target, dup_heads)

    def test_json_render_roundtrips_real_report(self):
        rep = report.summarize_data_hygiene(db_path=str(self.tmp))
        loaded = json.loads(report._render_json(rep))
        # nested structures survive serialization
        self.assertEqual(loaded["coverage_ratios"]["archive_row_level"]["denominator"], 78)
        self.assertEqual(loaded["synthetic_total"], 71)
        self.assertTrue(loaded["non_claims"]["does_not_delete_or_mutate_rows"])

    def test_empty_report_has_same_top_level_keys(self):
        # Guards against _empty_report drifting out of sync with the populated
        # report when a required field is added.
        rep = report.summarize_data_hygiene(db_path=str(self.tmp))
        self.assertEqual(set(report._empty_report()), set(rep))


# ---------------------------------------------------------------------------
# Honesty guard: the "157 remains the denominator of record" framing
# ---------------------------------------------------------------------------


# These phrases were true before Phase K (when the analysis-stage denominator
# was a frozen 157) but became dishonest once curated_observation rows were
# promoted into the analysis stage (live analysis_stage_total is now 165). None
# may reappear in the docstring, the non-claims block, or either renderer. The
# strictly-conditional thesis note ("may remain 157" / "not a frozen 157") is
# deliberately NOT banned — only the unconditional / "denominator of record"
# framing is.
_STALE_DENOMINATOR_PHRASES = (
    "denominator_of_record_remains_157",
    "denominator of record",
    "157 analysis-stage count",
    "157 remains",
)


class NoStaleDenominatorWordingTests(unittest.TestCase):
    def _assert_clean(self, text, where):
        for phrase in _STALE_DENOMINATOR_PHRASES:
            self.assertNotIn(
                phrase, text,
                f"stale denominator wording {phrase!r} reappeared in {where}",
            )

    def test_module_docstring_has_no_stale_denominator_wording(self):
        self._assert_clean(report.__doc__ or "", "module docstring")

    def test_non_claims_keys_have_no_frozen_157(self):
        for key in report._NON_CLAIMS:
            self.assertNotIn("157", key, f"non_claims key {key!r} embeds a frozen 157")
        self.assertNotIn("denominator_of_record_remains_157", report._NON_CLAIMS)

    def test_non_claims_notes_have_no_stale_denominator_wording(self):
        self._assert_clean(report._NON_CLAIMS["notes"], "non_claims notes")

    def test_json_render_has_no_stale_denominator_wording(self):
        self._assert_clean(report._render_json(report._empty_report()), "JSON render")

    def test_text_render_has_no_stale_denominator_wording(self):
        self._assert_clean(report._render_text(report._empty_report()), "text render")

    def test_non_claims_documents_dynamic_analysis_denominator(self):
        # The corrected stance must be machine-readable, not merely deleted.
        nc = report._NON_CLAIMS
        self.assertTrue(nc["analysis_stage_denominator_is_dynamic"])
        self.assertTrue(nc["thesis_denominator_separate_from_analysis_stage"])

    def test_text_render_surfaces_source_anchored_promoted(self):
        # The promoted curated_observation count is surfaced beside the
        # analysis-stage denominator, never hidden.
        self.assertIn(
            "source-anchored promoted", report._render_text(report._empty_report())
        )


if __name__ == "__main__":
    unittest.main()
