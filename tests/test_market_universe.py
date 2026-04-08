"""
tests/test_market_universe.py

Tests for the centralized liquid-market mapping layer.

Covers:
  - Symbol resolution per provider for every liquid market
  - Unknown identifiers return None
  - Provider switch changes the resolved symbol
  - Graceful failure when fetch_market_daily can't reach the provider
  - fetch_market_info shape
  - Integration with market_check.macro_snapshot
"""

import sys
import unittest
from unittest.mock import patch, MagicMock

import pandas as pd

sys.path.insert(0, ".")

import market_data
import market_check
import market_universe
from market_data import (
    YFinanceProvider,
    PolygonProvider,
    set_provider,
    get_provider,
)
from market_universe import (
    LIQUID_MARKETS,
    LIQUID_MARKET_INFO,
    fetch_market_daily,
    fetch_market_info,
    list_markets,
    resolve_symbol,
    _PROVIDER_SYMBOLS,
)


# ---------------------------------------------------------------------------
# Helper: minimal DataFrame
# ---------------------------------------------------------------------------

def _make_df(closes):
    n = len(closes)
    return pd.DataFrame(
        {"Close": closes, "Volume": [1_000_000.0] * n},
        index=pd.date_range("2026-03-01", periods=n, freq="B"),
    )


# ---------------------------------------------------------------------------
# Catalogue completeness
# ---------------------------------------------------------------------------

class TestCatalogueCompleteness(unittest.TestCase):
    """Every liquid market must have metadata and per-provider symbols."""

    def test_every_market_has_info(self):
        for m in LIQUID_MARKETS:
            self.assertIn(m, LIQUID_MARKET_INFO, f"Missing info for {m}")
            info = LIQUID_MARKET_INFO[m]
            for key in ("label", "unit", "asset_class"):
                self.assertIn(key, info, f"{m} missing {key}")

    def test_every_market_has_yfinance_symbol(self):
        for m in LIQUID_MARKETS:
            sym = _PROVIDER_SYMBOLS["yfinance"].get(m)
            self.assertIsNotNone(sym, f"yfinance has no symbol for {m}")
            self.assertTrue(sym, f"yfinance symbol for {m} is empty")

    def test_every_market_has_polygon_symbol(self):
        for m in LIQUID_MARKETS:
            sym = _PROVIDER_SYMBOLS["polygon"].get(m)
            self.assertIsNotNone(sym, f"polygon has no symbol for {m}")
            self.assertTrue(sym, f"polygon symbol for {m} is empty")

    def test_required_markets_present(self):
        """The 8 markets the product needs today must all be present."""
        required = {"ES", "NQ", "RTY", "CL", "GC", "DXY", "2Y", "10Y"}
        self.assertEqual(set(LIQUID_MARKETS), required)


# ---------------------------------------------------------------------------
# Symbol resolution under YFinance
# ---------------------------------------------------------------------------

class TestResolveYFinance(unittest.TestCase):
    """When YFinanceProvider is active, symbols come from the yfinance map."""

    def setUp(self):
        self._saved = get_provider()
        set_provider(YFinanceProvider())

    def tearDown(self):
        set_provider(self._saved)

    def test_es_resolves_to_futures(self):
        self.assertEqual(resolve_symbol("ES"), "ES=F")

    def test_nq_resolves_to_futures(self):
        self.assertEqual(resolve_symbol("NQ"), "NQ=F")

    def test_rty_resolves_to_futures(self):
        self.assertEqual(resolve_symbol("RTY"), "RTY=F")

    def test_cl_resolves_to_futures(self):
        self.assertEqual(resolve_symbol("CL"), "CL=F")

    def test_gc_resolves_to_futures(self):
        self.assertEqual(resolve_symbol("GC"), "GC=F")

    def test_dxy_resolves_to_dollar_index(self):
        self.assertEqual(resolve_symbol("DXY"), "DX-Y.NYB")

    def test_2y_resolves_to_etf_proxy(self):
        # No clean 2Y yield symbol in yfinance — use SHY proxy
        self.assertEqual(resolve_symbol("2Y"), "SHY")

    def test_10y_resolves_to_yield_index(self):
        self.assertEqual(resolve_symbol("10Y"), "^TNX")

    def test_case_insensitive(self):
        self.assertEqual(resolve_symbol("es"), "ES=F")
        self.assertEqual(resolve_symbol("Cl"), "CL=F")


# ---------------------------------------------------------------------------
# Symbol resolution under Polygon
# ---------------------------------------------------------------------------

class TestResolvePolygon(unittest.TestCase):
    """When PolygonProvider is active, symbols are ETF proxies."""

    def setUp(self):
        self._saved = get_provider()
        set_provider(PolygonProvider(api_key="test_key"))

    def tearDown(self):
        set_provider(self._saved)

    def test_es_resolves_to_spy(self):
        self.assertEqual(resolve_symbol("ES"), "SPY")

    def test_nq_resolves_to_qqq(self):
        self.assertEqual(resolve_symbol("NQ"), "QQQ")

    def test_rty_resolves_to_iwm(self):
        self.assertEqual(resolve_symbol("RTY"), "IWM")

    def test_cl_resolves_to_uso(self):
        self.assertEqual(resolve_symbol("CL"), "USO")

    def test_gc_resolves_to_gld(self):
        self.assertEqual(resolve_symbol("GC"), "GLD")

    def test_dxy_resolves_to_uup(self):
        self.assertEqual(resolve_symbol("DXY"), "UUP")

    def test_2y_resolves_to_shy(self):
        self.assertEqual(resolve_symbol("2Y"), "SHY")

    def test_10y_resolves_to_ief(self):
        self.assertEqual(resolve_symbol("10Y"), "IEF")


