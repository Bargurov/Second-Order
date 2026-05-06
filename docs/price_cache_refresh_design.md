# Zero-LLM Price-Cache Refresh — Safety-First Design

**Status:** design — no product code in this turn.  This document
specifies a CLI-only refresh path that warms `price_cache` rows for
already-analyzed archived events, so their `market_tickers` blocks
become reaction-profile-scorable without any new LLM call, any
`analyze_event` invocation, or any auto-backfill paid execution.

**Scope of this turn:** documentation only.  No `api.py`, no
`routes/`, no `scripts/`, no `tests/` change.  Everything in §11
must be true *before* the implementation lands.

**Companion modules:** `price_cache.py` (the read-through cache —
`fetch_daily_cached` is the only seam that reaches the provider);
`reaction_profile.py` + `routes/events.py:_build_reaction_profile_v1`
(the consumers that flip from `unscorable` to `forward_anchored`
when the cache is warm); `archive_rebuild.py` +
`scripts/rebuild_archive.py` (the existing CLI-only,
no-LLM, dry-run-by-default rebuild path whose safety model this
design mirrors verbatim); `auto_backfill_runner.py` +
`scripts/auto_backfill_dry_run.py` (the planner / runner / CLI
shape this design mirrors for the dry-run plumbing).

**Companion docs:** `docs/reaction_profile_design.md`,
`docs/reaction_profile_hydration_plan.md`,
`docs/auto_backfill_scheduler_design.md` (the safety-first design
template), `docs/local_operations_runbook.md` (operator commands).

---

## 1. Why this exists

Reaction profiles need cached daily closes around each event's
`event_date` to flip a per-ticker block from `unscorable` to
`forward_anchored`.  Today the cache fills opportunistically
(`market_check._fetch` / `ticker_chart` on a page hit), so the
ticker history coverage is uneven — events analysed before a given
ticker was ever queried still report `reaction_profile_basis="unscorable"`
even though the underlying close history is now fetchable for free.

A purpose-built refresh path would:

1. Walk archived events that already have `market_tickers` and an
   `event_date`.
2. Decide which ticker × window pairs need cache rows.
3. Fetch those rows through the existing
   `price_cache.fetch_daily_cached` seam (no LLM, no `analyze_event`,
   no `auto_backfill_runner.execute_paid_candidate`).
4. Re-render the reaction-profile diagnostic so operators see the
   uplift in `events_with_profile_input_ready` /
   `tickers_with_scalar_returns`.

Critically, this is a **read-side warm-up of an existing cache** —
no archive row is mutated, no overlay is rewritten, no analysis is
re-run.  The same pure-math composers that already serve
`/events/{event_id}/reaction-profile` consume the warmed cache the
next time the page is loaded.

---

## 2. Non-goals (explicit)

The refresh path **must not**:

* Call any LLM.  No `analyze_event`, no `analyze_event.*`, no
  `_call_llm_provider` / `_call_anthropic` / `_call_openai`.  These
  seams are gated under `scripts/no_paid_smoke.py::_DANGEROUS_SEAMS`
  and the new tests must keep them there.
* Touch `auto_backfill_runner.execute_paid_candidate`.  That stub
  raises `NotImplementedError` and is the canonical paid-execution
  seam; this refresh is independent and never reaches it.
* Mutate `events` rows.  Specifically: no `db.save_event`, no
  `db.update_review`, no `update_event_overlays`, no
  `append_revisit_snapshot`.  Only `price_cache` rows are written
  (and only via the established `fetch_daily_cached` upsert path).
* Be triggered from a GET / page-load handler.  The `routes/`
  surface remains read-only with respect to provider calls except
  for the existing yfinance allow-list documented in
  `tests/test_no_paid_get_routes.py`.  Opening a chart, hitting
  `/diagnostics/*`, or browsing the archive must not trigger
  refresh fetches.
* Be wired into the FastAPI lifespan.  No `app.state.*`
  publication, no APScheduler job, no background thread.  This
  invariant matches the `auto_backfill_scheduler` "off by default"
  posture and keeps the test process single-threaded.
