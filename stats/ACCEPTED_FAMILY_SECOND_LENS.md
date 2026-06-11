# Accepted-family overlay — second lens (mechanism text)

**Date:** 2026-06-11
**Status:** read-only research comparison. No events.db write. No DB labels.
No J1 rule change. No K1 refinement applied. No denominator change. No paid
analysis. Overlay-only.

Reproduce:

```
python scripts/accepted_family_second_lens_report.py --db-path events.db --json
python scripts/accepted_family_second_lens_report.py --db-path events.db
```

## Scope and denominators

Live archive denominators are unchanged by this comparison:

| denominator | value |
|---|---|
| archive rows | 180 |
| accepted coverage | 94 |
| accepted track-record (overlay target) | 86 |
| staged candidates | 13 |

The headline label for every row is taken from J1's `build_overlay` output
(`scripts/accepted_family_overlay_report.py`); the report does not re-select or
re-classify the headline lens. The second lens reuses J1's `classify_headline`
rule engine on mechanism text — same family vocabulary, different basis field.
J1 rules are not modified and no K1 refinement is applied.

## Why the second lens exists

K1 suggested a possible future second lens using `mechanism_summary` or richer
mechanism text, reported separately from the headline lens. This report tests
that idea read-only: does running the same J1 rules over local mechanism-text
fields **resolve** headline ambiguity (the 16 multi-match and 18 unclassified
rows), or does it add more?

## Mechanism-text field coverage (over the 86 accepted rows)

| field | non-empty | usable | generic/empty |
|---|---|---|---|
| mechanism_summary | 86 | **86** | 0 |
| what_changed | 86 | **86** | 0 |
| market_note | 86 | **86** | 0 |
| transmission_chain | 86 | 52 | 34 |
| notes | 0 | 0 | 86 |
| transmission_path | 86 | 0 | 86 |

Every accepted row has rich, usable text in `mechanism_summary`,
`what_changed`, and `market_note` (medians ~359 / ~138 / ~455 chars).
`transmission_chain` is usable about 60% of the time (the rest are the
placeholder `[]`). `notes` is empty corpus-wide and `transmission_path` is the
placeholder `[]` on every row — both are reported but contribute no text. So
text availability is **not** the constraint; text *behaviour* is.

## Headline lens vs second lens

| lens | single | multi | unclassified |
|---|---|---|---|
| headline (J1) | 52 | 16 | 18 |
| second (mechanism text) | 30 | **32** | 24 |

| comparison | count |
|---|---|
| changed (family set differs) | 34 |
| unchanged (family set identical) | 52 |
| worsened / more ambiguous | 18 |

Change-type breakdown (sums to 86):

| change_type | count |
|---|---|
| unchanged_single | 27 |
| worsened_or_more_ambiguous | 18 |
| unchanged_unclassified | 15 |
| confirmed_multi_match | 10 |
| review_needed | 12 |
| resolved_unclassified | 3 |
| clarified_multi_match | 1 |

The headline lens has 16 multi-match rows; the second lens has **32**. The
second lens does not reduce ambiguity — it roughly doubles the multi-match
count, because mechanism summaries describe the whole transmission (supply +
conflict + policy backdrop), so several families match per row.

## Rows improved by the second lens (resolved_unclassified = 3)

These are exactly the rule-miss rows K1 flagged, plus one taxonomy-gap row:

- **218** (Saudi voluntary oil-supply cut) `[]` → `[supply_shock]` — the
  cleanest gain: the headline dodged the oil token, the mechanism text names
  the supply mechanism. Single, unambiguous.
- **34** (Strait-of-Hormuz threat) `[]` → `[geopolitical_conflict_context,
  supply_shock]` — recovered, but as a (legitimate) multi-match, not a clean
  single.
- **25** (Foxconn earnings citing geopolitics) `[]` → `[tariff]` — candidate
  only: verify the tariff family is the event's mechanism, not an incidental
  backdrop mention. K1 read this row as a generic-geopolitics taxonomy gap.

That is the entire upside: 3 of 18 unclassified rows recovered, only one of
them as a clean single family.

## Rows still unresolved (45 rows in the unresolved/review-needed set)

- **15 unchanged_unclassified** — archive-noise rows (Moon, crime, auto-show)
  whose mechanism text is generic or matches nothing. They stay unclassified,
  which is correct — the second lens does not force them.
