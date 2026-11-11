// Browser check of unsaved work across a session expiry and a new sign-in, in the built Client (frontend/dist-client)
// and one headless Chrome, against a MOCK of the user contract that runs inside this script from the SYNTHETIC
// fixtures. Expiry is the MOCK's: it answers 401 session_expired for a session it has ended. Everything the server
// would enforce (review conflicts, a changed result, ownership) is the MOCK's here too: this proves what the Client
// keeps, gives back and sends, never what the real server enforces.
//
// The journey: a review typed when the session ends is given back, after re-reading the analysis, to the same user
// only, and saved only when they ask -> a version saved meanwhile by another tab is refused as a conflict, the notes
// kept -> a review written for a result that has since changed is offered to copy, never saved against the new result
// -> a source form typed when the session ends never reaches another user, and that user's sign-in discards it ->
// the same user signing in elsewhere is told it is waiting, opens it with every field, and saves it once -> an explicit
// sign-out discards what was typed -> an approval ticked before expiry is never restored and nothing runs -> two tabs
// share one sign-in: when another tab signs the browser in as Reader B, Reader A's tab is told, sends nothing (its Save
// and its reads stop), keeps the typed source for Reader A and gives it back after Reader A signs in again; a stale
// tab's Sign out ends nobody's session; a save after an unannounced switch names Reader A's account, is refused by the
// MOCK as the server refuses it (401 account_changed), and stops the tab with the text kept -> every user request
// names the tab's account -> no browser storage, no outside request, no page error.
//
//   cd frontend; npm run build; node tests/browser/client-recovery-check.mjs
import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const built = join(frontend, "dist-client");
const chromePath = [process.env.SECOND_ORDER_CHROME, "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
  "/usr/bin/chromium-browser"].find((path) => path && existsSync(path));
if (!chromePath) throw new Error("Chrome was not found; set SECOND_ORDER_CHROME to its executable.");
if (!existsSync(join(built, "client.html"))) throw new Error("Build the client first: npm run build");

const fixture = (name) => JSON.parse(readFileSync(join(frontend, "tests/fixtures", `${name}.json`), "utf8"));
const copy = (value) => structuredClone(value);
const CONTRACT = "user-api-0.2";
const PASSWORD = "synthetic-password";
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};

// ---------------------------------------------------------------- the MOCK server (synthetic data only)

const errors = fixture("user-contract-errors");
const recorded = fixture("user-contract-analysis-recorded").analysis;
const quotedTemplate = fixture("user-contract-analysis-quoted").analysis;
const quotedId = quotedTemplate.analysis_id.replace(/\.high$/, ".medium");
const quoted = { ...copy(quotedTemplate), analysis_id: quotedId, effort: "medium",
                 quote: { ...quotedTemplate.quote, analysis_id: quotedId, effort: "medium" } };
const users = {
  "reader-a": { session: fixture("user-contract-session-signed-in"), account: fixture("user-contract-account"),
                analyses: new Map([[recorded.analysis_id, copy(recorded)], [quotedId, quoted]]), sources: new Map() },
  "reader-b": { session: fixture("client-session-reader-b"), account: fixture("client-account-reader-b"),
                analyses: new Map(), sources: new Map() },
};
const mock = { tokens: new Map(), expired: new Set(), requests: [], forbidden: 0, unbound: 0 };
const STATUS = { not_signed_in: 401, session_expired: 401, invalid_credentials: 401, account_changed: 401,
  account_binding_required: 428, forbidden: 403, not_found: 404, invalid_request: 422, invalid_source: 422,
  invalid_review: 422 };
const refuse = (code) => ({ status: STATUS[code] ?? 409, body: copy(errors[code]) });
const summary = (item) => ({ analysis_id: item.analysis_id, effort: item.effort, prepared_at: item.prepared_at,
  source: { source_id: item.source.source_id, headline: item.source.headline, published_at: item.source.published_at },
  state: item.state, outcome: item.state === "recorded" ? item.result.outcome : null,
  review_status: item.reviews.at(-1)?.status ?? null, credits_charged: item.charge?.credits_charged ?? null });

