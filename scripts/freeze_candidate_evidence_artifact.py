#!/usr/bin/env python3
"""Freeze-candidate evidence artifact generator.

Aggregates the reviewed evidence set into a single read-only JSON
artifact suitable as the future demo backend's input *after operator
approval*.  The artifact is a *freeze-candidate* — never a frozen
release — until the operator approves it.

Inputs (all read-only; missing files are skipped with a warning, not
an error)::

    artifacts/curated_stage_validation_evidence.json
    artifacts/short_horizon_review_validation_top10.json
    artifacts/short_horizon_review_validation_next10.json
    artifacts/short_horizon_review_validation_final8.json
    artifacts/short_horizon_review_top10.csv
    artifacts/short_horizon_review_next10.csv
    artifacts/short_horizon_review_final8.csv

Output contract (JSON)::

    {
      "ok":                       bool,
      "artifact_type":            "freeze_candidate_evidence",
      "generated_at":             str,    # ISO-8601 UTC timestamp
      "source_files": [
        {"kind": str, "path": str, "present": bool},
        ...
      ],
      "cohort_summary": {
        "total_records":          int,
        "fdr_significant_count":  int,
        "raw_p_candidate_count":  int,
        "events_evaluated":       int,
        "horizons_covered":       [int, ...],
        "mechanism_families_covered": [str, ...],
      },
      "records": [
        {
          "source":            str,
          "event_id":          int,
          "headline":          str | None,
          "primary_ticker":    str | None,
          "benchmark":         str | None,
          "mechanism_family":  str | None,
          "horizon":           int | None,
          "p_value":           float | None,
          "fdr_q":             float | None,
          "raw_p_candidate":   bool,
          "fdr_significant":   bool,
          "verdict":           str,
        },
        ...
      ],
      "verdict_counts":           dict[str, int],
      "by_horizon":               dict[str, {records_count,
                                             fdr_significant_count,
                                             raw_p_candidate_count}],
      "by_mechanism_family":      dict[str, {records_count,
                                             fdr_significant_count,
                                             raw_p_candidate_count,
                                             events_evaluated}],
      "review_completion": [
        {
          "name":                str,
          "worksheet_path":      str,
          "validation_path":     str,
          "worksheet_total_rows":int,
          "accepted_count":      int,
          "excluded_count":      int,
          "pending_count":       int,
          "events_evaluated":    int,
          "records_count":       int,
          "significant_count":   int,
        },
        ...
      ],
      "duplicate_event_ids":      [int, ...],
      "limitations":              [str, ...],
      "evidence_claim_allowed":   [str, ...],
      "evidence_claim_not_allowed":[str, ...],
      "warnings":                 [str, ...],
      "errors":                   [str, ...],
    }

Verdict vocabulary (per-record)
-------------------------------
* ``fdr_significant``   — ``fdr_q`` non-null and ``<= alpha``.
* ``raw_p_only_candidate`` — ``p_value`` non-null and ``<= alpha``,
  but ``fdr_q`` does not clear.
* ``inconclusive_fdr``  — has p_value or fdr_q data but neither
  clears.
* ``insufficient``      — neither p_value nor fdr_q is a number.

Conservative wording — banned tokens in ``limitations`` /
``evidence_claim_*`` / ``warnings`` / ``errors`` text streams:
``proof``, ``proven``, ``automatically``, ``alpha generated``,
``guaranteed``, ``correct ticker``.  The word ``validated`` appears
in the verdict vocabulary tokens; in surfaced prose it appears only
within explicit "claim NOT allowed" disclaimers.

Out of scope (deliberately)
---------------------------
* No DB writes.  No DB reads either — every input is a JSON / CSV
  file in ``artifacts/``.
* No provider / yfinance / market_data / price_cache.fetch_*; no
  LLM; no FastAPI surface (never imports ``api`` / ``routes.*``).
* Read-only on every input.  ``--output`` is the only filesystem
  side effect, and only when explicitly passed.

Usage::

    python scripts/freeze_candidate_evidence_artifact.py --json
    python scripts/freeze_candidate_evidence_artifact.py --json \\
        --output artifacts/freeze_candidate_evidence.json
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_ARTIFACT_TYPE: str = "freeze_candidate_evidence"
_DEFAULT_ALPHA: float = 0.05

_VERDICT_FDR_SIGNIFICANT: str = "fdr_significant"
_VERDICT_RAW_P_ONLY:      str = "raw_p_only_candidate"
_VERDICT_INCONCLUSIVE:    str = "inconclusive_fdr"
_VERDICT_INSUFFICIENT:    str = "insufficient"

_VERDICT_VOCABULARY: tuple[str, ...] = (
    _VERDICT_FDR_SIGNIFICANT,
    _VERDICT_RAW_P_ONLY,
    _VERDICT_INCONCLUSIVE,
    _VERDICT_INSUFFICIENT,
)


_GATE_COLUMN: str = "include_in_short_horizon_validation"


_SHORT_HORIZON_BATCHES: tuple[tuple[str, str, str], ...] = (
    # (name, worksheet_csv, validation_json)
    ("top10",
     "artifacts/short_horizon_review_top10.csv",
     "artifacts/short_horizon_review_validation_top10.json"),
    ("next10",
     "artifacts/short_horizon_review_next10.csv",
     "artifacts/short_horizon_review_validation_next10.json"),
    ("final8",
     "artifacts/short_horizon_review_final8.csv",
     "artifacts/short_horizon_review_validation_final8.json"),
)


_CURATED_PATH: str = "artifacts/curated_stage_validation_evidence.json"


_LIMITATION_NO_FDR = (
    "no FDR-significant validation claim is supported by this "
    "evidence set; every surfaced record is either raw-p-only "
    "candidate, inconclusive_fdr, or insufficient."
)
_LIMITATION_DEFAULT_DISCLAIMER = (
    "freeze-candidate only — awaiting operator approval before any "
    "downstream demo backend may consume this artifact."
)
_LIMITATION_REVIEW_INCOMPLETE_TPL = (
    "{n} short-horizon worksheet row(s) carry a blank or unrecognised "
    "gate value across batches {batches}; the cohort is not fully "
    "operator-reviewed."
)

_CLAIM_ALLOWED: tuple[str, ...] = (
    "freeze-candidate cohort summary — record counts, horizons, "
    "mechanism-family geometry",
    "raw-p candidate signals that did not clear FDR",
    "review-completion bookkeeping per worksheet batch",
    "per-record (event_id, horizon) statistical-summary fields the "
    "upstream pipeline already produced",
)
_CLAIM_NOT_ALLOWED: tuple[str, ...] = (
    "FDR-significant validation claim when fdr_significant_count is 0",
    "any statement of certainty about future market direction",
    "renaming this artifact as 'frozen' before operator approval",
    "merging records across event_ids before deduplication review",
    "SPY-vs-XLE benchmark sensitivity inference when "
    "benchmark_sensitivity_status.status is not 'comparison_available'",
)


# ---------------------------------------------------------------------------
# Benchmark sensitivity appendix — surfaces the current XLE preflight
# state in the freeze-candidate envelope so a downstream reader can see
# whether SPY-vs-XLE sensitivity is even runnable yet.
# ---------------------------------------------------------------------------

_BENCH_STATUS_UNKNOWN:              str = "unknown"
_BENCH_STATUS_BLOCKED:              str = "blocked"
_BENCH_STATUS_PREVIEW_READY:        str = "preview_ready"
_BENCH_STATUS_COMPARISON_AVAILABLE: str = "comparison_available"

# Keys we strip from a comparison artifact when copying into the
# block's ``comparison_summary`` — these are typically large arrays of
# per-record / per-event data that bloat the freeze-candidate envelope.
_BENCH_COMPARISON_BULK_KEYS: frozenset[str] = frozenset({
    "by_event", "by_record", "examples", "records", "rows",
})

_BENCH_LIMITATION_BLOCKED: str = (
    "benchmark sensitivity remains unavailable: the XLE benchmark "
    "preflight is blocked on missing local price_cache rows; no "
    "SPY-vs-XLE comparison can be inferred until the required dates "
    "are present in price_cache."
)
_BENCH_LIMITATION_PREVIEW_READY: str = (
    "benchmark data readiness improved but the SPY-vs-XLE "
    "interpretation has not yet been run: the preview indicates the "
    "XLE preflight clears once the listed rows are staged; no "
    "directional conclusions are supported until the comparison "
    "itself executes."
)
_BENCH_LIMITATION_COMPARISON: str = (
    "comparison_summary is copied from the input comparison "
    "artifact; readers should consult the source artifact for the "
    "full statistical context."
)
_BENCH_LIMITATION_UNKNOWN: str = (
    "benchmark sensitivity status could not be determined: no XLE "
    "backfill request packet, preview, or comparison artifact was "
    "supplied; the freeze-candidate makes no SPY-vs-XLE claim."
)


# ---------------------------------------------------------------------------
# Patchable seam — tests patch this to pin the timestamp.
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ",
    )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def build_freeze_candidate_evidence_artifact(
    *,
    curated_path:        str | None = _CURATED_PATH,
    short_horizon_batches: Sequence[tuple[str, str, str]] = (
        _SHORT_HORIZON_BATCHES
    ),
    alpha:               float = _DEFAULT_ALPHA,
    output_path:         str | None = None,
    generated_at:        str | None = None,
    xle_request_packet_path: str | None = None,
    xle_preview_path:        str | None = None,
    xle_comparison_path:     str | None = None,
) -> dict[str, Any]:
    """Build the freeze-candidate evidence artifact.

    See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []
    source_files: list[dict[str, Any]] = []

    records: list[dict[str, Any]] = []

    # Step 1: curated stage validation.
    if curated_path:
        curated_present = Path(curated_path).exists()
        source_files.append({
            "kind":    "curated_stage_validation",
            "path":    curated_path,
            "present": curated_present,
        })
        if curated_present:
            curated_records = _load_curated_records(
                curated_path, warnings, errors, alpha=alpha,
            )
            records.extend(curated_records)
        else:
            warnings.append(
                f"curated stage validation file missing: {curated_path}"
            )

    # Step 2: short-horizon batches.
    review_completion: list[dict[str, Any]] = []
    for name, ws_path, val_path in short_horizon_batches:
        ws_present  = Path(ws_path).exists()
        val_present = Path(val_path).exists()
        source_files.append({
            "kind":    f"short_horizon_worksheet_{name}",
            "path":    ws_path,
            "present": ws_present,
        })
        source_files.append({
            "kind":    f"short_horizon_validation_{name}",
            "path":    val_path,
            "present": val_present,
        })
        if not ws_present:
            warnings.append(
                f"short-horizon worksheet missing: {ws_path}"
            )
        if not val_present:
            warnings.append(
                f"short-horizon validation missing: {val_path}"
            )

        ws_stats = _read_worksheet_stats(ws_path) if ws_present else _empty_ws_stats()
        val_stats = _read_validation_stats(val_path) if val_present else _empty_val_stats()
        sh_records = (
            _load_short_horizon_records(
                val_path, source_name=f"short_horizon_{name}",
                warnings=warnings, errors=errors, alpha=alpha,
            )
            if val_present else []
        )
        records.extend(sh_records)

        review_completion.append({
            "name":                 name,
            "worksheet_path":       ws_path,
            "validation_path":      val_path,
            "worksheet_total_rows": ws_stats["total_rows"],
            "accepted_count":       ws_stats["accepted_count"],
            "excluded_count":       ws_stats["excluded_count"],
            "pending_count":        ws_stats["pending_count"],
            "events_evaluated":     val_stats["events_evaluated"],
            "records_count":        val_stats["records_count"],
            "significant_count":    val_stats["significant_count"],
        })

    # Step 3: aggregate.
    verdict_counts = _verdict_counts(records)
    by_horizon = _aggregate_by_horizon(records)
    by_mechanism_family = _aggregate_by_mechanism_family(records)

    cohort_summary = _build_cohort_summary(records)

    duplicate_event_ids = _find_cross_source_duplicate_event_ids(records)

    limitations = _build_limitations(
        records=records,
        review_completion=review_completion,
    )

    benchmark_sensitivity_status = _build_benchmark_sensitivity_status(
        request_packet_path=xle_request_packet_path,
        preview_path=xle_preview_path,
        comparison_path=xle_comparison_path,
        warnings=warnings,
    )

    envelope = {
        "ok":                         not errors,
        "artifact_type":              _ARTIFACT_TYPE,
        "generated_at":               generated_at or _utcnow_iso(),
        "source_files":               source_files,
        "cohort_summary":             cohort_summary,
        "records":                    records,
        "verdict_counts":             verdict_counts,
        "by_horizon":                 by_horizon,
        "by_mechanism_family":        by_mechanism_family,
        "review_completion":          review_completion,
        "duplicate_event_ids":        duplicate_event_ids,
        "limitations":                limitations,
        "evidence_claim_allowed":     list(_CLAIM_ALLOWED),
        "evidence_claim_not_allowed": list(_CLAIM_NOT_ALLOWED),
        "benchmark_sensitivity_status": benchmark_sensitivity_status,
        "warnings":                   warnings,
        "errors":                     errors,
    }

    # Step 4: optional output-file persistence.  Only when --output is
    # passed; default invocation has no filesystem side effect.
    if output_path:
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(envelope, fh, indent=2, sort_keys=True, default=str)
        except OSError as exc:
            envelope["errors"].append(
                f"failed to write --output {output_path}: {exc}",
            )
            envelope["ok"] = False

    return envelope


