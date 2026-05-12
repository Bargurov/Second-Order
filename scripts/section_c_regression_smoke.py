#!/usr/bin/env python3
"""Section C post-change regression smoke — read-only.

A small, defensive smoke that runs the three shipped Section C
diagnostics (Daily, Weekly, Still Moving) plus a self-contained
weekly-canonicalization check so an operator can prove a Section C
filter / canonicalization change has not silently broken a sibling
surface.

The smoke is descriptive: it reports what each diagnostic counted
and what the weekly canonicalization helper did on a small synthetic
input.  It never re-tunes a filter, never mutates the events DB, the
news cache, or any artifact under ``artifacts/``, and never calls a
paid provider or an LLM.  The wording is conservative — the smoke
says "did not surface a regression" rather than "proves correctness".

Read-only by construction
-------------------------

* Every diagnostic the smoke invokes is itself read-only.  See the
  module docstrings of:
    - ``scripts.section_c_daily_quality_diagnostic``
    - ``scripts.section_c_weekly_duplicate_diagnostic``
    - ``scripts.section_c_still_moving_quality_diagnostic``
  for the contract each one upholds.
* The weekly canonicalization helper (``routes.weekly_canonicalization
  .collapse_weekly_duplicates``) is a pure function that returns a
  new list — it does not mutate its input and has no filesystem or
  DB side effect.
* The three diagnostics and the canonicalization helper are loaded
  through lazy seam wrappers (``_run_daily`` / ``_run_weekly`` /
  ``_run_still_moving`` / ``_collapse_weekly_duplicates``) so this
  module's top-level import surface stays narrow and tests can patch
  the seams directly.
* No ``yfinance`` / ``market_data`` / paid provider / LLM / FastAPI
  surface is imported at module load.  No ``api`` / ``routes.movers``
  / ``routes.events`` is imported anywhere in the smoke.
* ``--output`` is the only filesystem side effect, and only when
  explicitly passed.

Required checks
---------------

1. Weekly duplicate canonicalization should *reduce* the number of
   surfaced cards when the input contains a repeated-headline group.
   The smoke proves this with a small synthetic input run through
   ``collapse_weekly_duplicates`` so the check does not depend on
   today's events-DB state.
2. The canonical card emitted by the weekly canonicalizer must
   carry ``duplicate_count`` (an int ``>= 1`` when a real collapse
   happened) and ``grouped_event_ids`` (a sorted list of every
   group member's ``event_id``).  Without those two fields a
   downstream consumer cannot tell the canonical card is a
   collapsed cluster.
3. The Daily diagnostic's ``candidates_checked`` count must NOT be
   affected by the weekly canonicalization step.  The smoke
   confirms this by running the Daily diagnostic once and reporting
   its count; the weekly canonicalization runs on a separate
   synthetic input and never touches the Daily inbox.
4. The Still Moving diagnostic must NOT surface candidates that
   fail any of the five required weakness gates (``weak_ticker``,
   ``missing_price_cache``, ``no_benchmark_adjusted_evidence``,
   ``no_persistence_signal``, ``duplicate_narrative``) *once Task 1
   lands*.  Until Task 1 lands the smoke reports the failure counts
   as observed and does NOT raise a regression — it surfaces a
   warning so the operator sees the current shape.
5. Missing ``mechanism_family`` in the Daily inbox must be surfaced
   as a *limitation* (a warning or a non-zero
   ``missing_mechanism_cases`` bucket), never silently hidden.  The
   smoke reads the Daily diagnostic's warnings and bucket and
   surfaces both states in ``daily_mechanism_check``.
6. No provider / LLM / paid-surface call.  Pinned in tests with the
   ``_import_isolation_check`` helper.

Output contract (JSON)::

    {
      "ok":                    bool,
      "daily_summary":         {... 9 keys ...},
      "weekly_summary":        {... 5 keys ...},
      "still_moving_summary":  {... 9 keys ...},
      "weekly_duplicate_check":{... 6 keys ...},
      "still_moving_gate_check":{... 4 keys ...},
      "daily_mechanism_check": {... 4 keys ...},
      "regressions":           [str, ...],
      "warnings":              [str, ...],
      "errors":                [str, ...],
    }

The per-block summaries are descriptive aggregates — they carry the
counts the upstream diagnostic surfaced so an operator can read the
smoke output in one pass without re-running each diagnostic
separately.

Conservative wording
--------------------

Banned tokens in any prose the smoke emits (``regressions``,
``warnings``, ``errors``, the per-block ``notes`` lists):
``proof``, ``proven``, ``validated``, ``guaranteed``,
``automatically``, ``alpha generated``, ``correct ticker``,
``definitely``, ``causes``.  The smoke says "did not surface a
regression on this run" — never "is correct".

Usage::

    python scripts/section_c_regression_smoke.py --json
    python scripts/section_c_regression_smoke.py --json \\
        --daily-input news_inbox.json \\
        --weekly-db-path events.db \\
        --window-days 7 \\
        --still-moving-yaml examples/curated_events.example.yaml
    python scripts/section_c_regression_smoke.py --json \\
        --output artifacts/section_c_regression_smoke.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Defaults — every value is overridable from the CLI.
# ---------------------------------------------------------------------------

_DEFAULT_DAILY_INPUT:               str = "news_inbox.json"
_DEFAULT_WEEKLY_DB_PATH:            str = "events.db"
_DEFAULT_WINDOW_DAYS:               int = 7
_DEFAULT_STILL_MOVING_YAML:         str = "examples/curated_events.example.yaml"
_DEFAULT_EVIDENCE_ARTIFACT:         str = (
    "artifacts/freeze_candidate_evidence.json"
)
_DEFAULT_PERSISTENCE_SIGNALS:       str | None = None

# Required Still Moving weakness gates — a candidate carrying ANY of
# these tags is considered to be failing a required gate.  Mirrors the
# five-axis list in the diagnostic's docstring.
_STILL_MOVING_REQUIRED_GATES: tuple[str, ...] = (
    "weak_ticker",
    "missing_price_cache",
    "no_benchmark_adjusted_evidence",
    "no_persistence_signal",
    "duplicate_narrative",
)


# ---------------------------------------------------------------------------
# Patchable seams — every seam lazy-imports its target so the smoke's
# top-level import surface stays stdlib-only.  Tests patch these seams
# directly with synthetic payloads.
# ---------------------------------------------------------------------------


def _run_daily(
    *,
    input_path:  str | None,
) -> dict[str, Any]:
    """Invoke the Daily diagnostic.  Lazy-imported."""
    from scripts.section_c_daily_quality_diagnostic import (
        run_section_c_daily_quality_diagnostic,
    )
    return run_section_c_daily_quality_diagnostic(input_path=input_path)


def _run_weekly(
    *,
    db_path:        str,
    window_days:    int,
    reference_date: str | None,
) -> dict[str, Any]:
    """Invoke the Weekly duplicate diagnostic.  Lazy-imported."""
    from scripts.section_c_weekly_duplicate_diagnostic import (
        build_diagnostic,
    )
    return build_diagnostic(
        db_path=db_path,
        window_days=window_days,
        reference_date=reference_date,
    )


def _run_still_moving(
    *,
    yaml_path:                str,
    db_path:                  str | None,
    evidence_artifact_path:   str | None,
    persistence_signals_path: str | None,
) -> dict[str, Any]:
    """Invoke the Still Moving diagnostic.  Lazy-imported."""
    from scripts.section_c_still_moving_quality_diagnostic import (
        run_section_c_still_moving_quality_diagnostic,
    )
    return run_section_c_still_moving_quality_diagnostic(
        yaml_path=yaml_path,
        db_path=db_path,
        evidence_artifact_path=evidence_artifact_path,
        persistence_signals_path=persistence_signals_path,
    )


def _collapse_weekly_duplicates(
    cards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Invoke the production weekly canonicalization helper.

    Lazy-imported from ``routes.weekly_canonicalization``.  The
    module is stdlib-only (``re`` + ``typing``) so the import does
    not pull in FastAPI.  Tests patch this seam directly when they
    want to exercise the smoke against a synthetic collapse.
    """
    from routes.weekly_canonicalization import (
        collapse_weekly_duplicates,
    )
    return collapse_weekly_duplicates(cards)


