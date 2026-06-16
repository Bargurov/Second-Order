# Event-date quality distribution (J1)

A read-only honesty layer that shows **how reliable the event-date anchors are**
across the archive, the accepted corpus, the event-study-available subset, and
the 15-case representative library. When we read a market window around an
event, this report says how trustworthy the date the window is anchored on
actually is.

It reuses the existing event-date quality labels and their definitions
(`scripts/event_date_quality_report.py`), the event-study coverage report, the
representative case matrix (H1), and the headline family overlay (E1). It
computes **no new score, no ranking, no ordering by anchor quality, no
inference, no p-value, and no FDR**. Anchor quality is an inherent per-event
gradient; this
report tabulates it and never aggregates it into a per-subset or per-family
quality number.

## Denominators (live, unchanged)

archive **180** · accepted coverage **94** · accepted track-record **86** ·
event-study **78/94** · staged **13** (excluded).

## Event-date quality labels

Definitions and the per-label anticipation_risk are reused verbatim from the
event-date quality report; this report introduces no new label and no new scale.

| label | risk | what the label means |
| --- | --- | --- |
| clean_discrete_anchor | low | Discrete filing or action wording on a specific date. |
| partial_anticipation | elevated | Process-start or anticipatory wording; the move can leak before the date. |
| scheduled_or_weak_anchor | high | Scheduled-culmination wording; most information was likely priced before the date. |
| continuation_or_thread_sibling | thread_dependent | Shares a policy thread with an earlier anchor row; the date is not independent of it. |
| duplicate_or_deferred | deferred | Same-announcement collision with another row; deferred until the duplicate is resolved. |
| manual_review_needed | unknown | Missing or ambiguous date / fields, or no rule matched the wording. |

> **Guardrail:** anticipation_risk is a per-label research caution. This report
> does not sum it, weight it, or use it to rank or score any subset or family.

## Distribution across subsets

All six labels are shown in every row, with explicit zeros, in canonical label
order — so the rows stay comparable. `continuation_or_thread_sibling` appears
only in the archive (it is never carried into the accepted corpus). Each cell is
`count (percentage)`; the count is primary and the percentage is the descriptive
composition share within that subset's own denominator (shown in the `% over`
column). Percentages within a row are over the labelled rows of that subset, so
the archive row is over its **108 labelled** rows, not 180.

| subset | % over | clean | partial | scheduled | thread | dup | manual | total |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| archive (labeled) | 108 | 15 (13.9%) | 10 (9.3%) | 12 (11.1%) | 4 (3.7%) | 10 (9.3%) | 57 (52.8%) | 108 |
| accepted coverage | 94 | 11 (11.7%) | 9 (9.6%) | 9 (9.6%) | 0 (0.0%) | 8 (8.5%) | 57 (60.6%) | 94 |
| accepted track-record | 86 | 5 (5.8%) | 8 (9.3%) | 8 (9.3%) | 0 (0.0%) | 8 (9.3%) | 57 (66.3%) | 86 |
| event-study available | 78 | 10 (12.8%) | 8 (10.3%) | 7 (9.0%) | 0 (0.0%) | 8 (10.3%) | 45 (57.7%) | 78 |
| representative library | 15 | 2 (13.3%) | 3 (20.0%) | 5 (33.3%) | 0 (0.0%) | 1 (6.7%) | 4 (26.7%) | 15 |

> **Percentages are descriptive composition shares within each denominator. They
> are not scores, ranks, or evidence of stronger anchor quality.** Within-row
> shares may not sum to exactly 100% because of one-decimal rounding.

- **Archive:** 108 of the 180 archive rows carry an event-date quality label.
  The remaining **72 (40.0% of 180)** are outside the labelling universe —
  **71 `realized`-stage rows + 1 `curated_intake` row** — so labelled 108 +
  unlabelled 72 = 180. The label percentages above are over the 108 labelled
  rows, kept separate from this 72-of-180 unlabelled share.
- **Event-study available** is a **coverage-lens subset (78 of 94)**: it includes
  **8 curated observation rows alongside 70 accepted rows**, so it is *not* a
  track-record subset. Its lower `manual` count (45 vs the 57 of the 86-row
  track record) is exactly the 12 accepted manual-review rows that have no
  computable window; the 8 curated rows add no manual rows at all (they are
  clean 6 / scheduled 1 / partial 1), so they shift the share, not the count.
- The accepted corpus is dominated by `manual_review_needed` (57 of 86):
  the anchor wording or fields need a manual look before any window is read.

## Representative cases — four separate lenses

The event-date quality **label**, the **event-study availability**, the
**market-readout availability**, and the **thesis outcome** are four distinct
facts. They are listed side by side and combined into nothing.

