# F2 basis-integrity report - canonical return-basis policy (read-only)

> **Adopted (F3).** The section 7 recommendation - matched adjusted/adjusted
> preferred, matched raw/raw as the only disclosed fallback, no cross-basis
> pair - was adopted as the canonical default gate policy by the F3
> restatement slice. `stats/BASIS_RESTATEMENT.md` is the adoption record with
> the final basis split and every restated value. The figures below describe
> the PRE-adoption state (the 39 raw / 31 adjusted mixture) and the forced-
> basis comparison that motivated the policy; they are retained unchanged as
> the decision evidence.

**Status:** read-only comparison exhibit and policy memo. It restates nothing:
every published readout, outcome label, denominator, representative case, and
closed Phase 1 / Phase 2 pool is unchanged by this note. `events.db` was read
via the existing cached-close path only; no provider, fetch, backfill, or
write of any kind. Adoption of the recommended policy happened in the separate
F3 restatement slice (section 8 mapped its surface).

## 1. What a reviewer should take away first

- **The canonical readout set currently mixes two return definitions by cache
  accident, not by policy.** Of the 70 canonical readouts, 39 are computed on
  raw closes (price returns) and 31 on adjusted closes (total returns),
  because the gate tries the matched raw/raw basis first and falls back. No
  methodology document chose that mixture.
- **The mixture is mostly benign but not everywhere:** of the 38 rows
  computable on both bases, 9 are negligible (<10bp at every horizon) and the
  medians are small (|delta| 0.05% at 1d, 0.00% at 5d, 0.31% at 20d) - but
  **8 rows are materially basis-sensitive** (>=100bp at some horizon or a
  1d sign change), and every one of the 8 carries cache evidence of an
  adjustment-factor step inside its window (a step in the adjusted/raw close
  ratio). None is unexplained.
- **Three 1d sign changes exist, one on a representative case:** #239 (BAC,
  an F1/K2 representative case) reads -0.20% at 1d on the current raw basis
  and **+0.10%** on the total-return basis; #240 / #250 (GM) flip likewise.
