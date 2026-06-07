"""Invariant: no GET route invokes a paid/provider seam.

This test boots the FastAPI app under the riskiest configuration —
``ENABLE_AUTO_BACKFILL=true`` and ``ENABLE_PAID_ANALYSIS=true`` — patches
the documented paid/provider seams to raise, swaps ``db.DB_FILE`` to a
fresh temp DB seeded with one synthetic event, enumerates every GET
route on ``api.app``, hits each one (with synthetic path / query
params where needed), and asserts:

  * the strictly-forbidden seams (``api.analyze_event``,
    ``api.market_check``, ``auto_backfill_runner.execute_paid_candidate``)
    are NEVER invoked by any GET route,
  * the provider seams (``yfinance.download``, ``yfinance.Ticker``) are
    only invoked by routes on the documented allow-list — every other
    GET route must not call them,
  * no GET request spawned a thread (no scheduler started by request
    handling),
  * importing ``api`` / ``auto_backfill_runner`` /
    ``auto_backfill_scheduler`` / ``yfinance`` did not spawn a thread,
  * ``GET /diagnostics/auto-backfill-status`` reports
    ``scheduler.scheduler_started == false`` regardless of the env gates
    being on (FastAPI lifespan wiring is out of scope for this test —
    the TestClient is used without the ``with`` context, so no lifespan
    runs and no scheduler is attached).

The patched seams are exactly those listed by the contract:

  * ``api.analyze_event``
  * ``api.market_check``
  * ``yfinance.download``
  * ``yfinance.Ticker``
  * ``auto_backfill_runner.execute_paid_candidate``

Caveat: ``api.analyze_event`` and ``api.market_check`` are patched on
``api``'s module namespace.  Calls that flow through sub-router
``from market_check import ...`` bindings have their own independent
references and are therefore out of scope for this invariant — the
contract pins the listed seams.

About the seeded event
----------------------
``setUpClass`` saves one event with non-trivial ``market_tickers``
into a fresh temp DB so routes that need archive state (``/events/*``,
``/events/{event_id}/backtest``, ``/events/export``) actually reach
their handler bodies instead of returning 404 on an empty archive.
The seeded event uses an ``event_date`` 60 days in the past so the
backtest's freshness layer is past its frozen cutoff — combined with
``?force=true``, this drives ``/events/{event_id}/backtest`` through
the cold-cache market_check path that yfinance backs.

About the yfinance allow-list
-----------------------------
A handful of read-only market-data routes (``/macro``, ``/stress``,
``/rates-context``, ``/snapshots``, ``/ticker/{symbol}/chart``,
``/ticker/{symbol}/info``, ``/events/{event_id}/backtest``) call
``yfinance.download`` / ``yfinance.Ticker`` to top up
``price_cache.fetch_daily_cached`` on a cache miss.  This is
documented behaviour — see ``docs/local_operations_runbook.md``
§"Archive Rebuild Script — Safety Model" for the same cache-warming
contract on the rebuild path.  yfinance is a free RSS-style data
source rather than a paid LLM seam, but the contract still asks us
to pin every call site.  The allow-list below names each route +
seam pair with a rationale; any new caller will fail the invariant
test loudly until the operator decides whether the new call site is
correct.

About the market_data.get_provider allow-list
---------------------------------------------
``market_data.get_provider`` is the factory that hands out the
currently-active ``MarketDataProvider``.  It is not itself a paid
network call — the paid calls live inside the returned provider's
methods, and those (``yfinance.download`` / ``yfinance.Ticker``) are
already tracked above — but it is a documented dispatch seam and the
``no_paid_smoke`` / runbook treats it as one, so this test tracks it
under the same allow-list discipline as yfinance.

Two practical wrinkles drive the patching here:

* ``market_universe`` and ``market_snapshots`` both pull ``get_provider``
  in at module-load time via ``from market_data import get_provider``.
  Once either module is loaded in the test process the function lives
  under three names.  We patch all three with the SAME ``MagicMock``
  so the call is attributed to one logical target,
  ``"market_data.get_provider"``.
* ``scripts/no_paid_smoke.py``'s ``guard_no_paid_provider_calls()``
  patches ``market_data.get_provider`` with a ``RuntimeError`` raiser
  for the duration of the smoke run.  If ``market_universe`` /
  ``market_snapshots`` are lazy-imported during that window
  (e.g., by ``tests/test_auto_backfill_scheduler_smoke.py`` running
  earlier in the same process), they capture the raiser via the
  ``from market_data import get_provider`` alias and the guard's
  cleanup only restores the canonical ``market_data`` attribute —
  leaving the raiser stranded as ``market_universe.get_provider`` /
  ``market_snapshots.get_provider``.  ``setUpClass`` force-rebinds
  every known shadow back to the live original BEFORE applying our
  patches; this is the heal that keeps the suite order-independent.

The proxy mock returns the real provider via a thin lambda so the
allow-listed routes (e.g., ``/macro``, ``/snapshots``) keep
functioning end-to-end; the actual paid surface is still gated by
the strict yfinance raisers.
"""

