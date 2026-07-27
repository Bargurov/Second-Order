/**
 * A2-1 contract parity — the readout adapter consumes the REAL finalized
 * analysis contract.
 *
 * ``fixtures/finalized-analysis-readout.json`` is EXACTLY what the backend
 * finalizer (`analyze_event._finalize_analysis`) produces — proven by
 * ``tests/test_readout_fixture_fidelity.py``, which regenerates it and
 * deep-equals the committed file.  Driving that one real payload through
 * `buildReadout` pins the property A2-0 found broken: the shipped adapter
 * expected shapes no producer emits, so populated structured fields rendered
 * as falsely missing.
 *
 * Every expectation below is against the producer contract; none invents a
 * frontend-only shape.
 */
import { describe, it, expect } from "vitest";
import { buildReadout } from "../analysis-readout";
import REAL from "./fixtures/finalized-analysis-readout.json";

const r = buildReadout(REAL);

describe("transmission path — real hop objects render in declared order", () => {
  it("keeps all three hops", () => {
    expect(r.mechanism.path).toHaveLength(3);
  });

  it("keeps the action text of each hop, in order", () => {
    expect(r.mechanism.path.map((s) => s.action)).toEqual(
      REAL.transmission_path.map((h) => h.action),
    );
  });

  it("keeps the actor of each hop", () => {
    expect(r.mechanism.path.map((s) => s.actor)).toEqual(
      ["US Treasury OFAC", "Valero, PBF", "Suncor, Cenovus"],
    );
  });

  it("keeps the typed channel of each hop", () => {
    expect(r.mechanism.path.map((s) => s.channel)).toEqual(
      ["regulatory", "supply", "pricing_power"],
    );
  });

  it("keeps the expected market landing of each hop", () => {
    expect(r.mechanism.path[2].expectedMarketEffect).toContain("WCS-WTI");
  });

  it("keeps the timing of each hop", () => {
    expect(r.mechanism.path.map((s) => s.timing)).toEqual(
      ["1-5d", "5-20d", "5-20d"],
    );
  });

  it("numbers steps by declared order", () => {
    expect(r.mechanism.path.map((s) => s.sequence)).toEqual([1, 2, 3]);
  });
});

describe("counterforces — kind and chain link survive", () => {
  it("keeps both entries", () => {
    expect(r.counterforces.forces.values).toHaveLength(2);
  });

  it("distinguishes blocker from counterforce", () => {
    expect(r.counterforces.forces.values.map((f) => f.kind)).toEqual(
      ["counterforce", "blocker"],
    );
  });

  it("keeps the blocker's chain_hop link", () => {
    const blocker = r.counterforces.forces.values[1];
    expect(blocker.linkedHop).toContain("cuts off step 1");
  });

  it("keeps actor and likelihood", () => {
    expect(r.counterforces.forces.values[0].actor).toBe("OPEC+");
    expect(r.counterforces.forces.values[0].likelihood).toBe("medium");
  });
});

describe("substitution barriers — kind and severity survive", () => {
  it("keeps both barriers with severity", () => {
    expect(r.counterforces.substitutionBarriers.values.map((b) => b.severity))
      .toEqual(["high", "medium"]);
  });

  it("keeps the typed kind and leaves unclassified unlabelled", () => {
    expect(r.counterforces.substitutionBarriers.values[0].kind)
      .toBe("physical_sole_source");
    expect(r.counterforces.substitutionBarriers.values[1].kind).toBeNull();
  });
});

describe("critical breakpoints — structured objects are not dropped", () => {
  it("renders the real breakpoint object", () => {
    expect(r.falsifiers.criticalBreakpoints.available).toBe(true);
    expect(r.falsifiers.criticalBreakpoints.values).toHaveLength(1);
  });

  it("keeps observation, channel, timing and the thesis impact", () => {
    const bp = r.falsifiers.criticalBreakpoints.values[0];
    expect(bp.observation).toContain("OFAC licence revoked");
    expect(bp.channel).toBe("commodities");
    expect(bp.timing).toBe("1-5d");
    expect(bp.whyItChangesThesis).toContain("regulatory gate");
    expect(bp.condition).toContain("Treasury reverses");
    expect(bp.thresholdOrObservation).toContain("OFAC public notice");
  });

  it("keeps the proof/falsifier cross-link", () => {
    expect(r.falsifiers.criticalBreakpoints.values[0].linkedProofOrFalsifier)
      .toBe("key_falsifiers:0");
  });
});

describe("minimum proof — structured entries are not dropped", () => {
  it("renders both real proof objects", () => {
    expect(r.falsifiers.minimumProof.available).toBe(true);
    expect(r.falsifiers.minimumProof.values).toHaveLength(2);
  });

  it("keeps observation, channel, threshold and timing", () => {
    const p = r.falsifiers.minimumProof.values[0];
    expect(p.observation).toContain("WCS-WTI discount");
    expect(p.channel).toBe("commodities");
    expect(p.threshold).toBe(">=1.5pp narrower");
    expect(p.timing).toBe("1-5d");
  });
});

describe("confirming evidence — structured entries are not dropped", () => {
  it("renders the observation/channel object", () => {
    expect(r.resolution.confirmingEvidence.available).toBe(true);
    const ev = r.resolution.confirmingEvidence.values[0];
    expect(ev.observation).toContain("EIA");
    expect(ev.channel).toBe("commodities");
  });
});

