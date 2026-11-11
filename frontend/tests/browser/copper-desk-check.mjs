// Browser check of the copper desk (/copper) and a publication comparison (/copper/comparisons/:id), against
// tests/review_browser_server.py serving a new, empty folder with --copper-events synthetic --company-fcx synthetic
// --metals synthetic --accounts synthetic: the SYNTHETIC event-chain world of tests/event_chain_fakes.py, which also
// holds one SYNTHETIC comparison (world_comparison, version 1, pinned), and SYNTHETIC accounts. The whole check runs in
// accounts mode, signed in as the synthetic administrator, so every save goes through the account binding. The owner's
// notes go to research-notes/ below the check's own folder. Every note text is a marked test value, never a view of
// the owner's. The numbers:
// 1. the top bar's "Copper" link reaches the desk; the existing copper pages keep their own section;
// 2. the desk's header sentence, verbatim;
// 3. the five page links with their lines, as the view serves them;
// 4. each of the five existing copper pages links back to the desk from its crumbs, beside the crumb it already had;
// 5. the comparison link opens the comparison page; an unknown id and a malformed one say so;
// 6. both lines of each row with their places, side by side; the row's fixed sentence; exactly two quotes a row and
//    nothing that derives a change between them; the retained prices with their periods and the prices text;
// 7. a note with an expectation, a check-by date and a question: exactly one file, saved at the server's time, with
//    the typed text; it shows on the comparison page and on the desk with the personal mark, the hindsight sentence,
//    "Not yet checked" and its question under "Open questions";
// 8. keyboard: Tab reaches the form; Space ticks "follows my latest note" and saves on the comparison page, Enter
//    saves on the desk; a followed note's question is no longer open;
// 9. one byte of the served 10-Q copy changed while a note is typed: saving gives 409, the typed text and the message
//    stay; the later lines are withheld, the notes' figures read "[figure withheld]", and no withheld quote, price or
//    unmasked note text is in the text, attributes or accessible names; restored, everything is back and nothing was
//    written in between;
// 10. accounts: a POST without the binding gives 428 (one bound to another account 401), and the page always sends it;
// 11. phone widths of 375 and 390 px: both pages load and do not scroll sideways, folds closed and open, a row's two
//     lines stacked; the five existing copper pages do not scroll sideways with the new link in their crumbs;
// 12. the only writes are the note saves, the committed tree is unchanged, only local requests are made, and no page
//     error but the deliberate refusals.
//
//   cd frontend; npm run build; npm run test:browser:copper-desk
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromePath, freePort, leaks, same, shownScript, sleep, startChrome, tree, where } from "./metals-kit.mjs";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const python = process.env.SECOND_ORDER_PYTHON ?? "python";
if (!chromePath) throw new Error("Chrome was not found; set SECOND_ORDER_CHROME to its executable.");
if (!existsSync(join(repo, "frontend/dist/index.html"))) throw new Error("Build the client first: npm run build");

const API = "/api/theses/copper/research";
const DESK = "/copper";
const COMPARISON = "synthetic-annual-to-quarter";  // tests/event_chain_fakes.py, WORLD_COMPARISON
const PAGE = `${DESK}/comparisons/${COMPARISON}`;
const TEN_Q = "10q-2026q3";
const PAGE_SENTENCE = "One place for the copper research: its pages, what changed between two retained publications, "
  + "and your own notes. Nothing here is a research score.";
const PERSONAL_MARK = "Personal note: the owner's view. Not a source, not an AI draft, not part of any research score.";
const PREPARED_MARK = "Prepared by the assistant from retained sources; not reviewed by the owner.";
const HISTORICAL = "Historical: both publications were already retained when this comparison was prepared.";
const NOT_CHECKED = "Not yet checked: nothing retained after this note was saved has been compared with it.";
const FOLLOWS_LABEL = "This note follows my latest note on this subject";
const CLOSED = "Notes are not accepted while the comparison is in need of revalidation: The document "
  + `fcx:${TEN_Q} differs from its acquisition record.`;
const PAGES = [["thesis", "/theses/copper"], ["tools", "/theses/copper/tools"], ["fcx", "/companies/fcx"],
  ["metals", "/metals"], ["events", "/theses/copper/events"]];
// The five existing copper pages: the page's own element, and the crumb each already had before the desk's link.
const COPPER_PAGES = [["thesis", "/theses/copper", 'article[data-thesis="copper"]', "← Case library", "/library#theses"],
  ["tools", "/theses/copper/tools", 'article[data-tools="copper"]', "← Copper thesis", "/theses/copper"],
  ["fcx", "/companies/fcx", 'article[data-company="fcx"]', "← Case library", "/library"],
  ["metals", "/metals", "article[data-metals]", "← Case library", "/library"],
  ["events", "/theses/copper/events", 'article[data-page="copper-events"]', "Copper thesis", "/theses/copper"]];
// Owner values for this check only: marked test values, never the owner's view.
const NOTE = "TEST VALUE, not the owner's view: the two lines may not be one measure; 85% against 80%.";
const EXPECTATION = "TEST VALUE, not the owner's view: a move of 5% before the next report.";
const QUESTION = "TEST VALUE: does the next annual report keep the 80% line?";
const masked = (text) => text.replace(/[0-9]+%/g, "[figure withheld]");
const FOLLOW_NOTE = "TEST VALUE: a later note on the same comparison, written with the keyboard.";
const DESK_NOTE = "TEST VALUE: a note on the whole thesis, written with the keyboard.";
const HELD_NOTE = "TEST VALUE: typed before the document changed.";
const CHECK_BY = new Date(Date.now() + 120 * 86400000).toISOString().slice(0, 10);
const ADMIN = { username: "admin", password: "synthetic-admin-pass" };  // tests/account_fakes.py
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pad = (value) => String(value).padStart(2, "0");
/** "18 Sep 2024, 18:00 UTC", as the page writes a saving time (src/format.ts). */
const formatUtc = (iso) => {
  const date = new Date(iso);
  return `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}, ${pad(date.getUTCHours())}:${
    pad(date.getUTCMinutes())} UTC`;
};
/** What would show a change derived between two lines: a signed or pointed difference, a direction word, an arrow. */
const derived = (text) => ["-5", "−5", "5 points", "→", "⟶", "->", "↑", "↓", "▲", "▼"]
  .filter((mark) => text.includes(mark)).concat(text.match(/\b(?:fell|rose|fallen|risen|percentage points?)\b/gi) ?? []);

