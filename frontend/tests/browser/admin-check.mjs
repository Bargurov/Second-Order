// Browser acceptance check for accounts and the Admin screens, in one headless Chrome against
// tests/review_browser_server.py --accounts synthetic --simulated-provider: SYNTHETIC accounts (one administrator, two
// users), a SYNTHETIC credit policy and an in-process fake of the Claude API. No real key, model or network is used.
//
// The journey: a signed-out visitor gets the Client build's landing page and sign-in form, and neither their pages nor
// their scripts carry an Admin module, model, provider or price -> an admin signs in and the server hands over the
// Admin build: the operator pages under an administrator bar -> the admin grants reader-b credits and sets a daily limit on the Users
// screen -> with no usage limits set, reader-b's new source is refused and nothing is saved; the Usage & limits screen
// says so, its fields start empty, and the admin publishes SYNTHETIC limits once -> reader-b, through the real user API,
// adds a source, prepares, quotes and runs one analysis (recorded, charged once) and one whose send times out (held for
// review), and the Usage & limits screen counts its two new sources and prepared analyses -> the Actions screen shows each run's account, model,
// Effort, measured timing, usage, planning estimate and usage-derived cost, with the timed-out run's usage "Not
// reported" and cost "Unknown" -> the admin returns the held credits once on the Credits screen; the ledger reconciles
// -> a new policy version offering only Low supersedes reader-b's earlier quote -> two visitors register through the
// public route; Users points both out as waiting, shows them no balance or limit, and links to Registrations, which
// approves one and rejects the other, once each, naming the deciding administrator; the approved account signs in
// with nothing allocated, the rejected one sees only its own status, and Users offers it no action -> a policy preview
// shows the synthetic examples' quotes and records nothing -> the selected pilot preset fills a draft (flat 10 to 30
// points, the active planning limit kept), previews flat quotes and is published only by the explicit action; Users
// and Registrations point out reader-c as approved with nothing allocated, and Registrations' link opens its panel,
// where the initial allocation preset fills the two forms, submitted one at a time -> a user session in the browser gets
// the Client build at /admin and 403 from every admin route -> phone width has no sideways scroll -> nothing outside
// the local server is requested.
//
//   cd frontend; npm run build; npm run test:browser:admin
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
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

const USAGE_LIMITS = {  // SYNTHETIC values for this check only; a real server's limits are the administrator's choice.
  searches_per_day: "50", imports_per_day: "10", sources_per_day: "60", preparations_per_day: "60", max_sources: "500",
  max_source_bytes: "60000000", requests_per_minute: "600", concurrent_requests: "16",
  publication_fetches_per_day: "20", refreshes_per_day: "20", refresh_cooldown_seconds: "0",
};
const PASSWORDS = { admin: "synthetic-admin-pass", "reader-a": "synthetic-reader-a", "reader-b": "synthetic-reader-b" };
const SOURCE = "October 13, 2026\n\nSimulated statistics office publishes its quarterly survey\n\nThe Simulated " +
  "Statistics Office reported that output in the surveyed sector rose 1.2 percent in the third quarter.\n\nThe " +
  "office said it expects to revise the estimate when late responses arrive.\n\nSYNTHETIC TEST SOURCE.";
const CLIENT_FORBIDDEN = /claude|sonnet|anthropic|usd_per_mtok|x-second-order-research|x-second-order-admin|\/api\/admin|Hypotheses|Market context/i;
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const root = mkdtempSync(join(tmpdir(), "second-order-admin-check-"));
const served = join(root, "served");
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};

