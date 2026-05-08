#!/usr/bin/env python3
"""scripts/stat_validation_demo_report.py

Synthetic statistical-validation demo report — interview / CV evidence.

The script wires the deterministic synthetic-data generator from
:mod:`scripts.stat_validation_smoke` to the canonical record composer
in :mod:`stats.validation_pipeline` and wraps the output with a
methodology summary and an interpretation summary an external reviewer
can read end-to-end.

What this script is
-------------------
* A read-only demo that runs the full statistical-validation pipeline
  against deterministic synthetic asset/benchmark data and prints a
  human- or machine-readable report.
* Conservative framing: the run is consistently labelled a
  ``synthetic smoke``.  The methodology and interpretation strings
  deliberately avoid market-edge / "proof" language.

What this script is NOT
-----------------------
* Not a backtest.  No real market data, no archive, no provider.
* Not a DB writer.  No ``sqlite3``, no ``yfinance``, no LLM, no
  FastAPI surface.
* Not a claim of edge.  The synthetic shock is engineered into the
  data; passing the FDR threshold here is an end-to-end pipeline
  smoke, not evidence of a profitable strategy.

Composition
-----------
1. :func:`scripts.stat_validation_smoke._make_synthetic_pair` produces
   a deterministic asset/benchmark price pair per synthetic event.
   Same seed → byte-equal arrays.
2. :func:`stats.event_study.compute_event_study` produces per-event
   AR / SAR at every requested horizon.
3. :func:`stats.validation_pipeline.run_validation_pipeline` aggregates
   the cohort per horizon, builds a percentile bootstrap CI of the
   mean AR, runs a two-sided z-test on the cross-sectional SAR, applies
   Benjamini-Hochberg FDR adjustment, and emits a list of canonical
   :mod:`stats.stat_validation` records.
4. The script wraps the records with a methodology / interpretation
   summary and a synthetic-config echo, then renders to JSON or text.

Usage::

    python scripts/stat_validation_demo_report.py
    python scripts/stat_validation_demo_report.py --json
    python scripts/stat_validation_demo_report.py --json --seed 7
    python scripts/stat_validation_demo_report.py --horizons 1 5 20
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ``_make_synthetic_pair`` is a private (underscore-prefixed) symbol in
# the smoke module but is the canonical synthetic-data generator for
# this codebase — reusing it here means the demo report and the smoke
# share a single generator and therefore stay byte-aligned at the data
# layer.
from scripts.stat_validation_smoke import _make_synthetic_pair  # noqa: E402
from stats.event_study             import compute_event_study   # noqa: E402
from stats.stat_validation         import DEFAULT_ALPHA          # noqa: E402
from stats.validation_pipeline     import run_validation_pipeline  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic configuration — defaults tuned to mirror
# ``scripts.stat_validation_smoke`` so the demo report and the smoke
# tell the same story when run with the same seed.
# ---------------------------------------------------------------------------


_DEFAULT_N_EVENTS:    int   = 12
_DEFAULT_N_DAYS:      int   = 200
_DEFAULT_EVENT_INDEX: int   = 120
_DEFAULT_HORIZONS:    tuple[int, ...] = (1, 5, 20)
_DEFAULT_SEED:        int   = 42
_DEFAULT_ALPHA_VALUE: float = DEFAULT_ALPHA
_DEFAULT_BOOTSTRAP_N: int   = 500
_DEFAULT_EVENT_SHOCK: float = 0.04
_DEFAULT_MARKET_VOL:  float = 0.010
_DEFAULT_IDIO_VOL:    float = 0.005
_DEFAULT_DRIFT:       float = 0.0001
_DEFAULT_MIN_SAMPLES: int   = 8


# ---------------------------------------------------------------------------
# Methodology / interpretation strings.
#
# Conservative framing per spec — "synthetic smoke", no "proof" or
# market-edge language.  The methodology is data-independent (same
# every run); the interpretation is data-dependent and rebuilt each
# call from the live records.
# ---------------------------------------------------------------------------


_METHODOLOGY_SUMMARY = (
    "This is a synthetic smoke of an end-to-end statistical-validation "
    "pipeline.  Pipeline composition: "
    "scripts.stat_validation_smoke._make_synthetic_pair generates a "
    "deterministic cohort of asset/benchmark price pairs (shared market "
    "factor + idiosyncratic noise + an embedded one-day positive shock "
    "on the day after the event close).  stats.event_study computes "
    "per-event abnormal return (AR) and standardized abnormal return "
    "(SAR) at each requested horizon.  stats.validation_pipeline "
    "aggregates the cohort per horizon, builds a percentile bootstrap "
    "confidence interval for the mean AR via stats.bootstrap_ci, runs a "
    "two-sided z-test on the cross-sectional SAR for a raw p-value, "
    "applies Benjamini-Hochberg FDR adjustment across horizons (q-value "
    "per row), and composes a stats.stat_validation record carrying the "
    "canonical nine fields plus a derived statistically_significant flag "
    "and an interpretation label.  The shock is engineered into the "
    "synthetic data; clearing the FDR threshold here is an "
    "end-to-end-smoke result, not a backtest and not a claim of edge."
)


def _build_interpretation_summary(
    *,
    records:           list[dict[str, Any]],
    significant_count: int,
    seed:              int,
    q_threshold:       float,
) -> str:
    """Compose a data-dependent summary that surfaces the live counts.

    The exact ``significant_count`` and ``records_count`` integers are
    embedded verbatim so a downstream reader sees the actual run, not
    a frozen string.  Per-horizon labels are suffixed for drill-in.
    """
    records_count = len(records)
    if records_count == 0:
        per_horizon_clause = ""
    else:
        labels = ", ".join(
            f"h={r['horizon']}: {r['interpretation']}"
            for r in records
        )
        per_horizon_clause = f"  Per-horizon labels: {labels}."
    return (
        f"Under this synthetic smoke (seed={seed}), "
        f"{significant_count} of {records_count} horizon(s) cleared "
        f"the Benjamini-Hochberg FDR threshold "
        f"(q <= {q_threshold:g}).{per_horizon_clause}  Synthetic data "
        f"only — no archive, no live market data, no provider call."
    )


# ---------------------------------------------------------------------------
# Cohort generation — deterministic under a fixed seed.
# ---------------------------------------------------------------------------


def _build_cohort_event_studies(
    *,
    n_events:     int,
    n_days:       int,
    event_index:  int,
    horizons:     Sequence[int],
    seed:         int,
    event_shock:  float,
    market_vol:   float,
    idio_vol:     float,
    drift:        float,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Generate a synthetic cohort and run ``compute_event_study`` on each.

    Returns ``(event_study_outputs, errors)``.  Per-event failures are
    collected in ``errors`` and the surviving outputs are returned —
    the demo never crashes mid-cohort.
    """
    horizons_t = tuple(int(h) for h in horizons)
    es_outputs: list[dict[str, Any]] = []
    errors:     list[str] = []
    for i in range(n_events):
        # Match the smoke's sub-seed scheme so an operator that runs
        # both surfaces with the same master seed sees the same
        # underlying synthetic prices.
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
        es_outputs.append(es_result)
    return es_outputs, errors


