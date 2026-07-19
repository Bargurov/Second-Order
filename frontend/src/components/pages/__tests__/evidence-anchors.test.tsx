/**
 * M1/N2/U1 — stable Evidence anchors + bounded hash scrolling.
 *
 * Exactly six stable section IDs on the Evidence Overview content (page
 * header, canonical denominator ledger, Mission G record, Mission I record,
 * Mission J record, universal event dossiers — N2 added mission-i between
 * mission-g and mission-j; U1 added event-dossiers after mission-j), each
 * unique, each offset for the sticky TopBar, each present even while the
 * fetched records are still loading. Hash scrolling is a pure, injectable
 * helper: known IDs scroll, unknown hashes fail quietly, and the
 * hashchange listener is StrictMode-safe.
 *
 * Render-smoke pattern (renderToStaticMarkup, no jsdom).
 */
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  EvidenceOverview,
  EVIDENCE_ANCHOR_IDS,
  scrollToEvidenceHash,
  installEvidenceHashScroll,
} from "../evidence-overview";
import { qk } from "@/lib/queryKeys";
import { missionJFixture } from "@/components/ui/__tests__/mission-j-fixture";

function testQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity, gcTime: Infinity },
    },
  });
}

function renderOverview(client: QueryClient): string {
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <EvidenceOverview />
    </QueryClientProvider>,
  );
}

// Baseline render — Mission G/J queries unseeded, i.e. both cards in their
// honest loading state. The anchors must already exist here.
const loadingHtml = renderOverview(testQueryClient());

const seededClient = testQueryClient();
seededClient.setQueryData(qk.missionJEvidence(), missionJFixture());
const seededHtml = renderOverview(seededClient);

function countAnchor(html: string, id: string): number {
  return (html.match(new RegExp(`id="${id}"`, "g")) ?? []).length;
}

function anchorTag(html: string, id: string): string {
  const m = html.match(new RegExp(`<[^>]*id="${id}"[^>]*>`));
  return m?.[0] ?? "";
}

describe("EvidenceOverview — stable anchor IDs (M1/N2/U1)", () => {
  it("exposes exactly the six documented anchor IDs, event-dossiers after mission-j", () => {
    expect([...EVIDENCE_ANCHOR_IDS]).toEqual([
      "evidence-top",
      "denominators",
      "mission-g",
      "mission-i",
      "mission-j",
      "event-dossiers",
    ]);
  });

  it("renders each anchor ID exactly once", () => {
    for (const id of EVIDENCE_ANCHOR_IDS) {
      expect(countAnchor(loadingHtml, id), id).toBe(1);
    }
  });

  it("keeps the fetched-record anchors present while their records are loading", () => {
    expect(countAnchor(loadingHtml, "mission-g")).toBe(1);
    expect(countAnchor(loadingHtml, "mission-i")).toBe(1);
    expect(countAnchor(loadingHtml, "mission-j")).toBe(1);
    expect(countAnchor(loadingHtml, "event-dossiers")).toBe(1);
  });

  it("orders mission-i between g and j, and event-dossiers after mission-j", () => {
    const g = loadingHtml.indexOf('id="mission-g"');
    const i = loadingHtml.indexOf('id="mission-i"');
    const j = loadingHtml.indexOf('id="mission-j"');
    const d = loadingHtml.indexOf('id="event-dossiers"');
    expect(g).toBeGreaterThan(-1);
    expect(i).toBeGreaterThan(g);
    expect(j).toBeGreaterThan(i);
    expect(d).toBeGreaterThan(j);
  });

  it("keeps each anchor unique once the Mission J record resolves", () => {
    for (const id of EVIDENCE_ANCHOR_IDS) {
      expect(countAnchor(seededHtml, id), id).toBe(1);
    }
  });

  it("offsets every anchor for the sticky TopBar (scroll-margin-top)", () => {
    for (const id of EVIDENCE_ANCHOR_IDS) {
      expect(anchorTag(loadingHtml, id), id).toContain("scroll-mt-");
    }
  });
});

// ---------------------------------------------------------------------------
// Pure hash-scroll helper
// ---------------------------------------------------------------------------

