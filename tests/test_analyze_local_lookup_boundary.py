"""A1-4R — resolving a durable request identity must stay local and read-only.

A1-4 derives the durable request hash from the exact rendered prompt, and the
prompt embeds the macro backdrop.  The first implementation therefore built the
macro context BEFORE the durable lookup, on the normal (fetch-enabled) path, so
merely asking "does a saved analysis already exist?" could reach the external
market-data provider and write rows into the price cache — including on an
unconfirmed request, which had previously been completely free.

The contract this module pins:

  * every step before an explicit ``confirm_paid`` runs on local reads only —
    no provider call, no cache refresh, no write of any kind;
  * when the exact basis CAN be reconstructed locally, the durable lookup
    proceeds exactly as before;
  * when it CANNOT, the route says so (``durable_lookup_basis_unavailable``)
    instead of hashing a knowingly-degraded prompt and calling the answer
    exact, and instead of falling through to a weak headline match;
  * a confirmed run rebuilds the basis normally (it may refresh), then looks
    the durable cache up a SECOND time, so a refresh that lands on an
    already-saved basis reuses it rather than billing again.

Every provider seam is patched or armed to raise; no test here calls a real
provider.
"""

import os
import sqlite3
import tempfile
import unittest
import uuid
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

import api as _api
import db as _db
import market_check as _mc
import market_data as _md
import price_cache as _pc

_HEADLINE = "Central bank leaves policy rate unchanged"
_OTHER = "Port authority suspends container throughput"

_ANALYSIS = {
    "what_changed": "The policy rate was held.",
    "mechanism_summary": "The expected path is unchanged.",
    "beneficiaries": ["banks"], "losers": ["borrowers"],
    "beneficiary_tickers": [], "loser_tickers": [], "assets_to_watch": [],
    "confidence": "medium", "transmission_chain": ["hold"],
    "key_falsifiers": ["A cut within two meetings"], "primary_assets": ["XLF"],
    "if_persists": {}, "currency_channel": {},
}


def _frame(days: int, *, end: date | None = None) -> pd.DataFrame:
    """A synthetic daily frame ending on ``end`` (default: today)."""
    end = end or date.today()
    idx = pd.bdate_range(end=pd.Timestamp(end), periods=days)
    return pd.DataFrame(
        {"Close": [100.0 + i for i in range(len(idx))],
         "Volume": [1000 + i for i in range(len(idx))]},
        index=idx,
    )


