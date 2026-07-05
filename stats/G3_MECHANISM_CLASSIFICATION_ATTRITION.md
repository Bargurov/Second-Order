# G3 mechanism-classification attrition (Mission G, g0-v1)

## Headline finding

Applying one deterministic comparison-mechanism rubric (`g3-comparison-taxonomy-v1`) uniformly across all three cohorts, classification coverage COLLAPSES for the sampling-family historical candidates relative to the accepted track record:

- accepted track-record (news headlines): 79.1% classified
- G1A FOMC historical (official policy-action titles): 0.0% classified
- G1B OPEC historical (official decision titles): 3.1% classified

This near-total differential loss reflects the SOURCE REGISTER of the text each cohort natively carries - concise official policy-action and decision titles ('Maintain target range at 1.25-1.50 percent'; '1.2 mb/d joint production adjustment') do not contain the news-headline vocabulary the rubric keys on ('federal reserve', 'interest rate', 'oil', 'crude') - NOT the events' mechanisms. FOMC decisions are monetary events and OPEC decisions are supply events regardless; the collapse is a comparability property of the input text, not a statement about the events.

The collapse is strongly consistent with, and directly explained by, input-surface register mismatch. The accepted rows fall in 2026 while the historical rows span 2018-2025, so the two cohorts are temporally disjoint. Because the accepted and historical cohorts are temporally disjoint, source-register effects cannot be cleanly isolated from calendar-time language drift; the finding is an input-surface register mismatch strongly consistent with the data, not a claim that register is perfectly isolated from time.

The honest consequence for G4: mechanism classification via this headline rubric is NOT a comparable axis across the accepted corpus and the sampling-family historical candidates. Their input surfaces are incommensurable source registers. This report sets no G4 warning threshold; it records the comparability finding.

## Method (one rubric, one native surface per cohort)

SAMPLING FAMILY IS NOT COMPARISON MECHANISM: `fomc` / `opec` are never used as mechanism labels. The rubric reuses the frozen J1 headline rule set verbatim (module `accepted_family_overlay_report`, nine mechanism labels: tariff, sanction, supply_shock, ceasefire_deescalation, regulation, labor_inflation, industrial_policy, monetary_policy_or_rates, geopolitical_conflict_context). Taxonomy fingerprint `04ff3c68d7f91a200e30ba769426bd9a053f77b33237966255f248eb2a819eaa` is pinned; any rule change fails a test and requires a version bump plus a full re-run. Classification is a pure function of one normalized headline-like text field; stored archive mechanism fields are never used as classification keys.

Each cohort is classified on the most headline-like text its OWN source artifact natively carries: the accepted rows on the events.db `headline` field (the exact field the J1 overlay uses); G1A on the 'concise policy action from source' cell; G1B on the 'title / decision (concise)' cell. No cohort's text was enriched or substituted. Re-sourcing richer historical text (for example native news headlines for the historical events) would be the FORBIDDEN rescue named in the honesty rule; the accepted 86 cannot be re-sourced either. Classifying each cohort on its own native surface is the only method-symmetric option.

## 183-row classification split

| cohort | N | single | multi-match | unclassified | coverage |
|---|---|---|---|---|---|
| accepted track-record (86) | 86 | 52 | 16 | 18 | 79.1% |
| G1A FOMC historical (65) | 65 | 0 | 0 | 65 | 0.0% |
| G1B OPEC historical (32) | 32 | 1 | 0 | 31 | 3.1% |
| **total** | 183 | 53 | 16 | 114 | 37.7% |

## Coverage by source family

| source family | N | classified | coverage |
|---|---|---|---|
| accepted_news_headline | 86 | 68 | 79.1% |
| official_fomc_statement | 65 | 0 | 0.0% |
| official_opec_record | 32 | 1 | 3.1% |

## Coverage by calendar year (per cohort)

- accepted track-record (86): 2026 68/86 (79.1%)
- G1A FOMC historical (65): 2018 0/8 (0.0%), 2019 0/8 (0.0%), 2020 0/9 (0.0%), 2021 0/8 (0.0%), 2022 0/8 (0.0%), 2023 0/8 (0.0%), 2024 0/8 (0.0%), 2025 0/8 (0.0%)
- G1B OPEC historical (32): 2018 1/2 (50.0%), 2019 0/2 (0.0%), 2020 0/3 (0.0%), 2021 0/3 (0.0%), 2022 0/4 (0.0%), 2023 0/3 (0.0%), 2024 0/5 (0.0%), 2025 0/10 (0.0%)

## Single-family distribution (per cohort)

- accepted track-record (86): ceasefire_deescalation:3, geopolitical_conflict_context:11, monetary_policy_or_rates:3, sanction:4, supply_shock:20, tariff:11
- G1A FOMC historical (65): (none)
- G1B OPEC historical (32): supply_shock:1

## Differential classification attrition

- accepted vs FOMC historical: 79.1% vs 0.0% classified
- accepted vs OPEC historical: 79.1% vs 3.1% classified
- FOMC vs OPEC historical: 0.0% vs 3.1% classified

## Point-in-time state coverage (where structurally possible)

State coverage is structurally defined only for the 97 historical candidates (the G2 substrate: four state dimensions 97/97, credit_hy_oas 36/97). The accepted 86 have no G-state substrate, so the axis is not applicable to them. Because historical classification coverage is near zero regardless of state availability, the two axes are independent: point-in-time state availability does not rescue mechanism classification, and no further cross-tabulation is meaningful.

## Non-claims and firewall

Overlay-only: no stored archive field is rewritten, no row is promoted, and no DB is mutated. Classification uses no market data, no outcome, and no state value; the persisted rows carry only classification metadata (cohort, lane, source family, year, class, matched labels) - no absolute return, abnormal return, SAR, CAR, sector-relative return, sign, direction, magnitude, or outcome label, enforced by a tested field whitelist. This is a coverage-comparability measurement for G4, not a mechanism-performance or prevalence claim, and not a trading or recommendation surface.

## Provenance and reproduction

- taxonomy: `g3-comparison-taxonomy-v1`, fingerprint `04ff3c68d7f91a200e30ba769426bd9a053f77b33237966255f248eb2a819eaa` (pinned to the reused `accepted_family_overlay_report` rule set)
- accepted set: events.db (SHA256 `18aa372e791e98a8adf5a87c2da6f8131bfd4750a1d29c7a1ad11c137c0f6b1f`), accepted track-record loader (read-only)
- historical sets: `stats/G1A_FOMC_FRAME_INVENTORY.md` and `stats/G1B_OPEC_DESIGNED_RESERVOIR.md` (tracked ledgers)

```
python scripts/g3_mechanism_classification.py --classify
python scripts/g3_mechanism_classification.py --emit-report
python -m unittest tests.test_g3_mechanism_classification
```
