# J3 mechanism and transmission readout - the frozen graph adjudication (Mission J)

Contract: `j3-mechanism-readout-v1` under the locked j0-v1 constitution (sections 5, 6, 7, 12, 13). J3 is a readout layer over the published J1B and J2 surfaces; it computes no new statistic of any kind. Where an edge conclusion would require a new statistic, the edge is MEASUREMENT UNRESOLVED by construction.

## 1. Contract and provenance

- execution commit: `3d6a9af80a20854c88a43af5e952c5276711a125`
- executed at: 2026-07-10T17:23:47Z
- source reports (tracked, published, consumed read-only): `stats/J1B_FOMC_ROBUSTNESS_RESULTS.md`; `stats/J2_TIMING_COLLISION_RESULTS.md`
- no-new-statistics statement: J3 computed no response value, no median-of-percentiles estimand, no placement calibration, no event subset, no return, no beta, and no test quantity; every number below is quoted from a tracked published surface.
- graph manifest (frozen, J0 section 12): `fomc_decision -> policy_rates_repricing -> balance_sheet_sensitive_second_order -> broad_financial_sector`; panels N1 = 2Y_CMT (M2 primary) + SHY (M3); N2 = KRE (M3 primary) + IAT + KBE; N3 = XLF (M3 primary) + VFH; 2S10S_CMT is the contextual curve-shape layer (not a node); SPY is context/benchmark only.
- edge-state enumeration (frozen, exactly five): PROPAGATED; TRANSMISSION BREAK; UPSTREAM NOT ACTIVATED; DOWNSTREAM WITHOUT UPSTREAM; MEASUREMENT UNRESOLVED. No sixth state, no score, no probability, no edge ordering by strength.

## 2. Published evidence inputs (quoted verbatim, frozen order preserved)

### J1B 12-cell surface (window [t, t+1])

| # | measurement | lens | events avail/att | ref N | MEMP | calib pct | state | LOYO | LOEO |
|---|---|---|---|---|---|---|---|---|---|
| 1 | KRE | rolling_beta_ar | 64 / 65 | 1797 | 0.664719 | 0.998000 | ELEVATED | 0/8 | 0/64 |
| 2 | IAT | rolling_beta_ar | 64 / 65 | 1797 | 0.691987 | 1.000000 | ELEVATED | 0/8 | 0/64 |
| 3 | KBE | rolling_beta_ar | 64 / 65 | 1797 | 0.629382 | 0.983000 | ELEVATED | 0/8 | 0/64 |
| 4 | XLF | rolling_beta_ar | 64 / 65 | 1797 | 0.658319 | 0.996000 | ELEVATED | 0/8 | 0/64 |
| 5 | VFH | rolling_beta_ar | 64 / 65 | 1797 | 0.696717 | 0.999000 | ELEVATED | 0/8 | 0/64 |
| 6 | IAT | raw_return | 65 / 65 | 1816 | 0.655837 | 0.997000 | ELEVATED | 0/8 | 0/65 |
| 7 | KBE | raw_return | 65 / 65 | 1816 | 0.669604 | 0.999500 | ELEVATED | 0/8 | 0/65 |
| 8 | XLF | raw_return | 65 / 65 | 1816 | 0.645925 | 0.995500 | ELEVATED | 0/8 | 0/65 |
| 9 | VFH | raw_return | 65 / 65 | 1816 | 0.670705 | 0.999000 | ELEVATED | 0/8 | 0/65 |
| 10 | 2Y_CMT | raw_change | 65 / 65 | 1804 | 0.615576 | 0.981500 | ELEVATED | 0/8 | 0/65 |
| 11 | 2S10S_CMT | raw_change | 65 / 65 | 1804 | 0.652716 | 0.996000 | ELEVATED | 0/8 | 0/65 |
| 12 | SHY | raw_return | 65 / 65 | 1816 | 0.579295 | 0.934000 | ELEVATED | 0/8 | 0/65 |

### J2 state-bearing timing surface (window [-5, -1])

| # | metric | events avail/att | ref N | MEMP | calib pct | state | LOYO | LOEO |
|---|---|---|---|---|---|---|---|---|
| 13 | raw_return | 65 / 65 | 1427 | 0.491240 | 0.424500 | ORDINARY_UNRESOLVED | 4/8 | 32/65 |
| 14 | spy_relative_ar | 65 / 65 | 1427 | 0.537491 | 0.716500 | ORDINARY_UNRESOLVED | 1/8 | 0/65 |
| 15 | sector_relative_ar | 65 / 65 | 1427 | 0.609671 | 0.970000 | ELEVATED | 0/8 | 0/65 |
| 16 | sar | 65 / 65 | 1427 | 0.572530 | 0.889000 | ELEVATED | 0/8 | 0/65 |

