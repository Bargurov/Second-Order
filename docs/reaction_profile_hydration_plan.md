# Reaction Profile — Hydration Plan

**Status:** plan — no product-code changes in this document. Concrete enough that a follow-up task can implement step 1 verbatim.
**Companion:** `docs/reaction_profile_design.md` (field contract, edge-case truth table).
**Related:** `docs/magic_number_validation_baseline.md` (the cache row count + per-ticker bar distribution informing this plan).

## 1. Goal

Make the per-ticker block under `event["reaction_profile_v1"]["tickers"][i]` **scorable** instead of `unscorable` for any saved event whose tickers have enough cached close history to anchor against, **without** changing the schema, mutating saved rows, or making any provider call from a read endpoint.

`compute_reaction_profile` already exists and is verified (`reaction_profile.py:182`, `tests/test_reaction_profile.py` — 46 tests). The wiring already calls it (`routes/events.py:_build_reaction_profile_v1`); today every per-ticker call passes `closes=None` and the calculator falls through to its null-safe shape. This plan defines how to feed the calculator real `closes` from data we already have.

## 2. What the composer needs vs what's stored today

| Composer input | Required shape | Where it would come from |
|---|---|---|
| `closes` | `Sequence[float]`, ≥ 2 entries; `closes[0]` = event-date close, `closes[1:]` = subsequent session closes | **Not on saved row.** Live ticker dict carries `return_5d/20d`, normalized 0-1 `spark`, `anchor_date`, `validation_quality` — none of these is a raw close series. |
| `benchmark_closes` | Same shape as `closes`, anchored on the same event date | **Not on saved row.** Per-ticker block stores `relative_return_*` scalars, not the benchmark's raw closes. |
| `stale` | bool | **Already on saved ticker block.** `market_check._check_one_ticker:939-945` sets it when the last bar is older than `_STALE_TICKER_CALENDAR_DAYS=5`. Read it directly. |
| `same_day_fallback` | bool | **Already on saved ticker block.** `market_check.py:914-917` sets it; persisted on the ticker dict. Read it directly. |
| `benchmark_quarantined_horizons` | `set[str] ⊆ {"1d","5d","20d","60d"}` | **Indirect.** The per-ticker `validation_quality` field already encodes benchmark health per design §4.5; horizon-level quarantine is not stored explicitly. See §8 below. |

The single missing input is the **raw close series for the ticker and its benchmark**, anchored on the event date. Everything else the composer wants is already on the saved row.

## 3. Existing data sources audited

### 3.1 `price_cache` table (lives **inside `events.db`**, not the standalone `price_cache.db` file)

Schema (`db.py` init creates it; `price_cache.py:_ensure_table` mirrors the create):

```sql
CREATE TABLE price_cache (
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,           -- ISO YYYY-MM-DD
    close       REAL,                    -- raw close (auto_adjust=0) or adjusted (=1)
    volume      REAL,
    auto_adjust INTEGER NOT NULL,        -- 0 = raw historical fact; 1 = adjusted, may rewrite
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (ticker, date, auto_adjust)
);
CREATE INDEX idx_price_cache_ticker_range ON price_cache (ticker, auto_adjust, date);
```

Live numbers from the local archive (see `docs/magic_number_validation_baseline.md`):

- 10,086 rows, 136 distinct tickers, date range 2025-01-15 → 2026-05-05.
- Per-ticker bar count distribution: min = 7, mean ≈ 74, max = 400 (SPY).
- Tickers with ≥ 61 bars (enough for the 60d horizon): the majority of analyzed names, but not all. Tickers with < 61 bars degrade to per-horizon nulls — exactly the contract the composer already supports.

**Critical property:** `auto_adjust = 0` rows are written by `market_check._fetch_since` (`market_check.py:497`) which deliberately uses `auto_adjust=False` so raw closes are **historical facts that never change**. That is the dataset reaction-profile reads should bind to — no lookahead bias, no silent rewrites on dividends/splits.

### 3.2 In-memory caches (`market_check._cache_get` / TTL maps)

