import { describe, it, expect } from "vitest";
import { ageLabel, overallVariant } from "../system-health-panel";

describe("ageLabel", () => {
  it("returns '– ' for null", () => {
    expect(ageLabel(null)).toBe("–");
  });

  it("returns 'just now' for < 60s", () => {
    expect(ageLabel(0)).toBe("just now");
    expect(ageLabel(59)).toBe("just now");
  });

  it("returns minutes for < 1h", () => {
    expect(ageLabel(60)).toBe("1m ago");
    expect(ageLabel(119)).toBe("1m ago");
    expect(ageLabel(120)).toBe("2m ago");
    expect(ageLabel(3599)).toBe("59m ago");
  });

  it("returns hours for < 24h", () => {
    expect(ageLabel(3600)).toBe("1h ago");
    expect(ageLabel(7200)).toBe("2h ago");
    expect(ageLabel(86399)).toBe("23h ago");
  });

  it("returns days for >= 24h", () => {
    expect(ageLabel(86400)).toBe("1d ago");
    expect(ageLabel(172800)).toBe("2d ago");
  });
});

describe("overallVariant", () => {
  it("passes through all known values unchanged", () => {
    expect(overallVariant("ok")).toBe("ok");
    expect(overallVariant("degraded")).toBe("degraded");
    expect(overallVariant("error")).toBe("error");
    expect(overallVariant("no_data")).toBe("no_data");
  });
});
