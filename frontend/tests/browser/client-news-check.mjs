// Browser check of the Client's current-news journey (frontend/dist-client) in one headless Chrome, against a MOCK of
// the user-api-0.4 news routes (docs/news-usage-contract.md) that runs inside this script from the SYNTHETIC
// news-contract fixtures. Like the server, the MOCK refuses a request bound to another account (401 account_changed)
// and a write that names none (428). Every count, limit and import here is the MOCK's: this proves what the Client
// shows and sends, never what the real server enforces.
//
// The journey: the News link, by keyboard (focus on the title) -> opening the news sends only reads, each naming the
// account -> no interests yet: every topic, the feeds' states (not requested, retrieved), coverage that is not all news
// -> publication times as the feeds state them (a date only, an unusable time) beside retrieval times; excerpts marked
// as not the publication -> filtering sends nothing -> interests saved, then another tab's save refused as a conflict
// and the person's choice kept -> a search checked before sending; counted once; a lost reply repeated with the same
// key and not counted twice; today's limit refused with its figures -> an unsupported entry's paste step, filled with
// only what the feed states -> an import refused with the paste offer -> an import by keyboard: the text and where it
// came from, saved only on explicit confirmation, then the source's page with nothing prepared, quoted or run -> the
// browser signed in to another account: the next request is refused and the tab stops -> phone and tablet widths, no
// outside request, no page error, nothing in browser storage.
//
//   cd frontend; npm run build; node tests/browser/client-news-check.mjs
import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
// Test current source without replacing the builds served by an already running local server.
const built = join(process.env.SECOND_ORDER_TEST_STATIC_ROOT ? resolve(process.env.SECOND_ORDER_TEST_STATIC_ROOT)
  : frontend, "dist-client");
const chromePath = [process.env.SECOND_ORDER_CHROME, "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"].find((path) => path && existsSync(path));
if (!chromePath) throw new Error("Chrome was not found; set SECOND_ORDER_CHROME to its executable.");
if (!existsSync(join(built, "client.html"))) throw new Error("Build the Client first: npm run build");

const fixture = (name) => JSON.parse(readFileSync(join(frontend, "tests/fixtures", `${name}.json`), "utf8"));
const copy = (value) => structuredClone(value);
const CONTRACT = "user-api-0.4";
const PASSWORD = "synthetic-password";
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};

// ---------------------------------------------------------------- the MOCK server (synthetic data only)

const errors = fixture("user-contract-errors");
const users = {
  "reader-a": { session: fixture("user-contract-session-signed-in"), account: fixture("user-contract-account") },
  "reader-b": { session: fixture("client-session-reader-b"), account: fixture("client-account-reader-b") },
};
const SUPPORTED = "fed-monetary:e6ea86fba2aa8bf06700";  // The entry the import fixtures belong to.
const REFUSED_IMPORT = "fed-monetary:b8882b70996964140cb5";
const created = fixture("news-contract-import-created");
const confirmed = fixture("news-contract-import-confirmed");
const limitsFixture = fixture("news-contract-limits").limits;
const mock = {
  tokens: new Map(), requests: [], unbound: 0, forbidden: 0,
  interests: copy(fixture("news-contract-interests-none").interests),
  quota: Object.fromEntries(limitsFixture.operations.map((row) => [row.operation, { limit: row.limit, used: 0 }])),
  searches: new Map(), dropNextSearch: false, imports: null, source: null, imported: [],
};
const STATUS = { not_signed_in: 401, session_expired: 401, invalid_credentials: 401, account_changed: 401,
  account_binding_required: 428, forbidden: 403, not_found: 404, invalid_request: 422, publication_unreadable: 422,
  publication_too_long: 422, rate_limited: 429, too_many_requests: 429 };
const refuse = (code, extra = {}) => ({ status: STATUS[code] ?? 409, body: { ...copy(errors[code]), contract: CONTRACT, ...extra } });
const quotaNow = (operation) => {
  const { limit, used } = mock.quota[operation];
  const label = limitsFixture.operations.find((row) => row.operation === operation).label;
  return { operation, label, limit, used, remaining: Math.max(0, limit - used) };
};

function newsView(scope) {
  const view = copy(fixture(scope === "interests" ? "news-contract-news" : "news-contract-news-all").news);
  view.interests = [...mock.interests.selected];
  for (const entry of view.entries) {
    if (entry.entry_id === SUPPORTED) {
      entry.import = mock.imported.length > 0 ? { state: "imported", reason: null, source_ids: [...mock.imported] }
        : { state: "supported", reason: null, source_ids: [] };
    }
  }
  return view;
}

