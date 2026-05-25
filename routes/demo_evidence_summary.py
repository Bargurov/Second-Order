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

Schema versions
---------------

The source detects the artifact schema version at load time:

* **v1** (default): the artifact carries ``records``,
  ``cohort_summary``, ``verdict_counts``, and
  ``benchmark_sensitivity_status`` at the top level.  The source reads
  them directly.
* **v2**: the artifact carries ``candidates``, ``cohort_statistics``,
  ``robustness_gaps``, ``selection_bias_disclosure``, and
  ``methodology_notes``.  The source maps these into the same 10-key
  envelope the frontend expects, then adds non-breaking extra fields
  (``artifact_schema_version``, ``demo_bundle``, ``source``,
  ``records``, ``robustness_status``, ``methodology_notes``,
  ``selection_bias_disclosure``).

Detection: ``schema_version == "v2"`` OR the joint presence of
``candidates`` and ``cohort_statistics``.

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

    # --- v2 schema detection and delegation --------------------------
    schema_version = payload.get("schema_version")
    if (
        schema_version == "v2"
        or ("candidates" in payload and "cohort_statistics" in payload)
    ):
        return _build_v2_envelope(payload, errors=errors, warnings=warnings)

    # --- v1 schema (original path, unchanged) ------------------------
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


def _build_v2_envelope(
    payload: dict[str, Any],
    *,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    """Build the Evidence Summary envelope from a v2-schema artifact.

    Maps v2 keys (``candidates``, ``cohort_statistics``,
    ``robustness_gaps``, ``selection_bias_disclosure``,
    ``methodology_notes``) into the same 10-key base the frontend
    expects, then adds non-breaking extra fields for v2-aware
    consumers.
    """
    candidates_raw = payload.get("candidates") or []
    cohort_stats = payload.get("cohort_statistics") or {}
    robustness_raw = payload.get("robustness_gaps") or {}
    selection_bias_raw = payload.get("selection_bias_disclosure") or {}
    methodology_raw = payload.get("methodology_notes") or {}

    alpha = cohort_stats.get("alpha", 0.05)
    if not isinstance(alpha, (int, float)) or isinstance(alpha, bool):
        alpha = 0.05

    # -- Map candidates to record-like rows ---------------------------
    records: list[dict[str, Any]] = []
    for c in candidates_raw:
        if not isinstance(c, dict):
            continue
        fdr_sig = _v2_is_fdr_significant(c, alpha)
        raw_p = _v2_is_raw_p_only(c, alpha)
        records.append({
            "rank_in_cohort":    c.get("rank_in_cohort"),
            "event_date":        c.get("event_date", ""),
            "first_trading_date": c.get("first_trading_date", ""),
            "primary_ticker":    c.get("primary_ticker", ""),
            "benchmark_ticker":  c.get("benchmark_ticker", ""),
            "benchmark_role":    c.get("benchmark_role", ""),
            "expected_direction": c.get("expected_direction", ""),
            "mechanism_family":  c.get("mechanism_family", ""),
            "method":            c.get("method", ""),
            "claim_horizon":     c.get("claim_horizon", ""),
            "h1_AR_pct":         c.get("h1_AR_pct"),
            "h1_SAR":            c.get("h1_SAR"),
            "h1_p":              c.get("h1_p"),
            "h1_q_bh":           c.get("h1_q_bh"),
            "fdr_significant":   fdr_sig,
            "raw_p_candidate":   raw_p,
            "caveat":            c.get("caveat", ""),
            "falsifier":         c.get("falsifier", ""),
            "freeze_status":     c.get("freeze_status", ""),
            "cache_backed":      bool(c.get("cache_backed", False)),
        })

    # -- Derive counts ------------------------------------------------
    fdr_count = sum(1 for r in records if r.get("fdr_significant"))
    raw_p_only_count = sum(
        1 for r in records
        if r.get("raw_p_candidate") and not r.get("fdr_significant")
    )

    # -- cohort_summary from cohort_statistics ------------------------
    cohort_summary: dict[str, Any] = {
        "total_records":         cohort_stats.get("n_candidates", len(records)),
        "fdr_significant_count": fdr_count,
        "raw_p_candidate_count": raw_p_only_count,
        "method":                cohort_stats.get("method", ""),
        "fdr_method":            cohort_stats.get("fdr_method", ""),
        "alpha":                 alpha,
        "test_count_for_fdr":    cohort_stats.get("test_count_for_fdr", len(records)),
        "all_pass_q_005":        bool(cohort_stats.get("all_pass_q_005", False)),
    }

    # -- verdict_counts derived from records --------------------------
    verdict_counts: dict[str, Any] = {
        "fdr_significant":      fdr_count,
        "raw_p_only_candidate": raw_p_only_count,
        "inconclusive_fdr":     0,
        "insufficient":         0,
    }

    # -- robustness_status from robustness_gaps -----------------------
    robustness_status: dict[str, Any] = {}
    if isinstance(robustness_raw, dict):
        for gap_key, gap_val in robustness_raw.items():
            if isinstance(gap_val, dict):
                robustness_status[gap_key] = {
                    "status":              gap_val.get("status", ""),
                    "row":                 gap_val.get("row", ""),
                    "resolution_summary":  gap_val.get("resolution_summary", ""),
                }

    # -- limitations (clean of banned tokens) -------------------------
    limitations: list[str] = []
    limitations.append(
        "source artifact is a freeze candidate; the demo evidence summary "
        "describes record counts and verdict tallies only, and does not "
        "make any claim about market direction or mechanism causality"
    )
    fdr_scope = (
        selection_bias_raw.get("fdr_scope_disclaimer")
        if isinstance(selection_bias_raw, dict) else None
    )
    if isinstance(fdr_scope, str) and fdr_scope:
        limitations.append(fdr_scope)
    roundtrip_caveat = (
        methodology_raw.get("cache_storage_roundtrip_caveat")
        if isinstance(methodology_raw, dict) else None
    )
    if isinstance(roundtrip_caveat, str) and roundtrip_caveat:
        limitations.append(roundtrip_caveat)
    if fdr_count == 0:
        limitations.append(
            "no FDR-significant records are present in the source artifact; "
            "raw-p candidate signals are not FDR-significant and must not "
            "be reframed as such by downstream consumers"
        )

    # -- Base 10-key envelope -----------------------------------------
    envelope = _envelope(
        cohort_summary=cohort_summary,
        verdict_counts=verdict_counts,
        fdr_significant_count=fdr_count,
        raw_p_candidate_count=raw_p_only_count,
        benchmark_sensitivity_status={},
        limitations=limitations,
        errors=errors,
        warnings=warnings,
    )

    # -- Non-breaking v2 additions ------------------------------------
    envelope["artifact_schema_version"] = "v2"
    envelope["demo_bundle"] = "section_c_v2"
    envelope["source"] = "frozen_json_not_live_db"
    envelope["records"] = copy.deepcopy(records)
    envelope["robustness_status"] = copy.deepcopy(robustness_status)
    envelope["methodology_notes"] = (
        copy.deepcopy(methodology_raw) if isinstance(methodology_raw, dict)
        else {}
    )
    envelope["selection_bias_disclosure"] = (
        copy.deepcopy(selection_bias_raw) if isinstance(selection_bias_raw, dict)
        else {}
    )

    return envelope


def _v2_is_fdr_significant(candidate: dict[str, Any], alpha: float) -> bool:
    q = candidate.get("h1_q_bh")
    if not isinstance(q, (int, float)) or isinstance(q, bool):
        return False
    return q < alpha


def _v2_is_raw_p_only(candidate: dict[str, Any], alpha: float) -> bool:
    p = candidate.get("h1_p")
    if not isinstance(p, (int, float)) or isinstance(p, bool):
        return False
    q = candidate.get("h1_q_bh")
    q_passes = (
        isinstance(q, (int, float))
        and not isinstance(q, bool)
        and q < alpha
    )
    return p < alpha and not q_passes


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
