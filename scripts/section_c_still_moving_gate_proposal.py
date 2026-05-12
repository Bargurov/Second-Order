#!/usr/bin/env python3
"""Still Moving Market gate proposal — read-only.

Consumes a saved JSON output of
``scripts/section_c_still_moving_quality_diagnostic.py`` and proposes
eight concrete eligibility / ranking gates that weak or noisy ticker
candidates would have to clear before they appear in the Still Moving
Market section.

The proposal is *not* an implementation.  No still-moving filter is
applied; no production module is imported; no DB row, ``price_cache``
entry, or artifact under ``artifacts/`` is mutated.  The script
evaluates each candidate against each proposed gate against the
diagnostic snapshot and surfaces how many would pass / fail, plus a
small set of examples on each side, so an operator can decide whether
to wire any of the gates into the surface in a separate
implementation step.

Read-only contract
------------------
* Reads the diagnostic JSON snapshot opened ``"r"`` and parsed; never
  rewritten.
* No DB connection.  No call to ``yfinance`` / ``market_data`` / a
  paid provider / an LLM / a FastAPI surface.  No network.
* ``--output`` is the only filesystem side effect, and only when
  explicitly passed.

The eight proposed gates (spec-pinned, in order)
------------------------------------------------
1. ``primary_ticker_present``           — primary_ticker non-null.
2. ``primary_neq_benchmark``            — primary != benchmark.
3. ``primary_not_sector_etf``           — primary is not a sector
   ETF; an explicit allowlist may override (configurable, default
   empty).
4. ``price_cache_coverage``             — price_cache covers both
   the primary and the benchmark.
5. ``benchmark_adjusted_evidence``      — a benchmark-adjusted
   evidence record exists for the event.
6. ``persistence_signal_available``     — a persistence signal is
   recorded for the event.
7. ``no_duplicate_narrative``           — the event's narrative is
   not already represented by another candidate in the same window.
8. ``rank_by_evidence_strength``        — ranking gate: order
   candidates by recorded evidence strength rather than upstream LLM
   confidence.  This is a meta (ranking) gate, not a per-row
   eligibility check; its ``failure_count`` / ``pass_count`` are
   ``null``.

Output contract (JSON)::

    {
      "ok":                              bool,
      "candidates_analyzed":             int,
      "proposed_gates":                  [ {...gate dict}, ... ],
      "gate_failure_counts":             {gate_id: int | None, ...},
      "defensible_candidate_requirements":[ str, ... ],
      "examples_blocked_by_gate":        {gate_id: [example, ...]},
      "examples_allowed_by_gate":        [example, ...],
      "warnings":                        [str, ...],
      "errors":                          [str, ...],
    }

Each proposed gate dict carries::

    {
      "gate_id":            str,
      "name":               str,
      "requirement":        str,
      "gate_type":          "eligibility" | "ranking",
      "diagnostic_signal":  str | None,
      "failure_count":      int | None,
      "pass_count":         int | None,
      "false_positive_risk":str,
      "defensible_default": bool,
      "expected_benefit":   str,
    }

Conservative wording — banned tokens in any surfaced prose
(``proposed_gates``, ``defensible_candidate_requirements``,
``warnings``, ``errors``): ``proof``, ``proven``, ``automatically``,
``alpha generated``, ``guaranteed``, ``correct ticker``.  The
proposal never claims a candidate is the right call — it claims a
gate is *defensible* and that a candidate is *blocked* or *allowed*
by the proposed gate set.

Usage::

    python scripts/section_c_still_moving_gate_proposal.py --json
    python scripts/section_c_still_moving_gate_proposal.py --text \\
        --diagnostic-path artifacts/<diagnostic>.json
    python scripts/section_c_still_moving_gate_proposal.py --json \\
        --output artifacts/section_c_still_moving_gate_proposal.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_DIAGNOSTIC_PATH: str = (
    "artifacts/section_c_still_moving_quality_diagnostic.json"
)
_DEFAULT_BLOCKED_EXAMPLE_CAP: int = 3
_DEFAULT_ALLOWED_EXAMPLE_CAP: int = 5


_BANNED_TOKENS: tuple[str, ...] = (
    "proof", "proven", "automatically", "alpha generated",
    "guaranteed", "correct ticker",
)


# ---------------------------------------------------------------------------
# Gate vocabulary — the eight spec-pinned gates, in order.  The order
# is the contract: consumers may index by position.
# ---------------------------------------------------------------------------


_GATE_ORDER: tuple[str, ...] = (
    "primary_ticker_present",
    "primary_neq_benchmark",
    "primary_not_sector_etf",
    "price_cache_coverage",
    "benchmark_adjusted_evidence",
    "persistence_signal_available",
    "no_duplicate_narrative",
    "rank_by_evidence_strength",
)


# ---------------------------------------------------------------------------
# Per-candidate gate evaluation.  Each function returns True when the
# candidate *passes* the gate.  ``None`` is reserved for gates that
# are not per-row (the ranking gate).
# ---------------------------------------------------------------------------


def _gate_primary_ticker_present(c: dict[str, Any]) -> bool:
    primary = c.get("primary_ticker")
    return isinstance(primary, str) and bool(primary.strip())


def _gate_primary_neq_benchmark(c: dict[str, Any]) -> bool:
    primary   = c.get("primary_ticker")
    benchmark = c.get("benchmark_ticker")
    if not isinstance(primary, str) or not primary.strip():
        # Missing primary cascades: it cannot equal anything
        # meaningfully, so it fails this gate too.
        return False
    if not isinstance(benchmark, str) or not benchmark.strip():
        return True
    return primary.strip().upper() != benchmark.strip().upper()


def _gate_primary_not_sector_etf(
    c: dict[str, Any], *, allowlist: frozenset[str],
) -> bool:
    """Trust the upstream diagnostic's ``ticker_quality`` field.

    The diagnostic docstring states that ``bad_proxy`` covers the
    "primary is a known sector ETF" case (and the "primary equals
    benchmark" case, which gate 2 already catches).  An explicit
    allowlist can override the rejection — empty by default so the
    gate is conservative.
    """
    primary = c.get("primary_ticker")
    if isinstance(primary, str) and primary.strip().upper() in allowlist:
        return True
    quality = c.get("ticker_quality")
    return quality != "bad_proxy"


def _gate_price_cache_coverage(c: dict[str, Any]) -> bool:
    return bool(c.get("price_cache_available"))


def _gate_benchmark_adjusted_evidence(c: dict[str, Any]) -> bool:
    return bool(c.get("benchmark_adjusted_evidence_available"))


def _gate_persistence_signal_available(c: dict[str, Any]) -> bool:
    sig = c.get("persistence_signal")
    return sig is not None and sig != ""


def _gate_no_duplicate_narrative(c: dict[str, Any]) -> bool:
    tags = c.get("diagnostic_tags") or []
    if not isinstance(tags, list):
        return True
    return "duplicate_narrative" not in tags


# Gate 8 is a meta / ranking gate — no per-row predicate.
_GATE_EVALUATORS: dict[str, Callable[[dict[str, Any]], bool] | None] = {
    "primary_ticker_present":       _gate_primary_ticker_present,
    "primary_neq_benchmark":        _gate_primary_neq_benchmark,
    "primary_not_sector_etf":       None,   # handled separately for allowlist
    "price_cache_coverage":         _gate_price_cache_coverage,
    "benchmark_adjusted_evidence":  _gate_benchmark_adjusted_evidence,
    "persistence_signal_available": _gate_persistence_signal_available,
    "no_duplicate_narrative":       _gate_no_duplicate_narrative,
    "rank_by_evidence_strength":    None,   # ranking-only meta gate
}


def _evaluate_gate(
    gate_id: str, candidate: dict[str, Any], *,
    sector_etf_allowlist: frozenset[str],
) -> bool | None:
    """Return True/False for an eligibility gate; ``None`` for the
    ranking gate (gate 8)."""
    if gate_id == "primary_not_sector_etf":
        return _gate_primary_not_sector_etf(
            candidate, allowlist=sector_etf_allowlist,
        )
    if gate_id == "rank_by_evidence_strength":
        return None
    fn = _GATE_EVALUATORS.get(gate_id)
    if fn is None:
        return None
    return bool(fn(candidate))


# ---------------------------------------------------------------------------
# Gate metadata — the surfaced prose stays inside the script (no
# fields are invented per-candidate; these are constants describing
# the proposal).
# ---------------------------------------------------------------------------


_GATE_METADATA: dict[str, dict[str, Any]] = {
    "primary_ticker_present": {
        "name":        "Require primary_ticker present",
        "requirement": (
            "A still-moving candidate must carry a non-empty "
            "primary_ticker value."
        ),
        "gate_type":          "eligibility",
        "diagnostic_signal":  "candidate.primary_ticker",
        "false_positive_risk": (
            "events whose primary ticker is genuinely unknown at the "
            "moment of the move would be excluded; the diagnostic "
            "ticker_quality field is the place to confirm whether "
            "the candidate could be repaired by a manual review."
        ),
        "defensible_default": True,
        "expected_benefit": (
            "removes candidates whose primary asset is undefined, "
            "which the section cannot render meaningfully."
        ),
    },
    "primary_neq_benchmark": {
        "name":        "Require primary_ticker != benchmark_ticker",
        "requirement": (
            "primary_ticker and benchmark_ticker (case-insensitive) "
            "must not be the same symbol."
        ),
        "gate_type":          "eligibility",
        "diagnostic_signal":  "candidate.primary_ticker, candidate.benchmark_ticker",
        "false_positive_risk": (
            "overlaps with the sector-ETF gate; both catch a "
            "primary that equals the benchmark when the benchmark is "
            "a sector ETF.  The overlap is acceptable — neither gate "
            "is required to be orthogonal."
        ),
        "defensible_default": True,
        "expected_benefit": (
            "removes degenerate rows where benchmark-adjusted "
            "evidence would compare a ticker against itself."
        ),
    },
    "primary_not_sector_etf": {
        "name":        "Reject sector ETF as primary unless explicitly allowed",
        "requirement": (
            "If the diagnostic's ticker_quality is 'bad_proxy' "
            "(primary is a sector ETF or equals the benchmark), "
            "block the candidate unless the symbol is in the "
            "explicit operator allowlist."
        ),
        "gate_type":          "eligibility",
        "diagnostic_signal":  "candidate.ticker_quality",
        "false_positive_risk": (
            "an operator-allowed sector ETF (e.g., XLE when the "
            "headline is genuinely sector-wide) would be over-"
            "rejected absent the allowlist; the allowlist is the "
            "documented escape hatch."
        ),
        "defensible_default": True,
        "expected_benefit": (
            "removes sector-ETF primaries that make the move "
            "indistinguishable from the benchmark."
        ),
    },
    "price_cache_coverage": {
        "name":        "Require price_cache coverage for primary and benchmark",
        "requirement": (
            "price_cache must carry rows for both the primary and "
            "the benchmark across the diagnostic's relevant window."
        ),
        "gate_type":          "eligibility",
        "diagnostic_signal":  "candidate.price_cache_available",
        "false_positive_risk": (
            "events whose cache rows are missing for a benign "
            "calendar reason (weekend, holiday, recent backfill "
            "lag) would be blocked; the diagnostic and the backfill-"
            "request tooling are the right next step before promoting."
        ),
        "defensible_default": True,
        "expected_benefit": (
            "removes candidates the surface cannot render a return "
            "for, which would otherwise emit blank cells or stale "
            "rows."
        ),
    },
    "benchmark_adjusted_evidence": {
        "name":        "Require benchmark-adjusted evidence available",
        "requirement": (
            "A benchmark-adjusted evidence record must exist on file "
            "for the event."
        ),
        "gate_type":          "eligibility",
        "diagnostic_signal":  "candidate.benchmark_adjusted_evidence_available",
        "false_positive_risk": (
            "recent events whose evidence packet has not yet been "
            "produced would be blocked even when the move is real; "
            "the cohort review workflow is the right next step "
            "before promoting."
        ),
        "defensible_default": True,
        "expected_benefit": (
            "removes candidates that have no benchmark-adjusted "
            "context to support the 'still moving' claim."
        ),
    },
    "persistence_signal_available": {
        "name":        "Require persistence signal available",
        "requirement": (
            "A persistence signal value must be recorded for the "
            "event."
        ),
        "gate_type":          "eligibility",
        "diagnostic_signal":  "candidate.persistence_signal",
        "false_positive_risk": (
            "the persistence-signal pipeline may not have produced "
            "a record for a very fresh event; blocking too early is "
            "the trade-off versus surfacing a 'still moving' "
            "claim with no signal to back it."
        ),
        "defensible_default": True,
        "expected_benefit": (
            "removes candidates whose persistence claim is not "
            "backed by a recorded signal — the central failure mode "
            "the still-moving surface needs to avoid."
        ),
    },
    "no_duplicate_narrative": {
        "name":        "Group duplicate narratives before ranking",
        "requirement": (
            "Candidates flagged 'duplicate_narrative' must be "
            "grouped behind one canonical representative before "
            "they enter the still-moving ranking."
        ),
        "gate_type":          "eligibility",
        "diagnostic_signal":  "candidate.diagnostic_tags",
        "false_positive_risk": (
            "two genuinely distinct events with similar headlines "
            "could be over-merged; the duplicate-narrative detection "
            "is conservative, so the false-merge rate is bounded by "
            "the upstream diagnostic's choices."
        ),
        "defensible_default": True,
        "expected_benefit": (
            "removes near-duplicate rows that crowd out distinct "
            "candidates in the surface."
        ),
    },
    "rank_by_evidence_strength": {
        "name":        "Rank by evidence strength, not LLM confidence",
        "requirement": (
            "Among candidates that clear the eligibility gates, "
            "rank by recorded evidence strength (benchmark-adjusted "
            "abnormal return magnitude, persistence-signal "
            "magnitude) rather than by upstream LLM confidence "
            "scores."
        ),
        "gate_type":          "ranking",
        "diagnostic_signal":  None,
        "false_positive_risk": (
            "evidence-strength ranking depends on the upstream "
            "evidence record being well-calibrated across events; "
            "a miscalibrated evidence field would reorder the "
            "surface in misleading ways.  The ranking change should "
            "ship with a calibration check."
        ),
        "defensible_default": True,
        "expected_benefit": (
            "removes the reliance on LLM-side confidence values "
            "that are not anchored in observable market data."
        ),
    },
}


# ---------------------------------------------------------------------------
# Patchable seam — tests inject a synthetic diagnostic dict.
# ---------------------------------------------------------------------------


def _load_diagnostic(
    path: str, *, warnings: list[str], errors: list[str],
) -> dict[str, Any]:
    """Load the diagnostic snapshot JSON read-only.  Missing path
    surfaces a warning and returns an empty diagnostic; malformed
    JSON surfaces an error and returns empty."""
    p = Path(path)
    if not p.exists():
        warnings.append(
            f"diagnostic snapshot missing: {path}; proposal will "
            f"surface zero candidates"
        )
        return {}
    try:
        with p.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except OSError as exc:
        errors.append(f"failed to read diagnostic snapshot {path}: {exc}")
        return {}
    except json.JSONDecodeError as exc:
        errors.append(f"failed to parse diagnostic snapshot {path}: {exc}")
        return {}
    if not isinstance(payload, dict):
        warnings.append(
            f"diagnostic snapshot {path} is not a JSON object; ignored"
        )
        return {}
    return payload


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def build_proposal(
    *,
    diagnostic_path: str = _DEFAULT_DIAGNOSTIC_PATH,
    diagnostic:      dict[str, Any] | None = None,
    sector_etf_allowlist: Sequence[str] = (),
    blocked_example_cap: int = _DEFAULT_BLOCKED_EXAMPLE_CAP,
    allowed_example_cap: int = _DEFAULT_ALLOWED_EXAMPLE_CAP,
    output_path:     str | None = None,
) -> dict[str, Any]:
    """Compose the gate proposal envelope.

    ``diagnostic`` overrides ``diagnostic_path`` when supplied — this
    is the function-API shortcut tests use to avoid round-tripping
    through disk.  See module docstring for the full output contract.
    """
    warnings: list[str] = []
    errors:   list[str] = []

    if diagnostic is None:
        diagnostic = _load_diagnostic(
            diagnostic_path, warnings=warnings, errors=errors,
        )

    candidates = diagnostic.get("candidates") if isinstance(diagnostic, dict) else None
    if not isinstance(candidates, list):
        candidates = []

    allowlist = frozenset(
        s.strip().upper() for s in sector_etf_allowlist
        if isinstance(s, str) and s.strip()
    )

    # Per-candidate gate-result matrix.  Each row maps gate_id -> bool
    # (or None for the ranking gate).
    matrix: list[dict[str, bool | None]] = []
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        row: dict[str, bool | None] = {}
        for gate_id in _GATE_ORDER:
            row[gate_id] = _evaluate_gate(
                gate_id, cand, sector_etf_allowlist=allowlist,
            )
        matrix.append(row)

    failure_counts: dict[str, int | None] = {}
    pass_counts:    dict[str, int | None] = {}
    for gate_id in _GATE_ORDER:
        if _GATE_METADATA[gate_id]["gate_type"] == "ranking":
            failure_counts[gate_id] = None
            pass_counts[gate_id]    = None
            continue
        failures = sum(1 for row in matrix if row[gate_id] is False)
        passes   = sum(1 for row in matrix if row[gate_id] is True)
        failure_counts[gate_id] = failures
        pass_counts[gate_id]    = passes

    proposed_gates = []
    for gate_id in _GATE_ORDER:
        meta = _GATE_METADATA[gate_id]
        proposed_gates.append({
            "gate_id":             gate_id,
            "name":                meta["name"],
            "requirement":         meta["requirement"],
            "gate_type":           meta["gate_type"],
            "diagnostic_signal":   meta["diagnostic_signal"],
            "failure_count":       failure_counts[gate_id],
            "pass_count":          pass_counts[gate_id],
            "false_positive_risk": meta["false_positive_risk"],
            "defensible_default":  meta["defensible_default"],
            "expected_benefit":    meta["expected_benefit"],
        })

    examples_blocked_by_gate = _collect_blocked_examples(
        candidates=candidates, matrix=matrix, cap=blocked_example_cap,
    )
    examples_allowed_by_gate = _collect_allowed_examples(
        candidates=candidates, matrix=matrix, cap=allowed_example_cap,
    )

    defensible_requirements = [
        meta["requirement"]
        for gate_id in _GATE_ORDER
        for meta in (_GATE_METADATA[gate_id],)
    ]

    envelope = {
        "ok":                              not errors,
        "candidates_analyzed":             len(matrix),
        "proposed_gates":                  proposed_gates,
        "gate_failure_counts":             failure_counts,
        "defensible_candidate_requirements": defensible_requirements,
        "examples_blocked_by_gate":        examples_blocked_by_gate,
        "examples_allowed_by_gate":        examples_allowed_by_gate,
        "warnings":                        warnings,
        "errors":                          errors,
    }

    if output_path:
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(envelope, fh, indent=2, sort_keys=True, default=str)
        except OSError as exc:
            envelope["errors"].append(
                f"failed to write --output {output_path}: {exc}"
            )
            envelope["ok"] = False

    return envelope


# ---------------------------------------------------------------------------
# Example collectors
# ---------------------------------------------------------------------------


def _example(c: dict[str, Any]) -> dict[str, Any]:
    """Project a candidate into a small example dict carrying only
    the operator-facing identifiers."""
    return {
        "event_id":         c.get("event_id"),
        "headline":         c.get("headline"),
        "primary_ticker":   c.get("primary_ticker"),
        "benchmark_ticker": c.get("benchmark_ticker"),
        "event_date":       c.get("event_date"),
    }


def _collect_blocked_examples(
    *,
    candidates: list[dict[str, Any]],
    matrix:     list[dict[str, bool | None]],
    cap:        int,
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {
        gate_id: [] for gate_id in _GATE_ORDER
        if _GATE_METADATA[gate_id]["gate_type"] != "ranking"
    }
    for cand, row in zip(candidates, matrix):
        if not isinstance(cand, dict):
            continue
        for gate_id in out.keys():
            if row.get(gate_id) is False and len(out[gate_id]) < max(1, cap):
                example = _example(cand)
                example["blocked_by_gate"] = gate_id
                out[gate_id].append(example)
    return out


def _collect_allowed_examples(
    *,
    candidates: list[dict[str, Any]],
    matrix:     list[dict[str, bool | None]],
    cap:        int,
) -> list[dict[str, Any]]:
    eligibility_gates = [
        gate_id for gate_id in _GATE_ORDER
        if _GATE_METADATA[gate_id]["gate_type"] != "ranking"
    ]
    out: list[dict[str, Any]] = []
    for cand, row in zip(candidates, matrix):
        if not isinstance(cand, dict):
            continue
        if all(row[g] is True for g in eligibility_gates):
            out.append(_example(cand))
            if len(out) >= max(1, cap):
                break
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "Still Moving Market — gate proposal",
        "",
        f"OK:                   {report['ok']}",
        f"candidates_analyzed:  {report['candidates_analyzed']}",
        "",
        "Proposed gates:",
    ]
    for gate in report.get("proposed_gates") or []:
        fc = gate.get("failure_count")
        pc = gate.get("pass_count")
        fc_disp = "n/a" if fc is None else str(fc)
        pc_disp = "n/a" if pc is None else str(pc)
        lines.append(
            f"  [{gate.get('gate_id')}] type={gate.get('gate_type')} "
            f"pass={pc_disp}  fail={fc_disp}"
        )
        lines.append(f"      {gate.get('name')}")
        lines.append(f"      requirement: {gate.get('requirement')}")
        lines.append(
            f"      expected_benefit: {gate.get('expected_benefit')}"
        )
        lines.append(
            f"      false_positive_risk: "
            f"{gate.get('false_positive_risk')}"
        )
    lines.append("")
    lines.append("Examples blocked by gate (capped):")
    for gate_id, examples in (
        (report.get("examples_blocked_by_gate") or {}).items()
    ):
        if not examples:
            continue
        lines.append(f"  - {gate_id}:")
        for ex in examples:
            lines.append(
                f"      event_id={ex.get('event_id')} "
                f"primary={ex.get('primary_ticker')} "
                f"benchmark={ex.get('benchmark_ticker')}"
            )
    lines.append("")
    lines.append("Examples allowed by all eligibility gates (capped):")
    for ex in report.get("examples_allowed_by_gate") or []:
        lines.append(
            f"  - event_id={ex.get('event_id')} "
            f"primary={ex.get('primary_ticker')} "
            f"benchmark={ex.get('benchmark_ticker')}"
        )
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


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Still Moving Market gate proposal.  Reads a "
            "saved still-moving diagnostic snapshot and proposes "
            "eight concrete eligibility / ranking gates with their "
            "per-gate pass / fail counts and small example sets.  "
            "No still-moving filter is applied.  No DB writes, no "
            "provider, no LLM, no FastAPI.  Conservative wording — "
            "the proposal is a study aid, not authorisation."
        ),
    )
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument(
        "--json", action="store_true",
        help="Emit JSON (default if neither flag is passed).",
    )
    fmt.add_argument(
        "--text", action="store_true",
        help="Emit the compact text layout.",
    )
    parser.add_argument(
        "--diagnostic-path", dest="diagnostic_path",
        default=_DEFAULT_DIAGNOSTIC_PATH,
        help=(
            "Path to a saved still-moving diagnostic JSON snapshot "
            f"(default {_DEFAULT_DIAGNOSTIC_PATH}).  Missing files "
            f"are surfaced as warnings, not errors."
        ),
    )
    parser.add_argument(
        "--sector-etf-allowlist", dest="sector_etf_allowlist",
        action="append", default=[],
        help=(
            "Symbol to exempt from the sector-ETF gate.  Pass the "
            "flag multiple times for multiple symbols.  Empty by "
            "default — the gate is conservative."
        ),
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope to.  When "
            "omitted, the proposal has no filesystem side effect."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = build_proposal(
        diagnostic_path=args.diagnostic_path,
        sector_etf_allowlist=tuple(args.sector_etf_allowlist or ()),
        output_path=args.output_path,
    )

    if args.text:
        print(_render_text(report), file=output)
    else:
        print(_render_json(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "build_proposal",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
