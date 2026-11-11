// QA: the current-news journey end to end on the BUILT Client and Admin, in one headless Chrome against the REAL server
// (tests/review_browser_server.py --accounts fresh --simulated-provider --news retained), over COPIES of a RETAINED real
// retrieval: the data owner's 14 October 2026 smoke run (its Event Inbox cache and the one Federal Reserve press-release
// page it kept). Written by the QA chat for the combined local-live gate; nothing here is mocked.
//
// What is real: the feeds' cached entries and the kept page's bytes and retrieval record, copied twice (into this
// check's temporary folder, then by the launcher into the served folder); the run folder given on the command line is
// only read, and every file in it is compared by SHA-256 before and after. Nothing is requested: the launcher's
// publisher refuses and records every request, its feed fetcher refuses every request, and the served Event Inbox copy
// must be byte-identical at the end. What is synthetic: the accounts, passwords, credit and usage terms (typed by this
// check's administrator; no production value was selected), the server's clock (the machine's) and the model, a fake
// sender that answers the one approved run with a reply quoting the request's own text. Nothing measures a model.
//
// The journey: the administrator publishes the selected pilot credit terms -> a visitor registers -> pending (status
// only, no session) -> the administrator approves, then grants credits and sets a daily limit as two actions -> the
// user's news is refused while no usage limits exist, counting nothing -> the administrator publishes usage limits ->
// the news of every topic as the server reports it: each feed's state, coverage, the feed's own publication times apart
// from retrieval times (stated, date-only and unknown), excerpts marked -> a filter that sends nothing -> an
// unsupported entry offers the paste step, filled only with what the feed states -> interests saved, the news follows
// them -> one deliberate, counted search -> a search whose reply is lost after the server counted it (dropped in the
// browser by DevTools request interception), repeated with the same key and not counted again -> the kept page's import
// preview: the exact text the server proposes, where it came from (a kept copy, retrieved 14 October; nothing
// requested), the feed's publication time, what was left out and the documents only named (the linked PDF is not
// retrieved) -> saved only on explicit confirmation of that text, and confirming again saves nothing new -> Effort,
// prepare, quote, explicit approval -> one send to the fake, of the
// confirmed text -> the result, its research checks (research-quality-0.3) shown as checks to examine, exactly as the
// API serves them, with their limits and no score or pass mark -> the user's own review, the
// history and the export -> today's counts as the server reports them, the server's publication fetches unused -> the
// browser signed in to another account without any announcement: the next search is refused before it counts and the
// tab stops. Then: no request left the machine, no administrator field reached a user reply, nothing in browser storage.
//
//   cd frontend; npm run build; node tests/browser/qa-news-journey-check.mjs <retained run folder>
//   (or SECOND_ORDER_NEWS_RECORDS=<folder>; it must hold event-inbox/ and imports/raw/, imports/retrievals/)
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const python = process.env.SECOND_ORDER_PYTHON ?? "python";
const chromePath = [process.env.SECOND_ORDER_CHROME, "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
  "/usr/bin/chromium-browser"].find((path) => path && existsSync(path));
if (!chromePath) throw new Error("Chrome was not found; set SECOND_ORDER_CHROME to its executable.");
for (const built of ["frontend/dist/index.html", "frontend/dist-client/client.html"]) {
  if (!existsSync(join(repo, built))) throw new Error("Build both clients first: npm run build");
}
const records = process.argv[2] ?? process.env.SECOND_ORDER_NEWS_RECORDS;
if (!records || !existsSync(join(records, "event-inbox")) || !existsSync(join(records, "imports", "retrievals"))) {
  console.log("This check needs a retained retrieval (a folder with event-inbox/ and imports/retrievals/), given as its " +
    "argument or SECOND_ORDER_NEWS_RECORDS. It requests nothing itself.");
  process.exit(1);
}

const USAGE_LIMITS = {  // SYNTHETIC values typed by the check's administrator; a real server's are the operator's.
  searches_per_day: "50", imports_per_day: "10", sources_per_day: "60", preparations_per_day: "60", max_sources: "500",
  max_source_bytes: "60000000", requests_per_minute: "600", concurrent_requests: "16",
  publication_fetches_per_day: "20", refreshes_per_day: "20", refresh_cooldown_seconds: "0",
};
const PASSWORDS = { admin: "synthetic-admin-pass", "reader-a": "synthetic-reader-a", "reader-n": "synthetic-reader-n-news" };
// Fields only an administrator's payload may carry, matched as JSON keys: the retained publication's own words (which
// may say "costs" or "model") are the source, not a leak.
const ADMIN_KEYS = /^(model|provider|usd|cost|costs|tokens|input_tokens|output_tokens|request_id|http_status|elapsed|thinking|pid|prompt|planning|api_key)$/i;
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const digests = (folder) => {
  const out = {};
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) walk(path);
      else out[relative(folder, path).replaceAll("\\", "/")] = createHash("sha256").update(readFileSync(path)).digest("hex");
    }
  };
  walk(folder);
  return out;
};
const same = (a, b) => JSON.stringify(Object.entries(a).sort()) === JSON.stringify(Object.entries(b).sort());
const keysIn = (value, found = []) => {
  if (Array.isArray(value)) value.forEach((item) => keysIn(item, found));
  else if (value && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) { found.push(key); keysIn(item, found); }
  }
  return found;
};

