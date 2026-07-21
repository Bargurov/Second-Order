/**
 * operations.test.ts — pure brief transformations.
 *
 * A fixed clock and fixed ids are injected everywhere; the produced brief is
 * re-validated after each operation so no transformation can silently emit an
 * out-of-contract brief.
 */
import { describe, expect, it } from "vitest";

import { MAX_ACTIVE_HYPOTHESES } from "../types";
import { validateBrief } from "../validate";
import {
  addAssetRole,
  addFalsifier,
  addFollowUp,
  addHypothesis,
  addItem,
  addMarketReaction,
  addTypedEntry,
  appendRevision,
  countActiveHypotheses,
  createBrief,
  overdueFollowUps,
  patchBrief,
  patchItem,
  removeItem,
  setStage,
  touch,
  type NewBriefInput,
} from "../operations";

const T0 = "2026-03-15T12:00:00Z";
const T1 = "2026-03-16T09:00:00Z";

const NEW: NewBriefInput = {
  title: "March FOMC rate decision",
  event_family: "FOMC",
  event_type: "Scheduled monetary-policy decision",
  event_date: "2026-03-18",
  scheduled_timestamp: "2026-03-18T18:00:00Z",
  timezone: "America/New_York",
};

function fresh() {
  return createBrief(NEW, T0, "brief-1", "rev-0");
}

function assertValid(b: unknown) {
  const r = validateBrief(b);
  expect(r.ok, r.ok ? "" : r.errors.join("\n")).toBe(true);
}

describe("createBrief", () => {
  it("creates a valid PRE_EVENT brief with an initial revision and the fixed non-claim", () => {
    const b = fresh();
    assertValid(b);
    expect(b.current_stage).toBe("PRE_EVENT");
    expect(b.brief_id).toBe("brief-1");
    expect(b.created_at).toBe(T0);
    expect(b.updated_at).toBe(T0);
    expect(b.revision_log).toHaveLength(1);
    expect(b.revision_log[0].what_changed).toBe("Brief created.");
    expect(b.historical_context.comparable_cohort).toBe("NONE");
    expect(b.non_claim).toContain("structured decision support");
  });
});

describe("touch / patchBrief", () => {
  it("touch advances updated_at only", () => {
    const b = touch(fresh(), T1);
    expect(b.updated_at).toBe(T1);
    expect(b.created_at).toBe(T0);
  });

  it("patchBrief merges fields, bumps updated_at, and protects identity + non-claim", () => {
    const b = patchBrief(fresh(), { title: "Renamed", non_claim: "tampered", brief_id: "x" } as never, T1);
    expect(b.title).toBe("Renamed");
    expect(b.updated_at).toBe(T1);
    expect(b.brief_id).toBe("brief-1");
    expect(b.non_claim).toContain("structured decision support");
    assertValid(b);
  });
});

describe("appendRevision — append-only", () => {
  it("appends without editing or dropping earlier entries", () => {
    let b = fresh();
    b = appendRevision(b, { what_changed: "Added first fact.", why_it_changed: "New info." }, T1, "rev-1");
    expect(b.revision_log).toHaveLength(2);
    expect(b.revision_log[0].what_changed).toBe("Brief created."); // original intact
    expect(b.revision_log[1].id).toBe("rev-1");
    expect(b.updated_at).toBe(T1);
    assertValid(b);
  });
});

describe("setStage — forward and backward, notes preserved", () => {
  it("records a stage change in the revision log and preserves prior notes", () => {
    let b = fresh();
    b = addTypedEntry(b, "fact_summary", { type: "FACT", text: "held", source_note: "n" }, T1, "f1");
    const withFact = b.fact_summary.length;
    b = setStage(b, "LIVE", T1, "rev-live");
    expect(b.current_stage).toBe("LIVE");
    expect(b.fact_summary).toHaveLength(withFact); // notes not lost
    expect(b.revision_log.at(-1)?.stage).toBe("LIVE");

    // Backward move keeps everything and appends another revision.
    b = setStage(b, "PRE_EVENT", T1, "rev-back");
    expect(b.current_stage).toBe("PRE_EVENT");
    expect(b.fact_summary).toHaveLength(withFact);
    expect(b.revision_log.at(-1)?.id).toBe("rev-back");
    assertValid(b);
  });

  it("is a no-op when the stage is unchanged", () => {
    const b = fresh();
    const same = setStage(b, "PRE_EVENT", T1, "rev-x");
    expect(same).toBe(b);
  });
});

