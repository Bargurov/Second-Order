#!/usr/bin/env python3
"""Read-only evidence rehearsal Q&A report.

Interview-preparation report that asks and answers the hardest
questions about the current evidence set, drawn from the freeze-
candidate cohort and the three short-horizon review batches.  The
report teaches the operator to *defend* the result — never to oversell
it.

Sources (all read-only, never mutated)
--------------------------------------

    artifacts/freeze_candidate_evidence.json
    artifacts/curated_stage_validation_evidence.json
    artifacts/short_horizon_review_validation_top10.json
    artifacts/short_horizon_review_validation_next10.json
    artifacts/short_horizon_review_validation_final8.json

Optional companion (best-effort)
--------------------------------

``scripts.evidence_methodology_limitations_report.build_report`` — when
importable, the rehearsal report consumes the methodology report's
shared definitions (the ``validated_raw_only`` carve-out, the
event-source-vs-record framing) so the two reports stay in lockstep.
A failure to import or build is surfaced as a warning; the rehearsal
report still answers the canonical eight questions from its own
internal copy.

Read-only by construction
-------------------------

* Every artifact is opened ``"r"`` and parsed as JSON; never rewritten.
* No DB connection.  No call to ``yfinance`` / ``market_data`` / a
  paid provider / an LLM / a FastAPI surface.  No network.
* The optional methodology-report import only calls its ``build_report``
  function, which itself is read-only against the same artifact set.

Output contract (JSON)::

    {
      "ok":                       bool,
      "current_evidence_summary": {
        "events_evaluated":         int,
        "total_records":            int,
        "fdr_significant_count":    int,
        "raw_p_candidate_count":    int,
        "verdict_counts":           {verdict: int, ...},
        "mechanism_families":       [str, ...],
        "horizons":                 [int, ...],
        "duplicate_event_ids":      [int, ...],
        "short_horizon_review": {
          "accepted_total":   int,
          "excluded_total":   int,
          "candidate_total":  int,
          "by_batch":         {batch_name: {...}, ...},
        },
      },
      "hard_questions": [
        {"id": str, "question": str},
        ...
      ],
      "suggested_answers": {
        question_id: answer_text,
        ...
      },
      "weak_points": [
        {"name": str, "detail": str},
        ...
      ],
      "must_not_say": [str, ...],
      "warnings":  [str, ...],
      "errors":    [str, ...],
    }

``hard_questions`` and ``suggested_answers`` use stable string IDs so a
consumer can look up an answer without depending on list order.  Every
``hard_questions[*].id`` has a matching key in ``suggested_answers``.

Conservative wording
--------------------

The report is rehearsal material, NEVER an authorisation.  Banned
tokens in any answer text: ``proof``, ``proven``, ``automatically``,
``alpha generated``, ``correct ticker``, ``guaranteed``.  The literal
pipeline label ``validated_raw_only`` is cited verbatim and is the
*only* place the substring ``validated`` is allowed; outside that
label the report never uses the word.  The answer to Q2 explicitly
states that ``validated_raw_only`` is NOT an FDR-significance claim.

Usage::

    python scripts/evidence_rehearsal_qa_report.py --json
    python scripts/evidence_rehearsal_qa_report.py --text
    python scripts/evidence_rehearsal_qa_report.py --json \\
        --artifacts-dir artifacts \\
        --output artifacts/evidence_rehearsal_qa.json
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


_DEFAULT_ARTIFACTS_DIR: Path = ROOT / "artifacts"


# Mirrors the freeze script's benchmark_sensitivity_status vocabulary.
# Kept verbatim here so the rehearsal report can switch on the same
# strings the freeze artifact writes without importing the producer.
_BENCH_STATUS_UNKNOWN:                str = "unknown"
_BENCH_STATUS_BLOCKED:                str = "blocked"
_BENCH_STATUS_PREVIEW_READY:          str = "preview_ready"
_BENCH_STATUS_COMPARISON_UNCOMPUTABLE: str = "comparison_uncomputable"
_BENCH_STATUS_COMPARISON_AVAILABLE:   str = "comparison_available"


_ARTIFACT_FREEZE:     str = "freeze_candidate_evidence.json"
_ARTIFACT_CURATED:    str = "curated_stage_validation_evidence.json"
_ARTIFACT_SH_TOP10:   str = "short_horizon_review_validation_top10.json"
_ARTIFACT_SH_NEXT10:  str = "short_horizon_review_validation_next10.json"
_ARTIFACT_SH_FINAL8:  str = "short_horizon_review_validation_final8.json"


_BATCH_FILENAMES: tuple[tuple[str, str], ...] = (
    ("top10",  _ARTIFACT_SH_TOP10),
    ("next10", _ARTIFACT_SH_NEXT10),
    ("final8", _ARTIFACT_SH_FINAL8),
)


# Stable IDs — order is intentional (this is the interview flow).
_QUESTION_ORDER: tuple[tuple[str, str], ...] = (
    ("q_zero_fdr",
     "Why is 0 FDR-significant not a failure?"),
    ("q_validated_raw_only",
     "What does the verdict label 'validated_raw_only' mean?"),
    ("q_events_vs_records",
     "Why count event-sources and records separately?"),
    ("q_manual_exclusions",
     "Why manually exclude 20 of 28 short-horizon candidates?"),
    ("q_benchmark_sensitivity",
     "What does benchmark sensitivity test, and what does a "
     "different benchmark prove?"),
    ("q_xle_benchmark_status",
     "What happened with XLE benchmark sensitivity?"),
    ("q_next_evidence",
     "What would improve the evidence set next?"),
    ("q_what_not_to_claim",
     "What should not be claimed in an interview?"),
)


# Canonical "do not say" list — explicit so a downstream verification
# harness can pin each item as a substring assertion.  The benchmark-
# sensitivity items are computed at build time via
# :func:`_build_benchmark_must_not_say` so the rehearsal report does
# not carry stale "null spy_result / xle_result" wording after the
# comparison has produced computed legs.
_MUST_NOT_SAY_PRELUDE: tuple[str, ...] = (
    "any record is FDR-significant when the cohort has zero such "
    "records",
    "'validated_raw_only' means the record cleared the FDR bar — it "
    "does not",
    "the cohort predicts future returns, future signals, or any "
    "forward-looking outcome",
)


_MUST_NOT_SAY_TAIL: tuple[str, ...] = (
    "the small, operator-curated cohort generalises to a broader "
    "universe",
    "FDR-adjusted means the records are corrected for every possible "
    "source of bias — it controls multiple-testing only",
    "any single raw-p candidate is a finding; raw_p_candidate is a "
    "vocabulary flag, not a result",
    "the rehearsal report itself authorises any downstream demo "
    "claim — it is a study aid, not approval",
)


# The legacy XLE-vs-SPY warning — kept verbatim and emitted whenever
# the comparison legs are not currently computable.  This is the
# "comparison_uncomputable" / preview-only / blocked / unknown
# branch.  Pinned by a substring assertion in the tests.
_MUST_NOT_SAY_XLE_UNCOMPUTABLE: str = (
    "XLE-vs-SPY benchmark sensitivity is interpretable today — even "
    "with preflight clear, the comparison diagnostic currently returns "
    "null spy_result/xle_result for every checked event, so no "
    "directional inference is supported"
)


# ---------------------------------------------------------------------------
# Patchable seam — tests inject synthetic artifact bundles here
# ---------------------------------------------------------------------------


def _load_artifacts(
    artifacts_dir: str | Path = _DEFAULT_ARTIFACTS_DIR,
) -> tuple[dict[str, Any], list[str]]:
    """Read the five evidence artifacts read-only.  Missing /
    malformed files surface as warnings; the caller decides how to
    surface them in the final report.  Tests patch this seam to inject
    synthetic bundles without writing real JSON files.
    """
    base = Path(artifacts_dir)
    bundle:  dict[str, Any] = {}
    warnings: list[str]     = []

    for key, fname in (
        ("freeze",  _ARTIFACT_FREEZE),
        ("curated", _ARTIFACT_CURATED),
        ("top10",   _ARTIFACT_SH_TOP10),
        ("next10",  _ARTIFACT_SH_NEXT10),
        ("final8",  _ARTIFACT_SH_FINAL8),
    ):
        path = base / fname
        if not path.exists():
            warnings.append(f"artifact missing: {fname}")
            bundle[key] = {}
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                bundle[key] = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"artifact unreadable {fname}: {exc}")
            bundle[key] = {}

    return bundle, warnings


def _load_methodology_report() -> tuple[dict[str, Any] | None, str | None]:
    """Best-effort fetch of the companion methodology report.

    Returns ``(report, error_or_none)``.  Production: imports the
    sibling module's pure-compute entry point.  Tests patch this seam
    when they want to drive the no-methodology branch.
    """
    try:
        from scripts import evidence_methodology_limitations_report as _meth
        report = _meth.build_report()
        return report, None
    except Exception as exc:  # noqa: BLE001 — operator-visible warning
        return None, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def build_rehearsal_report(
    *,
    artifacts_dir: str | Path | None = None,
    output_path:   str | None        = None,
) -> dict[str, Any]:
    """Build the evidence rehearsal Q&A report.

    See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    bundle, load_warnings = _load_artifacts(
        artifacts_dir if artifacts_dir is not None
        else _DEFAULT_ARTIFACTS_DIR,
    )
    warnings.extend(load_warnings)

    methodology_report, meth_err = _load_methodology_report()
    if meth_err:
        warnings.append(
            f"methodology companion unavailable; rehearsal answers fall "
            f"back to internal copy ({meth_err})"
        )

    summary = _build_summary(bundle)

    hard_questions = [
        {"id": q_id, "question": q_text}
        for q_id, q_text in _QUESTION_ORDER
    ]

    suggested_answers = _suggested_answers(
        summary=summary,
        methodology_report=methodology_report,
    )

    weak_points = _weak_points(summary=summary)

    envelope = {
        "ok":                       not errors,
        "current_evidence_summary": summary,
        "hard_questions":           hard_questions,
        "suggested_answers":        suggested_answers,
        "weak_points":              weak_points,
        "must_not_say":             _build_must_not_say(summary),
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
# Summary computation
# ---------------------------------------------------------------------------


def _build_summary(bundle: dict[str, Any]) -> dict[str, Any]:
    """Derive the headline numbers from the artifact bundle.  Every
    number is computed at runtime; hardcoded values would rot the
    rehearsal answers if the artifacts evolved.
    """
    freeze   = _safe_dict(bundle.get("freeze"))
    cohort   = _safe_dict(freeze.get("cohort_summary"))
    verdicts = _safe_dict(freeze.get("verdict_counts"))
    review   = freeze.get("review_completion") or []
    duplicates = list(freeze.get("duplicate_event_ids") or [])

    events_evaluated      = _safe_int(cohort.get("events_evaluated"))
    total_records         = _safe_int(cohort.get("total_records"))
    fdr_significant_count = _safe_int(cohort.get("fdr_significant_count"))
    raw_p_candidate_count = _safe_int(cohort.get("raw_p_candidate_count"))
    mechanism_families    = list(cohort.get("mechanism_families_covered") or [])
    horizons              = list(cohort.get("horizons_covered") or [])

    verdict_counts: dict[str, int] = {}
    for k, v in verdicts.items():
        verdict_counts[str(k)] = _safe_int(v)

    by_batch:   dict[str, dict[str, int]] = {}
    accepted_total: int = 0
    excluded_total: int = 0
    candidate_total: int = 0
    for entry in review:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "")
        if not name:
            continue
        accepted = _safe_int(entry.get("accepted_count"))
        excluded = _safe_int(entry.get("excluded_count"))
        worksheet_total = _safe_int(entry.get("worksheet_total_rows"))
        by_batch[name] = {
            "accepted_count":      accepted,
            "excluded_count":      excluded,
            "worksheet_total":     worksheet_total,
            "events_evaluated":    _safe_int(entry.get("events_evaluated")),
            "records_count":       _safe_int(entry.get("records_count")),
            "significant_count":   _safe_int(entry.get("significant_count")),
        }
        accepted_total  += accepted
        excluded_total  += excluded
        candidate_total += worksheet_total

    benchmark_sensitivity = _build_benchmark_sensitivity_summary(
        _safe_dict(freeze.get("benchmark_sensitivity_status")),
    )

    return {
        "events_evaluated":      events_evaluated,
        "total_records":         total_records,
        "fdr_significant_count": fdr_significant_count,
        "raw_p_candidate_count": raw_p_candidate_count,
        "verdict_counts":        verdict_counts,
        "mechanism_families":    mechanism_families,
        "horizons":              horizons,
        "duplicate_event_ids":   duplicates,
        "short_horizon_review": {
            "accepted_total":   accepted_total,
            "excluded_total":   excluded_total,
            "candidate_total":  candidate_total,
            "by_batch":         by_batch,
        },
        "benchmark_sensitivity": benchmark_sensitivity,
    }


