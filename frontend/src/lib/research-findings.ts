/**
 * Static, typed snapshot of the T2 / T3 / T4 baseline research (read-only, as of
 * 2026-06-08), surfaced by the Evidence Overview page.  These numbers are
 * produced read-only by `scripts/baseline_characterization_report.py` and
 * `stats/baseline_characterization.py`; this module is a display snapshot, not a
 * live fetch.
 *
 * Copy carries no buy/sell/long/short/alpha/signal/trade framing and no
 * proof/proves/confirmed/edge framing.  The raw engine verdict token
 * (`mixed_no_consistent_signal`) is rendered here as a banned-word-free human
 * label.
 */

export const RESEARCH_FINDINGS = {
  asOf: "2026-06-08",

  corpus: {
    marketScored: 81,
    anySupporting: 19,
    contradicted: 35,
    unresolved: 27,
    eventStudyAvailable: 78,
    eventStudyUnavailable: 3,
  },

  t2aBaseline: {
    observedValidated: 19,
    nullMean: "19.2",
    ci95: "[13, 26]",
    verdict: "not_above_baseline",
    interpretation:
      "The raw scored archive is indistinguishable from a marginal-preserving naive baseline.",
  },

  t2bPrimary: {
    benchmark: "SPY",
    eligiblePerHorizon: 70,
    support: { "1d": "0.500", "5d": "0.214", "20d": "0.200" } as Record<string, string>,
    reliability: "not reliable — degenerate null",
    reason:
      "The primary-ticker event-study is degenerate because the eligible primaries are all beneficiaries (predicted-up marginal 1.00), so the permutation null has nothing to shuffle.",
  },

  t3aMulti: {
    eligibleObs: 292,
    eligibleEvents: 72,
    predictedUpMarginal: "0.675",
    verdict: "Mixed — no consistent above-baseline result across horizons",
    reliability: "Reliable — exposed-name coverage repaired (V2C); no longer thin",
    horizons: [
      { h: "1d", support: "0.531", nullMean: "0.455", ci: "[0.401, 0.503]" },
      { h: "5d", support: "0.339", nullMean: "0.422", ci: "[0.373, 0.469]" },
      { h: "20d", support: "0.397", nullMean: "0.399", ci: "[0.356, 0.438]" },
    ],
    interpretation:
      "Multi-ticker AR fixes the degeneracy on now-repaired coverage, but still shows no robust above-baseline directional skill: the 1d result does not hold at 5d / 20d.",
  },

  t4aCoverage: {
    beneficiary: "197 / 216",
    beneficiaryPct: "91.2%",
    loser: "95 / 113",
    loserPct: "84.1%",
    total: "292 / 329",
    totalPct: "88.8%",
    limitation:
      "Exposed-name coverage was repaired by an additive price-cache backfill (V2C); the residual gap is delisted / proxy-alias / holiday, not a fixable cache hole.",
    repairBoundary:
      "Repair executed: V2C promoted 8,538 additive price-cache rows into live (operator-approved daily-close provider); only price_cache changed.",
  },

  mechanismFamilies: {
    scoredTotal: 81,
    nonNone: 57,
    none: 24,
    label:
      "Deterministic mechanism-family inference — keyword/asset based, not paid structured extraction.",
    caveat:
      "This is a family grouping, not a first/second-order channel taxonomy or falsifier layer.",
    families: [
      { id: "commodity_squeeze", count: 26 },
      { id: "tariff", count: 13 },
      { id: "sanction", count: 9 },
      { id: "supply_shock", count: 3 },
      { id: "industrial_policy", count: 3 },
      { id: "ceasefire_deescalation", count: 2 },
      { id: "policy_surprise", count: 1 },
      { id: "none", count: 24 },
    ],
  },

  // U2 — definitions for the per-horizon measures the EventDossier event-study
  // table displays.  Surfaces existing methodology only (stats/METHODOLOGY.md +
  // event_study_validation.py constants: SPY, 60-bar window, horizons 1/5/20);
  // adds no new statistic and no new claim.
  methodology: {
    benchmark: "SPY",
    horizons: "1d / 5d / 20d",
    estimationWindow: 60,
    intro:
      "The EventDossier event-study table reports these per-horizon measures vs the benchmark. The definitions below explain the displayed numbers only — they add no new claim.",
    terms: [
      { term: "Raw", def: "The primary ticker's own move over the event window." },
      { term: "Bench", def: "The benchmark (SPY) move over the same window." },
      { term: "AR", def: "Abnormal return — raw minus benchmark over the horizon." },
      {
        term: "CAR",
        def: "Cumulative abnormal return — the additive accumulation of daily abnormal returns across the horizon.",
      },
      {
        term: "SAR",
        def: "Standardized abnormal return — AR divided by the daily abnormal-return volatility over the 60-bar pre-event window, scaled by the square root of the horizon. Shown as a ratio, not a percent.",
      },
    ],
    limits: [
      "Single-event rows are n = 1 descriptive readouts of one event window.",
      "Not statistical significance: no confidence interval, p-value, or false-discovery (FDR) control at the single-event level.",
      "The closed Phase 1 / Phase 2 FDR pools are a separate evidence track with their own frozen q-values.",
    ],
  },

  // V2C — the V2A worklist was EXECUTED and promoted to live (the V2B gated
  // backfill ran on a DB copy; V2C promoted the additive price-cache rows into
  // live after operator approval).  Live coverage now reflects the repair; the
  // numbers below are the residual (still-missing) worklist on live.
  coverageRepairPlan: {
    status: "executed",
    rowsInserted: "8,538",
    liveLoser: "95 / 113",
    liveTotal: "292 / 329",
    remaining: {
      units: 37,
      distinctSymbols: 26,
      windows: 28,
    },
    fixability: [
      { id: "gap_fill_maybe", count: 18, fixable: true },
      { id: "no_cache_backfill", count: 10, fixable: true },
      { id: "alias_manual_review", count: 6, fixable: false },
      { id: "future_not_yet", count: 2, fixable: false },
      { id: "delisted_stale", count: 1, fixable: false },
    ],
    notes: [
      "Executed via the V2C operator-approved promotion: +8,538 additive price-cache rows copied into live; only price_cache changed (events and other tables unchanged).",
      "Daily-close provider only; no existing live row was overwritten (48 existing-key value differences were kept as-is).",
      "Residual missingness is delisted / proxy-alias / residual gaps — not a simple backfill.",
    ],
    nonClaim:
      "The repair improves coverage / representativeness only. It does not create statistical significance, an edge, or a directional claim; a single-event AR stays an n = 1 descriptive point estimate. The temporal-clustering ceiling — the corpus is ~90% one 2-month window — is NOT lifted by coverage repair.",
  },

  nonClaims: [
    "Descriptive archive characterization only.",
    "Not a trading or prediction surface, and not a recommendation.",
    "Not a measure of edge.",
    "Not a statistical-significance test; the events are not independent.",
    "Single-event AR signs are n = 1 point estimates.",
    "Events are date-clustered / not independent.",
    "Separate from the closed Phase 1 / Phase 2 FDR pools; no pool q-values are used or implied.",
  ],
} as const;
