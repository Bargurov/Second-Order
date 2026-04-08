"""
news_cluster_store.py

Persisted incremental clustering for the /news endpoint.

Before this module the news refresh path recomputed the entire cluster
set from scratch on every call:

    records = fetch_all()              # ~500-800 headlines
    clusters = cluster_headlines(records)   # O(n^2) TF-IDF + union-find

On a warm server with a stable feed set the vast majority of those
headlines are ones we already clustered on the previous refresh, so
reclustering them is pure waste.

This module splits the work:

  * Every headline ever seen is persisted in ``news_headline_assignments``
    keyed by ``(source, title_key)`` where ``title_key`` is the same
    normaliser ``fetch_all`` uses for deduplication.  The row stores
    which cluster the headline belongs to.
  * Every cluster is persisted in ``news_clusters``, one row per cluster,
    carrying both the frontend-visible payload and the compact list of
    ``(source, title, published_at, url)`` records that joined it.

On refresh:

  1. Partition the incoming records into "already seen" and "new".
     Already-seen records require no work — they're already in a
     cluster and that cluster still carries the right metadata.
  2. Cluster the *new* records among themselves via the existing
     ``cluster_headlines`` function (so all the TF-IDF / polarity /
     summary / consensus logic stays in one place).
  3. For each resulting new-batch cluster, attempt to merge it into an
     *active* existing cluster by running the same similarity +
     polarity check between the new cluster's representative headline
     and each active cluster's representative headline.  On a match,
     the new records join the existing cluster and its metadata is
     rebuilt over the true union of stored + new records.  On no
     match, the new-batch cluster is inserted as a fresh cluster row.
  4. Drop clusters whose latest_published_at is older than the
     recency window from the returned payload.  They remain in the DB
     for diagnostics but no longer surface on /news.

Tunable recency window
----------------------
``_RECENCY_HOURS`` is the window inside which clusters stay live for
matching + display.  Calibrated in
``tools/news_cluster_store_validation.py`` against a representative
refresh cadence: 8 refreshes over 16 hours, 300-headline batches
with 95% overlap (5% genuinely new per refresh).  Grounded numbers:

                 reclustered / 2400 reads     recluster rate    hit rate
    tight (6h)           405                      16.9%          83.1%
    short (24h)          405                      16.9%          83.1%
    current (48h)        405                      16.9%          83.1%
    wide (96h)           405                      16.9%          83.1%

Above 6 hours the recluster rate plateaus because it's bounded below
by "bootstrap + 5% new per refresh" — every genuinely-new headline has
to go through cluster_fn regardless of window width.  The choice of
48h is therefore driven not by compute savings (all windows tie) but
by how long a story should keep picking up new sources before being
treated as "archived".  48h covers a full weekend news cycle; 6h
would drop Saturday stories by Sunday morning.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Callable, Optional

_log = logging.getLogger("second_order.news_cluster_store")


# ---------------------------------------------------------------------------
# Tunables — see module docstring and tools/news_cluster_store_validation.py
# ---------------------------------------------------------------------------

_RECENCY_HOURS: int = 48
_MERGE_COSINE_THRESHOLD: float = 0.20  # matches news_sources._CLUSTER_THRESHOLD


# ---------------------------------------------------------------------------
# Small helpers that wrap news_sources primitives
# ---------------------------------------------------------------------------


def _dedup_key(title: str) -> str:
    """Delegate to the same normaliser fetch_all uses."""
    from news_sources import _dedup_key as _impl
    return _impl(title)


def _record_key(rec: dict) -> tuple[str, str]:
    return (rec.get("source", ""), _dedup_key(rec.get("title", "")))


def _similarity(headline_a: str, headline_b: str) -> tuple[float, int, int]:
    """Return (cosine, polarity_a, polarity_b) for a pair of headlines.

    Delegates to the TF-IDF + polarity helpers in news_sources so we
    never diverge from the live clusterer's similarity metric.
    """
    from news_sources import (
        _build_tfidf_vectors, _cosine_sim, _tokenize, _headline_polarity,
    )
    vecs, _ = _build_tfidf_vectors([headline_a, headline_b])
    cos = _cosine_sim(vecs[0], vecs[1])
    pa = _headline_polarity(_tokenize(headline_a))
    pb = _headline_polarity(_tokenize(headline_b))
    return cos, pa, pb


def _can_merge(headline_a: str, headline_b: str) -> bool:
    """True when two representative headlines should collapse into one cluster.

    Applies the same gate used by ``news_sources.cluster_headlines``:
    cosine similarity ≥ threshold AND no clear polarity conflict.
    """
    cos, pa, pb = _similarity(headline_a, headline_b)
    if cos < _MERGE_COSINE_THRESHOLD:
        return False
    if pa != 0 and pb != 0 and pa != pb:
        return False
    return True


# ---------------------------------------------------------------------------
# Partitioning + metadata rebuild
# ---------------------------------------------------------------------------


def _partition_records(
    records: list[dict],
    assignments: dict[tuple[str, str], int],
) -> tuple[list[dict], list[dict]]:
    """Split records into (already_seen, new) using the assignments map."""
    known: list[dict] = []
    new: list[dict] = []
    for rec in records:
        if _record_key(rec) in assignments:
            known.append(rec)
        else:
            new.append(rec)
    return known, new


def _merge_records_unique(
    existing: list[dict], new: list[dict],
) -> list[dict]:
    """Return ``existing + new`` with (source, title_key) deduplication."""
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for rec in existing + new:
        key = _record_key(rec)
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out


def _build_cluster_payload(
    records: list[dict],
    cluster_fn: Callable[[list[dict]], list[dict]],
) -> Optional[dict]:
    """Rebuild the frontend-visible payload for a cluster from its records.

    We call the full ``cluster_fn`` (a.k.a. ``cluster_headlines``) on
    just the cluster's own records.  That gives us one output cluster
    with freshly computed summary / consensus / evidence / agreement /
    source list / representative headline — identical shape to what a
    full recluster would have produced.

    Returns None when the rebuild produces an empty list (shouldn't
    happen in practice; defensive guard against a degenerate
    ``cluster_fn`` stub).
    """
    if not records:
        return None
    try:
        rebuilt = cluster_fn(records) or []
    except Exception:
        _log.warning(
            "news_cluster_store: cluster_fn rebuild failed", exc_info=True,
        )
        return None
    if not rebuilt:
        return None
    # cluster_fn on a homogeneous cluster should return exactly one entry.
    # If the rebuild split the cluster (because intra-cluster similarity
    # dropped below threshold), we fall back to the biggest output — the
    # incremental caller will handle the rest via normal merge/insert.
    rebuilt.sort(key=lambda c: c.get("source_count", 0), reverse=True)
    return rebuilt[0]


# ---------------------------------------------------------------------------
# Core entry point
# ---------------------------------------------------------------------------


def refresh_clusters(
    records: list[dict],
    *,
    cluster_fn: Optional[Callable[[list[dict]], list[dict]]] = None,
    now: Optional[datetime] = None,
    recency_hours: int = _RECENCY_HOURS,
    load_assignments_fn: Optional[Callable[[], dict]] = None,
    load_clusters_fn: Optional[Callable[[Optional[str]], list[dict]]] = None,
    insert_cluster_fn: Optional[Callable[..., Optional[int]]] = None,
    update_cluster_fn: Optional[Callable[..., bool]] = None,
    upsert_assignments_fn: Optional[Callable[[list, str], None]] = None,
) -> list[dict]:
    """Incremental clustering for the /news refresh path.

    Returns the list of live clusters (newest-first, multi-source-first)
    ready for direct attachment to the /news response payload.

    All DB accessors are injectable so tests can run this without a
    real SQLite file.  The defaults resolve to ``db.*`` helpers on
    first use.
    """
    now_dt = now or datetime.now()

    # Late-import defaults — same DI pattern as market_check_freshness
    # and movers_cache, keeps this module cheap to import.
    if cluster_fn is None:
        from news_sources import cluster_headlines
        cluster_fn = cluster_headlines
    if load_assignments_fn is None:
        from db import load_news_headline_assignments
        load_assignments_fn = load_news_headline_assignments
    if load_clusters_fn is None:
        from db import load_news_clusters
        load_clusters_fn = load_news_clusters
    if insert_cluster_fn is None:
        from db import insert_news_cluster
        insert_cluster_fn = insert_news_cluster
    if update_cluster_fn is None:
        from db import update_news_cluster
        update_cluster_fn = update_news_cluster
    if upsert_assignments_fn is None:
        from db import upsert_news_headline_assignments
        upsert_assignments_fn = upsert_news_headline_assignments

    recency_cutoff_iso = (
        now_dt - timedelta(hours=recency_hours)
    ).isoformat(timespec="seconds")

    # 1. Load everything that's already known.
    assignments = load_assignments_fn()
    active_clusters = load_clusters_fn(recency_cutoff_iso) or []

    # 2. Split incoming records into "seen before" / "first time".
    known, new = _partition_records(records or [], assignments)

    now_iso = now_dt.replace(microsecond=0).isoformat()

    if not new:
        # No new headlines — nothing to do.  Just return the active set.
        return _sort_output([c["payload"] for c in active_clusters])

    # 3. Cluster the new records among themselves via the real clusterer.
    try:
        new_batch_clusters = cluster_fn(new) or []
    except Exception:
        _log.warning(
            "news_cluster_store: cluster_fn failed on new batch",
            exc_info=True,
        )
        # Degrade: return the existing active set unchanged so /news
        # never crashes on a transient clusterer bug.
        return _sort_output([c["payload"] for c in active_clusters])

    # Build an index of new-batch clusters by their representative
    # headline so we can match them to persisted clusters.
    active_by_id: dict[int, dict] = {c["id"]: c for c in active_clusters}

    pending_assignments: list[tuple[str, str, int]] = []
    touched_ids: set[int] = set()
    created_ids: list[int] = []

    for new_cluster in new_batch_clusters:
        new_headline = new_cluster.get("headline", "") or ""
        new_sources = new_cluster.get("sources", []) or []
        new_records_in_cluster = _records_for_new_cluster(new, new_cluster)

        # 4a. Try to merge into an existing active cluster.
        match_id = _find_merge_target(new_headline, active_clusters)

        if match_id is not None:
            existing = active_by_id[match_id]
            merged_records = _merge_records_unique(
                existing["records"], new_records_in_cluster,
            )
            rebuilt = _build_cluster_payload(merged_records, cluster_fn)
            if rebuilt is None:
                rebuilt = existing["payload"]
            latest = _max_published(rebuilt, existing["latest_published_at"])
            update_cluster_fn(
                match_id,
                rebuilt.get("headline", "") or "",
                rebuilt,
                merged_records,
                latest,
                now_iso,
            )
            # Refresh the local copy so subsequent new-clusters in the
            # same refresh see the updated records.
            existing["payload"] = rebuilt
            existing["records"] = merged_records
            existing["latest_published_at"] = latest
            touched_ids.add(match_id)

            for rec in new_records_in_cluster:
                src, key = _record_key(rec)
                pending_assignments.append((src, key, match_id))
            continue

        # 4b. No existing match — insert as a brand-new cluster row.
        latest = _max_published(new_cluster, "")
        cluster_id = insert_cluster_fn(
            new_headline,
            new_cluster,
            new_records_in_cluster,
            latest,
            now_iso,
        )
        if cluster_id is None:
            # Rare: DB not ready.  Fall through with the payload but
            # skip assignments.  The /news endpoint still serves a
            # sensible listing.
            _log.warning(
                "news_cluster_store: insert_cluster returned None; skipping"
            )
            continue
        created_ids.append(cluster_id)
        # Append to the in-memory list so later iterations in this
        # same refresh can merge into the brand-new cluster instead of
        # creating a duplicate.
        active_clusters.append({
            "id":                  cluster_id,
            "headline":            new_headline,
            "payload":             new_cluster,
            "records":             new_records_in_cluster,
            "latest_published_at": latest,
            "updated_at":          now_iso,
        })
        active_by_id[cluster_id] = active_clusters[-1]
        for rec in new_records_in_cluster:
            src, key = _record_key(rec)
            pending_assignments.append((src, key, cluster_id))

    if pending_assignments:
        upsert_assignments_fn(pending_assignments, now_iso)

    return _sort_output([c["payload"] for c in active_clusters])


# ---------------------------------------------------------------------------
# Helpers for the core loop
# ---------------------------------------------------------------------------


def _records_for_new_cluster(
    new_records: list[dict], new_cluster_output: dict,
) -> list[dict]:
    """Extract the raw records that belong to a new-batch cluster.

    ``cluster_fn`` returns a compact summary per cluster without the
    underlying record list.  We reconstruct it by matching sources:
    the new-batch cluster's ``sources`` list names every publisher in
    the cluster, and there's exactly one record per publisher in the
    new batch (fetch_all already deduped).  Records whose source isn't
    in the new cluster's source list are skipped.
    """
    wanted_sources = {
        s.get("name") for s in (new_cluster_output.get("sources") or [])
        if s.get("name")
    }
    if not wanted_sources:
        # Stub clusterer that omits sources — fall back to the
        # representative headline match.
        target_key = _dedup_key(new_cluster_output.get("headline", ""))
        return [r for r in new_records if _dedup_key(r.get("title", "")) == target_key]

    target_key = _dedup_key(new_cluster_output.get("headline", ""))
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for rec in new_records:
        if rec.get("source") not in wanted_sources:
            continue
        key = _record_key(rec)
        if key in seen:
            continue
        # Only attach records that actually cluster into this bucket —
        # we use the representative headline's dedup key as a coarse
        # filter.  Anything that didn't merge against that key via
        # cluster_fn's TF-IDF step gets skipped (it belongs to a
        # different new cluster).
        if target_key and _dedup_key(rec.get("title", "")) != target_key:
            # Still accept when cluster_fn merged via fuzzy similarity —
            # cosine ≥ threshold without exact-key match.
            if not _can_merge(rec.get("title", ""), new_cluster_output.get("headline", "")):
                continue
        seen.add(key)
        out.append(rec)
    if not out:
        # Defensive: if nothing matched by source, pick any new record
        # whose title fuzzy-matches the representative headline.
        out = [
            r for r in new_records
            if _can_merge(r.get("title", ""), new_cluster_output.get("headline", ""))
        ]
    return out


def _find_merge_target(
    new_headline: str, active_clusters: list[dict],
) -> Optional[int]:
    """Return the cluster id that should absorb the new-batch cluster, or None."""
    best_id: Optional[int] = None
    best_cos: float = -1.0
    from news_sources import _build_tfidf_vectors, _cosine_sim, _tokenize, _headline_polarity
    for c in active_clusters:
        existing_headline = c.get("headline", "") or ""
        if not existing_headline:
            continue
        vecs, _ = _build_tfidf_vectors([new_headline, existing_headline])
        cos = _cosine_sim(vecs[0], vecs[1])
        if cos < _MERGE_COSINE_THRESHOLD:
            continue
        pa = _headline_polarity(_tokenize(new_headline))
        pb = _headline_polarity(_tokenize(existing_headline))
        if pa != 0 and pb != 0 and pa != pb:
            continue
        if cos > best_cos:
            best_cos = cos
            best_id = c["id"]
    return best_id


def _max_published(cluster: dict, fallback: str) -> str:
    """Return the larger of cluster['published_at'] and the fallback."""
    pub = (cluster or {}).get("published_at", "") or ""
    return max(pub, fallback or "")


def _sort_output(clusters: list[dict]) -> list[dict]:
    """Apply the canonical /news sort: multi-source first, then newest-first.

    Mirrors news_sources.cluster_headlines so the incremental path
    returns bytes-for-bytes identical ordering to a full recluster.
    """
    result = list(clusters)
    result.sort(key=lambda c: c.get("published_at", "") or "", reverse=True)
    result.sort(key=lambda c: c.get("source_count", 0), reverse=True)
    return result
