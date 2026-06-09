/**
 * Guard coverage for the ``portfolio_view`` saved-study path.
 *
 * Three contracts under test:
 *   1. Typing — ``portfolio_view`` is in the closed ``SavedStudyType`` union
 *      and shows up in the rendered ``STUDY_TYPE_LABEL`` / order.
 *   2. UI grouping — saved ``portfolio_view`` studies are bucketed under
 *      their type so the SavedStudiesSection grid renders them with the
 *      other groups (and ahead of them, since they sort first).
 *   3. Replay/load — narrowing a saved config back into ``PortfolioFilters``
 *      keeps every valid filter and drops bad/unknown values cleanly so
 *      the portfolio page reopens with the same view the user saved.
 */
import { describe, it, expect } from "vitest";
import {
  STUDY_TYPE_LABEL,
  STUDY_TYPE_ORDER,
  groupSavedStudies,
  _studyConfigChips,
  _portfolioViewConfigToFilters,
} from "../portfolio-page";
import type { PortfolioFilters, SavedStudy, SavedStudyType } from "@/lib/api";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeStudy(overrides: Partial<SavedStudy> = {}): SavedStudy {
  return {
    id: 1,
    study_type: "portfolio_view",
    name: "Test view",
    description: "",
    config: {},
    created_at: "2026-04-01T00:00:00",
    updated_at: "2026-04-01T00:00:00",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// 1 · Typing — portfolio_view is part of the saved-study contract
// ---------------------------------------------------------------------------

describe("portfolio_view typing", () => {
  it("portfolio_view satisfies the SavedStudyType union", () => {
    // Compile-time guard: assigning the literal to the type fails to build
    // if the union ever loses ``portfolio_view``.
    const t: SavedStudyType = "portfolio_view";
    expect(t).toBe("portfolio_view");
  });

  it("STUDY_TYPE_LABEL has a human label for portfolio_view", () => {
    expect(STUDY_TYPE_LABEL.portfolio_view).toBe("Portfolio view");
  });

  it("STUDY_TYPE_ORDER includes portfolio_view as the first slot", () => {
    expect(STUDY_TYPE_ORDER).toContain("portfolio_view");
    // Lead position so saved portfolio views surface above other study types.
    expect(STUDY_TYPE_ORDER[0]).toBe("portfolio_view");
  });

  it("STUDY_TYPE_ORDER covers every SavedStudyType union member", () => {
    // If a new type is added to the union without being placed in the
    // ordered list, group-rendering would silently drop it.  The check
    // catches that regression.
    const labelKeys = Object.keys(STUDY_TYPE_LABEL).sort();
    const orderKeys = [...STUDY_TYPE_ORDER].sort();
    expect(orderKeys).toEqual(labelKeys);
  });
});

// ---------------------------------------------------------------------------
// 2 · UI grouping — portfolio_view studies render under their bucket
// ---------------------------------------------------------------------------

describe("groupSavedStudies", () => {
  it("returns an entry for every study type, even when empty", () => {
    const groups = groupSavedStudies([]);
    for (const t of STUDY_TYPE_ORDER) {
      expect(groups.has(t)).toBe(true);
      expect(groups.get(t)).toEqual([]);
    }
  });

  it("buckets a portfolio_view study under the portfolio_view slot", () => {
    const study = makeStudy({ id: 7, study_type: "portfolio_view", name: "My view" });
    const groups = groupSavedStudies([study]);
    expect(groups.get("portfolio_view")).toEqual([study]);
    // Other slots stay empty — no leakage into siblings.
    expect(groups.get("cohort_comparison")).toEqual([]);
    expect(groups.get("cascade_view")).toEqual([]);
  });

  it("keeps multiple portfolio_view studies in insertion order", () => {
    const a = makeStudy({ id: 1, name: "A" });
    const b = makeStudy({ id: 2, name: "B" });
    const c = makeStudy({ id: 3, name: "C" });
    const groups = groupSavedStudies([a, b, c]);
    expect(groups.get("portfolio_view")?.map((s) => s.id)).toEqual([1, 2, 3]);
  });

  it("groups a mixed list across types without dropping portfolio_view", () => {
    const pv = makeStudy({ id: 10, study_type: "portfolio_view" });
    const cc = makeStudy({ id: 20, study_type: "cohort_comparison" });
    const cas = makeStudy({ id: 30, study_type: "cascade_view" });
    const groups = groupSavedStudies([cc, pv, cas]);
    expect(groups.get("portfolio_view")).toEqual([pv]);
    expect(groups.get("cohort_comparison")).toEqual([cc]);
    expect(groups.get("cascade_view")).toEqual([cas]);
  });

  it("renders the grouped list in STUDY_TYPE_ORDER, putting portfolio_view first", () => {
    const pv = makeStudy({ id: 1, study_type: "portfolio_view", name: "PV" });
    const cc = makeStudy({ id: 2, study_type: "cohort_comparison", name: "CC" });
    const groups = groupSavedStudies([cc, pv]);

    // Mirror the SavedStudiesSection render: flatMap over STUDY_TYPE_ORDER.
    const flattened = STUDY_TYPE_ORDER.flatMap((t) => groups.get(t) ?? []);
    expect(flattened.map((s) => s.id)).toEqual([1, 2]);
  });

  it("tolerates null / undefined inputs without throwing", () => {
    expect(() => groupSavedStudies(null)).not.toThrow();
    expect(() => groupSavedStudies(undefined)).not.toThrow();
    expect(groupSavedStudies(null).get("portfolio_view")).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// 3 · Card chips — portfolio_view config surfaces as compact chips
// ---------------------------------------------------------------------------

describe("_studyConfigChips for portfolio_view", () => {
  it("renders 'default portfolio' for an empty config", () => {
    const study = makeStudy({ config: {} });
    expect(_studyConfigChips(study)).toEqual(["default portfolio"]);
  });

  it("humanises tier and subtype tokens", () => {
    const study = makeStudy({
      config: {
        quality_tier: "actionable",
        mechanism_subtype: "tariff_cycle",
      },
    });
    expect(_studyConfigChips(study)).toEqual(["high-quality", "tariff cycle"]);
  });

  it("emits a tradable / not tradable chip from a boolean", () => {
    expect(
      _studyConfigChips(makeStudy({ config: { tradable: true } })),
    ).toContain("tradable");
    expect(
      _studyConfigChips(makeStudy({ config: { tradable: false } })),
    ).toContain("not tradable");
  });

  it("emits queue / mover_window / thesis_state / proof_quality chips when set", () => {
    const study = makeStudy({
      config: {
        queue: "needs_review",
        mover_window: "weekly",
        thesis_state: "confirming",
        proof_quality: "high",
      },
    });
    const chips = _studyConfigChips(study);
    expect(chips).toContain("queue: needs review");
    expect(chips).toContain("weekly movers");
    expect(chips).toContain("confirming");
    expect(chips).toContain("high");
  });

  it("emits a low-info chip in either polarity", () => {
    expect(
      _studyConfigChips(makeStudy({ config: { low_information: true } })),
    ).toContain("low-info only");
    expect(
      _studyConfigChips(makeStudy({ config: { low_information: false } })),
    ).toContain("exclude low-info");
  });
});

// ---------------------------------------------------------------------------
// 4 · Replay/load — config narrows back to PortfolioFilters losslessly
// ---------------------------------------------------------------------------

describe("_portfolioViewConfigToFilters", () => {
  it("returns an empty filter object for an empty config", () => {
    expect(_portfolioViewConfigToFilters({})).toEqual({});
  });

  it("preserves every valid filter axis on round-trip", () => {
    const config = {
      thesis_state: "confirming",
      proof_quality: "high",
      low_information: false,
      queue: "needs_review",
      mover_window: "persistent",
      quality_tier: "actionable",
      tradable: true,
      mechanism_subtype: "tariff_cycle",
    };

    const filters: PortfolioFilters = _portfolioViewConfigToFilters(config);

    expect(filters).toEqual({
      thesis_state: "confirming",
      proof_quality: "high",
      low_information: false,
      queue: "needs_review",
      mover_window: "persistent",
      quality_tier: "actionable",
      tradable: true,
      mechanism_subtype: "tariff_cycle",
    });
  });

  it("accepts every legal mover_window literal", () => {
    for (const w of ["today", "weekly", "persistent", "market"] as const) {
      expect(
        _portfolioViewConfigToFilters({ mover_window: w }).mover_window,
      ).toBe(w);
    }
  });

  it("rejects an unknown mover_window without throwing", () => {
    const out = _portfolioViewConfigToFilters({ mover_window: "yearly" });
    expect(out.mover_window).toBeUndefined();
  });

  it("accepts every legal quality_tier literal", () => {
    for (const t of ["actionable", "watch_only", "low_information"] as const) {
      expect(
        _portfolioViewConfigToFilters({ quality_tier: t }).quality_tier,
      ).toBe(t);
    }
  });

  it("rejects an unknown quality_tier without throwing", () => {
    const out = _portfolioViewConfigToFilters({ quality_tier: "premium" });
    expect(out.quality_tier).toBeUndefined();
  });

  it("ignores fields with the wrong runtime type", () => {
    const out = _portfolioViewConfigToFilters({
      thesis_state: 42,
      tradable: "yes",
      mechanism_subtype: null,
      low_information: "no",
    });
    expect(out).toEqual({});
  });

  it("drops empty mechanism_subtype strings", () => {
    expect(
      _portfolioViewConfigToFilters({ mechanism_subtype: "" }).mechanism_subtype,
    ).toBeUndefined();
  });

  it("does not mutate the source config", () => {
    const config = {
      quality_tier: "actionable",
      tradable: true,
      mechanism_subtype: "tariff_cycle",
    };
    const snapshot = JSON.stringify(config);
    _portfolioViewConfigToFilters(config);
    expect(JSON.stringify(config)).toBe(snapshot);
  });

  it("survives the chip → filter round-trip without losing axes", () => {
    // The render path runs both _studyConfigChips (for the card) and
    // _portfolioViewConfigToFilters (for the replay).  Make sure the
    // same config feeds both branches without silently dropping any
    // axis the chip surfaces.
    const study = makeStudy({
      config: {
        quality_tier: "actionable",
        tradable: false,
        mechanism_subtype: "tariff_cycle",
      },
    });
    const chips = _studyConfigChips(study);
    const filters = _portfolioViewConfigToFilters(study.config);

    expect(chips).toContain("high-quality");
    expect(chips).toContain("not tradable");
    expect(chips).toContain("tariff cycle");

    expect(filters.quality_tier).toBe("actionable");
    expect(filters.tradable).toBe(false);
    expect(filters.mechanism_subtype).toBe("tariff_cycle");
  });
});
