# G1B OPEC designed-recruitment reservoir

Status: G1B shipping reservoir artifact. This file creates no row in the
database and makes no market-data provider, cache, ticker, price, event-study,
or state-series call. It is a candidate reservoir only: no candidate in this
file is selected for any Designed Contrast cell, and no market response or
market-state information appears anywhere in it.

Candidate-source ID: `opec-production-policy-reservoir-2018-2025@v1`
Sampling object: `designed_recruitment_reservoir`
Sampling lane (on any later recruitment): `designed_contrast`
Selection rule version: `g0-v1`
Non-enumerable-family flag: `true` (see section 1)

## 1. Reservoir contract

- **Source family:** official OPEC / OPEC+ records - OPEC Conference press
  releases, OPEC and non-OPEC Ministerial Meeting (ONOMM) press releases, and
  official statements of the eight coordinating OPEC+ producers (the "V8":
  Saudi Arabia, Russia, Iraq, UAE, Kuwait, Kazakhstan, Algeria, Oman)
  published by the OPEC Secretariat at opec.org.
- **Date range:** 2018-01-01 through 2025-12-31, inclusive, using the date of
  the official decision announcement.
- **Inclusion rule:** an official dated ministerial decision or official
  production-policy announcement that materially addresses collective
  crude-oil production policy - a production increase, a production
  reduction, an extension of an existing production policy, a reversal or
  phase-out, a restoration schedule, or an emergency collective decision.
- **Exclusion rule:** general commentary with no policy decision; monthly
  market reports; interviews; speeches; generic reaffirmations with no
  material policy action (e.g. routine monthly ONOMM confirmations of an
  already-announced schedule during 2021, the 34th ONOMM rollover of
  2022-12-04, the 39th ONOMM reaffirmation of 2025-05-28); JMMC meetings that
  issued recommendations without a policy decision; duplicate press releases
  describing the same event identity (preserved as mirrors, section 3);
  individual-country voluntary adjustments unless the record is a distinct
  collective policy event (the coordinated multi-country voluntary packages
  of 2023-2025 qualify as collective; single-country add-ons inside them do
  not create separate identities).
- **Why reproducible:** every entry cites an official meeting identity
  (numbered OPEC Conference / ONOMM meeting or dated V8 statement) in one
  bounded public source family over a fixed date range under the fixed rule
  above; a second researcher applying the same rule to the same source family
  reaches the same ledger, and every pin can be re-audited at opec.org.
- **Why NOT globally frame-complete:** the reservoir enumerates one issuer's
  official production-policy record. It does not and cannot enumerate oil
  supply shocks in general (wars, strikes, embargoes, accidents, unilateral
  national decisions outside OPEC+, demand collapses).

> Source-bounded candidate completeness is not completeness of all oil
> supply shocks.

- **Claim ceiling:** this reservoir supports later Designed Contrast
  recruitment under frozen G rules only. It is not a frame-complete inventory
  of oil supply shocks, not a final designed cohort, not a prevalence sample,
  and not a state-balanced sample. No prevalence claim, no pooled statistic,
  and no market-response claim may be built from it.

## 2. Full discovery ledger

Constant fields for every row (stated once, applying to all rows):
candidate-source ID `opec-production-policy-reservoir-2018-2025@v1`;
selection-rule version `g0-v1`; discovery path `official OPEC/OPEC+ record ->
reservoir rule g0-v1`; non-enumerable-family flag `true`; sampling object
`designed_recruitment_reservoir`. No row carries a ticker, AR, SAR, CAR,
price move, sector-relative value, state tag, or outcome - by contract.

Anchor status vocabulary: `pinned_official` (date verified against the
official record during this pass) or `pin_verification_pending` (date stated
from the documented public record but not re-verified against an official
page in this pass; held out of reservoir-ready until pinned). Anchor class
uses the existing event-date-quality vocabulary (`scheduled_or_weak_anchor`
for calendared ministerial meetings; `clean_discrete_anchor` for
extraordinary or surprise announcements).

