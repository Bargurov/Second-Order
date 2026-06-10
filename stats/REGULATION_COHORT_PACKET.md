# Regulation-family cohort packet — staged antitrust / market-structure cases

**Date:** 2026-06-10 · **Status: staged / no-paid review cohort — not accepted
evidence, no promotion, no paid analysis approved.**

Reproduce read-only:

```powershell
python scripts/regulation_cohort_packet.py --db-path events.db --json
```

## Scope and denominators

Denominators unchanged: 180 archive rows · **94** accepted coverage · **86**
accepted track-record · **13** staged candidates. The regulation family has
**5 staged rows and 0 accepted rows** — everything below is review staging,
outside every accepted denominator.

Cohort scope: **included 303 / 304 / 305 / 306** · **deferred 302**
(same-announcement duplicate of quarantined row **315**, which stays
pending-related and outside the cohort).

## Why the regulation family matters

The accepted archive's labeled evidence is entirely tariff/sanction curated
observations, and its thesis rows cluster on oil / war / semiconductors. The
staged antitrust cases would add a different transmission channel — legal /
regulatory overhang on named defendants — with an internal contrast the
existing archive cannot offer: conduct remedies vs structural (divestiture)
remedies, across platform, live-events, and payments market structures.

## Case table (event-date quality from the C4 layer — derived, not assumed)

| id | date | defendant | C4 anchor label | cohort use | subtype |
|---|---|---|---|---|---|
| 302 | 2023-09-26 | AMZN | duplicate_or_deferred | **deferred_duplicate** | platform_ecosystem / conduct_remedy |
| 303 | 2024-03-21 | AAPL | clean_discrete_anchor | usable_clean_anchor | platform_ecosystem / conduct_remedy |
| 304 | 2023-01-24 | GOOGL | clean_discrete_anchor | usable_clean_anchor | structural_remedy (ad-tech divestiture) |
| 305 | 2024-05-23 | LYV | clean_discrete_anchor | usable_clean_anchor | market_structure / vertical_integration |
| 306 | 2024-09-24 | V | clean_discrete_anchor | usable_clean_anchor | payments_network / network_access |

All five dates are DOJ/FTC suit filings, so the C4 layer reads four of them
as clean discrete anchors; 302 defers on the duplicate collision with row
315, not on date quality.

## Descriptive readout (n=1 per case; AR vs SPY; no significance)

| id | 1d | 5d | 20d |
|---|---|---|---|
| 302 (deferred) | −0.04% | +0.01% | +2.58% |
| 303 | +0.72% | −0.10% | +1.46% |
| 304 | −2.58% | −0.40% | −5.78% |
| 305 | +2.02% | +0.01% | −7.58% |
| 306 | −0.93% | +2.24% | +2.30% |

Read side by side, the descriptive picture is **heterogeneous**: the
structural-remedy case (304) shows the clearest negative defendant reaction;
the conduct case (303) barely moves; 305 and 306 are mixed across horizons.
That heterogeneity is itself the honest takeaway — four n=1 points spanning
2023–2024 macro regimes, not a family result. No pooled statistic is computed
and none would be defensible at this size.

## Mechanism taxonomy and case limits

- **303 — conduct remedy on a platform ecosystem:** developer-restriction
  overhang on AAPL services; single-name, remedies long-dated.
- **304 — structural remedy:** divestiture risk on the GOOGL ad-tech stack;
  **paid path closed-deferred by operator (B2b)**; second-order ad-tech names
  have no local price data (B1 packet).
- **305 — market structure / vertical integration:** promotion + venues +
  ticketing stack at LYV; smaller-cap defendant, noisier windows.
- **306 — payments network access:** debit-routing conduct overhang on V (MA
  rides as a related beneficiary leg in the staged row).
- **302 — deferred duplicate** of quarantined row 315; retired from future
  paid consideration (AX1); resolve before any use.

## How C4 changes interpretation

The event-date quality layer is consumed as an input, not re-derived by hand:
labels above come from `scripts/event_date_quality_report.py` at run time. If
a future row drifts (a duplicate appears, a date weakens), this packet's
labels move with it. Cohort rules inherited from C4: deferred duplicates
never count, thread siblings would collapse into their anchors (none exist in
this family today), and any scheduled/weak anchor would be read as residual
surprise only.

## Family-level limits

- Four usable cases is a **comparison set, not a cohort statistic** — no
  pooled mean, no test, no family-level inference.
- All four usable cases are single-defendant equity reads; second-order
  ecosystem names are not staged and mostly lack local price data.
- 2023–2024 filing dates sit in different macro regimes; cross-case
  differences may be regime, not mechanism.

## Non-claims

- Staged candidates are not accepted evidence; denominators (94 / 86)
  unchanged; no promotion, no stage or hygiene change.
- No paid analysis run or approved; paid `/analyze` remains blocked; 304's
  paid path is closed-deferred by operator decision.
- Descriptive n=1 readouts only — no CI, p-value, FDR, or significance.
- Mechanism chains and subtypes are research taxonomy to be tested, not
  established causal claims; the closed Phase 1 / Phase 2 FDR pools are
  untouched.

## Final disposition

- **303 / 304** — useful clean anchors for future no-paid comparison (the
  conduct-vs-structural contrast); **304's paid path stays closed-deferred**.
- **302** — remains a deferred duplicate; retired from paid consideration.
- **305 / 306** — clean dates per C4, but Tier-2 shortlist priority: cautious
  no-paid review before any future consideration (the antitrust family is
  already represented by 303/304).
- **No paid analysis is approved** by this packet, and nothing here promotes
  a candidate.
