/**
 * mechanism-resolution-readout.test.ts — A1-3 surface contract.
 *
 * Source-level scans in the style of the existing surface suites.  They pin
 * what the pure model (lib/analysis-readout) cannot see from outside the
 * component: that the readout follows the frozen chain, owns only the fields
 * it is meant to own, keeps limitations reachable, and adds no recommendation,
 * score, or re-analysis affordance.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const view = () =>
  readFileSync(resolve(__dirname, "..", "analysis-view.tsx"), "utf-8");

/**
 * The readout implementation, isolated from the rest of the page.
 *
 * Spans the helper components (ReadoutGroup / ReadoutList / ReadoutBand) too —
 * they carry the unavailable rendering and the label column, so a slice that
 * started at the main component would miss the behaviour under test.
 */
function readout(): string {
  const src = view();
  const start = src.indexOf("function ReadoutGroup");
  expect(start, "readout helpers must exist").toBeGreaterThan(-1);
  const end = src.indexOf("function AnalysisBasisSection");
  expect(end, "Analysis Basis must remain a separate component").toBeGreaterThan(start);
  return src.slice(start, end);
}

describe("the readout follows the frozen research chain", () => {
  it("renders the six sections in the declared order", () => {
    const body = readout();
    const order = ["Mechanism", "Exposure", "Counterforces",
                   "What would weaken", "resolve the mechanism", "Evidence limits"];
    let cursor = -1;
    for (const label of order) {
      const at = body.indexOf(label);
      expect(at, `${label} missing from the readout`).toBeGreaterThan(-1);
      expect(at, `${label} is out of chain order`).toBeGreaterThan(cursor);
      cursor = at;
    }
  });

  it("is driven by the pure model rather than reading the payload inline", () => {
    const body = readout();
    expect(view()).toMatch(/buildReadout\(/);
    // Every field must come through the model, so the component cannot
    // quietly reinterpret or backfill one.
    expect(body).not.toMatch(/analysis\.(key_falsifiers|primary_assets|hidden_mechanism)/);
  });

  it("states the mechanism non-claim", () => {
    expect(readout()).toContain("MECHANISM_NON_CLAIM");
  });
});

describe("field ownership on the surface", () => {
  it("renders the structured transmission path, not the already-shown chain", () => {
    const body = readout();
    expect(body).toMatch(/mechanism\.path/);
    // transmission_chain already has its own section; repeating it would be
    // the duplicate summary the slice is meant to avoid.
    expect(body).not.toMatch(/transmission_chain/);
  });

  it("renders each exposure role from its own group", () => {
    const body = readout();
    for (const g of ["directPositive", "directNegative", "primaryAssets",
                     "secondaryAssets", "hedgeOrSignal", "indirectChannels"]) {
      expect(body, g).toContain(g);
    }
  });

  it("keeps falsifiers separate from the minimum proof set", () => {
    const body = readout();
    expect(body).toContain("keyFalsifiers");
    expect(body).toContain("minimumProof");
  });

  it("keeps monitoring separate from falsifiers", () => {
    const body = readout();
    expect(body).toContain("monitorPlan");
    expect(body).toMatch(/resolution\./);
  });

  it("labels the adversarial challenge as model-generated", () => {
    expect(readout()).toContain("provenanceLabel");
  });
});

describe("honest missingness", () => {
  it("has an explicit unavailable rendering", () => {
    expect(readout()).toMatch(/Not (reported|available)|unavailable/i);
  });

  it("does not skip a group merely because it is empty", () => {
    // Groups render through one shared helper that handles the empty case,
    // rather than each being gated behind `.length > 0`.
    expect(readout()).toMatch(/available\s*\?/);
  });
});

describe("limitations stay reachable", () => {
  it("renders limits inside the readout, not behind a collapsed control", () => {
    const body = readout();
    const limitsAt = body.indexOf("Evidence limits");
    // The rendered disclosure block, not the state declaration.
    const disclosureAt = body.indexOf("{detailOpen && (");
    expect(limitsAt).toBeGreaterThan(-1);
    expect(disclosureAt, "the detail disclosure must exist").toBeGreaterThan(-1);
    expect(limitsAt, "limits must render before, and outside, the disclosure")
      .toBeLessThan(disclosureAt);
  });

  it("keeps degraded and validation warnings prominent", () => {
    const body = readout();
    expect(body).toMatch(/limits\.degraded/);
    expect(body).toMatch(/validationWarnings/);
  });

  it("translates the quality tier through the shared label map", () => {
    expect(readout()).toMatch(/qualityTierLabel\(/);
  });
});

describe("claim ceilings", () => {
  it("adds no recommendation, score, rank or trade vocabulary", () => {
    const body = readout().toLowerCase();
    // Affirmative recommendation-MAKING language only.  A bare "recommend"
    // stem would flag the surface's own honest denial ("not a
    // recommendation"), which is the disclosure this rule exists to keep.
    for (const banned of ["buy ", "sell ", "top trade", "winner", "alpha",
                          "opportunity score", "strength score", "conviction score",
                          "bullish", "bearish", "we recommend", "recommended"]) {
      expect(body, banned).not.toContain(banned);
    }
  });

  it("states plainly that the specification tier is not a recommendation", () => {
    expect(readout()).toContain("not a recommendation");
  });

  it("adds no re-analysis or refresh control", () => {
    const body = readout();
    expect(body).not.toMatch(/api\.analyze/);
    expect(body).not.toMatch(/submit\(/);
  });

  it("does not duplicate the Analysis Basis identity fields", () => {
    const body = readout();
    for (const owned of ["candidate_id", "provenance_hash", "analysis_prompt_version",
                         "analysis_schema_version", "provenanceLabel: PROVENANCE"]) {
      expect(body, owned).not.toContain(owned);
    }
  });

  it("does not treat provenance status as conclusion validity", () => {
    const body = readout();
    expect(body).not.toContain("VERIFIED_CURRENT");
    expect(body).not.toMatch(/isBasisTrustworthy/);
  });
});

describe("the readout is mounted in the completed analysis", () => {
  it("mounts after the thesis and before the reference band", () => {
    const src = view();
    const mount = src.indexOf("<MechanismResolutionReadout");
    const thesis = src.indexOf('title="What changed & how it transmits"');
    const backstage = src.indexOf("Backstage · reference");
    expect(mount).toBeGreaterThan(-1);
    expect(mount, "must come after the thesis section").toBeGreaterThan(thesis);
    expect(mount, "must come before the reference band").toBeLessThan(backstage);
  });

  it("keeps the Analysis Basis section intact and separate", () => {
    const src = view();
    expect(src).toContain("function AnalysisBasisSection");
    expect(src).toMatch(/<AnalysisBasisSection/);
  });
});
