# Auto-Backfill Scheduler Execution Audit (Lifespan Smoke)

This audit confirms that the FastAPI `lifespan` integration of the
dry-run auto-backfill scheduler is safe in every observable
configuration: the scheduler is only attached when both env gates are
true, the operator-panel `GET /diagnostics/auto-backfill-status`
endpoint reflects the attached state without spending paid calls or
reserving ledger calls, the dedicated scheduler smoke and the
existing no-paid smoke are both green, and shutdown stops the
scheduler. Paid execution remains unimplemented.

- Audit date: 2026-05-06
- Working directory: `C:\Users\Bar\desktop\geo_mechanism_project`
- Branch: `main`
- Environment: defaults — `ENABLE_AUTO_BACKFILL` and `ENABLE_PAID_ANALYSIS`
  unset (off-state); the scheduler smoke flips both to `true` for the
  duration of an in-process lifespan window via a snapshot-and-restore
  context manager. The shell environment is never mutated.

## Surfaces compared

| #   | Surface                                                    | Owner                                                          |
|-----|------------------------------------------------------------|----------------------------------------------------------------|
| (1) | `python scripts/auto_backfill_scheduler_smoke.py --json`   | `scripts/auto_backfill_scheduler_smoke.py` (live lifespan probe) |
| (2) | `GET /diagnostics/auto-backfill-status` inside lifespan    | `routes/diagnostics.py::auto_backfill_status`                  |
| (3) | `python scripts/no_paid_smoke.py --json`                   | `scripts/no_paid_smoke.py`                                     |

(1) is the dedicated dry-run scheduler smoke: it boots `api.app`'s
real lifespan with both gates flipped on, but patches
`auto_backfill_scheduler.create/start/stop`, raises on
`AutoBackfillLedger.reserve_calls`, and wraps every paid/provider
seam from `no_paid_smoke.guard_no_paid_provider_calls` with raisers,
so no APScheduler executor thread is spawned and no paid path is
reachable. (2) is the same diagnostics surface read inside the
lifespan from the smoke — its body is included verbatim in the
smoke's JSON report. (3) is the long-standing no-paid demo smoke; the
auto-backfill-status check inside it pins the off-state shape under
the default env.

Companion: `tests.test_auto_backfill_lifespan_wiring` is the
authoritative real-lifespan wiring suite. It pins the same
attach/start/stop contract via `with TestClient(api.app) as client:`
and asserts the GET status body when a fake scheduler is attached.
`tests.test_auto_backfill_scheduler_smoke` pins the smoke script
itself. The pre-wiring contract spec
`tests.test_auto_backfill_lifespan_plan` still passes (16/16 OK).

## (1) `python scripts/auto_backfill_scheduler_smoke.py --json` — 8/8 PASS

```json
{
  "checks": [
    { "name": "scheduler attached during lifespan",       "ok": true, "detail": null },
    { "name": "status endpoint mode=dry_run_only",        "ok": true, "detail": null },
    { "name": "status endpoint scheduler_started=true",   "ok": true, "detail": null },
    { "name": "no ledger calls reserved",                 "ok": true, "detail": null },
    { "name": "no paid/provider seams called",            "ok": true, "detail": null },
    { "name": "scheduler stops on shutdown",              "ok": true, "detail": null },
    { "name": "app.state cleaned after shutdown",         "ok": true, "detail": null },
    { "name": "no real apscheduler thread spawned",       "ok": true, "detail": null }
  ],
  "ok": true,
  "summary": { "passed": 8, "failed": 0, "total": 8 },
  "elapsed_ms": 591
}
```

The smoke's JSON report also embeds the diagnostics body captured
inside the lifespan (verbatim under the top-level `diagnostics`
key) — this is surface (2b) below.

The eight checks map directly onto the lifespan contract:

