"""
events_export.py
================

Pure, deterministic serializers for the saved event archive.

This module is intentionally I/O-light: it reuses :func:`db.load_recent_events`
for loading and exposes two serializers — ``build_json_export`` and
``build_csv_export`` — that take an already-loaded list of event dicts and
render a stable, research-friendly payload.

Design rules
------------
* No background jobs.  The endpoint calls these functions synchronously.
* Deterministic column order.  Reviewers should be able to diff two exports.
* Reuses :func:`db.load_recent_events` so any future schema additions flow
  through automatically.
* Empty archives produce a well-formed empty export (never an error).
* Nested lists/dicts (tickers, if_persists, etc.) are rendered as JSON
  strings in CSV so nothing is lost and downstream tools can re-parse them.
* A derived ``follow_through`` block exposes the best-by-magnitude 5d / 20d
  returns already stored in ``market_tickers``.  No new market pipeline.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from analyze_event import PERSISTED_OVERLAY_FIELDS
from db import load_recent_events
from overlay_sanitize import sanitize_overlay_block


# ---------------------------------------------------------------------------
# Single source of truth for which persisted overlays appear in user-facing
# exports.  ``regime_snapshot`` is intentionally excluded — it is an
# internal key used by the analog re-ranker, not a user-facing overlay.
#
# Both the bulk CSV/JSON paths here AND the single-event JSON export in
# api.py draw from this list, so a new persisted overlay shows up in every
# export format by updating PERSISTED_OVERLAY_FIELDS alone.
# ---------------------------------------------------------------------------

_EXPORT_OVERLAY_EXCLUDES: frozenset[str] = frozenset({"regime_snapshot"})

EXPORT_OVERLAY_FIELDS: tuple[str, ...] = tuple(
    f for f in PERSISTED_OVERLAY_FIELDS if f not in _EXPORT_OVERLAY_EXCLUDES
)


# ---------------------------------------------------------------------------
# CSV column order — kept stable for reproducible diffs across exports.
# Persisted overlay columns are appended at the end so historical readers
# that index by column name (the documented contract) keep working even
# when PERSISTED_OVERLAY_FIELDS grows.
# ---------------------------------------------------------------------------

_CSV_BASE_COLUMNS: tuple[str, ...] = (
    # Identifiers
    "id",
    "timestamp",
    "event_date",
    # Core classification
    "headline",
    "stage",
    "persistence",
    "confidence",
    # Stored labels / review state
    "rating",
    "model",
    "low_signal",
    "notes",
    # Analysis text
    "what_changed",
    "mechanism_summary",
    "market_note",
    # Serialized JSON lists / dicts
    "beneficiaries",
    "losers",
    "assets_to_watch",
    "transmission_chain",
    "if_persists",
    "currency_channel",
    "market_tickers",
    # Horizon-aware thesis structure — persisted as-is from the LLM.
    # The row's thesis_scorecard (computed in _enrich_event_for_export)
    # folds the 1d/5d/20d confirmation vs falsification reads against
    # the realised ticker returns.
    "horizon_checkpoints",
    # Derived follow-through (best return by magnitude from stored tickers)
    "followthrough_best_5d",
    "followthrough_best_20d",
    "followthrough_direction",
)


CSV_COLUMNS: tuple[str, ...] = _CSV_BASE_COLUMNS + EXPORT_OVERLAY_FIELDS


# ---------------------------------------------------------------------------
# Overlay projection helper — shared by JSON and CSV paths so sanitization
# happens at exactly one seam.
# ---------------------------------------------------------------------------


def _sanitized_overlay(ev: dict, field: str) -> dict:
    """Return ``ev[field]`` normalized via the overlay degraded contract.

    Missing / empty / non-dict persisted overlays become an explicit
    degraded block (available=False, stale=True, degraded=True,
    degraded_reason="no persisted <field> data") so the export can never
    silently drop a known overlay slot.
    """
    return sanitize_overlay_block(ev.get(field), name=field)


def _inject_sanitized_overlays(ev: dict) -> dict:
    """Return a shallow copy of ``ev`` with every export-facing overlay
    field replaced by its sanitized form.  Non-overlay fields are kept
    by reference (the caller is free to mutate them)."""
    out = dict(ev)
    for f in EXPORT_OVERLAY_FIELDS:
        out[f] = _sanitized_overlay(ev, f)
    return out


# ---------------------------------------------------------------------------
# Derived-field enrichment for exports
# ---------------------------------------------------------------------------
#
# Several macro-engine outputs (thesis_scorecard, finance_playbook,
# sector_rotation, funding_stress_mode) are computed at /analyze time
# but NOT persisted — they're either pure composers over other
# persisted fields (thesis_scorecard) or require live provider data
# (sector_rotation, funding_stress_mode).  The export surfaces should
# still reflect the deeper macro engine "where practical", so this
# helper recomputes the cheap ones from persisted data and attaches
# them to the event dict the export formatters consume.
#
# Contract:
#   * Pure function.  Never raises.  Any composer failure degrades to
#     an empty dict on that key (caller can detect absence).
#   * Does NOT pull live market data — exports must be deterministic
#     and fast on bulk archives.  Composers that need live macro (e.g.
#     sector_rotation) are deliberately NOT invoked here; they're
#     available through the live /analyze flow instead.

def enrich_event_with_derived(ev: dict) -> dict:
    """Return a copy of ``ev`` with derived export-facing blocks attached.

    Currently attaches:
      * ``thesis_scorecard`` — computed from ``horizon_checkpoints`` +
        ``market_tickers`` + ``revisit_snapshots`` (all persisted).
      * ``finance_playbook`` — synthesis composer over the above plus
        whatever ``regime_snapshot``/``credit_regime`` are already on
        the row.  Will degrade gracefully for blocks it can't see.
      * Engine-phase fields — ``quality_tier``, ``quality_warnings``,
        ``actionability_check``, ``counterfactual_check``,
        ``confidence_rationale``, ``validation_rationale``,
        ``thesis_timing``, ``critical_breakpoints``,
        ``evidence_sources`` — surfaced as top-level keys for the
        downloaded JSON.  ``thesis_timing`` /
        ``critical_breakpoints`` / ``evidence_sources`` lift out of
        their nested homes (``competing_thesis`` / ``hidden_mechanism``)
        so consumers don't have to navigate the nesting; the original
        copies stay in place.

    Non-derived fields are kept by reference.  The caller is free to
    mutate the returned dict further.
    """
    if not isinstance(ev, dict):
        return ev  # type: ignore[return-value]

    out = dict(ev)

    # thesis_scorecard is PURE over persisted fields.  Always safe to run.
    try:
        from thesis_scorecard import compute_thesis_scorecard
        out["thesis_scorecard"] = compute_thesis_scorecard(
            out.get("horizon_checkpoints"),
            out.get("market_tickers"),
            revisit_snapshots=out.get("revisit_snapshots"),
        )
    except Exception:
        out.setdefault("thesis_scorecard", {})

    # finance_playbook reads other composer outputs from the same dict.
    # Without live funding_stress_mode / sector_rotation it still emits
    # the regime + thesis lines and a partial base_case / coherence
    # read — that's the "where practical" part of the contract.
    try:
        from finance_playbook import compose_finance_playbook
        out["finance_playbook"] = compose_finance_playbook(out)
    except Exception:
        out.setdefault("finance_playbook", {})

    # Engine-phase fields — every composer below is a pure read over
    # already-persisted data.  Each catch-all degrades to the stable
    # empty shape so a partial event never breaks the export envelope.
    try:
        from low_information_gate import (
            compose_actionability_check,
            compose_confidence_rationale,
            compose_counterfactual_check,
            evidence_quality_tier,
            quality_warnings,
        )
        out["quality_tier"]         = evidence_quality_tier(out)
        out["quality_warnings"]     = quality_warnings(out)
        out["actionability_check"]  = compose_actionability_check(out)
        out["counterfactual_check"] = compose_counterfactual_check(out)
        out["confidence_rationale"] = compose_confidence_rationale(out)
    except Exception:
        out.setdefault("quality_tier",         "")
        out.setdefault("quality_warnings",     [])
        out.setdefault("actionability_check",  {})
        out.setdefault("counterfactual_check", {})
        out.setdefault("confidence_rationale", "")

    try:
        from thesis_state import derive_validation_rationale
        out["validation_rationale"] = derive_validation_rationale(out)
    except Exception:
        out.setdefault("validation_rationale", "")

    # thesis_timing and evidence_sources live inside competing_thesis;
    # critical_breakpoints lives inside hidden_mechanism.  Lift them
    # to top-level keys for the downloaded JSON without removing the
    # nested copies.  Top-level evidence_sources, when already attached
    # by an upstream producer, takes precedence over the nested copy.
    ct = out.get("competing_thesis") if isinstance(out.get("competing_thesis"), dict) else {}
    hm = out.get("hidden_mechanism") if isinstance(out.get("hidden_mechanism"), dict) else {}

    timing = ct.get("thesis_timing") if isinstance(ct, dict) else None
    out["thesis_timing"] = timing if isinstance(timing, dict) else {}

    breakpoints = hm.get("critical_breakpoints") if isinstance(hm, dict) else None
    out["critical_breakpoints"] = breakpoints if isinstance(breakpoints, list) else []

    existing_sources = out.get("evidence_sources")
    if not isinstance(existing_sources, list) or not existing_sources:
        nested = ct.get("evidence_sources") if isinstance(ct, dict) else None
        out["evidence_sources"] = nested if isinstance(nested, list) else []
    return out


# ---------------------------------------------------------------------------
# Derived follow-through helpers
# ---------------------------------------------------------------------------


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    # Drop NaN / inf silently — they should never appear in the export.
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _best_follow_through(
    tickers: list[dict] | None,
) -> tuple[float | None, float | None, str | None]:
    """Pick the best 5d and 20d returns (by magnitude) and the direction of
    the ticker that carries the best 5d number.

    Returns ``(best_5d, best_20d, direction)``.  Any component can be ``None``.
    """
    if not tickers:
        return None, None, None

    best_5d: float | None = None
    best_20d: float | None = None
    direction: str | None = None

    for t in tickers:
        r5 = _coerce_float(t.get("return_5d"))
        r20 = _coerce_float(t.get("return_20d"))
        if r5 is not None and (best_5d is None or abs(r5) > abs(best_5d)):
            best_5d = r5
            direction = t.get("direction") or direction
        if r20 is not None and (best_20d is None or abs(r20) > abs(best_20d)):
            best_20d = r20

    return best_5d, best_20d, direction


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------


def build_json_export(events: list[dict]) -> dict:
    """Return a JSON-serialisable payload capturing every export field.

    Shape::

        {
            "count": N,
            "events": [ {<event>, "follow_through": {...}}, ... ],
            "track_record_breakdown": {
                "schema": "track_record_breakdown.v1",
                "summary": {...},
                "by_mechanism_family": [...],
                "by_regime": [...],
                "by_compound_regime": [...],
            },
        }

    ``events`` should already be dicts with lists/dicts deserialised (the
    shape produced by :func:`db.load_recent_events`).  Persisted overlays
    are run through ``sanitize_overlay_block`` so frozen or empty overlays
    carry the uniform degraded contract instead of silently being ``{}``.

    The ``track_record_breakdown`` block is computed from the same event
    list so a memo template can pull mechanism / regime / compound-regime
    performance summaries without re-issuing a second API call.  On any
    composer failure it degrades to an empty dict so the event payload
    itself always ships.
    """
    enriched: list[dict] = []
    for ev in events:
        best_5d, best_20d, direction = _best_follow_through(ev.get("market_tickers"))
        out = _inject_sanitized_overlays(ev)
        out["follow_through"] = {
            "best_return_5d": best_5d,
            "best_return_20d": best_20d,
            "best_direction": direction,
        }
        # Attach derived macro-engine blocks (thesis_scorecard,
        # finance_playbook) so the JSON archive reflects the deeper
        # engine output, not only the raw persisted fields.
        out = enrich_event_with_derived(out)
        enriched.append(out)

    # Track-record breakdown: mechanism / regime / compound-regime slices
    # over the same event list.  Kept on the export envelope so a single
    # download carries both the event detail and the aggregate view.
    breakdown_block: dict = {}
    try:
        from track_record_breakdown import compute_track_record_breakdown
        from track_record_export import build_breakdown_json
        breakdown_block = build_breakdown_json(
            compute_track_record_breakdown(events),
        )
    except Exception:
        breakdown_block = {}

    return {
        "count": len(enriched),
        "events": enriched,
        "track_record_breakdown": breakdown_block,
    }


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


def _csv_cell(value: Any) -> str:
    """Render any value as a deterministic CSV cell.

    - ``None`` → empty string
    - list / dict → compact JSON (sorted keys, UTF-8 safe)
    - float → plain repr (the csv writer quotes if needed)
    - everything else → ``str(value)``
    """
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, bool):
        # Render as 0/1 to match the way low_signal is stored in SQLite.
        return "1" if value else "0"
    return str(value)


def build_csv_export(events: list[dict]) -> str:
    """Render events as a CSV string with a stable column order.

    Returns a string with the header row even when ``events`` is empty so
    downstream readers never have to handle two shapes.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)

    for ev in events:
        best_5d, best_20d, direction = _best_follow_through(ev.get("market_tickers"))
        derived = {
            "followthrough_best_5d": best_5d,
            "followthrough_best_20d": best_20d,
            "followthrough_direction": direction,
        }
        # Sanitize overlays once so CSV overlay cells carry the same
        # degraded contract as the JSON path.
        ev_view = _inject_sanitized_overlays(ev)
        row = [_csv_cell(derived.get(col, ev_view.get(col))) for col in CSV_COLUMNS]
        writer.writerow(row)

    return buf.getvalue()


# ---------------------------------------------------------------------------
# Loader wrapper (keeps the endpoint thin)
# ---------------------------------------------------------------------------


def load_events_for_export(limit: int | None = None) -> list[dict]:
    """Load events for export in a deterministic newest-first order.

    Reuses :func:`db.load_recent_events` with a generous default cap so the
    caller does not have to think about pagination.  ``limit`` can be
    overridden by the API layer to bound very large archives.
    """
    cap = limit if (limit is not None and limit > 0) else 10_000
    return load_recent_events(limit=cap)