class _Base(unittest.TestCase):
    """One temp DB per test; every external seam recorded, never performed."""

    def setUp(self):
        self._orig = _db.DB_FILE
        self._tmp = os.path.join(tempfile.gettempdir(),
                                 f"test_a14r_{uuid.uuid4().hex}.db")
        _db.DB_FILE = self._tmp
        _db.init_db()
        self.client = TestClient(_api.app)
        self.provider_fetches: list = []      # market-data provider reaches
        self.price_writes: list = []          # price-cache row writes
        self.analysis_calls: list = []        # paid analysis-provider calls
        _mc._cache_data.clear()

    def tearDown(self):
        _db.DB_FILE = self._orig
        _mc._cache_data.clear()
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    # -- seams ----------------------------------------------------------
    def _analysis(self, *a, **k):
        self.analysis_calls.append(1)
        return dict(_ANALYSIS)

    def _seams(self, *, arm=False):
        """Patch every external seam.

        ``arm=True`` makes the market provider RAISE, so a reached provider
        is a hard failure rather than a counted one.
        """
        real_write = _pc._write_rows

        def spy_write(ticker, df, auto_adjust, **kw):
            self.price_writes.append(str(ticker))
            return real_write(ticker, df, auto_adjust, **kw)

        class _Recording:
            def __init__(self, sink, arm):
                self._sink, self._arm = sink, arm

            def fetch_daily(self, ticker, **kw):
                self._sink.append(str(ticker))
                if self._arm:
                    raise AssertionError(
                        f"external market provider was called for {ticker}")
                return None

            def fetch_info(self, ticker):
                self._sink.append(str(ticker))
                if self._arm:
                    raise AssertionError(
                        f"external market provider was called for {ticker}")
                return {"symbol": ticker}

        return [
            patch("routes.analyze._call_analyze_event", self._analysis),
            patch.object(_api, "market_check",
                         return_value={"note": "", "tickers": []}),
            patch.object(_md, "_provider",
                         _Recording(self.provider_fetches, arm)),
            patch.object(_pc, "_write_rows", spy_write),
        ]

    def _stub_cached_response(self):
        """Replace the saved-event response builder with an inert marker.

        Serving a saved event recomputes live market overlays inside
        ``_build_cached_response``.  That is PRE-EXISTING post-retrieval
        behaviour (a numeric ``event_id`` reopen has always paid it) and is
        explicitly outside this repair.  Stubbing it isolates the boundary
        this module owns: everything up to and including the durable-cache
        resolution.  ``TestRetrievalOverlayIsOutOfScope`` below pins that
        split so the narrower assertion is stated, not hidden.
        """
        self.served: list = []

        def stub(cached, headline, effective_date, force=False):
            self.served.append(cached)
            return {"served_from_cache": True,
                    "analysis_event_id": cached.get("id"),
                    "analysis": cached}

        return patch.object(_api, "_build_cached_response", stub)

    def _post(self, body, path="/analyze", *, arm=False, extra=None):
        stack = self._seams(arm=arm) + list(extra or [])
        for p in stack:
            p.start()
        try:
            return self.client.post(path, json=body)
        finally:
            for p in reversed(stack):
                p.stop()

    # -- state ----------------------------------------------------------
    def _count(self, conn, table):
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.OperationalError:
            return 0          # table not created yet in this temp DB

    def _counts(self):
        conn = sqlite3.connect(self._tmp)
        try:
            return tuple(self._count(conn, t) for t in
                         ("events", "analysis_result_snapshot",
                          "analysis_request_cache", "price_cache"))
        finally:
            conn.close()

    def _seed_prices(self, *, days=200, end=None):
        """Populate the local price cache for exactly the tickers the macro
        build asks for, through the real write path, from a fake in-process
        provider.  Discovering the ticker set this way keeps the fixture from
        rotting when the macro backdrop changes.
        """
        frame_end = end

        class _Fake:
            def fetch_daily(_s, ticker, **kw):
                return _frame(days, end=frame_end)

            def fetch_info(_s, ticker):
                return {"symbol": ticker}

        _mc._cache_data.clear()
        with patch.object(_md, "_provider", _Fake()):
            try:
                _api.build_macro_context_for_prompt()
            except Exception:
                pass
        _mc._cache_data.clear()

    def _seed_saved_analysis(self):
        """One confirmed run, so a durable mapping exists to be found.

        Leaves the in-process macro memo exactly as the run left it — the
        warm-lookup case depends on that state being real, not reconstructed.
        """
        resp = self._post({"headline": _HEADLINE, "confirm_paid": True}).json()
        self.provider_fetches.clear()
        self.price_writes.clear()
        self.analysis_calls.clear()
        return resp


# ---------------------------------------------------------------------------
# The no-fetch boundary itself
# ---------------------------------------------------------------------------

