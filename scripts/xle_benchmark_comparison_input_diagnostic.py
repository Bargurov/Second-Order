#!/usr/bin/env python3
"""Benchmark comparison input coverage diagnostic.

Read-only diagnostic that answers a single question for each event in
the default backlog (``60``, ``73``):

    "Does ``price_cache`` carry enough rows on the primary ticker AND
    on BOTH ``SPY`` AND ``XLE`` for the forward horizons and
    estimation window a benchmark comparison would need?"

The diagnostic does NOT run the comparison and does NOT decide which
benchmark is correct.  It only surfaces input coverage so an operator
can see whether the cache is ready to *attempt* the comparison.

Read-only by construction
-------------------------

* Only issues ``SELECT`` statements.  No INSERT / UPDATE / DELETE.
* Reuses the public, read-only
  :func:`scripts.benchmark_sensitivity_preflight.summarize_benchmark_sensitivity_preflight`
  rather than re-implementing its NYSE-holiday-aware date math.
  Calls it twice — once with ``benchmark='SPY'``, once with
  ``benchmark='XLE'`` — and combines the two reports.
* Does NOT depend on ``xle_benchmark_sensitivity_compare_smoke``
  internals.  The diagnostic is a *coverage* report, not a
  comparison.
* No provider call (no ``yfinance`` / ``market_data`` / paid path),
  no LLM, no FastAPI surface (never imports ``api`` / ``routes.*``).
* No fabricated prices.  ``min_date`` / ``max_date`` reflect the
  actual cache contents.

Output contract (JSON)::

    {
      "ok":                       bool,
      "checked_events":           int,
      "rows": [
        {
          "event_id":                  int,
          "event_date":                str | None,
          "primary_ticker":            str | None,
          "benchmark_tickers_checked": ["SPY", "XLE"],
          "primary_cache_summary":     {
            "rows_in_cache": int,
            "min_date":      str | None,
            "max_date":      str | None,
            "available":     bool,
          },
          "spy_cache_summary":         { ...same shape },
          "xle_cache_summary":         { ...same shape },
          "horizons_checked":          [int, ...],
          "missing_by_ticker":         {
            "<primary_ticker>": [{"start": str, "end": str, "reason": str}, ...],
            "SPY":              [...],
            "XLE":              [...],
          },
          "can_attempt_comparison":    bool,
        },
        ...
      ],
      "missing_inputs": [
        {"event_id": int, "ticker": str,
         "ranges": [{"start": str, "end": str, "reason": str}, ...]},
        ...
      ],
      "ready_for_comparison":     int,
      "warnings":                 [str, ...],
      "errors":                   [str, ...],
      "recommended_next_action":  str,
    }

``ok`` is True iff the diagnostic ran without internal errors.  A
clean run with ``ready_for_comparison < checked_events`` is the
normal state when the cache is short coverage — it does NOT flip
``ok`` because the diagnostic's job is to *report* missing coverage,
not to fail when coverage is missing.

Conservative wording — the diagnostic reports cache geometry, never
benchmark-sensitivity conclusions.  Banned tokens in any text the
diagnostic emits: ``proof``, ``proves``, ``proven``, ``alpha``,
``guaranteed``, ``automatically``, ``validated``, ``definitely``,
``causes``, ``causation``.  The diagnostic never asserts an
SPY-vs-XLE verdict ("better than", "outperforms", "more sensitive").

Usage::

    python scripts/xle_benchmark_comparison_input_diagnostic.py --json
    python scripts/xle_benchmark_comparison_input_diagnostic.py --json \\
        --db-path events.db
    python scripts/xle_benchmark_comparison_input_diagnostic.py --json \\
        --event-ids 60,73 --horizons 1,5,20 --estimation-window 60
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_EVENT_IDS:         tuple[int, ...] = (60, 73)
_DEFAULT_HORIZONS:          tuple[int, ...] = (1, 5, 20)
_DEFAULT_ESTIMATION_WINDOW: int             = 60

_BENCHMARK_TICKERS_CHECKED: tuple[str, ...] = ("SPY", "XLE")


_RECOMMENDED_NO_EVENTS: str = (
    "No events were checked — supply --event-ids and re-run."
)
_RECOMMENDED_ALL_READY: str = (
    "All {n} checked event(s) have primary, SPY, and XLE cache "
    "coverage sufficient to attempt a benchmark comparison.  The "
    "diagnostic reports input coverage only and does not run the "
    "comparison itself."
)
_RECOMMENDED_PARTIAL: str = (
    "{ready} of {n} checked event(s) have full primary + SPY + XLE "
    "coverage; {short} event(s) are short coverage on at least one "
    "ticker.  Inspect 'missing_inputs' for the per-ticker date "
    "ranges that would need to land in price_cache before a "
    "benchmark comparison can be attempted.  The diagnostic reports "
    "input coverage only and does not infer a benchmark verdict."
)
_RECOMMENDED_NONE_READY: str = (
    "0 of {n} checked event(s) have full primary + SPY + XLE "
    "coverage.  Inspect 'missing_inputs' for the date ranges that "
    "would need to land in price_cache before a benchmark "
    "comparison can be attempted.  The diagnostic reports input "
    "coverage only and does not infer a benchmark verdict."
)
_RECOMMENDED_ERRORED: str = (
    "Diagnostic surfaced errors before the coverage counts settled."
    "  Inspect 'errors' before relying on any 'rows' field."
)


# ---------------------------------------------------------------------------
# Patchable seams
# ---------------------------------------------------------------------------


def _run_preflight(
    *,
    db_path:           str | None,
    event_ids:         Sequence[int],
    benchmark:         str,
    horizons:          Sequence[int],
    estimation_window: int,
) -> dict[str, Any]:
    """Wrap the read-only benchmark-sensitivity preflight runner so
    tests can drive a synthetic preflight payload without seeding a
    full events archive.  Lazy import keeps the module's import graph
    free of the preflight's holiday calendar on the patched test path.
    """
    from scripts.benchmark_sensitivity_preflight import (
        summarize_benchmark_sensitivity_preflight,
    )

    return summarize_benchmark_sensitivity_preflight(
        db_path=db_path,
        event_ids=event_ids,
        benchmark=benchmark,
        horizons=horizons,
        estimation_window=int(estimation_window),
    )


def _load_cache_summaries(
    *,
    db_path: str | None,
    tickers: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Issue ``SELECT COUNT(*), MIN(date), MAX(date) FROM price_cache
    WHERE UPPER(ticker) = ?`` once per distinct ticker.

    Returns a mapping ``ticker_upper -> {rows_in_cache, min_date,
    max_date}``.  Tickers absent from the cache surface as
    ``{rows_in_cache: 0, min_date: None, max_date: None}`` so callers
    can render them without a special case.

    Read-only by construction.  Tests patch this seam directly so
    the no-paid invariants hold under all code paths.
    """
    cleaned = sorted({
        t.strip().upper() for t in tickers
        if isinstance(t, str) and t.strip()
    })
    out: dict[str, dict[str, Any]] = {
        t: {"rows_in_cache": 0, "min_date": None, "max_date": None}
        for t in cleaned
    }
    if not cleaned:
        return out

    path = _resolve_db_path(db_path)
    if path is None or not Path(path).exists():
        return out

    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        return out

    try:
        for ticker in cleaned:
            try:
                row = conn.execute(
                    "SELECT COUNT(*), MIN(date), MAX(date) "
                    "FROM price_cache "
                    "WHERE UPPER(ticker) = ? "
                    "AND date IS NOT NULL AND date != ''",
                    (ticker,),
                ).fetchone()
            except sqlite3.Error:
                row = None
            if not row:
                continue
            count, min_d, max_d = row
            out[ticker] = {
                "rows_in_cache": int(count) if isinstance(count, int) else 0,
                "min_date":      min_d if isinstance(min_d, str) and min_d else None,
                "max_date":      max_d if isinstance(max_d, str) and max_d else None,
            }
    finally:
        conn.close()

    return out


