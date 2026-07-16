/**
 * M3 — reviewer guide pure contract (glossary + verification manifest).
 *
 * The glossary carries exactly the eight frozen terms with definitions,
 * tracked sources and explicit claim boundaries taken from the J0
 * constitution / publications — never invented, never softened into
 * confidence language.  The verification manifest traces exactly the four
 * material evidence lanes to their canonically recorded provenance:
 * missing fields say "not recorded", a pending contract says "preparing
 * tracked record", an unavailable contract says "record unavailable", and
 * nothing is inferred from Git HEAD, filenames or the clock.  The builder
 * is pure — no fetch, no browser global, deterministic ordering.
 */
import { describe, expect, it, vi } from "vitest";

import {
  EVIDENCE_GLOSSARY,
  buildEvidenceVerificationManifest,
  type VerificationLane,
} from "../evidence-reader-guide";
import { ACCEPTED_CORPUS as AC, FAMILY_COVERAGE as FC } from "../accepted-corpus";
import { EFFECTIVE_INDEPENDENT_EVIDENCE as EIE } from "../effective-independent-evidence";
import { MECHANISM_FAMILY_EVIDENCE as MFE } from "../mechanism-family-evidence";
import { REPRESENTATIVE_CASE_LIBRARY as RCL } from "../representative-case-library";
import { missionJFixture } from "@/components/ui/__tests__/mission-j-fixture";
import { missionGFixture } from "@/components/ui/__tests__/mission-g-fixture";

// ---------------------------------------------------------------------------
// Glossary
// ---------------------------------------------------------------------------

const EXPECTED_TERMS = [
  "MEMP",
  "ELEVATED",
  "ORDINARY / UNRESOLVED",
  "PROPAGATED",
  "BROAD MEASUREMENT CONSISTENCY",
  "Class B evidence",
  "measurement-limited",
  "unadjudicable",
];

function entry(term: string) {
  const found = EVIDENCE_GLOSSARY.find((e) => e.term === term);
  expect(found, term).toBeDefined();
  return found!;
}

