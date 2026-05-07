# event_date Backfill — Write Mode

Status: **implemented**. The dry-run planner
(`event_date_backfill.plan_event_date_backfill`), the guarded writer
(`event_date_backfill.apply_event_date_backfill`), and the CLI
(`scripts/event_date_backfill.py`, dry-run by default,
`--write --confirm` for the writer) are all live. This document
records the safety contract the write surface satisfies.

## Why this exists

Reaction hydration is blocked for legacy rows by `no_event_date`.
Diagnosis confirmed `timestamp[:10]` is the only viable backfill
candidate — there is no other source of truth in the local archive.
The read-only candidate diagnostic
(`GET /diagnostics/event-date-backfill-candidates` and
`scripts/event_date_backfill.py`) must be reviewed and accepted before
each write run.

## Safety contract

The contract tests in
`tests/test_event_date_backfill_write_contract.py` enforce these
rules and pass green today.

1. **Both `--write` and `--confirm` required.** Plain `--write` (or
   plain `--confirm`) writes nothing and exits non-zero with a
   guidance message. `--apply` is rejected by argparse as a permanent
   typo guard.
2. **Backup + dry-run preflight required.** The operator runs
   `python scripts/backup_archive.py` and reviews a fresh dry-run
   plan before invoking write mode. CI never invokes write mode.
3. **Only NULL or empty `event_date` rows are touched.** The
   `UPDATE … WHERE event_date IS NULL OR event_date = ''` clause
   prevents re-dating any row even if a stale plan is replayed.
4. **`event_date` is set to `timestamp[:10]`.** No other source is
   consulted. `CONFIDENCE_NOTE` is carried verbatim.
5. **Malformed timestamps are skipped, not coerced.** Rows whose
   `timestamp` does not parse as ISO `YYYY-MM-DD` remain unchanged
   and are reported in `skipped_counts.timestamp_unparseable`.
6. **Idempotent rerun.** A second run on the same DB makes zero
   writes; `events` and `price_cache` stay byte-identical between the
   second and any subsequent run.
7. **No paid surfaces.** No `market_check`, `market_data`,
   `price_cache`, `yfinance`, LLM, or network call. The same patching
   pattern used by the planner tests keeps the writer green.
8. **No FastAPI route surface for writes.** Write mode lives only on
   the CLI and the module function; the read-only candidate route
   stays read-only.

## API

```python
event_date_backfill.apply_event_date_backfill(
    *, db_path: str | None = None, confirm: bool = False,
) -> dict
```

Return shape:

- `applied_count`: number of rows updated.
- `applied_updates`: list of `{event_id, timestamp,
  proposed_event_date}` ordered by `event_id` ascending.
- `skipped_counts`: same keys as the planner. When `confirm=False`
  the function returns the dry-run shape and writes nothing.
- `confidence_note`: same string as the planner.

The write path opens a single `BEGIN IMMEDIATE` transaction (so it
serialises against any concurrent uvicorn writer on the same SQLite
file) and issues one guarded `UPDATE` per proposal.

CLI:

```
python scripts/event_date_backfill.py --write --confirm [--db-path PATH]
```

Plain `--write` and plain `--confirm` are rejected; both must appear
together.

## Out of scope

- Looking up an actual event date from any source other than
  `timestamp[:10]`.
- Touching `price_cache` or running any hydration as a side effect of
  the backfill.
- Re-dating rows that already carry an `event_date`.

## Operator verification

1. `python -m unittest tests.test_event_date_backfill_write_contract -v`
2. `python scripts/no_paid_smoke.py --json`
3. `python scripts/backup_archive.py`
4. `python scripts/event_date_backfill.py` (read-only dry-run)
5. `python scripts/event_date_backfill.py --write --confirm`
6. `python scripts/event_date_backfill.py` (re-dry-run; expect
   `total_candidates` drops to zero or to the unparseable subset).
7. `Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/reaction-profile-blockers"`
   — `no_event_date` count should drop; other blocker counters
   should not move.
