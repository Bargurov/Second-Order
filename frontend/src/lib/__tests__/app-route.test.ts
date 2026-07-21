/**
 * M1 — addressable Evidence record: pure route/history helpers.
 *
 * The app keeps its lightweight state-based navigation (no React Router);
 * `lib/app-route.ts` is the single seam deciding which Page a pathname maps
 * to, which history action an in-app transition needs, and how a popstate
 * restores state. Only Evidence is independently addressable (`/evidence`);
 * every other page stays a state-driven surface at `/`, and `/share/:id`
 * stays the shell-free SharePage path selected in main.tsx.
 *
 * Pure helpers, node-environment tests (no jsdom, matching the project
 * pattern); browser globals are injected as minimal fakes.
 */
import { describe, it, expect, vi } from "vitest";

import {
  EVIDENCE_PATH,
  matchSharePath,
  isPage,
  resolveInitialRoute,
  resolvePopstate,
  planNavigation,
  applyHistoryAction,
  installPopstateListener,
} from "../app-route";
import type { Page } from "@/components/layout/sidebar";

// ---------------------------------------------------------------------------
// Share path — the pre-existing shell-free route must keep matching exactly
// what main.tsx matched before M1 (regex ^/share/(\d+)/?$).
// ---------------------------------------------------------------------------

