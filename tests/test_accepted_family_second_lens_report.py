"""Tests for scripts/accepted_family_second_lens_report.py (read-only).

L1 compares the J1 headline-only accepted-family overlay against a SECOND
lens that runs the same J1 whole-token family rules over local mechanism-text
fields (mechanism_summary, what_changed, transmission_chain, market_note,
notes). It measures whether richer text resolves headline ambiguity WITHOUT
writing labels, without modifying J1 rules, and without applying K1
refinements.

Discipline mirrored from J1/K1 tests:
  * The report CONSUMES the J1 headline overlay; it does not reselect or
    replace the headline classification.
  * Nothing is written to events.db; mechanism-text fields are read-only.
  * The second-lens label is reported SEPARATELY and never overwrites the
    headline label.
  * Empty / generic mechanism text never manufactures a label.
  * Multi-match rows are not force-resolved without a strong text basis.
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

from scripts import accepted_family_second_lens_report as L  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_EVENTS_DDL = """
CREATE TABLE events (
    id                 INTEGER PRIMARY KEY,
    event_date         TEXT,
    stage              TEXT,
    mechanism_family   TEXT,
    headline           TEXT,
    market_tickers     TEXT,
    revisit_snapshots  TEXT,
    mechanism_summary  TEXT,
    what_changed       TEXT,
    transmission_chain TEXT,
    market_note        TEXT,
    notes              TEXT,
    transmission_path  TEXT
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


def _overlay(*, single=(), multi=(), unclassified=(), denoms=None):
    """Minimal J1 overlay dict in the exact shape build_second_lens consumes.

    single: iterable of (event_id, family)
    multi:  iterable of (event_id, [families...])
    unclassified: iterable of event_id
    """
    single = list(single)
    multi = list(multi)
    unc = list(unclassified)
    fams: dict[str, list[int]] = {}
    for eid, f in single:
        fams.setdefault(f, []).append(eid)
    family_counts = [{"family": f, "row_count": len(e),
                      "representative_event_ids": e} for f, e in fams.items()]
    target = len(single) + len(multi) + len(unc)
    d = {
        "archive_rows": 180,
        "accepted_coverage_denominator": 94,
        "accepted_track_record_denominator": target,
        "staged_candidate_count": 13,
        "overlay_target_count": target,
    }
    if denoms:
        d.update(denoms)
    return {
        "denominators": d,
        "family_counts": family_counts,
        "ambiguous_or_multi_match": {
            "count": len(multi),
            "representative_event_ids": [e for e, _ in multi],
            "matched_family_sets": [list(fs) for _, fs in multi],
        },
        "unclassified_or_review_needed": {
            "count": len(unc),
            "representative_event_ids": list(unc),
        },
    }


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_afsl_{uuid.uuid4().hex}.db",
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
              event_date="2026-01-05", tickers=("SPY",),
              mechanism_summary=None, what_changed=None,
              transmission_chain=None, market_note=None, notes=None,
              transmission_path=None):
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (event_id, event_date, stage, family, headline, _mt(*tickers),
                 None, mechanism_summary, what_changed, transmission_chain,
                 market_note, notes, transmission_path),
            )
            conn.commit()

    def _seed_lens_corpus(self):
        """Rows that exercise each change_type through the live path."""
        # single headline, text agrees -> unchanged_single
        self._seed(1, "US imposes new tariffs on electric vehicle imports",
                   mechanism_summary="Tariff pass-through to imported vehicle "
                                     "prices raises consumer costs over time.")
        # unclassified headline, empty text -> unchanged_unclassified
        self._seed(2, "Artemis II crew now halfway to Moon",
                   mechanism_summary="", what_changed="[]",
                   transmission_chain="[]")
        # unclassified headline, oil text -> resolved_unclassified (single)
        self._seed(3, "Saudi Arabia announces deeper voluntary output cuts",
                   mechanism_summary="OPEC oil output cut tightens crude "
                                     "supply for refineries and lifts the "
                                     "barrel price.")
        # multi headline, text confirms both -> confirmed_multi_match
        self._seed(4, "Iran threatens to close the Strait of Hormuz after "
                      "new US sanctions",
                   mechanism_summary="New US sanctions on Iran escalate; "
                                     "Strait of Hormuz oil tanker supply at "
                                     "risk across the region.")
        # single headline, text adds families -> worsened_or_more_ambiguous
        self._seed(5, "US imposes new tariffs on steel",
                   mechanism_summary="Tariff shock plus oil supply disruption "
                                     "amid war escalation widens the channel.")


# ---------------------------------------------------------------------------
# Consumes J1 headline overlay (does not reselect or replace it)
# ---------------------------------------------------------------------------