# ---------------------------------------------------------------------------
# Demo report builder
# ---------------------------------------------------------------------------


def build_demo_report(
    *,
    n_events:     int   = _DEFAULT_N_EVENTS,
    n_days:       int   = _DEFAULT_N_DAYS,
    event_index:  int   = _DEFAULT_EVENT_INDEX,
    horizons:     Sequence[int] = _DEFAULT_HORIZONS,
    seed:         int   = _DEFAULT_SEED,
    alpha:        float = _DEFAULT_ALPHA_VALUE,
    n_bootstrap:  int   = _DEFAULT_BOOTSTRAP_N,
    min_samples:  int   = _DEFAULT_MIN_SAMPLES,
    event_shock:  float = _DEFAULT_EVENT_SHOCK,
    market_vol:   float = _DEFAULT_MARKET_VOL,
    idio_vol:     float = _DEFAULT_IDIO_VOL,
    drift:        float = _DEFAULT_DRIFT,
) -> dict[str, Any]:
    """Run the full synthetic pipeline and return the demo report payload.

    Returns a dict carrying at least the five required keys
    (``records_count``, ``significant_count``, ``horizons``,
    ``methodology_summary``, ``interpretation_summary``) plus
    ``records`` for drill-in, ``config`` for reproducibility,
    ``errors`` for operator log, and ``ok`` matching pipeline success.
    """
    horizons_list = [int(h) for h in horizons]

    es_outputs, errors = _build_cohort_event_studies(
        n_events=n_events,
        n_days=n_days,
        event_index=event_index,
        horizons=horizons_list,
        seed=seed,
        event_shock=event_shock,
        market_vol=market_vol,
        idio_vol=idio_vol,
        drift=drift,
    )

    try:
        records = run_validation_pipeline(
            es_outputs,
            alpha=alpha,
            n_bootstrap=n_bootstrap,
            seed=seed,
            min_samples=min_samples,
        )
    except Exception as exc:  # noqa: BLE001 — operator log
        errors.append(
            f"validation_pipeline: {type(exc).__name__}: {exc}"
        )
        records = []

    significant_count = sum(
        1 for r in records if r.get("statistically_significant")
    )

    interpretation_summary = _build_interpretation_summary(
        records=records,
        significant_count=significant_count,
        seed=seed,
        q_threshold=float(alpha),
    )

    return {
        "ok":                     not errors,
        "records_count":          len(records),
        "significant_count":      significant_count,
        "horizons":               horizons_list,
        "methodology_summary":    _METHODOLOGY_SUMMARY,
        "interpretation_summary": interpretation_summary,
        "records":                records,
        "errors":                 list(errors),
        "config": {
            "n_events":    int(n_events),
            "n_days":      int(n_days),
            "event_index": int(event_index),
            "horizons":    list(horizons_list),
            "seed":        int(seed),
            "q_threshold": float(alpha),
            "n_bootstrap": int(n_bootstrap),
            "min_samples": int(min_samples),
            "event_shock": float(event_shock),
            "market_vol":  float(market_vol),
            "idio_vol":    float(idio_vol),
            "drift":       float(drift),
        },
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _wrap(text: str, *, width: int = 78, indent: str = "  ") -> str:
    """Soft-wrap a paragraph for the text mode rendering."""
    import textwrap
    return textwrap.fill(
        text, width=width,
        initial_indent=indent, subsequent_indent=indent,
    )


def _fmt_number(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["=== Statistical Validation Demo Report ==="]
    lines.append(f"ok:                {report['ok']}")
    lines.append(f"records_count:     {report['records_count']}")
    lines.append(f"significant_count: {report['significant_count']}")
    lines.append(f"horizons:          {report['horizons']}")
    lines.append("")

    lines.append("Methodology")
    lines.append("-----------")
    lines.append(_wrap(report["methodology_summary"]))
    lines.append("")

    lines.append("Records")
    lines.append("-------")
    if not report["records"]:
        lines.append("  (no records produced)")
    else:
        for r in report["records"]:
            lines.append(f"  h={r['horizon']:>3}")
            lines.append(
                f"      abnormal_return: "
                f"{_fmt_number(r['abnormal_return'])}"
            )
            lines.append(
                f"      sar:             {_fmt_number(r['sar'])}"
            )
            lines.append(
                f"      ci:              "
                f"[{_fmt_number(r['ci_low'])}, "
                f"{_fmt_number(r['ci_high'])}]"
            )
            lines.append(
                f"      p_value:         {_fmt_number(r['p_value'])}"
            )
            lines.append(
                f"      fdr_q:           {_fmt_number(r['fdr_q'])}"
            )
            lines.append(
                f"      significant:     "
                f"{r['statistically_significant']}"
            )
            lines.append(
                f"      interpretation:  {r['interpretation']}"
            )
    lines.append("")

    lines.append("Interpretation")
    lines.append("--------------")
    lines.append(_wrap(report["interpretation_summary"]))
    lines.append("")

    errors = report.get("errors") or []
    if errors:
        lines.append(f"Errors ({len(errors)}):")
        for e in errors:
            lines.append(f"  - {e}")
    else:
        lines.append("Errors: (none)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Synthetic statistical-validation demo report.  Wires "
            "scripts.stat_validation_smoke._make_synthetic_pair to "
            "stats.event_study and stats.validation_pipeline and "
            "renders a methodology + interpretation summary alongside "
            "the canonical stat_validation records.  Synthetic data "
            "only — no DB, no provider, no LLM, no UI."
        ),
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Emit structured JSON instead of the text rendering.",
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
    # Operator-facing flag uses ``--q-threshold`` to keep this CLI's
    # surface free of the word ``alpha``, matching the conservative
    # language rule the methodology / interpretation strings already
    # follow.  Internally we still pass the value as ``alpha`` to the
    # validation pipeline (which is how :mod:`stats.stat_validation`
    # and :mod:`stats.validation_pipeline` name the same parameter
    # everywhere else in the codebase).
    parser.add_argument(
        "--q-threshold", type=float, default=_DEFAULT_ALPHA_VALUE,
        dest="q_threshold",
        help=(
            "Significance threshold forwarded to the validation "
            f"pipeline (default: {_DEFAULT_ALPHA_VALUE})."
        ),
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

    report = build_demo_report(
        n_events=args.n_events,
        horizons=tuple(args.horizons),
        seed=args.seed,
        alpha=args.q_threshold,
        n_bootstrap=args.n_bootstrap,
    )

    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True), file=output)
    else:
        print(_render_text(report), file=output)

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
