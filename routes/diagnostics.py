"""Diagnostics routes — zero-cost introspection over the
headline_registry lifecycle.  See
docs/superpowers/specs/2026-05-03-headline-registry-design.md.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Query

from db import (
    load_registry_state_counts,
    load_registry_skip_reason_counts,
    load_registry_last_analyzed_at,
    load_registry_expired_count_since,
    load_eligible_unanalyzed_candidates,
)

router = APIRouter()


@router.get("/registry/diagnostics")
def registry_diagnostics(
    candidates_limit: int = Query(50, ge=1, le=500),
):
    """Pure-SQL view over headline_registry.  Zero LLM cost.

    Returns state counts, last-skip-reason counts, the most recent
    analyzed_at, the count of low-impact events that have expired in
    the last 24 hours, and the top eligible-but-unanalyzed candidates
    ranked by source_count then recency.
    """
    since_iso = (
        datetime.now() - timedelta(hours=24)
    ).isoformat(timespec="seconds")
    return {
        "state_counts":            load_registry_state_counts(),
        "skip_reason_counts":      load_registry_skip_reason_counts(),
        "last_analyzed_at":        load_registry_last_analyzed_at(),
        "expired_count_24h":       load_registry_expired_count_since(since_iso),
        "eligible_unanalyzed_candidates":
            load_eligible_unanalyzed_candidates(limit=candidates_limit),
    }
