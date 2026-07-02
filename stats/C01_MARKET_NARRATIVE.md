# c01 -- Market-Story Cluster: A Reviewer's Narrative

Read-only narrative context for cluster **c01**, the largest descriptive
market-story cluster surfaced by the effective-independent-evidence report
(`scripts/effective_independent_evidence_report.py`). This note adds no new
computation: every count below is read from that report's own pipeline over
`events.db` (read-only). It is descriptive market-history context, not a
confirmed mechanism and not an inferential result.

## 1. What a reviewer should take away first

Two facts, held together:

- **c01 is not one market story -- it is one calendar window.** The cluster is
  built mechanically: the 86 accepted track-record rows are linked when they
  share an event date, share a primary ticker within a 20-day window, or carry
  an explicit duplicate link. c01 is the connected component that swallows the
  whole **2026-04-04 -> 2026-05-05** window -- **81 of the 86 rows**. Its size
  reflects date-and-ticker adjacency, not 81 independent market events.
- **Within that window, the dominant coherent throughline is the Iran /
  Strait-of-Hormuz energy-and-geopolitics tape** -- an oil-and-shipping
  war-scare in early April, a de-escalation swing a few days later, and an
  OPEC / Saudi-pricing and ceasefire-talks coda into early May. Roughly half the
  rows sit directly on that tape (energy tickers XLE / XOM / VLO / BTU dominate).
  The rest are adjacent-but-distinct macro items (a Fed rate decision, a
  tariff-refund launch, non-oil sanctions, tech earnings) and a residue of
  general-news rows that ride a shared date or a noisy default ticker.

The single most important caution: **c01 holds almost the entire accepted
outcome ledger.** Of the 86-row track record's 46 supporting / 8 contradicting /
32 unresolved rows, c01 alone contains **42 supporting, all 8 contradicting, and
31 unresolved** (42 / 8 / 31). The accepted track record's outcome distribution
is, to a first approximation, this one cluster. So the 42 supporting rows are
not 42 independent confirmations -- they are one calendar window, dominated by
one macro tape, observed many times.

## 2. Tape summary

Chronological, finance-native:

- **Apr 4-5 -- war-scare / supply-shock leg.** A US-Iran military confrontation
  (a downed US aircraft over Iran, a missing crew member) escalates into explicit
  threats over the Strait of Hormuz and Iranian drone strikes on Gulf oil
  infrastructure (Kuwait). Refinery fires in Russia (Primorsk / NORSI) add a
  second supply scare. The tape reads as a classic oil-and-shipping risk premium:
  crude and energy equities bid, tanker / freight names in play.
