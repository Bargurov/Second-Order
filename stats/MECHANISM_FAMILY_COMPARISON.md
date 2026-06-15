# Mechanism-family comparison (I1)

A read-only, side-by-side comparison of the six accepted mechanism families so a
skeptical reviewer can see, in one place, where the accepted archive has mass and
where the denominators are too thin, overlay-only, or incomplete to say anything
beyond a descriptive archive read. It reuses E1's family inventory (counts) and
H1's reaction matrix (selected-case readout coverage); it computes no new score,
no threshold beyond the established thin-family flag, no inference, and no
significance. **No family is ranked, and none is asserted to be a stronger or
working family** — this is a descriptive read, not a contest.

## Denominator guardrail (live, unchanged)

archive **180** · accepted coverage **94** · accepted track-record **86** ·
event-study **78/94** · staged **13** (excluded). Headline overlay: single **52**
+ multi **16** + unclassified **18** = **86**. Case library: **15** selected
cases, **12** with a readout, missing **153, 154, 160**.

## Reproduce (read-only)

```
python scripts/mechanism_family_comparison_report.py --db-path events.db --json
python scripts/mechanism_family_comparison_report.py --db-path events.db
```

## Family comparison table

`S/C/U` = support / contradiction / unresolved (thesis-direction scoring). `ES`
= event-study available / family thesis rows (descriptive coverage only).
`selected` = representative case ids (F1/H1); `readouts` = how many of those have
a SPY-relative readout.

| family | status | n | S / C / U | ES | ES coverage | selected (readouts) |
| --- | --- | --- | --- | --- | --- | --- |
| supply_shock | canonical | 20 | 11 / 3 / 6 | 20/20 | complete | 210, 29, 38 (3/3) |
| geopolitical_conflict_context | overlay-only | 11 | 7 / 2 / 2 | 10/11 | partial | 61, 7 (2/2) |
| tariff | canonical | 11 | 5 / 0 / 6 | 8/11 | partial | 1, 212 (2/2) |
| sanction | canonical · thin | 4 | 0 / 0 / 4 | 1/4 | partial | 211, 153, 154 (1/3; missing 153, 154) |
| ceasefire_deescalation | canonical · thin | 3 | 2 / 0 / 1 | 2/3 | partial | 66, 71, 160 (2/3; missing 160) |
| monetary_policy_or_rates | overlay-only · thin | 3 | 1 / 0 / 2 | 2/3 | partial | 46, 239 (2/2) |

(Rows are in the canonical taxonomy order, not a ranking.)

## Comparison notes

- **Enough archive mass to inspect descriptively:** supply_shock, tariff,
  geopolitical_conflict_context (a larger accepted-family bucket is only more
  inspectable descriptively — a visible pattern is not inference).
- **Thin families (n <= 4):** sanction, ceasefire_deescalation,
  monetary_policy_or_rates — low-n blocks interpretation beyond a descriptive read.
- **Overlay-only buckets (outside the canonical taxonomy):**
  geopolitical_conflict_context, monetary_policy_or_rates.
- **Unresolved-heavy (unresolved >= support + contradiction):** tariff, sanction,
  monetary_policy_or_rates.
- **Contradiction present:** supply_shock, geopolitical_conflict_context.
- **Missingness blocks interpretation:** sanction (153, 154 missing readouts),
  ceasefire_deescalation (160 missing).
- Outside the per-family rows: 16 multi-match + 18 unclassified accepted thesis
  rows remain, not assigned to a single family.

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
