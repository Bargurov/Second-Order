"""Tests for the G3B comparison-mechanism classification overlay (Mission G).

Contract under test:

* the comparison taxonomy ``g3-comparison-taxonomy-v1`` REUSES the frozen J1
  headline rule set (``accepted_family_overlay_report.FAMILY_RULES`` /
  ``classify_headline``) verbatim; a pin test fails loudly if the upstream
  rules drift, so a silent change cannot redefine the frozen taxonomy;
* classification is a PURE function of one normalized headline-like text field,
  applied with the SAME rule set across every cohort; stored archive mechanism
  fields are never used as classification keys;
* single / multi-match / unclassified are each explicit; there is no per-event
  manual override path and no market data / outcome / state field enters
  classification;
* the three cohorts reconcile to 86 accepted + 65 G1A + 32 G1B = 183.

Pure fixtures; the live-archive reconciliation tests skip when events.db /
the G1 ledgers are absent.
"""
from __future__ import annotations

import inspect
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import accepted_family_overlay_report as O  # noqa: E402
from scripts import g3_mechanism_classification as g3c  # noqa: E402


def _cls(text, *, cohort="accepted_track_record", lane="accepted_thesis",
         source_family="accepted_news_headline", year="2020"):
    return g3c.classify_record(row_key="k", cohort=cohort, lane=lane,
                               source_family=source_family, year=year,
                               text=text)


# ---------------------------------------------------------------------------
# 1. Frozen taxonomy pin (reuse of the J1 rule set, not a fork)
# ---------------------------------------------------------------------------


class TaxonomyPinTests(unittest.TestCase):
    def test_taxonomy_version_frozen(self):
        self.assertEqual(g3c.TAXONOMY_VERSION, "g3-comparison-taxonomy-v1")

    def test_expected_family_labels_match_reused_source(self):
        live = tuple(rule["family"] for rule in O.FAMILY_RULES)
        self.assertEqual(live, g3c.EXPECTED_FAMILY_LABELS)

    def test_taxonomy_fingerprint_is_pinned(self):
        # A silent upstream edit to FAMILY_RULES changes the fingerprint and
        # fails here, forcing a version bump + full re-run rather than a
        # silent redefinition of g3-comparison-taxonomy-v1.
        self.assertEqual(g3c.taxonomy_fingerprint(),
                         g3c.PINNED_TAXONOMY_FINGERPRINT)

    def test_labels_are_mechanism_not_sampling_family(self):
        for banned in ("fomc", "opec"):
            self.assertNotIn(banned, g3c.EXPECTED_FAMILY_LABELS)


# ---------------------------------------------------------------------------
# 2. Pure classification: single / multi / unclassified, uniform across cohorts
# ---------------------------------------------------------------------------


class ClassificationTests(unittest.TestCase):
    def test_classify_text_takes_only_text(self):
        params = list(inspect.signature(g3c.classify_text).parameters)
        self.assertEqual(params, ["text"], params)

    def test_single_match_is_explicit(self):
        row = _cls("US may impose new tariffs on electric vehicle imports")
        self.assertEqual(row["klass"], "single")
        self.assertEqual(row["family"], "tariff")
        self.assertEqual(row["matched"], ["tariff"])

    def test_multi_match_is_explicit(self):
        row = _cls("Iran threatens to close the Strait of Hormuz after new "
                   "US sanctions")
        self.assertEqual(row["klass"], "multi_match")
        self.assertIsNone(row["family"])
        self.assertGreater(len(row["matched"]), 1)
        self.assertIn("sanction", row["matched"])
        self.assertIn("supply_shock", row["matched"])

    def test_unclassified_is_explicit(self):
        row = _cls("Maintain target range at 1.25-1.50 percent")
        self.assertEqual(row["klass"], "unclassified")
        self.assertIsNone(row["family"])
        self.assertEqual(row["matched"], [])

    def test_identical_text_classifies_identically_across_cohorts(self):
        text = "OPEC extends voluntary oil output cuts through the quarter"
        a = _cls(text, cohort="accepted_track_record")
        b = _cls(text, cohort="g1a_fomc_historical",
                 lane="frame_complete_historical",
                 source_family="official_fomc_statement")
        c = _cls(text, cohort="g1b_opec_historical",
                 lane="designed_contrast", source_family="official_opec_record")
        self.assertEqual(a["klass"], b["klass"])
        self.assertEqual(b["klass"], c["klass"])
        self.assertEqual(a["family"], c["family"])
        self.assertEqual(a["matched"], c["matched"])

    def test_row_fields_are_whitelisted(self):
        row = _cls("US imposes sanctions on foreign chipmaker")
        self.assertTrue(set(row).issubset(g3c.G3B_ROW_FIELDS), set(row))
        self.assertEqual(row["taxonomy_version"], "g3-comparison-taxonomy-v1")


