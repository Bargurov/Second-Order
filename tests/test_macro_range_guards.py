"""
tests/test_macro_range_guards.py

Unit tests for the plausible-range assertion layer covering:
  1. Constant correctness — _MACRO_PRICE_FLOORS and _MACRO_MOVE_CAPS
  2. macro_snapshot — start-price rejection for DXY, WTI, Brent, VIX
  3. macro_snapshot — move-cap rejection and normal pass-through
  4. compute_rates_context — breakeven proxy independent cap (±7 pp)
  5. Constant alignment — _MACRO_MOVE_CAPS["^VIX"] == _VIX_MOVE_CAP
  6. TIP now uses _validated_pct via _PRICE_FLOORS["TIP"] = (60, 160)

All tests mock market_check._fetch so no live network calls are needed.
"""

import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_check


# ---------------------------------------------------------------------------
# Helper: build a minimal Close DataFrame
# ---------------------------------------------------------------------------

def _make_df(closes, start="2026-01-01"):
    n = len(closes)
    dates = pd.date_range(start, periods=n, freq="B")
    return pd.DataFrame({"Close": list(closes), "Volume": [1_000_000.0] * n}, index=dates)


def _stable_df(price, length=25):
    """All rows at the same price — move is always 0%."""
    return _make_df([float(price)] * length)


def _rising_df(start, end, length=25):
    """Linearly rising from start to end over length rows."""
    import numpy as np
    prices = [start + (end - start) * i / (length - 1) for i in range(length)]
    return _make_df(prices)


# ---------------------------------------------------------------------------
# 1) Constant correctness
# ---------------------------------------------------------------------------

class TestMacroPriceFloorsConstants(unittest.TestCase):

    def test_all_expected_identifiers_present(self):
        floors = market_check._MACRO_PRICE_FLOORS
        for ident in ("DXY", "CL", "BZ=F", "^VIX"):
            self.assertIn(ident, floors, f"Missing identifier: {ident}")

    def test_yields_identifier_absent(self):
        # "10Y" is a yield; price-floor validation is not meaningful for yields.
        self.assertNotIn("10Y", market_check._MACRO_PRICE_FLOORS)

    def test_bounds_are_ordered(self):
        for ident, (lo, hi) in market_check._MACRO_PRICE_FLOORS.items():
            self.assertLess(lo, hi, f"{ident}: lower bound must be < upper bound")

    def test_bounds_are_positive(self):
        for ident, (lo, _hi) in market_check._MACRO_PRICE_FLOORS.items():
            self.assertGreater(lo, 0.0, f"{ident}: lower bound must be positive")


class TestMacroMoveCapsConstants(unittest.TestCase):

    def test_all_macro_instruments_covered(self):
        caps = market_check._MACRO_MOVE_CAPS
        for ident in ("DXY", "CL", "BZ=F", "^VIX", "10Y"):
            self.assertIn(ident, caps, f"Missing move cap for: {ident}")

    def test_caps_are_positive(self):
        for ident, cap in market_check._MACRO_MOVE_CAPS.items():
            self.assertGreater(cap, 0.0, f"{ident}: cap must be positive")

    def test_yield_cap_matches_known_extreme(self):
        # ±5 pp (±500 bps) in 5 days is established as beyond any extreme.
        self.assertEqual(market_check._MACRO_MOVE_CAPS["10Y"], 5.0)

    def test_vix_cap_matches_shared_constant(self):
        self.assertEqual(market_check._MACRO_MOVE_CAPS["^VIX"], market_check._VIX_MOVE_CAP)

    def test_tip_in_price_floors(self):
        # TIP is validated via _PRICE_FLOORS so _validated_pct can be used.
        self.assertIn("TIP", market_check._PRICE_FLOORS)
        lo, hi = market_check._PRICE_FLOORS["TIP"]
        self.assertEqual(lo, 60.0)
        self.assertEqual(hi, 160.0)


# ---------------------------------------------------------------------------
# 2) macro_snapshot — start-price rejection
# ---------------------------------------------------------------------------

def _mock_fetch_for_snapshot(ticker_prices: dict):
    """Return a side_effect fn that maps ticker → DataFrame."""
    def _side(sym, *a, **kw):
        return ticker_prices.get(sym)
    return _side