def _build_benchmark_sensitivity_summary(
    block: dict[str, Any],
) -> dict[str, Any]:
    """Distil the freeze artifact's ``benchmark_sensitivity_status``
    block into the flags the rehearsal answer composer needs.  Missing
    or shape-degraded blocks yield a coherent "unknown" summary rather
    than a crash so older fixtures and partial bundles still produce a
    valid report.
    """
    status = block.get("status") if isinstance(block, dict) else None
    if not isinstance(status, str) or not status:
        status = _BENCH_STATUS_UNKNOWN

    comparison_summary = block.get("comparison_summary") \
        if isinstance(block, dict) else None
    comparison_summary = (
        comparison_summary if isinstance(comparison_summary, dict) else None
    )

    # Inspect inner comparison rows for null SPY/XLE results.  The
    # freeze script trims bulky keys but keeps small inner arrays; the
    # SPY-vs-XLE comparison artifact carries either ``comparisons`` or
    # ``rows`` per its own contract — accept either.
    null_events: list[int] = []
    computable_events: list[int] = []
    rows = []
    if comparison_summary is not None:
        for k in ("comparisons", "rows"):
            v = comparison_summary.get(k)
            if isinstance(v, list):
                rows = v
                break
    for row in rows:
        if not isinstance(row, dict):
            continue
        ev_id = row.get("event_id")
        ev_id_int = _safe_int(ev_id) if ev_id is not None else 0
        if not isinstance(ev_id, (int, str)) or ev_id_int == 0:
            continue
        spy = row.get("spy_result")
        xle = row.get("xle_result")
        if spy is None or xle is None:
            null_events.append(ev_id_int)
        else:
            computable_events.append(ev_id_int)

    # Source-of-truth flags.
    preflight_ready = status in (
        _BENCH_STATUS_PREVIEW_READY,
        _BENCH_STATUS_COMPARISON_AVAILABLE,
        _BENCH_STATUS_COMPARISON_UNCOMPUTABLE,
    )
    comparison_attempted = status in (
        _BENCH_STATUS_COMPARISON_AVAILABLE,
        _BENCH_STATUS_COMPARISON_UNCOMPUTABLE,
    )
    comparison_complete = (
        status == _BENCH_STATUS_COMPARISON_AVAILABLE
        and len(computable_events) > 0
    )
    comparison_uncomputable = (
        status == _BENCH_STATUS_COMPARISON_UNCOMPUTABLE
        or (comparison_attempted and not comparison_complete)
    )

    # Per-event interpretation rollup — surfaced verbatim from the
    # freeze block when present so the rehearsal answer can name which
    # events flipped interpretation under XLE without re-deriving the
    # diff locally.  Defaults preserve graceful degradation for older
    # bundles that pre-date the rollup keys.
    changed_event_ids: list[int] = []
    unchanged_event_ids: list[int] = []
    changed_interpretation_count: int = 0
    per_event_summary: list[dict[str, Any]] = []
    if isinstance(block, dict):
        c_in = block.get("changed_event_ids")
        if isinstance(c_in, list):
            changed_event_ids = [
                _safe_int(v) for v in c_in if _safe_int(v) != 0
            ]
        u_in = block.get("unchanged_event_ids")
        if isinstance(u_in, list):
            unchanged_event_ids = [
                _safe_int(v) for v in u_in if _safe_int(v) != 0
            ]
        changed_interpretation_count = _safe_int(
            block.get("changed_interpretation_count")
        )
        p_in = block.get("per_event_summary")
        if isinstance(p_in, list):
            per_event_summary = [e for e in p_in if isinstance(e, dict)]

    return {
        "status":                       status,
        "preflight_ready":              preflight_ready,
        "comparison_attempted":         comparison_attempted,
        "comparison_complete":          comparison_complete,
        "comparison_uncomputable":      comparison_uncomputable,
        "null_event_ids":               sorted(set(null_events)),
        "computable_event_ids":         sorted(set(computable_events)),
        "changed_event_ids":            sorted(set(changed_event_ids)),
        "unchanged_event_ids":          sorted(set(unchanged_event_ids)),
        "changed_interpretation_count": changed_interpretation_count,
        "per_event_summary":            per_event_summary,
        "block_present":                isinstance(block, dict) and bool(block),
    }


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------


