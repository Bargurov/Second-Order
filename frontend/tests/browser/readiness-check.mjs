// Browser check of the "Before a freeze: readiness" card on the Hypotheses page, against tests/review_browser_server.py
// serving a new, empty folder with --assessment (SYNTHETIC kept H.15 packages, a store with two imported H.15 baselines
// and a mocked FRED snapshot; the server's clock starts at Monday 5 October 2026, 10 a.m. in New York). It checks:
// - the card opens on today's date in New York on the server's clock (2026-10-05) and says nothing can be frozen, with
//   the session it needs (Friday 2 October), what is held now and each row's next explicit action;
// - choosing a publication date asks the server for that date only and shows its reply exactly: 2026-09-29 is ready to
//   freeze on the two H.15 yields while FRED still needs a baseline; 2026-09-08 needs Friday 4 September (the weekend and
//   Labor Day are not sessions); 2026-10-06 waits for Monday's session to end;
// - connected observables and registry concepts are listed apart: the four yields with a provider, each with its
//   status, and the registry concepts with no provider, never with a freeze status or a next step;
// - freeze readiness is not research use: even where a freeze is ready, the research answer says research use is not
//   possible (INCLUSION.md), the freeze answer speaks of a prospective showcase hypothesis, every reply row is
//   ineligible for research, and the card offers no control but Check;
// - checking only reads: only GETs, the served folder (store, packages, journal) is byte for byte unchanged, every reply
//   says it called no provider and wrote nothing, nothing outside the local server is requested, and no page error;
// - a 375 px wide screen without sideways scrolling.
//
//   cd frontend; npm run build; npm run test:browser:readiness
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const python = process.env.SECOND_ORDER_PYTHON ?? "python";
const chromePath = [process.env.SECOND_ORDER_CHROME, "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
  "/usr/bin/chromium-browser"].find((path) => path && existsSync(path));
if (!chromePath) throw new Error("Chrome was not found; set SECOND_ORDER_CHROME to its executable.");
if (!existsSync(join(repo, "frontend/dist/index.html"))) throw new Error("Build the client first: npm run build");

const YIELDS = ["yield:ust2y_cmt", "yield:ust10y_cmt", "yield:ust2y_cmt_h15", "yield:ust10y_cmt_h15"];
const H15 = ["yield:ust2y_cmt_h15", "yield:ust10y_cmt_h15"];
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => { const { port } = server.address(); server.close(() => done(port)); });
});
const root = mkdtempSync(join(tmpdir(), "second-order-readiness-check-"));
const served = join(root, "served");
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
/** Every file below the served folder with its hash, to show that checking writes nothing. */
const tree = (folder) => {
  const found = {};
  const walk = (path) => {
    for (const name of readdirSync(path)) {
      const full = join(path, name);
      if (statSync(full).isDirectory()) walk(full);
      else found[relative(folder, full)] = createHash("sha256").update(readFileSync(full)).digest("hex");
    }
  };
  walk(folder);
  return found;
};
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

async function startServer(port) {
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    "--assessment"], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  for (let i = 0; i < 300; i++) {
    try { if ((await fetch(`http://127.0.0.1:${port}/api/lifecycle`)).ok) return server; } catch { /* starting */ }
    await sleep(200);
  }
  throw new Error("The review server did not start.");
}

