/**
 * Tests for failed-analysis row state and retry path logic.
 *
 * Covers three invariants:
 *   1) deriveRowState — failed/normal classification is correct.
 *   2) Trigger condition — which AnalyzeResponse shapes mark a headline failed.
 *   3) Retry / clear path — success clears the failed set; re-fail re-adds.
 *
 * Pure function tests — no component rendering, no React dependencies.
 */

import { describe, it, expect } from "vitest";
import { deriveRowState } from "../headlines-page";
import type { AnalyzeResponse } from "@/lib/api";

// ---------------------------------------------------------------------------
// 1) deriveRowState — row state classification
// ---------------------------------------------------------------------------

describe("deriveRowState — failed row state", () => {
  it("returns 'failed' when headline is in the failed set", () => {
    const failed = new Set(["Fed hikes rates by 50bp"]);
    expect(deriveRowState("Fed hikes rates by 50bp", failed)).toBe("failed");
  });

  it("returns 'normal' when headline is not in the failed set", () => {
    const failed = new Set(["Other headline"]);
    expect(deriveRowState("Fed hikes rates by 50bp", failed)).toBe("normal");
  });

  it("returns 'normal' when failed set is empty", () => {
    expect(deriveRowState("Fed hikes rates by 50bp", new Set())).toBe("normal");
  });

  it("returns 'normal' when failedHeadlines is undefined", () => {
    expect(deriveRowState("Fed hikes rates by 50bp", undefined)).toBe("normal");
  });

  it("match is exact — substring does not trigger failed state", () => {
    const failed = new Set(["Fed hikes"]);
    expect(deriveRowState("Fed hikes rates by 50bp", failed)).toBe("normal");
  });

  it("match is case-sensitive", () => {
    const failed = new Set(["fed hikes rates by 50bp"]);
    expect(deriveRowState("Fed hikes rates by 50bp", failed)).toBe("normal");
  });

  it("multiple headlines — only the matching one is failed", () => {
    const failed = new Set(["Oil surges on OPEC cut"]);
    expect(deriveRowState("Fed hikes rates by 50bp", failed)).toBe("normal");
    expect(deriveRowState("Oil surges on OPEC cut", failed)).toBe("failed");
  });
});

// ---------------------------------------------------------------------------
// 2) Trigger condition — which responses mark a headline failed
// ---------------------------------------------------------------------------

/** Mirror the condition from analysis-view submit() "complete" handler. */
function shouldMarkFailed(resp: Partial<AnalyzeResponse>): boolean {
  return resp.analysis_failed === true || resp.is_mock === true;
}

/** Mirror the condition for success (clears failed state). */
function shouldMarkSucceeded(resp: Partial<AnalyzeResponse>): boolean {
  return resp.analysis_failed !== true && resp.is_mock !== true;
}

describe("trigger condition — which responses fire onAnalysisFailed", () => {
  it("fires on analysis_failed=true", () => {
    expect(shouldMarkFailed({ analysis_failed: true, is_mock: false })).toBe(true);
  });

  it("fires on is_mock=true", () => {
    expect(shouldMarkFailed({ analysis_failed: false, is_mock: true })).toBe(true);
  });

  it("fires when both analysis_failed and is_mock are true", () => {
    expect(shouldMarkFailed({ analysis_failed: true, is_mock: true })).toBe(true);
  });

  it("does not fire on healthy response", () => {
    expect(shouldMarkFailed({ analysis_failed: false, is_mock: false })).toBe(false);
  });

  it("does not fire when both fields are absent", () => {
    expect(shouldMarkFailed({ headline: "Test" })).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 3) Retry / clear path — Set mutation logic
// ---------------------------------------------------------------------------

/** Simulate handleAnalysisFailed — add to set. */
function addToFailed(prev: Set<string>, headline: string): Set<string> {
  const next = new Set(prev);
  next.add(headline);
  return next;
}

/** Simulate handleAnalysisSucceeded — remove from set (no-op if absent). */
function removeFromFailed(prev: Set<string>, headline: string): Set<string> {
  if (!prev.has(headline)) return prev;
  const next = new Set(prev);
  next.delete(headline);
  return next;
}

describe("retry path — Set mutation for failed/clear cycle", () => {
  it("adding a headline marks it failed", () => {
    const set = addToFailed(new Set(), "Fed hikes rates by 50bp");
    expect(set.has("Fed hikes rates by 50bp")).toBe(true);
    expect(deriveRowState("Fed hikes rates by 50bp", set)).toBe("failed");
  });

  it("successful retry clears the headline from failed set", () => {
    const withFail = addToFailed(new Set(), "Fed hikes rates by 50bp");
    const cleared = removeFromFailed(withFail, "Fed hikes rates by 50bp");
    expect(cleared.has("Fed hikes rates by 50bp")).toBe(false);
    expect(deriveRowState("Fed hikes rates by 50bp", cleared)).toBe("normal");
  });

  it("removeFromFailed is a no-op when headline was never failed", () => {
    const before = new Set(["Other"]);
    const after = removeFromFailed(before, "Fed hikes rates by 50bp");
    // Returns the same reference — no new set allocated
    expect(after).toBe(before);
  });

  it("re-failing a cleared headline adds it back", () => {
    const withFail = addToFailed(new Set(), "Fed hikes rates by 50bp");
    const cleared = removeFromFailed(withFail, "Fed hikes rates by 50bp");
    const refailed = addToFailed(cleared, "Fed hikes rates by 50bp");
    expect(refailed.has("Fed hikes rates by 50bp")).toBe(true);
    expect(deriveRowState("Fed hikes rates by 50bp", refailed)).toBe("failed");
  });

  it("clearing one headline does not affect others", () => {
    let set = addToFailed(new Set(), "Fed hikes rates by 50bp");
    set = addToFailed(set, "Oil surges on OPEC cut");
    set = removeFromFailed(set, "Fed hikes rates by 50bp");
    expect(deriveRowState("Fed hikes rates by 50bp", set)).toBe("normal");
    expect(deriveRowState("Oil surges on OPEC cut", set)).toBe("failed");
  });
});

// ---------------------------------------------------------------------------
// 4) Healthy row behavior unchanged
// ---------------------------------------------------------------------------

describe("healthy row behavior", () => {
  it("shouldMarkSucceeded is true for a real analysis response", () => {
    expect(shouldMarkSucceeded({ analysis_failed: false, is_mock: false })).toBe(true);
  });

  it("shouldMarkSucceeded is false when analysis_failed", () => {
    expect(shouldMarkSucceeded({ analysis_failed: true, is_mock: false })).toBe(false);
  });

  it("shouldMarkSucceeded is false when is_mock", () => {
    expect(shouldMarkSucceeded({ analysis_failed: false, is_mock: true })).toBe(false);
  });

  it("deriveRowState normal when failedHeadlines is large but does not contain this headline", () => {
    const failed = new Set(Array.from({ length: 100 }, (_, i) => `headline-${i}`));
    expect(deriveRowState("Fed hikes rates by 50bp", failed)).toBe("normal");
  });
});
