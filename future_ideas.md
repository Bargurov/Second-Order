# Master Algorithmic Roadmap — Second Order

## What I'm cutting and why

Before the roadmap, here's what gets removed from your list. Not because the math is wrong, but because the implementation cost-to-edge ratio is bad given your current state.

**Discarded:**

- **Bayesian online change-point detection** — Run-length posteriors are elegant but you'll spend three weeks tuning hazard functions for a regime classifier that an HMM does better with less code. Cut.
- **Kalman-filter latent impulse extraction** — The "latent impulse + noise" framing is a textbook example, not a product feature. You can't show an interviewer a Kalman state and have it mean anything. Cut.
- **Functional reaction-shape classification (fPCA)** — Standard PCA on aligned vectors gives you 90% of the insight at 10% of the complexity. fPCA itself is cut; standard PCA stays.
- **Cross-asset causal graph with sign restrictions** — Causal graphs without instrumental variables or natural experiments are vibes-based science. Sign restrictions help, but the output won't survive a quant interview's first probing question. Cut until you have natural-experiment data.
- **Stop-run vs true repricing classifier** — Real value, but requires intraday tick data you don't have. Cut until data exists.
- **Auction-quality classifier** — Same problem. Requires intraday OHLCV at minute granularity across your entire archive. Cut for now.
- **Order-flow imbalance proxy without tick data** — Approximating signed pressure from daily bars is statistical fan-fiction. Either get the data or skip it. Cut.
- **Volume-profile displacement / liquidity-gap detectors** — Same data dependency. Cut.

**Demoted (keep on roadmap but not Phase 1):**

- DCC-GARCH / Diebold-Yilmaz spillover
- Empirical Bayes shrinkage by mechanism family
- Survival models for time-to-peak
- Synthetic-control validation
- HDBSCAN analogue clustering

These are all good ideas. They're just not the next things.

---

## The Core Insight Driving Sequencing

Your product's defensible edge is **second-order mechanism extraction validated by market reaction**. Everything in the roadmap should serve that one claim. The question an interviewer will ask is: *"You said this event would tighten financial conditions through dollar funding stress — how do you know the market actually agreed?"*

Your current answer is "we computed return_5d and called it validated." That's not enough. The roadmap below is what makes that answer rigorous.

The sequencing principle: **abnormal returns first, regimes second, transmission third, microstructure last.**

---

## Phase 1 — Make Validation Statistically Honest (Weeks 1-3)

These are non-negotiable. Without them, every downstream feature is built on a foundation of noise.

### 1.1 Volatility-normalized abnormal return (CAR/CAAR framework)

This is the single highest-leverage upgrade in your entire list. Currently your `return_5d` is raw return. That's wrong because a 2% move in NVDA is noise and a 2% move in XLU is a major event.

**Implementation:**
```
abnormal_return[t] = asset_return[t] - alpha - beta * benchmark_return[t]
standardized_abnormal_return = abnormal_return / sigma_local
```

Where `sigma_local` is realized volatility from a 60-day pre-event window, and beta is estimated from the same window. Use a market-model regression with SPY for equities, sector ETF as a secondary benchmark.

**Why this matters for your product:** Your `validation_status` becomes statistically meaningful. "Validated" now means "post-event SAR exceeded 2 standard deviations" instead of "return was positive and we hoped." This is the language of event studies in academic finance and on the buy-side.

**Library:** `numpy`, `pandas`, `statsmodels.regression.linear_model.OLS` for beta estimation.

### 1.2 Multiple-testing correction across tickers and horizons

You evaluate many tickers across many horizons per event. Without FDR control, you will manufacture false positives.

**Implementation:** Benjamini-Hochberg q-values across all (ticker, horizon) tests within an event. Use `statsmodels.stats.multitest.multipletests(pvals, method='fdr_bh')`.

**Why this matters:** Without it, your "validated" rate is artificially high and you have no defense against the obvious interviewer question: "isn't this just multiple-comparisons noise?"

### 1.3 Bootstrap confidence intervals for reaction profiles

Your reaction profile currently reports point estimates: peak_move_20d = 3.4%. That number is meaningless without uncertainty.

**Implementation:** Stationary block bootstrap (block length ~5-10 days to preserve autocorrelation) on event-relative SAR paths, grouped by mechanism family. 1000 resamples per group. Report 5th/50th/95th percentile.

**Library:** `arch.bootstrap.StationaryBootstrap` is the standard choice. 50 lines of code.

**Output:** Every reaction profile metric gets a CI. "Mean peak move for tariff events: 2.1% [0.8%, 3.7%]" is a vastly stronger claim than "2.1%."

### 1.4 Adaptive signal-to-noise score for ranking

Your current candidate ranking uses source count and rank weights. Replace it with:

```
SNR = |abnormal_return| / (realized_vol * liquidity_penalty * crowding_penalty)
```

Where:
- `realized_vol` is local volatility
- `liquidity_penalty` accounts for thin tape (use bid-ask proxy or volume z-score)
- `crowding_penalty` is event-window cross-asset correlation

