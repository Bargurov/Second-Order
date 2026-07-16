/**
 * app-route.ts — the single route/history seam for the state-based shell (M1).
 *
 * The app deliberately has no general router. Exactly one page is
 * independently addressable — the published Evidence Overview at
 * ``/evidence`` — while every other page remains a state-driven surface at
 * ``/`` whose identity travels in ``history.state.page``, and
 * ``/share/:eventId`` remains the shell-free SharePage selected in main.tsx.
 *
 * All route decisions live here as pure functions so main.tsx and App.tsx
 * compose tested helpers instead of duplicating conditionals:
 *
 *  - mount:    resolveInitialRoute() → initial Page + canonical URL to seed
 *              via ``history.replaceState({ page }, "", canonicalUrl)``;
 *  - navigate: planNavigation() → one bounded history action
 *              (push only across the Evidence boundary, replace among
 *              non-Evidence pages, nothing on a same-page click), applied by
 *              applyHistoryAction();
 *  - popstate: installPopstateListener() → resolvePopstate() — reads
 *              history, never writes it; StrictMode-safe cleanup.
 *
 * History state is external input: it is validated against the canonical
 * Page universe (isPage) and never cast blindly.
 */
import type { Page } from "@/components/layout/sidebar";

/** Canonical public path of the one addressable page. */
export const EVIDENCE_PATH = "/evidence";

/** Canonical path of every state-driven page. */
export const ROOT_PATH = "/";

// The canonical Page universe (mirrors the sidebar's Page union; the
// exhaustiveness check below fails typecheck if the union gains a member
// this list misses).
const PAGE_IDS = [
  "overview",
  "market",
  "headlines",
  "analyze",
  "events",
  "backtest",
  "cases",
  "evidence",
  "portfolio",
  "demo",
] as const satisfies readonly Page[];

type PageIdsCoverPage = Page extends (typeof PAGE_IDS)[number] ? true : never;
const _pageIdsCoverPage: PageIdsCoverPage = true;
void _pageIdsCoverPage;

/** Validate untrusted input (history state) against the Page universe. */
export function isPage(value: unknown): value is Page {
  return (
    typeof value === "string" && (PAGE_IDS as readonly string[]).includes(value)
  );
}

/**
 * Shell-free share route — the exact pre-M1 main.tsx regex, kept here so
 * shell selection and full-shell routing share one seam. Returns the event
 * id, or null when the path is not a share path.
 */
export function matchSharePath(pathname: string): number | null {
  const m = /^\/share\/(\d+)\/?$/.exec(pathname);
  return m ? parseInt(m[1] ?? "0", 10) : null;
}

function isEvidencePath(pathname: string): boolean {
  return pathname === EVIDENCE_PATH || pathname === `${EVIDENCE_PATH}/`;
}

export interface AppRoute {
  page: Page;
  /** Normalized URL for the current history entry (keeps a hash only on
   *  the addressable Evidence route). */
  canonicalUrl: string;
}

/**
 * Resolve a full-shell mount: ``/evidence`` (with optional trailing slash
 * and hash) → Evidence; ``/`` → Market; any unknown path fails safely to
 * Market and normalizes to ``/``. Fresh loads never trust prior history
 * state — a refreshed root is always Market.
 */
export function resolveInitialRoute(pathname: string, hash = ""): AppRoute {
  if (isEvidencePath(pathname)) {
    return { page: "evidence", canonicalUrl: `${EVIDENCE_PATH}${hash}` };
  }
  return { page: "market", canonicalUrl: ROOT_PATH };
}

/**
 * Resolve a popstate destination. The pathname wins for ``/evidence``;
 * at ``/`` a valid non-Evidence ``state.page`` is restored (Evidence never
 * lives at ``/``, so an evidence state there is treated as invalid);
 * anything else — missing, malformed, unknown path — fails to Market.
 * Read-only: popstate handling never writes history.
 */
export function resolvePopstate(pathname: string, state: unknown): Page {
  if (isEvidencePath(pathname)) return "evidence";
  if (pathname !== ROOT_PATH) return "market";
  if (typeof state === "object" && state !== null && "page" in state) {
    const page = (state as { page: unknown }).page;
    if (isPage(page) && page !== "evidence") return page;
  }
  return "market";
}

/** Canonical URL for a page (only Evidence is addressable). */
export function pathForPage(page: Page): string {
  return page === "evidence" ? EVIDENCE_PATH : ROOT_PATH;
}

export type NavigationAction =
  | { kind: "none" }
  | { kind: "push"; url: string; page: Page }
  | { kind: "replace"; url: string; page: Page };

/**
 * Plan the history action for an in-app transition:
 *  - same page               → nothing (no duplicate entries);
 *  - crossing the Evidence
 *    boundary (either way)   → push, so browser Back restores the exact
 *                              origin page;
 *  - among non-Evidence pages → replace in place at ``/`` (tab clicks never
 *                              pile up history entries).
 */
export function planNavigation(current: Page, target: Page): NavigationAction {
  if (current === target) return { kind: "none" };
  const url = pathForPage(target);
  if (target === "evidence" || current === "evidence") {
    return { kind: "push", url, page: target };
  }
  return { kind: "replace", url, page: target };
}

/** Minimal structural slice of ``window.history`` (injectable in tests). */
export interface HistoryLike {
  pushState(data: unknown, unused: string, url: string): void;
  replaceState(data: unknown, unused: string, url: string): void;
}

/** Apply a planned action with a ``{ page }`` state payload. */
export function applyHistoryAction(
  history: HistoryLike,
  action: NavigationAction,
): void {
  if (action.kind === "push") {
    history.pushState({ page: action.page }, "", action.url);
  } else if (action.kind === "replace") {
    history.replaceState({ page: action.page }, "", action.url);
  }
}

/** Minimal structural slice of ``window`` for popstate wiring. */
export interface PopstateWindowLike {
  location: { pathname: string };
  addEventListener(type: "popstate", listener: (ev: { state: unknown }) => void): void;
  removeEventListener(type: "popstate", listener: (ev: { state: unknown }) => void): void;
}

/**
 * Install the popstate listener; returns its cleanup. The handler resolves
 * every Back/Forward through resolvePopstate and only notifies — it never
 * pushes or replaces history — and removing the returned cleanup makes a
 * StrictMode setup → cleanup → setup cycle leave exactly one listener.
 */
export function installPopstateListener(
  win: PopstateWindowLike,
  onNavigate: (page: Page) => void,
): () => void {
  const handler = (ev: { state: unknown }) => {
    onNavigate(resolvePopstate(win.location.pathname, ev.state));
  };
  win.addEventListener("popstate", handler);
  return () => win.removeEventListener("popstate", handler);
}
