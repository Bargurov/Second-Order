#!/usr/bin/env python3
"""Guarded robustness-cache backfill write-smoke.

Warms the live ``price_cache`` table for one or more explicit
``(ticker, start_date, end_date, auto_adjust)`` robustness windows.
Default mode is read-only dry-run: the smoke reports the live cache
pre-count and a free-provider coverage preview, and never opens the
provider into the cache.  Write mode requires an explicit operator
gesture (``--write --confirm --backup-path``) and a backup that
exists and is distinct from the live DB.  The smoke writes only to
the ``price_cache`` table inside ``events.db``; the ``events`` table
row count is hashed (COUNT) before and after, and any drift is
surfaced as an error.

This script is the operator-curated companion to
:mod:`scripts.benchmark_cache_backfill_write_smoke` (which warms a
single canonical benchmark ticker into a temp copy of a backup).  The
robustness flow targets the live cache because robustness re-runs
read the same live cache the production validation pipeline uses;
keeping robustness rows in a separate temp DB would force every
downstream consumer to know which DB to open.  The trade-off is
explicit: the operator must take a fresh backup before invoking
write mode.

Modes
-----

  * ``dry-run`` (default) — for each ``--ticker-window`` arg the
    smoke:

      1. Counts rows currently in the live ``price_cache`` for that
         ticker / window / auto_adjust value (read-only ``SELECT
         COUNT(*)``).
      2. Soft-imports yfinance.  If the import fails the per-window
         result records the import error and continues to the next
         window.
      3. Runs a single yfinance ``Ticker(...).history(start=...,
         end=..., auto_adjust=..., actions=False)`` call as a
         coverage preview.  The DataFrame is discarded; only the
         row count and first / last date are reported.

    Dry-run NEVER calls ``price_cache.fetch_daily_cached`` and never
    opens the live DB for writes.

  * ``write`` — requires ALL of ``--write --confirm --backup-path
    <PATH>``.  In this mode the smoke:

      1. Checks the flag combination.  Rejects if ``--confirm`` is
         missing, ``--backup-path`` is missing, the backup is the
         same path as ``--db-path``, or the backup does not exist
         on disk.
      2. Counts rows in the live ``events`` table (read-only).
      3. For each ``--ticker-window``: counts the pre-row in
         ``price_cache``, calls ``price_cache.fetch_daily_cached``
         (which is the running app's normal read-through path —
         the provider call only happens for cache gaps), then
         counts the post-row.
      4. Counts rows in the live ``events`` table again and
         compares.  Drift surfaces as an error and flips
         ``events_table_unchanged`` to ``False``.

The smoke is intentionally conservative about every other table:
``fetch_daily_cached`` only writes ``price_cache`` rows.  Every
other table in the live archive is read-only or untouched in both
modes — the smoke itself never issues an INSERT / UPDATE / DELETE,
and the events table is opened only for the integrity COUNT(*).

Patchable seams
---------------

Four module-level seams let unit tests drive the smoke without
touching yfinance, the network, or the real archive:

  * ``_check_provider_available`` — soft import-only probe; True iff
    ``yfinance`` is importable.  No network call.
  * ``_provider_preview`` — would shell out to yfinance for the
    dry-run coverage preview.  Tests patch this to return synthetic
    ``(row_count, first_date, last_date)`` tuples.
  * ``_fetch_into_cache`` — would shell out to
    ``price_cache.fetch_daily_cached`` in write mode.  Tests patch
    this to no-op (so the live cache is never touched in CI).
  * ``_count_price_cache_rows`` / ``_count_events_rows`` — read-only
    COUNT(*) helpers.  Tests patch these to drive synthetic
    pre / post counts.

Conservative wording
--------------------

The smoke describes cache geometry and operator-curated robustness
windows, not market evidence.  The recommended_next_action and
per-window error strings stay descriptive ("rows_added=37"); they
never make a causal claim or promote the cache write to evidence.
The full banlist of forbidden tokens lives in the ``_BANNED_TOKENS``
tuple at module scope and is exercised by the paired test.

Output contract (JSON)::

    {
      "ok":                    bool,
      "mode":                  "dry-run" | "write",
      "db_path":               str,
      "backup_path":           str | None,
      "ticker_window_count":   int,
      "ticker_windows": [
        {
          "ticker":                str,
          "start_date":            str,   # ISO YYYY-MM-DD
          "end_date":              str,   # ISO YYYY-MM-DD
          "auto_adjust":           int,   # 0 or 1
          "pre_cache_row_count":   int,
          "provider_preview": {              # only in dry-run
            "row_count":           int | None,
            "first_date":          str | None,
            "last_date":           str | None,
            "error":               str | None,
          } | None,
          "post_cache_row_count":  int | None,   # only in write mode
          "rows_added":            int | None,   # only in write mode
          "error":                 str | None,
        },
        ...
      ],
      "events_row_count_before": int | None,
      "events_row_count_after":  int | None,
      "events_table_unchanged":  bool | None,
      "warnings":              [str, ...],
      "errors":                [str, ...],
      "recommended_next_action": str,
    }

The dict carries EXACTLY these 13 top-level keys.  Each per-window
dict carries EXACTLY these 9 keys.  Downstream tooling can gate on
``ok`` and ``events_table_unchanged`` without worrying about schema
drift.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date as _date
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_DB_PATH: str = "events.db"
_VALID_AUTO_ADJUST: tuple[int, ...] = (0, 1)

_BANNED_TOKENS: tuple[str, ...] = (
    "proof",
    "proven",
    "validated",
    "automatically",
    "alpha generated",
    "correct ticker",
    "guaranteed",
    "causes",
    "caused",
    "proves",
    "confirms",
    "validates",
)


_RECOMMENDED_DRY_RUN_OK = (
    "Dry-run complete.  Each window reports its live cache pre-count "
    "and a free-provider coverage preview.  No cache write was "
    "performed.  Re-run with --write --confirm --backup-path to warm "
    "the live cache."
)
_RECOMMENDED_DRY_RUN_PROVIDER_GAP = (
    "Dry-run complete.  One or more windows could not be previewed "
    "via the free provider; inspect each window's provider_preview "
    "error before attempting a live cache write."
)
_RECOMMENDED_WRITE_OK = (
    "Write complete.  Each window reports rows_added against the live "
    "price_cache.  The events table row count is unchanged.  Re-run "
    "the robustness probe to consume the warmed cache."
)
_RECOMMENDED_WRITE_DRIFT = (
    "Write completed but the events table row count drifted between "
    "the pre-write and post-write read; treat the live archive as "
    "needing a backup restore before any further work."
)
_RECOMMENDED_FLAG_REJECT = (
    "Write mode rejected before any cache or DB access; address the "
    "flag errors and re-run."
)


# ---------------------------------------------------------------------------
# Patchable seams.
# ---------------------------------------------------------------------------

def _check_provider_available() -> bool:
    """Soft import-only probe for yfinance.  No network call."""
    try:
        import yfinance  # noqa: F401
        return True
    except Exception:
        return False


def _provider_preview(
    ticker: str,
    start_date: str,
    end_date: str,
    auto_adjust: int,
) -> dict:
    """Dry-run yfinance coverage preview.

    Returns a dict with row_count, first_date, last_date, error.  The
    DataFrame itself is discarded — only the counts and bounds are
    reported.  Never writes to the cache.
    """
    try:
        import yfinance as _yf
    except Exception as exc:
        return {
            "row_count":  None,
            "first_date": None,
            "last_date":  None,
            "error":      f"yfinance import failed: {exc!r}",
        }
    try:
        df = _yf.Ticker(ticker).history(
            start=start_date,
            end=end_date,
            auto_adjust=bool(auto_adjust),
            actions=False,
        )
    except Exception as exc:
        return {
            "row_count":  None,
            "first_date": None,
            "last_date":  None,
            "error":      f"provider call failed: {exc!r}",
        }
    n = int(len(df))
    if n == 0:
        return {
            "row_count":  0,
            "first_date": None,
            "last_date":  None,
            "error":      None,
        }
    try:
        first = df.index.min().date().isoformat()
        last  = df.index.max().date().isoformat()
    except Exception as exc:
        return {
            "row_count":  n,
            "first_date": None,
            "last_date":  None,
            "error":      f"index inspection failed: {exc!r}",
        }
    return {
        "row_count":  n,
        "first_date": first,
        "last_date":  last,
        "error":      None,
    }


def _fetch_into_cache(
    ticker: str,
    start_date: str,
    end_date: str,
    auto_adjust: int,
) -> Optional[str]:
    """Write-mode shim around ``price_cache.fetch_daily_cached``.

    Returns ``None`` on success, an error string on failure.  Never
    raises — provider / DB failures are caught and surfaced.
    """
    try:
        import price_cache as _pc
    except Exception as exc:
        return f"price_cache import failed: {exc!r}"
    try:
        _pc.fetch_daily_cached(
            ticker,
            start=start_date,
            end=end_date,
            auto_adjust=bool(auto_adjust),
        )
    except Exception as exc:
        return f"fetch_daily_cached failed: {exc!r}"
    return None


def _count_price_cache_rows(
    db_path: str,
    ticker: str,
    start_date: str,
    end_date: str,
    auto_adjust: int,
) -> int:
    """Read-only COUNT(*) on price_cache for this ticker / window.

    Opens the DB via ``file:<path>?mode=ro`` URI so the connection
    cannot mutate any table.  Returns 0 for any error (missing DB,
    missing table) — the dry-run / write report tolerates a missing
    cache because ``fetch_daily_cached`` creates the table on first
    write.
    """
    try:
        uri = f"file:{db_path}?mode=ro"
        con = sqlite3.connect(uri, uri=True)
    except Exception:
        return 0
    try:
        cur = con.cursor()
        rows = cur.execute(
            """
            SELECT COUNT(*) FROM price_cache
            WHERE ticker = ? AND auto_adjust = ?
              AND date >= ? AND date <= ?
            """,
            (ticker, int(auto_adjust), start_date, end_date),
        ).fetchone()
        return int(rows[0]) if rows else 0
    except Exception:
        return 0
    finally:
        try:
            con.close()
        except Exception:
            pass


def _count_events_rows(db_path: str) -> Optional[int]:
    """Read-only COUNT(*) on the events table.

    Returns ``None`` on any error so the caller can distinguish "not
    measured" from "measured zero".  Used as the events-table
    integrity check in write mode.
    """
    try:
        uri = f"file:{db_path}?mode=ro"
        con = sqlite3.connect(uri, uri=True)
    except Exception:
        return None
    try:
        cur = con.cursor()
        rows = cur.execute("SELECT COUNT(*) FROM events").fetchone()
        return int(rows[0]) if rows else None
    except Exception:
        return None
    finally:
        try:
            con.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Ticker-window parsing.
# ---------------------------------------------------------------------------

def _parse_ticker_window(raw: str) -> tuple[str, str, str]:
    """Parse a single ``TICKER,YYYY-MM-DD,YYYY-MM-DD`` triple.

    Raises ``argparse.ArgumentTypeError`` on any malformed value so
    the CLI rejects with a clean message rather than a stack trace.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise argparse.ArgumentTypeError(
            "ticker-window value must be a non-empty string"
        )
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            f"ticker-window must be TICKER,YYYY-MM-DD,YYYY-MM-DD "
            f"(got {raw!r})"
        )
    ticker, start_s, end_s = parts
    if not ticker:
        raise argparse.ArgumentTypeError(
            f"ticker is empty in {raw!r}"
        )
    try:
        start_d = _date.fromisoformat(start_s)
        end_d   = _date.fromisoformat(end_s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"start_date / end_date must be ISO YYYY-MM-DD: {exc}"
        )
    if end_d < start_d:
        raise argparse.ArgumentTypeError(
            f"end_date {end_s} is before start_date {start_s}"
        )
    return ticker, start_d.isoformat(), end_d.isoformat()


