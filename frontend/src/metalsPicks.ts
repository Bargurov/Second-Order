// The metals the reader picked, kept in the address as ?m=a,b so a reload or a shared link shows the same comparison.
// URLSearchParams never throws on a malformed escape; an id that is not a known chapter is ignored and counted.

/**
 * The picks named by `m` (comma separated), in the address's order, first occurrence only, known ids only. When
 * nothing valid is left, the fallback (limited to known ids). `ignored` counts every named id that was not kept.
 */
export function picksFrom(search: string, known: readonly string[], fallback: readonly string[]):
  { picks: string[]; ignored: number } {
  const named = (new URLSearchParams(search).get("m") ?? "").split(",").filter((id) => id !== "");
  const picks: string[] = [];
  for (const id of named) if (known.includes(id) && !picks.includes(id)) picks.push(id);
  const ignored = named.length - picks.length;
  if (picks.length > 0) return { picks, ignored };
  return { picks: fallback.filter((id, at) => known.includes(id) && fallback.indexOf(id) === at), ignored };
}

/** The address search for a set of picks: "?m=a,b". */
export function searchFor(picks: readonly string[]): string {
  return `?m=${picks.join(",")}`;
}

/** The page's three parts, in tab order. */
export const TABS = ["overview", "by-metal", "method"] as const;
export type MetalsTab = typeof TABS[number];
const HASH = /^#(overview|method|by-metal)(?::(.*))?$/;

/**
 * The tab, and for "By metal" the metal opened, named by the address's hash ("#method", "#by-metal:cobalt"). A metal
 * that is not among the picks is dropped (the hash never adds a pick); any other hash is the overview.
 */
export function viewFrom(hash: string, picks: readonly string[]): { tab: MetalsTab; metal: string | null } {
  const found = HASH.exec(hash);
  if (found === null || (found[2] !== undefined && found[1] !== "by-metal")) return { tab: "overview", metal: null };
  const metal = found[2] !== undefined && picks.includes(found[2]) ? found[2] : null;
  return { tab: found[1] as MetalsTab, metal };
}

/** The hash for a tab and its opened metal: "" for the overview, so a plain link opens it. */
export function hashFor(tab: MetalsTab, metal: string | null): string {
  if (tab === "overview") return "";
  return tab === "by-metal" && metal !== null ? `#by-metal:${metal}` : `#${tab}`;
}

const words = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

/** The frames whose name (or id) holds the query, ignoring case, spaces and punctuation; all of them for none. */
export function matching<T extends { id: string; name: string }>(frames: readonly T[], query: string): T[] {
  const wanted = words(query);
  if (wanted === "") return [...frames];
  return frames.filter((frame) => words(frame.name).includes(wanted) || words(frame.id).includes(wanted));
}
