"""
tests/test_market_overview_preview_scaling.py

Pin down the Market Overview preview-value scaling contract.

Three things this file proves:

  1. **Sanity bounds at the compute boundary** —
     ``market_check._sanitize_returns`` drops absurd return values
     (like the +1348.50% XLE bug from corrupt price_cache stub bars)
     to None instead of propagating them into ``market_tickers``.

  2. **Sanity scrub at the emission boundary** —
     ``market_check._scrub_implausible_ticker_returns`` clears those
     same absurd values from PERSISTED ticker dicts so legacy events
     saved before the compute fix existed don't keep displaying
     +1348% on movers cards.  When r5 is scrubbed the derived
     ``direction_tag`` is also cleared.

  3. **Mover endpoint payloads stay sane** — /market-movers,
     /movers/today, /movers/persistent never surface a return value
     above the sanity ceiling, even when the underlying persisted
     event row carries a corrupt one.

  4. **Frontend cards no longer import Sparkline** — the
     ``market-overview.tsx`` source must not reference the
     ``Sparkline`` component, since the preview chips were
     intentionally simplified to symbol + return only.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import api
import market_check
import movers_cache


# ---------------------------------------------------------------------------
# Cluster A — _sanitize_returns at the compute boundary
# ---------------------------------------------------------------------------


class TestSanitizeReturns(unittest.TestCase):
    """The pure helper that drops implausibly large returns to None."""

    def test_xle_1348_bug_dropped(self):
        """The exact production-bug values are dropped."""
        r1, r5, r20 = market_check._sanitize_returns(624.25, 1348.5, 2.35)
        self.assertIsNone(r1)
        self.assertIsNone(r5)
        # r20 is well inside the cap → preserved.
        self.assertEqual(r20, 2.35)

    def test_plausible_returns_pass_through(self):
        """Normal market data is unchanged."""
        cases = [
            (0.5, 2.0, 6.0),
            (-1.5, -4.5, -8.0),
            (None, 5.0, None),
            (None, None, None),
        ]
        for inp in cases:
            self.assertEqual(market_check._sanitize_returns(*inp), inp)

    def test_each_window_capped_independently(self):
        """A corrupt single-bar fetch can blow out r1 without nuking
        a still-valid r20 (or vice versa)."""
        r1, r5, r20 = market_check._sanitize_returns(150.0, 5.0, 4.0)
        self.assertIsNone(r1)   # > 100% cap
        self.assertEqual(r5, 5.0)
        self.assertEqual(r20, 4.0)

        r1, r5, r20 = market_check._sanitize_returns(2.0, 5.0, 600.0)
        self.assertEqual(r1, 2.0)
        self.assertEqual(r5, 5.0)
        self.assertIsNone(r20)  # > 500% cap

    def test_negative_absurd_values_also_dropped(self):
        r1, r5, r20 = market_check._sanitize_returns(-150.0, -250.0, -600.0)
        self.assertIsNone(r1)
        self.assertIsNone(r5)
        self.assertIsNone(r20)

    def test_caps_at_exact_threshold(self):
        """Values right at the ceiling are kept; just over → dropped."""
        r1, _, _ = market_check._sanitize_returns(100.0, None, None)
        self.assertEqual(r1, 100.0)
        r1, _, _ = market_check._sanitize_returns(100.01, None, None)
        self.assertIsNone(r1)


# ---------------------------------------------------------------------------
# Cluster B — _scrub_implausible_ticker_returns at the emission boundary
# ---------------------------------------------------------------------------


class TestScrubImplausibleTickerReturns(unittest.TestCase):
    """Persisted ticker dicts get their absurd return fields nuked."""

    def test_xle_1348_row_scrubbed_to_pending_returns(self):
        """The exact corrupted XLE row from event 64 in the live DB."""
        tickers = [
            {"symbol": "XLE", "role": "beneficiary",
             "return_1d": 624.25, "return_5d": 1348.5, "return_20d": 2.35,
             "direction_tag": "supports \u2191",
             "spark": [0.94, 0.95, 0.96]},
            {"symbol": "XOM", "role": "beneficiary",
             "return_1d": -5.28, "return_5d": -8.49, "return_20d": 4.81,
             "direction_tag": "contradicts \u2191",
             "spark": [0.0, 0.1, 0.2]},
        ]
        out = market_check._scrub_implausible_ticker_returns(tickers)
        # XLE: r1 + r5 nuked, r20 preserved
        xle = out[0]
        self.assertIsNone(xle["return_1d"])
        self.assertIsNone(xle["return_5d"])
        self.assertEqual(xle["return_20d"], 2.35)
        # And the direction_tag derived from the now-suspect r5 is cleared
        self.assertIsNone(xle["direction_tag"])
        # Spark passes through (it's normalized 0..1 — not a return)
        self.assertEqual(xle["spark"], [0.94, 0.95, 0.96])

        # XOM (sane values) untouched
        xom = out[1]
        self.assertEqual(xom["return_1d"], -5.28)
        self.assertEqual(xom["return_5d"], -8.49)
        self.assertEqual(xom["return_20d"], 4.81)
        self.assertEqual(xom["direction_tag"], "contradicts \u2191")

    def test_returns_fresh_copies(self):
        """Mutating the output must not affect the input."""
        tickers = [
            {"symbol": "AAA", "return_1d": 5.0, "return_5d": 10.0,
             "return_20d": 15.0, "direction_tag": "supports up"},
        ]
        out = market_check._scrub_implausible_ticker_returns(tickers)
        out[0]["return_5d"] = 999.0
        self.assertEqual(tickers[0]["return_5d"], 10.0)

    def test_preserves_direction_tag_when_r5_passes(self):
        """If r5 is plausible, direction_tag is preserved even when
        r1 / r20 are scrubbed."""
        tickers = [
            {"symbol": "AAA", "return_1d": 200.0, "return_5d": 5.0,
             "return_20d": 700.0, "direction_tag": "supports up"},
        ]
        out = market_check._scrub_implausible_ticker_returns(tickers)
        self.assertIsNone(out[0]["return_1d"])
        self.assertEqual(out[0]["return_5d"], 5.0)
        self.assertIsNone(out[0]["return_20d"])
        self.assertEqual(out[0]["direction_tag"], "supports up")

    def test_empty_input_returns_empty(self):
        self.assertEqual(market_check._scrub_implausible_ticker_returns([]), [])

    def test_missing_return_fields_handled(self):
        """Tickers without return fields don't crash the scrub."""
        tickers = [
            {"symbol": "XYZ", "role": "beneficiary", "spark": []},
        ]
        out = market_check._scrub_implausible_ticker_returns(tickers)
        self.assertEqual(len(out), 1)
        self.assertIsNone(out[0].get("return_5d"))


