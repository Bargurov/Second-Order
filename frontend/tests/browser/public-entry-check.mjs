// Browser check of the signed-out pages of the Client build (frontend/dist-client) in one headless Chrome, against a
// MOCK of the onboarding contract (onboarding-api-0.1) and the user contract's session routes that runs inside this
// script. The built bundle is served as the server serves it; /api/session, /api/session/login,
// /api/public/credit-terms, /api/public/registrations and /api/user/* are answered from the SYNTHETIC onboarding and
// user-contract fixtures. Every server-side behaviour seen here (a registration recorded, a duplicate recognised, a
// pending or rejected status, a sign-in) is the MOCK's: this proves what the pages show and send, never what the real
// server enforces. That is the joint journey's job (the real synthetic backend with a fake sender).
//
// The journey: the landing page, keyboard only (skip link, focus on every stop, Register by Enter) -> registration typed
// by keyboard: a local mistake sends nothing; one clean submit sends exactly four fields -> received; a repeat is a
// duplicate; a taken username and a refused field keep what was typed except the password -> a lost reply: nothing is
// resent until the person asks; the same registration again is a duplicate -> check by signing in: the pending status,
// with no session -> a rejected status -> a wrong password -> a lost sign-in reply: nothing resent, an explicit session
// check -> how credits work: the server's rules and synthetic quotes, no terms, a failed read and Read again -> desktop,
// tablet and phone widths -> a bookmarked research page and /credits keep their address through sign-in; /register
// opens the Client's home -> passwords only in the two requests that carry them, never in storage, a URL or the page ->
// outside requests, page errors, and the built bundle's contents.
//
//   cd frontend; npm run build; node tests/browser/public-entry-check.mjs
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
const ONBOARDING = "onboarding-api-0.1";
const PASSWORDS = { "reader-a": "synthetic-password", "reader-c": "synthetic-reader-c-pass",
  "reader-e": "synthetic-reader-e-pass", "reader-f": "synthetic-reader-f-pass", "reader-g": "synthetic-reader-g-pass" };
const ADMIN_ONLY = /claude|sonnet|opus|haiku|anthropic|openai|\$\s?\d|\busd\b|dollar|\btokens?\b|\bcosts?\b|\bproviders?\b|\bmodels?\b|planning|prompt|thinking|http status|tariff|usage-points-draft/i;
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};

// ---------------------------------------------------------------- the MOCK server (synthetic data only)

const userErrors = fixture("user-contract-errors");
const onboardingErrors = fixture("onboarding-errors");
// Size-based SYNTHETIC test terms, no terms, and flat terms at the selected rates computed by the server's own code.
const terms = { configured: fixture("onboarding-credit-terms"), none: fixture("onboarding-credit-terms-none"),
                flat: fixture("public-credit-terms-flat") };
const created = fixture("onboarding-registration-created");
const signedInA = fixture("user-contract-session-signed-in");
const accountA = fixture("user-contract-account");
const RULES = { username: /^[a-z0-9][a-z0-9._-]{2,39}$/, control: /[\x00-\x1f\x7f]/ };
const mock = { tokens: new Map(), requests: [], forbidden: 0, terms: "configured", dropRegistrationReply: false,
               dropLoginReply: false, registrations: new Map(), reserved: new Set(["reader-a", "admin"]) };
const STATUS = { not_signed_in: 401, session_expired: 401, invalid_credentials: 401, registration_pending: 403,
  registration_rejected: 403, forbidden: 403, not_found: 404, payload_too_large: 413, invalid_request: 422,
  invalid_registration: 422, username_unavailable: 409, accounts_unavailable: 503, internal_error: 500 };
const refuse = (code, extra = {}) => ({ status: STATUS[code] ?? 409, body: { ...copy(userErrors[code]), ...extra } });
const refusePublic = (code, extra = {}) => ({ status: STATUS[code], body: { ...copy(onboardingErrors[code]), ...extra } });
const registrationOf = (entry) => ({ ...copy(created.registration), username: entry.form.username,
  display_name: entry.form.display_name, status: entry.status, submitted_at: entry.submitted_at,
  decided_at: entry.status === "pending" ? null : entry.decided_at,
  detail: entry.status === "pending" ? created.registration.detail : userErrors.registration_rejected.registration.detail });

/** A signed-in user: Reader A from the fixtures, or an approved registrant whose account the administrator has not
 * yet given a daily allowance or credits (both missing steps, in the server's order, as the real server reports). */
const unallocated = fixture("user-contract-account-unallocated");
const noLimit = fixture("user-contract-account-unavailable").analysis.reasons[0];
function userNamed(username) {
  if (username === "reader-a") return { session: signedInA, account: accountA };
  const entry = mock.registrations.get(username);
  const user = { user_id: `u-5ca1ab1e0000a0${username.at(-1) === "e" ? "e5" : "f6"}`, username,
                 display_name: entry.form.display_name, role: "user" };
  return { session: { ...signedInA, user },
    account: { ...copy(unallocated), user, daily: { ...unallocated.daily, limit: null, remaining: null },
      analysis: { available: false, reason: noLimit.reason, detail: noLimit.detail,
                  reasons: [noLimit, ...unallocated.analysis.reasons] } } };
}

