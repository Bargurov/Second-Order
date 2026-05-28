#!/usr/bin/env python3
"""Sanitized rejection-log summary validator.

Validates the tracked sanitized rejection summary at
``demo_artifacts/section_c_v2/rejection_log_summary_v1.json`` against
the public-summary schema.  Read-only by construction: opens the
artifact, walks its structure, and emits a structured ``ok`` /
``errors`` / ``warnings`` envelope.  The artifact file itself is never
mutated.

What the validator checks
-------------------------

1. The input is a JSON object with a ``summary`` object and an
   ``identifiable_rejections`` list.
2. ``summary.identifiable_rejections_count`` equals
   ``len(identifiable_rejections)``.
3. No item in ``identifiable_rejections`` carries the operator-only
   fields ``reason_note`` or ``source_files`` (those live in the
   local-only operator log, not the tracked summary).
4. ``summary.decision_counts``, ``summary.stage_counts``, and
   ``summary.reason_category_counts`` each match the actual counts
   built from the entries (multiset equality, zero-valued bins
   tolerated).
5. Per-ticker invariants pinned by the demo narrative:
   * CENX, NUE, NOC entries (if present) must each carry
     ``decision == "deferred_methodology_lesson"``.
   * The AMAT entry (if present) must be a Phase-2 pool failure:
     ``decision == "rejected"``,
     ``stage == "post_screen_canonical_test"``,
     ``reason_category == "g5_not_significant"``, and
     ``phase2_pool_count == True``.
6. No statistics / returns / p-value tokens leak into the tracked
   summary.  This is enforced two ways:
   * No item or summary object may carry a forbidden numeric field
     (e.g. ``p_value``, ``t_stat``, ``z_score``, ``cumulative_return``,
     ``car``, ``sar``, ``effect_size``) -- those belong in the local
     operator log, not the public summary.
   * No string value (``notes``, etc.) may contain stat-shaped tokens
     (``p-value``, ``t-stat``, ``z-score``, ``cumulative return``,
     ``abnormal return``).
7. No forbidden overclaim language:
   ``proof``, ``proven``, ``validated``, ``alpha``, ``prediction``,
   ``predicted`` (word-bounded, case-insensitive).

Read-only by construction
-------------------------

* No DB reads or writes.  The single input is one JSON file path
  supplied via ``--artifact``.
* No provider / yfinance / market_data / price_cache.fetch_*; no
  LLM; no FastAPI surface (never imports ``api`` / ``routes.*``).
* The artifact file is opened in read-mode only.  Byte identity is
  preserved across a validation run.
* The validator describes schema compliance only; it never makes
  claims about the underlying rejection's mechanism or statistical
  result.

Output contract (JSON)::

    {
      "ok":                              bool,
      "artifact_path":                   str,
      "identifiable_rejections_count":   int,
      "errors":                          list[str],
      "warnings":                        list[str],
    }

``ok`` is True iff ``errors`` is empty.

Usage::

    python scripts/validate_rejection_log_summary.py \\
        --artifact demo_artifacts/section_c_v2/rejection_log_summary_v1.json
    python scripts/validate_rejection_log_summary.py \\
        --artifact demo_artifacts/section_c_v2/rejection_log_summary_v1.json \\
        --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------


# Forbidden item-level keys that would leak operator-only context.
_FORBIDDEN_OPERATOR_KEYS: frozenset[str] = frozenset({
    "reason_note",
    "source_files",
})


# Forbidden statistics / returns keys anywhere in the tracked summary.
# These belong in the local-only operator log, not the public artifact.
_FORBIDDEN_STATS_KEYS: frozenset[str] = frozenset({
    "p_value",
    "pvalue",
    "p_val",
    "raw_p",
    "raw_p_value",
    "fdr_q",
    "q_value",
    "t_stat",
    "tstat",
    "t_statistic",
    "t_value",
    "z_score",
    "z_stat",
    "z_value",
    "f_stat",
    "f_statistic",
    "test_statistic",
    "statistic",
    "cumulative_return",
    "mean_return",
    "median_return",
    "abnormal_return",
    "ar",
    "sar",
    "car",
    "effect_size",
    "sharpe",
    "sharpe_ratio",
})


# Forbidden overclaim language tokens (word-bounded, case-insensitive).
_FORBIDDEN_LANGUAGE_TOKENS: tuple[str, ...] = (
    "proof",
    "proven",
    "validated",
    "alpha",
    "prediction",
    "predicted",
)


# Statistical phrases that may sneak into prose even when no numeric
# field is present.
_FORBIDDEN_STAT_PHRASE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bp[-_\s]?value(s)?\b", re.IGNORECASE),
    re.compile(r"\bt[-_\s]?stat(istic)?s?\b", re.IGNORECASE),
    re.compile(r"\bz[-_\s]?(score|stat)s?\b", re.IGNORECASE),
    re.compile(r"\bcumulative\s+returns?\b", re.IGNORECASE),
    re.compile(r"\babnormal\s+returns?\b", re.IGNORECASE),
    re.compile(r"\bsharpe\s+ratio\b", re.IGNORECASE),
)


# Decisions / stages / reason categories pinned by the demo narrative.
_DEFERRED_TICKERS: tuple[str, ...] = ("CENX", "NUE", "NOC")
_AMAT_REQUIRED_FIELDS: dict[str, Any] = {
    "decision":        "rejected",
    "stage":           "post_screen_canonical_test",
    "reason_category": "g5_not_significant",
    "phase2_pool_count": True,
}


# ---------------------------------------------------------------------------
# Walking helpers
# ---------------------------------------------------------------------------


def _iter_string_values(node: Any) -> Iterable[tuple[str, str]]:
    """Yield ``(json_pointer, string_value)`` pairs for every str leaf.

    Used to scan all prose in the summary for forbidden language and
    forbidden stat-shaped tokens without picking false positives out
    of key names.
    """
    stack: list[tuple[str, Any]] = [("$", node)]
    while stack:
        ptr, value = stack.pop()
        if isinstance(value, str):
            yield ptr, value
        elif isinstance(value, dict):
            for k, v in value.items():
                stack.append((f"{ptr}.{k}", v))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                stack.append((f"{ptr}[{i}]", v))
        # numeric / bool / null: not interesting for prose scans


def _iter_keys(node: Any) -> Iterable[tuple[str, str]]:
    """Yield ``(json_pointer_of_owner, key_name)`` pairs for every dict
    key encountered anywhere in the tree."""
    stack: list[tuple[str, Any]] = [("$", node)]
    while stack:
        ptr, value = stack.pop()
        if isinstance(value, dict):
            for k, v in value.items():
                yield ptr, k
                stack.append((f"{ptr}.{k}", v))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                stack.append((f"{ptr}[{i}]", v))


# ---------------------------------------------------------------------------
# Per-section checks
# ---------------------------------------------------------------------------


def _check_top_level_shape(
    payload: Any,
    errors: list[str],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None]:
    """Validate the top-level shape and return ``(summary, items)``."""
    if not isinstance(payload, dict):
        errors.append(
            "artifact root must be a JSON object, got "
            f"{type(payload).__name__}"
        )
        return None, None

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        errors.append(
            "'summary' must be a JSON object, got "
            f"{type(summary).__name__}"
        )
        summary = None

    items = payload.get("identifiable_rejections")
    if not isinstance(items, list):
        errors.append(
            "'identifiable_rejections' must be a JSON array, got "
            f"{type(items).__name__}"
        )
        items = None
    else:
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(
                    f"identifiable_rejections[{idx}] must be a JSON "
                    f"object, got {type(item).__name__}"
                )

    return summary, items


def _check_identifiable_count(
    summary: dict[str, Any],
    items: list[dict[str, Any]],
    errors: list[str],
) -> None:
    declared = summary.get("identifiable_rejections_count")
    actual = len(items)
    if declared != actual:
        errors.append(
            f"summary.identifiable_rejections_count = {declared!r} "
            f"but len(identifiable_rejections) = {actual}"
        )


def _check_operator_only_keys_absent(
    items: list[dict[str, Any]],
    errors: list[str],
) -> None:
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        for forbidden in _FORBIDDEN_OPERATOR_KEYS:
            if forbidden in item:
                ticker = item.get("primary_ticker", "<unknown>")
                errors.append(
                    f"identifiable_rejections[{idx}]({ticker}) "
                    f"carries operator-only field {forbidden!r}; this "
                    f"belongs in the local operator log, not the "
                    f"tracked public summary"
                )


def _check_stats_keys_absent(
    payload: dict[str, Any],
    errors: list[str],
) -> None:
    for owner_ptr, key_name in _iter_keys(payload):
        if key_name.lower() in _FORBIDDEN_STATS_KEYS:
            errors.append(
                f"{owner_ptr}.{key_name}: forbidden statistics/returns "
                f"field {key_name!r} leaked into tracked summary; "
                f"stats live in the local operator log only"
            )


def _check_forbidden_language(
    payload: dict[str, Any],
    errors: list[str],
) -> None:
    # Pre-build word-bounded patterns once per token.
    token_patterns = [
        (token, re.compile(rf"\b{re.escape(token)}\b", re.IGNORECASE))
        for token in _FORBIDDEN_LANGUAGE_TOKENS
    ]
    for ptr, text in _iter_string_values(payload):
        for token, pat in token_patterns:
            if pat.search(text):
                errors.append(
                    f"{ptr}: forbidden overclaim token {token!r} in "
                    f"tracked summary text {text!r}"
                )


def _check_forbidden_stat_phrases(
    payload: dict[str, Any],
    errors: list[str],
) -> None:
    for ptr, text in _iter_string_values(payload):
        for pat in _FORBIDDEN_STAT_PHRASE_PATTERNS:
            m = pat.search(text)
            if m:
                errors.append(
                    f"{ptr}: forbidden statistics phrase {m.group(0)!r} "
                    f"in tracked summary text {text!r}; stats belong "
                    f"in the local operator log only"
                )


def _check_counts(
    summary: dict[str, Any],
    items: list[dict[str, Any]],
    errors: list[str],
) -> None:
    spec = (
        ("decision_counts",        "decision"),
        ("stage_counts",           "stage"),
        ("reason_category_counts", "reason_category"),
    )
    for summary_key, item_field in spec:
        declared = summary.get(summary_key)
        if not isinstance(declared, dict):
            errors.append(
                f"summary.{summary_key} must be a JSON object, got "
                f"{type(declared).__name__}"
            )
            continue
        actual: Counter[str] = Counter(
            str(item.get(item_field))
            for item in items
            if isinstance(item, dict) and item.get(item_field) is not None
        )
        # Drop zero-valued bins from declared for multiset comparison.
        declared_nonzero = {
            str(k): v for k, v in declared.items() if v != 0
        }
        if dict(actual) != declared_nonzero:
            errors.append(
                f"summary.{summary_key} = {declared!r} does not match "
                f"counts built from identifiable_rejections "
                f"({dict(actual)!r})"
            )


def _check_per_ticker_invariants(
    items: list[dict[str, Any]],
    errors: list[str],
) -> None:
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        ticker = item.get("primary_ticker")
        if ticker in _DEFERRED_TICKERS:
            decision = item.get("decision")
            if decision != "deferred_methodology_lesson":
                errors.append(
                    f"identifiable_rejections[{idx}]({ticker}): "
                    f"decision must be 'deferred_methodology_lesson', "
                    f"got {decision!r}"
                )
        if ticker == "AMAT":
            for field, expected in _AMAT_REQUIRED_FIELDS.items():
                actual = item.get(field, _MISSING)
                if actual is _MISSING:
                    errors.append(
                        f"identifiable_rejections[{idx}](AMAT): "
                        f"missing required field {field!r} "
                        f"(expected {expected!r}); AMAT is the "
                        f"Phase-2 pool failure pinned by the demo "
                        f"narrative"
                    )
                elif actual != expected:
                    errors.append(
                        f"identifiable_rejections[{idx}](AMAT): "
                        f"{field} must be {expected!r}, got "
                        f"{actual!r}"
                    )


_MISSING = object()


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_validate_rejection_log_summary(
    *,
    artifact_path: str | None = None,
) -> dict[str, Any]:
    """Validate one rejection-log summary artifact.

    See module docstring for the full output contract.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not artifact_path:
        errors.append(
            "--artifact is required: pass the path to a "
            "rejection_log_summary JSON artifact"
        )
        return _envelope(
            artifact_path=artifact_path or "",
            identifiable_rejections_count=0,
            errors=errors,
            warnings=warnings,
        )

    path = Path(artifact_path)
    if not path.exists():
        errors.append(
            f"artifact path does not exist on disk: {artifact_path!r}"
        )
        return _envelope(
            artifact_path=artifact_path,
            identifiable_rejections_count=0,
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
            identifiable_rejections_count=0,
            errors=errors,
            warnings=warnings,
        )

    summary, items = _check_top_level_shape(payload, errors)
    items_for_count = items if isinstance(items, list) else []
    item_count = sum(
        1 for it in items_for_count if isinstance(it, dict)
    )

    if isinstance(summary, dict) and isinstance(items, list):
        _check_identifiable_count(summary, items, errors)
        _check_counts(summary, items, errors)

    if isinstance(items, list):
        _check_operator_only_keys_absent(items, errors)
        _check_per_ticker_invariants(items, errors)

    if isinstance(payload, dict):
        _check_stats_keys_absent(payload, errors)
        _check_forbidden_language(payload, errors)
        _check_forbidden_stat_phrases(payload, errors)

    return _envelope(
        artifact_path=artifact_path,
        identifiable_rejections_count=item_count,
        errors=errors,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def _envelope(
    *,
    artifact_path: str,
    identifiable_rejections_count: int,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "ok":                            not errors,
        "artifact_path":                 artifact_path,
        "identifiable_rejections_count": identifiable_rejections_count,
        "errors":                        errors,
        "warnings":                      warnings,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "Rejection-log summary validator",
        "",
        f"OK:                              {report['ok']}",
        f"Artifact path:                   {report['artifact_path']}",
        f"Identifiable rejections count:   "
        f"{report['identifiable_rejections_count']}",
    ]
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
            "Read-only validator for the tracked sanitized "
            "rejection_log_summary artifact. Confirms the summary "
            "counts agree with the entries, that operator-only "
            "fields (reason_note, source_files) and statistics fields "
            "have not leaked into the tracked surface, and that the "
            "per-ticker invariants pinned by the demo narrative "
            "(CENX/NUE/NOC deferred, AMAT Phase-2 pool failure) "
            "still hold."
        ),
    )
    parser.add_argument(
        "--artifact",
        dest="artifact_path",
        required=True,
        help=(
            "Required path to a rejection_log_summary JSON artifact. "
            "Read-only; the validator opens this file in read mode "
            "only."
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
    report = run_validate_rejection_log_summary(
        artifact_path=args.artifact_path,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_validate_rejection_log_summary",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