MEMPs from different windows, references, or availability sets are not value-comparable and are never merged; the cells appear in frozen order.

### Collision facts and denominators

- exact [t, t+1] collision register: C2 `opec-known-date-exclusion-register@i0-v1` (41 calendar dates) tags 0 of 65 events; the C1 BLS CPI / Employment Situation branch is unadjudicable in the published execution (no source-pinned era register); FOMC self-collision invariant holds (minimum anchor spacing 8). The collision-free sensitivity over the adjudicable registers is the full frame (N = 65) and reproduces the published J1B surface vacuously. Events are described as outside known-register collisions only; no stronger clean-window claim exists. Collision status qualifies the readout and neither creates nor removes an edge state.
- denominators: rolling-beta cells 64 / 65 events, reference 1797; raw-return cells 65 / 65, reference 1816; Treasury raw-change cells 65 / 65, reference 1804; J2 timing cells 65 / 65, reference 1427.

## 3. Node readout

### N0 `fomc_decision`

- event trigger; not measured; activation definitional (the decision occurred).
- node reading: **ACTIVATED**
- rule path: activation definitional: all 65 frame-complete decisions occurred (J0 section 12.1); event occurrence only, no market claim
- limitation: event trigger; activation definitional (the decision occurred); no market claim

### N1 `policy_rates_repricing`

- panel: 2Y_CMT (primary, M2): ELEVATED, SHY (M3): ELEVATED
- measurement class of primary: M2
- role modifier (published): **BROAD MEASUREMENT CONSISTENCY**
- node reading: **ACTIVATED**
- rule path: usable M2 primary at State A stands alone -> ACTIVATED (J0 section 5)
- limitation: measurement-limited: the ideal M1 policy-repricing measure (fed funds futures / OIS) is unavailable; the 2Y CMT blends policy expectations with term premium (J0 section 8)

### N2 `balance_sheet_sensitive_second_order`

- panel: KRE (primary, M3): ELEVATED, IAT (M3): ELEVATED, KBE (M3): ELEVATED
- measurement class of primary: M3
- role modifier (published): **BROAD MEASUREMENT CONSISTENCY**
- node reading: **ACTIVATED**
- rule path: M3 primary at State A with role BROAD MEASUREMENT CONSISTENCY (>= ROLE-CONSISTENT) -> ACTIVATED (J0 section 5 corroboration rule)
- limitation: equity-proxy limits (fund mechanics); single-proxy results stay asset-specific

### N3 `broad_financial_sector`

- panel: XLF (primary, M3): ELEVATED, VFH (M3): ELEVATED
- measurement class of primary: M3
- role modifier (published): **BROAD MEASUREMENT CONSISTENCY**
- node reading: **ACTIVATED**
- rule path: M3 primary at State A with role BROAD MEASUREMENT CONSISTENCY (>= ROLE-CONSISTENT) -> ACTIVATED (J0 section 5 corroboration rule)
- limitation: sector ETFs are cap-weighted composites; not a statement about every financial firm

## 4. Edge readout (ordered precedence, J0 section 5)

### E1 `fomc_decision` -> `policy_rates_repricing`

- upstream reading: ACTIVATED (upstream activation definitional (all 65 anchors exist); UPSTREAM NOT ACTIVATED and DOWNSTREAM WITHOUT UPSTREAM structurally unreachable on E1 (J0 section 12.3))
- downstream primary state: ELEVATED (M2); role modifier BROAD MEASUREMENT CONSISTENCY; Route B satisfied: False
- final edge state: **PROPAGATED**
- exact precedence path: precedence step 3: upstream ACTIVATED and downstream supports the ELEVATED edge claim (usable M1/M2 primary stands alone (Route A)) -> PROPAGATED (J0 section 5)

### E2 `policy_rates_repricing` -> `balance_sheet_sensitive_second_order`

- upstream reading: ACTIVATED (usable M2 primary at State A stands alone -> ACTIVATED (J0 section 5))
- downstream primary state: ELEVATED (M3); role modifier BROAD MEASUREMENT CONSISTENCY; Route B satisfied: False
- final edge state: **PROPAGATED**
- exact precedence path: precedence step 3: upstream ACTIVATED and downstream supports the ELEVATED edge claim (M3 primary with role BROAD MEASUREMENT CONSISTENCY (>= ROLE-CONSISTENT)) -> PROPAGATED (J0 section 5)

