// Event Inbox client: GET-only reads verified before use (five fixed sources, each entry's link on its own source's
// host), one explicit refresh POST, plain-text entries, local topic and source filters, and a form prefill that fills
// only the headline and official link. Feed timestamps are suggested exactly as stated, in any browser time zone. All
// feed content here is SYNTHETIC.
import assert from "node:assert/strict";
import test from "node:test";
import {
  INBOX_VIEW_VERSION, NO_FILTER, SOURCE_HOSTS, edited, fetchInbox, filtered, kindNote, linkLabel, officialLink,
  prefilledFields, refreshInbox, sourceStatus, suggestedFields, topics, utcStamp, type InboxItem, type InboxSource,
  type InboxView,
} from "../src/inbox.ts";
import { intakePayload, type IntakeFields } from "../src/intake.ts";

/** The zone this process started in. Deleting TZ does not make Node resolve its zone again, so it is set back by name. */
const STARTING_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;
const STARTING_TZ = process.env.TZ;
const ZONES = ["UTC", "America/New_York", "Asia/Jerusalem", "Pacific/Pago_Pago", "Pacific/Kiritimati", "Asia/Tokyo"];

function inZone<T>(zone: string, body: () => T): T {
  const original = process.env.TZ;
  process.env.TZ = zone;
  try {
    return body();
  } finally {
    process.env.TZ = original ?? STARTING_ZONE;  // Setting TZ makes Node resolve the zone again.
    if (original === undefined) delete process.env.TZ;  // Deleting does not, so the starting zone stays in force.
  }
}

async function withFetch<T>(fake: typeof fetch, run: () => Promise<T>): Promise<T> {
  const original = globalThis.fetch;
  globalThis.fetch = fake;
  try {
    return await run();
  } finally {
    globalThis.fetch = original;
  }
}

const EMPTY: IntakeFields = { headline: "", sourceUrl: "", publishedDate: "", publishedTime: "", publishedOffset: "",
                              sourceText: "" };
const TOPICS: Record<string, [string, string]> = {
  "fed-monetary": ["Monetary policy", "Policy announcement"], "bls-empsit": ["Employment", "Statistical release"],
  "bls-cpi": ["Inflation", "Statistical release"], "eia-todayinenergy": ["Energy", "Analysis article"],
  "wto-news": ["International trade", "News announcement"],
};
const source = (key: string): InboxSource => ({
  key, label: key, publisher: "Synthetic publisher", category: TOPICS[key][0], kind: TOPICS[key][1],
  attribution: key === "wto-news" ? "WTO news" : "", feed_url: "https://www.bls.gov/feed/empsit.rss",
  catalogue_url: "https://www.bls.gov/feed/", terms_url: "https://www.bls.gov/bls/linksite.htm", policy_url: null,
  contact_required: true, state: "ok", problem: null, last_attempt: null,
  last_success: { retrieved_at: "2026-10-08T09:00:03+00:00", http_status: 200, format: "atom", listed: 1,
                  not_retained: 0, duplicates: 0, skipped_count: 0, item_count: 1 } });
const ITEM: InboxItem = {
  id: "bls-empsit:abc", position: 1, title: "Synthetic payroll release", title_truncated: false,
  link: "https://www.bls.gov/news.release/archives/empsit_10022026.htm", excerpt: "Synthetic excerpt.",
  excerpt_truncated: false, excerpt_repeats_title: false,
  feed_timestamp: { raw: "2026-10-02T07:51:08.289-04:00", origin: "Atom published", instant_utc: "2026-10-02T11:51:08+00:00",
                    suggestion: { date: "2026-10-02", time: "07:51:08", offset: "-04:00", dropped_fraction: ".289" },
                    problem: null },
  first_seen_at: "2026-10-08T09:00:03+00:00", source: "bls-empsit", publisher: "U.S. Bureau of Labor Statistics",
  category: "Employment", kind: "Statistical release", attribution: "", retrieved_at: "2026-10-08T09:00:03+00:00",
  stale: false };
const ENERGY: InboxItem = {
  ...ITEM, id: "eia-todayinenergy:abc", title: "Synthetic energy article", source: "eia-todayinenergy",
  link: "https://www.eia.gov/todayinenergy/detail.php?id=90001", publisher: "U.S. Energy Information Administration",
  category: "Energy", kind: "Analysis article", attribution: "Source: U.S. Energy Information Administration" };
const TRADE: InboxItem = {
  ...ITEM, id: "wto-news:abc", title: "Synthetic trade news", source: "wto-news",
  link: "https://www.wto.org/english/news_e/news26_e/synth_08oct26_e.htm", publisher: "World Trade Organization",
  category: "International trade", kind: "News announcement", attribution: "WTO news" };
