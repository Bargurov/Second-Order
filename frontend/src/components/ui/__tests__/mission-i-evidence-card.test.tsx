/**
 * N2 — Mission I evidence card + client contract (mission-i-evidence-v1).
 *
 * The card is the first in-product consumer of the published Mission I
 * ordinary-period comparison (`GET /evidence/mission-i`, restored by N1).
 * Every research value rendered comes from the endpoint payload — the
 * backend parses the seven tracked Mission I publications at request time —
 * so the card carries no hand-copied research figure, re-runs no statistic,
 * and never pools the FOMC and OPEC ledgers.
 *
 * These tests pin the N2 contract:
 *   - one typed client method against /evidence/mission-i + a stable,
 *     unique query key;
 *   - the fixture (a typed transcription of the live payload) keeps all 20
 *     primary cells in frozen order, both families separate, the frozen
 *     denominators (65 / 32), FOMC 20d structurally unavailable, six
 *     separate falsifier families, F3 0/20, the FOMC 5d raw knife-edge, and
 *     non-empty non-claims — with no combined score field anywhere;
 *   - the card renders those facts (denominator strip, family readouts,
 *     20-cell surface, falsifiers, fragility, conclusion + clarifier,
 *     limitations, non-claims, provenance) without inventing a value;
 *   - honest loading and unavailable states with a stable message;
 *   - claim-language guards: banned affirmative framing never renders, and
 *     banned tokens appear only inside the payload's negated non-claims.
 *
 * Render-smoke pattern (renderToStaticMarkup, no jsdom).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { api } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { MissionIEvidenceCard } from "../mission-i-evidence-card";
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

const fixture = missionIFixture();
const cardHtml = renderToStaticMarkup(<MissionIEvidenceCard data={missionIFixture()} />);
const cardVisible = visibleText(cardHtml);
const loadingHtml = renderToStaticMarkup(<MissionIEvidenceCard />);
const unavailableHtml = renderToStaticMarkup(<MissionIEvidenceCard unavailable />);

// The frozen 20-cell identity order (I2B): FOMC 1d/5d, then OPEC 1d/5d/20d,
// each with the four frozen metrics in order.
const FROZEN_METRICS = ["raw_return", "spy_relative_ar", "sector_relative_ar", "sar"] as const;
const FROZEN_CELL_KEYS = [
  ...["1d", "5d"].flatMap((h) => FROZEN_METRICS.map((m) => `FOMC|${h}|${m}`)),
  ...["1d", "5d", "20d"].flatMap((h) => FROZEN_METRICS.map((m) => `OPEC|${h}|${m}`)),
];

// ---------------------------------------------------------------------------
// 1 + 2. Client method and query key
// ---------------------------------------------------------------------------

describe("Mission I client contract (N2)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("exposes exactly one typed client method that calls /evidence/mission-i", async () => {
    expect(typeof api.missionIEvidence).toBe("function");
    const fetchSpy = vi.fn(async () => ({
      ok: true,
      json: async () => missionIFixture(),
    }));
    vi.stubGlobal("fetch", fetchSpy);
    await api.missionIEvidence();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0][0]).toBe("/api/evidence/mission-i");
  });

  it("has a stable query key, unique among the evidence lanes", () => {
    expect(qk.missionIEvidence()).toEqual(["evidence", "mission-i"]);
    expect(qk.missionIEvidence()).toEqual(qk.missionIEvidence());
    const keys = [
      JSON.stringify(qk.trackedEvidenceSummary()),
      JSON.stringify(qk.missionGEvidence()),
      JSON.stringify(qk.missionIEvidence()),
      JSON.stringify(qk.missionJEvidence()),
    ];
    expect(new Set(keys).size).toBe(4);
  });
});

// ---------------------------------------------------------------------------
// 3–16. Contract-shaped fixture invariants (mission-i-evidence-v1)
// ---------------------------------------------------------------------------

describe("Mission I fixture — frozen contract invariants", () => {
  it("contains exactly 20 primary cells", () => {
    expect(fixture.primary_cells).toHaveLength(20);
    expect(fixture.constitution.primary_cell_count).toBe(20);
  });

  it("keeps the cells in frozen order (cell 1..20, frozen identity keys)", () => {
    expect(fixture.primary_cells.map((c) => c.cell)).toEqual(
      Array.from({ length: 20 }, (_, i) => i + 1),
    );
    expect(fixture.primary_cells.map((c) => c.cell_key)).toEqual(FROZEN_CELL_KEYS);
  });

  it("keeps FOMC and OPEC as separate ledgers with separate denominators", () => {
    const families = fixture.universe.families.map((f) => f.family);
    expect(families).toEqual(["FOMC", "OPEC"]);
    for (const cell of fixture.primary_cells) {
      expect(["FOMC", "OPEC"]).toContain(cell.family);
    }
    expect(fixture.constitution.family_pooling_prohibition).toContain("never");
  });

  it("carries the FOMC event denominator 65 on the lane and every FOMC cell", () => {
    const fomc = fixture.universe.families[0];
    expect(fomc.study_event_n_available).toBe(65);
    for (const cell of fixture.primary_cells.filter((c) => c.family === "FOMC")) {
      expect(cell.event_n_available).toBe(65);
    }
  });

  it("carries the OPEC event denominator 32 on the lane and every OPEC cell", () => {
    const opec = fixture.universe.families[1];
    expect(opec.study_event_n_available).toBe(32);
    for (const cell of fixture.primary_cells.filter((c) => c.family === "OPEC")) {
      expect(cell.event_n_available).toBe(32);
    }
  });

  it("has no FOMC 20d primary cell — the horizon is structurally infeasible", () => {
    expect(
      fixture.primary_cells.filter((c) => c.family === "FOMC" && c.horizon === "20d"),
    ).toHaveLength(0);
    const fomc20d = fixture.universe.families[0].horizons.find((h) => h.horizon === "20d")!;
    expect(fomc20d.status).toBe("structurally_infeasible");
    expect(fomc20d.reference_n_available).toBe(0);
    expect(fomc20d.limitation).toContain("not a data gap");
  });

  it("keeps six falsifier families, each defined separately", () => {
    expect(Object.keys(fixture.falsifiers.definitions)).toEqual([
      "f1", "f2", "f3", "f4", "f5", "f6",
    ]);
    expect(fixture.falsifiers.battery_disclosure).toContain("stand separately");
  });

  it("shows 0 of 20 F3 overlap-decimation direction changes", () => {
    expect(fixture.falsifiers.f3_overlap_decimation.sign_flips).toBe(0);
    expect(fixture.falsifiers.f3_overlap_decimation.of_cells).toBe(20);
    for (const cell of fixture.primary_cells) {
      expect(cell.f3_overlap_decimation.sign_flip).toBe(false);
    }
  });

  it("keeps the FOMC 5d raw knife-edge fragility visible", () => {
    expect(fixture.fragility.knife_edge.cell_key).toBe("FOMC|5d|raw_return");
    expect(fixture.fragility.knife_edge.memp).toBe("0.501155");
    expect(fixture.fragility.knife_edge.f2_loeo).toEqual({ runs: 65, flips: 32 });
    expect(fixture.fragility.knife_edge.f1_loyo).toEqual({ runs: 8, flips: 5 });
  });

  it("keeps all four OPEC 20d cells at the frozen lower-magnitude reading", () => {
    const opec20d = fixture.primary_cells.filter(
      (c) => c.family === "OPEC" && c.horizon === "20d",
    );
    expect(opec20d).toHaveLength(4);
    for (const cell of opec20d) {
      expect(cell.state.memp_direction).toBe("below_ordinary_midpoint");
    }
    const f4 = fixture.falsifiers.f4_cross_metric.find(
      (r) => r.family === "OPEC" && r.horizon === "20d",
    )!;
    expect(f4.negative).toBe(4);
    expect(f4.positive).toBe(0);
  });

  it("keeps the FOMC 1d four-metric elevation visible", () => {
    const fomc1d = fixture.primary_cells.filter(
      (c) => c.family === "FOMC" && c.horizon === "1d",
    );
    expect(fomc1d).toHaveLength(4);
    for (const cell of fomc1d) {
      expect(cell.state.memp_direction).toBe("above_ordinary_midpoint");
    }
    const f4 = fixture.falsifiers.f4_cross_metric.find(
      (r) => r.family === "FOMC" && r.horizon === "1d",
    )!;
    expect(f4.positive).toBe(4);
    const headline = fixture.family_horizon_readout.find(
      (r) => r.family === "FOMC" && r.horizon === "1d",
    )!;
    expect(headline.headline).toContain("all four frozen response metrics");
  });

  it("carries no combined score, ranking, or pass-count field", () => {
    const flat = JSON.stringify(fixture).toLowerCase();
    expect(flat).not.toContain('"score"');
    expect(flat).not.toContain("robustness score");
    expect(flat).not.toContain("passed");
  });

  it("keeps the whole-mission conclusion and its formal-test clarifier", () => {
    expect(fixture.whole_mission_conclusion.statement).toContain(
      "rejects the blanket idea",
    );
    expect(fixture.whole_mission_conclusion.clarifier).toContain(
      "not a formal hypothesis test",
    );
  });

  it("keeps the non-claims non-empty", () => {
    expect(fixture.non_claims.length).toBeGreaterThanOrEqual(11);
    expect(fixture.unresolved_or_limits.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Card rendering — every frozen fact visible, nothing invented
// ---------------------------------------------------------------------------

describe("MissionIEvidenceCard — denominators and research question", () => {
  it("renders the denominator strip with both event denominators, cells, falsifiers", () => {
    expect(cardVisible).toContain("FOMC events 65");
    expect(cardVisible).toContain("OPEC events 32");
    expect(cardVisible).toContain("Primary cells 20");
    expect(cardVisible).toContain("Falsifier families 6");
  });

  it("exposes the ordinary-reference denominators by family and horizon", () => {
    for (const n of ["1816", "1299", "1903", "1631", "889"]) {
      expect(cardVisible, `reference N ${n}`).toContain(n);
    }
    // non-overlapping block counts stay visible with their non-ESS note
    for (const n of ["927", "233", "960", "287", "51"]) {
      expect(cardVisible, `blocks ${n}`).toContain(n);
    }
    expect(cardVisible).toContain(
      "not an independent, effective, or degrees-of-freedom sample size",
    );
  });

  it("states the frozen research question before the results", () => {
    const question = cardVisible.indexOf(
      "Are the completed Mission G event windows unusual",
    );
    const firstCell = cardVisible.indexOf("0.674559");
    expect(question).toBeGreaterThan(-1);
    expect(firstCell).toBeGreaterThan(question);
  });

  it("states the no-p-value / no-pooled-FDR interpretation ceiling", () => {
    expect(cardVisible).toContain("no p-values");
    expect(cardVisible).toContain("no new FDR pool");
    expect(cardVisible).toContain(fixture.constitution.family_pooling_prohibition);
  });
});

describe("MissionIEvidenceCard — twenty-cell surface", () => {
  it("renders all 20 primary-cell MEMP values", () => {
    for (const cell of fixture.primary_cells) {
      expect(cardHtml, cell.cell_key).toContain(cell.memp);
    }
  });

  it("renders the cells in frozen order", () => {
    let last = -1;
    for (const cell of fixture.primary_cells) {
      const idx = cardHtml.indexOf(`>${cell.memp}<`);
      expect(idx, cell.cell_key).toBeGreaterThan(last);
      last = idx;
    }
  });

  it("exposes event N, reference N, calibration position, and frozen reading per row", () => {
    // spot-check the knife-edge row's full field set
    expect(cardVisible).toContain("0.501155");
    expect(cardVisible).toContain("0.476500");
    // direction vocabulary comes from the contract, humanized only
    expect(cardVisible).toContain("above ordinary midpoint");
    expect(cardVisible).toContain("below ordinary midpoint");
    expect(cardVisible).toContain("inside central 50%");
    expect(cardVisible).toContain("outside central 50%");
  });

  it("keeps the FOMC 20d structural unavailability visible, not skipped", () => {
    expect(cardVisible).toContain("structurally infeasible");
    expect(cardVisible).toContain("not a data gap");
  });

  it("keeps the signed-percentile diagnostic subordinate with its disclaimers", () => {
    expect(cardVisible).toContain(
      "not read as a directional or net-return statement",
    );
  });
});

describe("MissionIEvidenceCard — family readouts", () => {
  it("renders both family sections separately with their frozen headlines", () => {
    for (const readout of fixture.family_horizon_readout) {
      expect(cardVisible, `${readout.family} ${readout.horizon}`).toContain(
        readout.headline.slice(0, 60),
      );
    }
  });

  it("keeps the FOMC 1d elevation and 5d weakening both visible", () => {
    expect(cardVisible).toContain("all four frozen response metrics");
    expect(cardVisible).toContain("does not extend into a coherent 5d effect");
  });

  it("keeps the OPEC mixed and 20d lower-magnitude readings visible", () => {
    expect(cardVisible).toContain("do not show a uniform cross-metric response-magnitude pattern");
    expect(cardVisible).toContain("descriptively lower in magnitude");
    expect(cardVisible).toContain("limited cross-horizon consistency");
  });
});

describe("MissionIEvidenceCard — falsifiers, fragility, calibration", () => {
  it("renders all six falsifier families separately with their definitions", () => {
    for (const key of ["f1", "f2", "f3", "f4", "f5", "f6"] as const) {
      expect(cardVisible, key).toContain(
        visibleText(fixture.falsifiers.definitions[key]).slice(0, 50),
      );
    }
    expect(cardVisible).toContain("stand separately");
  });

  it("renders the F3 0 / 20 result with its reading and limitation", () => {
    expect(cardVisible).toContain("0 / 20");
    expect(cardVisible).toContain(
      "The direction of no primary cell depends on replacing",
    );
    expect(cardVisible).toContain("not an independence proof");
  });

  it("renders the F1/F2 totals and every affected cell", () => {
    expect(cardVisible).toContain("10 / 160");
    expect(cardVisible).toContain("32 / 904");
    for (const affected of fixture.falsifiers.f1_loyo.affected_cells) {
      expect(cardVisible).toContain(`${affected.flips} / ${affected.of}`);
    }
    expect(cardVisible).toContain("FOMC|5d|raw_return");
  });

  it("renders the F6 calibration-position split with its limitation", () => {
    expect(cardVisible).toContain("9 inside");
    expect(cardVisible).toContain("11 outside");
    expect(cardVisible).toContain("8 upper");
    expect(cardVisible).toContain("3 lower");
    expect(cardVisible).toContain("not a significance test");
  });

  it("keeps the FOMC 5d raw knife-edge fragility visible with its explanation", () => {
    expect(cardVisible).toContain("32 / 65");
    expect(cardVisible).toContain("5 / 8");
    expect(cardVisible).toContain("knife-edge");
    expect(cardVisible).toContain("removing any single event that tips the median");
  });

  it("renders the calibration frame (placements, seed, ceiling) from the payload", () => {
    expect(cardVisible).toContain("2,000");
    expect(cardVisible).toContain("20180101");
    expect(cardVisible).toContain("percentile-of-placements only");
  });

  it("presents no combined verdict — F4/F5 stay per-lane sign counts", () => {
    const opec20d = fixture.falsifiers.f4_cross_metric.find(
      (r) => r.family === "OPEC" && r.horizon === "20d",
    )!;
    expect(opec20d.negative).toBe(4);
    expect(cardVisible).not.toMatch(/\d\s*\/\s*6 (passed|failed)/i);
    // The frozen F5 caveat legitimately NEGATES a score ("...they are not
    // converted into a score."); every rendered occurrence of the token
    // must be that payload negation — no affirmative score exists.
    const lc = cardVisible.toLowerCase();
    const scoreCount = (lc.match(/\bscore\b/g) ?? []).length;
    const negatedCount = (lc.match(/not converted into a score/g) ?? []).length;
    expect(scoreCount).toBe(negatedCount);
    expect(scoreCount).toBeGreaterThan(0);
    expect(lc).not.toContain("robustness score");
  });
});

describe("MissionIEvidenceCard — conclusion, limitations, non-claims, provenance", () => {
  it("renders the whole-mission conclusion with the formal-test clarifier adjacent", () => {
    const statement = cardVisible.indexOf("rejects the blanket idea");
    const clarifier = cardVisible.indexOf("not a formal hypothesis test");
    expect(statement).toBeGreaterThan(-1);
    expect(clarifier).toBeGreaterThan(statement);
  });

  it("keeps the unresolved-or-limits statements visible", () => {
    for (const limit of fixture.unresolved_or_limits) {
      expect(cardVisible).toContain(visibleText(limit).slice(0, 60));
    }
    expect(cardVisible).toContain("does not remove multiple-comparison exposure");
  });

  it("renders every payload non-claim verbatim", () => {
    for (const nc of fixture.non_claims) {
      expect(cardVisible).toContain(visibleText(nc));
    }
  });

  it("carries the tracked-contract provenance and all seven publications", () => {
    expect(cardVisible).toContain("mission-i-evidence-v1");
    expect(cardVisible).toContain("GET /evidence/mission-i");
    for (const source of Object.values(fixture.provenance.sources)) {
      expect(cardVisible).toContain(source.artifact);
    }
    expect(cardVisible).toContain(
      fixture.provenance.no_recompute_statement.slice(0, 60),
    );
  });
});

// ---------------------------------------------------------------------------
// Loading / unavailable states — stable wrapper, no invented figures
// ---------------------------------------------------------------------------

describe("MissionIEvidenceCard — loading and unavailable states", () => {
  it("shows the honest loading message without skeleton numbers", () => {
    const v = visibleText(loadingHtml);
    expect(v).toContain("Preparing tracked Mission I record");
    expect(v).not.toMatch(/\d/);
  });

  it("shows the unavailable state without copied fallback conclusions", () => {
    const v = visibleText(unavailableHtml);
    expect(v).toContain("Mission I record unavailable");
    expect(v.toLowerCase()).toContain("not omitted");
    expect(v).not.toContain("rejects the blanket idea");
    expect(v).not.toContain("0.501155");
  });

  it("treats a payload that lost its contract shape as unavailable", () => {
    const broken = missionIFixture();
    (broken as unknown as Record<string, unknown>).primary_cells = undefined;
    const v = visibleText(
      renderToStaticMarkup(<MissionIEvidenceCard data={broken} />),
    );
    expect(v).toContain("Mission I record unavailable");
  });
});

// ---------------------------------------------------------------------------
// Claim-language guards (Step 8) — banned affirmative framing never renders;
// banned tokens live only inside the payload's negated non-claims list.
// ---------------------------------------------------------------------------

describe("MissionIEvidenceCard — claim-language honesty", () => {
  const NON_CLAIMS_MARKER = "Permanent non-claims";
  const markerAt = cardVisible.indexOf(NON_CLAIMS_MARKER);
  const beforeNonClaims = cardVisible.slice(0, markerAt).toLowerCase();

  it("carries the non-claims under a dedicated marker", () => {
    expect(markerAt).toBeGreaterThan(-1);
  });

  it("never renders banned affirmative phrases anywhere", () => {
    const lc = cardVisible.toLowerCase();
    for (const phrase of [
      "events are exceptional",
      "validation succeeded",
      "statistically significant",
      "general event rule",
      "fomc signal",
      "opec mean reversion",
      "robustness score",
      "confidence level",
      "strong evidence",
      "opportunity",
      "anomaly",
    ]) {
      expect(lc, `banned phrase "${phrase}"`).not.toContain(phrase);
    }
    for (const word of ["proved", "confirmed", "predictive", "tradable", "tradeable", "signal"]) {
      expect(lc, `banned word "${word}"`).not.toMatch(new RegExp(`\\b${word}\\b`));
    }
  });

  it("confines negated non-claim tokens to the non-claims list", () => {
    for (const token of ["alpha", "tradeability", "causality", "prediction"]) {
      expect(beforeNonClaims, `token "${token}" above the non-claims list`).not.toMatch(
        new RegExp(`\\b${token}\\b`),
      );
    }
  });

  it("uses 'confidence' only inside the payload's negated 'no confidence interval'", () => {
    const lc = cardVisible.toLowerCase();
    expect(lc.split("confidence").length).toBe(lc.split("no confidence interval").length);
  });

  it("never converts lower-magnitude into a return direction claim", () => {
    const lc = cardVisible.toLowerCase();
    expect(lc).not.toContain("negative return");
    expect(lc).not.toMatch(/\breversal\b/);
    expect(lc).not.toContain("positive performance");
    expect(lc).not.toMatch(/\bperformance\b/);
  });

  it("keeps F3 as a dependence check, never an independence proof", () => {
    const f3At = cardVisible.indexOf("0 / 20");
    const limitationAt = cardVisible.indexOf("not an independence proof");
    expect(f3At).toBeGreaterThan(-1);
    expect(limitationAt).toBeGreaterThan(f3At);
  });

  it("keeps the descriptive rejection bounded by the clarifier (no formal-test claim)", () => {
    expect(cardVisible).toContain("no significance test");
    expect(cardVisible).toContain("computed no p-value");
    expect(cardVisible).toContain("declared no null rejected");
  });
});