# ---------------------------------------------------------------------------
# Unknown identifiers and edge cases
# ---------------------------------------------------------------------------

class TestResolveUnknown(unittest.TestCase):

    def test_unknown_market_returns_none(self):
        self.assertIsNone(resolve_symbol("XXX"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(resolve_symbol(""))

    def test_none_returns_none(self):
        self.assertIsNone(resolve_symbol(None))

    def test_raw_yfinance_symbol_returns_none(self):
        """A literal symbol like '^VIX' is not a market identifier."""
        self.assertIsNone(resolve_symbol("^VIX"))

    def test_provider_override(self):
        """Explicit provider arg overrides the active one."""
        set_provider(YFinanceProvider())
        try:
            poly = PolygonProvider(api_key="test")
            self.assertEqual(resolve_symbol("ES", provider=poly), "SPY")
            self.assertEqual(resolve_symbol("ES"), "ES=F")  # active still YFinance
        finally:
            set_provider(YFinanceProvider())


# ---------------------------------------------------------------------------
# fetch_market_info
# ---------------------------------------------------------------------------

class TestFetchMarketInfo(unittest.TestCase):

    def setUp(self):
        self._saved = get_provider()
        set_provider(YFinanceProvider())

    def tearDown(self):
        set_provider(self._saved)

    def test_known_market_returns_full_info(self):
        info = fetch_market_info("CL")
        self.assertIsNotNone(info)
        self.assertEqual(info["market"], "CL")
        self.assertEqual(info["symbol"], "CL=F")
        self.assertEqual(info["label"], "WTI Crude")
        self.assertEqual(info["unit"], "$/bbl")
        self.assertEqual(info["asset_class"], "commodity")

    def test_unknown_market_returns_none(self):
        self.assertIsNone(fetch_market_info("XXX"))

    def test_case_insensitive(self):
        info = fetch_market_info("cl")
        self.assertIsNotNone(info)
        self.assertEqual(info["market"], "CL")

    def test_symbol_changes_with_provider(self):
        """Switching providers changes the resolved symbol."""
        set_provider(YFinanceProvider())
        info_yf = fetch_market_info("ES")
        self.assertEqual(info_yf["symbol"], "ES=F")
        set_provider(PolygonProvider(api_key="test"))
        info_poly = fetch_market_info("ES")
        self.assertEqual(info_poly["symbol"], "SPY")


# ---------------------------------------------------------------------------
# fetch_market_daily — provider delegation and graceful failure
# ---------------------------------------------------------------------------

class TestFetchMarketDaily(unittest.TestCase):
    """fetch_market_daily resolves the symbol and delegates to the provider."""

    def setUp(self):
        self._saved = get_provider()
        market_check._cache_clear()

    def tearDown(self):
        set_provider(self._saved)
        market_check._cache_clear()

    def test_yfinance_path(self):
        df = _make_df([100.0, 101.0, 102.0])
        fake = MagicMock(spec=YFinanceProvider)
        fake.fetch_daily.return_value = df
        # spec=YFinanceProvider makes isinstance() pass
        set_provider(fake)
        result = fetch_market_daily("ES", period="3mo")
        self.assertIs(result, df)
        # Verify the fake was called with the correct ticker for yfinance
        fake.fetch_daily.assert_called_once()
        call = fake.fetch_daily.call_args
        self.assertEqual(call.args[0], "ES=F")
        self.assertEqual(call.kwargs["period"], "3mo")

    def test_polygon_path(self):
        df = _make_df([400.0, 401.0])
        fake = MagicMock(spec=PolygonProvider)
        fake.fetch_daily.return_value = df
        set_provider(fake)
        result = fetch_market_daily("ES", period="3mo")
        self.assertIs(result, df)
        # Polygon should get the ETF proxy symbol
        call = fake.fetch_daily.call_args
        self.assertEqual(call.args[0], "SPY")

    def test_unknown_market_returns_none(self):
        set_provider(YFinanceProvider())
        self.assertIsNone(fetch_market_daily("XXX", period="3mo"))

    def test_provider_failure_returns_none(self):
        """When the provider raises, fetch_market_daily must not propagate."""
        fake = MagicMock(spec=YFinanceProvider)
        fake.fetch_daily.side_effect = ConnectionError("network down")
        set_provider(fake)
        result = fetch_market_daily("ES", period="3mo")
        self.assertIsNone(result)

    def test_provider_returns_none(self):
        """If the provider returns None (no data), so does fetch_market_daily."""
        fake = MagicMock(spec=YFinanceProvider)
        fake.fetch_daily.return_value = None
        set_provider(fake)
        result = fetch_market_daily("CL", period="3mo")
        self.assertIsNone(result)

    def test_auto_adjust_forwarded(self):
        df = _make_df([100.0, 101.0])
        fake = MagicMock(spec=YFinanceProvider)
        fake.fetch_daily.return_value = df
        set_provider(fake)
        fetch_market_daily("CL", start="2026-01-01", auto_adjust=False)
        kwargs = fake.fetch_daily.call_args.kwargs
        self.assertFalse(kwargs["auto_adjust"])


# ---------------------------------------------------------------------------
# list_markets
# ---------------------------------------------------------------------------

class TestListMarkets(unittest.TestCase):

    def setUp(self):
        self._saved = get_provider()
        set_provider(YFinanceProvider())

    def tearDown(self):
        set_provider(self._saved)

    def test_returns_all_liquid_markets(self):
        markets = list_markets()
        self.assertEqual(len(markets), len(LIQUID_MARKETS))

    def test_each_entry_has_symbol(self):
        markets = list_markets()
        for entry in markets:
            self.assertIn("market", entry)
            self.assertIn("symbol", entry)
            self.assertIn("label", entry)
            self.assertIn("unit", entry)


# ---------------------------------------------------------------------------
# Integration: macro_snapshot now goes through the resolver
# ---------------------------------------------------------------------------

class TestMacroSnapshotIntegration(unittest.TestCase):
    """macro_snapshot should pass resolved symbols to _fetch."""

    def setUp(self):
        self._saved = get_provider()
        market_check._cache_clear()

    def tearDown(self):
        set_provider(self._saved)
        market_check._cache_clear()

    def test_yfinance_fetches_native_symbols(self):
        """Under YFinance, macro_snapshot should fetch DX-Y.NYB / ^TNX / CL=F."""
        set_provider(YFinanceProvider())
        called_with: list[str] = []

        def _spy(ticker):
            called_with.append(ticker)
            return _make_df([100.0 + i * 0.1 for i in range(30)])

        with patch("market_check._fetch", side_effect=_spy):
            market_check.macro_snapshot()

        # All five macro instruments should be fetched
        self.assertEqual(len(called_with), 5)
        # The three liquid-market entries should be resolved to yfinance symbols
        self.assertIn("DX-Y.NYB", called_with)
        self.assertIn("^TNX", called_with)
        self.assertIn("CL=F", called_with)
        # The two raw-symbol entries should pass through unchanged
        self.assertIn("^VIX", called_with)
        self.assertIn("BZ=F", called_with)

    def test_polygon_fetches_etf_proxies(self):
        """Under Polygon, macro_snapshot should fetch UUP / IEF / USO."""
        set_provider(PolygonProvider(api_key="test"))
        called_with: list[str] = []

        def _spy(ticker):
            called_with.append(ticker)
            return _make_df([100.0 + i * 0.1 for i in range(30)])

        with patch("market_check._fetch", side_effect=_spy):
            market_check.macro_snapshot()

        self.assertEqual(len(called_with), 5)
        # Liquid markets should be resolved to Polygon ETF proxies
        self.assertIn("UUP", called_with)   # DXY
        self.assertIn("IEF", called_with)   # 10Y
        self.assertIn("USO", called_with)   # CL
        # Raw symbols still pass through (Polygon may not have them, but
        # _fetch will return None and we degrade gracefully)
        self.assertIn("^VIX", called_with)
        self.assertIn("BZ=F", called_with)

    def test_macro_snapshot_unchanged_shape(self):
        """API shape must be stable: same labels, same keys."""
        set_provider(YFinanceProvider())
        df = _make_df([100.0 + i * 0.1 for i in range(30)])
        with patch("market_check._fetch", return_value=df):
            result = market_check.macro_snapshot()
        self.assertEqual(len(result), 5)
        labels = {e["label"] for e in result}
        self.assertEqual(labels, {"USD", "10Y", "VIX", "WTI", "Brent"})
        for entry in result:
            self.assertIn("label", entry)
            self.assertIn("value", entry)
            self.assertIn("change_5d", entry)
            self.assertIn("unit", entry)


# ---------------------------------------------------------------------------
# Provider detection helper
# ---------------------------------------------------------------------------

class TestProviderKindDetection(unittest.TestCase):

    def setUp(self):
        self._saved = get_provider()

    def tearDown(self):
        set_provider(self._saved)

    def test_yfinance_detected(self):
        set_provider(YFinanceProvider())
        self.assertEqual(market_universe._provider_kind(), "yfinance")

    def test_polygon_detected(self):
        set_provider(PolygonProvider(api_key="test"))
        self.assertEqual(market_universe._provider_kind(), "polygon")

    def test_unknown_provider_falls_back_to_yfinance(self):
        """An exotic provider object that isn't Polygon defaults to yfinance map."""
        class _Custom:
            def fetch_daily(self, *a, **k): return None
            def fetch_info(self, *a, **k): return {}
        set_provider(_Custom())
        self.assertEqual(market_universe._provider_kind(), "yfinance")


if __name__ == "__main__":
    unittest.main()
