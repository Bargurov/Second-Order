# Archive Search & Filter Design Spec
**Date:** 2026-04-17
**Status:** Approved

## Problem

The Archive page loads 50 events and applies all filtering client-side. As the archive grows to hundreds of events, client-side filtering on a partial load will silently miss results — users searching for a specific theme or stage will see an incomplete picture. The filter must be truth-based: what the server returns is what matches, not "what happened to be preloaded."

## Goal

Add server-side search and filtering to the `/events` endpoint so Archive remains accurate and usable at any scale. Add a validation status filter (did the market move with the thesis?). Add pagination.

## Constraints

- Additive only — no new endpoints, no breaking changes for existing `/events` callers that send no params
- No DB schema changes
- Preserve all existing Archive behavior (pins, sort, bulk export, selection mode, expand/collapse, delete)
- `search` is keyword/theme search over stored text fields — not a sector taxonomy

---

## Section 1 — Backend

### 1.1 New DB function: `query_events_filtered`

Add to `db.py`. Returns all rows matching the provided filters (no pagination — the route layer does dedup + validation post-filtering before slicing):

```python
def query_events_filtered(
    *,
    search: str | None = None,
    stage: str | None = None,
    persistence: str | None = None,
    confidence: str | None = None,
    rating: str | None = None,
    date_from: str | None = None,   # ISO date: "YYYY-MM-DD"
    date_to: str | None = None,     # ISO date: "YYYY-MM-DD", treated as end-of-day
) -> list[dict]:
```

Builds a dynamic parameterized WHERE clause:

```python
clauses: list[str] = []
params: list[object] = []

if search:
    term = f"%{search}%"
    clauses.append(
        "(headline LIKE ? OR mechanism_summary LIKE ? OR beneficiaries LIKE ? OR losers LIKE ?)"
    )
    params.extend([term, term, term, term])
if stage:
    clauses.append("stage = ?")
    params.append(stage)
if persistence:
    clauses.append("persistence = ?")
    params.append(persistence)
if confidence:
    clauses.append("confidence = ?")
    params.append(confidence)
if rating:
    clauses.append("rating = ?")
    params.append(rating)
if date_from:
    clauses.append("timestamp >= ?")
    params.append(date_from)          # ISO date prefix-matches ISO timestamp
if date_to:
    clauses.append("timestamp <= ?")
    params.append(date_to + "T23:59:59")

where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
sql = f"SELECT * FROM events {where} ORDER BY id DESC"
```

Returns `[_decode_event_row(r) for r in rows]`. Returns `[]` if `_db_ready` is False.

`beneficiaries` and `losers` are stored as `TEXT` via `json.dumps` — plain UTF-8 strings, LIKE hits them directly.

### 1.2 Validation scoring helper

Add to `routes/events.py` as a module-level private function:

```python
def _score_validation(row: dict) -> str:
    """Derive validation status from stored market_tickers direction_tags.

    Returns:
        "validated"   — supporting > contradicting, ≥1 supporting
        "contradicted" — contradicting >= supporting, ≥1 contradicting
        "unresolved"  — no tickers, or all tags are absent/neutral
    """
    tickers = row.get("market_tickers") or []
    supporting   = sum(1 for t in tickers if t.get("direction_tag") == "supporting")
    contradicting = sum(1 for t in tickers if t.get("direction_tag") == "contradicting")
    if supporting == 0 and contradicting == 0:
        return "unresolved"
    if supporting > contradicting:
        return "validated"
    return "contradicted"
```

### 1.3 Updated `GET /events` handler

Replace the current handler:

