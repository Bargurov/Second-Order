# L1 anchor repair - first source-pinned batch selection (L1A)

**Status:** read-only selection packet. No event row was edited, no date was
changed, no status was changed, and the database was opened read-only. This
packet is the worklist for the next mutation task (L1B); it repairs nothing
itself.

## 1. What a reviewer should take away first

- This is the **first repair batch, not a new result.** K2 showed the 86
  accepted track-record rows collapse into 5 market-story clusters (one
  81-row cluster, c01); the c01 narrative note showed that cluster mixes a
  coherent Iran / Hormuz energy tape with adjacent macro and
  ticker-attribution noise. Describing that weakness again adds nothing;
  the next unit of work is repairing the underlying rows.
- **14 rows are selected** for source-pinned anchor repair - all accepted
  track-record rows, all inside c01, 10 of them `manual_review_needed`,
  8 of them representative walkthrough cases.
- The batch is meant to improve four things: (a) the anchor dates behind
  the most reviewer-visible cases (including the 7/29/38 triplet and the
  missing-readout tail 153/154/160), (b) the duplicate structure that
  C4's same-date rule could not see - **same-story re-ingestion across
  consecutive dates** (e.g. rows 2 -> 49, 30 -> 42, and the OPEC-extend
  saga 39/53/54/64/70), (c) the noisy primary-ticker attribution the c01
  note exposed (DRIV rows; one LMT row), and (d) honesty about rows whose
  stored fields cannot support a pinned anchor at all.
- Selection is evidence-weighted, not convenience-weighted: every row is
  chosen because its repair changes how the archive reads, not because it
  is easy.

## 2. Selection rules

- Accepted track-record rows only (86-row lens); staged, synthetic-seed,
  and quarantined rows are ineligible.
- Prioritize `manual_review_needed` anchors; non-manual rows enter only
  with a specific reason (representative visibility, missing readout,
  duplicate-pair resolution).
- Prioritize representative / high-visibility rows: they anchor the
  walkthroughs, the reaction matrix, and the family comparison.
- Prioritize rows where a source-pinned repair can change interpretation:
  duplicate splits change counting; date corrections change windows;
  attribution review changes cluster membership.
- Prioritize rows where the c01 narrative exposed attribution noise
  (DRIV; the Artemis LMT row) or weak mechanism grounding.
- No DB writes in this task; no external fetching in this task. Source
  documents that must be consulted (executive orders, OPEC statements,
  the Fed calendar) are flagged as L1B work under the existing gated
  sourcing rules.

## 3. Candidate universe (live, read-only)

| measure | value |
| --- | --- |
| accepted track-record rows | 86 |
| `manual_review_needed` among them | 57 |
| duplicate_or_deferred among them | 8 (4 same-date pairs: 12/41, 29/37, 35/36, 53/54) |
| rows with no derived primary ticker | 13 |
| representative cases | 15 (14 inside c01) |
| c01 membership | 81 rows |
| missing representative readouts | 153, 154, 160 (all no-ticker, no event-study readout) |
| DRIV-primary rows (attribution noise per c01 note) | 6 - ids 4, 8, 9, 46, 49, 51 |
| LMT-primary rows | 3 - ids 2 (mis-assigned), 42, 214 |
| cross-date same-story re-ingestion found this pass | 2->49 (Artemis), 9->51 (UK crime), 30->42 (fighter jet, opposite outcomes), 39/53/54/64/70 (OPEC-extend), 40->44 (tanker), 25->50 (Foxconn), 43->60, 16->72, 26/48/61 (coal story x3) |

The cross-date re-ingestion row is the load-bearing new observation: the
C4 duplicate rule links only same-date collisions, so the archive carries
same-story copies re-saved one to four days apart under different tickers
- several with conflicting outcome labels. Anchor repair must treat these
as one story each.

## 4. Selected first batch (14 rows)