function register(body, request) {
  const keys = Object.keys(body ?? {}).sort().join(",");
  if (keys !== "display_name,note,password,username") return refusePublic("invalid_request");
  if (!RULES.username.test(body.username)) return refusePublic("invalid_registration", { field: "username" });
  if (body.display_name === "SYNTHETIC refused name") {  // A rule the page does not check: the server's refusal.
    return refusePublic("invalid_registration", { field: "display_name",
      detail: "A display name must not repeat a reserved name (SYNTHETIC rule of this MOCK)" });
  }
  if (body.password.length < 10 || RULES.control.test(body.password)) return refusePublic("invalid_registration", { field: "password" });
  const known = mock.registrations.get(body.username);
  if (known && known.status === "pending" && known.form.password === body.password) {
    return { status: 200, body: { contract: ONBOARDING, duplicate: true, registration: registrationOf(known) } };
  }
  if (known || mock.reserved.has(body.username)) return refusePublic("username_unavailable");
  const entry = { form: copy(body), status: "pending", submitted_at: "2026-10-14T09:00:00+00:00", decided_at: null };
  mock.registrations.set(body.username, entry);
  if (mock.dropRegistrationReply) {  // Recorded, then the reply is lost.
    mock.dropRegistrationReply = false;
    request.socket.destroy();
    return null;
  }
  return { status: 201, body: { contract: ONBOARDING, duplicate: false, registration: registrationOf(entry) } };
}

async function api(method, path, body, user, request, response, token) {
  if (path === "/api/session" && method === "GET") {
    return { status: 200, body: user ? user.session : { ...fixture("user-contract-session-signed-out"),
      reason: mock.signedOutReason ?? "not_signed_in" } };
  }
  if (path === "/api/session/login" && method === "POST") {
    if (mock.dropLoginReply) {
      mock.dropLoginReply = false;
      request.socket.destroy();
      return null;
    }
    const entry = mock.registrations.get(body?.username);
    if (entry && entry.form.password === body.password && entry.status !== "approved") {
      const code = `registration_${entry.status}`;
      return refuse(code, { registration: registrationOf(entry) });
    }
    const approved = entry && entry.form.password === body.password;
    if (!approved && (body?.username !== "reader-a" || body.password !== PASSWORDS["reader-a"])) {
      return refuse("invalid_credentials");
    }
    const token = randomBytes(16).toString("hex");
    mock.tokens.set(token, body.username);
    response.setHeader("Set-Cookie", `second_order_session=${token}; HttpOnly; SameSite=Strict; Path=/`);
    return { status: 200, body: userNamed(body.username).session };
  }
  if (path === "/api/session/logout" && method === "POST") {
    mock.tokens.delete(token);
    mock.signedOutReason = "signed_out";
    return { status: 200, body: { ...fixture("user-contract-session-signed-out"), reason: "signed_out" } };
  }
  if (path === "/api/public/credit-terms" && method === "GET") {
    return mock.terms === "fail" ? refusePublic("internal_error") : { status: 200, body: copy(terms[mock.terms]) };
  }
  if (path === "/api/public/registrations" && method === "POST") return register(body, request);
  if (!user) return refuse("not_signed_in");
  if (method === "GET" && path === "/api/user/account") return { status: 200, body: user.account };
  if (method === "GET" && path === "/api/user/analyses") {
    return { status: 200, body: user.session === signedInA ? fixture("user-contract-analyses")
      : { contract: "user-api-0.2", analyses: [] } };
  }
  if (method === "GET" && path === "/api/user/sources") return { status: 200, body: fixture("user-contract-sources") };
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
  const raw = Buffer.concat(chunks).toString("utf8");
  let body = null;
  try {
    body = raw ? JSON.parse(raw) : null;
  } catch { /* refused below as malformed */ }
  const token = /second_order_session=([0-9a-f]+)/.exec(request.headers.cookie ?? "")?.[1];
  const name = token ? mock.tokens.get(token) : null;
  const user = name ? userNamed(name) : null;
  const header = url.pathname.startsWith("/api/session") || url.pathname.startsWith("/api/public")
    ? "x-second-order-session" : "x-second-order-user";
  let reply;
  if (request.method === "POST" && (request.headers.origin !== base || request.headers[header] !== "1" ||
      !String(request.headers["content-type"]).startsWith("application/json"))) {
    mock.forbidden += 1;
    reply = refuse("forbidden");
  } else {
    reply = await api(request.method, url.pathname, body, user, request, response, token);
  }
  mock.requests.push({ method: request.method, path: url.pathname, status: reply?.status ?? "dropped", raw,
                       body: reply ? JSON.stringify(reply.body) : "", sent: body });
  if (!reply) return;
  response.writeHead(reply.status, { "Content-Type": "application/json", Connection: "close" });
  response.end(JSON.stringify(reply.body));
});

// ---------------------------------------------------------------- the browser

