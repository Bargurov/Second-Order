#!/usr/bin/env python3
"""Phase 2 BH/FDR pool artifact schema validator.

Validates a ``demo_artifacts/section_c_v2/phase2_pool_v1.json``-shaped
artifact against the Phase 2 pool schema.  The validator is read-only:
it opens the artifact, walks its structure, and emits a structured
``ok`` / ``errors`` / ``warnings`` envelope.  The artifact file itself
is never mutated.

What the validator checks
-------------------------

1. Pinned top-level identifiers:

   * ``artifact_type == "phase2_pool"``
   * ``schema_version == "v1"``
   * ``pool_id == "phase2_pool_v1"``
   * ``denominator_count == 5`` and matches ``len(candidates)``
   * ``bh_alpha == 0.05``
   * ``fdr_method == "Benjamini-Hochberg"``

2. Exact candidate set — five rows, each
   ``(primary_ticker, benchmark_ticker)`` pair appearing once:

   * BA  / SPY
   * ALB / SPY
   * NVDA / SMH
   * AMAT / SPY
   * CF / SPY

3. Per-candidate flags:

   * ``phase2_pool_count`` is ``True`` for every candidate.

4. BH recompute — derive q-values and discovery flags from the
   ``raw_p`` column using :func:`stats.fdr.bh_adjust` at
   ``alpha=bh_alpha``.  Compare against the stored values within a
   tight numeric tolerance.  Fails when:

   * ``q_bh`` differs from recompute beyond tolerance,
   * ``bh_rank`` (1-indexed, ascending by ``raw_p``) is wrong,
   * ``passes_bh_at_005`` flag is wrong.

   The expected pass set is BA, ALB, NVDA; the expected fail set is
   AMAT, CF.  Both halves are pinned independently of recompute so a
   ``bh_alpha`` drift surfaces as an explicit pass/fail mismatch.

5. References:

   * ``policy_reference ==
     "demo_artifacts/section_c_v2/phase2_fdr_policy_v1.md"``
   * ``phase1_freeze_artifact_reference ==
     "demo_artifacts/section_c_v2/freeze_candidate_evidence.json"``

   Phase 1 q-values are intentionally not recomputed by this
   validator — that scope belongs to the freeze-candidate validator.

6. Banned overclaim language in *prose* fields only.  The scan
   targets free-text description fields, not categorical enums or
   numeric keys.  Forbidden tokens (case-insensitive, word-boundary
   matched so ``bh_alpha`` does not false-positive for ``alpha``):

   ``proof``, ``proven``, ``validated``, ``alpha``, ``prediction``,
   ``predicted``, ``confirms the mechanism``, ``fdr pending``,
   ``hypothetical``.

Read-only by construction
-------------------------

* No DB reads or writes.  Single input is one JSON file path supplied
  via ``--artifact``.
* No provider / yfinance / market_data / price_cache.fetch_*; no
  LLM; no FastAPI surface.
* The artifact file is opened in read-mode only.  Byte identity is
  preserved across a validation run.

Output contract (JSON)::

    {
      "ok":             bool,    # True iff errors is empty
      "artifact_path":  str,     # echoes the supplied path
      "records_count":  int,     # number of candidate rows discovered;
                                 # 0 on missing / malformed / empty input
      "errors":         list[str],
      "warnings":       list[str],
    }

Usage::

    python scripts/validate_phase2_pool.py \\
        --artifact demo_artifacts/section_c_v2/phase2_pool_v1.json
    python scripts/validate_phase2_pool.py \\
        --artifact demo_artifacts/section_c_v2/phase2_pool_v1.json --json
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stats.fdr import bh_adjust   # noqa: E402


# ---------------------------------------------------------------------------
# Pinned constants
# ---------------------------------------------------------------------------


_ARTIFACT_TYPE: str = "phase2_pool"
_SCHEMA_VERSION: str = "v1"
_POOL_ID: str = "phase2_pool_v1"
_DENOMINATOR_COUNT: int = 5
_BH_ALPHA: float = 0.05
_FDR_METHOD: str = "Benjamini-Hochberg"
_POLICY_REFERENCE: str = (
    "demo_artifacts/section_c_v2/phase2_fdr_policy_v1.md"
)
_PHASE1_FREEZE_REFERENCE: str = (
    "demo_artifacts/section_c_v2/freeze_candidate_evidence.json"
)


_REQUIRED_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "artifact_type",
    "schema_version",
    "pool_id",
    "denominator_count",
    "bh_alpha",
    "fdr_method",
    "candidates",
    "policy_reference",
    "phase1_freeze_artifact_reference",
)


_REQUIRED_CANDIDATE_FIELDS: tuple[str, ...] = (
    "candidate_id",
    "primary_ticker",
    "benchmark_ticker",
    "raw_p",
    "bh_rank",
    "q_bh",
    "passes_bh_at_005",
    "phase2_pool_count",
)


# Expected candidate set: (primary_ticker, benchmark_ticker, must_pass).
# Order is the pass-then-fail order the pool publishes; the validator
# does not require this order in the artifact — it requires set equality
# on (primary, benchmark) and pass/fail on each row.
_EXPECTED_CANDIDATES: tuple[tuple[str, str, bool], ...] = (
    ("BA",   "SPY", True),
    ("ALB",  "SPY", True),
    ("NVDA", "SMH", True),
    ("AMAT", "SPY", False),
    ("CF",   "SPY", False),
)


# Forbidden overclaim tokens.  Compared case-insensitive against
# lowercase prose with ``\b`` word boundaries so ``bh_alpha`` does not
# accidentally trip the bare ``alpha`` rule (underscore is part of
# ``\w`` so ``bh_alpha`` is a single word to the regex engine).
_BANNED_TOKENS: tuple[str, ...] = (
    "proof",
    "proven",
    "validated",
    "alpha",
    "prediction",
    "predicted",
    "confirms the mechanism",
    "fdr pending",
    "hypothetical",
)


# Top-level free-text fields scanned for banned tokens.  Categorical
# enum values (e.g. ``phase2_pool_role``) and pinned identifiers
# (``artifact_type``, ``pool_id``, …) are excluded by design.
_PROSE_TOP_LEVEL_FIELDS: tuple[str, ...] = (
    "fdr_method_note",
    "phase1_scope_note",
    "denominator_inclusion_note",
    "claimed_horizon_pool_note",
    "pool_lock_note",
    "downstream_promotion_note",
    "demo_wiring_note",
)


# Per-candidate free-text fields scanned for banned tokens.  Excludes
# ``phase2_pool_role`` (an enum) and ``candidate_id`` (an identifier).
_PROSE_CANDIDATE_FIELDS: tuple[str, ...] = (
    "phase2_pool_role_note",
)


# Numeric tolerance for q_bh recompute.  Spec calls for "tight" — these
# absolute / relative thresholds cover both the smallest stored q
# (~1.6e-7) and the largest (0.161).
_Q_REL_TOL: float = 1e-9
_Q_ABS_TOL: float = 1e-12


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_validate_phase2_pool(
    *,
    artifact_path: str | None = None,
) -> dict[str, Any]:
    """Validate one Phase 2 pool artifact.

    See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    if not artifact_path:
        errors.append(
            "--artifact is required: pass the path to a phase2 pool "
            "JSON artifact"
        )
        return _envelope(artifact_path or "", 0, errors, warnings)

    path = Path(artifact_path)
    if not path.exists():
        errors.append(
            f"artifact path does not exist on disk: {artifact_path!r}"
        )
        return _envelope(artifact_path, 0, errors, warnings)

    try:
        with open(artifact_path, "r", encoding="utf-8") as fh:
            payload: Any = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(
            f"failed to parse artifact as JSON: "
            f"{type(exc).__name__}: {exc}"
        )
        return _envelope(artifact_path, 0, errors, warnings)

    if not isinstance(payload, dict):
        errors.append(
            f"artifact root must be a JSON object, got "
            f"{type(payload).__name__}"
        )
        return _envelope(artifact_path, 0, errors, warnings)

    # Step 1: required top-level keys.
    for key in _REQUIRED_TOP_LEVEL_KEYS:
        if key not in payload:
            errors.append(f"required top-level key missing: {key!r}")

    # Step 2: pinned identifiers.
    _check_pinned_top_level(payload, errors)

    # Step 3: candidates as list, plus per-row schema sanity.
    candidates_raw = payload.get("candidates")
    if "candidates" in payload and not isinstance(candidates_raw, list):
        errors.append(
            f"candidates must be a list, got "
            f"{type(candidates_raw).__name__}"
        )
        candidates: list[dict[str, Any]] = []
    else:
        candidates = candidates_raw or []   # type: ignore[assignment]

    for idx, cand in enumerate(candidates):
        if not isinstance(cand, dict):
            errors.append(
                f"candidates[{idx}] must be a JSON object, got "
                f"{type(cand).__name__}"
            )
            continue
        for field in _REQUIRED_CANDIDATE_FIELDS:
            if field not in cand:
                ticker = cand.get("primary_ticker", f"[{idx}]")
                errors.append(
                    f"candidate {ticker} missing required field {field!r}"
                )

    # Step 4: denominator vs candidate count.
    if "denominator_count" in payload and "candidates" in payload:
        declared = payload.get("denominator_count")
        if isinstance(declared, int) and not isinstance(declared, bool):
            if declared != len(candidates):
                errors.append(
                    f"denominator_count={declared} does not match "
                    f"len(candidates)={len(candidates)}; the pool's "
                    f"declared denominator must equal the number of rows"
                )

    # Step 5: every candidate's phase2_pool_count flag must be True.
    _check_phase2_pool_count(candidates, errors)

    # Step 6: exact candidate set match (by ticker / benchmark pair),
    # plus the per-row pass / fail assignment.
    _check_exact_candidate_set(candidates, errors)

    # Step 7: BH recompute — q_bh, bh_rank, passes_bh_at_005.
    _check_bh_recompute(candidates, payload, errors)

    # Step 8: references.
    _check_references(payload, errors)

    # Step 9: prose banned-token scan.
    _check_banned_tokens(payload, candidates, errors)

    return _envelope(artifact_path, len(candidates), errors, warnings)


