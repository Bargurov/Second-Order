"""Diagnostics routes — zero-cost introspection over the
headline_registry lifecycle.  See
docs/superpowers/specs/2026-05-03-headline-registry-design.md.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from headline_registry import compose_diagnostics

router = APIRouter()


@router.get("/registry/diagnostics")
def registry_diagnostics(
    candidates_limit: int = Query(50, ge=1, le=500),
    recent_hours: int = Query(
        24, ge=1, le=720,
        description=(
            "Window (hours) for the ``analyzed_recent`` and "
            "``surfaced_recent`` counts.  Defaults to 24h to match the "
            "frozen ``expired_count_24h`` field's semantics."
        ),
    ),
):
    """Pure-SQL view over headline_registry.  Zero LLM cost.

    Preserves the legacy fields (``state_counts``, ``skip_reason_counts``,
    ``last_analyzed_at``, ``expired_count_24h``,
    ``eligible_unanalyzed_candidates``) and adds the demo-readiness
    block (``counts.eligible_unanalyzed``, ``counts.analyzed_recent``,
    ``counts.surfaced_recent``, ``counts.expired_low_impact``) plus
    ``last_surfaced_at`` at the top level.  Read-only — never analyzes
    or mutates registry rows.
    """
    return compose_diagnostics(
        candidates_limit=candidates_limit,
        recent_hours=recent_hours,
    )