def _suggested_answers(
    *,
    summary: dict[str, Any],
    methodology_report: dict[str, Any] | None,
) -> dict[str, str]:
    """Compose the suggested answers, citing the methodology report's
    shared definitions verbatim when available so the two reports stay
    in lockstep.
    """
    fdr_count   = summary["fdr_significant_count"]
    total_recs  = summary["total_records"]
    events_eval = summary["events_evaluated"]
    raw_p       = summary["raw_p_candidate_count"]
    horizons    = summary["horizons"]
    families_n  = len(summary["mechanism_families"])
    sh          = summary["short_horizon_review"]
    accepted    = sh["accepted_total"]
    excluded    = sh["excluded_total"]
    candidates  = sh["candidate_total"]
    duplicates  = summary["duplicate_event_ids"]

    meth_terms = {}
    meth_likely = {}
    if isinstance(methodology_report, dict):
        meth_terms = _safe_dict(methodology_report.get("statistical_terms"))
        for entry in methodology_report.get("likely_questions") or []:
            if not isinstance(entry, dict):
                continue
            q = entry.get("question")
            if isinstance(q, str):
                meth_likely[q] = entry.get("safe_answer")

    # ---- Q1: 0 FDR-significant is not a failure -----------------------------
    q_zero_fdr = (
        f"Zero FDR-significant is the honest answer for a cohort of "
        f"{total_recs} records across {events_eval} event sources.  The "
        f"FDR adjustment (Benjamini-Hochberg, alpha=0.05) is designed to "
        f"control the expected false-discovery proportion across the "
        f"whole cohort; with a small operator-curated cohort the "
        f"adjustment has to be conservative.  Reporting zero is the "
        f"evidence the methodology and pipeline ran end-to-end without "
        f"manufacturing a finding — it is not a failure, it is the "
        f"correct conservative output.  A non-zero FDR-significant "
        f"count from a cohort this small would be the warning sign, not "
        f"this one."
    )

    # ---- Q2: validated_raw_only ---------------------------------------------
    meth_validated_raw_only = meth_terms.get("validated_raw_only")
    if isinstance(meth_validated_raw_only, str) and meth_validated_raw_only:
        q_validated = (
            f"{meth_validated_raw_only}  The current cohort surfaces "
            f"{raw_p} record(s) carrying this label; none of them are "
            f"FDR-significant findings."
        )
    else:
        q_validated = (
            f"'validated_raw_only' is a vocabulary label the curated "
            f"pipeline writes for records whose raw p_value cleared the "
            f"threshold but whose FDR-adjusted fdr_q did NOT.  The label "
            f"looks like a finding because of the word it uses, but the "
            f"underlying record is the exact kind of false-positive risk "
            f"that motivates the FDR adjustment in the first place.  "
            f"The current cohort surfaces {raw_p} record(s) carrying "
            f"this label and zero records that cleared the FDR bar."
        )

    # ---- Q3: events vs records ----------------------------------------------
    meth_events_vs = meth_terms.get("event_source_vs_record_count")
    if isinstance(meth_events_vs, str) and meth_events_vs:
        q_events_vs_records = (
            f"They measure different things.  {meth_events_vs}  In this "
            f"cohort {events_eval} event sources produced {total_recs} "
            f"records across horizons "
            f"{sorted(int(h) for h in horizons if isinstance(h, int))}."
        )
    else:
        q_events_vs_records = (
            f"They measure different things.  One event source (a "
            f"single curated headline) contributes one record per "
            f"horizon the pipeline scored.  In this cohort {events_eval} "
            f"event sources produced {total_recs} records.  Reporting "
            f"only the record count would conflate scoring depth with "
            f"cohort breadth; reporting only event sources would hide "
            f"the per-horizon detail."
        )

    # ---- Q4: manual exclusion of 20 of 28 -----------------------------------
    q_manual_exclusions = (
        f"The {excluded} of {candidates} excluded short-horizon "
        f"candidates were dropped by operator review for documented "
        f"reasons that live on disk in the worksheet's exclude_reason "
        f"column — duplicate headlines, weak ticker proxies for the "
        f"named mechanism, headlines whose direction is not defensible "
        f"from the text alone.  The exclusions are visible, auditable, "
        f"and pre-registered: each excluded row carries its reason in "
        f"the same artifact the validation step reads.  This is "
        f"discipline, not cherry-picking — every dropped row is "
        f"recoverable from the worksheet and could be re-included by a "
        f"reviewer who disagreed with the reason.  The {accepted} "
        f"accepted rows ran through the pipeline unchanged."
    )

    # ---- Q5: benchmark sensitivity -----------------------------------------
    q_benchmark_sensitivity = (
        "Benchmark sensitivity tests whether the abnormal-return "
        "calculation is robust to the choice of market index used as a "
        "control.  The default benchmark is SPY (broad-market); a "
        "sector benchmark like XLE is the alternative for energy-"
        "themed events.  A different benchmark does NOT prove a record "
        "is real; it surfaces how much of the abnormal-return signal "
        "is sector-driven versus ticker-specific.  Until the cohort "
        "carries at least one FDR-significant record under SPY, the "
        "sensitivity test is a discipline check on the methodology, "
        "not evidence of a finding."
    )

    # ---- Q6: XLE benchmark sensitivity status -----------------------------
    q_xle_benchmark_status = _compose_xle_benchmark_status_answer(
        summary.get("benchmark_sensitivity") or {},
    )

    # ---- Q7: what would improve the evidence next --------------------------
    q_next_evidence = (
        "Three independent improvements, in priority order: "
        "(1) expand the operator-curated cohort beyond the current "
        f"{events_eval} event sources / {total_recs} records so the "
        "FDR adjustment has more records to work with; "
        "(2) approve the XLE estimation-window backfill so the "
        "blocked benchmark-sensitivity rows for events 60 and 73 "
        "produce comparable evidence; "
        "(3) add a second-reviewer pass to the short-horizon "
        f"worksheet review — the current {excluded}-of-{candidates} "
        "exclusion rate rests on a single reviewer's judgment.  "
        "None of these promise an FDR-significant result; they "
        "improve the credibility of whatever the next cohort surfaces."
    )

    # ---- Q8: what not to claim in an interview ----------------------------
    q_what_not_to_claim = (
        "Do not claim the cohort contains a finding: it has "
        f"{fdr_count} FDR-significant records out of {total_recs}.  "
        "Do not claim 'validated_raw_only' records are findings — the "
        "label is the pipeline's vocabulary tag for the exact failure "
        "mode the FDR adjustment is designed to catch.  Do not claim "
        "the XLE-vs-SPY comparison has produced an interpretable "
        "sensitivity result — preflight readiness is not the same as "
        "a computable comparison, and any null spy_result / xle_result "
        "pair means no SPY-vs-XLE inference is supported for that "
        "event.  Do not claim the cohort generalises to any broader "
        f"universe; it is operator-curated with {len(duplicates)} known "
        f"duplicate event_id(s) "
        f"({sorted(duplicates) if duplicates else 'none'}) carried "
        f"forward.  Do not describe the {accepted}-of-{candidates} "
        "short-horizon accept rate as a discovery — every exclusion "
        "is recorded with a reason in the worksheet artifacts.  The "
        f"cohort spans {families_n} mechanism families across horizons "
        f"{sorted(int(h) for h in horizons if isinstance(h, int))}; "
        "describe it as a methodology demonstration, not a signal "
        "claim."
    )

    return {
        "q_zero_fdr":              q_zero_fdr,
        "q_validated_raw_only":    q_validated,
        "q_events_vs_records":     q_events_vs_records,
        "q_manual_exclusions":     q_manual_exclusions,
        "q_benchmark_sensitivity": q_benchmark_sensitivity,
        "q_xle_benchmark_status":  q_xle_benchmark_status,
        "q_next_evidence":         q_next_evidence,
        "q_what_not_to_claim":     q_what_not_to_claim,
    }


