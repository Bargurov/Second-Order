# L1B repair preview - source-gated, pre-mutation (L1B-0)

**Status:** read-only source-gated preview. No event row was edited, no date was
changed, no ticker was changed, and `events.db` was opened read-only. This packet
decides, per selected row, what L1B *should* mutate and what it must not. It
repairs nothing itself. External free public sources were consulted only for the
14 selected L1A rows.

## 1. What a reviewer should take away first

- This is a **source-gated preview, not a mutation.** Its purpose is archive
  **correctness** - pinning each row to its real event date and honest ticker
  attribution - **not** improving outcomes. Where a date correction would move a
  readout window, that is a correctness side-effect to be handled carefully, never
  a goal.
- **The 14 selected rows are real news events, and public sources exist for all
  but one.** The dominant defect is not "no source" - it is that the stored
  `event_date` tracks the *ingestion* timestamp, so several rows are dated days to
  weeks after the event actually happened.
- Source-status split of the 14: **source-confirmed 4** (2, 7, 29, 39);
  **source-contradicts-date 5** (30, 46, 154, 160, 239);
  **duplicate/collapse-needed 2** (42, 49); **source-insufficient 1** (38);
  **ticker-attribution-noise 1** (9); **needs-human-source 1** (153).
- **Ready for L1B mutation now: 9 rows** (2, 7, 29, 30, 39, 154, 160, 239, plus
  38 as an insufficient-marking). **Needs duplicate policy first: 42, 49.**
  **Needs ticker-attribution policy first: 9, 46** (and the attribution facets of
  2 and 49). **Defer / human source: 153.**
- **Two corrections are high-consequence.** Row 46 (Fed/OCC finding) sources to
  **2026-03-26** and row 153 (ICC order) sources to **2025-02-06**; both fall
  *outside* the c01 window (2026-04-04 to 2026-05-05). Correcting them would move
  rows out of the mega-cluster and could bear on the accepted-window denominator,
  so they are flagged for explicit restatement, not casual edits.

## 2. Source rules used

- Free public sources only: official/primary pages preferred (federalreserve.gov,
  nasa.gov, opec.org, Wikipedia event pages), reputable non-paywalled news next.
- Where the primary source and the stored date disagree, the primary source is
  recorded as the true anchor and the row is marked source-contradicts-date.
- Where no identifiable primary source supports the row (editorial fragment) or
  the stored date cannot be reconciled with the sourced event, the row is marked
  source-insufficient or needs-human-source instead of guessing.
- No paid API, no market-data provider, no `/analyze`, no fetch/backfill script,
  no bulk crawling. No DB mutation. Event-study math, denominators, and the
  K2/K3/K4A/L1A artifacts were not touched.

## 3. Selected batch ledger

Anchor-quality codes (from L1A / C4): MRN = manual_review_needed, DUP =
duplicate_or_deferred, SW = scheduled_or_weak, PA = partial_anticipation. All 14
rows are in cluster **c01**. Source tags are short; full URLs are in section 10.
"Stored date" is `event_date` as held in `events.db` today.

