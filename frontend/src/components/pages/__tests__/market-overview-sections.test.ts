/**
 * Pins the honest non-claim copy for the split Market Overview lower
 * sections (3 · Outcome ledger, 4 · Evidence layer).
 *
 * These two notes are public-facing surface copy, so they must stay
 * descriptive and carry none of the project's banned overclaim words.
 * The strings are exported from ``market-overview`` and rendered verbatim
 * in their respective sections.
 */

import { describe, it, expect } from "vitest";

import {
  OUTCOME_LEDGER_NOTE,
  EVIDENCE_LAYER_NOTE,
} from "../market-overview";

const FORBIDDEN = [
  "buy",
  "sell",
  "alpha",
  "proven",
  "proof",
  "signal",
  "prediction",
  "predicted",
];

describe("Market Overview section notes", () => {
  it("Outcome ledger note is the exact honest non-claim copy", () => {
    expect(OUTCOME_LEDGER_NOTE).toBe(
      "Saved outcomes are descriptive archive reads, not a live trading record.",
    );
  });

  it("Evidence layer note is the exact honest non-claim copy", () => {
    expect(EVIDENCE_LAYER_NOTE).toBe(
      "Evidence pools remain separated by phase and denominator; closed FDR pools are not recomputed here.",
    );
  });

  it("neither note uses banned buy/sell/overclaim language", () => {
    for (const note of [OUTCOME_LEDGER_NOTE, EVIDENCE_LAYER_NOTE]) {
      const lc = note.toLowerCase();
      for (const word of FORBIDDEN) {
        expect(lc).not.toContain(word);
      }
    }
  });
});
