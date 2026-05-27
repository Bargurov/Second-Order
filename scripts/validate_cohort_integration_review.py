#!/usr/bin/env python3
"""Cohort-integration-review block schema validator.

Validates a per-candidate ``cohort_integration_review`` block (or an
expansion-batch artifact that embeds one or more such blocks) against
the eight-gate rule defined in
``docs/expansion_cohort_integration_rule.md``.  Read-only by
construction: opens the artifact, walks its structure, and emits a
structured ``ok`` / ``errors`` / ``warnings`` envelope.  The artifact
file itself is never mutated.

What the validator checks
-------------------------

1. The input is a JSON object.
2. The input contains one or more ``cohort_integration_review`` blocks.
   Accepted shapes:

   * Standalone block: the top-level object has ``gates`` and
     ``graduation_decision`` keys.
   * Embedded blocks: the top-level object has a
     ``cohort_integration_review`` key whose value is either a single
     block or a list of blocks.

3. Per-block schema:

   * All eight required gate names are present in ``gates``:
     ``G1_source_quality``, ``G2_ticker_benchmark``,
     ``G3_direction_pretest``, ``G4_not_result_selected``,
     ``G5_fdr_significant``, ``G6_horizon_defensible``,
     ``G7_no_confound``, ``G8_interview_defensible`` (identifier
     preserved across v0.1 -> v1 for schema stability; v1 wording is
     "operator can defensibly explain the mechanism").
   * Each gate is an object with an ``answer`` field equal to ``yes``
     or ``no``.
   * If ``answer == "no"``, the ``note`` field must be a non-empty
     string.
   * If ``G7_no_confound.answer == "yes"``, both ``pre_test_note`` and
     ``post_test_note`` must be non-empty strings.
   * Unknown gate names produce warnings, not errors (the schema is
     deliberately tolerant of additive evolution).

4. Aggregation correctness:

   * ``graduation_decision`` is one of ``graduate``, ``hold``,
     ``reject``.
   * If all eight required gates answer ``yes``,
     ``graduation_decision`` must equal ``graduate``.
   * If any required gate answers ``no``, ``graduation_decision`` must
     not equal ``graduate``.
   * If ``graduation_decision == "graduate"`` and
     ``graduation_status == "with_caveat"``, the ``borderline_gate``
     field must be set to one of the eight required gate names.

5. Anti-hindsight invariants (warning-level, heuristic):

   * ``G5_fdr_significant.note`` should declare ``horizon=N`` where N
     is in the pre-registered set {1, 5, 20}.  An out-of-set horizon
     is an error.  A missing ``horizon=N`` declaration is a warning.
   * ``G6_horizon_defensible.note`` should reference a horizon and be
     at least 20 characters; otherwise a warning is emitted.

6. Metadata:

   * ``reviewer`` must be a non-empty string.
   * ``reviewed_at`` must be a non-empty string parseable as ISO date
     (YYYY-MM-DD or full ISO 8601).

7. v1 advisory fields (warning-level only, by design of the v1 rule):

   * ``event_anchor_date``, ``first_tradable_reaction_date``,
     ``mechanism_family``, ``predicted_direction``, ``rule_version``,
     ``rule_commit_sha`` produce a warning when missing.  v0.1-shaped
     blocks remain valid in v1; a future v2 validator may upgrade
     these to errors once the fields have been used in one full
     expansion round.

Read-only by construction
-------------------------

* No DB reads or writes.  The single input is one JSON file path
  supplied via ``--artifact``.
* No provider / yfinance / market_data / price_cache.fetch_*; no
  LLM; no FastAPI surface (never imports ``api`` / ``routes.*``).
* The artifact file is opened in read-mode only.  Byte identity is
  preserved across a validation run.
* The validator describes schema compliance only; it never makes
  claims about the underlying candidate's mechanism, statistical
  result, or graduation worthiness.

Output contract (JSON)::

    {
      "ok":             bool,    # True iff errors is empty
      "artifact_path":  str,     # echoes the supplied path
      "blocks_count":   int,     # number of blocks discovered; 0 on
                                 # missing / malformed / empty input
      "errors":         list[str],
      "warnings":       list[str],
    }

Usage::

    python scripts/validate_cohort_integration_review.py \\
        --artifact path/to/block.json
    python scripts/validate_cohort_integration_review.py \\
        --artifact path/to/block.json --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_REQUIRED_GATE_NAMES: tuple[str, ...] = (
    "G1_source_quality",
    "G2_ticker_benchmark",
    "G3_direction_pretest",
    "G4_not_result_selected",
    "G5_fdr_significant",
    "G6_horizon_defensible",
    "G7_no_confound",
    "G8_interview_defensible",
)


_VALID_GRADUATION_DECISIONS: frozenset[str] = frozenset({
    "graduate",
    "hold",
    "reject",
})


_VALID_GRADUATION_STATUSES: frozenset[str] = frozenset({
    "clean",
    "with_caveat",
})


_PREREGISTERED_HORIZONS: tuple[int, ...] = (1, 5, 20)


# v1 advisory fields. Missing -> warning (not error). A future v2
# validator may upgrade these to required.
_V1_ADVISORY_FIELDS: tuple[str, ...] = (
    "event_anchor_date",
    "first_tradable_reaction_date",
    "mechanism_family",
    "predicted_direction",
    "rule_version",
    "rule_commit_sha",
)


_G5_HORIZON_PATTERN = re.compile(r"horizon\s*=\s*(\d+)")
_G6_HORIZON_REF_PATTERN = re.compile(
    r"\b(?:h\s*=\s*\d+|horizon)\b", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Block extraction
# ---------------------------------------------------------------------------


def _extract_blocks(payload: Any) -> list[dict[str, Any]]:
    """Return the list of cohort_integration_review blocks in the input.

    Supports two shapes:

    1. Standalone block: payload itself has ``gates`` and
       ``graduation_decision`` keys.
    2. Embedded under a ``cohort_integration_review`` key whose value
       is a single block or a list of blocks.
    """
    if not isinstance(payload, dict):
        return []
    if "gates" in payload and "graduation_decision" in payload:
        return [payload]
    if "cohort_integration_review" in payload:
        embedded = payload["cohort_integration_review"]
        if isinstance(embedded, list):
            return [b for b in embedded if isinstance(b, dict)]
        if isinstance(embedded, dict):
            return [embedded]
    return []


# ---------------------------------------------------------------------------
# Per-block checks
# ---------------------------------------------------------------------------


def _check_gates(
    block: dict[str, Any],
    block_label: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    gates = block.get("gates")
    if not isinstance(gates, dict):
        errors.append(
            f"{block_label}: gates must be a JSON object, got "
            f"{type(gates).__name__}"
        )
        return

    # Required gate presence -> error
    for required in _REQUIRED_GATE_NAMES:
        if required not in gates:
            errors.append(
                f"{block_label}: gates missing required entry "
                f"{required!r}"
            )

    # Unknown gate names -> warning (additive evolution tolerated)
    for gate_name in gates:
        if gate_name not in _REQUIRED_GATE_NAMES:
            warnings.append(
                f"{block_label}: gates contains unknown entry "
                f"{gate_name!r}"
            )

    # Per-gate field validation
    for gate_name, gate_data in gates.items():
        if not isinstance(gate_data, dict):
            errors.append(
                f"{block_label}: gates[{gate_name!r}] must be a JSON "
                f"object, got {type(gate_data).__name__}"
            )
            continue

        answer = gate_data.get("answer")
        if answer not in ("yes", "no"):
            errors.append(
                f"{block_label}: gates[{gate_name!r}].answer must be "
                f"'yes' or 'no', got {answer!r}"
            )
            continue

        # 'no' answers require a non-empty note
        if answer == "no":
            note = gate_data.get("note", "")
            if not isinstance(note, str) or not note.strip():
                errors.append(
                    f"{block_label}: gates[{gate_name!r}] answered "
                    f"'no' must carry a non-empty 'note' explaining "
                    f"the failure"
                )

        # G7 special case: both pre_test_note and post_test_note
        # required when answer == 'yes'
        if gate_name == "G7_no_confound" and answer == "yes":
            pre = gate_data.get("pre_test_note", "")
            post = gate_data.get("post_test_note", "")
            if not isinstance(pre, str) or not pre.strip():
                errors.append(
                    f"{block_label}: gates['G7_no_confound'] "
                    f"answered 'yes' must carry a non-empty "
                    f"'pre_test_note'"
                )
            if not isinstance(post, str) or not post.strip():
                errors.append(
                    f"{block_label}: gates['G7_no_confound'] "
                    f"answered 'yes' must carry a non-empty "
                    f"'post_test_note'"
                )


def _check_aggregation(
    block: dict[str, Any],
    block_label: str,
    errors: list[str],
) -> None:
    decision = block.get("graduation_decision")
    if decision not in _VALID_GRADUATION_DECISIONS:
        errors.append(
            f"{block_label}: graduation_decision must be one of "
            f"{sorted(_VALID_GRADUATION_DECISIONS)!r}, got "
            f"{decision!r}"
        )
        return

    gates = block.get("gates")
    if not isinstance(gates, dict):
        # gate-schema check will already have flagged this
        return

    # Aggregation rule is defined only over the required gates.
    required_gate_data = {
        name: gates[name]
        for name in _REQUIRED_GATE_NAMES
        if name in gates
    }
    if len(required_gate_data) < len(_REQUIRED_GATE_NAMES):
        # Missing gates already produced errors via _check_gates; skip
        # aggregation check rather than producing a misleading second
        # error.
        return

    all_yes = all(
        isinstance(g, dict) and g.get("answer") == "yes"
        for g in required_gate_data.values()
    )

    if all_yes and decision != "graduate":
        errors.append(
            f"{block_label}: all eight required gates answered 'yes' "
            f"but graduation_decision is {decision!r}; aggregation "
            f"rule requires 'graduate'"
        )
    if not all_yes and decision == "graduate":
        errors.append(
            f"{block_label}: at least one required gate answered "
            f"'no' but graduation_decision is 'graduate'; aggregation "
            f"rule requires 'hold' or 'reject'"
        )

    # graduation_status / borderline_gate (v1 addition)
    status = block.get("graduation_status")
    if status is not None:
        if status not in _VALID_GRADUATION_STATUSES:
            errors.append(
                f"{block_label}: graduation_status must be one of "
                f"{sorted(_VALID_GRADUATION_STATUSES)!r}, got "
                f"{status!r}"
            )
        elif status == "with_caveat" and decision == "graduate":
            borderline = block.get("borderline_gate")
            if (
                not isinstance(borderline, str)
                or borderline not in _REQUIRED_GATE_NAMES
            ):
                errors.append(
                    f"{block_label}: graduation_status 'with_caveat' "
                    f"requires 'borderline_gate' to name one of the "
                    f"eight required gates, got {borderline!r}"
                )


def _check_anti_hindsight(
    block: dict[str, Any],
    block_label: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    gates = block.get("gates")
    if not isinstance(gates, dict):
        return

    # G5 horizon must be in the pre-registered set
    g5 = gates.get("G5_fdr_significant")
    if isinstance(g5, dict) and g5.get("answer") == "yes":
        note = g5.get("note") if isinstance(g5.get("note"), str) else ""
        match = _G5_HORIZON_PATTERN.search(note)
        if match:
            horizon = int(match.group(1))
            if horizon not in _PREREGISTERED_HORIZONS:
                errors.append(
                    f"{block_label}: G5_fdr_significant note declares "
                    f"horizon={horizon}, which is not in the "
                    f"pre-registered set "
                    f"{list(_PREREGISTERED_HORIZONS)!r}; adding a "
                    f"horizon to chase a candidate is a G6 violation"
                )
        else:
            warnings.append(
                f"{block_label}: G5_fdr_significant note does not "
                f"declare a 'horizon=N' value (expected pattern "
                f"'horizon=1', 'horizon=5', or 'horizon=20')"
            )

    # G6 note: heuristic check that a horizon reference and enough
    # text exist to defend the choice
    g6 = gates.get("G6_horizon_defensible")
    if isinstance(g6, dict) and g6.get("answer") == "yes":
        note = g6.get("note") if isinstance(g6.get("note"), str) else ""
        has_horizon_ref = bool(_G6_HORIZON_REF_PATTERN.search(note))
        if not has_horizon_ref or len(note.strip()) < 20:
            warnings.append(
                f"{block_label}: G6_horizon_defensible note is "
                f"missing a horizon reference or is too short to "
                f"defend the choice (expected a one-sentence "
                f"rationale connecting the horizon to the mechanism)"
            )


def _check_metadata(
    block: dict[str, Any],
    block_label: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    reviewer = block.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        errors.append(
            f"{block_label}: 'reviewer' must be a non-empty string"
        )

    reviewed_at = block.get("reviewed_at")
    if not isinstance(reviewed_at, str) or not reviewed_at.strip():
        errors.append(
            f"{block_label}: 'reviewed_at' must be a non-empty string"
        )
    else:
        parsed = False
        try:
            datetime.fromisoformat(reviewed_at)
            parsed = True
        except ValueError:
            try:
                datetime.strptime(reviewed_at, "%Y-%m-%d")
                parsed = True
            except ValueError:
                parsed = False
        if not parsed:
            errors.append(
                f"{block_label}: 'reviewed_at' value {reviewed_at!r} "
                f"is not parseable as ISO date (expected YYYY-MM-DD "
                f"or full ISO 8601)"
            )

    # v1 advisory fields -> warnings only
    for field_name in _V1_ADVISORY_FIELDS:
        if field_name not in block:
            warnings.append(
                f"{block_label}: v1 advisory field {field_name!r} is "
                f"missing (recommended in rule v1; will be required "
                f"in a future rule version)"
            )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_validate_cohort_integration_review(
    *,
    artifact_path: str | None = None,
) -> dict[str, Any]:
    """Validate one cohort_integration_review artifact.

    See module docstring for the full output contract.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not artifact_path:
        errors.append(
            "--artifact is required: pass the path to a "
            "cohort_integration_review JSON artifact"
        )
        return _envelope(
            artifact_path=artifact_path or "",
            blocks_count=0,
            errors=errors,
            warnings=warnings,
        )

    path = Path(artifact_path)
    if not path.exists():
        errors.append(
            f"artifact path does not exist on disk: "
            f"{artifact_path!r}"
        )
        return _envelope(
            artifact_path=artifact_path,
            blocks_count=0,
            errors=errors,
            warnings=warnings,
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
            blocks_count=0,
            errors=errors,
            warnings=warnings,
        )

    if not isinstance(payload, dict):
        errors.append(
            f"artifact root must be a JSON object, got "
            f"{type(payload).__name__}"
        )
        return _envelope(
            artifact_path=artifact_path,
            blocks_count=0,
            errors=errors,
            warnings=warnings,
        )

    blocks = _extract_blocks(payload)
    if not blocks:
        errors.append(
            "no cohort_integration_review block found in artifact; "
            "expected either a standalone block (with 'gates' and "
            "'graduation_decision' keys) or an artifact with a "
            "'cohort_integration_review' key holding a single block "
            "or a list of blocks"
        )
        return _envelope(
            artifact_path=artifact_path,
            blocks_count=0,
            errors=errors,
            warnings=warnings,
        )

    for idx, block in enumerate(blocks):
        candidate_id = block.get("candidate_id") or "<unspecified>"
        block_label = f"block[{idx}]({candidate_id})"
        _check_gates(block, block_label, errors, warnings)
        _check_aggregation(block, block_label, errors)
        _check_anti_hindsight(block, block_label, errors, warnings)
        _check_metadata(block, block_label, errors, warnings)

    return _envelope(
        artifact_path=artifact_path,
        blocks_count=len(blocks),
        errors=errors,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def _envelope(
    *,
    artifact_path: str,
    blocks_count: int,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "ok":            not errors,
        "artifact_path": artifact_path,
        "blocks_count":  blocks_count,
        "errors":        errors,
        "warnings":      warnings,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "Cohort-integration-review block schema validator",
        "",
    ]
    lines.append(f"OK:               {report['ok']}")
    lines.append(f"Artifact path:    {report['artifact_path']}")
    lines.append(f"Blocks count:     {report['blocks_count']}")
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
            "Read-only cohort_integration_review block schema "
            "validator. Walks the structure of a "
            "cohort_integration_review block (standalone file or "
            "embedded in an expansion-batch artifact) and reports "
            "schema compliance via a structured ok/errors envelope. "
            "The validator never mutates the artifact and emits no "
            "filesystem side effects."
        ),
    )
    parser.add_argument(
        "--artifact",
        dest="artifact_path",
        required=True,
        help=(
            "Required path to a cohort_integration_review JSON "
            "artifact. Read-only; the validator opens this file in "
            "read mode only."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = run_validate_cohort_integration_review(
        artifact_path=args.artifact_path,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_validate_cohort_integration_review",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
