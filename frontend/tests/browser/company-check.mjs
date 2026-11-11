// The FCX company page (/companies/fcx) in headless Chrome, over the review server and the retained FCX documents
// (data/company-sources/fcx, private; the check needs them and only reads them). Four servers:
// - retained: the first screen, every figure against its record, no typed number in a text, the figure detail, the tabs,
//   folds and Numbers views by keyboard, the 2025 operating cash flow note, sensitivities and Bagdad, sources and
//   wording, phone width without sideways scrolling;
// - changed (one byte of the Bagdad release) and missing (no results release): what rests on them is not shown;
// - release changed (one byte of the results release), and missing again: no withheld figure's name or accessible label
//   carries FCX's ownership share (the four Grasberg copper figures); the share is shown only by its own record;
// - retained with SYNTHETIC accounts: signed out 401, a reader 403 and the Client build, an admin the page.
// SECOND_ORDER_SCREENSHOTS=<folder> also writes viewport screenshots (desktop 1280x900, phone 390x844).
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { affirmative, chromePath, freePort, same, sleep, startChrome, tree } from "./metals-kit.mjs";
import { takeShots } from "./company-shots.mjs";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const python = process.env.SECOND_ORDER_PYTHON ?? "python";
const shots = process.env.SECOND_ORDER_SCREENSHOTS;
const data = join(repo, "data/company-sources/fcx");
const research = join(repo, "research/fcx");
if (!chromePath) throw new Error("Chrome was not found; set SECOND_ORDER_CHROME to its executable.");
if (!existsSync(join(repo, "frontend/dist/index.html"))) throw new Error("Build the client first: npm run build");
const sourcesFile = JSON.parse(readFileSync(join(research, "sources.json"), "utf-8")).sources;
if (!sourcesFile.every((s) => existsSync(join(data, s.folder, s.name)))) {
  throw new Error("The retained FCX documents are not in data/company-sources/fcx; this check reads them.");
}
const facts = JSON.parse(readFileSync(join(research, "facts.json"), "utf-8"));

const root = mkdtempSync(join(tmpdir(), "second-order-company-check-"));
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(!!ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const q = JSON.stringify;
const PASSWORDS = { admin: "synthetic-admin-pass", "reader-a": "synthetic-reader-a" };  // tests/account_fakes.py
const digits = (text) => String(text ?? "").replace(/\D/g, "");

async function startServer(mode, accounts = false) {
  const served = join(root, `served-${mode}${accounts ? "-accounts" : ""}`);
  mkdirSync(served);
  const port = await freePort();
  const args = [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port), "--company-fcx", mode,
    ...(accounts ? ["--accounts", "synthetic"] : [])];
  children.push(spawn(python, args, { cwd: repo, stdio: ["ignore", "inherit", "inherit"] }));
  const base = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 300; i++) {
    try { const reply = await fetch(`${base}/api/companies/fcx`); if (reply.ok || reply.status === 401) return base; }
    catch { /* starting */ }
    await sleep(200);
  }
  throw new Error(`The review server (${mode}) did not start.`);
}

/** Text a page block shows as its own words: figures, tags and buttons cut out. */
const ownWords = `(() => [...document.querySelectorAll(".co-line > p, .co-change > p, .co-tile-note")].map((e) => {
  const c = e.cloneNode(true); c.querySelectorAll(".co-fig, .co-tag, button").forEach((x) => x.remove());
  return c.textContent; }))()`;
const figures = `[...document.querySelectorAll("article[data-company] .co-fig")].map((b) => ({ id: b.dataset.figure,
  state: b.dataset.state, text: b.querySelector(".co-fig-text").textContent, badge: b.querySelector(".co-kind").textContent }))`;
const noSideways = `document.documentElement.scrollWidth <= window.innerWidth`;
const IDENTIFYING = {  // all a withheld record may carry (second_order/company_research_view.py, IDENTIFYING)
  published: ["id", "kind", "metric", "unit", "period", "basis", "source", "page", "printed_page", "location", "rests_on",
    "state", "problem", "value", "display", "quote"],
  computed: ["id", "kind", "metric", "unit", "period", "basis", "formula", "inputs", "decimals", "assumptions", "rests_on",
    "state", "problem", "value"],
  assumption: ["id", "kind", "used_by", "rests_on", "state", "problem", "statement"],
};
const contentOf = (record) => ["note", "basis_mix", "period_mix", "unit_mix", "quote", "statement"]
  .map((key) => record?.[key]).filter((text) => typeof text === "string" && text.length >= 25);
const factsById = Object.fromEntries(facts.records.map((record) => [record.id, record]));
/** The texts that rest on a document that is not verified in `reply` (from the retained reply's rests_on), less any
 * that a shown figure or passage carries in its own right. */