* Run automatically.  There is no env gate that turns it on; it is
  a CLI invocation only, with a confirmation flag for the write
  mode (see §6).

The non-goals above are pinned as test invariants in §10.

---

## 3. Inputs

A single refresh run reads:

* `events` rows where `market_tickers` is non-empty and
  `event_date` is set.  Empty `market_tickers` events are filtered
  out — they have no per-ticker block to score.
* The existing `price_cache` table — used to compute *what is
  already covered* before any provider call.
* The active `MarketDataProvider` (yfinance by default) — used
  only via `price_cache.fetch_daily_cached`, which already gates
  the provider on cache miss.  The provider seam is documented and
  allow-listed; no new seam is introduced.

It writes only to `price_cache` and only via the existing upsert
inside `fetch_daily_cached`.  No schema changes, no migrations.

---

## 4. Window contract

For each (event, ticker) pair the refresh decides which dates need
to be in the cache to make the reaction profile scorable.  The
window is anchored on `event_date` (UTC date, parsed with the same
helper used by `archive_rebuild`).

* **Pre-window:** 5 business days *before* `event_date`.  Provides
  the same baseline that `compute_reaction_profile` reads when
  computing pre-event drift / median.
* **Post-window:** 20 business days *after* `event_date`.  Covers
  the longest scorable horizon (`return_20d`) and gives
  `same_day_fallback` a reachable post bar at the 1-day and 5-day
  horizons too.
* **Auto-adjust flag:** `True` (matches the rest of the
  reaction-profile pipeline; raw rows can be added later under a
  separate flag if a future profile field needs them).

If `event_date` is in the future or cannot be parsed, the (event,
ticker) pair is dropped with reason `invalid_event_date` (see §5).

The window contract is intentionally narrow — it does **not** try
to backfill arbitrary history.  Reaction profile scoring needs at
most ~6 weeks of business-day closes per event; the refresh stays
inside that envelope so a cap-busting run cannot accidentally
become a mass historical pull.

---

## 5. Dry-run planner

The planner is the load-bearing safety surface.  It is a pure
function over event rows + the current `price_cache` state, and
returns the work plan **without** invoking the provider.  Mirrors
`auto_backfill_runner.run_auto_backfill_dry_run` in shape so tests
can patch a single seam.

### 5.1 Selection

Iterate the events that satisfy the §3 input filter, in
deterministic order (`ORDER BY event_date DESC, id DESC`), and for
each event:

* Drop tickers with no `symbol` field, with whitespace-only
  symbols, or that fail the existing `_clean_fetch_symbol`
  normaliser → reason `invalid_ticker`.
* Drop tickers whose recent `fetch_daily_cached` history shows
  zero rows for *any* prior cache window of comparable size →
  reason `stale_ticker`.  This is the same staleness gate
  `reaction_profile_basis="stale"` uses today; the planner reads
  the existing `_LIVE_REFRESH_DAYS`-aware probe and re-uses its
  classifier so refresh and read agree.
* Drop tickers already fully covered (no missing dates in the
  pre/post window) → reason `already_covered`.
* For the remaining tickers, compute the **missing date set** by
  diffing the §4 window against the cache's
  `(ticker, date, auto_adjust=1)` rows.  Each missing run of
  consecutive dates becomes one **fetch interval**.

### 5.2 Provider-call estimate

`fetch_daily_cached` issues one provider call per *contiguous*
missing interval per ticker.  The planner reports:

* `intervals` — total contiguous missing intervals.
* `business_days` — total missing business days.
* `unique_tickers` — distinct tickers with at least one interval.
* `provider_calls_estimate = intervals` — the conservative upper
  bound (the cache's leading/trailing logic may merge intervals
  internally; the estimate is `>=` what the run will actually
  issue).

### 5.3 Caps

Hard caps applied in this order:

1. `--max-events` (default `100`) — sliced after the §5.1 filter.
2. `--max-tickers-per-event` (default `8`) — preserves the
   existing per-event ticker spread.
3. `--max-provider-calls` (default `50`) — the run-level ceiling
   on `provider_calls_estimate`.  When the cap is exceeded, the
   planner truncates by *event* (not by ticker), so a single
   event's window stays internally consistent.  The truncated
   tail is reported under `skipped_for_cap` with the originating
   event ids — the operator can re-run later with a higher cap
   or a tighter slice.