| key | source date | official source reference | title / decision (concise) | action type | canonical identity | anchor | dup/mirror |
|---|---|---|---|---|---|---|---|
| D01 | 2018-06-22 | 174th OPEC Conference PR | Conference decision toward 100 percent conformity | increase (effective) | C01 | pinned_official / scheduled | mirror of D02 |
| D02 | 2018-06-23 | 4th ONOMM PR | OPEC+ returns to 100 percent conformity (about 1 mb/d effective supply increase) | increase (effective) | C01 `opec-2018-06-23-conformity-return` | pinned_official / scheduled | canonical |
| D03 | 2018-12-06 | 175th OPEC Conference PR | Conference decision toward joint adjustment | reduction | C02 | pinned_official / scheduled | mirror of D04 |
| D04 | 2018-12-07 | 5th ONOMM PR | 1.2 mb/d joint production adjustment for six months from 2019-01 | reduction | C02 `opec-2018-12-07-cut-1p2` | pinned_official / scheduled | canonical |
| D05 | 2019-07-01 | 176th OPEC Conference PR | Conference decision to extend adjustment | extension | C03 | pinned_official / scheduled | mirror of D06 |
| D06 | 2019-07-02 | 6th ONOMM PR | 1.2 mb/d adjustment extended nine months to 2020-03 | extension | C03 `opec-2019-07-02-extension` | pinned_official / scheduled | canonical |
| D07 | 2019-12-05 | 177th OPEC Conference PR | Conference decision toward deeper adjustment | reduction | C04 | pinned_official / scheduled | mirror of D08 |
| D08 | 2019-12-06 | 7th ONOMM PR | Adjustment deepened by 0.5 mb/d to 1.7 mb/d for Q1 2020 | reduction | C04 `opec-2019-12-06-deepen-1p7` | pinned_official / scheduled | canonical |
| D09 | 2020-03-05 | 178th (Extraordinary) OPEC Conference PR + Heads of Delegation consultation PR; 2020 OPEC press-release archive shows no 2020-03-06 ONOMM decision PR | Conference recommended an additional 1.5 mb/d adjustment to the 8th ONOMM, then Heads of Delegation recommended extending that proposed adjustment to end-2020; the 2020-03-06 non-agreement remains preserved as context, but no official source-pinned collective policy decision was identified | held/excluded under current rule (recommendation not adopted; no clean official outcome source for the non-agreement) | C05-held `opec-2020-03-05-recommendation-nonagreement-held` | pinned_official / clean_discrete | held; not reservoir-ready |
| D10 | 2020-04-09 | 9th (Extraordinary) ONOMM PR | Agreement in principle on about 10 mb/d adjustment for May-June, conditional | emergency reduction | C06 | pinned_official / clean_discrete | mirror of D11 |
| D11 | 2020-04-12 | 10th (Extraordinary) ONOMM PR | 9.7 mb/d adjustment finalized for May-June 2020, with tapering schedule | emergency reduction | C06 `opec-2020-04-12-cut-9p7` | pinned_official / clean_discrete | canonical |
| D12 | 2020-06-06 | 179th OPEC Conference + 11th ONOMM PR | 9.7 mb/d adjustment extended through 2020-07 | extension | C07 `opec-2020-06-06-extension` | pinned_official / scheduled | none |
| D13 | 2020-12-03 | 12th ONOMM PR | 0.5 mb/d returned from 2021-01; monthly ministerial cadence adopted | restoration schedule | C08 `opec-2020-12-03-restoration-start` | pinned_official / scheduled | none |
| D14 | 2021-01-05 | 13th ONOMM PR | February-March 2021 production levels set (collective decision; a single-country voluntary add-on announced alongside is excluded per rule) | restoration schedule | C09 `opec-2021-01-05-feb-mar-levels` | pinned_official / scheduled | none |
| D15 | 2021-04-01 | 15th ONOMM PR | Gradual return set for May-July 2021 | restoration schedule | C10 `opec-2021-04-01-gradual-return` | pinned_official / scheduled | none |
| D16 | 2021-07-18 | 19th ONOMM PR | 0.4 mb/d monthly increases from 2021-08; baseline adjustments from 2022-05 | restoration schedule | C11 `opec-2021-07-18-monthly-400k` | pinned_official / scheduled | none |
| D17 | 2022-06-02 | 29th ONOMM PR | Return accelerated: 0.648 mb/d for July and August 2022 | restoration acceleration | C12 `opec-2022-06-02-accelerate-648k` | pinned_official / scheduled | none |
| D18 | 2022-08-03 | 31st ONOMM PR | 0.1 mb/d increase for September 2022 | increase | C13 `opec-2022-08-03-sep-100k` | pinned_official / scheduled | none |
| D19 | 2022-09-05 | 32nd ONOMM PR | 0.1 mb/d reduction for October 2022 (reverses the September step) | reduction (reversal) | C14 `opec-2022-09-05-oct-minus-100k` | pinned_official / scheduled | none |
| D20 | 2022-10-05 | 33rd ONOMM PR | 2 mb/d reduction from November 2022 | reduction | C15 `opec-2022-10-05-cut-2mbd` | pinned_official / scheduled | none |
| D21 | 2023-04-02 | 48th JMMC PR (opec.org pr-detail 63-03-apr-2023; notes 2023-04-02 voluntary adjustments) | Coordinated multi-country voluntary reduction announced on 2023-04-02 from May 2023 (collective policy event under the locked rule) | reduction (coordinated voluntary) | C16 `opec-2023-04-02-voluntary-1p16` | pinned_official / clean_discrete | none |
| D22 | 2023-06-04 | 35th ONOMM PR | 2024 required production levels revised; group adjustments extended (a single-country voluntary add-on excluded per rule) | reduction / extension (levels revision) | C17 `opec-2023-06-04-2024-levels` | pinned_official / scheduled | none |
| D23 | 2023-11-30 | 36th ONOMM PR + coordinating-producers statement | Coordinated additional voluntary adjustments of about 2.2 mb/d for Q1 2024 | reduction (coordinated voluntary) | C18 `opec-2023-11-30-voluntary-2p2` | pinned_official / scheduled | none |
| D24 | 2024-03-03 | Coordinating-producers statement (opec.org pr-detail 4-03-mar-2024) | 2.2 mb/d voluntary adjustments extended through Q2 2024 | extension | C19 `opec-2024-03-03-q2-extension` | pinned_official / scheduled | none |
| D25 | 2024-06-02 | 37th ONOMM PR + V8 statement | Group-wide adjustments extended into 2025; 2.2 mb/d voluntary extended to 2024-09 then phased return scheduled from 2024-10 | extension + restoration schedule | C20 `opec-2024-06-02-extension-schedule` | pinned_official / scheduled | none |
| D26 | 2024-09-05 | V8 statement | Phased return delayed two months (to end-November 2024) | extension (delay) | C21 `opec-2024-09-05-two-month-delay` | pinned_official / scheduled | none |
| D27 | 2024-11-03 | V8 statement | Phased return delayed one further month (to end-December 2024) | extension (delay) | C22 `opec-2024-11-03-one-month-delay` | pinned_official / scheduled | none |
| D28 | 2024-12-05 | 38th ONOMM PR (opec.org pr-detail 28-05-dec-2024) + V8 statement | Return start moved to 2025-04 over an extended runway to 2026-09; group-wide adjustments extended through 2026 | extension + schedule revision | C23 `opec-2024-12-05-april-start` | pinned_official / scheduled | none |
| D29 | 2025-03-03 | V8 statement (opec.org pr-detail 518-03-march-2025) | Gradual return set to begin 2025-04-01 (about 0.137 mb/d monthly design) | restoration activation | C24 `opec-2025-03-03-activation` | pinned_official / scheduled | none |
| D30 | 2025-04-03 | V8 statement | May 2025 level raised by 0.411 mb/d (three monthly increments in one) | restoration acceleration | C25 `opec-2025-04-03-may-411k` | pinned_official / scheduled | none |
| D31 | 2025-05-03 | V8 statement (opec.org pr-detail 563-03-may-2025) | June 2025 level raised by 0.411 mb/d | restoration acceleration | C26 `opec-2025-05-03-jun-411k` | pinned_official / scheduled | none |
| D32 | 2025-06-01 | V8 statement | July 2025 level raised by 0.411 mb/d | restoration acceleration | C27 `opec-2025-06-01-jul-411k` | pinned_official / scheduled | none |
| D33 | 2025-07-05 | V8 statement (opec.org pr-detail 569-05-july-2025) | August 2025 level raised by 0.548 mb/d | restoration acceleration | C28 `opec-2025-07-05-aug-548k` | pinned_official / scheduled | none |
| D34 | 2025-08-03 | V8 statement | September 2025 level raised by 0.547 mb/d (completes the 2.2 mb/d return ahead of schedule) | restoration acceleration | C29 `opec-2025-08-03-sep-547k` | pinned_official / scheduled | none |
| D35 | 2025-09-07 | V8 statement (opec.org pr-detail 573-07-september-2025) | October 2025 level raised by 0.137 mb/d - first step of returning the separate 1.65 mb/d voluntary layer (new phase) | restoration schedule (new layer) | C30 `opec-2025-09-07-oct-137k` | pinned_official / scheduled | none |
| D36 | 2025-10-05 | V8 statement (opec.org pr-detail 578-05-october-2025) | November 2025 level raised by 0.137 mb/d | restoration schedule | C31 `opec-2025-10-05-nov-137k` | pinned_official / scheduled | none |
| D37 | 2025-11-02 | V8 statement (opec.org pr-detail 1574579-02-november-2025) | December 2025 level raised by 0.137 mb/d; increments paused for Q1 2026 (seasonality) | restoration schedule + pause | C32 `opec-2025-11-02-dec-137k-pause` | pinned_official / scheduled | none |
| D38 | 2025-11-30 | 40th ONOMM PR (opec.org pr-detail 243582-30-november-2025; 583-30-november-2025) | Group-wide 2026 levels held; baseline/capacity mechanism agreed; Q1 2026 pause reaffirmed | extension (annual decision + mechanism) | C33 `opec-2025-11-30-2026-hold` | pinned_official / scheduled | none |

