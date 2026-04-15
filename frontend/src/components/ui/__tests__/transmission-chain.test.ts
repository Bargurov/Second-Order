/**
 * Unit tests for TransmissionChain label and accent helpers.
 * Tests pure functions — no React mount needed.
 */
import { describe, it, expect } from "vitest";
import { getStepLabel, isAccentStep } from "../transmission-chain";

describe("getStepLabel", () => {
  it("always returns Trigger for index 0", () => {
    expect(getStepLabel(0, 3)).toBe("Trigger");
    expect(getStepLabel(0, 5)).toBe("Trigger");
  });

  it("always returns Impact for last index", () => {
    expect(getStepLabel(2, 3)).toBe("Impact");
    expect(getStepLabel(4, 5)).toBe("Impact");
  });

  it("3-step chain: Trigger, Channel, Impact", () => {
    expect(getStepLabel(0, 3)).toBe("Trigger");
    expect(getStepLabel(1, 3)).toBe("Channel");
    expect(getStepLabel(2, 3)).toBe("Impact");
  });

  it("4-step chain: Trigger, Channel, Mechanism, Impact", () => {
    expect(getStepLabel(0, 4)).toBe("Trigger");
    expect(getStepLabel(1, 4)).toBe("Channel");
    expect(getStepLabel(2, 4)).toBe("Mechanism");
    expect(getStepLabel(3, 4)).toBe("Impact");
  });

  it("5-step chain: Trigger, Channel, Mechanism, Market, Impact", () => {
    expect(getStepLabel(0, 5)).toBe("Trigger");
    expect(getStepLabel(1, 5)).toBe("Channel");
    expect(getStepLabel(2, 5)).toBe("Mechanism");
    expect(getStepLabel(3, 5)).toBe("Market");
    expect(getStepLabel(4, 5)).toBe("Impact");
  });

  it("falls back to Channel for unknown middle index", () => {
    expect(getStepLabel(4, 7)).toBe("Channel");
    expect(getStepLabel(5, 7)).toBe("Channel");
  });
});

describe("isAccentStep", () => {
  it("first step is always accent", () => {
    expect(isAccentStep(0, 3)).toBe(true);
    expect(isAccentStep(0, 5)).toBe(true);
  });

  it("last step is always accent", () => {
    expect(isAccentStep(2, 3)).toBe(true);
    expect(isAccentStep(4, 5)).toBe(true);
  });

  it("middle steps are not accent", () => {
    expect(isAccentStep(1, 3)).toBe(false);
    expect(isAccentStep(1, 5)).toBe(false);
    expect(isAccentStep(2, 5)).toBe(false);
    expect(isAccentStep(3, 5)).toBe(false);
  });
});
