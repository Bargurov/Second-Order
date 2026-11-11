// The controls the Stage 2 parts add to the metals page, checked with real key presses (metals-check.mjs): the folds,
// the About notes, the uses part's own selects and the overview's Leaders | Concentration switch. `c` carries the
// check's page helpers (check, evaluate, press, focused, tabTo, waitFor, load, openFolds, q).
import { same } from "./metals-kit.mjs";
import { BADGES, hhiOf, NEW_FOLDS, NO_EVENT, PAGE, relianceWords, verifyMetal } from "./metals-stage2.mjs";

/** Each new fold is closed on arrival, and Enter and Space open and close it, with a visible focus. */
export async function foldKeys(c, id) {
  await c.load(`/metals#by-metal:${id}`);
  const closed = await c.evaluate(`${JSON.stringify(NEW_FOLDS)}.every((p) => { const d = document.querySelector('#mt-metal-panel details[data-part="' + p + '"]');
    return !!d && !d.open && !!d.querySelector(".mt-fold-teaser")?.innerText; })`);
  const steps = {}, focus = {};
  for (const part of NEW_FOLDS) {
    const sel = `#mt-metal-panel details[data-part="${part}"]`;
    await c.evaluate(`document.querySelector(${c.q(`${sel} > summary`)}).focus(); true`);
    steps[part] = [];
    for (const key of ["Enter", "Enter", "Space", "Space"]) {
      await c.press(key);
      steps[part].push(await c.evaluate(`document.querySelector(${c.q(sel)}).open`));
    }
    focus[part] = (await c.focused())?.visible === true;
  }
  c.check(`${id}: the five new folds are closed on arrival, each with a line on what it holds; Enter and Space open and close each, with a visible focus`,
    closed && NEW_FOLDS.every((part) => same(steps[part], [true, false, true, false]) && focus[part]), JSON.stringify([closed, steps, focus]));
}

const ABOUTS = [
  ["concentration", "the largest named country's share (CR1)", ["divided by the world total USGS prints"]],
  ["concentration", "the three largest named countries' share (CR3)", ["added and divided by the printed world total"]],
  ["concentration", "the HHI and its two bounds", ["sum of each named country's squared share", "two bounds"]],
  ["concentration", "coverage", ["added, as a share of the printed world total"]],
  ["concentration", "US import-source concentration", ["shares of US imports"], "2021–24"],
  ["snapshot", "US net import reliance", ["net imports as a percentage of apparent consumption"]],
];
/** Each About note opens from the keyboard with its formula, its source and its data year, and closes again. */
export async function aboutNotes(c, id, only) {
  await c.load(`/metals#by-metal:${id}`);
  await c.evaluate(c.openFolds);
  const problems = [];
  for (const [where, name, words, year = "2025"] of ABOUTS.filter(([, name]) => only.includes(name))) {
    const root = where === "snapshot" ? "#mt-metal-panel [data-snapshot]" : `#mt-metal-panel details[data-part="${where}"]`;
    const find = `document.querySelector(${c.q(`${root} button.mt-aside-button[aria-label="About ${name}"]`)})`;
    const state = () => c.evaluate(`(() => { const b = ${find}; if (!b) return null; const t = document.getElementById(b.getAttribute("aria-controls"));
      return { expanded: b.getAttribute("aria-expanded"), hidden: t.hidden, text: t.textContent }; })()`);
    const before = await state();
    if (before === null) { problems.push(`${name}: no button`); continue; }
    await c.evaluate(`${find}.focus(); true`);
    await c.press("Enter");
    const open = await state();
    await c.press("Space");
    const closed = await state();
    const full = open?.text ?? "";
    if (!(before.expanded === "false" && before.hidden && open.expanded === "true" && !open.hidden && closed.expanded === "false" && closed.hidden &&
      words.every((word) => full.includes(word)) && full.includes("Source: USGS Mineral Commodity Summaries 2026 data release") && full.includes(year))) {
      problems.push(`${name}: ${JSON.stringify([before, open?.expanded, closed?.expanded, full.slice(0, 60)])}`);
    }
  }
  c.check(`${id}: the About notes open and close from the keyboard, each with its formula, its source and its year`,
    problems.length === 0, problems.join(" | "));
}