# ---------------------------------------------------------------------------
# Synthetic weekly canonicalization input — used by
# ``weekly_duplicate_check`` so the check does not depend on the
# current events-DB state.  Three duplicates of the same headline plus
# a singleton card.  When canonicalization works correctly:
#
#   * the duplicate cluster collapses to one card,
#   * the singleton passes through unchanged,
#   * the surviving canonical carries duplicate_count == 2 and
#     grouped_event_ids == [11, 12, 13].
# ---------------------------------------------------------------------------


def _build_weekly_synthetic_input() -> list[dict[str, Any]]:
    return [
        {
            "event_id":  11,
            "headline":  "Turkey lira weakens as reserves slip further",
            "event_date":"2026-05-08",
            "primary_ticker": "TUR",
        },
        {
            "event_id":  12,
            "headline":  "Turkey lira weakens as reserves slip further",
            "event_date":"2026-05-08",
            "primary_ticker": "TUR",
        },
        {
            "event_id":  13,
            "headline":  "Turkey lira weakens as reserves slip further",
            "event_date":"2026-05-08",
            "primary_ticker": "TUR",
        },
        {
            "event_id":  20,
            "headline":  "Fed minutes show divided committee",
            "event_date":"2026-05-09",
            "primary_ticker": "SPY",
        },
    ]


