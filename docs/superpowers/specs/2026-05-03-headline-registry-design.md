# Headline Registry + Low-Impact Expiry — Design

Date: 2026-05-03
Status: Approved (ready for implementation plan)

## Goal

Track every ingested headline in a registry separate from the `events` table, record its lifecycle through the analysis pipeline, prevent reanalysis of already-analyzed keys, and expire low-impact analyzed events from active live surfaces after a configurable TTL (default 5 days). Provide zero-cost diagnostics so the operator can see what was ingested, what was skipped (and why), and which major eligible headlines have not yet been spent on.

## Non-goals

- No changes to `/movers/persistent`, `/movers/yearly`, `portfolio_view`, track-record, saved-study replay, news inbox, or candidates surfaces (CLAUDE.md frozen contracts).
- No frontend changes — affected list endpoints keep their response shape; they just return fewer rows.
- No changes to existing persistence / impact-level rules.
- No one-shot backfill of registry rows from the historical `events` table (optional operator script, deferred).

## Architecture

### 1. Data model

New table `headline_registry`. Primary key `(source, title_key)` where `title_key` uses the same `news_sources._dedup_key` normalizer as `news_headline_assignments`.

Columns:

| Column | Type | Notes |
|---|---|---|
| `source` | TEXT NOT NULL | Publisher name. |
| `title_key` | TEXT NOT NULL | Normalized headline. |
| `cluster_id` | INTEGER | Current cluster (`news_clusters.id`). Updated when cluster merges happen. No enforced FK. |
| `event_id` | INTEGER | Analyzed event row in `events`. NULL until analyzed. |
| `state` | TEXT NOT NULL | One of `seen`, `eligible`, `analyzed`, `market_checked`, `surfaced`, `expired_low_impact`. Forward-only. |
| `last_skip_reason` | TEXT | Latest reason from the existing skip taxonomy (mirrors `routes/movers.py` skip dict). |
| `impact_level` | TEXT | Copied from `conviction.impact_level` once analyzed (`low` / `medium` / `high`). |
| `first_seen_at` | TEXT NOT NULL | ISO timestamp of first ingest. |
| `last_seen_at` | TEXT NOT NULL | ISO timestamp of most recent ingest. |
| `analyzed_at` | TEXT | Set when state advances to `analyzed`. |
| `expired_at` | TEXT | Stamped lazily by `stamp_expired_if_observed` the first time a read site sees the row past TTL. |

Indexes:
- `idx_headline_registry_state` on `(state)`
- `idx_headline_registry_analyzed_at` on `(analyzed_at)`
- `idx_headline_registry_cluster` on `(cluster_id)`

