# Auto-Backfill Dry-Run Scheduler Tick Audit

This audit confirms that the scheduler-tick path of the auto-backfill
foundation is dry-run only at every layer: importing the scheduler
module does not start a thread, the operator-triggered dry-run route
does not mutate the long-lived state/ledger singletons, the per-tick
runner spends zero calls, and no paid or provider seam is invoked
inside the verifying tests.

The audit also pins the current integration boundary: the FastAPI
`lifespan` hook that would construct and start a live scheduler **has
not landed**. The status endpoint reports `scheduler_started=false` and
`mode="not_wired"` accordingly.

- Audit date: 2026-05-06
- Working directory: `C:\Users\Bar\desktop\geo_mechanism_project`
- Branch: `main`
- Environment: defaults — `ENABLE_AUTO_BACKFILL` and `ENABLE_PAID_ANALYSIS`
  unset; loader falls back to documented defaults (interval 6h, 3/run,
  12/day, model `claude-haiku-4-5-20251001`).

## Surfaces compared

| #   | Surface                                            | Owner                                                  |
|-----|----------------------------------------------------|--------------------------------------------------------|
| (1) | `tests.test_auto_backfill_scheduler`               | `auto_backfill_scheduler.py` skeleton                  |
| (2) | `tests.test_auto_backfill_runner`                  | `auto_backfill_runner.run_auto_backfill_dry_run`       |
| (3) | `POST /diagnostics/auto-backfill-dry-run`          | `routes/diagnostics.py::auto_backfill_dry_run`         |
| (4) | `GET  /diagnostics/auto-backfill-status`           | `routes/diagnostics.py::auto_backfill_status`          |

## (1) `tests.test_auto_backfill_scheduler` — 19/19 OK

```text
test_caller_can_inject_a_scheduler_engine ... ok
test_configured_config_adds_one_job ... ok
test_job_uses_interval_trigger_with_configured_seconds ... ok
test_default_coalesce_max_instances_misfire_grace_set ... ok
test_overrides_propagate_to_job ... ok
test_disabled_config_results_in_no_job ... ok
test_disabled_scheduler_can_be_safely_stopped ... ok
test_paid_guard_blocked_config_results_in_no_job ... ok
test_module_exposes_required_public_functions ... ok
test_module_has_no_module_level_scheduler_instance ... ok
test_no_thread_spawned_by_module_import ... ok
test_candidate_loader_invoked_when_job_runs ... ok
test_default_candidate_loader_returns_empty_list ... ok
test_loader_exception_does_not_crash_executor ... ok
test_runner_exception_does_not_crash_executor ... ok
test_runner_invoked_with_candidates_config_state_ledger ... ok
test_start_is_idempotent ... ok
test_stop_idempotent_after_start_then_stop ... ok
test_stop_on_never_started_scheduler_does_not_raise ... ok
Ran 19 tests in 0.007s
OK
```

Key assertions exercised:

- `test_no_thread_spawned_by_module_import` — snapshots the live thread
  set immediately before and immediately after `import
  auto_backfill_scheduler`; the difference must be empty. Passes.
- `test_module_has_no_module_level_scheduler_instance` — scans
  `dir(scheduler_module)` for any `BackgroundScheduler` instance and
  fails the test if one exists. Passes.
- `test_disabled_config_results_in_no_job` and
  `test_paid_guard_blocked_config_results_in_no_job` — even when
  `create_auto_backfill_scheduler` is invoked, no job is registered
  unless `effective_status == "configured"`.
- `test_default_candidate_loader_returns_empty_list` — the in-tree
  default loader is the no-op `[]`; the wiring layer would inject the
  real cached-news loader.
- `test_loader_exception_does_not_crash_executor` and
  `test_runner_exception_does_not_crash_executor` — the per-tick
  closure swallows exceptions so APScheduler's executor thread
  survives.
- `TestSeamsPatched` exclusively uses `MagicMock` runners; the real
  `run_auto_backfill_dry_run` is **never** invoked from this test
  module, and `execute_paid_candidate` (which raises
  `NotImplementedError`) is consequently never exercised.