Defaults are deliberately conservative.  Tightening them is a
low-risk change; loosening them requires a doc + test update.

### 5.4 Output shape (dry-run JSON)

```json
{
  "ok": true,
  "now": "<iso8601>",
  "selection": {
    "considered_events":         123,
    "events_with_market_tickers":123,
    "events_in_window":           87,
    "events_planned":             64,
    "skipped_for_cap":             9,
    "skip_counts": {
      "invalid_event_date": 0,
      "invalid_ticker":     2,
      "stale_ticker":       3,
      "already_covered":   31
    }
  },
  "estimate": {
    "intervals":             142,
    "business_days":        1840,
    "unique_tickers":         48,
    "provider_calls_estimate":50
  },
  "caps": {
    "max_events":              100,
    "max_tickers_per_event":     8,
    "max_provider_calls":       50,
    "applied":                true
  },
  "events": [
    {
      "event_id":    123,
      "event_date": "2026-04-12",
      "tickers":   [
        {
          "symbol": "AAPL",
          "intervals": 1,
          "business_days": 26,
          "covered_business_days": 0
        }
      ]
    }
  ],
  "decision_reason": "planned" | "no_work" | "cap_exhausted"
}
```

`spent_calls` is **not** in the dry-run shape — this is not the
auto-backfill paid-call ledger.  The estimate is reported in
provider-call units; the write mode (§6) reports actual issued
calls separately.

---

## 6. Write mode — explicit CLI only

Refresh execution lives behind a CLI flag, never a route, never
an env-gated background job.

### 6.1 Invocation contract

```powershell
# Dry-run: no provider calls, no DB writes (default).
python scripts/refresh_price_cache.py

# Narrower slice.
python scripts/refresh_price_cache.py --since-days 60 --max-events 25

# Write mode — refresh price_cache rows.  Both flags required.
python scripts/refresh_price_cache.py --write --confirm

# JSON for tooling / CI.
python scripts/refresh_price_cache.py --json
python scripts/refresh_price_cache.py --write --confirm --json
```

* `--write` *and* `--confirm` are **both** required to issue any
  provider call.  Either flag alone short-circuits with
  `decision_reason="write_requires_confirm"` and exit code `0`
  (it is a planning report, not an error).  This is a strict
  upgrade over `rebuild_archive.py`'s single-flag write gate —
  the second flag prevents an operator from accidentally moving
  from a dry-run habit into a write-by-default habit.
* No interactive prompt.  CI must work; `--confirm` is the
  machine-friendly equivalent.
* No environment variable enables write mode.  An accidentally
  exported `REFRESH_PRICE_CACHE_WRITE=1` does *nothing*.  This
  matches the `ENABLE_AUTO_BACKFILL` / `ENABLE_PAID_ANALYSIS`
  posture: env vars can disable but not single-handedly enable
  cost.
* The CLI never starts FastAPI's lifespan.  It does not call
  `init_db()` indirectly via the app — it ensures the DB is
  reachable through `db._db_ready` checks and `_ensure_table()`
  the same way `tools/price_cache_validation.py` does.
* Exit code: `0` on dry-run, `0` on a successful `--write
  --confirm` with zero fetch errors, `1` only when `--write` ran
  and at least one ticker errored.  Mirrors `rebuild_archive.py`.

### 6.2 Backup / preflight recommendation

The refresh writes only to `price_cache` (no archive rows
mutated), so a full DB backup is not required.  However, the
runbook addition (see §9) **must** recommend:

1. **Snapshot the cache before a large run.**
   ```powershell
   python scripts/backup_archive.py
   ```
   The existing backup helper covers `events.db` including the
   `price_cache` table.  A snapshot lets an operator roll back if
   a future provider-side data correction lands bad rows.
2. **Run the dry-run first** and review:
   * `provider_calls_estimate` is below the cap they plan to set.
   * `skip_counts.stale_ticker` is small — a spike means the
     active provider's symbol set drifted and the run would
     mostly fetch nothing useful.
   * `selection.events_planned` matches the slice they expected
     (`--since-days`, `--family`, `--limit`).
