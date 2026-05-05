"""Diagnostics routes — zero-cost introspection over the
headline_registry lifecycle.  See
docs/superpowers/specs/2026-05-03-headline-registry-design.md.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Query

import api as _api
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


@router.get("/registry/candidate-queue")
def registry_candidate_queue(
    limit: int = Query(25, ge=1, le=200),
    since_hours: int = Query(
        72, ge=1, le=720,
        description=(
            "Recency window (hours) for cluster eligibility.  Mirrors the "
            "``since_hours`` filter on ``/movers/backfill-preview`` so "
            "the queue reflects the same universe a paid run would see."
        ),
    ),
    include_low_signal: bool = Query(
        False,
        description=(
            "When true, low-signal clusters and headlines that fail the "
            "relevance gate are admitted.  Mirrors the backfill flag of "
            "the same name."
        ),
    ),
):
    """Read-only queue of unanalyzed preview candidates, ranked.

    Pure read of in-memory + SQLite state — no LLM call, no
    ``yfinance`` fetch, no persistence write.  Reuses
    ``routes.movers``'s preview helpers (cluster filter, scorer,
    label/explanation composers) plus the headline-registry lookup so
    the queue stays byte-aligned with what the preview would emit.

    Items: clusters whose registry state is unanalyzed (``seen`` /
    ``eligible`` / not-yet-registered).  ``registry_state`` and
    ``skip_reason`` per item carry the registry's current view so the
    operator sees prior skip reasons (e.g., ``llm_budget_exhausted``)
    on rows that survived an earlier paid run.

    Counts are aggregated over clusters that passed the recency +
    relevance pre-filter:
      * ``eligible``           — items in the queue.
      * ``already_analyzed``   — registry state in
        ``{analyzed, market_checked, surfaced}``.
      * ``expired_low_impact`` — registry state ``expired_low_impact``.
      * ``skipped``            — sum of the two above.
    """
    # Late imports — keep diagnostics' import-time surface light and
    # prevent a circular import path through routes.movers at startup.
    from routes.movers import (
        _cached_news_payload,
        _cluster_event_date,
        _cluster_has_asset_terms,
        _cluster_headline,
        _cluster_is_recent,
        _hr_dedup_key,
        _headline_is_market_relevant,
        _rank_explanation,
        _registry_state_for_title_key,
        _score_cluster_for_preview,
        _skip_reason_label,
    )

    payload, source = _cached_news_payload()
    raw_clusters = (payload or {}).get("clusters") or []
    since_dt = (
        datetime.now() - timedelta(hours=since_hours)
        if since_hours and since_hours > 0 else None
    )

    counts = {
        "eligible":           0,
        "skipped":            0,
        "already_analyzed":   0,
        "expired_low_impact": 0,
    }

    # Pre-filter: same recency / relevance / low_signal gates the
    # backfill-preview applies, so the queue counts reflect the same
    # working set a paid run would consider.
    eligible_clusters: list[dict] = []
    for cluster in raw_clusters:
        if not isinstance(cluster, dict):
            continue
        if not _cluster_is_recent(cluster, since=since_dt):
            continue
        headline = _cluster_headline(cluster)
        if not headline:
            continue
        if cluster.get("low_signal") and not include_low_signal:
            continue
        if (
            not include_low_signal
            and not _headline_is_market_relevant(headline)
        ):
            continue
        eligible_clusters.append(cluster)

    cluster_scores: list[tuple[dict, float, dict]] = []
    for cluster in eligible_clusters:
        score, factors = _score_cluster_for_preview(cluster)
        cluster_scores.append((cluster, score, factors))
    cluster_scores.sort(
        key=lambda triple: (
            triple[1],
            int(triple[0].get("source_count") or 0),
            1 if _cluster_has_asset_terms(triple[0]) else 0,
        ),
        reverse=True,
    )

    items: list[dict] = []
    for cluster, rank_score, rank_factors in cluster_scores:
        headline = _cluster_headline(cluster)
        title_key = _hr_dedup_key(headline)
        registry_state, _eid = _registry_state_for_title_key(title_key)

        if registry_state in ("analyzed", "market_checked", "surfaced"):
            counts["already_analyzed"] += 1
            counts["skipped"] += 1
            continue
        if registry_state == "expired_low_impact":
            counts["expired_low_impact"] += 1
            counts["skipped"] += 1
            continue

        # Surface the registry's last_skip_reason (e.g.,
        # ``llm_budget_exhausted`` from a prior partial run) so the
        # operator can tell why an actionable cluster hasn't been
        # picked up yet.  Pulled lazily; missing rows return None.
        last_skip_reason = _last_skip_reason_for_title_key(title_key)
        counts["eligible"] += 1
        if len(items) >= limit:
            continue
        items.append({
            "headline":          headline,
            "source_count":      int(cluster.get("source_count") or 0),
            "published_at":      str(cluster.get("published_at") or "") or None,
            "event_date":        _cluster_event_date(cluster),
            "registry_state":    registry_state,
            "skip_reason":       last_skip_reason,
            "skip_reason_label": _skip_reason_label(last_skip_reason),
            "rank_score":        round(float(rank_score), 3),
            "rank_factors":      rank_factors,
            "rank_explanation":  _rank_explanation(rank_factors),
        })

    return _api._sanitize_floats({
        "items": items,
        "counts": counts,
        "filters": {
            "limit":              limit,
            "since_hours":        since_hours,
            "include_low_signal": include_low_signal,
        },
        "news_source": source,
    })


def _last_skip_reason_for_title_key(title_key: str) -> str | None:
    """Return the most recent ``last_skip_reason`` across all registry
    rows that share ``title_key``.  Multiple sources can register
    duplicate headlines; the queue surfaces the freshest skip
    annotation so an operator sees the latest reason.  Pure read; no
    writes, no LLM, no provider calls.
    """
    import sqlite3
    from db import DB_FILE, _db_ready
    if not _db_ready:
        return None
    try:
        with sqlite3.connect(DB_FILE) as conn:
            row = conn.execute(
                "SELECT last_skip_reason "
                "FROM headline_registry "
                "WHERE title_key = ? AND last_skip_reason IS NOT NULL "
                "ORDER BY last_seen_at DESC "
                "LIMIT 1",
                (title_key,),
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    return row[0] if row and row[0] else None


@router.get("/diagnostics/data-quality")
def data_quality_summary():
    """Compact zero-cost data-quality view.

    Skeleton: composes already-existing read-only helpers into a
    single small payload the operator can poll without paying for any
    LLM, market_check, yfinance, or persistence work.  Each top-level
    block carries an ``available`` flag so a partial failure (a helper
    raising, a missing dependency) leaves the rest of the response
    intact — consumers branch on ``available`` rather than on the
    presence of the block.

    Blocks:
      * ``registry_counts``  — registry-lifecycle demo-readiness counts
        plus the skip-reason histogram, sourced from ``compose_diagnostics``.
      * ``archive_counts``   — total saved events + max event id.
      * ``snapshot_freshness`` — ``{total, fresh, stale, unavailable}``
        from the warm SnapshotStore (no refresh).
      * ``candidate_queue_counts`` — same eligible / skipped / already-
        analyzed / expired-low-impact counts the registry candidate-
        queue endpoint emits, recomputed from the cached news payload
        without any provider call.
      * ``latest_analyzed_at`` — most recent registry ``analyzed_at``
        timestamp, or None.
    """
    out: dict = {
        "registry_counts":        {"available": False},
        "archive_counts":         {"available": False},
        "snapshot_freshness":     {"available": False},
        "candidate_queue_counts": {"available": False},
        "latest_analyzed_at":     None,
    }

    diag: dict = {}
    try:
        diag = compose_diagnostics(candidates_limit=1, recent_hours=24)
    except Exception:
        diag = {}
    if diag:
        out["registry_counts"] = {
            "available":          True,
            "counts":             diag.get("counts", {}),
            "state_counts":       diag.get("state_counts", {}),
            "skip_reason_counts": diag.get("skip_reason_counts", {}),
            "last_surfaced_at":   diag.get("last_surfaced_at"),
            "expired_count_24h":  diag.get("expired_count_24h", 0),
        }
        out["latest_analyzed_at"] = diag.get("last_analyzed_at")

    try:
        from db import get_events_fingerprint
        count, max_id = get_events_fingerprint()
        out["archive_counts"] = {
            "available":   True,
            "total":       int(count),
            "max_id":      int(max_id),
        }
    except Exception:
        pass

    try:
        from market_snapshots import get_all_snapshots
        from market_context import _summarize_snapshots
        snaps = get_all_snapshots() or []
        # ``_summarize_snapshots`` accepts dict rows; coerce dataclass
        # rows so the helper stays simple.
        rows = []
        for s in snaps:
            if isinstance(s, dict):
                rows.append(s)
            elif hasattr(s, "to_dict"):
                try:
                    rows.append(s.to_dict())
                except Exception:
                    continue
        meta = _summarize_snapshots(rows)
        out["snapshot_freshness"] = {"available": True, **meta}
    except Exception:
        pass

    try:
        out["candidate_queue_counts"] = _candidate_queue_counts()
    except Exception:
        pass

    return _api._sanitize_floats(out)


def _candidate_queue_counts() -> dict:
    """Mirror the counts ``GET /registry/candidate-queue`` emits without
    re-fetching news.  Pure read of the in-memory news payload + the
    registry; no LLM, no market_check, no provider call.  Returns
    ``{"available": False}`` when the news cache or registry helpers
    are unavailable so the partial-availability contract holds.
    """
    try:
        from datetime import datetime, timedelta
        from routes.movers import (
            _cached_news_payload,
            _cluster_headline,
            _cluster_is_recent,
            _hr_dedup_key,
            _headline_is_market_relevant,
            _registry_state_for_title_key,
        )
    except Exception:
        return {"available": False}

    payload, _source = _cached_news_payload()
    raw_clusters = (payload or {}).get("clusters") or []
    since_dt = datetime.now() - timedelta(hours=72)

    counts = {
        "eligible":           0,
        "skipped":            0,
        "already_analyzed":   0,
        "expired_low_impact": 0,
    }

    for cluster in raw_clusters:
        if not isinstance(cluster, dict):
            continue
        if not _cluster_is_recent(cluster, since=since_dt):
            continue
        headline = _cluster_headline(cluster)
        if not headline:
            continue
        if cluster.get("low_signal"):
            continue
        if not _headline_is_market_relevant(headline):
            continue

        state, _eid = _registry_state_for_title_key(_hr_dedup_key(headline))
        if state in ("analyzed", "market_checked", "surfaced"):
            counts["already_analyzed"] += 1
            counts["skipped"] += 1
        elif state == "expired_low_impact":
            counts["expired_low_impact"] += 1
            counts["skipped"] += 1
        else:
            counts["eligible"] += 1

    return {"available": True, **counts}


@router.get("/diagnostics/config-health")
def config_health():
    """Operator-readable cost/security config snapshot.

    Returns booleans, integer caps, and a coarse ``present`` flag for
    each provider key — never the key text itself.  Pure read of env
    state via the ``routes.movers`` helpers; no LLM call, no provider
    request, no DB write.

    Top-level shape:
      * ``paid_analysis_enabled``      — ``ENABLE_PAID_ANALYSIS`` flag.
      * ``backfill_dry_run_default``   — default dry-run mode for
        ``/movers/backfill-recent`` when the request omits ``dry_run``.
      * ``max_backfill_llm_calls``     — server-side cap.
      * ``anthropic_key_present``      — bool only; no key bytes leaked.
      * ``openai_key_present``         — bool only.
      * ``warnings``                   — list of operator-actionable
        config-risk strings (paid+no-cap, paid+no-key, etc.).  Empty
        list = config looks safe.
    """
    from routes.movers import (
        _backfill_dry_run_default,
        _llm_available,
        _max_backfill_llm_calls,
        _paid_analysis_enabled,
    )

    paid_enabled  = bool(_paid_analysis_enabled())
    dry_run_def   = bool(_backfill_dry_run_default())
    max_calls     = int(_max_backfill_llm_calls())
    anthropic_ok  = bool(_llm_available("anthropic"))
    openai_ok     = bool(_llm_available("openai"))

    warnings: list[str] = []
    if paid_enabled and max_calls <= 0:
        warnings.append(
            "paid_analysis_enabled=true but max_backfill_llm_calls=0 — "
            "paid backfill cannot spend; either lift the cap or "
            "disable paid analysis."
        )
    if paid_enabled and not dry_run_def and max_calls > 5:
        warnings.append(
            f"paid_analysis_enabled=true with backfill_dry_run_default=false "
            f"and max_backfill_llm_calls={max_calls} (>5) — a stray request "
            f"could spend up to {max_calls} LLM calls. Consider lowering "
            f"the cap or re-enabling the dry-run default."
        )
    if paid_enabled and not (anthropic_ok or openai_ok):
        warnings.append(
            "paid_analysis_enabled=true but no provider API key is "
            "present — paid invocations will fail before any work is "
            "done.  Set ANTHROPIC_API_KEY or OPENAI_API_KEY, or "
            "disable paid analysis."
        )

    return {
        "paid_analysis_enabled":     paid_enabled,
        "backfill_dry_run_default":  dry_run_def,
        "max_backfill_llm_calls":    max_calls,
        "anthropic_key_present":     anthropic_ok,
        "openai_key_present":        openai_ok,
        "warnings":                  warnings,
    }