## (2) `tests.test_auto_backfill_runner` — 19/19 OK

```text
test_run_id_factory_is_called_once_per_run ... ok
test_two_runs_at_same_now_with_same_factory_match ... ok
test_empty_candidate_list_completes_with_zero_selected ... ok
test_ledger_unchanged_even_when_skipped ... ok
test_ledger_used_count_unchanged_after_dry_run ... ok
test_execute_paid_candidate_raises_not_implemented ... ok
test_runner_does_not_invoke_paid_stub_in_dry_run ... ok
test_already_analyzed_candidates_filtered_out ... ok
test_plan_caps_at_max_per_run ... ok
test_plan_respects_daily_remaining_when_lower_than_run_cap ... ok
test_returns_run_result_with_expected_fields ... ok
test_daily_cap_exhausted_skips ... ok
test_disabled_config_skips_with_disabled_reason ... ok
test_lock_held_by_other_owner_skips_with_lock_held ... ok
test_paid_guard_blocks_when_paid_disabled ... ok
test_recently_run_skips_within_interval ... ok
test_completed_run_stamps_started_and_completed_at ... ok
test_lock_released_after_completion ... ok
test_skipped_path_does_not_stamp_started ... ok
Ran 19 tests in 0.030s
OK
```

Key assertions exercised:

- `test_ledger_used_count_unchanged_after_dry_run` and
  `test_ledger_unchanged_even_when_skipped` — `ledger.used` does not
  change across any code path of the runner.
- `test_runner_does_not_invoke_paid_stub_in_dry_run` — patches
  `auto_backfill_runner.execute_paid_candidate` to a raiser; the test
  asserts the dry-run runner never invokes it.
- `test_execute_paid_candidate_raises_not_implemented` — the paid stub
  is wired to raise loudly until a real paid runner replaces it.

## (3) `POST /diagnostics/auto-backfill-dry-run`

Captured via in-process `fastapi.testclient.TestClient(api.app)`. The
route uses **ephemeral** `AutoBackfillState` and `AutoBackfillLedger`
constructed inside `_compose_auto_backfill_dry_run` and discarded after
the response is built.

```text
POST dry-run result snippet:
  spent_calls = 0
  selected_count = 0
  decision_reason = disabled
  ledger = {"daily_cap": 12, "day": "2026-05-06", "remaining": 12, "used": 0}
  state.last_skip_reason (ephemeral) = disabled
```

`spent_calls=0` is contractual on every dry-run path; the route
forwards the runner's `RunResult.spent_calls` verbatim.

## (4) `GET /diagnostics/auto-backfill-status` — pre/post comparison

Captured immediately before and immediately after the POST in §3,
against the same `TestClient`. The two GET snapshots are byte-equal
on the singleton fields, proving the dry-run did not mutate them.

```text
GET status BEFORE POST:
  state =     {"last_completed_at": null, "last_run_id": null,
               "last_skip_reason": null, "lock_held": false}
  ledger =    {"daily_cap": 12, "day": "2026-05-06",
               "remaining": 12, "used": 0}
  scheduler = {"job_count": 0, "mode": "not_wired",
               "scheduler_available": true, "scheduler_started": false}

GET status AFTER POST:
  state =     {"last_completed_at": null, "last_run_id": null,
               "last_skip_reason": null, "lock_held": false}
  ledger =    {"daily_cap": 12, "day": "2026-05-06",
               "remaining": 12, "used": 0}
  scheduler = {"job_count": 0, "mode": "not_wired",
               "scheduler_available": true, "scheduler_started": false}

Singletons unchanged across POST?  True
```

The POST in §3 reported `state.last_skip_reason="disabled"` on its own
ephemeral state, but the singletons feeding `GET status` show
`last_skip_reason=null` both before and after — confirming the
ephemeral state never leaked into the operator-panel singletons.

## Safety assertions confirmed

