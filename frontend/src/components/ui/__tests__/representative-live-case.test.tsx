/**
 * Representative Live Case band — resolution honesty and claim ceilings.
 *
 * Pure-view tests via renderToStaticMarkup (the project convention): the band
 * must present the one published case from its resolved contract, keep every
 * limit visible, offer exactly one CTA wired to the numeric saved-analysis
 * launch, and render unavailable states as explicit lines — never a
 * substitute case, never a hidden section.
 */
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import {
  RepresentativeLiveCaseView,
  viewStateFor,
  launchArgsFor,
  REPRESENTATIVE_LIVE_CASE_CANDIDATE_ID,
  REPRESENTATIVE_CASE_RATIONALE,
  REPRESENTATIVE_CASE_CUES,
  REPRESENTATIVE_CASE_LIMITS,
} from "../representative-live-case";
import type { RepresentativeCase } from "@/lib/api";

const AVAILABLE: RepresentativeCase = {
  availability: "AVAILABLE",
  candidate_id: REPRESENTATIVE_LIVE_CASE_CANDIDATE_ID,
  analysis_event_id: 316,
  headline:
    "Ambassador Greer Issues Statement on President Trump Imposing " +
    "Section 338 Tariffs on Canada",
  event_date: "2026-07-20",
  sources: ["USTR Trade Policy"],
  quality_tier: "watch_only",
  basis_status: "VERIFIED_CURRENT",
};

function html(state = viewStateFor(AVAILABLE, false, false)) {
  return renderToStaticMarkup(
    <RepresentativeLiveCaseView state={state} onOpenAnalysis={() => {}} />,
  );
}

describe("available case", () => {
  it("renders the headline, date and official USTR source", () => {
    const out = html();
    expect(out).toContain("Section 338 Tariffs on Canada");
    expect(out).toContain("2026-07-20");
    expect(out).toContain("source: USTR Trade Policy");
  });

  it("renders tier and basis as review language, never raw tokens", () => {
    const out = html();
    expect(out).toContain("Monitor / insufficiently resolved");
    expect(out).toContain("Matches current basis");
    expect(out).not.toContain("watch_only");
    expect(out).not.toContain("VERIFIED_CURRENT");
  });

  it("keeps the rationale, three reviewer cues and limits visible", () => {
    const out = html();
    expect(out).toContain(REPRESENTATIVE_CASE_RATIONALE);
    for (const cue of REPRESENTATIVE_CASE_CUES) {
      expect(out).toContain(cue.label);
      expect(out).toContain(cue.detail);
    }
    expect(out).toContain("Representative case, not proof");
    expect(out).toContain("not a recommendation");
  });

  it("does not display the internal candidate id", () => {
    expect(html()).not.toContain(REPRESENTATIVE_LIVE_CASE_CANDIDATE_ID);
  });

  it("offers exactly one CTA labelled Open full analysis", () => {
    const out = html();
    expect(out.match(/<button/g) || []).toHaveLength(1);
    expect(out).toContain("Open full analysis");
  });

  it("contains no recommendation or success vocabulary", () => {
    const out = html().toLowerCase();
    for (const banned of [
      "successful case", "validated mechanism", "confirmed transmission",
      "high-confidence", "strong edge", "best opportunity", "alpha",
      "trade idea", ">buy<", ">sell<",
    ]) {
      expect(out).not.toContain(banned);
    }
  });
});

describe("navigation wiring is pure and exact", () => {
  it("launch args carry the resolved event id and headline", () => {
    expect(launchArgsFor(AVAILABLE)).toEqual({
      headline: AVAILABLE.headline,
      eventId: 316,
    });
  });

  it("no launch args for any non-available or incomplete case", () => {
    expect(launchArgsFor(undefined)).toBeNull();
    expect(
      launchArgsFor({ ...AVAILABLE, availability: "CASE_UNLINKED" }),
    ).toBeNull();
    expect(
      launchArgsFor({ ...AVAILABLE, analysis_event_id: null }),
    ).toBeNull();
    expect(launchArgsFor({ ...AVAILABLE, headline: "" })).toBeNull();
  });
});

describe("unavailable states stay explicit", () => {
  const cases: Array<[RepresentativeCase["availability"], string]> = [
    ["CASE_UNLINKED", "not linked to a saved analysis"],
    ["CASE_NOT_FOUND", "identity was not found"],
    ["SAVED_ANALYSIS_UNAVAILABLE", "is unavailable"],
    ["PROVENANCE_UNAVAILABLE", "without a captured analysis basis"],
    ["INVALID", "did not resolve"],
  ];

  for (const [availability, message] of cases) {
    it(`${availability} renders one restrained line and no substitute`, () => {
      const out = html(
        viewStateFor(
          { availability, candidate_id: "x", analysis_event_id: null },
          false,
          false,
        ),
      );
      expect(out).toContain(message);
      expect(out).toContain("Representative live case"); // never hidden
      expect(out).toContain("Nothing is substituted");
      expect(out).not.toContain("<button"); // no CTA, no other case
      expect(out).not.toContain("Section 338");
    });
  }

  it("a fetch error folds to the explicit error line", () => {
    const out = html(viewStateFor(undefined, true, false));
    expect(out).toContain("could not be read");
    expect(out).not.toContain("<button");
  });

  it("pending renders a quiet loading line inside the labelled section", () => {
    const out = html(viewStateFor(undefined, false, true));
    expect(out).toContain("Loading the representative case");
    expect(out).toContain("Representative live case");
  });
});

describe("limits copy is the exact curated ceiling", () => {
  it("names all four limits", () => {
    for (const phrase of [
      "single-source evidence",
      "model-generated structured hypothesis",
      "descriptive, not causal",
      "not a recommendation",
    ]) {
      expect(REPRESENTATIVE_CASE_LIMITS.toLowerCase()).toContain(phrase);
    }
  });
});
