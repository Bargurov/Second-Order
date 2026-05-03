"""Research-study export composer — portable bundles for saved studies.

Makes the research layer usable outside the live UI by turning
saved-study configs (see ``saved_studies.py``) into replayable bundles
the caller can save to disk, email, or paste into a memo.

The bundle is *always* replayed against live events at export time
(never cached), so the numbers are current.  Saved studies store only
the config — the deterministic input shape — and this module executes
that config against whatever archive it's given.

Design discipline
-----------------
* Pure composer.  No I/O.  Never raises on malformed input — unknown
  study types or invalid configs are captured as per-study ``error``
  entries in the output so one bad study doesn't poison the bundle.
* Every per-study output block is annotated with the study type, the
  config that produced it, and the study name so a consumer can
  reconstruct the run without the saved-studies table.
* Markdown formatter is intentionally small: a single function that
  walks the bundle and emits a plain text/markdown summary.  Not a
  parallel rendering engine — just a human-readable echo.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from saved_studies import STUDY_TYPE_IDS


# ---------------------------------------------------------------------------
# Study replay
# ---------------------------------------------------------------------------

def _replay_cohort_comparison(
    events: list[dict], config: dict,
) -> dict[str, Any]:
    from cohort_comparison import compare_cohorts_by_filter
    return compare_cohorts_by_filter(
        events,
        config.get("filter_a") or {},
        config.get("filter_b") or {},
        label_a=config.get("label_a"),
        label_b=config.get("label_b"),
    )


def _replay_correlation_study(
    events: list[dict], config: dict,
) -> dict[str, Any]:
    from cross_event_studies import compute_cross_event_studies
    return compute_cross_event_studies(events)


def _replay_scenario_pack_research(
    events: list[dict], config: dict,
) -> dict[str, Any]:
    from cohort_research import run_batch_research
    pack = config.get("pack_name")
    return run_batch_research(
        events,
        scenario_pack=pack,
        cohort_label=pack,
    )


def _replay_cascade_view(
    events: list[dict], config: dict,
) -> dict[str, Any]:
    """Cascade view uses the full graph as the data source and then
    filters edges by the config (family / min_weight / active_only /
    focal_event_id).  The original graph envelope is preserved."""
    from event_graph import build_event_graph
    graph = build_event_graph(events)
    family = config.get("family")
    min_weight = config.get("min_weight")
    active_only = config.get("active_only")
    focal = config.get("focal_event_id")

    # Node lookup so family filtering against parent/child nodes is O(1).
    by_id = {n.get("id"): n for n in graph.get("nodes") or []}

    def _keep(edge: dict) -> bool:
        if active_only and not edge.get("active"):
            return False
        if min_weight is not None and float(edge.get("weight") or 0.0) < float(min_weight):
            return False
        if focal is not None and focal not in (edge.get("parent_id"), edge.get("child_id")):
            return False
        if family:
            parent_fam = (by_id.get(edge.get("parent_id")) or {}).get("mechanism_family")
            child_fam = (by_id.get(edge.get("child_id")) or {}).get("mechanism_family")
            if family not in (parent_fam, child_fam):
                return False
        return True

    filtered = [e for e in (graph.get("edges") or []) if _keep(e)]
    return {
        **graph,
        "edges":        filtered,
        "active_edges": sum(1 for e in filtered if e.get("active")),
        "total_edges":  len(filtered),
        "filter":       {
            "family":         family,
            "min_weight":     min_weight,
            "active_only":    bool(active_only),
            "focal_event_id": focal,
        },
    }


def _replay_portfolio_view(
    events: list[dict], config: dict,
) -> dict[str, Any]:
    """Replay a saved ``portfolio_view`` against ``events`` using the
    same filter vocabulary the live ``/portfolio`` route accepts.

    The saved config carries any / all of
    ``mover_window | queue | thesis_state | proof_quality |
    low_information | quality_tier | tradable | mechanism_subtype``.
    Replay projects each event through the existing thesis / proof /
    queue classifiers, walks the mover window index (when available),
    composes the engine-phase compact surface, and returns the
    filtered set + per-filter counts so the export reader can see what
    was dropped.

    Deliberately pure: when the live mover slices aren't reachable
    (standalone tests, offline export pipelines) the ``mover_window``
    filter degrades to no-op rather than raising.
    """
    from engine_phase_surface import decorate_compact
    from family_inference import resolve_effective_family
    from portfolio_flags import (
        classify_queues, portfolio_flags, proof_quality_bucket,
    )
    from thesis_state import derive_thesis_state, derive_validation_rationale
    from validation_outcome import _extract_primary_set, score_weighted_evidence

    event_window_index: dict[int, list[str]] = {}
    try:
        from mover_context import build_event_window_index
        from routes.movers import load_ui_slices_for_event_context
        event_window_index = build_event_window_index(
            load_ui_slices_for_event_context()
        )
    except Exception:
        event_window_index = {}

    filters = {
        "mover_window":      config.get("mover_window") or None,
        "queue":             config.get("queue") or None,
        "thesis_state":      config.get("thesis_state") or None,
        "proof_quality":     config.get("proof_quality") or None,
        "low_information":   config.get("low_information")
        if isinstance(config.get("low_information"), bool) else None,
        "quality_tier":      config.get("quality_tier") or None,
        "tradable":          config.get("tradable")
        if isinstance(config.get("tradable"), bool) else None,
        "mechanism_subtype": config.get("mechanism_subtype") or None,
    }

    items: list[dict[str, Any]] = []
    total_considered = 0
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        total_considered += 1
        ev_work = dict(ev)
        ev_work["mechanism_family"] = resolve_effective_family(ev_work)
        flags = portfolio_flags(ev_work)
        weighted = score_weighted_evidence(
            ev_work.get("market_tickers") or [],
            explicit_primary=_extract_primary_set(ev_work),
        )
        ev_ctx = {
            **ev_work,
            "weighted_evidence": weighted,
            "has_proof_set":     flags["has_proof_set"],
            "has_falsifiers":    flags["has_falsifiers"],
            "low_information":   flags["low_information"],
        }
        ts_state = derive_thesis_state(ev_ctx)
        ts_validation_rationale = derive_validation_rationale(
            ev_ctx, state=ts_state,
        )
        pq = proof_quality_bucket(ev_ctx)
        queues = classify_queues({
            "thesis_state":    ts_state,
            "low_information": flags["low_information"],
            "has_falsifiers":  flags["has_falsifiers"],
            "stale_signal":    ev_ctx.get("stale_signal"),
        })
        ev_windows = event_window_index.get(ev_work.get("id"), []) or []

        if filters["thesis_state"] is not None and ts_state != filters["thesis_state"]:
            continue
        if filters["proof_quality"] is not None and pq != filters["proof_quality"]:
            continue
        if filters["low_information"] is not None:
            if bool(flags["low_information"]) != filters["low_information"]:
                continue
        if filters["queue"] is not None and filters["queue"] not in queues:
            continue
        if filters["mover_window"] is not None and filters["mover_window"] not in ev_windows:
            continue

        # Engine-phase compact surface — composed AFTER the cheap
        # filters above so we don't pay the composer cost on rows the
        # legacy filters already dropped.
        compact = decorate_compact(ev_work)
        if filters["quality_tier"] is not None and compact.get("quality_tier") != filters["quality_tier"]:
            continue
        if filters["tradable"] is not None:
            ac = compact.get("actionability_check") or {}
            if bool(ac.get("tradable", False)) != filters["tradable"]:
                continue
        if filters["mechanism_subtype"] is not None and compact.get("mechanism_subtype") != filters["mechanism_subtype"]:
            continue

        items.append({
            "id":              ev_work.get("id"),
            "headline":        ev_work.get("headline"),
            "event_date":      ev_work.get("event_date"),
            "mechanism_family": ev_work.get("mechanism_family"),
            "thesis_state":    ts_state,
            "validation_rationale": ts_validation_rationale,
            "proof_quality":   pq,
            "queues":          queues,
            "mover_windows":   ev_windows,
            "low_information": bool(flags["low_information"]),
            "quality_tier":      compact.get("quality_tier"),
            "tradable":          (compact.get("actionability_check") or {}).get("tradable"),
            "mechanism_subtype": compact.get("mechanism_subtype"),
        })

    return {
        "filters":          {k: v for k, v in filters.items() if v is not None},
        "total_considered": total_considered,
        "total_matched":    len(items),
        "items":            items,
    }


_REPLAY_DISPATCH = {
    "cohort_comparison":      _replay_cohort_comparison,
    "correlation_study":      _replay_correlation_study,
    "scenario_pack_research": _replay_scenario_pack_research,
    "cascade_view":           _replay_cascade_view,
    "portfolio_view":         _replay_portfolio_view,
}


def replay_study(
    study_type: str,
    config: Optional[dict],
    events: Optional[list[dict]],
) -> dict[str, Any]:
    """Run the composer matching ``study_type`` against ``events``.

    Returns ``{output, error}`` — at most one of the two is populated.
    Unknown study types, malformed configs, or composer exceptions are
    caught and surfaced as ``error`` so the bundle shape stays stable.
    """
    events = events or []
    cfg = config if isinstance(config, dict) else {}
    if study_type not in _REPLAY_DISPATCH:
        return {
            "output": None,
            "error":  f"unknown study_type={study_type!r}",
        }
    try:
        output = _REPLAY_DISPATCH[study_type](events, cfg)
        return {"output": output, "error": None}
    except Exception as exc:   # noqa: BLE001 — narrow catch not useful here
        return {"output": None, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Bundle composer
# ---------------------------------------------------------------------------

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_research_bundle(
    events: Optional[list[dict]],
    studies: Optional[Iterable[dict]],
) -> dict[str, Any]:
    """Assemble a portable export bundle from a list of study specs.

    Args:
        events:  Archive events to replay against.
        studies: Iterable of study-spec dicts.  Each must have
                 ``study_type`` and ``config``; optional ``name``,
                 ``description``, ``id`` for provenance.

    Returns:
        {
          "generated_at": iso8601,
          "total_events": int,
          "studies": [
            {id?, name?, description?, study_type, config, output?, error?},
          ],
          "counts": {"studies": int, "errored": int, "succeeded": int},
        }

    Never raises.  Individual study failures land in per-entry ``error``
    fields so callers can still export partial bundles.
    """
    events = events or []
    out_entries: list[dict[str, Any]] = []
    errored = 0

    for spec in studies or []:
        if not isinstance(spec, dict):
            out_entries.append({
                "study_type": None,
                "config":     None,
                "output":     None,
                "error":      "non-dict study spec",
            })
            errored += 1
            continue
        study_type = spec.get("study_type")
        config = spec.get("config") or {}
        replayed = replay_study(study_type, config, events)

        entry: dict[str, Any] = {
            "study_type": study_type,
            "config":     config,
            "output":     replayed["output"],
            "error":      replayed["error"],
        }
        for opt in ("id", "name", "description"):
            if opt in spec and spec[opt] is not None:
                entry[opt] = spec[opt]
        if replayed["error"]:
            errored += 1
        out_entries.append(entry)

    return {
        "generated_at": _utcnow_iso(),
        "total_events": len(events),
        "studies":      out_entries,
        "counts": {
            "studies":   len(out_entries),
            "errored":   errored,
            "succeeded": len(out_entries) - errored,
        },
    }


# ---------------------------------------------------------------------------
# Markdown formatter — single human-readable echo, not a second engine.
# ---------------------------------------------------------------------------

def _fmt_pct(v: Any) -> str:
    if isinstance(v, (int, float)):
        return f"{int(round(float(v) * 100))}%"
    return "—"


def _fmt_signed_pp(v: Any) -> str:
    if isinstance(v, (int, float)):
        sign = "+" if v > 0 else ""
        return f"{sign}{float(v):.1f}%"
    return "—"


def _md_cohort_comparison(output: dict) -> list[str]:
    lines = []
    insight = output.get("headline_insight") or ""
    if insight:
        lines.append(f"> {insight}")
    lines.append("")
    a_label = output.get("a_label") or "A"
    b_label = output.get("b_label") or "B"
    a_size = output.get("a_size") or 0
    b_size = output.get("b_size") or 0
    score = output.get("divergence_score")
    basis = output.get("confidence_basis") or "thin"
    lines.append(
        f"**{a_label}** (n={a_size}) vs **{b_label}** (n={b_size}) · "
        f"divergence {score} · confidence {basis}"
    )
    lines.append("")
    lines.append("| Axis | A | B | Magnitude |")
    lines.append("|---|---|---|---|")
    for dim in output.get("dimensions") or []:
        axis = dim.get("axis", "")
        if axis in ("repricing_path",):
            a_val = dim.get("a_value")
            b_val = dim.get("b_value")
        elif axis in ("hold_rate", "failure_rate"):
            a_val = _fmt_pct(dim.get("a_value"))
            b_val = _fmt_pct(dim.get("b_value"))
        elif axis == "mean_20d":
            a_val = _fmt_signed_pp(dim.get("a_value"))
            b_val = _fmt_signed_pp(dim.get("b_value"))
        else:
            a_val = dim.get("a_top") or "—"
            b_val = dim.get("b_top") or "—"
        lines.append(f"| {axis} | {a_val} | {b_val} | {dim.get('magnitude', '—')} |")
    return lines


def _md_scenario_pack(output: dict) -> list[str]:
    lines = []
    summary = output.get("summary") or ""
    if summary:
        lines.append(f"> {summary}")
        lines.append("")
    rep = output.get("repricing_path") or {}
    per = output.get("persistence") or {}
    fal = output.get("falsification") or {}
    lines.append(
        f"size={output.get('size', 0)} · "
        f"typical repricing={rep.get('typical', '—')} "
        f"({_fmt_pct(rep.get('typical_share'))}) · "
        f"hold_rate={_fmt_pct(per.get('hold_rate'))} · "
        f"event_failure_rate={_fmt_pct(fal.get('event_failure_rate'))} · "
        f"confidence={output.get('confidence_basis', 'thin')}"
    )
    return lines


def _md_correlation_study(output: dict) -> list[str]:
    lines = []
    fams = output.get("family_cooccurrence") or []
    secs = output.get("sector_clusters") or []
    paths = output.get("path_clusters") or []
    lines.append(
        f"family pairs={len(fams)} · sector clusters={len(secs)} · "
        f"path clusters={len(paths)}"
    )
    for pair in fams[:5]:
        lines.append(
            f"- {pair.get('family_a')} × {pair.get('family_b')}: "
            f"{pair.get('cooccurrences', 0)} co-occurrences"
        )
    return lines


_PORTFOLIO_VIEW_MAX_ROWS: int = 25


def _md_portfolio_view(output: dict) -> list[str]:
    """Markdown render for a replayed ``portfolio_view``.

    Three sections: a compact filter echo (only filters that fired
    appear), a one-line count summary, and a markdown table of the
    matched events capped at ``_PORTFOLIO_VIEW_MAX_ROWS`` so a
    100-event archive doesn't produce a wall of rows.  The table
    surfaces the engine-phase fields (tier / tradable / subtype)
    alongside thesis / proof labels so a reader can scan filter
    coverage at a glance.

    Stays purely formatting; the replay layer is the single source of
    truth for the ids and counts.
    """
    if not isinstance(output, dict):
        return []
    filters = output.get("filters") or {}
    items = output.get("items") or []
    total_considered = output.get("total_considered", 0)
    total_matched = output.get("total_matched", len(items))

    def _fmt_filter(value: Any) -> str:
        if isinstance(value, bool):
            return "yes" if value else "no"
        return str(value)

    lines: list[str] = []
    if filters:
        echo = " · ".join(
            f"{key}={_fmt_filter(filters[key])}"
            for key in (
                # Engine-phase first so the new filters lead the echo;
                # legacy filters trail.  Only keys actually present
                # render, so a saved view that pinned just one filter
                # echoes a single chip.
                "quality_tier", "tradable", "mechanism_subtype",
                "thesis_state", "proof_quality", "low_information",
                "queue", "mover_window",
            )
            if key in filters
        )
        lines.append(f"**filters:** {echo}")
    else:
        lines.append("_no filters — every archive event matched_")

    lines.append("")
    lines.append(
        f"matched **{total_matched}** of {total_considered} archive event"
        f"{'s' if total_considered != 1 else ''}"
    )
    lines.append("")

    if not items:
        lines.append("_no events matched the saved filters_")
        return lines

    lines.append("| id | date | headline | tier | tradable | subtype | thesis | proof |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for item in items[:_PORTFOLIO_VIEW_MAX_ROWS]:
        if not isinstance(item, dict):
            continue
        tradable = item.get("tradable")
        tradable_str = (
            "yes" if tradable is True
            else "no" if tradable is False
            else "—"
        )
        # Pipe characters in headlines would break the row; escape
        # defensively.  Cap at 80 chars so a long headline doesn't
        # wreck the table on narrow viewers.
        headline = (item.get("headline") or "").replace("|", "\\|")
        if len(headline) > 80:
            headline = headline[:77] + "…"
        lines.append(
            "| {id} | {date} | {headline} | {tier} | {tradable} | "
            "{subtype} | {thesis} | {proof} |".format(
                id=item.get("id", "—"),
                date=item.get("event_date") or "—",
                headline=headline or "—",
                tier=item.get("quality_tier") or "—",
                tradable=tradable_str,
                subtype=item.get("mechanism_subtype") or "—",
                thesis=item.get("thesis_state") or "—",
                proof=item.get("proof_quality") or "—",
            )
        )

    extra = len(items) - _PORTFOLIO_VIEW_MAX_ROWS
    if extra > 0:
        lines.append("")
        lines.append(
            f"_+{extra} more matched event{'s' if extra != 1 else ''} "
            f"omitted from the table — see the JSON export for the full set_"
        )
    return lines


def _md_cascade_view(output: dict) -> list[str]:
    lines = [
        f"nodes={len(output.get('nodes') or [])} · "
        f"active_edges={output.get('active_edges', 0)}/"
        f"{output.get('total_edges', 0)} · "
        f"half_life={output.get('decay_half_life_days', 0)}d · "
        f"window={output.get('pair_window_days', 0)}d",
    ]
    # Top-5 edges by weight for a quick scan of the strongest cascades.
    edges = sorted(
        output.get("edges") or [],
        key=lambda e: -float(e.get("weight") or 0.0),
    )[:5]
    for e in edges:
        lines.append(
            f"- {e.get('parent_id')} → {e.get('child_id')} · "
            f"w={e.get('weight', 0)} · age={e.get('age_days', 0)}d · "
            f"{e.get('rationale') or ''}"
        )
    return lines


_MD_BY_TYPE = {
    "cohort_comparison":      _md_cohort_comparison,
    "scenario_pack_research": _md_scenario_pack,
    "correlation_study":      _md_correlation_study,
    "cascade_view":           _md_cascade_view,
    "portfolio_view":         _md_portfolio_view,
}


def format_research_markdown(bundle: Optional[dict]) -> str:
    """Render a bundle as a plain markdown document.

    Returns an empty string on malformed input rather than raising —
    this is a portability helper, not a data contract.
    """
    if not isinstance(bundle, dict):
        return ""
    lines: list[str] = ["# Research Export", ""]
    lines.append(
        f"_Generated {bundle.get('generated_at', '?')} · "
        f"{bundle.get('total_events', 0)} archive events_"
    )
    lines.append("")
    counts = bundle.get("counts") or {}
    if counts:
        lines.append(
            f"Studies: {counts.get('studies', 0)} "
            f"({counts.get('succeeded', 0)} succeeded, "
            f"{counts.get('errored', 0)} errored)"
        )
        lines.append("")

    for i, entry in enumerate(bundle.get("studies") or [], start=1):
        if not isinstance(entry, dict):
            continue
        study_type = entry.get("study_type") or "unknown"
        name = entry.get("name") or f"Study #{i}"
        lines.append(f"## {i}. {name}")
        lines.append(f"*type:* `{study_type}`")
        if entry.get("description"):
            lines.append("")
            lines.append(entry["description"])
        lines.append("")
        if entry.get("error"):
            lines.append(f"**error:** {entry['error']}")
            lines.append("")
            continue
        output = entry.get("output") or {}
        renderer = _MD_BY_TYPE.get(study_type)
        if renderer:
            lines.extend(renderer(output))
        else:
            lines.append(f"_(no markdown renderer for {study_type!r})_")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# Expose the study-type enum so callers can validate without importing
# saved_studies directly.
SUPPORTED_STUDY_TYPES: tuple[str, ...] = STUDY_TYPE_IDS
