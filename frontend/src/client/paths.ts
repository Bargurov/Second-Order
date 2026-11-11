// The Client's own addresses (the server sends the Client build for every non-API path of a user session). IDs are
// opaque: they are decoded and passed to the server, never parsed. A malformed address is Not Found, never an error.
// The public pages' addresses also reach a signed-in user (docs/onboarding-contract.md section 7): /credits is the
// user's own credits page, and /register and /sign-in say that the user is already signed in.
//
// News is the home (docs/news-stories-contract.md section 7): / and /news open Hot now, and the wordmark leads to
// /news. Every earlier address still opens what it did, except / itself: Your analyses, which / used to show, is at
// /analyses; analysis, source, import, credits and sign-in addresses are unchanged. The feed entries with interests,
// search and import, which /news used to show, are at /news/reports.

import type { View } from "../contracts/stories.ts";

export type NewsTab = View | "topics";

export type ClientRoute =
  | { view: "news"; tab: NewsTab }
  | { view: "story"; storyId: string }
  | { view: "deeper"; storyId: string }
  | { view: "topic"; topicId: string }
  | { view: "reports" }
  | { view: "analyses" }
  | { view: "import"; importId: string }
  | { view: "sources" }
  | { view: "new-source" }
  | { view: "source"; sourceId: string }
  | { view: "analysis"; analysisId: string }
  | { view: "credits" }
  | { view: "signed-in" }
  | { view: "not-found" };

const TAB_PATH: Record<NewsTab, string> = { hot: "/news", coverage: "/news/coverage", latest: "/news/latest", topics: "/news/topics",
                                            interests: "/news/for-you" };

export const href = {
  news: "/news",
  newsTab: (tab: NewsTab) => TAB_PATH[tab],
  story: (storyId: string) => `/news/stories/${encodeURIComponent(storyId)}`,
  deeper: (storyId: string) => `/news/stories/${encodeURIComponent(storyId)}/deeper`,
  topic: (topicId: string) => `/news/topics/${encodeURIComponent(topicId)}`,
  reports: "/news/reports",
  analyses: "/analyses",
  newsImport: (importId: string) => `/news/imports/${encodeURIComponent(importId)}`,
  sources: "/sources",
  newSource: "/sources/new",
  credits: "/credits",
  source: (sourceId: string) => `/sources/${encodeURIComponent(sourceId)}`,
  analysis: (analysisId: string) => `/analyses/${encodeURIComponent(analysisId)}`,
};

function decoded(segment: string): string | null {
  try {
    const value = decodeURIComponent(segment);
    return value.length > 0 && !value.includes("/") ? value : null;
  } catch (error) {
    if (error instanceof URIError) return null;
    throw error;
  }
}

/** The decoded ID when `path` is this kind of address: null when it is but its ID is malformed, undefined when not. */
function idOf(pattern: RegExp, path: string): string | null | undefined {
  const found = pattern.exec(path);
  return found ? decoded(found[1]) : undefined;
}

const WITH_ID: [RegExp, (id: string) => ClientRoute][] = [
  [/^\/news\/stories\/([^/]+)\/deeper$/, (storyId) => ({ view: "deeper", storyId })],
  [/^\/news\/stories\/([^/]+)$/, (storyId) => ({ view: "story", storyId })],
  [/^\/news\/topics\/([^/]+)$/, (topicId) => ({ view: "topic", topicId })],
  [/^\/news\/imports\/([^/]+)$/, (importId) => ({ view: "import", importId })],
  [/^\/sources\/([^/]+)$/, (sourceId) => ({ view: "source", sourceId })],
  [/^\/analyses\/([^/]+)$/, (analysisId) => ({ view: "analysis", analysisId })],
];

export function matchClientPath(pathname: string): ClientRoute {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  if (path === "/" || path === "/client.html") return { view: "news", tab: "hot" };
  const tab = (Object.entries(TAB_PATH) as [NewsTab, string][]).find(([, address]) => address === path);
  if (tab) return { view: "news", tab: tab[0] };
  if (path === "/news/reports") return { view: "reports" };
  if (path === "/analyses") return { view: "analyses" };
  if (path === "/sources") return { view: "sources" };
  if (path === "/sources/new") return { view: "new-source" };
  if (path === "/credits") return { view: "credits" };
  if (path === "/register" || path === "/sign-in") return { view: "signed-in" };
  for (const [pattern, route] of WITH_ID) {
    const id = idOf(pattern, path);
    if (id === null) return { view: "not-found" };
    if (id !== undefined) return route(id);
  }
  return { view: "not-found" };
}
