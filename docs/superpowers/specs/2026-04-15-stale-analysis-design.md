# Stale Analysis Detection — Design Spec
**Date:** 2026-04-15

## Problem

Saved analyses in Archive and Portfolio show market data (ticker returns, direction tags, support ratios) that was captured at analysis time. As time passes, those figures become outdated. Users have no signal that an analysis's market data may no longer reflect current conditions, and no way to refresh it without re-entering the full analyze flow.

## Scope

Detect staleness based on market check age. Surface a stale badge in Archive and Portfolio rows. Provide an inline Refresh button (hover/expand) that refreshes market tickers only — no LLM reanalysis. Frozen events (>30 days) show an "Archived" indicator with no refresh action.

## Staleness Signal

Driven by `compute_staleness()` from `market_check_freshness.py` (existing, pure, no I/O):

| `stale_signal` | Meaning | UI treatment |
|---|---|---|
| `fresh` | Within refresh threshold | No indicator |
| `stale` | Past threshold (4h for ≤7d events, 24h for >7d events) | Amber dot + "Data outdated" + Refresh on hover |
| `legacy` | Missing `last_market_check_at` | Same as stale |
| `frozen` | Event >30 days old | Muted dot + "Archived" — no refresh |

## Architecture

### 1. Backend: List endpoint annotation

`routes/events.py` and the portfolio route annotate each row after DB load:

```python
from market_check_freshness import compute_staleness

for row in rows:
    sig = compute_staleness(row)
    row["stale_signal"] = sig["status"]
    row["hours_since_check"] = sig.get("hours_since_check")
    row["event_age_days"] = sig.get("event_age_days")
```

Pure computation, no I/O. Fields are additive — existing consumers ignore them.

### 2. Backend: Refresh endpoint

```
POST /events/{id}/refresh-market
```

Added to `routes/events.py`. Backed by existing `refresh_market_for_saved_event(event, force=False)` from `market_check_freshness.py`. That function already:
- Respects the frozen gate (returns `status: "frozen"` for >30d events, no actual refresh)
- Calls `market_check`, stamps `last_market_check_at`, persists via `db.update_event_market_refresh`

Response: `{ status, tickers, note, hours_since_check, event_age_days }`

Returns 404 if event id not found.

### 3. Frontend: Types + API client

New additions to `frontend/src/lib/api.ts`:

```typescript
export type StaleSignal = "fresh" | "stale" | "frozen" | "legacy";
```

Added to existing event/portfolio types (additive fields):
```typescript
stale_signal?: StaleSignal;
hours_since_check?: number | null;
event_age_days?: number | null;
```

New API method:
```typescript
refreshMarket: (id: number) =>
  request<{ status: string; tickers: Ticker[]; note: string; hours_since_check?: number }>(
    `/events/${id}/refresh-market`, { method: "POST" }
  ),
```

New query key: `qk.refreshMarket(id)`.

### 4. Frontend: Archive (recent-events.tsx)

Staleness indicator added to the bottom strip of each event card, conditional on `stale_signal`:

- `stale` or `legacy`: amber dot + "Data outdated" label. Hover reveals a "Refresh" button.
- `frozen`: muted gray dot + "Archived" label. No Refresh button.
- `fresh`: nothing rendered.

Refresh button: `useMutation` → `POST /events/{id}/refresh-market` → on success, `queryClient.invalidateQueries(qk.events())`. Spinner + disabled state while in-flight.

No new component — inline additions to existing card bottom strip.

### 5. Frontend: Portfolio page

Same pattern. Mutation on success invalidates `qk.portfolio()`. The refetch picks up updated `market_tickers` (direction tags, return_5d) automatically, which flows through to the validation outcome and support ratio display.

## Data Flow

```
GET /events
  → load_recent_events()
  → annotate each row with compute_staleness()  [pure, no I/O]
  → return rows with stale_signal, hours_since_check, event_age_days

POST /events/{id}/refresh-market
  → load event by id
  → refresh_market_for_saved_event(event)
    → compute_staleness() → if frozen, return early
    → market_check(beneficiary_tickers, loser_tickers, event_date)
    → db.update_event_market_refresh(id, tickers, note, last_market_check_at)
  → return updated market block
```

## Testing

**Backend:**
- `tests/test_stale_signal_annotation.py` — annotation pass: `stale_signal` present on all rows; frozen rows get `"frozen"`; fresh rows get `"fresh"`; stale rows get `"stale"`.
- `tests/test_refresh_market_endpoint.py` — 404 on missing id; frozen event returns `status: "frozen"` without calling `market_check`; stale event calls refresh and returns updated tickers.

**Frontend:**
- `frontend/src/components/pages/__tests__/stale-signal.test.ts` — maps `StaleSignal` → display state (dot color, label, Refresh button presence). Pure helper function, no mount needed.

## Constraints

- Frozen events (>30d): backend enforces no-refresh even if the frontend somehow sends a request.
- No LLM reanalysis. Refresh only touches market tickers, `last_market_check_at`, and `market_note`.
- `compute_staleness` is not called at DB write time — it's computed on read. No schema changes needed.
- Existing `market_check_freshness.py` and `event_age_policy.py` thresholds are not modified.