const forbiddenIn = (reply, retained) => {
  const bad = new Set(reply.sources.filter((s) => s.state !== "verified").map((s) => s.id));
  const shown = [...Object.values(reply.records).filter((r) => r.state === "available").flatMap(contentOf),
    ...Object.values(reply.passages).filter((p) => p.state === "available").map((p) => p.quote)];
  const texts = Object.values(retained.records).filter((r) => (r.rests_on ?? []).some((s) => bad.has(s)))
    .flatMap((r) => contentOf(factsById[r.id]))
    .concat(facts.passages.filter((p) => bad.has(p.source)).map((p) => p.quote));
  return [...new Set(texts)].filter((text) => !shown.some((other) => other.includes(text)));
};
const replyLeaks = (reply) => {
  const out = [];
  for (const record of Object.values(reply.records)) {
    if (record.state !== "withheld") continue;
    const extra = Object.keys(record).filter((key) => !IDENTIFYING[record.kind].includes(key));
    if (extra.length || (record.kind === "assumption" && record.statement !== null)) out.push(`${record.id}: ${extra}`);
  }
  const walk = (node) => {
    if (Array.isArray(node)) node.forEach(walk);
    else if (node && typeof node === "object") {
      if ("refs" in node && node.state === "withheld" && node.segments !== null) out.push("a withheld line with words");
      Object.values(node).forEach(walk);
    }
  };
  walk(reply.page);
  return out;
};
const ALLOWED = /\b(?:19|20)\d{2}\b|\b(?:10-K|10-Q|8-K)\b/g;
const GRASBERG = facts.records.filter((r) => r.id.startsWith("r3-cu-grasberg-")).map((r) => r.id);
const GRASBERG_NAME = "Copper volumes: Grasberg minerals district";
const OWNERSHIP = "48.76";  // FCX's share of PTFI as the documents print it: a figure, never part of a name
const PERCENT = /\d\s*%/;