| Assertion                                                                         | Evidence                                                                                                                                                                                          |
|-----------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Scheduler module import does not start a thread                                   | (1) `test_no_thread_spawned_by_module_import` passes — thread set unchanged across `import auto_backfill_scheduler`.                                                                              |
| Status endpoint reports `scheduler_started=false`                                 | (4) `scheduler.scheduler_started: false` and `scheduler.mode: "not_wired"` both before and after the POST.                                                                                        |
| Dry-run tick spends 0 calls                                                       | (2) `test_ledger_used_count_unchanged_after_dry_run` plus (3) `spent_calls: 0` and `ledger.used: 0` in the POST response.                                                                         |
| Dry-run tick does not mutate ledger/state singletons                              | (4) Pre/post GET status snapshots are byte-equal on `state` and `ledger`. The POST's `state.last_skip_reason="disabled"` belongs to the per-request ephemeral state, not the singletons.          |
| No paid/provider seams invoked in tests                                           | (2) `test_runner_does_not_invoke_paid_stub_in_dry_run` patches `execute_paid_candidate` to a raiser and confirms it is never called. (1) Tests use `MagicMock` runners and never call the real `run_auto_backfill_dry_run` (so neither the paid stub nor any provider seam is reached). |

## FastAPI lifespan wiring is **not implemented yet**

The auto-backfill scheduler skeleton exists at module level
(`auto_backfill_scheduler.py`) and is unit-tested independently, but
nothing in `api.py` constructs or starts a live scheduler during
application startup.

`routes/diagnostics.py::_scheduler_block` documents this explicitly:

> *"The diagnostics layer never holds a live `BackgroundScheduler` —
>  the FastAPI lifespan wiring that would construct one has not
>  landed yet — so `scheduler_started` is constant False and
>  `job_count` is constant 0 until that integration arrives."*

Consequences of this gap:

- Operator panels reading `GET /diagnostics/auto-backfill-status`
  see `scheduler_started=false` and `mode="not_wired"` regardless of
  the env gates' values.
- A real auto-backfill tick is currently only observable through:
  - `POST /diagnostics/auto-backfill-dry-run` (operator-triggered, one
    shot, ephemeral state),
  - `python scripts/auto_backfill_dry_run.py [--json]` (the CLI added
    in this branch — see `docs/auto_backfill_dry_run_audit.md`),
  - the unit tests in `tests.test_auto_backfill_scheduler` and
    `tests.test_auto_backfill_runner`.
- Until the lifespan integration lands, no APScheduler thread runs in
  the FastAPI process. The only thread the auto-backfill foundation
  could spawn is one created by an explicit
  `start_auto_backfill_scheduler(...)` call, which production code does
  not make.

`auto_backfill_scheduler.py` covers what the future lifespan hook will
need (idempotent start/stop, paid-guard-respecting job registration,
exception isolation), so the integration patch should be a thin
composition rather than a behavioural change.

## Commands used

```powershell
# (1) Scheduler skeleton tests
python -m unittest tests.test_auto_backfill_scheduler -v

# (2) Runner tests
python -m unittest tests.test_auto_backfill_runner -v

# (3) and (4) — in-process FastAPI TestClient, before/POST/after sequence
python -c "
import json, sys
sys.path.insert(0, '.')
from fastapi.testclient import TestClient
import api
client = TestClient(api.app)
before = client.get('/diagnostics/auto-backfill-status').json()
post   = client.post('/diagnostics/auto-backfill-dry-run').json()
after  = client.get('/diagnostics/auto-backfill-status').json()
print('spent_calls=', post['spent_calls'],
      'selected_count=', post['selected_count'],
      'decision_reason=', post['decision_reason'])
print('singletons unchanged?',
      before['state']  == after['state']  and
      before['ledger'] == after['ledger'])
"
```

## Conclusion

All four surfaces agree on the safety contract: the scheduler module
imports without spawning a thread, the operator-triggered dry-run does
not pollute the long-lived singletons, every dry-run path records
`spent_calls=0`, and the verifying tests never reach a paid or provider
seam. The remaining integration work — wiring the scheduler skeleton
into FastAPI's `lifespan` — is a separate patch and is not in scope
here. Until it lands, `scheduler_started=false` is the canonical
operator-panel reading.
