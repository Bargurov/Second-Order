# Accepted-corpus mechanism-family overlay — classifying the 86 untagged thesis rows

**Date:** 2026-06-11 · **Status: read-only overlay — labels live in memory
only. Nothing was written to `events.db`; the `mechanism_family` column is
untouched; no inference is claimed.**

Reproduce read-only:

```powershell
python scripts/accepted_family_overlay_report.py --db-path events.db --json
python scripts/accepted_family_overlay_report.py --db-path events.db
```

## Scope and denominators

Denominators unchanged: 180 archive rows · **94** accepted coverage · **86**
accepted track-record · **13** staged. Overlay target = the **86 accepted
thesis rows** (selected with the same loader as the AV3 scoring-sensitivity
report; staged, curated-observation, intake, pending, and synthetic rows are
excluded and never classified).

## Why this overlay exists

`stats/MECHANISM_FAMILY_OVERVIEW.md` states the project's largest taxonomy
limitation: **every thesis row in the track-record corpus is
family-untagged** (`none`), so per-family splits are structurally
degenerate. This overlay measures how the taxonomy covers that corpus
without mutating it: deterministic, inspectable, whole-token rules over
headlines, computed in memory. A row matching two families is surfaced as
ambiguous (never forced); a row matching none stays unclassified.

## Family coverage (live)

| overlay family | canonical | rows | share | example ids |
|---|---|---|---|---|
| supply_shock | yes | **20** | 23.3% | 29, 38, 39 |
| tariff | yes | 11 | 12.8% | 1, 31, 80 |
| geopolitical_conflict_context | **overlay-only** | 11 | 12.8% | 7, 16, 26 |
| sanction | yes | 4 | 4.7% | 153, 154, 211 |
| ceasefire_deescalation | yes | 3 | 3.5% | 66, 71, 160 |
| monetary_policy_or_rates | **overlay-only** | 3 | 3.5% | 46, 231, 239 |
| regulation | yes | **0** | 0.0% | — |
| labor_inflation | yes | **0** | 0.0% | — |
| industrial_policy | yes | **0** | 0.0% | — |
| *(multi-match, not forced)* | — | 16 | 18.6% | see report |
| *(unclassified / review-needed)* | — | 18 | 20.9% | see report |

Single-match + multi-match + unclassified = **86** exactly.

## What the overlay reveals

1. **The archive's core is conflict-driven supply disruption.** supply_shock
   is the dominant bucket (20 rows), conflict context adds 11 more, and 9 of
   the 16 multi-match rows sit precisely on the conflict × supply overlap —
   a cluster the canonical 14-family taxonomy has no single name for.
2. **The C3 finding reproduces from the other side:** regulation,
   labor_inflation, and industrial_policy score **zero** accepted thesis
   matches — those families exist only as staged candidates.
3. **Two overlay-only buckets mark real, unnamed corpus mass:** central-bank
   rows (3) and conflict-context rows have no canonical family.
4. **The unclassified bucket (18 rows, 20.9%) is honest residue**, mixing
   visibly off-topic rows (Artemis crew, human-interest items — e.g. ids 2,
   8, 9) with terse market headlines the rules under-classify (e.g. id 34
   says "Strait" without "Hormuz"). It needs curated review, not looser
   rules.

## Descriptive splits — coverage decomposition, not family performance

Per-event outcomes use the canonical `any_support` rule from the AV3 scoring
module, aggregated by overlay family (validated / contradicted /
unresolved):

| family | n | v / c / u |
|---|---|---|
| supply_shock | 20 | 11 / 3 / 6 |
| tariff | 11 | 5 / 0 / 6 |
| geopolitical_conflict_context | 11 | 7 / 2 / 2 |
| sanction | 4 | 0 / 0 / 4 |
| ceasefire_deescalation | 3 | 2 / 0 / 1 |
| monetary_policy_or_rates | 3 | 1 / 0 / 2 |

These counts **locate the corpus; they do not compare families**: the labels
are post-hoc keyword matches, n per family is tiny, and no significance is
computed. See `stats/METHODOLOGY.md` and the AV3 sensitivity report for how
outcome labels move under stricter scoring rules.

## The rules are the contract

Every rule is a short list of whole-token terms/phrases with a written
rationale, embedded in the report (`family_rules`). Whole-token matching is
deliberate ("oil" must not fire inside "turmoil", "war" not inside "warns" —
fixture-tested), and the bare token "strike" is excluded from labor rules
because it collides with military strikes throughout this archive.

## How this updates MECHANISM_FAMILY_OVERVIEW

The overview's "structurally degenerate" limitation now has a measured
shape: ~61% of the thesis corpus is nameable by simple rules (53 single +
16 multi of 86), concentrated in supply/conflict/tariff; ~21% is
unclassified residue; three canonical families are confirmed empty on the
accepted side. The overview's table is unchanged — this is an overlay lens
over it, not a replacement.

## Non-claims

- Overlay labels are research overlay, **not DB labels**; no database write
  occurred; `mechanism_family` stays untouched and price_cache untouched.
- No family-level inference, no family performance ranking, no significance
  testing (no CI, p-value, FDR); not a recommendation.
- Staged candidates never enter the overlay target; denominators (94/86)
  unchanged; the closed Phase 1 / Phase 2 FDR pools are untouched.
- No paid analysis run or approved; paid `/analyze` remains blocked.

## Final recommendation

Keep the overlay read-only. **Do not write labels into the DB yet** — only
consider DB labels after the rule table has been human-reviewed and is
stable, and then only as its own gated task. Natural no-mutation next steps:
curated review of the unclassified/multi buckets, and a second basis-field
lens (`mechanism_summary`) reported separately. No paid analysis, no
inference claim.

> **Weak-bucket diagnostics (K1):** a read-only review of the 16 multi-match
> and 18 unclassified rows — why each landed there, which overlaps are
> legitimate, and bounded (never-applied) rule refinements — is in
> [`stats/ACCEPTED_FAMILY_OVERLAY_REVIEW.md`](ACCEPTED_FAMILY_OVERLAY_REVIEW.md)
> / `scripts/accepted_family_overlay_review.py`.
