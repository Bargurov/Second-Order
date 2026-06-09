/**
 * Pins the P5B "frozen archive" reframe helpers + copy contracts.
 *
 *  - pickLatestAnalyzedCases: prefers analysis-stage events, sorts by
 *    event_date descending (never insertion order), flags curated_observation
 *    rows as observations.
 *  - OUTCOME_BREAKDOWN_DIMENSION: the one populated breakdown dimension —
 *    must be by_quality_tier and must never be the degenerate by_mechanism_family.
 *  - Section copy avoids live-dashboard wording (today / live / now) and the
 *    banned overclaim words (proves / proof / buy / sell / alpha / signal).
 */

import { describe, it, expect } from "vitest";

import {
  pickLatestAnalyzedCases,
  ARCHIVE_SECTION_TITLE,
  ARCHIVE_FRAMING_NOTE,
  OUTCOME_BREAKDOWN_DIMENSION,
  EVIDENCE_LIMITS_TITLE,
  EVIDENCE_NONCLAIMS,
} from "../market-overview";
import type { SavedEvent } from "@/lib/api";

function ev(over: Partial<SavedEvent> & { id: number }): SavedEvent {
  return {
    stage: "initial",
    headline: "headline",
    event_date: "2026-01-01",
    market_tickers: [{ symbol: "AAA" }],
    validation_status_v2: { status: "unresolved" },
    ...over,
  } as unknown as SavedEvent;
}

describe("pickLatestAnalyzedCases", () => {
  it("sorts analysis-stage cases by event_date descending", () => {
    const out = pickLatestAnalyzedCases(
      [
        ev({ id: 1, event_date: "2026-01-10" }),
        ev({ id: 2, event_date: "2026-03-10" }),
        ev({ id: 3, event_date: "2026-02-10" }),
      ],
      5,
    );
    expect(out.map((c) => c.id)).toEqual([2, 3, 1]);
  });

  it("prefers analysis-stage events over curated_observation, even when older", () => {
    const out = pickLatestAnalyzedCases(
      [
        ev({ id: 9, stage: "curated_observation", event_date: "2026-05-30" }),
        ev({ id: 4, stage: "initial", event_date: "2026-01-01" }),
      ],
      5,
    );
    expect(out[0]!.id).toBe(4); // analysis first despite older date
    expect(out[0]!.isObservation).toBe(false);
    const obs = out.find((c) => c.id === 9)!;
    expect(obs.isObservation).toBe(true);
  });

  it("classifies a z1a_candidate_pack row as a non-analysis observation, never analyzed", () => {
    // AB1 Lane A: a candidate-only staging row must not be grouped with (or
    // sorted ahead of) analyzed cases — flag it as an observation even though
    // it carries the later date.  Defence-in-depth behind the backend /events
    // candidate suppression; candidate-only is a distinct stage, not the same
    // thing as a curated_observation.
    const out = pickLatestAnalyzedCases(
      [
        ev({ id: 7, stage: "z1a_candidate_pack", event_date: "2026-05-30" }),
        ev({ id: 4, stage: "initial", event_date: "2026-01-01" }),
      ],
      5,
    );
    expect(out[0]!.id).toBe(4); // analyzed case leads despite the older date
    expect(out[0]!.isObservation).toBe(false);
    const cand = out.find((c) => c.id === 7)!;
    expect(cand.isObservation).toBe(true);
  });

  it("respects the limit and carries display fields", () => {
    const out = pickLatestAnalyzedCases(
      [ev({ id: 1 }), ev({ id: 2 }), ev({ id: 3 })],
      2,
    );
    expect(out).toHaveLength(2);
    expect(out[0]).toMatchObject({ headline: "headline", ticker: "AAA", statusLabel: "unresolved" });
  });
});

describe("outcome breakdown dimension", () => {
  it("uses the populated quality-tier dimension, never the degenerate family one", () => {
    expect(OUTCOME_BREAKDOWN_DIMENSION).toBe("by_quality_tier");
    expect(OUTCOME_BREAKDOWN_DIMENSION).not.toBe("by_mechanism_family");
  });
});

describe("frozen-archive copy is honest", () => {
  it("Section 2 copy carries no live-dashboard wording", () => {
    for (const s of [ARCHIVE_SECTION_TITLE, ARCHIVE_FRAMING_NOTE]) {
      const lc = s.toLowerCase();
      for (const w of ["today", "live", "now"]) expect(lc).not.toContain(w);
    }
  });

  it("Evidence & limits copy carries no banned overclaim words", () => {
    const blob = [EVIDENCE_LIMITS_TITLE, ...EVIDENCE_NONCLAIMS].join(" ").toLowerCase();
    for (const w of ["proves", "proof", "buy", "sell", "alpha", "signal"]) {
      expect(blob).not.toContain(w);
    }
  });
});