class TestNoFetchBoundarySemantics(_Base):

    def test_a_blocked_read_still_returns_complete_local_data(self):
        self._seed_prices()
        with self._seams(arm=True)[2]:
            with _md.no_provider_fetch():
                got = _pc.fetch_daily_cached("^TNX", period="3mo",
                                             auto_adjust=True)
        self.assertIsNotNone(got)
        self.assertFalse(got.empty)
        self.assertEqual(self.provider_fetches, [])

    def test_a_blocked_read_of_an_empty_cache_reports_unavailable_not_refreshed(self):
        with self._seams(arm=True)[2]:
            with _md.no_provider_fetch():
                got = _pc.fetch_daily_cached("^TNX", period="3mo",
                                             auto_adjust=True)
        self.assertIsNone(got)
        self.assertEqual(self.provider_fetches, [])
        self.assertEqual(self.price_writes, [])

    def test_a_blocked_read_writes_nothing_at_all(self):
        stack = self._seams(arm=True)
        for p in (stack[2], stack[3]):
            p.start()
        try:
            before = self._counts()
            with _md.no_provider_fetch():
                _pc.fetch_daily_cached("^TNX", period="3mo", auto_adjust=True)
            self.assertEqual(self.price_writes, [])
            self.assertEqual(self._counts(), before)
        finally:
            for p in (stack[3], stack[2]):
                p.stop()

    def test_the_blocked_state_is_restored_after_the_context_exits(self):
        self.assertFalse(_md.provider_fetch_blocked())
        with _md.no_provider_fetch():
            self.assertTrue(_md.provider_fetch_blocked())
        self.assertFalse(_md.provider_fetch_blocked())

    def test_an_exception_does_not_leave_provider_fetching_blocked(self):
        with self.assertRaises(RuntimeError):
            with _md.no_provider_fetch():
                raise RuntimeError("boom")
        self.assertFalse(_md.provider_fetch_blocked())

    def test_nested_no_fetch_contexts_unwind_one_level_at_a_time(self):
        with _md.no_provider_fetch():
            with _md.no_provider_fetch():
                self.assertTrue(_md.provider_fetch_blocked())
            self.assertTrue(_md.provider_fetch_blocked())
        self.assertFalse(_md.provider_fetch_blocked())

    def test_the_blocked_state_does_not_leak_into_another_thread(self):
        import threading
        seen = []
        with _md.no_provider_fetch():
            t = threading.Thread(
                target=lambda: seen.append(_md.provider_fetch_blocked()))
            t.start()
            t.join()
        self.assertEqual(seen, [False])


# ---------------------------------------------------------------------------
# Local-read completeness recording — the signal the basis builder needs
# ---------------------------------------------------------------------------

class TestLocalReadRecording(_Base):

    def test_a_fully_covered_blocked_read_records_a_complete_local_read(self):
        self._seed_prices()
        with self._seams(arm=True)[2]:
            with _md.no_provider_fetch(), _md.record_local_reads() as reads:
                _pc.fetch_daily_cached("^TNX", period="3mo", auto_adjust=True)
        self.assertEqual([t for t, _ in reads], ["^TNX"])
        self.assertTrue(all(ok for _, ok in reads))

    def test_an_empty_cache_records_an_incomplete_local_read(self):
        with self._seams(arm=True)[2]:
            with _md.no_provider_fetch(), _md.record_local_reads() as reads:
                _pc.fetch_daily_cached("^TNX", period="3mo", auto_adjust=True)
        self.assertEqual([ok for _, ok in reads], [False])

    def test_a_partially_covered_cache_records_an_incomplete_local_read(self):
        # Rows stop ~40 business days short of the requested 3-month window.
        self._seed_prices(days=20, end=date.today() - timedelta(days=60))
        with self._seams(arm=True)[2]:
            with _md.no_provider_fetch(), _md.record_local_reads() as reads:
                _pc.fetch_daily_cached("^TNX", period="3mo", auto_adjust=True)
        self.assertEqual([ok for _, ok in reads], [False])

    def test_recording_is_inert_outside_its_context(self):
        self._seed_prices()
        with self._seams(arm=True)[2]:
            with _md.no_provider_fetch():
                # No recorder active — must not raise, must not accumulate.
                _pc.fetch_daily_cached("^TNX", period="3mo", auto_adjust=True)
        with _md.record_local_reads() as reads:
            pass
        self.assertEqual(reads, [])


# ---------------------------------------------------------------------------
# Required test 1-8 — the external boundary on the lookup path
# ---------------------------------------------------------------------------

