/**
 * Pins the P7 enrichment of Section 2 "The archive" case cards.
 *
 *  - pickLatestAnalyzedCases now carries real /events list fields onto each
 *    ArchiveCase: mechanism_summary (trimmed, null when blank/absent), the
 *    validation_status_v2 supporting/contradicting counts (null when the
 *    block omits them), and the lead market ticker's realized 5-day return
 *    (null when absent).  reaction_profile_v1 is intentionally NOT read here:
 *    it is a detail-route block (GET /events/{id}), absent from the /events
 *    list payload, so the reaction read comes off market_tickers.
 *  - formatSupportCounts renders the evidence subline only when at least one
 *    count is present (a real 0 is information, not absence).
 *  - Missing fields never invent content; the date-descending /
 *    analysis-first ordering is unchanged; no banned overclaim words are
 *    introduced; the P6 intake + archive/evidence headings remain exported.
 */

import { describe, it, expect } from "vitest";

import {
  pickLatestAnalyzedCases,
  formatSupportCounts,
  ARCHIVE_SECTION_TITLE,
  EVIDENCE_LIMITS_TITLE,
  INTAKE_TITLE,
} from "../market-overview";
import type { SavedEvent } from "@/lib/api";

function ev(over: Partial<SavedEvent> & { id: number }): SavedEvent {
  return {
    stage: "initial",
    headline: "headline",
    event_date: "2026-01-01",
    mechanism_summary: "",
    market_tickers: [{ symbol: "AAA" }],
    validation_status_v2: { status: "unresolved" },
    ...over,
  } as unknown as SavedEvent;
}

describe("pickLatestAnalyzedCases — P7 enrichment", () => {
  it("carries a trimmed mechanism_summary when present", () => {
    const [c] = pickLatestAnalyzedCases(
      [ev({ id: 1, mechanism_summary: "  Tariff phase-in raises input costs  " })],
      5,
    );
    expect(c!.mechanismSummary).toBe("Tariff phase-in raises input costs");
  });

  it("uses null for a blank / missing mechanism_summary (never invents one)", () => {
    const [blank] = pickLatestAnalyzedCases([ev({ id: 1, mechanism_summary: "   " })], 5);
    expect(blank!.mechanismSummary).toBeNull();
    const [missing] = pickLatestAnalyzedCases(
      [ev({ id: 2, mechanism_summary: undefined as unknown as string })],
      5,
    );
    expect(missing!.mechanismSummary).toBeNull();
  });

  it("carries validation_status_v2 supporting/contradicting counts when present", () => {
    const [c] = pickLatestAnalyzedCases(
      [
        ev({
          id: 1,
          validation_status_v2: {
            status: "validated",
            counts: { supporting: 3, contradicting: 1 },
          },
        }),
      ],
      5,
    );
    expect(c!.supporting).toBe(3);
    expect(c!.contradicting).toBe(1);
  });

  it("uses null counts when the validation block omits them", () => {
    const [c] = pickLatestAnalyzedCases(
      [ev({ id: 1, validation_status_v2: { status: "unresolved" } })],
      5,
    );
    expect(c!.supporting).toBeNull();
    expect(c!.contradicting).toBeNull();
  });

  it("carries the lead market ticker's 5-day reaction return when present", () => {
    const [c] = pickLatestAnalyzedCases(
      [ev({ id: 1, market_tickers: [{ symbol: "XLE", return_5d: 3.2 }] as SavedEvent["market_tickers"] })],
      5,
    );
    expect(c!.reactionReturn5d).toBe(3.2);
    // reaction aligns with the displayed lead ticker — same market_tickers[0].
    expect(c!.ticker).toBe("XLE");
  });

  it("uses null reaction when the lead ticker has no return_5d (symbol-only)", () => {
    const [c] = pickLatestAnalyzedCases([ev({ id: 1 })], 5);
    expect(c!.reactionReturn5d).toBeNull();
  });

  it("preserves event_date-descending, analysis-first ordering after enrichment", () => {
    const out = pickLatestAnalyzedCases(
      [
        ev({ id: 1, event_date: "2026-01-10" }),
        ev({ id: 2, event_date: "2026-03-10" }),
        // a curated observation with a far-later date still sorts last.
        ev({ id: 3, stage: "curated_observation", event_date: "2026-12-31" }),
      ],
      5,
    );
    expect(out.map((c) => c.id)).toEqual([2, 1, 3]);
  });
});

describe("formatSupportCounts", () => {
  it("joins both counts when present", () => {
    expect(formatSupportCounts(3, 1)).toBe("3 supporting · 1 contradicting");
  });

  it("shows a single side when only one is present", () => {
    expect(formatSupportCounts(3, null)).toBe("3 supporting");
    expect(formatSupportCounts(null, 2)).toBe("2 contradicting");
  });

  it("keeps a real zero when paired with directional evidence", () => {
    // 0 supporting alongside 2 contradicting is a meaningful "contradicted"
    // read — the zero is information here, not absence.
    expect(formatSupportCounts(0, 2)).toBe("0 supporting · 2 contradicting");
    expect(formatSupportCounts(2, 0)).toBe("2 supporting · 0 contradicting");
  });

  it("omits the line when there is no directional evidence at all", () => {
    // All-zero / absent tallies carry no evidence to show — the unresolved
    // status already conveys it, so the subline is omitted rather than
    // repeating "0 supporting · 0 contradicting" on every data-less card.
    expect(formatSupportCounts(0, 0)).toBeNull();
    expect(formatSupportCounts(0, null)).toBeNull();
    expect(formatSupportCounts(null, 0)).toBeNull();
    expect(formatSupportCounts(null, undefined)).toBeNull();
  });
});

describe("P7 enrichment stays honest + structurally intact", () => {
  it("introduces no banned overclaim / trading words in the new evidence copy", () => {
    const blob = [formatSupportCounts(3, 1) ?? "", "5d"].join(" ").toLowerCase();
    for (const w of [
      "buy",
      "sell",
      "alpha",
      "signal",
      "proof",
      "proves",
      "proven",
      "prediction",
      "predicted",
    ]) {
      expect(blob).not.toContain(w);
    }
  });

  it("keeps the P6 intake + archive/evidence headings present", () => {
    expect(ARCHIVE_SECTION_TITLE).toBe("The archive");
    expect(EVIDENCE_LIMITS_TITLE).toBe("Evidence & limits");
    expect(INTAKE_TITLE).toBe("Start an analysis");
  });
});