def _compose_xle_benchmark_status_answer(bench: dict[str, Any]) -> str:
    """Compose the Q6 answer about XLE benchmark sensitivity.

    Always surfaces three pillars so the operator can defend the
    distinction in an interview:
      * preflight / data readiness state
      * the SPY-vs-XLE comparison result state
      * why null comparison payloads mean no inference

    Wording is conservative regardless of branch.  Banned tokens are
    avoided; no directional ("XLE outperforms SPY") language ever
    appears.
    """
    status = bench.get("status") or _BENCH_STATUS_UNKNOWN
    null_event_ids = bench.get("null_event_ids") or []
    computable_event_ids = bench.get("computable_event_ids") or []
    changed_event_ids = bench.get("changed_event_ids") or []
    unchanged_event_ids = bench.get("unchanged_event_ids") or []

    # Pillar 1 — preflight / data readiness.
    if status == _BENCH_STATUS_BLOCKED:
        preflight = (
            "Preflight and data readiness: the XLE preflight is still "
            "blocked — the local price_cache is missing the required "
            "estimation-window rows, so the comparison gate is closed."
        )
    elif status in (
        _BENCH_STATUS_PREVIEW_READY,
        _BENCH_STATUS_COMPARISON_AVAILABLE,
        _BENCH_STATUS_COMPARISON_UNCOMPUTABLE,
    ):
        preflight = (
            "Preflight and data readiness: the XLE preflight now "
            "clears — the local price_cache holds the estimation-"
            "window rows the sensitivity gate requires, so the "
            "comparison gate is open."
        )
    else:
        preflight = (
            "Preflight and data readiness: the current artifact set "
            "does not surface a benchmark-sensitivity preflight signal, "
            "so the preflight state is unknown from the rehearsal "
            "report's inputs alone."
        )

    # Pillar 2 — SPY-vs-XLE comparison result.
    if status == _BENCH_STATUS_COMPARISON_AVAILABLE:
        comparison = (
            f"SPY-vs-XLE comparison result: the comparison ran and "
            f"produced at least one event with both legs computed "
            f"(event_id(s) {sorted(computable_event_ids)} carry "
            f"non-null spy_result and xle_result); the source "
            f"comparison artifact is the place to read the "
            f"per-event detail before any directional reading."
        )
    elif status == _BENCH_STATUS_COMPARISON_UNCOMPUTABLE:
        comparison = (
            f"SPY-vs-XLE comparison result: the comparison ran but "
            f"every checked event came back uncomputable on at least "
            f"one leg — event_id(s) "
            f"{sorted(null_event_ids) if null_event_ids else '[]'} "
            f"carry null spy_result and null xle_result; the "
            f"comparison diagnostic refused to compute a descriptive "
            f"sensitivity on at least one side, so no SPY-vs-XLE "
            f"interpretation comparison was made."
        )
    elif status == _BENCH_STATUS_PREVIEW_READY:
        comparison = (
            "SPY-vs-XLE comparison result: the SPY-vs-XLE comparison "
            "itself has not yet been executed against the now-ready "
            "cache — preflight readiness alone does NOT mean the "
            "sensitivity test was performed."
        )
    elif status == _BENCH_STATUS_BLOCKED:
        comparison = (
            "SPY-vs-XLE comparison result: the comparison has not run "
            "and cannot run until preflight clears."
        )
    else:
        comparison = (
            "SPY-vs-XLE comparison result: the rehearsal report's "
            "inputs do not surface a comparison artifact summary, so "
            "the comparison result is unknown from this evidence set."
        )

    # Pillar 3 — what null comparison payloads mean.
    null_explanation = (
        "What null comparison payloads mean: a null spy_result or "
        "null xle_result is the sensitivity diagnostic refusing to "
        "claim a number, not a benign empty value.  When either leg "
        "is null for an event, the SPY-vs-XLE interpretation cannot "
        "be drawn for that event, and the only honest reading is "
        "that no inference is supported until the comparison "
        "diagnostics are fixed."
    )

    # Pillar 4 — per-event interpretation rollup.  Only appears when
    # the freeze block surfaced the rollup *and* at least one event
    # flipped interpretation between SPY and XLE; otherwise the answer
    # has no per-event detail to honestly surface and the rollup line
    # is omitted.  This preserves graceful degradation for older
    # comparison_available fixtures that don't carry the rollup.
    if (
        status == _BENCH_STATUS_COMPARISON_AVAILABLE
        and isinstance(changed_event_ids, list)
        and len(changed_event_ids) > 0
    ):
        changed_sorted = sorted(int(v) for v in changed_event_ids)
        unchanged_sorted = sorted(int(v) for v in unchanged_event_ids)
        per_event_rollup = (
            f"  Per-event interpretation rollup: benchmark choice "
            f"materially changes the descriptive interpretation for "
            f"event_id(s) {changed_sorted} — under SPY the raw-p and "
            f"FDR thresholds clear and the significance flag is True, "
            f"under XLE neither threshold clears and the significance "
            f"flag is False; the raw-p vs FDR distinction is preserved "
            f"because the rollup reports each axis separately."
        )
        if unchanged_sorted:
            per_event_rollup += (
                f"  Event_id(s) {unchanged_sorted} remain not "
                f"significant under both SPY and XLE benchmarks, so "
                f"benchmark choice did not change the descriptive "
                f"interpretation for those events."
            )
        per_event_rollup += (
            "  This rollup is a descriptive observation about which "
            "benchmark frames each event's abnormal-return result "
            "differently; it does not prove mechanism causality for "
            "any one event."
        )
    else:
        per_event_rollup = ""

    return (
        "The XLE benchmark sensitivity story has three checkpoints "
        "that are easy to conflate.  "
        + preflight + "  "
        + comparison + "  "
        + null_explanation
        + per_event_rollup
    )


