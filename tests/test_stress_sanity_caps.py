"""
Tests for stress regime signal calculations with known inputs.

Covers:
- Credit/breadth/haven numeric correctness with clean data
- Corrupt cache purge prevents absurd values
- Explanation text uses human-readable units (no thousands)
- Secondary signals feed regime classifier (Calm with Undercurrent)
- Insufficient-evidence events excluded from weekly and market-context
- Persistent movers untouched by junk filter
"""

import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_df(prices, length=None):
    if length is None:
        length = len(prices)
    dates = pd.date_range("2026-01-01", periods=length, freq="B")
    return pd.DataFrame({
        "Close": prices[:length],
        "Volume": [1e6] * length,
    }, index=dates)


# Default plausible series for tickers that aren't the subject of each test.
_DEFAULT_PRICES = {
    "^VIX":    [18.0] * 25,
    "^VIX3M":  [20.0] * 25,
    "HYG":     [75.0] * 25,
    "SHY":     [82.0] * 25,
    "GLD":     [230.0] * 25,
    "DX-Y.NYB": [104.0] * 25,
    "TLT":     [92.0] * 25,
    "RSP":     [170.0] * 25,
    "SPY":     [530.0] * 25,
}


def _default_side(overrides: dict):
    """Build a mock _fetch side-effect with per-symbol overrides."""
    def _side(sym, *a, **kw):
        if sym in overrides:
            return _make_df(overrides[sym])
        if sym in _DEFAULT_PRICES:
            return _make_df(_DEFAULT_PRICES[sym])
        return _make_df([100.0] * 25)
    return _side


# ---------------------------------------------------------------------------
# Credit spread: input-level validation
# ---------------------------------------------------------------------------

