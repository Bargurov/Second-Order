#!/usr/bin/env python3
"""Manual five-event expansion-batch validation smoke.

Runs the existing zero-cost event-study + raw-p + BH-FDR primitives
over an operator-supplied CSV of (event_date, primary_ticker,
benchmark_ticker, ...) candidates and produces per-(event, horizon)
records that mirror the freeze-candidate vocabulary.  The smoke is
narrow by design:

* It does NOT merge into the main cohort.  Every emitted record
  carries ``source = "manual_five_event_batch"`` so a future grep
  can confirm none of these rows landed in
  ``artifacts/freeze_candidate_evidence.json``.
* It does NOT mutate the live archive, the artifact directory, the
  price cache, or any backup.  No DB write, no provider call, no
  ``yfinance`` / ``market_data`` import, no LLM seam, no FastAPI
  surface.  Prices are read from the existing ``price_cache.db`` via
  the read-only :func:`price_cache.read_window_no_fetch` entry —
  missing coverage is surfaced explicitly, never silently filled.
* It accepts the operator's curated CSV header verbatim and ignores
  any extra columns; only ``event_date``, ``primary_ticker``, and
  ``benchmark_ticker`` are required.  ``headline`` and
  ``mechanism_family`` are read when present.

Statistical contract
--------------------

* Horizons default to ``(1, 5, 20)`` — the same set the
  freeze-candidate artifact uses.
* For each (event, horizon) the smoke computes:

  - ``abnormal_return`` and ``sar`` via
    :func:`stats.event_study.compute_event_study`,
  - ``p_value`` (per-event, per-horizon) via
    :func:`stats.p_values.p_value_from_sar` — a two-sided normal
    z-test treating SAR as a draw from N(0, 1) under the null,
  - ``fdr_q`` via :func:`stats.fdr.bh_adjust` applied to the pooled
    valid p-values across every (event, horizon) record in the
    batch.

* ``fdr_significant`` is ``True`` when the BH-adjusted q is finite
  and ``q <= alpha`` (default :data:`stats.stat_validation.DEFAULT_ALPHA`).
* ``raw_p_candidate`` is ``True`` when the raw p is finite and
  ``p <= alpha`` but the record is not ``fdr_significant`` — the
  conservative "candidate" label the freeze-candidate artifact uses
  for rows where raw evidence does not survive FDR.
* The two labels are disjoint: a record is at most one of
  ``fdr_significant`` or ``raw_p_candidate``.

Note: the freeze-candidate pipeline pools SAR cross-sectionally at
each horizon to produce a single horizon-level p; this smoke is
narrower — its p-values are per-event-per-horizon (z on the
individual SAR).  Both conventions are read-only-cache-friendly; the
distinction is documented here so the records are not confused with
the freeze-candidate per-horizon pooled p.

Output contract::

    {
      "ok":                          bool,
      "input_csv":                   str,
      "horizons":                    [int, ...],
      "alpha":                       float,
      "rows_loaded":                 int,
      "events_evaluated":            int,
      "records_count":               int,
      "fdr_significant_count":       int,
      "raw_p_only_candidate_count":  int,
      "event_records":               [{record_dict}, ...],
      "missing_coverage":            [{coverage_entry}, ...],
      "warnings":                    [str, ...],
      "errors":                      [str, ...],
    }

Each ``record_dict`` carries::

    candidate_id, row_index, headline, event_date, primary_ticker,
    benchmark_ticker, mechanism_family, horizon, abnormal_return,
    sar, p_value, fdr_q, fdr_significant, raw_p_candidate,
    interpretation, source

Each ``coverage_entry`` carries::

    row_index, candidate_id, primary_ticker, benchmark_ticker,
    event_date, headline, mechanism_family, reason

``headline`` and ``mechanism_family`` are propagated from the
operator's CSV so a skipped row still tells the operator which event
it was; both fall back to the empty string when the CSV did not
supply them.

Conservative wording
--------------------

The smoke never claims a record is fit to trade, fit to ship, or
otherwise blessed — the operator owns the next step.  Records are
"candidates"; missing coverage is reported rather than papered over.
The banned-overclaim guard pinned by the test suite refuses any
rendered output that crosses into stronger language.

Usage::

    python scripts/manual_five_event_validation_smoke.py --json
    python scripts/manual_five_event_validation_smoke.py --json \\
        --input-csv examples/manual_five_event_expansion_batch.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import date as _date, timedelta as _timedelta
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_INPUT_CSV: str = "examples/manual_five_event_expansion_batch.csv"
_DEFAULT_HORIZONS:  tuple[int, ...] = (1, 5, 20)
_SOURCE_TOKEN:      str = "manual_five_event_batch"
_CANDIDATE_PREFIX:  str = "manual-five-"

# Calendar-day padding around the event date when we ask the price
# cache for a window.  Generous on both sides so the alignment step
# can locate the event trading day and the estimation window even
# across holidays.
_LOAD_PRE_CAL_DAYS:  int = 200
_LOAD_POST_CAL_DAYS: int = 60

# Required from the upstream estimation-window contract:
# compute_event_study requires event_index >= estimation_window.
_ESTIMATION_WINDOW: int = 60


# ---------------------------------------------------------------------------
# Patchable seam — load aligned prices for one (asset, benchmark, event_date)
# ---------------------------------------------------------------------------


def _load_aligned_prices(
    *,
    primary_ticker:   str,
    benchmark_ticker: str,
    event_date:       str,
) -> dict[str, Any]:
    """Return aligned asset/benchmark close prices and the event index.

    Reads from the existing ``price_cache.db`` via the strictly read-
    only :func:`price_cache.read_window_no_fetch` entry — never falls
    back to a provider, never modifies the cache.  The window spans
    ``event_date - _LOAD_PRE_CAL_DAYS`` to
    ``event_date + _LOAD_POST_CAL_DAYS`` so the estimation window and
    forward horizons have a chance of being covered.

    Returns a dict that always carries the same six keys::

        {
          "available":        bool,
          "asset_prices":     list[float],
          "benchmark_prices": list[float],
          "event_index":      int,
          "dates":            list[str],
          "reason":           str,
        }

    Tests patch this seam directly so the suite never depends on the
    cache contents.  On the un-patched path the function imports
    ``price_cache`` lazily so the smoke's top-level import surface
    stays narrow.
    """
    try:
        anchor = _date.fromisoformat(event_date[:10])
    except (ValueError, TypeError) as exc:
        return _coverage_failure(f"event_date not ISO YYYY-MM-DD: {exc}")

    start = (anchor - _timedelta(days=_LOAD_PRE_CAL_DAYS)).isoformat()
    end   = (anchor + _timedelta(days=_LOAD_POST_CAL_DAYS)).isoformat()

    try:
        from price_cache import read_window_no_fetch  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return _coverage_failure(
            f"price_cache unavailable: {type(exc).__name__}: {exc}"
        )

    try:
        asset_df = read_window_no_fetch(
            primary_ticker, start=start, end=end, auto_adjust=False,
        )
        bench_df = read_window_no_fetch(
            benchmark_ticker, start=start, end=end, auto_adjust=False,
        )
    except Exception as exc:  # noqa: BLE001
        return _coverage_failure(
            f"price_cache read failed: {type(exc).__name__}: {exc}"
        )

    if asset_df is None or bench_df is None:
        return _coverage_failure(
            "price_cache returned None for asset or benchmark window"
        )
    if asset_df.empty:
        return _coverage_failure(
            f"no cached bars for {primary_ticker} between {start} and {end}"
        )
    if bench_df.empty:
        return _coverage_failure(
            f"no cached bars for {benchmark_ticker} between {start} and {end}"
        )

    # Inner-join asset/benchmark on date.  The production cache reader
    # returns a DataFrame indexed by trading date with ``Close`` /
    # ``Volume`` columns; some tests and older seams use explicit
    # ``date`` / ``close`` columns.  Accept both shapes.
    asset_by_date = _close_by_date(asset_df)
    bench_by_date = _close_by_date(bench_df)
    shared_dates = sorted(set(asset_by_date) & set(bench_by_date))
    if not shared_dates:
        return _coverage_failure(
            "asset and benchmark date sets do not overlap"
        )

    # Pick event_index as the last shared trading day at or before the
    # anchor date.  When the anchor lies strictly before the first
    # shared date, return missing.
    event_index = -1
    for idx, d in enumerate(shared_dates):
        if d <= anchor.isoformat():
            event_index = idx
        else:
            break
    if event_index < 0:
        return _coverage_failure(
            f"event_date {anchor.isoformat()} precedes earliest cached "
            f"shared date {shared_dates[0]}"
        )

    asset_prices = [asset_by_date[d] for d in shared_dates]
    bench_prices = [bench_by_date[d] for d in shared_dates]

    # Estimation-window coverage gate so a too-recent ticker (e.g. a
    # post-IPO event without enough pre-event bars) is surfaced as
    # missing rather than reaching compute_event_study and bouncing
    # back as a warning.
    if event_index < _ESTIMATION_WINDOW:
        return _coverage_failure(
            f"insufficient pre-event coverage for {primary_ticker} / "
            f"{benchmark_ticker} at {anchor.isoformat()}: "
            f"{event_index} pre-event shared bars; need at least "
            f"{_ESTIMATION_WINDOW}"
        )

    return {
        "available":        True,
        "asset_prices":     asset_prices,
        "benchmark_prices": bench_prices,
        "event_index":      event_index,
        "dates":            shared_dates,
        "reason":           "",
    }


def _coverage_failure(reason: str) -> dict[str, Any]:
    return {
        "available":        False,
        "asset_prices":     [],
        "benchmark_prices": [],
        "event_index":      -1,
        "dates":            [],
        "reason":           reason,
    }


def _close_by_date(df: Any) -> dict[str, float]:
    if df is None or getattr(df, "empty", False):
        return {}

    try:
        columns = list(getattr(df, "columns", []))
        by_lower = {str(c).lower(): c for c in columns}
        close_col = by_lower.get("close")
        date_col = by_lower.get("date")
    except Exception:  # noqa: BLE001
        return {}
    if close_col is None:
        return {}

    out: dict[str, float] = {}
    try:
        iterator = df.iterrows()
    except AttributeError:
        return out
    for idx, row in iterator:
        date_value = row.get(date_col) if date_col is not None else idx
        close_value = row.get(close_col)
        try:
            close_f = float(close_value)
        except (TypeError, ValueError):
            continue
        date_s = _date_key(date_value)
        if date_s:
            out[date_s] = close_f
    return out


def _date_key(value: Any) -> str:
    try:
        if hasattr(value, "date"):
            value = value.date()
    except Exception:  # noqa: BLE001
        pass
    text = str(value)
    return text[:10] if text else ""


# ---------------------------------------------------------------------------
# Pure compute — main entry point
# ---------------------------------------------------------------------------


def run_manual_five_event_validation(
    *,
    input_csv:         str,
    horizons:          Sequence[int] | None = None,
    alpha:             float | None = None,
    estimation_window: int = _ESTIMATION_WINDOW,
) -> dict[str, Any]:
    """Read ``input_csv`` and return the per-event-per-horizon envelope.

    See the module docstring for the full output contract.
    """
    from stats.event_study import compute_event_study  # noqa: PLC0415
    from stats.p_values import p_value_from_sar  # noqa: PLC0415
    from stats.fdr import bh_adjust  # noqa: PLC0415
    from stats.stat_validation import (  # noqa: PLC0415
        DEFAULT_ALPHA,
        INTERPRETATION_INSUFFICIENT_DATA,
        INTERPRETATION_NOT_SIGNIFICANT,
        INTERPRETATION_SIGNIFICANT_NEGATIVE,
        INTERPRETATION_SIGNIFICANT_POSITIVE,
    )

    h_tuple = tuple(int(h) for h in (horizons or _DEFAULT_HORIZONS))
    a_value = float(alpha) if alpha is not None else float(DEFAULT_ALPHA)

    warnings: list[str] = []
    errors:   list[str] = []
    records:  list[dict[str, Any]] = []
    missing:  list[dict[str, Any]] = []
    rows_loaded:      int = 0
    events_evaluated: int = 0

    csv_path = Path(input_csv)
    if not csv_path.is_file():
        errors.append(
            f"input CSV missing: {input_csv!r}; the smoke requires the "
            f"operator-curated batch CSV on disk"
        )
        return _envelope(
            input_csv=input_csv,
            horizons=h_tuple,
            alpha=a_value,
            rows_loaded=0,
            events_evaluated=0,
            records=records,
            missing=missing,
            warnings=warnings,
            errors=errors,
        )

    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            raw_rows = list(reader)
    except (OSError, csv.Error) as exc:
        errors.append(
            f"failed to read input CSV {input_csv!r}: "
            f"{type(exc).__name__}: {exc}"
        )
        return _envelope(
            input_csv=input_csv,
            horizons=h_tuple,
            alpha=a_value,
            rows_loaded=0,
            events_evaluated=0,
            records=records,
            missing=missing,
            warnings=warnings,
            errors=errors,
        )

    rows_loaded = len(raw_rows)

    for row_index, raw in enumerate(raw_rows):
        candidate_id = f"{_CANDIDATE_PREFIX}{row_index + 1:03d}"
        event_date       = (raw.get("event_date") or "").strip()
        primary_ticker   = (raw.get("primary_ticker") or "").strip().upper()
        benchmark_ticker = (raw.get("benchmark_ticker") or "").strip().upper()
        headline         = (raw.get("headline") or "").strip()
        mechanism_family = (raw.get("mechanism_family") or "").strip()

        missing_fields: list[str] = []
        if not event_date:
            missing_fields.append("event_date")
        if not primary_ticker:
            missing_fields.append("primary_ticker")
        if not benchmark_ticker:
            missing_fields.append("benchmark_ticker")
        if missing_fields:
            missing.append(_coverage_record(
                row_index=row_index,
                candidate_id=candidate_id,
                primary_ticker=primary_ticker,
                benchmark_ticker=benchmark_ticker,
                event_date=event_date,
                headline=headline,
                mechanism_family=mechanism_family,
                reason=(
                    "row missing required field(s): "
                    + ", ".join(missing_fields)
                ),
            ))
            continue

        coverage = _load_aligned_prices(
            primary_ticker=primary_ticker,
            benchmark_ticker=benchmark_ticker,
            event_date=event_date,
        )
        if not coverage.get("available"):
            missing.append(_coverage_record(
                row_index=row_index,
                candidate_id=candidate_id,
                primary_ticker=primary_ticker,
                benchmark_ticker=benchmark_ticker,
                event_date=event_date,
                headline=headline,
                mechanism_family=mechanism_family,
                reason=str(coverage.get("reason") or "no coverage"),
            ))
            continue

        # ``compute_event_study`` may raise ValueError on caller bugs
        # (mismatched array shapes, NaN/inf prices).  Treat those
        # defensively as missing-coverage so a malformed cache row
        # cannot crash the smoke for the rest of the batch.
        try:
            es = compute_event_study(
                asset_prices=coverage["asset_prices"],
                benchmark_prices=coverage["benchmark_prices"],
                event_index=int(coverage["event_index"]),
                horizons=h_tuple,
                estimation_window=estimation_window,
            )
        except (ValueError, TypeError) as exc:
            missing.append(_coverage_record(
                row_index=row_index,
                candidate_id=candidate_id,
                primary_ticker=primary_ticker,
                benchmark_ticker=benchmark_ticker,
                event_date=event_date,
                headline=headline,
                mechanism_family=mechanism_family,
                reason=(
                    f"event-study compute raised "
                    f"{type(exc).__name__}: {exc}"
                ),
            ))
            continue

        events_evaluated += 1
        es_horizons = es.get("horizons") or {}
        for h in h_tuple:
            h_block = es_horizons.get(h) or es_horizons.get(int(h)) or {}
            ar  = h_block.get("abnormal_return")
            sar = h_block.get("sar")
            p   = p_value_from_sar(sar)
            records.append({
                "candidate_id":     candidate_id,
                "row_index":        row_index,
                "headline":         headline,
                "event_date":       event_date,
                "primary_ticker":   primary_ticker,
                "benchmark_ticker": benchmark_ticker,
                "mechanism_family": mechanism_family,
                "horizon":          int(h),
                "abnormal_return":  _scalar(ar),
                "sar":              _scalar(sar),
                "p_value":          _scalar(p),
                "fdr_q":            None,       # filled in BH pass
                "fdr_significant":  False,      # filled in BH pass
                "raw_p_candidate":  False,      # filled in BH pass
                "interpretation":   "",         # filled in BH pass
                "source":           _SOURCE_TOKEN,
            })

    _apply_fdr_and_labels(
        records=records,
        alpha=a_value,
        interpretation_pos=INTERPRETATION_SIGNIFICANT_POSITIVE,
        interpretation_neg=INTERPRETATION_SIGNIFICANT_NEGATIVE,
        interpretation_not_sig=INTERPRETATION_NOT_SIGNIFICANT,
        interpretation_insuff=INTERPRETATION_INSUFFICIENT_DATA,
        bh_adjust=bh_adjust,
    )

    fdr_count = sum(1 for r in records if r["fdr_significant"])
    rawp_only_count = sum(
        1 for r in records
        if r["raw_p_candidate"] and not r["fdr_significant"]
    )

    return _envelope(
        input_csv=input_csv,
        horizons=h_tuple,
        alpha=a_value,
        rows_loaded=rows_loaded,
        events_evaluated=events_evaluated,
        records=records,
        missing=missing,
        warnings=warnings,
        errors=errors,
        fdr_significant_count=fdr_count,
        raw_p_only_candidate_count=rawp_only_count,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply_fdr_and_labels(
    *,
    records:                list[dict[str, Any]],
    alpha:                  float,
    interpretation_pos:     str,
    interpretation_neg:     str,
    interpretation_not_sig: str,
    interpretation_insuff:  str,
    bh_adjust,
) -> None:
    """Run BH adjustment over the pooled p-values and write
    ``fdr_q`` / ``fdr_significant`` / ``raw_p_candidate`` /
    ``interpretation`` back to each record in-place.
    """
    p_values = [r.get("p_value") for r in records]
    bh = bh_adjust(p_values, alpha=alpha)
    adjusted = bh.get("adjusted") or []
    for idx, rec in enumerate(records):
        p = rec.get("p_value")
        q = adjusted[idx] if idx < len(adjusted) else None
        rec["fdr_q"] = _scalar(q)

        is_fdr_sig = (
            isinstance(q, float)
            and math.isfinite(q)
            and q <= alpha
        )
        is_raw_p = (
            isinstance(p, float)
            and math.isfinite(p)
            and p <= alpha
            and not is_fdr_sig
        )
        rec["fdr_significant"] = bool(is_fdr_sig)
        rec["raw_p_candidate"] = bool(is_raw_p)

        sar = rec.get("sar")
        if is_fdr_sig and isinstance(sar, float) and math.isfinite(sar):
            rec["interpretation"] = (
                interpretation_pos if sar >= 0.0 else interpretation_neg
            )
        elif p is None or not (
            isinstance(p, float) and math.isfinite(p)
        ):
            rec["interpretation"] = interpretation_insuff
        else:
            rec["interpretation"] = interpretation_not_sig


def _scalar(value: Any) -> float | None:
    """Normalise numeric values to ``float | None``; NaN / inf → None."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _coverage_record(
    *,
    row_index:        int,
    candidate_id:     str,
    primary_ticker:   str,
    benchmark_ticker: str,
    event_date:       str,
    reason:           str,
    headline:         str = "",
    mechanism_family: str = "",
) -> dict[str, Any]:
    return {
        "row_index":        int(row_index),
        "candidate_id":     candidate_id,
        "primary_ticker":   primary_ticker,
        "benchmark_ticker": benchmark_ticker,
        "event_date":       event_date,
        "headline":         str(headline or ""),
        "mechanism_family": str(mechanism_family or ""),
        "reason":           reason,
    }


