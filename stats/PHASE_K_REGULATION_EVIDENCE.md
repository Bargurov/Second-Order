# Phase-K regulation single-event evidence note (h1-only, copy-computed)

## 1. Purpose

This note records **descriptive single-event h1 evidence** for the Phase-K
**regulation** candidate family — the third crossed-sign mechanism family
sourced and timing-audited through
`examples/phase_k_regulation_sourcing_funnel.yaml`. It is read off realized
abnormal returns and reported as evidence, never as a confirmed mechanism.

- **Computed on a DB copy only.** Every figure below was produced on
  `backups/m17_regulation_backfill_copy.db` (an M17 throwaway copy backfilled
  from free yfinance). The live archive `events.db` was **not mutated** —
  verified byte-identical before and after M17
  (`e103724553783fdd74ef0fedbcc4cc7d7a0e32ddc559a29b03ca1129175adc89`). None
  of these regulation candidates is promoted into the live archive; they remain
  funnel includes.
- **This is not a pooled-cohort result.** Each event stands alone. Nothing here
  is aggregated into a cohort statistic, and the family/sign confound (§9) is
  not resolved by this note.

The event-study reads in §5 are vs **SPY** (the production event-study
benchmark). A read-only **sector-relative sensitivity** against each row's
funnel `benchmark_ticker` (a sector ETF) is reported in §6 as a descriptive
robustness check; it adds no new claim.

## 2. Explicit non-claims

This note makes **none** of the following claims:

- **No pooled-cohort claim.** n>1 here, but nothing is pooled; no cohort
  statistic is computed.
- **No FDR / significance claim.** The SAR figures are descriptive standardized
  abnormal returns; they are not p-values and are not corrected for multiple
  testing.
- **No validated / contradicted *mechanism* claim.** Sign agreement with a
  pre-registered direction is reported as evidence, not as a confirmed or
  refuted mechanism.
- **No buy / sell or directional trading-signal framing.**
- **No merge with the closed Phase 1 / Phase 2 FDR pools.** Those are a separate
  scope and are never mixed into this event-level surface.
- **No h5 / h20 support claim.** Only h1 is reported (see §4).
- **No track-record claim.** These rows do not enter any track-record or
  thesis-outcome denominator.

## 3. Denominator / funnel (kept visible)

| stage | count | detail |
|---|---|---|
| considered | **29** | full regulation sourcing funnel |
| `include_in_validation: true` | **15** | the rows read here |
| excluded | **14** | scope / sector / timing / macro-contamination excludes — kept visible in the funnel, never deleted |
| **h1 reads in §5** | **16** | the 15 includes, with **BFH counted twice** (two anchors) |

The 14 excluded rows stay in `phase_k_regulation_sourcing_funnel.yaml` with
their exclusion reasons; this note reads the **included** rows only and does not
re-litigate the excludes.

## 4. Anchor / horizon rule

- **h1 is the only horizon reported.** For this set the 5-day and 20-day windows
  reliably overlap earnings, sector-macro shocks, or broad-market shocks, so
  **h5 / h20 are not used as support** for any claim in this note.
- **`event_date` is the prior-close anchor.** Following the §3 convention used
  across Phase-K, `event_date` is the last trading session strictly before the
  first session that could price the announcement; intraday / after-close
  announcements anchor to the prior close. The production event study measures
  forward **from the `event_date` close**, so the anchor day's own move is
  excluded from h1.
- **BFH (`k-reg-04`) carries a two-anchor sensitivity** — the court action's
  priceable session is itself ambiguous, so both anchors are read separately:
  - `2024-05-09` → first priceable session `2024-05-10`
  - `2024-05-10` → first priceable session `2024-05-13`

## 5. Main h1 evidence table

Read **magnitude-stratified, per-event** — deliberately **not** as a
supports/contradicts tally. A bare count would weigh TMUS (SAR +12) the same as
GS (SAR −0.15) and would launder benchmark-fragile noise into a score. AR% is
the h1 abnormal return; SAR is the same return standardized by the 60-bar
estimation sigma. All 16 rows reached `event_study_available` on the
`(raw asset, raw benchmark)` basis (no mixed-basis caveat).

### A. Strong, name-specific supports — |SAR| ≥ 3 and surviving the sector benchmark