describe("ranked assets — objects are not dropped", () => {
  it("renders primary assets with symbol, rank and rationale", () => {
    expect(r.exposure.primaryAssets.available).toBe(true);
    expect(r.exposure.primaryAssets.values.map((a) => a.symbol))
      .toEqual(["VLO", "PBF"]);
    expect(r.exposure.primaryAssets.values[0].rank).toBe(1);
    expect(r.exposure.primaryAssets.values[0].rationale)
      .toContain("coking capacity");
  });

  it("renders secondary and hedge buckets", () => {
    expect(r.exposure.secondaryAssets.values.map((a) => a.symbol))
      .toEqual(["SU"]);
    expect(r.exposure.hedgeOrSignal.values.map((a) => a.symbol))
      .toEqual(["XLE"]);
  });
});

describe("horizon checkpoints — the canonical shape renders", () => {
  it("keeps the timing profile", () => {
    expect(r.resolution.horizons.timingProfile).toBe("delayed_pass_through");
  });

  it("keeps the 1d / 5d / 20d cadence in order", () => {
    expect(r.resolution.horizons.checkpoints.map((h) => h.horizon))
      .toEqual(["1d", "5d", "20d"]);
  });

  it("keeps expected / confirms / falsifies per horizon", () => {
    const h5 = r.resolution.horizons.checkpoints[1];
    expect(h5.expected[0]).toContain("WCS-WTI");
    expect(h5.confirmsIf[0]).toContain(">=1.5pp");
    expect(h5.falsifiesIf[0]).toContain("unchanged or wider");
  });

  it("never renders the timing profile as a bogus horizon row", () => {
    expect(r.resolution.horizons.checkpoints.map((h) => h.horizon))
      .not.toContain("timing_profile");
  });
});

describe("monitor plan — the real dict shape renders", () => {
  it("keeps the first decisive tell", () => {
    expect(r.resolution.monitorPlan.available).toBe(true);
    expect(r.resolution.monitorPlan.tell?.observation)
      .toContain("Venezuelan cargo fixture");
    expect(r.resolution.monitorPlan.tell?.whatItMeans)
      .toContain("actually resuming");
  });

  it("keeps no-call signals with their reason", () => {
    expect(r.resolution.monitorPlan.noCallSignals).toHaveLength(1);
    expect(r.resolution.monitorPlan.noCallSignals[0].whyNoCall)
      .toContain("market-irrelevant");
  });
});

describe("source quality and regime caveats — real keys render", () => {
  it("reads source_type, not a phantom tier key", () => {
    expect(r.limits.sourceQuality.available).toBe(true);
    expect(r.limits.sourceQuality.value).toBe("policy_action");
  });

  it("keeps specificity and uncertainty", () => {
    expect(r.limits.sourceSpecificity.value).toBe("high");
    expect(r.limits.sourceUncertainty.value).toBe("low");
  });

  it("keeps the evidence-limitations sentence (a string, not a list)", () => {
    expect(r.limits.evidenceLimitations.available).toBe(true);
    expect(r.limits.evidenceLimitations.value).toContain("volume caps");
  });

  it("renders regime caveats from the real list shape", () => {
    expect(r.resolution.evidenceToRevisit.available).toBe(true);
    const caveat = r.resolution.evidenceToRevisit.values[0];
    expect(caveat.condition).toContain("Crude demand holds");
    expect(caveat.evidenceToRevisit).toContain("utilisation");
    expect(caveat.domain).toBe("credit");
  });
});

describe("fields that were already correct stay correct", () => {
  it("mechanism summary and enums", () => {
    expect(r.mechanism.summary.available).toBe(true);
    expect(r.mechanism.transmissionType.value).toBe("physical_flow");
    expect(r.mechanism.bottleneckType.value).toBe("commodity_quality_mismatch");
  });

  it("roles and flat falsifiers", () => {
    expect(r.exposure.directPositive.values).toContain("Valero Energy");
    expect(r.falsifiers.keyFalsifiers.values).toHaveLength(3);
  });

  it("escape path and regime caveat prose", () => {
    expect(r.counterforces.escapePath.value).toContain("TMX");
    expect(r.limits.regimeCaveat.available).toBe(true);
  });
});

describe("honest missingness is preserved for absent structures", () => {
  it("an empty analysis stays fully unavailable", () => {
    const empty = buildReadout({});
    expect(empty.mechanism.path).toEqual([]);
    expect(empty.falsifiers.criticalBreakpoints.available).toBe(false);
    expect(empty.falsifiers.minimumProof.available).toBe(false);
    expect(empty.exposure.primaryAssets.available).toBe(false);
    expect(empty.resolution.monitorPlan.available).toBe(false);
    expect(empty.resolution.horizons.checkpoints).toEqual([]);
    expect(empty.resolution.confirmingEvidence.available).toBe(false);
    expect(empty.limits.sourceQuality.available).toBe(false);
  });

  it("a malformed structured entry is skipped, not invented", () => {
    const messy = buildReadout({
      transmission_path: [42, { channel: "supply" }, { hop: "Named actor cuts supply", channel: "supply", actor: "" }],
      counterforces: [{ likelihood: "high" }],
      hidden_mechanism: { critical_breakpoints: [{ channel: "commodities" }] },
    });
    expect(messy.mechanism.path).toHaveLength(1);
    expect(messy.mechanism.path[0].actor).toBeNull();
    expect(messy.counterforces.forces.available).toBe(false);
    expect(messy.falsifiers.criticalBreakpoints.available).toBe(false);
  });

  it("legacy string entries stay readable as observation-only items", () => {
    const legacy = buildReadout({
      minimum_proof_set: ["Diesel crack > +8% vs pre-event"],
      hidden_mechanism: { critical_breakpoints: ["Restart before day 10"] },
    });
    expect(legacy.falsifiers.minimumProof.values[0].observation)
      .toBe("Diesel crack > +8% vs pre-event");
    expect(legacy.falsifiers.minimumProof.values[0].channel).toBeNull();
    expect(legacy.falsifiers.criticalBreakpoints.values[0].observation)
      .toBe("Restart before day 10");
  });
});