**Why this matters:** Movers ranked by SNR will surface genuine signal, not just headlines that happened during low-vol periods.

---

## Phase 2 — Regime Conditioning (Weeks 4-5)

Reaction profiles unconditional on regime are misleading. A tariff announcement in a risk-on regime behaves differently than the same announcement during a liquidity crisis.

### 2.1 Hidden Markov regime layer

Implement first with 3-4 states, not 5+. More states means less data per state means worse estimates.

**Recommended states:** risk-on, inflation-shock, growth-scare, liquidity-stress.

**Emissions vector:** SPY return, 10Y yield change, HY-IG credit spread change, VIX level, DXY return. Five-dimensional Gaussian emissions.

**Library:** `hmmlearn.GaussianHMM`. Fit on 5+ years of daily data. Use Viterbi for state assignment, posterior probabilities for soft conditioning.

**Output:** Every event gets a regime label (or posterior distribution). Reaction profiles get computed conditional on regime.

**Why this matters:** Your Track Record card becomes "validated rate by regime" — a serious quant artifact.

### 2.2 Policy reaction-function module

This is where you get genuine macro edge that no generic news tool has.

**Build a Taylor-rule-style index:**
```
policy_constraint = w1 * inflation_gap + w2 * labor_gap + w3 * real_rate_impulse
                  + w4 * fci_index + w5 * fx_pressure + w6 * credit_stress
```

Start with equal weights and FRED data. Inflation gap from Core PCE vs target. Labor gap from unemployment vs NAIRU proxy. Real rate from 10Y TIPS. FCI from Chicago Fed NFCI. FX from broad dollar index.

**Output:** A scalar measuring how constrained the central bank is. Events that occur when this index is high (Fed boxed in) have systematically different reaction profiles than events when it's low.

**Why this is the macro edge:** When you tell an interviewer "we model the Fed's constraint set and condition reaction profiles on it," that's senior buy-side language.

### 2.3 Macro surprise decomposition

For events affecting major macro releases (CPI, NFP, FOMC), decompose the cross-asset reaction into:
- Growth shock (equities up, yields up, dollar up)
- Inflation shock (equities down, yields up, dollar mixed, gold up)
- Liquidity shock (equities down, yields down, dollar up, credit wider)
- Sovereign shock (equities down, yields up, dollar down, gold up)

Start rule-based with sign-pattern matching across SPY/10Y/DXY/Gold/HY. Upgrade later to a sign-restricted factor model.

---

## Phase 3 — Causal Inference for Validation (Weeks 6-7)

This is where you separate "the market moved after the headline" from "the headline caused the market to move."

### 3.1 Synthetic-control validation

For each affected ticker in a validated event, construct a synthetic control from sector peers / control ETFs using pre-event window weights.

**Implementation:**
```
synthetic_path = ridge_regression(target_pre_event ~ control_basket_pre_event)
abnormal_path = actual_post_event - predict(synthetic_path, post_event)
```

Use a 60-90 day pre-event window. Constrain weights to sum to 1 if you want classical synthetic control; use ridge if you want stability.

**Why this matters:** This is the cleanest way to isolate event-specific reaction from market drift. Every quant will recognize this technique. It's used in Card-Krueger style policy evaluation and increasingly in quant equity research.

### 3.2 Jump detection for event impulse

