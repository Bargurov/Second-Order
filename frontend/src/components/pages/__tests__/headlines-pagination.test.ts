/**
 * Unit tests for the _getNextPageParam pagination contract.
 *
 * The helper reads an opaque server-issued cursor from the last page.
 * It must terminate the infinite query when the cursor is absent and
 * forward the cursor string otherwise.
 */

import { describe, it, expect } from "vitest";
import { _getNextPageParam } from "../headlines-page";
import type { NewsResponse } from "@/lib/api";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("_getNextPageParam (cursor contract)", () => {
  it("returns undefined when lastPage is undefined", () => {
    expect(_getNextPageParam(undefined)).toBeUndefined();
  });

  it("returns undefined when next_cursor is null (last page reached)", () => {
    const p = { clusters: [], total_count: 0, next_cursor: null } as unknown as NewsResponse;
    expect(_getNextPageParam(p)).toBeUndefined();
  });

  it("returns undefined when next_cursor is missing from the payload", () => {
    const p = { clusters: [], total_count: 0 } as unknown as NewsResponse;
    expect(_getNextPageParam(p)).toBeUndefined();
  });

  it("returns undefined when next_cursor is an empty string", () => {
    const p = { clusters: [], total_count: 0, next_cursor: "" } as unknown as NewsResponse;
    expect(_getNextPageParam(p)).toBeUndefined();
  });

  it("forwards the cursor string verbatim when present", () => {
    const p = { clusters: [], total_count: 10, next_cursor: "abc123" } as unknown as NewsResponse;
    expect(_getNextPageParam(p)).toBe("abc123");
  });

  it("handles completely empty shape {} as lastPage (returns undefined)", () => {
    const empty = {} as unknown as NewsResponse;
    expect(_getNextPageParam(empty)).toBeUndefined();
  });
});
