/**
 * Tests for the mock/failure detection logic in the Analysis View.
 *
 * The SSE handler checks `analysis_failed` on the response object to
 * decide between rendering the error state vs the analysis panels.
 * These tests verify the contract the frontend relies on.
 */

import { describe, it, expect } from "vitest";
import type { AnalyzeResponse } from "@/lib/api";

/** Simulate the detection logic from the SSE "complete" handler. */
function shouldShowFailure(resp: Partial<AnalyzeResponse>): boolean {
  return resp.analysis_failed === true;
}

describe("mock failure detection", () => {
  it("detects analysis_failed response", () => {
    expect(shouldShowFailure({
      headline: "Test",
      is_mock: true,
      analysis_failed: true,
      failure_reason: "overloaded",
    })).toBe(true);
  });

  it("does not flag healthy response", () => {
    expect(shouldShowFailure({
      headline: "Test",
      is_mock: false,
      analysis_failed: undefined,
    })).toBe(false);
  });

  it("does not flag when analysis_failed is false", () => {
    expect(shouldShowFailure({
      headline: "Test",
      is_mock: false,
      analysis_failed: false,
    })).toBe(false);
  });

  it("does not flag when field is missing", () => {
    expect(shouldShowFailure({
      headline: "Test",
      is_mock: false,
    })).toBe(false);
  });

  it("failure_reason is accessible on failed response", () => {
    const resp: Partial<AnalyzeResponse> = {
      analysis_failed: true,
      failure_reason: "no API key",
    };
    expect(resp.failure_reason).toBe("no API key");
  });

  it("is_mock true without analysis_failed does not trigger failure", () => {
    // Legacy cached response that has is_mock but not analysis_failed
    expect(shouldShowFailure({
      is_mock: true,
      analysis_failed: undefined,
    })).toBe(false);
  });
});
