# Auto-Backfill Dry-Run Result Audit

This audit confirms that the three zero-cost surfaces of the auto-backfill
foundation — the CLI, the operator-triggered POST route, and the
read-only GET status route — agree with each other and uphold the
no-paid-spend contract under the default disabled environment.

The audit also demonstrates the runner's behaviour when both env gates are
flipped on inside a test-scoped probe (no real env mutation).

- Audit date: 2026-05-06
- Working directory: `C:\Users\Bar\desktop\geo_mechanism_project`
- Branch: `main`
- Environment: defaults — `ENABLE_AUTO_BACKFILL` and `ENABLE_PAID_ANALYSIS`
  unset; `AUTO_BACKFILL_*` caps not exported. The loader falls back to the
  documented defaults (interval 6h, 3/run, 12/day, model
  `claude-haiku-4-5-20251001`).

## Surfaces compared

| # | Command                                            | Owner module                                                        |
|---|----------------------------------------------------|---------------------------------------------------------------------|
| 1 | `python scripts/auto_backfill_dry_run.py --json`   | `scripts/auto_backfill_dry_run.py`                                  |
| 2 | `POST /diagnostics/auto-backfill-dry-run`          | `routes/diagnostics.py::auto_backfill_dry_run`                      |
| 3 | `GET /diagnostics/auto-backfill-status`            | `routes/diagnostics.py::auto_backfill_status`                       |

(1) and (2) both compose `auto_backfill_runner.run_auto_backfill_dry_run`
over a freshly-built `AutoBackfillState` + `AutoBackfillLedger`, so neither
surface mutates persistent state. (3) reads the long-lived per-process
singletons backing the operator panel.

## 1. CLI — `python scripts/auto_backfill_dry_run.py --json`

```json
{
  "config": {
    "effective_status": "disabled",
    "enabled": false,
    "interval_hours": 6,
    "max_calls_per_day": 12,
    "max_calls_per_run": 3,
    "model": "claude-haiku-4-5-20251001",
    "paid_analysis_enabled": false
  },
  "considered_count": 0,
  "daily_remaining": 12,
  "decision_reason": "disabled",
  "effective_per_run_cap": 3,
  "effective_status": "disabled",
  "eligible_count": 0,
  "now": "2026-05-06T04:36:14.714411+00:00",
  "ok": true,
  "selected": [],
  "selected_count": 0,
  "skip_counts": {},
  "skip_reason": "disabled",
  "skip_reasons": {}
}
```

The CLI short-circuits the candidate loader when `enabled` and
`paid_analysis_enabled` are both false, so `routes.diagnostics.registry_candidate_queue`
is never imported on this path. `considered_count` is therefore 0.

## 2. POST `/diagnostics/auto-backfill-dry-run`

Captured via in-process `fastapi.testclient.TestClient(api.app)`:

```python
from fastapi.testclient import TestClient
import api
TestClient(api.app).post('/diagnostics/auto-backfill-dry-run')
```

Response (HTTP 200):

```json
{
  "available": true,
  "candidate_queue_counts": {
    "already_analyzed": 0,
    "eligible": 0,
    "expired_low_impact": 0,
    "skipped": 0
  },
  "candidates_considered": 0,
  "completed": false,
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
  "decision_reason": "disabled",
  "effective_call_cap": 0,
  "eligible_count": 0,
  "filters": {
    "include_low_signal": false,
    "since_hours": 72
  },
  "ledger": {
    "daily_cap": 12,
    "day": "2026-05-06",
    "remaining": 12,
    "used": 0
  },
  "news_source": "none",
  "now": "2026-05-06T04:36:20.058390+00:00",
  "run_id": null,
  "selected": [],
  "selected_count": 0,
  "skip_counts": {},
  "skip_reason": "disabled",
  "skip_reasons": {},
  "spent_calls": 0,
  "started": false,
  "state": {
    "last_completed_at": null,
    "last_error": null,
    "last_run_id": null,
    "last_selected_count": null,
    "last_skip_reason": "disabled",
    "last_spent_calls": null,
    "last_started_at": null,
    "lock_acquired_at": null,
    "lock_expires_at": null,
    "lock_held": false,
    "lock_owner": null
  }
}
```

`state.last_skip_reason="disabled"` here is on the **ephemeral**
`AutoBackfillState` constructed inside `_compose_auto_backfill_dry_run`
and discarded after the response is built. It does not leak into the
singleton consumed by the status endpoint — see §3.

