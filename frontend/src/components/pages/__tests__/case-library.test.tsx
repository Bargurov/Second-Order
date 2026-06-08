/**
 * T8B — Curated Case Library page, expanded 5 → 15 representative cases.
 *
 * A guided, honest entry point: fifteen real representative cases drawn from
 * the scored archive, each linking into the existing EventDossier surface via
 * the URL-addressable /share/:id route AND an in-app open control.  The slate
 * is contradiction-led to mirror the scored archive (35 contradicted is the
 * modal real outcome), spans six deterministic mechanism families, and discloses
 * both directions of missingness — so the denominator anchor, the slate outcome
 * mix, the standing non-claims, and the banned-framing discipline stay visible.
 *
 * Families are the deterministic effective family (family_inference.
 * resolve_effective_family) as the backend emits it — never hand-relabelled.
 *
 * Pure / presentational (no React Query, no jsdom), matching the project's
 * render-smoke pattern (renderToStaticMarkup).
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { CaseLibrary } from "../case-library";
import { CURATED_CASES } from "@/lib/curated-cases";

// The T8A-approved slate (15 ids), in slate order.
const APPROVED_IDS = [105, 29, 85, 215, 72, 84, 94, 80, 1, 240, 238, 300, 211, 239, 214];
const ORIGINAL_IDS = [105, 29, 240, 300, 238];

// Deterministic effective family per id, as produced by the backend's
// resolve_effective_family over db._decode_event_row rows (read-only verified).
// Pinned here so a hand-relabel can never silently slip in.
const FAMILY_BY_ID: Record<number, string> = {
  105: "commodity_squeeze",
  29: "commodity_squeeze",
  85: "commodity_squeeze",
  215: "commodity_squeeze",
  72: "supply_shock",
  84: "tariff",
  94: "tariff",
  80: "tariff",
  1: "tariff",
  240: "tariff",
  238: "tariff",
  300: "sanction",
  211: "sanction",
  239: "policy_surprise",
  214: "ceasefire_deescalation",
};

const html = renderToStaticMarkup(<CaseLibrary />);
const visible = html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

describe("CaseLibrary — page renders the expanded curated slate (T8B)", () => {
  it("shows the page title", () => {
    expect(visible).toContain("Case Library");
  });

  it("links every approved case into the dossier surface (/share/:id)", () => {
    for (const id of APPROVED_IDS) {
      expect(html).toContain(`/share/${id}`);
    }
  });

  it("renders a primary in-app open control carrying each case's event id", () => {
    for (const id of APPROVED_IDS) {
      expect(html).toContain(`data-open-event-id="${id}"`);
    }
  });

  it("shows the full outcome range via role labels (not best-of)", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("strong support");
    expect(lc).toContain("contradiction");
    expect(lc).toContain("unresolved");
    expect(lc).toContain("data-limited");
    expect(lc).toContain("mechanism-rich");
  });
});

describe("CaseLibrary — denominator + anti-cherry-pick copy stays visible (T8B)", () => {
  it("renders the expanded denominator anchor", () => {
    expect(visible).toContain("15 representative cases drawn from 81 market-scored events of 166 saved.");
  });

  it("keeps the corpus outcome split visible", () => {
    expect(visible).toContain("19 any-supporting · 35 contradicted · 27 unresolved.");
  });

  it("states the slate is representative, not best-of", () => {
    expect(visible).toContain("Representative cases — selected to show the range of outcomes, not a best-of.");
  });

  it("surfaces contradiction / unresolved / data-limited language near the top", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("contradict");
    expect(lc).toContain("unresolved");
    expect(lc).toContain("data-limited");
  });

  it("annotates honest missingness on cases with no raw market-check returns", () => {
    expect(visible.toLowerCase()).toContain("event-study readout carries");
  });

  it("renders the required standing non-claim lines verbatim", () => {
    expect(visible).toContain("Representative cases — selected to show the range of outcomes, not a best-of.");
    expect(visible).toContain("Each case is a descriptive event-window read at n = 1, not benchmark-adjusted significance.");
    expect(visible).toContain("Not exhaustive; denominators differ by gate and data availability.");
    expect(visible).toContain("Separate from the closed Phase 1 / Phase 2 FDR pools; no pooled denominator is implied.");
  });
});

describe("CURATED_CASES registry — slate integrity (T8B)", () => {
  it("contains exactly the 15 approved, unique event ids", () => {
    const ids = CURATED_CASES.map((c) => c.eventId);
    expect(ids.length).toBe(15);
    expect(new Set(ids).size).toBe(ids.length);
    expect(new Set(ids)).toEqual(new Set(APPROVED_IDS));
  });

  it("keeps all five original case ids", () => {
    const ids = new Set(CURATED_CASES.map((c) => c.eventId));
    for (const id of ORIGINAL_IDS) {
      expect(ids.has(id)).toBe(true);
    }
  });

  it("uses only the five existing CaseRole values", () => {
    const allowed = new Set([
      "strong-support",
      "contradiction",
      "unresolved",
      "data-limited",
      "mechanism-rich",
    ]);
    for (const c of CURATED_CASES) {
      expect(allowed.has(c.role)).toBe(true);
    }
  });
});

describe("CURATED_CASES registry — deterministic family, no relabel (T8B)", () => {
  it("carries the backend effective family for every case", () => {
    const byId = Object.fromEntries(CURATED_CASES.map((c) => [c.eventId, c.family]));
    for (const id of APPROVED_IDS) {
      expect(byId[id]).toBe(FAMILY_BY_ID[id]);
    }
  });

  it("covers all six families the slate spans", () => {
    const fams = new Set(CURATED_CASES.map((c) => c.family));
    for (const fam of [
      "commodity_squeeze",
      "tariff",
      "sanction",
      "supply_shock",
      "policy_surprise",
      "ceasefire_deescalation",
    ]) {
      expect(fams.has(fam)).toBe(true);
    }
  });
});

describe("CURATED_CASES registry — outcome mix + cherry-pick guard (T8B)", () => {
  it("includes supporting, contradiction, unresolved, and data-limited outcomes", () => {
    const roles = new Set(CURATED_CASES.map((c) => c.role));
    expect(roles.has("strong-support")).toBe(true);
    expect(roles.has("contradiction")).toBe(true);
    expect(roles.has("unresolved")).toBe(true);
    expect(roles.has("data-limited")).toBe(true);
  });

  it("is contradiction-led: contradiction count >= supporting count", () => {
    const contradiction = CURATED_CASES.filter((c) => c.role === "contradiction").length;
    const supporting = CURATED_CASES.filter((c) => c.role === "strong-support").length;
    expect(contradiction).toBeGreaterThanOrEqual(supporting);
    expect(contradiction).toBeGreaterThan(0);
  });
});

describe("CaseLibrary — no banned framing across the whole page (T8B)", () => {
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

describe("CaseLibrary — per-case evidence density (W1A)", () => {
  it("surfaces a compact research-read line for every case", () => {
    for (const c of CURATED_CASES) {
      expect(visible, `read line for #${c.eventId}`).toContain(c.demonstrates);
    }
  });

  it("surfaces an event-study availability cue (all available after V2C)", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("event-study: available");
    expect(lc).not.toContain("event-study: unavailable");
  });

  it("renders each case's deterministic mechanism family cue", () => {
    for (const c of CURATED_CASES) {
      expect(visible, `family cue for #${c.eventId}`).toContain(c.family);
    }
  });

  it("renders each case's outcome/role label cue", () => {
    for (const c of CURATED_CASES) {
      expect(visible, `role cue for #${c.eventId}`).toContain(c.roleLabel);
    }
  });

  it("keeps the 15 / 81 / 166 denominator visible", () => {
    expect(visible).toContain("15 representative cases drawn from 81 market-scored events of 166 saved.");
  });

  it("states the cases are illustrative, not a validation pool", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("illustrative");
    expect(lc).toContain("not a validation pool");
    expect(lc).toContain("3/15");
    expect(lc).toContain("do not replace the corpus-level denominators");
  });

  it("keeps contradiction, unresolved, and data-limited cases first-class/visible", () => {
    const lc = visible.toLowerCase();
    expect(lc).toContain("contradiction");
    expect(lc).toContain("unresolved");
    expect(lc).toContain("data-limited");
  });
});

describe("CURATED_CASES registry — event-study availability flag (V2D)", () => {
  it("marks all 15 cases event-study-available after the V2C coverage repair", () => {
    for (const c of CURATED_CASES) {
      expect(c.eventStudyAvailable, `#${c.eventId} ES`).toBe(true);
    }
  });
});