- **A total-return-preferred policy costs almost nothing on this cache:**
  forced adjusted/adjusted computes 69 of 70 rows (the single exception is
  #50, GLD, whose adjusted pair has no contiguous aligned window), while
  forced raw/raw computes only 39 of 70. An adjusted-first fallback keeps
  availability at 70/70 with a 69/1 mixture instead of today's 39/31.
- **Recommendation (PM guidance, section 7): adopt the adjusted-first
  fallback as the stated canonical basis policy**, in a separate gated
  restatement slice. This is a counting/semantics policy, not a claim that
  any mechanism reads differently.

## 2. Denominator reconciliation (stated before any result)

This exhibit's cohort is **70** rows. The archive's familiar event-study
figure is **78 / 94**. The two reconcile exactly:

| pool | count | composition |
| --- | --- | --- |
| accepted coverage denominator | 94 | 86 accepted track-record + 8 curated context rows |
| event-study available (coverage lens) | 78 | 70 accepted + 8 curated (ids 294-301), all available |
| **this exhibit's cohort** | **70** | accepted track-record rows with an available canonical readout |
| accepted, no primary ticker | 13 | ids 153, 154, 160, 206, 207, 208, 216, 220, 226, 231, 237, 281, 292 |
| accepted, primary blocked by data gates | 3 | ids 31, 101, 291 |

The 8 curated rows are excluded because they are curated context (a separate
lens), not accepted track-record evidence. 70 + 13 + 3 = 86; 70 + 8 = 78.

## 3. Method (read-only)

- Each cohort row is recomputed by the same gated engine under a **forced
  matched raw/raw** basis and a **forced matched adjusted/adjusted** basis
  (`build_event_study_validation(..., flag_pairs=...)`); a forced basis that
  is not computable is reported `insufficient_data` - never a silent
  fallback, never an approximation.
- Deltas are per-horizon `adjusted AR - raw AR` on rows where BOTH bases
  compute; rows computable on one basis only are labeled, not compared.
- A difference is flagged as an adjustment-factor step **only** when the cache
  itself shows one: a day-over-day step larger than 5bp in the asset's
  adjusted/raw close ratio strictly inside the forward window; the specific
  cause (dividend, split, or other) is not classified. Rows without that
  evidence would be labeled basis-sensitive with cause unresolved
  (live: none - all 8 material rows carry the step evidence).
- Bucket cuts (<10bp / 10-50bp / 50-100bp / >=100bp) and the >=100bp-or-sign-
  change materiality line are descriptive cuts, not significance thresholds.

## 4. Availability under each basis

| lens | rows |
| --- | --- |
| cohort | 70 |
| computable on forced raw/raw | 39 |
| computable on forced adjusted/adjusted | 69 |
| computable on both bases | 38 |
| raw-only | 1 (#50 GLD - adjusted pair: no contiguous aligned window) |
| adjusted-only | 31 (raw pair fails the same gates the current fallback already routes around) |
| neither | 0 |

## 5. Delta distribution and sign changes (38 both-bases rows)

| horizon | <10bp | 10-50bp | 50-100bp | >=100bp | median abs | max abs |
| --- | --- | --- | --- | --- | --- | --- |
| 1d | 19 | 4 | 10 | 5 | 0.05% | 1.22% |
| 5d | 21 | 5 | 8 | 4 | 0.00% | 1.24% |
| 20d | 18 | 2 | 14 | 4 | 0.31% | 1.21% |

Sign changes (all at 1d): #239 BAC -0.20% -> +0.10%; #240 GM -0.26% ->
+0.27%; #250 GM -0.26% -> +0.27%.

## 6. Materiality tiers

- **Negligible (9 rows):** |delta| < 10bp at every horizon - basis choice is
  immaterial for these.
- **Minor band (remaining both-bases rows):** 10-100bp differences,
  concentrated at 20d (14 rows in the 50-100bp bucket) - the size of a
  distribution paid inside a 20-day window.
- **Materially basis-sensitive (8 rows, all with cache evidence of an
  adjustment-factor step in the window):**

| row | primary | date | max abs delta | 1d sign change |
| --- | --- | --- | --- | --- |
| 71 | VLO | 2026-04-09 | 1.24% | no |
| 72 | VLO | 2026-04-09 | 1.24% | no |
| 232 | XLE | 2026-05-01 | 1.13% | no |
| 234 | XLE | 2026-05-01 | 1.13% | no |
| 217 | XLE | 2026-04-30 | 1.11% | no |
| 240 | GM | 2026-05-01 | 0.60% | yes |
| 250 | GM | 2026-05-02 | 0.60% | yes |
| 239 | BAC | 2026-04-29 | 0.36% | yes |

Worked example (#239 BAC, representative case): current published readout
-0.20% / -1.41% / -10.04% (1d/5d/20d, raw basis). On the total-return basis
it reads **+0.10% / -1.77% / -10.04%**. The 20d figure is identical (no
ratio step spans that comparison); the 1d sign flips.

This also resolves the F1 sector-lens cross-basis exclusions: rows 52 / 63 /
71 / 72 mismatched precisely because the SPY lens landed on raw while the
sector lens landed on adjusted; one stated basis policy removes that class
of artifact.

## 7. Policy comparison and recommendation

| policy | availability | semantics | mixture |
| --- | --- | --- | --- |
| current raw-first fallback | 70/70 | mixed by cache shape | 39 raw / 31 adjusted |
| raw-only | 39/70 | price returns everywhere | - (31 rows lost) |
| adjusted-only | 69/70 | total returns everywhere | - (1 row lost) |
| **adjusted-first fallback (recommended)** | **70/70** | **total returns preferred, price-return fallback disclosed** | **69 adjusted / 1 raw** |

**Recommendation (PM guidance): adjusted-first fallback.**

- *Semantic consistency:* 69/70 rows on one stated definition (total
  returns), one disclosed exception - versus today's 39/31 cache-shape
  mixture that no document chose.
- *Finance interpretability:* a total-return abnormal return measures the
  holder outcome including distributions; on the raw basis a distribution
  paid inside the window lands in the "abnormal" return as a spurious
  negative. The 8 material rows each carry an adjustment-factor step in the
  cached adjusted/raw close ratio inside the window - consistent with such a
  distribution - but the cache evidences only the ratio step, not the
  specific corporate action: it does not distinguish a dividend from a split
  or any other adjustment.
- *Availability:* zero cost (70/70, identical to current).
- *Reproducibility:* the basis becomes a stated policy verified by the
  forced-pair machinery, not an artifact of which series happened to align
  first.
- *Compatibility:* 38 both-basis rows move by <10bp in half the cases and
  medians are small; the 8 material moves are evidence-backed adjustment-
  factor-step rows, and no outcome label, denominator, cluster count, or FDR
  figure depends on the gate (outcomes score the stored ticker fields, a
  different layer).

The historical rationale for raw-first - broadest raw SPY coverage - is
empirically moot on the current cache (adjusted computes 69/70). Raw-only is
rejected outright (availability collapses to 39/70). Keeping the current
mixture is defensible only with a disclosure that the basis is per-row
arbitrary; a stated policy is strictly more honest.

## 8. Exact restatement surface if the policy is adopted (gated, NOT done here)

Adopting adjusted-first changes published per-horizon AR/SAR/CAR values for
up to 39 rows (those currently on raw basis; 8 materially). The surfaces:

- **Generated outputs (regenerate):** event-study coverage report;
  `case_library_reaction_matrix` JSON/text; `sector_relative_readout`
  coverage (the same gate feeds both lenses; the F1 exclusions shrink).
- **Tracked hand-enriched artifacts (surgical edits):**
  `stats/CASE_LIBRARY_REACTION_MATRIX.md` (readout cells + sector section),
  `stats/EXPANDED_CASE_NOTES.md` (per-case readout blocks),
  `stats/TRANSMISSION_CASE_WALKTHROUGH.md` (N1 dossier readouts).
- **Live API behavior:** `routes/events.py` serves gate payloads computed on
  request; responses change with the policy (no stored restatement, but the
  change must be release-noted).
- **Explicitly unchanged:** outcome labels (scored from stored ticker
  fields, not the gate), accepted denominators (94 / 86), K2 clusters
  (date/ticker/link-based), representative-case selection, event-date
  quality labels, closed Phase 1 / Phase 2 pools,
  `stats/MECHANISM_FAMILY_EVIDENCE_INVENTORY.md` (carries no AR values),
  `stats/C01_MARKET_NARRATIVE.md` (cluster membership, outcome labels, and a
  readout-availability flag - not AR values), and the frontend
  representative-case library (availability flags, not AR values).

## 9. Guardrails and non-claims

- Descriptive comparison only: no p-value, no CI, no FDR, no significance
  threshold, no new statistical model.
- Nothing was restated: this exhibit changes no published number.
- Adjustment-factor-step attribution rests solely on the cached adjusted/raw
  ratio step inside the window; the specific corporate action is not
  identified and no external source was consulted.
- Availability reflects the current cache; nothing was fetched, backfilled,
  or approximated.
- The section 7 recommendation is an internal counting/semantics policy
  judgment; it is not investment advice, implies no direction on any asset,
  and says nothing about future returns.

## 10. Reproduction (read-only)

```
python scripts/basis_integrity_report.py --db-path events.db
python scripts/basis_integrity_report.py --db-path events.db --json
```

- Engine: `stats/event_study.py` (untouched); gate:
  `event_study_validation.build_event_study_validation` with the new
  `flag_pairs` override (default `None` = canonical order, byte-identical
  for every existing caller; verified by the existing gate suites).
- Cohort and reconciliation recomputed live against `events.db` (SHA-256
  `18aa372e...` unchanged before and after; `price_cache.db` 0 bytes,
  untouched).