Process-local, lost on restart, only useful within a single request. Do **not** reach for these from a read endpoint. They sit on top of the SQLite layer; if the SQLite cache has the bars, an in-memory miss is irrelevant.

### 3.3 Saved event row

The event row's `market_tickers[i]` block carries `anchor_date`, `stale`, `same_day_fallback`, `validation_quality`, scalar returns, and a normalized sparkline. **No raw closes.** Mathematically wrong to treat the 0-1 sparkline as a close sequence: percent-change math over a normalized sparkline produces meaningless ratios (e.g. `(1.0 / 0.5 − 1) × 100 = 100%`).

### 3.4 `compute_reaction_profile` itself

Already pure, already null-safe on every malformed-input path, already round-trips signs correctly (verified by the existing 46-test suite). No changes proposed here.

## 4. Recommended data source: `price_cache` rows, **read-only**, `auto_adjust=0`

The recommendation:

- Read raw close series (`auto_adjust = 0`) from the `price_cache` table at the event-date anchor + forward window.
- **Never** call `price_cache.fetch_daily_cached(...)` from the detail endpoint — that function will call the provider for any uncached gap (`price_cache.py:535-548`). Read endpoints must use a strictly read-only entry point that does **not** plan or trigger gap fetches.
- Use the same anchor convention `market_check._check_one_ticker` already uses (`market_check.py:932-937`): event-date close = first row whose `date >= event_date` in raw cache.

Why this source over alternatives:

| Alternative | Verdict | Reason |
|---|---|---|
| Reconstruct closes from stored `return_5d/20d` scalars | **Reject.** | The scalars carry only end-points; a series synthesized at indices `[0, 1, 5, 20]` confuses the composer's `closes[N]` semantics, and `_peak_in_window` would scan padded intermediates and emit nonsense. |
| Use the normalized `spark` field | **Reject.** | Sparkline is min-max normalized to 0-1 *for chart rendering*; ratios over it are not percent moves. Mathematically wrong (see §3.3). |
| Trigger `fetch_daily_cached` from the detail endpoint | **Reject.** | It calls the provider on miss. Violates the "no provider calls during read endpoints" rule and adds wall-clock latency proportional to ticker count × cache miss rate. |
| Write a snapshot of raw closes onto `market_tickers[i]` at `market_check` time | **Defer.** | Cleanest long-term but requires a writer change and bloats the persisted row. Step 2 below makes this the second milestone, not the first. |
| Read from the standalone `price_cache.db` file | **Reject.** | The file exists empty; the actual cache is the `price_cache` *table* inside `events.db`. Confirmed by inspection: standalone file has zero tables, events.db `price_cache` has 10,086 rows. |

## 5. Anchor rules (mirroring `market_check._check_one_ticker`)

The hydration helper must use the same anchor logic the existing market-check path uses, so a hydrated reaction profile is bit-comparable to one produced in-process at market-check time. The rules below are not new; they restate the existing module's behaviour for the read-only path.

1. **Anchor candidate:** the event's `event_date` (preferred). Fall back to the date portion of `event["timestamp"]` when `event_date` is missing or unparsable.
2. **Snap forward to the next trading session.** If the anchor date is a Saturday, Sunday, or US holiday, snap to the next available session via `market_check._clamp_to_market_date`. The anchor close is the first cached row at `date >= snapped_anchor`, raw `auto_adjust=0`.
3. **Forward window:** request bars at `date >= snapped_anchor` ordered ascending, limit 62 rows (1 anchor + 61 forward — enough for the 60d horizon). Pass the resulting `[close]` list directly into `compute_reaction_profile`.
4. **Future-dated event:** if `event_date > today_in_cache`, treat it like a stale ticker — return the unscorable shape. The pure calculator already does the right thing on `closes=None`; the hydration helper should not invent forward bars.
5. **Same-day fallback:** if the saved ticker block carries `same_day_fallback=True` (already persisted by `market_check.py:914-917`), pass that flag through to the composer. The composer already handles same-day-fallback semantics (`reaction_profile.py:226-240`): only `return_1d` and `benchmark_relative_return_1d` populate; longer-horizon fields are correctly nulled.
6. **Stale ticker:** if the saved ticker block carries `stale=True` (`market_check.py:939-945`), pass that through too. The composer collapses to its `"stale"` basis (`reaction_profile.py:222-224`).
7. **Anchor not in cache:** if no row at `date >= snapped_anchor` exists in `price_cache` for this ticker, the per-ticker entry is `unscorable` — emit the null-safe shape, do **not** fetch.