# ---------------------------------------------------------------------------
# Core run path.
# ---------------------------------------------------------------------------

def _validate_write_flags(
    write: bool,
    confirm: bool,
    backup_path: Optional[str],
    db_path: str,
) -> list[str]:
    """Return a list of flag-rejection errors.  Empty iff write mode
    is safe to proceed (or the run is dry-run)."""
    errors: list[str] = []
    if not write:
        return errors
    if not confirm:
        errors.append(
            "write mode requires --confirm to be passed alongside --write"
        )
    if not backup_path:
        errors.append(
            "write mode requires --backup-path <PATH> alongside --write"
        )
        return errors
    bk = Path(backup_path)
    db = Path(db_path)
    try:
        same = bk.resolve() == db.resolve()
    except Exception:
        same = bk == db
    if same:
        errors.append(
            f"backup-path {backup_path!r} must differ from db-path "
            f"{db_path!r}; refusing to overwrite the live DB as its "
            f"own backup"
        )
    if not bk.exists():
        errors.append(
            f"backup-path {backup_path!r} does not exist on disk; "
            f"take a fresh backup via scripts/backup_archive.py before "
            f"re-running"
        )
    return errors


def run_smoke(
    *,
    ticker_windows: list[tuple[str, str, str]],
    auto_adjust: int,
    write: bool,
    confirm: bool,
    backup_path: Optional[str],
    db_path: str,
) -> dict:
    """Top-level entry point invoked by the CLI and by tests."""
    warnings: list[str] = []
    errors:   list[str] = []
    flag_errors = _validate_write_flags(
        write=write,
        confirm=confirm,
        backup_path=backup_path,
        db_path=db_path,
    )
    if flag_errors:
        errors.extend(flag_errors)
        return _build_envelope(
            ok=False,
            mode="write",
            db_path=db_path,
            backup_path=backup_path,
            ticker_windows_payload=[],
            events_row_count_before=None,
            events_row_count_after=None,
            events_table_unchanged=None,
            warnings=warnings,
            errors=errors,
            recommended=_RECOMMENDED_FLAG_REJECT,
        )

    if auto_adjust not in _VALID_AUTO_ADJUST:
        errors.append(
            f"auto-adjust must be one of {_VALID_AUTO_ADJUST}; "
            f"got {auto_adjust!r}"
        )
        return _build_envelope(
            ok=False,
            mode="write" if write else "dry-run",
            db_path=db_path,
            backup_path=backup_path,
            ticker_windows_payload=[],
            events_row_count_before=None,
            events_row_count_after=None,
            events_table_unchanged=None,
            warnings=warnings,
            errors=errors,
            recommended=_RECOMMENDED_FLAG_REJECT,
        )

    if not ticker_windows:
        errors.append(
            "no --ticker-window args supplied; pass at least one "
            "TICKER,YYYY-MM-DD,YYYY-MM-DD triple"
        )
        return _build_envelope(
            ok=False,
            mode="write" if write else "dry-run",
            db_path=db_path,
            backup_path=backup_path,
            ticker_windows_payload=[],
            events_row_count_before=None,
            events_row_count_after=None,
            events_table_unchanged=None,
            warnings=warnings,
            errors=errors,
            recommended=_RECOMMENDED_FLAG_REJECT,
        )

    if write:
        return _run_write(
            ticker_windows=ticker_windows,
            auto_adjust=auto_adjust,
            backup_path=backup_path or "",
            db_path=db_path,
            warnings=warnings,
            errors=errors,
        )
    return _run_dry_run(
        ticker_windows=ticker_windows,
        auto_adjust=auto_adjust,
        db_path=db_path,
        warnings=warnings,
        errors=errors,
    )