const VIEW: InboxView = {
  view_version: INBOX_VIEW_VERSION, retention: { per_source: 50, statement: "At most 50 per source." },
  sources: Object.keys(SOURCE_HOSTS).map(source), items: [ITEM, ENERGY, TRADE] };
const reply = (status: number, body: unknown, sent: { url: string; init?: RequestInit }[] = []) =>
  (async (url: string, init?: RequestInit) => {
    sent.push({ url, init });
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  }) as typeof fetch;

test("the inbox is read with a plain GET and refused unless it verifies", async () => {
  const sent: { url: string; init?: RequestInit }[] = [];
  assert.deepEqual(await withFetch(reply(200, VIEW, sent), () => fetchInbox()), { state: "ready", data: VIEW });
  assert.deepEqual(sent.map(({ url, init }) => [url, init?.method ?? "GET"]), [["/api/inbox", "GET"]]);
  for (const bad of [{ ...VIEW, view_version: "event-inbox-view-9" }, { ...VIEW, sources: VIEW.sources.slice(1) },
                     { ...VIEW, sources: [...VIEW.sources].reverse() },
                     { ...VIEW, sources: [...VIEW.sources, source("wto-news")] },
                     { ...VIEW, sources: VIEW.sources.map((one) => ({ ...one, kind: undefined })) },
                     { ...VIEW, items: [{ ...ITEM, link: "javascript:alert(1)" }] },
                     { ...VIEW, items: [{ ...ITEM, link: "https://mirror.example.org/empsit.htm" }] },
                     // An official link on another source's host is not this entry's link.
                     { ...VIEW, items: [{ ...ITEM, link: ENERGY.link }] },
                     { ...VIEW, items: [{ ...TRADE, link: "https://www.eia.gov/todayinenergy/detail.php?id=1" }] },
                     { ...VIEW, items: [{ ...ENERGY, kind: undefined }] },
                     { ...VIEW, items: [{ ...ITEM, source: "elsewhere" }] },
                     { ...VIEW, items: [{ ...ITEM, source: "toString" }] }]) {
    assert.equal((await withFetch(reply(200, bad), () => fetchInbox())).state, "error");
  }
  assert.equal((await withFetch(reply(500, { detail: "broken" }), () => fetchInbox())).state, "error");
});

test("retained entries from the local archive verify only as marked history with official links", async () => {
  const kept: InboxItem = { ...ITEM, id: "bls-empsit:old", position: null, history: true,
                            last_seen_at: "2026-10-07T09:00:03+00:00", retrieved_at: "2026-10-07T09:00:03+00:00", versions: 1 };
  const withHistory = { ...VIEW, retained: [kept] };
  assert.deepEqual(await withFetch(reply(200, withHistory), () => fetchInbox()), { state: "ready", data: withHistory });
  for (const bad of [{ ...withHistory, retained: [{ ...kept, history: undefined }] },
                     { ...withHistory, retained: [{ ...kept, last_seen_at: undefined }] },
                     { ...withHistory, retained: [{ ...kept, link: "https://mirror.example.org/empsit.htm" }] },
                     { ...withHistory, retained: "none" }]) {
    assert.equal((await withFetch(reply(200, bad), () => fetchInbox())).state, "error");
  }
});

test("a refresh is one explicit POST with the inbox header and no options", async () => {
  const sent: { url: string; init?: RequestInit }[] = [];
  const done = await withFetch(reply(200, { ...VIEW, refreshed: [] }, sent), () => refreshInbox());
  assert.equal(done.state, "done");
  assert.equal(sent.length, 1);
  const { url, init } = sent[0];
  assert.deepEqual([url, init?.method, init?.body], ["/api/inbox/refresh", "POST", "{}"]);
  assert.equal((init?.headers as Record<string, string>)["X-Second-Order-Inbox"], "1");
  assert.deepEqual(await withFetch(reply(409, { detail: "A refresh is already running" }), () => refreshInbox()),
                   { state: "failed", message: "A refresh is already running" });
  assert.equal((await withFetch(reply(500, {}), () => refreshInbox())).state, "unconfirmed");
  const lost = await withFetch((async () => { throw new TypeError("network"); }) as typeof fetch, () => refreshInbox());
  assert.equal(lost.state, "unconfirmed");
});

test("only https links on the publishers' own hosts are official", () => {
  for (const ok of ["https://www.bls.gov/news.release/x.htm", "https://www.federalreserve.gov/newsevents/x.htm",
                    "https://www.eia.gov/todayinenergy/detail.php?id=1", "https://www.wto.org/english/news_e/x.htm"]) {
    assert.ok(officialLink(ok), ok);
  }
  for (const bad of ["http://www.bls.gov/x.htm", "javascript:alert(1)", "https://bls.gov.example.org/x.htm",
                     "https://user@www.bls.gov/x.htm", "https://www.bls.gov:8443/x.htm", "data:text/html,x", "not a url",
                     "http://www.wto.org/english/news_e/x.htm", "https://wto.org/x.htm", "https://eia.gov/x.php",
                     "https://www.eia.gov.example.org/x.php"]) {
    assert.ok(!officialLink(bad), bad);
  }
});