| id | role | family | label | risk | ES | readout | outcome |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | anchor | tariff | partial_anticipation | elevated | yes | yes | support |
| 46 | anchor | monetary_policy_or_rates | scheduled_or_weak_anchor | high | yes | yes | support |
| 61 | anchor | geopolitical_conflict_context | partial_anticipation | elevated | yes | yes | contradiction |
| 66 | anchor | ceasefire_deescalation | scheduled_or_weak_anchor | high | yes | yes | support |
| 210 | anchor | supply_shock | clean_discrete_anchor | low | yes | yes | unresolved |
| 211 | anchor | sanction | scheduled_or_weak_anchor | high | yes | yes | unresolved |
| 7 | new | geopolitical_conflict_context | manual_review_needed | unknown | yes | yes | support |
| 29 | new | supply_shock | duplicate_or_deferred | deferred | yes | yes | contradiction |
| 38 | new | supply_shock | manual_review_needed | unknown | yes | yes | support |
| 71 | new | ceasefire_deescalation | scheduled_or_weak_anchor | high | yes | yes | support |
| 153 | new | sanction | scheduled_or_weak_anchor | high | no | no | unresolved |
| 154 | new | sanction | manual_review_needed | unknown | no | no | unresolved |
| 160 | new | ceasefire_deescalation | partial_anticipation | elevated | no | no | unresolved |
| 212 | new | tariff | clean_discrete_anchor | low | yes | yes | unresolved |
| 239 | new | monetary_policy_or_rates | manual_review_needed | unknown | yes | yes | unresolved |

- Missing market readouts: **153, 154, 160** — note these still carry an
  event-date quality label (scheduled / manual / partial) even though no window
  can be read. A label is not a readout, and a readout is not an outcome.
- Only **210** and **212** are `clean_discrete_anchor`; the other 13 carry an
  anticipation, scheduling, duplicate, or manual-review caveat.

## Family cross-section (accepted thesis rows, single-match overlay)

Event-date quality by mechanism family over the single-match accepted thesis
rows, in canonical taxonomy order (not a ranking).

| family | n | clean | partial | scheduled | thread | dup | manual |
| --- | --- | --- | --- | --- | --- | --- | --- |
| supply_shock | 20 | 2 | 1 | 0 | 0 | 3 | 14 |
| geopolitical_conflict_context | 11 | 0 | 4 | 0 | 0 | 0 | 7 |
| tariff | 11 | 3 | 1 | 0 | 0 | 0 | 7 |
| sanction | 4 | 0 | 0 | 2 | 0 | 0 | 2 |
| ceasefire_deescalation | 3 | 0 | 1 | 2 | 0 | 0 | 0 |
| monetary_policy_or_rates | 3 | 0 | 0 | 1 | 0 | 0 | 2 |

single-match **52** + multi-match **16** + unclassified **18** = **86**. The 16
multi-match and 18 unclassified accepted thesis rows are not assigned to a single
family and are outside the per-family rows.

## Reader takeaways

- Most accepted track-record rows carry `manual_review_needed`: the date anchor
  or fields need a manual look before any window is read.
- `clean_discrete_anchor` is the minority of the accepted track record (5 of 86)
  and is more common among the curated observation rows than the thesis rows.
- The archive-only `continuation_or_thread_sibling` label never appears in the
  accepted corpus; thread siblings are not carried as independent anchors.
- In the 15-case library only two cases (210, 212) are `clean_discrete_anchor`;
  the rest carry anticipation, scheduling, duplicate, or manual-review caveats.
- An anchor's quality label, its event-study availability, its market-readout
  availability, and its thesis outcome are four separate facts; this report keeps
  them separate and combines none of them into a number.

## Lens discipline

- The event-date quality label, event-study availability, market-readout
  availability, and thesis outcome are four different lenses; do not collapse
  them into one number.
- A label is research caution about the date anchor; it is not a statement about
  whether the thesis held or how the market moved.
- Event-study availability is whether a SPY-relative window can be computed; it
  is not anchor quality and not thesis support.

## Caveats / non-claims

- An event-date quality label is research caution, not evidence of any mechanism
  and not a measure of mechanism correctness.
- This report adds no new score and no ranking; it ranks nothing and orders no
  subset or family by anchor quality.
- Counts are descriptive; a visible pattern is not inference, and there is no
  significance claim, no p-value, and no FDR here.
- The closed Phase 1 / Phase 2 FDR pools remain separate from this descriptive
  read; nothing here is merged into them.
- Not a recommendation, forecast, or trading signal.

## Reproduce (read-only)

```
python scripts/event_date_quality_distribution_report.py --db-path events.db --json
python scripts/event_date_quality_distribution_report.py --db-path events.db
```