Legend - labels: MRN = manual_review_needed, DUP = duplicate_or_deferred,
SW = scheduled_or_weak_anchor, PA = partial_anticipation. All 14 rows are
accepted track-record rows inside cluster c01. "Local evidence" means
stored row fields (headline, what_changed, mechanism text, market note,
C4 anchor rationale) plus sibling rows carrying the same story; "missing"
names the source work L1B must do (gated).

| id | date | event (short label) | anchor | rep | ticker | family lens | outcome | ES | expected action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 7 | 2026-04-05 | US-Iran threats escalate (triplet) | MRN | yes | XLE | geopolitical | support | yes | confirm anchor |
| 29 | 2026-04-05 | Hormuz closure threat (triplet) | DUP (29/37) | yes | XLE | supply_shock | contradiction | yes | split/defer duplicate |
| 38 | 2026-04-05 | "big for oil and shipping" note (triplet) | MRN | yes | XLE | supply_shock | support | yes | mark source-insufficient |
| 30 | 2026-04-05 | US fighter jet downed over Iran | MRN | no | XOM | geopolitical | contradiction | yes | confirm anchor (canonical row of the pair) |
| 42 | 2026-04-06 | same fighter-jet story, re-ingested | MRN | no | LMT | geopolitical | support | yes | split/defer cross-date duplicate of 30 |
| 39 | 2026-04-05 | OPEC extend-cuts story (first of 5 copies) | MRN | no | XLE | supply_shock | contradiction | yes | correct date + anchor the saga (39/53/54/64/70) |
| 2 | 2026-04-04 | Artemis II Moon image (non-market) | MRN | no | LMT | unclassified | support | yes | review noisy ticker attribution |
| 49 | 2026-04-06 | same Artemis story, re-ingested | MRN | no | DRIV | unclassified | support | yes | split/defer cross-date duplicate of 2 |
| 9 | 2026-04-05 | UK murder-arrest item (non-market) | MRN | no | DRIV | unclassified | support | yes | review noisy ticker attribution |
| 46 | 2026-04-06 | Fed joint-findings release | SW | yes | DRIV | monetary | support | yes | review noisy ticker attribution + confirm anchor |
| 153 | 2026-04-29 | ICC sanctions executive order | SW | yes | none | sanction | unresolved | no | confirm anchor + add source note |
| 154 | 2026-04-29 | Kyrgyzstan / Russia-evasion call | MRN | yes | none | sanction | unresolved | no | mark source-insufficient or pin date |
| 160 | 2026-04-29 | Araghchi arrives ahead of talks | PA | yes | none | ceasefire | unresolved | no | confirm anchor + add source note |
| 239 | 2026-05-01 | Powell stays; rates held | MRN | yes | BAC | monetary | unresolved | yes | correct/confirm date against the Fed calendar |

Per-row why-selected, local evidence, missing evidence, and risk:

- **7 / 29 / 38 - the triplet.** Why: the sharpest known one-event-three-rows
  case; two outcomes disagree (29 contradiction vs 7/38 support); all three
  are representative cases carried in the walkthrough, matrix, notes, and
  comparison. Local evidence: three mutually corroborating headlines plus
  C4's 29<->37 duplicate link; row 38's mechanism text says evidence is
  insufficient. Missing: a primary-source timeline of the Apr-5 threat
  sequence to pin which row (if any) is the discrete anchor. Risk if
  unrepaired: the most-cited walkthrough cases keep triple-counting one
  event with contradictory labels. Note 38 is an editorial fragment with
  no identifiable primary source - the honest outcome may be
  "source-insufficient, preserve as manual with reason".
- **30 / 42 - fighter-jet pair.** Why: same story saved on consecutive
  dates under different tickers (XOM then LMT) with **opposite outcome
  labels** - a 7/29/38-class defect not caught by the same-date dup rule.
  Local evidence: near-identical headlines in both rows. Missing: pinning
  the actual incident date/session. Risk: one story contributes both a
  support and a contradiction to the ledger from two different windows.