# ---------------------------------------------------------------------------
# Per-section checks
# ---------------------------------------------------------------------------


def _check_pinned_top_level(
    payload: dict[str, Any], errors: list[str],
) -> None:
    pins = (
        ("artifact_type",     _ARTIFACT_TYPE),
        ("schema_version",    _SCHEMA_VERSION),
        ("pool_id",           _POOL_ID),
        ("fdr_method",        _FDR_METHOD),
    )
    for key, expected in pins:
        if key in payload and payload[key] != expected:
            errors.append(
                f"{key} must equal {expected!r}, got {payload[key]!r}"
            )

    if "denominator_count" in payload:
        declared = payload["denominator_count"]
        if isinstance(declared, bool) or not isinstance(declared, int):
            errors.append(
                f"denominator_count must be an int, got "
                f"{type(declared).__name__}"
            )
        elif declared != _DENOMINATOR_COUNT:
            errors.append(
                f"denominator_count must equal {_DENOMINATOR_COUNT}, "
                f"got {declared}"
            )

    if "bh_alpha" in payload:
        alpha = payload["bh_alpha"]
        if isinstance(alpha, bool) or not isinstance(alpha, (int, float)):
            errors.append(
                f"bh_alpha must be numeric, got {type(alpha).__name__}"
            )
        elif not math.isclose(
            float(alpha), _BH_ALPHA, rel_tol=_Q_REL_TOL, abs_tol=_Q_ABS_TOL,
        ):
            errors.append(
                f"bh_alpha must equal {_BH_ALPHA}, got {alpha!r}"
            )


