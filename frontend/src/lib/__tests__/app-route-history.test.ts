/**
 * M1 — addressable Evidence record: history-contract integration.
 *
 * Drives the pure app-route helpers against a faithful fake browser history
 * (entry stack + popstate dispatch) the way App.tsx composes them: resolve
 * the initial route, seed the current entry's { page } state, install the
 * popstate listener, and route every in-app transition through
 * planNavigation/applyHistoryAction. This is the required
 * Portfolio ↔ Evidence Back/Forward contract without jsdom.
 */
import { describe, it, expect } from "vitest";

import {
  resolveInitialRoute,
  planNavigation,
  applyHistoryAction,
  installPopstateListener,
} from "../app-route";
import type { Page } from "@/components/layout/sidebar";

// ---------------------------------------------------------------------------
// Fake browser — entry stack, pushState/replaceState, back/forward + popstate.
// ---------------------------------------------------------------------------

type Entry = { state: unknown; url: string };
type PopHandler = (ev: { state: unknown }) => void;

class FakeBrowser {
  entries: Entry[];
  index = 0;
  handlers: PopHandler[] = [];
  writesDuringDispatch = 0;
  private dispatching = false;

  constructor(url: string, state: unknown = null) {
    this.entries = [{ state, url }];
  }

  get current(): Entry {
    return this.entries[this.index]!;
  }

  get location() {
    const url = this.current.url;
    const hashIdx = url.indexOf("#");
    return {
      pathname: hashIdx === -1 ? url : url.slice(0, hashIdx),
      hash: hashIdx === -1 ? "" : url.slice(hashIdx),
    };
  }

  history = {
    pushState: (state: unknown, _unused: string, url: string): void => {
      if (this.dispatching) this.writesDuringDispatch++;
      this.entries.splice(this.index + 1);
      this.entries.push({ state, url });
      this.index++;
    },
    replaceState: (state: unknown, _unused: string, url: string): void => {
      if (this.dispatching) this.writesDuringDispatch++;
      this.entries[this.index] = { state, url };
    },
  };

  addEventListener(_type: "popstate", fn: PopHandler): void {
    this.handlers.push(fn);
  }

  removeEventListener(_type: "popstate", fn: PopHandler): void {
    const i = this.handlers.indexOf(fn);
    if (i !== -1) this.handlers.splice(i, 1);
  }

  private dispatchPop(): void {
    this.dispatching = true;
    try {
      for (const fn of [...this.handlers]) fn({ state: this.current.state });
    } finally {
      this.dispatching = false;
    }
  }

  back(): void {
    if (this.index > 0) {
      this.index--;
      this.dispatchPop();
    }
  }

  forward(): void {
    if (this.index < this.entries.length - 1) {
      this.index++;
      this.dispatchPop();
    }
  }
}

// ---------------------------------------------------------------------------
// Minimal App harness — composes the helpers exactly like App.tsx.
// ---------------------------------------------------------------------------

function mountApp(browser: FakeBrowser) {
  let page: Page = resolveInitialRoute(browser.location.pathname).page;
  const route = resolveInitialRoute(browser.location.pathname, browser.location.hash);
  browser.history.replaceState({ page: route.page }, "", route.canonicalUrl);
  const cleanup = installPopstateListener(browser, (p) => {
    page = p;
  });
  return {
    get page() {
      return page;
    },
    navigate(target: Page) {
      applyHistoryAction(browser.history, planNavigation(page, target));
      page = target;
    },
    cleanup,
  };
}

// ---------------------------------------------------------------------------
// Mount contract
// ---------------------------------------------------------------------------