3. **Run the no-paid smoke after a `--write`** to confirm the GET
   surface still has `scheduler.scheduler_started=false` and
   `ledger.used=0`:
   ```powershell
   python scripts/no_paid_smoke.py --json
   ```
4. **Re-render reaction-profile diagnostics** to confirm uplift
   (see §7.3).

These are recommendations, not gates — the CLI itself does not
shell out to backup/smoke/diag.  Composing the operator workflow
in the runbook keeps the script single-purpose.

---

## 7. Diagnostics

Three new read-only views surface the cache's coverage shape so
operators can target a refresh and verify its uplift.  All three
must be implementable as `routes/diagnostics.py` GET endpoints
without invoking the refresh path itself — they read `price_cache`
+ `events` rows and aggregate.

### 7.1 Coverage by ticker — `GET /diagnostics/price-cache-by-ticker`

Per ticker, across all archived events that reference it:

```json
{
  "available": true,
  "as_of":            "<iso8601>",
  "auto_adjust":      true,
  "tickers": [
    {
      "ticker":              "AAPL",
      "events_referencing":  37,
      "events_fully_covered":29,
      "events_partial":       6,
      "events_unscorable":    2,
      "expected_business_days":  962,
      "cached_business_days":   908,
      "coverage_ratio":           0.94
    }
  ],
  "summary": {
    "tickers":               142,
    "fully_covered_tickers":  91,
    "median_coverage_ratio":  0.92
  }
}
```

`events_unscorable` is the lever the refresh moves: each pair of
event × ticker that the planner schedules will, on a successful
write run, increment `events_fully_covered` and decrement
`events_unscorable`.

### 7.2 Coverage by event age — `GET /diagnostics/price-cache-by-age`

Per coarse age bucket (mirrors the existing `archive_drift`
buckets so the two diagnostics line up):

| Bucket          | Span                        |
|-----------------|-----------------------------|
| `last_7d`       | 0–7 days                    |
| `last_30d`      | 8–30 days                   |
| `last_90d`      | 31–90 days                  |
| `last_year`     | 91–365 days                 |
| `older`         | > 365 days                  |

```json
{
  "available": true,
  "as_of":     "<iso8601>",
  "buckets": [
    {
      "name":               "last_30d",
      "events":             54,
      "ticker_pairs":      261,
      "fully_covered_pairs":248,
      "partial_pairs":       9,
      "unscorable_pairs":    4,
      "coverage_ratio":      0.96
    }
  ]
}
```

The age view is the default operator entry point: "where are the
gaps?"  Older events are the dominant unscorable slice today
because the cache started filling later than the archive did.

### 7.3 Reaction-profile scorable count — extends existing
`GET /diagnostics/reaction-profile-stats`

The endpoint already returns `events_with_profile_input_ready`,
`events_unscorable`, `tickers_with_scalar_returns`,
`profile_basis_counts`, and `latest_event_timestamp`.  This design
adds **no new field**; the *uplift* signal is the diff of two
snapshots taken before and after a `--write` run.  The runbook
records the diff as the success criterion:

```text
BEFORE refresh:
  events_with_profile_input_ready = 612
  events_unscorable               = 211
  tickers_with_scalar_returns     = 4 870

AFTER refresh:
  events_with_profile_input_ready = 793   (+181)
  events_unscorable               =  30   (-181)
  tickers_with_scalar_returns     = 5 412 (+542)
```

Tying the success measurement to an existing endpoint keeps the
write surface narrow (no new fields, no new aggregator) and
guarantees the diagnostic is already covered by the
`scripts/no_paid_smoke.py` invariant (`scheduler_started=false`,
`ledger.used=0` — neither moves).

---

## 8. Module shape

The implementation lands as three new files plus one CLI; nothing
in `api.py`, `routes/`, `auto_backfill_*.py`, or `analyze_event.py`
changes.