describe("addTypedEntry", () => {
  it("stamps as_of and keeps FACT / INTERPRETATION / UNKNOWN distinct", () => {
    let b = fresh();
    b = addTypedEntry(b, "fact_summary", { type: "FACT", text: "held", source_reference: "src" }, T1, "f1");
    b = addTypedEntry(b, "fact_summary", { type: "INTERPRETATION", text: "reads dovish" }, T1, "i1");
    b = addTypedEntry(b, "known_unknowns", { type: "UNKNOWN", text: "presser?", source_note: "later" }, T1, "u1");
    expect(b.fact_summary.map((e) => e.type)).toEqual(["FACT", "INTERPRETATION"]);
    expect(b.known_unknowns[0].type).toBe("UNKNOWN");
    expect(b.fact_summary[0].as_of).toBe(T1);
    assertValid(b);
  });
});

describe("addHypothesis — up to three active", () => {
  it("adds hypotheses and caps active (non-falsified) at three", () => {
    let b = fresh();
    for (let i = 0; i < MAX_ACTIVE_HYPOTHESES; i++) {
      const r = addHypothesis(b, { name: `h${i}`, mechanism_path: "p" }, T1, `hyp-${i}`);
      expect(r.ok).toBe(true);
      if (r.ok) b = r.brief;
    }
    expect(countActiveHypotheses(b)).toBe(3);
    const overflow = addHypothesis(b, { name: "h4", mechanism_path: "p" }, T1, "hyp-4");
    expect(overflow.ok).toBe(false);
    assertValid(b);
  });

  it("still allows adding a FALSIFIED hypothesis past the active cap", () => {
    let b = fresh();
    for (let i = 0; i < MAX_ACTIVE_HYPOTHESES; i++) {
      const r = addHypothesis(b, { name: `h${i}`, mechanism_path: "p" }, T1, `hyp-${i}`);
      if (r.ok) b = r.brief;
    }
    const dead = addHypothesis(b, { name: "dead", mechanism_path: "p", current_state: "FALSIFIED" }, T1, "hyp-d");
    expect(dead.ok).toBe(true);
    if (dead.ok) assertValid(dead.brief);
  });
});

describe("addAssetRole / addMarketReaction", () => {
  it("adds an asset role without any directional / sizing field", () => {
    let b = fresh();
    b = addAssetRole(b, { asset: "TLT", role: "RATES", basis: "benchmark-relative" }, T1, "a1");
    expect(b.asset_roles[0].role).toBe("RATES");
    expect(Object.keys(b.asset_roles[0])).not.toContain("position");
    assertValid(b);
  });

  it("keeps a missing reaction value as null (unavailable), numeric value carries a basis", () => {
    let b = fresh();
    b = addMarketReaction(b, { horizon: "1d", value: null }, T1, "rx-1");
    b = addMarketReaction(b, { horizon: "intraday", value: -0.4, basis: "vs SPY" }, T1, "rx-2");
    expect(b.market_reactions[0].value).toBeNull();
    expect(b.market_reactions[1].value).toBe(-0.4);
    assertValid(b);
  });
});

describe("addFalsifier / addFollowUp / overdueFollowUps", () => {
  it("adds a falsifier defaulting to NOT_YET_TESTABLE", () => {
    let b = fresh();
    b = addFalsifier(b, { statement: "yields rise" }, T1, "fl-1");
    expect(b.falsifiers[0].status).toBe("NOT_YET_TESTABLE");
    assertValid(b);
  });

  it("derives overdue checks from the current stage, not a stored flag", () => {
    let b = fresh(); // PRE_EVENT
    b = addFollowUp(b, { question: "live move?", due_stage: "LIVE" }, T1, "fu-live");
    b = addFollowUp(b, { question: "5d persist?", due_stage: "FIVE_DAY" }, T1, "fu-5d");
    expect(overdueFollowUps(b)).toHaveLength(0); // nothing due pre-event

    b = setStage(b, "LIVE", T1, "rev-live");
    expect(overdueFollowUps(b).map((f) => f.follow_up_id)).toEqual(["fu-live"]);

    b = setStage(b, "TWENTY_DAY", T1, "rev-20d");
    expect(overdueFollowUps(b).map((f) => f.follow_up_id).sort()).toEqual(["fu-5d", "fu-live"]);

    // Answering one removes it from the overdue view.
    b = patchBrief(b, { follow_up_checks: patchItem(b.follow_up_checks, (f) => f.follow_up_id, "fu-live", { status: "ANSWERED", result: "moved" }) }, T1);
    expect(overdueFollowUps(b).map((f) => f.follow_up_id)).toEqual(["fu-5d"]);
    assertValid(b);
  });
});

describe("generic list utilities", () => {
  it("addItem / patchItem / removeItem operate by id without mutating input", () => {
    const arr = [{ id: "a", v: 1 }, { id: "b", v: 2 }];
    const added = addItem(arr, { id: "c", v: 3 });
    expect(added).toHaveLength(3);
    const patched = patchItem(arr, (x) => x.id, "b", { v: 9 });
    expect(patched[1].v).toBe(9);
    expect(arr[1].v).toBe(2); // input untouched
    const removed = removeItem(arr, (x) => x.id, "a");
    expect(removed.map((x) => x.id)).toEqual(["b"]);
  });
});
