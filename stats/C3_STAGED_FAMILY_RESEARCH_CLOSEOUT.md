# C3 staged-family research arc — closeout memo

**Date:** 2026-06-11 · **Status: arc closed.** All four ranked no-paid moves
on the C3 board are executed and documented. Everything in this arc stays
**staged / no-paid**: nothing was promoted, nothing was paid-analyzed, no
database row changed, and the one designed mutation (the LEA/APTV backfill)
remains **not approved**.

## Scope

This memo consolidates the staged-family research arc that started with the
C3 coverage board (`stats/STAGED_FAMILY_COVERAGE.md`) and ran through its
four ranked moves: D1 (industrial_policy anchors), E1 (sanction/export-
control thread collapse), F1 (regulation conduct-vs-structural memo), and
G1 (UAW supplier backfill gate). It is a legibility deliverable — no new
analysis, no new claims.

## Starting problem

The 13 staged candidates made the staged universe look broader than it was.
Four families (regulation, labor_inflation, industrial_policy, sanction)
appeared on the board, but family counts hid three problems: weak anchors
(scheduled signings read as if they were shocks), thread density (escalation
rows counted as independent events), and a computability illusion (cached
rows treated as readable windows). The arc's job was to apply anchor,
thread, and gate discipline so each family's staged rows say exactly what
they can and cannot support.

## Denominator snapshot (unchanged throughout)

180 archive rows · **94** accepted coverage · **86** accepted track-record ·
**13** staged candidates. Every readout in the arc is a descriptive n=1
point estimate vs SPY. Staged candidates never entered an accepted
denominator at any point.

## What each slice resolved

### D1 — industrial_policy anchor quality (311 CHIPS / 312 IRA)

Both cases anchor on **scheduled bill signings** (C4:
`scheduled_or_weak_anchor`), so their windows measure residual surprise
only. Near-zero 1d windows match the priced-in prediction; FSLR's +24.21%
20d drift is the cautionary exhibit — post-passage repricing context, not a
signing-date effect (INTC's −7.91% cuts the opposite way). **Resolution:
keep 311/312 staged/no-paid; re-anchoring needs credible milestone evidence
(price-side history is already cached, but the milestone event rows are
missing locally).** → `stats/INDUSTRIAL_POLICY_ANCHOR_PACKET.md`

### E1 — sanction/export-control thread collapse (307–310)

Connected components over the C4 thread links: the **4 raw staged rows add
0 independent events**, collapsing into **2 effective threads** rooted at
curated anchors — [298, 309] (Huawei) and [300, 307, 308, 310]
(NVIDIA/advanced computing). The three NVDA rows' +10–13% 20d windows are
overlapping same-ticker windows on one secular tape, not three separate
observations. **Resolution: keep 307–310 staged/deferred; future packets
take at most one observation per thread component, anchored at the curated
root.** → `stats/SANCTION_THREAD_COLLAPSE.md`

### F1 — regulation conduct vs structural (303 DOJ v Apple / 304 DOJ v Google)

The family's two clean discrete anchors now have their comparison: conduct
remedy (303, AAPL +0.72/−0.10/+1.46%) vs structural divestiture threat
(304, GOOGL −2.58/−0.40/−5.78%). The pattern matches the textbook prior,
but **304's more negative window does not establish mechanism strength**:
remedy type is confounded with exposure share in this pair, the filings sit
in different macro tapes, and each case is n=1. **Resolution: keep 303/304
staged/no-paid as the representative comparison; 304's paid path remains
closed/deferred (operator decision, B2b).**
→ `stats/REGULATION_CONDUCT_VS_STRUCTURAL.md`

### G1 — UAW supplier backfill gate (313)

**Rows-exist is not compute-ready**, now machine-measured: GM (900 rows,
275 pre-event dates) and F (928/275) are compute-ready; LEA and APTV hold
174 cached rows each — all 2026-dated, **zero pre-event dates** for
2023-09-15 — so the supplier legs cannot be read. The gate defines the
exact bounded write a future backfill would be allowed to make (LEA/APTV
daily bars **2023-05-30..2023-10-27**, ~106 per ticker, **212 rows max**,
`price_cache` only, derived from the cached SPY trading calendar) and the
nine-step safety sequence any mutation must pass. **Resolution: design
done; the actual backfill is NOT approved and requires a separate operator
decision.** → `stats/UAW_SUPPLIER_BACKFILL_GATE.md`

## Cross-cutting research lessons

1. **Weak anchors are not clean shocks.** A scheduled signing's window
   measures residual surprise; reading drift as an event effect is the
   error, not the finding (D1).
2. **Thread siblings are not family breadth.** Four staged rows on one
   escalation path are one thread's depth, not four events (E1).
3. **Representative cases are not proof.** A clean two-case contrast can
   still be confounded — here remedy type with exposure share (F1).
4. **Rows-exist is not compute-ready.** Cached rows prove presence, not
   readability at the event date; window checks must be bounded so
   far-future rows cannot fake coverage (G1, and C2A before it).
5. **Paid gates save money.** Every move in this arc was no-paid; the two
   places where paid calls were tempting (304 analysis, supplier backfill
   sourcing) are both closed behind explicit operator gates instead of
   having been spent.

## Current non-claims

- No staged row is accepted evidence; accepted vs staged pools stayed
  separated and the denominators (94/86) never moved.
- No family-level inference anywhere in the arc — every comparison is
  illustrative research design over descriptive n=1 windows.
- No single-event significance: no CI, p-value, or FDR on any readout.
- The closed Phase 1 / Phase 2 FDR pools were neither reopened nor read.
- No paid analysis was run or approved; paid `/analyze` remains blocked.
- Nothing here is a recommendation of any kind.
- No candidate promotion, no stage or event_hygiene change.
- No events.db or price_cache mutation occurred in this phase (DB hash
  unchanged end to end; latest price_cache fetch timestamp predates the
  arc).

## Next fork (operator decision)

- **Option A — freeze.** Close this arc here; the staged universe is now
  honestly labeled and fully documented.
- **Option B — preview the backfill.** Run the G1 safety sequence's
  temp-DB/snapshot preview for the bounded LEA/APTV backfill (still no live
  write; the preview itself needs its own task and approval).
- **Option C — new arc.** Start a different research-depth direction (e.g.
  re-anchoring industrial_policy on milestone evidence, or a thread-level
  sanction observation design). *(Taken — J1, the accepted-corpus family
  overlay: [`stats/ACCEPTED_FAMILY_OVERLAY.md`](ACCEPTED_FAMILY_OVERLAY.md).)*

## Recommendation

**Freeze C3 after this closeout (Option A).** Do not run the live backfill —
or its preview — until the operator explicitly approves a separate temp-DB
preview task through the G1 gate. The arc's value is the discipline layer
itself; it loses nothing by resting here.