class TestMacroSnapshotStartPriceRejection(unittest.TestCase):
    """When a macro instrument's start price is outside _MACRO_PRICE_FLOORS,
    change_5d must be None even if the data is otherwise well-formed."""

    def _run_snapshot(self, ticker_prices):
        """Run macro_snapshot(no event_date) with mocked _fetch and resolve_symbol.

        resolve_symbol is patched to return None for all identifiers, so the
        code falls back to using the identifier string itself as the fetch key.
        """
        with patch("market_check._fetch", side_effect=_mock_fetch_for_snapshot(ticker_prices)), \
             patch("market_universe.resolve_symbol", return_value=None):
            return market_check.macro_snapshot()

    def _entry(self, results, label):
        return next((e for e in results if e["label"] == label), None)

    def test_dxy_implausible_start_discards_change(self):
        """DXY start price of 5.0 (impossible) → change_5d = None."""
        # 25 rows: first 20 at 5.0 (corrupt), last 5 at 6.0
        prices = [5.0] * 20 + [6.0] * 5
        results = self._run_snapshot({"DXY": _make_df(prices)})
        entry = self._entry(results, "USD")
        self.assertIsNotNone(entry)
        self.assertIsNone(entry["change_5d"],
                          f"DXY implausible start should discard change_5d, got {entry['change_5d']}")

    def test_dxy_plausible_start_passes(self):
        """DXY start price of 95.0 (normal range) → change_5d is set."""
        prices = [95.0] * 20 + [95.5, 95.6, 95.7, 95.8, 95.9]
        results = self._run_snapshot({"DXY": _make_df(prices)})
        entry = self._entry(results, "USD")
        self.assertIsNotNone(entry)
        self.assertIsNotNone(entry["change_5d"],
                             "DXY plausible start should produce a change_5d")

    def test_wti_implausible_start_discards_change(self):
        """WTI (CL) start price of 5.0 (below floor) → change_5d = None."""
        prices = [5.0] * 20 + [5.5] * 5
        results = self._run_snapshot({"CL": _make_df(prices)})
        entry = self._entry(results, "WTI")
        self.assertIsNotNone(entry)
        self.assertIsNone(entry["change_5d"],
                          f"WTI implausible start should discard change_5d, got {entry['change_5d']}")

    def test_wti_plausible_start_passes(self):
        """WTI start price of 80.0 → change_5d is set."""
        prices = [80.0] * 20 + [80.5, 80.6, 80.7, 80.8, 80.9]
        results = self._run_snapshot({"CL": _make_df(prices)})
        entry = self._entry(results, "WTI")
        self.assertIsNotNone(entry)
        self.assertIsNotNone(entry["change_5d"],
                             "WTI plausible start should produce a change_5d")

    def test_vix_implausible_start_discards_change(self):
        """VIX start price of 200.0 (above ceiling of 90) → change_5d = None."""
        prices = [200.0] * 20 + [210.0] * 5
        results = self._run_snapshot({"^VIX": _make_df(prices)})
        entry = self._entry(results, "VIX")
        self.assertIsNotNone(entry)
        self.assertIsNone(entry["change_5d"],
                          f"VIX implausible start should discard change_5d, got {entry['change_5d']}")

    def test_brent_implausible_start_discards_change(self):
        """Brent start price of 5.0 (below floor) → change_5d = None."""
        prices = [5.0] * 20 + [5.5] * 5
        results = self._run_snapshot({"BZ=F": _make_df(prices)})
        entry = self._entry(results, "Brent")
        self.assertIsNotNone(entry)
        self.assertIsNone(entry["change_5d"],
                          f"Brent implausible start should discard change_5d, got {entry['change_5d']}")


# ---------------------------------------------------------------------------
# 3) macro_snapshot — move cap rejection
# ---------------------------------------------------------------------------

