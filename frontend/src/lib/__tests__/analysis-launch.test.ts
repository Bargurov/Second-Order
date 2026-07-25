/**
 * analysis-launch.test.ts — the decision layer between an inbox candidate and
 * a paid analysis run.
 *
 * A1-1 contract: opening a candidate must never *be* the provider call.  The
 * launch object carries the candidate's identity untouched; a separate,
 * explicit action decides whether a paid run happens, a saved analysis is
 * re-read for free, or nothing is offered at all.
 *
 * Every candidate here comes from the captured producer fixture, so the types
 * are the real payload's, not hand-authored approximations.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { parseInboxPayload, type InboxEvent } from "../event-inbox";
import {
  launchFromInboxEvent,
  launchFromHeadline,
  shouldAutoSubmit,
  analysisActionFor,
  analyzeRequestFor,
} from "../analysis-launch";

const FIXTURE_PATH = resolve(__dirname, "fixtures", "automatic-event-inbox-v3.json");

function firstEvent(): InboxEvent {
  const parsed = parseInboxPayload(
    JSON.parse(readFileSync(FIXTURE_PATH, "utf-8")),
  );
  if (parsed === null) throw new Error("captured fixture must parse");
  return parsed.events[0]!;
}

function withLink(
  status: "unanalyzed" | "analyzed" | "conflict",
  analysisEventId: number | null,
): InboxEvent {
  const ev = firstEvent();
  return {
    ...ev,
    analysis_target: {
      ...ev.analysis_target,
      analysis_link_status: status,
      analysis_event_id: analysisEventId,
    },
  };
}

// ---------------------------------------------------------------------------
// Identity is carried, never re-derived
// ---------------------------------------------------------------------------

describe("launchFromInboxEvent", () => {
  it("carries every identity field verbatim from the payload", () => {
    const ev = firstEvent();
    const launch = launchFromInboxEvent(ev);
    expect(launch.origin).toBe("inbox");
    expect(launch.headline).toBe(ev.analysis_target.headline);
    expect(launch.context).toBe(ev.analysis_target.context);
    expect(launch.candidate).toEqual({
      candidate_id: ev.analysis_target.candidate_id,
      parent_cluster_id: ev.analysis_target.parent_cluster_id,
      title_key: ev.analysis_target.title_key,
    });
    expect(launch.link.status).toBe(ev.analysis_target.analysis_link_status);
    expect(launch.link.analysisEventId).toBe(ev.analysis_target.analysis_event_id);
  });

  it("keeps the candidate handle out of the numeric saved-analysis id", () => {
    const launch = launchFromInboxEvent(withLink("analyzed", 412));
    expect(launch.candidate.candidate_id).toMatch(/^aei-/);
    expect(launch.link.analysisEventId).toBe(412);
    expect(typeof launch.link.analysisEventId).toBe("number");
  });
});

// ---------------------------------------------------------------------------
// Opening is not running
// ---------------------------------------------------------------------------

describe("shouldAutoSubmit", () => {
  it("never auto-submits a candidate opened from the inbox", () => {
    for (const status of ["unanalyzed", "analyzed", "conflict"] as const) {
      expect(shouldAutoSubmit(launchFromInboxEvent(withLink(
        status, status === "analyzed" ? 9 : null,
      )))).toBe(false);
    }
  });

  it("still auto-submits a direct headline, where the click IS the action", () => {
    expect(shouldAutoSubmit(launchFromHeadline("Fed holds rates"))).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// What the operator is offered
// ---------------------------------------------------------------------------

describe("analysisActionFor", () => {
  it("offers a confirmable paid run for an unanalyzed candidate", () => {
    expect(analysisActionFor(launchFromInboxEvent(withLink("unanalyzed", null))))
      .toBe("run_paid");
  });

  it("offers the free saved analysis when one is linked", () => {
    expect(analysisActionFor(launchFromInboxEvent(withLink("analyzed", 412))))
      .toBe("open_saved");
  });

  it("offers nothing on a conflict — no id may be chosen for the operator", () => {
    expect(analysisActionFor(launchFromInboxEvent(withLink("conflict", null))))
      .toBe("blocked_conflict");
  });

  it("treats a direct headline as a confirmable run", () => {
    expect(analysisActionFor(launchFromHeadline("Fed holds rates"))).toBe("run_paid");
  });
});

// ---------------------------------------------------------------------------
// The request that actually leaves the browser
// ---------------------------------------------------------------------------

describe("analyzeRequestFor", () => {
  it("sends the full candidate identity and an explicit confirmation on a paid run", () => {
    const ev = withLink("unanalyzed", null);
    const req = analyzeRequestFor(launchFromInboxEvent(ev), "run_paid");
    expect(req).not.toBeNull();
    expect(req!.confirm_paid).toBe(true);
    expect(req!.candidate_id).toBe(ev.analysis_target.candidate_id);
    expect(req!.parent_cluster_id).toBe(ev.analysis_target.parent_cluster_id);
    expect(req!.title_key).toBe(ev.analysis_target.title_key);
    expect(req!.event_context).toBe(ev.analysis_target.context);
    // The `aei-*` handle must never be smuggled into the numeric field.
    expect(req!.event_id).toBeUndefined();
  });

  it("reads a saved analysis by numeric id with no confirmation", () => {
    const req = analyzeRequestFor(launchFromInboxEvent(withLink("analyzed", 412)), "open_saved");
    expect(req).not.toBeNull();
    expect(req!.confirm_paid).toBe(false);
    expect(req!.event_id).toBe(412);
  });

  it("refuses to build any request for a conflicted candidate", () => {
    expect(analyzeRequestFor(
      launchFromInboxEvent(withLink("conflict", null)), "blocked_conflict",
    )).toBeNull();
  });

  it("refuses a saved read when no saved id exists", () => {
    expect(analyzeRequestFor(
      launchFromInboxEvent(withLink("unanalyzed", null)), "open_saved",
    )).toBeNull();
  });

  it("confirms a direct headline run and sends no candidate identity", () => {
    const req = analyzeRequestFor(launchFromHeadline("Fed holds rates"), "run_paid");
    expect(req!.confirm_paid).toBe(true);
    expect(req!.candidate_id).toBeUndefined();
    expect(req!.parent_cluster_id).toBeUndefined();
    expect(req!.title_key).toBeUndefined();
  });

  it("carries a direct headline's own event id through unchanged", () => {
    const req = analyzeRequestFor(
      launchFromHeadline("Archive re-run", { eventId: 77 }), "open_saved",
    );
    expect(req!.event_id).toBe(77);
    expect(req!.confirm_paid).toBe(false);
  });
});