# ---------------------------------------------------------------------------
# Cluster C — mover endpoints never surface absurd persisted values
# ---------------------------------------------------------------------------


class TestMoverEndpointsRejectAbsurdReturns(unittest.TestCase):
    """End-to-end: a corrupted event in the DB must not surface a
    +1348% chip on /market-movers, /movers/persistent, or /movers/today."""

    @classmethod
    def setUpClass(cls):
        os.environ["ANTHROPIC_API_KEY"] = ""
        from fastapi.testclient import TestClient
        cls.client = TestClient(api.app)

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_preview_scale_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        movers_cache.invalidate()
        api._news_cache["data"] = None
        api._news_cache["ts"] = 0.0
        api._TODAYS_MOVERS_CACHE["data"] = None
        api._TODAYS_MOVERS_CACHE["ts"] = 0.0

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def _seed_corrupt_xle_event(self, *, headline: str, days_old: int = 8) -> None:
        """Save an event whose XLE row has the +1348% bug shape."""
        ts = (datetime.now() - timedelta(days=days_old)).isoformat(timespec="seconds")
        event_date = (datetime.now() - timedelta(days=days_old)).strftime("%Y-%m-%d")
        db.save_event({
            "headline": headline,
            "stage": "realized",
            "persistence": "structural",
            "event_date": event_date,
            "timestamp": ts,
            "what_changed": "ctx",
            "mechanism_summary": "Energy supply shock test",
            "market_tickers": [
                # Corrupted XLE row — exact production bug shape
                {"symbol": "XLE", "role": "beneficiary",
                 "return_1d": 624.25, "return_5d": 1348.5, "return_20d": 2.35,
                 "direction_tag": "supports \u2191",
                 "label": "notable move", "volume_ratio": 1.5,
                 "spark": [0.939, 0.942, 0.945, 0.955, 0.954],
                 "anchor_date": event_date},
                # Sane companion ticker
                {"symbol": "XOM", "role": "beneficiary",
                 "return_1d": -5.28, "return_5d": -8.49, "return_20d": 4.81,
                 "direction_tag": "contradicts \u2191",
                 "label": "in motion", "volume_ratio": 1.2,
                 "spark": [0.0, 0.098, 0.228, 0.284, 0.363],
                 "anchor_date": event_date},
                # Another sane ticker
                {"symbol": "DAL", "role": "loser",
                 "return_1d": 6.06, "return_5d": 6.75, "return_20d": 3.2,
                 "direction_tag": "contradicts \u2193",
                 "label": "in motion", "volume_ratio": 1.1,
                 "spark": [0.4, 0.5, 0.6, 0.7, 0.8],
                 "anchor_date": event_date},
            ],
        })

    _SANITY_R1 = market_check._RETURN_SANITY_R1_PCT
    _SANITY_R5 = market_check._RETURN_SANITY_R5_PCT
    _SANITY_R20 = market_check._RETURN_SANITY_R20_PCT

    def _assert_no_absurd_returns(self, body: list[dict]) -> None:
        for mover in body:
            for t in mover.get("tickers", []):
                r1 = t.get("return_1d")
                r5 = t.get("return_5d")
                r20 = t.get("return_20d")
                if r1 is not None:
                    self.assertLessEqual(
                        abs(r1), self._SANITY_R1,
                        f"absurd r1 leaked: {mover['headline']} {t['symbol']} r1={r1}",
                    )
                if r5 is not None:
                    self.assertLessEqual(
                        abs(r5), self._SANITY_R5,
                        f"absurd r5 leaked: {mover['headline']} {t['symbol']} r5={r5}",
                    )
                if r20 is not None:
                    self.assertLessEqual(
                        abs(r20), self._SANITY_R20,
                        f"absurd r20 leaked: {mover['headline']} {t['symbol']} r20={r20}",
                    )

    def test_market_movers_drops_xle_1348(self):
        self._seed_corrupt_xle_event(headline="OPEC corrupt XLE event")
        body = self.client.get("/market-movers").json()
        self.assertEqual(self.client.get("/market-movers").status_code, 200)
        self._assert_no_absurd_returns(body)

        # The corrupt XLE row should be scrubbed away — XOM (the
        # sane companion that exceeds the 1.5% threshold) should be
        # what carries the card.
        for mover in body:
            if mover["headline"] == "OPEC corrupt XLE event":
                xle_row = next(
                    (t for t in mover["tickers"] if t["symbol"] == "XLE"),
                    None,
                )
                if xle_row is not None:
                    # XLE may still appear (because it has a sane r20)
                    # but its r1 and r5 must be cleared.
                    self.assertIsNone(xle_row["return_5d"])

    def test_movers_persistent_drops_xle_1348(self):
        self._seed_corrupt_xle_event(headline="Persistent corrupt XLE event")
        body = self.client.get("/movers/persistent").json()
        self._assert_no_absurd_returns(body)

    def test_movers_today_drops_xle_1348(self):
        # Recent event so it lands in /movers/today's 24h window.
        self._seed_corrupt_xle_event(headline="Today corrupt XLE event", days_old=0)
        body = self.client.get("/movers/today").json()
        self._assert_no_absurd_returns(body)

    def test_movers_weekly_drops_xle_1348(self):
        self._seed_corrupt_xle_event(headline="Weekly corrupt XLE event", days_old=2)
        body = self.client.get("/movers/weekly").json()
        self._assert_no_absurd_returns(body)

    def test_sane_companion_tickers_pass_through(self):
        """The sane XOM/DAL rows on the corrupted event must still
        flow through with their original values intact."""
        self._seed_corrupt_xle_event(headline="Sane companion test event")
        body = self.client.get("/movers/persistent").json()
        for mover in body:
            if mover["headline"] != "Sane companion test event":
                continue
            xom_row = next((t for t in mover["tickers"] if t["symbol"] == "XOM"), None)
            if xom_row is not None:
                self.assertEqual(xom_row["return_5d"], -8.49)
            dal_row = next((t for t in mover["tickers"] if t["symbol"] == "DAL"), None)
            if dal_row is not None:
                self.assertEqual(dal_row["return_5d"], 6.75)


