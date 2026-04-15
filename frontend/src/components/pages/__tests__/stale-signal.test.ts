/**
 * Unit tests for getStaleDisplay() — maps StaleSignal to display state.
 */

import { describe, it, expect } from "vitest";
import { getStaleDisplay } from "@/lib/api";

describe("getStaleDisplay", () => {
  it("returns no indicator for fresh signal", () => {
    const d = getStaleDisplay("fresh");
    expect(d.showIndicator).toBe(false);
    expect(d.showRefresh).toBe(false);
  });

  it("returns no indicator for undefined signal", () => {
    const d = getStaleDisplay(undefined);
    expect(d.showIndicator).toBe(false);
    expect(d.showRefresh).toBe(false);
  });

  it("returns Archived label for frozen — no refresh", () => {
    const d = getStaleDisplay("frozen");
    expect(d.showIndicator).toBe(true);
    expect(d.label).toBe("Archived");
    expect(d.showRefresh).toBe(false);
  });

  it("returns Data outdated label for stale — with refresh", () => {
    const d = getStaleDisplay("stale");
    expect(d.showIndicator).toBe(true);
    expect(d.label).toBe("Data outdated");
    expect(d.showRefresh).toBe(true);
  });

  it("returns Data outdated label for legacy — with refresh", () => {
    const d = getStaleDisplay("legacy");
    expect(d.showIndicator).toBe(true);
    expect(d.label).toBe("Data outdated");
    expect(d.showRefresh).toBe(true);
  });

  it("frozen dot class is muted", () => {
    const d = getStaleDisplay("frozen");
    expect(d.dotClass).toContain("muted");
  });

  it("stale dot class is amber", () => {
    const d = getStaleDisplay("stale");
    expect(d.dotClass).toContain("amber");
  });
});