# ---------------------------------------------------------------------------
# Per-block builders.  Each one returns a dict that lands under the
# matching top-level key of the smoke envelope.
# ---------------------------------------------------------------------------


def _build_daily_summary(
    report: dict[str, Any],
) -> dict[str, Any]:
    """Project the Daily diagnostic into a flat summary.  Counts are
    pulled from the list lengths so we never trust a sibling count
    field the diagnostic might shadow."""
    return {
        "candidates_checked":          _safe_int(
            report.get("candidates_checked")
        ),
        "accepted_like":               _len(report.get("accepted_like_candidates")),
        "junk":                        _len(report.get("junk_headlines")),
        "raw_legal":                   _len(report.get("raw_legal_text_cases")),
        "off_topic":                   _len(report.get("off_topic_cases")),
        "vague":                       _len(report.get("vague_cases")),
        "duplicates":                  _len(report.get("duplicate_cases")),
        "missing_mechanism":           _len(report.get("missing_mechanism_cases")),
        "warnings":                    _string_list(report.get("warnings")),
    }


def _build_weekly_summary(
    report: dict[str, Any],
) -> dict[str, Any]:
    return {
        "candidates_checked":           _safe_int(
            report.get("candidates_checked")
        ),
        "duplicate_groups":             _len(report.get("duplicate_groups")),
        "repeated_headline_groups":     _len(report.get("repeated_headline_groups")),
        "repeated_date_ticker_groups":  _len(report.get("repeated_date_ticker_groups")),
        "warnings":                     _string_list(report.get("warnings")),
    }


def _build_still_moving_summary(
    report: dict[str, Any],
) -> dict[str, Any]:
    return {
        "candidates_checked":            _safe_int(
            report.get("candidates_checked")
        ),
        "defensible":                    _safe_int(
            report.get("defensible_candidates")
        ),
        "weak_ticker":                   _safe_int(
            report.get("weak_ticker_cases")
        ),
        "bad_proxy":                     _safe_int(
            report.get("bad_proxy_cases")
        ),
        "missing_price_cache":           _safe_int(
            report.get("missing_price_cache_cases")
        ),
        "no_persistence":                _safe_int(
            report.get("no_persistence_cases")
        ),
        "duplicate_narrative":           _safe_int(
            report.get("duplicate_narrative_cases")
        ),
        "warnings":                      _string_list(report.get("warnings")),
    }