```python
@router.get("/events")
def events(
    limit:       int         = Query(25, ge=1, le=100),
    offset:      int         = Query(0,  ge=0),
    search:      str | None  = Query(None),
    stage:       str | None  = Query(None),
    persistence: str | None  = Query(None),
    confidence:  str | None  = Query(None),
    rating:      str | None  = Query(None),
    date_from:   str | None  = Query(None),
    date_to:     str | None  = Query(None),
    validated:   str | None  = Query(None, pattern="^(validated|contradicted|unresolved)$"),
):
    # Step 1: DB-level filtering
    any_filter = any([search, stage, persistence, confidence, rating, date_from, date_to, validated])

    if any_filter:
        rows = query_events_filtered(
            search=search, stage=stage, persistence=persistence,
            confidence=confidence, rating=rating,
            date_from=date_from, date_to=date_to,
        )
    else:
        # Legacy path: over-fetch for dedup, same as before
        rows = load_recent_events(limit=min(limit * 2, 200))

    # Step 2: Dedup
    rows = dedup_events(rows)

    # Step 3: Decorate with computed signals
    for row in rows:
        sig = compute_staleness(row)
        row["stale_signal"]        = sig["status"]
        row["hours_since_check"]   = sig.get("hours_since_check")
        row["event_age_days"]      = sig.get("event_age_days")
        row["persistence_signal"]  = classify_persistence_signal(row)
        row["validation_status"]   = _score_validation(row)  # new field

    # Step 4: Validated post-filter
    if validated:
        rows = [r for r in rows if r["validation_status"] == validated]

    # Step 5: Total (after all filtering)
    total = len(rows)

    # Step 6: Paginate
    items = rows[offset: offset + limit]

    return _api._sanitize_floats({"items": items, "total": total, "offset": offset, "limit": limit})
```

**Backward compatibility:** Existing callers that send no params get `limit=25, offset=0` with no filters active. The legacy `load_recent_events` path is used. The only change visible to old callers is the response shape: previously `list[SavedEvent]`, now `{"items": [...], "total": N, "offset": 0, "limit": 25}`. The only consumer of `/events` is the frontend, which is updated in Section 2. The Telegram bot uses `/events/{id}` not `/events`.

The new `validation_status` field is added to every returned event (additive).

---

## Section 2 — Frontend

### 2.1 New types in `frontend/src/lib/api.ts`

```typescript
export interface EventsQuery {
  limit?:       number;
  offset?:      number;
  search?:      string;
  stage?:       string;
  persistence?: string;
  confidence?:  string;
  rating?:      string;
  date_from?:   string;
  date_to?:     string;
  validated?:   "validated" | "contradicted" | "unresolved";
}

export interface EventsPage {
  items:  SavedEvent[];
  total:  number;
  offset: number;
  limit:  number;
}
```

Add `validation_status?: "validated" | "contradicted" | "unresolved"` to `SavedEvent`.

### 2.2 Updated `events()` method in `api.ts`

```typescript
events(query: EventsQuery = {}): Promise<EventsPage> {
  const params = new URLSearchParams();
  if (query.limit   != null) params.set("limit",       String(query.limit));
  if (query.offset  != null) params.set("offset",      String(query.offset));
  if (query.search)          params.set("search",      query.search);
  if (query.stage)           params.set("stage",       query.stage);
  if (query.persistence)     params.set("persistence", query.persistence);
  if (query.confidence)      params.set("confidence",  query.confidence);
  if (query.rating)          params.set("rating",      query.rating);
  if (query.date_from)       params.set("date_from",   query.date_from);
  if (query.date_to)         params.set("date_to",     query.date_to);
  if (query.validated)       params.set("validated",   query.validated);
  const qs = params.toString();
  return this.request<EventsPage>(`/events${qs ? `?${qs}` : ""}`);
},
```

### 2.3 Updated query key in `queryKeys.ts`

```typescript
events: (query: import("@/lib/api").EventsQuery) => ["events", query] as const,
```

### 2.4 Changes in `recent-events.tsx`

#### New state

```typescript
// Debounced search: UI input fires immediately; query only fires after 300ms idle
const [search,          setSearch]          = useState("");
const [debouncedSearch, setDebouncedSearch] = useState("");
const [validationFilter, setValidationFilter] = useState<"validated"|"contradicted"|"unresolved"|null>(null);
const [offset,          setOffset]          = useState(0);

// Existing state preserved: stageFilter, confFilter, persistenceFilter, ratingFilter, dateFrom, dateTo, sortKey, pinnedIds, selectionMode, etc.
```

Debounce effect:
```typescript
useEffect(() => {
  const t = setTimeout(() => setDebouncedSearch(search), 300);
  return () => clearTimeout(t);
}, [search]);
```

Reset offset to 0 when any filter changes:
```typescript
useEffect(() => { setOffset(0); }, [debouncedSearch, stageFilter, confFilter, persistenceFilter, ratingFilter, dateFrom, dateTo, validationFilter]);
```

#### Query

