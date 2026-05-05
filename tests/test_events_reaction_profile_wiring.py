"""tests/test_events_reaction_profile_wiring.py

Smoke tests for wiring ``reaction_profile.compute_reaction_profile``
into ``GET /events/{event_id}`` detail responses.

Contract pinned here:

  * Detail body carries a ``reaction_profile_v1`` block on every
    response, regardless of whether the saved row has enough data to
    score the profile.
  * Block shape is stable: ``{available, reason, tickers, n_tickers}``.
  * Per-ticker entries carry the full key set the pure calculator
    emits (return_*, benchmark_relative_return_*, peak_move_*,
    time_to_peak_*, fade_or_hold_label_*, reaction_profile_basis) plus
    a ``symbol`` field.
  * Stored ``market_tickers`` rows do not carry a raw close series —
    saved tickers expose scalar ``return_5d`` and a normalized
    ``spark`` only.  The pure calculator therefore returns its
    null-safe / unscorable shape, and the wrapper carries
    ``available = False`` with an explicit ``reason`` so the consumer
    can branch deterministically on availability without re-deriving
    the cause.
  * Endpoint stays read-only: no DB writes, no provider calls.
  * Existing detail fields (validation_status_v2, mover_context,
    market_tickers, …) stay byte-stable.

Filter / list-side wiring is intentionally out of scope; this is the
detail-only surface per ``docs/reaction_profile_design.md``.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import api
import movers_cache
from fastapi.testclient import TestClient

client = TestClient(api.app)


# ---------------------------------------------------------------------------
# Shape contract — names mirrored from reaction_profile._empty_profile
# ---------------------------------------------------------------------------

_REQUIRED_BLOCK_KEYS = {"available", "reason", "tickers", "n_tickers"}

_RETURN_HORIZONS = ("1d", "5d", "20d", "60d")
_PEAK_HORIZONS   = ("5d", "20d", "60d")


def _expected_per_ticker_keys() -> set[str]:
    keys = {"symbol", "reaction_profile_basis"}
    for h in _RETURN_HORIZONS:
        keys.add(f"return_{h}")
        keys.add(f"benchmark_relative_return_{h}")
    for h in _PEAK_HORIZONS:
        keys.add(f"peak_move_{h}")
        keys.add(f"time_to_peak_{h}")
        keys.add(f"fade_or_hold_label_{h}")
    return keys


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _tmp_db() -> str:
    return os.path.join(
        tempfile.gettempdir(),
        f"test_events_rp_wiring_{uuid.uuid4().hex}.db",
    )


def _reset_caches() -> None:
    movers_cache.invalidate()
    api._news_cache["data"] = None
    api._news_cache["ts"] = 0.0
    api._TODAYS_MOVERS_CACHE["data"] = None
    api._TODAYS_MOVERS_CACHE["ts"] = 0.0
    api._WEEKLY_MOVERS_CACHE["data"] = None
    api._YEARLY_MOVERS_CACHE["data"] = None
    api._PERSISTENT_MOVERS_CACHE["data"] = None


def _today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _ticker(symbol: str = "XLE", direction_tag: str = "supports ↑") -> dict:
    return {
        "symbol":        symbol,
        "role":          "beneficiary",
        "return_5d":     4.0,
        "direction_tag": direction_tag,
        "anchor_date":   _today_iso(),
    }


def _seed(
    *,
    headline: str = "Reaction-profile seed event",
    tickers: list[dict] | None = None,
    days_old: int = 1,
) -> int:
    today = _today_iso()
    ts = (datetime.now() - timedelta(days=days_old)).isoformat(timespec="seconds")
    db.save_event({
        "headline":           headline,
        "stage":              "realized",
        "persistence":        "structural",
        "event_date":         today,
        "timestamp":          ts,
        "what_changed":       "Real change description",
        "mechanism_summary":  "Mechanism summary text long enough to pass.",
        "transmission_chain": ["a", "b"],
        "if_persists":        {"thesis": "stub"},
        "market_tickers":     [_ticker()] if tickers is None else tickers,
        "confidence":         "medium",
    })
    return db.load_recent_events(1)[0]["id"]


def _snapshot_events_table(path: str) -> list[tuple]:
    with sqlite3.connect(path) as conn:
        return list(conn.execute("SELECT * FROM events ORDER BY id"))


# ---------------------------------------------------------------------------
# Base — temp DB per test
# ---------------------------------------------------------------------------


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.setdefault("ANTHROPIC_API_KEY", "")
        self._orig = db.DB_FILE
        self._tmp = _tmp_db()
        db.DB_FILE = self._tmp
        db.init_db()
        _reset_caches()

    def tearDown(self) -> None:
        db.DB_FILE = self._orig
        _reset_caches()
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass


# ---------------------------------------------------------------------------
# Detail block shape
# ---------------------------------------------------------------------------


class TestDetailReactionProfileBlock(_Base):
    def test_detail_carries_reaction_profile_v1_block(self) -> None:
        eid = _seed()
        body = client.get(f"/events/{eid}").json()
        self.assertIn("reaction_profile_v1", body)
        rp = body["reaction_profile_v1"]
        self.assertIsInstance(rp, dict)
        self.assertEqual(set(rp.keys()), _REQUIRED_BLOCK_KEYS)
        self.assertIsInstance(rp["available"], bool)
        self.assertIsInstance(rp["reason"], str)
        self.assertGreater(len(rp["reason"]), 0)
        self.assertIsInstance(rp["tickers"], list)
        self.assertIsInstance(rp["n_tickers"], int)
        self.assertEqual(rp["n_tickers"], len(rp["tickers"]))

    def test_per_ticker_entry_has_full_pure_calculator_keyset(self) -> None:
        eid = _seed()  # 1 default ticker
        rp = client.get(f"/events/{eid}").json()["reaction_profile_v1"]
        self.assertEqual(rp["n_tickers"], 1)
        per_ticker = rp["tickers"][0]
        self.assertEqual(set(per_ticker.keys()), _expected_per_ticker_keys())
        self.assertEqual(per_ticker["symbol"], "XLE")

    def test_multiple_tickers_each_get_their_own_entry(self) -> None:
        eid = _seed(tickers=[_ticker("XLE"), _ticker("XOM"), _ticker("CVX")])
        rp = client.get(f"/events/{eid}").json()["reaction_profile_v1"]
        self.assertEqual(rp["n_tickers"], 3)
        symbols = [t["symbol"] for t in rp["tickers"]]
        self.assertEqual(symbols, ["XLE", "XOM", "CVX"])
        for entry in rp["tickers"]:
            self.assertEqual(set(entry.keys()), _expected_per_ticker_keys())


# ---------------------------------------------------------------------------
# Insufficient-data behaviour — explicit unscorable shape
# ---------------------------------------------------------------------------


class TestInsufficientDataBehaviour(_Base):
    def test_unscorable_basis_when_raw_closes_not_stored(self) -> None:
        # Saved tickers do not carry raw close series — only scalar
        # returns + a normalized sparkline.  The pure calculator must
        # therefore emit ``unscorable`` for every per-ticker row.
        eid = _seed()
        rp = client.get(f"/events/{eid}").json()["reaction_profile_v1"]
        for entry in rp["tickers"]:
            self.assertEqual(entry["reaction_profile_basis"], "unscorable")

    def test_unscorable_fields_are_null_safe(self) -> None:
        eid = _seed()
        per_ticker = client.get(
            f"/events/{eid}",
        ).json()["reaction_profile_v1"]["tickers"][0]
        for h in _RETURN_HORIZONS:
            self.assertIsNone(per_ticker[f"return_{h}"])
            self.assertIsNone(per_ticker[f"benchmark_relative_return_{h}"])
        for h in _PEAK_HORIZONS:
            self.assertIsNone(per_ticker[f"peak_move_{h}"])
            self.assertIsNone(per_ticker[f"time_to_peak_{h}"])
            self.assertEqual(per_ticker[f"fade_or_hold_label_{h}"], "insufficient")

    def test_block_available_false_when_all_tickers_unscorable(self) -> None:
        eid = _seed()
        rp = client.get(f"/events/{eid}").json()["reaction_profile_v1"]
        self.assertFalse(rp["available"])

    def test_no_tickers_returns_empty_shape(self) -> None:
        eid = _seed(tickers=[])
        rp = client.get(f"/events/{eid}").json()["reaction_profile_v1"]
        self.assertEqual(rp["tickers"], [])
        self.assertEqual(rp["n_tickers"], 0)
        self.assertFalse(rp["available"])
        # Reason for no_tickers is distinct from "tickers exist but
        # raw closes missing" so consumers can branch.
        self.assertNotEqual(rp["reason"], "")

    def test_non_dict_ticker_entries_are_skipped_safely(self) -> None:
        eid = _seed(tickers=[_ticker("XLE")])
        # Patch the in-memory event row that the route loads to also
        # carry junk entries in market_tickers; verifies the helper
        # tolerates malformed entries without raising.
        original = api.load_event_by_id

        def _wrapped(eid_in: int):
            ev = original(eid_in)
            if ev is not None:
                ev = dict(ev)
                ev["market_tickers"] = list(ev.get("market_tickers") or []) + [
                    "not-a-dict", 42, None,
                ]
            return ev

        with patch.object(api, "load_event_by_id", side_effect=_wrapped):
            rp = client.get(f"/events/{eid}").json()["reaction_profile_v1"]
        # Only the one valid dict-shaped ticker survives.
        self.assertEqual(rp["n_tickers"], 1)
        self.assertEqual(rp["tickers"][0]["symbol"], "XLE")


# ---------------------------------------------------------------------------
# Existing detail fields are preserved
# ---------------------------------------------------------------------------


class TestExistingFieldsPreserved(_Base):
    def test_validation_status_v2_still_present(self) -> None:
        eid = _seed()
        body = client.get(f"/events/{eid}").json()
        self.assertIn("validation_status_v2", body)
        self.assertIn("status", body["validation_status_v2"])

    def test_mover_context_still_present(self) -> None:
        eid = _seed()
        body = client.get(f"/events/{eid}").json()
        self.assertIn("mover_context", body)
        self.assertIsInstance(body["mover_context"], dict)

    def test_market_tickers_still_present_and_unmodified(self) -> None:
        eid = _seed()
        body = client.get(f"/events/{eid}").json()
        self.assertIn("market_tickers", body)
        self.assertEqual(len(body["market_tickers"]), 1)
        self.assertEqual(body["market_tickers"][0]["symbol"], "XLE")
        # No reaction-profile fields leaked into the original tickers
        # block — those must live under reaction_profile_v1.tickers,
        # never on the saved market_tickers entries.
        self.assertNotIn("reaction_profile_basis", body["market_tickers"][0])
        self.assertNotIn("peak_move_5d",            body["market_tickers"][0])


# ---------------------------------------------------------------------------
# Read-only contract — no DB writes, no provider calls
# ---------------------------------------------------------------------------


class TestReactionProfileReadOnlyContract(_Base):
    def test_detail_does_not_write_to_db(self) -> None:
        eid = _seed()
        before = _snapshot_events_table(self._tmp)
        r = client.get(f"/events/{eid}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("reaction_profile_v1", r.json())
        after = _snapshot_events_table(self._tmp)
        self.assertEqual(before, after, "detail mutated events table")

    def test_detail_makes_no_provider_calls(self) -> None:
        eid = _seed()
        with patch("api.analyze_event",
                   side_effect=AssertionError("detail must not call analyze_event")), \
             patch("api.market_check",
                   side_effect=AssertionError("detail must not call market_check")), \
             patch("yfinance.download",
                   side_effect=AssertionError("detail must not call yfinance.download")), \
             patch("yfinance.Ticker",
                   side_effect=AssertionError("detail must not call yfinance.Ticker")):
            r = client.get(f"/events/{eid}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("reaction_profile_v1", r.json())


# ---------------------------------------------------------------------------
# List does NOT carry the block (out of scope per task)
# ---------------------------------------------------------------------------


class TestListDoesNotCarryBlock(_Base):
    def test_list_items_do_not_carry_reaction_profile_v1(self) -> None:
        # Distinct headlines so dedup does not collapse a seed.
        _seed(headline="OPEC announces production cut of 500k bpd")
        _seed(headline="ECB holds policy rate steady at 4 percent")
        items = client.get("/events?limit=10").json()["items"]
        self.assertGreater(len(items), 0)
        for item in items:
            self.assertNotIn(
                "reaction_profile_v1", item,
                "list items must not carry reaction_profile_v1 yet",
            )


if __name__ == "__main__":
    unittest.main()
