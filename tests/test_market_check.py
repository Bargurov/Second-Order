"""
tests/test_market_check.py

Unit tests for market_check.py using mocks — no live network calls.

Strategy: patch market_check._fetch so we control the data each test sees.
This lets us test every label path and edge case without yfinance installed.
"""

import sys
import unittest
from unittest.mock import patch

import pandas as pd

# Make sure we import the real module from the project root.
sys.path.insert(0, ".")
import market_check


# ---------------------------------------------------------------------------
# Helper: build a fake daily DataFrame the same shape yfinance returns
# ---------------------------------------------------------------------------

def _make_df(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    """Return a minimal Close/Volume DataFrame with a business-day DatetimeIndex."""
    n = len(closes)
    if volumes is None:
        volumes = [1_000_000.0] * n
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame({"Close": closes, "Volume": volumes}, index=dates)


# ---------------------------------------------------------------------------
# Tests for _pct() — the percentage-change helper
# ---------------------------------------------------------------------------

class TestPct(unittest.TestCase):

    def test_basic_return(self):
        s = pd.Series([100.0, 110.0])
        self.assertAlmostEqual(market_check._pct(s, 1), 10.0)

    def test_negative_return(self):
        s = pd.Series([100.0, 90.0])
        self.assertAlmostEqual(market_check._pct(s, 1), -10.0)

    def test_not_enough_data_returns_none(self):
        # Need periods+1 rows; asking for 5-period change from 3 rows → None
        s = pd.Series([100.0, 101.0, 102.0])
        self.assertIsNone(market_check._pct(s, 5))

    def test_exact_boundary(self):
        # 6 rows → 5-period change is possible
        s = pd.Series([100.0, 100.0, 100.0, 100.0, 100.0, 103.0])
        self.assertAlmostEqual(market_check._pct(s, 5), 3.0)


class TestPctForward(unittest.TestCase):
    """_pct_forward computes return FROM iloc[0] TO iloc[periods]."""

    def test_basic_forward_return(self):
        # 100 → 110 = +10%
        s = pd.Series([100.0, 110.0])
        self.assertAlmostEqual(market_check._pct_forward(s, 1), 10.0)

    def test_negative_forward_return(self):
        s = pd.Series([100.0, 90.0])
        self.assertAlmostEqual(market_check._pct_forward(s, 1), -10.0)

    def test_not_enough_data_returns_none(self):
        s = pd.Series([100.0, 101.0, 102.0])
        self.assertIsNone(market_check._pct_forward(s, 5))

    def test_five_day_forward_return(self):
        # Base 100 at index 0; index 5 = 105 → +5%
        s = pd.Series([100.0, 100.0, 100.0, 100.0, 100.0, 105.0])
        self.assertAlmostEqual(market_check._pct_forward(s, 5), 5.0)

    def test_forward_differs_from_rolling(self):
        # Rising series: forward return from [0] is different from rolling from [-6]
        s = pd.Series([90.0, 91.0, 92.0, 93.0, 94.0, 95.0])
        forward = market_check._pct_forward(s, 5)
        rolling = market_check._pct(s, 5)
        # forward: 90→95 = +5.56%,  rolling: 90→95 same here, but concept is distinct
        self.assertAlmostEqual(forward, (95 - 90) / 90 * 100, places=4)
        self.assertAlmostEqual(rolling, (95 - 90) / 90 * 100, places=4)


# ---------------------------------------------------------------------------
# Tests for _check_one_ticker() — the per-ticker logic
# ---------------------------------------------------------------------------

class TestCheckOneTicker(unittest.TestCase):

    def _run(self, closes, volumes=None, ticker="GLD", xle_closes=None):
        """Convenience: patch _fetch + _is_valid_ticker and call _check_one_ticker."""
        df = _make_df(closes, volumes)
        xle_df = _make_df(xle_closes) if xle_closes is not None else None
        with patch("market_check._fetch", return_value=df), \
             patch("market_check._is_valid_ticker", return_value=True):
            return market_check._check_one_ticker(ticker, xle_data=xle_df)

    # -- Label: "notable move" ------------------------------------------------

    def test_notable_move_big_move_and_high_volume(self):
        # 5-day return ≥ 2% AND latest volume ≥ 1.25x average
        flat = [100.0] * 35
        last_five = [100.0, 101.0, 103.0, 104.0, 106.0]   # +6% over 5 days
        closes = flat + last_five

        normal_vol = [1_000_000.0] * 39
        spike_vol  = [2_000_000.0]                          # 2x average
        volumes = normal_vol + spike_vol

        result = self._run(closes, volumes)
        self.assertEqual(result["label"], "notable move")

    # -- Label: "in motion" ---------------------------------------------------

    def test_in_motion_big_move_flat_volume(self):
        # 5-day return ≥ 2%, but volume is flat (< 1.25x)
        flat = [100.0] * 35
        last_five = [100.0, 101.0, 103.0, 104.0, 103.0]   # +3%
        closes = flat + last_five
        volumes = [1_000_000.0] * 40                        # flat volume

        result = self._run(closes, volumes)
        self.assertEqual(result["label"], "in motion")

    def test_in_motion_flat_move_high_volume(self):
        # Small 5-day return, but volume is high
        closes  = [100.0] * 40                              # no price move
        volumes = [1_000_000.0] * 39 + [2_000_000.0]       # volume spike

        result = self._run(closes, volumes)
        self.assertEqual(result["label"], "in motion")

    # -- Label: "flat" --------------------------------------------------------

    def test_flat_tiny_move_and_flat_volume(self):
        # 5-day return < 0.5% and volume normal
        closes  = [100.0] * 35 + [100.0, 100.1, 100.2, 100.1, 100.2]  # +0.2%
        volumes = [1_000_000.0] * 40

        result = self._run(closes, volumes)
        self.assertEqual(result["label"], "flat")

    # -- Label: "needs more evidence" -----------------------------------------

    def test_needs_more_evidence_short_series(self):
        # Fewer than 6 rows → not enough data (pre-check passes, full fetch returns short series)
        df = _make_df([100.0, 101.0, 102.0])
        with patch("market_check._fetch", return_value=df), \
             patch("market_check._is_valid_ticker", return_value=True):
            result = market_check._check_one_ticker("GLD")
        self.assertEqual(result["label"], "needs more evidence")

    def test_needs_more_evidence_fetch_returns_none(self):
        # Pre-check passes but full fetch returns nothing (edge case)
        with patch("market_check._fetch", return_value=None), \
             patch("market_check._is_valid_ticker", return_value=True):
            result = market_check._check_one_ticker("GLD")
        self.assertEqual(result["label"], "needs more evidence")

    def test_needs_more_evidence_on_exception(self):
        with patch("market_check._fetch", side_effect=RuntimeError("network error")), \
             patch("market_check._is_valid_ticker", return_value=True):
            result = market_check._check_one_ticker("GLD")
        self.assertEqual(result["label"], "needs more evidence")
        self.assertIn("Error:", result["detail"])

    def test_needs_more_evidence_on_type_error(self):
        # Regression: yfinance occasionally returns malformed data for legitimate
        # tickers like LI (Li Auto), causing a TypeError deep in the computation.
        # The except Exception handler must catch it and return a clean fallback.
        with patch("market_check._fetch", side_effect=TypeError("expected float, got NoneType")), \
             patch("market_check._is_valid_ticker", return_value=True):
            result = market_check._check_one_ticker("LI")
        self.assertEqual(result["label"], "needs more evidence")
        self.assertIn("Error:", result["detail"])
        self.assertIsNone(result["direction"])

    # -- Detail string --------------------------------------------------------

    def test_detail_string_contains_return_windows(self):
        closes  = [100.0] * 35 + [100.0, 100.5, 101.0, 101.5, 102.0]
        volumes = [1_000_000.0] * 40
        result  = self._run(closes, volumes)

        self.assertIn("1d:", result["detail"])
        self.assertIn("5d:", result["detail"])
        self.assertIn("20d:", result["detail"])
        self.assertIn("vol", result["detail"])

    # -- XLE benchmark --------------------------------------------------------

    def test_xle_benchmark_included_for_energy_ticker(self):
        # USO is in ENERGY_PROXIES — relative return vs XLE should appear
        closes_uso = [100.0] * 35 + [100.0, 101.0, 103.0, 104.0, 105.0]   # +5%
        closes_xle = [50.0]  * 35 + [50.0,  50.0,  50.0,  50.0,  50.0]    # flat

        df_uso = _make_df(closes_uso, [2_000_000.0] * 40)
        df_xle = _make_df(closes_xle)

        with patch("market_check._fetch", return_value=df_uso), \
             patch("market_check._is_valid_ticker", return_value=True):
            result = market_check._check_one_ticker("USO", xle_data=df_xle)

        self.assertIn("vs XLE", result["detail"])

    def test_xle_benchmark_skipped_for_non_energy_ticker(self):
        # GLD is not in ENERGY_PROXIES — no relative return even if xle_data given
        closes = [100.0] * 35 + [100.0, 101.0, 103.0, 104.0, 105.0]
        df_gld = _make_df(closes, [2_000_000.0] * 40)
        df_xle = _make_df([50.0] * 40)

        with patch("market_check._fetch", return_value=df_gld), \
             patch("market_check._is_valid_ticker", return_value=True):
            result = market_check._check_one_ticker("GLD", xle_data=df_xle)

        self.assertNotIn("vs XLE", result["detail"])

    def test_xle_benchmark_skipped_when_ticker_is_xle(self):
        # XLE vs itself makes no sense — should be omitted
        closes = [50.0] * 35 + [50.0, 51.0, 52.0, 53.0, 54.0]
        df_xle = _make_df(closes, [2_000_000.0] * 40)

        with patch("market_check._fetch", return_value=df_xle), \
             patch("market_check._is_valid_ticker", return_value=True):
            result = market_check._check_one_ticker("XLE", xle_data=df_xle)

        self.assertNotIn("vs XLE", result["detail"])


# ---------------------------------------------------------------------------
# Tests for structured numeric fields returned by _check_one_ticker()
# ---------------------------------------------------------------------------

class TestCheckOneTickerNumericFields(unittest.TestCase):
    """Verify that _check_one_ticker() returns structured numeric fields
    alongside the existing label/detail/direction keys."""

    def _run(self, closes, volumes=None, ticker="GLD", role="beneficiary"):
        df = _make_df(closes, volumes)
        with patch("market_check._fetch", return_value=df), \
             patch("market_check._is_valid_ticker", return_value=True):
            return market_check._check_one_ticker(ticker, role=role)

    def test_numeric_fields_present_on_success(self):
        closes  = [100.0] * 35 + [100.0, 101.0, 102.0, 103.0, 104.0]
        volumes = [1_000_000.0] * 40
        result  = self._run(closes, volumes)

        for field in ("return_1d", "return_5d", "return_20d", "volume_ratio"):
            self.assertIn(field, result, f"Missing field: {field}")
        self.assertIn("vs_xle_5d", result)

    def test_numeric_fields_are_floats_when_data_available(self):
        closes  = [100.0] * 35 + [100.0, 101.0, 102.0, 103.0, 105.0]
        volumes = [1_000_000.0] * 40
        result  = self._run(closes, volumes)

        self.assertIsInstance(result["return_5d"],    float)
        self.assertIsInstance(result["return_20d"],   float)
        self.assertIsInstance(result["volume_ratio"], float)

    def test_return_5d_value_is_correct(self):
        # 100 → 105 over 5 periods = +5%
        closes = [100.0] * 35 + [100.0, 100.0, 100.0, 100.0, 105.0]
        result = self._run(closes)
        self.assertAlmostEqual(result["return_5d"], 5.0, places=1)

    def test_numeric_fields_none_when_no_data(self):
        # Only 3 rows — not enough for any return windows (pre-check passes)
        df = _make_df([100.0, 101.0, 102.0])
        with patch("market_check._fetch", return_value=df), \
             patch("market_check._is_valid_ticker", return_value=True):
            result = market_check._check_one_ticker("GLD")

        self.assertIsNone(result["return_1d"])
        self.assertIsNone(result["return_5d"])
        self.assertIsNone(result["return_20d"])
        self.assertIsNone(result["volume_ratio"])
        self.assertIsNone(result["vs_xle_5d"])

    def test_numeric_fields_none_on_exception(self):
        with patch("market_check._fetch", side_effect=RuntimeError("network error")), \
             patch("market_check._is_valid_ticker", return_value=True):
            result = market_check._check_one_ticker("GLD")

        self.assertIsNone(result["return_5d"])
        self.assertIsNone(result["volume_ratio"])
        self.assertIsNone(result["vs_xle_5d"])

    def test_vs_xle_5d_is_none_for_non_energy_ticker(self):
        closes = [100.0] * 35 + [100.0, 101.0, 102.0, 103.0, 105.0]
        df_gld = _make_df(closes, [1_000_000.0] * 40)
        df_xle = _make_df([50.0] * 40)
        with patch("market_check._fetch", return_value=df_gld), \
             patch("market_check._is_valid_ticker", return_value=True):
            result = market_check._check_one_ticker("GLD", xle_data=df_xle)
        self.assertIsNone(result["vs_xle_5d"])

    def test_vs_xle_5d_is_float_for_energy_ticker(self):
        # USO outperforms XLE: r5=+5%, XLE r5=0% → vs_xle_5d=+5%
        closes_uso = [100.0] * 35 + [100.0, 101.0, 102.0, 103.0, 105.0]
        closes_xle = [50.0]  * 40
        df_uso = _make_df(closes_uso, [1_000_000.0] * 40)
        df_xle = _make_df(closes_xle)
        with patch("market_check._fetch", return_value=df_uso), \
             patch("market_check._is_valid_ticker", return_value=True):
            result = market_check._check_one_ticker("USO", xle_data=df_xle)
        self.assertIsInstance(result["vs_xle_5d"], float)
        self.assertAlmostEqual(result["vs_xle_5d"], 5.0, places=1)

    def test_volume_ratio_rounded_to_two_dp(self):
        # vol_ratio = 2_000_000 / 1_000_000 = 2.0 exactly
        closes  = [100.0] * 35 + [100.0, 100.0, 100.0, 100.0, 100.0]
        volumes = [1_000_000.0] * 39 + [2_000_000.0]
        result  = self._run(closes, volumes)
        # Round-trip: stored value should have at most 2 decimal places
        self.assertEqual(result["volume_ratio"], round(result["volume_ratio"], 2))


# ---------------------------------------------------------------------------
# Tests for _is_valid_ticker() and the pre-check gate in _check_one_ticker()
# ---------------------------------------------------------------------------

class TestTickerValidityCheck(unittest.TestCase):

    def test_invalid_ticker_returns_unavailable_detail(self):
        # Pre-check fails → return early with a clear message, no fetch attempted
        with patch("market_check._is_valid_ticker", return_value=False):
            result = market_check._check_one_ticker("FAKEXYZ")
        self.assertEqual(result["label"], "needs more evidence")
        self.assertIn("Invalid or unavailable", result["detail"])

    def test_invalid_ticker_has_none_numeric_fields(self):
        with patch("market_check._is_valid_ticker", return_value=False):
            result = market_check._check_one_ticker("FAKEXYZ")
        for field in ("return_1d", "return_5d", "return_20d", "volume_ratio", "vs_xle_5d"):
            self.assertIsNone(result[field], f"Expected None for {field}")

    def test_invalid_ticker_has_none_direction(self):
        with patch("market_check._is_valid_ticker", return_value=False):
            result = market_check._check_one_ticker("FAKEXYZ", role="loser")
        self.assertIsNone(result["direction"])

    def test_fetch_not_called_for_invalid_ticker(self):
        # _fetch should never be called when the pre-check already fails
        with patch("market_check._is_valid_ticker", return_value=False), \
             patch("market_check._fetch") as mock_fetch:
            market_check._check_one_ticker("FAKEXYZ")
        mock_fetch.assert_not_called()

    def test_valid_ticker_proceeds_to_fetch(self):
        # Pre-check passes → _fetch is called normally
        df = _make_df([100.0] * 40, [1_000_000.0] * 40)
        with patch("market_check._is_valid_ticker", return_value=True), \
             patch("market_check._fetch", return_value=df) as mock_fetch:
            market_check._check_one_ticker("GLD")
        mock_fetch.assert_called_once()

    def test_is_valid_ticker_returns_true_for_nonempty_data(self):
        # _is_valid_ticker does `import yfinance as yf` lazily, so we inject a
        # mock module via sys.modules before calling it.
        import sys
        from unittest.mock import MagicMock
        yf_mock = MagicMock()
        yf_mock.download.return_value = _make_df([100.0])   # one row = not empty
        with patch.dict(sys.modules, {"yfinance": yf_mock}):
            self.assertTrue(market_check._is_valid_ticker("GLD"))

    def test_is_valid_ticker_returns_false_for_empty_data(self):
        import sys
        import pandas as pd
        from unittest.mock import MagicMock
        yf_mock = MagicMock()
        yf_mock.download.return_value = pd.DataFrame()      # empty = not found
        with patch.dict(sys.modules, {"yfinance": yf_mock}):
            self.assertFalse(market_check._is_valid_ticker("FAKEXYZ"))

    def test_is_valid_ticker_returns_false_on_exception(self):
        import sys
        from unittest.mock import MagicMock
        yf_mock = MagicMock()
        yf_mock.download.side_effect = Exception("network error")
        with patch.dict(sys.modules, {"yfinance": yf_mock}):
            self.assertFalse(market_check._is_valid_ticker("BADTICKER"))


# ---------------------------------------------------------------------------
# Tests for _direction_tag() — the direction-label helper
# ---------------------------------------------------------------------------

class TestDirectionTag(unittest.TestCase):

    def test_beneficiary_positive_return_supports(self):
        self.assertEqual(market_check._direction_tag(5.0, "beneficiary"), "supports ↑")

    def test_beneficiary_zero_return_supports(self):
        # Flat is still "supports" for a beneficiary (not contradicting)
        self.assertEqual(market_check._direction_tag(0.0, "beneficiary"), "supports ↑")

    def test_beneficiary_negative_return_contradicts(self):
        self.assertEqual(market_check._direction_tag(-3.5, "beneficiary"), "contradicts ↓")

    def test_loser_negative_return_supports(self):
        self.assertEqual(market_check._direction_tag(-4.0, "loser"), "supports ↓")

    def test_loser_zero_return_supports(self):
        # Flat is still "supports" for a loser (not contradicting)
        self.assertEqual(market_check._direction_tag(0.0, "loser"), "supports ↓")

    def test_loser_positive_return_contradicts(self):
        self.assertEqual(market_check._direction_tag(13.3, "loser"), "contradicts ↑")

    def test_none_r5_returns_none(self):
        # No data → no direction tag
        self.assertIsNone(market_check._direction_tag(None, "beneficiary"))
        self.assertIsNone(market_check._direction_tag(None, "loser"))


# ---------------------------------------------------------------------------
# Direction tag integration: direction flows through _check_one_ticker
# ---------------------------------------------------------------------------

class TestCheckOneTickerDirection(unittest.TestCase):

    def _run(self, closes, role, volumes=None, ticker="GLD"):
        df = _make_df(closes, volumes)
        with patch("market_check._fetch", return_value=df), \
             patch("market_check._is_valid_ticker", return_value=True):
            return market_check._check_one_ticker(ticker, role=role)

    def test_beneficiary_up_gets_supports(self):
        flat = [100.0] * 35
        last_five = [100.0, 101.0, 102.0, 103.0, 105.0]   # +5%
        result = self._run(flat + last_five, role="beneficiary")
        self.assertEqual(result["direction"], "supports ↑")

    def test_beneficiary_down_gets_contradicts(self):
        flat = [100.0] * 35
        last_five = [100.0, 99.0, 98.0, 97.0, 96.0]       # -4%
        result = self._run(flat + last_five, role="beneficiary")
        self.assertEqual(result["direction"], "contradicts ↓")

    def test_loser_down_gets_supports(self):
        flat = [100.0] * 35
        last_five = [100.0, 99.0, 98.0, 97.0, 96.0]       # -4%
        result = self._run(flat + last_five, role="loser")
        self.assertEqual(result["direction"], "supports ↓")

    def test_loser_up_gets_contradicts(self):
        flat = [100.0] * 35
        last_five = [100.0, 101.0, 103.0, 105.0, 113.3]   # +13.3%
        result = self._run(flat + last_five, role="loser")
        self.assertEqual(result["direction"], "contradicts ↑")

    def test_no_data_returns_none_direction(self):
        # Only 3 rows — not enough to compute r5 (pre-check passes)
        with patch("market_check._fetch", return_value=_make_df([100.0, 101.0, 102.0])), \
             patch("market_check._is_valid_ticker", return_value=True):
            result = market_check._check_one_ticker("GLD", role="beneficiary")
        self.assertIsNone(result["direction"])


# ---------------------------------------------------------------------------
# Tests for the public market_check() function
# ---------------------------------------------------------------------------

class TestMarketCheck(unittest.TestCase):

    def test_empty_lists(self):
        result = market_check.market_check([], [])
        self.assertEqual(result["note"], "No assets to check.")
        self.assertEqual(result["details"], {})
        self.assertEqual(result["tickers"], [])

    def test_output_shape(self):
        fake = {"label": "in motion", "detail": "1d: +0.1%  |  vol 1.0x avg", "direction": "supports ↑"}
        with patch("market_check._check_one_ticker", return_value=fake):
            result = market_check.market_check(["GLD"], ["USO"])

        self.assertIn("note", result)
        self.assertIn("details", result)
        self.assertIn("tickers", result)
        self.assertEqual(set(result["details"].keys()), {"GLD", "USO"})

    def test_tickers_list_length_matches_unique_tickers(self):
        fake = {"label": "flat", "detail": "5d: +0.1%  |  vol 1.0x avg", "direction": "supports ↑"}
        with patch("market_check._check_one_ticker", return_value=fake):
            result = market_check.market_check(["GLD", "XOM"], ["USO"])
        self.assertEqual(len(result["tickers"]), 3)

    def test_tickers_list_has_required_keys(self):
        fake = {"label": "in motion", "detail": "5d: +2.0%  |  vol 1.0x avg", "direction": "supports ↑"}
        with patch("market_check._check_one_ticker", return_value=fake):
            result = market_check.market_check(["GLD"], [])

        ticker_entry = result["tickers"][0]
        for key in ("symbol", "role", "label", "direction_tag",
                    "return_1d", "return_5d", "return_20d", "volume_ratio", "vs_xle_5d"):
            self.assertIn(key, ticker_entry, f"Missing key in tickers entry: {key}")

    def test_tickers_list_symbol_and_role_correct(self):
        fake = {"label": "flat", "detail": "5d: +0.1%  |  vol 1.0x avg", "direction": "supports ↑"}
        with patch("market_check._check_one_ticker", return_value=fake):
            result = market_check.market_check(["CVX"], ["SU"])

        symbols_roles = {entry["symbol"]: entry["role"] for entry in result["tickers"]}
        self.assertEqual(symbols_roles["CVX"], "beneficiary")
        self.assertEqual(symbols_roles["SU"],  "loser")

    def test_tickers_list_deduped_same_as_details(self):
        # A ticker in both lists appears once; beneficiary takes precedence
        fake = {"label": "flat", "detail": "5d: +0.1%  |  vol 1.0x avg", "direction": "supports ↑"}
        with patch("market_check._check_one_ticker", return_value=fake):
            result = market_check.market_check(["GLD"], ["GLD"])

        self.assertEqual(len(result["tickers"]), 1)
        self.assertEqual(result["tickers"][0]["symbol"], "GLD")
        self.assertEqual(result["tickers"][0]["role"], "beneficiary")

    def test_note_contains_ticker_and_label(self):
        fake = {"label": "notable move", "detail": "5d: +4.1%  |  vol 1.5x avg", "direction": "supports ↑"}
        with patch("market_check._check_one_ticker", return_value=fake):
            result = market_check.market_check(["XOM"], [])

        self.assertIn("XOM", result["note"])
        self.assertIn("notable move", result["note"])

    def test_note_header(self):
        fake = {"label": "flat", "detail": "5d: +0.1%  |  vol 1.0x avg", "direction": "supports ↑"}
        with patch("market_check._check_one_ticker", return_value=fake):
            result = market_check.market_check(["GLD"], [])

        self.assertTrue(result["note"].startswith("Market check (current prices, not event-date validation):"))

    def test_note_contains_role_label(self):
        # Each ticker line should show the role in parentheses
        fake = {"label": "in motion", "detail": "5d: +2.1%  |  vol 1.0x avg", "direction": "supports ↑"}
        with patch("market_check._check_one_ticker", return_value=fake):
            result = market_check.market_check(["TSLA"], ["NIO"])

        self.assertIn("(beneficiary)", result["note"])
        self.assertIn("(loser)", result["note"])

    def test_note_contains_direction_tag(self):
        fake = {"label": "in motion", "detail": "5d: +2.1%  |  vol 1.0x avg", "direction": "supports ↑"}
        with patch("market_check._check_one_ticker", return_value=fake):
            result = market_check.market_check(["GLD"], [])

        self.assertIn("supports ↑", result["note"])

    def test_note_contains_summary_line(self):
        # Summary line should always appear when there is at least one ticker with direction data
        fake = {"label": "in motion", "detail": "5d: +3.0%  |  vol 1.0x avg", "direction": "supports ↑"}
        with patch("market_check._check_one_ticker", return_value=fake):
            result = market_check.market_check(["GLD"], ["USO"])

        self.assertIn("Hypothesis support:", result["note"])

    def test_duplicate_ticker_only_appears_once(self):
        # If a ticker appears in both lists, it should be deduplicated
        fake = {"label": "flat", "detail": "5d: +0.1%  |  vol 1.0x avg", "direction": "supports ↑"}
        with patch("market_check._check_one_ticker", return_value=fake):
            result = market_check.market_check(["GLD"], ["GLD"])

        self.assertEqual(list(result["details"].keys()), ["GLD"])

    def test_no_event_date_uses_current_price_header(self):
        fake = {"label": "flat", "detail": "5d: +0.1%  |  vol 1.0x avg", "direction": "supports ↑"}
        with patch("market_check._check_one_ticker", return_value=fake):
            result = market_check.market_check(["GLD"], [])
        self.assertIn("current prices", result["note"])
        self.assertNotIn("anchored", result["note"])

    def test_event_date_changes_note_header(self):
        fake = {"label": "flat", "detail": "5d: +0.1%  |  vol 1.0x avg", "direction": "supports ↑"}
        with patch("market_check._check_one_ticker", return_value=fake):
            result = market_check.market_check(["GLD"], [], event_date="2025-01-15")
        self.assertIn("anchored to event date: 2025-01-15", result["note"])
        self.assertNotIn("current prices", result["note"])

    def test_event_date_passed_to_check_one_ticker(self):
        # Verify event_date is forwarded to _check_one_ticker via keyword arg
        fake = {"label": "flat", "detail": "5d: +0.1%  |  vol 1.0x avg", "direction": "supports ↑"}
        with patch("market_check._check_one_ticker", return_value=fake) as mock_check:
            market_check.market_check(["GLD"], [], event_date="2025-03-01")
        call_kwargs = mock_check.call_args
        self.assertEqual(call_kwargs.kwargs.get("event_date"), "2025-03-01")

    def test_no_event_date_passes_none_to_check_one_ticker(self):
        fake = {"label": "flat", "detail": "5d: +0.1%  |  vol 1.0x avg", "direction": "supports ↑"}
        with patch("market_check._check_one_ticker", return_value=fake) as mock_check:
            market_check.market_check(["GLD"], [])
        call_kwargs = mock_check.call_args
        self.assertIsNone(call_kwargs.kwargs.get("event_date"))


if __name__ == "__main__":
    unittest.main()