const root = mkdtempSync(join(tmpdir(), "second-order-qa-news-journey-"));
const served = join(root, "served");
const copied = join(root, "records");
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const runBefore = digests(records);

try {
  // ---------------------------------------------------------------- copies of the retained retrieval, and the server
  mkdirSync(served);
  cpSync(join(records, "event-inbox"), join(copied, "event-inbox"), { recursive: true });
  for (const part of ["raw", "retrievals"]) {
    if (existsSync(join(records, "imports", part))) {
      cpSync(join(records, "imports", part), join(copied, "imports", part), { recursive: true });
    }
  }
  const kept = JSON.parse(readFileSync(join(copied, "imports", "retrievals", "000001.json"), "utf8"));
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    "--accounts", "fresh", "--simulated-provider", "--news", "retained", "--news-records", copied],
  { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  let started = false;
  for (let i = 0; i < 150 && !started; i++) {
    try { started = (await fetch(`${base}/api/session`)).ok; } catch { await sleep(200); }
  }
  if (!started) throw new Error("The server did not start.");
  const inboxAtStart = digests(join(served, "event-inbox"));
  const publisherLog = join(served, "simulated-publisher", "requests.jsonl");

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
  const statuses = new Map();
  const answered = new Map();
  const pageErrors = [];
  const outside = [];
  const dropped = [];
  let dropSearches = 0;  // Replies to drop after the server answered, as a connection lost on the way back would.
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else if (message.method === "Network.requestWillBeSent") {
      const { url, method, postData, headers } = message.params.request;
      if (!url.startsWith(base) && !url.startsWith("data:")) outside.push(url);
      sent.push({ id: message.params.requestId, url, path: url.startsWith(base) ? new URL(url).pathname : url, method,
                  postData: postData ?? "", bound: headers["X-Second-Order-Account"] ?? null });
    } else if (message.method === "Network.responseReceived") {
      statuses.set(message.params.requestId, message.params.response.status);
    } else if (message.method === "Network.loadingFinished") {
      const request = sent.find((item) => item.id === message.params.requestId);
      if (request && /\/api\/(user|public|session)/.test(request.url)) {
        answered.set(request.id, send("Network.getResponseBody", { requestId: request.id })
          .then((body) => ({ path: request.path, text: body.body }), () => null));
      }
    } else if (message.method === "Runtime.exceptionThrown") {
      pageErrors.push(message.params.exceptionDetails.text);
    } else if (message.method === "Fetch.requestPaused") {
      const { requestId } = message.params;
      if (dropSearches > 0) {
        dropSearches -= 1;
        dropped.push(message.params.request.url);
        send("Fetch.failRequest", { requestId, errorReason: "ConnectionClosed" });
      } else send("Fetch.continueRequest", { requestId });
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
  const count = (selector) => evaluate(`document.querySelectorAll(${JSON.stringify(selector)}).length`);
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete' && !document.querySelector('.shell-status')");
  };
  const writes = (fragment = "") => sent.filter((item) => item.method === "POST" && item.path.startsWith("/api/user/") &&
    item.path.includes(fragment));
  const newsReady = () => waitFor(`!!document.querySelector(".client-news [data-news-count]") && !document.querySelector(".client-news .client-status")`, 15000);
  const signIn = async (username, password = PASSWORDS[username]) => {
    await open("/sign-in");
    await waitFor(`!!document.querySelector('.shell-form input[name="password"]')`);
    await setValue('.shell-form input[name="username"]', username);
    await setValue('.shell-form input[name="password"]', password);
    await click(".shell-form button[type=submit]");
  };
  const signInClient = async (username) => {
    await signIn(username);
    // A reader lands on the News home (docs/news-stories-contract.md section 7); Your analyses, with the account's
    // allowance, is at /analyses.
    if (!await waitFor(`document.querySelector("main.page.client")?.dataset.view === "news" &&
      !document.querySelector(".admin-bar")`, 15000)) return false;
    await open("/analyses");
    return waitFor(`!!document.querySelector("main.page.client .client-entitlements dd")`, 15000);
  };
  const signInAdmin = async () => {
    await signIn("admin");
    return waitFor(`!!document.querySelector(".admin-bar")`, 15000);
  };
  const signOutClient = async () => {
    await click(".account-strip button");
    return waitFor(`!!document.querySelector('[data-public="landing"], .shell-form')`);
  };
  const signOutAdmin = async () => {
    await clickText(".admin-bar button", "Sign out");
    return waitFor(`!document.querySelector(".admin-bar")`);
  };
  // As the pages do, every call names the account the page is signed in as (docs/account-binding-contract.md).
  const call = (path, role = "user") => evaluate(`fetch("/api/session").then((reply) => reply.json())
    .then((session) => fetch(${JSON.stringify(path)}, { headers: { "X-Second-Order-Account": session.user.user_id } }))
    .then(async (reply) => ({ status: reply.status, body: await reply.json() }))`);
  const userPost = (path, body) => evaluate(`fetch("/api/session").then((reply) => reply.json())
    .then((session) => fetch(${JSON.stringify(path)}, { method: "POST", headers: { "Content-Type": "application/json",
      "X-Second-Order-User": "1", "X-Second-Order-Account": session.user.user_id }, body: ${JSON.stringify(JSON.stringify(body))} }))
    .then(async (reply) => ({ status: reply.status, body: await reply.json() }))`);
  const usedToday = async (operation) => (await call("/api/user/limits")).body.limits.operations
    .find((row) => row.operation === operation)?.used;
  const providerSends = () => existsSync(join(served, "simulated-provider"))
    ? readdirSync(join(served, "simulated-provider")).filter((name) => /^request-\d+\.json$/.test(name)) : [];
  const usedBy = (usage, userId, operation) => {
    const row = usage.accounts.find((account) => account.user_id === userId);
    const operations = row?.operations ?? [];
    const found = Array.isArray(operations) ? operations.find((item) => item.operation === operation) : operations[operation];
    return found?.used ?? (typeof found === "number" ? found : 0);
  };

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  // 1. The administrator publishes the selected pilot credit terms (the public journey checks these terms in full).
  check("the administrator signs in and is handed the Admin build", await signInAdmin());
  await open("/admin/policy");
  await waitFor(`!!document.querySelector('[data-preset="pilot-flat-1"] button')`);
  await click('[data-preset="pilot-flat-1"] button');
  for (const [name, typed] of [["max_request_usd", "1"], ["quote_valid_seconds", "900"],
    ["reason", "SYNTHETIC: the selected pilot terms, with a test planning limit"]]) {
    await setValue(`form[aria-label="New policy version"] input[name="${name}"]`, typed);
  }
  await click('form[aria-label="New policy version"] button[type=submit]');
  check("the pilot credit terms are published as the first policy version",
    await waitFor(`document.querySelector("[data-policy]")?.dataset.policy === "credit-policy-1"`));
  await signOutAdmin();

  // 2. Registration and the pending state.
  await open("/register");
  await waitFor(`!!document.querySelector(".public-register")`);
  for (const [name, typed] of Object.entries({ username: "reader-n", display_name: "Reader N (synthetic)",
    password: PASSWORDS["reader-n"], repeat: PASSWORDS["reader-n"], note: "SYNTHETIC registration for the QA news journey" })) {
    await setValue(`.public-register [name="${name}"]`, typed);
  }
  await click(".public-register button[type=submit]");
  check("a visitor registers once and the server records it as pending",
    await waitFor(`!!document.querySelector('[data-public="registered"]')`) &&
    writes().length === 0 && sent.filter((item) => item.method === "POST" && item.path === "/api/public/registrations").length === 1);
  await signIn("reader-n");
  check("signing in while pending shows only the registrant's own status, with no session",
    await waitFor(`/waiting for approval/i.test(document.querySelector('[data-public="status"]')?.textContent ?? "")`) &&
    (await send("Network.getCookies", { urls: [base] })).cookies.length === 0);

  // 3. Approval, then the allocation as two separate actions.
  await signInAdmin();
  await open("/admin/registrations");
  await waitFor(`!!document.querySelector('form[aria-label="Decision on reader-n"]')`);
  await setValue('form[aria-label="Decision on reader-n"] input[name="reason"]', "SYNTHETIC approval in the QA news journey");
  await click('form[aria-label="Decision on reader-n"] button[type=submit]');
  await waitFor(`!document.querySelector('form[aria-label="Decision on reader-n"]')`);
  const users = (await call("/api/admin/users")).body.users;
  const readerId = users.find((user) => user.username === "reader-n")?.user_id;
  const otherId = users.find((user) => user.username === "reader-a")?.user_id;
  check("the administrator approves the registration; nothing is allocated by it",
    users.find((user) => user.username === "reader-n")?.status === "active" &&
    users.find((user) => user.username === "reader-n")?.allocated === false);
  await open("/admin");
  await waitFor(`!!document.querySelector('tr[data-user="reader-n"] .admin-link')`);
  await click('tr[data-user="reader-n"] .admin-link');
  await waitFor(`!!document.querySelector('[data-preset="pilot-initial-1"] button')`);
  await click('[data-preset="pilot-initial-1"] button');
  await setValue('form[aria-label="Credits for reader-n"] input[name="reason"]', "SYNTHETIC initial grant in the QA news journey");
  await click('form[aria-label="Credits for reader-n"] button[type=submit]');
  const granted = await waitFor(`document.querySelector('tr[data-user="reader-n"] [data-field="available"]')?.textContent === "100"
    && !!document.querySelector('form[aria-label="Daily limit for reader-n"]')`);
  await setValue('form[aria-label="Daily limit for reader-n"] input[name="reason"]', "SYNTHETIC initial limit in the QA news journey");
  await click('form[aria-label="Daily limit for reader-n"] button[type=submit]');
  check("the administrator grants 100 credits and then sets a daily limit of 3, as two actions", granted &&
    await waitFor(`document.querySelector('tr[data-user="reader-n"] [data-field="limit"]')?.textContent === "3"`));
  await signOutAdmin();

  // 4. No usage limits yet: the news is refused and nothing is counted.
  check("the approved user signs in to the Client", await signInClient("reader-n"));
  await open("/news/reports");
  const refusedShown = await waitFor(`!!document.querySelector('[data-code="no_usage_policy"]')`, 15000);
  check("with no usage limits on this server, the news is refused as not available yet (its first read, 409), and " +
    "nothing is written", refusedShown && writes().length === 0 &&
    sent.some((item) => item.path.startsWith("/api/user/news") && statuses.get(item.id) === 409),
    JSON.stringify({ refusedShown, reads: sent.filter((item) => item.path.startsWith("/api/user/")).map((item) =>
      `${item.method} ${item.path} ${statuses.get(item.id)}`), codes: await evaluate(`[...document.querySelectorAll("[data-code]")]
      .map((e) => e.dataset.code)`), main: (await text("main")).slice(0, 400) }));
  await signOutClient();
  await signInAdmin();
  await open("/admin/usage");
  check("the Usage & limits screen says no usage limits are set",
    await waitFor(`document.querySelector("[data-usage-policy]")?.dataset.usagePolicy === "none"`));
  const nothingCounted = (await call("/api/admin/usage")).body;
  check("the refused news read counted nothing", ["search", "import", "source", "preparation"].every((operation) =>
    usedBy(nothingCounted, readerId, operation) === 0) &&
    nothingCounted.server.publication_fetches.used === 0, JSON.stringify(nothingCounted.accounts));
  for (const [name, typed] of Object.entries(USAGE_LIMITS)) {
    await setValue(`form[aria-label="New usage limits"] input[name="${name}"]`, typed);
  }
  await setValue('form[aria-label="New usage limits"] input[name="reason"]', "SYNTHETIC usage limits in the QA news journey");
  await click('form[aria-label="New usage limits"] button[type=submit]');
  check("the administrator publishes usage limits, as its own action",
    await waitFor(`document.querySelector("[data-usage-policy]")?.dataset.usagePolicy === "usage-policy-1"`));
  await signOutAdmin();

  // 5. The news of every topic, from the retained retrieval, as the server reports it.
  check("signed in again, the user's account is ready", await signInClient("reader-n"));
  const beforeNews = sent.length;
  await open("/news/reports");
  check("the news opens on every topic (no interests chosen yet)", await newsReady() &&
    (await evaluate(`document.querySelector(".client-news")?.dataset.scope`)) === "all");
  const opening = sent.slice(beforeNews).filter((item) => item.path.startsWith("/api/user/"));
  check("opening the news sends only reads, each naming the user's account",
    opening.length >= 3 && opening.every((item) => item.method === "GET" && item.bound === readerId),
    JSON.stringify(opening.map((item) => `${item.method} ${item.path}`)));
  const all = (await call("/api/user/news?scope=all")).body.news;
  check("every entry the server lists from the retained cache is shown, in its order",
    all.entries.length > 20 && JSON.stringify(await evaluate(`[...document.querySelectorAll(".client-news-entry")]
      .map((e) => e.dataset.entry)`)) === JSON.stringify(all.entries.map((entry) => entry.entry_id)), String(all.entries.length));
  const feeds = await evaluate(`[...document.querySelectorAll(".client-feed-list li")].map((li) => ({ source: li.dataset.source,
    state: li.dataset.state, text: li.querySelector(".client-feed-state")?.textContent ?? "" }))`);
  check("each feed's state is the retained one: BLS not requested; Federal Reserve, EIA and WTO retrieved on 14 October",
    feeds.filter((feed) => feed.source.startsWith("bls")).every((feed) => feed.state === "not_requested") &&
    feeds.filter((feed) => !feed.source.startsWith("bls")).every((feed) => feed.state === "ok" &&
      feed.text.startsWith("Retrieved 14 Oct 2026")) && feeds.length === all.sources.length, JSON.stringify(feeds));
  check("the page says what it covers and that it is not all news",
    (await text(".client-news-sources")).includes("It is not all news."));
  const times = await evaluate(`[...document.querySelectorAll(".client-news-entry")].map((e) => ({ id: e.dataset.entry,
    published: e.dataset.published, line: e.querySelector(".client-news-times")?.textContent ?? "" }))`);
  const byId = Object.fromEntries(all.entries.map((entry) => [entry.entry_id, entry]));
  check("each entry's publication time is the feed's own state, shown apart from when this server retrieved it",
    times.every((row) => row.published === byId[row.id].published.state && row.line.includes("Retrieved 14 Oct 2026")),
    JSON.stringify(times.filter((row) => row.published !== byId[row.id].published.state || !row.line.includes("Retrieved 14 Oct 2026")).slice(0, 3)));
  const shownTimes = await evaluate(`[...document.querySelectorAll(".client-news-entry")].map((e) => ({
    state: e.dataset.published, line: e.querySelector(".client-news-published")?.textContent ?? "",
    note: e.querySelector(".client-news-time-note")?.textContent ?? "" }))`);
  const timesIn = (state) => shownTimes.filter((row) => row.state === state);
  check("stated times are shown in the quota zone; date-only entries keep the feed's date and say it states no time " +
    "of day; unusable timestamps are shown as unknown, with the feed's reason",
    timesIn("stated").length > 0 && timesIn("stated").every((row) =>
      /^Published \d+ \w{3} 2026, \d\d:\d\d \(Asia\/Jerusalem\)$/.test(row.line)) &&
    timesIn("date_only").length > 0 && timesIn("date_only").every((row) =>
      /^Published \d+ \w{3} 2026; the feed states no time of day$/.test(row.line)) &&
    timesIn("unstated").length > 0 && timesIn("unstated").every((row) =>
      row.line.startsWith("Publication time unknown") && row.note.length > 0) &&
    timesIn("stated").length + timesIn("date_only").length + timesIn("unstated").length === shownTimes.length,
    JSON.stringify(["stated", "date_only", "unstated"].map((state) => [state, timesIn(state).length, timesIn(state)[0]])));
  check("excerpts are marked as the feed's, not the publication",
    (await evaluate(`[...document.querySelectorAll(".client-news-excerpt .client-label")]
      .every((label) => label.textContent === "The feed's excerpt, not the publication")`)));

  const beforeFilter = sent.length;
  const energy = all.entries.filter((entry) => entry.topics.some((topic) => topic.interest === "energy")).length;
  await setValue(".client-news-filter select", "energy");
  await sleep(300);
  const filtered = await count(".client-news-entry");
  check("filtering by topic narrows the entries on the page and sends nothing",
    energy > 0 && filtered === energy && sent.length === beforeFilter,
    `${filtered} shown of ${energy}; ${sent.length - beforeFilter} requests`);
  await setValue(".client-news-filter select", "");
  await sleep(200);

  // 6. An unsupported entry: the paste step, filled only with what the feed states.
  const target = all.entries.find((entry) => entry.link === kept.url);
  const unsupported = all.entries.find((entry) => entry.import.state === "unsupported");
  check("the kept page's entry is in the news and is importable; another publisher's entry is not",
    !!target && target.import.state !== "unsupported" && !!unsupported, JSON.stringify({ kept: kept.url,
      unsupported: unsupported?.source }));
  const beforePaste = writes().length;
  await click(`.client-news-entry[data-entry="${unsupported.entry_id}"] .client-paste`);
  await waitFor(`location.pathname === "/sources/new" && !!document.querySelector("[data-from-news]")`);
  const pasted = await evaluate(`({ headline: document.querySelector('[name="headline"]').value,
    url: document.querySelector('[name="source_url"]').value, text: document.querySelector('[name="source_text"]').value })`);
  check("the paste step fills the headline and official address the feed states, no text, and sends nothing",
    pasted.headline === unsupported.title && pasted.url === unsupported.link && pasted.text === "" &&
    writes().length === beforePaste, JSON.stringify(pasted));

  // 7. Interests, then one deliberate, counted search.
  await open("/news/reports");
  await newsReady();
  await click('.client-interests input[value="monetary-policy"]');
  await click(".client-save-interests");
  check("interests are saved with the version the page loaded, and the news follows them",
    await waitFor(`document.querySelector(".client-news")?.dataset.scope === "interests"`) && await newsReady() &&
    JSON.parse(writes("/news/interests").at(-1)?.postData ?? "{}").expected_version === null &&
    (await text("[data-interests-saved]")) === "Monetary policy");
  const word = target.title.split(/[^A-Za-z]+/).find((part) => part.length >= 6) ?? "Federal";
  await setValue('.client-search input[name="query"]', word);
  await click(".client-search-send");
  await waitFor(`!!document.querySelector(".client-search-results")`, 15000);
  const searched = writes("/news/searches");
  check("one deliberate search is sent, with a new key, and the server counts it once",
    searched.length === 1 && /^search-[0-9a-f]{32}$/.test(JSON.parse(searched[0].postData).request_key) &&
    statuses.get(searched[0].id) === 201 &&
    (await evaluate(`document.querySelector(".client-search-results").dataset.counted`)) === "true",
    JSON.stringify(searched.map((item) => [statuses.get(item.id), item.postData])));
  check("the search reads only the kept entries and finds the kept page's entry",
    await exists(`.client-search-results .client-news-entry[data-entry="${target.entry_id}"]`) &&
    (await count(".client-search-results .client-news-entry")) <= all.entries.length);
  await waitFor(`document.querySelector('[data-operation="search"]')?.textContent.includes("1 of 50")`);
  check("the limits are read again from the server: one search of 50 used today",
    (await text('[data-operation="search"]')).startsWith("Searches: 1 of 50 used today"));
  await click(".client-search-close");
  await send("Fetch.enable", { patterns: [{ urlPattern: "*/api/user/news/searches", requestStage: "Response" }] });
  dropSearches = 1;
  await setValue('.client-search input[name="query"]', "statement");
  await click(".client-search-send");
  const lostShown = await waitFor(`!!document.querySelector('.client-search .client-notice.is-unconfirmed')`, 15000);
  await send("Fetch.disable");
  const lost = writes("/news/searches").at(-1);
  const usedAfterLost = await usedToday("search");
  check("a search whose reply is lost after the server counted it: the page says so and sends nothing more by itself",
    lostShown && dropped.length === 1 && writes("/news/searches").length === 2 &&
    (await text(".client-search .client-notice")).includes("not counted twice") && usedAfterLost === 2,
    JSON.stringify({ lostShown, dropped: dropped.length, used: usedAfterLost }));
  await click(".client-search-send");
  await waitFor(`!!document.querySelector(".client-search-results")`, 15000);
  const repeated = writes("/news/searches").at(-1);
  const usedAfterRepeat = await usedToday("search");
  check("pressing Search again repeats the same key, and the server answers that it was not counted again",
    writes("/news/searches").length === 3 && repeated.id !== lost.id &&
    JSON.parse(repeated.postData).request_key === JSON.parse(lost.postData).request_key && statuses.get(repeated.id) === 200 &&
    (await text(".client-search-results .client-note")).startsWith("This repeated a search already sent") &&
    usedAfterRepeat === 2, JSON.stringify({ status: statuses.get(repeated.id), used: usedAfterRepeat }));
  await click(".client-search-close");

  // 8. The kept page's import preview, then its explicit confirmation.
  await open("/news/reports");
  await newsReady();
  await click(`.client-news-entry[data-entry="${target.entry_id}"] .client-import`);
  await waitFor(`location.pathname.startsWith("/news/imports/") && !!document.querySelector(".client-import-text pre")`, 15000);
  const previewSent = writes("/news/imports");
  check("one preview of exactly the entry version shown is sent", previewSent.length === 1 &&
    JSON.stringify(JSON.parse(previewSent[0].postData)) === JSON.stringify({ entry_id: target.entry_id,
      version_sha256: target.version_sha256 }) && statuses.get(previewSent[0].id) === 201);
  const importId = (await evaluate("location.pathname")).split("/").at(-1);
  const preview = (await call(`/api/user/news/imports/${importId}`)).body.import;
  const shown = await evaluate(`({ text: document.querySelector(".client-import-text pre")?.textContent,
    statements: document.querySelectorAll(".client-import-statements li").length,
    url: document.querySelector(".client-import-facts a")?.getAttribute("href"),
    facts: document.querySelector(".client-import-facts")?.textContent ?? "",
    left: document.querySelectorAll(".client-import-left-out li").length,
    linked: [...document.querySelectorAll(".client-import-linked li a")].map((a) => a.getAttribute("href")),
    linkedNote: document.querySelector(".client-import-linked .client-sub")?.textContent ?? "",
    save: document.querySelector(".client-confirm-import")?.disabled })`);
  check("the page shows exactly the text the server proposes to save, in full",
    shown.text === preview.proposed_source.text && preview.proposed_source.characters === [...preview.proposed_source.text].length &&
    shown.statements === preview.statements.length, `${shown.text?.length} vs ${preview.proposed_source.text.length}`);
  check("the page was read from the kept copy: retrieved 14 October, nothing requested again",
    preview.publication.retrieval === "reused" && preview.publication.sha256 === kept.body.sha256 &&
    shown.url === kept.url && shown.facts.includes("14 Oct 2026") && shown.facts.includes("nothing was requested again"),
    JSON.stringify({ retrieval: preview.publication.retrieval, retrieved: preview.publication.retrieved_at }));
  check("the publication time is the feed's stated instant, not a retrieval time",
    preview.proposed_source.published_at === target.published.utc &&
    ![kept.started_at, kept.finished_at].includes(preview.proposed_source.published_at),
    `${preview.proposed_source.published_at} vs ${target.published.utc}`);
  check("what was left out and the linked documents are listed; the linked documents were only named",
    shown.left === preview.left_out.length && preview.linked_documents.length > 0 &&
    JSON.stringify(shown.linked) === JSON.stringify(preview.linked_documents.map((row) => row.url)) &&
    shown.linkedNote.includes("none was retrieved") && !existsSync(publisherLog), JSON.stringify(preview.linked_documents));
  await sleep(300);
  check("nothing is saved until the person confirms: Save is disabled and no confirmation was sent",
    shown.save === true && writes("/confirmation").length === 0);
  await click(".client-import-confirm .client-approve input");
  await click(".client-confirm-import");
  await waitFor(`/^\\/sources\\/[^/]+$/.test(location.pathname)`, 15000);
  const confirmation = writes("/confirmation");
  const sourceId = (await evaluate("location.pathname")).split("/").at(-1);
  check("confirming sends the previewed text's fingerprint once and opens the saved source",
    confirmation.length === 1 && JSON.stringify(JSON.parse(confirmation[0].postData)) ===
      JSON.stringify({ text_sha256: preview.proposed_source.text_sha256, confirm: true }) && confirmation[0].bound === readerId);
  const again = await userPost(`/api/user/news/imports/${importId}/confirmation`,
    { text_sha256: preview.proposed_source.text_sha256, confirm: true });
  const sourcesHeld = (await call("/api/user/sources")).body.sources.length;
  const sourcesCounted = await usedToday("source");
  check("confirming the same import again saves nothing new and counts nothing",
    again.status === 200 && again.body.created === false && sourcesHeld === 1 && sourcesCounted === 1,
    JSON.stringify({ status: again.status, created: again.body.created, sourcesHeld, sourcesCounted }));
  const source = (await call(`/api/user/sources/${sourceId}`)).body.source;
  check("the saved source is exactly the confirmed text, with the feed's publication time as supplied and the official " +
    "address", source.text === preview.proposed_source.text && source.source_url === kept.url &&
    source.published_at_as_supplied === preview.proposed_source.published_at &&
    Date.parse(source.published_at) === Date.parse(preview.proposed_source.published_at), JSON.stringify({ published: source.published_at,
      supplied: source.published_at_as_supplied, proposed: preview.proposed_source.published_at,
      textSame: source.text === preview.proposed_source.text, url: source.source_url }));

  // 9. Effort, quote, explicit approval, one fake send of the confirmed text.
  await waitFor(`document.querySelectorAll('input[name="effort"]').length > 0`, 15000);
  check("on the source's page nothing is prepared, quoted or run; no Effort is chosen",
    !(await evaluate(`[...document.querySelectorAll('input[name="effort"]')].some((e) => e.checked)`)) &&
    writes("/api/user/analyses").length === 0);
  await click('input[name="effort"][value="high"]');
  await click(".client-prepare");
  await waitFor(`!!document.querySelector(".client-get-quote")`, 15000);
  await click(".client-get-quote");
  await waitFor(`!!document.querySelector(".client-approve input")`, 15000);
  const quoted = Number(await text("[data-quote-credits]"));
  check("the flat quote at High is 20 points; nothing was sent before the approval",
    quoted === 20 && await evaluate(`document.querySelector(".client-run").disabled`) && providerSends().length === 0);
  await click(".client-approve input");
  await click(".client-run");
  await waitFor(`!!document.querySelector("[data-panel=recorded]")`, 30000);
  const sends = providerSends();
  const sentBody = sends.length ? readFileSync(join(served, "simulated-provider", sends[0]), "utf8") : "";
  const firstParagraph = preview.proposed_source.text.split("\n\n").find((part) => part.trim().length > 40)?.trim() ?? "";
  check("one explicit approval sends once to the fake, and the request carries the confirmed text",
    sends.length === 1 && firstParagraph.length > 0 && JSON.parse(sentBody).messages[0].content.includes(firstParagraph) &&
    writes("/runs").length === 1, `${sends.length} sends`);
  check("the result shows evidence, interpretation and unknowns, charged exactly the quote",
    (await evaluate(`["client-evidence", "client-interpretation", "client-unknowns"].every((name) =>
      !!document.querySelector("." + name))`)) &&
    (await text(".client-charge")).startsWith(`${quoted} credits charged of ${quoted} credits reserved`));
  const analysisId = decodeURIComponent(writes("/runs")[0].path.split("/").at(-2));
  const quality = (await call(`/api/user/analyses/${encodeURIComponent(analysisId)}/quality`)).body.quality;
  check("the research checks are served at research-quality-0.3: nothing rejected, every finding only flagged",
    quality?.rubric_version === "research-quality-0.3" && Array.isArray(quality.rejected) && quality.rejected.length === 0 &&
    quality.findings.every((finding) => finding.level === "flagged"), JSON.stringify(quality)?.slice(0, 300));
  const writesBeforeChecks = writes().length;
  const checksShown = await waitFor(
    `document.querySelector(".client-checks")?.dataset.checks === ${JSON.stringify(String(quality?.flagged))}`, 15000);
  const panel = await evaluate(`(() => {
    const p = document.querySelector(".client-checks");
    const before = (a, b) => !!(a && b && (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING));
    return { state: p.dataset.checks,
      placed: before(document.querySelector(".client-evidence"), p) && before(p, document.querySelector(".client-review")),
      findings: [...p.querySelectorAll(".client-check-findings li")].map((li) => ({ check: li.dataset.check,
        where: li.dataset.where, detail: li.querySelector(".client-check-detail")?.textContent ?? "",
        rule: li.querySelector(".client-sub")?.textContent ?? "" })),
      review: [...p.querySelectorAll(".client-check-review li")].map((li) => li.textContent),
      checks: [...p.querySelectorAll(".client-check-list dt")].length,
      summary: p.querySelector(".client-check-list summary")?.textContent ?? "",
      limits: p.querySelector("[data-checks-limits]")?.textContent ?? "",
      nothing: p.querySelector("[data-checks-nothing]")?.textContent ?? "",
      own: [...p.querySelectorAll("h2, h3, .client-label, .client-checks-statement, [data-checks-limits], " +
        "[data-checks-nothing], .client-check-list summary, .client-basis")].map((e) => e.textContent).join(" | ") }; })()`);
  check("the checks to examine stand after the result's evidence and before the review, as the server reports them",
    checksShown && panel.placed && panel.state === String(quality.flagged) &&
    JSON.stringify(panel.findings.map((row) => [row.check, row.where, row.detail, row.rule])) ===
      JSON.stringify(quality.findings.map((finding) => [finding.check, finding.where, finding.detail, `Rule: ${finding.rule}`])) &&
    JSON.stringify(panel.review) === JSON.stringify(quality.human_review) &&
    panel.checks === Object.keys(quality.checks).length && panel.summary.includes("research-quality-0.3"),
    JSON.stringify({ shown: checksShown, state: panel.state, placed: panel.placed, findings: panel.findings.length,
      checks: panel.checks }));
  check("the panel states its limits (a flag can be wrong, a mistake can go unflagged), lists what only a person can " +
    "judge, and gives no score, pass mark, grade or confidence",
    panel.limits.includes("A flag can be wrong, and a mistake can go unflagged") && panel.review.length > 0 &&
    (quality.findings.length > 0 || panel.nothing.includes("not a confirmation")) &&
    !/\bscore|pass mark|\bpassed\b|\bgrade[sd]?\b|\bconfidence\b|\d+\s*%/i.test(panel.own), panel.own.slice(0, 300));
  check("reading the checks wrote nothing and sent nothing to the fake",
    writes().length === writesBeforeChecks && providerSends().length === 1 &&
    sent.some((item) => item.method === "GET" && item.path === `/api/user/analyses/${encodeURIComponent(analysisId)}/quality`));

  // 10. The user's own review, the export and the history.
  await evaluate(`document.querySelector('input[name="review-status"][value="human_reviewed"]').click()`);
  await setValue(".client-review textarea", "SYNTHETIC review in the QA news journey: statement 1 matches its quote.");
  await click(".client-save-review");
  check("the user's own review is saved as version 1", await waitFor(`!!document.querySelector('[data-version="1"]')`));
  const exported = await evaluate(`fetch(document.querySelector(".client-export a").getAttribute("href"))
    .then(async (reply) => ({ status: reply.status, body: await reply.json() }))`);
  check("the export is the saved record: the confirmed source's result and the review",
    exported.status === 200 && exported.body.analysis.state === "recorded" &&
    exported.body.analysis.reviews.length === 1 && exported.body.analysis.source?.source_id === sourceId,
    JSON.stringify({ status: exported.status, state: exported.body?.analysis?.state }));
  await open("/analyses");
  check("the history lists the recorded, reviewed analysis", await waitFor(
    `document.querySelectorAll(".client-history-row").length === 1 &&
     document.querySelector(".client-history-row")?.textContent.includes("Reviewed")`));
  await open("/credits");
  check("today's counts as the server reports them: 2 searches, 1 import, 1 new source",
    await waitFor(`!!document.querySelector('.client-limits [data-operation="source"]')`) &&
    (await text('.client-limits [data-operation="search"]')).startsWith("Searches: 2 of 50") &&
    (await text('.client-limits [data-operation="import"]')).startsWith("Publication imports: 1 of 10") &&
    (await text('.client-limits [data-operation="source"]')).startsWith("New sources: 1 of 60"));

  // 11. The browser signed in to another account with no announcement: the next search is refused before it counts.
  await open("/news/reports");
  await newsReady();
  const searchesBefore = writes("/news/searches").length;
  const switched = await evaluate(`fetch("/api/session/login", { method: "POST", headers: { "Content-Type": "application/json",
    "X-Second-Order-Session": "1" }, body: JSON.stringify({ username: "reader-a", password: ${JSON.stringify(PASSWORDS["reader-a"])} }) })
    .then((reply) => reply.status)`);
  await setValue('.client-search input[name="query"]', word);
  await click(".client-search-send");
  await waitFor(`!!document.querySelector('[data-account="stopped"]')`, 15000);
  const refusedSearch = writes("/news/searches").at(-1);
  check("signed in elsewhere as another account, this tab's next search is refused 401 and the tab stops",
    switched === 200 && writes("/news/searches").length === searchesBefore + 1 && statuses.get(refusedSearch.id) === 401 &&
    refusedSearch.bound === readerId && await exists('[data-account="stopped"]'));
  await send("Network.clearBrowserCookies");  // The browser is reader-a's now; the administrator signs in afresh.
  await signInAdmin();
  const usage = (await call("/api/admin/usage")).body;
  check("the refused search counted for neither account; the server requested no publication page",
    usedBy(usage, readerId, "search") === 2 && usedBy(usage, otherId, "search") === 0 &&
    usedBy(usage, readerId, "import") === 1 && usedBy(usage, readerId, "source") === 1 &&
    usedBy(usage, readerId, "preparation") === 1 && usage.server.publication_fetches.used === 0,
    JSON.stringify({ accounts: usage.accounts, server: usage.server.publication_fetches }));

  // 12. Nothing left the machine; the retained records are unchanged; no administrator field in a user reply.
  check("no publication page or feed was requested: no publisher request, the served Event Inbox copy unchanged",
    !existsSync(publisherLog) && same(digests(join(served, "event-inbox")), inboxAtStart));
  const payloads = (await Promise.all([...answered.values()])).filter(Boolean);
  const leaks = [];
  for (const { path, text: body } of payloads) {
    if (path.startsWith("/api/admin")) continue;
    let parsed = null;
    try { parsed = JSON.parse(body); } catch { continue; }
    for (const key of keysIn(parsed)) if (ADMIN_KEYS.test(key)) leaks.push(`${path}: ${key}`);
  }
  check("no public, session or user reply carried an administrator's field", payloads.length > 20 && leaks.length === 0,
    leaks.slice(0, 5).join(" | "));
  const stored = await evaluate(`JSON.stringify({ local: Object.entries(localStorage), session: Object.entries(sessionStorage) })`);
  check("nothing was left in browser storage", stored === '{"local":[],"session":[]}', stored);
  check("the browser requested nothing outside the local server", outside.length === 0, outside.join(", "));
  check("no page error", pageErrors.length === 0, pageErrors.join(" | "));
  check("the fake sender received exactly the one approved run", providerSends().length === 1);
  ws.close();
} catch (error) {
  check("the QA news journey ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(600);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}
check("the retained run folder given to this check is byte-identical afterwards", same(digests(records), runBefore));

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