function api(method, path, query, body, user) {
  if (path === "/api/session" && method === "GET") {
    return { status: 200, body: user ? user.session : fixture("user-contract-session-signed-out") };
  }
  if (path === "/api/session/login") {
    if (!users[body?.username] || body.password !== PASSWORD) return refuse("invalid_credentials");
    const issued = randomBytes(16).toString("hex");
    mock.tokens.set(issued, body.username);
    return { status: 200, body: users[body.username].session, cookie: issued };
  }
  if (path === "/api/session/logout") return { status: 200, body: { ...fixture("user-contract-session-signed-out"), reason: "signed_out" } };
  if (path === "/api/public/credit-terms") return { status: 200, body: fixture("onboarding-credit-terms") };
  if (!user) return refuse("not_signed_in");
  if (method === "GET" && path === "/api/user/account") return { status: 200, body: user.account };
  if (method === "GET" && path === "/api/user/analyses") return { status: 200, body: { contract: CONTRACT, analyses: [] } };
  if (method === "GET" && path === "/api/user/limits") {
    const limits = copy(limitsFixture);
    limits.operations = limits.operations.map((row) => quotaNow(row.operation));
    return { status: 200, body: { contract: CONTRACT, limits } };
  }
  if (path === "/api/user/news" && method === "GET") {
    return { status: 200, body: { contract: CONTRACT, news: newsView(query.get("scope") === "interests" ? "interests" : "all") } };
  }
  if (path === "/api/user/news/interests") {
    if (method === "GET") return { status: 200, body: { contract: CONTRACT, interests: mock.interests } };
    if (body.expected_version !== mock.interests.version) return refuse("interests_changed", { interests: mock.interests });
    if (JSON.stringify(body.interests) === JSON.stringify(mock.interests.selected)) {
      return { status: 200, body: { contract: CONTRACT, interests: mock.interests, changed: false } };
    }
    mock.interests = { ...mock.interests, selected: body.interests, version: (mock.interests.version ?? 0) + 1,
                       saved_at: new Date().toISOString() };
    return { status: 201, body: { contract: CONTRACT, interests: mock.interests, changed: true } };
  }
  if (path === "/api/user/news/searches" && method === "POST") {
    const { request_key: key, ...form } = body;
    const same = JSON.stringify(form);
    const reply = (status, counted) => {
      const shown = copy(fixture("news-contract-search"));
      shown.search = { ...shown.search, query: form.query, words: form.query.toLowerCase().split(/\s+/),
                       interests: form.interests, sources: form.sources, listing: form.listing };
      return { status, body: { ...shown, contract: CONTRACT, counted, quota: quotaNow("search") } };
    };
    if (mock.searches.has(key)) return mock.searches.get(key) === same ? reply(200, false) : refuse("request_key_reused");
    const quota = mock.quota.search;
    if (quota.used >= quota.limit) {
      return refuse("usage_limit_reached", { quota: { ...errors.usage_limit_reached.quota, limit: quota.limit, used: quota.used } });
    }
    quota.used += 1;
    mock.searches.set(key, same);
    return reply(201, true);
  }
  if (path === "/api/user/news/imports" && method === "POST") {
    if (body.entry_id === REFUSED_IMPORT) {
      mock.quota.import.used += 1;  // The MOCK's publisher refused after a request: it counts (requested: true).
      return refuse("publication_unavailable");
    }
    const entry = newsView("all").entries.find((item) => item.entry_id === body.entry_id);
    if (!entry) return refuse("not_found");
    if (entry.version_sha256 !== body.version_sha256) return refuse("entry_changed");
    if (entry.import.state === "unsupported") return refuse("import_unsupported");
    if (mock.imports) return { status: 200, body: { contract: CONTRACT, import: mock.imports, created: false, quota: quotaNow("import") } };
    mock.quota.import.used += 1;
    mock.imports = copy(created.import);
    return { status: 201, body: { contract: CONTRACT, import: mock.imports, created: true, quota: quotaNow("import") } };
  }
  const imported = /^\/api\/user\/news\/imports\/([^/]+)(\/confirmation)?$/.exec(path);
  if (imported) {
    if (!mock.imports || decodeURIComponent(imported[1]) !== mock.imports.import_id) return refuse("not_found");
    if (method === "GET" && !imported[2]) return { status: 200, body: { contract: CONTRACT, import: mock.imports } };
    if (method === "POST" && imported[2]) {
      if (body.confirm !== true || body.text_sha256 !== mock.imports.proposed_source.text_sha256) return refuse("publication_changed");
      if (mock.source) return { status: 200, body: { contract: CONTRACT, import: mock.imports, source: mock.source, created: false } };
      mock.quota.source.used += 1;
      mock.imports = copy(confirmed.import);
      mock.source = copy(confirmed.source);
      mock.imported = [mock.source.source_id];
      return { status: 201, body: { contract: CONTRACT, import: mock.imports, source: mock.source, created: true } };
    }
  }
  const source = /^\/api\/user\/sources\/([^/]+)$/.exec(path);
  if (source && method === "GET" && mock.source && decodeURIComponent(source[1]) === mock.source.source_id) {
    return { status: 200, body: { contract: CONTRACT, source: mock.source, analyses: [] } };
  }
  return refuse("not_found");
}