| New file                                        | Role                                                                                      |
|-------------------------------------------------|-------------------------------------------------------------------------------------------|
| `price_cache_refresh.py`                        | Pure planner (`plan_refresh`) + executor (`execute_refresh`) — no FastAPI, no scheduler.  |
| `scripts/refresh_price_cache.py`                | Thin CLI wrapper — argument parsing → planner → optional executor → report rendering.    |
| `tests/test_price_cache_refresh.py`             | Planner / executor unit tests + the §10 invariants.                                       |

`price_cache_refresh.py` deliberately mirrors
`auto_backfill_runner.py` so the existing review patterns apply:

* `RefreshConfig` dataclass — caps, since-window, auto_adjust flag.
* `RefreshPlan` dataclass — the §5.4 shape.
* `RefreshResult` dataclass — issued provider calls, errors per
  ticker, durations.
* `plan_refresh(events, *, config, now=None) -> RefreshPlan` —
  pure (no IO).  `now` is injectable for deterministic tests.
* `execute_refresh(plan, *, config, fetch=None) -> RefreshResult`
  — issues fetches.  `fetch` is the seam tests patch with a
  `MagicMock`; defaults to `price_cache.fetch_daily_cached`.

The CLI imports `price_cache_refresh` lazily so a `--help`
invocation does not pay the FastAPI / `api` import cost.  This
mirrors `scripts/auto_backfill_dry_run.py`.

---

## 9. Runbook addition

`docs/local_operations_runbook.md` will gain a "Price-cache
refresh" section after the existing "Auto-Backfill Foundation
Checks" block.  The section:

* Lists the dry-run command first, with expected fields.
* Shows the snapshot-then-write-then-verify cycle from §6.2.
* Records the success criterion (the §7.3 diff).
* Reminds the operator that `--write` requires `--confirm`.
* Links back to `docs/reaction_profile_design.md` so the
  semantics behind the uplift are one click away.

The runbook is the authoritative operator-facing surface; this
design doc is the engineering contract.

---

## 10. Tests required *before* implementation

Every claim in this document must be pinned by a test before any
of the §8 modules is merged.  Directory: `tests/`.

### 10.1 Pure planner — `tests/test_price_cache_refresh_planner.py`

Mirrors `tests/test_auto_backfill_planner.py`'s structure.

| Test                                                               | What it asserts                                                                                  |
|--------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| `test_empty_events_yields_empty_plan`                              | No events → `events_planned=0`, `provider_calls_estimate=0`.                                     |
| `test_event_without_market_tickers_is_dropped`                     | `events_with_market_tickers` count is correct; the pair never appears in `events`.               |
| `test_invalid_event_date_drops_pair_with_reason`                   | `skip_counts.invalid_event_date` increments; no fetch interval for that pair.                    |
| `test_invalid_ticker_drops_pair_with_reason`                       | Whitespace / empty / `_clean_fetch_symbol`-failing symbols increment `invalid_ticker`.           |
| `test_already_covered_event_drops_pair_with_reason`                | Pre-loaded cache covering the §4 window → `already_covered`; intervals=0.                        |
| `test_partial_coverage_yields_minimal_intervals`                   | A single missing leading or trailing run produces exactly one interval.                          |
| `test_split_coverage_yields_two_intervals`                         | A gap in the middle of the window produces two intervals.                                        |
| `test_max_events_cap_truncates_by_event_order`                     | `--max-events=N` keeps the first N by `(event_date desc, id desc)`; rest land in `skipped_for_cap`. |
| `test_max_tickers_per_event_cap_truncates_per_event`               | Per-event ticker cap applied independently.                                                      |
| `test_max_provider_calls_cap_truncates_by_event`                   | Whole-event truncation when the running estimate would exceed the cap.                           |
| `test_plan_decision_reason_branches`                               | `planned` vs `no_work` vs `cap_exhausted`.                                                       |
| `test_plan_is_pure_no_provider_call`                               | Patched `price_cache.fetch_daily_cached` raiser is **never** called by `plan_refresh`.           |
| `test_plan_is_deterministic`                                       | Two runs over the same fixture yield byte-equal plans.                                           |

### 10.2 Executor — `tests/test_price_cache_refresh_executor.py`

