# Mechanism-family evidence inventory (E1)

Read-only inventory of where the accepted archive has real evidence depth by
mechanism family, and where it is thin. It adds no new claim, no p-value, no
FDR pool, no forecast, and no trading language. Every figure is recomputed
read-only by `scripts/mechanism_family_evidence_inventory.py`; a clean clone
(empty archive) computes zero.

## Why the headline overlay is the family lens

Every accepted **thesis** row is stored `mechanism_family = 'none'`, so the
stored taxonomy gives no structure for the 86 track-record rows. The inventory
therefore groups the accepted thesis corpus by the tested J1 headline overlay
(`accepted_family_overlay_report.classify_headline`) and surfaces the
multi-match and unclassified buckets explicitly, rather than inventing a new
taxonomy. The 8 stored accepted **observations** (tariff/sanction) are the
coverage-only bridge to the stored taxonomy: they sit in the 94 coverage
denominator, not the 86 track-record denominator.

Two denominator lenses are kept separate at every row:

- **coverage lens** = 94 accepted rows; event-study availability is **78 / 94**.
- **track-record lens** = 86 accepted thesis rows; per-family event-study counts
  are `k of the family's thesis rows` on this lens, never against 94.

## Global denominators (live, as of the current frozen research block)

| quantity | value |
| --- | --- |
| archive rows | 180 |
| accepted coverage rows | 94 |
| accepted track-record rows | 86 |
| event-study available (coverage lens) | 78 / 94 |
| staged candidates (excluded) | 13 |
| families with accepted thesis rows | 6 |
| multi-family (ambiguous) rows | 16 |
| unclassified rows | 18 |

**Sum-invariant:** single-match `52` + multi-match `16` + unclassified `18`
= `86` = the accepted track-record denominator. This is asserted on every live
run; it is what proves no thesis row is silently dropped or double-counted.

**Independent-window capacity, global (track-record lens, 86 rows, 19 distinct
event dates):** 1d `19`, 5d `7`, 20d `3`. Diagnostic only: an upper-bound count
of mutually non-overlapping windows, not a true effective sample size; it runs
no cohort inference, adds no p-value or CI, validates no mechanism, changes no
FDR scope, and authorizes no pooling.

## Per-family table (track-record lens)

`v/c/u` = validated / contradicted / unresolved under the canonical any_support
rule (the existing `track_record_scoring` vocabulary, applied descriptively per
event). `ES` = thesis rows with a SPY-relative event-study readout, on the
track-record lens. Independent-window capacity (1d) is shown only at n >= 8 and
suppressed below it, to avoid a small-n count reading as an effective sample
size.

| family | taxonomy | n | v / c / u | ES (k/n) | distinct dates | date span | indep-window 1d |
| --- | --- | --- | --- | --- | --- | --- | --- |
| supply_shock | canonical | 20 | 11 / 3 / 6 | 20/20 | 11 | 2026-04-05 .. 2026-05-05 | 11 |
| geopolitical_conflict_context | overlay-only | 11 | 7 / 2 / 2 | 10/11 | 6 | 2026-04-05 .. 2026-05-01 | 6 |
| tariff | canonical | 11 | 5 / 0 / 6 | 8/11 | 9 | 2026-04-03 .. 2026-05-05 | 9 |
| sanction | canonical | 4 | 0 / 0 / 4 | 1/4 | 2 | 2026-04-23 .. 2026-04-29 | suppressed (n<8) |
| ceasefire_deescalation | canonical | 3 | 2 / 0 / 1 | 2/3 | 3 | 2026-04-08 .. 2026-04-24 | suppressed (n<8) |
| monetary_policy_or_rates | overlay-only | 3 | 1 / 0 / 2 | 2/3 | 3 | 2026-04-06 .. 2026-04-30 | suppressed (n<8) |

`overlay-only` families (geopolitical_conflict_context, monetary_policy_or_rates)
have no name in the canonical stored taxonomy; they are honest headline buckets
for real corpus mass the taxonomy cannot name, not an extension of the taxonomy.