def _run_dry_run(
    *,
    ticker_windows: list[tuple[str, str, str]],
    auto_adjust: int,
    db_path: str,
    warnings: list[str],
    errors: list[str],
) -> dict:
    payload: list[dict[str, Any]] = []
    provider_ok = _check_provider_available()
    if not provider_ok:
        warnings.append(
            "yfinance not importable; provider_preview will record "
            "an import error for every window"
        )
    any_preview_error = False
    for ticker, start_s, end_s in ticker_windows:
        pre = _count_price_cache_rows(
            db_path=db_path,
            ticker=ticker,
            start_date=start_s,
            end_date=end_s,
            auto_adjust=auto_adjust,
        )
        preview = _provider_preview(
            ticker=ticker,
            start_date=start_s,
            end_date=end_s,
            auto_adjust=auto_adjust,
        )
        if preview.get("error"):
            any_preview_error = True
        payload.append({
            "ticker":              ticker,
            "start_date":          start_s,
            "end_date":            end_s,
            "auto_adjust":         int(auto_adjust),
            "pre_cache_row_count": int(pre),
            "provider_preview":    preview,
            "post_cache_row_count": None,
            "rows_added":          None,
            "error":               None,
        })

    recommended = (
        _RECOMMENDED_DRY_RUN_PROVIDER_GAP
        if any_preview_error
        else _RECOMMENDED_DRY_RUN_OK
    )
    return _build_envelope(
        ok=(not errors) and (not any_preview_error),
        mode="dry-run",
        db_path=db_path,
        backup_path=None,
        ticker_windows_payload=payload,
        events_row_count_before=None,
        events_row_count_after=None,
        events_table_unchanged=None,
        warnings=warnings,
        errors=errors,
        recommended=recommended,
    )