try {
  // ---------------------------------------------------------------- retained
  const dataBefore = tree(data), researchBefore = tree(research);
  const base = await startServer("retained");
  const reply = await (await fetch(`${base}/api/companies/fcx`)).json();
  const records = reply.records;
  check("the server verifies all four documents and shows every record",
    reply.verified === 4 && Object.values(records).every((r) => r.state === "available") && reply.provider_called === false);
  const { send, evaluate, waitFor, press, requests, errors, close } = await startChrome({ profile: join(root, "chrome"), children });
  await send("Page.enable"); await send("Runtime.enable"); await send("Log.enable"); await send("Network.enable");
  const ready = `!!document.querySelector('article[data-company] h1') && !!document.querySelector('[data-read]')`;
  let at = base;
  const load = async (path, wait = ready) => {
    await send("Page.navigate", { url: "about:blank" });
    await waitFor(`location.href === "about:blank"`, 5000);
    await send("Page.navigate", { url: `${at}${path}` });
    return waitFor(`document.readyState === "complete" && (${wait})`, 30000);
  };
  const size = (width, height, mobile = false) =>
    send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: mobile ? 2 : 1, mobile });
  const focusedFigure = `document.activeElement?.dataset?.figure ?? null`;
  /** Open the detail of every withheld figure on the given tabs (every fold open) and look in it for text that rests on
   * an unverified document; also scan each tab's whole text. */
  const sweep = async (state, forbidden, hashes, least) => {
    let opened = 0;
    const found = [];
    for (const hash of hashes) {
      await load(`/companies/fcx${hash}`);
      await evaluate(`document.querySelectorAll("article[data-company] details").forEach((d) => { d.open = true; }); true`);
      const pageText = await evaluate(`document.querySelector("article[data-company]").innerText`);
      found.push(...forbidden.filter((text) => pageText.includes(text)).map((text) => `${hash} page: ${text.slice(0, 50)}`));
      const ids = await evaluate(`[...new Set([...document.querySelectorAll('.co-fig[data-state="withheld"]')]
        .map((b) => b.dataset.figure))]`);
      for (const id of ids) {
        await evaluate(`document.querySelector('.co-fig[data-figure="${id}"]').click(); true`);
        if (!(await waitFor(`document.querySelector("aside.co-detail")?.dataset.detail === "${id}"`, 3000))) continue;
        opened += 1;
        const detail = await evaluate(`document.querySelector("aside.co-detail").innerText`);
        found.push(...forbidden.filter((text) => detail.includes(text)).map((text) => `${id}: ${text.slice(0, 50)}`));
        if (/\n(Note|Units|Bases|Periods)\n/.test(detail)) found.push(`${id}: an explanation field is shown`);
        await evaluate(`document.querySelector(".co-detail-close").click(); true`);
      }
    }
    check(`(${state}) every withheld figure's detail (${opened} opened) and every tab show nothing that rests on the `
      + "unverified document", opened >= least && found.length === 0, `${opened} opened; ${found.slice(0, 4).join("; ")}`);
  };
  /** Every row of "Every figure" (all shown): its name, the figure's state and accessible label; and the heading and
   * text of the first Grasberg copper figure's detail. The release prints FCX's share of PTFI in that row's label; the
   * figures' names do not carry it. */
  const grasbergRows = async () => {
    await load("/companies/fcx#numbers");
    await evaluate(`document.querySelector('details[data-part="register"]').open = true; true`);
    await waitFor(`!!document.querySelector("[data-register] tbody tr")`, 5000);
    await evaluate(`document.querySelector("[data-register] .co-show-all")?.click(); true`);
    await waitFor(`document.querySelectorAll("[data-register] tbody tr").length > 100`, 5000);
    const rows = await evaluate(`[...document.querySelectorAll("[data-register] .co-fig")].map((b) => ({ id: b.dataset.figure,
      state: b.dataset.state, label: b.getAttribute("aria-label"), name: b.closest("tr").querySelector("th").textContent }))`);
    await evaluate(`document.querySelector('[data-register] .co-fig[data-figure="${GRASBERG[0]}"]').click(); true`);
    await waitFor(`document.querySelector("aside.co-detail")?.dataset.detail === "${GRASBERG[0]}"`, 3000);
    const detail = await evaluate(`({ heading: document.querySelector("#co-detail-title")?.textContent ?? "",
      text: document.querySelector("aside.co-detail")?.innerText ?? "" })`);
    await press("Escape");
    return { rows, grasberg: rows.filter((row) => GRASBERG.includes(row.id)), detail };
  };
  const ownershipNotInNames = async (state) => {
    const { rows, grasberg, detail } = await grasbergRows();
    check(`(${state}) the four Grasberg copper figures read Withheld, and neither their names, their accessible labels `
      + "nor the detail carry FCX's ownership share",
      grasberg.length === 4 && grasberg.every((row) => row.state === "withheld" && row.name === GRASBERG_NAME &&
        row.label.startsWith(`Withheld: ${GRASBERG_NAME}, `) && !`${row.name} ${row.label}`.includes(OWNERSHIP)) &&
      detail.heading === GRASBERG_NAME && !detail.text.includes(OWNERSHIP), q({ grasberg, heading: detail.heading }));
    const withheld = rows.filter((row) => row.state === "withheld");
    const named = withheld.filter((row) => PERCENT.test(`${row.name} ${row.label}`));
    check(`(${state}) no withheld figure's name or accessible label carries a percentage (${withheld.length} withheld)`,
      withheld.length > 100 && named.length === 0, q(named.slice(0, 3)));
  };

  await size(1280, 900);
  check("the page opens at /companies/fcx", await load("/companies/fcx"));
  check("the header names the company and the status says four of four files match and no valuation",
    await evaluate(`document.querySelector("#co-title").textContent === "Freeport-McMoRan (FCX)" &&
      /4 of 4 source files match/.test(document.querySelector("[data-read]").textContent) &&
      document.querySelector("[data-read]").dataset.read === "available" &&
      document.querySelector("[data-read]").textContent.includes("No valuation, target price or advice.")`));
  const first = await evaluate(`(() => { const top = (e) => e.getBoundingClientRect().top;
    return { summary: top(document.querySelector(".co-summary")), tiles: [...document.querySelectorAll(".co-tile")].map(top),
      change: top(document.querySelector(".co-change")), count: document.querySelectorAll(".co-tile").length,
      changes: document.querySelectorAll(".co-change").length, height: innerHeight }; })()`);
  check("the first screen holds the summary, the six key figures and the first lines of what changed",
    first.count === 6 && first.changes >= 3 && first.changes <= 6 && first.summary < first.height &&
    first.tiles.every((top) => top < first.height) && first.change < first.height, q(first));
  check("by default only the overview is built: no table, no register, the other panels empty",
    await evaluate(`document.querySelectorAll('[data-panel="overview"] table').length === 0 &&
      !document.querySelector("[data-register]") &&
      [...document.querySelectorAll("[data-panel]")].filter((p) => p.dataset.panel !== "overview")
        .every((p) => p.hidden && p.childElementCount === 0)`));
  check("the summary carries the AI authorship stamp",
    await evaluate(`document.querySelector(".co-summary .co-stamp")?.textContent === "AI-drafted, not reviewed by the owner"`));

  const figureCheck = (list) => list.filter((item) => {
    const record = records[item.id];
    if (!record || item.state !== "available") return true;
    const expected = record.kind === "published" ? record.display : record.value;
    const badge = record.kind === "computed" ? "C" : record.period.kind === "outlook" ? "F" : "P";
    return digits(item.text) !== digits(expected) || item.badge !== badge;
  });
  const tabs = ["", "#business", "#numbers", "#numbers:nine-months", "#numbers:year", "#mechanisms", "#questions", "#method"];
  const wrong = [], typed = [], sideways = [];
  let seen = 0;
  for (const hash of tabs) {
    await load(`/companies/fcx${hash}`);
    await evaluate(`document.querySelectorAll("article[data-company] details").forEach((d) => { d.open = true; }); true`);
    await sleep(150);
    const list = await evaluate(figures);
    seen += list.length;
    wrong.push(...figureCheck(list).map((item) => `${hash || "#overview"} ${item.id} ${item.text}`));
    typed.push(...(await evaluate(ownWords)).filter((text) => /\d/.test(text.replace(ALLOWED, ""))));
    if (!(await evaluate(noSideways))) sideways.push(hash || "#overview");
  }
  check("every figure on every tab reads as its record, with the badge of its kind (P, F or C)",
    wrong.length === 0 && seen > 300, `${seen} figures; ${wrong.slice(0, 5).join("; ")}`);
  check("no page text types a number: every digit outside years and form names comes from a record",
    typed.length === 0, typed.slice(0, 3).join(" | "));
  check("no tab scrolls sideways at desktop width, every fold open", sideways.length === 0, sideways.join(", "));

  // The figure detail, by mouse and by keyboard.
  await load("/companies/fcx");
  await evaluate(`document.querySelector('.co-tile .co-fig[data-figure="r3-cu-sales-q3-2026"]').click(); true`);
  const quote = records["r3-cu-sales-q3-2026"].quote;
  check("a click on a figure opens its detail with source, date kind, page and the quote, focus inside",
    await waitFor(`!!document.querySelector('aside[data-detail="r3-cu-sales-q3-2026"]')`, 5000) &&
    await evaluate(`(() => { const a = document.querySelector("aside.co-detail"); const t = a.textContent;
      return t.includes("Freeport Reports Third-Quarter") && t.includes("(dateline)") && t.includes("Page") &&
        t.includes(${q(quote)}) && a.contains(document.activeElement); })()`));
  await press("Escape");
  check("Escape closes the detail and returns focus to the figure",
    await waitFor(`!document.querySelector("aside.co-detail")`, 3000) &&
    await waitFor(`${focusedFigure} === "r3-cu-sales-q3-2026"`, 3000));
  let found = -1;
  await evaluate(`document.querySelector("#co-tab-overview").focus(); true`);
  for (let count = 1; count <= 60 && found < 0; count++) {
    await press("Tab");
    if (await evaluate(`${focusedFigure} !== null`)) found = count;
  }
  const keyed = await evaluate(focusedFigure);
  await press("Enter");
  check("Tab reaches a figure and Enter opens its detail", found > 0 &&
    await waitFor(`document.querySelector("aside.co-detail")?.dataset.detail === ${q(keyed)}`, 3000), `${found} ${keyed}`);
  const computedId = "c-ocf-less-capex-9m-2026";
  await press("Escape");
  await evaluate(`document.querySelector('.co-tile .co-fig[data-figure="${computedId}"]').click(); true`);
  check("a computed figure's detail shows its formula, its inputs and half-even rounding",
    await waitFor(`document.querySelector("aside.co-detail")?.dataset.detail === "${computedId}"`, 3000) &&
    await evaluate(`(() => { const t = document.querySelector("aside.co-detail").textContent;
      return t.includes(${q(records[computedId].formula)}) && t.includes("half to even") &&
        document.querySelectorAll("aside.co-detail .co-inputs li").length === ${Object.keys(records[computedId].inputs).length}; })()`));
  await press("Escape");

  // Tabs, the why-and-how lines, folds and the Numbers views by keyboard.
  const selected = `document.querySelector('.co-tabs [aria-selected="true"]')?.dataset.tab`;
  await evaluate(`document.querySelector("#co-tab-overview").focus(); true`);
  await press("ArrowRight");
  const afterRight = await evaluate(`[${selected}, location.hash, !document.querySelector('[data-panel="business"]').hidden]`);
  await press("End");
  const afterEnd = await evaluate(selected);
  await press("Home");
  const afterHome = await evaluate(selected);
  await press("ArrowLeft");
  const afterWrap = await evaluate(selected);
  check("arrow keys, Home and End move between the tabs and keep the tab in the address",
    same(afterRight, ["business", "#business", true]) && afterEnd === "method" && afterHome === "overview" &&
    afterWrap === "method", q([afterRight, afterEnd, afterHome, afterWrap]));
  await load("/companies/fcx");
  await evaluate(`document.querySelector('.co-change[data-change="revenue"] .co-more').focus(); true`);
  await press("Enter");
  check("Enter on a what-changed line opens why and how: the bridge lines and the company's words",
    await evaluate(`(() => { const b = document.querySelector('.co-change[data-change="revenue"] .co-more');
      const d = document.getElementById(b.getAttribute("aria-controls"));
      return b.getAttribute("aria-expanded") === "true" && !d.hidden && d.textContent.includes("Atlantic Copper"); })()`));
  await load("/companies/fcx#business");
  await evaluate(`document.querySelector('details[data-part="assets"] > summary').focus(); true`);
  await press("Space");
  check("Space opens a fold: the key assets table", await waitFor(
    `document.querySelector('details[data-part="assets"]').open && !!document.querySelector('details[data-part="assets"] table')`, 3000));

  await load("/companies/fcx#numbers");
  const note = (view) => `(() => { const n = document.querySelector('[data-view="${view}"] tr[data-note="Operating cash flows"]');
    return n ? n.textContent : ""; })()`;
  const quarterNote = await evaluate(note("quarter"));
  check("the quarter table keeps both 2025 operating cash flow figures beside the row, and says neither is explained",
    quarterNote.includes("Neither document explains the difference") && quarterNote.includes("1,664") &&
    quarterNote.includes("1,689") && !/restat|correct/i.test(quarterNote), quarterNote);
  await evaluate(`document.querySelector("#co-view-quarter").focus(); true`);
  await press("ArrowRight");
  const nineNote = await evaluate(note("nine-months"));
  check("ArrowRight switches to nine months, in the address, with the nine-month note (4,917 and 4,942)",
    (await evaluate(`location.hash`)) === "#numbers:nine-months" && nineNote.includes("4,917") && nineNote.includes("4,942"),
    nineNote);
  const columns = await evaluate(`[...document.querySelectorAll('[data-view="nine-months"] table')].map((t) =>
    [...t.querySelectorAll("thead th")].map((th) => th.textContent).join("|"))`);
  check("a Numbers view never puts quarter and nine-month figures in one table",
    columns.length > 0 && columns.every((head) => !(head.includes("Q3") && head.includes("9M"))), q(columns));
  await evaluate(`document.querySelector('details[data-part="nine-months-The company\\'s revenue bridge"]').open = true; true`);
  check("the company's revenue bridge is in the view, with the group sums and the check that it adds up (zero)",
    await waitFor(`(() => { const t = document.querySelector('details[data-part="nine-months-The company\\'s revenue bridge"] table');
      return t && t.querySelectorAll("tbody tr").length === 17 &&
        t.querySelector('tr[data-row="Check: the bridge adds up (zero)"] .co-fig-text')?.textContent === "0"; })()`, 3000));
  await evaluate(`document.querySelector('details[data-part="register"]').open = true; true`);
  const register = await waitFor(`!!document.querySelector("[data-register] tbody tr")`, 5000) &&
    await evaluate(`[document.querySelectorAll("[data-register] tbody tr").length,
      document.querySelector("[data-register] [role=status]").textContent]`);
  check("Every figure opens only on request, a hundred rows at a time, filterable",
    Array.isArray(register) && register[0] === 100 && register[1] === `${Object.values(records).filter((r) => r.kind !== "assumption").length} of ${
      Object.values(records).filter((r) => r.kind !== "assumption").length} figures`, q(register));

  await load("/companies/fcx#mechanisms");
  const cards = await evaluate(`[...document.querySelectorAll('.co-sens > .co-cards .co-card')].map((c) => ({ id: c.dataset.sensitivity,
    value: c.querySelector(".co-card-value").textContent, caption: c.querySelector(".co-caption").textContent,
    rest: (() => { const x = c.cloneNode(true); x.querySelector(".co-caption").remove(); return x.textContent; })() }))`);
  check("the two copper sensitivities sit side by side as published, each with the fixed caption and no other earnings word",
    cards.length === 2 && cards[0].value.startsWith("$75 million") && cards[1].value.startsWith("$330 million") &&
    cards.every((c) => c.caption.includes("It is not an earnings, EBITDA or share-price sensitivity.") &&
      !/EBITDA|earnings|per share/i.test(c.rest)), q(cards.map((c) => [c.id, c.value])));
  const bagdad = await evaluate(`(() => { const b = document.querySelector("[data-bagdad]");
    return { decided: b.querySelector('[data-badge="decision"]').textContent, estimate: b.querySelector('[data-badge="estimate"]').textContent,
      decidedFigures: b.querySelectorAll('[data-part="decided"] .co-fig').length,
      badges: [...b.querySelectorAll('[data-part="estimates"] .co-estimates .co-kind')].map((k) => k.textContent) }; })()`);
  check("Bagdad keeps the board's decision apart from the company's estimates, each estimate badged F",
    bagdad.decided === "Decision, as stated by the company on 4 Nov 2026" && bagdad.estimate.startsWith("Company estimate") &&
    bagdad.decidedFigures === 0 && bagdad.badges.length === 9 && bagdad.badges.every((b) => b === "F"), q(bagdad));

  await load("/companies/fcx#method");
  const method = await evaluate(`[...document.querySelectorAll("[data-source]")].map((s) => [s.dataset.source, s.dataset.state,
    s.querySelector(".co-source-meta").textContent])`);
  check("the sources show four verified documents, each date with its kind, and no filing date claimed",
    method.length === 4 && method.every(([, state]) => state === "verified") &&
    method.find(([id]) => id === "10q-2026q3")[2].includes("6 Nov 2026 (signature date)") &&
    method.find(([id]) => id === "news-2026-11-04")[2].includes("4 Nov 2026 (dateline)") &&
    method.every(([, , meta]) => !/filed|filing date/i.test(meta)), q(method));
  check("the refused request for the Bagdad detail page is listed as a request, not a source",
    await evaluate(`document.querySelector("[data-requests]")?.textContent.includes("HTTP 403") ?? false`));

  let pageText = "", ownText = "";
  for (const hash of tabs) {
    await load(`/companies/fcx${hash}`);
    await evaluate(`document.querySelectorAll("article[data-company] details").forEach((d) => { d.open = true; }); true`);
    pageText += await evaluate(`document.querySelector("article[data-company]").innerText`);
    ownText += await evaluate(`(() => { const c = document.querySelector("article[data-company]").cloneNode(true);
      c.querySelectorAll("[data-read], .co-quote, blockquote, .co-fig").forEach((e) => e.remove()); return c.innerText; })()`);
  }
  check("no page says restated, restatement or corrected", !/restat|\bcorrect(ed|ion)\b/i.test(pageText));
  check("no recommendation or price-direction phrasing in the page's own words (the company's quoted words aside)",
    affirmative(ownText).length === 0, affirmative(ownText).join(", "));
  check("target price appears only in the status line's denial",
    (pageText.match(/target price/gi) ?? []).length === tabs.length);

  // Phone width.
  await size(390, 844, true);
  await load("/companies/fcx");
  const phone = await evaluate(`({ sideways: ${noSideways}, summary: document.querySelector(".co-summary").getBoundingClientRect().top,
    tiles: [...document.querySelectorAll(".co-tile")].map((t) => Math.round(t.getBoundingClientRect().width)) })`);
  check("on a phone the page does not scroll sideways and the figures sit two to a row", phone.sideways &&
    phone.summary < 844 && phone.tiles.every((w) => w <= 195), q(phone));
  const order = await evaluate(`(() => { const top = (s) => document.querySelector(s).getBoundingClientRect().top;
    const size = (s) => parseFloat(getComputedStyle(document.querySelector(s)).fontSize);
    return { summary: top(".co-summary"), figures: top(".co-tiles"), changes: top(".co-changes"),
      lines: document.querySelectorAll(".co-summary-text .co-line").length,
      more: document.querySelector('details[data-part="summary-more"]')?.open,
      stamp: document.querySelector(".co-summary .co-stamp")?.textContent,
      summarySize: size(".co-summary-text .co-line p"), changeSize: size(".co-change > p"),
      tileSize: size(".co-tile-value") }; })()`);
  check("on a phone the reading order is the short summary, then the key figures, then what changed",
    order.summary < order.figures && order.figures < order.changes, q(order));
  check("the visible summary is three sentences with the AI stamp, and the fuller summary is a closed fold",
    order.lines === 3 && order.more === false && order.stamp === "AI-drafted, not reviewed by the owner", q(order));
  check("text was not made smaller to fit: summary 16.5px, what changed 15px, figures 24px on a phone",
    order.summarySize === 16.5 && order.changeSize === 15 && order.tileSize === 24, q(order));
  const phoneSideways = [];
  for (const hash of tabs) {
    await load(`/companies/fcx${hash}`);
    await evaluate(`document.querySelectorAll("article[data-company] details").forEach((d) => { d.open = true; }); true`);
    await sleep(120);
    if (!(await evaluate(noSideways))) phoneSideways.push(hash || "#overview");
  }
  check("no tab scrolls sideways on a phone, every fold open: wide tables scroll in their frames",
    phoneSideways.length === 0, phoneSideways.join(", "));
  await load("/companies/fcx");
  await evaluate(`document.querySelector(".co-tile .co-fig").click(); true`);
  check("on a phone the figure detail is a sheet from the bottom, full width, and the page still does not scroll sideways",
    await waitFor(`!!document.querySelector("aside.co-detail")`, 3000) && await evaluate(`(() => {
      const r = document.querySelector("aside.co-detail").getBoundingClientRect();
      return Math.abs(r.bottom - innerHeight) < 2 && Math.abs(r.width - innerWidth) < 2 && ${noSideways}; })()`));
  await size(1280, 900);

  await load("/library", `!!document.querySelector('[data-company-card="fcx"] a[href="/companies/fcx"]')`);
  check("the library lists FCX under Company research, beside the theses",
    await evaluate(`(() => { const s = document.querySelector("[data-companies]");
      return s.querySelector("h2").textContent === "Company research" &&
        s.querySelectorAll("[data-company-card]").length === 1 && !!document.querySelector("#theses"); })()`));
  await evaluate(`document.querySelector('[data-company-card="fcx"] a').click(); true`);
  check("the library card opens the company page", await waitFor(`location.pathname === "/companies/fcx" && ${ready}`, 10000));
  await load("/theses/copper", `!!document.querySelector('[data-tools="company"] a[href="/companies/fcx"]')`);
  check("the copper thesis links to the company page in context, beside the copper tools and metals",
    await evaluate(`(() => { const p = document.querySelector('[data-tools="company"]').closest(".thesis-tools");
      return !!p && !!p.querySelector('a[href="/metals"]') && !!p.querySelector('a[href="/theses/copper/tools"]'); })()`));
  const kept = await grasbergRows();
  check("the Grasberg copper figures are shown under a name without FCX's ownership share, which is its own record",
    kept.grasberg.length === 4 && kept.grasberg.every((row) => row.state === "available" && row.name === GRASBERG_NAME) &&
    kept.rows.some((row) => row.id === "r3-ptfi-ownership" && row.state === "available"), q(kept.grasberg));
  check("no page error or console error", errors.length === 0, q(errors.slice(0, 3)));
  check("the browser asked only the local server", requests.every((r) => r.url.startsWith(base) || r.url.startsWith("about:")
    || r.url.startsWith("data:")), q(requests.filter((r) => !r.url.startsWith(base)).slice(0, 3)));
  if (shots) await takeShots(shots, { send, load, evaluate, sleep });

  // ---------------------------------------------------------------- one byte of the Bagdad release changed
  at = await startServer("changed");
  const changed = await (await fetch(`${at}/api/companies/fcx`)).json();
  check("(changed) the server marks the Bagdad release changed and withholds what rests on it",
    changed.sources.find((s) => s.id === "news-2026-11-04").state === "changed" && changed.verified === 3 &&
    changed.records["nr-bagdad-capex-estimate"].value === null && changed.records["c-bagdad-funding-2027"].value === null &&
    changed.records["r3-cu-sales-q3-2026"].state === "available");
  await load("/companies/fcx");
  check("(changed) the status says three of four and that figures resting on the other are not shown",
    await evaluate(`(() => { const s = document.querySelector("[data-read]");
      return s.dataset.read === "withheld" && s.textContent.includes("3 of 4") && s.textContent.includes("not shown"); })()`));
  check("(changed) the Bagdad line of the summary is not shown and names the document; the other lines are",
    await evaluate(`(() => { const lines = [...document.querySelectorAll(".co-summary-text .co-line")];
      return lines.length === 3 && lines.slice(0, 2).every((l) => l.dataset.state === "available") &&
        lines[2].dataset.state === "withheld" && lines[2].textContent.includes("the Bagdad release of 4 November 2026"); })()`));
  let changedText = "";
  for (const hash of ["", "#mechanisms", "#numbers", "#business", "#method"]) {
    await load(`/companies/fcx${hash}`);
    await evaluate(`document.querySelectorAll("article[data-company] details").forEach((d) => { d.open = true; }); true`);
    changedText += await evaluate(`document.querySelector("article[data-company]").innerText`);
    if (hash === "#mechanisms") {
      check("(changed) every Bagdad estimate reads Withheld with the M badge",
        await evaluate(`[...document.querySelectorAll('[data-part="estimates"] .co-fig')].every((b) =>
          b.dataset.state === "withheld" && b.textContent.startsWith("Withheld") && b.querySelector(".co-kind").textContent === "M")`));
    }
  }
  const newsQuotes = [...facts.passages, ...facts.records].filter((x) => x.source === "news-2026-11-04").map((x) => x.quote);
  check("(changed) no quote from the changed document appears anywhere on the page",
    newsQuotes.length > 20 && newsQuotes.every((text) => !changedText.includes(text)));
  check("(changed) the sources list the Bagdad release as changed", changedText.includes("Changed:"));
  check("(changed) the reply carries nothing but identification for what is withheld: no note, explanation, label, "
    + "assumption statement or words of a line", replyLeaks(changed).length === 0, replyLeaks(changed).slice(0, 3).join("; "));
  const changedForbidden = forbiddenIn(changed, reply);
  check("(changed) no note, explanation, quote or assumption resting on the changed document is in the reply",
    changedForbidden.length > 20 && changedForbidden.every((text) => !JSON.stringify(changed).includes(text)));
  await load("/companies/fcx#mechanisms");
  await evaluate(`document.querySelectorAll("article[data-company] details").forEach((d) => { d.open = true; }); true`);
  await evaluate(`document.querySelector('.co-fig[data-figure="c-bagdad-funding-2027"]').click(); true`);
  await waitFor(`document.querySelector("aside.co-detail")?.dataset.detail === "c-bagdad-funding-2027"`, 3000);
  const fundingDetail = await evaluate(`document.querySelector("aside.co-detail").innerText`);
  check("(changed) the detail of a withheld computation shows its formula and why, but no explanation and no assumption text",
    fundingDetail.includes("c * s / 100") && fundingDetail.includes("Bagdad release of 4 November 2026") &&
    !fundingDetail.includes("$4.5 billion") && !/\nUnits\n/.test(fundingDetail) &&
    !fundingDetail.includes("Applies the company's stated funding shares"), fundingDetail.slice(0, 400));
  await press("Escape");
  await sweep("changed", changedForbidden, ["#mechanisms", "", "#business"], 17);  // the 9 estimates and 8 computations
  if (shots) await takeShots(shots, { send, load, evaluate, sleep }, "changed-");

  // ---------------------------------------------------------------- the results release missing
  at = await startServer("missing");
  await load("/companies/fcx");
  check("(missing) all six key figures read Withheld, and the status says three of four",
    await evaluate(`[...document.querySelectorAll(".co-tile .co-tile-value .co-fig")].every((b) => b.dataset.state === "withheld") &&
      document.querySelector("[data-read]").textContent.includes("3 of 4")`));
  await load("/companies/fcx#numbers:year");
  check("(missing) the year view, from the 10-K, still shows its figures",
    await evaluate(`document.querySelector('[data-view="year"] .co-fig[data-figure="k25-revenues-fy2025"]')?.dataset.state === "available"`));
  await load("/companies/fcx#method");
  check("(missing) the sources say the results release is missing", await evaluate(
    `document.querySelector('[data-source="release-2026q3"]').dataset.state === "missing"`));
  const missing = await (await fetch(`${at}/api/companies/fcx`)).json();
  check("(missing) the reply carries nothing but identification for what is withheld",
    replyLeaks(missing).length === 0, replyLeaks(missing).slice(0, 3).join("; "));
  check("(missing) the reported case: r3-ocf-9m-2026 carries no note in the reply",
    missing.records["r3-ocf-9m-2026"].state === "withheld" && !("note" in missing.records["r3-ocf-9m-2026"]) &&
    !JSON.stringify(missing).includes("cash used for working capital was $0.4 billion"));
  await load("/companies/fcx");
  await evaluate(`document.querySelector('.co-tile .co-fig[data-figure="r3-ocf-9m-2026"]').click(); true`);
  await waitFor(`document.querySelector("aside.co-detail")?.dataset.detail === "r3-ocf-9m-2026"`, 3000);
  const ocfDetail = await evaluate(`document.querySelector("aside.co-detail").innerText`);
  check("(missing) the reported case in the browser: its detail names the source, page and why, and shows no note",
    ocfDetail.includes("Freeport Reports Third-Quarter") && ocfDetail.includes("Why it is not shown") &&
    !/\nNote\n/.test(ocfDetail) && !ocfDetail.includes("working capital") && !ocfDetail.includes("0.8 billion"),
    ocfDetail.slice(0, 500));
  await press("Escape");
  const missingForbidden = forbiddenIn(missing, reply);
  await sweep("missing", missingForbidden, ["", "#numbers", "#mechanisms", "#scenarios", "#scenarios:cash-flow"], 60);
  await load("/companies/fcx#numbers:year");
  await evaluate(`document.querySelector('[data-view="year"] .co-fig[data-figure="k25-revenues-fy2025"]').click(); true`);
  check("(missing) a figure from a verified document keeps its detail: quote and note",
    await waitFor(`document.querySelector("aside.co-detail")?.dataset.detail === "k25-revenues-fy2025"`, 3000) &&
    await evaluate(`(() => { const t = document.querySelector("aside.co-detail").innerText;
      return t.includes(${q(records["k25-revenues-fy2025"].quote)}) && t.includes("Note"); })()`));
  await press("Escape");
  await ownershipNotInNames("missing");
  if (shots) await takeShots(shots, { send, load, evaluate, sleep }, "missing-");

  // ---------------------------------------------------------------- one byte of the results release changed
  at = await startServer("release-changed");
  const releaseChanged = await (await fetch(`${at}/api/companies/fcx`)).json();
  check("(release changed) the server marks the results release changed and withholds the figures resting on it",
    releaseChanged.sources.find((s) => s.id === "release-2026q3").state === "changed" && releaseChanged.verified === 3 &&
    GRASBERG.length === 4 && GRASBERG.every((id) => releaseChanged.records[id].state === "withheld"));
  check("(release changed) the reply carries nothing but identification for what is withheld",
    replyLeaks(releaseChanged).length === 0, replyLeaks(releaseChanged).slice(0, 3).join("; "));
  await ownershipNotInNames("release changed");

  // ---------------------------------------------------------------- access
  at = await startServer("retained", true);
  const signedOut = await fetch(`${at}/api/companies/fcx`);
  const sessionHeaders = { Origin: at, "Content-Type": "application/json", "X-Second-Order-Session": "1" };
  const signIn = async (username) => {
    const reply = await fetch(`${at}/api/session/login`, { method: "POST", headers: sessionHeaders,
      body: JSON.stringify({ username, password: PASSWORDS[username] }) });
    return (reply.headers.get("set-cookie") ?? "").split(";")[0];
  };
  const readerCookie = await signIn("reader-a"), adminCookie = await signIn("admin");
  const asReader = await fetch(`${at}/api/companies/fcx`, { headers: { Cookie: readerCookie } });
  const readerBody = await asReader.text();
  const asAdmin = await fetch(`${at}/api/companies/fcx`, { headers: { Cookie: adminCookie } });
  check("signed out 401, a reader 403 with nothing of the research, an admin 200",
    signedOut.status === 401 && asReader.status === 403 && !readerBody.includes("Grasberg") && asAdmin.status === 200,
    `${signedOut.status} ${asReader.status} ${asAdmin.status}`);
  const setCookie = async (cookie) => {
    await send("Network.clearBrowserCookies");
    const [name, value] = cookie.split("=");
    await send("Network.setCookie", { name, value, url: at });
  };
  await setCookie(readerCookie);
  await send("Page.navigate", { url: `${at}/companies/fcx` });
  await sleep(2500);
  check("a reader opening /companies/fcx gets the Client build, never the company page",
    await evaluate(`document.readyState === "complete" && !document.querySelector("article[data-company]") &&
      !document.body.innerText.includes("Grasberg")`));
  await send("Page.navigate", { url: `${at}/library` });
  await sleep(2000);
  check("a reader's build has no company card", await evaluate(`!document.querySelector("[data-company-card]")`));
  await setCookie(adminCookie);
  check("an admin opening /companies/fcx gets the page", await load("/companies/fcx"));
  close();

  check("the retained documents and the research folder are unchanged after every read",
    same(tree(data), dataBefore) && same(tree(research), researchBefore));
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