from __future__ import annotations

import os
import sys
import threading
import unittest
from typing import Any
from unittest import mock


# ---------------------------------------------------------------------------
# Module-level boot — env gates flipped ON BEFORE any product import.
# ---------------------------------------------------------------------------

os.environ["ENABLE_AUTO_BACKFILL"] = "true"
os.environ["ENABLE_PAID_ANALYSIS"] = "true"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Capture the live thread set before importing ``api``.  Subsequent
# snapshots compare against this baseline so the assertion is order-
# independent (a later test that started a real scheduler cannot pollute
# this baseline because both snapshots are taken at module-load time).
_THREADS_BEFORE_API_IMPORT: set[str] = {
    (t.name or "").lower() for t in threading.enumerate()
}

import api                        # noqa: E402
import auto_backfill_runner       # noqa: E402
import auto_backfill_scheduler    # noqa: E402
import db                         # noqa: E402
import yfinance                   # noqa: E402

_THREADS_AFTER_API_IMPORT: set[str] = {
    (t.name or "").lower() for t in threading.enumerate()
}


# ---------------------------------------------------------------------------
# Per-route synthesis — chosen by probing each route once under the
# patched-seam guard and confirming the response is in the safe-status
# set (200/304/400/404/422).  Anything 5xx would imply a paid seam was
# reached or the handler crashed before its no-paid guard.
# ---------------------------------------------------------------------------

_PATH_PARAM_SUBS: dict[str, str] = {
    "event_id": "1",
    "symbol":   "AAPL",
    "study_id": "1",
}

_QUERY_PARAM_SUBS: dict[str, str] = {
    "/ticker/{symbol}/chart":         "?event_date=2025-01-15",
    "/portfolio/cohort-comparison":   "?a=cohort1&b=cohort2",
    # ``force=true`` bypasses the freshness layer's frozen cutoff so the
    # backtest probe reliably hits the cold-cache market_check path —
    # the same path that drives the yfinance.download calls captured
    # by the allow-list entry below.
    "/events/{event_id}/backtest":    "?force=true",
}

_SAFE_STATUS_CODES: frozenset[int] = frozenset({200, 304, 400, 404, 422})

# No routes are skipped: probing showed every current GET route is
# reachable with synthetic parameters.  If a future addition needs
# server-side state to render, list it here with a one-line rationale.
_DOCUMENTED_SKIPS: dict[str, str] = {}

# Patch targets — listed exactly as in the contract.
_PAID_SEAM_TARGETS: tuple[str, ...] = (
    "api.analyze_event",
    "api.market_check",
    "yfinance.download",
    "yfinance.Ticker",
    "auto_backfill_runner.execute_paid_candidate",
    "market_data.get_provider",
)

# Strictly-forbidden seams: ZERO calls allowed from any GET route.
_STRICT_FORBIDDEN_TARGETS: frozenset[str] = frozenset({
    "api.analyze_event",
    "api.market_check",
    "auto_backfill_runner.execute_paid_candidate",
})

# Provider-factory seam.  Patched non-raising (the proxy returns the
# live provider) so allow-listed routes keep functioning; tracked as a
# normal allow-list target via ``_KNOWN_PAID_SEAM_CALLERS`` below.
_PROVIDER_PROXY_TARGET: str = "market_data.get_provider"

