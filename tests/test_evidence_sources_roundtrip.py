"""End-to-end round-trip coverage for ``evidence_sources``.

The traceability list lives under ``competing_thesis.evidence_sources``
(populated deterministically by ``_clean_competing_thesis`` from the
LLM-emitted ``evidence_favoring_primary`` / ``evidence_favoring_alternative``
entries).  These tests verify the field survives the
normalize/finalize → ``save_event`` → ``load_event_by_id`` round-trip
without losing structure, gaining scratch fields, or erroring on
missing input.
"""

from __future__ import annotations

import gc
import os
import shutil
import sys
import time
import unittest
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import db
from analyze_event import _finalize_analysis


# ---------------------------------------------------------------------------
# Test DB scaffolding (mirrors tests/test_db.py)
# ---------------------------------------------------------------------------

def _make_temp_db(prefix: str) -> tuple[str, str]:
    tmp_dir = os.path.join(
        os.path.dirname(__file__), f"{prefix}{uuid.uuid4().hex}",
    )
    os.makedirs(tmp_dir)
    return tmp_dir, os.path.join(tmp_dir, "events.db")


def _remove_temp_dir(path: str) -> None:
    last_error: Exception | None = None
    for _ in range(5):
        gc.collect()
        try:
            shutil.rmtree(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05)
    if last_error is not None:
        raise last_error


# ---------------------------------------------------------------------------
# Synthetic analysis fixtures
# ---------------------------------------------------------------------------

# A parsed-LLM dict whose competing_thesis carries enough structure
# for ``_clean_competing_thesis`` to compose evidence_sources.
def _parsed_with_competing_thesis() -> dict:
    return {
        "what_changed": (
            "US Commerce expanded the Entity List to cover 28 Chinese "
            "semiconductor firms, restricting export of advanced chips."
        ),
        "mechanism_summary": (
            "Entity List expansion cuts Chinese fabs off from US-origin "
            "semiconductor capital equipment, redirecting orders to TSMC "
            "and Korean foundries while compressing Lam / AMAT revenue."
        ),
        "beneficiaries":      ["TSMC"],
        "losers":              ["SMIC"],
        "beneficiary_tickers": ["TSM"],
        "loser_tickers":       ["LRCX", "AMAT"],
        "confidence": "medium",
        "transmission_chain": [
            "Commerce expands Entity List",
            "Chinese fabs lose access to US semi tools",
            "TSM absorbs reallocated demand",
            "Lam / AMAT revenue guidance cuts",
        ],
        "transmission_path": [
            {"hop": "Commerce expands Entity List",
             "actor": "US Commerce", "channel": "policy",
             "expected_market_effect": "Chinese fab capex restricted",
             "timing": "0-5d"},
            {"hop": "Order reallocation to TSM",
             "actor": "TSMC", "channel": "equities",
             "expected_market_effect": "TSM rerates higher",
             "timing": "5-30d"},
            {"hop": "Lam / AMAT order book contracts",
             "actor": "Lam Research", "channel": "equities",
             "expected_market_effect": "Capital-equipment names underperform",
             "timing": "30-60d"},
        ],
        "mechanism_family": "tariff",
        "expected_first_order_channels":  ["policy"],
        "expected_second_order_channels": ["equities"],
        "competing_thesis": {
            "primary_thesis": (
                "Entity List restrictions structurally compress "
                "US capital-equipment revenue and reroute order flow to "
                "non-Chinese foundries."
            ),
            "alternative_thesis": (
                "Restrictions accelerate Chinese self-sufficiency build, "
                "supporting domestic semi names over the medium term."
            ),
            "discriminator": (
                "Lam / AMAT FY guidance cuts >10% within 90 days."
            ),
            "evidence_favoring_primary": [
                {"observation": (
                    "Lam Research FY revenue guidance cut 12% post-listing"
                ), "channel": "equities", "timing": "0-30d"},
                {"observation": (
                    "TSMC reports 8% sequential order increase from "
                    "displaced Chinese demand"
                ), "channel": "equities", "timing": "30-60d"},
            ],
            "evidence_favoring_alternative": [
                {"observation": (
                    "SMIC capex doubles within 60 days of restrictions"
                ), "channel": "equities", "timing": "0-60d"},
            ],
        },
        "key_falsifiers": [
            (
                "Lam / AMAT FY revenue guidance reaffirmed within "
                "30 days of expanded Entity List."
            ),
        ],
        "minimum_proof_set": [
            {"observation": (
                "SOXX semiconductor ETF sector rotation: TSM "
                "outperforms by >3% over 5 trading days"
            ), "channel": "equities", "threshold": "3pp",
             "timing": "1-5d"},
        ],
        "primary_assets": [
            {"symbol": "TSM", "rank": 1,
             "rationale": "Direct beneficiary of redirected wafer demand."},
        ],
    }


def _saveable_event(analysis: dict, *, headline: str) -> dict:
    """Wrap an analysis dict with the minimum top-level fields
    ``save_event`` requires."""
    base = dict(analysis)
    base.setdefault("headline", headline)
    base.setdefault("stage", "realized")
    base.setdefault("persistence", "structural")
    return base


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------

