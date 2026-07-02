# Effective independent evidence - market-story clusters (K2)

How many distinct market stories sit behind the accepted track-record rows? This is a read-only honesty layer over the accepted corpus: rows are grouped into descriptive market-story clusters so a reviewer can weigh the nominal row count against date clustering, repeated tickers, and duplicate links. It adds **no new score, no ranking, and no inference**.

## What a reviewer should take away first

- The 86 accepted track-record rows group into 5 descriptive market-story clusters under three transparent rules -- they are not 86 independent market stories.
- 83 of 86 rows (96.5%) sit in 2 multi-row clusters; the largest single cluster holds 81 rows.
- The largest clustering pressure is shared event dates: 82 rows are touched by it.
- This does not invalidate the archive; it makes the interpretation more honest. Clustered rows remain real archive evidence -- they are one story observed several times, not several stories.

## Scope and non-claims

- Accepted track-record rows only (**86** rows); staged candidates (**13**) are excluded.
- Read-only archive description; the database is opened read-only and nothing is written.
- Descriptive grouping, not inference: this report is not a p-value, an FDR pool, a score, a rank, a signal, a forecast, or a recommendation.
- The cluster count is an independence caution, not an inferential effective sample size; no statistical independence is claimed for any row or cluster.
- Clustered rows are not invalid and singleton rows are not proof; no causal claim is made.
- Representative cases remain illustrative walkthrough material, not evidence of any mechanism.
- No family-level inference; family lenses are context columns only.
- The closed Phase 1 / Phase 2 FDR pools are neither read nor touched.
- Not a recommendation, forecast, or trading signal.

## Method in plain English

Two rows are grouped into one market-story cluster when any of these transparent rules links them, directly or through a chain:

- **Same event date** - their 1d/5d/20d reaction windows sit on the same tape day, so the market readouts are the same tape, whatever the headlines say.
- **Same primary ticker within 20 calendar days** - the same price series is being re-read over overlapping reaction windows.
- **Duplicate links** - the event-date-quality layer already marked the rows as same-announcement collisions.

Mechanism families are shown as context only; they play no part in the grouping. The rules are deliberately conservative about claiming separateness: chained links merge (a row 19 days from the next can chain a long same-ticker run into one cluster), and same-date rows on different tickers still share one tape day. Cross-ticker window overlap on *different* dates is NOT grouped here - that stricter lens is reported as the 20d-window capacity line below and would group even more aggressively. The method is descriptive grouping, not inference.

## Denominator ledger (live, unchanged)

archive **180** - accepted coverage **94** - accepted track-record **86** - event-study **78/94** - staged **13** (excluded).

K2 reads the **accepted track-record** lens (**86** rows): it is the corpus the track-record split is quoted from, so it is where an inflated nominal row count would mislead a reviewer most.

## Cluster summary

| measure | value |
| --- | --- |
| nominal accepted track-record rows | 86 |
| market-story clusters | **5** |
| singleton clusters | 3 |
| multi-row clusters | 2 |
| rows in multi-row clusters | 83 (96.5%) |
| largest cluster size | 81 |
| top clustered dates | 2026-04-05 (21 rows), 2026-04-06 (13 rows), 2026-04-29 (12 rows) |
| top repeated primary tickers | XLE (25 rows), XOM (8 rows), DRIV (6 rows) |
| event-study rows inside multi-row clusters | 67 |
| event-study rows on singletons | 3 |
| max non-overlapping 20d windows (C1-style caution) | 3 |

The 20d-window capacity line is the stricter cross-ticker caution: even ignoring tickers and headlines, at most 3 mutually non-overlapping 20-day reaction windows exist among these rows' event dates. It is an upper-bound diagnostic in the C1 house convention, not an inferential effective sample size.

## Largest clusters

