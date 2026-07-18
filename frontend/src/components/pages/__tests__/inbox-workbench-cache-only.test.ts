/**
 * Cache-only contract for the Headlines surface (InboxWorkbench).
 *
 * Rendering the page must NEVER auto-trigger a refresh: a refresh is a POST
 * that reaches RSS and writes SQLite, and it is an explicit user action (the
 * refresh button, the sole POST /news/refresh owner).  A GET-served feed —
 * fresh, stale, or unavailable — renders as-is.  Before this contract the
 * mount effect auto-POSTed a refresh whenever refresh_meta.freshness was
 * "stale" or "degraded"; because the cache-only backend marks BOTH stale and
 * unavailable payloads freshness="stale", that auto-refreshed a real fetch on
 * every stale/missing load.  `shouldAutoRefreshOnRender` locks the gate.
 */

import { describe, it, expect } from "vitest";
import { shouldAutoRefreshOnRender } from "../inbox-workbench";
import type { RefreshMeta } from "@/lib/api";

const base: RefreshMeta = {
  status: "ok",
  known: 10,
  new: 0,
  merged: 0,
  created: 0,
  reused: 10,
  source: "incremental",
  freshness: "fresh",
  last_successful_refresh: "2026-04-13T10:00:00",
};

describe("shouldAutoRefreshOnRender (cache-only)", () => {
  it("never auto-refreshes on a stale cache", () => {
    expect(shouldAutoRefreshOnRender({ ...base, status: "ok", freshness: "stale" })).toBe(false);
  });

  it("never auto-refreshes on an unavailable cache (status error + stale)", () => {
    expect(shouldAutoRefreshOnRender({ ...base, status: "error", freshness: "stale" })).toBe(false);
  });

  it("never auto-refreshes on a degraded feed", () => {
    expect(shouldAutoRefreshOnRender({ ...base, status: "degraded", freshness: "degraded" })).toBe(false);
  });

  it("never auto-refreshes on a fresh feed", () => {
    expect(shouldAutoRefreshOnRender({ ...base, status: "ok", freshness: "fresh" })).toBe(false);
  });

  it("never auto-refreshes when meta is null", () => {
    expect(shouldAutoRefreshOnRender(null)).toBe(false);
  });
});
