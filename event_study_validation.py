"""Gated single-event event-study (SAR/CAR) proof for the live backend.

Reaches the existing :func:`stats.event_study.compute_event_study` engine
for ONE archived event, but only when per-event readiness gates pass.
For non-ready events it returns an explicit ``insufficient_data`` object
with blocking reasons — never a raw-return fallback.

Honest single-event semantics
-----------------------------
``compute_event_study`` yields per-horizon point estimates: the
buy-and-hold abnormal return (``abnormal_return`` / BHAR), the
standardized abnormal return (``sar``, AR over the 60-bar estimation
sigma), and the cumulative abnormal return (``car``).  Cross-sectional
inference — bootstrap CI, p-value, BH-FDR — is a COHORT statistic: with a
single event ``n = 1`` it is undefined (``stats.validation_pipeline``
requires ``min_samples = 8``).  This surface therefore reports the point
estimates and marks ``cross_sectional_inference.available = False`` with
the ``n=1`` reason.  It never claims "confirmed" / "validated" /
statistical significance for a single event, and never routes one event
through ``run_validation_pipeline`` (which would return ``None`` and
mislabel the record ``not_significant``).

Correctness guard
-----------------
``compute_event_study`` derives its daily-AR series by POSITIONAL
consecutive ratios over the price array.  An interior hole, or a series
spliced from two ``auto_adjust`` flags, would silently inflate
``sigma_ar_daily`` and corrupt SAR with no error.  So this module:

  * picks ONE ``auto_adjust`` flag wholesale for both the asset and the
    benchmark series (never unions flags into one series);
  * validates the actual intersected array — enough rows before / after
    the event index, and rough trading-day contiguity (consecutive
    cached closes within ~5 calendar days) over the window the engine
    actually consumes;
  * also requires the benchmark (SPY) pre-event estimation window, which
    the archive-wide readiness report does not check;
  * treats the engine's own ``available = False`` or a non-positive
    ``sigma_ar_daily`` as ``insufficient_data``.

The contiguity guard catches large gaps; a single missing trading day
(<=5 calendar days) is not detected — that assumption is named in the
payload rather than hidden.

Read-only / no network / no mutation
------------------------------------
Reads the SQLite ``price_cache`` table with plain ``SELECT`` statements
through ``db.connect_db()`` (the same path resolver tests rebind via
``db.DB_FILE``); deliberately does not touch the ``price_cache`` module's
``_ensure_table`` write path.  No provider, no ``yfinance``,
``market_check`` / ``market_data``, no LLM, no archive mutation, no
FastAPI surface here (the route lives in ``routes/events.py``).  Reads no
``evidence_artifacts`` / ``cohort_evidence`` — the Phase 1 / Phase 2 FDR pools
are a separate scope and are never mixed into this event-level surface.

Readiness gate parity
---------------------
The gate mirrors ``scripts.stat_validation_readiness_report`` (the
canonical readiness logic).  The four tiny pure date helpers are
replicated locally rather than imported, to avoid pulling a CLI script's
private API into the request path; the report stays the source of truth.
"""
from __future__ import annotations

import sqlite3
from datetime import date as _date, timedelta as _timedelta
from typing import Any, Optional

import db as _db
from stats.event_study import compute_event_study


# Mirror stats.event_study defaults and the readiness report constants.
BENCHMARK_TICKER: str = "SPY"
ESTIMATION_WINDOW: int = 60
HORIZONS: tuple[int, ...] = (1, 5, 20)
# Mirrors stats.validation_pipeline._DEFAULT_MIN_SAMPLES — the cohort size
# below which cross-sectional CI / p-value / FDR are undefined.
MIN_COHORT_SAMPLES: int = 8
# Rough trading-day contiguity guard: two consecutive cached closes more
# than this many calendar days apart signal a hole in the window.
_MAX_GAP_CALENDAR_DAYS: int = 5

STATUS_AVAILABLE = "event_study_available"
STATUS_INSUFFICIENT = "insufficient_data"


# ---------------------------------------------------------------------------
# Replicated pure helpers (canonical: scripts.stat_validation_readiness_report)
# ---------------------------------------------------------------------------


