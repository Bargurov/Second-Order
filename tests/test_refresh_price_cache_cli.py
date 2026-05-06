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


# ---------------------------------------------------------------------------
# Write-mode flags — --write / --confirm gating + executor seam
# ---------------------------------------------------------------------------


class TestWriteModeGating(_CliBase):
    def test_default_invocation_mode_is_dry_run(self) -> None:
        # No flags → dry_run, confirmed=false, executor never called.
        sentinel_executor = MagicMock(side_effect=AssertionError(
            "execute_refresh must NOT be called in default dry-run",
        ))
        with patch.object(cli, "execute_refresh", sentinel_executor):
            buf = io.StringIO()
            rc = cli.main(argv=["--json"], out=buf)
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["mode"],           "dry_run")
        self.assertIs(payload["confirmed"],         False)
        self.assertEqual(payload["attempted_jobs"], 0)
        self.assertEqual(payload["written_rows"],   0)
        self.assertEqual(payload["errors"],         [])

    def test_confirm_alone_is_dry_run(self) -> None:
        # --confirm without --write must NOT enable write mode.
        sentinel_executor = MagicMock(side_effect=AssertionError(
            "execute_refresh must NOT be called when --write is absent",
        ))
        with patch.object(cli, "execute_refresh", sentinel_executor):
            buf = io.StringIO()
            rc = cli.main(argv=["--confirm", "--json"], out=buf)
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["mode"],   "dry_run")
        self.assertIs(payload["confirmed"], False)

    def test_write_alone_exits_nonzero_and_skips_executor(self) -> None:
        sentinel_executor = MagicMock(side_effect=AssertionError(
            "execute_refresh must NOT be called when --confirm is missing",
        ))
        with patch.object(cli, "execute_refresh", sentinel_executor):
            buf = io.StringIO()
            rc = cli.main(argv=["--write", "--json"], out=buf)
        self.assertEqual(rc, 1, msg=buf.getvalue())
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["mode"],           "write")
        self.assertIs(payload["confirmed"],         False)
        self.assertEqual(payload["attempted_jobs"], 0)
        self.assertEqual(payload["written_rows"],   0)
        self.assertEqual(payload["errors"],         [])
        # Top-level human-readable error is set; ok flag is false.
        self.assertIn("error",                      payload)
        self.assertIn("--confirm",                  payload["error"])
        self.assertIs(payload["ok"],                False)

    def test_write_alone_does_not_print_to_stderr(self) -> None:
        # The verification command pipes JSON; stderr would split the
        # output.  Even on the exit-1 path the JSON must land on the
        # ``out`` stream the caller passed.
        sentinel_executor = MagicMock(side_effect=AssertionError(
            "execute_refresh must NOT be called when --confirm is missing",
        ))
        buf = io.StringIO()
        with patch.object(cli, "execute_refresh", sentinel_executor):
            rc = cli.main(argv=["--write", "--json"], out=buf)
        self.assertEqual(rc, 1)
        # Body parses as JSON — proves the report did not leak to a
        # secondary stream.
        json.loads(buf.getvalue())