describe("mount — initial route + entry-state seeding", () => {
  it("/ mounts on Market and seeds { page: market } without new entries", () => {
    const b = new FakeBrowser("/");
    const app = mountApp(b);
    expect(app.page).toBe("market");
    expect(b.entries).toHaveLength(1);
    expect(b.current).toEqual({ state: { page: "market" }, url: "/" });
  });

  it("/evidence mounts on Evidence (direct entry) and a remount (refresh) stays on Evidence", () => {
    const b = new FakeBrowser("/evidence");
    const app = mountApp(b);
    expect(app.page).toBe("evidence");
    expect(b.current).toEqual({ state: { page: "evidence" }, url: "/evidence" });

    app.cleanup();
    const refreshed = mountApp(b); // refresh re-resolves from the same entry
    expect(refreshed.page).toBe("evidence");
    expect(b.entries).toHaveLength(1);
    expect(b.current.url).toBe("/evidence");
  });

  it("/evidence/ normalizes in place to /evidence", () => {
    const b = new FakeBrowser("/evidence/");
    const app = mountApp(b);
    expect(app.page).toBe("evidence");
    expect(b.entries).toHaveLength(1);
    expect(b.current.url).toBe("/evidence");
  });

  it("/evidence#mission-j mounts on Evidence and keeps the hash", () => {
    const b = new FakeBrowser("/evidence#mission-j");
    const app = mountApp(b);
    expect(app.page).toBe("evidence");
    expect(b.current.url).toBe("/evidence#mission-j");
  });

  it("an unknown path fails safely to Market and normalizes to /", () => {
    const b = new FakeBrowser("/no-such-page");
    const app = mountApp(b);
    expect(app.page).toBe("market");
    expect(b.entries).toHaveLength(1);
    expect(b.current).toEqual({ state: { page: "market" }, url: "/" });
  });

  it("a refreshed / ignores stale history state — fresh root load remains Market", () => {
    const b = new FakeBrowser("/", { page: "portfolio" });
    const app = mountApp(b);
    expect(app.page).toBe("market");
    expect(b.current).toEqual({ state: { page: "market" }, url: "/" });
  });
});

// ---------------------------------------------------------------------------
// In-app navigation — push/replace discipline
// ---------------------------------------------------------------------------

describe("in-app navigation — history entry discipline", () => {
  it("non-Evidence tab clicks replace in place: no entry per click", () => {
    const b = new FakeBrowser("/");
    const app = mountApp(b);
    app.navigate("portfolio");
    app.navigate("headlines");
    app.navigate("cases");
    expect(b.entries).toHaveLength(1);
    expect(b.current).toEqual({ state: { page: "cases" }, url: "/" });
  });

  it("entering Evidence pushes exactly one /evidence entry", () => {
    const b = new FakeBrowser("/");
    const app = mountApp(b);
    app.navigate("portfolio");
    app.navigate("evidence");
    expect(app.page).toBe("evidence");
    expect(b.entries).toHaveLength(2);
    expect(b.current).toEqual({ state: { page: "evidence" }, url: "/evidence" });
  });

  it("re-clicking Evidence while active adds no entry", () => {
    const b = new FakeBrowser("/");
    const app = mountApp(b);
    app.navigate("evidence");
    app.navigate("evidence");
    expect(b.entries).toHaveLength(2);
  });

  it("leaving Evidence pushes / carrying the destination page in state", () => {
    const b = new FakeBrowser("/");
    const app = mountApp(b);
    app.navigate("evidence");
    app.navigate("market");
    expect(app.page).toBe("market");
    expect(b.entries).toHaveLength(3);
    expect(b.current).toEqual({ state: { page: "market" }, url: "/" });
  });
});

// ---------------------------------------------------------------------------
// Browser Back / Forward — the required scenario
// ---------------------------------------------------------------------------

describe("browser Back/Forward", () => {
  it("Portfolio at / → Evidence → Back → Portfolio → Forward → Evidence", () => {
    const b = new FakeBrowser("/");
    const app = mountApp(b);
    app.navigate("portfolio");
    expect(app.page).toBe("portfolio");

    app.navigate("evidence");
    expect(b.location.pathname).toBe("/evidence");

    b.back();
    expect(app.page).toBe("portfolio");
    expect(b.location.pathname).toBe("/");

    b.forward();
    expect(app.page).toBe("evidence");
    expect(b.location.pathname).toBe("/evidence");
  });

  it("Evidence → Market, then Back returns to Evidence", () => {
    const b = new FakeBrowser("/evidence");
    const app = mountApp(b);
    app.navigate("market");
    expect(app.page).toBe("market");

    b.back();
    expect(app.page).toBe("evidence");
    expect(b.location.pathname).toBe("/evidence");
  });

  it("popstate handling never writes history", () => {
    const b = new FakeBrowser("/");
    const app = mountApp(b);
    app.navigate("portfolio");
    app.navigate("evidence");
    b.back();
    b.forward();
    b.back();
    expect(b.writesDuringDispatch).toBe(0);
    expect(app.page).toBe("portfolio");
  });

  it("a StrictMode setup → cleanup → setup cycle keeps one live listener", () => {
    const b = new FakeBrowser("/");
    const first = mountApp(b);
    first.cleanup();
    const app = mountApp(b);
    expect(b.handlers).toHaveLength(1);

    app.navigate("portfolio");
    app.navigate("evidence");
    b.back();
    expect(app.page).toBe("portfolio");
    // the stale first mount saw no popstate — its listener is gone
    expect(first.page).toBe("market");
  });
});
