# Duplicate Event Cluster Resolution

Status: **design only**.  The read-only duplicate-cluster *diagnostic*
(`routes.archive_diagnostics.compute_archive_consistency` →
`duplicate_headline_event_date_clusters`, surfaced at
`GET /diagnostics/archive-consistency`) ships and is green.  *No*
duplicate-resolution writer, planner, or CLI exists.  This document
records the safety contract any future write surface must satisfy
before it can ship.

## Why this exists

Archive-consistency surfaces clusters of ≥ 2 events sharing the same
`(headline, event_date)`.  Today the runbook escalation path is manual
SQL — the operator reviews the diagnostic, decides whether each
cluster is a true duplicate or a coincidence (two real events sharing
a title), and resolves it by hand.

A future guarded writer might land if exact-duplicate clusters become
common enough to warrant tooling.  Cluster resolution is structurally
risky (it deletes or merges archive rows), so the contract below pins
the rules the writer must satisfy *before* any code is written.  This
mirrors the precedent set by
[`docs/event_date_backfill_write_design.md`](event_date_backfill_write_design.md):
design first, contract test next, planner before writer, CLI gate
before route surface.

## Safety contract

The contract tests in
`tests/test_duplicate_event_cluster_resolution_contract.py` enforce
these rules and pass green today (the absence-pins are live; the
future-behavior pins activate when the writer ships).

1. **Read-only preview first.**  A pure SELECT-only planner —
   `duplicate_event_cluster_resolution.plan_duplicate_event_cluster_resolution`
   — must ship and run green for at least one local-demo cycle before
   any writer lands.  The planner mirrors the
   `event_date_backfill.plan_event_date_backfill` shape: candidate
   counts, proposed actions, skipped buckets, capped examples.

2. **No deletion by default.**  The default mode of any future writer
   is dry-run.  `confirm=False` (the default) returns the planner
   shape and writes nothing — no `DELETE`, no `UPDATE`, no `INSERT`.

3. **No merging until exact-duplicate criteria pass.**  A cluster is
   *exact* only when every row in the cluster shares all four:

   - same `headline` (byte-equal after `TRIM`),
   - same `event_date` (already guaranteed by how clusters are
     grouped),
   - same `market_tickers` (parsed JSON, set-equal symbol lists),
   - same `timestamp[:10]`.

   Non-exact clusters are surfaced in a `skipped_clusters` bucket and
   the writer never touches them.  Resolution of non-exact clusters
   stays a manual operator call.

4. **Preserve original rows unless explicit `--write --confirm`.**
   Plain `--write` (or plain `--confirm`) writes nothing and exits
   non-zero with a guidance message.  `--apply` is reserved as a typo
   guard.  Same gate pattern as the event_date backfill writer.

5. **Never touch `price_cache`.**  Cluster resolution is a metadata
   operation on the `events` table only.  No import of `price_cache`,
   `market_data`, `market_check`, or `yfinance` during planning or
   writing.  No cache invalidation, no hydration trigger.

6. **Never alter `market_tickers` without preview.**  The writer does
   not coerce, normalise, or union `market_tickers` lists.  If a
   cluster's rows have divergent `market_tickers` it is non-exact
   (Rule 3) and must be surfaced — not silently merged.  When the
   writer keeps one row of an exact cluster and removes the rest,
   `market_tickers` on the kept row is preserved verbatim.

7. **Keep an audit log if write mode ever lands.**  Every applied
   resolution appends one JSON line to a tamper-evident audit log
   (suggested location: `logs/duplicate_event_cluster_audit.jsonl`)
   with at minimum:

   - `applied_at` (ISO timestamp),
   - `cluster_key` (`{headline, event_date}`),
   - `kept_event_id`,
   - `removed_event_ids` (sorted ascending),
   - `applied_by` (operator label, defaulting to `$USER`).

   The audit log is append-only.  A failed apply must roll back the
   transaction *and* skip the audit append for that cluster.

8. **No FastAPI route surface for writes.**  Write mode lives only on
   the CLI (`scripts/duplicate_event_cluster_resolution.py`,
   `--write --confirm`) and the module function.  The read-only
   diagnostic at `GET /diagnostics/archive-consistency` stays
   read-only.

## API (proposed, not yet implemented)

```python
# duplicate_event_cluster_resolution.py — module-level
def plan_duplicate_event_cluster_resolution(
    *, db_path: str | None = None,
) -> dict: ...

def apply_duplicate_event_cluster_resolution(
    *, db_path: str | None = None, confirm: bool = False,
) -> dict: ...
```

Planner return shape (proposed):

- `total_clusters`               — count from the diagnostic.
- `exact_clusters`               — count meeting Rule 3.
- `proposed_resolutions`         — list of `{cluster_key,
  kept_event_id, removed_event_ids, ticker_count}` ordered by
  `kept_event_id` ascending.
- `skipped_clusters`             — list of non-exact clusters with a
  `reason` key.
- `examples`                     — capped sample of proposed
  resolutions (≤ 10).

Writer return shape (proposed): same keys plus `applied_count` and
`audit_log_path`.  When `confirm=False` the writer returns the
planner shape verbatim.

CLI:

```
python scripts/duplicate_event_cluster_resolution.py
python scripts/duplicate_event_cluster_resolution.py --write --confirm [--db-path PATH]
```

## Out of scope

- Cross-day deduplication (different `event_date` values).
- Coalescing similar-but-not-exact `market_tickers` lists.
- LLM-assisted "looks like a duplicate" judgement.
- Mover or reaction cache invalidation triggered by resolution.
- Resolving clusters in `news_clusters` (a separate domain handled by
  `db.delete_news_cluster`).

## Operator verification (when writer lands)

1. `python -m unittest tests.test_duplicate_event_cluster_resolution_contract -v`
2. `python scripts/no_paid_smoke.py --json`
3. `python scripts/backup_archive.py`
4. `python scripts/duplicate_event_cluster_resolution.py` (read-only
   preview)
5. `python scripts/duplicate_event_cluster_resolution.py --write --confirm`
6. `Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/archive-consistency"`
   — `duplicate_headline_event_date_clusters.count` should drop or
   stay zero.
