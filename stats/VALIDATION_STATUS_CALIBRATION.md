# Validation-status evidence-floor calibration (read-only)

Contract: `validation-status-calibration-v1`. This report calibrates the production event-level rule `validation_status.score_validation_status` (the `validation_status_v2` label) against the real archive. It reuses the production scorer verbatim for the current-rule column, changes no production behaviour or label, and reads the database over a `mode=ro` connection only.

- source database: `events.db`
- database sha256: `c9bb5a3219511a1112b55f4264c42038412a7840a182d6184f75cb320b21c846`
- database unchanged during run: True (sha256 after: `c9bb5a3219511a1112b55f4264c42038412a7840a182d6184f75cb320b21c846`)
- note: the snapshot sha is a whole-file hash covering volatile non-research tables (news / market caches) that mutate independently of the archive; it is a same-run safety proof, not a reproduction key — reproduce via the accepted denominator and funnel below, never the whole-file hash.
- as-of: 2026-07-11
- decisive labels (validated/contradicted) are age-invariant; only pending vs unresolved on no-directional rows depends on as-of

## 1. Eligibility and denominators

Primary lens: the accepted track-record population — every `events` row whose `stage` is not in `db.NON_THESIS_STAGES` and whose id is not an `event_hygiene` `synthetic_seed`. This is the established accepted denominator, reproduced so the report reconciles with `routes/diagnostics.py::_compute_validation_status_stats`. Accepted (86-style) and raw analysis-stage lenses are separate columns and are never summed. The accepted set is 'archive minus non-thesis stages minus override-flagged synthetic seeds' — not 'all real events'.

## 2. Missingness funnel

- total archive rows: 180
- excluded — non-thesis stage: 23
- excluded — synthetic seed: 71
- accepted (primary denominator): 86
- reconciliation: 86 + 23 + 71 = 180

Within the 86 accepted rows:
- with thesis information: 86
- with market tickers: 73
- with directional ticker tags: 65
- with no directional evidence: 21

Secondary raw/analysis-stage lens (separate, never summed): 94 rows.

## 3. Current-rule status distribution (accepted lens)

- validated 24 (27.91%); contradicted 41 (47.67%); unresolved 21 (24.42%)

## 4. Directional-evidence-count distribution (accepted lens)

- 0 directional ticker(s): 21 events
- 1 directional ticker(s): 3 events
- 2 directional ticker(s): 12 events
- 3 directional ticker(s): 14 events
- 4 directional ticker(s): 14 events
- 5 directional ticker(s): 11 events
- 6 directional ticker(s): 10 events
- 7 directional ticker(s): 1 events

### Decisive labels by directional-evidence count (the crux)

- decisive labels total: 65
- resting on exactly 1 directional ticker: 1 validated + 2 contradicted = 3 (4.6% of decisive labels)
- resting on exactly 2 directional tickers: 9 validated + 3 contradicted
- resting on 3+ directional tickers: 14 validated + 36 contradicted
- decisive labels resting on an exact tie (supports == contradicts): 5

## 5. Observed (supporting, contradicting) combinations (accepted lens)

- supports 0, contradicts 0: 21
- supports 2, contradicts 0: 9
- supports 1, contradicts 2: 6
- supports 1, contradicts 3: 5
- supports 1, contradicts 5: 5
- supports 2, contradicts 3: 4
- supports 0, contradicts 3: 3
- supports 2, contradicts 2: 3
- supports 3, contradicts 0: 3
- supports 3, contradicts 1: 3
- supports 0, contradicts 1: 2
- supports 0, contradicts 2: 2
- supports 0, contradicts 4: 2
- supports 0, contradicts 5: 2
- supports 1, contradicts 4: 2
- supports 2, contradicts 1: 2
- supports 3, contradicts 2: 2
- supports 4, contradicts 2: 2
- supports 0, contradicts 6: 1
- supports 1, contradicts 0: 1
- supports 1, contradicts 1: 1
- supports 1, contradicts 6: 1
- supports 2, contradicts 4: 1
- supports 3, contradicts 3: 1
- supports 4, contradicts 0: 1
- supports 5, contradicts 0: 1