```typescript
const PAGE_SIZE = 25;

const query: EventsQuery = {
  limit:       PAGE_SIZE,
  offset,
  search:      debouncedSearch || undefined,
  stage:       stageFilter     ?? undefined,
  persistence: persistenceFilter ?? undefined,
  confidence:  confFilter      ?? undefined,
  rating:      ratingFilter    ?? undefined,
  date_from:   dateFrom        || undefined,
  date_to:     dateTo          || undefined,
  validated:   validationFilter ?? undefined,
};

const { data, isLoading: loading, error: queryError, refetch } = useQuery({
  queryKey: qk.events(query),
  queryFn:  () => api.events(query),
  retry:    (failureCount, err) =>
    !(err instanceof ApiError && err.status >= 500) && failureCount < 1,
});

const events = data?.items ?? [];
const total  = data?.total ?? 0;
```

#### Remove client-side filter logic

Remove `filterEvents()`, `ArchiveFilters`, and the `filters` + `filtered` useMemo. Replace with server-returned `events`. Sort and pin remain client-side on the returned page:

```typescript
const displayed = useMemo(
  () => applyPinSort(sortEvents(events, sortKey), pinnedIds),
  [events, sortKey, pinnedIds],
);
```

#### Add "Validated" pills to the filter bar

In the filter section, add a new pill group (same style as Stage / Persist / Conf / Rating):

```tsx
<span className="text-[10px] text-on-surface-variant/70 uppercase tracking-widest mx-1">Validated</span>
{(["validated", "contradicted", "unresolved"] as const).map((v) => (
  <button
    key={v}
    onClick={() => setValidationFilter(validationFilter === v ? null : v)}
    className={cn(
      "rounded-full border px-2 py-0.5 text-[10px] font-medium transition-colors",
      validationFilter === v
        ? "border-primary/40 bg-primary/10 text-primary"
        : "border-border/60 text-on-surface-variant hover:border-border hover:text-foreground",
    )}
  >
    {v}
  </button>
))}
```

#### Pagination controls

Below the event list (above the footer, if any). Only rendered when `total > PAGE_SIZE`:

```tsx
{total > PAGE_SIZE && (
  <div className="flex items-center justify-between px-1 py-2 text-[11px] text-muted-foreground">
    <button
      disabled={offset === 0}
      onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
      className="disabled:opacity-30 hover:text-foreground transition-colors"
    >
      ← Prev
    </button>
    <span className="font-num tabular-nums">
      {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
    </span>
    <button
      disabled={offset + PAGE_SIZE >= total}
      onClick={() => setOffset(offset + PAGE_SIZE)}
      className="disabled:opacity-30 hover:text-foreground transition-colors"
    >
      Next →
    </button>
  </div>
)}
```

#### Result count

Replace `filtered.length/events.length` with server-supplied total:

```tsx
{(debouncedSearch || stageFilter || confFilter || persistenceFilter || ratingFilter || dateFrom || dateTo || validationFilter) && (
  <span className="ml-auto text-[10px] font-num text-muted-foreground/50">
    {total} result{total !== 1 ? "s" : ""}
  </span>
)}
```

---

## Section 3 — Tests

### 3.1 `tests/test_archive_search.py` (new)

