# G5 promotion proof (Mission G, g0-v1)

Status: temp-DB promotion proof and controlled live promotion record.
Promotion version `g5-promotion-v1`. This slice promoted the 97 frozen
Mission G historical candidates into the shared storage substrate
(`events.db`) under the one-substrate / separate-denominator-ledgers rule
(protocol section 2), leaving the existing accepted track record and every
pre-existing row untouched. No outcome value was read, computed, stored,
or displayed anywhere in the path; no price was fetched; no paid call was
made.

## 1. Storage design (smallest additive implementation)

One new dedicated table `g_historical_evidence` inside `events.db` - the
same live workbench substrate - with the denominator ledger carried as a
lineage field on every row (per the protocol: lineage fields, not physical
location, determine the one ledger a row counts in). The table enters no
existing query path: stage-driven surfaces, the accepted denominators,
`event_hygiene`, and every other pre-existing table are never written and
never read for writing. The `events` table is consulted READ-ONLY by the
ledger-precedence collision gate. The existing analysis-shaped `events`
schema was deliberately NOT reused for candidate rows: G candidates carry
no analysis fields, and stage-driven surfaces must never render them (the
Z1D staging lesson).

Row contents (exact column whitelist, schema-enforced): candidate id;
denominator ledger (frame_complete_historical / designed_contrast, CHECK
constraint); sampling family (fomc / opec); source/discovery provenance
(JSON: G1A frame reference with `frame_member` selection, or G1B reservoir
`opec-production-policy-reservoir-2018-2025@v1` with
`designed_recruitment (g4-designed-recruitment-v1)` selection); event
date (UNIQUE); conservative cutoff; frozen transmission mapping + version;
G4 freeze version; the four primary point-in-time state values (NOT NULL);
the secondary credit value (nullable) with explicit availability
(`available` / `source_missing`); and the three frozen G4 tags (CHECK
constraints). No outcome-shaped column and no mechanism-taxonomy column
exists; the G3B J1 classification is not stored in any form.

Promotion invariants (all enforced in one transaction, full rollback on
any failure, tested): whitelisted keys only with outcome-shaped and
mechanism-shaped keys rejected; ledger must equal the family's ledger
(frame rows cannot enter the designed ledger and vice versa); assets and
mapping version must equal the frozen `g3-transmission-map-v1` map;
complete primary state vector required; credit availability must match
value presence; tag values must equal the frozen sign rules applied to the
stored state (recomputed at insert); duplicate ids/dates rejected; an
existing promoted row that differs from its incoming row raises rather
than updates; a live-events identity collision (same event date + family
identity pattern, ledger precedence rule 1) halts the entire promotion.

## 2. Temp-DB proof (mandatory, ran first)

A byte-identical copy of the live DB (SHA256
`18aa372e791e98a8adf5a87c2da6f8131bfd4750a1d29c7a1ad11c137c0f6b1f`,
verified after copy) was created OUTSIDE tracked repository state and the
full promotion path ran against it:

| invariant | result |
|---|---|
| pre-existing tables changed | none (canonical per-table dump hashes identical for all 14 pre-existing tables) |
| accepted track record before -> after | 86 -> 86 |
| pre-existing rows updated | 0 (dump-hash proof) |
| promoted | 97 (inserted 97, already-present 0) |
| frame ledger | 65 |
| designed ledger | 32 |
| unique candidate ids / event dates | 97 / 97 |
| one ledger per identity | yes (single NOT NULL CHECK column; partition verified) |
| collisions | 0 (gate passed; a hit would have halted everything) |
| idempotent rerun | inserted 0, already-present 97 |
| primary state coverage | 97/97 on all four dimensions |
| credit | 36 available / 61 source_missing |
| tag occupancy | fed easing/hold/tightening 29/33/35; spy below/above 23/74; curve inverted/non 26/71 (exactly the G4 freeze) |
| FOMC mapping | 65 x KRE/SPY/XLF |
| OPEC mapping | 32 x XOP/SPY/XLE |
| mapping / freeze versions | `g3-transmission-map-v1` x97, `g4-structural-freeze-v1` x97 |
| response values stored | none (schema carries no such column) |
| accepted-stage contamination | none (no write touches `events` or any stage) |

Verdict: PASS on every invariant; live promotion authorized.

## 3. Controlled live promotion

- Safety snapshot: byte-identical copy of `events.db` stored outside
  tracked repository state, hash-verified equal to the live pre-mutation
  hash before promotion ran.
