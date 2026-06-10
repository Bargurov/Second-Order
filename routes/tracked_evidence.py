"""Tracked evidence summary source.

Read-only source module for the tracked Phase 1 + Phase 2 evidence
layer. Loads the freeze-candidate artifact, the closed Phase 2 BH/FDR
pool artifact, and the rejection / deferred-lesson summary through
:mod:`cohort_evidence`, then shapes them into a single envelope the
:func:`api._evidence_summary_endpoint` FastAPI handler returns.

The source module is the platform-consumable backend contract for the
tracked evidence layer. The HTTP endpoint is a thin wrapper around
:func:`build_tracked_evidence_summary`; in-process callers (tests,
operator scripts) import this module directly.

Scope separation is structural
------------------------------

The envelope returns ``phase1`` and ``phase2`` as **separate**
top-level arrays. There is no flat combined candidate list, no
combined q-value, no combined denominator, no cross-phase FDR field.
Phase 1 q-values come from the five-row Phase 1 denominator only;
Phase 2 q-values come from the five-row Phase 2 denominator only.
The :data:`FDR_SCOPE_NOTE` string is embedded in every envelope as a
machine-readable caveat for consumers that strip prose and look at
data fields only.

Read-only by construction
-------------------------

* Imports only stdlib and :mod:`cohort_evidence`. No FastAPI, no
  ``api``, no other ``routes.*`` module, no provider / yfinance /
  market_data / price_cache / movers_cache, no DB, no LLM, no
  network. Enforced by an AST-level import whitelist test.
* The three source artifacts are opened in read-mode only by
  :mod:`cohort_evidence`; byte identity is preserved across an
  envelope build (verified by a hash-invariance test).
* No artifact mutation, no implicit cache population, no environment
  inspection. Path resolution (including the
  ``SECOND_ORDER_DEMO_ARTIFACT_DIR`` env-var convention) is the
  caller's responsibility — the source module accepts explicit
  string paths.

Error handling
--------------

* Missing Phase 1 artifact: ``ok`` is False with a path-bearing error
  in the ``errors`` list. The envelope still contains all documented
  keys; ``phase1`` is ``[]`` and ``phase1_count`` is ``0``.
* Missing Phase 2 artifact: ``ok`` stays True; ``phase2`` is ``[]``,
  ``phase2_count`` / ``phase2_pass_count`` / ``phase2_fail_count``
  are all ``0``. Phase 2 may not yet exist for older snapshots.
* Missing rejection-log summary: ``ok`` stays True;
  ``deferred_count`` is ``None``.
* Malformed JSON / unexpected schema on Phase 1 surfaces as an error;
  on Phase 2 surfaces as a warning with an empty array.
* No raw stack traces leak into the envelope; only the exception
  type name and the offending path are reported.

Output contract
---------------

::

    {
      "ok":             bool,
      "section":        "tracked_evidence",
      "schema_version": "v1",
      "summary": {
        "phase1_count":      int,
        "phase2_count":      int,
        "phase2_pass_count": int,
        "phase2_fail_count": int,
        "deferred_count":    int | None,
      },
      "phase1":         [normalized record, ...],
      "phase2":         [normalized record, ...],
      "fdr_scope_note": str,
      "limitations":    [str, ...],
      "warnings":       [str, ...],
      "errors":         [str, ...],
    }

``ok`` is ``True`` iff ``errors == []``. ``phase1`` and ``phase2``
each contain records whose key set matches
:data:`cohort_evidence.RECORD_KEYS`; the per-record ``phase`` field
matches the array key.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import cohort_evidence


SECTION: str = "tracked_evidence"
SCHEMA_VERSION: str = "v1"


ENVELOPE_KEYS: tuple[str, ...] = (
    "ok",
    "section",
    "schema_version",
    "summary",
    "phase1",
    "phase2",
    "fdr_scope_note",
    "limitations",
    "warnings",
    "errors",
)


SUMMARY_KEYS: tuple[str, ...] = (
    "phase1_count",
    "phase2_count",
    "phase2_pass_count",
    "phase2_fail_count",
    "deferred_count",
)


FDR_SCOPE_NOTE: str = (
    "Phase 1 and Phase 2 are independent FDR scopes. Phase 1 q-values "
    "are pinned within the five-row Phase 1 denominator and are not "
    "recomputed when Phase 2 candidates are screened. Phase 2 q-values "
    "come from Benjamini-Hochberg step-up within the closed Phase 2 "
    "pool only. q-values from one phase must not be compared as if "
    "drawn from the other."
)


_BASE_LIMITATIONS: tuple[str, ...] = (
    "Tracked evidence summary reports per-phase counts and per-row "
    "values exactly as they appear in the tracked artifacts; it does "
    "not recompute any FDR statistic and does not adjust q-values "
    "across phases.",
    "Not live trading advice.",
    "Not a forecasting tool that produces forward-return estimates.",
    "Not a causal-mechanism claim. A row that passes the screen "
    "supports the pre-registered direction on the named event date; "
    "it does not establish causality.",
    "Not a complete universe of events; the tracked cohort is a small "
    "curated bundle.",
    "Not a demo or presentation script.",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_paths(
    phase1_path: str | None,
    phase2_path: str | None,
    rejection_path: str | None,
) -> tuple[str, str, str]:
    """Resolve the three artifact paths against cohort_evidence defaults."""
    return (
        phase1_path if phase1_path is not None else cohort_evidence.DEFAULT_PHASE1_PATH,
        phase2_path if phase2_path is not None else cohort_evidence.DEFAULT_PHASE2_PATH,
        rejection_path if rejection_path is not None else cohort_evidence.DEFAULT_REJECTION_PATH,
    )


def _read_deferred_count(path: str) -> int | None:
    """Return the deferred-methodology-lesson count from the rejection log.

    Returns ``None`` when the file is missing, when the JSON cannot be
    parsed, or when the expected
    ``summary.decision_counts.deferred_methodology_lesson`` key path
    is absent or non-integer. Read-only.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return None
    counts = summary.get("decision_counts")
    if not isinstance(counts, dict):
        return None
    value = counts.get("deferred_methodology_lesson")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _load_phase1(
    path: str,
    errors: list[str],
) -> list[dict[str, Any]]:
    """Load Phase 1; on failure, append a clear error and return ``[]``."""
    try:
        return list(cohort_evidence.load_phase1(path))
    except FileNotFoundError:
        errors.append(
            f"Phase 1 freeze artifact not found at {path!r}"
        )
    except (ValueError, json.JSONDecodeError) as exc:
        errors.append(
            f"Phase 1 freeze artifact at {path!r} could not be loaded: "
            f"{type(exc).__name__}"
        )
    return []