function api(method, path, body, user, token, expired) {
  if (path === "/api/session" && method === "GET") {
    if (user) return { status: 200, body: user.session };
    return { status: 200, body: fixture(expired ? "user-contract-session-expired" : "user-contract-session-signed-out") };
  }
  if (path === "/api/session/login") {
    if (!users[body?.username] || body.password !== PASSWORD) return refuse("invalid_credentials");
    const issued = randomBytes(16).toString("hex");
    mock.tokens.set(issued, body.username);
    return { status: 200, body: users[body.username].session, cookie: issued };
  }
  if (path === "/api/session/logout") {
    mock.tokens.delete(token);
    return { status: 200, body: { ...fixture("user-contract-session-signed-out"), reason: "signed_out" } };
  }
  if (!user) return refuse(expired ? "session_expired" : "not_signed_in");
  const parts = path.split("/").slice(3).map(decodeURIComponent);
  if (method === "GET" && parts[0] === "account") return { status: 200, body: user.account };
  if (parts[0] === "sources") {
    if (method === "POST") {
      const source = { source_id: `20261014T120000000000Z-${randomBytes(6).toString("hex")}`, headline: body.headline,
        source_url: body.source_url, published_at: body.published_at, published_at_as_supplied: body.published_at,
        captured_at: new Date().toISOString(), characters: Array.from(body.source_text).length, text: body.source_text };
      user.sources.set(source.source_id, source);
      return { status: 201, body: { contract: CONTRACT, source } };
    }
    const own = user.sources.get(parts[1]);
    return own ? { status: 200, body: { contract: CONTRACT, source: own, analyses: [] } } : refuse("not_found");
  }
  if (parts[0] !== "analyses") return refuse("not_found");
  if (parts.length === 1) return { status: 200, body: { contract: CONTRACT, analyses: [...user.analyses.values()].map(summary) } };
  const analysis = user.analyses.get(parts[1]);
  if (!analysis) return refuse("not_found");
  if (method === "GET" && parts.length === 2) return { status: 200, body: { contract: CONTRACT, analysis } };
  if (method === "GET" && parts[2] === "quality") {  // The research checks (a read): canonical, nothing flagged.
    return { status: 200, body: { contract: CONTRACT, quality: analysis.result?.analysis ? copy(fixture("news-contract-quality").quality) : null } };
  }
  if (method === "POST" && parts[2] === "reviews") {
    if (body.result_sha256 !== analysis.result_sha256) return refuse("result_changed");
    if (body.parent_review_id !== (analysis.reviews.at(-1)?.review_id ?? null)) return refuse("review_conflict");
    const review = { review_id: `r-${randomBytes(12).toString("hex")}`, sequence: analysis.reviews.length + 1,
      parent_review_id: body.parent_review_id, saved_at: new Date().toISOString(), status: body.status, notes: body.notes,
      result_sha256: analysis.result_sha256, reviewer: { user_id: user.session.user.user_id,
                                                          display_name: user.session.user.display_name } };
    analysis.reviews.push(review);
    return { status: 201, body: { contract: CONTRACT, review, analysis } };
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
  const expired = Boolean(token && mock.expired.has(token));
  const user = token && !expired ? users[mock.tokens.get(token)] ?? null : null;
  const header = url.pathname.startsWith("/api/session") ? "x-second-order-session" : "x-second-order-user";
  // The account binding (docs/account-binding-contract.md), as the server applies it before any route.
  const bound = request.headers["x-second-order-account"];
  const userRoute = url.pathname.startsWith("/api/user/");
  if (userRoute && bound === undefined) mock.unbound += 1;
  let reply;
  if (request.method === "POST" && (request.headers.origin !== base || request.headers[header] !== "1" ||
      !String(request.headers["content-type"]).startsWith("application/json"))) {
    mock.forbidden += 1;
    reply = refuse("forbidden");
  } else if ((userRoute || url.pathname === "/api/session/logout") && user && bound !== undefined &&
             bound !== user.session.user.user_id) {
    reply = refuse("account_changed");
  } else if (userRoute && user && request.method === "POST" && bound === undefined) {
    reply = refuse("account_binding_required");
  } else {
    reply = api(request.method, url.pathname, body, user, token, expired);
  }
  mock.requests.push({ method: request.method, path: url.pathname, status: reply.status, sent: body,
                       user: user?.session.user.username ?? null, bound: bound ?? null });
  const headers = { "Content-Type": "application/json", Connection: "close" };
  if (reply.cookie) headers["Set-Cookie"] = `second_order_session=${reply.cookie}; HttpOnly; SameSite=Strict; Path=/`;
  response.writeHead(reply.status, headers);
  response.end(JSON.stringify(reply.body));
});