class TestConsumesHeadlineOverlay(_Base):
    def test_scope_names_source_report_and_review(self):
        ov = _overlay(single=[(1, "tariff")])
        rep = L.build_second_lens(overlay=ov, records=[
            {"event_id": 1, "headline": "x"}], mech_text={})
        scope = rep["second_lens_scope"]
        self.assertEqual(scope["source_report"],
                         "accepted_family_overlay_report")
        self.assertEqual(scope["source_review"],
                         "accepted_family_overlay_review")

    def test_headline_label_taken_from_overlay_not_recomputed(self):
        # Headline text has no family token, but the overlay says 'tariff'.
        # The report MUST use the overlay's label, proving consumption.
        ov = _overlay(single=[(1, "tariff")])
        rep = L.build_second_lens(
            overlay=ov,
            records=[{"event_id": 1, "headline": "a headline with no token"}],
            mech_text={1: {"mechanism_summary": "nothing relevant here at "
                                                "all in this text body"}})
        row = next(r for r in rep["row_changes"]["rows"]
                   if r["event_id"] == 1)
        self.assertEqual(row["headline_lens_families"], ["tariff"])
        self.assertEqual(row["headline_lens_status"], "single")

    def test_headline_counts_passthrough_from_overlay(self):
        ov = _overlay(single=[(1, "tariff"), (2, "sanction")],
                      multi=[(3, ["sanction", "supply_shock"])],
                      unclassified=[4])
        rep = L.build_second_lens(
            overlay=ov,
            records=[{"event_id": i, "headline": "h"} for i in (1, 2, 3, 4)],
            mech_text={})
        lc = rep["lens_comparison"]
        self.assertEqual(lc["headline_single_match"], 2)
        self.assertEqual(lc["headline_multi_match"], 1)
        self.assertEqual(lc["headline_unclassified"], 1)

    def test_raises_on_truncated_overlay_lists(self):
        ov = _overlay(single=[(1, "tariff")])
        ov["unclassified_or_review_needed"]["count"] = 5  # lie about count
        with self.assertRaises(ValueError):
            L.build_second_lens(overlay=ov, records=[
                {"event_id": 1, "headline": "h"}], mech_text={})


# ---------------------------------------------------------------------------
# Field state / usable text
# ---------------------------------------------------------------------------


class TestFieldState(_Base):
    def test_empty_values_are_empty(self):
        for v in (None, "", "  ", "none", "N/A", "null"):
            self.assertEqual(L.field_state(v), "empty", repr(v))

    def test_json_empty_and_short_are_generic(self):
        self.assertEqual(L.field_state("[]"), "generic")
        self.assertEqual(L.field_state("{}"), "generic")
        self.assertEqual(L.field_state("short"), "generic")

    def test_substantive_text_is_usable(self):
        self.assertEqual(
            L.field_state("OPEC oil output cut tightens crude supply"),
            "usable")

    def test_usable_text_lists_only_usable_basis_fields(self):
        combined, basis = L.usable_text({
            "mechanism_summary": "OPEC oil output cut tightens crude supply",
            "what_changed": "[]",
            "notes": None,
            "market_note": "Brent crude rose on the supply threat overnight.",
        })
        self.assertIn("mechanism_summary", basis)
        self.assertIn("market_note", basis)
        self.assertNotIn("what_changed", basis)
        self.assertNotIn("notes", basis)
        self.assertIn("OPEC", combined)


# ---------------------------------------------------------------------------
# change_type pure function
# ---------------------------------------------------------------------------