class TestLookupPathTouchesNoProvider(_Base):

    def test_1_a_warm_durable_hit_makes_no_external_call_and_no_write(self):
        self._seed_prices()
        seeded = self._seed_saved_analysis()
        # Warm: the confirmed build left the macro TTL memo populated, so the
        # lookup answers entirely from process memory.
        self.assertTrue(_mc._cache_data)
        before = self._counts()
        resp = self._post({"headline": _HEADLINE}, arm=True,
                          extra=[self._stub_cached_response()]).json()
        self.assertEqual(resp.get("analysis_event_id"),
                         seeded["analysis_event_id"])
        self.assertEqual(self.provider_fetches, [])
        self.assertEqual(self.price_writes, [])
        self.assertEqual(self.analysis_calls, [])
        self.assertEqual(self._counts(), before)

    def test_2_a_cold_process_with_complete_local_prices_still_hits(self):
        self._seed_prices()
        seeded = self._seed_saved_analysis()
        _mc._cache_data.clear()          # cold in-process macro memo
        before = self._counts()
        resp = self._post({"headline": _HEADLINE}, arm=True,
                          extra=[self._stub_cached_response()]).json()
        self.assertEqual(resp.get("analysis_event_id"),
                         seeded["analysis_event_id"])
        self.assertEqual(self.provider_fetches, [])
        self.assertEqual(self.price_writes, [])
        self.assertEqual(self.analysis_calls, [])
        self.assertEqual(self._counts(), before)

    def test_3_partial_local_prices_report_the_basis_unavailable(self):
        self._seed_saved_analysis()
        _mc._cache_data.clear()
        self._seed_prices(days=20, end=date.today() - timedelta(days=60))
        before = self._counts()
        resp = self._post({"headline": _HEADLINE}, arm=True).json()
        self.assertEqual(resp.get("status"), "durable_lookup_basis_unavailable")
        self.assertEqual(self.provider_fetches, [])
        self.assertEqual(self.price_writes, [])
        self.assertEqual(self.analysis_calls, [])
        self.assertEqual(self._counts(), before)

    def test_4_no_local_prices_report_the_basis_unavailable(self):
        self._seed_saved_analysis()
        _mc._cache_data.clear()
        before = self._counts()
        resp = self._post({"headline": _HEADLINE}, arm=True).json()
        self.assertEqual(resp.get("status"), "durable_lookup_basis_unavailable")
        self.assertIs(resp.get("provider_called"), False)
        self.assertEqual(self.provider_fetches, [])
        self.assertEqual(self.price_writes, [])
        self.assertEqual(self._counts(), before)

    def test_5_an_armed_provider_is_never_touched_by_a_lookup(self):
        # arm=True raises on any reach; the assertion is that nothing raised
        # and the route returned a normal (non-500) payload.
        self._seed_prices()
        self._seed_saved_analysis()
        _mc._cache_data.clear()
        resp = self._post({"headline": _HEADLINE}, arm=True,
                          extra=[self._stub_cached_response()])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.provider_fetches, [])

    def test_6_an_unconfirmed_miss_performs_no_external_work(self):
        self._seed_prices()
        before = self._counts()
        resp = self._post({"headline": _OTHER}, arm=True).json()
        self.assertEqual(resp.get("status"), "paid_confirmation_required")
        self.assertEqual(self.provider_fetches, [])
        self.assertEqual(self.price_writes, [])
        self.assertEqual(self.analysis_calls, [])
        self.assertEqual(self._counts(), before)

    def test_7_the_legacy_headline_fallback_performs_no_external_work(self):
        self._seed_prices()
        legacy = _db.save_event({
            "headline": _OTHER, "stage": "breaking", "persistence": "transient",
            "event_date": _api.datetime.now().strftime("%Y-%m-%d"),
            "mechanism_summary": "stored", "what_changed": "stored",
            "confidence": "medium", "model": _api._active_model()})
        self.assertIsNotNone(legacy)
        _mc._cache_data.clear()
        before = self._counts()
        resp = self._post({"headline": _OTHER}, arm=True,
                          extra=[self._stub_cached_response()]).json()
        self.assertNotEqual(resp.get("status"), "paid_confirmation_required")
        self.assertEqual(len(self.served), 1)
        self.assertEqual(self.served[0].get("mechanism_summary"), "stored")
        self.assertEqual(self.provider_fetches, [])
        self.assertEqual(self.price_writes, [])
        self.assertEqual(self.analysis_calls, [])
        self.assertEqual(self._counts(), before)

    def test_8_a_numeric_lookup_builds_no_request_basis_at_all(self):
        seeded = self._seed_saved_analysis()
        eid = seeded["analysis_event_id"]
        basis_calls = []
        real = __import__("routes.analyze", fromlist=["x"])._build_request_basis

        def spy(*a, **k):
            basis_calls.append(1)
            return real(*a, **k)

        resp = self._post({"headline": _HEADLINE, "event_id": eid}, arm=True,
                          extra=[patch("routes.analyze._build_request_basis",
                                       spy)]).json()
        self.assertEqual(resp.get("analysis_event_id"), eid)
        self.assertEqual(basis_calls, [])


