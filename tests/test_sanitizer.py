"""
tests/test_sanitizer.py

Pure-function unit tests for the ticker sanitizer in analyze_event.py.
No network calls, no API key needed.
"""

import sys
import unittest

sys.path.insert(0, ".")
from analyze_event import _clean_assets, _is_bad_ticker


# ---------------------------------------------------------------------------
# Tests for _is_bad_ticker()
# ---------------------------------------------------------------------------

class TestIsBadTicker(unittest.TestCase):

    def test_normal_us_tickers_pass(self):
        for ticker in ["TSLA", "GLD", "XLE", "SMH", "PALL", "FRO", "DRIV"]:
            with self.subTest(ticker=ticker):
                self.assertFalse(_is_bad_ticker(ticker))

    def test_known_index_symbols_rejected(self):
        for ticker in ["VIX", "DXY", "SPX", "NDX", "RUT"]:
            with self.subTest(ticker=ticker):
                self.assertTrue(_is_bad_ticker(ticker))

    def test_benchmarks_rejected(self):
        for ticker in ["TTF", "JKM", "NBP"]:
            with self.subTest(ticker=ticker):
                self.assertTrue(_is_bad_ticker(ticker))

    def test_eval_observed_bad_tickers_rejected(self):
        for ticker in ["ISDX", "GULF", "ALTM"]:
            with self.subTest(ticker=ticker):
                self.assertTrue(_is_bad_ticker(ticker))

    def test_x_rejected(self):
        # X (US Steel) has had acquisition/delisting issues — no reliable price data
        self.assertTrue(_is_bad_ticker("X"))

    def test_fm_rejected(self):
        # FM (First Quantum Minerals) primary listing is TSX: FM.TO, not US exchange
        self.assertTrue(_is_bad_ticker("FM"))

    def test_eurn_rejected(self):
        # EURN (Euronav) delisted after 2023 merger with Frontline — use FRO instead
        self.assertTrue(_is_bad_ticker("EURN"))

    def test_tell_rejected(self):
        # TELL (Tellurian) filed bankruptcy 2024 — use LNG or UNG instead
        self.assertTrue(_is_bad_ticker("TELL"))

    def test_arnc_rejected(self):
        # ARNC = Arconic Corp, inconsistent yfinance coverage after Howmet spinoff
        self.assertTrue(_is_bad_ticker("ARNC"))

    def test_egpt_rejected(self):
        # EGPT = VanEck Egypt ETF, very low volume / frequently empty yfinance data
        self.assertTrue(_is_bad_ticker("EGPT"))

    def test_arch_rejected(self):
        # ARCH = Arch Resources, merged into CEIX 2024, ticker retired
        self.assertTrue(_is_bad_ticker("ARCH"))

    def test_pcrfy_rejected(self):
        # PCRFY = Porsche AG OTC ADR, unreliable yfinance coverage
        self.assertTrue(_is_bad_ticker("PCRFY"))

    def test_lges_rejected(self):
        # LGES = LG Energy Solution, primary listing is KRX, not US-listed
        self.assertTrue(_is_bad_ticker("LGES"))

    def test_foreign_suffix_rejected(self):
        for ticker in ["8035.T", "FM.TO", "VOD.L", "005930.KS"]:
            with self.subTest(ticker=ticker):
                self.assertTrue(_is_bad_ticker(ticker))

    def test_caret_prefix_rejected(self):
        for ticker in ["^VIX", "^GSPC", "^TNX"]:
            with self.subTest(ticker=ticker):
                self.assertTrue(_is_bad_ticker(ticker))

    def test_empty_and_whitespace_rejected(self):
        for ticker in ["", "  ", "\t"]:
            with self.subTest(ticker=repr(ticker)):
                self.assertTrue(_is_bad_ticker(ticker))


# ---------------------------------------------------------------------------
# Tests for _clean_assets()
# ---------------------------------------------------------------------------

