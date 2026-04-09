"""
tests/test_analog_dedup_and_ticker_binding.py

Release-candidate hardening tests for the two analysis-correctness
clusters flagged by user feedback:

  1. Historical Analogs must not surface duplicate or near-duplicate
     copies of the same story in the top 3.  Dedup runs by story-family
     key (normalised content words + event_date) BEFORE rerank /
     truncation, preserving the highest-scoring representative.

  2. Real-Time Market Validation cards must each bind to their own
     return / sparkline / status — no shared series, no shared dict
     references between ticker dicts.  The defensive fix dedupes by
     symbol and forces a fresh ``spark`` list per emitted ticker.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch  # noqa: F401

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import market_check
import market_check_freshness as mcf


# ---------------------------------------------------------------------------
# Cluster 1 — Historical Analog dedup
# ---------------------------------------------------------------------------


def _save_analog(
    *,
    headline: str,
    event_date: str,
    return_5d: float = 4.0,
    timestamp: str | None = None,
) -> int:
    """Insert an analog candidate.  Returns the new event id."""
    record = {
        "headline": headline,
        "stage": "realized",
        "persistence": "structural",
        "what_changed": "ctx",
        "mechanism_summary": "Trump threatens Iran sanctions over Hormuz strait closure",
        "beneficiaries": ["XOM"],
        "losers": ["DAL"],
        "assets_to_watch": ["XOM"],
        "confidence": "high",
        "market_note": "",
        "market_tickers": [
            {"symbol": "XOM", "role": "beneficiary",
             "return_5d": return_5d, "return_20d": return_5d * 1.1,
             "direction_tag": "supports \u2191"},
        ],
        "event_date": event_date,
    }
    if timestamp:
        record["timestamp"] = timestamp
    db.save_event(record)
    return db.load_recent_events(1)[0]["id"]


class TestAnalogDedup(unittest.TestCase):
    """Top-3 analogs must be three genuinely distinct stories."""

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_analog_dedup_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def _backdate(self, event_id: int, minutes: int) -> None:
        """Push the timestamp back so the dedup-window check doesn't
        block a second insert with the same headline + date."""
        old = (
            datetime.now() - timedelta(minutes=minutes)
        ).isoformat(timespec="seconds")
        with sqlite3.connect(db.DB_FILE) as conn:
            conn.execute(
                "UPDATE events SET timestamp = ? WHERE id = ?",
                (old, event_id),
            )

    def test_exact_duplicate_headline_and_date_collapses_to_one(self):
        """Two saves with identical headline + event_date → one analog row."""
        a = _save_analog(
            headline="Trump threatens Iran over Hormuz Strait",
            event_date="2025-09-01",
        )
        self._backdate(a, minutes=20)
        _save_analog(
            headline="Trump threatens Iran over Hormuz Strait",
            event_date="2025-09-01",
        )

        analogs = db.find_historical_analogs(
            headline="Trump warns Iran on oil shipping",
            mechanism="Tankers diverted from Hormuz strait, oil prices jump.",
            stage="realized", persistence="structural",
            limit=3,
        )
        headlines = [a["headline"] for a in analogs]
        self.assertEqual(
            len(headlines), len(set((h, a["event_date"]) for h, a in zip(headlines, analogs))),
            f"duplicate headline+date in top-3: {headlines}",
        )

    def test_near_duplicate_rewording_collapses(self):
        """Same content words in a different order on the same date → one row."""
        a = _save_analog(
            headline="Trump threatens Iran over Hormuz strait",
            event_date="2025-09-02",
        )
        self._backdate(a, minutes=20)
        _save_analog(
            headline="Hormuz strait — Trump threatens Iran",
            event_date="2025-09-02",
        )

        analogs = db.find_historical_analogs(
            headline="Iran Hormuz tensions escalate",
            mechanism="Oil shipping at risk through the Hormuz strait.",
            stage="realized", persistence="structural",
            limit=3,
        )
        # Both candidates share content-word set → must collapse to one
        story_keys = {
            (frozenset(db._headline_words(a["headline"])), a["event_date"])
            for a in analogs
        }
        self.assertEqual(len(story_keys), len(analogs))

    def test_distinct_analogs_still_rank_correctly(self):
        """Three distinct stories must all surface, in expected order."""
        # Higher topic similarity → ranks first.
        a1 = _save_analog(
            headline="Trump threatens Iran over Hormuz strait",
            event_date="2025-09-01",
        )
        self._backdate(a1, minutes=30)
        a2 = _save_analog(
            headline="OPEC cuts production by two million barrels",
            event_date="2025-09-02",
        )
        self._backdate(a2, minutes=20)
        _save_analog(
            headline="Russia gas pipeline halted by sanctions",
            event_date="2025-09-03",
        )

        analogs = db.find_historical_analogs(
            headline="Trump threatens Iran over Hormuz oil shipping",
            mechanism="Iran threatens to close Hormuz strait, oil prices spike.",
            stage="realized", persistence="structural",
            limit=3,
        )
        self.assertEqual(len(analogs), 3)
        # Hormuz analog scores highest → first.
        self.assertIn("Hormuz", analogs[0]["headline"])
        # All three are distinct stories.
        self.assertEqual(
            len({a["headline"] for a in analogs}), 3,
        )

    def test_dedup_preserves_best_representative(self):
        """When two duplicates have different similarity, the higher-
        scoring one survives the dedup pass."""
        # Lower similarity (less mechanism overlap) saved first
        a1 = _save_analog(
            headline="Trump threatens Iran over Hormuz strait",
            event_date="2025-09-01",
        )
        self._backdate(a1, minutes=30)
        # Same headline + date but the SECOND save has the same
        # mechanism so similarity is identical; the dedup must keep
        # the first occurrence (highest in the sort order).
        _save_analog(
            headline="Trump threatens Iran over Hormuz strait",
            event_date="2025-09-01",
        )

        analogs = db.find_historical_analogs(
            headline="Iran Hormuz oil shipping",
            mechanism="Hormuz strait closure threatens crude shipping.",
            stage="realized", persistence="structural",
            limit=3,
        )
        # Exactly one Hormuz row in the result.
        hormuz = [a for a in analogs if "Hormuz" in a["headline"]]
        self.assertEqual(len(hormuz), 1)

    def test_empty_event_date_does_not_collapse_unrelated_stories(self):
        """Two unrelated stories with NULL event_date must NOT dedupe."""
        a = _save_analog(
            headline="Trump threatens Iran over Hormuz strait",
            event_date="",
        )
        self._backdate(a, minutes=30)
        _save_analog(
            headline="OPEC cuts production by two million barrels",
            event_date="",
        )

        analogs = db.find_historical_analogs(
            headline="Iran Hormuz oil OPEC supply shock",
            mechanism="Oil supply disruption from Iran or OPEC cut.",
            stage="realized", persistence="structural",
            limit=3,
        )
        # Both should appear — distinct content words
        headlines = {a["headline"] for a in analogs}
        self.assertGreaterEqual(len(headlines), 2)


# ---------------------------------------------------------------------------
# Cluster 2 — Per-ticker validation card binding
# ---------------------------------------------------------------------------


def _make_series(closes: list[float]):
    """Build a DataFrame with a fresh weekday index ending today."""
    import pandas as pd
    end = pd.Timestamp.today().normalize()
    idx = pd.bdate_range(end=end, periods=len(closes))
    return pd.DataFrame(
        {"Close": closes, "Volume": [1_000_000.0] * len(closes)},
        index=idx,
    )


def _series(start: float, daily_pct: float, n: int = 22) -> list[float]:
    """Geometric series so each ticker has a distinct % return."""
    out = [start]
    for _ in range(n - 1):
        out.append(round(out[-1] * (1 + daily_pct), 4))
    return out


# Each ticker has a different daily growth rate so 5d / 20d returns
# differ across cards.  XLE (benchmark) is intentionally tame.
_TICKER_SERIES = {
    "XOM": _series(100.0, +0.012),
    "CVX": _series(200.0, -0.004),
    "FRO": _series(50.0,  +0.008),
    "DAL": _series(40.0,  -0.010),
    "UAL": _series(30.0,  -0.015),
    "XLE": _series(80.0,  +0.001),
}


def _stub_fetch(ticker: str):
    """Direct replacement for ``market_check._fetch`` — bypasses the
    price cache so synthetic series land in ``_check_one_ticker``
    regardless of the current date."""
    sym = ticker.upper()
    series = _TICKER_SERIES.get(sym)
    if series is None:
        return None
    return _make_series(series)


class TestPerTickerValidationBinding(unittest.TestCase):
    """Each ticker emitted by market_check must carry its OWN spark,
    return numbers, and direction tag — no shared references."""

    def setUp(self):
        # Patch market_check._fetch directly so synthetic series land
        # straight in _check_one_ticker (bypasses the price-cache /
        # date-window resolution).
        self._fetch_patch = patch.object(market_check, "_fetch", side_effect=_stub_fetch)
        self._fetch_patch.start()
        market_check._cache_clear()

    def tearDown(self):
        self._fetch_patch.stop()
        market_check._cache_clear()

    def test_each_ticker_has_distinct_spark_object(self):
        """No two emitted ticker dicts share the same spark list reference."""
        result = market_check.market_check(
            ["XOM", "CVX", "FRO"],
            ["DAL", "UAL"],
            event_date=None,
        )
        tickers = result["tickers"]
        self.assertEqual(
            len(tickers), 5,
            f"expected 5 tickers, got {[t['symbol'] for t in tickers]}",
        )
        spark_ids = [id(t["spark"]) for t in tickers]
        self.assertEqual(
            len(set(spark_ids)), len(spark_ids),
            "two ticker dicts share the same spark list reference",
        )

    def test_mutating_one_spark_does_not_leak_into_other_tickers(self):
        """Defensive fresh-copy: mutate one spark, others stay intact."""
        result = market_check.market_check(
            ["XOM", "CVX"], ["DAL"], event_date=None,
        )
        tickers = result["tickers"]
        original_sparks = {t["symbol"]: list(t["spark"]) for t in tickers}
        # Mutate the first ticker's spark — fresh copies mean others
        # are immune.
        tickers[0]["spark"].append(0.999)
        for t in tickers[1:]:
            self.assertEqual(t["spark"], original_sparks[t["symbol"]])

    def test_mixed_winner_loser_pending_have_distinct_returns(self):
        """Distinct symbols → distinct numeric return windows + labels."""
        result = market_check.market_check(
            ["XOM", "CVX", "FRO"],
            ["DAL", "UAL"],
            event_date=None,
        )
        tickers = result["tickers"]
        # All return_5d values should be different (distinct synthetic series).
        r5_values = [t["return_5d"] for t in tickers]
        self.assertEqual(len(set(r5_values)), len(r5_values),
                         f"return_5d not distinct across cards: {r5_values}")
        # All spark values should be different.
        sparks = [tuple(t["spark"]) for t in tickers]
        self.assertEqual(len(set(sparks)), len(sparks),
                         "two tickers ended up with identical spark series")
        # Symbols are distinct.
        symbols = [t["symbol"] for t in tickers]
        self.assertEqual(len(set(symbols)), len(symbols))

    def test_pending_card_does_not_inherit_other_ticker_data(self):
        """A symbol the provider can't fetch must come back as a
        pending card with no return data — and never inherit values
        from a previously-fetched ticker."""
        result = market_check.market_check(
            ["XOM", "ZZZZZZ"],   # XOM ok, ZZZZZZ unknown to stub
            [], event_date=None,
        )
        tickers = {t["symbol"]: t for t in result["tickers"]}
        self.assertIn("XOM", tickers)
        self.assertIn("ZZZZZZ", tickers)
        pending = tickers["ZZZZZZ"]
        # Pending card has no leaked numbers
        self.assertEqual(pending["label"], "needs more evidence")
        self.assertIsNone(pending["return_5d"])
        self.assertIsNone(pending["return_20d"])
        self.assertEqual(pending["spark"], [])
        # And the live XOM card was not contaminated either
        self.assertEqual(tickers["XOM"]["label"] != "needs more evidence", True)
        self.assertIsNotNone(tickers["XOM"]["return_5d"])

    def test_market_check_dedupes_overlapping_ticker_lists(self):
        """If a symbol appears in both beneficiary and loser lists,
        the result still emits exactly one card for it."""
        result = market_check.market_check(
            ["XOM", "CVX"],
            ["XOM"],   # XOM in BOTH lists
            event_date=None,
        )
        symbols = [t["symbol"] for t in result["tickers"]]
        self.assertEqual(len(symbols), len(set(symbols)),
                         f"duplicate symbol in tickers: {symbols}")


class TestProviderConcurrencySerialization(unittest.TestCase):
    """Regression for the production bug where concurrent yf.download
    calls from market_check's ThreadPoolExecutor cross-contaminated
    the SQLite price cache (XOM and CVX persisted with identical
    closes).  YFinanceProvider.fetch_daily must serialise the
    underlying provider call so concurrent worker threads can never
    see another ticker's DataFrame.
    """

    def test_provider_lock_serializes_concurrent_fetch_daily(self):
        """Two threads calling fetch_daily concurrently must observe
        the lock — one waits while the other holds it."""
        from market_data import YFinanceProvider, _PROVIDER_FETCH_LOCK

        # Sanity: lock exists and is the right type.
        import threading as _t
        self.assertIsInstance(
            _PROVIDER_FETCH_LOCK, type(_t.Lock()),
            "_PROVIDER_FETCH_LOCK must be a threading.Lock instance",
        )

        # Patch yf.download with a stub that records the in-flight
        # call count.  If the lock is missing, both threads see
        # in_flight == 2 mid-call; with the lock, max is 1.
        in_flight = {"current": 0, "max": 0}
        in_flight_lock = _t.Lock()
        release = _t.Event()
        import pandas as pd
        import sys as _sys

        def _fake_yf_download(ticker, **kwargs):
            with in_flight_lock:
                in_flight["current"] += 1
                in_flight["max"] = max(in_flight["max"], in_flight["current"])
            release.wait(timeout=0.5)
            with in_flight_lock:
                in_flight["current"] -= 1
            idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=10)
            return pd.DataFrame(
                {"Close": [float(i) for i in range(10)],
                 "Volume": [1_000_000.0] * 10},
                index=idx,
            )

        fake_yf = type("FakeYF", (), {"download": staticmethod(_fake_yf_download)})()

        # Install the fake yfinance module BEFORE the threads start so
        # there's no per-worker patch.dict race when restoring sys.modules.
        original = _sys.modules.get("yfinance")
        _sys.modules["yfinance"] = fake_yf
        try:
            provider = YFinanceProvider()
            results: list = []

            def _worker(sym: str) -> None:
                df = provider.fetch_daily(sym, period="3mo")
                results.append((sym, df is not None))

            t1 = _t.Thread(target=_worker, args=("XOM",))
            t2 = _t.Thread(target=_worker, args=("CVX",))
            t1.start()
            t2.start()
            release.set()
            t1.join(timeout=5)
            t2.join(timeout=5)
        finally:
            if original is not None:
                _sys.modules["yfinance"] = original
            else:
                _sys.modules.pop("yfinance", None)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(ok for _, ok in results))
        self.assertEqual(
            in_flight["max"], 1,
            "yfinance was called concurrently — provider lock missing",
        )

    def test_macro_snapshot_doc_invariant(self):
        """The macro_snapshot serialization comment must still call
        out the yfinance thread-safety hazard.  Acts as a doc-rot
        guard so a future refactor doesn't drop the warning that
        explains why the lock exists in the first place.
        """
        with open(os.path.join(os.path.dirname(__file__), "..", "market_check.py"),
                  encoding="utf-8") as f:
            src = f.read()
        self.assertIn("yfinance is not thread-safe", src)


class TestMergeFollowupBindingHardening(unittest.TestCase):
    """The freshness-merge boundary (cached-response path) also has to
    return distinct dicts with distinct spark lists."""

    def test_merge_dedupes_stored_by_symbol(self):
        stored = [
            {"symbol": "XOM", "role": "beneficiary",
             "return_5d": 1.0, "spark": [0.1, 0.2, 0.3]},
            {"symbol": "XOM", "role": "beneficiary",   # duplicate row
             "return_5d": 1.0, "spark": [0.1, 0.2, 0.3]},
            {"symbol": "DAL", "role": "loser",
             "return_5d": -1.5, "spark": [0.4, 0.3, 0.2]},
        ]
        merged = mcf._merge_followup_into_stored(stored, [])
        self.assertEqual([t["symbol"] for t in merged], ["XOM", "DAL"])

    def test_merge_emits_fresh_spark_lists(self):
        spark_ref = [0.1, 0.2, 0.3]
        stored = [
            {"symbol": "XOM", "role": "beneficiary",
             "return_5d": 1.0, "spark": spark_ref},
            {"symbol": "DAL", "role": "loser",
             "return_5d": -1.5, "spark": [0.4, 0.3, 0.2]},
        ]
        merged = mcf._merge_followup_into_stored(stored, [])
        # The merged XOM spark must NOT be the same list reference as
        # the input — mutating one should not affect the other.
        self.assertIsNot(merged[0]["spark"], spark_ref)
        merged[0]["spark"].append(0.999)
        self.assertEqual(spark_ref, [0.1, 0.2, 0.3])


if __name__ == "__main__":
    unittest.main()