# ---------------------------------------------------------------------------
# The boundary this repair does NOT move
# ---------------------------------------------------------------------------

class TestRetrievalOverlayIsOutOfScope(_Base):
    """Serving a saved event recomputes live market overlays.

    That happens AFTER retrieval, inside ``_build_cached_response``, and a
    numeric ``event_id`` reopen has always paid it — it is pre-existing
    behaviour this repair deliberately leaves alone.  Pinning it here keeps
    the narrower assertions above honest: they stub the response builder
    because of THIS, not to hide a provider call on the lookup path.
    """

    def _fetches_by_phase(self, body):
        phase = {"v": "lookup"}
        by_phase = {"lookup": [], "response_builder": []}
        real = _api._build_cached_response

        def marked(*a, **k):
            phase["v"] = "response_builder"
            return real(*a, **k)

        class _Rec:
            def fetch_daily(_s, ticker, **kw):
                by_phase[phase["v"]].append(str(ticker))
                return None

            def fetch_info(_s, ticker):
                by_phase[phase["v"]].append(str(ticker))
                return {"symbol": ticker}

        stack = [patch("routes.analyze._call_analyze_event", self._analysis),
                 patch.object(_api, "market_check",
                              return_value={"note": "", "tickers": []}),
                 patch.object(_md, "_provider", _Rec()),
                 patch.object(_api, "_build_cached_response", marked)]
        for p in stack:
            p.start()
        try:
            resp = self.client.post("/analyze", json=body).json()
        finally:
            for p in reversed(stack):
                p.stop()
        return resp, by_phase

    def test_a_durable_hit_reaches_no_provider_until_the_response_is_built(self):
        self._seed_prices()
        seeded = self._seed_saved_analysis()
        _mc._cache_data.clear()
        resp, by_phase = self._fetches_by_phase({"headline": _HEADLINE})
        self.assertEqual(resp.get("analysis_event_id"),
                         seeded["analysis_event_id"])
        self.assertEqual(by_phase["lookup"], [])
        self.assertGreater(len(by_phase["response_builder"]), 0)

    def test_a_durable_reopen_costs_what_a_numeric_reopen_already_cost(self):
        """The reuse path must not be more expensive than reopening the same
        saved event by id — the cost is the shared, pre-existing overlay."""
        self._seed_prices()
        seeded = self._seed_saved_analysis()
        eid = seeded["analysis_event_id"]
        _mc._cache_data.clear()
        _, by_id = self._fetches_by_phase({"headline": _HEADLINE,
                                           "event_id": eid})
        _mc._cache_data.clear()
        _, by_hash = self._fetches_by_phase({"headline": _HEADLINE})
        self.assertEqual(by_id["lookup"], [])
        self.assertEqual(by_hash["lookup"], [])
        self.assertEqual(len(by_id["response_builder"]),
                         len(by_hash["response_builder"]))


# ---------------------------------------------------------------------------
# Required confirmed-run tests
# ---------------------------------------------------------------------------

