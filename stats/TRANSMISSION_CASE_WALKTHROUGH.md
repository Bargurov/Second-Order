# Representative transmission-case walkthrough

**Date:** 2026-06-11
**Status:** read-only, recomputable research artifact. No events.db write. No
DB labels. No new denominator. No event-study math change. No paid analysis.
Backend only — not a frontend change and not a trading surface.

Reproduce (the report, not the numbers below, is the source of truth):

```
python scripts/transmission_case_walkthrough_report.py --db-path events.db --json
python scripts/transmission_case_walkthrough_report.py --db-path events.db
```

## Scope and denominators

| denominator | value |
|---|---|
| archive rows | 180 |
| accepted coverage | 94 |
| accepted track-record | 86 |
| staged candidates | 13 |

The report draws only from the **86** accepted thesis rows and adds no
denominator. Staged candidates are never eligible for selection.

## Why this report exists

The family-overlay arc (J1/K1/L1) *classified* the accepted corpus and
*measured* its labeling limitation. This report does the complementary thing:
it **shows the full transmission chain** for a small, honestly-selected set of
real cases, so a finance reviewer can read end to end —

> event → what changed → mechanism / transmission → named assets →
> 1d / 5d / 20d reaction → event-study (AR/SAR/CAR) readout if available →
> event-date-quality caveat → track-record outcome / scoring-sensitivity
> caveat → non-claims.

It rebuilds nothing: family label via J1's `classify_headline`; anchor caveat
via `event_date_quality_report`; outcome + sensitivity via
`stats.track_record_scoring`; 1d/5d/20d AR/SAR/CAR via the same event-study
gate as `GET /events/{id}/event-study`.

## Selection policy (deterministic, outcome-diverse, not winners-only)

- **Accepted-only**, deterministic, no randomness. Ranking is
  `info_score` desc, then `event_id` asc. `info_score` rewards a fuller, less
  anticipation-confounded walkthrough: event-study readout available (+2),
  usable mechanism text (+1), named assets (+1), clean event-date anchor (+1).
- **Outcome diversity is forced**: the first three picks fill the required
  roles — one support, one contradiction, one unresolved/data-limited — before
  any family-diversity fills. This is the winners-only guard.
- **Family diversity preferred**: remaining slots take the most-informative
  row from a not-yet-used family.

## Selected-case table (live snapshot, 2026-06-11; default 6 cases)

| id | role | outcome | family overlay | event-date anchor | event |
|---|---|---|---|---|---|
| 1 | support_case | support | tariff | partial_anticipation | US may impose new tariffs on Chinese EV imports |
| 61 | contradiction_case | contradiction | geopolitical_conflict_context | partial_anticipation | "How Trump's Iran war could make the world…" |
| 210 | unresolved_or_limited_case | unresolved | supply_shock | clean_discrete_anchor | Saudi Arabia raises crude OSPs |
| 46 | mechanism_diversity_case | support | monetary_policy_or_rates | scheduled_or_weak_anchor | Federal Reserve Board announcement |
| 66 | mechanism_diversity_case | support | ceasefire_deescalation | scheduled_or_weak_anchor | "'Iran open to negotiations': diplomacy…" |
| 211 | mechanism_diversity_case | unresolved | sanction | scheduled_or_weak_anchor | China warns "price must be paid" after US move |

Six cases span **six** mechanism families and three outcome buckets. All six
carry a local event-study readout, named assets, and usable mechanism text
(missingness summary: 0 / 0 / 0 on this snapshot).

## Per-case walkthrough (read the report for full text and live numbers)

- **#1 — tariff, support.** Named assets TSLA / F / DRIV / NIO / XPEV / STLA.
  The descriptive window is negative on the basket vs SPY (≈ −2.6% 1d /
  −6.8% 5d) — note that the **support** label is a per-ticker
  direction-agreement read under the generous any-support rule, *not* a
  positive-basket claim, and the anchor carries partial-anticipation risk.
- **#61 — conflict, contradiction.** The deliberate counterweight: the named
  assets moved against the thesis direction. Included so the set is never a
  winners reel.
- **#210 — supply_shock, unresolved.** A clean discrete OSP-hike anchor whose
  window neither supports nor contradicts under the any-support rule — an
  honest non-result.
- **#46 / #66 — monetary / ceasefire, support** on scheduled/weak anchors:
  the anchor caveat warns the window measures residual surprise, not the full
  event.
- **#211 — sanction, unresolved.** A retaliation-warning row that does not
  resolve directionally.

## Outcome-diversity check

support 3 · contradiction 1 · unresolved-or-limited 2 → **passes = true**.
The support-lean of the fills reflects the archive's own any-support
distribution (46 of 86 accepted rows score `validated` under the generous
rule); the report does not rebalance it, it discloses it.

## Missingness summary

On this snapshot every selected case has an event-study readout, named assets,
and mechanism text (0 / 0 / 0). When a selected row lacks an event-study
window, the report surfaces the `blocking_reasons` as a `missingness_note`
rather than silently dropping the horizons.

## Taxonomy lessons

- **What the cases show:** a recomputable, end-to-end transmission read per
  case, across families and outcomes — an honest cross-section, not a winners
  reel.
- **What the cases do not show:** nothing statistical. Each is n=1 (no CI,
  p-value, FDR); a single case does not characterise its family, and the cases
  are not compared for performance.
- **Why representative cases are not proof:** the per-case scoring-sensitivity
  and event-date-quality caveats show how fragile a single-event read is — a
  clean window can still reflect anticipation, window overlap, or single-name
  idiosyncrasy.

## How this differs from the frontend Case Library

The frontend **Case Library** is a guided UI surface organized by track-record
outcome. This report is a **backend, recomputable, read-only artifact**
organized to span mechanism families *and* outcomes, with the event-date
anchor caveat, the event-study readout, and the scoring-sensitivity caveat
assembled inline per case and re-derivable from `events.db` with `mode=ro`. It
touches no frontend.

## Non-claims

- Representative illustrations, **not proof** of any mechanism.
- n=1 per case; descriptive event-window evidence only; no single-event
  significance (no CI, p-value, FDR).
- No family-level inference and no performance ranking across families.
- Not a recommendation of any kind.
- The closed Phase 1 / Phase 2 FDR pools are neither read nor reopened.
- No paid analysis run or approved; paid `/analyze` remains blocked.
- No database write; `mechanism_family` and `price_cache` untouched.
- Denominators unchanged: 94 accepted coverage / 86 accepted track-record.

## Final recommendation

- **Keep the report read-only** and use it as a reviewer-walkthrough evidence
  surface — it recomputes from the live archive.
- **Do not promote representative cases to proof**; the caveats are part of
  each case, not a footnote.
- **Do not add a frontend** for this until the backend artifact has been
  reviewed and is stable; the existing Case Library already serves the UI.
