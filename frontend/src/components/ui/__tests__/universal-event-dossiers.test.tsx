/**
 * U1 — Universal Event Dossier reader: index contract + event ledger.
 *
 * The complete 97-event published historical universe (65 FOMC + 32 OPEC)
 * must be discoverable through one bounded, publication-ordered ledger:
 * no event is selected, promoted, ranked, or featured; search and the
 * family filter are outcome-neutral order-preserving subsequences; the
 * enrichment tier is displayed, never a filter; and a malformed or
 * wrong-version index fails closed with zero event controls.
 *
 * Render-smoke pattern (renderToStaticMarkup, no jsdom); interaction
 * state is exercised through the documented starting-state props (the
 * ReactionProfileCard `initialHorizon` / E2 `initialOpenCellKey`
 * precedent) plus the real browser smoke.
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { EventDossierIndex } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { EvidenceOverview } from "@/components/pages/evidence-overview";
import {
  DOSSIER_LEDGER_PAGE_SIZE,
  UniversalEventDossiersCard,
  eventDossierIndexState,
  filterDossierEvents,
  visibleDossierRows,
} from "../universal-event-dossiers";
import { eventDossierIndexFixture } from "./event-dossier-fixture";

function testQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity, gcTime: Infinity },
    },
  });
}

function renderCard(
  props: Partial<Parameters<typeof UniversalEventDossiersCard>[0]> = {},
  client: QueryClient = testQueryClient(),
): string {
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <UniversalEventDossiersCard data={eventDossierIndexFixture()} {...props} />
    </QueryClientProvider>,
  );
}

function visibleText(html: string): string {
  return html
    .replace(/<[^>]*>/g, " ")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();
}

/** Candidate ids of the rendered ledger rows, in DOM order. */
function rowIds(html: string): string[] {
  return [...html.matchAll(/data-dossier-row="([^"]+)"/g)].map((m) => m[1]);
}

const index = eventDossierIndexFixture();
const allIds = index.events.map((e) => e.candidate_id);
const closedHtml = renderCard();
const closedVisible = visibleText(closedHtml);

// ---------------------------------------------------------------------------
// Captured-fixture acceptance — the real producer output passes the validator
// ---------------------------------------------------------------------------

describe("event-dossier-index-v1 — captured fixture acceptance", () => {
  it("accepts the captured real producer index", () => {
    expect(eventDossierIndexState(eventDossierIndexFixture())).toBe("ok");
  });

  it("carries the frozen universe accounting (97 = 65 FOMC + 32 OPEC, 6/91)", () => {
    expect(index.contract_version).toBe("event-dossier-index-v1");
    expect(index.universe).toBe("historical_research");
    expect(index.coverage.total).toBe(97);
    expect(index.coverage.family_counts).toEqual({ FOMC: 65, OPEC: 32 });
    expect(index.coverage.enrichment_counts).toEqual({
      published_per_event_dossier: 6,
      core_published_evidence: 91,
    });
    expect(index.events).toHaveLength(97);
    expect(new Set(allIds).size).toBe(97);
  });

  it("keeps publication order: the FOMC block then the OPEC block, each ascending by anchor", () => {
    const families = index.events.map((e) => e.family);
    expect(families.slice(0, 65).every((f) => f === "FOMC")).toBe(true);
    expect(families.slice(65).every((f) => f === "OPEC")).toBe(true);
    for (const block of [index.events.slice(0, 65), index.events.slice(65)]) {
      for (let i = 1; i < block.length; i++) {
        expect(block[i].anchor_session > block[i - 1].anchor_session).toBe(true);
      }
    }
  });
});

// ---------------------------------------------------------------------------
// 1, 11. Coverage header
// ---------------------------------------------------------------------------

describe("UniversalEventDossiersCard — coverage header", () => {
  it("renders the 97 / 65 / 32 coverage summary from the payload", () => {
    expect(closedVisible).toContain("97 historical events");
    expect(closedVisible).toContain("65 FOMC");
    expect(closedVisible).toContain("32 OPEC");
    expect(closedVisible).toContain("97 complete dossiers");
  });

  it("shows the 6 / 91 enrichment split with the approved tier wording", () => {
    expect(closedVisible).toContain("6 published per-event enrichments");
    expect(closedVisible).toContain("91 core evidence records");
    expect(closedVisible).not.toMatch(/\bpremium\b/i);
    expect(closedVisible).not.toMatch(/\bbest\b/i);
    expect(closedVisible).not.toMatch(/high quality/i);
    expect(closedVisible).not.toMatch(/strong evidence/i);
    expect(closedVisible).not.toMatch(/complete case/i);
  });

  it("states the publication-order / no-ranking rule", () => {
    expect(closedVisible).toContain(
      "Publication order. No outcome-based ranking or case selection.",
    );
  });

  it("explains COMPLETE without calling it successful", () => {
    expect(closedVisible).toContain(
      "Every required section has an explicit resolved state; some evidence " +
        "may still be structurally unavailable or not exposed.",
    );
    expect(closedVisible.toLowerCase()).not.toContain("successful");
  });
});

