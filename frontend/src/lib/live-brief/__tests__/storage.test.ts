/**
 * storage.test.ts — browser-local persistence, fail-closed loads, reload
 * restoration.  Uses an injected in-memory store (the project runs tests with
 * no jsdom / no real ``localStorage``).
 */
import { describe, expect, it } from "vitest";

import { STORAGE_KEY } from "../types";
import { loadBriefs, removeBrief, saveBriefs, upsertBrief, type BriefStore } from "../storage";
import { validBriefFixture } from "./fixture";

function memStore(seed: Record<string, string> = {}): BriefStore & { map: Record<string, string> } {
  const map: Record<string, string> = { ...seed };
  return {
    map,
    getItem: (k) => (k in map ? map[k] : null),
    setItem: (k, v) => {
      map[k] = v;
    },
  };
}

describe("saveBriefs / loadBriefs", () => {
  it("persists and restores a valid brief (reload restoration)", () => {
    const store = memStore();
    const brief = validBriefFixture();
    expect(saveBriefs([brief], store)).toBe(true);

    // Simulate a page reload: a brand-new store object over the same backing map.
    const reloaded = loadBriefs(memStore(store.map));
    expect(reloaded).toHaveLength(1);
    expect(reloaded[0].brief_id).toBe(brief.brief_id);
    expect(reloaded[0]).toEqual(brief);
  });

  it("returns [] on an empty store, a null store, or corrupt JSON", () => {
    expect(loadBriefs(memStore())).toEqual([]);
    expect(loadBriefs(null)).toEqual([]);
    expect(loadBriefs(memStore({ [STORAGE_KEY]: "{not json" }))).toEqual([]);
  });

  it("drops invalid stored briefs but keeps the valid ones", () => {
    const good = validBriefFixture();
    const bad = { ...validBriefFixture(), non_claim: "tampered" };
    const store = memStore({
      [STORAGE_KEY]: JSON.stringify({ schema_version: "live-event-brief-v1", briefs: [good, bad] }),
    });
    const loaded = loadBriefs(store);
    expect(loaded).toHaveLength(1);
    expect(loaded[0].brief_id).toBe(good.brief_id);
  });

  it("saveBriefs returns false with no store and never throws", () => {
    expect(saveBriefs([validBriefFixture()], null)).toBe(false);
  });

  it("also accepts a bare-array store payload", () => {
    const store = memStore({ [STORAGE_KEY]: JSON.stringify([validBriefFixture()]) });
    expect(loadBriefs(store)).toHaveLength(1);
  });
});

describe("upsertBrief / removeBrief", () => {
  it("appends a new brief and replaces an existing one by id, order preserved", () => {
    const a = { ...validBriefFixture(), brief_id: "a" };
    const b = { ...validBriefFixture(), brief_id: "b" };
    let list = upsertBrief([a], b);
    expect(list.map((x) => x.brief_id)).toEqual(["a", "b"]);
    list = upsertBrief(list, { ...a, title: "renamed" });
    expect(list.map((x) => x.brief_id)).toEqual(["a", "b"]);
    expect(list[0].title).toBe("renamed");
    list = removeBrief(list, "a");
    expect(list.map((x) => x.brief_id)).toEqual(["b"]);
  });
});