- **39 (anchoring 53/54/64/70).** Why: the OPEC extend-cuts story appears
  five times across Apr 5-9 (one same-date dup pair 53/54 already linked;
  64/70 escaped) with outcomes flipping between copies; one pinned OPEC
  announcement date clarifies five rows at once. Local evidence: the five
  sibling rows; C4 53<->54 link. Missing: the actual OPEC/OPEC+ statement
  date. Risk: one cartel decision counted as up to five observations.
- **2 / 49 - Artemis pair; 9 - UK crime row.** Why: the c01 note's named
  attribution noise made concrete: non-market general-news rows carrying
  LMT/DRIV default tickers, all currently scored *support* in the
  track record; 2->49 is also a cross-date re-ingestion pair. Local
  evidence: the rows' own non-market content; the c01 asset-map finding.
  Missing: none - these are decidable from stored fields. Risk: the
  support count silently includes non-market noise; DRIV/LMT read as
  exposure where none exists. (Sibling noise rows 8 and 51 follow the
  same repair pattern and ride on this decision - see section 5.)
- **46 - Fed joint-findings (N1 walkthrough anchor).** Why: highest
  reviewer visibility of any DRIV artifact (it anchors the monetary
  family in the walkthrough and comparison); scheduled anchor + off-tape
  content + artifact ticker. Local evidence: stored fields identify the
  release; the c01 note flags the DRIV assignment. Missing: exact Fed
  release date confirmation. Risk: a family-anchor case rests on an
  attribution artifact.
