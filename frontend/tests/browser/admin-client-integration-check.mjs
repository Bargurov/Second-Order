// Joint browser check of the built Admin and Client against the real integrated FastAPI application, in one headless
// Chrome: tests/review_browser_server.py --accounts synthetic --usage-policy synthetic --simulated-provider --controls
// serves a temporary folder with a SYNTHETIC accounts store (one administrator, reader-a and reader-b), a SYNTHETIC
// credit policy and SYNTHETIC usage limits, and an in-process fake of the Claude API (an httpx MockTransport with a dummy key; nothing can reach the network). The
// launcher's test-only controls (tests/integration_controls.py, on their own loopback port, never an application route)
// set the accounts clock and hold a run at three points: after its reservation, before its send is recorded, and inside
// the fake provider. The child process gets a decoy ANTHROPIC_API_KEY, so the check also shows the fake receives the
// dummy key whatever the environment holds. Every invariant below is read from the real server's durable records
// (accounts store, attempt folders, the fake's own record of what it received), never from a mock counter.
//
// The journey, by the integration brief's numbering:
//  1. signed out, `/` is the Client build's landing page (with registration and sign-in links) and every other route
//     its sign-in form, keeping the address; an admin gets the Admin build; an operator capture
//     made through /api/intake stays the administrator's; library browsing as admin (10); expiry with unsaved source
//     and review text shown before signing in again, given back to the same account after it signs in again on the
//     real server and never to another account (whose sign-in discards it); direct opens and reloads of every Client
//     route; another user's records and every admin route are refused; no user payload carries an admin field.
//  2. source -> Effort -> preparation -> quote -> approval -> one send of the saved bytes -> evidence, interpretation and
//     unknowns -> a review version -> export; a source of 50,000 emoji typed in the form is accepted whole.
//  3. another Effort carries no approval; mismatched, expired and superseded quotes, an unsupported Effort, no daily
//     limit, insufficient credits and a used day are refused before any send; page loads write nothing.
//  4. a run reply lost after the server accepted it gates the page until a successful read (a failed read keeps it);
//     a run that failed before reaching the server restores the ordinary approval after the read.
//  5. the browser's approval POST replayed, four times concurrently and once more: one attempt, one send, one debit.
//  6. two users racing for the last daily slot and the last credits, independent balances, the 25-hour quota day at the
//     end of daylight saving time in Asia/Jerusalem, a restart that changes nothing, and the fixed quota zone refused in
//     the Admin screen.
//  7. a worker held before its send and one held in transport past 15 minutes stay unresolvable; a server killed with
//     one attempt in transport and one before its send; stale and competing admin decisions; over-charging refused;
//     an attempt returned before its worker took the lock never sends.
//  8. returned, partially charged, zero-charged and fully charged attempts: the Admin ledger, the server's state_detail
//     and the Client's charge and attempt lines agree, and nothing offers a resend.
//  9. reads stay responsive while runs are held; unknown usage and cost stay unknown; nothing is retried.
//
//   cd frontend; npm run build; node tests/browser/admin-client-integration-check.mjs
//   (SECOND_ORDER_SCREENSHOTS=<folder> also saves a few screenshots there.)
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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
for (const built of ["frontend/dist/index.html", "frontend/dist-client/client.html"]) {
  if (!existsSync(join(repo, built))) throw new Error("Build both clients first: npm run build");
}
const shots = process.env.SECOND_ORDER_SCREENSHOTS ?? null;

const PASSWORDS = { admin: "synthetic-admin-pass", "reader-a": "synthetic-reader-a", "reader-b": "synthetic-reader-b" };
const DECOY_KEY = "sk-ant-decoy-environment-value-never-sent-0000";  // Not a credential: the server must not use it.
const START = "2026-10-20T06:00:00+00:00";  // Tuesday 20 October 2026, 09:00 in Jerusalem (IDT, UTC+3).
const ADMIN_ONLY = /claude|sonnet|opus|haiku|anthropic|\$\s?\d|\busd\b|\btokens?\b|\bcosts?\b|\bproviders?\b|\bmodels?\b|planning|request_id|x-api-key|sk-ant|http_status|elapsed|thinking|\bpid\b|prompt/i;
const SOURCE_TEXT = (title) => `October 12, 2026\n\n${title}\n\nThe Simulated Statistics Office reported that output ` +
  "in the surveyed sector rose 1.2 percent in the third quarter, after a 0.4 percent decline in the second.\n\nThe " +
  "office said it expects to revise the estimate when late responses arrive in November.\n\nSYNTHETIC TEST SOURCE " +
  "written for the joint check.";
const supplied = new Set();  // What users typed (headlines, texts, notes): removed before the payload privacy scan.
const sourceForm = (headline) => {
  supplied.add(headline);
  supplied.add(SOURCE_TEXT(headline));
  return { headline, source_url: "https://example.org/synthetic/joint", published_at: "2026-10-12T10:00:00+03:00",
           source_text: SOURCE_TEXT(headline) };
};
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const probe = createServer().listen(0, "127.0.0.1", () => {
    const { port } = probe.address();
    probe.close(() => done(port));
  });
});
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
const root = mkdtempSync(join(tmpdir(), "second-order-joint-check-"));
const served = join(root, "served");
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const section = (name) => console.log(`\n-- ${name}`);

let server = null;
const port = await freePort();
const controlPort = await freePort();
const base = `http://127.0.0.1:${port}`;

async function startServer(keep, clockAt) {
  const args = [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port), "--accounts",
    "synthetic", "--usage-policy", "synthetic", "--simulated-provider", "--controls", String(controlPort),
    "--accounts-clock", clockAt];
  if (keep) args.push("--keep-records");
  server = spawn(python, args, { cwd: repo, stdio: ["ignore", "inherit", "inherit"],
                                 env: { ...process.env, ANTHROPIC_API_KEY: DECOY_KEY } });
  children.push(server);
  for (let i = 0; i < 150; i++) {
    try {
      if ((await fetch(`${base}/api/session`)).ok) return;
    } catch { /* starting */ }
    await sleep(200);
  }
  throw new Error("The server did not start.");
}

async function stopServer() {
  const stopped = new Promise((done) => server.once("exit", done));
  server.kill();
  await stopped;
  for (let i = 0; i < 50; i++) {
    try { await fetch(`${base}/api/session`); } catch { return; }
    await sleep(100);
  }
  throw new Error("The server did not stop.");
}

// ---------------------------------------------------------------- the launcher's test-only controls
const control = async (path, body) => (await fetch(`http://127.0.0.1:${controlPort}${path}`,
  body === undefined ? {} : { method: "POST", body: JSON.stringify(body) })).json();
const setClock = (instant, frozen = false) => control("/clock", { set: instant, frozen });
const advance = (seconds) => control("/clock", { advance_seconds: seconds });
const hold = (gate, held) => control(`/gates/${gate}`, { hold: held });
const providerCount = async () => (await control("/state")).provider_requests;
async function waitGate(gate, waiting, timeout = 15000) {
  for (const start = Date.now(); Date.now() - start < timeout; await sleep(50)) {
    if ((await control("/state")).gates[gate].waiting === waiting) return true;
  }
  return false;
}

// ---------------------------------------------------------------- the API, as each signed-in account calls it
// Each session names the account it signed in as on every request, as a page opened for that account does
// (docs/account-binding-contract.md).
const userPayloads = [];
function session(cookie, label, account) {
  const call = async (method, path, body, header) => {
    const started = performance.now();
    const response = await fetch(`${base}${path}`, { method, body: body === undefined ? undefined
      : typeof body === "string" ? body : JSON.stringify(body),
      headers: { Cookie: cookie, ...(account ? { "X-Second-Order-Account": account } : {}),
        ...(method === "POST" ? { Origin: base, "Content-Type": "application/json", [header]: "1" } : {}) } });
    const text = await response.text();
    if (label !== "admin" && (path.startsWith("/api/user") || path.startsWith("/api/session"))) {
      userPayloads.push({ path, text });
    }
    let parsed = null;
    try { parsed = JSON.parse(text); } catch { /* not JSON */ }
    return { status: response.status, body: parsed, text, ms: performance.now() - started,
             disposition: response.headers.get("content-disposition") };
  };
  return {
    cookie, get: (path) => call("GET", path),
    post: (path, body) => call("POST", path, body, "X-Second-Order-User"),
    admin: (path, body) => call("POST", path, body, "X-Second-Order-Admin"),
    intake: (path, body) => call("POST", path, body, "X-Second-Order-Intake"),
  };
}
async function login(username) {
  const reply = await fetch(`${base}/api/session/login`, { method: "POST", body: JSON.stringify({
    username, password: PASSWORDS[username] }), headers: { Origin: base, "Content-Type": "application/json",
    "X-Second-Order-Session": "1" } });
  if (!reply.ok) throw new Error(`${username} could not sign in (${reply.status})`);
  const account = (await reply.json()).user.user_id;
  return session((reply.headers.get("set-cookie") ?? "").split(";")[0], username === "admin" ? "admin" : "user",
                 account);
}
const enc = encodeURIComponent;
const analysisPath = (id) => `/api/user/analyses/${enc(id)}`;
const approvalOf = (quote) => ({ quote_id: quote.quote_id, effort: quote.effort, credits: quote.credits, approve: true });
async function prepared(user, headline, effort) {
  const source = await user.post("/api/user/sources", sourceForm(headline));
  const analysis = await user.post("/api/user/analyses", { source_id: source.body.source.source_id, effort });
  return { sourceId: source.body.source.source_id, id: analysis.body.analysis.analysis_id };
}
async function quoted(user, headline, effort) {
  const made = await prepared(user, headline, effort);
  const quote = (await user.post(`${analysisPath(made.id)}/quotes`, {})).body.quote;
  return { ...made, quote };
}
const runOf = (user, item, body = approvalOf(item.quote)) => user.post(`${analysisPath(item.id)}/runs`, body);
const stateOf = async (user, id) => (await user.get(analysisPath(id))).body.analysis;
const holdsFor = async (admin) => (await admin.get("/api/admin/holds")).body.holds;
const holdOf = async (admin, id) => (await holdsFor(admin)).find((row) => row.request_id === id);
const decideAttempt = (admin, row, resolution, credits, reason, observed = row.observed) =>
  admin.admin(`/api/admin/attempts/${enc(row.attempt_id)}/resolve`, { resolution, credits_charged: credits, reason,
                                                                       observed });

