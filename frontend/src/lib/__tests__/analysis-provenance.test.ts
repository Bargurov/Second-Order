/**
 * analysis-provenance.test.ts — the Analysis Basis consumer contract.
 *
 * The basis records what an analysis USED.  Nothing here treats a verifying
 * hash as support for the analysis's conclusion, and the parser must never
 * upgrade a missing or broken basis into a reassuring one: legacy stays
 * legacy, invalid stays invalid, and an unknown status is refused outright.
 */

import { describe, it, expect } from "vitest";
import {
  parseProvenance,
  provenanceLabel,
  changedDimensionLabel,
  isBasisTrustworthy,
  PROVENANCE_NON_CLAIM,
  PROVENANCE_STATES,
} from "../analysis-provenance";

function payload(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    status: "VERIFIED_CURRENT",
    changed_dimensions: [],
    problems: [],
    non_claim: PROVENANCE_NON_CLAIM,
    candidate_id: "aei-4211-deadbeef",
    parent_cluster_id: 4211,
    source_count: 3,
    candidate_first_seen_at: "2026-07-07T08:15:00",
    candidate_last_updated_at: "2026-07-07T11:30:00",
    provider: "anthropic",
    model: "claude-sonnet-4-20250514",
    analysis_prompt_version: "event-analysis-prompt-v1",
    analysis_schema_version: "analysis-result-v1",
    created_at: "2026-07-26T10:00:00",
    provenance_hash: "a".repeat(64),
    candidate_context_snapshot: "Sources (3): Reuters, BBC, AP",
    candidate_records: [
      { source: "Reuters World", title: "Oil climbs", title_key: "oil climbs",
        published_at: "2026-07-07T09:00:00", url: "https://x.test/r", record_id: "r1" },
    ],
    ...over,
  };
}

describe("parseProvenance", () => {
  it("accepts a real summary and narrows every field", () => {
    const p = parseProvenance(payload());
    expect(p).not.toBeNull();
    expect(p!.status).toBe("VERIFIED_CURRENT");
    expect(p!.sourceCount).toBe(3);
    expect(p!.model).toBe("claude-sonnet-4-20250514");
    expect(p!.records).toHaveLength(1);
    expect(p!.contextSnapshot).toContain("Sources (3)");
  });

  it("accepts every state in the closed vocabulary", () => {
    for (const status of PROVENANCE_STATES) {
      const p = parseProvenance(payload({
        status,
        changed_dimensions: status === "SAVED_WITH_OLDER_BASIS" ? ["model"] : [],
        // An invalid basis must name what broke; the parser refuses one that
        // does not, so the fixture has to supply it here.
        problems: status === "PROVENANCE_INVALID" ? ["hash mismatch"] : [],
      }));
      expect(p, status).not.toBeNull();
      expect(p!.status).toBe(status);
    }
  });

  it("refuses an unknown status rather than guessing a safe one", () => {
    expect(parseProvenance(payload({ status: "PROBABLY_FINE" }))).toBeNull();
    expect(parseProvenance(payload({ status: null }))).toBeNull();
  });

  it("refuses a missing or absent payload", () => {
    expect(parseProvenance(undefined)).toBeNull();
    expect(parseProvenance(null)).toBeNull();
    expect(parseProvenance("VERIFIED_CURRENT")).toBeNull();
  });

  it("refuses drifted non-claim wording", () => {
    expect(parseProvenance(payload({ non_claim: "Provenance proves the thesis." })))
      .toBeNull();
  });

  it("keeps a legacy record empty rather than inventing a basis", () => {
    const p = parseProvenance(payload({
      status: "LEGACY_PROVENANCE_UNAVAILABLE",
      candidate_id: null, provider: null, model: null, source_count: null,
      created_at: null, provenance_hash: null,
      candidate_context_snapshot: null, candidate_records: [],
    }));
    expect(p).not.toBeNull();
    expect(p!.candidateId).toBeNull();
    expect(p!.model).toBeNull();
    expect(p!.records).toEqual([]);
  });

  it("carries every named changed dimension on a stale basis", () => {
    const p = parseProvenance(payload({
      status: "SAVED_WITH_OLDER_BASIS",
      changed_dimensions: ["candidate_records", "model"],
    }));
    expect(p!.changedDimensions).toEqual(["candidate_records", "model"]);
  });

  it("carries integrity problems on an invalid basis", () => {
    const p = parseProvenance(payload({
      status: "PROVENANCE_INVALID",
      problems: ["provenance_hash does not verify — the record was altered"],
    }));
    expect(p!.problems.length).toBe(1);
  });

  it("refuses a stale basis that names no changed dimension", () => {
    // "Older basis" with nothing named would tell the reviewer nothing.
    expect(parseProvenance(payload({
      status: "SAVED_WITH_OLDER_BASIS", changed_dimensions: [],
    }))).toBeNull();
  });

  it("refuses an invalid basis that names no problem", () => {
    expect(parseProvenance(payload({
      status: "PROVENANCE_INVALID", problems: [],
    }))).toBeNull();
  });
});

describe("labels never overstate what a basis proves", () => {
  it("gives each state a distinct, non-celebratory label", () => {
    const labels = PROVENANCE_STATES.map((s) => provenanceLabel(s));
    expect(new Set(labels).size).toBe(PROVENANCE_STATES.length);
    for (const label of labels) {
      expect(label.toLowerCase()).not.toMatch(
        /valid(ated)?\b|confirm|proven|accurate|correct|reliable/);
    }
  });

  it("names each changed dimension in plain language", () => {
    for (const d of ["candidate_records", "candidate_context", "provider",
                     "model", "prompt_version", "schema_version",
                     "candidate_unresolved", "candidate_link_conflict"]) {
      const label = changedDimensionLabel(d);
      expect(label, d).toBeTruthy();
      // Every underscored token must be humanized; "provider" and "model" are
      // already the words a reviewer would use, so they map to themselves.
      expect(label, d).not.toContain("_");
    }
  });

  it("falls back to the raw token for an unmapped dimension", () => {
    expect(changedDimensionLabel("something_new")).toBe("something_new");
  });

  it("treats only an intact, current basis as trustworthy input evidence", () => {
    expect(isBasisTrustworthy("VERIFIED_CURRENT")).toBe(true);
    expect(isBasisTrustworthy("SAVED_WITH_OLDER_BASIS")).toBe(false);
    expect(isBasisTrustworthy("LEGACY_PROVENANCE_UNAVAILABLE")).toBe(false);
    expect(isBasisTrustworthy("PROVENANCE_INVALID")).toBe(false);
  });

  it("states the non-claim verbatim", () => {
    expect(PROVENANCE_NON_CLAIM).toContain("does not verify");
    expect(PROVENANCE_NON_CLAIM).not.toMatch(/proves|confirms|validates/i);
  });
});