class TestMacroSnapshotMoveCap(unittest.TestCase):
    """When the computed 5d move exceeds _MACRO_MOVE_CAPS, change_5d must be None."""

    def _run_snapshot(self, ticker_prices):
        with patch("market_check._fetch", side_effect=_mock_fetch_for_snapshot(ticker_prices)), \
             patch("market_universe.resolve_symbol", return_value=None):
            return market_check.macro_snapshot()

    def _entry(self, results, label):
        return next((e for e in results if e["label"] == label), None)

    def test_dxy_move_above_cap_discarded(self):
        """DXY +20% move (above ±15% cap) → change_5d = None."""
        # start = 95.0, end = 114.0 → +20%
        prices = [95.0] * 20 + [100.0, 105.0, 109.0, 112.0, 114.0]
        results = self._run_snapshot({"DXY": _make_df(prices)})
        entry = self._entry(results, "USD")
        self.assertIsNone(entry["change_5d"],
                          f"DXY +20% should be capped to None, got {entry['change_5d']}")

    def test_dxy_move_at_cap_accepted(self):
        """DXY exactly ±15% — at boundary, should pass (cap is strict >)."""
        # start = 100.0, end = 115.0 → exactly +15%
        prices = [100.0] * 20 + [102.0, 105.0, 109.0, 112.0, 115.0]
        results = self._run_snapshot({"DXY": _make_df(prices)})
        entry = self._entry(results, "USD")
        # 15.0 is not > 15.0, so it should pass
        self.assertIsNotNone(entry["change_5d"],
                             "DXY exactly at cap boundary should pass through")

    def test_dxy_normal_move_passes(self):
        """DXY +1% (well within ±15%) → change_5d is set."""
        prices = [100.0] * 20 + [100.2, 100.4, 100.6, 100.8, 101.0]
        results = self._run_snapshot({"DXY": _make_df(prices)})
        entry = self._entry(results, "USD")
        self.assertIsNotNone(entry["change_5d"],
                             "DXY +1% should produce a change_5d")
        self.assertAlmostEqual(entry["change_5d"], 1.0, places=0)

    def test_wti_move_above_cap_discarded(self):
        """WTI +70% move (above ±65% cap) → change_5d = None."""
        prices = [60.0] * 20 + [70.0, 80.0, 90.0, 95.0, 102.0]
        results = self._run_snapshot({"CL": _make_df(prices)})
        entry = self._entry(results, "WTI")
        self.assertIsNone(entry["change_5d"],
                          f"WTI +70% should be capped to None, got {entry['change_5d']}")

    def test_wti_normal_move_passes(self):
        """WTI +3% → change_5d is set."""
        prices = [80.0] * 20 + [80.5, 81.0, 81.5, 82.0, 82.4]
        results = self._run_snapshot({"CL": _make_df(prices)})
        entry = self._entry(results, "WTI")
        self.assertIsNotNone(entry["change_5d"],
                             "WTI +3% should produce a change_5d")


# ---------------------------------------------------------------------------
# 4) compute_rates_context — breakeven proxy independent cap
# ---------------------------------------------------------------------------