| Check                                       | Mechanism                                                                                                                                                                                                                                                            |
|---------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| scheduler attached during lifespan          | `getattr(app.state, "auto_backfill_scheduler", None) is fake`. The lifespan helper publishes the started scheduler to `app.state` only after `start_auto_backfill_scheduler` returns successfully.                                                                  |
| status endpoint mode=dry_run_only           | `body["scheduler"]["mode"] == "dry_run_only"`. `routes/diagnostics.py::_scheduler_block` reads `app.state.auto_backfill_scheduler` and returns this string when one is present and `running=True`.                                                                  |
| status endpoint scheduler_started=true      | `body["scheduler"]["scheduler_started"] is True`. Same path: derived from `scheduler.running` of the attached fake.                                                                                                                                                  |
| no ledger calls reserved                    | `body["ledger"]["used"] == 0` *combined with* a `RuntimeError` raiser patched onto `AutoBackfillLedger.reserve_calls`. If anything had attempted to reserve a paid call, the lifespan would have crashed under the raiser; the `used==0` outcome is the joint proof. |
| no paid/provider seams called               | `no_paid_smoke.guard_no_paid_provider_calls()` is active for the entire lifespan window; any paid call (LLM, market provider, `/analyze*`, `movers/backfill-*`) would have raised. Reaching the assertion alive is the proof.                                       |
| scheduler stops on shutdown                 | After exiting the `TestClient` `with` block, `stop_auto_backfill_scheduler.call_count == 1` and `call_args[0] is fake` — the lifespan stopped *that exact* scheduler.                                                                                                |
| app.state cleaned after shutdown            | `getattr(app.state, "auto_backfill_scheduler", None) is None`. The shutdown helper drops the attribute so a follow-on lifespan boot starts from a clean slate.                                                                                                       |
| no real apscheduler thread spawned          | Snapshot of `threading.enumerate()` names taken before the lifespan and after it. No new lowercase `"apscheduler"` thread appears — confirming the patches intercepted the real `BackgroundScheduler` factory and no executor thread leaked.                        |

## (2) `GET /diagnostics/auto-backfill-status` inside lifespan

### (2a) gates OFF — default env, captured in the no-paid smoke

```json
{
  "config": {
    "effective_status": "disabled",
    "enabled": false,
    "interval_hours": 6,
    "max_calls_per_day": 12,
    "max_calls_per_run": 3,
    "model": "claude-haiku-4-5-20251001",
    "paid_analysis_enabled": false,
    "warnings": []
  },
  "daily_remaining": 12,
  "effective_status": "disabled",
  "last_error": null,
  "last_skip_reason": null,
  "ledger": {
    "daily_cap": 12,
    "day": "2026-05-06",
    "remaining": 12,
    "used": 0
  },
  "scheduler": {
    "job_count": 0,
    "mode": "not_wired",
    "scheduler_available": true,
    "scheduler_started": false
  },
  "state": {
    "last_completed_at": null,
    "last_error": null,
    "last_run_id": null,
    "last_selected_count": null,
    "last_skip_reason": null,
    "last_spent_calls": null,
    "last_started_at": null,
    "lock_acquired_at": null,
    "lock_expires_at": null,
    "lock_held": false,
    "lock_owner": null
  }
}
```

`scheduler.mode` is `"not_wired"` and `scheduler_started` is `false` —
the lifespan helper short-circuited at
`cfg.effective_status != "configured"` and never published a
scheduler to `app.state`. The no-paid smoke's body invariant
`_assert_auto_backfill_status_no_paid` enforces exactly this shape.

### (2b) gates BOTH-TRUE — attached during scheduler smoke lifespan

Verbatim from the smoke's `diagnostics` field in (1):

```json
{
  "config": {
    "effective_status": "configured",
    "enabled": true,
    "interval_hours": 6,
    "max_calls_per_day": 12,
    "max_calls_per_run": 3,
    "model": "claude-haiku-4-5-20251001",
    "paid_analysis_enabled": true,
    "warnings": []
  },
  "daily_remaining": 12,
  "effective_status": "configured",
  "last_error": null,
  "last_skip_reason": null,
  "ledger": {
    "daily_cap": 12,
    "day": "2026-05-06",
    "remaining": 12,
    "used": 0
  },
  "scheduler": {
    "job_count": 1,
    "mode": "dry_run_only",
    "scheduler_available": true,
    "scheduler_started": true
  },
  "state": {
    "last_completed_at": null,
    "last_error": null,
    "last_run_id": null,
    "last_selected_count": null,
    "last_skip_reason": null,
    "last_spent_calls": null,
    "last_started_at": null,
    "lock_acquired_at": null,
    "lock_expires_at": null,
    "lock_held": false,
    "lock_owner": null
  }
}
```