class TestConfirmedRunRebuildsAndLooksUpAgain(_Base):

    def test_1_a_confirmed_run_may_refresh_and_hashes_the_refreshed_basis(self):
        """The confirmed basis is built on the normal (fetch-enabled) path."""
        macro_modes: list = []
        real_macro = _api.build_macro_context_for_prompt

        def spy_macro(*a, **k):
            macro_modes.append(_md.provider_fetch_blocked())
            return real_macro(*a, **k)

        self._post({"headline": _HEADLINE, "confirm_paid": True},
                   extra=[patch.object(_api, "build_macro_context_for_prompt",
                                       spy_macro)])
        # One blocked (read-only lookup) build, then one unblocked (confirmed).
        self.assertIn(True, macro_modes)
        self.assertIn(False, macro_modes)
        self.assertIs(macro_modes[-1], False)

    def test_2_the_second_lookup_reuses_a_saved_result_without_billing(self):
        """A refreshed basis that matches a saved one must not bill again."""
        self._seed_prices()
        seeded = self._seed_saved_analysis()
        _mc._cache_data.clear()
        # Local basis is complete, so the FIRST lookup already hits; force the
        # second-lookup path by making only the read-only build unavailable.
        before = self._counts()
        resp = self._post({"headline": _HEADLINE, "confirm_paid": True},
                          extra=[patch("routes.analyze._read_only_macro_context",
                                       lambda: ("", False))]).json()
        self.assertEqual(resp.get("analysis_event_id"),
                         seeded["analysis_event_id"])
        self.assertEqual(self.analysis_calls, [])
        self.assertEqual(self._counts(), before)

    def test_3_a_genuine_final_miss_calls_the_provider_exactly_once(self):
        self._seed_prices()
        resp = self._post({"headline": _OTHER, "confirm_paid": True}).json()
        self.assertEqual(len(self.analysis_calls), 1)
        eid = resp["analysis_event_id"]
        conn = sqlite3.connect(self._tmp)
        try:
            row = conn.execute(
                "SELECT request_hash FROM analysis_request_cache"
                " WHERE analysis_event_id = ?", (eid,)).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(len(row[0]), 64)

    def test_4_a_confirmed_macro_failure_fails_visibly_without_billing(self):
        before = self._counts()
        resp = self._post({"headline": _OTHER, "confirm_paid": True},
                          extra=[patch.object(
                              _api, "build_macro_context_for_prompt",
                              side_effect=RuntimeError("macro down"))]).json()
        self.assertEqual(resp.get("status"), "analysis_basis_unavailable")
        self.assertEqual(self.analysis_calls, [])
        self.assertEqual(self._counts(), before)

    def test_5_a_changed_refreshed_macro_context_changes_the_request_hash(self):
        """A refresh that moves the backdrop must not reuse the old result."""
        import routes.analyze as _ra
        today = _api.datetime.now().strftime("%Y-%m-%d")
        hashes = []
        for backdrop in ("Macro backdrop: A", "Macro backdrop: B"):
            with patch.object(_api, "build_macro_context_for_prompt",
                              return_value=backdrop):
                built = _ra._build_request_basis(
                    _HEADLINE, "", today, mode=_ra.BASIS_CONFIRMED_FRESH_RUN)
            self.assertEqual(built.status, _ra.BASIS_COMPLETE)
            hashes.append(built.hash)
        self.assertEqual(len(set(hashes)), 2)
        # And the durable cache must not answer one basis with the other.
        self._post({"headline": _HEADLINE, "confirm_paid": True},
                   extra=[patch.object(_api, "build_macro_context_for_prompt",
                                       return_value="Macro backdrop: A")])
        self.assertIsNone(_db.find_event_id_by_request_hash(hashes[1]))
        self.assertIsNotNone(_db.find_event_id_by_request_hash(hashes[0]))

    def test_6_both_routes_report_the_same_unavailable_state(self):
        self._seed_saved_analysis()
        _mc._cache_data.clear()
        plain = self._post({"headline": _HEADLINE}, arm=True).json()
        _mc._cache_data.clear()
        streamed = self._post({"headline": _HEADLINE}, path="/analyze/stream",
                              arm=True)
        self.assertEqual(plain.get("status"), "durable_lookup_basis_unavailable")
        self.assertIn("durable_lookup_basis_unavailable", streamed.text)

    def test_6b_the_streamed_unavailable_state_is_a_valid_terminal_payload(self):
        """Not a truncated stream: the terminal frame must satisfy the
        frontend's fail-closed validator (analysis_failed + failure_reason +
        market record + headline + is_mock + event_date)."""
        import json as _json
        self._seed_saved_analysis()
        _mc._cache_data.clear()
        raw = self._post({"headline": _HEADLINE}, path="/analyze/stream",
                         arm=True).text
        frames = [_json.loads(line[6:]) for line in raw.splitlines()
                  if line.startswith("data: ")]
        terminal = [f for f in frames if f.get("_phase") == "complete"]
        self.assertEqual(len(terminal), 1)
        payload = terminal[0]
        self.assertEqual(payload.get("status"),
                         "durable_lookup_basis_unavailable")
        self.assertIs(payload.get("analysis_failed"), True)
        self.assertIsInstance(payload.get("failure_reason"), str)
        self.assertTrue(payload["failure_reason"])
        self.assertIsInstance(payload.get("market"), dict)
        self.assertIsInstance(payload.get("headline"), str)
        self.assertIs(payload.get("is_mock"), False)

    def test_6c_an_unavailable_lookup_is_not_permission_to_run_paid_work(self):
        """A1-1 regression: the new state must be as inert as the
        confirmation gate it sits beside — no provider, no row, no linkage."""
        from event_inbox import candidate_event_id
        from news_sources import _dedup_key
        key = _dedup_key(_OTHER)
        before = self._counts()
        resp = self._post({"headline": _OTHER,
                           "candidate_id": candidate_event_id(4242, key),
                           "parent_cluster_id": 4242, "title_key": key},
                          arm=True).json()
        self.assertEqual(resp.get("status"), "durable_lookup_basis_unavailable")
        self.assertIsNone(resp.get("analysis_event_id"))
        self.assertIsNone(resp.get("candidate_link"))
        self.assertEqual(self.analysis_calls, [])
        self.assertEqual(self._counts(), before)

    def test_7_the_unavailable_state_discloses_no_internals(self):
        self._seed_saved_analysis()
        _mc._cache_data.clear()
        resp = self._post({"headline": _HEADLINE}, arm=True).json()
        blob = repr(resp).lower()
        for leak in (".db", "sqlite", "traceback", "c:\\", "/users/",
                     "api_key", "password"):
            self.assertNotIn(leak, blob)


