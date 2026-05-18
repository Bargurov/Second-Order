#!/usr/bin/env python3
"""Placebo / negative-control smoke for the freeze-candidate cohort.

Tests whether the per-record abnormal-return signals recorded in
the tracked demo evidence bundle
(``demo_artifacts/section_c_v1/freeze_candidate_evidence.json``)
also appear at nearby non-event "placebo" dates.  The smoke reads
from the tracked demo bundle by default so a fresh clone produces
the same comparison without depending on the local untracked
``artifacts/`` directory; ``--evidence-path`` overrides the
default for callers that want to point at a different evidence
file.  The smoke is a **methodology probe**, not a research
claim: it reports how many (event_id, horizon) placebo draws land
in the raw-p-candidate and FDR-significant buckets, side by side
with the artifact's own counts, and surfaces every coverage gap
as a warning.

Reuse
-----

The script does not reinvent statistics.  Every numeric step is
funnelled through the existing ``stats/`` helpers:

* ``stats.event_study.compute_event_study``  — abnormal-return /
  SAR for each placebo (event_id, horizon, offset) draw.
* ``stats.p_values.p_value_from_sar``        — two-sided normal
  p-value, matching the convention used by the real-cohort
  validation pipeline (``erfc(|sar|/√2)``).
* ``stats.fdr.bh_adjust``                    — Benjamini-Hochberg
  adjustment, applied once across the full pool of placebo
  p-values.
* ``_classify_record``-equivalent logic       — raw-p-candidate vs
  FDR-significant uses the same rule as
  ``scripts/freeze_candidate_evidence_artifact.py``:
    - ``fdr_significant`` ↔ ``fdr_q ≤ alpha``;
    - ``raw_p_candidate``  ↔ ``p_value ≤ alpha`` AND NOT FDR-significant.

The real-cohort counts are **read directly from the artifact**, not
recomputed — the artifact is the system of record for those numbers.

Read-only contract
------------------

* No FastAPI surface, no ``routes.*``, no ``api`` import.
* No paid provider, no ``yfinance``, no ``market_data``, no
  ``market_check``.
* No LLM (``openai``, ``anthropic``).
* No mutation of events / archive / artifacts.  The default run
  writes nothing to disk; ``--output <path>`` is the only flag that
  produces a file.
* Live DB reads use ``sqlite3`` with the ``mode=ro`` URI param so a
  bad caller cannot accidentally mutate ``events.db``.
* Price reads go through ``price_cache.read_window_no_fetch`` —
  the strictly read-only cache path that never plans or executes a
  provider fetch.

Offset semantics
----------------

Placebo offsets are **calendar-day** offsets applied to the event
date.  The script requires an exact price bar at the offset date
for both the asset and the benchmark; offsets that land on a
non-trading day are skipped and counted in ``warnings``.  This is
the conservative rule (rule (a) in the runbook): no snapping, no
silent shifting.

Estimation-window contamination
-------------------------------

The default offsets are deliberately small (±5, ±10 calendar days
of the event).  At ±5 days the 60-day pre-event estimation window
used by ``compute_event_study`` *overlaps* with the real event day;
at ±10 days the 20-day forward horizon also straddles the real
event.  This means the placebo SAR distribution is **not** a clean
null — it is contaminated by the real event signal it is supposed
to compare against.  The script surfaces this prominently in
``warnings`` and ``comparison_notes`` so the reader cannot mistake
a small placebo / event signal gap for evidence of a clean null.

Coverage-aware fallback + estimation-window auto-shrink
-------------------------------------------------------

The local price cache often does not hold the full 60-day pre-event
window every event would need, and many calendar-day offsets land on
non-trading days.  The script handles this in two coverage-aware,
deterministic ways — both of which are surfaced explicitly, never
silently:

* **Auto-shrink (default on).** For each (event, offset) draw whose
  cached pre-history is shorter than the requested estimation window,
  the script reduces the window *for that draw* to the maximum that
  fits, capped at the requested window and floored at
  ``--min-estimation-window`` (default 5).  Every shrink is recorded
  in ``methodology_adjustments`` and a top-level warning announces
  that the placebo SAR scaling is not directly comparable to the
  freeze-candidate artifact's SAR scaling under a 60-day window.
  Operators who want the strict methodology can pass ``--no-shrink``
  and accept zero computable draws when coverage is insufficient.

* **Coverage-aware fallback offsets.** If *none* of the requested
  offsets produce a computable draw, the script enumerates the
  cached trading days within ±30 calendar days of each event_date
  and derives per-event offsets from that set deterministically.
  This is a coverage-aware second pass — never a methodology
  invention — and the offsets actually attempted are listed in
  ``placebo_offsets_used``.

Conservative wording
--------------------

The script reports counts.  It does not claim the cohort passed or
failed a placebo test, does not claim a result is causal, validated,
proven, or anything else stronger than "this many placebo draws
landed in this bucket".

Output contract (JSON)::

    {
      "ok":                       bool,
      "cohort_event_count":       int,
      "placebo_dates_tested":     int,
      "requested_placebo_draws":  int,
      "computable_placebo_draws": int,
      "skipped_placebo_draws":    int,
      "skip_reason_counts":             dict[str, int],
      "placebo_offsets_used":     list[int],
      "coverage_diagnostics": {
        "<event_id>": {
          "event_date":          str | None,
          "primary_ticker":      str,
          "benchmark":           str,
          "asset_first":         str | None,
          "asset_last":          str | None,
          "asset_bar_count":     int,
          "pre_event_bar_count": int,
        }, ...
      },
      "methodology_adjustments": list[str],
      "recommended_next_action": str | None,
      "event_signal_summary":    {…records / raw_p / fdr / by_horizon…},
      "placebo_signal_summary":  {…records / raw_p / fdr / by_horizon…},
      "comparison_notes":        list[str],
      "warnings":                list[str],
      "errors":                  list[str],
    }

Usage::

    python scripts/placebo_negative_control_smoke.py
    python scripts/placebo_negative_control_smoke.py --json
    python scripts/placebo_negative_control_smoke.py --json \\
        --offsets -10 -5 5 10
    python scripts/placebo_negative_control_smoke.py --json \\
        --output artifacts/placebo_negative_control_report.json
    python scripts/placebo_negative_control_smoke.py --json \\
        --input-csv examples/<batch>.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Pure stats imports — these never touch DB / provider / LLM.
from stats.event_study   import compute_event_study   # noqa: E402
from stats.fdr           import bh_adjust             # noqa: E402
from stats.p_values      import p_value_from_sar      # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_OFFSETS:                tuple[int, ...] = (-10, -5, 5, 10)
_DEFAULT_HORIZONS:               tuple[int, ...] = (1, 5, 20)
_DEFAULT_ALPHA:                  float           = 0.05
_DEFAULT_ESTIMATION_WINDOW:      int             = 60
_DEFAULT_MIN_ESTIMATION_WINDOW:  int             = 5
_DEFAULT_EVIDENCE_PATH:          str             = (
    "demo_artifacts/section_c_v1/freeze_candidate_evidence.json"
)
_DEFAULT_DB_PATH:                str             = "events.db"

# Read enough pre-history to cover the requested estimation window plus
# weekend padding.  Calendar-day window — the price cache returns
# only existing rows, so over-asking is harmless.
_PRE_DAYS_PAD:  int = 100
_POST_DAYS_PAD: int = 35     # ≥ max horizon (20 trading days) + weekend slack

# Coverage-aware fallback: enumerate cached trading days within this
# half-window (in calendar days) of each event_date.
_FALLBACK_HALF_WINDOW_DAYS: int = 30

# Skip-reason canonical names.  Kept in one place so the test suite
# can assert against a stable vocabulary.
_SKIP_UNCACHED_BAR:           str = "uncached_bar"
_SKIP_INSUFFICIENT_PRE_HIST:  str = "insufficient_pre_history"
_SKIP_COMPUTE_ERROR:          str = "compute_event_study_error"
_SKIP_NO_EVENT_DATE:          str = "no_event_date"
_SKIP_NO_PRICE_COVERAGE:      str = "no_price_coverage"

_CONTAMINATION_NOTE: str = (
    "Default placebo offsets (±5, ±10 calendar days) overlap with the "
    "real event's 60-day pre-event estimation window and 20-day forward "
    "horizon — the placebo distribution is not a clean null and any "
    "small placebo / event gap should not be read as evidence of "
    "specificity."
)

# Input-CSV mode (operator-curated batch).  When --input-csv is
# supplied the smoke bypasses the freeze-artifact + events.db read
# and drives both real-side and placebo-side computation from the
# CSV rows.  Required columns mirror the manual-five batch schema;
# ``predicted_direction`` is read when present and propagated as
# documentation only — directional gating is the cohort-integration
# rule's job (see docs/expansion_cohort_integration_rule.md), not
# this smoke's.
_CSV_REQUIRED_FIELDS: tuple[str, ...] = (
    "event_date", "primary_ticker", "benchmark_ticker",
)
_CSV_REAL_SIDE_NOTE: str = (
    "Input-CSV mode: real-side counts were computed in-session from "
    "the supplied CSV using the same event-study + p-value + BH-FDR "
    "primitives as the placebo side.  No precomputed validated "
    "artifact exists for this batch; treat both real and placebo "
    "counts as in-session probes, not as freeze-cohort evidence."
)


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------


def run_placebo_smoke(
    *,
    evidence_path:                 str | Path = _DEFAULT_EVIDENCE_PATH,
    db_path:                       str | Path = _DEFAULT_DB_PATH,
    input_csv:                     Optional[str | Path] = None,
    offsets:                       Sequence[int] = _DEFAULT_OFFSETS,
    horizons:                      Sequence[int] = _DEFAULT_HORIZONS,
    alpha:                         float        = _DEFAULT_ALPHA,
    estimation_window:             int          = _DEFAULT_ESTIMATION_WINDOW,
    min_estimation_window:         int          = _DEFAULT_MIN_ESTIMATION_WINDOW,
    auto_shrink_estimation_window: bool         = True,
    price_reader:                  Optional[Any] = None,
) -> dict[str, Any]:
    """Run the placebo smoke and return the report envelope.

    ``price_reader`` is an injectable seam.  When ``None`` (the
    default) the smoke imports ``price_cache.read_window_no_fetch``
    on demand and uses it.  Tests pass a fake reader to avoid the
    cache import and to drive a deterministic price series.

    ``estimation_window`` is the requested pre-event window for
    ``compute_event_study``.  When ``auto_shrink_estimation_window``
    is True (the default), the script reduces the window for any
    draw whose cached pre-history is shorter, capped at the requested
    window and floored at ``min_estimation_window``.  Every shrink
    is recorded in ``methodology_adjustments`` and a top-level
    warning announces the methodology change.
    """
    warnings: list[str] = []
    errors:   list[str] = []
    notes:    list[str] = []
    methodology_adjustments: list[str] = []

    offsets_t  = tuple(int(o) for o in offsets if int(o) != 0)
    horizons_t = tuple(int(h) for h in horizons if int(h) > 0)
    alpha_f    = float(alpha)
    est_window = max(1, int(estimation_window))
    min_window = max(1, int(min_estimation_window))
    if min_window > est_window:
        min_window = est_window
    auto_shrink = bool(auto_shrink_estimation_window)
    if not horizons_t:
        errors.append("no positive horizons supplied")
    if not offsets_t:
        errors.append("no non-zero offsets supplied")

    from_csv: bool = input_csv is not None

    if from_csv:
        # 1-3. Input-CSV mode: build specs + event_dates directly
        # from the operator-curated CSV.  No freeze-artifact read,
        # no events.db read.  Real-side counts are computed in-
        # session below (step 5a) using the same compute helpers
        # as the placebo side.
        event_specs, event_dates, csv_warnings = _build_specs_from_csv(
            Path(input_csv), errors=errors,
        )
        warnings.extend(csv_warnings)
        if errors:
            return _empty_envelope(
                warnings=warnings, errors=errors, notes=notes,
                requested_placebo_draws=0,
            )
        cohort_event_count = len(event_specs)
        if cohort_event_count == 0:
            warnings.append(
                "input CSV produced no usable (event_date, "
                "primary_ticker, benchmark_ticker) rows",
            )
        # Placeholder: populated by the in-session real-side compute
        # block below.  In CSV mode there is no precomputed artifact
        # to read trusted counts from.
        event_signal_summary: dict[str, Any] = _empty_summary()
    else:
        # 1. Read the freeze artifact.  Real-side counts come straight
        #    from the artifact — we do not recompute them.
        evidence = _read_evidence(Path(evidence_path), errors=errors)
        if evidence is None:
            return _empty_envelope(
                warnings=warnings, errors=errors, notes=notes,
                requested_placebo_draws=0,
            )

        event_signal_summary = _summarise_event_signals(
            evidence, horizons=horizons_t, alpha=alpha_f,
        )

        # 2. Build the per-event spec list (event_id, primary_ticker,
        #    benchmark, headline).  Skip records with missing tickers —
        #    we cannot draw a placebo without an asset / benchmark pair.
        event_specs, spec_warnings = _build_event_specs(evidence)
        warnings.extend(spec_warnings)
        cohort_event_count = len(event_specs)
        if cohort_event_count == 0:
            warnings.append(
                "no usable (event_id, primary_ticker, benchmark) tuples "
                "found in the evidence artifact",
            )

        # 3. Resolve event_id → event_date via read-only sqlite3.
        event_dates, date_warnings = _read_event_dates(
            db_path=Path(db_path),
            event_ids=[s["event_id"] for s in event_specs],
        )
        warnings.extend(date_warnings)

    # 4. Resolve a price reader (real or injected).
    if price_reader is None:
        price_reader = _default_price_reader(errors=errors)

    # 5. Discover per-event price coverage once.  This drives both
    #    the spec'd-offsets pass and any coverage-aware fallback.
    coverage_diagnostics, aligned_series = _discover_coverage(
        event_specs=event_specs,
        event_dates=event_dates,
        offsets_requested=offsets_t,
        price_reader=price_reader,
    )

    # 5a. CSV mode: real-side compute via the same _compute_placebo_records
    #     helper with per_event_offsets={eid: [0]} for each event so
    #     placebo_date == event_date and event_index lands on the real
    #     event-day bar.  The returned skip counter is intentionally
    #     discarded — skip_reason_counts is accounting-balanced against
    #     placebo-side draws; a real-side skip manifests as a smaller
    #     event_signal_summary.records_count instead.  Methodology
    #     adjustments DO accumulate into the global list because each
    #     entry already self-identifies via "event_id=X offset=+0".
    if from_csv and event_specs:
        real_records, _real_skip_unused, real_adj = _compute_placebo_records(
            event_specs=event_specs,
            event_dates=event_dates,
            offsets=None,
            horizons=horizons_t,
            aligned_series=aligned_series,
            estimation_window=est_window,
            min_estimation_window=min_window,
            auto_shrink=auto_shrink,
            per_event_offsets={
                int(s["event_id"]): [0] for s in event_specs
            },
        )
        methodology_adjustments.extend(real_adj)
        real_p_pool: list[Any] = [r["p_value"] for r in real_records]
        if real_p_pool:
            try:
                real_fdr_result = bh_adjust(real_p_pool, alpha=alpha_f)
                real_q = (
                    real_fdr_result.get("adjusted")
                    or [None] * len(real_p_pool)
                )
            except Exception as exc:  # noqa: BLE001 — operator-visible
                errors.append(
                    f"bh_adjust raised on real-side records: "
                    f"{type(exc).__name__}: {exc}",
                )
                real_q = [None] * len(real_p_pool)
            for rec, q in zip(real_records, real_q):
                rec["fdr_q"] = q
                is_fdr = isinstance(q, (int, float)) and q <= alpha_f
                is_rawp = (
                    (not is_fdr)
                    and isinstance(rec["p_value"], (int, float))
                    and rec["p_value"] <= alpha_f
                )
                rec["fdr_significant"] = bool(is_fdr)
                rec["raw_p_candidate"] = bool(is_rawp)
        event_signal_summary = _summarise_placebo_records(
            real_records, horizons=horizons_t,
        )
        warnings.append(_CSV_REAL_SIDE_NOTE)

    # 6. First pass: try the spec'd offsets.
    placebo_records, skip_counter_a, adj_a = _compute_placebo_records(
        event_specs=event_specs,
        event_dates=event_dates,
        offsets=offsets_t,
        horizons=horizons_t,
        aligned_series=aligned_series,
        estimation_window=est_window,
        min_estimation_window=min_window,
        auto_shrink=auto_shrink,
    )
    methodology_adjustments.extend(adj_a)
    skip_reason_counts:    dict[str, int] = dict(skip_counter_a)
    requested_draws_a = len(event_specs) * len(offsets_t)
    offsets_used:    list[int] = list(offsets_t)
    requested_total = requested_draws_a

    # 7. Coverage-aware fallback if nothing computed at the spec'd offsets.
    fallback_offsets_by_event: dict[int, list[int]] = {}
    if not placebo_records and offsets_t:
        fallback_offsets_by_event = _coverage_aware_fallback_offsets(
            event_specs=event_specs,
            event_dates=event_dates,
            aligned_series=aligned_series,
            half_window_days=_FALLBACK_HALF_WINDOW_DAYS,
            exclude_offsets=set(offsets_t),
        )
        if any(fallback_offsets_by_event.values()):
            placebo_records, skip_counter_b, adj_b = (
                _compute_placebo_records(
                    event_specs=event_specs,
                    event_dates=event_dates,
                    offsets=None,
                    per_event_offsets=fallback_offsets_by_event,
                    horizons=horizons_t,
                    aligned_series=aligned_series,
                    estimation_window=est_window,
                    min_estimation_window=min_window,
                    auto_shrink=auto_shrink,
                )
            )
            methodology_adjustments.extend(adj_b)
            for k, v in skip_counter_b.items():
                skip_reason_counts[k] = skip_reason_counts.get(k, 0) + v
            requested_total += sum(
                len(v) for v in fallback_offsets_by_event.values()
            )
            offsets_used = sorted({
                o for offs in fallback_offsets_by_event.values() for o in offs
            })
            notes.append(
                "Spec'd offsets produced no computable draws; the "
                "smoke fell back to deterministic offsets derived "
                "from cached trading days within "
                f"±{_FALLBACK_HALF_WINDOW_DAYS} calendar days of "
                "each event_date.",
            )

    placebo_dates_tested = len({
        (r["event_id"], r["offset"], r["placebo_date"])
        for r in placebo_records
    })

    # 8. Pool all placebo p-values into one BH-FDR adjustment.
    pooled_p: list[float | None] = [r["p_value"] for r in placebo_records]
    if pooled_p:
        try:
            fdr_result = bh_adjust(pooled_p, alpha=alpha_f)
            adjusted = fdr_result.get("adjusted") or [None] * len(pooled_p)
        except Exception as exc:  # noqa: BLE001 — operator-visible
            errors.append(
                f"bh_adjust raised {type(exc).__name__}: {exc}",
            )
            adjusted = [None] * len(pooled_p)
    else:
        adjusted = []

    for rec, q in zip(placebo_records, adjusted):
        rec["fdr_q"] = q
        is_fdr = isinstance(q, (int, float)) and q <= alpha_f
        is_rawp = (
            (not is_fdr)
            and isinstance(rec["p_value"], (int, float))
            and rec["p_value"] <= alpha_f
        )
        rec["fdr_significant"] = bool(is_fdr)
        rec["raw_p_candidate"] = bool(is_rawp)

    placebo_signal_summary = _summarise_placebo_records(
        placebo_records, horizons=horizons_t,
    )

    # 9. Build conservative comparison notes + warnings.
    notes.extend(_build_comparison_notes(
        event_summary=event_signal_summary,
        placebo_summary=placebo_signal_summary,
        horizons=horizons_t,
    ))
    if offsets_t and any(abs(o) <= 30 for o in offsets_t):
        warnings.append(_CONTAMINATION_NOTE)
    if methodology_adjustments:
        warnings.append(
            "Methodology adjustment: estimation window was reduced "
            f"from {est_window} for one or more placebo draws due to "
            "cache coverage.  Placebo SAR scaling is not directly "
            "comparable to the freeze-candidate artifact's signals; "
            "treat these counts as a coverage-limited probe, not a "
            "clean null-distribution comparison.  See "
            "methodology_adjustments for the per-draw record.",
        )

    # 10. Distinct (event, offset) pairs that produced ≥1 record.
    computable_draws = len({
        (r["event_id"], r["offset"]) for r in placebo_records
    })
    skipped_total = max(0, requested_total - computable_draws)

    # 11. Recommended next action when zero computable draws remain.
    recommended_next_action: Optional[str] = None
    if computable_draws == 0:
        if not auto_shrink:
            recommended_next_action = (
                "No placebo draws computable at "
                f"estimation_window={est_window} with --no-shrink.  "
                "Either rerun without --no-shrink (and accept a "
                "surfaced methodology adjustment), or expand the "
                "local price cache to cover the requested offsets."
            )
        else:
            recommended_next_action = (
                "No placebo draws computable.  Expand the local "
                "price cache so cached pre-history covers at least "
                f"{min_window} trading days before each placebo "
                "date.  Provider / yfinance fetches are out of "
                "scope for this smoke."
            )

    return {
        "ok":                       not errors,
        "cohort_event_count":       int(cohort_event_count),
        "placebo_dates_tested":     int(placebo_dates_tested),
        "requested_placebo_draws":  int(requested_total),
        "computable_placebo_draws": int(computable_draws),
        "skipped_placebo_draws":    int(skipped_total),
        "skip_reason_counts":             dict(skip_reason_counts),
        "placebo_offsets_used":     list(offsets_used),
        "coverage_diagnostics":     coverage_diagnostics,
        "methodology_adjustments":  list(methodology_adjustments),
        "recommended_next_action":  recommended_next_action,
        "event_signal_summary":     event_signal_summary,
        "placebo_signal_summary":   placebo_signal_summary,
        "comparison_notes":         notes,
        "warnings":                 warnings,
        "errors":                   errors,
    }


# ---------------------------------------------------------------------------
# Evidence reader
# ---------------------------------------------------------------------------


def _empty_envelope(
    *,
    warnings: list[str],
    errors:   list[str],
    notes:    list[str],
    requested_placebo_draws: int = 0,
) -> dict[str, Any]:
    return {
        "ok":                       False,
        "cohort_event_count":       0,
        "placebo_dates_tested":     0,
        "requested_placebo_draws":  int(requested_placebo_draws),
        "computable_placebo_draws": 0,
        "skipped_placebo_draws":    int(requested_placebo_draws),
        "skip_reason_counts":             {},
        "placebo_offsets_used":     [],
        "coverage_diagnostics":     {},
        "methodology_adjustments":  [],
        "recommended_next_action":  None,
        "event_signal_summary":     _empty_summary(),
        "placebo_signal_summary":   _empty_summary(),
        "comparison_notes":         notes,
        "warnings":                 warnings,
        "errors":                   errors,
    }


def _empty_summary() -> dict[str, Any]:
    return {
        "records_count":         0,
        "raw_p_candidate_count": 0,
        "fdr_significant_count": 0,
        "by_horizon":            {},
    }


def _read_evidence(
    path: Path, *, errors: list[str],
) -> Optional[Mapping[str, Any]]:
    if not path.is_file():
        errors.append(f"freeze-candidate evidence file not found: {path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(
            f"failed to read evidence file {path}: "
            f"{type(exc).__name__}: {exc}",
        )
        return None


def _build_specs_from_csv(
    path: Path, *, errors: list[str],
) -> tuple[list[dict[str, Any]], dict[int, str], list[str]]:
    """Build event_specs + event_dates from an operator-curated CSV.

    Returns ``(event_specs, event_dates, warnings)``.  Each spec
    carries the same shape as :func:`_build_event_specs`'s artifact-
    sourced output (``event_id``, ``primary_ticker``, ``benchmark``,
    ``headline``, ``mechanism_family``) plus an optional
    ``predicted_direction`` field propagated from the CSV when
    present.  ``event_id`` is the 1-indexed CSV row number — a
    synthetic id that is unique within the batch and never collides
    with real ``events.db`` ids because the CSV path skips the DB
    read entirely.

    Required columns: ``event_date``, ``primary_ticker``,
    ``benchmark_ticker``.  Missing file and missing required column
    are fatal (appended to ``errors``).  Per-row issues (empty
    event_date, malformed event_date, empty ticker) are surfaced as
    warnings with skip counts so the operator can see exactly how
    many rows did not survive ingestion.

    The ``predicted_direction`` column is read when present and
    propagated as documentation only — this smoke does not gate on
    directional priors.  Direction-gating belongs to the cohort-
    integration rule (see G3 in
    ``docs/expansion_cohort_integration_rule.md``).
    """
    import csv as _csv          # noqa: PLC0415 — narrow top-level surface
    warnings: list[str] = []
    if not path.is_file():
        errors.append(f"input CSV not found: {path}")
        return [], {}, warnings
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(
            f"failed to read input CSV {path}: "
            f"{type(exc).__name__}: {exc}",
        )
        return [], {}, warnings
    reader = _csv.DictReader(text.splitlines())
    header = reader.fieldnames or []
    missing_fields = [f for f in _CSV_REQUIRED_FIELDS if f not in header]
    if missing_fields:
        errors.append(
            f"input CSV missing required column(s): "
            f"{', '.join(missing_fields)}",
        )
        return [], {}, warnings

    event_specs: list[dict[str, Any]] = []
    event_dates: dict[int, str] = {}
    skipped_no_date:      int = 0
    skipped_bad_date:     int = 0
    skipped_no_primary:   int = 0
    skipped_no_benchmark: int = 0
    for idx, raw in enumerate(reader, start=1):
        event_date = (raw.get("event_date") or "").strip()
        primary    = (raw.get("primary_ticker") or "").strip().upper()
        benchmark  = (raw.get("benchmark_ticker") or "").strip().upper()
        predicted  = (raw.get("predicted_direction") or "").strip().lower()
        if not event_date:
            skipped_no_date += 1
            continue
        try:
            date.fromisoformat(event_date[:10])
        except ValueError:
            skipped_bad_date += 1
            continue
        if not primary:
            skipped_no_primary += 1
            continue
        if not benchmark:
            skipped_no_benchmark += 1
            continue
        eid = int(idx)
        event_specs.append({
            "event_id":            eid,
            "primary_ticker":      primary,
            "benchmark":           benchmark,
            "headline":            (raw.get("headline") or "").strip(),
            "mechanism_family":    (raw.get("mechanism_family") or "").strip(),
            "predicted_direction": predicted or None,
        })
        event_dates[eid] = event_date[:10]
    if skipped_no_date:
        warnings.append(
            f"input CSV: skipped {skipped_no_date} row(s) with no event_date",
        )
    if skipped_bad_date:
        warnings.append(
            f"input CSV: skipped {skipped_bad_date} row(s) with "
            "malformed event_date",
        )
    if skipped_no_primary:
        warnings.append(
            f"input CSV: skipped {skipped_no_primary} row(s) with "
            "no primary_ticker",
        )
    if skipped_no_benchmark:
        warnings.append(
            f"input CSV: skipped {skipped_no_benchmark} row(s) with "
            "no benchmark_ticker",
        )
    return event_specs, event_dates, warnings


# ---------------------------------------------------------------------------
# Real-cohort summary — read directly from the artifact
# ---------------------------------------------------------------------------


def _summarise_event_signals(
    evidence: Mapping[str, Any],
    *,
    horizons: Sequence[int],
    alpha: float,
) -> dict[str, Any]:
    """Build the event-side summary from the artifact's own records.

    We trust the artifact's ``raw_p_candidate`` / ``fdr_significant``
    booleans rather than recomputing — the artifact is the system of
    record.  We filter to the requested horizons so the summary lines
    up with the placebo summary's horizon set.
    """
    records = evidence.get("records") or []
    horizons_set = {int(h) for h in horizons}

    rec_count = rawp = fdrs = 0
    by_h: dict[int, dict[str, int]] = {
        int(h): {
            "records_count":         0,
            "raw_p_candidate_count": 0,
            "fdr_significant_count": 0,
        }
        for h in horizons_set
    }
    for rec in records:
        h = rec.get("horizon")
        try:
            h_int = int(h)
        except (TypeError, ValueError):
            continue
        if h_int not in horizons_set:
            continue
        rec_count += 1
        by_h[h_int]["records_count"] += 1
        if bool(rec.get("fdr_significant")):
            fdrs += 1
            by_h[h_int]["fdr_significant_count"] += 1
        if bool(rec.get("raw_p_candidate")):
            rawp += 1
            by_h[h_int]["raw_p_candidate_count"] += 1

    return {
        "records_count":         int(rec_count),
        "raw_p_candidate_count": int(rawp),
        "fdr_significant_count": int(fdrs),
        "by_horizon": {
            str(h): by_h[h] for h in sorted(by_h)
        },
    }


# ---------------------------------------------------------------------------
# Event spec extraction
# ---------------------------------------------------------------------------


def _build_event_specs(
    evidence: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return one spec per distinct ``event_id`` in the artifact.

    Each spec carries ``event_id`` / ``primary_ticker`` / ``benchmark``
    so the placebo loop can read the same (asset, benchmark) pair the
    artifact already evaluated.  Records missing either ticker are
    dropped with a warning — we cannot draw a placebo on a row whose
    primary ticker is None.
    """
    warnings: list[str] = []
    by_event: dict[int, dict[str, Any]] = {}
    skipped_no_ticker:    set[int] = set()
    skipped_no_benchmark: set[int] = set()
    for rec in evidence.get("records") or []:
        try:
            eid = int(rec.get("event_id"))
        except (TypeError, ValueError):
            continue
        if eid in by_event:
            continue
        primary = rec.get("primary_ticker")
        bench   = rec.get("benchmark")
        if not (isinstance(primary, str) and primary.strip()):
            skipped_no_ticker.add(eid)
            continue
        if not (isinstance(bench, str) and bench.strip()):
            skipped_no_benchmark.add(eid)
            continue
        by_event[eid] = {
            "event_id":        eid,
            "primary_ticker":  primary.strip().upper(),
            "benchmark":       bench.strip().upper(),
            "headline":        str(rec.get("headline") or ""),
            "mechanism_family": str(rec.get("mechanism_family") or ""),
        }
    if skipped_no_ticker:
        warnings.append(
            f"skipped {len(skipped_no_ticker)} event_id(s) with no "
            f"primary_ticker",
        )
    if skipped_no_benchmark:
        warnings.append(
            f"skipped {len(skipped_no_benchmark)} event_id(s) with no "
            f"benchmark",
        )
    return list(by_event.values()), warnings


