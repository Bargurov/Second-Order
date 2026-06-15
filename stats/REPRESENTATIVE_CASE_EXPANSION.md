# Representative case expansion (F1)

A read-only, deterministic proposal for a broader representative case library
across mechanism families, so a finance reviewer can see the archive's
mechanisms, outcomes, weak spots, contradictions, and unresolved examples beyond
the six N1 anchors. It adds no new analysis, no p-values, no FDR, no forecast,
and no trading language. Every figure is recomputed read-only by
`scripts/representative_case_expansion_report.py`; a clean clone computes its own.

The family lens, per-family coverage, and denominators are taken verbatim from
the E1 inventory (`mechanism_family_evidence_inventory.build_inventory`) so this
report cannot drift from E1. Candidate pools reuse E1's accepted-row loader,
grouped by the same tested headline overlay and scored by the same canonical
any_support rule.

## Global denominators (live)

| quantity | value |
| --- | --- |
| archive rows | 180 |
| accepted coverage rows | 94 |
| accepted track-record rows | 86 |
| event-study available (coverage lens) | 78 / 94 |
| staged candidates (excluded) | 13 |
| multi-family (ambiguous) rows | 16 |
| unclassified rows | 18 |

## Baseline N1 cases

The N1 walkthrough cases are carried as already-covered anchors (one per family
on the live archive) and are never rewritten here. They are illustrative anchors
only, not representative evidence; this expansion broadens family and outcome
coverage around them.

| event_id | family | outcome |
| --- | --- | --- |
| 1 | tariff | support |
| 61 | geopolitical_conflict_context | contradiction |
| 210 | supply_shock | unresolved |
| 46 | monetary_policy_or_rates | support |
| 66 | ceasefire_deescalation | support |
| 211 | sanction | unresolved |

## Selection policy (deterministic)

Per family the library = anchors + new picks, **capped at 3 total (including the
N1 anchor)**. New picks fill the remaining slots in order **support ->
contradiction -> unresolved**, then by **(event-study-available first, lowest
event_id)**. Thin families (n <= 4) keep their unresolved cases rather than
dropping them. Multi-match and unclassified rows are surfaced as counts, never
selected. Staged candidates are excluded.