def _envelope(
    *,
    input_csv:                  str,
    horizons:                   tuple[int, ...],
    alpha:                      float,
    rows_loaded:                int,
    events_evaluated:           int,
    records:                    list[dict[str, Any]],
    missing:                    list[dict[str, Any]],
    warnings:                   list[str],
    errors:                     list[str],
    fdr_significant_count:      int = 0,
    raw_p_only_candidate_count: int = 0,
) -> dict[str, Any]:
    return {
        "ok":                          not errors,
        "input_csv":                   input_csv,
        "horizons":                    list(horizons),
        "alpha":                       float(alpha),
        "rows_loaded":                 int(rows_loaded),
        "events_evaluated":            int(events_evaluated),
        "records_count":               len(records),
        "fdr_significant_count":       int(fdr_significant_count),
        "raw_p_only_candidate_count":  int(raw_p_only_candidate_count),
        "event_records":               list(records),
        "missing_coverage":            list(missing),
        "warnings":                    list(warnings),
        "errors":                      list(errors),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(envelope: dict[str, Any]) -> str:
    return json.dumps(envelope, indent=2, sort_keys=True, default=str)


def _render_text(envelope: dict[str, Any]) -> str:
    lines: list[str] = ["Manual five-event expansion-batch validation", ""]
    lines.append(f"OK:                  {envelope['ok']}")
    lines.append(f"Input CSV:           {envelope['input_csv']}")
    lines.append(f"Horizons:            {envelope['horizons']}")
    lines.append(f"Alpha:               {envelope['alpha']}")
    lines.append(f"Rows loaded:         {envelope['rows_loaded']}")
    lines.append(f"Events evaluated:    {envelope['events_evaluated']}")
    lines.append(f"Records:             {envelope['records_count']}")
    lines.append(f"FDR-significant:     {envelope['fdr_significant_count']}")
    lines.append(
        f"Raw-p only:          {envelope['raw_p_only_candidate_count']}"
    )
    if envelope["missing_coverage"]:
        lines.append("")
        lines.append(
            f"Missing coverage ({len(envelope['missing_coverage'])}):"
        )
        for m in envelope["missing_coverage"]:
            lines.append(
                f"  - row {m['row_index']:>2}  "
                f"{m['primary_ticker']:>6}/{m['benchmark_ticker']:<6}  "
                f"{m['event_date']}  {m['reason']}"
            )
    if envelope["event_records"]:
        lines.append("")
        lines.append("Records:")
        for r in envelope["event_records"]:
            p = r.get("p_value")
            q = r.get("fdr_q")
            sar = r.get("sar")
            lines.append(
                f"  - row {r['row_index']:>2}  "
                f"{r['primary_ticker']:>6}/{r['benchmark_ticker']:<6}  "
                f"h={int(r['horizon']):>2}  "
                f"sar={_fmt(sar)}  p={_fmt(p)}  q={_fmt(q)}  "
                f"{r['interpretation']}"
            )
    if envelope.get("warnings"):
        lines.append("")
        lines.append("Warnings:")
        for w in envelope["warnings"]:
            lines.append(f"  - {w}")
    if envelope.get("errors"):
        lines.append("")
        lines.append("Errors:")
        for e in envelope["errors"]:
            lines.append(f"  - {e}")
    return "\n".join(lines)


def _fmt(value: Any) -> str:
    if value is None:
        return "    - "
    try:
        return f"{float(value):+.4f}"
    except (TypeError, ValueError):
        return "    - "


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only manual-five-event expansion-batch validation "
            "smoke.  Runs the existing event-study + raw-p + BH-FDR "
            "primitives over an operator-curated CSV of (event_date, "
            "primary_ticker, benchmark_ticker) candidates and emits "
            "per-(event, horizon) records.  Does not write to the "
            "DB, does not start a server, does not import any paid "
            "provider or LLM seam, and does not merge into the main "
            "cohort."
        ),
    )
    parser.add_argument(
        "--input-csv", dest="input_csv", default=_DEFAULT_INPUT_CSV,
        help=(
            "Path to the operator-curated batch CSV.  Defaults to "
            f"{_DEFAULT_INPUT_CSV!r}.  Read-only."
        ),
    )
    parser.add_argument(
        "--horizons", dest="horizons", default=None,
        help=(
            "Comma-separated forward horizons (days).  Defaults to "
            f"{','.join(str(h) for h in _DEFAULT_HORIZONS)}."
        ),
    )
    parser.add_argument(
        "--alpha", dest="alpha", type=float, default=None,
        help=(
            "Significance alpha for the BH adjustment.  Defaults to "
            "the canonical stat_validation alpha."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _parse_horizons(spec: str | None) -> tuple[int, ...] | None:
    if not spec:
        return None
    out: list[int] = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            out.append(int(token))
        except ValueError as exc:
            raise SystemExit(
                f"invalid --horizons value {token!r}: {exc}"
            ) from exc
    return tuple(out) if out else None


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    envelope = run_manual_five_event_validation(
        input_csv=args.input_csv,
        horizons=_parse_horizons(args.horizons),
        alpha=args.alpha,
    )
    if args.json:
        print(_render_json(envelope), file=output)
    else:
        print(_render_text(envelope), file=output)
    return 0 if envelope.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_manual_five_event_validation",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