State machine is forward-only on the lifecycle axis. `seen → eligible → analyzed → market_checked → surfaced → expired_low_impact`. `last_skip_reason` is updated independently (a `seen` row's skip reason can change between refreshes without regressing `state`).

### 2. Ingestion path — registry write

`news_cluster_store.refresh_clusters` already builds `pending_assignments: list[(source, title_key, cluster_id)]` for `news_headline_assignments`. Add a sibling call to `db.upsert_headline_registry_seen(pending_assignments, now_iso)`:

```sql
INSERT INTO headline_registry
  (source, title_key, cluster_id, state, first_seen_at, last_seen_at)
VALUES (?, ?, ?, 'seen', ?, ?)
ON CONFLICT(source, title_key) DO UPDATE SET
  cluster_id   = excluded.cluster_id,
  last_seen_at = excluded.last_seen_at
```

The conflict branch never touches `state`, `event_id`, `analyzed_at`, `impact_level`, or `expired_at`. This guarantees re-ingesting an already-`analyzed` headline only bumps recency and (potentially) re-points `cluster_id`.

### 3. Analysis routing — `routes/movers.py` backfill

**Lookup key.** `news_cluster_store._sort_output` returns `[c["payload"] for c in active_clusters]` (`news_cluster_store.py:282, 399`); the persisted `news_clusters.id` is dropped at this hand-off. The cluster payload visible at the backfill loop in `routes/movers.py:1159` therefore does NOT carry `cluster_id`. **All registry lookups and writes use `title_key` derived from the cluster's representative headline** (`news_sources._dedup_key(cluster["headline"])`), not `cluster_id`. This works because the cluster's representative headline already maps deterministically to the same `title_key` that `news_cluster_store` wrote to the registry on ingest.

`cluster_id` remains in the registry as a back-pointer for diagnostics and the cluster→candidates join (section 5), but is NOT load-bearing for the pre-LLM check or the analyze-stamp. The diagnostics endpoint join works because `news_cluster_store` writes the post-merge `cluster_id` at ingest time and updates it on subsequent merges.

Two changes inside the eligible-cluster loop in `routes/movers.py:1159`:

**3a. Pre-LLM registry check.** For each eligible cluster, look up registry rows by `title_key`. If any row has:
- `state ∈ {analyzed, market_checked, surfaced}` and `not force_reanalyze` → skip with `last_skip_reason='registry_already_analyzed'`, increment `skipped["registry_already_analyzed"]`, continue. Zero LLM budget consumed.
- `state == 'expired_low_impact'` and `not force_reanalyze` → skip with `last_skip_reason='registry_expired_low_impact'`, continue. Zero budget consumed.

**3b. Post-action stamp.** When `_fresh_analysis_market_event` succeeds, call `headline_registry.advance_state(title_key, new_state='analyzed', event_id=…, impact_level=…, analyzed_at=now_iso)` which updates every registry row whose `title_key` matches (across all sources). After `_market_check_event` succeeds, advance to `market_checked`. After admission to a surfaced list (e.g. `/movers/today`'s items), advance to `surfaced`.

**Skip-reason stamping.** When a cluster is skipped before the LLM step (`outside_recency_window`, `irrelevant_headline`, `low_signal`, `dry_run`, `limit_reached`, `llm_budget_exhausted`, `already_market_checked`), call `headline_registry.advance_state(title_key, last_skip_reason=<reason>)` — this writes `last_skip_reason` without regressing `state`. If the cluster passed all gates and reached the LLM-budget check (i.e. would have been analyzed), promote `state` to `eligible` first.

`force_reanalyze=True` (already a query param on `routes/movers.py:1038`) bypasses both new registry skips, in addition to its existing override of the `cached` short-circuit.

### 4. Expiry helper + read-site filter

New module `headline_registry.py`.

```python
def is_expired_low_impact(
    event_row: dict,
    registry_analyzed_at: str | None = None,
    now: datetime | None = None,
) -> bool:
    """True when an event is low-impact AND its analyzed_at is past TTL.

    Uses ``registry_analyzed_at`` when provided; falls back to
    ``event_row['timestamp']`` only when the registry analyzed_at is
    missing (e.g. legacy events analyzed before the registry existed).
    """
    impact = (event_row.get("conviction") or {}).get("impact_level")
    if impact != "low":
        return False
    anchor = registry_analyzed_at or event_row.get("timestamp")
    if not anchor:
        return False
    ttl = int(os.environ.get("HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS", "5"))
    cutoff = (now or datetime.now()) - timedelta(days=ttl)
    return _parse_iso(anchor) < cutoff


def stamp_expired_if_observed(
    event_row: dict,
    registry_analyzed_at: str | None = None,
    now: datetime | None = None,
) -> None:
    """Idempotent UPSERT setting state='expired_low_impact' + expired_at
    for every registry row matching the event's title_key. No-op when
    the row is not expired or already stamped."""
```

To avoid N round-trips per page, read sites use a bulk helper:

```python
def filter_expired_low_impact(
    event_rows: list[dict],
    now: datetime | None = None,
) -> list[dict]:
    """Bulk-load registry analyzed_at for the page's title_keys in one
    SELECT, run is_expired_low_impact per row, lazy-stamp the expired
    ones, return the surviving rows in original order."""
```

Internally:
1. Compute `title_keys = {_dedup_key(r['headline']) for r in event_rows}`.
2. `SELECT title_key, MAX(analyzed_at) FROM headline_registry WHERE title_key IN (…) GROUP BY title_key`.
3. For each event, call `is_expired_low_impact(row, registry_analyzed_at=map.get(title_key))`.
4. Lazy-stamp the expired ones via `stamp_expired_if_observed`.
5. Return non-expired rows.

`MAX(analyzed_at)` handles the case where the same `title_key` exists for multiple sources — pick the most recent (a re-analysis from a later source counts as the canonical analyzed time).

Applied **only** at:

- **`/movers/today`** — read-time filter, not cache-build-time. `api.movers_today(limit)` (`api.py:3082`) carries its own 5-minute `_TODAYS_MOVERS_CACHE`. The filter must run on the cached list at every call (in `routes/movers.py:1394` after `_api.movers_today(limit=...)` returns), not inside the cache build, otherwise rows expire mid-TTL without being filtered. Lazy-stamp happens at this read-time pass.
- **`/events` listing** in `routes/events.py:225` — applied **after `query_events_filtered` + `dedup_events` and BEFORE the offset/limit slice** (`routes/events.py:280, 391`). This matches how the existing `validated`, `mover_window`, and engine-derived filters work today (full-scan-then-paginate at `routes/events.py:369-391`) and avoids the short-page problem that filtering after pagination would create. `total` count returned to the client reflects the post-expiry universe so paginated UI shows accurate totals. Detail-by-id (`/events/{event_id}` at `routes/events.py:469`) does NOT call the filter.

Untouched (verified frozen by CLAUDE.md):
- `/events/{id}` detail
- `/movers/persistent`, `/movers/yearly`
- `portfolio_view` and Markdown export
- track-record dimensions
- saved-study replay
- news inbox
- candidates view

### 5. Diagnostics

`GET /registry/diagnostics` (added to existing diagnostics route module if one exists; otherwise create `routes/diagnostics.py`). Pure SQL, zero LLM cost.

Response shape:
```json
{
  "state_counts": {
    "seen": N, "eligible": N, "analyzed": N,
    "market_checked": N, "surfaced": N, "expired_low_impact": N
  },
  "skip_reason_counts": {
    "outside_recency_window": N,
    "irrelevant_headline": N,
    "low_signal": N,
    "already_market_checked": N,
    "registry_already_analyzed": N,
    "registry_expired_low_impact": N,
    "llm_budget_exhausted": N,
    "dry_run": N,
    "limit_reached": N
  },
  "last_analyzed_at": "ISO",
  "expired_count_24h": N,
  "eligible_unanalyzed_candidates": [
    {
      "headline": "…",
      "cluster_id": 1234,
      "source_count": 7,
      "has_asset_terms": true,
      "first_seen_at": "ISO",
      "last_seen_at": "ISO",
      "last_skip_reason": "irrelevant_headline" | null,
      "state": "seen" | "eligible"
    }
  ]
}
```

`eligible_unanalyzed_candidates` is built by joining `headline_registry` to `news_clusters`:

```sql
SELECT hr.cluster_id, hr.first_seen_at, MAX(hr.last_seen_at), hr.last_skip_reason, hr.state,
       nc.headline, nc.payload_json
FROM headline_registry hr
JOIN news_clusters nc ON nc.id = hr.cluster_id
WHERE hr.state IN ('seen', 'eligible')
  AND hr.event_id IS NULL
GROUP BY hr.cluster_id
ORDER BY json_extract(nc.payload_json, '$.source_count') DESC,
         hr.last_seen_at DESC
LIMIT 50
```

`source_count` and `has_asset_terms` come out of the cluster payload (the same signals the backfill route uses to rank `eligible_clusters` at `routes/movers.py:1146`). This surfaces *major* headlines that did not turn into LLM calls — exactly the gap the operator wants to see.

Optional `?since_hours=24` scopes counts to recent activity; default returns all-time counts plus the candidate list.

## Edge cases

- **Cluster merges.** When `news_cluster_store.refresh_clusters` merges new records into an existing cluster, the registry write uses the final `cluster_id` (post-merge) because `pending_assignments` already carries the correct id. The `title_key`-based lookups used at the backfill loop are unaffected by merges since the title_key is derived from the headline content, not cluster membership.
- **Registry empty on first deploy.** Pre-existing analyzed events in `events` have no registry row. The pre-LLM check at 3a finds no row and falls through to the existing `cached` short-circuit in the backfill loop — no regression. Registry populates naturally as new headlines arrive and as backfill runs touch their clusters.
- **Pre-registry events at read-time expiry.** Old analyzed events have no registry row, so `filter_expired_low_impact` finds no `registry_analyzed_at` and falls back to `event_row['timestamp']` per `is_expired_low_impact`'s spec. This preserves expected behavior for the historical archive without requiring a one-shot backfill.
- **Same `title_key` from multiple sources.** Each gets its own registry row. `advance_state(title_key, …)` updates all rows with that title_key; bulk read uses `MAX(analyzed_at) GROUP BY title_key` so the most-recent analysis wins for expiry math.
- **State race.** SQLite serializes writes. The state machine is forward-only and the ingest UPSERT never writes `state` on conflict; concurrent ingest + analysis cannot regress state.
- **Detail-by-id is always served.** `/events/{id}` does not call the expiry filter. CLAUDE.md is explicit that detail views must keep proof/falsifier content visible.

## Tests — `tests/test_headline_registry.py`

1. **Ingest writes seen.** `refresh_clusters` over a fixture upserts one registry row per record with `state='seen'`, correct `cluster_id`, `first_seen_at == last_seen_at`.
2. **No state regression.** Re-ingesting an already-`analyzed` headline bumps `last_seen_at` only; `state`, `event_id`, `analyzed_at`, `impact_level`, `expired_at` unchanged.
3. **Skip-reason stamping.** A cluster filtered by `irrelevant_headline` lands `last_skip_reason='irrelevant_headline'` on its registry rows; `state` stays `seen`.
4. **Backfill skips analyzed registry row.** With `force_reanalyze=False` and a pre-stamped `analyzed` row, backfill returns `skipped: {registry_already_analyzed: 1}`; `diagnostics.llm_calls == 0`.
5. **Backfill skips expired registry row.** `state='expired_low_impact'`, `force_reanalyze=False` → `skipped: {registry_expired_low_impact: 1}`; LLM calls = 0.
6. **`force_reanalyze=True` overrides both registry skips** (analyzed and expired).
6a. **Title-key lookup independent of cluster_id.** With a registry row whose `cluster_id` is null/stale, the pre-LLM check still finds the row by `title_key` and short-circuits correctly.
7. **`is_expired_low_impact` boundary cases.**
   - low + registry analyzed_at past TTL → True
   - low + registry analyzed_at fresh → False
   - low + registry analyzed_at missing, event timestamp past TTL → True (fallback works)
   - low + registry analyzed_at fresh, event timestamp old → False (registry wins)
   - high + old → False
   - missing impact_level → False
   - env override `HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS=1` shrinks the window
8. **`/movers/today` hides expired-low and lazy-stamps.** Fixture: one fresh-low + one old-low. After call, only fresh-low surfaces; old-low's registry row has `state='expired_low_impact'` and `expired_at` set.
9. **`/events` listing hides expired-low; `/events/{id}` still serves it.**
10. **`/movers/persistent` & `/movers/yearly` regression guard.** Old-low-impact still excluded from persistent for the original (impact-level) reason; expiry isn't double-counted; counts and ordering match a baseline snapshot taken before the change.
11. **Diagnostics state counts** match a synthetic ingest+backfill flow.
12. **`eligible_unanalyzed_candidates` ranking.** Two `seen` rows: one with cluster `source_count=7`, one with `source_count=1`. The 7-source one ranks first.
13. **`/events` listing total reflects post-expiry universe.** With one expired-low-impact row in the matched set, `total` returned to the client equals (rows after dedup) − 1, not the raw row count, so paginated UI sees a consistent total.
14. **`/movers/today` filter applies on cached payload.** With `_TODAYS_MOVERS_CACHE` warm and an expired-low row in the cache, the second call to `/movers/today` still hides the expired row (filter runs at read time, not cache build time).

Frontend: `npm run typecheck && npm run build` only — no UI changes; surfaces just return fewer rows.

## Files touched

- `db.py` — new CREATE TABLE block + indexes; `upsert_headline_registry_seen`, `advance_registry_state`, `load_registry_diagnostics`, `load_eligible_unanalyzed_candidates`.
- `news_cluster_store.py` — one extra DI-injected call alongside the existing `upsert_assignments_fn`.
- `headline_registry.py` (new) — `is_expired_low_impact`, `stamp_expired_if_observed`, `filter_expired_low_impact`, `advance_state` thin wrapper.
- `routes/movers.py` — pre-LLM registry check, post-action stamp, `/movers/today` filter, skip-reason stamping in the eligible-cluster loop.
- `routes/events.py` — listing filter (detail unchanged).
- `routes/diagnostics.py` (new) or extend an existing diagnostics module — `/registry/diagnostics`.
- `tests/test_headline_registry.py` (new).
- `.env.example` — document `HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS=5`.

## Out of scope

- Persistence / impact rule changes (frozen).
- `/movers/persistent` & `/movers/yearly` read contracts (frozen).
- portfolio_view / Markdown export (frozen).
- News inbox / candidates / saved-study replay (frozen).
- Frontend changes (no shape changes).
- One-shot historical backfill of the registry from `events` (optional operator script, deferred).