| cluster | rows | dates | primary tickers | S / C / U | ES | why grouped |
| --- | --- | --- | --- | --- | --- | --- |
| c01 | 81 | 2026-04-04 .. 2026-05-05 | AA, BAC, BDRY, BTU, ... | 42 / 8 / 31 | 67/81 | 12 shared event dates (top: 2026-04-05 x21, 2026-04-06 x13, 2026-04-29 x12); 9 repeated primary tickers (top: XLE x24, XOM x8, DRIV x6); 8 duplicate-linked row(s) |
| c02 | 2 | 2026-05-30 | XLE | 1 / 0 / 1 | 0/2 | shared event date(s) 2026-05-30 x2 |

Event ids per cluster:

- **c01** (2026-04-04 .. 2026-05-05 / mixed tickers): 2, 3, 4, 7, 8, 9, 11, 12, 16, 17, 25, 26, 29, 30, 31, 32, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 60, 61, 63, 64, 66, 70, 71, 72, 84, 85, 101, 105, 153, 154, 160, 206, 207, 208, 210, 211, 212, 213, 214, 215, 216, 217, 218, 219, 220, 225, 226, 231, 232, 233, 234, 235, 236, 237, 238, 239, 240, 250, 280, 281
- **c02** (2026-05-30 / XLE): 291, 292

Interpretation caution, per cluster: rows inside one cluster read overlapping reaction windows on one stretch of tape - weigh each cluster as one market story, not as its row count.

## Singleton / less-clustered rows

3 rows stand alone under these rules (no shared date, no repeated primary ticker inside the 20-day window, no duplicate link). These rows are **less exposed to this specific clustering issue** - nothing more. A singleton is still one n=1 descriptive read with its own anchor and scoring caveats; it is not proof of anything.

## Representative case overlay

Where the 15 representative walkthrough cases fall under the same grouping:

| case | family | outcome | cluster | cluster size | grouping | readout |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | tariff | support | c03 | 1 | singleton | available |
| 7 | geopolitical_conflict_context | support | c01 | 81 | multi-row | available |
| 29 | supply_shock | contradiction | c01 | 81 | multi-row | available |
| 38 | supply_shock | support | c01 | 81 | multi-row | available |
| 46 | monetary_policy_or_rates | support | c01 | 81 | multi-row | available |
| 61 | geopolitical_conflict_context | contradiction | c01 | 81 | multi-row | available |
| 66 | ceasefire_deescalation | support | c01 | 81 | multi-row | available |
| 71 | ceasefire_deescalation | support | c01 | 81 | multi-row | available |
| 153 | sanction | unresolved | c01 | 81 | multi-row | missing |
| 154 | sanction | unresolved | c01 | 81 | multi-row | missing |
| 160 | ceasefire_deescalation | unresolved | c01 | 81 | multi-row | missing |
| 210 | supply_shock | unresolved | c01 | 81 | multi-row | available |
| 211 | sanction | unresolved | c01 | 81 | multi-row | available |
| 212 | tariff | unresolved | c01 | 81 | multi-row | available |
| 239 | monetary_policy_or_rates | unresolved | c01 | 81 | multi-row | available |

- **Cases 7 / 29 / 38:** Cases 7, 29 and 38 share the 2026-04-05 event date and the XLE primary readout; under the stated rules they are one market-story cluster, not three separate pieces of market evidence.
- **Missing market readouts:** 153, 154, 160 - these cases still carry event-date and cluster context even though no window can be read; a missing readout is stated, never hidden.

## Reader guardrails

- Market-story clusters are a descriptive review aid; they are not an inferential effective sample size and no 'effective n' is claimed or implied.
- Clustered rows are not invalid; singleton rows are not proof.
- The cluster count is an independence caution, not a quality measure of the archive or of any family.
- No family-level inference: family lenses are context columns only.
- No causal claim; descriptive grouping, not inference.
- Not a trading signal, forecast, or recommendation.

## Reproduce (read-only)

```
python scripts/effective_independent_evidence_report.py --db-path events.db
python scripts/effective_independent_evidence_report.py --db-path events.db --json
```

Source lens: the accepted track-record rows (**86**), assembled from the event-date-quality layer (dates, anchor labels, duplicate links), the track-record scoring layer (canonical any-support outcomes), the event-study coverage layer (readout availability), and the representative case selection - all read-only (`mode=ro`); the database is never written. No provider, API, network, fetch, or backfill call is made.
