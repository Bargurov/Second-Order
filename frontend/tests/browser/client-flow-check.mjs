// Browser check of the user Client (frontend/dist-client) in one headless Chrome, against a MOCK of the user contract
// (user-api-0.1) that runs inside this script: the built Client bundle is served as the server will serve it, and
// /api/session and /api/user/* are answered from the SYNTHETIC user-contract fixtures and two synthetic users, with
// the contract's refusals. Every server-side behaviour seen here (quotes, credits, daily limits, ownership, expiry,
// repeats) is the MOCK's: this proves what the Client shows and sends, never what the real server enforces. That is
// the combined integration gate's job.
//
// The journey: sign in -> the account strip, styled, with Sign out reachable by keyboard -> allowance from the server
// -> add a source, reached by keyboard (focus on the new page's title), its address checked before saving -> choose an
// Effort, prepare (focus on the analysis's title), quote by keyboard (focus on the quote) -> another Effort is a
// separate analysis without the quote -> an
// expired quote is refused and re-quoted only on request -> a run whose reply is lost is never re-sent, its header says
// the outcome is unknown until a successful read, and approving again is answered as a repeat -> evidence, interpretation and
// unknowns -> a review version, a conflicting one kept as typed -> held and unsent analyses offer no run -> reloads
// write nothing -> the session ends with unsaved notes shown -> a second user: someone else's analysis is Not Found,
// an Effort withdrawn, today's allowance used, not enough credits -> phone and tablet width (a recorded outcome on the
// first screen), outside requests, page errors, and the built bundle's contents. One run is approved and sent by
// keyboard alone, and focus follows each step: the quote to read, then the outcome.
//
//   cd frontend; npm run build; node tests/browser/client-flow-check.mjs
import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
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
const CONTRACT = "user-api-0.1";
const PASSWORD = "synthetic-password";
const ADMIN_ONLY = /claude|sonnet|opus|haiku|anthropic|openai|\$\s?\d|\busd\b|dollar|\btokens?\b|\bcosts?\b|\bproviders?\b|\bmodels?\b|http status|planning estimate/i;
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};

// ---------------------------------------------------------------- the MOCK server (synthetic data only)

const errors = fixture("user-contract-errors");
const source = fixture("user-contract-source-created").source;
const recordedHigh = fixture("user-contract-run-recorded").analysis;
const recordedLow = fixture("user-contract-analysis-no-finding").analysis;
const declined = fixture("user-contract-analysis-declined").analysis;
const preparedTemplate = fixture("user-contract-analysis-prepared").analysis;
const CREDITS = { low: 3, medium: 4, high: 6 };
const seeded = ["analysis-declined", "analysis-invalid", "analysis-failed", "analysis-unresolved", "analysis-not-sent"]
  .map((name) => fixture(`user-contract-${name}`).analysis);

function newUser(session, account, analyses) {
  const sources = new Map(analyses.map((item) => [item.source.source_id, copy(item.source)]));
  return { session, account, analyses: new Map(analyses.map((item) => [item.analysis_id, copy(item)])), sources };
}
const users = {
  "reader-a": newUser(fixture("user-contract-session-signed-in"), fixture("user-contract-account"), seeded),
  "reader-b": newUser(fixture("client-session-reader-b"), fixture("client-account-reader-b"), []),
};
const mock = { tokens: new Map(), expired: new Set(), requests: [], forbidden: 0, unbound: 0, dispatches: 0, holdRun: 0,
               promptVersion: "research-prompt-1",
               dropRunReply: false, expireNextQuote: false, failNextAnalysisRead: false, failNextRunBeforeSend: false };
const summary = (item) => ({ analysis_id: item.analysis_id, effort: item.effort, prepared_at: item.prepared_at,
  source: { source_id: item.source.source_id, headline: item.source.headline, published_at: item.source.published_at },
  state: item.state, outcome: item.state === "recorded" ? item.result.outcome : null,
  review_status: item.reviews.at(-1)?.status ?? null, credits_charged: item.charge?.credits_charged ?? null });
const withoutText = ({ text, ...rest }) => rest;
const STATUS = { not_signed_in: 401, session_expired: 401, invalid_credentials: 401, account_changed: 401,
  account_binding_required: 428, forbidden: 403, not_found: 404, payload_too_large: 413, invalid_request: 422,
  invalid_source: 422, invalid_review: 422, sending_disabled: 503, accounts_unavailable: 503, internal_error: 500 };
  // Every other code is 409 (contract section 9).
const refuse = (code, extra = {}) => ({ status: STATUS[code] ?? 409, body: { ...copy(errors[code]), ...extra } });

function recordedFor(prepared, quote) {
  const template = prepared.effort === "high" ? recordedHigh : prepared.effort === "low" ? recordedLow
    : { ...declined, source: prepared.source };
  return { ...copy(template), analysis_id: prepared.analysis_id, effort: prepared.effort, prepared_at: prepared.prepared_at,
           source: copy(prepared.source), reviews: [], quote: null,
           charge: { credits_reserved: quote.credits, credits_charged: quote.credits, credits_returned: 0,
                     state: "charged", quota_day: prepared.charge?.quota_day ?? "2026-10-14" } };
}

