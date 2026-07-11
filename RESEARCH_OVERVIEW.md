# Second Order Research Overview

This is the finance-reviewer front door for Second Order's current research record. It summarizes what the workbench does, how the evidence lanes are separated, what Mission G found, and where the durable proof artifacts live.

## 1. What Second Order Is

Second Order is an event-driven quant-finance research workbench and portfolio piece for geopolitical, macro, and policy headlines. Its maintained research chain is:

`event -> mechanism -> affected assets -> 1d/5d/20d reaction -> abnormal/event-study readout -> falsifier/limits -> ordinary-period comparison -> robustness -> archive evidence -> representative cases`

The point is to make each dated event legible as evidence: what changed, what transmission channel was hypothesized, which assets were exposed, how those assets actually moved, and which limits or counter-readings remain visible.

It is not a buy/sell tool, not a forecasting system, not a claim of single-event significance, and not a live-trading product. The event-study layer describes realized event-window behavior; it does not establish that one event proves a mechanism or that a future event should behave the same way.

## 2. Research Architecture

The project keeps evidence lanes visible because each lane has a different denominator:

- Existing live track record: 86 accepted archive rows, preserved as its own live-track-record denominator.
- Frame-complete FOMC historical lane: 65 Federal Reserve monetary-policy decisions from 2018-2025, enumerated as a bounded official frame.
- Designed-contrast OPEC lane: 32 source-pinned reservoir-ready OPEC/OPEC+ production-policy identities, recruited under a separate designed-contrast rule.
- Representative cases: illustrations only, with no denominator of their own.

The denominator separation is central. The live archive, the complete FOMC frame, and the OPEC designed reservoir answer different research questions and are not pooled into one general market-event result. Representative cases help a reader inspect the machinery but never substitute for a lane-level count.

The live track-record lane is read through two named outcome lenses that stay separate: the **Any-support OR-rule** ledger (`db.compute_track_record` — one supporting directional name is enough for the any-supporting bucket) and the **directional-majority** ledger (`validation_status_v2` — supporting vs contradicting names, with ties counting as contradicted under the frozen current rule). Both ledgers are descriptive archive accounting; the boundary on what they do and do not establish lives in the claims section below. The event-level rule behind `validation_status_v2` was audited read-only in [`stats/VALIDATION_STATUS_CALIBRATION.md`](stats/VALIDATION_STATUS_CALIBRATION.md) — a dated pre-recovery snapshot (65 decisive labels at its as-of date). The current post-recovery ledger carries 73 decisive labels after the 2026-07-11 directional-evidence recovery; the calibration's KEEP_CURRENT_RULE conclusion is unchanged and no production rule changed.

## 3. Event-Study Layer

The shipped event-study hierarchy uses four response lenses:

1. Absolute asset return.
2. SPY-relative abnormal return.
3. Sector-relative abnormal return, where the sector benchmark is eligible.
4. SAR, the standardized abnormal return.

Each lens is read at 1d, 5d, and 20d horizons. The canonical basis is adjusted/adjusted when available. Raw/raw fallback is allowed only when required by data availability, and a cross-basis readout is never treated as canonical. The point of the hierarchy is to keep raw movement, market movement, sector movement, and volatility-scaled movement separate rather than forcing them into one headline number.

## 4. Mission G Chain

Mission G was built as an outcome-blind historical evidence chain:

1. Protocol lock.
2. Independent historical universes.
3. Point-in-time state construction.
4. Mechanical eligibility.
5. Outcome-blind structural freeze.
6. Separate-ledger promotion.
7. Complete frozen-manifest readout.
8. Uniform stability diagnostics.
9. Outcome-independent representative cases.

The order matters. The universes, state axes, eligibility gates, comparison menu, and ledger promotion were frozen before historical outcome values were inspected. The readout then executed the frozen menu rather than choosing comparisons after seeing which ones looked favorable.

## 5. Point-In-Time State

The primary state vector is continuous and point-in-time:

