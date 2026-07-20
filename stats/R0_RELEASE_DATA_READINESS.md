# R0 - CPI and Employment release-surprise data readiness

Contract: `r0-release-register-v1`. Capture retrieved at 2026-07-19T23:53:56+00:00 (all report content derives from that pinned capture; regeneration from the same capture is byte-identical). Scope: scheduled U.S. CPI and Employment Situation releases, capture years 2008-2026. This is a data-readiness proof only: no asset reaction, no event study, no surprise threshold, and no statistical conclusion appears here.

## Data contract

One record per (release, series). Fields: release_id (`family:release_date`), family, release_name, series_id, measure, reference_period, release_date, scheduled_timestamp (ISO-8601 with America/New_York offset), scheduled_timezone, actual, prior, revised_prior, consensus (each an explicit value cell with status, vintage provenance and reason), unit, seasonal_adjustment, measure_kind, frequency, source_reference, source_timestamp, retrieval_method, revision_status, availability_status, missing_reason, schedule_attestation.

Three prior layers stay permanently distinct: `prior` is the previous reference month as originally published (its first vintage, strictly before this release); `revised_prior` is the same month as shown in this release's own vintage; the latest revised historical value is not a field of this contract and may never enter a point-in-time computation. A vintage after the release date can never populate a point-in-time field (hard construction error). Availability vocabulary: `available`, `missing_consensus`, `missing_prior`, `missing_actual`, `timestamp_unresolved`, `unit_incompatible`, `revision_ambiguous`, `source_unavailable`, `not_applicable`. Null alone never carries research meaning.

Registered series:

| family | series | measure | unit | seasonal basis |
|---|---|---|---|---|
| cpi | CPIAUCSL | cpi_u_all_items_sa_index | index_1982_1984_100 | SA |
| cpi | CPIAUCNS | cpi_u_all_items_nsa_index | index_1982_1984_100 | NSA |
| employment | PAYEMS | total_nonfarm_payrolls_sa_level | thousands_of_persons | SA |
| employment | UNRATE | unemployment_rate_sa | percent_of_labor_force | SA |

## Source inventory

Identity + scheduled-timestamp layer: the official BLS per-program schedule pages, read as PINNED Internet Archive (Wayback Machine) raw snapshots. A pinned snapshot is byte-reproducible; the archived page is still the primary BLS document. One snapshot attests roughly 14 forward months; one-or-two snapshots per calendar year give overlapping attestation. Direct www.bls.gov access from this environment is refused (HTTP 403 recorded below), which is an access-path failure mode, not a data gap.

- Consumer Price Index: `https://www.bls.gov/schedule/news_release/cpi.htm`; 36 pinned snapshots (2008-2026), supplying reference month, release date and release time per row; revision behavior: reschedules appear as cross-snapshot conflicts and are never resolved silently.
- Employment Situation: `https://www.bls.gov/schedule/news_release/empsit.htm`; 37 pinned snapshots (2008-2026), supplying reference month, release date and release time per row; revision behavior: reschedules appear as cross-snapshot conflicts and are never resolved silently.
- direct BLS probe evidence: {"cpi": {"evidence": "RuntimeError: fetch failed after 1 attempts: https://www.bls.gov/schedule/news_release/cpi.htm: HTTP Error 403: Forbidden", "reachable": false}, "employment": {"evidence": "RuntimeError: fetch failed after 1 attempts: https://www.bls.gov/schedule/news_release/empsit.htm: HTTP Error 403: Forbidden", "reachable": false}}