def _check_phase2_pool_count(
    candidates: list[Any], errors: list[str],
) -> None:
    for idx, cand in enumerate(candidates):
        if not isinstance(cand, dict):
            continue
        ticker = cand.get("primary_ticker", f"[{idx}]")
        flag = cand.get("phase2_pool_count")
        if flag is not True:
            errors.append(
                f"candidate {ticker} phase2_pool_count must be True, "
                f"got {flag!r}; every row in a closed phase2 pool counts "
                f"in the BH denominator"
            )


def _check_exact_candidate_set(
    candidates: list[Any], errors: list[str],
) -> None:
    expected_pairs: set[tuple[str, str]] = {
        (t, b) for t, b, _ in _EXPECTED_CANDIDATES
    }
    expected_pass: dict[tuple[str, str], bool] = {
        (t, b): p for t, b, p in _EXPECTED_CANDIDATES
    }

    seen_pairs: list[tuple[str, str]] = []
    for idx, cand in enumerate(candidates):
        if not isinstance(cand, dict):
            continue
        primary = cand.get("primary_ticker")
        bench = cand.get("benchmark_ticker")
        if not isinstance(primary, str) or not isinstance(bench, str):
            continue
        seen_pairs.append((primary, bench))

    seen_set = set(seen_pairs)
    missing = expected_pairs - seen_set
    for primary, bench in sorted(missing):
        errors.append(
            f"required candidate missing: {primary} / {bench}; "
            f"phase2_pool_v1 must contain exactly the five tracked rows"
        )

    unexpected = seen_set - expected_pairs
    for primary, bench in sorted(unexpected):
        errors.append(
            f"unexpected candidate present: {primary} / {bench}; "
            f"phase2_pool_v1 must not contain rows outside the closed "
            f"five-row pool"
        )

    # Duplicates within the candidates list.
    duplicates: list[tuple[str, str]] = []
    counts: dict[tuple[str, str], int] = {}
    for pair in seen_pairs:
        counts[pair] = counts.get(pair, 0) + 1
    for pair, n in counts.items():
        if n > 1:
            duplicates.append(pair)
    for primary, bench in sorted(duplicates):
        errors.append(
            f"duplicate candidate: {primary} / {bench} appears more "
            f"than once; phase2_pool_v1 must list each row exactly once"
        )

    # Per-row pass / fail assignment.
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        primary = cand.get("primary_ticker")
        bench = cand.get("benchmark_ticker")
        if not isinstance(primary, str) or not isinstance(bench, str):
            continue
        pair = (primary, bench)
        if pair not in expected_pass:
            continue   # already reported as unexpected above
        want = expected_pass[pair]
        got = cand.get("passes_bh_at_005")
        if got is None:
            continue   # already reported as missing field
        if bool(got) is not want:
            errors.append(
                f"candidate {primary} / {bench} passes_bh_at_005={got!r}; "
                f"expected {want!r} under bh_alpha={_BH_ALPHA}"
            )


