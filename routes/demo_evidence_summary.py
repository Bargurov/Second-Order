"""Demo Evidence Summary source — read-only summarizer for the
freeze-candidate evidence artifact.

The demo backend's Evidence Summary section consumes the JSON returned
by :func:`build_demo_evidence_summary`.  The source opens the
freeze-candidate evidence artifact at
``artifacts/freeze_candidate_evidence.json`` (or a caller-supplied
path), walks the structure, and returns a single envelope that pins:

* the cohort summary block exactly as the artifact records it,
* the verdict tallies the artifact computed,
* the authoritative ``fdr_significant_count`` from the artifact (never
  inflated with raw-p-only signals),
* the artifact's ``raw_p_candidate_count`` surfaced separately,
* the artifact's ``benchmark_sensitivity_status`` block (which
  carries the SPY-vs-XLE change-of-interpretation observation for
  event 60 when present), and
* a conservative ``limitations`` list that combines the artifact's
  own caveats with the source's read-only / freeze-candidate
  caveats.

Read-only by construction
-------------------------

* No DB writes — no DB reads.  The single input is one JSON file.
* No provider / ``yfinance`` / ``market_data`` / ``price_cache`` /
  ``news_fetch`` / ``news_relevance`` / LLM call.
* No FastAPI surface — the source defines no router and is not
  registered in ``api.py``.  The demo backend imports this module
  directly and calls :func:`build_demo_evidence_summary`.
* The artifact file is opened in read-mode only; byte identity is
  preserved across a call.
* Returned sub-structures are decoupled copies so a caller mutating
  the report does not corrupt cached artifact state on a subsequent
  call.

Conservative wording
--------------------

The source describes record counts and verdict tallies only — it
never relabels the freeze-candidate as "frozen", never claims any
record is "validated" or "proven", and surfaces a "no FDR-significant"
caveat whenever ``cohort_summary.fdr_significant_count`` is zero.  The
following overclaim tokens are banned from any prose this module
emits (``limitations`` it appends, ``errors``, ``warnings``):
``proof``, ``proven``, ``guaranteed``, ``alpha generated``,
``correct ticker``, ``automatically``, ``validated``.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


SECTION: str = "evidence_summary"


DEFAULT_ARTIFACT_PATH: str = "artifacts/freeze_candidate_evidence.json"


_ARTIFACT_TYPE_EXPECTED: str = "freeze_candidate_evidence"


def build_demo_evidence_summary(
    *,
    artifact_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build the demo Evidence Summary envelope.

    Parameters
    ----------
    artifact_path
        Optional path to a freeze-candidate evidence JSON artifact.
        When omitted, the source reads
        :data:`DEFAULT_ARTIFACT_PATH` (``artifacts/freeze_candidate_evidence.json``).

    Returns
    -------
    dict
        An envelope with exactly the following 10 keys::

            ok, section, cohort_summary, verdict_counts,
            fdr_significant_count, raw_p_candidate_count,
            benchmark_sensitivity_status, limitations, warnings,
            errors

        ``ok`` is ``True`` iff ``errors`` is empty.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    raw_path = artifact_path if artifact_path is not None else DEFAULT_ARTIFACT_PATH
    # Preserve the caller's exact path string in error messages so the
    # operator can fix the path they supplied; Path() normalisation
    # (slash flipping on Windows) is for filesystem ops only.
    path_repr = str(raw_path)
    path = Path(raw_path)

    if not path.is_file():
        errors.append(
            f"freeze-candidate evidence artifact is missing at {path_repr!r}; "
            f"the demo evidence summary source requires the artifact to be "
            f"present on disk"
        )
        return _envelope(errors=errors, warnings=warnings)

    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload: Any = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(
            f"failed to read freeze-candidate evidence artifact at "
            f"{path_repr!r}: {type(exc).__name__}: {exc}"
        )
        return _envelope(errors=errors, warnings=warnings)

    if not isinstance(payload, dict):
        errors.append(
            f"freeze-candidate evidence artifact root must be a JSON "
            f"object, got {type(payload).__name__}"
        )
        return _envelope(errors=errors, warnings=warnings)

    artifact_type = payload.get("artifact_type")
    if artifact_type != _ARTIFACT_TYPE_EXPECTED:
        errors.append(
            f"freeze-candidate evidence artifact carries "
            f"artifact_type={artifact_type!r}; the demo evidence "
            f"summary source requires artifact_type=="
            f"{_ARTIFACT_TYPE_EXPECTED!r}"
        )
        return _envelope(errors=errors, warnings=warnings)

    cohort_summary = payload.get("cohort_summary")
    if not isinstance(cohort_summary, dict):
        cohort_summary = {}

    verdict_counts = payload.get("verdict_counts")
    if not isinstance(verdict_counts, dict):
        verdict_counts = {}

    fdr_significant_count = _int_field(cohort_summary, "fdr_significant_count")
    raw_p_candidate_count = _int_field(cohort_summary, "raw_p_candidate_count")

    bench = payload.get("benchmark_sensitivity_status")
    if not isinstance(bench, dict):
        bench = {}

    artifact_limitations_raw = payload.get("limitations")
    if not isinstance(artifact_limitations_raw, list):
        artifact_limitations_raw = []
    artifact_limitations: list[str] = [
        entry for entry in artifact_limitations_raw if isinstance(entry, str)
    ]

    limitations = list(artifact_limitations)
    limitations.append(
        "source artifact is a freeze candidate; the demo evidence summary "
        "describes record counts and verdict tallies only, and does not "
        "make any claim about market direction or mechanism causality"
    )
    if fdr_significant_count == 0:
        limitations.append(
            "no FDR-significant records are present in the source artifact; "
            "raw-p candidate signals are not FDR-significant and must not "
            "be reframed as such by downstream consumers"
        )

    return _envelope(
        cohort_summary=cohort_summary,
        verdict_counts=verdict_counts,
        fdr_significant_count=fdr_significant_count,
        raw_p_candidate_count=raw_p_candidate_count,
        benchmark_sensitivity_status=bench,
        limitations=limitations,
        errors=errors,
        warnings=warnings,
    )


def _int_field(container: dict[str, Any], key: str) -> int:
    """Return ``container[key]`` when it is an int (and not a bool);
    otherwise ``0``.  Booleans are explicitly excluded so a stray
    ``True`` upstream cannot be silently surfaced as ``1``."""
    value = container.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0


def _envelope(
    *,
    cohort_summary:               dict[str, Any] | None = None,
    verdict_counts:               dict[str, Any] | None = None,
    fdr_significant_count:        int = 0,
    raw_p_candidate_count:        int = 0,
    benchmark_sensitivity_status: dict[str, Any] | None = None,
    limitations:                  list[str] | None = None,
    errors:                       list[str],
    warnings:                     list[str],
) -> dict[str, Any]:
    return {
        "ok":                            not errors,
        "section":                       SECTION,
        "cohort_summary":                copy.deepcopy(cohort_summary or {}),
        "verdict_counts":                copy.deepcopy(verdict_counts or {}),
        "fdr_significant_count":         fdr_significant_count,
        "raw_p_candidate_count":         raw_p_candidate_count,
        "benchmark_sensitivity_status":  copy.deepcopy(
            benchmark_sensitivity_status or {}
        ),
        "limitations":                   list(limitations or []),
        "warnings":                      list(warnings),
        "errors":                        list(errors),
    }


__all__: tuple[str, ...] = (
    "SECTION",
    "DEFAULT_ARTIFACT_PATH",
    "build_demo_evidence_summary",
)
