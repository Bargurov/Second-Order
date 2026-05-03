"""Tests for track_record_export — research-friendly serializers for the
mechanism-family + regime + compound-regime breakdown."""

import csv
import io
import json
import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
from track_record_export import (
    build_breakdown_json,
    build_breakdown_csv,
    build_breakdown_markdown,
    _fmt_pct,
    _fmt_return,
    _fmt_int,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _breakdown(**overrides) -> dict:
    base = {
        "total_events":       10,
        "validated_total":    6,
        "contradicted_total": 3,
        "revisit_scored":     7,
        "hit_rate":           0.667,
        "generated_at":       "2026-04-18T12:00:00+00:00",
        "by_policy_status": [
            {
                "status": "announced", "label": "Announced",
                "total": 0, "validated": 0, "contradicted": 0,
                "unresolved": 0, "revisit_scored": 0,
                "hit_rate": None, "coverage": None,
                "avg_return_5d": None, "avg_return_20d": None,
                "avg_support_ratio": None,
            },
            {
                "status": "effective", "label": "Effective",
                "total": 4, "validated": 3, "contradicted": 1,
                "unresolved": 0, "revisit_scored": 3,
                "hit_rate": 0.75, "coverage": 1.0,
                "avg_return_5d": 1.5, "avg_return_20d": 2.4,
                "avg_support_ratio": 0.7,
            },
            {
                "status": "under_review", "label": "Under review",
                "total": 0, "validated": 0, "contradicted": 0,
                "unresolved": 0, "revisit_scored": 0,
                "hit_rate": None, "coverage": None,
                "avg_return_5d": None, "avg_return_20d": None,
                "avg_support_ratio": None,
            },
            {
                "status": "expired", "label": "Expired",
                "total": 0, "validated": 0, "contradicted": 0,
                "unresolved": 0, "revisit_scored": 0,
                "hit_rate": None, "coverage": None,
                "avg_return_5d": None, "avg_return_20d": None,
                "avg_support_ratio": None,
            },
        ],
        "by_overall_vulnerability": [
            {
                "tier": "resilient", "label": "Resilient",
                "total": 0, "validated": 0, "contradicted": 0,
                "unresolved": 0, "revisit_scored": 0,
                "hit_rate": None, "coverage": None,
                "avg_return_5d": None, "avg_return_20d": None,
                "avg_support_ratio": None,
            },
            {
                "tier": "moderate", "label": "Moderate",
                "total": 1, "validated": 1, "contradicted": 0,
                "unresolved": 0, "revisit_scored": 1,
                "hit_rate": 1.0, "coverage": 1.0,
                "avg_return_5d": 0.9, "avg_return_20d": None,
                "avg_support_ratio": 1.0,
            },
            {
                "tier": "vulnerable", "label": "Vulnerable",
                "total": 3, "validated": 2, "contradicted": 1,
                "unresolved": 0, "revisit_scored": 2,
                "hit_rate": 0.667, "coverage": 1.0,
                "avg_return_5d": -0.4, "avg_return_20d": 1.1,
                "avg_support_ratio": 0.5,
            },
            {
                "tier": "fragile", "label": "Fragile",
                "total": 0, "validated": 0, "contradicted": 0,
                "unresolved": 0, "revisit_scored": 0,
                "hit_rate": None, "coverage": None,
                "avg_return_5d": None, "avg_return_20d": None,
                "avg_support_ratio": None,
            },
        ],
        "by_mechanism_family": [
            {
                "family": "supply_shock", "family_label": "Supply shock",
                "total": 5, "validated": 4, "contradicted": 1, "unresolved": 0,
                "revisit_scored": 4,
                "hit_rate": 0.8, "coverage": 1.0,
                "avg_return_5d": 2.5, "avg_return_20d": 4.2,
                "avg_support_ratio": 0.75,
            },
            {
                "family": "policy_surprise", "family_label": "Policy surprise",
                "total": 3, "validated": 1, "contradicted": 2, "unresolved": 0,
                "revisit_scored": 2,
                "hit_rate": 0.333, "coverage": 1.0,
                "avg_return_5d": -0.8, "avg_return_20d": None,
                "avg_support_ratio": 0.3,
            },
        ],
        "by_regime": [
            {
                "regime_key": "hot/hawkish",
                "inflation": "hot", "policy_stance": "hawkish",
                "total": 6, "validated": 4, "contradicted": 2, "unresolved": 0,
                "revisit_scored": 5,
                "hit_rate": 0.667, "coverage": 1.0,
                "avg_return_5d": 1.8, "avg_return_20d": 3.0,
                "avg_support_ratio": 0.6,
            },
        ],
        "by_compound_regime": [
            {
                "state": "reflation", "label": "Reflation",
                "total": 4, "validated": 3, "contradicted": 1, "unresolved": 0,
                "revisit_scored": 3,
                "hit_rate": 0.75, "coverage": 1.0,
                "avg_return_5d": 2.1, "avg_return_20d": 3.5,
                "avg_support_ratio": 0.7,
            },
        ],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


class TestFormatters(unittest.TestCase):
    def test_pct_formatting(self):
        self.assertEqual(_fmt_pct(0.667), "67%")
        self.assertEqual(_fmt_pct(0.0), "0%")
        self.assertEqual(_fmt_pct(1.0), "100%")
        self.assertEqual(_fmt_pct(None), "—")

    def test_return_formatting(self):
        self.assertEqual(_fmt_return(2.5), "+2.5%")
        self.assertEqual(_fmt_return(-1.2), "-1.2%")
        self.assertEqual(_fmt_return(0.0), "+0.0%")
        self.assertEqual(_fmt_return(None), "—")

    def test_int_formatting(self):
        self.assertEqual(_fmt_int(5), "5")
        self.assertEqual(_fmt_int(0), "0")
        self.assertEqual(_fmt_int(None), "—")


# ---------------------------------------------------------------------------
# JSON envelope
# ---------------------------------------------------------------------------


class TestJsonEnvelope(unittest.TestCase):
    def test_schema_tag_and_summary_block(self):
        out = build_breakdown_json(_breakdown())
        self.assertEqual(out["schema"], "track_record_breakdown.v1")
        self.assertEqual(out["summary"]["total_events"], 10)
        self.assertEqual(out["summary"]["validated_total"], 6)
        self.assertEqual(out["summary"]["contradicted_total"], 3)
        self.assertEqual(out["summary"]["unresolved_total"], 1)  # 10 - 6 - 3
        self.assertAlmostEqual(out["summary"]["hit_rate"], 0.667)

    def test_dimensions_carry_through(self):
        out = build_breakdown_json(_breakdown())
        self.assertEqual(len(out["by_mechanism_family"]), 2)
        self.assertEqual(len(out["by_regime"]), 1)
        self.assertEqual(len(out["by_compound_regime"]), 1)
        # New deterministic-context dimensions ride along.
        self.assertEqual(len(out["by_policy_status"]), 4)
        self.assertEqual(len(out["by_overall_vulnerability"]), 4)
        self.assertEqual(out["by_policy_status"][1]["status"], "effective")
        self.assertEqual(out["by_policy_status"][1]["validated"], 3)
        self.assertEqual(out["by_overall_vulnerability"][2]["tier"], "vulnerable")

    def test_empty_input_stable_shape(self):
        out = build_breakdown_json({
            "total_events": 0, "validated_total": 0,
            "contradicted_total": 0, "revisit_scored": 0, "hit_rate": None,
            "by_mechanism_family": [], "by_regime": [], "by_compound_regime": [],
            "generated_at": "2026-04-18T12:00:00+00:00",
        })
        self.assertEqual(out["summary"]["total_events"], 0)
        self.assertEqual(out["summary"]["unresolved_total"], 0)
        self.assertEqual(out["by_mechanism_family"], [])
        self.assertEqual(out["by_regime"], [])
        self.assertEqual(out["by_compound_regime"], [])

    def test_generated_at_fallback(self):
        """A breakdown missing generated_at still emits a valid ISO stamp."""
        b = _breakdown()
        del b["generated_at"]
        out = build_breakdown_json(b)
        self.assertIsInstance(out["generated_at"], str)
        self.assertTrue(out["generated_at"].startswith("20"))

    def test_json_serializable(self):
        """The envelope must round-trip through json.dumps / json.loads."""
        out = build_breakdown_json(_breakdown())
        round_tripped = json.loads(json.dumps(out))
        self.assertEqual(round_tripped["schema"], "track_record_breakdown.v1")


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


class TestCsvExport(unittest.TestCase):
    def _sections(self, csv_text: str) -> dict[str, list[list[str]]]:
        """Split the multi-section CSV by ``# heading`` rows."""
        sections: dict[str, list[list[str]]] = {}
        current: list[list[str]] | None = None
        current_name = ""
        for row in csv.reader(io.StringIO(csv_text)):
            if row and row[0].startswith("# "):
                current_name = row[0][2:].strip()
                current = []
                sections[current_name] = current
                continue
            if current is not None and row:
                current.append(row)
        return sections

    def test_contains_four_sections(self):
        sections = self._sections(build_breakdown_csv(_breakdown()))
        for expected in ("summary", "by_mechanism_family",
                         "by_regime", "by_compound_regime",
                         "by_policy_status", "by_overall_vulnerability"):
            self.assertIn(expected, sections)

    def test_policy_status_section_uses_status_column(self):
        sections = self._sections(build_breakdown_csv(_breakdown()))
        ps = sections["by_policy_status"]
        header = ps[0]
        self.assertEqual(header[0], "status")
        self.assertEqual(header[1], "label")
        # Effective bucket is the only populated row in the fixture.
        effective_row = next(r for r in ps[1:] if r[0] == "effective")
        total_idx = header.index("total")
        validated_idx = header.index("validated")
        self.assertEqual(effective_row[total_idx], "4")
        self.assertEqual(effective_row[validated_idx], "3")

    def test_vulnerability_section_uses_tier_column(self):
        sections = self._sections(build_breakdown_csv(_breakdown()))
        vt = sections["by_overall_vulnerability"]
        header = vt[0]
        self.assertEqual(header[0], "tier")
        self.assertEqual(header[1], "label")
        vuln_row = next(r for r in vt[1:] if r[0] == "vulnerable")
        total_idx = header.index("total")
        contradicted_idx = header.index("contradicted")
        self.assertEqual(vuln_row[total_idx], "3")
        self.assertEqual(vuln_row[contradicted_idx], "1")

    def test_summary_contains_schema_and_counts(self):
        sections = self._sections(build_breakdown_csv(_breakdown()))
        summary_rows = {r[0]: r[1] for r in sections["summary"] if len(r) >= 2 and r[0] != "metric"}
        self.assertEqual(summary_rows["schema"], "track_record_breakdown.v1")
        self.assertEqual(summary_rows["total_events"], "10")
        self.assertEqual(summary_rows["validated_total"], "6")
        self.assertEqual(summary_rows["hit_rate"], "0.667")

    def test_family_section_has_header_row(self):
        sections = self._sections(build_breakdown_csv(_breakdown()))
        family = sections["by_mechanism_family"]
        header = family[0]
        self.assertEqual(header[0], "family")
        self.assertEqual(header[1], "family_label")
        # Every breakdown numeric field must appear in the header.
        for col in ("total", "validated", "contradicted", "hit_rate",
                    "coverage", "avg_return_5d", "avg_return_20d"):
            self.assertIn(col, header)

    def test_family_section_row_values(self):
        sections = self._sections(build_breakdown_csv(_breakdown()))
        family = sections["by_mechanism_family"]
        # First data row after the header.
        row = family[1]
        self.assertEqual(row[0], "supply_shock")
        self.assertEqual(row[1], "Supply shock")
        # total=5, validated=4, contradicted=1
        self.assertEqual(row[2], "5")
        self.assertEqual(row[3], "4")
        self.assertEqual(row[4], "1")

    def test_regime_section_uses_regime_key(self):
        sections = self._sections(build_breakdown_csv(_breakdown()))
        regime = sections["by_regime"]
        header = regime[0]
        self.assertEqual(header[0], "regime_key")
        self.assertEqual(regime[1][0], "hot/hawkish")

    def test_compound_section_uses_state_column(self):
        sections = self._sections(build_breakdown_csv(_breakdown()))
        compound = sections["by_compound_regime"]
        header = compound[0]
        self.assertEqual(header[0], "state")
        self.assertEqual(header[1], "label")
        self.assertEqual(compound[1][0], "reflation")

    def test_empty_dimensions_still_emit_header(self):
        """A breakdown with empty dimensions must still ship the header row
        so downstream spreadsheet templates don't error on missing columns."""
        b = _breakdown(
            by_mechanism_family=[],
            by_regime=[],
            by_compound_regime=[],
        )
        sections = self._sections(build_breakdown_csv(b))
        for key in ("by_mechanism_family", "by_regime", "by_compound_regime"):
            # Header row always emitted even when no data rows follow.
            self.assertGreaterEqual(len(sections[key]), 1)

    def test_null_avg_return_renders_blank(self):
        """``avg_return_20d = None`` on the policy_surprise row must become
        an empty CSV cell, not the literal string 'None'."""
        sections = self._sections(build_breakdown_csv(_breakdown()))
        header = sections["by_mechanism_family"][0]
        avg20_idx = header.index("avg_return_20d")
        policy_row = next(
            r for r in sections["by_mechanism_family"][1:] if r[0] == "policy_surprise"
        )
        self.assertEqual(policy_row[avg20_idx], "")


# ---------------------------------------------------------------------------
# Markdown memo
# ---------------------------------------------------------------------------


class TestMarkdownMemo(unittest.TestCase):
    def test_carries_three_section_headers(self):
        md = build_breakdown_markdown(_breakdown())
        self.assertIn("# Track-record breakdown", md)
        self.assertIn("## By mechanism family", md)
        self.assertIn("## By regime", md)
        self.assertIn("## By compound regime", md)
        # Deterministic-context dimensions get their own sections.
        self.assertIn("## By policy status", md)
        self.assertIn("## By overall vulnerability", md)
        # Populated rows render their canonical labels.
        self.assertIn("Effective", md)
        self.assertIn("Vulnerable", md)

    def test_family_table_rows_present(self):
        md = build_breakdown_markdown(_breakdown())
        self.assertIn("Supply shock", md)
        self.assertIn("Policy surprise", md)

    def test_hit_rate_rendered_as_percent(self):
        md = build_breakdown_markdown(_breakdown())
        # Overall hit rate 0.667 → 67%
        self.assertIn("overall hit rate: **67%**", md)
        # Supply shock hit rate 0.8 → 80% in the family table.
        self.assertIn("80%", md)

    def test_returns_rendered_with_signed_percent(self):
        md = build_breakdown_markdown(_breakdown())
        self.assertIn("+2.5%", md)  # supply_shock avg_return_5d
        self.assertIn("-0.8%", md)  # policy_surprise avg_return_5d

    def test_empty_breakdown_yields_stable_markdown(self):
        """An empty breakdown still produces every section + an em-dash table."""
        b = _breakdown(
            total_events=0, validated_total=0, contradicted_total=0,
            hit_rate=None, by_mechanism_family=[], by_regime=[],
            by_compound_regime=[],
        )
        md = build_breakdown_markdown(b)
        self.assertIn("Events: **0**", md)
        # All three section tables must still be present.
        self.assertIn("## By mechanism family", md)
        self.assertIn("## By regime", md)
        self.assertIn("## By compound regime", md)

    def test_summary_line_uses_unresolved_count(self):
        md = build_breakdown_markdown(_breakdown())
        # unresolved = 10 - 6 - 3 = 1
        self.assertIn("**6/3/1**", md)


# ---------------------------------------------------------------------------
# Endpoint wiring — /stats/track-record/breakdown/export
# ---------------------------------------------------------------------------


class TestExportEndpoint(unittest.TestCase):
    def setUp(self):
        self._orig = db.DB_FILE
        db.DB_FILE = os.path.join(
            os.path.dirname(__file__),
            f"test_trexp_{uuid.uuid4().hex}.db",
        )
        db.init_db()
        from fastapi.testclient import TestClient
        from api import app
        self.client = TestClient(app)

    def tearDown(self):
        try:
            os.remove(db.DB_FILE)
        except (OSError, PermissionError):
            pass
        db.DB_FILE = self._orig

    def _seed(self):
        regime = {
            "available": True, "inflation": "hot", "policy_stance": "hawkish",
            "compound": {"label": "reflation", "confidence": 0.8},
        }
        db.save_event({
            "headline":         "Exp seed A",
            "stage":            "realized",
            "persistence":      "medium",
            "mechanism_family": "tariff",
            "event_date":       "2026-03-01",
            "regime_snapshot":  regime,
            "market_tickers":   [{"symbol": "SPY", "role": "beneficiary",
                                  "direction_tag": "supports_thesis",
                                  "return_5d": 2.0, "return_20d": 3.0}],
        })
        db.save_event({
            "headline":         "Exp seed B",
            "stage":            "realized",
            "persistence":      "medium",
            "mechanism_family": "tariff",
            "event_date":       "2026-03-02",
            "regime_snapshot":  regime,
            "market_tickers":   [{"symbol": "SPY", "role": "beneficiary",
                                  "direction_tag": "contradicts_thesis",
                                  "return_5d": -1.0}],
        })

    def test_json_format_returns_schema_envelope(self):
        self._seed()
        r = self.client.get("/stats/track-record/breakdown/export?format=json")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["schema"], "track_record_breakdown.v1")
        self.assertEqual(body["summary"]["total_events"], 2)
        self.assertEqual(len(body["by_mechanism_family"]), 1)

    def test_csv_format_has_content_disposition(self):
        self._seed()
        r = self.client.get("/stats/track-record/breakdown/export?format=csv")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.headers["content-type"].startswith("text/csv"))
        self.assertIn("track_record_breakdown.csv",
                      r.headers.get("content-disposition", ""))
        # Header row is the first row of the summary section.
        self.assertIn("# summary", r.text)
        self.assertIn("tariff", r.text)

    def test_markdown_format_has_content_disposition(self):
        self._seed()
        r = self.client.get("/stats/track-record/breakdown/export?format=markdown")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.headers["content-type"].startswith("text/markdown"))
        self.assertIn("track_record_breakdown.md",
                      r.headers.get("content-disposition", ""))
        self.assertIn("# Track-record breakdown", r.text)
        self.assertIn("Tariff", r.text)

    def test_invalid_format_422(self):
        r = self.client.get("/stats/track-record/breakdown/export?format=xml")
        self.assertEqual(r.status_code, 422)

    def test_json_default_when_format_absent(self):
        r = self.client.get("/stats/track-record/breakdown/export")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["schema"], "track_record_breakdown.v1")


