/**
 * M3/N2 — reviewer guide disclosure on Evidence Overview.
 *
 * Exactly one compact native <details> disclosure ("How to read and verify
 * this record"), collapsed by default, placed between the page header and
 * the denominator ledger, with exactly two subsections: the five-lane
 * verification path (N2 added the Mission I ordinary-period comparison
 * record between Mission G and Mission J) and the eight-term claim-ceiling
 * glossary.  Pending and unavailable Mission contracts stay visible as
 * honest lane states; reproduction commands render as inert code (no
 * execute control); the M2 export action, M1/N2 anchors, non-claim
 * introduction, and the three existing Mission queries are all unchanged.
 *
 * Render-smoke pattern (renderToStaticMarkup, no jsdom) — note static
 * markup includes <details> children even while collapsed, which is exactly
 * what lets these tests assert the disclosed content.
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { EvidenceOverview } from "../evidence-overview";
import { qk } from "@/lib/queryKeys";
import { EVIDENCE_GLOSSARY } from "@/lib/evidence-reader-guide";
import { missionJFixture } from "@/components/ui/__tests__/mission-j-fixture";
import { missionIFixture } from "@/components/ui/__tests__/mission-i-fixture";
import { missionGFixture } from "@/components/ui/__tests__/mission-g-fixture";

const SUMMARY = "How to read and verify this record";

function testQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, retryOnMount: false, staleTime: Infinity, gcTime: Infinity },
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
  return html
    .replace(/<[^>]*>/g, " ")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();
}

function detailsBlock(html: string): string {
  const blocks = html.match(/<details[\s\S]*?<\/details>/g) ?? [];
  expect(blocks, "exactly one disclosure").toHaveLength(1);
  return blocks[0];
}

const loadingHtml = renderOverview(testQueryClient());

const seededClient = testQueryClient();
seededClient.setQueryData(qk.missionGEvidence(), missionGFixture());
seededClient.setQueryData(qk.missionIEvidence(), missionIFixture());
seededClient.setQueryData(qk.missionJEvidence(), missionJFixture());
const seededHtml = renderOverview(seededClient);

const degradedClient = testQueryClient();
degradedClient.setQueryData(qk.missionGEvidence(), missionGFixture());
degradedClient.setQueryData(qk.missionIEvidence(), missionIFixture());
seedError(degradedClient, qk.missionJEvidence());
const degradedHtml = renderOverview(degradedClient);

describe("EvidenceOverview — reviewer guide disclosure (M3)", () => {
  it("renders exactly one disclosure, collapsed by default, with the accessible summary", () => {
    const details = detailsBlock(seededHtml);
    expect(details).not.toMatch(/<details[^>]*\bopen\b/);
    expect(details).toContain(`<summary`);
    expect(visible(details)).toContain(SUMMARY);
    // native disclosure — no route change, no link, no modal trigger
    expect(details).not.toContain("<a ");
    expect(details).not.toContain("href=");
  });

  it("places the disclosure after the header introduction and before the denominator ledger", () => {
    const header = seededHtml.indexOf('id="evidence-top"');
    const details = seededHtml.indexOf("<details");
    const ledger = seededHtml.indexOf('id="denominators"');
    expect(header).toBeGreaterThan(-1);
    expect(details).toBeGreaterThan(header);
    expect(ledger).toBeGreaterThan(details);
  });

  it("contains exactly the two subsections", () => {
    const v = visible(detailsBlock(seededHtml));
    expect(v).toContain("Verification path");
    expect(v).toContain("Terms and claim ceilings");
  });

  it("renders exactly the five verification lanes, Mission I between G and J", () => {
    const v = visible(detailsBlock(seededHtml));
    for (const lane of [
      "Accepted archive and denominator record",
      "Mission G historical record",
      "Mission I ordinary-period comparison record",
      "Mission J robustness and transmission record",
      "Mechanism-family / independence / representative-case static evidence",
    ]) {
      expect(v.split(lane).length - 1, lane).toBe(1);
    }
    const g = v.indexOf("Mission G historical record");
    const i = v.indexOf("Mission I ordinary-period comparison record");
    const j = v.indexOf("Mission J robustness and transmission record");
    expect(i).toBeGreaterThan(g);
    expect(j).toBeGreaterThan(i);
  });

  it("sources the Mission I lane from its payload with honest null provenance (N2)", () => {
    const v = visible(detailsBlock(seededHtml));
    expect(v).toContain("stats/I0_ORDINARY_PERIOD_BASELINE_PROTOCOL.md");
    expect(v).toContain("stats/MISSION_I_CLOSEOUT.md");
    expect(v).toContain("python -m scripts.i2a_response_substrate --emit");
    expect(v).toContain("Computation dates");
    expect(v).toContain("Execution commits");
    expect(v).toContain("percentile-of-placements only");
  });

  it("renders exactly the eight glossary terms with sources", () => {
    const details = detailsBlock(seededHtml);
    const v = visible(details);
    for (const e of EVIDENCE_GLOSSARY) {
      expect(v, e.term).toContain(e.term);
      expect(v, `${e.term} boundary`).toContain(e.boundary.slice(0, 40));
    }
    expect(EVIDENCE_GLOSSARY).toHaveLength(8);
    expect(v).toContain("stats/J0_FOMC_ROBUSTNESS_CONSTITUTION.md");
  });

  it("keeps pending lanes visible while contracts load", () => {
    const v = visible(detailsBlock(loadingHtml));
    expect(v).toContain("Mission G historical record");
    expect(v).toContain("Mission I ordinary-period comparison record");
    expect(v).toContain("Mission J robustness and transmission record");
    expect(v).toContain("preparing tracked record");
    // static lanes stay complete
    expect(v).toContain("Accepted archive and denominator record");
    expect(v).toContain("stats/EFFECTIVE_INDEPENDENT_EVIDENCE.md");
  });

  it("keeps an unavailable lane visible as record unavailable", () => {
    const v = visible(detailsBlock(degradedHtml));
    expect(v).toContain("record unavailable");
    expect(v).toContain("Mission J robustness and transmission record");
    // Mission G still fully sourced from its payload
    expect(v).toContain("G6_FROZEN_MANIFEST_READOUT.md");
  });

  it("renders honest not-recorded fields", () => {
    expect(visible(detailsBlock(seededHtml))).toContain("not recorded");
  });

  it("renders reproduction commands as inert code with no execute control", () => {
    const details = detailsBlock(seededHtml);
    expect(details).toContain("<code");
    expect(details).toContain("python scripts/effective_independent_evidence_report.py");
    expect(details).not.toContain("<button");
    expect(details).not.toContain("onClick");
    expect(details).not.toContain("<input");
    expect(visible(details)).not.toMatch(/\b(run|execute) command\b/i);
  });

  it("adds no duplicate Mission G/I/J request", () => {
    const client = testQueryClient();
    client.setQueryData(qk.missionGEvidence(), missionGFixture());
    client.setQueryData(qk.missionIEvidence(), missionIFixture());
    client.setQueryData(qk.missionJEvidence(), missionJFixture());
    renderOverview(client);
    const keys = client
      .getQueryCache()
      .getAll()
      .map((q) => JSON.stringify(q.queryKey))
      .sort();
    expect(keys).toEqual([
      JSON.stringify(qk.missionGEvidence()),
      JSON.stringify(qk.missionIEvidence()),
      JSON.stringify(qk.missionJEvidence()),
    ]);
  });

  it("keeps the M2 export action exactly once and the M1/N2 anchors exactly once", () => {
    for (const html of [loadingHtml, seededHtml, degradedHtml]) {
      expect(html.split("Download research record (.md)").length - 1).toBe(1);
      for (const id of ["evidence-top", "denominators", "mission-g", "mission-i", "mission-j"]) {
        expect((html.match(new RegExp(`id="${id}"`, "g")) ?? []).length, id).toBe(1);
      }
    }
  });

  it("keeps the page non-claim introduction visible", () => {
    const v = visible(seededHtml).toLowerCase();
    expect(v).toContain("not a trading or prediction surface");
  });

  it("keeps every existing research section rendering (regression smoke)", () => {
    const v = visible(seededHtml).replace(/&amp;/g, "&");
    for (const section of [
      "Canonical denominators",
      "Mission G historical research record",
      "FOMC robustness & transmission record",
      "Effective independent evidence",
      "Mechanism-family evidence inventory",
      "F1/F2 representative research set",
      "How to read the event-study rows",
      "What this is not",
    ]) {
      expect(v, section).toContain(section);
    }
  });
});