class TestWriteConfirmInvokesExecutor(_CliBase):
    def test_write_and_confirm_invokes_executor_once(self) -> None:
        plan = _plan(
            refresh_jobs=(
                _job(event_id=1, event_date="2026-04-12", symbol="AAPL"),
            ),
            events_considered=1,
            tickers_considered=1,
            provider_calls_estimate=1,
            decision_reason="planned",
        )
        cli.plan_refresh = MagicMock(return_value=plan)
        executor_stub = MagicMock(return_value={
            "attempted_jobs": 1,
            "written_rows":   24,
            "errors":         [],
        })
        with patch.object(cli, "execute_refresh", executor_stub):
            buf = io.StringIO()
            rc = cli.main(argv=["--write", "--confirm", "--json"], out=buf)
        self.assertEqual(rc, 0)
        executor_stub.assert_called_once()
        args, kwargs = executor_stub.call_args
        # Plan passed positionally; config kwarg carries RefreshConfig.
        self.assertIs(args[0], plan)
        self.assertIsInstance(kwargs.get("config"), pcr.RefreshConfig)

    def test_write_confirm_propagates_executor_counters_into_payload(self) -> None:
        cli.plan_refresh = MagicMock(return_value=_plan(decision_reason="planned"))
        executor_stub = MagicMock(return_value={
            "attempted_jobs": 7,
            "written_rows":   124,
            "errors":         [],
        })
        with patch.object(cli, "execute_refresh", executor_stub):
            buf = io.StringIO()
            rc = cli.main(argv=["--write", "--confirm", "--json"], out=buf)
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["mode"],           "write")
        self.assertIs(payload["confirmed"],         True)
        self.assertEqual(payload["attempted_jobs"], 7)
        self.assertEqual(payload["written_rows"],   124)
        self.assertEqual(payload["errors"],         [])

    def test_write_confirm_with_errors_exits_nonzero(self) -> None:
        cli.plan_refresh = MagicMock(return_value=_plan(decision_reason="planned"))
        executor_stub = MagicMock(return_value={
            "attempted_jobs": 3,
            "written_rows":   60,
            "errors": [
                {
                    "event_id":       42,
                    "symbol":         "TSLA",
                    "interval_start": "2026-04-01",
                    "interval_end":   "2026-04-25",
                    "error":          "RuntimeError: provider down",
                },
            ],
        })
        with patch.object(cli, "execute_refresh", executor_stub):
            buf = io.StringIO()
            rc = cli.main(argv=["--write", "--confirm", "--json"], out=buf)
        self.assertEqual(rc, 1)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["mode"],          "write")
        self.assertIs(payload["confirmed"],        True)
        self.assertEqual(payload["attempted_jobs"], 3)
        self.assertEqual(payload["written_rows"],   60)
        self.assertEqual(len(payload["errors"]),    1)
        self.assertEqual(payload["errors"][0]["symbol"], "TSLA")

    def test_write_confirm_executor_raise_lands_in_errors(self) -> None:
        # If the executor itself blows up (rather than returning per-
        # interval errors), the exception is captured into the errors
        # list and the run still reports a stable JSON shape, exit 1.
        cli.plan_refresh = MagicMock(return_value=_plan(decision_reason="planned"))
        executor_stub = MagicMock(side_effect=RuntimeError("executor exploded"))
        with patch.object(cli, "execute_refresh", executor_stub):
            buf = io.StringIO()
            rc = cli.main(argv=["--write", "--confirm", "--json"], out=buf)
        self.assertEqual(rc, 1)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["mode"],   "write")
        self.assertIs(payload["confirmed"], True)
        self.assertGreaterEqual(len(payload["errors"]), 1)
        self.assertIn("executor exploded", payload["errors"][0]["error"])


class TestWriteConfirmDoesNotInvokeRealProvider(_CliBase):
    """The default executor would call ``price_cache.fetch_daily_cached``
    which in turn reaches the market-data provider.  Tests must patch
    the executor seam so no provider call happens.  This case
    additionally raisers ``price_cache.fetch_daily_cached`` to prove
    the patched executor is the *only* path the CLI took.
    """

    def test_provider_seam_never_reached_with_patched_executor(self) -> None:
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
        executor_stub = MagicMock(return_value={
            "attempted_jobs": 2,
            "written_rows":   48,
            "errors":         [],
        })
        with ExitStack() as stack:
            stack.enter_context(patch.object(cli, "execute_refresh", executor_stub))
            _patch_raisers(
                stack,
                _FORBIDDEN_PAID_SEAMS + (("price_cache", "fetch_daily_cached"),),
                label="paid/provider seam",
            )
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "refresh_price_cache --write must not call yfinance",
                    ),
                ))
            except ImportError:
                pass
            buf = io.StringIO()
            rc = cli.main(argv=["--write", "--confirm", "--json"], out=buf)
        self.assertEqual(rc, 0)
        executor_stub.assert_called_once()


class TestWriteModeTextRendering(_CliBase):
    def test_write_confirm_text_carries_mode_and_executor_summary(self) -> None:
        cli.plan_refresh = MagicMock(return_value=_plan(decision_reason="planned"))
        with patch.object(cli, "execute_refresh", MagicMock(return_value={
            "attempted_jobs": 4,
            "written_rows":   88,
            "errors":         [],
        })):
            buf = io.StringIO()
            rc = cli.main(argv=["--write", "--confirm"], out=buf)
        self.assertEqual(rc, 0)
        text = buf.getvalue()
        self.assertIn("Mode: write",           text)
        self.assertIn("confirmed=true",        text)
        self.assertIn("attempted_jobs=4",      text)
        self.assertIn("written_rows=88",       text)


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


# ---------------------------------------------------------------------------
# --focus dry-run option — narrows the events fed into the planner to a
# named gap bucket (e.g. ``no-forward-20d-gap``) without touching write
# behaviour.  The focus value must reach the planner via the events list
# it is called with, and must be visible in the rendered payload.
# ---------------------------------------------------------------------------


