#!/usr/bin/env python3
"""Live dry-run scheduler smoke check.

Boots the real ``api.app`` FastAPI lifespan with both auto-backfill
gates flipped on (``ENABLE_AUTO_BACKFILL=true`` /
``ENABLE_PAID_ANALYSIS=true``), but with the ``auto_backfill_scheduler``
create/start/stop seams patched so no APScheduler executor thread is
ever spawned and no real paid path is reachable.  Verifies that the
diagnostics surface reports the wired-and-running shape during the
lifespan and that the shutdown half stops the (fake) scheduler and
drops the ``app.state`` reference.

The script is the live counterpart to ``scripts/auto_backfill_dry_run.py``:
the dry-run CLI inspects what one tick would plan, this smoke inspects
what the lifespan boot/shutdown actually wires.

Out of scope (deliberately)
---------------------------
* No real ``BackgroundScheduler`` thread.  Three seams are mocked
  (create / start / stop); a raiser also replaces
  ``AutoBackfillLedger.reserve_calls`` so any accidental paid-cap
  reservation explodes loudly.
* No paid execution.  The paid/provider/SQLite-write seams from
  ``scripts.no_paid_smoke.guard_no_paid_provider_calls`` are wrapped
  with raisers for the duration of the lifespan.
* No real LLM, ``yfinance``, ``market_check``, or network call.

Usage:
    python scripts/auto_backfill_scheduler_smoke.py
    python scripts/auto_backfill_scheduler_smoke.py --json
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_GATE_ENV: tuple[str, ...] = (
    "ENABLE_AUTO_BACKFILL",
    "ENABLE_PAID_ANALYSIS",
)


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str | None = None


# ---------------------------------------------------------------------------
# Env + app.state hygiene
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _gates_on() -> Iterator[None]:
    """Snapshot-and-restore the two gate env vars.  Both flipped to
    ``true`` for the duration of the ``with`` block; original values
    (including absence) are restored on exit.
    """
    import os
    backup = {name: os.environ.get(name) for name in _GATE_ENV}
    for name in _GATE_ENV:
        os.environ[name] = "true"
    try:
        yield
    finally:
        for name, value in backup.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _clear_app_state_scheduler(app: Any) -> None:
    """Defensive cleanup — Starlette's ``State.__delattr__`` raises
    ``KeyError`` (not ``AttributeError``) on a missing key, so guard
    both so this stays a true no-op when nothing is attached.
    """
    try:
        delattr(app.state, "auto_backfill_scheduler")
    except (AttributeError, KeyError):
        pass


# ---------------------------------------------------------------------------
# Seam patching
# ---------------------------------------------------------------------------


def _ledger_reservation_raiser(*_args: Any, **_kwargs: Any) -> None:
    raise RuntimeError(
        "auto_backfill scheduler smoke: AutoBackfillLedger.reserve_calls "
        "must not be invoked during a dry-run lifespan boot",
    )


@contextlib.contextmanager
def _patched_seams(fake_scheduler: Any) -> Iterator[dict[str, MagicMock]]:
    """Patch every seam the lifespan touches that could spawn a thread,
    reach a paid path, or reserve a daily-cap call.  Yields the three
    create/start/stop mocks so the caller can assert call counts after
    the lifespan exits.
    """
    create_p = patch(
        "auto_backfill_scheduler.create_auto_backfill_scheduler",
        return_value=fake_scheduler,
    )
    start_p = patch(
        "auto_backfill_scheduler.start_auto_backfill_scheduler",
    )
    stop_p = patch(
        "auto_backfill_scheduler.stop_auto_backfill_scheduler",
    )
    reserve_p = patch(
        "auto_backfill_ledger.AutoBackfillLedger.reserve_calls",
        side_effect=_ledger_reservation_raiser,
    )

    create_mock = create_p.start()
    start_mock  = start_p.start()
    stop_mock   = stop_p.start()
    reserve_p.start()
    try:
        yield {
            "create": create_mock,
            "start":  start_mock,
            "stop":   stop_mock,
        }
    finally:
        reserve_p.stop()
        stop_p.stop()
        start_p.stop()
        create_p.stop()


# ---------------------------------------------------------------------------
# Smoke run
# ---------------------------------------------------------------------------


def _make_fake_scheduler() -> MagicMock:
    """Build a ``MagicMock`` shaped like a started ``BackgroundScheduler``.

    The lifespan calls our mocked ``start_auto_backfill_scheduler``
    which is a no-op, so we set ``running=True`` and ``get_jobs()->[obj]``
    by hand to mirror the post-start state the diagnostics endpoint
    would observe.  Mirrors the pattern in
    ``tests/test_auto_backfill_lifespan_wiring.py``.
    """
    fake = MagicMock()
    fake.running = True
    fake.get_jobs.return_value = [object()]
    return fake


def _check_scheduler_attached(app: Any, fake: Any) -> CheckResult:
    attached = getattr(app.state, "auto_backfill_scheduler", None)
    if attached is None:
        return CheckResult(
            "scheduler attached during lifespan",
            False,
            "app.state.auto_backfill_scheduler is None inside lifespan",
        )
    if attached is not fake:
        return CheckResult(
            "scheduler attached during lifespan",
            False,
            "app.state.auto_backfill_scheduler is not the fake scheduler",
        )
    return CheckResult("scheduler attached during lifespan", True)


def _check_status_endpoint(client: Any) -> tuple[CheckResult, CheckResult, dict]:
    """Return (mode-check, started-check, body)."""
    response = client.get("/diagnostics/auto-backfill-status")
    if response.status_code != 200:
        fail = CheckResult(
            "status endpoint mode=dry_run_only",
            False,
            f"HTTP {response.status_code} from /diagnostics/auto-backfill-status",
        )
        return fail, CheckResult(
            "status endpoint scheduler_started=true", False, "no body",
        ), {}
    body = response.json()
    block = body.get("scheduler") or {}
    mode = block.get("mode")
    started = block.get("scheduler_started")
    mode_ok = mode == "dry_run_only"
    started_ok = started is True
    return (
        CheckResult(
            "status endpoint mode=dry_run_only",
            mode_ok,
            None if mode_ok else f"mode={mode!r}",
        ),
        CheckResult(
            "status endpoint scheduler_started=true",
            started_ok,
            None if started_ok else f"scheduler_started={started!r}",
        ),
        body,
    )


def _check_no_ledger_reservation(body: dict) -> CheckResult:
    """The status response surfaces ``ledger.used``; a non-zero value
    means somebody called ``reserve_calls`` against the singleton —
    which would have raised under our patch, so 0 here is the joint
    "no reservation happened" guarantee.
    """
    ledger = body.get("ledger") or {}
    used = ledger.get("used")
    if used == 0:
        return CheckResult("no ledger calls reserved", True)
    return CheckResult(
        "no ledger calls reserved",
        False,
        f"ledger.used={used!r} (expected 0)",
    )


def _check_paid_seams_quiet() -> CheckResult:
    """Gate replaced paid/provider seams with raisers via
    ``no_paid_smoke.guard_no_paid_provider_calls``.  Any invocation
    would have crashed the lifespan / endpoint already; reaching this
    point with the guard active is the proof.
    """
    return CheckResult("no paid/provider seams called", True)


def _check_stop_called_on_shutdown(stop_mock: MagicMock, fake: Any) -> CheckResult:
    if stop_mock.call_count != 1:
        return CheckResult(
            "scheduler stops on shutdown",
            False,
            f"stop_auto_backfill_scheduler called "
            f"{stop_mock.call_count} times (expected 1)",
        )
    args, kwargs = stop_mock.call_args
    if (args and args[0] is fake) or kwargs.get("scheduler") is fake:
        return CheckResult("scheduler stops on shutdown", True)
    return CheckResult(
        "scheduler stops on shutdown",
        False,
        "stop_auto_backfill_scheduler called with wrong scheduler instance",
    )


def _check_app_state_dropped(app: Any) -> CheckResult:
    leftover = getattr(app.state, "auto_backfill_scheduler", None)
    if leftover is None:
        return CheckResult("app.state cleaned after shutdown", True)
    return CheckResult(
        "app.state cleaned after shutdown",
        False,
        f"app.state.auto_backfill_scheduler still set: {leftover!r}",
    )


def _check_no_real_scheduler_thread(
    threads_before: set[str], threads_after: set[str],
) -> CheckResult:
    """APScheduler's ``BackgroundScheduler`` names its executor thread
    ``apscheduler``.  Any new lowercase-apscheduler thread spawned
    across the lifespan run means a real scheduler started despite the
    patches.
    """
    new_threads = threads_after - threads_before
    leaked = sorted(t for t in new_threads if "apscheduler" in t)
    if not leaked:
        return CheckResult("no real apscheduler thread spawned", True)
    return CheckResult(
        "no real apscheduler thread spawned",
        False,
        f"new apscheduler threads observed: {leaked!r}",
    )


def _snapshot_thread_names() -> set[str]:
    return {(t.name or "").lower() for t in threading.enumerate()}


def run_smoke() -> tuple[list[CheckResult], dict[str, Any]]:
    """Run the smoke and return ``(results, diagnostics_body)``.

    Diagnostics body is captured inside the lifespan so callers can
    surface it in the JSON report; an empty dict is returned if the
    endpoint fetch failed.
    """
    # Imports deferred so a no-arg ``--help`` doesn't pull in
    # FastAPI / api.app side-effects.
    import api
    from fastapi.testclient import TestClient
    from scripts.no_paid_smoke import guard_no_paid_provider_calls

    results: list[CheckResult] = []
    body: dict[str, Any] = {}
    fake = _make_fake_scheduler()

    _clear_app_state_scheduler(api.app)
    threads_before = _snapshot_thread_names()

    with _gates_on(), _patched_seams(fake) as mocks, \
            guard_no_paid_provider_calls():
        try:
            with TestClient(api.app) as client:
                results.append(_check_scheduler_attached(api.app, fake))
                mode_check, started_check, body = _check_status_endpoint(client)
                results.append(mode_check)
                results.append(started_check)
                results.append(_check_no_ledger_reservation(body))
                results.append(_check_paid_seams_quiet())
        except Exception as exc:
            results.append(CheckResult(
                "lifespan boot succeeded",
                False,
                f"{type(exc).__name__}: {exc}",
            ))
            _clear_app_state_scheduler(api.app)
            return results, body

        results.append(_check_stop_called_on_shutdown(mocks["stop"], fake))
        results.append(_check_app_state_dropped(api.app))

    threads_after = _snapshot_thread_names()
    results.append(_check_no_real_scheduler_thread(threads_before, threads_after))

    _clear_app_state_scheduler(api.app)
    return results, body


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def summarize(results: list[CheckResult], body: dict) -> dict[str, Any]:
    passed = sum(1 for r in results if r.ok)
    total = len(results)
    return {
        "ok": passed == total,
        "summary": {
            "passed": passed,
            "failed": total - passed,
            "total":  total,
        },
        "checks": [asdict(r) for r in results],
        "diagnostics": body,
    }


def render_table(results: list[CheckResult]) -> str:
    lines = ["Auto-backfill scheduler smoke", ""]
    lines.append(f"{'check':<46} status")
    lines.append(f"{'-' * 46} {'-' * 6}")
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        lines.append(f"{result.name:<46} {status}")
        if result.detail:
            lines.append(f"  -> {result.detail}")
    passed = sum(1 for r in results if r.ok)
    total = len(results)
    lines.append("")
    lines.append(
        f"Summary: {passed}/{total} PASS, {total - passed} FAIL"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Live dry-run smoke check for the auto-backfill scheduler "
            "lifespan boot.  Mocks the scheduler seams so no real "
            "APScheduler thread is spawned."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact table.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out or sys.stdout
    started = time.perf_counter()
    results, body = run_smoke()
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    payload = summarize(results, body)
    payload["elapsed_ms"] = elapsed_ms

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str),
              file=output)
    else:
        print(render_table(results), file=output)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
