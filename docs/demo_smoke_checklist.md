# Demo Smoke Checklist — Second Order

A practical pre-demo walk-through to confirm the local stack is healthy
and every demo-critical surface renders without surprises. Run top to
bottom; each section takes < 1 minute.

PowerShell commands assume the repo root is the current directory. The
backend serves on `http://127.0.0.1:8000`; the frontend dev server on
`http://localhost:5173`.

Cost legend used throughout:

- **[zero-cost]** — pure read of cached / SQLite / in-memory state. Safe
  to run repeatedly. No LLM, no `market_check`, no `yfinance`.
- **[paid]** — calls `analyze_event`, `market_check`, or `yfinance`.
  Spends API credits. Run intentionally, never in a polling loop.

---

## 0. Local startup

```powershell
# Backend (terminal 1)
python -m uvicorn api:app --reload

# Frontend (terminal 2)
cd frontend
npm run dev
```

Sanity check both processes are alive:

```powershell
# Backend health probe — [zero-cost]
curl http://127.0.0.1:8000/openapi.json | Out-Null; if ($?) { "backend ok" }
```

Open `http://localhost:5173` in the browser and confirm the dark theme
loads and the left-rail navigation is present.

---

## 1. Market Context  *(top-level macro panel)*

Endpoint: `GET /market-context`  **[zero-cost]**

```powershell
curl http://127.0.0.1:8000/market-context | ConvertFrom-Json |
  Select-Object -Property source,
    @{n='snaps_meta';e={$_.snapshots_meta}},
    @{n='note';e={$_.snapshot_freshness_note}}
```

Confirm:

- `snapshots_meta.total = 8`.
- `snapshots_meta.fresh = 8` after a healthy first call. If `unavailable
  > 0`, read `snapshot_freshness_note` — the operator-facing string
  distinguishes "not refreshed yet" from a real provider failure.
- `stress.regime` is set (e.g. `"Calm"`, `"Stress"`).
- `rates`, `regime_vector`, `credit_regime`, `funding_stress_mode`,
  `sector_rotation`, `finance_playbook` each carry an `available` flag.
- `context_explanations` carries the static A/B card copy the frontend
  uses for hover/legend text. It is a constant — empty here means the
  block was rewritten unintentionally.

If everything is `unavailable`, `yfinance` is being rate-limited or
network-blocked — re-run `curl` once or twice; do **not** chain rapid
retries.

UI: navigate to **Market Overview**. The benchmark strip should show 8
tiles with values; if a tile is dim, the freshness note explains why.

---

## 2. Section C — Still Moving Markets  *(persistent + weekly + today)*

Endpoints **[zero-cost]** (all serve from cached mover slices):

```powershell
curl "http://127.0.0.1:8000/movers/today?limit=5"      | ConvertFrom-Json
curl "http://127.0.0.1:8000/movers/weekly?limit=5"     | ConvertFrom-Json
curl "http://127.0.0.1:8000/movers/persistent?limit=5" | ConvertFrom-Json
curl "http://127.0.0.1:8000/movers/yearly?limit=5"     | ConvertFrom-Json
```

Confirm:

- `/movers/today` returns 0–N rows; row count of 0 is acceptable when no
  fresh analyzed event currently has a confirmed move.
- Each card carries `headline`, `tickers`, `conviction`, `evidence`,
  `mover_window`.

**Truthfully-empty surfaces.** `Weekly` and `Persistent` can return
`[]` even on a healthy stack — the high-conviction gate refuses to
backfill with low/medium-impact filler. An empty list is the correct
signal when no event clears the bar; do NOT treat it as a bug or
attempt to "fix" it by relaxing the gate.

UI: **Market Overview → Still Moving Markets** should render the
cards or an explicit "no qualifying events" empty state.

---

## 3. Headlines  *(news cluster cache)*

Endpoint: `GET /news`  **[zero-cost]**

```powershell
curl "http://127.0.0.1:8000/news?limit=10" | ConvertFrom-Json |
  Select-Object total_headlines,
    @{n='clusters';e={$_.clusters.Count}},
    @{n='refresh';e={$_.refresh_meta.freshness}}
```

Confirm:

