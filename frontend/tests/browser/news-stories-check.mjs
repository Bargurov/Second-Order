// Browser check of the news-first journey on the BUILT Client and Admin, in one headless Chrome against the REAL server
// (tests/news_desk_server.py --simulated-provider): SYNTHETIC accounts, terms and usage limits, SYNTHETIC publishers
// whose reports are dated relative to the launcher's start, grouped, merged, briefed and linked to a topic through the
// server's own actions, one of them answering a later refresh with HTTP 503. Nothing is mocked in the browser, nothing
// reaches a network (every fetcher is simulated and records each request), and no real key is read.
//
// The journey: a signed-out visitor's story read is refused -> the reader signs in and lands on the News home (Hot now),
// the News link current -> the lead story is the newest development; a briefed story shows its summary, a story without
// a brief says so and shows its feed excerpt marked as not the article; a stale feed's story says so -> a headline
// opens the internal story page: the brief with reported facts apart from possible implications and what is uncertain,
// its provenance and material, the Sources with each publisher's own https link in a new tab, coverage that counts a
// wire copy once, related developments and the topic -> reading sent only GETs, and the server's feeds, provider and
// limits were untouched -> the topic's timeline in order -> Latest, Topics and Your interests -> a story without a
// stated time offers no deeper analysis and says why -> Go deeper: what it uses, the exact text, an Effort, one
// explicit Prepare that saves the reader's source and prepares the analysis, then the analysis page with its credit
// quote still to ask for, nothing quoted or sent -> going back shows the earlier work, and the counts are one source
// and one preparation -> the wordmark leads to News; /analyses, an analysis and a source open by address; Reports &
// search -> the administrator's News desk: the registry, the stories, a $0 draft from the reports' own words completed
// and published -> the reader sees it -> phone width, no outside request, no page error, nothing in browser storage.
//
//   cd frontend; npm run build; node tests/browser/news-stories-check.mjs
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const python = process.env.SECOND_ORDER_PYTHON ?? "python";
const chromePath = [process.env.SECOND_ORDER_CHROME, "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
  "/usr/bin/chromium-browser"].find((path) => path && existsSync(path));
if (!chromePath) throw new Error("Chrome was not found; set SECOND_ORDER_CHROME to its executable.");
// Test current source without replacing the builds served by an already running local server.
const staticRoot = process.env.SECOND_ORDER_TEST_STATIC_ROOT
  ? resolve(process.env.SECOND_ORDER_TEST_STATIC_ROOT) : join(repo, "frontend");
for (const built of ["dist/index.html", "dist-client/client.html"]) {
  if (!existsSync(join(staticRoot, built))) throw new Error("Build both clients first: npm run build (or set SECOND_ORDER_TEST_STATIC_ROOT)");
}

const PASSWORDS = { admin: "synthetic-admin-pass", "reader-a": "synthetic-reader-a" };  // tests/account_fakes.py
const TARIFF = "Synthetic Republic announces 15% tariff on imported steel";
const REVISION = "Synthetic Republic narrows steel tariff after talks";
const PORT_STORY = "Synthetic port reports record container volumes";
const UNRELATED = "Synthetic Republic steel museum opens new wing";  // Assessed (SYNTHETIC) as outside the scope.
// What a user reply must never carry: an administrator-only field (as src/contracts/user.ts lists them, and the
// newsroom's own), a model or provider name, money, a key, or the newsroom's operator records. A brief's own words may
// speak of costs or models, since the news is about them, so ordinary words are not searched for: only fields and
// markers are.
const ADMIN_ONLY = /"(model|provider|usage|input_tokens|output_tokens|max_tokens|cost_usd|usage_cost_usd|planning_estimate_usd|prices|request_sha256|prompt_version|preparation|guard|history|actor|prepared_by|idempotency_key|estimated_max_usd)":|claude|sonnet|opus|haiku|anthropic|\busd\b|x-api-key|sk-ant|synthetic-editor|curate-/i;
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const root = mkdtempSync(join(tmpdir(), "second-order-news-stories-"));
const served = join(root, "served");
const profile = join(root, "chrome");
const children = [];
const results = [];
let museumId = null;  // The SYNTHETIC story outside the scope, found on the desk.
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};