// ---------------------------------------------------------------- the browser

const root = mkdtempSync(join(tmpdir(), "second-order-recovery-check-"));
const children = [];
const posts = (part) => mock.requests.filter((item) => item.method === "POST" && item.path.endsWith(part));
const expire = (username) => { for (const [token, name] of mock.tokens) if (name === username) mock.expired.add(token); };
try {
  await new Promise((done) => server.listen(0, "127.0.0.1", done));
  base = `http://127.0.0.1:${server.address().port}`;
  const profile = join(root, "chrome");
  children.push(spawn(chromePath, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
    "--no-first-run", "--disable-gpu", "about:blank"], { stdio: "ignore" }));
  let socketUrl;
  let devtools;
  for (let i = 0; i < 150 && !socketUrl; i++) {
    try {
      devtools = readFileSync(join(profile, "DevToolsActivePort"), "utf8").split("\n")[0].trim();
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
  const dialogs = [];
  const blockedPrompts = [];
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
      if (/Blocked attempt to show a 'beforeunload' confirmation panel/.test(entry.text)) blockedPrompts.push(entry.url);
      else if (!(/status of 4\d\d|Failed to load resource/.test(entry.text) && String(entry.url ?? "").startsWith(`${base}/api/`))) {
        pageErrors.push(`${entry.text} ${entry.url ?? ""}`);
      }
    } else if (message.method === "Page.javascriptDialogOpening") {
      dialogs.push(message.params.message);
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
  const clickText = (selector, words) => evaluate(`(() => { const e = [...document.querySelectorAll(${JSON.stringify(selector)})]
    .find((item) => item.textContent.includes(${JSON.stringify(words)})); if (!e) return false; e.click(); return true; })()`);
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);
  const value = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.value ?? null`);
  const exists = (selector) => evaluate(`!!document.querySelector(${JSON.stringify(selector)})`);
  const shots = process.env.SECOND_ORDER_SCREENSHOTS;
  const shoot = async (name, selector) => {  // Opt-in, one section scrolled into view; never a whole tall page.
    if (!shots) return;
    await evaluate(`document.querySelector(${JSON.stringify(selector)})?.scrollIntoView({ block: "start" })`);
    await sleep(200);
    const shot = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(shots, `${name}.png`), Buffer.from(shot.data, "base64"));
  };
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete' && !document.querySelector('.shell-status')");
  };
  /** Sign in on the form shown now (it keeps the address), or at /sign-in. */
  const signIn = async (username) => {
    if (!(await exists('.shell-form input[name="password"]'))) await open("/sign-in");
    await waitFor(`!!document.querySelector('.shell-form input[name="password"]')`);
    await setValue('.shell-form input[name="username"]', username);
    await setValue('.shell-form input[name="password"]', PASSWORD);
    await click(".shell-form button[type=submit]");
    return waitFor(`!!document.querySelector("main.page.client") && !!document.querySelector(".account-strip")`, 15000);
  };
  /** The session ends; the page's next request is answered 401, and the person signs in again on the form shown. */
  const endWith = async (username, action) => {
    expire(username);
    await action();
    await waitFor(`!!document.querySelector(".client-ended") || !!document.querySelector('.shell-form input[name="password"]')`);
  };
  const reviewOn = () => evaluate(`({ notes: document.querySelector(".client-review-notes textarea")?.value ?? null,
    status: document.querySelector('input[name="review-status"]:checked')?.value ?? null })`);
  const typeReview = async (status, notes) => {
    await waitFor(`!!document.querySelector(".client-review-notes textarea")`);
    await evaluate(`document.querySelector('input[name="review-status"][value="${status}"]').click()`);
    await setValue(".client-review-notes textarea", notes);
  };
  const SOURCE = { headline: "SYNTHETIC source typed before the session ended", source_url: "https://example.org/synthetic/kept",
                   date: "2026-10-13", time: "10:00", offset: "+03:00",
                   source_text: "October 13, 2026\n\nSYNTHETIC text typed into the form when the session ended." };
  const typeSource = async () => {
    await waitFor(`!!document.querySelector(".client-form")`);
    for (const [name, typed] of Object.entries(SOURCE)) {
      await setValue(name === "source_text" ? 'textarea[name="source_text"]' : name === "offset" ? 'select[name="offset"]'
        : `input[name="${name}"]`, typed);
    }
  };
  const sourceOn = () => evaluate(`({ ${Object.keys(SOURCE).map((name) => `${name}: document.querySelector('[name="${name}"]')?.value ?? null`).join(", ")} })`);
  const loginsSince = () => mock.requests.findLastIndex((item) => item.path === "/api/session/login" && item.status === 200);
  const readAfterLogin = (path) => mock.requests.slice(loginsSince()).some((item) => item.method === "GET" &&
    item.path === path && item.status === 200);
  const R = recorded.analysis_id;
  const analysisPath = `/api/user/analyses/${encodeURIComponent(R)}`;

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Log.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  check("Reader A signs in", await signIn("reader-a"));

  // 1. A review typed when the session ends comes back to the same user, after the analysis is read again.
  await open(`/analyses/${encodeURIComponent(R)}`);
  await typeReview("needs_revision", "SYNTHETIC notes A: statement 2 reads more than its quote.");
  const firstBase = users["reader-a"].analyses.get(R).reviews.at(-1).review_id;
  await endWith("reader-a", () => click(".client-save-review"));
  const ended = await text(".client-ended");
  check("the session ends on Save: the notes are shown, kept in this tab for the same account, and nothing was saved",
    (await value(".client-ended-text")) === "SYNTHETIC notes A: statement 2 reads more than its quote." &&
    /kept in this tab/.test(ended) && ended.includes("Reader A (synthetic)") &&
    posts("/reviews").every((item) => item.status === 401), ended);
  await shoot("recovery-ended", ".client-ended");
  await click(".client-ended .button");
  await waitFor(`!!document.querySelector(".shell-form")`);
  check("signing in again happens at the same address", (await evaluate("location.pathname")) === `/analyses/${encodeURIComponent(R)}`);
  const reviewsBefore = posts("/reviews").length;
  await signIn("reader-a");
  await waitFor(`!!document.querySelector('[data-recovered="review"]')`);
  check("MOCK: after the account and the analysis are read again, the same user gets the notes and status back",
    JSON.stringify(await reviewOn()) === JSON.stringify({ notes: "SYNTHETIC notes A: statement 2 reads more than its quote.",
      status: "needs_revision" }) && readAfterLogin("/api/user/account") && readAfterLogin(analysisPath));
  await shoot("recovery-review-restored", ".client-review");
  await sleep(500);
  check("nothing was saved by itself", posts("/reviews").length === reviewsBefore);
  await click(".client-save-review");
  await waitFor(`!!document.querySelector('[data-version="2"]')`);
  const saved = posts("/reviews").at(-1);
  check("MOCK: saved only on request, as one new version that follows the version it was written after",
    saved.status === 201 && saved.sent.parent_review_id === firstBase && saved.sent.notes.startsWith("SYNTHETIC notes A") &&
    posts("/reviews").length === reviewsBefore + 1 && !(await exists('[data-recovered="review"]')));
  const promptsBefore = blockedPrompts.length;
  await open("/");
  await waitFor(`!!document.querySelector("main.client")`);
  check("once saved, nothing is held: leaving asks nothing and no recovered work is listed",
    blockedPrompts.length === promptsBefore && !(await exists("[data-recovered-list]")));

  // 2. A version saved meanwhile (another tab): the restored notes are refused as a conflict and kept.
  await open(`/analyses/${encodeURIComponent(R)}`);
  await typeReview("human_reviewed", "SYNTHETIC notes B, written after version 2.");
  await endWith("reader-a", () => click(".client-save-review"));
  const latest = users["reader-a"].analyses.get(R).reviews.at(-1);
  users["reader-a"].analyses.get(R).reviews.push({ ...latest, review_id: `r-${randomBytes(12).toString("hex")}`,
    sequence: latest.sequence + 1, parent_review_id: latest.review_id, notes: "SYNTHETIC: saved in another tab" });
  await click(".client-ended .button");
  await signIn("reader-a");
  await waitFor(`!!document.querySelector('[data-recovered="review"]')`);
  await click(".client-save-review");
  await waitFor(`!!document.querySelector('[data-code="review_conflict"]')`);
  check("MOCK: the restored notes follow version 2, so version 3 saved meanwhile is refused as a conflict; notes kept",
    posts("/reviews").at(-1).sent.parent_review_id === latest.review_id &&
    (await reviewOn()).notes === "SYNTHETIC notes B, written after version 2.");
  await clickText('[data-code="review_conflict"] button', "Read again");
  await waitFor(`!document.querySelector('[data-code="review_conflict"]') && !!document.querySelector('[data-version="3"]')`);
  await click(".client-save-review");
  check("after reading the other version, saving on request adds version 4 after it",
    await waitFor(`!!document.querySelector('[data-version="4"]')`) &&
    posts("/reviews").at(-1).sent.parent_review_id === users["reader-a"].analyses.get(R).reviews[2].review_id);

  // 3. A review written for a result that has since changed is offered to copy, never put into the editor.
  await typeReview("needs_revision", "SYNTHETIC notes C, for the earlier result.");
  await endWith("reader-a", () => click(".client-save-review"));
  users["reader-a"].analyses.get(R).result_sha256 = "c".repeat(64);
  await click(".client-ended .button");
  const staleBefore = posts("/reviews").length;
  await signIn("reader-a");
  await waitFor(`!!document.querySelector('[data-recovered="stale"]')`);
  check("MOCK: notes for an earlier result are shown to copy, not restored into the editor, and cannot be saved",
    (await value('[data-recovered="stale"] textarea')) === "SYNTHETIC notes C, for the earlier result." &&
    (await reviewOn()).notes === "" && await evaluate(`document.querySelector(".client-save-review").disabled`) &&
    posts("/reviews").length === staleBefore);
  await shoot("recovery-review-stale", ".client-review");
  const discarded = await clickText('[data-recovered="stale"] button', "Discard");
  check("discarding them removes them", discarded && await waitFor(`!document.querySelector('[data-recovered="stale"]')`));

  // 4. A source form never reaches another user, and that user's sign-in discards it.
  await open("/sources/new");
  await typeSource();
  await endWith("reader-a", () => click(".client-save-source"));
  check("the session ends on Save: the source is shown to copy, and was not saved",
    (await evaluate(`[...document.querySelectorAll(".client-ended-text")].map((t) => t.value).join("|")`)).includes(SOURCE.headline) &&
    posts("/sources").every((item) => item.status === 401));
  await click(".client-ended .button");
  await signIn("reader-b");
  await waitFor(`!!document.querySelector(".client-form")`);
  await sleep(400);
  check("MOCK: Reader B signing in at the same address gets an empty form and nothing of Reader A's",
    Object.values(await sourceOn()).every((field) => field === "") && !(await exists("[data-recovered], [data-recovered-list]")) &&
    !(await evaluate(`document.body.innerText.includes(${JSON.stringify(SOURCE.headline)})`)));
  await click(".account-strip button");
  await waitFor(`!!document.querySelector(".shell-form")`);
  await signIn("reader-a");
  await waitFor(`!!document.querySelector(".client-form")`);
  await sleep(400);
  check("and Reader A signing in afterwards gets nothing back either: it was discarded",
    Object.values(await sourceOn()).every((field) => field === "") && !(await exists("[data-recovered], [data-recovered-list]")));

  // 5. The same user signing in elsewhere is told the source is waiting, opens it with every field, and saves once.
  await typeSource();
  await endWith("reader-a", () => click(".client-save-source"));
  await click(".client-ended .button");
  // Within the page: a full navigation reloads the tab, and what is kept in its memory is gone by design.
  await click('.topbar a[href="/sign-in"]');
  await waitFor(`location.pathname === "/sign-in" && !!document.querySelector('.shell-form input[name="password"]')`);
  await signIn("reader-a");
  await waitFor(`!!document.querySelector("[data-recovered-list]")`);
  check("MOCK: signed in at home, the waiting source is listed with Open and Discard",
    (await text("[data-recovered-list]")).includes(SOURCE.headline) && (await evaluate("location.pathname")) === "/" &&
    (await exists('[data-recovered-list] a[href="/sources/new"]')));
  await shoot("recovery-waiting-list", "[data-recovered-list]");
  const sourcesBefore = posts("/sources").length;
  await click('[data-recovered-list] a[href="/sources/new"]');
  await waitFor(`!!document.querySelector('[data-recovered="source"]')`);
  check("opening it puts every field back, as typed, and saves nothing",
    JSON.stringify(await sourceOn()) === JSON.stringify(SOURCE) && posts("/sources").length === sourcesBefore &&
    !(await exists("[data-recovered-list]")));
  await click(".client-save-source");
  await waitFor(`/^\\/sources\\/2026/.test(location.pathname)`);
  const sourceSaved = posts("/sources").at(-1);
  check("MOCK: saved once, on request, with exactly the typed fields",
    posts("/sources").length === sourcesBefore + 1 && sourceSaved.status === 201 &&
    sourceSaved.sent.headline === SOURCE.headline && sourceSaved.sent.source_text === SOURCE.source_text &&
    sourceSaved.sent.published_at === "2026-10-13T10:00:00+03:00");

  // 6. An explicit sign-out discards what was typed.
  await open(`/analyses/${encodeURIComponent(R)}`);
  await typeReview("human_reviewed", "SYNTHETIC notes F, then signed out.");
  const dialogsBefore = dialogs.length;
  await click(".account-strip button");
  await waitFor(`!!document.querySelector(".shell-form")`);
  check("signing out with unsaved notes asks first", dialogs.length === dialogsBefore + 1 && /Sign out anyway/.test(dialogs.at(-1)));
  await signIn("reader-a");
  await waitFor(`!!document.querySelector(".client-review-notes textarea")`);
  await sleep(400);
  check("after an explicit sign-out nothing comes back", (await reviewOn()).notes === "" &&
    !(await exists("[data-recovered], [data-recovered-list]")));

  // 7. An approval ticked before the session ended is never restored, and nothing runs.
  await open(`/analyses/${encodeURIComponent(quotedId)}`);
  await waitFor(`!!document.querySelector(".client-approve input")`);
  await click(".client-approve input");
  await endWith("reader-a", () => click(".client-basis .client-link-button"));
  check("with nothing typed, the session's end goes straight to the sign-in form", !(await exists(".client-ended")));
  await signIn("reader-a");
  await waitFor(`!!document.querySelector(".client-approve input")`);
  check("the quote is shown again from the server, unapproved; Run is disabled and nothing was run",
    !(await evaluate(`document.querySelector(".client-approve input").checked`)) &&
    await evaluate(`document.querySelector(".client-run").disabled`) && posts("/runs").length === 0);

  // 8. Two tabs of one browser share one sign-in (QA-2). Tab 2 signs out and in as Reader B while tab 1, opened for
  //    Reader A, has a source typed: tab 1 must never save to, read from or show Reader B's account under Reader A.
  const second = await (await fetch(`http://127.0.0.1:${devtools}/json/new?about:blank`, { method: "PUT" })).json();
  const ws2 = new WebSocket(second.webSocketDebuggerUrl);
  await new Promise((done) => ws2.addEventListener("open", done, { once: true }));
  const pending2 = new Map();
  let counter2 = 0;
  ws2.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending2.has(message.id)) {
      pending2.get(message.id)(message);
      pending2.delete(message.id);
    } else if (message.method === "Runtime.exceptionThrown") {
      pageErrors.push(`tab 2: ${message.params.exceptionDetails.text}`);
    } else if (message.method === "Page.javascriptDialogOpening") {
      dialogs.push(message.params.message);
    }
  });
  const send2 = (method, params = {}) => new Promise((done, fail) => {
    const id = ++counter2;
    pending2.set(id, (message) => message.error ? fail(new Error(message.error.message)) : done(message.result));
    ws2.send(JSON.stringify({ id, method, params }));
  });
  const evaluate2 = async (expression) =>
    (await send2("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })).result.value;
  const waitFor2 = async (expression, timeout = 10000) => {
    for (const start = Date.now(); Date.now() - start < timeout; await sleep(60)) {
      if (await evaluate2(expression)) return true;
    }
    return false;
  };
  const signIn2 = async (username) => {
    await waitFor2(`!!document.querySelector('.shell-form input[name="password"]')`);
    await evaluate2(`(() => { const set = (selector, typed) => { const element = document.querySelector(selector);
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(element, typed);
      element.dispatchEvent(new Event("input", { bubbles: true })); };
      set('.shell-form input[name="username"]', ${JSON.stringify(username)});
      set('.shell-form input[name="password"]', ${JSON.stringify(PASSWORD)});
      document.querySelector(".shell-form button[type=submit]").click(); })()`);
    return waitFor2(`!!document.querySelector(".account-strip")`);
  };
  /** In-app navigation in tab 1: a full page load would lose what the tab holds in memory. */
  const go = (path) => evaluate(`(() => { history.pushState(null, "", ${JSON.stringify(path)});
    dispatchEvent(new PopStateEvent("popstate")); return true; })()`);
  await send2("Page.enable");
  await send2("Runtime.enable");

  await open("/sources/new");
  await typeSource();
  await send2("Page.navigate", { url: `${base}/` });
  check("tab 2 opens signed in as Reader A: the tabs share one cookie",
    await waitFor2(`document.querySelector(".account-strip")?.textContent.includes("Reader A")`));
  await evaluate2(`document.querySelector(".account-strip button").click()`);
  await waitFor2(`!document.querySelector(".account-strip")`);
  await evaluate2(`location.assign("/sign-in")`);
  const bSourcesBefore = users["reader-b"].sources.size;
  check("tab 2 signs out, then in as Reader B", await signIn2("reader-b"));
  check("tab 1 is told at once: still labelled for Reader A, it says the browser is now signed in elsewhere",
    await waitFor(`!!document.querySelector('[data-account="elsewhere"]')`) &&
    (await text(".account-strip")).includes("This tab was opened for Reader A (synthetic)"),
    await text(".account-strip"));
  await shoot("tabs-elsewhere", "main.client");
  const requestsBefore = mock.requests.length;
  await click(".client-save-source");
  await waitFor(`!!document.querySelector('[data-account="stopped"]')`);
  check("saving in tab 1 sends nothing: no request at all, and Reader B has no new source",
    mock.requests.length === requestsBefore && users["reader-b"].sources.size === bSourcesBefore,
    JSON.stringify(mock.requests.slice(requestsBefore).map((item) => `${item.method} ${item.path}`)));
  const stoppedView = await text('[data-account="stopped"]');
  check("tab 1 stops: Reader A's typed source is shown to copy, kept for Reader A only, with no account strip",
    (await evaluate(`[...document.querySelectorAll(".client-ended-text")].map((t) => t.value).join("|")`)).includes(SOURCE.source_text) &&
    stoppedView.includes("kept in this tab for Reader A (synthetic) only") && !(await exists(".account-strip")) &&
    !stoppedView.includes("Reader B"), stoppedView);
  await shoot("tabs-stopped", '[data-account="stopped"]');
  await go("/credits");
  await sleep(500);
  check("a stopped tab reads nothing either, whatever page it is sent to",
    mock.requests.length === requestsBefore && await exists('[data-account="stopped"]'));
  await go("/sources/new");
  await clickText('[data-account="stopped"] button', "Sign in again");
  await waitFor(`!!document.querySelector('.shell-form input[name="password"]')`);
  await signIn("reader-a");
  await waitFor(`!!document.querySelector('[data-recovered="source"]')`);
  check("MOCK: signing in again as Reader A gives the typed source back, unsaved, in Reader A's form",
    JSON.stringify(await sourceOn()) === JSON.stringify(SOURCE) && users["reader-b"].sources.size === bSourcesBefore);
  check("tab 2, opened for Reader B, is now told the same way", await waitFor2(`!!document.querySelector('[data-account="elsewhere"]')`));
  const logoutsBefore = posts("/logout").length;
  await evaluate2(`document.querySelector(".account-strip button").click()`);
  await waitFor2(`!!document.querySelector('[data-account="stopped"]')`);
  check("Sign out in tab 2 ends nobody's session: Reader A's, signed in now, stays", posts("/logout").length === logoutsBefore &&
    (await evaluate2(`document.querySelector('[data-account="stopped"]')?.textContent.includes("Reader B (synthetic)")`)));
  const aSourcesBefore = users["reader-a"].sources.size;
  await click(".client-save-source");
  check("MOCK: back as Reader A, tab 1 saves the source once, to Reader A", await waitFor(`/^\\/sources\\/2026/.test(location.pathname)`) &&
    users["reader-a"].sources.size === aSourcesBefore + 1 && users["reader-b"].sources.size === bSourcesBefore);
  // The race no announcement can close: the browser's session becomes Reader B's without any tab saying so (the MOCK
  // changes whose session tab 1's cookie names), and tab 1 saves. The save names Reader A (account binding), so the
  // server refuses it before anything is written (401 account_changed): Reader B gains nothing, and tab 1 stops,
  // keeping the typed source for Reader A.
  await open("/sources/new");
  await typeSource();
  const token = [...mock.tokens].filter(([, name]) => name === "reader-a").at(-1)[0];
  mock.tokens.set(token, "reader-b");
  const bRaced = users["reader-b"].sources.size;
  await click(".client-save-source");
  await waitFor(`!!document.querySelector('[data-account="stopped"]')`);
  const raced = posts("/sources").at(-1);
  const shown = await evaluate("document.body.innerText");
  check("MOCK: a save bound to Reader A after an unannounced switch to Reader B is refused as account_changed; nothing is saved for Reader B and tab 1 stops with the text kept",
    raced.status === 401 && raced.bound === users["reader-a"].session.user.user_id &&
    users["reader-b"].sources.size === bRaced && await exists('[data-account="stopped"]') && !shown.includes("Reader B") &&
    (await evaluate(`[...document.querySelectorAll(".client-ended-text")].map((t) => t.value).join("|")`)).includes(SOURCE.source_text),
    JSON.stringify({ status: raced.status, bound: raced.bound, shown: shown.slice(0, 200) }));
  mock.tokens.set(token, "reader-a");
  ws2.close();

  // 9. Boundaries.
  const stored = await evaluate(`JSON.stringify({ local: Object.entries(localStorage), session: Object.entries(sessionStorage) })`);
  check("nothing was kept in browser storage", stored === '{"local":[],"session":[]}', stored);
  check("every write carried this page's origin and its header", mock.forbidden === 0);
  check("every request to the user routes named the tab's account (account binding)", mock.unbound === 0,
    `${mock.unbound} unbound`);
  check("the page requested nothing outside the local server", outside.length === 0, outside.join(", "));
  check("no page error", pageErrors.length === 0, pageErrors.join(" | "));
  ws.close();
} catch (error) {
  check("the recovery browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  server.close();
  await sleep(400);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