describe("evidence reader guide — glossary contract", () => {
  it("contains exactly the eight frozen terms, unique, in stable order", () => {
    expect(EVIDENCE_GLOSSARY.map((e) => e.term)).toEqual(EXPECTED_TERMS);
    expect(new Set(EVIDENCE_GLOSSARY.map((e) => e.term)).size).toBe(8);
  });

  it("gives every term a definition, source document, source section, and claim boundary", () => {
    for (const e of EVIDENCE_GLOSSARY) {
      expect(e.definition.length, e.term).toBeGreaterThan(20);
      expect(e.source, e.term).toMatch(/^stats\/J[023]/);
      expect(e.sourceSection.length, e.term).toBeGreaterThan(3);
      expect(e.boundary.length, e.term).toBeGreaterThan(10);
    }
  });

  it("defines MEMP as the median event magnitude percentile via the mid-rank rule, never a p-value", () => {
    const e = entry("MEMP");
    expect(e.definition.toLowerCase()).toContain("median event magnitude percentile");
    expect(e.definition.toLowerCase()).toContain("mid-rank");
    expect(e.definition.toLowerCase()).toContain("ordinary reference");
    expect(e.definition.toLowerCase()).toContain("descriptive");
    expect(e.boundary.toLowerCase()).toContain("not a p-value");
    expect(e.boundary.toLowerCase()).toContain("not a probability of success");
    expect((e.definition + e.boundary).toLowerCase()).not.toContain("confidence");
  });

  it("defines ELEVATED with both frozen inequalities and its interpretation", () => {
    const e = entry("ELEVATED");
    expect(e.definition).toContain("M > 0.5");
    expect(e.definition).toContain("C > 0.75");
    expect(e.definition.toLowerCase()).toContain("above ordinary-period central tendency");
    expect(e.definition.toLowerCase()).toContain("upper side");
    const b = e.boundary.toLowerCase();
    expect(b).toContain("not statistical significance");
    expect(b).toContain("not a positive return");
    expect(b).toContain("not a causal effect");
    expect(b).toContain("not an investment opportunity");
  });

  it("defines ORDINARY / UNRESOLVED with the inclusive central calibration interval", () => {
    const e = entry("ORDINARY / UNRESOLVED");
    expect(e.definition).toContain("0.25 <= C <= 0.75");
    expect(e.definition.toLowerCase()).toContain("regardless of whether m is slightly above or below 0.5");
    expect(e.definition.toLowerCase()).toContain("do not support a special-response classification");
    expect(e.boundary.toLowerCase()).toContain('not "no effect"');
  });

  it("defines PROPAGATED as descriptive alignment, never proof of transmission", () => {
    const e = entry("PROPAGATED");
    const d = e.definition.toLowerCase();
    expect(d).toContain("upstream");
    expect(d).toContain("activated");
    expect(d).toContain("elevated");
    expect(d).toContain("descriptive");
    expect(e.boundary).toContain(
      "Descriptive alignment under frozen measurement rules — not proof that transmission occurred.",
    );
  });

  it("defines BROAD MEASUREMENT CONSISTENCY with the correlated-views boundary", () => {
    const e = entry("BROAD MEASUREMENT CONSISTENCY");
    const d = e.definition.toLowerCase();
    expect(d).toContain("all usable frozen measurements");
    expect(d).toContain("does not rest on one proxy");
    expect(e.boundary).toContain("correlated views, not independent replications");
  });

  it("defines Class B evidence as post-outcome, prospectively frozen, never independent confirmation", () => {
    const e = entry("Class B evidence");
    const d = e.definition.toLowerCase();
    expect(d).toContain("post-outcome");
    expect(d).toContain("prospectively frozen");
    expect(d).toContain("same historical sample");
    expect(d).toContain("robustness evidence");
    expect(e.boundary).toContain("Never independent historical confirmation.");
  });

  it("keeps the unavailable-ideal-measure limitation inside measurement-limited", () => {
    const e = entry("measurement-limited");
    const d = e.definition.toLowerCase();
    expect(d).toContain("ideal");
    expect(d).toContain("unavailable");
    expect(d).toContain("lower measurement class");
    expect(d).toContain("travels with every affected statement");
    expect(e.boundary.toLowerCase()).toContain('not "approximately confirmed"');
  });

  it("distinguishes missing adjudication from condition absence for unadjudicable", () => {
    const e = entry("unadjudicable");
    const d = e.definition.toLowerCase();
    expect(d).toContain("absent");
    expect(d).toContain("cannot receive a supported classification");
    expect(e.boundary).toContain(
      "Absence of adjudication is not evidence that the condition was absent",
    );
  });

  it("introduces no affirmative buy/sell, alpha, probability-of-success or significance claims", () => {
    const NEGATION = /\b(not|no|never|none|non|without|unavailable|absence)\b/i;
    for (const e of EVIDENCE_GLOSSARY) {
      for (const field of [e.definition, e.boundary]) {
        for (const banned of [
          /\bbuy\b/i,
          /\bsell\b/i,
          /\balpha\b/i,
          /confidence score/i,
          /success probability/i,
          /probability of success/i,
          /statistically significant/i,
          /statistical significance/i,
          /\bproof\b/i,
          /\bconfirmed\b/i,
          /investment opportunity/i,
        ]) {
          if (banned.test(field)) {
            expect(
              NEGATION.test(field),
              `${e.term}: banned token ${banned} outside a negation in ${JSON.stringify(field)}`,
            ).toBe(true);
          }
        }
      }
    }
  });
});

// ---------------------------------------------------------------------------
// Verification manifest
// ---------------------------------------------------------------------------

const EXPECTED_LANES = [
  "Accepted archive and denominator record",
  "Mission G historical record",
  "Mission J robustness and transmission record",
  "Mechanism-family / independence / representative-case static evidence",
];

const settledG = { isPending: false, isError: false, data: missionGFixture() };
const settledJ = { isPending: false, isError: false, data: missionJFixture() };
const pending = { isPending: true, isError: false, data: undefined };
const errored = { isPending: false, isError: true, data: undefined };

function fieldValue(lane: VerificationLane, label: string): string {
  const f = lane.fields.find((x) => x.label === label);
  expect(f, `${lane.lane}: ${label}`).toBeDefined();
  return f!.value;
}

function flat(lane: VerificationLane): string {
  return JSON.stringify(lane);
}