# ---------------------------------------------------------------------------
# Curated stage validation reader
# ---------------------------------------------------------------------------


def _load_curated_records(
    path: str,
    warnings: list[str],
    errors: list[str],
    *,
    alpha: float,
) -> list[dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except OSError as exc:
        errors.append(f"failed to read {path}: {exc}")
        return []
    except json.JSONDecodeError as exc:
        errors.append(f"failed to parse {path}: {exc}")
        return []

    examples = payload.get("examples") or []
    if not isinstance(examples, list):
        warnings.append(
            f"{path}: 'examples' is not a list; treating as empty"
        )
        return []

    out: list[dict[str, Any]] = []
    for ex in examples:
        if not isinstance(ex, dict):
            continue
        event_id = _safe_int(ex.get("source_event_id"))
        if event_id is None:
            event_id = _safe_int(ex.get("event_id"))
        if event_id is None:
            continue
        p_value = _safe_float(ex.get("p_value"))
        fdr_q   = _safe_float(ex.get("fdr_q"))
        fdr_significant, raw_p_candidate, verdict = _classify_record(
            p_value=p_value, fdr_q=fdr_q, alpha=alpha,
        )
        out.append({
            "source":           "curated_stage_validation",
            "event_id":         event_id,
            "headline":         _safe_str(ex.get("headline")),
            "primary_ticker":   _safe_str(ex.get("primary_ticker")),
            "benchmark":        _safe_str(
                ex.get("benchmark_ticker") or ex.get("benchmark")
            ),
            "mechanism_family": _safe_str(ex.get("mechanism_family")),
            "horizon":          _safe_int(ex.get("horizon")),
            "p_value":          p_value,
            "fdr_q":            fdr_q,
            "raw_p_candidate":  raw_p_candidate,
            "fdr_significant":  fdr_significant,
            "verdict":          verdict,
        })
    return out


# ---------------------------------------------------------------------------
# Short-horizon validation reader
# ---------------------------------------------------------------------------


def _load_short_horizon_records(
    path: str,
    *,
    source_name: str,
    warnings: list[str],
    errors: list[str],
    alpha: float,
) -> list[dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except OSError as exc:
        errors.append(f"failed to read {path}: {exc}")
        return []
    except json.JSONDecodeError as exc:
        errors.append(f"failed to parse {path}: {exc}")
        return []

    examples = payload.get("examples") or []
    if not isinstance(examples, list):
        warnings.append(
            f"{path}: 'examples' is not a list; treating as empty"
        )
        return []

    out: list[dict[str, Any]] = []
    for ex in examples:
        if not isinstance(ex, dict):
            continue
        event_id = _safe_int(ex.get("event_id"))
        if event_id is None:
            continue
        p_value = _safe_float(ex.get("p_value"))
        fdr_q   = _safe_float(ex.get("fdr_q"))
        fdr_significant, raw_p_candidate, verdict = _classify_record(
            p_value=p_value, fdr_q=fdr_q, alpha=alpha,
        )
        out.append({
            "source":           source_name,
            "event_id":         event_id,
            "headline":         _safe_str(ex.get("headline")),
            "primary_ticker":   _safe_str(ex.get("primary_ticker")),
            "benchmark":        _safe_str(
                ex.get("benchmark") or ex.get("benchmark_ticker")
            ),
            "mechanism_family": _safe_str(ex.get("mechanism_family")),
            "horizon":          _safe_int(ex.get("horizon")),
            "p_value":          p_value,
            "fdr_q":            fdr_q,
            "raw_p_candidate":  raw_p_candidate,
            "fdr_significant":  fdr_significant,
            "verdict":          verdict,
        })
    return out


# ---------------------------------------------------------------------------
# Record classification
# ---------------------------------------------------------------------------


def _classify_record(
    *, p_value: float | None, fdr_q: float | None, alpha: float,
) -> tuple[bool, bool, str]:
    """Derive ``(fdr_significant, raw_p_candidate, verdict)``.

    * FDR-significant: ``fdr_q`` is a number and ``fdr_q <= alpha``.
    * raw-p-only candidate: ``p_value`` is a number and ``p_value <=
      alpha``, but FDR did not clear.
    """
    fdr_significant = isinstance(fdr_q, (int, float)) and fdr_q <= alpha
    raw_p_only = (
        not fdr_significant
        and isinstance(p_value, (int, float))
        and p_value <= alpha
    )
    if fdr_significant:
        verdict = _VERDICT_FDR_SIGNIFICANT
    elif raw_p_only:
        verdict = _VERDICT_RAW_P_ONLY
    elif p_value is not None or fdr_q is not None:
        verdict = _VERDICT_INCONCLUSIVE
    else:
        verdict = _VERDICT_INSUFFICIENT
    return fdr_significant, raw_p_only, verdict


# ---------------------------------------------------------------------------
# Worksheet stats
# ---------------------------------------------------------------------------


def _read_worksheet_stats(path: str) -> dict[str, int]:
    total = accepted = excluded = pending = 0
    try:
        with open(path, "r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                total += 1
                gate = (row.get(_GATE_COLUMN) or "").strip().lower()
                if gate == "yes":
                    accepted += 1
                elif gate == "no":
                    excluded += 1
                else:
                    pending += 1
    except OSError:
        return _empty_ws_stats()
    return {
        "total_rows":     total,
        "accepted_count": accepted,
        "excluded_count": excluded,
        "pending_count":  pending,
    }


def _empty_ws_stats() -> dict[str, int]:
    return {
        "total_rows": 0, "accepted_count": 0,
        "excluded_count": 0, "pending_count": 0,
    }


def _read_validation_stats(path: str) -> dict[str, int]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return _empty_val_stats()
    return {
        "events_evaluated":  _safe_int(payload.get("events_evaluated")) or 0,
        "records_count":     _safe_int(payload.get("records_count")) or 0,
        "significant_count": _safe_int(payload.get("significant_count")) or 0,
    }


def _empty_val_stats() -> dict[str, int]:
    return {"events_evaluated": 0, "records_count": 0, "significant_count": 0}


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------


def _verdict_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {v: 0 for v in _VERDICT_VOCABULARY}
    for rec in records:
        v = rec.get("verdict")
        if isinstance(v, str) and v in out:
            out[v] += 1
    return out


def _aggregate_by_horizon(
    records: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for rec in records:
        h = rec.get("horizon")
        if not isinstance(h, int):
            continue
        key = str(h)
        block = out.setdefault(key, {
            "records_count":         0,
            "fdr_significant_count": 0,
            "raw_p_candidate_count": 0,
        })
        block["records_count"] += 1
        if rec.get("fdr_significant"):
            block["fdr_significant_count"] += 1
        if rec.get("raw_p_candidate"):
            block["raw_p_candidate_count"] += 1
    return out


def _aggregate_by_mechanism_family(
    records: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    seen_events: dict[str, set[int]] = {}
    for rec in records:
        family = rec.get("mechanism_family")
        if not isinstance(family, str) or not family:
            continue
        block = out.setdefault(family, {
            "records_count":         0,
            "fdr_significant_count": 0,
            "raw_p_candidate_count": 0,
            "events_evaluated":      0,
        })
        ev_id = rec.get("event_id")
        if isinstance(ev_id, int):
            seen = seen_events.setdefault(family, set())
            if ev_id not in seen:
                seen.add(ev_id)
                block["events_evaluated"] += 1
        block["records_count"] += 1
        if rec.get("fdr_significant"):
            block["fdr_significant_count"] += 1
        if rec.get("raw_p_candidate"):
            block["raw_p_candidate_count"] += 1
    return out


def _build_cohort_summary(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    total = len(records)
    fdr_sig = sum(1 for r in records if r.get("fdr_significant"))
    raw_p   = sum(1 for r in records if r.get("raw_p_candidate"))
    events  = sorted({
        r["event_id"] for r in records
        if isinstance(r.get("event_id"), int)
    })
    horizons = sorted({
        r["horizon"] for r in records
        if isinstance(r.get("horizon"), int)
    })
    families = sorted({
        r["mechanism_family"] for r in records
        if isinstance(r.get("mechanism_family"), str)
        and r["mechanism_family"]
    })
    return {
        "total_records":              total,
        "fdr_significant_count":      fdr_sig,
        "raw_p_candidate_count":      raw_p,
        "events_evaluated":           len(events),
        "horizons_covered":           horizons,
        "mechanism_families_covered": families,
    }


def _find_cross_source_duplicate_event_ids(
    records: list[dict[str, Any]],
) -> list[int]:
    sources_by_event: dict[int, set[str]] = {}
    for rec in records:
        ev_id = rec.get("event_id")
        src   = rec.get("source")
        if not isinstance(ev_id, int) or not isinstance(src, str):
            continue
        sources_by_event.setdefault(ev_id, set()).add(src)
    return sorted(
        ev_id for ev_id, sources in sources_by_event.items()
        if len(sources) > 1
    )


def _build_limitations(
    *,
    records:           list[dict[str, Any]],
    review_completion: list[dict[str, Any]],
) -> list[str]:
    out: list[str] = [_LIMITATION_DEFAULT_DISCLAIMER]
    fdr_sig = sum(1 for r in records if r.get("fdr_significant"))
    if fdr_sig == 0:
        out.append(_LIMITATION_NO_FDR)
    pending_batches = sorted({
        rc["name"] for rc in review_completion
        if rc.get("pending_count")
    })
    pending_total = sum(
        int(rc.get("pending_count") or 0) for rc in review_completion
    )
    if pending_total > 0:
        out.append(
            _LIMITATION_REVIEW_INCOMPLETE_TPL.format(
                n=pending_total, batches=pending_batches,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return int(s)
        except ValueError:
            return None
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        return int(value)
    return None


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value != value:
            return None
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _safe_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s or None
    return str(value)


# ---------------------------------------------------------------------------
# Benchmark sensitivity appendix builder
# ---------------------------------------------------------------------------


def _build_benchmark_sensitivity_status(
    *,
    request_packet_path: str | None,
    preview_path:        str | None,
    comparison_path:     str | None,
    warnings:            list[str],
) -> dict[str, Any]:
    """Read the (optional) XLE benchmark sensitivity inputs and
    summarise the current state without inferring SPY-vs-XLE.

    Status decision priority:

      1. comparison artifact present   -> 'comparison_available'
      2. preview present AND blocked_after == 0  -> 'preview_ready'
      3. request packet present OR preview with blocked_after > 0
         -> 'blocked'
      4. otherwise -> 'unknown'

    Inputs are all read-only.  Missing files become warnings, not
    errors — the freeze-candidate keeps building.
    """
    request    = _safe_load_json_dict(request_packet_path, warnings)
    preview    = _safe_load_json_dict(preview_path,        warnings)
    comparison = _safe_load_json_dict(comparison_path,     warnings)

    blocked_events: list[dict[str, Any]] = []
    required_dates: list[str] = []
    if isinstance(request, dict):
        be_in = request.get("blocked_events")
        if isinstance(be_in, list):
            for be in be_in:
                if isinstance(be, dict):
                    blocked_events.append(dict(be))
        rd_in = request.get("required_dates")
        if isinstance(rd_in, list):
            required_dates = [d for d in rd_in if isinstance(d, str)]

    # Preview-derived flags.
    local_backfill_available = False
    blocked_after: int | None = None
    if isinstance(preview, dict):
        added = preview.get("added_rows")
        local_backfill_available = (
            isinstance(added, list) and len(added) > 0
        )
        ba = preview.get("blocked_after")
        if isinstance(ba, bool):
            blocked_after = None  # reject bool-as-int
        elif isinstance(ba, int):
            blocked_after = ba

    # Determine status.
    if isinstance(comparison, dict):
        status = _BENCH_STATUS_COMPARISON_AVAILABLE
    elif isinstance(preview, dict) and blocked_after == 0:
        status = _BENCH_STATUS_PREVIEW_READY
    elif isinstance(request, dict) or isinstance(preview, dict):
        status = _BENCH_STATUS_BLOCKED
    else:
        status = _BENCH_STATUS_UNKNOWN

    online_backfill_required = (
        status == _BENCH_STATUS_BLOCKED
    )

    comparison_summary: dict[str, Any] | None = None
    if isinstance(comparison, dict):
        comparison_summary = {
            k: v for k, v in comparison.items()
            if k not in _BENCH_COMPARISON_BULK_KEYS
        }

    if status == _BENCH_STATUS_BLOCKED:
        limitations = [_BENCH_LIMITATION_BLOCKED]
    elif status == _BENCH_STATUS_PREVIEW_READY:
        limitations = [_BENCH_LIMITATION_PREVIEW_READY]
    elif status == _BENCH_STATUS_COMPARISON_AVAILABLE:
        limitations = [_BENCH_LIMITATION_COMPARISON]
    else:
        limitations = [_BENCH_LIMITATION_UNKNOWN]

    return {
        "status":                   status,
        "blocked_events":           blocked_events,
        "required_dates":           required_dates,
        "local_backfill_available": local_backfill_available,
        "online_backfill_required": online_backfill_required,
        "comparison_summary":       comparison_summary,
        "limitations":              limitations,
    }


def _safe_load_json_dict(
    path: str | None, warnings: list[str],
) -> dict[str, Any] | None:
    """Load a JSON file read-only.  Returns the parsed dict on success.
    Missing files return None silently (they are the documented
    absent-input case).  Non-dict / malformed payloads return None and
    surface a warning."""
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(
            f"failed to read benchmark-sensitivity input {path}: {exc}",
        )
        return None
    if not isinstance(payload, dict):
        warnings.append(
            f"benchmark-sensitivity input {path} is not a JSON object; "
            f"ignored"
        )
        return None
    return payload


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    cs = report.get("cohort_summary") or {}
    lines: list[str] = [
        "Freeze-candidate evidence artifact", "",
    ]
    lines.append(f"OK:                       {report['ok']}")
    lines.append(f"artifact_type:            {report['artifact_type']}")
    lines.append(f"generated_at:             {report['generated_at']}")
    lines.append(f"total_records:            {cs.get('total_records', 0)}")
    lines.append(
        f"fdr_significant_count:    {cs.get('fdr_significant_count', 0)}"
    )
    lines.append(
        f"raw_p_candidate_count:    {cs.get('raw_p_candidate_count', 0)}"
    )
    lines.append(f"events_evaluated:         {cs.get('events_evaluated', 0)}")
    lines.append(
        f"horizons_covered:         {cs.get('horizons_covered', [])}"
    )
    lines.append(
        f"mechanism_families:       {cs.get('mechanism_families_covered', [])}"
    )
    lines.append("")
    lines.append("Verdict counts:")
    for v, n in (report.get("verdict_counts") or {}).items():
        lines.append(f"  {v:<30} {n:>4}")
    lines.append("")
    lines.append("Review completion:")
    for rc in report.get("review_completion") or []:
        lines.append(
            f"  {rc.get('name'):<10} "
            f"total={rc.get('worksheet_total_rows'):>3} "
            f"yes={rc.get('accepted_count'):>3} "
            f"no={rc.get('excluded_count'):>3} "
            f"pending={rc.get('pending_count'):>3} "
            f"records={rc.get('records_count'):>3}"
        )
    if report.get("duplicate_event_ids"):
        lines.append("")
        lines.append(
            f"Duplicate event_ids across sources: "
            f"{report['duplicate_event_ids']}"
        )
    if report.get("limitations"):
        lines.append("")
        lines.append("Limitations:")
        for w in report["limitations"]:
            lines.append(f"  - {w}")
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
            "Aggregate the reviewed evidence set into a single "
            "freeze-candidate JSON artifact.  Read-only on every "
            "input; only writes to --output when explicitly passed.  "
            "No DB / provider / yfinance / LLM / FastAPI.  "
            "Conservative wording: freeze-candidate only, never "
            "claimed validated unless fdr_significant_count is "
            "positive."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON artifact to.  When "
            "omitted, the script has no filesystem side effect."
        ),
    )
    parser.add_argument(
        "--curated", dest="curated_path", default=_CURATED_PATH,
        help=(
            f"Path to the curated stage validation evidence JSON "
            f"(default {_CURATED_PATH})."
        ),
    )
    parser.add_argument(
        "--alpha", type=float, default=_DEFAULT_ALPHA,
        help=(
            f"Statistical alpha used to derive raw_p_candidate / "
            f"fdr_significant per record (default {_DEFAULT_ALPHA})."
        ),
    )
    parser.add_argument(
        "--xle-request-packet", dest="xle_request_packet_path",
        default="artifacts/xle_backfill_request_packet.json",
        help=(
            "Optional path to a saved JSON output of "
            "scripts/xle_benchmark_backfill_request_packet.py "
            "(default artifacts/xle_backfill_request_packet.json).  "
            "Missing files are treated as absent, not as errors."
        ),
    )
    parser.add_argument(
        "--xle-preview", dest="xle_preview_path",
        default=(
            "artifacts/xle_online_backfill_preview_post_calendar_fix.json"
        ),
        help=(
            "Optional path to a saved XLE preview JSON (default "
            "artifacts/xle_online_backfill_preview_post_calendar_fix"
            ".json).  Missing files are treated as absent, not as "
            "errors."
        ),
    )
    parser.add_argument(
        "--xle-comparison", dest="xle_comparison_path",
        default="artifacts/xle_benchmark_sensitivity_comparison.json",
        help=(
            "Optional path to a saved SPY-vs-XLE comparison artifact "
            "(default artifacts/xle_benchmark_sensitivity_comparison"
            ".json).  When supplied and readable, the "
            "freeze-candidate's benchmark_sensitivity_status.status "
            "becomes 'comparison_available' and comparison_summary "
            "surfaces a trimmed copy of the artifact.  Missing files "
            "are treated as absent, not as errors."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = build_freeze_candidate_evidence_artifact(
        curated_path=args.curated_path,
        alpha=float(args.alpha),
        output_path=args.output_path,
        xle_request_packet_path=args.xle_request_packet_path,
        xle_preview_path=args.xle_preview_path,
        xle_comparison_path=args.xle_comparison_path,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "build_freeze_candidate_evidence_artifact",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