class TestChangeType(_Base):
    def test_unclassified_to_single_is_resolved(self):
        self.assertEqual(
            L.change_type(frozenset(), {"supply_shock"}), "resolved_unclassified")

    def test_unclassified_to_multi_is_resolved(self):
        self.assertEqual(
            L.change_type(frozenset(), {"supply_shock", "sanction"}),
            "resolved_unclassified")

    def test_multi_confirmed_when_equal(self):
        s = {"supply_shock", "geopolitical_conflict_context"}
        self.assertEqual(L.change_type(s, set(s)), "confirmed_multi_match")

    def test_multi_narrowed_to_subset_is_clarified(self):
        self.assertEqual(
            L.change_type({"supply_shock", "geopolitical_conflict_context"},
                          {"supply_shock"}), "clarified_multi_match")

    def test_single_to_multi_is_worsened(self):
        self.assertEqual(
            L.change_type({"tariff"}, {"tariff", "supply_shock"}),
            "worsened_or_more_ambiguous")

    def test_multi_to_more_families_is_worsened(self):
        self.assertEqual(
            L.change_type({"supply_shock", "ceasefire_deescalation"},
                          {"supply_shock", "ceasefire_deescalation",
                           "sanction"}),
            "worsened_or_more_ambiguous")

    def test_multi_shifted_family_is_review_needed(self):
        self.assertEqual(
            L.change_type({"supply_shock", "ceasefire_deescalation"},
                          {"supply_shock", "sanction"}), "review_needed")

    def test_text_loses_all_families_is_review_needed(self):
        self.assertEqual(
            L.change_type({"supply_shock", "ceasefire_deescalation"},
                          frozenset()), "review_needed")

    def test_no_text_basis_does_not_resolve(self):
        # Without a text basis, an unclassified row stays unclassified and a
        # multi row needs review - the second lens never invents a label.
        self.assertEqual(
            L.change_type(frozenset(), frozenset(), has_text=False),
            "unchanged_unclassified")
        self.assertEqual(
            L.change_type({"a", "b"}, frozenset(), has_text=False),
            "review_needed")
        self.assertEqual(
            L.change_type({"tariff"}, frozenset(), has_text=False),
            "unchanged_single")


# ---------------------------------------------------------------------------
# Live-path behaviour (fixture DB)
# ---------------------------------------------------------------------------


class TestLivePath(_Base):
    def test_denominator_is_seeded_accepted_count(self):
        self._seed_lens_corpus()
        rep = L.build_second_lens(db_path=self._tmp)
        d = rep["denominators"]
        self.assertEqual(d["accepted_track_record_denominator"], 5)
        self.assertEqual(d["overlay_target_count"], 5)

    def test_resolved_rule_miss_surfaced(self):
        self._seed_lens_corpus()
        rep = L.build_second_lens(db_path=self._tmp)
        row = next(r for r in rep["row_changes"]["rows"]
                   if r["event_id"] == 3)
        self.assertEqual(row["headline_lens_status"], "unclassified")
        self.assertEqual(row["change_type"], "resolved_unclassified")
        self.assertIn("supply_shock", row["second_lens_families"])

    def test_empty_text_does_not_create_label(self):
        self._seed_lens_corpus()
        rep = L.build_second_lens(db_path=self._tmp)
        row = next(r for r in rep["row_changes"]["rows"]
                   if r["event_id"] == 2)
        self.assertEqual(row["second_lens_families"], [])
        self.assertEqual(row["change_type"], "unchanged_unclassified")

    def test_multi_confirmed_not_force_resolved(self):
        self._seed_lens_corpus()
        rep = L.build_second_lens(db_path=self._tmp)
        row = next(r for r in rep["row_changes"]["rows"]
                   if r["event_id"] == 4)
        self.assertEqual(row["headline_lens_status"], "multi")
        self.assertEqual(row["change_type"], "confirmed_multi_match")
        self.assertEqual(len(row["second_lens_families"]), 2)

    def test_rich_text_can_worsen_ambiguity(self):
        self._seed_lens_corpus()
        rep = L.build_second_lens(db_path=self._tmp)
        row = next(r for r in rep["row_changes"]["rows"]
                   if r["event_id"] == 5)
        self.assertEqual(row["headline_lens_status"], "single")
        self.assertEqual(row["change_type"], "worsened_or_more_ambiguous")

    def test_headline_and_second_lens_labels_both_present_and_separate(self):
        self._seed_lens_corpus()
        rep = L.build_second_lens(db_path=self._tmp)
        for row in rep["row_changes"]["rows"]:
            self.assertIn("headline_lens_families", row)
            self.assertIn("second_lens_families", row)

    def test_single_family_over_example_cap_not_truncated(self):
        # A single-match family with more rows than build_overlay's default
        # example cap (3) must NOT trip the truncation guard - build_second_lens
        # has to request the full per-row headline buckets.
        for eid in (10, 11, 12, 13):
            self._seed(eid, f"US imposes new tariffs round {eid}",
                       mechanism_summary="Tariff pass-through to import "
                                         "prices over the coming quarters.")
        rep = L.build_second_lens(db_path=self._tmp)
        tariff_rows = [r for r in rep["row_changes"]["rows"]
                       if r["headline_lens_families"] == ["tariff"]]
        self.assertEqual(len(tariff_rows), 4)

    def test_build_never_writes_database(self):
        self._seed_lens_corpus()
        before = _file_sha256(self._tmp)
        L.build_second_lens(db_path=self._tmp)
        self.assertEqual(_file_sha256(self._tmp), before)

    def test_db_family_column_untouched(self):
        self._seed_lens_corpus()
        L.build_second_lens(db_path=self._tmp)
        with sqlite3.connect(self._tmp) as conn:
            fams = [r[0] for r in conn.execute(
                "SELECT mechanism_family FROM events").fetchall()]
        self.assertTrue(all(f == "none" for f in fams))


