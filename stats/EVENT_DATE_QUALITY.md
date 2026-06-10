# Event-date quality / anticipation risk

**Date:** 2026-06-10 · **Scope:** read-only research-caution layer. An
event-date label is **not** proof of any mechanism — it qualifies whether a
1d/5d/20d market-reaction window is even anchored on a real information shock.

Reproduce read-only:

```powershell
python scripts/event_date_quality_report.py --db-path events.db --json
```

## Why event-date quality matters

Every event-window readout in this project assumes the event date carries new
information. That assumption has visibly different strength across the
archive: a DOJ suit *filing* is a discrete shock; a bill *signing* is the
scheduled culmination of a telegraphed process; a strike *start* is partly
anticipated; a same-thread export-control *update* is real but not
independent of an earlier anchor. Reading windows without this screen
overstates how many independent, well-anchored observations a cohort has.

## Labels

| label | meaning | anticipation risk |
|---|---|---|
| `clean_discrete_anchor` | discrete filing/action wording | low |
| `partial_anticipation` | process-start / anticipatory wording | elevated |
| `scheduled_or_weak_anchor` | scheduled culmination (signings, effect dates) | high |
| `continuation_or_thread_sibling` | shares a policy thread with an earlier same-family row | thread-dependent |
| `duplicate_or_deferred` | same-announcement collision | deferred |
| `manual_review_needed` | missing/ambiguous fields or wording | unknown |

Rules are deliberately simple and explainable — headline keyword lists
(whole-word matched), a same-date/near-identical-headline collision check, a
same-family primary-ticker thread link, and a small curated thread-entity
lexicon (`huawei`, `smic`, `nvidia`) derived from the curated sanction
anchors. Every label carries an `anchor_rationale` naming the rule that
fired. No numeric score is emitted: a number would be fake precision.

## Live snapshot (2026-06-10)

Denominators unchanged: 180 archive rows · 94 accepted coverage · 86 accepted
track-record · 13 staged (excluded and disclosed: 71 synthetic seeds, 1
intake stub).

| corpus status | clean | partial | scheduled | thread-sibling | duplicate | manual |
|---|---|---|---|---|---|---|
| accepted (86) | 5 | 8 | 8 | 0 | 8 | 57 |
| curated (8) | 6 | 1 | 1 | 0 | 0 | 0 |
| staged (13) | 4 | 1 | 3 | 4 | 1 | 0 |
| pending (1) | 0 | 0 | 0 | 0 | 1 | 0 |

Examples (staged shortlist + threads):

- **Clean:** #303 DOJ v Apple, #304 DOJ v Google ad-tech (suit filings; 304's
  paid path stays deferred per the B2b operator decision).
- **Partial anticipation:** #313 UAW strike begins (telegraphed deadline, but
  the deal-vs-strike binary and the novel scope carried real surprise).
- **Weak scheduled anchors:** #311 CHIPS Act, #312 IRA (bill signings); #314
  SAG-AFTRA strike *order takes effect* (the order predates the date).
- **Thread siblings:** #307/#308/#310 share the NVDA export-control thread
  with curated anchor #300; #309 shares the Huawei thread with curated
  anchor #298. Real events, but not independent observations.
- **Duplicate/deferred:** #302 FTC v Amazon, the same announcement as
  quarantined row #315 — resolve before any read.
- Curated anchors are mostly clean (6/8); #296 (announced *intent* to impose
  tariffs) is partial anticipation and #295 (Presidential safeguard
  *approval*) is a scheduled culmination — honest caveats on two of the
  Phase-K observations.

**Limitation stated, not hidden:** 57 of the 86 accepted thesis rows land in
`manual_review_needed` — the keyword rules are tuned for the curated + staged
research corpus, and most untagged news-archive headlines need a human read.
The 8 accepted `duplicate_or_deferred` rows are same-day near-identical
coverage pairs inside the date-clustered news archive — the screen surfacing
exactly the non-independence the methodology docs already disclose.

## How this affects later cohort work

Before pooling events into any cohort packet: (1) drop or resolve
`duplicate_or_deferred` rows; (2) treat `continuation_or_thread_sibling` rows
as the same underlying observation as their anchor, not new ones; (3) read
`scheduled_or_weak_anchor` windows as residual-surprise measurements only;
(4) carry the `partial_anticipation` caveat into interpretation. A cohort
count that ignores this screen overstates its independent-event denominator.

## Non-claims and limitations

- Event-date quality is a caution layer — not proof, not validation of any
  mechanism, and not a significance statement.
- Labels come from simple keyword/collision heuristics a reviewer can
  re-derive; representative classifications are illustrative.
- Staged candidates remain staged/no-paid and outside every accepted
  denominator; nothing here promotes a candidate or runs paid analysis.
- The closed Phase 1 / Phase 2 FDR pools are untouched.