Use bipower variation as the practical implementation (Lee-Mykland is more rigorous but needs intraday data you don't have).

```
RV = sum(squared_returns)
BV = (pi/2) * sum(|return_t| * |return_{t-1}|)
jump_component = max(RV - BV, 0)
```

Compute on event day. Compare to local distribution.

**Output:** Binary jump flag + jump magnitude. Distinguishes "the market gradually digested this" from "there was a discrete repricing event."

### 3.3 OU half-life for fade/hold behavior

Your current binary fade/hold is an information-loss representation. Replace with a continuous-time mean-reversion estimate.

**Implementation:**
```
ΔX_t = a + b * X_{t-1} + ε_t
kappa = -log(1 + b)
half_life = ln(2) / kappa
```

Where X_t is the post-event SAR path, regressed on its lag. Half-life in trading days is your output.

**Output:** Replace fade_or_hold_label with `mean_reversion_half_life_days`. "Tariff events have a fade half-life of 12 days; sanctions events have 47 days" is a real finding.

---

## Phase 4 — Transmission and Spillover (Weeks 8-10)

This is where second-order effects become quantifiable.

### 4.1 Diebold-Yilmaz spillover index

Skip DCC-GARCH for now. The Diebold-Yilmaz framework is simpler, more interpretable, and gives you the same essential insight.

**Implementation:** Estimate a VAR on rolling 250-day windows over (SPY, TLT, HYG, DXY, GLD, USO, sector ETFs). Compute forecast-error variance decomposition. The off-diagonal elements give you directional spillover from each asset to each other asset.

**Library:** `statsmodels.tsa.api.VAR` + manual FEVD computation.

**Output:** A time-varying spillover network. You can now answer: "during this event, did rates lead equities or vice versa?"

### 4.2 ES/NQ macro beta divergence

This is one of the most practically useful items on your list and I'm surprised it isn't already implemented.

**Implementation:** For each event, compute:
```
divergence = NQ_abnormal_return - ES_abnormal_return
```

Conditional on the event being rates-shock-related, divergence > 0 means duration-sensitive growth equities led the move (consistent with rate transmission). Divergence < 0 during a duration shock means something else is happening.

**Output:** A simple but powerful diagnostic that confirms or contradicts the proposed mechanism.

### 4.3 State-dependent local projections

Use Jordà local projections instead of a full SVAR. Simpler, more robust, easier to interpret.

```
y_{t+h} = α_h + β_h * shock_t + γ_h * shock_t * regime_t + controls + ε
```

Run for h = 1, 5, 10, 20, 60 days. Use HAC standard errors.

**Output:** Impulse response functions conditional on regime, for each mechanism family.

### 4.4 Empirical Bayes shrinkage

Once you have enough events per mechanism family (~30+), implement normal-normal empirical Bayes shrinkage for sparse-family estimates.

```
posterior_mean = (n / (n + tau)) * sample_mean + (tau / (n + tau)) * grand_mean
```

Where tau is estimated from cross-family variance.

**Why this matters:** Tiny families (rare event types) get sensible estimates that don't overfit to 3-4 observations.

---

## Phase 5 — Tail and Survival (Weeks 11-12)

### 5.1 Extreme-value analysis for tail validation

Fit Generalized Pareto to the upper tail of standardized abnormal returns (above the 95th percentile). This gives you principled answers to "is this move statistically extreme?"

**Library:** `scipy.stats.genpareto.fit`.

**Output:** Tail probability for any given event move. Replaces ad-hoc thresholds with principled tail risk.

### 5.2 Survival model for time-to-peak

Many events haven't peaked yet (right-censored). A binary "did it peak in 20d?" loses information.

**Implementation:** Cox proportional hazards or Weibull AFT. Covariates: mechanism family, validation status, regime, VIX level, event age.

**Library:** `lifelines.CoxPHFitter`.

**Output:** Probability of peak by horizon, given covariates. "This sanctions event has a 73% probability of peaking within 30 days given current regime."

---

## Phase 6 — Microstructure (Wait Until Daily Pipeline Is Solid)

Skip this entire section until everything above is working. The data dependency is too heavy and the marginal edge is small relative to Phase 1-5.

When you do return to it, prioritize:
- HMM-state-conditional intraday participation (if you get minute data)
- Volume-profile acceptance tests around prior-day value areas
- Cross-market lead-lag at the hourly level

---

## Deferred Ops Follow-Ups

- 2026-05-07 operator-side safety/diagnostic surface (no product-code changes, no paid/provider/LLM seams): event-date backfill planner + guarded writer + CLI (`event_date_backfill.py`, `scripts/event_date_backfill.py`, `--write --confirm` required together), event-date diagnostics (`/diagnostics/event-date-backfill-candidates`, `/diagnostics/event-date-backfill-impact-preview`), repo hygiene guard (`.githooks/`, `scripts/repo_hygiene_check.py`), backup restore checker, no-paid smoke 15/15.
- 2026-05-06 price-cache refreshes: guarded `auto_adjust=False` refresh improved reaction hydration (`hydrated_from_price_cache` 77, `reaction_profile_available_count` 49, `events_with_20d_signal` 31) with no paid/LLM paths. Current no-forward-20d split: 53 too recent, 3 `auto_adjust` mismatches, 71 cache-window gaps, 0 likely delisted/sparse. A focused no-forward-20d-gap refresh attempted 50 jobs but wrote 0 rows after yfinance raised `OperationalError: unable to open database file`; coverage stayed unchanged and no-paid smoke stayed green. Stop: do not run further refreshes until the provider cache failure is diagnosed.

---

## What This Roadmap Buys You

After Phase 1 alone, your "validated" claim becomes statistically defensible. After Phase 2, your reaction profiles become regime-aware. After Phase 3, you can distinguish causation from correlation. After Phase 4, you can quantify second-order transmission — which is literally your product's name.

For your demo specifically: **Phase 1 is the minimum acceptable bar.** Walking into a buy-side interview with raw returns and no multiple-testing correction is a credibility risk. Walking in with SAR + bootstrap CIs + FDR control is table stakes for the conversation to begin seriously.

## Implementation Discipline

Three rules:

1. **No new statistical machinery without a backtest.** Every method in Phase 1-3 must produce visible before/after on the existing 270-event archive before being shipped to UI.

2. **No method survives Phase 1-3 without a confidence interval.** Point estimates without uncertainty are not a quant product.

3. **Every model must have a falsifier.** If you claim "tariff events tighten financial conditions," there must be a specific test that could prove you wrong. Implement the falsifier alongside the claim.

These rules are what separate a quant tool from a fancy dashboard.
