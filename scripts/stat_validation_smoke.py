#!/usr/bin/env python3
"""scripts/stat_validation_smoke.py

Read-only pipeline smoke over deterministic synthetic data.

Wires the four ``stats/`` building blocks end-to-end and emits a
single :mod:`stats.stat_validation` record per requested horizon::

    event_study  →  bootstrap CI  →  p-value  →  FDR  →  stat_validation

Pipeline detail
---------------
1. **Synthetic data.**  For each event in the cohort we generate a
   pair of asset / benchmark price series.  Returns share a common
   market factor (so the benchmark is informative), each side carries
   independent idiosyncratic noise, and a fixed positive shock is
   injected on the day after the event close (which propagates into
   every forward-horizon window).  All RNG is via
   :class:`random.Random(seed)` so the entire pipeline is byte-equal
   under a fixed seed.

2. **Per-event event study.**  :func:`stats.event_study.compute_event_study`
   returns ``(abnormal_return, sar)`` per horizon.  The cohort
   collects those numbers per horizon for downstream aggregation.

3. **Bootstrap CI of mean AR.**  Per horizon we feed the cohort's AR
   samples to :func:`stats.bootstrap_ci.bootstrap_ar_ci` to recover
   ``(mean, ci_low, ci_high)``.  Insufficient samples surface as
   ``None`` bounds and propagate cleanly into the schema.

4. **Cohort p-value.**  Under H0 the per-event SAR is approximately
   ``N(0, 1)`` and the cohort mean SAR is approximately
   ``N(0, 1/sqrt(n))``.  We standardize the cohort mean
   (``z = mean_sar * sqrt(n)``) and compute the two-sided normal-CDF
   p-value via :class:`statistics.NormalDist`.  No external
   distribution package required.

5. **FDR adjustment.**  :func:`stats.fdr.bh_adjust` produces an
   adjusted q-value per horizon.

6. **Schema composition.**  Each horizon's mean AR / mean SAR / CI
   bounds / p-value / fdr_q feed
   :func:`stats.stat_validation.make_stat_validation_record` so every
   record carries the canonical nine fields.

Read-only / no I/O
------------------
* No DB seam, no provider, no ``yfinance``, no LLM, no FastAPI app.
* No filesystem writes.  No network.
* The smoke is a pure compute path — every dependency lives under
  ``stats/``.

Usage::

    python scripts/stat_validation_smoke.py
    python scripts/stat_validation_smoke.py --json
    python scripts/stat_validation_smoke.py --json --seed 7
    python scripts/stat_validation_smoke.py --json --horizons 1 5 20
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from statistics import NormalDist
from typing import Any, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stats.bootstrap_ci   import bootstrap_ar_ci          # noqa: E402
from stats.event_study    import compute_event_study      # noqa: E402
from stats.fdr            import bh_adjust                # noqa: E402
from stats.stat_validation import (                       # noqa: E402
    DEFAULT_ALPHA,
    make_stat_validation_record,
)


# ---------------------------------------------------------------------------
# Defaults — tuned so the default smoke produces non-trivial output:
# the cohort is large enough for the bootstrap default ``min_samples=8``
# and the shock magnitude × estimation-window noise yields a clearly
# significant cohort z-stat at h=1.
# ---------------------------------------------------------------------------


_DEFAULT_N_EVENTS:    int   = 12
_DEFAULT_N_DAYS:      int   = 200
_DEFAULT_EVENT_INDEX: int   = 120
_DEFAULT_HORIZONS:    tuple[int, ...] = (1, 5, 20)
_DEFAULT_SEED:        int   = 42
_DEFAULT_ALPHA_VALUE: float = DEFAULT_ALPHA
_DEFAULT_BOOTSTRAP_N: int   = 500
_DEFAULT_EVENT_SHOCK: float = 0.04   # +4% one-day shock to the asset
_DEFAULT_MARKET_VOL:  float = 0.010  # 1.0% daily market factor stddev
_DEFAULT_IDIO_VOL:    float = 0.005  # 0.5% daily idiosyncratic stddev
_DEFAULT_DRIFT:       float = 0.0001 # ~2.5% annualized drift
_RETURN_FLOOR:        float = -0.40  # safety clamp so prices stay positive


# ---------------------------------------------------------------------------
# Synthetic data — deterministic under a fixed seed.
# ---------------------------------------------------------------------------


def _make_synthetic_pair(
    *,
    seed:         int,
    n_days:       int,
    event_index:  int,
    event_shock:  float,
    market_vol:   float,
    idio_vol:     float,
    drift:        float,
) -> tuple[list[float], list[float]]:
    """Return aligned asset / benchmark price arrays of length ``n_days``.

    The shock is applied on day ``event_index + 1`` so the ``t=0``
    close is still pre-shock; the close-to-close return from
    ``event_index → event_index + 1`` carries the shock.  This is
    what :func:`compute_event_study` consumes when computing
    ``abnormal_return`` at h=1.
    """
    rng = random.Random(seed)
    asset = [100.0]
    bench = [100.0]
    for t in range(1, n_days):
        # Shared market factor produces correlation between the two
        # series, so the benchmark is informative for normalization.
        market = rng.gauss(0.0, market_vol)
        idio_a = rng.gauss(0.0, idio_vol)
        idio_b = rng.gauss(0.0, idio_vol)
        ret_asset = drift + market + idio_a
        ret_bench = drift + market + idio_b
        if t == event_index + 1:
            ret_asset += event_shock
        # Defensive clamp — prices must stay positive for
        # compute_event_study to accept them.  The clamp only fires
        # on extreme negative draws that are vanishingly rare under
        # the default vols.
        if ret_asset < _RETURN_FLOOR:
            ret_asset = _RETURN_FLOOR
        if ret_bench < _RETURN_FLOOR:
            ret_bench = _RETURN_FLOOR
        asset.append(asset[-1] * (1.0 + ret_asset))
        bench.append(bench[-1] * (1.0 + ret_bench))
    return asset, bench


# ---------------------------------------------------------------------------
# Cohort aggregation
# ---------------------------------------------------------------------------


def _collect_per_horizon_samples(
    cohort_results: list[dict[str, Any]],
    horizons:       Sequence[int],
) -> tuple[dict[int, list[float]], dict[int, list[float]]]:
    """Pivot a list of per-event ``compute_event_study`` results into
    ``{horizon: [ar_per_event, ...]}`` plus the matching SAR map.

    Per-event missing values (insufficient estimation window, horizon
    overflow) are filtered out — those events simply don't contribute
    to that horizon's cohort sample.
    """
    ar_by_h:  dict[int, list[float]] = {int(h): [] for h in horizons}
    sar_by_h: dict[int, list[float]] = {int(h): [] for h in horizons}
    for result in cohort_results:
        per_h = result.get("horizons") or {}
        for h in horizons:
            row = per_h.get(int(h)) or {}
            ar  = row.get("abnormal_return")
            sar = row.get("sar")
            if isinstance(ar, (int, float)) and math.isfinite(float(ar)):
                ar_by_h[int(h)].append(float(ar))
            if isinstance(sar, (int, float)) and math.isfinite(float(sar)):
                sar_by_h[int(h)].append(float(sar))
    return ar_by_h, sar_by_h


def _cohort_p_value(sar_samples: list[float]) -> Optional[float]:
    """Two-sided p-value for the cohort mean SAR under H0.

    Under H0 each event's SAR is approximately ``N(0, 1)``.  The
    cohort mean SAR is then approximately ``N(0, 1/sqrt(n))``;
    standardizing back to a unit normal gives ``z = mean_sar *
    sqrt(n)``.  We use :class:`statistics.NormalDist` so this stays a
    pure-stdlib computation.
    """
    n = len(sar_samples)
    if n < 1:
        return None
    mean_sar = sum(sar_samples) / n
    if not math.isfinite(mean_sar):
        return None
    z = mean_sar * math.sqrt(n)
    if not math.isfinite(z):
        return None
    # ``2 * cdf(-|z|)`` is more numerically stable for tiny tails
    # than ``2 * (1 - cdf(|z|))``.
    p = 2.0 * NormalDist(0.0, 1.0).cdf(-abs(z))
    if p < 0.0:
        p = 0.0
    elif p > 1.0:
        p = 1.0
    return p


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------


def run_smoke(
    *,
    n_events:     int   = _DEFAULT_N_EVENTS,
    n_days:       int   = _DEFAULT_N_DAYS,
    event_index:  int   = _DEFAULT_EVENT_INDEX,
    horizons:     Sequence[int] = _DEFAULT_HORIZONS,
    seed:         int   = _DEFAULT_SEED,
    alpha:        float = _DEFAULT_ALPHA_VALUE,
    n_bootstrap:  int   = _DEFAULT_BOOTSTRAP_N,
    event_shock:  float = _DEFAULT_EVENT_SHOCK,
    market_vol:   float = _DEFAULT_MARKET_VOL,
    idio_vol:     float = _DEFAULT_IDIO_VOL,
    drift:        float = _DEFAULT_DRIFT,
) -> dict[str, Any]:
    """Run the full pipeline and return the smoke payload.

    Returns a dict with at least four required keys: ``ok``,
    ``records_count``, ``significant_count``, ``errors``.  The
    ``records`` list and ``config`` echo are included for operator
    drill-in but are not part of the minimum contract.
    """
    horizons_t = tuple(int(h) for h in horizons)
    errors: list[str] = []

    # 1. Per-event event study.  Each event uses a derived sub-seed so
    # cohort members produce distinct but reproducible data.
    cohort_results: list[dict[str, Any]] = []
    for i in range(n_events):
        sub_seed = seed * 1_000_003 + i
        try:
            asset, bench = _make_synthetic_pair(
                seed=sub_seed,
                n_days=n_days,
                event_index=event_index,
                event_shock=event_shock,
                market_vol=market_vol,
                idio_vol=idio_vol,
                drift=drift,
            )
            es_result = compute_event_study(
                asset_prices=asset,
                benchmark_prices=bench,
                event_index=event_index,
                horizons=horizons_t,
            )
        except Exception as exc:  # noqa: BLE001 — operator log
            errors.append(
                f"event {i}: {type(exc).__name__}: {exc}"
            )
            continue
        cohort_results.append(es_result)

    # 2. Pivot per-horizon samples.
    ar_by_h, sar_by_h = _collect_per_horizon_samples(
        cohort_results, horizons_t,
    )

    # 3. Per-horizon bootstrap CI of mean AR.  We collect raw p-values
    # in a list aligned with ``horizons_t`` so the FDR step's outputs
    # can be matched back row-for-row.
    ci_by_h:  dict[int, dict[str, Any]] = {}
    p_values: list[Optional[float]] = []
    mean_ar_by_h:  dict[int, Optional[float]] = {}
    mean_sar_by_h: dict[int, Optional[float]] = {}
    for h in horizons_t:
        ar_samples  = ar_by_h[h]
        sar_samples = sar_by_h[h]
        try:
            ci = bootstrap_ar_ci(
                ar_samples,
                seed=seed,
                n_bootstrap=n_bootstrap,
            )
        except Exception as exc:  # noqa: BLE001 — operator log
            errors.append(
                f"horizon {h} bootstrap_ar_ci: "
                f"{type(exc).__name__}: {exc}"
            )
            ci = {"lower": None, "upper": None}
        ci_by_h[h] = ci

        mean_ar_by_h[h] = (
            sum(ar_samples) / len(ar_samples) if ar_samples else None
        )
        mean_sar_by_h[h] = (
            sum(sar_samples) / len(sar_samples) if sar_samples else None
        )
        p_values.append(_cohort_p_value(sar_samples))

    # 4. FDR adjustment over the per-horizon p-values.  ``bh_adjust``
    # accepts ``None`` entries and carries them through as ``None``.
    fdr_result = bh_adjust(p_values, alpha=alpha)
    fdr_qs = fdr_result.get("adjusted") or [None] * len(horizons_t)

    # 5. Compose schema records — one per horizon, in input order.
    records: list[dict[str, Any]] = []
    for i, h in enumerate(horizons_t):
        ci = ci_by_h[h]
        try:
            record = make_stat_validation_record(
                horizon=h,
                abnormal_return=mean_ar_by_h[h],
                sar=mean_sar_by_h[h],
                ci_low=ci.get("lower"),
                ci_high=ci.get("upper"),
                p_value=p_values[i],
                fdr_q=fdr_qs[i],
                alpha=alpha,
            )
        except Exception as exc:  # noqa: BLE001 — operator log
            errors.append(
                f"horizon {h} make_stat_validation_record: "
                f"{type(exc).__name__}: {exc}"
            )
            continue
        records.append(record)

    significant_count = sum(
        1 for r in records if r.get("statistically_significant")
    )

    payload: dict[str, Any] = {
        "ok":                 (not errors) and len(records) == len(horizons_t),
        "records_count":      len(records),
        "significant_count":  significant_count,
        "errors":             list(errors),
        "records":            records,
        "config": {
            "n_events":     int(n_events),
            "n_days":       int(n_days),
            "event_index":  int(event_index),
            "horizons":     list(horizons_t),
            "seed":         int(seed),
            "alpha":        float(alpha),
            "n_bootstrap":  int(n_bootstrap),
            "event_shock":  float(event_shock),
            "market_vol":   float(market_vol),
            "idio_vol":     float(idio_vol),
            "drift":        float(drift),
        },
    }
    return payload


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(payload: dict[str, Any]) -> str:
    lines: list[str] = ["=== stat_validation pipeline smoke ==="]
    lines.append(f"ok:                 {payload['ok']}")
    lines.append(f"records_count:      {payload['records_count']}")
    lines.append(f"significant_count:  {payload['significant_count']}")
    lines.append("")
    for record in payload.get("records", []):
        lines.append(f"  horizon h={record['horizon']:>3}")
        lines.append(
            f"      abnormal_return:           "
            f"{_fmt(record['abnormal_return'])}"
        )
        lines.append(
            f"      sar:                       {_fmt(record['sar'])}"
        )
        lines.append(
            f"      ci:                        "
            f"[{_fmt(record['ci_low'])}, {_fmt(record['ci_high'])}]"
        )
        lines.append(
            f"      p_value:                   {_fmt(record['p_value'])}"
        )
        lines.append(
            f"      fdr_q:                     {_fmt(record['fdr_q'])}"
        )
        lines.append(
            f"      statistically_significant: "
            f"{record['statistically_significant']}"
        )
        lines.append(
            f"      interpretation:            "
            f"{record['interpretation']}"
        )
    errors = payload.get("errors") or []
    lines.append("")
    if errors:
        lines.append(f"Errors ({len(errors)}):")
        for e in errors:
            lines.append(f"  - {e}")
    else:
        lines.append("Errors: (none)")
    return "\n".join(lines)


def _fmt(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only pipeline smoke over deterministic synthetic "
            "data: event_study → bootstrap CI → p-value → FDR → "
            "stat_validation.  Never touches the DB, a provider, "
            "yfinance, an LLM, or the FastAPI app."
        ),
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Emit structured JSON instead of the text summary.",
    )
    parser.add_argument(
        "--seed", type=int, default=_DEFAULT_SEED,
        help=f"Master RNG seed (default: {_DEFAULT_SEED}).",
    )
    parser.add_argument(
        "--n-events", type=int, default=_DEFAULT_N_EVENTS,
        dest="n_events",
        help=f"Synthetic cohort size (default: {_DEFAULT_N_EVENTS}).",
    )
    parser.add_argument(
        "--horizons", type=int, nargs="+", default=list(_DEFAULT_HORIZONS),
        help=(
            "Forward horizons to test (default: "
            f"{' '.join(str(h) for h in _DEFAULT_HORIZONS)})."
        ),
    )
    parser.add_argument(
        "--alpha", type=float, default=_DEFAULT_ALPHA_VALUE,
        help=f"Significance threshold (default: {_DEFAULT_ALPHA_VALUE}).",
    )
    parser.add_argument(
        "--n-bootstrap", type=int, default=_DEFAULT_BOOTSTRAP_N,
        dest="n_bootstrap",
        help=f"Bootstrap resample count (default: {_DEFAULT_BOOTSTRAP_N}).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    payload = run_smoke(
        n_events=args.n_events,
        horizons=tuple(args.horizons),
        seed=args.seed,
        alpha=args.alpha,
        n_bootstrap=args.n_bootstrap,
    )

    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True), file=output)
    else:
        print(_render_text(payload), file=output)

    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