// ---------------------------------------------------------------------------
// 2, 3, 4. Default order, bounded first page, show-more prefix
// ---------------------------------------------------------------------------

describe("UniversalEventDossiersCard — bounded publication-ordered ledger", () => {
  it("renders the first page as an exact prefix of the payload order", () => {
    expect(rowIds(closedHtml)).toEqual(allIds.slice(0, DOSSIER_LEDGER_PAGE_SIZE));
  });

  it("bounds the first page to the page size, never 97 rows", () => {
    expect(DOSSIER_LEDGER_PAGE_SIZE).toBe(25);
    expect(rowIds(closedHtml)).toHaveLength(25);
    expect(closedVisible).toContain("Showing 25 of 97 events");
  });

  it("show-more depths stay pure prefixes of the payload order", () => {
    expect(rowIds(renderCard({ initialRowsShown: 50 }))).toEqual(
      allIds.slice(0, 50),
    );
    expect(rowIds(renderCard({ initialRowsShown: 97 }))).toEqual(allIds);
  });

  it("offers a show-more control while rows remain, none once exhausted", () => {
    expect(closedVisible.toLowerCase()).toContain("show 25 more");
    const fullHtml = renderCard({ initialRowsShown: 97 });
    expect(visibleText(fullHtml).toLowerCase()).not.toContain("more");
  });
});

// ---------------------------------------------------------------------------
// 5, 6, 7. Family filter and search preserve relative publication order
// ---------------------------------------------------------------------------

