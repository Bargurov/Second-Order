# F3 basis restatement record - adjusted-preferred canonical policy adopted

**Status:** adoption and restatement record. The F2 basis-integrity exhibit
(`stats/BASIS_INTEGRITY.md`) recommended one stated canonical return basis;
this slice adopted it as the shared default of the event-study gate and
restated every affected published readout. No live database or cache was
mutated; no provider, fetch, or backfill call was made; no outcome label,
denominator, representative-case selection, event-date-quality label, or
closed FDR pool changed. This record maps the exact before/after.

## 1. Policy: old -> new

- **Old default (pre-F3):** matched raw/raw tried first, then matched
  adjusted/adjusted, then the two cross-basis pairs - an implementation
  fallback order, not a stated methodology, which left the published readout
  set mixing price returns (39 rows) with total returns (31 rows) by cache
  shape.
- **New canonical default (F3):**
  1. matched **adjusted/adjusted first** (total returns - the holder outcome
     including distributions);
  2. matched **raw/raw only as a fallback** when the adjusted pair is not
     computable;
  3. every fallback is **explicitly disclosed** in the payload
     (`basis_fallback` = `matched_raw_fallback`, with a note);
  4. **no cross-basis pair** in the default order - a series split across
     flags gates to `insufficient_data` rather than silently mixing an
     adjusted asset with a raw benchmark.
- The F2 forced-basis machinery (`flag_pairs=...`) is policy-exempt and
  unchanged: explicit callers can still force any pair, including cross
  pairs, for comparison work.

## 2. Final basis split (verified live, before == after sweep)

