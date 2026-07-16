/**
 * M1 — App/main navigation-contract reconciliation.
 *
 * App.tsx owns page state and main.tsx owns shell selection; neither renders
 * under the project's no-jsdom test pattern, so this test reconciles their
 * source against the M1 route contract the way tests/test_nav_label_consistency.py
 * reconciles the nav chrome:
 *
 *  - every programmatic page transition (headline → Analyze, Case Library →
 *    Archive detail, Analyze Back → Market, cold-clone Evidence pointer) goes
 *    through the central navigate() seam — no direct setPage("...") literal
 *    can silently desynchronize the URL/history contract;
 *  - App composes the tested app-route helpers instead of duplicating route
 *    conditionals;
 *  - main.tsx still selects the shell-free SharePage through the same shared
 *    matchSharePath seam, before the full App shell;
 *  - the literals pinned by the backend nav contract stay intact.
 */
import { describe, it, expect } from "vitest";

// Vite ?raw imports — source text, not modules.
import appSource from "../App.tsx?raw";
import mainSource from "../main.tsx?raw";

describe("App.tsx — central navigation contract", () => {
  it("routes no page transition through a direct setPage(\"...\") literal", () => {
    const direct = appSource.match(/setPage\("[a-z]+"\)/g) ?? [];
    expect(direct, `direct setPage literals bypass the history contract: ${direct.join(", ")}`)
      .toEqual([]);
  });

  it("routes the programmatic transitions through navigate()", () => {
    // headline → Analyze
    expect(appSource).toContain('navigate("analyze")');
    // Case Library → Archive detail
    expect(appSource).toContain('navigate("events")');
    // Analyze Back → Market
    expect(appSource).toContain('navigate("market")');
  });

  it("wires the cold-clone Evidence pointer through navigate(\"evidence\")", () => {
    expect(appSource).toMatch(/onOpenEvidence=\{\(\) => navigate\("evidence"\)\}/);
  });

  it("derives the initial Page and popstate destinations from the tested route seam", () => {
    expect(appSource).toContain('from "@/lib/app-route"');
    expect(appSource).toContain("resolveInitialRoute");
    expect(appSource).toContain("installPopstateListener");
    expect(appSource).toContain("planNavigation");
  });

  it("keeps the literals pinned by tests/test_nav_label_consistency.py", () => {
    expect(appSource).toContain('(page === "market" || page === "overview")');
    expect(appSource).toContain('page === "demo"');
  });
});

describe("main.tsx — shell selection stays share-first and seam-driven", () => {
  it("selects the shell-free SharePage through the shared matchSharePath seam", () => {
    expect(mainSource).toContain("matchSharePath(window.location.pathname)");
    expect(mainSource).toContain("SharePage");
  });

  it("checks the share path before rendering the full App shell", () => {
    const shareIdx = mainSource.indexOf("SharePage eventId");
    const appIdx = mainSource.indexOf("<App />");
    expect(shareIdx).toBeGreaterThan(-1);
    expect(appIdx).toBeGreaterThan(shareIdx);
  });

  it("adds no route conditionals duplicated from the route seam", () => {
    // the /evidence decision lives in app-route.ts, not in main.tsx
    expect(mainSource).not.toContain('"/evidence"');
  });
});
