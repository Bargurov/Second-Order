# Validation Status — Design Sketch

**Status:** sketch — no schema or product code changes proposed in this document.
**Owner:** validation layer (`validation_outcome.py`, `routes/events.py`).
**Scope:** event-level status only. The per-ticker evidence vocabulary
(`supportive / mixed / contradictory / insufficient` in `validation_evidence.py`)
is a separate layer and is **not** unified by this design.

## 1. Why this exists

`score_validation_outcome(tickers)` in `validation_outcome.py` today produces
four labels: `validated`, `contradicted`, `unresolved`, `no_data`. The API
surface (`routes/events.py:317`) further collapses `no_data` into `unresolved`
so callers only ever see three.

That collapse hides two distinct situations behind a single string:

- **A fresh event** whose tickers have not yet accumulated enough tape (1d/5d
  returns are still noise) and whose `direction_tag`s have not been written.
  This event will likely resolve once time passes.
- **A low-information event** whose thesis is too vague, whose channels do not
  map, or whose tickers carry no scorable evidence. This event will not
  resolve no matter how long we wait.

Treating both as `unresolved` makes the status field misleading: the desk has
no way to tell "wait" from "give up". This sketch refines the status into
**four explicit values** so that distinction is first-class.

## 2. Status definitions (event level)

The four labels, exhaustive and mutually exclusive:

| Label | Plain reading | Decision implied |
|-------|---------------|------------------|
| `validated` | Tape supports the thesis direction. | Confidence-up. |
| `contradicted` | Tape pushes against the thesis. | Stop / re-examine. |
| `unresolved` | Tape is mixed, or the event lacks a scorable thesis, and waiting will not help. | Park / move on. |
| `pending` | Event is fresh; tape has not had time to speak. | Re-check later. |

Key invariant: **`pending` is a temporary state.** Every `pending` event is
expected to transition into one of the other three within a bounded window. An
event that is permanently undecidable is `unresolved`, never `pending`.

This refines — does not replace — the existing four-label scheme. `no_data` is
absorbed: events that previously reported `no_data` now route to either
`pending` or `unresolved` based on age and discriminator (see §4).

## 3. Inputs

Status derives from data already on the event row. **No new sources.**

- `event.market_tickers[]` — each ticker may carry `direction_tag`,
  `evidence_score`, `evidence_label`, `return_1d`, `return_5d`, `return_20d`,
  `relative_return_5d`, `volume_ratio`, `role`, `symbol`.
- `event.event_date` (preferred) or `event.timestamp` — used to derive event
  age via `event_age_policy.event_age_days`.
- `event.thesis_*` fields — used only as a discriminator for the
  pending-vs-unresolved decision (see §4.3). The status function does **not**
  re-classify the thesis; it only checks whether a thesis classification
  exists.

## 4. Decision rules

### 4.1 Determinism becomes time-aware

The signature changes from
`score_validation_outcome(tickers) -> (label, ratio)` to
`score_validation_status(event, *, now=None) -> (label, ratio, reason)`.

- Takes the **whole event** (not just tickers) so it can read `event_date` and
  the thesis discriminator.
- Takes an explicit `now` kwarg (default `datetime.now()`) so the function
  stays pure and unit-testable. **No hidden clock reads inside the function.**
- Returns a `reason` string for observability — short, human-readable, e.g.
  `"hot event (0d old) with 1 directional ticker; pending"`.

Callers that already use `score_validation_outcome` continue to work via a thin
shim that defaults `now` and discards `reason`.

### 4.2 Resolution order

Compute in this order; the first rule that fires wins:

1. **Existing majority rule** (unchanged) over directional `direction_tag`s:
   - `supporting > contradicting` → `validated`
   - `contradicting >= supporting` and at least one of each → `contradicted`
   - all-tied or all-neutral → continue.
2. **No directional evidence yet:**
   - If `event_age_days <= PENDING_MAX_DAYS` → `pending`.
   - Else → `unresolved` (but see §4.3 for the discriminator that promotes
     "would never resolve" cases out of pending early).

### 4.3 The `pending` vs `unresolved` discriminator

A young event with no directional tags is `pending` **only if** at least one
of these is true:

- The event has a thesis classification (`thesis_*` fields populated, thesis
  classifier did not return null/insufficient).