## 3. GET `/diagnostics/auto-backfill-status`

Captured immediately after the POST above, against the same
`TestClient`:

```python
TestClient(api.app).get('/diagnostics/auto-backfill-status')
```

Response (HTTP 200):

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

`last_skip_reason` is `null` here even though the POST in §2 stamped
`"disabled"` on its ephemeral state — the dry-run route does not
contaminate the long-lived singletons.

## Cross-surface agreement

| Field                                    | (1) CLI         | (2) POST dry-run  | (3) GET status   |
|------------------------------------------|-----------------|-------------------|------------------|
| `config.effective_status`                | `disabled`      | `disabled`        | `disabled`       |
| `config.enabled`                         | `false`         | `false`           | `false`          |
| `config.paid_analysis_enabled`           | `false`         | `false`           | `false`          |
| `config.interval_hours`                  | `6`             | `6`               | `6`              |
| `config.max_calls_per_run`               | `3`             | `3`               | `3`              |
| `config.max_calls_per_day`               | `12`            | `12`              | `12`             |
| `config.model`                           | `claude-haiku-4-5-20251001` | same  | same             |
| `decision_reason`                        | `disabled`      | `disabled`        | n/a (read-only)  |
| `selected_count`                         | `0`             | `0`               | n/a              |
| `selected` (list length)                 | `0`             | `0`               | n/a              |
| `skip_reason`                            | `disabled`      | `disabled`        | n/a              |
| `spent_calls`                            | n/a*           | `0`               | n/a              |
| `ledger.used`                            | n/a (CLI surfaces `daily_remaining=12`) | `0`               | `0`              |
| `ledger.remaining`                       | `12`            | `12`              | `12`             |
| `ledger.daily_cap`                       | n/a (carries `max_calls_per_day=12`) | `12` | `12`             |
| `state.lock_held`                        | n/a             | `false`           | `false`          |

\* The CLI surfaces `spent_calls` indirectly via `selected_count=0`. The
runner records `spent_calls=0` on every dry-run path; the CLI reflects
this through the empty `selected` array and unchanged `daily_remaining`.

## Safety assertions confirmed by the captured outputs

| Assertion                                                 | Evidence                                                                                                                                          |
|-----------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------|
| No calls reserved by any surface                          | `ledger.used=0` and `ledger.remaining=12` on both (2) and (3); CLI reports `daily_remaining=12` matching the configured `max_calls_per_day=12`.   |
| `spent_calls=0`                                           | (2) explicit `spent_calls: 0`; the runner contract pins this on every dry-run path (`auto_backfill_runner.RunResult.spent_calls`).                |
| Scheduler not started                                     | No `BackgroundScheduler` / `AsyncIOScheduler` instantiated by project code (only present in `.venv` site-packages); `state.lock_held=false`.      |
| `selected_count=0` under disabled config                  | (1) and (2) both return `selected_count: 0` and an empty `selected` list. The disabled decision short-circuits before planning runs.              |
| Dry-run does not contaminate the status singletons        | Compare (2) `state.last_skip_reason: "disabled"` (ephemeral) with (3) `state.last_skip_reason: null` (singleton, same TestClient session).        |

## What changes when env gates are enabled (test-only probe)

This probe builds an `AutoBackfillConfig` from an injected env mapping —
real `os.environ` is untouched. No paid call is made; the candidate set
is synthetic and the runner is the same dry-run path the CLI and POST
route call.

```python
from auto_backfill_config import load_auto_backfill_config
from auto_backfill_ledger  import AutoBackfillLedger
from auto_backfill_state   import AutoBackfillState
from auto_backfill_runner  import run_auto_backfill_dry_run

cfg = load_auto_backfill_config(env={
    'ENABLE_AUTO_BACKFILL':                'true',
    'ENABLE_PAID_ANALYSIS':                 'true',
    'AUTO_BACKFILL_INTERVAL_HOURS':         '6',
    'AUTO_BACKFILL_MAX_LLM_CALLS_PER_RUN':  '3',
    'AUTO_BACKFILL_MAX_LLM_CALLS_PER_DAY':  '12',
})
candidates = [
    {'headline': f'Synthetic cluster #{i}',
     'rank_score': 10.0 - i, 'source_count': 3 - (i % 3),
     'published_at': '2026-05-05T11:00:00+00:00',
     'registry_state': 'eligible', 'skip_reason': None}
    for i in range(5)
]
ledger = AutoBackfillLedger(daily_cap=cfg.max_calls_per_day)
state  = AutoBackfillState(ttl_seconds=3600)
result = run_auto_backfill_dry_run(
    candidates=candidates, config=cfg, state=state, ledger=ledger,
)
```

