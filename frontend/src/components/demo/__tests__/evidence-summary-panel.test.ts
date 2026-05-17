/**
 * Unit tests for evidence-summary-panel pure helpers.
 *
 * The panel is presentational — most logic lives in the
 * ``pickAdvisories`` / ``benchmarkIncludesEvent60`` helpers and in
 * the pinned ``COPY`` / ``LABELS`` string tables.  These tests sweep
 * the helpers and verify conservative-language constraints without
 * rendering the React tree.
 */

import { describe, it, expect } from "vitest";

import {
  COPY,
  LABELS,
  benchmarkIncludesEvent60,
  formatLimitationText,
  pickAdvisories,
  type BenchmarkSensitivityStatus,
} from "../evidence-summary-panel";

// ---------------------------------------------------------------------------
// Fixture helpers
// ---------------------------------------------------------------------------

function bench(
  overrides: Partial<BenchmarkSensitivityStatus> = {},
): BenchmarkSensitivityStatus {
  return {
    status: "comparison_available",
    changed_event_ids: [],
    unchanged_event_ids: [],
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// pickAdvisories — pinned copy trigger conditions
// ---------------------------------------------------------------------------

describe("pickAdvisories", () => {
  it("surfaces the FDR-zero advisory when fdr_significant_count is 0", () => {
    const advisories = pickAdvisories({
      fdr_significant_count: 0,
      raw_p_candidate_count: 0,
      benchmark_sensitivity_status: bench(),
    });
    const texts = advisories.map((a) => a.text);
    expect(texts).toContain(COPY.fdrZero);
  });

  it("omits the FDR-zero advisory when fdr_significant_count > 0", () => {
    const advisories = pickAdvisories({
      fdr_significant_count: 2,
      raw_p_candidate_count: 0,
      benchmark_sensitivity_status: bench(),
    });
    const texts = advisories.map((a) => a.text);
    expect(texts).not.toContain(COPY.fdrZero);
  });

  it("surfaces the raw-p caveat when raw_p_candidate_count > 0", () => {
    const advisories = pickAdvisories({
      fdr_significant_count: 1,
      raw_p_candidate_count: 4,
      benchmark_sensitivity_status: bench(),
    });
    const texts = advisories.map((a) => a.text);
    expect(texts).toContain(COPY.rawPCaveat);
  });

  it("omits the raw-p caveat when raw_p_candidate_count == 0", () => {
    const advisories = pickAdvisories({
      fdr_significant_count: 1,
      raw_p_candidate_count: 0,
      benchmark_sensitivity_status: bench(),
    });
    const texts = advisories.map((a) => a.text);
    expect(texts).not.toContain(COPY.rawPCaveat);
  });

  it("surfaces the event-60 advisory when 60 is in changed_event_ids", () => {
    const advisories = pickAdvisories({
      fdr_significant_count: 1,
      raw_p_candidate_count: 0,
      benchmark_sensitivity_status: bench({ changed_event_ids: [60] }),
    });
    const texts = advisories.map((a) => a.text);
    expect(texts).toContain(COPY.event60);
  });

  it("omits the event-60 advisory when 60 is not in changed_event_ids", () => {
    const advisories = pickAdvisories({
      fdr_significant_count: 1,
      raw_p_candidate_count: 0,
      benchmark_sensitivity_status: bench({ changed_event_ids: [73, 88] }),
    });
    const texts = advisories.map((a) => a.text);
    expect(texts).not.toContain(COPY.event60);
  });

  it("returns all three advisories together when every trigger applies", () => {
    const advisories = pickAdvisories({
      fdr_significant_count: 0,
      raw_p_candidate_count: 4,
      benchmark_sensitivity_status: bench({ changed_event_ids: [60] }),
    });
    const keys = advisories.map((a) => a.key);
    expect(keys).toEqual(["fdr_zero", "raw_p", "event_60"]);
  });

  it("returns an empty list when no trigger applies", () => {
    const advisories = pickAdvisories({
      fdr_significant_count: 2,
      raw_p_candidate_count: 0,
      benchmark_sensitivity_status: bench({ changed_event_ids: [] }),
    });
    expect(advisories).toEqual([]);
  });

  it("tolerates missing benchmark block", () => {
    const advisories = pickAdvisories({
      fdr_significant_count: 0,
      raw_p_candidate_count: 0,
      benchmark_sensitivity_status: null,
    });
    expect(advisories.map((a) => a.key)).toEqual(["fdr_zero"]);
  });
});

// ---------------------------------------------------------------------------
// benchmarkIncludesEvent60 — narrow predicate, but the panel relies
// on it for one of its pinned copy triggers.
// ---------------------------------------------------------------------------

describe("benchmarkIncludesEvent60", () => {
  it("returns true when 60 is in changed_event_ids", () => {
    expect(benchmarkIncludesEvent60({ changed_event_ids: [60, 73] })).toBe(true);
  });

  it("returns false when 60 is missing", () => {
    expect(benchmarkIncludesEvent60({ changed_event_ids: [42, 73] })).toBe(false);
  });

  it("returns false on null / undefined", () => {
    expect(benchmarkIncludesEvent60(null)).toBe(false);
    expect(benchmarkIncludesEvent60(undefined)).toBe(false);
  });

  it("returns false when changed_event_ids is missing", () => {
    expect(benchmarkIncludesEvent60({})).toBe(false);
  });

  it("returns false when changed_event_ids is not an array", () => {
    expect(
      benchmarkIncludesEvent60({
        changed_event_ids: "60" as unknown as number[],
      }),
    ).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// formatLimitationText - visible caveat wording
// ---------------------------------------------------------------------------

describe("formatLimitationText", () => {
  it("removes validation-claim phrasing from displayed artifact caveats", () => {
    const text = formatLimitationText(
      "no FDR-significant validation claim is supported by this evidence set",
    );
    expect(text).toBe(
      "no FDR-significant claim is supported by this evidence set",
    );
    expect(text.toLowerCase()).not.toContain("validation");
    expect(text.toLowerCase()).not.toContain("validated");
  });

  it("preserves unrelated limitations", () => {
    const text = "raw-p candidate signals are not FDR-significant";
    expect(formatLimitationText(text)).toBe(text);
  });
});

// ---------------------------------------------------------------------------
// Conservative-language sweep — every user-facing string the panel
// emits must avoid the banned overclaim tokens.
// ---------------------------------------------------------------------------

const _BANNED_TOKENS = ["proven", "validated", "alpha", "causal"] as const;

function allUserFacingStrings(): string[] {
  return [
    ...Object.values(COPY),
    ...Object.values(LABELS),
  ];
}

describe("conservative language", () => {
  for (const token of _BANNED_TOKENS) {
    it(`no user-facing string contains the banned token "${token}"`, () => {
      const offenders = allUserFacingStrings()
        .filter((s) => s.toLowerCase().includes(token));
      expect(offenders, `banned token "${token}" leaked into: ${offenders.join(" | ")}`)
        .toEqual([]);
    });
  }

  it("FDR-zero copy matches the task-pinned wording exactly", () => {
    expect(COPY.fdrZero).toBe(
      "No FDR-significant results in this pilot cohort.",
    );
  });

  it("raw-p caveat matches the task-pinned wording exactly", () => {
    expect(COPY.rawPCaveat).toBe(
      "Raw-p candidates did not necessarily survive FDR.",
    );
  });

  it("event-60 copy matches the task-pinned wording exactly", () => {
    expect(COPY.event60).toBe(
      "Event 60 changes descriptive interpretation under XLE vs SPY.",
    );
  });

  it("FDR vs raw-p distinction is preserved in the pinned vocabulary", () => {
    // Both strings must mention FDR explicitly so the reader sees the
    // distinction; the raw-p string says "did not necessarily survive",
    // never "validated" or equivalent.
    expect(COPY.fdrZero.includes("FDR")).toBe(true);
    expect(COPY.rawPCaveat.includes("FDR")).toBe(true);
    expect(COPY.rawPCaveat.toLowerCase().includes("raw-p")).toBe(true);
  });
});
