#!/usr/bin/env python3
"""Read-only archive statistical-readiness coverage report.

Walks the events archive once and answers, per event, "could the
event-study engine in :mod:`stats.event_study` actually produce a
record for this row given what the price cache currently has?"

Denominator lenses (AT1)
------------------------
The report runs under one of two explicit denominator lenses:

  * ``accepted`` (default) — the canonical hygiene-aware accepted-corpus
    analysis / coverage denominator.  Excludes every
    ``db.NON_ANALYSIS_STAGES`` row (``curated_intake`` stubs,
    ``z1a_candidate_pack`` staged candidates, ``analysis_pending_review``
    quarantined rows) and every ``event_hygiene``
    ``override_class='synthetic_seed'`` row (AP3a/AP3b).  This matches
    ``scripts/event_study_coverage_report.py`` exactly, so the two
    reports share one denominator.
  * ``raw`` — an all-stage diagnostic data-coverage scan over every
    archive row, including synthetic seeds, staged candidates, and
    pending-review rows.  Diagnostic only: its counts must never be
    quoted as accepted-corpus numbers.

Every payload carries a ``denominator`` metadata block (active lens,
included/excluded stages, excluded override classes, and explicit
excluded/population counts — exclusions are disclosed, never silent)
plus a ``non_claims`` block.

Five binary readiness checks are computed per event:

  * ``has_event_date``                — non-empty ISO event_date.
  * ``has_market_tickers``            — at least one non-empty symbol
                                        in the stored ``market_tickers``
                                        JSON list.
  * ``forward_cache_1d``              — price_cache has at least one
                                        row for the **primary ticker**
                                        (the first non-empty symbol)
                                        with ``date >= event_date +
                                        1 business day``.
  * ``forward_cache_5d`` / ``_20d``   — same, with horizons 5 and 20.
  * ``benchmark_proxy_available``     — price_cache has at least one
                                        row for ``SPY`` with
                                        ``date >= event_date + 20bd``.
                                        ``SPY`` is the project's
                                        universal benchmark fallback
                                        (see ``market_check._DEFAULT_BENCHMARK``).
  * ``estimation_window_sufficient``  — at least 60 distinct cached
                                        dates strictly before the
                                        event_date for the primary
                                        ticker, matching
                                        ``stats.event_study._DEFAULT_ESTIMATION_WINDOW``.

``fully_ready`` is the AND of every above check.  Per-event checks
that depend on a parsed event_date or a primary ticker degrade to
``False`` cleanly when those inputs are missing — there is no
exception path.

Top-level aggregates count every event in the archive (no ``--limit``
truncation); the ``events`` list is capped at ``--limit`` and sorted
by ``id`` ascending so the surfaced sample is deterministic.

Output contract::

    {
      "denominator": {                     # active-lens metadata (AT1)
        "lens":                      "accepted" | "raw",
        "description":               str,
        "included_stages":           [str, ...],   # observed, post-exclusion
        "excluded_stages":           [str, ...],   # policy; [] for raw
        "excluded_override_classes": [str, ...],   # ["synthetic_seed"] / []
        "counts": {
          "archive_rows":               int,   # every parseable events row
          "denominator_events":         int,   # == total_events
          "synthetic_seed_flagged":     int,   # archive-wide population
          "synthetic_seed_excluded":    int,   # dropped under this lens
          "staged_candidates":          int,
          "staged_candidates_excluded": int,
          "pending_review":             int,
          "pending_review_excluded":    int,
          "curated_intake":             int,
          "curated_intake_excluded":    int,
          "total_excluded":             int,
        },
      },
      "non_claims":                              {...},  # see _NON_CLAIMS
      "total_events":                            int,
      "events_with_event_date":                  int,
      "events_with_market_tickers":              int,
      "events_with_event_date_and_tickers":      int,
      "events_with_1d_forward_cache":            int,
      "events_with_5d_forward_cache":            int,
      "events_with_20d_forward_cache":           int,
      "events_missing_benchmark_proxy":          int,
      "events_with_insufficient_estimation_window": int,
      "events_fully_ready":                      int,   # ARCHIVE readiness
      "compute_readiness": {                     # STRICT event-study gate
        "archive_ready_count":             int,
        "event_study_compute_ready_count": int,
        "status_counts": {"event_study_available": int, "insufficient_data": int},
        "top_blocking_reasons":            {str: int},
        "auto_adjust_basis_counts":        {"matched": int, "cross_flag": int},
        "cross_flag_caveat_count":         int,
      },
      "events": [                          # capped at --limit, id asc
        {
          "event_id":         int,
          "event_date":       str | None,
          "primary_ticker":   str | None,
          "checks": {
            "has_event_date":               bool,
            "has_market_tickers":           bool,
            "forward_cache_1d":             bool,
            "forward_cache_5d":             bool,
            "forward_cache_20d":            bool,
            "benchmark_proxy_available":    bool,
            "estimation_window_sufficient": bool,
          },
          "fully_ready": bool,
        },
        ...
      ],
      "recommended_next_action": str,
    }

Per-event entries also carry the row's ``stage`` (or ``None``) so a raw
scan never shows a quarantined or staged row unlabeled.

Out of scope (deliberately)
---------------------------
* Read-only.  Issues only ``SELECT`` statements; never INSERT /
  UPDATE / DELETE; never calls ``_ensure_table`` / ``init_db``.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* The archive-readiness checks above are a pure date-coverage measure.
  The ``compute_readiness`` section additionally reaches
  ``stats.event_study.compute_event_study`` (via
  ``event_study_validation.build_event_study_validation``, the same gate
  the live ``/events/{id}/event-study`` route uses) to count how many
  events the engine can actually score.  That path stays read-only —
  SELECT-only, no provider, no DB writes, no FastAPI, no ``api`` /
  ``routes.*`` import.

Usage::

    python scripts/stat_validation_readiness_report.py
    python scripts/stat_validation_readiness_report.py --json
    python scripts/stat_validation_readiness_report.py --json --limit 20
    python scripts/stat_validation_readiness_report.py --json --lens accepted
    python scripts/stat_validation_readiness_report.py --json --lens raw
    python scripts/stat_validation_readiness_report.py --db-path ./events.db --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date as _date, timedelta as _timedelta
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_LIMIT = 25

# Mirrors ``stats.event_study._DEFAULT_ESTIMATION_WINDOW`` and
# ``market_check._DEFAULT_BENCHMARK`` so the readiness check stays
# aligned with what the compute path actually requires.  Inlined here
# (not imported) so the report keeps its no-project-imports posture
# for the SELECT path.
_ESTIMATION_WINDOW: int = 60
_BENCHMARK_TICKER:  str = "SPY"
_HORIZONS:          tuple[int, ...] = (1, 5, 20)

# Mirror ``db.CURATED_INTAKE_STAGE`` / ``db.CANDIDATE_PACK_STAGE`` /
# ``db.ANALYSIS_PENDING_REVIEW_STAGE`` — kept inline (not imported) for the
# same reason as the constants above: the SELECT path stays project-import
# free.  At run time the accepted lens prefers ``db.NON_ANALYSIS_STAGES``
# (the single source of truth) and falls back to the inline mirror only if
# ``db`` cannot be imported.  Excluded rows are always disclosed via the
# ``denominator`` counts (never silently dropped).
_CURATED_INTAKE_STAGE:  str = "curated_intake"
_CANDIDATE_PACK_STAGE:  str = "z1a_candidate_pack"
_PENDING_REVIEW_STAGE:  str = "analysis_pending_review"
_FALLBACK_NON_ANALYSIS_STAGES: frozenset[str] = frozenset({
    _CURATED_INTAKE_STAGE, _CANDIDATE_PACK_STAGE, _PENDING_REVIEW_STAGE,
})
_SYNTHETIC_SEED_OVERRIDE: str = "synthetic_seed"

# Denominator lenses (AT1).  ``accepted`` is the canonical hygiene-aware
# accepted-corpus analysis / coverage denominator (matches
# ``scripts/event_study_coverage_report.py``); ``raw`` is an all-stage
# diagnostic scan that must never masquerade as the accepted corpus.
LENS_ACCEPTED = "accepted"
LENS_RAW = "raw"
_VALID_LENSES: tuple[str, ...] = (LENS_ACCEPTED, LENS_RAW)

_LENS_DESCRIPTIONS: dict[str, str] = {
    LENS_ACCEPTED: (
        "Hygiene-aware accepted-corpus analysis/coverage denominator: "
        "excludes non-analysis stages (curated_intake, z1a_candidate_pack, "
        "analysis_pending_review) and event_hygiene synthetic_seed rows "
        "(AP3a/AP3b). Matches scripts/event_study_coverage_report.py."
    ),
    LENS_RAW: (
        "All-stage diagnostic data-coverage scan over every archive row, "
        "including synthetic seeds, staged candidates, and pending-review "
        "rows. Diagnostic only - never an accepted-corpus denominator."
    ),
}

_NON_CLAIMS: dict[str, Any] = {
    "not_a_trade_recommendation": True,
    "not_a_prediction": True,
    "no_statistical_significance_claim": True,
    "descriptive_coverage_only": True,
    "raw_lens_is_diagnostic_only": True,
    "notes": (
        "Readiness counts are descriptive data-coverage diagnostics only. "
        "They are not statistical evidence, carry no significance claim, "
        "are not a prediction, and are not advice to transact in any "
        "instrument. The raw lens is an all-stage diagnostic scan and must "
        "never be quoted as the accepted corpus; accepted-corpus numbers "
        "use the accepted lens."
    ),
}


_RECOMMENDED_OK = (
    "Every event in the archive has the cache coverage needed to run "
    "the event-study engine over 1d/5d/20d horizons."
)
_RECOMMENDED_GAPS = (
    "Some events lack the cache coverage needed for the event-study "
    "engine.  Refresh the price cache for the listed primary tickers "
    "and SPY benchmark, then re-run this report."
)


# ---------------------------------------------------------------------------
# Pure SQL probe + compute
# ---------------------------------------------------------------------------


def summarize_readiness(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
    lens: str = LENS_ACCEPTED,
) -> dict[str, Any]:
    """Return the statistical-readiness coverage report dict.

    See module docstring for the full output contract.

    Parameters
    ----------
    db_path
        Optional path to a SQLite events.db file.  When omitted, reads
        ``db.DB_FILE`` so the report follows the project's configured
        archive.
    limit
        Maximum number of per-event entries surfaced under
        ``events``.  The aggregate counts always reflect every event
        in the archive — only the listed examples are truncated.
        Negative values are clamped to ``0``.
    lens
        Denominator lens: ``"accepted"`` (default — hygiene-aware
        accepted-corpus denominator) or ``"raw"`` (all-stage diagnostic
        scan).  Unknown values raise ``ValueError``.
    """
    if lens not in _VALID_LENSES:
        raise ValueError(
            f"unknown lens {lens!r}; expected one of {_VALID_LENSES}"
        )
    capped_limit = max(int(limit), 0)
    empty: dict[str, Any] = _empty_report(lens=lens)

    path = _resolve_db_path(db_path)
    if path is None:
        return empty

    try:
        # Read-only / no-create (matches data_hygiene_report.py): a missing
        # file raises sqlite3.Error here instead of creating a stray events.db.
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return empty

    synthetic: frozenset[int] = frozenset()
    try:
        try:
            event_rows = conn.execute(
                "SELECT id, event_date, market_tickers, stage "
                "FROM events ORDER BY id"
            ).fetchall()
        except sqlite3.Error:
            # Older / hand-rolled fixtures may lack the ``stage`` column;
            # fall back to the stage-less shape (no row is then excluded).
            try:
                rows = conn.execute(
                    "SELECT id, event_date, market_tickers "
                    "FROM events ORDER BY id"
                ).fetchall()
                event_rows = [(r[0], r[1], r[2], None) for r in rows]
            except sqlite3.Error:
                event_rows = []

        try:
            cache_rows = conn.execute(
                "SELECT ticker, date FROM price_cache "
                "WHERE ticker IS NOT NULL AND ticker != '' "
                "  AND date IS NOT NULL AND date != ''"
            ).fetchall()
        except sqlite3.Error:
            cache_rows = []

        # AP3a synthetic-seed flags — read on the SAME read-only connection
        # before it closes (degrades to empty when the sidecar is absent).
        synthetic = _load_synthetic_seed_ids(conn)
    finally:
        conn.close()

    cache_dates_by_ticker = _group_cache_dates(cache_rows)
    excluded_stages = _excluded_stages_for(lens)

    # Per-event compute -------------------------------------------------------
    # Under the ``accepted`` lens, non-analysis-stage rows (curated_intake
    # stubs, staged candidates, pending-review quarantine) and synthetic-seed
    # hygiene rows are dropped from the readiness universe (denominator +
    # listing); every exclusion is tallied in the ``denominator`` block so
    # nothing is silently hidden.  The ``raw`` lens excludes nothing.
    population = {
        "synthetic_seed_flagged":     0,
        "staged_candidates":          0,
        "pending_review":             0,
        "curated_intake":             0,
    }
    excluded = {
        "synthetic_seed_excluded":    0,
        "staged_candidates_excluded": 0,
        "pending_review_excluded":    0,
        "curated_intake_excluded":    0,
        "other_stage_excluded":       0,
    }
    archive_rows = 0
    per_event: list[dict[str, Any]] = []
    for raw_id, raw_event_date, raw_market_tickers, raw_stage in event_rows:
        try:
            event_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        archive_rows += 1
        stage = raw_stage if isinstance(raw_stage, str) else None

        # Archive-wide population disclosure — counted regardless of lens.
        if event_id in synthetic:
            population["synthetic_seed_flagged"] += 1
        if stage == _CANDIDATE_PACK_STAGE:
            population["staged_candidates"] += 1
        elif stage == _PENDING_REVIEW_STAGE:
            population["pending_review"] += 1
        elif stage == _CURATED_INTAKE_STAGE:
            population["curated_intake"] += 1

        # Lens exclusion — stage policy first, then the synthetic-seed flag
        # (the flag tally counts only rows not already stage-excluded, so
        # ``total_excluded`` is a plain sum without double counting).
        if stage is not None and stage in excluded_stages:
            if stage == _CURATED_INTAKE_STAGE:
                excluded["curated_intake_excluded"] += 1
            elif stage == _CANDIDATE_PACK_STAGE:
                excluded["staged_candidates_excluded"] += 1
            elif stage == _PENDING_REVIEW_STAGE:
                excluded["pending_review_excluded"] += 1
            else:
                excluded["other_stage_excluded"] += 1
            continue
        if lens == LENS_ACCEPTED and event_id in synthetic:
            excluded["synthetic_seed_excluded"] += 1
            continue

        event_date_str = raw_event_date if isinstance(raw_event_date, str) else None
        primary_ticker = _primary_ticker(raw_market_tickers)
        has_event_date = _parse_iso_date(event_date_str) is not None
        has_market_tickers = primary_ticker is not None
        event_d = _parse_iso_date(event_date_str)

        forward = {
            h: _has_forward_cache_row(
                cache_dates_by_ticker, primary_ticker, event_d, h,
            )
            for h in _HORIZONS
        }
        benchmark_ok = _has_forward_cache_row(
            cache_dates_by_ticker, _BENCHMARK_TICKER, event_d, max(_HORIZONS),
        )
        est_ok = _has_estimation_window(
            cache_dates_by_ticker, primary_ticker, event_d,
            window=_ESTIMATION_WINDOW,
        )

        checks = {
            "has_event_date":               has_event_date,
            "has_market_tickers":           has_market_tickers,
            "forward_cache_1d":             forward[1],
            "forward_cache_5d":             forward[5],
            "forward_cache_20d":            forward[20],
            "benchmark_proxy_available":    benchmark_ok,
            "estimation_window_sufficient": est_ok,
        }
        fully_ready = all(checks.values())
        per_event.append({
            "event_id":       event_id,
            "event_date":     event_date_str if isinstance(event_date_str, str) and event_date_str else None,
            "primary_ticker": primary_ticker,
            "stage":          stage,
            "checks":         checks,
            "fully_ready":    fully_ready,
        })

    # Aggregates --------------------------------------------------------------
    total_events = len(per_event)
    n_event_date          = sum(1 for e in per_event if e["checks"]["has_event_date"])
    n_market_tickers      = sum(1 for e in per_event if e["checks"]["has_market_tickers"])
    n_both                = sum(
        1 for e in per_event
        if e["checks"]["has_event_date"] and e["checks"]["has_market_tickers"]
    )
    n_forward_1d          = sum(1 for e in per_event if e["checks"]["forward_cache_1d"])
    n_forward_5d          = sum(1 for e in per_event if e["checks"]["forward_cache_5d"])
    n_forward_20d         = sum(1 for e in per_event if e["checks"]["forward_cache_20d"])
    n_missing_benchmark   = sum(
        1 for e in per_event if not e["checks"]["benchmark_proxy_available"]
    )
    n_insufficient_est    = sum(
        1 for e in per_event if not e["checks"]["estimation_window_sufficient"]
    )
    n_fully_ready         = sum(1 for e in per_event if e["fully_ready"])

    # Per-event entries are already in id-ascending order from the
    # SQL ``ORDER BY id`` above; cap at the requested limit.
    truncated = per_event[:capped_limit]

    # Strict event-study compute readiness over EVERY event (not the
    # truncated list), via the same gate the live route uses.
    compute_readiness = _summarize_compute_readiness(
        per_event, db_path=path, archive_ready_count=n_fully_ready,
    )

    total_excluded = sum(excluded.values())
    included_stages = sorted({
        (e["stage"] if e["stage"] is not None else "<untagged>")
        for e in per_event
    })
    denominator = {
        "lens":                      lens,
        "description":               _LENS_DESCRIPTIONS[lens],
        "included_stages":           included_stages,
        "excluded_stages":           sorted(excluded_stages),
        "excluded_override_classes": (
            [_SYNTHETIC_SEED_OVERRIDE] if lens == LENS_ACCEPTED else []
        ),
        "counts": {
            "archive_rows":               archive_rows,
            "denominator_events":         total_events,
            "synthetic_seed_flagged":     population["synthetic_seed_flagged"],
            "synthetic_seed_excluded":    excluded["synthetic_seed_excluded"],
            "staged_candidates":          population["staged_candidates"],
            "staged_candidates_excluded": excluded["staged_candidates_excluded"],
            "pending_review":             population["pending_review"],
            "pending_review_excluded":    excluded["pending_review_excluded"],
            "curated_intake":             population["curated_intake"],
            "curated_intake_excluded":    excluded["curated_intake_excluded"],
            "total_excluded":             total_excluded,
        },
    }

    return {
        "denominator":                                 denominator,
        "non_claims":                                  dict(_NON_CLAIMS),
        "total_events":                                total_events,
        "events_with_event_date":                      n_event_date,
        "events_with_market_tickers":                  n_market_tickers,
        "events_with_event_date_and_tickers":          n_both,
        "events_with_1d_forward_cache":                n_forward_1d,
        "events_with_5d_forward_cache":                n_forward_5d,
        "events_with_20d_forward_cache":               n_forward_20d,
        "events_missing_benchmark_proxy":              n_missing_benchmark,
        "events_with_insufficient_estimation_window":  n_insufficient_est,
        "events_fully_ready":                          n_fully_ready,
        "curated_intake_excluded_count":               excluded["curated_intake_excluded"],
        "compute_readiness":                           compute_readiness,
        "events":                                      truncated,
        "recommended_next_action": (
            _RECOMMENDED_OK
            if total_events > 0 and n_fully_ready == total_events
            else _RECOMMENDED_GAPS
        ),
    }


def _excluded_stages_for(lens: str) -> frozenset[str]:
    """Stage names excluded from the denominator under ``lens``.

    The accepted lens keys off ``db.NON_ANALYSIS_STAGES`` (the single
    source of truth shared with every accepted-corpus loader); the inline
    mirror is only a fallback for environments where ``db`` is not
    importable.  The raw lens excludes nothing.
    """
    if lens != LENS_ACCEPTED:
        return frozenset()
    try:
        import db as _dbmod
        return frozenset(getattr(
            _dbmod, "NON_ANALYSIS_STAGES", _FALLBACK_NON_ANALYSIS_STAGES,
        ))
    except Exception:
        return _FALLBACK_NON_ANALYSIS_STAGES


def _load_synthetic_seed_ids(conn: sqlite3.Connection) -> frozenset[int]:
    """Event ids flagged ``override_class='synthetic_seed'`` (AP3a).

    Prefers ``db.synthetic_seed_ids`` (the canonical helper) on the
    already-open read-only connection; falls back to the equivalent
    inline SELECT when ``db`` is not importable.  Both paths degrade to
    an empty set when the ``event_hygiene`` sidecar is absent.
    """
    try:
        import db as _dbmod
        return _dbmod.synthetic_seed_ids(conn)
    except Exception:
        pass
    try:
        rows = conn.execute(
            "SELECT event_id FROM event_hygiene WHERE override_class = ?",
            (_SYNTHETIC_SEED_OVERRIDE,),
        ).fetchall()
        return frozenset(int(r[0]) for r in rows)
    except sqlite3.Error:
        return frozenset()


# ---------------------------------------------------------------------------
# Compute-readiness — the STRICT gate the live event-study proof enforces
# ---------------------------------------------------------------------------
#
# ``events_fully_ready`` above is ARCHIVE readiness: it unions the two
# auto_adjust flags, checks only the primary ticker's estimation window,
# and never checks that the asset+benchmark intersection forms a single
# contiguous engine-consumable window.  This section answers the stricter
# question the backend proof path actually enforces — would
# ``stats.event_study.compute_event_study`` produce a usable record for
# this event right now? — by REUSING
# ``event_study_validation.build_event_study_validation`` (the same gate
# the ``/events/{id}/event-study`` route uses) rather than duplicating it,
# so the report and the route never drift.

_COMPUTE_TOP_REASONS = 8


def _compute_readiness_empty() -> dict[str, Any]:
    return {
        "archive_ready_count":             0,
        "event_study_compute_ready_count": 0,
        "status_counts": {"event_study_available": 0, "insufficient_data": 0},
        "top_blocking_reasons":            {},
        "auto_adjust_basis_counts":        {"matched": 0, "cross_flag": 0},
        "cross_flag_caveat_count":         0,
    }


def _summarize_compute_readiness(
    per_event: list[dict[str, Any]],
    *,
    db_path: str | None,
    archive_ready_count: int,
) -> dict[str, Any]:
    """Apply the strict event-study compute gate to every event.

    Reuses ``event_study_validation.build_event_study_validation`` so the
    report cannot overstate what the engine can actually compute.
    Read-only: ``build`` issues only ``SELECT`` statements and never
    reaches a provider, the price_cache writer, or a FastAPI surface.
    """
    # Lazy import keeps the module-level import graph (and ``--help``)
    # free of the event-study engine + numpy until a run needs the gate.
    from event_study_validation import (
        STATUS_AVAILABLE,
        STATUS_INSUFFICIENT,
        build_event_study_validation,
    )
    import db as _dbmod

    status_counts = {STATUS_AVAILABLE: 0, STATUS_INSUFFICIENT: 0}
    basis_counts = {"matched": 0, "cross_flag": 0}
    blocking: dict[str, int] = {}
    cross_flag_caveat = 0

    # ``build`` reads price_cache through the global ``db.DB_FILE``; point
    # it at the same archive this report summarizes for the loop, then
    # restore.  When ``db_path`` is the live default this is a no-op.
    saved = _dbmod.DB_FILE
    if db_path is not None:
        _dbmod.DB_FILE = db_path
    try:
        for entry in per_event:
            primary = entry.get("primary_ticker")
            event = {
                "id":             entry.get("event_id"),
                "event_date":     entry.get("event_date"),
                "market_tickers": [{"symbol": primary}] if primary else [],
            }
            out = build_event_study_validation(event)
            if out.get("status") == STATUS_AVAILABLE:
                status_counts[STATUS_AVAILABLE] += 1
                basis = out.get("auto_adjust_basis") or {}
                if basis.get("asset") == basis.get("benchmark"):
                    basis_counts["matched"] += 1
                else:
                    basis_counts["cross_flag"] += 1
                if out.get("basis_caveat"):
                    cross_flag_caveat += 1
            else:
                status_counts[STATUS_INSUFFICIENT] += 1
                for reason in out.get("blocking_reasons") or []:
                    # Collapse parameterized suffixes (``engine_error(..)``)
                    # to the bare reason key for a stable histogram.
                    key = reason.split("(")[0].split(":")[0].strip()
                    blocking[key] = blocking.get(key, 0) + 1
    finally:
        _dbmod.DB_FILE = saved

    top = dict(
        sorted(blocking.items(), key=lambda kv: (-kv[1], kv[0]))[:_COMPUTE_TOP_REASONS]
    )
    return {
        "archive_ready_count":             archive_ready_count,
        "event_study_compute_ready_count": status_counts[STATUS_AVAILABLE],
        "status_counts":                   dict(status_counts),
        "top_blocking_reasons":            top,
        "auto_adjust_basis_counts":        dict(basis_counts),
        "cross_flag_caveat_count":         cross_flag_caveat,
    }


def _empty_report(*, lens: str = LENS_ACCEPTED) -> dict[str, Any]:
    return {
        "denominator": {
            "lens":                      lens,
            "description":               _LENS_DESCRIPTIONS[lens],
            "included_stages":           [],
            "excluded_stages":           sorted(_excluded_stages_for(lens)),
            "excluded_override_classes": (
                [_SYNTHETIC_SEED_OVERRIDE] if lens == LENS_ACCEPTED else []
            ),
            "counts": {
                "archive_rows":               0,
                "denominator_events":         0,
                "synthetic_seed_flagged":     0,
                "synthetic_seed_excluded":    0,
                "staged_candidates":          0,
                "staged_candidates_excluded": 0,
                "pending_review":             0,
                "pending_review_excluded":    0,
                "curated_intake":             0,
                "curated_intake_excluded":    0,
                "total_excluded":             0,
            },
        },
        "non_claims":                                  dict(_NON_CLAIMS),
        "total_events":                                0,
        "events_with_event_date":                      0,
        "events_with_market_tickers":                  0,
        "events_with_event_date_and_tickers":          0,
        "events_with_1d_forward_cache":                0,
        "events_with_5d_forward_cache":                0,
        "events_with_20d_forward_cache":               0,
        "events_missing_benchmark_proxy":              0,
        "events_with_insufficient_estimation_window":  0,
        "events_fully_ready":                          0,
        "curated_intake_excluded_count":               0,
        "compute_readiness":                           _compute_readiness_empty(),
        "events":                                      [],
        # An empty archive isn't "fully ready" for downstream
        # event-study work — there's nothing to validate.  The gaps
        # message is the truthful default; an explicit no-events
        # phrasing would be a separate label without operator value.
        "recommended_next_action":                     _RECOMMENDED_GAPS,
    }


def _resolve_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:
        return None
    return getattr(_db, "DB_FILE", None)


# ---------------------------------------------------------------------------
# Pure helpers — small, isolated, easy to unit-test individually.
# ---------------------------------------------------------------------------


def _group_cache_dates(
    rows: Sequence[tuple],
) -> dict[str, set[str]]:
    """Collect ``{ticker_upper: {iso_date, ...}}`` from raw price_cache rows.

    The auto_adjust flag is intentionally ignored — the readiness
    check cares only that *some* row for the (ticker, date) key
    exists in the cache, regardless of which adjustment flag carries
    it.  Both flags' dates are unioned via ``set``.
    """
    out: dict[str, set[str]] = {}
    for raw_ticker, raw_date in rows:
        if not isinstance(raw_ticker, str) or not raw_ticker:
            continue
        if not isinstance(raw_date, str) or not raw_date:
            continue
        out.setdefault(raw_ticker.upper(), set()).add(raw_date)
    return out


def _parse_iso_date(value: Any) -> _date | None:
    """Return ``date`` for ISO ``YYYY-MM-DD`` strings; else ``None``.

    Defensive against the historical messiness of the archive: empty
    strings, non-string types, malformed dates, and date-time strings
    longer than 10 chars (we accept those by trimming to the first 10
    chars, matching ``price_cache.read_window_no_fetch``).
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        return _date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _primary_ticker(raw_market_tickers: Any) -> str | None:
    """Return the first non-empty ``symbol`` in the JSON list, or ``None``.

    Tolerant of every malformed shape the archive carries:

      * ``None`` / ``""``                 → ``None``
      * unparseable JSON                   → ``None``
      * non-list payload                   → ``None``
      * list with no dict entries          → ``None``
      * list with empty/blank symbols      → ``None``
      * list with non-string symbol fields → ``None``

    Symbols are upper-cased to match the price_cache convention.
    """
    if raw_market_tickers is None:
        return None
    parsed: Any = raw_market_tickers
    if isinstance(parsed, str):
        if not parsed:
            return None
        try:
            parsed = json.loads(parsed)
        except (TypeError, ValueError):
            return None
    if not isinstance(parsed, list):
        return None
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        sym = entry.get("symbol")
        if not isinstance(sym, str):
            continue
        sym = sym.strip().upper()
        if sym:
            return sym
    return None