| id | stored date | short label | ticker | anchor | rep | outcome | ES | L1A action | source status | source | true event date | proposed L1B mutation | risk |
|---|---|---|---|---|:--:|---|:--:|---|---|---|---|---|---|
| 2 | 2026-04-04 | Artemis II halfway to Moon | LMT | MRN | no | support | yes | review noisy ticker | source-confirmed | NASA/Forbes | 2026-04-04 | keep date; flag LMT as attribution noise | med |
| 7 | 2026-04-05 | US-Iran "hell" threats, missing airman | XLE | MRN | yes | support | yes | confirm anchor | source-confirmed | AlJazeera | 2026-04-05 | confirm date; add source | low |
| 9 | 2026-04-05 | Barnsley pedestrian-death arrests | DRIV | MRN | no | support | yes | review noisy ticker | ticker-attribution-noise | (local news) | ~2026-04-05 | attribution ruling (DRIV noise); no date change | med |
| 29 | 2026-04-05 | Iran threatens to close Hormuz | XLE | DUP 29/37 | yes | contradiction | yes | split/defer dup | source-confirmed | AlJazeera | 2026-04-05 | confirm date; defer same-date sibling 37 | low |
| 30 | 2026-04-05 | US fighter jet downed over Iran | XOM | MRN | no | contradiction | yes | confirm anchor | source-contradicts-date | Wiki/CNN/TWZ | 2026-04-03 | correct date -> 2026-04-03 (incident); canonical of 30/42 | high |
| 38 | 2026-04-05 | "big for oil and shipping" (fragment) | XLE | MRN | yes | support | yes | mark source-insufficient | source-insufficient | none | (none) | mark source-insufficient, preserved as manual w/ reason | low |
| 39 | 2026-04-05 | OPEC+ output-cut decision | XLE | MRN | no | contradiction | yes | correct date + anchor saga | source-confirmed | OPEC | 2026-04-05 | confirm date; anchor saga; defer 53/54/64/70 | med |
| 42 | 2026-04-06 | same fighter-jet story, re-ingested | LMT | MRN | no | support | yes | split/defer cross-date dup of 30 | duplicate/collapse-needed | Wiki/CNN | 2026-04-03 | collapse/defer to 30; do not double-count | high |
| 46 | 2026-04-06 | Fed/OCC 23A finding, Morgan Stanley | DRIV | SW | yes | support | yes | review ticker + confirm anchor | source-contradicts-date | Fed PR | 2026-03-26 | correct date -> 2026-03-26 (out of c01) + DRIV attribution; RESTATE | high |
| 49 | 2026-04-06 | same Artemis story, re-ingested | DRIV | MRN | no | support | yes | split/defer cross-date dup of 2 | duplicate/collapse-needed | NASA/Forbes | 2026-04-04 | collapse/defer to 2; DRIV attribution noise | high |
| 153 | 2026-04-29 | Trump ICC sanctions order | none | SW | yes | unresolved | no | confirm anchor + source note | needs-human-source | Wiki/PBS | 2025-02-06 (EO 14203) | do NOT pin to 2026-04-29; human source needed | high |
| 154 | 2026-04-29 | UK MPs urge Kyrgyzstan sanctions | none | MRN | yes | unresolved | no | source-insufficient or pin date | source-contradicts-date | OCCRP/F24 | 2026-04-24 | correct date -> ~2026-04-24; still no ticker | med |
| 160 | 2026-04-29 | Araghchi arrives Pakistan, ceasefire talks | none | PA | yes | unresolved | no | confirm anchor + source note | source-contradicts-date | France24 | 2026-04-24 | correct date -> 2026-04-24; still no ticker | med |
| 239 | 2026-05-01 | Powell stays; FOMC holds rates | BAC | MRN | yes | unresolved | yes | correct/confirm via Fed calendar | source-contradicts-date | Fed PR/CNBC | 2026-04-29 | correct date -> 2026-04-29 (FOMC day) | med |

Ledger composition: source-confirmed 4 / source-contradicts-date 5 /
duplicate-collapse 2 / source-insufficient 1 / ticker-attribution-noise 1 /
needs-human-source 1 = 14.

## 4. Row-by-row repair previews

**Row 2 - Artemis II halfway to Moon (LMT).** DB: date 2026-04-04, LMT
beneficiary, outcome support, ES available, mechanism a weak "lunar-program
funding" thesis. Source: NASA and Forbes place the halfway/Earth-image milestone
on **2026-04-04** (Artemis II launched Apr 1, splashdown Apr 10). Anchor date is
therefore **correct**. Attribution is not credible: a crewed lunar milestone is
not a market event for LMT; the mechanism text is thin. Decision: **confirm the
date; separate ticker-attribution repair** (LMT is default-ticker noise; the
honest attribution is "no assignable market primary"). Likely L1B field change:
`market_tickers` / attribution note; **not** `event_date`. Rerun if changed: none
for date (unchanged); attribution change touches the c01 asset-map narrative only,
not readouts. Do not change: the date, the outcome.

**Row 7 - US-Iran "hell" threats, missing airman (XLE).** DB: date 2026-04-05,
XLE, support, ES available. Source: Al Jazeera "Trump threatens hell for Iran over
Hormuz Strait" is dated **2026-04-05**; the missing-airman search ran Apr 3-5.
Anchor **confirmed** at 2026-04-05. XLE (energy) attribution is credible for an
oil-geopolitics headline. Decision: **confirm anchor, add source citation.**
Likely change: add source note only; no `event_date` change. Rerun: none. Do not
change: date, ticker, outcome.