```python
class TestQueryEventsFiltered(unittest.TestCase):
    """DB-level filtering via query_events_filtered."""

    def setUp(self):
        import os, tempfile
        os.environ.setdefault("ANTHROPIC_API_KEY", "")
        import db
        self._orig_db = db.DB_FILE
        self._tmp = tempfile.mktemp(suffix=".db")
        db.DB_FILE = self._tmp
        db.init_db()
        from datetime import datetime, timedelta
        def _ts(days_ago: int) -> str:
            return (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="seconds")
        db.save_event({"headline": "alpha-keyword event", "stage": "realized",
            "persistence": "medium", "confidence": "high", "timestamp": _ts(1),
            "beneficiaries": [], "losers": [], "market_tickers": [
                {"direction_tag": "supporting"}, {"direction_tag": "supporting"}
            ]})
        db.save_event({"headline": "event with energy-sector-tag beneficiary", "stage": "developing",
            "persistence": "low", "confidence": "medium", "timestamp": _ts(10),
            "beneficiaries": ["energy-sector-tag"], "losers": [], "market_tickers": []})
        db.save_event({"headline": "old event with loser-tag", "stage": "anticipated",
            "persistence": "high", "confidence": "low", "timestamp": "2025-06-01T12:00:00",
            "beneficiaries": [], "losers": ["loser-tag"], "market_tickers": [
                {"direction_tag": "contradicting"}, {"direction_tag": "contradicting"}
            ]})
        db.save_event({"headline": "alpha-keyword developing event", "stage": "developing",
            "persistence": "medium", "confidence": "high", "timestamp": _ts(5),
            "beneficiaries": [], "losers": [], "market_tickers": [
                {"direction_tag": "supporting"}, {"direction_tag": "contradicting"}
            ]})

    def tearDown(self):
        import db, os
        db.DB_FILE = self._orig_db
        try:
            os.unlink(self._tmp)
        except OSError:
            pass

    def test_search_hits_headline(self):
        rows = query_events_filtered(search="alpha-keyword")
        self.assertEqual(len(rows), 1)
        self.assertIn("alpha-keyword", rows[0]["headline"])

    def test_search_hits_beneficiaries(self):
        rows = query_events_filtered(search="energy-sector-tag")
        self.assertEqual(len(rows), 1)

    def test_search_hits_losers(self):
        rows = query_events_filtered(search="loser-tag")
        self.assertEqual(len(rows), 1)

    def test_stage_filter(self):
        rows = query_events_filtered(stage="realized")
        self.assertTrue(all(r["stage"] == "realized" for r in rows))

    def test_date_from_filter(self):
        rows = query_events_filtered(date_from="2026-01-01")
        self.assertTrue(all(r["timestamp"] >= "2026-01-01" for r in rows))

    def test_date_to_filter(self):
        rows = query_events_filtered(date_to="2025-12-31")
        self.assertTrue(all(r["timestamp"] <= "2025-12-31T23:59:59" for r in rows))

    def test_combined_stage_and_search(self):
        rows = query_events_filtered(stage="developing", search="alpha")
        self.assertTrue(all(r["stage"] == "developing" for r in rows))

    def test_no_filters_returns_all(self):
        rows = query_events_filtered()
        self.assertGreaterEqual(len(rows), 4)


class TestScoreValidation(unittest.TestCase):
    """_score_validation derives status from direction_tags."""

    def _row(self, tags: list[str]) -> dict:
        return {"market_tickers": [{"direction_tag": t} for t in tags]}

    def test_validated_when_supporting_majority(self):
        from routes.events import _score_validation
        self.assertEqual(_score_validation(self._row(["supporting", "supporting", "contradicting"])), "validated")

    def test_contradicted_when_contradicting_majority(self):
        from routes.events import _score_validation
        self.assertEqual(_score_validation(self._row(["contradicting", "contradicting"])), "contradicted")

    def test_contradicted_on_tie(self):
        # contradicting >= supporting → contradicted
        from routes.events import _score_validation
        self.assertEqual(_score_validation(self._row(["supporting", "contradicting"])), "contradicted")

    def test_unresolved_when_no_tickers(self):
        from routes.events import _score_validation
        self.assertEqual(_score_validation({"market_tickers": []}), "unresolved")

    def test_unresolved_when_all_neutral(self):
        from routes.events import _score_validation
        self.assertEqual(_score_validation(self._row(["neutral", "neutral"])), "unresolved")
```

---

## Files to Touch

| File | Change |
|------|--------|
| `db.py` | Add `query_events_filtered(...)` function |
| `routes/events.py` | Add `_score_validation()`, update `GET /events` handler, import `query_events_filtered` |
| `frontend/src/lib/api.ts` | Add `EventsQuery`, `EventsPage` types; update `events()` method; add `validation_status` to `SavedEvent` |
| `frontend/src/lib/queryKeys.ts` | Update `events` key to accept `EventsQuery` |
| `frontend/src/components/pages/recent-events.tsx` | Remove client-side filter logic, wire server params, add validated pills, add pagination |
| `tests/test_archive_search.py` | New test file for `query_events_filtered` and `_score_validation` |

## What is NOT Changing

- All other `/events/*` endpoints (export, delete, review, revisit, etc.)
- DB schema
- `SavedEvent` fields beyond adding `validation_status?`
- Pins (localStorage), bulk export, selection mode, sort (client-side on page)
- News ingestion and analysis pipelines
