# Validation-Status Filter Audit

**Date:** 2026-05-05
**Scope:** verify that `/events?validation_status_v2=<status>` agrees
with `/diagnostics/validation-status-stats` on the live archive
(`./events.db`, 270 rows at audit time).
**Methodology:** zero-cost local TestClient calls.  No product code
changed.  No tests changed.  No LLM, yfinance, market_check, provider,
or DB writes performed.

## TL;DR

- **Per-row correctness:** PASS.  Every row returned by
  `/events?validation_status_v2=X` carries
  `validation_status_v2.status == X`.  Across all four statuses, **90 of
  90** rows in the default filter and **99 of 99** rows with
  `include_mock=true` matched.  Zero mismatches, zero null statuses.
- **Aggregate count agreement:** EXPECTED DIVERGENCE, not a bug.
  Diagnostic counts the full 270-row archive; `/events` first applies
  dedup, expired-low-impact suppression, and mock/demo/degraded
  suppression.  The two endpoints answer different questions and
  operate on different universes by design.
- **Confidence:** the four-label scorer is wired correctly.  Both
  endpoints call the same `validation_status.score_validation_status`
  composer — they differ only in the **set of rows** they hand it.

## How I ran the audit

All commands below are invoked from the project root.  TestClient does
NOT trigger FastAPI startup events, so `db.init_db()` must be called
manually before issuing requests.

### Setup

```python
import api, db
from fastapi.testclient import TestClient

if not db._db_ready:
    db.init_db()

c = TestClient(api.app)
```

### Diagnostic snapshot

```python
diag = c.get("/diagnostics/validation-status-stats").json()
print(diag["total_events"], diag["counts_by_status"])
```

Output captured at audit time:

```
total_events: 270
counts_by_status: {'validated': 20, 'contradicted': 48, 'unresolved': 43, 'pending': 159}
```

Sanity check vs raw archive:

```python
import sqlite3
with sqlite3.connect(db.DB_FILE) as conn:
    raw_total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    low_sig   = conn.execute("SELECT COUNT(*) FROM events WHERE low_signal=1").fetchone()[0]
print(raw_total, low_sig)
# 270 9
```

Sums match: `20 + 48 + 43 + 159 = 270` = raw row count.  The
diagnostic is partition-complete over the archive.

### Per-status filter sweep

```python
STATUSES = ("validated", "contradicted", "unresolved", "pending")

for s in STATUSES:
    r = c.get(f"/events?validation_status_v2={s}&limit=100").json()
    items = r["items"]
    matches = sum(
        1 for it in items
        if (it.get("validation_status_v2") or {}).get("status") == s
    )
    print(f"{s}: total={r['total']} returned={len(items)} match={matches}")
```

Run a second time with `&include_mock=true` appended to widen the
universe.

## Findings

### 1. Per-row status correctness (the central correctness question)

For every row returned by the filter, `validation_status_v2.status`
matches the requested filter value.  Zero mismatches, zero null
statuses, in either default or `include_mock=true` mode.

| Status | Returned (default) | Match | Wrong | None | Returned (+mock) | Match | Wrong | None |
|--------|--------------------|-------|-------|------|------------------|-------|-------|------|
| validated    | 16 | 16 | 0 | 0 | 16 | 16 | 0 | 0 |
| contradicted | 28 | 28 | 0 | 0 | 28 | 28 | 0 | 0 |
| unresolved   | 16 | 16 | 0 | 0 | 17 | 17 | 0 | 0 |
| pending      | 30 | 30 | 0 | 0 | 38 | 38 | 0 | 0 |

The brief asked for "first 5 rows" verification; I extended the check
to **every returned row** (`limit=100` exceeds the largest per-status
total seen, so the entire filtered universe is verified).  Result:
clean across the board.

Sample `validation_status_v2.reason` for the first row of each status,
to fingerprint the scorer's branches:

| Status | Reason |
|--------|--------|
| validated    | `4 supports vs 0 contradicts (5 tickers); ratio 1.00` |
| contradicted | `0 supports vs 2 contradicts (5 tickers); ratio 0.00` |
| unresolved   | `event 15d old (> 7d pending window); no directional evidence` |
| pending      | `event Nd old (<= 7d window); no directional tags yet (…)` |

These map onto the design's §4.2.1 majority rule (validated /
contradicted), §4.4 past-window backfill (unresolved), and §4.3
discriminator (pending) respectively.

### 2. Aggregate count comparison

| Status | Diagnostic | `/events` default | `/events` +mock | Δ default | Δ +mock |
|--------|-----------:|------------------:|----------------:|----------:|--------:|
| validated    |  20 | 16 | 16 |   4 |   4 |
| contradicted |  48 | 28 | 28 |  20 |  20 |
| unresolved   |  43 | 16 | 17 |  27 |  26 |
| pending      | 159 | 30 | 38 | 129 | 121 |
| **TOTAL**    | **270** | **90** | **99** | **180** | **171** |

The diagnostic counts every row in `events.db`.  `/events` shows a
strict subset.

### 3. Why the totals diverge — pre-filter pipeline in `routes/events.py`

`routes/events.py::events()` runs four read-time suppressors **before**
the `validation_status_v2` filter is applied
(`routes/events.py:582-602`):

1. `dedup_events(rows)` — collapses headline duplicates.
2. `_hr.filter_expired_low_impact(rows)` — removes registry-expired
   low-impact rows.
3. Mock / demo / degraded suppression — default-on; `include_mock=true`
   lifts the mock+demo part but the degraded carve-out remains
   (`quality=degraded` is the documented opt-in).
4. `quality` bucket filter when supplied.

The diagnostic
(`routes/diagnostics.py::_compute_validation_status_stats`) does
`SELECT * FROM events` and applies the scorer to every row — it has no
pre-filter pipeline.  The 171-row gap with `include_mock=true` is the
union of dedup victims, expired-low-impact rows, and degraded rows.

This is **scope difference, not a correctness bug**.  Both endpoints
call the same `validation_status.score_validation_status` composer; the
divergence is entirely from the row set each one passes in.

## Mismatch interpretation rubric

A genuine correctness bug would look like:

- A row returned by `/events?validation_status_v2=X` carrying a
  different `validation_status_v2.status` than `X`.  **Did not occur.**
- A `validation_status_v2` block missing from a returned row.  **Did
  not occur** (`none=0` everywhere).
- Diagnostic totals not summing to `total_events`.  Verified:
  `20 + 48 + 43 + 159 = 270 = total_events`.  **PASS.**

The observed totals divergence (270 vs 99) does not match any of these
patterns and is fully explained by the documented pre-filter pipeline.

## Recommendations

- **No code change required.**  Filter and diagnostic are both
  correct for their stated scopes.
- **Consider documenting the universe difference** in the
  diagnostic's response (e.g. add a `notes` field that says "counts
  the raw archive; `/events` applies dedup + suppression before
  filtering").  Out of scope for this audit; left for a follow-up.
- **If a strict cross-check is wanted**, expose an
  `include_suppressed=true` mode on `/events` that disables the
  pre-filter pipeline.  Then a per-status total comparison would be a
  one-line equality assertion.  Also out of scope; left for a
  follow-up.

## Reproducibility

The audit script is contained entirely in this document; no helper
modules or fixtures.  To re-run on a different snapshot:

1. `python -c "import api, db; db.init_db()"` (or rely on app startup).
2. Paste the setup block + the per-status sweep block above into a
   `python -c "..."` invocation.
3. Compare against the tables here; deltas should track changes in
   the archive's row count and the dedup/suppression hit-rate.

The audit performed no DB writes; the archive was inspected via
read-only SQL and TestClient GETs only.