- Fed path.
- VIX level/trailing percentile.
- SPY distance from the 200-day moving average.
- 2s10s yield curve.

These four dimensions are available for all 97 historical Mission G candidates. Continuous values are canonical; categorical tags are secondary reader aids.

HY OAS is handled separately. It is available for 36/97 candidates, bounded by the source era, and is therefore secondary-only. It is not a cross-period primary state vector, and no proxy was substituted for the missing history.

## 6. Main Empirical Result

The lead result is a null. The broad state-conditioning surface is predominantly flat, fragile, or contradictory. Across the 120 continuous associations in the stability pass, 44/120 changed sign under leave-one-event-out and 76/120 changed sign under leave-one-year-out. The frame-complete FOMC lane is broadly flat, with no general regime effect under the frozen manifest.

There is one bounded exception: in the OPEC designed-contrast lane, Fed path x sector-relative reaction remained negative across 1d, 5d, and 20d and survived the uniform leave-one-event-out and leave-one-year-out sign checks. The correct description is: stable descriptive association with unresolved calendar-time confounding.

That phrase is deliberately narrow. It does not claim prediction, causality, single-event significance, or a general market rule.

## 7. Credit Result

The OPEC credit subset has N=16. It is era-bounded, secondary-only, and mostly fragile under the same stability discipline. Credit coverage is useful as a constrained descriptive slice of the period where HY OAS exists, but it was not promoted to a primary cross-period state dimension after outcomes were visible. That restraint is part of the result.

## 8. Representative Cases

The representative-case artifact is [`stats/G6C_REPRESENTATIVE_CASES.md`](stats/G6C_REPRESENTATIVE_CASES.md). It contains six state-anchored cases selected by three roles: the OPEC Fed-path association, the fragile OPEC credit subset, and the broad-null FOMC lane. Each role takes Q25 and Q75 state anchors; the selected case is the nearest event to the anchor, with deterministic tiebreaks by event date and candidate id. Outcome magnitude is never used.

Three compact examples show why the cases are illustrations rather than proof:

- `opec-2024-03-03-q2-extension`: a large raw 20d move collapses after the sector benchmark, showing why the response hierarchy matters.
- `opec-2023-11-30-voluntary-2p2`: after the first day, the traded outcome runs opposite the announcement's face-value direction across the market, sector, and volatility-scaled lenses.
- `fomc-policy-decision-2019-09-18`: a quiet FOMC case where the response is small and mixed, illustrating the broad flatness of the FOMC lane.

The cases are useful because they make the statistics inspectable at the dossier level. They are not evidence that the selected event is typical, decisive, or independently probative.

## 9. What Failed And Why It Matters

Several attempted research paths failed or narrowed:

- Broad regime conditioning did not survive as a stable general surface.
- Mechanism-label comparability failed across source registers and input surfaces, so mechanism labels were not used as a cross-cohort Mission G conditioning axis.
- Credit coverage was not adequate for a primary cross-period vector.
- Many associations changed sign under uniform stability diagnostics.

Those failures matter because they are visible outcomes, not discarded work. They define the claim boundary and make the surviving descriptive statement narrower and more honest.

## 10. Reproducibility Evidence Trail

Key artifacts, in audit order:

- Protocol and ledger rules: [`stats/G_RESEARCH_PROTOCOL.md`](stats/G_RESEARCH_PROTOCOL.md).
- Event-study standardization: [`stats/G_STANDARDIZATION_SPEC.md`](stats/G_STANDARDIZATION_SPEC.md).
- FOMC frame inventory: [`stats/G1A_FOMC_FRAME_INVENTORY.md`](stats/G1A_FOMC_FRAME_INVENTORY.md).
- OPEC designed reservoir: [`stats/G1B_OPEC_DESIGNED_RESERVOIR.md`](stats/G1B_OPEC_DESIGNED_RESERVOIR.md).
- State-source readiness: [`stats/G2_STATE_SOURCE_READINESS.md`](stats/G2_STATE_SOURCE_READINESS.md).
- Mechanical eligibility: [`stats/G3_MECHANICAL_ELIGIBILITY.md`](stats/G3_MECHANICAL_ELIGIBILITY.md).
- Structural freeze: [`stats/G4_STRUCTURAL_FREEZE.md`](stats/G4_STRUCTURAL_FREEZE.md).
- Promotion proof: [`stats/G5_PROMOTION_PROOF.md`](stats/G5_PROMOTION_PROOF.md).
- Frozen-manifest readout: [`stats/G6_FROZEN_MANIFEST_READOUT.md`](stats/G6_FROZEN_MANIFEST_READOUT.md).
- Stability and falsifiers: [`stats/G6B_STABILITY_AND_FALSIFIERS.md`](stats/G6B_STABILITY_AND_FALSIFIERS.md).
- Representative cases: [`stats/G6C_REPRESENTATIVE_CASES.md`](stats/G6C_REPRESENTATIVE_CASES.md).

Together these artifacts let a reviewer reconstruct the bounded historical universes, state substrate, eligibility gate, frozen comparison set, readout, stability checks, and case-selection rule without relying on market memory or presentation copy.

## 11. Claims And Non-Claims

Second Order currently claims that its research workflow can preserve event identity, denominator separation, point-in-time state, and event-study readouts in an auditable local workbench. The main Mission G empirical result is a broad null, plus the bounded OPEC phrase above and a constrained secondary credit result.

It does not claim a tradable rule, a general market regime model, a causal statement, a future-return forecast, or single-event statistical significance. Representative cases remain illustrations. The durable contribution is the disciplined research record: what held, what failed, and where the limits are visible.

## 12. Mission I: Ordinary-Period Baseline

Mission I is a separate, self-contained research section that asks one question: are completed FOMC and OPEC event windows unusual relative to eligible *ordinary* periods on the same frozen assets and response metrics? It runs its own frozen chain — protocol, candidate universe, symmetric response substrate, a closed 20-cell magnitude-percentile family, a 2,000-placement era-matched calibration, and a six-part falsifier battery — with no p-values and no new FDR pool.

The answer is structural, not a yes/no. Event exceptionalism is family-, horizon-, and metric-specific. FOMC decision windows show a broad, perturbation-stable elevation in one-day response magnitude across all four metrics; that coherence weakens by 5d, where the raw-return cell is a near-0.5 knife-edge. OPEC is mixed at 1d and 5d and uniformly below ordinary response magnitude at 20d, but with limited cross-horizon consistency. Across the surface, no primary cell's direction depends on the overlap-decimation reference swap (F3 0/20), and leave-out fragility is concentrated in the single near-0.5 FOMC 5d raw cell. Mission I rejects the *blanket* descriptive idea that event windows are generally more extreme than ordinary periods — a statement about the broad narrative, not a formal hypothesis test.

The interpretation, full stability synthesis, and permanent non-claims are in the closeout: [`stats/MISSION_I_CLOSEOUT.md`](stats/MISSION_I_CLOSEOUT.md). Its frozen evidence chain is the I0 protocol ([`stats/I0_ORDINARY_PERIOD_BASELINE_PROTOCOL.md`](stats/I0_ORDINARY_PERIOD_BASELINE_PROTOCOL.md)), the candidate universe ([`stats/I1_ORDINARY_PERIOD_CANDIDATE_UNIVERSE.md`](stats/I1_ORDINARY_PERIOD_CANDIDATE_UNIVERSE.md)), the response substrate ([`stats/I2A_RESPONSE_SUBSTRATE.md`](stats/I2A_RESPONSE_SUBSTRATE.md)), the frozen MEMP family ([`stats/I2B_MEMP_PRIMARY_COMPARISON.md`](stats/I2B_MEMP_PRIMARY_COMPARISON.md)), the placement calibration ([`stats/I2C_CALIBRATION.md`](stats/I2C_CALIBRATION.md)), and the F1–F6 falsifiers ([`stats/I2C_FALSIFIERS.md`](stats/I2C_FALSIFIERS.md)). Like Mission G, it is descriptive research: no causality, prediction, tradeability, or single-event significance.