| Test                                                                    | What it asserts                                                                                       |
|-------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------|
| `test_executor_calls_fetch_once_per_interval`                           | Fetch seam called exactly once per planned `(ticker, interval)`.                                      |
| `test_executor_records_per_ticker_errors`                               | Fetch raise → recorded in `RefreshResult.errors[ticker]`; the run continues.                          |
| `test_executor_does_not_call_fetch_when_plan_empty`                     | `RefreshPlan(events=[])` → 0 fetches.                                                                 |
| `test_executor_does_not_invoke_paid_seams`                              | Patches `api.analyze_event`, `api.market_check`, `auto_backfill_runner.execute_paid_candidate`, `yfinance.download`, `yfinance.Ticker` to raise; the executor must complete using only the injected fetch seam. |
| `test_executor_does_not_mutate_events_table`                            | `db.save_event` / `db.update_review` / `db.append_revisit_snapshot` patched to raise; run completes.  |
| `test_executor_writes_only_via_fetch_daily_cached`                      | Only the injected fetch seam is invoked; no other DB writer is touched.                               |

### 10.3 CLI — `tests/test_refresh_price_cache_cli.py`

| Test                                                                | What it asserts                                                                                  |
|---------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| `test_help_exits_cleanly`                                           | `--help` exits 0; argparse description includes "dry-run".                                       |
| `test_default_invocation_is_dry_run`                                | No flags → planner runs, executor never called, exit 0.                                          |
| `test_write_without_confirm_short_circuits`                         | `--write` alone → `decision_reason="write_requires_confirm"`, executor never called, exit 0.     |
| `test_confirm_without_write_short_circuits`                         | `--confirm` alone → same shape, executor never called.                                           |
| `test_write_and_confirm_invokes_executor`                           | `--write --confirm` → executor called once with the planned `RefreshPlan`.                       |
| `test_env_var_cannot_enable_write`                                  | `REFRESH_PRICE_CACHE_WRITE=1` set → still dry-run.                                               |
| `test_json_output_round_trips`                                      | `--json` produces parseable JSON with the §5.4 keys.                                             |
| `test_cli_does_not_import_fastapi_until_needed`                     | Importing the CLI module never imports `api` / `fastapi` directly.                               |

### 10.4 No-paid invariants — `tests/test_price_cache_refresh_no_paid.py`

These are the load-bearing safety tests; matches the
`scripts/no_paid_smoke.py` and `tests/test_no_paid_get_routes.py`
patterns.

| Test                                                                                | What it asserts                                                                                                                                         |
|-------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------|
| `test_no_llm_seam_invoked_under_dry_run`                                            | `analyze_event`, `_call_anthropic`, `_call_openai`, `_call_llm_provider` patched to raise; planner runs; nothing raises.                                |
| `test_no_llm_seam_invoked_under_write_mode`                                         | Same, with `--write --confirm`.                                                                                                                         |
| `test_auto_backfill_paid_seam_never_invoked`                                        | `auto_backfill_runner.execute_paid_candidate` patched to raise; both modes complete without raising.                                                    |
| `test_get_routes_do_not_import_or_call_refresh`                                     | After `with TestClient(api.app) as client:` and a hit on every documented GET, neither `price_cache_refresh.plan_refresh` nor `execute_refresh` is invoked. |
| `test_no_apscheduler_thread_spawned_by_cli`                                         | Snapshot `threading.enumerate()` before and after the CLI; no new APScheduler-named thread.                                                             |
| `test_lifespan_does_not_attach_refresh_scheduler`                                   | `with TestClient(api.app) as client:` boots the lifespan; `getattr(app.state, "price_cache_refresh_scheduler", None) is None`.                          |
| `test_module_import_does_not_spawn_threads`                                         | Importing `price_cache_refresh` and `scripts.refresh_price_cache` does not spawn threads (mirrors the existing `_THREADS_AFTER_API_IMPORT` invariant).  |

### 10.5 Diagnostics — `tests/test_price_cache_diagnostics.py`

