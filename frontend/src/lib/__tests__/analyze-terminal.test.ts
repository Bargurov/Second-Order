/**
 * P2-2 — runtime terminal-payload validator contract
 * (`validateTerminalAnalyzePayload` in `src/lib/analyze-terminal.ts`).
 *
 * A `_phase === "complete"` label alone must not authorize completion. The
 * validator accepts exactly the three real backend-owned complete payloads
 * (normal success, cached success, handled mock/analysis_failed failure) and
 * rejects phase-only, structurally invalid, and wrong-typed payloads.
 */
import { describe, it, expect } from "vitest";
import { validateTerminalAnalyzePayload } from "../analyze-terminal";

const VALID_ANALYSIS = {
  what_changed: "Test change",
  mechanism_summary: "Test mechanism.",
  beneficiaries: ["A"],
  losers: ["B"],
  beneficiary_tickers: ["AAPL"],
  loser_tickers: ["MSFT"],
  assets_to_watch: ["AAPL"],
  confidence: "medium",
};
const MARKET = { note: "", details: {}, tickers: [] };

function success(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    _phase: "complete", headline: "h", stage: "initial", persistence: "short",
    analysis: { ...VALID_ANALYSIS }, market: { ...MARKET },
    is_mock: false, event_date: "2026-01-01", ...over,
  };
}
function failure(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    _phase: "complete", headline: "h", stage: "", persistence: "",
    analysis: {}, market: { ...MARKET },
    is_mock: true, analysis_failed: true, failure_reason: "overloaded",
    event_date: "2026-01-01", ...over,
  };
}

describe("validateTerminalAnalyzePayload — accepts real terminals", () => {
  it("accepts a normal success completion", () => {
    expect(validateTerminalAnalyzePayload(success())?.outcome).toBe("success");
  });
  it("accepts a success with event_date null (nullable contract)", () => {
    expect(validateTerminalAnalyzePayload(success({ event_date: null }))?.outcome).toBe("success");
  });
  it("accepts a success with empty beneficiaries/losers (low-signal)", () => {
    const v = validateTerminalAnalyzePayload(success({ analysis: { ...VALID_ANALYSIS, beneficiaries: [], losers: [] } }));
    expect(v?.outcome).toBe("success");
  });
  it("accepts a handled mock/analysis_failed failure with empty analysis", () => {
    expect(validateTerminalAnalyzePayload(failure())?.outcome).toBe("handled_failure");
  });
  it("accepts is_mock=true without analysis_failed as handled failure", () => {
    expect(validateTerminalAnalyzePayload(failure({ analysis_failed: undefined }))?.outcome).toBe("handled_failure");
  });
});

describe("validateTerminalAnalyzePayload — rejects invalid terminals", () => {
  it("rejects a phase-only complete payload", () => {
    expect(validateTerminalAnalyzePayload({ _phase: "complete" })).toBeNull();
  });
  it("rejects non-objects, null, and arrays", () => {
    expect(validateTerminalAnalyzePayload(null)).toBeNull();
    expect(validateTerminalAnalyzePayload("complete")).toBeNull();
    expect(validateTerminalAnalyzePayload([{ _phase: "complete" }])).toBeNull();
  });
  it("rejects the wrong _phase", () => {
    expect(validateTerminalAnalyzePayload(success({ _phase: "analysis" }))).toBeNull();
  });
  it("rejects a success missing analysis", () => {
    const p = success(); delete (p as Record<string, unknown>).analysis;
    expect(validateTerminalAnalyzePayload(p)).toBeNull();
  });
  it("rejects a success whose analysis is an empty object", () => {
    expect(validateTerminalAnalyzePayload(success({ analysis: {} }))).toBeNull();
  });
  it("rejects a success whose analysis is malformed (array / string)", () => {
    expect(validateTerminalAnalyzePayload(success({ analysis: [] }))).toBeNull();
    expect(validateTerminalAnalyzePayload(success({ analysis: "nope" }))).toBeNull();
  });
  it("rejects a success whose analysis lacks confidence/beneficiaries/losers", () => {
    expect(validateTerminalAnalyzePayload(success({ analysis: { beneficiaries: [], losers: [] } }))).toBeNull();
    expect(validateTerminalAnalyzePayload(success({ analysis: { confidence: "low", losers: [] } }))).toBeNull();
    expect(validateTerminalAnalyzePayload(success({ analysis: { confidence: "low", beneficiaries: [] } }))).toBeNull();
  });
  it("rejects a success missing identity/status fields", () => {
    const noHeadline = success(); delete (noHeadline as Record<string, unknown>).headline;
    expect(validateTerminalAnalyzePayload(noHeadline)).toBeNull();
    const noStage = success(); delete (noStage as Record<string, unknown>).stage;
    expect(validateTerminalAnalyzePayload(noStage)).toBeNull();
    const noIsMock = success(); delete (noIsMock as Record<string, unknown>).is_mock;
    expect(validateTerminalAnalyzePayload(noIsMock)).toBeNull();
    const noDate = success(); delete (noDate as Record<string, unknown>).event_date;
    expect(validateTerminalAnalyzePayload(noDate)).toBeNull();
  });
  it("rejects wrong field types", () => {
    expect(validateTerminalAnalyzePayload(success({ is_mock: "false" }))).toBeNull();
    expect(validateTerminalAnalyzePayload(success({ event_date: 20260101 }))).toBeNull();
    expect(validateTerminalAnalyzePayload(success({ market: "n/a" }))).toBeNull();
    expect(validateTerminalAnalyzePayload(success({ headline: "" }))).toBeNull();
    expect(validateTerminalAnalyzePayload(success({ analysis: { ...VALID_ANALYSIS, confidence: 3 } }))).toBeNull();
  });
  it("rejects a handled failure missing/empty failure_reason", () => {
    const noReason = failure(); delete (noReason as Record<string, unknown>).failure_reason;
    expect(validateTerminalAnalyzePayload(noReason)).toBeNull();
    expect(validateTerminalAnalyzePayload(failure({ failure_reason: "" }))).toBeNull();
  });
});