class TestCleanAssets(unittest.TestCase):

    def test_clean_list_passes_through_unchanged(self):
        assets = ["TSLA", "GLD", "XLE"]
        self.assertEqual(_clean_assets(assets), ["TSLA", "GLD", "XLE"])

    def test_normalises_to_uppercase(self):
        result = _clean_assets(["tsla", "gld", "xle"])
        self.assertEqual(result, ["TSLA", "GLD", "XLE"])

    def test_strips_whitespace_around_tickers(self):
        result = _clean_assets(["  TSLA  ", " GLD", "XLE "])
        self.assertEqual(result, ["TSLA", "GLD", "XLE"])

    def test_bad_tickers_removed(self):
        result = _clean_assets(["TSLA", "VIX", "TTF", "GLD", "XLE"])
        self.assertNotIn("VIX", result)
        self.assertNotIn("TTF", result)
        self.assertIn("TSLA", result)
        self.assertIn("GLD", result)

    def test_foreign_suffixes_removed(self):
        result = _clean_assets(["8035.T", "TSM", "ASML"], context="semiconductor chip")
        self.assertNotIn("8035.T", result)
        self.assertIn("TSM", result)
        self.assertIn("ASML", result)

    def test_deduplicates_preserving_order(self):
        result = _clean_assets(["GLD", "XLE", "GLD", "SMH"])
        self.assertEqual(result.count("GLD"), 1)
        self.assertEqual(result.index("GLD"), 0)  # first occurrence kept

    def test_capped_at_five(self):
        assets = ["TSLA", "AAPL", "GLD", "XLE", "SMH", "PALL", "FRO"]
        result = _clean_assets(assets)
        self.assertLessEqual(len(result), 5)

    def test_backfill_when_only_one_good_ticker(self):
        # VIX and TTF are removed, leaving only TSLA — backfill should add oil proxies
        result = _clean_assets(["TSLA", "VIX", "TTF"], context="oil crude petroleum barrel")
        self.assertGreaterEqual(len(result), 3)
        self.assertIn("TSLA", result)
        self.assertTrue(any(t in result for t in ["XLE", "USO", "BNO"]))

    def test_backfill_uses_semiconductor_context(self):
        result = _clean_assets(["8035.T", "^VIX"], context="semiconductor chip foundry")
        self.assertGreaterEqual(len(result), 1)
        self.assertTrue(any(t in result for t in ["SMH", "SOXX"]))

    def test_backfill_uses_shipping_context(self):
        result = _clean_assets(["TTF", "VIX"], context="shipping tanker vessel maritime")
        self.assertTrue(any(t in result for t in ["FRO", "STNG"]))

    def test_no_backfill_when_already_three_good_tickers(self):
        # Three clean tickers → backfill should not add anything extra
        result = _clean_assets(["TSLA", "GLD", "XLE"], context="oil crude opec")
        # Result should still be exactly those three (XLE already present, no new oil proxies)
        self.assertEqual(result, ["TSLA", "GLD", "XLE"])

    def test_empty_input_no_context_returns_empty(self):
        result = _clean_assets([], context="")
        self.assertEqual(result, [])

    def test_eurn_and_tell_removed_and_backfilled(self):
        # Regression: EURN and TELL were slipping through in eval
        result = _clean_assets(["EURN", "TELL", "FRO"], context="shipping tanker lng gas export")
        self.assertNotIn("EURN", result)
        self.assertNotIn("TELL", result)
        self.assertIn("FRO", result)
        # Only FRO survived → backfill should bring total to ≥ 3
        self.assertGreaterEqual(len(result), 3)

    def test_x_and_fm_removed_and_backfilled(self):
        # Regression: X and FM were slipping through in eval; metals context backfills
        result = _clean_assets(["X", "FM", "NUE"], context="steel metal mining copper")
        self.assertNotIn("X", result)
        self.assertNotIn("FM", result)
        self.assertIn("NUE", result)
        # Only NUE survived → backfill should bring total to ≥ 3
        self.assertGreaterEqual(len(result), 3)

    def test_arnc_egpt_removed_and_backfilled(self):
        # Regression: ARNC and EGPT flagged in canary eval; metals context backfills
        result = _clean_assets(
            ["ARNC", "EGPT", "AA"],
            context="aluminum metal mining copper",
        )
        self.assertNotIn("ARNC", result)
        self.assertNotIn("EGPT", result)
        self.assertIn("AA", result)              # clean ticker survives
        self.assertGreaterEqual(len(result), 3)  # backfill kicks in

    def test_arch_pcrfy_lges_removed_and_backfilled(self):
        # Regression: ARCH (retired), PCRFY (OTC ADR), LGES (KRX-listed) flagged in eval
        result = _clean_assets(
            ["ARCH", "PCRFY", "LGES", "ALB"],
            context="battery lithium electric vehicle ev",
        )
        self.assertNotIn("ARCH", result)
        self.assertNotIn("PCRFY", result)
        self.assertNotIn("LGES", result)
        self.assertIn("ALB", result)          # clean ticker survives
        self.assertGreaterEqual(len(result), 3)  # backfill kicks in

    def test_non_string_entries_skipped(self):
        # LLM could theoretically return malformed list items
        result = _clean_assets(["TSLA", None, 123, "GLD"])  # type: ignore
        self.assertIn("TSLA", result)
        self.assertIn("GLD", result)
        self.assertNotIn(None, result)
        self.assertNotIn(123, result)


if __name__ == "__main__":
    unittest.main()
