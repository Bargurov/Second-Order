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
    eventStudyAvailable: 71,
    eventStudyUnavailable: 10,
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
    eligiblePerHorizon: 63,
    support: { "1d": "0.508", "5d": "0.206", "20d": "0.222" } as Record<string, string>,
    reliability: "not reliable — degenerate null",
    reason:
      "The primary-ticker event-study is degenerate because the eligible primaries are all beneficiaries (predicted-up marginal 1.00), so the permutation null has nothing to shuffle.",
  },

  t3aMulti: {
    eligibleObs: 149,
    eligibleEvents: 69,
    predictedUpMarginal: "0.792",
    verdict: "Mixed — no consistent above-baseline result across horizons",
    reliability: "Reliable but thin (exposed-name coverage is the binding constraint)",
    horizons: [
      { h: "1d", support: "0.524", nullMean: "0.440", ci: "[0.376, 0.510]" },
      { h: "5d", support: "0.302", nullMean: "0.358", ci: "[0.302, 0.409]" },
      { h: "20d", support: "0.356", nullMean: "0.326", ci: "[0.275, 0.383]" },
    ],
    interpretation:
      "Multi-ticker AR fixes the degeneracy, but does not show robust above-baseline directional skill: the 1d result does not hold at 5d / 20d.",
  },

  t4aCoverage: {
    beneficiary: "118 / 216",
    beneficiaryPct: "54.6%",
    loser: "31 / 113",
    loserPct: "27.4%",
    total: "149 / 329",
    totalPct: "45.3%",
    limitation:
      "The exposed-name side is thin because cached price history and forward bars are missing, not because of a simple alias or code fix.",
    repairBoundary:
      "Repair requires a separate price-cache backfill with operator approval for network/provider calls and DB/cache writes.",
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

  // V3A — surfaces the V2A *dry-run* coverage repair plan (commit c77a4ec).
  // Static snapshot of the read-only planner output: NOTHING has been
  // executed, no coverage number above has changed, and no provider/cache
  // write has occurred.  V2B (the actual backfill) stays gated behind a DB
  // copy + explicit operator confirm_paid.
  coverageRepairPlan: {
    status: "not executed",
    currentLoser: "31 / 113",
    currentTotal: "149 / 329",
    worklist: {
      missingUnits: 180,
      distinctSymbols: 87,
      fixableWindows: 171,
      estRequests: 87,
      estCacheRows: "7,830",
    },
    fixability: [
      { id: "backfill_forward", count: 55, fixable: true },
      { id: "gap_fill_maybe", count: 53, fixable: true },
      { id: "backfill_earlier", count: 44, fixable: true },
      { id: "no_cache_backfill", count: 19, fixable: true },
      { id: "alias_manual_review", count: 6, fixable: false },
      { id: "future_not_yet", count: 2, fixable: false },
      { id: "delisted_stale", count: 1, fixable: false },
    ],
    gate: [
      "Not executed — no coverage numbers above have changed.",
      "V2B runs against a DB copy only; the live archive is never mutated first.",
      "V2B requires explicit operator confirm_paid=true before any provider or cache write.",
    ],
    nonClaim:
      "Filling exposed-name coverage may improve representativeness of the descriptive reads. It does not create statistical significance, an edge, or a directional claim; a single-event AR stays an n = 1 descriptive point estimate.",
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
