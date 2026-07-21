/**
 * validate.test.ts — the exact-validator mutation battery.
 *
 * The spec enumerates 18 validation requirements.  Numbers 1–16 are structural
 * mutations of a known-valid brief; 17 (malformed import preserves existing
 * briefs) and 18 (deterministic export) are exercised in export.test.ts.  Each
 * numbered mutation below maps 1:1 to a spec item so the count is auditable.
 */
import { describe, expect, it } from "vitest";

import { NON_CLAIM, type Brief } from "../types";
import { validateBrief } from "../validate";
import { validBriefFixture } from "./fixture";

/** Apply a mutation to a fresh valid brief and return it. */
function mutated(fn: (b: Brief) => void): Brief {
  const b = validBriefFixture();
  fn(b);
  return b;
}

describe("validateBrief — valid baseline", () => {
  it("accepts the complete valid fixture", () => {
    const r = validateBrief(validBriefFixture());
    expect(r.ok, r.ok ? "" : r.errors.join("\n")).toBe(true);
  });

  it("fails closed on non-object input", () => {
    for (const bad of [null, undefined, 42, "brief", [], true]) {
      expect(validateBrief(bad).ok).toBe(false);
    }
  });
});

describe("validateBrief — 18-item mutation battery", () => {
  // 1
  it("1. rejects a wrong schema version", () => {
    expect(validateBrief(mutated((b) => ((b as { schema_version: string }).schema_version = "live-event-brief-v2"))).ok).toBe(false);
  });

  // 2
  it("2. rejects a missing brief ID", () => {
    expect(validateBrief(mutated((b) => (b.brief_id = ""))).ok).toBe(false);
    expect(validateBrief(mutated((b) => delete (b as Partial<Brief>).brief_id)).ok).toBe(false);
  });

  // 3
  it("3. rejects an invalid stage", () => {
    expect(validateBrief(mutated((b) => ((b as { current_stage: string }).current_stage = "OPEN"))).ok).toBe(false);
  });

  // 4
  it("4. rejects missing timestamps", () => {
    expect(validateBrief(mutated((b) => (b.created_at = ""))).ok).toBe(false);
    expect(validateBrief(mutated((b) => delete (b as Partial<Brief>).updated_at)).ok).toBe(false);
  });

  // 5
  it("5. rejects an invalid FACT / INTERPRETATION / UNKNOWN type", () => {
    expect(validateBrief(mutated((b) => ((b.fact_summary[0] as { type: string }).type = "OBSERVATION"))).ok).toBe(false);
  });

  // 6
  it("6. rejects a malformed hypothesis state", () => {
    expect(validateBrief(mutated((b) => ((b.mechanism_hypotheses[0] as { current_state: string }).current_state = "WINNER"))).ok).toBe(false);
  });

  // 7
  it("7. rejects a malformed falsifier state", () => {
    expect(validateBrief(mutated((b) => ((b.falsifiers[0] as { status: string }).status = "MAYBE"))).ok).toBe(false);
  });

  // 8
  it("8. rejects an unsupported asset role", () => {
    expect(validateBrief(mutated((b) => ((b.asset_roles[0] as { role: string }).role = "LONG"))).ok).toBe(false);
  });

  // 9
  it("9. rejects a missing as-of timestamp on a reaction", () => {
    expect(validateBrief(mutated((b) => (b.market_reactions[0].as_of = ""))).ok).toBe(false);
  });

  // 10
  it("10. rejects a numeric reaction with no basis", () => {
    expect(
      validateBrief(
        mutated((b) => {
          b.market_reactions[1].value = -0.4;
          b.market_reactions[1].basis = "";
        }),
      ).ok,
    ).toBe(false);
  });

  // 11
  it("11. rejects duplicate hypothesis IDs", () => {
    expect(validateBrief(mutated((b) => (b.mechanism_hypotheses[1].hypothesis_id = b.mechanism_hypotheses[0].hypothesis_id))).ok).toBe(false);
  });

  // 12
  it("12. rejects duplicate falsifier IDs", () => {
    expect(
      validateBrief(
        mutated((b) => {
          b.falsifiers.push({ ...b.falsifiers[0] });
        }),
      ).ok,
    ).toBe(false);
  });

  // 13
  it("13. rejects duplicate follow-up IDs", () => {
    expect(
      validateBrief(
        mutated((b) => {
          b.follow_up_checks.push({ ...b.follow_up_checks[0] });
        }),
      ).ok,
    ).toBe(false);
  });

  // 14
  it("14. rejects a malformed revision entry", () => {
    expect(validateBrief(mutated((b) => (b.revision_log[0].timestamp = ""))).ok).toBe(false);
    expect(validateBrief(mutated((b) => ((b.revision_log[0] as { stage: string }).stage = "SOON"))).ok).toBe(false);
  });

  // 15
  it("15. rejects a missing / altered non-claim", () => {
    expect(validateBrief(mutated((b) => (b.non_claim = ""))).ok).toBe(false);
    expect(validateBrief(mutated((b) => (b.non_claim = NON_CLAIM + " Also a forecast."))).ok).toBe(false);
  });

  // 16
  it("16. rejects an aggregate Mission label injected as the live-event verdict", () => {
    expect(validateBrief(mutated((b) => (b.fact_summary[0].text = "Reaction was ELEVATED versus baseline."))).ok).toBe(false);
    expect(validateBrief(mutated((b) => (b.mechanism_hypotheses[0].name = "PROPAGATED across the curve"))).ok).toBe(false);
    expect(validateBrief(mutated((b) => (b.claim_ceiling = "MEMP-consistent"))).ok).toBe(false);
  });

  it("16b. does NOT reject ordinary lowercase prose or a labelled historical mention", () => {
    // Case-sensitive: lowercase "elevated" in live prose is fine.
    expect(validateBrief(mutated((b) => (b.fact_summary[0].text = "Volatility looked elevated intraday."))).ok).toBe(true);
    // historical_context.notes is the carve-out where naming a cohort's
    // published label is descriptive context, not a live verdict.
    expect(
      validateBrief(mutated((b) => (b.historical_context.notes = "Mission I FOMC window was ELEVATED (published)."))).ok,
    ).toBe(true);
  });
});