**Row 9 - Barnsley pedestrian-death arrests (DRIV).** DB: date 2026-04-05, DRIV
beneficiary, support, mechanism "insufficient evidence." This is a UK local-crime
item with no market mechanism; DRIV (auto/EV ETF) is default-ticker noise. Source
work on the exact collision date has low value because the defect is attribution,
not the anchor. Decision: **ticker-attribution ruling** - DRIV assignment removed
/ marked non-market; the row's *support* contribution to the ledger is
attribution noise. Likely change: `market_tickers` / attribution note; not
`event_date`. Rerun if changed: c01 asset-map narrative context only. Do not
change: the date. Sibling 51 (per L1A, 9->51) is the same story re-ingested and
rides on this same ruling.

**Row 29 - Iran threatens to close Hormuz (XLE).** DB: date 2026-04-05, XLE,
contradiction, ES available; C4 already links a same-date duplicate 29/37. Source:
the Hormuz-closure / Trump-ultimatum threat is an Apr 5 story (Al Jazeera; Trump's
10-day deadline was set Mar 26). Anchor **confirmed** at 2026-04-05. Decision:
**confirm anchor; defer the same-date sibling 37** as duplicate context (one
observation). Likely change: duplicate flag on 37 (a sibling, not in this batch) /
source note; not row 29's date. Rerun if 37 collapsed: K2 cluster size, the
duplicate ledger. Do not change: row 29's date, ticker, outcome.