# ---------------------------------------------------------------------------
# Must-not-say composition
# ---------------------------------------------------------------------------


def _build_must_not_say(summary: dict[str, Any]) -> list[str]:
    """Compose the rehearsal report's "do not say" list.

    The benchmark-sensitivity warning is conditional on the freeze
    artifact's current state so the rehearsal does not carry stale
    "null spy_result / xle_result" wording after the comparison has
    produced computed legs.  Two branches:

    * ``comparison_complete`` (status == ``comparison_available`` AND
      at least one event has both SPY and XLE legs computed):  emit
      the three benchmark warnings about causality, validation
      framing, and the per-event interpretation rollup.
    * Otherwise (``comparison_uncomputable`` / blocked / preview-only
      / unknown):  keep the legacy null-comparison warning verbatim.

    The non-benchmark items are unchanged in both branches.
    """
    bench = _safe_dict(summary.get("benchmark_sensitivity"))
    items: list[str] = list(_MUST_NOT_SAY_PRELUDE)
    items.extend(_build_benchmark_must_not_say(bench))
    items.extend(_MUST_NOT_SAY_TAIL)
    return items


def _build_benchmark_must_not_say(bench: dict[str, Any]) -> list[str]:
    """Return the benchmark-sensitivity items for the must-not-say list.

    When the freeze artifact's ``benchmark_sensitivity_status`` block
    reads ``comparison_available`` AND at least one event carries both
    SPY and XLE computed legs (``comparison_complete=True``), the
    rehearsal emits three replacement warnings that match the
    currently computed state.  Otherwise the legacy null-comparison
    wording is retained.

    The wording is conservative — banned tokens are avoided, the
    raw-p vs FDR axes are named separately, and no claim is made
    that a benchmark-flipped event proves the underlying mechanism.
    """
    if bool(bench.get("comparison_complete")):
        changed = sorted(int(v) for v in (bench.get("changed_event_ids") or []) if isinstance(v, int))
        unchanged = sorted(int(v) for v in (bench.get("unchanged_event_ids") or []) if isinstance(v, int))
        # Name the changed event(s) verbatim so the rehearsal warning
        # tracks the current rollup rather than a generic placeholder.
        # When no event flipped interpretation, the second-axis
        # warning still applies but no event id is named.
        changed_phrase = (
            f"event_id(s) {changed}"
            if changed else "any benchmark-flipped event"
        )
        unchanged_phrase = (
            f"event_id(s) {unchanged}"
            if unchanged else "events that did not flip"
        )
        return [
            (
                "the SPY-vs-XLE comparison proves mechanism causality "
                "for any event — the comparison rollup is descriptive "
                "only and names which benchmark frames each event's "
                "abnormal-return result, not what caused the result"
            ),
            (
                "XLE validates or invalidates an event significance "
                "flag — the comparison reports which benchmark frames "
                "each event's raw-p threshold and FDR threshold "
                "separately, not which framing is the right one; "
                f"{unchanged_phrase} remain not significant under both "
                "SPY and XLE"
            ),
            (
                "the per-event interpretation rollup can be ignored or "
                f"glossed over — {changed_phrase} change descriptive "
                "interpretation between SPY and XLE on both the raw-p "
                "axis and the FDR axis, and that flip must be cited "
                "with the raw-p vs FDR distinction preserved"
            ),
        ]
    return [_MUST_NOT_SAY_XLE_UNCOMPUTABLE]