## 3. Canonical identity resolution

```
38 source discoveries
-> 33 canonical event identities   (5 discoveries are Conference/ONOMM or
                                    agreement-in-principle mirrors of the same
                                    decision identity: D01->C01, D03->C02,
                                    D05->C03, D07->C04, D10->C06)
-> 1 held/excluded identity         (C05-held: recommendation/non-agreement
                                    trail, not an adopted collective decision
                                    under the current rule)
-> 32 canonical reservoir identities
-> 32 anchor-pinned                (pinned_official, reservoir-ready set)
    0 pin-verification-pending     (the five formerly pending identities:
                                    C16, C19, C24, C30, C31 - now pinned)
-> 5 duplicate/mirror links preserved (no discovery deleted; mirrors remain
                                    visible above and in the discovery count)
-> 0 archive collisions            (section 4)
-> 32 reservoir-ready identities   (pinned + duplicate-resolved + no collision)
```

Reconciliation: 38 discoveries = 33 canonical identities + 5 mirror links.
33 identities fall on 33 distinct announcement dates (no two identities share
a date). Of those 33, one is held/excluded (C05-held), leaving 32 canonical
reservoir identities; 32 = 32 pinned-ready + 0 pin-verification-pending. No
identity advances twice: each mirror is linked to exactly one canonical row
and cannot be recruited separately.

