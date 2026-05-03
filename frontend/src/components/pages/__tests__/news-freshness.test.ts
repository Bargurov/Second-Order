/**
 * Focused tests for the deriveNewsFreshness pure function.
 *
 * Covers every RefreshMeta state the backend can produce:
 *   - null / undefined  → "No data" / neutral
 *   - status "error"    → "Feed error" / error
 *   - status "throttled"→ "Throttled" / neutral
 *   - freshness "stale" → "Stale" / warn
 *   - status "degraded" → "Degraded" / warn
 *   - freshness "degraded" (without status degraded) → "Degraded" / warn
 *   - status "recent"   → "Cached" / ok
 *   - status "ok"       → "Live" / ok
 */

import { describe, it, expect } from "vitest";
import { deriveNewsFreshness } from "../market-overview";
import type { RefreshMeta } from "@/lib/api";

const base: RefreshMeta = {
  status: "ok",
  known: 10,
  new: 2,
  merged: 1,
  created: 1,
  reused: 8,
  source: "incremental",
  freshness: "fresh",
  last_successful_refresh: "2026-04-13T10:00:00",
};

describe("deriveNewsFreshness", () => {
  it("returns neutral 'No data' when meta is null", () => {
    const r = deriveNewsFreshness(null);
    expect(r).toEqual({ label: "No data", tone: "neutral" });
  });

  it("returns neutral 'No data' when meta is undefined", () => {
    const r = deriveNewsFreshness(undefined);
    expect(r).toEqual({ label: "No data", tone: "neutral" });
  });

  it("returns error on status=error", () => {
    const r = deriveNewsFreshness({ ...base, status: "error", freshness: "stale" });
    expect(r.label).toBe("Feed error");
    expect(r.tone).toBe("error");
  });

  it("returns neutral on status=throttled", () => {
    const r = deriveNewsFreshness({ ...base, status: "throttled" });
    expect(r.label).toBe("Throttled");
    expect(r.tone).toBe("neutral");
  });

  it("returns warn on freshness=stale (even if status ok)", () => {
    const r = deriveNewsFreshness({ ...base, status: "ok", freshness: "stale" });
    expect(r.label).toBe("Stale");
    expect(r.tone).toBe("warn");
  });

  it("returns warn on status=degraded", () => {
    const r = deriveNewsFreshness({ ...base, status: "degraded", freshness: "degraded" });
    expect(r.label).toBe("Degraded");
    expect(r.tone).toBe("warn");
  });

  it("returns warn on freshness=degraded without status degraded", () => {
    const r = deriveNewsFreshness({ ...base, status: "ok", freshness: "degraded" });
    expect(r.label).toBe("Degraded");
    expect(r.tone).toBe("warn");
  });

  it("returns ok on status=recent", () => {
    const r = deriveNewsFreshness({ ...base, status: "recent", freshness: "fresh" });
    expect(r.label).toBe("Cached");
    expect(r.tone).toBe("ok");
  });

  it("returns ok 'Live' on healthy status=ok + freshness=fresh", () => {
    const r = deriveNewsFreshness({ ...base, status: "ok", freshness: "fresh" });
    expect(r.label).toBe("Live");
    expect(r.tone).toBe("ok");
  });

  it("returns ok 'Live' when freshness is missing but status is ok", () => {
    const { freshness: _, ...noFreshness } = base;
    const r = deriveNewsFreshness(noFreshness as RefreshMeta);
    expect(r.label).toBe("Live");
    expect(r.tone).toBe("ok");
  });

  // Priority: error > throttled > stale > degraded > recent > ok
  it("error takes priority over stale", () => {
    const r = deriveNewsFreshness({ ...base, status: "error", freshness: "stale" });
    expect(r.label).toBe("Feed error");
  });

  it("stale takes priority over degraded status", () => {
    const r = deriveNewsFreshness({ ...base, status: "degraded", freshness: "stale" });
    expect(r.label).toBe("Stale");
  });
});