- **18 worsened_or_more_ambiguous** — single-family headline rows that gain a
  backdrop family from the text, e.g. several `[supply_shock]` →
  `[geopolitical_conflict_context, supply_shock]`, and conflict rows gaining
  `sanction` / `supply_shock`. The added family is real backdrop, not the
  event's primary mechanism.
- **12 review_needed** — the text disagrees with the headline: some single
  rows whose text matches no token at all (e.g. a `tariff` headline whose
  `mechanism_summary` never says tariff → `[]`), and multi rows whose text
  shifts the overlap (17, 63 `ceasefire+supply` → `sanction+supply`; 250
  `conflict+tariff` → `sanction+tariff`; 292 → `[]`).

## Rows where the second lens should NOT override headline ambiguity

- **47** `[conflict, supply]` → `[supply]` (clarified_multi_match): the text
  emphasised supply, but K1 found conflict×supply overlaps legitimate, so
  dropping conflict would discard a real channel. Treat as a candidate only.
- The 10 **confirmed_multi_match** rows (e.g. 3, 11, 12, 37): the text
  reproduces the same overlap — corroborating K1's legitimate-overlap reading,
  not a reason to collapse them.
- The multi **review_needed** shifts (17, 63, 250, 292): the text picks up a
  different family (often `sanction`, which appears in the macro backdrop of
  most oil/ceasefire rows). This is incidental-token noise, not a cleaner
  label.

## Taxonomy lessons

- **What the second lens reveals:** running J1's headline rules over mechanism
  text does not cleanly reduce ambiguity; it raises multi-match from 16 to 32
  because the text references multiple backdrop families per row. The only
  genuine recall gains are the rule-miss rows K1 already identified.
- **Where text fields help:** recovering a handful of unclassified rule-miss
  rows whose text states the family directly (218, 34), and *confirming* —
  not resolving — the legitimate multi-match overlaps.
- **Where text fields do not help:** single-family rows (text adds backdrop →
  worse), disambiguating legitimate overlaps (text shifts, not resolves), and
  archive noise (correctly stays unclassified).
- **What should not be forced:** do not adopt the second lens as a replacement
  classifier (it changes 34 of 86 rows and doubles multi-match); do not let an
  incidental backdrop family override a clean headline single; do not narrow a
  legitimate overlap because the text emphasised one channel.

## How this updates ACCEPTED_FAMILY_OVERLAY and ACCEPTED_FAMILY_OVERLAY_REVIEW

This report does not change J1's overlay or K1's review. It adds a read-only
second lens and records that:

- the headline lens remains the right primary lens (52/16/18 unchanged);
- a mechanism-text lens, using the same rules, is **not** a clean
  disambiguator — it recovers only 3 unclassified rows while worsening 18 and
  needing review on 12;
- the second lens is useful only as a narrow, manually-reviewed recall aid for
  the specific unclassified rule-miss rows (notably 218 and 34), exactly the
  cases K1 already named — not as a corpus-wide reclassifier.

## Non-claims

- Second-lens labels are a read-only comparison artifact, **not DB labels**;
  the `mechanism_family` column was not read as truth and was not modified.
- No database write occurred anywhere in this report; price_cache untouched.
- J1 rules are unchanged; K1 refinements are not applied (no `trade war`
  negative phrase, no context-gated supply phrase, no catch-all bucket).
- No family-level inference, no family performance ranking, no
  validated-vs-contradicted comparison.
- No significance testing (no CI, p-value, or FDR); the closed Phase 1 /
  Phase 2 FDR pools are neither read nor reopened.
- Not a recommendation of any kind.
- No paid analysis was run and none is approved; paid `/analyze` remains
  blocked.
- Denominators unchanged: 94 accepted coverage / 86 accepted track-record.

## Final recommendation

- **Keep the second lens read-only.** It is a comparison artifact, not a
  classifier.
- **Do not write DB labels** from either lens.
- **Do not apply K1 rule refinements automatically**; this report does not
  change that posture.
- **Only consider a K2 rule-refinement task** for the narrow, named rule-miss
  rows (e.g. 218, 34) where the mechanism text states the family directly and
  a human has reviewed it — not as a corpus-wide second-lens reclassification,
  which this report shows adds more ambiguity than it resolves.
