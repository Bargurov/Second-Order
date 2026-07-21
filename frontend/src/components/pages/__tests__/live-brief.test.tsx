/**
 * live-brief.test.tsx — render-smoke for the Live Event Brief surface.
 *
 * Project pattern: renderToStaticMarkup, no jsdom.  State logic is proven in
 * @/lib/live-brief; here we prove the shell renders the empty state and a
 * seeded editor with every section, keeps the permanent non-claim and the
 * historical-context disclaimer visible, surfaces triggered falsifiers and
 * overdue follow-ups, shows a missing reaction as unavailable, loads the
 * historical evidence lazily, and clears the accessibility floor.
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { Brief } from "@/lib/live-brief/types";
import { validateBrief } from "@/lib/live-brief/validate";
import { LiveBriefPage } from "../live-brief";
import { validBriefFixture } from "@/lib/live-brief/__tests__/fixture";

function client(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
}

function render(el: React.ReactNode): string {
  return renderToStaticMarkup(<QueryClientProvider client={client()}>{el}</QueryClientProvider>);
}

function visibleText(html: string): string {
  return html.replace(/<[^>]*>/g, " ").replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&amp;/g, "&").replace(/\s+/g, " ").trim();
}

/** A rich, valid seeded brief: advanced stage, a triggered falsifier, an
 *  overdue follow-up, and an unavailable reaction. */
function seeded(): Brief {
  const b = validBriefFixture();
  b.current_stage = "TWENTY_DAY";
  b.falsifiers[0].status = "TRIGGERED";
  return b;
}

describe("LiveBriefPage — empty state", () => {
  const html = render(<LiveBriefPage />);
  const text = visibleText(html);

  it("renders the empty state with a create control", () => {
    expect(text).toContain("No brief selected");
    expect(html).toContain('data-testid="create-brief"');
    expect(html).toContain('data-testid="create-brief-empty"');
  });

  it("shows the permanent non-claim even with no brief", () => {
    expect(text).toContain("structured decision support, not a forecast");
  });
});

describe("LiveBriefPage — seeded editor", () => {
  const brief = seeded();
  const html = render(<LiveBriefPage initialBriefs={[brief]} initialActiveBriefId={brief.brief_id} />);
  const text = visibleText(html);

  it("keeps the seeded brief valid", () => {
    expect(validateBrief(brief).ok).toBe(true);
  });

  it("renders every required section", () => {
    for (const heading of [
      "Identity & official sources",
      "What changed?",
      "Facts, interpretations & unknowns",
      "Known unknowns",
      "Mechanism hypotheses",
      "Assets & expected channels",
      "Reaction observations",
      "Historical research context",
      "Falsifiers",
      "Follow-up plan",
      "Revision log",
      "Claim ceiling",
      "Local export / import",
    ]) {
      expect(text, `missing section: ${heading}`).toContain(heading);
    }
  });

  it("shows the stage header and last-updated as-of", () => {
    expect(text).toContain("Stage · 20-day");
    expect(text).toContain(brief.updated_at);
  });

  it("distinguishes FACT / INTERPRETATION / UNKNOWN visibly", () => {
    // The three type labels render as text badges (non-color-only).
    expect(text).toContain("FACT");
    expect(text).toContain("INTERPRETATION");
    expect(text).toContain("UNKNOWN");
  });

  it("shows a missing reaction value as 'unavailable', not omitted", () => {
    expect(text).toContain("unavailable");
  });

  it("keeps a triggered falsifier visible with its status text", () => {
    expect(text).toContain("TRIGGERED");
  });

  it("surfaces an overdue follow-up check", () => {
    expect(text).toContain("OVERDUE");
  });

  it("presents competing hypotheses without a winner treatment (uniform neutral badges)", () => {
    // Both hypothesis states render; none is styled as positive/celebratory.
    expect(text).toContain("OPEN");
    expect(text).toContain("UNRESOLVED");
    expect(html).not.toMatch(/hypothesis[^<]*win/i);
  });

  it("shows the full append-only revision log", () => {
    expect(text).toContain("Brief created.");
  });

  it("keeps the permanent non-claim and the claim-ceiling boundary visible", () => {
    expect(text).toContain("structured decision support, not a forecast");
    expect(text).toContain("Fixed non-claim:");
  });

  it("offers deterministic Markdown and JSON export plus import controls", () => {
    expect(html).toContain('data-testid="export-md"');
    expect(html).toContain('data-testid="export-json"');
  });
});

describe("LiveBriefPage — historical context is lazy + descriptive", () => {
  const brief = seeded();
  const closedHtml = render(<LiveBriefPage initialBriefs={[brief]} initialActiveBriefId={brief.brief_id} />);

  it("always states the descriptive-only disclaimer", () => {
    expect(visibleText(closedHtml)).toContain(
      "Historical context is descriptive and does not classify or forecast this live event.",
    );
  });

  it("mounts no evidence card until the operator opens a cohort (lazy)", () => {
    expect(closedHtml).not.toContain('data-testid="historical-panel"');
  });

  it("mounts a cohort panel only when explicitly opened", () => {
    const openHtml = render(
      <LiveBriefPage initialBriefs={[brief]} initialActiveBriefId={brief.brief_id} initialHistoricalPanel="dossiers" />,
    );
    expect(openHtml).toContain('data-testid="historical-panel"');
  });

  it("says no comparable cohort is available for a non-mapping family", () => {
    const none = validBriefFixture();
    none.historical_context.comparable_cohort = "NONE";
    const html = render(<LiveBriefPage initialBriefs={[none]} initialActiveBriefId={none.brief_id} />);
    expect(visibleText(html)).toContain("No directly comparable published Second Order cohort is available.");
  });
});

describe("LiveBriefPage — accessibility floor", () => {
  const brief = seeded();
  const html = render(<LiveBriefPage initialBriefs={[brief]} initialActiveBriefId={brief.brief_id} />);

  it("uses semantic type=button controls only (no clickable divs)", () => {
    const buttons = html.match(/<button[^>]*>/g) ?? [];
    expect(buttons.length).toBeGreaterThan(0);
    for (const b of buttons) expect(b, b).toContain('type="button"');
    expect(html).not.toMatch(/<div[^>]*role="button"/);
  });

  it("labels form controls and scopes table headers", () => {
    expect(html).toContain("<label");
    const ths = html.match(/<th\s[^>]*>/g) ?? [];
    expect(ths.length).toBeGreaterThan(0);
    for (const th of ths) expect(th).toContain('scope="col"');
  });

  it("groups the stage control in a fieldset with a legend", () => {
    expect(html).toContain("<fieldset");
    expect(html).toContain("<legend");
  });
});
