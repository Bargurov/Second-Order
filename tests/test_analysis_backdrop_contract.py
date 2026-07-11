"""
tests/test_analysis_backdrop_contract.py

Contract tests for the /market-context endpoint as consumed by the
analysis page MarketBackdropStrip component.

The backdrop renders three pieces in one compact strip:
  1. Regime chip from ctx.stress.regime (skipped when "Unknown" or unavailable)
  2. Five key benchmark values: ES, CL, GC, DXY, 10Y (subset of LIQUID_MARKETS)
  3. One "top mover" line from ctx.highlights[0]

These tests lock the contract that:
  - All five backdrop benchmarks must be present in the snapshots payload
  - Stale state must be readable per snapshot
  - Partial availability never crashes the endpoint
  - The shape stays stable so the analysis-view consumer never NPEs
"""

import os
import sys
import time
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

sys.path.insert(0, ".")

import api as api_module
import market_check
from market_data import YFinanceProvider, get_provider, set_provider
from market_snapshots import (
    SNAPSHOT_MAX_AGE_SECONDS,
    get_store,
    refresh_all,
    stop_background_refresh,
)


# The 5 benchmarks the analysis backdrop strip reads.
BACKDROP_MARKETS = ("ES", "CL", "GC", "DXY", "10Y")

# Per-snapshot keys the strip reads on each backdrop entry.
SNAPSHOT_KEYS_USED = {
    "market", "value", "change_5d", "unit", "stale", "error", "fetched_at",
}

# Top-level keys the strip reads on the context object.
CONTEXT_KEYS_USED = {"snapshots", "stress", "highlights", "snapshots_meta", "source"}


def _make_df(closes):
    n = len(closes)
    return pd.DataFrame(
        {"Close": closes, "Volume": [1_000_000.0] * n},
        index=pd.date_range("2026-03-01", periods=n, freq="B"),
    )


def _good_df():
    return _make_df([100.0 + i * 0.5 for i in range(30)])


class _Base(unittest.TestCase):

    def setUp(self):
        os.environ.pop("MARKET_SNAPSHOTS_ENABLED", None)
        get_store().clear()
        market_check._cache_clear()
        self._saved = get_provider()
        set_provider(YFinanceProvider())
        # compute_news_uncertainty otherwise lazy-fetches the full live news
        # pipeline (feeds + clustering) inside the GET — nondeterministic
        # network latency that can stall a full-suite pytest run (T1).  This
        # contract file never reads the uncertainty block, so stub it with
        # the route's own degraded value, mirroring
        # tests/test_market_context_contract.py.
        self._uc_patch = patch("api.compute_news_uncertainty", return_value=None)
        self._uc_patch.start()
        self.client = TestClient(api_module.app)

    def tearDown(self):
        self._uc_patch.stop()
        stop_background_refresh()
        get_store().clear()
        market_check._cache_clear()
        set_provider(self._saved)


# ---------------------------------------------------------------------------
# Full data — happy path
# ---------------------------------------------------------------------------