## 6. Candidate rules and transition matrices (accepted lens)

Each candidate holds the non-directional branch fixed, so every reported change is attributable to the evidence-floor rule alone.

### current — Current rule (majority; ties -> contradicted; floor 1)
- empirical basis: the production rule, reproduced verbatim for the baseline column
- status: validated 24 (27.91%); contradicted 41 (47.67%); unresolved 21 (24.42%)
- decisive-label coverage: 65
- labels changed vs current: 0
- transitions: none (identity)

### min2 — Minimum 2 directional tickers for a decisive label
- empirical basis: grounded in the observed single-directional-ticker decisive rows
- status: validated 23 (26.74%); contradicted 39 (45.35%); unresolved 24 (27.91%)
- decisive-label coverage: 62
- labels changed vs current: 3
- transitions: contradicted->unresolved 2; validated->unresolved 1

### tie_unresolved — Ties -> unresolved (balance floor, keeps count floor of 1)
- empirical basis: grounded in the observed exact-tie (supports == contradicts) rows
- status: validated 24 (27.91%); contradicted 36 (41.86%); unresolved 26 (30.23%)
- decisive-label coverage: 60
- labels changed vs current: 5
- transitions: contradicted->unresolved 5

### min2_supermajority — Minimum 2 directional AND a 2/3 supermajority
- empirical basis: combines the count floor and the balance floor over observed combos
- status: validated 21 (24.42%); contradicted 30 (34.88%); unresolved 35 (40.7%)
- decisive-label coverage: 51
- labels changed vs current: 14
- transitions: contradicted->unresolved 11; validated->unresolved 3

## 7. Family and age-bucket sensitivity (accepted lens)

- mechanism families present: ['none']
- NOTE: every accepted row carries `mechanism_family = 'none'`; family stratification is degenerate and unavailable on this archive.
- age buckets present: ['frozen']
  - frozen: {'validated': 24, 'contradicted': 41, 'unresolved': 21}

## 8. Ground-truth availability

- accepted rows with a manual `rating`: 0
- rating vocabulary observed: []
- independent target available: False
- manual rating is human judgement (same archive), not a market outcome; event-study inference is n=1 with no cross-sectional test; predictive accuracy cannot be calibrated

Because no defensible independent target exists, predictive accuracy CANNOT be calibrated. The analysis is restricted to evidence sufficiency, label stability, coverage, and sensitivity. No claim is made that any rule is 'more accurate'; any agreement with manual ratings or outcomes would be descriptive and same-sample only.

## 9. Recommendation

- denominator: 86 accepted track-record events (archive 180; excluded 23 non-thesis-stage + 71 synthetic-seed).
- observed basis: 65 decisive labels; 3 rest on a single directional ticker (4.6%); 5 rest on an exact tie; the remainder rest on two or more directional tickers.
- proposed rule: none is compelled by the data. A minimum-2 directional floor (`min2`) is available and would move 3 label(s); it is documented as an optional guard, not a required change.
- labels affected / coverage cost: min2 3; tie_unresolved 5; min2_supermajority 14 (all out of the accepted decisive set).
- fragility: label stability under small rule perturbations is reported in section 6; the current decisive labels move only 3 under the count floor and 14 under the combined count+balance floor.
- what was unavailable: an independent target (manual `rating` present on 0 accepted rows; mechanism-family labels degenerate; event-study inference is n=1), so predictive accuracy could not be calibrated.
- scope: this characterizes the current 86-event accepted archive snapshot (65 decisive labels) — a small, bounded set; the calibration should be re-run as accepted coverage grows before any rule change is considered.
- non-claim: this report does not assert any rule is more accurate, does not confirm any thesis, and proposes no directional or trading interpretation; it characterizes evidence sufficiency and label stability only.

### KEEP_CURRENT_RULE
