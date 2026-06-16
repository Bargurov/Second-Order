# Mechanism-family comparison (I1)

A read-only, side-by-side comparison of the six accepted mechanism families,
written for a finance reviewer: where the accepted archive has mass and where the
denominators are too thin, overlay-only, or incomplete to say anything beyond a
descriptive archive read. It reuses E1's family inventory (counts) and H1's
reaction matrix (selected-case readout coverage); it computes no new score, no
threshold beyond the established thin-family flag, no inference, and no
significance. **No family is ranked, and none is asserted to be a stronger or
working family** — this is a descriptive read, not a contest.

## What to take away first

- supply_shock is the largest inspectable bucket (n=20) with complete
  event-study coverage, but it is still a descriptive archive read, not evidence
  of a family effect.
- geopolitical_conflict_context is sizable (n=11) but overlay-only — a useful
  conflict-context lens, not part of the stored canonical taxonomy.
- tariff is sizable (n=11) but unresolved-heavy: more cases ended unresolved than
  supported or contradicted.
- sanction, ceasefire_deescalation, and monetary_policy_or_rates are thin
  (n <= 4): useful as walkthrough examples, not family-level evidence.
- Representative cases are walkthrough material, not evidence — they illustrate a
  family, they do not establish it.
- Market readout coverage helps locate where a reaction can be inspected; it is
  availability, not thesis support.

## How to read the table

- **n** — accepted track-record rows in that family.
- **S / C / U** — support / contradiction / unresolved thesis-direction outcomes
  (scoring of the named tickers).
- **ES** — event-study availability: how many family rows have a SPY-relative
  readout. This is availability, not success.
- **selected cases** — the representative walkthrough examples chosen for that
  family.
- **status** — canonical (in the stored taxonomy), overlay-only, or thin.
- **readout coverage** — whether the selected examples have 1d / 5d / 20d market
  reactions available.

Definitions: an *overlay-only* bucket is a headline-overlay lens outside the
stored canonical taxonomy; *thin* means too few rows (n <= 4) to read at the
family level.

## Denominator guardrail (live, unchanged)

archive **180** · accepted coverage **94** · accepted track-record **86** ·
event-study **78/94** · staged **13** (excluded). Headline overlay: single **52**
+ multi **16** + unclassified **18** = **86**. Case library: **15** selected
cases, **12** with a readout, missing **153, 154, 160**.

## Family comparison table

| family | status | n | S / C / U | ES | ES coverage | selected (readouts) |
| --- | --- | --- | --- | --- | --- | --- |
| supply_shock | canonical | 20 | 11 / 3 / 6 | 20/20 | complete | 210, 29, 38 (3/3) |
| geopolitical_conflict_context | overlay-only | 11 | 7 / 2 / 2 | 10/11 | partial | 61, 7 (2/2) |
| tariff | canonical | 11 | 5 / 0 / 6 | 8/11 | partial | 1, 212 (2/2) |
| sanction | canonical · thin | 4 | 0 / 0 / 4 | 1/4 | partial | 211, 153, 154 (1/3; missing 153, 154) |
| ceasefire_deescalation | canonical · thin | 3 | 2 / 0 / 1 | 2/3 | partial | 66, 71, 160 (2/3; missing 160) |
| monetary_policy_or_rates | overlay-only · thin | 3 | 1 / 0 / 2 | 2/3 | partial | 46, 239 (2/2) |

(Rows are in the canonical taxonomy order, not a ranking.)

## Family-by-family notes

- **supply_shock** — largest accepted bucket (n=20) with complete event-study
  coverage; it has support, contradiction, and unresolved outcomes, so it is the
  most inspectable descriptively — still a descriptive archive read, not a
  family-level conclusion.
- **geopolitical_conflict_context** — sizable (n=11) but overlay-only: a useful
  conflict-context lens, not part of the stored canonical taxonomy.
- **tariff** — sizable (n=11) with partial event-study coverage and
  unresolved-heavy outcomes; useful to inspect, but not a clean family-level read.
- **sanction** — thin (n=4) and unresolved-heavy; its examples show missingness
  and limits more than a pattern.
- **ceasefire_deescalation** — thin (n=3); useful as de-escalation examples, not
  a family-level conclusion.
- **monetary_policy_or_rates** — thin (n=3) and overlay-only; informative as
  individual cases, not a stable family read.

## Comparison notes

- **Enough archive mass to inspect descriptively:** supply_shock, tariff,
  geopolitical_conflict_context.
- **Thin families (n <= 4):** sanction, ceasefire_deescalation,
  monetary_policy_or_rates.
- **Overlay-only buckets:** geopolitical_conflict_context, monetary_policy_or_rates.
- **Unresolved-heavy:** tariff, sanction, monetary_policy_or_rates.
- **Contradiction present:** supply_shock, geopolitical_conflict_context.
- **Missingness blocks interpretation:** sanction (153, 154 missing readouts),
  ceasefire_deescalation (160 missing).
- Outside the per-family rows: 16 multi-match + 18 unclassified accepted thesis
  rows remain, not assigned to a single family.

## Reader guardrails

- Do not rank one family above another; this is a descriptive read, not a contest.
- The support count is not a score or a success rate.
- Event-study coverage is availability, not success; it is not evidence that a
  thesis held.
- Do not collapse outcome counts and market readouts into one score.
- The closed Phase 1 / Phase 2 FDR pools remain separate from this descriptive read.

## Lens discipline

- Outcome counts (S/C/U) are **thesis-direction scoring** of the named tickers.
- Readouts are the **primary ticker's abnormal return vs SPY** (the H1 matrix) —
  a different lens; 29 and 38 share a readout but carry opposite outcomes.
- Representative cases are **walkthrough material**, not a family verdict.
- Do not collapse these into one success metric.

## Caveats / non-claims

- Descriptive archive read only; this comparison adds no new claim and no new score.
- No family-level inference; counts and coverage are descriptive — a visible
  pattern is not inference.
- No statistical-significance claim; no CI, p-value, or FDR, and the descriptive
  archive is not merged with the closed Phase 1 / Phase 2 FDR pools.
- No family is ranked above another; this is a side-by-side descriptive read.
- Not a recommendation, forecast, or trading signal.
- Denominators unchanged: 94 accepted coverage / 86 accepted track-record;
  staged candidates (13) are excluded.

## Reproduce (read-only)

```
python scripts/mechanism_family_comparison_report.py --db-path events.db --json
python scripts/mechanism_family_comparison_report.py --db-path events.db
```