Captured result:

```
config.effective_status      = configured
config.enabled               = True
config.paid_analysis_enabled = True

decision_reason              = configured
started                      = True
completed                    = True
skip_reason                  = None
selected_count               = 3
spent_calls                  = 0
plan.effective_call_cap      = 3
plan.considered_count        = 5
plan.eligible_count          = 5
selected headlines           = ['Synthetic cluster #0',
                                'Synthetic cluster #1',
                                'Synthetic cluster #2']

ledger.used (after runner)   = 0
ledger.remaining (after)     = 12
```

### Deltas vs the disabled baseline

| Field                  | Disabled (real env) | Configured (test-only env) |
|------------------------|---------------------|----------------------------|
| `effective_status`     | `disabled`          | `configured`               |
| `decision_reason`      | `disabled`          | `configured`               |
| `started` / `completed`| `false` / `false`   | `true` / `true`            |
| `skip_reason`          | `disabled`          | `null`                     |
| `selected_count`       | `0`                 | `3` (capped at `max_calls_per_run`) |
| `effective_call_cap`   | `0`                 | `3`                        |
| `considered_count`     | `0`                 | `5`                        |
| `spent_calls`          | `0`                 | `0` (unchanged — dry-run)  |
| `ledger.used`          | `0`                 | `0` (unchanged — dry-run)  |
| `ledger.remaining`     | `12`                | `12` (unchanged — dry-run) |

The two load-bearing safety properties — `spent_calls=0` and ledger
unchanged — hold both with the gates off and with the gates on. Flipping
the env gates only changes the planner's selection surface; it does not
authorise paid execution. Paid execution would require replacing
`auto_backfill_runner.execute_paid_candidate` (currently raises
`NotImplementedError`) and adding a scheduler, neither of which exists
in this branch.

## Commands used

```powershell
# (1) CLI
python scripts/auto_backfill_dry_run.py --json

# (2) and (3) — in-process FastAPI TestClient
python -c "
import json, sys
sys.path.insert(0, '.')
from fastapi.testclient import TestClient
import api
client = TestClient(api.app)
print(json.dumps(client.post('/diagnostics/auto-backfill-dry-run').json(),
                 indent=2, sort_keys=True))
print(json.dumps(client.get('/diagnostics/auto-backfill-status').json(),
                 indent=2, sort_keys=True))
"

# Test-only env-gates-on probe (no real env mutation)
python -c "
import sys
sys.path.insert(0, '.')
from auto_backfill_config import load_auto_backfill_config
from auto_backfill_ledger  import AutoBackfillLedger
from auto_backfill_state   import AutoBackfillState
from auto_backfill_runner  import run_auto_backfill_dry_run

cfg = load_auto_backfill_config(env={
    'ENABLE_AUTO_BACKFILL': 'true',
    'ENABLE_PAID_ANALYSIS': 'true',
})
candidates = [
    {'headline': f'Synthetic cluster #{i}', 'rank_score': 10.0 - i,
     'source_count': 3, 'published_at': '2026-05-05T11:00:00+00:00',
     'registry_state': 'eligible', 'skip_reason': None}
    for i in range(5)
]
ledger = AutoBackfillLedger(daily_cap=cfg.max_calls_per_day)
state  = AutoBackfillState(ttl_seconds=3600)
result = run_auto_backfill_dry_run(
    candidates=candidates, config=cfg, state=state, ledger=ledger,
)
print('selected_count =', result.selected_count,
      'spent_calls =', result.spent_calls,
      'ledger.used =', ledger.snapshot().used)
"

# Repeatable test coverage
python -m unittest tests.test_auto_backfill_dry_run_cli -v
python -m unittest tests.test_auto_backfill_runner -v
python -m unittest tests.test_diagnostics -v
```

## Conclusion

All three zero-cost surfaces agree on the disabled-config view, the
ledger remains untouched on every path, `spent_calls` is zero across the
board, and no scheduler is started by importing or invoking any of these
endpoints. The dry-run route uses ephemeral state, so repeated hits do
not pollute the operator-panel singletons exposed by
`/diagnostics/auto-backfill-status`. Flipping the env gates in a
test-scoped probe surfaces the planner's selection without changing any
of the safety properties.