# Shadow bindings created by ``from market_data import get_provider``
# at module-load time.  We force-rebind these back to the live
# original in setUpClass, then patch each with the same proxy mock so
# calls are attributed to the canonical target regardless of which
# alias the caller resolved through.
_PROVIDER_PROXY_SHADOW_BINDINGS: tuple[str, ...] = (
    "market_universe.get_provider",
    "market_snapshots.get_provider",
)

# Provider seams that MAY be called only by the documented allow-list
# below.  Every (route, target) pair carries a rationale string.
_KNOWN_PAID_SEAM_CALLERS: dict[tuple[str, str], str] = {
    ("/macro", "yfinance.download"): (
        "macro snapshot warms price_cache.fetch_daily_cached on a cold "
        "yield-curve / credit-tape window"
    ),
    ("/stress", "yfinance.download"): (
        "stress-regime composer fetches the macro tape "
        "(^TNX, ^FVX, ^TYX, TIP, HYG, LQD, SHY) on cache miss"
    ),
    ("/rates-context", "yfinance.download"): (
        "rates-context composer fetches yield-curve series on cache miss"
    ),
    ("/snapshots", "yfinance.download"): (
        "snapshot composer warms the macro tape via fetch_daily_cached"
    ),
    ("/market-context", "yfinance.download"): (
        "market-context composes snapshots + stress + rates and triggers a "
        "cold-start auto-warm via _padded_snapshots_payload(refresh_if_empty=True); "
        "the warm-up flows into fetch_daily_cached on cache miss"
    ),
    ("/ticker/{symbol}/chart", "yfinance.download"): (
        "ticker chart fetches OHLC on cache miss for the requested symbol"
    ),
    ("/ticker/{symbol}/info", "yfinance.Ticker"): (
        "ticker info reads ticker metadata via yfinance.Ticker on cache miss"
    ),
    ("/events/{event_id}/backtest", "yfinance.download"): (
        "backtest re-runs the freshness-aware market_check pipeline for "
        "the event's tickers; under ?force=true (or a stale cache) the "
        "fetch falls through to fetch_daily_cached → yfinance.download. "
        "No paid LLM seam is involved on this path."
    ),
    # ``market_data.get_provider`` — factory that returns the active
    # ``MarketDataProvider``.  Allow-listed for every route that
    # transitively resolves a liquid-market identifier through
    # ``market_universe.resolve_symbol → _provider_kind → get_provider()``
    # or that constructs a provider-specific symbol map via
    # ``market_snapshots.get_provider()``.  The factory itself never
    # touches the network — the paid surface is the provider methods,
    # which are independently gated by the yfinance.* raisers above.
    ("/macro", "market_data.get_provider"): (
        "macro snapshot resolves liquid-market identifiers via "
        "market_universe.resolve_symbol → _provider_kind → get_provider() "
        "to pick the active provider's preferred ticker for each "
        "instrument on the macro tape (DXY, 10Y, CL, ...)"
    ),
    ("/stress", "market_data.get_provider"): (
        "stress-regime composer resolves yield-curve / credit-tape "
        "symbols via market_universe → _provider_kind → get_provider() "
        "before dispatching the cold-cache fetch"
    ),
    ("/rates-context", "market_data.get_provider"): (
        "rates-context composer resolves yield-curve symbols via "
        "market_universe → _provider_kind → get_provider() before "
        "the cold-cache fetch"
    ),
    ("/snapshots", "market_data.get_provider"): (
        "snapshots composer (market_snapshots.py) calls get_provider() "
        "to pick provider-specific ETFs/futures and to dispatch the "
        "fetch on cache miss"
    ),
    ("/market-context", "market_data.get_provider"): (
        "market-context composes snapshots + stress + rates; each leg "
        "resolves its symbol set via market_universe → _provider_kind "
        "→ get_provider() on cache miss"
    ),
    ("/ticker/{symbol}/chart", "market_data.get_provider"): (
        "ticker chart resolves liquid-market symbols via market_universe "
        "→ _provider_kind → get_provider() before dispatching the OHLC "
        "fetch"
    ),
    ("/ticker/{symbol}/info", "market_data.get_provider"): (
        "ticker info reads provider metadata via market_universe → "
        "_provider_kind → get_provider() so the right symbol alphabet "
        "is queried"
    ),
    ("/events/{event_id}/backtest", "market_data.get_provider"): (
        "backtest re-runs market_check for the event's tickers; under "
        "?force=true the cold-cache path resolves provider-specific "
        "symbols via market_universe → _provider_kind → get_provider() "
        "before dispatching the historical fetch"
    ),
}


