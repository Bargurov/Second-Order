"""tests/test_reaction_profile_hydration.py

Tests for ``reaction_profile_hydration.hydrate_per_ticker_profile``.

The hydrator composes one per-ticker reaction-profile dict by:
  1. Reading raw close series from the SQLite price cache via an
     injected ``cache_reader`` seam (default:
     ``price_cache.read_window_no_fetch``).
  2. Resolving the benchmark ETF via an injected ``benchmark_resolver``
     seam (default: ``market_check.resolve_benchmark``).
  3. Forwarding the resulting ``closes`` / ``benchmark_closes`` plus the
     saved-row flags (``stale``, ``same_day_fallback``,
     ``validation_quality``) into the pure
     ``reaction_profile.compute_reaction_profile``.

Tests are seam-injected: every test passes a synthetic ``cache_reader``
and ``benchmark_resolver`` so no SQLite, no network, no provider call,
no LLM is touched.

Mirrors the test-plan in ``docs/reaction_profile_hydration_plan.md``
§11.2.
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import Optional, Sequence

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reaction_profile_hydration import hydrate_per_ticker_profile  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture helpers — synthetic cache + benchmark resolver
# ---------------------------------------------------------------------------

ANCHOR_DATE = "2026-04-01"  # Wednesday — a real US trading day


def _bars(closes: Sequence[float], start: str = ANCHOR_DATE) -> pd.DataFrame:
    """Return a DataFrame the cache reader would produce for ``closes``."""
    if not closes:
        return pd.DataFrame(columns=["Close", "Volume"])
    idx = pd.date_range(start=start, periods=len(closes), freq="B")
    return pd.DataFrame(
        {"Close": list(closes), "Volume": [1_000_000.0] * len(closes)},
        index=idx,
    )


def _stub_resolver(_ticker: str) -> tuple[str, str]:
    """Return a fixed benchmark ETF / sector for every ticker."""
    return ("SPY", "market")


def _make_reader(
    *,
    ticker_closes: Optional[Sequence[float]] = None,
    benchmark_closes: Optional[Sequence[float]] = None,
    ticker_symbol: str = "XLE",
    benchmark_symbol: str = "SPY",
):
    """Build a cache_reader callable that returns canned bars per ticker.

    Returns ``None`` for tickers not in the canned mapping (mirrors the
    shape ``read_window_no_fetch`` returns when the DB is unreachable).
    """
    canned: dict[str, Optional[pd.DataFrame]] = {}
    if ticker_closes is not None:
        canned[ticker_symbol.upper()] = _bars(ticker_closes)
    if benchmark_closes is not None:
        canned[benchmark_symbol.upper()] = _bars(benchmark_closes)

    def _reader(ticker: str, *, start: str, end: Optional[str] = None,
                auto_adjust: bool = False) -> Optional[pd.DataFrame]:
        # Read-only contract: tests that want to verify the hydrator
        # never asks for adjusted closes flip auto_adjust here.
        return canned.get((ticker or "").upper())

    return _reader


def _saved_ticker(symbol: str = "XLE", **overrides) -> dict:
    """Build a saved per-ticker block in the same shape ``market_check``
    produces.  Tests can override individual flags.
    """
    base = {
        "symbol":             symbol,
        "role":               "beneficiary",
        "anchor_date":        ANCHOR_DATE,
        "stale":              False,
        "same_day_fallback":  False,
        "validation_quality": "ok",
        "return_5d":          None,
        "direction_tag":      "supports ↑",
    }
    base.update(overrides)
    return base


# Stable shape contract the hydrator always emits.  ``hydration_status``
# is the operator-facing triage label distinct from the composer's
# scoring-shape ``reaction_profile_basis`` — see the docstring for the
# enum definition in ``reaction_profile_hydration.HYDRATION_STATUSES``.
_REQUIRED_KEYS: frozenset = frozenset({
    "symbol",
    "hydration_status",
    "return_1d", "return_5d", "return_20d", "return_60d",
    "benchmark_relative_return_1d",
    "benchmark_relative_return_5d",
    "benchmark_relative_return_20d",
    "benchmark_relative_return_60d",
    "peak_move_5d", "peak_move_20d", "peak_move_60d",
    "time_to_peak_5d", "time_to_peak_20d", "time_to_peak_60d",
    "fade_or_hold_label_5d",
    "fade_or_hold_label_20d",
    "fade_or_hold_label_60d",
    "reaction_profile_basis",
})


# ---------------------------------------------------------------------------
# Happy path — forward-anchored hydration
# ---------------------------------------------------------------------------


class TestForwardAnchoredHydration(unittest.TestCase):
    def test_hydrates_full_keyset_when_cache_has_bars(self) -> None:
        # Anchor 100 → bar 1 +1%, bar 5 +5%, bar 20 +10%, bar 60 +20%.
        bars = [100.0]
        for i in range(1, 61):
            if   i == 1:  bars.append(101.0)
            elif i == 5:  bars.append(105.0)
            elif i == 20: bars.append(110.0)
            elif i == 60: bars.append(120.0)
            else:         bars.append(100.0)

        bench = [100.0]
        for i in range(1, 61):
            if   i == 1:  bench.append(100.5)
            elif i == 5:  bench.append(102.0)
            elif i == 20: bench.append(103.0)
            elif i == 60: bench.append(105.0)
            else:         bench.append(100.0)

        reader = _make_reader(ticker_closes=bars, benchmark_closes=bench)

        out = hydrate_per_ticker_profile(
            _saved_ticker("XLE"),
            event_date=ANCHOR_DATE,
            benchmark_resolver=_stub_resolver,
            cache_reader=reader,
        )
        self.assertEqual(set(out.keys()), _REQUIRED_KEYS)
        self.assertEqual(out["symbol"], "XLE")
        self.assertEqual(out["reaction_profile_basis"], "forward_anchored")
        self.assertAlmostEqual(out["return_1d"],   1.0,  places=2)
        self.assertAlmostEqual(out["return_5d"],   5.0,  places=2)
        self.assertAlmostEqual(out["return_20d"], 10.0,  places=2)
        self.assertAlmostEqual(out["return_60d"], 20.0,  places=2)
        # Relative returns = ticker - benchmark at each horizon.
        self.assertAlmostEqual(out["benchmark_relative_return_1d"],  0.5, places=2)
        self.assertAlmostEqual(out["benchmark_relative_return_5d"],  3.0, places=2)
        self.assertAlmostEqual(out["benchmark_relative_return_20d"], 7.0, places=2)
        self.assertAlmostEqual(out["benchmark_relative_return_60d"], 15.0, places=2)
        # Peak-of-window equals the largest |move| in 1..N — for this
        # series that's the bar at horizon N itself.
        self.assertAlmostEqual(out["peak_move_5d"],   5.0,  places=2)
        self.assertAlmostEqual(out["peak_move_20d"], 10.0,  places=2)
        self.assertAlmostEqual(out["peak_move_60d"], 20.0,  places=2)

    def test_returns_none_means_unscorable_when_cache_empty(self) -> None:
        reader = _make_reader()  # no canned bars at all
        out = hydrate_per_ticker_profile(
            _saved_ticker("XLE"),
            event_date=ANCHOR_DATE,
            benchmark_resolver=_stub_resolver,
            cache_reader=reader,
        )
        self.assertEqual(set(out.keys()), _REQUIRED_KEYS)
        self.assertEqual(out["reaction_profile_basis"], "unscorable")
        for h in ("1d", "5d", "20d", "60d"):
            self.assertIsNone(out[f"return_{h}"])
            self.assertIsNone(out[f"benchmark_relative_return_{h}"])
        for h in ("5d", "20d", "60d"):
            self.assertIsNone(out[f"peak_move_{h}"])
            self.assertIsNone(out[f"time_to_peak_{h}"])
            self.assertEqual(out[f"fade_or_hold_label_{h}"], "insufficient")

    def test_partial_hydration_nulls_only_unfilled_horizons(self) -> None:
        # Only 6 forward bars in cache (anchor + 5 forward bars).  5d
        # populates; 20d / 60d null.
        bars = [100.0, 100.5, 101.0, 101.5, 102.0, 102.5]
        reader = _make_reader(ticker_closes=bars, benchmark_closes=bars)
        out = hydrate_per_ticker_profile(
            _saved_ticker("XLE"),
            event_date=ANCHOR_DATE,
            benchmark_resolver=_stub_resolver,
            cache_reader=reader,
        )
        self.assertEqual(out["reaction_profile_basis"], "forward_anchored")
        self.assertIsNotNone(out["return_5d"])
        self.assertIsNone(out["return_20d"])
        self.assertIsNone(out["return_60d"])
        # 20d / 60d peak families null when their return is null.
        self.assertIsNone(out["peak_move_20d"])
        self.assertIsNone(out["peak_move_60d"])

    def test_only_anchor_present_is_unscorable(self) -> None:
        # Cache returns just the anchor row — composer needs >= 2 bars.
        reader = _make_reader(ticker_closes=[100.0])
        out = hydrate_per_ticker_profile(
            _saved_ticker("XLE"),
            event_date=ANCHOR_DATE,
            benchmark_resolver=_stub_resolver,
            cache_reader=reader,
        )
        self.assertEqual(out["reaction_profile_basis"], "unscorable")


# ---------------------------------------------------------------------------
# Saved-row flags propagate into the composer
# ---------------------------------------------------------------------------


class TestSavedRowFlagsPropagate(unittest.TestCase):
    def test_stale_flag_yields_stale_basis(self) -> None:
        bars = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
        reader = _make_reader(ticker_closes=bars, benchmark_closes=bars)
        out = hydrate_per_ticker_profile(
            _saved_ticker("XLE", stale=True),
            event_date=ANCHOR_DATE,
            benchmark_resolver=_stub_resolver,
            cache_reader=reader,
        )
        self.assertEqual(out["reaction_profile_basis"], "stale")
        # Forward-looking fields nulled even when bars are present.
        for h in ("1d", "5d", "20d", "60d"):
            self.assertIsNone(out[f"return_{h}"])

    def test_same_day_fallback_only_return_1d_populates(self) -> None:
        bars = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
        reader = _make_reader(ticker_closes=bars, benchmark_closes=bars)
        out = hydrate_per_ticker_profile(
            _saved_ticker("XLE", same_day_fallback=True),
            event_date=ANCHOR_DATE,
            benchmark_resolver=_stub_resolver,
            cache_reader=reader,
        )
        self.assertEqual(out["reaction_profile_basis"], "same_day_fallback")
        self.assertAlmostEqual(out["return_1d"], 1.0, places=2)
        self.assertIsNone(out["return_5d"])
        self.assertIsNone(out["return_20d"])
        self.assertIsNone(out["return_60d"])

    def test_quarantined_validation_quality_nulls_relative_returns(self) -> None:
        bars = [100.0] + [100.0 + i for i in range(1, 61)]  # +1% per bar
        reader = _make_reader(ticker_closes=bars, benchmark_closes=bars)
        out = hydrate_per_ticker_profile(
            _saved_ticker("XLE", validation_quality="quarantined"),
            event_date=ANCHOR_DATE,
            benchmark_resolver=_stub_resolver,
            cache_reader=reader,
        )
        self.assertEqual(out["reaction_profile_basis"], "forward_anchored")
        # Ticker returns still populate.
        self.assertIsNotNone(out["return_5d"])
        self.assertIsNotNone(out["return_20d"])
        # Relative returns nulled at every horizon.
        for h in ("1d", "5d", "20d", "60d"):
            self.assertIsNone(out[f"benchmark_relative_return_{h}"])

    def test_warn_validation_quality_keeps_relative_returns(self) -> None:
        bars   = [100.0] + [100.0 + i for i in range(1, 61)]
        bench  = [100.0] + [100.0 + i * 0.5 for i in range(1, 61)]
        reader = _make_reader(ticker_closes=bars, benchmark_closes=bench)
        out = hydrate_per_ticker_profile(
            _saved_ticker("XLE", validation_quality="warn"),
            event_date=ANCHOR_DATE,
            benchmark_resolver=_stub_resolver,
            cache_reader=reader,
        )
        self.assertIsNotNone(out["benchmark_relative_return_5d"])


# ---------------------------------------------------------------------------
# No DB writes / no provider calls — seam-level guarantees
# ---------------------------------------------------------------------------


class TestNoSideEffects(unittest.TestCase):
    def test_seam_reader_is_only_data_path(self) -> None:
        """The hydrator must not import market_data and must not call any
        provider seam.  We patch ``market_data.get_provider`` and
        ``yfinance.download`` / ``yfinance.Ticker`` to raise on call.
        """
        from unittest.mock import patch

        bars   = [100.0] + [100.0 + i for i in range(1, 61)]
        reader = _make_reader(ticker_closes=bars, benchmark_closes=bars)

        boom = AssertionError("hydrator must not touch provider seam")
        with patch("market_data.get_provider", side_effect=boom), \
             patch("yfinance.download",        side_effect=boom), \
             patch("yfinance.Ticker",          side_effect=boom):
            out = hydrate_per_ticker_profile(
                _saved_ticker("XLE"),
                event_date=ANCHOR_DATE,
                benchmark_resolver=_stub_resolver,
                cache_reader=reader,
            )
        self.assertEqual(out["reaction_profile_basis"], "forward_anchored")
        self.assertIsNotNone(out["return_5d"])

    def test_default_cache_reader_does_not_hit_provider_on_cache_miss(self) -> None:
        """Default cache_reader is ``price_cache.read_window_no_fetch``.
        Even on a cache miss it must not trigger a provider fetch.
        """
        from unittest.mock import patch

        with patch("market_data.get_provider",
                   side_effect=AssertionError("provider must not be called")):
            out = hydrate_per_ticker_profile(
                _saved_ticker("DOES_NOT_EXIST_XYZ"),
                event_date=ANCHOR_DATE,
                benchmark_resolver=_stub_resolver,
                # cache_reader omitted → uses real read_window_no_fetch
            )
        # Symbol unknown to cache → unscorable but never raises.
        self.assertEqual(out["reaction_profile_basis"], "unscorable")


# ---------------------------------------------------------------------------
# Determinism — pure over inputs
# ---------------------------------------------------------------------------


class TestDeterminism(unittest.TestCase):
    def test_byte_equal_repeated_invocations(self) -> None:
        bars   = [100.0] + [100.0 + i * 0.5 for i in range(1, 61)]
        reader = _make_reader(ticker_closes=bars, benchmark_closes=bars)
        out1 = hydrate_per_ticker_profile(
            _saved_ticker("XLE"), event_date=ANCHOR_DATE,
            benchmark_resolver=_stub_resolver, cache_reader=reader,
        )
        out2 = hydrate_per_ticker_profile(
            _saved_ticker("XLE"), event_date=ANCHOR_DATE,
            benchmark_resolver=_stub_resolver, cache_reader=reader,
        )
        self.assertEqual(out1, out2)


# ---------------------------------------------------------------------------
# Future-dated / malformed inputs — never raise, always unscorable
# ---------------------------------------------------------------------------


class TestEdgeCases(unittest.TestCase):
    def test_future_dated_event_with_no_cache_rows_unscorable(self) -> None:
        reader = _make_reader()  # no rows for any ticker
        out = hydrate_per_ticker_profile(
            _saved_ticker("XLE"),
            event_date="2099-01-01",
            benchmark_resolver=_stub_resolver,
            cache_reader=reader,
        )
        self.assertEqual(out["reaction_profile_basis"], "unscorable")
        self.assertEqual(set(out.keys()), _REQUIRED_KEYS)

    def test_malformed_event_date_unscorable(self) -> None:
        reader = _make_reader()
        out = hydrate_per_ticker_profile(
            _saved_ticker("XLE"),
            event_date="not-a-date",
            benchmark_resolver=_stub_resolver,
            cache_reader=reader,
        )
        self.assertEqual(out["reaction_profile_basis"], "unscorable")

    def test_missing_event_date_falls_back_to_anchor_date(self) -> None:
        # When event_date is None, the saved ticker block's anchor_date
        # should be used as the anchor instead.
        bars   = [100.0] + [101.0] * 60
        reader = _make_reader(ticker_closes=bars, benchmark_closes=bars)
        out = hydrate_per_ticker_profile(
            _saved_ticker("XLE", anchor_date=ANCHOR_DATE),
            event_date=None,
            benchmark_resolver=_stub_resolver,
            cache_reader=reader,
        )
        self.assertEqual(out["reaction_profile_basis"], "forward_anchored")
        self.assertAlmostEqual(out["return_1d"], 1.0, places=2)

    def test_missing_symbol_unscorable(self) -> None:
        reader = _make_reader(ticker_closes=[100.0, 101.0, 102.0])
        out = hydrate_per_ticker_profile(
            {"role": "beneficiary"},  # no symbol field
            event_date=ANCHOR_DATE,
            benchmark_resolver=_stub_resolver,
            cache_reader=reader,
        )
        self.assertEqual(out["reaction_profile_basis"], "unscorable")
        self.assertIsNone(out["symbol"])


# ---------------------------------------------------------------------------
# Hydration status — operator-facing triage enum
# ---------------------------------------------------------------------------


class TestHydrationStatus(unittest.TestCase):
    """Each branch of ``_derive_hydration_status`` gets a fixture."""

    def test_hydrated_when_return_populates(self) -> None:
        bars = [100.0] + [101.0] * 60
        reader = _make_reader(ticker_closes=bars, benchmark_closes=bars)
        out = hydrate_per_ticker_profile(
            _saved_ticker("XLE"),
            event_date=ANCHOR_DATE,
            benchmark_resolver=_stub_resolver,
            cache_reader=reader,
        )
        self.assertEqual(out["hydration_status"], "hydrated")
        self.assertEqual(out["reaction_profile_basis"], "forward_anchored")

    def test_cache_miss_when_reader_returns_no_rows(self) -> None:
        reader = _make_reader()  # no canned bars at all
        out = hydrate_per_ticker_profile(
            _saved_ticker("XLE"),
            event_date=ANCHOR_DATE,
            benchmark_resolver=_stub_resolver,
            cache_reader=reader,
        )
        self.assertEqual(out["hydration_status"], "cache_miss")
        self.assertEqual(out["reaction_profile_basis"], "unscorable")

    def test_insufficient_window_when_only_anchor_present(self) -> None:
        reader = _make_reader(ticker_closes=[100.0])
        out = hydrate_per_ticker_profile(
            _saved_ticker("XLE"),
            event_date=ANCHOR_DATE,
            benchmark_resolver=_stub_resolver,
            cache_reader=reader,
        )
        self.assertEqual(out["hydration_status"], "insufficient_window")
        self.assertEqual(out["reaction_profile_basis"], "unscorable")

    def test_stale_status_overrides_cache_state(self) -> None:
        # Even with a full cache window, stale=True wins.
        bars = [100.0] + [101.0] * 60
        reader = _make_reader(ticker_closes=bars, benchmark_closes=bars)
        out = hydrate_per_ticker_profile(
            _saved_ticker("XLE", stale=True),
            event_date=ANCHOR_DATE,
            benchmark_resolver=_stub_resolver,
            cache_reader=reader,
        )
        self.assertEqual(out["hydration_status"], "stale")
        self.assertEqual(out["reaction_profile_basis"], "stale")

    def test_stale_status_when_cache_also_empty(self) -> None:
        # stale beats cache_miss too — the operator's takeaway is "this
        # ticker is delisted, ignore", regardless of what the cache says.
        reader = _make_reader()
        out = hydrate_per_ticker_profile(
            _saved_ticker("XLE", stale=True),
            event_date=ANCHOR_DATE,
            benchmark_resolver=_stub_resolver,
            cache_reader=reader,
        )
        self.assertEqual(out["hydration_status"], "stale")

    def test_same_day_fallback_with_r1d_signal_lands_in_hydrated(self) -> None:
        # SDF + 2 cache bars → r1d populates → status="hydrated".  The
        # composer's basis still says "same_day_fallback" so consumers
        # can see the anchor convention; the operator-facing status
        # answers "did we get useful numbers" (yes).
        reader = _make_reader(
            ticker_closes=[100.0, 101.0],
            benchmark_closes=[100.0, 100.5],
        )
        out = hydrate_per_ticker_profile(
            _saved_ticker("XLE", same_day_fallback=True),
            event_date=ANCHOR_DATE,
            benchmark_resolver=_stub_resolver,
            cache_reader=reader,
        )
        self.assertEqual(out["hydration_status"], "hydrated")
        self.assertEqual(out["reaction_profile_basis"], "same_day_fallback")
        self.assertAlmostEqual(out["return_1d"], 1.0, places=2)

    def test_hydration_status_in_required_keys(self) -> None:
        # Defense: every other test would already catch this via the
        # _REQUIRED_KEYS equality assertion, but pin the explicit
        # presence check too.
        bars = [100.0, 101.0]
        reader = _make_reader(ticker_closes=bars, benchmark_closes=bars)
        out = hydrate_per_ticker_profile(
            _saved_ticker("XLE"),
            event_date=ANCHOR_DATE,
            benchmark_resolver=_stub_resolver,
            cache_reader=reader,
        )
        self.assertIn("hydration_status", out)


if __name__ == "__main__":
    unittest.main()