# ---------------------------------------------------------------------------
# Field coverage + lens comparison structure
# ---------------------------------------------------------------------------


class TestFieldCoverageAndComparison(_Base):
    def test_field_coverage_reports_unusable_fields_honestly(self):
        self._seed_lens_corpus()
        rep = L.build_second_lens(db_path=self._tmp)
        by_field = {f["field"]: f for f in rep["field_coverage"]}
        # notes seeded empty everywhere -> 0 usable
        self.assertIn("notes", by_field)
        self.assertEqual(by_field["notes"]["usable_count"], 0)
        self.assertGreater(by_field["mechanism_summary"]["usable_count"], 0)

    def test_lens_comparison_counts_are_consistent(self):
        self._seed_lens_corpus()
        rep = L.build_second_lens(db_path=self._tmp)
        lc = rep["lens_comparison"]
        rows = rep["row_changes"]["rows"]
        changed = sum(1 for r in rows
                      if sorted(r["headline_lens_families"])
                      != sorted(r["second_lens_families"]))
        self.assertEqual(lc["changed_count"], changed)
        self.assertEqual(lc["unchanged_count"], len(rows) - changed)

    def test_unresolved_rows_surfaced(self):
        self._seed_lens_corpus()
        rep = L.build_second_lens(db_path=self._tmp)
        self.assertIn("unresolved_or_review_needed", rep)
        self.assertGreaterEqual(rep["unresolved_or_review_needed"]["count"], 1)


# ---------------------------------------------------------------------------
# Discipline / scope flags / non-claims / banned framing
# ---------------------------------------------------------------------------


class TestDiscipline(_Base):
    def test_scope_flags_declare_no_write_and_no_rule_changes(self):
        ov = _overlay(single=[(1, "tariff")])
        rep = L.build_second_lens(overlay=ov, records=[
            {"event_id": 1, "headline": "h"}], mech_text={})
        scope = rep["second_lens_scope"]
        self.assertEqual(scope["db_write_status"], "not_written")
        self.assertIs(scope["overlay_only"], True)
        self.assertIs(scope["headline_lens"], True)
        self.assertIs(scope["mechanism_text_lens"], True)
        self.assertIs(scope["j1_rules_modified"], False)
        self.assertIs(scope["k1_refinements_applied"], False)

    def test_non_claims_cover_required_ground(self):
        ov = _overlay(single=[(1, "tariff")])
        rep = L.build_second_lens(overlay=ov, records=[
            {"event_id": 1, "headline": "h"}], mech_text={})
        blob = " ".join(rep["non_claims"]).lower()
        for needle in ("not db labels", "no database write", "j1 rules",
                       "k1 refinements", "family-level", "significance",
                       "recommendation", "fdr", "no paid", "denominator"):
            self.assertIn(needle, blob)

    def test_taxonomy_lessons_present(self):
        ov = _overlay(single=[(1, "tariff")])
        rep = L.build_second_lens(overlay=ov, records=[
            {"event_id": 1, "headline": "h"}], mech_text={})
        tl = rep["taxonomy_lessons"]
        self.assertTrue(tl["what_second_lens_reveals"])
        self.assertTrue(tl["where_text_fields_help"])
        self.assertTrue(tl["where_text_fields_do_not_help"])
        self.assertTrue(tl["what_should_not_be_forced"])

    def test_banned_framing_absent_from_source_and_output(self):
        self._seed_lens_corpus()
        rep = L.build_second_lens(db_path=self._tmp)
        text = L._render_text(rep) + " " + json.dumps(rep)
        with open(os.path.join(_REPO, "scripts",
                               "accepted_family_second_lens_report.py"),
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
        self._seed_lens_corpus()
        rep = L.build_second_lens(db_path=self._tmp)
        text = L._render_text(rep)
        text.encode("cp1252")
        low = text.lower()
        for section in ("denominator", "field coverage", "headline",
                        "second lens", "row changes", "unresolved",
                        "non-claims"):
            self.assertIn(section, low)

    def test_main_json_smoke(self):
        self._seed_lens_corpus()
        self.assertEqual(L.main(["--db-path", self._tmp, "--json"]), 0)

    def test_main_text_smoke(self):
        self._seed_lens_corpus()
        self.assertEqual(L.main(["--db-path", self._tmp]), 0)


if __name__ == "__main__":
    unittest.main()