class TestBreakevenProxyIndependentCap(unittest.TestCase):
    """breakeven_proxy_5d must be None when the computed value exceeds ±7 pp,
    even if both nominal and TIP are individually within their bounds."""

    @patch("market_check._fetch")
    def test_be_proxy_exceeds_7pp_discarded(self, mock_fetch):
        """Craft normal-looking nominal + TIP that combine to >7 pp breakeven."""
        # nominal_5d = 4.9 pp (just below ±5 cap)
        # tip_5d = +3.0% (plausible TIP move)
        # _TIP_DURATION ≈ 7.7 → tip_pp = 3.0 / 7.7 ≈ 0.39 pp
        # be_proxy = 4.9 + 0.39 = 5.29 pp  — under 7, not a good test
        #
        # Better: tip_5d = +20% (plausible within 60–160 start price)
        # 107.0 start → end = 107.0 * 1.20 = 128.4 → +20%
        # nominal_5d = 4.9 pp
        # be_proxy = 4.9 + 20 / 7.7 ≈ 4.9 + 2.6 = 7.5 pp → should be capped
        tnx_prices = [4.5] * 5 + [4.5 + i * 0.98 for i in range(6)]  # big move
        # ^TNX is UNIT_YIELD so compute_move gives pp: iloc[-1] - iloc[-6]
        # We need nominal_5d ≈ 4.9 pp
        tnx_series = [4.5] * 19 + [4.5, 4.6, 4.7, 4.8, 4.9, 9.4]  # +4.9 pp
        tip_series = [107.0] * 19 + [107.0, 110.0, 115.0, 121.0, 126.0, 128.4]  # +20%

        def _side(sym, *a, **kw):
            if sym == "^TNX":
                return _make_df(tnx_series)
            if sym == "TIP":
                return _make_df(tip_series)
            return None

        mock_fetch.side_effect = _side
        from market_check import compute_rates_context
        result = compute_rates_context()

        nominal_5d = result.get("nominal", {}).get("change_5d")
        # First verify nominal moved a lot
        self.assertIsNotNone(nominal_5d)
        be_5d = (result.get("breakeven_proxy") or {}).get("change_5d")
        if nominal_5d is not None and abs(nominal_5d) < 5.0:
            # Only check cap if nominal itself wasn't discarded
            # If be_proxy > 7 it should be None
            pass  # covered below

        # Check that if the total be_proxy would exceed 7, it's discarded
        # Build a scenario that definitely exceeds 7 pp
        # nominal = 4.9 pp, TIP = +30% → 4.9 + 30/7.7 ≈ 8.8 pp
        tnx_big = [4.5] * 19 + [4.5, 4.6, 4.7, 4.8, 4.9, 9.4]
        # tip start 107 → end 107*1.30 = 139.1 → +30% (still in 60-160 range)
        tip_big = [107.0] * 19 + [107.0, 112.0, 120.0, 130.0, 136.0, 139.1]

        def _side2(sym, *a, **kw):
            if sym == "^TNX":
                return _make_df(tnx_big)
            if sym == "TIP":
                return _make_df(tip_big)
            return None

        mock_fetch.side_effect = _side2
        result2 = compute_rates_context()

        nominal2 = result2.get("nominal", {}).get("change_5d")
        be2 = (result2.get("breakeven_proxy") or {}).get("change_5d")

        if nominal2 is not None and abs(nominal2) < 5.0:
            # breakeven exceeds 7 pp → must be None
            self.assertIsNone(be2,
                f"breakeven_proxy should be capped to None when >7 pp, got {be2}")

    @patch("market_check._fetch")
    def test_be_proxy_within_cap_passes(self, mock_fetch):
        """Normal scenario: breakeven ~0.2 pp → passes through."""
        tnx_series = [4.50] * 25
        tip_series = [107.0 + i * 0.01 for i in range(25)]  # tiny trend

        def _side(sym, *a, **kw):
            if sym == "^TNX":
                return _make_df(tnx_series)
            if sym == "TIP":
                return _make_df(tip_series)
            return None

        mock_fetch.side_effect = _side
        from market_check import compute_rates_context
        result = compute_rates_context()

        be_5d = (result.get("breakeven_proxy") or {}).get("change_5d")
        self.assertIsNotNone(be_5d, "Normal breakeven proxy should not be None")
        self.assertLess(abs(be_5d), 7.0,
                        f"Normal breakeven proxy should be < 7 pp, got {be_5d}")


# ---------------------------------------------------------------------------
# 5) TIP now uses _validated_pct — still catches corrupt start prices
# ---------------------------------------------------------------------------

class TestTipValidatedPctPath(unittest.TestCase):
    """After refactoring to _validated_pct, TIP corrupt start price must still
    be caught (regression guard)."""

    @patch("market_check._fetch")
    def test_tip_corrupt_start_discarded(self, mock_fetch):
        """TIP start price 0.06 (below floor 60) → change_5d = None."""
        corrupt_tip = [0.06] * 19 + [0.06, 0.2, 0.5, 0.8, 1.0, 1.11]
        normal_tnx = [4.5] * 25

        def _side(sym, *a, **kw):
            if sym == "^TNX":
                return _make_df(normal_tnx)
            if sym == "TIP":
                return _make_df(corrupt_tip)
            return None

        mock_fetch.side_effect = _side
        from market_check import compute_rates_context
        result = compute_rates_context()

        tip_5d = (result.get("real_proxy") or {}).get("change_5d")
        self.assertIsNone(tip_5d,
                          f"TIP corrupt start should produce None change_5d, got {tip_5d}")

    @patch("market_check._fetch")
    def test_tip_normal_start_passes(self, mock_fetch):
        """TIP start price 107.0 (within 60–160) → change_5d is set."""
        normal_tip = [107.0] * 19 + [107.0, 107.1, 107.2, 107.3, 107.4, 107.5]
        normal_tnx = [4.5] * 25

        def _side(sym, *a, **kw):
            if sym == "^TNX":
                return _make_df(normal_tnx)
            if sym == "TIP":
                return _make_df(normal_tip)
            return None

        mock_fetch.side_effect = _side
        from market_check import compute_rates_context
        result = compute_rates_context()

        tip_5d = (result.get("real_proxy") or {}).get("change_5d")
        self.assertIsNotNone(tip_5d, "Normal TIP should produce a change_5d")


if __name__ == "__main__":
    unittest.main()
