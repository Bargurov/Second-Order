#!/usr/bin/env python3
"""Summarize the v2 selection-funnel ledger and audit against the
v2 artifact disclosure.

The ledger (default ``examples/selection_funnel_ledger.yaml``) is a
flat list of candidate considerations recorded across the v2
workstream. Each entry carries ``gate_stage``, ``outcome``, and a
validation-run ``result_code`` (PASS / FAIL_WRONG_SIGN /
FAIL_DATE_ERROR / N/A for non-validation rows).

This script computes the funnel counts and verifies them against
the numbers the v2 artifact's ``selection_bias_disclosure`` claims:

* approximately 20 candidates considered (tolerance: 18..22 inclusive)
* 8 temp-validation runs (counting temp_validation + corrected_validation)
* 4 pass, 4 fail
* 3 date-error originals (CENX-Apr6, TXT-Dec5, RIO-Jan28)
* 1 wrong-sign rejection at validation (WY softwood)
* 2 provider-blocked (CLR, AGN)
* 5 accepted in the v2 cohort

Exit code
---------

0  — every expected count matches.
1  — any mismatch, missing field, or malformed ledger.

Read-only: no DB, no provider, no LLM, no artifact write.

CLI
---

::

    python scripts/selection_funnel_summary.py \\
        --ledger examples/selection_funnel_ledger.yaml --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional, Sequence


_DEFAULT_LEDGER: str = "examples/selection_funnel_ledger.yaml"

_VALID_GATE_STAGES: frozenset[str] = frozenset({
    "planning", "date_sanity", "provider_preview",
    "temp_validation", "corrected_validation", "accepted_v2",
})
_VALID_OUTCOMES: frozenset[str] = frozenset({
    "accepted", "rejected", "blocked", "backup",
    "corrected_original_failed",
})
_VALID_RESULT_CODES: frozenset[str] = frozenset({
    "PASS", "FAIL_WRONG_SIGN", "FAIL_DATE_ERROR", "N/A",
})

_REQUIRED_FIELDS: tuple[str, ...] = (
    "candidate_id", "event_name", "primary_ticker", "benchmark_ticker",
    "gate_stage", "outcome", "result_code",
)

# Expected disclosure numbers — match the v2.1 artifact's
# selection_bias_disclosure section.
_EXPECTED_TOTAL_MIN:               int = 18
_EXPECTED_TOTAL_MAX:               int = 22
_EXPECTED_VALIDATION_RUNS:         int = 8
_EXPECTED_PASS_COUNT:              int = 4
_EXPECTED_FAIL_COUNT:              int = 4
_EXPECTED_DATE_ERROR_COUNT:        int = 3
_EXPECTED_WRONG_SIGN_AT_VAL:       int = 1
_EXPECTED_PROVIDER_BLOCKED_COUNT:  int = 2
_EXPECTED_V2_QUEUE_SIZE:           int = 5


# ---------------------------------------------------------------------------
# Ledger loader
# ---------------------------------------------------------------------------


def load_ledger(path: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Return ``(candidates, errors)``. Mirrors the
    ``curated_event_loader`` shape: empty list + non-empty errors on
    any structural problem; caller decides how to react.
    """
    errors: list[str] = []
    p = Path(path)
    if not p.exists():
        errors.append(f"ledger YAML not found: {path}")
        return [], errors
    try:
        import yaml as _yaml
    except ImportError:
        errors.append("PyYAML not installed; cannot parse ledger YAML")
        return [], errors
    try:
        with p.open("r", encoding="utf-8") as fh:
            raw = _yaml.safe_load(fh)
    except _yaml.YAMLError as exc:
        errors.append(f"failed to parse ledger {path}: {exc}")
        return [], errors
    except OSError as exc:
        errors.append(f"failed to read ledger {path}: {exc}")
        return [], errors
    if raw is None:
        return [], errors
    if not isinstance(raw, dict) or "candidates" not in raw:
        errors.append("ledger YAML must have a top-level 'candidates:' key")
        return [], errors
    candidates_raw = raw["candidates"]
    if not isinstance(candidates_raw, list):
        errors.append("'candidates' must be a list")
        return [], errors
    out: list[dict[str, Any]] = []
    for i, entry in enumerate(candidates_raw):
        if not isinstance(entry, dict):
            errors.append(
                f"candidate entry {i} is not a mapping "
                f"(got {type(entry).__name__})",
            )
            continue
        out.append(dict(entry))
    return out, errors


