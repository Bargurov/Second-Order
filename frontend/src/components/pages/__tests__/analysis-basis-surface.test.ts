/**
 * analysis-basis-surface.test.ts — A1-2 Analysis Basis wiring.
 *
 * Source-level scans in the style of the existing surface tests: they pin the
 * wiring the pure-logic suite (lib/analysis-provenance) cannot see from
 * outside the component — that the section is fed by the validator, that each
 * honest state is rendered distinctly, that the captured basis is inspectable
 * without a raw JSON dump, and that nothing on this surface can start a run.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const view = () =>
  readFileSync(resolve(__dirname, "..", "analysis-view.tsx"), "utf-8");

describe("Analysis Basis is fed by the fail-closed validator", () => {
  it("parses the payload rather than reading it raw", () => {
    const src = view();
    expect(src).toMatch(/parseProvenance\(result\.provenance\)/);
    expect(src).toContain("AnalysisBasisSection");
  });

  it("renders nothing when no provenance was received", () => {
    expect(view()).toMatch(/if \(!provenance\) return null;/);
  });
});

describe("every honest state is distinguishable", () => {
  it("names the legacy state without inventing a basis", () => {
    expect(view()).toContain(
      "Analysis provenance was not captured for this earlier record.");
  });

  it("shows a restrained integrity warning for an invalid basis", () => {
    const src = view();
    expect(src).toMatch(/did not pass its integrity/);
    expect(src).toMatch(/text-error/);
  });

  it("names the changed dimensions on a stale basis and says nothing re-ran", () => {
    const src = view();
    expect(src).toMatch(/changedDimensions\.map\(changedDimensionLabel\)/);
    expect(src).toMatch(/nothing was re-run/);
  });

  it("labels the status through the shared label map", () => {
    expect(view()).toMatch(/provenanceLabel\(status\)/);
  });
});

describe("the captured basis is inspectable, not dumped", () => {
  it("hides the captured context and records behind an explicit control", () => {
    const src = view();
    expect(src).toMatch(/Inspect captured basis/);
    expect(src).toMatch(/useState\(false\)/);
  });

  it("renders records as identities, never as a raw JSON blob", () => {
    const src = view();
    const section = src.slice(src.indexOf("function AnalysisBasisSection"));
    expect(section).not.toMatch(/JSON\.stringify/);
  });
});

describe("the basis never claims more than it records", () => {
  it("states the non-claim unconditionally", () => {
    const src = view();
    const section = src.slice(src.indexOf("function AnalysisBasisSection"));
    expect(section).toContain("PROVENANCE_NON_CLAIM");
  });

  it("offers no re-analysis control on the basis section", () => {
    const src = view();
    const section = src.slice(src.indexOf("function AnalysisBasisSection"));
    // Absence of a CONTROL, not absence of words: the section legitimately
    // tells the operator that "nothing was re-run", so a prose scan would
    // flag the very disclosure it is meant to protect.  Assert instead that
    // the only interactive handler is the disclosure toggle, and that no
    // request or submit seam is reachable from here.
    const handlers = section.match(/onClick=\{[^}]*\}/g) ?? [];
    expect(handlers).toEqual(['onClick={() => setOpen((v) => !v)}']);
    expect(section).not.toMatch(/api\.analyze/);
    expect(section).not.toMatch(/submit\(/);
  });
});