### E3 `balance_sheet_sensitive_second_order` -> `broad_financial_sector`

- upstream reading: ACTIVATED (M3 primary at State A with role BROAD MEASUREMENT CONSISTENCY (>= ROLE-CONSISTENT) -> ACTIVATED (J0 section 5 corroboration rule))
- downstream primary state: ELEVATED (M3); role modifier BROAD MEASUREMENT CONSISTENCY; Route B satisfied: False
- final edge state: **PROPAGATED**
- exact precedence path: precedence step 3: upstream ACTIVATED and downstream supports the ELEVATED edge claim (M3 primary with role BROAD MEASUREMENT CONSISTENCY (>= ROLE-CONSISTENT)) -> PROPAGATED (J0 section 5)

## 5. Timing qualification (carried, never rewriting states)

- timing evidence is lens-dependent under daily measurement — published J2 [-5, -1] pre-event states: raw_return ORDINARY_UNRESOLVED; spy_relative_ar ORDINARY_UNRESOLVED; sector_relative_ar ELEVATED; sar ELEVATED. The J0 section-15 withdrawal condition for the 1d concentration claim was not triggered (tracked J2 section 7). Timing qualifies temporal interpretation only; it rewrites no J1B node state and no edge state.
- published fragility carried: the J2 raw_return pre-event cell is knife-edge (LOYO 4/8, LOEO 32/65); the J1B post-anchor surface carried 0 overlay flips.
- daily close-to-close data cannot resolve intraday repricing; the 2 p.m. ET statement release sits before the anchor-session close, so part of the same-session reaction is outside every daily window.

## 6. Collision qualification (carried, never rewriting states)

- exact [t, t+1] collision register: C2 `opec-known-date-exclusion-register@i0-v1` (41 calendar dates) tags 0 of 65 events; the C1 BLS CPI / Employment Situation branch is unadjudicable in the published execution (no source-pinned era register); FOMC self-collision invariant holds (minimum anchor spacing 8). The collision-free sensitivity over the adjudicable registers is the full frame (N = 65) and reproduces the published J1B surface vacuously. Events are described as outside known-register collisions only; no stronger clean-window claim exists. Collision status qualifies the readout and neither creates nor removes an edge state.

## 7. What the graph readout supports

- Every frozen edge reads **PROPAGATED under the frozen measurement rules**: the frozen upstream and downstream roles show aligned elevated-response states on the published [t, t+1] surface (E1, E2, E3).
- Every measured role carries **BROAD MEASUREMENT CONSISTENCY**: no reading rests on a single proxy.
- Claim-ladder ceiling (J0 section 14, tier 5): a **mechanism-consistent descriptive pattern** - the predeclared linked roles satisfy the frozen state rules with sufficient measurement adjudicability and no proxy substitution. This is a descriptive alignment, not proof of transmission, and it is never phrased as a confirmed mechanism.
- The rates-role reading and therefore E1 and E2 are **measurement-limited** (J0 section 8): the ideal M1 repricing measure is unavailable, and the 2Y CMT blends policy expectations with term premium; this limitation travels with every affected statement.
- All of it is same-sample Class B evidence: post-outcome robustness under prospectively frozen new tests, never independent historical confirmation.

## 8. Where transmission remains unresolved

- The ideal M1 policy-repricing measure (fed funds futures / OIS) is unavailable in the frozen substrate; the rates-role reading rests on an M2 official series plus an M3 investable proxy and stays measurement-limited.
- Temporal placement is unresolved at daily resolution: timing evidence is lens-dependent under daily measurement (section 5); the graph adjudicates response-magnitude alignment, not sequencing.
- The C1 BLS CPI / Employment Situation collision branch is unadjudicable in the published execution; freedom from those releases is not certified for any event window.
- The three panels and two windows are correlated same-sample views over overlapping events, assets, and reference structures - not independent replications.
- No panel produced MEASUREMENT DISAGREEMENT on the published surface; had one occurred, the affected role would carry no single reading and its edges would be MEASUREMENT UNRESOLVED.

## 9. What J3 does not establish

- causality (edge states are descriptive alignments under frozen measurement rules, never proof of transmission);
- prediction;
- tradeability;
- alpha;
- independent historical confirmation of Mission I, J1B, or J2;
- permanent price impact;
- intraday sequencing (daily data cannot resolve it);
- a structural macro model;
- mechanism proof beyond the frozen descriptive graph adjudication (tier-5 ceiling, J0 section 14);
- any hypothesis-test conclusion (calibration percentiles are placement positions, not test outcomes).
