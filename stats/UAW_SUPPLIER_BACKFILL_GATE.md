# UAW supplier backfill gate — bounded LEA/APTV design for candidate 313

**Date:** 2026-06-11 · **Status: gate/design only — read-only, nothing
mutated, nothing approved. The actual backfill requires separate operator
approval and has NOT been run.**

Reproduce read-only:

```powershell
python scripts/uaw_supplier_backfill_gate.py --db-path events.db --json
python scripts/uaw_supplier_backfill_gate.py --db-path events.db
```

## Scope and denominators

Denominators unchanged: 180 archive rows · **94** accepted coverage · **86**
accepted track-record · **13** staged. Candidate 313 stays staged/no-paid and
enters no accepted denominator. Target table for any future write:
`price_cache` only. Mutation status: **not_approved**.

## Candidate 313

UAW Stand Up Strike begins against GM, Ford, and Stellantis — 2023-09-15,
`labor_inflation`, staged (`z1a_candidate_pack`), C4 anchor label
`partial_anticipation` (telegraphed deadline; windows may understate or
misplace repricing).

## Why the supplier transmission matters — and why it is not readable

The strike's mechanism chain runs OEM production halt → cancelled
just-in-time orders → supplier volume pass-through. The supplier leg
(LEA seating, APTV electrical/harness) is the part of the chain the archive
cannot currently read: C2A established that the cached LEA/APTV rows are
2026-only, so the 2023-09-15 event window has **zero pre-event coverage**.

## Current coverage (live, read-only)

| ticker | role | rows | span | pre-event dates | est. window | event window | compute-ready |
|---|---|---|---|---|---|---|---|
| GM | direct OEM | 900 | 2022-08-11..2026-06-02 | 275 | yes | yes | **yes** |
| F | direct OEM | 928 | 2022-08-11..2026-06-01 | 275 | yes | yes | **yes** |
| LEA | supplier | 174 | 2026-01-27..2026-06-01 | **0** | no | no | **no** |
| APTV | supplier | 174 | 2026-01-27..2026-06-01 | **0** | no | no | **no** |
| SPY | benchmark | 3667 | 2015-08-04..2026-06-09 | 1358 | yes | yes | yes |
| XLY | context | 1076 | 2017-07-07..2026-06-09 | 180 | yes | yes | no (non-contiguous window) |

**Rows-exist is not compute-ready.** LEA/APTV each hold 174 cached rows and
still cannot be read at this event date; XLY holds 1076 rows including 180
pre-event dates and is still blocked (`no_contiguous_aligned_window`).
Compute-readiness comes from the event-study gate itself, never from a
rows-exist flag — and forward coverage only counts **inside** the bounded
event window, so far-future rows cannot fake event-window coverage.

## What is readable now (descriptive n=1, AR vs SPY)

| leg | 1d | 5d | 20d |
|---|---|---|---|
| GM | −1.86% | −1.11% | −9.96% |
| F | −2.20% | +1.49% | −3.67% |

The intra-OEM contrast is the only readable comparison today. The supplier
legs report `not computable locally: LEA (0 pre-event dates), APTV (0
pre-event dates)`.

## Exact bounded future backfill scope (design only — NOT approved)

- **Allowed tickers:** LEA, APTV — nothing else (no STLA, no BWA, no broad
  auto-supplier sweep).
- **Allowed date range:** **2023-05-30 .. 2023-10-27**, derived from the
  cached SPY trading calendar: 60 estimation bars + 15 buffer bars before
  the event, the event day, and 20 horizon bars + 10 buffer bars after it
  (H2 lesson: size windows by trading days plus a holiday buffer).
- **Expected volume:** 106 trading bars per ticker, **212 rows max total**,
  `price_cache` only.
- **Forbidden:** any other ticker, any date outside the range, any other
  table, any schema change, any paid/billed provider endpoint, any rewrite
  of existing GM/F/SPY/XLY rows, any `/analyze` run, any promotion.

## Safety sequence required before any live mutation

1. `clean_tree_check` — clean `git status` before starting; abort otherwise.
2. `db_hash_before` — record the live events.db SHA-256.
3. `local_backup_required` — dated local backup copy (backups/ convention).
4. `temp_db_or_snapshot_preview_required` — run against a temp copy first
   and review the diff before any live touch.
5. `dry_run_expected_rows` — dry run must report ~106 inserts per ticker
   (212 max) and abort on divergence.
6. `targeted_tests_required` — this gate's suite plus the UAW packet suite
   must pass against the previewed result.
7. `live_probe_required` — after a live write, re-run the UAW packet and
   this gate; supplier legs must become compute-ready with no other change.
8. `db_hash_after_or_expected_mutation_report` — post-write SHA-256 beside
   the before-hash with the exact price_cache row delta.
9. `staged_files_check` — no DB or generated artifacts staged afterwards.

## Disposition

- **Do not backfill yet.** This packet is the gate, not the write.
- A future backfill requires **separate operator approval**; if approved, it
  may write only LEA/APTV rows inside the bounded window above.
- **No paid analysis, no promotion, no stage change.**

## How this updates C3

C3's remaining ranked move (#3, the LEA/APTV backfill **design**) is done as
a design: the gap is measured, the write is bounded, and the safety sequence
is explicit. The board's gated caveat stands — the backfill itself stays
blocked until an operator approves it through this gate.

## Non-claims

- The supplier transmission is **not computable** locally today; nothing
  here observes or implies a supplier effect, and a future backfill would
  only make the legs computable — it would not by itself show anything.
- Rows-exist is not compute-ready; the gate reports both separately.
- No DB mutation occurred; no paid analysis run or approved; no
  provider/API call made or approved; paid `/analyze` remains blocked.
- No candidate promotion, no stage/event_hygiene change; staged candidates
  are not accepted evidence; denominators (94/86) unchanged.
- All readouts are descriptive n=1 point estimates — no CI, p-value, FDR,
  significance, family-level inference, or recommendation.
- The closed Phase 1 / Phase 2 FDR pools are untouched.

## Final recommendation

Do not backfill yet. If the operator later approves it through the safety
sequence above, the write is limited to LEA/APTV daily bars in
2023-05-30..2023-10-27 (~212 rows, `price_cache` only), free path only —
no paid analysis, no promotion.
