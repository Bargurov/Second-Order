"""
event_graph.py

Cross-event graph + cascade modelling.

Why this module
---------------
The archive already supports per-event analysis (single-event composers),
cross-event correlation (``cross_event_studies``), and cohort-level
research (``cohort_research`` + ``cohort_comparison``).  It does not
know how shocks *propagate* between specific events over time.

This module builds a directed graph where:

  * **Nodes** are archive events (every event, edge-connected or not —
    isolates still appear so the UI can render the full archive).
  * **Edges** are parent → child links from the earlier event to the
    later one.  An edge exists only when at least one "spillover
    component" fires, meaning the two events share a mechanism family,
    a transmission-path signature, some assets, or some sectors.
  * **Decay** exponentially discounts edge weights by event-date
    distance (half-life 14 days), so a pair 46+ days apart falls below
    the active threshold and the UI can filter it out as a cold link.
  * **Aggregate weight** per edge is ``max(components) + 0.1 × (n − 1)``,
    capped at 1.0.  Sum would double-count correlated signals
    (same-family events also tend to share sectors).

Design choices (advisor-confirmed)
----------------------------------
  * One edge per (parent, child) pair, never one edge per component.
  * Hard pair window of 60 days upfront so the composer is O(N × W)
    where W is the in-window neighbourhood, not O(N²) worst case.
  * **actor_overlap is deferred.**  Free-text actor strings from
    ``transmission_path`` ("US Treasury OFAC" vs "Treasury OFAC")
    need normalisation that's its own subtask.
  * Decay parameters are baked module constants, not kwargs.  Users
    who want a different half-life run a different study.

Output discipline
-----------------
  * Envelope names the parameters (``decay_half_life_days``,
    ``active_threshold``, ``pair_window_days``) so consumers can
    reason about the graph without re-reading this file.
  * Every edge carries ``components`` provenance — the specific family,
    signature, shared tickers / sectors that produced the edge.
    Unauditable edges are not useful research output.
  * Empty archive returns a shaped empty block, not ``{}``.

Pure composer.  No I/O.  Never raises.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from cross_event_studies import (
    _event_sectors,
    _event_tickers,
    _parse_event_date,
    _path_signature,
)


# ---------------------------------------------------------------------------
# Baked parameters — not tunable per call
# ---------------------------------------------------------------------------

_HALF_LIFE_DAYS: int = 14
_ACTIVE_THRESHOLD: float = 0.10
_PAIR_WINDOW_DAYS: int = 60

# Component base weights — calibrated in [0, 1].  path_cluster beats
# family because the channel-only signature is structurally tighter
# (proven by cross_event_studies recurrence rates).  asset / sector use
# Jaccard so they normalise across event universes of different size.
_FAMILY_WEIGHT: float = 0.50
_PATH_WEIGHT: float   = 0.70
_ASSET_WEIGHT: float  = 0.30
_SECTOR_WEIGHT: float = 0.20

# Bonus per additional active component beyond the first.  Small so
# the max-based aggregate isn't overwhelmed by signal stacking.
_MULTI_COMPONENT_BONUS: float = 0.10

# Cap on the number of representative items carried on each edge
# component for provenance (shared tickers, shared sectors, etc.).
_MAX_PROVENANCE_ITEMS: int = 5


# ---------------------------------------------------------------------------
# Decay
# ---------------------------------------------------------------------------

def _decay_factor(age_days: float) -> float:
    """Exponential decay with a 14-day half-life."""
    if age_days < 0:
        age_days = 0.0
    return math.exp(-math.log(2.0) * age_days / _HALF_LIFE_DAYS)


# ---------------------------------------------------------------------------
# Per-event feature extraction
# ---------------------------------------------------------------------------

def _event_family(ev: dict) -> Optional[str]:
    v = ev.get("mechanism_family")
    if not isinstance(v, str):
        return None
    v = v.strip()
    if not v or v == "none":
        return None
    return v


def _event_assets(ev: dict) -> set[str]:
    """Union of beneficiary + loser ticker symbols, upper-cased."""
    out: set[str] = set()
    for key in ("beneficiary_tickers", "loser_tickers"):
        for sym in _event_tickers(ev, key):
            out.add(sym)
    return out


def _path_channel_set(sig: Optional[tuple[str, ...]]) -> Optional[tuple[str, ...]]:
    """Signature tuple ordered — keeps a sig that's None when the event
    has no transmission_path rather than turning it into an empty tuple."""
    return sig


def _feature_pack(ev: dict) -> dict[str, Any]:
    """Pre-compute everything the pair-scoring loop needs, once per event.

    Doing this once per event (rather than on every pair check) keeps
    the composer at O(N × W) with a tight inner loop.
    """
    date = _parse_event_date(ev.get("event_date"))
    return {
        "id":       ev.get("id"),
        "date":     date,
        "family":   _event_family(ev),
        "path_sig": _path_signature(ev),
        "assets":   _event_assets(ev),
        "sectors":  _event_sectors(ev),
        "headline": ev.get("headline") or "",
    }


# ---------------------------------------------------------------------------
# Component scoring
# ---------------------------------------------------------------------------

def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = a & b
    if not inter:
        return 0.0
    union = a | b
    return len(inter) / len(union)


def _components_for_pair(
    parent: dict[str, Any],
    child: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Return the active spillover components for a (parent, child) pair.

    Missing components are absent from the returned dict — the caller
    iterates over what's there rather than reading zeros from a fixed
    shape.  Each component carries its own contribution score + the
    evidence that produced it for downstream auditability.
    """
    comps: dict[str, dict[str, Any]] = {}

    # Family — binary.
    if parent["family"] and parent["family"] == child["family"]:
        comps["family_shared"] = {
            "contribution": _FAMILY_WEIGHT,
            "family":       parent["family"],
        }

    # Path cluster — channel-only signature, exact match.
    p_sig = parent["path_sig"]
    c_sig = child["path_sig"]
    if p_sig is not None and p_sig == c_sig:
        comps["path_cluster"] = {
            "contribution": _PATH_WEIGHT,
            "signature":    list(p_sig),
        }

    # Asset overlap — Jaccard over ticker sets.
    asset_jaccard = _jaccard(parent["assets"], child["assets"])
    if asset_jaccard > 0:
        shared = sorted(parent["assets"] & child["assets"])[:_MAX_PROVENANCE_ITEMS]
        comps["asset_overlap"] = {
            "contribution":   round(_ASSET_WEIGHT * asset_jaccard, 3),
            "jaccard":        round(asset_jaccard, 3),
            "shared_tickers": shared,
        }

    # Sector overlap — Jaccard over sectors derived from tickers.
    sector_jaccard = _jaccard(parent["sectors"], child["sectors"])
    if sector_jaccard > 0:
        shared = sorted(parent["sectors"] & child["sectors"])[:_MAX_PROVENANCE_ITEMS]
        comps["sector_overlap"] = {
            "contribution":    round(_SECTOR_WEIGHT * sector_jaccard, 3),
            "jaccard":         round(sector_jaccard, 3),
            "shared_sectors":  shared,
        }

    return comps