# ---------------------------------------------------------------------------
# Event-date lookup — read-only sqlite3 URI
# ---------------------------------------------------------------------------


def _read_event_dates(
    *,
    db_path:   Path,
    event_ids: Sequence[int],
) -> tuple[dict[int, str], list[str]]:
    """Return ``{event_id: 'YYYY-MM-DD'}`` for events with a date.

    The DB is opened in read-only mode via the ``mode=ro`` URI param;
    a bad caller cannot accidentally write.  Missing event_ids and
    NULL dates are reported as warnings.
    """
    warnings: list[str] = []
    out: dict[int, str] = {}
    if not event_ids:
        return out, warnings
    if not db_path.is_file():
        warnings.append(
            f"events DB not found at {db_path}; placebo draws skipped",
        )
        return out, warnings
    # Open and close explicitly — ``with sqlite3.connect(...)`` does
    # not close the connection on exit (it only commits / rolls back),
    # and Windows refuses to unlink a DB file with an open handle.
    conn: Optional[sqlite3.Connection] = None
    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        placeholders = ",".join("?" * len(event_ids))
        rows = conn.execute(
            f"SELECT id, event_date FROM events "
            f"WHERE id IN ({placeholders})",
            list(event_ids),
        ).fetchall()
    except sqlite3.Error as exc:
        warnings.append(
            f"sqlite3 read failed on {db_path}: "
            f"{type(exc).__name__}: {exc}",
        )
        return out, warnings
    finally:
        if conn is not None:
            conn.close()

    have: set[int] = set()
    for eid, ed in rows:
        try:
            eid_i = int(eid)
        except (TypeError, ValueError):
            continue
        have.add(eid_i)
        if isinstance(ed, str) and ed.strip():
            try:
                date.fromisoformat(ed[:10])
            except ValueError:
                warnings.append(
                    f"event_id={eid_i}: unparseable event_date {ed!r}",
                )
                continue
            out[eid_i] = ed[:10]
    missing = [e for e in event_ids if e not in have]
    if missing:
        warnings.append(
            f"events DB missing {len(missing)} of {len(event_ids)} "
            f"requested event_id(s)",
        )
    null_dates = [e for e in event_ids if e in have and e not in out]
    if null_dates:
        warnings.append(
            f"{len(null_dates)} event_id(s) have NULL event_date",
        )
    return out, warnings