| pool | available | adjusted | raw fallback (disclosed) | status flips |
| --- | --- | --- | --- | --- |
| accepted track-record cohort | 70 / 70 | 69 | 1 (#50 GLD) | none |
| curated context rows (294-301) | 8 / 8 | 7 | 1 (#296) | none |
| staged / other gate-reachable rows | 13 / 13 | 13 | 0 | none |
| **total through the default gate** | **91 / 91** | **89** | **2** | **none** |

Availability is provably unchanged: no row anywhere resolved through a
cross-basis pair before this change (verified in the pre-change sweep), so
removing cross pairs from the default order could not and did not gate any
row out. The 78 / 94 coverage lens and every funnel figure are unchanged.

## 3. Exact changed rows and horizons - accepted cohort (36 rows)

Old -> new abnormal return (SPY-relative, %) per horizon at published 2dp
precision. Rows 45 and 211 flipped basis with values identical at every
horizon (not listed). "(same at 2dp)" = the underlying value moved by less
than the published rounding.

| row | primary | 1d AR% | 5d AR% | 20d AR% |
| --- | --- | --- | --- | --- |
| 1 (rep) | TSLA | -2.63 (unchanged) | -6.83 (unchanged) | -2.08 -> -1.50 |
| 2 | LMT | +1.95 (unchanged) | -5.06 (unchanged) | -28.13 -> -28.08 |
| 4 | DRIV | -0.13 (unchanged) | +2.89 (unchanged) | +11.76 -> +12.33 |
| 8 | DRIV | -0.13 (unchanged) | +2.89 (unchanged) | +11.76 -> +12.33 |
| 9 | DRIV | -0.13 (unchanged) | +2.89 (unchanged) | +11.76 -> +12.33 |
| 17 | CCL | +0.81 (same at 2dp) | +5.52 (same at 2dp) | -6.48 -> -5.91 |
| 25 | INDA | +0.81 (unchanged) | +2.16 (unchanged) | -5.17 -> -4.59 |
| 26 | BTU | -2.05 (same at 2dp) | -19.31 (same at 2dp) | -31.41 -> -30.83 |
| 42 | LMT | -1.64 (unchanged) | -6.98 (unchanged) | -27.74 -> -28.27 |
| 46 (rep) | DRIV | -0.19 (unchanged) | +4.10 (same at 2dp) | +11.63 (unchanged) |
| 48 | BTU | -3.28 (same at 2dp) | -17.90 (same at 2dp) | -28.68 (same at 2dp) |
| 49 | DRIV | -0.19 (unchanged) | +4.10 (same at 2dp) | +11.63 (unchanged) |
| 51 | DRIV | -0.19 (unchanged) | +4.10 (same at 2dp) | +11.63 (unchanged) |
| 52 | VLO | +2.36 (same at 2dp) | -6.43 -> -5.55 | -6.50 (same at 2dp) |
| 61 (rep) | BTU | -8.76 (same at 2dp) | -10.66 (same at 2dp) | -25.85 (same at 2dp) |
| 63 | CVX | -0.95 -> -1.89 | -7.35 -> -7.68 | -12.89 -> -12.83 |
| 71 (rep) | VLO | +0.43 -> +1.65 | -1.61 -> -0.37 | -8.28 -> -7.07 |
| 72 | VLO | +0.43 -> +1.65 | -1.61 -> -0.37 | -8.28 -> -7.07 |
| 80 | ADM | -0.85 -> -1.50 | -8.37 -> -9.00 | +2.81 -> +2.08 |
| 94 | BA | -0.82 -> -0.72 | -3.45 (unchanged) | -0.44 (unchanged) |
| 212 (rep) | TJX | -0.50 -> -0.89 | -3.52 -> -3.85 | -6.80 (unchanged) |
| 213 | VWO | -0.70 -> -0.18 | +0.37 (unchanged) | -3.65 (unchanged) |
| 214 | LMT | -0.87 -> -0.06 | -2.25 -> -2.91 | -0.67 -> -1.36 |
| 215 | XLE | +0.06 (unchanged) | -6.58 -> -6.57 | -9.57 (unchanged) |
| 217 | XLE | -2.73 -> -1.62 | -8.00 (unchanged) | -10.90 (unchanged) |
| 219 | XLE | +2.30 (unchanged) | +1.60 -> +1.32 | -6.70 (unchanged) |
| 232 | XLE | +2.41 -> +1.28 | -6.61 -> -7.71 | -6.76 -> -7.89 |
| 233 | AA | +0.62 -> +0.09 | -0.94 -> -1.48 | +19.45 -> +19.10 |
| 234 | XLE | +2.41 -> +1.28 | -6.61 -> -7.71 | -6.76 -> -7.89 |
| 235 | TSM | +0.52 -> +1.36 | +0.31 -> +1.17 | +3.37 -> +4.29 |
| 236 | DLR | -0.93 -> -0.40 | -4.86 (unchanged) | -10.71 (unchanged) |
| 238 | PDD | -0.74 -> -1.24 | -2.45 -> -2.97 | -16.95 -> -17.48 |
| 239 (rep) | BAC | -0.20 -> +0.10 | -1.41 -> -1.77 | -10.04 (unchanged) |
| 240 | GM | -0.26 -> +0.27 | +1.08 -> +1.64 | +3.26 -> +3.86 |
| 250 | GM | -0.26 -> +0.27 | +1.08 -> +1.64 | +3.26 -> +3.86 |
| 280 | XLE | -5.79 -> -5.51 | -5.42 -> -5.15 | -5.73 -> -5.45 |

## 4. Sign changes (all at 1d)

| row | primary | old 1d AR% | new 1d AR% |
| --- | --- | --- | --- |
| 239 (rep) | BAC | -0.20 | **+0.10** |
| 240 | GM | -0.26 | **+0.27** |
| 250 | GM | -0.26 | **+0.27** |

All three were predicted by the F2 exhibit; each carries cache evidence of
an adjustment-factor step inside its window. Outcome labels are computed
from the stored ticker fields, not from the gate, so no outcome changed.

## 5. Representative-case readout changes

Of the 15 representative cases (12 with readouts):

- **1 (TSLA):** 20d -2.08 -> **-1.50** (1d / 5d unchanged at 2dp).
- **71 (VLO):** 1d +0.43 -> **+1.65**, 5d -1.61 -> **-0.37**, 20d -8.28 ->
  **-7.07** - the F1 sector-lens basis caveat for this case is resolved.
- **212 (TJX):** 1d -0.50 -> **-0.89**, 5d -3.52 -> **-3.85** (20d
  unchanged at 2dp).
- **239 (BAC):** 1d -0.20 -> **+0.10** (sign change), 5d -1.41 -> **-1.77**,
  20d AR unchanged (-10.04; 20d CAR -9.78 -> -9.79).
- **46 (DRIV), 61 (BTU):** basis flipped; every printed value unchanged at
  2dp.
- **211 (FSLR):** basis flipped; values identical at every horizon.
- **7, 29, 38, 66 (XLE), 210 (XOM):** already on the adjusted basis;
  unchanged.
- **153, 154, 160:** no readout; unchanged.

Representative-case *selection* is untouched (same 15 ids, same roles).

## 6. Accepted vs contextual restatement split

- **Accepted cohort:** 38 basis flips, 36 rows with a value change at some
  horizon (section 3), 3 sign changes (section 4).
- **Curated context rows:** 7 of 8 flipped to adjusted with value changes
  (294, 295, 297, 298, 299, 300, 301); #296 is the disclosed raw fallback.
- **Staged / other rows (302-314):** all 13 flipped to adjusted with value
  changes. These feed dated, point-in-time packet exhibits (regulation /
  labor / sanction / industrial-policy / UAW), which record what was
  computed at their stated commit and are deliberately NOT restated - they
  remain historical records; any future reader recomputes current values
  with the reproduce commands they carry.

## 7. Surfaces regenerated / edited / unchanged

- **Generated-on-request surfaces (now emit new-policy values, nothing
  stored):** event-study coverage report, case-library reaction-matrix
  script output, sector-relative readout coverage, data-hygiene report, the
  live API event-study payloads (`routes/events.py` - responses now carry
  `basis_fallback` where applicable).
- **Hand-enriched tracked artifacts surgically edited (values only):**
  - `stats/CASE_LIBRARY_REACTION_MATRIX.md` - table rows 1 / 71 / 212 /
    239; the F1 sector section's case-71 bullet (basis caveat resolved) and
    sector-vs-market component paragraph (now 17 / 17 basis-matched rows,
    medians -0.61% / -7.48% / -10.36% at 1d / 5d / 20d, unique-window
    caution unchanged); a basis-policy pointer line.
  - `stats/EXPANDED_CASE_NOTES.md` - readout lines for cases 71 / 212 /
    239; a basis-policy pointer line.
  - `stats/BASIS_INTEGRITY.md` - adoption note at the top (its comparison
    tables are retained unchanged as pre-adoption decision evidence).
- **Explicitly unchanged:** accepted coverage 94; accepted track-record 86;
  event-study coverage 78 / 94; K2 clusters 86 / 7 / 79; c01 split
  42 / 8 / 29; representative-case selection; every outcome label;
  event-date-quality labels; closed Phase 1 / Phase 2 FDR pools;
  `stats/TRANSMISSION_CASE_WALKTHROUGH.md` (its quoted figures are
  unchanged at their printed precision);
  `stats/C01_MARKET_NARRATIVE.md` and
  `stats/MECHANISM_FAMILY_EVIDENCE_INVENTORY.md` (carry no AR values);
  `stats/METHODOLOGY.md` (states the beta-1 SPY-relative convention and is
  silent on close basis; the basis policy is stated here and in
  `stats/BASIS_INTEGRITY.md`); README; the frontend libraries (availability
  flags and counts only); all dated historical packet exhibits (section 6).

## 8. Guardrails and non-claims

- This is a counting/semantics restatement: the same events, the same
  windows, the same engine - one stated return basis instead of a
  cache-shape mixture. It creates no evidence and makes no mechanism read
  differently in kind.
- No live DB or cache mutation; the archive and price cache are
  byte-identical before and after.
- No outcome relabeling, no denominator change, no FDR change, no
  representative-case reselection, no new research layer.
- A total-return abnormal return is not a claim of statistical
  significance; no p-value, CI, or threshold is stated or implied.
- Not a recommendation of any trading action; no prediction about future
  returns of any asset.

## 9. Reproduce (read-only)

```
python scripts/basis_integrity_report.py --db-path events.db
python scripts/case_library_reaction_matrix.py --db-path events.db
python scripts/expanded_case_notes_report.py --db-path events.db
python scripts/sector_relative_readout.py --db-path events.db
```

The gate policy lives in `event_study_validation.build_event_study_validation`
(default `flag_pairs=None` = the F3 canonical order); the policy tests live in
`tests/test_event_study_validation.py::CanonicalBasisPolicyTests` and the
live-state assertions in `tests/test_basis_integrity_report.py`.
