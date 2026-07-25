/**
 * event-inbox.test.ts — fail-closed consumer contract for
 * automatic-event-inbox-v3.
 *
 * The captured fixture (fixtures/automatic-event-inbox-v3.json) is the REAL
 * producer payload: it is deep-equal-pinned against live GET /news/inbox
 * output by tests/test_event_inbox_route_boundary.py.  Every type the parser
 * accepts is derived from that captured payload, not from field names.
 *
 * The parser refuses (returns null) on ANY contract violation — a malformed
 * inbox must never render as a plausible inbox.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  parseInboxPayload,
  groupByLifecycle,
  shouldAutoAnalyzeOnLoad,
  INBOX_NON_CLAIM,
  INBOX_ABSENCE_NOTE,
  LIFECYCLES,
  type InboxPayload,
} from "../event-inbox";

const FIXTURE_PATH = resolve(__dirname, "fixtures", "automatic-event-inbox-v3.json");

function loadFixture(): unknown {
  return JSON.parse(readFileSync(FIXTURE_PATH, "utf-8"));
}

function validPayload(): InboxPayload {
  const parsed = parseInboxPayload(loadFixture());
  if (parsed === null) throw new Error("captured fixture must parse");
  return parsed;
}

// ---------------------------------------------------------------------------
// Captured real payload parses and survives intact
// ---------------------------------------------------------------------------

describe("captured producer payload", () => {
  it("parses the real captured GET /news/inbox payload", () => {
    const parsed = parseInboxPayload(loadFixture());
    expect(parsed).not.toBeNull();
    expect(parsed!.contract).toBe("automatic-event-inbox-v3");
    expect(parsed!.availability).toBe("AVAILABLE");
    expect(parsed!.events.length).toBeGreaterThan(0);
  });

  it("preserves channels, reasons and unknowns verbatim", () => {
    const parsed = validPayload();
    const raw = loadFixture() as { events: Record<string, unknown>[] };
    parsed.events.forEach((ev, i) => {
      expect(ev.material_channels).toEqual(raw.events[i].material_channels);
      expect(ev.why_surfaced).toEqual(raw.events[i].why_surfaced);
      expect(ev.known_unknowns).toEqual(raw.events[i].known_unknowns);
    });
  });

  it("keeps oil and non-oil events under one contract", () => {
    const parsed = validPayload();
    const channels = new Set(parsed.events.flatMap((e) => e.material_channels));
    expect(channels.has("ENERGY_COMMODITIES")).toBe(true);
    expect(channels.has("TECHNOLOGY_PRODUCTIVITY")).toBe(true);
  });

  it("pins the permanent non-claim and absence wording", () => {
    const parsed = validPayload();
    expect(parsed.non_claim).toBe(INBOX_NON_CLAIM);
    expect(parsed.limitations).toContain(INBOX_ABSENCE_NOTE);
  });
});

// ---------------------------------------------------------------------------
// Fail-closed refusals — every mutation must be refused, not repaired
// ---------------------------------------------------------------------------

describe("malformed payloads are refused", () => {
  function mutate(fn: (p: Record<string, unknown>) => void): unknown {
    const p = loadFixture() as Record<string, unknown>;
    fn(p);
    return p;
  }

  it("refuses a non-object payload", () => {
    expect(parseInboxPayload(null)).toBeNull();
    expect(parseInboxPayload("inbox")).toBeNull();
    expect(parseInboxPayload([])).toBeNull();
  });

  it("refuses a wrong contract version", () => {
    expect(parseInboxPayload(mutate((p) => { p.contract = "automatic-event-inbox-v4"; }))).toBeNull();
    expect(parseInboxPayload(mutate((p) => { p.contract = "automatic-event-inbox-v2"; }))).toBeNull();
  });

  it("refuses a missing top-level field", () => {
    expect(parseInboxPayload(mutate((p) => { delete p.counts; }))).toBeNull();
  });

  it("refuses an unexpected extra top-level field", () => {
    expect(parseInboxPayload(mutate((p) => { p.ranking = []; }))).toBeNull();
  });

  it("refuses an unknown lifecycle", () => {
    expect(parseInboxPayload(mutate((p) => {
      (p.events as Record<string, unknown>[])[0].lifecycle = "URGENT";
    }))).toBeNull();
  });

  it("refuses an unknown material channel", () => {
    expect(parseInboxPayload(mutate((p) => {
      (p.events as Record<string, unknown>[])[0].material_channels = ["VIBES"];
    }))).toBeNull();
  });

  it("refuses a surfaced event without a material channel", () => {
    expect(parseInboxPayload(mutate((p) => {
      (p.events as Record<string, unknown>[])[0].material_channels = [];
    }))).toBeNull();
  });

  it("refuses a surfaced event without a why_surfaced reason", () => {
    expect(parseInboxPayload(mutate((p) => {
      (p.events as Record<string, unknown>[])[0].why_surfaced = [];
    }))).toBeNull();
  });

  it("refuses a score-like or directional field anywhere", () => {
    expect(parseInboxPayload(mutate((p) => {
      (p.events as Record<string, unknown>[])[0].impact_score = 0.9;
    }))).toBeNull();
    expect(parseInboxPayload(mutate((p) => {
      (p.events as Record<string, unknown>[])[0].direction = "up";
    }))).toBeNull();
  });

  it("refuses PARTIAL availability without a visible missing_reason", () => {
    expect(parseInboxPayload(mutate((p) => {
      const ev = (p.events as Record<string, unknown>[])[0];
      ev.availability_status = "PARTIAL";
      ev.missing_reason = null;
    }))).toBeNull();
  });

  it("refuses counts that do not reconcile with the event list", () => {
    expect(parseInboxPayload(mutate((p) => {
      (p.counts as Record<string, unknown>).surfaced = 99;
    }))).toBeNull();
  });

  it("refuses a malformed analysis_target", () => {
    expect(parseInboxPayload(mutate((p) => {
      (p.events as Record<string, unknown>[])[0].analysis_target = { headline: "x" };
    }))).toBeNull();
  });

  // -- v3 candidate identity ------------------------------------------------
  // The launch object the UI hands to the analysis surface is only as
  // trustworthy as the identity fields it carries; a drifted or partial
  // identity must refuse rather than open the wrong candidate.

  it("refuses an analysis_target missing any identity field", () => {
    for (const field of [
      "candidate_id", "parent_cluster_id", "title_key",
      "analysis_link_status", "analysis_event_id",
    ]) {
      expect(parseInboxPayload(mutate((p) => {
        const t = (p.events as Record<string, unknown>[])[0]
          .analysis_target as Record<string, unknown>;
        delete t[field];
      })), `deleting ${field} must refuse`).toBeNull();
    }
  });

  it("refuses a candidate_id that disagrees with the event id", () => {
    expect(parseInboxPayload(mutate((p) => {
      const ev = (p.events as Record<string, unknown>[])[0];
      (ev.analysis_target as Record<string, unknown>).candidate_id = "aei-1-deadbeef";
    }))).toBeNull();
  });

  it("refuses a parent_cluster_id that disagrees with the cluster id", () => {
    expect(parseInboxPayload(mutate((p) => {
      const ev = (p.events as Record<string, unknown>[])[0];
      (ev.analysis_target as Record<string, unknown>).parent_cluster_id = 999999;
    }))).toBeNull();
  });

  it("refuses an unknown analysis_link_status", () => {
    expect(parseInboxPayload(mutate((p) => {
      const ev = (p.events as Record<string, unknown>[])[0];
      (ev.analysis_target as Record<string, unknown>).analysis_link_status = "maybe";
    }))).toBeNull();
  });

  it("refuses an unanalyzed candidate that still carries an analysis id", () => {
    expect(parseInboxPayload(mutate((p) => {
      const ev = (p.events as Record<string, unknown>[])[0];
      (ev.analysis_target as Record<string, unknown>).analysis_event_id = 7;
    }))).toBeNull();
  });

  it("refuses an analyzed candidate with no analysis id", () => {
    expect(parseInboxPayload(mutate((p) => {
      const t = (p.events as Record<string, unknown>[])[0]
        .analysis_target as Record<string, unknown>;
      t.analysis_link_status = "analyzed";
    }))).toBeNull();
  });

  it("accepts an analyzed candidate carrying a numeric analysis id", () => {
    expect(parseInboxPayload(mutate((p) => {
      const t = (p.events as Record<string, unknown>[])[0]
        .analysis_target as Record<string, unknown>;
      t.analysis_link_status = "analyzed";
      t.analysis_event_id = 412;
    }))).not.toBeNull();
  });

  it("accepts a conflicted candidate, which must select no id", () => {
    expect(parseInboxPayload(mutate((p) => {
      const t = (p.events as Record<string, unknown>[])[0]
        .analysis_target as Record<string, unknown>;
      t.analysis_link_status = "conflict";
    }))).not.toBeNull();
    expect(parseInboxPayload(mutate((p) => {
      const t = (p.events as Record<string, unknown>[])[0]
        .analysis_target as Record<string, unknown>;
      t.analysis_link_status = "conflict";
      t.analysis_event_id = 5;
    }))).toBeNull();
  });

  it("refuses drifted non-claim wording", () => {
    expect(parseInboxPayload(mutate((p) => { p.non_claim = "Trust the inbox."; }))).toBeNull();
  });

  it("refuses a payload missing the absence disclosure", () => {
    expect(parseInboxPayload(mutate((p) => { p.limitations = []; }))).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Honest states — empty and unavailable both parse (they are not errors)
// ---------------------------------------------------------------------------

describe("honest empty and unavailable states", () => {
  function emptyPayload(availability: "AVAILABLE" | "UNAVAILABLE"): unknown {
    const p = loadFixture() as Record<string, unknown>;
    p.availability = availability;
    p.events = [];
    p.counts = {
      parent_clusters_total: 0, partitioned_parent_clusters: 0,
      malformed_parent_clusters: 0, candidates_total: 0, surfaced: 0,
      beyond_window: 0, excluded_no_material_channel: 0,
      malformed_candidates: 0,
      by_lifecycle: { NEW: 0, DEVELOPING: 0, WATCH: 0, RESOLVED: 0 },
    };
    return p;
  }

  it("a valid empty inbox parses (empty is honest, not malformed)", () => {
    const parsed = parseInboxPayload(emptyPayload("AVAILABLE"));
    expect(parsed).not.toBeNull();
    expect(parsed!.events).toEqual([]);
  });

  it("an explicit UNAVAILABLE state parses with zero events", () => {
    const parsed = parseInboxPayload(emptyPayload("UNAVAILABLE"));
    expect(parsed).not.toBeNull();
    expect(parsed!.availability).toBe("UNAVAILABLE");
  });
});

// ---------------------------------------------------------------------------
// Lifecycle grouping — workflow order, payload order preserved inside groups
// ---------------------------------------------------------------------------

describe("groupByLifecycle", () => {
  it("groups events under the four workflow states in fixed order", () => {
    const parsed = validPayload();
    const groups = groupByLifecycle(parsed.events);
    expect(Object.keys(groups)).toEqual([...LIFECYCLES]);
    const total = LIFECYCLES.reduce((n, lc) => n + groups[lc].length, 0);
    expect(total).toBe(parsed.events.length);
  });

  it("preserves payload (publication) order inside each group", () => {
    const parsed = validPayload();
    const groups = groupByLifecycle(parsed.events);
    for (const lc of LIFECYCLES) {
      const expected = parsed.events.filter((e) => e.lifecycle === lc);
      expect(groups[lc]).toEqual(expected);
    }
  });

  it("returns four empty groups for an empty inbox", () => {
    const groups = groupByLifecycle([]);
    for (const lc of LIFECYCLES) expect(groups[lc]).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// No automatic provider work on page load
// ---------------------------------------------------------------------------

describe("no automatic analysis on load", () => {
  it("shouldAutoAnalyzeOnLoad is unconditionally false", () => {
    expect(shouldAutoAnalyzeOnLoad()).toBe(false);
  });
});
