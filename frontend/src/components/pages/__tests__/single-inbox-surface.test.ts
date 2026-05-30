/**
 * single-inbox-surface.test.ts
 *
 * Structural invariants proving that exactly one headlines/inbox surface is
 * active and no stale duplicate implementation exists in the codebase.
 *
 * Uses filesystem reads instead of React rendering — these tests verify
 * source structure, not runtime behavior, so they run instantly with no
 * DOM or network dependencies.
 *
 * Three invariant groups:
 *  1) Only one maintained inbox surface is mounted
 *  2) Route behavior stays the same (sidebar + bottom-nav + App router)
 *  3) No stale alternate path remains in active use
 */

import { describe, it, expect } from "vitest";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const PAGES_DIR = resolve(__dirname, "..");
const LAYOUT_DIR = resolve(__dirname, "../../layout");
const APP_FILE   = resolve(__dirname, "../../../App.tsx");

// ---------------------------------------------------------------------------
// 1) Only one maintained inbox surface is mounted
// ---------------------------------------------------------------------------

describe("single inbox surface", () => {
  it("headlines-page.tsx still exists as a shared-helper module", () => {
    expect(existsSync(resolve(PAGES_DIR, "headlines-page.tsx"))).toBe(true);
  });

  it("news-inbox.tsx has been deleted", () => {
    expect(existsSync(resolve(PAGES_DIR, "news-inbox.tsx"))).toBe(false);
  });

  it("no tsx file in components/pages exports NewsInbox", () => {
    const files = readdirSync(PAGES_DIR).filter(
      (f) => f.endsWith(".tsx") || f.endsWith(".ts"),
    );
    for (const file of files) {
      const content = readFileSync(resolve(PAGES_DIR, file), "utf-8");
      expect(content).not.toContain("export function NewsInbox");
      expect(content).not.toContain("export class NewsInbox");
      expect(content).not.toContain("export default NewsInbox");
    }
  });

  it("HeadlinesPage is exported from headlines-page.tsx", () => {
    const content = readFileSync(resolve(PAGES_DIR, "headlines-page.tsx"), "utf-8");
    expect(content).toMatch(/export\s+function\s+HeadlinesPage/);
  });
});

// ---------------------------------------------------------------------------
// 2) Route behavior stays the same
// ---------------------------------------------------------------------------

describe("route behavior", () => {
  it("App.tsx mounts InboxWorkbench (not HeadlinesPage) for the headlines route", () => {
    const app = readFileSync(APP_FILE, "utf-8");
    // InboxWorkbench replaced HeadlinesPage as the mounted headlines surface
    // (commit ab6e0fc).  It is imported and rendered for page === "headlines".
    expect(app).toContain("InboxWorkbench");
    expect(app).toContain('page === "headlines"');
    // The headlines conditional wraps InboxWorkbench.
    expect(app).toMatch(/page === "headlines"[\s\S]{0,120}InboxWorkbench/);
    // HeadlinesPage is no longer mounted by App.tsx for this (or any) route.
    expect(app).not.toContain("<HeadlinesPage");
    expect(app).not.toMatch(/page === "headlines"[\s\S]{0,120}HeadlinesPage/);
  });

  it("App.tsx has exactly one conditional branch for the headlines route", () => {
    const app = readFileSync(APP_FILE, "utf-8");
    const branches = app.match(/page === "headlines"/g) ?? [];
    expect(branches).toHaveLength(1);
  });

  it('sidebar defines "headlines" as a valid Page', () => {
    const sidebar = readFileSync(resolve(LAYOUT_DIR, "sidebar.tsx"), "utf-8");
    // Page union type includes "headlines"
    expect(sidebar).toContain('"headlines"');
  });

  it('bottom-nav includes the "headlines" tab', () => {
    const bottomNav = readFileSync(resolve(LAYOUT_DIR, "bottom-nav.tsx"), "utf-8");
    expect(bottomNav).toContain('"headlines"');
  });

  it("sidebar and App.tsx agree on the full page set", () => {
    const sidebar = readFileSync(resolve(LAYOUT_DIR, "sidebar.tsx"), "utf-8");
    const app     = readFileSync(APP_FILE, "utf-8");
    // Every active route must appear in both files.  Note: ``overview``
    // is retained in App.tsx as a back-compat alias for the
    // MarketOverview surface but no longer surfaces in the sidebar nav;
    // the new explicit Market Context route is ``market``.
    const routes = ["portfolio", "market", "headlines", "analyze", "events", "backtest"];
    for (const route of routes) {
      expect(sidebar).toContain(`"${route}"`);
      expect(app).toContain(`"${route}"`);
    }
  });

  it("App.tsx defaults to the market workspace landing", () => {
    // Intentional contract: the default home page is Market Context.
    // Documented in App.tsx ("Default home page is Market Context") and
    // sidebar.tsx ("Workspace leads with Market context (the new default
    // landing)").  ``overview`` remains a back-compat alias that resolves
    // to the same surface; the literal default state is ``"market"``.
    const app = readFileSync(APP_FILE, "utf-8");
    expect(app).toMatch(/useState<Page>\("market"\)/);
  });

  it("App.tsx routes the back-compat overview alias to MarketOverview", () => {
    const app = readFileSync(APP_FILE, "utf-8");
    // Both ``market`` and ``overview`` resolve to the same page so older
    // setPage("overview") callers keep working.
    expect(app).toContain('page === "market"');
    expect(app).toContain('page === "overview"');
  });
});

// ---------------------------------------------------------------------------
// 3) No stale alternate path in active use
// ---------------------------------------------------------------------------

describe("no stale alternate path", () => {
  it("App.tsx does not import or reference NewsInbox", () => {
    const app = readFileSync(APP_FILE, "utf-8");
    expect(app).not.toContain("NewsInbox");
    expect(app).not.toContain("news-inbox");
  });

  it("no file in the project src imports from news-inbox", () => {
    // Walk the src tree looking for any import of the deleted module.
    function walk(dir: string): string[] {
      const entries = readdirSync(dir, { withFileTypes: true });
      const files: string[] = [];
      for (const e of entries) {
        const full = resolve(dir, e.name);
        if (e.isDirectory() && e.name !== "node_modules" && e.name !== "__tests__") {
          files.push(...walk(full));
        } else if (e.name.endsWith(".ts") || e.name.endsWith(".tsx")) {
          files.push(full);
        }
      }
      return files;
    }
    const SRC_DIR = resolve(__dirname, "../../../");
    const allSrc = walk(SRC_DIR);
    for (const file of allSrc) {
      const content = readFileSync(file, "utf-8");
      const rel = file.replace(SRC_DIR, "");
      expect(content, `${rel} still imports news-inbox`).not.toContain("news-inbox");
      expect(content, `${rel} still references NewsInbox`).not.toContain("NewsInbox");
    }
  });

  it("only the allowed headlines/inbox page components exist in pages/", () => {
    const files = readdirSync(PAGES_DIR).filter((f) => f.endsWith(".tsx"));
    const headlineFiles = files.filter((f) =>
      f.toLowerCase().includes("headline") ||
      f.toLowerCase().includes("inbox") ||
      f.toLowerCase().includes("feed"),
    ).sort();
    // InboxWorkbench is the mounted headlines surface; headlines-page.tsx
    // remains as a shared-helper module (and the now-unmounted HeadlinesPage
    // component).  No other headlines / inbox / feed surface may exist.
    expect(headlineFiles).toEqual(["headlines-page.tsx", "inbox-workbench.tsx"]);
  });
});
