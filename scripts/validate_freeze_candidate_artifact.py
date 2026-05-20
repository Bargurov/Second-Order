#!/usr/bin/env python3
"""Freeze-candidate evidence artifact schema validator.

Validates an ``artifacts/freeze_candidate_evidence.json`` file against
the freeze-candidate schema *before* it becomes the demo backend's
input dependency.  The validator is read-only: it opens the artifact,
walks its structure, and emits a structured ``ok`` / ``errors`` /
``warnings`` envelope.  The artifact file itself is never mutated.

What the validator checks
-------------------------

1. Required top-level keys exist:
   ``artifact_type``, ``cohort_summary``, ``records``,
   ``benchmark_sensitivity_status``, ``duplicate_event_ids``,
   ``limitations``.
2. ``artifact_type`` equals exactly ``freeze_candidate_evidence``.
   The artifact is a *freeze-candidate*; the validator never accepts
   it being renamed "frozen" before operator approval.
3. ``cohort_summary`` is a non-null object.
4. ``records`` is a list, and each record carries the 12 required
   fields: ``source``, ``event_id``, ``headline``, ``primary_ticker``,
   ``benchmark``, ``mechanism_family``, ``horizon``, ``p_value``,
   ``fdr_q``, ``raw_p_candidate``, ``fdr_significant``, ``verdict``.
5. ``verdict`` is one of: ``fdr_significant``, ``raw_p_only_candidate``,
   ``inconclusive_fdr``, ``insufficient``.
6. ``cohort_summary.fdr_significant_count`` matches the number of
   records whose ``verdict`` is ``fdr_significant``.
7. No record with ``verdict == "raw_p_only_candidate"`` may carry
   ``fdr_significant == True`` — raw-p-only signals are never
   counted as FDR-significant.
8. ``benchmark_sensitivity_status`` exists as an object and its
   ``status`` field is one of:
   ``unknown``, ``blocked``, ``preview_ready``,
   ``comparison_uncomputable``, ``comparison_available``.
9. ``duplicate_event_ids`` is present (list, may be empty).
10. ``limitations`` exists as a list of strings.  When
    ``fdr_significant_count == 0``, at least one ``limitations``
    entry must mention the "no FDR-significant" caveat.
11. No forbidden overclaim tokens appear in ``limitations`` text:
    ``proof``, ``proven``, ``guaranteed``, ``alpha generated``,
    ``correct ticker``, ``automatically``, ``validated``.

Read-only by construction
-------------------------

* No DB writes — no DB reads either.  The single input is one JSON
  file path supplied via ``--artifact``.
* No provider / yfinance / market_data / price_cache.fetch_*; no
  LLM; no FastAPI surface (never imports ``api`` / ``routes.*``).
* The artifact file is opened in read-mode only; the validator never
  produces an ``--output``.  Byte identity is preserved across a
  validation run.
* Validates the artifact as freeze-candidate evidence only — the
  validator never claims the artifact is "frozen", and the schema
  pin on ``artifact_type`` actively prevents that label from
  appearing.

Output contract (JSON)::

    {
      "ok":             bool,    # True iff errors is empty
      "artifact_path":  str,     # echoes the supplied path
      "records_count":  int,     # len(records) after parse; 0 on
                                 # missing / malformed input
      "errors":         list[str],
      "warnings":       list[str],
    }

Conservative wording — the validator describes schema compliance,
not validation of the underlying evidence.  Banned tokens in this
module's own emitted prose: ``proof``, ``proven``, ``guaranteed``,
``alpha generated``, ``correct ticker``, ``automatically``,
``validated``.

Usage::

    python scripts/validate_freeze_candidate_artifact.py \\
        --artifact artifacts/freeze_candidate_evidence.json
    python scripts/validate_freeze_candidate_artifact.py \\
        --artifact artifacts/freeze_candidate_evidence.json --json
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


_ARTIFACT_TYPE_EXPECTED: str = "freeze_candidate_evidence"


_REQUIRED_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "artifact_type",
    "cohort_summary",
    "records",
    "benchmark_sensitivity_status",
    "duplicate_event_ids",
    "limitations",
)


_REQUIRED_RECORD_FIELDS: tuple[str, ...] = (
    "source",
    "event_id",
    "headline",
    "primary_ticker",
    "benchmark",
    "mechanism_family",
    "horizon",
    "p_value",
    "fdr_q",
    "raw_p_candidate",
    "fdr_significant",
    "verdict",
)


_VALID_VERDICTS: frozenset[str] = frozenset({
    "fdr_significant",
    "raw_p_only_candidate",
    "inconclusive_fdr",
    "insufficient",
})


_VALID_BENCH_STATUSES: frozenset[str] = frozenset({
    "unknown",
    "blocked",
    "preview_ready",
    "comparison_uncomputable",
    "comparison_available",
})


# Banned overclaim tokens that may not appear in any ``limitations``
# entry.  The validator scans ``limitations`` only — disallow lists in
# ``evidence_claim_not_allowed`` legitimately reference some of these
# tokens inside disclaimers, so scanning that field would be a
# self-defeating false-positive.
_BANNED_LIMITATION_TOKENS: tuple[str, ...] = (
    "proof",
    "proven",
    "guaranteed",
    "alpha generated",
    "correct ticker",
    "automatically",
    "validated",
)


# Substring matched (lowercased) against ``limitations`` entries to
# detect the no-FDR caveat.  Kept loose so the validator is not
# brittle-coupled to the builder's exact phrasing.
_NO_FDR_CAVEAT_TOKEN: str = "no fdr-significant"


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_validate_freeze_candidate_artifact(
    *,
    artifact_path: str | None = None,
) -> dict[str, Any]:
    """Validate one freeze-candidate evidence artifact.

    See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    if not artifact_path:
        errors.append(
            "--artifact is required: pass the path to a freeze-candidate "
            "evidence JSON artifact"
        )
        return _envelope(
            artifact_path=artifact_path or "",
            records_count=0,
            errors=errors, warnings=warnings,
        )

    path = Path(artifact_path)
    if not path.exists():
        errors.append(
            f"artifact path does not exist on disk: {artifact_path!r}"
        )
        return _envelope(
            artifact_path=artifact_path,
            records_count=0,
            errors=errors, warnings=warnings,
        )

    try:
        with open(artifact_path, "r", encoding="utf-8") as fh:
            payload: Any = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(
            f"failed to parse artifact as JSON: "
            f"{type(exc).__name__}: {exc}"
        )
        return _envelope(
            artifact_path=artifact_path,
            records_count=0,
            errors=errors, warnings=warnings,
        )

    if not isinstance(payload, dict):
        errors.append(
            f"artifact root must be a JSON object, got "
            f"{type(payload).__name__}"
        )
        return _envelope(
            artifact_path=artifact_path,
            records_count=0,
            errors=errors, warnings=warnings,
        )

    # Step 1: required top-level keys.
    for key in _REQUIRED_TOP_LEVEL_KEYS:
        if key not in payload:
            errors.append(
                f"required top-level key missing: {key!r}"
            )

    # Step 2: artifact_type.
    artifact_type = payload.get("artifact_type")
    if artifact_type is not None and artifact_type != _ARTIFACT_TYPE_EXPECTED:
        errors.append(
            f"artifact_type must equal {_ARTIFACT_TYPE_EXPECTED!r}, "
            f"got {artifact_type!r}"
        )

    # Step 3: cohort_summary.
    cohort_summary = payload.get("cohort_summary")
    if "cohort_summary" in payload and not isinstance(cohort_summary, dict):
        errors.append(
            f"cohort_summary must be a JSON object, got "
            f"{type(cohort_summary).__name__}"
        )
        cohort_summary = None

    # Step 4: records — must be a list; validate per-record fields.
    records_raw = payload.get("records")
    records: list[dict[str, Any]]
    if "records" in payload and not isinstance(records_raw, list):
        errors.append(
            f"records must be a list, got {type(records_raw).__name__}"
        )
        records = []
    else:
        records = records_raw or []  # type: ignore[assignment]

    _check_records(records, errors)

    # Step 5: fdr_significant_count consistency.
    if isinstance(cohort_summary, dict):
        _check_fdr_count(
            cohort_summary=cohort_summary,
            records=records,
            errors=errors,
        )

    # Step 6: benchmark_sensitivity_status.
    bench_status = payload.get("benchmark_sensitivity_status")
    if "benchmark_sensitivity_status" in payload:
        _check_benchmark_sensitivity_status(bench_status, errors)

    # Step 7: duplicate_event_ids.
    if "duplicate_event_ids" in payload:
        dup_ids = payload.get("duplicate_event_ids")
        if not isinstance(dup_ids, list):
            errors.append(
                f"duplicate_event_ids must be a list, got "
                f"{type(dup_ids).__name__}"
            )

    # Step 8: limitations.
    if "limitations" in payload:
        limitations = payload.get("limitations")
        fdr_count = 0
        if isinstance(cohort_summary, dict):
            raw = cohort_summary.get("fdr_significant_count")
            if isinstance(raw, int) and not isinstance(raw, bool):
                fdr_count = raw
        _check_limitations(
            limitations=limitations,
            fdr_significant_count=fdr_count,
            errors=errors,
            warnings=warnings,
        )

    return _envelope(
        artifact_path=artifact_path,
        records_count=len(records),
        errors=errors, warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Per-section checks
# ---------------------------------------------------------------------------


def _check_records(
    records: list[Any], errors: list[str],
) -> None:
    """Validate each record carries the 12 required fields and a
    recognised verdict; pin the raw-p-only / fdr-significant
    invariant."""
    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            errors.append(
                f"record[{idx}] must be a JSON object, got "
                f"{type(rec).__name__}"
            )
            continue
        for field in _REQUIRED_RECORD_FIELDS:
            if field not in rec:
                errors.append(
                    f"record[{idx}] missing required field {field!r}"
                )
        verdict = rec.get("verdict")
        if isinstance(verdict, str) and verdict not in _VALID_VERDICTS:
            errors.append(
                f"record[{idx}] verdict {verdict!r} is not in the "
                f"allowed vocabulary "
                f"{sorted(_VALID_VERDICTS)!r}"
            )
        # Raw-p-only records must NEVER be flagged as FDR-significant.
        if verdict == "raw_p_only_candidate":
            fdr_sig = rec.get("fdr_significant")
            if fdr_sig is True:
                errors.append(
                    f"record[{idx}] has verdict raw_p_only_candidate "
                    f"but fdr_significant=True; raw-p-only records "
                    f"must not be counted as FDR-significant"
                )
        # Symmetric guardrail: a verdict of fdr_significant must be
        # accompanied by fdr_significant=True.  Catches builder bugs
        # before the count check (which only sums verdict tokens) lets
        # a half-flagged record through.
        if verdict == "fdr_significant":
            fdr_sig = rec.get("fdr_significant")
            if fdr_sig is not True:
                errors.append(
                    f"record[{idx}] has verdict fdr_significant but "
                    f"fdr_significant={fdr_sig!r}; the verdict requires "
                    f"the flag to be True"
                )


def _check_fdr_count(
    *,
    cohort_summary: dict[str, Any],
    records: list[Any],
    errors: list[str],
) -> None:
    expected = sum(
        1 for r in records
        if isinstance(r, dict) and r.get("verdict") == "fdr_significant"
    )
    declared = cohort_summary.get("fdr_significant_count")
    if not isinstance(declared, int) or isinstance(declared, bool):
        errors.append(
            f"cohort_summary.fdr_significant_count must be an int, "
            f"got {type(declared).__name__}"
        )
        return
    if declared != expected:
        errors.append(
            f"cohort_summary.fdr_significant_count={declared} does not "
            f"match {expected} record(s) with "
            f"verdict='fdr_significant'"
        )


def _check_benchmark_sensitivity_status(
    bench_status: Any, errors: list[str],
) -> None:
    if not isinstance(bench_status, dict):
        errors.append(
            f"benchmark_sensitivity_status must be a JSON object, "
            f"got {type(bench_status).__name__}"
        )
        return
    status = bench_status.get("status")
    if not isinstance(status, str):
        errors.append(
            "benchmark_sensitivity_status.status missing or not a string"
        )
        return
    if status not in _VALID_BENCH_STATUSES:
        errors.append(
            f"benchmark_sensitivity_status.status {status!r} is not in "
            f"the allowed vocabulary "
            f"{sorted(_VALID_BENCH_STATUSES)!r}"
        )


def _check_limitations(
    *,
    limitations: Any,
    fdr_significant_count: int,
    errors: list[str],
    warnings: list[str],
) -> None:
    if not isinstance(limitations, list):
        errors.append(
            f"limitations must be a list of strings, got "
            f"{type(limitations).__name__}"
        )
        return
    # Stringify only — every entry should be a string per the schema.
    text_entries: list[str] = []
    for idx, entry in enumerate(limitations):
        if not isinstance(entry, str):
            errors.append(
                f"limitations[{idx}] must be a string, got "
                f"{type(entry).__name__}"
            )
            continue
        text_entries.append(entry)

    if fdr_significant_count == 0:
        if not any(
            _NO_FDR_CAVEAT_TOKEN in entry.lower()
            for entry in text_entries
        ):
            errors.append(
                "limitations must include a 'no FDR-significant' "
                "caveat when cohort_summary.fdr_significant_count is 0"
            )

    joined = " | ".join(text_entries).lower()
    for token in _BANNED_LIMITATION_TOKENS:
        if token in joined:
            errors.append(
                f"limitations contains banned overclaim token "
                f"{token!r}; freeze-candidate prose must remain "
                f"conservative"
            )


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def _envelope(
    *,
    artifact_path: str,
    records_count: int,
    errors:        list[str],
    warnings:      list[str],
) -> dict[str, Any]:
    return {
        "ok":            not errors,
        "artifact_path": artifact_path,
        "records_count": records_count,
        "errors":        errors,
        "warnings":      warnings,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "Freeze-candidate evidence artifact validator", "",
    ]
    lines.append(f"OK:               {report['ok']}")
    lines.append(f"Artifact path:    {report['artifact_path']}")
    lines.append(f"Records count:    {report['records_count']}")
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
            "Read-only freeze-candidate evidence artifact schema "
            "validator.  Walks the structure of an "
            "artifacts/freeze_candidate_evidence.json file and reports "
            "schema compliance via a structured ok/errors envelope.  "
            "The validator never mutates the artifact, never claims "
            "the artifact is frozen, and emits no filesystem side "
            "effects."
        ),
    )
    parser.add_argument(
        "--artifact", dest="artifact_path", required=True,
        help=(
            "Required path to a freeze-candidate evidence JSON "
            "artifact.  Read-only; the validator opens this file in "
            "read mode only."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = run_validate_freeze_candidate_artifact(
        artifact_path=args.artifact_path,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_validate_freeze_candidate_artifact",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