/** The uses part's own scenario and year selects change the IEA energy-technology table to the reply's values. */
export async function usesSelects(c, id, entry) {
  await c.load(`/metals#by-metal:${id}`);
  await c.evaluate(c.openFolds);
  const use = `#mt-metal-panel [data-use=${c.q(entry.name)}]`;
  const cells = (key) => c.evaluate(`[...document.querySelectorAll('${use} table[data-uses="${key}"] tbody tr')]
    .map((tr) => [...tr.querySelectorAll("td")].map((td) => td.innerText.trim()))`);
  const label = await c.evaluate(`[...document.querySelectorAll("#mt-${id}-uses-scenario, #mt-${id}-uses-year")]
    .map((s) => s.labels[0]?.innerText.replace(/\\s+/g, " ").trim())`);
  const before = await cells("cps-2030");
  await c.evaluate(`(() => { for (const [sid, value] of [["mt-${id}-uses-scenario", "steps"], ["mt-${id}-uses-year", "2040"]]) {
    const s = document.getElementById(sid); s.value = value; s.dispatchEvent(new Event("change", { bubbles: true })); } return true; })()`);
  await c.waitFor(`!!document.querySelector('${use} table[data-uses="steps-2040"]')`, 5000);
  const after = await cells("steps-2040");
  const total = await c.evaluate(`[...document.querySelectorAll('${use} table[data-uses="steps-2040"] tfoot td')].map((td) => td.innerText.trim())`);
  const techs = entry.technologies ?? [];
  const row = (x, key, shown) => [x.values["2025"], x.share_2025 === null ? shown[0]?.[1] : `${x.share_2025}%`, x.values[key]];
  c.check(`${id}: the IEA energy-technology table shows the reply's values, and its own scenario and year selects (named) change them`,
    techs.length > 0 && same(before, techs.map((x) => row(x, "cps-2030", before))) && same(after, techs.map((x) => row(x, "steps-2040", after))) &&
    !same(before, after) && total[2] === entry.total["steps-2040"] && label.length === 2 &&
    label.every((text) => text?.includes("for energy-technology uses")) && label[0].startsWith("Scenario") && label[1].startsWith("Year"),
    JSON.stringify([label, before, after]));
}

/** The overview's Leaders | Concentration switch: keyboard-reachable, aria-pressed follows, the table shows the reply.
 * `hhiOf(indicators)` is the expected { range, coverage } of a series, or null. */