**Row 30 - US fighter jet downed over Iran (XOM).** DB: date 2026-04-05, XOM,
contradiction, ES available. Source: the F-15E shootdown over western Iran
occurred on **2026-04-03** (Wikipedia "2026 United States F-15E rescue operation
in Iran"; CNN Apr 3 live blog; TWZ); the WSO was rescued Apr 5, which is why the
"search underway" framing lingers. The stored 2026-04-05 lags the incident by two
days. Decision: **correct date -> 2026-04-03** (incident date) as the canonical
row of the 30/42 pair. Likely change: `event_date`; this **moves the 1d/5d/20d
window two sessions earlier**. Rerun if changed: event-date-quality suite, the K2
report + committed exhibit, the representative-case and reaction-matrix readouts
for this case, and the frontend snapshot if the readout shifts. Risk: high - the
readout and its outcome label may move. Do not change: the ticker (XOM is a
plausible oil primary), the mechanism text.

**Row 38 - "this feels big for oil and shipping" (XLE).** DB: date 2026-04-05,
XLE, support, mechanism "insufficient evidence." This is an editorial/social
fragment, not a datable news event; no primary source can pin it. Decision:
**mark source-insufficient, preserved as manual review with reason** (do not force
a date). Likely change: an anchor-quality / source-insufficient note; not
`event_date`. Rerun: none. Do not change: the date to a guessed value, the
outcome.

**Row 39 - OPEC+ output-cut decision (XLE).** DB: date 2026-04-05, XLE,
contradiction, ES available. Source: the OPEC+ Eight met on **2026-04-05**
(opec.org; the prior step was Mar 1). The stored date is **correct**. Note a
mechanism nuance for L1B's awareness only: the Apr 5 meeting concerned *resuming
the unwinding* of cuts, while the headline says "extending" - a mechanism-text
question, not an anchor question, and out of scope here. Decision: **confirm the
date; treat row 39 as the saga anchor and defer siblings 53/54/64/70** (re-ingested
Apr 6-9) as duplicate context. Likely change: duplicate flags on the siblings (not
in this batch) / source note; not row 39's date. Rerun if siblings collapsed: K2
cluster size, duplicate ledger. Do not change: row 39's date, the outcome, the
mechanism math.

**Row 42 - same fighter-jet story, re-ingested (LMT).** DB: date 2026-04-06, LMT,
support, ES available, mechanism "insufficient evidence." This is the **same
event as row 30** (F-15E shootdown, Apr 3) re-saved a day later under a different
ticker (LMT vs XOM) and with the **opposite outcome label** (support vs
contradiction). Decision: **collapse/defer to row 30** - one anchored observation
at 2026-04-03, row 42 marked duplicate-deferred context. Likely change: duplicate
flag + deferral; optionally `event_date` alignment. Rerun if changed: K2 size and
duplicate ledger; the ledger stops counting one incident as both a support and a
contradiction. Risk: high (touches outcome bookkeeping). Do not change: the
underlying incident interpretation; do not silently delete the row.

**Row 46 - Fed/OCC section-23A finding, Morgan Stanley (DRIV).** DB: date
2026-04-06, DRIV, support, ES available, mechanism "insufficient evidence."
Source: the Federal Reserve press release announcing the joint 23A finding for
Morgan Stanley Bank, N.A. is dated **2026-03-26**
(federalreserve.gov/.../orders20260326a.htm). The stored 2026-04-06 lags the
release by eleven days, and **2026-03-26 is outside the c01 window
(2026-04-04..2026-05-05).** Attribution is also wrong: DRIV (auto/EV) is not the
primary for a bank-regulatory action. Decision: **two separate mutations** - (a)
correct `event_date` -> 2026-03-26, and (b) attribution ruling (DRIV is noise;
a bank/financials primary or "no market primary" is honest). Because the date
correction moves the row out of c01 and out of the current window, it may bear on
cluster membership and the accepted-window framing. Decision: **flag for explicit
restatement** before mutating; do not casually edit. Rerun if changed:
event-date-quality suite, K2 report + exhibit (cluster membership shifts),
representative-case + reaction-matrix + frontend snapshot; and a denominator
restatement note if the accepted window changes. Risk: high. Do not change:
event-study math, denominators (without explicit restatement).

**Row 49 - same Artemis story, re-ingested (DRIV).** DB: date 2026-04-06, DRIV,
support, ES available, mechanism "insufficient evidence." This is the **same event
as row 2** (Artemis halfway milestone, Apr 4) re-saved two days later under DRIV.
Decision: **collapse/defer to row 2** as duplicate context, and the same DRIV
attribution-noise ruling applies. Likely change: duplicate flag + deferral;
attribution note. Rerun if changed: K2 size, duplicate ledger, asset-map
narrative. Risk: high (duplicate bookkeeping). Do not change: row 2's confirmed
Apr 4 anchor.

**Row 153 - Trump ICC sanctions order (no ticker).** DB: date 2026-04-29, no
tickers, unresolved, no readout, `what_changed` explicitly a "thin response."
Source: the canonical event, Executive Order 14203 "Imposing Sanctions on the
International Criminal Court," was signed **2025-02-06**, with expansions through
2025 (Wikipedia; PBS; NBC). No distinct new ICC-sanctions signing on 2026-04-29 is
identifiable from free sources; the row may be a re-surfaced or syndicated
reference to the 2025 order. Decision: **needs-human-source** - do NOT pin to
2026-04-29 and do NOT silently redate to 2025-02-06 (that would move the row more
than a year and out of the corpus window). Escalate for a human sourcing decision:
is this the Feb-2025 EO re-surfacing, or a distinct April-2026 action? Likely
change: none until resolved. Rerun: none yet. Do not change: anything, pending the
human ruling.

**Row 154 - UK MPs urge Kyrgyzstan sanctions (no ticker).** DB: date 2026-04-29,
no tickers, unresolved, no readout, thin response. Source: the cross-party UK
letter urging sanctions on Kyrgyz officials over crypto-based Russia sanctions
evasion is an **2026-04-24** story (OCCRP; France 24 via others). The event is
real and datable; the stored 2026-04-29 lags by ~5 days. Decision: **correct date
-> ~2026-04-24; remains no-ticker** (a policy-letter story with no clean market
primary). Not source-insufficient after all. Likely change: `event_date`; the row
has no readout, so no window recompute. Rerun if changed: event-date-quality
suite. Risk: medium. Do not change: the no-ticker status (no honest primary),
the outcome.

**Row 160 - Araghchi arrives Pakistan, ceasefire talks (no ticker).** DB: date
2026-04-29, no tickers, unresolved, no readout. Source: the France 24 headline
that this row mirrors is dated **2026-04-24** (Araghchi's initial Islamabad
arrival; he returned Apr 26). The stored 2026-04-29 lags by ~5 days. Decision:
**correct date -> 2026-04-24; remains no-ticker** (diplomacy story, no clean
market primary). Likely change: `event_date`; no readout to recompute. Rerun if
changed: event-date-quality suite. Risk: medium. Do not change: no-ticker status,
outcome.

**Row 239 - Powell stays; FOMC holds rates (BAC).** DB: date 2026-05-01, BAC,
unresolved, ES available (but "not enough price data" for BAC). Source: the FOMC
decision to hold and Powell's statement that he will stay are the **2026-04-29**
meeting (federalreserve.gov statement monetary20260429a.htm; CNBC Apr 29). The
stored 2026-05-01 lags the decision by two days. Decision: **correct date ->
2026-04-29** (the FOMC day). Note for L1B awareness only (out of anchor scope): the
row's mechanism text states rates held at "5.25-5.50%," whereas the sourced hold
was at **3.50-3.75%** - a mechanism-text accuracy issue to log separately, not an
anchor edit. Likely change: `event_date` (moves the window two sessions earlier).
Rerun if changed: event-date-quality suite, and any BAC/KRE readout if price data
exists. Risk: medium. Do not change: the mechanism math here, the outcome, the
5.25-5.50 text (log it; separate task).

## 5. Cross-date same-story groups

- **30 -> 42 (fighter jet).** Same F-15E shootdown (true incident 2026-04-03),
  saved Apr 5 (XOM, contradiction) and Apr 6 (LMT, support). L1B should **correct
  30 to 2026-04-03, collapse/defer 42 to 30** as one observation. This removes a
  case where one incident contributes both a support and a contradiction from two
  windows. High risk (outcome bookkeeping); do first among duplicates because it
  is the clearest.
- **2 -> 49 (Artemis).** Same halfway milestone (2026-04-04), saved Apr 4 (LMT)
  and Apr 6 (DRIV), both "insufficient." L1B should **keep 2 at Apr 4, collapse/
  defer 49 to 2**, and apply the ticker-attribution-noise ruling to both. Neither
  is a genuine market event.
- **9 -> 51 (Barnsley UK crime).** Non-market local news re-ingested under DRIV.
  L1B should **collapse/defer 51 to 9** and rule DRIV attribution as noise for
  both. No date pinning is needed for correctness; the defect is attribution.
- **OPEC saga 39 / 53 / 54 / 64 / 70.** One OPEC+ decision (2026-04-05) re-saved
  five times across Apr 5-9, with outcome labels differing between copies. L1B
  should **anchor 39 at Apr 5 and collapse/defer 53/54/64/70** as duplicate
  context (53/54 already C4-linked same-date; 64/70 escaped the same-date rule).
  One cartel decision, one observation.

General rule these support: for cross-date re-ingestion, **collapse to one
anchored observation at the true event date and mark the siblings
duplicate-deferred** (mirroring the staged-row thread-collapse convention); do not
delete rows and do not leave conflicting outcome labels standing on the same
event.

## 6. Missing-readout representative tail (153, 154, 160)

All three are representative cases with **no primary ticker and no event-study
readout** - the missing readout is because there is **no assigned market asset**,
not because the anchor is unknowable.

- **153 (ICC order):** needs-human-source. The real event is a 2025-02-06
  signing; the 2026-04-29 anchor cannot be confirmed as a distinct action from
  free sources. Missing readout is secondary; the anchor itself is the open
  question. No mutation until a human sources it.
- **154 (Kyrgyzstan letter):** source supports **date correction to ~2026-04-24**;
  it remains legitimately no-ticker (a sanctions-policy letter with no clean
  market primary). Missing readout is expected and honest, not a defect to force.
- **160 (Araghchi/Pakistan):** source supports **date correction to 2026-04-24**;
  also legitimately no-ticker (diplomacy). Missing readout is expected.

So for this tail: one row (153) blocks on human sourcing; two (154, 160) get an
honest date correction and stay no-ticker/no-readout. None should have a ticker or
a readout invented to fill the gap.

## 7. Mutation readiness summary

- **Ready for L1B mutation (confirm or clean date correction):** 7, 29, 39
  (confirm date), 2 (confirm date), 154, 160, 239 (correct date, in-window, no or
  minor readout impact), 30 (correct date -> Apr 3, readout recompute expected).
- **Ready only for source-insufficient marking:** 38.
- **Needs duplicate policy before mutation:** 42, 49 (and the saga siblings
  53/54/64/70, and 37, all riding on their anchors).
- **Needs ticker-attribution policy before mutation:** 9, 46, plus the attribution
  facets of 2 and 49.
- **Defer / needs human source:** 153. **High-consequence / needs restatement
  before mutation:** 46 (date correction exits c01/window).

## 8. Proposed L1B mutation order

1. **Source-confirmed anchor confirms first (lowest risk):** 7, 29, 39, 2 - add
   source citations, no date change, no readout movement.
2. **In-window date corrections next:** 239 (May 1 -> Apr 29), 154 and 160
   (Apr 29 -> Apr 24), then 30 (Apr 5 -> Apr 3). These move windows but stay in
   the corpus; recompute the affected readouts explicitly and preserve
   before/after.
3. **Duplicate / cross-date collapse decisions:** 42 -> 30, 49 -> 2, and the OPEC
   saga (53/54/64/70 -> 39), 37 -> 29, 51 -> 9. Do these after the anchors they
   collapse onto are fixed, so the surviving observation carries the true date.
4. **Ticker-attribution cleanup as a separate mutation axis:** 9, 46, 2, 49 -
   remove/relabel default-ticker noise (DRIV, and the Artemis LMT), never bundled
   into the date edits.
5. **High-consequence, out-of-window corrections and the human-source tail last:**
   46 (Mar 26 exits c01 -> requires cluster/denominator restatement) and 153
   (needs human sourcing) - handle only after the safe edits, with explicit
   restatement where a row leaves the window.

Rationale: confirmations and in-window date fixes are reversible-in-effect and
low-blast-radius; duplicate collapses depend on the anchors being correct first;
attribution is a different field axis and must not be conflated with dates; the
window-exiting corrections carry denominator/cluster consequences and deserve the
most scrutiny, so they go last.

## 9. Non-claims and guardrails

- This preview **repairs nothing**; it selects, sources, and documents.
- Repaired anchors and corrected dates do **not** create independent evidence; a
  more accurate date improves legibility and trust, it does not add a data point
  or make a mechanism true.
- Duplicate collapse does **not** prove or disprove any mechanism; it stops one
  event being counted several times.
- No p-value, no FDR update, no new pool, no score, no rank.
- No family-level inference; family lenses are context only.
- Not a trading signal, not a forecast, not a recommendation, and it says nothing
  about future returns of any asset.
- Outcome labels quoted here are the canonical descriptive any-support labels;
  correcting a date may move a readout window and thereby change a label as a
  side-effect of correctness - that is not an attempt to change outcomes.

## 10. Reproduction note (read-only)

- Database access: `events.db` opened via SQLite `mode=ro` only; SHA-256 verified
  unchanged before and after this pass. `price_cache.db` not opened. No row was
  edited.
- Local inputs inspected: `stats/L1_ANCHOR_REPAIR_BATCH.md`,
  `stats/C01_MARKET_NARRATIVE.md`, `stats/EFFECTIVE_INDEPENDENT_EVIDENCE.md`,
  `stats/METHODOLOGY.md`, `stats/EVENT_DATE_QUALITY_DISTRIBUTION.md`,
  `stats/CASE_LIBRARY_REACTION_MATRIX.md`; and one read-only query over the 14
  selected rows (id, event_date, timestamp, headline, market_tickers,
  mechanism_family, what_changed, mechanism_summary, market_note).
- External free public sources consulted (no paid access):
  - FOMC 2026-04-29: federalreserve.gov/newsevents/pressreleases/monetary20260429a.htm;
    cnbc.com/2026/04/29/fed-interest-rate-decision-april-2026.html
  - F-15E shootdown 2026-04-03: en.wikipedia.org/wiki/2026_United_States_F-15E_rescue_operation_in_Iran;
    cnn.com/2026/04/03/world/live-news/iran-war-us-trump-oil; twz.com F-15E wreckage
  - Iran "hell"/Hormuz 2026-04-05: aljazeera.com/news/2026/4/5/trump-threatens-hell-for-iran-over-hormuz-strait;
    euronews.com/2026/04/07 Iran defies deadline
  - Artemis II 2026-04-04: nasa.gov Artemis II Moon-flyby photos;
    forbes.com/sites/jamiecartereurope/2026/04/04 halfway-to-the-moon
  - OPEC+ 2026-04-05: opec.org/pr-detail/593-1-march-2026.html (and the Apr 5 Eight meeting)
  - Fed/OCC 23A 2026-03-26: federalreserve.gov/newsevents/pressreleases/orders20260326a.htm
  - ICC EO 14203 signed 2025-02-06: en.wikipedia.org/wiki/Executive_Order_14203;
    pbs.org/newshour/world Trump ICC sanctions
  - Araghchi/Pakistan 2026-04-24: france24.com/en/middle-east/20260424-iran-fm-araghchi-arrives-in-pakistan
  - Kyrgyzstan/UK MPs 2026-04-24: occrp.org UK lawmakers demand sanctions on Kyrgyz officials
- No provider/market-data API, no `/analyze`, no fetch/backfill, no bulk crawl.
- events.db SHA-256 before: ae3a1187c4c70ae62d29d9dd087bcdd9ec98a8f8fa454136ad891cf8408d23ba
  (after: re-verified identical). price_cache.db: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855,
  size 0 bytes, mtime 2026-04-11 21:20:31 (unchanged).