# ---------------------------------------------------------------------------
# Weak points
# ---------------------------------------------------------------------------


def _weak_points(*, summary: dict[str, Any]) -> list[dict[str, str]]:
    fdr_count   = summary["fdr_significant_count"]
    total_recs  = summary["total_records"]
    events_eval = summary["events_evaluated"]
    raw_p       = summary["raw_p_candidate_count"]
    duplicates  = summary["duplicate_event_ids"]
    sh          = summary["short_horizon_review"]
    accepted    = sh["accepted_total"]
    excluded    = sh["excluded_total"]
    candidates  = sh["candidate_total"]
    by_batch    = sh["by_batch"]

    points: list[dict[str, str]] = []

    points.append({
        "name":   "zero_fdr_significant",
        "detail": (
            f"{fdr_count} of {total_recs} records cleared the FDR bar; "
            f"the rest are inconclusive_fdr or raw_p_only_candidate "
            f"({raw_p} of the latter).  Every record needs the "
            f"raw_p_candidate caveat when surfaced."
        ),
    })
    points.append({
        "name":   "small_operator_curated_cohort",
        "detail": (
            f"{events_eval} event sources / {total_recs} records is too "
            "small to generalise beyond the curated set.  The cohort is "
            "not sampled from a known universe and the operator chose "
            "every headline by hand."
        ),
    })
    points.append({
        "name":   "manual_exclusion_rate",
        "detail": (
            f"{excluded} of {candidates} short-horizon candidates were "
            f"excluded ({accepted} accepted).  Each exclusion has a "
            "written reason in the worksheet artifact, but the rate "
            "rests on a single reviewer's judgment."
        ),
    })
    if duplicates:
        points.append({
            "name":   "duplicate_event_ids",
            "detail": (
                f"duplicate_event_ids={sorted(duplicates)} appear in "
                "the freeze cohort; the same event source surfaced via "
                "both the curated stage and a short-horizon batch and "
                "is carried forward — counts must be read with that in "
                "mind."
            ),
        })
    final8 = _safe_dict(by_batch.get("final8"))
    if _safe_int(final8.get("accepted_count")) == 0 and _safe_int(
        final8.get("excluded_count")
    ) > 0:
        points.append({
            "name":   "final8_zero_accepted",
            "detail": (
                f"The final8 short-horizon batch accepted 0 of "
                f"{_safe_int(final8.get('excluded_count'))} candidates "
                "— the entire batch contributed no records to the "
                "freeze cohort.  Re-running the reviewer pass on this "
                "batch (or expanding it) is the next improvement."
            ),
        })
    bench = _safe_dict(summary.get("benchmark_sensitivity"))
    bench_status = bench.get("status") or _BENCH_STATUS_UNKNOWN
    null_event_ids = bench.get("null_event_ids") or []
    computable_event_ids = bench.get("computable_event_ids") or []

    if bench_status == _BENCH_STATUS_BLOCKED:
        bench_detail = (
            "The XLE benchmark sensitivity preflight is blocked on "
            "missing local price_cache rows; the SPY-vs-XLE comparison "
            "has not run and cannot run until the required estimation-"
            "window dates are present in price_cache."
        )
    elif bench_status == _BENCH_STATUS_PREVIEW_READY:
        bench_detail = (
            "Preflight readiness has improved — the XLE preflight now "
            "clears — but the SPY-vs-XLE comparison itself has not yet "
            "been executed, so no sensitivity interpretation can be "
            "drawn from this state."
        )
    elif bench_status == _BENCH_STATUS_COMPARISON_UNCOMPUTABLE:
        bench_detail = (
            "Preflight clears, but the SPY-vs-XLE comparison returned "
            f"null spy_result and null xle_result for every checked "
            f"event (event_id(s) "
            f"{sorted(null_event_ids) if null_event_ids else '[]'}); "
            "the comparison diagnostic is uncomputable on at least one "
            "side, so no SPY-vs-XLE interpretation is supported until "
            "those diagnostics are fixed."
        )
    elif bench_status == _BENCH_STATUS_COMPARISON_AVAILABLE:
        bench_detail = (
            f"The SPY-vs-XLE comparison ran and produced at least one "
            f"event with both legs computed "
            f"(event_id(s) {sorted(computable_event_ids)}); readers "
            f"should consult the source comparison artifact before "
            f"drawing any sensitivity reading and treat any null-"
            f"result rows the same way they would treat any other "
            f"missing measurement."
        )
    else:
        bench_detail = (
            "The XLE benchmark sensitivity state cannot be determined "
            "from the current artifact set; the rehearsal report makes "
            "no SPY-vs-XLE claim."
        )

    points.append({
        "name":   "xle_benchmark_sensitivity_status",
        "detail": bench_detail,
    })
    if bench.get("comparison_uncomputable"):
        points.append({
            "name":   "xle_benchmark_sensitivity_comparison_uncomputable",
            "detail": (
                "The benchmark-sensitivity comparison artifact is "
                "present but currently produces null spy_result and "
                "null xle_result for every checked event; the "
                "uncomputable comparison is the rate-limiting weakness "
                "for benchmark sensitivity until the comparison "
                "diagnostics are repaired."
            ),
        })
    points.append({
        "name":   "single_reviewer_workflow",
        "detail": (
            "The short-horizon worksheet review is single-reviewer.  "
            "A second-pair-of-eyes pass would harden the exclusion "
            "decisions and reduce subjectivity risk."
        ),
    })
    points.append({
        "name":   "raw_p_only_label_misread_risk",
        "detail": (
            f"{raw_p} record(s) carry the verdict 'validated_raw_only'.  "
            "The word in the label is easy to misread as a finding; the "
            "rehearsal must explicitly contradict that reading."
        ),
    })
    return points


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except (TypeError, ValueError):
            return 0
    return 0


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "Evidence rehearsal Q&A report", "",
    ]
    summary = _safe_dict(report.get("current_evidence_summary"))
    lines.append("Current evidence summary")
    lines.append("------------------------")
    lines.append(f"  events_evaluated:      {summary.get('events_evaluated')}")
    lines.append(f"  total_records:         {summary.get('total_records')}")
    lines.append(
        f"  fdr_significant_count: {summary.get('fdr_significant_count')}"
    )
    lines.append(
        f"  raw_p_candidate_count: {summary.get('raw_p_candidate_count')}"
    )
    lines.append(f"  horizons:              {summary.get('horizons')}")
    families = summary.get("mechanism_families") or []
    lines.append(
        f"  mechanism_families ({len(families)}): {sorted(families)}"
    )
    lines.append(
        f"  duplicate_event_ids:   {summary.get('duplicate_event_ids')}"
    )
    sh = _safe_dict(summary.get("short_horizon_review"))
    lines.append(
        f"  short_horizon:         accepted={sh.get('accepted_total')} "
        f"excluded={sh.get('excluded_total')} "
        f"total={sh.get('candidate_total')}"
    )
    for name, block in sorted((sh.get("by_batch") or {}).items()):
        b = _safe_dict(block)
        lines.append(
            f"    - {name:<7} accepted={b.get('accepted_count')} "
            f"excluded={b.get('excluded_count')} "
            f"records={b.get('records_count')} "
            f"significant={b.get('significant_count')}"
        )
    verdicts = _safe_dict(summary.get("verdict_counts"))
    if verdicts:
        lines.append("  verdict_counts:")
        for k in sorted(verdicts.keys()):
            lines.append(f"    - {k}: {verdicts[k]}")
    lines.append("")
    lines.append("Hard questions and suggested answers")
    lines.append("------------------------------------")
    answers = _safe_dict(report.get("suggested_answers"))
    for idx, entry in enumerate(report.get("hard_questions") or [], start=1):
        q_id = entry.get("id") if isinstance(entry, dict) else None
        q    = entry.get("question") if isinstance(entry, dict) else None
        ans  = answers.get(q_id, "(no answer available)")
        lines.append(f"")
        lines.append(f"Q{idx}. {q}")
        lines.append(f"  -> {ans}")
    lines.append("")
    lines.append("Weak points to acknowledge")
    lines.append("--------------------------")
    for wp in report.get("weak_points") or []:
        if not isinstance(wp, dict):
            continue
        lines.append(f"  - [{wp.get('name')}] {wp.get('detail')}")
    lines.append("")
    lines.append("Must NOT say")
    lines.append("------------")
    for item in report.get("must_not_say") or []:
        lines.append(f"  - {item}")
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
            "Read-only evidence rehearsal Q&A report.  Reads the freeze-"
            "candidate evidence cohort and the three short-horizon "
            "review batches, computes a current-evidence summary, and "
            "produces eight hard questions + suggested answers so an "
            "operator can defend the evidence in an interview without "
            "overselling.  No DB writes, no provider, no LLM, no "
            "FastAPI; artifacts are never mutated.  Conservative "
            "wording — the report is a study aid, not authorisation."
        ),
    )
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON (default if neither flag is passed).",
    )
    fmt.add_argument(
        "--text", action="store_true",
        help="Emit the compact text rehearsal layout.",
    )
    parser.add_argument(
        "--artifacts-dir", dest="artifacts_dir", default=None,
        help=(
            "Optional directory holding the five evidence artifacts.  "
            f"Defaults to {_DEFAULT_ARTIFACTS_DIR}."
        ),
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope to.  When "
            "omitted, the report has no filesystem side effect."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = build_rehearsal_report(
        artifacts_dir=args.artifacts_dir,
        output_path=args.output_path,
    )

    if args.text:
        print(_render_text(report), file=output)
    else:
        print(_render_json(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "build_rehearsal_report",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
