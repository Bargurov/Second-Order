// Browser check of the research checks on a recorded analysis (frontend/dist-client) in one headless Chrome, against a
// MOCK of GET /api/user/analyses/{id}/quality (docs/news-usage-contract.md) that runs inside this script from the
// canonical SYNTHETIC quality fixtures. Like the server, the MOCK refuses a request bound to another account (401
// account_changed). What the checks find is the MOCK's fixture: this proves what the Client shows and sends, never
// which mistakes the rubric catches.
//
// The journey: the result first, then the checks, then the review -> a flagged finding with its place (a link to the
// statement, reached by keyboard), detail and rule; what only a person can judge; every check run, named from the
// payload -> the limits said with or without findings; nothing flagged is not a confirmation -> an unreadable reply,
// and a server error, said in the checks alone: the result stays and the review typed stays -> a result with no
// analysis has no checks -> phone width -> the browser signed in to another account: the read is refused and the tab
// stops, keeping the review typed -> only reads were sent, each naming the account; no outside request, no page error.
//
//   cd frontend; npm run build; node tests/browser/client-checks-check.mjs
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
const users = { "reader-a": { session: fixture("user-contract-session-signed-in"), account: fixture("user-contract-account") },
                "reader-b": { session: fixture("client-session-reader-b"), account: fixture("client-account-reader-b") } };
const recorded = fixture("user-contract-analysis-recorded").analysis;
const declined = fixture("user-contract-analysis-declined").analysis;
const analyses = new Map([[recorded.analysis_id, recorded], [declined.analysis_id, declined]]);
const QUALITY = { flagged: fixture("news-contract-quality-flagged"), clean: fixture("news-contract-quality"),
                  none: fixture("news-contract-quality-none") };
const mock = { tokens: new Map(), requests: [], unbound: 0, mode: "flagged" };
const refuse = (code, status) => ({ status, body: { ...copy(errors[code]), contract: CONTRACT } });

function api(method, path, body, user) {
  if (path === "/api/session" && method === "GET") return { status: 200, body: user ? user.session : fixture("user-contract-session-signed-out") };
  if (path === "/api/session/login") {
    if (!users[body?.username] || body.password !== PASSWORD) return refuse("invalid_credentials", 401);
    const issued = randomBytes(16).toString("hex");
    mock.tokens.set(issued, body.username);
    return { status: 200, body: users[body.username].session, cookie: issued };
  }
  if (!user) return refuse("not_signed_in", 401);
  if (method === "GET" && path === "/api/user/account") return { status: 200, body: user.account };
  const parts = path.split("/").slice(3).map(decodeURIComponent);  // ["analyses", id, "quality"]
  const analysis = parts[0] === "analyses" ? analyses.get(parts[1]) : undefined;
  if (method !== "GET" || !analysis) return refuse("not_found", 404);
  if (parts.length === 2) return { status: 200, body: { contract: CONTRACT, analysis } };
  if (parts[2] === "quality") {
    if (analysis === declined) return { status: 200, body: { ...QUALITY.none, contract: CONTRACT } };
    if (mock.mode === "unreadable") return { status: 200, body: { contract: CONTRACT, quality: { rubric_version: "research-quality-0.3", flagged: "many" } } };
    if (mock.mode === "error") return refuse("internal_error", 500);
    return { status: 200, body: { ...copy(QUALITY[mock.mode]), contract: CONTRACT } };
  }
  return refuse("not_found", 404);
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
  if (userRoute && bound === undefined) mock.unbound += 1;
  const reply = userRoute && user && bound !== undefined && bound !== user.session.user.user_id
    ? refuse("account_changed", 401) : api(request.method, url.pathname, body, user);
  mock.requests.push({ method: request.method, path: url.pathname, status: reply.status, bound: bound ?? null });
  const headers = { "Content-Type": "application/json", Connection: "close" };
  if (reply.cookie) headers["Set-Cookie"] = `second_order_session=${reply.cookie}; HttpOnly; SameSite=Strict; Path=/`;
  response.writeHead(reply.status, headers);
  response.end(JSON.stringify(reply.body));
});