# ---------------------------------------------------------------------------
# Price reader — lazy import keeps the smoke importable without the cache
# ---------------------------------------------------------------------------


def _default_price_reader(*, errors: list[str]):
    """Return a callable ``(ticker, start, end) -> (dates, closes)``.

    Wraps ``price_cache.read_window_no_fetch`` so the rest of the
    pipeline does not depend on pandas in its signature.  When the
    cache module cannot be imported, the returned callable always
    yields ``([], [])`` and the per-event loop will surface the gap
    as a warning.
    """
    try:
        from price_cache import read_window_no_fetch  # noqa: WPS433
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
        dates: list[str] = []
        for ts in df.index:
            try:
                dates.append(str(ts.date()))  # pandas Timestamp
            except AttributeError:
                dates.append(str(ts)[:10])
        closes = [float(v) for v in df["Close"].tolist()]
        return dates, closes
    return _read


# ---------------------------------------------------------------------------
# Per-event placebo compute
# ---------------------------------------------------------------------------


def _discover_coverage(
    *,
    event_specs:       Sequence[Mapping[str, Any]],
    event_dates:       Mapping[int, str],
    offsets_requested: Sequence[int],
    price_reader:      Any,
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    """Read prices once per event and report per-event coverage.

    Returns ``(coverage_diagnostics, aligned_series)`` where:

    * ``coverage_diagnostics`` is the JSON-friendly per-event dict
      surfaced in the output envelope (string-keyed).
    * ``aligned_series`` is the in-memory cache keyed by ``event_id``
      that downstream passes use to look up bars and compute SARs
      without re-reading.
    """
    diagnostics: dict[str, Any] = {}
    aligned: dict[int, dict[str, Any]] = {}
    if offsets_requested:
        min_off = min(offsets_requested)
        max_off = max(offsets_requested)
    else:
        min_off = max_off = 0
    pad_min = min(min_off, -_FALLBACK_HALF_WINDOW_DAYS)
    pad_max = max(max_off, _FALLBACK_HALF_WINDOW_DAYS)

    for spec in event_specs:
        eid = int(spec["event_id"])
        primary = spec["primary_ticker"]
        bench   = spec["benchmark"]
        entry: dict[str, Any] = {
            "event_date":          event_dates.get(eid),
            "primary_ticker":      primary,
            "benchmark":           bench,
            "asset_first":         None,
            "asset_last":          None,
            "asset_bar_count":     0,
            "pre_event_bar_count": 0,
        }
        diagnostics[str(eid)] = entry
        if eid not in event_dates:
            continue
        ev_date = date.fromisoformat(event_dates[eid])
        win_start = (ev_date + timedelta(days=pad_min)
                     - timedelta(days=_PRE_DAYS_PAD)).isoformat()
        win_end   = (ev_date + timedelta(days=pad_max)
                     + timedelta(days=_POST_DAYS_PAD)).isoformat()
        asset_dates, asset_closes = price_reader(primary, win_start, win_end)
        bench_dates, bench_closes = price_reader(bench,   win_start, win_end)
        if not asset_closes or not bench_closes:
            continue
        asset_map = dict(zip(asset_dates, asset_closes))
        bench_map = dict(zip(bench_dates, bench_closes))
        common = sorted(set(asset_map) & set(bench_map))
        if not common:
            continue
        entry["asset_first"]     = common[0]
        entry["asset_last"]      = common[-1]
        entry["asset_bar_count"] = len(common)
        ev_iso = ev_date.isoformat()
        pre = sum(1 for d in common if d < ev_iso)
        entry["pre_event_bar_count"] = int(pre)
        aligned[eid] = {
            "ev_date":       ev_date,
            "common":        common,
            "asset_closes":  [asset_map[d] for d in common],
            "bench_closes":  [bench_map[d] for d in common],
            "date_to_index": {d: i for i, d in enumerate(common)},
        }
    return diagnostics, aligned


def _coverage_aware_fallback_offsets(
    *,
    event_specs:      Sequence[Mapping[str, Any]],
    event_dates:      Mapping[int, str],
    aligned_series:   Mapping[int, Mapping[str, Any]],
    half_window_days: int,
    exclude_offsets:  set[int],
) -> dict[int, list[int]]:
    """Per-event fallback offsets derived from cached trading days.

    For each event with a cached aligned series, enumerate the
    cached trading days within ``±half_window_days`` calendar days of
    the event_date, then compute the offset (in calendar days) for
    each.  Offsets that exactly match an already-attempted offset are
    excluded so the fallback never re-runs a known-bad attempt.
    """
    out: dict[int, list[int]] = {}
    for spec in event_specs:
        eid = int(spec["event_id"])
        bundle = aligned_series.get(eid)
        if bundle is None:
            continue
        ev_date: date = bundle["ev_date"]
        offsets_for_event: list[int] = []
        for d_iso in bundle["common"]:
            d = date.fromisoformat(d_iso)
            offset = (d - ev_date).days
            if offset == 0:
                continue
            if abs(offset) > half_window_days:
                continue
            if offset in exclude_offsets:
                continue
            offsets_for_event.append(int(offset))
        # Deterministic, deduplicated, ordered.
        offsets_for_event = sorted(set(offsets_for_event))
        if offsets_for_event:
            out[eid] = offsets_for_event
    return out


def _compute_placebo_records(
    *,
    event_specs:           Sequence[Mapping[str, Any]],
    event_dates:           Mapping[int, str],
    offsets:               Optional[Sequence[int]],
    horizons:              Sequence[int],
    aligned_series:        Mapping[int, Mapping[str, Any]],
    estimation_window:     int,
    min_estimation_window: int,
    auto_shrink:           bool,
    per_event_offsets:     Optional[Mapping[int, Sequence[int]]] = None,
) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    """Compute one SAR-record per (event, offset, horizon) draw.

    Returns ``(records, skip_counter, methodology_adjustments)``.
    Each skip increments a canonical bucket in ``skip_counter`` so
    the caller can surface a structured ``skip_reason_counts`` map.  The
    ``methodology_adjustments`` list carries one entry per draw whose
    estimation window had to be shrunk to fit cached pre-history.
    """
    records:  list[dict[str, Any]] = []
    skip_counter: dict[str, int] = {}
    adjustments:  list[str] = []

    def _bump(reason: str) -> None:
        skip_counter[reason] = skip_counter.get(reason, 0) + 1

    for spec in event_specs:
        eid = int(spec["event_id"])
        if eid not in event_dates:
            # One skip per requested offset for this event so the
            # accounting balances against requested_placebo_draws.
            offs = _offsets_for(spec, offsets, per_event_offsets)
            for _ in offs:
                _bump(_SKIP_NO_EVENT_DATE)
            continue
        bundle = aligned_series.get(eid)
        offs = _offsets_for(spec, offsets, per_event_offsets)
        if bundle is None:
            for _ in offs:
                _bump(_SKIP_NO_PRICE_COVERAGE)
            continue
        ev_date: date = bundle["ev_date"]
        primary = spec["primary_ticker"]
        bench   = spec["benchmark"]
        aligned_asset = bundle["asset_closes"]
        aligned_bench = bundle["bench_closes"]
        date_to_index = bundle["date_to_index"]

        for offset in offs:
            placebo_date = (
                ev_date + timedelta(days=int(offset))
            ).isoformat()
            if placebo_date not in date_to_index:
                _bump(_SKIP_UNCACHED_BAR)
                continue
            event_index = int(date_to_index[placebo_date])
            # event_index == 0 means no pre-history.  compute_event_study
            # requires event_index >= estimation_window.
            if auto_shrink:
                effective = min(estimation_window, event_index)
            else:
                effective = estimation_window
            if effective < min_estimation_window:
                _bump(_SKIP_INSUFFICIENT_PRE_HIST)
                continue
            if effective < estimation_window:
                adjustments.append(
                    f"event_id={eid} offset={offset:+d} placebo_date="
                    f"{placebo_date}: estimation_window reduced from "
                    f"{estimation_window} to {effective} (cached "
                    f"pre-history = {event_index} bars)",
                )
            try:
                es = compute_event_study(
                    asset_prices=aligned_asset,
                    benchmark_prices=aligned_bench,
                    event_index=event_index,
                    horizons=tuple(horizons),
                    estimation_window=effective,
                )
            except Exception as exc:  # noqa: BLE001
                _bump(_SKIP_COMPUTE_ERROR)
                adjustments.append(
                    f"event_id={eid} offset={offset:+d}: "
                    f"compute_event_study raised "
                    f"{type(exc).__name__}: {exc}",
                )
                continue
            if not es.get("available"):
                _bump(_SKIP_INSUFFICIENT_PRE_HIST)
                continue
            per_h = es.get("horizons") or {}
            for h in horizons:
                row = per_h.get(int(h)) or {}
                sar = row.get("sar")
                ar  = row.get("abnormal_return")
                p   = p_value_from_sar(sar, alternative="two-sided")
                records.append({
                    "event_id":           eid,
                    "offset":             int(offset),
                    "placebo_date":       placebo_date,
                    "horizon":            int(h),
                    "primary_ticker":     primary,
                    "benchmark":          bench,
                    "abnormal_return":    _safe_float(ar),
                    "sar":                _safe_float(sar),
                    "p_value":            _safe_float(p),
                    "estimation_window_used": int(effective),
                    "fdr_q":              None,
                    "raw_p_candidate":    False,
                    "fdr_significant":    False,
                })

    return records, skip_counter, adjustments


def _offsets_for(
    spec:              Mapping[str, Any],
    offsets:           Optional[Sequence[int]],
    per_event_offsets: Optional[Mapping[int, Sequence[int]]],
) -> Sequence[int]:
    """Resolve the offset list for one event spec.

    The compute helper supports two modes: a single ``offsets`` tuple
    applied to every event (the spec'd-offsets pass), or a per-event
    map (the coverage-aware fallback).  Exactly one of the two must
    be supplied.
    """
    if per_event_offsets is not None:
        return list(per_event_offsets.get(int(spec["event_id"]), ()))
    return list(offsets or ())


def _safe_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v


# ---------------------------------------------------------------------------
# Placebo summary
# ---------------------------------------------------------------------------


def _summarise_placebo_records(
    records: Iterable[Mapping[str, Any]],
    *,
    horizons: Sequence[int],
) -> dict[str, Any]:
    horizons_set = {int(h) for h in horizons}
    rec_count = rawp = fdrs = 0
    by_h: dict[int, dict[str, int]] = {
        int(h): {
            "records_count":         0,
            "raw_p_candidate_count": 0,
            "fdr_significant_count": 0,
        }
        for h in horizons_set
    }
    for rec in records:
        h = int(rec.get("horizon", -1))
        if h not in horizons_set:
            continue
        rec_count += 1
        by_h[h]["records_count"] += 1
        if rec.get("fdr_significant"):
            fdrs += 1
            by_h[h]["fdr_significant_count"] += 1
        if rec.get("raw_p_candidate"):
            rawp += 1
            by_h[h]["raw_p_candidate_count"] += 1
    return {
        "records_count":         int(rec_count),
        "raw_p_candidate_count": int(rawp),
        "fdr_significant_count": int(fdrs),
        "by_horizon": {
            str(h): by_h[h] for h in sorted(by_h)
        },
    }


# ---------------------------------------------------------------------------
# Conservative comparison wording
# ---------------------------------------------------------------------------


def _build_comparison_notes(
    *,
    event_summary:   Mapping[str, Any],
    placebo_summary: Mapping[str, Any],
    horizons:        Sequence[int],
) -> list[str]:
    notes: list[str] = []
    notes.append(
        f"Real-cohort record count: {event_summary['records_count']}; "
        f"placebo record count: {placebo_summary['records_count']}.",
    )
    notes.append(
        f"Raw-p candidates — real: "
        f"{event_summary['raw_p_candidate_count']}; placebo: "
        f"{placebo_summary['raw_p_candidate_count']}.  Raw-p and FDR "
        f"are separate measures; a raw-p candidate is not "
        f"FDR-significant.",
    )
    notes.append(
        f"FDR-significant — real: "
        f"{event_summary['fdr_significant_count']}; placebo: "
        f"{placebo_summary['fdr_significant_count']}.",
    )
    for h in sorted({int(x) for x in horizons}):
        ev = (event_summary.get("by_horizon") or {}).get(str(h)) or {}
        pl = (placebo_summary.get("by_horizon") or {}).get(str(h)) or {}
        notes.append(
            f"h={h}: real raw_p={ev.get('raw_p_candidate_count', 0)} / "
            f"fdr={ev.get('fdr_significant_count', 0)} of "
            f"{ev.get('records_count', 0)}; placebo raw_p="
            f"{pl.get('raw_p_candidate_count', 0)} / fdr="
            f"{pl.get('fdr_significant_count', 0)} of "
            f"{pl.get('records_count', 0)}.",
        )
    notes.append(
        "These are reported counts at fixed calendar-day offsets; "
        "they are not a pass / fail verdict on the cohort.",
    )
    return notes


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


def _render_text(payload: Mapping[str, Any]) -> str:
    lines: list[str] = ["=== placebo / negative-control smoke ==="]
    lines.append(f"ok:                       {payload['ok']}")
    lines.append(f"cohort_event_count:       {payload['cohort_event_count']}")
    lines.append(f"placebo_dates_tested:     {payload['placebo_dates_tested']}")
    lines.append(
        f"requested_placebo_draws:  {payload['requested_placebo_draws']}",
    )
    lines.append(
        f"computable_placebo_draws: {payload['computable_placebo_draws']}",
    )
    lines.append(
        f"skipped_placebo_draws:    {payload['skipped_placebo_draws']}",
    )
    sr = payload.get("skip_reason_counts") or {}
    if sr:
        lines.append("skip_reason_counts:")
        for k in sorted(sr):
            lines.append(f"  - {k}: {sr[k]}")
    used = payload.get("placebo_offsets_used") or []
    if used:
        lines.append(
            f"placebo_offsets_used:     {', '.join(str(o) for o in used)}",
        )
    next_action = payload.get("recommended_next_action")
    if next_action:
        lines.append("")
        lines.append("recommended_next_action:")
        lines.append(f"  {next_action}")
    lines.append("")
    lines.append("event_signal_summary:")
    _dump_summary(lines, payload.get("event_signal_summary") or {})
    lines.append("")
    lines.append("placebo_signal_summary:")
    _dump_summary(lines, payload.get("placebo_signal_summary") or {})
    adjustments = payload.get("methodology_adjustments") or []
    if adjustments:
        lines.append("")
        lines.append(f"methodology_adjustments ({len(adjustments)}):")
        for a in adjustments[:25]:
            lines.append(f"  - {a}")
        if len(adjustments) > 25:
            lines.append(f"  ... ({len(adjustments) - 25} more)")
    notes = payload.get("comparison_notes") or []
    if notes:
        lines.append("")
        lines.append("comparison_notes:")
        for n in notes:
            lines.append(f"  - {n}")
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


def _dump_summary(lines: list[str], summary: Mapping[str, Any]) -> None:
    lines.append(
        f"  records_count:         {summary.get('records_count', 0)}",
    )
    lines.append(
        f"  raw_p_candidate_count: {summary.get('raw_p_candidate_count', 0)}",
    )
    lines.append(
        f"  fdr_significant_count: {summary.get('fdr_significant_count', 0)}",
    )
    by_h = summary.get("by_horizon") or {}
    if by_h:
        lines.append("  by_horizon:")
        for h in sorted(by_h, key=lambda s: int(s)):
            row = by_h[h]
            lines.append(
                f"    h={h:>3}: records={row.get('records_count', 0)} "
                f"raw_p={row.get('raw_p_candidate_count', 0)} "
                f"fdr={row.get('fdr_significant_count', 0)}",
            )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Placebo / negative-control smoke for the freeze-candidate "
            "cohort.  Read-only against the live DB and price cache; "
            "writes nothing to disk unless --output is supplied.  "
            "Reports counts only — does not claim the cohort passed "
            "or failed a placebo test."
        ),
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Emit structured JSON instead of the text summary.",
    )
    parser.add_argument(
        "--evidence-path", default=_DEFAULT_EVIDENCE_PATH,
        dest="evidence_path",
        help=(
            "Freeze-candidate evidence artifact "
            f"(default: {_DEFAULT_EVIDENCE_PATH})."
        ),
    )
    parser.add_argument(
        "--db-path", default=_DEFAULT_DB_PATH, dest="db_path",
        help=(
            "events.db path opened in read-only mode "
            f"(default: {_DEFAULT_DB_PATH})."
        ),
    )
    parser.add_argument(
        "--input-csv", default=None, dest="input_csv",
        help=(
            "Operator-curated CSV with rows "
            "(event_date, primary_ticker, benchmark_ticker[, "
            "predicted_direction]).  When supplied, the smoke "
            "bypasses --evidence-path and --db-path entirely and "
            "computes real-side counts in-session from the CSV "
            "using the same event-study + p-value + BH-FDR "
            "primitives as the placebo side.  Default: read the "
            "freeze-candidate evidence artifact."
        ),
    )
    parser.add_argument(
        "--offsets", type=int, nargs="+", default=list(_DEFAULT_OFFSETS),
        help=(
            "Calendar-day offsets relative to event_date "
            f"(default: {' '.join(str(o) for o in _DEFAULT_OFFSETS)})."
        ),
    )
    parser.add_argument(
        "--horizons", type=int, nargs="+", default=list(_DEFAULT_HORIZONS),
        help=(
            "Forward horizons in trading days "
            f"(default: {' '.join(str(h) for h in _DEFAULT_HORIZONS)})."
        ),
    )
    parser.add_argument(
        "--alpha", type=float, default=_DEFAULT_ALPHA,
        help=f"Significance threshold (default: {_DEFAULT_ALPHA}).",
    )
    parser.add_argument(
        "--estimation-window", type=int,
        default=_DEFAULT_ESTIMATION_WINDOW,
        dest="estimation_window",
        help=(
            "Requested pre-event estimation window in trading days "
            f"(default: {_DEFAULT_ESTIMATION_WINDOW})."
        ),
    )
    parser.add_argument(
        "--min-estimation-window", type=int,
        default=_DEFAULT_MIN_ESTIMATION_WINDOW,
        dest="min_estimation_window",
        help=(
            "Floor for the auto-shrunk estimation window; draws "
            "with cached pre-history shorter than this are skipped "
            f"(default: {_DEFAULT_MIN_ESTIMATION_WINDOW})."
        ),
    )
    parser.add_argument(
        "--no-shrink", action="store_true", dest="no_shrink",
        help=(
            "Disable per-draw estimation-window auto-shrink.  Draws "
            "with cached pre-history shorter than --estimation-window "
            "are skipped instead of being computed under a reduced "
            "window."
        ),
    )
    parser.add_argument(
        "--output", default=None, dest="output_path",
        help=(
            "Optional path to write the JSON report.  Default writes "
            "nothing to disk."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(
    argv: Optional[Sequence[str]] = None, *, out: Any = None,
) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    payload = run_placebo_smoke(
        evidence_path=args.evidence_path,
        db_path=args.db_path,
        input_csv=args.input_csv,
        offsets=tuple(args.offsets),
        horizons=tuple(args.horizons),
        alpha=float(args.alpha),
        estimation_window=int(args.estimation_window),
        min_estimation_window=int(args.min_estimation_window),
        auto_shrink_estimation_window=not bool(args.no_shrink),
    )
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
    "run_placebo_smoke",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
