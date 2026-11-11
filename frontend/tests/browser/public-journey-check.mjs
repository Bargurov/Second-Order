// The entry journey end to end, in one headless Chrome against the REAL server with SYNTHETIC accounts and the fake
// sender (tests/review_browser_server.py --accounts fresh --simulated-provider): nothing here is mocked. Part of the
// connected entry gate (npm run test:browser:entry-gate), as its acceptance case for the operator's selected pilot
// terms; the joint Admin/Client check keeps a configurable size-rated policy. The server starts as an operator would
// set it up: accounts, no credit policy, nothing allocated. A visitor reads the landing page and is told no credit terms
// are set; the administrator fills the selected pilot preset on the Policy screen, supplies the planning limit and quote
// validity (synthetic test values: no monetary limit was selected) and publishes it, the one explicit action; the
// visitor's /credits then shows the flat quotes (10, 15, 20, 25, 30 points at each Effort, for every example). The
// visitor registers, is told the registration is pending when they sign in, an administrator approves it on the
// Registrations screen, the approved account signs in with nothing allocated and is shown every missing step, the
// administrator fills the selected initial allocation and records the grant of 100 credits and the daily limit of 3 as
// two separate actions, then publishes usage limits on the Usage & limits screen (SYNTHETIC values: none are selected
// for production; without any, a new source is refused), and the user adds a source, chooses High, prepares, is quoted 20 points, approves explicitly,
// gets the fake's result (evidence, interpretation, unknowns), saves a review and exports it. Also: a duplicate
// registration, a taken username, a forged field, a rejected registration and a deactivated account, each refused by
// the server.
//
// It needs the onboarding backend of entry/onboarding-logic (175f76f or later) and both builds; on a tree without the
// public routes it stops and says so. Every account, password, source and policy is SYNTHETIC; the fake sender never
// reaches a network, and the server reads no real key.
//
//   cd frontend; npm run build; node tests/browser/public-journey-check.mjs
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
for (const built of ["frontend/dist/index.html", "frontend/dist-client/client.html"]) {
  if (!existsSync(join(repo, built))) throw new Error("Build both clients first: npm run build");
}

const USAGE_LIMITS = {  // SYNTHETIC values typed by the check's administrator; a real server's are the operator's.
  searches_per_day: "50", imports_per_day: "10", sources_per_day: "60", preparations_per_day: "60", max_sources: "500",
  max_source_bytes: "60000000", requests_per_minute: "600", concurrent_requests: "16",
  publication_fetches_per_day: "20", refreshes_per_day: "20", refresh_cooldown_seconds: "0",
};
const PASSWORDS = { admin: "synthetic-admin-pass", "reader-c": "synthetic-reader-c-journey",
                    "reader-d": "synthetic-reader-d-journey", taken: "synthetic-taken-journey" };
const SOURCE = { headline: "Simulated freight office reports September throughput",
  url: "https://example.org/synthetic-freight", text: "October 13, 2026\n\nSimulated freight office reports " +
    "September throughput\n\nThe Simulated Freight Office reported that container throughput fell 4.2 percent from " +
    "August while two berths were closed for maintenance.\n\nThe office said it expects the maintenance work to be " +
    "complete by mid-October.\n\nSYNTHETIC TEST SOURCE." };