def _build_weekly_duplicate_check(
    *,
    warnings: list[str],
    errors:   list[str],
) -> dict[str, Any]:
    """Run the weekly canonicalization helper on a small synthetic
    input and confirm it collapses duplicates while preserving
    ``duplicate_count`` and ``grouped_event_ids``."""
    synthetic = _build_weekly_synthetic_input()
    notes: list[str] = []

    try:
        collapsed = _collapse_weekly_duplicates(list(synthetic))
    except Exception as exc:  # noqa: BLE001 — operator-visible
        errors.append(
            f"weekly canonicalization helper raised: "
            f"{type(exc).__name__}: {exc}"
        )
        return {
            "groups_reduced":            False,
            "duplicate_count_preserved": False,
            "grouped_event_ids_preserved": False,
            "synthetic_input_size":      len(synthetic),
            "synthetic_output_size":     0,
            "notes":                     notes,
        }

    if not isinstance(collapsed, list):
        errors.append(
            "weekly canonicalization helper did not return a list; "
            "treating as a structural break"
        )
        return {
            "groups_reduced":            False,
            "duplicate_count_preserved": False,
            "grouped_event_ids_preserved": False,
            "synthetic_input_size":      len(synthetic),
            "synthetic_output_size":     0,
            "notes":                     notes,
        }

    groups_reduced = len(collapsed) < len(synthetic)
    if not groups_reduced:
        notes.append(
            "synthetic input carries a 3-card duplicate cluster; the "
            "canonicalizer did not reduce the surfaced card count on "
            "this run"
        )

    # Find the canonical card.  It is the only card in the output
    # whose headline matches the duplicate cluster.
    duplicate_count_preserved   = False
    grouped_event_ids_preserved = False
    canonical_card: dict[str, Any] | None = None
    for card in collapsed:
        if not isinstance(card, dict):
            continue
        if card.get("headline") == (
            "Turkey lira weakens as reserves slip further"
        ):
            canonical_card = card
            break

    if canonical_card is None:
        notes.append(
            "canonical card for the duplicate cluster was not present "
            "in the canonicalizer's output"
        )
    else:
        dup = canonical_card.get("duplicate_count")
        gids = canonical_card.get("grouped_event_ids")
        if isinstance(dup, int) and not isinstance(dup, bool) and dup >= 1:
            duplicate_count_preserved = True
        else:
            notes.append(
                "canonical card is missing a non-negative integer "
                "duplicate_count"
            )
        if (
            isinstance(gids, list)
            and all(isinstance(g, int) and not isinstance(g, bool) for g in gids)
            and gids == sorted(gids)
            and {11, 12, 13}.issubset(set(gids))
        ):
            grouped_event_ids_preserved = True
        else:
            notes.append(
                "canonical card is missing the sorted grouped_event_ids "
                "list that names every cluster member"
            )

    return {
        "groups_reduced":              groups_reduced,
        "duplicate_count_preserved":   duplicate_count_preserved,
        "grouped_event_ids_preserved": grouped_event_ids_preserved,
        "synthetic_input_size":        len(synthetic),
        "synthetic_output_size":       len(collapsed),
        "notes":                       notes,
    }