# ---------------------------------------------------------------------------
# Archive JSON export carries the breakdown
# ---------------------------------------------------------------------------


class TestArchiveJsonCarriesBreakdown(unittest.TestCase):
    """`build_json_export` should attach the breakdown block alongside
    events so a memo template can pull both from one download."""

    def test_breakdown_block_attached_to_archive(self):
        from events_export import build_json_export

        regime = {
            "available": True, "inflation": "hot", "policy_stance": "hawkish",
            "compound": {"label": "reflation", "confidence": 0.8},
        }
        events = [{
            "id": 1,
            "headline": "Archive demo",
            "timestamp": "2026-03-01T12:00:00",
            "event_date": "2026-03-01",
            "stage": "realized",
            "persistence": "medium",
            "confidence": "medium",
            "mechanism_family": "tariff",
            "market_tickers": [{"symbol": "SPY", "role": "beneficiary",
                                "direction_tag": "supports_thesis",
                                "return_5d": 2.0}],
            "revisit_snapshots": [],
            "regime_snapshot": regime,
        }]
        out = build_json_export(events)

        self.assertEqual(out["count"], 1)
        self.assertIn("track_record_breakdown", out)
        block = out["track_record_breakdown"]
        self.assertEqual(block["schema"], "track_record_breakdown.v1")
        self.assertEqual(block["summary"]["total_events"], 1)
        self.assertTrue(any(
            e["family"] == "tariff" for e in block["by_mechanism_family"]
        ))

    def test_empty_archive_still_emits_breakdown_envelope(self):
        from events_export import build_json_export
        out = build_json_export([])
        self.assertEqual(out["count"], 0)
        self.assertIn("track_record_breakdown", out)
        block = out["track_record_breakdown"]
        self.assertEqual(block["schema"], "track_record_breakdown.v1")
        self.assertEqual(block["summary"]["total_events"], 0)


if __name__ == "__main__":
    unittest.main()