describe("evidence reader guide — verification manifest", () => {
  const manifest = buildEvidenceVerificationManifest(settledG, settledJ);
  const [accepted, missionG, missionJ, staticEvidence] = manifest;

  it("contains exactly the four material lanes, unique, in stable order", () => {
    expect(manifest.map((l) => l.lane)).toEqual(EXPECTED_LANES);
    expect(new Set(manifest.map((l) => l.lane)).size).toBe(4);
  });

  it("is deterministic for equal inputs and adds no Mission I lane", () => {
    expect(
      JSON.stringify(
        buildEvidenceVerificationManifest(
          { isPending: false, isError: false, data: missionGFixture() },
          { isPending: false, isError: false, data: missionJFixture() },
        ),
      ),
    ).toBe(JSON.stringify(manifest));
    expect(JSON.stringify(manifest)).not.toContain("Mission I");
  });

  it("preserves the canonical accepted-corpus provenance fields", () => {
    expect(accepted.availability).toBe("available — static tracked snapshot");
    expect(accepted.scope).toContain(String(AC.trackRecordTotal));
    expect(accepted.scope).toContain(String(AC.coverageDenominator));
    expect(accepted.scope).toContain(String(AC.savedEvents));
    expect(fieldValue(accepted, "As of")).toBe(AC.restatedOn);
    expect(fieldValue(accepted, "Reproduce (any-support OR-rule ledger)")).toBe(AC.orRuleRepro);
    expect(fieldValue(accepted, "Reproduce (directional-majority ledger)")).toBe(
      AC.directionalMajority.repro,
    );
    expect(fieldValue(accepted, "Source commit")).toBe("not recorded");
  });

  it("preserves the canonical static-evidence provenance fields", () => {
    expect(staticEvidence.availability).toBe("available — static tracked snapshot");
    expect(fieldValue(staticEvidence, "Independence caution (K2)")).toContain(EIE.sourceDoc);
    expect(fieldValue(staticEvidence, "Independence caution (K2)")).toContain(EIE.sourceCommit);
    expect(fieldValue(staticEvidence, "Reproduce (independence caution)")).toBe(EIE.reproCommand);
    expect(fieldValue(staticEvidence, "Family inventory (E1)")).toContain(MFE.sourceCommit);
    expect(fieldValue(staticEvidence, "Reproduce (family inventory)")).toBe(MFE.reproCommand);
    expect(fieldValue(staticEvidence, "Representative cases (F1/F2)")).toContain(RCL.sourceCommit);
    expect(fieldValue(staticEvidence, "Representative cases (F1/F2)")).toContain(
      RCL.outcomesRestatedOn,
    );
    expect(fieldValue(staticEvidence, "Reproduce (representative cases)")).toBe("not recorded");
    expect(fieldValue(staticEvidence, "Family coverage (AZ1)")).toContain(FC.asOf);
    expect(fieldValue(staticEvidence, "Reproduce (family coverage)")).toBe(FC.reproCommand);
  });

  it("takes Mission G provenance from the payload and marks unrecorded fields honestly", () => {
    const g = missionGFixture();
    expect(missionG.availability).toBe("available — tracked contract");
    expect(missionG.scope).toContain(String(g.lanes.historical.total));
    expect(missionG.scope).toContain(String(g.lanes.historical.fomc_frame_complete));
    expect(missionG.scope).toContain(String(g.lanes.historical.opec_designed_contrast));
    expect(fieldValue(missionG, "Source artifacts")).toContain(g.source_artifacts.readout);
    expect(fieldValue(missionG, "Source artifacts")).toContain(
      g.source_artifacts.mechanism_attrition,
    );
    // the contract records no commit / hash / date / command — never inferred
    expect(fieldValue(missionG, "Source commit")).toBe("not recorded");
    expect(fieldValue(missionG, "Artifact hashes")).toBe("not recorded");
    expect(fieldValue(missionG, "Computation / restatement date")).toBe("not recorded");
    expect(fieldValue(missionG, "Reproduce")).toBe("not recorded");
    expect(fieldValue(missionG, "Evidence ceiling")).toBe(g.non_claims[0]);
  });

  it("takes Mission J provenance (artifacts, hashes, ceiling) from the payload", () => {
    const j = missionJFixture();
    expect(missionJ.availability).toBe("available — tracked contract");
    expect(missionJ.scope).toContain(String(j.j2.collisions.primary_n));
    for (const key of ["j1b", "j2", "j3"] as const) {
      const src = j.provenance.sources[key];
      const label = `${key.toUpperCase()} artifact`;
      expect(fieldValue(missionJ, label)).toContain(src.artifact);
      expect(fieldValue(missionJ, label)).toContain(src.sha256);
      expect(fieldValue(missionJ, label)).toContain(String(src.bytes));
    }
    expect(fieldValue(missionJ, "Publication status")).toBe(j.provenance.publication_status);
    expect(fieldValue(missionJ, "Computation / restatement date")).toBe("not recorded");
    expect(fieldValue(missionJ, "Reproduce")).toBe("not recorded");
    const ceiling = fieldValue(missionJ, "Evidence ceiling");
    expect(ceiling.toLowerCase()).toContain("same-sample class b evidence");
    expect(ceiling.toLowerCase()).toContain("mechanism-consistent descriptive pattern");
    expect(ceiling).not.toContain("**");
  });

  it("keeps Mission G and Mission J as separate, unmerged lanes", () => {
    expect(flat(missionG)).not.toContain("J1B");
    expect(flat(missionG)).not.toContain("sha256");
    expect(flat(missionJ)).not.toContain("G6_FROZEN_MANIFEST_READOUT");
    expect(flat(manifest[0] as VerificationLane) + flat(missionG) + flat(missionJ)).not.toContain(
      "183",
    );
  });

  it("renders a pending contract lane as preparing, without hiding it", () => {
    const m = buildEvidenceVerificationManifest(pending, pending);
    expect(m).toHaveLength(4);
    expect(m[1].availability).toBe("preparing tracked record");
    expect(m[2].availability).toBe("preparing tracked record");
    expect(fieldValue(m[1], "Source artifacts")).toBe("preparing tracked record");
    expect(fieldValue(m[2], "Evidence ceiling")).toBe("preparing tracked record");
    // static lanes stay fully available
    expect(m[0].availability).toBe("available — static tracked snapshot");
    expect(m[3].availability).toBe("available — static tracked snapshot");
  });

  it("renders an unavailable contract lane as record unavailable, without omission", () => {
    const m = buildEvidenceVerificationManifest(errored, settledJ);
    expect(m).toHaveLength(4);
    expect(m[1].availability).toBe("record unavailable");
    expect(fieldValue(m[1], "Source artifacts")).toBe("record unavailable");
    expect(fieldValue(m[1], "Evidence ceiling")).toBe("record unavailable");
    // the sibling lane is untouched
    expect(m[2].availability).toBe("available — tracked contract");
    // the contract route itself is app knowledge, not payload knowledge
    expect(fieldValue(m[1], "Contract")).toContain("GET /evidence/mission-g");
  });

  it("never infers a Mission G commit or hash from anywhere", () => {
    for (const snapshot of [settledG, pending, errored]) {
      const m = buildEvidenceVerificationManifest(snapshot, settledJ);
      const commit = m[1].fields.find((f) => f.label === "Source commit")?.value ?? "";
      expect(["not recorded", "preparing tracked record", "record unavailable"]).toContain(commit);
      expect(commit).not.toMatch(/^[0-9a-f]{7,40}$/);
    }
  });

  it("exposes reproduction commands as inert code strings only", () => {
    for (const lane of manifest) {
      for (const f of lane.fields) {
        expect(typeof f.value, `${lane.lane}: ${f.label}`).toBe("string");
        if (f.label.startsWith("Reproduce") && f.value !== "not recorded") {
          expect(f.code, `${lane.lane}: ${f.label} must be code`).toBe(true);
          expect(f.value).toMatch(/^python/);
        }
      }
    }
  });

  it("builds without fetching or touching browser globals", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    try {
      buildEvidenceVerificationManifest(settledG, settledJ);
      buildEvidenceVerificationManifest(errored, pending);
      expect(fetchSpy).not.toHaveBeenCalled();
      // node test env has no window/document — construction would have thrown
      expect(typeof globalThis.window).toBe("undefined");
      expect(typeof globalThis.document).toBe("undefined");
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
