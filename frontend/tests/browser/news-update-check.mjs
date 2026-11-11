// Browser check of an operator's update run on the BUILT Admin and Client, in one headless Chrome against the REAL
// server (tests/news_desk_server.py --simulated-drafting --later-feeds): SYNTHETIC accounts, publishers and a curated
// newsroom set up an hour earlier, whose feeds then answer later entries (a new development of the tariff topic, a
// central bank decision, a copy of the tariff report, an older report not listed before, an entry with no time, a
// revised excerpt) while one feed answers HTTP 503; the paid model is the in-process fake (news_desk_fakes.BriefModel)
// and every request it receives is recorded. Nothing is mocked in the browser and nothing reaches a network.
//
// The journey: the administrator's News desk shows the update plan (what a refresh would request, its limits, that
// planning and reading send nothing) -> a run is started -> its one explicit refresh requests each planned feed once and
// the arrivals are told apart (new, discovered late, no stated time, additional reporting, revised), the failed feed
// listed as a failure -> a model relevance batch is previewed: its saved requests and planning estimate shown, nothing
// sent, and reading the desk again sends nothing -> the approval needs its own checkbox, then sends each request once
// -> a follow-up is related to its ongoing topic -> structural context, a model brief batch (stage 1, the evidence),
// its approval, the stage-2 batch prepared from it (the interpretation and brief), its own approval, and the
// explicit publication -> the run's report: completed, attention, failed -> the reader: the new stories in Latest, Hot
// now and Most covered with their own meanings, the updated story saying what changed and keeping its earlier version,
// the topic's developments in order, headlines opening internal pages, attribution and authorship -> reading sent only
// GETs and the feeds and the model received nothing -> no page error, no outside request.
//
//   cd frontend; npm run build; node tests/browser/news-update-check.mjs
//   (SECOND_ORDER_SCREENSHOTS=<folder> saves viewport captures)
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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

const PASSWORDS = { admin: "synthetic-admin-pass", "reader-a": "synthetic-reader-a" };  // tests/account_fakes.py
const TARIFF = "Synthetic Republic announces 15% tariff on imported steel";
const RATES = "Synthetic central bank holds its policy rate at 4.25%";
const EXTENSION = "Synthetic Republic extends steel tariff to aluminium imports";
const SHIPYARD = "Synthetic shipyard orders fell 12% in September";
const MUSEUM = "Synthetic Republic steel museum opens new wing";
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const root = mkdtempSync(join(tmpdir(), "second-order-news-update-"));
const served = join(root, "served");
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const lines = (file) => existsSync(file) ? readFileSync(file, "utf8").split("\n").filter(Boolean) : [];