def _load_phase2(
    path: str,
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Load Phase 2; missing file returns ``[]`` silently.

    Malformed JSON / schema surfaces as a warning (not a hard error) so
    a stale Phase 2 file does not block the rest of the envelope.
    """
    try:
        result = cohort_evidence.load_phase2(path)
    except (ValueError, json.JSONDecodeError) as exc:
        warnings.append(
            f"Phase 2 pool artifact at {path!r} could not be loaded: "
            f"{type(exc).__name__}; phase2 reported as empty"
        )
        return []
    return list(result) if result is not None else []


def _envelope(
    *,
    phase1:      list[dict[str, Any]],
    phase2:      list[dict[str, Any]],
    summary:     dict[str, Any],
    limitations: list[str],
    errors:      list[str],
    warnings:    list[str],
) -> dict[str, Any]:
    """Assemble the documented envelope. Decoupled copies of nested data."""
    return {
        "ok":             not errors,
        "section":        SECTION,
        "schema_version": SCHEMA_VERSION,
        "summary":        copy.deepcopy(summary),
        "phase1":         copy.deepcopy(phase1),
        "phase2":         copy.deepcopy(phase2),
        "fdr_scope_note": FDR_SCOPE_NOTE,
        "limitations":    list(limitations),
        "warnings":       list(warnings),
        "errors":         list(errors),
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_tracked_evidence_summary(
    *,
    phase1_path:    str | None = None,
    phase2_path:    str | None = None,
    rejection_path: str | None = None,
) -> dict[str, Any]:
    """Build the tracked evidence summary envelope.

    Parameters
    ----------
    phase1_path, phase2_path, rejection_path:
        Optional explicit paths. ``None`` resolves to the corresponding
        :data:`cohort_evidence.DEFAULT_*` constant
        (``evidence_artifacts/section_c_v2/``).

    Returns
    -------
    Dict matching the contract documented at module level. ``ok`` is
    True iff ``errors == []``. Phase 1 and Phase 2 are returned as
    separate top-level arrays; no flat combined list is produced and
    no q-values are recomputed.
    """
    resolved_phase1, resolved_phase2, resolved_rejection = _resolve_paths(
        phase1_path, phase2_path, rejection_path,
    )

    errors:   list[str] = []
    warnings: list[str] = []

    phase1 = _load_phase1(resolved_phase1, errors)
    phase2 = _load_phase2(resolved_phase2, warnings)
    deferred_count = _read_deferred_count(resolved_rejection)

    phase2_pass = sum(
        1 for r in phase2 if bool(r.get("passes_bh_at_005"))
    )
    phase2_fail = sum(
        1 for r in phase2 if not bool(r.get("passes_bh_at_005"))
    )

    summary: dict[str, Any] = {
        "phase1_count":      len(phase1),
        "phase2_count":      len(phase2),
        "phase2_pass_count": phase2_pass,
        "phase2_fail_count": phase2_fail,
        "deferred_count":    deferred_count,
    }

    return _envelope(
        phase1=phase1,
        phase2=phase2,
        summary=summary,
        limitations=list(_BASE_LIMITATIONS),
        errors=errors,
        warnings=warnings,
    )


__all__: tuple[str, ...] = (
    "SECTION",
    "SCHEMA_VERSION",
    "ENVELOPE_KEYS",
    "SUMMARY_KEYS",
    "FDR_SCOPE_NOTE",
    "build_tracked_evidence_summary",
)