Global target **12-15 total** (hard max 18 = six families x cap 3). When the
per-family selection exceeds the target, only **new** picks are trimmed (anchors
never removed, a family's last entry never dropped). The trim removes
**duplicate same-outcome extras first** (an outcome already covered by the
family's anchor or an earlier diversifying pick) and **protects one support
example for each material (non-thin) family** so the largest family is never
left without a support case; contradiction / unresolved examples are protected
above duplicates. Within a tier: non-thin before thin, missing-readout before
event-study-available, higher event_id before lower. On the live archive the
natural selection of 18 is trimmed to 15 by removing three duplicate
same-outcome extras (31 tariff duplicate-support, 30 geopolitical
duplicate-contradiction, 231 monetary duplicate-unresolved), so supply_shock
keeps its support example and every family keeps a diverse, non-duplicated set.

## Family coverage table

`S / C / U` = support / contradiction / unresolved (canonical any_support rule,
applied descriptively). `ES` = thesis rows with a SPY-relative readout on the
86 track-record lens. `library` = anchor + new selected for this report.

| family | taxonomy | n | S / C / U | ES | library (anchor + new) |
| --- | --- | --- | --- | --- | --- |
| supply_shock | canonical | 20 | 11 / 3 / 6 | 20/20 | 3 (210 + 38, 29) |
| geopolitical_conflict_context | overlay-only | 11 | 7 / 2 / 2 | 10/11 | 2 (61 + 7) |
| tariff | canonical | 11 | 5 / 0 / 6 | 8/11 | 2 (1 + 212) |
| sanction | canonical · thin | 4 | 0 / 0 / 4 | 1/4 | 3 (211 + 153, 154) |
| ceasefire_deescalation | canonical · thin | 3 | 2 / 0 / 1 | 2/3 | 3 (66 + 71, 160) |
| monetary_policy_or_rates | overlay-only · thin | 3 | 1 / 0 / 2 | 2/3 | 2 (46 + 239) |

Thin families (n <= 4) are selected up to the cap with unresolved kept;
non-thin families are capped at 3 (anchor + new). All three canonical families
absent from the accepted thesis corpus (regulation, labor_inflation,
industrial_policy) stay staged-only and are not in this library.

## Proposed expanded case library (15 cases)

6 N1 anchors + 9 newly proposed. `dq` = event-date-quality anchor label (research
caution, from the event-date-quality report).

| role | event_id | family | outcome | event-study | dq |
| --- | --- | --- | --- | --- | --- |
| anchor | 210 | supply_shock | unresolved | yes | clean_discrete_anchor |
| new | 38 | supply_shock | support | yes | manual_review_needed |
| new | 29 | supply_shock | contradiction | yes | duplicate_or_deferred |
| anchor | 61 | geopolitical_conflict_context | contradiction | yes | partial_anticipation |
| new | 7 | geopolitical_conflict_context | support | yes | manual_review_needed |
| anchor | 1 | tariff | support | yes | partial_anticipation |
| new | 212 | tariff | unresolved | yes | clean_discrete_anchor |
| anchor | 211 | sanction | unresolved | yes | scheduled_or_weak_anchor |
| new | 153 | sanction | unresolved | no | scheduled_or_weak_anchor |
| new | 154 | sanction | unresolved | no | manual_review_needed |
| anchor | 66 | ceasefire_deescalation | support | yes | scheduled_or_weak_anchor |
| new | 71 | ceasefire_deescalation | support | yes | scheduled_or_weak_anchor |
| new | 160 | ceasefire_deescalation | unresolved | no | partial_anticipation |
| anchor | 46 | monetary_policy_or_rates | support | yes | scheduled_or_weak_anchor |
| new | 239 | monetary_policy_or_rates | unresolved | yes | manual_review_needed |

Newly proposed ids: 7, 29, 38, 71, 153, 154, 160, 212, 239.

The largest family, supply_shock, is represented by all three outcomes -
support (38), contradiction (29), and unresolved (210) - rather than by a
contradiction and unresolved alone.

## Expansion summary

- total proposed: **15** (within the 12-15 target)
- already in N1: **6**; newly proposed: **9**
- family diversity: all **6** families with accepted thesis rows
- outcome diversity: support, contradiction, and unresolved all present
- event-study coverage: **12 of 15** selected cases have a SPY-relative readout
- contradictions present (29, 61); unresolved present (multiple, incl. all of sanction)
- the largest family (supply_shock) shows support, contradiction, and unresolved

## Missingness / thin-family caveats

- **sanction (n=4):** every row unresolved, single-date clustered, only 1/4 with
  a readout - the thinnest, most date-collapsed family; the library keeps its
  unresolved cases rather than hiding the gap.
- **ceasefire_deescalation, monetary_policy_or_rates (n=3):** below the thin
  floor; unresolved cases kept with caution.
- **event-study gaps:** 153, 154, 160 have no readout (surfaced, not dropped).
- **event-date quality:** several anchors are partial-anticipation / scheduled /
  manual-review-needed - flagged per case as research caution, not removed.
- **classification:** headline-overlay lens; 16 multi-match and 18 unclassified
  rows are not selected but are reported as counts.

## Non-claims

- Illustrative case library only; this report adds no new claim.
- Representative cases are illustrative, not evidence and not family-level inference.
- No pooled significance: no CI, p-value, or FDR is computed or implied.
- No family performance ranking and no across-family comparison is implied.
- Not a recommendation of any kind.
- The closed Phase 1 / Phase 2 FDR pools are neither read nor reopened.
- No paid analysis was run and none is approved.
- Denominators unchanged: 94 accepted coverage / 86 accepted track-record;
  staged candidates (13) are excluded and never selected here.

## Reproduce (read-only)

```
python scripts/representative_case_expansion_report.py --db-path events.db --json
python scripts/representative_case_expansion_report.py --db-path events.db
```