try {
  mkdirSync(served);
  await startServer(false, START);

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
  const listeners = [];
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else listeners.forEach((listener) => listener(message));
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
    const prototype = element instanceof HTMLSelectElement ? HTMLSelectElement.prototype
      : element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value").set.call(element, ${JSON.stringify(value)});
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`);
  const click = (selector) => evaluate(`(() => { const element = document.querySelector(${JSON.stringify(selector)});
    if (!element) return false; element.click(); return true; })()`);
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);
  const exists = (selector) => evaluate(`!!document.querySelector(${JSON.stringify(selector)})`);
  const clickText = (selector, words) => evaluate(`(() => { const element = [...document.querySelectorAll(
    ${JSON.stringify(selector)})].find((item) => item.textContent.includes(${JSON.stringify(words)}));
    if (!element) return false; element.click(); return true; })()`);
  const scripts = () => evaluate(`[...document.querySelectorAll("script[src]")].map((script) => script.src)`);
  const shoot = async (name) => {
    if (!shots) return;
    mkdirSync(shots, { recursive: true });
    const { data } = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
    writeFileSync(join(shots, `${name}.png`), Buffer.from(data, "base64"));
  };

  const requests = [];
  const errors = [];
  const dialogs = [];
  let intercept = { runReply: false, runRequest: false, readPath: null };
  const intercepted = [];
  listeners.push((message) => {
    if (message.method === "Network.requestWillBeSent") {
      const request = message.params.request;
      requests.push({ url: request.url, method: request.method, postData: request.postData ?? null });
    } else if (message.method === "Runtime.exceptionThrown") {
      errors.push(message.params.exceptionDetails.exception?.description ?? message.params.exceptionDetails.text);
    } else if (message.method === "Page.javascriptDialogOpening") {
      dialogs.push(message.params.message);
      send("Page.handleJavaScriptDialog", { accept: true }).catch(() => {});
    } else if (message.method === "Fetch.requestPaused") {
      const { requestId, request, responseStatusCode } = message.params;
      const atResponse = responseStatusCode !== undefined;
      const isRun = request.method === "POST" && /\/runs$/.test(new URL(request.url).pathname);
      const fail = (isRun && atResponse && intercept.runReply) || (isRun && !atResponse && intercept.runRequest) ||
        (!atResponse && request.method === "GET" && new URL(request.url).pathname === intercept.readPath);
      if (fail) intercepted.push({ url: request.url, method: request.method, atResponse, status: responseStatusCode });
      send(fail ? "Fetch.failRequest" : "Fetch.continueRequest",
           fail ? { requestId, errorReason: "ConnectionReset" } : { requestId }).catch(() => {});
    }
  });
  const interceptUserApi = (rules) => {
    intercept = { runReply: false, runRequest: false, readPath: null, ...rules };
    return send("Fetch.enable", { patterns: [{ urlPattern: `${base}/api/user/*`, requestStage: "Request" },
                                            { urlPattern: `${base}/api/user/analyses/*/runs`, requestStage: "Response" }] });
  };
  const stopIntercepting = () => {
    intercept = { runReply: false, runRequest: false, readPath: null };
    return send("Fetch.disable");
  };
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete'");
  };
  const reload = async () => {
    await send("Page.reload", { ignoreCache: true });
    await sleep(100);
    await waitFor("document.readyState === 'complete'");
  };
  const signIn = async (username) => {
    if (!(await evaluate(`!!document.querySelector(".shell-form")`))) await open("/sign-in");  // From the landing page.
    await waitFor(`!!document.querySelector(".shell-form")`);
    await setValue('.shell-form input[name="username"]', username);
    await setValue('.shell-form input[name="password"]', PASSWORDS[username]);
    await click(".shell-form button[type=submit]");
    return username === "admin" ? waitFor(`!!document.querySelector(".admin-bar")`, 15000)
      : waitFor(`!!document.querySelector("main.page.client") && !document.querySelector(".admin-bar")`, 15000);
  };
  const signedOutPage = `!!document.querySelector(".shell-form") || !!document.querySelector('a[href="/register"]')`;
  const signOutClient = async () => {
    await click(".account-strip button");
    return waitFor(signedOutPage);
  };
  const signOutAdmin = async () => {
    await clickText(".admin-bar button", "Sign out");
    return waitFor(signedOutPage);
  };
  const browserSession = async () => {
    const { cookies } = await send("Network.getCookies", { urls: [base] });
    const cookie = cookies.find((item) => item.name === "second_order_session");
    const current = await (await fetch(`${base}/api/session`, { headers: { Cookie: `${cookie.name}=${cookie.value}` } }))
      .json();  // The account this browser is signed in as now, as a page opened now would name it.
    return session(`${cookie.name}=${cookie.value}`, "user", current.user?.user_id);
  };
  const writesSince = (mark) => requests.slice(mark).filter((request) => request.method !== "GET" &&
    request.url.startsWith(base));
  const panel = () => evaluate(`document.querySelector(".client-state")?.dataset.panel ?? null`);
  const noResend = () => evaluate(`!document.querySelector(".client-run, .client-get-quote, .client-approve")`);
  const entitlement = (name) => text(`[data-entitlement="${name}"]`);

  // ================================================================ 1. signed out, admin, operator records, library
  section("1. signed out: the Client build's landing page at /, its sign-in form on every other route");
  await open("/");
  check("signed out, / is the Client build's landing page, with registration and sign-in links",
        await waitFor(`!!document.querySelector('a[href="/register"]') && !!document.querySelector('a[href="/sign-in"]')
          && !document.querySelector(".shell-form")`) &&
        (await scripts()).length > 0 && (await scripts()).every((src) => /\/assets\/client-/.test(src)));
  const routes = ["/sign-in", "/sources", "/sources/new", "/sources/unknown-source", "/analyses/unknown-analysis",
                  "/no-such-page", "/admin", "/admin/credits", "/library"];
  const signedOut = [];
  for (const path of routes) {
    await open(path);
    signedOut.push(await waitFor(`!!document.querySelector(".shell-form")`) &&
      (await scripts()).every((src) => /\/assets\/client-/.test(src)) && (await scripts()).length > 0);
  }
  check("every other route opened signed out is the Client build's sign-in form, at its own address",
        signedOut.every(Boolean) && (await evaluate("location.pathname")) === "/library",
        routes.filter((_, index) => !signedOut[index]).join(", "));
  check("admin, intake and library routes refuse a signed-out caller with 401",
        (await Promise.all(["/api/admin/users", "/api/intake", "/api/case-library", "/api/user/account"]
          .map(async (path) => (await fetch(base + path)).status))).every((status) => status === 401));

  section("1. an administrator: the Admin build, an operator capture, and the library (10)");
  await open("/sign-in");
  check("an admin signing in is handed the Admin build", await signIn("admin") &&
        (await scripts()).every((src) => !/\/assets\/client-/.test(src)));
  let admin = await login("admin");
  const operator = await admin.intake("/api/intake", sourceForm("Operator capture kept by the administrator"));
  const legacyId = operator.body?.capture_id;
  check("an operator capture made through /api/intake has no user owner", operator.status === 201 && !!legacyId &&
        (await admin.get("/api/intake")).body.captures.some((capture) => capture.capture_id === legacyId));
  const library = (await admin.get("/api/case-library")).body;
  const mining = library.cases.filter((item) => item.sectors.includes("mining-materials"));
  check("the library lists 27 distinct cases under five sectors", library.cases.length === 27 &&
        new Set(library.cases.map((item) => item.id)).size === 27 && library.sectors.length === 5 &&
        library.sectors.every((sector) => library.cases.some((item) => item.sectors.includes(sector.slug))));
  check("Mining & materials lists the three existing G.17 cases, as additional memberships",
        JSON.stringify(mining.map((item) => item.id).sort()) ===
          JSON.stringify(["g17-2026-07-17", "g17-2026-08-18", "g17-2026-09-18"]) &&
        mining.every((item) => item.sectors.includes("manufacturing-automotive") && item.sectors.length >= 2));
  let mark = requests.length;
  await open("/library");
  const allCases = await waitFor(`document.querySelectorAll(".library-index .library-entry").length === 27`, 15000);
  await open("/library?sector=mining-materials");
  const miningCases = await waitFor(`document.querySelectorAll(".library-index .library-entry").length === 3`);
  check("the admin's library page shows 27 cases, and 3 under Mining & materials", allCases && miningCases);
  check("browsing the library writes nothing", writesSince(mark).length === 0,
        writesSince(mark).map((request) => request.url).join(", "));
  check("the admin signs out", await signOutAdmin());

  // ================================================================ 1-2. reader-a: expiry, the full flow
  section("1. reader-a: the Client, and an expired session with an unsaved source");
  check("reader-a signing in is handed the Client build", await signIn("reader-a") &&
        (await scripts()).every((src) => /\/assets\/client-/.test(src)));
  await open("/");
  check("a signed-in reader's home, /, is the News (docs/news-stories-contract.md section 7)",
        await waitFor(`document.querySelector("main.page.client")?.dataset.view === "news" &&
          !!document.querySelector('.news-tabs a[aria-current="page"][href="/news"]')`));
  await open("/analyses");  // Your analyses, with the allowance, moved from / to /analyses.
  check("the allowance is the server's: 30 credits, 3 of 3 today, resetting at midnight in Jerusalem",
        await waitFor(`document.querySelector('[data-entitlement="credits"]')?.textContent === "30 credits available"`) &&
        (await entitlement("daily")).startsWith("3 of 3 analyses left today (0 used on 20 Oct 2026)") &&
        (await entitlement("reset")).includes("21 Oct 2026, 00:00 (Asia/Jerusalem)") &&
        (await entitlement("reset")).includes("20 Oct 2026, 21:00 UTC"));
  const first = sourceForm("Simulated statistics office publishes its quarterly survey");
  const fillSource = async (form) => {
    await open("/sources/new");
    await waitFor(`!!document.querySelector('input[name="headline"]')`);
    await setValue('input[name="headline"]', form.headline);
    await setValue('input[name="source_url"]', form.source_url);
    await setValue('input[name="date"]', "2026-10-12");
    await setValue('input[name="time"]', "10:00");
    await setValue('select[name="offset"]', "+03:00");
    await setValue('textarea[name="source_text"]', form.source_text);
  };
  await fillSource(first);
  await advance(13 * 3600);  // Past the 12-hour session.
  await click(".client-save-source");
  check("an expired session shows the unsaved source text before the sign-in form",
        await waitFor(`!!document.querySelector(".client-ended")`) &&
        (await evaluate(`[...document.querySelectorAll(".client-ended-text")].map((t) => t.value).join("\\n")`))
          .includes("revise the estimate when late responses arrive"));
  await clickText(".client-ended button", "Sign in again");
  check("signing in again says the session ended", await waitFor(`!!document.querySelector(".shell-form")`) &&
        (await text(".shell-note")).includes("Your session has ended"));
  await signIn("reader-a");
  let readerA = await browserSession();
  check("the expired session saved no source", (await readerA.get("/api/user/sources")).body.sources.length === 0);
  check("signed in again on the real server, the same account gets its unsaved source back in the form, unsaved",
        await waitFor(`!!document.querySelector('[data-recovered="source"]') &&
          document.querySelector('input[name="headline"]')?.value === ${JSON.stringify(first.headline)} &&
          document.querySelector('textarea[name="source_text"]')?.value === ${JSON.stringify(first.source_text)}`) &&
        (await readerA.get("/api/user/sources")).body.sources.length === 0);

  section("2. source -> Effort -> preparation -> quote -> approval -> one send -> result, review, export");
  await fillSource(first);
  await click(".client-save-source");
  await waitFor(`location.pathname.startsWith("/sources/") && location.pathname !== "/sources/new"`);
  const firstSource = decodeURIComponent((await evaluate("location.pathname")).split("/")[2]);
  check("saving the source opens its page", await waitFor(`document.querySelector(".client-title")?.textContent ===
    ${JSON.stringify(first.headline)}`));
  await reload();
  check("a reload of the source page shows the same source", await waitFor(
    `document.querySelector(".client-title")?.textContent === ${JSON.stringify(first.headline)}`));
  await waitFor(`document.querySelectorAll('input[name="effort"]').length > 0`);
  const offered = await evaluate(`[...document.querySelectorAll('input[name="effort"]')].map((input) => input.value)`);
  check("the Efforts offered are the server's", JSON.stringify(offered) === '["low","medium","high"]', offered.join());
  await click('input[name="effort"][value="high"]');
  await click(".client-prepare");
  await waitFor(`location.pathname.startsWith("/analyses/")`);
  const high = decodeURIComponent((await evaluate("location.pathname")).split("/")[2]);
  check("preparing opens the analysis, prepared and not run, with a quote to ask for",
        await waitFor(`document.querySelector(".client-state")?.dataset.panel === "quote"`) &&
        (await text(".client-chip.is-state")) === "Prepared · not run");
  mark = requests.length;
  await reload();
  await waitFor(`document.querySelector(".client-state")?.dataset.panel === "quote"`);
  check("reloading the analysis writes nothing", writesSince(mark).length === 0,
        writesSince(mark).map((request) => `${request.method} ${request.url}`).join(", "));
  await click(".client-get-quote");
  check("the quote is shown for approval, unchecked", await waitFor(`!!document.querySelector(".client-quote.is-approval")`) &&
        !(await evaluate(`document.querySelector(".client-approve input").checked`)) &&
        (await evaluate(`document.querySelector(".client-run").disabled`)));
  const highQuote = (await stateOf(readerA, high)).quote;
  check("the page shows the server's quote", (await text("[data-quote-credits]")) === String(highQuote.credits) &&
        (await evaluate(`document.querySelector(".client-quote.is-approval").dataset.quote`)) === highQuote.quote_id);
  await click(".client-approve input");
  await waitFor(`!document.querySelector(".client-run").disabled`);
  const sentBefore = await providerCount();
  mark = requests.length;
  await click(".client-run");
  check("the approved run is recorded", await waitFor(`document.querySelector(".client-state")?.dataset.panel === "recorded"`, 20000) &&
        (await text(".client-chip.is-outcome")) === "Analysis recorded");
  const runPost = requests.slice(mark).find((request) => request.method === "POST" && request.url.endsWith("/runs"));
  check("the browser sent one approval repeating the quote exactly", !!runPost &&
        JSON.stringify(JSON.parse(runPost.postData)) === JSON.stringify(approvalOf(highQuote)) &&
        requests.slice(mark).filter((request) => request.url.endsWith("/runs")).length === 1);
  check("the fake provider received one request", (await providerCount()) === sentBefore + 1);
  const saved = readFileSync(join(served, "research-analyses", "requests", high, "request.json"));
  const delivered = readFileSync(join(served, "simulated-provider", `request-${sentBefore + 1}.json`));
  check("it received exactly the saved request bytes", saved.equals(delivered), `${saved.length} vs ${delivered.length}`);
  const receipt = JSON.parse(readFileSync(join(served, "simulated-provider", `received-${sentBefore + 1}.json`), "utf8"));
  check("with the dummy key, never the environment's decoy, at the Messages endpoint",
        receipt.x_api_key_is_the_dummy_key === true && receipt.url_is_messages_api === true &&
        !readFileSync(join(served, "simulated-provider", `request-${sentBefore + 1}.json`), "utf8").includes(DECOY_KEY));
  check("the result shows the source's evidence, the interpretation and the unknowns, apart",
        (await evaluate(`document.querySelectorAll(".client-evidence li[data-statement]").length`)) >= 1 &&
        (await text(".client-evidence blockquote")).length > 20 && (await exists(".client-interpretation")) &&
        (await exists(".client-unknowns")) &&
        (await text(".client-interpretation")).includes("Simulated interpretation"));
  check("the charge line is the server's settlement", (await text(".client-charge")) ===
        `${highQuote.credits} credits charged of ${highQuote.credits} credits reserved, counted on 20 Oct 2026's allowance.`);
  await shoot("01-recorded-analysis");

  section("5. the browser's approval POST replayed by the harness");
  const replay = await readerA.post(`${analysisPath(high)}/runs`, runPost.postData);
  check("a replay of the same approval is a truthful duplicate: nothing reserved, charged or sent again",
        replay.status === 200 && replay.body.duplicate === true && replay.body.analysis.state === "recorded" &&
        replay.body.account.credits.available === 30 - highQuote.credits &&
        (await providerCount()) === sentBefore + 1);

  section("2. a review version and the export");
  await click('input[name="review-status"][value="human_reviewed"]');
  supplied.add("Read against the source: the statements match it.");
  await setValue(".client-review-notes textarea", "Read against the source: the statements match it.");
  await click(".client-save-review");
  check("the review is saved as version 1", await waitFor(
    `document.querySelector('.client-versions li[data-version="1"]')?.textContent.includes("Reviewed")`));
  const exported = await evaluate(`fetch(document.querySelector(".client-export a").getAttribute("href")).then(async (r) =>
    ({ status: r.status, disposition: r.headers.get("content-disposition"), text: await r.text() }))`);
  const exportBody = JSON.parse(exported.text);
  check("the export is the user's record: the analysis, its result and the review", exported.status === 200 &&
        /attachment/.test(exported.disposition) && exportBody.analysis?.analysis_id === high &&
        exportBody.analysis?.reviews?.length === 1 && exportBody.analysis?.result?.outcome === "analysis");
  userPayloads.push({ path: "export (browser)", text: exported.text });
  check("the allowance after one run", await waitFor(`document.querySelector('[data-entitlement="credits"]')
    ?.textContent === "${30 - highQuote.credits} credits available"`) &&
        (await entitlement("daily")).startsWith("2 of 3 analyses left today (1 used on 20 Oct 2026)"));

  section("1. an expired session with an unsaved review");
  await click('input[name="review-status"][value="needs_revision"]');
  supplied.add("Unsaved second thoughts about statement 2.");
  await setValue(".client-review-notes textarea", "Unsaved second thoughts about statement 2.");
  await advance(13 * 3600);  // Now Wednesday 21 October, 11:00 in Jerusalem.
  await click(".client-save-review");
  check("the unsaved review notes are shown before signing in again", await waitFor(`!!document.querySelector(".client-ended")`) &&
        (await evaluate(`[...document.querySelectorAll(".client-ended-text")].some((t) => t.value.includes("Unsaved second thoughts"))`)));
  await clickText(".client-ended button", "Sign in again");
  await signIn("reader-a");
  readerA = await browserSession();
  check("the same account gets its review notes back in the editor after the analysis is read again",
        await waitFor(`!!document.querySelector('[data-recovered="review"]') &&
          document.querySelector(".client-review-notes textarea")?.value === "Unsaved second thoughts about statement 2."`));
  check("nothing more was saved", (await stateOf(readerA, high)).reviews.length === 1);

  section("1. direct opens and reloads of every Client route, and role-specific files");
  const views = [["/", "news"], ["/analyses", "analyses"], ["/news/reports", "reports"], ["/sources", "sources"], ["/sources/new", "new-source"], [`/sources/${enc(firstSource)}`, "source"],
                 [`/analyses/${enc(high)}`, "analysis"], ["/no-such-page", "not-found"], ["/admin/users", "not-found"],
                 ["/library", "not-found"]];
  const viewed = [];
  for (const [path, view] of views) {
    await open(path);
    const opened = await waitFor(`document.querySelector("main.page.client")?.dataset.view === "${view}"`);
    await reload();
    const reloaded = await waitFor(`document.querySelector("main.page.client")?.dataset.view === "${view}"`);
    viewed.push(opened && reloaded && (await scripts()).every((src) => /\/assets\/client-/.test(src)) &&
                !(await exists(".admin-bar")));
  }
  check("every Client route opens and reloads directly, in the Client build only", viewed.every(Boolean),
        views.filter((_, index) => !viewed[index]).map(([path]) => path).join(", "));
  const adminAssets = readdirSync(join(repo, "frontend/dist/assets")).filter((name) => /\.(js|css)$/.test(name));
  const assetBodies = await Promise.all(adminAssets.map(async (name) =>
    (await fetch(`${base}/assets/${name}`, { headers: { Cookie: readerA.cookie } })).text()));
  check("no Admin build file is served to a user", assetBodies.every((body) => body.includes("<!doctype html") &&
        !/AdminLedger|\/api\/admin|usd_per_mtok/.test(body)));
  const adminRoutes = await Promise.all(["/api/admin/users", "/api/admin/holds", "/api/admin/ledger",
    "/api/admin/actions", "/api/admin/policy", "/api/admin/settings", "/api/intake", `/api/intake/${legacyId}`,
    "/api/case-library", "/api/research-analyses?capture_id=x"].map(async (path) => (await readerA.get(path)).status));
  check("every admin, operator and library route answers 403 to a user", adminRoutes.every((status) => status === 403),
        adminRoutes.join());

  section("1. other accounts' records");
  let readerB = await login("reader-b");
  const unknown = await readerB.get(analysisPath(`${high.slice(0, -4)}ffff`));
  const foreign = [await readerB.get(analysisPath(high)), await readerB.get(`${analysisPath(high)}/export`),
    await readerB.get(`/api/user/sources/${enc(firstSource)}`), await readerB.post(`${analysisPath(high)}/quotes`, {}),
    await readerB.post(`${analysisPath(high)}/runs`, approvalOf(highQuote)),
    await readerB.post(`${analysisPath(high)}/reviews`, { parent_review_id: null, result_sha256: "0".repeat(64),
                                                          status: null, notes: "x" })];
  check("reader-b gets Not Found for reader-a's analysis, export, source, quote, run and review",
        foreign.every((reply) => reply.status === 404 && reply.body?.code === "not_found") &&
        foreign[0].text === unknown.text);
  check("reader-b's lists hold none of reader-a's records",
        (await readerB.get("/api/user/analyses")).body.analyses.length === 0 &&
        (await readerB.get("/api/user/sources")).body.sources.length === 0);
  const legacy = [await readerA.get(`/api/user/sources/${enc(legacyId)}`),
                  await readerA.post("/api/user/analyses", { source_id: legacyId, effort: "low" })];
  check("the operator's capture stays the administrator's: Not Found to a user, and in no user list",
        legacy.every((reply) => reply.status === 404) &&
        !(await readerA.get("/api/user/sources")).body.sources.some((source) => source.source_id === legacyId));

  // ================================================================ 3. Effort, quotes and refusals before any send
  section("3. another Effort is a separate analysis; refusals before any send");
  admin = await login("admin");  // The earlier admin session ended with the clock's jumps.
  await open(`/sources/${enc(firstSource)}`);
  await waitFor(`!!document.querySelector('input[name="effort"][value="low"]')`);
  await click('input[name="effort"][value="low"]');
  await click(".client-prepare");
  await waitFor(`location.pathname.startsWith("/analyses/") && !location.pathname.endsWith(${JSON.stringify(enc(high))})`);
  const low = decodeURIComponent((await evaluate("location.pathname")).split("/")[2]);
  await waitFor(`document.querySelector(".client-state")?.dataset.panel === "quote"`);
  await click(".client-get-quote");
  await waitFor(`!!document.querySelector(".client-approve input")`);
  await click(".client-approve input");
  const lowQuote = (await stateOf(readerA, low)).quote;
  await open(`/sources/${enc(firstSource)}`);
  await waitFor(`!!document.querySelector('input[name="effort"][value="medium"]')`);
  await click('input[name="effort"][value="medium"]');
  await click(".client-prepare");
  await waitFor(`location.pathname.startsWith("/analyses/") && !location.pathname.endsWith(${JSON.stringify(enc(low))})`);
  const medium = decodeURIComponent((await evaluate("location.pathname")).split("/")[2]);
  check("the other Effort's analysis asks for its own quote", await waitFor(
    `document.querySelector(".client-state")?.dataset.panel === "quote"`) && medium !== low && medium !== high);
  await open(`/analyses/${enc(low)}`);
  check("returning to the first analysis shows its quote again, not approved", await waitFor(
    `document.querySelector(".client-quote.is-approval")?.dataset.quote === ${JSON.stringify(lowQuote.quote_id)}`) &&
        !(await evaluate(`document.querySelector(".client-approve input").checked`)) &&
        (await evaluate(`document.querySelector(".client-run").disabled`)));
  const sentAtRefusals = await providerCount();
  const tampered = [
    await runOf(readerA, { id: low }, { ...approvalOf(lowQuote), effort: "medium" }),
    await runOf(readerA, { id: low }, { ...approvalOf(lowQuote), credits: lowQuote.credits - 1 }),
    await runOf(readerA, { id: medium }, approvalOf(lowQuote)),
  ];
  check("an approval with another Effort, fewer credits or for another analysis is a quote mismatch",
        tampered.every((reply) => reply.status === 409 && reply.body.code === "quote_mismatch"),
        tampered.map((reply) => `${reply.status} ${reply.body?.code}`).join());
  check("an approval that is not explicit is refused", (await runOf(readerA, { id: low },
    { ...approvalOf(lowQuote), approve: false })).status === 422);
  await click(".client-approve input");
  await advance(901);  // Past the quote's 15 minutes.
  await click(".client-run");
  check("an expired quote is refused at run time, with a new quote offered", await waitFor(
    `document.querySelector(".client-notice")?.dataset.code === "quote_expired"`) &&
        (await clickText(".client-notice button", "Get a new quote")));
  await waitFor(`!!document.querySelector(".client-approve input")`);
  await click(".client-approve input");
  const v2 = { model: "claude-sonnet-5-5", efforts: { low: { extra_credits: 0 }, medium: { extra_credits: 1 } },
               credits: { base: 1, per_1k_input_tokens: 1, per_1k_output_tokens: 0 }, max_request_usd: 5.0,
               quote_valid_seconds: 900 };
  check("the admin publishes policy version 2 without High", (await admin.admin("/api/admin/policy",
    { policy: v2, reason: "SYNTHETIC: Low and Medium only", idempotency_key: "joint-policy-v2-0001" })).status === 201);
  await click(".client-run");
  check("a quote issued under the earlier policy is superseded at run time", await waitFor(
    `document.querySelector(".client-notice")?.dataset.code === "quote_superseded"`));
  const secondSource = (await readerA.post("/api/user/sources", sourceForm("Simulated ministry releases monthly trade data"))).body.source.source_id;
  const analysesBefore = (await readerA.get("/api/user/analyses")).body.analyses.length;
  const unsupported = await readerA.post("/api/user/analyses", { source_id: secondSource, effort: "high" });
  check("preparing at an Effort no longer offered is refused with the server's options", unsupported.status === 409 &&
        unsupported.body.code === "unsupported_effort" &&
        JSON.stringify(unsupported.body.efforts.map((option) => option.effort)) === '["low","medium"]' &&
        (await readerA.get("/api/user/analyses")).body.analyses.length === analysesBefore);
  await open(`/sources/${enc(secondSource)}`);
  check("the source page offers only the server's current Efforts", await waitFor(`JSON.stringify([...document
    .querySelectorAll('input[name="effort"]')].map((input) => input.value)) === '["low","medium"]'`));
  readerB = await login("reader-b");
  const accountIds = Object.fromEntries((await admin.get("/api/admin/users")).body.users
    .map((user) => [user.username, user.user_id]));
  const [readerAId, readerBId] = [accountIds["reader-a"], accountIds["reader-b"]];
  const bOne = await quoted(readerB, "Simulated agency reports regional output", "low");
  const noLimit = await runOf(readerB, bOne);
  check("a user without a daily limit is refused", noLimit.status === 409 && noLimit.body.code === "no_daily_limit");
  await admin.admin(`/api/admin/users/${enc(readerBId)}/daily-limit`, { limit: 1, reason: "SYNTHETIC limit" });
  await admin.admin(`/api/admin/users/${enc(readerBId)}/credits`, { kind: "grant", credits: 1,
    reason: "SYNTHETIC: fewer than a quote", idempotency_key: "joint-grant-b-0001" });
  const poor = await runOf(readerB, bOne);
  check("a run needing more credits than available is refused, with the server's figures", poor.status === 409 &&
        poor.body.code === "insufficient_credits" && poor.body.credits?.available === 1);
  check("no refusal reserved or sent anything", (await providerCount()) === sentAtRefusals &&
        (await holdsFor(admin)).length === 0 &&
        (await readerA.get("/api/user/account")).body.credits.available === 30 - highQuote.credits);

  // ================================================================ 4. a lost reply, and a failure before the server
  section("4. a run whose reply is lost after the server accepted it");
  await open(`/analyses/${enc(low)}`);
  await waitFor(`document.querySelector(".client-state")?.dataset.panel === "quote"`);
  await click(".client-get-quote");
  await waitFor(`!!document.querySelector(".client-approve input")`);
  await click(".client-approve input");
  await interceptUserApi({ runReply: true });
  const sentAtLost = await providerCount();
  await click(".client-run");
  check("the page knows only that it does not know: Check again, and nothing else", await waitFor(
    `document.querySelector(".client-state")?.dataset.panel === "uncertain"`, 20000) &&
        (await exists('[data-uncertain="run"] .client-check')) && (await noResend()) &&
        intercepted.some((item) => item.atResponse && item.status === 201));
  check("the server ran it once", (await providerCount()) === sentAtLost + 1 &&
        (await stateOf(readerA, low)).state === "recorded");
  await shoot("02-uncertain-after-lost-reply");
  intercept.readPath = analysisPath(low);
  await click(".client-check");
  for (const start = Date.now(); !intercepted.some((item) => item.method === "GET") && Date.now() - start < 10000;) {
    await sleep(50);
  }
  await waitFor(`!!document.querySelector(".client-notice") && !document.querySelector(".client-check").disabled`);
  check("a failed read keeps the gate", (await panel()) === "uncertain" && (await noResend()) &&
        intercepted.some((item) => item.method === "GET"));
  await stopIntercepting();
  await click(".client-check");
  check("a successful read shows the recorded run, charged once", await waitFor(
    `document.querySelector(".client-state")?.dataset.panel === "recorded"`) &&
        (await evaluate(`document.querySelector(".client-charge")?.dataset.charge`)) === "charged" &&
        (await providerCount()) === sentAtLost + 1);

  section("4. a run that failed before reaching the server");
  await open(`/analyses/${enc(medium)}`);
  await waitFor(`document.querySelector(".client-state")?.dataset.panel === "quote"`);
  await click(".client-get-quote");
  await waitFor(`!!document.querySelector(".client-approve input")`);
  const mediumQuote = await evaluate(`document.querySelector(".client-quote.is-approval").dataset.quote`);
  await click(".client-approve input");
  await interceptUserApi({ runRequest: true });
  await click(".client-run");
  check("it is uncertain on the page too", await waitFor(`document.querySelector(".client-state")?.dataset.panel === "uncertain"`) &&
        (await noResend()));
  check("the server has no attempt and the quote is still active", (await providerCount()) === sentAtLost + 1 &&
        (await stateOf(readerA, medium)).state === "prepared" &&
        (await stateOf(readerA, medium)).quote?.quote_id === mediumQuote);
  await stopIntercepting();
  await click(".client-check");
  check("the read restores the ordinary approval: the same quote, not approved", await waitFor(
    `document.querySelector(".client-quote.is-approval")?.dataset.quote === ${JSON.stringify(mediumQuote)}`) &&
        !(await evaluate(`document.querySelector(".client-approve input").checked`)));
  await click(".client-approve input");
  await waitFor(`!document.querySelector(".client-run").disabled`);
  await click(".client-run");
  check("approving again runs it once", await waitFor(`document.querySelector(".client-state")?.dataset.panel === "recorded"`, 20000) &&
        (await providerCount()) === sentAtLost + 2);

  // ================================================================ 5, 9. concurrent replays; reads while a run is held
  section("5. four concurrent replays of one approval, and one more; 9. reads stay responsive");
  // The SYNTHETIC policy charges a credit per 1,000 assumed input tokens. Since research-prompt-2 the planning estimate
  // assumes 1,000 tokens for the JSON output format's system prompt, so a quote here is one credit above what it was;
  // this top-up keeps reader-a able to run it.
  await admin.admin(`/api/admin/users/${enc(readerAId)}/credits`, { kind: "grant", credits: 10,
    reason: "SYNTHETIC top-up for the replays", idempotency_key: "joint-grant-a-0003" });
  const replayed = await quoted(readerA, "Simulated bureau publishes housing starts", "low");
  await hold("provider", true);
  const sentAtReplay = await providerCount();
  const approval = JSON.stringify(approvalOf(replayed.quote));
  const settled = [];
  const concurrent = Array.from({ length: 4 }, () => readerA.post(`${analysisPath(replayed.id)}/runs`, approval)
    .then((reply) => { settled.push(reply); return reply; }));
  const inTransport = await waitGate("provider", 1);
  for (const start = Date.now(); settled.length < 3 && Date.now() - start < 10000;) await sleep(50);
  check("while one is in transport, the other three are duplicates of it, showing it running", inTransport &&
        settled.length === 3 && settled.every((reply) => reply.status === 200 && reply.body.duplicate === true &&
        reply.body.analysis.state === "running" && reply.body.analysis.charge.state === "held"));
  const reads = [await readerA.get("/api/session"), await readerA.get("/api/user/account"),
    await readerA.get(analysisPath(replayed.id)), await admin.get("/api/admin/holds"), await admin.get("/api/admin/actions"),
    await admin.get("/api/admin/users")];
  check("session, account, analysis and Admin reads answer within 2 seconds meanwhile",
        reads.every((reply) => reply.status === 200 && reply.ms < 2000), reads.map((reply) => Math.round(reply.ms)).join());
  const heldRow = await holdOf(admin, replayed.id);
  check("the Admin holds list shows it held, with a worker, not resolvable", heldRow?.worker_active === true &&
        heldRow?.resolvable === false && heldRow?.entitlement?.state === "held");
  await hold("provider", false);
  const all = await Promise.all(concurrent);
  const again = await readerA.post(`${analysisPath(replayed.id)}/runs`, approval);
  check("exactly one reply created the run; every other one, and a later replay, is a duplicate",
        all.filter((reply) => reply.status === 201 && reply.body.duplicate === false).length === 1 &&
        again.status === 200 && again.body.duplicate === true && again.body.analysis.state === "recorded");
  const replayLedger = (await admin.get(`/api/admin/ledger?user_id=${enc(readerAId)}`)).body.entries
    .filter((entry) => entry.attempt_id === heldRow.attempt_id);
  check("one send, one hold, settled once at the quote", (await providerCount()) === sentAtReplay + 1 &&
        replayLedger.filter((entry) => entry.kind === "hold").length === 1 &&
        replayLedger.filter((entry) => entry.kind !== "hold").length === 1 &&
        replayLedger.find((entry) => entry.kind === "hold").amount === -replayed.quote.credits &&
        (await stateOf(readerA, replayed.id)).charge.credits_charged === replayed.quote.credits);

  section("3. today's allowance is used");
  await open(`/sources/${enc(replayed.sourceId)}`);
  await waitFor(`!!document.querySelector('input[name="effort"][value="medium"]')`);
  await click('input[name="effort"][value="medium"]');
  await click(".client-prepare");
  await waitFor(`document.querySelector(".client-state")?.dataset.panel === "quote"`);
  await click(".client-get-quote");
  await waitFor(`!!document.querySelector(".client-approve input")`);
  await click(".client-approve input");
  const sentAtDaily = await providerCount();
  await click(".client-run");
  check("a run beyond the daily limit is refused with the day's reset in Jerusalem and UTC", await waitFor(
    `document.querySelector(".client-notice")?.dataset.code === "daily_limit_reached"`) &&
        (await text(".client-notice")).includes("3 of 3 analyses used on 21 Oct 2026.") &&
        (await text(".client-notice")).includes("The day resets 22 Oct 2026, 00:00 (Asia/Jerusalem) (21 Oct 2026, 21:00 UTC).") &&
        (await providerCount()) === sentAtDaily);

  // ================================================================ 6. two users, the day boundary, DST, a restart
  section("6. the Admin screens set reader-b's terms");
  await setClock("2026-10-24T20:59:00+00:00", true);  // Saturday 24 October, 23:59 in Jerusalem (IDT, UTC+3).
  await open("/sign-in");  // The sign-in form appears only to a signed-out browser.
  check("the browser's session has expired", await waitFor(`!!document.querySelector(".shell-form")`));
  await signIn("admin");
  await open("/admin");
  await waitFor(`!!document.querySelector('tr[data-user="reader-b"] .admin-link')`);
  await click('tr[data-user="reader-b"] .admin-link');
  await waitFor(`!!document.querySelector('form[aria-label="Credits for reader-b"]')`);
  await setValue('form[aria-label="Credits for reader-b"] input[name="credits"]', "49");
  await setValue('form[aria-label="Credits for reader-b"] input[name="reason"]', "SYNTHETIC grant in the joint check");
  await click('form[aria-label="Credits for reader-b"] button[type=submit]');
  await waitFor(`document.querySelector('tr[data-user="reader-b"] [data-field="available"]')?.textContent === "50"`);
  await setValue('form[aria-label="Daily limit for reader-b"] input[name="limit"]', "2");
  await setValue('form[aria-label="Daily limit for reader-b"] input[name="reason"]', "SYNTHETIC limit in the joint check");
  await click('form[aria-label="Daily limit for reader-b"] button[type=submit]');
  check("the admin grants reader-b 49 credits and a daily limit of 2", await waitFor(
    `document.querySelector('tr[data-user="reader-b"] [data-field="limit"]')?.textContent === "2" &&
     document.querySelector('tr[data-user="reader-b"] [data-field="available"]')?.textContent === "50"`));

  section("6. two users at the daily boundary, concurrently");
  admin = await login("admin");
  readerA = await login("reader-a");
  readerB = await login("reader-b");
  await admin.admin(`/api/admin/users/${enc(readerAId)}/credits`, { kind: "grant", credits: 30,
    reason: "SYNTHETIC grant for the day's runs", idempotency_key: "joint-grant-a-0002" });
  const bRuns = [await quoted(readerB, "Simulated office counts new firms", "low"),
                 await quoted(readerB, "Simulated office counts closed firms", "low"),
                 await quoted(readerB, "Simulated office counts firm transfers", "low")];
  const aRun = await quoted(readerA, "Simulated institute surveys employers", "low");
  const sentAtRace = await providerCount();
  const raced = await Promise.all([...bRuns.map((item) => runOf(readerB, item)), runOf(readerA, aRun)]);
  const bReplies = raced.slice(0, 3);
  check("reader-b's three concurrent runs: exactly two run, one is refused for the day",
        bReplies.filter((reply) => reply.status === 201).length === 2 &&
        bReplies.filter((reply) => reply.status === 409 && reply.body.code === "daily_limit_reached").length === 1,
        bReplies.map((reply) => `${reply.status} ${reply.body?.code ?? ""}`).join());
  check("reader-a's run beside them is unaffected", raced[3].status === 201 && raced[3].body.analysis.state === "recorded",
        `${raced[3].status} ${raced[3].body?.code ?? ""}`);
  check("three sends in all", (await providerCount()) === sentAtRace + 3);
  const bAccount = (await readerB.get("/api/user/account")).body;
  check("reader-b's account: two used on 24 October, resetting at 21:00 UTC", bAccount.daily.used === 2 &&
        bAccount.daily.remaining === 0 && bAccount.daily.day === "2026-10-24" &&
        Date.parse(bAccount.daily.resets_at) === Date.parse("2026-10-24T21:00:00Z") &&
        bAccount.credits.available === 50 - 2 * bRuns[0].quote.credits && bAccount.credits.held === 0);

  section("6. the 25-hour quota day at the end of daylight saving time");
  await signOutAdmin();
  await signIn("reader-b");
  await open("/analyses");
  await waitFor(`!!document.querySelector('[data-entitlement="reset"]')`);
  check("at 23:59 the Client shows the day ending at midnight, 21:00 UTC",
        (await entitlement("reset")).includes("25 Oct 2026, 00:00 (Asia/Jerusalem)") &&
        (await entitlement("reset")).includes("24 Oct 2026, 21:00 UTC") &&
        (await entitlement("daily")).startsWith("0 of 2 analyses left today (2 used on 24 Oct 2026)"));
  await setClock("2026-10-24T21:00:00+00:00", true);  // Midnight: Sunday 25 October, which has 25 hours.
  await clickText(".client-entitlements button", "Read again");
  check("at midnight the new day resets 25 hours later, at 22:00 UTC", await waitFor(
    `document.querySelector('[data-entitlement="reset"]')?.textContent.includes("25 Oct 2026, 22:00 UTC")`) &&
        (await entitlement("reset")).includes("26 Oct 2026, 00:00 (Asia/Jerusalem)") &&
        (await entitlement("daily")).startsWith("2 of 2 analyses left today (0 used on 25 Oct 2026)"));
  const newDay = (await readerB.get("/api/user/account")).body.daily;
  check("the server's day is 25 October, resetting at 2026-10-25T22:00Z", newDay.day === "2026-10-25" &&
        Date.parse(newDay.resets_at) === Date.parse("2026-10-25T22:00:00Z"));

  section("6. two runs for the last credits, concurrently");
  const refusedB = bRuns[bReplies.findIndex((reply) => reply.status === 409)];
  const lastCredits = await quoted(readerB, "Simulated office counts firm mergers", "low");
  const available = (await readerB.get("/api/user/account")).body.credits.available;
  const enough = Math.max(refusedB.quote.credits, lastCredits.quote.credits);  // One run, never both.
  await admin.admin(`/api/admin/users/${enc(readerBId)}/credits`, { kind: "correction",
    credits: enough - available, reason: "SYNTHETIC: credits for exactly one run",
    idempotency_key: "joint-correction-b-0001" });
  const sentAtCredits = await providerCount();
  const creditRace = await Promise.all([runOf(readerB, refusedB), runOf(readerB, lastCredits)]);
  check("exactly one runs; the other is refused for credits", creditRace.filter((reply) => reply.status === 201).length === 1 &&
        creditRace.filter((reply) => reply.status === 409 && reply.body.code === "insufficient_credits").length === 1,
        creditRace.map((reply) => `${reply.status} ${reply.body?.code ?? ""}`).join());
  const winner = [refusedB, lastCredits][creditRace.findIndex((reply) => reply.status === 201)];
  const bLeft = enough - winner.quote.credits;
  check("one send; reader-b has only what the winner left, nothing held", (await providerCount()) === sentAtCredits + 1 &&
        (await readerB.get("/api/user/account")).body.credits.available === bLeft &&
        (await readerB.get("/api/user/account")).body.credits.held === 0);

  section("6. a restart changes nothing");
  const before = { a: (await readerA.get("/api/user/account")).body, b: (await readerB.get("/api/user/account")).body,
                   ledger: (await admin.get("/api/admin/ledger")).body, holds: await holdsFor(admin) };
  await stopServer();
  await startServer(true, "2026-10-24T21:00:00+00:00");
  await setClock("2026-10-24T21:00:00+00:00", true);
  const after = { a: (await readerA.get("/api/user/account")).body, b: (await readerB.get("/api/user/account")).body,
                  ledger: (await admin.get("/api/admin/ledger")).body, holds: await holdsFor(admin) };
  check("accounts, ledger and holds are identical after the restart", JSON.stringify(before) === JSON.stringify(after));
  const refusedAgain = creditRace.findIndex((reply) => reply.status === 409);
  const retried = await runOf(readerB, [refusedB, lastCredits][refusedAgain]);
  check("the refused run is still refused, and nothing is sent", retried.status === 409 &&
        retried.body.code === "insufficient_credits" && (await providerCount()) === sentAtCredits + 1);
  await reload();
  check("the browser's session survived the restart", await waitFor(`!!document.querySelector("main.page.client")`) &&
        (await waitFor(`document.querySelector('[data-entitlement="credits"]')?.textContent ===
          "${bLeft} ${bLeft === 1 ? "credit" : "credits"} available"`)));

  section("6. the fixed quota zone, in the Admin screen");
  await signOutClient();
  await signIn("admin");
  await open("/admin/policy");
  check("the Admin screen says the zone is fixed", await waitFor(`!!document.querySelector('[data-zone="fixed"]')`));
  await setValue('form[aria-label="Quota time zone"] input[name="quota_timezone"]', "Europe/London");
  await setValue('form[aria-label="Quota time zone"] input[name="reason"]', "SYNTHETIC: try another zone");
  await click('form[aria-label="Quota time zone"] button[type=submit]');
  check("changing it is refused with the server's reason", await waitFor(
    `!!document.querySelector('form[aria-label="Quota time zone"] .admin-problem')`));
  const settings = (await admin.get("/api/admin/settings")).body;
  const same = await admin.admin("/api/admin/settings", { quota_timezone: "Asia/Jerusalem", reason: "SYNTHETIC: unchanged" });
  check("the zone stays Asia/Jerusalem; repeating it changes nothing", settings.quota_timezone === "Asia/Jerusalem" &&
        settings.fixed === true && same.status === 200 && same.body.changed === false);
  await shoot("03-fixed-zone-refused");

  // ================================================================ 7. held workers, a killed server, admin decisions
  section("7. a worker held before its send, past 15 minutes");
  await setClock("2026-10-26T06:00:00+00:00");  // Monday 26 October, 08:00 in Jerusalem (IST, UTC+2).
  admin = await login("admin");
  await admin.admin(`/api/admin/users/${enc(readerAId)}/daily-limit`, { limit: 10, reason: "SYNTHETIC limit" });
  await admin.admin(`/api/admin/users/${enc(readerAId)}/credits`, { kind: "grant", credits: 100,
    reason: "SYNTHETIC grant", idempotency_key: "joint-grant-a-0001" });
  readerA = await login("reader-a");
  const a1 = await quoted(readerA, "Simulated authority reports retail sales", "low");
  await hold("before_send", true);
  const sentAtHeld = await providerCount();
  const a1Run = runOf(readerA, a1);
  check("the worker waits before its send", await waitGate("before_send", 1));
  await advance(16 * 60);
  const a1Row = await holdOf(admin, a1.id);
  const a1Early = await decideAttempt(admin, a1Row, "return", 0, "SYNTHETIC: try to return a running attempt");
  check("past 15 minutes it is still running for the user, and held with a worker for the admin",
        (await stateOf(readerA, a1.id)).state === "running" && a1Row.worker_active === true && a1Row.resolvable === false);
  check("an admin decision is refused as in flight, and nothing is recorded", a1Early.status === 409 &&
        a1Early.body.code === "in_flight" && !!(await holdOf(admin, a1.id)) &&
        (await providerCount()) === sentAtHeld);
  await hold("before_send", false);
  const a1Done = await a1Run;
  check("released, it sends once and settles automatically at the quote", a1Done.status === 201 &&
        a1Done.body.analysis.state === "recorded" && a1Done.body.analysis.charge.state === "charged" &&
        a1Done.body.analysis.charge.credits_charged === a1.quote.credits && (await providerCount()) === sentAtHeld + 1 &&
        !(await holdOf(admin, a1.id)));

  section("7. one run in transport and one before its send when the server is killed");
  await open("/sign-in");  // The browser's admin session has expired by now.
  await signIn("reader-a");
  readerA = await browserSession();
  const a2 = await prepared(readerA, "Simulated commission publishes freight volumes", "low");
  const a3 = await quoted(readerA, "Simulated commission publishes passenger volumes", "low");
  await open(`/analyses/${enc(a2.id)}`);
  await waitFor(`document.querySelector(".client-state")?.dataset.panel === "quote"`);
  await click(".client-get-quote");
  await waitFor(`!!document.querySelector(".client-approve input")`);
  await click(".client-approve input");
  await hold("before_send", true);
  await hold("provider", true);
  const sentAtKill = await providerCount();
  await click(".client-run");
  await waitGate("before_send", 1);
  const staleObserved = (await holdOf(admin, a2.id)).observed;
  await hold("before_send", false);
  check("the browser's run reaches the fake provider and waits there", await waitGate("provider", 1) &&
        (await providerCount()) === sentAtKill + 1);
  await hold("before_send", true);
  const a3Run = runOf(readerA, a3).catch((error) => ({ status: 0, body: null, error }));  // Its server is killed.
  await waitGate("before_send", 1);
  check("the Client shows it running, sent once", (await text(".client-run")) === "Running…" &&
        (await text(".client-quote.is-approval")).includes("It is sent once and never again"));
  const heldReads = [await readerA.get("/api/session"), await readerA.get("/api/user/account"),
    await readerA.get(analysisPath(a2.id)), await admin.get("/api/admin/holds"), await admin.get("/api/admin/actions")];
  check("9. reads answer within 2 seconds while both are held", heldReads.every((reply) => reply.status === 200 &&
        reply.ms < 2000), heldReads.map((reply) => Math.round(reply.ms)).join());
  await advance(16 * 60);
  const inFlight = [await decideAttempt(admin, await holdOf(admin, a2.id), "charge", 1, "SYNTHETIC: early decision"),
                    await decideAttempt(admin, await holdOf(admin, a3.id), "return", 0, "SYNTHETIC: early decision")];
  check("past 15 minutes both are refused as in flight", inFlight.every((reply) => reply.status === 409 &&
        reply.body.code === "in_flight"));
  await stopServer();
  check("the killed server's reply never arrives: the Client is uncertain and offers only Check again",
        await waitFor(`document.querySelector(".client-state")?.dataset.panel === "uncertain"`, 15000) && (await noResend()));
  const a3Lost = await a3Run;
  check("the held run's reply is lost too", a3Lost.status >= 500 || a3Lost.status === 0 || a3Lost.body === null,
        String(a3Lost.status));
  await startServer(true, "2026-10-26T06:40:00+00:00");
  await hold("before_send", false);
  await hold("provider", false);
  const a2State = await stateOf(readerA, a2.id);
  const a3State = await stateOf(readerA, a3.id);
  check("after the restart the sent run is unresolved, held for review, never sent again", a2State.state === "unresolved" &&
        a2State.state_detail === "The request was sent, but no outcome was recorded. It is not sent again. Your credits " +
          "stay reserved until an administrator reviews this run." && a2State.charge.state === "under_review" &&
        (await providerCount()) === sentAtKill + 1);
  check("the run stopped before its send is unresolved too, and says nothing was sent", a3State.state === "unresolved" &&
        a3State.state_detail.startsWith("The run stopped before anything was sent. It is not run again."));
  await click(".client-check");
  check("Check again shows it held for review, with no way to send it again", await waitFor(
    `document.querySelector(".client-state")?.dataset.panel === "held"`) && (await noResend()) &&
        (await text(".client-chip.is-state")) === "Outcome not recorded" &&
        (await text(".client-attempt")) === "No outcome was recorded for this run. It is not sent again." &&
        (await text(".client-charge")).startsWith(`${a2State.charge.credits_reserved} credits held for an administrator's review`));
  await shoot("04-unresolved-after-restart");

  section("7. stale, competing and over-charging admin decisions");
  admin = await login("admin");
  const a2Row = await holdOf(admin, a2.id);
  check("the Admin holds list now offers a decision, with no worker", a2Row.resolvable === true &&
        a2Row.worker_active === false && a2Row.observed.sent_at !== null);
  const stale = await decideAttempt(admin, a2Row, "return", 0, "SYNTHETIC: decided on the state before the send",
                              staleObserved);
  check("a decision on the state from before the send is refused as changed", stale.status === 409 &&
        stale.body.code === "state_changed");
  const over = await decideAttempt(admin, a2Row, "charge", a2Row.credits + 1, "SYNTHETIC: more than the quote");
  check("charging more than the approved credits is refused", over.status === 422 && !!(await holdOf(admin, a2.id)));
  const competing = await Promise.all([1, 2].map(() => decideAttempt(admin, a2Row, "charge", a2Row.credits,
    "SYNTHETIC: the provider's Console shows the request")));
  check("two identical decisions at once: one applies, the other reports the applied one",
        competing.filter((reply) => reply.status === 201 && reply.body.applied === true).length === 1 &&
        competing.filter((reply) => reply.status === 409 && reply.body.code === "already_resolved").length === 1);
  const late = await decideAttempt(admin, a2Row, "return", 0, "SYNTHETIC: a later, different decision");
  check("a later, different decision is refused as already resolved", late.status === 409 &&
        late.body.code === "already_resolved");
  const a2Entries = (await admin.get(`/api/admin/ledger?user_id=${enc(readerAId)}`)).body.entries
    .filter((entry) => entry.attempt_id === a2Row.attempt_id);
  check("the ledger holds its hold and one settlement returning nothing (charged in full)",
        a2Entries.length === 2 && a2Entries[0].kind === "hold" && a2Entries[0].amount === -a2Row.credits &&
        a2Entries[1].kind === "settle" && a2Entries[1].amount === 0);

  section("7. an attempt returned before its worker took the lock never sends");
  const a4 = await quoted(readerA, "Simulated registry publishes vehicle counts", "low");
  await hold("after_reserve", true);
  const sentAtReturn = await providerCount();
  const a4Run = runOf(readerA, a4);
  await waitGate("after_reserve", 1);
  check("reserved and young, it shows as running", (await stateOf(readerA, a4.id)).state === "running");
  await advance(16 * 60);
  const a4Row = await holdOf(admin, a4.id);
  const a4Return = await decideAttempt(admin, a4Row, "return", 0, "SYNTHETIC: return before the worker continues");
  check("past 15 minutes with no worker holding it, the admin returns it once", a4Row.worker_active === false &&
        a4Row.resolvable === true && a4Return.status === 201 && a4Return.body.applied === true);
  await hold("after_reserve", false);
  const a4Reply = await a4Run;
  check("its worker then sends nothing and says so", a4Reply.status === 409 && a4Reply.body.code === "already_attempted" &&
        a4Reply.body.detail.includes("Nothing was sent.") &&
        a4Reply.body.detail.includes(`An administrator returned all ${a4.quote.credits} credits and the day's allowance.`) &&
        (await providerCount()) === sentAtReturn);
  const a4State = await stateOf(readerA, a4.id);
  check("the user sees it not sent, its credits returned", a4State.state === "not_sent" &&
        a4State.charge.state === "returned" && !existsSync(join(served, "research-analyses", "attempts", a4.id, "response.json")));

  // ================================================================ 8, 9. failed and unknown runs reconciled in the Admin screen
  section("8. reconciling failed and unknown attempts in the Admin screen");
  const t1 = await quoted(readerA, "Simulated provider timeout for a partial charge", "low");
  const t2 = await quoted(readerA, "Simulated provider timeout for a zero charge", "low");
  const sentAtTimeouts = await providerCount();
  const timeouts = [await runOf(readerA, t1), await runOf(readerA, t2)];
  check("two sends that time out are held for review, not refunded or retried", timeouts.every((reply) =>
    reply.status === 201 && reply.body.analysis.state === "failed" && reply.body.analysis.charge.state === "under_review") &&
        (await providerCount()) === sentAtTimeouts + 2);
  await signOutClient();
  readerA = await login("reader-a");  // The browser's session for reader-a ended with its sign-out.
  readerB = await login("reader-b");
  await signIn("admin");
  await open("/admin/actions");
  await waitFor(`!!document.querySelector('tr[data-request="${t1.id}"]')`);
  check("9. the Actions screen keeps unknown usage and cost unknown",
        (await text(`tr[data-request="${t1.id}"] [data-field="usage"]`)) === "Not reported" &&
        (await text(`tr[data-request="${t1.id}"] [data-field="cost"]`)) === "Unknown" &&
        (await text(`tr[data-request="${a2.id}"] [data-field="usage"]`)) === "Not reported" &&
        (await text(`tr[data-request="${a2.id}"] [data-field="cost"]`)) === "Unknown");
  await open("/admin/credits");
  const holdItem = async (id) => (await holdOf(admin, id)).attempt_id;
  const [a3Attempt, t1Attempt, t2Attempt] = [await holdItem(a3.id), await holdItem(t1.id), await holdItem(t2.id)];
  await waitFor(`document.querySelectorAll("li[data-attempt]").length === 3`);
  await shoot("05-admin-holds");
  // A resolution reloads the holds, and while they load the whole list is replaced by "Loading the holds…": a hold's
  // row being gone proves nothing until the list is back, and a form filled meanwhile is replaced by a fresh one.
  const holdsSettled = `!document.body.textContent.includes("Loading the holds")`;
  const decide = async (attempt, resolution, credits) => {
    const form = `form[aria-label="Resolve ${attempt}"]`;
    if (!(await waitFor(`${holdsSettled} && !!document.querySelector('${form}')`))) return false;
    if (!(await setValue(`${form} select[name="resolution"]`, resolution))) return false;
    if (credits !== null) {
      await waitFor(`!!document.querySelector('${form} input[name="credits_charged"]')`);
      if (!(await setValue(`${form} input[name="credits_charged"]`, String(credits)))) return false;
    }
    if (!(await setValue(`${form} input[name="reason"]`, `SYNTHETIC: ${resolution} ${credits ?? ""}`))) return false;
    await click(`${form} button[type=submit]`);
    return waitFor(`${holdsSettled} && !document.querySelector('li[data-attempt="${attempt}"]')`);
  };
  check("the admin returns the attempt stopped before its send", await decide(a3Attempt, "return", null));
  check("charges 1 credit for one timed-out attempt", await decide(t1Attempt, "charge", 1));
  check("and 0 credits for the other", await decide(t2Attempt, "charge", 0));
  check("nothing is held any more and every ledger reconciles", await waitFor(
    `document.body.textContent.includes("No credits are held.")`) && await waitFor(`[...document
    .querySelectorAll("li[data-user-total]")].length === 2 && [...document.querySelectorAll("li[data-user-total]")]
    .every((item) => item.textContent.includes("reconciles") && !item.textContent.includes("does not"))`));
  const ledger = (await admin.get("/api/admin/ledger")).body;
  const entriesOf = (attempt) => ledger.entries.filter((entry) => entry.attempt_id === attempt);
  const charged = (attempt) => -entriesOf(attempt).reduce((sum, entry) => sum + entry.amount, 0);
  const credits = { a2: a2Row.credits, a3: (await stateOf(readerA, a3.id)).charge.credits_reserved,
                    t1: t1.quote.credits, t2: t2.quote.credits, a4: a4.quote.credits };
  check("the ledger records each once: full, returned, 1 and 0 credits charged, and the early return",
        charged(a2Row.attempt_id) === credits.a2 && charged(a3Attempt) === 0 && charged(t1Attempt) === 1 &&
        charged(t2Attempt) === 0 && charged(a4Row.attempt_id) === 0 &&
        [a2Row.attempt_id, a3Attempt, t1Attempt, t2Attempt, a4Row.attempt_id].every((attempt) =>
          entriesOf(attempt).filter((entry) => entry.kind === "hold").length === 1 && entriesOf(attempt).length === 2));
  const totals = ledger.totals;
  const accountA = (await readerA.get("/api/user/account")).body.credits;
  check("each user's account is the ledger's total", accountA.available === totals[readerAId].available &&
        accountA.held === 0 && (await readerB.get("/api/user/account")).body.credits.available === totals[readerBId].available);

  section("8. the Client says what the ledger says, and offers no resend");
  await signOutAdmin();
  await signIn("reader-a");
  const expected = [
    [a2.id, "held", `${credits.a2} credits charged of ${credits.a2} credits reserved, counted on 26 Oct 2026's allowance.`,
     `The request was sent, but no outcome was recorded. It is not sent again. An administrator settled it: ${credits.a2} of the ${credits.a2} reserved credits were charged.`],
    [a3.id, "not_sent", `${credits.a3} credits returned; nothing was charged.`,
     `Nothing was sent. This prepared analysis cannot be run again. An administrator returned all ${credits.a3} credits and the day's allowance.`],
    [t1.id, "held", `1 credit charged of ${credits.t1} credits reserved; ${credits.t1 - 1} returned, counted on 26 Oct 2026's allowance.`,
     `The analysis service returned an error. It is not run again. An administrator settled it: 1 of the ${credits.t1} reserved credits were charged, and ${credits.t1 - 1} were returned.`],
    [t2.id, "held", `0 credits charged of ${credits.t2} credits reserved; ${credits.t2} returned, counted on 26 Oct 2026's allowance.`,
     `The analysis service returned an error. It is not run again. An administrator settled it: 0 of the ${credits.t2} reserved credits were charged, and ${credits.t2} were returned.`],
    [a4.id, "not_sent", `${credits.a4} credits returned; nothing was charged.`,
     `Nothing was sent. This prepared analysis cannot be run again. An administrator returned all ${credits.a4} credits and the day's allowance.`],
  ];
  for (const [id, shown, chargeText, detail] of expected) {
    await open(`/analyses/${enc(id)}`);
    await waitFor(`document.querySelector(".client-state")?.dataset.panel === "${shown}"`);
    const server = await stateOf(readerA, id);
    const ok = (await panel()) === shown && (await text(".client-charge")) === chargeText &&
      (await text(".client-state-detail")) === detail && server.state_detail === detail && (await noResend());
    check(`${id.slice(-12)}: "${chargeText}"`, ok, `${await panel()} | ${await text(".client-charge")} | ` +
          `${await text(".client-state-detail")}`);
    if (id === t1.id) await shoot("06-partial-charge-copy");
  }

  section("2. a source of 50,000 emoji typed in the browser: four bytes each, past the 120,000 a form had before");
  const wide = { ...sourceForm("Simulated survey written in four-byte characters"),
                 source_text: "\u{1F4C8}".repeat(50_000) };
  supplied.add(wide.source_text);
  await fillSource(wide);
  check("the form counts 50,000 characters, as the server does", await waitFor(`[...document.querySelectorAll(
    ".client-sub")].some((node) => node.textContent === "50,000 of 50,000 characters" && !node.classList.contains(
    "is-over"))`));
  await click(".client-save-source");
  await waitFor(`location.pathname.startsWith("/sources/") && location.pathname !== "/sources/new"`, 20000);
  const wideId = decodeURIComponent((await evaluate("location.pathname")).split("/")[2]);
  const wideSource = (await (await browserSession()).get(`/api/user/sources/${enc(wideId)}`)).body.source;
  check("the browser's form is accepted whole: every character kept, nothing truncated",
        wideSource?.characters === 50_000 && wideSource?.text === wide.source_text,
        `${wideSource?.characters} characters`);

  section("1. unsaved work across an expiry reaches only the same account, on real sessions");
  const isolated = sourceForm("Simulated unsaved source that only reader-a may get back");
  const sourceCount = async (user) => (await user.get("/api/user/sources")).body.sources.length;
  readerB = await login("reader-b");
  const countsBefore = [await sourceCount(await browserSession()), await sourceCount(readerB)];
  await fillSource(isolated);
  await advance(13 * 3600);  // Past the 12-hour session; no later step reads a date.
  await click(".client-save-source");
  await waitFor(`!!document.querySelector(".client-ended")`);
  await clickText(".client-ended button", "Sign in again");
  await signIn("reader-b");
  await waitFor(`!!document.querySelector('input[name="headline"]')`);
  await sleep(400);
  check("reader-b signing in at the same address gets an empty form and nothing of reader-a's",
        (await evaluate(`document.querySelector('input[name="headline"]').value === "" &&
          document.querySelector('textarea[name="source_text"]').value === "" &&
          !document.querySelector("[data-recovered], [data-recovered-list]") &&
          !document.body.innerText.includes(${JSON.stringify(isolated.headline)})`)));
  readerB = await browserSession();
  const countB = await sourceCount(readerB);
  await signOutClient();
  await signIn("reader-a");
  await sleep(400);
  check("and reader-a signing in afterwards gets nothing back: reader-b's sign-in discarded it, and nothing was saved",
        !(await evaluate(`!!document.querySelector("[data-recovered], [data-recovered-list]")`)) &&
        JSON.stringify([await sourceCount(await browserSession()), countB]) === JSON.stringify(countsBefore));

  // ================================================================ the whole run
  section("every send, every key, every payload");
  const sends = readdirSync(join(served, "simulated-provider")).filter((name) => /^request-\d+\.json$/.test(name));
  const hashes = sends.map((name) => sha(readFileSync(join(served, "simulated-provider", name))));
  const savedHashes = new Set(readdirSync(join(served, "research-analyses", "requests")).map((id) =>
    sha(readFileSync(join(served, "research-analyses", "requests", id, "request.json")))));
  check("each send is a different saved request, sent once", new Set(hashes).size === hashes.length &&
        hashes.every((hash) => savedHashes.has(hash)), `${hashes.length} sends`);
  check("every send carried the dummy key, never the environment's", sends.every((name) => JSON.parse(readFileSync(
    join(served, "simulated-provider", name.replace("request-", "received-")), "utf8")).x_api_key_is_the_dummy_key));
  const ids = userPayloads.flatMap(({ text }) => [...text.matchAll(/"(analysis_id|source_id)":\s*"([^"]*)"/g)]);
  check("every ID a user sees has the contract's opaque form", ids.length > 0 && ids.every(([, kind, id]) =>
    kind === "source_id" ? /^\d{8}T\d{12}Z-[0-9a-f]{12}$/.test(id) : /^[A-Za-z0-9._-]{1,160}$/.test(id)));
  const leaks = userPayloads.filter(({ text }) => {
    let scrubbed = text;
    for (const value of supplied) scrubbed = scrubbed.split(JSON.stringify(value).slice(1, -1)).join("");
    // Opaque IDs (contract section 3: "Clients must not parse them") are checked by their pattern, not as words.
    scrubbed = scrubbed.replace(/\d{8}T\d{12}Z-[0-9a-f]{12}(\.[A-Za-z0-9_-]+)*/g, "ID");
    return ADMIN_ONLY.test(scrubbed);
  });
  check("no user reply, refusal or export carries an admin field", leaks.length === 0,
        leaks.map(({ path, text }) => `${path}: ${text.match(ADMIN_ONLY)?.[0]}`).slice(0, 5).join(" | "));
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  const narrow = [];
  for (const path of ["/", `/analyses/${enc(t1.id)}`, `/analyses/${enc(high)}`, "/sources/new"]) {
    await open(path);
    await waitFor(`!!document.querySelector("main.page.client h1")`);
    narrow.push(await evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"));
  }
  check("at phone width the Client pages have no sideways scroll", narrow.every(Boolean), narrow.join());
  const outside = requests.filter((request) => !request.url.startsWith(base) && !request.url.startsWith("data:") &&
    request.url !== "about:blank");
  check("the pages requested nothing outside the local server", outside.length === 0,
        outside.map((request) => request.url).join(", "));
  check("no page error", errors.length === 0, errors.join(" | "));
  ws.close();
} catch (error) {
  check("the joint check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(500);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