def _primary_ticker(raw_market_tickers: Any) -> Optional[str]:
    """First non-empty ``symbol`` in the market_tickers list, upper-cased."""
    parsed: Any = raw_market_tickers
    if isinstance(parsed, str):
        if not parsed:
            return None
        try:
            import json
            parsed = json.loads(parsed)
        except (TypeError, ValueError):
            return None
    if not isinstance(parsed, list):
        return None
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        sym = entry.get("symbol")
        if isinstance(sym, str) and sym.strip():
            return sym.strip().upper()
    return None


def _parse_iso_date(value: Any) -> Optional[_date]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _business_day_offset(start: _date, n: int) -> _date:
    """Shift ``start`` forward by ``n`` business days (n<=0 → start)."""
    if n <= 0:
        return start
    out = start
    remaining = n
    while remaining > 0:
        out = out + _timedelta(days=1)
        if out.weekday() < 5:
            remaining -= 1
    return out


def _is_finite_positive(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    f = float(value)
    return f == f and f not in (float("inf"), float("-inf")) and f > 0.0


# ---------------------------------------------------------------------------
# Read-only price-cache access (plain SELECT — never writes)
# ---------------------------------------------------------------------------


def _read_closes(ticker: str, *, auto_adjust: bool) -> dict[str, float]:
    """Return ``{iso_date: close}`` for ``ticker`` at one auto_adjust flag.

    Pure read: a single ``SELECT`` through ``db.connect_db()``.  Any DB
    error (missing table, unreachable file) degrades to an empty map.
    """
    out: dict[str, float] = {}
    # ``with sqlite3.connect(...)`` manages the transaction, not the
    # handle — explicit close() is required so a temp DB can be removed
    # on Windows and the live archive never accrues a lingering handle.
    try:
        conn = _db.connect_db()
    except sqlite3.Error:
        return {}
    try:
        rows = conn.execute(
            "SELECT date, close FROM price_cache "
            "WHERE ticker = ? AND auto_adjust = ? AND close IS NOT NULL "
            "ORDER BY date",
            (ticker.upper(), 1 if auto_adjust else 0),
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    for raw_date, raw_close in rows:
        if not isinstance(raw_date, str) or raw_close is None:
            continue
        try:
            out[raw_date[:10]] = float(raw_close)
        except (TypeError, ValueError):
            continue
    return out


def _last_index_le(sorted_dates: list[str], target_iso: str) -> Optional[int]:
    """Largest index ``i`` with ``sorted_dates[i] <= target_iso``, or None."""
    idx: Optional[int] = None
    for i, d in enumerate(sorted_dates):
        if d <= target_iso:
            idx = i
        else:
            break
    return idx


def _is_contiguous(window_dates: list[str]) -> bool:
    """True iff consecutive dates are within ``_MAX_GAP_CALENDAR_DAYS``."""
    for a, b in zip(window_dates, window_dates[1:]):
        try:
            gap = (_date.fromisoformat(b) - _date.fromisoformat(a)).days
        except (ValueError, TypeError):
            return False
        if gap > _MAX_GAP_CALENDAR_DAYS:
            return False
    return True


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def _base(event: dict, primary: Optional[str]) -> dict[str, Any]:
    return {
        "event_id":         event.get("id"),
        "primary_ticker":   primary,
        "benchmark":        BENCHMARK_TICKER,
        "estimation_window": ESTIMATION_WINDOW,
        "horizons":         list(HORIZONS),
    }


def _insufficient(base: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    out = dict(base)
    out["status"] = STATUS_INSUFFICIENT
    # De-dup while preserving order.
    seen: set[str] = set()
    ordered = [r for r in reasons if not (r in seen or seen.add(r))]
    out["blocking_reasons"] = ordered
    return out


def _available(
    base: dict[str, Any],
    es: dict[str, Any],
    *,
    asset_flag: bool,
    bench_flag: bool,
    aligned_sample_size: int,
    event_index: int,
) -> dict[str, Any]:
    per_horizon: list[dict[str, Any]] = []
    horizons_block = es.get("horizons") or {}
    for h in HORIZONS:
        fields = horizons_block.get(h) or horizons_block.get(int(h)) or {}
        per_horizon.append({
            "horizon":          h,
            "raw_return":       fields.get("raw_return"),
            "benchmark_return": fields.get("benchmark_return"),
            "abnormal_return":  fields.get("abnormal_return"),
            "sar":              fields.get("sar"),
            "car":              fields.get("car"),
        })

    out = dict(base)
    out["status"]                  = STATUS_AVAILABLE
    out["auto_adjust_basis"]       = {"asset": asset_flag, "benchmark": bench_flag}
    out["estimation_window_used"]  = es.get("estimation_window_used")
    out["sigma_ar_daily"]          = es.get("sigma_ar_daily")
    out["aligned_sample_size"]     = aligned_sample_size
    out["event_index"]             = event_index
    out["per_horizon"]             = per_horizon
    if asset_flag != bench_flag:
        out["basis_caveat"] = (
            "asset and benchmark use different auto_adjust bases "
            "(adjusted vs raw); each return series is internally "
            "single-flag, so no splice fakes a split-jump, but the "
            "abnormal return carries a small dividend-basis bias over "
            "the 1-20d window"
        )
    out["cross_sectional_inference"] = {
        "available":   False,
        "reason": (
            "single-event proof: bootstrap CI / p-value / BH-FDR are "
            "cross-sectional cohort statistics requiring at least "
            f"{MIN_COHORT_SAMPLES} events (stats.validation_pipeline "
            "min_samples); n=1 here"
        ),
        "n_events":    1,
        "min_samples": MIN_COHORT_SAMPLES,
    }
    out["assumptions"] = [
        "cached closes are treated as consecutive trading days; windows "
        "with gaps over 5 calendar days gate to insufficient_data, but a "
        "single missing trading day is not detected",
    ]
    out["engine"]          = "stats.event_study.compute_event_study"
    out["engine_warnings"] = list(es.get("warnings") or [])
    out["claims"] = {
        "computed":    ["abnormal_return", "sar", "car"],
        "not_claimed": [
            "statistical_significance",
            "confidence_interval",
            "confirmed",
            "validated",
        ],
    }
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_event_study_validation(event: dict) -> dict[str, Any]:
    """Return the gated event-study payload for one event.

    Ready events get a ``status="event_study_available"`` payload with
    per-horizon AR / SAR / CAR; non-ready events get
    ``status="insufficient_data"`` with ``blocking_reasons``.  Read-only.
    """
    if not isinstance(event, dict):
        return _insufficient(_base({}, None), ["no_event"])

    primary = _primary_ticker(event.get("market_tickers"))
    event_d = _parse_iso_date(event.get("event_date"))
    base = _base(event, primary)

    early: list[str] = []
    if event_d is None:
        early.append("missing_or_malformed_event_date")
    if primary is None:
        early.append("no_primary_ticker")
    if early:
        return _insufficient(base, early)

    # Read both auto_adjust flags once for the asset and the benchmark.
    closes = {
        (primary, False):          _read_closes(primary, auto_adjust=False),
        (primary, True):           _read_closes(primary, auto_adjust=True),
        (BENCHMARK_TICKER, False): _read_closes(BENCHMARK_TICKER, auto_adjust=False),
        (BENCHMARK_TICKER, True):  _read_closes(BENCHMARK_TICKER, auto_adjust=True),
    }
    tkr_dates = set(closes[(primary, False)]) | set(closes[(primary, True)])
    spy_dates = set(closes[(BENCHMARK_TICKER, False)]) | set(closes[(BENCHMARK_TICKER, True)])
    event_iso = event_d.isoformat()

    # Date-union readiness gates (friendly blocking reasons).
    reasons: list[str] = []
    if not tkr_dates:
        reasons.append("no_cached_prices_for_primary_ticker")
    if sum(1 for d in tkr_dates if d < event_iso) < ESTIMATION_WINDOW:
        reasons.append("insufficient_estimation_window_primary")
    if sum(1 for d in spy_dates if d < event_iso) < ESTIMATION_WINDOW:
        reasons.append("insufficient_estimation_window_benchmark")
    for h in HORIZONS:
        target = _business_day_offset(event_d, h).isoformat()
        if not any(d >= target for d in tkr_dates):
            reasons.append(f"missing_forward_cache_{h}d")
    spy_target = _business_day_offset(event_d, max(HORIZONS)).isoformat()
    if not any(d >= spy_target for d in spy_dates):
        reasons.append("missing_benchmark_proxy")
    if reasons:
        return _insufficient(base, reasons)

    # Correctness pass.  Each series must be INTERNALLY single-flag (so no
    # splice fakes a split-jump), but the asset and the benchmark may sit
    # on DIFFERENT flags: an abnormal return differences two
    # independently-computed return series, so adjusted-asset minus
    # raw-benchmark is well-formed — it carries only a small dividend-basis
    # bias over the 1-20d window, surfaced as a caveat.  Preference order:
    # matched flags first (no bias), then adjusted-asset / raw-benchmark
    # (adjusted handles asset splits; raw SPY has the broadest coverage),
    # then the remaining cross pair.
    max_h = max(HORIZONS)
    compute_failures: list[str] = []
    flag_pairs = [(False, False), (True, True), (True, False), (False, True)]
    for asset_flag, bench_flag in flag_pairs:
        asset_map = closes[(primary, asset_flag)]
        bench_map = closes[(BENCHMARK_TICKER, bench_flag)]
        common = sorted(set(asset_map) & set(bench_map))
        idx = _last_index_le(common, event_iso)
        if idx is None:
            continue
        if idx < ESTIMATION_WINDOW or (len(common) - 1) < idx + max_h:
            continue
        window = common[idx - ESTIMATION_WINDOW: idx + max_h + 1]
        if not _is_contiguous(window):
            continue
        asset_prices = [asset_map[d] for d in common]
        bench_prices = [bench_map[d] for d in common]
        label = f"asset={'adj' if asset_flag else 'raw'},bench={'adj' if bench_flag else 'raw'}"
        try:
            es = compute_event_study(
                asset_prices=asset_prices,
                benchmark_prices=bench_prices,
                event_index=idx,
                horizons=HORIZONS,
                estimation_window=ESTIMATION_WINDOW,
            )
        except ValueError as exc:
            compute_failures.append(f"engine_error({label}): {exc}")
            continue
        if not es.get("available") or not _is_finite_positive(es.get("sigma_ar_daily")):
            compute_failures.append(
                f"engine_unavailable({label}): "
                f"available={es.get('available')} sigma={es.get('sigma_ar_daily')}"
            )
            continue
        return _available(
            base, es,
            asset_flag=asset_flag,
            bench_flag=bench_flag,
            aligned_sample_size=len(common),
            event_index=idx,
        )

    return _insufficient(
        base,
        ["no_contiguous_aligned_window"] + compute_failures,
    )


def event_study_ar_for_symbol(symbol: str, event_date: Any) -> dict[str, Any]:
    """Read-only per-horizon abnormal return for ONE arbitrary symbol vs SPY.

    An argument adapter (not synthetic data): it computes a real ticker's real
    abnormal return on a real event date by running the existing primary-ticker
    gate with ``symbol`` placed as the sole/primary ticker.  Same output shape,
    same read-only price-cache access — no DB write, no provider, no network.
    Lets the T3 multi-ticker baseline score every affected name, not only the
    first one.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        return _insufficient(_base({}, None), ["no_primary_ticker"])
    return build_event_study_validation(
        {"event_date": event_date, "market_tickers": [{"symbol": symbol.strip()}]}
    )


__all__ = (
    "build_event_study_validation",
    "event_study_ar_for_symbol",
    "BENCHMARK_TICKER",
    "ESTIMATION_WINDOW",
    "HORIZONS",
    "MIN_COHORT_SAMPLES",
    "STATUS_AVAILABLE",
    "STATUS_INSUFFICIENT",
)
