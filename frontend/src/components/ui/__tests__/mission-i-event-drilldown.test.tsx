/**
 * E2 — Mission I event-level evidence drilldown (mission-i-evidence-v2).
 *
 * The drilldown lets a skeptical reviewer move from each available
 * published family/horizon/metric cell to its exact denominator, its
 * published and internally recomputed aggregates, its reconciliation
 * status, and its publication-ordered event observations — without any
 * new statistic, outcome ranking, or claim expansion.
 *
 * These tests pin the E2 contract:
 *   - the captured v2 fixture keeps 904 event rows, 20 event-level cells
 *     in frozen order, 65/32 per-cell denominators, no FOMC 20d cell,
 *     and every cell internally reconciled;
 *   - opening a cell shows its identity, separately labeled published /
 *     recomputed aggregates, denominators, evidence class, method wording,
 *     provenance (nulls stated, never inferred), and the explicit
 *     non-claim;
 *   - default row order is the publication's own (ascending anchor
 *     session); nothing default-sorts by response or percentile, and
 *     progressive disclosure (25-row pages) never reorders;
 *   - only the selected cell's event table is mounted; closing releases
 *     it; FOMC 20d stays visibly unavailable and non-actionable;
 *   - absent, malformed, valid-empty, and loading states stay distinct
 *     and fail closed with no fabricated empty state;
 *   - the disclosure controls are semantic buttons with the full
 *     aria-expanded / aria-controls contract.
 *
 * Render-smoke pattern (renderToStaticMarkup, no jsdom); interaction
 * state is exercised through the documented starting-selection props
 * (the ReactionProfileCard `initialHorizon` precedent) and the real
 * browser smoke.
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import type {
  MissionIEventLevelCell,
  MissionIEventRow,
  MissionIEvidenceSummary,
} from "@/lib/api";
import { MissionIEvidenceCard } from "../mission-i-evidence-card";
import {
  EVENT_ROWS_PAGE_SIZE,
  MissionIEventLevelPanel,
  missionIEventLevelState,
  visibleEventRows,
} from "../mission-i-event-drilldown";
import { missionIFixture } from "./mission-i-fixture";

function visibleText(html: string): string {
  return html
    .replace(/<[^>]*>/g, " ")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();
}

function countTags(html: string, tag: string): number {
  return (html.match(new RegExp(`<${tag}[\\s>]`, "g")) ?? []).length;
}

const fixture = missionIFixture();
const eventLevel = fixture.event_level!;
const FOMC_CELL_KEY = "FOMC|1d|raw_return";
const OPEC_CELL_KEY = "OPEC|1d|raw_return";
const KNIFE_CELL_KEY = "FOMC|5d|raw_return";
const fomcCell = eventLevel.cells.find((c) => c.cell_key === FOMC_CELL_KEY)!;
const opecCell = eventLevel.cells.find((c) => c.cell_key === OPEC_CELL_KEY)!;

const closedCardHtml = renderToStaticMarkup(
  <MissionIEvidenceCard data={missionIFixture()} />,
);
const openFomcCardHtml = renderToStaticMarkup(
  <MissionIEvidenceCard
    data={missionIFixture()}
    initialOpenCellKey={FOMC_CELL_KEY}
  />,
);

function panelHtml(cellKey: string, initialRowsShown?: number): string {
  return renderToStaticMarkup(
    <MissionIEventLevelPanel
      data={missionIFixture()}
      cellKey={cellKey}
      panelId="test-panel"
      initialRowsShown={initialRowsShown}
    />,
  );
}

// ---------------------------------------------------------------------------
// 1–7. Captured v2 fixture acceptance — the published event-level contract
// ---------------------------------------------------------------------------

describe("mission-i-evidence-v2 fixture — event-level contract acceptance", () => {
  it("carries the v2 contract version and a contract-shaped event_level block", () => {
    expect(fixture.contract_version).toBe("mission-i-evidence-v2");
    expect(missionIEventLevelState(fixture)).toBe("ok");
  });

  it("sources the event-level block from the same tracked I2B publication", () => {
    expect(eventLevel.source.artifact).toBe(
      fixture.provenance.sources.i2b_memp.artifact,
    );
    expect(eventLevel.source.sha256).toBe(
      fixture.provenance.sources.i2b_memp.sha256,
    );
    expect(eventLevel.source.bytes).toBe(
      fixture.provenance.sources.i2b_memp.bytes,
    );
    expect(eventLevel.source.row_count).toBe(904);
  });

  it("accounts for exactly 904 event rows, split 520 FOMC / 384 OPEC", () => {
    expect(eventLevel.total_rows).toBe(904);
    expect(eventLevel.family_counts).toEqual({ FOMC: 520, OPEC: 384 });
    const summed = eventLevel.cells.reduce((n, c) => n + c.rows.length, 0);
    expect(summed).toBe(904);
  });

  it("keeps exactly 20 event-level cells aligned 1:1 with the primary cells", () => {
    expect(eventLevel.cells).toHaveLength(20);
    expect(eventLevel.cells.map((c) => c.cell_key)).toEqual(
      fixture.primary_cells.map((c) => c.cell_key),
    );
    expect(eventLevel.cells.map((c) => c.cell)).toEqual(
      Array.from({ length: 20 }, (_, i) => i + 1),
    );
  });

  it("has no FOMC 20d event-level cell — the horizon is structurally unavailable", () => {
    expect(
      eventLevel.cells.filter(
        (c) => c.family === "FOMC" && c.horizon === "20d",
      ),
    ).toHaveLength(0);
  });

  it("carries 65 rows on every FOMC cell and 32 on every OPEC cell", () => {
    for (const cell of eventLevel.cells) {
      const want = cell.family === "FOMC" ? 65 : 32;
      expect(cell.event_n, cell.cell_key).toBe(want);
      expect(cell.rows, cell.cell_key).toHaveLength(want);
    }
  });

  it("keeps all 20 cells reconciled: published equals recomputed, matching the aggregate surface", () => {
    for (const [i, cell] of eventLevel.cells.entries()) {
      expect(cell.reconciled, cell.cell_key).toBe(true);
      expect(cell.recomputed, cell.cell_key).toEqual(cell.published);
      expect(cell.published.memp, cell.cell_key).toBe(
        fixture.primary_cells[i].memp,
      );
      expect(cell.published.signed_percentile_median, cell.cell_key).toBe(
        fixture.primary_cells[i].signed_percentile_median,
      );
    }
  });

  it("keeps every cell's rows in the publication's ascending anchor-session order", () => {
    for (const cell of eventLevel.cells) {
      const anchors = cell.rows.map((r) => r.anchor_session);
      expect(anchors, cell.cell_key).toEqual([...anchors].sort());
      expect(new Set(anchors).size, cell.cell_key).toBe(anchors.length);
    }
  });
});

// ---------------------------------------------------------------------------
// 8 + 11 + 12. Opened panel — identity, aggregate contract, denominators
// ---------------------------------------------------------------------------

describe("MissionIEventLevelPanel — cell identity and aggregate contract", () => {
  const html = panelHtml(FOMC_CELL_KEY);
  const text = visibleText(html);

  it("states the opened cell's family, horizon, and metric with the raw identity", () => {
    expect(text).toContain("FOMC");
    expect(text).toContain("1d");
    expect(text).toContain("raw return");
    expect(text).toContain(FOMC_CELL_KEY);
  });

  it("keeps published and recomputed aggregates separately labeled, never one value", () => {
    const lc = text.toLowerCase();
    expect(lc).toContain("published");
    expect(lc).toContain("recomputed");
    const memp = fomcCell.published.memp;
    expect((html.match(new RegExp(memp.replace(".", "\\."), "g")) ?? []).length)
      .toBeGreaterThanOrEqual(2);
    expect(lc).toContain("reconciled");
  });

  it("shows the eligible denominators and the event-level row count", () => {
    const primary = fixture.primary_cells.find(
      (c) => c.cell_key === FOMC_CELL_KEY,
    )!;
    expect(text).toContain(`${fomcCell.event_n}`);
    expect(text).toContain(`${primary.reference_n_available}`);
    expect(text.toLowerCase()).toContain("event n");
    expect(text.toLowerCase()).toContain("reference n");
  });

  it("names the evidence class as descriptive, same-sample reconciliation evidence", () => {
    const lc = text.toLowerCase();
    expect(lc).toContain("descriptive");
    expect(lc).toContain("same-sample");
  });

  it("shows the correct family identity for an OPEC cell", () => {
    const opecText = visibleText(panelHtml(OPEC_CELL_KEY));
    expect(opecText).toContain("OPEC");
    expect(opecText).toContain(OPEC_CELL_KEY);
    expect(opecText).toContain(`${opecCell.event_n}`);
  });

  it("keeps the FOMC 5d raw knife-edge warning visible on its own cell", () => {
    const knifeText = visibleText(panelHtml(KNIFE_CELL_KEY));
    expect(knifeText).toContain("knife-edge");
    // ...and not on cells it does not describe
    expect(visibleText(panelHtml(FOMC_CELL_KEY))).not.toContain("knife-edge");
  });
});

// ---------------------------------------------------------------------------
// 9 + 10 + 13. Publication order, no outcome sorting, pagination
// ---------------------------------------------------------------------------

describe("MissionIEventLevelPanel — publication order and progressive disclosure", () => {
  it("renders the first page in the publication's own order", () => {
    const html = panelHtml(FOMC_CELL_KEY);
    let last = -1;
    for (const row of fomcCell.rows.slice(0, EVENT_ROWS_PAGE_SIZE)) {
      const idx = html.indexOf(row.anchor_session);
      expect(idx, row.anchor_session).toBeGreaterThan(last);
      last = idx;
    }
  });

  it("does not default-sort by response or percentile (payload order is not outcome order)", () => {
    const firstPage = fomcCell.rows.slice(0, EVENT_ROWS_PAGE_SIZE);
    const byAbs = [...firstPage].sort((a, b) =>
      a.abs_mid_rank_pct.localeCompare(b.abs_mid_rank_pct),
    );
    const byResponse = [...firstPage].sort((a, b) =>
      a.response.localeCompare(b.response),
    );
    // the publication order genuinely differs from every outcome order…
    expect(firstPage).not.toEqual(byAbs);
    expect(firstPage).not.toEqual(byResponse);
    // …and the rendered order is the publication order (asserted above),
    // while the pure helper never reorders whatever it is given:
    expect(visibleEventRows(byAbs, 10)).toEqual(byAbs.slice(0, 10));
  });

  it("mounts only the first 25 rows initially, with an honest show-more control", () => {
    const html = panelHtml(FOMC_CELL_KEY);
    expect(EVENT_ROWS_PAGE_SIZE).toBe(25);
    const rowCount = (html.match(/data-mi-event-row/g) ?? []).length;
    expect(rowCount).toBe(25);
    const text = visibleText(html).toLowerCase();
    expect(text).toContain("25 of 65");
    expect(text).toContain("show");
  });

  it("keeps deeper pages in the same order and never re-sorts (show-more contract)", () => {
    expect(visibleEventRows(fomcCell.rows, 50)).toEqual(
      fomcCell.rows.slice(0, 50),
    );
    expect(visibleEventRows(fomcCell.rows, 999)).toEqual(fomcCell.rows);
    const html = panelHtml(FOMC_CELL_KEY, 65);
    let last = -1;
    for (const row of fomcCell.rows) {
      const idx = html.indexOf(row.anchor_session);
      expect(idx, row.anchor_session).toBeGreaterThan(last);
      last = idx;
    }
    expect((html.match(/data-mi-event-row/g) ?? []).length).toBe(65);
    // the fully disclosed page reports itself honestly and offers no
    // further disclosure
    expect(visibleText(html).toLowerCase()).toContain("65 of 65");
  });

  it("uses stable row keys from the cell/event identity (no index-keyed rows)", () => {
    // Stable keys are exercised indirectly: every rendered row carries the
    // event identity, and event slugs are unique within a cell.
    const html = panelHtml(FOMC_CELL_KEY);
    for (const row of fomcCell.rows.slice(0, EVENT_ROWS_PAGE_SIZE)) {
      expect(html).toContain(row.event);
    }
    const slugs = new Set(fomcCell.rows.map((r) => r.event));
    expect(slugs.size).toBe(fomcCell.rows.length);
  });
});

// ---------------------------------------------------------------------------
// 14. Card integration — only the selected cell's table is mounted
// ---------------------------------------------------------------------------

describe("MissionIEvidenceCard — bounded mounting of the event surface", () => {
  it("mounts no event-level row on the closed card", () => {
    expect(closedCardHtml).not.toContain("data-mi-event-row");
    expect(closedCardHtml).not.toContain(fomcCell.rows[0].event);
    expect(closedCardHtml).not.toContain(opecCell.rows[0].event);
  });

  it("mounts exactly one first page when a cell starts open — and nothing from other cells", () => {
    const rowCount = (openFomcCardHtml.match(/data-mi-event-row/g) ?? [])
      .length;
    expect(rowCount).toBe(EVENT_ROWS_PAGE_SIZE);
    expect(openFomcCardHtml).toContain(fomcCell.rows[0].event);
    // same events exist in other FOMC cells, so discriminate by the other
    // cells' distinct response values; OPEC rows must be absent entirely.
    expect(openFomcCardHtml).not.toContain(opecCell.rows[0].event);
    const otherFomc = eventLevel.cells.find(
      (c) => c.cell_key === "FOMC|1d|spy_relative_ar",
    )!;
    expect(openFomcCardHtml).not.toContain(otherFomc.rows[0].abs_mid_rank_pct);
  });

  it("re-resolves an unavailable or unknown starting cell to closed", () => {
    for (const bad of ["FOMC|20d|raw_return", "nonsense", ""]) {
      const html = renderToStaticMarkup(
        <MissionIEvidenceCard
          data={missionIFixture()}
          initialOpenCellKey={bad}
        />,
      );
      expect(html, `initialOpenCellKey=${bad}`).not.toContain(
        "data-mi-event-row",
      );
    }
  });
});

// ---------------------------------------------------------------------------
// 15 + 16. Fail-closed semantics — absent, malformed, valid-empty, loading
// ---------------------------------------------------------------------------

describe("event-level fail-closed semantics", () => {
  function summaryWith(
    mutate: (s: MissionIEvidenceSummary) => void,
  ): MissionIEvidenceSummary {
    const s = missionIFixture();
    mutate(s);
    return s;
  }

  it("classifies a missing event_level block as absent", () => {
    expect(
      missionIEventLevelState(summaryWith((s) => delete s.event_level)),
    ).toBe("absent");
  });

  it("classifies structural damage as malformed, never absent or ok", () => {
    const damaged: Array<(s: MissionIEvidenceSummary) => void> = [
      (s) => {
        (s.event_level as unknown as Record<string, unknown>).cells =
          "not-an-array";
      },
      (s) => {
        s.event_level!.cells[0].rows.pop(); // row count vs event_n drift
      },
      (s) => {
        s.event_level!.total_rows = 903; // total vs summed rows drift
      },
      (s) => {
        (s.event_level!.cells[3].rows[0] as unknown as Record<string, unknown>)
          .abs_mid_rank_pct = 0.5; // number where the contract has a string
      },
      (s) => {
        (s.event_level!.cells[0] as unknown as Record<string, unknown>)
          .published = undefined;
      },
      (s) => {
        (s.event_level!.method as unknown as Record<string, unknown>)
          .claim_ceiling = undefined;
      },
      (s) => {
        s.event_level!.cells[0].reconciled =
          false as boolean; // an unreconciled cell can never be served
      },
    ];
    for (const [i, mutate] of damaged.entries()) {
      expect(missionIEventLevelState(summaryWith(mutate)), `variant ${i}`).toBe(
        "malformed",
      );
    }
  });

  it("keeps a structure-valid zero-row cell distinct from malformed (honest empty, never fabricated)", () => {
    // The valid-zero-row construction must be CROSS-SURFACE consistent to
    // stay valid under the exact contract: both surfaces carry the zero
    // denominator and every whole-block count is restated to match.  (The
    // published contract contains no such cell; this pins the semantic
    // distinction, not a displayable expectation.)
    const s = summaryWith((sm) => {
      sm.primary_cells[0].event_n_available = 0;
      sm.event_level!.cells[0] = {
        ...sm.event_level!.cells[0],
        event_n: 0,
        rows: [],
      };
      sm.event_level!.total_rows = 904 - 65;
      sm.event_level!.source.row_count = 904 - 65;
      sm.event_level!.family_counts.FOMC = 520 - 65;
    });
    expect(missionIEventLevelState(s)).toBe("ok");
    const html = renderToStaticMarkup(
      <MissionIEventLevelPanel
        data={s}
        cellKey={FOMC_CELL_KEY}
        panelId="test-panel"
      />,
    );
    const text = visibleText(html).toLowerCase();
    expect(text).toContain("0 of 0");
    expect(html).not.toContain("data-mi-event-row");
    expect(text).not.toContain("did not match");
  });

  it("fails closed on a malformed block: aggregates stay, disclosure is refused explicitly", () => {
    const s = summaryWith((sm) => {
      (sm.event_level as unknown as Record<string, unknown>).cells =
        "not-an-array";
    });
    const html = renderToStaticMarkup(<MissionIEvidenceCard data={s} />);
    const text = visibleText(html);
    // the aggregate 20-cell surface is still served…
    expect(text).toContain("0.674559");
    // …but no disclosure control is actionable and the refusal is explicit
    expect(html).not.toContain("data-mi-event-row");
    expect(html).not.toContain("aria-expanded");
    expect(text).toContain("Event-level disclosure unavailable");
    expect(text.toLowerCase()).toContain("did not match");
  });

  it("treats an absent block as unavailable with distinct wording, not an error and not an empty table", () => {
    const s = summaryWith((sm) => delete sm.event_level);
    const html = renderToStaticMarkup(<MissionIEvidenceCard data={s} />);
    const text = visibleText(html);
    expect(text).toContain("0.674559");
    expect(html).not.toContain("data-mi-event-row");
    expect(html).not.toContain("aria-expanded");
    expect(text).toContain("Event-level disclosure unavailable");
    expect(text.toLowerCase()).toContain("carries no event-level block");
    expect(text.toLowerCase()).not.toContain("did not match");
  });

  it("keeps the loading state free of any drilldown affordance", () => {
    const html = renderToStaticMarkup(<MissionIEvidenceCard />);
    expect(html).not.toContain("aria-expanded");
    expect(html).not.toContain("data-mi-event-row");
  });
});

// ---------------------------------------------------------------------------
// 17 + 18. Provenance nulls and the explicit non-claim
// ---------------------------------------------------------------------------

describe("MissionIEventLevelPanel — provenance and the explicit non-claim", () => {
  const text = visibleText(panelHtml(FOMC_CELL_KEY));

  it("shows the payload provenance without inventing missing values", () => {
    expect(text).toContain("mission-i-evidence-v2");
    expect(text).toContain("stats/I2B_MEMP_PRIMARY_COMPARISON.md");
    expect(text).toContain("904");
    // computation dates / execution commits are null in the payload and
    // stay visibly unrecorded — never inferred from the current checkout
    expect(text).toContain(
      "computation dates and execution commits: not recorded in any Mission I publication",
    );
    expect(text).not.toMatch(/execution commit: [0-9a-f]{7}/);
  });

  it("renders the explicit non-claim verbatim", () => {
    expect(text).toContain(
      "Event-level rows are reconciliation evidence for the published descriptive cell. They are not independent replication, causal estimates, statistical significance, forecasts, trade signals or representative-case proof.",
    );
  });

  it("carries the method context: mid-rank percentile, ordering, precision, claim ceiling", () => {
    expect(text).toContain(eventLevel.method.aggregate_definition);
    expect(text).toContain(eventLevel.method.ordering_statement);
    expect(text).toContain(eventLevel.method.claim_ceiling);
    expect(text.toLowerCase()).toContain("mid-rank");
  });

  it("labels the percentile columns with the published method names, never a strength or model framing", () => {
    const lc = text.toLowerCase();
    expect(lc).toContain("abs mid-rank pct");
    expect(lc).toContain("signed pct");
    for (const banned of ["strength", "model rank", "probability", "z-score"]) {
      expect(lc, banned).not.toContain(banned);
    }
  });
});

// ---------------------------------------------------------------------------
// 19. Keyboard / ARIA disclosure contract
// ---------------------------------------------------------------------------

describe("disclosure accessibility contract", () => {
  it("renders one semantic disclosure button per available cell, none for FOMC 20d", () => {
    const buttons =
      closedCardHtml.match(/<button[^>]*aria-expanded[^>]*>/g) ?? [];
    expect(buttons).toHaveLength(20);
    for (const b of buttons) {
      expect(b).toContain('type="button"');
      expect(b).toContain('aria-expanded="false"');
      expect(b).toContain("aria-controls=");
    }
    expect(visibleText(closedCardHtml)).toContain("structurally infeasible");
  });

  it("marks the open cell's button expanded and wires it to the mounted panel", () => {
    const expanded =
      openFomcCardHtml.match(/<button[^>]*aria-expanded="true"[^>]*>/g) ?? [];
    expect(expanded).toHaveLength(1);
    const controls = /aria-controls="([^"]+)"/.exec(expanded[0])![1];
    expect(openFomcCardHtml).toContain(`id="${controls}"`);
    const region = new RegExp(
      `<section[^>]*id="${controls}"[^>]*aria-labelledby="([^"]+)"`,
    ).exec(openFomcCardHtml);
    expect(region).not.toBeNull();
    expect(openFomcCardHtml).toContain(`id="${region![1]}"`);
  });

  it("announces cell identity and row count from the panel label", () => {
    const html = panelHtml(FOMC_CELL_KEY);
    const labelled = /aria-labelledby="([^"]+)"/.exec(html);
    expect(labelled).not.toBeNull();
    const labelId = labelled![1];
    const label = new RegExp(
      `<[^>]*id="${labelId}"[^>]*>([\\s\\S]*?)</`,
    ).exec(html);
    const labelText = visibleText(label![1]);
    expect(labelText).toContain("FOMC");
    expect(labelText).toContain("65");
  });

  it("gives the event table meaningful headers and the panel a keyboard-reachable close", () => {
    const html = panelHtml(FOMC_CELL_KEY);
    for (const header of [
      "event",
      "anchor session",
      "response",
      "abs mid-rank pct",
      "signed pct",
    ]) {
      expect(visibleText(html).toLowerCase()).toContain(header);
    }
    expect(html).toMatch(/<th scope="col"/);
    expect(html).toMatch(/<button[^>]*type="button"[^>]*>(?:[^<]*close)/i);
  });

  it("uses no clickable div anywhere in the drilldown surface", () => {
    for (const html of [closedCardHtml, openFomcCardHtml]) {
      expect(html).not.toMatch(/<div[^>]*(?:onclick|role="button"|tabindex)/i);
    }
  });
});

// ---------------------------------------------------------------------------
// 20. The existing aggregate surface stays intact around the drilldown
// ---------------------------------------------------------------------------

describe("existing Mission I surface preserved", () => {
  it("keeps the closed card's aggregate facts unchanged by the drilldown", () => {
    const text = visibleText(closedCardHtml);
    expect(text).toContain("FOMC events 65");
    expect(text).toContain("OPEC events 32");
    expect(text).toContain("Primary cells 20");
    expect(text).toContain("mission-i-evidence-v2");
    for (const cell of fixture.primary_cells) {
      expect(closedCardHtml, cell.cell_key).toContain(cell.memp);
    }
    expect(text).toContain("structurally infeasible");
    expect(text).toContain("not a data gap");
  });

  it("adds no drilldown table row count to the closed card beyond the disclosure column", () => {
    const closedTrCount = countTags(closedCardHtml, "tr");
    const openTrCount = countTags(openFomcCardHtml, "tr");
    // opening one cell adds exactly the panel's header row + 25 event rows
    expect(openTrCount - closedTrCount).toBe(EVENT_ROWS_PAGE_SIZE + 1);
  });
});

// ---------------------------------------------------------------------------
// Claim-language honesty on the OPENED surface (the closed card is covered
// by the existing card suite; the panel introduces new copy, so the same
// affirmative bans apply — the explicit non-claim is the one sanctioned
// negation site inside the panel).
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// E2 repair — exact contract validation.  Every internally inconsistent or
// cross-surface-inconsistent event-level payload must classify malformed and
// fail closed: zero disclosure controls, zero mounted rows, explicit
// refusal.  Each mutation below is deliberately constructed to keep the
// SHALLOW invariants (field shapes, local row totals) intact wherever
// possible, so only the exact cross-surface contract can reject it.
// ---------------------------------------------------------------------------

interface ContractMutation {
  name: string;
  mutate: (s: MissionIEvidenceSummary) => void;
}

function cloneCell(c: MissionIEventLevelCell): MissionIEventLevelCell {
  return structuredClone(c);
}

const CONTRACT_MUTATIONS: ContractMutation[] = [
  {
    name: "contract version is not mission-i-evidence-v2",
    mutate: (s) => {
      s.contract_version = "mission-i-evidence-v1";
    },
  },
  {
    name: "19 event-level cells (whole-block counts restated to match)",
    mutate: (s) => {
      const dropped = s.event_level!.cells.pop()!;
      s.event_level!.total_rows -= dropped.rows.length;
      s.event_level!.source.row_count -= dropped.rows.length;
      s.event_level!.family_counts.OPEC -= dropped.rows.length;
    },
  },
  {
    name: "21 event-level cells (whole-block counts restated to match)",
    mutate: (s) => {
      const extra = cloneCell(s.event_level!.cells[19]);
      extra.cell = 21;
      s.event_level!.cells.push(extra);
      s.event_level!.total_rows += extra.rows.length;
      s.event_level!.source.row_count += extra.rows.length;
      s.event_level!.family_counts.OPEC += extra.rows.length;
    },
  },
  {
    name: "duplicate cell number",
    mutate: (s) => {
      s.event_level!.cells[1].cell = 1;
    },
  },
  {
    name: "duplicate cell_key",
    mutate: (s) => {
      s.event_level!.cells[1].cell_key = s.event_level!.cells[0].cell_key;
    },
  },
  {
    name: "cells reordered relative to primary_cells",
    mutate: (s) => {
      const cells = s.event_level!.cells;
      [cells[0], cells[1]] = [cells[1], cells[0]];
    },
  },
  {
    name: "family/horizon/metric identity differs from its primary cell",
    mutate: (s) => {
      s.event_level!.cells[0].metric = "sar"; // valid vocabulary, wrong cell
    },
  },
  {
    name: "event_n differs from the primary-cell event denominator",
    mutate: (s) => {
      const cell = s.event_level!.cells[0];
      cell.rows = cell.rows.slice(0, 64);
      cell.event_n = 64; // internally consistent — only cross-surface catches
      s.event_level!.total_rows -= 1;
      s.event_level!.source.row_count -= 1;
      s.event_level!.family_counts.FOMC -= 1;
    },
  },
  {
    name: "published MEMP differs from the primary cell",
    mutate: (s) => {
      s.event_level!.cells[0].published.memp = "0.999999";
      s.event_level!.cells[0].recomputed.memp = "0.999999"; // internally equal
    },
  },
  {
    name: "published signed median differs from the primary cell",
    mutate: (s) => {
      s.event_level!.cells[0].published.signed_percentile_median = "0.111111";
      s.event_level!.cells[0].recomputed.signed_percentile_median = "0.111111";
    },
  },
  {
    name: "published differs from recomputed while reconciled stays true",
    mutate: (s) => {
      s.event_level!.cells[0].recomputed.memp = "0.123456";
    },
  },
  {
    name: "source.row_count differs from total_rows",
    mutate: (s) => {
      s.event_level!.source.row_count = 903;
    },
  },
  {
    // Already rejected by the pre-repair validator; kept in the battery so
    // the exact contract is pinned in one place.
    name: "total_rows differs from the summed rows",
    mutate: (s) => {
      s.event_level!.total_rows = 903;
    },
  },
  {
    name: "family_counts.FOMC differs from the actual FOMC rows",
    mutate: (s) => {
      s.event_level!.family_counts.FOMC = 519;
    },
  },
  {
    name: "family_counts.OPEC differs from the actual OPEC rows",
    mutate: (s) => {
      s.event_level!.family_counts.OPEC = 383;
    },
  },
  {
    name: "an unexpected family-count key is inserted",
    mutate: (s) => {
      (s.event_level!.family_counts as unknown as Record<string, number>).SPX = 0;
    },
  },
  {
    name: "a synthetic FOMC 20d cell is inserted (whole-block counts restated)",
    mutate: (s) => {
      const synthetic = cloneCell(s.event_level!.cells[0]);
      synthetic.cell = 21;
      synthetic.cell_key = "FOMC|20d|raw_return";
      synthetic.horizon = "20d";
      s.event_level!.cells.push(synthetic);
      s.event_level!.total_rows += synthetic.rows.length;
      s.event_level!.source.row_count += synthetic.rows.length;
      s.event_level!.family_counts.FOMC += synthetic.rows.length;
    },
  },
  {
    name: "invalid horizon vocabulary (matched on both surfaces)",
    mutate: (s) => {
      // Both surfaces mutated identically so cross-surface identity still
      // matches — only the frozen vocabulary check can reject this.
      (s.primary_cells[0] as unknown as Record<string, unknown>).horizon = "3d";
      (s.event_level!.cells[0] as unknown as Record<string, unknown>).horizon =
        "3d";
      (s.primary_cells[0] as unknown as Record<string, unknown>).cell_key =
        "FOMC|3d|raw_return";
      (s.event_level!.cells[0] as unknown as Record<string, unknown>).cell_key =
        "FOMC|3d|raw_return";
    },
  },
  {
    name: "duplicate event identity inside one cell",
    mutate: (s) => {
      const rows = s.event_level!.cells[0].rows;
      rows[1] = { ...rows[1], event: rows[0].event }; // anchors stay ascending
    },
  },
  {
    name: "rows out of ascending anchor-session publication order",
    mutate: (s) => {
      const rows = s.event_level!.cells[0].rows;
      [rows[0], rows[1]] = [rows[1], rows[0]];
    },
  },
];

describe("exact contract validation — inconsistent payloads fail closed", () => {
  for (const { name, mutate } of CONTRACT_MUTATIONS) {
    it(`rejects: ${name}`, () => {
      const s = missionIFixture();
      mutate(s);
      expect(missionIEventLevelState(s)).toBe("malformed");
      // Even a requested starting cell must not open on a malformed block:
      // zero disclosure controls, zero mounted rows, explicit refusal.
      const html = renderToStaticMarkup(
        <MissionIEvidenceCard data={s} initialOpenCellKey={FOMC_CELL_KEY} />,
      );
      expect(html).not.toContain("aria-expanded");
      expect(html).not.toContain("data-mi-event-row");
      const text = visibleText(html);
      expect(text).toContain("Event-level disclosure unavailable");
      expect(text.toLowerCase()).toContain("did not match");
    });
  }

  it("still accepts the exact served v2 payload after all mutation tests", () => {
    expect(missionIEventLevelState(missionIFixture())).toBe("ok");
  });
});

// ---------------------------------------------------------------------------
// E2 repair — the provenance limitation the v2 contract actually has: no
// source-section field is exposed, and the panel must say so rather than
// silently omitting it or inferring a heading from repository knowledge.
// ---------------------------------------------------------------------------

describe("provenance limitation — source section not exposed by v2", () => {
  const text = visibleText(panelHtml(FOMC_CELL_KEY));

  it("states the source-section limitation explicitly", () => {
    expect(text).toContain(
      "Source section: not exposed by mission-i-evidence-v2.",
    );
  });

  it("infers no section heading from the parser, filename, or repository", () => {
    expect(text).not.toContain("Per-event percentile surface");
    expect(text).not.toContain("##");
  });

  it("keeps the full source identity accessible: artifact, full hash, bytes, row count", () => {
    expect(text).toContain(eventLevel.source.artifact);
    expect(text).toContain(eventLevel.source.sha256);
    expect(text).toContain(`${eventLevel.source.bytes}`);
    expect(text).toContain(`${eventLevel.source.row_count}`);
  });

  it("keeps the null computation/execution provenance visible alongside the limitation", () => {
    expect(text).toContain(
      "computation dates and execution commits: not recorded in any Mission I publication",
    );
  });
});

describe("opened drilldown — claim-language honesty", () => {
  const panels = [FOMC_CELL_KEY, OPEC_CELL_KEY, KNIFE_CELL_KEY].map((k) =>
    visibleText(panelHtml(k, 65)).toLowerCase(),
  );

  it("never renders banned affirmative phrases in any opened panel", () => {
    for (const lc of panels) {
      for (const phrase of [
        "statistically significant",
        "strong evidence",
        "robustness score",
        "confidence level",
        "opportunity",
        "anomaly",
        "top events",
        "most extreme",
        "best",
        "worst",
        "winner",
        "loser",
      ]) {
        expect(lc, `banned phrase "${phrase}"`).not.toContain(phrase);
      }
      for (const word of [
        "proved",
        "confirmed",
        "predictive",
        "tradable",
        "tradeable",
        "signal",
        "score",
        "ranked",
        "largest",
        "smallest",
      ]) {
        expect(lc, `banned word "${word}"`).not.toMatch(
          new RegExp(`\\b${word}\\b`),
        );
      }
    }
  });

  it("confines negation-only tokens to the explicit non-claim sentence", () => {
    for (const lc of panels) {
      for (const token of [
        "independent replication",
        "causal estimates",
        "statistical significance",
        "forecasts",
        "trade signals",
        "representative-case proof",
      ]) {
        const inNonClaim =
          lc.split("they are not")[1]?.includes(token) ?? false;
        const occurrences = lc.split(token).length - 1;
        expect(
          occurrences,
          `token "${token}" outside the non-claim`,
        ).toBeLessThanOrEqual(inNonClaim ? 1 : 0);
      }
    }
  });
});