# ---------------------------------------------------------------------------
# 3. Stored archive mechanism fields are ignored; no manual override
# ---------------------------------------------------------------------------


class DisciplineTests(unittest.TestCase):
    def test_stored_mechanism_family_is_ignored(self):
        # A record whose STORED mechanism_family says "sanction" but whose
        # headline carries no rule keyword must classify as unclassified:
        # the overlay keys on text, never the stored label.
        record = {"event_id": 9, "headline": "quarterly earnings update",
                  "mechanism_family": "sanction",
                  "market_tickers": "[]", "revisit_snapshots": "[]"}
        row = g3c._accepted_row(record, event_date="2020-05-01")
        self.assertEqual(row["klass"], "unclassified")
        self.assertIsNone(row["family"])

    def test_stored_family_matching_text_still_text_driven(self):
        record = {"event_id": 10,
                  "headline": "US imposes new tariffs on steel",
                  "mechanism_family": "none"}   # stored says none; text says tariff
        row = g3c._accepted_row(record, event_date="2021-03-01")
        self.assertEqual(row["family"], "tariff")

    def test_no_manual_override_parameter(self):
        params = set(inspect.signature(g3c.classify_record).parameters)
        self.assertNotIn("override", params)
        self.assertNotIn("force", params)
        self.assertNotIn("family", params)   # cannot inject a family directly

    def test_accepted_row_carries_no_outcome_or_stored_family(self):
        record = {"event_id": 11, "headline": "US imposes sanctions on Zbank",
                  "mechanism_family": "sanction",
                  "market_tickers": '[{"symbol":"XYZ"}]',
                  "revisit_snapshots": '[{"ar":0.1}]'}
        row = g3c._accepted_row(record, event_date="2022-01-01")
        dumped = json.dumps(row).lower()
        # The stored outcome-adjacent fields and the raw headline TEXT must not
        # leak into the persisted row (source_family label is metadata, allowed).
        for banned in ("mechanism_family", "revisit", "market_tickers",
                       "abnormal", "imposes", "zbank", "xyz", "0.1"):
            self.assertNotIn(banned, dumped, banned)


# ---------------------------------------------------------------------------
# 4. Cohort input-surface extraction (pure line parsing)
# ---------------------------------------------------------------------------


_G1A_LINE = ("| `fomc-policy-decision-2020-03-15` | 2020-03-15 | "
             "5:00 p.m. EDT | unscheduled | "
             "Lower target range to 0.00-0.25 percent | "
             "[Fed statement](https://example) | `clean_discrete_anchor` | "
             "`frame_complete_historical` | `f@v1` | `g0-v1` | frame_member | "
             "path | frame-complete historical |")

_G1B_CANON = ("| D02 | 2018-06-23 | 4th ONOMM PR | "
              "OPEC+ returns to 100 percent conformity | increase (effective) | "
              "C01 `opec-2018-06-23-conformity-return` | "
              "pinned_official / scheduled | canonical |")

_G1B_MIRROR = ("| D01 | 2018-06-22 | 174th OPEC Conference PR | "
               "Conference decision toward 100 percent conformity | "
               "increase (effective) | C01 | "
               "pinned_official / scheduled | mirror of D02 |")