try {
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    "--accounts", "synthetic", "--simulated-provider"], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  let started = false;
  for (let i = 0; i < 150 && !started; i++) {
    try { started = (await fetch(`${base}/api/session`)).ok; } catch { await sleep(200); }
  }
  if (!started) throw new Error("The server did not start.");

  // ---------------------------------------------------------------- the user API, as a synthetic user would call it
  const sessionFor = async (username) => {
    const reply = await fetch(`${base}/api/session/login`, { method: "POST", body: JSON.stringify({
      username, password: PASSWORDS[username] }), headers: { Origin: base, "Content-Type": "application/json",
      "X-Second-Order-Session": "1" } });
    const cookie = (reply.headers.get("set-cookie") ?? "").split(";")[0];
    const account = (await reply.clone().json()).user.user_id;  // Named on every request (account binding).
    const call = async (method, path, body) => {
      const response = await fetch(`${base}${path}`, { method, body: body === undefined ? undefined : JSON.stringify(body),
        headers: { Cookie: cookie, "X-Second-Order-Account": account, ...(method === "POST" ? { Origin: base,
          "Content-Type": "application/json", "X-Second-Order-User": "1" } : {}) } });
      return { status: response.status, body: await response.json().catch(() => null) };
    };
    return { ok: reply.ok, cookie, get: (path) => call("GET", path), post: (path, body) => call("POST", path, body) };
  };
  const runAnalysis = async (user, headline, effort) => {
    const source = await user.post("/api/user/sources", { headline, source_url: "https://example.org/synthetic",
      published_at: "2026-10-13T10:00:00+03:00", source_text: SOURCE });
    const prepared = await user.post("/api/user/analyses", { source_id: source.body.source.source_id, effort });
    const id = prepared.body.analysis.analysis_id;
    const quote = (await user.post(`/api/user/analyses/${encodeURIComponent(id)}/quotes`, {})).body.quote;
    const run = await user.post(`/api/user/analyses/${encodeURIComponent(id)}/runs`, {
      quote_id: quote.quote_id, effort: quote.effort, credits: quote.credits, approve: true });
    return { id, quote, run };
  };

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
    const prototype = element instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value").set.call(element, ${JSON.stringify(value)});
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`);
  const click = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.click()`);
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);
  const clickText = (selector, words) => evaluate(`[...document.querySelectorAll(${JSON.stringify(selector)})]
    .find((element) => element.textContent.includes(${JSON.stringify(words)}))?.click() ?? false`);

  const requests = [];
  const errors = [];
  listeners.push((message) => {
    if (message.method === "Network.requestWillBeSent") {
      requests.push({ url: message.params.request.url, method: message.params.request.method });
    } else if (message.method === "Runtime.exceptionThrown") {
      errors.push(message.params.exceptionDetails.text);
    }
  });
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete'");
  };
  const signIn = async (username) => {
    await waitFor(`!!document.querySelector(".shell-form")`);
    await setValue('.shell-form input[name="username"]', username);
    await setValue('.shell-form input[name="password"]', PASSWORDS[username]);
    await click(".shell-form button[type=submit]");
  };

  // ---------------------------------------------------------------- signed out: the Client build only
  await open("/");
  check("a signed-out visitor at / gets the landing page, with registration and sign-in links", await waitFor(
    `!!document.querySelector('a[href="/register"]') && !!document.querySelector('a[href="/sign-in"]')`));
  await open("/sign-in");
  check("a signed-out visitor gets the sign-in form", await waitFor(`!!document.querySelector(".shell-form")`));
  const page = await evaluate("document.documentElement.outerHTML");
  const scripts = await evaluate(`[...document.querySelectorAll("script[src], link[rel=stylesheet]")]
    .map((element) => element.src || element.href)`);
  const bodies = await Promise.all(scripts.map(async (url) => (await fetch(url)).text()));
  check("the signed-out page loads only the Client build", scripts.length > 0 &&
    scripts.every((url) => /\/assets\/client-/.test(url)), scripts.join(", "));
  check("the Client build's page and scripts carry no Admin module, model, provider or price",
    !CLIENT_FORBIDDEN.test(page) && bodies.every((body) => !CLIENT_FORBIDDEN.test(body)));
  const adminAssets = readdirSync(join(repo, "frontend/dist/assets")).filter((name) => name.endsWith(".js"));
  const probed = await Promise.all(adminAssets.slice(0, 3).map(async (name) => (await fetch(`${base}/assets/${name}`)).text()));
  check("an Admin build file is not served to a signed-out visitor",
    probed.every((body) => !CLIENT_FORBIDDEN.test(body) && body.includes("<!doctype html")));
  check("admin routes refuse a signed-out caller", (await fetch(`${base}/api/admin/users`)).status === 401);

  // ---------------------------------------------------------------- an admin signs in: the Admin build
  await signIn("admin");
  check("an admin is handed the Admin build: the operator pages under an administrator bar",
    await waitFor(`!!document.querySelector(".admin-bar") && document.body.textContent.includes("Tracker")`, 15000));
  await open("/admin");
  check("the Users screen lists the synthetic accounts", await waitFor(
    `["admin", "reader-a", "reader-b"].every((name) => !!document.querySelector('tr[data-user="' + name + '"]'))`));
  check("reader-b starts without credits or a daily limit", (await text('tr[data-user="reader-b"]')).includes("No limit set") &&
    (await text('tr[data-user="reader-b"] [data-field="available"]')) === "0");
  await click('tr[data-user="reader-b"] .admin-link');
  await waitFor(`!!document.querySelector('form[aria-label="Credits for reader-b"]')`);
  await setValue('form[aria-label="Credits for reader-b"] input[name="credits"]', "20");
  await setValue('form[aria-label="Credits for reader-b"] input[name="reason"]', "SYNTHETIC grant in the admin check");
  await click('form[aria-label="Credits for reader-b"] button[type=submit]');
  await waitFor(`document.querySelector('tr[data-user="reader-b"] [data-field="available"]')?.textContent === "20"`);
  await setValue('form[aria-label="Daily limit for reader-b"] input[name="limit"]', "2");
  await setValue('form[aria-label="Daily limit for reader-b"] input[name="reason"]', "SYNTHETIC limit");
  await click('form[aria-label="Daily limit for reader-b"] button[type=submit]');
  check("the admin grants reader-b 20 credits and a daily limit of 2", await waitFor(
    `document.querySelector('tr[data-user="reader-b"] [data-field="limit"]')?.textContent === "2" &&
     document.querySelector('tr[data-user="reader-b"] [data-field="available"]')?.textContent === "20"`));

  // ---------------------------------------------------------------- usage limits: none set, then published once
  const readerB = await sessionFor("reader-b");
  const unlimited = await readerB.post("/api/user/sources", { headline: "Simulated source before any usage limit",
    source_url: "https://example.org/synthetic", published_at: "2026-10-13T10:00:00+03:00", source_text: SOURCE });
  check("without usage limits a user's new source is refused and nothing is saved", unlimited.status === 409 &&
    unlimited.body?.code === "no_usage_policy" && (await readerB.get("/api/user/sources")).body.sources.length === 0,
    JSON.stringify(unlimited));
  await open("/admin/usage");
  check("the Usage & limits screen says no usage limits are set and every field starts empty", await waitFor(
    `document.querySelector("[data-usage-policy]")?.dataset.usagePolicy === "none" &&
     [...document.querySelectorAll('form[aria-label="New usage limits"] input')].length === 12 &&
     [...document.querySelectorAll('form[aria-label="New usage limits"] input')].every((input) => input.value === "")`));
  for (const [name, value] of Object.entries(USAGE_LIMITS)) {
    await setValue(`form[aria-label="New usage limits"] input[name="${name}"]`, value);
  }
  await setValue('form[aria-label="New usage limits"] input[name="reason"]', "SYNTHETIC usage limits for the admin check");
  await click('form[aria-label="New usage limits"] button[type=submit]');
  check("the admin publishes the usage limits once", await waitFor(
    `document.querySelector("[data-usage-policy]")?.dataset.usagePolicy === "usage-policy-1" &&
     document.querySelector('[data-limit="sources_per_day"]')?.textContent === "60"`) &&
    (await evaluate(`fetch("/api/admin/usage-policy").then((reply) => reply.json())
      .then((view) => view.versions.length)`)) === 1);

  // ---------------------------------------------------------------- reader-b runs two analyses through the API
  const account = (await readerB.get("/api/user/account")).body;
  check("reader-b's account shows the granted credits and limit", account.credits.available === 20 &&
    account.daily.limit === 2 && account.analysis.available === true);
  const ok = await runAnalysis(readerB, "Simulated survey for the admin check", "high");
  check("reader-b's approved run is recorded and charged its quote once", ok.run.status === 201 &&
    ok.run.body.analysis.state === "recorded" && ok.run.body.analysis.charge.credits_charged === ok.quote.credits);
  const timedOut = await runAnalysis(readerB, "Simulated provider timeout for the admin check", "low");
  check("a send that times out is held for review, not refunded", timedOut.run.status === 201 &&
    timedOut.run.body.analysis.state === "failed" && timedOut.run.body.analysis.charge.state === "under_review" &&
    timedOut.run.body.account.credits.held === timedOut.quote.credits);
  await open("/admin/usage");
  check("the Usage & limits screen counts reader-b's two new sources and two prepared analyses today", await waitFor(
    `document.querySelector('tr[data-usage-user="reader-b"] [data-operation="source"]')?.textContent === "2 of 60" &&
     document.querySelector('tr[data-usage-user="reader-b"] [data-operation="preparation"]')?.textContent === "2 of 60" &&
     document.querySelector('tr[data-usage-user="reader-a"] [data-operation="source"]')?.textContent === "0 of 60"`),
    await text('[data-usage="accounts"]'));
  const providerCalls = readdirSync(join(served, "simulated-provider")).filter((name) => name.startsWith("request-"));
  const savedBytes = readFileSync(join(served, "research-analyses", "requests", ok.id, "request.json"));
  check("the fake provider received exactly the two approved sends, the first byte for byte the saved request",
    providerCalls.length === 2 && readFileSync(join(served, "simulated-provider", "request-1.json")).equals(savedBytes));

  // ---------------------------------------------------------------- the Actions screen
  await open("/admin/actions");
  await waitFor(`document.querySelectorAll("tr[data-request]").length >= 2`);
  const row = (id) => `tr[data-request="${id}"]`;
  check("the Actions screen names the account, model and Effort of each run",
    (await text(row(ok.id))).includes("reader-b") && (await text(row(ok.id))).includes("claude-sonnet-5-5") &&
    (await text(row(ok.id))).includes("high") && (await text(row(timedOut.id))).includes("low"));
  check("a recorded run shows its measured time, reported usage, estimate and a usage-derived cost marked unverified",
    (await text(`${row(ok.id)} [data-field="usage"]`)) === "3,000 in · 900 out" &&
    (await text(`${row(ok.id)} [data-field="cost"]`)).startsWith("$0.0150") &&
    (await text(`${row(ok.id)} [data-field="cost"]`)).includes("not verified billing") &&
    (await text(`${row(ok.id)} [data-field="estimate"]`)).startsWith("$") &&
    !(await text(`${row(ok.id)} [data-field="elapsed"]`)).includes("Not recorded"));
  check("the timed-out run's usage is not reported and its cost unknown, never zero",
    (await text(`${row(timedOut.id)} [data-field="usage"]`)) === "Not reported" &&
    (await text(`${row(timedOut.id)} [data-field="cost"]`)) === "Unknown");

  // ---------------------------------------------------------------- the operator page of a user's event
  const userCapture = ok.run.body.analysis.source.source_id;
  await open(`/events/capture/${userCapture}/research`);
  check("the operator research page lists a user's analysis read-only, with no send or review controls",
    await waitFor(`!!document.querySelector('#research-account-requests [data-request="${ok.id}"]')`) &&
    !(await evaluate(`!!document.querySelector("#research-send, #research-review, .research-send")`)));

  // ---------------------------------------------------------------- the Credits screen: resolve the hold once
  await open("/admin/credits");
  check("the held attempt is listed as needing review", await waitFor(
    `document.querySelector("li[data-attempt]")?.dataset.state === "needs_review"`));
  await setValue("li[data-attempt] input[name=reason]", "SYNTHETIC: no charge appears for this attempt");
  await click("li[data-attempt] button[type=submit]");
  check("returning the credits clears the hold and adds one ledger entry", await waitFor(
    `!document.querySelector("li[data-attempt]") && document.querySelectorAll('tr[data-kind="release"]').length === 1`));
  check("every user's ledger reconciles", await waitFor(`[...document.querySelectorAll("li[data-user-total]")]
    .every((item) => item.textContent.includes("reconciles") && !item.textContent.includes("does not"))`));
  const after = (await readerB.get("/api/user/account")).body;
  check("reader-b's held credits are returned exactly once", after.credits.held === 0 &&
    after.credits.available === 20 - ok.quote.credits);

  // ---------------------------------------------------------------- a new policy version supersedes quotes
  const stale = await readerB.post("/api/user/analyses", { source_id: ok.run.body.analysis.source.source_id,
    effort: "medium" });
  const staleQuote = (await readerB.post(`/api/user/analyses/${encodeURIComponent(stale.body.analysis.analysis_id)}/quotes`,
    {})).body.quote;
  await open("/admin/policy");
  await waitFor(`!!document.querySelector('form[aria-label="New policy version"]')`);
  await click('form[aria-label="New policy version"] input[name="effort-low"]');
  for (const [name, value] of [["base", "1"], ["per_1k_input_tokens", "1"], ["per_1k_output_tokens", "0"],
    ["max_request_usd", "2"], ["quote_valid_seconds", "600"], ["reason", "SYNTHETIC: offer Low only"]]) {
    await setValue(`form[aria-label="New policy version"] input[name="${name}"]`, value);
  }
  await click('form[aria-label="New policy version"] button[type=submit]');
  check("the admin publishes a policy version offering only Low", await waitFor(
    `document.querySelector("[data-policy]")?.dataset.policy === "credit-policy-2"`));
  const superseded = await readerB.post(`/api/user/analyses/${encodeURIComponent(stale.body.analysis.analysis_id)}/runs`,
    { quote_id: staleQuote.quote_id, effort: staleQuote.effort, credits: staleQuote.credits, approve: true });
  check("reader-b's earlier quote is superseded and nothing is sent", superseded.status === 409 &&
    superseded.body.code === "quote_superseded" &&
    readdirSync(join(served, "simulated-provider")).filter((name) => name.startsWith("request-")).length === 2);
  const efforts = (await readerB.get("/api/user/account")).body.efforts.map((option) => option.effort);
  check("reader-b is offered only Low now", JSON.stringify(efforts) === '["low"]');

  // ---------------------------------------------------------------- registrations: one decision each, nothing granted
  const publicWrite = { Origin: base, "Content-Type": "application/json", "X-Second-Order-Session": "1" };
  const register = (username) => fetch(`${base}/api/public/registrations`, { method: "POST", headers: publicWrite,
    body: JSON.stringify({ username, display_name: `${username} (synthetic)`, password: `synthetic-${username}-pass`,
                           note: "SYNTHETIC registration in the admin check" }) });
  const registered = await Promise.all(["reader-c", "reader-d"].map(register));
  check("two visitors register through the public route and wait", registered.every((reply) => reply.status === 201));
  await open("/admin");
  check("Users points out both waiting registrations by name", await waitFor(  // They registered at the same moment.
    `[/^2 registrations are waiting for a decision: /, /reader-c \\(synthetic\\)/, /reader-d \\(synthetic\\)/].every(
       (pattern) => pattern.test(document.querySelector('[data-attention="waiting"]')?.textContent ?? ""))`),
    await text('[data-attention="waiting"]'));
  check("a waiting registration shows no balance or limit, which the store cannot record before approval",
    await evaluate(`!!document.querySelector('tr[data-user="reader-c"] [data-unapproved]') &&
      !document.querySelector('tr[data-user="reader-c"] [data-field]') &&
      document.querySelector('tr[data-user="reader-c"] .admin-daily')?.textContent === "—"`));
  await clickText('[data-attention="waiting"] a', "Decide under Registrations");
  check("the Registrations screen lists both as waiting, with their notes", await waitFor(
    `location.pathname === "/admin/registrations" && `+
    `!!document.querySelector('form[aria-label="Decision on reader-c"]') &&
     !!document.querySelector('form[aria-label="Decision on reader-d"]') &&
     document.body.textContent.includes("SYNTHETIC registration in the admin check")`));
  await setValue('form[aria-label="Decision on reader-c"] input[name="reason"]', "SYNTHETIC approval");
  await click('form[aria-label="Decision on reader-c"] button[type=submit]');
  await waitFor(`!document.querySelector('form[aria-label="Decision on reader-c"]')`);
  await setValue('form[aria-label="Decision on reader-d"] input[name="reason"]', "SYNTHETIC rejection");
  await clickText('form[aria-label="Decision on reader-d"] button', "Reject");
  check("the admin approves one and rejects the other; both show as decided", await waitFor(
    `!document.querySelector('[data-registration] form') && document.body.textContent.includes("Approved · active") &&
     document.body.textContent.includes("Rejected")`));
  check("each decision names the administrator who made it, not an account ID", await waitFor(
    `["reader-c", "reader-d"].every((name) => document.querySelector('[data-registration="' + name + '"] [data-decided-by]')
       ?.textContent === "admin (synthetic)")`) &&
    !/\bu-[0-9a-f]{16}\b/.test(await text('[data-registration="reader-c"]') + await text('[data-registration="reader-d"]')));
  check("the approval says nothing is allocated yet and links to the allocation; the rejection does neither",
    await waitFor(`!!document.querySelector('[data-registration="reader-c"] [data-allocation="none"]')`) &&
    (await evaluate(`document.querySelector('[data-registration="reader-c"] a')?.getAttribute("href")`)) ===
      "/admin?manage=reader-c" &&
    !(await evaluate(`!!document.querySelector('[data-registration="reader-d"] a, [data-registration="reader-d"] [data-allocation]')`)));
  const again = await evaluate(`Promise.all([fetch("/api/session").then((reply) => reply.json()),
    fetch("/api/admin/registrations").then((reply) => reply.json())]).then(([session, body]) => fetch(
      "/api/admin/registrations/" + body.registrations.find((row) => row.username === "reader-c").user_id + "/decision",
      { method: "POST", headers: { "Content-Type": "application/json", "X-Second-Order-Admin": "1",
        "X-Second-Order-Account": session.user.user_id },
        body: JSON.stringify({ decision: "reject", reason: "SYNTHETIC second" }) }))
    .then(async (reply) => [reply.status, (await reply.json()).code])`);
  check("a second decision is refused with the one that applied", JSON.stringify(again) === '[409,"already_decided"]',
        JSON.stringify(again));
  const signInAs = (username) => fetch(`${base}/api/session/login`, { method: "POST", headers: publicWrite,
    body: JSON.stringify({ username, password: `synthetic-${username}-pass` }) });
  const approved = await signInAs("reader-c");
  const approvedCookie = (approved.headers.get("set-cookie") ?? "").split(";")[0];
  const approvedId = (await approved.clone().json()).user.user_id;
  const approvedAccount = await (await fetch(`${base}/api/user/account`, { headers: { Cookie: approvedCookie } })).json();
  const rejected = await (await signInAs("reader-d")).json();
  check("the approved account signs in with nothing allocated; the rejected one sees only its own status",
    approved.status === 200 && JSON.stringify(approvedAccount.analysis.reasons.map((row) => row.reason)) ===
      '["no_daily_limit","no_credits_allocated"]' && approvedAccount.credits.available === 0 &&
    rejected.code === "registration_rejected" && rejected.registration.status === "rejected" &&
    !JSON.stringify(rejected).includes("SYNTHETIC rejection"), JSON.stringify(rejected));
  await open("/admin");
  await waitFor(`!!document.querySelector('tr[data-user="reader-d"] .admin-link')`);
  await click('tr[data-user="reader-d"] .admin-link');
  check("Users marks the rejected registration and offers it no credit, limit or status action", await waitFor(
    `document.querySelector('tr[data-user="reader-d"] [data-status]')?.dataset.status === "rejected" &&
     !!document.querySelector('[data-status-note="rejected"]') &&
     !document.querySelector('form[aria-label="Credits for reader-d"]') &&
     !document.querySelector('form[aria-label="Status of reader-d"]')`));
  check("it says the rejection is final, shows no balance, and no longer counts as waiting",
    (await text('[data-status-note="rejected"]')).includes("a rejection is final") &&
    await evaluate(`!!document.querySelector('tr[data-user="reader-d"] [data-unapproved]') &&
      !document.querySelector('[data-attention="waiting"]')`));

  // ---------------------------------------------------------------- a policy preview records nothing
  await open("/admin/policy");
  await waitFor(`!!document.querySelector('form[aria-label="New policy version"] input[name="effort-low"]')`);
  await click('form[aria-label="New policy version"] input[name="effort-low"]');
  for (const [name, value] of [["base", "1"], ["per_1k_input_tokens", "1"], ["per_1k_output_tokens", "5"],
    ["max_request_usd", "0.2"], ["quote_valid_seconds", "900"]]) {
    await setValue(`form[aria-label="New policy version"] input[name="${name}"]`, value);
  }
  await clickText('form[aria-label="New policy version"] button', "Preview the quotes");
  const previewed = await waitFor(`document.querySelectorAll('[data-preview="policy"] tbody tr').length === 3`);
  const versions = await evaluate(`fetch("/api/admin/policy").then((reply) => reply.json())
    .then((body) => body.versions.length)`);
  check("a policy preview shows the three synthetic examples' quotes, names the ones the limit refuses, and records " +
    "nothing", previewed && versions === 2 && (await text('[data-preview="policy"]')).includes("Refused"),
    `versions ${versions}`);
  await setValue('form[aria-label="New policy version"] input[name="base"]', "2");
  check("changing the draft clears its preview", await waitFor(`!document.querySelector('[data-preview="policy"]')`));

  // ---------------------------------------------------------------- the selected pilot terms: presets, explicit actions
  await open("/admin/policy");
  await waitFor(`!!document.querySelector('[data-preset="pilot-flat-1"] button')`);
  await click('[data-preset="pilot-flat-1"] button');
  const draft = await evaluate(`Object.fromEntries([...document.querySelectorAll(
    'form[aria-label="New policy version"] input:not([type=checkbox])')].map((input) => [input.name, input.value]))`);
  const expected = { "extra-low": "0", "extra-medium": "5", "extra-high": "10", "extra-xhigh": "15", "extra-max": "20",
    base: "10", per_1k_input_tokens: "0", per_1k_output_tokens: "0", max_request_usd: "2", quote_valid_seconds: "600",
    reason: "" };
  const sorted = (value) => JSON.stringify(Object.entries(value).sort());
  const countVersions = () => evaluate(`fetch("/api/admin/policy").then((reply) => reply.json())
    .then((body) => body.versions.length)`);
  check("the pilot preset fills the draft's flat rates and Effort extras, keeps the active planning limit and " +
    "validity, and records nothing", sorted(draft) === sorted(expected) && await countVersions() === 2,
    JSON.stringify(draft));
  await clickText('form[aria-label="New policy version"] button', "Preview the quotes");
  await waitFor(`document.querySelectorAll('[data-preview="policy"] tbody tr').length === 15`);
  const flat = await evaluate(`[...document.querySelectorAll('[data-preview="policy"] tbody tr')]
    .map((row) => row.children[2].textContent).join()`);
  check("its preview quotes 10, 15, 20, 25 and 30 points for each synthetic example, whatever its length",
    flat === Array(3).fill("10,15,20,25,30").join(), flat);
  await setValue('form[aria-label="New policy version"] input[name="reason"]', "SYNTHETIC: the selected pilot terms");
  await click('form[aria-label="New policy version"] button[type=submit]');
  check("publishing it is the separate explicit action: a new version", await waitFor(
    `document.querySelector("[data-policy]")?.dataset.policy === "credit-policy-3"`) && await countVersions() === 3);
  const pilotTerms = await (await fetch(`${base}/api/public/credit-terms`)).json();
  check("the public terms quote the flat points for every example and say size does not change them",
    pilotTerms.examples.length === 3 && pilotTerms.examples.every((example) =>
      example.quotes.map((quote) => quote.credits).join() === "10,15,20,25,30") &&
    pilotTerms.size_note.includes("does not change"), JSON.stringify(pilotTerms.examples));
  await open("/admin");
  check("Users points out reader-c as the one active account with nothing allocated yet", await waitFor(
    `(document.querySelector('[data-attention="unallocated"]')?.textContent ?? "")
       .startsWith("1 active account has nothing allocated yet: reader-c (synthetic).") &&
     !!document.querySelector('tr[data-user="reader-c"] [data-allocation="none"]') &&
     !document.querySelector('tr[data-user="reader-b"] [data-allocation]')`),
    await text('[data-attention="unallocated"]'));
  await click('[data-attention="unallocated"] [data-manage="reader-c"]');
  check("its name opens reader-c's panel with the initial allocation offered", await waitFor(
    `!!document.querySelector('[aria-label="Manage reader-c"] [data-preset="pilot-initial-1"] button')`));
  await open("/admin?manage=nobody-here");
  check("an address naming no account opens no panel and says so", await waitFor(
    `!!document.querySelector("[data-manage-missing]") && !document.querySelector('[aria-label^="Manage "]')`));
  await open("/admin/registrations");
  await waitFor(`!!document.querySelector('[data-registration="reader-c"] a')`);
  await click('[data-registration="reader-c"] a');
  check("Registrations' link opens reader-c's panel under Users, with the initial allocation offered", await waitFor(
    `location.pathname === "/admin" && location.search === "?manage=reader-c" &&
     !!document.querySelector('[aria-label="Manage reader-c"] [data-preset="pilot-initial-1"] button')`));
  await click('[data-preset="pilot-initial-1"] button');
  const formValue = (form, name) => evaluate(`document.querySelector('form[aria-label="${form} for reader-c"] ` +
    `input[name="${name}"]')?.value ?? null`);
  const unallocated = await evaluate(`fetch("/api/admin/users").then((reply) => reply.json()).then((body) =>
    body.users.find((user) => user.username === "reader-c").allocated)`);
  check("the initial allocation fills reader-c's two forms with 100 credits and 3 a day, and records nothing",
    await formValue("Credits", "credits") === "100" && await formValue("Daily limit", "limit") === "3" &&
    unallocated === false);
  await setValue('form[aria-label="Credits for reader-c"] input[name="reason"]', "SYNTHETIC initial grant");
  await click('form[aria-label="Credits for reader-c"] button[type=submit]');
  check("the grant is its own action: 100 credits, still no daily limit, the offer gone and the grant not filled again",
    await waitFor(`document.querySelector('tr[data-user="reader-c"] [data-field="available"]')?.textContent === "100" &&
     !document.querySelector('[data-preset="pilot-initial-1"]') &&
     !!document.querySelector('form[aria-label="Daily limit for reader-c"]')`) &&
    (await text('tr[data-user="reader-c"] .admin-daily')).startsWith("No limit set") &&
    await formValue("Credits", "credits") === "" && await formValue("Daily limit", "limit") === "3");
  await setValue('form[aria-label="Daily limit for reader-c"] input[name="reason"]', "SYNTHETIC initial limit");
  await click('form[aria-label="Daily limit for reader-c"] button[type=submit]');
  check("the daily limit is the second action", await waitFor(
    `document.querySelector('tr[data-user="reader-c"] [data-field="limit"]')?.textContent === "3"`));
  check("once allocated, reader-c is no longer pointed out on Users", await waitFor(
    `document.querySelector("[data-attention]")?.dataset.attention === "none" &&
     !document.querySelector('tr[data-user="reader-c"] [data-allocation]')`));
  await open("/admin/registrations");
  check("nor on Registrations", await waitFor(`!!document.querySelector('[data-registration="reader-c"] [data-decided-by]')`) &&
    !(await evaluate(`!!document.querySelector('[data-registration="reader-c"] [data-allocation], [data-registration="reader-c"] a')`)));
  const readerC = async (method, path, body) => {
    const reply = await fetch(`${base}${path}`, { method, body: body && JSON.stringify(body), headers: {
      Cookie: approvedCookie, "X-Second-Order-Account": approvedId, ...(method === "POST" ? { Origin: base,
        "Content-Type": "application/json", "X-Second-Order-User": "1" } : {}) } });
    return reply.json();
  };
  const readyAccount = await readerC("GET", "/api/user/account");
  const pilotSource = await readerC("POST", "/api/user/sources", { headline: "Simulated pilot-terms source",
    source_url: "https://example.org/synthetic", published_at: "2026-10-13T10:00:00+03:00", source_text: SOURCE });
  const pilotAnalysis = await readerC("POST", "/api/user/analyses", { source_id: pilotSource.source.source_id,
    effort: "high" });
  const pilotQuote = await readerC("POST",
    `/api/user/analyses/${encodeURIComponent(pilotAnalysis.analysis.analysis_id)}/quotes`, {});
  check("reader-c is ready (100 credits, 3 a day) and is quoted 20 points at High", readyAccount.analysis.reasons.length
    === 0 && readyAccount.credits.available === 100 && readyAccount.daily.limit === 3 && pilotQuote.quote?.credits === 20,
    JSON.stringify(pilotQuote));

  // ---------------------------------------------------------------- a user in the browser never gets the Admin build
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  for (const path of ["/admin", "/admin/registrations", "/admin/actions", "/admin/credits", "/admin/policy",
    "/admin/usage"]) {
    await open(path);
    await waitFor(`!!document.querySelector(".admin-section h1")`);
    const layout = await evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth");
    check(`at phone width ${path} has no sideways scroll`, layout);
  }
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  await open("/");
  await waitFor(`!!document.querySelector(".admin-bar button")`);
  await clickText(".admin-bar button", "Sign out");
  await waitFor(`!!document.querySelector('a[href="/register"]')`);  // Signed out at `/`: the landing page.
  await open("/sign-in");
  await signIn("reader-a");
  check("a user is handed the Client build", await waitFor(
    `!!document.querySelector("main.page.client") && !document.querySelector(".admin-bar") &&
     document.querySelector(".account-strip")?.textContent.includes("reader-a (synthetic)")`, 15000));
  await open("/admin/users");
  await waitFor("document.readyState === 'complete' && !!document.querySelector('main')");
  check("/admin in a user's browser is the Client build", !(await evaluate(`!!document.querySelector(".admin-bar")`)) &&
    (await evaluate(`[...document.querySelectorAll("script[src]")].every((s) => /\\/assets\\/client-/.test(s.src))`)));
  const statuses = await evaluate(`Promise.all(["/api/admin/users", "/api/admin/actions", "/api/intake",
    "/api/research-analyses?capture_id=x"].map((path) => fetch(path).then((reply) => reply.status)))`);
  check("every admin route answers 403 to a user session", statuses.every((status) => status === 403), statuses.join());

  // ---------------------------------------------------------------- what the browser requested
  const outside = requests.filter((request) => !request.url.startsWith(base) && !request.url.startsWith("data:"));
  check("the pages requested nothing outside the local server", outside.length === 0,
    outside.map((request) => request.url).join(", "));
  check("no page error", errors.length === 0, errors.join(" | "));
  ws.close();
} catch (error) {
  check("the admin browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(500);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