const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".woff": "font/woff",
                ".woff2": "font/woff2" };
let base = "";
const server = createServer(async (request, response) => {
  const url = new URL(request.url, "http://local");
  if (!url.pathname.startsWith("/api/")) {
    const file = join(built, url.pathname);
    const target = file.startsWith(built) && existsSync(file) && statSync(file).isFile() ? file : join(built, "client.html");
    response.writeHead(200, { "Content-Type": TYPES[extname(target)] ?? "application/octet-stream", Connection: "close" });
    response.end(readFileSync(target));
    return;
  }
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString("utf8");
  const body = raw ? JSON.parse(raw) : null;
  const token = /second_order_session=([0-9a-f]+)/.exec(request.headers.cookie ?? "")?.[1];
  const user = token ? users[mock.tokens.get(token)] ?? null : null;
  const bound = request.headers["x-second-order-account"];
  const userRoute = url.pathname.startsWith("/api/user/");
  const header = url.pathname.startsWith("/api/session") ? "x-second-order-session" : "x-second-order-user";
  let reply;
  if (request.method === "POST" && !url.pathname.startsWith("/api/public/") && (request.headers.origin !== base ||
      request.headers[header] !== "1" || !String(request.headers["content-type"]).startsWith("application/json"))) {
    mock.forbidden += 1;
    reply = refuse("forbidden");
  } else if (userRoute && user && bound !== undefined && bound !== user.session.user.user_id) {
    reply = refuse("account_changed");  // Decided before the route: nothing read, written or counted.
  } else if (userRoute && user && request.method === "POST" && bound === undefined) {
    reply = refuse("account_binding_required");
  } else {
    reply = api(request.method, url.pathname, url.searchParams, body, user);
  }
  if (userRoute && bound === undefined) mock.unbound += 1;
  const dropped = url.pathname === "/api/user/news/searches" && reply.status === 201 && mock.dropNextSearch;
  mock.requests.push({ method: request.method, path: url.pathname, query: url.search, status: dropped ? "dropped" : reply.status,
                       sent: body, bound: bound ?? null });
  if (dropped) {
    mock.dropNextSearch = false;
    request.socket.destroy();  // Counted by the MOCK, but the reply never arrives.
    return;
  }
  const headers = { "Content-Type": "application/json", Connection: "close" };
  if (reply.cookie) headers["Set-Cookie"] = `second_order_session=${reply.cookie}; HttpOnly; SameSite=Strict; Path=/`;
  response.writeHead(reply.status, headers);
  response.end(JSON.stringify(reply.body));
});

// ---------------------------------------------------------------- the browser