class SurfaceExtractionTests(unittest.TestCase):
    def test_g1a_uses_concise_policy_action_cell(self):
        rows = g3c._g1a_rows_from_lines([_G1A_LINE])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["cohort"], g3c.COHORT_G1A)
        self.assertEqual(r["year"], "2020")
        self.assertEqual(r["row_key"], "g1a:fomc-policy-decision-2020-03-15")
        # "Lower target range to 0.00-0.25 percent" carries no rule keyword.
        self.assertEqual(r["klass"], "unclassified")

    def test_g1b_uses_title_cell_and_skips_mirrors(self):
        rows = g3c._g1b_rows_from_lines([_G1B_CANON, _G1B_MIRROR])
        self.assertEqual(len(rows), 1)      # the mirror row is not advanced
        r = rows[0]
        self.assertEqual(r["cohort"], g3c.COHORT_G1B)
        self.assertEqual(r["year"], "2018")
        self.assertEqual(r["row_key"], "g1b:opec-2018-06-23-conformity-return")
        # "OPEC+ returns to 100 percent conformity" hits the supply_shock rule
        # on the literal token "opec".
        self.assertEqual(r["family"], "supply_shock")


# ---------------------------------------------------------------------------
# 5. Loaders, reconciliation, firewall
#    The unit suite is sandboxed away from the live archive (tests/__init__.py
#    redirects db.DB_FILE), so the real 86 + 65 + 32 = 183 reconciliation is a
#    VERIFICATION-time check against the live events.db, not a unit test. Here
#    the accepted loader is exercised against a SEEDED temp DB; the G1 loaders
#    against the real tracked ledgers.
# ---------------------------------------------------------------------------

import os          # noqa: E402
import sqlite3     # noqa: E402
import tempfile    # noqa: E402
import uuid        # noqa: E402

_EVENTS_DDL = (
    "CREATE TABLE events (id INTEGER PRIMARY KEY, event_date TEXT, "
    "stage TEXT, mechanism_family TEXT, headline TEXT, market_tickers TEXT)")
_HYGIENE_DDL = (
    "CREATE TABLE event_hygiene (event_id INTEGER PRIMARY KEY, "
    "override_class TEXT, override_reason TEXT, created_at TEXT)")


def _seed_events_db(rows):
    """rows: (id, event_date, stage, mechanism_family, headline). Returns path."""
    path = os.path.join(tempfile.gettempdir(), f"g3b_{uuid.uuid4().hex}.db")
    conn = sqlite3.connect(path)
    try:
        conn.execute(_EVENTS_DDL)
        conn.execute(_HYGIENE_DDL)
        conn.executemany(
            "INSERT INTO events VALUES (?,?,?,?,?,?)",
            [(i, d, s, f, h, "[]") for (i, d, s, f, h) in rows])
        conn.commit()
    finally:
        conn.close()
    return path


@unittest.skipUnless(g3c.G1A_PATH.exists(), "G1A ledger absent")
class G1LoaderTests(unittest.TestCase):
    def test_g1a_loads_65(self):
        self.assertEqual(len(g3c.load_g1a_rows()), 65)

    def test_g1b_loads_32(self):
        self.assertEqual(len(g3c.load_g1b_rows()), 32)

    def test_g1_rows_are_whitelisted_and_outcome_blind(self):
        rows = g3c.load_g1a_rows() + g3c.load_g1b_rows()
        self.assertEqual(len(rows), 97)
        for r in rows:
            self.assertTrue(set(r).issubset(g3c.G3B_ROW_FIELDS), set(r))
        dumped = json.dumps(rows).lower()
        for banned in ("abnormal", "revisit", "sigma", "raw_return",
                       "market_tickers", "mechanism_family", "state_tag"):
            self.assertNotIn(banned, dumped, banned)