describe("UniversalEventDossiersCard — outcome-neutral filtering", () => {
  it("family filter renders an order-preserving OPEC subsequence", () => {
    const opecIds = allIds.filter((id) => id.startsWith("opec-"));
    expect(
      rowIds(renderCard({ initialFamilyFilter: "OPEC", initialRowsShown: 97 })),
    ).toEqual(opecIds);
  });

  it("family filter renders an order-preserving FOMC subsequence", () => {
    const fomcIds = allIds.filter((id) => id.startsWith("fomc-"));
    expect(
      rowIds(renderCard({ initialFamilyFilter: "FOMC", initialRowsShown: 97 })),
    ).toEqual(fomcIds);
  });

  it("candidate-id search preserves relative publication order", () => {
    const expected = allIds.filter((id) => id.includes("2019"));
    expect(
      rowIds(renderCard({ initialSearch: "2019", initialRowsShown: 97 })),
    ).toEqual(expected);
  });

  it("exact displayed-date search matches event date and anchor session", () => {
    const target = index.events.find((e) => e.event_date !== e.anchor_session)!;
    const byEventDate = index.events
      .filter(
        (e) =>
          e.event_date === target.event_date ||
          e.anchor_session === target.event_date ||
          e.candidate_id.includes(target.event_date),
      )
      .map((e) => e.candidate_id);
    expect(
      rowIds(
        renderCard({ initialSearch: target.event_date, initialRowsShown: 97 }),
      ),
    ).toEqual(byEventDate);
  });

  it("filterDossierEvents with cleared filters is the identity (order restored)", () => {
    const events = eventDossierIndexFixture().events;
    const cleared = filterDossierEvents(events, "All", "");
    expect(cleared.map((e) => e.candidate_id)).toEqual(allIds);
  });

  it("visibleDossierRows is a pure prefix slice, never a reorder", () => {
    const events = eventDossierIndexFixture().events;
    expect(visibleDossierRows(events, 10).map((e) => e.candidate_id)).toEqual(
      allIds.slice(0, 10),
    );
    expect(visibleDossierRows(events, 0)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// 8, 9. No outcome sort/filter controls; no responses in the ledger
// ---------------------------------------------------------------------------

describe("UniversalEventDossiersCard — no outcome-based controls or values", () => {
  it("offers no sort control and no outcome or enrichment filter", () => {
    expect(closedHtml).not.toContain("<select");
    expect(closedVisible.toLowerCase()).not.toContain("sort");
    // exactly the three family-scope buttons; no status/enrichment/outcome filters
    const pressed = [...closedHtml.matchAll(/aria-pressed="(?:true|false)"/g)];
    expect(pressed).toHaveLength(3);
    expect(closedVisible).toContain("All");
    expect(closedVisible).toContain("FOMC");
    expect(closedVisible).toContain("OPEC");
  });

  it("shows no response, percentile, or aggregate label in ledger rows", () => {
    // no decimal response/percentile strings anywhere in the closed ledger
    expect(closedVisible).not.toMatch(/-?0\.\d{6}/);
    for (const label of [
      "ELEVATED",
      "PROPAGATED",
      "ORDINARY_UNRESOLVED",
      "BROAD MEASUREMENT CONSISTENCY",
    ]) {
      expect(closedVisible).not.toContain(label);
    }
    expect(closedVisible).not.toContain("MEMP");
  });
});

// ---------------------------------------------------------------------------
// 10. Event date and anchor session stay visibly separate
// ---------------------------------------------------------------------------

describe("UniversalEventDossiersCard — event date vs anchor session", () => {
  it("renders both dates for a row where they differ", () => {
    const diff = index.events.find((e) => e.event_date !== e.anchor_session)!;
    const html = renderCard({ initialSearch: diff.candidate_id });
    expect(html).toContain(diff.event_date);
    expect(html).toContain(diff.anchor_session);
  });

  it("labels the two date columns separately for screen readers", () => {
    expect(closedVisible).toContain("Event date");
    expect(closedVisible).toContain("Anchor session");
  });
});

// ---------------------------------------------------------------------------
// 12–15. Fail-closed index states
// ---------------------------------------------------------------------------

function mutated(
  mutate: (idx: EventDossierIndex) => void,
): EventDossierIndex {
  const idx = eventDossierIndexFixture();
  mutate(idx);
  return idx;
}

describe("eventDossierIndexState — fail-closed validation", () => {
  it("rejects a wrong contract version", () => {
    expect(
      eventDossierIndexState(
        mutated((i) => {
          i.contract_version = "event-dossier-index-v2";
        }),
      ),
    ).toBe("malformed");
  });

  it("rejects a wrong universe", () => {
    expect(
      eventDossierIndexState(
        mutated((i) => {
          i.universe = "product";
        }),
      ),
    ).toBe("malformed");
  });

  it("rejects a duplicate candidate id", () => {
    expect(
      eventDossierIndexState(
        mutated((i) => {
          i.events[1].candidate_id = i.events[0].candidate_id;
        }),
      ),
    ).toBe("malformed");
  });

  it("rejects a dropped event (96 of 97)", () => {
    expect(
      eventDossierIndexState(
        mutated((i) => {
          i.events.pop();
        }),
      ),
    ).toBe("malformed");
  });

  it("rejects family-count reconciliation failure", () => {
    expect(
      eventDossierIndexState(
        mutated((i) => {
          i.coverage.family_counts.FOMC = 64;
        }),
      ),
    ).toBe("malformed");
  });

  it("rejects status-count reconciliation failure", () => {
    expect(
      eventDossierIndexState(
        mutated((i) => {
          i.coverage.status_counts.COMPLETE = 96;
          i.coverage.status_counts.PARTIAL = 1;
        }),
      ),
    ).toBe("malformed");
  });

  it("rejects enrichment-count reconciliation failure", () => {
    expect(
      eventDossierIndexState(
        mutated((i) => {
          i.events.find(
            (e) => e.enrichment_tier === "published_per_event_dossier",
          )!.enrichment_tier = "core_published_evidence";
        }),
      ),
    ).toBe("malformed");
  });

  it("rejects invalid status or enrichment vocabulary", () => {
    expect(
      eventDossierIndexState(
        mutated((i) => {
          (i.events[0] as { top_level_status: string }).top_level_status =
            "ELEVATED";
        }),
      ),
    ).toBe("malformed");
    expect(
      eventDossierIndexState(
        mutated((i) => {
          (i.events[0] as { enrichment_tier: string }).enrichment_tier =
            "premium";
        }),
      ),
    ).toBe("malformed");
  });

  it("rejects a missing required entry field", () => {
    expect(
      eventDossierIndexState(
        mutated((i) => {
          delete (i.events[0] as Partial<(typeof i.events)[0]>).anchor_session;
        }),
      ),
    ).toBe("malformed");
  });

  it("rejects section counts that do not sum to 13", () => {
    expect(
      eventDossierIndexState(
        mutated((i) => {
          i.events[0].available_section_count = 5;
        }),
      ),
    ).toBe("malformed");
  });

  it("rejects a reordered payload (OPEC before FOMC) rather than repairing it", () => {
    expect(
      eventDossierIndexState(
        mutated((i) => {
          i.events.reverse();
        }),
      ),
    ).toBe("malformed");
  });

  it("rejects a structurally invalid generated_from reference", () => {
    expect(
      eventDossierIndexState(
        mutated((i) => {
          (i.generated_from[0] as { artifact: unknown }).artifact = 7;
        }),
      ),
    ).toBe("malformed");
  });
});

describe("UniversalEventDossiersCard — malformed index fails closed", () => {
  const malformedHtml = renderCard({
    data: mutated((i) => {
      i.coverage.family_counts.FOMC = 64;
    }),
  });
  const malformedVisible = visibleText(malformedHtml);

  it("renders zero event controls and zero ledger rows", () => {
    expect(rowIds(malformedHtml)).toEqual([]);
    expect(malformedHtml).not.toContain("<table");
    expect(malformedHtml).not.toContain("<button");
  });

  it("states an explicit contract-unavailable refusal, never an empty ledger", () => {
    expect(malformedVisible).toContain(
      "did not match the event-dossier-index-v1 contract",
    );
    expect(malformedVisible.toLowerCase()).toContain("no event ledger is shown");
  });

  it("keeps the loading and unavailable states distinct from malformed", () => {
    const loading = visibleText(renderCard({ data: undefined }));
    expect(loading.toLowerCase()).toContain("loading");
    const unavailable = visibleText(
      renderCard({ data: undefined, unavailable: true }),
    );
    expect(unavailable.toLowerCase()).toContain("unavailable");
    expect(unavailable).not.toContain("did not match");
  });
});

// ---------------------------------------------------------------------------
// Accessibility floor for the ledger controls
// ---------------------------------------------------------------------------

describe("UniversalEventDossiersCard — ledger accessibility", () => {
  it("uses semantic type=button controls only (no clickable divs)", () => {
    const buttons = closedHtml.match(/<button[^>]*>/g) ?? [];
    expect(buttons.length).toBeGreaterThan(0);
    for (const b of buttons) {
      expect(b).toContain('type="button"');
    }
    expect(closedHtml).not.toMatch(/<div[^>]*role="button"/);
  });

  it("gives every ledger open-control the aria-expanded / aria-controls contract", () => {
    const openControls = closedHtml.match(/data-dossier-open="[^"]+"/g) ?? [];
    expect(openControls).toHaveLength(25);
    const expanded = closedHtml.match(
      /data-dossier-open="[^"]+"[^>]*aria-expanded="false"/g,
    ) ?? [];
    expect(expanded).toHaveLength(25);
    expect(closedHtml).toMatch(/data-dossier-open="[^"]+"[^>]*aria-controls=/);
  });

  it("labels the search input and scopes the table headers", () => {
    expect(closedHtml).toContain("<label");
    expect(closedHtml).toMatch(/<input[^>]*type="search"/);
    const headers = closedHtml.match(/<th\s[^>]*>/g) ?? [];
    expect(headers.length).toBeGreaterThan(0);
    for (const th of headers) {
      expect(th).toContain('scope="col"');
    }
  });
});

// ---------------------------------------------------------------------------
// Evidence Overview integration — initial state of the mounted section
// ---------------------------------------------------------------------------

describe("EvidenceOverview — universal event dossiers section (U1)", () => {
  it("renders the coverage summary and a bounded ledger from a seeded index, with zero dossier sections mounted", () => {
    const client = testQueryClient();
    client.setQueryData(qk.eventDossierIndex(), eventDossierIndexFixture());
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <EvidenceOverview />
      </QueryClientProvider>,
    );
    const text = visibleText(html);
    expect(text).toContain("Universal event dossiers");
    expect(text).toContain("97 historical events");
    expect(rowIds(html)).toHaveLength(DOSSIER_LEDGER_PAGE_SIZE);
    expect(html).not.toContain("data-dossier-section");
    expect(html).not.toContain("data-dossier-panel");
  });

  it("shows the honest index loading state on the unseeded page render", () => {
    const html = renderToStaticMarkup(
      <QueryClientProvider client={testQueryClient()}>
        <EvidenceOverview />
      </QueryClientProvider>,
    );
    expect(visibleText(html)).toContain("Loading the tracked dossier index…");
    expect(rowIds(html)).toHaveLength(0);
  });
});