| candidate | ticker | regulatory action | exp. dir | SPY AR% (SAR) | sector AR% (SAR) |
|---|---|---|---|---|---|
| k-reg-26 | TMUS | court approves T-Mobile / Sprint merger (2020-02-10) | + | **+11.61** (+12.03) | +11.89 (+12.14) |
| k-reg-20 | LYV | DOJ sues Live Nation–Ticketmaster (2024-05-22) | − | **−7.08** (−4.26) | −6.68 (−3.78) |
| k-reg-16 | V | DOJ sues Visa over debit-network monopolization (2024-09-23) | − | **−5.78** (−5.16) | −4.84 (−4.03) |
| k-reg-18 | AAPL | DOJ sues Apple over smartphone monopolization (2024-03-20) | − | **−4.42** (−4.49) | −4.16 (−4.08) |

**TMUS has the largest AR (+11.6%);** lead on that. Its SAR (+12) is **inflated
by a compressed, pre-COVID low-volatility estimation window** — read it as
standardization, not as added signal.

### B. Modest supports — sign agrees, |SAR| ≈ 0.4–1.8

| candidate | ticker | regulatory action | exp. dir | SPY AR% (SAR) | caveat |
|---|---|---|---|---|---|
| k-reg-09 | JBLU | court blocks JetBlue–Spirit merger (2024-01-12) | + | +5.28 (+1.20) | large raw move, but JBLU is high-vol → modest SAR |
| k-reg-11 | BTU | EPA proposes to repeal the power-plant GHG rule (2025-06-10) | + | +2.73 (+0.72) | **CPI day**; sector leg weak (XLE +1.00 / +0.28) |
| k-reg-04 | BFH | court enjoins the CFPB late-fee rule — anchor 2024-05-10 | + | +1.98 (+0.75) | later anchor |
| k-reg-04 | BFH | same action — anchor 2024-05-09 | + | +0.94 (+0.36) | earlier anchor |

### C. Strong contradiction (as measured)

| candidate | ticker | regulatory action | exp. dir | SPY AR% (SAR) |
|---|---|---|---|---|
| k-reg-02 | JPM | Fed VC Barr signals a major softening of Basel "endgame" (2024-09-09) | + | **−5.62** (−4.71) |

Reported as a contradiction **as measured**. The session 2024-09-10 carried
same-day bank-specific news that a single-day h1 read cannot disentangle from
the regulatory signal; resolving that is **source-level intraday attribution,
not a validation-note call**. This caveat is stated symmetrically — it is **not**
used to neutralize or rescue the contradiction.

### D. Modest contradictions — wrong-signed, |SAR| < 1.5

| candidate | ticker | regulatory action | exp. dir | SPY AR% (SAR) | caveat |
|---|---|---|---|---|---|
| k-reg-06 | BTU | EPA finalizes the power-plant GHG rule (2024-04-24) | − | +2.43 (+1.45) | Q1-GDP / PCE day; rule heavily anticipated |
| k-reg-03 | SYF | CFPB finalizes the credit-card late-fee rule (2024-03-04) | − | +1.54 (+1.06) | rule long-telegraphed / largely priced |
| k-reg-05 | BMY | CMS names first 10 Medicare price-negotiation drugs (2023-08-28) | − | +0.52 (+0.44) | JOLTS day |
| k-reg-24 | BX | SEC adopts the private-fund-adviser rule (2023-08-22) | − | +0.35 (+0.25) | heavily contested / legally fragile rule facing immediate industry challenge — a muted issuer reaction is unsurprising |

### E. Inconclusive / benchmark-fragile — explicitly **not tallied** (|SAR| < 0.5)

| candidate | ticker | regulatory action | exp. dir | SPY AR% (SAR) | sector AR% (SAR) | why |
|---|---|---|---|---|---|---|
| k-reg-01 | GS | Fed/OCC/FDIC propose Basel III "Endgame" (2023-07-26) | − | −0.19 (−0.15) | +0.41 (+0.41) | **sign flips** by benchmark |
| k-reg-27 | WFC | Fed terminates the Wells Fargo $1.95T asset cap (2025-06-03) | + | −0.33 (−0.25) | +0.76 (+0.81) | **sign flips** by benchmark |
| k-reg-25 | PYPL | CFPB finalizes the larger-participant rule for digital wallets (2024-11-20) | − | −0.44 (−0.25) | −0.68 (−0.44) | sign-consistent but sub-noise magnitude |

## 6. Sector-relative h1 sensitivity

- **Available for all 16 rows.** Computed with the **same** event-study logic
  (`event_study_validation.build_event_study_validation`), changing only the
  benchmark from SPY to each row's funnel sector ETF.
- **h1 raw-return parity passed for every row** — the asset's own h1 return is
  identical across the SPY and sector legs, so the two legs differ only in the
  benchmark subtracted. This is the check that makes "the sector leg repeats the
  SPY leg's asset move exactly" a verified fact rather than an assertion.