## 6. Read-only entry point: `price_cache.read_window_no_fetch`

A new public helper, sibling to `fetch_daily_cached`, scoped explicitly to never call the provider. **This is the only product-code change Step 1 introduces.** Concretely:

```python
# price_cache.py — proposed addition (NOT IMPLEMENTED IN THIS TURN)

def read_window_no_fetch(
    ticker: str,
    *,
    start: str,                  # ISO YYYY-MM-DD; inclusive
    end: Optional[str] = None,   # ISO YYYY-MM-DD; inclusive; defaults to today's last weekday
    auto_adjust: bool = False,
) -> Optional[pd.DataFrame]:
    """Strictly read-only window read from the SQLite price cache.

    Mirrors the cache-read half of ``fetch_daily_cached`` — same SQL,
    same DataFrame shape — but **never** plans or executes a provider
    fetch.  A cache miss returns whatever rows are present (possibly
    none); the caller decides whether the result is sufficient for
    its purposes.

    Safe to call from a request handler: no provider seam, no gap
    backfill, no DB writes.
    """
```

Implementation is a strict subset of the existing `_resolve_range` + `_read_range` flow (`price_cache.py:251` and `:323`). No new SQL, no new index, no schema change.

The hydration composition itself lives in a new module `reaction_profile_hydration.py` (sibling to `reaction_profile.py`) so the pure calculator stays free of any SQLite import:

```python
# reaction_profile_hydration.py — proposed structure (NOT IMPLEMENTED)

def hydrate_per_ticker_profile(
    saved_ticker: dict,
    *,
    event_date: Optional[str],
    benchmark_resolver=None,   # default: market_math.resolve_benchmark
    cache_reader=None,         # default: price_cache.read_window_no_fetch
) -> dict:
    """Compose one per-ticker reaction-profile entry from cache rows.

    Pure over its arguments — both seam parameters are injectable so
    tests can pass canned readers and never hit SQLite.  Returns the
    same dict shape ``compute_reaction_profile`` returns plus a
    ``symbol`` key, exactly matching what
    ``routes/events._build_reaction_profile_v1`` produces today.
    """
```

Wiring change in `routes/events.py:_build_reaction_profile_v1` is then minimal: replace `compute_reaction_profile(None)` with `hydrate_per_ticker_profile(t, event_date=event.get("event_date"))`.

## 7. Avoiding provider calls — guards layered three ways

1. **API surface.** `read_window_no_fetch` does not import `market_data` and does not call any provider seam. The function is a SQL SELECT plus a `_df_from_rows` materialisation. There is no code path inside it that reaches the provider.
2. **Test ban.** The hydration test suite patches `market_data.get_provider`, `yfinance.download`, `yfinance.Ticker`, `api.market_check`, and `api.analyze_event` to raise. Each test asserts the detail endpoint still returns 200 and a fully populated profile from cache rows. This is the same banlist already used by `tests/test_events_archive_detail_consistency.py:TestRelatedEventsRetrieval`.
3. **Wiring guard.** `routes/events.py:_build_reaction_profile_v1` already runs in the detail handler and is read-only over the row dict. The hydrator must keep that contract — no DB writes, no `db.update_*`, no `_cache_set`. Verified by snapshotting `SELECT * FROM events` and `SELECT * FROM price_cache` before/after the request and asserting equality.

## 8. Benchmark + quarantine handling