const root = mkdtempSync(join(tmpdir(), "second-order-copper-desk-check-"));
const served = join(root, "served");
const notesDir = join(served, "research-notes");
const research = join(served, "fcx", "research");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(!!ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const q = JSON.stringify;
const readJson = (path) => JSON.parse(readFileSync(path, "utf8"));
/** The files below a folder by their content only (the restored byte changes a modification time). */
const contents = (folder) => Object.fromEntries(Object.entries(tree(folder)).map(([path, stamp]) => [path, stamp.split(":")[0]]));
const noteFiles = () => (existsSync(notesDir) ? readdirSync(notesDir).sort() : []);
/** A saved note as the server wrote it: one JSON file with its keys sorted. */
const noteOf = (number) => readJson(join(notesDir, `${String(number).padStart(6, "0")}.json`));

try {
  const committedBefore = { content: tree(join(repo, "content")), research: tree(join(repo, "research")) };
  const repoNotes = existsSync(join(repo, "data", "research-notes"));
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
  const first = await view();
  const served1 = first.comparisons[0];

  const { send, evaluate, waitFor, press, type, on, requests, errors, close } =
    await startChrome({ profile: join(root, "chrome"), children });
  const sent = new Map();  // DevTools request id -> { method, url, headers, body, status }
  on(({ method, params }) => {
    if (method === "Network.requestWillBeSent") {
      sent.set(params.requestId, { method: params.request.method, url: params.request.url, headers: params.request.headers,
        body: params.request.postData ?? null, status: null });
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

  const desk = `document.querySelector('article[data-page="copper-desk"]')`;
  const page = `document.querySelector('article[data-page="copper-comparison"]')`;
  const deskReady = `!!${desk}?.querySelector('[data-part="write"]')`;
  const pageReady = `!!${page}?.querySelector("section[data-row]")`;
  /** A fresh page (never a same-document change) that satisfies `wait`. */
  const load = async (path, wait) => {
    await send("Page.navigate", { url: "about:blank" });
    await waitFor(`location.href === "about:blank"`, 5000);
    await send("Page.navigate", { url: `${base}${path}` });
    return waitFor(`document.readyState === "complete" && (${wait})`, 30000);
  };
  const words = (expression) => evaluate(`(${expression})?.textContent.replace(/\\s+/g, " ").trim() ?? null`);
  const click = (expression) => evaluate(`(() => { const e = ${expression}; if (!e) return false; e.click();
    return true; })()`);
  const navNow = () => evaluate(`[...document.querySelectorAll(".site-nav a")].map((a) => ({ text: a.textContent.trim(),
    href: a.getAttribute("href"), current: a.getAttribute("aria-current") }))`);
  const formOf = (at) => `${at}?.querySelector('form[data-form="note"]')`;
  const fieldOf = (at, name) => `${formOf(at)}?.querySelector('[data-field="${name}"]')`;
  /** Type into one of the form's text boxes with real text input, replacing what it holds (or adding to it). */
  const write = async (at, name, value, add = false) => {
    const focused = await evaluate(`(() => { const e = ${fieldOf(at, name)}; if (!e) return false; e.focus();
      if (${add}) e.setSelectionRange(e.value.length, e.value.length); else e.select();
      return document.activeElement === e; })()`);
    if (!focused) return null;
    await type(value);
    return evaluate(`${fieldOf(at, name)}.value`);
  };
  /** Set a control that takes no typed text (the date, the subject) as a choice in it would: its value, one event. */
  const choose = (at, name, value) => evaluate(`(() => { const e = ${fieldOf(at, name)};
    if (!e || e.disabled) return null;
    const proto = e.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(e, ${q(value)});
    e.dispatchEvent(new Event(e.tagName === "SELECT" ? "change" : "input", { bubbles: true })); return e.value; })()`);
  const submit = (at) => evaluate(`(() => { const b = ${formOf(at)}?.querySelector('button[type="submit"]');
    if (!b || b.disabled) return false; b.click(); return true; })()`);
  /** What the form shows now; null when it is not on the page. */
  const formNow = (at) => evaluate(`(() => { const f = ${formOf(at)}; if (!f) return null;
    const v = (name) => f.querySelector('[data-field="' + name + '"]');
    return { text: v("text").value, expectation: v("expectation").value, question: v("question").value,
      checkBy: v("check-by").value, checkByOff: v("check-by").disabled,
      follows: v("follows") ? v("follows").checked : null,
      followsLabel: v("follows")?.closest("label").textContent.trim() ?? null, subject: v("subject")?.value ?? null,
      subjects: [...(v("subject")?.options ?? [])].map((o) => o.textContent),
      message: f.querySelector('.ec-message[role="status"]')?.textContent ?? null,
      closed: f.querySelector('[data-forms="closed"]')?.textContent ?? null,
      count: [...f.querySelectorAll(".ec-count")].map((p) => p.textContent),
      send: !f.querySelector('button[type="submit"]').disabled }; })()`);
  /** Every saved note a part of a page shows, as written there. */
  const notesOn = (at) => evaluate(`[...(${at}?.querySelectorAll("article[data-note]") ?? [])].map((a) => {
    const t = (s) => a.querySelector(s)?.textContent.replace(/\\s+/g, " ").trim() ?? null;
    const raw = (s) => a.querySelector(s)?.textContent ?? null;
    return { id: a.dataset.note, state: a.dataset.noteState, mark: t('[data-mark="personal"]'), signed: t(".rn-signed"),
      subject: t(".rn-subject a"), href: a.querySelector(".rn-subject a")?.getAttribute("href") ?? null,
      hindsight: t("[data-hindsight]"), text: raw("[data-note-text]"),
      dir: a.querySelector("[data-note-text]")?.dir ?? null, expectation: raw("[data-expectation-text]"),
      checkBy: t("[data-check-by]"), status: t("[data-expectation-status]"),
      question: raw("[data-question-text]"), stateLine: t("[data-state-line]"),
      differs: [...a.querySelectorAll("[data-differs] li")].map((li) => li.textContent), masked: t("[data-masked]"),
      followed: t("[data-followed]"), follows: t("[data-follows]"), basisOpen: a.querySelector("details").open,
      basisTitle: t("details summary"),
      basis: [...a.querySelectorAll("details li")].map((li) => li.textContent.trim()) }; })`);
  /** Every row of the comparison page: its two lines as shown, where they stand, its sentence and its note. */
  const rowsNow = () => evaluate(`[...${page}.querySelectorAll("section[data-row]")].map((s) => {
    const side = (name) => { const e = s.querySelector('[data-side="' + name + '"]');
      const r = e.getBoundingClientRect(); const text = (q) => e.querySelector(q)?.textContent ?? null;
      return { state: e.dataset.sideState, head: text("h4"), quote: text("blockquote p"),
        where: text("blockquote footer"), withheld: text(".ec-withheld"),
        line: text(".ec-source-line").replace(/\\s+/g, " ").trim(), left: r.left, right: r.right, top: r.top }; };
    return { id: s.dataset.row, label: s.querySelector("h3").textContent,
      quotes: s.querySelectorAll("blockquote").length, earlier: side("earlier"), later: side("later"),
      sentence: s.querySelector('[data-sentence="measure"]')?.textContent ?? null,
      note: s.querySelector("[data-row-note]")?.textContent ?? null }; })`);
  /** A row as written, without where it stands on the screen. */
  const rowWords = (row) => [row.id, row.label, row.quotes, row.sentence, row.note, ...["earlier", "later"]
    .flatMap((side) => ["state", "head", "quote", "where", "withheld", "line"].map((key) => row[side][key]))];
  const pricesNow = () => evaluate(`({ text: ${page}.querySelector('[data-prices="text"]')?.textContent ?? null,
    figures: [...${page}.querySelectorAll("[data-figure]")].map((li) => ({ id: li.dataset.figure,
      state: li.dataset.figureState, line: li.querySelector('[data-line="figure"]')?.textContent ?? null,
      problem: li.querySelector('[data-line="problem"]')?.textContent ?? null,
      source: li.querySelector(".ec-source-line")?.textContent ?? null })) })`);
  const openFolds = (at) => evaluate(`(() => { ${at}.querySelectorAll("details").forEach((d) => { d.open = true; });
    return true; })()`);
  const axNames = async () => (await send("Accessibility.getFullAXTree")).nodes
    .map((node) => String(node.name?.value ?? "")).filter((name) => name !== "");
  /** A save sent by the check itself from the page (not by the page's form), marked by ?probe= in its address. */
  const probe = (name, body, account) => evaluate(`fetch(${q(`${API}/notes?probe=${name}`)}, { method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json", "X-Second-Order-Research-Note": "1"${
      account ? `, "X-Second-Order-Account": ${q(account)}` : ""} }, body: ${q(JSON.stringify(body))} })
    .then(async (r) => ({ status: r.status, body: await r.json().catch(() => null) }))`);
  const header = (request, name) => Object.entries(request.headers ?? {}).find(([key]) => key.toLowerCase() === name)?.[1];
  const posts = () => [...sent.values()].filter((r) => r.method === "POST" && new URL(r.url).pathname.startsWith(API));
  const pageSaves = () => posts().filter((r) => !new URL(r.url).search.includes("probe="));
  const focusNow = () => evaluate(`(() => { const e = document.activeElement; if (!e || e === document.body) return null;
    return { tag: e.tagName.toLowerCase(), type: e.type ?? "", field: e.dataset.field ?? null,
      form: e.closest("form")?.dataset.form ?? null, checked: e.checked ?? null,
      text: (e.textContent ?? "").trim().slice(0, 40), visible: e.matches(":focus-visible") }; })()`);
  const tabUntil = async (test, limit = 150) => {
    for (let count = 0; count < limit; count++) {
      await press("Tab");
      const now = await focusNow();
      if (now && test(now)) return now;
    }
    return null;
  };

  // ---------------------------------------------------------------- 1. the top bar
  await load("/library", `!!document.querySelector('.site-nav a[href="${DESK}"]')`);
  const nav = (await navNow()).map((item) => item.text);
  check("1. the top bar has a Copper link between Findings and Market context",
    nav.indexOf("Copper") > 0 && nav[nav.indexOf("Copper") - 1] === "Findings"
      && nav[nav.indexOf("Copper") + 1] === "Market context", nav.join());
  await click(`document.querySelector('.site-nav a[href="${DESK}"]')`);
  const reached = await waitFor(`location.pathname === ${q(DESK)} && ${deskReady}`, 15000);
  const current = (await navNow()).filter((item) => item.current === "page");
  check("1. clicking it opens the desk, with the link marked as the current page",
    reached && same(current, [{ text: "Copper", href: DESK, current: "page" }])
      && (await evaluate("document.title")) === "Copper desk · Second Order", q(await navNow()));

  // ---------------------------------------------------------------- 2. the header
  check("2. the header sentence is shown verbatim, under the kicker and the title",
    (await evaluate(`${desk}.querySelector('[data-sentence="page"]')?.textContent`)) === PAGE_SENTENCE
      && (await words(`${desk}.querySelector(".kicker")`)) === "Copper research"
      && (await words(`${desk}.querySelector("h1")`)) === "Copper desk");
  const parts = await evaluate(`[...${desk}.querySelectorAll("section[data-part] > h2")].map((h) => h.textContent)`);
  check("2. the desk's parts stand in order", same(parts, ["Pages", "What changed between two publications",
    "Open questions", "My notes", "Write a note"]), q(parts));

  // ---------------------------------------------------------------- 3. the five pages
  const lines = await evaluate(`[...${desk}.querySelectorAll("[data-desk-page]")].map((li) => ({ id: li.dataset.deskPage,
    title: li.querySelector("a").textContent, path: li.querySelector("a").getAttribute("href"),
    what: li.querySelector('[data-line="what"]').textContent,
    status: li.querySelector('[data-line="status"]')?.textContent ?? null,
    problem: li.querySelector('[data-line="problem"]')?.textContent ?? null }))`);
  check("3. the five pages are linked in order, each with what it is and its line as the view serves them",
    same(lines, first.desk.pages) && same(lines.map((item) => [item.id, item.path]), PAGES)
      && /^Version 1, published /.test(lines[0].status) && /^4 documents, 4 verified/.test(lines[2].status)
      && lines[4].status === "1 chain: 1 awaiting your review." && lines[1].status === null && lines[3].status === null, q(lines));
  check("3. with no note saved, the desk says so in both parts and offers the form",
    (await words(`${desk}.querySelector('[data-part="questions"] .ec-none')`)) === "No open question."
      && (await words(`${desk}.querySelector('[data-part="notes"] .ec-none')`)) === "No note is saved."
      && same((await formNow(desk))?.subjects, first.subjects.map((item) =>
        `${{ thesis: "Thesis", chain: "Chain", comparison: "Comparison" }[item.kind]}: ${item.title}`))
      && first.subjects.length === 3, q(await formNow(desk)));

  // ---------------------------------------------------------------- 4. the links back
  const back = [];
  for (const [id, path, article, crumb, crumbHref] of COPPER_PAGES) {
    const link = `document.querySelector('${article} nav.library-crumbs a[data-desk-link]')`;
    const loaded = await load(path, `!!${link}`);
    const shown = await evaluate(`[...(${link})?.closest("nav").children ?? []].map((e) => [e.tagName, e.textContent.trim(),
      e.getAttribute("href")])`);
    const section = (await navNow()).filter((item) => item.current === "page").map((item) => item.text);
    const went = (await click(link)) && await waitFor(`location.pathname === ${q(DESK)} && ${deskReady}`, 15000);
    back.push({ id, loaded, shown, section, went, crumb: [crumb, crumbHref] });
  }
  check("4. each of the five existing copper pages holds one \"Copper desk\" link in its crumbs, between the crumb it "
    + "already had and the page's own name, and it opens the desk",
  back.every((item) => item.loaded && item.went && item.shown.length === 3
      && same(item.shown[0], ["A", ...item.crumb]) && same(item.shown[1], ["A", "Copper desk", DESK])
      && item.shown[2][0] === "SPAN" && item.shown[2][1] !== ""), q(back));
  check("1. the existing copper pages keep the Library section, not the Copper one",
    back.every((item) => same(item.section, ["Library"])), q(back.map((item) => [item.id, item.section])));

  // ---------------------------------------------------------------- 5. the comparison link
  const listed = await evaluate(`[...${desk}.querySelectorAll("[data-comparison]")].map((li) => ({
    id: li.dataset.comparison, state: li.dataset.comparisonState, title: li.querySelector("a").textContent,
    href: li.querySelector("a").getAttribute("href"),
    tag: li.querySelector('[data-tag="historical"]')?.textContent ?? null,
    earlier: li.querySelector('[data-publication="earlier"]').textContent,
    later: li.querySelector('[data-publication="later"]').textContent,
    line: li.querySelector('[data-line="state"]').textContent }))`);
  check("5. the desk lists the comparison: its title, the Historical tag, both publications with their dates, its state",
    same(listed, [{ id: COMPARISON, state: "available", title: served1.title, href: PAGE, tag: "Historical",
      earlier: "Earlier: the FCX 10-K, dated 2026-02-13 (signature date).",
      later: "Later: the FCX 10-Q, dated 2026-11-06 (signature date).", line: "State: Available." }]), q(listed));
  await click(`${desk}.querySelector('[data-comparison] a')`);
  const opened = await waitFor(`location.pathname === ${q(PAGE)} && ${pageReady}`, 15000);
  const crumbs = await evaluate(`[...${page}.querySelector("nav.library-crumbs").children].map((e) => [e.tagName, e.textContent,
    e.getAttribute("href")])`);
  check("5. its link opens the comparison page: the crumbs, the kicker, the title, the historical sentence, the mark",
    opened && same(crumbs, [["A", "Copper desk", DESK], ["SPAN", served1.title, null]])
      && (await words(`${page}.querySelector(".kicker")`)) === "Copper research · what changed"
      && (await words(`${page}.querySelector("h1")`)) === served1.title
      && (await words(`${page}.querySelector('[data-sentence="historical"]')`)) === HISTORICAL
      && (await words(`${page}.querySelector('[data-mark="prepared"]')`)) === PREPARED_MARK
      && (await words(`${page}.querySelector('header [data-line="state"]')`)) === "State: Available."
      && same((await navNow()).filter((item) => item.current === "page").map((item) => item.text), ["Copper"]), q(crumbs));
  const publications = await evaluate(`[...${page}.querySelectorAll('[data-part="publications"] [data-publication]')].map((e) =>
    [...e.children].map((c) => c.textContent))`);
  check("5. both publications: Earlier and Later, each with its name, title, date and document state",
    same(publications, ["earlier", "later"].map((side) => [side === "earlier" ? "Earlier" : "Later", served1[side].name,
      served1[side].title, `dated ${served1[side].dated} (${served1[side].dated_as})`,
      "The retained document matches its acquisition record."])), q(publications));
  const absent = `document.querySelector('[data-page="copper-comparison"][data-missing]')`;
  await load(`${DESK}/comparisons/no-such-comparison`, `!!${absent}`);
  const missing = await evaluate(`(() => { const s = ${absent}; if (!s) return null;
    return { text: [...s.querySelectorAll("p:not(.kicker)")].map((p) => p.textContent),
      href: s.querySelector("a")?.getAttribute("href") }; })()`);
  await load(`${DESK}/comparisons/Not_An_Id`, `!!document.querySelector("#missing-title")`);
  check("5. an id the view does not hold says so with a link back, and a malformed id is the not-found page",
    same(missing, { text: ["No comparison has this id.", "Copper desk"], href: DESK })
      && !(await evaluate(`!!document.querySelector('[data-page="copper-comparison"]')`)), q(missing));

  // ---------------------------------------------------------------- 6. the rows and the prices
  await load(PAGE, pageReady);
  const rows = await rowsNow();
  const firstRow = rows[0];
  check("6. both lines of the first row are shown in the sources' words, each with its place",
    rows.length === served1.rows.length && firstRow.id === "return-to-operation" && firstRow.label === served1.rows[0].label
      && firstRow.earlier.quote === served1.rows[0].earlier.quote && firstRow.later.quote === served1.rows[0].later.quote
      && firstRow.earlier.quote.includes("85%") && firstRow.later.quote.includes("80%")
      && firstRow.earlier.where === served1.rows[0].earlier.where && firstRow.later.where === served1.rows[0].later.where
      && firstRow.earlier.where.startsWith("page 25 (printed page 23)") && firstRow.later.where.startsWith("page 43"),
    q(firstRow));
  check("6. the two lines sit side by side under the earlier and the later publication and its date",
    rows.every((row) => Math.abs(row.earlier.top - row.later.top) < 2 && row.earlier.right <= row.later.left
      && row.earlier.head === "Earlier: the FCX 10-K, dated 2026-02-13 (signature date)"
      && row.later.head === "Later: the FCX 10-Q, dated 2026-11-06 (signature date)"
      && row.earlier.line === "the FCX 10-K matches its acquisition record. The record is as it was pinned."
      && row.later.line === "the FCX 10-Q matches its acquisition record. The record is as it was pinned."), q(rows));
  check("6. each row shows its fixed sentence, and the assistant's note where the row has one",
    same(rows.map((row) => [row.sentence, row.note]), served1.rows.map((row) => [row.sentence,
      row.note === null ? null : `The assistant's note: ${row.note}`]))
      && rows[0].sentence === "No retained source establishes that the two lines measure the same thing. No change is "
        + "computed between them." && rows[1].sentence === "Two statements, each shown as written.", q(rows));
  const pageText = await evaluate(`${page}.innerText`);
  const quoteCount = await evaluate(`${page}.querySelectorAll("blockquote").length`);
  check("6. nothing on the page derives a change between two lines: exactly two quotes a row, no difference, direction "
    + "word or arrow in its text",
    rows.every((row) => row.quotes === 2) && quoteCount === 2 * rows.length && derived(pageText).length === 0
      && pageText.includes("85%") && pageText.includes("80%") && !/\b5\s*(%|percent|points?)/.test(pageText),
    q(derived(pageText)));
  const prices = await pricesNow();
  check("6. the retained prices: each figure with its period and source, then the fixed prices text",
    same(prices.figures.map((item) => [item.id, item.state, item.line, item.source]), served1.prices.figures.map((item) =>
      [item.id, "available", `${item.label}, ${item.period.label} (${item.period.start} to ${item.period.end}): ${
        item.display} ${item.unit}`, item.source.name]))
      && prices.figures[0].line === "Average realized price per pound (copper), FY2025 (2025-01-01 to 2025-12-31): 4.75 "
        + "USD per pound"
      && prices.text === "Retained prices cover up to 2026-09-30. No retained price covers a later date."
      && prices.text === served1.prices.text, q(prices));

  // ---------------------------------------------------------------- 7. a note with an expectation and a question
  const empty = await formNow(page);
  check("7. the form opens empty: no subject selector on this page, no \"follows\" box, the date off, nothing to send",
    same(empty, { text: "", expectation: "", question: "", checkBy: "", checkByOff: true, follows: null, followsLabel: null,
      subject: null, subjects: [], message: null, closed: null,
      count: ["0 of 2000 characters", "0 of 500 characters", "0 of 280 characters"], send: false }), q(empty));
  const typed = [await write(page, "text", NOTE), await write(page, "expectation", EXPECTATION),
    await choose(page, "check-by", CHECK_BY), await write(page, "question", QUESTION)];
  const filled = await formNow(page);
  // A saved note can never be changed, so Enter in the one-line date field must not send the form.
  const savesBeforeEnter = pageSaves().length;
  await evaluate(`${formOf(page)}.querySelector('[data-field="check-by"]').focus()`);
  await press("Enter");
  await sleep(500);
  check("7. Enter in the check-by field saves nothing: no file, no request, and the typed text is kept",
    noteFiles().length === 0 && pageSaves().length === savesBeforeEnter && (await formNow(page))?.text === NOTE,
    q([noteFiles(), pageSaves().length]));
  const before = Date.now();
  const clicked = await submit(page);
  await waitFor(`${page}.querySelectorAll("article[data-note]").length === 1`, 15000);
  const after = Date.now();
  const one = noteFiles().length === 1 ? noteOf(1) : null;
  const firstSave = pageSaves().at(-1);
  check("7. the typed note, expectation, date and question are in the form, and the date opens with the expectation",
    same(typed, [NOTE, EXPECTATION, CHECK_BY, QUESTION]) && filled.checkByOff === false && filled.send === true
      && filled.count[0] === `${NOTE.length} of 2000 characters`, q([typed, filled]));
  check("7. saving writes exactly one file, holding what was typed, bound to the comparison and the account",
    clicked && same(noteFiles(), ["000001.json"]) && one?.text === NOTE
      && same(one.expectation, { check_by: CHECK_BY, text: EXPECTATION }) && one.question === QUESTION
      && same(one.about, { id: COMPARISON, kind: "comparison" }) && one.parent_note_id === null && one.follows === null
      && one.sequence === 1 && one.basis.comparison.sha256 === served1.sha256
      && same(one.basis.documents.map((item) => item.ref), ["fcx:10k-2025", `fcx:${TEN_Q}`])
      && same(one.account, { user_id: adminId, username: ADMIN.username }), q([noteFiles(), one]));
  const sentBody = firstSave?.body ? JSON.parse(firstSave.body) : null;
  check("7. its saved_at is the server's time: within the save, while the request carried no time at all",
    one !== null && Date.parse(one.saved_at) >= before - 2000 && Date.parse(one.saved_at) <= after + 2000
      && firstSave.status === 201 && same(Object.keys(sentBody ?? {}), ["parent_note_id", "about", "subject_sha256",
        "follows", "text", "expectation", "question"]) && !q(sentBody).includes(one.saved_at.slice(0, 10)),
    q([one?.saved_at, before, after, sentBody]));
  const hindsight = `Written after both publications were known: saved on ${one?.saved_at.slice(0, 10)}, the later `
    + "publication is dated 2026-11-06.";
  const shownNote = (note) => note && note.id === one?.note_id && note.state === "current" && note.mark === PERSONAL_MARK
    && note.signed === `Saved ${formatUtc(one.saved_at)} by ${ADMIN.username}` && note.subject === served1.title
    && note.href === PAGE && note.hindsight === hindsight && note.text === NOTE && note.dir === "auto"
    && note.expectation === EXPECTATION && note.checkBy === `Check by ${CHECK_BY}` && note.status === NOT_CHECKED
    && note.question === QUESTION && note.stateLine === "Current" && note.differs.length === 0 && note.masked === null
    && note.followed === null && note.follows === null && note.basisOpen === false && note.basisTitle === "Basis"
    && same(note.basis, ["the FCX 10-K matches its acquisition record.", "the FCX 10-Q matches its acquisition record."]);
  const onPage = await notesOn(page);
  const cleared = await formNow(page);
  check("7. the note shows on the comparison page: the personal mark, its real saving time, the hindsight sentence, "
    + "\"Not yet checked\", its question, a closed Basis fold",
    onPage.length === 1 && shownNote(onPage[0]), q(onPage));
  check("7. the form says \"Saved.\", is empty again, and now offers to follow the latest note",
    cleared.message === "Saved." && cleared.text === "" && cleared.expectation === "" && cleared.question === ""
      && cleared.checkBy === "" && cleared.follows === false && cleared.followsLabel === FOLLOWS_LABEL, q(cleared));
  await load(DESK, deskReady);
  const onDesk = await notesOn(`${desk}.querySelector('[data-part="notes"]')`);
  const asked = await evaluate(`[...${desk}.querySelectorAll('[data-part="questions"] [data-open-question]')].map((li) => ({
    id: li.dataset.openQuestion, question: li.querySelector(".ec-own-text").textContent,
    subject: li.querySelector("a")?.textContent ?? null, href: li.querySelector("a")?.getAttribute("href") ?? null }))`);
  check("7. the note shows on the desk the same way, and its question stands under \"Open questions\" with its subject",
    onDesk.length === 1 && shownNote(onDesk[0])
      && same(asked, [{ id: one?.note_id, question: QUESTION, subject: served1.title, href: PAGE }]), q([onDesk, asked]));

  // ---------------------------------------------------------------- 8. keyboard
  await load(PAGE, pageReady);
  await evaluate(`${page}.querySelector(".library-crumbs a").focus(); true`);
  const textBox = await tabUntil((f) => f.form === "note" && f.field === "text");
  if (textBox) await type(FOLLOW_NOTE);
  const box = await tabUntil((f) => f.form === "note" && f.field === "follows");
  await press("Space");
  const ticked = await focusNow();
  const saveButton = await tabUntil((f) => f.form === "note" && f.tag === "button");
  await press("Space");
  await waitFor(`${page}.querySelectorAll("article[data-note]").length === 2`, 15000);
  const two = noteFiles().length === 2 ? noteOf(2) : null;
  check("8. Tab reaches the note box, the \"follows\" box and the save button; Space ticks and Space saves",
    textBox?.tag === "textarea" && textBox.visible && box?.type === "checkbox" && ticked?.checked === true
      && saveButton?.text === "Save note" && two?.text === FOLLOW_NOTE && two.follows === one?.note_id
      && two.parent_note_id === one?.note_id && two.expectation === null && two.question === null,
    q([textBox, box, ticked, saveButton, two]));
  const pair = await notesOn(page);
  check("8. the page shows the newest note first; the later one follows, the earlier one is followed",
    same(pair.map((note) => [note.id, note.text, note.followed, note.follows]),
      [[two?.note_id, FOLLOW_NOTE, null, "Follows an earlier note."],
        [one?.note_id, NOTE, "A later note follows this one.", null]]), q(pair));
  await load(DESK, deskReady);
  await evaluate(`${desk}.querySelector("[data-desk-page] a").focus(); true`);
  const selector = await tabUntil((f) => f.form === "note" && f.field === "subject");
  const deskBox = await tabUntil((f) => f.form === "note" && f.field === "text");
  if (deskBox) await type(DESK_NOTE);
  const deskButton = await tabUntil((f) => f.form === "note" && f.tag === "button");
  await press("Enter");
  await waitFor(`${desk}.querySelectorAll('[data-part="notes"] article[data-note]').length === 3`, 15000);
  const three = noteFiles().length === 3 ? noteOf(3) : null;
  const deskNotes = await notesOn(`${desk}.querySelector('[data-part="notes"]')`);
  check("8. on the desk Tab reaches the subject selector, the note box and the save button, and Enter saves",
    selector?.tag === "select" && deskBox?.tag === "textarea" && deskButton?.text === "Save note"
      && three?.text === DESK_NOTE && same(three.about, { id: "copper", kind: "thesis" })
      && three.parent_note_id === two?.note_id && three.follows === null
      && same(Object.keys(three.basis).sort(), ["documents", "thesis"]), q([selector, deskBox, deskButton, three]));
  check("8. the desk lists every note, newest first, each linked to its subject's page; the thesis note has no hindsight "
    + "sentence",
    same(deskNotes.map((note) => [note.id, note.href, note.hindsight === null]), [[three?.note_id, "/theses/copper", true],
      [two?.note_id, PAGE, false], [one?.note_id, PAGE, false]]), q(deskNotes.map((note) => [note.id, note.href])));
  check("8. the followed note's question is no longer open",
    (await words(`${desk}.querySelector('[data-part="questions"] .ec-none')`)) === "No open question."
      && !(await evaluate(`!!${desk}.querySelector("[data-open-question]")`)));

  // ---------------------------------------------------------------- 9. a retained file changed
  const entry = readJson(join(research, "sources.json")).sources.find((item) => item.id === TEN_Q);
  const document = join(served, "fcx", "sources", entry.folder, entry.name);
  const laterQuotes = served1.rows.map((row) => row.later.quote);
  const laterPrice = served1.prices.figures.find((item) => item.source.ref === `fcx:${TEN_Q}`).display;
  // What the byte change must withhold: the 10-Q's two quotes and its price figure, and the note's texts unmasked.
  const withheldValues = [...laterQuotes, laterPrice, NOTE, EXPECTATION, QUESTION];
  const shownNow = (article) => shownScript("[data-none]", article);
  await load(PAGE, pageReady);
  await openFolds(page);
  const control = leaks(await evaluate(shownNow('article[data-page="copper-comparison"]')), withheldValues);
  const controlNames = leaks({ text: (await axNames()).join("\n"), attributes: [] }, withheldValues);
  check("9. while the 10-Q verifies, the same scan finds its quotes, its price and the unmasked note texts on the page, "
    + "and among the accessible names (the scan can see them)",
    laterQuotes.length === 2 && laterPrice === "6.54" && same(control, withheldValues) && same(controlNames, withheldValues),
    q({ control, controlNames }));
  await write(page, "text", HELD_NOTE);  // typed while the 10-Q still verifies; sent after one byte of it changed
  const original = readFileSync(document);
  const flipped = Buffer.from(original);
  flipped[100] ^= 1;
  writeFileSync(document, flipped);
  const before409 = noteFiles();
  const sentHeld = await submit(page);
  await waitFor(`${page}?.dataset.comparisonState === "needs_revalidation"`, 15000);  // read again on its own
  await sleep(500);
  const kept = await formNow(page);
  const changed = await view();
  const reasons = changed.comparisons[0].reasons;
  check("9. the save button gives 409 and nothing is written",
    sentHeld && pageSaves().at(-1)?.status === 409 && same(noteFiles(), before409), q(pageSaves().at(-1)?.status));
  check("9. after the page has read again, the typed note and the server's message stay; the form cannot send and says why",
    kept?.text === HELD_NOTE && kept.message === `The comparison is not available: ${reasons.join("; ")}`
      && kept.message.includes(`fcx:${TEN_Q}`) && kept.send === false && kept.closed === CLOSED, q(kept));
  await openFolds(page);
  await sleep(200);
  const shown = await evaluate(shownNow('article[data-page="copper-comparison"]'));
  const names = await axNames();
  const found = leaks(shown, withheldValues);
  const foundNames = leaks({ text: names.join("\n"), attributes: [] }, withheldValues);
  check("9. with one byte of the 10-Q changed, no withheld quote, price or unmasked note text is in the text, attributes "
    + "or accessible names", found.length === 0 && foundNames.length === 0 && names.length > 50,
  [...found.map((value) => where(value, shown)), ...foundNames].join(" | "));
  const withheldRows = await rowsNow();
  check("9. the later line of each row is withheld and says why; the earlier line stays, and so does the fixed sentence",
    withheldRows.every((row, at) => row.quotes === 1 && row.later.quote === null && row.later.state === "changed"
      && row.later.withheld === "Withheld: the FCX 10-Q no longer matches its acquisition record"
      && row.later.line === "the FCX 10-Q differs from its acquisition record."
      && row.earlier.quote === served1.rows[at].earlier.quote && row.sentence === served1.rows[at].sentence)
      && (await words(`${page}.querySelector('header [data-line="state"]')`)) === "State: Needs revalidation."
      && same(await evaluate(`[...${page}.querySelectorAll("header .ec-reasons li")].map((li) => li.textContent)`), reasons)
      && derived(await evaluate(`${page}.innerText`)).length === 0, q(withheldRows));
  const heldPrices = await pricesNow();
  check("9. the 10-Q's price figure is withheld with its reason, and the prices text names the day still covered",
    same(heldPrices.figures.map((item) => item.state), ["available", "withheld", "available", "available"])
      && heldPrices.figures[1].line === null && heldPrices.figures[1].problem === changed.comparisons[0].prices.figures[1].problem
      && heldPrices.text === "Retained prices cover up to 2025-12-31. No retained price covers a later date.", q(heldPrices));
  const heldNotes = await notesOn(page);
  check("9. the notes' figures read \"[figure withheld]\"; the notes say what is withheld and that their basis differs",
    same(heldNotes.map((note) => [note.text, note.expectation, note.question]),
      [[FOLLOW_NOTE, null, null], [masked(NOTE), masked(EXPECTATION), masked(QUESTION)]])
      && masked(NOTE).split("[figure withheld]").length === 3
      && heldNotes.every((note) => note.state === "earlier_basis" && note.stateLine === "Earlier basis"
        && same(note.differs, reasons) && note.masked?.startsWith("Figures withheld: ") && note.masked.includes(`fcx:${TEN_Q}`)
        && note.basis.includes("the FCX 10-Q differs from its acquisition record."))
      && heldNotes[1].checkBy === `Check by ${CHECK_BY}`, q(heldNotes));
  const ownTexts = await evaluate(`[...${page}.querySelectorAll(".ec-own-text")].map((e) => e.textContent)`);
  check("9. no figure in the owner's words is shown unmasked",
    ownTexts.length === 4 && ownTexts.every((value) => !/\d/.test(value)), q(ownTexts));
  await write(page, "text", " TEST VALUE: more.", true);
  const edited = await formNow(page);
  check("9. editing the note clears the message and keeps the text; the form still cannot send",
    edited?.text === `${HELD_NOTE} TEST VALUE: more.` && edited.message === null && edited.send === false
      && edited.closed === CLOSED, q(edited));
  await load(DESK, deskReady);
  await openFolds(desk);
  const deskShown = await evaluate(shownNow('article[data-page="copper-desk"]'));
  const deskNames = await axNames();
  const deskFound = leaks(deskShown, withheldValues);
  const deskFoundNames = leaks({ text: deskNames.join("\n"), attributes: [] }, withheldValues);
  const deskHeld = await notesOn(`${desk}.querySelector('[data-part="notes"]')`);
  const deskLines = await evaluate(`[...${desk}.querySelectorAll("[data-desk-page]")].map((li) =>
    li.querySelector('[data-line="status"]')?.textContent ?? null)`);
  check("9. the desk shows the same: the comparison needs revalidation, the notes masked, nothing withheld in its text, "
    + "attributes or accessible names",
    deskFound.length === 0 && deskFoundNames.length === 0 && deskNames.length > 50
      && (await evaluate(`${desk}.querySelector("[data-comparison]").dataset.comparisonState`)) === "needs_revalidation"
      && (await words(`${desk}.querySelector('[data-comparison] [data-line="state"]')`)) === "State: Needs revalidation."
      && same(deskHeld.map((note) => [note.text, note.state]), [[DESK_NOTE, "current"], [FOLLOW_NOTE, "earlier_basis"],
        [masked(NOTE), "earlier_basis"]]) && /^4 documents, 3 verified/.test(deskLines[2]),
    [...deskFound.map((value) => where(value, deskShown)), ...deskFoundNames, q(deskLines)].join(" | "));
  const thesisOpen = await formNow(desk);
  const picked = await choose(desk, "subject", `comparison:${COMPARISON}`);
  await write(desk, "text", HELD_NOTE);
  const comparisonClosed = await formNow(desk);
  check("9. on the desk the form stays open for the thesis and is closed, with the reason, for the comparison",
    thesisOpen?.subject === "thesis:copper" && thesisOpen.closed === null && picked === `comparison:${COMPARISON}`
      && comparisonClosed.closed === CLOSED && comparisonClosed.send === false && comparisonClosed.text === HELD_NOTE,
    q([thesisOpen, comparisonClosed]));
  const stale = { parent_note_id: changed.notes.latest, about: { kind: "comparison", id: COMPARISON },
    subject_sha256: served1.sha256, follows: null, text: "TEST VALUE: a save the server must refuse.", expectation: null,
    question: null };
  const refused = await probe("409", stale, adminId);
  check("9. the server answers 409 with exactly {detail, latest} to a note on the changed comparison, and writes nothing",
    refused.status === 409 && same(Object.keys(refused.body ?? {}).sort(), ["detail", "latest"])
      && refused.body.detail.includes(`fcx:${TEN_Q}`) && refused.body.latest === three?.note_id
      && same(noteFiles(), before409), q(refused));
  writeFileSync(document, original);
  await load(PAGE, pageReady);
  const restoredRows = await rowsNow();
  const restoredNotes = await notesOn(page);
  check("9. the file restored: available, both lines of each row back, the notes' figures back, nothing written in between",
    (await evaluate(`${page}.dataset.comparisonState`)) === "available" && same(restoredRows.map(rowWords), rows.map(rowWords))
      && same(await pricesNow(), prices) && same(restoredNotes.map((note) => [note.text, note.expectation, note.question,
        note.state, note.masked]), [[FOLLOW_NOTE, null, null, "current", null], [NOTE, EXPECTATION, QUESTION, "current", null]])
      && same(noteFiles(), before409) && same(noteFiles(), ["000001.json", "000002.json", "000003.json"])
      && (await formNow(page))?.closed === null, q([restoredRows, restoredNotes]));

  // ---------------------------------------------------------------- 10. accounts mode
  const latest = (await view()).notes.latest;
  const beforeUnbound = noteFiles();
  const unbound = await probe("428", { ...stale, parent_note_id: latest }, null);
  const otherAccount = await probe("401", { ...stale, parent_note_id: latest }, "not-this-account");
  check("10. signed out, the copper research is not served (401)", signedOut === 401, String(signedOut));
  check("10. a POST without the binding gives 428 (account_binding_required), one bound to another account 401",
    unbound.status === 428 && unbound.body?.code === "account_binding_required"
      && otherAccount.status === 401 && otherAccount.body?.code === "account_changed", q([unbound, otherAccount]));
  check("10. neither wrote anything", same(noteFiles(), beforeUnbound));

  // ---------------------------------------------------------------- 11. phone widths
  for (const [width, height] of [[375, 812], [390, 844]]) {
    await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 2, mobile: true });
    const overflow = `document.documentElement.scrollWidth - document.documentElement.clientWidth`;
    const sizes = [];
    for (const [path, ready, at] of [[DESK, deskReady, desk], [PAGE, pageReady, page]]) {
      const loaded = await load(path, ready);
      await sleep(300);
      const folded = await evaluate(overflow);
      await openFolds(at);
      await sleep(200);
      sizes.push({ path, loaded, folded, opened: await evaluate(overflow) });
    }
    const stacked = await rowsNow();
    check(`11. at ${width} px the desk and the comparison page load and do not scroll sideways, with their folds closed `
      + "and open; a row's two lines are stacked, the earlier above the later",
    sizes.every((item) => item.loaded === true && item.folded <= 0 && item.opened <= 0) && stacked.length === rows.length
        && stacked.every((row) => row.quotes === 2 && Math.abs(row.earlier.left - row.later.left) < 2
          && row.later.top > row.earlier.top && row.earlier.right <= width && row.later.right <= width), q([sizes, stacked]));
    const crumbed = [];
    for (const [id, path, article] of COPPER_PAGES) {
      const loaded = await load(path, `!!document.querySelector('${article} nav.library-crumbs a[data-desk-link]')`);
      await sleep(300);
      crumbed.push({ id, loaded, over: await evaluate(overflow) });
    }
    check(`11. at ${width} px the five existing copper pages, with the desk's link in their crumbs, do not scroll sideways`,
      crumbed.every((item) => item.loaded === true && item.over <= 0), q(crumbed));
  }
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  // ---------------------------------------------------------------- 12. writes, the tree, requests and errors
  const saves = pageSaves();
  const probes = posts().filter((r) => new URL(r.url).search.includes("probe="));
  const written = [one, two, three].filter(Boolean);
  check("10. the page sent the account binding and the action header with every one of its saves",
    saves.length === 4 && saves.every((r) => header(r, "x-second-order-account") === adminId
      && header(r, "x-second-order-research-note") === "1" && new URL(r.url).pathname === `${API}/notes`)
      && written.length === 3 && written.every((item) => same(item.account, { user_id: adminId, username: ADMIN.username })),
    q(saves.map((r) => [new URL(r.url).pathname, header(r, "x-second-order-account") ?? null])));
  check("12. the page's writes are the note saves: three saved, and one refused with 409",
    same(saves.map((r) => r.status), [201, 201, 201, 409]), q(saves.map((r) => [r.url, r.status])));
  check("12. the check's own refused saves are the three listed ones",
    same(probes.map((r) => [new URL(r.url).searchParams.get("probe"), r.status]), [["409", 409], ["428", 428], ["401", 401]]),
    q(probes.map((r) => [r.url, r.status])));
  const writes = requests.filter((r) => r.method !== "GET" && r.method !== "HEAD");
  check("12. nothing else was sent but GET requests", writes.length === saves.length + probes.length,
    q(writes.map((r) => `${r.method} ${r.url}`)));
  check("12. the server wrote only the three notes", same(noteFiles(), ["000001.json", "000002.json", "000003.json"]),
    q(noteFiles()));
  const servedAfter = contents(served);
  const differing = [...new Set([...Object.keys(servedBefore), ...Object.keys(servedAfter)])]
    .filter((path) => servedBefore[path] !== servedAfter[path]).sort();
  const allowed = (path) => path.startsWith("research-notes/") || path.startsWith("accounts/");
  check("12. below the served folder only the notes and the session store changed; the changed byte is back",
    differing.every(allowed) && differing.filter((path) => path.startsWith("research-notes/")).length === 3,
    q(differing.filter((path) => !allowed(path))));
  check("12. the committed content and research are unchanged, and nothing went to the repository's data folder",
    same(tree(join(repo, "content")), committedBefore.content) && same(tree(join(repo, "research")), committedBefore.research)
      && existsSync(join(repo, "data", "research-notes")) === repoNotes);
  const outside = requests.filter((r) => !r.url.startsWith(base) && !r.url.startsWith("data:") && !r.url.startsWith("about:"));
  check("12. only requests to the local server", outside.length === 0, outside.map((r) => r.url).join());
  // The browser logs the deliberate refusals above (the 409s, the 428 and the 401) as failed loads of exactly those
  // addresses; each is attributed to its URL and set aside, as is the favicon probe.
  const deliberate = (e) => /status of (409|428|401)/.test(e.text) && e.url.includes(`${API}/notes`);
  const real = errors.filter((e) => !e.url.endsWith("/favicon.ico") && !deliberate(e));
  check("12. no page errors", real.length === 0, real.map((e) => `${e.text} @ ${e.url}`).join(" | "));
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
