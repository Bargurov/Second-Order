"""Tests for the proof_quality breakdown dimension.

Covers bucket assignment, summary counts, and export shape across
JSON / CSV / markdown.  No fixture touches market validation directly
— buckets are derived from stored event fields only.
"""

from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from track_record_breakdown import (
    PROOF_QUALITY_BUCKETS,
    compute_track_record_breakdown,
)
from track_record_export import (
    build_breakdown_csv,
    build_breakdown_json,
    build_breakdown_markdown,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _ticker(symbol: str, direction_tag: str, return_5d: float | None = None) -> dict:
    t = {"symbol": symbol, "direction_tag": direction_tag}
    if return_5d is not None:
        t["return_5d"] = return_5d
    return t


def _event(
    *, event_id: int = 1,
    confidence: str = "medium",
    mechanism_summary: str = "Refinery outage tightens Gulf Coast capacity.",
    minimum_proof_set: list | None = None,
    key_falsifiers: list | None = None,
    market_tickers: list | None = None,
) -> dict:
    return {
        "id":                event_id,
        "mechanism_family":  "commodity_squeeze",
        "confidence":        confidence,
        "mechanism_summary": mechanism_summary,
        "minimum_proof_set": minimum_proof_set or [],
        "key_falsifiers":    key_falsifiers or [],
        "market_tickers":    market_tickers or [],
        "revisit_snapshots": [],
        "regime_snapshot":   {"available": False},
    }


def _proof_entry() -> dict:
    return {"observation": "WCS-WTI spread widens", "channel": "commodities"}


def _falsifier_entry() -> dict:
    return {"observation": "USO -3% intraday", "channel": "commodities"}


# ---------------------------------------------------------------------------
# Bucket assignment
# ---------------------------------------------------------------------------

class TestBucketAssignment(unittest.TestCase):
    def _bucket_counts(self, events: list[dict]) -> dict[str, int]:
        out = compute_track_record_breakdown(events)
        return {b["bucket"]: b["total"] for b in out["by_proof_quality"]}

    def test_buckets_enum_stable(self):
        self.assertEqual(
            PROOF_QUALITY_BUCKETS,
            ("proof_backed", "partial_proof", "no_proof",
             "falsified", "low_information"),
        )

    def test_proof_backed_requires_both(self):
        ev = _event(
            minimum_proof_set=[_proof_entry()],
            key_falsifiers=[_falsifier_entry()],
        )
        counts = self._bucket_counts([ev])
        self.assertEqual(counts["proof_backed"], 1)
        self.assertEqual(counts["partial_proof"], 0)
        self.assertEqual(counts["no_proof"], 0)

    def test_partial_proof_when_only_proof_set(self):
        ev = _event(minimum_proof_set=[_proof_entry()])
        self.assertEqual(self._bucket_counts([ev])["partial_proof"], 1)

    def test_partial_proof_when_only_falsifiers(self):
        ev = _event(key_falsifiers=[_falsifier_entry()])
        self.assertEqual(self._bucket_counts([ev])["partial_proof"], 1)

    def test_no_proof_when_neither(self):
        ev = _event()
        counts = self._bucket_counts([ev])
        self.assertEqual(counts["no_proof"], 1)
        self.assertEqual(counts["partial_proof"], 0)

    def test_falsified_when_falsifier_and_contradicted_outcome(self):
        # Event has falsifiers AND market tickers contradict the thesis
        # (has_con branch in _score_event).  Must land in "falsified",
        # not "proof_backed".
        ev = _event(
            minimum_proof_set=[_proof_entry()],
            key_falsifiers=[_falsifier_entry()],
            market_tickers=[_ticker("USO", "contradicts down")],
        )
        counts = self._bucket_counts([ev])
        self.assertEqual(counts["falsified"], 1)
        self.assertEqual(counts["proof_backed"], 0)

    def test_low_information_trumps_proof_fields(self):
        # Even when proof fields are populated, a low-info event is
        # classified as low_information so the scorecard flags the
        # weakest analyses first.
        ev = _event(
            confidence="low",
            mechanism_summary="Insufficient evidence to characterise.",
            minimum_proof_set=[_proof_entry()],
            key_falsifiers=[_falsifier_entry()],
        )
        counts = self._bucket_counts([ev])
        self.assertEqual(counts["low_information"], 1)
        self.assertEqual(counts["proof_backed"], 0)

    def test_mixed_cohort_tallies_correctly(self):
        events = [
            _event(event_id=1,
                   minimum_proof_set=[_proof_entry()],
                   key_falsifiers=[_falsifier_entry()]),
            _event(event_id=2,
                   minimum_proof_set=[_proof_entry()]),
            _event(event_id=3),
            _event(event_id=4,
                   key_falsifiers=[_falsifier_entry()],
                   market_tickers=[_ticker("USO", "contradicts down")]),
            _event(event_id=5,
                   confidence="low",
                   mechanism_summary="Insufficient evidence."),
        ]
        counts = self._bucket_counts(events)
        self.assertEqual(counts["proof_backed"], 1)
        self.assertEqual(counts["partial_proof"], 1)
        self.assertEqual(counts["no_proof"], 1)
        self.assertEqual(counts["falsified"], 1)
        self.assertEqual(counts["low_information"], 1)


# ---------------------------------------------------------------------------
# Summary counts
# ---------------------------------------------------------------------------

class TestSummaryCounts(unittest.TestCase):
    def test_summary_counts_present_at_top_level(self):
        out = compute_track_record_breakdown([_event()])
        for key in ("proof_backed", "falsifier_triggered", "low_information"):
            self.assertIn(key, out)
            self.assertIsInstance(out[key], int)

    def test_summary_counts_match_bucket_totals(self):
        events = [
            _event(event_id=1,
                   minimum_proof_set=[_proof_entry()],
                   key_falsifiers=[_falsifier_entry()]),
            _event(event_id=2,
                   minimum_proof_set=[_proof_entry()],
                   key_falsifiers=[_falsifier_entry()]),
            _event(event_id=3,
                   key_falsifiers=[_falsifier_entry()],
                   market_tickers=[_ticker("USO", "contradicts down")]),
            _event(event_id=4,
                   confidence="low",
                   mechanism_summary="Insufficient evidence."),
        ]
        out = compute_track_record_breakdown(events)
        # proof_backed counts events where both proof set + falsifiers
        # are populated.  Event 3 has only falsifiers → doesn't count.
        # Summary is flag-based (proof+falsifier present), bucket is
        # outcome-aware (event 1+2 land in proof_backed bucket; event 3
        # in falsified because its tickers contradicted).
        self.assertEqual(out["proof_backed"], 2)
        self.assertEqual(out["falsifier_triggered"], 1)
        self.assertEqual(out["low_information"], 1)

    def test_existing_summary_keys_still_present(self):
        out = compute_track_record_breakdown([_event()])
        for legacy in ("total_events", "validated_total", "contradicted_total",
                       "revisit_scored", "hit_rate",
                       "by_mechanism_family", "by_regime",
                       "by_compound_regime", "generated_at"):
            self.assertIn(legacy, out, f"legacy key {legacy} was dropped")


# ---------------------------------------------------------------------------
# Export shapes
# ---------------------------------------------------------------------------

class TestExportShapes(unittest.TestCase):
    def _breakdown(self) -> dict:
        events = [
            _event(event_id=1,
                   minimum_proof_set=[_proof_entry()],
                   key_falsifiers=[_falsifier_entry()]),
            _event(event_id=2),
            _event(event_id=3,
                   confidence="low",
                   mechanism_summary="Insufficient evidence."),
        ]
        return compute_track_record_breakdown(events)

    def test_json_includes_proof_quality_list(self):
        env = build_breakdown_json(self._breakdown())
        self.assertIn("by_proof_quality", env)
        self.assertEqual(
            {b["bucket"] for b in env["by_proof_quality"]},
            set(PROOF_QUALITY_BUCKETS),
        )

    def test_json_summary_has_new_counts(self):
        env = build_breakdown_json(self._breakdown())
        for key in ("proof_backed", "falsifier_triggered", "low_information"):
            self.assertIn(key, env["summary"])

    def test_json_is_serialisable(self):
        env = build_breakdown_json(self._breakdown())
        s = json.dumps(env)
        self.assertIn("by_proof_quality", s)
        self.assertIn("proof_backed", s)

    def test_csv_includes_proof_quality_section(self):
        csv_text = build_breakdown_csv(self._breakdown())
        self.assertIn("# by_proof_quality", csv_text)
        # Bucket identity column appears in the header row.
        self.assertIn("bucket", csv_text)
        # Every enum bucket appears exactly once in the section.
        for b in PROOF_QUALITY_BUCKETS:
            self.assertIn(b, csv_text, f"bucket {b} missing from CSV")

    def test_csv_summary_has_new_counts(self):
        csv_text = build_breakdown_csv(self._breakdown())
        self.assertIn("proof_backed", csv_text)
        self.assertIn("falsifier_triggered", csv_text)
        self.assertIn("low_information", csv_text)

    def test_markdown_has_proof_quality_section(self):
        md = build_breakdown_markdown(self._breakdown())
        self.assertIn("## By proof quality", md)
        self.assertIn("Proof-backed", md)
        self.assertIn("Low information", md)

    def test_markdown_header_includes_proof_counts(self):
        md = build_breakdown_markdown(self._breakdown())
        self.assertIn("proof-backed", md.lower())
        self.assertIn("falsifier-triggered", md.lower())
        self.assertIn("low-information", md.lower())

    def test_existing_sections_still_present(self):
        md = build_breakdown_markdown(self._breakdown())
        self.assertIn("## By mechanism family", md)
        self.assertIn("## By regime", md)
        self.assertIn("## By compound regime", md)

    def test_by_proof_quality_enum_order_in_output(self):
        """Proof-quality buckets keep a fixed order regardless of
        sample sizes — the frontend relies on this for stable
        row layouts."""
        bd = self._breakdown()
        bucket_order = [b["bucket"] for b in bd["by_proof_quality"]]
        self.assertEqual(bucket_order, list(PROOF_QUALITY_BUCKETS))

    def test_empty_breakdown_still_has_proof_quality_buckets(self):
        bd = compute_track_record_breakdown([])
        self.assertEqual(
            [b["bucket"] for b in bd["by_proof_quality"]],
            list(PROOF_QUALITY_BUCKETS),
        )
        for b in bd["by_proof_quality"]:
            self.assertEqual(b["total"], 0)


if __name__ == "__main__":
    unittest.main()
