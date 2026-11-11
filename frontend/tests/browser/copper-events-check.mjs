// Browser check of the copper event chains page (/theses/copper/events), against tests/review_browser_server.py serving
// a new, empty folder with --copper-events synthetic --company-fcx synthetic --metals synthetic --accounts synthetic:
// the SYNTHETIC event-chain world of tests/event_chain_fakes.py (a synthetic "copper" thesis, the SYNTHETIC FCX package,
// the metals sources, the register, the mechanism list and one chain, version 1, pinned), which every page reads from
// the same folders, and SYNTHETIC accounts. The whole check runs in accounts mode, signed in as the synthetic
// administrator, so every save goes through the account binding. Between page loads tests/event_chain_browser_helpers.py
// publishes a chain's next version or edits a cited record, and this script changes one byte of the served 10-Q copy,
// all below the check's own folder. The numbers follow the plan (Task 11):
// 1. the links on the thesis page, the library and the metals page reach the page;
// 2. the header sentence, verbatim;
// 3. the review form: needs revision with notes; a synthetic version 2 answering it; the owner approves; (3.4, run last)
//    a version answering a review that is not on this machine says so in the history;
// 4. the reading form: "Test line: the company expects 85% in 2026, see step 3." gives a current reading;
// 5. a cited record edited (k25-mud-rush-85pct's printed page in the served facts.json copy) while review notes are
//    typed: the save button gives 409; after the page reads again on its own, the notes and the 409 message are still
//    shown and the form cannot send; evidence changed, the pinned and current wording side by side, the approval on an
//    earlier basis; editing clears the message; undone, everything is current again and the review can be sent;
// 6. a retained file changed (one byte of the served 10-Q copy) while a reading is typed: no withheld quote and no
//    unmasked reading line in the text, attributes or accessible names, the reading's figures masked; saving refused,
//    the typed line and the 409 message kept; restored;
// 7. accounts: a POST without the binding gives 428 (one bound to another account 401), and the page always sends it;
// 8. keyboard: Tab reaches both forms and the judgment radios; Space chooses, Enter saves;
// 9. phone widths of 375 and 390 px: the page loads with its chain cards, no sideways scrolling, folds closed and open;
// 10. the only writes are the listed POSTs and their records, the committed tree is unchanged, only local requests are
//     made, and no page error but the deliberate refusals.
//
//   cd frontend; npm run build; npm run test:browser:copper-events
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromePath, freePort, leaks, same, shownScript, sleep, startChrome, tree, where } from "./metals-kit.mjs";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const python = process.env.SECOND_ORDER_PYTHON ?? "python";
if (!chromePath) throw new Error("Chrome was not found; set SECOND_ORDER_CHROME to its executable.");
if (!existsSync(join(repo, "frontend/dist/index.html"))) throw new Error("Build the client first: npm run build");

const API = "/api/theses/copper/event-chains";
const PAGE = "/theses/copper/events";
const CHAIN = "synthetic-world-chain";  // tests/event_chain_fakes.py, WORLD_CHAIN
const PAGE_SENTENCE = "Each chain shows one possible path from a past event to a reason or risk of the copper thesis. "
  + "A chain is not evidence that the event caused anything and is not a forecast. Your reading is your own view.";
const MARK = "General economics, not stated by any source about this event. Drafted by the assistant;";
const SHORT_TERM = "Short term (up to 12 months after the event)";
const LONG_TERM = "Long term (more than 12 months after it)";
const ABSENT_REVIEW = "The version's change names a review that is not on this machine.";
// The assistant's synthetic versions 2 and 3 (tests/event_chain_browser_helpers.py publish-next).
const V2_NOTE = "The second step's label now names the company's expectation as its view";
const V2_LABEL = "An expectation of the company: most output back in the second half";
const V3_NOTE = "Answers a review written on another machine";
// Owner values for this check only (spec section 9: test values, not the owner's reading).
const NOTE = "Label step 2 as the company's expectation, not a result.";
const APPROVAL_NOTE = "Checked each step against its source.";
const HELD_NOTES = "Typed before the record changed; step 2 still reads as the company's view.";
const AFTER_NOTES = "Checked again after the record was put back.";
const LINE = "Test line: the company expects 85% in 2026, see step 3.";
const MASKED_LINE = "Test line: the company expects [figure withheld] in [figure withheld], see step 3.";
const HELD_LINE = "Test line: a second reading typed before the document changed, see step 2.";
const KEYBOARD_LINE = "Test line: a reading written with the keyboard, see step 2.";
const CITED = "k25-mud-rush-85pct";
const TEN_Q = "10q-2026q3";
const ADMIN = { username: "admin", password: "synthetic-admin-pass" };  // tests/account_fakes.py