- **Apr 5-6 -- pricing and cartel response.** Saudi Arabia raises official
  selling prices to a record premium; OPEC+ members discuss and then extend
  voluntary output cuts. Coal (BTU) enters as a substitution story ("an Iran war
  could make the world more reliant on coal").
- **Apr 8-9 -- de-escalation swing.** "Iran open to negotiations"; diplomacy
  shows signs of progress. The same energy and refiner names now sit on the
  other side of the scare.
- **Apr 12-15 -- tariff / standards noise.** Reciprocal-tariff summaries and
  global-standards-proliferation items enter the window on shared dates.
- **Apr 28 -- May 5 -- coda.** A late-April cluster of non-oil sanctions (ICC,
  Kyrgyzstan / Russia-evasion, US-China Uighur), a US tariff-refund launch,
  UAE-leaves-OPEC headlines, a fresh Saudi OSP hike, a Fed rate decision (Powell
  stays; rates held), and Bank-of-England commentary. Iran ceasefire-talks
  headlines run alongside.

## 3. Mechanism narrative

The economically legible core of c01 is a **geopolitical oil-supply-risk**
narrative: a Hormuz-closure / Gulf-infrastructure threat raises the risk premium
on crude, which propagates to integrated majors (XOM), refiners (VLO), the broad
energy sector (XLE), and, as a substitution hedge, thermal coal (BTU). The
de-escalation leg is the same narrative in reverse. OPEC / Saudi supply
decisions (output cuts, OSP hikes, the UAE-exit story) sit on the supply side of
the same crude-pricing narrative.

Two honest qualifications:

- The **family labels are a headline-overlay lens, not a stored taxonomy.**
  Every accepted row's stored `mechanism_family` is `none`; the labels
  (supply_shock, geopolitical_conflict_context, ceasefire_deescalation, tariff,
  sanction, monetary_policy_or_rates) are assigned by the J1 / K2 keyword overlay
  on the headline. They are a reading aid, not six confirmed mechanisms. Under
  that lens c01 breaks down roughly as: supply_shock 18, unclassified 20,
  multi-match 13, geopolitical_conflict_context 12, tariff 8, sanction 4,
  monetary_policy_or_rates 3, ceasefire_deescalation 3 -- note that 33 of the 81
  rows are multi-match or unclassified, i.e. the overlay itself does not cleanly
  resolve them.
- The Fed / tariff-refund / non-oil-sanction / tech-earnings rows are **not part
  of the oil narrative.** They land in c01 because they share dates (Apr 6,
  Apr 29-30, May 1) with oil-tape rows, not because they transmit through the
  same channel.

## 4. Asset map

Primary tickers in c01 (rows on which each is the derived primary ticker):

| Ticker | Rows | Reads as | Note |
|--------|-----:|----------|------|
| XLE | 24 | Energy sector (SPDR) | Spine of the oil tape: Iran / Hormuz threats, OPEC cuts, Saudi pricing. |
| (none) | 12 | -- | Late-April sanctions / general-news rows carry no derived primary ticker. |
| XOM | 8 | Integrated oil major | Saudi OSP, OPEC, fighter-jet-over-Iran rows. |
| DRIV | 6 | auto / EV ETF -- attribution artifact | Its 6 rows are an Iran-rescue item, a Fed-findings release, an Artemis-Moon image, an India feature, and two UK crime items -- none auto / EV. Treat DRIV here as a noisy default primary-ticker assignment, not a channel. |
| VLO | 5 | Refiner | Russian-refinery drone-strike rows; refiner-output / diplomacy rows. |
| LMT | 3 | Defense prime | 2 of 3 rows are genuine Iran-conflict (fighter jet downed over Iran; Hormuz peace-talks stall); 1 (Artemis Moon) is a mis-assignment. |
| BTU | 3 | Thermal coal | All 3 rows are the same coal-substitution story -- one headline repeated, not three coal events. |

The energy complex (XLE + XOM + VLO + BTU = 40 rows) is the genuine center of
gravity. DRIV, and one of the LMT rows, show that the primary-ticker field is
noisy: some rows are glued into c01 by a default ticker, not by real exposure.
That noise inflates the cluster's size beyond its true macro membership.

## 5. Outcome split

- **c01: 42 supporting / 8 contradicting / 31 unresolved** (81 rows).
- Whole accepted track record: 46 / 8 / 32 (86 rows).

So c01 contains **all 8 contradicting rows, 42 of 46 supporting rows, and 31 of
32 unresolved rows** of the entire accepted corpus. The accepted track record's
outcome distribution essentially *is* c01.

Read the 42 supporting rows as a **clustered, not independent, count.** They are
one calendar window dominated by one macro tape, observed through many headlines
and tickers; the same underlying oil-shock event contributes multiple supporting
rows. This is exactly the independence caution the effective-independent-evidence
report exists to surface: 86 nominal rows are far fewer distinct market tapes.
Treating c01's 42 supports as 42 confirmations would multiply-count a handful of
events.

## 6. Representative cases inside c01

14 of the 15 representative walkthrough cases fall inside c01 (only case 1 sits
outside, in cluster c03). Compact map (family lens is the headline-overlay
reading aid, not stored taxonomy):

| Case | Date | Ticker | Family lens | Outcome | Readout | Reads as |
|-----:|------|--------|-------------|---------|:-------:|----------|
| 7 | 2026-04-05 | XLE | geopolitical_conflict_context | support | yes | US-Iran "hell" threats; oil bid |
| 29 | 2026-04-05 | XLE | supply_shock | contradiction | yes | Iran threatens to close Hormuz |
| 38 | 2026-04-05 | XLE | supply_shock | support | yes | "big for oil and shipping" |
| 46 | 2026-04-06 | DRIV | monetary_policy_or_rates | support | yes | Fed joint-findings release (off the oil tape; DRIV artifact) |
| 61 | 2026-04-08 | BTU | geopolitical_conflict_context | contradiction | yes | coal-substitution story |
| 66 | 2026-04-08 | XLE | ceasefire_deescalation | support | yes | "Iran open to negotiations" |
| 71 | 2026-04-09 | VLO | ceasefire_deescalation | support | yes | same diplomacy leg, refiner |
| 153 | 2026-04-29 | (none) | sanction | unresolved | no | ICC sanctions order |
| 154 | 2026-04-29 | (none) | sanction | unresolved | no | Kyrgyzstan / Russia-evasion |
| 160 | 2026-04-29 | (none) | ceasefire_deescalation | unresolved | no | Iran FM pre-ceasefire-talks |
| 210 | 2026-04-30 | XOM | supply_shock | unresolved | yes | Saudi crude OSP +USD 2 |
| 211 | 2026-04-29 | FSLR | sanction | unresolved | yes | US-China Uighur sanctions |
| 212 | 2026-04-29 | TJX | tariff | unresolved | yes | US tariff-refund launch |
| 239 | 2026-05-01 | BAC | monetary_policy_or_rates | unresolved | yes | Powell stays; rates held |

Cases 153 / 154 / 160 carry no event-study readout (they are among the 14 of 81
c01 rows without one). The unresolved late-April cases (153 / 154 / 160 / 211 /
212 / 239) are the adjacent-macro tail, not the oil core.

## 7. The 7 / 29 / 38 caution

Cases 7, 29, and 38 are all dated **2026-04-05**, all carry **XLE** as primary
ticker, and all describe the **same Iran / Strait-of-Hormuz oil-shock event** --
respectively the "unleash hell" threats, the explicit Hormuz-closure threat, and
a market-reaction note ("this feels big for oil and shipping"). They are three
headlines on one tape, not three independent observations.

They do not even agree on outcome: **29 is labeled contradiction while 7 and 38
are labeled support.** The same underlying event resolves differently depending
on the exact readout window and the label rule. This is the sharpest single
illustration of why c01's row count overstates its evidentiary weight: one
oil-shock event here produces three rows and two different outcome labels. Count
the event once.

## 8. What would make c01 stronger later

Design notes only -- no work is proposed or approved here.

- **Event-level de-duplication.** Collapse same-event, same-day, same-ticker
  rows (7 / 29 / 38 being the clearest case) to one observation before any
  outcome tally, so the window contributes distinct events rather than distinct
  headlines.
- **Repair the primary-ticker attribution.** The DRIV rows, and one LMT row,
  show a noisy default ticker gluing unrelated general-news items into the
  cluster. A cleaner ticker map would shrink c01 toward its genuine macro
  membership.
- **Separate the adjacent-macro tail.** The Fed / tariff-refund /
  non-oil-sanction / tech-earnings rows share only a calendar with the oil tape.
  Splitting them out would leave a cleaner Iran / Hormuz component.
- **Recover the missing readouts.** 14 of the 81 rows (including 153 / 154 / 160)
  have no event-study readout; their outcomes stay unresolved partly for that
  reason.

None of these change the accepted corpus; they would only sharpen how the same
rows are grouped and counted.

## 9. Reader guardrails

- This is **descriptive market-history context**, not a confirmed mechanism. The
  Iran / Hormuz oil narrative is the legible throughline of the window, not a
  validated causal claim.
- c01 is a **mechanical adjacency cluster** (shared date / shared 20-day-window
  ticker / duplicate link), so its 81-row size is not a measure of evidence. It
  mixes one dominant tape, adjacent-but-distinct macro, and general-news noise.
- The family labels are a **headline-overlay reading lens**, not stored taxonomy
  and not six confirmed mechanisms.
- The outcome counts (42 / 8 / 31) are **clustered, not independent.** Do not
  read 42 supports as 42 confirmations.
- This note is **not an inferential effective sample size, score, rank, p-value,
  or FDR pool, and not a trading, prediction, or recommendation surface.**

## 10. Reproduction

All counts above are read (not recomputed) from the effective-independent-evidence
report:

```
python scripts/effective_independent_evidence_report.py --db-path events.db --json
```

Source of truth: `stats/EFFECTIVE_INDEPENDENT_EVIDENCE.md` (report commit
`8d247ea`). c01 is the first / largest cluster in that output. Row-level fields
used here -- `event_date`, derived `primary_ticker`, `family_lens`, `outcome`,
`event_study_available`, `duplicate_of` -- come from that pipeline over
`events.db` (read-only, `mode=ro`). Headlines were read read-only from
`events.db` for narrative paraphrase only; none are quoted verbatim.