// ---------------------------------------------------------------- the browser

const root = mkdtempSync(join(tmpdir(), "second-order-checks-check-"));
const children = [];
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
  const dialogs = [];
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
      // Attributed, not ignored: a refused API request is logged by the browser (the scenario itself).
      if (!(/status of (4\d\d|500)|Failed to load resource/.test(entry.text) && String(entry.url ?? "").startsWith(`${base}/api/`))) {
        pageErrors.push(`${entry.text} ${entry.url ?? ""}`);
      }
    } else if (message.method === "Page.javascriptDialogOpening") {
      // Leaving a page with typed review notes asks first (the unsaved-text guard); this check leaves on purpose.
      dialogs.push(message.params.type);
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
  const setValue = (selector, value) => evaluate(`(() => { const e = document.querySelector(${JSON.stringify(selector)});
    if (!e) return false; const prototype = e instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value").set.call(e, ${JSON.stringify(value)});
    e.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
  const click = (selector) => evaluate(`(() => { const e = document.querySelector(${JSON.stringify(selector)});
    if (!e) return false; e.click(); return true; })()`);
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);
  const exists = (selector) => evaluate(`!!document.querySelector(${JSON.stringify(selector)})`);
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete' && !document.querySelector('.shell-status')");
  };
  const KEYS = { Tab: { key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 },
                 Enter: { key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, text: "\r" } };
  const press = async (name) => {
    const { text: typed, ...key } = KEYS[name];
    await send("Input.dispatchKeyEvent", { type: "keyDown", ...key, ...(typed ? { text: typed } : {}) });
    await send("Input.dispatchKeyEvent", { type: "keyUp", ...key });
  };
  const tabTo = async (selector, presses = 40) => {
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
  const checksState = () => evaluate(`document.querySelector(".client-checks")?.dataset.checks ?? null`);
  const R = `/analyses/${encodeURIComponent(recorded.analysis_id)}`;
  const A = users["reader-a"].session.user.user_id;
  const flagged = QUALITY.flagged.quality;
  // The Client's own words: no verdict. A banned word may appear only where the server's payload says it.
  const VERDICT = /\bscore|\bgrade|\bpass(?:ed|es|ing)?\b|pass mark|\bapprov|\bverified\b|\bcertif|\d+\s?%|\bconfidence\b/gi;
  const payloadWords = JSON.stringify(QUALITY).toLowerCase();

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Log.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  await open("/sign-in");
  await waitFor(`!!document.querySelector('.shell-form input[name="password"]')`);
  await setValue('.shell-form input[name="username"]', "reader-a");
  await setValue('.shell-form input[name="password"]', PASSWORD);
  await click(".shell-form button[type=submit]");
  check("Reader A signs in", await waitFor(`!!document.querySelector(".account-strip")`, 15000));

  // 1. The result first, then the checks, then the review.
  const beforeOpen = mock.requests.length;
  await open(R);
  await waitFor(`document.querySelector(".client-checks")?.dataset.checks === "1"`);
  const order = await evaluate(`(() => { const at = (selector) => document.querySelector(selector);
    const before = (a, b) => !!(at(a) && at(b) && (at(a).compareDocumentPosition(at(b)) & Node.DOCUMENT_POSITION_FOLLOWING));
    return ["client-outcome", "client-evidence", "client-interpretation", "client-unknowns", "client-marked"]
      .every((name) => before("." + name, ".client-checks")) && before(".client-checks", ".client-review"); })()`);
  check("the result and its evidence come first, the checks after them, the review last", order);
  const opening = mock.requests.slice(beforeOpen).filter((item) => item.path.startsWith("/api/user/"));
  check("opening the analysis sends only reads, the checks among them, each naming Reader A's account",
    opening.every((item) => item.method === "GET" && item.bound === A) &&
    opening.some((item) => item.path.endsWith("/quality")), JSON.stringify(opening.map((item) => `${item.method} ${item.path}`)));

  // 2. The flagged finding: its place, detail and rule; what only a person can judge; every check run.
  const finding = await evaluate(`(() => { const li = document.querySelector('.client-check-findings li[data-check="number_not_in_source"]');
    return li && { link: li.querySelector("a")?.getAttribute("href"), place: li.querySelector(".client-check-place").textContent,
      detail: li.querySelector(".client-check-detail").textContent, rule: li.querySelector(".client-sub").textContent }; })()`);
  check("a flagged finding shows its statement as a link, the server's detail and the check's rule",
    finding?.link === "#statement-1" && finding.place === "Statement 1 · Number not in source" &&
    finding.detail === flagged.findings[0].detail && finding.rule === `Rule: ${flagged.findings[0].rule}`, JSON.stringify(finding));
  check("what only a person can judge is listed as the server states it",
    JSON.stringify(await evaluate(`[...document.querySelectorAll(".client-check-review li")].map((li) => li.textContent)`)) ===
      JSON.stringify(flagged.human_review));
  check("the limits are said beside the findings: a flag can be wrong, a mistake can go unflagged",
    (await text("[data-checks-limits]")).startsWith("A flag can be wrong, and a mistake can go unflagged") &&
    (await text(".client-checks-statement")) === flagged.statement);
  const panel = (await evaluate(`document.querySelector(".client-checks").innerText`)).toLowerCase();
  const verdicts = [...panel.matchAll(VERDICT)].map((match) => match[0]).filter((word) => !payloadWords.includes(word));
  check("the checks give no score, pass mark, approval or confirmation of their own", verdicts.length === 0, verdicts.join(", "));
  await shoot("checks-flagged", ".client-checks");

  // 3. By keyboard: the list of every check opens, and the finding's link reaches its statement.
  const toSummary = await tabTo(".client-check-list summary");
  await press("Enter");
  const listed = await evaluate(`[...document.querySelectorAll(".client-check-list dt")].map((dt) => dt.textContent)`);
  check("by keyboard, the list of checks run opens: every check of the payload, named from it",
    toSummary && await evaluate(`document.querySelector(".client-check-list").open`) &&
    listed.length === Object.keys(flagged.checks).length && listed.includes("Negation differs") && listed.includes("Speaker differs"),
    JSON.stringify(listed));
  await evaluate(`document.querySelector("#checks-title").scrollIntoView()`);
  await evaluate(`document.querySelector("#checks-title").setAttribute("tabindex", "-1")`);
  await evaluate(`document.querySelector("#checks-title").focus()`);
  const toLink = await tabTo('.client-check-findings a[href="#statement-1"]', 6);
  await press("Enter");
  await waitFor(`location.hash === "#statement-1" && (() => { const box = document.getElementById("statement-1")
    ?.getBoundingClientRect(); return !!box && box.top >= 0 && box.top < innerHeight; })()`, 3000);
  const reached = await evaluate(`({ hash: location.hash, path: location.pathname,
    top: Math.round(document.getElementById("statement-1")?.getBoundingClientRect().top ?? -1), height: innerHeight })`);
  check("by keyboard, the finding's link reaches its statement in the result",
    toLink && reached.hash === "#statement-1" && reached.top >= 0 && reached.top < reached.height,
    JSON.stringify({ toLink, ...reached }));

  // 4. Nothing flagged: still not a confirmation.
  mock.mode = "clean";
  await click(".client-checks .client-basis .client-link-button");
  await waitFor(`document.querySelector(".client-checks")?.dataset.checks === "0"`);
  check("with nothing flagged, the page says it is not a confirmation, and keeps the limits and what a person must judge",
    (await text("[data-checks-nothing]")).includes("not a confirmation that the analysis is correct") &&
    await exists("[data-checks-limits]") && (await evaluate(`document.querySelectorAll(".client-check-review li").length`)) ===
      QUALITY.clean.quality.human_review.length && !(await exists(".client-check-findings")));

  // 5. An unreadable reply and a server error are said in the checks alone; the result and the typed review stay.
  const notes = "SYNTHETIC review notes typed while the checks are read again.";
  await setValue(".client-review textarea", notes);
  for (const mode of ["unreadable", "error"]) {
    mock.mode = mode;
    await click(".client-checks .client-basis .client-link-button, .client-checks .client-notice button");
    await waitFor(`document.querySelector(".client-checks")?.dataset.checks === "notice"`);
    check(`MOCK: ${mode === "error" ? "a server error" : "an unreadable reply"} is said in the checks alone; the result and the typed review stay`,
      (await text(".client-checks .client-note")).includes("not affected") && await exists(".client-outcome") &&
      await exists(".client-evidence") && (await evaluate(`document.querySelector(".client-review textarea").value`)) === notes);
  }
  mock.mode = "flagged";
  await click(".client-checks .client-notice button");
  check("reading again, on request, shows the checks once the reply is readable",
    await waitFor(`document.querySelector(".client-checks")?.dataset.checks === "1"`) &&
    (await evaluate(`document.querySelector(".client-review textarea").value`)) === notes);

  // 6. A result with no analysis has no checks.
  await open(`/analyses/${encodeURIComponent(declined.analysis_id)}`);
  await waitFor(`document.querySelector(".client-checks")?.dataset.checks === "none"`);
  check("a result holding no analysis says it has no checks, and shows no findings",
    (await text("[data-checks-none]")) === "There are no checks for this result: it holds no analysis to check." &&
    !(await exists(".client-check-findings, [data-checks-limits]")));

  // 7. Phone width.
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 1, mobile: true });
  await open(R);
  await waitFor(`document.querySelector(".client-checks")?.dataset.checks === "1"`);
  check("at phone width the result still opens first and nothing scrolls sideways",
    await evaluate(`document.documentElement.scrollWidth <= document.documentElement.clientWidth`) &&
    await evaluate(`document.querySelector(".client-outcome").getBoundingClientRect().top < document.querySelector(".client-checks").getBoundingClientRect().top`));
  await shoot("checks-phone", ".client-checks");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  // 8. The browser signed in to another account: the checks' read is refused, and the tab stops with the review kept.
  await open(R);
  await waitFor(`document.querySelector(".client-checks")?.dataset.checks === "1"`);
  await setValue(".client-review textarea", notes);
  const [token] = [...mock.tokens].filter(([, name]) => name === "reader-a").at(-1);
  mock.tokens.set(token, "reader-b");
  await click(".client-checks .client-basis .client-link-button");
  await waitFor(`!!document.querySelector('[data-account="stopped"]')`);
  check("MOCK: a checks read bound to Reader A while the browser is Reader B's is refused; the tab stops, keeping the review",
    mock.requests.at(-1).status === 401 && (await evaluate(`[...document.querySelectorAll(".client-ended-text")].map((t) => t.value).join("|")`)) === notes &&
    !(await evaluate("document.body.innerText")).includes("Reader B"));

  // 9. Boundaries.
  check("only reads were sent: the checks run nothing, quote nothing and save nothing",
    mock.requests.filter((item) => item.method === "POST" && item.path !== "/api/session/login").length === 0);
  check("every request to the user routes named the account", mock.unbound === 0, `${mock.unbound} unbound`);
  check("the page requested nothing outside the local server", outside.length === 0, outside.join(", "));
  check("no page error", pageErrors.length === 0, pageErrors.join(" | "));
  ws.close();
} catch (error) {
  check("the checks browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  server.close();
  await sleep(400);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
