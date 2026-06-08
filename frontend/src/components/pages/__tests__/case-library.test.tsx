/**
 * R6B — Curated Case Library page.
 *
 * A guided, honest entry point: five real representative cases (one per role)
 * drawn from the scored archive, each linking into the existing EventDossier
 * surface via the URL-addressable /share/:id route.  The page must show the
 * range of outcomes (support / contradiction / unresolved / data-limited /
 * mechanism-rich) without implying cherry-picked proof — so the denominator
 * anchor, the outcome split, and the standing non-claims stay visible.
 *
 * Pure / presentational (no React Query, no jsdom), matching the project's
 * render-smoke pattern (renderToStaticMarkup).
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { CaseLibrary } from "../case-library";
import { CURATED_CASES } from "@/lib/curated-cases";

const APPROVED_IDS = [105, 29, 240, 300, 238];

const html = renderToStaticMarkup(<CaseLibrary />);
const visible = html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

describe("CaseLibrary — page renders the five curated cases (R6B)", () => {
  it("shows the page title and a purpose line", () => {
    expect(visible).toContain("Case Library");
  });

  it("renders every approved case id's headline", () => {
    expect(visible).toContain("OPEC extends voluntary oil output cuts");           // 105
    expect(visible).toContain("close the Strait of Hormuz");                       // 29
    expect(visible).toContain("GM raises 2026 guidance");                          // 240
    expect(visible).toContain("NVIDIA A100/H100 exports to China");               // 300
    expect(visible).toContain("China scraps tariffs on 53 African nations");      // 238
  });

  it("links every case into the existing dossier surface (/share/:id)", () => {
    for (const id of APPROVED_IDS) {
      expect(html).toContain(`/share/${id}`);
    }
  });

  it("shows all five role labels (full outcome range, not best-of)", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("strong support");
    expect(lc).toContain("contradiction");
    expect(lc).toContain("unresolved");
    expect(lc).toContain("data-limited");
    expect(lc).toContain("mechanism-rich");
  });
});

describe("CaseLibrary — in-app Archive deep-link (R6C)", () => {
  it("renders a primary in-app open control carrying each case's event id", () => {
    // The card requests in-app Archive/Event Detail navigation via onOpenCase,
    // not only a /share link — the control encodes the target event id.
    for (const id of APPROVED_IDS) {
      expect(html).toContain(`data-open-event-id="${id}"`);
    }
  });

  it("keeps /share/:id available as a secondary link, not the only target", () => {
    for (const id of APPROVED_IDS) {
      expect(html).toContain(`/share/${id}`);
    }
  });
});

describe("CaseLibrary — denominator + non-claim copy stays visible (R6B)", () => {
  it("renders the denominator anchor and the outcome split", () => {
    expect(visible).toContain("5 representative cases drawn from 81 market-scored events of 166 saved.");
    expect(visible).toContain("19 any-supporting · 35 contradicted · 27 unresolved.");
  });

  it("renders the required non-claim lines verbatim", () => {
    expect(visible).toContain("Representative cases — selected to show the range of outcomes, not a best-of.");
    expect(visible).toContain("Each case is a descriptive event-window read at n = 1, not benchmark-adjusted significance.");
    expect(visible).toContain("Not exhaustive; denominators differ by gate and data availability.");
    expect(visible).toContain("Separate from the closed Phase 1 / Phase 2 FDR pools; no pooled denominator is implied.");
  });

  it("annotates honest missingness on the cases with no raw market-check returns", () => {
    // ids 240 / 300 / 238 have no stored raw returns — the event-study readout
    // carries the quantitative read; this must be stated, never faked.
    expect(visible.toLowerCase()).toContain("event-study readout carries");
  });
});

describe("CaseLibrary — no banned framing across the whole page (R6B)", () => {
  it("carries no buy / sell / trade / signal / overclaim framing", () => {
    const lc = visible.toLowerCase();
    for (const w of [
      "buy", "sell", "long", "short", "alpha", "signal", "trade",
      "live trading", "proof", "proves", "confirmed", "validated",
    ]) {
      expect(lc, `banned word "${w}" on the Case Library page`).not.toMatch(new RegExp(`\\b${w}\\b`));
    }
  });
});

describe("CaseLibrary — mechanism-family label per case (T7B-A)", () => {
  it("renders each case's deterministic mechanism family", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("commodity_squeeze"); // 105, 29
    expect(lc).toContain("tariff");            // 240, 238
    expect(lc).toContain("sanction");          // 300
  });
});

describe("CURATED_CASES registry — mechanism family field (T7B-A)", () => {
  it("carries the deterministic effective family for every case", () => {
    const byId = Object.fromEntries(CURATED_CASES.map((c) => [c.eventId, c.family]));
    expect(byId[105]).toBe("commodity_squeeze");
    expect(byId[29]).toBe("commodity_squeeze");
    expect(byId[240]).toBe("tariff");
    expect(byId[300]).toBe("sanction");
    expect(byId[238]).toBe("tariff");
  });
});

describe("CURATED_CASES registry — integrity + cherry-pick guard (R6B)", () => {
  it("contains exactly the five approved, unique event ids", () => {
    const ids = CURATED_CASES.map((c) => c.eventId);
    expect(ids.length).toBe(5);
    expect(new Set(ids).size).toBe(ids.length);
    expect(new Set(ids)).toEqual(new Set(APPROVED_IDS));
  });

  it("covers all five distinct roles", () => {
    const roles = new Set(CURATED_CASES.map((c) => c.role));
    expect(roles).toEqual(
      new Set(["strong-support", "contradiction", "unresolved", "data-limited", "mechanism-rich"]),
    );
  });

  it("cherry-pick guard: not all winners — includes a contradiction and an unresolved case", () => {
    const roles = CURATED_CASES.map((c) => c.role);
    expect(roles).toContain("contradiction");
    expect(roles).toContain("unresolved");
    expect(CURATED_CASES.every((c) => c.role === "strong-support")).toBe(false);
  });
});