March 2020 adjudication: the 178th Conference record states only a
recommendation to the 8th ONOMM for an additional adjustment; the same-day
Heads of Delegation record extends the recommended duration of that proposed
adjustment. The official 2020 OPEC press-release archive has no 2020-03-06
ONOMM decision record between the 2020-03-05 records and the 2020-03-16
joint statement. Under the locked inclusion rule, this is a preserved
recommendation/non-agreement discovery trail, not an advancing collective
production-policy decision.

## 4. Existing-archive collision check (read-only)

The live archive was searched read-only for OPEC-related identities
(headline family match). Result: 32 rows match the headline family; every one
is dated 2026 (2026-04-05 .. 2026-05-08), outside this reservoir's
2018-2025 range.

| existing event id(s) | match basis | same identity as a reservoir row? | resolution |
|---|---|---|---|
| 39, 53, 54, 64, 70 (accepted; L2 duplicate group G4) | headline family: "OPEC members discuss/agree extending output cuts", April 2026 | NO - the April 2026 decision is outside 2018-2025 | no collision; live rows keep ledger precedence 1 (live track record); noted so a future range extension re-checks them |
| 105 (accepted) | headline family: "OPEC extends voluntary oil output cuts", 2026-04-15 | NO - 2026 | as above |
| 35, 36, 215, 217, 225 (accepted) | OPEC-adjacent geopolitical headlines, April 2026 | NO - different events, 2026 | no collision |
| 56, 58, 67, 74, 77, 81, 86, 98, 102, 106, 109, 113, 116, 119, 124, 159, 177, 209, 245, 263, 286 | literal "OPEC slashes output by 2 mbpd" copies | NO - these are the known synthetic seed rows (event_hygiene `synthetic_seed`), not real event identities | no collision; synthetic rows are excluded from every research denominator already |

