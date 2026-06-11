"""Tests for scripts/accepted_family_overlay_review.py (read-only review).

K1 builds a reviewer-legible diagnostic over the J1 overlay's two weak
buckets - the multi-match rows and the unclassified / review-needed rows.
It explains WHY each row landed there, proposes (never applies) bounded
rule refinements, and refuses to force ambiguous rows into a family.

Discipline mirrored from the J1 tests:
  * The review CONSUMES the J1 overlay output; it does not reselect the
    target corpus independently.
  * Nothing is written to events.db.
  * Multi-match rows keep every matched family; unclassified rows keep an
    honest reason category - no family is assigned to them.
  * No family-level inference, no significance, no banned framing.
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

from scripts import accepted_family_overlay_review as R  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

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


def _synthetic_overlay(*, multi=(), unclassified=(), single_count=0,
                       denoms=None):
    """Minimal overlay dict in the exact shape build_review consumes.

    multi: iterable of (event_id, [families...])
    unclassified: iterable of (event_id, headline)
    """
    multi = list(multi)
    unclassified = list(unclassified)
    d = {
        "archive_rows": 180,
        "accepted_coverage_denominator": 94,
        "accepted_track_record_denominator": 86,
        "staged_candidate_count": 13,
        "overlay_target_count": single_count + len(multi) + len(unclassified),
    }
    if denoms:
        d.update(denoms)
    return {
        "denominators": d,
        "family_counts": [
            {"family": "supply_shock", "row_count": single_count},
        ],
        "ambiguous_or_multi_match": {
            "count": len(multi),
            "representative_event_ids": [eid for eid, _ in multi],
            "matched_family_sets": [list(fams) for _, fams in multi],
        },
        "unclassified_or_review_needed": {
            "count": len(unclassified),
            "representative_event_ids": [eid for eid, _ in unclassified],
            "representative_headlines": [h for _, h in unclassified],
        },
    }


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_afor_{uuid.uuid4().hex}.db",
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

    def _seed_weak_bucket_corpus(self):
        """Real ids/headlines that reproduce the live weak buckets."""
        # single-match thesis rows
        self._seed(1, "US imposes new tariffs on electric vehicle imports")
        self._seed(3, "OPEC extends voluntary oil output cuts this quarter")
        # multi-match: sanction + supply (the Hormuz-after-sanctions row)
        self._seed(37, "Reuters: Iran threatens to close the Strait of "
                       "Hormuz after new US sanctions")
        # unclassified, curated off-topic
        self._seed(2, "Artemis II crew now halfway to Moon as they take "
                      "'spectacular' image of Earth")
        # unclassified, curated rule-miss (oil supply cut without oil token)
        self._seed(218, "Saudi Arabia signals deeper voluntary cuts via "
                        "export reductions in May")


# ---------------------------------------------------------------------------
# Consumes the J1 overlay (does not reselect)
# ---------------------------------------------------------------------------


class TestConsumesJ1Overlay(_Base):
    def test_source_report_is_named(self):
        ov = _synthetic_overlay(single_count=1)
        review = R.build_review(overlay=ov, records=[])
        self.assertEqual(review["review_scope"]["source_report"],
                         "accepted_family_overlay_report")

    def test_review_reflects_injected_overlay_counts(self):
        ov = _synthetic_overlay(
            single_count=5,
            multi=[(37, ["sanction", "supply_shock"])],
            unclassified=[(2, "Artemis II crew now halfway to Moon")],
        )
        review = R.build_review(overlay=ov, records=[])
        sc = review["review_scope"]["source_counts"]
        self.assertEqual(sc["single_match"], 5)
        self.assertEqual(sc["multi_match"], 1)
        self.assertEqual(sc["unclassified_or_review_needed"], 1)
        self.assertEqual(review["multi_match_diagnostics"]["count"], 1)
        self.assertEqual(review["unclassified_diagnostics"]["count"], 1)

    def test_review_buckets_match_overlay_on_fixture_db(self):
        from scripts import accepted_family_overlay_report as O
        self._seed_weak_bucket_corpus()
        overlay = O.build_overlay(db_path=self._tmp, limit=10000)
        review = R.build_review(db_path=self._tmp)
        mm_ids = {r["event_id"]
                  for r in review["multi_match_diagnostics"]["rows"]}
        unc_ids = {r["event_id"]
                   for r in review["unclassified_diagnostics"]["rows"]}
        self.assertEqual(
            mm_ids,
            set(overlay["ambiguous_or_multi_match"]["representative_event_ids"]))
        self.assertEqual(
            unc_ids,
            set(overlay["unclassified_or_review_needed"]
                ["representative_event_ids"]))

    def test_raises_on_truncated_overlay_lists(self):
        # count says 3 but only 1 id provided -> diagnosing a silent subset.
        ov = _synthetic_overlay(single_count=1)
        ov["unclassified_or_review_needed"]["count"] = 3
        with self.assertRaises(ValueError):
            R.build_review(overlay=ov, records=[])


# ---------------------------------------------------------------------------
# Multi-match diagnostics
# ---------------------------------------------------------------------------


class TestMultiMatchDiagnostics(_Base):
    def test_rows_surface_all_matched_families(self):
        ov = _synthetic_overlay(
            multi=[(3, ["supply_shock", "geopolitical_conflict_context"])])
        review = R.build_review(overlay=ov, records=[])
        row = review["multi_match_diagnostics"]["rows"][0]
        self.assertEqual(set(row["matched_families"]),
                         {"supply_shock", "geopolitical_conflict_context"})

    def test_conflict_supply_is_legitimate_overlap(self):
        d = R.diagnose_multi(["supply_shock", "geopolitical_conflict_context"])
        self.assertEqual(d["category"], "legitimate_overlap")
        self.assertTrue(d["why"])
        self.assertTrue(d["recommendation"])

    def test_supply_ceasefire_is_legitimate_overlap(self):
        d = R.diagnose_multi(["supply_shock", "ceasefire_deescalation"])
        self.assertEqual(d["category"], "legitimate_overlap")

    def test_sanction_supply_is_legitimate_overlap(self):
        d = R.diagnose_multi(["sanction", "supply_shock"])
        self.assertEqual(d["category"], "legitimate_overlap")

    def test_tariff_conflict_is_overfit_risk(self):
        # The conflict 'war' token mis-fires on the 'trade war' metaphor.
        d = R.diagnose_multi(["tariff", "geopolitical_conflict_context"])
        self.assertEqual(d["category"], "overfit_risk")
        self.assertIn("trade war", (d["why"] + d["recommendation"]).lower())

    def test_unknown_multi_set_defaults_to_review_needed(self):
        d = R.diagnose_multi(["tariff", "labor_inflation"])
        self.assertEqual(d["category"], "review_needed")

    def test_family_set_order_is_irrelevant(self):
        a = R.diagnose_multi(["supply_shock", "sanction"])
        b = R.diagnose_multi(["sanction", "supply_shock"])
        self.assertEqual(a["category"], b["category"])


# ---------------------------------------------------------------------------
# Unclassified diagnostics
# ---------------------------------------------------------------------------


class TestUnclassifiedDiagnostics(_Base):
    def test_every_row_has_reason_category_and_text(self):
        ov = _synthetic_overlay(
            unclassified=[(2, "Artemis II crew now halfway to Moon"),
                          (218, "Saudi Arabia signals deeper voluntary "
                                "cuts via export reductions in May")])
        review = R.build_review(overlay=ov, records=[])
        for row in review["unclassified_diagnostics"]["rows"]:
            self.assertIn(row["diagnosis_category"], R.ALLOWED_CATEGORIES)
            self.assertTrue(row["why_unclassified"])
            self.assertTrue(row["recommendation"])

    def test_off_topic_row_flagged(self):
        d = R.diagnose_unclassified(
            2, "Artemis II crew now halfway to Moon as they take "
               "'spectacular' image of Earth")
        self.assertEqual(d["category"], "off_topic_or_noise")

    def test_rule_miss_candidate_flagged(self):
        # Saudi export cuts = an oil-supply story with no oil/opec token.
        d = R.diagnose_unclassified(
            218, "Saudi Arabia signals deeper voluntary cuts via export "
                 "reductions in May")
        self.assertEqual(d["category"], "rule_miss_candidate")

    def test_taxonomy_gap_flagged(self):
        d = R.diagnose_unclassified(
            235, "South Korea's Export Growth Stays Strong on "
                 "Semiconductor Demand")
        self.assertEqual(d["category"], "taxonomy_gap")

    def test_unclassified_rows_carry_no_assigned_family(self):
        ov = _synthetic_overlay(
            unclassified=[(2, "Artemis II crew now halfway to Moon")])
        review = R.build_review(overlay=ov, records=[])
        row = review["unclassified_diagnostics"]["rows"][0]
        # diagnosis only - never a resolved family label.
        self.assertNotIn("assigned_family", row)
        self.assertNotIn("matched_families", row)

    def test_uncurated_id_defaults_to_review_needed(self):
        d = R.diagnose_unclassified(999999, "Some brand new headline")
        self.assertEqual(d["category"], "review_needed")

    def test_curated_label_downgrades_when_headline_drifts(self):
        # id 2 is curated off-topic, but if its headline no longer matches
        # the frozen snapshot the curated label must NOT be applied.
        d = R.diagnose_unclassified(2, "A completely different headline now")
        self.assertEqual(d["category"], "review_needed")

    def test_duplicate_headlines_flagged(self):
        ov = _synthetic_overlay(
            unclassified=[(2, "Artemis II crew now halfway to Moon"),
                          (49, "Artemis II crew now halfway to Moon")])
        review = R.build_review(overlay=ov, records=[])
        dups = [r for r in review["unclassified_diagnostics"]["rows"]
                if r.get("duplicate_of")]
        self.assertTrue(dups)


# ---------------------------------------------------------------------------
# Pattern summary
# ---------------------------------------------------------------------------


class TestPatternSummary(_Base):
    def test_summary_has_all_required_category_keys(self):
        ov = _synthetic_overlay(single_count=1)
        review = R.build_review(overlay=ov, records=[])
        ps = review["pattern_summary"]
        for key in ("legitimate_overlap_count", "taxonomy_gap_count",
                    "terse_or_missing_context_count",
                    "off_topic_or_noise_count", "rule_miss_candidate_count",
                    "overfit_risk_count"):
            self.assertIn(key, ps)

    def test_summary_counts_match_row_diagnoses(self):
        ov = _synthetic_overlay(
            multi=[(3, ["supply_shock", "geopolitical_conflict_context"]),
                   (250, ["tariff", "geopolitical_conflict_context"])],
            unclassified=[(2, "Artemis II crew now halfway to Moon"),
                          (218, "Saudi Arabia signals deeper voluntary "
                                "cuts via export reductions in May")])
        review = R.build_review(overlay=ov, records=[])
        ps = review["pattern_summary"]
        # tally categories from the diagnosed rows themselves.
        cats = [r["diagnosis_category"]
                for r in review["multi_match_diagnostics"]["rows"]]
        cats += [r["diagnosis_category"]
                 for r in review["unclassified_diagnostics"]["rows"]]
        self.assertEqual(ps["legitimate_overlap_count"],
                         cats.count("legitimate_overlap"))
        self.assertEqual(ps["overfit_risk_count"], cats.count("overfit_risk"))
        self.assertEqual(ps["off_topic_or_noise_count"],
                         cats.count("off_topic_or_noise"))
        self.assertEqual(ps["rule_miss_candidate_count"],
                         cats.count("rule_miss_candidate"))

    def test_examples_capped_by_include_examples(self):
        ov = _synthetic_overlay(
            multi=[(3, ["supply_shock", "geopolitical_conflict_context"]),
                   (11, ["supply_shock", "geopolitical_conflict_context"]),
                   (12, ["supply_shock", "geopolitical_conflict_context"])])
        review = R.build_review(overlay=ov, records=[], include_examples=2)
        for ids in review["pattern_summary"]["examples_by_category"].values():
            self.assertLessEqual(len(ids), 2)
        # diagnostic rows themselves stay complete (never capped).
        self.assertEqual(len(review["multi_match_diagnostics"]["rows"]), 3)


# ---------------------------------------------------------------------------
# Proposed / rejected refinements
# ---------------------------------------------------------------------------


class TestRefinements(_Base):
    def test_refinements_are_recommendations_only(self):
        ov = _synthetic_overlay(single_count=1)
        review = R.build_review(overlay=ov, records=[])
        refs = review["proposed_rule_refinements"]
        self.assertTrue(refs)
        for r in refs:
            self.assertIn(r["status"], {"consider", "reject", "defer"})
            self.assertTrue(r["risk"], "every refinement must state a risk")
            self.assertTrue(r["affected_examples"])
            # never auto-applied / written.
            self.assertNotIn(r["status"], {"applied", "written"})

    def test_at_least_one_rejected_refinement_with_false_positive_risk(self):
        ov = _synthetic_overlay(single_count=1)
        review = R.build_review(overlay=ov, records=[])
        rejected = [r for r in review["proposed_rule_refinements"]
                    if r["status"] == "reject"]
        self.assertTrue(rejected)
        for r in rejected:
            self.assertTrue(r["risk"])

    def test_db_write_status_not_written(self):
        ov = _synthetic_overlay(single_count=1)
        review = R.build_review(overlay=ov, records=[])
        scope = review["review_scope"]
        self.assertEqual(scope["db_write_status"], "not_written")
        self.assertIs(scope["overlay_only"], True)


# ---------------------------------------------------------------------------
# No write / denominators / discipline
# ---------------------------------------------------------------------------


class TestNoWriteAndDenominators(_Base):
    def test_build_review_never_writes_database(self):
        self._seed_weak_bucket_corpus()
        before = _file_sha256(self._tmp)
        R.build_review(db_path=self._tmp)
        self.assertEqual(_file_sha256(self._tmp), before)

    def test_denominators_passthrough_from_overlay(self):
        self._seed_weak_bucket_corpus()
        review = R.build_review(db_path=self._tmp)
        d = review["denominators"]
        self.assertEqual(d["accepted_coverage_denominator"], 5)
        self.assertEqual(d["accepted_track_record_denominator"], 5)
        for key in ("archive_rows", "staged_candidate_count",
                    "overlay_target_count"):
            self.assertIn(key, d)


class TestDiscipline(_Base):
    def test_non_claims_cover_required_ground(self):
        ov = _synthetic_overlay(single_count=1)
        review = R.build_review(overlay=ov, records=[])
        blob = " ".join(review["non_claims"]).lower()
        for needle in ("not db labels", "no database write", "family-level",
                       "significance", "recommendation", "fdr", "no paid",
                       "denominator"):
            self.assertIn(needle, blob)

    def test_taxonomy_lessons_present(self):
        ov = _synthetic_overlay(single_count=1)
        review = R.build_review(overlay=ov, records=[])
        tl = review["taxonomy_lessons"]
        self.assertTrue(tl["what_the_weak_buckets_reveal"])
        self.assertTrue(tl["what_should_not_be_forced"])
        self.assertTrue(tl["what_can_improve_without_db_write"])

    def test_banned_framing_absent_from_source_and_output(self):
        self._seed_weak_bucket_corpus()
        review = R.build_review(db_path=self._tmp)
        text = R._render_text(review) + " " + json.dumps(review)
        with open(os.path.join(_REPO, "scripts",
                               "accepted_family_overlay_review.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        blob = (text + " " + src).lower()
        for pattern in (r"trading signal", r"buy/sell recommendation",
                        r"\bforecast\b", r"\bproves\b", r"\bproven\b",
                        r"confirmed mechanism", r"validated.as.success",
                        r"actionable trade", r"\balpha\b", r"\bsignal\b"):
            self.assertIsNone(re.search(pattern, blob),
                              f"banned framing {pattern!r} present")


# ---------------------------------------------------------------------------
# Rendering / CLI
# ---------------------------------------------------------------------------


class TestRendering(_Base):
    def test_text_render_cp1252_with_required_sections(self):
        self._seed_weak_bucket_corpus()
        review = R.build_review(db_path=self._tmp)
        text = R._render_text(review)
        text.encode("cp1252")
        low = text.lower()
        for section in ("denominator", "multi-match", "unclassified",
                        "pattern summary", "refinement",
                        "do not force", "non-claims"):
            self.assertIn(section, low)

    def test_text_render_handles_empty_buckets(self):
        ov = _synthetic_overlay(single_count=1)
        review = R.build_review(overlay=ov, records=[])
        text = R._render_text(review)
        self.assertTrue(text)
        text.encode("cp1252")

    def test_main_json_smoke(self):
        self._seed_weak_bucket_corpus()
        rc = R.main(["--db-path", self._tmp, "--json"])
        self.assertEqual(rc, 0)

    def test_main_text_smoke(self):
        self._seed_weak_bucket_corpus()
        rc = R.main(["--db-path", self._tmp])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