def _business_day_offset(start: _date, n: int) -> _date:
    """Shift ``start`` forward by ``n`` business days.

    Matches ``scripts.auto_adjust_mismatch_repair_preview._business_day_offset``
    so the readiness check uses the same business-day calendar as the
    no_forward_20d hydrator and the diagnostics surface.  ``n <= 0``
    returns ``start`` unchanged.
    """
    if n <= 0:
        return start
    out = start
    remaining = n
    while remaining > 0:
        out = out + _timedelta(days=1)
        if out.weekday() < 5:
            remaining -= 1
    return out


def _has_forward_cache_row(
    cache_dates_by_ticker: dict[str, set[str]],
    ticker: str | None,
    event_d: _date | None,
    horizon_business_days: int,
) -> bool:
    """True iff the cache has any row for ``ticker`` on or after the
    horizon-shifted event date.

    Returns ``False`` for missing ticker, missing event_date, or empty
    cache — every degraded path collapses to "not ready" cleanly.
    """
    if ticker is None or event_d is None:
        return False
    target = _business_day_offset(event_d, horizon_business_days)
    target_iso = target.isoformat()
    dates = cache_dates_by_ticker.get(ticker.upper())
    if not dates:
        return False
    # ISO-formatted YYYY-MM-DD strings sort lexicographically the same
    # as chronological order, so a string ``>= target_iso`` test is
    # exactly the chronological "on or after" check.
    return any(d >= target_iso for d in dates)