class ReconcileLogicTests(unittest.TestCase):
    def _synthetic(self, cohort, n, start):
        return [g3c.classify_record(
            row_key=f"{cohort}:{i}", cohort=cohort,
            lane=g3c.COHORT_LANE[cohort],
            source_family=g3c.SOURCE_FAMILY[cohort], year="2020",
            text="x") for i in range(start, start + n)]

    def test_reconciles_86_65_32_to_183(self):
        rows = (self._synthetic(g3c.COHORT_ACCEPTED, 86, 0)
                + self._synthetic(g3c.COHORT_G1A, 65, 0)
                + self._synthetic(g3c.COHORT_G1B, 32, 0))
        rec = g3c.reconcile(rows)
        self.assertEqual((rec["accepted"], rec["g1a"], rec["g1b"]),
                         (86, 65, 32))
        self.assertEqual(rec["total"], 183)
        self.assertEqual(rec["unique"], 183)

    def test_reconcile_raises_on_duplicate_row_key(self):
        rows = self._synthetic(g3c.COHORT_G1A, 1, 0) * 2
        with self.assertRaises(ValueError):
            g3c.reconcile(rows)


class AcceptedLoaderIntegrationTests(unittest.TestCase):
    def test_accepted_loader_classifies_on_headline_not_stored_family(self):
        # Seeded accepted rows: a realized row whose STORED family is 'sanction'
        # but whose headline has no keyword must classify as unclassified.
        path = _seed_events_db([
            (1, "2020-03-01", "realized", "sanction",
             "quarterly earnings update"),                 # -> unclassified
            (2, "2021-06-01", "realized", "none",
             "US imposes new tariffs on steel imports"),   # -> tariff
        ])
        try:
            rows = g3c.load_accepted_rows(path)
            by_key = {r["row_key"]: r for r in rows}
            self.assertEqual(len(rows), 2)
            self.assertEqual(by_key["accepted:1"]["klass"], "unclassified")
            self.assertEqual(by_key["accepted:2"]["family"], "tariff")
            self.assertEqual(by_key["accepted:2"]["year"], "2021")
        finally:
            os.remove(path)

    def test_run_overlay_reconciles_seeded_accepted_plus_97(self):
        path = _seed_events_db([
            (1, "2020-03-01", "realized", "none", "US imposes tariffs"),
            (2, "2020-04-01", "realized", "none", "OPEC cuts oil output"),
            (3, "2020-05-01", "realized", "none", "generic company update"),
        ])
        try:
            rec = g3c.reconcile(g3c.run_overlay(path))
            self.assertEqual(rec["accepted"], 3)
            self.assertEqual(rec["g1a"], 65)
            self.assertEqual(rec["g1b"], 32)
            self.assertEqual(rec["total"], 100)
        finally:
            os.remove(path)


# ---------------------------------------------------------------------------
# 6. Attrition summary + deterministic, honestly-framed report
# ---------------------------------------------------------------------------


def _row(cohort, year, klass, family=None):
    return {"row_key": f"{cohort}:{year}:{klass}:{family}", "cohort": cohort,
            "lane": g3c.COHORT_LANE[cohort],
            "source_family": g3c.SOURCE_FAMILY[cohort], "year": year,
            "klass": klass, "family": family,
            "matched": [family] if family else ([] if klass != "multi_match"
                                                else ["a", "b"]),
            "taxonomy_version": g3c.TAXONOMY_VERSION}