- **The four strong supports (V, AAPL, LYV, TMUS) survive the sector
  benchmark** — each keeps a large same-signed abnormal move once sector beta is
  removed.
- **GS and WFC flip sign by benchmark** (negative vs SPY, positive vs sector
  ETF), which is precisely why they sit in the inconclusive bucket.
- The sector-relative leg is **descriptive only**. It removes sector beta, not
  the family/sign confound (§9), and adds no new claim.

## 7. Macro-cleanliness handling (one consistent bar)

The same skepticism is applied to supports and contradictions alike:

- **GS** — Q2-GDP / post-FOMC proximity; tiny and sign-flips by benchmark →
  **inconclusive**.
- **WFC** — ADP + ISM-Services print day; tiny and sign-flips by benchmark →
  **inconclusive**.
- **BTU `k-reg-11`** — CPI day; modest positive that is weak against XLE →
  **low-confidence support**.
- **BTU `k-reg-06`** — Q1-GDP / PCE day, and the rule was heavily anticipated →
  **low-confidence contradiction**.
- **BMY** — JOLTS day; tiny wrong-signed move → **low-confidence contradiction**.
- **AAPL** — post-FOMC day, **but the move survives strongly** (−4.42% vs SPY,
  −4.16% vs XLK): the bar is **not** softened because it genuinely survives both
  market and sector removal.
- **LYV** — hot-PMI day, **but survives strongly** (−7.08% vs SPY, −6.68% vs
  XLC): again not softened.
- **JPM** — contradiction **as measured**; the same-day-attribution caveat is
  stated (§5.C) but **not** used to neutralize it.

## 8. Legible observation (descriptive — not a class-level claim)

- The **four largest idiosyncratic h1 moves were all merger / antitrust-
  litigation events**: TMUS (merger approval, +11.6%) and V / AAPL / LYV (DOJ
  monopolization suits, −5.8% / −4.4% / −7.1%).
- The **financial / prudential / rulemaking events mostly cluster near zero or
  are wrong-signed** at h1.
- **Named exceptions stay visible** (the data resists the tidy version): BTU
  `k-reg-11` (EPA repeal) and PYPL `k-reg-25` (CFPB digital-wallet rule) are
  rulemaking-side *supports*, though weak / sub-noise; and JPM `k-reg-02` (Basel
  softening) is a rulemaking-side **strong contradiction**, not a weak one.
- This is an **observation reported per-event with its exceptions shown** — not
  a causal, class-level generalization, and not a cohort read.

## 9. What this enables / does not enable

- **Enables:** regulation is now a serious **third crossed-sign family
  candidate** — it carries both predicted-positive events (TMUS, JBLU, BFH,
  BTU-repeal, WFC) and predicted-negative events (the antitrust suits, the
  prudential / pricing rules), with strong reads on **both** signs (TMUS + and
  the antitrust − names). That crossed coverage is the structural ingredient
  that *could* later help break the tariff(+) / sanction(−) family/sign
  confound of `PHASE_K_EVIDENCE.md` §7.
- **Does not enable:** this note **does not** establish a pooled cohort. Any
  future pooled regulation / tariff / sanction cohort requires (a) a **new,
  self-contained FDR scope** for the cohort's `(cohort, horizon)` hypotheses —
  **never** merged with or compared against the closed Phase 1 / Phase 2 FDR
  pools — and (b) an explicit independence / design statement. Until that is
  built, the honest surface is this per-event, h1-only, descriptive note.

## 10. M19 decision (separate and optional)

- **Live promotion is optional and separate.** A later **M19** gate — not this
  note — would decide whether to promote any of the validated regulation
  observations into the live archive as `curated_observation` rows (with a live
  `price_cache` backfill), mirroring the K14 tariff/sanction promotion.
- **M19 must not happen automatically from this note.** This note is computed on
  a throwaway copy and changes nothing live; promotion is a deliberate,
  separately-authored decision with its own backup, hash-verification, and
  all-or-nothing guard.

---

*Sources:* `examples/phase_k_regulation_sourcing_funnel.yaml` (frozen funnel,
included rows only). Event-study reads via
`event_study_validation.build_event_study_validation` (vs SPY; sector leg with
`BENCHMARK_TICKER` swapped to the funnel ETF), computed read-only on
`backups/m17_regulation_backfill_copy.db` (M17 backfill, free yfinance,
`auto_adjust=False`). Live `events.db` was not mutated and no event row was
promoted or re-dated; copy integrity verified (0 duplicate / 0 conflicting
`(ticker, date, auto_adjust)` rows). h1-only; h5/h20 deliberately omitted as
contaminated.
