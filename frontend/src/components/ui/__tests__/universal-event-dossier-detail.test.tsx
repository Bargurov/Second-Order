/**
 * U1 — Universal Event Dossier reader: one opened dossier.
 *
 * A dossier is fetched only after the reviewer opens an event; exactly one
 * dossier is mounted at a time; its 13 sections render in the backend's
 * frozen order with progressive disclosure; aggregate research context
 * stays visibly aggregate (never an event verdict); missingness and the
 * permanent non-claim stay visible; G6C material renders only as
 * separately-labeled optional enrichment; and a malformed or mismatched
 * detail fails closed with an explicit refusal while the index ledger
 * stays usable.
 *
 * Render-smoke pattern (renderToStaticMarkup, no jsdom): the detail
 * payload is seeded into the React Query cache under its real query key,
 * so the card's own query path — not an injection side-channel — serves
 * the panel.  Live fetch-on-open is proven by the browser smoke.
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { EventDossierDetail } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import {
  DOSSIER_SECTION_ORDER,
  UniversalEventDossiersCard,
  eventDossierDetailState,
} from "../universal-event-dossiers";
import {
  EVENT_DOSSIER_PROBE_IDS,
  eventDossierDetailFixture,
  eventDossierIndexFixture,
  type EventDossierProbeKey,
} from "./event-dossier-fixture";

function testQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity, gcTime: Infinity },
    },
  });
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

function rowIds(html: string): string[] {
  return [...html.matchAll(/data-dossier-row="([^"]+)"/g)].map((m) => m[1]);
}

function sectionNames(html: string): string[] {
  return [...html.matchAll(/data-dossier-section="([^"]+)"/g)].map((m) => m[1]);
}

interface OpenRenderOptions {
  detail?: EventDossierDetail;
  seedId?: string;
  props?: Partial<Parameters<typeof UniversalEventDossiersCard>[0]>;
}

function renderOpen(key: EventDossierProbeKey, opts: OpenRenderOptions = {}): string {
  const id = EVENT_DOSSIER_PROBE_IDS[key];
  const detail = opts.detail ?? eventDossierDetailFixture(key);
  const client = testQueryClient();
  client.setQueryData(qk.eventDossierDetail(opts.seedId ?? id), detail);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <UniversalEventDossiersCard
        data={eventDossierIndexFixture()}
        initialOpenCandidateId={id}
        {...opts.props}
      />
    </QueryClientProvider>,
  );
}

const fomcEnrichedHtml = renderOpen("fomc_enriched");
const fomcCoreHtml = renderOpen("fomc_core");
const opecEnrichedHtml = renderOpen("opec_enriched");
const opecCoreHtml = renderOpen("opec_core");
const fomcEnrichedVisible = visibleText(fomcEnrichedHtml);
const fomcCoreVisible = visibleText(fomcCoreHtml);
const opecEnrichedVisible = visibleText(opecEnrichedHtml);
const opecCoreVisible = visibleText(opecCoreHtml);

// Every-section-open renders (documented `initialOpenSections` seam — the
// ReactionProfileCard `initialHorizon` precedent): deep section bodies are
// collapsed by default, so their content assertions render fully disclosed.
const ALL_OPEN = { props: { initialOpenSections: [...DOSSIER_SECTION_ORDER] } };
const fomcEnrichedOpenHtml = renderOpen("fomc_enriched", ALL_OPEN);
const opecEnrichedOpenHtml = renderOpen("opec_enriched", ALL_OPEN);
const opecCoreOpenHtml = renderOpen("opec_core", ALL_OPEN);
const fomcEnrichedOpenVisible = visibleText(fomcEnrichedOpenHtml);
const opecEnrichedOpenVisible = visibleText(opecEnrichedOpenHtml);
const opecCoreOpenVisible = visibleText(opecCoreOpenHtml);

// ---------------------------------------------------------------------------
// Captured-fixture acceptance — real producer details pass the validator
// ---------------------------------------------------------------------------

describe("event-dossier-v1 — captured fixture acceptance", () => {
  it("accepts all four captured probe dossiers against their index entries", () => {
    const index = eventDossierIndexFixture();
    for (const key of Object.keys(EVENT_DOSSIER_PROBE_IDS) as EventDossierProbeKey[]) {
      const id = EVENT_DOSSIER_PROBE_IDS[key];
      const entry = index.events.find((e) => e.candidate_id === id)!;
      expect(
        eventDossierDetailState(eventDossierDetailFixture(key), id, entry),
        key,
      ).toBe("ok");
    }
  });

  it("keeps exactly the 13 frozen sections in payload order", () => {
    for (const key of Object.keys(EVENT_DOSSIER_PROBE_IDS) as EventDossierProbeKey[]) {
      expect(Object.keys(eventDossierDetailFixture(key).sections)).toEqual([
        ...DOSSIER_SECTION_ORDER,
      ]);
    }
  });
});

// ---------------------------------------------------------------------------
// 16–18. Lazy detail, one dossier at a time, closed state
// ---------------------------------------------------------------------------

describe("UniversalEventDossiersCard — detail lifecycle", () => {
  it("mounts zero dossier sections and registers zero detail queries while closed", () => {
    const client = testQueryClient();
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <UniversalEventDossiersCard data={eventDossierIndexFixture()} />
      </QueryClientProvider>,
    );
    expect(sectionNames(html)).toEqual([]);
    expect(html).not.toContain("data-dossier-panel");
    expect(client.getQueryCache().getAll()).toHaveLength(0);
  });

  it("mounts exactly one dossier panel for the opened event", () => {
    const panels = fomcEnrichedHtml.match(/data-dossier-panel="[^"]+"/g) ?? [];
    expect(panels).toEqual([
      `data-dossier-panel="${EVENT_DOSSIER_PROBE_IDS.fomc_enriched}"`,
    ]);
  });

  it("offers an explicit close control on the opened panel", () => {
    expect(fomcEnrichedHtml).toMatch(/<button[^>]*data-dossier-close/);
  });

  it("keeps the open dossier open when a family filter hides its row (explicit rule)", () => {
    const html = renderOpen("fomc_core", {
      props: { initialFamilyFilter: "OPEC", initialRowsShown: 97 },
    });
    expect(rowIds(html).every((id) => id.startsWith("opec-"))).toBe(true);
    expect(html).toContain(
      `data-dossier-panel="${EVENT_DOSSIER_PROBE_IDS.fomc_core}"`,
    );
  });
});

// ---------------------------------------------------------------------------
// 19. Exact 13-section inventory in frozen order
// ---------------------------------------------------------------------------

describe("EventDossierPanel — frozen section inventory", () => {
  it("renders all 13 sections in the backend's frozen order", () => {
    for (const html of [fomcEnrichedHtml, fomcCoreHtml, opecEnrichedHtml, opecCoreHtml]) {
      expect(sectionNames(html)).toEqual([...DOSSIER_SECTION_ORDER]);
    }
  });

  it("shows the dossier header identity: id, family, dates, status, tier, counts", () => {
    const id = EVENT_DOSSIER_PROBE_IDS.fomc_core;
    const entry = eventDossierIndexFixture().events.find(
      (e) => e.candidate_id === id,
    )!;
    expect(fomcCoreVisible).toContain(id);
    expect(fomcCoreVisible).toContain("COMPLETE");
    expect(fomcCoreVisible).toContain("Core published evidence");
    expect(fomcCoreVisible).toContain(
      `${entry.available_section_count} available`,
    );
    expect(fomcCoreVisible).toContain(
      `${entry.unavailable_section_count} unavailable`,
    );
  });
});

// ---------------------------------------------------------------------------
// 20–22. Fail-closed detail states preserve the index
// ---------------------------------------------------------------------------

describe("UniversalEventDossiersCard — malformed detail fails closed", () => {
  it("refuses a response whose candidate id differs from the request", () => {
    const wrong = eventDossierDetailFixture("fomc_enriched");
    const html = renderOpen("fomc_core", { detail: wrong });
    expect(sectionNames(html)).toEqual([]);
    expect(visibleText(html)).toContain(
      "did not match the event-dossier-v1 contract",
    );
    expect(rowIds(html)).toHaveLength(25);
  });

  it("refuses a dossier whose identity disagrees with the index entry", () => {
    const detail = eventDossierDetailFixture("fomc_core");
    (detail.sections.identity.data as { family: string }).family = "OPEC";
    const html = renderOpen("fomc_core", { detail });
    expect(sectionNames(html)).toEqual([]);
    expect(visibleText(html)).toContain("did not match");
  });

  it("refuses a dossier with a missing section but keeps the ledger usable", () => {
    const detail = eventDossierDetailFixture("opec_core");
    delete (detail.sections as Record<string, unknown>).missingness_limitations;
    const html = renderOpen("opec_core", { detail });
    expect(sectionNames(html)).toEqual([]);
    expect(visibleText(html)).toContain(
      "did not match the event-dossier-v1 contract",
    );
    expect(rowIds(html)).toHaveLength(25);
    expect(visibleText(html)).toContain("97 historical events");
  });

  it("never partially renders a malformed dossier (no orphan tables)", () => {
    const detail = eventDossierDetailFixture("fomc_enriched");
    (detail.sections.reaction_observations.data as { rows: unknown[] }).rows.pop();
    const html = renderOpen("fomc_enriched", { detail });
    expect(sectionNames(html)).toEqual([]);
    expect(html).not.toContain("data-dossier-panel");
  });
});

describe("eventDossierDetailState — fail-closed validation", () => {
  const index = eventDossierIndexFixture();
  const id = EVENT_DOSSIER_PROBE_IDS.fomc_core;
  const entry = index.events.find((e) => e.candidate_id === id)!;

  function state(mutate: (d: EventDossierDetail) => void): string {
    const d = eventDossierDetailFixture("fomc_core");
    mutate(d);
    return eventDossierDetailState(d, id, entry);
  }

  it("rejects a wrong contract version", () => {
    expect(
      state((d) => {
        d.contract_version = "event-dossier-v2";
      }),
    ).toBe("malformed");
  });

  it("rejects reordered sections rather than repairing them", () => {
    expect(
      state((d) => {
        const { identity, ...rest } = d.sections;
        d.sections = { ...rest, identity };
      }),
    ).toBe("malformed");
  });

  it("rejects an extra fourteenth section", () => {
    expect(
      state((d) => {
        (d.sections as Record<string, unknown>).extra = d.sections.non_claim;
      }),
    ).toBe("malformed");
  });

  it("rejects a section missing one of the five required fields", () => {
    expect(
      state((d) => {
        delete (d.sections.identity as Partial<typeof d.sections.identity>)
          .reason_code;
      }),
    ).toBe("malformed");
  });

  it("rejects invalid top-level or section status vocabulary", () => {
    expect(
      state((d) => {
        (d as { top_level_status: string }).top_level_status = "ELEVATED";
      }),
    ).toBe("malformed");
    expect(
      state((d) => {
        (d.sections.identity as { status: string }).status = "PROPAGATED";
      }),
    ).toBe("malformed");
  });

  it("rejects an aggregate label outside explicit aggregate context", () => {
    expect(
      state((d) => {
        (d.sections.identity.data as { identity_status: string }).identity_status =
          "ELEVATED";
      }),
    ).toBe("malformed");
  });

  it("rejects a core dossier whose enrichment is not explicitly not_exposed", () => {
    expect(
      state((d) => {
        (d.sections.reaction_enrichment as { status: string }).status =
          "available";
      }),
    ).toBe("malformed");
  });

  it("rejects a FOMC dossier without the structural FOMC 20d state", () => {
    expect(
      state((d) => {
        delete (d.sections.ordinary_period_context.data as { fomc_20d?: unknown })
          .fomc_20d;
      }),
    ).toBe("malformed");
  });

  it("rejects a missing non-claim statement", () => {
    expect(
      state((d) => {
        (d.sections.non_claim.data as { statement: string }).statement = "";
      }),
    ).toBe("malformed");
  });

  it("rejects a structurally invalid source reference", () => {
    expect(
      state((d) => {
        (d.sections.identity.source_references[0] as { artifact: unknown }).artifact = 7;
      }),
    ).toBe("malformed");
  });

  it("rejects an OPEC dossier whose Mission J block is not not_applicable", () => {
    const opecId = EVENT_DOSSIER_PROBE_IDS.opec_core;
    const opecEntry = index.events.find((e) => e.candidate_id === opecId)!;
    const d = eventDossierDetailFixture("opec_core");
    (
      d.sections.robustness_timing_transmission.data as {
        mission_j: { status: string };
      }
    ).mission_j.status = "available";
    expect(eventDossierDetailState(d, opecId, opecEntry)).toBe("malformed");
  });

  it("rejects a wrong per-family reaction row count", () => {
    expect(
      state((d) => {
        (d.sections.reaction_observations.data as { rows: unknown[] }).rows.pop();
      }),
    ).toBe("malformed");
  });
});

// ---------------------------------------------------------------------------
// Atomic aggregate labels (U1 repair) — the frozen vocabulary must cover
// the standalone forms ORDINARY and UNRESOLVED exactly like their
// compound variants: rejected outside explicit aggregate scope, rejected
// in any status field, accepted as plain aggregate-scoped values.
// ---------------------------------------------------------------------------

describe("eventDossierDetailState — atomic aggregate labels (U1 repair)", () => {
  const ATOMIC_LABELS = ["ORDINARY", "UNRESOLVED"] as const;
  const index = eventDossierIndexFixture();
  const fomcId = EVENT_DOSSIER_PROBE_IDS.fomc_core;
  const fomcEntry = index.events.find((e) => e.candidate_id === fomcId)!;

  function timingCells(d: EventDossierDetail): Array<Record<string, unknown>> {
    return (
      d.sections.robustness_timing_transmission.data as {
        mission_j: { j2_timing_cells: Array<Record<string, unknown>> };
      }
    ).mission_j.j2_timing_cells;
  }

  it("rejects each atomic label in a non-aggregate event-level field", () => {
    for (const label of ATOMIC_LABELS) {
      const d = eventDossierDetailFixture("fomc_core");
      (d.sections.identity.data as Record<string, unknown>).event_label = label;
      expect(eventDossierDetailState(d, fomcId, fomcEntry), label).toBe(
        "malformed",
      );
    }
  });

  it("fails closed in the consumer: refusal, zero sections, valid index preserved", () => {
    const d = eventDossierDetailFixture("fomc_core");
    (d.sections.identity.data as Record<string, unknown>).event_label =
      "ORDINARY";
    const html = renderOpen("fomc_core", { detail: d });
    expect(sectionNames(html)).toEqual([]);
    expect(html).not.toContain("data-dossier-panel");
    expect(visibleText(html)).toContain(
      "did not match the event-dossier-v1 contract",
    );
    expect(rowIds(html)).toHaveLength(25);
    expect(visibleText(html)).toContain("97 historical events");
  });

  it("accepts each atomic label as a plain value inside explicit aggregate scope", () => {
    for (const label of ATOMIC_LABELS) {
      const d = eventDossierDetailFixture("fomc_core");
      timingCells(d).push({
        metric: "raw_return",
        window: "[-1, +1]",
        label,
      });
      expect(eventDossierDetailState(d, fomcId, fomcEntry), label).toBe("ok");
    }
  });

  it("rejects each atomic label used as a status even inside aggregate scope", () => {
    for (const label of ATOMIC_LABELS) {
      const d = eventDossierDetailFixture("fomc_core");
      timingCells(d).push({
        metric: "raw_return",
        window: "[-1, +1]",
        label: "ORDINARY_UNRESOLVED",
        status: label,
      });
      expect(eventDossierDetailState(d, fomcId, fomcEntry), label).toBe(
        "malformed",
      );
    }
  });
});

// ---------------------------------------------------------------------------
// 23–24. Enrichment: optional G6C tier vs explicit not-exposed
// ---------------------------------------------------------------------------

describe("EventDossierPanel — reaction enrichment tier", () => {
  it("core dossiers state the not-exposed enrichment, with no placeholder table", () => {
    for (const visible of [fomcCoreVisible, opecCoreVisible]) {
      expect(visible).toContain("Not exposed");
      expect(visible).toContain(
        "No published richer per-event reaction dossier exists",
      );
    }
    const enrichment = fomcCoreHtml.match(
      /data-dossier-section="reaction_enrichment"[\s\S]*?data-dossier-section="ordinary_period_context"/,
    )![0];
    expect(enrichment).not.toContain("<table");
  });

  it("enriched dossiers label the G6C readout as separate optional enrichment", () => {
    for (const visible of [fomcEnrichedOpenVisible, opecEnrichedOpenVisible]) {
      expect(visible).toContain("Optional enrichment");
      expect(visible).toContain("G6C");
      expect(visible).toContain("absolute asset return");
      expect(visible.toLowerCase()).toContain("illustration-only");
    }
  });

  it("keeps the enriched tier wording tier-neutral in the panel header", () => {
    // scoped to the header chrome: payload research wording elsewhere may
    // legitimately contain e.g. "term premium" verbatim
    const header = fomcEnrichedHtml.match(
      /data-dossier-header[\s\S]*?data-dossier-section=/,
    )![0];
    const headerVisible = visibleText(header);
    expect(headerVisible).toContain("Published per-event enrichment");
    expect(headerVisible.toLowerCase()).not.toContain("premium enrichment");
    expect(headerVisible.toLowerCase()).not.toMatch(/\bbest\b|\bstrongest\b/);
  });
});

// ---------------------------------------------------------------------------
// 25–27. Family-specific structural states
// ---------------------------------------------------------------------------

describe("EventDossierPanel — family-specific structural states", () => {
  it("shows the FOMC 20d structural unavailability prominently", () => {
    for (const visible of [fomcEnrichedVisible, fomcCoreVisible]) {
      expect(visible).toContain("FOMC 20d");
      expect(visible.toLowerCase()).toContain("structurally unavailable");
      expect(visible).toContain("not a data gap");
    }
  });

  it("states Mission J as not applicable on OPEC dossiers, even fully disclosed", () => {
    for (const visible of [opecEnrichedVisible, opecCoreVisible, opecCoreOpenVisible]) {
      expect(visible).toContain("Not applicable — Mission J is FOMC-only.");
    }
    expect(opecCoreOpenVisible).not.toContain("J1B");
    expect(opecEnrichedOpenVisible).not.toContain("J1B");
  });

  it("shows the Mission J aggregate surfaces separately on FOMC dossiers", () => {
    expect(fomcEnrichedOpenVisible).toContain("J1B");
    expect(fomcEnrichedOpenVisible).toContain("J2");
    expect(fomcEnrichedOpenVisible).toContain("J3");
    expect(fomcEnrichedOpenVisible).toContain("64 / 65");
    expect(fomcEnrichedOpenVisible).toContain("0/65");
    expect(fomcEnrichedOpenVisible.toLowerCase()).toContain("unadjudicable");
    expect(fomcEnrichedOpenVisible).toContain("PROPAGATED");
    expect(fomcEnrichedOpenVisible).toContain(
      "frozen descriptive edge label at the published claim ceiling",
    );
  });

  it("keeps FOMC and OPEC denominators separate (65 vs 32, never pooled)", () => {
    expect(fomcCoreVisible).toContain("65");
    expect(fomcCoreVisible).not.toContain("97 of 97");
    expect(opecCoreVisible).toContain("32");
  });
});

// ---------------------------------------------------------------------------
// 28–29. Aggregate context stays aggregate; observation stays distinct
// ---------------------------------------------------------------------------

describe("EventDossierPanel — aggregate context handling", () => {
  it("never shows an aggregate label in the dossier header", () => {
    const header = fomcEnrichedHtml.match(
      /data-dossier-header[\s\S]*?data-dossier-section=/,
    )![0];
    const headerVisible = visibleText(header);
    for (const label of [
      "ELEVATED",
      "PROPAGATED",
      "ORDINARY_UNRESOLVED",
      "BROAD MEASUREMENT CONSISTENCY",
    ]) {
      expect(headerVisible).not.toContain(label);
    }
  });

  it("tags every aggregate block as aggregate context, not an event classification", () => {
    const tags =
      fomcEnrichedOpenVisible.match(
        /Aggregate context — not an individual-event classification/g,
      ) ?? [];
    expect(tags.length).toBeGreaterThanOrEqual(3);
  });

  it("keeps the published aggregate and this event's observation separately labeled", () => {
    expect(fomcEnrichedOpenVisible).toContain("Published aggregate");
    expect(fomcEnrichedOpenVisible).toContain("This event's observation");
  });

  it("keeps Mission I and Mission G aggregate blocks separate", () => {
    expect(fomcEnrichedOpenVisible).toContain("Mission I aggregate context");
    expect(fomcEnrichedOpenVisible).toContain("Mission G aggregate context");
  });
});

// ---------------------------------------------------------------------------
// 30–31. Missingness and the permanent non-claim stay visible
// ---------------------------------------------------------------------------

describe("EventDossierPanel — missingness and non-claim visibility", () => {
  it("keeps missingness and the non-claim visible even with every disclosure collapsed", () => {
    const html = renderOpen("fomc_core", { props: { initialOpenSections: [] } });
    const visible = visibleText(html);
    expect(visible).toContain("stated null, never inferred");
    const statement = (
      eventDossierDetailFixture("fomc_core").sections.non_claim.data as {
        statement: string;
      }
    ).statement;
    expect(visible).toContain(statement);
    // collapsed sections keep their bodies unmounted
    expect(html).not.toMatch(/data-dossier-section="reaction_observations"[\s\S]{0,400}<table/);
  });

  it("renders every missingness reason code with its statement", () => {
    const items = (
      eventDossierDetailFixture("opec_core").sections.missingness_limitations
        .data as { items: Array<{ reason_code: string; statement: string }> }
    ).items;
    expect(items.length).toBeGreaterThanOrEqual(5);
    for (const item of items) {
      expect(opecCoreVisible).toContain(item.reason_code);
      expect(opecCoreVisible).toContain(item.statement);
    }
  });

  it("renders the full permanent non-claim near the dossier footer", () => {
    const statement = (
      eventDossierDetailFixture("opec_enriched").sections.non_claim.data as {
        statement: string;
      }
    ).statement;
    expect(statement.length).toBeGreaterThan(100);
    expect(opecEnrichedVisible).toContain(statement);
  });
});

// ---------------------------------------------------------------------------
// 32, 34. Provenance disclosure; nulls stated, never inferred
// ---------------------------------------------------------------------------

describe("EventDossierPanel — provenance disclosure", () => {
  it("offers one provenance disclosure per section (13), collapsed by default", () => {
    const blocks = fomcEnrichedHtml.match(/data-dossier-provenance/g) ?? [];
    expect(blocks).toHaveLength(13);
    expect(fomcEnrichedHtml).toMatch(/<details[^>]*data-dossier-provenance/);
  });

  it("shows artifact, full SHA-256 and bytes for tracked references", () => {
    const ref = eventDossierDetailFixture("fomc_enriched").sections.identity
      .source_references[0];
    expect(fomcEnrichedVisible).toContain(ref.artifact);
    expect(fomcEnrichedVisible).toContain(ref.sha256!);
    expect(fomcEnrichedVisible).toContain(String(ref.bytes!));
  });

  it("states missing hash / byte fields as not exposed, never inferred", () => {
    // the non-claim section cites the dossier contract itself: no sha, no bytes
    const nonClaimBlock = fomcCoreHtml.match(
      /data-dossier-section="non_claim"[\s\S]*$/,
    )![0];
    const visible = visibleText(nonClaimBlock);
    expect(visible).toContain("event-dossier-v1");
    expect(visible).toContain("SHA-256: not exposed");
  });
});

// ---------------------------------------------------------------------------
// 33. Method percentile warning
// ---------------------------------------------------------------------------

describe("EventDossierPanel — method percentile warning", () => {
  it("keeps the mid-rank method note visible with the observations", () => {
    for (const visible of [fomcEnrichedVisible, opecCoreVisible]) {
      expect(visible).toContain("mid-rank method percentile");
      expect(visible).toContain("not a strength, rank, or probability score");
    }
  });
});

// ---------------------------------------------------------------------------
// 35. Keyboard / ARIA floor
// ---------------------------------------------------------------------------

describe("EventDossierPanel — accessibility floor", () => {
  it("uses semantic type=button controls with aria-expanded/aria-controls", () => {
    const buttons = fomcEnrichedHtml.match(/<button[^>]*>/g) ?? [];
    for (const b of buttons) {
      expect(b).toContain('type="button"');
    }
    const toggles =
      fomcEnrichedHtml.match(/data-dossier-toggle="[^"]+"/g) ?? [];
    expect(toggles.length).toBeGreaterThanOrEqual(10);
    const withAria =
      fomcEnrichedHtml.match(
        /data-dossier-toggle="[^"]+"[^>]*aria-expanded="(?:true|false)"[^>]*aria-controls="[^"]+"/g,
      ) ?? [];
    expect(withAria.length).toBe(toggles.length);
    expect(fomcEnrichedHtml).not.toMatch(/<div[^>]*role="button"/);
  });

  it("distinguishes event date and anchor session for screen readers", () => {
    expect(fomcEnrichedVisible).toContain("Event date");
    expect(fomcEnrichedVisible).toContain("Anchor session");
  });

  it("labels the opened panel as a region", () => {
    expect(fomcEnrichedHtml).toMatch(
      /<section[^>]*data-dossier-panel[^>]*aria-labelledby=/,
    );
  });
});

// ---------------------------------------------------------------------------
// Claim-language provenance: the panel chrome adds no banned token beyond
// the payload's own sanctioned wording (the non-claim list and verbatim
// contract summaries).
// ---------------------------------------------------------------------------

describe("EventDossierPanel — no new banned framing beyond the payload", () => {
  const BANNED =
    /\b(buy|sell|long|short|alpha|signal|trade|proof|proves|confirmed|forecast|proven|premium|best|strongest|winner|loser|score|ranked)\b/gi;

  it("every banned-token occurrence in the fully disclosed panels exists in the payload", () => {
    for (const key of Object.keys(EVENT_DOSSIER_PROBE_IDS) as EventDossierProbeKey[]) {
      const payload = JSON.stringify(eventDossierDetailFixture(key)).toLowerCase();
      const html = renderOpen(key, ALL_OPEN);
      const matches = visibleText(html).match(BANNED) ?? [];
      for (const m of matches) {
        expect(
          payload.includes(m.toLowerCase()),
          `panel chrome introduced banned token "${m}" (${key})`,
        ).toBe(true);
      }
    }
  });
});