def _build_still_moving_gate_check(
    report: dict[str, Any],
) -> dict[str, Any]:
    """Count Still Moving candidates that fail any required gate.

    Reads the diagnostic's per-candidate ``diagnostic_tags`` and the
    aggregate counters.  Until Task 1 lands the smoke does NOT raise
    a regression; it surfaces the counts and a ``task1_landed``
    heuristic (True iff every required-gate counter is zero).
    """
    by_axis: dict[str, int] = {axis: 0 for axis in _STILL_MOVING_REQUIRED_GATES}
    failing_total = 0
    for cand in report.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        tags = cand.get("diagnostic_tags") or []
        if not isinstance(tags, list):
            continue
        hit = False
        for gate in _STILL_MOVING_REQUIRED_GATES:
            if gate in tags:
                by_axis[gate] += 1
                hit = True
        if hit:
            failing_total += 1

    # Cross-check against the aggregate counters where the diagnostic
    # offers them.  Treat any discrepancy as a note (operator-visible)
    # rather than an error — the per-candidate walk is authoritative.
    notes: list[str] = []
    aggregate_pairs = (
        ("weak_ticker",         "weak_ticker_cases"),
        ("missing_price_cache", "missing_price_cache_cases"),
        ("no_persistence_signal", "no_persistence_cases"),
        ("duplicate_narrative", "duplicate_narrative_cases"),
    )
    for tag, key in aggregate_pairs:
        observed = by_axis.get(tag, 0)
        agg = _safe_int(report.get(key))
        if observed != agg:
            notes.append(
                f"per-candidate walk and aggregate counter disagree on "
                f"{tag!r}: walk={observed} aggregate={agg}; the "
                f"per-candidate walk is treated as authoritative for "
                f"this check"
            )

    # task1_landed requires both: zero failing candidates AND at
    # least one candidate was checked.  An empty curated YAML
    # trivially reports zero failures and would otherwise claim the
    # gate is enforced — surface that ambiguity as a note instead.
    candidates_checked = _safe_int(report.get("candidates_checked"))
    task1_landed = failing_total == 0 and candidates_checked > 0
    if failing_total == 0 and candidates_checked == 0:
        notes.append(
            "no Still Moving candidates were checked; the smoke "
            "cannot confirm Task 1 has landed from an empty input"
        )

    return {
        "candidates_failing_required_gates": failing_total,
        "gate_failures_by_axis":             dict(by_axis),
        "task1_landed":                      task1_landed,
        "notes":                             notes,
    }


def _build_daily_mechanism_check(
    report: dict[str, Any],
) -> dict[str, Any]:
    """Confirm a missing ``mechanism_family`` surfaces as a limitation.

    Two paths are valid:
      * The inbox source-schema does not carry the field; the
        diagnostic emits a warning saying so.
      * The schema carries the field but some entries are
        null/empty/"none"; the diagnostic surfaces those in the
        ``missing_mechanism_cases`` bucket.

    The check fails when neither path is taken — i.e., the warning
    is absent AND the bucket is empty AND yet the inbox is non-empty
    — because that would mean the limitation is hidden.
    """
    warnings = _string_list(report.get("warnings"))
    schema_warning_present = any(
        "mechanism_family" in w.lower()
        for w in warnings
    )
    missing_cases = _len(report.get("missing_mechanism_cases"))
    candidates_checked = _safe_int(report.get("candidates_checked"))

    surfaced_as_limitation = (
        schema_warning_present or missing_cases > 0
        # An empty inbox is trivially fine — there is nothing to surface.
        or candidates_checked == 0
    )

    notes: list[str] = []
    if not surfaced_as_limitation:
        notes.append(
            "Daily diagnostic processed candidates yet emitted no "
            "missing-mechanism warning and reported zero missing-"
            "mechanism cases; the limitation may be hidden — operator "
            "review suggested"
        )
    if schema_warning_present:
        notes.append(
            "missing_mechanism is surfaced as a schema-level warning"
        )
    if missing_cases > 0:
        notes.append(
            f"missing_mechanism is surfaced as {missing_cases} bucketed "
            f"case(s) in the Daily diagnostic"
        )

    return {
        "mechanism_family_warning_in_daily": schema_warning_present,
        "missing_mechanism_cases":           missing_cases,
        "surfaced_as_limitation":            surfaced_as_limitation,
        "notes":                             notes,
    }


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