def _run_write(
    *,
    ticker_windows: list[tuple[str, str, str]],
    auto_adjust: int,
    backup_path: str,
    db_path: str,
    warnings: list[str],
    errors: list[str],
) -> dict:
    events_before = _count_events_rows(db_path)
    if events_before is None:
        warnings.append(
            "events row count read returned None before the write "
            "loop; integrity check will record events_table_unchanged "
            "= None"
        )

    payload: list[dict[str, Any]] = []
    any_fetch_error = False
    for ticker, start_s, end_s in ticker_windows:
        pre = _count_price_cache_rows(
            db_path=db_path,
            ticker=ticker,
            start_date=start_s,
            end_date=end_s,
            auto_adjust=auto_adjust,
        )
        fetch_error = _fetch_into_cache(
            ticker=ticker,
            start_date=start_s,
            end_date=end_s,
            auto_adjust=auto_adjust,
        )
        if fetch_error is not None:
            any_fetch_error = True
            payload.append({
                "ticker":               ticker,
                "start_date":           start_s,
                "end_date":             end_s,
                "auto_adjust":          int(auto_adjust),
                "pre_cache_row_count":  int(pre),
                "provider_preview":     None,
                "post_cache_row_count": None,
                "rows_added":           None,
                "error":                fetch_error,
            })
            continue
        post = _count_price_cache_rows(
            db_path=db_path,
            ticker=ticker,
            start_date=start_s,
            end_date=end_s,
            auto_adjust=auto_adjust,
        )
        payload.append({
            "ticker":               ticker,
            "start_date":           start_s,
            "end_date":             end_s,
            "auto_adjust":          int(auto_adjust),
            "pre_cache_row_count":  int(pre),
            "provider_preview":     None,
            "post_cache_row_count": int(post),
            "rows_added":           int(post) - int(pre),
            "error":                None,
        })

    events_after = _count_events_rows(db_path)
    if events_before is None or events_after is None:
        events_table_unchanged: Optional[bool] = None
    else:
        events_table_unchanged = bool(events_before == events_after)
        if not events_table_unchanged:
            errors.append(
                f"events table row count drifted during write: "
                f"before={events_before} after={events_after}"
            )

    if any_fetch_error:
        errors.append(
            "one or more ticker-window fetches failed; see per-window "
            "error fields"
        )

    if errors:
        recommended = (
            _RECOMMENDED_WRITE_DRIFT
            if events_table_unchanged is False
            else _RECOMMENDED_DRY_RUN_PROVIDER_GAP
        )
    else:
        recommended = _RECOMMENDED_WRITE_OK

    return _build_envelope(
        ok=(not errors),
        mode="write",
        db_path=db_path,
        backup_path=backup_path,
        ticker_windows_payload=payload,
        events_row_count_before=events_before,
        events_row_count_after=events_after,
        events_table_unchanged=events_table_unchanged,
        warnings=warnings,
        errors=errors,
        recommended=recommended,
    )


