"""Tests for ``scripts/refresh_price_cache.py``.

The CLI is a thin composer over :func:`price_cache_refresh.plan_refresh`
plus the read-only :func:`price_cache_refresh.load_inputs` loader.
These tests pin the seam contract: cases never touch the real
archive, never invoke any provider / LLM / paid-execution seam, and
never write to the DB.  Both seams (``plan_refresh`` and
``load_inputs``) are patched per case so the CLI runs hermetically
even when no archive DB exists in the tmp dir.
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import price_cache_refresh as pcr  # noqa: E402
from scripts import refresh_price_cache as cli  # noqa: E402


# ---------------------------------------------------------------------------
# Stub builders — produce ``RefreshPlan`` / ``TickerRefreshJob``
# instances so the CLI's normalisation layer exercises the real
# dataclass shape.
# ---------------------------------------------------------------------------


def _job(
    *,
    event_id: int,
    event_date: str,
    symbol: str,
    intervals: tuple[tuple[str, str], ...] = (("2026-04-01", "2026-04-25"),),
    business_days: int = 18,
    auto_adjust: bool = True,
) -> pcr.TickerRefreshJob:
    return pcr.TickerRefreshJob(
        event_id=event_id,
        event_date=event_date,
        symbol=symbol,
        intervals=intervals,
        business_days=business_days,
        auto_adjust=auto_adjust,
    )


def _plan(
    *,
    refresh_jobs: tuple[pcr.TickerRefreshJob, ...] = (),
    events_considered: int = 0,
    tickers_considered: int = 0,
    skipped_counts: dict | None = None,
    provider_calls_estimate: int = 0,
    max_provider_calls: int = 50,
    cap_applied: bool = False,
    decision_reason: str = "no_work",
) -> pcr.RefreshPlan:
    if skipped_counts is None:
        skipped_counts = {key: 0 for key in pcr.SKIP_COUNT_KEYS}
    return pcr.RefreshPlan(
        events_considered=events_considered,
        tickers_considered=tickers_considered,
        refresh_jobs=refresh_jobs,
        skipped_counts=skipped_counts,
        provider_calls_estimate=provider_calls_estimate,
        max_provider_calls=max_provider_calls,
        cap_applied=cap_applied,
        decision_reason=decision_reason,
    )


# ---------------------------------------------------------------------------
# Shared base — restores the module-level seams between cases so a
# previous test's MagicMock does not leak across cases.
# ---------------------------------------------------------------------------


class _CliBase(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_plan_refresh = cli.plan_refresh
        self._orig_load_inputs  = cli.load_inputs
        # Default to safe stubs so a test that forgets to patch a seam
        # still produces a hermetic dry-run instead of touching disk.
        cli.load_inputs  = MagicMock(return_value=([], {}))
        cli.plan_refresh = MagicMock(return_value=_plan())

    def tearDown(self) -> None:
        cli.plan_refresh = self._orig_plan_refresh
        cli.load_inputs  = self._orig_load_inputs


# ---------------------------------------------------------------------------
# Help / argument plumbing
# ---------------------------------------------------------------------------


class TestHelp(_CliBase):
    def test_help_exits_zero(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            cli.main(argv=["--help"], out=io.StringIO())
        self.assertEqual(ctx.exception.code, 0)

    def test_default_arg_values_match_planner_defaults(self) -> None:
        ns = cli._parse_args([])
        self.assertEqual(ns.max_events,
                         pcr.RefreshConfig.__dataclass_fields__["max_events"].default)
        self.assertEqual(ns.max_provider_calls,
                         pcr.RefreshConfig.__dataclass_fields__["max_provider_calls"].default)
        self.assertFalse(ns.json)


# ---------------------------------------------------------------------------
# Default invocation — exit 0 with the planner returning an empty plan
# ---------------------------------------------------------------------------


class TestDefaultDryRun(_CliBase):
    def test_default_invocation_dry_run_exit_zero(self) -> None:
        buf = io.StringIO()
        rc = cli.main(argv=[], out=buf)
        self.assertEqual(rc, 0, msg=buf.getvalue())

    def test_default_invocation_does_not_touch_real_loader(self) -> None:
        # The base class patches ``load_inputs`` to a MagicMock; the
        # CLI must use that bound seam (not the real
        # price_cache_refresh.load_inputs).  A real call would attempt
        # SQLite IO against the live archive.
        cli.main(argv=[], out=io.StringIO())
        cli.load_inputs.assert_called_once()

    def test_json_output_is_parseable_and_carries_ok_flag(self) -> None:
        buf = io.StringIO()
        rc = cli.main(argv=["--json"], out=buf)
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertTrue(payload["ok"])
        self.assertIn("decision_reason", payload)
        self.assertIn("caps",            payload)
        self.assertIn("skipped_counts",  payload)
        self.assertIn("events",          payload)
        self.assertEqual(payload["events"], [])


# ---------------------------------------------------------------------------
# Planner seam invocation — caps forwarded into RefreshConfig
# ---------------------------------------------------------------------------


class TestPlannerSeamInvoked(_CliBase):
    def test_planner_called_with_loader_outputs_and_config(self) -> None:
        events_stub  = [{"id": 1, "event_date": "2026-04-12", "market_tickers": []}]
        cached_stub  = {"AAPL": frozenset()}
        cli.load_inputs = MagicMock(return_value=(events_stub, cached_stub))

        cli.main(argv=["--json"], out=io.StringIO())
        cli.plan_refresh.assert_called_once()
        args, kwargs = cli.plan_refresh.call_args
        self.assertEqual(list(args[0]), events_stub)
        self.assertEqual(args[1],       cached_stub)
        cfg = kwargs.get("config")
        self.assertIsNotNone(cfg)
        self.assertIsInstance(cfg, pcr.RefreshConfig)

    def test_max_events_and_max_provider_calls_forwarded(self) -> None:
        cli.main(
            argv=["--max-events", "12", "--max-provider-calls", "9", "--json"],
            out=io.StringIO(),
        )
        cfg = cli.plan_refresh.call_args.kwargs["config"]
        self.assertEqual(cfg.max_events,         12)
        self.assertEqual(cfg.max_provider_calls,  9)

    def test_caps_block_reflects_overrides_in_payload(self) -> None:
        buf = io.StringIO()
        cli.main(
            argv=["--max-events", "7", "--max-provider-calls", "3", "--json"],
            out=buf,
        )
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["caps"]["max_events"],         7)
        self.assertEqual(payload["caps"]["max_provider_calls"], 3)


# ---------------------------------------------------------------------------
# Planner output rendering — dataclass plan with refresh_jobs
# ---------------------------------------------------------------------------


class TestPlannerOutputRendering(_CliBase):
    def test_json_payload_groups_jobs_by_event(self) -> None:
        plan = _plan(
            refresh_jobs=(
                _job(event_id=42, event_date="2026-04-12", symbol="AAPL"),
                _job(
                    event_id=42, event_date="2026-04-12",
                    symbol="MSFT",
                    intervals=(("2026-04-01", "2026-04-15"),
                               ("2026-04-20", "2026-04-25")),
                    business_days=14,
                ),
                _job(event_id=43, event_date="2026-04-13", symbol="TSLA"),
            ),
            events_considered=2,
            tickers_considered=3,
            provider_calls_estimate=4,
            decision_reason="planned",
        )
        cli.plan_refresh = MagicMock(return_value=plan)
        buf = io.StringIO()
        rc = cli.main(argv=["--json"], out=buf)
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["decision_reason"],         "planned")
        self.assertEqual(payload["events_planned"],          2)
        self.assertEqual(payload["unique_tickers"],          3)
        self.assertEqual(payload["provider_calls_estimate"], 4)
        # Two events present; first event has two tickers grouped under it.
        self.assertEqual(len(payload["events"]), 2)
        first = payload["events"][0]
        self.assertEqual(first["event_id"], 42)
        self.assertEqual(len(first["tickers"]), 2)
        msft = next(t for t in first["tickers"] if t["symbol"] == "MSFT")
        self.assertEqual(msft["interval_count"], 2)
        self.assertEqual(len(msft["intervals"]), 2)

    def test_text_output_lists_events_tickers_windows_and_skip_counts(self) -> None:
        plan = _plan(
            refresh_jobs=(
                _job(
                    event_id=99, event_date="2026-04-12", symbol="AAPL",
                    intervals=(("2026-04-05", "2026-05-08"),),
                    business_days=24,
                ),
            ),
            events_considered=1,
            tickers_considered=1,
            skipped_counts={
                **{key: 0 for key in pcr.SKIP_COUNT_KEYS},
                pcr.SKIP_STALE_TICKER:    2,
                pcr.SKIP_INVALID_TICKER:  1,
                pcr.SKIP_ALREADY_COVERED: 4,
            },
            provider_calls_estimate=1,
            decision_reason="planned",
        )
        cli.plan_refresh = MagicMock(return_value=plan)
        buf = io.StringIO()
        rc = cli.main(argv=[], out=buf)
        self.assertEqual(rc, 0)
        text = buf.getvalue()
        self.assertIn("Decision reason: planned",       text)
        self.assertIn("events_considered",              text)
        self.assertIn("provider_calls_estimate",        text)
        self.assertIn(pcr.SKIP_STALE_TICKER,            text)
        self.assertIn(pcr.SKIP_INVALID_TICKER,          text)
        self.assertIn(pcr.SKIP_ALREADY_COVERED,         text)
        # Per-event row + ticker symbol + window are surfaced.
        self.assertIn("event_id=99",                    text)
        self.assertIn("AAPL",                           text)
        self.assertIn("2026-04-05..2026-05-08",         text)

    def test_cap_applied_flag_surfaces_in_text_view(self) -> None:
        plan = _plan(
            cap_applied=True,
            decision_reason="cap_exhausted",
            skipped_counts={
                **{key: 0 for key in pcr.SKIP_COUNT_KEYS},
                pcr.SKIP_CAP_EXHAUSTED: 3,
            },
        )
        cli.plan_refresh = MagicMock(return_value=plan)
        buf = io.StringIO()
        cli.main(argv=[], out=buf)
        text = buf.getvalue()
        self.assertIn("cap applied",                    text)
        self.assertIn("Decision reason: cap_exhausted", text)
        self.assertIn(pcr.SKIP_CAP_EXHAUSTED,           text)


# ---------------------------------------------------------------------------
# Loader resilience — degrades to empty inputs on any DB failure
# ---------------------------------------------------------------------------


class TestLoaderFailureDegrade(_CliBase):
    def test_loader_exception_does_not_propagate(self) -> None:
        cli.load_inputs = MagicMock(
            side_effect=RuntimeError("DB exploded"),
        )
        # The planner is still invoked with empty inputs so the report
        # remains stable.
        plan_returned = _plan(decision_reason="no_work")
        cli.plan_refresh = MagicMock(return_value=plan_returned)
        buf = io.StringIO()
        rc = cli.main(argv=["--json"], out=buf)
        self.assertEqual(rc, 0)
        cli.plan_refresh.assert_called_once()
        args, _kwargs = cli.plan_refresh.call_args
        self.assertEqual(list(args[0]), [])
        self.assertEqual(args[1],       {})


# ---------------------------------------------------------------------------
# Safety invariants — no provider, no LLM, no paid path, no DB write
# ---------------------------------------------------------------------------


_FORBIDDEN_PAID_SEAMS: tuple[tuple[str, str], ...] = (
    ("analyze_event",        "analyze_event"),
    ("analyze_event",        "_call_anthropic"),
    ("analyze_event",        "_call_openai"),
    ("analyze_event",        "_call_llm_provider"),
    ("market_check",         "_fetch"),
    ("market_check",         "_fetch_since"),
    ("market_check",         "market_check"),
    ("price_cache",          "fetch_daily_cached"),
    ("market_data",          "get_provider"),
    ("auto_backfill_runner", "execute_paid_candidate"),
)


_FORBIDDEN_DB_WRITERS: tuple[tuple[str, str], ...] = (
    ("db", "save_event"),
    ("db", "update_review"),
    ("db", "append_revisit_snapshot"),
    ("db", "delete_event"),
    ("db", "save_movers_cache"),
    ("db", "clear_movers_cache"),
)


def _patch_raisers(stack: ExitStack, seams: tuple[tuple[str, str], ...],
                   *, label: str) -> None:
    """Patch every (module, attr) pair with a raiser, skipping those
    that are not on this checkout.  Tolerates optional dependencies
    (e.g. missing ``yfinance``) while still pinning the seams that
    DO exist.
    """
    for module_name, attr in seams:
        try:
            mod = __import__(module_name)
        except Exception:
            continue
        if not hasattr(mod, attr):
            continue
        stack.enter_context(patch.object(
            mod, attr,
            side_effect=AssertionError(
                f"refresh_price_cache CLI must not invoke "
                f"{module_name}.{attr} ({label})",
            ),
        ))


class TestNoPaidSeams(_CliBase):
    def test_no_provider_or_paid_seams_invoked_under_dry_run(self) -> None:
        # Inject a planner that returns a populated plan so the
        # rendering path also runs — we want to prove that even when
        # the CLI has work to render, no paid seam is reached.
        cli.plan_refresh = MagicMock(return_value=_plan(
            refresh_jobs=(
                _job(event_id=1, event_date="2026-04-12", symbol="AAPL"),
            ),
            events_considered=1,
            tickers_considered=1,
            provider_calls_estimate=1,
            decision_reason="planned",
        ))
        with ExitStack() as stack:
            _patch_raisers(stack, _FORBIDDEN_PAID_SEAMS, label="paid seam")
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "refresh_price_cache must not call yfinance",
                    ),
                ))
            except ImportError:
                pass
            buf = io.StringIO()
            rc = cli.main(argv=["--json"], out=buf)
        self.assertEqual(rc, 0, msg=buf.getvalue())


class TestNoDbWrites(_CliBase):
    def test_no_db_writers_invoked(self) -> None:
        cli.plan_refresh = MagicMock(return_value=_plan(
            refresh_jobs=(
                _job(event_id=1, event_date="2026-04-12", symbol="AAPL"),
                _job(event_id=2, event_date="2026-04-13", symbol="MSFT"),
            ),
            events_considered=2,
            tickers_considered=2,
            provider_calls_estimate=2,
            decision_reason="planned",
        ))
        with ExitStack() as stack:
            _patch_raisers(stack, _FORBIDDEN_DB_WRITERS, label="db writer")
            buf = io.StringIO()
            rc = cli.main(argv=["--json"], out=buf)
        self.assertEqual(rc, 0, msg=buf.getvalue())


# ---------------------------------------------------------------------------
# Module import surface — CLI must not pull in api / FastAPI eagerly
# ---------------------------------------------------------------------------


class TestImportSurface(_CliBase):
    def test_default_db_path_helper_lazy_imports_db(self) -> None:
        # The CLI imports ``price_cache_refresh`` at top-level (which
        # depends only on stdlib + sqlite3) but must NOT import ``db``
        # eagerly — that would pull in FastAPI / api side effects.
        # Inspect the helper to confirm the import lives inside the
        # function body, not at module top.
        import inspect
        src = inspect.getsource(cli._default_db_path)
        self.assertIn("from db import", src)


if __name__ == "__main__":
    unittest.main()
