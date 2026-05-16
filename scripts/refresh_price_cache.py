#!/usr/bin/env python3
"""Price-cache refresh CLI.

Composes :func:`price_cache_refresh.plan_refresh` with the read-only
input loader to preview which event x ticker windows a refresh would
warm.  Default: dry-run.  ``--write --confirm`` (both required) hands
the plan to a thin executor that issues the cache fetches.

Out of scope (deliberately)
---------------------------
* **No FastAPI route.**  This CLI is invocation-only; it never
  publishes to ``app.state``, never starts a scheduler, never opens
  a socket.
* **No LLM, no analyze_event, no auto-backfill paid path.**  Neither
  the planner nor the executor reaches the LLM seams or
  ``auto_backfill_runner.execute_paid_candidate``; the test suite
  pins these invariants.
* **No archive mutation.**  Only ``price_cache`` rows can ever be
  written, and only via the established ``fetch_daily_cached``
  upsert path.  ``db.save_event`` / ``update_review`` /
  ``append_revisit_snapshot`` are never called.

Three seams keep the CLI hermetic for tests:

* :data:`plan_refresh` — the planner seam.  Tests patch
  ``scripts.refresh_price_cache.plan_refresh`` directly.
* :data:`load_inputs` — the events + cached-dates loader.  Tests
  patch with a stub returning ``([], {})`` so the hermetic path
  never touches SQLite.
* :data:`execute_refresh` — the executor seam invoked only under
  ``--write --confirm``.  Tests patch with a MagicMock so the
  default implementation (which calls ``price_cache.fetch_daily_cached``)
  is never reached.

Usage::

    python scripts/refresh_price_cache.py
    python scripts/refresh_price_cache.py --json
    python scripts/refresh_price_cache.py --max-events 25 --max-provider-calls 20 --json
    python scripts/refresh_price_cache.py --write --confirm
    python scripts/refresh_price_cache.py --write --confirm --json
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from price_cache_refresh import (                              # noqa: E402
    RefreshConfig,
    load_inputs,
    plan_refresh,
    _bday_offset,
    _clean_symbol,
)


# ---------------------------------------------------------------------------
# --focus dry-run buckets — narrow which events the planner sees so the
# operator can target a specific gap without re-deriving the filter logic
# at the call site.  Adding a new bucket = one entry in ``_FOCUS_CHOICES``
# plus one branch in :func:`_apply_focus`.  Default ``"none"`` is a
# pass-through so existing dry-run output is bit-stable.
# ---------------------------------------------------------------------------

FOCUS_NONE: str                = "none"
FOCUS_NO_FORWARD_20D_GAP: str  = "no-forward-20d-gap"

_FOCUS_CHOICES: tuple[str, ...] = (FOCUS_NONE, FOCUS_NO_FORWARD_20D_GAP)


# Defaults pinned by ``docs/price_cache_refresh_design.md`` §5.3.
# Tightening them is low-risk, loosening requires a doc + test update.
_DEFAULT_MAX_EVENTS:         int = RefreshConfig.__dataclass_fields__[
    "max_events"
].default
_DEFAULT_MAX_PROVIDER_CALLS: int = RefreshConfig.__dataclass_fields__[
    "max_provider_calls"
].default


def _apply_focus(
    focus: str,
    events: list[dict],
    cached_by_ticker: dict,
) -> list[dict]:
    """Return ``events`` narrowed to the named focus bucket.

    ``no-forward-20d-gap`` keeps events where at least one ticker's
    cached coverage does not reach ``event_date + 20 business days``.
    A ticker absent from ``cached_by_ticker`` (or with an empty cached
    set) counts as missing 20d coverage — that is exactly the case the
    refresh exists to fix.

    Pure: never reads SQLite, never invokes a provider, returns a new
    list so the caller can still log the unfiltered length.  Unknown
    focus values short-circuit to a pass-through; argparse already
    refuses values outside :data:`_FOCUS_CHOICES`, so a wrong value
    here would only arrive via a programmatic caller — better to
    return the input than to drop events silently.
    """
    if focus != FOCUS_NO_FORWARD_20D_GAP:
        return list(events)

    out: list[dict] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        raw_date = ev.get("event_date")
        if not isinstance(raw_date, str) or not raw_date:
            continue
        try:
            event_date = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        target = _bday_offset(event_date, 20)

        tickers = ev.get("market_tickers") or []
        if not isinstance(tickers, list) or not tickers:
            continue

        any_missing = False
        for raw in tickers:
            symbol = _clean_symbol(
                raw.get("symbol") if isinstance(raw, dict) else raw
            )
            if not symbol:
                continue
            cached = cached_by_ticker.get(symbol) or frozenset()
            if not cached or max(cached) < target:
                any_missing = True
                break
        if any_missing:
            out.append(ev)
    return out


# ---------------------------------------------------------------------------
# Provider/SQLite preflight — surfaces store-level failures (yfinance's
# internal tz/cookie cache, the project events.db) BEFORE the executor
# attempts N provider calls.  Without this, a sandboxed run that cannot
# write outside the project dir produces N silent ``OperationalError(
# 'unable to open database file')`` errors with ok=true, 0 rows
# written, and no visible cause for the operator.
# ---------------------------------------------------------------------------


def _resolve_yfinance_cache_dir() -> Optional[str]:
    """Best-effort resolution of yfinance's tz/cookie cache directory.

    Returns ``None`` when yfinance is not installed or its internal
    layout has shifted — the preflight then skips the yfinance probe
    rather than raising.  Pure: no network, no SQLite.
    """
    override = (
        os.environ.get("SECOND_ORDER_YFINANCE_CACHE_DIR")
        or os.environ.get("YFINANCE_CACHE_DIR")
        or ""
    ).strip()
    try:
        from yfinance.cache import (  # type: ignore[import-not-found]
            _TzDBManager,
            set_cache_location,
        )
    except Exception:
        return None
    if override:
        try:
            set_cache_location(override)
        except Exception:
            return None
    try:
        loc = _TzDBManager.get_location()
    except Exception:
        return None
    return loc if isinstance(loc, str) and loc else None


def _probe_dir_writable(path: Optional[str]) -> tuple[bool, Optional[str]]:
    """Return ``(ok, reason)`` for a directory's writability.

    Uses a uuid-named sentinel file so a parallel preflight cannot
    collide on the same name.  The sentinel is removed on success.
    Read-only: a probe failure does not mutate the directory beyond
    the lifetime of the sentinel attempt.
    """
    if path is None:
        return False, "path-unresolved"
    if not os.path.isdir(path):
        return False, "directory-missing"
    sentinel = os.path.join(path, f".pcr_preflight_{uuid.uuid4().hex}.tmp")
    try:
        with open(sentinel, "w") as fh:
            fh.write("ok")
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    try:
        os.remove(sentinel)
    except Exception:
        # Sentinel write succeeded — that is the property we're
        # checking.  A failed cleanup is logged into the reason but
        # does not flip ok=False.
        return True, "cleanup-failed-but-write-ok"
    return True, None


def _probe_sqlite_writable(
    path: Optional[str],
) -> tuple[bool, Optional[str]]:
    """Return ``(ok, reason)`` for a SQLite file's writability.

    Opens a ``mode=rw`` URI connection, runs ``BEGIN IMMEDIATE`` then
    ``ROLLBACK`` to force the journal-file path SQLite would use under
    a real write.  Never commits; never mutates the database.  ``None``
    or non-existent paths fail closed with a structured reason.
    """
    if not path:
        return False, "path-unresolved"
    if not os.path.isfile(path):
        return False, "file-missing"
    if not os.access(path, os.W_OK):
        return False, "not-writable"
    try:
        with sqlite3.connect(
            f"file:{path}?mode=rw", uri=True, timeout=2.0,
        ) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("ROLLBACK")
    except sqlite3.OperationalError as exc:
        return False, f"OperationalError: {exc}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, None


def _provider_cache_preflight(
    *, db_path: Optional[str] = None,
) -> dict:
    """Read-only writability probe for the executor's downstream stores.

    Probes:

      * yfinance's internal tz/cookie cache directory (typically
        ``%LOCALAPPDATA%/py-yfinance`` on Windows or
        ``~/.cache/py-yfinance`` on POSIX).  A failure here is the
        proximate cause of the ``OperationalError('unable to open
        database file')`` storm seen on sandboxed Windows runs.
      * The project ``events.db`` SQLite file.  ``BEGIN IMMEDIATE``
        forces SQLite to verify it can acquire the write lock — the
        same precondition the executor relies on for INSERT OR REPLACE.

    Pure: no network, no LLM, no provider call, no DDL/DML against
    either store.  Tests patch this function on the cli module so
    failure paths can be exercised without touching the filesystem.
    """
    yf_path = _resolve_yfinance_cache_dir()
    yf_ok, yf_reason = _probe_dir_writable(yf_path)
    db_ok, db_reason = _probe_sqlite_writable(db_path)

    errors: list[str] = []
    if not yf_ok:
        errors.append(
            f"yfinance cache dir not writable "
            f"(path={yf_path or 'unresolved'!s}): {yf_reason}"
        )
    if not db_ok:
        errors.append(
            f"events.db not writable (path={db_path or 'unresolved'!s}): "
            f"{db_reason}"
        )

    return {
        "ok":              yf_ok and db_ok,
        "yfinance_cache":  {"path": yf_path, "ok": yf_ok, "reason": yf_reason},
        "events_db":       {"path": db_path, "ok": db_ok, "reason": db_reason},
        "errors":          errors,
    }


# ---------------------------------------------------------------------------
# DB-path resolution — kept lazy so ``--help`` does not import ``db``.
# ---------------------------------------------------------------------------


def _default_db_path() -> str:
    """Resolve the SQLite path used by ``load_inputs``.

    Lazy import of :mod:`db` keeps a no-arg ``--help`` invocation
    free of ``api`` / FastAPI side-effects.  Tests patch
    :data:`load_inputs` directly so this helper never runs in the
    hermetic suite.
    """
    from db import get_db_path
    return get_db_path()


# ---------------------------------------------------------------------------
# Executor seam — invoked only under ``--write --confirm``
# ---------------------------------------------------------------------------


_EXECUTOR_RESULT_KEYS: tuple[str, ...] = (
    "attempted_jobs",
    "written_rows",
    "errors",
)


def _empty_executor_result() -> dict:
    return {"attempted_jobs": 0, "written_rows": 0, "errors": []}


def _default_execute_refresh(plan: Any, *, config: RefreshConfig) -> dict:
    """Default executor — issues one ``fetch_daily_cached`` per
    ``(symbol, interval)`` pair in ``plan.refresh_jobs``.

    Lazy import of :mod:`price_cache` keeps the dry-run path free of
    the cache module's import side-effects (``_purge_corrupt_rows``
    on first ``_ensure_table``).  The provider is reached only when
    this default executor actually runs — i.e. only under
    ``--write --confirm``.

    Returns a dict with the contract keys ``attempted_jobs`` /
    ``written_rows`` / ``errors``.  Per-interval failures are
    captured into ``errors`` and the run continues so a single bad
    ticker does not block the rest of the plan.
    """
    from price_cache import fetch_daily_cached  # lazy: see docstring

    attempted = 0
    written   = 0
    errors: list[dict] = []

    refresh_jobs = list(getattr(plan, "refresh_jobs", ()) or ())
    for job in refresh_jobs:
        for interval in job.intervals:
            start_iso, end_iso = interval[0], interval[1]
            attempted += 1
            try:
                df = fetch_daily_cached(
                    job.symbol,
                    start=start_iso,
                    end=end_iso,
                    auto_adjust=job.auto_adjust,
                )
            except Exception as exc:
                errors.append({
                    "event_id":       job.event_id,
                    "symbol":         job.symbol,
                    "interval_start": start_iso,
                    "interval_end":   end_iso,
                    "error":          f"{type(exc).__name__}: {exc}",
                })
                continue
            if df is None:
                continue
            try:
                written += int(len(df))
            except Exception:
                pass

    return {
        "attempted_jobs": attempted,
        "written_rows":   written,
        "errors":         errors,
    }


# Module-level binding tests patch via
# ``patch("scripts.refresh_price_cache.execute_refresh", MagicMock(...))``.
execute_refresh = _default_execute_refresh


def _normalise_executor_result(result: Any) -> dict:
    """Normalise the executor return into the contract dict.

    Tolerates dataclass / dict / namespaced returns so a future
    ``RefreshResult`` dataclass drops in without test churn.
    Missing keys collapse to safe zeros / empty list.
    """
    if result is None:
        return _empty_executor_result()
    if dataclasses.is_dataclass(result):
        result = dataclasses.asdict(result)
    if not isinstance(result, dict):
        return _empty_executor_result()

    attempted = result.get("attempted_jobs", 0)
    try:
        attempted = int(attempted)
    except (TypeError, ValueError):
        attempted = 0

    written = result.get("written_rows", 0)
    try:
        written = int(written)
    except (TypeError, ValueError):
        written = 0

    errors = result.get("errors") or []
    if not isinstance(errors, list):
        errors = []

    return {
        "attempted_jobs": attempted,
        "written_rows":   written,
        "errors":         errors,
    }


# ---------------------------------------------------------------------------
# Plan -> dict normalisation + payload composition
# ---------------------------------------------------------------------------


def _group_jobs_by_event(refresh_jobs: Sequence[Any]) -> list[dict]:
    """Collapse the planner's flat ``(event, ticker)`` job list into the
    per-event view the report renders.

    Deterministic order: events appear in the order their first job is
    encountered (the planner already orders events by
    ``event_date desc, id desc``); tickers within an event preserve the
    planner's encounter order too.
    """
    grouped: dict[int, dict] = {}
    order: list[int] = []
    for job in refresh_jobs:
        event_id = job.event_id
        if event_id not in grouped:
            grouped[event_id] = {
                "event_id":   event_id,
                "event_date": job.event_date,
                "tickers":    [],
            }
            order.append(event_id)
        grouped[event_id]["tickers"].append({
            "symbol":        job.symbol,
            "intervals":     [list(iv) for iv in job.intervals],
            "interval_count":job.provider_calls,
            "business_days": job.business_days,
            "auto_adjust":   job.auto_adjust,
        })
    return [grouped[eid] for eid in order]


def _plan_to_dict(plan: Any) -> dict:
    """Normalise a ``RefreshPlan`` dataclass (or a dict-shaped stub
    from a test) into a JSON-friendly view.
    """
    if isinstance(plan, dict):
        return plan
    if dataclasses.is_dataclass(plan):
        refresh_jobs = list(getattr(plan, "refresh_jobs", ()) or ())
        skip_counts = dict(getattr(plan, "skipped_counts", {}) or {})
        return {
            "decision_reason":         getattr(plan, "decision_reason", "no_work"),
            "events_considered":       int(getattr(plan, "events_considered", 0)),
            "tickers_considered":      int(getattr(plan, "tickers_considered", 0)),
            "events_planned":          len({j.event_id for j in refresh_jobs}),
            "unique_tickers":          len({j.symbol for j in refresh_jobs}),
            "total_business_days":     sum(j.business_days for j in refresh_jobs),
            "provider_calls_estimate": int(getattr(plan, "provider_calls_estimate", 0)),
            "max_provider_calls":      int(getattr(plan, "max_provider_calls", 0)),
            "cap_applied":             bool(getattr(plan, "cap_applied", False)),
            "skipped_counts":          skip_counts,
            "events":                  _group_jobs_by_event(refresh_jobs),
        }
    if hasattr(plan, "to_dict"):
        try:
            out = plan.to_dict()
        except Exception:
            out = {}
        return out if isinstance(out, dict) else {}
    return {}


def _compose_payload(
    *,
    plan_dict: dict,
    caps: dict,
    now_iso: str,
    mode: str,
    confirmed: bool,
    executor_result: dict,
    focus: str = FOCUS_NONE,
    error_message: str | None = None,
) -> dict:
    """Wrap the normalised plan + executor result in the outer envelope.

    Top-level keys ``mode`` / ``confirmed`` / ``attempted_jobs`` /
    ``written_rows`` / ``errors`` are pinned by the task's JSON
    contract.  Plan + cap fields stay at the top level too so the
    dry-run shape from the previous CLI iteration remains intact for
    operator panels that already consume it.

    ``error_message`` is set when ``--write`` was passed without
    ``--confirm`` so the JSON carries a human-readable reason
    alongside the structured ``mode="write"`` / ``confirmed=false``
    flags.
    """
    payload: dict = {
        "ok":                      error_message is None,
        "now":                     now_iso,
        "mode":                    mode,
        "confirmed":               confirmed,
        "focus":                   focus,
        "attempted_jobs":          executor_result["attempted_jobs"],
        "written_rows":            executor_result["written_rows"],
        "errors":                  executor_result["errors"],
        "decision_reason":         plan_dict.get("decision_reason", "no_work"),
        "caps":                    caps,
        "events_considered":       plan_dict.get("events_considered",       0),
        "tickers_considered":      plan_dict.get("tickers_considered",      0),
        "events_planned":          plan_dict.get("events_planned",          0),
        "unique_tickers":          plan_dict.get("unique_tickers",          0),
        "total_business_days":     plan_dict.get("total_business_days",     0),
        "provider_calls_estimate": plan_dict.get("provider_calls_estimate", 0),
        "max_provider_calls":      plan_dict.get("max_provider_calls",      caps["max_provider_calls"]),
        "cap_applied":             plan_dict.get("cap_applied",             False),
        "skipped_counts":          plan_dict.get("skipped_counts",          {}),
        "events":                  plan_dict.get("events",                  []),
    }
    if error_message is not None:
        payload["error"] = error_message
    return payload


# ---------------------------------------------------------------------------
# Preflight-only payload — slim envelope used by ``--preflight-only``.  The
# verbose dry-run shape (caps / events_considered / skipped_counts) would
# only carry zeros on this branch and would muddy what "preflight mode"
# means; the helper below keeps the contract surface to the keys the task
# brief pins (ok, mode, focus, preflight, errors) plus ``now`` so the
# timestamp story matches the other modes.
# ---------------------------------------------------------------------------


def _compose_preflight_payload(
    *,
    preflight: dict,
    focus: str,
    now_iso: str,
) -> dict:
    return {
        "ok":        bool(preflight.get("ok")),
        "now":       now_iso,
        "mode":      "preflight",
        "focus":     focus,
        "preflight": preflight,
        "errors":    list(preflight.get("errors") or []),
    }


def _render_preflight_text(payload: dict) -> str:
    pf = payload.get("preflight") or {}
    yf = pf.get("yfinance_cache") or {}
    db = pf.get("events_db")      or {}
    lines: list[str] = ["Price-cache refresh preflight", ""]
    lines.append(f"Mode:  {payload.get('mode', 'preflight')}")
    lines.append(f"Focus: {payload.get('focus', FOCUS_NONE)}")
    lines.append(f"ok:    {payload.get('ok')}")
    lines.append("")
    lines.append(
        f"yfinance_cache: ok={yf.get('ok')!s:<5} "
        f"path={yf.get('path') or '(unresolved)'}"
    )
    if not yf.get("ok"):
        lines.append(f"  reason: {yf.get('reason')}")
    lines.append(
        f"events_db:      ok={db.get('ok')!s:<5} "
        f"path={db.get('path') or '(unresolved)'}"
    )
    if not db.get("ok"):
        lines.append(f"  reason: {db.get('reason')}")
    errors = payload.get("errors") or []
    if errors:
        lines.append("")
        lines.append(f"Errors ({len(errors)}):")
        for msg in errors:
            lines.append(f"  - {msg}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


def _render_text(payload: dict) -> str:
    mode = payload.get("mode", "dry_run")
    confirmed = bool(payload.get("confirmed"))
    header = "Price-cache refresh dry-run" if mode == "dry_run" else "Price-cache refresh write mode"
    lines: list[str] = [header, ""]
    lines.append(f"Mode: {mode}  confirmed={str(confirmed).lower()}")
    focus = payload.get("focus") or FOCUS_NONE
    if focus != FOCUS_NONE:
        lines.append(f"Focus: {focus}")
    err = payload.get("error")
    if err:
        lines.append(f"Error: {err}")
    if mode == "write" and confirmed:
        lines.append(
            f"Executor: attempted_jobs={payload.get('attempted_jobs', 0)} "
            f"written_rows={payload.get('written_rows', 0)} "
            f"errors={len(payload.get('errors') or [])}"
        )
    lines.append("")
    lines.append(f"Decision reason: {payload.get('decision_reason', '-')}")
    caps = payload.get("caps", {})
    lines.append(
        f"Caps: max_events={caps.get('max_events')!s} "
        f"max_provider_calls={caps.get('max_provider_calls')!s}"
    )
    if payload.get("cap_applied"):
        lines.append("(cap applied - some events were dropped)")
    lines.append("")

    lines.append("Selection:")
    for key in (
        "events_considered",
        "tickers_considered",
        "events_planned",
        "unique_tickers",
        "total_business_days",
        "provider_calls_estimate",
    ):
        lines.append(f"  {key:<28} {payload.get(key, 0)}")

    lines.append("")
    lines.append("Skip counts:")
    skipped = payload.get("skipped_counts", {}) or {}
    if not skipped:
        lines.append("  (none)")
    else:
        for reason, count in skipped.items():
            lines.append(f"  {reason:<28} {count}")

    events = payload.get("events", []) or []
    if events:
        lines.append("")
        lines.append(f"Planned events ({len(events)}):")
        for index, event in enumerate(events, start=1):
            event_id   = event.get("event_id")
            event_date = event.get("event_date")
            tickers    = event.get("tickers") or []
            lines.append(
                f"  {index:>3}. event_id={event_id} event_date={event_date}"
            )
            for ticker in tickers:
                symbol         = ticker.get("symbol")
                interval_count = ticker.get("interval_count", 0)
                bdays          = ticker.get("business_days",  0)
                intervals      = ticker.get("intervals")      or []
                window_str = (
                    f"{intervals[0][0]}..{intervals[-1][-1]}"
                    if intervals
                    else "-"
                )
                lines.append(
                    f"        - {symbol:<10} intervals={interval_count} "
                    f"business_days={bdays} window={window_str}"
                )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run preview of the price-cache refresh planner.  "
            "Reports which event x ticker windows a refresh would warm "
            "without invoking any provider, LLM, or paid path."
        ),
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=_DEFAULT_MAX_EVENTS,
        help=(
            "Maximum number of events the planner is allowed to "
            f"include after filtering.  Default: {_DEFAULT_MAX_EVENTS}."
        ),
    )
    parser.add_argument(
        "--max-provider-calls",
        type=int,
        default=_DEFAULT_MAX_PROVIDER_CALLS,
        help=(
            "Run-level cap on the planner's provider-call estimate.  "
            f"Default: {_DEFAULT_MAX_PROVIDER_CALLS}."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=(
            "Run the planner AND invoke the executor.  Requires "
            "--confirm; without --confirm this CLI exits non-zero "
            "and writes nothing."
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Confirmation flag required alongside --write before any "
            "provider call is issued.  Has no effect on its own; the "
            "default remains dry-run."
        ),
    )
    parser.add_argument(
        "--focus",
        choices=list(_FOCUS_CHOICES),
        default=FOCUS_NONE,
        help=(
            "Narrow the planner's input to a named gap bucket.  "
            "'no-forward-20d-gap' keeps events whose tickers do not "
            "yet reach event_date + 20 business days in the cache.  "
            "Default: 'none' (no filter)."
        ),
    )
    parser.add_argument(
        "--preflight-only",
        dest="preflight_only",
        action="store_true",
        help=(
            "Run only the provider-cache / events.db writability "
            "preflight and exit before the planner or executor is "
            "reached.  No provider calls, no DB writes; --confirm is "
            "not required.  Takes precedence over --write when both "
            "are passed.  Combine with --focus to label the run."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    focus = getattr(args, "focus", FOCUS_NONE) or FOCUS_NONE

    # ``--preflight-only`` short-circuits BEFORE load_inputs / plan_refresh /
    # the executor.  The brief pins this ordering: no provider calls, no DB
    # reads via the loader, no DB writes, and no ``--confirm`` requirement.
    # Calling ``_provider_cache_preflight`` is the only DB / filesystem touch
    # — and it is read-only (mode=rw + BEGIN IMMEDIATE + ROLLBACK on the
    # SQLite probe; sentinel-file write+remove on the dir probe).
    if getattr(args, "preflight_only", False):
        preflight = _provider_cache_preflight(db_path=_default_db_path())
        payload = _compose_preflight_payload(
            preflight=preflight,
            focus=focus,
            now_iso=_now_iso(),
        )
        if args.json:
            print(_render_json(payload), file=output)
        else:
            print(_render_preflight_text(payload), file=output)
        return 0 if payload["ok"] else 1

    caps = {
        "max_events":         int(args.max_events),
        "max_provider_calls": int(args.max_provider_calls),
    }
    cfg = RefreshConfig(
        max_events=caps["max_events"],
        max_provider_calls=caps["max_provider_calls"],
    )

    try:
        events, cached_by_ticker = load_inputs(_default_db_path())
    except Exception:
        # Read-only loader degrades to empty inputs on any DB failure
        # so the dry-run still produces a stable report.
        events, cached_by_ticker = [], {}

    if focus != FOCUS_NONE:
        events = _apply_focus(focus, events, cached_by_ticker)

    plan = plan_refresh(events, cached_by_ticker, config=cfg)
    plan_dict = _plan_to_dict(plan)
    now_iso = _now_iso()

    # Three-branch decision tree:
    #   1. --write and not --confirm → exit 1, executor NEVER called.
    #   2. --write and --confirm     → executor called once; exit 1 only
    #                                   if it reports errors.
    #   3. otherwise (dry-run)       → executor never called, exit 0.
    # ``--confirm`` alone is silently treated as dry-run; the design
    # doc reserves the warn / error path for a future iteration.
    write_requested = bool(args.write)
    confirmed       = write_requested and bool(args.confirm)

    if write_requested and not args.confirm:
        payload = _compose_payload(
            plan_dict=plan_dict,
            caps=caps,
            now_iso=now_iso,
            mode="write",
            confirmed=False,
            executor_result=_empty_executor_result(),
            focus=focus,
            error_message=(
                "--write requires --confirm; refusing to run the "
                "executor.  Re-run with both flags to issue provider "
                "calls."
            ),
        )
        exit_code = 1
    elif confirmed:
        # Preflight runs ONLY in the confirmed-write branch; dry-run
        # and write-without-confirm paths skip it so a sandboxed dev
        # box can still produce a stable dry-run payload.
        preflight = _provider_cache_preflight(db_path=_default_db_path())
        if not preflight["ok"]:
            executor_result = _empty_executor_result()
            for msg in preflight["errors"]:
                executor_result["errors"].append({
                    "event_id":       None,
                    "symbol":         None,
                    "interval_start": None,
                    "interval_end":   None,
                    "error":          f"PreflightError: {msg}",
                })
            payload = _compose_payload(
                plan_dict=plan_dict,
                caps=caps,
                now_iso=now_iso,
                mode="write",
                confirmed=True,
                executor_result=executor_result,
                focus=focus,
                error_message=(
                    "provider-cache preflight failed; refusing to "
                    "invoke the executor.  Re-run after fixing the "
                    "reported store(s)."
                ),
            )
            payload["preflight"] = preflight
            exit_code = 1
        else:
            try:
                raw_result = execute_refresh(plan, config=cfg)
            except Exception as exc:
                executor_result = _empty_executor_result()
                executor_result["errors"].append({
                    "event_id":       None,
                    "symbol":         None,
                    "interval_start": None,
                    "interval_end":   None,
                    "error":          f"{type(exc).__name__}: {exc}",
                })
            else:
                executor_result = _normalise_executor_result(raw_result)
            payload = _compose_payload(
                plan_dict=plan_dict,
                caps=caps,
                now_iso=now_iso,
                mode="write",
                confirmed=True,
                executor_result=executor_result,
                focus=focus,
            )
            payload["preflight"] = preflight
            exit_code = 1 if executor_result["errors"] else 0
    else:
        payload = _compose_payload(
            plan_dict=plan_dict,
            caps=caps,
            now_iso=now_iso,
            mode="dry_run",
            confirmed=False,
            executor_result=_empty_executor_result(),
            focus=focus,
        )
        exit_code = 0

    if args.json:
        print(_render_json(payload), file=output)
    else:
        print(_render_text(payload), file=output)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