- `clusters` is non-empty (the cache may take ~30s after first start).
- `refresh_meta.freshness` is one of `"fresh"`, `"degraded"`, or
  `"stale"`. `"degraded"` means at least one source feed failed in the
  last refresh — the cluster pipeline still ran and the response is
  usable; check `refresh_meta.fail_feeds` for the count.
- Each cluster carries `headline`, `source_count`, `published_at`,
  `sources[]`.

UI: **Headlines** view shows ranked clusters. If empty, give the news
fetcher 30 seconds and refresh the page.

---

## 4. Archive  *(saved events list)*

Endpoint: `GET /events`  **[zero-cost]**

```powershell
curl "http://127.0.0.1:8000/events?limit=10" | ConvertFrom-Json |
  Select-Object total, offset, limit,
    @{n='items';e={$_.items.Count}}
```

Confirm:

- `total` reflects the filtered, deduped, post-expiry universe.
- Default listing hides mock / demo / degraded / expired-low-impact
  rows. To see them: append `?include_mock=true` (only restores
  mock/demo/degraded — expired-low-impact stays filtered by design).
- Paging works: `?offset=10&limit=10` returns the next page with
  `total` unchanged.

Detail by id is always served, even for hidden rows:

```powershell
curl "http://127.0.0.1:8000/events/1" | ConvertFrom-Json | Select-Object id, headline
```

UI: **Archive** view should list events with filter controls intact.

---

## 5. Event Detail

Pick a real `event_id` from `/events` and open it in the UI, or:

```powershell
curl "http://127.0.0.1:8000/events/1" | ConvertFrom-Json |
  Select-Object id, headline, thesis_state, validation_rationale,
    @{n='proof';e={$_.proof_status.status}},
    @{n='falsifier';e={$_.falsifier_status.status}}
```

Confirm:

- `thesis_state` is one of the documented values
  (`confirming` / `pending` / `low_information` / `falsified` / etc.).
- Proof / falsifier blocks render with `items` arrays (may be empty
  for low-information events).
- Engine-Reference content sits **after** proof / falsifier on the page
  (frozen UI boundary).

UI: **Event Detail** view should show the full thesis + supporting
sections without console errors.

---

## 6. Portfolio

Endpoint: `GET /portfolio`  **[zero-cost]**

```powershell
curl "http://127.0.0.1:8000/portfolio?limit=10" | ConvertFrom-Json
curl "http://127.0.0.1:8000/portfolio?limit=10&quality_tier=actionable&tradable=true"
```

Confirm:

- Default response is a bare list (legacy contract).
- Filtered request (with any of `quality_tier`, `tradable`,
  `mechanism_subtype`) returns the `{items, ...counts}` envelope.
- Saved-study replay still works via `?study=portfolio_view&...`.

UI: **Portfolio** view filters update the count bar and table without
full-page reloads.

---

## 7. Backfill preview  *(cost-safe candidate ranking)*

Endpoint: `GET /movers/backfill-preview`  **[zero-cost]** — this is a
read-only classifier; it never spends LLM credits or calls the market.

```powershell
curl "http://127.0.0.1:8000/movers/backfill-preview?limit=10" |
  ConvertFrom-Json |
  Select-Object @{n='items';e={$_.items.Count}},
    @{n='counts';e={$_.counts}},
    @{n='skip';e={$_.skip_reasons}}
```

Confirm:

- `counts.eligible`, `counts.already_analyzed`, `counts.would_call_llm`
  add up consistently.
- Each item carries `headline`, `source_count`, `rank_score`,
  `rank_factors` (with `macro_policy`, `geopolitical`, `commodity_policy`,
  `corporate_action`, `generic_finance_noise` booleans plus
  `high_tier_sources` count). Major macro headlines should rank above
  generic finance wrap headlines even at lower source_count.
- `skip_reasons` aggregates the pre-filter rejections.

Paid path *(do not run in casual demo)*: `POST /movers/backfill-recent`
with `dry_run=false` and an explicit `confirm_paid=true` is **[paid]**
— it spends LLM credits and writes events.

---

## 7b. Manual paid candidate analysis  *(NOT part of the no-paid smoke pass)*

Endpoint: `POST /movers/backfill-candidate`  **[paid]**

Spends exactly **one** LLM call by design — the route analyzes the
single requested headline and writes the resulting event. It is the
manual "promote one preview row" companion to `/movers/backfill-recent`.
Skip this section entirely during a no-paid smoke pass; only run when
you intentionally want to bring one specific headline into the archive.