try {
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(python, [join(repo, "tests/news_desk_server.py"), "--root", served, "--port", String(port),
    "--simulated-provider", "--static-root", staticRoot], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  let started = false;
  for (let i = 0; i < 200 && !started; i++) {
    try { started = (await fetch(`${base}/api/session`)).ok; } catch { await sleep(200); }
  }
  if (!started) throw new Error("The server did not start.");
  const feedLog = join(served, "simulated-feeds", "requests.jsonl");
  const feedRequests = () => existsSync(feedLog) ? readFileSync(feedLog, "utf8").split("\n").filter(Boolean).length : 0;
  const providerSends = () => existsSync(join(served, "simulated-provider"))
    ? readdirSync(join(served, "simulated-provider")).filter((name) => /^request-\d+\.json$/.test(name)).length : 0;
  const feedsAtStart = feedRequests();
  check("a signed-out visitor's story read is refused before anything is read",
    (await fetch(`${base}/api/user/news/stories`)).status === 401);

  // ---------------------------------------------------------------- the browser
  const chrome = spawn(chromePath, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
    "--no-first-run", "--disable-gpu", "about:blank"], { stdio: "ignore" });
  children.push(chrome);
  let socketUrl;
  for (let i = 0; i < 150 && !socketUrl; i++) {
    try {
      const devtools = readFileSync(join(profile, "DevToolsActivePort"), "utf8").split("\n")[0].trim();
      socketUrl = (await (await fetch(`http://127.0.0.1:${devtools}/json/list`)).json())
        .find((target) => target.type === "page")?.webSocketDebuggerUrl;
    } catch { /* starting */ }
    if (!socketUrl) await sleep(200);
  }
  if (!socketUrl) throw new Error("Chrome's DevTools endpoint did not start.");
  const ws = new WebSocket(socketUrl);
  await new Promise((done) => ws.addEventListener("open", done, { once: true }));
  let counter = 0;
  const pending = new Map();
  const sent = [];
  const answered = new Map();
  const pageErrors = [];
  const outside = [];
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else if (message.method === "Network.requestWillBeSent") {
      const { url, method, postData } = message.params.request;
      if (!url.startsWith(base) && !url.startsWith("data:")) outside.push(url);
      sent.push({ id: message.params.requestId, url, method, postData: postData ?? "" });
    } else if (message.method === "Network.loadingFinished") {
      const request = sent.find((item) => item.id === message.params.requestId);
      if (request && /\/api\/user/.test(request.url)) {
        answered.set(request.id, send("Network.getResponseBody", { requestId: request.id })
          .then((body) => ({ path: new URL(request.url).pathname, text: body.body }), () => null));
      }
    } else if (message.method === "Runtime.exceptionThrown") {
      pageErrors.push(message.params.exceptionDetails.text);
    }
  });
  const send = (method, params = {}) => new Promise((done, fail) => {
    const id = ++counter;
    pending.set(id, (message) => message.error ? fail(new Error(message.error.message)) : done(message.result));
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) =>
    (await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })).result.value;
  const waitFor = async (expression, timeout = 10000) => {
    for (const start = Date.now(); Date.now() - start < timeout; await sleep(80)) {
      if (await evaluate(expression)) return true;
    }
    return false;
  };
  const setValue = (selector, value) => evaluate(`(() => {
    const element = document.querySelector(${JSON.stringify(selector)});
    if (!element) return false;
    const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
      : element instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value").set.call(element, ${JSON.stringify(value)});
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`);
  const click = (selector) => evaluate(`(() => { const e = document.querySelector(${JSON.stringify(selector)});
    if (!e) return false; e.click(); return true; })()`);
  const clickText = (selector, words) => evaluate(`(() => { const e = [...document.querySelectorAll(${JSON.stringify(selector)})]
    .find((item) => item.textContent.includes(${JSON.stringify(words)})); if (!e) return false; e.click(); return true; })()`);
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);
  const exists = (selector) => evaluate(`!!document.querySelector(${JSON.stringify(selector)})`);
  const path = () => evaluate("location.pathname");
  const open = async (address) => {
    await send("Page.navigate", { url: base + address });
    await waitFor("document.readyState === 'complete' && !document.querySelector('.shell-status')");
  };
  const shots = process.env.SECOND_ORDER_SCREENSHOTS;
  const shoot = async (name) => {  // Opt-in viewport captures; never a whole tall page.
    if (!shots) return;
    const shot = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(shots, `${name}.png`), Buffer.from(shot.data, "base64"));
  };
  const signIn = async (username) => {
    await open("/sign-in");
    await waitFor(`!!document.querySelector('.shell-form input[name="password"]')`);
    await setValue('.shell-form input[name="username"]', username);
    await setValue('.shell-form input[name="password"]', PASSWORDS[username]);
    await click(".shell-form button[type=submit]");
  };
  const apiGet = (address) => evaluate(`fetch("/api/session").then((reply) => reply.json())
    .then((session) => fetch(${JSON.stringify(address)}, { headers: { "X-Second-Order-Account": session.user.user_id } }))
    .then(async (reply) => ({ status: reply.status, body: await reply.json() }))`);
  const storyLink = (title) => `.news-story-title a`;
  const posts = () => sent.filter((item) => item.method === "POST" && item.url.startsWith(`${base}/api/`));

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  // 1. The News home is where a reader lands.
  await signIn("reader-a");
  check("the reader signs in and lands on the News home, Hot now, with News current in the navigation",
    await waitFor(`document.querySelector("main.page.client")?.dataset.view === "news" &&
      document.querySelector('.news-stories')?.dataset.view === "hot" && !!document.querySelector(".news-story")`, 15000) &&
    (await path()) === "/" && (await text("h1.client-title")) === "What is happening" &&
    (await evaluate(`document.querySelector('.site-nav a[href="/news"]')?.getAttribute("aria-current")`)) === "page");
  await shoot("news-home");
  const home = await evaluate(`[...document.querySelectorAll(".news-story")].map((row) => ({
    title: row.querySelector(".news-story-title")?.textContent, brief: row.dataset.brief,
    href: row.querySelector(".news-story-title a")?.getAttribute("href"), target: row.querySelector(".news-story-title a")?.target,
    summary: row.querySelector(".news-story-summary")?.textContent ?? null,
    excerpt: row.querySelector(".news-story-excerpt")?.textContent ?? null, lead: row.classList.contains("is-lead"),
    chips: [...row.querySelectorAll(".client-chip")].map((chip) => chip.textContent) }))`);
  check("the lead story is the newest development, and every story is marked as a synthetic example",
    home[0]?.lead && home[0].title === REVISION && home.every((row) => row.chips.includes("Synthetic example, not real news")),
    JSON.stringify(home.map((row) => row.title)));
  check("every headline opens the internal story page, never the publisher's",
    home.length >= 3 && home.every((row) => /^\/news\/stories\/story-[0-9a-f]{16}$/.test(row.href ?? "") && !row.target));
  const tariffRow = home.find((row) => row.title === TARIFF);
  check("a briefed story shows its brief's summary; a story without a brief says so and marks the feed excerpt",
    tariffRow?.brief === "published" && /15% tariff on imported steel/.test(tariffRow.summary ?? "") &&
    home.some((row) => row.brief === "none" && /feed excerpt, not the article/.test(row.excerpt ?? "")),
    JSON.stringify(home.map(({ title, brief, summary, excerpt }) => ({ title, brief, summary, excerpt }))));
  const cards = await evaluate(`[...document.querySelectorAll(".news-story")].map((row) => ({
    brief: row.dataset.brief, ready: row.classList.contains("has-brief"), compact: row.classList.contains("is-compact"),
    tag: row.querySelector("[data-brief-tag]")?.textContent ?? null, preview: row.querySelector("[data-brief-preview]")
      ?.textContent ?? null, state: row.querySelector("[data-state-tag]")?.textContent.trim() ?? null }))`);
  check("a ready brief stands out with a tag from its own record (who prepared it, whether an editor read it) and a preview; other headlines stay listed, compact, with their state",
    cards.filter((row) => row.brief === "published").every((row) => row.ready &&
      row.tag === "Brief · Synthetic example · not read by an editor" &&
      /Read the brief$/.test(row.preview ?? "")) &&
    cards.filter((row) => row.brief !== "published").every((row) => row.compact && /^(Awaiting a brief|Not enough material for a brief|Headline only.*|Brief withdrawn)$/.test(row.state ?? "")) &&
    cards.some((row) => row.brief === "published") && cards.some((row) => row.brief !== "published"),
    JSON.stringify(cards));
  const portRow = home.find((row) => row.title === PORT_STORY);
  check("a story whose feed's latest retrieval failed says it comes from an earlier retrieval",
    portRow?.chips.includes("From an earlier retrieval"), JSON.stringify(portRow));
  await click('.news-tabs a[href="/news/coverage"]');
  await waitFor(`document.querySelector('.news-stories')?.dataset.view === "coverage"`);
  const coverageView = (await apiGet("/api/user/news/stories?view=coverage")).body.stories;
  check("Most covered is a separate news view whose displayed order is the server's origin-based order",
    (await path()) === "/news/coverage" &&
    (await evaluate(`document.querySelector('.news-tabs a[href="/news/coverage"]')?.getAttribute("aria-current")`)) === "page" &&
    JSON.stringify(await evaluate(`[...document.querySelectorAll(".news-story")].map((row) => row.dataset.story)`)) ===
      JSON.stringify(coverageView.stories.map((row) => row.story_id)));
  check("the coverage view distinguishes copies and possible origins, and keeps a way back to single-source news",
    /Copies count once/.test(await text("[data-coverage-order]")) &&
    /confirmed and possible origins/.test(await text("[data-coverage-order]")) &&
    /worldwide popularity/.test(await text(".news-rank")) &&
    await exists('[data-coverage-order] a[href="/news"]'));
  await click('.news-tabs a[href="/news"]');
  await waitFor(`document.querySelector('.news-stories')?.dataset.view === "hot"`);
  check("returning to Hot now preserves its importance order and switching views sends no analysis",
    (await text(".news-story.is-lead .news-story-title")) === REVISION && providerSends() === 0);
  await click(".news-sources summary");
  check("Where the news comes from names each source's state, what it allows and its terms",
    await waitFor(`/Latest retrieval failed/.test(document.querySelector('.news-source-list [data-source="synthetic-gazette"]')?.textContent ?? "")`) &&
    /headlines and links only/.test(await text('.news-source-list [data-source="prnewswire-business"]')) &&
    /shown as the feed gives it; never summarised/.test(await text('.news-source-list [data-source="techcrunch"]')));
  check("Why it is here explains the ranking in words", /Latest report/.test(await text(".news-story.is-lead .news-why")));

  check("the News introduction says how briefs are prepared and never that editors wrote them",
    /how it was prepared \(by an editor, or with AI\) and whether an editor has read it/.test(await text("[data-lede]")) &&
    !/editors prepare/.test(await text("[data-lede]")));
  // 2. A story page.
  const before = { feeds: feedRequests(), sends: providerSends(), posts: posts().length,
                   account: (await apiGet("/api/user/account")).body.credits };
  await clickText(".news-story-title a", TARIFF);
  check("the headline opened the story page at its own address",
    await waitFor(`!!document.querySelector(".news-story-page .news-brief") && /^\\/news\\/stories\\/story-/.test(location.pathname)`));
  await shoot("news-story");
  const story = await evaluate(`({
    top: [...document.querySelectorAll("[data-explanation-top] h3")].map((h) => h.textContent),
    why: document.querySelector("[data-why]")?.textContent ?? "",
    who: document.querySelector("[data-who]")?.textContent ?? "",
    sections: [...document.querySelectorAll("[data-explanation-detail] > details")].map((d) => ({
      section: d.dataset.section, open: d.open, summary: d.querySelector("summary")?.textContent })),
    figure: document.querySelector("[data-figure='f1']")?.textContent ?? "",
    origins: document.querySelector("[data-origins-line]")?.textContent ?? "",
    parts: [...document.querySelectorAll(".news-brief-part h3")].map((h) => h.textContent),
    first: [...document.querySelectorAll(".news-brief > .news-brief-part h3")].map((h) => h.textContent),
    more: [...document.querySelectorAll(".news-brief-more .news-brief-part h3")].map((h) => h.textContent),
    moreOpen: document.querySelector(".news-brief-more")?.open,
    basedOn: document.querySelector("[data-brief-sources]")?.textContent ?? "",
    tag: document.querySelector("[data-authorship-tag]")?.textContent?.trim() ?? "",
    headline: document.querySelector(".news-brief-headline")?.textContent,
    provenance: document.querySelector("[data-provenance]")?.textContent ?? "",
    sources: [...document.querySelectorAll(".news-source-report")].map((row) => ({ use: row.dataset.use,
      href: row.querySelector(".news-source-title a")?.href, target: row.querySelector(".news-source-title a")?.target,
      rel: row.querySelector(".news-source-title a")?.rel, publisher: row.querySelector(".client-label")?.textContent })),
    coverage: document.querySelector("[data-coverage]")?.textContent ?? "",
    related: [...document.querySelectorAll(".news-related a")].map((a) => a.textContent),
    topic: document.querySelector('a[href^="/news/topics/topic-"]')?.getAttribute("href"),
    deeper: document.querySelector(".news-go-deeper")?.getAttribute("href") })`);
  check("the economic explanation's first read is what happened, why it matters economically, who may be affected and the main uncertainty",
    JSON.stringify(story.top) === JSON.stringify(["What happened", "Why it matters economically", "Who may be affected",
      "Main uncertainty"]) && /a duty of 15% on imported steel may raise costs/.test(story.why) &&
    story.who === "steel importers; steel-using manufacturers" && story.first.length === 0,
    JSON.stringify([story.top, story.why, story.who, story.first]));
  check("its mechanisms, knock-on effects, evidence, assumptions, alternatives, observables and background are expandable on the same page, closed at first",
    JSON.stringify(story.sections.map((row) => row.section)) === JSON.stringify(["channels", "second-order", "evidence",
      "assumptions", "alternatives", "watch", "background"]) && story.sections.every((row) => !row.open) &&
    /15%/.test(story.figure) && /quoted: “a 15% tariff on imported steel”/.test(story.figure), JSON.stringify(story.sections));
  const support = await evaluate(`({
    channels: [...document.querySelectorAll("[data-section='channels'] [data-support]")].map((row) => [row.dataset.support,
      row.textContent.replace(/\\s+/g, " ").trim()]),
    background: document.querySelector("[data-section='background'] [data-background]")?.dataset.background ?? null,
    outdated: !!document.querySelector("[data-explanation-note='outdated']") })`);
  check("each channel says what supports it, and the background shows the notes the explanation was prepared with",
    support.channels.length > 0 && support.channels.every(([kind, line]) => kind === "framework" &&
      /^Supported by: General economic reasoning: a sourced framework note\.$/.test(line)) &&
    support.background === "recorded" && !support.outdated, JSON.stringify(support));
  check("reporting origins keep confirmed apart from possible ones, in correct numbers",
    story.origins === "Reporting origins: 1 confirmed · 2 publishers", story.origins);
  check("the brief's headline and its sources are named",
    story.headline === "Synthetic Republic announces a 15% steel tariff" &&
    /^Based on Synthetic \w+ \[1\]; Synthetic \w+ \[2\]\.$/.test(story.basedOn.trim()) && story.tag === "Synthetic example · not read by an editor",
    JSON.stringify([story.first, story.basedOn, story.tag]));
  check("what was reported, kept apart from the implications, and the themes wait under More detail",
    JSON.stringify(story.more) === JSON.stringify(["What was reported", "Sectors, companies and themes"]) &&
    story.moreOpen === false, JSON.stringify(story.more));
  check("its provenance names the method, the version and what it rests on, and that the publications were not read",
    /SYNTHETIC example written for this demonstration/.test(story.provenance) && /Version 1, prepared/.test(story.provenance) &&
    /The full publications were not read/.test(story.provenance), story.provenance);
  check("each source opens its publisher's own https page in a new tab",
    story.sources.length === 2 && story.sources.every((row) => /^https:\/\/(ledger|courier)\.example\.org\/news\//.test(row.href ?? "") &&
      row.target === "_blank" && /noreferrer/.test(row.rel ?? "")), JSON.stringify(story.sources));
  check("publishers are counted apart from reporting origins: the wire copy counts once, with its origin",
    /2 reports from 2 publishers: 1 reporting origin \(1 newsroom\); 1 copy counted with its origin/.test(story.coverage),
    story.coverage);
  const origins = await evaluate(`[...document.querySelectorAll(".news-origins li")].map((row) => ({
    role: row.dataset.origin, independence: row.dataset.independence, text: row.textContent }))`);
  check("the story page lists its reporting origins, each with its publishers and kind",
    origins.length === 1 && origins[0].role === "news" && origins[0].independence === "established" &&
    /Synthetic Courier, Synthetic Ledger · a newsroom's own reporting · 2 reports counted together/.test(origins[0].text),
    JSON.stringify(origins));
  check("related developments and the ongoing topic are linked", story.related.includes("Tariff narrowed") &&
    story.related.includes("The Federation responds") && !!story.topic, JSON.stringify(story.related));
  const relevance = await evaluate(`({ state: document.querySelector(".news-relevance")?.dataset.relevance,
    summary: document.querySelector(".news-relevance summary")?.textContent ?? "",
    text: document.querySelector(".news-relevance")?.textContent ?? "",
    chips: [...document.querySelectorAll(".news-relevance-dimensions .client-chip")].map((chip) => chip.textContent) })`);
  check("the story says why it is in the economic news, who assessed it, and which dimensions its sources support",
    relevance.state === "relevant" && relevance.summary === "Why it is in the economic news" &&
    relevance.chips.includes("Trade") && /A SYNTHETIC assessment/.test(relevance.text) &&
    /not a measured market impact/.test(relevance.text), JSON.stringify(relevance));
  const after = { feeds: feedRequests(), sends: providerSends(), posts: posts().length,
                  account: (await apiGet("/api/user/account")).body.credits };
  check("reading the news and a story sent only reads: no feed request, no provider request, no credit used",
    JSON.stringify(after) === JSON.stringify(before) && before.feeds === feedsAtStart && before.sends === 0,
    JSON.stringify({ before, after }));

  // 3. The topic, the other views and an unusable story.
  await click(`a[href="${story.topic}"]`);
  check("the topic's timeline lists its developments in the order they happened",
    await waitFor(`document.querySelectorAll(".news-timeline li").length === 3`) &&
    JSON.stringify(await evaluate(`[...document.querySelectorAll(".news-timeline-label")].map((p) => p.textContent)`)) ===
      JSON.stringify(["Tariff announced", "The Federation responds", "Tariff narrowed"]));
  await open("/news/latest");
  check("Latest lists every story, newest first, and says when a time is only when this server first saw it",
    await waitFor(`document.querySelector('.news-stories')?.dataset.view === "latest" && document.querySelectorAll(".news-story").length >= 5`) &&
    /first seen by this server; the feed states no time/.test(await evaluate(`[...document.querySelectorAll(".news-story")]
      .find((row) => row.textContent.includes(${JSON.stringify(PORT_STORY)}))?.textContent ?? ""`)));
  check("Latest leaves out the story assessed as outside the economic news, and counts what it leaves out",
    !(await evaluate(`[...document.querySelectorAll(".news-story")].some((row) =>
      row.textContent.includes(${JSON.stringify(UNRELATED)}))`)) &&
    /^1 story was assessed as outside the economic news's scope/.test(await text("[data-left-out]")),
    await text("[data-left-out]"));
  await clickText(".news-tab", "Topics");
  check("Topics lists the ongoing topics", await waitFor(`!!document.querySelector('[data-topics="1"] .news-topic')`) &&
    (await path()) === "/news/topics");
  await clickText(".news-tab", "Your interests");
  check("Your interests says that none is chosen yet, and selects nothing",
    await waitFor(`document.querySelector('.news-stories')?.dataset.view === "interests"`) &&
    /You have not chosen interests yet/.test(await text(".news-stories")) && !(await exists(".news-story")));
  await open("/news/latest");
  await waitFor(`!!document.querySelector(".news-story")`);
  await clickText(".news-story-title a", PORT_STORY);
  check("a story whose reports state no time offers no deeper analysis, and says why",
    await waitFor(`!!document.querySelector("[data-deeper-reason]")`) && !(await exists(".news-go-deeper")) &&
    /states a publication time/.test(await text("[data-deeper-reason]")) &&
    /No brief has been prepared/.test(await text("[data-brief-note]")));

  // 4. Go deeper.
  await open(new URL(story.deeper, base).pathname.replace(/\/deeper$/, ""));
  await waitFor(`!!document.querySelector(".news-go-deeper")`);
  await click(".news-go-deeper");
  check("Go deeper shows what it uses, the exact text and an Effort, and has sent nothing yet",
    await waitFor(`!!document.querySelector("[data-material-statement]") && !!document.querySelector('.client-efforts input[name="effort"]')`) &&
    /The full publications were not read/.test(await text("[data-material-statement]")) &&
    /not the publication/.test(await evaluate(`document.querySelector("[data-source-text]")?.textContent ?? ""`)) &&
    posts().length === before.posts);
  const stages = await evaluate(`[...document.querySelectorAll("[data-deeper-stages] li")].map((row) => ({
    stage: row.dataset.stage, ready: row.dataset.ready }))`);
  check("Go deeper says which stages this server is ready for: prepare, quote and run",
    JSON.stringify(stages) === JSON.stringify([{ stage: "prepare", ready: "true" }, { stage: "quote", ready: "true" },
      { stage: "run", ready: "true" }]) && /basis|Headline/.test(await text("[data-material-basis]")),
    JSON.stringify(stages));
  await shoot("news-deeper");
  await click(".news-prepare-deeper");
  check("one explicit Prepare saves the reader's own source, prepares the analysis and opens it",
    await waitFor(`/^\\/analyses\\//.test(location.pathname) && !!document.querySelector("main.page.client[data-view=analysis]")`, 15000) &&
    posts().filter((item) => /\/deeper$/.test(item.url)).length === 1);
  const analysisPath = await path();
  check("the analysis page asks for a credit quote; nothing was quoted, sent or charged",
    await waitFor(`[...document.querySelectorAll("button")].some((b) => /quote/i.test(b.textContent))`) &&
    providerSends() === 0 && posts().every((item) => !/\/(quotes|runs)$/.test(item.url)) &&
    JSON.stringify((await apiGet("/api/user/account")).body.credits) === JSON.stringify(before.account));
  const limits = Object.fromEntries((await apiGet("/api/user/limits")).body.limits.operations
    .map((row) => [row.operation, row.used]));
  check("it counted one new source and one prepared analysis", limits.source === 1 && limits.preparation === 1 &&
    limits.search === 0, JSON.stringify(limits));
  // The rest of the reader's path, against the SIMULATED provider: a quote, the reader's explicit approval, one send
  // and the private result. Nothing here is a real request.
  const creditsBefore = (await apiGet("/api/user/account")).body.credits.available;
  await click(".client-get-quote");
  check("the credit quote names the exact credits; the approval starts unchecked and nothing is sent",
    await waitFor(`!!document.querySelector(".client-approve input")`) &&
    !(await evaluate(`document.querySelector(".client-approve input").checked`)) &&
    (await evaluate(`document.querySelector(".client-run").disabled`)) && providerSends() === 0 &&
    posts().filter((item) => /\/quotes$/.test(item.url)).length === 1 &&
    /never charged more than \d+ credits/.test(await text(".client-approve")), await text(".client-approve"));
  const quoted = Number((/never charged more than (\d+) credits/.exec(await text(".client-approve")) ?? [])[1]);
  await click(".client-approve input");
  await click(".client-run");
  check("one explicit approval sends the analysis once (simulated) and shows the reader's private result",
    await waitFor(`!!document.querySelector(".client-outcome")`, 30000) && providerSends() === 1 &&
    posts().filter((item) => /\/runs$/.test(item.url)).length === 1 &&
    (await evaluate(`document.querySelectorAll("[data-statement]").length`)) > 0, String(providerSends()));
  const captions = await evaluate(`[...document.querySelectorAll(".client-quote-figure figcaption")].map((row) =>
    row.textContent)`);
  check("each quote of the deeper analysis is a publisher's own words, located in its report (deeper-evidence-0.1)",
    captions.length > 0 && captions.every((caption) =>
      /Report \d+, [^,]+, its (headline|feed excerpt|publication text)/.test(caption)), JSON.stringify(captions));
  const creditsAfter = (await apiGet("/api/user/account")).body.credits.available;
  check("the account was charged exactly the quoted credits, and nothing else was sent",
    quoted > 0 && creditsBefore - creditsAfter === quoted && providerSends() === 1, JSON.stringify({ creditsBefore,
      creditsAfter, quoted }));
  await shoot("news-deeper-result");
  await open(new URL(story.deeper, base).pathname);
  check("going back shows the source and analysis already made from this material",
    await waitFor(`!!document.querySelector("[data-existing]")`) && (await exists(`[data-existing] a[href="${analysisPath}"]`)));

  // 5. Addresses and the wordmark.
  await open("/analyses");
  check("Your analyses opens at /analyses and lists the new one",
    await waitFor(`document.querySelectorAll(".client-history-row").length === 1`));
  await click(".wordmark");
  check("the wordmark leads to the News home", await waitFor(`location.pathname === "/news" && !!document.querySelector(".news-story")`));
  await open(analysisPath);
  check("an analysis opens by its address", await waitFor(`document.querySelector("main.page.client")?.dataset.view === "analysis"`));
  await open("/news/reports");
  check("Reports & search keeps the feed entries, interests and search",
    await waitFor(`!!document.querySelector(".client-search") && !!document.querySelector(".client-interests")`) &&
    /Reports from the official feeds/.test(await text("h1.client-title")));

  // 6. Phone width.
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  const widths = {};
  for (const address of ["/news", new URL(story.deeper, base).pathname.replace(/\/deeper$/, ""), story.topic]) {
    await open(address);
    await waitFor(`!!document.querySelector(".news-story, .news-brief, .news-timeline")`);
    widths[address] = await evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth");
  }
  check("at phone width the News home, a story and a topic need no sideways scrolling",
    Object.values(widths).every(Boolean), JSON.stringify(widths));
  await shoot("news-phone");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  // 7. The administrator's News desk.
  await click(".account-strip button");
  await waitFor(`!!document.querySelector('[data-public="landing"], .shell-form')`);
  await signIn("admin");
  await waitFor(`!!document.querySelector(".admin-bar")`, 15000);
  await open("/admin/news");
  check("the News desk shows the registry, with what each publisher allows and needs",
    await waitFor(`!!document.querySelector('[data-news="registry"] [data-publisher="reuters"]')`, 15000) &&
    (await evaluate(`document.querySelector('[data-publisher="techcrunch"]')?.dataset.status`)) === "connected" &&
    (await evaluate(`document.querySelector('[data-publisher="reuters"]')?.dataset.status`)) === "needs_agreement");
  await shoot("news-desk");
  check("the desk's coverage says how many important stories have a current brief, and why the others do not",
    await waitFor(`!!document.querySelector("[data-coverage-summary]") && document.querySelectorAll("[data-coverage-story]").length > 0`, 15000) &&
    /important stories with summarisable material have a current brief/.test(await text("[data-coverage-summary]")) &&
    (await evaluate(`[...document.querySelectorAll("[data-coverage-story]")].every((row) => !!row.dataset.state)`)));
  const sentBefore = posts().length;
  await setValue("[data-batch-panel] select", "assisted");
  await clickText("[data-batch-panel] button", "Preview the batch");
  check("an assisted batch preview lists the stories that need a brief and sends nothing to a model",
    await waitFor(`!!document.querySelector("[data-batch] [data-batch-item]")`, 15000) &&
    posts().length === sentBefore + 1 && /news batch import/.test(await text("[data-batch]")) &&
    !(await exists("[data-batch] .admin-attention")));
  const matching = await evaluate(`document.querySelector("[data-suggestions]")?.parentElement?.textContent ?? document.body.textContent`);
  check("the desk explains suggested matches and their three decisions, and says when no pair shares names or figures",
    /Same development: the later story merges into the earlier one/.test(matching) &&
    (/No pair of current stories shares distinctive names or figures/.test(matching) ||
      /shared names: .*figures: /.test(matching)), matching.slice(0, 300));
  check("the desk's relevance panel counts current stories by state and says who decided each, and why",
    await waitFor(`!!document.querySelector("[data-relevance-panel] [data-relevance-counts]") &&
      !!document.querySelector('[data-relevance-panel] tr[data-relevance="outside_scope"]')`, 15000) &&
    /outside the scope/.test(await text("[data-relevance-counts]")) &&
    /SYNTHETIC/.test(await text('[data-relevance-panel] tr[data-relevance="outside_scope"]')));
  museumId = await evaluate(`document.querySelector('[data-relevance-panel] tr[data-relevance="outside_scope"]')
    ?.dataset.relevanceStory ?? null`);
  await evaluate(`document.querySelector('[data-relevance-panel] tr[data-relevance="outside_scope"] .admin-link')?.click()`);
  await waitFor(`!!document.querySelector('[data-judge="${museumId}"] input')`);
  await setValue(`[data-judge="${museumId}"] input`, "SYNTHETIC: a museum opening; checked by an editor");
  await clickText(`[data-judge="${museumId}"] button`, "Record");
  check("an editor's judgement is recorded with its reason, and the queue then names the editor as deciding",
    await waitFor(`/editor/.test(document.querySelector('[data-relevance-panel] tr[data-relevance-story="${museumId}"]')
      ?.textContent ?? "") && /checked by an editor/.test(document.querySelector('[data-relevance-panel] tr[data-relevance-story="${museumId}"]')
      ?.textContent ?? "")`, 10000));
  const revisionPanel = `[data-desk-story]`;
  await evaluate(`[...document.querySelectorAll(${JSON.stringify(revisionPanel)})].find((row) =>
    row.querySelector("summary")?.textContent.includes(${JSON.stringify(REVISION)}))?.setAttribute("open", "")`);
  const panel = `[data-desk-story][open]`;
  await clickText(`${panel} button`, "Start from the reports' own words");
  check("a $0 draft from the reports' own words fills the editor and records nothing",
    await waitFor(`/\\[1\\]$/.test(document.querySelector("${panel} .admin-brief-editor textarea")?.value ?? "") ||
      [...document.querySelectorAll("${panel} .admin-brief-editor textarea")].some((t) => /\\[1\\]/.test(t.value))`));
  await setValue(`${panel} .admin-brief-editor label:nth-of-type(4) textarea`,
    "SYNTHETIC: exempted steel grades could cost buyers less if the change takes effect.");
  await setValue(`${panel} .admin-brief-editor label:nth-of-type(6) textarea`, "Which grades are exempted is not stated.");
  await setValue(`${panel} .admin-form input`, "SYNTHETIC: checked against the reports");
  await clickText(`${panel} button`, "Save as version 1");
  check("saving makes version 1, and the guard finds nothing to stop it",
    await waitFor(`!!document.querySelector('${panel} [data-versions] [data-version="1"] .admin-ok')`, 10000));
  await setValue(`${panel} .admin-form input`, "SYNTHETIC: checked against the reports");
  await clickText(`${panel} [data-version="1"] button`, "Publish");
  check("publishing it is one explicit action",
    await waitFor(`/published/.test(document.querySelector('${panel} [data-version="1"]')?.textContent ?? "")`, 10000));
  await evaluate(`[...document.querySelectorAll(".admin-bar button")].find((b) => b.textContent.includes("Sign out"))?.click()`);
  await waitFor(`!document.querySelector(".admin-bar")`);
  await signIn("reader-a");
  await waitFor(`!!document.querySelector(".news-story")`, 15000);
  check("the reader now reads the editors' brief of that story",
    await waitFor(`[...document.querySelectorAll(".news-story")].some((row) => row.textContent.includes(${JSON.stringify(REVISION)}) &&
      row.dataset.brief === "published")`));
  await open(`/news/stories/${museumId}`);
  check("a story outside the economic news keeps its page, says an editor judged it and why, and offers no deeper analysis",
    await waitFor(`document.querySelector(".news-relevance")?.dataset.relevance === "outside_scope"`) &&
    /Not in the economic news/.test(await text(".news-relevance summary")) &&
    /Judged by an editor/.test(await text(".news-relevance")) && /checked by an editor/.test(await text(".news-relevance")) &&
    !(await exists(".news-go-deeper")) && /outside the economic news's scope/.test(await text("[data-deeper-reason]")));

  // 8. Payloads, storage and requests.
  const payloads = (await Promise.all([...answered.values()])).filter(Boolean);
  const leaks = payloads.filter(({ text: body }) => ADMIN_ONLY.test(body));
  check("no user reply carried an administrator's field, a model or provider name, money or an operator's record",
    payloads.length > 10 && leaks.length === 0,
    leaks.map(({ path: where, text: body }) => `${where}: ${body.match(ADMIN_ONLY)?.[0]}`).slice(0, 5).join(" | "));
  const stored = await evaluate(`JSON.stringify({ local: Object.entries(localStorage), session: Object.entries(sessionStorage) })`);
  check("nothing was left in browser storage", stored === '{"local":[],"session":[]}', stored);
  check("the browser requested nothing outside the local server", outside.length === 0, outside.join(", "));
  check("the server's simulated feeds were requested only at startup", feedRequests() === feedsAtStart);
  check("no page error", pageErrors.length === 0, pageErrors.join(" | "));
  ws.close();
} catch (error) {
  check("the news journey ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(600);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
