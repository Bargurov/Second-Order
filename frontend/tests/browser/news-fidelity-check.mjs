// Browser check of economic fidelity on the reader's story page (econ-fidelity-0.1), on the BUILT Client against the
// REAL server (tests/news_desk_server.py --fidelity-case): a SYNTHETIC statistic at a seasonally adjusted annual rate
// and a change inside its stated margin, published through the real actions. Nothing is mocked in the browser, nothing
// reaches a network (every fetcher is simulated) and no real key is read.
//
// What a reader must see wherever a figure appears: the development sentence, assumptions, channels, affected parties,
// what to watch and the compact references each say the rate is a seasonally adjusted annual rate (never a month's
// count) and that the change sits inside its stated margin; the figure list states the margin, and "nominal or real
// not stated" is not said of a count of houses; no reference is left unrendered; reading sends only GETs.
//
// econ-explanation-0.4: each explanation says the form of its evidence apart from its subject. A SYNTHETIC bank lending
// survey (banks' answers about credit conditions, published through the real actions) says whose answers it reports,
// writes its balances as net percentages of respondents and shows the bank survey's framework note with its limits;
// an explanation saved before 0.4 (the real copies) says that its evidence form was not recorded.
//
// story-brief-0.4 and econ-explanation-0.5: a SYNTHETIC safeguard investigation, opened and undecided, records who
// says what. Its page shows the stage "Procedure opened, no decision on a measure", a "Who says what" block with the
// duty's condition in its own words, each fact's claim, and the bounded duty marked conditional wherever it appears.
//
// econ-explanation-0.6: each alternative of the SYNTHETIC investigation says what supports it, and a channel's steps
// are said not to be a timeline; copies of real records saved earlier show no support, as they were saved.
//
// With SECOND_ORDER_REAL_RECORDS (a data folder) and SECOND_ORDER_REAL_STORIES (comma-separated story IDs), the server
// also serves COPIES of that folder's newsroom and caches (only read), and the check opens each named story's page
// and records what it shows. SECOND_ORDER_SCREENSHOTS names a folder for viewport captures.
//
//   cd frontend; npm run build; node tests/browser/news-fidelity-check.mjs
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const python = process.env.SECOND_ORDER_PYTHON ?? "python";
// Test current source without replacing the builds served by an already running local server.
const staticRoot = process.env.SECOND_ORDER_TEST_STATIC_ROOT
  ? resolve(process.env.SECOND_ORDER_TEST_STATIC_ROOT) : join(repo, "frontend");
const chromePath = [process.env.SECOND_ORDER_CHROME, "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
  "/usr/bin/chromium-browser"].find((path) => path && existsSync(path));
if (!chromePath) throw new Error("Chrome was not found; set SECOND_ORDER_CHROME to its executable.");
for (const built of ["dist/index.html", "dist-client/client.html"]) {
  if (!existsSync(join(staticRoot, built))) throw new Error("Build both clients first: npm run build (or set SECOND_ORDER_TEST_STATIC_ROOT)");
}