test("an entry fills only the headline and official link; time and published text stay for the operator", () => {
  const filled = prefilledFields(ITEM, EMPTY);
  assert.deepEqual(filled, { ...EMPTY, headline: ITEM.title, sourceUrl: ITEM.link });
  assert.equal(filled.sourceText, "");  // The excerpt is never the published text.
  assert.equal(prefilledFields({ ...ITEM, link: "javascript:alert(1)" }, EMPTY).sourceUrl, "");
  assert.ok(!edited(filled, filled));
  assert.ok(edited({ ...filled, sourceText: "typed" }, filled));
  assert.equal(intakePayload(filled).payload, null);  // Incomplete until the operator adds time and text.
});

test("a feed timestamp is suggested exactly as stated, in every browser time zone", () => {
  for (const zone of [STARTING_ZONE, ...ZONES]) {
    inZone(zone, () => {
      const suggested = suggestedFields(ITEM.feed_timestamp);
      assert.deepEqual(suggested, { publishedDate: "2026-10-02", publishedTime: "07:51:08", publishedOffset: "-04:00" }, zone);
      const payload = intakePayload({ ...prefilledFields(ITEM, EMPTY), ...suggested!, sourceText: "Pasted text." }).payload;
      assert.equal(payload?.published_at, "2026-10-02T07:51:08-04:00", zone);
      assert.equal(utcStamp(ITEM.feed_timestamp.instant_utc), "2026-10-02 11:51 UTC", zone);
      assert.equal(utcStamp(ITEM.retrieved_at), "2026-10-08 09:00 UTC", zone);
    });
  }
  assert.equal(Intl.DateTimeFormat().resolvedOptions().timeZone, STARTING_ZONE);
  assert.equal(process.env.TZ, STARTING_TZ);
  const unknown = { ...ITEM.feed_timestamp, raw: null, instant_utc: null, suggestion: null, problem: "No timestamp." };
  assert.equal(suggestedFields(unknown), null);
  assert.equal(utcStamp(null), "unknown");
  assert.equal(utcStamp("2026-10-08T16:26:49.550324+00:00"), "2026-10-08 16:26 UTC");  // A recorded response time.
});

test("filters narrow only the entries already held, by topic and source", async () => {
  const sent: { url: string; init?: RequestInit }[] = [];
  const all = [ITEM, ENERGY, TRADE];
  await withFetch(reply(200, VIEW, sent), async () => {
    assert.deepEqual(filtered(all, NO_FILTER), all);
    assert.deepEqual(filtered(all, { topic: "Energy", source: "" }), [ENERGY]);
    assert.deepEqual(filtered(all, { topic: "", source: "wto-news" }), [TRADE]);
    assert.deepEqual(filtered(all, { topic: "Energy", source: "wto-news" }), []);
    assert.deepEqual(filtered(all, { topic: "International trade", source: "wto-news" }), [TRADE]);
  });
  assert.equal(sent.length, 0);  // Filtering is local: nothing is requested.
  assert.deepEqual(topics(VIEW.sources), ["Monetary policy", "Employment", "Inflation", "Energy", "International trade"]);
});

test("energy articles and trade news are told apart from formal statistical releases", () => {
  assert.equal(kindNote("Statistical release"), "Formal statistical release");
  assert.equal(kindNote("Analysis article"), "Analysis article, not a statistical release");
  assert.equal(kindNote("News announcement"), "News announcement, not a statistical release");
  assert.equal(kindNote("Policy announcement"), "Policy announcement, not a statistical release");
  assert.deepEqual(["Statistical release", "Policy announcement", "Analysis article", "News announcement"].map(linkLabel),
                   ["Official release", "Official release", "Official article", "Official news item"]);
  // Analyze this event fills the same two fields for every source: no article text, no time.
  for (const item of [ENERGY, TRADE]) {
    assert.deepEqual(prefilledFields(item, EMPTY), { ...EMPTY, headline: item.title, sourceUrl: item.link });
  }
});

test("a source's state never claims live data", () => {
  const states: InboxSource["state"][] = ["ok", "failed", "not_requested", "unreadable", "never_refreshed"];
  for (const state of states) {
    const label = sourceStatus({ ...source("bls-cpi"), state }).label;
    assert.ok(!/\blive\b/i.test(label.replace("not live", "")), `${state}: ${label}`);
  }
  assert.equal(sourceStatus(source("bls-cpi")).label, "Retrieved 2026-10-08 09:00 UTC · as of that refresh, not live");
});
