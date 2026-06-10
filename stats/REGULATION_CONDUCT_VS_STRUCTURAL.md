# Regulation conduct vs structural — 303 (DOJ v Apple) vs 304 (DOJ v Google ad-tech)

**Date:** 2026-06-11 · **Status: staged / no-paid — a representative
comparison, not evidence; no promotion, no paid analysis approved; 304's
paid path stays closed/deferred.**

Reproduce read-only:

```powershell
python scripts/regulation_conduct_structural_memo.py --db-path events.db --json
```

## Scope and denominators

Denominators unchanged: 180 archive rows · **94** accepted coverage · **86**
accepted track-record · **13** staged. Regulation: 5 staged / 0 accepted.
Primary comparison: **303 and 304** (both clean discrete anchors per the C4
layer). Context only: 305/306 (Tier-2). Deferred: 302 (duplicate of
quarantined 315).

## Why this comparison matters

303 and 304 are the archive's cleanest pair on the dimension antitrust
actually varies: **what the state threatens**. 303 is a *conduct* case —
behavioural remedies against platform-ecosystem restrictions. 304 is a
*structural* case — divestiture of the ad-tech stack, the sharpest remedy
form available. Two clean filing-date anchors at the two ends of the remedy
spectrum make the most legible no-paid comparison the regulation family can
currently offer.

## Cases

| id | date | defendant | anchor (C4) | subtype | paid path |
|---|---|---|---|---|---|
| 303 | 2024-03-21 | AAPL | clean_discrete_anchor | platform_ecosystem / conduct_remedy | no-paid default |
| 304 | 2023-01-24 | GOOGL | clean_discrete_anchor | structural_remedy (ad-tech divestiture) | **closed/deferred by operator (B2b)** |

## Descriptive readout (n=1, AR vs SPY)

| id | 1d | 5d | 20d |
|---|---|---|---|
| 303 (conduct) | +0.72% | −0.10% | +1.46% |
| 304 (structural) | **−2.58%** | −0.40% | **−5.78%** |

## Why 304 moved more than 303 — and why that is not proof

The pattern is *consistent* with the textbook prior (structural threats
reprice harder than conduct threats), but **it cannot be read as mechanism
strength**, for one sharp reason and two ordinary ones:

1. **The exposure-mix confound (the core point):** remedy type is confounded
   with dollars-at-risk in this pair. The challenged ad-tech business is a
   far larger share of the 304 defendant's economics than the challenged
   conduct is of 303's. Even if markets priced both suits identically per
   dollar at risk, 304's defendant would move more. Remedy severity and
   exposure share cannot be separated with these two cases.
2. Different filing dates sit in different macro tapes (early 2023 vs
   spring 2024) — cross-case differences may be regime, not mechanism.
3. n=1 per case: no CI, no p-value, no FDR; same-window tape moves are
   never disentangled from the filing at n=1.

What each case *does not show*, stated per case: 303's quiet window cannot
separate "conduct remedies priced as small" from "not priced at all"; 304's
negative window cannot rank remedy types.

## What can / cannot be read

- **Can:** two descriptive n=1 windows representing the two ends of the
  antitrust remedy spectrum, side by side, as research framing.
- **Cannot:** any ranking of remedy-type severity, any regulation-family
  effect, any causal attribution of either defendant's move to its filing.

## Disposition

- **Keep 303/304 staged/no-paid**; use this memo as the representative
  comparison only.
- **304's paid path remains closed/deferred** (operator decision, B2b); this
  memo does not reopen it.
- Review 305/306 later only if the family is deliberately expanded.
- **No paid analysis approved; no promotion.**

## How this updates the regulation family

C3's rank-2 no-paid move is done. The family now carries: a cohort packet
(C1), a paid-gate packet with an operator deferral (B1/B2b), and this
focused conduct-vs-structural comparison — all read-only, all staged/no-paid.

## Non-claims

- Staged candidates are not accepted evidence; denominators (94/86)
  unchanged; no promotion, no stage/hygiene change.
- No paid analysis run or approved; 304's paid path remains closed/deferred.
- Descriptive n=1 readouts only; no significance, no family-level inference,
  no recommendation; the comparison is illustrative, not proof.
- The closed Phase 1 / Phase 2 FDR pools are untouched.