def validate_entries(candidates: list[dict[str, Any]]) -> list[str]:
    """Return a list of human-readable validation errors. Empty list
    means every entry has required fields with values from the
    closed vocabularies.
    """
    errors: list[str] = []
    ids_seen: set[str] = set()
    for i, c in enumerate(candidates):
        for f in _REQUIRED_FIELDS:
            if f not in c:
                errors.append(
                    f"candidate index {i} missing required field '{f}'",
                )
        cid = c.get("candidate_id")
        if cid in ids_seen:
            errors.append(f"duplicate candidate_id: {cid}")
        elif cid is not None:
            ids_seen.add(cid)
        gs = c.get("gate_stage")
        if gs is not None and gs not in _VALID_GATE_STAGES:
            errors.append(
                f"candidate {cid}: gate_stage '{gs}' not in "
                f"{sorted(_VALID_GATE_STAGES)}",
            )
        oc = c.get("outcome")
        if oc is not None and oc not in _VALID_OUTCOMES:
            errors.append(
                f"candidate {cid}: outcome '{oc}' not in "
                f"{sorted(_VALID_OUTCOMES)}",
            )
        rc = c.get("result_code")
        if rc is not None and rc not in _VALID_RESULT_CODES:
            errors.append(
                f"candidate {cid}: result_code '{rc}' not in "
                f"{sorted(_VALID_RESULT_CODES)}",
            )
    return errors


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def compute_summary(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute funnel counts. Pure function over the ledger entries."""
    by_outcome: dict[str, int] = {o: 0 for o in _VALID_OUTCOMES}
    by_gate_stage: dict[str, int] = {g: 0 for g in _VALID_GATE_STAGES}
    by_result_code: dict[str, int] = {r: 0 for r in _VALID_RESULT_CODES}
    for c in candidates:
        oc = c.get("outcome")
        if oc in by_outcome:
            by_outcome[oc] += 1
        gs = c.get("gate_stage")
        if gs in by_gate_stage:
            by_gate_stage[gs] += 1
        rc = c.get("result_code")
        if rc in by_result_code:
            by_result_code[rc] += 1

    validation_runs = (
        by_gate_stage["temp_validation"]
        + by_gate_stage["corrected_validation"]
    )
    validation_pass = by_result_code["PASS"]
    validation_fail = (
        by_result_code["FAIL_WRONG_SIGN"]
        + by_result_code["FAIL_DATE_ERROR"]
    )
    date_error_count = by_result_code["FAIL_DATE_ERROR"]
    # Wrong-sign rejections that landed at temp_validation specifically
    # (FSLR Section 201's wrong-sign mechanism was caught earlier, at
    # date_sanity — it should NOT count toward "wrong-sign at validation").
    wrong_sign_at_validation = sum(
        1 for c in candidates
        if c.get("result_code") == "FAIL_WRONG_SIGN"
        and c.get("gate_stage") == "temp_validation"
    )
    provider_blocked = sum(
        1 for c in candidates
        if c.get("outcome") == "blocked"
        and c.get("gate_stage") == "provider_preview"
    )
    v2_queue_size = by_outcome["accepted"]

    return {
        "total_candidates":              len(candidates),
        "by_outcome":                    by_outcome,
        "by_gate_stage":                 by_gate_stage,
        "by_result_code":                by_result_code,
        "validation_runs":               validation_runs,
        "validation_pass_count":         validation_pass,
        "validation_fail_count":         validation_fail,
        "date_error_count":              date_error_count,
        "wrong_sign_at_validation_count": wrong_sign_at_validation,
        "provider_blocked_count":        provider_blocked,
        "v2_queue_size":                 v2_queue_size,
    }


# ---------------------------------------------------------------------------
# Audit against v2 disclosure
# ---------------------------------------------------------------------------


def check_against_v2_expectations(
    summary: dict[str, Any],
) -> dict[str, Any]:
    """Return per-check pass/fail flags and overall ``all_pass``.

    The expected numbers are baked-in constants matching the v2.1
    artifact's selection_bias_disclosure section. If the ledger ever
    needs to disagree with the artifact (e.g., the operator adds new
    candidates to the queue mid-cycle), bump these constants together
    with the artifact's disclosure.
    """
    total = summary["total_candidates"]
    total_in_range = _EXPECTED_TOTAL_MIN <= total <= _EXPECTED_TOTAL_MAX
    checks = {
        "total_candidates_in_range": {
            "expected_min":   _EXPECTED_TOTAL_MIN,
            "expected_max":   _EXPECTED_TOTAL_MAX,
            "actual":         total,
            "ok":             total_in_range,
        },
        "validation_runs_match_8": {
            "expected":   _EXPECTED_VALIDATION_RUNS,
            "actual":     summary["validation_runs"],
            "ok":         summary["validation_runs"] == _EXPECTED_VALIDATION_RUNS,
        },
        "pass_count_match_4": {
            "expected":   _EXPECTED_PASS_COUNT,
            "actual":     summary["validation_pass_count"],
            "ok":         summary["validation_pass_count"] == _EXPECTED_PASS_COUNT,
        },
        "fail_count_match_4": {
            "expected":   _EXPECTED_FAIL_COUNT,
            "actual":     summary["validation_fail_count"],
            "ok":         summary["validation_fail_count"] == _EXPECTED_FAIL_COUNT,
        },
        "date_error_count_match_3": {
            "expected":   _EXPECTED_DATE_ERROR_COUNT,
            "actual":     summary["date_error_count"],
            "ok":         summary["date_error_count"] == _EXPECTED_DATE_ERROR_COUNT,
        },
        "wrong_sign_at_validation_match_1": {
            "expected":   _EXPECTED_WRONG_SIGN_AT_VAL,
            "actual":     summary["wrong_sign_at_validation_count"],
            "ok":         summary["wrong_sign_at_validation_count"] == _EXPECTED_WRONG_SIGN_AT_VAL,
        },
        "provider_blocked_match_2": {
            "expected":   _EXPECTED_PROVIDER_BLOCKED_COUNT,
            "actual":     summary["provider_blocked_count"],
            "ok":         summary["provider_blocked_count"] == _EXPECTED_PROVIDER_BLOCKED_COUNT,
        },
        "v2_queue_match_5": {
            "expected":   _EXPECTED_V2_QUEUE_SIZE,
            "actual":     summary["v2_queue_size"],
            "ok":         summary["v2_queue_size"] == _EXPECTED_V2_QUEUE_SIZE,
        },
    }
    all_pass = all(v["ok"] for v in checks.values())
    return {"all_pass": all_pass, "checks": checks}


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


def run_all(ledger_path: str) -> dict[str, Any]:
    candidates, load_errors = load_ledger(ledger_path)
    validation_errors = validate_entries(candidates) if candidates else []
    if load_errors or validation_errors:
        return {
            "ok":            False,
            "ledger_path":   ledger_path,
            "load_errors":   load_errors,
            "validation_errors": validation_errors,
        }
    summary = compute_summary(candidates)
    audit = check_against_v2_expectations(summary)
    return {
        "ok":             audit["all_pass"],
        "ledger_path":    ledger_path,
        "summary":        summary,
        "audit":          audit,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize the v2 selection-funnel ledger and audit "
            "against the v2 artifact's disclosure numbers. Exit "
            "non-zero on any ledger-vs-disclosure mismatch."
        ),
    )
    parser.add_argument(
        "--ledger", default=_DEFAULT_LEDGER,
        help=f"Path to the ledger YAML. Default: {_DEFAULT_LEDGER}",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Emit structured JSON instead of a text summary.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    result = run_all(args.ledger)
    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        ok = result.get("ok")
        flag = "PASS" if ok else "FAIL"
        print(f"funnel ledger audit: {flag}")
        if result.get("load_errors"):
            print("  load errors:")
            for e in result["load_errors"]:
                print(f"    - {e}")
        if result.get("validation_errors"):
            print("  validation errors:")
            for e in result["validation_errors"]:
                print(f"    - {e}")
        if "summary" in result:
            s = result["summary"]
            print(
                f"  total={s['total_candidates']} "
                f"v2_queue={s['v2_queue_size']} "
                f"validation_runs={s['validation_runs']} "
                f"pass={s['validation_pass_count']} "
                f"fail={s['validation_fail_count']} "
                f"date_err={s['date_error_count']} "
                f"wrong_sign={s['wrong_sign_at_validation_count']} "
                f"blocked={s['provider_blocked_count']}"
            )
        if "audit" in result:
            for name, body in result["audit"]["checks"].items():
                f = "PASS" if body["ok"] else "FAIL"
                print(f"  [{f}] {name}: actual={body['actual']}")
    return 0 if result.get("ok") else 1


__all__ = (
    "load_ledger",
    "validate_entries",
    "compute_summary",
    "check_against_v2_expectations",
    "run_all",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
