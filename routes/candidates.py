"""Read-only diagnostic for high-priority unanalyzed news clusters.

Surfaces clusters from the news cache that look most promising for
analysis but have not yet been processed.  Zero LLM cost — this
endpoint never invokes a model and never spends a paid call.  It is
strictly a planning aid so operators can see which headlines are
worth queuing for ``/analyze`` (manual) or ``/movers/backfill-recent``
(operator-controlled budget).

Reuses helpers from ``routes.movers`` so dedup / relevance / recency
semantics agree exactly with what the backfill considers "already
analyzed" — the operator can trust that a headline appearing here
will not be dismissed as a duplicate by the backfill path.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Query

import api as _api
from routes.movers import (
    _ASSET_TICKER_RE,
    _cached_news_payload,
    _cluster_event_date,
    _cluster_has_asset_terms,
    _cluster_headline,
    _cluster_published_dt,
    _find_recent_saved_event,
    _headline_is_market_relevant,
    _sort_news_clusters,
)

router = APIRouter()


def _explicit_ticker_count(headline: str) -> int:
    if not headline:
        return 0
    return len(_ASSET_TICKER_RE.findall(headline))


def _hours_since(published_at: str | None) -> float | None:
    if not published_at:
        return None
    when = _cluster_published_dt({"published_at": published_at})
    if when is None:
        return None
    delta = datetime.now() - when
    return round(delta.total_seconds() / 3600.0, 2)


def _priority_score(
    *,
    source_count: int,
    has_asset_terms: bool,
    has_explicit_tickers: bool,
    recency_hours: float | None,
) -> float:
    """Heuristic priority score — higher means more worth analyzing.

    Combines source confluence (multiple feeds reporting the cluster),
    asset specificity (explicit ticker syntax beats company terms),
    and recency.  Pure / deterministic so the ranking is stable
    across calls when the cache hasn't changed.
    """
    score = float(source_count or 0)
    if has_explicit_tickers:
        score += 3.0
    elif has_asset_terms:
        score += 1.5
    if recency_hours is not None:
        if recency_hours <= 1.0:
            score += 2.0
        elif recency_hours <= 6.0:
            score += 1.0
        elif recency_hours <= 24.0:
            score += 0.5
    return round(score, 2)


def _build_reasons(
    *,
    source_count: int,
    has_explicit_tickers: bool,
    has_asset_terms: bool,
    recency_hours: float | None,
) -> list[str]:
    reasons: list[str] = []
    if source_count >= 3:
        reasons.append(f"{source_count} sources confirm this cluster")
    elif source_count > 0:
        reasons.append(f"{source_count} source carries this story")
    if has_explicit_tickers:
        reasons.append("Headline names an explicit ticker symbol")
    elif has_asset_terms:
        reasons.append(
            "Headline names a specific company / asset class / instrument"
        )
    if recency_hours is not None:
        if recency_hours < 1.0:
            reasons.append(
                f"{int(recency_hours * 60)} minutes old — fresh for analysis"
            )
        elif recency_hours < 6.0:
            reasons.append(f"{recency_hours:.1f}h old — fresh for analysis")
        elif recency_hours < 24.0:
            reasons.append(f"{recency_hours:.0f}h old — still actionable")
    return reasons


@router.get("/candidates/unanalyzed")
def candidates_unanalyzed(
    limit: int = Query(
        10, ge=1, le=50,
        description=(
            "Maximum number of candidates returned (after ranking)."
        ),
    ),
    since_hours: int = Query(
        24, ge=1, le=168,
        description=(
            "Only consider clusters with ``published_at`` within the last "
            "N hours.  Clusters lacking a parseable date are admitted."
        ),
    ),
    min_source_count: int = Query(
        1, ge=1, le=20,
        description=(
            "Drop clusters reported by fewer than N sources.  Default 1 "
            "admits every cluster the relevance filter accepts."
        ),
    ),
):
    """High-priority unanalyzed news clusters (zero LLM cost).

    Read-only diagnostic.  Reads the existing news cache (memory →
    SQLite) and the saved-event archive to surface clusters that look
    worth queuing for analysis.  No model is invoked.  No paid call
    is made.  No row is persisted.

    Each candidate carries:
      * ``priority_score`` — heuristic ranking input (deterministic).
      * ``reasons`` — short human-readable justifications for the
        score, so the operator sees WHY a cluster was surfaced.
      * ``source_count``, ``recency_hours``, ``has_asset_terms``,
        ``has_explicit_tickers`` — the raw signals the score was
        built from.
      * ``event_date`` — the date stamp /analyze would use.

    Diagnostics include filter counts (cache size → candidates
    returned) so operators can see how each gate trimmed the working
    set without spending an LLM call.
    """
    payload, source = _cached_news_payload()
    raw_clusters = _sort_news_clusters((payload or {}).get("clusters") or [])

    cutoff_dt = datetime.now() - timedelta(hours=since_hours)
    diagnostics: dict = {
        "source": source,
        "since_hours": since_hours,
        "min_source_count": min_source_count,
        "clusters_in_cache": len(raw_clusters),
        "filtered_outside_window": 0,
        "filtered_below_min_source_count": 0,
        "filtered_irrelevant": 0,
        "filtered_already_analyzed": 0,
        "candidates_returned": 0,
    }

    candidates: list[dict] = []
    for cluster in raw_clusters:
        published = str(cluster.get("published_at") or "")
        when = _cluster_published_dt(cluster)
        # Undated clusters are admitted (mirrors backfill semantics);
        # only reject when we have a parseable date older than cutoff.
        if when is not None and when < cutoff_dt:
            diagnostics["filtered_outside_window"] += 1
            continue
        sc = int(cluster.get("source_count") or 0)
        if sc < min_source_count:
            diagnostics["filtered_below_min_source_count"] += 1
            continue
        headline = _cluster_headline(cluster)
        if not headline:
            continue
        if not _headline_is_market_relevant(headline):
            diagnostics["filtered_irrelevant"] += 1
            continue
        # Cache lookup uses the same path /movers/backfill-recent uses
        # so this endpoint's "already analyzed" semantics agree with
        # backfill's exactly.  An empty model token forces the
        # any-model fallback path inside ``find_cached_analysis``.
        event_date = _cluster_event_date(cluster)
        cached = _find_recent_saved_event(headline, event_date, "")
        if cached is not None:
            diagnostics["filtered_already_analyzed"] += 1
            continue
        recency = _hours_since(published)
        has_explicit = _explicit_ticker_count(headline) > 0
        has_terms = _cluster_has_asset_terms(cluster)
        reasons = _build_reasons(
            source_count=sc,
            has_explicit_tickers=has_explicit,
            has_asset_terms=has_terms,
            recency_hours=recency,
        )
        score = _priority_score(
            source_count=sc,
            has_asset_terms=has_terms,
            has_explicit_tickers=has_explicit,
            recency_hours=recency,
        )
        candidates.append({
            "headline": headline,
            "published_at": published,
            "event_date": event_date,
            "source_count": sc,
            "has_explicit_tickers": has_explicit,
            "has_asset_terms": has_terms,
            "recency_hours": recency,
            "priority_score": score,
            "reasons": reasons,
        })

    candidates.sort(key=lambda c: (
        -float(c.get("priority_score") or 0),
        -int(c.get("source_count") or 0),
        c.get("published_at", "") or "",
    ))
    candidates = candidates[:limit]
    diagnostics["candidates_returned"] = len(candidates)

    return _api._sanitize_floats({
        "status": "ok",
        "candidates": candidates,
        "diagnostics": diagnostics,
        "notes": (
            "Zero-LLM-cost diagnostic. To analyze a candidate, POST its "
            "headline to /analyze (manual) or POST to "
            "/movers/backfill-recent with an explicit max_llm_calls "
            "budget (operator-controlled paid path)."
        ),
    })