def _aggregate_weight(
    components: dict[str, dict[str, Any]],
    decay: float,
) -> float:
    """Max contribution + small bonus per additional component, × decay.

    Clamped to [0, 1] so the UI has a predictable scale.  Sum would
    compound correlated signals (same family often shares sectors);
    max picks the strongest and rewards ensembles modestly.
    """
    if not components:
        return 0.0
    contribs = [c["contribution"] for c in components.values()]
    base = max(contribs) + _MULTI_COMPONENT_BONUS * (len(contribs) - 1)
    return max(0.0, min(1.0, base * decay))


# ---------------------------------------------------------------------------
# Rationale synthesis
# ---------------------------------------------------------------------------

def _component_summary_bits(components: dict[str, dict[str, Any]]) -> list[str]:
    bits: list[str] = []
    if "family_shared" in components:
        bits.append(f"shared family ({components['family_shared']['family']})")
    if "path_cluster" in components:
        sig = components["path_cluster"]["signature"]
        bits.append(f"same path shape ({' → '.join(sig)})")
    if "asset_overlap" in components:
        shared = components["asset_overlap"]["shared_tickers"]
        preview = ", ".join(shared[:3])
        more = "" if len(shared) <= 3 else f" +{len(shared) - 3} more"
        bits.append(f"asset overlap ({preview}{more})")
    if "sector_overlap" in components:
        shared = components["sector_overlap"]["shared_sectors"]
        bits.append(f"sector overlap ({', '.join(shared)})")
    return bits


def _edge_rationale(
    components: dict[str, dict[str, Any]],
    age_days: int,
    active: bool,
) -> str:
    bits = _component_summary_bits(components)
    if not bits:
        return ""
    head = "; ".join(bits)
    tail = f" · {age_days}d apart"
    tail += " · active" if active else " · fading"
    return head + tail


# ---------------------------------------------------------------------------
# Graph composer
# ---------------------------------------------------------------------------