class TestCreditSpread(unittest.TestCase):

    @patch("market_check._fetch")
    def test_credit_values_human_readable(self, mock_fetch):
        """With clean data, credit_spread_5d must be in single-digit pp range."""
        mock_fetch.side_effect = _default_side({
            "HYG": [75.0] * 19 + [75.0, 74.8, 74.7, 74.5, 74.3, 74.25],
            "SHY": [82.0] * 19 + [82.0, 82.02, 82.04, 82.06, 82.08, 82.1],
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()
        spread = result["raw"]["credit_spread_5d"]
        self.assertIsNotNone(spread)
        # Human-readable: small single-digit number, not hundreds/thousands
        self.assertLess(abs(spread), 10.0, f"Spread {spread} is too large for clean data")

    @patch("market_check._fetch")
    def test_normal_credit_spread_exact(self, mock_fetch):
        """HYG $75→$74.77 (−0.307%), SHY $82→$82.08 (+0.098%) → spread ≈ 0.40."""
        mock_fetch.side_effect = _default_side({
            "HYG": [75.0] * 19 + [75.0, 74.9, 74.85, 74.8, 74.78, 74.77],
            "SHY": [82.0] * 19 + [82.0, 82.02, 82.04, 82.06, 82.08, 82.08],
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        spread = result["raw"]["credit_spread_5d"]
        self.assertIsNotNone(spread)
        # shy_5d = (82.08 - 82.0) / 82.0 * 100 = 0.0976
        # hyg_5d = (74.77 - 75.0) / 75.0 * 100 = -0.3067
        # spread = 0.0976 - (-0.3067) = 0.4042
        self.assertAlmostEqual(spread, 0.40, delta=0.05)
        self.assertFalse(result["signals"]["credit_widening"])

    @patch("market_check._fetch")
    def test_credit_widening_fires(self, mock_fetch):
        """HYG down 1%, SHY flat → spread > 0.5 → credit_widening signal."""
        mock_fetch.side_effect = _default_side({
            "HYG": [75.0] * 19 + [75.0, 74.7, 74.5, 74.3, 74.1, 74.0],
            "SHY": [82.0] * 25,
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        spread = result["raw"]["credit_spread_5d"]
        # hyg_5d = (74.0 - 75.0)/75.0*100 = -1.333
        # shy_5d = 0.0
        # spread = 0 - (-1.333) = 1.333
        self.assertGreater(spread, 0.5)
        self.assertTrue(result["signals"]["credit_widening"])
        self.assertIn("credit stress rising", result["detail"]["credit"]["explanation"])


# ---------------------------------------------------------------------------
# Breadth gap: input-level validation
# ---------------------------------------------------------------------------

class TestBreadthGap(unittest.TestCase):

    @patch("market_check._fetch")
    def test_breadth_values_human_readable(self, mock_fetch):
        """With clean data, breadth_gap_5d must be in small pp range."""
        mock_fetch.side_effect = _default_side({
            "RSP": [170.0] * 19 + [170.0, 169.5, 169.0, 168.5, 168.0, 167.8],
            "SPY": [530.0] * 25,
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()
        gap = result["raw"]["breadth_gap_5d"]
        self.assertIsNotNone(gap)
        self.assertLess(abs(gap), 10.0, f"Gap {gap} is too large for clean data")

    @patch("market_check._fetch")
    def test_normal_breadth_gap_exact(self, mock_fetch):
        """RSP −0.29%, SPY flat → gap ≈ −0.29."""
        mock_fetch.side_effect = _default_side({
            "RSP": [170.0] * 19 + [170.0, 169.9, 169.8, 169.7, 169.6, 169.5],
            "SPY": [530.0] * 25,
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        gap = result["raw"]["breadth_gap_5d"]
        # rsp_5d = (169.5 - 170.0)/170.0*100 = -0.294
        # spy_5d = 0
        # gap = -0.294
        self.assertAlmostEqual(gap, -0.29, delta=0.02)
        self.assertFalse(result["signals"]["breadth_deterioration"])

    @patch("market_check._fetch")
    def test_breadth_deterioration_fires(self, mock_fetch):
        """RSP down 2%, SPY flat → gap < -1.5 → signal fires (threshold raised from -0.5)."""
        mock_fetch.side_effect = _default_side({
            "RSP": [170.0] * 19 + [170.0, 169.0, 168.0, 167.0, 166.4, 166.6],
            "SPY": [530.0] * 25,
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        gap = result["raw"]["breadth_gap_5d"]
        # rsp_5d = (166.6 - 170.0)/170.0*100 = -2.0
        self.assertLess(gap, -1.5)
        self.assertTrue(result["signals"]["breadth_deterioration"])
        self.assertIn("narrow leadership", result["detail"]["breadth"]["explanation"])


# ---------------------------------------------------------------------------
# Safe haven flows: input-level validation
# ---------------------------------------------------------------------------

class TestSafeHavenFlows(unittest.TestCase):

    @patch("market_check._fetch")
    def test_haven_values_human_readable(self, mock_fetch):
        """With clean data, individual haven returns must be small percentages."""
        mock_fetch.side_effect = _default_side({
            "GLD": [230.0] * 19 + [230.0, 230.5, 231.0, 231.5, 232.0, 232.5],
            "DX-Y.NYB": [104.0] * 19 + [104.0, 104.05, 104.1, 104.15, 104.2, 104.2],
            "TLT": [92.0] * 19 + [92.0, 92.1, 92.2, 92.3, 92.4, 92.5],
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()
        assets = result["detail"]["safe_haven"]["assets"]
        for name, val in assets.items():
            self.assertIsNotNone(val, f"{name} should have a value")
            self.assertLess(abs(val), 20.0,
                            f"{name} return {val}% is too large for clean data")

    @patch("market_check._fetch")
    def test_normal_haven_returns_exact(self, mock_fetch):
        """Gold up 3.5%, Dollar up 0.5%, Bonds up 1.5% → avg ~1.83, signal fires (threshold 1.5)."""
        mock_fetch.side_effect = _default_side({
            "GLD":     [230.0] * 19 + [230.0, 231.5, 233.0, 235.0, 237.0, 238.05],
            "DX-Y.NYB": [104.0] * 19 + [104.0, 104.1, 104.2, 104.3, 104.4, 104.52],
            "TLT":     [92.0] * 19 + [92.0, 92.3, 92.5, 92.8, 93.1, 93.38],
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        assets = result["detail"]["safe_haven"]["assets"]
        # Gold: (238.05 - 230)/230*100 = 3.50
        self.assertAlmostEqual(assets["Gold"], 3.5, delta=0.15)
        # Dollar: (104.52 - 104)/104*100 = 0.50
        self.assertAlmostEqual(assets["Dollar"], 0.5, delta=0.1)
        # Bonds: (93.38 - 92)/92*100 = 1.50
        self.assertAlmostEqual(assets["Long Bonds"], 1.5, delta=0.1)
        # avg_haven = (3.5 + 0.5 + 1.5) / 3 = 1.83
        self.assertGreater(result["raw"]["haven_avg_5d"], 1.5)
        self.assertTrue(result["signals"]["safe_haven_bid"])

    @patch("market_check._fetch")
    def test_haven_calm_when_flat(self, mock_fetch):
        """All havens flat → no safe-haven bid."""
        mock_fetch.side_effect = _default_side({})
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        self.assertFalse(result["signals"]["safe_haven_bid"])


# ---------------------------------------------------------------------------
# Explanation text readability
# ---------------------------------------------------------------------------

class TestExplanationText(unittest.TestCase):

    @patch("market_check._fetch")
    def test_credit_explanation_readable(self, mock_fetch):
        """Credit explanation should use reasonable numbers, not thousands."""
        mock_fetch.side_effect = _default_side({
            "HYG": [75.0] * 19 + [75.0, 74.8, 74.6, 74.4, 74.2, 74.0],
            "SHY": [82.0] * 19 + [82.0, 82.1, 82.2, 82.3, 82.4, 82.5],
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        expl = result["detail"]["credit"]["explanation"]
        import re
        numbers = [float(n) for n in re.findall(r'[\d.]+', expl)]
        for n in numbers:
            self.assertLess(n, 100, f"Explanation contains implausible number {n}: {expl}")

    @patch("market_check._fetch")
    def test_breadth_explanation_readable(self, mock_fetch):
        """Breadth explanation should use small readable numbers."""
        mock_fetch.side_effect = _default_side({
            "RSP": [170.0] * 19 + [170.0, 169.5, 169.0, 168.5, 168.0, 168.3],
            "SPY": [530.0] * 25,
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        expl = result["detail"]["breadth"]["explanation"]
        import re
        numbers = [float(n) for n in re.findall(r'[\d.]+', expl)]
        for n in numbers:
            self.assertLess(n, 100, f"Explanation contains implausible number {n}: {expl}")


# ---------------------------------------------------------------------------
# Regime classifier: secondary signals produce "Calm with Undercurrent"
# ---------------------------------------------------------------------------

class TestRegimeClassification(unittest.TestCase):

    @patch("market_check._fetch")
    def test_haven_bid_plus_breadth_produces_undercurrent(self, mock_fetch):
        """safe_haven_bid + breadth_deterioration → Calm with Undercurrent."""
        mock_fetch.side_effect = _default_side({
            # Haven: Gold up 3.5%, Dollar up 0.5%, Bonds up 1.5% → avg ~1.83 > 1.5
            "GLD":     [230.0] * 19 + [230.0, 231.5, 233.0, 235.0, 237.0, 238.05],
            "DX-Y.NYB": [104.0] * 19 + [104.0, 104.1, 104.2, 104.3, 104.4, 104.52],
            "TLT":     [92.0] * 19 + [92.0, 92.3, 92.5, 92.8, 93.1, 93.38],
            # Breadth: RSP lagging SPY by >1.5pp (RSP -2%, SPY flat)
            "RSP":     [170.0] * 19 + [170.0, 169.0, 168.0, 167.0, 166.4, 166.6],
            "SPY":     [530.0] * 25,
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        self.assertTrue(result["signals"]["safe_haven_bid"])
        self.assertTrue(result["signals"]["breadth_deterioration"])
        self.assertFalse(result["signals"]["vix_elevated"])
        self.assertEqual(result["regime"], "Calm with Undercurrent")
        self.assertIn("secondary", result["summary"].lower())

    @patch("market_check._fetch")
    def test_haven_bid_alone_produces_undercurrent(self, mock_fetch):
        """safe_haven_bid alone → Calm with Undercurrent (avg > 1.5pp threshold)."""
        mock_fetch.side_effect = _default_side({
            "GLD":     [230.0] * 19 + [230.0, 231.5, 233.0, 235.0, 237.0, 238.05],
            "DX-Y.NYB": [104.0] * 19 + [104.0, 104.1, 104.2, 104.3, 104.4, 104.52],
            "TLT":     [92.0] * 19 + [92.0, 92.3, 92.5, 92.8, 93.1, 93.38],
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        self.assertTrue(result["signals"]["safe_haven_bid"])
        self.assertEqual(result["regime"], "Calm with Undercurrent")

    @patch("market_check._fetch")
    def test_all_calm_produces_calm(self, mock_fetch):
        """All flat data → Calm regime."""
        mock_fetch.side_effect = _default_side({})
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        self.assertEqual(result["regime"], "Calm")
        self.assertIn("stable", result["summary"].lower())


# ---------------------------------------------------------------------------
# Market-context highlights: low-signal suppression
# ---------------------------------------------------------------------------

class TestHighlightLowSignalSuppression(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ["ANTHROPIC_API_KEY"] = ""
        # Patch analyze_event + market_check for the full API
        from unittest.mock import patch as _p
        cls._patches = [
            _p("api.analyze_event", return_value={
                "what_changed": "test", "mechanism_summary": "test",
                "beneficiaries": ["A"], "losers": ["B"],
                "beneficiary_tickers": ["AAPL"], "loser_tickers": ["MSFT"],
                "assets_to_watch": [], "confidence": "medium",
                "transmission_chain": [], "if_persists": {}, "currency_channel": {},
            }),
            _p("api.market_check", return_value={
                "note": "", "details": {}, "tickers": [],
            }),
        ]
        for p in cls._patches:
            p.start()
        from fastapi.testclient import TestClient
        import api
        cls.api = api
        cls.client = TestClient(api.app)

    @classmethod
    def tearDownClass(cls):
        for p in cls._patches:
            p.stop()

    def setUp(self):
        import tempfile, uuid, db
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_highlight_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        self.api._news_cache["data"] = None
        self.api._news_cache["ts"] = 0.0
        import api as _api
        _api._last_refresh_at = 0.0
        _api._last_refresh_payload = None
        _api._TODAYS_MOVERS_CACHE["data"] = None
        _api._TODAYS_MOVERS_CACHE["ts"] = 0.0

    def tearDown(self):
        import db
        db.DB_FILE = self._orig_db
        db._db_ready = False
        try:
            os.remove(self._tmp)
        except (PermissionError, OSError):
            pass

    def test_low_signal_event_excluded_from_movers_today(self):
        """Events with low_signal=1 must not appear in movers_today."""
        import db
        from datetime import datetime
        # Save a low-signal event with valid tickers
        ev = {
            "headline": "Ecuador agreement test",
            "stage": "developing", "persistence": "1d",
            "what_changed": "", "mechanism_summary": "Insufficient evidence to identify mechanism.",
            "beneficiaries": [], "losers": [],
            "assets_to_watch": [], "confidence": "low",
            "market_note": "",
            "market_tickers": [
                {"symbol": "AAPL", "role": "beneficiary",
                 "return_5d": 5.0, "return_20d": 8.0,
                 "direction_tag": "supports \u2191", "spark": [],
                 "label": "up", "return_1d": 1.0, "volume_ratio": 1.5, "vs_xle_5d": None},
            ],
            "event_date": datetime.now().strftime("%Y-%m-%d"),
            "notes": "",
            "low_signal": 1,
        }
        db.save_event(ev)

        r = self.client.get("/movers/today")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        items = body["items"] if isinstance(body, dict) else body
        headlines = [m["headline"] for m in items]
        self.assertNotIn("Ecuador agreement test", headlines)


# ---------------------------------------------------------------------------
# Regime signal restoration: secondary signals feed Undercurrent
# ---------------------------------------------------------------------------

class TestRegimeSignalRestoration(unittest.TestCase):
    """Verify that credit, breadth, and haven signals actually fire
    and produce 'Calm with Undercurrent' when the underlying data
    supports it — i.e. _safe_pct does NOT suppress valid data."""

    @patch("market_check._fetch")
    def test_credit_plus_breadth_produces_undercurrent(self, mock_fetch):
        """Credit widening + breadth deterioration (no VIX) → Undercurrent.

        Credit alone doesn't trigger Undercurrent (classifier requires
        haven/breadth or ≥2 non-VIX signals).  Pairing credit with
        breadth meets the ≥2 threshold.
        """
        mock_fetch.side_effect = _default_side({
            # HYG down 1.5%, SHY flat → spread > 0.5
            "HYG": [75.0] * 19 + [75.0, 74.7, 74.4, 74.2, 73.9, 73.88],
            "SHY": [82.0] * 25,
            # Breadth: RSP lagging SPY by >0.5pp
            "RSP": [170.0] * 19 + [170.0, 169.3, 168.7, 168.0, 167.5, 167.3],
            "SPY": [530.0] * 25,
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        self.assertTrue(result["signals"]["credit_widening"],
                        "credit_widening should fire when spread > 0.5")
        self.assertTrue(result["signals"]["breadth_deterioration"])
        self.assertFalse(result["signals"]["vix_elevated"])
        self.assertEqual(result["regime"], "Calm with Undercurrent")
        # credit detail must have a numeric spread, not None
        spread = result["detail"]["credit"].get("spread_5d")
        self.assertIsNotNone(spread)
        self.assertGreater(spread, 0.5)

    @patch("market_check._fetch")
    def test_breadth_alone_produces_undercurrent(self, mock_fetch):
        """Breadth deterioration without VIX → Calm with Undercurrent."""
        mock_fetch.side_effect = _default_side({
            "RSP": [170.0] * 19 + [170.0, 169.3, 168.7, 168.0, 167.5, 167.3],
            "SPY": [530.0] * 25,
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        self.assertTrue(result["signals"]["breadth_deterioration"])
        self.assertFalse(result["signals"]["vix_elevated"])
        self.assertEqual(result["regime"], "Calm with Undercurrent")

    @patch("market_check._fetch")
    def test_all_three_secondary_signals_produce_undercurrent(self, mock_fetch):
        """Credit + breadth + haven all firing, VIX calm → Undercurrent."""
        mock_fetch.side_effect = _default_side({
            "HYG": [75.0] * 19 + [75.0, 74.6, 74.2, 73.8, 73.5, 73.5],
            "SHY": [82.0] * 25,
            # Haven: avg ~1.83% > 1.5pp threshold
            "GLD": [230.0] * 19 + [230.0, 231.5, 233.0, 235.0, 237.0, 238.05],
            "DX-Y.NYB": [104.0] * 19 + [104.0, 104.1, 104.2, 104.3, 104.4, 104.52],
            "TLT": [92.0] * 19 + [92.0, 92.3, 92.5, 92.8, 93.1, 93.38],
            # Breadth: RSP -2%, SPY flat → gap -2.0 < -1.5pp threshold
            "RSP": [170.0] * 19 + [170.0, 169.0, 168.0, 167.0, 166.4, 166.6],
            "SPY": [530.0] * 25,
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        self.assertTrue(result["signals"]["credit_widening"])
        self.assertTrue(result["signals"]["safe_haven_bid"])
        self.assertTrue(result["signals"]["breadth_deterioration"])
        self.assertFalse(result["signals"]["vix_elevated"])
        self.assertEqual(result["regime"], "Calm with Undercurrent")
        # All detail blocks must have numeric values, not "unavailable"
        self.assertNotIn("unavailable", result["detail"]["credit"]["explanation"])
        self.assertNotIn("unavailable", result["detail"]["breadth"]["explanation"])
        self.assertNotIn("unavailable", result["detail"]["safe_haven"]["explanation"])


# ---------------------------------------------------------------------------
# Weekly-only junk filtering: weekly excludes, persistent keeps
# ---------------------------------------------------------------------------

class TestWeeklyOnlyJunkFilter(unittest.TestCase):
    """Verify that _is_event_low_signal only applies to weekly slice."""

    def _make_events(self, now_dt):
        """Return events with various junk types and one real event."""
        ts_recent = (now_dt - timedelta(hours=6)).isoformat(timespec="seconds")
        ts_old = (now_dt - timedelta(days=10)).isoformat(timespec="seconds")
        low_signal_junk = {
            "headline": "India stage-queens celebration",
            "timestamp": ts_recent,
            "low_signal": 1,
            "market_tickers": [
                {"symbol": "X", "return_5d": 3.0, "return_20d": 5.0,
                 "direction_tag": "supports ↑"},
            ],
        }
        insufficient_evidence = {
            "headline": "US and Ecuador sign reciprocal trade agreement",
            "timestamp": ts_recent,
            "low_signal": 0,
            "mechanism_summary": "Insufficient evidence to identify mechanism.",
            "market_tickers": [
                {"symbol": "ADM", "return_5d": -5.55, "return_20d": -3.82,
                 "direction_tag": "contradicts ↑"},
            ],
        }
        real = {
            "headline": "OPEC cuts oil output by 500k bpd",
            "timestamp": ts_recent,
            "low_signal": 0,
            "mechanism_summary": "OPEC output cuts reduce global crude supply.",
            "market_tickers": [
                {"symbol": "XLE", "return_5d": 4.0, "return_20d": 7.0,
                 "direction_tag": "supports ↑"},
            ],
        }
        # Old junk event for persistent test
        junk_old = {
            "headline": "Ecuador agreement on trade",
            "timestamp": ts_old,
            "low_signal": 1,
            "market_tickers": [
                {"symbol": "EWZ", "return_5d": 2.0, "return_20d": 10.0,
                 "direction_tag": "supports ↑"},
            ],
        }
        return [low_signal_junk, insufficient_evidence, real, junk_old]

    def _stub_summary(self, ev, tickers, support_ratio):
        return {
            "headline": ev["headline"],
            "impact": abs(tickers[0].get("return_5d", 0)),
            "tickers": tickers,
        }

    def _stub_persistent(self, ev, tickers, now_dt):
        ts = ev.get("timestamp", "")
        days = max(0, (now_dt - datetime.fromisoformat(ts)).days) if ts else 0
        return {
            "headline": ev["headline"],
            "impact": abs(tickers[0].get("return_5d", 0)),
            "tickers": tickers,
            "days_since_event": days,
        }

    def _stub_decay(self, r5, r20):
        return {"label": "Holding", "evidence": "test"}

    def test_weekly_excludes_low_signal(self):
        from movers_cache import compute_slice
        now_dt = datetime.now()
        events = self._make_events(now_dt)
        result = compute_slice(
            "weekly", events, now=now_dt,
            build_mover_summary=self._stub_summary,
        )
        headlines = [r["headline"] for r in result]
        self.assertNotIn("India stage-queens celebration", headlines)
        self.assertIn("OPEC cuts oil output by 500k bpd", headlines)

    def test_weekly_excludes_insufficient_evidence(self):
        """Events with 'Insufficient evidence' mechanism must not appear in weekly."""
        from movers_cache import compute_slice
        now_dt = datetime.now()
        events = self._make_events(now_dt)
        result = compute_slice(
            "weekly", events, now=now_dt,
            build_mover_summary=self._stub_summary,
        )
        headlines = [r["headline"] for r in result]
        self.assertNotIn("US and Ecuador sign reciprocal trade agreement", headlines,
                         "Insufficient-evidence event should be excluded from weekly")
        self.assertIn("OPEC cuts oil output by 500k bpd", headlines)

    def test_yearly_keeps_all(self):
        from movers_cache import compute_slice
        now_dt = datetime.now()
        events = self._make_events(now_dt)
        result = compute_slice(
            "yearly", events, now=now_dt,
            build_mover_summary=self._stub_summary,
        )
        headlines = [r["headline"] for r in result]
        # Yearly does NOT filter — junk event is included
        self.assertIn("India stage-queens celebration", headlines)
        self.assertIn("OPEC cuts oil output by 500k bpd", headlines)

    def test_persistent_keeps_junk_with_trajectory(self):
        from movers_cache import compute_slice
        now_dt = datetime.now()
        events = self._make_events(now_dt)
        result = compute_slice(
            "persistent", events, now=now_dt,
            build_persistent_summary=self._stub_persistent,
            classify_decay_fn=self._stub_decay,
        )
        headlines = [r["headline"] for r in result]
        # Persistent does NOT filter low-signal — junk_old is kept
        self.assertIn("Ecuador agreement on trade", headlines)


# ---------------------------------------------------------------------------
# Insufficient-evidence gate: unit test for _is_event_low_signal
# ---------------------------------------------------------------------------

class TestInsufficientEvidenceGate(unittest.TestCase):
    """Verify that 'Insufficient evidence' mechanism_summary triggers the
    low-signal gate, while real mechanisms pass through."""

    def test_insufficient_evidence_is_low_signal(self):
        from movers_cache import _is_event_low_signal
        ev = {
            "headline": "Petronas-chartered tanker loaded with Iraqi crude",
            "mechanism_summary": "Insufficient evidence to identify mechanism.",
            "low_signal": 0,
        }
        self.assertTrue(_is_event_low_signal(ev))

    def test_real_mechanism_passes(self):
        from movers_cache import _is_event_low_signal
        ev = {
            "headline": "China calls for independent refiners to maintain fuel output",
            "mechanism_summary": "War disruptions tighten global refined product markets.",
            "low_signal": 0,
        }
        self.assertFalse(_is_event_low_signal(ev))

    def test_relevant_headline_with_insufficient_evidence_blocked(self):
        """A relevant headline + insufficient evidence → still blocked."""
        from movers_cache import _is_event_low_signal
        ev = {
            "headline": "US and Ecuador sign reciprocal trade agreement",
            "mechanism_summary": "Insufficient evidence to identify mechanism.",
            "low_signal": 0,
        }
        self.assertTrue(_is_event_low_signal(ev))

    def test_empty_mechanism_passes_through(self):
        """Missing or empty mechanism doesn't trigger the gate."""
        from movers_cache import _is_event_low_signal
        ev = {
            "headline": "Fed raises interest rate by 25 basis points",
            "mechanism_summary": "",
            "low_signal": 0,
        }
        self.assertFalse(_is_event_low_signal(ev))


# ---------------------------------------------------------------------------
# Cache purge: corrupt test-fixture data is removed
# ---------------------------------------------------------------------------

class TestCachePurge(unittest.TestCase):
    """Verify that the price_cache purge removes test-fixture fingerprint
    rows (integer close < 10, volume = 1e6) on first init."""

    def setUp(self):
        import tempfile, uuid, db as _db
        self._orig_db = _db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_purge_{uuid.uuid4().hex}.db",
        )
        _db.DB_FILE = self._tmp
        import price_cache
        price_cache._table_ready = False

    def tearDown(self):
        import db as _db
        _db.DB_FILE = self._orig_db
        import price_cache
        price_cache._table_ready = False
        try:
            os.remove(self._tmp)
        except (PermissionError, OSError):
            pass

    def test_corrupt_rows_purged_on_init(self):
        import sqlite3, db as _db, price_cache
        # Create the table and inject corrupt rows
        price_cache._ensure_table()
        price_cache._table_ready = False  # force re-run

        conn = sqlite3.connect(_db.DB_FILE)
        for i in range(9):
            conn.execute(
                "INSERT INTO price_cache (ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, 1000000.0, 1, '2026-04-08T00:00:00+00:00')",
                ("HYG", f"2026-03-{26+i:02d}", float(i)),
            )
        conn.commit()
        corrupt_before = conn.execute(
            "SELECT COUNT(*) FROM price_cache WHERE close < 10 AND volume = 1000000.0"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(corrupt_before, 9)

        # Re-init triggers purge
        price_cache._ensure_table()

        conn = sqlite3.connect(_db.DB_FILE)
        corrupt_after = conn.execute(
            "SELECT COUNT(*) FROM price_cache WHERE close < 10 AND volume = 1000000.0"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(corrupt_after, 0, "Corrupt rows should be purged on init")

    def test_real_data_survives_purge(self):
        import sqlite3, db as _db, price_cache
        price_cache._ensure_table()
        price_cache._table_ready = False

        conn = sqlite3.connect(_db.DB_FILE)
        # Real HYG price
        conn.execute(
            "INSERT INTO price_cache (ticker, date, close, volume, auto_adjust, fetched_at) "
            "VALUES ('HYG', '2026-04-08', 80.19, 2345678.0, 1, '2026-04-08T00:00:00+00:00')"
        )
        # Real ^TNX yield (below 10 but volume != 1e6)
        conn.execute(
            "INSERT INTO price_cache (ticker, date, close, volume, auto_adjust, fetched_at) "
            "VALUES ('^TNX', '2026-04-08', 4.35, 0.0, 1, '2026-04-08T00:00:00+00:00')"
        )
        conn.commit()
        conn.close()

        price_cache._ensure_table()

        conn = sqlite3.connect(_db.DB_FILE)
        hyg = conn.execute("SELECT close FROM price_cache WHERE ticker = 'HYG'").fetchone()
        tnx = conn.execute("SELECT close FROM price_cache WHERE ticker = '^TNX'").fetchone()
        conn.close()
        self.assertIsNotNone(hyg, "Real HYG row must survive")
        self.assertAlmostEqual(hyg[0], 80.19, places=1)
        self.assertIsNotNone(tnx, "Real ^TNX row must survive")
        self.assertAlmostEqual(tnx[0], 4.35, places=1)


if __name__ == "__main__":
    unittest.main()
