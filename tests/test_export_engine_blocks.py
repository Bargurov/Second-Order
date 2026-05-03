"""
tests/test_export_engine_blocks.py

Contract tests for the new macro-engine outputs surfaced on export:

  1. ``horizon_checkpoints`` present as a persisted column on CSV
     + JSON exports.
  2. ``thesis_scorecard`` computed from persisted fields and attached
     to single-event + bulk JSON exports.
  3. ``finance_playbook`` attached to single-event + bulk JSON exports;
     degrades gracefully on rows missing upstream blocks.
  4. Text + markdown memos render Horizon Checkpoints and Thesis
     Scorecard sections when the source data exists, and silently
     skip them when it doesn't.
  5. ``events_export.enrich_event_with_derived`` is idempotent and
     pure — never raises on partial inputs.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from events_export import (
    CSV_COLUMNS,
    build_csv_export,
    build_json_export,
    enrich_event_with_derived,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _checkpoints() -> dict:
    """Minimal but realistic horizon_checkpoints payload."""
    return {
        "timing_profile": "fast_shock",
        "horizons": [
            {"horizon": "1d",
             "expected":     ["XOM +1-2% intraday"],
             "confirms_if":  ["XOM closes green on volume"],
             "falsifies_if": ["XOM closes red with broader energy rally"]},
            {"horizon": "5d",
             "expected":     ["Spread vs XLE holds positive"],
             "confirms_if":  ["5d return > 2pp vs XLE"],
             "falsifies_if": ["5d return < 0 and analyst cuts appear"]},
            {"horizon": "20d",
             "expected":     ["Structural revision to capex guidance"],
             "confirms_if":  ["Earnings commentary confirms persistence"],
             "falsifies_if": ["Guidance unchanged; move fully unwound"]},
        ],
    }


def _event_with_everything() -> dict:
    return {
        "id":                1,
        "timestamp":         "2026-04-13T10:00:00",
        "headline":          "OPEC announces 500kbpd cut",
        "event_date":        "2026-04-13",
        "stage":             "realized",
        "persistence":       "structural",
        "confidence":        "high",
        "what_changed":      "OPEC cut by 500kbpd",
        "mechanism_summary": "Tighter supply, higher crude",
        "beneficiaries":     ["XOM", "CVX"],
        "losers":            ["AAL"],
        "assets_to_watch":   [],
        "market_note":       "Crude up 4%",
        "market_tickers": [
            {"symbol": "XOM", "role": "beneficiary",
             "return_1d": 1.5, "return_5d": 3.0, "return_20d": 6.0,
             "direction_tag": "supports thesis", "spark": [0.1] * 20},
            {"symbol": "CVX", "role": "beneficiary",
             "return_1d": 1.2, "return_5d": 2.5, "return_20d": 5.5,
             "direction_tag": "supports thesis", "spark": [0.1] * 20},
        ],
        "horizon_checkpoints": _checkpoints(),
        "if_persists":         {"direction": "bullish energy"},
        "currency_channel":    {},
        "transmission_chain":  ["OPEC cut", "crude up", "energy equities lift"],
        "regime_snapshot": {
            "available":      True,
            "stale":          False,
            "inflation":      "hot",
            "policy_stance":  "hawkish",
            "credit":         "risk_on",
            "fx":             "dollar_weak",
            "growth_stress":  "calm",
            "curve_shape":    "parallel",
            "inflation_path": "hawkish_constraint",
            "compound": {"label": "reflation", "confidence": 0.75,
                         "rationale": "test", "matched_axes": [],
                         "candidates": []},
            "transition": {"state": "stable", "changed_axes": [],
                           "rationale": "test"},
        },
        "rating": "good",
        "notes":  "Clean trade",
    }


# ---------------------------------------------------------------------------
# 1. CSV export surfaces horizon_checkpoints as a column
# ---------------------------------------------------------------------------

class TestCsvSurfacesHorizonCheckpoints(unittest.TestCase):

    def test_horizon_checkpoints_is_a_csv_column(self):
        self.assertIn("horizon_checkpoints", CSV_COLUMNS)

    def test_csv_cell_contains_serialized_checkpoint_json(self):
        csv_text = build_csv_export([_event_with_everything()])
        rows = list(csv.reader(io.StringIO(csv_text)))
        header, data = rows[0], rows[1]
        idx = header.index("horizon_checkpoints")
        parsed = json.loads(data[idx])
        # Must preserve structure end-to-end.
        self.assertEqual(parsed["timing_profile"], "fast_shock")
        self.assertEqual(len(parsed["horizons"]), 3)

    def test_empty_event_omits_checkpoints_gracefully(self):
        ev = {"id": 2, "headline": "empty", "stage": "developing",
              "persistence": "medium", "event_date": "2026-04-13",
              "market_tickers": []}
        csv_text = build_csv_export([ev])
        rows = list(csv.reader(io.StringIO(csv_text)))
        # The column still exists; the cell is an empty-dict JSON literal.
        idx = rows[0].index("horizon_checkpoints")
        # Either "" (None-like) or "{}" — both acceptable as "absent".
        self.assertIn(rows[1][idx], ("", "{}"))


# ---------------------------------------------------------------------------
# 2. Bulk JSON export attaches derived blocks
# ---------------------------------------------------------------------------

class TestBulkJsonIncludesDerivedBlocks(unittest.TestCase):

    def test_thesis_scorecard_attached_on_bulk_json(self):
        out = build_json_export([_event_with_everything()])
        ev = out["events"][0]
        self.assertIn("thesis_scorecard", ev)
        self.assertTrue(ev["thesis_scorecard"]["available"])
        # With 2 supporting beneficiaries at every horizon, the scorecard
        # should read "on_track".
        self.assertEqual(ev["thesis_scorecard"]["aggregate"]["status"],
                         "on_track")

    def test_finance_playbook_attached_on_bulk_json(self):
        out = build_json_export([_event_with_everything()])
        ev = out["events"][0]
        self.assertIn("finance_playbook", ev)
        self.assertTrue(ev["finance_playbook"]["available"])
        # Regime line must reflect the compound label from regime_snapshot.
        self.assertIn("reflation", ev["finance_playbook"]["lines"]["regime"])

    def test_horizon_checkpoints_preserved_on_bulk_json(self):
        out = build_json_export([_event_with_everything()])
        ev = out["events"][0]
        self.assertEqual(ev["horizon_checkpoints"]["timing_profile"],
                         "fast_shock")


# ---------------------------------------------------------------------------
# 3. Single-event JSON export + _JSON_EXPORT_KEYS
# ---------------------------------------------------------------------------

class TestSingleEventJsonExport(unittest.TestCase):

    def test_export_keys_include_derived(self):
        from api import _JSON_EXPORT_KEYS
        for key in ("horizon_checkpoints", "thesis_scorecard",
                    "finance_playbook"):
            self.assertIn(key, _JSON_EXPORT_KEYS,
                          f"{key!r} missing from _JSON_EXPORT_KEYS")

    def test_build_event_json_export_populates_derived(self):
        from api import _build_event_json_export
        exported = _build_event_json_export(_event_with_everything())
        self.assertIn("horizon_checkpoints", exported)
        self.assertTrue(exported["thesis_scorecard"]["available"])
        self.assertTrue(exported["finance_playbook"]["available"])

    def test_minimal_event_still_emits_derived_keys(self):
        """A row without checkpoints / tickers still must include the
        keys (as empty/unavailable dicts) because the JSON export has a
        stable shape contract."""
        from api import _build_event_json_export
        minimal = {
            "id": 99, "headline": "minimal", "stage": "developing",
            "persistence": "medium", "event_date": "2026-04-13",
            "timestamp": "2026-04-13T00:00:00",
            "confidence": "low", "market_tickers": [],
        }
        exported = _build_event_json_export(minimal)
        self.assertIn("horizon_checkpoints", exported)
        self.assertIn("thesis_scorecard", exported)
        self.assertIn("finance_playbook", exported)
        # Scorecard should degrade to pending aggregate.
        self.assertEqual(
            exported["thesis_scorecard"]["aggregate"]["status"],
            "pending",
        )


# ---------------------------------------------------------------------------
# 4. Text + markdown memos render the new sections
# ---------------------------------------------------------------------------

class TestMemoRendering(unittest.TestCase):

    def test_text_memo_has_horizon_checkpoints_section(self):
        from api import _build_event_text_memo
        memo = _build_event_text_memo(_event_with_everything())
        self.assertIn("HORIZON CHECKPOINTS", memo)
        self.assertIn("Timing profile: fast_shock", memo)
        # Each horizon marker must appear.
        for h in ("[1d]", "[5d]", "[20d]"):
            self.assertIn(h, memo)
        # At least one LLM-written criterion appears verbatim.
        self.assertIn("XOM +1-2% intraday", memo)

    def test_text_memo_has_thesis_scorecard_section(self):
        from api import _build_event_text_memo
        memo = _build_event_text_memo(_event_with_everything())
        self.assertIn("THESIS SCORECARD", memo)
        self.assertIn("Aggregate:", memo)
        # Every horizon row appears in the per-horizon block.
        self.assertIn("  1d:", memo.replace("   1d:", "  1d:"))  # tolerate padding

    def test_text_memo_without_checkpoints_omits_section(self):
        from api import _build_event_text_memo
        ev = dict(_event_with_everything())
        ev.pop("horizon_checkpoints", None)
        memo = _build_event_text_memo(ev)
        self.assertNotIn("HORIZON CHECKPOINTS", memo)

    def test_markdown_memo_has_horizon_checkpoints_heading(self):
        from api import _build_event_markdown_memo
        memo = _build_event_markdown_memo(_event_with_everything())
        self.assertIn("## Horizon Checkpoints", memo)
        self.assertIn("**1d**", memo)
        self.assertIn("Falsifies if", memo)

    def test_markdown_memo_has_thesis_scorecard_table(self):
        from api import _build_event_markdown_memo
        memo = _build_event_markdown_memo(_event_with_everything())
        self.assertIn("## Thesis Scorecard", memo)
        self.assertIn("| Horizon | Status | Rationale |", memo)
        # `on_track` aggregate status appears in backticks.
        self.assertIn("`on_track`", memo)

    def test_markdown_memo_omits_sections_when_data_absent(self):
        from api import _build_event_markdown_memo
        ev = {
            "id": 5, "headline": "bare", "stage": "developing",
            "persistence": "medium", "event_date": "2026-04-13",
            "timestamp": "2026-04-13T00:00:00", "market_tickers": [],
        }
        memo = _build_event_markdown_memo(ev)
        self.assertNotIn("## Horizon Checkpoints", memo)
        # Scorecard section should also not appear when there are no
        # resolved horizons AND no checkpoint criteria to render.
        # (The scorecard itself still exists but is_available=False.)
        self.assertNotIn("## Thesis Scorecard", memo)


# ---------------------------------------------------------------------------
# 5. enrich_event_with_derived: pure + idempotent
# ---------------------------------------------------------------------------

class TestEnrichmentPurityAndIdempotence(unittest.TestCase):

    def test_original_dict_not_mutated(self):
        ev = _event_with_everything()
        before = set(ev.keys())
        _ = enrich_event_with_derived(ev)
        after = set(ev.keys())
        # The enrichment must NOT add keys to the original dict.
        self.assertEqual(before, after)

    def test_idempotent(self):
        ev = _event_with_everything()
        once = enrich_event_with_derived(ev)
        twice = enrich_event_with_derived(once)
        self.assertEqual(
            once["thesis_scorecard"]["aggregate"]["status"],
            twice["thesis_scorecard"]["aggregate"]["status"],
        )

    def test_non_dict_input_returned_unchanged(self):
        """Defensive: if a caller hands us something weird the enricher
        must not raise — it returns the input."""
        self.assertIs(enrich_event_with_derived(None), None)  # type: ignore[arg-type]
        self.assertEqual(enrich_event_with_derived("oops"), "oops")  # type: ignore[arg-type]

    def test_partial_inputs_degrade_rather_than_raise(self):
        partial = {
            "id": 7, "headline": "no checkpoints", "stage": "developing",
            "persistence": "medium", "event_date": "2026-04-13",
            "market_tickers": [],
        }
        out = enrich_event_with_derived(partial)
        # thesis_scorecard must still be a dict with the documented shape.
        self.assertIn("thesis_scorecard", out)
        self.assertIsInstance(out["thesis_scorecard"], dict)


if __name__ == "__main__":
    unittest.main()