def _check_bh_recompute(
    candidates: list[Any],
    payload: dict[str, Any],
    errors: list[str],
) -> None:
    """Recompute BH q-values and ranks from raw_p and compare against
    the stored columns.  Skips rows whose ``raw_p`` is missing or
    non-numeric (those errors were emitted by the schema check)."""
    rows: list[tuple[int, dict[str, Any]]] = []
    for idx, cand in enumerate(candidates):
        if not isinstance(cand, dict):
            continue
        raw_p = cand.get("raw_p")
        if isinstance(raw_p, bool) or not isinstance(raw_p, (int, float)):
            continue
        if not (0.0 <= float(raw_p) <= 1.0):
            errors.append(
                f"candidate {cand.get('primary_ticker', idx)} raw_p "
                f"must be in [0, 1], got {raw_p!r}"
            )
            continue
        rows.append((idx, cand))

    if not rows:
        return

    # Recompute using the artifact's declared bh_alpha when valid, else
    # the spec default.  The pinned-bh_alpha check has already flagged
    # any drift; this picks the artifact's own value so the discovery
    # flags it back match what the pool actually claims.
    alpha = payload.get("bh_alpha", _BH_ALPHA)
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)):
        alpha = _BH_ALPHA
    alpha_f = float(alpha)
    if not (0.0 < alpha_f <= 1.0):
        alpha_f = _BH_ALPHA

    raw_p_values = [float(cand["raw_p"]) for _, cand in rows]
    result = bh_adjust(raw_p_values, alpha=alpha_f)
    adjusted = result["adjusted"]
    discoveries = result["discoveries"]

    # Rank: 1-indexed ascending by raw_p, deterministic tie-break by
    # original list position to match the bh_adjust internal ordering.
    sort_keyed = sorted(
        range(len(raw_p_values)),
        key=lambda i: (raw_p_values[i], i),
    )
    rank_for_local: dict[int, int] = {
        local_idx: rank_zero + 1
        for rank_zero, local_idx in enumerate(sort_keyed)
    }

    for local_idx, (_, cand) in enumerate(rows):
        ticker = cand.get("primary_ticker", f"[{local_idx}]")
        stated_q = cand.get("q_bh")
        recomputed_q = adjusted[local_idx]
        if recomputed_q is None:
            errors.append(
                f"candidate {ticker} raw_p produced no recomputed q_bh "
                f"(unexpected for a valid raw_p)"
            )
        elif not isinstance(stated_q, (int, float)) or isinstance(stated_q, bool):
            errors.append(
                f"candidate {ticker} q_bh must be numeric, got "
                f"{type(stated_q).__name__}"
            )
        elif not math.isclose(
            float(stated_q), float(recomputed_q),
            rel_tol=_Q_REL_TOL, abs_tol=_Q_ABS_TOL,
        ):
            errors.append(
                f"candidate {ticker} q_bh={stated_q!r} disagrees with "
                f"recomputed BH q={recomputed_q!r} (raw_p={cand['raw_p']!r})"
            )

        stated_rank = cand.get("bh_rank")
        recomputed_rank = rank_for_local[local_idx]
        if isinstance(stated_rank, bool) or not isinstance(stated_rank, int):
            errors.append(
                f"candidate {ticker} bh_rank must be an int, got "
                f"{type(stated_rank).__name__}"
            )
        elif stated_rank != recomputed_rank:
            errors.append(
                f"candidate {ticker} bh_rank={stated_rank} disagrees with "
                f"recomputed sort-rank {recomputed_rank} "
                f"(raw_p={cand['raw_p']!r})"
            )

        stated_pass = cand.get("passes_bh_at_005")
        recomputed_pass = bool(discoveries[local_idx])
        if isinstance(stated_pass, bool):
            if stated_pass is not recomputed_pass:
                errors.append(
                    f"candidate {ticker} passes_bh_at_005={stated_pass} "
                    f"disagrees with recomputed BH discovery flag "
                    f"{recomputed_pass} at alpha={alpha_f}"
                )


