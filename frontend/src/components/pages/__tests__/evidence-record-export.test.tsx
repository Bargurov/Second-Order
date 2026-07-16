/**
 * M2 — Evidence Overview research-record export action.
 *
 * Exactly one quiet "Download research record (.md)" action near the page
 * header: disabled (with a quiet "Preparing tracked evidence…" note) while
 * either Mission contract is still in its initial loading state, enabled
 * once both queries settle — including settled errors, because the memo
 * records an errored lane as explicitly unavailable.  The action reuses the
 * page's existing Mission G / J query results (no duplicate evidence
 * request) and the same canonical static inputs that render the page, and
 * it must not disturb any existing research section, the non-claim
 * introduction, or the M1 anchors.
 *
 * Render-smoke pattern (renderToStaticMarkup, no jsdom); settled-error
 * states are exercised by seeding the query cache and disabling
 * retryOnMount so no network is touched.  Click-time mechanics (blob,
 * filename, revoke) live in the research-record-memo lib suite via the
 * injected download adapter.
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { EvidenceOverview } from "../evidence-overview";
import { api } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import {
  buildResearchRecordMemo,
  researchRecordMemoInput,
} from "@/lib/research-record-memo";
import { missionJFixture } from "@/components/ui/__tests__/mission-j-fixture";
import { missionGFixture } from "@/components/ui/__tests__/mission-g-fixture";

const ACTION_LABEL = "Download research record (.md)";

function testQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        retryOnMount: false,
        staleTime: Infinity,
        gcTime: Infinity,
      },
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

/** Force a query into a settled-error state without any fetch. */
function seedError(client: QueryClient, queryKey: readonly unknown[]): void {
  const query = client.getQueryCache().build(client, {
    queryKey: queryKey as unknown[],
    queryFn: async () => {
      throw new Error("seeded error");
    },
  });
  query.setState({
    status: "error",
    error: new Error("contract unavailable"),
    fetchStatus: "idle",
    errorUpdateCount: 1,
  });
}

function visible(html: string): string {
  return html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}

/** The rendered export button tag (there must be exactly one). */
function actionTag(html: string): string {
  const tags = html.match(/<button[^>]*>(?:(?!<\/button>).)*?Download research record[\s\S]*?<\/button>/g) ?? [];
  expect(tags, "exactly one export action").toHaveLength(1);
  return tags[0];
}

// Loading baseline: both Mission queries unseeded.
const loadingHtml = renderOverview(testQueryClient());

// Settled success: both contracts seeded.
const seededClient = testQueryClient();
seededClient.setQueryData(qk.missionGEvidence(), missionGFixture());
seededClient.setQueryData(qk.missionJEvidence(), missionJFixture());
const seededHtml = renderOverview(seededClient);

// Settled with one unavailable lane: Mission G ok, Mission J errored.
const degradedClient = testQueryClient();
degradedClient.setQueryData(qk.missionGEvidence(), missionGFixture());
seedError(degradedClient, qk.missionJEvidence());
const degradedHtml = renderOverview(degradedClient);

describe("EvidenceOverview — research-record export action (M2)", () => {
  it("renders exactly one quiet export action with an accessible label", () => {
    for (const html of [loadingHtml, seededHtml, degradedHtml]) {
      const count = html.split(ACTION_LABEL).length - 1;
      expect(count).toBe(1);
    }
    expect(actionTag(seededHtml)).toContain('type="button"');
  });

  // React static markup renders the boolean attribute as disabled="";
  // matching the bare word would collide with the disabled: style variants.
  it("disables the action and explains quietly while a contract is still loading", () => {
    expect(actionTag(loadingHtml)).toContain('disabled=""');
    expect(visible(loadingHtml)).toContain("Preparing tracked evidence…");
  });

  it("enables the action once both contracts settle", () => {
    expect(actionTag(seededHtml)).not.toContain('disabled=""');
    expect(visible(seededHtml)).not.toContain("Preparing tracked evidence…");
  });

  it("enables the action when a contract settled as an error (unavailable lane)", () => {
    expect(actionTag(degradedHtml)).not.toContain('disabled=""');
    expect(visible(degradedHtml)).not.toContain("Preparing tracked evidence…");
    // the page itself shows the honest unavailable state alongside
    expect(visible(degradedHtml)).toContain("Mission J record unavailable");
  });

  it("keeps the non-claim introduction visible next to the action", () => {
    const v = visible(seededHtml);
    expect(v).toContain("Evidence Overview");
    expect(v.toLowerCase()).toContain("not a trading or prediction surface");
  });

  it("introduces no duplicate evidence request", () => {
    const client = testQueryClient();
    client.setQueryData(qk.missionGEvidence(), missionGFixture());
    client.setQueryData(qk.missionJEvidence(), missionJFixture());
    renderOverview(client);
    // exactly the two existing Mission queries — no third evidence fetch
    const keys = client
      .getQueryCache()
      .getAll()
      .map((q) => JSON.stringify(q.queryKey))
      .sort();
    expect(keys).toEqual([
      JSON.stringify(qk.missionGEvidence()),
      JSON.stringify(qk.missionJEvidence()),
    ]);
    expect(
      (api as unknown as Record<string, unknown>).researchRecord,
    ).toBeUndefined();
  });

  it("builds the memo from the same contract payloads the page renders", () => {
    const memo = buildResearchRecordMemo(
      researchRecordMemoInput(
        { isPending: false, isError: false, data: missionGFixture() },
        { isPending: false, isError: false, data: missionJFixture() },
      ),
    );
    // the memo carries the same frozen states the seeded page shows
    expect(seededHtml).toContain("12/12");
    expect(memo).toContain("12/12 frozen cells at state ELEVATED");
    expect(memo).toContain("ORDINARY_UNRESOLVED");
    expect(seededHtml).toContain("ORDINARY / UNRESOLVED");
    expect(memo.toLowerCase()).toContain("unadjudicable");
    expect(visible(seededHtml)).toContain("UNADJUDICABLE");
  });

  it("records an errored lane as unavailable in the exported memo", () => {
    const memo = buildResearchRecordMemo(
      researchRecordMemoInput(
        { isPending: false, isError: false, data: missionGFixture() },
        { isPending: false, isError: true, data: undefined },
      ),
    );
    expect(memo).toContain("Mission J research record: unavailable");
    expect(memo).not.toContain("Mission G research record: unavailable");
  });

  it("changes no existing research section (regression smoke)", () => {
    const v = visible(seededHtml);
    for (const anchor of [
      "Canonical denominators",
      "Mission G historical research record",
      "FOMC robustness & transmission record",
      "Effective independent evidence",
      "Mechanism-family evidence inventory",
      "F1/F2 representative research set",
      "How to read the event-study rows",
      "What this is not",
    ]) {
      expect(v.replace(/&amp;/g, "&"), anchor).toContain(anchor);
    }
    // M1 anchors intact
    for (const id of ["evidence-top", "denominators", "mission-g", "mission-j"]) {
      expect(
        (seededHtml.match(new RegExp(`id="${id}"`, "g")) ?? []).length,
        id,
      ).toBe(1);
    }
  });
});
