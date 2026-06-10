# Candidate 304 paid-gate packet — DOJ v Google ad-tech

**Date:** 2026-06-10 · **Status: staged / no-paid, not promoted, paid gate
blocked by default.** This packet asks whether candidate 304 is mature enough
to be *considered* for a future, separately-approved paid analysis. It does
not run one, approve one, or move the candidate.

Reproduce read-only (safe to run repeatedly; no paid credential needed):

```powershell
python scripts/candidate_paid_gate_packet.py --candidate-id 304 --db-path events.db --json
```

## Candidate

| field | value |
|---|---|
| event_id | 304 |
| stage | `z1a_candidate_pack` (staged / no-paid) |
| date | 2023-01-24 |
| headline | Justice Department sues Google for monopolizing digital advertising technologies |
| mechanism_family | regulation |
| primary ticker | GOOGL (exposed) |
| provenance | official DOJ press release |
| shortlist position | Tier 1 (AX1/AX3; see `stats/STAGED_CANDIDATE_SHORTLIST.md`) |

Staged candidates are excluded from every accepted-corpus denominator
(coverage 94, track-record 86 — both unaffected by this packet).

## Research question

Did the 2023-01-24 DOJ ad-tech complaint reprice **structural-remedy
(divestiture) risk** on GOOGL, and did any mechanism-linked ad-tech name show
a consistent second-order reaction — as descriptive n=1 event-window evidence
for the regulation family?

## Mechanism chain

DOJ + 8 states file in the Eastern District of Virginia alleging Google
monopolizes the ad-tech stack (publisher ad server, ad exchange, advertiser
network), seeking **divestiture** — a structural remedy.

1. **First order:** legal/regulatory overhang reprices GOOGL equity (forced-
   divestiture risk on the ads business).
2. **Second order (hypotheses, not yet measurable locally):** independent
   ad-tech competitors could reprice on a prospective forced divestiture;
   META is directionally ambiguous (shared regulatory risk vs competitive
   relief); publishers/advertisers are too diffuse for an event-window read.
3. **Measured how:** 1d / 5d / 20d event windows vs SPY — descriptive n=1
   point estimates only.

## Local readout (descriptive only, n=1)

| horizon | AR vs SPY | SAR | CAR |
|---|---|---|---|
| 1d | −2.58% | −1.67 | −2.58% |
| 5d | −0.40% | −0.12 | −0.29% |
| 20d | −5.78% | −0.84 | −5.03% |

These already-computed local numbers carry no confidence interval, p-value,
or FDR; they did not rank the candidate (tiering is by research design).

## Duplicate / thread check (local data only)

- **Exact duplicates: none** (no same-date ticker/headline collision) —
  conclusion `distinct_no_exact_duplicate`.
- Family siblings: the four other staged regulation candidates
  (302/303/305/306) — different defendants/dates; listed for review, not
  duplicates.
- Keyword rows: one (`id 236`, a 2026 tech-earnings roundup mentioning
  Google) — unrelated to this complaint.
- Date-window neighbors (±10d): none.

## Asset / proxy discipline

| category | ticker | local price data | note |
|---|---|---|---|
| primary defendant | GOOGL | yes (718 rows) | named defendant; staged primary |
| possible second-order | TTD | **no** | independent ad-tech (demand side) — possible divestiture beneficiary |
| possible second-order | PUBM | **no** | independent ad-tech (sell side) |
| possible second-order | MGNI | **no** | independent ad-tech (sell side) |
| possible second-order | META | **no** | ads-scale peer; direction ambiguous |
| noisy / context | SPY | yes | benchmark only |
| noisy / context | XLK | partial | broad-tech factor context, not a mechanism asset |
| excluded | GOOG | no | same economics as GOOGL (share class) — double counting |

**Honest gap:** every second-order name currently has zero local price rows,
so none is measurable today. They are mechanism-linked hypotheses, not
accepted assets; measuring them would require a separately-approved free
cache backfill first. The map is deliberately small — an unsupported ticker
would be fake sophistication.

## Falsifiers / failure modes

- Remedy risk is too long-dated: years of litigation discount divestiture to
  roughly zero at event horizons.
- Broad tech-factor confound: Jan-2023 tape moves explain the window, not the
  complaint.
- GOOGL's move is not idiosyncratic once benchmarked.
- Second-order ad-tech proxies are small-cap and noisy.
- The market treats the lawsuit as low-probability or already priced.

## Cost / approval gate (blocked by default)

Any future paid step requires **all** of:

1. The explicit operator phrase, verbatim: *"I approve a single paid /analyze
   run for candidate 304 after a fresh verified events.db backup and a
   passing dry run."*
2. A fresh, hash-verified `events.db` backup.
3. A passing dry run.

Expected mutation scope if ever approved: one **new** analyzed events row at
the classify stage (the staged row 304 itself stays untouched and is never
auto-promoted); free cache backfills would add `price_cache` rows only.
Stop conditions: DB hash drift from the backup baseline, candidate no longer
staged, an exact duplicate appearing, any accepted-denominator change, or a
missing/paraphrased approval phrase.

## Non-claims

- No paid analysis was performed; paid `/analyze` remains blocked; nothing in
  this packet is approval.
- No promotion; no stage or `event_hygiene` change; denominators unchanged.
- A staged candidate is **not accepted evidence**.
- The readout is a descriptive n=1 point estimate — no significance, no
  causal certainty, not a recommendation to transact in anything.
- The closed Phase 1 / Phase 2 FDR pools are untouched.

## Decision

**`eligible_for_future_paid_gate_design_only`** — candidate 304 is staged,
mechanically distinct, locally readable, and carries the clearest structural-
remedy mechanism in the regulation family. That makes it eligible for paid-
gate *design* only: the gate above stays blocked until the operator phrase,
backup, and dry run all exist, and the no-paid review path (free local
evidence first) remains the default.

## Operator decision (post-review disposition)

**2026-06-10 — paid analysis deferred.** The operator reviewed this packet and
decided that candidate 304 is not worth paid analysis at this time.

- Paid `/analyze` remains **blocked**; no approval phrase is granted and no paid
  run is authorized.
- Candidate 304 remains **staged / no-paid** in `z1a_candidate_pack`; it is not
  promoted.
- No DB mutation, no promotion, and no stage or `event_hygiene` change is
  authorized; the accepted denominators (coverage 94, track-record 86) stay
  unchanged.
- This deferral does **not** retract the mechanism hypothesis or the descriptive
  n=1 readout above. It records only that the case is not worth paid spend now.
  The free, no-paid local-evidence path stays the default, and the candidate can
  be reconsidered later without re-deriving this packet.
