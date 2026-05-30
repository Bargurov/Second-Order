/**
 * Pure-helper tests for EnginePhaseSummary.
 *
 * Covers the skip-empty contract documented in
 * ``engine-phase-summary.tsx``: each group must skip cleanly when its
 * data is empty, and ``hasAnyEnginePhaseContent`` decides whether the
 * wrapper card renders at all.
 *
 * No React mount — mirrors transmission-chain.test.ts.
 */
import { describe, expect, it } from "vitest";
import {
  hasAnyEnginePhaseContent,
  isActionabilityEmpty,
  isCounterfactualEmpty,
  isTimingEmpty,
} from "../engine-phase-summary";
import type { AnalysisDetail } from "@/lib/api";

const _BASE: AnalysisDetail = {
  what_changed: "x",
  mechanism_summary: "x",
  beneficiaries: [],
  losers: [],
  beneficiary_tickers: [],
  loser_tickers: [],
  assets_to_watch: [],
  confidence: "low",
};

describe("isActionabilityEmpty", () => {
  it("treats undefined / null / non-dict as empty", () => {
    expect(isActionabilityEmpty(undefined)).toBe(true);
    expect(isActionabilityEmpty(null)).toBe(true);
    expect(isActionabilityEmpty({})).toBe(true);
  });

  it("treats a populated dict as non-empty", () => {
    expect(isActionabilityEmpty({ tradable: false })).toBe(false);
    expect(isActionabilityEmpty({ why_tradable_or_not: "x" })).toBe(false);
  });

  it("treats a low_information populated block as non-empty", () => {
    // The engine composer ALWAYS populates the dict on low_information
    // — that read is exactly what the user needs to see ("not
    // decision-relevant because: insufficient evidence").  Skipping it
    // would hide the diagnostic.
    expect(
      isActionabilityEmpty({
        tradable: false,
        why_tradable_or_not: "low_information: insufficient",
        risk_level: "high",
      }),
    ).toBe(false);
  });
});

describe("isCounterfactualEmpty", () => {
  it("treats undefined / null / non-dict as empty", () => {
    expect(isCounterfactualEmpty(undefined)).toBe(true);
    expect(isCounterfactualEmpty(null)).toBe(true);
    expect(isCounterfactualEmpty({})).toBe(true);
  });

  it("treats a populated dict as non-empty", () => {
    expect(
      isCounterfactualEmpty({ what_should_not_happen: "x" }),
    ).toBe(false);
  });
});

describe("isTimingEmpty", () => {
  it("treats undefined / null / no-window dict as empty", () => {
    expect(isTimingEmpty(undefined)).toBe(true);
    expect(isTimingEmpty(null)).toBe(true);
    expect(isTimingEmpty({})).toBe(true);
  });

  it("treats any populated window field as non-empty", () => {
    expect(isTimingEmpty({ expected_reaction_window: "1d" })).toBe(false);
    expect(isTimingEmpty({ follow_through_window: "1-5d" })).toBe(false);
    expect(isTimingEmpty({ stale_after: "20d+" })).toBe(false);
    expect(isTimingEmpty({ timing_rationale: "stage=anticipation" })).toBe(false);
  });
});

describe("hasAnyEnginePhaseContent", () => {
  it("returns false on null / empty analysis", () => {
    expect(hasAnyEnginePhaseContent(null)).toBe(false);
    expect(hasAnyEnginePhaseContent(undefined)).toBe(false);
    expect(hasAnyEnginePhaseContent(_BASE)).toBe(false);
  });

  it("returns true when ANY engine-phase field is populated", () => {
    expect(
      hasAnyEnginePhaseContent({ ..._BASE, quality_tier: "actionable" }),
    ).toBe(true);
    expect(
      hasAnyEnginePhaseContent({ ..._BASE, quality_warnings: ["weak_mechanism"] }),
    ).toBe(true);
    expect(
      hasAnyEnginePhaseContent({
        ..._BASE,
        actionability_check: { tradable: true },
      }),
    ).toBe(true);
    expect(
      hasAnyEnginePhaseContent({
        ..._BASE,
        counterfactual_check: { what_should_not_happen: "x" },
      }),
    ).toBe(true);
    expect(
      hasAnyEnginePhaseContent({
        ..._BASE,
        thesis_timing: { expected_reaction_window: "1d" },
      }),
    ).toBe(true);
    expect(
      hasAnyEnginePhaseContent({
        ..._BASE,
        critical_breakpoints: [{ condition: "trigger" }],
      }),
    ).toBe(true);
    expect(
      hasAnyEnginePhaseContent({
        ..._BASE,
        evidence_sources: [{ field_used: "x", source_type: "y" }],
      }),
    ).toBe(true);
    expect(
      hasAnyEnginePhaseContent({ ..._BASE, confidence_rationale: "x" }),
    ).toBe(true);
    expect(
      hasAnyEnginePhaseContent({ ..._BASE, validation_rationale: "x" }),
    ).toBe(true);
    expect(
      hasAnyEnginePhaseContent({ ..._BASE, mechanism_subtype: "carry_unwind" }),
    ).toBe(true);
  });

  it("ignores whitespace-only rationale strings", () => {
    expect(
      hasAnyEnginePhaseContent({ ..._BASE, confidence_rationale: "   " }),
    ).toBe(false);
    expect(
      hasAnyEnginePhaseContent({ ..._BASE, validation_rationale: "\n" }),
    ).toBe(false);
  });

  it("returns false on the all-defaults shape decorate_full emits on a thin row", () => {
    // Mirrors the back-end default-shape: empty dicts / lists / strings
    // for every engine-phase field.  The wrapper must NOT render a
    // placeholder card on a row that has nothing engine-derived to say.
    expect(
      hasAnyEnginePhaseContent({
        ..._BASE,
        mechanism_subtype: null,
        quality_warnings: [],
        actionability_check: {},
        counterfactual_check: {},
        thesis_timing: {},
        critical_breakpoints: [],
        evidence_sources: [],
        confidence_rationale: "",
        validation_rationale: "",
      }),
    ).toBe(false);
  });
});
