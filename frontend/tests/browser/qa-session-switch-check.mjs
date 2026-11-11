// QA reproduction of finding QA-2 (draft and session isolation across tabs), against the REAL server with SYNTHETIC
// accounts and usage limits (tests/review_browser_server.py --accounts synthetic --usage-policy synthetic): nothing is
// mocked and nothing is sent to a provider.
//
// Two tabs of one browser share one session cookie. Tab 1 is signed in as reader-a and has a source form typed but not
// saved. In tab 2 the person signs out (ending reader-a's session) and signs in as reader-b. Tab 1 never receives a
// 401: its next request already carries reader-b's valid session. The check asserts what should hold:
//   - saving tab 1's form must not add a source to reader-b's account;
//   - tab 1 must not show reader-b's account under "Signed in as reader-a (synthetic)";
//   - tab 1's typed text is not lost.
// Then the same account signs out and in again in tab 2: tab 1's work must stay that account's and reach nobody else
// (so a fix cannot over-correct by refusing or discarding a same-account save).
// Last, the switch races a request: tab 1 (whose BroadcastChannel holds the other tab's announcements until the check
// releases them) sends its save while it still names reader-a, the request is held in flight (DevTools Fetch
// interception), tab 2 signs in as reader-b, and only then is the request let go. Only the server can catch this: it
// must refuse it (401 account_changed, docs/account-binding-contract.md), it must reach neither account, and tab 1 must
// keep the text for reader-a, not show reader-b under reader-a's name once the announcement arrives, and offer no way
// to end reader-b's session. Signing in again as reader-a in that tab gives the text back, unsaved; the same race
// followed by signing in as reader-b there discards it.
// On the entry release (37caa69) the first two cross-account assertions fail: the source is saved into reader-b's account, and tab 1 shows
// reader-b's credits under reader-a's name. It is part of the connected entry gate (npm run test:browser:entry-gate)
// and exits 1 until every assertion holds.
//
// Every account, password and source is SYNTHETIC; the server reads no real key and sends nothing.
//
//   cd frontend; npm run build; node tests/browser/qa-session-switch-check.mjs
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
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

// tests/account_fakes.py PASSWORDS: SYNTHETIC test strings.
const PASSWORDS = { "reader-a": "synthetic-reader-a", "reader-b": "synthetic-reader-b" };
const FORM = { headline: "Simulated harbour office reports a berth closure (QA tab check)",
  source_url: "https://example.org/synthetic/qa-tab-check", date: "2026-10-13", time: "10:00", offset: "+03:00",
  source_text: "October 13, 2026\n\nSimulated harbour office reports a berth closure\n\nThe Simulated Harbour " +
    "Office said one berth will close for two weeks of maintenance.\n\nSYNTHETIC TEST SOURCE for the QA tab check." };
const SAME = { ...FORM, headline: "Simulated harbour office schedules channel dredging (QA same-account check)",
  source_url: "https://example.org/synthetic/qa-same-account",
  source_text: "October 13, 2026\n\nSimulated harbour office schedules channel dredging\n\nThe Simulated Harbour " +
    "Office said channel dredging will start next month.\n\nSYNTHETIC TEST SOURCE for the QA same-account check." };
const UNHEARD = { ...FORM, headline: "Simulated harbour office reports a crane outage (QA unheard-tab check)",
  source_url: "https://example.org/synthetic/qa-unheard-tab",
  source_text: "October 13, 2026\n\nSimulated harbour office reports a crane outage\n\nThe Simulated Harbour " +
    "Office said a quay crane outage slowed unloading.\n\nSYNTHETIC TEST SOURCE for the QA unheard-tab check." };
// Installed in tab 1 before any of its scripts: every BroadcastChannel it opens still sends, but holds what it receives
// until window.__qaRelease() delivers it, as a slow or lost announcement would.
const HOLD_ANNOUNCEMENTS = `(() => {
  if (window.__qaHeld) return;  // Installed once per document.
  const Real = window.BroadcastChannel;
  window.__qaHeld = [];
  window.BroadcastChannel = class extends EventTarget {
    constructor(name) {
      super();
      this.name = name;
      this.onmessage = null;
      this.real = new Real(name);
      this.real.onmessage = (event) => window.__qaHeld.push({ channel: this, data: event.data });
    }
    postMessage(data) { this.real.postMessage(data); }
    close() { this.real.close(); }
  };
  window.__qaRelease = () => {
    for (const { channel, data } of window.__qaHeld.splice(0)) {
      const event = new MessageEvent("message", { data });
      channel.dispatchEvent(event);
      if (typeof channel.onmessage === "function") channel.onmessage(event);
    }
    return true;
  };
})();`;
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const root = mkdtempSync(join(tmpdir(), "second-order-qa-session-switch-"));
const served = join(root, "served");
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const note = (text) => console.log(`      ${text}`);