def _has_estimation_window(
    cache_dates_by_ticker: dict[str, set[str]],
    ticker: str | None,
    event_d: _date | None,
    *,
    window: int,
) -> bool:
    """True iff the cache has at least ``window`` distinct dates
    strictly before ``event_d`` for ``ticker``.

    The check is "distinct dates", not "rows" — auto_adjust=0 and
    auto_adjust=1 holding the same date count once.  This matches
    the event-study convention that the estimation window is a
    sequence of pre-event business-day closes, not a row count.
    """
    if ticker is None or event_d is None:
        return False
    dates = cache_dates_by_ticker.get(ticker.upper())
    if not dates:
        return False
    event_iso = event_d.isoformat()
    pre_count = sum(1 for d in dates if d < event_iso)
    return pre_count >= window


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


_LENS_TEXT_LABELS: dict[str, str] = {
    LENS_ACCEPTED: "accepted (hygiene-aware accepted-corpus denominator)",
    LENS_RAW:      "raw (all-stage diagnostic scan - NOT the accepted corpus)",
}


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Archive statistical-readiness coverage report", ""]
    denom = report.get("denominator") or {}
    lens = denom.get("lens", LENS_ACCEPTED)
    counts = denom.get("counts") or {}
    lines.append(f"Lens: {_LENS_TEXT_LABELS.get(lens, lens)}")
    lines.append(
        f"  denominator events:                          "
        f"{counts.get('denominator_events', 0)} "
        f"(of {counts.get('archive_rows', 0)} archive rows; "
        f"{counts.get('total_excluded', 0)} excluded)"
    )
    lines.append(
        f"  excluded:                                    "
        f"synthetic_seed={counts.get('synthetic_seed_excluded', 0)} "
        f"staged_candidates={counts.get('staged_candidates_excluded', 0)} "
        f"pending_review={counts.get('pending_review_excluded', 0)} "
        f"curated_intake={counts.get('curated_intake_excluded', 0)}"
    )
    lines.append(
        f"  archive populations:                         "
        f"synthetic_seed={counts.get('synthetic_seed_flagged', 0)} "
        f"staged_candidates={counts.get('staged_candidates', 0)} "
        f"pending_review={counts.get('pending_review', 0)} "
        f"curated_intake={counts.get('curated_intake', 0)}"
    )
    lines.append("")
    lines.append(f"Total events:                                  {report['total_events']}")
    lines.append(f"  with event_date:                             {report['events_with_event_date']}")
    lines.append(f"  with market_tickers:                         {report['events_with_market_tickers']}")
    lines.append(f"  with both:                                   {report['events_with_event_date_and_tickers']}")
    lines.append(f"  forward cache ready (1d):                    {report['events_with_1d_forward_cache']}")
    lines.append(f"  forward cache ready (5d):                    {report['events_with_5d_forward_cache']}")
    lines.append(f"  forward cache ready (20d):                   {report['events_with_20d_forward_cache']}")
    lines.append(f"  missing benchmark proxy ({_BENCHMARK_TICKER}):              {report['events_missing_benchmark_proxy']}")
    lines.append(f"  insufficient estimation window (<{_ESTIMATION_WINDOW}d):       {report['events_with_insufficient_estimation_window']}")
    lines.append(f"  fully ready (archive):                       {report['events_fully_ready']}")
    lines.append(f"  curated_intake excluded (not analysis):      {report.get('curated_intake_excluded_count', 0)}")
    cr = report.get("compute_readiness") or {}
    basis = cr.get("auto_adjust_basis_counts") or {}
    lines.append(
        f"  event-study compute-ready:                   "
        f"{cr.get('event_study_compute_ready_count', 0)} "
        f"(of {cr.get('archive_ready_count', 0)} archive-ready)"
    )
    lines.append(
        f"  compute basis:                               "
        f"matched={basis.get('matched', 0)} "
        f"cross_flag={basis.get('cross_flag', 0)} "
        f"(caveat={cr.get('cross_flag_caveat_count', 0)})"
    )
    tbr = cr.get("top_blocking_reasons") or {}
    if tbr:
        lines.append("  top compute blockers:")
        for reason, count in tbr.items():
            lines.append(f"    {reason}: {count}")
    lines.append("")

    events = report["events"]
    lines.append(f"Events listed ({len(events)}):")
    if events:
        for entry in events:
            checks = entry.get("checks") or {}
            failed = sorted(k for k, v in checks.items() if v is False)
            failed_str = ", ".join(failed) if failed else "-"
            lines.append(
                f"  id={entry.get('event_id')} "
                f"date={entry.get('event_date') or '-'} "
                f"ticker={entry.get('primary_ticker') or '-'} "
                f"fully_ready={entry.get('fully_ready')}"
            )
            lines.append(f"      failed_checks: {failed_str}")
    else:
        lines.append("  -")
    lines.append("")
    lines.append(f"Recommended next action: {report['recommended_next_action']}")
    lines.append(
        "Non-claims: descriptive coverage diagnostics only - no "
        "statistical-significance claim, not a prediction, not advice to "
        "transact; the raw lens is diagnostic and never the accepted corpus."
    )
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only archive statistical-readiness coverage report.  "
            "Walks the events archive once and counts how many rows "
            "have the cache coverage needed to drive the event-study "
            "engine.  Read-only: no INSERT / UPDATE / DELETE, no "
            "provider call, no LLM, no FastAPI surface."
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
            f"Cap the surfaced per-event list at N entries (default "
            f"{_DEFAULT_LIMIT}).  Aggregate counts always reflect "
            f"every event in the archive."
        ),
    )
    parser.add_argument(
        "--db-path",
        dest="db_path",
        default=None,
        help=(
            "Optional path to a SQLite events.db file.  Defaults to "
            "db.DB_FILE so the report follows the project's "
            "configured archive."
        ),
    )
    parser.add_argument(
        "--lens",
        choices=_VALID_LENSES,
        default=LENS_ACCEPTED,
        help=(
            "Denominator lens.  'accepted' (default) is the hygiene-aware "
            "accepted-corpus analysis/coverage denominator (excludes "
            "non-analysis stages and event_hygiene synthetic_seed rows, "
            "matching scripts/event_study_coverage_report.py).  'raw' is "
            "an all-stage diagnostic scan over every archive row - "
            "diagnostic only, never an accepted-corpus number."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = summarize_readiness(
        db_path=args.db_path, limit=args.limit, lens=args.lens,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
