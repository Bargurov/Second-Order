#!/usr/bin/env python3
"""SPY vs XLE benchmark sensitivity comparison smoke.

A read-only descriptive comparison.  For each event in ``--event-ids``
(default ``60,73``) the smoke runs the existing benchmark-sensitivity
machinery twice — once against the SPY benchmark, once against the XLE
benchmark — and reports whether the choice of benchmark changes the
raw-p / FDR interpretation for that event.

The comparison is **gated** by
:func:`scripts.benchmark_sensitivity_preflight.summarize_benchmark_sensitivity_preflight`.
If the supplied DB does not currently carry the cache coverage for
*both* SPY and XLE to run sensitivity for every requested event, the
smoke short-circuits with ``ok=False`` and surfaces the preflight's
blocker reasons.  Comparisons are only produced when the preflight
clears for every (event, benchmark) pair the smoke is about to run.

Read-only by construction
-------------------------

* ``--db-path`` is required.  The smoke never falls through to
  ``db.DB_FILE`` — every run names its target DB explicitly.
* No DB writes anywhere — no INSERT / UPDATE / DELETE, no temp copy
  staging.  The preflight is read-only by construction and the
  sensitivity seam is invoked with the same ``--db-path`` for read-
  only sensitivity computation.
* No ``yfinance``, ``market_data``, ``price_cache.fetch_*``, LLM, or
  paid provider call.  No network.
* No FastAPI surface — never imports ``api`` or ``routes.*``.
* No fabricated prices, returns, p-values, or FDR-q values.  The seam
  is the single source for numerical results; if the seam returns
  ``None`` for a side, the comparison records "uncomputable" without
  inventing a value.

Conservative wording
--------------------

The smoke describes sensitivity, not validation.  No causality claim
is asserted.  Banned tokens in any text the smoke emits: ``proof``,
``proven``, ``validated``, ``automatically``, ``alpha generated``,
``correct ticker``, ``guaranteed``, ``causes``, ``caused``, ``proves``,
``confirms``, ``validates``.  ``note`` text on each comparison is
phrased descriptively ("SPY and XLE results differ on FDR
significance"), never causally ("XLE causes a different conclusion").

Output contract (JSON)::

    {
      "ok":                       bool,
      "db_path":                  str,
      "checked_events":           int,
      "blocked_count":            int,   # combined SPY+XLE preflight
      "comparisons": [
        {
          "event_id":             int,
          "primary_ticker":       str | None,
          "event_date":           str | None,
          "spy_result":           {raw_p, fdr_q, significant, sar} | None,
          "xle_result":           {raw_p, fdr_q, significant, sar} | None,
          "spy_blocker":          {event_id, benchmark_ticker, missing_ticker,
                                   missing_dates, missing_range, horizon,
                                   reason} | None,
          "xle_blocker":          {event_id, benchmark_ticker, missing_ticker,
                                   missing_dates, missing_range, horizon,
                                   reason} | None,
          "changed_interpretation": bool,
          "note":                 str,    # conservative, descriptive
        },
        ...
      ],
      "interpretation_changes":   int,    # count where changed_interpretation
      "warnings":                 list[str],
      "errors":                   list[str],   # carries blocker reasons too
      "recommended_next_action":  str,
    }

``ok`` is True iff:
* a usable ``--db-path`` was supplied, AND
* the SPY+XLE combined preflight reports ``blocked_count == 0``, AND
* no internal error was raised.

When the preflight blocks, ``comparisons`` is empty, ``blocked_count``
echoes the combined SPY+XLE count, and ``errors`` carries one entry
per blocked (event, benchmark) row with the preflight's verbatim
``blocker_reason`` and ``missing_*_ranges``.

Live-path notes
---------------

Against the live archive as of 2026-05-12, the XLE preflight is
blocked for events 60 and 73 (the request packet's live truth).  The
live sensitivity seam is therefore not exercised in production today;
once the operator-approved XLE backfill clears the preflight, the
seam path begins to fire.  Tests patch ``_compute_sensitivity_for_
benchmark`` directly so the contract is pinned without depending on
the live archive.

Usage::

    python scripts/xle_benchmark_sensitivity_compare_smoke.py \\
        --db-path events.db --json
    python scripts/xle_benchmark_sensitivity_compare_smoke.py \\
        --db-path events.db --json --event-ids 60,73 \\
        --output artifacts/xle_compare_smoke.json
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import date as _date
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts import benchmark_sensitivity_preflight as _preflight  # noqa: E402


_DEFAULT_EVENT_IDS:         tuple[int, ...] = (60, 73)
_DEFAULT_HORIZONS:          tuple[int, ...] = (1, 5, 20)
_DEFAULT_ESTIMATION_WINDOW: int             = 60
_DEFAULT_ALPHA:             float           = 0.05

_BENCH_SPY: str = "SPY"
_BENCH_XLE: str = "XLE"


_NOTE_BENCH_AGREE: str = (
    "SPY and XLE descriptive sensitivity results agree on both raw-p "
    "threshold and FDR significance; benchmark choice did not change "
    "the current descriptive conclusion."
)
_NOTE_FDR_FLIP: str = (
    "SPY and XLE descriptive sensitivity results differ on FDR "
    "significance for this event; benchmark choice changes the "
    "descriptive interpretation."
)
_NOTE_RAWP_FLIP: str = (
    "SPY and XLE descriptive sensitivity results differ on raw-p "
    "threshold at alpha=0.05 for this event; FDR significance is "
    "unchanged.  Benchmark choice changes the descriptive raw-p "
    "interpretation."
)
_NOTE_BOTH_FLIP: str = (
    "SPY and XLE descriptive sensitivity results differ on both "
    "raw-p threshold and FDR significance for this event; benchmark "
    "choice changes the descriptive interpretation on both axes."
)
_NOTE_UNCOMPUTABLE: str = (
    "Descriptive sensitivity uncomputable on one side; interpretation "
    "comparison not made."
)


_RECOMMENDED_NO_EVENTS = (
    "No events were checked — supply --event-ids and re-run."
)
_RECOMMENDED_BLOCKED = (
    "{blocked} of {checked} requested (event, benchmark) pair(s) are "
    "blocked by the read-only preflight; inspect 'errors' for the "
    "per-row missing ranges and clear the preflight before the "
    "comparison can run.  This smoke does not backfill the cache."
)
_RECOMMENDED_NO_CHANGES = (
    "All {checked} compared event(s) agree on raw-p threshold and FDR "
    "significance across SPY and XLE; benchmark choice did not change "
    "the current descriptive conclusion."
)
_RECOMMENDED_WITH_CHANGES = (
    "{changed} of {checked} compared event(s) show a descriptive "
    "interpretation change between SPY and XLE.  This is a "
    "sensitivity observation, not a validation; inspect each "
    "comparison's 'note' for the axis that differs."
)
_RECOMMENDED_ALL_UNCOMPUTABLE = (
    "No comparisons could be made: the sensitivity seam returned "
    "uncomputable on at least one side for every one of the {checked} "
    "requested event(s).  Inspect each comparison's 'note' before "
    "drawing a descriptive conclusion."
)
_RECOMMENDED_PARTIAL_UNCOMPUTABLE = (
    "{uncomputable} of {checked} compared event(s) were uncomputable "
    "on at least one side; the remaining {agreed} event(s) agree on "
    "raw-p threshold and FDR significance across SPY and XLE.  "
    "Inspect each comparison's 'note' before drawing a descriptive "
    "conclusion."
)
_RECOMMENDED_ERRORED = (
    "Smoke reported internal errors — inspect 'errors' before relying "
    "on the comparisons."
)
_RECOMMENDED_DB_MISSING = (
    "Supply an existing --db-path before re-running; the smoke is "
    "read-only and cannot create a DB."
)


# ---------------------------------------------------------------------------
# Patchable seams
# ---------------------------------------------------------------------------


def _compute_sensitivity_for_benchmark(
    *,
    db_path:           str,
    event_id:          int,
    event_date:        str | None,
    primary_ticker:    str | None,
    benchmark:         str,
    horizons:          Sequence[int],
    estimation_window: int,
) -> dict[str, Any] | None:
    """Compute descriptive sensitivity for one event against one
    benchmark.

    Read-only by construction.  Opens the SQLite at ``db_path`` only to
    issue ``SELECT`` queries against ``price_cache`` — no provider, no
    ``yfinance``, no LLM, no network, no fabricated values.

    Returns a dict with keys ``raw_p`` / ``fdr_q`` / ``significant`` /
    ``sar`` when a result is available, or ``None`` when the underlying
    rows are insufficient (missing anchor / horizon row, sigma=0,
    missing event metadata, etc.).  ``None`` is honestly surfaced as
    "uncomputable" by the caller — this module does not fabricate raw-p
    or FDR-q values.

    Method (descriptive, no causal claim):

    * Anchor at the trading day immediately before ``event_date``
      (``_trading_day_offset(event_d, -1)``).
    * Endpoint at the ``max(horizons)``-th trading day after
      ``event_date`` (``_trading_day_offset(event_d, max_h)``) — used
      directly, not derived from a range from the anchor.
    * Compute BHAR (Buy-and-Hold Abnormal Return, not CAR) over that
      window: ``(p_end / p_start - 1) - (b_end / b_start - 1)``.
    * Compute sigma from daily abnormal returns
      ``r_primary[i] - r_benchmark[i]`` over the
      ``estimation_window`` most-recent trading days strictly before
      ``event_d`` (uses sample stddev with ``n-1`` degrees of freedom).
    * Test statistic ``z = bhar / (sigma * sqrt(max_h))`` and two-tail
      raw-p via ``math.erfc(|z| / sqrt(2))``.
    * ``fdr_q == raw_p`` (single-test, no BH-FDR adjustment for one
      side at a time — the conservative direction).
    * ``significant = raw_p <= _DEFAULT_ALPHA`` (0.05).
    * ``sar`` carries the BHAR magnitude so the operator can read the
      direction and size alongside the p-value.

    Tests patch this seam directly with synthetic payloads so the
    smoke contract is pinned without depending on real price rows.
    """
    if not isinstance(db_path, str) or not db_path:
        return None
    if not isinstance(event_date, str) or not event_date:
        return None
    if not isinstance(primary_ticker, str) or not primary_ticker:
        return None
    if not isinstance(benchmark, str) or not benchmark:
        return None

    try:
        event_d = _date.fromisoformat(event_date[:10])
    except (ValueError, TypeError):
        return None

    horizons_clean = tuple(
        int(h) for h in (horizons or ()) if isinstance(h, int) and h > 0
    )
    if not horizons_clean:
        return None
    max_h = max(horizons_clean)

    try:
        est_window = int(estimation_window)
    except (TypeError, ValueError):
        return None
    if est_window < 2:
        return None

    primary_prices   = _load_price_map(db_path, primary_ticker)
    benchmark_prices = _load_price_map(db_path, benchmark)
    if not primary_prices or not benchmark_prices:
        return None

    # Anchor at event_d - 1bd (close immediately before event).  End at
    # event_d + max_h bd — call _trading_day_offset directly with max_h
    # so the endpoint counts trading days from the event, not from the
    # anchor (avoids an off-by-one).
    anchor_d = _preflight._trading_day_offset(event_d, -1)
    end_d    = _preflight._trading_day_offset(event_d, max_h)
    anchor_iso = anchor_d.isoformat()
    end_iso    = end_d.isoformat()

    p_start = primary_prices.get(anchor_iso)
    p_end   = primary_prices.get(end_iso)
    b_start = benchmark_prices.get(anchor_iso)
    b_end   = benchmark_prices.get(end_iso)
    if not _is_positive_number(p_start) \
            or not _is_positive_number(p_end) \
            or not _is_positive_number(b_start) \
            or not _is_positive_number(b_end):
        return None

    bhar = (p_end / p_start - 1.0) - (b_end / b_start - 1.0)

    # Estimation-window daily abnormal returns.  ``_trading_days_before``
    # returns the ``est_window`` most-recent trading days strictly
    # before event_d, in ascending order — the same anchors the
    # preflight pinned, so a preflight-cleared event has every required
    # row in the cache.
    est_days = _preflight._trading_days_before(event_d, est_window)
    if len(est_days) < 2:
        return None

    daily_abnormal: list[float] = []
    prev_p: float | None = None
    prev_b: float | None = None
    for d in est_days:
        iso = d.isoformat()
        p = primary_prices.get(iso)
        b = benchmark_prices.get(iso)
        if not _is_positive_number(p) or not _is_positive_number(b):
            return None
        if prev_p is not None and prev_b is not None:
            r_p = p / prev_p - 1.0
            r_b = b / prev_b - 1.0
            daily_abnormal.append(r_p - r_b)
        prev_p = p
        prev_b = b

    n = len(daily_abnormal)
    if n < 2:
        return None

    mean_ab = sum(daily_abnormal) / n
    var_ab  = sum((x - mean_ab) ** 2 for x in daily_abnormal) / (n - 1)
    if var_ab <= 0.0:
        return None
    sigma = math.sqrt(var_ab)

    denom = sigma * math.sqrt(float(max_h))
    if denom <= 0.0:
        return None
    z = bhar / denom
    raw_p = _two_tail_normal_p(z)

    del event_id  # event_id arrives for symmetry with the gate; the
                  # seam keys results by (db_path, event_date, tickers)
                  # not by event_id.

    return {
        "raw_p":       raw_p,
        "fdr_q":       raw_p,
        "significant": raw_p <= _DEFAULT_ALPHA,
        "sar":         bhar,
    }


def _load_price_map(db_path: str, ticker: str) -> dict[str, float]:
    """Return ``{date_iso: close_float}`` for ``ticker`` from
    ``price_cache``.  Read-only — issues a single ``SELECT``.  Returns
    an empty dict on any sqlite error so the caller can degrade
    gracefully to ``None`` (i.e., "uncomputable")."""
    out: dict[str, float] = {}
    if not isinstance(db_path, str) or not db_path:
        return out
    if not isinstance(ticker, str) or not ticker:
        return out
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return out
    try:
        try:
            rows = conn.execute(
                "SELECT date, close FROM price_cache "
                "WHERE ticker = ? "
                "AND date IS NOT NULL AND date != '' "
                "AND close IS NOT NULL "
                "ORDER BY date",
                (ticker.strip().upper(),),
            ).fetchall()
        except sqlite3.Error:
            rows = []
        for d, c in rows:
            if isinstance(d, str) and d \
                    and isinstance(c, (int, float)) \
                    and not isinstance(c, bool):
                out[d] = float(c)
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass
    return out


def _two_tail_normal_p(z: float) -> float:
    """Two-tail p-value for a standard-normal test statistic ``z``,
    via ``math.erfc``.  Stdlib only — no scipy dependency."""
    return math.erfc(abs(z) / math.sqrt(2.0))


def _is_positive_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value > 0
    )


def _build_blocker_for_uncomputed_side(
    *,
    event_id:         int,
    benchmark_ticker: str,
    horizons:         Sequence[int],
) -> dict[str, Any]:
    """Structured blocker for a side the sensitivity seam could not
    compute even though the preflight cleared.

    The six fields the caller relies on are always present: ``event_id``,
    ``benchmark_ticker``, ``missing_ticker``, ``missing_dates``,
    ``missing_range``, ``horizon``, ``reason``.  ``missing_ticker`` is
    always a string (never ``None``) so downstream tools can group
    blockers by ticker without a key check.  When the preflight cleared
    but the seam still couldn't produce a result, the side that
    couldn't be computed is the benchmark side itself, so
    ``missing_ticker`` echoes ``benchmark_ticker``.
    """
    horizons_clean = tuple(
        int(h) for h in (horizons or ()) if isinstance(h, int) and h > 0
    )
    horizon = max(horizons_clean) if horizons_clean else 0
    return {
        "event_id":         event_id,
        "benchmark_ticker": benchmark_ticker,
        "missing_ticker":   benchmark_ticker,
        "missing_dates":    [],
        "missing_range":    None,
        "horizon":          horizon,
        "reason":           "sensitivity_seam_uncomputable_despite_preflight_clear",
    }


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_xle_benchmark_sensitivity_compare_smoke(
    *,
    db_path:           str | None       = None,
    event_ids:         Sequence[int]    = _DEFAULT_EVENT_IDS,
    horizons:          Sequence[int]    = _DEFAULT_HORIZONS,
    estimation_window: int              = _DEFAULT_ESTIMATION_WINDOW,
    alpha:             float            = _DEFAULT_ALPHA,
    output_path:       str | None       = None,
) -> dict[str, Any]:
    """Run the SPY-vs-XLE benchmark-sensitivity comparison smoke.

    See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    # Step 0: --db-path must be supplied AND exist on disk.  The smoke
    # is read-only and never creates a DB.
    if not db_path:
        errors.append(
            "--db-path is required for this smoke; pass an existing "
            "SQLite events.db path on the command line"
        )
        return _finalize(
            envelope=_envelope(
                db_path=db_path or "",
                errors=errors, warnings=warnings,
                recommended_next_action=_RECOMMENDED_DB_MISSING,
            ),
            output_path=output_path,
        )

    if not Path(db_path).exists():
        errors.append(
            f"supplied --db-path does not exist on disk: {db_path!r}"
        )
        return _finalize(
            envelope=_envelope(
                db_path=db_path,
                errors=errors, warnings=warnings,
                recommended_next_action=_RECOMMENDED_DB_MISSING,
            ),
            output_path=output_path,
        )

    event_ids_clean: list[int] = []
    seen: set[int] = set()
    for ev in event_ids:
        if isinstance(ev, int) and ev not in seen:
            event_ids_clean.append(ev)
            seen.add(ev)

    horizons_clean = tuple(
        int(h) for h in horizons if isinstance(h, int) and h > 0
    )
    if not horizons_clean:
        horizons_clean = _DEFAULT_HORIZONS

    # Step 1: run preflight for BOTH benchmarks.  The combined blocked
    # count gates the rest of the smoke; either side blocked means we
    # cannot run sensitivity for both sides.
    spy_report = _safe_preflight(
        db_path=db_path, event_ids=event_ids_clean,
        benchmark=_BENCH_SPY, horizons=horizons_clean,
        estimation_window=int(estimation_window),
        errors=errors,
    )
    xle_report = _safe_preflight(
        db_path=db_path, event_ids=event_ids_clean,
        benchmark=_BENCH_XLE, horizons=horizons_clean,
        estimation_window=int(estimation_window),
        errors=errors,
    )

    spy_blocked = _blocked_rows(spy_report)
    xle_blocked = _blocked_rows(xle_report)
    blocked_count = len(spy_blocked) + len(xle_blocked)

    if errors:
        return _finalize(
            envelope=_envelope(
                db_path=db_path,
                checked_events=len(event_ids_clean),
                blocked_count=blocked_count,
                errors=errors, warnings=warnings,
                recommended_next_action=_RECOMMENDED_ERRORED,
            ),
            output_path=output_path,
        )

    if blocked_count > 0:
        for row in spy_blocked:
            errors.append(_format_blocker(row, _BENCH_SPY))
        for row in xle_blocked:
            errors.append(_format_blocker(row, _BENCH_XLE))
        return _finalize(
            envelope=_envelope(
                db_path=db_path,
                checked_events=len(event_ids_clean),
                blocked_count=blocked_count,
                errors=errors, warnings=warnings,
                recommended_next_action=_RECOMMENDED_BLOCKED.format(
                    blocked=blocked_count,
                    checked=2 * len(event_ids_clean),
                ),
            ),
            output_path=output_path,
        )

    # Step 2: preflight cleared.  Build a per-event metadata map from
    # the XLE report (the SPY report carries identical event metadata
    # — both come from the same events table read).
    event_meta = _event_metadata_map(xle_report)

    comparisons: list[dict[str, Any]] = []
    for ev_id in event_ids_clean:
        meta = event_meta.get(ev_id, {})
        event_date    = meta.get("event_date")
        primary_ticker = meta.get("primary_ticker")

        try:
            spy_result = _compute_sensitivity_for_benchmark(
                db_path=db_path, event_id=ev_id,
                event_date=event_date, primary_ticker=primary_ticker,
                benchmark=_BENCH_SPY, horizons=horizons_clean,
                estimation_window=int(estimation_window),
            )
        except Exception as exc:  # noqa: BLE001 — operator-visible
            errors.append(
                f"sensitivity seam raised for event_id={ev_id} "
                f"benchmark=SPY: {type(exc).__name__}: {exc}"
            )
            spy_result = None

        try:
            xle_result = _compute_sensitivity_for_benchmark(
                db_path=db_path, event_id=ev_id,
                event_date=event_date, primary_ticker=primary_ticker,
                benchmark=_BENCH_XLE, horizons=horizons_clean,
                estimation_window=int(estimation_window),
            )
        except Exception as exc:  # noqa: BLE001 — operator-visible
            errors.append(
                f"sensitivity seam raised for event_id={ev_id} "
                f"benchmark=XLE: {type(exc).__name__}: {exc}"
            )
            xle_result = None

        changed, note = _interpret_comparison(
            spy=spy_result, xle=xle_result, alpha=float(alpha),
        )

        # Per-side blocker fields: ``None`` when the seam produced a
        # result, structured 6-field dict when it did not.  These
        # surface the exact uncomputable-side info an operator needs
        # to interpret a ``None`` result without re-running the
        # preflight by hand.
        spy_blocker = None if spy_result is not None else \
            _build_blocker_for_uncomputed_side(
                event_id=ev_id, benchmark_ticker=_BENCH_SPY,
                horizons=horizons_clean,
            )
        xle_blocker = None if xle_result is not None else \
            _build_blocker_for_uncomputed_side(
                event_id=ev_id, benchmark_ticker=_BENCH_XLE,
                horizons=horizons_clean,
            )

        comparisons.append({
            "event_id":               ev_id,
            "primary_ticker":         primary_ticker,
            "event_date":             event_date,
            "spy_result":             spy_result,
            "xle_result":             xle_result,
            "spy_blocker":            spy_blocker,
            "xle_blocker":            xle_blocker,
            "changed_interpretation": changed,
            "note":                   note,
        })

    interpretation_changes = sum(
        1 for c in comparisons if c["changed_interpretation"]
    )
    uncomputable_count = sum(
        1 for c in comparisons
        if c["spy_result"] is None or c["xle_result"] is None
    )

    if errors:
        recommended = _RECOMMENDED_ERRORED
    elif not comparisons:
        recommended = _RECOMMENDED_NO_EVENTS
    elif interpretation_changes > 0:
        recommended = _RECOMMENDED_WITH_CHANGES.format(
            changed=interpretation_changes,
            checked=len(comparisons),
        )
    elif uncomputable_count >= len(comparisons):
        # Every comparison was uncomputable on at least one side —
        # claiming "all events agree" here would be a false-clear.
        recommended = _RECOMMENDED_ALL_UNCOMPUTABLE.format(
            checked=len(comparisons),
        )
    elif uncomputable_count > 0:
        recommended = _RECOMMENDED_PARTIAL_UNCOMPUTABLE.format(
            uncomputable=uncomputable_count,
            checked=len(comparisons),
            agreed=len(comparisons) - uncomputable_count,
        )
    else:
        recommended = _RECOMMENDED_NO_CHANGES.format(
            checked=len(comparisons),
        )

    return _finalize(
        envelope=_envelope(
            db_path=db_path,
            checked_events=len(comparisons),
            blocked_count=0,
            comparisons=comparisons,
            interpretation_changes=interpretation_changes,
            errors=errors, warnings=warnings,
            recommended_next_action=recommended,
        ),
        output_path=output_path,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_preflight(
    *,
    db_path:           str,
    event_ids:         Sequence[int],
    benchmark:         str,
    horizons:          Sequence[int],
    estimation_window: int,
    errors:            list[str],
) -> dict[str, Any]:
    try:
        return _preflight.summarize_benchmark_sensitivity_preflight(
            db_path=db_path, event_ids=event_ids,
            benchmark=benchmark, horizons=horizons,
            estimation_window=estimation_window,
        )
    except Exception as exc:  # noqa: BLE001 — operator-visible
        errors.append(
            f"preflight raised for benchmark={benchmark}: "
            f"{type(exc).__name__}: {exc}"
        )
        return {}


def _blocked_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in (report or {}).get("rows") or []:
        if not isinstance(row, dict):
            continue
        if not row.get("can_run_sensitivity"):
            out.append(row)
    return out


def _event_metadata_map(report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in (report or {}).get("rows") or []:
        if not isinstance(row, dict):
            continue
        ev_id = row.get("event_id")
        if not isinstance(ev_id, int):
            continue
        out[ev_id] = {
            "event_date":     row.get("event_date")
                              if isinstance(row.get("event_date"), str) else None,
            "primary_ticker": row.get("primary_ticker")
                              if isinstance(row.get("primary_ticker"), str)
                                 and row.get("primary_ticker") else None,
        }
    return out


def _format_blocker(row: dict[str, Any], benchmark: str) -> str:
    ev_id   = row.get("event_id")
    blocker = row.get("blocker_reason") or "cache_gap"
    parts = [f"event_id={ev_id} benchmark={benchmark} {blocker}"]
    primary_ranges   = row.get("missing_primary_ranges")   or []
    benchmark_ranges = row.get("missing_benchmark_ranges") or []
    for rg in primary_ranges:
        if isinstance(rg, dict):
            parts.append(
                f"primary missing {rg.get('start')} → {rg.get('end')} "
                f"({rg.get('reason')})"
            )
    for rg in benchmark_ranges:
        if isinstance(rg, dict):
            parts.append(
                f"benchmark missing {rg.get('start')} → {rg.get('end')} "
                f"({rg.get('reason')})"
            )
    return "; ".join(parts)


def _interpret_comparison(
    *,
    spy: dict[str, Any] | None,
    xle: dict[str, Any] | None,
    alpha: float,
) -> tuple[bool, str]:
    """Return (changed_interpretation, note).

    Two axes are compared:

    * raw-p threshold at ``alpha`` (``raw_p <= alpha``)
    * FDR significance flag (``significant`` from the seam result)

    A side with ``None`` result, or a side missing both raw_p and the
    significance flag, is treated as uncomputable.  The comparison
    records ``changed_interpretation=False`` and the note explains
    why — no causal inference is drawn from a missing side.
    """
    if spy is None or xle is None:
        return False, _NOTE_UNCOMPUTABLE

    spy_raw = _maybe_float(spy.get("raw_p"))
    xle_raw = _maybe_float(xle.get("raw_p"))
    spy_sig = _maybe_bool(spy.get("significant"))
    xle_sig = _maybe_bool(xle.get("significant"))

    if (spy_raw is None and spy_sig is None) \
            or (xle_raw is None and xle_sig is None):
        return False, _NOTE_UNCOMPUTABLE

    # Raw-p axis: only flips when both sides have a raw_p.  If one is
    # missing the raw-p axis is treated as "no observable change".
    raw_flip = False
    if spy_raw is not None and xle_raw is not None:
        raw_flip = (spy_raw <= alpha) != (xle_raw <= alpha)

    # FDR axis: only flips when both sides expose the flag.
    fdr_flip = False
    if spy_sig is not None and xle_sig is not None:
        fdr_flip = (spy_sig != xle_sig)

    if raw_flip and fdr_flip:
        return True, _NOTE_BOTH_FLIP
    if fdr_flip:
        return True, _NOTE_FDR_FLIP
    if raw_flip:
        return True, _NOTE_RAWP_FLIP
    return False, _NOTE_BENCH_AGREE


def _maybe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _maybe_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


# ---------------------------------------------------------------------------
# Envelope + finalize
# ---------------------------------------------------------------------------


def _envelope(
    *,
    db_path:                 str,
    checked_events:          int = 0,
    blocked_count:           int = 0,
    comparisons:             list[dict[str, Any]] | None = None,
    interpretation_changes:  int = 0,
    errors:                  list[str],
    warnings:                list[str],
    recommended_next_action: str,
) -> dict[str, Any]:
    return {
        "ok":                       (not errors) and (blocked_count == 0),
        "db_path":                  db_path,
        "checked_events":           checked_events,
        "blocked_count":            blocked_count,
        "comparisons":              comparisons or [],
        "interpretation_changes":   interpretation_changes,
        "warnings":                 warnings,
        "errors":                   errors,
        "recommended_next_action":  recommended_next_action,
    }


def _finalize(
    *,
    envelope:    dict[str, Any],
    output_path: str | None,
) -> dict[str, Any]:
    if output_path:
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(envelope, fh, indent=2, sort_keys=True, default=str)
        except OSError as exc:
            envelope["errors"].append(
                f"failed to write --output {output_path}: {exc}"
            )
            envelope["ok"] = False
    return envelope


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "SPY vs XLE benchmark sensitivity comparison smoke", "",
    ]
    lines.append(f"OK:                       {report['ok']}")
    lines.append(f"DB path:                  {report['db_path']}")
    lines.append(f"Checked events:           {report['checked_events']}")
    lines.append(f"Blocked count:            {report['blocked_count']}")
    lines.append(f"Interpretation changes:   {report['interpretation_changes']}")
    comparisons = report.get("comparisons") or []
    lines.append(f"Comparisons:              {len(comparisons)}")
    for c in comparisons:
        lines.append(
            f"  - event_id={c.get('event_id')} "
            f"date={c.get('event_date') or '-'} "
            f"primary={c.get('primary_ticker') or '-'}"
        )
        lines.append(f"      spy_result: {c.get('spy_result')!r}")
        lines.append(f"      xle_result: {c.get('xle_result')!r}")
        spy_blk = c.get("spy_blocker")
        xle_blk = c.get("xle_blocker")
        if spy_blk is not None:
            lines.append(
                f"      spy_blocker: ticker={spy_blk.get('missing_ticker')} "
                f"horizon={spy_blk.get('horizon')} "
                f"reason={spy_blk.get('reason')}"
            )
        if xle_blk is not None:
            lines.append(
                f"      xle_blocker: ticker={xle_blk.get('missing_ticker')} "
                f"horizon={xle_blk.get('horizon')} "
                f"reason={xle_blk.get('reason')}"
            )
        lines.append(
            f"      changed_interpretation: {c.get('changed_interpretation')}"
        )
        lines.append(f"      note: {c.get('note')}")
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
            "Read-only SPY-vs-XLE benchmark-sensitivity comparison "
            "smoke.  Gated by the read-only preflight: if either SPY or "
            "XLE cache coverage is missing for a requested event, the "
            "smoke returns ok=False with the blocker reasons.  When the "
            "preflight clears, each event's SPY result and XLE result "
            "are reported side by side; the smoke flags raw-p / FDR "
            "interpretation changes descriptively, without claiming "
            "causality or validation."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", required=True,
        help=(
            "Required path to a SQLite events.db file.  Read-only; the "
            "smoke never writes to this DB or to any temp copy."
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
            f"Comma-separated event_ids to compare (default "
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
        "--alpha", dest="alpha",
        type=float, default=_DEFAULT_ALPHA,
        help=(
            f"Raw-p threshold used to derive descriptive significance "
            f"on each side (default {_DEFAULT_ALPHA})."
        ),
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope to.  When "
            "omitted, the smoke has no filesystem side effect."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = run_xle_benchmark_sensitivity_compare_smoke(
        db_path=args.db_path,
        event_ids=_parse_int_csv(args.event_ids),
        horizons=_parse_int_csv(args.horizons),
        estimation_window=args.estimation_window,
        alpha=args.alpha,
        output_path=args.output_path,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_xle_benchmark_sensitivity_compare_smoke",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
