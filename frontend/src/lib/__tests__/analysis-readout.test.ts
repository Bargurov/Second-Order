/**
 * analysis-readout.test.ts — the pure presentation model for A1-3.
 *
 * The readout REORGANIZES what the engine already returned.  It performs no
 * analysis, invents no fallback content, and never merges two things the
 * contract keeps apart — an indirect channel is not a primary asset, a
 * monitoring item is not a falsifier, and a competing thesis is not a footnote
 * on the primary one.
 *
 * Missingness is a first-class result: a field the engine did not return reads
 * as explicitly unavailable, never as an empty success.
 */

import { describe, it, expect } from "vitest";
import {
  buildReadout,
  qualityTierLabel,
  READOUT_SECTION_ORDER,
  MECHANISM_NON_CLAIM,
} from "../analysis-readout";

/** Minimal logic fixture in the REAL finalizer shapes (the captured-payload
 *  regression lives in analysis-readout-contract.test.ts; this one proves
 *  ownership/missingness mechanics only). */
function full(): Record<string, unknown> {
  return {
    what_changed: "Outage removed 400kb/d of refining capacity.",
    mechanism_summary: "Regional diesel balance tightens through Q3.",
    transmission_chain: ["outage", "cracks widen", "haulier costs rise"],
    transmission_path: [
      { hop: "Refinery outage removes regional capacity", channel: "supply",
        actor: "Regional refiner", expected_market_effect: "Diesel cracks widen",
        timing: "1-5d" },
      { hop: "Crack spreads widen on the reduced supply", channel: "pricing_power",
        actor: "Merchant refiners" },
    ],
    hidden_mechanism: {
      transmission_type: "physical_flow",
      bottleneck_type: "capacity_bottleneck",
      substitution_escape_path: "Seaborne imports within 3 weeks",
      critical_breakpoints: [
        { signal: "Restart before day 10", channel: "commodities", timing: "1-5d" },
      ],
      optional_confirming_evidence: [
        { observation: "Freight rate divergence", channel: "commodities" },
      ],
      source_quality: {
        source_type: "reported_disruption",
        specificity: "medium",
        uncertainty_level: "medium",
        evidence_limitations: "One outlet reported the volume",
      },
      regime_caveats: [
        { condition: "Diesel demand stays firm",
          effect_on_thesis: "A demand slump would swamp the supply effect",
          evidence_to_revisit: "Demand-side prints", domain: "credit" },
      ],
    },
    beneficiaries: ["independent refiners"],
    losers: ["road hauliers"],
    primary_assets: [
      { symbol: "VLO", rank: 1, rationale: "Merchant refiner margin exposure" },
      { symbol: "PSX", rank: 2, rationale: "Second-largest merchant capacity" },
    ],
    secondary_assets: [{ symbol: "ODFL", rank: 1, rationale: "Fuel cost taker" }],
    hedge_or_signal_assets: [{ symbol: "XLE", rank: 1, rationale: "Sector control" }],
    expected_second_order_channels: ["SUPPLY_CHAIN", "INFLATION"],
    counterforces: [
      { force: "SPR release", actor: "US DOE", likelihood: "medium",
        kind: "counterforce" },
    ],
    substitution_barriers: [
      { barrier: "Import logistics", kind: "logistics", severity: "high" },
    ],
    competing_thesis: {
      thesis: "Demand weakness dominates",
      evidence: "Freight volumes already falling",
    },
    adversarial_challenge: "The outage may be repaired faster than assumed.",
    key_falsifiers: ["Crack spreads flat after 5 sessions"],
    minimum_proof_set: [
      { observation: "Diesel crack > +8% vs pre-event", channel: "commodities",
        threshold: "+8%", timing: "1-5d" },
    ],
    proof_status: { status: "not_yet_observed" },
    falsifier_status: { status: "not_yet_observed" },
    horizon_checkpoints: {
      timing_profile: "fast_shock",
      horizons: [
        { horizon: "1d", expected: ["Crack reaction"], confirms_if: [],
          falsifies_if: [] },
        { horizon: "5d", expected: ["Inventory print"], confirms_if: [],
          falsifies_if: [] },
      ],
    },
    monitor_plan: {
      first_decisive_tell: {
        observation: "Weekly EIA inventory print", channel: "commodities",
        what_it_means: "Confirms whether the draw is showing up",
      },
      no_call_signals: [],
    },
    quality_tier: "actionable",
    quality_warnings: ["Single-outlet volume estimate"],
    validation_warnings: ["Ticker set not independently confirmed"],
    degraded: false,
    regime_conditioned_caveat: "Holds only while imports stay constrained.",
  };
}

// ---------------------------------------------------------------------------
// Order and shape
// ---------------------------------------------------------------------------

