# Auto-Backfill Scheduler — Safety-First Design

**Status:** design — no product code in this turn.  This document
specifies a disabled-by-default APScheduler-style background job that
periodically asks the existing paid-backfill pipeline to analyse the
top-ranked unanalysed candidate(s).  The scheduler is the cost-bearing
seam.  Its safety model is deliberately conservative: a single
misconfiguration must default to "no spend, no surprise."

**Scope of this turn:** documentation only.  No `api.py`, no `routes/`,
no `tests/` change.  Everything in §11 must be true *before* the
implementation lands.

**Companion modules:** `routes/movers.py` (existing paid-backfill
endpoints — `_paid_analysis_enabled`, `_score_cluster_for_preview`,
`_compute_major_skipped`), `headline_registry` (state machine),
`auto_revisit.py` / `market_snapshots.py` (precedent for env-gated
background loops in `api._lifespan`).

**Dependency choice — APScheduler over bare thread.**  Existing
background loops in this app use bare `threading.Thread` +
`time.sleep(interval)`.  This design *diverges* from that pattern
and adopts `apscheduler >= 3.10` as a new dependency.  Justification:
a paid-spend scheduler needs misfire-grace handling
(don't fire a 6-hour-late tick once the laptop wakes up), tick
coalescing (don't fire once-per-missed-interval), and a proper
job-lifecycle event hook for observability — all of which a bare
`time.sleep` loop can technically replicate but only with hand-rolled
state we'd then need to test.  APScheduler's `BackgroundScheduler`
+ `IntervalTrigger` + `EVENT_JOB_ERROR` listener give us those
semantics for free, and §11.9 pins them.  The cost is one new
dependency in `requirements.txt`; the benefit is fewer scheduler
correctness bugs paid for in dollars.

---

## 1. Goal & non-goals

**Goal.** Wake up every `AUTO_BACKFILL_INTERVAL_HOURS`, ask the same
preview helpers `/registry/candidate-queue` and
`/movers/backfill-preview` already use to identify "high-rank,
unanalysed" headlines, and analyse up to
`AUTO_BACKFILL_MAX_LLM_CALLS_PER_RUN` of them — capped by a
hard `AUTO_BACKFILL_MAX_LLM_CALLS_PER_DAY` ledger.  No new candidate
ranking; no new fetch path; no new LLM-prompt vocabulary.

**Non-goals.**

- Not a real-time trigger.  Headline arrival does not wake the
  scheduler.  The interval is the only clock.
- Not a queue worker for `/movers/backfill-candidate` (which is
  manually invoked).  The scheduler runs the same composer, but is
  driven by a deterministic interval, not a user POST.
- Not a multi-process coordinator.  A single FastAPI process owns
  the lock; horizontal scaling is out of scope for v1 (§5).
- Not a UI feature.  `/diagnostics/auto-backfill-status` is a
  read-only operator panel, not a control surface.

---

## 2. Hard safety invariants

These hold regardless of configuration, env vars, or runtime state.
A violation of any one of these is a P0 bug.

1. **No GET / no page load can trigger paid work.**  The scheduler
   is the *only* trigger.  Every existing GET endpoint already enforces
   this — `_paid_analysis_enabled` is checked exclusively inside POST
   handlers (`movers_backfill_recent`, `movers_backfill_candidate`).
   The scheduler reaches the analyser via the same gated POST helper
   path (§6.4), so a curl GET against any URL still results in zero
   spend.  §11.5 pins this with a banlist test.
2. **Disabled by default.**  Both `ENABLE_AUTO_BACKFILL` *and*
   `ENABLE_PAID_ANALYSIS` must be true.  Either-only or
   both-unset starts the app cleanly without scheduling anything.
3. **App startup never fails because of the scheduler.**  Any
   exception during scheduler bootstrap is logged and swallowed;
   the FastAPI lifespan continues to `yield` (§7).
4. **Per-run AND per-day caps are independent.**  The per-run cap
   protects against a runaway selection; the per-day ledger protects
   against many small runs adding up.  Hitting either zero stops
   further calls (§4).
5. **A single concurrent run.**  The job lock (§5) is acquired
   before any candidate is selected and released only after the run
   summary is written.  A second tick that finds the lock held exits
   immediately with `skip_reason="lock_held"`.
6. **Failure isolation per candidate.**  A composer raise on
   candidate N must not abort candidates N+1..max.  The ledger is
   incremented only on successful spend (§4.3).
7. **No silent recovery from drift.**  If the ledger row for "today"
   does not exist when the scheduler fires, it is created with zero
   used calls — never seeded from a different day.  Clock skew across
   restarts cannot inflate quota (§4.4).

---

## 3. Environment variables — full contract

Every variable below is **read at scheduler boot only** and cached.
Operators must restart the process to pick up changes — this is the
same shape `MARKET_SNAPSHOTS_ENABLED` and `AUTO_REVISIT_ENABLED` use
in `api._lifespan` today.

| Variable | Type | Default | Effect |
|---|---|---|---|
| `ENABLE_AUTO_BACKFILL` | bool (`true`/`1`/`yes`) | `false` | Master switch.  When false, the scheduler is never started, no thread, no SQL writes, no logs. |
| `ENABLE_PAID_ANALYSIS` | bool | `false` | Pre-existing kill switch.  Even if `ENABLE_AUTO_BACKFILL=true`, the scheduler refuses to start unless this is also true.  Both must agree. |
| `AUTO_BACKFILL_INTERVAL_HOURS` | int (≥ 1) | `6` | Wall-clock period between job triggers.  Must be ≥ 1 to avoid trivially-tight schedules; values ≤ 0 are clamped to 1 with a `WARNING` log. |
| `AUTO_BACKFILL_MAX_LLM_CALLS_PER_RUN` | int (≥ 1) | `3` | Hard cap on candidates analysed in a single tick.  After this many calls (successful or errored), the run exits even if more candidates rank above threshold. |
| `AUTO_BACKFILL_MAX_LLM_CALLS_PER_DAY` | int (≥ 1) | `12` | Hard ledger cap, UTC-day-scoped.  When exhausted, every subsequent tick exits with `skip_reason="daily_cap_exhausted"` until the next UTC day. |
| `AUTO_BACKFILL_MODEL` | str | `claude-haiku-4-5` | Model id passed through to the analyser.  Must be in the project's known-model list — unknown values fall back to the default with a `WARNING` log; the run continues. |

**Boot decision tree:**

```
ENABLE_AUTO_BACKFILL ?
├── false / unset → log "auto-backfill disabled" at INFO; return.
└── true:
    ENABLE_PAID_ANALYSIS ?
    ├── false / unset → log WARNING
    │     "auto-backfill requested but ENABLE_PAID_ANALYSIS is false;
    │      not scheduling.  Either disable AUTO_BACKFILL or enable PAID."
    │     and return.
    └── true → validate caps + interval, register job, log INFO with
               full effective config (model, interval, per-run cap,
               per-day cap).  Lifespan teardown calls scheduler.shutdown().
```

The "log + return" branches must be loud enough that an operator
checking `journalctl` or `docker logs` can confirm whether the
scheduler is active or not.

---

## 4. Daily call ledger

### 4.1 Storage

A new SQLite table inside `events.db`, created idempotently from
`db.init_db` on next migration:

```sql
CREATE TABLE IF NOT EXISTS auto_backfill_ledger (
    day_utc        TEXT NOT NULL PRIMARY KEY,  -- ISO YYYY-MM-DD, UTC
    calls_used     INTEGER NOT NULL DEFAULT 0,
    last_run_at    TEXT,                       -- ISO 8601 UTC
    last_skip_reason TEXT
);
```

One row per UTC day.  Bounded growth: 365 rows / year is negligible.
No indexes needed beyond the primary key.

### 4.2 Day key — UTC, never local

The ledger is keyed by `datetime.now(timezone.utc).date().isoformat()`.
Local-time keys break across DST and across container relocations;
UTC keys are stable.  All log timestamps are UTC for consistency.

### 4.3 Reservation pattern (try/finally around the paid call)

The ledger increments via a `try/finally` that wraps the paid call.
Concretely, the per-candidate flow is:

```
acquire_lock()
ledger_row = upsert_today_ledger()  # idempotent; defaults calls_used=0
remaining_today = max_per_day - ledger_row.calls_used
if remaining_today <= 0: skip("daily_cap_exhausted")
remaining_run  = max_per_run

for candidate in ranked_candidates:
    if remaining_run <= 0:        break
    if remaining_today <= 0:      break

    # Pre-flight: check the gate one more time.  An operator could
    # have flipped ENABLE_PAID_ANALYSIS between scheduler boot and
    # this tick; the analyser already enforces it, but cheap to
    # belt-and-suspenders here too.
    if not _paid_analysis_enabled(): skip("paid_disabled_mid_run"); break

    try:
        result = analyse(candidate)         # paid call here
    except Exception as exc:
        # The provider may have charged us even on error; assume yes.
        record_error(candidate, exc)
        # Continue — failure isolation per §2.6.
    finally:
        # Increment in finally so a KeyboardInterrupt / SystemExit
        # between the paid call returning and the increment still
        # leaves the ledger correct.  Worst case: the provider
        # short-circuited to "no spend" (mock / degraded analyser
        # branch) and we over-count by one.  That's the safer side
        # — under-counting risks runaway spend.
        ledger_increment(today, by=1)

    remaining_run   -= 1
    remaining_today -= 1
```

### 4.4 Failure modes around the increment

The reservation pattern above defends against three failure modes:

| Failure | Effect on ledger |
|---|---|
| Analyser raises | Ledger still increments (provider may have charged). |
| Process crash between call and increment | `try/finally` runs the increment for `KeyboardInterrupt` / `SystemExit`; SIGKILL / power loss would lose the increment.  Documented caveat — under SIGKILL the next tick could over-spend by up to one call.  Acceptable in practice; a per-run history table (§9.3 deferred) would close the gap if it ever matters. |
| Analyser short-circuits to no-spend (mock mode, degraded fallback) | Ledger over-counts by one.  Strictly safer than the inverse error, since the bias caps spend rather than amplifies it. |

### 4.5 Reset semantics

There is no reset job.  The "next day" simply has a different
`day_utc` key, so an `INSERT OR IGNORE` on first call of that day
creates a fresh row with `calls_used=0`.

A clock that moves backwards (NTP correction, container migration)
might cause two rows to coexist for the same day; both are valid
reservations of that day's quota.  Total spend stays bounded because
both rows still cap at `max_per_day`, but the *effective* per-day
cap can briefly be 2× while the clock settles.  Acceptable for v1;
tracked as an operational caveat in the runbook entry that lands with
the implementation.

### 4.6 Manual reset

Operators occasionally need to reset the ledger after a failed run
exhausted quota uselessly.  Manual reset is a `DELETE FROM
auto_backfill_ledger WHERE day_utc = ?` run by hand from `sqlite3` —
no API, no UI button.  This is intentional: a button to reset paid
quota is a soft loaded gun.

---

## 5. Job lock — no overlap

### 5.1 Storage

Lock state lives next to the ledger:

```sql
CREATE TABLE IF NOT EXISTS auto_backfill_run_state (
    id                 INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton
    lock_acquired_at   TEXT,        -- ISO 8601 UTC
    lock_expires_at    TEXT,        -- ISO 8601 UTC
    lock_owner         TEXT,        -- "{hostname}:{pid}"
    last_completed_at  TEXT,        -- ISO 8601 UTC
    last_run_id        TEXT,        -- UUID of the last completed run
    last_skip_reason   TEXT
);
```

Singleton row guarantee via `CHECK (id = 1)`.  Idempotent
`INSERT OR IGNORE INTO ... VALUES (1, ...)` on bootstrap.

### 5.2 Acquire

Atomic SQL update:

```sql
UPDATE auto_backfill_run_state
SET    lock_acquired_at = :now,
       lock_expires_at  = :now_plus_2h,
       lock_owner       = :owner
WHERE  id = 1
  AND  (lock_acquired_at IS NULL
        OR lock_expires_at < :now);
```

The acquirer reads `cursor.rowcount` — `1` means it owns the lock,
`0` means another worker holds it.  No `SELECT-then-UPDATE` race
window.

### 5.3 Lock expiry

`lock_expires_at = now + max(2 × INTERVAL_HOURS, 2h)`.  A hung process
can hold the lock for up to that long before another tick re-claims
it.  With default `INTERVAL_HOURS=6`, that's 12 hours — long enough
for an unusually slow analyser, short enough to recover from a crash
without a full day of silence.

### 5.4 Release

In a `finally` block — whether the run completed or raised:

```sql
UPDATE auto_backfill_run_state
SET    lock_acquired_at  = NULL,
       lock_expires_at   = NULL,
       lock_owner        = NULL,
       last_completed_at = :now,
       last_run_id       = :run_id,
       last_skip_reason  = :skip_reason   -- NULL on normal completion
WHERE  id = 1
  AND  lock_owner = :owner;               -- only if we still hold it
```

The `WHERE lock_owner = :owner` clause prevents a stale finally from
clobbering a newer holder's lock if expiry already kicked in.

### 5.5 Skip reasons (vocabulary, exhaustive)

These are the only values that can land in
`auto_backfill_run_state.last_skip_reason` and the only values the
diagnostics endpoint will surface in the `last_run.skip_reason` field.

| Skip reason | When |
|---|---|
| `lock_held` | Another worker / a previous tick still owns the lock. |
| `recently_run` | `last_completed_at` is within `INTERVAL_HOURS - epsilon` (§6.1). |
| `daily_cap_exhausted` | Ledger says zero remaining for today's UTC day. |
| `paid_disabled_mid_run` | `ENABLE_PAID_ANALYSIS` flipped to false while the run was selecting candidates. |
| `no_candidates` | Selector returned an empty list (queue empty / all scored). |
| `composer_unavailable` | `analyze_event` import failed; treat as disabled for this run. |
| `job_crashed` | Caught by the job-level wrapper in §7.2 — emitted on the lock-release in the `finally` so the operator can correlate with the exception log. |

A run always closes with one of `null` (normal completion) or one
of these strings — there is no "unknown" branch.

The `disabled` case (env gate false) is *not* in this vocabulary
because the lifespan returns before scheduling, so no
`run_state` row is ever written.  Operators detect that case from
the boot log line, not from the run-state row.

---

## 6. Skip-if-recent-run

### 6.1 Threshold

`now - last_completed_at < INTERVAL_HOURS - 5 min` ⇒ skip with
`recently_run`.  The 5-minute slop lets a slightly-early APScheduler
tick (clock drift, GC pause) fire normally without bouncing.

### 6.2 Why this is independent of the lock

The lock prevents *concurrent* runs.  This guard prevents
*back-to-back* runs that the lock would let through, e.g. after a
manual `POST /diagnostics/auto-backfill/trigger` (out of v1 scope) or
after a scheduler-restart that fires the first tick immediately.

### 6.3 Pre-tick check

Reading `last_completed_at` is the very first thing the job does
after acquiring the lock, before any candidate selection.  Cheaper
than producing a candidate list and discarding it.

### 6.4 Reuse of the existing paid path

The job calls the same internal helper that
`POST /movers/backfill-candidate` uses — `analyze_event` plus the
registry-state transition — not a new analyser.  The helper already
checks `_paid_analysis_enabled()` (§2.1, ground truth at the call
site).  This is the single point of contact between the scheduler
and the LLM.

---

## 7. Failure isolation

### 7.1 Lifespan boot

```python
# api._lifespan, alongside MARKET_SNAPSHOTS_ENABLED / AUTO_REVISIT_ENABLED
if os.environ.get("ENABLE_AUTO_BACKFILL", "").lower() in ("1", "true", "yes"):
    if os.environ.get("ENABLE_PAID_ANALYSIS", "").lower() in ("1", "true", "yes"):
        try:
            from auto_backfill_scheduler import start_scheduler
            start_scheduler()
        except Exception:
            _log.warning(
                "auto_backfill: failed to start scheduler; "
                "app will continue without it",
                exc_info=True,
            )
    else:
        _log.warning(
            "auto_backfill: ENABLE_AUTO_BACKFILL=true but "
            "ENABLE_PAID_ANALYSIS is false; not scheduling."
        )
```

Notice the bare `except Exception` around `start_scheduler()`.  The
app must keep serving requests even if APScheduler import is broken
or the SQLite migration fails.

### 7.2 Job-level wrapper

The job function is wrapped end-to-end:

```python
def run_auto_backfill_job():
    run_id = uuid.uuid4().hex[:12]
    try:
        _do_run(run_id)
    except Exception as exc:
        # APScheduler will already log this, but we add the run_id so the
        # operator can correlate with the run-state row and ledger row.
        _log.exception(
            "auto_backfill[%s]: unhandled exception; run aborted",
            run_id,
        )
        # Best-effort lock release.  If the lock row update raises again,
        # we accept the lock will sit until expiry.
        try: _release_lock(owner=_owner(), reason="job_crashed",
                          run_id=run_id)
        except Exception: pass
```

Per-candidate exceptions are caught one level lower (§4.3 — the
"failure isolation per candidate" loop), so an `_do_run` exception
here means a structural failure: DB unreachable, lock SQL syntax error,
import circular.  Those are operator-visible; per-candidate composer
errors are log-only and counted in the run summary.

### 7.3 APScheduler error listener

A defensive `scheduler.add_listener(_log_error, EVENT_JOB_ERROR)`
catches exceptions APScheduler swallowed (e.g. misfire-handler
errors).  This is belt-and-suspenders; in practice the job-level
wrapper covers everything, but the listener guarantees visibility if
APScheduler itself goes wrong.

### 7.4 Misfire policy

`misfire_grace_time=600` (10 minutes) and `coalesce=True`.  If the
process was paused (laptop sleep, debugger break) and several ticks
queued, APScheduler runs the job once.  Anything older than 10 minutes
is dropped — rather than firing a stale paid run "to catch up,"
better to wait for the next regular tick.

---

## 8. Candidate selection

### 8.1 Source

Reuse `routes.diagnostics._compute_major_skipped` (or its underlying
movers helpers — `_score_cluster_for_preview`,
`_cached_news_payload`, `_registry_state_for_title_key`,
`_headline_is_market_relevant`).  These are already pure / read-only /
zero-cost / production-tested.  The scheduler imports the helpers
behind a `try/except ImportError` inside `_do_run`, so a refactor of
the movers module that breaks the import skips the run with
`composer_unavailable` instead of crashing the scheduler.

### 8.2 Filter parameters

| Parameter | Value | Rationale |
|---|---|---|
| `since_hours` | `INTERVAL_HOURS × 4` (capped at 72) | Window must cover at least the last few ticks so a headline that arrives between ticks doesn't get missed.  Capped at 72h so the scheduler doesn't routinely re-rank stale clusters. |
| `min_source_count` | `2` | Same default the existing `/diagnostics/major-skipped-headlines` endpoint uses; filters singleton-source rumours. |
| `include_low_signal` | `false` | Conservative — paid scheduler should not spend on low-signal clusters. |
| `limit` | `MAX_LLM_CALLS_PER_RUN × 3` | Pull 3× the cap so registry state changes between selection and analysis don't shrink the candidate set below the cap. |

### 8.3 Ranking

Re-use `_score_cluster_for_preview` exactly.  Ties broken by
`source_count`, then by asset-term presence (the same tie-breakers
already encoded in `routes/movers.py:_rank_explanation`).  No new
ranking signal is introduced by the scheduler.

### 8.4 Skip already-analysed

Before analysing each candidate, re-check the registry state via
`_registry_state_for_title_key` — if it has already moved to
`analyzed` / `market_checked` / `surfaced` / `expired_low_impact`
since selection, skip without spending.  This is a soft race window
(another scheduler instance, a manual backfill) but the registry's
own dedup will catch it as a fallback anyway.

---

## 9. Diagnostics & logging

### 9.1 Read-only endpoint

`GET /diagnostics/auto-backfill-status` — same partial-failure shape
as the other diagnostics routes (§9 of `reaction_profile_design.md`
sets the precedent):

```json
{
  "available": true,
  "enabled": true,
  "paid_analysis_enabled": true,
  "interval_hours": 6,
  "max_per_run": 3,
  "max_per_day": 12,
  "model": "claude-haiku-4-5",
  "today": {
    "day_utc": "2026-05-05",
    "calls_used": 4,
    "calls_remaining": 8
  },
  "last_run": {
    "run_id": "a1b2c3d4e5f6",
    "completed_at": "2026-05-05T14:00:01Z",
    "skip_reason": null,
    "candidates_seen": 6,
    "candidates_analyzed": 3,
    "errors": 0
  },
  "lock": {
    "held": false,
    "acquired_at": null,
    "expires_at": null,
    "owner": null
  }
}
```

When `enabled=false` or `paid_analysis_enabled=false`, the rest of
the block falls back to zeros / nulls.  Implementation lives in
`routes/diagnostics.py` next to the existing config-health and
validation-status panels.

### 9.2 Structured log fields

Every log line emitted from the scheduler uses Python `logging` with
a stable extra-field set so log scrapers can index them:

| Field | Type | When |
|---|---|---|
| `run_id` | str (12-char hex) | every line emitted from a run |
| `event` | str (`run_started`, `lock_acquired`, `candidate_selected`, `candidate_analyzed`, `candidate_skipped`, `run_completed`, `run_skipped`) | mandatory |
| `interval_hours` | int | bootstrap line only |
| `candidate_headline` | str (truncated to 80 chars) | per-candidate lines |
| `candidate_rank_score` | float | per-candidate lines |
| `calls_used_today` | int | run start + run end |
| `calls_remaining_today` | int | run start + run end |
| `skip_reason` | str / null | run-end and per-candidate-skip lines |
| `error_type` | str | only when a candidate raised |
| `error_message` | str (truncated 200 chars) | only when a candidate raised |

**No log line carries headline content beyond 80 chars and never
carries LLM completions.**  The risk model is "operator can read logs
in a screenshare without leaking intel".

### 9.3 Per-run summary row

`auto_backfill_run_state.last_run_id` and `last_completed_at` are the
canonical record.  A more detailed history table is *deferred* —
`logs/` retention is plenty for v1 forensics; a per-run table can be
added later without schema churn since `run_id` is already the
join key.

---

## 10. Concurrency / horizontal-scaling notes

The lock guarantees a single concurrent run **per database file**.
Two FastAPI processes pointing at the same `events.db` correctly
coordinate via the SQL lock.  Two processes pointing at *different*
DBs (e.g. dev + prod on the same host) each run their own scheduler
against their own ledger.  Cross-process coordination beyond a shared
DB is out of scope; the runbook should call out "do not run two
schedulers against two DBs that share a paid-analysis API key,
because their ledgers don't talk to each other."

A future v2 may move the ledger to a shared Redis if multi-instance
deployment becomes real.  Today's design's swap-out cost is one
helper module — the rest of the scheduler is ledger-agnostic.

---

## 11. Tests required BEFORE implementation

Each block names a new test file.  Fixtures use temp DBs + monkey-
patched env vars; nothing reaches the network or the LLM.  Per
project convention, every test is added BEFORE the corresponding
implementation lands (TDD).

### 11.1 `tests/test_auto_backfill_scheduler_boot.py`

| Test | Pinned behaviour |
|---|---|
| `test_disabled_by_default_no_scheduler_started` | App boots with both env vars unset.  No background thread.  `/diagnostics/auto-backfill-status` returns `available=true, enabled=false`. |
| `test_enabled_without_paid_does_not_start` | `ENABLE_AUTO_BACKFILL=true`, `ENABLE_PAID_ANALYSIS=false` ⇒ no scheduler thread; WARNING log captured. |
| `test_enabled_with_paid_starts_scheduler` | Both true ⇒ scheduler started; `add_job` mock asserts called with the right interval; lifespan teardown calls `shutdown()`. |
| `test_invalid_interval_clamps_to_one_hour` | `AUTO_BACKFILL_INTERVAL_HOURS=0` ⇒ effective `1`, WARNING log emitted. |
| `test_unknown_model_falls_back_to_default` | `AUTO_BACKFILL_MODEL=does-not-exist` ⇒ default model used, WARNING log emitted, scheduler still starts. |
| `test_scheduler_boot_failure_does_not_break_app` | `start_scheduler` raises ⇒ `/health` still returns 200; warning logged. |

### 11.2 `tests/test_auto_backfill_ledger.py`

| Test | Pinned behaviour |
|---|---|
| `test_first_call_creates_today_row` | Empty table.  One increment ⇒ row exists with `calls_used=1`. |
| `test_increment_atomic_under_concurrent_writes` | Two threads each call `ledger_increment` 5×.  Final value = 10. |
| `test_new_utc_day_starts_fresh` | Patch `datetime.now` across UTC midnight.  Day-1 row at 11 calls, day-2 row independent at 0. |
| `test_cap_exhaustion_prevents_further_calls` | Seed `calls_used = max_per_day`.  Run trigger ⇒ skip with `daily_cap_exhausted`. |
| `test_clock_skew_creates_independent_day_rows` | Two day-keys for "the same day" both rate-limit independently — accept the documented 2× edge case. |

### 11.3 `tests/test_auto_backfill_lock.py`

| Test | Pinned behaviour |
|---|---|
| `test_lock_acquire_when_unlocked` | Empty state ⇒ acquire returns owner-token; row updated. |
| `test_concurrent_acquire_only_one_wins` | Two acquires in tight succession; second returns `None` and `skip_reason="lock_held"`. |
| `test_expired_lock_can_be_reclaimed` | Seed an expired lock row (now − 1 day) ⇒ next acquire wins; old owner-token cannot release it. |
| `test_release_only_succeeds_for_owner` | Owner A acquires, owner B's release is a no-op; A's release clears the row. |
| `test_finally_release_after_job_crash` | Job crashes mid-run ⇒ lock released with `last_skip_reason="job_crashed"`. |

### 11.4 `tests/test_auto_backfill_skip_recent.py`

| Test | Pinned behaviour |
|---|---|
| `test_first_run_after_boot_is_not_skipped` | `last_completed_at` null ⇒ run proceeds. |
| `test_run_within_interval_is_skipped` | `last_completed_at = now − interval/2` ⇒ skip with `recently_run`. |
| `test_run_just_after_interval_proceeds` | `last_completed_at = now − interval − 1min` ⇒ run proceeds. |
| `test_grace_window_allows_slightly_early_tick` | `last_completed_at = now − interval + 4min` ⇒ run proceeds (slop allows it). |

### 11.5 `tests/test_auto_backfill_no_paid_via_get.py`

| Test | Pinned behaviour |
|---|---|
| `test_no_get_endpoint_calls_analyze_event` | Boot the app with both env vars true.  Patch `analyze_event` to raise.  Enumerate GET routes from `api.app.routes` (NOT a hard-coded list — a future endpoint added without the banlist must still get caught) and hit each with synthetic path params; none raise — i.e. none of them call the analyser. |
| `test_only_scheduler_tick_can_invoke_analyzer` | Same setup; verify only the scheduler's job function reaches `analyze_event` (via call-counter on the patch).  Manually trigger a tick → exactly N calls (= candidates analysed). |
| `test_GET_status_endpoint_does_not_increment_ledger` | Hit `/diagnostics/auto-backfill-status` 5× ⇒ `calls_used` unchanged. |

### 11.6 `tests/test_auto_backfill_candidate_selection.py`

| Test | Pinned behaviour |
|---|---|
| `test_empty_news_cache_skips_with_no_candidates` | Patched empty `_cached_news_payload` ⇒ skip with `no_candidates`. |
| `test_only_paid_eligible_candidates_returned` | Mixed registry; assert already-analysed clusters dropped before spending. |
| `test_max_per_run_caps_calls_even_when_more_eligible` | 10 ranked clusters, `max_per_run=3` ⇒ exactly 3 analyser calls. |
| `test_max_per_day_caps_across_runs` | Two ticks the same UTC day, `max_per_day=4`, each run's preview shows 5 candidates ⇒ first run analyses 4 (or `max_per_run`), second skips. |
| `test_low_signal_clusters_filtered` | `low_signal=True` clusters not selected. |
| `test_min_source_count_filter` | `source_count < 2` clusters not selected. |

### 11.7 `tests/test_auto_backfill_failure_isolation.py`

| Test | Pinned behaviour |
|---|---|
| `test_one_candidate_raise_does_not_abort_others` | 3 candidates; second raises ⇒ candidates 1 and 3 still analysed; ledger `calls_used += 3` (errored calls count). |
| `test_provider_5xx_emits_error_log_and_continues` | Patched analyser raises an HTTP-shaped exception; log carries `error_type` and `error_message`; run still completes. |
| `test_lock_released_after_provider_error` | After every candidate raises, lock row is back to `lock_acquired_at IS NULL`. |
| `test_paid_disabled_mid_run_stops_subsequent_calls` | Flip `ENABLE_PAID_ANALYSIS=false` after first call ⇒ second call skipped with `paid_disabled_mid_run`. |

### 11.8 `tests/test_auto_backfill_diagnostics_endpoint.py`

| Test | Pinned behaviour |
|---|---|
| `test_disabled_returns_stable_shape` | Feature off ⇒ `enabled=false`, every numeric field `0`, `last_run` null. |
| `test_enabled_after_one_run_reports_summary` | Run one synthetic tick ⇒ `last_run.run_id`, `candidates_analyzed`, `errors`, `today.calls_used` all populated. |
| `test_response_byte_stable_across_two_calls` | Two GETs in a row produce byte-identical JSON (no clock leak). |
| `test_partial_failure_isolated_per_block` | Patch the ledger reader to raise ⇒ `today` block carries `available=false`; the rest of the response (lock, last_run, config) is intact. |

### 11.9 `tests/test_auto_backfill_misfire.py`

| Test | Pinned behaviour |
|---|---|
| `test_coalesce_collapses_queued_ticks` | Simulate 3 queued ticks during a `time.sleep` ⇒ run executes once. |
| `test_misfire_grace_drops_stale_tick` | Tick scheduled > 10 minutes in the past ⇒ APScheduler does not fire the job; no spend. |

---

## 12. Open questions / deferred decisions

- **Manual trigger.**  v1 has no `POST /diagnostics/auto-backfill/trigger`.
  An operator who wants an immediate run restarts the process or
  changes the interval.  Adding a manual trigger is a small follow-up
  but introduces a second invocation path; deferring keeps v1's
  attack surface minimal.
- **Per-candidate cost ceiling.**  Today's analyser does not carry a
  per-call dollar estimate.  Future calibration may want to skip
  candidates whose estimated tokens × model price exceeds a per-day
  budget rather than a per-day call count.  Out of scope here; the
  ledger SQL would gain a `dollars_spent` column.
- **Replay of failed candidates.**  A candidate that errors today is
  not retried tomorrow automatically — the registry will move it to
  `expired_low_impact` if it ages out.  Whether to add a deliberate
  `retry_after_at` column is deferred until we see real failure
  patterns.
- **Per-run history table.**  `auto_backfill_run_state.last_run_*`
  carries one row.  A `auto_backfill_run_history` insert-only table
  would let the diagnostics panel show a 7-day timeline; deferred
  until the operator panel actually wants that view.
- **Multi-instance coordination.**  Mentioned in §10.  Not blocking
  v1; trigger is a deployment change, not a code one.

---

## 13. Verification

This document changes no code.  `git diff --check` is the only
mechanical verification expected this turn; clean output is the
success signal.  The test bodies in §11 are the contract under which
the implementation will land in a follow-up.
