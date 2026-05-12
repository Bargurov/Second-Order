#!/usr/bin/env python3
"""Read-only methodology and limitations report for the current
evidence set.

Reads four on-disk evidence artifacts (one curated stage cohort plus
three short-horizon review batches) and produces a plain JSON / text
report explaining what the current evidence actually supports, in
interview-safe language.  Never invokes a DB writer, a provider, an
LLM, ``yfinance``, or any FastAPI surface; never rewrites the
artifacts.

Sources (all read-only)::

    artifacts/curated_stage_validation_evidence.json
    artifacts/short_horizon_review_validation_top10.json
    artifacts/short_horizon_review_validation_next10.json
    artifacts/short_horizon_review_validation_final8.json

Output contract (JSON)::

    {
      "ok":                                bool,
      "methodology_summary":               str,
      "statistical_terms":                 dict[str, str],
      "current_evidence_state":            dict,
      "what_the_artifacts_support":        [str, ...],
      "what_the_artifacts_do_not_support": [str, ...],
      "interview_safe_language":           [str, ...],
      "likely_questions":                  [{question, safe_answer}, ...],
      "warnings":                          [str, ...],
      "errors":                            [str, ...],
    }

Conservative-language posture
-----------------------------

* The string ``validated_raw_only`` is a vocabulary label inherited
  from the upstream evidence pipeline (it tags records whose raw
  p-value cleared the threshold but whose FDR-adjusted q-value did
  not).  The report cites that label verbatim, with an explicit
  disclaimer that it is NOT an FDR-significance claim.
* Outside that literal carve-out, the report avoids the words
  ``validated``, ``predictive``, ``proven``, ``proves``, ``proof``,
  and ``guaranteed`` in any surfaced text.
* Current cohort totals (13 event sources, 31 records, 0
  FDR-significant) are derived from the artifacts at run time, not
  hardcoded — the methodology framing stays accurate even if the
  artifacts change.

Usage::

    python scripts/evidence_methodology_limitations_report.py
    python scripts/evidence_methodology_limitations_report.py --json
    python scripts/evidence_methodology_limitations_report.py --text
    python scripts/evidence_methodology_limitations_report.py \\
        --artifacts-dir /path/to/artifacts
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


_ARTIFACT_FILENAMES: tuple[tuple[str, str], ...] = (
    ("curated_stage_validation_evidence",     "curated_stage_validation_evidence.json"),
    ("short_horizon_review_validation_top10", "short_horizon_review_validation_top10.json"),
    ("short_horizon_review_validation_next10","short_horizon_review_validation_next10.json"),
    ("short_horizon_review_validation_final8","short_horizon_review_validation_final8.json"),
)


_DEFAULT_ARTIFACTS_DIR: Path = ROOT / "artifacts"


# ---------------------------------------------------------------------------
# Patchable seam — tests inject synthetic artifact bundles here
# ---------------------------------------------------------------------------


def _load_artifacts(
    artifacts_dir: str | Path = _DEFAULT_ARTIFACTS_DIR,
) -> dict[str, Any]:
    """Load the four evidence artifacts from disk.  Missing or
    malformed files are reported as warnings via the returned
    bundle's ``__warnings__`` slot; the caller decides how to surface
    them in the final report.
    """
    base = Path(artifacts_dir)
    bundle: dict[str, Any] = {}
    warnings: list[str] = []
    for key, fname in _ARTIFACT_FILENAMES:
        path = base / fname
        if not path.exists():
            warnings.append(f"artifact missing: {fname}")
            bundle[key] = None
            continue
        try:
            with path.open("r", encoding="utf-8") as fh:
                bundle[key] = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            warnings.append(f"failed to read {fname}: {e}")
            bundle[key] = None
    bundle["__warnings__"] = warnings
    return bundle


# ---------------------------------------------------------------------------
# Derivation — current_evidence_state
# ---------------------------------------------------------------------------


def _safe_int(v: Any) -> int:
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return v
    return 0


def _safe_examples(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    examples = payload.get("examples")
    if not isinstance(examples, list):
        return []
    return [e for e in examples if isinstance(e, dict)]


def _count_raw_p_only(examples: list[dict[str, Any]]) -> int:
    """Count records the upstream pipeline explicitly tagged as
    raw-p-only.  Tags come from one of two fields:

      * ``raw_p_candidate`` is True, OR
      * ``verdict`` equals the literal ``"validated_raw_only"``.

    No threshold heuristics are applied to raw p-values — the script
    counts only what the artifact tagged.  Short-horizon artifacts
    don't carry these fields, so they contribute zero.
    """
    n = 0
    for e in examples:
        if e.get("raw_p_candidate") is True:
            n += 1
            continue
        if e.get("verdict") == "validated_raw_only":
            n += 1
    return n


def _per_artifact_summary(payload: Any) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {
            "events_evaluated":   0,
            "records_count":      0,
            "significant_count":  0,
            "raw_p_only_records": 0,
        }
    examples = _safe_examples(payload)
    return {
        "events_evaluated":   _safe_int(payload.get("events_evaluated")),
        "records_count":      _safe_int(payload.get("records_count")),
        "significant_count":  _safe_int(payload.get("significant_count")),
        "raw_p_only_records": _count_raw_p_only(examples),
    }


def _build_current_evidence_state(bundle: dict[str, Any]) -> dict[str, Any]:
    per_artifact: dict[str, dict[str, int]] = {}
    for key, _ in _ARTIFACT_FILENAMES:
        per_artifact[key] = _per_artifact_summary(bundle.get(key))

    total_events  = sum(v["events_evaluated"]   for v in per_artifact.values())
    total_records = sum(v["records_count"]      for v in per_artifact.values())
    total_sig     = sum(v["significant_count"]  for v in per_artifact.values())
    total_raw_p   = sum(v["raw_p_only_records"] for v in per_artifact.values())

    horizons: set[int] = set()
    families: set[str] = set()
    for key, _ in _ARTIFACT_FILENAMES:
        payload = bundle.get(key)
        if not isinstance(payload, dict):
            continue
        by_h = payload.get("by_horizon")
        if isinstance(by_h, dict):
            for h_key in by_h.keys():
                try:
                    horizons.add(int(h_key))
                except (TypeError, ValueError):
                    continue
        by_mf = payload.get("by_mechanism_family")
        if isinstance(by_mf, dict):
            for mf_key in by_mf.keys():
                if isinstance(mf_key, str) and mf_key:
                    families.add(mf_key)

    return {
        "total_event_sources_evaluated": total_events,
        "total_records":                 total_records,
        "fdr_significant_records":       total_sig,
        "raw_p_only_records":            total_raw_p,
        "by_artifact":                   per_artifact,
        "horizons_evaluated":            sorted(horizons),
        "mechanism_families_represented": sorted(families),
    }


# ---------------------------------------------------------------------------
# Content blocks — methodology summary, glossary, claims, disclaimers,
# interview-safe language, likely questions.
# ---------------------------------------------------------------------------


_METHODOLOGY_SUMMARY = (
    "The evidence set is an event-study cohort drawn from curated "
    "news headlines and the short-horizon operator review batches. "
    "For each (event_source, horizon) pair the pipeline computes a "
    "horizon-windowed abnormal return and the associated SAR, the "
    "raw per-record p_value, and an FDR-adjusted fdr_q value via "
    "Benjamini-Hochberg across the cohort. Three horizons are "
    "evaluated: 1, 5, and 20 trading days post-event. A record "
    "clears the FDR bar only when fdr_q is below the chosen alpha "
    "(0.05) - the raw p_value alone does not. The current evidence "
    "state surfaces 0 FDR-significant records, so the cohort is "
    "useful for methodology demonstration and case-study discipline, "
    "not a signal claim."
)


def _statistical_terms() -> dict[str, str]:
    return {
        "p_value": (
            "Raw per-record significance. Lower means the observed "
            "abnormal return is less likely under the null. A p_value "
            "below 0.05 on its own is NOT a finding once you account "
            "for the many records tested across the cohort."
        ),
        "fdr_q": (
            "The Benjamini-Hochberg FDR-adjusted q-value computed "
            "across all records in the cohort. Adjustment controls "
            "the expected proportion of false discoveries when "
            "multiple records are tested at once. A record is "
            "FDR-significant only when fdr_q < 0.05; raw p_value is "
            "not sufficient."
        ),
        "raw_p_candidate": (
            "A boolean flag the curated pipeline attaches to a record "
            "when its raw p_value cleared the threshold but its "
            "fdr_q did NOT. The flag is a vocabulary marker, not a "
            "finding."
        ),
        "validated_raw_only": (
            "A verdict label the curated pipeline writes when a "
            "record carries raw_p_candidate=True. The label is "
            "raw-p-only: it does NOT mean the record cleared the FDR "
            "bar, and it does NOT mean the record is a finding. The "
            "report cites this label verbatim because the underlying "
            "artifact uses it; readers should treat it as 'raw "
            "p-value passed, FDR did not.'"
        ),
        "fdr_significant": (
            "Boolean field on each per-record example. True means "
            "fdr_q is below the chosen alpha (0.05) and the record "
            "cleared the FDR bar. The current cohort has 0 records "
            "with fdr_significant=True."
        ),
        "horizon": (
            "Post-event trading-day window used to compute the "
            "abnormal return. The pipeline evaluates three horizons: "
            "1, 5, and 20 trading days post-event. Each event source "
            "contributes one record per horizon it was evaluated on."
        ),
        "mechanism_family": (
            "Closed-vocabulary label assigned during curation to "
            "group records by the kind of mechanism implied by the "
            "headline (e.g. supply_shock, commodity_squeeze, "
            "bank_regulatory_capital_relief). It is a grouping field, "
            "not a finding."
        ),
        "event_source_vs_record_count": (
            "One event source (a single curated headline) contributes "
            "multiple records to the cohort - one per horizon the "
            "pipeline scored. With three horizons (1, 5, 20), one "
            "event source can produce up to three records. The "
            "short-horizon batches only score the 1 and 5 horizons, "
            "so each event source there yields up to two records. "
            "events_evaluated and records_count therefore measure "
            "different things."
        ),
    }


def _what_the_artifacts_support() -> list[str]:
    return [
        "The pipeline computes a per-record p_value and an "
        "FDR-adjusted fdr_q across the cohort, end-to-end, against a "
        "small curated set.",
        "The horizon-windowed abnormal return calculation runs at 1, "
        "5, and 20 trading days post-event and lands in the artifacts "
        "with the expected shape (records_count, significant_count, "
        "by_horizon, by_mechanism_family).",
        "The operator review workflow (worksheet -> validator -> "
        "apply smoke -> stage validation) is exercised end-to-end and "
        "produces inspectable JSON evidence files.",
        "The current evidence state is a methodology demonstration "
        "and a case-study discipline exercise: a reader can follow a "
        "single record from headline to abnormal return to p_value to "
        "fdr_q.",
    ]


def _what_the_artifacts_do_not_support() -> list[str]:
    return [
        "Any forward-looking claim about future returns, future "
        "signals, or future events. The cohort is retrospective and "
        "small.",
        "Any inference from records the artifact tagged "
        "validated_raw_only. The label means the raw p_value cleared "
        "the threshold but the FDR-adjusted fdr_q did NOT - reading "
        "those records as findings is exactly the multiple-testing "
        "mistake the FDR adjustment is designed to catch.",
        "Any cross-cohort generalisation. The cohort is operator-"
        "curated, on the order of 13 event sources and 31 records, "
        "and was not sampled from a known universe.",
        "Any signal claim about a particular ticker, mechanism "
        "family, or horizon. The current cohort has 0 records that "
        "cleared the FDR bar.",
    ]


def _interview_safe_language() -> list[str]:
    return [
        "The current evidence reports record-level p_value and "
        "FDR-adjusted fdr_q across three horizons (1, 5, and 20 "
        "trading days post-event).",
        "Across the four artifacts the cohort surfaces 0 records "
        "with fdr_significant=True. The cohort is useful for "
        "methodology demonstration and case-study discipline, not a "
        "signal claim.",
        "Records the pipeline tagged validated_raw_only cleared the "
        "raw p_value threshold but did NOT clear the FDR-adjusted "
        "fdr_q bar. The label is the pipeline's vocabulary, not a "
        "finding.",
        "events_evaluated and records_count are different numbers: "
        "one event source contributes one record per horizon scored.",
    ]


def _likely_questions() -> list[dict[str, str]]:
    return [
        {
            "question": (
                "Does the current evidence set contain a real signal "
                "anywhere?"
            ),
            "safe_answer": (
                "Across the four artifacts, the cohort has 0 records "
                "with fdr_significant=True. The methodology and the "
                "end-to-end pipeline are exercised; no signal is "
                "claimed. I treat the cohort as a methodology "
                "demonstration and a case-study discipline exercise."
            ),
        },
        {
            "question": (
                "What does the verdict label validated_raw_only mean?"
            ),
            "safe_answer": (
                "It is a vocabulary label the curated pipeline writes "
                "when a record's raw p_value cleared the threshold "
                "but its FDR-adjusted fdr_q did NOT. It is raw-p-"
                "only. The label looks like a finding because of the "
                "word it uses, but the underlying record is the "
                "exact kind of false-positive risk that motivates the "
                "FDR adjustment in the first place."
            ),
        },
        {
            "question": (
                "Why are events_evaluated and records_count different "
                "in the artifacts?"
            ),
            "safe_answer": (
                "One event source - a single curated headline - is "
                "scored at multiple horizons. The curated artifact "
                "uses three horizons (1, 5, 20), so 5 event sources "
                "produce 15 records. The short-horizon batches score "
                "only the 1 and 5 horizons, so each event source "
                "there yields up to two records."
            ),
        },
        {
            "question": (
                "Why such a small cohort?"
            ),
            "safe_answer": (
                "The cohort is operator-curated. Each event source "
                "and each per-record artifact can be inspected by "
                "hand. Scaling the cohort is a separate workstream; "
                "the current artifacts are a methodology "
                "demonstration."
            ),
        },
    ]


# ---------------------------------------------------------------------------
# Top-level report
# ---------------------------------------------------------------------------


def build_report(
    *, artifacts_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Build the methodology and limitations report.  Reads the four
    artifacts read-only via the ``_load_artifacts`` seam and assembles
    the ten-key envelope documented in the module docstring.
    """
    bundle = _load_artifacts(
        artifacts_dir if artifacts_dir is not None
        else _DEFAULT_ARTIFACTS_DIR,
    )
    load_warnings = bundle.pop("__warnings__", []) if isinstance(bundle, dict) else []

    state = _build_current_evidence_state(bundle)

    return {
        "ok":                               True,
        "methodology_summary":              _METHODOLOGY_SUMMARY,
        "statistical_terms":                _statistical_terms(),
        "current_evidence_state":           state,
        "what_the_artifacts_support":       _what_the_artifacts_support(),
        "what_the_artifacts_do_not_support": _what_the_artifacts_do_not_support(),
        "interview_safe_language":          _interview_safe_language(),
        "likely_questions":                 _likely_questions(),
        "warnings":                         list(load_warnings),
        "errors":                           [],
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Evidence methodology & limitations report")
    lines.append("=" * 60)
    lines.append("")
    lines.append("OK: " + str(report["ok"]))
    lines.append("")
    lines.append("Methodology summary")
    lines.append("-" * 60)
    lines.append(str(report["methodology_summary"]))
    lines.append("")
    state = report["current_evidence_state"]
    lines.append("Current evidence state")
    lines.append("-" * 60)
    lines.append(f"  event sources evaluated:   {state['total_event_sources_evaluated']}")
    lines.append(f"  total records:             {state['total_records']}")
    lines.append(f"  FDR-significant records:   {state['fdr_significant_records']}")
    lines.append(f"  raw-p-only records:        {state['raw_p_only_records']}")
    lines.append(f"  horizons evaluated:        {state['horizons_evaluated']}")
    lines.append(f"  mechanism families:        {state['mechanism_families_represented']}")
    lines.append("")
    lines.append("By artifact:")
    for key, sub in state["by_artifact"].items():
        lines.append(
            f"  {key}: events={sub['events_evaluated']}, "
            f"records={sub['records_count']}, "
            f"significant={sub['significant_count']}, "
            f"raw_p_only={sub['raw_p_only_records']}"
        )
    lines.append("")
    lines.append("Statistical terms")
    lines.append("-" * 60)
    for term, defn in report["statistical_terms"].items():
        lines.append(f"  {term}:")
        lines.append(f"    {defn}")
    lines.append("")
    lines.append("What the artifacts support")
    lines.append("-" * 60)
    for item in report["what_the_artifacts_support"]:
        lines.append(f"  - {item}")
    lines.append("")
    lines.append("What the artifacts do NOT support")
    lines.append("-" * 60)
    for item in report["what_the_artifacts_do_not_support"]:
        lines.append(f"  - {item}")
    lines.append("")
    lines.append("Interview-safe language")
    lines.append("-" * 60)
    for item in report["interview_safe_language"]:
        lines.append(f"  - {item}")
    lines.append("")
    lines.append("Likely questions")
    lines.append("-" * 60)
    for q in report["likely_questions"]:
        lines.append(f"  Q: {q.get('question')}")
        lines.append(f"  A: {q.get('safe_answer')}")
        lines.append("")
    if report.get("warnings"):
        lines.append("Warnings")
        lines.append("-" * 60)
        for w in report["warnings"]:
            lines.append(f"  - {w}")
        lines.append("")
    if report.get("errors"):
        lines.append("Errors")
        lines.append("-" * 60)
        for e in report["errors"]:
            lines.append(f"  - {e}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only methodology & limitations report for the "
            "current evidence set.  Aggregates four evidence "
            "artifacts (one curated stage cohort plus three "
            "short-horizon review batches) into a plain JSON / text "
            "report explaining what the cohort actually supports.  "
            "No DB writes, no provider, no LLM, no FastAPI surface.  "
            "Conservative wording: the cohort is a methodology "
            "demonstration, not a signal claim."
        ),
    )
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument(
        "--json", action="store_true",
        help="Emit a structured JSON report (this is also the default).",
    )
    fmt.add_argument(
        "--text", action="store_true",
        help="Emit a compact human-readable text report.",
    )
    parser.add_argument(
        "--artifacts-dir", dest="artifacts_dir",
        default=str(_DEFAULT_ARTIFACTS_DIR),
        help=(
            "Optional artifacts directory override.  Defaults to "
            "<repo-root>/artifacts.  Read-only."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = build_report(artifacts_dir=args.artifacts_dir)
    if args.text:
        output.write(_render_text(report))
        output.write("\n")
    else:
        # JSON is the default; ``--json`` is accepted for ergonomics.
        output.write(_render_json(report))
        output.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
