/**
 * V1 — provenance parity across the reviewer guide and the research-record
 * memo.
 *
 * The verification manifest (evidence-reader-guide) and the Markdown
 * provenance appendix (research-record-memo) render the SAME canonical
 * provenance: the same source artifacts, hashes, recorded commits/dates,
 * and reproduction commands, with genuinely missing fields saying
 * "not recorded" on both surfaces.  Nothing here is inferred from Git
 * HEAD, filenames, or the clock: every hex hash the two surfaces render
 * must be traceable to a contract payload or a canonical static constant.
 * Reproduction commands stay inert display strings.
 */
import { describe, expect, it } from "vitest";

import { buildEvidenceVerificationManifest, type VerificationLane } from "../evidence-reader-guide";
import { buildResearchRecordMemo } from "../research-record-memo";
import { ACCEPTED_CORPUS as AC, FAMILY_COVERAGE as FC } from "../accepted-corpus";
import { EFFECTIVE_INDEPENDENT_EVIDENCE as EIE } from "../effective-independent-evidence";
import { MECHANISM_FAMILY_EVIDENCE as MFE } from "../mechanism-family-evidence";
import { REPRESENTATIVE_CASE_LIBRARY as RCL } from "../representative-case-library";
import { missionGFixture } from "@/components/ui/__tests__/mission-g-fixture";
import { missionIFixture } from "@/components/ui/__tests__/mission-i-fixture";
import { missionJFixture } from "@/components/ui/__tests__/mission-j-fixture";

const g = missionGFixture();
const i = missionIFixture();
const j = missionJFixture();

const manifest = buildEvidenceVerificationManifest(
  { isPending: false, isError: false, data: g },
  { isPending: false, isError: false, data: i },
  { isPending: false, isError: false, data: j },
);
const [accepted, missionG, missionI, missionJ, staticEvidence] = manifest;

const memo = buildResearchRecordMemo({
  missionG: { available: true, data: g },
  missionI: { available: true, data: i },
  missionJ: { available: true, data: j },
});

function fieldValue(lane: VerificationLane, label: string): string {
  const f = lane.fields.find((x) => x.label === label);
  expect(f, `${lane.lane}: ${label}`).toBeDefined();
  return f!.value;
}

/** The memo's provenance appendix (section 12) alone. */
const appendix = memo.slice(
  memo.indexOf("## 12. Provenance and reproduction appendix"),
  memo.indexOf("## 13. Final non-claims"),
);

describe("provenance parity — accepted archive lane", () => {
  it("renders the same two safe reproduction commands on both surfaces", () => {
    expect(fieldValue(accepted, "Reproduce (any-support OR-rule ledger)")).toBe(AC.orRuleRepro);
    expect(fieldValue(accepted, "Reproduce (directional-majority ledger)")).toBe(
      AC.directionalMajority.repro,
    );
    expect(appendix).toContain(`\`${AC.orRuleRepro}\``);
    expect(appendix).toContain(`\`${AC.directionalMajority.repro}\``);
  });

  it("advertises only non-initializing read-only commands", () => {
    expect(AC.orRuleRepro).not.toContain("init_db");
    expect(AC.orRuleRepro).toContain("scripts/track_record_report.py");
    expect(memo).not.toContain("init_db");
  });

  it("keeps the unrecorded source document / commit honest on both surfaces", () => {
    expect(fieldValue(accepted, "Source document")).toContain("not recorded");
    expect(fieldValue(accepted, "Source commit")).toBe("not recorded");
    expect(appendix).toContain("- Source commit: not recorded");
  });
});

describe("provenance parity — Mission G lane", () => {
  it("renders every request-time artifact hash on both surfaces", () => {
    const hashes = fieldValue(missionG, "Artifact hashes");
    for (const src of Object.values(g.provenance.sources)) {
      expect(hashes).toContain(src.artifact);
      expect(hashes).toContain(src.sha256);
      expect(appendix).toContain(src.sha256);
    }
  });

  it("renders every recorded reproduction command on both surfaces", () => {
    const repro = fieldValue(missionG, "Reproduce");
    for (const commands of Object.values(g.provenance.reproduction.commands)) {
      for (const cmd of commands) {
        expect(repro).toContain(cmd);
        expect(appendix).toContain(cmd);
      }
    }
  });

  it("keeps the genuinely unrecorded commit / date honest on both surfaces", () => {
    expect(g.provenance.execution_commits).toBeNull();
    expect(g.provenance.computation_dates).toBeNull();
    expect(fieldValue(missionG, "Source commit")).toBe("not recorded");
    expect(fieldValue(missionG, "Computation / restatement date")).toBe("not recorded");
    const gAppendix = appendix.slice(
      appendix.indexOf("### Mission G historical record"),
      appendix.indexOf("### Mission I published record"),
    );
    expect(gAppendix).toContain("- Source commit: not recorded");
    expect(gAppendix).toContain("- Computation / restatement date: not recorded");
  });
});