function fakeDoc(presentIds: string[]) {
  const scrolled: string[] = [];
  return {
    scrolled,
    getElementById(id: string) {
      if (!presentIds.includes(id)) return null;
      return {
        scrollIntoView: () => scrolled.push(id),
      } as unknown as HTMLElement;
    },
  };
}

describe("scrollToEvidenceHash — bounded scrolling (M1)", () => {
  it("scrolls to each known anchor and reports success", () => {
    for (const id of EVIDENCE_ANCHOR_IDS) {
      const doc = fakeDoc([...EVIDENCE_ANCHOR_IDS]);
      expect(scrollToEvidenceHash(`#${id}`, doc)).toBe(true);
      expect(doc.scrolled).toEqual([id]);
    }
  });

  it("fails quietly on unknown hashes", () => {
    const doc = fakeDoc([...EVIDENCE_ANCHOR_IDS]);
    expect(scrollToEvidenceHash("#not-an-anchor", doc)).toBe(false);
    expect(scrollToEvidenceHash("#Mission-J", doc)).toBe(false);
    expect(doc.scrolled).toEqual([]);
  });

  it("fails quietly on an empty or bare hash", () => {
    const doc = fakeDoc([...EVIDENCE_ANCHOR_IDS]);
    expect(scrollToEvidenceHash("", doc)).toBe(false);
    expect(scrollToEvidenceHash("#", doc)).toBe(false);
    expect(doc.scrolled).toEqual([]);
  });

  it("fails quietly when the target element is not in the document yet", () => {
    const doc = fakeDoc([]);
    expect(scrollToEvidenceHash("#mission-j", doc)).toBe(false);
    expect(doc.scrolled).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// hashchange listener lifecycle
// ---------------------------------------------------------------------------

type HashHandler = () => void;

function fakeHashWindow(hash: string) {
  const handlers: HashHandler[] = [];
  return {
    location: { hash },
    handlers,
    addEventListener(_type: "hashchange", fn: HashHandler) {
      handlers.push(fn);
    },
    removeEventListener(_type: "hashchange", fn: HashHandler) {
      const i = handlers.indexOf(fn);
      if (i !== -1) handlers.splice(i, 1);
    },
    dispatch() {
      for (const fn of [...handlers]) fn();
    },
  };
}

describe("installEvidenceHashScroll — post-mount + hashchange scrolling (M1)", () => {
  it("scrolls the direct-entry hash immediately after mount", () => {
    const win = fakeHashWindow("#mission-j");
    const doc = fakeDoc([...EVIDENCE_ANCHOR_IDS]);
    installEvidenceHashScroll(win, doc);
    expect(doc.scrolled).toEqual(["mission-j"]);
  });

  it("does nothing on mount without a hash, then scrolls on a hash change", () => {
    const win = fakeHashWindow("");
    const doc = fakeDoc([...EVIDENCE_ANCHOR_IDS]);
    installEvidenceHashScroll(win, doc);
    expect(doc.scrolled).toEqual([]);

    win.location.hash = "#denominators";
    win.dispatch();
    expect(doc.scrolled).toEqual(["denominators"]);
  });

  it("ignores unknown hashes from hash changes", () => {
    const win = fakeHashWindow("");
    const doc = fakeDoc([...EVIDENCE_ANCHOR_IDS]);
    installEvidenceHashScroll(win, doc);
    win.location.hash = "#unknown";
    win.dispatch();
    expect(doc.scrolled).toEqual([]);
  });

  it("cleanup removes the listener; a StrictMode cycle keeps exactly one", () => {
    const win = fakeHashWindow("");
    const doc = fakeDoc([...EVIDENCE_ANCHOR_IDS]);
    const cleanup1 = installEvidenceHashScroll(win, doc);
    cleanup1();
    expect(win.handlers).toHaveLength(0);

    installEvidenceHashScroll(win, doc);
    expect(win.handlers).toHaveLength(1);
    win.location.hash = "#evidence-top";
    win.dispatch();
    expect(doc.scrolled).toEqual(["evidence-top"]);
  });
});