const root = mkdtempSync(join(tmpdir(), "second-order-public-check-"));
const children = [];
const posts = (part = "") => mock.requests.filter((item) => item.method === "POST" && item.path.includes(part)).length;
const gets = (part) => mock.requests.filter((item) => item.method === "GET" && item.path === part).length;
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
  const addresses = [];
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else if (message.method === "Network.requestWillBeSent") {
      browserRequests.push(message.params.request.url);
    } else if (message.method === "Page.frameNavigated") {
      addresses.push(message.params.frame.url);
    } else if (message.method === "Page.navigatedWithinDocument") {
      addresses.push(message.params.url);
    } else if (message.method === "Runtime.exceptionThrown") {
      pageErrors.push(message.params.exceptionDetails.text);
    } else if (message.method === "Log.entryAdded" && message.params.entry.level === "error") {
      const entry = message.params.entry;
      // A refused or dropped API request is logged by the browser: that is the scenario, not a page error.
      if (!(/status of (4\d\d|500)|ERR_EMPTY_RESPONSE|Failed to load resource/.test(entry.text) &&
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
    const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value").set.call(element, ${JSON.stringify(value)});
    element.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  })()`);
  const value = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.value ?? null`);
  const click = (selector) => evaluate(`(() => { const e = document.querySelector(${JSON.stringify(selector)});
    if (!e) return false; e.click(); return true; })()`);
  const clickText = (selector, text) => evaluate(`(() => { const e = [...document.querySelectorAll(${JSON.stringify(selector)})]
    .find((item) => item.textContent.trim() === ${JSON.stringify(text)}); if (!e) return false; e.click(); return true; })()`);
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);
  const exists = (selector) => evaluate(`!!document.querySelector(${JSON.stringify(selector)})`);
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete' && !document.querySelector('.shell-status')");
  };
  const key = async (name, modifiers = 0) => {
    const codes = { Tab: 9, Enter: 13, " ": 32 };
    const press = { key: name, code: name === " " ? "Space" : name, windowsVirtualKeyCode: codes[name], modifiers };
    await send("Input.dispatchKeyEvent", { type: "keyDown", ...press, ...(name === "Enter" ? { text: "\r" } : {}) });
    await send("Input.dispatchKeyEvent", { type: "keyUp", ...press });
  };
  const type = (words) => send("Input.insertText", { text: words });
  const focused = () => evaluate(`(() => { const e = document.activeElement; if (!e || e === document.body) return null;
    const style = getComputedStyle(e);
    return { tag: e.tagName, name: e.getAttribute("name"), text: e.textContent.trim().slice(0, 60), href: e.getAttribute("href"),
             ring: e.matches(":focus-visible") && style.outlineStyle !== "none" && parseFloat(style.outlineWidth) >= 2 }; })()`);
  /** Tab until `matches(stop)` holds; every stop on the way must show a visible ring. */
  const tabTo = async (matches, limit = 30) => {
    const stops = [];
    for (let press = 0; press < limit; press++) {
      await key("Tab");
      const stop = await focused();
      stops.push(stop);
      if (stop && matches(stop)) return { reached: true, stops };
    }
    return { reached: false, stops };
  };
  const pageWords = () => evaluate("document.body.innerText");
  const vocabulary = [];
  const scan = async (label) => {
    const match = ADMIN_ONLY.exec(await pageWords());
    if (match) vocabulary.push(`${label}: ${match[0]}`);
  };
  const noSideways = () => evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth");
  const shots = process.env.SECOND_ORDER_SCREENSHOTS;
  const shoot = async (name) => {  // Opt-in viewport captures; never a whole tall page.
    if (!shots) return;
    const shot = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(shots, `${name}.png`), Buffer.from(shot.data, "base64"));
  };
  const viewport = (width, height, mobile) =>
    send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: mobile ? 2 : 1, mobile });
  const fill = async (form) => {
    for (const [name, typed] of Object.entries(form)) await setValue(`.public-register [name="${name}"]`, typed);
  };
  const signInWith = async (username, password) => {
    await waitFor(`!!document.querySelector('.shell-form input[name="password"]')`);
    await setValue('.shell-form input[name="username"]', username);
    await setValue('.shell-form input[name="password"]', password);
    await click(".shell-form button[type=submit]");
  };

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Log.enable");
  await viewport(1280, 900, false);

  // 1. The landing page, signed out: what the product does, and the way in.
  await open("/");
  await waitFor(`!!document.querySelector('[data-public="landing"]')`);
  const landing = await evaluate(`({ register: !!document.querySelector('main a[href="/register"]'),
    signIn: !!document.querySelector('a[href="/sign-in"]'), credits: !!document.querySelector('a[href="/credits"]'),
    form: !!document.querySelector(".shell-form"), h1: document.querySelector("h1")?.textContent ?? "",
    example: document.querySelector('[data-public="example"]')?.innerText ?? "", words: document.body.innerText })`);
  check("signed out, / is the landing page: register, sign-in and credits links, no sign-in form",
    landing.register && landing.signIn && landing.credits && !landing.form && landing.h1.length > 0, JSON.stringify(landing.h1));
  check("the landing page's worked example is labelled as synthetic, with evidence, interpretation and unknowns apart",
    /synthetic/i.test(landing.example) && /not the publisher's words/i.test(landing.example) &&
    (await evaluate(`document.querySelectorAll('[data-public="example"] [data-surface]').length`)) === 3);
  check("the landing page states no number of credits and asks the server for nothing but the session",
    !/\d[\d,]*\s*(credits?|points?)\b/i.test(landing.words) && mock.requests.every((item) => item.path === "/api/session"),
    mock.requests.map((item) => item.path).join(", "));
  await scan("landing");
  await shoot("public-landing-1280");

  // 2. Keyboard only, from the top of the landing page.
  const skip = await tabTo(() => true, 1);
  check("the first Tab stop is a visible 'Skip to content' link", skip.stops[0]?.text === "Skip to content" &&
    skip.stops[0].ring, JSON.stringify(skip.stops[0]));
  await key("Enter");
  check("Skip to content moves focus to the page's main content",
    await waitFor(`!!document.activeElement?.closest("main") || document.activeElement?.tagName === "MAIN"`));
  await evaluate("document.activeElement.blur(); window.scrollTo(0, 0)");
  const toRegister = await tabTo((stop) => stop.href === "/register" && /register/i.test(stop.text) &&
    stop.tag === "A", 40);
  check("every Tab stop on the way to Register shows a visible focus ring", toRegister.reached &&
    toRegister.stops.every((stop) => stop && stop.ring), JSON.stringify(toRegister.stops.filter((stop) => !stop?.ring)));
  await key("Enter");
  check("Enter on Register opens the registration page and puts focus on its heading",
    await waitFor(`location.pathname === "/register" && document.activeElement?.tagName === "H1"`));

  // 3. Registration typed by keyboard: a local mistake sends nothing; a clean submit sends four fields once.
  const typedForm = { username: "reader-c", display_name: "Reader C (synthetic)", password: PASSWORDS["reader-c"],
                      repeat: "synthetic-mistyped-pass", note: "SYNTHETIC note for the administrator" };
  for (const [name, words] of Object.entries(typedForm)) {
    const reached = await tabTo((stop) => stop.name === name, 15);
    if (!reached.reached) throw new Error(`Tab did not reach the ${name} field`);
    await type(words);
  }
  const submitStop = await tabTo((stop) => stop.tag === "BUTTON" && stop.text === "Register", 6);
  await key("Enter");
  await waitFor(`document.querySelector('[name="repeat"]')?.getAttribute("aria-invalid") === "true"`);
  check("a mistyped repeat is marked on its field, focus moves there, and nothing is sent",
    submitStop.reached && (await focused())?.name === "repeat" && posts("/registrations") === 0 &&
    (await text('[data-field-error="repeat"]')).includes("The two passwords differ"));
  await setValue('.public-register [name="repeat"]', PASSWORDS["reader-c"]);
  await click(".public-register button[type=submit]");
  await waitFor(`!!document.querySelector('[data-public="registered"]')`);
  const sent = mock.requests.filter((item) => item.path === "/api/public/registrations");
  check("one submit sends exactly username, display name, password and note, once",
    sent.length === 1 && Object.keys(sent[0].sent).sort().join(",") === "display_name,note,password,username" &&
    sent[0].sent.note === typedForm.note && !sent[0].raw.includes("synthetic-mistyped-pass"), JSON.stringify(sent[0]?.sent));
  const received = await evaluate(`document.querySelector('[data-public="registered"]').innerText`);
  check("MOCK: the received registration shows the server's record and what happens next, with no password",
    received.includes("reader-c") && received.includes("Reader C (synthetic)") && /waiting for approval/i.test(received) &&
    /allocat/i.test(received) && !received.includes(PASSWORDS["reader-c"]) &&
    !(await evaluate(`document.body.innerHTML.includes(${JSON.stringify(PASSWORDS["reader-c"])})`)));
  check("focus moves to the received registration's heading",
    (await evaluate(`document.activeElement?.tagName`)) === "H1");
  await scan("registered");
  await shoot("public-registered-1280");

  // 4. The same registration again (a resubmission): the server's duplicate, nothing new recorded.
  await open("/register");
  await waitFor(`!!document.querySelector(".public-register")`);
  await fill({ ...typedForm, repeat: PASSWORDS["reader-c"] });
  await click(".public-register button[type=submit]");
  await waitFor(`!!document.querySelector('[data-public="registered"]')`);
  check("MOCK: a resubmission is answered as already received; the page says nothing new was recorded",
    /already been received/i.test(await text('[data-public="registered"]')) &&
    /Nothing new was recorded/.test(await text('[data-public="registered"]')) && posts("/registrations") === 2);

  // 5. Refusals keep what was typed, except the password.
  await open("/register");
  await waitFor(`!!document.querySelector(".public-register")`);
  await fill({ username: "reader-a", display_name: "Someone (synthetic)", password: "synthetic-taken-pass",
               repeat: "synthetic-taken-pass", note: "SYNTHETIC kept note" });
  await click(".public-register button[type=submit]");
  await waitFor(`!!document.querySelector('[data-field-error="username"]')`);
  check("MOCK: a taken username is marked on its field; the password fields are cleared, the rest kept",
    (await text('[data-field-error="username"]')).includes(onboardingErrors.username_unavailable.detail) &&
    (await value('[name="password"]')) === "" && (await value('[name="repeat"]')) === "" &&
    (await value('[name="username"]')) === "reader-a" && (await value('[name="note"]')) === "SYNTHETIC kept note" &&
    (await text(".public-notice")).includes("Nothing was recorded") && (await focused())?.name === "username");
  await fill({ username: "reader-g", display_name: "SYNTHETIC refused name", password: PASSWORDS["reader-g"],
               repeat: PASSWORDS["reader-g"] });
  await click(".public-register button[type=submit]");
  await waitFor(`!!document.querySelector('[data-field-error="display_name"]')`);
  check("MOCK: a field the server refuses is marked with the server's own words, and focus moves there",
    (await text('[data-field-error="display_name"]')).includes("SYNTHETIC rule of this MOCK") &&
    (await focused())?.name === "display_name" && (await value('[name="password"]')) === "" &&
    (await value('[name="display_name"]')) === "SYNTHETIC refused name");
  await scan("register-refused");
  await shoot("public-register-refused-1280");

  // 6. A lost reply: both password fields are cleared and nothing is sent again by itself. Registering again needs the
  //    password typed again, and the server answers the same username and password as the duplicate it is.
  await open("/register");
  await waitFor(`!!document.querySelector(".public-register")`);
  mock.dropRegistrationReply = true;
  await fill({ username: "reader-e", display_name: "Reader E (synthetic)", password: PASSWORDS["reader-e"],
               repeat: PASSWORDS["reader-e"], note: "" });
  const beforeLost = posts("/registrations");
  await click(".public-register button[type=submit]");
  await waitFor(`!!document.querySelector('[data-public="unconfirmed"]')`);
  await sleep(1500);
  const unsure = { posts: posts("/registrations") - beforeLost, words: await text('[data-public="unconfirmed"]'),
    buttons: await evaluate(`[...document.querySelectorAll('[data-public="unconfirmed"] button')].map((b) => b.textContent.trim())`),
    passwords: [await value('[name="password"]'), await value('[name="repeat"]')],
    kept: [await value('[name="username"]'), await value('[name="display_name"]')],
    editable: await evaluate(`[...document.querySelectorAll(".public-register input")].every((input) => !input.readOnly)`),
    inPage: await evaluate(`document.body.innerHTML.includes(${JSON.stringify(PASSWORDS["reader-e"])})`) };
  check("a lost reply: one request only, both password fields cleared, the rest kept, a check by signing in offered",
    unsure.posts === 1 && JSON.stringify(unsure.passwords) === '["",""]' && !unsure.inPage &&
    JSON.stringify(unsure.kept) === '["reader-e","Reader E (synthetic)"]' && unsure.editable &&
    /type the password again/.test(unsure.words) && JSON.stringify(unsure.buttons) === '["Check by signing in"]',
    JSON.stringify(unsure));
  await shoot("public-register-unconfirmed-1280");
  await click(".public-register button[type=submit]");
  await waitFor(`!!document.querySelector('[data-field-error="password"]')`);
  check("registering again without typing the password sends nothing and asks for it",
    posts("/registrations") - beforeLost === 1 && (await focused())?.name === "password");
  await fill({ password: PASSWORDS["reader-e"], repeat: PASSWORDS["reader-e"] });
  await click(".public-register button[type=submit]");
  await waitFor(`!!document.querySelector('[data-public="registered"]')`);
  const again = mock.requests.filter((item) => item.path === "/api/public/registrations").slice(-2);
  check("MOCK: with the password typed again, the same registration is answered as the duplicate it is",
    posts("/registrations") - beforeLost === 2 && again[0].raw === again[1].raw &&
    /already been received/i.test(await text('[data-public="registered"]')));

  // 7. A lost reply, then a check by signing in: the pending status, and no session.
  await open("/register");
  await waitFor(`!!document.querySelector(".public-register")`);
  mock.dropRegistrationReply = true;
  await fill({ username: "reader-f", display_name: "Reader F (synthetic)", password: PASSWORDS["reader-f"],
               repeat: PASSWORDS["reader-f"] });
  await click(".public-register button[type=submit]");
  await waitFor(`!!document.querySelector('[data-public="unconfirmed"]')`);
  await clickText('[data-public="unconfirmed"] button', "Check by signing in");
  check("checking by signing in opens the sign-in form with the username filled and the password empty",
    await waitFor(`location.pathname === "/sign-in" && document.querySelector('.shell-form [name="username"]')?.value === "reader-f"`) &&
    (await value('.shell-form [name="password"]')) === "");
  await signInWith("reader-f", PASSWORDS["reader-f"]);
  await waitFor(`!!document.querySelector('[data-public="status"]')`);
  const status = await text('[data-public="status"]');
  const cookies = (await send("Network.getCookies", { urls: [base] })).cookies;
  check("MOCK: a pending registrant sees only their own registration, waiting for approval, and gets no session",
    status.includes("reader-f") && status.includes("Reader F (synthetic)") && /waiting for approval/i.test(status) &&
    !(await exists('.shell-form input[name="password"]')) && cookies.length === 0 &&
    (await evaluate("document.activeElement?.tagName")) === "H1");
  await scan("status-pending");
  await shoot("public-status-pending-1280");

  // 8. A rejected registration, a wrong password, a lost sign-in reply.
  mock.registrations.get("reader-c").status = "rejected";
  mock.registrations.get("reader-c").decided_at = "2026-10-14T10:00:00+00:00";
  await clickText('[data-public="status"] button', "Sign in as someone else");
  await signInWith("reader-c", PASSWORDS["reader-c"]);
  await waitFor(`/not approved/i.test(document.querySelector('[data-public="status"]')?.textContent ?? "")`);
  const declined = await text('[data-public="status"]');
  check("MOCK: a rejected registrant is told it was not approved and that the username cannot be registered again",
    declined.includes("reader-c") && /cannot be registered again/.test(declined) &&
    (await exists('[data-public="status"] a[href="/register"]')));
  await clickText('[data-public="status"] button', "Sign in as someone else");
  await signInWith("reader-c", "synthetic-wrong-pass");
  await waitFor(`!!document.querySelector(".shell-problem")`);
  check("MOCK: a wrong password is refused with the server's one message, and the password field is cleared",
    (await text(".shell-problem")).includes(userErrors.invalid_credentials.detail) &&
    (await value('.shell-form [name="password"]')) === "" && (await value('.shell-form [name="username"]')) === "reader-c");
  mock.dropLoginReply = true;
  const loginsBefore = posts("/api/session/login");
  await signInWith("reader-a", PASSWORDS["reader-a"]);
  await waitFor(`!!document.querySelector('[data-sign-in="unconfirmed"]')`);
  await sleep(1200);
  check("a lost sign-in reply: the password is not sent again and the field is cleared; a session check is offered",
    posts("/api/session/login") - loginsBefore === 1 && (await value('.shell-form [name="password"]')) === "" &&
    (await exists('[data-sign-in="unconfirmed"] button')));
  const sessionsBefore = gets("/api/session");
  await clickText('[data-sign-in="unconfirmed"] button', "Check whether you are signed in");
  await waitFor(`!document.querySelector('[data-sign-in="unconfirmed"]')`);
  check("MOCK: the explicit check reads the session once and, signed out, offers the form again",
    gets("/api/session") === sessionsBefore + 1 && posts("/api/session/login") - loginsBefore === 1 &&
    (await exists('.shell-form input[name="password"]')));
  await scan("sign-in");

  // 9. How credits work: the server's rules and synthetic quotes; no terms; a failed read.
  await open("/credits");
  await waitFor(`!!document.querySelector('[data-credit-terms="configured"]')`);
  const guide = await evaluate(`({ rules: [...document.querySelectorAll("[data-credit-rules] li")].map((li) => li.textContent),
    heads: [...document.querySelectorAll("[data-credit-examples] thead th")].map((th) => th.textContent),
    rows: [...document.querySelectorAll("[data-credit-examples] tbody tr")].map((tr) => [...tr.querySelectorAll("td")].map((td) => td.textContent)),
    caption: document.querySelector("[data-credit-examples] caption")?.textContent ?? "",
    words: document.querySelector("main").innerText })`);
  const expectedRows = terms.configured.examples.map((example) => example.quotes.map((quote) => String(quote.credits)));
  check("MOCK: /credits shows the server's rules in its own words and its synthetic quotes exactly",
    JSON.stringify(guide.rules) === JSON.stringify(terms.configured.rules) &&
    JSON.stringify(guide.heads.slice(1)) === JSON.stringify(terms.configured.efforts.map((option) => option.label)) &&
    JSON.stringify(guide.rows) === JSON.stringify(expectedRows) && /synthetic/i.test(guide.caption) &&
    guide.words.includes("15 minutes") && guide.words.includes(terms.configured.size_note) &&
    !(await exists("[data-credit-per-effort]")), JSON.stringify(guide.rows));
  await scan("credits");
  await shoot("public-credits-1280");
  mock.terms = "flat";
  await open("/credits");
  await waitFor(`!!document.querySelector("[data-credit-per-effort]")`);
  const flat = { line: await text("[data-credit-per-effort]"), words: await evaluate(`document.querySelector("main").innerText`),
    rows: await evaluate(`[...document.querySelectorAll("[data-credit-examples] tbody tr")].map((tr) =>
      [...tr.querySelectorAll("td")].map((td) => td.textContent))`) };
  const flatRates = terms.flat.efforts.map((option, index) => `${option.label} ${terms.flat.examples[0].quotes[index].credits}`);
  check("MOCK: under flat terms the page says, from the server's quotes, that the Effort decides and length does not",
    flat.line.includes(flatRates.join(", ")) && flat.words.includes(terms.flat.size_note) &&
    flat.rows.length === 3 && flat.rows.every((row) => JSON.stringify(row) === JSON.stringify(flat.rows[0])),
    JSON.stringify(flat));
  await scan("credits-flat");
  await shoot("public-credits-flat-1280");
  mock.terms = "none";
  await open("/credits");
  await waitFor(`!!document.querySelector('[data-credit-terms="no_credit_policy"]')`);
  const empty = await evaluate(`document.querySelector("main").innerText`);
  check("MOCK: with no credit terms, the rules and the server's reason, and no number of credits at all",
    empty.includes(terms.none.detail) && !(await exists("[data-credit-examples]")) &&
    !/\d[\d,]*\s*(credits?|points?)\b/i.test(empty) && !/\b\d+\b/.test(empty.replace(/50,000|2,000/g, "")));
  mock.terms = "fail";
  await open("/credits");
  await waitFor(`!!document.querySelector('[data-credit-terms="unread"]')`);
  check("a failed read says the terms could not be read, with no fallback numbers",
    /could not be read/.test(await text('[data-credit-terms="unread"]')) && !(await exists("[data-credit-examples]")));
  mock.terms = "configured";
  const termsBefore = gets("/api/public/credit-terms");
  await clickText('[data-credit-terms="unread"] button', "Read again");
  check("Read again reads once more, on request", await waitFor(`!!document.querySelector('[data-credit-terms="configured"]')`) &&
    gets("/api/public/credit-terms") === termsBefore + 1);

  // 10. Desktop, tablet and phone widths.
  const layouts = {};
  for (const [width, height, mobile] of [[1280, 900, false], [768, 1024, true], [375, 812, true]]) {
    await viewport(width, height, mobile);
    for (const path of ["/", "/register", "/sign-in", "/credits", "/sources/bookmarked"]) {
      await open(path);
      await waitFor(`!!document.querySelector("main h1")`);
      layouts[`${width} ${path}`] = await noSideways();
      if (width !== 1280) await shoot(`public-${path.replace(/\W+/g, "-").replace(/^-|-$/g, "") || "landing"}-${width}`);
    }
  }
  check("at 1280, 768 and 375 pixels no public page scrolls sideways", Object.values(layouts).every(Boolean),
    JSON.stringify(Object.entries(layouts).filter(([, fits]) => !fits)));
  await viewport(375, 812, true);
  const phoneTargets = await evaluate(`[...document.querySelectorAll("main button, main input, main a.button, .topbar a")]
    .filter((e) => e.offsetParent).map((e) => [e.textContent.trim().slice(0, 30) || e.name, Math.round(e.getBoundingClientRect().height)])
    .filter(([, height]) => height < 24)`);
  check("at phone width every control is at least 24 pixels tall", phoneTargets.length === 0, JSON.stringify(phoneTargets));
  await viewport(1280, 900, false);

  // 11. A bookmarked research page and /credits keep their address through sign-in; /register opens the Client's home.
  await open("/analyses/synthetic-bookmark");
  await waitFor(`!!document.querySelector(".shell-form")`);
  check("signed out, a research bookmark is the sign-in form at its own address",
    (await evaluate("location.pathname")) === "/analyses/synthetic-bookmark");
  await signInWith("reader-a", PASSWORDS["reader-a"]);
  check("MOCK: after signing in, the bookmarked page opens at the same address",
    await waitFor(`!!document.querySelector("main.page.client") && location.pathname === "/analyses/synthetic-bookmark"`, 15000));
  await click(".account-strip button");
  await waitFor(`!!document.querySelector(".shell-form")`);
  check("signing out there shows the sign-in form saying so", (await text(".shell-note")).includes("You are signed out"));
  await open("/credits");
  await waitFor(`!!document.querySelector('[data-credit-terms="configured"]')`);
  await clickText('[data-public="credits"] button', "Sign in to see your own credits");
  check("signed out, /credits offers sign-in in place, at its own address",
    await waitFor(`!!document.querySelector('[data-public="credits"] .shell-form')`) &&
    (await evaluate("location.pathname")) === "/credits");
  await signInWith("reader-a", PASSWORDS["reader-a"]);
  check("MOCK: signing in from /credits stays on /credits, in the Client",
    await waitFor(`!!document.querySelector('main.page.client[data-view="credits"]') && location.pathname === "/credits"`, 15000));
  check("MOCK: a signed-in user's /credits shows their own allowance above the server's terms, and no missing step",
    await waitFor(`document.querySelector('[data-entitlement="credits"]')?.textContent === "40 credits available" &&
      !!document.querySelector('[data-credit-terms="configured"]')`) && !(await exists("[data-first-use]")));
  await click(".account-strip button");
  await waitFor(`!!document.querySelector('[data-public="credits"]')`);
  await open("/register");
  await waitFor(`!!document.querySelector(".public-register")`);
  await clickText(".public-register-aside a, .public-footnote a", "Sign in");
  await waitFor(`location.pathname === "/sign-in"`);
  await signInWith("reader-a", PASSWORDS["reader-a"]);
  check("MOCK: signing in from the sign-in page opens the Client's home, the News",
    await waitFor(`!!document.querySelector('main.page.client[data-view="news"]') && location.pathname === "/"`, 15000));
  await click(".account-strip button");
  await waitFor(`!!document.querySelector('[data-public="landing"]')`);
  check("signing out at / shows the landing page, saying you are signed out",
    /signed out/i.test(await text('[data-public="reason"]')));

  // 11b. Approved, with nothing allocated yet: every missing step the server lists, in its words; and a signed-in user
  //      at /register or /sign-in is told they are signed in.
  mock.registrations.get("reader-e").status = "approved";
  await open("/sign-in");
  await signInWith("reader-e", PASSWORDS["reader-e"]);
  await waitFor(`!!document.querySelector('main.page.client[data-view="news"]')`, 15000);
  await open("/analyses");  // Your analyses, with the first-use steps, moved from / to /analyses.
  await waitFor(`!!document.querySelector("[data-first-use] [data-reason]")`, 15000);
  const firstUse = await evaluate(`({ reasons: [...document.querySelectorAll("[data-first-use] [data-reason]")].map((e) => e.dataset.reason),
    words: document.querySelector("[data-first-use]")?.innerText ?? "", credits: document.querySelector('[data-entitlement="credits"]')?.textContent,
    link: !!document.querySelector('[data-first-use] a[href="/credits"]'), empty: !!document.querySelector(".client-empty") })`);
  const approvedSteps = userNamed("reader-e").account.analysis.reasons;
  check("MOCK: an approved account with nothing allocated lists both missing steps, in order, in the server's words",
    JSON.stringify(firstUse.reasons) === '["no_daily_limit","no_credits_allocated"]' &&
    approvedSteps.every((step) => firstUse.words.includes(step.detail)) && /administrator/.test(firstUse.words) &&
    firstUse.credits === "0 credits available" && firstUse.link && firstUse.empty, JSON.stringify(firstUse));
  await scan("first-use");
  await shoot("client-first-use-1280");
  await open("/credits");
  check("MOCK: their /credits shows the same steps, their allowance and the server's terms",
    await waitFor(`!!document.querySelector('main.page.client[data-view="credits"] [data-first-use]') &&
      !!document.querySelector('[data-entitlement="credits"]') && !!document.querySelector('[data-credit-terms="configured"]')`));
  for (const path of ["/register", "/sign-in"]) {
    await open(path);
    await waitFor(`!!document.querySelector('[data-view-note="signed-in"]')`);
    const note = await text('[data-view-note="signed-in"]');
    check(`signed in, ${path} says so, names the account and offers the news and the analyses; nothing is sent`,
      note.includes("Reader E (synthetic)") && /sign out first/i.test(note) &&
      (await exists('[data-view-note="signed-in"] a[href="/news"]')) &&
      (await exists('[data-view-note="signed-in"] a[href="/analyses"]')) && !(await exists(".shell-form, .public-register")));
  }
  await viewport(375, 812, true);
  await open("/analyses");
  await waitFor(`!!document.querySelector("[data-first-use] [data-reason]")`);
  check("at phone width the first-use page does not scroll sideways", await noSideways());
  await viewport(1280, 900, false);
  await click(".account-strip button");
  await waitFor(`!!document.querySelector('[data-public="landing"]')`);

  // 12. Passwords, storage, addresses, requests and the bundle.
  const secrets = Object.values(PASSWORDS).concat(["synthetic-taken-pass", "synthetic-wrong-pass", "synthetic-mistyped-pass"]);
  const carriers = mock.requests.filter((item) => secrets.some((secret) => item.raw.includes(secret)));
  check("passwords went only into the registration and sign-in requests the person submitted",
    carriers.length > 0 && carriers.every((item) => item.method === "POST" &&
      (item.path === "/api/public/registrations" || item.path === "/api/session/login")),
    carriers.map((item) => item.path).join(", "));
  const stored = await evaluate(`JSON.stringify({ local: Object.entries(localStorage), session: Object.entries(sessionStorage) })`);
  check("nothing was kept in browser storage, and no address carried a password",
    stored === '{"local":[],"session":[]}' && addresses.every((url) => !secrets.some((secret) => url.includes(secret))),
    stored);
  check("no page showed the administrator's vocabulary, a tariff or a draft", vocabulary.length === 0, vocabulary.join(", "));
  check("every write carried this page's origin and its header (no refusal as forbidden)", mock.forbidden === 0);
  const outside = browserRequests.filter((url) => !url.startsWith(base) && !url.startsWith("data:"));
  check("the page requested nothing outside the local server", outside.length === 0, outside.join(", "));
  check("no page error", pageErrors.length === 0, pageErrors.join(" | "));
  check("no confirmation dialog", dialogs.length === 0, dialogs.join(" | "));
  const bundle = readdirSync(join(built, "assets")).filter((name) => name.endsWith(".js"))
    .map((name) => readFileSync(join(built, "assets", name), "utf8")).join("\n");
  check("the built Client bundle names no vendor or product, no draft tariff and no Admin module",
    !/claude|sonnet|opus|haiku|anthropic|openai|usage-points-draft|x-second-order-admin|\/api\/admin/i.test(bundle) &&
    !/Market context|Case library|Hypotheses|Treasury findings|Tracker attempts/.test(bundle));
  ws.close();
} catch (error) {
  check("the public entry browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  server.close();
  await sleep(400);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