# ---------------------------------------------------------------------------
# Cluster D — frontend cards no longer render sparklines
# ---------------------------------------------------------------------------


class TestMarketOverviewFrontendNoSparkline(unittest.TestCase):
    """The market-overview source must not import or render Sparkline."""

    def test_no_sparkline_import_in_market_overview(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "frontend", "src",
            "components", "pages", "market-overview.tsx",
        )
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        # Strict: no import statement, no JSX usage.
        self.assertNotIn(
            "from \"@/components/ui/sparkline\"", src,
            "market-overview.tsx must not import Sparkline anymore",
        )
        self.assertNotIn(
            "<Sparkline", src,
            "market-overview.tsx must not render <Sparkline /> anywhere",
        )

    def test_persistent_card_still_renders_symbol_and_return(self):
        """The cleanup removed the chart but kept symbol + value chips."""
        path = os.path.join(
            os.path.dirname(__file__), "..", "frontend", "src",
            "components", "pages", "market-overview.tsx",
        )
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        # Symbol render
        self.assertIn("{t.symbol}", src)
        # Return value render via the pct() helper
        self.assertIn("{pct(t.return_5d)}", src)
        # Anchor / as-of footer still present
        self.assertIn("Anchor", src)
        self.assertIn("As of", src)


if __name__ == "__main__":
    unittest.main()