def _check_references(
    payload: dict[str, Any], errors: list[str],
) -> None:
    if "policy_reference" in payload:
        ref = payload["policy_reference"]
        if ref != _POLICY_REFERENCE:
            errors.append(
                f"policy_reference must equal {_POLICY_REFERENCE!r}, "
                f"got {ref!r}"
            )
    if "phase1_freeze_artifact_reference" in payload:
        ref = payload["phase1_freeze_artifact_reference"]
        if ref != _PHASE1_FREEZE_REFERENCE:
            errors.append(
                f"phase1_freeze_artifact_reference must equal "
                f"{_PHASE1_FREEZE_REFERENCE!r}, got {ref!r}"
            )


def _check_banned_tokens(
    payload: dict[str, Any],
    candidates: list[Any],
    errors: list[str],
) -> None:
    """Scan declared prose fields for banned overclaim language.

    Word-boundary regex matching: ``\\balpha\\b`` does NOT match
    ``bh_alpha`` because underscore is a word character.  Multi-word
    tokens (``confirms the mechanism``) are also wrapped in ``\\b``
    boundaries but their internal spaces match literally.
    """
    for field in _PROSE_TOP_LEVEL_FIELDS:
        val = payload.get(field)
        if isinstance(val, str):
            _scan_text_for_banned(val, f"top-level {field}", errors)

    # summary.summary_language is a nested prose field.
    summary = payload.get("summary")
    if isinstance(summary, dict):
        summary_lang = summary.get("summary_language")
        if isinstance(summary_lang, str):
            _scan_text_for_banned(
                summary_lang, "summary.summary_language", errors,
            )

    # limitations: each entry should be a string.
    limitations = payload.get("limitations")
    if isinstance(limitations, list):
        for i, entry in enumerate(limitations):
            if isinstance(entry, str):
                _scan_text_for_banned(
                    entry, f"limitations[{i}]", errors,
                )

    # Per-candidate prose.
    for idx, cand in enumerate(candidates):
        if not isinstance(cand, dict):
            continue
        ticker = cand.get("primary_ticker", f"[{idx}]")
        for field in _PROSE_CANDIDATE_FIELDS:
            val = cand.get(field)
            if isinstance(val, str):
                _scan_text_for_banned(
                    val, f"candidate {ticker} {field}", errors,
                )


def _scan_text_for_banned(
    text: str, field_label: str, errors: list[str],
) -> None:
    low = text.lower()
    for token in _BANNED_TOKENS:
        pattern = r"\b" + re.escape(token) + r"\b"
        if re.search(pattern, low):
            errors.append(
                f"{field_label} contains banned overclaim token "
                f"{token!r}; phase2 pool prose must remain conservative"
            )


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def _envelope(
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
        "Phase 2 BH/FDR pool artifact validator", "",
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
            "Read-only Phase 2 BH/FDR pool artifact schema validator.  "
            "Walks the structure of a phase2_pool_v1.json file, "
            "recomputes BH q-values from raw_p, and reports schema "
            "compliance via a structured ok/errors envelope.  Read-only: "
            "no DB seam, no provider, no LLM, no FastAPI surface."
        ),
    )
    parser.add_argument(
        "--artifact", dest="artifact_path", required=True,
        help=(
            "Required path to a phase2_pool JSON artifact.  Read-only; "
            "the validator opens this file in read mode only."
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
    report = run_validate_phase2_pool(
        artifact_path=args.artifact_path,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_validate_phase2_pool",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
