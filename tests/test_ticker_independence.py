"""
tests/test_ticker_independence.py

Independence guarantees for the per-ticker validation cards.

The production bug we are pinning down: distinct symbols (XOM, CVX,
FRO, DAL, UAL) appearing in the same /analyze or /movers payload were
showing byte-identical return windows and sparklines.  Root cause was
yfinance thread-unsafety contaminating the SQLite price cache during
parallel fetches; the lock fix in market_data prevents new corruption,
and the defensive ``market_check._suppress_duplicate_tickers`` pass
suppresses any leftover persisted corruption at the API emission
boundary so the UI never displays misleading shared values.

Tests in this file pin both layers down:

  1. With distinct upstream price series, market_check emits distinct
     return / spark per symbol — every layer of the pipeline.
  2. The suppression helper turns cross-contaminated payloads (multiple
     distinct symbols sharing identical return_5d + spark) into pending
     placeholders, preserving symbol/role.
  3. The api.py boundaries (_build_cached_response, _score_event,
     movers_today, movers_cache slices) all apply the suppression so
     persisted bad data never reaches the response payload.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import market_check
import movers_cache


# ---------------------------------------------------------------------------
# Stub provider — distinct geometric series per symbol so each ticker
# has a verifiably distinct percentage return path.
# ---------------------------------------------------------------------------


def _series(start: float, daily_pct: float, n: int = 22) -> list[float]:
    out = [start]
    for _ in range(n - 1):
        out.append(round(out[-1] * (1 + daily_pct), 4))
    return out


_TICKER_SERIES: dict[str, list[float]] = {
    "XOM": _series(100.0, +0.012),
    "CVX": _series(150.0, -0.004),
    "FRO": _series(30.0,  +0.008),
    "DAL": _series(50.0,  -0.010),
    "UAL": _series(70.0,  -0.015),
    "XLE": _series(80.0,  +0.001),
    "BDRY": _series(20.0, +0.002),
}


def _stub_fetch(ticker: str):
    """Direct replacement for ``market_check._fetch`` — bypasses the
    SQLite price cache so each call returns a fresh per-symbol
    DataFrame regardless of the current date."""
    sym = ticker.upper()
    series = _TICKER_SERIES.get(sym)
    if series is None:
        return None
    import pandas as pd
    end = pd.Timestamp.today().normalize()
    idx = pd.bdate_range(end=end, periods=len(series))
    return pd.DataFrame(
        {"Close": series, "Volume": [1_000_000.0] * len(series)},
        index=idx,
    )


# ---------------------------------------------------------------------------
# Cluster A — _suppress_duplicate_tickers helper
# ---------------------------------------------------------------------------


class TestSuppressDuplicateTickers(unittest.TestCase):
    """The defensive validation pass that catches cross-contaminated
    persisted ticker rows."""

    def _ok_ticker(self, sym: str, r5: float, spark: list[float]) -> dict:
        return {
            "symbol": sym,
            "role": "beneficiary",
            "label": "in motion",
            "direction_tag": "supports \u2191",
            "return_1d": 0.5,
            "return_5d": r5,
            "return_20d": r5 * 1.5,
            "volume_ratio": 1.1,
            "vs_xle_5d": 0.2,
            "spark": spark,
        }

    def test_distinct_symbols_distinct_data_pass_through_unchanged(self):
        """No collisions → every entry preserved with fresh spark copies."""
        tickers = [
            self._ok_ticker("XOM", 5.0, [0.1, 0.5, 0.9]),
            self._ok_ticker("DAL", -3.0, [0.9, 0.5, 0.1]),
            self._ok_ticker("CVX", 1.0, [0.3, 0.4, 0.5]),
        ]
        out = market_check._suppress_duplicate_tickers(tickers)
        self.assertEqual(len(out), 3)
        self.assertEqual([t["return_5d"] for t in out], [5.0, -3.0, 1.0])
        # Fresh copies — not the same list refs as input.
        for original, emitted in zip(tickers, out):
            self.assertIsNot(original["spark"], emitted["spark"])
            self.assertEqual(original["spark"], emitted["spark"])

    def test_three_way_collision_all_become_pending(self):
        """The exact production-bug shape: three distinct symbols with
        identical (return_5d, spark) → all suppressed to pending."""
        spark = [0.101, 0.0, 0.071, 0.244, 0.58, 0.494, 0.595]
        tickers = [
            self._ok_ticker("XOM", 5.02, spark),
            self._ok_ticker("CVX", 5.02, spark),
            self._ok_ticker("FRO", 5.02, spark),
        ]
        out = market_check._suppress_duplicate_tickers(tickers)
        self.assertEqual(len(out), 3)
        for t in out:
            self.assertEqual(t["label"], "needs more evidence")
            self.assertIsNone(t["return_5d"])
            self.assertIsNone(t["return_20d"])
            self.assertIsNone(t["return_1d"])
            self.assertEqual(t["spark"], [])
            self.assertIsNone(t["direction_tag"])
        # Symbols / roles preserved so the UI keeps the right cards.
        self.assertEqual([t["symbol"] for t in out], ["XOM", "CVX", "FRO"])

    def test_collision_in_subset_does_not_taint_distinct_entries(self):
        """A 3-of-5 collision suppresses only the 3 — DAL and CVX with
        distinct data survive intact."""
        spark = [0.1, 0.2, 0.3]
        tickers = [
            self._ok_ticker("XOM", 5.02, spark),
            self._ok_ticker("FRO", 5.02, spark),
            self._ok_ticker("BTU", 5.02, spark),
            self._ok_ticker("DAL", -3.0, [0.9, 0.5, 0.1]),
            self._ok_ticker("CVX", 1.5, [0.4, 0.5, 0.6]),
        ]
        out = market_check._suppress_duplicate_tickers(tickers)
        suppressed = [t for t in out if t["label"] == "needs more evidence"]
        live = [t for t in out if t["label"] != "needs more evidence"]
        self.assertEqual({t["symbol"] for t in suppressed}, {"XOM", "FRO", "BTU"})
        self.assertEqual({t["symbol"] for t in live}, {"DAL", "CVX"})

    def test_pending_entries_with_empty_spark_are_not_grouped(self):
        """Pending tickers (no return, empty spark) must not collide
        with each other — there is no data signature to dedupe on."""
        pending_a = self._ok_ticker("XOM", 0.0, [])
        pending_a["return_5d"] = None
        pending_a["spark"] = []
        pending_b = self._ok_ticker("CVX", 0.0, [])
        pending_b["return_5d"] = None
        pending_b["spark"] = []
        out = market_check._suppress_duplicate_tickers([pending_a, pending_b])
        # Both pass through unchanged — they have no data to compare.
        self.assertEqual(len(out), 2)
        self.assertEqual({t["symbol"] for t in out}, {"XOM", "CVX"})

    def test_same_symbol_appearing_twice_does_not_count_as_collision(self):
        """If a symbol legitimately appears twice (would be a separate
        bug elsewhere) the suppression should not fire — only DISTINCT
        symbols sharing data signal corruption."""
        spark = [0.1, 0.2, 0.3]
        tickers = [
            self._ok_ticker("XOM", 5.0, spark),
            self._ok_ticker("XOM", 5.0, spark),
        ]
        out = market_check._suppress_duplicate_tickers(tickers)
        for t in out:
            self.assertEqual(t["label"], "in motion")

    def test_one_ticker_input_returns_one_ticker_output(self):
        """Single-ticker payloads bypass the collision check."""
        out = market_check._suppress_duplicate_tickers(
            [self._ok_ticker("XOM", 5.0, [0.1, 0.2])],
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["return_5d"], 5.0)

    def test_empty_input_returns_empty(self):
        self.assertEqual(market_check._suppress_duplicate_tickers([]), [])

    def test_returned_lists_are_fresh_copies(self):
        """Mutating an emitted spark must not affect any other emitted
        ticker (or the input)."""
        spark = [0.1, 0.2, 0.3]
        tickers = [
            self._ok_ticker("XOM", 5.0, list(spark)),
            self._ok_ticker("DAL", -3.0, [0.9, 0.5, 0.1]),
        ]
        out = market_check._suppress_duplicate_tickers(tickers)
        out[0]["spark"].append(99.9)
        self.assertEqual(tickers[0]["spark"], [0.1, 0.2, 0.3])
        self.assertNotIn(99.9, out[1]["spark"])


# ---------------------------------------------------------------------------
# Cluster B — market_check end-to-end with distinct provider data
# ---------------------------------------------------------------------------


class TestMarketCheckIndependentTickers(unittest.TestCase):
    """When the underlying source data is distinct per symbol,
    ``market_check.market_check`` must emit distinct
    return_5d / return_20d / spark for every ticker — no shared
    references, no last-loop-value reuse, no fallback collisions."""

    def setUp(self):
        # Patch _fetch directly so each symbol receives its own
        # synthetic series.  Bypasses the price-cache layer.
        self._fetch_patch = patch.object(
            market_check, "_fetch", side_effect=_stub_fetch,
        )
        self._fetch_patch.start()
        market_check._cache_clear()

    def tearDown(self):
        self._fetch_patch.stop()
        market_check._cache_clear()

    def test_five_distinct_tickers_have_five_distinct_returns(self):
        """The exact symbol mix from the user-reported bug
        (XOM/CVX/FRO/DAL/UAL) — every emitted card must carry its
        OWN return_5d, return_20d, and spark series."""
        result = market_check.market_check(
            ["XOM", "CVX", "FRO"],
            ["DAL", "UAL"],
            event_date=None,
        )
        tickers = result["tickers"]
        self.assertEqual(len(tickers), 5)
        self.assertEqual(
            [t["symbol"] for t in tickers],
            ["XOM", "CVX", "FRO", "DAL", "UAL"],
        )

        r5 = [t["return_5d"] for t in tickers]
        r20 = [t["return_20d"] for t in tickers]
        sparks = [tuple(t["spark"]) for t in tickers]

        self.assertEqual(len(set(r5)), 5,
                         f"return_5d not distinct across cards: {r5}")
        self.assertEqual(len(set(r20)), 5,
                         f"return_20d not distinct across cards: {r20}")
        self.assertEqual(len(set(sparks)), 5,
                         "spark series not distinct across cards")

    def test_each_emitted_spark_is_a_fresh_list(self):
        """No two emitted ticker dicts share a spark list reference."""
        result = market_check.market_check(
            ["XOM", "CVX", "FRO"],
            ["DAL", "UAL"],
            event_date=None,
        )
        spark_ids = [id(t["spark"]) for t in result["tickers"]]
        self.assertEqual(len(set(spark_ids)), len(spark_ids),
                         "two emitted ticker dicts share a spark reference")

    def test_mutating_one_emitted_ticker_does_not_leak(self):
        """Defensive fresh-copy contract holds across the full
        market_check pipeline."""
        result = market_check.market_check(
            ["XOM", "CVX"], ["DAL"], event_date=None,
        )
        tickers = result["tickers"]
        original_sparks = {t["symbol"]: list(t["spark"]) for t in tickers}
        tickers[0]["spark"].append(0.999)
        tickers[0]["return_5d"] = -123.0
        for t in tickers[1:]:
            self.assertEqual(t["spark"], original_sparks[t["symbol"]])
            self.assertNotEqual(t["return_5d"], -123.0)

    def test_market_check_suppresses_corrupted_provider_output(self):
        """If a stubbed provider returns the SAME DataFrame for two
        distinct symbols (simulating the yfinance race), market_check
        must suppress the colliding cards to pending instead of
        propagating misleading shared values."""
        import pandas as pd
        end = pd.Timestamp.today().normalize()
        idx = pd.bdate_range(end=end, periods=22)
        # Identical series for both symbols → same r5 and spark.
        shared_df = pd.DataFrame(
            {"Close": [100 + i for i in range(22)],
             "Volume": [1_000_000.0] * 22},
            index=idx,
        )
        # Distinct frame for a third symbol so we can prove it survives.
        distinct_df = pd.DataFrame(
            {"Close": [200 - i for i in range(22)],
             "Volume": [1_000_000.0] * 22},
            index=idx,
        )

        def _shared_fetch(ticker):
            if ticker.upper() in ("AAA", "BBB"):
                return shared_df
            if ticker.upper() == "CCC":
                return distinct_df
            return None

        # Replace the patch from setUp with one that returns shared
        # data for AAA and BBB.
        self._fetch_patch.stop()
        with patch.object(market_check, "_fetch", side_effect=_shared_fetch):
            result = market_check.market_check(
                ["AAA", "BBB", "CCC"], [], event_date=None,
            )
        # Re-arm the original patch so tearDown's stop() does not error.
        self._fetch_patch = patch.object(
            market_check, "_fetch", side_effect=_stub_fetch,
        )
        self._fetch_patch.start()

        by_symbol = {t["symbol"]: t for t in result["tickers"]}
        # AAA and BBB collided → both suppressed to pending.
        self.assertEqual(by_symbol["AAA"]["label"], "needs more evidence")
        self.assertEqual(by_symbol["BBB"]["label"], "needs more evidence")
        self.assertIsNone(by_symbol["AAA"]["return_5d"])
        self.assertIsNone(by_symbol["BBB"]["return_5d"])
        # CCC had distinct data → survives.
        self.assertNotEqual(by_symbol["CCC"]["label"], "needs more evidence")
        self.assertIsNotNone(by_symbol["CCC"]["return_5d"])


# ---------------------------------------------------------------------------
# Cluster C — api.py boundaries apply the suppression
# ---------------------------------------------------------------------------


class TestApiBoundariesApplySuppression(unittest.TestCase):
    """Persisted cross-contaminated ticker payloads must be suppressed
    on the way out of every api.py read path: cached /analyze response,
    /market-movers, /movers/today, /movers/weekly, /movers/persistent."""

    @classmethod
    def setUpClass(cls):
        os.environ["ANTHROPIC_API_KEY"] = ""  # mock path
        from fastapi.testclient import TestClient
        import api
        cls.api = api
        cls.client = TestClient(api.app)

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_ticker_indep_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        # Reset all in-memory caches so each test starts cold.
        movers_cache.invalidate()
        self.api._news_cache["data"] = None
        self.api._news_cache["ts"] = 0.0
        self.api._TODAYS_MOVERS_CACHE["data"] = None
        self.api._TODAYS_MOVERS_CACHE["ts"] = 0.0

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def _seed_corrupted_event(self, *, headline: str, days_old: int = 0) -> int:
        """Save a corrupted event whose tickers all share identical
        return_5d + spark — the production bug shape."""
        spark = [0.101, 0.0, 0.071, 0.244, 0.58, 0.494, 0.595, 0.463,
                 0.605, 0.733, 0.846, 0.751, 0.58, 0.442, 0.719, 0.813,
                 0.742, 0.744, 0.646, 1.0]
        ts = (datetime.now() - timedelta(days=days_old)).isoformat(timespec="seconds")
        event_date = (datetime.now() - timedelta(days=days_old)).strftime("%Y-%m-%d")
        db.save_event({
            "headline": headline,
            "stage": "realized",
            "persistence": "structural",
            "what_changed": "ctx",
            "mechanism_summary": "Iran tensions in the Strait of Hormuz",
            "event_date": event_date,
            "timestamp": ts,
            "market_tickers": [
                {"symbol": "XOM", "role": "beneficiary",
                 "return_5d": 5.02, "return_20d": 17.8, "return_1d": 1.1,
                 "direction_tag": "supports \u2191", "spark": list(spark),
                 "label": "notable move", "volume_ratio": 1.5},
                {"symbol": "CVX", "role": "beneficiary",
                 "return_5d": 5.02, "return_20d": 17.8, "return_1d": 1.1,
                 "direction_tag": "supports \u2191", "spark": list(spark),
                 "label": "notable move", "volume_ratio": 1.5},
                {"symbol": "FRO", "role": "beneficiary",
                 "return_5d": 5.02, "return_20d": 17.8, "return_1d": 1.1,
                 "direction_tag": "supports \u2191", "spark": list(spark),
                 "label": "notable move", "volume_ratio": 1.5},
                {"symbol": "DAL", "role": "loser",
                 "return_5d": 5.02, "return_20d": 17.8, "return_1d": 1.1,
                 "direction_tag": "contradicts \u2191", "spark": list(spark),
                 "label": "notable move", "volume_ratio": 1.5},
            ],
        })
        return db.load_recent_events(1)[0]["id"]

    def _seed_clean_event(self, *, headline: str, days_old: int = 0) -> int:
        """A non-corrupted event with genuinely distinct ticker data."""
        ts = (datetime.now() - timedelta(days=days_old)).isoformat(timespec="seconds")
        event_date = (datetime.now() - timedelta(days=days_old)).strftime("%Y-%m-%d")
        db.save_event({
            "headline": headline,
            "stage": "realized",
            "persistence": "medium",
            "event_date": event_date,
            "timestamp": ts,
            "market_tickers": [
                {"symbol": "GLD", "role": "beneficiary",
                 "return_5d": 4.0, "return_20d": 6.0, "spark": [0.1, 0.5, 0.9],
                 "direction_tag": "supports \u2191", "label": "notable move"},
                {"symbol": "TLT", "role": "beneficiary",
                 "return_5d": 2.0, "return_20d": 3.0, "spark": [0.2, 0.4, 0.7],
                 "direction_tag": "supports \u2191", "label": "in motion"},
            ],
        })
        return db.load_recent_events(1)[0]["id"]

    def test_market_movers_suppresses_corrupted_event(self):
        """A corrupted event must NOT appear in /market-movers as a
        qualifying mover (after suppression all its tickers are pending
        and the qualification check filters it out)."""
        self._seed_corrupted_event(headline="Hormuz strait corrupt")
        self._seed_clean_event(headline="Clean GLD rally")

        r = self.client.get("/market-movers")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        # The corrupted event must not surface; the clean one may
        # or may not (depending on the qualification threshold).
        for mover in body:
            self.assertNotEqual(mover["headline"], "Hormuz strait corrupt")

    def test_movers_today_suppresses_corrupted_event_tickers(self):
        """If a corrupted event still surfaces (because at least one
        ticker has data after suppression — none in this case), its
        tickers must show distinct values, never the corrupted shared
        ones."""
        self._seed_corrupted_event(headline="Hormuz strait corrupt today")

        r = self.client.get("/movers/today")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        # All tickers were corrupted → all suppressed → no qualifying
        # tickers → event drops out of /movers/today entirely.
        for mover in body:
            self.assertNotEqual(mover["headline"], "Hormuz strait corrupt today")

    def test_movers_weekly_suppresses_corruption(self):
        """The persisted movers cache slice must not surface a
        corrupted event with shared values."""
        self._seed_corrupted_event(headline="Hormuz weekly corrupt")
        self._seed_clean_event(headline="Clean weekly")

        r = self.client.get("/movers/weekly")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for mover in body:
            self.assertNotEqual(mover["headline"], "Hormuz weekly corrupt")

    def test_movers_persistent_suppresses_corruption(self):
        """Same contract for the persistent slice."""
        # 10 days old so it qualifies for the strict persistent branch.
        self._seed_corrupted_event(headline="Hormuz persistent corrupt", days_old=10)

        r = self.client.get("/movers/persistent")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for mover in body:
            self.assertNotEqual(mover["headline"], "Hormuz persistent corrupt")

    def test_clean_event_with_distinct_data_still_renders(self):
        """The suppression must NOT throw away legitimately-distinct
        ticker data — the clean event must still render with both
        cards intact."""
        self._seed_clean_event(headline="Clean event survives")
        # Backdate slightly so it sits in the weekly window.
        import sqlite3
        old_ts = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "UPDATE events SET timestamp = ? WHERE headline = ?",
                (old_ts, "Clean event survives"),
            )

        r = self.client.get("/movers/weekly")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        clean = next(
            (m for m in body if m["headline"] == "Clean event survives"),
            None,
        )
        self.assertIsNotNone(clean, f"clean event was filtered out: {body}")
        # Both ticker symbols present with their distinct returns.
        symbols = {t["symbol"]: t for t in clean["tickers"]}
        self.assertIn("GLD", symbols)
        self.assertIn("TLT", symbols)
        self.assertEqual(symbols["GLD"]["return_5d"], 4.0)
        self.assertEqual(symbols["TLT"]["return_5d"], 2.0)

    def test_cached_response_suppresses_corruption(self):
        """The /analyze cached-response path must suppress corrupted
        persisted ticker data so the response payload never displays
        misleading shared values."""
        # Seed a corrupted event under the active model so the cached
        # path actually picks it up.
        spark = [0.101, 0.0, 0.071, 0.244, 0.58]
        headline = f"Cached corrupted {uuid.uuid4().hex[:6]}"
        event_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        db.save_event({
            "headline": headline,
            "stage": "realized",
            "persistence": "structural",
            "event_date": event_date,
            "model": self.api._active_model(),
            "what_changed": "ctx",
            "mechanism_summary": "ctx",
            "market_tickers": [
                {"symbol": "XOM", "role": "beneficiary",
                 "return_5d": 5.02, "return_20d": 17.8, "spark": list(spark),
                 "direction_tag": "supports \u2191", "label": "notable move"},
                {"symbol": "CVX", "role": "beneficiary",
                 "return_5d": 5.02, "return_20d": 17.8, "spark": list(spark),
                 "direction_tag": "supports \u2191", "label": "notable move"},
                {"symbol": "FRO", "role": "beneficiary",
                 "return_5d": 5.02, "return_20d": 17.8, "spark": list(spark),
                 "direction_tag": "supports \u2191", "label": "notable move"},
            ],
        })

        # Patch the freshness refresh path to a no-op so the cached
        # branch reads the persisted tickers as-is.
        from market_check_freshness import refresh_market_for_saved_event as real_refresh
        def _passthrough(event, **kwargs):
            return {
                "tickers": list(event.get("market_tickers", [])),
                "note": event.get("market_note", ""),
                "details": {},
                "last_market_check_at": event.get("last_market_check_at"),
                "market_check_staleness": "fresh",
                "event_age_days": 1,
            }
        with patch("api.refresh_market_for_saved_event", side_effect=_passthrough):
            r = self.client.post(
                "/analyze",
                json={"headline": headline, "event_date": event_date},
            )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        tickers = body["market"]["tickers"]
        # All three colliding cards must be pending — no shared values
        # leak through to the response payload.
        for t in tickers:
            if t["symbol"] in {"XOM", "CVX", "FRO"}:
                self.assertEqual(
                    t["label"], "needs more evidence",
                    f"{t['symbol']} should have been suppressed: {t}",
                )
                self.assertIsNone(t["return_5d"])
                self.assertEqual(t["spark"], [])


if __name__ == "__main__":
    unittest.main()
