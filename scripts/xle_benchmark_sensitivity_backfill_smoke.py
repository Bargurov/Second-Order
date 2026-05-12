#!/usr/bin/env python3
"""XLE benchmark-sensitivity estimation-window backfill smoke.

Demonstrates whether the existing local ``price_cache`` carries enough
XLE coverage to clear the benchmark-sensitivity preflight for events
60 and 73 without fetching any online data.  The smoke is a
*demonstration* — it never mutates the live DB and never fabricates
market prices.

Workflow
--------

1. Copy the live events DB to a fresh file in ``tempfile.gettempdir()``.
2. Run :func:`benchmark_sensitivity_preflight.summarize_benchmark_sensitivity_preflight`
   against the temp copy to capture the **before** state.
3. For each event's ``missing_benchmark_ranges``, look up XLE rows on
   those exact business days in the temp DB's existing local
   ``price_cache``.  This is the *only* source of synthesis allowed
   by the smoke's contract — no provider, no LLM, no yfinance, no
   network, no fabricated prices.
4. ``INSERT OR IGNORE`` any rows the lookup returns into the temp DB
   (idempotent against ``PRIMARY KEY (ticker, date, auto_adjust)``).
5. Re-run the preflight against the (potentially augmented) temp DB
   to capture the **after** state.
6. Re-hash the live DB and report ``live_db_unchanged`` from the
   before/after hash equality.

In practice the local cache does not carry XLE rows for the missing
estimation-window dates (else the preflight would not have reported
them missing in the first place).  The smoke therefore typically
reports ``added_rows=[]`` and surfaces every missing date in
``still_missing_ranges`` — the honest "blocked" answer to "can we
clear the preflight from local data alone?".

The script is structured so that a future operator-led backfill
(rows added to ``price_cache`` from a separate process) is detected
automatically: re-running the smoke would find the new rows and
re-clear the preflight.

Out of scope (deliberately)
---------------------------
* No live DB writes.  ``live_db_unchanged`` is the byte-identity
  guard.
* No provider / yfinance / market_data / price_cache.fetch_*; no LLM;
  no FastAPI surface (never imports ``api`` / ``routes.*``).
* No SPY-vs-XLE inference.  The smoke only reports cache geometry.
* No fabricated XLE prices.  The single allowed insert source is a
  copy of a row that already lives in ``price_cache``.

Output contract (JSON)::

    {
      "ok":                       bool,
      "temp_db_path":             str | None,
      "checked_events_before":    int,
      "checked_events_after":     int,
      "ready_before":             int,
      "ready_after":              int,
      "blocked_before":           int,
      "blocked_after":            int,
      "added_rows": [
        {"ticker": str, "date": str, "source": str},
        ...
      ],
      "still_missing_ranges": [
        {"event_id": int, "start": str, "end": str, "reason": str},
        ...
      ],
      "live_db_unchanged":        bool,
      "warnings":                 [str, ...],
      "errors":                   [str, ...],
      "recommended_next_action":  str,
    }

Conservative wording — the smoke reports cache geometry, not market
evidence.  Banned tokens in any text the smoke emits: ``proof``,
``proven``, ``validated``, ``automatically``, ``alpha generated``,
``correct ticker``, ``guaranteed``.

Usage::

    python scripts/xle_benchmark_sensitivity_backfill_smoke.py --json
    python scripts/xle_benchmark_sensitivity_backfill_smoke.py --json \\
        --event-ids 60,73 --output artifacts/xle_backfill_smoke.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid
from datetime import date as _date, timedelta as _timedelta
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts import benchmark_sensitivity_preflight as _preflight  # noqa: E402


_DEFAULT_EVENT_IDS:         tuple[int, ...] = (60, 73)
_DEFAULT_BENCHMARK:         str             = "XLE"
_DEFAULT_HORIZONS:          tuple[int, ...] = (1, 5, 20)
_DEFAULT_ESTIMATION_WINDOW: int             = 60


_REASON_NO_LOCAL_SOURCE: str = "no_local_cache_row_for_date"


_RECOMMENDED_BLOCKED_NO_ADDS = (
    "{blocked} of {checked} checked event(s) remain blocked from {bench} "
    "benchmark sensitivity; no XLE rows are available in the existing "
    "local price_cache for the missing estimation-window dates.  An "
    "online backfill (out of scope for this smoke) is required before "
    "the preflight will clear."
)
_RECOMMENDED_BLOCKED_PARTIAL = (
    "{added} XLE row(s) staged into the temp DB from local cache; "
    "{blocked} of {checked} event(s) still blocked.  Inspect "
    "'still_missing_ranges' for the dates that remain uncovered."
)
_RECOMMENDED_CLEARED = (
    "Temp DB now clears the {bench} benchmark-sensitivity preflight "
    "for all {checked} checked event(s).  This is a cache-geometry "
    "demonstration on the temp DB; the live DB is unchanged."
)
_RECOMMENDED_NO_EVENTS = (
    "No events were checked — supply --event-ids and re-run."
)
_RECOMMENDED_ERRORED = (
    "Smoke reported errors — inspect 'errors' before relying on the "
    "before/after counts."
)


# ---------------------------------------------------------------------------
# Patchable seams
# ---------------------------------------------------------------------------


def _load_xle_rows_from_local_cache(
    *,
    db_path: str,
    ticker: str,
    missing_dates: Sequence[str],
) -> list[dict[str, Any]]:
    """Look up rows for ``ticker`` on ``missing_dates`` in the local
    ``price_cache`` of the SQLite file at ``db_path``.

    Returns a list of dicts with keys
    ``(ticker, date, close, volume, auto_adjust, fetched_at)``.  Uses
    a case-insensitive match on ``ticker`` so a row stored under a
    case variant is still surfaced.

    Read-only by construction — issues only ``SELECT``.  Tests patch
    this seam directly with synthetic payloads so they can drive the
    "row added" path without crafting a SQLite fixture.
    """
    if not missing_dates:
        return []
    if not db_path or not Path(db_path).exists():
        return []
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return []
    try:
        date_list = sorted({d for d in missing_dates if isinstance(d, str) and d})
        if not date_list:
            return []
        placeholders = ",".join(["?"] * len(date_list))
        try:
            rows = conn.execute(
                f"SELECT ticker, date, close, volume, auto_adjust, fetched_at "
                f"FROM price_cache "
                f"WHERE UPPER(ticker) = ? AND date IN ({placeholders})",
                [ticker.strip().upper()] + date_list,
            ).fetchall()
        except sqlite3.Error:
            return []
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r[1], str) or not r[1]:
            continue
        out.append({
            "ticker":      r[0],
            "date":        r[1],
            "close":       r[2],
            "volume":      r[3],
            "auto_adjust": r[4] if isinstance(r[4], int) else 1,
            "fetched_at":  r[5] if isinstance(r[5], str) else "",
        })
    return out


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_xle_benchmark_sensitivity_backfill_smoke(
    *,
    db_path: str | None = None,
    event_ids: Sequence[int] = _DEFAULT_EVENT_IDS,
    benchmark: str = _DEFAULT_BENCHMARK,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
    estimation_window: int = _DEFAULT_ESTIMATION_WINDOW,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Run the XLE benchmark-sensitivity backfill smoke.

    See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []
    cleanup_paths: list[str] = []

    live_path = _resolve_live_db_path(db_path)
    if live_path is None or not Path(live_path).exists():
        errors.append(
            "no live events DB path could be resolved; pass --db-path "
            "to point at a SQLite events.db"
        )
        return _finalize(
            envelope=_envelope(
                temp_db_path=None,
                errors=errors, warnings=warnings,
            ),
            output_path=output_path,
            cleanup=cleanup_paths,
        )

    live_hash_before = _hash_file_safe(live_path)

    try:
        temp_db_path = _copy_to_temp(live_path)
        cleanup_paths.append(temp_db_path)
    except OSError as exc:
        errors.append(f"failed to copy live DB to temp: {exc}")
        return _finalize(
            envelope=_envelope(
                temp_db_path=None,
                errors=errors, warnings=warnings,
            ),
            output_path=output_path,
            cleanup=cleanup_paths,
        )

    benchmark_upper = (benchmark or _DEFAULT_BENCHMARK).strip().upper()
    horizons_tuple  = tuple(int(h) for h in horizons if isinstance(h, int) and h > 0)
    if not horizons_tuple:
        horizons_tuple = _DEFAULT_HORIZONS

    # Step 1: preflight on the freshly-copied temp DB ("before").
    before_report = _preflight.summarize_benchmark_sensitivity_preflight(
        db_path=temp_db_path,
        event_ids=event_ids,
        benchmark=benchmark_upper,
        horizons=horizons_tuple,
        estimation_window=int(estimation_window),
    )
    if not before_report.get("ok"):
        warnings.append(
            "preflight (before) reported ok=False; "
            "downstream counts may be partial"
        )

    # Step 2: collect missing XLE dates per event.
    missing_dates_by_event = _expand_missing_dates(before_report)
    flat_missing_dates: set[str] = set()
    for _, dates in missing_dates_by_event.items():
        flat_missing_dates.update(dates)

    # Step 3: ask the seam for any rows the local cache can supply for
    # those dates.  Production: typically empty (rows missing by
    # definition).  Tests patch the seam to drive the "added" path.
    candidate_rows: list[dict[str, Any]] = []
    if flat_missing_dates:
        try:
            candidate_rows = _load_xle_rows_from_local_cache(
                db_path=temp_db_path,
                ticker=benchmark_upper,
                missing_dates=sorted(flat_missing_dates),
            )
        except Exception as exc:  # noqa: BLE001 — operator-visible
            errors.append(
                f"local cache lookup raised: "
                f"{type(exc).__name__}: {exc}",
            )
            candidate_rows = []

    # Step 4: stage candidate rows into the temp DB.  INSERT OR IGNORE
    # against PRIMARY KEY (ticker, date, auto_adjust) — duplicates are
    # silently skipped, so a row already in the cache contributes zero
    # to ``added_rows``.
    added_rows: list[dict[str, Any]] = []
    if candidate_rows:
        try:
            inserted = _stage_rows_into_temp_db(temp_db_path, candidate_rows)
        except sqlite3.Error as exc:
            errors.append(f"temp DB staging raised: {exc}")
            inserted = []
        for row in inserted:
            added_rows.append({
                "ticker": row.get("ticker"),
                "date":   row.get("date"),
                "source": "local_price_cache_existing",
            })

    # Step 5: re-run preflight on the temp DB ("after").
    after_report = _preflight.summarize_benchmark_sensitivity_preflight(
        db_path=temp_db_path,
        event_ids=event_ids,
        benchmark=benchmark_upper,
        horizons=horizons_tuple,
        estimation_window=int(estimation_window),
    )
    if not after_report.get("ok"):
        warnings.append(
            "preflight (after) reported ok=False; "
            "downstream counts may be partial"
        )

    # Step 6: compute still-missing ranges from the after-report so the
    # operator sees exactly what the local-cache lookup could not fill.
    still_missing = _still_missing_from_after(after_report)

    # Step 7: byte-identity guard on the live DB.
    live_hash_after = _hash_file_safe(live_path)
    live_db_unchanged = (
        live_hash_before is not None
        and live_hash_after is not None
        and live_hash_before == live_hash_after
    )

    recommended = _recommend(
        checked=int(before_report.get("checked_events") or 0),
        ready_after=int(after_report.get("ready_count") or 0),
        blocked_after=int(after_report.get("blocked_count") or 0),
        added=len(added_rows),
        benchmark=benchmark_upper,
        has_errors=bool(errors),
    )

    return _finalize(
        envelope=_envelope(
            temp_db_path=temp_db_path,
            checked_events_before=int(before_report.get("checked_events") or 0),
            checked_events_after=int(after_report.get("checked_events") or 0),
            ready_before=int(before_report.get("ready_count") or 0),
            ready_after=int(after_report.get("ready_count") or 0),
            blocked_before=int(before_report.get("blocked_count") or 0),
            blocked_after=int(after_report.get("blocked_count") or 0),
            added_rows=added_rows,
            still_missing_ranges=still_missing,
            live_db_unchanged=live_db_unchanged,
            errors=errors,
            warnings=warnings,
            recommended_next_action=recommended,
        ),
        output_path=output_path,
        cleanup=cleanup_paths,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_live_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:  # noqa: BLE001 — best-effort default
        return None
    return getattr(_db, "DB_FILE", None)


def _copy_to_temp(src_path: str) -> str:
    src = Path(src_path)
    dst_name = f"xle_backfill_smoke_{uuid.uuid4().hex}{src.suffix or '.db'}"
    dst = Path(tempfile.gettempdir()) / dst_name
    shutil.copy2(str(src), str(dst))
    return str(dst)


def _hash_file_safe(path: str | None) -> str | None:
    if not path or not Path(path).exists():
        return None
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _expand_missing_dates(
    preflight_report: dict[str, Any],
) -> dict[int, list[str]]:
    """Map ``event_id`` → sorted list of ISO date strings the preflight
    flagged as missing benchmark coverage.  Each ``missing_benchmark_
    ranges`` entry is expanded to its inclusive business-day list."""
    out: dict[int, list[str]] = {}
    rows = preflight_report.get("rows") or []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ev_id = row.get("event_id")
        if not isinstance(ev_id, int):
            continue
        ranges = row.get("missing_benchmark_ranges") or []
        dates: set[str] = set()
        for r in ranges:
            if not isinstance(r, dict):
                continue
            for d in _business_days_inclusive(r.get("start"), r.get("end")):
                dates.add(d.isoformat())
        if dates:
            out[ev_id] = sorted(dates)
    return out


def _business_days_inclusive(
    start_iso: Any, end_iso: Any,
) -> list[_date]:
    s = _parse_iso(start_iso)
    e = _parse_iso(end_iso)
    if s is None or e is None or s > e:
        return []
    out: list[_date] = []
    cur = s
    one = _timedelta(days=1)
    while cur <= e:
        if cur.weekday() < 5:
            out.append(cur)
        cur = cur + one
    return out


def _parse_iso(value: Any) -> _date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None


def _stage_rows_into_temp_db(
    temp_db_path: str, rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """INSERT OR IGNORE each ``row`` into the temp DB's price_cache.

    Returns the list of rows whose insert affected a new physical row
    (``cursor.rowcount > 0``).  Duplicates against the PRIMARY KEY are
    silently skipped — the temp DB stays idempotent across repeated
    runs.
    """
    if not rows:
        return []
    inserted: list[dict[str, Any]] = []
    conn = sqlite3.connect(temp_db_path)
    try:
        for r in rows:
            ticker = r.get("ticker")
            date_   = r.get("date")
            if not isinstance(ticker, str) or not ticker:
                continue
            if not isinstance(date_, str) or not date_:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    ticker, date_,
                    r.get("close"), r.get("volume"),
                    int(r.get("auto_adjust") if isinstance(r.get("auto_adjust"), int) else 1),
                    str(r.get("fetched_at") or ""),
                ),
            )
            if cur.rowcount and cur.rowcount > 0:
                inserted.append(r)
        conn.commit()
    finally:
        conn.close()
    return inserted


def _still_missing_from_after(
    after_report: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in after_report.get("rows") or []:
        if not isinstance(row, dict):
            continue
        ev_id = row.get("event_id")
        if not isinstance(ev_id, int):
            continue
        for rg in row.get("missing_benchmark_ranges") or []:
            if not isinstance(rg, dict):
                continue
            out.append({
                "event_id": ev_id,
                "start":    rg.get("start"),
                "end":      rg.get("end"),
                "reason":   rg.get("reason") or _REASON_NO_LOCAL_SOURCE,
            })
    return out


def _recommend(
    *,
    checked: int, ready_after: int, blocked_after: int,
    added: int, benchmark: str, has_errors: bool,
) -> str:
    if has_errors:
        return _RECOMMENDED_ERRORED
    if checked <= 0:
        return _RECOMMENDED_NO_EVENTS
    if blocked_after <= 0:
        return _RECOMMENDED_CLEARED.format(
            checked=checked, bench=benchmark or "(unspecified)",
        )
    if added > 0:
        return _RECOMMENDED_BLOCKED_PARTIAL.format(
            added=added, checked=checked, blocked=blocked_after,
        )
    return _RECOMMENDED_BLOCKED_NO_ADDS.format(
        checked=checked, blocked=blocked_after,
        bench=benchmark or "(unspecified)",
    )


# ---------------------------------------------------------------------------
# Envelope + finalize
# ---------------------------------------------------------------------------


def _envelope(
    *,
    temp_db_path: str | None,
    checked_events_before: int = 0,
    checked_events_after:  int = 0,
    ready_before:          int = 0,
    ready_after:           int = 0,
    blocked_before:        int = 0,
    blocked_after:         int = 0,
    added_rows: list[dict[str, Any]] | None = None,
    still_missing_ranges: list[dict[str, Any]] | None = None,
    live_db_unchanged:     bool = True,
    errors:   list[str],
    warnings: list[str],
    recommended_next_action: str | None = None,
) -> dict[str, Any]:
    if recommended_next_action is None:
        recommended_next_action = (
            _RECOMMENDED_ERRORED if errors else _RECOMMENDED_NO_EVENTS
        )
    return {
        "ok":                       not errors,
        "temp_db_path":             temp_db_path,
        "checked_events_before":    checked_events_before,
        "checked_events_after":     checked_events_after,
        "ready_before":             ready_before,
        "ready_after":              ready_after,
        "blocked_before":           blocked_before,
        "blocked_after":            blocked_after,
        "added_rows":               added_rows or [],
        "still_missing_ranges":     still_missing_ranges or [],
        "live_db_unchanged":        live_db_unchanged,
        "warnings":                 warnings,
        "errors":                   errors,
        "recommended_next_action":  recommended_next_action,
    }


def _finalize(
    *,
    envelope:    dict[str, Any],
    output_path: str | None,
    cleanup:     list[str],
) -> dict[str, Any]:
    if output_path:
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(envelope, fh, indent=2, sort_keys=True, default=str)
        except OSError as exc:
            envelope["errors"].append(
                f"failed to write --output {output_path}: {exc}",
            )
            envelope["ok"] = False

    for p in cleanup:
        try:
            if os.path.exists(p):
                os.unlink(p)
        except OSError:
            # Best-effort cleanup; never flip ok on unlink failure.
            pass
    return envelope


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "XLE benchmark-sensitivity backfill smoke", "",
    ]
    lines.append(f"OK:                       {report['ok']}")
    lines.append(f"Temp DB path:             {report['temp_db_path']}")
    lines.append(f"Checked events (before):  {report['checked_events_before']}")
    lines.append(f"Checked events (after):   {report['checked_events_after']}")
    lines.append(f"Ready (before/after):     "
                 f"{report['ready_before']}/{report['ready_after']}")
    lines.append(f"Blocked (before/after):   "
                 f"{report['blocked_before']}/{report['blocked_after']}")
    lines.append(f"Added rows:               {len(report['added_rows'])}")
    lines.append(
        f"Still-missing ranges:     {len(report['still_missing_ranges'])}"
    )
    lines.append(f"Live DB unchanged:        {report['live_db_unchanged']}")
    lines.append("")
    lines.append(f"Recommended next action:  {report['recommended_next_action']}")
    if report.get("warnings"):
        lines.append("")
        lines.append("Warnings:")
        for w in report["warnings"]:
            lines.append(f"  - {w}")
    if report.get("errors"):
        lines.append("")
        lines.append("Errors:")
        for e in report["errors"]:
            lines.append(f"  - {e}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_int_csv(value: str) -> tuple[int, ...]:
    out: list[int] = []
    for tok in (value or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(int(tok))
        except ValueError:
            continue
    return tuple(out)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Temp-only XLE benchmark-sensitivity estimation-window "
            "backfill smoke.  Copies the live events DB to a temp file, "
            "runs the benchmark-sensitivity preflight, attempts to add "
            "any missing XLE rows from the local price_cache, re-runs "
            "the preflight, and reports before/after readiness.  Never "
            "mutates the live DB.  No provider, LLM, yfinance, or "
            "FastAPI surface.  Conservative wording: the smoke reports "
            "cache geometry, not market evidence."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--event-ids", dest="event_ids",
        default=",".join(str(i) for i in _DEFAULT_EVENT_IDS),
        help=(
            f"Comma-separated event_ids to check (default "
            f"{','.join(str(i) for i in _DEFAULT_EVENT_IDS)})."
        ),
    )
    parser.add_argument(
        "--benchmark", dest="benchmark", default=_DEFAULT_BENCHMARK,
        help=f"Benchmark ticker symbol (default {_DEFAULT_BENCHMARK!r}).",
    )
    parser.add_argument(
        "--horizons", dest="horizons",
        default=",".join(str(h) for h in _DEFAULT_HORIZONS),
        help=(
            f"Comma-separated forward horizons in business days "
            f"(default {','.join(str(h) for h in _DEFAULT_HORIZONS)})."
        ),
    )
    parser.add_argument(
        "--estimation-window", dest="estimation_window",
        type=int, default=_DEFAULT_ESTIMATION_WINDOW,
        help=(
            f"Number of distinct pre-event cache dates required "
            f"(default {_DEFAULT_ESTIMATION_WINDOW})."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Optional path to the live events DB.  Defaults to "
            "db.DB_FILE.  Read-only by construction."
        ),
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope to.  When "
            "omitted, the smoke has no filesystem side effect outside "
            "the auto-cleaned temp DB."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = run_xle_benchmark_sensitivity_backfill_smoke(
        db_path=args.db_path,
        event_ids=_parse_int_csv(args.event_ids),
        benchmark=args.benchmark,
        horizons=_parse_int_csv(args.horizons),
        estimation_window=args.estimation_window,
        output_path=args.output_path,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_xle_benchmark_sensitivity_backfill_smoke",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