- **153 / 154 / 160 - the missing-readout representative tail.** Why:
  required explicit consideration; all three are representative cases
  with no primary ticker and no readout; anchors are scheduled / manual /
  partial respectively. Local evidence: stored headlines and mechanism
  text (thin; 154's is explicitly insufficient); the ICC order (153) is
  a datable signing. Missing: source-pinned dates (ICC order text,
  Kyrgyzstan statement, arrival reporting); a considered decision on
  whether any primary exposure is even assignable. Risk: three of
  fifteen showcase cases remain unreadable and unpinned. 154 may
  honestly resolve to "source-insufficient".
- **239 - FOMC row.** Why: representative, manual anchor, and the one
  row in the batch where an authoritative public schedule (the Fed
  calendar) can pin the date exactly. Local evidence: stored fields name
  the decision and Powell statement. Missing: calendar confirmation of
  the meeting/statement date vs the stored 2026-05-01. Risk: a
  representative monetary case with an uncheckable window.

Selected-batch composition check: 14 rows; 10 MRN + 1 DUP + 2 SW + 1 PA;
8 representative; 14 of 14 in c01; 3 missing-readout cases; 5 touching
the DRIV/LMT noise; none clean_discrete_anchor; none staged, synthetic,
or quarantined.

## 5. Rows considered but not selected

| id(s) | reason not selected in batch 1 |
| --- | --- |
| 51, 8 | same repair pattern as 9 (DRIV general-news noise); decided by the same L1B ruling - no separate source work |
| 4 | DRIV row but genuinely Iran-linked (rescue coverage); needs the same attribution ruling, lower ambiguity value than 9 |
| 37, 53, 54, 64, 70 | ride on selected anchors (37 with 29; the OPEC saga with 39) - repairing the anchor row resolves the siblings |
| 12 / 41 | Primorsk refinery same-date dup pair, already C4-linked; mechanical split, saved for batch 2 |
| 35 / 36 | Kuwait drone-strike same-date dup pair, same situation |
| 26, 48 (with 61) | coal-substitution story x3; 61 (the representative contradiction) is PA not MRN, and the two repeats are mechanical; batch 2 |
| 40 / 44, 25 / 50, 43 / 60, 16 / 72 | remaining cross-date re-ingestion pairs; same protocol as 30/42, lower reviewer visibility; batch 2 |
| 206, 207, 208, 216, 226, 231, 237, 281 | no-ticker general-news tail; no local source evidence and low reviewer visibility; several will likely resolve to source-insufficient in a later batch |
| 80, 94 | manual rows outside c01 (c04/c05 tariff singletons); real candidates but repairing them clarifies only themselves; later batch |
| 210, 211, 212 | representative but clean/scheduled anchors with readouts - no repair need shown |
| 291, 292 | c02 pair (May 30); isolated from the mega-cluster; later batch |

## 6. Repair protocol for L1B

1. **Source-pinned evidence first.** Every anchor decision cites a primary
   source (order text, statement, schedule, incident reporting) before
   any field changes. External source consultation happens only under the
   project's existing gated sourcing rules and with operator approval.
2. **No silent redating.** Follow the Phase-K precedent: a corrected
   anchor is recorded as an explicit correction entry preserving
   before/after; original rows are never quietly rewritten.
3. **Date changes invalidate readouts.** If a date moves, the affected
   1d/5d/20d readouts and any outcome label derived from them must be
   recomputed or explicitly marked stale - never left standing on the old
   window.
4. **Insufficient is an honest outcome.** If stored fields plus sources
   cannot pin an anchor (38 and 154 are the likely cases), record
   "source-insufficient, preserved as manual review with reason" instead
   of forcing a date.
5. **Separate the two repair axes.** Anchor (date) repair and
   ticker/mechanism attribution repair are different mutations; the DRIV
   / LMT rows need the attribution ruling even where the date is fine.
   Do not bundle them into one opaque edit.
6. **Duplicate splits change counting, not content.** Cross-date
   re-ingestion pairs (2/49, 30/42, the OPEC saga) should be collapsed to
   one anchored observation with the siblings marked as
   duplicate-deferred context, mirroring the staged-row thread-collapse
   convention.
7. **Run the affected surfaces after mutation:** the event-date-quality
   suite, the K2 effective-evidence report and its committed exhibit,
   the representative case reports, the reaction matrix, and the
   frontend evidence snapshot if counts shift.
8. **Denominators change only if rows change status.** Anchor repair as
   scoped here does not add or remove accepted rows; if a repair
   decision ever would (e.g. a row reclassified out of the corpus), that
   is a separate, explicitly restated denominator event.

## 7. Non-claims and guardrails

- This packet **repairs nothing**; it selects and documents.
- Selected rows are not evidence of any mechanism, and repair does not
  make them so; anchor repair improves trust and legibility, it does not
  create independent evidence.
- Not a trading signal, not a forecast, not a recommendation.
- No claim about future returns of any kind.
- No statistical-significance claim, no FDR update, no new pool, no
  score, no rank.
- No family-level inference; family lenses appear as context only.
- Outcome labels quoted here are the canonical descriptive any-support
  labels; their known generosity is documented in the methodology.

## 8. Reproduction note (read-only)

- Database access: `events.db` opened via SQLite `mode=ro` only; hash
  verified unchanged before and after this selection pass.
- Candidate assembly reused the K2 pipeline read-only
  (`scripts/effective_independent_evidence_report.py`: `_assemble_rows`,
  `build_clusters`) plus one read-only query for headline / mechanism
  text, and `scripts/representative_case_expansion_report.py` for the
  15-case selection.
- Source artifacts inspected: `stats/EFFECTIVE_INDEPENDENT_EVIDENCE.md`,
  `stats/C01_MARKET_NARRATIVE.md`,
  `stats/EVENT_DATE_QUALITY_DISTRIBUTION.md`,
  `stats/CASE_LIBRARY_REACTION_MATRIX.md`,
  `stats/REPRESENTATIVE_CASE_EXPANSION.md`,
  `stats/EXPANDED_CASE_NOTES.md`,
  `stats/MECHANISM_FAMILY_EVIDENCE_INVENTORY.md`, `stats/METHODOLOGY.md`.
- No provider, API, network, fetch, or backfill call was made; `/analyze`
  was not run; no paid path was touched.