try {
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(python, [join(repo, "tests/news_desk_server.py"), "--root", served, "--port", String(port),
    "--simulated-drafting", "--later-feeds"], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  let started = false;
  for (let i = 0; i < 200 && !started; i++) {
    try { started = (await fetch(`${base}/api/session`)).ok; } catch { await sleep(200); }
  }
  if (!started) throw new Error("The server did not start.");
  const feedLog = join(served, "simulated-feeds", "requests.jsonl");
  const modelLog = join(served, "simulated-drafting", "requests.jsonl");
  const feedRequests = () => lines(feedLog);
  const modelRequests = () => lines(modelLog).length;

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
    .find((item) => item.textContent.includes(${JSON.stringify(words)})); if (!e || e.disabled) return false; e.click();
    return true; })()`);
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);
  const exists = (selector) => evaluate(`!!document.querySelector(${JSON.stringify(selector)})`);
  const open = async (address) => {
    await send("Page.navigate", { url: base + address });
    await waitFor("document.readyState === 'complete' && !document.querySelector('.shell-status')");
  };
  const shots = process.env.SECOND_ORDER_SCREENSHOTS;
  const shoot = async (name, selector = null) => {  // Opt-in viewport captures; never a whole tall page.
    if (!shots) return;
    if (selector) await evaluate(`document.querySelector(${JSON.stringify(selector)})?.scrollIntoView({ block: "start" })`);
    await sleep(150);
    const shot = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(shots, `${name}.png`), Buffer.from(shot.data, "base64"));
  };
  const signIn = async (username) => {
    await open("/sign-in");
    await waitFor(`!!document.querySelector('.shell-form input[name="password"]')`);
    await setValue('.shell-form input[name="username"]', username);
    await setValue('.shell-form input[name="password"]', PASSWORDS[username]);
    await click(".shell-form button[type=submit]");
  };
  const report = () => evaluate(`fetch("/api/session").then((reply) => reply.json())
    .then((session) => fetch("/api/admin/news/updates/" + document.querySelector("[data-update-run]").dataset.updateRun,
      { headers: { "X-Second-Order-Account": session.user.user_id } }))
    .then((reply) => reply.json()).then((body) => body.report)`);
  const story = (rows, title) => rows.find((row) => row.title === title);

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  // 1. The plan.
  await signIn("admin");
  await waitFor(`!!document.querySelector(".admin-bar")`, 15000);
  const feedsBefore = feedRequests().length;
  await open("/admin/news");
  check("the desk shows the update plan: what a refresh would request, its limits, and that planning sends nothing",
    await waitFor(`!!document.querySelector("[data-update-plan]")`, 15000) &&
    /A refresh would request \d+ sources, each once with no retry/.test(await text("[data-update-plan]")) &&
    /not a billing ceiling/.test(await text("[data-update-paid]")) &&
    (await evaluate(`document.querySelector("[data-update-paid]").dataset.updatePaid`)) === "true");
  const planned = Number((await text("[data-update-plan]")).match(/request (\d+) sources/)[1]);
  check("opening the desk requested no feed and sent nothing to the model",
    feedRequests().length === feedsBefore && modelRequests() === 0);
  await shoot("update-plan", "[data-update-panel]");

  // 2. A run and its one refresh.
  await setValue("[data-update-panel] .admin-form input", "SYNTHETIC update run");
  await click("[data-update-panel] .admin-effort input");  // Leave out the official feeds (refused here anyway).
  await clickText("[data-update-panel] button", "Start an update run");
  check("starting a run records its cutoff and reference time, and requests nothing",
    await waitFor(`document.querySelector("[data-update-run]")?.dataset.refreshState === "not_started"`, 15000) &&
    feedRequests().length === feedsBefore && /arrivals compared with/.test(await text("[data-update-run]")));
  const publisherPlan = Number((await text("[data-update-run] button")).match(/Refresh (\d+) sources/)?.[1] ?? -1);
  await clickText("[data-update-run] button", "sources and group");
  check("the explicit refresh requests each planned feed once and groups the arrivals",
    await waitFor(`document.querySelector("[data-update-run]")?.dataset.refreshState === "done"`, 20000) &&
    feedRequests().length - feedsBefore === publisherPlan &&
    new Set(feedRequests().slice(feedsBefore).map((row) => JSON.parse(row).url)).size === publisherPlan,
    `${feedRequests().length - feedsBefore} of ${publisherPlan} (plan with official feeds: ${planned})`);
  let shown = await report();
  const kinds = Object.fromEntries(shown.stories.map((row) => [row.title, row.kind]));
  check("arrivals keep newly published, older-discovered, undated, repeated and revised reports apart",
    kinds[RATES] === "new_development" && kinds[EXTENSION] === "new_development" &&
    kinds[SHIPYARD] === "discovered_late" && kinds[TARIFF] === "additional_reporting" &&
    shown.stories.some((row) => row.kind === "time_unknown") && shown.stories.some((row) => row.kind === "revised") &&
    /published after the reference time/.test(await text("[data-update-arrivals]")), JSON.stringify(kinds));
  check("the feed that answered 503 is reported as a failure, not as an editorial judgement",
    shown.failed.some((row) => /synthetic-maker/.test(row)) && /synthetic-maker/.test(await text("[data-update-failed]")));
  await shoot("update-arrivals", "[data-update-arrivals]");

  // 3. Relevance through the model: preview, nothing sent; reading again sends nothing; then one approval.
  await clickText("[data-update-run] button", "Preview a relevance batch");
  check("a model relevance batch shows its saved requests and planning estimate, and sends nothing",
    await waitFor(`/saved requests? not sent: an approval now would send \\d+ \\(planning estimate \\$[0-9.]+, not a billing ceiling\\)/.test(
      document.querySelector("[data-update-paid-line]")?.textContent ?? "")`, 15000) && modelRequests() === 0);
  await open("/admin/news");
  await waitFor(`!!document.querySelector("[data-update-approval]")`, 15000);
  check("reading the desk again sends nothing; the approval needs its own checkbox",
    modelRequests() === 0 &&
    (await evaluate(`document.querySelector("[data-update-approval] button")?.disabled`)) === true);
  await shoot("update-paid-approval", "[data-update-paid-line]");
  shown = await report();
  const relevanceRequests = shown.paid.not_attempted;
  await click("[data-update-approval] .admin-effort input");
  await clickText("[data-update-approval] button", "Send");
  check("approving sends each saved relevance request once",
    await waitFor(`/0 saved requests not sent|1 attempted|attempted:/.test(document.querySelector("[data-update-paid-line]")?.textContent ?? "")`, 20000) &&
    modelRequests() === relevanceRequests, `${modelRequests()} of ${relevanceRequests}`);

  // 4. A follow-up related to its ongoing topic.
  shown = await report();
  const followUp = shown.follow_ups.topics.find((row) => row.title === EXTENSION);
  check("a new development is suggested as a follow-up to its ongoing topic, with the shared names and figures",
    !!followUp && followUp.evidence.figures.includes("15%") &&
    await waitFor(`/may be a further development of/.test(document.querySelector("[data-update-topics]")?.textContent ?? "")`));
  await setValue("[data-update-run] label.admin-form input", "SYNTHETIC: the tariff extended to aluminium");
  await clickText("[data-update-topics] button", "Relate to this topic");
  check("relating it makes it a new development of that topic",
    await waitFor(`document.querySelector('[data-update-story] td') && [...document.querySelectorAll("[data-update-story]")]
      .some((row) => row.dataset.kind === "topic_development")`, 15000));

  // 5. Context, briefs, approval and the explicit publication.
  await clickText("[data-update-run] button", "Gather structural context");
  await waitFor(`/context bundles/.test(document.querySelector("[data-update-report]")?.textContent ?? "")`, 15000);
  // A brief and its explanation take two requests (brief-prompt-9): stage 1's batch, then stage 2's, each approved.
  const approveBriefs = async () => {
    const open = `[...document.querySelectorAll("[data-update-approval]")].find((item) =>
      item.textContent.startsWith("briefs") && item.querySelector(".admin-effort input"))`;
    await evaluate(`${open}.querySelector(".admin-effort input").click()`);
    await sleep(100);
    await evaluate(`${open}.querySelector("button").click()`);
  };
  await clickText("[data-update-run] button", "Preview a brief batch");
  await waitFor(`document.querySelectorAll("[data-update-approval]").length === 2`, 15000);
  const before = modelRequests();
  shown = await report();
  const briefRequests = shown.paid.not_attempted;
  await approveBriefs();
  check("approving the stage-1 brief batch sends each saved request once, saves no version and prepares stage 2",
    await waitFor(`/next stage/.test(document.querySelector("[data-update-next]")?.textContent ?? "")`, 20000) &&
    modelRequests() - before === briefRequests && (await report()).paid.attempted.validated === briefRequests &&
    (await report()).counts.run.published_in_run === 0);
  await clickText("[data-update-run] button", "Preview a brief batch");
  await waitFor(`document.querySelectorAll("[data-update-approval]").length === 3`, 15000);
  check("stage 2 is its own batch: previewing it sends nothing and it awaits its own approval",
    modelRequests() - before === briefRequests && (await report()).paid.not_attempted === briefRequests);
  await approveBriefs();
  check("approving the stage-2 batch sends each saved request once, and publishes nothing by itself",
    await waitFor(`/prepared version/.test(document.querySelector("[data-update-next]")?.textContent ?? "")`, 20000) &&
    modelRequests() - before === 2 * briefRequests && (await report()).counts.run.published_in_run === 0);
  await setValue("[data-update-publication] input", "SYNTHETIC: the update run's drafts checked");
  await clickText("[data-update-publication] button", "Publish the publishable versions");
  check("publication is one explicit recorded action, and the report says what completed",
    await waitFor(`/published in this run/.test(document.querySelector("[data-update-counts]")?.textContent ?? "") &&
      !/ 0 published in this run/.test(document.querySelector("[data-update-counts]")?.textContent ?? "")`, 15000) &&
    /Refreshed at/.test(await text("[data-update-report]")));
  shown = await report();
  check("the report keeps failures apart and leaves nothing to prepare",
    shown.failed.length > 0 && shown.failed.every((row) => !/outside the scope|insufficient/i.test(row)) &&
    shown.stories.every((row) => row.tone !== "todo"), JSON.stringify(shown.stories.map((row) => [row.title, row.tone])));
  await shoot("update-report", "[data-update-report]");

  // The story panel's paid draft: both stages shown, stage 1 approved on its own, stage 2 prepared and not sent.
  const panel = `[...document.querySelectorAll("[data-desk-story]")].find((row) =>
    row.querySelector("summary")?.textContent.includes(${JSON.stringify(MUSEUM)}))`;
  await evaluate(`${panel}.setAttribute("open", "")`);
  const draftsBefore = modelRequests();
  await evaluate(`[...${panel}.querySelectorAll("button")].find((b) => b.textContent.includes("Preview a paid model draft")).click()`);
  const stagesShown = await waitFor(`${panel}.querySelector("[data-drafting-state]")?.dataset.draftingState === "awaiting_stage_1"`, 15000);
  const panelPlan = await evaluate(`${panel}.querySelector("[data-drafting-stages]")?.textContent ?? ""`);
  check("the story panel shows both stages: stage 1's exact estimate, stage 2's planned one, and sends nothing",
    stagesShown && /Stage 1, evidence and figures: planning estimate \$[0-9.]+, at most 6,000/.test(panelPlan) &&
    /Stage 2, interpretation and brief: planned estimate \$[0-9.]+, at most 9,500/.test(panelPlan) &&
    modelRequests() === draftsBefore, panelPlan);
  await evaluate(`${panel}.querySelector("[data-drafting] .admin-effort input").click()`);
  await sleep(100);
  await evaluate(`[...${panel}.querySelectorAll("[data-drafting] button")].find((b) => b.textContent.includes("Send stage 1 once")).click()`);
  const prepared = await waitFor(`${panel}.querySelector("[data-drafting-state]")?.dataset.draftingState === "awaiting_stage_2"`, 15000);
  const panelAfter = await evaluate(`${panel}.querySelector("[data-drafting-stages]")?.textContent ?? ""`);
  check("approving stage 1 in the panel sends it once and shows stage 2's exact request for its own approval",
    prepared && /Stage 1, evidence and figures: .*validated/.test(panelAfter) &&
    /Stage 2, brief from limited evidence: planning estimate/.test(panelAfter) &&
    /retains the checked insufficient-evidence decision and reason/.test(panelAfter) && modelRequests() === draftsBefore + 1 &&
    /Send stage 2 once/.test(await evaluate(`${panel}.querySelector("[data-drafting]")?.textContent ?? ""`)), panelAfter);
  await shoot("update-story-drafting", "[data-drafting]");
  const rates = story(shown.stories, RATES).story_id;
  const tariff = story(shown.stories, TARIFF).story_id;
  const topic = followUp.topic_id;

  // 6. The reader.
  await evaluate(`[...document.querySelectorAll(".admin-bar button")].find((b) => b.textContent.includes("Sign out"))?.click()`);
  await waitFor(`!document.querySelector(".admin-bar")`);
  const feedsRead = feedRequests().length;
  const modelRead = modelRequests();
  const firstRead = sent.length;
  await signIn("reader-a");
  await waitFor(`!!document.querySelector(".news-story")`, 15000);
  await open("/news/latest");
  check("the new stories are discoverable in Latest, their headlines opening internal story pages",
    await waitFor(`!!document.querySelector('.news-story[data-story="${rates}"]')`, 15000) &&
    (await evaluate(`document.querySelector('.news-story[data-story="${rates}"] .news-story-title a')?.getAttribute("href")`)) ===
      `/news/stories/${rates}` &&
    (await evaluate(`document.querySelector('.news-story[data-story="${rates}"] .news-story-title a')?.target ?? ""`)) === "");
  await shoot("reader-latest");
  await open("/news");
  await waitFor(`document.querySelector(".news-stories")?.dataset.view === "hot"`, 15000);
  const hot = await evaluate(`[...document.querySelectorAll(".news-story")].map((row) => row.dataset.story)`);
  const hotRule = await evaluate(`document.querySelector(".news-stories details p")?.textContent ?? ""`);
  await open("/news/coverage");
  await waitFor(`document.querySelector(".news-stories")?.dataset.view === "coverage"`, 15000);
  const covered = await evaluate(`[...document.querySelectorAll(".news-story")].map((row) => row.dataset.story)`);
  const coveredRule = await evaluate(`document.querySelector("[data-coverage-order]")?.textContent ?? ""`);
  check("Hot now and Most covered keep their own meanings: the same eligible stories, ordered by their own rules",
    hot.includes(rates) && [...hot].sort().join() === [...covered].sort().join() && hotRule !== "" &&
    /origin|cover/i.test(coveredRule) && hotRule !== coveredRule, `${hot.length}/${covered.length}`);
  await open(`/news/stories/${tariff}`);
  check("the updated story says when it was updated, what changed, and keeps its earlier version readable",
    await waitFor(`!!document.querySelector("[data-brief-updated]")`, 15000) &&
    /version 2 replaces version 1/.test(await text("[data-brief-updated]")) &&
    /Adds the report/.test(await text("[data-brief-changes]")) &&
    (await exists('[data-earlier-version="1"]')));
  check("its authorship is the model's, unread by an editor, and each source keeps its publisher's attribution",
    /AI-drafted · not read by an editor/.test(await text("[data-authorship-tag]")) &&
    (await evaluate(`[...document.querySelectorAll(".news-source-title a")].every((a) => a.target === "_blank" && a.href.startsWith("https://"))`)));
  await evaluate(`document.querySelector("[data-brief-revisions]")?.setAttribute("open", "")`);
  await shoot("reader-updated-story", "[data-brief-updated]");
  await open(`/news/topics/${topic}`);
  const loaded = await waitFor(`document.querySelectorAll(".news-timeline li").length >= 4`, 15000);
  const timeline = await evaluate(`[...document.querySelectorAll(".news-timeline li")].map((row) => row.dataset.story)`);
  const extension = story(shown.stories, EXTENSION).story_id;
  check("the topic's timeline holds its developments in order, the new one last",
    loaded && timeline.at(-1) === extension && timeline.includes(tariff), JSON.stringify(timeline));
  await shoot("reader-topic", ".news-timeline");
  check("reading sent only GETs, and the feeds and the model received nothing",
    sent.slice(firstRead).filter((row) => row.url.startsWith(`${base}/api/`) && row.method !== "GET" &&
      !row.url.endsWith("/api/session/login")).length === 0 &&
    feedRequests().length === feedsRead && modelRequests() === modelRead);
  check("the browser requested nothing outside the local server", outside.length === 0, outside.join(", "));
  check("no page error", pageErrors.length === 0, pageErrors.join(" | "));
  ws.close();
} catch (error) {
  check("the update journey ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(600);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
