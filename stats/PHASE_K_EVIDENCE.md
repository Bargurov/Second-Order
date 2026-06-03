# Phase-K single-event evidence note (corrected anchors, h1-only)

## 1. Purpose

This note records **descriptive single-event evidence** for the eight
source-anchored Phase-K events promoted to `curated_observation` (live event
ids 294–301). It is read off realized abnormal returns and reported as
evidence, never as a confirmed mechanism.

It makes **no** of the following claims:

- **No pooled-cohort claim.** Each event stands alone; nothing here is
  aggregated into a cohort statistic.
- **No FDR / significance claim.** The SAR figures below are descriptive
  standardized abnormal returns; they are not p-values and are not corrected
  for multiple testing.
- **No validated / contradicted *thesis* or *mechanism* claim.** Sign
  agreement with a pre-registered direction is reported as evidence, not as a
  confirmed (or refuted) mechanism.
- **No buy / sell or directional trading-signal framing.**

All reads are vs **SPY** (the production event-study benchmark). A
sector-relative benchmark sensitivity (XME/SMH/TAN/XLE) has not been run.

## 2. Denominator / funnel (kept visible)

| stage | count | detail |
|---|---|---|
| considered (both funnels) | **30** | 15 tariff (`phase_k_tariff_sourcing_funnel.yaml`) + 15 sanction (`phase_k_sanction_sourcing_funnel.yaml`) |
| `include_in_validation: true` | **11** | 6 tariff + 5 sanction |
| permanent provider / delisting dropouts | **3** | X×2 (`k-tar-01`, `k-tar-02`, US Steel) + ACIA (`k-san-01`, Acacia) — provider returns empty; **not replaced** |
| promoted / computable `curated_observation` | **8** | live ids 294–301 |
| excluded from corrected evidence | **1** | STLD (`k-tar-03`) — anchor date not source-pinned (see §4) |
| **readable corrected h1 events** | **7** | the table in §4 |

## 3. Anchor rule

The production event study measures forward **from the `event_date` close**,
so the anchor day's own move is excluded from h1. The correct anchor is
therefore:

> `event_date` = the **last trading session strictly before the first session
> that could price the announcement.**

The "first priceable session" is derived from the **source's announcement
time of day** (pre-market / intraday / after-close), **not** from where the
return landed. After-close announcements need no correction (the next session
is the first priceable one); intraday / pre-market announcements must anchor
to the prior close.

Corrected anchors are recorded here as **new, separately-counted evidence
entries** (`…b` labels), following the closed-ledger `cenx-apr6 → cenx-apr9`
precedent. The frozen funnel rows and the live `curated_observation` rows keep
their **original** anchors and are **not silently re-dated**.

## 4. Corrected h1 table

| candidate | ticker | family | exp. dir | original anchor | corrected anchor | h1 AR% | h1 SAR | agreement | caveat |
|---|---|---|---|---|---|---|---|---|---|
| k-tar-04 | WHR | tariff | + | 2018-01-22 | 2018-01-22 *(unchanged)* | **+2.99** | +3.10 | supports | after-close announce; verify no firm-specific Jan-23 news |
| k-san-04 | NVDA | sanction | − | 2022-08-31 | 2022-08-31 *(unchanged)* | **−7.98** | −3.15 | supports | after-close 8-K; h20 would catch the Sep-13-2022 CPI shock |
| k-tar-05b | NUE | tariff | + | 2018-03-01 | **2018-02-28** | **+4.71** | +3.40 | supports | original h1 was 0.00 (anchor artifact) |
| k-san-03b | PBF | sanction | − | 2019-01-28 | **2019-01-25** | **−1.92** | −0.93 | supports (modest) | small SAR; original h1 +0.66 was a contradict artifact |
| k-san-02b | QRVO | sanction | − | 2019-05-16 | **2019-05-15** | **−8.07** | −5.62 | supports | original h1 −5.49 understated the first-session move |
| k-tar-06b | FSLR | tariff | + | 2024-05-14 | **2024-05-13** | **−1.81** | −0.81 | **contradicts** | announcement leaked May-11–13; prior "+support" was contaminated (see §6) |
| k-san-05 | LRCX | sanction | − | 2020-12-18 | 2020-12-18 *(timing unpinned)* | +0.83 | +0.50 | contradicts (weak) | action heavily anticipated; timing not source-pinned |
| k-tar-03 | STLD | tariff | + | 2015-12-22 | **EXCLUDED** | — | — | excluded | 2015-12-22 matches **no** Commerce determination (CVD prelim 2015-11-06; AD prelim FR-published 2016-01-04) |

