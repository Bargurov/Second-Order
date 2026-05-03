/**
 * Guard coverage for the Headlines page crash that black-screened the
 * route on certain backend payloads.  Two pure helpers anchor the fix:
 *
 *   - ``_getNextPageParam`` must tolerate a missing / non-array
 *     ``allPages`` argument so a future maintainer can never re-introduce
 *     a ``pages.length`` crash.
 *   - ``_normalizeNewsPage`` must always return a NewsResponse-shaped
 *     object — even when fed nonsense — so ``data.pages.flatMap`` can
 *     trust ``clusters`` to be an array and ``total_count`` to be a
 *     number.
 *
 * The existing pagination tests (``headlines-pagination.test.ts``) cover
 * the cursor-passthrough contract; this file only exercises the
 * crash-resistance contract added alongside the fix.
 */

import { describe, it, expect } from "vitest";
import { _getNextPageParam, _normalizeNewsPage } from "../headlines-page";
import type { NewsResponse } from "@/lib/api";

// ---------------------------------------------------------------------------
// _getNextPageParam — tolerate hostile / missing allPages
// ---------------------------------------------------------------------------

describe("_getNextPageParam — allPages tolerance", () => {
  const cursored = { clusters: [], total_count: 5, next_cursor: "x1" } as unknown as NewsResponse;

  it("returns the cursor when allPages is omitted (direct call)", () => {
    expect(_getNextPageParam(cursored)).toBe("x1");
  });

  it("returns the cursor when allPages is a single-page array (cold start)", () => {
    expect(_getNextPageParam(cursored, [cursored])).toBe("x1");
  });

  it("returns the cursor when allPages is the multi-page history", () => {
    expect(_getNextPageParam(cursored, [cursored, cursored, cursored])).toBe("x1");
  });

  it("returns undefined when allPages is null", () => {
    // Defensive guard — should never occur in practice, but a stale
    // cache slot could feed null in.
    expect(_getNextPageParam(cursored, null)).toBeUndefined();
  });

  it("returns undefined when allPages is a non-array value", () => {
    // @ts-expect-error — runtime contract guard for hostile input
    expect(_getNextPageParam(cursored, {})).toBeUndefined();
    // @ts-expect-error — same
    expect(_getNextPageParam(cursored, "[]")).toBeUndefined();
  });

  it("returns undefined when allPages is an empty array (re-mount race)", () => {
    expect(_getNextPageParam(cursored, [])).toBeUndefined();
  });

  it("does not crash dereferencing pages length on hostile input", () => {
    // @ts-expect-error — null is not assignable, but the runtime guard
    // is the contract under test.
    expect(() => _getNextPageParam(undefined, null)).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// _normalizeNewsPage — always emit a NewsResponse-shaped object
// ---------------------------------------------------------------------------

describe("_normalizeNewsPage — defensive page shape", () => {
  it("emits a complete empty page from undefined input", () => {
    const out = _normalizeNewsPage(undefined);
    expect(out.clusters).toEqual([]);
    expect(out.total_count).toBe(0);
    expect(out.total_headlines).toBe(0);
    expect(out.next_cursor).toBeNull();
    expect(out.macro_releases).toEqual([]);
    expect(out.policy_items).toEqual([]);
    expect(out.feed_status).toEqual([]);
  });

  it("emits a complete empty page from null input", () => {
    const out = _normalizeNewsPage(null);
    expect(out.clusters).toEqual([]);
    expect(out.total_count).toBe(0);
    expect(out.next_cursor).toBeNull();
  });

  it("emits a complete empty page from non-object input", () => {
    expect(_normalizeNewsPage("oops").clusters).toEqual([]);
    expect(_normalizeNewsPage(42).total_count).toBe(0);
    expect(_normalizeNewsPage([]).clusters).toEqual([]);
  });

  it("normalises a partial payload missing clusters", () => {
    const out = _normalizeNewsPage({ total_count: 7, next_cursor: "abc" });
    expect(out.clusters).toEqual([]);
    expect(out.total_count).toBe(7);
    expect(out.next_cursor).toBe("abc");
  });

  it("converts an empty-string next_cursor to null (terminate)", () => {
    expect(_normalizeNewsPage({ next_cursor: "" }).next_cursor).toBeNull();
  });

  it("preserves a non-empty next_cursor verbatim", () => {
    expect(_normalizeNewsPage({ next_cursor: "page2" }).next_cursor).toBe("page2");
  });

  it("coerces null/undefined collection fields to []", () => {
    const out = _normalizeNewsPage({
      clusters: null,
      macro_releases: null,
      policy_items: undefined,
      feed_status: undefined,
    });
    expect(out.clusters).toEqual([]);
    expect(out.macro_releases).toEqual([]);
    expect(out.policy_items).toEqual([]);
    expect(out.feed_status).toEqual([]);
  });

  it("preserves valid array inputs by reference content", () => {
    const clusters = [
      { headline: "A", source_count: 1, low_signal: false } as unknown,
    ];
    const out = _normalizeNewsPage({ clusters, total_count: 1 });
    expect(out.clusters).toEqual(clusters);
    expect(out.total_count).toBe(1);
  });

  it("forwards refresh_meta when present", () => {
    const refresh_meta = { status: "ok", freshness: "fresh" } as unknown as NewsResponse["refresh_meta"];
    const out = _normalizeNewsPage({ refresh_meta });
    expect(out.refresh_meta).toBe(refresh_meta);
  });

  it("ignores garbage collection-typed fields without throwing", () => {
    const out = _normalizeNewsPage({
      clusters: "not an array",
      macro_releases: 42,
      policy_items: { not: "array" },
    });
    expect(out.clusters).toEqual([]);
    expect(out.macro_releases).toEqual([]);
    expect(out.policy_items).toEqual([]);
  });

  it("is idempotent — running a normalised page through itself is a no-op", () => {
    const once = _normalizeNewsPage({});
    const twice = _normalizeNewsPage(once);
    expect(twice).toEqual(once);
  });
});

// ---------------------------------------------------------------------------
// Combined contract — pagination terminates cleanly on a normalised empty
// ---------------------------------------------------------------------------

describe("normalize → getNextPageParam pipeline", () => {
  it("a normalised page from a malformed body terminates pagination", () => {
    const page = _normalizeNewsPage({});
    expect(_getNextPageParam(page, [page])).toBeUndefined();
  });

  it("a normalised page with a real cursor advances pagination", () => {
    const page = _normalizeNewsPage({ next_cursor: "next-x" });
    expect(_getNextPageParam(page, [page])).toBe("next-x");
  });

  it("a normalised page with empty-string cursor terminates", () => {
    const page = _normalizeNewsPage({ next_cursor: "" });
    expect(_getNextPageParam(page, [page])).toBeUndefined();
  });
});
