"""
tests/test_ranked_asset_round_trip.py

Round-trip and scratch-field guards for ranked-asset persistence.

The three ranked-asset buckets — ``primary_assets``,
``secondary_assets``, ``hedge_or_signal_assets`` — are JSON-encoded
list columns on the ``events`` table.  Each entry's documented shape
is ``{symbol, rank, rationale}`` with two optional fields when
upstream populates them:

  * ``eligibility_classification`` — the desk-facing tier label
    (``primary`` / ``secondary`` / ``signal`` / ``rejected``)
  * ``rejection_reason``           — controlled-vocabulary tag from
    ``asset_selection`` / ``validation_plan`` (e.g.
    ``weak_exposure``, ``duplicate_proxy``, ``signal_only_not_beneficiary``)

These tests pin the contract:
  1. Save → load round-trips every one of those fields when the
     analysis carries them.
  2. Internal scratch fields (``_raw_beneficiary_tickers``,
     ``_raw_loser_tickers``) NEVER reach the persisted row or bleed
     into ``load_event_by_id`` / ``find_cached_analysis`` output.
  3. Missing ranked-asset fields on legacy rows decode as stable
     empty lists — never ``None``, never raw JSON strings.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

import db as db_module
from db import (
    _decode_event_row,
    find_cached_analysis,
    init_db,
    load_event_by_id,
    save_event,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_event(**overrides) -> dict:
    base = {
        "headline":          "headline",
        "stage":              "test",
        "persistence":        "1d",
        "what_changed":       "x",
        "mechanism_summary":  "y",
        "beneficiaries":      ["A"],
        "losers":             ["B"],
        "assets_to_watch":    [],
        "confidence":         "medium",
        "market_note":        "",
        "market_tickers":     [],
        "event_date":         "2025-01-15",
        "notes":              "",
        "model":              "test-model",
    }
    base.update(overrides)
    return base


class _IsolatedDbTestCase(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._orig_db = db_module.DB_FILE
        db_module.DB_FILE = self._tmp.name
        db_module._db_ready = False
        init_db()

    def tearDown(self) -> None:
        db_module.DB_FILE = self._orig_db
        db_module._db_ready = False
        try:
            os.unlink(self._tmp.name)
        except (PermissionError, OSError):
            pass

    def _row_id(self) -> int:
        with sqlite3.connect(db_module.DB_FILE) as conn:
            (rid,) = conn.execute(
                "SELECT id FROM events ORDER BY id DESC LIMIT 1",
            ).fetchone()
        return rid


# ---------------------------------------------------------------------------
# 1. Save → load round-trip preserves required + optional fields
# ---------------------------------------------------------------------------


class RoundTripCoreFieldsTests(_IsolatedDbTestCase):

    def test_primary_assets_round_trip_preserves_rank_and_rationale(self) -> None:
        primary = [
            {"symbol": "XOM", "rank": 1,
             "rationale": "Direct integrated-major beneficiary on the OPEC cut."},
            {"symbol": "CVX", "rank": 2,
             "rationale": "Gulf Coast feedstock margin expansion."},
        ]
        save_event(_minimal_event(
            headline="round-trip primary",
            primary_assets=primary,
        ))
        loaded = load_event_by_id(self._row_id())
        self.assertEqual(loaded["primary_assets"], primary)

    def test_all_three_buckets_round_trip(self) -> None:
        primary    = [{"symbol": "XOM", "rank": 1, "rationale": "direct beneficiary"}]
        secondary  = [{"symbol": "XLE", "rank": 1, "rationale": "sector ETF read"}]
        hedge      = [{"symbol": "VXX", "rank": 1, "rationale": "vol hedge"}]
        save_event(_minimal_event(
            headline="three buckets",
            primary_assets=primary,
            secondary_assets=secondary,
            hedge_or_signal_assets=hedge,
        ))
        loaded = load_event_by_id(self._row_id())
        self.assertEqual(loaded["primary_assets"],         primary)
        self.assertEqual(loaded["secondary_assets"],       secondary)
        self.assertEqual(loaded["hedge_or_signal_assets"], hedge)

    def test_optional_eligibility_classification_round_trips(self) -> None:
        primary = [{
            "symbol":                    "XOM",
            "rank":                      1,
            "rationale":                 "Direct integrated-major beneficiary.",
            "eligibility_classification": "primary",
        }]
        save_event(_minimal_event(
            headline="eligibility round-trip",
            primary_assets=primary,
        ))
        loaded = load_event_by_id(self._row_id())
        self.assertEqual(len(loaded["primary_assets"]), 1)
        entry = loaded["primary_assets"][0]
        self.assertEqual(entry["symbol"],                     "XOM")
        self.assertEqual(entry["rank"],                       1)
        self.assertIn("rationale",                            entry)
        self.assertEqual(entry["eligibility_classification"], "primary")

    def test_optional_rejection_reason_round_trips(self) -> None:
        secondary = [{
            "symbol":            "XLU",
            "rank":              1,
            "rationale":         "Utilities ETF — mechanism mismatch on this thesis.",
            "rejection_reason":  "weak_exposure",
        }]
        save_event(_minimal_event(
            headline="rejection_reason round-trip",
            secondary_assets=secondary,
        ))
        loaded = load_event_by_id(self._row_id())
        entry = loaded["secondary_assets"][0]
        self.assertEqual(entry["symbol"],           "XLU")
        self.assertEqual(entry["rejection_reason"], "weak_exposure")

    def test_round_trip_via_decode_event_row_directly(self) -> None:
        """Round-trip through ``_decode_event_row`` — the path
        ``load_recent_events`` and ``find_cached_analysis`` share."""
        save_event(_minimal_event(
            headline="decode round-trip",
            primary_assets=[
                {"symbol": "XOM", "rank": 1, "rationale": "direct"},
                {"symbol": "CVX", "rank": 2, "rationale": "feedstock margin"},
            ],
        ))
        with sqlite3.connect(db_module.DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM events LIMIT 1").fetchone()
        ev = _decode_event_row(row)
        self.assertIsInstance(ev["primary_assets"], list)
        self.assertEqual(len(ev["primary_assets"]), 2)
        self.assertEqual(ev["primary_assets"][0]["symbol"], "XOM")
        self.assertEqual(ev["primary_assets"][1]["rank"],   2)


# ---------------------------------------------------------------------------
# 2. Scratch fields never persist or leak
# ---------------------------------------------------------------------------


class ScratchFieldGuardTests(_IsolatedDbTestCase):

    def test_raw_ticker_scratch_fields_not_persisted_to_db(self) -> None:
        """``_raw_beneficiary_tickers`` and ``_raw_loser_tickers`` are
        intermediate fields populated by ``_normalize_schema`` and
        popped by ``_finalize_analysis``.  They have no DB column —
        even if a caller hands a dict carrying them to ``save_event``,
        they must not surface anywhere on the persisted row."""
        save_event(_minimal_event(
            headline="scratch guard",
            _raw_beneficiary_tickers=["XOM", "CVX"],
            _raw_loser_tickers=["DAL"],
        ))
        with sqlite3.connect(db_module.DB_FILE) as conn:
            cols = [
                r[1] for r in conn.execute(
                    "PRAGMA table_info(events)",
                ).fetchall()
            ]
        self.assertNotIn("_raw_beneficiary_tickers", cols)
        self.assertNotIn("_raw_loser_tickers", cols)

    def test_load_event_by_id_does_not_surface_scratch_fields(self) -> None:
        save_event(_minimal_event(
            headline="scratch guard 2",
            _raw_beneficiary_tickers=["XOM"],
            _raw_loser_tickers=["DAL"],
        ))
        loaded = load_event_by_id(self._row_id())
        self.assertNotIn("_raw_beneficiary_tickers", loaded)
        self.assertNotIn("_raw_loser_tickers", loaded)

    def test_find_cached_analysis_does_not_surface_scratch_fields(self) -> None:
        save_event(_minimal_event(
            headline="scratch guard cached",
            event_date="2025-05-01",
            _raw_beneficiary_tickers=["XOM"],
        ))
        cached = find_cached_analysis(
            "scratch guard cached", event_date="2025-05-01",
        )
        self.assertIsNotNone(cached)
        self.assertNotIn("_raw_beneficiary_tickers", cached)
        self.assertNotIn("_raw_loser_tickers", cached)

    def test_decoded_row_does_not_surface_scratch_fields(self) -> None:
        save_event(_minimal_event(
            headline="scratch guard decode",
            _raw_beneficiary_tickers=["XOM"],
            _raw_loser_tickers=["DAL"],
        ))
        with sqlite3.connect(db_module.DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM events LIMIT 1").fetchone()
        ev = _decode_event_row(row)
        self.assertNotIn("_raw_beneficiary_tickers", ev)
        self.assertNotIn("_raw_loser_tickers", ev)

    def test_finalize_analysis_strips_scratch_fields(self) -> None:
        """End-to-end: a parsed LLM dict carrying the scratch fields
        in raw form must produce a finalised result with the scratch
        fields popped — they are intermediate values populated by
        ``_normalize_schema`` and consumed inside ``_finalize_analysis``."""
        from analyze_event import _finalize_analysis
        parsed = {
            "what_changed":       "Saudi Aramco cuts liftings by 1mbd.",
            "mechanism_summary":  (
                "Saudi Aramco crude lifting reduction tightens Gulf "
                "Coast refinery feedstock and widens WCS-WTI spread."
            ),
            "beneficiaries":          ["XOM", "CVX"],
            "losers":                  ["DAL"],
            "beneficiary_tickers":    ["XOM", "CVX"],
            "loser_tickers":           ["DAL"],
            "mechanism_family":       "supply_shock",
            "primary_assets":         [],
            "secondary_assets":       [],
            "hedge_or_signal_assets": [],
        }
        out = _finalize_analysis(
            parsed,
            headline="OPEC cuts crude liftings",
            stage="realized",
            persistence="1d",
        )
        self.assertNotIn("_raw_beneficiary_tickers", out)
        self.assertNotIn("_raw_loser_tickers", out)


# ---------------------------------------------------------------------------
# 3. Missing fields on old rows default to stable empty lists
# ---------------------------------------------------------------------------


class LegacyRowDefaultsTests(_IsolatedDbTestCase):

    def test_legacy_row_without_ranked_asset_columns_loads_as_empty_lists(
        self,
    ) -> None:
        """A pre-ranked-asset event (saved before the columns were
        added) must decode with empty-list defaults — never ``None``,
        never the raw JSON string."""
        save_event(_minimal_event(headline="legacy row"))
        # Simulate a pre-migration row by NULL-ing the ranked-asset
        # columns the way an older DB would carry them.
        with sqlite3.connect(db_module.DB_FILE) as conn:
            conn.execute(
                "UPDATE events SET "
                "primary_assets = NULL, "
                "secondary_assets = NULL, "
                "hedge_or_signal_assets = NULL",
            )
        loaded = load_event_by_id(self._row_id())
        self.assertEqual(loaded["primary_assets"],         [])
        self.assertEqual(loaded["secondary_assets"],       [])
        self.assertEqual(loaded["hedge_or_signal_assets"], [])

    def test_empty_string_in_column_decodes_to_empty_list(self) -> None:
        save_event(_minimal_event(headline="legacy empty string"))
        with sqlite3.connect(db_module.DB_FILE) as conn:
            conn.execute(
                "UPDATE events SET "
                "primary_assets = '', "
                "secondary_assets = '', "
                "hedge_or_signal_assets = ''",
            )
        loaded = load_event_by_id(self._row_id())
        self.assertEqual(loaded["primary_assets"],         [])
        self.assertEqual(loaded["secondary_assets"],       [])
        self.assertEqual(loaded["hedge_or_signal_assets"], [])

    def test_invalid_json_in_ranked_asset_column_decodes_to_empty_list(
        self,
    ) -> None:
        save_event(_minimal_event(headline="legacy invalid json"))
        with sqlite3.connect(db_module.DB_FILE) as conn:
            conn.execute(
                "UPDATE events SET primary_assets = ?",
                ("{not json",),
            )
        loaded = load_event_by_id(self._row_id())
        self.assertEqual(loaded["primary_assets"], [])

    def test_default_value_when_save_omits_ranked_asset_field(self) -> None:
        """``save_event`` defaults missing ranked-asset fields to ``[]``
        before serialising — the legacy event with no ranked assets
        round-trips as empty lists, not as ``None``."""
        save_event(_minimal_event(headline="legacy save omits"))
        loaded = load_event_by_id(self._row_id())
        self.assertEqual(loaded["primary_assets"],         [])
        self.assertEqual(loaded["secondary_assets"],       [])
        self.assertEqual(loaded["hedge_or_signal_assets"], [])


if __name__ == "__main__":
    unittest.main()