`scheduler.mode="dry_run_only"`, `scheduler_started=true`,
`job_count=1`, `effective_status="configured"`. `ledger.used` stays
`0` and `daily_remaining` stays `12` — the read-only status endpoint
did not reserve a paid call (and could not have: `reserve_calls` is
patched to raise during the smoke).

## (3) `python scripts/no_paid_smoke.py --json` — 14/14 PASS

```json
{
  "ok": true,
  "summary": { "passed": 14, "failed": 0, "total": 14 }
}
```

The auto-backfill-status check inside the smoke enforces two no-paid
invariants that match the GET capture in (2a):

- `scheduler.scheduler_started` is `false` (no background scheduler
  running under the default env)
- `ledger.used` is `0` (no paid call has been reserved)

Both are satisfied; the smoke is green. The smoke also re-asserts
that `POST /diagnostics/auto-backfill-dry-run` returns 200 with valid
JSON and that the route inventory contains no banned paid path
(`/analyze`, `/analyze/stream`, `/movers/backfill-recent`,
`/movers/backfill-candidate`).

## Confirmations

| Claim                                                                               | Evidence                                                                                                                                                                                                              |
|-------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Dry-run scheduler can be attached under both gates                                  | (1) `scheduler attached during lifespan` PASS — `app.state.auto_backfill_scheduler is fake_scheduler` inside the lifespan with `ENABLE_AUTO_BACKFILL=true` / `ENABLE_PAID_ANALYSIS=true`. (2b) GET status reports `effective_status="configured"`, `scheduler.mode="dry_run_only"`, `scheduler_started=true`, `job_count=1`. Cross-check: `tests.test_auto_backfill_lifespan_wiring.TestLifespanWiringBothGatesTrue` (5 tests) covers the same path. |
| Dry-run scheduler is **not** attached when either gate is off                       | (2a) gates-off GET status: `scheduler.mode="not_wired"`, `scheduler_started=false`, `effective_status="disabled"`. (3) no-paid smoke `_assert_auto_backfill_status_no_paid` invariant. Cross-check: `TestLifespanWiringDisabled` and `TestLifespanWiringPaidGuardBlocked` (5 tests).                                                                       |
| No paid call is executed                                                            | (1) `no paid/provider seams called` PASS — `guard_no_paid_provider_calls()` blanket-raises on every paid seam for the lifespan window; the lifespan completed without raising. (2a)/(2b) `ledger.used=0` on every GET. `auto_backfill_runner.execute_paid_candidate` itself raises `NotImplementedError` (pinned by `tests.test_auto_backfill_runner.test_execute_paid_candidate_raises_not_implemented`). |
| No ledger call is reserved                                                          | (1) `no ledger calls reserved` PASS — `AutoBackfillLedger.reserve_calls` is patched to a `RuntimeError` raiser; the lifespan and the GET endpoint both completed without triggering it; `body["ledger"]["used"]==0` confirms. (3) no-paid smoke pins `ledger.used=0` separately under the default env. |
| Shutdown stops scheduler                                                            | (1) `scheduler stops on shutdown` PASS — `stop_auto_backfill_scheduler.call_count==1` and `call_args[0] is fake`. `app.state cleaned after shutdown` PASS — the attribute is dropped. Cross-check: `TestLifespanWiringBothGatesTrue.test_shutdown_calls_stop_when_scheduler_was_started` and `test_shutdown_drops_app_state_attribute`. Stop raises are logged and swallowed (`test_stop_raise_does_not_propagate_through_shutdown`). |
| Paid execution remains unimplemented                                                | `auto_backfill_runner.execute_paid_candidate({})` raises `NotImplementedError` with the message *"auto_backfill_runner.execute_paid_candidate is not implemented; auto-backfill currently runs in dry-run mode only.  See docs/auto_backfill_scheduler_design.md §4 / §11 for the paid-path contract that will replace this stub."* No verifying surface invokes it: the smoke uses a `MagicMock` scheduler whose patched `start_auto_backfill_scheduler` is a no-op, so no real APScheduler tick — and therefore no candidate executor — runs. |
| GET `/diagnostics/auto-backfill-status` is read-only                                | (1)+(2b) under the smoke, `ledger.used=0` and `daily_remaining=12` both inside the lifespan and after the GET; `state.last_*` fields stay `null`. The only mutation a read could make would be a `reserve_calls` call, which would have raised under the patch. (3) no-paid smoke pins the same invariant under the default env. |
| Boot failures do not crash the app and do not publish a partial scheduler           | Cross-check: `TestLifespanWiringBootFailureSwallowed` (4 tests) — factory raise, start raise, and config-load raise all keep `app.state.auto_backfill_scheduler` unset and the app responds 200 to `/health`.                                                                                                                                          |
| No real APScheduler executor thread spawns under the smoke                          | (1) `no real apscheduler thread spawned` PASS — `threading.enumerate()` snapshot before/after shows no new `"apscheduler"`-named thread. The smoke patches `auto_backfill_scheduler.create/start/stop`, so the lifespan never reaches the real `BackgroundScheduler`.                                                                                  |

