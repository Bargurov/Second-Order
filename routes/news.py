"""Route handlers for /news and /news/refresh."""

import base64
import json
import time
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query

import api as _api
from macro_calendar import get_macro_releases
from macro_surprise import attach_cluster_macro_blocks, classify_macro_surprise
from policy_tracker import get_policy_items
from policy_timing import attach_policy_timing_blocks

router = APIRouter()


# ---------------------------------------------------------------------------
# Cursor helpers — opaque base64(JSON) encoding of (source_count, published_at, id)
# ---------------------------------------------------------------------------

def _sort_key(c: dict) -> tuple:
    """Descending order: source_count, then published_at, then id."""
    return (
        c.get("source_count", 0) or 0,
        c.get("published_at", "") or "",
        c.get("id", 0) or 0,
    )


def _encode_cursor(c: dict) -> str:
    payload = {
        "sc":  c.get("source_count", 0) or 0,
        "pub": c.get("published_at", "") or "",
        "id":  c.get("id", 0) or 0,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple:
    """Return (source_count, published_at, id) or raise ValueError on malformed input."""
    pad = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + pad)
        data = json.loads(raw.decode("utf-8"))
        return (int(data["sc"]), str(data["pub"] or ""), int(data["id"]))
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("malformed cursor")


def _first_after_cursor(sorted_clusters: list[dict], cursor_key: tuple) -> int:
    """Index of the first cluster whose sort-key is strictly less than cursor_key.

    O(N) scan is fine here — the cached cluster list is small (<= a few hundred).
    Using strict-less lets us skip past evicted clusters without duplicating.
    """
    for i, c in enumerate(sorted_clusters):
        if _sort_key(c) < cursor_key:
            return i
    return len(sorted_clusters)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/news")
def news(
    limit: int = Query(0, ge=0, le=500),
    cursor: Optional[str] = None,
):
    # Cache-only read: read_news_cache_state never fetches RSS, clusters, or
    # writes SQLite/cache — the /news GET boundary.  Refresh ownership stays
    # with POST /news/refresh.
    state = _api.read_news_cache_state()
    payload = state.payload if state.payload is not None else _api._unavailable_news_payload()
    # Re-sort defensively so pagination is stable even if the cached list
    # was produced by an older sort contract.  Sort is descending on the
    # composite key (source_count, published_at, id).
    clusters = sorted(payload.get("clusters") or [], key=_sort_key, reverse=True)
    total = len(clusters)

    if cursor:
        try:
            cursor_key = _decode_cursor(cursor)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid cursor")
        start = _first_after_cursor(clusters, cursor_key)
    else:
        start = 0

    page = clusters[start:start + limit] if limit > 0 else clusters[start:]

    next_cursor: Optional[str] = None
    if limit > 0 and page and (start + len(page)) < total:
        next_cursor = _encode_cursor(page[-1])

    meta = payload.get("refresh_meta")
    if meta is None:
        meta = {
            "status": "ok", "known": 0, "new": 0, "merged": 0, "created": 0,
            "reused": total, "source": "cached_fallback",
            "freshness": "stale", "last_successful_refresh": None,
        }
    # A cache-only stale read keeps the payload's own status but marks the
    # freshness badge stale so the frontend indicator matches the honest
    # availability (the cache was served without a refresh).
    if state.availability == "stale":
        meta = {**meta, "freshness": "stale"}

    # Track enrichment failures explicitly so the frontend can render a
    # "degraded" indicator instead of silently showing an empty calendar
    # or empty policy feed as if it were the current state of the world.
    degraded_fields: list[str] = []

    try:
        macro_releases = get_macro_releases()
    except Exception:
        macro_releases = []
        degraded_fields.append("macro_releases")

    try:
        macro_releases = classify_macro_surprise(macro_releases, clusters)
    except Exception:
        # Enrichment failure leaves calendar rows intact but without surprise tags.
        degraded_fields.append("macro_surprise")

    # Stamp matching clusters with the official macro block when stored
    # release facts exist.  No-op (and the page shape stays exactly as
    # before) when no release has signal_source="official".  Failures
    # here are non-fatal — clusters remain untagged.
    try:
        page = attach_cluster_macro_blocks(macro_releases, page)
    except Exception:
        degraded_fields.append("macro_surprise_blocks")

    # Stamp matching clusters with a tracked ``policy_timing`` block
    # (announced / effective / under_review / expired) for the
    # policy-timing strip on the Headlines page.  Unmatched clusters
    # are left byte-stable so the NewsCluster contract stays unchanged
    # for consumers that don't read the block.
    try:
        page = attach_policy_timing_blocks(page)
    except Exception:
        degraded_fields.append("policy_timing")

    try:
        policy_items = get_policy_items()
    except Exception:
        policy_items = []
        degraded_fields.append("policy_items")

    return {
        "clusters": page,
        "next_cursor": next_cursor,
        "total_headlines": payload.get("total_headlines", 0),
        "total_count": total,
        "feed_status": payload.get("feed_status", []),
        "refresh_meta": meta,
        "macro_releases": macro_releases,
        "policy_items": policy_items,
        "data_quality": "degraded" if degraded_fields else "ok",
        "degraded_fields": degraded_fields,
        # P2-1 cache-only honesty signals: distinguish a fresh / stale local
        # feed from an unavailable local cache (never a silent empty feed).
        "availability": state.availability,
        "refresh_required": state.refresh_required,
        "source": state.source,
        "last_updated_at": state.last_updated_at,
    }


@router.get("/news/inbox")
def news_inbox():
    """Automatic Event Inbox — local-state-only GET.

    Derives ``automatic-event-inbox-v1`` from the persisted news_clusters
    store through a READ-ONLY SQLite connection.  Never refreshes news,
    never reaches RSS or a provider, never writes any cache or database —
    refresh ownership stays with ``POST /news/refresh``.
    """
    import event_inbox
    return event_inbox.build_inbox_response()


@router.post("/news/refresh")
def news_refresh(_body: _api.NewsRefreshRequest | None = Body(default=None)):
    """Trigger a fresh news ingestion pass.

    The body is optional; when provided it must be empty-object `{}` or a
    request that matches ``NewsRefreshRequest``.  Unknown fields are rejected
    with 422 at the boundary.
    """
    now = time.monotonic()

    if _api._last_refresh_payload is not None and (now - _api._last_refresh_at) < _api._REFRESH_COOLDOWN_SECONDS:
        recent = dict(_api._last_refresh_payload)
        meta = dict(recent.get("refresh_meta") or {})
        meta["status"] = "recent"
        recent["refresh_meta"] = meta
        return recent

    acquired = _api._refresh_lock.acquire(blocking=False)
    if not acquired:
        if _api._last_refresh_payload is not None:
            busy = dict(_api._last_refresh_payload)
            meta = dict(busy.get("refresh_meta") or {})
            meta["status"] = "throttled"
            busy["refresh_meta"] = meta
            return busy
        with _api._refresh_lock:
            return _api._last_refresh_payload or _api._fetch_fresh_news()

    try:
        result = _api._fetch_fresh_news()
        _api._last_refresh_at = time.monotonic()
        _api._last_refresh_payload = result
        return result
    finally:
        _api._refresh_lock.release()


@router.get("/news/trends")
def news_trends(window_hours: int = 72, min_sources: int = 3, limit: int = 8):
    from db import get_trending_clusters
    return get_trending_clusters(window_hours=window_hours, min_sources=min_sources, limit=limit)