const PASSWORDS = { "reader-a": "synthetic-reader-a" };  // tests/account_fakes.py
const HOMES = "Synthetic new home sales at a 676,000 annual rate in September";  // tests/news_desk_fakes.py
const BANKS = "Synthetic bank lending survey: banks report tighter credit standards";  // tests/news_desk_fakes.py
const WIRE = "Synthetic Republic opens safeguard investigation into imported steel wire";  // tests/news_desk_fakes.py
const records = process.env.SECOND_ORDER_REAL_RECORDS ?? null;
const realStories = (process.env.SECOND_ORDER_REAL_STORIES ?? "").split(",").filter(Boolean);
const shots = process.env.SECOND_ORDER_SCREENSHOTS ?? null;
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const root = mkdtempSync(join(tmpdir(), "second-order-news-fidelity-"));
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
  const extra = records ? ["--records", records, "--newsroom", join(records, "newsroom", "newsroom.db")] : [];
  const server = spawn(python, [join(repo, "tests/news_desk_server.py"), "--root", served, "--port", String(port),
    "--simulated-provider", "--fidelity-case", "--static-root", staticRoot, ...extra],
  { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  let started = false;
  for (let i = 0; i < 300 && !started; i++) {
    try { started = (await fetch(`${base}/api/session`)).ok; } catch { await sleep(200); }
  }
  if (!started) throw new Error("The server did not start.");
  const feedLog = join(served, "simulated-feeds", "requests.jsonl");
  const feedRequests = () => existsSync(feedLog) ? readFileSync(feedLog, "utf8").split("\n").filter(Boolean).length : 0;
  const providerSends = () => existsSync(join(served, "simulated-provider"))
    ? readdirSync(join(served, "simulated-provider")).filter((name) => /^request-\d+\.json$/.test(name)).length : 0;

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
  const pageErrors = [];
  const outside = [];
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else if (message.method === "Network.requestWillBeSent") {
      const { url, method } = message.params.request;
      if (!url.startsWith(base) && !url.startsWith("data:")) outside.push(url);
      sent.push({ url, method });
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
  const waitFor = async (expression, timeout = 15000) => {
    for (const start = Date.now(); Date.now() - start < timeout; await sleep(80)) {
      if (await evaluate(expression)) return true;
    }
    return false;
  };
  const setValue = (selector, value) => evaluate(`(() => {
    const element = document.querySelector(${JSON.stringify(selector)});
    if (!element) return false;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(element, ${JSON.stringify(value)});
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`);
  const click = (selector) => evaluate(`(() => { const e = document.querySelector(${JSON.stringify(selector)});
    if (!e) return false; e.click(); return true; })()`);
  const clickText = (selector, words) => evaluate(`(() => { const e = [...document.querySelectorAll(${JSON.stringify(selector)})]
    .find((item) => item.textContent.includes(${JSON.stringify(words)})); if (!e) return false; e.click(); return true; })()`);
  const open = async (address) => {
    await send("Page.navigate", { url: base + address });
    await waitFor("document.readyState === 'complete' && !document.querySelector('.shell-status')");
  };
  if (shots) mkdirSync(shots, { recursive: true });
  const shoot = async (name, selector) => {  // Opt-in viewport captures of one part, never a whole tall page.
    if (!shots) return;
    if (selector) await evaluate(`document.querySelector(${JSON.stringify(selector)})?.scrollIntoView({ block: "start" })`);
    await sleep(150);
    const shot = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(shots, `${name}.png`), Buffer.from(shot.data, "base64"));
  };
  const page = () => evaluate(`({
    path: location.pathname,
    what: document.querySelector("[data-explanation-top] [data-stage]")?.textContent ?? "",
    why: document.querySelector("[data-why]")?.textContent ?? "",
    tag: document.querySelector("[data-authorship-tag]")?.textContent?.trim() ?? "",
    channels: [...document.querySelectorAll("[data-section='channels'] .news-channels > li")].map((li) => li.textContent),
    figures: [...document.querySelectorAll("[data-figure]")].map((li) => ({ id: li.dataset.figure,
      text: li.textContent.replace(/\\s+/g, " "), details: li.querySelector("[data-figure-details]")?.textContent
        .replace(/\\s+/g, " ") ?? "" })),
    assumptions: [...document.querySelectorAll("[data-section='assumptions'] li")].map((li) => li.textContent),
    watch: [...document.querySelectorAll("[data-section='watch'] li")].map((li) => li.textContent),
    basis: [...document.querySelectorAll(".news-basis")].map((row) => row.textContent.replace(/\\s+/g, " ")),
    evidence: document.querySelector("[data-evidence-form]")?.dataset.evidenceForm ?? null,
    evidenceText: document.querySelector("[data-evidence-form]")?.textContent.replace(/\\s+/g, " ").trim() ?? "",
    notes: [...document.querySelectorAll("[data-section='background'] [data-note]")].map((li) => li.textContent.replace(/\\s+/g, " ")),
    stage: document.querySelector("[data-explanation-top] [data-stage]")?.dataset.stage ?? null,
    claims: [...document.querySelectorAll("[data-claims] [data-claim]")].map((li) => ({ id: li.dataset.claim,
      modality: li.dataset.modality, text: li.textContent.replace(/\\s+/g, " ") })),
    factClaims: [...document.querySelectorAll("[data-fact-claim]")].map((span) => span.dataset.factClaim),
    figureClaims: [...document.querySelectorAll("[data-figure-claim]")].map((span) => span.textContent.trim()),
    raw: /\\{[fcFC] ?\\d{1,2}\\}/.test(document.body.textContent),
    explained: !!document.querySelector("[data-explanation-top]"),
    alternatives: [...document.querySelectorAll("[data-section='alternatives'] > ul:first-of-type > li")].map((li) => ({
      support: li.querySelector("[data-support]")?.dataset.support ?? null,
      said: li.querySelector("[data-support]")?.textContent.trim() ?? "" })),
    stepsNote: document.querySelector("[data-steps-note]")?.textContent.replace(/\\s+/g, " ").trim() ?? "",
    explanationNote: document.querySelector("[data-explanation-note]")?.textContent.replace(/\\s+/g, " ").trim() ?? "",
  })`);

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  await open("/sign-in");
  await waitFor(`!!document.querySelector('.shell-form input[name="password"]')`);
  await setValue('.shell-form input[name="username"]', "reader-a");
  await setValue('.shell-form input[name="password"]', PASSWORDS["reader-a"]);
  await click(".shell-form button[type=submit]");
  check("the reader signs in and lands on the News home",
    await waitFor(`document.querySelector("main.page.client")?.dataset.view === "news" && !!document.querySelector(".news-story")`));
  const before = { feeds: feedRequests(), sends: providerSends(), writes: sent.filter((row) => row.method !== "GET").length };

  // The SYNTHETIC annual-rate story, opened from its headline.
  check("the annual-rate story's headline opens its internal story page",
    await clickText(".news-story-title a", HOMES) &&
    await waitFor(`!!document.querySelector(".news-story-page [data-explanation-top]") && /^\\/news\\/stories\\/story-/.test(location.pathname)`));
  const homes = await page();
  check("what happened says the level is a seasonally adjusted annual rate, never a month's count",
    /676,000 houses \(seasonally adjusted annual rate\) in September/.test(homes.what), homes.what);
  check("the change carries its stated margin and that the margin is wider than the change",
    /−0\.6% \(seasonally adjusted; stated margin ±13\.8%, wider than the change\)/.test(homes.what), homes.what);
  check("a sentence that already speaks of the margin is not told it twice",
    /the −0\.6% \(seasonally adjusted\) change is small next to its stated margin/.test(homes.why), homes.why);
  check("channels, affected parties, assumptions and what to watch render the figure with its rate basis",
    homes.channels.length === 1 && (homes.channels[0].match(/676,000 houses \(seasonally adjusted annual rate\)/g) ?? [])
      .length >= 3 && homes.assumptions.some((row) => /rate of 676,000 houses \(seasonally adjusted annual rate\) is not revised away/.test(row)) &&
      homes.watch.some((row) => /revision of 676,000 houses \(seasonally adjusted annual rate\)/.test(row)),
    JSON.stringify([homes.channels, homes.assumptions, homes.watch]));
  check("compact references keep the rate basis and the margin",
    homes.basis.some((row) => /676,000 houses \(seasonally adjusted annual rate\): SYNTHETIC September new home sales/.test(row)) &&
    homes.basis.some((row) => /stated margin ±13\.8%/.test(row)), JSON.stringify(homes.basis));
  const [f1, f2] = homes.figures;
  check("the figure list states the annual rate and the margin, and no nominal or real label for a count of houses",
    /a flow at an annual rate/.test(f1?.details ?? "") && !/nominal or real/.test(f1?.details ?? "") &&
    /stated margin ±13\.8%/.test(f2?.details ?? ""), JSON.stringify(homes.figures));
  check("no reference is left unrendered anywhere on the page", !homes.raw);
  check("what changed says the form of its evidence apart from its subject",
    homes.evidence === "recorded" && homes.evidenceText ===
      "Evidence: a reported observation or measurement. Subject: housing sales, construction or house prices.",
    homes.evidenceText);
  await click("[data-section='evidence'] summary");
  await shoot("fidelity-synthetic-top", "[data-explanation-top]");
  await shoot("fidelity-synthetic-figures", "[data-section='evidence']");

  // The SYNTHETIC bank lending survey: banks' answers, never a policy decision or a fall in lending.
  await clickText("a", "News");
  await waitFor(`!!document.querySelector(".news-story")`);
  check("the bank survey's headline opens its internal story page",
    await clickText(".news-story-title a", BANKS) &&
    await waitFor(`!!document.querySelector(".news-story-page [data-explanation-top]") && /^\\/news\\/stories\\/story-/.test(location.pathname)`));
  await click("[data-section='background'] summary");
  const banks = await page();
  check("the bank survey says it reports banks' answers about credit conditions",
    banks.evidence === "recorded" && banks.evidenceText ===
      "Evidence: respondents' answers in a survey (banks). Subject: credit or financing conditions.", banks.evidenceText);
  check("its balances read as net percentages of respondents, never as a change in lending",
    /firms \(9% \(net percentage of respondents\)\)/.test(banks.what) &&
    /housing loans \(−27% \(net percentage of respondents\)\)/.test(banks.what), banks.what);
  check("the figure list says what a net percentage is",
    banks.figures.length === 2 && banks.figures.every((row) => /a net percentage: the share of respondents reporting one direction minus the share reporting the other/.test(row.details)),
    JSON.stringify(banks.figures));
  check("the background is the bank survey's note with its limits, not the firm survey's note",
    banks.notes.length === 1 && /Banks' reports on credit standards and loan demand/.test(banks.notes[0]) &&
    /Reported tightening is not an observed fall in lending/.test(banks.notes[0]) &&
    !/Firms' access to finance/.test(banks.notes.join(" ")), JSON.stringify(banks.notes));
  check("no reference is left unrendered on the bank survey's page", !banks.raw);
  await click("[data-section='evidence'] summary");
  await shoot("form-subject-banks-top", "[data-explanation-top]");
  await shoot("form-subject-banks-figures", "[data-section='evidence']");
  await shoot("form-subject-banks-background", "[data-section='background']");

  // The SYNTHETIC opened investigation: a procedure, and who says what, with the duty's condition in view.
  await clickText("a", "News");
  await waitFor(`!!document.querySelector(".news-story")`);
  check("the investigation's headline opens its internal story page",
    await clickText(".news-story-title a", WIRE) &&
    await waitFor(`!!document.querySelector(".news-story-page [data-explanation-top]") && /^\\/news\\/stories\\/story-/.test(location.pathname)`));
  await click("[data-brief-more] summary");
  await click("[data-section='evidence'] summary");
  await click("[data-section='channels'] summary");
  const wire = await page();
  check("an opened investigation is shown as a procedure, never as a decision or a measure in force",
    wire.stage === "procedure" && /^Procedure opened, no decision on a measure/.test(wire.what), wire.what);
  check("who says what lists each claim with its holder and how it was put",
    wire.claims.length === 2 && wire.claims[0].modality === "asserted" && wire.claims[1].modality === "conditional" &&
    /The publisher's own statement/.test(wire.claims[0].text) && /Only if its condition is met/.test(wire.claims[1].text),
    JSON.stringify(wire.claims));
  check("the duty's condition is shown in its source's own words",
    /Condition, in its own words: “only if increased imports are found to cause serious injury”/.test(wire.claims[1].text),
    wire.claims[1].text);
  check("each fact names the claim it rests on",
    JSON.stringify(wire.factClaims) === JSON.stringify(["asserted", "conditional"]), JSON.stringify(wire.factClaims));
  check("the bounded duty is marked conditional in the figure list and in every text that writes it",
    wire.figureClaims.length === 1 && /^conditional: only if increased imports/.test(wire.figureClaims[0]) &&
    /at most 25% \(conditional: only if increased imports are found to cause serious injury\)/.test(wire.why) &&
    wire.channels.length === 1 && /up to 25% \(conditional: only if increased imports/.test(wire.channels[0]),
    JSON.stringify({ why: wire.why, figures: wire.figureClaims, channel: wire.channels[0] }));
  check("no reference is left unrendered on the investigation's page", !wire.raw);
  check("each alternative says what supports it (econ-explanation-0.6)",
    wire.alternatives.length === 1 && wire.alternatives[0].support === "event_evidence" &&
    wire.alternatives[0].said === "Supported by: Stated in this story's sources.", JSON.stringify(wire.alternatives));
  check("a channel's steps are said not to be a timeline",
    wire.stepsNote === "Each step could follow from the one before; the steps are not a timeline.", wire.stepsNote);
  await shoot("claims-wire-top", "[data-claims]");
  await shoot("claims-wire-figures", "[data-section='evidence']");
  await shoot("consistency-wire-channels", "[data-section='channels']");
  await click("[data-section='alternatives'] summary");
  await shoot("consistency-wire-alternatives", "[data-section='alternatives']");
  check("a brief that records no claims shows no claims block (the bank survey)", banks.claims.length === 0 &&
    banks.factClaims.length === 0 && banks.figureClaims.length === 0);

  // Copies of real records, when named: what each real story page shows (only read).
  const real = [];
  for (const storyId of realStories) {
    await open(`/news/stories/${storyId}`);
    await waitFor(`!!document.querySelector(".news-story-page .news-brief")`);
    const shown = await page();
    real.push({ story_id: storyId, ...shown });
    await click("[data-section='evidence'] summary");
    await click("[data-section='channels'] summary");
    await shoot(`fidelity-real-${storyId}-top`, "[data-explanation-top]");
    await shoot(`fidelity-real-${storyId}-figures`, "[data-section='evidence']");
    await shoot(`fidelity-real-${storyId}-channels`, "[data-section='channels']");
    check(`the copied story ${storyId} shows no unrendered reference`, !shown.raw);
    if (shown.explained) {
      check(`the copied story ${storyId} says whether its evidence form was recorded`,
        shown.evidence === "recorded" || (shown.evidence === "not-recorded" && /not recorded/.test(shown.evidenceText)),
        shown.evidenceText);
    } else {  // No explanation (insufficient evidence, or none prepared): the reader is told why, never shown one.
      check(`the copied story ${storyId}, without an explanation, says why`,
        shown.evidence === null && shown.explanationNote.length > 0, shown.explanationNote);
    }
    check(`the copied story ${storyId}, saved before 0.6, shows its alternatives as they were saved`,
      shown.alternatives.every((row) => row.support === null), JSON.stringify(shown.alternatives));
    // Who says what is shown exactly when the published version records it (the v7 publication does, since 29 October).
    const recorded = await evaluate(`fetch("/api/user/news/stories/${storyId}").then((r) => r.json())
      .then((body) => body.story.brief?.claims?.claims?.length ?? 0)`);
    if (recorded > 0) {
      check(`the copied story ${storyId} shows each claim it records, and facts that name them`,
        shown.claims.length === recorded && shown.factClaims.length > 0, JSON.stringify(shown.claims));
    } else {
      check(`the copied story ${storyId}, which records no claims, shows none and no claim label`,
        shown.claims.length === 0 && shown.factClaims.length === 0 && shown.figureClaims.length === 0);
    }
  }
  if (records) writeFileSync(join(shots ?? root, "fidelity-real-pages.json"), JSON.stringify(real, null, 1));

  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  await clickText("a", "News");
  check("the page reads at phone width without horizontal scrolling",
    await evaluate(`document.documentElement.scrollWidth <= window.innerWidth + 1`));
  check("reading sent only GETs: no write, no feed request and no provider send",
    sent.filter((row) => row.method !== "GET").length === before.writes && feedRequests() === before.feeds &&
    providerSends() === before.sends, JSON.stringify(sent.filter((row) => row.method !== "GET")));
  check("no request left this server and no page error occurred", outside.length === 0 && pageErrors.length === 0,
    JSON.stringify({ outside, pageErrors }));
  check("nothing was kept in browser storage", await evaluate("localStorage.length === 0 && sessionStorage.length === 0"));
} catch (error) {
  console.error(error);
  results.push(false);
} finally {
  for (const child of children.reverse()) child.kill();
  await sleep(500);
  try { rmSync(root, { recursive: true, force: true }); } catch { /* Chrome may still hold its profile briefly. */ }
}
const passed = results.filter(Boolean).length;
console.log(`${passed}/${results.length} checks passed`);
process.exit(passed === results.length && results.length > 0 ? 0 : 1);
