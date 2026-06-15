"""Tests for ``scripts/expanded_case_notes_report.py`` (F2).

Read-only expanded case notes for the 9 newly proposed F1 cases
(7, 29, 38, 71, 153, 154, 160, 212, 239). Each note surfaces event identity,
mechanism text (verbatim from record fields, never fabricated), assets, the
SPY-relative event-study readout where available, the deterministic F1 selection
reason, caveats, and an explicit non-claim. The N1 anchors (1, 46, 61, 66, 210,
211) are referenced but NOT rewritten. Pins:

* exactly the 9 newly proposed ids, in the documented order;
* the readout block is labeled as a different lens from the outcome (29 and 38
  share an identical XLE-vs-SPY readout but have opposite outcomes);
* missing readouts (153, 154, 160) are explicit, not silently omitted;
* mechanism text is the record's own field (incl. honest "insufficient
  evidence" placeholders), never invented when the source is empty;
* event-date-quality labels are populated where available;
* canonical denominators (180 / 94 / 86 / 78-of-94 / 13) are preserved;
* the report mutates nothing and its output is cp1252-safe;
* no proof / significance / forecast / recommendation / trading framing.

The pure ``build_notes`` core runs on synthetic inputs; the DB wiring and the
live specifics run against the live archive (skipped when absent).
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.expanded_case_notes_report import (  # noqa: E402
    NEW_IDS,
    N1_ANCHOR_IDS,
    build_notes,
    build_report,
    render_text,
)

LIVE_DB = ROOT / "events.db"


def _case(eid, fam, outcome, es, **kw):
    return {
        "event_id": eid,
        "headline": kw.get("headline", f"headline {eid}"),
        "event_date": kw.get("date", "2026-04-05"),
        "family": fam,
        "outcome": outcome,
        "event_study_available": es,
        "role": "newly_proposed",
        "assets": kw.get("assets", []),
        "representative_reason": kw.get("reason", f"support example in {fam}"),
        "event_date_quality": kw.get("dq", "clean_discrete_anchor"),
        "caveats": kw.get("caveats", []),
    }


def _readout(primary, ar1, sar1, car1):
    return {"benchmark": "SPY", "primary_ticker": primary,
            "per_horizon": {1: (ar1, sar1, car1), 5: (ar1, sar1, car1),
                            20: (ar1, sar1, car1)}}


# ---------------------------------------------------------------------------
# Pure: build_notes
# ---------------------------------------------------------------------------

class TestBuildNotes(unittest.TestCase):
    def _notes(self, cases, mech=None, read=None):
        return build_notes(cases, mechanism_by_id=mech or {}, readout_by_id=read or {})

    def test_orders_by_new_ids(self):
        cases = [_case(239, "monetary_policy_or_rates", "unresolved", False),
                 _case(7, "geopolitical_conflict_context", "validated", True)]
        notes = self._notes(cases)
        self.assertEqual([n["event_id"] for n in notes], [7, 239])

    def test_each_note_has_required_fields(self):
        notes = self._notes([_case(7, "geopolitical_conflict_context", "validated", True)])
        n = notes[0]
        for k in ("event_id", "headline", "event_date", "family", "outcome",
                  "event_study_available", "why_selected", "mechanism", "assets",
                  "readout", "caveats", "event_date_quality", "non_claim"):
            self.assertIn(k, n)

    def test_readout_available_formats_and_carries_lens_note(self):
        notes = self._notes(
            [_case(7, "geopolitical_conflict_context", "validated", True)],
            read={7: _readout("XLE", -0.075, -1.99, -0.0747)},
        )
        rd = notes[0]["readout"]
        self.assertTrue(rd["available"])
        self.assertEqual(rd["primary_ticker"], "XLE")
        self.assertEqual(rd["horizons"]["5d"]["ar_pct"], -7.5)
        self.assertEqual(rd["horizons"]["5d"]["sar"], -1.99)
        self.assertIn("lens_note", rd)
        self.assertIn("not", rd["lens_note"].lower())  # it is a separating statement

    def test_readout_missing_is_explicit(self):
        notes = self._notes([_case(160, "ceasefire_deescalation", "unresolved", False)])
        rd = notes[0]["readout"]
        self.assertFalse(rd["available"])
        self.assertIn("note", rd)
        self.assertEqual(rd["horizons"], {})

    def test_mechanism_unavailable_when_source_empty_not_fabricated(self):
        notes = self._notes(
            [_case(7, "geopolitical_conflict_context", "validated", True)],
            mech={7: {"mechanism_summary": None, "what_changed": None,
                      "transmission_chain": []}},
        )
        m = notes[0]["mechanism"]
        self.assertFalse(m["available"])
        # rendered text states unavailability rather than inventing content
        txt = render_text({"denominators": {}, "new_ids": [7],
                           "n1_anchor_ids": list(N1_ANCHOR_IDS), "notes": notes,
                           "non_claims": [], "reproduce_command": "x"})
        self.assertIn("mechanism text unavailable", txt.lower())

    def test_identical_readout_opposite_outcome_both_carry_lens_note(self):
        cases = [_case(29, "supply_shock", "contradicted", True),
                 _case(38, "supply_shock", "validated", True)]
        rd = _readout("XLE", -0.075, -1.985, -0.0747)
        notes = self._notes(cases, read={29: rd, 38: rd})
        by = {n["event_id"]: n for n in notes}
        self.assertNotEqual(by[29]["outcome"], by[38]["outcome"])
        self.assertEqual(by[29]["readout"]["horizons"], by[38]["readout"]["horizons"])
        self.assertIn("lens_note", by[29]["readout"])
        self.assertIn("lens_note", by[38]["readout"])

    def test_non_claim_present_and_clean(self):
        notes = self._notes([_case(7, "geopolitical_conflict_context", "validated", True)])
        nc = notes[0]["non_claim"].lower()
        self.assertIn("illustrative case note", nc)
        self.assertIn("not evidence", nc)


# ---------------------------------------------------------------------------
# Live wiring
# ---------------------------------------------------------------------------

@unittest.skipUnless(LIVE_DB.exists(), "live events.db not present")
class TestLiveCaseNotes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_report(db_path=str(LIVE_DB))
        cls.by = {n["event_id"]: n for n in cls.report["notes"]}

    def test_exactly_nine_new_ids(self):
        self.assertEqual([n["event_id"] for n in self.report["notes"]], list(NEW_IDS))
        self.assertEqual(sorted(NEW_IDS), [7, 29, 38, 71, 153, 154, 160, 212, 239])

    def test_n1_anchors_referenced_not_rewritten(self):
        note_ids = {n["event_id"] for n in self.report["notes"]}
        self.assertEqual(note_ids & set(N1_ANCHOR_IDS), set())
        self.assertEqual(list(self.report["n1_anchor_ids"]), list(N1_ANCHOR_IDS))

    def test_event_38_is_supply_shock_support(self):
        self.assertEqual(self.by[38]["family"], "supply_shock")
        self.assertEqual(self.by[38]["outcome"], "validated")

    def test_event_29_is_supply_shock_contradiction(self):
        self.assertEqual(self.by[29]["family"], "supply_shock")
        self.assertEqual(self.by[29]["outcome"], "contradicted")

    def test_29_and_38_identical_readout_opposite_outcome(self):
        self.assertNotEqual(self.by[29]["outcome"], self.by[38]["outcome"])
        self.assertEqual(self.by[29]["readout"]["horizons"],
                         self.by[38]["readout"]["horizons"])
        self.assertIn("lens_note", self.by[29]["readout"])
        self.assertIn("lens_note", self.by[38]["readout"])

    def test_153_154_thin_sanction_unresolved(self):
        for i in (153, 154):
            self.assertEqual(self.by[i]["family"], "sanction")
            self.assertEqual(self.by[i]["outcome"], "unresolved")
            self.assertIn("thin family", self.by[i]["why_selected"].lower())

    def test_160_ceasefire_unresolved_missing_readout(self):
        self.assertEqual(self.by[160]["family"], "ceasefire_deescalation")
        self.assertEqual(self.by[160]["outcome"], "unresolved")
        self.assertFalse(self.by[160]["readout"]["available"])

    def test_239_monetary_overlay_only_unresolved(self):
        self.assertEqual(self.by[239]["family"], "monetary_policy_or_rates")
        self.assertEqual(self.by[239]["outcome"], "unresolved")
        self.assertIn("overlay-only", self.by[239]["why_selected"].lower())

    def test_event_study_availability_surfaced(self):
        # six available, three not (153, 154, 160)
        avail = {i for i, n in self.by.items() if n["readout"]["available"]}
        self.assertEqual(avail, {7, 29, 38, 71, 212, 239})

    def test_missing_readouts_explicit(self):
        for i in (153, 154, 160):
            self.assertFalse(self.by[i]["readout"]["available"])
            self.assertIn("note", self.by[i]["readout"])

    def test_event_date_quality_populated(self):
        for n in self.report["notes"]:
            self.assertIsInstance(n["event_date_quality"], str)
            self.assertTrue(n["event_date_quality"])

    def test_mechanism_grounded_not_fabricated(self):
        # event 38's record carries an honest "insufficient evidence" summary;
        # the note must surface that text rather than invent a mechanism
        m = self.by[38]["mechanism"]
        self.assertTrue(m["available"])
        self.assertIn("insufficient", (m["mechanism_summary"] or "").lower())

    def test_canonical_denominators_preserved(self):
        d = self.report["denominators"]
        self.assertEqual(d["archive_rows"], 180)
        self.assertEqual(d["accepted_coverage_denominator"], 94)
        self.assertEqual(d["accepted_track_record_denominator"], 86)
        self.assertEqual(d["event_study_available_count"], 78)
        self.assertEqual(d["event_study_coverage_denominator"], 94)
        self.assertEqual(d["staged_candidates"], 13)

    def test_read_only_does_not_mutate_db(self):
        before = hashlib.sha256(LIVE_DB.read_bytes()).hexdigest()
        build_report(db_path=str(LIVE_DB))
        after = hashlib.sha256(LIVE_DB.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_text_render_is_cp1252_safe(self):
        txt = render_text(self.report)
        txt.encode("cp1252")  # raises if not safe

    def test_no_banned_framing(self):
        import re
        blob = json.dumps(self.report).lower()
        for w in ["proof", "proven", "statistically significant",
                  "validated-as-success", "trading signal", "alpha"]:
            self.assertNotIn(w, blob, f"banned term {w!r}")
        for w in ["buy", "sell"]:
            self.assertIsNone(re.search(rf"\b{w}\b", blob), f"banned word {w!r}")
        # forecast / recommendation are allowed only inside negated non-claims
        residue = blob
        for negated in ("no recommendation or forecast",
                        "not a recommendation of any kind, and no forecast",
                        "no forecast", "not a recommendation"):
            residue = residue.replace(negated, "")
        self.assertNotIn("forecast", residue)
        self.assertNotIn("recommendation", residue)


if __name__ == "__main__":
    unittest.main()