def _node_row(pack: dict[str, Any]) -> dict[str, Any]:
    date = pack.get("date")
    return {
        "id":                pack.get("id"),
        "headline":          pack.get("headline") or "",
        "event_date":        date.isoformat() if isinstance(date, datetime) else None,
        "mechanism_family":  pack.get("family") or "none",
    }


def _sorted_components_list(
    components: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flatten components dict to a list sorted by contribution desc,
    so UI consumers have a stable rendering order without re-sorting."""
    rows = [{"component": k, **v} for k, v in components.items()]
    rows.sort(key=lambda r: -float(r.get("contribution") or 0))
    return rows


def build_event_graph(events: Iterable[dict]) -> dict[str, Any]:
    """Build the cross-event spillover graph from an archive-event list.

    Returns::

        {
          "generated_at":          iso8601 timestamp,
          "total_events":           int,
          "decay_half_life_days":   int,
          "active_threshold":       float,
          "pair_window_days":       int,
          "active_edges":           int,
          "total_edges":            int,
          "nodes":   [{id, headline, event_date, mechanism_family}, ...],
          "edges":   [edge, ...],
        }

    Each edge shape::

        {
          "parent_id":   int,
          "child_id":    int,
          "parent_date": str,
          "child_date":  str,
          "age_days":    int,
          "weight":      float,       # in [0, 1], decay-adjusted aggregate
          "active":      bool,        # weight ≥ _ACTIVE_THRESHOLD
          "components":  {...},       # keyed by component type with evidence
          "components_list": [...],   # same content, sorted by contribution
          "rationale":   str,
        }

    The ``edges`` list contains every pair where at least one component
    fired, regardless of whether the aggregate cleared the active
    threshold.  ``active_edges`` counts the subset that did — UI /
    research can filter on ``active`` to get the live graph while the
    fading-cascade list stays visible in the same output.

    Skipped for now: ``actor_overlap``.  Free-text actor matching
    requires a normaliser that's out of scope here.
    """
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    event_list = [e for e in (events or []) if isinstance(e, dict)]
    if not event_list:
        return {
            "generated_at":         generated_at,
            "total_events":         0,
            "decay_half_life_days": _HALF_LIFE_DAYS,
            "active_threshold":     _ACTIVE_THRESHOLD,
            "pair_window_days":     _PAIR_WINDOW_DAYS,
            "active_edges":         0,
            "total_edges":          0,
            "nodes":                [],
            "edges":                [],
        }

    # Pre-compute feature packs; drop events missing a date (they can't
    # be ordered in the cascade, so they can't form parent/child edges).
    packs: list[dict[str, Any]] = []
    for ev in event_list:
        pack = _feature_pack(ev)
        packs.append(pack)

    nodes = [_node_row(p) for p in packs]

    # Sort by date for the windowed sweep.  Packs missing a date sink
    # to the end and are excluded from edge construction.
    dated_packs = [p for p in packs if isinstance(p.get("date"), datetime)]
    dated_packs.sort(key=lambda p: p["date"])  # type: ignore[arg-type]

    edges: list[dict[str, Any]] = []
    active_count = 0

    for i, parent in enumerate(dated_packs):
        parent_date: datetime = parent["date"]  # type: ignore[assignment]
        for j in range(i + 1, len(dated_packs)):
            child = dated_packs[j]
            child_date: datetime = child["date"]  # type: ignore[assignment]
            age_days_f = (child_date - parent_date).total_seconds() / 86_400.0
            if age_days_f > _PAIR_WINDOW_DAYS:
                break   # sorted; anything further is also out of window
            age_days_int = max(0, int(round(age_days_f)))

            components = _components_for_pair(parent, child)
            if not components:
                continue

            decay = _decay_factor(age_days_f)
            weight = _aggregate_weight(components, decay)
            active = weight >= _ACTIVE_THRESHOLD
            if active:
                active_count += 1

            edges.append({
                "parent_id":       parent.get("id"),
                "child_id":        child.get("id"),
                "parent_date":     parent_date.isoformat(),
                "child_date":      child_date.isoformat(),
                "age_days":        age_days_int,
                "weight":          round(weight, 3),
                "active":          active,
                "components":      components,
                "components_list": _sorted_components_list(components),
                "rationale":       _edge_rationale(components, age_days_int, active),
            })

    return {
        "generated_at":         generated_at,
        "total_events":         len(event_list),
        "decay_half_life_days": _HALF_LIFE_DAYS,
        "active_threshold":     _ACTIVE_THRESHOLD,
        "pair_window_days":     _PAIR_WINDOW_DAYS,
        "active_edges":         active_count,
        "total_edges":          len(edges),
        "nodes":                nodes,
        "edges":                edges,
    }