/** One page target over its own DevTools socket. */
async function tab(socketUrl, base) {
  const ws = new WebSocket(socketUrl);
  await new Promise((done) => ws.addEventListener("open", done, { once: true }));
  let counter = 0;
  const pending = new Map();
  const writes = [];
  const methods = new Map();
  const errors = [];
  const dialogs = [];
  const paused = [];
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else if (message.method === "Network.requestWillBeSent") {
      methods.set(message.params.requestId, message.params.request.method);
    } else if (message.method === "Network.responseReceived") {
      const { url, status } = message.params.response;
      const method = methods.get(message.params.requestId);
      if (method === "POST" && (url === `${base}/api/user/sources` || url === `${base}/api/session/logout`)) {
        writes.push({ url, status });
      }
    } else if (message.method === "Runtime.exceptionThrown") {
      errors.push(message.params.exceptionDetails.text);
    } else if (message.method === "Fetch.requestPaused") {
      paused.push(message.params);
    } else if (message.method === "Page.javascriptDialogOpening") {  // A leave-page warning: the person leaves.
      dialogs.push(message.params.message || message.params.type);
      void send("Page.handleJavaScriptDialog", { accept: true });
    }
  });
  const send = (method, params = {}) => new Promise((done, fail) => {
    const id = ++counter;
    pending.set(id, (message) => message.error ? fail(new Error(message.error.message)) : done(message.result));
    ws.send(JSON.stringify({ id, method, params }));
  });
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
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
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete' && !document.querySelector('.shell-status')");
  };
  /** In-app navigation: a full page load would lose what the tab holds in memory. */
  const go = (path) => evaluate(`(() => { history.pushState(null, "", ${JSON.stringify(path)});
    dispatchEvent(new PopStateEvent("popstate")); return true; })()`);
  const signIn = async (username) => {
    await open("/sign-in");
    await waitFor(`!!document.querySelector('.shell-form input[name="password"]')`);
    await setValue('.shell-form input[name="username"]', username);
    await setValue('.shell-form input[name="password"]', PASSWORDS[username]);
    await click(".shell-form button[type=submit]");
    // A reader lands on the News home (docs/news-stories-contract.md section 7), with the account strip.
    return waitFor(`document.querySelector("main.page.client")?.dataset.view === "news" &&
      !!document.querySelector(".account-strip")`, 15000);
  };
  const read = (path) => evaluate(`fetch(${JSON.stringify(path)}).then(async (reply) =>
    ({ status: reply.status, body: await reply.json() }))`);
  /** Sign in on the form this tab shows now, without loading another page (which would discard what it holds). */
  const signInHere = async (username) => {
    if (!await waitFor(`!!document.querySelector('.shell-form input[name="password"]')`)) return false;
    await setValue('.shell-form input[name="username"]', username);
    await setValue('.shell-form input[name="password"]', PASSWORDS[username]);
    await click(".shell-form button[type=submit]");
    return waitFor(`!document.querySelector(".shell-form") && !!document.querySelector(".account-strip")`, 15000);
  };
  return { ws, send, evaluate, waitFor, setValue, click, clickText, text, open, go, signIn, signInHere, read, writes,
           errors, dialogs, paused };
}