class TestFocusMode(_CliBase):
    """``--focus`` filters which events the planner sees but never
    changes write-mode gating, executor invocation, or the cap config.
    """

    @staticmethod
    def _events_with_mixed_20d_coverage() -> tuple[list[dict], dict]:
        """Two events: one fully covered through +20bd, one with a ticker
        whose cached max ends well before +20bd.  Used by every focus
        test so the per-test set-up reads identically.
        """
        from datetime import date
        # Event 1 anchor 2026-04-01.  +20 business days → 2026-04-29.
        # AAPL cached through 2026-04-30  → covered.
        # Event 2 anchor 2026-04-15.  +20 business days → 2026-05-13.
        # TSLA cached through 2026-04-20 → 20d gap.
        events = [
            {"id": 1, "event_date": "2026-04-01",
             "market_tickers": [{"symbol": "AAPL"}]},
            {"id": 2, "event_date": "2026-04-15",
             "market_tickers": [{"symbol": "TSLA"}]},
        ]
        cached = {
            "AAPL": frozenset({date(2026, 4, 30)}),
            "TSLA": frozenset({date(2026, 4, 20)}),
        }
        return events, cached

    def test_default_focus_is_none_in_payload(self) -> None:
        buf = io.StringIO()
        cli.main(argv=["--json"], out=buf)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["focus"], "none")

    def test_focus_no_forward_20d_filters_events_reaching_planner(self) -> None:
        events, cached = self._events_with_mixed_20d_coverage()
        cli.load_inputs = MagicMock(return_value=(events, cached))

        cli.main(
            argv=["--focus", "no-forward-20d-gap", "--json"],
            out=io.StringIO(),
        )

        cli.plan_refresh.assert_called_once()
        args, _kwargs = cli.plan_refresh.call_args
        forwarded_events = list(args[0])
        forwarded_ids = [ev["id"] for ev in forwarded_events]
        self.assertEqual(
            forwarded_ids, [2],
            msg="Only events whose tickers lack 20d forward coverage "
                "should reach the planner under --focus no-forward-20d-gap.",
        )
        # cached_by_ticker map is forwarded unchanged so the planner can
        # still see what is already covered for the surviving event.
        self.assertEqual(args[1], cached)

    def test_focus_value_appears_in_json_payload(self) -> None:
        events, cached = self._events_with_mixed_20d_coverage()
        cli.load_inputs = MagicMock(return_value=(events, cached))
        buf = io.StringIO()
        cli.main(
            argv=["--focus", "no-forward-20d-gap", "--json"],
            out=buf,
        )
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["focus"], "no-forward-20d-gap")

    def test_focus_value_appears_in_text_output(self) -> None:
        events, cached = self._events_with_mixed_20d_coverage()
        cli.load_inputs = MagicMock(return_value=(events, cached))
        # Return a populated plan so the rendering path exercises the
        # planned-jobs section alongside the focus banner.
        cli.plan_refresh = MagicMock(return_value=_plan(
            refresh_jobs=(_job(
                event_id=2, event_date="2026-04-15", symbol="TSLA",
            ),),
            events_considered=1,
            tickers_considered=1,
            provider_calls_estimate=1,
            decision_reason="planned",
        ))
        buf = io.StringIO()
        cli.main(argv=["--focus", "no-forward-20d-gap"], out=buf)
        text = buf.getvalue()
        self.assertIn("Focus: no-forward-20d-gap", text)
        # Planned jobs section still renders the surviving event.
        self.assertIn("event_id=2", text)
        self.assertIn("TSLA",       text)

    def test_focus_does_not_invoke_executor(self) -> None:
        # Focus is a dry-run-side filter; --write is absent so the
        # executor must remain untouched even when focus is set.
        events, cached = self._events_with_mixed_20d_coverage()
        cli.load_inputs = MagicMock(return_value=(events, cached))
        sentinel_executor = MagicMock(side_effect=AssertionError(
            "execute_refresh must NOT be called by a --focus dry-run",
        ))
        with patch.object(cli, "execute_refresh", sentinel_executor):
            cli.main(
                argv=["--focus", "no-forward-20d-gap", "--json"],
                out=io.StringIO(),
            )

    def test_focus_invalid_value_rejected_by_argparse(self) -> None:
        # Unknown focus values must be rejected at the CLI boundary; the
        # CLI never silently accepts a typo and runs the unfiltered path.
        with self.assertRaises(SystemExit):
            cli.main(
                argv=["--focus", "definitely-not-a-bucket", "--json"],
                out=io.StringIO(),
            )

    def test_focus_does_not_alter_refresh_config(self) -> None:
        events, cached = self._events_with_mixed_20d_coverage()
        cli.load_inputs = MagicMock(return_value=(events, cached))
        cli.main(
            argv=["--focus", "no-forward-20d-gap", "--json"],
            out=io.StringIO(),
        )
        cfg = cli.plan_refresh.call_args.kwargs["config"]
        defaults = pcr.RefreshConfig()
        self.assertEqual(cfg.max_events,         defaults.max_events)
        self.assertEqual(cfg.max_provider_calls, defaults.max_provider_calls)
        self.assertEqual(cfg.auto_adjust,        defaults.auto_adjust)