### Top recurring sectors (best-effort descriptive mapping)

Sectors come from the existing descriptive ticker->sector classifier
(`sector_benchmark_suggestion_report._classify`, SPY-fallback "broad" rows
dropped as no-signal). It is best-effort: a family is blank where its names
carry no confident sector match. SPY stays the canonical benchmark; these are a
descriptive hint, not a sector-relative abnormal-return claim.

| family | top recurring sectors |
| --- | --- |
| supply_shock | energy (20) |
| geopolitical_conflict_context | energy (5), industrials (1) |
| tariff | consumer_discretionary (1), industrials (1) |
| ceasefire_deescalation | energy (2) |
| monetary_policy_or_rates | financials (3) |
| sanction | (no confident sector match) |

### Accepted observations bridge (the 94 vs 86 gap)

8 accepted curated observations carry a stored `mechanism_family` but no thesis
outcome: **tariff 4 + sanction 4**. They are in the coverage denominator (94),
not the track-record denominator (86). These are the same tariff/sanction
accepted rows the Evidence Overview shows; `94 - 86 = 8`.

## Representative examples (deterministic, illustrative only)

Selected under an explicit total order: one contradicted and one unresolved row
where they exist, remaining slots filled by event-study-available then lowest
event id, capped at three, displayed by event id. They illustrate a family;
they are not evidence for it.

| family | representative event ids |
| --- | --- |
| supply_shock | 29, 38, 210 |
| geopolitical_conflict_context | 7, 30, 232 |
| tariff | 1, 80, 212 |
| sanction | 153, 154, 211 |
| ceasefire_deescalation | 66, 71, 160 |
| monetary_policy_or_rates | 46, 231, 239 |

## Ambiguity, kept visible

- **Multi-family (16 rows).** Headlines matching more than one family, reported
  with all matched names and never tie-broken. Observed family pairs:
  `geopolitical_conflict_context x supply_shock` (the archive's core
  conflict-driven supply cluster), `ceasefire_deescalation x supply_shock`,
  `geopolitical_conflict_context x tariff`, `sanction x supply_shock`.
- **Unclassified (18 rows).** Headlines matching no family rule, kept visible
  rather than absorbed. The bucket visibly contains non-market / off-topic
  headlines that no taxonomy family should claim.

## Thin-family caveats

- **sanction (n=4):** every row unresolved (`0/0/4`), two event dates with 3 of
  the 4 rows sharing 2026-04-29 (still heavily date-clustered), and only 1 of 4
  with an event-study readout - the thinnest, most date-collapsed family.
- **ceasefire_deescalation (n=3), monetary_policy_or_rates (n=3):** below the
  low-n floor (5); independent-window capacity suppressed.
- **regulation, labor_inflation, industrial_policy:** zero accepted thesis
  matches - these canonical families exist only as staged candidates (consistent
  with the C3 staged-family finding), not as accepted evidence.
- Classification is headline-only; richer local fields (mechanism_summary,
  transmission_chain) are not used, so terse headlines under-classify.

## Non-claims

- Descriptive coverage decomposition only; this inventory adds no new claim.
- No pooled significance: no CI, p-value, or FDR is computed or implied.
- No family-level causal claim is established; per-family rows are post-hoc
  headline matches over small n.
- No family performance ranking and no across-family comparison is implied.
- Not a recommendation of any kind.
- Representative cases are illustrative, not evidence.
- The closed Phase 1 / Phase 2 FDR pools are neither read nor reopened.
- No paid analysis was run and none is approved.
- Denominators unchanged: 94 accepted coverage / 86 accepted track-record;
  staged candidates (13) are excluded and never classified here.

## Reproduce (read-only)

```
python scripts/mechanism_family_evidence_inventory.py --db-path events.db --json
python scripts/mechanism_family_evidence_inventory.py --db-path events.db
```