class TestEvidenceSourcesRoundTrip(unittest.TestCase):
    def setUp(self) -> None:
        self._original_db = db.DB_FILE
        self._original_ready = db._db_ready
        self._tmp_dir, self._tmp_db = _make_temp_db("test_es_rt_")
        db.DB_FILE = self._tmp_db
        db.init_db()

    def tearDown(self) -> None:
        db.DB_FILE = self._original_db
        db._db_ready = self._original_ready
        _remove_temp_dir(self._tmp_dir)

    def _round_trip(self, parsed: dict, *, headline: str) -> dict:
        finalized = _finalize_analysis(
            parsed,
            headline=headline, stage="realized", persistence="structural",
        )
        # Sanity: finalize must not leak underscore-prefixed scratch.
        for key in finalized:
            self.assertFalse(
                isinstance(key, str) and key.startswith("_"),
                msg=f"scratch field {key!r} on finalized analysis",
            )
        ev = _saveable_event(finalized, headline=headline)
        db.save_event(ev)
        rows = db.load_recent_events(limit=10)
        self.assertEqual(len(rows), 1)
        loaded = db.load_event_by_id(rows[0]["id"])
        self.assertIsNotNone(loaded)
        return loaded

    # -- competing_thesis.evidence_sources (the populated production path) --

    def test_competing_thesis_evidence_sources_round_trips(self):
        parsed = _parsed_with_competing_thesis()
        finalized = _finalize_analysis(
            parsed,
            headline="US Commerce expands Entity List",
            stage="realized", persistence="structural",
        )
        # Populated by _clean_competing_thesis from the
        # evidence_favoring_* entries.
        self.assertIn("evidence_sources", finalized.get("competing_thesis") or {})
        self.assertTrue(finalized["competing_thesis"]["evidence_sources"])

        loaded = self._round_trip(
            parsed, headline="US Commerce expands Entity List",
        )
        loaded_ct = loaded.get("competing_thesis") or {}
        self.assertIsInstance(loaded_ct, dict)
        self.assertIn("evidence_sources", loaded_ct)
        self.assertEqual(
            loaded_ct["evidence_sources"],
            finalized["competing_thesis"]["evidence_sources"],
        )

    def test_evidence_sources_preserves_item_shape(self):
        parsed = _parsed_with_competing_thesis()
        loaded = self._round_trip(
            parsed, headline="US Commerce expands Entity List",
        )
        for entry in loaded["competing_thesis"]["evidence_sources"]:
            self.assertIsInstance(entry, dict)
            # make_source emits at least these keys; the round-trip
            # must not drop or coerce them.
            for key in ("source_type", "field_used", "supports_or_contradicts"):
                self.assertIn(key, entry)

    def test_evidence_favoring_primary_carries_through(self):
        parsed = _parsed_with_competing_thesis()
        loaded = self._round_trip(
            parsed, headline="US Commerce expands Entity List",
        )
        ct = loaded["competing_thesis"]
        # Underlying analyst text survives so evidence_sources can be
        # re-derived if needed; round-trip must not strip the source.
        self.assertIn("evidence_favoring_primary", ct)
        self.assertTrue(ct["evidence_favoring_primary"])

    # -- defensive defaults --

    def test_missing_evidence_sources_returns_stable_shape(self):
        # Parsed dict has no competing_thesis at all — round-trip must
        # not crash and the loaded competing_thesis must default to {}.
        parsed = _parsed_with_competing_thesis()
        parsed.pop("competing_thesis", None)
        loaded = self._round_trip(
            parsed, headline="Entity List, missing thesis",
        )
        ct = loaded.get("competing_thesis")
        self.assertEqual(ct, {})

    def test_competing_thesis_without_evidence_lines_yields_empty(self):
        # competing_thesis present but no evidence_favoring_* lines —
        # _clean_competing_thesis must not invent sources, and the
        # round-trip must preserve the empty/absent shape without
        # erroring.
        parsed = _parsed_with_competing_thesis()
        parsed["competing_thesis"] = {
            "primary_thesis": "Restrictions compress US semi tools.",
            "alternative_thesis": "Restrictions accelerate Chinese build.",
            "discriminator": "Lam guidance trajectory.",
        }
        loaded = self._round_trip(
            parsed, headline="Entity List, no evidence lines",
        )
        ct = loaded.get("competing_thesis") or {}
        # evidence_sources is absent or empty — never raises.
        sources = ct.get("evidence_sources", [])
        self.assertIsInstance(sources, list)
        self.assertEqual(len(sources), 0)

    # -- scratch-field hygiene on the load side --

    def test_loaded_event_has_no_scratch_fields(self):
        parsed = _parsed_with_competing_thesis()
        loaded = self._round_trip(
            parsed, headline="Entity List scratch hygiene",
        )
        for key in loaded:
            self.assertFalse(
                isinstance(key, str) and key.startswith("_"),
                msg=f"scratch field {key!r} present after load",
            )

    def test_top_level_evidence_sources_absent_does_not_error(self):
        # A finalized analysis does not populate top-level
        # evidence_sources today — production producers nest it under
        # competing_thesis or under overlay blocks.  Round-trip must
        # treat top-level absence as the stable default.
        parsed = _parsed_with_competing_thesis()
        loaded = self._round_trip(
            parsed, headline="Entity List, top-level es absent",
        )
        # Defensive read mirrors eval.py:3506.
        self.assertEqual(loaded.get("evidence_sources", []), [])


if __name__ == "__main__":
    unittest.main()