## Observed result fields (summary)

| Field                                       | gates OFF (2a) | gates ON, smoke-attached (1)+(2b) |
|---------------------------------------------|---------------:|----------------------------------:|
| `effective_status`                          | `disabled`     | `configured`                      |
| `scheduler.mode`                            | `not_wired`    | `dry_run_only`                    |
| `scheduler.scheduler_started`               | `false`        | `true`                            |
| `scheduler.job_count`                       | `0`            | `1`                               |
| `scheduler.scheduler_available`             | `true`         | `true`                            |
| `ledger.used`                               | `0`            | `0`                               |
| `ledger.remaining`                          | `12`           | `12`                              |
| `daily_remaining`                           | `12`           | `12`                              |
| `state.last_run_id`                         | `null`         | `null`                            |
| `state.last_spent_calls`                    | `null`         | `null`                            |
| `state.lock_held`                           | `false`        | `false`                           |
| smoke summary                               | n/a            | 8/8 PASS, `elapsed_ms≈591`        |

## Commands used

```powershell
# (1) Live dry-run scheduler smoke — boots api.app's lifespan with mocked seams
python scripts/auto_backfill_scheduler_smoke.py --json

# Cross-check: pinned by the smoke's own unit tests
python -m unittest tests.test_auto_backfill_scheduler_smoke

# Cross-check: real-lifespan wiring suite + companion contract spec
python -m unittest tests.test_auto_backfill_lifespan_wiring
python -m unittest tests.test_auto_backfill_lifespan_plan

# (3) Existing no-paid demo smoke (default env / off-state)
python scripts/no_paid_smoke.py --json
```

## Conclusion

Inside the FastAPI lifespan, the dry-run auto-backfill scheduler is
attached only when both `ENABLE_AUTO_BACKFILL` and
`ENABLE_PAID_ANALYSIS` are true; in every other case the helper
short-circuits with a warning and `scheduler.mode` remains
`"not_wired"`. When the scheduler is attached, the dedicated smoke
script confirms `mode="dry_run_only"`, `scheduler_started=true`,
`job_count=1`, the scheduler is published to `app.state`, no real
APScheduler thread spawns, no paid/provider seam is invoked, no
`AutoBackfillLedger.reserve_calls` happens, shutdown stops the
scheduler, and `app.state` is cleaned afterward — 8/8 PASS in
`scripts/auto_backfill_scheduler_smoke.py --json`. The existing
no-paid smoke pins the off-state shape under the default env (14/14
PASS), and `auto_backfill_runner.execute_paid_candidate` still raises
`NotImplementedError` — paid execution remains unimplemented.