async function api(method, path, body, user, request, response) {
  if (path === "/api/session" && method === "GET") {
    if (!user) return { status: 200, body: fixture(mock.expiredCookie ? "user-contract-session-expired" : "user-contract-session-signed-out") };
    return { status: 200, body: user.session };
  }
  if (path === "/api/session/login") {
    const found = users[body?.username];
    if (!found || body.password !== PASSWORD) return refuse("invalid_credentials");
    const token = randomBytes(16).toString("hex");
    mock.tokens.set(token, body.username);
    response.setHeader("Set-Cookie", `second_order_session=${token}; HttpOnly; SameSite=Strict; Path=/`);
    return { status: 200, body: found.session };
  }
  if (path === "/api/session/logout") return { status: 200, body: { ...fixture("user-contract-session-signed-out"), reason: "signed_out" } };
  if (!user) return refuse(mock.expiredCookie ? "session_expired" : "not_signed_in");
  const account = user.account;
  const parts = path.split("/").slice(3).map(decodeURIComponent);  // ["account"] | ["sources", id] | ["analyses", id, "quotes"]
  if (method === "GET" && parts[0] === "account") return { status: 200, body: account };
  if (parts[0] === "sources") {
    if (method === "POST") {
      if (body.source_text !== source.text || body.published_at !== source.published_at_as_supplied) return refuse("invalid_source");
      user.sources.set(source.source_id, copy(source));
      return { status: 201, body: { contract: CONTRACT, source } };
    }
    if (parts.length === 1) return { status: 200, body: { contract: CONTRACT, sources: [...user.sources.values()].map(withoutText) } };
    const own = user.sources.get(parts[1]);
    if (!own) return refuse("not_found");
    return { status: 200, body: { contract: CONTRACT, source: own,
      analyses: [...user.analyses.values()].filter((item) => item.source.source_id === own.source_id).map(summary) } };
  }
  if (parts[0] !== "analyses") return refuse("not_found");
  if (parts.length === 1 && method === "GET") return { status: 200, body: { contract: CONTRACT, analyses: [...user.analyses.values()].map(summary) } };
  if (parts.length === 1 && method === "POST") {
    const own = user.sources.get(body.source_id);
    if (!own) return refuse("not_found");
    if (!account.efforts.some((option) => option.effort === body.effort)) return refuse("unsupported_effort", { efforts: account.efforts });
    const id = `${own.source_id}.${mock.promptVersion}.${body.effort}`;
    if (user.analyses.has(id)) return { status: 200, body: { contract: CONTRACT, created: false, analysis: user.analyses.get(id) } };
    const made = { ...copy(preparedTemplate), analysis_id: id, effort: body.effort, prepared_at: new Date().toISOString(),
                   source: copy(own) };
    user.analyses.set(id, made);
    return { status: 201, body: { contract: CONTRACT, created: true, analysis: made } };
  }
  const analysis = user.analyses.get(parts[1]);
  if (!analysis) return refuse("not_found");
  if (method === "GET" && parts.length === 2) {
    if (mock.failNextAnalysisRead) {  // One failed read of the analysis (a 5xx): it proves nothing either way.
      mock.failNextAnalysisRead = false;
      return refuse("internal_error");
    }
    return { status: 200, body: { contract: CONTRACT, analysis } };
  }
  if (method === "GET" && parts[2] === "export") return { status: 200, body: { contract: CONTRACT, exported_at: new Date().toISOString(), analysis } };
  if (method === "GET" && parts[2] === "quality") {  // The research checks (a read): canonical, nothing flagged.
    return { status: 200, body: { contract: CONTRACT, quality: analysis.result?.analysis ? copy(fixture("news-contract-quality").quality) : null } };
  }
  if (method === "POST" && parts[2] === "quotes") {
    if (analysis.state !== "prepared") return refuse("already_attempted");
    if (!account.efforts.some((option) => option.effort === analysis.effort)) return refuse("unsupported_effort", { efforts: account.efforts });
    const issued = new Date();
    analysis.quote = { quote_id: `q-${randomBytes(12).toString("hex")}`, analysis_id: analysis.analysis_id,
      effort: analysis.effort, credits: CREDITS[analysis.effort], policy_version: "credit-policy-1",
      issued_at: issued.toISOString(), expires_at: new Date(issued.getTime() + 900_000).toISOString(), state: "active" };
    return { status: 201, body: { contract: CONTRACT, quote: analysis.quote, account } };
  }
  if (method === "POST" && parts[2] === "runs") {
    if (body.approve !== true) return refuse("invalid_request");
    if (analysis.ranWith === body.quote_id) return { status: 200, body: { contract: CONTRACT, duplicate: true, analysis, account } };
    const quote = analysis.quote;
    if (!quote || quote.quote_id !== body.quote_id || quote.effort !== body.effort || quote.credits !== body.credits) return refuse("quote_mismatch");
    if (mock.expireNextQuote) {
      mock.expireNextQuote = false;
      quote.state = "expired";
    }
    if (quote.state === "expired") return refuse("quote_expired");
    if (account.daily.remaining === 0) return refuse("daily_limit_reached", { daily: account.daily, resets_at: account.daily.resets_at });
    if (account.credits.available < quote.credits) return refuse("insufficient_credits", { credits: account.credits });
    if (mock.failNextRunBeforeSend) {  // A 5xx before anything is reserved or sent: the page cannot know that.
      mock.failNextRunBeforeSend = false;
      return refuse("sending_disabled");
    }
    // Reserve, "send" once (the MOCK's stand-in for the dispatch it never makes), record, settle.
    account.credits.available -= quote.credits;
    account.daily.used += 1;
    account.daily.remaining -= 1;
    analysis.ranWith = quote.quote_id;
    mock.dispatches += 1;
    Object.assign(analysis, { state: "running", quote: null, state_detail: "Running: the request has been sent once.",
      charge: { credits_reserved: quote.credits, credits_charged: null, credits_returned: null, state: "held", quota_day: account.daily.day } });
    if (mock.holdRun) await sleep(mock.holdRun);
    const done = recordedFor(analysis, quote);
    Object.assign(analysis, done);
    if (mock.dropRunReply) {
      mock.dropRunReply = false;
      request.socket.destroy();  // The reply is lost after the attempt was recorded.
      return null;
    }
    return { status: 201, body: { contract: CONTRACT, duplicate: false, analysis, account } };
  }
  if (method === "POST" && parts[2] === "reviews") {
    if (analysis.state !== "recorded") return refuse("no_result");
    if (body.result_sha256 !== analysis.result_sha256) return refuse("result_changed");
    if (body.parent_review_id !== (analysis.reviews.at(-1)?.review_id ?? null)) return refuse("review_conflict");
    if (body.status === null && !String(body.notes).trim()) return refuse("invalid_review");
    const review = { review_id: `r-${randomBytes(12).toString("hex")}`, sequence: analysis.reviews.length + 1,
      parent_review_id: body.parent_review_id, saved_at: new Date().toISOString(), status: body.status, notes: body.notes,
      result_sha256: analysis.result_sha256, reviewer: { user_id: user.session.user.user_id, display_name: user.session.user.display_name } };
    analysis.reviews.push(review);
    return { status: 201, body: { contract: CONTRACT, review, analysis } };
  }
  return refuse("not_found");
}

const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".woff": "font/woff",
                ".woff2": "font/woff2", ".svg": "image/svg+xml", ".png": "image/png" };
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
  const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : null;
  const token = /second_order_session=([0-9a-f]+)/.exec(request.headers.cookie ?? "")?.[1];
  mock.expiredCookie = Boolean(token && mock.expired.has(token));
  const user = token && !mock.expired.has(token) ? users[mock.tokens.get(token)] : null;
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
  } else if (userRoute && user && bound !== undefined && bound !== user.session.user.user_id) {
    reply = refuse("account_changed");
  } else if (userRoute && user && request.method === "POST" && bound === undefined) {
    reply = refuse("account_binding_required");
  } else {
    reply = await api(request.method, url.pathname, body, user, request, response);
  }
  mock.requests.push({ method: request.method, path: url.pathname, user: user?.session.user.username ?? null,
                       status: reply?.status ?? "dropped", body: reply ? JSON.stringify(reply.body) : "", sent: body,
                       bound: bound ?? null });
  if (!reply) return;
  // Every connection closes after its reply. Chrome re-sends a request, POST included, once by itself when a REUSED
  // connection closes before any reply; on a fresh connection a lost reply stays lost, which is the case tested here.
  // (Observed while writing this check: that browser re-send reached the MOCK as a repeat of the same approval, and
  // the contract's duplicate rule answered it without a second dispatch. The real server must do the same.)
  response.writeHead(reply.status, { "Content-Type": "application/json", Connection: "close" });
  response.end(JSON.stringify(reply.body));
});

// ---------------------------------------------------------------- the browser