Values layer: the ALFRED vintage layer of the official FRED API (authenticated free registered key; the key authenticates only and every recorded URL is redacted). A vintage dated on the release day carries the numbers published that morning; historical depth reaches 1949-1972 depending on series; failure modes are vintage/release-date misalignment (counted explicitly below) and capture-scope truncation (bounded by the schedule layer's own start).

Consensus layer survey (every zero-cost candidate evaluated):

| source | fields | depth | terms | reproducibility | verdict |
|---|---|---|---|---|---|
| FRED / ALFRED catalog | actual, prior, revised prior (vintages); no consensus series exists for these releases | vintages to 1949-1972 depending on series | free registered key; redistribution of derived counts permitted | high (stable API, stable identifiers) | supplies values; supplies no consensus |
| Philadelphia Fed Survey of Professional Forecasters | quarterly-average forecasts (CPI inflation rate, payroll employment averages) | 1968+ (quarterly) | free, documented | high | structurally incompatible with per-release surprise |
| Cleveland Fed inflation nowcasts | model nowcasts of CPI before each release | 2014+ | free | high | excluded on principle (inferred consensus) |
| commercial economic calendars (survey medians from Bloomberg / Reuters / Dow Jones lineage; web mirrors) | per-release consensus, actual, prior | varies, roughly 2007+ on web mirrors | licensed or terms-restricted; scraping mirrors violates their terms of use | low for mirrors (no stable archive, opaque provenance); licensed feeds are not zero-cost | not zero-cost / not license-clean |

## Coverage denominators

### Consumer Price Index (cpi)

| layer | count |
|---|---|
| attempted_releases | 214 |
| identity_resolved | 213 |
| timestamp_resolved | 210 |
| actual_available | 211 |
| prior_available | 212 |
| consensus_available | 0 |
| actual_prior_consensus_complete | 0 |
| revision_ambiguous | 2 |
| unit_incompatible | 0 |
| source_unavailable | 0 |
| fully_eligible | 0 |

- schedule snapshots parsed: 36; rejected schedule rows: 1; future-scheduled entries beyond the capture cutoff (excluded): 5; entries before the capture scope (excluded): 0; same-day release-date collisions (excluded, listed): []

Per series:

| series | records | actual | prior | revised prior | consensus | prior revised | prior unrevised | revision ambiguous |
|---|---|---|---|---|---|---|---|---|
| CPIAUCNS | 213 | 211 | 212 | 210 | 0 | 1 | 209 | 2 |
| CPIAUCSL | 213 | 211 | 212 | 210 | 0 | 19 | 191 | 2 |

By calendar year (release year; strict all-series basis):

| year | attempted | timestamp | actual | prior | consensus | complete a/p/c | fully eligible |
|---|---|---|---|---|---|---|---|
| 2008 | 2 | 2 | 2 | 2 | 0 | 0 | 0 |
| 2009 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2010 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2011 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2012 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2013 | 12 | 11 | 11 | 12 | 0 | 0 | 0 |
| 2014 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2015 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2016 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2017 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2018 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2019 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2020 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2021 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2022 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2023 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2024 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2025 | 12 | 10 | 11 | 11 | 0 | 0 | 0 |
| 2026 | 7 | 7 | 7 | 7 | 0 | 0 | 0 |

### Employment Situation (employment)

| layer | count |
|---|---|
| attempted_releases | 213 |
| identity_resolved | 213 |
| timestamp_resolved | 210 |
| actual_available | 211 |
| prior_available | 211 |
| consensus_available | 0 |
| actual_prior_consensus_complete | 0 |
| revision_ambiguous | 2 |
| unit_incompatible | 0 |
| source_unavailable | 0 |
| fully_eligible | 0 |

- schedule snapshots parsed: 37; rejected schedule rows: 0; future-scheduled entries beyond the capture cutoff (excluded): 5; entries before the capture scope (excluded): 0; same-day release-date collisions (excluded, listed): []

Per series:

| series | records | actual | prior | revised prior | consensus | prior revised | prior unrevised | revision ambiguous |
|---|---|---|---|---|---|---|---|---|
| PAYEMS | 213 | 211 | 211 | 211 | 0 | 209 | 1 | 2 |
| UNRATE | 213 | 211 | 211 | 210 | 0 | 5 | 205 | 1 |

By calendar year (release year; strict all-series basis):

| year | attempted | timestamp | actual | prior | consensus | complete a/p/c | fully eligible |
|---|---|---|---|---|---|---|---|
| 2008 | 2 | 2 | 2 | 2 | 0 | 0 | 0 |
| 2009 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2010 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2011 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2012 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2013 | 12 | 11 | 11 | 12 | 0 | 0 | 0 |
| 2014 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2015 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2016 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2017 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2018 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2019 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2020 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2021 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2022 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2023 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2024 | 12 | 12 | 12 | 12 | 0 | 0 | 0 |
| 2025 | 12 | 10 | 11 | 10 | 0 | 0 | 0 |
| 2026 | 7 | 7 | 7 | 7 | 0 | 0 | 0 |

## Availability and missingness

- cpi record availability histogram: missing_actual: 4, missing_consensus: 416, timestamp_unresolved: 6
- employment record availability histogram: missing_actual: 4, missing_consensus: 416, timestamp_unresolved: 6

Every non-available record carries its own missing_reason; the dominant reasons per family:

- cpi (top 6 reason patterns of 7):
  - 426x consensus: no zero-cost reproducible point-in-time consensus source (see consensus source survey)
  - 6x conflicting schedule attestations
  - 4x actual: no vintage exists on the release date
  - 4x revised_prior: no vintage exists on the release date
  - 4x revision relation not assessable: only one of prior / revised_prior is available
  - 2x prior: previous reference month never observed in the captured vintages
- employment (top 6 reason patterns of 9):
  - 426x consensus: no zero-cost reproducible point-in-time consensus source (see consensus source survey)
  - 6x conflicting schedule attestations
  - 4x actual: no vintage exists on the release date
  - 4x revised_prior: no vintage exists on the release date
  - 3x revision relation not assessable: only one of prior / revised_prior is available
  - 2x prior: first publication of the previous reference month (2025-11-20) is not before the release date

## Revision handling

The original prior is read from the previous release's own vintage and is immutable; the revised prior is read from this release's vintage; their difference is the observed within-release revision. When only one side is available the relation is `revision_ambiguous` and the release is excluded from the eligible denominator rather than repaired. Later vintages (annual seasonal recalculations, benchmark revisions) never overwrite any stored field.

- CPIAUCSL: revision delta (count 210, min -0.317, max 0.878, mean 0.002676, median 0.0); nonzero revisions: 19 of 210
- CPIAUCNS: revision delta (count 210, min -0.004, max 0.0, mean -1.9e-05, median 0.0); nonzero revisions: 1 of 210
- PAYEMS: revision delta (count 210, min -1363.0, max 813.0, mean -5.67619, median 5.5); nonzero revisions: 209 of 210
- UNRATE: revision delta (count 210, min -0.1, max 0.1, mean 0.000476, median 0.0); nonzero revisions: 5 of 210

## Timestamp handling

Scheduled timestamps combine the attested schedule date and local release time with the America/New_York zone into an explicit-offset ISO-8601 instant. A missing or unparseable time, or conflicting cross-snapshot attestations (reschedules), fail closed as `timestamp_unresolved`; nothing falls back to a convention. Release-day alignment against the values layer is enforced separately: an actual may come only from a vintage dated exactly on the attested release date, so a schedule/vintage mismatch surfaces as `missing_actual` with the mismatching date in the reason, never as a silently shifted join.

- cpi: timestamp resolved 210 of 213 identity-resolved releases; releases with conflicting schedule attestations: 3
- employment: timestamp resolved 210 of 213 identity-resolved releases; releases with conflicting schedule attestations: 3

## Unit compatibility

Each series carries one declared unit, one seasonal basis and one measure kind; a record mixing any of them fails closed as `unit_incompatible` with every numeric field demoted. Seasonally adjusted and unadjusted CPI are separate series and never share a record; monthly levels and derived monthly changes are distinct measure kinds and cannot be stored in one field.

- CPIAUCSL: unit `index_1982_1984_100`, basis SA; observed decimal places in as-published values: 3; unit-incompatible records: 0
- CPIAUCNS: unit `index_1982_1984_100`, basis NSA; observed decimal places in as-published values: 3; unit-incompatible records: 0
- PAYEMS: unit `thousands_of_persons`, basis SA; observed decimal places in as-published values: 1; unit-incompatible records: 0
- UNRATE: unit `percent_of_labor_force`, basis SA; observed decimal places in as-published values: 1; unit-incompatible records: 0

## Point-in-time risks

Field classification (a field classified retrospective, latest-revised or uncertain may not enter a future point-in-time surprise calculation):

| field | classification |
|---|---|
| scheduled_timestamp | known at scheduled release (published in the annual BLS schedule, attested by pre-release snapshots where available) |
| actual | published in the release document (release-day vintage) |
| prior (original) | published at the previous release; known before this release |
| revised_prior | published in the release document (release-day vintage) |
| consensus | uncertain: no compliant source exists; the field stays explicitly missing |
| latest revised value | latest-revised: excluded from the contract by design |

Residual risks kept visible rather than repaired: (1) a Wayback snapshot taken after a reschedule can attest only the revised date - conflicts are counted and fail closed; (2) ALFRED vintage dates can lag or lead the BLS release date - such releases surface as missing_actual with the date in the reason and are excluded, not shifted; (3) snapshot coverage begins in 2008, so earlier releases have deep vintage values but no source-pinned schedule attestation and stay outside this register; (4) intraday timestamp precision rests on the schedule's local release time - no trade-level timestamping is claimed.

## Distribution observations

Descriptive scales only, from as-published values; no threshold, no classification, no standardization is defined here.

- CPIAUCSL (cpi, `index_1982_1984_100`):
  - actual minus revised prior: count 210, min -3.65, max 3.854, mean 0.533852, median 0.508
  - actual percent change vs revised prior: count 210, min -1.684279, max 1.322245, mean 0.197331, median 0.199587
  - within-release revision delta: count 210, min -0.317, max 0.878, mean 0.002676, median 0.0
  - actual minus consensus: 0 records (not computable: no release carries a point-in-time consensus value)
- CPIAUCNS (cpi, `index_1982_1984_100`):
  - actual minus revised prior: count 210, min -4.148, max 4.015, mean 0.550376, median 0.5105
  - actual percent change vs revised prior: count 210, min -1.91529, max 1.373608, mean 0.202786, median 0.197019
  - within-release revision delta: count 210, min -0.004, max 0.0, mean -1.9e-05, median 0.0
  - actual minus consensus: 0 records (not computable: no release carries a point-in-time consensus value)
- PAYEMS (employment, `thousands_of_persons`):
  - actual minus revised prior: count 211, min -20500.0, max 4800.0, mean 108.241706, median 178.0
  - actual percent change vs revised prior: count 211, min -13.524925, max 3.608968, mean 0.078151, median 0.126842
  - within-release revision delta: count 210, min -1363.0, max 813.0, mean -5.67619, median 5.5
  - actual minus consensus: 0 records (not computable: no release carries a point-in-time consensus value)
- UNRATE (employment, `percent_of_labor_force`):
  - actual minus revised prior: count 210, min -2.2, max 10.3, mean -0.01, median 0.0
  - actual percent change vs revised prior: count 210, min -17.647059, max 234.090909, mean 0.439409, median 0.0
  - within-release revision delta: count 210, min -0.1, max 0.1, mean 0.000476, median 0.0
  - actual minus consensus: 0 records (not computable: no release carries a point-in-time consensus value)

## Proposed future eligibility gate

Minimum defensible gate, derived from the observed layers (no numeric coverage threshold is invented): a release is eligible only when its identity is snapshot-attested without conflict, its timestamp is resolved, its actual and revised prior come from the release-day vintage, its original prior comes from a strictly earlier vintage, a point-in-time consensus value exists, and all values share one unit, basis and measure kind. This is exactly the `fully_eligible` counter above; every excluded release is preserved with its reason. The gate is sufficient for the intended descriptive release-surprise question because each clause removes one named look-ahead or conflation channel; it is applied uniformly to both families.

## Readiness verdict

- cpi: NOT READY
- employment: NOT READY

### cpi blockers

- point-in-time consensus: zero releases carry any zero-cost reproducible pre-release consensus value; the surprise column of the intended design cannot be built
- eligible denominator: zero releases pass the structural eligibility gate
- affected denominator: 214 attempted releases (213 identity-resolved), years 2008-2026
- smallest realistic repair: a licensed per-release consensus history (cost / licensing) or a manually adjudicated point-in-time capture of archived pre-release survey medians (manual adjudication); prospective capture going forward is zero-cost but builds history only from now on. No repair is attempted here and nothing is built around the missing field.

### employment blockers

- point-in-time consensus: zero releases carry any zero-cost reproducible pre-release consensus value; the surprise column of the intended design cannot be built
- eligible denominator: zero releases pass the structural eligibility gate
- affected denominator: 213 attempted releases (213 identity-resolved), years 2008-2026
- smallest realistic repair: a licensed per-release consensus history (cost / licensing) or a manually adjudicated point-in-time capture of archived pre-release survey medians (manual adjudication); prospective capture going forward is zero-cost but builds history only from now on. No repair is attempted here and nothing is built around the missing field.

## Non-claims

- No event study, asset reaction, or estimate of any economic relationship was computed anywhere in R0.
- No surprise threshold, classification, or standardization was defined.
- Source availability is a feasibility property only; it is not evidence that any release moves anything.
- No predictive, causal, significant, or tradeable claim is made, and none is implied.
- No synthetic value was created, no gap was filled, no release was hand-selected: the universe is every schedule-attested release in the capture scope.
- A NOT READY verdict prices the missing layer; it says nothing about the economic importance of either family.