## 13. Mission J: Hindsight-Controlled FOMC Robustness

Mission J is a separate, self-contained research section that takes the one place Mission I found a broad, perturbation-stable elevation — the FOMC one-day response — and asks a single frozen question: does that inherited reading survive asset and benchmark substitution, pre-event timing, and exact-window event collisions, and how far does it carry across a pre-declared transmission graph? It runs its own frozen chain over a 65-event FOMC frame (2018–2025): a locked constitution (J0), a frozen data substrate (J1A), an asset/benchmark challenge (J1B), a timing and exact-window collision challenge (J2), and a mechanism/transmission readout (J3). No Mission J outcome value existed before each stage ran, and no number is merged with the Mission G or Mission I ledgers.

**J1B — asset/benchmark challenge.** On the frozen 12-cell surface, all twelve cells are ELEVATED, and all three measured panels — policy-rates repricing, balance-sheet-sensitive second-order, and broad financial sector — carry BROAD MEASUREMENT CONSISTENCY. The elevation is neither KRE-specific nor an artifact of the inherited beta=1 benchmark: it holds under a frozen 252/20 market model and across regional-bank, broad-sector, and rates proxies. These twelve cells are correlated robustness views over overlapping events, assets, benchmarks, and reference structures — not independent replications. Full surface: [`stats/J1B_FOMC_ROBUSTNESS_RESULTS.md`](stats/J1B_FOMC_ROBUSTNESS_RESULTS.md).

**J2 — timing and collision challenge.** On the pre-event [-5, -1] window, the raw-return and SPY-relative cells read ORDINARY / UNRESOLVED while the sector-relative and SAR cells read ELEVATED. Timing evidence is lens-dependent under daily measurement. The frozen J0 withdrawal condition for a primarily pre-event interpretation was not triggered; nevertheless, the sector-relative and SAR lenses remained ELEVATED in the pre-event window. The raw-return pre-event cell is knife-edge under the published leave-one-out overlays. On exact [t, t+1] collisions, the C2 OPEC known-date register tags 0 of 65 events, and the C1 BLS CPI / Employment Situation branch remains unadjudicable in the published execution — the repository carries no source-pinned release register for the frozen era, so events are described as outside known-register collisions only. Full surface: [`stats/J2_TIMING_COLLISION_RESULTS.md`](stats/J2_TIMING_COLLISION_RESULTS.md).

**J3 — mechanism/transmission readout.** Over the pre-declared transmission graph, edges E1 (decision → policy-rates repricing), E2 (policy-rates repricing → balance-sheet-sensitive second-order), and E3 (balance-sheet-sensitive second-order → broad financial sector) are each PROPAGATED under the frozen measurement rules — a mechanism-consistent descriptive pattern at the tier-5 claim ceiling. E3 is a breadth/specificity ordering across financial-sector roles, not causal sequencing; the graph adjudicates response-magnitude alignment, not timing. Full surface: [`stats/J3_MECHANISM_TRANSMISSION_READOUT.md`](stats/J3_MECHANISM_TRANSMISSION_READOUT.md).

Measurement limitations travel with every affected statement. The ideal M1 policy-path measure (fed funds futures / OIS) is unavailable in the frozen substrate; the rates role rests on the 2Y CMT, which is measurement-limited because it blends policy expectations with term premium. All of Mission J is same-sample Class B evidence: post-outcome robustness under prospectively frozen new tests.

Mission J makes no claim of causality, prediction, tradeability, alpha, independent historical confirmation, intraday sequencing, or structural macro-model proof. Like Mission G and Mission I, it is descriptive research: what survived the frozen challenge, what stayed lens-dependent or unadjudicable, and where the measurement limits are visible.