const root = mkdtempSync(join(tmpdir(), "second-order-client-check-"));
const children = [];
const posts = (part = "") => mock.requests.filter((item) => item.method === "POST" && item.path.includes(part)).length;
try {
  await new Promise((done) => server.listen(0, "127.0.0.1", done));
  base = `http://127.0.0.1:${server.address().port}`;
  const profile = join(root, "chrome");
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
  const browserRequests = [];
  const pageErrors = [];
  const dialogs = [];
  const blockedPrompts = [];
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else if (message.method === "Network.requestWillBeSent") {
      browserRequests.push(message.params.request.url);
    } else if (message.method === "Runtime.exceptionThrown") {
      pageErrors.push(message.params.exceptionDetails.text);
    } else if (message.method === "Log.entryAdded" && message.params.entry.level === "error") {
      const entry = message.params.entry;
      // Attributed, not ignored: a refused or dropped API request is logged by the browser (the scenario), and Chrome
      // blocks the unsaved-text prompt on a scripted navigation without a user gesture (the guard working).
      if (/Blocked attempt to show a 'beforeunload' confirmation panel/.test(entry.text)) blockedPrompts.push(entry.url);
      else if (!(/status of (4\d\d)|ERR_EMPTY_RESPONSE|Failed to load resource/.test(entry.text) &&
                 String(entry.url ?? "").startsWith(`${base}/api/`))) pageErrors.push(`${entry.text} ${entry.url ?? ""}`);
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
  const clickText = (selector, text) => evaluate(`(() => { const e = [...document.querySelectorAll(${JSON.stringify(selector)})]
    .find((item) => item.textContent.includes(${JSON.stringify(text)})); if (!e) return false; e.click(); return true; })()`);
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);
  const exists = (selector) => evaluate(`!!document.querySelector(${JSON.stringify(selector)})`);
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete'");
  };
  const pageWords = () => evaluate("document.body.innerText");
  const vocabulary = [];
  const scan = async (label) => {
    const words = await pageWords();
    const match = ADMIN_ONLY.exec(words);
    if (match) vocabulary.push(`${label}: ${match[0]}`);
  };
  const shots = process.env.SECOND_ORDER_SCREENSHOTS;
  const shoot = async (name, selector) => {  // Opt-in, bounded per-section clips; never a whole tall page.
    if (!shots) return;
    await evaluate(`document.querySelector(${JSON.stringify(selector)})?.scrollIntoView({ block: "start" })`);
    await sleep(250);
    const box = await evaluate(`(() => { const r = document.querySelector(${JSON.stringify(selector)})?.getBoundingClientRect();
      return r && { x: r.left, y: r.top + scrollY, width: r.width, height: Math.min(r.height, 2200) }; })()`);
    if (!box) return;
    const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip: { ...box, scale: 1 } });
    writeFileSync(join(shots, `${name}.png`), Buffer.from(shot.data, "base64"));
  };
  const waitMock = async (predicate, timeout = 10000) => {  // A condition on the MOCK's own records.
    for (const start = Date.now(); Date.now() - start < timeout; await sleep(40)) if (predicate()) return true;
    return false;
  };
  const tab = async (backwards = false) => {  // A real Tab key press, so :focus-visible applies as for a keyboard user.
    const key = { key: "Tab", code: "Tab", windowsVirtualKeyCode: 9, modifiers: backwards ? 8 : 0 };
    await send("Input.dispatchKeyEvent", { type: "keyDown", ...key });
    await send("Input.dispatchKeyEvent", { type: "keyUp", ...key });
  };
  const KEYS = { Enter: { key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, text: "\r" },
                 Space: { key: " ", code: "Space", windowsVirtualKeyCode: 32, text: " " } };
  const press = async (name) => {  // A real key press on whatever has focus: Enter activates, Space toggles.
    const { text: typed, ...key } = KEYS[name];
    await send("Input.dispatchKeyEvent", { type: "keyDown", ...key, text: typed });
    await send("Input.dispatchKeyEvent", { type: "keyUp", ...key });
  };
  const tabTo = async (selector, presses = 8) => {  // Tab forward until focus reaches `selector`; false if it never does.
    for (let count = 0; count < presses; count++) {
      await tab();
      if (await evaluate(`document.activeElement?.matches(${JSON.stringify(selector)}) ?? false`)) return true;
    }
    return false;
  };
  const focused = () => evaluate(`(() => { const active = document.activeElement;
    if (!active || active === document.body) return { on: "body" };
    const box = active.getBoundingClientRect();
    return { on: active.dataset.focusTarget ?? (active.matches("h1.client-title") ? "title" : active.tagName.toLowerCase()),
             text: active.textContent.trim().slice(0, 60), inView: box.top >= 0 && box.top < innerHeight,
             ring: getComputedStyle(active).outlineStyle }; })()`);
  const header = async () => ({ chip: await text(".client-header .client-chip.is-state"),
    state: await evaluate(`document.querySelector(".client-header .client-chip.is-state")?.dataset.state`),
    outcome: await exists(".client-header .client-chip.is-outcome") });
  const signIn = async (username) => {
    await open("/sign-in");  // Signed out, `/` is the landing page (docs/onboarding-contract.md section 7).
    await waitFor(`!!document.querySelector('input[name="username"]')`);
    await setValue('input[name="username"]', username);
    await setValue('input[name="password"]', PASSWORD);
    await click(".shell-form button[type=submit]");
    // A reader lands on the News home (docs/news-stories-contract.md section 7); the allowance is on /analyses.
    if (!await waitFor(`document.querySelector("main.page.client")?.dataset.view === "news"`)) return false;
    await open("/analyses");
    return waitFor(`!!document.querySelector(".client-entitlements dd")`);
  };

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Log.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  // 1. Sign in; the allowance is the server's; the history shows only reads.
  check("Reader A signs in through the shared shell and sees the Client", await signIn("reader-a"));
  const strip = await evaluate(`(() => { const strip = document.querySelector(".account-strip");
    const button = strip?.querySelector("button"); if (!strip || !button) return null;
    const style = getComputedStyle(strip), look = getComputedStyle(button), bar = document.querySelector(".topbar");
    return { text: strip.textContent, buttons: strip.querySelectorAll("button").length, button: button.textContent,
             display: style.display, rule: style.borderBottomStyle, width: strip.getBoundingClientRect().width,
             bar: bar.getBoundingClientRect().width, frame: look.borderTopStyle, fill: look.backgroundColor }; })()`);
  check("the account strip is the Client's own: who is signed in, aligned with the topbar, Sign out its one quiet button",
    strip?.text.includes("Signed in as Reader A (synthetic)") && strip.buttons === 1 && strip.button === "Sign out" &&
    strip.display === "flex" && strip.rule === "solid" && Math.abs(strip.width - strip.bar) < 1 &&
    strip.frame === "none" && strip.fill === "rgba(0, 0, 0, 0)", JSON.stringify(strip));
  let reached = false;
  for (let press = 0; press < 12 && !reached; press++) {
    await tab();
    reached = await evaluate(`document.activeElement === document.querySelector(".account-strip button")`);
  }
  check("Sign out is reached by Tab and shows a visible focus ring", reached &&
    await evaluate(`(() => { const style = getComputedStyle(document.activeElement);
      return document.activeElement.matches(":focus-visible") && style.outlineStyle === "solid" &&
        parseFloat(style.outlineWidth) >= 2; })()`));
  await evaluate("document.activeElement.blur()");
  check("MOCK: the allowance repeats the server's credits, daily remainder and reset in the quota time zone",
    (await text('[data-entitlement="credits"]')) === "40 credits available" &&
    (await text('[data-entitlement="daily"]')).startsWith("3 of 3 analyses left today") &&
    (await text('[data-entitlement="reset"]')).includes("15 Oct 2026, 00:00 (Asia/Jerusalem)") &&
    (await text('[data-entitlement="reset"]')).includes("14 Oct 2026, 21:00 UTC"));
  await waitFor(`document.querySelectorAll(".client-history-row").length === 5`);
  check("the history lists the user's analyses, and opening the page wrote nothing",
    (await evaluate(`document.querySelectorAll(".client-history-row").length`)) === 5 && posts() === 1);
  await scan("home");
  await shoot("client-home", "main.client");

  // 2. Add a source, reached from the navigation by keyboard: the new page's title takes focus once it is shown.
  await evaluate(`document.querySelector('.site-nav a[href="/sources/new"]').focus()`);
  await press("Enter");
  await waitFor(`!!document.querySelector(".client-form")`);
  await waitFor(`document.activeElement?.matches("h1.client-title") ?? false`, 3000);
  const arrived = await focused();
  check("following a section link by keyboard puts focus on the new page's title, without a ring around it",
    arrived.on === "title" && arrived.text === "Add a source" && arrived.ring === "none", JSON.stringify(arrived));
  check("the source form states the server's limits: 50,000 characters in any script, a one-line headline of 1,500",
    /50,000 characters in any script/.test(await text("[data-source-size]")) &&
    /one line, up to 1,500 characters/.test(await text("[data-headline-note]")));
  await setValue('input[name="headline"]', "😀".repeat(1_501));
  check("a headline over 1,500 characters, counted as the server counts them, is marked and cannot be saved",
    (await text("[data-headline-note]")) === "The headline has 1,501 of 1,500 characters." &&
    await evaluate(`document.querySelector(".client-save-source").disabled`) && posts("/sources") === 0);
  await setValue('input[name="headline"]', source.headline);
  const address = async (typed) => {
    await setValue('input[name="source_url"]', typed);
    return { note: await text("[data-source-url-note]"), saveable: !(await evaluate(`document.querySelector(".client-save-source").disabled`)),
             invalid: await evaluate(`document.querySelector('input[name="source_url"]').getAttribute("aria-invalid")`) };
  };
  const addressNote = await address("");
  const otherScheme = await address("ftp://example.invalid/synthetic.txt");
  const incomplete = await address("example.invalid/synthetic");
  const tooLong = await address(`https://example.invalid/${"é".repeat(1_030)}`);  // 24 + 2 × 1,030 = 2,084 bytes.
  check("beside the address, before saving: an http(s) address of at most 2,083 characters as the server counts them; anything else is marked and cannot be saved",
    addressNote.note === "Where it was published: a web address beginning with https:// or http://, at most 2,083 " +
      "characters, where a character outside basic Latin counts as two to four." &&
    addressNote.invalid === null && otherScheme.note.startsWith("Only a web address beginning with https:// or http://") &&
    otherScheme.invalid === "true" && !otherScheme.saveable && incomplete.note.startsWith("Not a complete web address yet") &&
    !incomplete.saveable && tooLong.note.startsWith("The address counts as 2,084 characters") && tooLong.invalid === "true" &&
    !tooLong.saveable && posts("/sources") === 0, JSON.stringify({ addressNote, otherScheme, incomplete, tooLong }));
  const accepted = await address(source.source_url);
  check("the source's own https address is accepted, and the note returns",
    accepted.note === addressNote.note && accepted.invalid === null, JSON.stringify(accepted));
  await setValue('input[name="date"]', "2026-10-13");
  await setValue('input[name="time"]', "10:00");
  await setValue('select[name="offset"]', "+03:00");
  await setValue('textarea[name="source_text"]', source.text);
  await click(".client-save-source");
  check("saving the source sends it once, exactly as typed, and opens its page",
    await waitFor(`location.pathname === "/sources/${encodeURIComponent(source.source_id)}"`) && posts("/sources") === 1 &&
    mock.requests.find((item) => item.path === "/api/user/sources" && item.method === "POST").status === 201);

  // 3. Effort first, then prepare; nothing is chosen for the person.
  await waitFor(`document.querySelectorAll('input[name="effort"]').length === 3`);
  check("the Effort options are exactly the server's, with none chosen and preparing disabled until one is",
    JSON.stringify(await evaluate(`[...document.querySelectorAll('input[name="effort"]')].map((e) => e.value)`)) ===
      JSON.stringify(["low", "medium", "high"]) &&
    !(await evaluate(`[...document.querySelectorAll('input[name="effort"]')].some((e) => e.checked)`)) &&
    await evaluate(`document.querySelector(".client-prepare").disabled`));
  await click('input[name="effort"][value="high"]');
  await click(".client-prepare");
  const highId = `${source.source_id}.research-prompt-1.high`;
  check("preparing the High Effort analysis is one request and opens it, not quoted or run",
    await waitFor(`location.pathname === "/analyses/${encodeURIComponent(highId)}"`) && posts("/api/user/analyses") === 1 &&
    await waitFor(`!!document.querySelector(".client-get-quote")`) && posts("/quotes") === 0);
  check("beside 'Get a credit quote', a link explains how credits work",
    await exists('.client-quote a[href="/credits"]'));
  await waitFor(`document.activeElement?.matches("h1.client-title") ?? false`, 3000);
  const prepared = await focused();
  check("after preparing, focus is on the opened analysis's title, not left on the control that has gone",
    prepared.on === "title" && prepared.text === source.headline, JSON.stringify(prepared));
  check("while a quote is still to decide, the allowance stands right after the analysis's state",
    await evaluate(`document.querySelector(".client-state").nextElementSibling?.matches(".client-entitlements") ?? false`));
  const toQuote = await tabTo(".client-get-quote", 6);
  await press("Enter");
  await waitFor(`!!document.querySelector(".client-approve input")`);
  await waitFor(`document.activeElement?.dataset.focusTarget === "quote"`, 3000);
  const quoteFocus = await focused();
  check("by keyboard: Tab reaches 'Get a credit quote', Enter asks once, and focus moves to the quote to read",
    toQuote && posts("/quotes") === 1 && quoteFocus.on === "quote" && quoteFocus.text.startsWith("Quote · approve it to run") &&
    quoteFocus.inView && quoteFocus.ring === "none" &&
    (await evaluate(`document.querySelector('[data-focus-target="quote"]').getAttribute("aria-label")`)) ===
      "Credit quote: read it, then approve to run", JSON.stringify({ toQuote, quoteFocus }));
  check("MOCK: the server's quote names its credits; the approval starts unchecked and Run is disabled",
    (await text("[data-quote-credits]")) === "6" &&
    !(await evaluate(`document.querySelector(".client-approve input").checked`)) &&
    await evaluate(`document.querySelector(".client-run").disabled`) &&
    (await text(".client-approve")).includes("never charged more than 6 credits"));
  await scan("quote");
  await shoot("client-quote", "main.client");

  // 4. Another Effort is another analysis, without this quote.
  await open(`/sources/${encodeURIComponent(source.source_id)}`);
  await waitFor(`document.querySelectorAll('input[name="effort"]').length === 3`);
  await click('input[name="effort"][value="low"]');
  await click(".client-prepare");
  const lowId = `${source.source_id}.research-prompt-1.low`;
  check("choosing Low prepares a separate analysis that offers only a fresh quote",
    await waitFor(`location.pathname === "/analyses/${encodeURIComponent(lowId)}"`) &&
    await waitFor(`!!document.querySelector(".client-get-quote")`) && !(await exists(".client-approve")));
  await open(`/analyses/${encodeURIComponent(highId)}`);
  await waitFor(`!!document.querySelector(".client-approve input")`);
  check("back on High, its own active quote is shown again and the approval is not carried over",
    !(await evaluate(`document.querySelector(".client-approve input").checked`)));

  // 5. An expired quote: refused by the server, re-quoted only on request.
  mock.expireNextQuote = true;
  await click(".client-approve input");
  await click(".client-run");
  await waitFor(`!!document.querySelector('[data-code="quote_expired"]')`);
  check("MOCK: an expired quote is refused; the page asks for a new quote and sends nothing else",
    (await text('[data-code="quote_expired"]')).includes("The quote has expired") && mock.dispatches === 0 &&
    !(await exists(".client-approve")) && posts("/runs") === 1 && posts("/quotes") === 1);
  await clickText("[data-code=quote_expired] button", "Get a new quote");
  await waitFor(`!!document.querySelector(".client-approve input")`);
  check("a new quote comes only from the explicit request", posts("/quotes") === 2);

  // 6. A lost run reply: the page offers only a read until the server says what happened, and never a second run.
  mock.holdRun = 1200;
  mock.dropRunReply = true;
  await click(".client-approve input");
  await click(".client-run");
  await waitFor(`document.querySelector(".client-run")?.textContent.includes("Running")`);
  await click(".client-run");  // Disabled while in flight.
  const runningNote = await text(".client-quote");
  check("while running, the note promises one attempt and points to reading again, not to a recorded outcome",
    runningNote.includes("It is sent once and never again") && runningNote.includes("read this page again") &&
    !/either way|is recorded|does not stop/.test(runningNote), runningNote);
  await waitFor(`document.querySelector("[data-panel]")?.dataset.panel === "uncertain"`, 15000);
  const gate = { runs: posts("/runs"), dispatches: mock.dispatches, note: await text("[data-uncertain]"),
                 controls: await exists(".client-approve, .client-run, .client-get-quote"),
                 notice: await text(".client-notice.is-unconfirmed"), state: await text(".client-state"),
                 buttons: await evaluate(`[...document.querySelectorAll(".client-state button")].map((b) => b.textContent)`) };
  check("a lost run reply leaves only 'Check again': no quote, approval or run control, and nothing re-sent",
    gate.runs === 2 && gate.dispatches === 1 && !gate.controls && gate.notice.includes("Nothing was retried") &&
    gate.notice.match(/Nothing was retried/g).length === 1 && !gate.state.includes("Nothing has been run") &&
    gate.note.includes("does not know whether it was sent") && JSON.stringify(gate.buttons) === '["Check again"]',
    JSON.stringify(gate));
  const unknown = '{"chip":"Run outcome unknown","state":"uncertain","outcome":false}';
  const lostHeader = await header();
  check("the header agrees: 'Run outcome unknown', never the stale 'Prepared · not run'",
    JSON.stringify(lostHeader) === unknown && !(await text("main.client")).includes("Prepared · not run"),
    JSON.stringify(lostHeader));
  await shoot("client-run-uncertain", ".client-state");
  await click(".client-approve input");  // Absent: these do nothing.
  await click(".client-run");
  await sleep(300);
  check("pressing where the approval and Run were sends nothing", posts("/runs") === 2);
  mock.failNextAnalysisRead = true;
  const readsBefore = mock.requests.filter((item) => item.method === "GET" && item.path.endsWith(encodeURIComponent(highId))).length;
  await click("[data-uncertain] .client-check");
  await waitMock(() => mock.requests.filter((item) => item.method === "GET" &&
    item.path.endsWith(encodeURIComponent(highId))).length > readsBefore);
  await waitFor(`!!document.querySelector(".client-notice.is-unconfirmed") &&
    !document.querySelector("[data-uncertain] .client-check")?.disabled`);
  check("MOCK: a failed read keeps the gate: still only 'Check again', still no second run, the header still unknown",
    (await evaluate(`document.querySelector("[data-panel]").dataset.panel`)) === "uncertain" &&
    !(await exists(".client-approve, .client-run, .client-get-quote")) && posts("/runs") === 2 &&
    JSON.stringify(await header()) === unknown);
  await click("[data-uncertain] .client-check");
  await waitFor(`!!document.querySelector("[data-panel=recorded]")`, 15000);
  check("MOCK: a successful read shows the run was recorded; Run stays unavailable and nothing was sent twice",
    !(await exists(".client-approve, .client-run, .client-get-quote")) && posts("/runs") === 2 && mock.dispatches === 1);
  const readHeader = await header();
  check("only that read gives the header the server's state and outcome",
    readHeader.chip === "Recorded" && readHeader.state === "recorded" && readHeader.outcome, JSON.stringify(readHeader));
  mock.holdRun = 0;
  // Network replay, in this harness and not through the page: the same approval POST, with the page's account binding,
  // arrives twice more.
  const lostRun = mock.requests.find((item) => item.path.endsWith("/runs") && item.status === "dropped");
  const tokenA = [...mock.tokens].filter(([, name]) => name === "reader-a").at(-1)[0];
  const ledger = () => ({ dispatches: mock.dispatches, ...users["reader-a"].account.credits, used: users["reader-a"].account.daily.used });
  const beforeReplay = ledger();
  const replays = await Promise.all([1, 2].map(() => fetch(base + lostRun.path, { method: "POST", body: JSON.stringify(lostRun.sent),
    headers: { Origin: base, "Content-Type": "application/json", "X-Second-Order-User": "1",
               "X-Second-Order-Account": lostRun.bound, Cookie: `second_order_session=${tokenA}` } })
    .then(async (reply) => ({ status: reply.status, body: await reply.json() }))));
  check("MOCK network replay: the same approval POST arriving twice more is a repeat; one dispatch, no second debit",
    replays.every((reply) => reply.status === 200 && reply.body.duplicate === true) &&
    JSON.stringify(ledger()) === JSON.stringify(beforeReplay), JSON.stringify({ replays: replays.map((r) => r.status), beforeReplay, after: ledger() }));

  // 7. The result.
  const evidence = await evaluate(`({ statements: document.querySelectorAll(".client-evidence [data-statement]").length,
    quotes: document.querySelectorAll(".client-evidence blockquote").length,
    marks: document.querySelectorAll(".client-marked-text mark").length,
    label: document.querySelector(".client-interpretation .client-label")?.textContent,
    unknowns: [...document.querySelectorAll(".client-unknowns h3")].map((h) => h.textContent),
    looks: ["client-evidence", "client-interpretation", "client-unknowns"].map((name) => {
      const style = getComputedStyle(document.querySelector("." + name));
      return [style.backgroundColor, style.borderTopStyle, style.borderTopColor].join("|"); }) })`);
  check("evidence, interpretation and unknowns are three different surfaces, with the quoted passages marked",
    evidence.statements === recordedHigh.result.analysis.established.length && evidence.quotes === 4 && evidence.marks >= 1 &&
    evidence.label === "Generated interpretation, not the publisher's words" && new Set(evidence.looks).size === 3 &&
    JSON.stringify(evidence.unknowns) === JSON.stringify(["Assumptions", "Competing explanations", "Missing information",
                                                          "What would test it", "Earlier baseline"]), JSON.stringify(evidence));
  check("MOCK: the charge and the balance after the run are the server's figures",
    (await text(".client-charge")).startsWith("6 credits charged of 6 credits reserved") &&
    (await text('[data-entitlement="credits"]')) === "34 credits available");
  await open("/analyses");
  await waitFor(`document.querySelector('[data-entitlement="credits"]')?.textContent === "34 credits available"`);
  check("MOCK: the home page reads the new balance and allowance from the server",
    (await text('[data-entitlement="daily"]')).startsWith("2 of 3 analyses left today"));

  // 6b. An unconfirmed run that was in fact never sent: once a read shows it still prepared, the ordinary flow returns.
  await open(`/analyses/${encodeURIComponent(lowId)}`);
  await waitFor(`!!document.querySelector(".client-get-quote")`);
  await click(".client-get-quote");
  await waitFor(`!!document.querySelector(".client-approve input")`);
  mock.failNextRunBeforeSend = true;
  await click(".client-approve input");
  await click(".client-run");
  await waitFor(`document.querySelector("[data-panel]")?.dataset.panel === "uncertain"`);
  const lowRuns = posts("/runs");
  await click(".client-approve input");
  await click(".client-run");
  await sleep(300);
  check("MOCK: a server error before sending gates the page just the same; nothing more is sent",
    posts("/runs") === lowRuns && mock.dispatches === 1 && !(await exists(".client-approve, .client-run")) &&
    JSON.stringify(await header()) === unknown);
  await click("[data-uncertain] .client-check");
  await waitFor(`!!document.querySelector(".client-approve input")`);
  check("a read showing it still prepared under the server's active quote restores the approval flow, unapproved",
    !(await evaluate(`document.querySelector(".client-approve input").checked`)) &&
    await evaluate(`document.querySelector(".client-run").disabled`) &&
    JSON.stringify(await header()) === '{"chip":"Prepared · not run","state":"prepared","outcome":false}');
  // Keyboard only from here: focus is already on the restored quote, so Tab, Space, Tab, Enter approve and run it.
  const restoredFocus = await focused();
  const toApprove = await tabTo(".client-approve input", 3);
  await press("Space");
  const approvedByKey = await evaluate(`document.querySelector(".client-approve input").checked`);
  const toRun = await tabTo(".client-run", 3);
  await press("Enter");
  await waitFor(`!!document.querySelector("[data-panel=recorded]")`, 15000);
  await waitFor(`document.activeElement?.dataset.focusTarget === "result"`, 3000);
  const resultFocus = await focused();
  check("by keyboard: from the quote, Tab and Space approve, Tab and Enter run, and focus lands on the outcome, in view",
    restoredFocus.on === "quote" && toApprove && approvedByKey && toRun && resultFocus.on === "result" &&
    resultFocus.text === "No additional finding" && resultFocus.inView && resultFocus.ring === "none",
    JSON.stringify({ restoredFocus, toApprove, approvedByKey, toRun, resultFocus }));
  check("MOCK: the new explicit approval runs it once; the balance is the server's",
    mock.dispatches === 2 && posts("/runs") === lowRuns + 1 &&
    (await text('[data-entitlement="credits"]')) === "31 credits available");
  check("with nothing left to decide, the allowance follows the result instead of standing before it",
    await evaluate(`(() => { const outcome = document.querySelector(".client-outcome"), allowance = document.querySelector(".client-entitlements");
      return !!outcome && !!allowance && !!(outcome.compareDocumentPosition(allowance) & Node.DOCUMENT_POSITION_FOLLOWING) &&
        !document.querySelector(".client-state").nextElementSibling?.matches(".client-entitlements"); })()`));
  await open(`/analyses/${encodeURIComponent(highId)}`);
  await waitFor(`!!document.querySelector(".client-review textarea")`);
  await scan("result");
  await shoot("client-result-evidence", ".client-evidence");
  await shoot("client-result-interpretation", ".client-interpretation");
  await shoot("client-result-unknowns", ".client-unknowns");

  // 8. Reviews: one saved version; a conflicting save keeps the typed notes.
  await evaluate(`document.querySelector('input[name="review-status"][value="needs_revision"]').click()`);
  await setValue(".client-review textarea", "SYNTHETIC review: statement 2 reads more than the quote supports.");
  await click(".client-save-review");
  check("one explicit save records review version 1, bound to the result shown",
    await waitFor(`!!document.querySelector('[data-version="1"]')`) && posts("/reviews") === 1);
  users["reader-a"].analyses.get(highId).reviews.push({ ...users["reader-a"].analyses.get(highId).reviews[0],
    review_id: `r-${randomBytes(12).toString("hex")}`, sequence: 2,
    parent_review_id: users["reader-a"].analyses.get(highId).reviews[0].review_id, notes: "SYNTHETIC: another tab" });
  await setValue(".client-review textarea", "SYNTHETIC review, edited after another tab saved.");
  await click(".client-save-review");
  await waitFor(`!!document.querySelector('[data-code="review_conflict"]')`);
  check("MOCK: a conflicting save is refused and the typed notes stay in the editor",
    (await evaluate(`document.querySelector(".client-review textarea").value`)) ===
      "SYNTHETIC review, edited after another tab saved." && posts("/reviews") === 2);

  // 9. Failed and unresolved analyses, before and after an administrator's reconciliation (the MOCK swaps in the
  //    Client's SYNTHETIC reconciled fixtures), and an unsent one: no run and no resend in any of them.
  const credits = (count) => `${count} ${count === 1 ? "credit" : "credits"}`;
  const expectedCharge = (reserved, variant) => ({
    charged: `${credits(reserved)} charged of ${credits(reserved)} reserved, counted on 14 Oct 2026's allowance.`,
    partial: `${credits(Math.floor(reserved / 2))} charged of ${credits(reserved)} reserved; ${reserved - Math.floor(reserved / 2)} returned, counted on 14 Oct 2026's allowance.`,
    zero: `0 credits charged of ${credits(reserved)} reserved; ${reserved} returned, counted on 14 Oct 2026's allowance.`,
    returned: `${credits(reserved)} returned; nothing was charged.` })[variant];
  const heldView = async () => ({ panel: await evaluate(`document.querySelector("[data-panel]")?.dataset.panel`),
    state: await text(".client-state"), chip: await text(".client-chip.is-state"), charge: await text(".client-charge"),
    run: await exists(".client-run, .client-get-quote, .client-approve"), check: await exists(".client-check") });
  const reconciliation = {};
  for (const kind of ["unresolved", "failed"]) {
    const published = fixture(`user-contract-analysis-${kind}`).analysis;
    users["reader-a"].analyses.set(published.analysis_id, copy(published));
    await open(`/analyses/${encodeURIComponent(published.analysis_id)}`);
    await waitFor(`document.querySelector("[data-panel]")?.dataset.panel === "held"`);
    reconciliation[`${kind}-before`] = await heldView();
    for (const variant of ["charged", "partial", "zero", "returned"]) {
      const settled = fixture(`client-analysis-${kind}-${variant}`).analysis;
      users["reader-a"].analyses.set(published.analysis_id, copy(settled));
      await click(".client-check");
      await waitFor(`document.querySelector(".client-state-detail")?.textContent === ${JSON.stringify(settled.state_detail)}`);
      reconciliation[`${kind}-${variant}`] = { ...await heldView(), expected: expectedCharge(settled.charge.credits_reserved, variant) };
      if (variant === "partial") await shoot(`client-${kind}-partial`, ".client-state");
    }
  }
  const unsettled = ["unresolved-before", "failed-before"].map((key) => reconciliation[key]);
  check("before reconciliation: credits held for an administrator's review, no amount invented, only 'Check again'",
    unsettled.every((view) => view.panel === "held" && view.check && !view.run &&
      view.charge.includes("held for an administrator's review") && !/charged of|returned/.test(view.charge)),
    JSON.stringify(unsettled));
  const settledViews = Object.entries(reconciliation).filter(([key]) => !key.endsWith("-before"));
  check("after a charge, a partial or zero charge, or a return: the page states the server's settlement, never 'held'",
    settledViews.length === 8 && settledViews.every(([, view]) => view.charge === view.expected &&
      !/\bheld\b|reserved until/i.test(view.state) && !/held/i.test(view.chip)),
    JSON.stringify(settledViews.filter(([, view]) => view.charge !== view.expected || /\bheld\b/i.test(view.state))));
  check("a reconciled failure or unrecorded outcome stays non-retryable, even with its credits returned",
    settledViews.every(([, view]) => view.panel === "held" && !view.run && /not (run|sent) again/.test(view.state)));
  const unsent = fixture("user-contract-analysis-not-sent").analysis;
  await open(`/analyses/${encodeURIComponent(unsent.analysis_id)}`);
  await waitFor(`!!document.querySelector("[data-panel]")`);
  check("an unsent analysis cannot be run again",
    (await evaluate(`document.querySelector("[data-panel]").dataset.panel`)) === "not_sent" &&
    !(await exists(".client-run, .client-get-quote, .client-approve, .client-check")));
  await scan("held");
  await shoot("client-not-sent", "main.client");

  // 10. Reloads write nothing.
  const before = posts();
  for (const path of ["/", "/sources", `/sources/${encodeURIComponent(source.source_id)}`, `/analyses/${encodeURIComponent(highId)}`]) {
    await open(path);
    await waitFor(`!!document.querySelector("main.client")`);
    await sleep(150);
  }
  check("opening and reloading every page sends no write", posts() === before);

  // 11. Phone width.
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  const widths = {};
  const firstScreen = {};
  const outcomeFirst = `(() => { const outcome = document.querySelector(".client-outcome")?.getBoundingClientRect();
    const allowance = document.querySelector(".client-entitlements")?.getBoundingClientRect();
    return { top: Math.round(outcome?.top ?? -1), bottom: Math.round(outcome?.bottom ?? -1), screen: innerHeight,
             allowance: Math.round(allowance?.top ?? -1) }; })()`;
  for (const path of [`/analyses/${encodeURIComponent(highId)}`, "/sources/new", "/"]) {
    await open(path);
    await waitFor(`!!document.querySelector("main.client") && !document.querySelector(".client-status")`);
    widths[path] = await evaluate(`document.documentElement.scrollWidth <= document.documentElement.clientWidth`);
    if (path.startsWith("/analyses/")) firstScreen.phone = await evaluate(outcomeFirst);
    await shoot(`client-phone-${Object.keys(widths).length}`, "main.client");
  }
  check("at phone width no page scrolls sideways", Object.values(widths).every(Boolean), JSON.stringify(widths));
  check("at phone width Sign out is a touch target at least 40 pixels tall",
    await evaluate(`document.querySelector(".account-strip button").getBoundingClientRect().height >= 40`));
  await send("Emulation.setDeviceMetricsOverride", { width: 768, height: 1024, deviceScaleFactor: 1, mobile: true });
  const tabletWidths = {};
  for (const path of [`/analyses/${encodeURIComponent(highId)}`, "/sources/new", "/"]) {
    await open(path);
    await waitFor(`!!document.querySelector("main.client") && !document.querySelector(".client-status")`);
    tabletWidths[path] = await evaluate(`document.documentElement.scrollWidth <= document.documentElement.clientWidth`);
    if (path.startsWith("/analyses/")) firstScreen.tablet = await evaluate(outcomeFirst);
  }
  check("at tablet width no page scrolls sideways", Object.values(tabletWidths).every(Boolean), JSON.stringify(tabletWidths));
  check("a recorded analysis opens with its outcome on the first screen at phone and tablet width, the allowance after it",
    Object.values(firstScreen).length === 2 && Object.values(firstScreen).every((view) =>
      view.top > 0 && view.bottom <= view.screen && view.allowance > view.bottom), JSON.stringify(firstScreen));
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  // 12. The session ends with unsaved notes: they are shown to copy before signing in again.
  await open(`/analyses/${encodeURIComponent(highId)}`);
  await waitFor(`!!document.querySelector(".client-review textarea")`);
  await setValue(".client-review textarea", "SYNTHETIC notes typed when the session ends.");
  for (const [token, name] of mock.tokens) if (name === "reader-a") mock.expired.add(token);
  await click(".client-basis .client-link-button");
  await waitFor(`!!document.querySelector(".client-ended")`);
  check("MOCK: a 401 shows the unsaved notes to copy, then the shell's sign-in form says the session ended",
    (await evaluate(`document.querySelector(".client-ended-text")?.value`)) === "SYNTHETIC notes typed when the session ends." &&
    await click(".client-ended .button") && await waitFor(`!!document.querySelector('input[name="username"]')`) &&
    (await text(".shell-note")).includes("Your session has ended"));

  // 13. A second user.
  check("Reader B signs in", await signIn("reader-b"));
  check("MOCK: Reader B's own allowance: 2 credits, none left today, credits held by other analyses",
    (await text('[data-entitlement="credits"]')) === "2 credits available" &&
    (await text('[data-entitlement="daily"]')).startsWith("0 of 2 analyses left today") &&
    (await text('[data-entitlement="held"]')).startsWith("4 credits held"));
  await waitFor(`!!document.querySelector(".client-empty")`);
  check("Reader B's history is Reader B's only", (await evaluate(`document.querySelectorAll(".client-history-row").length`)) === 0);
  await open(`/analyses/${encodeURIComponent(highId)}`);
  await waitFor(`!!document.querySelector('[data-code="not_found"]')`);
  check("MOCK: Reader A's analysis opened by Reader B is Not Found", (await text('[data-code="not_found"]')).includes("Not found"));
  await open("/sources/new");
  await waitFor(`!!document.querySelector(".client-form")`);
  await setValue('input[name="headline"]', source.headline);
  await setValue('input[name="source_url"]', source.source_url);
  await setValue('input[name="date"]', "2026-10-13");
  await setValue('input[name="time"]', "10:00");
  await setValue('select[name="offset"]', "+03:00");
  await setValue('textarea[name="source_text"]', source.text);
  await click(".client-save-source");
  await waitFor(`document.querySelectorAll('input[name="effort"]').length === 2`);
  users["reader-b"].account.efforts = users["reader-b"].account.efforts.filter((option) => option.effort !== "medium");
  await click('input[name="effort"][value="medium"]');
  await click(".client-prepare");
  await waitFor(`!!document.querySelector('[data-code="unsupported_effort"]')`);
  check("MOCK: a withdrawn Effort is refused; the server's remaining options replace the list and none is chosen",
    JSON.stringify(await evaluate(`[...document.querySelectorAll('input[name="effort"]')].map((e) => e.value)`)) === '["low"]' &&
    !(await evaluate(`document.querySelector('input[name="effort"]').checked`)) &&
    (await text('[data-code="unsupported_effort"]')).includes("The server now offers: Low"));
  await click('input[name="effort"][value="low"]');
  await click(".client-prepare");
  await waitFor(`!!document.querySelector(".client-get-quote")`);
  await click(".client-get-quote");
  await waitFor(`!!document.querySelector(".client-approve input")`);
  const advice = await evaluate(`[...document.querySelectorAll(".client-advisory")].map((e) => e.textContent).join(" ")`);
  await click(".client-approve input");
  check("server-reported limits are shown as advice, and the run stays the person's decision",
    advice.includes("no analyses left today") && advice.includes("fewer than this quote's 3") &&
    !(await evaluate(`document.querySelector(".client-run").disabled`)));
  const dispatchesBeforeB = mock.dispatches;
  const debitsBeforeB = JSON.stringify(users["reader-b"].account.credits);
  await click(".client-run");
  await waitFor(`!!document.querySelector('[data-code="daily_limit_reached"]')`);
  check("MOCK: today's allowance used: refused with the reset time in the quota time zone, nothing sent",
    (await text('[data-code="daily_limit_reached"]')).includes("(Asia/Jerusalem)") &&
    mock.dispatches === dispatchesBeforeB && JSON.stringify(users["reader-b"].account.credits) === debitsBeforeB);
  users["reader-b"].account.daily = { ...users["reader-b"].account.daily, limit: 3, remaining: 1 };
  await click(".client-approve input");
  await click(".client-run");
  await waitFor(`!!document.querySelector('[data-code="insufficient_credits"]')`);
  check("MOCK: not enough credits: refused with the server's balance, nothing sent",
    (await text('[data-code="insufficient_credits"]')).includes("needs 3 credits") &&
    (await text('[data-code="insufficient_credits"]')).includes("2 credits available") &&
    mock.dispatches === dispatchesBeforeB && JSON.stringify(users["reader-b"].account.credits) === debitsBeforeB);
  await scan("reader-b");
  await shoot("client-refusal", ".client-state");

  // 14. Source continuation after a server upgrade. The earlier row at the same Effort must not block preparing
  // today's request. This MOCK verifies the button; test_source_continuation.py verifies the real server action.
  const earlierLow = `${source.source_id}.research-prompt-1.low`;
  const currentLow = `${source.source_id}.research-prompt-2.low`;
  const historicalLow = JSON.stringify(users["reader-b"].analyses.get(earlierLow));
  const creditsBeforeContinuation = JSON.stringify(users["reader-b"].account.credits);
  const beforeContinuation = { prepare: posts("/api/user/analyses"), quote: posts("/quotes"), run: posts("/runs"),
                               dispatch: mock.dispatches, analyses: users["reader-b"].analyses.size };
  mock.promptVersion = "research-prompt-2";
  await open(`/sources/${encodeURIComponent(source.source_id)}`);
  await waitFor(`!!document.querySelector('input[name="effort"][value="low"]')`);
  await click('input[name="effort"][value="low"]');
  check("an earlier analysis at the chosen Effort leaves an explicit Continue action available",
    await exists(".client-prepare") && !(await evaluate('document.querySelector(".client-prepare").disabled')) &&
    (await text(".client-prepare")).includes("Continue with Low"));
  await click(".client-prepare");
  check("continuing asks the server once and opens its current preparation, not the earlier history entry",
    await waitFor(`location.pathname === ${JSON.stringify(`/analyses/${currentLow}`)}`) &&
    posts("/api/user/analyses") === beforeContinuation.prepare + 1 &&
    users["reader-b"].analyses.size === beforeContinuation.analyses + 1);
  check("continuing only prepares: no quote, approval, charge or dispatch is added",
    await waitFor(`!!document.querySelector(".client-get-quote")`) &&
    posts("/quotes") === beforeContinuation.quote && posts("/runs") === beforeContinuation.run &&
    mock.dispatches === beforeContinuation.dispatch &&
    JSON.stringify(users["reader-b"].account.credits) === creditsBeforeContinuation);
  await open(`/sources/${encodeURIComponent(source.source_id)}`);
  await waitFor(`document.querySelectorAll(".client-history-row").length >= 2`);
  check("both saved analyses remain linked, with their preparation times",
    await exists(`a.client-history-title[href="/analyses/${earlierLow}"]`) &&
    await exists(`a.client-history-title[href="/analyses/${currentLow}"]`) &&
    (await text('[aria-labelledby="source-analyses-title"]')).includes("Prepared "));
  await click('input[name="effort"][value="low"]');
  await click(".client-prepare");
  check("continuing again reopens that current preparation without creating another or requesting a quote",
    await waitFor(`location.pathname === ${JSON.stringify(`/analyses/${currentLow}`)}`) &&
    users["reader-b"].analyses.size === beforeContinuation.analyses + 1 &&
    posts("/quotes") === beforeContinuation.quote && posts("/runs") === beforeContinuation.run);
  await open(`/sources/${encodeURIComponent(source.source_id)}`);
  await waitFor(`!!document.querySelector('a.client-history-title[href="/analyses/${earlierLow}"]')`);
  await click(`a.client-history-title[href="/analyses/${earlierLow}"]`);
  check("the earlier analysis still opens unchanged from its history link",
    await waitFor(`location.pathname === ${JSON.stringify(`/analyses/${earlierLow}`)}`) &&
    JSON.stringify(users["reader-b"].analyses.get(earlierLow)) === historicalLow);
  await scan("source-continuation");

  // 15. Boundaries.
  const leaked = mock.requests.filter((item) => ADMIN_ONLY.test(item.body));
  check("no reply the page received carried administrator vocabulary, and no page showed any",
    leaked.length === 0 && vocabulary.length === 0, [...leaked.map((item) => item.path), ...vocabulary].join(", "));
  check("every write carried this page's origin and the user header (no refusal as forbidden)", mock.forbidden === 0);
  check("every request to the user routes named the signed-in account (account binding)", mock.unbound === 0,
    `${mock.unbound} unbound`);
  const outside = browserRequests.filter((url) => !url.startsWith(base) && !url.startsWith("data:"));
  check("the page requested nothing outside the local server", outside.length === 0, outside.join(", "));
  check("no page error", pageErrors.length === 0, pageErrors.join(" | "));
  check("leaving a page with unsaved review notes raised the unsaved-text guard (Chrome blocks its prompt in a script)",
    blockedPrompts.length >= 1 && blockedPrompts.every((url) => url.startsWith(`${base}/analyses/`)), blockedPrompts.join(", "));
  check("no unexpected confirmation dialog", dialogs.length === 0, dialogs.join(" | "));
  const bundle = readdirSync(join(built, "assets")).filter((name) => name.endsWith(".js"))
    .map((name) => readFileSync(join(built, "assets", name), "utf8")).join("\n");
  check("the built Client bundle names no vendor or product and carries no operator page",
    !/claude|sonnet|opus|haiku|anthropic|openai/i.test(bundle) &&
    !/Market context|Case library|Hypotheses|Treasury findings|Tracker attempts/.test(bundle));
  check("MOCK: exactly two analyses were dispatched, one per approved run that reached sending; replays added none",
    mock.dispatches === 2);
  ws.close();
} catch (error) {
  check("the Client browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  server.close();
  await sleep(400);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
