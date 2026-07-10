/**
 * Mission J evidence card render contract (Evidence Overview flagship).
 *
 * The card is the first in-product consumer of the published Mission J
 * record (GET /evidence/mission-j).  It must render the complete frozen
 * surfaces in server order — mechanism readout (N0-N3, E1-E3), the J1B
 * 12-cell robustness record, the J2 timing challenge with its
 * descriptive-only diagnostics, the collision qualification with C1
 * unadjudicability prominent, and the claim-limit block — while keeping
 * ORDINARY / UNRESOLVED results at equal visual weight, never inventing a
 * value in loading/unavailable/malformed states, and carrying no ranking,
 * strength, clean-window, or assertive-claim framing.
 *
 * Presentational only — vitest + renderToStaticMarkup, no jsdom.  The
 * contract-shaped fixture lives in mission-j-fixture.ts.
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { MissionJEvidenceCard } from "../mission-j-evidence-card";
import { missionJFixture } from "./mission-j-fixture";

function render(props: Parameters<typeof MissionJEvidenceCard>[0]): string {
  return renderToStaticMarkup(<MissionJEvidenceCard {...props} />);
}

const html = render({ data: missionJFixture() });
const visible = html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

describe("MissionJEvidenceCard — mechanism readout (J3)", () => {
  it("renders the four frozen nodes in order", () => {
    const idx = ["N0", "N1", "N2", "N3"].map((n) => visible.indexOf(`${n} `));
    for (const i of idx) expect(i).toBeGreaterThan(-1);
    expect([...idx]).toEqual([...idx].sort((a, b) => a - b));
    expect(visible).toContain("fomc_decision");
    expect(visible).toContain("policy_rates_repricing");
    expect(visible).toContain("balance_sheet_sensitive_second_order");
    expect(visible).toContain("broad_financial_sector");
  });

  it("renders the three frozen edges in order, each PROPAGATED with the frozen qualifier", () => {
    const idx = ["E1", "E2", "E3"].map((e) => visible.indexOf(`${e} `));
    for (const i of idx) expect(i).toBeGreaterThan(-1);
    expect([...idx]).toEqual([...idx].sort((a, b) => a - b));
    const qualified = visible.match(
      /PROPAGATED under the frozen measurement rules/g,
    );
    expect(qualified?.length).toBe(3);
  });

  it("shows rule paths, measurement classes, panel modifiers and limitations on edges", () => {
    expect(visible).toContain("precedence step 3");
    expect(visible).toContain("Route A");
    expect(visible).toContain("M2");
    expect(visible).toContain("M3");
    expect(visible).toContain("BROAD MEASUREMENT CONSISTENCY");
    expect(visible.toLowerCase()).toContain("measurement-limited");
  });

  it("keeps 2s10s contextual only — never a graph node", () => {
    // context note present…
    expect(visible).toContain("2S10S_CMT");
    expect(visible.toLowerCase()).toContain("outside edge adjudication");
    // …and never inside the node ledger (nodes only carry the frozen roles)
    expect(visible).not.toContain("N4");
    const nodeBlock = visible.slice(
      visible.indexOf("N0 "),
      visible.indexOf("E1 "),
    );
    expect(nodeBlock).not.toContain("2S10S_CMT");
  });

  it("uses no animated-flow, strength, probability or ranking presentation", () => {
    const lc = html.toLowerCase();
    for (const banned of [
      "animation",
      "animate-",
      "progress",
      "strength",
      "probability",
      "score",
      "winner",
      "strongest",
      "ranked",
      "best cell",
    ]) {
      expect(lc, banned).not.toContain(banned);
    }
  });
});

describe("MissionJEvidenceCard — J1B robustness record", () => {
  it("leads with 12/12 ELEVATED and the three BROAD panels", () => {
    expect(visible).toContain("12/12");
    expect(visible).toContain("ELEVATED");
    const broad = visible.match(/BROAD MEASUREMENT CONSISTENCY/g);
    expect(broad?.length).toBeGreaterThanOrEqual(3);
  });

  it("attaches the correlated-view disclosure and measurement-limited rates path", () => {
    expect(visible).toContain("correlated robustness views");
    expect(visible.toLowerCase()).toContain("fed funds futures / ois");
  });

  it("renders all 12 cells in frozen order with exact published values", () => {
    const order = [
      "KRE", "IAT", "KBE", "XLF", "VFH",
    ];
    // rolling-beta block precedes the raw-return block (frozen order 1..12)
    const first = visible.indexOf("rolling_beta_ar");
    const raw = visible.indexOf("raw_return");
    expect(first).toBeGreaterThan(-1);
    expect(raw).toBeGreaterThan(first);
    for (const m of order) expect(visible).toContain(m);
    expect(visible).toContain("0.664719"); // cell 1 MEMP, exact precision
    expect(visible).toContain("1.000000"); // cell 2 calibration, trailing zeros
    expect(visible).toContain("0.579295"); // cell 12 MEMP
    expect(visible).toContain("2Y_CMT");
    expect(visible).toContain("SHY");
  });

  it("renders denominators: 64 / 65 beta cells, 65 / 65 raw cells, references", () => {
    expect(visible).toContain("64 / 65");
    expect(visible).toContain("65 / 65");
    expect(visible).toContain("1797");
    expect(visible).toContain("1816");
    expect(visible).toContain("1804");
    expect(visible).toContain("2018-01-31"); // the published unavailable event
  });

  it("shows overlays including F3 sign status", () => {
    expect(visible).toContain("0/8");
    expect(visible).toContain("0/64");
    const noFlip = visible.match(/no flip/g);
    expect(noFlip?.length).toBeGreaterThanOrEqual(12);
  });
});

describe("MissionJEvidenceCard — J2 timing challenge", () => {
  it("renders all four state-bearing cells with both ORDINARY / UNRESOLVED visible", () => {
    for (const m of ["raw_return", "spy_relative_ar", "sector_relative_ar", "sar"]) {
      expect(visible).toContain(m);
    }
    const ou = visible.match(/ORDINARY \/ UNRESOLVED/g);
    expect(ou?.length).toBeGreaterThanOrEqual(2);
    expect(visible).toContain("0.491240"); // raw pre-event MEMP shown, not hidden
    expect(visible).toContain("1427");     // timing reference N
  });

  it("shows the timing qualifier and the raw-cell fragility", () => {
    expect(visible).toContain(
      "timing evidence is lens-dependent under daily measurement",
    );
    expect(visible).toContain("4/8");
    expect(visible).toContain("32/65");
    expect(visible.toLowerCase()).toContain("knife-edge");
  });

  it("keeps D1-D4 descriptive-only and stateless under a labeled block", () => {
    expect(visible).toContain("Descriptive [-20, -1] diagnostics");
    for (const d of ["D1", "D2", "D3", "D4"]) expect(visible).toContain(d);
    expect(visible).toContain(
      "no ordinary-reference state is assigned under the frozen procedure",
    );
    // the diagnostics table carries no state or calibration column
    const diagBlock = visible.slice(visible.indexOf("Descriptive [-20, -1]"));
    expect(diagBlock).toContain("-0.071910"); // D4 median, signed
    const idxD1 = diagBlock.indexOf("D1");
    const elevatedAfterD1 = diagBlock.slice(idxD1).indexOf("ELEVATED");
    expect(elevatedAfterD1).toBe(-1);
  });
});

describe("MissionJEvidenceCard — collision qualification", () => {
  it("shows the exact denominators and the C2 register facts", () => {
    expect(visible).toContain("0 of 65");
    expect(visible).toContain("opec-known-date-exclusion-register@i0-v1");
    expect(visible).toContain("insufficient subset under the frozen procedure");
  });

  it("makes C1 unadjudicability prominent with its reason", () => {
    expect(visible).toContain("UNADJUDICABLE");
    expect(visible).toContain("BLS CPI and BLS Employment Situation");
    expect(visible.toLowerCase()).toContain("no source-pinned bls release register");
  });

  it("never describes the frame as clean or free of competing events", () => {
    const lc = visible.toLowerCase();
    expect(lc).not.toContain("free of competing events");
    // the frozen limitation NEGATES the clean-window claim verbatim; no
    // other "clean" wording may exist anywhere in the card
    const scrubbed = lc.replace(
      /no stronger clean-window claim exists/g,
      "",
    );
    expect(scrubbed).not.toMatch(/\bclean\b/);
    expect(lc).toContain("outside known-register collisions");
  });
});

describe("MissionJEvidenceCard — claim limits and ceilings", () => {
  it("renders the claim-limit block with the required non-claims", () => {
    for (const token of [
      "causality",
      "prediction;",
      "tradeability;",
      "alpha;",
      "independent historical confirmation",
      "intraday sequencing",
      "structural macro model",
    ]) {
      expect(visible).toContain(token);
    }
  });

  it("shows the Class B ceiling and no-new-statistics statement", () => {
    expect(visible).toContain("same-sample Class B");
    expect(visible).toContain("computes no research statistic");
    expect(visible).toContain("mechanism-consistent descriptive pattern");
  });

  it("carries no assertive claim framing", () => {
    const lc = visible.toLowerCase();
    for (const banned of [
      "mechanism confirmed",
      "validated",
      "actionable",
    ]) {
      expect(lc, banned).not.toContain(banned);
    }
    // word-boundary: "provenance" is legitimate; bare claim words are not
    for (const banned of [/\bproven\b/, /\bbuy\b/, /\bsell\b/]) {
      expect(lc).not.toMatch(banned);
    }
  });
});

describe("MissionJEvidenceCard — states and structure", () => {
  it("renders an honest loading state when data is absent", () => {
    const loading = render({ data: undefined });
    expect(loading.toLowerCase()).toContain("loading the mission j");
    expect(loading).not.toContain("0.664719");
  });

  it("renders an explicit unavailable state instead of fake values", () => {
    const unavailable = render({ data: undefined, unavailable: true });
    expect(unavailable.toLowerCase()).toContain("unavailable");
    expect(unavailable).toContain("/evidence/mission-j");
    expect(unavailable).not.toContain("0.664719");
    expect(unavailable).not.toContain("PROPAGATED");
  });

  it("treats a malformed payload as unavailable rather than crashing or guessing", () => {
    const malformed = render({
      // deliberately wrong shape
      data: { contract_version: "mission-j-evidence-v1" } as never,
    });
    expect(malformed.toLowerCase()).toContain("did not match the expected contract");
    expect(malformed).not.toContain("PROPAGATED");
  });

  it("keeps dense tables inside bounded horizontal-scroll containers", () => {
    expect(html).toContain("overflow-x-auto");
    expect(html).toContain("<table");
    expect(html).toContain('scope="col"');
  });

  it("renders deterministically", () => {
    expect(render({ data: missionJFixture() })).toBe(
      render({ data: missionJFixture() }),
    );
  });
});