try {
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  await startServer(port);
  const before = tree(served);
  check("the served folder holds a store and kept packages to read", Object.keys(before).some((name) =>
    name.startsWith("store")) && Object.keys(before).some((name) => name.startsWith("market-store")));
  /** The server's own reply for a date, read directly (a GET), to compare the page with. */
  const reply = async (published) =>
    (await fetch(`${base}/api/lifecycle/readiness${published ? `?published=${published}` : ""}`)).json();

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
  const requests = [];
  const errors = [];
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else if (message.method === "Network.requestWillBeSent") {
      requests.push({ method: message.params.request.method, url: message.params.request.url });
    } else if (message.method === "Runtime.exceptionThrown") {
      errors.push(message.params.exceptionDetails.text);
    } else if (message.method === "Log.entryAdded" && message.params.entry.level === "error") {
      errors.push(`${message.params.entry.text} ${message.params.entry.url ?? ""}`);
    }
  });
  const send = (method, params = {}) => new Promise((done, fail) => {
    const id = ++counter;
    pending.set(id, (message) => message.error ? fail(new Error(message.error.message)) : done(message.result));
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) =>
    (await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })).result.value;
  const waitFor = async (expression, timeout = 20000) => {
    for (const start = Date.now(); Date.now() - start < timeout; await sleep(80)) {
      if (await evaluate(expression)) return true;
    }
    return false;
  };
  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("Log.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete'");
  };
  /** What the card shows: its date, the three answers kept apart, both lists and the technical line. */
  const card = () => evaluate(`(() => {
    const result = document.querySelector(".hypotheses-readiness .readiness-result");
    if (!result) return null;
    const rows = (selector) => [...result.querySelectorAll(selector)].map((row) => ({
      id: row.dataset.observable, status: row.dataset.status,
      label: row.querySelector(".readiness-status")?.textContent ?? null,
      next: row.querySelector(".readiness-next")?.textContent ?? null, text: row.textContent }));
    const lists = [...result.querySelectorAll("ul.readiness-rows")];
    return {
      published: result.dataset.published,
      freeze: result.querySelector('[data-answer="freeze"]')?.textContent ?? null,
      outcomes: result.querySelector('[data-answer="outcomes"]')?.textContent ?? null,
      research: result.querySelector('[data-answer="research"]')?.textContent ?? null,
      headings: [...result.querySelectorAll("h3")].map((item) => item.textContent),
      connected: rows("ul.readiness-rows:not(.readiness-concepts) > li"),
      concepts: rows("ul.readiness-concepts > li"),
      lists: lists.length,
      technical: result.querySelector(".readiness-technical")?.textContent ?? "",
      controls: [...document.querySelectorAll(".hypotheses-readiness button, .hypotheses-readiness input, " +
        ".hypotheses-readiness select, .hypotheses-readiness textarea, .hypotheses-readiness a")]
        .map((item) => item.tagName === "INPUT" ? "input:" + item.type : item.tagName.toLowerCase() + ":" +
          item.textContent.trim()),
    };
  })()`);
  /** Choose a publication date in the card's date field, as typing would, and press Check. */
  const choose = async (published) => {
    await evaluate(`(() => {
      const field = document.querySelector(".hypotheses-readiness .readiness-date input");
      const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(field), "value").set;
      setter.call(field, ${JSON.stringify(published)});
      field.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    })()`);
    await evaluate(`document.querySelector(".hypotheses-readiness .readiness-date button[type=submit]").click()`);
    return waitFor(`document.querySelector(".hypotheses-readiness .readiness-result")?.dataset.published === ${
      JSON.stringify(published)}`);
  };
  const readinessCalls = () => requests.filter((row) => row.url.startsWith(`${base}/api/lifecycle/readiness`));

  // 1. The card opens on today's date in New York on the server's clock.
  await open("/hypotheses");
  const opened = await waitFor(`!!document.querySelector(".hypotheses-readiness .readiness-result")`);
  check("the Hypotheses page shows the readiness card with a reply", opened);
  const today = await card();
  const todayReply = await reply("");
  check("with no date chosen, the card reads today in New York on the server's clock (2026-10-05)",
    today?.published === "2026-10-05" && todayReply.published_date === "2026-10-05", today?.published);
  check("the first read asks for today, not a chosen date", readinessCalls().length === 1 &&
    readinessCalls()[0].url === `${base}/api/lifecycle/readiness`, JSON.stringify(readinessCalls()));
  check("not ready: the freeze answer says nothing can be frozen and names the session it needs (2026-10-02)",
    /^Nothing can be frozen prospectively for 2026-10-05 yet\./.test(today?.freeze ?? "") &&
    today.freeze.includes("classifies 2026-10-02") && today.freeze === todayReply.answer.freeze_now, today?.freeze);
  check("not ready: it says what is held now, including the kept package that is not imported",
    /Held now: .*through 2026-09-28.*not imported\./.test(today?.freeze ?? ""), today?.freeze);
  check("not ready: every connected row needs a newer baseline and names its next explicit action",
    today?.connected.length === 4 && today.connected.every((row) => row.status === "needs_baseline" &&
      row.label === "Needs a newer baseline" && /^Next: \S/.test(row.next ?? "")), JSON.stringify(today?.connected));
  check("the technical line names the required session and that it has ended",
    /publication date 2026-10-05 · required session 2026-10-02 \(ended\)/.test(today?.technical ?? ""), today?.technical);

  // 2. Choosing a date: ready on the H.15 yields, FRED apart, and research use still not possible.
  const before0929 = readinessCalls().length;
  check("choosing 2026-09-29 shows that date's reply", await choose("2026-09-29"));
  const ready = await card();
  const readyReply = await reply("2026-09-29");
  const asked = readinessCalls().slice(before0929);
  check("Check asks the server for the chosen date only, once, with a GET",
    asked.length === 1 && asked[0].method === "GET" && asked[0].url === `${base}/api/lifecycle/readiness?published=2026-09-29`,
    JSON.stringify(asked));
  check("the freeze answer is the server's, a prospective showcase freeze on the H.15 baseline",
    ready?.freeze === readyReply.answer.freeze_now &&
    /^You can freeze a prospective showcase hypothesis for 2026-09-29 on the 2-year Treasury yield \(Board H\.15\) and 10-year Treasury yield \(Board H\.15\), with baseline [0-9a-f]{12}\./
      .test(ready?.freeze ?? ""), ready?.freeze);
  const status = (rows, id) => rows?.find((row) => row.id === id);
  check("the two H.15 yields read Ready to freeze, with no next step",
    H15.every((id) => status(ready?.connected, id)?.status === "freeze_ready" &&
      status(ready.connected, id).label === "Ready to freeze" && status(ready.connected, id).next === null),
    JSON.stringify(ready?.connected));
  check("the two FRED yields still need a newer baseline: one provider's readiness is not another's",
    ["yield:ust2y_cmt", "yield:ust10y_cmt"].every((id) => status(ready?.connected, id)?.status === "needs_baseline" &&
      /^Next: /.test(status(ready.connected, id).next ?? "")), JSON.stringify(ready?.connected));
  check("research use is a separate answer: not possible, even where a freeze is ready",
    /^Not possible now\. INCLUSION\.md: research intake has not started\./.test(ready?.research ?? "") &&
    ready.research === readyReply.research.plain && ready.research !== ready.freeze, ready?.research);
  check("no reply row is eligible for research, whatever its freeze status",
    readyReply.observables.every((row) => row.research.eligible === false) &&
    todayReply.observables.every((row) => row.research.eligible === false));
  check("the card offers no control but its date field and Check (nothing to freeze, import or start research)",
    same(ready?.controls, ["input:date", "button:Check"]), JSON.stringify(ready?.controls));
  check("the answers are labelled Freeze now, Outcome data and Research use, kept apart",
    await evaluate(`[...document.querySelectorAll(".hypotheses-readiness .readiness-answer dt")].map((item) =>
      item.textContent).join("|")`) === "Freeze now|Outcome data|Research use");

  // 3. Connected observables and registry concepts are listed apart.
  const replyConnected = readyReply.observables.filter((row) => row.kind !== "concept_only").map((row) => row.observable_id);
  const replyConcepts = readyReply.observables.filter((row) => row.kind === "concept_only").map((row) => row.observable_id);
  check("the connected list holds exactly the four Treasury yields, each with a provider in the reply",
    same(ready?.connected.map((row) => row.id), replyConnected) && same([...replyConnected].sort(), [...YIELDS].sort()) &&
    readyReply.observables.filter((row) => row.kind !== "concept_only").every((row) => row.provider !== null),
    JSON.stringify(ready?.connected.map((row) => row.id)));
  check("the registry concepts are listed apart, exactly the reply's concepts, none with a provider",
    ready?.concepts.length > 0 && same(ready.concepts.map((row) => row.id), replyConcepts) &&
    readyReply.observables.filter((row) => row.kind === "concept_only").every((row) => row.provider === null),
    JSON.stringify(ready?.concepts.map((row) => row.id)));
  check("the two lists share no observable and together hold every reply row",
    ready?.connected.every((row) => !replyConcepts.includes(row.id)) &&
    ready.connected.length + ready.concepts.length === readyReply.observables.length);
  check("a registry concept shows no freeze status and no next step",
    ready?.concepts.every((row) => row.status === "concept_only" && row.label === null && row.next === null &&
      !/Ready to freeze|Needs a newer baseline|Waiting for a session/.test(row.text)), JSON.stringify(ready?.concepts));
  check("the lists sit under their own headings",
    ["Connected observables", "Registry concepts with no provider"].every((heading) => ready?.headings.includes(heading)) &&
    ready.lists === 2, JSON.stringify(ready?.headings));

  // 4. The calendar and a session that has not ended.
  check("choosing 2026-09-08 shows that date's reply", await choose("2026-09-08"));
  const afterHoliday = await card();
  check("2026-09-08 needs Friday 4 September: the weekend and Labor Day are not sessions",
    /publication date 2026-09-08 · required session 2026-09-04 \(ended\)/.test(afterHoliday?.technical ?? ""),
    afterHoliday?.technical);
  check("choosing 2026-10-06 shows that date's reply", await choose("2026-10-06"));
  const waiting = await card();
  const waitingReply = await reply("2026-10-06");
  check("2026-10-06 waits for Monday's session (2026-10-05), which has not ended on the server's clock",
    waiting?.connected.length === 4 && waiting.connected.every((row) => row.status === "waiting_for_session" &&
      row.label === "Waiting for a session to end") &&
    /required session 2026-10-05 \(not ended\)/.test(waiting.technical) && waitingReply.required_session_ended === false,
    JSON.stringify(waiting?.connected));
  check("waiting is not ready: the freeze answer says nothing can be frozen for 2026-10-06",
    /^Nothing can be frozen prospectively for 2026-10-06 yet\./.test(waiting?.freeze ?? ""), waiting?.freeze);

  // 5. Checking only reads.
  check("every reply says it called no provider and wrote nothing", [todayReply, readyReply, waitingReply]
    .every((item) => item.provider_called === false && item.written === false));
  check("the page sent only GETs", requests.every((row) => row.method === "GET"),
    JSON.stringify(requests.filter((row) => row.method !== "GET")));
  check("each Check was one readiness read: four in all, for today and the three chosen dates",
    same(readinessCalls().map((row) => new URL(row.url).searchParams.get("published")),
      [null, "2026-09-29", "2026-09-08", "2026-10-06"]), JSON.stringify(readinessCalls()));
  check("checking wrote nothing: the store, the kept packages and every other served file are unchanged",
    same(tree(served), before));

  // 6. Narrow screen.
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  await open("/hypotheses");
  await waitFor(`!!document.querySelector(".hypotheses-readiness .readiness-result")`);
  await sleep(400);
  const layout = await evaluate(`({ scroll: document.documentElement.scrollWidth,
    width: document.documentElement.clientWidth })`);
  check("narrow screen /hypotheses: no sideways scrolling with the card open", layout.scroll <= layout.width,
    JSON.stringify(layout));

  const outside = requests.filter((row) => !row.url.startsWith(base) && !row.url.startsWith("data:") && row.url !== "about:blank");
  check("nothing outside the local server was requested", outside.length === 0, outside.map((row) => row.url).join(", "));
  const real = errors.filter((entry) => !/favicon\.ico/.test(entry));
  check("no page error", real.length === 0, real.join(" | "));
  check("reading again at the end still wrote nothing", same(tree(served), before));
  ws.close();
} catch (error) {
  check("the readiness browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(300);
  try { rmSync(root, { recursive: true, force: true }); } catch { /* Windows may hold a file briefly. */ }
}
console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
process.exit(results.every(Boolean) ? 0 : 1);
