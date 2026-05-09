#!/usr/bin/env python3
"""Read-only archive statistical validation runner.

Walks the events archive, restricts to rows the
:mod:`scripts.stat_validation_readiness_report` predicate marks as
``fully_ready``, and runs the existing ``stats/`` pipeline end-to-end::

    event_study  →  bootstrap_ar_ci (cohort)  →  p_value_from_sar
                                                       ↓
                                   bh_adjust (cohort, BH)
                                                       ↓
                                   make_stat_validation_record

The runner answers a narrowly-scoped question: *given the price_cache
coverage we already paid for, what statistical evidence does the
archive carry for the event-study horizons we already report?*  It is
deliberately conservative — the surfaced evidence is **statistical
evidence under FDR control**, never "proof", "alpha generated", or
causal language.

Output contract::

    {
      "ok":                 bool,
      "events_evaluated":   int,
      "records_count":      int,
      "significant_count":  int,
      "by_horizon": {                        # keys are str(horizon)
        "1":  {
          "records_count":         int,
          "significant_count":     int,
          "mean_abnormal_return":  float | None,
          "mean_sar":              float | None,
          "ci_low":                float | None,
          "ci_high":               float | None,
        },
        "5":  {...},
        "20": {...},
      },
      "by_mechanism_family": {           # omitted (== {}) when no
        "policy_constraint": {           # evaluated event carries a
          "events_evaluated":  int,      # non-empty mechanism_family
          "records_count":     int,
          "significant_count": int,
        },
        ...
      },
      "errors":             list[str],   # one entry per per-event /
                                         # per-horizon pipeline failure
      "examples": [                      # capped at --limit
        {
          "event_id":          int,
          "headline":          str | None,
          "ticker":            str | None,
          "horizon":           int,
          "abnormal_return":   float | None,
          "sar":               float | None,
          "ci_low":            float | None,
          "ci_high":           float | None,
          "p_value":           float | None,
          "fdr_q":             float | None,
          "interpretation":    str,
        },
        ...
      ],
      "config": {                        # operator drill-in echo
        "alpha":              float,
        "horizons":           list[int],
        "n_bootstrap":        int,
        "seed":               int,
        "estimation_window":  int,
        "limit":              int,
      },
      "recommended_next_action": str,    # operator-facing prose
    }

Read-only by construction
-------------------------
* Issues only ``SELECT`` statements; never INSERT / UPDATE / DELETE;
  never calls ``_ensure_table`` / ``init_db``.
* No DB writes, no LLM seam (``anthropic`` / ``openai``), no
  ``yfinance``, no ``market_check``, ``market_data``, no
  ``price_cache.fetch_daily_cached``, no provider call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* No mutating CLI flag.  ``--limit`` only caps the surfaced examples;
  per-event reads always cover the full archive.

Usage::

    python scripts/archive_stat_validation_run.py
    python scripts/archive_stat_validation_run.py --json
    python scripts/archive_stat_validation_run.py --json --limit 50
    python scripts/archive_stat_validation_run.py --db-path ./events.db --json
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Reuse the readiness predicate so the runner gates on exactly the
# same cache-coverage rules the operator-facing readiness report
# surfaces.  Importing the predicate (not duplicating it) means a
# future tightening flows through both scripts together.
from scripts.stat_validation_readiness_report import (  # noqa: E402
    _BENCHMARK_TICKER,
    _ESTIMATION_WINDOW,
    _HORIZONS,
    _has_estimation_window,
    _has_forward_cache_row,
    _parse_iso_date,
    _primary_ticker,
)

from stats.bootstrap_ci    import bootstrap_ar_ci             # noqa: E402
from stats.event_study     import compute_event_study         # noqa: E402
from stats.fdr             import bh_adjust                   # noqa: E402
from stats.p_values        import p_value_from_sar            # noqa: E402
from stats.stat_validation import (                           # noqa: E402
    DEFAULT_ALPHA,
    make_stat_validation_record,
)


_DEFAULT_LIMIT:       int   = 25
_DEFAULT_ALPHA:       float = DEFAULT_ALPHA
_DEFAULT_N_BOOTSTRAP: int   = 500
_DEFAULT_SEED:        int   = 42


# ---------------------------------------------------------------------------
# Recommended-next-action vocabulary.  Conservative by design: the
# runner reports statistical evidence under FDR control and never
# claims "proof", "alpha", or causal language.
# ---------------------------------------------------------------------------


_RECOMMENDED_NO_READY = (
    "No events met the statistical-readiness predicate; the runner "
    "has nothing to validate.  Refresh the price cache (primary "
    "tickers + SPY benchmark) and re-run."
)


def _recommended_with_evidence(
    *, significant_count: int, records_count: int,
) -> str:
    return (
        f"Statistical evidence: {significant_count} of {records_count} "
        f"per-event/horizon records cleared the significance threshold "
        f"under Benjamini-Hochberg FDR control.  Treat results as "
        f"evidence, not a causal claim."
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _resolve_db_path(db_path: str | None) -> str | None:
    """Return ``db_path`` when supplied, else ``db.DB_FILE``.

    Read-only project import.  Never imports ``api`` or ``routes.*``.
    """
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:  # noqa: BLE001 — best-effort default
        return None
    return getattr(_db, "DB_FILE", None)


def _empty_payload(
    *, limit: int, horizons: Sequence[int],
    alpha: float, n_bootstrap: int, seed: int, estimation_window: int,
) -> dict[str, Any]:
    horizons_t = tuple(int(h) for h in horizons)
    return {
        "ok":                 True,
        "events_evaluated":   0,
        "records_count":      0,
        "significant_count":  0,
        "by_horizon": {
            str(h): {
                "records_count":        0,
                "significant_count":    0,
                "mean_abnormal_return": None,
                "mean_sar":             None,
                "ci_low":               None,
                "ci_high":              None,
            }
            for h in horizons_t
        },
        "by_mechanism_family": {},
        "errors":              [],
        "examples":            [],
        "config": {
            "alpha":             float(alpha),
            "horizons":          list(horizons_t),
            "n_bootstrap":       int(n_bootstrap),
            "seed":              int(seed),
            "estimation_window": int(estimation_window),
            "limit":             int(max(int(limit), 0)),
        },
        "recommended_next_action": _RECOMMENDED_NO_READY,
    }


def _coerce_close_price(value: Any) -> float | None:
    """Return a positive finite float, else ``None``.

    The compute pipeline rejects non-positive / non-finite closes; we
    drop them upstream so a single corrupt cache row doesn't mask a
    whole event's evaluation as an error.
    """
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out) or out <= 0.0:
        return None
    return out


def _load_events_and_cache(
    path: str,
) -> tuple[list[tuple], dict[str, dict[str, float]]]:
    """Read the events table and price_cache once, return:

      * event rows as a list of tuples in id-asc order;
      * a ``{ticker_upper: {iso_date: close}}`` map keyed for the
        compute path.

    When the same ``(ticker, date)`` key carries both ``auto_adjust=1``
    and ``auto_adjust=0`` rows, the adjusted (``=1``) close wins —
    matching the project's ``price_cache.fetch_daily_cached``
    convention.  ``ORDER BY ticker, date, auto_adjust DESC`` lets us
    walk in a single pass and keep the first close seen per key.
    """
    with sqlite3.connect(path) as conn:
        try:
            event_rows = conn.execute(
                "SELECT id, headline, event_date, market_tickers, "
                "       mechanism_family "
                "FROM events ORDER BY id"
            ).fetchall()
        except sqlite3.Error:
            event_rows = []
        try:
            cache_rows = conn.execute(
                "SELECT ticker, date, close, auto_adjust "
                "FROM price_cache "
                "WHERE ticker IS NOT NULL AND ticker != '' "
                "  AND date IS NOT NULL AND date != '' "
                "  AND close IS NOT NULL "
                "ORDER BY ticker, date, auto_adjust DESC"
            ).fetchall()
        except sqlite3.Error:
            cache_rows = []

    closes_by_ticker: dict[str, dict[str, float]] = {}
    for row in cache_rows:
        ticker, date, close, _aa = row
        if not isinstance(ticker, str) or not ticker:
            continue
        if not isinstance(date, str) or not date:
            continue
        coerced = _coerce_close_price(close)
        if coerced is None:
            continue
        per_ticker = closes_by_ticker.setdefault(ticker.upper(), {})
        # First write wins because of the auto_adjust DESC order.
        if date not in per_ticker:
            per_ticker[date] = coerced
    return event_rows, closes_by_ticker


def _cache_dates_view(
    closes_by_ticker: dict[str, dict[str, float]],
) -> dict[str, set[str]]:
    """Project the closes map to a dates-only set per ticker — the
    shape the readiness predicate consumes.
    """
    return {
        ticker: set(closes_map.keys())
        for ticker, closes_map in closes_by_ticker.items()
    }


def _is_fully_ready(
    *,
    event_d: Any,
    primary_ticker: str | None,
    cache_dates_by_ticker: dict[str, set[str]],
    horizons: Sequence[int],
    estimation_window: int,
) -> bool:
    """The runner's readiness gate — identical predicate to the
    ``stat_validation_readiness_report`` ``fully_ready`` flag.
    """
    if event_d is None or primary_ticker is None:
        return False
    for h in horizons:
        if not _has_forward_cache_row(
            cache_dates_by_ticker, primary_ticker, event_d, int(h),
        ):
            return False
    if not _has_forward_cache_row(
        cache_dates_by_ticker, _BENCHMARK_TICKER, event_d, max(horizons),
    ):
        return False
    if not _has_estimation_window(
        cache_dates_by_ticker, primary_ticker, event_d,
        window=estimation_window,
    ):
        return False
    return True


def _aligned_series_for_event(
    *,
    primary_ticker: str,
    closes_by_ticker: dict[str, dict[str, float]],
    event_d: Any,
    estimation_window: int,
    max_horizon: int,
) -> tuple[list[float], list[float], int] | None:
    """Build aligned ``(asset_prices, benchmark_prices, event_index)``.

    Returns ``None`` when the date intersection between asset and
    benchmark cannot satisfy the estimation window or the largest
    forward horizon — those events drop out of the cohort cleanly,
    no exception bubbles.
    """
    asset_map = closes_by_ticker.get(primary_ticker.upper(), {})
    bench_map = closes_by_ticker.get(_BENCHMARK_TICKER, {})
    common = sorted(set(asset_map.keys()) & set(bench_map.keys()))
    if not common:
        return None

    event_iso = event_d.isoformat()
    event_index: int | None = None
    for i, d in enumerate(common):
        if d <= event_iso:
            event_index = i
        else:
            break
    if event_index is None:
        return None
    if event_index < estimation_window:
        return None
    if event_index + max_horizon >= len(common):
        return None

    asset_prices = [asset_map[d] for d in common]
    bench_prices = [bench_map[d] for d in common]
    return asset_prices, bench_prices, event_index


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def run_archive_stat_validation(
    *,
    db_path:           str | None       = None,
    limit:             int              = _DEFAULT_LIMIT,
    alpha:             float            = _DEFAULT_ALPHA,
    n_bootstrap:       int              = _DEFAULT_N_BOOTSTRAP,
    seed:              int              = _DEFAULT_SEED,
    horizons:          Sequence[int]    = _HORIZONS,
    estimation_window: int              = _ESTIMATION_WINDOW,
) -> dict[str, Any]:
    """Run the read-only archive statistical validation pipeline.

    See module docstring for the full output contract.  Every numeric
    keyword has a sensible default so the smoke runner can invoke
    ``run_archive_stat_validation()`` with no args and get a
    deterministic JSON envelope.
    """
    horizons_t = tuple(int(h) for h in horizons)
    capped_limit = max(int(limit), 0)

    empty = _empty_payload(
        limit=capped_limit, horizons=horizons_t,
        alpha=alpha, n_bootstrap=n_bootstrap, seed=seed,
        estimation_window=estimation_window,
    )

    path = _resolve_db_path(db_path)
    if path is None:
        return empty

    try:
        event_rows, closes_by_ticker = _load_events_and_cache(path)
    except sqlite3.Error as exc:
        empty["ok"] = False
        empty["errors"] = [
            f"sqlite read failure: {type(exc).__name__}: {exc}",
        ]
        return empty

    cache_dates_by_ticker = _cache_dates_view(closes_by_ticker)

    # ---- Per-event compute --------------------------------------------------
    errors: list[str] = []
    per_event: list[dict[str, Any]] = []
    for raw_id, raw_headline, raw_event_date, raw_market_tickers, raw_family in event_rows:
        try:
            event_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        primary = _primary_ticker(raw_market_tickers)
        event_d = _parse_iso_date(
            raw_event_date if isinstance(raw_event_date, str) else None,
        )
        if not _is_fully_ready(
            event_d=event_d, primary_ticker=primary,
            cache_dates_by_ticker=cache_dates_by_ticker,
            horizons=horizons_t, estimation_window=estimation_window,
        ):
            continue
        aligned = _aligned_series_for_event(
            primary_ticker=primary,
            closes_by_ticker=closes_by_ticker,
            event_d=event_d,
            estimation_window=estimation_window,
            max_horizon=max(horizons_t),
        )
        if aligned is None:
            continue
        asset_prices, bench_prices, event_index = aligned
        try:
            es_result = compute_event_study(
                asset_prices=asset_prices,
                benchmark_prices=bench_prices,
                event_index=event_index,
                horizons=horizons_t,
                estimation_window=estimation_window,
            )
        except Exception as exc:  # noqa: BLE001 — operator-visible
            errors.append(
                f"event {event_id}: compute_event_study: "
                f"{type(exc).__name__}: {exc}"
            )
            continue
        per_h = es_result.get("horizons") or {}
        per_event.append({
            "event_id":         event_id,
            "headline":         raw_headline if isinstance(raw_headline, str) else None,
            "ticker":           primary,
            "mechanism_family": (
                raw_family if isinstance(raw_family, str) and raw_family
                else None
            ),
            "horizons_data":    {int(h): per_h.get(int(h)) or {} for h in horizons_t},
        })

    if not per_event:
        if errors:
            empty["ok"] = False
            empty["errors"] = errors
        return empty

    # ---- Per-horizon cohort CI on AR samples -------------------------------
    ci_by_h: dict[int, dict[str, Any]] = {}
    mean_sar_by_h: dict[int, float | None] = {}
    for h in horizons_t:
        ar_samples: list[float] = []
        sar_samples: list[float] = []
        for r in per_event:
            row = r["horizons_data"].get(h) or {}
            ar = row.get("abnormal_return")
            sar = row.get("sar")
            if isinstance(ar, (int, float)) and math.isfinite(float(ar)):
                ar_samples.append(float(ar))
            if isinstance(sar, (int, float)) and math.isfinite(float(sar)):
                sar_samples.append(float(sar))
        try:
            ci = bootstrap_ar_ci(
                ar_samples, seed=seed, n_bootstrap=n_bootstrap,
            )
        except Exception as exc:  # noqa: BLE001 — operator-visible
            errors.append(
                f"horizon {h} bootstrap_ar_ci: "
                f"{type(exc).__name__}: {exc}"
            )
            ci = {"lower": None, "upper": None, "mean": None}
        ci_by_h[h] = ci
        mean_sar_by_h[h] = (
            sum(sar_samples) / len(sar_samples) if sar_samples else None
        )

    # ---- Per-record p-values; concatenate; BH adjust as one cohort ---------
    flat_p_values: list[float | None] = []
    flat_index: list[tuple[int, int]] = []  # (per_event index, horizon)
    for ri, r in enumerate(per_event):
        for h in horizons_t:
            row = r["horizons_data"].get(h) or {}
            flat_p_values.append(p_value_from_sar(row.get("sar")))
            flat_index.append((ri, h))

    if flat_p_values:
        fdr_dict = bh_adjust(flat_p_values, alpha=alpha)
    else:
        fdr_dict = {"adjusted": []}
    fdr_qs: list[float | None] = (
        list(fdr_dict.get("adjusted") or [None] * len(flat_p_values))
    )

    # ---- Compose stat_validation records per (event, horizon) --------------
    records: list[dict[str, Any]] = []
    for (ri, h), p_val, fdr_q in zip(flat_index, flat_p_values, fdr_qs):
        r = per_event[ri]
        row = r["horizons_data"].get(h) or {}
        ar  = row.get("abnormal_return")
        sar = row.get("sar")
        ci  = ci_by_h[h]
        try:
            sv = make_stat_validation_record(
                horizon=h,
                abnormal_return=ar,
                sar=sar,
                ci_low=ci.get("lower"),
                ci_high=ci.get("upper"),
                p_value=p_val,
                fdr_q=fdr_q,
                alpha=alpha,
            )
        except Exception as exc:  # noqa: BLE001 — operator-visible
            errors.append(
                f"event {r['event_id']} h={h} "
                f"make_stat_validation_record: {type(exc).__name__}: {exc}"
            )
            continue
        records.append({
            "event_id":         r["event_id"],
            "headline":         r["headline"],
            "ticker":           r["ticker"],
            "mechanism_family": r["mechanism_family"],
            "horizon":          sv["horizon"],
            "abnormal_return":  sv["abnormal_return"],
            "sar":              sv["sar"],
            "ci_low":           sv["ci_low"],
            "ci_high":          sv["ci_high"],
            "p_value":          sv["p_value"],
            "fdr_q":            sv["fdr_q"],
            "statistically_significant": sv["statistically_significant"],
            "interpretation":   sv["interpretation"],
        })

    # ---- Aggregates --------------------------------------------------------
    events_evaluated = len(per_event)
    records_count    = len(records)
    significant_count = sum(
        1 for rec in records if rec["statistically_significant"]
    )

    by_horizon: dict[str, dict[str, Any]] = {}
    for h in horizons_t:
        h_records = [rec for rec in records if rec["horizon"] == h]
        ci = ci_by_h[h]
        by_horizon[str(h)] = {
            "records_count":        len(h_records),
            "significant_count":    sum(
                1 for rec in h_records if rec["statistically_significant"]
            ),
            "mean_abnormal_return": ci.get("mean"),
            "mean_sar":             mean_sar_by_h[h],
            "ci_low":               ci.get("lower"),
            "ci_high":              ci.get("upper"),
        }

    by_mechanism_family: dict[str, dict[str, int]] = {}
    for r in per_event:
        family = r["mechanism_family"]
        if not family:
            continue
        block = by_mechanism_family.setdefault(family, {
            "events_evaluated":  0,
            "records_count":     0,
            "significant_count": 0,
        })
        block["events_evaluated"] += 1
    for rec in records:
        family = rec["mechanism_family"]
        if not family:
            continue
        block = by_mechanism_family.setdefault(family, {
            "events_evaluated":  0,
            "records_count":     0,
            "significant_count": 0,
        })
        block["records_count"] += 1
        if rec["statistically_significant"]:
            block["significant_count"] += 1

    # ---- Examples — capped at limit, deterministic order -------------------
    sorted_records = sorted(
        records, key=lambda rec: (rec["event_id"], rec["horizon"]),
    )
    examples: list[dict[str, Any]] = []
    for rec in sorted_records[:capped_limit]:
        examples.append({
            "event_id":         rec["event_id"],
            "headline":         rec["headline"],
            "ticker":           rec["ticker"],
            "horizon":          rec["horizon"],
            "abnormal_return":  rec["abnormal_return"],
            "sar":              rec["sar"],
            "ci_low":           rec["ci_low"],
            "ci_high":          rec["ci_high"],
            "p_value":          rec["p_value"],
            "fdr_q":            rec["fdr_q"],
            "interpretation":   rec["interpretation"],
        })

    return {
        "ok":                  not errors,
        "events_evaluated":    events_evaluated,
        "records_count":       records_count,
        "significant_count":   significant_count,
        "by_horizon":          by_horizon,
        "by_mechanism_family": by_mechanism_family,
        "errors":              list(errors),
        "examples":            examples,
        "config": {
            "alpha":             float(alpha),
            "horizons":          list(horizons_t),
            "n_bootstrap":       int(n_bootstrap),
            "seed":              int(seed),
            "estimation_window": int(estimation_window),
            "limit":             int(capped_limit),
        },
        "recommended_next_action": _recommended_with_evidence(
            significant_count=significant_count,
            records_count=records_count,
        ),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _render_text(payload: dict[str, Any]) -> str:
    lines: list[str] = ["Archive statistical validation runner", ""]
    lines.append(f"ok:                  {payload['ok']}")
    lines.append(f"events_evaluated:    {payload['events_evaluated']}")
    lines.append(f"records_count:       {payload['records_count']}")
    lines.append(f"significant_count:   {payload['significant_count']}")
    lines.append("")

    lines.append("Per horizon:")
    for h_key in sorted(payload["by_horizon"].keys(), key=lambda x: int(x)):
        block = payload["by_horizon"][h_key]
        lines.append(
            f"  h={h_key:>3}  records={block['records_count']:>4} "
            f"significant={block['significant_count']:>4} "
            f"mean_AR={_fmt(block['mean_abnormal_return'])} "
            f"CI=[{_fmt(block['ci_low'])}, {_fmt(block['ci_high'])}]"
        )
    lines.append("")

    fam_block = payload.get("by_mechanism_family") or {}
    if fam_block:
        lines.append("Per mechanism_family:")
        for family in sorted(fam_block.keys()):
            stats = fam_block[family]
            lines.append(
                f"  {family:<24} events={stats['events_evaluated']:>3} "
                f"records={stats['records_count']:>4} "
                f"significant={stats['significant_count']:>4}"
            )
        lines.append("")

    examples = payload.get("examples") or []
    lines.append(f"Examples listed ({len(examples)}):")
    if examples:
        for ex in examples:
            headline = (ex.get("headline") or "").strip() or "-"
            if len(headline) > 70:
                headline = headline[:67] + "..."
            lines.append(
                f"  id={ex['event_id']} h={ex['horizon']:>3} "
                f"ticker={ex.get('ticker') or '-':<6} "
                f"AR={_fmt(ex['abnormal_return'])} "
                f"SAR={_fmt(ex['sar'])} "
                f"p={_fmt(ex['p_value'])} fdr_q={_fmt(ex['fdr_q'])} "
                f"interp={ex['interpretation']}"
            )
            lines.append(f"      headline: {headline}")
    else:
        lines.append("  -")
    lines.append("")

    errors = payload.get("errors") or []
    if errors:
        lines.append(f"Errors ({len(errors)}):")
        for e in errors:
            lines.append(f"  - {e}")
    else:
        lines.append("Errors: (none)")
    lines.append("")

    lines.append(f"Recommended next action: {payload['recommended_next_action']}")
    return "\n".join(lines)


def _render_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only archive statistical validation runner.  Walks "
            "the events archive, restricts to fully-ready events, and "
            "runs the existing event_study / bootstrap CI / p-value / "
            "FDR / stat_validation pipeline.  Read-only: issues only "
            "SELECT statements; no provider, no LLM, no FastAPI surface."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced per-record examples list at N entries "
            f"(default {_DEFAULT_LIMIT}).  Aggregate counts always "
            f"reflect every evaluated event."
        ),
    )
    parser.add_argument(
        "--db-path",
        dest="db_path",
        default=None,
        help=(
            "Optional path to a SQLite events.db file.  Defaults to "
            "db.DB_FILE so the runner follows the project's "
            "configured archive."
        ),
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=_DEFAULT_ALPHA,
        help=f"Significance threshold (default: {_DEFAULT_ALPHA}).",
    )
    parser.add_argument(
        "--n-bootstrap",
        type=int,
        dest="n_bootstrap",
        default=_DEFAULT_N_BOOTSTRAP,
        help=f"Bootstrap resample count (default: {_DEFAULT_N_BOOTSTRAP}).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=_DEFAULT_SEED,
        help=f"Bootstrap RNG seed (default: {_DEFAULT_SEED}).",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    payload = run_archive_stat_validation(
        db_path=args.db_path,
        limit=args.limit,
        alpha=args.alpha,
        n_bootstrap=args.n_bootstrap,
        seed=args.seed,
    )

    if args.json:
        print(_render_json(payload), file=output)
    else:
        print(_render_text(payload), file=output)
    return 0 if payload["ok"] else 1


__all__: tuple[str, ...] = (
    "run_archive_stat_validation",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
