"""
tests/test_track_record_engine_dims.py

Coverage for the engine-phase dimensions added to the track-record
breakdown — quality_tier, mechanism_subtype, tradable.  Each dimension
is read from the surfaced field on the event dict when present and
falls back to the same composer the live API path uses, so the bulk
export reads bucket identically to the per-event route.

The breakdown contract requires:
  * Skip-empty for unknown / off-enum values (does not pollute groups).
  * Stable shape: known dimensions render as empty enum tables when
    the input set has no events that match.
  * Existing keys (by_mechanism_family, by_regime, ...) untouched.
  * JSON / CSV / markdown all carry the new dimensions.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from track_record_breakdown import (
    QUALITY_TIER_BUCKETS,
    TRADABLE_BUCKETS,
    _mechanism_subtype_key,
    _quality_tier_key,
    _tradable_key,
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


def _ticker(symbol: str, direction: str, r5: float | None = None,
            r20: float | None = None) -> dict:
    return {
        "symbol":         symbol,
        "role":           "beneficiary",
        "direction_tag":  direction,
        "return_5d":      r5,
        "return_20d":     r20,
    }


def _event(
    *,
    family: str = "supply_shock",
    quality_tier: str | None = "actionable",
    subtype: str | None = "oil_price_shock",
    actionability: dict | None = None,
    tickers: list[dict] | None = None,
) -> dict:
    """Build a minimally-shaped event dict carrying the engine-phase
    surface fields the breakdown reads.  Designed so the breakdown
    composer never needs to dive into the actual composers — the
    surfaced values are honoured directly."""
    if actionability is None:
        actionability = {"tradable": True}
    return {
        "mechanism_family":     family,
        "mechanism_subtype":    subtype,
        "mechanism_summary":    "minimal",
        "what_changed":         "minimal",
        "quality_tier":         quality_tier,
        "actionability_check":  actionability,
        "market_tickers":       tickers if tickers is not None else
                                 [_ticker("SPY", "supports_thesis", 2.0, 4.0)],
        "revisit_snapshots":    [],
        "regime_snapshot":      {"available": False},
    }


# ---------------------------------------------------------------------------
# Key extractors
# ---------------------------------------------------------------------------


class TestQualityTierKey(unittest.TestCase):
    def test_returns_surfaced_field_when_in_enum(self):
        self.assertEqual(_quality_tier_key({"quality_tier": "actionable"}), "actionable")
        self.assertEqual(_quality_tier_key({"quality_tier": "watch_only"}), "watch_only")
        self.assertEqual(
            _quality_tier_key({"quality_tier": "low_information"}),
            "low_information",
        )

    def test_is_case_insensitive(self):
        self.assertEqual(_quality_tier_key({"quality_tier": "Actionable"}), "actionable")

    def test_returns_none_for_off_enum_value(self):
        self.assertIsNone(_quality_tier_key({"quality_tier": "freeform"}))

    def test_falls_back_to_composer_when_field_missing(self):
        # No quality_tier surfaced; composer derives one from the empty
        # event dict — ``evidence_quality_tier`` returns "low_information"
        # for thin events, which IS in the enum.
        result = _quality_tier_key({})
        self.assertIn(result, set(QUALITY_TIER_BUCKETS))


class TestMechanismSubtypeKey(unittest.TestCase):
    def test_returns_surfaced_subtype(self):
        self.assertEqual(
            _mechanism_subtype_key({"mechanism_subtype": "Oil_Price_Shock"}),
            "oil_price_shock",
        )

    def test_skips_none_string(self):
        self.assertIsNone(_mechanism_subtype_key({"mechanism_subtype": "none"}))

    def test_skips_blank(self):
        self.assertIsNone(_mechanism_subtype_key({"mechanism_subtype": "   "}))

    def test_falls_back_to_composer_on_missing(self):
        # No mechanism_subtype on the event; composer can't infer one
        # without family / summary / what_changed prose, so the result
        # is None (skipped from the dimension).
        self.assertIsNone(_mechanism_subtype_key({}))


class TestTradableKey(unittest.TestCase):
    def test_returns_tradable_when_true(self):
        self.assertEqual(
            _tradable_key({"actionability_check": {"tradable": True}}),
            "tradable",
        )

    def test_returns_not_tradable_when_false(self):
        self.assertEqual(
            _tradable_key({"actionability_check": {"tradable": False}}),
            "not_tradable",
        )

    def test_returns_a_valid_bucket_when_composer_succeeds(self):
        # No actionability_check → composer kicks in.  The composer
        # always emits a boolean ``tradable`` on analyzable events, so
        # the bulk-export path never empties this dimension by accident.
        bucket = _tradable_key({})
        self.assertIn(bucket, set(TRADABLE_BUCKETS))

    def test_returns_none_when_tradable_is_non_boolean(self):
        # Non-boolean ``tradable`` values (None / strings) skip the
        # dimension entirely — no synthetic ``unknown`` bucket.
        self.assertIsNone(
            _tradable_key({"actionability_check": {"tradable": None}}),
        )
        self.assertIsNone(
            _tradable_key({"actionability_check": {"tradable": "yes"}}),
        )


# ---------------------------------------------------------------------------
# Composer — three new dimensions land in the output
# ---------------------------------------------------------------------------


class TestBreakdownDimensions(unittest.TestCase):
    def test_empty_input_emits_empty_dimensions(self):
        # Hardened contract: dimensions never carry placeholder rows.
        # Empty input → empty list for all three dimensions.  The
        # dimension keys themselves remain present so the envelope
        # shape is stable.
        out = compute_track_record_breakdown([])
        self.assertEqual(out["by_quality_tier"],      [])
        self.assertEqual(out["by_mechanism_subtype"], [])
        self.assertEqual(out["by_tradable"],          [])

    def test_existing_keys_byte_stable(self):
        out = compute_track_record_breakdown([_event()])
        for legacy_key in (
            "total_events", "validated_total", "contradicted_total",
            "revisit_scored", "hit_rate",
            "by_mechanism_family", "by_regime", "by_compound_regime",
            "by_proof_quality", "by_policy_status",
            "by_overall_vulnerability",
        ):
            self.assertIn(legacy_key, out)

    def test_quality_tier_buckets_accumulate(self):
        events = [
            _event(quality_tier="actionable"),
            _event(quality_tier="actionable"),
            _event(quality_tier="watch_only"),
            _event(quality_tier="low_information"),
        ]
        out = compute_track_record_breakdown(events)
        by_tier = {g["tier"]: g for g in out["by_quality_tier"]}
        self.assertEqual(by_tier["actionable"]["total"],      2)
        self.assertEqual(by_tier["watch_only"]["total"],      1)
        self.assertEqual(by_tier["low_information"]["total"], 1)

    def test_tradable_buckets_accumulate_and_skip_non_boolean(self):
        # Hardened contract: events with non-boolean ``tradable`` skip
        # this dimension entirely (no ``unknown`` bucket).
        events = [
            _event(actionability={"tradable": True}),
            _event(actionability={"tradable": False}),
            _event(actionability={"tradable": False}),
            _event(actionability={"tradable": "n/a"}),  # skipped
        ]
        out = compute_track_record_breakdown(events)
        by_bucket = {g["bucket"]: g for g in out["by_tradable"]}
        self.assertEqual(by_bucket.keys(), {"tradable", "not_tradable"})
        self.assertEqual(by_bucket["tradable"]["total"],     1)
        self.assertEqual(by_bucket["not_tradable"]["total"], 2)
        # All four events still contribute to the overall totals.
        self.assertEqual(out["total_events"], 4)

    def test_no_label_field_on_engine_dimension_entries(self):
        # Verbatim stored values — entries must NOT carry a humanised
        # ``label`` key on the three new dimensions.
        out = compute_track_record_breakdown([
            _event(quality_tier="actionable",  subtype="oil_price_shock",
                   actionability={"tradable": True}),
        ])
        for entry in out["by_quality_tier"]:
            self.assertNotIn("label", entry)
        for entry in out["by_tradable"]:
            self.assertNotIn("label", entry)
        for entry in out["by_mechanism_subtype"]:
            self.assertNotIn("label", entry)
            # Subtype + family carry the verbatim stored tokens.
            self.assertEqual(entry["subtype"], "oil_price_shock")

    def test_subtype_skip_none_clean(self):
        events = [
            _event(subtype="oil_price_shock"),
            _event(subtype="oil_price_shock"),
            _event(subtype="rate_hike"),
            _event(subtype="none"),
            _event(subtype=None),
        ]
        out = compute_track_record_breakdown(events)
        by_sub = {g["subtype"]: g for g in out["by_mechanism_subtype"]}
        self.assertIn("oil_price_shock", by_sub)
        self.assertIn("rate_hike",       by_sub)
        self.assertNotIn("none", by_sub)
        self.assertEqual(by_sub["oil_price_shock"]["total"], 2)
        self.assertEqual(by_sub["rate_hike"]["total"],       1)
        # Subtype list is sorted by sample size (ties broken on key);
        # totals 2 > 1.
        ordered = [g["subtype"] for g in out["by_mechanism_subtype"]]
        self.assertEqual(ordered[0], "oil_price_shock")

    def test_unknown_quality_tier_skipped_but_event_counted(self):
        out = compute_track_record_breakdown([
            _event(quality_tier="totally-not-a-tier"),
            _event(quality_tier="actionable"),
        ])
        self.assertEqual(out["total_events"], 2)
        by_tier = {g["tier"]: g for g in out["by_quality_tier"]}
        # Only the actionable row landed in a bucket; the off-enum row
        # is invisible in this dimension but still counts in totals.
        # Empty buckets are not emitted — ``watch_only`` should be
        # absent because no event matched it.
        self.assertEqual(by_tier.keys(), {"actionable"})
        self.assertEqual(by_tier["actionable"]["total"], 1)


# ---------------------------------------------------------------------------
# Exports — JSON / CSV / markdown carry the new dimensions
# ---------------------------------------------------------------------------


class TestExportSurfaceTheNewDimensions(unittest.TestCase):
    def _breakdown(self) -> dict:
        return compute_track_record_breakdown([
            _event(quality_tier="actionable",  subtype="oil_price_shock",
                   actionability={"tradable": True}),
            _event(quality_tier="watch_only",  subtype="rate_hike",
                   actionability={"tradable": False}),
            _event(quality_tier="low_information", subtype=None,
                   actionability={"tradable": "n/a"}),
        ])

    def test_json_envelope_carries_new_dimensions(self):
        out = build_breakdown_json(self._breakdown())
        self.assertIn("by_quality_tier",      out)
        self.assertIn("by_mechanism_subtype", out)
        self.assertIn("by_tradable",          out)
        # Round-trip safe.
        json.loads(json.dumps(out))

    def test_json_envelope_legacy_keys_byte_stable(self):
        out = build_breakdown_json(self._breakdown())
        for legacy_key in (
            "schema", "generated_at", "summary",
            "by_mechanism_family", "by_regime", "by_compound_regime",
            "by_proof_quality", "by_policy_status",
            "by_overall_vulnerability",
        ):
            self.assertIn(legacy_key, out)

    def test_csv_carries_new_section_headers(self):
        csv_text = build_breakdown_csv(self._breakdown())
        for header in (
            "# by_quality_tier",
            "# by_mechanism_subtype",
            "# by_tradable",
        ):
            self.assertIn(header, csv_text)

    def test_csv_quality_tier_section_is_parseable(self):
        csv_text = build_breakdown_csv(self._breakdown())
        rows = list(csv.reader(io.StringIO(csv_text)))
        idx = next(
            i for i, r in enumerate(rows)
            if r and r[0] == "# by_quality_tier"
        )
        header = rows[idx + 1]
        # Identity column is the verbatim ``tier`` token only — no
        # ``label`` column.
        self.assertEqual(header[0], "tier")
        self.assertNotIn("label", header)
        # Read data rows until the next section / blank line.
        data: list[str] = []
        for r in rows[idx + 2:]:
            if not r or (r and r[0].startswith("#")):
                break
            if r[0]:
                data.append(r[0])
        # Fixture seeds 3 tiers, all 3 should appear with verbatim keys.
        self.assertEqual(set(data), {"actionable", "watch_only", "low_information"})

    def test_csv_tradable_section_drops_unknown_and_label(self):
        csv_text = build_breakdown_csv(self._breakdown())
        rows = list(csv.reader(io.StringIO(csv_text)))
        idx = next(
            i for i, r in enumerate(rows)
            if r and r[0] == "# by_tradable"
        )
        header = rows[idx + 1]
        self.assertEqual(header[0], "bucket")
        self.assertNotIn("label", header)
        data: list[str] = []
        for r in rows[idx + 2:]:
            if not r or (r and r[0].startswith("#")):
                break
            if r[0]:
                data.append(r[0])
        # Hardened contract: only the buckets that received events
        # appear; ``unknown`` is gone.
        self.assertNotIn("unknown", data)
        self.assertEqual(set(data), {"tradable", "not_tradable"})

    def test_markdown_renders_verbatim_tokens(self):
        md = build_breakdown_markdown(self._breakdown())
        # Stored tokens render verbatim (wrapped in backticks to
        # signal "raw key") — no humanised "Actionable" / "Watch only"
        # labels, no "Oil Price Shock" title-case, no underscore-to-
        # space rewrites on family.
        self.assertIn("`actionable`", md)
        self.assertIn("`watch_only`", md)
        self.assertIn("`low_information`", md)
        self.assertIn("`oil_price_shock`", md)
        self.assertIn("`rate_hike`", md)
        self.assertIn("`tradable`", md)
        self.assertIn("`not_tradable`", md)
        # No relabeled forms.
        self.assertNotIn("Watch only", md)
        self.assertNotIn("Oil Price Shock", md)
        self.assertNotIn("Not tradable", md)

    def test_markdown_includes_new_section_headings(self):
        md = build_breakdown_markdown(self._breakdown())
        self.assertIn("## By engine quality tier", md)
        self.assertIn("## By mechanism subtype",   md)
        self.assertIn("## By tradable",            md)

    def test_markdown_legacy_sections_still_present(self):
        md = build_breakdown_markdown(self._breakdown())
        for legacy_heading in (
            "## By mechanism family",
            "## By regime (inflation / policy stance)",
            "## By compound regime",
            "## By proof quality",
            "## By policy status",
            "## By overall vulnerability",
        ):
            self.assertIn(legacy_heading, md)


if __name__ == "__main__":
    unittest.main()