const root = mkdtempSync(join(tmpdir(), "second-order-news-check-"));
const children = [];
const since = (index) => mock.requests.slice(index);
const writes = (part = "") => mock.requests.filter((item) => item.method === "POST" && item.path.includes(part));
try {
  await new Promise((done) => server.listen(0, "127.0.0.1", done));
  base = `http://127.0.0.1:${server.address().port}`;
  const profile = join(root, "chrome");
  children.push(spawn(chromePath, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
    "--no-first-run", "--disable-gpu", "about:blank"], { stdio: "ignore" }));
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
  const outside = [];
  const pageErrors = [];
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else if (message.method === "Network.requestWillBeSent") {
      const url = message.params.request.url;
      if (!url.startsWith(base) && !url.startsWith("data:")) outside.push(url);
    } else if (message.method === "Runtime.exceptionThrown") {
      pageErrors.push(message.params.exceptionDetails.text);
    } else if (message.method === "Log.entryAdded" && message.params.entry.level === "error") {
      const entry = message.params.entry;
      // Attributed, not ignored: a refused or dropped API request is logged by the browser (the scenario itself).
      if (!(/status of (4\d\d)|ERR_EMPTY_RESPONSE|Failed to load resource/.test(entry.text) &&
            String(entry.url ?? "").startsWith(`${base}/api/`))) pageErrors.push(`${entry.text} ${entry.url ?? ""}`);
    } else if (message.method === "Page.javascriptDialogOpening") {
      void send("Page.handleJavaScriptDialog", { accept: true });
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
    for (const start = Date.now(); Date.now() - start < timeout; await sleep(60)) {
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
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);
  const exists = (selector) => evaluate(`!!document.querySelector(${JSON.stringify(selector)})`);
  const count = (selector) => evaluate(`document.querySelectorAll(${JSON.stringify(selector)}).length`);
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete' && !document.querySelector('.shell-status')");
  };
  const KEYS = { Tab: { key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 },
                 Enter: { key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, text: "\r" },
                 Space: { key: " ", code: "Space", windowsVirtualKeyCode: 32, text: " " } };
  const press = async (name) => {
    const { text: typed, ...key } = KEYS[name];
    await send("Input.dispatchKeyEvent", { type: "keyDown", ...key, ...(typed ? { text: typed } : {}) });
    await send("Input.dispatchKeyEvent", { type: "keyUp", ...key });
  };
  const tabTo = async (selector, presses = 12) => {
    for (let index = 0; index < presses; index++) {
      await press("Tab");
      if (await evaluate(`document.activeElement?.matches(${JSON.stringify(selector)}) ?? false`)) return true;
    }
    return false;
  };
  const shots = process.env.SECOND_ORDER_SCREENSHOTS;
  const shoot = async (name, selector) => {  // Opt-in, one section scrolled into view; never a whole tall page.
    if (!shots) return;
    await evaluate(`document.querySelector(${JSON.stringify(selector)})?.scrollIntoView({ block: "start" })`);
    await sleep(200);
    const shot = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(shots, `${name}.png`), Buffer.from(shot.data, "base64"));
  };
  const newsReady = () => waitFor(`!!document.querySelector(".client-news [data-news-count]") && !document.querySelector(".client-news .client-status")`);
  const A = users["reader-a"].session.user.user_id;

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Log.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  // 1. Sign in; the News link by keyboard.
  await open("/sign-in");
  await waitFor(`!!document.querySelector('.shell-form input[name="password"]')`);
  await setValue('.shell-form input[name="username"]', "reader-a");
  await setValue('.shell-form input[name="password"]', PASSWORD);
  await click(".shell-form button[type=submit]");
  check("Reader A signs in", await waitFor(`!!document.querySelector(".account-strip")`, 15000));
  await evaluate(`document.querySelector('.site-nav a[href="/news"]').focus()`);
  await press("Enter");
  check("the News link opens the News home by keyboard (docs/news-stories-contract.md section 7)",
    await waitFor(`document.querySelector("main.page.client")?.dataset.view === "news" && location.pathname === "/news" &&
      !!document.querySelector('.news-tabs a[href="/news/reports"]')`));
  const beforeNews = mock.requests.length;
  await evaluate(`document.querySelector('.news-tabs a[href="/news/reports"]').focus()`);
  await press("Enter");
  await newsReady();
  await waitFor(`document.activeElement?.matches("h1.client-title") ?? false`, 3000);
  check("Reports & search opens the feed entries by keyboard, with focus on its title",
    (await evaluate("location.pathname")) === "/news/reports" &&
    (await text("h1.client-title")) === "Reports from the official feeds" &&
    await evaluate(`document.activeElement?.matches("h1.client-title") ?? false`));
  const opening = since(beforeNews).filter((item) => item.path.startsWith("/api/user/"));
  check("opening the news sends only reads (interests, news, limits), every one naming Reader A's account",
    opening.length >= 3 && opening.every((item) => item.method === "GET" && item.bound === A) &&
    ["/api/user/news/interests", "/api/user/news", "/api/user/limits"].every((path) => opening.some((item) => item.path === path)),
    JSON.stringify(opening.map((item) => `${item.method} ${item.path}${item.query}`)));

  // 2. No interests yet: every topic; the feeds as the server reports them.
  check("with no interests chosen, the page says so, opens the choice, and shows every topic",
    await exists("[data-no-interests]") && await evaluate(`document.querySelector(".client-interests").open`) &&
    (await evaluate(`document.querySelector(".client-news").dataset.scope`)) === "all" &&
    mock.requests.some((item) => item.path === "/api/user/news" && item.query === "?scope=all"));
  const all = fixture("news-contract-news-all").news;
  check("every entry the server listed is shown, in its order", (await count(".client-news-entry")) === all.entries.length &&
    JSON.stringify(await evaluate(`[...document.querySelectorAll(".client-news-entry")].map((e) => e.dataset.entry)`)) ===
      JSON.stringify(all.entries.map((entry) => entry.entry_id)));
  const feeds = await evaluate(`[...document.querySelectorAll(".client-feed-list li")].map((li) => ({ source: li.dataset.source,
    state: li.dataset.state, text: li.querySelector(".client-feed-state").textContent }))`);
  check("each feed's state is the server's: BLS not requested, with the publisher's reason; the others retrieved",
    feeds.length === 5 && feeds.filter((feed) => feed.state === "not_requested").length === 2 &&
    feeds.find((feed) => feed.source === "bls-cpi").text.includes("carry a contact") &&
    feeds.filter((feed) => feed.state === "ok").every((feed) => feed.text.startsWith("Retrieved 14 Oct 2026")),
    JSON.stringify(feeds));
  check("the page says what it covers and that it is not all news",
    (await text(".client-news-sources")).includes("It is not all news.") &&
    !(await text("main.client")).includes("Case library"));
  await shoot("news-desktop", ".client-news");

  // 3. Times and excerpts.
  const card = (state) => `.client-news-entry[data-published="${state}"]`;
  check("a date-only entry keeps its date and says the feed states no time of day",
    (await text(`${card("date_only")} .client-news-published`)) === "Published 8 Oct 2026; the feed states no time of day");
  check("an entry whose feed time contradicts its date has an unknown publication time, with the reason",
    (await text(`${card("unstated")} .client-news-published`)).startsWith("Publication time unknown") &&
    (await text(`${card("unstated")} .client-news-time-note`)).includes("contradicts the date"));
  const stated = await evaluate(`[...document.querySelectorAll('${card("stated")} .client-news-times')].map((p) => p.textContent)`);
  check("a stated time is shown in the quota zone, apart from when this server retrieved the entry",
    stated.length > 0 && stated.every((line) => /^Published \d+ \w{3} 2026, \d\d:\d\d \(Asia\/Jerusalem\)Retrieved /.test(line)),
    JSON.stringify(stated));
  check("each excerpt shown is marked as the feed's, not the publication",
    (await count(".client-news-excerpt")) > 0 && (await evaluate(`[...document.querySelectorAll(".client-news-excerpt .client-label")]
      .every((label) => label.textContent === "The feed's excerpt, not the publication")`)));

  // 4. Filtering sends nothing.
  const beforeFilter = mock.requests.length;
  await setValue('.client-news-filter select', "energy");
  await sleep(250);
  const energy = all.entries.filter((entry) => entry.topics.some((topic) => topic.interest === "energy")).length;
  check("filtering by topic narrows the list and sends nothing",
    (await count(".client-news-entry")) === energy && (await text("[data-news-count]")) === `Showing ${energy} of ${all.entries.length} entries.` &&
    mock.requests.length === beforeFilter);
  await setValue('.client-news-filter select', "");

  // 5. Interests: saved; another tab's save is refused as a conflict, never overwritten.
  for (const slug of ["monetary-policy", "energy"]) await click(`.client-interests input[value="${slug}"]`);
  await click(".client-save-interests");
  await waitFor(`document.querySelector(".client-news")?.dataset.scope === "interests"`);
  await newsReady();
  const saveSent = writes("/news/interests").at(-1);
  check("saving interests sends the selection with the version the page loaded, and the news follows them",
    JSON.stringify(saveSent?.sent) === JSON.stringify({ interests: ["monetary-policy", "energy"], expected_version: null }) &&
    saveSent.status === 201 && mock.requests.some((item) => item.query === "?scope=interests") &&
    (await text("[data-interests-saved]")) === "Monetary policy, Energy");
  mock.interests = { ...mock.interests, selected: ["monetary-policy"], version: mock.interests.version + 1,
                     saved_at: new Date().toISOString() };  // Another tab saves meanwhile.
  await evaluate(`document.querySelector(".client-interests").open = true`);
  await click('.client-interests input[value="trade"]');
  await click(".client-save-interests");
  await waitFor(`!!document.querySelector('.client-interests [data-code="interests_changed"]')`);
  check("MOCK: a save after another tab's is refused; the newer one is shown and the person's choice kept to save again",
    (await text('.client-interests [data-code="interests_changed"]')).includes("Saved there: Monetary policy.") &&
    await evaluate(`document.querySelector('.client-interests input[value="trade"]').checked`) &&
    !(await evaluate(`document.querySelector(".client-save-interests").disabled`)));
  await click(".client-save-interests");
  check("saving again, deliberately, replaces it", await waitFor(`!!document.querySelector('.client-interests [role="status"]')`) &&
    writes("/news/interests").at(-1).status === 201 &&
    JSON.stringify(mock.interests.selected) === JSON.stringify(["monetary-policy", "energy", "trade"]));
  await click('.client-interests input[value="trade"]');  // Back to the two the interests fixture's news is for.
  await click(".client-save-interests");
  await waitFor(`document.querySelector("[data-interests-saved]")?.textContent === "Monetary policy, Energy"`);
  await newsReady();

  // 6. Search: checked first, counted once, a lost reply repeated with the same key, today's limit refused.
  const searchesBefore = writes("/news/searches").length;
  await setValue('.client-search input[name="query"]', "!!! ---");
  await click(".client-search-send");
  await sleep(250);
  check("a search with no word is said beside the field and nothing is sent",
    (await text("[data-search-note]")) === "A search needs at least one word of letters or digits." &&
    writes("/news/searches").length === searchesBefore);
  await setValue('.client-search input[name="query"]', "synthetic");
  await click(".client-search-send");
  await waitFor(`!!document.querySelector(".client-search-results")`);
  const first = writes("/news/searches").at(-1);
  check("a deliberate search is sent once, with a new key, and its result says it counted",
    writes("/news/searches").length === searchesBefore + 1 && /^search-[0-9a-f]{32}$/.test(first.sent.request_key) &&
    first.bound === A && (await evaluate(`document.querySelector(".client-search-results").dataset.counted`)) === "true" &&
    (await text(".client-search-results .client-note")).includes("Searches: 1 of 20 used today · 19 left") &&
    (await count(".client-search-results .client-news-entry")) === 6);
  await waitFor(`document.querySelector('[data-operation="search"]')?.textContent.includes("1 of 20")`);
  check("the limits are read again from the server after a counted search",
    (await text('[data-operation="search"]')) === "Searches: 1 of 20 used today · 19 left");
  await click(".client-search-close");
  mock.dropNextSearch = true;
  await setValue('.client-search input[name="query"]', "natural gas");
  await click(".client-search-send");
  await waitFor(`!!document.querySelector('.client-search .client-notice.is-unconfirmed')`, 15000);
  const lost = writes("/news/searches").at(-1);
  check("MOCK: a search whose reply is lost says so and sends nothing more by itself",
    lost.status === "dropped" && (await text(".client-search .client-notice")).includes("not counted twice") &&
    writes("/news/searches").length === searchesBefore + 2);
  await click(".client-search-send");
  await waitFor(`!!document.querySelector(".client-search-results")`);
  const repeated = writes("/news/searches").at(-1);
  check("pressing Search again repeats the same key, and the server's answer is that it was not counted again",
    repeated.sent.request_key === lost.sent.request_key && repeated.status === 200 &&
    (await text(".client-search-results .client-note")).startsWith("This repeated a search already sent") &&
    mock.quota.search.used === 2);
  await click(".client-search-close");
  mock.quota.search.used = mock.quota.search.limit;
  await setValue('.client-search input[name="query"]', "minutes");
  await click(".client-search-send");
  await waitFor(`!!document.querySelector('.client-search [data-code="usage_limit_reached"]')`);
  check("MOCK: today's searches used: refused with the figures and the reset in the quota zone",
    (await text('.client-search [data-code="usage_limit_reached"]')).includes("20 of 20 searches used on 14 Oct 2026.") &&
    (await text('.client-search [data-code="usage_limit_reached"]')).includes("(Asia/Jerusalem)"));
  await shoot("news-search-limit", ".client-search");

  // 7. An unsupported entry's paste step: only what the feed states, never the excerpt as text.
  await open("/news/reports");
  await newsReady();
  const beforePaste = writes().length;
  await click(`.client-news-entry[data-entry="wto-news:32de5add4d0365be3615"] .client-paste`);
  await waitFor(`location.pathname === "/sources/new" && !!document.querySelector("[data-from-news]")`);
  const pasted = await evaluate(`({ headline: document.querySelector('[name="headline"]').value,
    url: document.querySelector('[name="source_url"]').value, date: document.querySelector('[name="date"]').value,
    time: document.querySelector('[name="time"]').value, offset: document.querySelector('[name="offset"]').value,
    text: document.querySelector('[name="source_text"]').value, note: document.querySelector("[data-from-news]").textContent })`);
  const wto = fixture("news-contract-news").news.entries.find((entry) => entry.entry_id === "wto-news:32de5add4d0365be3615");
  check("the paste step fills the headline, the official address and the date the feed states, nothing more",
    pasted.headline === wto.title && pasted.url === wto.link && pasted.date === "2026-10-08" && pasted.time === "" &&
    pasted.offset === "" && pasted.text === "" && pasted.note.includes("not the publication") &&
    pasted.note.includes("only the date") && writes().length === beforePaste, JSON.stringify(pasted));
  await shoot("news-paste", ".client-form");
  await evaluate(`history.back()`);
  await newsReady();

  // 8. An import the publisher refused: the paste step is offered, and the limits are read again.
  await click(`.client-news-entry[data-entry="${REFUSED_IMPORT}"] .client-import`);
  await waitFor(`!!document.querySelector('.client-news-entry[data-entry="${REFUSED_IMPORT}"] [data-code="publication_unavailable"]')`);
  const refusal = await text(`.client-news-entry[data-entry="${REFUSED_IMPORT}"] [data-code="publication_unavailable"]`);
  check("MOCK: a refused import says whether the publisher was requested and offers to paste instead",
    refusal.includes("so it counts as one of today's publication imports") &&
    (await evaluate(`document.querySelector('.client-news-entry[data-entry="${REFUSED_IMPORT}"] .client-paste').className`)).includes("button"));
  await waitFor(`document.querySelector('[data-operation="import"]')?.textContent.includes("1 of 5")`);
  check("the limits show the counted refusal, as read from the server", (await text('[data-operation="import"]')).startsWith("Publication imports: 1 of 5"));

  // 9. An import by keyboard: the text and where it came from, saved only on confirmation.
  await evaluate(`document.querySelector('.client-news-entry[data-entry="${SUPPORTED}"]').scrollIntoView()`);
  await evaluate(`document.querySelector('.client-news-entry[data-entry="${SUPPORTED}"] .client-label').setAttribute("tabindex", "-1")`);
  await evaluate(`document.querySelector('.client-news-entry[data-entry="${SUPPORTED}"] .client-label').focus()`);
  const reached = await tabTo(`.client-news-entry[data-entry="${SUPPORTED}"] .client-import`);
  await press("Enter");
  await waitFor(`location.pathname === "/news/imports/${created.import.import_id}" && !!document.querySelector(".client-import")`);
  const previewSent = writes("/news/imports").at(-1);
  check("Tab reaches Import and Enter sends one preview of exactly the entry version shown",
    reached && JSON.stringify(previewSent.sent) === JSON.stringify({ entry_id: SUPPORTED,
      version_sha256: all.entries.find((entry) => entry.entry_id === SUPPORTED).version_sha256 }) && previewSent.bound === A);
  await waitFor(`document.activeElement?.matches("h1.client-title") ?? false`, 3000);
  const importPage = await evaluate(`({ statements: document.querySelectorAll(".client-import-statements li").length,
    text: document.querySelector(".client-import-text pre")?.textContent, url: document.querySelector(".client-import-facts a")?.href,
    left: document.querySelectorAll(".client-import-left-out li").length, linked: document.querySelectorAll(".client-import-linked li").length,
    save: document.querySelector(".client-confirm-import")?.disabled, title: document.activeElement?.textContent })`);
  check("the import shows the server's statements, the official page, the exact text, what was left out and linked",
    importPage.statements === created.import.statements.length && importPage.text === created.import.proposed_source.text &&
    importPage.url === created.import.publication.url && importPage.left === created.import.left_out.length &&
    importPage.linked === created.import.linked_documents.length && importPage.save === true &&
    importPage.title === created.import.proposed_source.headline, JSON.stringify(importPage));
  await shoot("news-import", ".client-import");
  const confirmsBefore = writes("/confirmation").length;
  await sleep(300);
  check("nothing is saved until the person confirms", writes("/confirmation").length === confirmsBefore);
  await click(".client-import-confirm .client-approve input");
  await click(".client-confirm-import");
  await waitFor(`location.pathname === "/sources/${confirmed.source.source_id}"`);
  const confirmSent = writes("/confirmation").at(-1);
  check("confirming sends the previewed text's fingerprint once and opens the saved source",
    JSON.stringify(confirmSent.sent) === JSON.stringify({ text_sha256: created.import.proposed_source.text_sha256, confirm: true }) &&
    writes("/confirmation").length === confirmsBefore + 1 && confirmSent.bound === A);
  await waitFor(`document.querySelectorAll('input[name="effort"]').length > 0`);
  check("on the source's page, nothing has been prepared, quoted or run: an Effort is still the person's choice",
    !(await evaluate(`[...document.querySelectorAll('input[name="effort"]')].some((e) => e.checked)`)) &&
    writes("/api/user/analyses").length === 0);
  await open("/news/reports");
  await newsReady();
  check("back on the news, the entry says it is saved as the person's source",
    (await evaluate(`document.querySelector('.client-news-entry[data-entry="${SUPPORTED}"]')?.dataset.import`)) === "imported" &&
    await exists(`.client-news-entry[data-entry="${SUPPORTED}"] a[href="/sources/${confirmed.source.source_id}"]`));

  // 10. Reloading writes nothing.
  const beforeReload = writes().length;
  for (const path of ["/news/reports", `/news/imports/${created.import.import_id}`, "/credits"]) {
    await open(path);
    await sleep(500);
  }
  check("opening and reloading the news, an import and the credits page send no write", writes().length === beforeReload);
  check("the credits page shows today's limits as the server reports them",
    await waitFor(`!!document.querySelector('.client-limits [data-operation="source"]')`) &&
    (await text('.client-limits [data-operation="source"]')) === "New sources: 1 of 10 used today · 9 left");

  // 11. Phone and tablet widths.
  const widths = {};
  for (const [name, width, height] of [["tablet", 768, 1024], ["phone", 375, 812]]) {
    await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: true });
    for (const path of ["/news/reports", `/news/imports/${created.import.import_id}`]) {
      await open(path);
      await waitFor(`!!document.querySelector(".client-news-entry, .client-import")`);
      await sleep(300);
      widths[`${name} ${path}`] = await evaluate(`document.documentElement.scrollWidth <= document.documentElement.clientWidth ||
        \`\${document.documentElement.scrollWidth} > \${document.documentElement.clientWidth}: \` +
        [...document.querySelectorAll("body *")].filter((element) => element.getBoundingClientRect().right >
          document.documentElement.clientWidth || (element.scrollWidth > element.clientWidth + 1 &&
          getComputedStyle(element).overflowX === "visible")).slice(0, 3)
          .map((element) => \`\${element.tagName.toLowerCase()}.\${element.className}\`).join(", ")`);
      await shoot(`news-${name}-${path.length > 6 ? "import" : "list"}`, "main.client");
    }
  }
  check("at tablet and phone widths no news or import page scrolls sideways",
    Object.values(widths).every((fits) => fits === true), JSON.stringify(widths));
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  // 12. The browser signed in to another account: the next request is refused and the tab stops.
  await open("/news/reports");
  await newsReady();
  const [token] = [...mock.tokens].filter(([, name]) => name === "reader-a").at(-1);
  mock.tokens.set(token, "reader-b");  // Unannounced: no other tab of this browser says so.
  const searchesNow = mock.quota.search.used;
  mock.quota.search.used = 0;
  await setValue('.client-search input[name="query"]', "synthetic");
  await click(".client-search-send");
  await waitFor(`!!document.querySelector('[data-account="stopped"]')`);
  const refusedSearch = writes("/news/searches").at(-1);
  check("MOCK: a search bound to Reader A while the browser is Reader B's is refused before it counts; the tab stops",
    refusedSearch.status === 401 && mock.quota.search.used === 0 && await exists('[data-account="stopped"]') &&
    !(await evaluate("document.body.innerText")).includes("Reader B"));
  mock.quota.search.used = searchesNow;

  // 13. Boundaries.
  check("every request to the user routes named the account", mock.unbound === 0, `${mock.unbound} unbound`);
  check("every write carried this page's origin and its header", mock.forbidden === 0);
  const stored = await evaluate(`JSON.stringify({ local: Object.entries(localStorage), session: Object.entries(sessionStorage) })`);
  check("nothing was kept in browser storage", stored === '{"local":[],"session":[]}', stored);
  check("the page requested nothing outside the local server", outside.length === 0, outside.join(", "));
  check("no page error", pageErrors.length === 0, pageErrors.join(" | "));
  ws.close();
} catch (error) {
  check("the news browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  server.close();
  await sleep(400);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
