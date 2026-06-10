# UAW supplier-transmission packet — candidate 313, direct OEM vs supplier channel

**Date:** 2026-06-10 · **Status: staged / no-paid — candidate 313 remains
`z1a_candidate_pack`; no promotion, no paid analysis approved.**

Reproduce read-only:

```powershell
python scripts/uaw_supplier_transmission_packet.py --db-path events.db --json
```

## Scope and denominators

Denominators unchanged: 180 archive rows · **94** accepted coverage · **86**
accepted track-record · **13** staged. One staged candidate is read here; it
enters no accepted denominator.

**Candidate 313** — UAW Stand Up Strike begins (2023-09-15), labor_inflation,
staged/no-paid. Event-date caveat from the C4 layer: **partial anticipation**
(telegraphed deadline) — windows may understate or misplace repricing that
leaked in before the strike date.

## The packet's headline finding (a correction, stated plainly)

C2 flagged LEA/APTV as "locally feasible" supplier legs because they have
cached price rows. The event-study gate says otherwise at this event date:
**both supplier caches cover 2026 only (zero pre-event dates for
2023-09-15)**, so the supplier transmission is **not currently computable
locally**. What the local data *does* support today is the direct OEM read —
including an intra-OEM contrast (GM vs F) that C2 did not surface.

| ticker | group | local rows | pre-event dates | gate status |
|---|---|---|---|---|
| GM | direct OEM | yes | 275 | **available** |
| F | direct OEM | yes | 275 | **available** |
| LEA | supplier | yes (2026 only) | **0** | insufficient (no estimation window) |
| APTV | supplier | yes (2026 only) | **0** | insufficient (no estimation window) |
| XLY | context | yes | 180 | insufficient (window not contiguous) |
| SPY | benchmark | yes | 1358 | benchmark basis |
| STLA / TSLA / BWA | excluded | mixed | 0 | excluded (not staged / not linked / no data) |

Closing the supplier gap is a **bounded, separately-approved free backfill**
(~85 daily bars per supplier around 2023-09-15) — a concrete no-paid next
step, not a vague aspiration.

## Descriptive readout (n=1, AR vs SPY, partial-anticipation caveat)

| leg | 1d | 5d | 20d |
|---|---|---|---|
| GM (struck primary) | −1.86% | −1.11% | **−9.96%** |
| F (struck leg) | −2.20% | +1.49% | −3.67% |

The newly-readable intra-OEM contrast: both OEMs dip on day one, but **GM's
20d drift is roughly 2.7× deeper than Ford's**. Descriptively consistent with
escalation-target expectations and exposure mix — and equally consistent with
ordinary idiosyncratic divergence in a confounded macro window. n=1 per leg;
the comparison shows a difference, not a cause.

## Mechanism chain

strike start (targeted plants) → production disruption (partial, escalating)
→ inventory buffer (revenue lags the halt; equity prices expected duration)
→ supplier order-flow pass-through (sharper but diversified, lagged) →
wage-cost settlement (the durable cost) → OEM margin pressure vs supplier
volume deleverage (suppliers get no offsetting wage savings).

## Interpretation limits

- Anticipated deadline (C4 partial anticipation) — 1d window may misplace
  the shock.
- Targeted plants limited day-one impact; inventory buffers distort 1d/5d.
- Supplier exposure is diversified across OEMs and platforms.
- Broad auto/consumer tape confounds the same-window comparison.
- Descriptive n=1 only — differences shown are not inference.

## How this deepens C2

C2 established the labor family and its goods-vs-media contrast. This packet
takes the goods case one level deeper: it converts "supplier legs exist" into
a gate-verified statement of what is readable now (GM, F — including their
contrast) and exactly what is missing for the supplier channel (pre-event
history), replacing an optimistic flag with a precise, costed gap.

## Non-claims

- Staged candidate 313 is not accepted evidence; denominators (94/86)
  unchanged; no promotion, no stage/hygiene change.
- No paid analysis run or approved; paid `/analyze` remains blocked.
- Descriptive n=1 readouts only — no CI, p-value, FDR, or significance; no
  family-level inference; not a recommendation of any kind.
- The closed Phase 1 / Phase 2 FDR pools are untouched.

## Final disposition

- **313 remains staged/no-paid.**
- The supplier read is **not** locally computable today; the bounded
  pre-event backfill for LEA/APTV is the natural no-paid follow-up if the
  labor family is expanded — it would require its own approval gate.
- The GM-vs-F intra-OEM contrast is usable no-paid evidence context now,
  under the partial-anticipation caveat.
- No paid analysis approved; no promotion authorized.