- Pre-mutation live hash:
  `18aa372e791e98a8adf5a87c2da6f8131bfd4750a1d29c7a1ad11c137c0f6b1f`
- The SAME tested path (identical code, identical input builder) ran
  against `events.db` in one transaction; no manual row patch of any kind.
- Result: identical to the temp proof on every invariant in section 2
  (inserted 97; idempotence rerun inserted 0; accepted 86 -> 86; all 14
  pre-existing tables dump-hash identical; verification battery equal).
- Post-mutation live hash:
  `18aa1b7004a36270d2b61a80f3bfed629b7746e5931039fcac5c448974811964`
- Root `price_cache.db` untouched and still the empty file
  (`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`).
- An independent read-only probe (`--verify`) against the live DB
  re-confirmed: 97 promoted, 65/32 ledgers, accepted 86, credit 36/61,
  primary coverage 97/97, unique ids/dates 97/97.

Rollback/safety procedure: the pre-mutation snapshot
(`g5_pre_promotion_snapshot_18aa372e.db`, session scratchpad, untracked)
restores the exact prior state by file replacement with the application
stopped; the recorded pre-mutation hash verifies the restore. The
promotion itself rolls back automatically inside its transaction on any
error (tested, including mid-batch failure).

## 4. Ledger isolation and immutability evidence

- The accepted track record reproduces as 86 before and after (accepted
  stages minus `event_hygiene` synthetic-seed overrides - the shipped
  definition).
- Canonical per-table dump hashes over all pre-existing tables (events,
  event_hygiene, event_provenance, curated_candidates, price_cache table,
  news/headline tables, and the rest) are IDENTICAL before and after both
  runs: no pre-existing row was inserted, updated, or deleted anywhere.
- Promoted rows are distinguishable by construction: dedicated table, NOT
  NULL ledger column restricted to the two historical ledgers. They cannot
  silently join the accepted 86, any accepted-stage pool, any
  representative-case set, or any closed FDR pool: no existing reader
  selects from `g_historical_evidence`, and the accepted denominator
  definition references stages and hygiene overrides that promoted rows do
  not have.
- Ledger precedence: rule 1 (live) is enforced by the collision gate
  (zero hits on the real data, consistent with the G1B collision audit -
  every FOMC/OPEC-keyword row in the archive is 2026-dated or synthetic);
  rules 2-3 are enforced by the family->ledger CHECK and validation.

## 5. Verification battery

- `tests/test_g5_promotion.py`: 23 tests - fixture mechanics (insert,
  partition, idempotence, tamper-raise, mid-batch rollback, dump-hash
  immutability, accepted-count invariance), validation rejections (ledger
  crossing both directions, mapping drift, mapping-version drift, null
  primary state, credit-availability mismatch, tag/state inconsistency,
  outcome-shaped key, mechanism-taxonomy key, live collision halt, schema
  column whitelist), and live-input reconciliation (97 = 65 + 32, unique
  ids/dates, credit 36/61, primary 97/97, tag occupancy equal to the G4
  freeze recomputation, transmission map equal to G3A, validators pass).
- Reused-contract suites re-run green beside it: G2 state acquisition
  (38), G4 structural freeze (30), G3A grinder + G3B classification (67).
- Outcome-field firewall: the schema whitelist test plus key-token
  rejection tests; the verification probe output contains counts and
  metadata only.
- No DB, snapshot, cache, JSON, or CSV file is staged or committed; the
  mutated `events.db` and the safety snapshot remain untracked.

## 6. Non-claims

- Promotion stores candidate identity, provenance, mapping, state, and
  tags - it computes and stores NO market response of any kind (no
  abnormal return, no standardized value, no outcome label, no sign, no
  magnitude); G6 outcome work remains a separate, later slice under the
  frozen manifest.
- No prevalence claim attaches to either promoted ledger; the designed
  lane remains recruited evidence under its explicit non-prevalence claim.
- The accepted 86 remain a separate, immutable lineage; nothing here
  merges, reweights, or reinterprets them.
- The closed Phase 1 / Phase 2 FDR pools stay closed; promoted rows never
  enter them.
- Not a trading, prediction, or recommendation surface.

## 7. Reproduction

```
python -m unittest tests.test_g5_promotion
python scripts/g5_promotion.py --verify            # read-only live probe
python scripts/g5_promotion.py --temp-proof COPY   # full proof on a copy
```