export async function concentrationSwitch(c, reply, everything, hhiOf) {
  await c.load(everything);
  const pressed = `(() => Object.fromEntries([...document.querySelectorAll("[data-switch] button")].map((b) => [b.dataset.mode, b.getAttribute("aria-pressed")])))()`;
  const first = await c.evaluate(pressed);
  await c.evaluate(`document.activeElement?.blur(); window.scrollTo(0, 0); true`);
  const presses = await c.tabTo((now) => now.tag === "button" && now.text === "Concentration");
  const onSwitch = await c.focused();
  await c.press("Enter");
  const concentration = await c.evaluate(pressed);
  const mode = await c.evaluate(`document.getElementById("compare").dataset.mode`);
  const rows = await c.evaluate(`[...document.querySelectorAll("table[data-concentration] tbody[data-metal]")].map((body) => ({ metal: body.dataset.metal,
    rows: [...body.querySelectorAll("tr")].map((tr) => { const td = [...tr.querySelectorAll("td")]; const h = tr.querySelector(".mt-hhi");
      return { stage: td[0]?.innerText.trim(), cr3: td[1]?.innerText.trim(), hhi: h ? { range: h.querySelector(".mt-share").innerText.trim(),
        coverage: h.querySelector(".mt-sub").innerText.trim() } : null, reliance: td[td.length - 1]?.innerText.trim() ?? null }; }) }))`);
  const heads = await c.evaluate(`document.querySelector("table[data-concentration] thead").textContent.replace(/\\s+/g, " ")`);
  const bad = [];
  if (rows.map((r) => r.metal).join() !== reply.usgs.chapters.map((x) => x.id).join()) bad.push("the picked metals");
  for (const body of rows) {
    const chapter = reply.usgs.chapters.find((x) => x.id === body.metal), risk = reply.risk.chapters.find((x) => x.id === body.metal);
    const series = chapter.series.filter((s) => s.statistic === "Production" && s.year === "2025");
    if (series.length === 0) continue;
    if (body.rows.length !== series.length) { bad.push(`${body.metal} rows`); continue; }
    series.forEach((s, at) => {
      const row = body.rows[at], ind = risk.series[s.id];
      const ok = row.stage === s.detail && same(row.hhi, hhiOf(ind)) && (s.top3.shown !== null
        ? row.cr3.startsWith(`${s.top3.shown}%`) && s.top3.countries.every((x) => row.cr3.includes(x)) : !row.cr3.includes("%"));
      if (!ok) bad.push(`${body.metal}/${s.detail}: ${JSON.stringify(row)}`);
    });
    const want = risk.us.reliance === null ? null : relianceWords(chapter, risk.us.reliance);
    if (want !== null && !(body.rows[0].reliance?.startsWith(want.figure) && (want.oneOf === null || body.rows[0].reliance.includes(want.oneOf)))) {
      bad.push(`${body.metal} reliance "${body.rows[0].reliance}"`);
    }
  }
  await c.evaluate(`document.querySelector('[data-switch] button[data-mode="leaders"]').focus(); true`);
  await c.press("Space");
  const back = await c.evaluate(pressed);
  c.check("the overview switch: Leaders pressed first; Tab reaches Concentration with a visible focus, Enter presses it (aria-pressed follows), Space returns",
    first.leaders === "true" && first.concentration === "false" && presses > 0 && onSwitch?.visible === true &&
    concentration.concentration === "true" && concentration.leaders === "false" && mode === "concentration" &&
    back.leaders === "true" && back.concentration === "false", JSON.stringify([first, presses, onSwitch, concentration, mode, back]));
  c.check("the Concentration table shows, per metal and stage, the reply's three largest (CR3), the HHI range with the named countries' coverage, and US reliance",
    bad.length === 0 && /Three largest named \(CR3\)/.test(heads) && /HHI/.test(heads) && rows.some((r) => r.rows.some((x) => x.hhi?.range.includes("–"))) &&
    rows.some((r) => r.rows.some((x) => x.hhi?.coverage.startsWith("named countries"))), `${bad.slice(0, 4).join(" | ")} ${heads}`);
}

/** Every metal with every fold open, the Stage 2 parts read off the page and compared with the reply, then the controls.
 * Returns problemsOf(reply, pages), which the withholding steps use on the pages they read. */
