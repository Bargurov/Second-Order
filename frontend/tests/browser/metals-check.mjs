// Browser check of the metals page (/metals), against tests/review_browser_server.py serving a new, empty folder with
// --metals synthetic (the SYNTHETIC USGS CSV and IEA workbook of tests/metals_fakes.py, retained with their acquisition
// records, and a matching sources file), or, as an explicit opt-in, SECOND_ORDER_THESIS_SOURCES=<the retained
// data/sector-sources/copper folder> (the committed content/metals against the real retained files, served read-only;
// the step that changes a retained file runs only on the synthetic copy). SECOND_ORDER_SCREENSHOTS=<folder> also saves
// desktop and phone screenshots. It checks, by step:
//  1. discovery: the case library's copper entry and the copper thesis page link to /metals, and the link opens it;
//  2. the first screen: a short header, the picker closed (its button says "6 of 45", the names follow), the Overview
//     tab selected with the six default picks in its table, the other two tabs' panels hidden;
//  3. the picker: Tab reaches its button with a visible focus; Enter opens it on the search box; the list is one column
//     read top to bottom, the order ArrowDown follows; typing filters the
//     list; ArrowDown reaches a checkbox, Space ticks it (rows and address follow, the panel stays open); a click ticks
//     another (several at once); Escape closes and returns focus; a click outside and a Tab past the last control close
//     it; Defaults, Clear (the empty state's "Pick metals" reopens it) and Done; a search with no match says so; the
//     picks survive a reload and a tab change, and ?m=cobalt,nosuch,../x ignores two names;
//  4. the tabs: arrow keys, Home and End move and select with a visible focus; the hash follows (#by-metal, #method,
//     none for the overview) and opens its tab on load (#by-metal:copper too); a metal's name in the table opens it;
//  5. the overview's values: cobalt's top producer, Congo (Kinshasa) 74.2%; the United States printed "W" (synthetic:
//     nickel; real: lithium): a short label whose "Why?" opens the full reason; copper's 43 years with the years caveat
//     beside it; a dash read as zero (synthetic: tin, Delta; real: copper's Germany); vanadium's years "Unit in doubt"
//     with the unit issue's words; (synthetic) silver's "less than 1 year"; headings and scope line naming the ranking
//     as among named countries; the reserves column naming its series; the how-to closed until opened;
//  6. by metal, one metal at a time: its parts closed on arrival (Enter and Space open and close one); every metal
//     visited: each world total labelled as rounded exactly where the reply says so, an IEA part only on the six
//     mapped chapters, vanadium's reserves giving the unit issue with no quantity or unit and every share; a table's
//     foot ranking named countries with "Other countries" one unsplit group; rare earths' scope note; the scenario
//     select changing the demand values; the usgs and iea sections apart; the chooser following arrow keys;
//  7. (synthetic only) a changed byte in the retained CSV, then, restored, in the workbook: the page says the part is
//     withheld, every metal visited with its parts open shows the withheld part as frames only, and nothing only the
//     withheld file holds (values, countries, details, notes, reasons) is anywhere on the page, in any tab, hidden
//     text and attributes included; the page's own words (notes, ranking line) are unchanged; the other part stays;
//  8. every focusable element has an accessible name, with the picker open, a metal's parts open and the method tab;
//  9. at 375 px: no sideways scroll on the first screen, with the picker open (its panel inside the screen, a tap
//     ticks a metal, Done closes it), and with every metal picked and a metal's parts open;
// 10. hygiene: only GET requests, to the local server only; no page errors; no affirmative recommendation or price
//     direction in the page's own words; the retained sources and committed content unchanged;
// 11. (real, opt-in) both sources verified, cobalt 74.2%, the lithium top-3 reason, copper 43 years, folder unchanged.
// Stage 2 (metals-stage2.mjs reads each part off the page and compares it with the reply; metals-controls.mjs drives
// the new controls with real key presses):
// 12. every metal: the snapshot always open (outside every fold) with a source line on each item; the supply chain's
//     printed stages (a missing stage's exact sentence), the "Final products" sentence and the IEA block labelled apart;
//     Concentration & risk's CR1, CR3 and HHI range with the named countries' coverage, and its import-source rows;
//     Industrial uses' IEA energy-technology table; Geopolitical exposure's verified events or the exact NO_EVENT
//     sentence with the unverified citations listed apart; Economic transmission's written-by sentence and every link
//     (Measured / Stated by a source / Hypothesis) with its value, coverage, quote or reason; all equal to the reply;
//     copper's three events (synthetic: all unverified; real: the two thesis events verified, quoted, and the FCX
//     event listed apart, its documents not served here); the three link kinds all present;
// 13. every new fold closed on arrival and opening and closing with Enter and Space; each About note opens with its
//     formula, source and year; the uses part's scenario and year selects change the IEA table; the overview's
//     Leaders | Concentration switch (Tab reaches it, aria-pressed follows, the table shows the reply);
// 14. (synthetic) with the CSV changed (risk withheld) and with the workbook changed (uses withheld): every metal, every
//     fold open, shows the withheld part's problem and none of its values (the risk and uses figures and words are in
//     the whole-page leak scan), and research's measured links show no value for a withheld part;
// 15. every new control has an accessible name; at 375 px every new fold open does not scroll sideways.
//
//   cd frontend; npm run build; npm run test:browser:metals
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { affirmative, chromeOf, chromePath, controlNames, freePort, given, ieaLabels, ieaValues, leaks, occurrences, occurs,
  riskLabels, riskValues, same, shownScript, sleep, startChrome, startServer, strings, tree, usesLabels, usesValues,
  usgsLabels, usgsValues, where } from "./metals-kit.mjs";
import { phoneFolds, stage2Checks } from "./metals-controls.mjs";
import { takeShots } from "./metals-shots.mjs";
import { NEW_FOLDS, PAGE, verifyMetal } from "./metals-stage2.mjs";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const python = process.env.SECOND_ORDER_PYTHON ?? "python";
const realSources = process.env.SECOND_ORDER_THESIS_SOURCES
  ? resolve(repo, process.env.SECOND_ORDER_THESIS_SOURCES) : undefined;
const shots = process.env.SECOND_ORDER_SCREENSHOTS;
if (!chromePath) throw new Error("Chrome was not found; set SECOND_ORDER_CHROME to its executable.");
if (!existsSync(join(repo, "frontend/dist/index.html"))) throw new Error("Build the client first: npm run build");
if (realSources && !existsSync(realSources)) throw new Error("SECOND_ORDER_THESIS_SOURCES names no folder.");

