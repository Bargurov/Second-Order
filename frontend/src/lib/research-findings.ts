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