export async function stage2Checks(c) {
  const { check, evaluate, selectMetal, view, allIds, everything, realSources, DEFAULTS, load, openFolds } = c;
  const ctx = c;
  const readPages = async () => {
    const pages = {};
    for (const id of allIds) { await selectMetal(id); await evaluate(openFolds); pages[id] = await evaluate(PAGE); }
    return pages;
  };
  const problemsOf = (reply, pages) => {
    const found = { snapshot: [], supply: [], conc: [], uses: [], exposure: [], transmission: [] };
    for (const id of allIds) for (const [part, list] of Object.entries(verifyMetal(reply, id, pages[id]))) found[part].push(...list);
    return found;
  };
  await load(`${everything}#by-metal`);
  const pagesNow = await readPages();
  const problems = problemsOf(view, pagesNow);
  const say = (part) => problems[part].slice(0, 3).join(" | ");
  check("every metal's snapshot is open outside every fold, a source line on each item, its figures the reply's",
    problems.snapshot.length === 0, say("snapshot"));
  check("every metal's supply chain prints the reply's stages (a missing stage by its exact sentence), the Final products sentence and the IEA block labelled apart",
    problems.supply.length === 0 && view.risk.chapters.some((chapter) => chapter.stages.length > 0) &&
    allIds.some((id) => pagesNow[id].supply.ladder.some((step) => step.missing)), say("supply"));
  const hhiCells = allIds.flatMap((id) => pagesNow[id].conc.rows.map((row) => row.hhi).filter(Boolean));
  check("every metal's Concentration & risk shows each CR1, CR3 and HHI range with the named countries' coverage, and its import rows, as the reply has them",
    problems.conc.length === 0 && hhiCells.length > 10 && hhiCells.some((cell) => cell.range.includes("–")) &&
    allIds.some((id) => pagesNow[id].conc.imports.some((row) => row.hhi !== null)), say("conc"));
  const withUses = allIds.filter((id) => pagesNow[id].uses.tables.length > 0);
  check("every metal's Industrial uses shows the IEA energy-technology table as the reply has it (an unmapped metal says so)",
    problems.uses.length === 0 && withUses.length >= 3 && allIds.some((id) => pagesNow[id].uses.missing !== ""), say("uses"));
  const events = pagesNow.copper.exposure;
  check(realSources ? "(real) copper's two verified events are shown with their quotes, kinds, dates (each in its quote) and places, and no NO_EVENT sentence"
    : "(synthetic) copper's three cited events are unverified: the exact NO_EVENT sentence, and all three listed under “Cited, not verified on this read”",
  problems.exposure.length === 0 && allIds.filter((id) => id !== "copper").every((id) => pagesNow[id].exposure.noEvent === NO_EVENT) &&
    (realSources ? events.noEvent === "" && events.events.length === 2 && events.events.every((x) => x.quote.length > 20 && x.kind !== "" && x.when !== "" && x.quote.includes(x.when) && x.source !== "")
      : events.noEvent === NO_EVENT && events.events.length === 0 && events.head === "Cited, not verified on this read" && events.unverified.length === 3),
  `${say("exposure")} ${JSON.stringify(events.events.length)}`);
  const links = allIds.flatMap((id) => pagesNow[id].transmission.chains.flatMap((chain) => chain.links));
  check("every metal's Economic transmission: the written-by sentence, each link labelled by its kind with its value, coverage, quote or reason, as the reply has it",
    problems.transmission.length === 0 && ["measured", "stated", "hypothesis"].every((kind) => links.some((link) => link.kind === kind && link.badge === BADGES[kind])) &&
    links.some((link) => link.kind === "measured" && link.measured !== null) && links.some((link) => link.coverage !== null) &&
    (!realSources || links.some((link) => link.kind === "stated" && link.passage?.state === "verified" && link.passage.quote.length > 20)),
    `${say("transmission")} ${links.length} links`);
  const entryOf = view.uses.entries.find((entry) => entry.chapter === "copper" && entry.technologies !== null);
  await foldKeys(ctx, "copper");
  await foldKeys(ctx, "cobalt");
  const aboutOn = (test) => view.risk.chapters.find((chapter) => DEFAULTS.includes(chapter.id) && test(chapter)).id;
  await aboutNotes(ctx, aboutOn((chapter) => chapter.us.imports.length > 0), ["the largest named country's share (CR1)",
    "the three largest named countries' share (CR3)", "the HHI and its two bounds", "coverage", "US import-source concentration"]);
  await aboutNotes(ctx, aboutOn((chapter) => chapter.us.reliance !== null), ["US net import reliance"]);
  await usesSelects(ctx, "copper", entryOf);
  await concentrationSwitch(ctx, view, everything, hhiOf);
  return problemsOf;
}

/** At 375 px, with every new fold open on five metals, and the overview's Concentration table: nothing scrolls sideways. */
export async function phoneFolds(c) {
  const { check, evaluate, selectTab, selectMetal, openFolds, sideways, outsideFrames, sleep } = c;
  const phone = [];
  for (const id of ["copper", "cobalt", "lithium", "rare-earths", "nickel"]) {
    await selectTab("by-metal");
    await selectMetal(id);
    await evaluate(openFolds);
    await sleep(150);
    phone.push([id, (await evaluate(sideways)).over, (await evaluate(outsideFrames)).slice(0, 3)]);
  }
  await selectTab("overview");
  await evaluate(`document.querySelector('[data-switch] button[data-mode="concentration"]').click(); true`);
  const conc375 = await evaluate(`(() => { const w = document.querySelector("#compare .mt-table-wrap"); w.scrollLeft = 300;
    const moved = w.scrollLeft; w.scrollLeft = 0; return { overflowX: getComputedStyle(w).overflowX, moved, page: window.scrollX }; })()`);
  check("at 375 px, with every new fold open on five metals (supply chain, concentration, uses, exposure, transmission) nothing scrolls sideways or reaches past the edge outside a frame, and the Concentration table scrolls in its own",
    phone.every(([, over, outside]) => over <= 0 && outside.length === 0) && (await evaluate(sideways)).over <= 0 &&
    ["auto", "scroll"].includes(conc375.overflowX) && conc375.moved > 0 && conc375.page === 0, JSON.stringify([phone, conc375]));
}