**Step 1 — preview first (zero-cost).** Always identify the headline
and confirm it is `eligible / would_call_llm=true` via the preview
before authorising spend:

```powershell
# [zero-cost] — pick a candidate from the preview output.
curl "http://127.0.0.1:8000/movers/backfill-preview?limit=10" |
  ConvertFrom-Json |
  Select-Object -ExpandProperty items |
  Where-Object { $_.skip_reason -eq $null -and $_.would_call_llm } |
  Select-Object -First 5 headline, source_count, rank_score
```

**Step 2 — paid invocation (example only — do not run in casual demo).**
The endpoint refuses the request unless `confirm_paid=true` is passed
explicitly. Match the headline string exactly to a preview row.

```powershell
# [paid] — example only.  Spends one LLM call and writes one event.
$headline = "Fed signals two rate cuts at next meeting"
curl -Method POST "http://127.0.0.1:8000/movers/backfill-candidate" `
  -Body @{ headline = $headline; confirm_paid = "true" } |
  ConvertFrom-Json |
  Select-Object status, reason, analyzed, persisted, event_id, llm_calls
```

Confirm (when intentionally run):

- `llm_calls` is `0` or `1` — never higher (single-candidate guarantee).
- `status` is `ok` (analyzed + persisted) or a documented `degraded` /
  `skipped` reason — `confirm_paid_required` indicates the gate
  rejected the call before any spend.
- `event_id` is set on success and the row appears in `/events` on the
  next read.

---

## 8. Registry diagnostics  *(headline lifecycle health)*

Endpoint: `GET /registry/diagnostics`  **[zero-cost]**

```powershell
curl "http://127.0.0.1:8000/registry/diagnostics" | ConvertFrom-Json |
  Select-Object last_analyzed_at, last_surfaced_at,
    @{n='counts';e={$_.counts}},
    @{n='states';e={$_.state_counts}},
    @{n='top_eligible';e={$_.eligible_unanalyzed_candidates |
      Select-Object -First 3 headline, source_count}}
```

Confirm:

- `counts.eligible_unanalyzed`, `counts.analyzed_recent`,
  `counts.surfaced_recent`, `counts.expired_low_impact` are all
  integers.
- `last_analyzed_at` is set if any event has been analyzed.
  `last_surfaced_at` is `null` on a cold demo box (no surfaced rows yet).
- `eligible_unanalyzed_candidates` ranks major headlines first by
  source_count.
- `?recent_hours=72` widens the `analyzed_recent` / `surfaced_recent`
  windows — useful when the demo box has been idle.

---

## 9. Snapshots  *(benchmark strip data source)*

Endpoint: `GET /snapshots`  **[zero-cost]** (warm read).
`?refresh=true` triggers a synchronous provider refresh — only run
once before the demo if the values are clearly stale.

```powershell
# Warm read — never spends provider quota.
curl http://127.0.0.1:8000/snapshots | ConvertFrom-Json |
  Select-Object market, value, stale, error

# Force refresh — only before the demo, not during.  Hits yfinance.
curl "http://127.0.0.1:8000/snapshots?refresh=true" | Out-Null
```

Confirm:

- 8 rows, canonical order (ES, NQ, RTY, CL, GC, DXY, 2Y, 10Y).
- Every row has `value` set OR an explicit `error` string.
- `stale=true` after the 2-minute TTL passes is normal — the strip
  still renders cached values.
- `/snapshots` and `/market-context` agree on per-row `value` /
  `error` / `stale` after a refresh.

---

## Pre-demo final pass  *(60 seconds)*

1. `GET /market-context` → no `snapshot_freshness_note` (or a benign
   "X of 8 cached" note); `stress.available = true`.
2. `GET /movers/today` → 1+ cards if there is fresh analyzed news;
   empty is OK.
3. `GET /events?limit=5` → `total > 0`, items decorated with
   `validation_status`, `thesis_state`.
4. `GET /registry/diagnostics` → `counts.analyzed_recent > 0` if a
   backfill has run today; `eligible_unanalyzed_candidates` ranked
   by source_count.

If anything above is empty when it should not be, check the backend
log for `yfinance` rate-limit warnings or a missing
`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` env var. Do not regenerate
the news cache or run a paid backfill mid-demo.