describe("provenance parity — Mission I lane (honest nulls preserved)", () => {
  it("renders the recorded I2A reproduction path on both surfaces", () => {
    const repro = fieldValue(missionI, "Reproduce");
    for (const cmd of i.provenance.reproduction.commands) {
      expect(repro).toContain(cmd);
      expect(appendix).toContain(cmd);
    }
    expect(repro).toContain(i.provenance.reproduction.source);
  });

  it("keeps computation dates and execution commits null and 'not recorded' everywhere", () => {
    expect(i.provenance.computation_dates).toBeNull();
    expect(i.provenance.execution_commits).toBeNull();
    expect(fieldValue(missionI, "Computation dates")).toBe("not recorded");
    expect(fieldValue(missionI, "Execution commits")).toBe("not recorded");
    const iAppendix = appendix.slice(
      appendix.indexOf("### Mission I published record"),
      appendix.indexOf("### Mission J published record"),
    );
    expect(iAppendix).toContain("- Computation dates: not recorded");
    expect(iAppendix).toContain("- Execution commits: not recorded");
  });
});

describe("provenance parity — Mission J lane", () => {
  it("renders every recorded execution commit and timestamp on both surfaces", () => {
    const commits = fieldValue(missionJ, "Execution commits");
    const dates = fieldValue(missionJ, "Computation / restatement date");
    for (const [key, exec] of Object.entries(j.provenance.execution)) {
      expect(commits, key).toContain(exec.execution_commit);
      expect(dates, key).toContain(exec.executed_at);
      expect(appendix).toContain(exec.execution_commit);
      expect(appendix).toContain(exec.executed_at);
    }
  });

  it("keeps the genuinely unrecorded Mission J reproduction honest on both surfaces", () => {
    expect(j.provenance.reproduction).toBeNull();
    expect(fieldValue(missionJ, "Reproduce")).toBe("not recorded");
    const jAppendix = appendix.slice(appendix.indexOf("### Mission J published record"));
    expect(jAppendix).toContain("- Reproduction command: not recorded");
  });
});

describe("provenance parity — static / representative lanes", () => {
  it("renders the recorded F1/F2 reproduction commands on both surfaces", () => {
    const repro = fieldValue(staticEvidence, "Reproduce (representative cases)");
    for (const cmd of RCL.reproCommands) {
      expect(repro).toContain(cmd);
      expect(appendix).toContain(cmd);
    }
    expect(repro).not.toBe("not recorded");
  });

  it("renders the recorded shortlist baseline commit for family coverage on both surfaces", () => {
    const coverage = fieldValue(staticEvidence, "Family coverage (AZ1)");
    expect(coverage).toContain(FC.shortlistBaselineCommit);
    expect(coverage).toContain(FC.shortlistNote);
    expect(appendix).toContain(FC.shortlistBaselineCommit);
  });

  it("renders the K2 / E1 source commits and commands on both surfaces", () => {
    expect(fieldValue(staticEvidence, "Independence caution (K2)")).toContain(EIE.sourceCommit);
    expect(fieldValue(staticEvidence, "Family inventory (E1)")).toContain(MFE.sourceCommit);
    for (const [doc, commit, cmd] of [
      [EIE.sourceDoc, EIE.sourceCommit, EIE.reproCommand],
      [MFE.sourceDoc, MFE.sourceCommit, MFE.reproCommand],
    ] as const) {
      expect(appendix).toContain(doc);
      expect(appendix).toContain(commit);
      expect(appendix).toContain(`\`${cmd}\``);
    }
    expect(fieldValue(staticEvidence, "Representative cases (F1/F2)")).toContain(
      RCL.sourceCommit,
    );
    expect(appendix).toContain(RCL.sourceCommit);
  });
});

describe("provenance parity — global honesty invariants", () => {
  it("never renders a hex hash that is not traceable to a payload or canonical constant", () => {
    const allowed = new Set<string>([
      ...Object.values(g.provenance.sources).map((s) => s.sha256),
      ...Object.values(i.provenance.sources).map((s) => s.sha256),
      ...Object.values(j.provenance.sources).map((s) => s.sha256),
      ...Object.values(j.provenance.execution).map((e) => e.execution_commit),
      EIE.sourceCommit,
      MFE.sourceCommit,
      RCL.sourceCommit,
      FC.shortlistBaselineCommit,
    ]);
    const surfaces = [JSON.stringify(manifest), memo];
    // Hash-like: 7-64 hex chars with at least one a-f letter (pure-digit
    // tokens are seeds / dates / counts, not commits or digests).
    const hashLike = /\b(?=[0-9a-f]*[a-f])[0-9a-f]{7,64}\b/g;
    for (const surface of surfaces) {
      for (const hex of surface.match(hashLike) ?? []) {
        expect(allowed.has(hex), `untraceable hash-like token: ${hex}`).toBe(true);
      }
    }
  });

  it("keeps reproduction commands as inert python display strings", () => {
    for (const lane of manifest) {
      for (const f of lane.fields) {
        if (f.label.startsWith("Reproduce") && f.value !== "not recorded") {
          expect(f.code, `${lane.lane}: ${f.label}`).toBe(true);
          expect(f.value).toMatch(/^python/);
        }
      }
    }
  });

  it("changes no denominator and no claim ceiling", () => {
    expect(accepted.scope).toContain(String(AC.trackRecordTotal));
    expect(missionG.scope).toContain(String(g.lanes.historical.total));
    expect(fieldValue(missionG, "Evidence ceiling")).toBe(g.non_claims[0]);
    expect(fieldValue(missionI, "Evidence ceiling")).toBe(
      i.calibration.interpretation_ceiling,
    );
    expect(memo).toContain(
      `Two named outcome lenses over the same ${AC.trackRecordTotal} accepted track-record rows`,
    );
  });
});
