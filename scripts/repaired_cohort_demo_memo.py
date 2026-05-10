#!/usr/bin/env python3
"""Read-only evidence memo for the repaired-cohort validation summary.

Wraps :mod:`scripts.manual_repaired_cohort_validation_summary` through a
single patchable seam and renders a conservative evidence memo that
states EXACTLY what the current cohort supports — never more.

Why this layer exists
---------------------

The validation runner produces records, the summary distills them into
an 8-key dict, and this memo translates that dict into reviewer-facing
prose: a headline, the list of claims the data DO support, and the list
of claims the data do NOT support.  The split lets the lower layers stay
quantitative while the memo enforces conservative reviewer-grade
language.

What this memo says (current 5-event cohort)
--------------------------------------------

For the current state — 5 repaired clean events / 15 records / 0
FDR-significant aggregate results / event 73 carrying the
``validated_raw_only`` verdict — the memo states the evidence is
underpowered and recommends expanding the repaired cohort to 10–15
events before any aggregate statistical-validation claim.  Each of
those numeric facts is derived from the summary, not hard-coded; the
memo automatically restates whatever the cohort actually shows.

What this memo never says
-------------------------

* No claim of "proof" — every conclusion is framed as evidence, not
  established fact.
* No alpha-generation claim — the memo never asserts the strategy
  produces alpha.
* No predictive-edge claim — the memo never asserts the data show
  out-of-sample predictive ability.
* No causal claim — repaired cohort evidence is exploratory.

These restrictions are enforced by tests so the memo's language stays
conservative even as the underlying cohort grows.

Read-only by construction
-------------------------

* Calls through to the validation summary, which itself wraps the
  validation runner; this module never touches the live DB or the
  input backup.
* No DB writes.  No LLM, no FastAPI, no provider call.

Output contract
---------------

Stable 8-key dict::

    {
      "headline":              str,
      "evidence_state":        {...},
      "supported_claims":      [str, ...],
      "unsupported_claims":    [str, ...],
      "next_target":           str,
      "underpowered":          bool,
      "limitations":           [str, ...],
      "source_summary":        {...},
    }

``evidence_state`` carries the numeric facts the memo cites:
``repaired_clean_event_count``, ``repaired_clean_event_ids``,
``records_count``, ``fdr_significant_count``,
``validated_raw_only_event_ids``, ``validated_raw_only_count``,
``by_event_verdict``.

``source_summary`` echoes the full upstream summary dict so a reviewer
can drill from the memo's prose down to the numbers without re-running
the pipeline.

Patchable seam
--------------

* ``_run_validation_summary`` — wraps
  ``manual_repaired_cohort_validation_summary.summarize_repaired_cohort_validation``.
  Tests patch this seam directly.

Usage::

    python scripts/repaired_cohort_demo_memo.py --json --limit 50
    python scripts/repaired_cohort_demo_memo.py --text --limit 50
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_LIMIT:        int   = 50
_DEFAULT_ALPHA:        float = 0.05
_TARGET_MIN_EVENTS:    int   = 10
_TARGET_MAX_EVENTS:    int   = 15

_VERDICT_VALIDATED_RAW_ONLY: str = "validated_raw_only"


# ---------------------------------------------------------------------------
# Patchable seam — local to this module so tests patch a single
# surface.  The lazy import only fires on the un-patched path.
# ---------------------------------------------------------------------------


def _run_validation_summary(
    *,
    backup_path:          str | None,
    high_priority_csv:    str | None,
    medium_csv:           str | None,
    mechanism_family_csv: str | None = None,
    db_path:              str | None,
    limit:                int,
    alpha:                float,
) -> dict[str, Any]:
    """Invoke the manual-aware repaired-cohort validation SUMMARY and
    return its 8-key dict.  Tests patch this seam to drive the memo
    without re-running the upstream pipeline."""
    from scripts.manual_repaired_cohort_validation_summary import (
        summarize_repaired_cohort_validation,
    )

    return summarize_repaired_cohort_validation(
        backup_path=backup_path,
        high_priority_csv=high_priority_csv,
        medium_csv=medium_csv,
        mechanism_family_csv=mechanism_family_csv,
        db_path=db_path,
        limit=limit,
        alpha=alpha,
    )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def build_repaired_cohort_demo_memo(
    *,
    backup_path:          str | None = None,
    high_priority_csv:    str | None = None,
    medium_csv:           str | None = None,
    mechanism_family_csv: str | None = None,
    db_path:              str | None = None,
    limit:                int        = _DEFAULT_LIMIT,
    alpha:                float      = _DEFAULT_ALPHA,
    target_min_events:    int        = _TARGET_MIN_EVENTS,
    target_max_events:    int        = _TARGET_MAX_EVENTS,
) -> dict[str, Any]:
    """Build the read-only evidence memo from the validation summary.

    ``target_min_events`` / ``target_max_events`` define the operator
    cohort-expansion goal that surfaces in ``next_target`` and that
    drives the ``underpowered`` flag.  Defaults of 10 / 15 mirror the
    project goal: expand from the current 5-event pilot to a 10–15
    event cohort before any aggregate statistical-validation claim.
    """
    capped_limit = max(int(limit), 0)
    summary = _run_validation_summary(
        backup_path=backup_path,
        high_priority_csv=high_priority_csv,
        medium_csv=medium_csv,
        mechanism_family_csv=mechanism_family_csv,
        db_path=db_path,
        limit=capped_limit,
        alpha=float(alpha),
    )
    return _compose_memo(
        summary=summary,
        target_min_events=int(target_min_events),
        target_max_events=int(target_max_events),
    )


def _compose_memo(
    *,
    summary:           dict[str, Any],
    target_min_events: int,
    target_max_events: int,
) -> dict[str, Any]:
    repaired_ids:      list[int]      = _coerce_int_list(
        summary.get("repaired_clean_event_ids") or []
    )
    repaired_count:    int            = len(repaired_ids)
    records_count:     int            = _coerce_int(summary.get("records_count"))
    fdr_significant:   int            = _coerce_int(
        summary.get("significant_count")
    )
    by_event_verdict:  dict[str, str] = {
        str(k): str(v)
        for k, v in (summary.get("by_event_verdict") or {}).items()
    }

    validated_raw_only_ids: list[int] = sorted(
        int(eid) for eid, verdict in by_event_verdict.items()
        if verdict == _VERDICT_VALIDATED_RAW_ONLY and _is_int_str(eid)
    )

    # "Underpowered" combines two reasons: cohort below the operator
    # target AND/OR no aggregate FDR-significant result.  Either alone
    # is enough — a 12-event cohort with 0 FDR-significant records is
    # still underpowered for an aggregate claim, and a tiny cohort with
    # one raw-p hit is not powered enough for an aggregate claim either.
    underpowered: bool = (
        repaired_count < target_min_events or fdr_significant == 0
    )

    headline = _build_headline(
        repaired_count=repaired_count,
        records_count=records_count,
        fdr_significant=fdr_significant,
        underpowered=underpowered,
    )
    supported_claims = _build_supported_claims(
        repaired_count=repaired_count,
        records_count=records_count,
        fdr_significant=fdr_significant,
        validated_raw_only_ids=validated_raw_only_ids,
    )
    unsupported_claims = _build_unsupported_claims()
    next_target = _build_next_target(
        repaired_count=repaired_count,
        target_min_events=target_min_events,
        target_max_events=target_max_events,
        underpowered=underpowered,
    )
    limitations = [
        s for s in (summary.get("limitations") or [])
        if isinstance(s, str)
    ]

    return {
        "headline":          headline,
        "evidence_state": {
            "repaired_clean_event_count":    repaired_count,
            "repaired_clean_event_ids":      list(repaired_ids),
            "records_count":                 records_count,
            "fdr_significant_count":         fdr_significant,
            "validated_raw_only_event_ids":  list(validated_raw_only_ids),
            "validated_raw_only_count":      len(validated_raw_only_ids),
            "by_event_verdict":              dict(by_event_verdict),
        },
        "supported_claims":   supported_claims,
        "unsupported_claims": unsupported_claims,
        "next_target":        next_target,
        "underpowered":       underpowered,
        "limitations":        limitations,
        "source_summary":     dict(summary),
    }


def _build_headline(
    *,
    repaired_count:  int,
    records_count:   int,
    fdr_significant: int,
    underpowered:    bool,
) -> str:
    record_word = "record" if records_count == 1 else "records"
    sig_word    = (
        "FDR-significant aggregate result"
        if fdr_significant == 1
        else "FDR-significant aggregate results"
    )
    suffix = " — evidence underpowered." if underpowered else "."
    return (
        f"Repaired cohort: N={repaired_count} events, "
        f"{records_count} {record_word}, "
        f"{fdr_significant} {sig_word}{suffix}"
    )


def _build_supported_claims(
    *,
    repaired_count:         int,
    records_count:          int,
    fdr_significant:        int,
    validated_raw_only_ids: list[int],
) -> list[str]:
    event_word  = "event" if repaired_count == 1 else "events"
    record_word = "record" if records_count == 1 else "records"
    sig_record  = "record" if fdr_significant == 1 else "records"

    claims = [
        f"{repaired_count} repaired clean {event_word} were validated; "
        f"{records_count} (event, horizon) {record_word} were produced.",
        f"{fdr_significant} {sig_record} cleared FDR multiple-testing "
        f"correction in aggregate.",
    ]
    if validated_raw_only_ids:
        ids_str = ", ".join(str(eid) for eid in validated_raw_only_ids)
        plural  = (
            "Event" if len(validated_raw_only_ids) == 1 else "Events"
        )
        claims.append(
            f"{plural} {ids_str} carry the validated_raw_only verdict "
            f"(at least one record cleared raw p<=alpha; this is NOT an "
            f"aggregate FDR-significant claim)."
        )
    else:
        claims.append(
            "No event carries the validated_raw_only verdict at the "
            "current alpha threshold."
        )
    return claims


def _build_unsupported_claims() -> list[str]:
    return [
        "No causal claim — repaired cohort evidence is exploratory, "
        "not confirmatory.",
        "No predictive-edge claim — sample size and design do not "
        "support an out-of-sample predictive claim.",
        "No 'proof' framing — the memo states what the data show, "
        "not that anything is established.",
        "No alpha-generation claim — the memo never asserts the "
        "strategy produces alpha.",
    ]


def _build_next_target(
    *,
    repaired_count:    int,
    target_min_events: int,
    target_max_events: int,
    underpowered:      bool,
) -> str:
    if repaired_count >= target_max_events and not underpowered:
        return (
            f"Repaired cohort already meets the {target_min_events}–"
            f"{target_max_events} event target with at least one "
            f"FDR-significant aggregate result; consider pre-registering "
            f"directional hypotheses and broadening to a larger expansion "
            f"before making any out-of-sample claim."
        )
    return (
        f"Expand the repaired cohort to {target_min_events}–"
        f"{target_max_events} events (currently {repaired_count}) "
        f"before making any aggregate statistical-validation claim."
    )


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _coerce_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _coerce_int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for v in value:
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            out.append(v)
            continue
        if isinstance(v, str) and v.strip():
            try:
                out.append(int(v.strip()))
            except ValueError:
                continue
    return sorted(set(out))


def _is_int_str(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    s = value.strip()
    if not s:
        return False
    if s[0] in "+-":
        s = s[1:]
    return s.isdigit()


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _wrap(text: str, *, width: int = 78, indent: str = "  ") -> str:
    return textwrap.fill(
        text, width=width,
        initial_indent=indent, subsequent_indent=indent,
    )


def _render_text(memo: dict[str, Any]) -> str:
    state = memo["evidence_state"]
    lines: list[str] = ["=== Repaired Cohort Demo Evidence Memo ==="]
    lines.append("")
    lines.append("Headline")
    lines.append("--------")
    lines.append(_wrap(memo["headline"]))
    lines.append("")

    lines.append("Evidence state")
    lines.append("--------------")
    lines.append(
        f"  repaired_clean_event_count:    "
        f"{state['repaired_clean_event_count']}"
    )
    lines.append(
        f"  repaired_clean_event_ids:      "
        f"{state['repaired_clean_event_ids']}"
    )
    lines.append(
        f"  records_count:                 {state['records_count']}"
    )
    lines.append(
        f"  fdr_significant_count:         "
        f"{state['fdr_significant_count']}"
    )
    lines.append(
        f"  validated_raw_only_event_ids:  "
        f"{state['validated_raw_only_event_ids']}"
    )
    lines.append(
        f"  underpowered:                  {memo['underpowered']}"
    )
    lines.append("")

    if state.get("by_event_verdict"):
        lines.append("Per-event verdict")
        lines.append("-----------------")
        verdict_map = state["by_event_verdict"]
        for ev_id_str in sorted(verdict_map.keys(), key=_safe_int_key):
            lines.append(
                f"  id={ev_id_str:>4}  {verdict_map[ev_id_str]}"
            )
        lines.append("")

    lines.append("Supported claims")
    lines.append("----------------")
    for claim in memo["supported_claims"]:
        lines.append(_wrap("- " + claim))
    lines.append("")

    lines.append("Unsupported claims (the memo NEVER asserts these)")
    lines.append("-------------------------------------------------")
    for claim in memo["unsupported_claims"]:
        lines.append(_wrap("- " + claim))
    lines.append("")

    lines.append("Next target")
    lines.append("-----------")
    lines.append(_wrap(memo["next_target"]))

    if memo["limitations"]:
        lines.append("")
        lines.append("Limitations")
        lines.append("-----------")
        for lim in memo["limitations"]:
            lines.append(_wrap("- " + lim))
    return "\n".join(lines)


def _safe_int_key(value: str) -> tuple[int, str]:
    try:
        return (0, f"{int(value):020d}")
    except (TypeError, ValueError):
        return (1, str(value))


def _render_json(memo: dict[str, Any]) -> str:
    return json.dumps(memo, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only evidence memo for the repaired-cohort "
            "validation summary.  Wraps "
            "manual_repaired_cohort_validation_summary through a "
            "single patchable seam and renders a conservative memo "
            "stating EXACTLY what the current cohort supports.  Never "
            "claims 'proof', alpha generation, or predictive edge."
        ),
    )
    parser.add_argument(
        "--backup-path", dest="backup_path", default=None,
        help="Path to the events DB backup (passed through).",
    )
    parser.add_argument(
        "--high-priority-csv", dest="high_priority_csv", default=None,
        help="Path to the high-priority manual ticker repair CSV.",
    )
    parser.add_argument(
        "--medium-csv", dest="medium_csv", default=None,
        help="Path to the medium-batch manual ticker repair CSV.",
    )
    parser.add_argument(
        "--mechanism-family-csv", dest="mechanism_family_csv",
        default=None,
        help="Optional path to the mechanism-family repair packet CSV.",
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Optional path to the LIVE events DB.  Hashed read-only "
            "by the runner; never opened for writes."
        ),
    )
    parser.add_argument(
        "--limit", type=int, default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced top_abs_sar list at N entries "
            f"(default {_DEFAULT_LIMIT})."
        ),
    )
    parser.add_argument(
        "--alpha", type=float, default=_DEFAULT_ALPHA,
        help=(
            f"Significance threshold forwarded to the summary "
            f"(default: {_DEFAULT_ALPHA})."
        ),
    )
    parser.add_argument(
        "--target-min-events", type=int, default=_TARGET_MIN_EVENTS,
        dest="target_min_events",
        help=(
            f"Lower bound of the operator cohort-expansion goal "
            f"(default {_TARGET_MIN_EVENTS}).  Drives the underpowered "
            f"flag and the next_target string."
        ),
    )
    parser.add_argument(
        "--target-max-events", type=int, default=_TARGET_MAX_EVENTS,
        dest="target_max_events",
        help=(
            f"Upper bound of the operator cohort-expansion goal "
            f"(default {_TARGET_MAX_EVENTS})."
        ),
    )
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Emit structured JSON.",
    )
    fmt.add_argument(
        "--text", action="store_true", dest="as_text",
        help="Emit the human-readable text memo (default).",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    memo = build_repaired_cohort_demo_memo(
        backup_path=args.backup_path,
        high_priority_csv=args.high_priority_csv,
        medium_csv=args.medium_csv,
        mechanism_family_csv=args.mechanism_family_csv,
        db_path=args.db_path,
        limit=int(args.limit),
        alpha=float(args.alpha),
        target_min_events=int(args.target_min_events),
        target_max_events=int(args.target_max_events),
    )
    if args.as_json:
        print(_render_json(memo), file=output)
    else:
        print(_render_text(memo), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
