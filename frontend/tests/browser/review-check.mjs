// Browser check of saving human reviews: leaving with unsaved edits, edits made while a save is pending, lost
// replies (including one followed by a newer version from another tab), and a prepared view that changes under
// the page. It drives headless Chrome over the DevTools Protocol
// (no dependencies) against tests/review_browser_server.py, which serves synthetic drafts from a temporary folder.
//
//   cd frontend; npm run build; node tests/browser/review-check.mjs
//
// Chrome is found in the usual places, or set SECOND_ORDER_CHROME. Python is `python`, or SECOND_ORDER_PYTHON.
// Nothing under data/ is read or written, and no model is called. Exits 1 if any check fails.
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const chromePath = [process.env.SECOND_ORDER_CHROME, "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
  "/usr/bin/chromium-browser"].find((path) => path && existsSync(path));
if (!chromePath) throw new Error("Chrome was not found; set SECOND_ORDER_CHROME to its executable.");
if (!existsSync(join(repo, "frontend/dist/index.html"))) throw new Error("Build the client first: npm run build");

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const until = async (condition, timeout = 10000) => {
  for (const start = Date.now(); Date.now() - start < timeout; await sleep(50)) if (condition()) return true;
  return false;
};
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const root = mkdtempSync(join(tmpdir(), "second-order-review-check-"));
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
  const server = spawn(process.env.SECOND_ORDER_PYTHON ?? "python",
    [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port)],
    { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  let drafts = null;
  for (let i = 0; i < 150 && !drafts; i++) {
    try { drafts = (await (await fetch(`${base}/api/drafts`)).json()).drafts; } catch { await sleep(200); }
  }
  if (!drafts) throw new Error("The review server did not start.");
  const draftId = drafts.find((row) => row.case === "draft").id;
  const viewFile = join(served, "prepared-drafts", `draft-${draftId}.json`);
  const reviewFolder = join(served, "reviews", draftId);
  const versions = () => (existsSync(reviewFolder) ? readdirSync(reviewFolder).sort() : []);
  const version = (n) => JSON.parse(readFileSync(join(reviewFolder, `${String(n).padStart(6, "0")}.json`), "utf8"));
  const fileHash = (n) => createHash("sha256")
    .update(readFileSync(join(reviewFolder, `${String(n).padStart(6, "0")}.json`))).digest("hex");
  const viewHash = () => createHash("sha256").update(readFileSync(viewFile)).digest("hex");

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
    pending.set(id, (m) => (m.error ? fail(new Error(`${method}: ${m.error.message}`)) : done(m.result)));
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
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);
  const notes = ".human-review .review-field textarea";
  const notesValue = () => evaluate(`document.querySelector(${JSON.stringify(notes)}).value`);
  const typeAtEnd = async (selector, value) => {
    await evaluate(`(() => { const e = document.querySelector(${JSON.stringify(selector)}); e.focus();
      e.setSelectionRange(e.value.length, e.value.length); })()`);
    await send("Input.insertText", { text: value });
    await sleep(100);
  };
  const click = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
  const saveButton = ".review-save-bar button";
  const saveEnabled = () => evaluate(`!document.querySelector(${JSON.stringify(saveButton)}).disabled`);
  const status = () => text(".review-dirty");
  const path = () => evaluate("location.pathname + location.search");
  const formReady = () => waitFor(`!!document.querySelector(${JSON.stringify(notes)})`);
  // Another tab's save: the same local, same-origin JSON request the page sends, from outside the page.
  const anotherTab = async (parent, note) => {
    const loaded = await fetch(`${base}/api/drafts/${draftId}`);
    const { provenance } = await loaded.json();
    const body = { parent_review_id: parent, status: "needs_revision", notes: note,
      corrections: { summary: null, legs: {} },
      binding: { draft_view_sha256: loaded.headers.get("x-draft-view-sha256"), prompt_hash: provenance.prompt_hash,
                 response_sha256: provenance.response_sha256 } };
    return fetch(`${base}/api/drafts/${draftId}/reviews`, { method: "POST", body: JSON.stringify(body),
      headers: { Origin: base, "Content-Type": "application/json", "X-Second-Order-Review": "1" } });
  };

  // window.confirm answers come from `answer`; leaving the page itself (beforeunload) is always allowed.
  const dialogs = [];
  let answer = false;
  listeners.push((message) => {
    if (message.method !== "Page.javascriptDialogOpening") return;
    const { type, message: question } = message.params;
    if (type !== "beforeunload") dialogs.push(question);
    send("Page.handleJavaScriptDialog", { accept: type === "beforeunload" || answer });
  });
  // Review requests can be held, failed or passed; GETs pass unless `holdGets` is set.
  const posts = [];
  const held = [];
  let postMode = "pass";
  let holdGets = false;
  listeners.push((message) => {
    if (message.method !== "Fetch.requestPaused") return;
    const { requestId, request, responseStatusCode } = message.params;
    const isPost = request.method === "POST";
    if (isPost) posts.push(responseStatusCode === undefined ? "request" : "response");
    if ((isPost && postMode === "hold") || (!isPost && holdGets)) held.push(requestId);
    else if (isPost && postMode === "fail") send("Fetch.failRequest", { requestId, errorReason: "ConnectionReset" });
    else send("Fetch.continueRequest", { requestId });
  });
  const intercept = (stage) =>
    send("Fetch.enable", { patterns: [{ urlPattern: "*/api/drafts/*/reviews", requestStage: stage }] });
  const release = async () => {
    while (held.length) await send("Fetch.continueRequest", { requestId: held.shift() });
  };

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const open = async (address) => {
    await send("Page.navigate", { url: base + address });
    await waitFor("document.readyState === 'complete'");
  };

  // 1. Leaving the Tracker with unsaved edits asks first: links, Back, and re-selecting the same draft.
  await open("/method");
  await waitFor(`!!document.querySelector('a.site-link[href="/"]')`);
  await click('a.site-link[href="/"]');
  await waitFor(`[...document.querySelectorAll(".draft-choice-meta")].some((e) => e.textContent.startsWith("draft ·"))`);
  await evaluate(`[...document.querySelectorAll(".draft-choice")]
    .find((b) => b.querySelector(".draft-choice-meta").textContent.startsWith("draft ·")).click()`);
  check("guard: the draft opens from the Tracker", await formReady() && (await path()) === `/?draft=${draftId}`);
  await typeAtEnd(notes, "Unsaved thought.");
  check("guard: typing marks unsaved changes", (await status()) === "Unsaved changes");
  await click('.draft-choice[aria-pressed="true"]');
  await sleep(200);
  check("guard: re-selecting the same draft asks nothing and keeps the edits",
    dialogs.length === 0 && (await notesValue()) === "Unsaved thought." && (await status()) === "Unsaved changes");
  answer = false;
  await click('a.site-link[href="/method"]');
  await sleep(200);
  check("guard: the Method link asks, even after re-selecting the same draft", dialogs.length === 1,
    `${dialogs.length} dialogs`);
  check("guard: declining keeps the Tracker and the edits",
    (await path()) === `/?draft=${draftId}` && (await notesValue()) === "Unsaved thought.");
  await click("a.case-link");
  await sleep(200);
  check("guard: a Dossier link asks too; declining stays",
    dialogs.length === 2 && (await path()) === `/?draft=${draftId}` && (await notesValue()) === "Unsaved thought.");
  await evaluate("history.back()");
  await until(() => dialogs.length === 3);
  await sleep(300);
  check("guard: Back asks; declining restores the address and keeps the edits",
    dialogs.length === 3 && (await path()) === `/?draft=${draftId}` && (await notesValue()) === "Unsaved thought.",
    `${dialogs.length} dialogs, at ${await path()}`);
  answer = true;
  await evaluate("history.back()");
  check("guard: Back after accepting reaches the Method page", await waitFor(`location.pathname === "/method"
    && !!document.querySelector("h1")`) && dialogs.length === 4, `${dialogs.length} dialogs`);
  await open(`/?draft=${draftId}`);
  await formReady();
  await click('a.site-link[href="/method"]');
  check("guard: with nothing unsaved, links ask nothing", await waitFor(`location.pathname === "/method"`) &&
    dialogs.length === 4);
  check("guard: nothing was saved by any of this", versions().length === 0);
  answer = false;

  // 2. Edits made while a save is pending are kept for the next version.
  await open(`/?draft=${draftId}`);
  await formReady();
  await intercept("Request");
  postMode = "hold";
  await typeAtEnd(notes, "First version.");
  await click(saveButton);
  await until(() => held.length === 1);
  check("pending: the save is held in flight", held.length === 1 && posts.length === 1);
  check("pending: the page says it is saving and offers no second save",
    (await status()).startsWith("Saving") && !(await saveEnabled()));
  await typeAtEnd(notes, " Added while saving.");
  await release();
  check("pending: the save completes as version 1", await waitFor(`document.body.innerText.includes("Saved version 1 at")`));
  check("pending: the edit made while saving is still in the form",
    (await notesValue()) === "First version. Added while saving.");
  check("pending: it is marked unsaved, and the message says so", (await status()) === "Unsaved changes" &&
    (await text(".review-message")).includes("Changes made since are not in it"));
  check("pending: version 1 holds only what was sent", version(1).notes === "First version.");
  postMode = "pass";
  await click(saveButton);
  check("pending: saving again records the kept edit as version 2",
    await waitFor(`document.body.innerText.includes("Saved version 2 at")`) &&
    version(2).notes === "First version. Added while saving." && (await status()) === "All changes saved · version 2");

  // 3. A reply lost after the server saved: not confirmed, edits kept, settled by reading the saved versions.
  await intercept("Response");
  postMode = "fail";
  await typeAtEnd(notes, " Third.");
  const postsBefore = posts.length;
  await click(saveButton);
  check("lost reply: the outcome is reported as not confirmed",
    await waitFor(`document.querySelector(".review-message.is-unconfirmed") !== null`));
  const unconfirmed = await text(".review-message");
  check("lost reply: no claim that nothing was saved", !/nothing was saved/i.test(unconfirmed), unconfirmed);
  check("lost reply: the server did save version 3", versions().length === 3 && version(3).notes.endsWith("Third."));
  check("lost reply: edits are kept and saving waits for a check",
    (await notesValue()).endsWith(" Third.") && !(await saveEnabled()));
  await typeAtEnd(notes, " Fourth.");
  await intercept("Request");
  postMode = "hold";
  await click(".review-message.is-unconfirmed button");
  check("lost reply: the check confirms version 3 from the saved versions",
    await waitFor(`document.body.innerText.includes("Saved version 3 at")`));
  check("lost reply: the check sent nothing again", posts.length === postsBefore + 1 && versions().length === 3);
  check("lost reply: edits made since are kept and unsaved",
    (await notesValue()).endsWith(" Third. Fourth.") && (await status()) === "Unsaved changes");

  // 4. A request lost before the server: the check shows nothing was recorded, and saving resumes.
  postMode = "fail";
  await click(saveButton);
  check("lost request: not confirmed", await waitFor(`document.querySelector(".review-message.is-unconfirmed") !== null`));
  postMode = "hold";
  const postsBeforeCheck = posts.length;
  await click(".review-message.is-unconfirmed button");
  check("lost request: the check finds no new version and says so",
    await waitFor(`document.body.innerText.includes("this save was not recorded")`) && versions().length === 3 &&
    posts.length === postsBeforeCheck);
  check("lost request: edits are kept and saving is offered again",
    (await notesValue()).endsWith(" Fourth.") && (await saveEnabled()));
  postMode = "pass";
  await click(saveButton);
  check("lost request: the next save is version 4", await waitFor(`document.body.innerText.includes("Saved version 4 at")`)
    && version(4).parent_review_id === version(3).review_id);
  await send("Fetch.disable");

  // 5. The prepared view changes on disk while the page shows it: the stale save is refused, nothing is appended.
  const before = [1, 2, 3, 4].map(fileHash);
  const loadedView = viewHash();
  const view = JSON.parse(readFileSync(viewFile, "utf8"));
  view.draft.summary = "A different summary, prepared after the page loaded.";
  writeFileSync(viewFile, JSON.stringify(view));
  await click('.review-status input[type="radio"]:not(:checked)');
  await click(saveButton);
  check("changed view: the save is refused",
    await waitFor(`document.body.innerText.includes("The prepared draft has changed since it was loaded")`));
  check("changed view: nothing was appended", versions().length === 4);
  await click(".review-message.is-failed button");
  check("changed view: reloading shows the new summary",
    await waitFor(`document.querySelector(".draft-summary")?.textContent.startsWith("A different summary")`) &&
    await formReady());
  check("changed view: earlier versions are marked and not applied",
    (await text(".review-earlier")).includes("earlier prepared view") && (await notesValue()) === "" &&
    (await status()) === "Nothing saved for this view yet" &&
    await evaluate(`document.querySelector('.review-status input[type="radio"]').checked`) &&
    await evaluate(`document.querySelectorAll(".review-earlier-tag").length === 4`));
  await typeAtEnd(notes, "Reviewed against the new view.");
  await click(saveButton);
  check("changed view: a new version is bound to the view now served",
    await waitFor(`document.body.innerText.includes("Saved version 5 at")`) &&
    version(5).binding.draft_view_sha256 === viewHash() && viewHash() !== loadedView);
  check("changed view: versions 1 to 4 are byte-identical", [1, 2, 3, 4].map(fileHash).join() === before.join());

  // 6. The view changes between loading it and loading its saved versions: detected, and saving is refused.
  await intercept("Request");
  holdGets = true;
  await open(`/?draft=${draftId}`);
  await until(() => held.length === 1);
  await waitFor(`!!document.querySelector(".draft-summary")`);
  view.draft.summary = "A third summary, prepared while the page was loading.";
  writeFileSync(viewFile, JSON.stringify(view));
  holdGets = false;
  await release();
  check("view vs history: the mismatch is reported",
    await waitFor(`document.body.innerText.includes("The prepared draft has changed since this page loaded it")`));
  await typeAtEnd(notes, "Should not be saved.");
  check("view vs history: saving is not offered", !(await saveEnabled()) && versions().length === 5);
  await click(".human-review > .review-message.is-failed button");
  check("view vs history: reloading clears the mismatch",
    await waitFor(`document.querySelector(".draft-summary")?.textContent.startsWith("A third summary")`) &&
    await formReady() && !(await evaluate(`document.body.innerText.includes("changed since this page loaded it")`)));

  // 7. A lost reply after the server saved, then a newer version from another tab: saved, but not the latest.
  await intercept("Response");
  postMode = "fail";
  await typeAtEnd(notes, "Lost reply, then another tab.");
  await click(saveButton);
  check("superseded: the lost reply is not confirmed",
    await waitFor(`document.querySelector(".review-message.is-unconfirmed") !== null`));
  check("superseded: the server recorded the save as version 6",
    versions().length === 6 && version(6).notes === "Lost reply, then another tab.");
  await typeAtEnd(notes, " Typed after the lost reply.");
  const other = await anotherTab(version(6).review_id, "Saved in another tab.");
  check("superseded: another tab saves version 7 after it", other.status === 201 && versions().length === 7,
    `HTTP ${other.status}`);
  await intercept("Request");
  postMode = "hold";
  const postsBeforeSuperseded = posts.length;
  await click(".review-message.is-unconfirmed button");
  check("superseded: the check reports a recorded save with a newer version",
    await waitFor(`document.querySelector(".review-message.is-superseded") !== null`));
  const superseded = await text(".review-message.is-superseded");
  check("superseded: the message says version 6 was saved and names version 7, never 'Not saved'",
    superseded.startsWith("Saved, but no longer the latest.") && superseded.includes("recorded as version 6") &&
    superseded.includes("newer version 7") && !superseded.includes("Not saved") &&
    !(await evaluate(`document.body.innerText.includes("Not saved")`)), superseded);
  check("superseded: edits made after the lost reply are kept and marked unsaved",
    (await notesValue()) === "Lost reply, then another tab. Typed after the lost reply." &&
    (await status()) === "Unsaved changes" && superseded.includes("Edits made after your save are kept"));
  check("superseded: the check sent nothing and merged nothing",
    posts.length === postsBeforeSuperseded && versions().length === 7 &&
    version(7).notes === "Saved in another tab.");
  postMode = "pass";
  await click(saveButton);
  check("superseded: a save from this outdated page is refused as a conflict",
    await waitFor(`document.querySelector(".review-message.is-failed")?.textContent.startsWith("Not saved.") ?? false`)
    && versions().length === 7);
  check("superseded: the edits survive the refusal", (await notesValue()).endsWith(" Typed after the lost reply."));
  await click(".review-message.is-failed button");
  check("superseded: the explicit reload shows version 7 as the latest",
    await waitFor(`document.querySelector(".review-dirty")?.textContent === "All changes saved · version 7"`) &&
    (await notesValue()) === "Saved in another tab.");
  await send("Fetch.disable");
  ws.close();
} catch (error) {
  check("the browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(500);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
