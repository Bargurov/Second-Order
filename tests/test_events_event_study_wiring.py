"""tests/test_events_event_study_wiring.py

Smoke tests for wiring ``event_study_validation.build_event_study_validation``
into ``GET /events/{event_id}`` detail responses (E5).

Contract pinned here:

  * Detail body carries an ``event_study`` block on every response.
  * For a ready event the block is the gate's ``event_study_available``
    payload with per-horizon ``abnormal_return`` / ``sar`` / ``car`` and the
    n=1 non-claim markers (``cross_sectional_inference.available == False``,
    ``claims.not_claimed``).
  * For a non-ready event the block is the gate's ``insufficient_data``
    payload with ``blocking_reasons`` and no point estimates.
  * The detail ``event_study`` block equals the standalone
    ``GET /events/{id}/event-study`` payload for the same event.
  * Existing additive detail fields (``validation_status_v2``,
    ``reaction_profile_v1``) stay present/unchanged.
  * An engine failure must NOT 500 the detail endpoint — it degrades to a
    stable insufficient-shaped block.
  * The endpoint stays read-only — no DB writes.

No LLM, market_check, or yfinance — events + price_cache are seeded directly
into a temp DB.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import date, datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import api
import movers_cache
from fastapi.testclient import TestClient

client = TestClient(api.app)


# ---------------------------------------------------------------------------
# Ready-event price seeding (mirror tests/test_event_study_validation)
# ---------------------------------------------------------------------------

_EVENT_D = date(2026, 3, 16)  # a Monday
_EVENT_ISO = _EVENT_D.isoformat()


def _bdays_before(anchor: date, count: int) -> list[date]:
    out: list[date] = []
    cur = anchor
    while len(out) < count:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            out.append(cur)
    out.reverse()
    return out


def _bdays_after(anchor: date, count: int) -> list[date]:
    out: list[date] = []
    cur = anchor
    while len(out) < count:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            out.append(cur)
    return out


def _close(i: int, base: float, *, noise: bool = True, jump_from: int | None = None) -> float:
    val = base * (1 + 0.0005 * i + (0.003 * ((-1) ** i) if noise else 0.0))
    if jump_from is not None and i >= jump_from:
        val *= 1.04
    return round(val, 4)


def _ready_price_rows() -> list[tuple]:
    """(ticker, iso_date, close, auto_adjust) making XLE event_study_available."""
    pre = _bdays_before(_EVENT_D, 65)
    post = _bdays_after(_EVENT_D, 25)
    dates = pre + [_EVENT_D] + post
    event_index = len(pre)
    rows: list[tuple] = []
    for i, d in enumerate(dates):
        rows.append(("SPY", d.isoformat(), _close(i, 100.0, noise=False), 0))
        rows.append(("XLE", d.isoformat(), _close(i, 50.0, jump_from=event_index + 1), 0))
    return rows


def _reset_caches() -> None:
    movers_cache.invalidate()
    api._news_cache["data"] = None
    api._news_cache["ts"] = 0.0
    api._TODAYS_MOVERS_CACHE["data"] = None
    api._TODAYS_MOVERS_CACHE["ts"] = 0.0
    api._WEEKLY_MOVERS_CACHE["data"] = None
    api._YEARLY_MOVERS_CACHE["data"] = None
    api._PERSISTENT_MOVERS_CACHE["data"] = None


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.setdefault("ANTHROPIC_API_KEY", "")
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_events_es_wiring_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        import price_cache as _pc
        _pc._reset_table_ready_for_tests()
        _reset_caches()

    def tearDown(self) -> None:
        db.DB_FILE = self._orig
        _reset_caches()
        import price_cache as _pc
        _pc._reset_table_ready_for_tests()
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    def _seed(self, *, headline: str, tickers: list[dict], event_date: str = _EVENT_ISO) -> int:
        db.save_event({
            "headline":           headline,
            "stage":              "realized",
            "persistence":        "structural",
            "event_date":         event_date,
            "timestamp":          datetime.now().isoformat(timespec="seconds"),
            "what_changed":       "Real change description",
            "mechanism_summary":  "Mechanism summary text long enough to pass.",
            "market_tickers":     tickers,
            "confidence":         "medium",
        })
        return db.load_recent_events(1)[0]["id"]

    def _seed_ready_prices(self) -> None:
        rows = _ready_price_rows()
        with sqlite3.connect(self._tmp) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(t, d, c, 1000.0, aa, "2026-01-01T00:00:00") for (t, d, c, aa) in rows],
            )

    def _snapshot(self):
        with sqlite3.connect(self._tmp) as conn:
            events = list(conn.execute("SELECT * FROM events ORDER BY id"))
            cache = list(conn.execute(
                "SELECT ticker, date, close, volume, auto_adjust "
                "FROM price_cache ORDER BY ticker, date, auto_adjust"
            ))
        return events, cache


# ---------------------------------------------------------------------------
# Ready event
# ---------------------------------------------------------------------------

class TestReadyEventDetail(_Base):
    def test_detail_carries_available_event_study(self) -> None:
        self._seed_ready_prices()
        eid = self._seed(
            headline="Ready XLE event",
            tickers=[{"symbol": "XLE", "role": "beneficiary"}],
        )
        body = client.get(f"/events/{eid}").json()
        self.assertIn("event_study", body)
        es = body["event_study"]
        self.assertEqual(es["status"], "event_study_available")
        self.assertEqual(es["primary_ticker"], "XLE")
        self.assertEqual(es["benchmark"], "SPY")
        horizons = {h["horizon"]: h for h in es["per_horizon"]}
        self.assertEqual(set(horizons), {1, 5, 20})
        for h in (1, 5, 20):
            self.assertIsNotNone(horizons[h]["abnormal_return"])
            self.assertIsNotNone(horizons[h]["sar"])
            self.assertIsNotNone(horizons[h]["car"])

    def test_available_block_carries_n1_non_claims(self) -> None:
        self._seed_ready_prices()
        eid = self._seed(headline="Ready XLE non-claims", tickers=[{"symbol": "XLE"}])
        es = client.get(f"/events/{eid}").json()["event_study"]
        self.assertFalse(es["cross_sectional_inference"]["available"])
        self.assertEqual(es["cross_sectional_inference"]["n_events"], 1)
        self.assertIn("confirmed", es["claims"]["not_claimed"])
        self.assertIn("validated", es["claims"]["not_claimed"])
        self.assertIn("confidence_interval", es["claims"]["not_claimed"])


# ---------------------------------------------------------------------------
# Insufficient event
# ---------------------------------------------------------------------------

class TestInsufficientEventDetail(_Base):
    def test_no_ticker_event_is_insufficient(self) -> None:
        eid = self._seed(headline="No ticker event", tickers=[])
        es = client.get(f"/events/{eid}").json()["event_study"]
        self.assertEqual(es["status"], "insufficient_data")
        self.assertIn("no_primary_ticker", es["blocking_reasons"])
        self.assertNotIn("per_horizon", es)


# ---------------------------------------------------------------------------
# Consistency: detail block == standalone route payload
# ---------------------------------------------------------------------------

class TestDetailMatchesStandaloneRoute(_Base):
    def test_ready_event_consistency(self) -> None:
        self._seed_ready_prices()
        eid = self._seed(headline="Consistency XLE event", tickers=[{"symbol": "XLE"}])
        detail_es = client.get(f"/events/{eid}").json()["event_study"]
        route_es = client.get(f"/events/{eid}/event-study").json()
        self.assertEqual(detail_es, route_es)

    def test_insufficient_event_consistency(self) -> None:
        eid = self._seed(headline="Consistency no-ticker", tickers=[])
        detail_es = client.get(f"/events/{eid}").json()["event_study"]
        route_es = client.get(f"/events/{eid}/event-study").json()
        self.assertEqual(detail_es, route_es)


# ---------------------------------------------------------------------------
# Existing additive fields preserved
# ---------------------------------------------------------------------------

class TestExistingFieldsPreserved(_Base):
    def test_validation_status_v2_and_reaction_profile_present(self) -> None:
        self._seed_ready_prices()
        eid = self._seed(headline="Fields XLE event", tickers=[{"symbol": "XLE"}])
        body = client.get(f"/events/{eid}").json()
        self.assertIn("validation_status_v2", body)
        self.assertIn("status", body["validation_status_v2"])
        self.assertIn("reaction_profile_v1", body)
        self.assertEqual(
            set(body["reaction_profile_v1"].keys()),
            {"available", "reason", "tickers", "n_tickers"},
        )


# ---------------------------------------------------------------------------
# Defensive wrap — engine failure must not 500 the detail
# ---------------------------------------------------------------------------

class TestDefensiveWrap(_Base):
    def test_engine_failure_does_not_500_detail(self) -> None:
        eid = self._seed(headline="Defensive event", tickers=[{"symbol": "XLE"}])
        with patch(
            "routes.events.build_event_study_validation",
            side_effect=RuntimeError("boom"),
        ):
            r = client.get(f"/events/{eid}")
        self.assertEqual(r.status_code, 200, r.text)
        es = r.json()["event_study"]
        self.assertEqual(es["status"], "insufficient_data")
        self.assertIn("blocking_reasons", es)
        self.assertTrue(es["blocking_reasons"])


# ---------------------------------------------------------------------------
# Read-only contract
# ---------------------------------------------------------------------------

class TestReadOnly(_Base):
    def test_detail_with_event_study_does_not_write_db(self) -> None:
        self._seed_ready_prices()
        eid = self._seed(headline="Readonly XLE event", tickers=[{"symbol": "XLE"}])
        before = self._snapshot()
        r = client.get(f"/events/{eid}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("event_study", r.json())
        self.assertEqual(before, self._snapshot(), "detail mutated the DB")


if __name__ == "__main__":
    unittest.main()