def _resolve_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:  # noqa: BLE001 — best-effort default
        return None
    return getattr(_db, "DB_FILE", None)


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_xle_benchmark_comparison_input_diagnostic(
    *,
    db_path:           str | None = None,
    event_ids:         Sequence[int] = _DEFAULT_EVENT_IDS,
    horizons:          Sequence[int] = _DEFAULT_HORIZONS,
    estimation_window: int = _DEFAULT_ESTIMATION_WINDOW,
    output_path:       str | None = None,
) -> dict[str, Any]:
    """Run the read-only benchmark comparison input coverage
    diagnostic.

    See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    horizons_tuple = tuple(
        int(h) for h in horizons if isinstance(h, int) and h > 0
    )
    if not horizons_tuple:
        horizons_tuple = _DEFAULT_HORIZONS

    event_ids_clean: list[int] = []
    seen: set[int] = set()
    for ev in event_ids:
        if isinstance(ev, int) and ev not in seen:
            event_ids_clean.append(ev)
            seen.add(ev)

    # Step 1: run preflight twice — once per benchmark we are
    # surveying.  Two calls keep the preflight contract pristine
    # (one benchmark per call) and let us combine the per-event rows
    # afterward.
    spy_report = _safe_dict(_safe_run_preflight(
        db_path=db_path,
        event_ids=event_ids_clean,
        benchmark="SPY",
        horizons=horizons_tuple,
        estimation_window=int(estimation_window),
        errors=errors,
    ))
    xle_report = _safe_dict(_safe_run_preflight(
        db_path=db_path,
        event_ids=event_ids_clean,
        benchmark="XLE",
        horizons=horizons_tuple,
        estimation_window=int(estimation_window),
        errors=errors,
    ))

    spy_rows_by_id = _rows_by_event_id(spy_report)
    xle_rows_by_id = _rows_by_event_id(xle_report)

    # Step 2: collect the tickers we need cache summaries for —
    # primary tickers seen in either preflight plus SPY and XLE.
    summary_tickers: set[str] = set(_BENCHMARK_TICKERS_CHECKED)
    for ev_id in event_ids_clean:
        for source in (spy_rows_by_id, xle_rows_by_id):
            pt = _safe_dict(source.get(ev_id)).get("primary_ticker")
            if isinstance(pt, str) and pt:
                summary_tickers.add(pt.strip().upper())

    cache_summaries = _safe_dict(_load_cache_summaries(
        db_path=db_path, tickers=sorted(summary_tickers),
    ))

    # Step 3: build per-event diagnostic rows.
    rows: list[dict[str, Any]] = []
    missing_inputs: list[dict[str, Any]] = []
    for ev_id in event_ids_clean:
        spy_row = _safe_dict(spy_rows_by_id.get(ev_id))
        xle_row = _safe_dict(xle_rows_by_id.get(ev_id))

        primary_ticker = _pick_primary_ticker(
            spy_row=spy_row, xle_row=xle_row,
            warnings=warnings, event_id=ev_id,
        )
        event_date = _pick_event_date(
            spy_row=spy_row, xle_row=xle_row,
        )
        primary_available = _pick_primary_available(
            spy_row=spy_row, xle_row=xle_row,
            warnings=warnings, event_id=ev_id,
        )
        spy_available = bool(spy_row.get("benchmark_cache_available"))
        xle_available = bool(xle_row.get("benchmark_cache_available"))

        primary_summary = _summary_for(
            ticker=primary_ticker, summaries=cache_summaries,
            available=primary_available,
        )
        spy_summary = _summary_for(
            ticker="SPY", summaries=cache_summaries,
            available=spy_available,
        )
        xle_summary = _summary_for(
            ticker="XLE", summaries=cache_summaries,
            available=xle_available,
        )

        missing_by_ticker: dict[str, list[dict[str, str]]] = {}
        if primary_ticker:
            primary_ranges = _dedupe_ranges(
                list(spy_row.get("missing_primary_ranges") or [])
                + list(xle_row.get("missing_primary_ranges") or []),
            )
            if primary_ranges:
                missing_by_ticker[primary_ticker] = primary_ranges
        spy_ranges = _safe_ranges(spy_row.get("missing_benchmark_ranges"))
        if spy_ranges:
            missing_by_ticker["SPY"] = spy_ranges
        xle_ranges = _safe_ranges(xle_row.get("missing_benchmark_ranges"))
        if xle_ranges:
            missing_by_ticker["XLE"] = xle_ranges

        can_attempt = bool(
            primary_ticker
            and primary_available
            and spy_available
            and xle_available
        )

        rows.append({
            "event_id":                  ev_id,
            "event_date":                event_date,
            "primary_ticker":            primary_ticker,
            "benchmark_tickers_checked": list(_BENCHMARK_TICKERS_CHECKED),
            "primary_cache_summary":     primary_summary,
            "spy_cache_summary":         spy_summary,
            "xle_cache_summary":         xle_summary,
            "horizons_checked":          list(horizons_tuple),
            "missing_by_ticker":         missing_by_ticker,
            "can_attempt_comparison":    can_attempt,
        })

        # Flatten into missing_inputs in deterministic order.
        if primary_ticker and missing_by_ticker.get(primary_ticker):
            missing_inputs.append({
                "event_id": ev_id,
                "ticker":   primary_ticker,
                "ranges":   missing_by_ticker[primary_ticker],
            })
        for bench in _BENCHMARK_TICKERS_CHECKED:
            if missing_by_ticker.get(bench):
                missing_inputs.append({
                    "event_id": ev_id,
                    "ticker":   bench,
                    "ranges":   missing_by_ticker[bench],
                })

    ready_for_comparison = sum(
        1 for r in rows if r["can_attempt_comparison"]
    )
    short_count = len(rows) - ready_for_comparison

    recommended = _recommend(
        checked=len(rows),
        ready=ready_for_comparison,
        short=short_count,
        has_errors=bool(errors),
    )

    return _finalize(
        envelope={
            "ok":                      not errors,
            "checked_events":          len(rows),
            "rows":                    rows,
            "missing_inputs":          missing_inputs,
            "ready_for_comparison":    ready_for_comparison,
            "warnings":                warnings,
            "errors":                  errors,
            "recommended_next_action": recommended,
        },
        output_path=output_path,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_run_preflight(
    *,
    db_path:           str | None,
    event_ids:         Sequence[int],
    benchmark:         str,
    horizons:          Sequence[int],
    estimation_window: int,
    errors:            list[str],
) -> dict[str, Any]:
    try:
        report = _run_preflight(
            db_path=db_path,
            event_ids=event_ids,
            benchmark=benchmark,
            horizons=horizons,
            estimation_window=int(estimation_window),
        )
    except Exception as exc:  # noqa: BLE001 — operator-visible
        errors.append(
            f"preflight (benchmark={benchmark}) raised: "
            f"{type(exc).__name__}: {exc}"
        )
        return {}
    return report if isinstance(report, dict) else {}


def _rows_by_event_id(report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in report.get("rows") or []:
        if not isinstance(row, dict):
            continue
        ev_id = row.get("event_id")
        if isinstance(ev_id, int):
            out[ev_id] = row
    return out


def _pick_primary_ticker(
    *,
    spy_row:   dict[str, Any],
    xle_row:   dict[str, Any],
    warnings:  list[str],
    event_id:  int,
) -> str | None:
    spy_pt = spy_row.get("primary_ticker")
    xle_pt = xle_row.get("primary_ticker")
    spy_pt = spy_pt if isinstance(spy_pt, str) and spy_pt else None
    xle_pt = xle_pt if isinstance(xle_pt, str) and xle_pt else None
    if spy_pt and xle_pt and spy_pt != xle_pt:
        warnings.append(
            f"event_id={event_id}: SPY preflight reported "
            f"primary_ticker={spy_pt!r} but XLE preflight reported "
            f"{xle_pt!r}; picking the SPY value, audit the source DB"
        )
        return spy_pt
    return spy_pt or xle_pt


def _pick_event_date(
    *,
    spy_row: dict[str, Any],
    xle_row: dict[str, Any],
) -> str | None:
    for src in (spy_row, xle_row):
        ed = src.get("event_date")
        if isinstance(ed, str) and ed:
            return ed
    return None


def _pick_primary_available(
    *,
    spy_row:  dict[str, Any],
    xle_row:  dict[str, Any],
    warnings: list[str],
    event_id: int,
) -> bool:
    spy_pa = bool(spy_row.get("primary_cache_available"))
    xle_pa = bool(xle_row.get("primary_cache_available"))
    if spy_pa != xle_pa:
        warnings.append(
            f"event_id={event_id}: SPY preflight and XLE preflight "
            f"disagree on primary_cache_available "
            f"({spy_pa} vs {xle_pa}); taking the conservative AND"
        )
        return spy_pa and xle_pa
    return spy_pa


def _summary_for(
    *,
    ticker:    str | None,
    summaries: dict[str, dict[str, Any]],
    available: bool,
) -> dict[str, Any]:
    if not ticker:
        return {
            "rows_in_cache": 0,
            "min_date":      None,
            "max_date":      None,
            "available":     False,
        }
    raw = _safe_dict(summaries.get(ticker.strip().upper()))
    return {
        "rows_in_cache": _safe_int(raw.get("rows_in_cache")),
        "min_date":      raw.get("min_date") if isinstance(raw.get("min_date"), str) else None,
        "max_date":      raw.get("max_date") if isinstance(raw.get("max_date"), str) else None,
        "available":     bool(available),
    }


def _safe_ranges(value: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(value, list):
        return out
    for rg in value:
        if not isinstance(rg, dict):
            continue
        start  = rg.get("start")
        end    = rg.get("end")
        reason = rg.get("reason")
        if not isinstance(start, str) or not isinstance(end, str):
            continue
        out.append({
            "start":  start,
            "end":    end,
            "reason": reason if isinstance(reason, str) else "",
        })
    return out


def _dedupe_ranges(
    ranges: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Deduplicate by (start, end, reason).  Stable ordering: first
    occurrence wins so the SPY-preflight ranges show up before XLE's
    if they share an entry.
    """
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, str]] = []
    for rg in ranges:
        if not isinstance(rg, dict):
            continue
        start  = rg.get("start")
        end    = rg.get("end")
        reason = rg.get("reason")
        if not isinstance(start, str) or not isinstance(end, str):
            continue
        key = (
            start, end,
            reason if isinstance(reason, str) else "",
        )
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "start":  start,
            "end":    end,
            "reason": key[2],
        })
    return out


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _recommend(
    *,
    checked:    int,
    ready:      int,
    short:      int,
    has_errors: bool,
) -> str:
    if has_errors:
        return _RECOMMENDED_ERRORED
    if checked <= 0:
        return _RECOMMENDED_NO_EVENTS
    if short <= 0:
        return _RECOMMENDED_ALL_READY.format(n=checked)
    if ready <= 0:
        return _RECOMMENDED_NONE_READY.format(n=checked)
    return _RECOMMENDED_PARTIAL.format(
        ready=ready, short=short, n=checked,
    )