def _build_url(template: str) -> str:
    """Substitute ``{name}`` placeholders and append documented query
    params, returning a request URL the TestClient can hit.
    """
    url = template
    for name, value in _PATH_PARAM_SUBS.items():
        url = url.replace("{" + name + "}", value)
    query = _QUERY_PARAM_SUBS.get(template, "")
    return url + query


def _enumerate_get_routes() -> list[str]:
    routes: list[str] = []
    for r in api.app.routes:
        methods = getattr(r, "methods", None) or set()
        if "GET" in methods:
            routes.append(r.path)
    return routes


# ---------------------------------------------------------------------------
# Single shared probe — every test inspects the captured results so the
# routes are only hit once per test run.
# ---------------------------------------------------------------------------


class TestNoPaidGetRoutes(unittest.TestCase):
    """Boot once, probe every GET route once, assert the invariants."""

    _patches: list[Any] = []
    _mocks: dict[str, Any] = {}
    _client: Any = None
    # results[i] = (path, status_or_kind, calls_per_target)
    _results: list[tuple[str, Any, dict[str, int]]] = []
    _threads_after_gets: set[str] = set()
    _orig_db_file: str = ""
    _tmp_db_path: str = ""
    _seeded_event_id: int = 1

    @classmethod
    def setUpClass(cls) -> None:
        # Re-assert the env gates here in case earlier tests in the same
        # process clobbered them.  ``load_auto_backfill_config`` reads
        # ``os.environ`` per request, so this is the load-bearing flip.
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        os.environ["ENABLE_PAID_ANALYSIS"] = "true"

        # Heal any leak from a prior test in the same process before
        # patching.  ``scripts/no_paid_smoke.py``'s
        # ``guard_no_paid_provider_calls`` patches
        # ``market_data.get_provider`` with a ``RuntimeError`` raiser
        # for the duration of its with-block; if ``market_universe`` /
        # ``market_snapshots`` were lazy-imported during that window
        # they captured the raiser via the ``from market_data import
        # get_provider`` alias and the guard's cleanup only restored
        # the canonical ``market_data`` attribute.  Force-rebind every
        # known shadow back to the live original so our patches start
        # from a clean baseline regardless of test order.
        import importlib
        import market_data
        for shadow in _PROVIDER_PROXY_SHADOW_BINDINGS:
            mod_name, attr_name = shadow.rsplit(".", 1)
            if mod_name not in sys.modules:
                # Force-import so the binding exists with the right
                # value before we patch (and so a future test cannot
                # observe a half-resolved shadow).
                importlib.import_module(mod_name)
            setattr(
                sys.modules[mod_name], attr_name, market_data.get_provider,
            )

        # Patch every paid/provider seam.  Strict targets get a raiser
        # so any unexpected call fails the request loudly; the
        # provider-factory target gets a non-raising proxy mock so
        # allow-listed routes keep functioning.  Both flavours land in
        # ``cls._mocks`` so the per-route call counts feed the same
        # allow-list invariant.
        cls._patches = []
        cls._mocks = {}
        for target in _PAID_SEAM_TARGETS:
            if target == _PROVIDER_PROXY_TARGET:
                continue
            patcher = mock.patch(
                target,
                side_effect=AssertionError(
                    f"paid seam {target!r} called under no-paid GET test"
                ),
            )
            mock_obj = patcher.start()
            cls._patches.append(patcher)
            cls._mocks[target] = mock_obj

        # Provider-factory proxy: one ``MagicMock`` shared across the
        # canonical attribute and every shadow binding so a call
        # through any alias is attributed to the same logical target.
        # ``side_effect=lambda: real_get_provider()`` keeps the routes
        # functional — they receive the real provider object — while
        # the mock records the call count.
        real_get_provider = market_data.get_provider
        provider_proxy_mock = mock.MagicMock(
            side_effect=lambda: real_get_provider(),
            name=_PROVIDER_PROXY_TARGET,
        )
        for binding in (_PROVIDER_PROXY_TARGET,) + _PROVIDER_PROXY_SHADOW_BINDINGS:
            patcher = mock.patch(binding, new=provider_proxy_mock)
            patcher.start()
            cls._patches.append(patcher)
        cls._mocks[_PROVIDER_PROXY_TARGET] = provider_proxy_mock

        # Swap to a fresh temp DB so the probe is hermetic and seed a
        # single event whose backtest path will exercise the cold-cache
        # market_check pipeline once ``?force=true`` bypasses the
        # freshness cutoff.
        import tempfile
        import uuid
        cls._orig_db_file = db.DB_FILE
        cls._tmp_db_path = os.path.join(
            tempfile.gettempdir(),
            f"test_no_paid_get_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = cls._tmp_db_path
        db._db_ready = False
        db.init_db()
        cls._seeded_event_id = cls._seed_event()
        # Update path-param substitution so the parametric event routes
        # use the seeded id rather than a hard-coded ``1`` (the latter
        # could collide if the temp DB ever skips id=1).
        _PATH_PARAM_SUBS["event_id"] = str(cls._seeded_event_id)

        # TestClient is constructed AFTER the patches and the DB seeding
        # are in place so any startup hook attached to the app (none
        # today, but defensively) runs under the no-paid guard.  The
        # client is NOT used as a context manager: lifespan wiring is
        # exercised by tests/test_auto_backfill_lifespan_wiring.py.
        from fastapi.testclient import TestClient
        cls._client = TestClient(api.app)

        # Drive every GET route once.  Reset every mock between requests
        # so the per-route call delta is exact.
        cls._results = []
        for path in _enumerate_get_routes():
            if path in _DOCUMENTED_SKIPS:
                cls._results.append((path, "SKIP", {}))
                continue
            for mock_obj in cls._mocks.values():
                mock_obj.reset_mock()
            url = _build_url(path)
            try:
                response = cls._client.get(url)
                status: Any = response.status_code
            except Exception as exc:
                status = f"EXC:{type(exc).__name__}: {exc}"
            calls: dict[str, int] = {
                target: m.call_count
                for target, m in cls._mocks.items()
                if m.call_count > 0
            }
            cls._results.append((path, status, calls))

        cls._threads_after_gets = {
            (t.name or "").lower() for t in threading.enumerate()
        }

    @classmethod
    def tearDownClass(cls) -> None:
        for patcher in cls._patches:
            patcher.stop()
        # Restore the original DB pointer and remove the temp file.
        db.DB_FILE = cls._orig_db_file
        db._db_ready = False
        try:
            os.remove(cls._tmp_db_path)
        except (OSError, PermissionError):
            pass

    @staticmethod
    def _seed_event() -> int:
        """Save one synthetic event with non-trivial market_tickers and
        an event_date 60 days in the past so the backtest freshness
        layer is past its frozen cutoff.  Returns the saved row id.
        """
        from datetime import datetime, timedelta, timezone
        event_date = (
            datetime.now(timezone.utc) - timedelta(days=60)
        ).date().isoformat()
        record = {
            "headline":           "No-paid invariant probe event",
            "stage":              "realized",
            "persistence":        "structural",
            "what_changed":       "synthetic",
            "mechanism_summary":  "A → B",
            "beneficiaries":      ["Alpha Corp"],
            "losers":             ["Beta Corp"],
            "assets_to_watch":    ["AAPL", "MSFT"],
            "confidence":         "medium",
            "market_note":        "synthetic",
            "market_tickers": [
                {
                    "symbol":     "AAPL",
                    "role":       "beneficiary",
                    "return_1d":  0.5,
                    "return_5d":  1.2,
                    "return_20d": 3.8,
                    "direction":  "supports thesis",
                },
                {
                    "symbol":     "MSFT",
                    "role":       "loser",
                    "return_1d":  -0.1,
                    "return_5d":  -2.5,
                    "return_20d": -1.0,
                    "direction":  "contradicts thesis",
                },
            ],
            "event_date":         event_date,
            "notes":              "synthetic",
            "model":              "claude-test",
            "transmission_chain": ["a", "b"],
            "if_persists":        {"horizon": "weeks"},
            "currency_channel":   {"pair": "USDJPY"},
            "policy_sensitivity": {"stance": "neutral"},
            "inventory_context":  {"status": "tight"},
            "low_signal":         0,
        }
        db.save_event(record)
        return db.load_recent_events(limit=1)[0]["id"]

    # ------------------------------------------------------------------
    # Invariants
    # ------------------------------------------------------------------

    def test_env_gates_are_on(self) -> None:
        """The contract requires the riskiest config so the test
        actually exercises the paid-decision branches.
        """
        self.assertEqual(os.environ.get("ENABLE_AUTO_BACKFILL"), "true")
        self.assertEqual(os.environ.get("ENABLE_PAID_ANALYSIS"), "true")

    def test_module_import_did_not_spawn_threads(self) -> None:
        new_threads = _THREADS_AFTER_API_IMPORT - _THREADS_BEFORE_API_IMPORT
        self.assertEqual(
            new_threads, set(),
            "importing api / auto_backfill_runner / auto_backfill_scheduler "
            f"/ yfinance spawned threads: {new_threads}",
        )

    def test_get_routes_were_enumerated(self) -> None:
        # Sanity — both that we have routes and that the probe ran.
        self.assertGreater(len(self._results), 0)
        # Distinct paths on every result.
        paths = [path for path, _, _ in self._results]
        self.assertEqual(len(paths), len(set(paths)))

    def test_all_get_routes_return_non_5xx(self) -> None:
        offenders: list[str] = []
        for path, status, _calls in self._results:
            if status == "SKIP":
                continue
            if isinstance(status, str) and status.startswith("EXC:"):
                offenders.append(f"{path} -> {status}")
                continue
            if isinstance(status, int) and status not in _SAFE_STATUS_CODES:
                offenders.append(f"{path} -> HTTP {status}")
        self.assertEqual(
            offenders, [],
            "GET routes returned non-safe statuses (expected one of "
            f"{sorted(_SAFE_STATUS_CODES)}):\n  " + "\n  ".join(offenders),
        )

    def test_strict_forbidden_seams_have_zero_calls(self) -> None:
        """``api.analyze_event``, ``api.market_check``, and
        ``auto_backfill_runner.execute_paid_candidate`` MUST NOT be
        invoked by ANY GET route.  No allow-list applies — these are the
        load-bearing paid-LLM and paid-stub seams.
        """
        violations: list[str] = []
        for path, _status, calls in self._results:
            for target, count in calls.items():
                if target in _STRICT_FORBIDDEN_TARGETS:
                    violations.append(
                        f"{path} -> {target} (call_count={count})"
                    )
        self.assertEqual(
            violations, [],
            "strictly-forbidden paid seams were invoked by GET routes:\n  "
            + "\n  ".join(violations),
        )

    def test_provider_seams_only_called_by_known_routes(self) -> None:
        """``yfinance.download`` / ``yfinance.Ticker`` may be called only
        by routes on ``_KNOWN_PAID_SEAM_CALLERS``.  Any other GET route
        that triggers a yfinance call is a violation — either a real
        regression or a new caller that needs a rationale entry on the
        allow-list.
        """
        violations: list[str] = []
        for path, _status, calls in self._results:
            for target, count in calls.items():
                if target in _STRICT_FORBIDDEN_TARGETS:
                    # Covered by ``test_strict_forbidden_seams_have_zero_calls``.
                    continue
                if (path, target) in _KNOWN_PAID_SEAM_CALLERS:
                    continue
                violations.append(
                    f"{path} -> {target} (call_count={count}) — not on "
                    f"the allow-list"
                )
        self.assertEqual(
            violations, [],
            "provider seams were called by routes outside the allow-list:\n  "
            + "\n  ".join(violations),
        )

    def test_known_paid_seam_callers_have_rationale(self) -> None:
        """Forward-guard: every entry on ``_KNOWN_PAID_SEAM_CALLERS``
        must carry a non-empty rationale string.  Prevents silent
        additions to the allow-list.
        """
        for (path, target), reason in _KNOWN_PAID_SEAM_CALLERS.items():
            self.assertIsInstance(path, str)
            self.assertIn(target, _PAID_SEAM_TARGETS)
            self.assertTrue(
                isinstance(reason, str) and reason.strip(),
                f"allow-list entry ({path!r}, {target!r}) is missing a rationale",
            )

    def test_no_thread_spawned_by_get_calls(self) -> None:
        new_threads = self._threads_after_gets - _THREADS_AFTER_API_IMPORT
        self.assertEqual(
            new_threads, set(),
            f"GET requests spawned threads: {new_threads}",
        )

    def test_scheduler_status_reports_not_started(self) -> None:
        """Even with both env gates on, the FastAPI lifespan wiring that
        would construct a live scheduler has not landed yet, so the
        diagnostics block must still report ``scheduler_started=false``.
        """
        response = self._client.get("/diagnostics/auto-backfill-status")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        scheduler_block = body.get("scheduler") or {}
        self.assertFalse(
            scheduler_block.get("scheduler_started", True),
            f"scheduler_started should be False; got {scheduler_block!r}",
        )
        self.assertEqual(
            scheduler_block.get("mode"), "not_wired",
            f"scheduler.mode should be 'not_wired'; got {scheduler_block!r}",
        )

    def test_documented_skips_have_rationale(self) -> None:
        """Any route the suite chooses to skip must carry a non-empty
        rationale string.  Today the skip list is empty; the test still
        runs as a forward-guard against silent additions.
        """
        for path, reason in _DOCUMENTED_SKIPS.items():
            self.assertTrue(
                isinstance(reason, str) and reason.strip(),
                f"documented skip for {path!r} is missing a rationale",
            )


class TestRoutesDirectoryFullyMounted(unittest.TestCase):
    """Regression: every GET path declared on a router under ``routes/``
    must be mounted on ``api.app``.

    ``test_no_paid_get_routes`` enumerates ``api.app.routes`` to drive
    its probe — so a router that exists on disk but is missing from the
    ``app.include_router(...)`` block in ``api.py`` would silently slip
    past every no-paid invariant.  The check here walks ``routes/*.py``,
    imports each module, inspects its ``router`` attribute, and asserts
    every declared GET path also appears on ``api.app``.  Catches
    mounting drift (a new diagnostics router added under ``routes/`` but
    not wired into ``api.py``) before it can surface in production —
    pure read, no DB writes, no provider/yfinance/LLM, no production
    code touched.
    """

    def test_every_get_route_in_routes_dir_is_mounted_on_app(self) -> None:
        import importlib
        import pathlib

        from fastapi import APIRouter

        routes_dir = pathlib.Path(__file__).resolve().parents[1] / "routes"
        self.assertTrue(
            routes_dir.is_dir(),
            f"expected routes/ dir at {routes_dir}, not found",
        )

        on_disk: dict[str, str] = {}
        scanned_modules: list[str] = []
        for py_file in sorted(routes_dir.glob("*.py")):
            if py_file.name == "__init__.py":
                continue
            module_name = f"routes.{py_file.stem}"
            module = importlib.import_module(module_name)
            scanned_modules.append(module_name)
            router = getattr(module, "router", None)
            if not isinstance(router, APIRouter):
                continue
            for route in router.routes:
                methods = getattr(route, "methods", None) or set()
                if "GET" not in methods:
                    continue
                path = getattr(route, "path", None)
                if path:
                    on_disk.setdefault(path, module_name)

        # Sanity — at least one router module was actually scanned, so a
        # silent collapse of the routes/ tree (e.g., a refactor that
        # accidentally moves every router elsewhere) doesn't make this
        # regression test pass vacuously.
        self.assertGreater(
            len(scanned_modules), 0,
            "no routes/*.py modules were scanned — refusing to pass "
            "the mount-coverage check vacuously",
        )
        self.assertGreater(
            len(on_disk), 0,
            "no GET paths discovered across scanned routers — refusing "
            "to pass the mount-coverage check vacuously",
        )

        mounted = set(_enumerate_get_routes())
        missing = sorted(
            f"{path} (declared in {module_name}, not mounted on api.app)"
            for path, module_name in on_disk.items()
            if path not in mounted
        )
        self.assertEqual(
            missing, [],
            "Routers exist under routes/ but their GET paths are not "
            "mounted on api.app — wire them in via app.include_router(...):"
            "\n  " + "\n  ".join(missing),
        )

    def test_archive_consistency_route_is_mounted(self) -> None:
        # Explicit pin for the route this regression was added to guard.
        # Dynamic enumeration already covers it via app.routes, but the
        # named assertion gives a precise failure message if the
        # ``include_router`` line for ``archive_diagnostics`` is dropped.
        self.assertIn(
            "/diagnostics/archive-consistency",
            set(_enumerate_get_routes()),
            "GET /diagnostics/archive-consistency is missing from the "
            "mounted route inventory — restore the include_router(...) "
            "wiring in api.py for routes.archive_diagnostics",
        )


class TestNoRouteBypassesPaidSeam(unittest.TestCase):
    """Defense-in-depth for the ``api.*`` patch gap (Q1 L1).

    The no-paid invariant above patches ``api.analyze_event`` /
    ``api.market_check`` on the ``api`` module namespace.  A route that bound
    the paid callables directly — ``from market_check import market_check`` or
    a dotted call on any module other than ``_api`` / ``api`` — would hold its
    own reference and bypass that patch.  This static AST check pins that
    every ``routes/*.py`` reaches the paid callables ONLY through the
    ``_api.`` / ``api.`` seam, so the runtime invariant can never be silently
    out-flanked.  Pure source analysis: no app boot, no DB, no network.
    """

    _PAID_CALLABLES = ("market_check", "analyze_event")
    _ALLOWED_BASES = ("_api", "api")

    @classmethod
    def _offenders(cls, src: str, label: str) -> list[str]:
        import ast
        out: list[str] = []
        tree = ast.parse(src, filename=label)
        for node in ast.walk(tree):
            # Direct from-import binding of a paid callable.
            if isinstance(node, ast.ImportFrom) and node.module in ("market_check", "analyze_event"):
                for alias in node.names:
                    if alias.name in cls._PAID_CALLABLES:
                        out.append(f"{label}: from {node.module} import {alias.name}")
            # Calls to a paid callable.
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in cls._PAID_CALLABLES:
                    out.append(f"{label}: bare call {func.id}(...)")
                elif isinstance(func, ast.Attribute) and func.attr in cls._PAID_CALLABLES:
                    base = func.value.id if isinstance(func.value, ast.Name) else "<expr>"
                    if base not in cls._ALLOWED_BASES:
                        out.append(f"{label}: {base}.{func.attr}(...)")
        return out

    def test_detector_flags_a_direct_paid_binding(self) -> None:
        # Self-check: the detector MUST flag a route that binds + calls the
        # paid callable directly, otherwise the invariant below is vacuous.
        from_import = (
            "from market_check import market_check\n\n"
            "def h():\n    return market_check([], [])\n"
        )
        self.assertTrue(self._offenders(from_import, "synthetic_from.py"))
        dotted = (
            "import market_check as mc\n\n"
            "def h():\n    return mc.market_check([], [])\n"
        )
        self.assertTrue(self._offenders(dotted, "synthetic_dotted.py"))

    def test_detector_allows_the_api_seam(self) -> None:
        # The sanctioned pattern must NOT be flagged (no false positives).
        ok = "import api as _api\n\ndef h():\n    return _api.market_check([], [])\n"
        self.assertEqual(self._offenders(ok, "ok.py"), [])

    def test_no_route_module_bypasses_the_paid_seam(self) -> None:
        import pathlib
        routes_dir = pathlib.Path(__file__).resolve().parent.parent / "routes"
        self.assertTrue(routes_dir.is_dir(), "routes/ directory not found")
        offenders: list[str] = []
        for path in sorted(routes_dir.glob("*.py")):
            offenders.extend(self._offenders(path.read_text(encoding="utf-8"), path.name))
        self.assertEqual(
            offenders, [],
            "routes bypass the patched api.* paid seam (would evade the "
            f"no-paid invariant): {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
