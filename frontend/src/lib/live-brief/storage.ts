/**
 * storage.ts — browser-local persistence for the ``live-event-brief-v1``
 * contract.  No backend, no database, no network.
 *
 * Reads are fail-closed: a missing store, unreadable value, non-JSON text, or
 * a brief that does not pass the exact validator is dropped rather than
 * crashing the surface, and an invalid item never evicts the valid ones.  All
 * access is guarded so the loader is safe to call from a render initializer in
 * the project's no-jsdom (no ``localStorage``) test environment.
 */
import { SCHEMA_VERSION, STORAGE_KEY, type Brief } from "./types";
import { isValidBrief } from "./validate";

/** Minimal structural slice of ``Storage`` (injectable in tests). */
export interface BriefStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/** The real browser store, or null when unavailable (SSR / tests / denied). */
export function defaultStore(): BriefStore | null {
  try {
    if (typeof localStorage !== "undefined") return localStorage;
  } catch {
    // access can throw (privacy mode, sandboxed frame) — treat as unavailable.
  }
  return null;
}

function extractBriefArray(parsed: unknown): unknown[] {
  if (Array.isArray(parsed)) return parsed;
  if (parsed && typeof parsed === "object" && Array.isArray((parsed as { briefs?: unknown }).briefs)) {
    return (parsed as { briefs: unknown[] }).briefs;
  }
  return [];
}

/**
 * Load every valid stored brief.  Invalid items are silently dropped (never
 * throw); a completely absent or corrupt store yields ``[]``.
 */
export function loadBriefs(store: BriefStore | null = defaultStore()): Brief[] {
  if (!store) return [];
  let raw: string | null;
  try {
    raw = store.getItem(STORAGE_KEY);
  } catch {
    return [];
  }
  if (!raw) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  return extractBriefArray(parsed).filter(isValidBrief);
}

/**
 * Persist the brief set.  Returns false when there is no store or the write
 * fails (e.g. quota) rather than throwing.
 */
export function saveBriefs(briefs: Brief[], store: BriefStore | null = defaultStore()): boolean {
  if (!store) return false;
  try {
    store.setItem(STORAGE_KEY, JSON.stringify({ schema_version: SCHEMA_VERSION, briefs }));
    return true;
  } catch {
    return false;
  }
}

/** Insert or replace a brief by id (preserving order; appends if new). */
export function upsertBrief(briefs: readonly Brief[], brief: Brief): Brief[] {
  const idx = briefs.findIndex((b) => b.brief_id === brief.brief_id);
  if (idx === -1) return [...briefs, brief];
  const next = briefs.slice();
  next[idx] = brief;
  return next;
}

/** Remove a brief by id. */
export function removeBrief(briefs: readonly Brief[], id: string): Brief[] {
  return briefs.filter((b) => b.brief_id !== id);
}