# ---------------------------------------------------------------------------
# Finalize
# ---------------------------------------------------------------------------


def _finalize(
    *, envelope: dict[str, Any], output_path: str | None,
) -> dict[str, Any]:
    if output_path:
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(
                    envelope, fh, indent=2, sort_keys=True, default=str,
                )
        except OSError as exc:
            envelope["errors"].append(
                f"failed to write --output {output_path}: {exc}"
            )
            envelope["ok"] = False
    return envelope


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


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
            "Read-only benchmark comparison input coverage "
            "diagnostic.  For each event in --event-ids (default 60, "
            "73), reports whether the primary ticker AND both SPY "
            "AND XLE have enough price_cache rows for the requested "
            "forward horizons and estimation window.  Does NOT run "
            "the benchmark comparison itself and does NOT infer a "
            "benchmark verdict.  No DB writes, no provider, no LLM, "
            "no FastAPI surface.  Conservative wording: reports "
            "cache geometry only."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help=(
            "Accepted for ergonomic parity with sibling scripts.  "
            "Output is always JSON."
        ),
    )
    parser.add_argument(
        "--event-ids", dest="event_ids",
        default=",".join(str(i) for i in _DEFAULT_EVENT_IDS),
        help=(
            f"Comma-separated event_ids to diagnose (default "
            f"{','.join(str(i) for i in _DEFAULT_EVENT_IDS)})."
        ),
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
            "Optional path to the events DB.  Defaults to "
            "db.DB_FILE.  Read-only by construction."
        ),
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope to.  When "
            "omitted, the diagnostic has no filesystem side effect."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = run_xle_benchmark_comparison_input_diagnostic(
        db_path=args.db_path,
        event_ids=_parse_int_csv(args.event_ids),
        horizons=_parse_int_csv(args.horizons),
        estimation_window=args.estimation_window,
        output_path=args.output_path,
    )
    print(_render_json(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_xle_benchmark_comparison_input_diagnostic",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