class TestBackdropFullContext(_Base):

    def _full(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
            return self.client.get("/market-context?highlight_limit=1").json()

    def test_top_level_keys_present(self):
        data = self._full()
        for key in CONTEXT_KEYS_USED:
            self.assertIn(key, data)

    def test_all_backdrop_markets_present_in_snapshots(self):
        data = self._full()
        markets = {s["market"] for s in data["snapshots"]}
        for backdrop_market in BACKDROP_MARKETS:
            self.assertIn(
                backdrop_market, markets,
                f"Backdrop market {backdrop_market} missing from snapshots",
            )

    def test_each_backdrop_snapshot_has_required_keys(self):
        data = self._full()
        by_market = {s["market"]: s for s in data["snapshots"]}
        for market in BACKDROP_MARKETS:
            snap = by_market[market]
            for key in SNAPSHOT_KEYS_USED:
                self.assertIn(
                    key, snap,
                    f"{market} missing key {key}",
                )

    def test_full_data_no_backdrop_markets_unavailable(self):
        data = self._full()
        by_market = {s["market"]: s for s in data["snapshots"]}
        for market in BACKDROP_MARKETS:
            snap = by_market[market]
            self.assertIsNotNone(snap["value"], f"{market} value should be set")
            self.assertIsNone(snap["error"], f"{market} should have no error")
            self.assertFalse(snap["stale"], f"{market} should be fresh")

    def test_stress_section_has_regime(self):
        data = self._full()
        self.assertIn("regime", data["stress"])
        self.assertTrue(data["stress"].get("available"))

    def test_highlights_at_least_empty_list(self):
        data = self._full()
        self.assertIsInstance(data["highlights"], list)

    def test_snapshots_meta_summed_correctly(self):
        data = self._full()
        meta = data["snapshots_meta"]
        self.assertEqual(meta["total"], 8)
        self.assertEqual(meta["fresh"] + meta["stale"] + meta["unavailable"], meta["total"])


# ---------------------------------------------------------------------------
# Partial availability — backdrop subset
# ---------------------------------------------------------------------------

class TestBackdropPartialAvailability(_Base):

    def test_one_backdrop_market_unavailable(self):
        """When CL fails, the backdrop strip can still render the other 4."""
        def _flaky(symbol):
            if symbol == "CL=F":
                return None
            return _good_df()

        with patch("market_check._fetch", side_effect=_flaky):
            refresh_all()
            data = self.client.get("/market-context").json()

        by_market = {s["market"]: s for s in data["snapshots"]}
        cl = by_market["CL"]
        self.assertIsNone(cl["value"])
        self.assertIsNotNone(cl["error"])
        # Other backdrop markets still have data
        for market in ("ES", "GC", "DXY", "10Y"):
            self.assertIsNotNone(by_market[market]["value"])

    def test_all_backdrop_markets_unavailable(self):
        """When all 5 backdrop markets fail, the strip should still get a
        valid context (it will hide itself client-side)."""
        def _flaky(symbol):
            if symbol in {"ES=F", "CL=F", "GC=F", "DX-Y.NYB", "^TNX"}:
                return None
            return _good_df()

        with patch("market_check._fetch", side_effect=_flaky):
            refresh_all()
            response = self.client.get("/market-context")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        by_market = {s["market"]: s for s in data["snapshots"]}
        for market in BACKDROP_MARKETS:
            self.assertIsNone(by_market[market]["value"])
            self.assertIsNotNone(by_market[market]["error"])
        # Stress and highlights still rendered (different fetch path)
        self.assertIn("regime", data["stress"])

    def test_stress_unavailable_strip_still_has_snapshots(self):
        """When stress fails, backdrop falls back to benchmark-only display."""
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        with patch("api.compute_stress_regime", side_effect=RuntimeError("boom")):
            data = self.client.get("/market-context").json()

        # Stress degraded
        self.assertEqual(data["stress"]["regime"], "Unknown")
        self.assertFalse(data["stress"]["available"])
        # Snapshots intact
        by_market = {s["market"]: s for s in data["snapshots"]}
        for market in BACKDROP_MARKETS:
            self.assertIsNotNone(by_market[market]["value"])

    def test_highlights_unavailable_strip_still_has_other_sections(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        with patch("api.movers_today", side_effect=RuntimeError("kaboom")):
            data = self.client.get("/market-context").json()

        self.assertEqual(data["highlights"], [])
        # Other sections present
        self.assertIn("regime", data["stress"])
        self.assertEqual(len(data["snapshots"]), 8)

    def test_cold_store_endpoint_returns_not_refreshed_placeholders(self):
        """Most realistic dev state: snapshot store empty, other sections work.

        Cache-only GET contract (post no-provider-fetch boundary):
        ``/market-context`` reads the SnapshotStore only.  A cold store
        is *not* auto-warmed by the GET — every liquid market surfaces
        as an explicit shaped ``not_refreshed`` placeholder
        (``value=None``) so the backdrop can render a truthful cell
        instead of dropping the strip.  ``market_check._fetch`` is
        patched to a healthy frame precisely to prove the GET does *not*
        reach for it: even with a live seam available, no refresh runs.
        Stress + highlights still compute independently from cached data.

        Warming the store is the (non-GET) snapshot warmer's job — see
        ``TestBackdropFullContext`` and ``TestBackdropCacheOnlyContract``.
        """
        self.assertEqual(len(get_store()), 0, "store must start cold")
        with patch("market_check._fetch", return_value=_good_df()):
            data = self.client.get("/market-context").json()
        # GET is a pure read: the cold store stays cold.
        self.assertEqual(len(get_store()), 0, "GET must not warm the store")
        # Still eight shaped rows, every one an explicit not_refreshed placeholder.
        self.assertEqual(len(data["snapshots"]), 8)
        for snap in data["snapshots"]:
            self.assertEqual(snap["error"], "not_refreshed")
            self.assertIsNone(snap["value"])
        meta = data["snapshots_meta"]
        self.assertEqual(meta["total"], 8)
        self.assertEqual(meta["unavailable"], meta["total"])
        self.assertEqual(meta["fresh"], 0)
        # Operator-readable note: not-refreshed-yet, never a provider failure.
        note = data["snapshot_freshness_note"]
        self.assertIsNotNone(note)
        self.assertIn("have not been refreshed yet", note)
        self.assertNotIn("failed to refresh", note)
        # Other sections still render from their own (cached) fetch paths.
        self.assertIn("regime", data["stress"])

    def test_all_sections_fail_endpoint_still_200(self):
        """Worst case: backdrop should hide itself, never crash the page."""
        with patch("market_snapshots.get_all_snapshots", side_effect=RuntimeError("snap")), \
             patch("api.compute_stress_regime", side_effect=RuntimeError("stress")), \
             patch("api.movers_today", side_effect=RuntimeError("movers")):
            response = self.client.get("/market-context")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["snapshots"], [])
        self.assertEqual(data["highlights"], [])
        self.assertFalse(data["stress"]["available"])


# ---------------------------------------------------------------------------
# Stale state rendering
# ---------------------------------------------------------------------------

class TestBackdropStaleState(_Base):

    def test_one_backdrop_market_stale(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        # Backdate ES (one of the backdrop markets)
        store = get_store()
        with store._lock:
            snap, _ = store._entries["ES"]
            store._entries["ES"] = (
                snap, time.monotonic() - SNAPSHOT_MAX_AGE_SECONDS - 5,
            )
        data = self.client.get("/market-context").json()
        by_market = {s["market"]: s for s in data["snapshots"]}
        es = by_market["ES"]
        self.assertTrue(es["stale"])
        self.assertIsNotNone(es["value"])
        # Other backdrop markets still fresh
        for market in ("CL", "GC", "DXY", "10Y"):
            self.assertFalse(by_market[market]["stale"])

    def test_all_backdrop_markets_stale(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        store = get_store()
        with store._lock:
            for k, (snap, _ts) in list(store._entries.items()):
                store._entries[k] = (
                    snap, time.monotonic() - SNAPSHOT_MAX_AGE_SECONDS - 5,
                )
        data = self.client.get("/market-context").json()
        by_market = {s["market"]: s for s in data["snapshots"]}
        for market in BACKDROP_MARKETS:
            self.assertTrue(by_market[market]["stale"])
            # Data still present so the strip can dim them visually
            self.assertIsNotNone(by_market[market]["value"])

    def test_stale_count_in_meta(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        store = get_store()
        # Backdate two of the backdrop markets
        with store._lock:
            for key in ("CL", "GC"):
                snap, _ = store._entries[key]
                store._entries[key] = (
                    snap, time.monotonic() - SNAPSHOT_MAX_AGE_SECONDS - 5,
                )
        data = self.client.get("/market-context").json()
        meta = data["snapshots_meta"]
        self.assertEqual(meta["stale"], 2)
        self.assertEqual(meta["fresh"], 6)

    def test_freshness_metadata_present_on_each_backdrop_snapshot(self):
        """The strip reads stale + fetched_at to render the inline 'stale' tag."""
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        data = self.client.get("/market-context").json()
        by_market = {s["market"]: s for s in data["snapshots"]}
        for market in BACKDROP_MARKETS:
            snap = by_market[market]
            self.assertIn("stale", snap)
            self.assertIn("fetched_at", snap)


# ---------------------------------------------------------------------------
# Mixed real-world state (one of each kind)
# ---------------------------------------------------------------------------

class TestBackdropMixedState(_Base):

    def test_mixed_fresh_stale_unavailable(self):
        """Realistic blend: most fresh, one stale, one unavailable."""
        def _flaky(symbol):
            if symbol == "GC=F":
                return None
            return _good_df()

        with patch("market_check._fetch", side_effect=_flaky):
            refresh_all()
        # Make CL stale
        store = get_store()
        with store._lock:
            snap, _ = store._entries["CL"]
            store._entries["CL"] = (
                snap, time.monotonic() - SNAPSHOT_MAX_AGE_SECONDS - 5,
            )

        data = self.client.get("/market-context").json()
        by_market = {s["market"]: s for s in data["snapshots"]}

        gc = by_market["GC"]
        self.assertIsNone(gc["value"])
        self.assertIsNotNone(gc["error"])

        cl = by_market["CL"]
        self.assertTrue(cl["stale"])
        self.assertIsNotNone(cl["value"])

        # ES, DXY, 10Y still fresh
        for market in ("ES", "DXY", "10Y"):
            snap = by_market[market]
            self.assertFalse(snap["stale"])
            self.assertIsNotNone(snap["value"])
            self.assertIsNone(snap["error"])

        meta = data["snapshots_meta"]
        self.assertEqual(meta["unavailable"], 1)
        self.assertEqual(meta["stale"], 1)
        self.assertEqual(meta["fresh"], 6)


# ---------------------------------------------------------------------------
# Cache-only GET contract — the backdrop reads the SnapshotStore, it never
# warms it.  Provider-backed refresh + store mutation live behind the
# explicit (non-GET) warmer.  These tests lock that division so a future
# change cannot silently reintroduce synchronous warming from the GET path.
# ---------------------------------------------------------------------------

class TestBackdropCacheOnlyContract(_Base):

    # Top-level sections the analysis backdrop depends on being present.
    TOP_LEVEL_SECTIONS = {
        "snapshots", "snapshots_meta", "snapshot_freshness_note",
        "stress", "highlights", "source",
    }

    def _snapshot_timestamps(self):
        """Monotonic write-timestamps per stored market — mutation fingerprint.

        A GET that re-``update()``s any entry would reset its timestamp; an
        unchanged map after a GET proves the store was read, not rewritten.
        """
        store = get_store()
        with store._lock:
            return {k: v[1] for k, v in store._entries.items()}

    def _assert_backdrop_shape(self, data):
        """Every backdrop market keeps the full consumer key set, in any state."""
        for key in self.TOP_LEVEL_SECTIONS:
            self.assertIn(key, data, f"missing top-level section {key}")
        by_market = {s["market"]: s for s in data["snapshots"]}
        for market in BACKDROP_MARKETS:
            self.assertIn(market, by_market, f"backdrop market {market} dropped")
            for key in SNAPSHOT_KEYS_USED:
                self.assertIn(key, by_market[market], f"{market} missing key {key}")

    # -- Cold store: explicit placeholders, no provider, no writer ----------

    def test_cold_store_get_reaches_no_provider_or_writer(self):
        """A cold-store GET is a pure read: no provider fetch, no cache write,
        no store mutation — yet still 200 with eight shaped placeholders."""
        import price_cache

        class _RecordingProvider:
            def __init__(self):
                self.fetch_daily_calls = []
                self.fetch_info_calls = []

            def fetch_daily(self, ticker, *, period=None, start=None, end=None,
                            auto_adjust=True):
                self.fetch_daily_calls.append(ticker)
                return None

            def fetch_info(self, ticker):
                self.fetch_info_calls.append(ticker)
                return {}

        rec = _RecordingProvider()
        set_provider(rec)  # _Base.tearDown restores the saved provider

        # Recording (not raising) writer: the route wraps each section in
        # try/except, so a raising writer would be swallowed and prove
        # nothing.  Record calls and assert the list stays empty instead.
        writes = []

        def _recording_write_rows(*args, **kwargs):
            writes.append(args)
            return 0

        self.assertEqual(len(get_store()), 0)
        with patch.object(price_cache, "_write_rows", _recording_write_rows):
            resp = self.client.get("/market-context")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(rec.fetch_daily_calls, [], "provider fetch_daily reached from GET")
        self.assertEqual(rec.fetch_info_calls, [], "provider fetch_info reached from GET")
        self.assertEqual(writes, [], "price-cache write attempted during GET")
        self.assertEqual(len(get_store()), 0, "GET mutated the snapshot store")

        data = resp.json()
        self.assertEqual(len(data["snapshots"]), 8)
        for snap in data["snapshots"]:
            self.assertEqual(snap["error"], "not_refreshed")
            self.assertIsNone(snap["value"])

    # -- Explicit warmer owns mutation; GET performs no second refresh ------

    def test_explicit_warmer_populates_store_get_makes_no_second_refresh(self):
        """Division of responsibility: the (non-GET) warmer mutates, the GET
        reads.  After ``refresh_all()`` the store is populated; a subsequent
        GET returns those warm values without re-writing the store or cache."""
        import price_cache

        self.assertEqual(len(get_store()), 0)
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        self.assertEqual(len(get_store()), 8, "explicit warmer must populate the store")

        ts_before = self._snapshot_timestamps()
        writes = []

        def _recording_write_rows(*args, **kwargs):
            writes.append(args)
            return 0

        with patch.object(price_cache, "_write_rows", _recording_write_rows):
            data = self.client.get("/market-context").json()

        self.assertEqual(self._snapshot_timestamps(), ts_before,
                         "GET re-updated a warm snapshot (hidden refresh)")
        self.assertEqual(writes, [], "warm-store GET wrote to the price cache")

        by_market = {s["market"]: s for s in data["snapshots"]}
        for market in BACKDROP_MARKETS:
            self.assertIsNotNone(by_market[market]["value"])
            self.assertIsNone(by_market[market]["error"])
            self.assertFalse(by_market[market]["stale"])

    # -- Stale values stay visible; the GET never auto-refreshes them -------

    def test_stale_store_served_not_auto_refreshed(self):
        """Backdated snapshots read back as stale-but-present; the GET serves
        them as-is (counted stale, not unavailable) and never refreshes."""
        import price_cache

        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        store = get_store()
        with store._lock:
            for k, (snap, _ts) in list(store._entries.items()):
                store._entries[k] = (
                    snap, time.monotonic() - SNAPSHOT_MAX_AGE_SECONDS - 5,
                )
        ts_before = self._snapshot_timestamps()
        writes = []

        def _recording_write_rows(*args, **kwargs):
            writes.append(args)
            return 0

        with patch.object(price_cache, "_write_rows", _recording_write_rows):
            data = self.client.get("/market-context").json()

        self.assertEqual(self._snapshot_timestamps(), ts_before,
                         "GET refreshed a stale snapshot instead of serving it")
        self.assertEqual(writes, [])

        by_market = {s["market"]: s for s in data["snapshots"]}
        for market in BACKDROP_MARKETS:
            self.assertTrue(by_market[market]["stale"])
            self.assertIsNotNone(by_market[market]["value"])
        meta = data["snapshots_meta"]
        self.assertEqual(meta["stale"], 8)
        self.assertEqual(meta["unavailable"], 0)
        note = data["snapshot_freshness_note"]
        self.assertIsNotNone(note)
        self.assertIn("may lag the live tape", note)

    # -- Partial store: real rows kept, missing ones padded -----------------

    def test_partial_store_padded_without_losing_real_rows(self):
        """A partially-populated store keeps its real values; missing markets
        surface as not_refreshed placeholders.  Total stays eight, meta
        reconciles, and the GET mutates nothing."""
        import price_cache

        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        store = get_store()
        missing = ("CL", "GC", "DXY")
        with store._lock:
            for k in missing:
                store._entries.pop(k, None)
        ts_before = self._snapshot_timestamps()
        writes = []

        def _recording_write_rows(*args, **kwargs):
            writes.append(args)
            return 0

        with patch.object(price_cache, "_write_rows", _recording_write_rows):
            data = self.client.get("/market-context").json()

        self.assertEqual(self._snapshot_timestamps(), ts_before, "GET mutated a partial store")
        self.assertEqual(writes, [])

        self.assertEqual(len(data["snapshots"]), 8)
        by_market = {s["market"]: s for s in data["snapshots"]}
        # Backdrop markets still present keep their real values.
        for market in ("ES", "10Y"):
            self.assertIsNotNone(by_market[market]["value"])
            self.assertIsNone(by_market[market]["error"])
        # Dropped markets come back as explicit placeholders, not omitted.
        for market in missing:
            self.assertIsNone(by_market[market]["value"])
            self.assertEqual(by_market[market]["error"], "not_refreshed")
        meta = data["snapshots_meta"]
        self.assertEqual(meta["total"], 8)
        self.assertEqual(meta["unavailable"], len(missing))
        self.assertEqual(meta["fresh"], 8 - len(missing))

    # -- Freshness note distinguishes cold vs stale vs provider failure -----

    def test_freshness_note_distinguishes_cold_stale_and_failed(self):
        """The note tells cold (never refreshed) from stale (cached, may lag)
        from a real provider failure — and never leaks the internal
        ``not_refreshed`` token into product-facing prose."""
        # Cold: not-refreshed-yet wording.
        cold_note = self.client.get("/market-context").json()["snapshot_freshness_note"]
        self.assertIsNotNone(cold_note)
        self.assertIn("have not been refreshed yet", cold_note)
        self.assertNotIn("failed to refresh", cold_note)
        self.assertNotIn("not_refreshed", cold_note)

        # Stale: cached-may-lag wording.
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        store = get_store()
        with store._lock:
            for k, (snap, _ts) in list(store._entries.items()):
                store._entries[k] = (
                    snap, time.monotonic() - SNAPSHOT_MAX_AGE_SECONDS - 5,
                )
        stale_note = self.client.get("/market-context").json()["snapshot_freshness_note"]
        self.assertIsNotNone(stale_note)
        self.assertIn("may lag the live tape", stale_note)

        # Provider failure: warmed with error rows (error != not_refreshed).
        get_store().clear()
        with patch("market_check._fetch", return_value=None):
            refresh_all()
        failed_note = self.client.get("/market-context").json()["snapshot_freshness_note"]
        self.assertIsNotNone(failed_note)
        self.assertIn("failed to refresh from the data provider", failed_note)

    # -- Response shape stays stable across every store state ---------------

    def test_backdrop_row_shape_stable_across_states(self):
        """Cold, warm, stale and partial stores all yield the same stable
        shape: the consumer never NPEs on a missing key.  Values are only
        asserted where the scenario actually has them."""
        # Cold — shape present, values absent (that's the contract).
        self._assert_backdrop_shape(self.client.get("/market-context").json())

        # Warm.
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        self._assert_backdrop_shape(self.client.get("/market-context").json())

        # Stale.
        store = get_store()
        with store._lock:
            for k, (snap, _ts) in list(store._entries.items()):
                store._entries[k] = (
                    snap, time.monotonic() - SNAPSHOT_MAX_AGE_SECONDS - 5,
                )
        self._assert_backdrop_shape(self.client.get("/market-context").json())

        # Partial.
        get_store().clear()
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        with store._lock:
            store._entries.pop("CL", None)
        self._assert_backdrop_shape(self.client.get("/market-context").json())


if __name__ == "__main__":
    unittest.main()