describe("matchSharePath — shell-free SharePage selection", () => {
  it("matches /share/:eventId with and without a trailing slash", () => {
    expect(matchSharePath("/share/123")).toBe(123);
    expect(matchSharePath("/share/123/")).toBe(123);
    expect(matchSharePath("/share/7")).toBe(7);
  });

  it("does not match full-shell or malformed paths", () => {
    expect(matchSharePath("/")).toBeNull();
    expect(matchSharePath("/evidence")).toBeNull();
    expect(matchSharePath("/share/")).toBeNull();
    expect(matchSharePath("/share/abc")).toBeNull();
    expect(matchSharePath("/share/123/extra")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Page validation — history state is external input; never cast it blindly.
// ---------------------------------------------------------------------------

describe("isPage — canonical Page universe validation", () => {
  it("accepts every canonical Page id", () => {
    const all: Page[] = [
      "overview", "market", "headlines", "analyze", "events",
      "backtest", "cases", "evidence", "portfolio", "brief", "demo",
    ];
    for (const p of all) expect(isPage(p), p).toBe(true);
  });

  it("rejects everything else", () => {
    for (const bad of ["nope", "", "Market", null, undefined, 42, {}, ["market"]]) {
      expect(isPage(bad), String(bad)).toBe(false);
    }
  });
});

// ---------------------------------------------------------------------------
// Initial route resolution — the mount contract.
// ---------------------------------------------------------------------------

describe("resolveInitialRoute — full-shell mount", () => {
  it("resolves / to Market at canonical /", () => {
    expect(resolveInitialRoute("/")).toEqual({ page: "market", canonicalUrl: "/" });
  });

  it("resolves /evidence to Evidence", () => {
    expect(resolveInitialRoute("/evidence")).toEqual({
      page: "evidence",
      canonicalUrl: "/evidence",
    });
    expect(EVIDENCE_PATH).toBe("/evidence");
  });

  it("normalizes /evidence/ to canonical /evidence", () => {
    expect(resolveInitialRoute("/evidence/")).toEqual({
      page: "evidence",
      canonicalUrl: "/evidence",
    });
  });

  it("preserves a hash fragment on /evidence", () => {
    expect(resolveInitialRoute("/evidence", "#mission-j")).toEqual({
      page: "evidence",
      canonicalUrl: "/evidence#mission-j",
    });
    expect(resolveInitialRoute("/evidence/", "#mission-g")).toEqual({
      page: "evidence",
      canonicalUrl: "/evidence#mission-g",
    });
  });

  it("fails an unknown full-shell path safely to Market at /", () => {
    for (const p of ["/portfolio", "/foo", "/foo/bar", "/EVIDENCE", "/evidence/extra"]) {
      expect(resolveInitialRoute(p), p).toEqual({ page: "market", canonicalUrl: "/" });
    }
  });

  it("drops hash fragments on non-evidence paths", () => {
    expect(resolveInitialRoute("/", "#anything")).toEqual({
      page: "market",
      canonicalUrl: "/",
    });
    expect(resolveInitialRoute("/unknown", "#mission-j")).toEqual({
      page: "market",
      canonicalUrl: "/",
    });
  });
});

// ---------------------------------------------------------------------------
// popstate resolution — path wins for /evidence; state may restore a valid
// Page at /; anything invalid fails to Market. Never writes history.
// ---------------------------------------------------------------------------

describe("resolvePopstate — Back/Forward destination", () => {
  it("always resolves /evidence to Evidence, regardless of state", () => {
    expect(resolvePopstate("/evidence", null)).toBe("evidence");
    expect(resolvePopstate("/evidence", { page: "portfolio" })).toBe("evidence");
    expect(resolvePopstate("/evidence/", undefined)).toBe("evidence");
  });

  it("restores a valid non-evidence Page from state at /", () => {
    expect(resolvePopstate("/", { page: "portfolio" })).toBe("portfolio");
    expect(resolvePopstate("/", { page: "market" })).toBe("market");
    expect(resolvePopstate("/", { page: "demo" })).toBe("demo");
  });

  it("fails missing or invalid state to Market", () => {
    expect(resolvePopstate("/", null)).toBe("market");
    expect(resolvePopstate("/", undefined)).toBe("market");
    expect(resolvePopstate("/", {})).toBe("market");
    expect(resolvePopstate("/", { page: "bogus" })).toBe("market");
    expect(resolvePopstate("/", { page: 7 })).toBe("market");
    expect(resolvePopstate("/", "portfolio")).toBe("market");
  });

  it("never resolves evidence-in-state at a non-evidence path (URL/page sync)", () => {
    expect(resolvePopstate("/", { page: "evidence" })).toBe("market");
  });

  it("fails an unknown path to Market even with a valid state", () => {
    expect(resolvePopstate("/unknown", { page: "portfolio" })).toBe("market");
  });
});

// ---------------------------------------------------------------------------
// Navigation planning — push only for the Evidence boundary; replace among
// non-Evidence pages; nothing on a same-page click.
// ---------------------------------------------------------------------------

describe("planNavigation — in-app transitions", () => {
  it("pushes exactly one /evidence entry when entering Evidence", () => {
    expect(planNavigation("market", "evidence")).toEqual({
      kind: "push",
      url: "/evidence",
      page: "evidence",
    });
    expect(planNavigation("portfolio", "evidence")).toEqual({
      kind: "push",
      url: "/evidence",
      page: "evidence",
    });
  });

  it("does not push when Evidence is already active", () => {
    expect(planNavigation("evidence", "evidence")).toEqual({ kind: "none" });
  });

  it("pushes / carrying the destination Page when leaving Evidence", () => {
    expect(planNavigation("evidence", "portfolio")).toEqual({
      kind: "push",
      url: "/",
      page: "portfolio",
    });
    expect(planNavigation("evidence", "market")).toEqual({
      kind: "push",
      url: "/",
      page: "market",
    });
  });

  it("replaces (never pushes) among non-Evidence pages", () => {
    expect(planNavigation("market", "portfolio")).toEqual({
      kind: "replace",
      url: "/",
      page: "portfolio",
    });
    expect(planNavigation("headlines", "analyze")).toEqual({
      kind: "replace",
      url: "/",
      page: "analyze",
    });
  });

  it("does nothing on a same-page click", () => {
    expect(planNavigation("portfolio", "portfolio")).toEqual({ kind: "none" });
    expect(planNavigation("market", "market")).toEqual({ kind: "none" });
  });
});

describe("applyHistoryAction — bounded history writes", () => {
  const fakeHistory = () => ({ pushState: vi.fn(), replaceState: vi.fn() });

  it("push calls pushState once with { page } state and the url", () => {
    const h = fakeHistory();
    applyHistoryAction(h, { kind: "push", url: "/evidence", page: "evidence" });
    expect(h.pushState).toHaveBeenCalledTimes(1);
    expect(h.pushState).toHaveBeenCalledWith({ page: "evidence" }, "", "/evidence");
    expect(h.replaceState).not.toHaveBeenCalled();
  });

  it("replace calls replaceState once with { page } state and the url", () => {
    const h = fakeHistory();
    applyHistoryAction(h, { kind: "replace", url: "/", page: "portfolio" });
    expect(h.replaceState).toHaveBeenCalledTimes(1);
    expect(h.replaceState).toHaveBeenCalledWith({ page: "portfolio" }, "", "/");
    expect(h.pushState).not.toHaveBeenCalled();
  });

  it("none writes nothing", () => {
    const h = fakeHistory();
    applyHistoryAction(h, { kind: "none" });
    expect(h.pushState).not.toHaveBeenCalled();
    expect(h.replaceState).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// popstate listener installation — StrictMode-safe setup/cleanup.
// ---------------------------------------------------------------------------

type PopHandler = (ev: { state: unknown }) => void;

function fakePopstateWindow(pathname = "/") {
  const handlers: PopHandler[] = [];
  return {
    location: { pathname },
    addEventListener(_type: "popstate", fn: PopHandler) {
      handlers.push(fn);
    },
    removeEventListener(_type: "popstate", fn: PopHandler) {
      const i = handlers.indexOf(fn);
      if (i !== -1) handlers.splice(i, 1);
    },
    handlers,
    dispatch(state: unknown) {
      for (const fn of [...handlers]) fn({ state });
    },
  };
}

describe("installPopstateListener — StrictMode-safe listener lifecycle", () => {
  it("installs one popstate listener and resolves dispatches through the route seam", () => {
    const win = fakePopstateWindow("/");
    const seen: Page[] = [];
    installPopstateListener(win, (p) => seen.push(p));
    expect(win.handlers).toHaveLength(1);
    win.dispatch({ page: "portfolio" });
    expect(seen).toEqual(["portfolio"]);
  });

  it("cleanup removes exactly the installed listener", () => {
    const win = fakePopstateWindow("/");
    const cleanup = installPopstateListener(win, () => {});
    cleanup();
    expect(win.handlers).toHaveLength(0);
  });

  it("a StrictMode setup → cleanup → setup cycle leaves exactly one listener", () => {
    const win = fakePopstateWindow("/");
    const seen: Page[] = [];
    const cleanup1 = installPopstateListener(win, (p) => seen.push(p));
    cleanup1();
    installPopstateListener(win, (p) => seen.push(p));
    expect(win.handlers).toHaveLength(1);
    win.dispatch({ page: "portfolio" });
    expect(seen).toEqual(["portfolio"]);
  });

  it("resolves by the window's current pathname (evidence wins over state)", () => {
    const win = fakePopstateWindow("/evidence");
    const seen: Page[] = [];
    installPopstateListener(win, (p) => seen.push(p));
    win.dispatch({ page: "portfolio" });
    expect(seen).toEqual(["evidence"]);
  });
});
