/**
 * export.test.ts — deterministic export + fail-closed import (spec items 17–18).
 */
import { describe, expect, it } from "vitest";

import { NON_CLAIM } from "../types";
import { validateBrief } from "../validate";
import { canonicalizeBrief, exportBriefJson, exportBriefMarkdown, importBriefJson } from "../export";
import { validBriefFixture } from "./fixture";

const TS = "2026-03-19T00:00:00Z";

describe("JSON export — deterministic + complete (spec 18)", () => {
  it("produces byte-identical output for identical input", () => {
    const b = validBriefFixture();
    expect(exportBriefJson(b, TS)).toBe(exportBriefJson(b, TS));
  });

  it("is independent of the input object's key order", () => {
    const a = validBriefFixture();
    // Rebuild with keys inserted in reverse order — same data, shuffled keys.
    const shuffled = Object.fromEntries(Object.entries(a).reverse()) as typeof a;
    expect(exportBriefJson(shuffled, TS)).toBe(exportBriefJson(a, TS));
  });

  it("carries the schema version, non-claim, revision log and export timestamp", () => {
    const json = exportBriefJson(validBriefFixture(), TS);
    const parsed = JSON.parse(json);
    expect(parsed.schema_version).toBe("live-event-brief-v1");
    expect(parsed.non_claim).toBe(NON_CLAIM);
    expect(parsed.revision_log.length).toBeGreaterThan(0);
    expect(parsed.exported_at).toBe(TS);
    expect(parsed.mechanism_hypotheses.length).toBeGreaterThan(0);
    expect(parsed.falsifiers.length).toBeGreaterThan(0);
    expect(parsed.follow_up_checks.length).toBeGreaterThan(0);
  });
});

describe("JSON import — round-trip + fail-closed (spec 17)", () => {
  it("round-trips a valid export back to the canonical brief", () => {
    const b = validBriefFixture();
    const r = importBriefJson(exportBriefJson(b, TS));
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.brief).toEqual(canonicalizeBrief(b));
      // The stray export timestamp is not persisted onto the brief.
      expect((r.brief as Record<string, unknown>).exported_at).toBeUndefined();
    }
  });

  it("rejects non-JSON without throwing", () => {
    const r = importBriefJson("{ not json");
    expect(r.ok).toBe(false);
  });

  it("rejects an out-of-contract brief (missing non-claim / wrong version)", () => {
    expect(importBriefJson(JSON.stringify({ ...validBriefFixture(), non_claim: "x" })).ok).toBe(false);
    expect(importBriefJson(JSON.stringify({ ...validBriefFixture(), schema_version: "v2" })).ok).toBe(false);
  });

  it("a malformed import preserves the existing briefs (caller keeps its list)", () => {
    const existing = [validBriefFixture()];
    const r = importBriefJson("garbage");
    // Fail-closed: the caller only replaces on ok, so existing is untouched.
    const next = r.ok ? [r.brief] : existing;
    expect(next).toBe(existing);
    expect(validateBrief(next[0]).ok).toBe(true);
  });
});

describe("Markdown export — deterministic + visible missingness", () => {
  const md = exportBriefMarkdown(validBriefFixture(), TS);

  it("is byte-identical for identical input", () => {
    expect(exportBriefMarkdown(validBriefFixture(), TS)).toBe(md);
  });

  it("renders every required section and the non-claim + disclaimer", () => {
    for (const heading of [
      "## Sources",
      "## Facts, interpretations & unknowns",
      "## What changed?",
      "## Known unknowns",
      "## Competing mechanism hypotheses",
      "## Asset-role map",
      "## Market-reaction observations",
      "## Historical research context",
      "## Falsifiers",
      "## Follow-up plan",
      "## Revision log",
      "## Claim ceiling",
      "## Non-claim",
    ]) {
      expect(md).toContain(heading);
    }
    expect(md).toContain(NON_CLAIM);
    expect(md).toContain("Historical context is descriptive and does not classify or forecast this live event.");
    expect(md).toContain(`Exported ${TS}`);
  });

  it("shows a missing reaction value as 'unavailable', not omitted", () => {
    expect(md).toContain("unavailable");
  });

  it("labels each typed entry with its type", () => {
    expect(md).toContain("**[FACT]**");
    expect(md).toContain("**[INTERPRETATION]**");
    expect(md).toContain("**[UNKNOWN]**");
  });

  it("shows the no-comparable-cohort line when the operator declares NONE", () => {
    const none = exportBriefMarkdown({ ...validBriefFixture(), historical_context: { comparable_cohort: "NONE", notes: "" } }, TS);
    expect(none).toContain("No directly comparable published Second Order cohort is available.");
  });
});