const root = mkdtempSync(join(tmpdir(), "second-order-copper-events-check-"));
const served = join(root, "served");
const records = join(served, "records");
const research = join(served, "fcx", "research");
const chainFolder = join(served, "theses", "copper", "event-chains", CHAIN);
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(!!ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const q = JSON.stringify;
const readJson = (path) => JSON.parse(readFileSync(path, "utf8"));
/** The files below a folder by their content only (the helper's undo and the restored byte change modification times). */
const contents = (folder) => Object.fromEntries(Object.entries(tree(folder)).map(([path, stamp]) => [path, stamp.split(":")[0]]));
const recordFiles = () => Object.keys(tree(records)).sort();
const recordOf = (kind, number) => readJson(join(records, kind, CHAIN, `${String(number).padStart(6, "0")}.json`));
/** One change below the served folder, by tests/event_chain_browser_helpers.py. */
const helper = (command, ...args) => {
  const run = spawnSync(python, [join(repo, "tests/event_chain_browser_helpers.py"), command, "--root", served, ...args],
    { cwd: repo, encoding: "utf8" });
  if (run.status !== 0) throw new Error(`event_chain_browser_helpers.py ${command} failed: ${run.stderr}`);
};

try {
  const committedBefore = { content: tree(join(repo, "content")), research: tree(join(repo, "research")) };
  const repoRecords = existsSync(join(repo, "data", "event-chains"));
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  children.push(spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    "--copper-events", "synthetic", "--company-fcx", "synthetic", "--metals", "synthetic", "--accounts", "synthetic"],
  { cwd: repo, stdio: ["ignore", "inherit", "inherit"] }));
  let signedOut = null;
  for (let i = 0; i < 300 && signedOut === null; i++) {
    try { const reply = await fetch(`${base}${API}`); if (reply.status === 401 || reply.ok) signedOut = reply.status; }
    catch { /* starting */ }
    if (signedOut === null) await sleep(200);
  }
  if (signedOut === null) throw new Error("The review server did not start.");
  const servedBefore = contents(served);
  const login = await fetch(`${base}/api/session/login`, { method: "POST", body: JSON.stringify(ADMIN),
    headers: { Origin: base, "Content-Type": "application/json", "X-Second-Order-Session": "1" } });
  const cookie = (login.headers.get("set-cookie") ?? "").split(";")[0];
  const adminId = (await login.json()).user?.user_id;
  if (!cookie || !adminId) throw new Error("The synthetic administrator could not sign in.");
  const view = async () => (await fetch(`${base}${API}`, { headers: { Cookie: cookie } })).json();

  const { send, evaluate, waitFor, press, type, on, requests, errors, close } =
    await startChrome({ profile: join(root, "chrome"), children });
  const sent = new Map();  // DevTools request id -> { method, url, headers, status }
  on(({ method, params }) => {
    if (method === "Network.requestWillBeSent") {
      sent.set(params.requestId, { method: params.request.method, url: params.request.url, headers: params.request.headers,
        status: null });
    } else if (method === "Network.responseReceived" && sent.has(params.requestId)) {
      sent.get(params.requestId).status = params.response.status;
    } else if (method === "Page.javascriptDialogOpening") {  // leaving with typed text asks first; the check leaves
      send("Page.handleJavaScriptDialog", { accept: true }).catch(() => undefined);
    }
  });
  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("Log.enable");
  await send("Emulation.setFocusEmulationEnabled", { enabled: true });
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const [cookieName, cookieValue] = [cookie.slice(0, cookie.indexOf("=")), cookie.slice(cookie.indexOf("=") + 1)];
  await send("Network.setCookie", { name: cookieName, value: cookieValue, url: base });

  const ready = `!!document.querySelector('article[data-page="copper-events"] article[data-chain]')`;
  /** A fresh page (never a same-document change) that satisfies `wait`. */
  const load = async (path = PAGE, wait = ready) => {
    await send("Page.navigate", { url: "about:blank" });
    await waitFor(`location.href === "about:blank"`, 5000);
    await send("Page.navigate", { url: `${base}${path}` });
    return waitFor(`document.readyState === "complete" && (${wait})`, 30000);
  };
  const card = `document.querySelector('article[data-chain=${q(CHAIN)}]')`;
  const inCard = (selector) => `${card}?.querySelector(${q(selector)})`;
  const has = (selector) => evaluate(`!!(${inCard(selector)})`);
  const words = (selector) => evaluate(`(${inCard(selector)})?.textContent.replace(/\\s+/g, " ").trim() ?? null`);
  const all = (selector) => evaluate(`[...(${card}?.querySelectorAll(${q(selector)}) ?? [])]
    .map((e) => e.textContent.replace(/\\s+/g, " ").trim())`);
  const chainState = () => evaluate(`${card}?.dataset.chainState ?? null`);
  const approvalState = () => evaluate(`${inCard("[data-approval]")}?.dataset.approval ?? null`);
  /** Choose a radio of a form by its group's legend and its label: a click, as the page receives one. */
  const choose = (form, legend, label) => evaluate(`(() => {
    const set = [...${card}.querySelectorAll('form[data-form="${form}"] fieldset')]
      .find((f) => f.querySelector("legend")?.textContent.trim() === ${q(legend)});
    const input = set && [...set.querySelectorAll("label")].find((l) => l.textContent.trim() === ${q(label)})?.querySelector("input");
    if (!input) return false; input.click(); return input.checked; })()`);
  /** Type into a form's text box with real text input, replacing what it holds (or adding to it). */
  const write = async (form, value, add = false) => {
    await evaluate(`(() => { const t = ${card}.querySelector('form[data-form="${form}"] textarea'); t.focus();
      if (${add}) t.setSelectionRange(t.value.length, t.value.length); else t.select(); return true; })()`);
    await type(value);
    return evaluate(`${card}.querySelector('form[data-form="${form}"] textarea').value`);
  };
  const submit = (form) => evaluate(`(() => { const b = ${card}.querySelector('form[data-form="${form}"] button[type="submit"]');
    if (!b || b.disabled) return false; b.click(); return true; })()`);
  /** What a form shows now: its text, its message and whether it can send; null when it is not on the page. */
  const formNow = (form) => evaluate(`(() => { const f = ${inCard(`form[data-form="${form}"]`)}; if (!f) return null;
    return { text: f.querySelector("textarea").value, message: f.querySelector('.ec-message[role="status"]')?.textContent ?? null,
      send: !f.querySelector('button[type="submit"]').disabled }; })()`);
  const openFolds = `(() => { document.querySelectorAll("article[data-page='copper-events'] details").forEach((d) => { d.open = true; }); return true; })()`;
  /** A save sent by the check itself from the page (not by the page's forms), marked by ?probe= in its address. */
  const probe = (name, kind, body, account) => evaluate(`fetch(${q(`${API}/${CHAIN}/${kind}?probe=${name}`)}, { method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json", "X-Second-Order-Event-Chain": "1"${
      account ? `, "X-Second-Order-Account": ${q(account)}` : ""} }, body: ${q(JSON.stringify(body))} })
    .then(async (r) => ({ status: r.status, body: await r.json().catch(() => null) }))`);
  const header = (request, name) => Object.entries(request.headers ?? {}).find(([key]) => key.toLowerCase() === name)?.[1];
  const posts = () => [...sent.values()].filter((r) => r.method === "POST" && new URL(r.url).pathname.startsWith(API));
  const pageSaves = (kind) => posts().filter((r) => r.url.endsWith(`/${CHAIN}/${kind}`));

  // ---------------------------------------------------------------- 1. the links reach the page
  const viaLink = async (path, link, prepare = async () => true) => {
    if (!(await load(path, `!!document.querySelector(${q(link)}) || !!document.querySelector("article[data-metals] h1")`))) return false;
    if (!(await prepare())) return false;
    const clicked = await evaluate(`(() => { const a = document.querySelector(${q(link)}); if (!a) return false; a.click(); return true; })()`);
    return clicked && await waitFor(`location.pathname === ${q(PAGE)} && ${ready}`, 15000);
  };
  check("1. the thesis page's link reaches the page",
    await viaLink("/theses/copper", `[data-tools="events"] a[href="${PAGE}"]`));
  check("1. the library's link beside the copper thesis reaches the page",
    await viaLink("/library", `[data-thesis="copper"] [data-tools="events"] a[href="${PAGE}"]`));
  check("1. the link in copper's Economic transmission fold on the metals page reaches the page",
    await viaLink("/metals?m=copper", `[data-events-link] a[href="${PAGE}"]`, async () => {
      await waitFor(`!!document.getElementById("mt-tab-by-metal")`, 10000);
      await evaluate(`document.getElementById("mt-tab-by-metal").click(); true`);
      await waitFor(`!!document.getElementById("mt-metal-tab-copper")`, 10000);
      await evaluate(`document.getElementById("mt-metal-tab-copper").click(); true`);
      await waitFor(`document.getElementById("mt-metal-panel")?.dataset.metal === "copper"`, 10000);
      return evaluate(`(() => { const d = document.querySelector('#mt-metal-panel details[data-part="transmission"]');
        if (!d) return false; d.open = true; return !!d.querySelector("[data-events-link] a"); })()`);
    }));

  // ---------------------------------------------------------------- 2. the header sentence
  await load();
  check("2. the header sentence is shown verbatim",
    (await evaluate(`document.querySelector('[data-sentence="page"]')?.textContent`)) === PAGE_SENTENCE);
  check("the chain opens available and awaiting review, the mechanism marked as awaiting it, no reading form",
    (await chainState()) === "available" && (await approvalState()) === "awaiting_review"
      && same(await all('[data-mark="mechanism"]'), [`${MARK} awaiting your review`])
      && await has('[data-forms="reading-closed"]') && !(await has('form[data-form="reading"]')),
    q(await all('[data-mark="mechanism"]')));

  // ---------------------------------------------------------------- 3. the review form
  await choose("review", "Your review", "Needs revision");
  await write("review", NOTE);
  await submit("review");
  await waitFor(`!!(${inCard('[data-approval="needs_revision"]')})`, 15000);
  const asked = await words('[data-approval="needs_revision"]');
  check("3.1 needs revision with notes gives \"needs revision\", the notes in the owner's voice",
    (asked ?? "").includes("Needs revision") && (await words('[data-approval="needs_revision"] .ec-own-text')) === NOTE
      && same(await evaluate(`[...${card}.querySelectorAll("[data-review-state]")].map((e) => e.dataset.reviewState)`),
        ["needs_revision"])
      && (await words('[data-forms="reading-closed"]') ?? "").includes("asks for a revision"), asked);
  const first = recordOf("reviews", 1);
  check("3.1 the server saved that review, bound to version 1",
    same(recordFiles(), [`reviews/${CHAIN}/000001.json`]) && first?.status === "needs_revision" && first.notes === NOTE
      && first.basis.chain.version === 1 && first.parent_review_id === null, q(recordFiles()));

  helper("publish-next", "--chain", CHAIN, "--answers", first.review_id, "--note", V2_NOTE, "--label", V2_LABEL);
  const v1 = readJson(join(chainFolder, "v1.json")), v2 = readJson(join(chainFolder, "v2.json"));
  await load();
  const versions = await evaluate(`[...${card}.querySelectorAll("[data-version]")].map((e) => ({ version: e.dataset.version,
    state: e.dataset.versionState, change: e.querySelector(".ec-change")?.textContent ?? null,
    review: e.querySelector("[data-review-note]")?.textContent ?? null }))`);
  check("3.2 the synthetic version 2, answering that review, shows as awaiting review",
    v2.change.answers_review === first.review_id && (await words(".ec-meta") ?? "").startsWith("Version 2,")
      && (await approvalState()) === "awaiting_review" && (await words('[data-step="2"] strong')) === V2_LABEL,
    q(await words(".ec-meta")));
  check("3.2 the history holds version 1, version 2 with its change note, and the review it answers (on this machine, "
    + "so no absent-review sentence)",
    same(versions, [{ version: "1", state: "earlier", change: null, review: null },
      { version: "2", state: "latest", change: `Change: ${V2_NOTE}`, review: null }])
      && same(await evaluate(`[...${card}.querySelectorAll("[data-review-state]")].map((e) => e.dataset.reviewState)`),
        ["needs_revision"]), q(versions));

  await choose("review", "Your review", "Approved");
  await write("review", APPROVAL_NOTE);
  await submit("review");
  await waitFor(`!!(${inCard('[data-approval="approved"]')})`, 15000);
  const second = recordOf("reviews", 2);
  check("3.3 the owner approves: approved, current, and the mechanism mark names the day",
    (await words('[data-approval="approved"]') ?? "").includes("Approved, current")
      && same(await all('[data-mark="mechanism"]'), [`${MARK} approved by the owner on ${second?.saved_at.slice(0, 10)}`]),
    q(await all('[data-mark="mechanism"]')));
  check("3.3 the approval is saved on version 2, after the review it follows",
    second?.status === "approved" && second.basis.chain.version === 2 && second.parent_review_id === first.review_id
      && second.notes === APPROVAL_NOTE);

  // ---------------------------------------------------------------- 4. the reading form
  await waitFor(`!!(${inCard('form[data-form="reading"]')})`, 10000);
  const picked = [await choose("reading", SHORT_TERM, "Not sure"), await choose("reading", LONG_TERM, "Neither")];
  await write("reading", LINE);
  await submit("reading");
  await waitFor(`!!(${inCard('[data-reading="current"]')})`, 15000);
  const reading = recordOf("readings", 1);
  check("4. the reading line gives a current reading, signed, with both judgments",
    same(picked, [true, true]) && (await words('[data-reading="current"] .ec-own-text')) === LINE
      && same(await all('[data-reading="current"] dd'), ["Not sure", "Neither"])
      && same(await evaluate(`[...${card}.querySelectorAll("[data-reading-state]")].map((e) => e.dataset.readingState)`),
        ["current"]), q(await words('[data-reading="current"]')));
  check("4. the reading is saved on version 2 and its approval",
    reading?.line === LINE && reading.short_term === "not_sure" && reading.long_term === "neither"
      && reading.approval_id === second.review_id && reading.basis.chain.version === 2);

  // ---------------------------------------------------------------- 5. a cited record edited
  const passage = readJson(join(research, "facts.json")).passages.find((item) => item.id === CITED);
  await choose("review", "Your review", "Approved");
  await write("review", HELD_NOTES);  // typed while the record is still as pinned; sent after it changed
  helper("edit-record", "--passage", CITED, "--field", "printed_page", "--value", "24");
  const reasons = (await view()).chains[0].reasons;
  const before409 = recordFiles();
  const clicked = await submit("review");
  // The page reads again on its own after the refusal; nothing holds that reload.
  await waitFor(`${card}?.dataset.chainState === "evidence_changed"`, 15000);
  await sleep(500);
  const keptReview = await formNow("review");
  check("5.2 the save button gives 409 and nothing is written",
    clicked && pageSaves("reviews").at(-1)?.status === 409 && same(recordFiles(), before409),
    q(pageSaves("reviews").at(-1)?.status));
  check("5.2 after the page has read again, the typed notes and the 409 message are still shown; the form cannot send, "
    + "beside the closed reason",
    keptReview?.text === HELD_NOTES && keptReview.message === `The chain is not available: ${reasons.join("; ")}`
      && keptReview.message.includes(`fcx:${CITED}`) && keptReview.send === false && await has('[data-forms="closed"]'),
    q(keptReview));
  check("5.2 the page reads: evidence changed, naming the record",
    (await chainState()) === "evidence_changed" && (await words(".ec-meta") ?? "").includes("Evidence changed")
      && (await all(".ec-reasons li")).some((text) => text.includes(`fcx:${CITED}`)), q(await all(".ec-reasons li")));
  const sides = await evaluate(`(() => { const s = ${inCard('[data-step="2"][data-step-state="record_changed"] [data-sides]')};
    if (!s) return null; const side = (name) => { const e = s.querySelector('[data-side="' + name + '"]'); const r = e.getBoundingClientRect();
      return { quote: e.querySelector(".ec-quote p")?.textContent ?? null, where: e.querySelector(".ec-quote footer")?.textContent ?? null,
        left: r.left, right: r.right, top: r.top }; };
    return { pinned: side("pinned"), current: side("current") }; })()`);
  check("5.2 the pinned and the current wording sit side by side, the pinned and the current place in each",
    sides !== null && sides.pinned.quote === passage.quote && sides.current.quote === passage.quote
      && sides.pinned.where.includes("printed page 23") && sides.current.where.includes("printed page 24")
      && Math.abs(sides.pinned.top - sides.current.top) < 2 && sides.pinned.right <= sides.current.left, q(sides));
  check("5.2 the approval reads approved on an earlier basis, naming what differs",
    (await approvalState()) === "approved_earlier_basis"
      && (await words('[data-approval="approved_earlier_basis"]') ?? "").includes("Approved on an earlier basis")
      && (await words('[data-approval="approved_earlier_basis"]') ?? "").includes(`fcx:${CITED}`));
  check("5.2 the reading is shown on an earlier basis, its line in full, and no reading form is offered",
    await has('[data-reading="none"]') && same(await all('[data-reading-state="earlier_basis"] .ec-own-text'), [LINE])
      && !(await has('form[data-form="reading"]')));
  await write("review", " Still holds.", true);
  const editedReview = await formNow("review");
  check("5.2 editing the notes clears the message and keeps the text; the form still cannot send",
    editedReview?.text === `${HELD_NOTES} Still holds.` && editedReview.message === null && editedReview.send === false,
    q(editedReview));
  helper("undo-record");
  await load();
  check("5.3 the edit undone: available, approved, the reading current again, nothing written in between",
    (await chainState()) === "available" && (await approvalState()) === "approved"
      && (await words('[data-reading="current"] .ec-own-text')) === LINE && !(await has("[data-sides]"))
      && (await all(".ec-reasons li")).length === 0 && same(recordFiles(), before409));
  await choose("review", "Your review", "Approved");
  await write("review", AFTER_NOTES);
  const sendable = (await formNow("review"))?.send === true;
  await submit("review");
  await waitFor(`(${inCard('[data-approval="approved"] .ec-own-text')})?.textContent === ${q(AFTER_NOTES)}`, 15000);
  const third = recordOf("reviews", 3);
  check("5.3 and the review can be sent: a new approval, so the earlier reading rests on the earlier approval",
    sendable && third?.status === "approved" && third.parent_review_id === second.review_id && third.notes === AFTER_NOTES
      && (await approvalState()) === "approved" && await has('[data-reading="none"]')
      && same(await all('[data-reading-state="earlier_basis"] .ec-own-text'), [LINE]), q(third));

  // ---------------------------------------------------------------- 6. a retained file changed
  const entry = readJson(join(research, "sources.json")).sources.find((item) => item.id === TEN_Q);
  const document = join(served, "fcx", "sources", entry.folder, entry.name);
  const withheldQuotes = [...new Set([v1, v2].flatMap((version) => version.evidence.passages)
    .filter((item) => item.source === TEN_Q).map((item) => item.quote))];
  const shownNow = shownScript("[data-none]", `article[data-page="copper-events"]`);
  const axNames = async () => (await send("Accessibility.getFullAXTree")).nodes
    .map((node) => String(node.name?.value ?? "")).filter((name) => name !== "");
  // What the byte change must withhold: the 10-Q's quote, and the reading line with its figures unmasked.
  const withheldValues = [...withheldQuotes, LINE];
  await evaluate(openFolds);
  const control = leaks(await evaluate(shownNow), withheldValues);
  const controlNames = leaks({ text: (await axNames()).join("\n"), attributes: [] }, withheldValues);
  check("6. while the 10-Q verifies, the same scan finds its quote and the unmasked reading line on the page, and the "
    + "line among the accessible names (the scan can see them)",
    withheldQuotes.length === 1 && same(control, withheldValues) && controlNames.includes(LINE),
    q({ withheldQuotes, control, controlNames }));
  await choose("reading", SHORT_TERM, "Neither");
  await choose("reading", LONG_TERM, "Not sure");
  await write("reading", HELD_LINE);  // typed while the 10-Q still verifies; sent after one byte of it changed
  const original = readFileSync(document);
  const flipped = Buffer.from(original);
  flipped[100] ^= 1;
  writeFileSync(document, flipped);
  const beforeReading409 = recordFiles();
  const sentReading = await submit("reading");
  await waitFor(`${card}?.dataset.chainState === "needs_revalidation"`, 15000);  // read again on its own
  await sleep(500);
  const keptReading = await formNow("reading");
  const readingReasons = (await view()).chains[0].reasons;
  await evaluate(openFolds);
  await sleep(200);
  const shown = await evaluate(shownNow);
  const names = await axNames();
  const found = leaks(shown, withheldValues);
  const foundNames = leaks({ text: names.join("\n"), attributes: [] }, withheldValues);
  check("6.2 with one byte of the 10-Q changed, no withheld quote and no unmasked reading line is in the text, "
    + "attributes or accessible names",
    (await chainState()) === "needs_revalidation" && found.length === 0 && foundNames.length === 0 && names.length > 50,
    [...found.map((value) => where(value, shown)), ...foundNames].join(" | "));
  check("6.2 the 10-Q step shows no quote and says why it is withheld",
    !(await has('[data-step="3"] .ec-quote')) && /10-Q/.test(await words('[data-step="3"] .ec-withheld') ?? ""),
    await words('[data-step="3"]'));
  const ownTexts = await evaluate(`[...document.querySelectorAll("article[data-page='copper-events'] .ec-own-text")]
    .map((e) => e.textContent)`);
  check("6.2 the reading line reads with its figures withheld",
    same(await all('[data-reading-state="earlier_basis"] .ec-own-text'), [MASKED_LINE]), q(ownTexts));
  check("6.2 no figure in the owner's words is shown unmasked (a step reference is not a figure)",
    ownTexts.length >= 3 && ownTexts.every((value) => !/\d/.test(value.replace(/\bsteps?\s+\d+/gi, ""))), q(ownTexts));
  check("6.3 the reading's save button gives 409 and nothing is written",
    sentReading && pageSaves("readings").at(-1)?.status === 409 && same(recordFiles(), beforeReading409),
    q(pageSaves("readings").at(-1)?.status));
  check("6.3 after the page has read again, the typed line and the 409 message stay, and no form can send",
    keptReading?.text === HELD_LINE && keptReading.message === `The chain is not available: ${readingReasons.join("; ")}`
      && keptReading.send === false && await has('[data-forms="closed"]') && !(await has('form[data-form="review"]')),
    q(keptReading));
  const stale = (await view()).chains[0].binding;
  const beforeRefused = recordFiles();
  const refusedReview = await probe("409-review", "reviews", { parent_review_id: stale.parent_review_id,
    chain_sha256: stale.chain_sha256, status: "approved", notes: "A save the server must refuse." }, adminId);
  const refusedReading = await probe("409-reading", "readings", { parent_reading_id: stale.parent_reading_id,
    chain_sha256: stale.chain_sha256, approval_id: third.review_id, short_term: "neither", long_term: "neither",
    line: "Test line: a save the server must refuse, see step 2." }, adminId);
  const flat = (reply) => reply.status === 409 && same(Object.keys(reply.body ?? {}).sort(), ["detail", "latest"]);
  check("6.3 the server answers 409 to a review and a reading sent on the binding the page had before the change",
    flat(refusedReview) && flat(refusedReading) && refusedReview.body.detail.includes(`fcx:${TEN_Q}`)
      && refusedReading.body.detail.includes(`fcx:${TEN_Q}`), q([refusedReview, refusedReading]));
  check("6.3 nothing was written", same(recordFiles(), beforeRefused));
  writeFileSync(document, original);
  await load();
  check("6.4 the file restored: available, approved, and the reading line shows its figures again",
    (await chainState()) === "available" && (await approvalState()) === "approved"
      && same(await all('[data-reading-state="earlier_basis"] .ec-own-text'), [LINE]));

  // ---------------------------------------------------------------- 7. accounts mode
  const binding = (await view()).chains[0].binding;
  const body = { parent_review_id: binding.parent_review_id, chain_sha256: binding.chain_sha256, status: "approved",
    notes: "A save the server must refuse." };
  const beforeUnbound = recordFiles();
  const unbound = await probe("428", "reviews", body, null);
  const otherAccount = await probe("401", "reviews", body, "not-this-account");
  check("7. signed out, the chains are not served (401)", signedOut === 401, String(signedOut));
  check("7. a POST without the binding gives 428 (account_binding_required), one bound to another account 401",
    unbound.status === 428 && unbound.body?.code === "account_binding_required"
      && otherAccount.status === 401 && otherAccount.body?.code === "account_changed", q([unbound, otherAccount]));
  check("7. neither wrote anything", same(recordFiles(), beforeUnbound));

  // ---------------------------------------------------------------- 8. keyboard
  await load();
  await waitFor(`!!(${inCard('form[data-form="reading"]')}) && !!(${inCard('form[data-form="review"]')})`, 10000);
  const focusNow = () => evaluate(`(() => { const e = document.activeElement; if (!e || e === document.body) return null;
    return { tag: e.tagName.toLowerCase(), type: e.type ?? "", name: e.name ?? "", form: e.closest("form")?.dataset.form ?? null,
      checked: e.checked ?? null, label: e.closest("label")?.textContent.trim() ?? null,
      text: (e.textContent ?? "").trim().slice(0, 40) }; })()`);
  const tabUntil = async (test, limit = 150) => {
    for (let count = 0; count < limit; count++) {
      await press("Tab");
      const now = await focusNow();
      if (now && test(now)) return now;
    }
    return null;
  };
  await evaluate(`document.querySelector('article[data-page="copper-events"] .library-crumbs a').focus(); true`);
  const reviewRadio = await tabUntil((f) => f.form === "review" && f.type === "radio");
  await press("Space");
  const reviewChosen = await focusNow();
  check("8. Tab reaches the review form's radios, and Space chooses one",
    reviewRadio?.label === "Approved" && reviewChosen?.checked === true && reviewChosen.label === "Approved", q(reviewChosen));
  const shortRadio = await tabUntil((f) => f.form === "reading" && f.type === "radio" && f.name.startsWith("short-"));
  await press("Space");
  const shortChosen = await focusNow();
  const longRadio = await tabUntil((f) => f.form === "reading" && f.type === "radio" && f.name.startsWith("long-"));
  await press("Space");
  const longChosen = await focusNow();
  check("8. Tab reaches the reading form's two judgment groups, and Space chooses in each",
    shortRadio?.label === "Supports the thesis" && shortChosen?.checked === true
      && longRadio?.label === "Supports the thesis" && longChosen?.checked === true, q([shortChosen, longChosen]));
  const lineBox = await tabUntil((f) => f.form === "reading" && f.tag === "textarea");
  if (lineBox) await type(KEYBOARD_LINE);
  const saveButton = await tabUntil((f) => f.form === "reading" && f.tag === "button");
  await press("Enter");
  await waitFor(`(${inCard('[data-reading="current"] .ec-own-text')})?.textContent === ${q(KEYBOARD_LINE)}`, 15000);
  const keyboardReading = existsSync(join(records, "readings", CHAIN, "000002.json")) ? recordOf("readings", 2) : null;
  check("8. Tab reaches the line and the save button, and Enter saves the reading",
    lineBox !== null && saveButton?.text === "Save reading"
      && (await words('[data-reading="current"] .ec-own-text')) === KEYBOARD_LINE
      && keyboardReading?.short_term === "supports" && keyboardReading?.long_term === "supports"
      && keyboardReading?.parent_reading_id === reading.reading_id && keyboardReading?.approval_id === third.review_id,
    q(saveButton));

  // ---------------------------------------------------------------- 9. phone widths
  for (const [width, height] of [[375, 812], [390, 844]]) {
    await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 2, mobile: true });
    const loaded = await load();
    await sleep(300);
    const cards = await evaluate(
      `document.querySelectorAll('article[data-page="copper-events"] article[data-chain]').length`);
    const overflow = `document.documentElement.scrollWidth - document.documentElement.clientWidth`;
    const folded = await evaluate(overflow);
    await evaluate(openFolds);
    await sleep(200);
    const opened = await evaluate(overflow);
    check(`9. at ${width} px the page loads with its chain card and does not scroll sideways, with its folds closed `
      + "and open", loaded === true && cards === 1 && folded <= 0 && opened <= 0,
    `loaded ${loaded}, ${cards} cards, ${folded} / ${opened}`);
  }
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  // ---------------------------------------------------------------- 3.4, run last: it publishes a newer version
  helper("publish-next", "--chain", CHAIN, "--answers", "f".repeat(64), "--note", V3_NOTE);
  await load();
  const later = await evaluate(`[...${card}.querySelectorAll("[data-version]")].map((e) => ({ version: e.dataset.version,
    change: e.querySelector(".ec-change")?.textContent ?? null, review: e.querySelector("[data-review-note]")?.textContent ?? null }))`);
  check("3.4 a version answering a review that is not on this machine says so beside its change note",
    same(later, [{ version: "1", change: null, review: null }, { version: "2", change: `Change: ${V2_NOTE}`, review: null },
      { version: "3", change: `Change: ${V3_NOTE}`, review: ABSENT_REVIEW }]) && (await approvalState()) === "awaiting_review",
    q(later));

  // ---------------------------------------------------------------- 10. writes, the tree, requests and errors
  const pagePosts = posts().filter((r) => !new URL(r.url).search.includes("probe="));
  const probes = posts().filter((r) => new URL(r.url).search.includes("probe="));
  const written = [first, second, third, reading, keyboardReading].filter(Boolean);
  check("7. the page sent the account binding with every one of its saves",
    pagePosts.length === 7 && pagePosts.every((r) => header(r, "x-second-order-account") === adminId
      && header(r, "x-second-order-event-chain") === "1")
      && written.length === 5 && written.every((item) => same(item.account, { user_id: adminId, username: ADMIN.username })),
    q(pagePosts.map((r) => [new URL(r.url).pathname, header(r, "x-second-order-account") ?? null])));
  check("10. the page's writes are the listed saves: three reviews, two readings, and a review and a reading refused "
    + "with 409",
    same(pagePosts.map((r) => [new URL(r.url).pathname.split("/").at(-1), r.status]),
      [["reviews", 201], ["reviews", 201], ["readings", 201], ["reviews", 409], ["reviews", 201], ["readings", 409],
        ["readings", 201]]), q(pagePosts.map((r) => [r.url, r.status])));
  check("10. the check's own refused saves are the four listed ones",
    same(probes.map((r) => [new URL(r.url).searchParams.get("probe"), r.status]),
      [["409-review", 409], ["409-reading", 409], ["428", 428], ["401", 401]]), q(probes.map((r) => [r.url, r.status])));
  const writes = requests.filter((r) => r.method !== "GET" && r.method !== "HEAD");
  check("10. nothing else was sent but GET requests", writes.length === pagePosts.length + probes.length,
    q(writes.map((r) => `${r.method} ${r.url}`)));
  check("10. the server wrote only the five records",
    same(recordFiles(), [`readings/${CHAIN}/000001.json`, `readings/${CHAIN}/000002.json`, `reviews/${CHAIN}/000001.json`,
      `reviews/${CHAIN}/000002.json`, `reviews/${CHAIN}/000003.json`]), q(recordFiles()));
  const servedAfter = contents(served);
  const changed = [...new Set([...Object.keys(servedBefore), ...Object.keys(servedAfter)])]
    .filter((path) => servedBefore[path] !== servedAfter[path]).sort();
  const published = ["index.json", "v2.json", "v3.json"].map((name) => `theses/copper/event-chains/${CHAIN}/${name}`);
  const allowed = (path) => path.startsWith("records/") || path.startsWith("accounts/") || published.includes(path);
  check("10. below the served folder only the records, the session store and the published versions 2 and 3 changed; "
    + "the edited record and the changed byte are back", changed.every(allowed) && published.every((path) => changed.includes(path))
      && servedBefore[`theses/copper/event-chains/${CHAIN}/v1.json`] === servedAfter[`theses/copper/event-chains/${CHAIN}/v1.json`],
    q(changed.filter((path) => !allowed(path))));
  check("10. the committed content and research are unchanged, and nothing went to the repository's data folder",
    same(tree(join(repo, "content")), committedBefore.content) && same(tree(join(repo, "research")), committedBefore.research)
      && existsSync(join(repo, "data", "event-chains")) === repoRecords);
  const outside = requests.filter((r) => !r.url.startsWith(base) && !r.url.startsWith("data:") && !r.url.startsWith("about:"));
  check("10. only requests to the local server", outside.length === 0, outside.map((r) => r.url).join());
  // The browser logs the deliberate refusals above (the 409s, the 428 and the 401) as failed loads of exactly those
  // addresses; each is attributed to its URL and set aside, as is the favicon probe.
  const deliberate = (e) => /status of (409|428|401)/.test(e.text) && e.url.includes(`${API}/${CHAIN}/`);
  const real = errors.filter((e) => !e.url.endsWith("/favicon.ico") && !deliberate(e));
  check("10. no page errors", real.length === 0, real.map((e) => `${e.text} @ ${e.url}`).join(" | "));
  close();
} catch (error) {
  check("the check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(300);
  try { rmSync(root, { recursive: true, force: true }); } catch { /* Windows may hold a file briefly */ }
  const failed = results.filter((ok) => !ok).length;
  console.log(`\n${results.length - failed}/${results.length} checks passed`);
  process.exitCode = failed ? 1 : 0;
}
