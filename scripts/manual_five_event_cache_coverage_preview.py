#!/usr/bin/env python3
"""Manual five-event expansion-batch cache-coverage preview.

Reports which (ticker, date-window) pairs the local price cache
already covers — and which ones it does not — for the operator's
five-event expansion batch.  The preview is **diagnosis only**: it
performs no online fetch, never mutates the cache, never imports a
provider, and never invokes a validation pipeline.  Its purpose is
to make the cost of bringing the batch online (and the risk of
short-history tickers — see the ZIM IPO note below) visible
*before* any cache-mutating work is scheduled.

Inputs
------
* ``--input-csv`` (default
  ``examples/manual_five_event_expansion_batch.csv``) — the
  operator-curated CSV with the canonical header
  ``event_date, headline, source_url, mechanism_family,
  primary_ticker, benchmark_ticker, ...``.  Extra columns are
  ignored; only ``event_date``, ``primary_ticker``, and
  ``benchmark_ticker`` are required.

* The existing ``price_cache.db`` consulted via the strictly
  read-only :func:`price_cache.read_window_no_fetch` entry — the
  same seam the validation smoke uses.  The import is lazy so the
  module's import surface stays narrow and tests can patch the
  price reader directly without pulling the cache into scope.

Window contract
---------------
For each (event, ticker) pair the preview asks the cache for a
calendar window that brackets the event date by
``_LOAD_PRE_CAL_DAYS`` days before and ``_LOAD_POST_CAL_DAYS``
days after.  This matches the validation smoke's window so a row
that passes coverage here will not bounce on coverage when it is
validated next.  The estimation-window contract used downstream is
**60 trading days** of pre-event shared history; the preview
surfaces both the observed pre-event-bar count and a boolean
``sufficient_for_estimation_window`` so an operator can scan for
short-history tickers at a glance.

ZIM IPO note
------------
ZIM IPO'd on 2021-01-28, so any operator row that names ZIM as
the primary for an event before mid-2021 has no pre-event
estimation window.  The bundled CSV no longer uses ZIM for the
Ever Given / Suez 2021-03-24 row — that row was swapped to MATX
(NYSE-listed since the 2012 Alexander & Baldwin spin-off) so the
estimation window is recoverable.  ZIM remains in
``_KNOWN_IPO_RISKS`` so that if a future operator adds a ZIM row
the preview still surfaces the IPO-window gap explicitly in
``warnings`` and in the ``missing_coverage`` reason string,
rather than the operator mistaking "no cached bars before
2021-01-28" for a price-cache bug.

Read-only contract
------------------
* No FastAPI surface, no ``routes.*``, no ``api`` import.
* No paid provider, no ``yfinance``, no ``market_data``, no
  ``market_check``.
* No LLM (``openai``, ``anthropic``).
* No DB write, no cache write, no artifact mutation.  The preview
  prints to stdout (and, optionally, an ``--output`` JSON file).

Conservative wording
--------------------
The preview describes coverage in terms of cached bars.  It does
not claim a window is "validated", "ready", or "proven"; missing
coverage is surfaced as ``missing_coverage`` and the
``recommended_next_action`` reads as plainly as possible.

Output contract (JSON)::

    {
      "ok":                       bool,
      "input_csv":                str,
      "rows_checked":             int,
      "tickers_needed":           [str, ...],
      "required_windows": [
        {
          "row_index":            int,
          "event_date":           str,
          "primary_ticker":       str,
          "benchmark_ticker":     str,
          "role":                 "primary" | "benchmark",
          "ticker":               str,
          "requested_start":      str,
          "requested_end":        str,
          "estimation_window_start_iso": str,
        }, ...
      ],
      "available_coverage": [
        {
          "row_index":                       int,
          "event_date":                      str,
          "ticker":                          str,
          "role":                            "primary" | "benchmark",
          "observed_first":                  str | None,
          "observed_last":                   str | None,
          "bar_count":                       int,
          "pre_event_bar_count":             int,
          "post_event_bar_count":            int,
          "sufficient_for_estimation_window": bool,
        }, ...
      ],
      "missing_coverage": [
        {
          "row_index":            int,
          "event_date":           str,
          "ticker":               str,
          "role":                 "primary" | "benchmark",
          "reason":               str,
        }, ...
      ],
      "recommended_next_action":  str | None,
      "warnings":                 [str, ...],
      "errors":                   [str, ...],
    }
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date as _date, timedelta as _timedelta
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_INPUT_CSV: str = "examples/manual_five_event_expansion_batch.csv"

# Calendar-day padding mirrors scripts/manual_five_event_validation_smoke.py
# so the preview's "covered" answer matches what validation would observe.
_LOAD_PRE_CAL_DAYS:  int = 200
_LOAD_POST_CAL_DAYS: int = 60

# Estimation-window contract for stats.event_study.compute_event_study.
_ESTIMATION_WINDOW: int = 60

# Known short-history risks the operator already flagged in the CSV's
# ``operator_notes`` column.  Surfaced as a warning when the ticker
# appears in the batch and any required window starts before its IPO.
_KNOWN_IPO_RISKS: dict[str, str] = {
    "ZIM": "2021-01-28",
}


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------


def run_coverage_preview(
    *,
    input_csv:    str | Path = _DEFAULT_INPUT_CSV,
    price_reader: Optional[Any] = None,
) -> dict[str, Any]:
    """Run the cache-coverage preview and return the JSON envelope.

    ``price_reader`` is an injectable seam.  When ``None`` the
    preview imports ``price_cache.read_window_no_fetch`` on demand
    and uses it.  Tests pass a fake reader so the suite never depends
    on cache contents or pandas.
    """
    warnings: list[str] = []
    errors:   list[str] = []

    rows, load_errors, load_warnings = _read_rows(Path(input_csv))
    warnings.extend(load_warnings)
    errors.extend(load_errors)
    if errors:
        return _empty_envelope(
            input_csv=str(input_csv),
            warnings=warnings, errors=errors,
        )

    if price_reader is None:
        price_reader = _default_price_reader(errors=errors)
        if errors:
            return _empty_envelope(
                input_csv=str(input_csv),
                warnings=warnings, errors=errors,
            )

    required_windows: list[dict[str, Any]] = []
    available_coverage: list[dict[str, Any]] = []
    missing_coverage:   list[dict[str, Any]] = []

    for row in rows:
        for role in ("primary", "benchmark"):
            ticker = row[f"{role}_ticker"]
            if not ticker:
                missing_coverage.append({
                    "row_index":    row["row_index"],
                    "event_date":   row["event_date"],
                    "ticker":       "",
                    "role":         role,
                    "reason":       f"{role}_ticker is empty in input CSV",
                })
                continue
            window = _compute_required_window(
                event_date=row["event_date"],
                ticker=ticker,
                role=role,
                row=row,
            )
            if window is None:
                missing_coverage.append({
                    "row_index":    row["row_index"],
                    "event_date":   row["event_date"],
                    "ticker":       ticker,
                    "role":         role,
                    "reason":       "event_date is not ISO YYYY-MM-DD",
                })
                continue
            required_windows.append(window)
            obs = _observe_ticker_window(
                ticker=ticker,
                event_date_iso=row["event_date"],
                requested_start=window["requested_start"],
                requested_end=window["requested_end"],
                role=role,
                row_index=row["row_index"],
                price_reader=price_reader,
            )
            available_coverage.append(obs["available_entry"])
            if obs["missing_entry"] is not None:
                missing_coverage.append(obs["missing_entry"])

    tickers_needed = _distinct_tickers(rows)
    ipo_warnings = _scan_ipo_risk(
        required_windows=required_windows,
        tickers_in_batch=tickers_needed,
    )
    warnings.extend(ipo_warnings)

    recommended_next_action: Optional[str] = None
    if missing_coverage:
        recommended_next_action = (
            "Expand the local price cache to cover the listed "
            "missing windows before running the validation smoke "
            "on this batch.  Provider / yfinance fetches are out "
            "of scope for this preview; the operator owns the "
            "cache-expansion step."
        )

    return {
        "ok":                       not errors,
        "input_csv":                str(input_csv),
        "rows_checked":             int(len(rows)),
        "tickers_needed":           tickers_needed,
        "required_windows":         required_windows,
        "available_coverage":       available_coverage,
        "missing_coverage":         missing_coverage,
        "recommended_next_action":  recommended_next_action,
        "warnings":                 warnings,
        "errors":                   errors,
    }


# ---------------------------------------------------------------------------
# Empty envelope (input load failed)
# ---------------------------------------------------------------------------


def _empty_envelope(
    *,
    input_csv: str,
    warnings:  list[str],
    errors:    list[str],
) -> dict[str, Any]:
    return {
        "ok":                       False,
        "input_csv":                input_csv,
        "rows_checked":             0,
        "tickers_needed":           [],
        "required_windows":         [],
        "available_coverage":       [],
        "missing_coverage":         [],
        "recommended_next_action":  None,
        "warnings":                 warnings,
        "errors":                   errors,
    }


# ---------------------------------------------------------------------------
# CSV loader
# ---------------------------------------------------------------------------


_REQUIRED_FIELDS: tuple[str, ...] = (
    "event_date", "primary_ticker", "benchmark_ticker",
)


def _read_rows(
    path: Path,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    errors:   list[str] = []
    warnings: list[str] = []
    if not path.is_file():
        errors.append(f"input CSV not found: {path}")
        return [], errors, warnings
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(
            f"failed to read {path}: {type(exc).__name__}: {exc}",
        )
        return [], errors, warnings

    reader = csv.DictReader(text.splitlines())
    header = reader.fieldnames or []
    missing_fields = [f for f in _REQUIRED_FIELDS if f not in header]
    if missing_fields:
        errors.append(
            f"input CSV missing required column(s): "
            f"{', '.join(missing_fields)}",
        )
        return [], errors, warnings

    rows: list[dict[str, Any]] = []
    for idx, raw in enumerate(reader, start=1):
        event_date = (raw.get("event_date") or "").strip()
        primary    = (raw.get("primary_ticker") or "").strip().upper()
        benchmark  = (raw.get("benchmark_ticker") or "").strip().upper()
        if not event_date:
            warnings.append(
                f"row {idx}: missing event_date; row skipped",
            )
            continue
        rows.append({
            "row_index":         idx,
            "event_date":        event_date,
            "primary_ticker":    primary,
            "benchmark_ticker":  benchmark,
            "headline":          (raw.get("headline") or "").strip(),
            "mechanism_family":  (raw.get("mechanism_family") or "").strip(),
        })
    return rows, errors, warnings


# ---------------------------------------------------------------------------
# Window math
# ---------------------------------------------------------------------------


def _compute_required_window(
    *,
    event_date: str,
    ticker:     str,
    role:       str,
    row:        dict[str, Any],
) -> Optional[dict[str, Any]]:
    try:
        anchor = _date.fromisoformat(event_date[:10])
    except (ValueError, TypeError):
        return None
    start = (anchor - _timedelta(days=_LOAD_PRE_CAL_DAYS)).isoformat()
    end   = (anchor + _timedelta(days=_LOAD_POST_CAL_DAYS)).isoformat()
    # ``estimation_window_start_iso`` is an informational hint: the
    # downstream estimation window is measured in *trading* days, not
    # calendar days, so this is approximate.  It is included so the
    # operator can eyeball coverage against the source's IPO date
    # without re-deriving the offset.
    est_start = (
        anchor - _timedelta(days=_ESTIMATION_WINDOW + 30)
    ).isoformat()
    return {
        "row_index":                  int(row["row_index"]),
        "event_date":                 anchor.isoformat(),
        "primary_ticker":             row["primary_ticker"],
        "benchmark_ticker":           row["benchmark_ticker"],
        "role":                       role,
        "ticker":                     ticker,
        "requested_start":            start,
        "requested_end":              end,
        "estimation_window_start_iso": est_start,
    }


# ---------------------------------------------------------------------------
# Per-ticker observation
# ---------------------------------------------------------------------------


def _observe_ticker_window(
    *,
    ticker:          str,
    event_date_iso:  str,
    requested_start: str,
    requested_end:   str,
    role:            str,
    row_index:       int,
    price_reader:    Any,
) -> dict[str, Any]:
    """Ask the cache for ``(ticker, requested_start, requested_end)``.

    Returns a dict with two keys:

    * ``available_entry`` — always produced; carries observed bar
      counts and the ``sufficient_for_estimation_window`` flag.
    * ``missing_entry``   — produced when the observed bars do not
      cover the estimation-window contract; ``None`` otherwise.
    """
    dates, _closes = price_reader(ticker, requested_start, requested_end)
    if dates:
        observed_first = dates[0]
        observed_last  = dates[-1]
        bar_count      = len(dates)
        pre_bars = sum(1 for d in dates if d < event_date_iso)
        post_bars = sum(1 for d in dates if d > event_date_iso)
    else:
        observed_first = None
        observed_last  = None
        bar_count      = 0
        pre_bars       = 0
        post_bars      = 0
    sufficient = pre_bars >= _ESTIMATION_WINDOW

    available_entry: dict[str, Any] = {
        "row_index":                       int(row_index),
        "event_date":                      event_date_iso,
        "ticker":                          ticker,
        "role":                            role,
        "observed_first":                  observed_first,
        "observed_last":                   observed_last,
        "bar_count":                       int(bar_count),
        "pre_event_bar_count":             int(pre_bars),
        "post_event_bar_count":            int(post_bars),
        "sufficient_for_estimation_window": bool(sufficient),
    }

    missing_entry: Optional[dict[str, Any]] = None
    if bar_count == 0:
        missing_entry = {
            "row_index":    int(row_index),
            "event_date":   event_date_iso,
            "ticker":       ticker,
            "role":         role,
            "reason":       (
                f"no cached bars for {ticker} between "
                f"{requested_start} and {requested_end}"
            ),
        }
    elif not sufficient:
        ipo_hint = ""
        if ticker in _KNOWN_IPO_RISKS:
            ipo_date = _KNOWN_IPO_RISKS[ticker]
            if observed_first and observed_first[:10] >= ipo_date:
                ipo_hint = (
                    f" (cached history starts {observed_first}; "
                    f"{ticker} IPO'd {ipo_date}, so pre-IPO bars "
                    "are not available from any source the local "
                    "cache can read)"
                )
        missing_entry = {
            "row_index":    int(row_index),
            "event_date":   event_date_iso,
            "ticker":       ticker,
            "role":         role,
            "reason":       (
                f"insufficient pre-event bars for {ticker}: "
                f"{pre_bars} cached pre-event bars, need at least "
                f"{_ESTIMATION_WINDOW}{ipo_hint}"
            ),
        }
    return {
        "available_entry": available_entry,
        "missing_entry":   missing_entry,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _distinct_tickers(rows: Iterable[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    out:  list[str] = []
    for row in rows:
        for role in ("primary_ticker", "benchmark_ticker"):
            ticker = row.get(role) or ""
            if ticker and ticker not in seen:
                seen.add(ticker)
                out.append(ticker)
    return sorted(out)


def _scan_ipo_risk(
    *,
    required_windows: Sequence[dict[str, Any]],
    tickers_in_batch: Sequence[str],
) -> list[str]:
    """Emit one warning per (ticker, event_date) pair whose required
    window starts before the ticker's known IPO date.

    Warnings are derived from the table of known short-history
    tickers; coverage gaps from any other cause are surfaced via the
    per-row missing_coverage entries rather than as warnings.
    """
    out: list[str] = []
    for ticker, ipo_iso in _KNOWN_IPO_RISKS.items():
        if ticker not in tickers_in_batch:
            continue
        for window in required_windows:
            if window["ticker"] != ticker:
                continue
            start = window["requested_start"]
            est_start = window["estimation_window_start_iso"]
            if start < ipo_iso or est_start < ipo_iso:
                out.append(
                    f"{ticker} (event_date {window['event_date']}): "
                    f"required window starts {start} and the "
                    f"estimation window ~ {est_start} both precede "
                    f"the {ticker} IPO on {ipo_iso}; cached "
                    "pre-IPO bars do not exist and cannot be "
                    "back-filled without a provider call.",
                )
    return out


def _default_price_reader(*, errors: list[str]):
    """Return a callable ``(ticker, start, end) -> (dates, closes)``.

    Wraps :func:`price_cache.read_window_no_fetch` so the rest of
    the preview does not need pandas in its signature.  When the
    cache module cannot be imported, the returned callable always
    yields ``([], [])`` and per-row missing_coverage surfaces the
    gap row by row.
    """
    try:
        from price_cache import read_window_no_fetch  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        errors.append(
            f"price_cache import failed: {type(exc).__name__}: {exc}",
        )

        def _no_cache(ticker: str, start: str, end: str):
            return [], []
        return _no_cache

    def _read(ticker: str, start: str, end: str):
        df = read_window_no_fetch(
            ticker, start=start, end=end, auto_adjust=False,
        )
        if df is None or df.empty:
            return [], []
        dates:  list[str] = []
        closes: list[float] = []
        columns = list(getattr(df, "columns", []))
        by_lower = {str(c).lower(): c for c in columns}
        close_col = by_lower.get("close")
        date_col = by_lower.get("date")
        if close_col is None:
            return [], []
        for idx, row in df.iterrows():
            d = row.get(date_col) if date_col is not None else idx
            if d is None:
                continue
            try:
                close = float(row.get(close_col, 0.0))
            except (TypeError, ValueError):
                continue
            dates.append(_date_key(d))
            closes.append(close)
        return dates, closes
    return _read


def _date_key(value: Any) -> str:
    try:
        if hasattr(value, "date"):
            value = value.date()
    except Exception:  # noqa: BLE001
        pass
    text = str(value)
    return text[:10] if text else ""


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


def _render_text(payload: dict[str, Any]) -> str:
    lines: list[str] = ["=== manual five-event cache-coverage preview ==="]
    lines.append(f"ok:                  {payload['ok']}")
    lines.append(f"input_csv:           {payload['input_csv']}")
    lines.append(f"rows_checked:        {payload['rows_checked']}")
    lines.append(
        f"tickers_needed:      "
        f"{', '.join(payload['tickers_needed']) or '(none)'}",
    )
    lines.append("")
    lines.append("required_windows:")
    for w in payload["required_windows"]:
        lines.append(
            f"  row={w['row_index']} {w['ticker']:>5} ({w['role']}) "
            f"event={w['event_date']} "
            f"window={w['requested_start']}..{w['requested_end']}",
        )
    lines.append("")
    lines.append("available_coverage:")
    for c in payload["available_coverage"]:
        ok_flag = "OK " if c["sufficient_for_estimation_window"] else "GAP"
        first = c.get("observed_first") or "—"
        last  = c.get("observed_last") or "—"
        lines.append(
            f"  [{ok_flag}] row={c['row_index']} {c['ticker']:>5} "
            f"({c['role']}) bars={c['bar_count']:>4} "
            f"pre={c['pre_event_bar_count']:>3} "
            f"post={c['post_event_bar_count']:>3} "
            f"observed={first}..{last}",
        )
    miss = payload.get("missing_coverage") or []
    if miss:
        lines.append("")
        lines.append(f"missing_coverage ({len(miss)}):")
        for m in miss:
            lines.append(
                f"  - row={m['row_index']} {m['ticker']:>5} "
                f"({m['role']}): {m['reason']}",
            )
    rec = payload.get("recommended_next_action")
    if rec:
        lines.append("")
        lines.append("recommended_next_action:")
        lines.append(f"  {rec}")
    warnings = payload.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append("warnings:")
        for w in warnings:
            lines.append(f"  - {w}")
    errors = payload.get("errors") or []
    if errors:
        lines.append("")
        lines.append("errors:")
        for e in errors:
            lines.append(f"  - {e}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(
    argv: Optional[Sequence[str]] = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose price-cache coverage for the manual five-event "
            "expansion batch.  Read-only; never mutates the cache, "
            "never fetches from a provider.  Reports which "
            "(ticker, window) pairs are covered and which are not."
        ),
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Emit structured JSON instead of the text summary.",
    )
    parser.add_argument(
        "--input-csv", default=_DEFAULT_INPUT_CSV, dest="input_csv",
        help=(
            f"Operator-curated CSV (default: {_DEFAULT_INPUT_CSV})."
        ),
    )
    parser.add_argument(
        "--output", default=None, dest="output_path",
        help=(
            "Optional path to write the JSON report.  Default "
            "writes nothing to disk."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(
    argv: Optional[Sequence[str]] = None, *, out: Any = None,
) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    payload = run_coverage_preview(input_csv=args.input_csv)
    if args.output_path:
        try:
            Path(args.output_path).write_text(
                _render_json(payload) + "\n", encoding="utf-8",
            )
        except OSError as exc:
            payload.setdefault("errors", []).append(
                f"failed to write --output {args.output_path}: "
                f"{type(exc).__name__}: {exc}",
            )
    if args.as_json:
        print(_render_json(payload), file=output)
    else:
        print(_render_text(payload), file=output)
    return 0 if payload.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_coverage_preview",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
