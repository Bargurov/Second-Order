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
)

# Strictly-forbidden seams: ZERO calls allowed from any GET route.
_STRICT_FORBIDDEN_TARGETS: frozenset[str] = frozenset({
    "api.analyze_event",
    "api.market_check",
    "auto_backfill_runner.execute_paid_candidate",
})

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

        # Patch every paid/provider seam to raise on call.  The mock
        # objects are reset between requests so the probe can attribute
        # call counts to individual routes.
        cls._patches = []
        cls._mocks = {}
        for target in _PAID_SEAM_TARGETS:
            patcher = mock.patch(
                target,
                side_effect=AssertionError(
                    f"paid seam {target!r} called under no-paid GET test"
                ),
            )
            mock_obj = patcher.start()
            cls._patches.append(patcher)
            cls._mocks[target] = mock_obj

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


if __name__ == "__main__":
    unittest.main()
