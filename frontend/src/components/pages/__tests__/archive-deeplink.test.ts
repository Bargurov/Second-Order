/**
 * R6C — Archive deep-link resolution.
 *
 * `resolveSelectedEvent` is the pure seam behind the Case Library → in-app
 * Archive/Event Detail upgrade: when a case id is requested that is NOT on the
 * archive's currently-loaded page, the detail must still open by falling back
 * to a read-only fetch-by-id (GET /events/{id}, which is decorated with
 * validation_status_v2).  It must never fabricate an event — an empty or
 * mismatched fetch resolves to null.
 *
 * Pure helper, node-environment test (no jsdom, matching the project pattern).
 */
import { describe, it, expect } from "vitest";

import { resolveSelectedEvent } from "../recent-events";
import type { SavedEvent } from "@/lib/api";

const ev = (id: number, extra: Partial<SavedEvent> = {}): SavedEvent =>
  ({ id, headline: `event ${id}`, ...extra }) as unknown as SavedEvent;

describe("resolveSelectedEvent — Case Library in-app deep-link (R6C)", () => {
  it("returns null when nothing is selected", () => {
    expect(resolveSelectedEvent(null, [ev(1)], null)).toBeNull();
  });

  it("returns the in-page event when the selected id is on the loaded page", () => {
    const page = [ev(1), ev(105)];
    expect(resolveSelectedEvent(105, page, null)?.id).toBe(105);
  });

  it("prefers the in-page event over a fetched one with the same id", () => {
    const inPage = ev(105, { headline: "in-page" });
    const fetched = ev(105, { headline: "fetched" });
    expect(resolveSelectedEvent(105, [inPage], fetched)?.headline).toBe("in-page");
  });

  it("falls back to the fetched-by-id event when the id is not on the loaded page", () => {
    expect(resolveSelectedEvent(105, [ev(1)], ev(105))?.id).toBe(105);
  });

  it("does not fabricate: returns null when the fetch is empty", () => {
    expect(resolveSelectedEvent(105, [ev(1)], null)).toBeNull();
    expect(resolveSelectedEvent(105, [ev(1)], undefined)).toBeNull();
  });

  it("ignores a fetched event whose id does not match the selection", () => {
    expect(resolveSelectedEvent(105, [ev(1)], ev(999))).toBeNull();
  });
});