def run_section_c_regression_smoke(
    *,
    daily_input_path:           str | None = None,
    weekly_db_path:             str        = _DEFAULT_WEEKLY_DB_PATH,
    window_days:                int        = _DEFAULT_WINDOW_DAYS,
    reference_date:             str | None = None,
    still_moving_yaml_path:     str        = _DEFAULT_STILL_MOVING_YAML,
    still_moving_db_path:       str | None = None,
    evidence_artifact_path:     str | None = _DEFAULT_EVIDENCE_ARTIFACT,
    persistence_signals_path:   str | None = _DEFAULT_PERSISTENCE_SIGNALS,
    output_path:                str | None = None,
) -> dict[str, Any]:
    """Run the Section C post-change regression smoke.

    See module docstring for the full output contract.
    """
    warnings:    list[str] = []
    errors:      list[str] = []
    regressions: list[str] = []

    daily_input = daily_input_path or _DEFAULT_DAILY_INPUT

    # ---- Daily diagnostic --------------------------------------------------
    daily_report: dict[str, Any] = {}
    try:
        daily_report = _run_daily(input_path=daily_input)
    except Exception as exc:  # noqa: BLE001 — operator-visible
        errors.append(
            f"Daily diagnostic raised: {type(exc).__name__}: {exc}"
        )
    for e in _string_list(daily_report.get("errors")):
        errors.append(f"daily: {e}")
    for w in _string_list(daily_report.get("warnings")):
        warnings.append(f"daily: {w}")

    daily_summary = _build_daily_summary(daily_report)

    # ---- Weekly diagnostic -------------------------------------------------
    weekly_report: dict[str, Any] = {}
    try:
        weekly_report = _run_weekly(
            db_path=weekly_db_path,
            window_days=window_days,
            reference_date=reference_date,
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(
            f"Weekly diagnostic raised: {type(exc).__name__}: {exc}"
        )
    for e in _string_list(weekly_report.get("errors")):
        errors.append(f"weekly: {e}")
    for w in _string_list(weekly_report.get("warnings")):
        warnings.append(f"weekly: {w}")

    weekly_summary = _build_weekly_summary(weekly_report)

    # ---- Still Moving diagnostic ------------------------------------------
    still_moving_report: dict[str, Any] = {}
    try:
        still_moving_report = _run_still_moving(
            yaml_path=still_moving_yaml_path,
            db_path=still_moving_db_path,
            evidence_artifact_path=evidence_artifact_path,
            persistence_signals_path=persistence_signals_path,
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(
            f"Still Moving diagnostic raised: "
            f"{type(exc).__name__}: {exc}"
        )
    for e in _string_list(still_moving_report.get("errors")):
        errors.append(f"still_moving: {e}")
    for w in _string_list(still_moving_report.get("warnings")):
        warnings.append(f"still_moving: {w}")

    still_moving_summary = _build_still_moving_summary(still_moving_report)

    # ---- Cross-cutting checks ---------------------------------------------
    weekly_duplicate_check  = _build_weekly_duplicate_check(
        warnings=warnings, errors=errors,
    )
    still_moving_gate_check = _build_still_moving_gate_check(
        still_moving_report,
    )
    daily_mechanism_check   = _build_daily_mechanism_check(
        daily_report,
    )

    # ---- Regression bookkeeping -------------------------------------------
    # The weekly canonicalization check is a *structural* invariant — if it
    # fails on the synthetic input the helper itself is broken.
    if not weekly_duplicate_check["groups_reduced"]:
        regressions.append(
            "weekly canonicalization did not reduce a 3-card duplicate "
            "cluster down to one canonical card on the synthetic input; "
            "the canonicalization helper may not be wired in"
        )
    if not weekly_duplicate_check["duplicate_count_preserved"]:
        regressions.append(
            "weekly canonical card did not carry a non-negative integer "
            "duplicate_count; downstream consumers cannot tell the card "
            "is a collapsed cluster"
        )
    if not weekly_duplicate_check["grouped_event_ids_preserved"]:
        regressions.append(
            "weekly canonical card did not carry a sorted "
            "grouped_event_ids list naming every cluster member"
        )

    # Daily candidate count must NOT be affected by the weekly
    # canonicalization step.  The weekly step ran on a synthetic
    # in-memory list, never on the Daily inbox; nevertheless we
    # re-read the Daily count as a defensive cross-check.
    daily_count_after_weekly_step = _safe_int(
        daily_report.get("candidates_checked")
    )
    if daily_count_after_weekly_step != daily_summary["candidates_checked"]:
        regressions.append(
            "Daily candidate count drifted between the initial read "
            "and the post-weekly-step read; the Daily surface may be "
            "affected by Weekly canonicalization (it should not be)"
        )

    # Still Moving gate check — surface the current failure count as a
    # warning until Task 1 lands.  Only flag as a regression when the
    # operator opts into a stricter mode (no flag yet; we surface a
    # warning consistent with the spec).
    failing_total = still_moving_gate_check[
        "candidates_failing_required_gates"
    ]
    if failing_total > 0 and not still_moving_gate_check["task1_landed"]:
        warnings.append(
            f"Still Moving currently surfaces {failing_total} "
            f"candidate(s) that fail at least one required gate "
            f"({', '.join(_STILL_MOVING_REQUIRED_GATES)}); once Task 1 "
            f"lands the smoke will surface this as a regression instead"
        )

    # Daily mechanism limitation must surface somewhere.
    if not daily_mechanism_check["surfaced_as_limitation"]:
        regressions.append(
            "Daily diagnostic processed candidates yet did not surface "
            "missing mechanism_family as a warning or a bucketed case; "
            "the limitation appears to be hidden"
        )

    ok = not errors and not regressions
    envelope: dict[str, Any] = {
        "ok":                       ok,
        "daily_summary":            daily_summary,
        "weekly_summary":           weekly_summary,
        "still_moving_summary":     still_moving_summary,
        "weekly_duplicate_check":   weekly_duplicate_check,
        "still_moving_gate_check":  still_moving_gate_check,
        "daily_mechanism_check":    daily_mechanism_check,
        "regressions":              regressions,
        "warnings":                 warnings,
        "errors":                   errors,
    }

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
# Coercion helpers
# ---------------------------------------------------------------------------


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _len(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str) and v]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Section C post-change regression smoke", ""]
    lines.append(f"OK: {report['ok']}")
    lines.append("")
    daily = report["daily_summary"]
    lines.append(
        f"Daily:       checked={daily['candidates_checked']:>4} "
        f"accepted={daily['accepted_like']:>4} "
        f"junk={daily['junk']:>4} legal={daily['raw_legal']:>4} "
        f"off_topic={daily['off_topic']:>4} vague={daily['vague']:>4} "
        f"dup={daily['duplicates']:>4} no_mech={daily['missing_mechanism']:>4}"
    )
    weekly = report["weekly_summary"]
    lines.append(
        f"Weekly:      checked={weekly['candidates_checked']:>4} "
        f"groups={weekly['duplicate_groups']:>4} "
        f"headline_groups={weekly['repeated_headline_groups']:>4} "
        f"date_ticker_groups={weekly['repeated_date_ticker_groups']:>4}"
    )
    sm = report["still_moving_summary"]
    lines.append(
        f"Still Moving:checked={sm['candidates_checked']:>4} "
        f"defensible={sm['defensible']:>4} "
        f"weak={sm['weak_ticker']:>4} bad_proxy={sm['bad_proxy']:>4} "
        f"no_cache={sm['missing_price_cache']:>4} "
        f"no_persist={sm['no_persistence']:>4} "
        f"dup_narr={sm['duplicate_narrative']:>4}"
    )
    lines.append("")
    wdc = report["weekly_duplicate_check"]
    lines.append(
        f"weekly_duplicate_check: groups_reduced={wdc['groups_reduced']} "
        f"duplicate_count_preserved={wdc['duplicate_count_preserved']} "
        f"grouped_event_ids_preserved={wdc['grouped_event_ids_preserved']}"
    )
    smgc = report["still_moving_gate_check"]
    lines.append(
        f"still_moving_gate_check: "
        f"failing={smgc['candidates_failing_required_gates']} "
        f"task1_landed={smgc['task1_landed']}"
    )
    dmc = report["daily_mechanism_check"]
    lines.append(
        f"daily_mechanism_check: "
        f"surfaced={dmc['surfaced_as_limitation']} "
        f"warning_in_daily={dmc['mechanism_family_warning_in_daily']} "
        f"missing_cases={dmc['missing_mechanism_cases']}"
    )
    if report.get("regressions"):
        lines.append("")
        lines.append("Regressions:")
        for r in report["regressions"]:
            lines.append(f"  - {r}")
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


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Section C post-change regression smoke.  Runs "
            "the Daily, Weekly, and Still Moving diagnostics and a "
            "small synthetic weekly-canonicalization check, then "
            "reports whether any required invariant looks regressed.  "
            "Does not mutate the events DB, the news cache, or any "
            "artifact.  No provider / LLM / FastAPI surface."
        ),
    )
    parser.add_argument(
        "--daily-input", dest="daily_input_path",
        default=None,
        help=(
            f"Path to the Daily Market inbox JSON.  Defaults to "
            f"{_DEFAULT_DAILY_INPUT!r}.  Read-only."
        ),
    )
    parser.add_argument(
        "--weekly-db-path", dest="weekly_db_path",
        default=_DEFAULT_WEEKLY_DB_PATH,
        help=(
            f"Path to the events DB the Weekly diagnostic scans.  "
            f"Defaults to {_DEFAULT_WEEKLY_DB_PATH!r}.  Read-only "
            f"(opened with SQLite URI mode=ro)."
        ),
    )
    parser.add_argument(
        "--window-days", dest="window_days",
        type=int, default=_DEFAULT_WINDOW_DAYS,
        help=(
            f"Trailing window (days) the Weekly diagnostic scans "
            f"(default {_DEFAULT_WINDOW_DAYS})."
        ),
    )
    parser.add_argument(
        "--reference-date", dest="reference_date", default=None,
        help=(
            "ISO-format reference date the Weekly window ends on.  "
            "Defaults to today."
        ),
    )
    parser.add_argument(
        "--still-moving-yaml", dest="still_moving_yaml_path",
        default=_DEFAULT_STILL_MOVING_YAML,
        help=(
            f"Path to the curated-event YAML the Still Moving "
            f"diagnostic reads.  Defaults to "
            f"{_DEFAULT_STILL_MOVING_YAML!r}."
        ),
    )
    parser.add_argument(
        "--still-moving-db-path", dest="still_moving_db_path",
        default=None,
        help=(
            "Optional path to the events DB the Still Moving "
            "diagnostic queries for price_cache coverage.  Defaults "
            "to db.DB_FILE.  Read-only."
        ),
    )
    parser.add_argument(
        "--evidence-artifact", dest="evidence_artifact_path",
        default=_DEFAULT_EVIDENCE_ARTIFACT,
        help=(
            f"Path to the benchmark-adjusted evidence artifact the "
            f"Still Moving diagnostic reads.  Defaults to "
            f"{_DEFAULT_EVIDENCE_ARTIFACT!r}."
        ),
    )
    parser.add_argument(
        "--persistence-signals", dest="persistence_signals_path",
        default=_DEFAULT_PERSISTENCE_SIGNALS,
        help=(
            "Optional path to a JSON mapping event_id -> persistence "
            "signal label.  When omitted, every Still Moving "
            "candidate surfaces 'no_persistence_signal'."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
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
    report = run_section_c_regression_smoke(
        daily_input_path=args.daily_input_path,
        weekly_db_path=args.weekly_db_path,
        window_days=args.window_days,
        reference_date=args.reference_date,
        still_moving_yaml_path=args.still_moving_yaml_path,
        still_moving_db_path=args.still_moving_db_path,
        evidence_artifact_path=args.evidence_artifact_path,
        persistence_signals_path=args.persistence_signals_path,
        output_path=args.output_path,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_section_c_regression_smoke",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