const root = mkdtempSync(join(tmpdir(), "second-order-metals-check-"));
const served = join(root, "served");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(!!ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const DEFAULTS = ["copper", "lithium", "cobalt", "rare-earths", "nickel", "aluminum"];
const YEARS_LABEL = "at the 2025 rate; not a depletion date";
const sources = realSources ?? join(served, "metals-sources");
const wMetal = realSources ? "lithium" : "nickel";  // The metal whose 2025 mine production prints the United States as "W".
const q = JSON.stringify;

try {
  check("the phrasing scan flags affirmative phrasings and passes the lines that name what they deny",
    affirmative("No price view, projection or advice. Not a depletion date.").length === 0 &&
    ["PRICES WILL RISE", "there is a shortage", "the upside case", "time to sell", "we recommend"]
      .every((phrase) => affirmative(phrase).length > 0));
  check("the figure match finds whole figures, codes and words only",
    occurs("W", "Printed as “W”") && occurs("74.2", "Congo (Kinshasa) 74.2%") && occurs("300", "0.1% of 300") &&
    occurs("Congo (Kinshasa)", "Congo (Kinshasa)74.2%") && occurs(">95", "1>95") && !occurs("5", "2025") &&
    !occurs("W", "Where") && !occurs("2,000", ">2,000,000") && !occurs("300", "2,300") && !occurs("China", "Chinatown"));

  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const getJson = async (path) => (await fetch(`${base}${path}`)).json();
  await startServer({ python, repo, served, port, args: ["--metals", realSources ?? "synthetic"], children });
  const sourcesBefore = tree(sources);
  const contentBefore = tree(join(repo, "content"));
  const metalsContent = realSources ? join(repo, "content/metals") : join(served, "metals-content");
  const metalsContentBefore = tree(metalsContent);
  const { send, evaluate, waitFor, press, type, focused, tabTo, requests, errors, close } =
    await startChrome({ profile: join(root, "chrome"), children });

  const inner = (selector) => evaluate(`document.querySelector(${q(selector)})?.innerText ?? ""`);
  const pageReady = `!!document.querySelector('article[data-metals] h1') && !!document.querySelector('[data-read]')`;
  /** A fresh page (never a same-document hash change) that satisfies `ready`. */
  const load = async (path, ready = pageReady) => {
    await send("Page.navigate", { url: "about:blank" });
    await waitFor(`location.href === "about:blank"`, 5000);
    await send("Page.navigate", { url: `${base}${path}` });
    return waitFor(`document.readyState === "complete" && (${ready})`);
  };
  const picked = `[...document.querySelectorAll('#compare tbody[data-metal]')].map((e) => e.dataset.metal)`;
  const panelOpen = `!!document.getElementById("mt-picker-panel")`;
  const picker = `(() => { const b = document.querySelector(".mt-picker-button"); return { expanded: b.getAttribute("aria-expanded"),
    count: b.querySelector("[data-count]").innerText.trim(), names: document.querySelector("[data-picked-names]").innerText.trim(),
    open: !!document.getElementById("mt-picker-panel") }; })()`;
  const openPicker = async () => {
    if (!(await evaluate(panelOpen))) await evaluate(`document.querySelector(".mt-picker-button").click(); true`);
    return waitFor(panelOpen, 5000);
  };
  const listed = `[...document.querySelectorAll('.mt-picker-list input')].map((e) => e.value)`;
  const tabState = `(() => ({ selected: document.querySelector('.mt-tabs [aria-selected="true"]')?.dataset.tab ?? null,
    visible: [...document.querySelectorAll("[data-panel]")].filter((p) => !p.hidden).map((p) => p.dataset.panel),
    hash: location.hash, search: location.search }))()`;
  const selectTab = async (id) => {
    await evaluate(`document.getElementById("mt-tab-${id}").click(); true`);
    return waitFor(`!document.getElementById("mt-panel-${id}").hidden && document.getElementById("mt-panel-${id}").childElementCount > 0`, 5000);
  };
  const selectMetal = async (id) => {
    await evaluate(`document.getElementById(${q(`mt-metal-tab-${id}`)})?.click(); true`);
    return waitFor(`document.getElementById("mt-metal-panel")?.dataset.metal === ${q(id)}`, 5000);
  };
  const openFolds = `(() => { const all = [...document.querySelectorAll("#mt-panel-by-metal details")];
    all.forEach((d) => { d.open = true; }); return all.length; })()`;
  /** One comparison row's cells: visible text, a short label, its full reason (hidden or not) and a years figure. */
  const compareRow = (metal, stage) => evaluate(`(() => {
    const rows = [...document.querySelectorAll('#compare tbody[data-metal=${q(metal)}] tr')];
    const row = rows.find((tr) => (tr.querySelector("td")?.innerText ?? "").trim().startsWith(${q(stage)}));
    return row ? [...row.querySelectorAll("td")].map((td) => ({ text: td.innerText.trim(),
      label: td.querySelector(".mt-why-label")?.textContent.trim() ?? null,
      reason: td.querySelector(".mt-why-text")?.textContent.trim() ?? null,
      years: td.querySelector(".mt-years-value")?.innerText.trim() ?? null })) : null; })()`);
  /** One country's cells in the opened metal's USGS table whose caption starts `caption` (its part must be open). */
  const tableRow = (caption, country) => evaluate(`(() => {
    const table = [...document.querySelectorAll('#mt-metal-panel section[data-source="usgs"] table')]
      .find((t) => (t.querySelector("caption")?.innerText ?? "").startsWith(${q(caption)}));
    const row = table && [...table.querySelectorAll("tbody tr")].find((tr) => tr.querySelector("th").innerText.trim() === ${q(country)});
    return row ? [...row.querySelectorAll("td")].map((td) => td.innerText.trim()) : null; })()`);
  // Everything the page holds now, but its own words checked apart (metals-kit.mjs, shownScript). Only the new folds'
  // teasers (counts and words, checked apart) are left out of the scan; stage 1's are scanned.
  const newTeasers = NEW_FOLDS.map((part) => `details[data-part='${part}'] > summary .mt-fold-teaser`).join(", ");
  const shownNow = shownScript(newTeasers);
  const notesText = `document.querySelector("article[data-metals] dl[data-notes]")?.textContent ?? ""`;
  const scopeText = `(() => [...document.querySelectorAll("article[data-metals] :is([data-ranking-scope], [data-howto])")]
    .map((e) => e.textContent).join(" | "))()`;

  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("Log.enable");
  await send("Emulation.setFocusEmulationEnabled", { enabled: true });
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const view = await getJson("/api/metals");
  const ieaChapters = new Map(view.iea.minerals.map((mineral) => [mineral.chapter, mineral]));
  const allIds = view.usgs.chapters.map((chapter) => chapter.id);
  const names = new Map(view.usgs.chapters.map((chapter) => [chapter.id, chapter.name]));
  const everything = `/metals?m=${allIds.join(",")}`;
  const chapterOf = (id) => view.usgs.chapters.find((chapter) => chapter.id === id);
  const mineOf = (id, detail = "Mine production") => chapterOf(id).series
    .find((s) => s.statistic === "Production" && s.year === "2025" && s.detail === detail);
  check("the reply has both parts available over verified sources",
    view.usgs.state === "available" && view.iea.state === "available" &&
    same(view.sources.map((s) => [s.id, s.state]), [["usgs-csv-2026", "verified"], ["iea-dataset-2026", "verified"]]) &&
    allIds.length === 45 && ieaChapters.size === 6, JSON.stringify(view.sources.map((s) => [s.id, s.state])));

  // 1. Discovery.
  await load("/theses/copper", `!!document.querySelector('a[href="/metals"]')`);
  check("the copper thesis page links to /metals", await evaluate(`!!document.querySelector('a[href="/metals"]')`));
  await load("/library", `!!document.querySelector('[data-tools="metals"] a[href="/metals"]')`);
  check("the case library's copper entry links to /metals",
    await evaluate(`!!document.querySelector('[data-thesis="copper"] [data-tools="metals"] a[href="/metals"]')`));
  await evaluate(`document.querySelector('[data-thesis="copper"] [data-tools="metals"] a[href="/metals"]').click()`);
  check("the library's link opens the metals page",
    await waitFor(pageReady) && await evaluate(`location.pathname === "/metals" && location.search === ""`));

  // 2. The first screen.
  await load("/metals");
  const first = await evaluate(picker);
  check("the header says both sources match their records, in one short line",
    await evaluate(`document.querySelector('[data-read]').dataset.read === "available"`) &&
    (await inner("[data-read]")).startsWith("USGS and IEA files match their acquisition records."));
  check("the picker is closed: its button says 6 of 45 and the six names follow, in order",
    first.expanded === "false" && !first.open && first.count === "6 of 45" &&
    first.names === DEFAULTS.map((id) => names.get(id)).join(", ") && same(view.deep, DEFAULTS), JSON.stringify(first));
  const tabsFirst = await evaluate(tabState);
  check("the Overview tab is selected with the six default picks in its table; the other panels are hidden",
    tabsFirst.selected === "overview" && same(tabsFirst.visible, ["overview"]) && same(await evaluate(picked), DEFAULTS) &&
    await evaluate(`document.querySelectorAll("#mt-panel-by-metal *, #mt-panel-method *").length === 0`),
    JSON.stringify(tabsFirst));

  // 3. The picker.
  await evaluate(`document.activeElement?.blur(); window.scrollTo(0, 0); true`);
  const toButton = await tabTo((now) => now.picker);
  const onButton = await focused();
  check("Tab reaches the picker's button from the top of the page, with a visible focus",
    toButton > 0 && onButton?.visible === true, `${toButton} presses; ${JSON.stringify(onButton)}`);
  await press("Enter");
  await waitFor(panelOpen, 5000);
  const onSearch = await focused();
  check("Enter opens the panel on its search box, with a visible focus",
    (await evaluate(picker)).expanded === "true" && onSearch?.search === true && onSearch.visible === true &&
    (await evaluate(listed)).length === 45, JSON.stringify(onSearch));
  // One column: what the eye reads down is the order ArrowDown and Tab follow.
  const layout = await evaluate(`(() => { const r = [...document.querySelectorAll(".mt-picker-list label")].map((e) => e.getBoundingClientRect());
    return { columns: new Set(r.map((x) => Math.round(x.left))).size, down: r.every((x, i) => i === 0 || x.top >= r[i - 1].bottom - 1) }; })()`);
  await press("ArrowDown");
  const firstBox = await focused();
  await press("ArrowDown");
  const secondBox = await focused();
  check("the list reads in one column, top to bottom in USGS order, and ArrowDown moves to the metal below",
    layout.columns === 1 && layout.down && firstBox?.value === "aluminum" && secondBox?.value === "bauxite-and-alumina",
    JSON.stringify({ layout, firstBox, secondBox }));
  await press("ArrowUp");
  await press("ArrowUp");
  await type("baux");
  check("typing filters the list to the matching metal and says how many match",
    same(await evaluate(listed), ["bauxite-and-alumina"]) && (await inner("#mt-picker-status")).startsWith("1 match"),
    JSON.stringify(await evaluate(listed)));
  await press("ArrowDown");
  const onBox = await focused();
  await press("Space");
  await waitFor(`${picked}.includes("bauxite-and-alumina")`, 5000);
  check("ArrowDown reaches its checkbox and Space ticks it: its rows are added last, the address and count follow, " +
    "the panel stays open",
    onBox?.box === true && onBox.value === "bauxite-and-alumina" && onBox.visible === true &&
    same(await evaluate(picked), [...DEFAULTS, "bauxite-and-alumina"]) &&
    await evaluate(`location.search === "?m=copper,lithium,cobalt,rare-earths,nickel,aluminum,bauxite-and-alumina"`) &&
    (await evaluate(picker)).count === "7 of 45" && await evaluate(panelOpen), JSON.stringify(onBox));
  await press("ArrowUp");
  for (let i = 0; i < 4; i++) await press("Backspace");
  await evaluate(`document.querySelector('label[data-pick="gold"]').click(); true`);
  await waitFor(`${picked}.includes("gold")`, 5000);
  check("cleared, the list shows all 45 again, and a click ticks a second metal: several are picked at once",
    (await evaluate(listed)).length === 45 && same(await evaluate(picked), [...DEFAULTS, "bauxite-and-alumina", "gold"]) &&
    (await evaluate(picker)).count === "8 of 45", JSON.stringify(await evaluate(picked)));
  await press("Escape");
  const afterEscape = await focused();
  check("Escape closes the panel and returns focus to the button",
    !(await evaluate(panelOpen)) && afterEscape?.picker === true && (await evaluate(picker)).expanded === "false",
    JSON.stringify(afterEscape));
  await press("Space");
  await waitFor(panelOpen, 5000);
  const title = await evaluate(`(() => { const r = document.querySelector("article[data-metals] h1").getBoundingClientRect();
    return { x: r.left + 20, y: r.top + r.height / 2 }; })()`);
  for (const type of ["mousePressed", "mouseReleased"]) {
    await send("Input.dispatchMouseEvent", { type, x: title.x, y: title.y, button: "left", clickCount: 1 });
  }
  check("Space opens it again, and a click outside closes it", await waitFor(`!${panelOpen}`, 3000));
  await openPicker();
  await evaluate(`document.querySelector(".mt-done").focus(); true`);
  await press("Tab");
  const pastDone = await focused();
  check("Tab past its last control closes it, focus moving on to the tabs",
    !(await evaluate(panelOpen)) && pastDone?.role === "tab", JSON.stringify(pastDone));
  await openPicker();
  await evaluate(`[...document.querySelectorAll(".mt-picker-actions button")].find((b) => b.innerText === "Defaults").click(); true`);
  await waitFor(`${q(DEFAULTS)} === JSON.stringify(${picked})`, 5000);
  const defaultsBack = same(await evaluate(picked), DEFAULTS);
  await evaluate(`[...document.querySelectorAll(".mt-picker-actions button")].find((b) => b.innerText === "Clear").click(); true`);
  await waitFor(`${picked}.length === 0`, 5000);
  const cleared = await evaluate(`({ empty: document.querySelector("#compare .mt-empty")?.innerText ?? "",
    count: document.querySelector("[data-count]").innerText, names: document.querySelector("[data-picked-names]").innerText })`);
  await evaluate(`document.querySelector(".mt-done").click(); true`);
  const doneClosed = await waitFor(`!${panelOpen}`, 3000);
  await evaluate(`document.querySelector("#compare .mt-empty button").click(); true`);
  const reopened = await waitFor(panelOpen, 3000);
  check("Defaults restores the six, Clear empties the table (its \"Pick metals\" reopens the picker), Done closes it",
    defaultsBack && cleared.empty.startsWith("No metal is picked.") && cleared.count === "0 of 45" &&
    cleared.names === "None picked" && doneClosed && reopened, JSON.stringify(cleared));
  await type("zzz");
  check("a search with no match says so", (await inner("#mt-picker-status")).startsWith("0 matches") &&
    (await inner(".mt-picker-empty")) === "No metal matches “zzz”.");
  await press("Escape");
  await load("/metals?m=gold,cobalt");
  const kept = await evaluate(picker);
  const keptRows = await evaluate(picked);
  await selectTab("by-metal");
  const chips = await evaluate(`[...document.querySelectorAll(".mt-chooser [role=tab]")].map((e) => e.dataset.tab)`);
  check("the picks survive a reload and a change of tab: the address keeps ?m and adds the tab",
    same(keptRows, ["gold", "cobalt"]) && kept.count === "2 of 45" &&
    kept.names === "Gold, Cobalt" && same(chips, ["gold", "cobalt"]) &&
    await evaluate(`location.search === "?m=gold,cobalt" && location.hash === "#by-metal"`), JSON.stringify([kept, chips]));
  await load("/metals?m=cobalt,nosuch,../x");
  check("?m=cobalt,nosuch,../x shows cobalt only and says two names were ignored",
    same(await evaluate(picked), ["cobalt"]) &&
    await evaluate(`document.querySelector("[data-ignored]")?.dataset.ignored === "2"`) &&
    (await inner("[data-ignored]")).startsWith("2 names in the address were ignored"), await inner("[data-ignored]"));

  // 4. The tabs.
  await load("/metals");
  await evaluate(`document.activeElement?.blur(); window.scrollTo(0, 0); true`);
  const toTab = await tabTo((now) => now.role === "tab");
  const onTab = await focused();
  const moves = [];
  for (const key of ["ArrowRight", "ArrowRight", "ArrowRight", "End", "Home"]) {
    await press(key);
    const state = await evaluate(tabState);
    moves.push([key, (await focused())?.tab, state.selected, state.visible.join(), state.hash]);
  }
  check("Tab reaches the Overview tab with a visible focus; arrows, Home and End move, select and set the hash",
    toTab > 0 && onTab?.tab === "overview" && onTab.visible === true && same(moves, [
      ["ArrowRight", "by-metal", "by-metal", "by-metal", "#by-metal"], ["ArrowRight", "method", "method", "method", "#method"],
      ["ArrowRight", "overview", "overview", "overview", ""], ["End", "method", "method", "method", "#method"],
      ["Home", "overview", "overview", "overview", ""]]), JSON.stringify([onTab, moves]));
  await load("/metals#method");
  const onMethod = await evaluate(tabState);
  await load("/metals?m=cobalt,copper#by-metal:copper");
  const onCopper = await evaluate(`({ ...${tabState}, metal: document.getElementById("mt-metal-panel")?.dataset.metal })`);
  check("a hash opens its tab on load, and #by-metal:copper its metal",
    onMethod.selected === "method" && onCopper.selected === "by-metal" && onCopper.metal === "copper",
    JSON.stringify([onMethod, onCopper]));
  await load("/metals");
  await evaluate(`document.querySelector('#compare a[data-open-metal="cobalt"]').click(); true`);
  await waitFor(`document.getElementById("mt-metal-panel")?.dataset.metal === "cobalt"`, 5000);
  check("a metal's name in the table opens it under By metal",
    (await evaluate(tabState)).hash === "#by-metal:cobalt" && (await evaluate(tabState)).selected === "by-metal");

  // 5. The overview's values, every metal picked.
  await load(everything);
  const notesAvailable = await (async () => { await selectTab("method"); const text = await evaluate(notesText);
    await selectTab("overview"); return text; })();
  const scopeAvailable = await evaluate(scopeText);
  const cobalt = await compareRow("cobalt", "Mine production");
  check("cobalt's top producer in 2025 is Congo (Kinshasa), 74.2% of world output",
    cobalt?.[1].text === "Congo (Kinshasa) 74.2%", JSON.stringify(cobalt));
  const wSeries = mineOf(wMetal);
  const wRow = await compareRow(wMetal, "Mine production");
  const wHidden = await evaluate(`(() => { const td = [...document.querySelectorAll('#compare tbody[data-metal=${q(wMetal)}] tr')][0]
    .querySelectorAll("td")[2]; const b = td.querySelector(".mt-why-button"), t = td.querySelector(".mt-why-text");
    const before = [b.getAttribute("aria-expanded"), t.hidden, t.offsetHeight]; b.click();
    return new Promise((done) => setTimeout(() => done([...before, b.getAttribute("aria-expanded"), t.hidden, t.offsetHeight > 0]), 100)); })()`);
  check(`${wMetal}'s three largest give a short label, and "Why?" opens the full reason naming the United States and “W”`,
    wSeries.top3.shown === null && wRow?.[2].label === "Order unknown" && wRow[2].reason === wSeries.top3.reason &&
    wRow[2].reason === "United States is printed as “W”, so the order is unknown" &&
    same(wHidden, ["false", true, 0, "true", false, true]), JSON.stringify([wRow?.[2], wHidden]));
  const copper = await compareRow("copper", "Mine production");
  const aside = await evaluate(`(() => { const td = document.querySelector('#compare tbody[data-metal="copper"] .mt-years');
    const b = td.querySelector(".mt-aside-button"), t = td.querySelector(".mt-aside-text"); const before = t.hidden; b.click();
    return new Promise((done) => setTimeout(() => done({ before, after: t.hidden, text: t.innerText, name: b.getAttribute("aria-label") }), 100)); })()`);
  check("copper's years of reserves are 43, with the caveat one click away beside the figure and in the heading",
    copper?.[4].years === "43 years" && aside.before === true && aside.after === false && aside.text === YEARS_LABEL &&
    aside.name.includes(YEARS_LABEL) && (await evaluate(`document.querySelectorAll("#compare thead th")[5].textContent`))
      .includes(YEARS_LABEL), JSON.stringify([copper?.[4], aside]));
  const [dashMetal] = realSources ? ["copper"] : ["tin"];
  const [dashLeader, dashTop3] = realSources ? ["Chile 23.0%", "48.7%\nChile, Congo (Kinshasa), Peru"]
    : ["Kappa 40.0%", "90.0%\nKappa, Omega, Sigma"];
  const dashRow = await compareRow(dashMetal, "Mine production");
  check(`a dash counts as zero in the order: ${dashMetal}'s top producer and three largest are shown`,
    dashRow?.[1].text === dashLeader && dashRow?.[2].text === dashTop3, JSON.stringify(dashRow));
  const vanadium = await compareRow("vanadium", "Mine production");
  const vanadiumYears = chapterOf("vanadium").years_of_reserves[0];
  const issueSeries = chapterOf("vanadium").series.find((s) => s.id === "vanadium/reserves/reserves/metric-tons/2025");
  check("vanadium's years read “Unit in doubt”, and “Why?” holds the unit issue's words",
    typeof issueSeries?.unit_issue === "string" && issueSeries.unit_issue.startsWith("Unit in doubt: ") &&
    vanadiumYears.shown === null && vanadiumYears.reason === `Reserves: ${issueSeries.unit_issue}` &&
    vanadium?.[4].label === "Unit in doubt" && vanadium[4].reason === vanadiumYears.reason, JSON.stringify(vanadium?.[4]));
  if (!realSources) {
    const silver = await compareRow("silver", "Mine production");
    check("(synthetic) a valid ratio under one year reads “less than 1 year”",
      silver?.[4].years === "less than 1 year" && chapterOf("silver").years_of_reserves[0].shown === "less than 1",
      JSON.stringify(silver?.[4]));
  }
  const heads = await evaluate(`[...document.querySelectorAll("#compare thead th")].map((th) => th.textContent.replace(/\\s+/g, " ").trim())`);
  const howto = await evaluate(`(() => { const d = document.querySelector("[data-howto]"); const closed = !d.open; d.open = true;
    return { closed, text: d.innerText }; })()`);
  check("the headings and the scope line say the ranking is among named countries; the how-to opens on demand",
    heads[2]?.startsWith("Top named producer") && heads[3]?.startsWith("Three largest named") &&
    heads[4]?.startsWith("Top named reserves holder") && scopeAvailable.startsWith("Rankings are among the countries USGS names") &&
    howto.closed && howto.text.includes("not a complete ranking of the world"), JSON.stringify(heads));
  const reservesOf = (id, detail) => chapterOf(id).series.find((s) => s.statistic === "Reserves" && s.year === "2025" && s.detail === detail);
  const leaderText = (top) => `${top.countries[0]} ${top.shown}%`;
  const reservesWanted = realSources ? [
    ["copper", "Mine production", leaderText(reservesOf("copper", "Reserves").leader)],
    ["copper", "Refinery production", `${leaderText(reservesOf("copper", "Reserves").leader)}\nReserves`],
    ["iron-ore", "Mine production: Iron content", "No matching series"],
  ] : [
    ["copper", "Mine production", leaderText(reservesOf("copper", "Reserves").leader)],
    ["iron-ore", "Mine production: Iron content", `${leaderText(reservesOf("iron-ore",
      "Reserves (million metric tons): Crude ore").leader)}\nReserves (million metric tons): Crude ore`],
    ["tin", "Mine production", "No matching series"],
  ];
  const reservesShown = [];
  for (const [metal, stage] of reservesWanted) {
    const cell = (await compareRow(metal, stage))?.[3];
    reservesShown.push(cell?.label ?? cell?.text);
  }
  check("the reserves column shows the paired series, else the chapter's only 2025 reserves named, else none",
    same(reservesShown, reservesWanted.map((entry) => entry[2])) && (!realSources || reservesShown[0] === "Chile 18.4%"),
    JSON.stringify(reservesShown));

  // 6. By metal, one metal at a time.
  await load("/metals#by-metal:cobalt");
  const arrival = await evaluate(`({ panels: document.querySelectorAll("[data-metal]").length,
    metal: document.getElementById("mt-metal-panel").dataset.metal,
    parts: [...document.querySelectorAll("#mt-metal-panel details")].map((d) => d.dataset.part),
    open: document.querySelectorAll("#mt-metal-panel details[open]").length })`);
  await evaluate(`document.querySelector('#mt-metal-panel details[data-part="production"] > summary').focus(); true`);
  await press("Enter");
  const enterOpens = await evaluate(`document.querySelector('[data-part="production"]').open`);
  await press("Enter");
  const enterCloses = !(await evaluate(`document.querySelector('[data-part="production"]').open`));
  await press("Space");
  const spaceOpens = await evaluate(`document.querySelector('[data-part="production"]').open`);
  const onSummary = await focused();
  check("one metal opens with its parts closed; Enter and Space open and close a part, with a visible focus",
    arrival.panels === 1 && arrival.metal === "cobalt" && arrival.open === 0 &&
    same(arrival.parts.slice(0, 9), ["production", "reserves", ...NEW_FOLDS, "imports", "notes"]) && arrival.parts.includes("iea-supply") &&
    enterOpens && enterCloses && spaceOpens && onSummary?.summary === true && onSummary.visible === true, JSON.stringify(arrival));
  await evaluate(`document.getElementById("mt-metal-tab-cobalt").focus(); true`);
  await press("ArrowRight");
  check("the chooser follows the arrow keys to the next picked metal",
    await waitFor(`document.getElementById("mt-metal-panel")?.dataset.metal === "rare-earths"`, 3000) &&
    (await focused())?.tab === "rare-earths");

  await load(`${everything}#by-metal`);
  const visits = {};
  for (const id of allIds) {
    await selectMetal(id);
    await evaluate(openFolds);
    visits[id] = await evaluate(`(() => { const panel = document.getElementById("mt-metal-panel");
      return { labels: [...panel.querySelectorAll("table.mt-series-table")].map((t) => t.querySelector("tfoot th")?.innerText.trim() ?? null),
        iea: panel.querySelectorAll('section[data-source="iea"]').length, title: panel.querySelector(".mt-iea-title")?.innerText ?? "",
        usgs: panel.querySelectorAll('section[data-source="usgs"]').length, issues: panel.querySelectorAll("[data-unit-issue]").length }; })()`);
  }
  const labelsWanted = Object.fromEntries(allIds.map((id) => {
    const series = chapterOf(id).series;
    return [id, [...series.filter((s) => s.statistic !== "Reserves"), ...series.filter((s) => s.statistic === "Reserves")]
      .map((s) => (s.world === null ? null : s.world.rounded ? "World total (rounded by USGS)" : "World total"))];
  }));
  const allLabels = Object.values(visits).flatMap((v) => v.labels);
  check("every world total is labelled as rounded by USGS exactly where the reply says so (both kinds shown)",
    allIds.every((id) => same(visits[id].labels, labelsWanted[id])) && allLabels.includes("World total (rounded by USGS)") &&
    allLabels.includes("World total"), JSON.stringify(allIds.filter((id) => !same(visits[id].labels, labelsWanted[id])).slice(0, 3)));
  check("every metal has its USGS section, an IEA section only on the six mapped chapters, each the reply's mineral",
    allIds.every((id) => visits[id].usgs === 1 && visits[id].iea === (ieaChapters.has(id) ? 1 : 0)) &&
    [...ieaChapters].every(([id, mineral]) => visits[id].title === `${mineral.name}: demand by technology, supply by country`) &&
    allIds.every((id) => visits[id].issues === (id === "vanadium" ? 1 : 0)), JSON.stringify(allIds.filter((id) => visits[id].iea !== (ieaChapters.has(id) ? 1 : 0))));
  await selectMetal("vanadium");
  await evaluate(openFolds);
  const issueTable = await evaluate(`(() => {
    const block = [...document.querySelectorAll('#mt-metal-panel section[data-source="usgs"] .mt-series')].find((b) => b.querySelector("[data-unit-issue]"));
    const table = block?.querySelector("table");
    if (!table) return null;
    const texts = [], walk = document.createTreeWalker(table, NodeFilter.SHOW_TEXT);
    while (walk.nextNode()) texts.push(walk.currentNode.nodeValue);
    return { flag: document.querySelector('#mt-metal-panel [data-part="reserves"] [data-flag]')?.innerText ?? "",
      issue: block.querySelector("[data-unit-issue]").innerText.trim(), caption: table.querySelector("caption").innerText,
      text: texts.join(" \\n "), attributes: [table, ...table.querySelectorAll("*")].flatMap((e) => [...e.attributes].map((a) => ({ name: a.name, value: a.value }))),
      shares: [...table.querySelectorAll(".mt-share")].map((e) => e.innerText.trim()) }; })()`);
  const issuePrinted = [issueSeries.world, issueSeries.other, ...issueSeries.countries].filter(Boolean).map((c) => c.value);
  const issueShares = [...issueSeries.countries, issueSeries.other].filter(Boolean).map((c) => c.share.shown).filter(given).map((s) => `${s}%`);
  check("vanadium's reserves part is flagged; its table gives the unit issue, no quantity and no unit, but every share",
    issueTable !== null && issueTable.flag.toLowerCase() === "unit in doubt" && issueTable.issue === issueSeries.unit_issue &&
    issueTable.caption.startsWith("Reserves · Reserves · 2025") && issueTable.caption.endsWith("unit not shown") &&
    !issueTable.caption.includes(issueSeries.unit) && issuePrinted.length > 2 && leaks(issueTable, issuePrinted).length === 0 &&
    issueShares.length > 1 && same(issueTable.shares, issueShares),
    JSON.stringify(issueTable && { ...issueTable, text: undefined, attributes: undefined, leaked: leaks(issueTable, issuePrinted).map((v) => where(v, issueTable)) }));
  const [dashCountry] = realSources ? ["Germany"] : ["Delta"];
  await selectMetal(dashMetal);
  await evaluate(openFolds);
  const dashCell = await tableRow("Production · Mine production · 2025", dashCountry);
  await selectMetal(wMetal);
  await evaluate(openFolds);
  const wCell = await tableRow("Production · Mine production · 2025", "United States");
  check(`a table shows a print as printed: ${dashMetal}'s ${dashCountry} “—” and ${wMetal}'s United States “W”, each share its print`,
    dashCell?.[0] === "—" && dashCell?.[1] === "Printed as “—”" && wCell?.[0] === "W" && wCell?.[1] === "Printed as “W”",
    JSON.stringify([dashCell, wCell]));
  await selectMetal("cobalt");
  await evaluate(openFolds);
  const cobaltMine = mineOf("cobalt");
  const cobaltTable = await evaluate(`(() => {
    const block = [...document.querySelectorAll('#mt-metal-panel section[data-source="usgs"] .mt-series')]
      .find((b) => (b.querySelector("caption")?.innerText ?? "").startsWith("Production · Mine production · 2025"));
    return block ? { foot: [...block.querySelectorAll(".mt-series-foot")].map((p) => p.innerText.trim()),
      other: [...block.querySelectorAll("tbody th")].map((th) => th.innerText.trim()).find((t) => t.startsWith("Other countries")) ?? null } : null; })()`);
  check("a table's foot ranks the named countries and shows “Other countries” as one unsplit group with its share",
    typeof cobaltMine.other?.share.shown === "string" && cobaltTable?.other === "Other countries (one group, not split by USGS)" &&
    cobaltTable.foot[0]?.startsWith("Largest named country: ") && cobaltTable.foot[1] === "Ranked among the countries USGS " +
      `names. “Other countries”, one group USGS does not split, holds ${cobaltMine.other.share.shown}% of the world total and is never ranked.`,
    JSON.stringify(cobaltTable));
  const cobaltDemand = ieaChapters.get("cobalt").demand.rows;
  const demandCells = `[...document.querySelectorAll('#mt-metal-panel table.mt-demand-table tbody tr')].map((tr) => [...tr.querySelectorAll("td")].map((td) => td.innerText.trim()))`;
  const before = await evaluate(demandCells);
  await evaluate(`(() => { const s = document.querySelector("#mt-cobalt-scenario"); s.value = "steps";
    s.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`);
  await waitFor(`!!document.querySelector('#mt-metal-panel table[data-demand="steps-2030"]')`, 5000);
  const after = await evaluate(demandCells);
  check("cobalt's IEA demand shows the reply's values, and the Stated Policies scenario shows its own (its own select)",
    same(before, cobaltDemand.map((row) => [row.values["2025"], row.values["cps-2030"]])) &&
    same(after, cobaltDemand.map((row) => [row.values["2025"], row.values["steps-2030"]])), JSON.stringify(after));
  check("the usgs and iea sections are separate elements, neither inside the other",
    await evaluate(`(() => { const u = document.querySelector('#mt-metal-panel section[data-source="usgs"]'),
      i = document.querySelector('#mt-metal-panel section[data-source="iea"]');
      return !!u && !!i && u !== i && !u.contains(i) && !i.contains(u) && u.parentElement === i.parentElement; })()`));
  await selectMetal("rare-earths");
  const scope = await inner('#mt-metal-panel section[data-source="iea"] [data-scope]');
  check("rare earths shows the IEA scope note without opening anything",
    scope === ieaChapters.get("rare-earths").scope_note && scope.includes("magnet rare earth elements") &&
    await evaluate(`document.querySelector('#mt-metal-panel [data-scope]').offsetHeight > 0`), scope);


  // 12. Stage 2 parts, every metal with every fold open, against the reply; 13. their controls.
  const ctx = { check, evaluate, press, focused, tabTo, waitFor, load, openFolds, q, selectMetal, view, allIds, everything, realSources, DEFAULTS };
  const problemsOf = await stage2Checks(ctx);

  // 7. A changed byte in a retained file (synthetic only).
  /** Every tab, every metal with its parts open and the picker open: everything the page then holds, and per metal the
   * USGS and IEA sections' state. */
  const visitAll = async () => {
    const parts = [], sections = {};
    await selectTab("overview");
    parts.push(await evaluate(shownNow));
    await evaluate(`document.querySelector('[data-switch] button[data-mode="concentration"]').click(); true`);
    parts.push(await evaluate(shownNow));
    await evaluate(`document.querySelector('[data-switch] button[data-mode="leaders"]').click(); true`);
    await selectTab("by-metal");
    const pages = {};
    for (const id of allIds) {
      await selectMetal(id);
      await evaluate(openFolds);
      parts.push(await evaluate(shownNow));
      pages[id] = await evaluate(PAGE);
      sections[id] = await evaluate(`(() => { const s = (key) => document.querySelector('#mt-metal-panel section[data-source="' + key + '"]');
        const u = s("usgs"), i = s("iea"); return { usgs: u ? { withheld: u.innerText.includes("Withheld:"), tables: u.querySelectorAll("table, details").length } : null,
          iea: i ? { withheld: i.innerText.includes("Withheld:"), tables: i.querySelectorAll("table, select").length } : null }; })()`);
    }
    await selectTab("method");
    parts.push(await evaluate(shownNow));
    const notes = await evaluate(notesText);
    await selectTab("overview");
    const scopeNow = await evaluate(scopeText);
    await openPicker();
    parts.push(await evaluate(shownNow));
    await press("Escape");
    return { shown: { text: parts.map((p) => p.text).join("\n"), attributes: parts.flatMap((p) => p.attributes) }, sections, pages, notes, scope: scopeNow };
  };
  if (!realSources) {
    const entries = JSON.parse(readFileSync(join(metalsContent, "sources.json"), "utf8")).sources;
    const change = (id) => {
      const { folder, name } = entries.find((entry) => entry.id === id);
      const file = join(sources, folder, name);
      const away = join(root, `${name}.away`);
      renameSync(file, away);  // The original keeps its bytes and times; a copy with its last byte flipped stands in.
      const data = readFileSync(away);
      data[data.length - 1] ^= 1;
      writeFileSync(file, data);
      return () => { rmSync(file); renameSync(away, file); };
    };
    const fixture = spawnSync(python, ["-c",
      "import json, metals_fakes; print(json.dumps([row[8] for row in metals_fakes.usgs_rows()[1:]]))"],
      { cwd: join(repo, "tests"), encoding: "utf8" });
    const usgsFixture = [...new Set([...JSON.parse(fixture.stdout), ...usgsValues(view.usgs), ...riskValues(view.risk)])];
    const ieaFixture = [...new Set([...ieaValues(view.iea), ...usesValues(view.uses)])];
    check("the fixture's USGS and IEA value strings were read", usgsFixture.length > 50 && ieaFixture.length > 200,
      `${usgsFixture.length} ${ieaFixture.length} ${fixture.stderr}`);

    let restore = change("usgs-csv-2026");
    await load(everything);
    const withoutUsgs = await getJson("/api/metals");
    check("with the CSV changed, the USGS part is withheld and the page says so: header, banner, every row",
      withoutUsgs.usgs.state === "withheld" && withoutUsgs.iea.state === "available" &&
      await evaluate(`document.querySelector('[data-read]').dataset.read === "withheld"`) &&
      (await inner("[data-read]")).includes("the USGS data file differs from its acquisition record, so its figures are withheld") &&
      (await inner('[data-banner="usgs"]')).startsWith("USGS figures withheld.") &&
      await evaluate(`[...document.querySelectorAll('#compare tbody[data-metal]')].every((t) => t.dataset.state === "withheld" &&
        t.querySelector(".mt-why-label").innerText === "Withheld")`));
    const allU = await visitAll();
    // One-digit counts ("0 source tables") are the page's own and no figure can be told from them, so one-character values
    // are left out of the lists; every other value is scanned, the IEA years too (only the page's own year labels are left
    // out of the scan, where they stand: shownScript).
    const kept = (list) => [...new Set(list)].filter((value) => value.length > 1);
    const onlyCsv = kept([...usgsFixture, ...usgsLabels(view.usgs), ...riskLabels(view.risk)])
      .filter((value) => !strings(withoutUsgs).some((text) => occurs(value, text)));
    // A negative control: the year the uses table is set to, printed as a value in an IEA cell, in the energy-share line
    // and in an attribute, is found by the scan (three more occurrences than before).
    await load("/metals#by-metal:copper");
    await evaluate(openFolds);
    const year = await evaluate(`document.querySelector("#mt-metal-panel table[data-uses]").dataset.uses.split("-").pop()`);
    const before = await evaluate(shownNow);
    await evaluate(`(() => { const cell = document.querySelector("#mt-metal-panel td[data-year]");
      for (const e of [cell, document.querySelector("#mt-metal-panel [data-energy-share]")]) {
        const probe = document.createElement("span"); probe.className = "mt-probe"; probe.textContent = ${q(year)}; e.append(probe); }
      cell.setAttribute("title", ${q(year)}); return true; })()`);
    const after = await evaluate(shownNow);
    await evaluate(`(() => { document.querySelectorAll(".mt-probe").forEach((e) => e.remove());
      document.querySelector("#mt-metal-panel td[data-year]").removeAttribute("title"); return true; })()`);
    check(`the leak scan exempts no year: ${year} as a value in an IEA cell, the energy-share line and an attribute is found by the scan`,
      /^20\d\d$/.test(year) && occurrences(year, after) === occurrences(year, before) + 3 &&
      [...usgsFixture, ...ieaFixture].filter((value) => value.length === 1).every((value) => /^[0-9A-Za-z—]$/.test(value)),
      JSON.stringify({ year, before: occurrences(year, before), after: occurrences(year, after) }));
    const leakedU = leaks(allU.shown, onlyCsv);
    check("every metal, its parts open, shows the USGS part as withheld frames only, and its IEA part still",
      allIds.every((id) => allU.sections[id].usgs?.withheld && allU.sections[id].usgs.tables === 0) &&
      [...ieaChapters.keys()].every((id) => allU.sections[id].iea && !allU.sections[id].iea.withheld && allU.sections[id].iea.tables > 0),
      JSON.stringify(Object.entries(allU.sections).filter(([, s]) => !s.usgs?.withheld).slice(0, 3)));
    const badU = problemsOf(withoutUsgs, allU.pages);
    const usgsLinks = Object.values(withoutUsgs.research.metals).flatMap((m) => m.chains.flatMap((chain) => chain.links))
      .filter((link) => link.kind === "measured" && !("iea" in link.ref));
    const IEA_VALUE = /energy-technology demand/;  // How an IEA measured link writes its value.
    const valueOf = (pages, test) => allIds.flatMap((id) => pages[id].transmission.chains.flatMap((chain) => chain.links
      .filter((link) => link.kind === "measured" && test(link.measured) && link.measured !== null)));
    check("with the CSV changed, every metal with every fold open shows the risk part's problem in its snapshot, supply chain, concentration and exposure, no table or value, and no figure in research's USGS links",
      withoutUsgs.risk.state === "withheld" && withoutUsgs.risk.problem !== null && Object.values(badU).every((list) => list.length === 0) &&
      allIds.every((id) => allU.pages[id].conc.tables === 0 && allU.pages[id].snapshot.items[0].id === "usgs") &&
      usgsLinks.length > 3 && usgsLinks.every((link) => link.shown === null) &&
      valueOf(allU.pages, (value) => !IEA_VALUE.test(value)).length === 0 && valueOf(allU.pages, (value) => IEA_VALUE.test(value)).length > 0,
      JSON.stringify([usgsLinks.length, valueOf(allU.pages, () => true).map((link) => link.measured)]));
    check(`none of the ${onlyCsv.length} strings only the CSV holds is anywhere on the page, in any tab, hidden or not`,
      onlyCsv.includes("Congo (Kinshasa)") && onlyCsv.includes("230,000") && leakedU.length === 0 &&
      notesAvailable.length > 500 && allU.notes === notesAvailable && allU.scope === scopeAvailable,
      `notes unchanged ${allU.notes === notesAvailable}; scope unchanged ${allU.scope === scopeAvailable}; ` +
      `found ${JSON.stringify(leakedU.slice(0, 5).map((v) => where(v, allU.shown)))}`);
    check("the IEA part is unchanged in the reply", same(withoutUsgs.iea, view.iea));
    restore();
    await load("/metals");
    check("restoring the CSV restores the USGS part",
      await evaluate(`document.querySelector('[data-read]').dataset.read === "available"`) &&
      (await compareRow("cobalt", "Mine production"))?.[1].text === "Congo (Kinshasa) 74.2%");

    restore = change("iea-dataset-2026");
    await load(everything);
    const withoutIea = await getJson("/api/metals");
    check("with the workbook changed, the IEA part is withheld and the page says so",
      withoutIea.iea.state === "withheld" && withoutIea.usgs.state === "available" &&
      await evaluate(`document.querySelector('[data-read]').dataset.read === "withheld"`));
    const allI = await visitAll();
    const onlyWorkbook = kept([...ieaFixture, ...ieaLabels(view.iea), ...usesLabels(view.uses)])
      .filter((value) => !strings(withoutIea).some((text) => occurs(value, text)));
    const leakedI = leaks(allI.shown, onlyWorkbook);
    check("every IEA part is withheld frames only, named, on its six chapters; the USGS parts stay",
      [...ieaChapters.keys()].every((id) => allI.sections[id].iea?.withheld && allI.sections[id].iea.tables === 0) &&
      allIds.every((id) => !allI.sections[id].usgs?.withheld) && same(withoutIea.usgs, view.usgs));
    const badI = problemsOf(withoutIea, allI.pages);
    const ieaLinks = Object.values(withoutIea.research.metals).flatMap((m) => m.chains.flatMap((chain) => chain.links))
      .filter((link) => link.kind === "measured" && "iea" in link.ref);
    check("with the workbook changed, every metal with every fold open shows the uses part's problem in its snapshot, uses and IEA blocks, no value, and no figure in research's IEA links; the risk part stays",
      withoutIea.uses.state === "withheld" && withoutIea.uses.problem !== null && Object.values(badI).every((list) => list.length === 0) &&
      allIds.every((id) => allI.pages[id].uses.tables.length === 0) && ieaLinks.length > 0 && ieaLinks.every((link) => link.shown === null) &&
      same(withoutIea.risk, view.risk) && allI.pages.copper.conc.rows.length > 0 && valueOf(allI.pages, (value) => !IEA_VALUE.test(value)).length > 0 &&
      valueOf(allI.pages, (value) => IEA_VALUE.test(value)).length === 0, Object.values(badI).flat().slice(0, 3).join(" | "));
    check(`none of the ${onlyWorkbook.length} strings only the workbook holds is anywhere on the page`,
      onlyWorkbook.includes("Democratic Republic of Congo") && onlyWorkbook.includes("84.5") && leakedI.length === 0 &&
      allI.notes === notesAvailable && allI.scope === scopeAvailable,
      `found ${JSON.stringify(leakedI.slice(0, 5).map((v) => where(v, allI.shown)))}`);
    restore();
    await load("/metals#by-metal:cobalt");
    check("restoring the workbook restores the IEA part",
      await evaluate(`document.querySelector('[data-read]').dataset.read === "available"`) &&
      await evaluate(`document.querySelectorAll('#mt-metal-panel section[data-source="iea"] details').length > 0`));
  }

  // 8. Accessible names, in each state (each element asked for its own accessibility node).
  const names8 = () => controlNames(send);
  await send("Accessibility.enable");
  await load(everything);
  await openPicker();
  const a = await names8();
  await press("Escape");
  await selectTab("by-metal");
  await selectMetal("cobalt");
  await evaluate(openFolds);
  const b = await names8();
  await selectTab("method");
  const c = await names8();
  await selectTab("by-metal");
  await selectMetal("copper");
  await evaluate(openFolds);
  const d = await names8();
  const asides = await evaluate(`[...document.querySelectorAll("#mt-metal-panel button.mt-aside-button")].map((e) => e.getAttribute("aria-label") ?? "")`);
  const whys = await evaluate(`[...document.querySelectorAll("#mt-metal-panel button.mt-why-button")].map((e) => e.getAttribute("aria-label") ?? "")`);
  await selectTab("overview");
  await evaluate(`document.querySelector('[data-switch] button[data-mode="concentration"]').click(); true`);
  const e = await names8();
  await send("Accessibility.disable");
  const nameless = [...a, ...b, ...c, ...d, ...e].filter((control) => control.ignored || control.name === "");
  const count = (list, role) => list.filter((control) => control.role === role).length;
  const named = (list, text) => list.some((control) => control.name === text);
  check("every control has an accessible name: picker open (45 checkboxes, its search), a metal open (tabs, its parts, " +
    "4 selects: demand and uses), the method tab, copper with every fold open, the overview's Concentration view",
    nameless.length === 0 && count(a, "checkbox") === 45 && count(a, "searchbox") === 1 && count(a, "tab") >= 3 &&
    count(b, "tab") >= 48 && count(b, "combobox") === 4 && count(b, "DisclosureTriangle") >= 10 && count(a, "region") >= 1 &&
    NEW_FOLDS.length === 5 && count(d, "DisclosureTriangle") >= 12 && count(e, "button") >= 2,
    `${JSON.stringify(nameless.slice(0, 5))}; ${["checkbox", "searchbox", "tab", "combobox", "DisclosureTriangle", "region"]
      .map((role) => `${role} ${count(a, role)}/${count(b, role)}`).join(", ")}`);
  check("the new controls are named for what they do: every About note names its indicator, every Why? its figure, the uses selects their part, the folds their title and the switch its buttons",
    asides.length >= 6 && asides.every((name) => name.startsWith("About ") && name.length > 9) && whys.length > 0 &&
    whys.every((name) => name.startsWith("Why? ")) && named(b, "Scenario for energy-technology uses") && named(b, "Year for energy-technology uses") &&
    ["Supply chain", "Concentration & risk", "Industrial uses", "Geopolitical exposure", "Economic transmission"].every((title) =>
      d.some((control) => control.role === "DisclosureTriangle" && control.name.startsWith(title))) &&
    named(e, "Leaders") && named(e, "Concentration"), JSON.stringify([asides.slice(0, 3), whys.slice(0, 2), b.filter((x) => x.role === "combobox").map((x) => x.name)]));

  // 9. At 375 px.
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  const sideways = `(() => { const over = document.documentElement.scrollWidth - document.documentElement.clientWidth;
    window.scrollTo(400, window.scrollY); const x = window.scrollX; window.scrollTo(0, window.scrollY); return { over, x }; })()`;
  const outsideFrames = `(() => { const width = document.documentElement.clientWidth, out = [];
    const framed = (e) => { for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
      if (["auto", "scroll"].includes(getComputedStyle(p).overflowX)) return true; } return false; };
    for (const e of document.body.querySelectorAll("*")) { const r = e.getBoundingClientRect();
      if ((r.width === 0 && r.height === 0) || (r.right <= width + 0.5 && r.left >= -0.5) || framed(e)) continue;
      out.push(e.tagName.toLowerCase() + (e.className ? "." + String(e.className).split(" ")[0] : "") + " " + Math.round(r.left) + ".." + Math.round(r.right)); }
    return out; })()`;
  await load("/metals");
  const phoneFirst = await evaluate(sideways);
  check("at 375 px the first screen does not scroll sideways, and the tabs fit",
    phoneFirst.over <= 0 && phoneFirst.x === 0 && (await evaluate(outsideFrames)).length === 0 &&
    await evaluate(`(() => { const t = document.querySelector(".mt-tabs"); return t.scrollWidth <= t.clientWidth + 1; })()`),
    JSON.stringify(phoneFirst));
  await openPicker();
  const panelBox = await evaluate(`(() => { const r = document.getElementById("mt-picker-panel").getBoundingClientRect();
    return { left: r.left, right: r.right, width: document.documentElement.clientWidth }; })()`);
  const phoneOpen = await evaluate(sideways);
  await evaluate(`document.querySelector('label[data-pick="gold"]').click(); true`);
  const tapped = await waitFor(`${picked}.includes("gold")`, 3000);
  await evaluate(`document.querySelector(".mt-done").click(); true`);
  check("at 375 px the open picker stays inside the screen, a tap ticks a metal and Done closes it",
    panelBox.left >= 0 && panelBox.right <= panelBox.width + 0.5 && phoneOpen.over <= 0 && phoneOpen.x === 0 && tapped &&
    await waitFor(`!${panelOpen}`, 3000), JSON.stringify([panelBox, phoneOpen]));
  await load(`${everything}#by-metal:vanadium`);
  await evaluate(openFolds);
  await sleep(300);
  const phoneMetal = await evaluate(sideways);
  const outside = await evaluate(outsideFrames);
  await selectTab("overview");
  const frame = await evaluate(`(() => { const w = document.querySelector("#compare .mt-table-wrap"); const style = getComputedStyle(w);
    w.scrollLeft = 300; const moved = w.scrollLeft; w.scrollLeft = 0; return { overflowX: style.overflowX, moved, page: window.scrollX }; })()`);
  check("at 375 px, every metal picked and a metal's parts open, nothing reaches past the edge outside a frame, and the " +
    "comparison scrolls inside its own", phoneMetal.over <= 0 && phoneMetal.x === 0 && outside.length === 0 &&
    ["auto", "scroll"].includes(frame.overflowX) && frame.moved > 0 && frame.page === 0,
    `${JSON.stringify([phoneMetal, frame])} ${outside.slice(0, 6).join(" | ")}`);

  await phoneFolds({ ...ctx, selectTab, sideways, outsideFrames, sleep });

  // 10. Hygiene.
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  let own = "";
  for (const tab of ["overview", "by-metal", "method"]) {
    await load(`/metals#${tab}`);
    own += `\n${await inner("body")}`;
  }
  await load("/metals");  // The Overview's Concentration view, then every fold open on the six metals with chains.
  await evaluate(`document.querySelector('[data-switch] button[data-mode="concentration"]').click(); true`);
  own += `\n${await inner("#compare")}`;
  await load(`/metals#by-metal`);
  for (const id of DEFAULTS) {
    await selectMetal(id);
    await evaluate(openFolds);
    own += `\n${await inner("#mt-metal-panel")}`;
  }
  const found = affirmative(chromeOf(own, view));
  check("the page's own words make no recommendation and state no price direction", found.length === 0, found.join());
  const outsideRequests = requests.filter((r) => !r.url.startsWith(base) && !r.url.startsWith("data:") && !r.url.startsWith("about:"));
  check("only requests to the local server", outsideRequests.length === 0, outsideRequests.map((r) => r.url).join());
  const writes = requests.filter((r) => r.method !== "GET");
  check("only GET requests", writes.length === 0 && requests.length > 0, writes.map((r) => `${r.method} ${r.url}`).join());
  const real = errors.filter((e) => !e.url.endsWith("/favicon.ico"));
  check("no page errors", real.length === 0, real.map((e) => `${e.text} @ ${e.url}`).join(" | "));
  check("the retained sources, the served sources file and the committed content are unchanged by the run",
    same(tree(sources), sourcesBefore) && same(tree(metalsContent), metalsContentBefore) &&
    same(tree(join(repo, "content")), contentBefore));

  // 11. The real sources (opt-in).
  if (realSources) {
    await load("/metals#method");
    const files = await evaluate(`[...document.querySelectorAll("[data-source-file]")].map((e) => [e.dataset.sourceFile, e.dataset.state])`);
    check("(real) both sources are read by id and match their acquisition records",
      same(files, [["usgs-csv-2026", "verified"], ["iea-dataset-2026", "verified"]]), JSON.stringify(files));
    await load("/metals");
    check("(real) cobalt 74.2%, the lithium top-3 reason naming the United States and “W”, copper 43 years",
      (await compareRow("cobalt", "Mine production"))?.[1].text === "Congo (Kinshasa) 74.2%" &&
      /United States.*“W”/.test((await compareRow("lithium", "Mine production"))?.[2].reason ?? "") &&
      (await compareRow("copper", "Mine production"))?.[4].years === "43 years");
    check("(real) the retained folder is unchanged", same(tree(realSources), sourcesBefore));
  }

  // Screenshots for a visual review (opt-in): each a viewport, never a tall page.
  if (shots) await takeShots(shots, { send, load, evaluate, sleep });
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