describe("the frozen research chain", () => {
  it("exposes the sections in the declared order", () => {
    expect(READOUT_SECTION_ORDER).toEqual([
      "mechanism", "exposure", "counterforces",
      "falsifiers", "resolution", "limits",
    ]);
  });

  it("returns a section for every declared name, populated or not", () => {
    for (const source of [full(), {}]) {
      const r = buildReadout(source);
      for (const name of READOUT_SECTION_ORDER) {
        expect(r[name], `${name} missing`).toBeDefined();
      }
    }
  });

  it("preserves the engine's transmission order verbatim", () => {
    const r = buildReadout(full());
    expect(r.mechanism.path.map((s) => s.action)).toEqual([
      "Refinery outage removes regional capacity",
      "Crack spreads widen on the reduced supply",
    ]);
    expect(r.mechanism.path.map((s) => s.sequence)).toEqual([1, 2]);
  });

  it("does not mutate the response it was given", () => {
    const source = full();
    const snapshot = JSON.stringify(source);
    buildReadout(source);
    expect(JSON.stringify(source)).toBe(snapshot);
  });

  it("is deterministic across repeated calls", () => {
    expect(JSON.stringify(buildReadout(full())))
      .toBe(JSON.stringify(buildReadout(full())));
  });
});

// ---------------------------------------------------------------------------
// Field ownership — things the contract keeps apart stay apart
// ---------------------------------------------------------------------------

describe("exposure roles stay separate", () => {
  it("keeps direct positive, direct negative, indirect and hedge distinct", () => {
    const e = buildReadout(full()).exposure;
    expect(e.directPositive.values).toEqual(["independent refiners"]);
    expect(e.directNegative.values).toEqual(["road hauliers"]);
    expect(e.primaryAssets.values.map((a) => a.symbol)).toEqual(["VLO", "PSX"]);
    expect(e.secondaryAssets.values.map((a) => a.symbol)).toEqual(["ODFL"]);
    expect(e.hedgeOrSignal.values.map((a) => a.symbol)).toEqual(["XLE"]);
    expect(e.indirectChannels.values).toEqual(["SUPPLY_CHAIN", "INFLATION"]);
  });

  it("never merges indirect channels into primary assets", () => {
    const e = buildReadout(full()).exposure;
    for (const channel of e.indirectChannels.values) {
      expect(e.primaryAssets.values.map((a) => a.symbol)).not.toContain(channel);
      expect(e.secondaryAssets.values.map((a) => a.symbol)).not.toContain(channel);
    }
  });

  it("keeps economic roles separate from assets", () => {
    const e = buildReadout(full()).exposure;
    expect(e.directPositive.kind).toBe("role");
    expect(e.primaryAssets.values[0]).toHaveProperty("symbol");
  });

  it("reports an empty role group as unavailable, not as assessed-and-empty", () => {
    const e = buildReadout({ ...full(), hedge_or_signal_assets: [] }).exposure;
    expect(e.hedgeOrSignal.available).toBe(false);
    expect(e.hedgeOrSignal.values).toEqual([]);
  });
});

describe("falsifiers, proof and monitoring stay separate", () => {
  it("keeps key falsifiers distinct from the minimum proof set", () => {
    const f = buildReadout(full()).falsifiers;
    expect(f.keyFalsifiers.values).toEqual(["Crack spreads flat after 5 sessions"]);
    expect(f.minimumProof.values.map((p) => p.observation))
      .toEqual(["Diesel crack > +8% vs pre-event"]);
    expect(f.keyFalsifiers.values)
      .not.toEqual(f.minimumProof.values.map((p) => p.observation));
  });

  it("keeps monitoring items out of the falsifier group", () => {
    const r = buildReadout(full());
    expect(r.resolution.monitorPlan.tell?.observation)
      .toBe("Weekly EIA inventory print");
    expect(r.falsifiers.keyFalsifiers.values)
      .not.toContain("Weekly EIA inventory print");
  });

  it("preserves an explicit not-yet-observed status without upgrading it", () => {
    const f = buildReadout(full()).falsifiers;
    expect(f.proofStatus.label).toMatch(/not yet observed/i);
    expect(f.proofStatus.label.toLowerCase()).not.toMatch(/passed|met|confirmed/);
  });

  it("reports an absent status as unknown rather than as passed", () => {
    const f = buildReadout({ ...full(), proof_status: undefined,
                             falsifier_status: undefined }).falsifiers;
    expect(f.proofStatus.available).toBe(false);
    expect(f.proofStatus.label.toLowerCase()).not.toMatch(/passed|met|confirmed/);
  });
});