Ledger precedence applied: (1) existing live track record, (2) frame-complete
historical, (3) designed contrast. No reservoir identity matches a
higher-precedence identity, so no precedence transfer occurs. If a future
reservoir version overlaps the live window, the live identity keeps
precedence: it would remain discoverable through this reservoir (discovery
path preserved in provenance) but could never become a duplicate evidence
row or move ledgers.

## 5. Outcome-blindness statement

This artifact contains no market return, no abnormal return, no SAR or CAR,
no outcome label, no market-state classification, and no post-event
performance rationale. Inclusion and exclusion are explainable entirely from
the official source record and the locked rule in section 1: every
reservoir-ready row is an official dated collective production-policy
decision; the March 2020 recommendation/non-agreement trail is preserved but
held out of advancement under that same rule; every excluded class is named in
the contract. Subsequent oil-price reaction and remembered historical
importance played no role in inclusion - the ledger includes routine-magnitude
decisions and excludes several famous meeting dates (e.g. the 34th ONOMM
rollover) because the rule, not the market, draws the line.

## 6. Reservoir readiness

No candidate in this reservoir is assigned to any volatility, policy, trend,
curve, or credit category, nor to any G6 comparison cell. Those assignments
are downstream of point-in-time state computation (G2/G3) and the G4 final
structural freeze, in that order. The output of this slice is a candidate
reservoir only; recruitment from it requires the frozen G rules and is a
separate, later decision.

## 7. Verification and reproduction

- Every canonical reservoir identity cites an official meeting identity
  (numbered Conference/ONOMM press release or dated V8 statement) or an
  official OPEC page that pins the event date; no anchor remains
  pin-verification-pending, and the March 2020 recommendation/non-agreement
  trail is explicitly held/excluded from readiness.
- Counts reconcile: 38 = 33 + 5 (section 3); 33 identities on 33 distinct
  dates; 33 = 32 reservoir identities + 1 held/excluded identity; readiness
  32 = 32 - 0 pending - 0 collisions.
- Official source pages verified during this pass include:
  [48th JMMC, 2023-04-03](https://www.opec.org/pr-detail/63-03-apr-2023.html),
  [coordinating-producers statement, 2024-03-03](https://www.opec.org/pr-detail/4-03-mar-2024.html),
  [V8 statement, 2025-03-03](https://www.opec.org/pr-detail/518-03-march-2025.html),
  [V8 statement, 2025-09-07](https://www.opec.org/pr-detail/573-07-september-2025.html),
  [V8 statement, 2025-10-05](https://www.opec.org/pr-detail/578-05-october-2025.html),
  [178th OPEC Conference, 2020-03-05](https://www.opec.org/pr-detail/316-05-mar-2020.html),
  [OPEC Heads of Delegation consultation, 2020-03-05](https://www.opec.org/pr-detail/317-05-mar-2020.html),
  [OPEC 2020 press-release archive](https://www.opec.org/press-releases-2020.html),
  [38th ONOMM, 2024-12-05](https://www.opec.org/pr-detail/28-05-dec-2024.html),
  [V8 statement, 2025-05-03](https://www.opec.org/pr-detail/563-03-may-2025.html),
  [V8 statement, 2025-07-05](https://www.opec.org/pr-detail/569-05-july-2025.html),
  [V8 statement, 2025-11-02](https://www.opec.org/pr-detail/1574579-02-november-2025.html),
  [40th ONOMM, 2025-11-30](https://www.opec.org/pr-detail/243582-30-november-2025.html);
  corroborating contemporaneous coverage was used only to cross-check dates
  (never outcomes), e.g. for 2025-04-03, 2025-08-03, 2024-06-02, 2024-09-05,
  2024-11-03.
- This slice made no market-data provider call, no ticker mapping, no price
  availability check, no event-study call, and no state-series acquisition;
  `events.db` and `price_cache.db` are unchanged.

Not a trading, prediction, or recommendation surface; nothing here says
anything about the market behavior of any asset.