- **Benchmark resolution.** `market_math.resolve_benchmark(ticker)` returns `(etf, sector)` and is already pure. Use it; do not re-implement.
- **Benchmark closes.** Read with `read_window_no_fetch(etf, start=snapped_anchor, end=…)`. Same anchor as the ticker series (the composer assumes it).
- **Quarantine.** Per design §4.5, the per-ticker block's existing `validation_quality` carries the benchmark health signal. Until horizon-level quarantine is persisted explicitly, the hydrator translates `validation_quality ∈ {"quarantined", "warn", …}` into a coarse policy: when `"quarantined"`, pass `benchmark_quarantined_horizons={"1d","5d","20d","60d"}` so every relative-return field nulls. When `"warn"` or `"ok"`, pass `set()`. This is conservative — if calibration later wants per-horizon quarantine, the persisted shape grows; the hydrator's set construction is one place to touch.

## 9. Migration-free first step (Step 1)

**Step 1 is migration-free.** Concretely, ship the following without any DB change or row mutation:

1. Add `price_cache.read_window_no_fetch` (new public function, ~30 lines, mirrors existing read half).
2. Add `reaction_profile_hydration.py` (new module, ~80 lines, pure-with-injected-seams composition).
3. Replace the per-ticker call in `routes/events.py:_build_reaction_profile_v1` from `compute_reaction_profile(None)` to `hydrate_per_ticker_profile(t, event_date=…)`.
4. Tests (see §11).

After Step 1, every saved event whose tickers have ≥ 2 raw cached bars at `date >= event_date` produces a real reaction profile on the detail response. The rest stay `unscorable` exactly as today — that's the same contract `routes/events._build_reaction_profile_v1` already documents.

## 10. What must be persisted or cached for later steps

Step 1 does not require persistence. The following items become attractive once Step 1's hit rate is measured:

| Step | Persistence | Why it would help |
|---|---|---|
| 2 | Snapshot raw closes onto `market_tickers[i]` at `market_check` time | Removes the SQL roundtrip on detail; survives even if `price_cache` rows are pruned for storage. Requires a writer change in `market_check._check_one_ticker` to attach `closes_window: list[float]` (≤ 62 floats) at the time of the original fetch. |
| 3 | Cache the *composed* `reaction_profile` JSON next to `last_market_check_at` | Skips the per-ticker computation on every detail read. Trades disk for latency; only worth it if §11 measurements show the composer is hot. |
| 4 | Persist horizon-level benchmark quarantine | Lets `benchmark_quarantined_horizons` carry exact per-horizon nulls instead of the coarse all-or-nothing rule §8 lands on. Needs a one-line addition to the per-ticker dict at write time. |

None of these is a schema change in the strict sense — `market_tickers` is a free-shape JSON list. They are persisted-payload extensions, deployable without an `ALTER TABLE`.

## 11. Tests required before implementation

Each block below names a new test file or extends an existing one. Fixtures are dict literals + temp DB rows; no provider seam, no network, no LLM. Tests are written and watched fail BEFORE the implementation lands (TDD; cf. `superpowers:test-driven-development`).

### 11.1 `tests/test_price_cache_read_window_no_fetch.py` (new)

Pure pinning tests for the new read-only entry point:

- Cache hit at exact start/end → DataFrame with the requested rows.
- Partial hit (cache covers only the suffix of the request) → DataFrame with whatever's there; **no provider call** (assert via `get_provider` patch raising).
- Empty cache → empty DataFrame, no exception, no provider call.
- Weekend/holiday `start` parameter → snaps to next weekday before SQL query (mirrors `_resolve_range`).
- `auto_adjust=False` and `auto_adjust=True` route to separate rowsets (the schema's PK includes the flag).
- DB-unreachable (point `db.DB_FILE` at a missing file) → returns `None`, never raises.

### 11.2 `tests/test_reaction_profile_hydration.py` (new)

Composition tests, all using injected `cache_reader` so they run without touching SQLite:

- **Happy path (forward-anchored):** ticker has 65 bars in cache starting at the anchor; profile populates `return_1d/5d/20d/60d`, `peak_move_*`, `time_to_peak_*`, `fade_or_hold_label_*`, `reaction_profile_basis = "forward_anchored"`. Hand-computed expected values, not regex.
- **Anchor not in cache:** cache returns 0 rows at `date >= event_date` → `reaction_profile_basis = "unscorable"`, every horizon null.
- **Insufficient bars (only 4 forward bars):** `return_5d` populates from `closes[5]`-style index but `peak_move_5d` requires the full 5-bar window — null; `peak_move_20d` and `peak_move_60d` null; `reaction_profile_basis = "forward_anchored"`. (Pinning the design's "independent nullability per horizon" rule.)
- **Stale ticker:** `saved_ticker["stale"] = True` → composer is invoked with `stale=True`, basis = `"stale"`, every forward field null even when cache rows are present.
- **Same-day fallback:** `saved_ticker["same_day_fallback"] = True` → basis = `"same_day_fallback"`; only `return_1d` and `benchmark_relative_return_1d` populate.
- **Benchmark quarantined:** `saved_ticker["validation_quality"] = "quarantined"` → all `benchmark_relative_return_*` are null, ticker's own `return_*` still populate.
- **Future-dated event:** `event_date` after the latest cached bar → unscorable shape; no exception.
- **Determinism:** same inputs → byte-equal output across two invocations; no clock reads inside the hydrator (assert by patching `datetime.now` to raise — composer must still produce results from cache bars).

### 11.3 Wiring tests — extend `tests/test_events_reaction_profile_wiring.py`

The existing 14 tests already pin the unscorable-block contract. Step 1 should keep all 14 passing, and add:

- **`available = True` on a hydrated ticker:** seed the temp DB with synthetic `price_cache` rows at the event date and beyond; assert `body["reaction_profile_v1"]["available"]` flips to `True` and the per-ticker entry has non-null `return_5d`.
- **`reason` carries the "available rows" message** when at least one ticker hydrated, distinct from the `"raw close series not stored…"` reason today.
- **No DB writes** — re-run the existing `_snapshot_events_table` + new `_snapshot_price_cache_table` snapshots before/after; assert equality.
- **No provider calls** — extend the existing patch list. The hydrator must not import `market_data` directly; the test asserts so.

### 11.4 Performance smoke (optional but recommended)

Time the detail endpoint with 50 tickers each carrying 100 cache rows. Assert wall-clock < 200 ms locally so the SQL roundtrips per ticker do not regress detail-page latency. This is a guardrail, not a correctness check.

## 12. Open questions / deferred decisions

- **Pre-warming.** Step 1 only hydrates events whose `price_cache` window already exists. A backfill pass (akin to `scripts/rebuild_archive.py`) would warm the cache for every saved event in one batch. Out of scope here; should ride on top of an existing `market_check.refresh_event` invocation rather than a new fetch path.
- **`reaction_profile_basis` extension.** When the cache has bars but the anchor itself is missing (post-event close not yet recorded), should that surface as `"unscorable"` or as a new `"awaiting_anchor"` value? Open until the wiring test sees the case in real archive data.
- **60d horizon coverage.** The local archive shows ~50% of tickers have ≥ 61 bars today; the rest will report `peak_move_60d=None` until enough trading days pass. Consumers must not interpret null as "the move was zero". The design contract already says this; flagging here so reviewers don't ask for a different fallback.
- **Concurrency.** The detail endpoint serialises hydration per ticker. If profiling shows it matters, batch the SQL into one `WHERE ticker IN (…)` query. Defer until a measurement says it's worth the loss in code clarity.

## 13. What this plan deliberately avoids

- No schema migrations. No `ALTER TABLE`. The `market_tickers` payload extension in §10 is JSON-blob shape only.
- No provider calls from any read path. `read_window_no_fetch` is named so the constraint is grep-able; the wiring guard repeats the constraint in a banlist test.
- No mutation of saved rows from the detail endpoint. `_build_reaction_profile_v1` stays read-only over the row dict; hydration only reads the price cache.
- No new field-vocabulary in `reaction_profile_v1`. The existing `{available, reason, tickers, n_tickers}` shape stays exactly the same; consumers binding to it today keep working unchanged.

## 14. Verification

Doc-only commit. `git diff --check` is the only mechanical verification expected this turn; clean output is the success signal.