| Test                                                                | What it asserts                                                                                  |
|---------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| `test_by_ticker_endpoint_shape`                                     | Shape matches §7.1; `auto_adjust=true` is the default.                                           |
| `test_by_age_buckets_match_archive_drift`                           | Bucket names + spans line up with `archive_drift`'s buckets.                                     |
| `test_endpoints_are_zero_cost_under_no_paid_smoke`                  | Both endpoints land in `scripts/no_paid_smoke.py::ENDPOINTS` and pass the existing invariants.   |
| `test_reaction_profile_stats_uplift_signal`                         | After seeding cache rows for a previously-unscorable event, `events_with_profile_input_ready` increases by exactly 1; `events_unscorable` decreases by 1. |

### 10.6 Allow-list extension

`tests/test_no_paid_get_routes.py::_KNOWN_PAID_SEAM_CALLERS` gains
two entries with rationale, mirroring the existing yfinance allow
list, so the new diagnostics endpoints don't accidentally start
fetching:

```python
("/diagnostics/price-cache-by-ticker", "yfinance.download"): (
    "must be zero — pure SQLite aggregator over price_cache rows"
),
("/diagnostics/price-cache-by-age",    "yfinance.download"): (
    "must be zero — pure SQLite aggregator over price_cache rows"
),
```

These entries are inverted relative to the cache-warming routes:
they are listed as **expected zero-call sites** so a regression
that turns the diagnostics into provider callers fails the
existing invariant.  (Implementation: the test's allow-list test
asserts each listed pair is on the per-route tally; we will add a
sibling `_KNOWN_ZERO_CALL_PAIRS` map if the inversion proves
awkward.  This is the only minor schema decision deferred to
implementation time.)

---

## 11. Pre-merge invariants

Before the implementation lands, the repo must already satisfy:

1. `python -m unittest tests.test_price_cache_refresh_planner
   tests.test_price_cache_refresh_executor
   tests.test_refresh_price_cache_cli
   tests.test_price_cache_refresh_no_paid
   tests.test_price_cache_diagnostics` — all green, hermetic, no
   network.
2. `python scripts/no_paid_smoke.py --json` — still 14/14 PASS;
   `scheduler.scheduler_started=false`, `ledger.used=0` unchanged
   under the new module's import side effects.
3. `python -m unittest tests.test_no_paid_get_routes` — still
   green standalone *and* under the combined order pinned in
   `docs/auto_backfill_lifespan_smoke_audit.md` §"Commands used".
4. `git grep "price_cache_refresh" api.py routes/` — empty.  The
   refresh path must not be wired into FastAPI.
5. `git grep "execute_paid_candidate\|analyze_event"
   price_cache_refresh.py scripts/refresh_price_cache.py` —
   empty.  The refresh path must not import the LLM /
   paid-execution seams.
6. `python scripts/auto_backfill_scheduler_smoke.py --json` —
   still 8/8 PASS.  The auto-backfill scheduler smoke is
   independent of this work; a regression here would mean the new
   module pulled the auto-backfill machinery into its import
   graph.
7. `tests/test_no_paid_get_routes.py` enumeration test continues
   to pass under the §10.6 allow-list extension; the strict
   forbidden seams (`api.analyze_event`, `api.market_check`,
   `auto_backfill_runner.execute_paid_candidate`) still report
   zero calls across every GET.

§11 items 1, 2, 3, and 6 are commands that already work today;
the implementation is allowed to land only when items 4 and 5
also produce empty output and item 7 is still green under the
extended allow-list.

---

## 12. Out of scope (recorded so we don't drift)

* Backfilling raw (`auto_adjust=False`) bars.  The reaction-profile
  pipeline reads adjusted closes only; raw bars are a separate
  refresh contract.
* Refreshing `events.market_tickers` themselves (e.g., adding new
  tickers post-hoc).  That is a re-analysis decision and belongs
  on the paid-backfill path, gated behind
  `ENABLE_PAID_ANALYSIS` + `ENABLE_AUTO_BACKFILL`.
* Wiring a scheduler.  If recurring refresh is ever needed, it
  composes on top of this CLI via cron / Task Scheduler — the
  module does not grow an APScheduler dependency.
* Mutating overlays (`update_event_overlays`).  That is the
  `archive_rebuild.py` contract; this design is strictly
  cache-warming.