try {
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    "--accounts", "synthetic", "--usage-policy", "synthetic"], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  let started = false;
  for (let i = 0; i < 150 && !started; i++) {
    try { started = (await fetch(`${base}/api/session`)).ok; } catch { await sleep(200); }
  }
  if (!started) throw new Error("The server did not start.");

  const chrome = spawn(chromePath, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
    "--no-first-run", "--disable-gpu", "about:blank"], { stdio: "ignore" });
  children.push(chrome);
  let devtools;
  let firstUrl;
  for (let i = 0; i < 150 && !firstUrl; i++) {
    try {
      devtools = readFileSync(join(profile, "DevToolsActivePort"), "utf8").split("\n")[0].trim();
      firstUrl = (await (await fetch(`http://127.0.0.1:${devtools}/json/list`)).json())
        .find((target) => target.type === "page")?.webSocketDebuggerUrl;
    } catch { /* starting */ }
    if (!firstUrl) await sleep(200);
  }
  if (!firstUrl) throw new Error("Chrome's DevTools endpoint did not start.");
  const one = await tab(firstUrl, base);
  const opened = await (await fetch(`http://127.0.0.1:${devtools}/json/new?about:blank`, { method: "PUT" })).json();
  const two = await tab(opened.webSocketDebuggerUrl, base);

  // ---------------------------------------------------------------- tab 1: reader-a types a source
  check("tab 1 signs in as reader-a", await one.signIn("reader-a"));
  await one.go("/sources/new");
  await one.waitFor(`!!document.querySelector('.client-form [name="source_text"]')`);
  for (const [name, typed] of Object.entries(FORM)) await one.setValue(`.client-form [name="${name}"]`, typed);
  check("tab 1's form is typed and ready to save",
    await one.waitFor(`!document.querySelector(".client-save-source")?.disabled`));
  const sourcesOf = async (page) => (await page.read("/api/user/sources")).body.sources ?? [];
  /** An account's sources read outside the browser, with a session of its own (the browser's cookie is untouched). */
  const sourcesAs = async (username) => {
    const login = await fetch(`${base}/api/session/login`, { method: "POST", body: JSON.stringify({ username,
      password: PASSWORDS[username] }), headers: { Origin: base, "Content-Type": "application/json",
      "X-Second-Order-Session": "1" } });
    const cookie = (login.headers.get("set-cookie") ?? "").split(";")[0];
    const reply = await fetch(`${base}/api/user/sources`, { headers: { Cookie: cookie } });
    return reply.ok ? (await reply.json()).sources : [];
  };

  // ---------------------------------------------------------------- tab 2: sign out, then sign in as reader-b
  await two.open("/");
  check("tab 2 opens signed in as reader-a (one shared cookie)",
    await two.waitFor(`document.querySelector(".account-strip")?.textContent.includes("reader-a")`));
  await two.click(".account-strip button");
  await two.waitFor(`!!document.querySelector('[data-public="landing"], .shell-form')`);
  check("tab 2 signs in as reader-b", await two.signIn("reader-b"));
  const bBefore = (await sourcesOf(two)).length;

  // ---------------------------------------------------------------- tab 1 saves, still showing reader-a
  check("tab 1 still says it is signed in as reader-a (before any request)",
    (await one.text(".account-strip")).includes("reader-a"));
  await one.click(".client-save-source");
  await one.waitFor(`!document.querySelector(".client-save-source") || !document.querySelector(".client-save-source").disabled`, 10000);
  await sleep(600);
  note(`tab 1's POST /api/user/sources answered ${one.writes.map((write) => write.status).join(", ") || "nothing"}`);
  const bAfter = await sourcesOf(two);
  const landed = bAfter.find((source) => source.headline === FORM.headline);
  if (landed) note(`the source was recorded in reader-b's account (${landed.source_id})`);
  check("saving tab 1's form adds no source to reader-b's account", bAfter.length === bBefore && !landed,
    `reader-b had ${bBefore} source(s), now ${bAfter.length}`);

  const inPage = await one.evaluate(`[...document.querySelectorAll("textarea, input")].some((field) =>
    field.value && field.value.includes("berth will close"))`);
  const ownSources = await sourcesAs("reader-a");
  check("tab 1's typed text stays reader-a's (still in the tab, or saved in reader-a's own account)",
    inPage || ownSources.some((source) => source.headline === FORM.headline),
    landed ? "it is now a source of reader-b's account" : "the tab no longer holds it");

  // ---------------------------------------------------------------- what tab 1 shows next
  await one.go("/credits");
  await one.waitFor(`!!document.querySelector("main.page.client .client-entitlements dd") || !!document.querySelector('[role="alert"]')`, 10000);
  const session = (await one.read("/api/session")).body;
  const strip = await one.text(".account-strip");
  note(`tab 1's strip: "${strip.trim()}"; the server's session in tab 1: ${session.user?.username ?? session.state}`);
  check("tab 1 never shows another account's data under reader-a's name",
    !strip.includes("reader-a") || session.user?.username === "reader-a",
    "the strip names reader-a while every read now returns reader-b's account");

  // ---------------------------------------------------------------- the same account signs in again elsewhere
  // A fix must not over-correct: when tab 2 signs out and back in as the same account, tab 1's work stays that
  // account's (saved there, or kept in the tab), and nothing reaches anyone else.
  await two.click(".account-strip button");
  await two.waitFor(`!!document.querySelector('[data-public="landing"], .shell-form')`);
  check("tab 2 signs in as reader-a", await two.signIn("reader-a"));
  await one.open("/");
  check("tab 1 opens as reader-a", await one.waitFor(`document.querySelector(".account-strip")?.textContent.includes("reader-a")`));
  await one.go("/sources/new");
  await one.waitFor(`!!document.querySelector('.client-form [name="source_text"]')`);
  for (const [name, typed] of Object.entries(SAME)) await one.setValue(`.client-form [name="${name}"]`, typed);
  await one.waitFor(`!document.querySelector(".client-save-source")?.disabled`);
  await two.click(".account-strip button");
  await two.waitFor(`!!document.querySelector('[data-public="landing"], .shell-form')`);
  check("tab 2 signs out and in again as reader-a", await two.signIn("reader-a"));
  await one.click(".client-save-source");
  await one.waitFor(`!document.querySelector(".client-save-source") || !document.querySelector(".client-save-source").disabled`, 10000);
  await sleep(600);
  const keptInTab = await one.evaluate(`[...document.querySelectorAll("textarea, input")].some((field) =>
    field.value && field.value.includes("dredging"))`);
  const savedForA = (await sourcesAs("reader-a")).some((source) => source.headline === SAME.headline);
  check("after a same-account sign-in elsewhere, tab 1's text stays reader-a's (saved there, or kept in the tab)",
    savedForA || keptInTab);
  check("and nothing reaches reader-b's account",
    !(await sourcesAs("reader-b")).some((source) => source.headline === SAME.headline));
  // ---------------------------------------------------------------- the switch races tab 1's save
  const UNHEARD_TEXT = "crane outage slowed unloading";
  const holds = (page, words) => page.evaluate(`document.body.innerText.includes(${JSON.stringify(words)}) ||
    [...document.querySelectorAll("textarea, input")].some((field) => field.value.includes(${JSON.stringify(words)}))`);
  /** Tab 1 (reader-a, announcements held) types `form`; its save is held in flight while tab 2 signs in as `other`. */
  const race = async (form, other) => {
    await one.send("Fetch.disable");
    await one.open("/");
    const ready = await one.waitFor(`document.querySelector(".account-strip")?.textContent.includes("reader-a")`) &&
      await one.evaluate(`Array.isArray(window.__qaHeld)`);
    await one.go("/sources/new");
    await one.waitFor(`!!document.querySelector('.client-form [name="source_text"]')`);
    for (const [name, typed] of Object.entries(form)) await one.setValue(`.client-form [name="${name}"]`, typed);
    await one.waitFor(`!document.querySelector(".client-save-source")?.disabled`);
    await one.send("Fetch.enable", { patterns: [{ urlPattern: "*/api/user/sources", requestStage: "Request" }] });
    const from = one.writes.length;
    one.paused.length = 0;
    await one.click(".client-save-source");
    let held = false;
    for (let i = 0; i < 100 && !held; i++) { held = one.paused.length > 0; if (!held) await sleep(50); }
    const strip = await one.text(".account-strip");
    await two.open("/");  // Tab 2 as the browser is signed in now, then another account.
    await two.waitFor(`!!document.querySelector(".account-strip button")`);
    await two.click(".account-strip button");
    await two.waitFor(`!!document.querySelector('[data-public="landing"], .shell-form')`);
    const switched = await two.signIn(other) && (await two.read("/api/session")).body.user?.username === other;
    for (const request of one.paused.splice(0)) await one.send("Fetch.continueRequest", { requestId: request.requestId });
    await one.send("Fetch.disable");
    await sleep(800);
    const saves = one.writes.slice(from).filter((write) => write.url.endsWith("/api/user/sources"));
    return { ready, held, strip, switched, saves };
  };
  await one.send("Page.addScriptToEvaluateOnNewDocument", { source: HOLD_ANNOUNCEMENTS });
  const raced = await race(UNHEARD, "reader-b");
  check("tab 1 opens as reader-a with the other tab's announcements held", raced.ready);
  check("tab 1's save leaves while tab 1 still names reader-a, and is held in flight", raced.held &&
    raced.strip.includes("reader-a"), raced.strip);
  check("tab 2 signs in as reader-b while the save is held", raced.switched);
  note(`the held save, let go after the switch, answered ${raced.saves.map((write) => write.status).join(", ") || "nothing"}`);
  check("the server refuses the raced save as another account's (401)", raced.saves.length === 1 &&
    raced.saves[0].status === 401, JSON.stringify(raced.saves));
  check("the raced save reaches neither reader-b's account nor reader-a's",
    !(await sourcesAs("reader-b")).some((source) => source.headline === UNHEARD.headline) &&
    !(await sourcesAs("reader-a")).some((source) => source.headline === UNHEARD.headline));
  check("tab 1 still holds the raced text (in a field or shown to copy)", await holds(one, UNHEARD_TEXT));
  await one.evaluate("window.__qaRelease()");
  await sleep(600);
  const lateStrip = await one.text(".account-strip");
  note(`after the late announcement, tab 1's strip: "${lateStrip.trim()}"`);
  check("the late announcement does not make tab 1 show reader-b's account under reader-a's name",
    (await two.read("/api/session")).body.user?.username === "reader-b" &&
    !(lateStrip.includes("Signed in as reader-a") && await one.evaluate(`document.body.innerText.includes("reader-b")`)));
  const outFrom = one.writes.length;
  const offered = await one.clickText("button", "Sign out");
  await sleep(800);
  const logouts = one.writes.slice(outFrom).filter((write) => write.url.endsWith("/api/session/logout"));
  note(`tab 1 ${offered ? "offers a sign-out" : "offers no sign-out"}; logout ${logouts.map((write) => write.status)
    .join(", ") || "not sent"}`);
  check("tab 1 cannot end reader-b's session", (await two.read("/api/session")).body.user?.username === "reader-b" &&
    logouts.every((write) => write.status !== 200));
  // Same account: signing in again as reader-a in tab 1 gives the text back, unsaved.
  const again = await one.clickText("button", "Sign in again");
  check("tab 1 offers to sign in again, and signs in as reader-a in place", again && await one.signInHere("reader-a"));
  check("signed in again as reader-a, tab 1 gives the raced text back and saves nothing by itself",
    await one.waitFor(`[...document.querySelectorAll("textarea, input")].some((field) =>
      field.value.includes(${JSON.stringify(UNHEARD_TEXT)}))`, 10000) &&
    !(await sourcesAs("reader-a")).some((source) => source.headline === UNHEARD.headline));
  // Another account: the same race, then signing in as reader-b in tab 1 discards the text.
  const OTHER = { ...UNHEARD, headline: "Simulated harbour office reports a tug shortage (QA discard check)",
    source_text: UNHEARD.source_text.replace("a quay crane outage slowed unloading", "a tug shortage delayed berthing") };
  await one.evaluate(`[...document.querySelectorAll("textarea, input")].forEach((field) => {
    const prototype = field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value").set.call(field, "");
    field.dispatchEvent(new Event("input", { bubbles: true })); })`);  // The given-back text is set aside.
  const second = await race(OTHER, "reader-b");
  check("in a second race, tab 2 signs in as reader-b while tab 1's save is held", second.ready && second.held &&
    second.switched);
  check("the second raced save is refused too (401)", second.saves.length === 1 && second.saves[0].status === 401,
    JSON.stringify(second.saves));
  check("tab 1 holds the second text for reader-a", await holds(one, "tug shortage delayed berthing"));
  await one.evaluate("window.__qaRelease()");
  await sleep(600);
  if (!await one.clickText("button", "Sign in again")) {  // A warned tab shows how to continue first.
    await one.clickText("button, a", "See how to continue");
    await one.waitFor(`[...document.querySelectorAll("button")].some((item) => item.textContent.includes("Sign in again"))`);
  }
  const otherAgain = await one.clickText("button", "Sign in again") || await one.evaluate(
    `!!document.querySelector('.shell-form input[name="password"]')`);
  check("signing in as reader-b in tab 1 discards reader-a's text: it is never shown to reader-b",
    otherAgain && await one.signInHere("reader-b") && !(await holds(one, "tug shortage delayed berthing")) &&
    !(await sourcesAs("reader-b")).some((source) => source.headline === OTHER.headline));
  if (one.dialogs.length) note(`tab 1's leave-page warnings answered: ${one.dialogs.length}`);
  check("no page error in either tab", one.errors.length === 0 && two.errors.length === 0,
    [...one.errors, ...two.errors].join(" | "));
  one.ws.close();
  two.ws.close();
} catch (error) {
  console.error(error);
  results.push(false);
} finally {
  for (const child of children) child.kill();
  await sleep(500);
  try { rmSync(root, { recursive: true, force: true }); } catch { /* Windows may hold the profile briefly */ }
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