The anchor correction **cut both ways**: it rescued a real signal (NUE
0.00 → +4.71), flipped a contradiction artifact to support (PBF +0.66 →
−1.92), **and removed a false winner** (FSLR +1.41 → −1.81). It is not a
support-maximizing exercise.

## 5. Findings (descriptive — do **not** summarize as "validated")

- **Clean supports (h1 in the pre-registered direction, |SAR| ≳ 3):** WHR,
  NVDA, NUE, QRVO.
- **Modest support (direction agrees, small |SAR|):** PBF.
- **Contradiction:** FSLR — the clean h1 is negative against an expected
  positive; its earlier apparent support was a contamination artifact.
- **Weak / anticipated:** LRCX — small, wrong-sign, heavily anticipated,
  timing unpinned.
- **Excluded:** STLD — the anchor is not pinned to a real Commerce
  determination.

So of the **7 readable** events, **5 show an h1 abnormal move in their
pre-registered direction**, **1 contradicts**, **1 is weak/anticipated**.
This is descriptive single-event evidence only. It is **not** a validation,
and it is **not** separable into "mechanism vs direction" (see §7).

## 6. Contamination rules

- **h1 is the only horizon reported.** For this set the 5-day and 20-day
  windows reliably overlap earnings, sector macro shocks, or broad-market
  shocks (e.g. the Jan-2016 selloff, the Feb-2018 correction, the May-2019
  trade-war escalation, the Sep-2022 CPI shock, the late-2020 semis rally).
- **h5 / h20 must not be used for any evidence claim** in this note.
- **FSLR h5/h20 are explicitly rejected as contaminated.** FSLR's large
  positive 5- and 20-day moves were driven by the May-21–22-2024 non-tariff
  spike (analyst / AI-power demand narrative), not the §301 action; only the
  h1 read (−1.81%) is attributable, and it contradicts the expected direction.

## 7. Remaining blockers (why this is not a cohort)

- **The family / sign confound remains.** Every tariff event is
  expected-positive; every sanction event is expected-negative. The five
  "supports" are 2 tariff (+) and 3 sanction (−), so a pooled read cannot
  separate "the mechanism worked" from "tariffs rose / sanctioned-supplier
  names fell" as two one-sided phenomena.
- **Per-family counts are too small** for a single-family cohort (readable:
  tariff = WHR, NUE [FSLR contradicts]; sanction = NVDA, PBF, QRVO [LRCX
  weak]) — neither family reaches the ≥8 independent-shock floor.
- **A defensible pooled cohort requires** (a) a third, **crossed-sign**
  mechanism family (e.g. a positive-direction `supply_shock` set) to break the
  confound, and (b) a **new, self-contained FDR scope** for the cohort's
  `(cohort, horizon)` hypotheses — **never merged with, or compared against,
  the closed Phase 1 / Phase 2 evidence FDR pools.**

Until then, the honest surface is this per-event, h1-only, descriptive note.

---

*Sources:* `examples/phase_k_tariff_sourcing_funnel.yaml`,
`examples/phase_k_sanction_sourcing_funnel.yaml` (frozen funnels); live
`curated_observation` rows 294–301; `price_cache` backfilled in the K14 live
run (restore point `backups/pre_k14_phase_k_live_promotion_2026-06-04.db`).
Event-study reads via `event_study_validation.build_event_study_validation`
(vs SPY). Corrected-anchor reads were computed read-only on a DB copy; live
`events.db` was not mutated and no event row was re-dated.