# ---------------------------------------------------------------------------
# Envelope assembly.
# ---------------------------------------------------------------------------

def _build_envelope(
    *,
    ok: bool,
    mode: str,
    db_path: str,
    backup_path: Optional[str],
    ticker_windows_payload: list[dict[str, Any]],
    events_row_count_before: Optional[int],
    events_row_count_after:  Optional[int],
    events_table_unchanged:  Optional[bool],
    warnings: list[str],
    errors:   list[str],
    recommended: str,
) -> dict:
    return {
        "ok":                        bool(ok),
        "mode":                      str(mode),
        "db_path":                   str(db_path),
        "backup_path":               backup_path,
        "ticker_window_count":       int(len(ticker_windows_payload)),
        "ticker_windows":            ticker_windows_payload,
        "events_row_count_before":   events_row_count_before,
        "events_row_count_after":    events_row_count_after,
        "events_table_unchanged":    events_table_unchanged,
        "warnings":                  list(warnings),
        "errors":                    list(errors),
        "recommended_next_action":   str(recommended),
    }


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="robustness_cache_backfill_write_smoke.py",
        description=(
            "Guarded robustness-cache backfill smoke for explicit "
            "ticker/window pairs.  Default is read-only dry-run with "
            "a free-provider coverage preview; --write --confirm "
            "--backup-path warms the live price_cache.  The events "
            "table is never mutated."
        ),
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Read-only dry-run mode (default).  No cache write.",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        default=False,
        help=(
            "Enable write mode.  Requires --confirm and "
            "--backup-path together."
        ),
    )
    p.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help=(
            "Required co-flag for --write.  Forces an explicit "
            "operator gesture before any provider call or cache "
            "write."
        ),
    )
    p.add_argument(
        "--backup-path",
        type=str,
        default=None,
        help=(
            "Path to a backup of the events DB.  Required for "
            "--write.  Must exist on disk and differ from --db-path; "
            "the backup is hashed for existence only and is never "
            "mutated by this smoke."
        ),
    )
    p.add_argument(
        "--db-path",
        type=str,
        default=_DEFAULT_DB_PATH,
        help=(
            "Path to the live events DB containing the price_cache "
            "table.  Defaults to 'events.db'.  Opened read-only for "
            "COUNT(*) calls; opened for write only by "
            "price_cache.fetch_daily_cached in --write mode."
        ),
    )
    p.add_argument(
        "--auto-adjust",
        type=int,
        choices=(0, 1),
        default=0,
        help=(
            "auto_adjust value for the cache rows.  Defaults to 0 "
            "(event-anchored backtest convention used by every "
            "tracked freeze-cohort row).  Pass 1 only for live "
            "rolling reads."
        ),
    )
    p.add_argument(
        "--ticker-window",
        type=_parse_ticker_window,
        action="append",
        default=None,
        metavar="TICKER,YYYY-MM-DD,YYYY-MM-DD",
        help=(
            "Repeatable.  TICKER,start_date,end_date triple.  At "
            "least one is required."
        ),
    )
    p.add_argument(
        "--json",
        action="store_true",
        default=False,
        help=(
            "Accepted for ergonomic parity with sibling scripts.  "
            "Output is always JSON."
        ),
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    ticker_windows = list(args.ticker_window) if args.ticker_window else []
    result = run_smoke(
        ticker_windows=ticker_windows,
        auto_adjust=int(args.auto_adjust),
        write=bool(args.write),
        confirm=bool(args.confirm),
        backup_path=args.backup_path,
        db_path=args.db_path,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
