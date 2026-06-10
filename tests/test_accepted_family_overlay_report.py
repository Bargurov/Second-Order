"""Tests for scripts/accepted_family_overlay_report.py (read-only overlay).

The overlay classifies the accepted thesis (track-record) rows into mechanism
families with deterministic whole-token rules, entirely in memory: labels are
never written to the DB, ambiguous rows are surfaced instead of forced, and
every split is coverage decomposition - never family performance inference.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
import uuid

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from scripts import accepted_family_overlay_report as O  # noqa: E402


_EVENTS_DDL = """
CREATE TABLE events (
    id               INTEGER PRIMARY KEY,
    event_date       TEXT,
    stage            TEXT,
    mechanism_family TEXT,
    headline         TEXT,
    market_tickers   TEXT
)
""".strip()

_PRICE_CACHE_DDL = """
CREATE TABLE price_cache (
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,
    close       REAL,
    volume      REAL,
    auto_adjust INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (ticker, date, auto_adjust)
)
""".strip()

_EVENT_HYGIENE_DDL = """
CREATE TABLE event_hygiene (
    event_id        INTEGER PRIMARY KEY,
    override_class  TEXT,
    override_reason TEXT,
    created_at      TEXT
)
""".strip()


def _mt(*symbols):
    return json.dumps([{"symbol": s, "role": "exposed"} for s in symbols])


def _file_sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_afo_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(self._tmp)
        try:
            conn.execute(_EVENTS_DDL)
            conn.execute(_PRICE_CACHE_DDL)
            conn.execute(_EVENT_HYGIENE_DDL)
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def _seed(self, event_id, headline, *, stage="realized", family="none",
              event_date="2026-01-05", tickers=("SPY",)):
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?)",
                (event_id, event_date, stage, family, headline, _mt(*tickers)),
            )
            conn.commit()

    def _mark_synthetic(self, event_id):
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO event_hygiene VALUES (?, 'synthetic_seed', 'r', 't')",
                (event_id,),
            )
            conn.commit()

    def _seed_mixed_corpus(self):
        """Thesis rows across families plus excluded rows of every kind."""
        self._seed(1, "US imposes new tariffs on electric vehicle imports")
        self._seed(2, "US imposes sanctions on foreign chipmaker")
        self._seed(3, "OPEC extends voluntary oil output cuts through quarter")
        self._seed(4, "Federal Reserve keeps interest rates unchanged")
        self._seed(5, "Iran threatens to close the Strait of Hormuz "
                      "after new US sanctions")          # multi: sanction+supply
        self._seed(6, "Artemis II crew now halfway to Moon")  # unclassified
        # excluded rows - must never enter the overlay target
        self._seed(7, "Tariff observation row", stage="curated_observation",
                   family="tariff")
        self._seed(8, "Staged tariff candidate", stage="z1a_candidate_pack",
                   family="regulation")
        self._seed(9, "Synthetic seed row")
        self._mark_synthetic(9)

    def _family_block(self, overlay, family):
        for row in overlay["family_counts"]:
            if row["family"] == family:
                return row
        return None


class TestTargetSelection(_Base):
    def test_overlay_targets_thesis_rows_only(self):
        self._seed_mixed_corpus()
        overlay = O.build_overlay(db_path=self._tmp)
        d = overlay["denominators"]
        self.assertEqual(d["archive_rows"], 9)
        self.assertEqual(d["accepted_coverage_denominator"], 7)
        self.assertEqual(d["accepted_track_record_denominator"], 6)
        self.assertEqual(d["staged_candidate_count"], 1)
        self.assertEqual(d["overlay_target_count"], 6)

    def test_excluded_rows_never_appear_in_overlay_lists(self):
        self._seed_mixed_corpus()
        overlay = O.build_overlay(db_path=self._tmp)
        listed = set()
        for row in overlay["family_counts"]:
            listed.update(row["representative_event_ids"])
        listed.update(overlay["unclassified_or_review_needed"]
                      ["representative_event_ids"])
        listed.update(overlay["ambiguous_or_multi_match"]
                      ["representative_event_ids"])
        self.assertFalse(listed & {7, 8, 9})

    def test_empty_db_degrades_gracefully(self):
        overlay = O.build_overlay(db_path=self._tmp)
        self.assertEqual(overlay["denominators"]["overlay_target_count"], 0)
        self.assertEqual(overlay["unclassified_or_review_needed"]["count"], 0)


class TestNoWrite(_Base):
    def test_build_overlay_never_writes_to_database(self):
        self._seed_mixed_corpus()
        before = _file_sha256(self._tmp)
        O.build_overlay(db_path=self._tmp)
        self.assertEqual(_file_sha256(self._tmp), before)

    def test_db_family_field_still_untagged_after_run(self):
        self._seed(1, "US imposes new tariffs on imports")
        O.build_overlay(db_path=self._tmp)
        with sqlite3.connect(self._tmp) as conn:
            fam = conn.execute(
                "SELECT mechanism_family FROM events WHERE id = 1").fetchone()[0]
        self.assertEqual(fam, "none")

    def test_overlay_scope_declares_no_write(self):
        self._seed_mixed_corpus()
        overlay = O.build_overlay(db_path=self._tmp)
        scope = overlay["overlay_scope"]
        self.assertEqual(scope["db_write_status"], "not_written")
        self.assertIs(scope["overlay_only"], True)
        self.assertEqual(scope["classifier_type"], "deterministic_rules")
        self.assertIn("headline", scope["classification_basis_fields"])


class TestClassification(_Base):
    def test_obvious_examples_land_in_expected_families(self):
        self._seed_mixed_corpus()
        overlay = O.build_overlay(db_path=self._tmp)
        for family, eid in (("tariff", 1), ("sanction", 2),
                            ("supply_shock", 3),
                            ("monetary_policy_or_rates", 4)):
            block = self._family_block(overlay, family)
            self.assertIsNotNone(block, family)
            self.assertEqual(block["row_count"], 1, family)
            self.assertIn(eid, block["representative_event_ids"], family)

    def test_multi_match_is_surfaced_not_forced(self):
        self._seed_mixed_corpus()
        overlay = O.build_overlay(db_path=self._tmp)
        multi = overlay["ambiguous_or_multi_match"]
        self.assertEqual(multi["count"], 1)
        self.assertIn(5, multi["representative_event_ids"])
        for row in overlay["family_counts"]:
            self.assertNotIn(5, row["representative_event_ids"])
        self.assertTrue(multi["how_resolved"])

    def test_whole_token_matching_avoids_substring_hits(self):
        # 'oil' inside 'turmoil' and 'war' inside 'warns' must not fire.
        self._seed(1, "Political turmoil continues in the region")
        self._seed(2, "Company warns of long delivery delays")
        overlay = O.build_overlay(db_path=self._tmp)
        self.assertEqual(overlay["unclassified_or_review_needed"]["count"], 2)
        for row in overlay["family_counts"]:
            self.assertEqual(row["row_count"], 0, row["family"])

    def test_counts_sum_to_overlay_target(self):
        self._seed_mixed_corpus()
        overlay = O.build_overlay(db_path=self._tmp)
        total = (sum(r["row_count"] for r in overlay["family_counts"])
                 + overlay["ambiguous_or_multi_match"]["count"]
                 + overlay["unclassified_or_review_needed"]["count"])
        self.assertEqual(total,
                         overlay["denominators"]["overlay_target_count"])

    def test_unclassified_is_explicit_with_reason(self):
        self._seed_mixed_corpus()
        overlay = O.build_overlay(db_path=self._tmp)
        unc = overlay["unclassified_or_review_needed"]
        self.assertEqual(unc["count"], 1)
        self.assertIn(6, unc["representative_event_ids"])
        self.assertTrue(unc["reason"])

    def test_representative_examples_capped(self):
        for i, eid in enumerate((1, 2, 3)):
            self._seed(eid, f"US imposes new tariffs round {i}")
        overlay = O.build_overlay(db_path=self._tmp, include_examples=2)
        block = self._family_block(overlay, "tariff")
        self.assertEqual(block["row_count"], 3)
        self.assertEqual(len(block["representative_event_ids"]), 2)
        self.assertEqual(len(block["representative_headlines"]), 2)


class TestRulesAndSplits(_Base):
    def test_family_rules_documented_and_canonical_flagged(self):
        self._seed_mixed_corpus()
        overlay = O.build_overlay(db_path=self._tmp)
        rules = {r["family"]: r for r in overlay["family_rules"]}
        self.assertIn("tariff", rules)
        self.assertIn("tariff", rules["tariff"]["include_terms"])
        for r in rules.values():
            self.assertTrue(r["rationale"], r["family"])
            self.assertIn("canonical_family", r)
        self.assertIs(rules["monetary_policy_or_rates"]["canonical_family"],
                      False)
        self.assertIs(rules["tariff"]["canonical_family"], True)

    def test_descriptive_splits_marked_coverage_only(self):
        self._seed_mixed_corpus()
        overlay = O.build_overlay(db_path=self._tmp)
        splits = overlay["descriptive_splits_if_available"]
        self.assertTrue(splits["splits"])
        for s in splits["splits"]:
            self.assertIs(s["descriptive_only"], True)
            self.assertIs(s["no_family_level_inference"], True)
            outcome_total = sum(s["any_support_outcomes"].values())
            self.assertEqual(outcome_total, s["n"])
        by_family = {s["family"]: s for s in splits["splits"]}
        self.assertEqual(by_family["tariff"]["n"], 1)
        self.assertIn("coverage decomposition", splits["note"].lower())


class TestDiscipline(_Base):
    def test_non_claims_cover_required_ground(self):
        self._seed_mixed_corpus()
        overlay = O.build_overlay(db_path=self._tmp)
        blob = " ".join(overlay["non_claims"]).lower()
        for needle in ("overlay", "not db labels", "no database write",
                       "family-level", "performance", "significance",
                       "recommendation", "fdr", "no paid", "denominator"):
            self.assertIn(needle, blob)

    def test_taxonomy_readout_present(self):
        self._seed_mixed_corpus()
        overlay = O.build_overlay(db_path=self._tmp)
        tr = overlay["taxonomy_readout"]
        self.assertTrue(tr["what_the_overlay_reveals"])
        self.assertTrue(tr["what_remains_missing"])
        self.assertTrue(tr["suggested_next_no_mutation_improvements"])


class TestRendering(_Base):
    def test_text_render_cp1252_with_required_sections(self):
        self._seed_mixed_corpus()
        overlay = O.build_overlay(db_path=self._tmp)
        text = O._render_text(overlay)
        text.encode("cp1252")
        low = text.lower()
        for section in ("family coverage", "unclassified",
                        "overlay, not db labels",
                        "coverage decomposition, not family performance",
                        "taxonomy", "non-claims"):
            self.assertIn(section, low)

    def test_banned_framing_absent_from_source_and_output(self):
        self._seed_mixed_corpus()
        overlay = O.build_overlay(db_path=self._tmp)
        text = O._render_text(overlay) + " " + json.dumps(overlay)
        with open(os.path.join(_REPO, "scripts",
                               "accepted_family_overlay_report.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        blob = (text + " " + src).lower()
        for pattern in (r"trading signal", r"buy/sell recommendation",
                        r"\bforecast\b", r"\bproves\b", r"\bproven\b",
                        r"confirmed mechanism", r"validated.as.success",
                        r"actionable trade", r"\balpha\b"):
            self.assertIsNone(re.search(pattern, blob),
                              f"banned framing {pattern!r} present")


if __name__ == "__main__":
    unittest.main()