# ---------------------------------------------------------------------------
# Provider/SQLite preflight — the executor short-circuits when the
# yfinance tz/cookie cache directory or the project events.db is not
# writable, so a sandboxed run reports one structured cause instead of
# N silent OperationalError errors.
# ---------------------------------------------------------------------------


class TestProviderCachePreflightHelper(unittest.TestCase):
    """Direct unit coverage of the preflight helper — no main()/argparse
    plumbing.  Filesystem probes are patched so the test never depends
    on whether yfinance is installed or where its cache lives.
    """

    def test_returns_ok_when_both_probes_pass(self) -> None:
        with patch.object(cli, "_resolve_yfinance_cache_dir",
                          return_value="/tmp/yf"), \
             patch.object(cli, "_probe_dir_writable",
                          return_value=(True, None)), \
             patch.object(cli, "_probe_sqlite_writable",
                          return_value=(True, None)):
            result = cli._provider_cache_preflight(db_path="/tmp/events.db")

        self.assertTrue(result["ok"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["yfinance_cache"]["path"], "/tmp/yf")
        self.assertTrue(result["yfinance_cache"]["ok"])
        self.assertTrue(result["events_db"]["ok"])

    def test_yfinance_dir_failure_propagates(self) -> None:
        with patch.object(cli, "_resolve_yfinance_cache_dir",
                          return_value=r"C:\Users\Bar\AppData\Local\py-yfinance"), \
             patch.object(cli, "_probe_dir_writable",
                          return_value=(False, "PermissionError: sandbox")), \
             patch.object(cli, "_probe_sqlite_writable",
                          return_value=(True, None)):
            result = cli._provider_cache_preflight(db_path="/tmp/events.db")

        self.assertFalse(result["ok"])
        self.assertFalse(result["yfinance_cache"]["ok"])
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("yfinance cache dir not writable", result["errors"][0])
        self.assertIn("PermissionError",                 result["errors"][0])
        self.assertIn("sandbox",                         result["errors"][0])

    def test_events_db_failure_propagates(self) -> None:
        with patch.object(cli, "_resolve_yfinance_cache_dir",
                          return_value="/tmp/yf"), \
             patch.object(cli, "_probe_dir_writable",
                          return_value=(True, None)), \
             patch.object(cli, "_probe_sqlite_writable",
                          return_value=(False, "OperationalError: locked")):
            result = cli._provider_cache_preflight(db_path="/tmp/events.db")

        self.assertFalse(result["ok"])
        self.assertFalse(result["events_db"]["ok"])
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("events.db not writable", result["errors"][0])
        self.assertIn("OperationalError",       result["errors"][0])

    def test_skips_yfinance_probe_when_path_unresolved(self) -> None:
        # yfinance not installed (or layout shifted) → resolver returns
        # None.  The probe must NOT silently mark everything ok; the
        # operator deserves to see "path-unresolved".
        with patch.object(cli, "_resolve_yfinance_cache_dir",
                          return_value=None), \
             patch.object(cli, "_probe_sqlite_writable",
                          return_value=(True, None)):
            result = cli._provider_cache_preflight(db_path="/tmp/events.db")
        self.assertFalse(result["ok"])
        self.assertEqual(result["yfinance_cache"]["reason"], "path-unresolved")


class TestWriteConfirmPreflight(_CliBase):
    """Integration: --write --confirm honours the preflight result."""

    def test_preflight_failure_short_circuits_executor(self) -> None:
        # Plan is non-empty so we can prove the executor would have
        # been reachable — only the preflight blocks it.
        cli.plan_refresh = MagicMock(return_value=_plan(
            refresh_jobs=(
                _job(event_id=1, event_date="2026-04-12", symbol="AAPL"),
            ),
            events_considered=1,
            tickers_considered=1,
            provider_calls_estimate=1,
            decision_reason="planned",
        ))
        sentinel_executor = MagicMock(side_effect=AssertionError(
            "execute_refresh must NOT be called when preflight fails",
        ))
        failing_preflight = {
            "ok": False,
            "yfinance_cache": {
                "path":   r"C:\Users\Bar\AppData\Local\py-yfinance",
                "ok":     False,
                "reason": "PermissionError: sandbox blocks AppData",
            },
            "events_db": {"path": "events.db", "ok": True, "reason": None},
            "errors": [
                "yfinance cache dir not writable "
                "(path='C:\\\\Users\\\\Bar\\\\AppData\\\\Local\\\\py-yfinance'): "
                "PermissionError: sandbox blocks AppData",
            ],
        }
        with patch.object(cli, "execute_refresh", sentinel_executor), \
             patch.object(cli, "_provider_cache_preflight",
                          return_value=failing_preflight):
            buf = io.StringIO()
            rc = cli.main(argv=["--write", "--confirm", "--json"], out=buf)

        self.assertEqual(rc, 1, msg=buf.getvalue())
        payload = json.loads(buf.getvalue())
        # Top-level shape: confirmed run, but ok=false and an error
        # message naming the preflight as the cause.
        self.assertEqual(payload["mode"],   "write")
        self.assertIs(payload["confirmed"], True)
        self.assertIs(payload["ok"],        False)
        self.assertIn("preflight",          payload["error"])
        # Per-error rows carry the structured PreflightError prefix so
        # operators can grep for the failure family.
        self.assertGreaterEqual(len(payload["errors"]), 1)
        self.assertTrue(any(
            "PreflightError" in e["error"] for e in payload["errors"]
        ))
        # Structured preflight block surfaces the resolved path so the
        # operator does not need to re-derive it.
        self.assertIn("preflight", payload)
        self.assertFalse(payload["preflight"]["ok"])
        self.assertEqual(
            payload["preflight"]["yfinance_cache"]["path"],
            r"C:\Users\Bar\AppData\Local\py-yfinance",
        )

    def test_preflight_pass_invokes_executor_normally(self) -> None:
        cli.plan_refresh = MagicMock(return_value=_plan(
            refresh_jobs=(
                _job(event_id=1, event_date="2026-04-12", symbol="AAPL"),
            ),
            events_considered=1,
            tickers_considered=1,
            provider_calls_estimate=1,
            decision_reason="planned",
        ))
        executor_stub = MagicMock(return_value={
            "attempted_jobs": 1,
            "written_rows":   24,
            "errors":         [],
        })
        passing_preflight = {
            "ok": True,
            "yfinance_cache": {"path": "/tmp/yf",         "ok": True, "reason": None},
            "events_db":      {"path": "/tmp/events.db",  "ok": True, "reason": None},
            "errors": [],
        }
        with patch.object(cli, "execute_refresh", executor_stub), \
             patch.object(cli, "_provider_cache_preflight",
                          return_value=passing_preflight):
            buf = io.StringIO()
            rc = cli.main(argv=["--write", "--confirm", "--json"], out=buf)

        self.assertEqual(rc, 0)
        executor_stub.assert_called_once()
        payload = json.loads(buf.getvalue())
        self.assertIs(payload["preflight"]["ok"], True)
        self.assertEqual(payload["written_rows"], 24)

    def test_preflight_does_not_run_in_dry_run(self) -> None:
        # No --write → preflight must NOT run.  Patch the function with
        # a raiser so an accidental invocation fails the test loudly.
        sentinel_preflight = MagicMock(side_effect=AssertionError(
            "_provider_cache_preflight must NOT run in dry-run mode",
        ))
        with patch.object(cli, "_provider_cache_preflight", sentinel_preflight):
            buf = io.StringIO()
            rc = cli.main(argv=["--json"], out=buf)
        self.assertEqual(rc, 0)
        # Dry-run payload does NOT carry a preflight block — the field
        # is reserved for the confirmed-write branch.
        payload = json.loads(buf.getvalue())
        self.assertNotIn("preflight", payload)

    def test_preflight_does_not_run_when_write_without_confirm(self) -> None:
        # --write without --confirm short-circuits with exit 1; the
        # preflight is reserved for the confirmed branch and must not
        # run on the refusal path either.
        sentinel_preflight = MagicMock(side_effect=AssertionError(
            "_provider_cache_preflight must NOT run on the --write-only "
            "refusal path",
        ))
        with patch.object(cli, "_provider_cache_preflight", sentinel_preflight):
            buf = io.StringIO()
            rc = cli.main(argv=["--write", "--json"], out=buf)
        self.assertEqual(rc, 1)
        payload = json.loads(buf.getvalue())
        self.assertNotIn("preflight", payload)


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