# ---------------------------------------------------------------------------
# The confirmed basis must stay byte-identical to pre-repair A1-4
# ---------------------------------------------------------------------------

class TestConfirmedBasisUnchanged(_Base):

    def test_the_read_only_pass_leaves_the_shared_macro_memo_untouched(self):
        """Otherwise the confirmed build would silently reuse the cache-only
        frames the lookup pass memoized, and the billed prompt would differ
        from what A1-4 sent."""
        self._seed_prices()
        _mc._cache_data.clear()
        stack = self._seams(arm=True)
        for p in stack:
            p.start()
        try:
            import routes.analyze as _ra
            _ra._read_only_macro_context()
        finally:
            for p in reversed(stack):
                p.stop()
        self.assertEqual(list(_mc._cache_data.keys()), [])

    def test_a_warm_memo_entry_is_preserved_by_the_read_only_pass(self):
        self._seed_prices()
        _mc._cache_data.clear()
        _mc._cache_set("fetch:^TNX", _frame(120))
        stack = self._seams(arm=True)
        for p in stack:
            p.start()
        try:
            import routes.analyze as _ra
            _ra._read_only_macro_context()
        finally:
            for p in reversed(stack):
                p.stop()
        self.assertIn("fetch:^TNX", _mc._cache_data)


if __name__ == "__main__":
    unittest.main()