// The joint check's own list of what a user payload must never carry (tests/browser/admin-client-integration-check.mjs).
const ADMIN_ONLY = /claude|sonnet|opus|haiku|anthropic|\$\s?\d|\busd\b|\btokens?\b|\bcosts?\b|\bproviders?\b|\bmodels?\b|planning|request_id|x-api-key|sk-ant|http_status|elapsed|thinking|\bpid\b|prompt/i;
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const root = mkdtempSync(join(tmpdir(), "second-order-public-journey-"));
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
    "--accounts", "fresh", "--simulated-provider"], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  let started = false;
  for (let i = 0; i < 150 && !started; i++) {
    try { started = (await fetch(`${base}/api/session`)).ok; } catch { await sleep(200); }
  }
  if (!started) throw new Error("The server did not start.");
  const terms = await fetch(`${base}/api/public/credit-terms`);
  if (!terms.ok) {
    throw new Error(`GET /api/public/credit-terms answered ${terms.status}: this tree has no onboarding backend. Run ` +
      "this check on a tree with entry/onboarding-logic 175f76f or later.");
  }
  let serverTerms = await terms.json();

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
      if (request && /\/api\/(user|public|session)/.test(request.url)) {
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
  const value = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.value ?? null`);
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete' && !document.querySelector('.shell-status')");
  };
  const cookies = async () => (await send("Network.getCookies", { urls: [base] })).cookies;
  const shots = process.env.SECOND_ORDER_SCREENSHOTS;
  const shoot = async (name) => {  // Opt-in viewport captures; never a whole tall page.
    if (!shots) return;
    const shot = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(shots, `${name}.png`), Buffer.from(shot.data, "base64"));
  };
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
  const register = async (form) => {
    await open("/register");
    await waitFor(`!!document.querySelector(".public-register")`);
    for (const [name, typed] of Object.entries(form)) await setValue(`.public-register [name="${name}"]`, typed);
    await click(".public-register button[type=submit]");
  };
  // As the Admin page does, every call names the account the page is signed in as (docs/account-binding-contract.md).
  const adminCall = (path, method = "GET", body) => evaluate(`fetch("/api/session").then((reply) => reply.json())
    .then((session) => fetch(${JSON.stringify(path)}, { method: ${JSON.stringify(method)},
      headers: { "X-Second-Order-Account": session.user.user_id${method === "POST"
        ? ', "Content-Type": "application/json", "X-Second-Order-Admin": "1"' : ""} },
      ${body ? `body: ${JSON.stringify(JSON.stringify(body))},` : ""} }))
    .then(async (reply) => ({ status: reply.status, body: await reply.json() }))`);
  const providerSends = () => existsSync(join(served, "simulated-provider"))
    ? readdirSync(join(served, "simulated-provider")).filter((name) => /^request-\d+\.json$/.test(name)) : [];

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  // 1. A visitor: the landing page and the server's own credit terms, first none, then the selected pilot terms.
  await open("/");
  check("signed out, / is the landing page of the Client build, with Register, Sign in and How credits work",
    await waitFor(`!!document.querySelector('[data-public="landing"] a[href="/register"]') &&
      !!document.querySelector('a[href="/sign-in"]') && !!document.querySelector('a[href="/credits"]') &&
      !document.querySelector(".shell-form")`) &&
    (await evaluate(`[...document.querySelectorAll("script[src]")].every((s) => /\\/assets\\/client-/.test(s.src))`)));
  await open("/credits");
  check("a fresh server sets no terms, and /credits says so", serverTerms.state === "no_credit_policy" &&
    await waitFor(`!!document.querySelector('[data-credit-terms="no_credit_policy"]')`) &&
    !(await exists("[data-credit-examples] tbody tr")));
  check("the administrator signs in from the Client's sign-in page and is handed the Admin build", await signInAdmin());
  await open("/admin/policy");
  await waitFor(`!!document.querySelector('[data-preset="pilot-flat-1"] button')`);
  await click('[data-preset="pilot-flat-1"] button');
  const pilotDraft = await evaluate(`Object.fromEntries([...document.querySelectorAll(
    'form[aria-label="New policy version"] input:not([type=checkbox])')].map((input) => [input.name, input.value]))`);
  check("the selected pilot preset fills flat rates and Effort extras and leaves the planning limit to the administrator",
    pilotDraft.base === "10" && pilotDraft.per_1k_input_tokens === "0" && pilotDraft.per_1k_output_tokens === "0" &&
    ["0", "5", "10", "15", "20"].join() === ["low", "medium", "high", "xhigh", "max"].map((effort) =>
      pilotDraft[`extra-${effort}`]).join() && pilotDraft.max_request_usd === "" &&
    (await adminCall("/api/admin/policy")).body.versions.length === 0, JSON.stringify(pilotDraft));
  for (const [name, typed] of [["max_request_usd", "1"], ["quote_valid_seconds", "900"],
    ["reason", "SYNTHETIC: the selected pilot terms, with a test planning limit"]]) {
    await setValue(`form[aria-label="New policy version"] input[name="${name}"]`, typed);
  }
  await click('form[aria-label="New policy version"] button[type=submit]');
  check("publishing it is the one explicit action: the first policy version",
    await waitFor(`document.querySelector("[data-policy]")?.dataset.policy === "credit-policy-1"`));
  await signOutAdmin();
  serverTerms = await (await fetch(`${base}/api/public/credit-terms`)).json();
  await open("/credits");
  await waitFor(`!!document.querySelector('[data-credit-terms="configured"] [data-credit-examples] tbody tr')`);
  const shownTerms = await evaluate(`({ state: document.querySelector("[data-credit-terms]")?.dataset.creditTerms,
    rules: [...document.querySelectorAll("[data-credit-rules] li")].map((li) => li.textContent),
    rows: [...document.querySelectorAll("[data-credit-examples] tbody tr")].map((tr) => [...tr.querySelectorAll("td")].map((td) => td.textContent)) })`);
  check("/credits shows this server's rules and the quotes it gives now for its synthetic examples, exactly",
    shownTerms.state === serverTerms.state && JSON.stringify(shownTerms.rules) === JSON.stringify(serverTerms.rules) &&
    JSON.stringify(shownTerms.rows) === JSON.stringify(serverTerms.examples.map((example) =>
      example.quotes.map((quote) => String(quote.credits)))), JSON.stringify({ shownTerms, state: serverTerms.state }));
  check("they are the selected flat terms: 10, 15, 20, 25 and 30 points for every example, whatever its length",
    shownTerms.rows.length === 3 && shownTerms.rows.every((row) => row.join() === "10,15,20,25,30"),
    JSON.stringify(shownTerms.rows));
  await shoot("journey-credits");

  // 2. Registration, a resubmission, a taken username and a forged field.
  const readerC = { username: "reader-c", display_name: "Reader C (synthetic)", password: PASSWORDS["reader-c"],
                    repeat: PASSWORDS["reader-c"], note: "SYNTHETIC journey registration" };
  await register(readerC);
  check("registering sends one request and the server records it as pending",
    await waitFor(`!!document.querySelector('[data-public="registered"]')`) &&
    /waiting for approval/i.test(await text('[data-public="registered"]')) &&
    sent.filter((item) => item.method === "POST" && item.url.endsWith("/api/public/registrations")).length === 1);
  await register(readerC);
  check("the same registration again is the server's duplicate: nothing new recorded",
    await waitFor(`/already been received/i.test(document.querySelector('[data-public="registered"]')?.textContent ?? "")`));
  await register({ username: "reader-a", display_name: "Someone (synthetic)", password: PASSWORDS.taken,
                   repeat: PASSWORDS.taken, note: "" });
  check("a username that belongs to another account is refused on its field; the password field is cleared",
    await waitFor(`!!document.querySelector('[data-field-error="username"]')`) &&
    (await value('.public-register [name="password"]')) === "" && (await value('.public-register [name="note"]')) === "");
  const forged = await fetch(`${base}/api/public/registrations`, { method: "POST", headers: { Origin: base,
    "Content-Type": "application/json", "X-Second-Order-Session": "1" }, body: JSON.stringify({ username: "reader-x",
    display_name: "Forged (synthetic)", password: "synthetic-forged-pass", note: "", role: "admin" }) });
  check("a registration carrying a role is refused whole by the server",
    forged.status === 422 && (await forged.json()).code === "invalid_request");

  // 3. Pending: signing in shows the registrant's own status and opens no session.
  await signIn("reader-c");
  await waitFor(`!!document.querySelector('[data-public="status"]')`);
  check("signing in while pending shows only the registrant's own status, with no session",
    /waiting for approval/i.test(await text('[data-public="status"]')) &&
    (await text('[data-public="status"]')).includes("reader-c") && (await cookies()).length === 0 &&
    !(await exists('.shell-form input[name="password"]')));
  await shoot("journey-pending");
  await register({ username: "reader-d", display_name: "Reader D (synthetic)", password: PASSWORDS["reader-d"],
                   repeat: PASSWORDS["reader-d"], note: "SYNTHETIC journey registration to reject" });
  await waitFor(`!!document.querySelector('[data-public="registered"]')`);

  // 4. The administrator decides on the Registrations screen: approve one, reject the other. Nothing is allocated.
  check("the administrator signs in again and is handed the Admin build", await signInAdmin());
  await open("/admin/registrations");
  await waitFor(`!!document.querySelector('form[aria-label="Decision on reader-c"]') &&
    !!document.querySelector('form[aria-label="Decision on reader-d"]')`);
  check("the Registrations screen lists both, with the notes typed at registration",
    (await evaluate("document.body.textContent")).includes("SYNTHETIC journey registration"));
  await setValue('form[aria-label="Decision on reader-c"] input[name="reason"]', "SYNTHETIC approval in the journey");
  await click('form[aria-label="Decision on reader-c"] button[type=submit]');
  await waitFor(`!document.querySelector('form[aria-label="Decision on reader-c"]')`);
  await setValue('form[aria-label="Decision on reader-d"] input[name="reason"]', "SYNTHETIC rejection in the journey");
  await clickText('form[aria-label="Decision on reader-d"] button', "Reject");
  await waitFor(`!document.querySelector('form[aria-label="Decision on reader-d"]')`);
  const users = (await adminCall("/api/admin/users")).body.users;
  const row = (name) => users.find((user) => user.username === name);
  check("the server records one approval and one rejection (what approval allocated is checked by the user's Home)",
    row("reader-c")?.status === "active" && row("reader-d")?.status === "rejected", JSON.stringify(users.map((user) =>
      [user.username, user.status])));
  await signOutAdmin();

  // 5. Approved, nothing allocated: every missing step, from the server.
  await open("/sign-in");
  check("the approved account signs in to the Client", await signInClient("reader-c"));
  await waitFor(`!!document.querySelector("[data-first-use] [data-reason]")`);
  const steps = await evaluate(`[...document.querySelectorAll("[data-first-use] [data-reason]")].map((e) => e.dataset.reason)`);
  check("before allocation, Home lists the server's missing steps: no daily limit, no credits allocated",
    JSON.stringify(steps) === '["no_daily_limit","no_credits_allocated"]' &&
    (await text('[data-entitlement="credits"]')) === "0 credits available", JSON.stringify(steps));
  await shoot("journey-first-use");
  await open("/credits");
  check("their /credits shows the same steps above the server's terms", await waitFor(
    `!!document.querySelector('main.page.client [data-first-use]') && !!document.querySelector('[data-credit-terms="${serverTerms.state}"]')`));
  await signOutClient();
  await signIn("reader-d");
  check("the rejected registrant sees only that it was not approved, with no session", await waitFor(
    `/not approved/i.test(document.querySelector('[data-public="status"]')?.textContent ?? "")`) &&
    !(await text('[data-public="status"]')).includes("SYNTHETIC rejection") && (await cookies()).length === 0);

  // 6. The administrator fills the selected initial allocation and records it as two separate actions.
  await signInAdmin();
  await open("/admin");
  await waitFor(`!!document.querySelector('tr[data-user="reader-c"] .admin-link')`);
  await click('tr[data-user="reader-c"] .admin-link');
  await waitFor(`!!document.querySelector('[data-preset="pilot-initial-1"] button')`);
  await click('[data-preset="pilot-initial-1"] button');
  check("the selected initial allocation fills the two forms with 100 credits and 3 a day; nothing is recorded yet",
    (await value('form[aria-label="Credits for reader-c"] input[name="credits"]')) === "100" &&
    (await value('form[aria-label="Daily limit for reader-c"] input[name="limit"]')) === "3" &&
    (await adminCall("/api/admin/users")).body.users.find((user) => user.username === "reader-c")?.allocated === false);
  await setValue('form[aria-label="Credits for reader-c"] input[name="reason"]', "SYNTHETIC initial grant in the journey");
  await click('form[aria-label="Credits for reader-c"] button[type=submit]');
  const granted = await waitFor(`document.querySelector('tr[data-user="reader-c"] [data-field="available"]')?.textContent === "100"
    && !!document.querySelector('form[aria-label="Daily limit for reader-c"]')`) &&
    (await adminCall("/api/admin/users")).body.users.find((user) => user.username === "reader-c")?.daily.limit === null;
  await setValue('form[aria-label="Daily limit for reader-c"] input[name="reason"]', "SYNTHETIC initial limit in the journey");
  await click('form[aria-label="Daily limit for reader-c"] button[type=submit]');
  check("the administrator records the grant of 100 credits, and then the daily limit of 3, as two actions", granted &&
    await waitFor(`document.querySelector('tr[data-user="reader-c"] [data-field="limit"]')?.textContent === "3"`));
  await open("/admin/usage");
  check("no usage limits are set yet, and every field of the Usage & limits form starts empty", await waitFor(
    `document.querySelector("[data-usage-policy]")?.dataset.usagePolicy === "none" &&
     [...document.querySelectorAll('form[aria-label="New usage limits"] input')].every((input) => input.value === "")`));
  for (const [name, typed] of Object.entries(USAGE_LIMITS)) {
    await setValue(`form[aria-label="New usage limits"] input[name="${name}"]`, typed);
  }
  await setValue('form[aria-label="New usage limits"] input[name="reason"]', "SYNTHETIC usage limits in the journey");
  await click('form[aria-label="New usage limits"] button[type=submit]');
  check("the administrator publishes the usage limits once, as its own action", await waitFor(
    `document.querySelector("[data-usage-policy]")?.dataset.usagePolicy === "usage-policy-1"`) &&
    (await adminCall("/api/admin/usage-policy")).body.versions.length === 1);
  await signOutAdmin();

  // 7. The user: source -> Effort -> prepare -> quote -> explicit approval -> the fake's result -> review -> export.
  await open("/sign-in");
  check("signed in again, the account is ready: no missing step, the server's credits and allowance",
    await signInClient("reader-c") && await waitFor(`document.querySelector('[data-entitlement="credits"]')?.textContent === "100 credits available"`) &&
    !(await exists("[data-first-use]")) && (await text('[data-entitlement="daily"]')).startsWith("3 of 3 analyses left today"));
  await open("/sources/new");
  await waitFor(`!!document.querySelector(".client-form")`);
  await setValue('input[name="headline"]', SOURCE.headline);
  await setValue('input[name="source_url"]', SOURCE.url);
  await setValue('input[name="date"]', "2026-10-13");
  await setValue('input[name="time"]', "10:00");
  await setValue('select[name="offset"]', "+03:00");
  await setValue('textarea[name="source_text"]', SOURCE.text);
  await click(".client-save-source");
  check("the source is saved once and opens its page", await waitFor(`/^\\/sources\\/[^/]+$/.test(location.pathname)`, 15000) &&
    sent.filter((item) => item.method === "POST" && item.url.endsWith("/api/user/sources")).length === 1);
  await waitFor(`document.querySelectorAll('input[name="effort"]').length > 0`);
  const offered = await evaluate(`[...document.querySelectorAll('input[name="effort"]')].map((e) => e.value)`);
  check("the Effort options are the server's, none chosen", JSON.stringify(offered) ===
    JSON.stringify(serverTerms.efforts.map((option) => option.effort)) &&
    !(await evaluate(`[...document.querySelectorAll('input[name="effort"]')].some((e) => e.checked)`)), JSON.stringify(offered));
  const effort = "high";
  await click(`input[name="effort"][value="${effort}"]`);
  await click(".client-prepare");
  await waitFor(`!!document.querySelector(".client-get-quote")`, 15000);
  check("preparing is one request and quotes nothing", sent.filter((item) => item.method === "POST" &&
    item.url.endsWith("/api/user/analyses")).length === 1 && !sent.some((item) => item.url.endsWith("/quotes")));
  await click(".client-get-quote");
  await waitFor(`!!document.querySelector(".client-approve input")`, 15000);
  const quoted = Number(await text("[data-quote-credits]"));
  check("the server's flat quote at High is shown, 20 points; the approval starts unchecked, Run is disabled and " +
    "nothing was sent", quoted === 20 && !(await evaluate(`document.querySelector(".client-approve input").checked`)) &&
    await evaluate(`document.querySelector(".client-run").disabled`) && providerSends().length === 0);
  await click(".client-approve input");
  await click(".client-run");
  await waitFor(`!!document.querySelector("[data-panel=recorded]")`, 30000);
  const surfaces = await evaluate(`["client-evidence", "client-interpretation", "client-unknowns"].map((name) =>
    !!document.querySelector("." + name))`);
  check("one explicit approval sends once to the fake; the result shows evidence, interpretation and unknowns",
    providerSends().length === 1 && surfaces.every(Boolean) &&
    sent.filter((item) => item.method === "POST" && item.url.endsWith("/runs")).length === 1);
  const runBody = JSON.parse(sent.find((item) => item.method === "POST" && item.url.endsWith("/runs")).postData);
  check("the run repeated the quote exactly, with the person's approval",
    runBody.credits === quoted && runBody.effort === effort && runBody.approve === true);
  check("the server charged exactly the quote, and the allowance moved by one run",
    (await text(".client-charge")).startsWith(`${quoted} credits charged of ${quoted} credits reserved`) &&
    (await text('[data-entitlement="credits"]')) === `${100 - quoted} credits available` &&
    (await text('[data-entitlement="daily"]')).startsWith("2 of 3 analyses left today"));
  await shoot("journey-result");
  await evaluate(`document.querySelector('input[name="review-status"][value="human_reviewed"]').click()`);
  await setValue(".client-review textarea", "SYNTHETIC review in the entry journey: statement 1 matches its quote.");
  await click(".client-save-review");
  check("the review is saved as version 1, bound to this result", await waitFor(`!!document.querySelector('[data-version="1"]')`));
  const exported = await evaluate(`fetch(document.querySelector(".client-export a").getAttribute("href"))
    .then(async (reply) => ({ status: reply.status, body: await reply.json() }))`);
  check("the export is the saved record: the result and the review version",
    exported.status === 200 && exported.body.analysis.reviews.length === 1 &&
    exported.body.analysis.reviews[0].status === "human_reviewed" && exported.body.analysis.state === "recorded");
  await open("/analyses");
  check("the history lists the recorded, reviewed analysis", await waitFor(
    `document.querySelectorAll(".client-history-row").length === 1 &&
     document.querySelector(".client-history-row")?.textContent.includes("Reviewed")`));
  await signOutClient();

  // 8. A deactivated account is refused with the one message for every failure.
  await signInAdmin();
  await open("/admin");
  await waitFor(`!!document.querySelector('tr[data-user="reader-c"] .admin-link')`);
  await click('tr[data-user="reader-c"] .admin-link');
  await waitFor(`!!document.querySelector('form[aria-label="Status of reader-c"]')`);
  await setValue('form[aria-label="Status of reader-c"] input[name="reason"]', "SYNTHETIC deactivation in the journey");
  await click('form[aria-label="Status of reader-c"] button[type=submit]');
  await waitFor(`(document.querySelector('tr[data-user="reader-c"]')?.textContent ?? "").toLowerCase().includes("disabled") ||
    (document.querySelector('tr[data-user="reader-c"] [data-status]')?.dataset.status === "disabled")`);
  await signOutAdmin();
  await signIn("reader-c");
  await waitFor(`!!document.querySelector(".shell-problem")`);
  check("a deactivated account is refused with the one message for every failure, and no status",
    /not correct, or the account is not active/.test(await text(".shell-problem")) &&
    !(await exists('[data-public="status"]')) && (await value('.shell-form [name="password"]')) === "");

  // 9. Passwords, payloads, storage and requests.
  const secrets = Object.values(PASSWORDS);
  const carriers = sent.filter((item) => secrets.some((secret) => item.postData.includes(secret) || item.url.includes(secret)));
  check("passwords went only into registrations and sign-ins",
    carriers.length > 0 && carriers.every((item) => item.method === "POST" &&
      /\/api\/(public\/registrations|session\/login)$/.test(item.url)), carriers.map((item) => item.url).join(", "));
  const payloads = (await Promise.all([...answered.values()])).filter(Boolean);
  const leaks = payloads.filter(({ text: body }) => ADMIN_ONLY.test(body.replace(/\d{8}T\d{12}Z-[0-9a-f]{12}(\.[A-Za-z0-9_-]+)*/g, "ID")));
  check("no public, session or user reply carried an administrator's field", payloads.length > 20 && leaks.length === 0,
    leaks.map(({ path, text: body }) => `${path}: ${body.match(ADMIN_ONLY)?.[0]}`).slice(0, 5).join(" | "));
  const stored = await evaluate(`JSON.stringify({ local: Object.entries(localStorage), session: Object.entries(sessionStorage) })`);
  check("nothing was left in browser storage", stored === '{"local":[],"session":[]}', stored);
  check("the browser requested nothing outside the local server", outside.length === 0, outside.join(", "));
  check("no page error", pageErrors.length === 0, pageErrors.join(" | "));
  check("the fake sender received exactly the one approved run", providerSends().length === 1);
  ws.close();
} catch (error) {
  check("the entry journey ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(600);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