describe("counterforces and the competing thesis stay visible", () => {
  it("keeps counterforces populated even when the mechanism is populated", () => {
    const r = buildReadout(full());
    expect(r.mechanism.summary.available).toBe(true);
    expect(r.counterforces.forces.values).toHaveLength(1);
  });

  it("keeps the competing thesis separate from the primary mechanism", () => {
    const r = buildReadout(full());
    expect(r.counterforces.competingThesis.available).toBe(true);
    expect(r.mechanism.summary.value)
      .not.toContain("Demand weakness dominates");
  });

  it("labels the adversarial challenge as model-generated", () => {
    const c = buildReadout(full()).counterforces;
    expect(c.adversarialChallenge.available).toBe(true);
    expect(c.adversarialChallenge.provenanceLabel.toLowerCase())
      .toContain("model-generated");
  });

  it("reports absent counterforces as unavailable, never as strength", () => {
    const c = buildReadout({ ...full(), counterforces: [] }).counterforces;
    expect(c.forces.available).toBe(false);
    expect(JSON.stringify(c).toLowerCase())
      .not.toMatch(/no counterforces means|robust|unchallenged|strong/);
  });
});

// ---------------------------------------------------------------------------
// Missingness
// ---------------------------------------------------------------------------

describe("missingness is explicit", () => {
  it("marks every field of an empty analysis unavailable", () => {
    const r = buildReadout({});
    expect(r.mechanism.summary.available).toBe(false);
    expect(r.mechanism.path).toEqual([]);
    expect(r.exposure.primaryAssets.available).toBe(false);
    expect(r.falsifiers.keyFalsifiers.available).toBe(false);
    expect(r.resolution.horizons)
      .toEqual({ timingProfile: null, checkpoints: [], legacy: [] });
    expect(r.limits.qualityTier.available).toBe(false);
  });

  it("invents no fallback text for a missing field", () => {
    const r = buildReadout({});
    expect(r.mechanism.summary.value).toBeNull();
    expect(r.counterforces.competingThesis.value).toBeNull();
  });

  it("survives a malformed payload without throwing", () => {
    for (const bad of [null, undefined, "text", 42,
                       { transmission_path: "not an array" },
                       { hidden_mechanism: [] },
                       { counterforces: [null, 3] }]) {
      expect(() => buildReadout(bad as never)).not.toThrow();
    }
  });

  it("keeps a partially populated hidden mechanism honest", () => {
    const r = buildReadout({ hidden_mechanism: { transmission_type: "physical_supply" } });
    expect(r.mechanism.transmissionType.available).toBe(true);
    expect(r.mechanism.bottleneckType.available).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Limits, warnings and claim ceilings
// ---------------------------------------------------------------------------

describe("limits and warnings cannot be hidden", () => {
  it("always surfaces degraded state and validation warnings", () => {
    const l = buildReadout({ ...full(), degraded: true }).limits;
    expect(l.degraded).toBe(true);
    expect(l.validationWarnings.values).toHaveLength(1);
    expect(l.prominent).toBe(true);
  });

  it("stays prominent on validation warnings even when not degraded", () => {
    expect(buildReadout(full()).limits.prominent).toBe(true);
  });

  it("separates source quality from model confidence", () => {
    const l = buildReadout(full()).limits;
    expect(l.sourceQuality.available).toBe(true);
    expect(JSON.stringify(l)).not.toContain("confidence");
  });

  it("carries evidence limitations and the regime caveat", () => {
    const l = buildReadout(full()).limits;
    expect(l.evidenceLimitations.value).toBe("One outlet reported the volume");
    expect(l.regimeCaveat.available).toBe(true);
  });
});

describe("quality tier reads as review language, never as a recommendation", () => {
  it("maps each stored enum to professional review copy", () => {
    expect(qualityTierLabel("low_information")).toBe("Limited information");
    expect(qualityTierLabel("watch_only")).toBe("Monitor / insufficiently resolved");
    expect(qualityTierLabel("actionable"))
      .toBe("Sufficiently specified for research review");
  });

  it("contains no recommendation or trade vocabulary", () => {
    for (const tier of ["low_information", "watch_only", "actionable"]) {
      const label = qualityTierLabel(tier).toLowerCase();
      expect(label).not.toMatch(/buy|sell|trade|alpha|actionable|winner|best|top|opportunity/);
    }
  });

  it("passes an unknown tier through rather than inventing a rating", () => {
    expect(qualityTierLabel("something_new")).toBe("something_new");
    expect(qualityTierLabel(undefined)).toBeNull();
  });

  it("keeps the stored enum value unchanged on the model", () => {
    expect(buildReadout(full()).limits.qualityTier.value).toBe("actionable");
  });
});

describe("the mechanism is framed as a hypothesis", () => {
  it("ships a non-claim that denies a causal estimate", () => {
    expect(MECHANISM_NON_CLAIM.toLowerCase()).toContain("not a causal estimate");
    expect(MECHANISM_NON_CLAIM.toLowerCase()).not.toMatch(/proves|confirms|validated/);
  });

  it("never describes the ordered path as a proven chain", () => {
    const r = buildReadout(full());
    expect(r.mechanism.pathLabel.toLowerCase()).not.toMatch(/proven|causal|established/);
  });
});