class SummarizeTests(unittest.TestCase):
    def _corpus(self):
        # Temporally disjoint like the real data: accepted in 2026, historical
        # in 2018-2024. Coverage is year-independent, so the split-coverage
        # assertions are unaffected.
        rows = []
        # accepted: 2 single, 1 multi, 1 unclassified (coverage 3/4)
        rows += [_row(g3c.COHORT_ACCEPTED, "2026", "single", "tariff"),
                 _row(g3c.COHORT_ACCEPTED, "2026", "single", "sanction"),
                 _row(g3c.COHORT_ACCEPTED, "2026", "multi_match"),
                 _row(g3c.COHORT_ACCEPTED, "2026", "unclassified")]
        # g1a: all unclassified (coverage 0/2)
        rows += [_row(g3c.COHORT_G1A, "2019", "unclassified"),
                 _row(g3c.COHORT_G1A, "2023", "unclassified")]
        # g1b: 1 single, 2 unclassified (coverage 1/3)
        rows += [_row(g3c.COHORT_G1B, "2018", "single", "supply_shock"),
                 _row(g3c.COHORT_G1B, "2022", "unclassified"),
                 _row(g3c.COHORT_G1B, "2024", "unclassified")]
        return rows

    def test_no_arbitrary_early_late_split(self):
        s = g3c.summarize(self._corpus())
        self.assertNotIn("earlier_vs_later", s["differential"])
        self.assertIn("coverage", s["differential"])       # retained
        self.assertIn(g3c.COHORT_G1A, s["per_cohort_year"])  # year-by-year kept

    def test_per_cohort_split_and_coverage(self):
        s = g3c.summarize(self._corpus())
        acc = s["per_cohort"][g3c.COHORT_ACCEPTED]
        self.assertEqual((acc["n"], acc["single"], acc["multi"],
                          acc["unclassified"]), (4, 2, 1, 1))
        self.assertAlmostEqual(acc["coverage"], 0.75)
        self.assertAlmostEqual(
            s["per_cohort"][g3c.COHORT_G1A]["coverage"], 0.0)
        self.assertAlmostEqual(
            s["per_cohort"][g3c.COHORT_G1B]["coverage"], 1 / 3)

    def test_totals_reconcile(self):
        s = g3c.summarize(self._corpus())
        self.assertEqual(s["n"], 9)
        self.assertEqual(s["totals"]["single"], 3)
        self.assertEqual(s["totals"]["multi"], 1)
        self.assertEqual(s["totals"]["unclassified"], 5)

    def test_differential_attrition_present(self):
        s = g3c.summarize(self._corpus())
        diff = s["differential"]["coverage"]
        self.assertGreater(diff[g3c.COHORT_ACCEPTED], diff[g3c.COHORT_G1A])
        self.assertGreater(diff[g3c.COHORT_ACCEPTED], diff[g3c.COHORT_G1B])


class RenderTests(unittest.TestCase):
    _META = {"taxonomy_fingerprint": "abc123", "source_overlay": "x",
             "events_db_sha256": "deadbeef"}

    def _summary(self):
        return g3c.summarize(SummarizeTests()._corpus())

    def test_render_is_byte_deterministic(self):
        s = self._summary()
        a = g3c.render_report(s, meta=self._META)
        b = g3c.render_report(s, meta=self._META)
        self.assertEqual(a, b)
        self.assertTrue(a.endswith("\n"))

    def test_render_carries_honest_framing(self):
        text = g3c.render_report(self._summary(), meta=self._META).lower()
        self.assertIn("g3-comparison-taxonomy-v1", text)
        self.assertIn("source register", text)          # register attribution
        self.assertIn("not the events", text)            # not the mechanisms
        self.assertIn("forbidden", text)                 # forbidden-rescue note
        self.assertNotIn("g4 warning threshold set", text)
        # sampling family is not a mechanism label
        self.assertIn("sampling family", text)

    def test_render_leaks_no_outcome_values(self):
        text = g3c.render_report(self._summary(), meta=self._META).lower()
        for leak in ("abnormal_return", "raw_return", "sector_relative_return",
                     "sigma_ar", "revisit_snapshot"):
            self.assertNotIn(leak, text, leak)

    def test_render_has_no_arbitrary_time_threshold(self):
        text = g3c.render_report(self._summary(), meta=self._META).lower()
        for banned in ("<=2021", ">=2022", "earlier (", "earlier_le",
                       "later_ge", "earlier <=", "later >="):
            self.assertNotIn(banned, text, banned)

    def test_render_discloses_temporal_disjointness(self):
        text = g3c.render_report(self._summary(), meta=self._META).lower()
        self.assertIn("strongly consistent", text)
        self.assertIn("temporally disjoint", text)
        self.assertIn("calendar-time language drift", text)
        self.assertIn("cannot be cleanly isolated", text)
        self.assertIn("2026", text)          # accepted span (this corpus)
        self.assertIn("2018-2024", text)     # historical span (this corpus)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