- At least one ticker carries a `role` (`beneficiary` / `loser`) — the
  classifier had enough to assign sides, even if the tape has not confirmed.
- At least one ticker carries 1d return data (the price-cache pipeline ran;
  the issue is just that 1d returns are below the noise floor).

If none of these hold, the event is `unresolved` regardless of age — no amount
of waiting will give the validation layer something to score.

### 4.4 Pending window

Initial proposal: **`PENDING_MAX_DAYS = _WARM_MAX_DAYS` (7 days)**.

Rationale: the per-ticker evidence weights in `validation_evidence.py` lean
hardest on 5d returns (`_W_5D = 0.40`); the 5d horizon needs a full trading
week before its noise floor (`_NOISE_5D_PCT = 1.0`) is meaningfully crossable.
At the `hot` boundary (≤1d) the dominant horizon has not had time to speak;
at the `warm` boundary (≤7d) it has.

Reuse `event_age_policy._WARM_MAX_DAYS` rather than introducing a new
constant; if calibration later wants a different boundary, it gets pinned in
`validation_outcome.py` with a comment explaining the divergence.

### 4.5 State monotonicity

Resolution is **one-way**: once an event has been `validated`, `contradicted`,
or `unresolved`, it does not revert to `pending`, even if a later recompute
sees the directional tags vanish (rare, but possible if a re-classification
clears tags).

Implementation note (for the future implementation, not this sketch): the
status function is a pure read; monotonicity is enforced by the caller that
persists the result, comparing against the prior persisted status before
overwriting. The function itself returns whatever the inputs imply.

## 5. Edge cases — explicit mapping

| Situation | Inputs | Status | Why |
|-----------|--------|--------|-----|
| No tickers at all, fresh event with thesis | `market_tickers=[]`, `age=0d`, thesis present | `pending` | Pipeline may still attach tickers. |
| No tickers at all, fresh event without thesis | `market_tickers=[]`, `age=0d`, no thesis | `unresolved` | No path to evidence. |
| No tickers at all, archived event | `market_tickers=[]`, `age=60d` | `unresolved` | Past the pending window; backfill will not help. |
| Tickers exist, no `direction_tag` anywhere, fresh | tickers present, no tags, `age<=7d`, role/1d data present | `pending` | Tag classifier has not run; wait. |
| Tickers exist, no `direction_tag`, fresh, no role/1d | tickers present, no tags, no role, no 1d returns | `unresolved` | Even with time, classifiers have nothing to chew on. |
| Tickers exist, no `direction_tag`, archived | `age>7d`, no tags | `unresolved` | Past the window. |
| Mixed ticker evidence, supports > contradicts | mixed tags, `supports=3, contradicts=1` | `validated` | Existing majority rule. |
| Mixed ticker evidence, supports == contradicts | tied tags, e.g. `supports=2, contradicts=2` | `contradicted` | Existing rule (ties go to `contradicted`; preserved verbatim). |
| Mixed ticker evidence, supports < contradicts | `supports=1, contradicts=3` | `contradicted` | Existing rule. |
| All tags neutral / unknown prefix | tags present but none `supports*`/`contradicts*` | `unresolved` | Tag classifier ran and abstained — not a wait condition. |
| Low-information event (vague thesis) | thesis classifier returned null | `unresolved` | Discriminator §4.3 promotes out of pending. |
| Future-dated event (anchor in the future) | `event_age_days = 0` (clamped) | per pending rules | `event_age_policy` already clamps; treated as `age=0`. |
| Missing/unparsable `event_date` and `timestamp` | classified `legacy` by `event_age_policy` | `unresolved` | Cannot evaluate the pending window without an anchor; do not optimistically pending. |

## 6. Backfill semantics

A backfill job that recomputes status for historical events **must never emit
`pending`** for any row whose `event_age_days > PENDING_MAX_DAYS`. The
`pending` label is forward-looking; an archived row that would have been
pending at the time is now `unresolved`.

Backfill ordering, when it lands:

1. Read each event's tickers + age at time of backfill (i.e. `now = current
   real time`, not the event date).
2. Apply §4.2 / §4.3 unchanged. Age cutoff falls out automatically — old rows
   skip the pending branch.
3. Persist via the same monotonicity-respecting writer as the live path; do
   not overwrite an existing terminal status with `pending`.
4. Emit a count by transitioned-from / transitioned-to so the diff against the
   pre-backfill distribution is auditable. Expected diff: `no_data` (or
   `unresolved`-from-`no_data`) reduces, `pending` count is approximately the
   number of `hot`/`warm` events with a thesis but no directional tags yet.

The backfill should be a one-shot script (analogous to `scripts/rebuild_archive.py`),
not a recurring job — once the live path emits the four-label vocabulary,
backfill is only needed for the initial cutover.

## 7. Tests required before implementation

These test cases must exist (and fail against the current implementation)
before the schema or endpoint change ships.

### 7.1 Pure-function unit tests (extend `tests/test_audit_blockers.py` or new file)

For each row in §5, a fixture asserting `(label, reason)` matches.
Fixtures are dict literals — no DB, no network.

### 7.2 Time-awareness tests

- `now` parameter is honoured: same event, two different `now`s, assert the
  status flips from `pending` (younger `now`) to `unresolved` (older `now`)
  when no tags exist.
- Default `now` (omitted kwarg) does not raise and produces a status
  consistent with the system clock.
- Future-dated event (event_date > now) — assert no exception, treat as fresh.

### 7.3 Transition tests

These guard the state-machine, not the pure function.

- `pending` → `validated` when directional tags appear.
- `pending` → `contradicted` when directional tags appear with majority
  contradicting.
- `pending` → `unresolved` when the pending window expires (advance `now`
  past `PENDING_MAX_DAYS` with no tags).
- `pending` → `pending` (stable) when `now` advances but stays inside the
  window.
- Once `validated`/`contradicted`/`unresolved` is reached, a subsequent
  recompute that would yield `pending` is rejected by the persistence layer
  (assert no overwrite to `pending`).

### 7.4 Discriminator tests

- Empty tickers + thesis present + fresh → `pending`.
- Empty tickers + thesis missing + fresh → `unresolved`.
- Tickers with role + no tags + fresh → `pending`.
- Tickers without role + no tags + no 1d returns + fresh → `unresolved`.

### 7.5 Backfill tests

- Backfill on a fixture archive: assert no row past `PENDING_MAX_DAYS` emerges
  as `pending`.
- Backfill that would emit `pending` against a row already persisted as
  `validated`: assert the persisted value is preserved (monotonicity).
- Backfill counters: assert the per-label transition counts match a
  hand-computed expectation on a small fixture set.

### 7.6 API contract tests (extend `tests/test_events_archive_detail_consistency.py`)

- The `validated` query parameter on `/events` accepts `pending` in addition
  to the existing three values.
- Filter `?validated=pending` returns only `pending` rows.
- The `validation_status` field in event-detail responses is one of the four
  documented values; never `no_data`, never null, never any other string.
- Counts in any list-endpoint summary block sum to total rows (no row is
  silently double-counted or dropped).

## 8. Out of scope (intentionally)

- Schema migrations. The status string is stored in whatever column already
  holds `validation_status`; widening the allowed values is not a schema
  change.
- Endpoint shape changes beyond accepting `pending` in the existing filter.
- Per-ticker evidence vocabulary changes — `validation_evidence.py` stays
  exactly as it is.
- Unifying event-level status with per-ticker evidence labels — these are
  distinct layers (per-ticker = "did this name's tape move?"; event-level =
  "did the basket of names support the thesis?") and conflating them would
  obscure the per-ticker reads the desk uses to debug an event-level call.
- Calibrating `PENDING_MAX_DAYS`. The 7-day reuse of `_WARM_MAX_DAYS` is a
  defensible starting point; tuning waits until the live path has emitted the
  new vocabulary for long enough that the bucket-distribution diff is real
  data instead of a guess.

## 9. Open questions

- **Should `pending` show in the validation-status filter dropdown by
  default, or only when explicitly toggled?** Argument for default-visible:
  the desk wants to see what's still cooking. Argument for default-hidden:
  pending events are noise during retrospective review. Defer to product
  signal once the label exists in the archive.
- **What's the right `reason` string format?** First implementation should
  match the style of `event_age_policy.classify_event_age`'s `reason` field
  for consistency, but the exact phrasing is a UI concern, not a status-layer
  concern.
