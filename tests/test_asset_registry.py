"""
tests/test_asset_registry.py

Contract tests for the (channel, region) → benchmark-ticker registry.

Goals:

  1. Non-US coverage actually loads without breaking the import-time
     invariants in ``asset_registry._validate_registry_invariants``.
  2. Every ticker the registry can return has quarantine thresholds in
     ``benchmark_quarantine.BENCHMARK_REGISTRY`` — i.e. the new non-US
     entries that were added alongside this registry line up with the
     lookup table 1-1.
  3. Healthy-path invariant: the default ``region="americas"`` lookup
     returns the same tickers the existing composers (shock_decomposition,
     cross_asset_coherence) already hard-code.  If this test fails a
     future change is about to silently shift US behaviour.
  4. Region vocabulary stays in lockstep with ``feed_registry`` so asset
     coverage and news coverage don't drift into parallel taxonomies.
  5. The new macro series added to ``macro_surprises.SERIES_CATEGORY``
     actually upsert end-to-end — storage/validation didn't regress.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

import asset_registry as ar
from benchmark_quarantine import BENCHMARK_REGISTRY
from feed_registry import ALL_REGIONS
from macro_surprises import SERIES_CATEGORY
import db as _db
import macro_surprises as _ms


# Composer dicts — the source of truth for "what the existing engine
# paths look up today."  Pulled via import so the test catches
# drift on either side without having to keep a frozen copy.
from shock_decomposition import _CHANNEL_BENCHMARK_TICKER as _SHOCK_MAP
from cross_asset_coherence import _COHERENCE_CHANNEL_BENCHMARK as _COHERENCE_MAP


class TestRegistryLoads(unittest.TestCase):
    """Smoke — the module imported without raising its invariant guard."""

    def test_registry_version_present(self) -> None:
        self.assertIsInstance(ar.REGISTRY_VERSION, int)
        self.assertGreaterEqual(ar.REGISTRY_VERSION, 1)

    def test_channel_ids_closed(self) -> None:
        self.assertEqual(
            set(ar.CHANNEL_IDS),
            {"rates", "fx", "equities", "commodities", "credit", "vol"},
        )

    def test_region_ids_match_feed_registry(self) -> None:
        # Asset coverage must use the same region taxonomy news coverage
        # does — otherwise a "europe" flag means different things in two
        # modules.  The registry should re-export the feed vocabulary
        # verbatim.
        self.assertEqual(set(ar.REGION_IDS), set(ALL_REGIONS))


class TestInvariantsEnforced(unittest.TestCase):
    def test_every_ticker_has_quarantine_thresholds(self) -> None:
        for channel in ar.CHANNEL_IDS:
            for region in ar.list_regions_for_channel(channel):
                ticker = ar.get_channel_benchmark(channel, region)
                self.assertIn(
                    ticker.strip().upper(), BENCHMARK_REGISTRY,
                    f"{channel}/{region} → {ticker!r} has no quarantine"
                    " thresholds — add it to BENCHMARK_REGISTRY or drop"
                    " from the lookup.",
                )

    def test_every_channel_covers_every_region(self) -> None:
        # The lookup table is deliberately dense — callers can pass any
        # region without branching on "is this channel available here."
        for channel in ar.CHANNEL_IDS:
            covered = set(ar.list_regions_for_channel(channel))
            self.assertEqual(
                covered, set(ar.REGION_IDS),
                f"channel {channel!r} is missing regions: "
                f"{set(ar.REGION_IDS) - covered}",
            )


class TestAmericasDefaultMatchesComposers(unittest.TestCase):
    """Healthy-path invariant — never silently shift US behaviour."""

    def test_rates_americas_matches_composers(self) -> None:
        expected = ar.get_channel_benchmark("rates", "americas")
        # cross_asset_coherence uses ``rates`` as the key.
        self.assertEqual(_COHERENCE_MAP["rates"], expected)
        # shock_decomposition splits rates into nominal/real/breakeven;
        # nominal_yield is the primary and must also match.
        self.assertEqual(_SHOCK_MAP["nominal_yield"], expected)

    def test_fx_americas_matches_composers(self) -> None:
        expected = ar.get_channel_benchmark("fx", "americas")
        self.assertEqual(_COHERENCE_MAP["fx"], expected)
        self.assertEqual(_SHOCK_MAP["fx"], expected)

    def test_commodities_americas_matches_composers(self) -> None:
        expected = ar.get_channel_benchmark("commodities", "americas")
        self.assertEqual(_COHERENCE_MAP["commodities"], expected)
        self.assertEqual(_SHOCK_MAP["commodity"], expected)

    def test_equities_americas_matches_composers(self) -> None:
        self.assertEqual(
            _COHERENCE_MAP["equities"],
            ar.get_channel_benchmark("equities", "americas"),
        )

    def test_credit_americas_defaults_to_hyg(self) -> None:
        # cross_asset_coherence doesn't register a single credit ticker
        # (credit is a spread composite), so only the registry side is
        # asserted — HYG is the conventional US credit anchor.
        self.assertEqual(
            ar.get_channel_benchmark("credit", "americas"), "HYG",
        )

    def test_vol_americas_matches_composers(self) -> None:
        self.assertEqual(
            _COHERENCE_MAP["vol"],
            ar.get_channel_benchmark("vol", "americas"),
        )

    def test_default_region_is_americas(self) -> None:
        # A caller that doesn't pass ``region`` gets the US answer —
        # identical to pre-registry behaviour.  This is the guarantee
        # the composers rely on when they DON'T opt in.
        for channel in ar.CHANNEL_IDS:
            self.assertEqual(
                ar.get_channel_benchmark(channel),
                ar.get_channel_benchmark(channel, "americas"),
            )


class TestNonUSCoverage(unittest.TestCase):
    def test_europe_rates_is_not_us_ticker(self) -> None:
        # The whole point of the expansion — don't silently fall back to
        # ^TNX for an ECB event.
        self.assertNotIn(
            ar.get_channel_benchmark("rates", "europe"),
            {"10Y", "^TNX", "2Y"},
        )

    def test_europe_equities_is_regional_index(self) -> None:
        self.assertEqual(
            ar.get_channel_benchmark("equities", "europe"),
            "^STOXX50E",
        )

    def test_asia_fx_is_usd_jpy(self) -> None:
        self.assertEqual(
            ar.get_channel_benchmark("fx", "asia"), "USDJPY=X",
        )

    def test_em_credit_is_emb(self) -> None:
        for region in ("latin_america", "south_asia", "africa"):
            self.assertEqual(
                ar.get_channel_benchmark("credit", region), "EMB",
            )

    def test_europe_commodities_is_brent(self) -> None:
        self.assertEqual(
            ar.get_channel_benchmark("commodities", "europe"), "BZ=F",
        )


class TestLookupAPI(unittest.TestCase):
    def test_unknown_channel_raises(self) -> None:
        with self.assertRaises(ValueError):
            ar.get_channel_benchmark("not_a_channel", "americas")

    def test_unknown_region_raises(self) -> None:
        with self.assertRaises(ValueError):
            ar.get_channel_benchmark("rates", "not_a_region")

    def test_is_supported_positive(self) -> None:
        self.assertTrue(ar.is_supported("rates", "europe"))

    def test_is_supported_negative(self) -> None:
        self.assertFalse(ar.is_supported("not_a_channel", "europe"))
        self.assertFalse(ar.is_supported("rates", "not_a_region"))

    def test_list_channel_tickers_unique_sorted(self) -> None:
        tickers = ar.list_channel_tickers("equities")
        self.assertEqual(tickers, sorted(set(tickers)))
        self.assertIn("SPY", tickers)
        self.assertIn("EEM", tickers)

    def test_list_regions_for_channel_matches_table(self) -> None:
        for channel in ar.CHANNEL_IDS:
            self.assertEqual(
                set(ar.list_regions_for_channel(channel)),
                set(ar.REGION_IDS),
            )


# ---------------------------------------------------------------------------
# Non-US macro-series coverage — the SERIES_CATEGORY table grew alongside
# the asset registry; verify the new entries actually work end-to-end.
# ---------------------------------------------------------------------------


class TestNonUSMacroCoverage(unittest.TestCase):
    def test_new_non_us_series_are_registered(self) -> None:
        must_have = [
            # Inflation
            "uk_core_cpi_yoy", "in_cpi_yoy", "br_cpi_yoy", "mx_cpi_yoy",
            # Employment
            "eu_unemployment_rate", "uk_unemployment_rate",
            "jp_unemployment_rate",
            # Growth
            "uk_gdp_qoq", "jp_gdp_qoq",
            "eu_pmi_manufacturing", "eu_pmi_services",
            "uk_pmi_manufacturing", "cn_pmi_manufacturing",
            "cn_industrial_production_yoy", "eu_industrial_production_mom",
            # Monetary policy
            "boc_rate", "rba_rate", "rbi_rate", "snb_rate",
            "br_selic", "mx_tiie",
            # Sentiment
            "eu_economic_sentiment", "de_ifo",
            # Trade
            "eu_trade_balance", "cn_trade_balance", "jp_trade_balance",
        ]
        missing = [s for s in must_have if s not in SERIES_CATEGORY]
        self.assertEqual(missing, [],
                         f"new series missing from SERIES_CATEGORY: {missing}")

    def test_every_series_maps_to_valid_category(self) -> None:
        from macro_surprises import CATEGORY_IDS
        for series, category in SERIES_CATEGORY.items():
            self.assertIn(
                category, CATEGORY_IDS,
                f"series {series!r} → unknown category {category!r}",
            )


class TestNonUSMacroUpsertEndToEnd(unittest.TestCase):
    """A quick round-trip proves validation accepts the new series."""

    def setUp(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".db", prefix="asset_registry_test_")
        os.close(fd)
        os.unlink(path)
        self._tmp_path = path
        self._patchers = [
            mock.patch.object(_db, "DB_FILE", path),
            mock.patch.object(_ms, "DB_FILE", path),
        ]
        for p in self._patchers:
            p.start()
        _db.init_db()

    def tearDown(self) -> None:
        for p in self._patchers:
            p.stop()
        try:
            os.unlink(self._tmp_path)
        except OSError:
            pass

    def test_ecb_rate_upsert(self) -> None:
        stored = _ms.upsert_release(
            series="ecb_rate",
            release_time="2026-03-06T13:15:00+00:00",
            expected=3.75, realized=4.00,
            country="EU", unit="%",
        )
        self.assertEqual(stored["category"], "monetary_policy")
        self.assertEqual(stored["surprise_direction"], "hawkish")

    def test_eu_pmi_manufacturing_upsert(self) -> None:
        # Surprise must clear the 5 %-of-expected inline band to register
        # as hawkish (49.0 × 0.05 = 2.45, so use 52.5).
        stored = _ms.upsert_release(
            series="eu_pmi_manufacturing",
            release_time="2026-04-01T08:00:00+00:00",
            expected=49.0, realized=52.5,
            country="EU",
        )
        self.assertEqual(stored["category"], "growth")
        self.assertEqual(stored["surprise_direction"], "hawkish")

    def test_de_ifo_is_sentiment_category(self) -> None:
        # 5 % of 87 ≈ 4.35, so use a clear miss to clear the inline band.
        stored = _ms.upsert_release(
            series="de_ifo",
            release_time="2026-04-25T08:00:00+00:00",
            expected=87.0, realized=80.0,
            country="DE",
        )
        self.assertEqual(stored["category"], "sentiment")
        self.assertEqual(stored["surprise_direction"], "down")


if __name__ == "__main__":
    unittest.main()
