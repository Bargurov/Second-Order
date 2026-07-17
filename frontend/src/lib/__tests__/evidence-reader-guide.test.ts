/**
 * M3/N2 — reviewer guide pure contract (glossary + verification manifest).
 *
 * The glossary carries exactly the eight frozen terms with definitions,
 * tracked sources and explicit claim boundaries taken from the J0
 * constitution / publications — never invented, never softened into
 * confidence language.  The verification manifest traces exactly the five
 * material evidence lanes (N2 added the Mission I ordinary-period
 * comparison record between Mission G and Mission J) to their canonically
 * recorded provenance: missing fields say "not recorded", a pending
 * contract says "preparing tracked record", an unavailable contract says
 * "record unavailable", and nothing is inferred from Git HEAD, filenames
 * or the clock.  The builder is pure — no fetch, no browser global,
 * deterministic ordering.
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
import { missionIFixture } from "@/components/ui/__tests__/mission-i-fixture";
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
  "Mission I ordinary-period comparison record",
  "Mission J robustness and transmission record",
  "Mechanism-family / independence / representative-case static evidence",
];

const settledG = { isPending: false, isError: false, data: missionGFixture() };
const settledI = { isPending: false, isError: false, data: missionIFixture() };
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
  const manifest = buildEvidenceVerificationManifest(settledG, settledI, settledJ);
  const [accepted, missionG, missionI, missionJ, staticEvidence] = manifest;

  it("contains exactly the five material lanes, unique, in stable order", () => {
    expect(manifest.map((l) => l.lane)).toEqual(EXPECTED_LANES);
    expect(new Set(manifest.map((l) => l.lane)).size).toBe(5);
  });

  it("is deterministic for equal inputs, with exactly one Mission I lane between G and J", () => {
    expect(
      JSON.stringify(
        buildEvidenceVerificationManifest(
          { isPending: false, isError: false, data: missionGFixture() },
          { isPending: false, isError: false, data: missionIFixture() },
          { isPending: false, isError: false, data: missionJFixture() },
        ),
      ),
    ).toBe(JSON.stringify(manifest));
    const laneNames = manifest.map((l) => l.lane);
    expect(
      laneNames.filter((l) => l === "Mission I ordinary-period comparison record"),
    ).toHaveLength(1);
    expect(laneNames.indexOf("Mission I ordinary-period comparison record")).toBe(
      laneNames.indexOf("Mission G historical record") + 1,
    );
    expect(laneNames.indexOf("Mission J robustness and transmission record")).toBe(
      laneNames.indexOf("Mission I ordinary-period comparison record") + 1,
    );
  });

  it("takes Mission I provenance (artifacts, hashes, repro, ceiling) from the payload", () => {
    const i = missionIFixture();
    expect(missionI.availability).toBe("available — tracked contract");
    expect(missionI.scope).toContain("65");
    expect(missionI.scope).toContain("32");
    expect(missionI.scope).toContain("20 primary cells");
    expect(missionI.scope).toContain("6 falsifier families");
    expect(fieldValue(missionI, "Contract")).toContain("GET /evidence/mission-i");
    expect(fieldValue(missionI, "Contract")).toContain(i.contract_version);
    const artifacts = fieldValue(missionI, "Source artifacts");
    const hashes = fieldValue(missionI, "Artifact hashes");
    for (const src of Object.values(i.provenance.sources)) {
      expect(artifacts).toContain(src.artifact);
      expect(hashes).toContain(src.sha256);
    }
    const repro = fieldValue(missionI, "Reproduce");
    for (const cmd of i.provenance.reproduction.commands) {
      expect(repro).toContain(cmd);
    }
    // recorded in NO Mission I publication — stated, never inferred
    expect(fieldValue(missionI, "Computation dates")).toBe("not recorded");
    expect(fieldValue(missionI, "Execution commits")).toBe("not recorded");
    const ceiling = fieldValue(missionI, "Evidence ceiling");
    expect(ceiling).toContain("percentile-of-placements only");
    expect(ceiling.toLowerCase()).toContain("no p-values");
  });

  it("keeps Mission I a separate, unpooled lane", () => {
    expect(flat(missionI)).not.toContain("J1B");
    expect(flat(missionI)).not.toContain("G6_FROZEN_MANIFEST_READOUT");
    expect(flat(missionG)).not.toContain("mission-i");
    expect(flat(missionJ)).not.toContain("mission-i");
    // 65 + 32 never presented as one 97-event Mission I sample
    expect(missionI.scope).not.toContain("97");
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
    // recorded in both F1/F2 source documents ("Reproduce (read-only)")
    expect(fieldValue(staticEvidence, "Reproduce (representative cases)")).toBe(
      RCL.reproCommands.join(" · "),
    );
    expect(fieldValue(staticEvidence, "Family coverage (AZ1)")).toContain(FC.asOf);
    // the shortlist decision log records its baseline commit; the overview
    // map records none — both states stay explicit
    expect(fieldValue(staticEvidence, "Family coverage (AZ1)")).toContain(
      FC.shortlistBaselineCommit,
    );
    expect(fieldValue(staticEvidence, "Family coverage (AZ1)")).toContain(
      "overview commit not recorded",
    );
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
    // request-time artifact hashes and the recorded per-publication
    // reproduction commands come from the payload
    const hashes = fieldValue(missionG, "Artifact hashes");
    for (const src of Object.values(g.provenance.sources)) {
      expect(hashes).toContain(src.artifact);
      expect(hashes).toContain(src.sha256);
      expect(hashes).toContain(String(src.bytes));
    }
    const repro = fieldValue(missionG, "Reproduce");
    for (const [key, commands] of Object.entries(g.provenance.reproduction.commands)) {
      for (const cmd of commands) expect(repro, key).toContain(cmd);
      expect(repro).toContain(
        g.provenance.reproduction.recorded_in[
          key as keyof typeof g.provenance.reproduction.recorded_in
        ],
      );
    }
    // the contract records no commit / date — never inferred
    expect(fieldValue(missionG, "Source commit")).toBe("not recorded");
    expect(fieldValue(missionG, "Computation / restatement date")).toBe("not recorded");
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
    // execution provenance RECORDED in each publication comes from the payload
    const commits = fieldValue(missionJ, "Execution commits");
    const dates = fieldValue(missionJ, "Computation / restatement date");
    for (const key of ["j1b", "j2", "j3"] as const) {
      expect(commits, key).toContain(j.provenance.execution[key].execution_commit);
      expect(dates, key).toContain(j.provenance.execution[key].executed_at);
    }
    expect(dates).toContain("executed at (recorded)");
    // no Mission J publication records a reproduction command — never fabricated
    expect(fieldValue(missionJ, "Reproduce")).toBe("not recorded");
    const ceiling = fieldValue(missionJ, "Evidence ceiling");
    expect(ceiling.toLowerCase()).toContain("same-sample class b evidence");
    expect(ceiling.toLowerCase()).toContain("mechanism-consistent descriptive pattern");
    expect(ceiling).not.toContain("**");
  });

  it("keeps Mission G and Mission J as separate, unmerged lanes", () => {
    const g = missionGFixture();
    const j = missionJFixture();
    expect(flat(missionG)).not.toContain("J1B");
    expect(flat(missionJ)).not.toContain("G6_FROZEN_MANIFEST_READOUT");
    // each lane carries only its own provenance — no cross-lane hashes
    for (const src of Object.values(j.provenance.sources)) {
      expect(flat(missionG)).not.toContain(src.sha256);
    }
    for (const src of Object.values(g.provenance.sources)) {
      expect(flat(missionJ)).not.toContain(src.sha256);
    }
    expect(flat(manifest[0] as VerificationLane) + flat(missionG) + flat(missionJ)).not.toContain(
      "183",
    );
  });

  it("renders a pending contract lane as preparing, without hiding it", () => {
    const m = buildEvidenceVerificationManifest(pending, pending, pending);
    expect(m).toHaveLength(5);
    expect(m[1].availability).toBe("preparing tracked record");
    expect(m[2].availability).toBe("preparing tracked record");
    expect(m[3].availability).toBe("preparing tracked record");
    expect(fieldValue(m[1], "Source artifacts")).toBe("preparing tracked record");
    expect(fieldValue(m[2], "Source artifacts")).toBe("preparing tracked record");
    expect(fieldValue(m[3], "Evidence ceiling")).toBe("preparing tracked record");
    // static lanes stay fully available
    expect(m[0].availability).toBe("available — static tracked snapshot");
    expect(m[4].availability).toBe("available — static tracked snapshot");
  });

  it("renders an unavailable contract lane as record unavailable, without omission", () => {
    const m = buildEvidenceVerificationManifest(errored, errored, settledJ);
    expect(m).toHaveLength(5);
    expect(m[1].availability).toBe("record unavailable");
    expect(m[2].availability).toBe("record unavailable");
    expect(fieldValue(m[1], "Source artifacts")).toBe("record unavailable");
    expect(fieldValue(m[2], "Source artifacts")).toBe("record unavailable");
    expect(fieldValue(m[2], "Evidence ceiling")).toBe("record unavailable");
    // the sibling lane is untouched
    expect(m[3].availability).toBe("available — tracked contract");
    // the contract routes are app knowledge, not payload knowledge
    expect(fieldValue(m[1], "Contract")).toContain("GET /evidence/mission-g");
    expect(fieldValue(m[2], "Contract")).toContain("GET /evidence/mission-i");
  });

  it("never infers a Mission G commit or hash from anywhere", () => {
    for (const snapshot of [settledG, pending, errored]) {
      const m = buildEvidenceVerificationManifest(snapshot, settledI, settledJ);
      const commit = m[1].fields.find((f) => f.label === "Source commit")?.value ?? "";
      expect(["not recorded", "preparing tracked record", "record unavailable"]).toContain(commit);
      expect(commit).not.toMatch(/^[0-9a-f]{7,40}$/);
    }
  });

  it("never infers a Mission I computation date or commit from anywhere", () => {
    for (const snapshot of [settledI, pending, errored]) {
      const m = buildEvidenceVerificationManifest(settledG, snapshot, settledJ);
      for (const label of ["Computation dates", "Execution commits"]) {
        const value = m[2].fields.find((f) => f.label === label)?.value ?? "";
        expect(
          ["not recorded", "preparing tracked record", "record unavailable"],
          label,
        ).toContain(value);
        expect(value).not.toMatch(/^[0-9a-f]{7,40}$/);
        expect(value).not.toMatch(/\d{4}-\d{2}-\d{2}/);
      }
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
      buildEvidenceVerificationManifest(settledG, settledI, settledJ);
      buildEvidenceVerificationManifest(errored, pending, errored);
      expect(fetchSpy).not.toHaveBeenCalled();
      // node test env has no window/document — construction would have thrown
      expect(typeof globalThis.window).toBe("undefined");
      expect(typeof globalThis.document).toBe("undefined");
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