describe("validateBrief — additional contract rules", () => {
  it("rejects a FACT with neither a source reference nor an explicit source note", () => {
    expect(
      validateBrief(
        mutated((b) => {
          b.fact_summary[0].source_reference = "";
          b.fact_summary[0].source_note = "";
        }),
      ).ok,
    ).toBe(false);
  });

  it("allows a FACT sourced only by an explicit not-yet-attached note", () => {
    expect(
      validateBrief(
        mutated((b) => {
          b.fact_summary[0].source_reference = "";
          b.fact_summary[0].source_note = "source not yet attached";
        }),
      ).ok,
    ).toBe(true);
  });

  it("rejects more than three active (non-falsified) hypotheses", () => {
    expect(
      validateBrief(
        mutated((b) => {
          b.mechanism_hypotheses = [
            { ...b.mechanism_hypotheses[0], hypothesis_id: "h1", current_state: "OPEN" },
            { ...b.mechanism_hypotheses[0], hypothesis_id: "h2", current_state: "SUPPORTED" },
            { ...b.mechanism_hypotheses[0], hypothesis_id: "h3", current_state: "WEAKENED" },
            { ...b.mechanism_hypotheses[0], hypothesis_id: "h4", current_state: "UNRESOLVED" },
          ];
        }),
      ).ok,
    ).toBe(false);
  });

  it("allows three active plus any number of falsified hypotheses", () => {
    expect(
      validateBrief(
        mutated((b) => {
          b.mechanism_hypotheses = [
            { ...b.mechanism_hypotheses[0], hypothesis_id: "h1", current_state: "OPEN" },
            { ...b.mechanism_hypotheses[0], hypothesis_id: "h2", current_state: "SUPPORTED" },
            { ...b.mechanism_hypotheses[0], hypothesis_id: "h3", current_state: "WEAKENED" },
            { ...b.mechanism_hypotheses[0], hypothesis_id: "h4", current_state: "FALSIFIED" },
          ];
        }),
      ).ok,
    ).toBe(true);
  });

  it("rejects an invalid comparable-cohort declaration", () => {
    expect(validateBrief(mutated((b) => ((b.historical_context as { comparable_cohort: string }).comparable_cohort = "CPI"))).ok).toBe(false);
  });

  it("rejects an invalid follow-up due stage or status", () => {
    expect(validateBrief(mutated((b) => ((b.follow_up_checks[0] as { due_stage: string }).due_stage = "PRE_EVENT"))).ok).toBe(false);
    expect(validateBrief(mutated((b) => ((b.follow_up_checks[0] as { status: string }).status = "DONE"))).ok).toBe(false);
  });
});
