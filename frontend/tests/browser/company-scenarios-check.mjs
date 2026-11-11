// The FCX Scenarios tab (/companies/fcx#scenarios) in headless Chrome, over the review server and the retained FCX
// documents (data/company-sources/fcx, private; the check needs them and only reads them). Servers:
// - retained: the base unchanged, a higher and a lower price, a volume change, both together, the split adding up; the
//   published cash flow sensitivity up and down; bad inputs named before anything is sent; units; a result only for the
//   inputs it was computed for (a changed input hides it; a late reply for earlier inputs is never shown); reset; a
//   refused or blocked reply; keyboard; phone widths without sideways scrolling; the Overview unchanged;
// - release changed (one byte) and release missing: both calculations blocked, with the explanations that name the
//   release, and the server refuses (409); Bagdad release changed: both still available; the release changing while
//   the page is open (a temporary copy): the 409 makes the page read again, also when it arrives late for inputs that
//   have changed since;
// - retained with SYNTHETIC accounts: signed out 401, a reader 403, an admin 200.
// SECOND_ORDER_SCREENSHOTS=<folder> also writes viewport screenshots (desktop 1280x900, phone 390x844).
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromePath, freePort, same, sleep, startChrome, tree } from "./metals-kit.mjs";

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

const root = mkdtempSync(join(tmpdir(), "second-order-scenarios-check-"));
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(!!ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const q = JSON.stringify;
const PASSWORDS = { admin: "synthetic-admin-pass", "reader-a": "synthetic-reader-a" };  // tests/account_fakes.py
const ROUTE = "/api/companies/fcx/scenario";
const noSideways = `document.documentElement.scrollWidth <= window.innerWidth`;

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

// In the page: hold the next scenario requests until released, replace one reply, or fake a refusal.
const harness = `(() => { if (window.__held) return true; window.__held = []; window.__hold = 0; window.__tamper = null;
  window.__fake = null; window.__heldStatus = null; const real = window.fetch.bind(window);
  window.fetch = (url, init) => {
    if (!String(url).includes(${q(ROUTE)})) return real(url, init);
    if (window.__fake) { const fake = window.__fake; window.__fake = null; return Promise.resolve(new Response(
      JSON.stringify(fake.body), { status: fake.status, headers: { "Content-Type": "application/json" } })); }
    if (window.__tamper) { const tamper = window.__tamper; window.__tamper = null; return real(url, init).then(async (r) =>
      new Response(JSON.stringify(tamper(await r.json())), { status: r.status, headers: { "Content-Type": "application/json" } })); }
    if (window.__hold > 0) { window.__hold -= 1; return new Promise((done, fail) =>
      window.__held.push(() => real(url, init).then((reply) => { window.__heldStatus = reply.status; done(reply); }, fail))); }
    return real(url, init);
  }; return true; })()`;

try {
  const dataBefore = tree(data), researchBefore = tree(research);
  const { send, evaluate, waitFor, press, type, requests, errors, close } = await startChrome({ profile: join(root, "chrome"),
    children });
  await send("Page.enable"); await send("Runtime.enable"); await send("Log.enable"); await send("Network.enable");
  let at = await startServer("retained");
  const ready = `!!document.querySelector('article[data-company] h1') && !!document.querySelector('[data-read]')`;
  const load = async (path, wait = ready) => {
    await send("Page.navigate", { url: "about:blank" });
    await waitFor(`location.href === "about:blank"`, 5000);
    await send("Page.navigate", { url: `${at}${path}` });
    return waitFor(`document.readyState === "complete" && (${wait})`, 30000);
  };
  const size = (width, height, mobile = false) =>
    send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: mobile ? 2 : 1, mobile });
  const panel = (mode) => `document.querySelector('[data-calc="${mode}"]')`;
  const inPanel = (mode, selector) => `${panel(mode)}?.querySelector(${q(selector)})`;
  /** Clear a field with real keys and type into it. */
  const enter = async (mode, field, text) => {
    await evaluate(`(() => { const e = ${inPanel(mode, `input[data-input="${field}"]`)}; e.focus(); e.select(); return true; })()`);
    await press("Backspace");
    if (text) await type(text);
  };
  const compute = (mode) => evaluate(`(() => { ${inPanel(mode, 'button[data-action="compute"]')}.click(); return true; })()`);
  const resultState = (mode) => evaluate(`${inPanel(mode, "[data-result]")}?.dataset.resultState ?? null`);
  const out = (mode, key) => evaluate(`${inPanel(mode, `[data-out="${key}"]`)}?.textContent ?? null`);
  const waitReady = (mode) => waitFor(`${inPanel(mode, "[data-result]")}?.dataset.resultState === "ready"`, 15000);
  const posts = () => requests.filter((r) => r.method === "POST" && r.url.endsWith(ROUTE)).length;
  const run = async (mode, price, volume) => {
    await enter(mode, "price", price);
    if (volume !== undefined) await enter(mode, "volume", volume);
    await compute(mode);
    return waitReady(mode);
  };
  const outs = async (mode, keys) => Object.fromEntries(await Promise.all(keys.map(async (key) => [key, await out(mode, key)])));
  const PV = ["value", "change", "price_effect", "volume_effect"];

  // ---------------------------------------------------------------- the tab and the base
  await size(1280, 900);
  await load("/companies/fcx");
  const tabs = await evaluate(`[...document.querySelectorAll('.co-tabs [role="tab"]')].map((t) => t.dataset.tab)`);
  check("a Scenarios tab sits after Mechanisms and before the open questions",
    same(tabs, ["overview", "business", "numbers", "mechanisms", "scenarios", "questions", "method"]), q(tabs));
  check("the Overview is unchanged: six key figures and no calculation on it",
    await evaluate(`document.querySelectorAll(".co-tile").length === 6 && !document.querySelector("[data-calc]")
      && !document.querySelector("[data-scenario-form]")`));
  await load("/companies/fcx#scenarios", `!!${panel("price_volume")}`);
  check("the tab opens on price × volume, with the cash flow calculation as a second, separate choice",
    await evaluate(`(() => { const t = [...document.querySelectorAll('.co-calc-tabs [role="tab"]')];
      return t.length === 2 && t[0].getAttribute("aria-selected") === "true" && !${panel("price_volume")}.hidden
        && ${panel("cash_flow")}.hidden; })()`));
  const baseFigures = await evaluate(`[...${panel("price_volume")}.querySelectorAll("[data-base] .co-fig")].map((b) =>
    ({ id: b.dataset.figure, text: b.querySelector(".co-fig-text").textContent, badge: b.querySelector(".co-kind").textContent }))`);
  check("the base is the company's Q4 2026 assumptions, marked as company estimates (F), and their price × volume (C)",
    same(baseFigures, [{ id: "r3-out-cu-price-q4-2026", text: "$6.50", badge: "F" },
      { id: "r3-out-cu-sales-q4-2026", text: "875 million pounds", badge: "F" },
      { id: "c-q4-cu-sales-value-base", text: "$5,687.5 million", badge: "C" }]), q(baseFigures));
  check("the base names the results release and its date",
    await evaluate(`${inPanel("price_volume", "[data-base]")}.innerText.toLowerCase().includes("results release, 27 oct 2026")`));
  check("the three marks are explained: company assumption, your input, computed by this project",
    await evaluate(`(() => { const t = document.querySelector("[data-marks]")?.innerText ?? "";
      return t.includes("Company assumption") && t.includes("Your input") && t.includes("Computed by this project"); })()`));
  check("the inputs start at the company's assumptions, in their units",
    await evaluate(`(() => { const p = ${inPanel("price_volume", 'input[data-input="price"]')}, v = ${inPanel("price_volume",
      'input[data-input="volume"]')}; return p.value === "6.50" && v.value === "875"
      && p.labels[0].innerText.includes("US$ per pound") && v.labels[0].innerText.includes("million pounds")
      && v.labels[0].innerText.toLowerCase().includes("sales"); })()`));
  check("the page's stamp marks the AI-drafted texts as not reviewed by the owner",
    await evaluate(`document.querySelector('[data-panel="scenarios"] .co-stamp')?.innerText.includes("not reviewed")`));
  check("before anything is computed there is no result", (await resultState("price_volume")) === "empty");

  // ---------------------------------------------------------------- price × volume
  await evaluate(harness);
  await compute("price_volume");
  await waitReady("price_volume");
  check("the base unchanged: $5,687.5 million and no change in either part",
    same(await outs("price_volume", PV), { value: "$5,687.5 million", change: "$0 million", price_effect: "$0 million",
      volume_effect: "$0 million" }), q(await outs("price_volume", PV)));
  check("the definition sits beside the result: an approximation, not reported revenue, earnings or cash flow",
    await evaluate(`(() => { const t = ${inPanel("price_volume", "[data-result] [data-definition]")}?.innerText ?? "";
      return t.includes("approximate value of copper sales") && t.includes("not reported revenue"); })()`));
  await run("price_volume", "6.60", "875");
  check("a higher price: +$87.5 million, all of it the price effect",
    same(await outs("price_volume", PV), { value: "$5,775 million", change: "+$87.5 million",
      price_effect: "+$87.5 million", volume_effect: "$0 million" }), q(await outs("price_volume", PV)));
  check("the result names the inputs it was computed for",
    await evaluate(`(() => { const r = ${inPanel("price_volume", "[data-result]")}; return r.dataset.price === "6.60"
      && r.dataset.volume === "875" && r.innerText.includes("$6.60 a pound") && r.innerText.includes("875 million pounds"); })()`));
  await run("price_volume", "6.40", "875");
  check("a lower price: −$87.5 million",
    same(await outs("price_volume", PV), { value: "$5,600 million", change: "−$87.5 million",
      price_effect: "−$87.5 million", volume_effect: "$0 million" }), q(await outs("price_volume", PV)));
  await run("price_volume", "6.50", "900");
  check("more copper sold: +$162.5 million, all of it the volume effect",
    same(await outs("price_volume", PV), { value: "$5,850 million", change: "+$162.5 million",
      price_effect: "$0 million", volume_effect: "+$162.5 million" }), q(await outs("price_volume", PV)));
  await run("price_volume", "6.60", "900");
  check("both: +$252.5 million = price effect +$90 million + volume effect +$162.5 million",
    same(await outs("price_volume", PV), { value: "$5,940 million", change: "+$252.5 million",
      price_effect: "+$90 million", volume_effect: "+$162.5 million" }), q(await outs("price_volume", PV)));
  check("the split is labelled with its order: volume at the company's price, price on your volume",
    await evaluate(`(() => { const t = ${inPanel("price_volume", "[data-result]")}.innerText;
      return t.includes("at the company's price") && t.includes("on your volume"); })()`));

  // ---------------------------------------------------------------- a result belongs to its inputs
  await enter("price_volume", "price", "6.70");
  check("changing an input removes the result at once, so an old one never stands for new inputs",
    (await resultState("price_volume")) === "empty" && !(await evaluate(`${inPanel("price_volume", "[data-result]")}.innerText
      .includes("5,940")`)));
  await evaluate(`window.__hold = 1; true`);
  await compute("price_volume");
  await sleep(300);
  await enter("price_volume", "price", "6.80");
  await evaluate(`(() => { const f = window.__held.shift(); f(); return true; })()`);
  await sleep(1200);
  check("a late reply for earlier inputs is never shown",
    (await resultState("price_volume")) === "empty" && !(await evaluate(`${inPanel("price_volume", "[data-result]")}.innerText
      .includes("6,030")`)));
  await evaluate(`window.__hold = 1; true`);
  await compute("price_volume");  // held: 6.80 x 900
  await sleep(300);
  await enter("price_volume", "price", "6.90");
  await compute("price_volume");  // not held: 6.90 x 900
  await waitReady("price_volume");
  await evaluate(`(() => { const f = window.__held.shift(); f(); return true; })()`);
  await sleep(1200);
  check("when an earlier reply arrives after a later one, the later inputs' result stays",
    (await out("price_volume", "value")) === "$6,210 million" && (await evaluate(`${inPanel("price_volume", "[data-result]")}
      .dataset.price`)) === "6.90");

  // ---------------------------------------------------------------- bad inputs and units
  const before = posts();
  const bad = async (field, text, words) => {
    await enter("price_volume", "price", field === "price" ? text : "6.50");
    await enter("price_volume", "volume", field === "volume" ? text : "875");
    await compute("price_volume");
    await sleep(250);
    return evaluate(`(() => { const e = ${inPanel("price_volume", `input[data-input="${field}"]`)};
      const m = ${inPanel("price_volume", `[data-input-error="${field}"]`)}?.innerText ?? "";
      return e.getAttribute("aria-invalid") === "true" && ${q(words)}.every((w) => m.includes(w))
        && e.getAttribute("aria-describedby").includes(${inPanel("price_volume", `[data-input-error="${field}"]`)}.id)
        && ${inPanel("price_volume", "[data-result]")}.dataset.resultState === "empty"; })()`);
  };
  check("a price with three decimals is named before anything is sent", await bad("price", "6.505", ["to the cent"]));
  check("letters, an empty field and a negative price are refused", await bad("price", "abc", ["per pound"])
    && await bad("price", "", ["per pound"]) && await bad("price", "-1", ["per pound"]));
  check("a price per tonne is refused with its unit", await bad("price", "14330", ["per pound", "tonne"]));
  check("a volume with two decimals, or in tonnes, is refused in million pounds",
    await bad("volume", "875.25", ["million pounds"]) && await bad("volume", "397000", ["million pounds"]));
  check("no request was sent for a bad input", posts() === before, `${posts() - before} sent`);
  await enter("price_volume", "volume", "875");
  check("a corrected input clears its message",
    await evaluate(`${inPanel("price_volume", 'input[data-input="volume"]')}.getAttribute("aria-invalid") !== "true"`));

  // ---------------------------------------------------------------- refused and blocked replies
  await enter("price_volume", "price", "6.60");
  await evaluate(`window.__tamper = (body) => { body.result.value = "5776"; return body; }; true`);
  await compute("price_volume");
  await waitFor(`${inPanel("price_volume", "[data-result]")}.dataset.resultState === "error"`, 10000);
  check("a reply that does not recompute exactly is refused and shows no number",
    await evaluate(`(() => { const r = ${inPanel("price_volume", "[data-result]")}; return r.innerText.includes("refused")
      && !r.innerText.includes("5,776") && !r.querySelector("[data-out]") && !!r.querySelector('[role="alert"]'); })()`));
  const reads = () => requests.filter((r) => r.method === "GET" && r.url.endsWith("/api/companies/fcx")).length;
  const readsBefore = reads();
  await evaluate(`window.__fake = { status: 409, body: { detail: "Not computed: this calculation rests on the results release of 27 October 2026, which is changed on this machine." } }; true`);
  await compute("price_volume");
  for (let i = 0; i < 100 && reads() === readsBefore; i++) await sleep(100);
  await waitFor(`!!${panel("price_volume")}`, 15000);
  check("a calculation the server blocks makes the page read its sources again, and no earlier number stays",
    reads() > readsBefore && !(await evaluate(`!!${panel("price_volume")}.querySelector("[data-out]")`)),
    `${reads() - readsBefore} reads`);

  // ---------------------------------------------------------------- reset and the folds
  await enter("price_volume", "volume", "900");
  await evaluate(`(() => { ${inPanel("price_volume", 'button[data-action="reset"]')}.click(); return true; })()`);
  await sleep(200);
  check("reset returns to the company's assumptions and clears the result",
    await evaluate(`${inPanel("price_volume", 'input[data-input="price"]')}.value === "6.50"
      && ${inPanel("price_volume", 'input[data-input="volume"]')}.value === "875"`)
      && (await resultState("price_volume")) === "empty");
  check("formulas, sources and the cost explanation are closed folds",
    await evaluate(`["pv-formulas", "pv-sources", "pv-costs"].every((p) => { const d = ${panel("price_volume")}
      .querySelector('details[data-part="' + p + '"]'); return d && !d.open; })`));
  await evaluate(`${panel("price_volume")}.querySelectorAll("details").forEach((d) => { d.open = true; }); true`);
  check("the cost explanation: no fixed and variable split, and unit cost is not held constant",
    await evaluate(`(() => { const t = ${panel("price_volume")}.querySelector('details[data-part="pv-costs"]').innerText
      .toLowerCase(); return t.includes("no split of costs into fixed and variable") && t.includes("cost per pound constant")
        && t.includes("ai reading, not reviewed"); })()`));
  check("the formulas give the exact arithmetic and the order of the split",
    await evaluate(`(() => { const t = ${panel("price_volume")}.querySelector('details[data-part="pv-formulas"]').innerText;
      return t.includes("$6.50 × 875 million pounds = $5,687.5 million") && t.includes("(your volume − company volume) × company price")
        && t.includes("(your price − company price) × your volume") && t.includes("nothing is rounded"); })()`));

  // ---------------------------------------------------------------- the published cash flow sensitivity
  await evaluate(`document.querySelector('.co-calc-tabs [data-tab="price_volume"]').focus(); true`);
  await press("ArrowRight");
  check("the arrow keys move to the cash flow calculation",
    await evaluate(`document.activeElement?.dataset.tab === "cash_flow" && !${panel("cash_flow")}.hidden
      && ${panel("price_volume")}.hidden`));
  check("the hash follows the calculation", await evaluate(`location.hash === "#scenarios:cash-flow"`));
  const flowBase = await evaluate(`[...${panel("cash_flow")}.querySelectorAll("[data-base] .co-fig")].map((b) =>
    ({ id: b.dataset.figure, text: b.querySelector(".co-fig-text").textContent, badge: b.querySelector(".co-kind").textContent }))`);
  check("its base: the price, $75 million for each $0.10, all from the October release (F)",
    same(flowBase, [{ id: "r3-out-cu-price-q4-2026", text: "$6.50", badge: "F" },
      { id: "r3-sens-ocf-copper", text: "$75 million", badge: "F" },
      { id: "r3-sens-ocf-copper-step", text: "$0.10", badge: "F" }]), q(flowBase));
  check("it takes a price only, and never the 10-K's sensitivity",
    await evaluate(`!${inPanel("cash_flow", 'input[data-input="volume"]')} && !${panel("cash_flow")}
      .querySelector('[data-figure="k25-sensitivity-ocf-copper-fy2026"]')`));
  check("what stays fixed and the linear use are said beside the inputs, not hidden",
    await evaluate(`(() => { const t = ${panel("cash_flow")}.innerText; return t.includes("linear use")
      && t.includes("does not say over what range") && t.includes("Volumes, costs and the company's other assumptions stay"); })()`));
  const CF = ["change", "steps"];
  await run("cash_flow", "6.60");
  check("$6.60: about +$75 million of 2026 operating cash flows, one step",
    same(await outs("cash_flow", CF), { change: "+$75 million", steps: "+1" }), q(await outs("cash_flow", CF)));
  check("the result is marked as an approximation and as this project's computation",
    await evaluate(`(() => { const r = ${inPanel("cash_flow", "[data-result]")}; return r.innerText.includes("≈")
      && r.innerText.includes("consolidated operating cash flows for 2026") && !!r.querySelector('.co-kind[data-kind="computed"]'); })()`));
  await run("cash_flow", "6.40");
  check("$6.40: about −$75 million", same(await outs("cash_flow", CF), { change: "−$75 million", steps: "−1" }));
  await run("cash_flow", "6.55");
  check("$6.55: about +$37.5 million, half a step", same(await outs("cash_flow", CF), { change: "+$37.5 million", steps: "+0.5" }));
  const stepsNote = () => evaluate(`${inPanel("cash_flow", "[data-steps-note]")}?.innerText ?? null`);
  const withinOneStep = await stepsNote();
  await run("cash_flow", "7.00");
  const note = await stepsNote();
  check("$7.00: about +$375 million, with a note that five steps of the company's figure is this project's arithmetic",
    withinOneStep === null && (await out("cash_flow", "change")) === "+$375 million" && (note ?? "").includes("5 steps")
      && (note ?? "").includes("this project's arithmetic") && (note ?? "").includes("not a range the company has confirmed"),
    q({ withinOneStep, note }));
  check("the two calculations keep their own inputs",
    await evaluate(`${inPanel("price_volume", 'input[data-input="price"]')}.value === "6.50"
      && ${inPanel("cash_flow", 'input[data-input="price"]')}.value === "7.00"`));
  await evaluate(`${panel("cash_flow")}.querySelectorAll("details").forEach((d) => { d.open = true; }); true`);
  check("the worked example: $87.5 million of price × volume against the company's $75 million, not attributed",
    await evaluate(`(() => { const d = ${panel("cash_flow")}.querySelector('details[data-part="cf-versus"]');
      return d.querySelector('[data-figure="c-q4-copper-revenue-per-10c"] .co-fig-text').textContent === "$87.5 million"
        && d.querySelector('[data-figure="r3-sens-ocf-copper"] .co-fig-text').textContent === "$75 million"
        && d.innerText.includes("does not put it down to taxes"); })()`));
  check("the company's words are behind a button, and the 10-K's older sensitivity is said not to be used",
    await evaluate(`(() => { const p = ${panel("cash_flow")}; return !!p.querySelector('details[data-part="cf-words"] .co-quote-button')
      && p.querySelector('details[data-part="cf-not-used"]').innerText.includes("older sensitivity"); })()`));
  await enter("cash_flow", "price", "6.70");
  await press("Enter");
  await waitReady("cash_flow");
  check("Enter in the field computes", (await out("cash_flow", "change")) === "+$150 million");
  check("the keyboard reaches the field, Compute and Reset in order",
    await evaluate(`(() => { const f = [...${panel("cash_flow")}.querySelectorAll("input, button[data-action]")].map((e) =>
      e.dataset.input ?? e.dataset.action); return f.join(",") === "price,compute,reset"; })()`));
  check("no page errors on the retained server", errors.length === 0, q(errors.slice(0, 3)));

  // ---------------------------------------------------------------- phone widths
  for (const [width, height] of [[390, 844], [375, 812]]) {
    await size(width, height, true);
    await load("/companies/fcx#scenarios", `!!${panel("price_volume")}`);
    await evaluate(harness);
    await run("price_volume", "6.60", "900");
    const pvFits = await evaluate(noSideways);
    const fields = await evaluate(`[...${panel("price_volume")}.querySelectorAll("input, button[data-action]")]
      .every((e) => e.getBoundingClientRect().height >= 36 && e.getBoundingClientRect().right <= window.innerWidth)`);
    await load("/companies/fcx#scenarios:cash-flow", `!!${panel("cash_flow")} && !${panel("cash_flow")}.hidden`);
    await run("cash_flow", "6.60");
    check(`phone ${width}px: both calculations with results fit without sideways scrolling, fields easy to touch`,
      pvFits && fields && await evaluate(noSideways));
  }
  if (shots) await takeShots("", "retained");

  // ---------------------------------------------------------------- blocked: the results release changed or missing
  for (const mode of ["release-changed", "missing"]) {
    at = await startServer(mode);
    await size(1280, 900);
    await load("/companies/fcx#scenarios", `!!${panel("price_volume")}`);
    const state = mode === "missing" ? "missing" : "changed";
    for (const calc of ["price_volume", "cash_flow"]) {
      check(`(${mode}) ${calc}: blocked with the release named, no inputs and none of its numbers`,
        await evaluate(`(() => { const p = ${panel(calc)}; const b = p.querySelector("[data-calc-blocked]");
          const t = p.innerText; return !!b && b.innerText.includes("results release") && b.innerText.includes(${q(state)})
            && !p.querySelector("input, button[data-action]") && !t.includes("6.50") && !t.includes("875")
            && !t.includes("$75") && [...p.querySelectorAll("[data-base] .co-fig")].every((f) => f.dataset.state === "withheld"); })()`));
    }
    await evaluate(`${panel("price_volume")}.querySelectorAll("details").forEach((d) => { d.open = true; }); true`);
    check(`(${mode}) the explanations that name the release are withheld with it`,
      await evaluate(`(() => { const d = ${panel("price_volume")}.querySelector('details[data-part="pv-sources"]');
        return d.querySelectorAll("[data-withheld]").length >= 2 && !d.innerText.includes("price its"); })()`));
    const refused = await evaluate(`fetch(${q(ROUTE)}, { method: "POST", headers: { "Content-Type": "application/json",
      "X-Second-Order-Scenario": "1" }, body: JSON.stringify({ mode: "cash_flow", price: "6.60" }) })
      .then(async (r) => ({ status: r.status, body: await r.text() }))`);
    check(`(${mode}) the server refuses the calculation (409), naming the release`,
      refused.status === 409 && refused.body.includes("results release") && !refused.body.includes("75 million"), q(refused));
    if (shots && mode === "release-changed") await takeShots("release-changed-", mode);
  }
  at = await startServer("changed");
  await load("/companies/fcx#scenarios:cash-flow", `!!${panel("cash_flow")}`);
  await evaluate(harness);
  check("(Bagdad release changed) both calculations rest only on the results release and stay available",
    await run("cash_flow", "6.60") && (await out("cash_flow", "change")) === "+$75 million"
      && await evaluate(`!${panel("price_volume")}.querySelector("[data-calc-blocked]")`));
  // The results release changes while the page is open (one byte of the server's copy below the check's own folder).
  const release = sourcesFile.find((s) => s.id === "release-2026q3");
  const copy = join(root, "served-changed", "company-sources", release.folder, release.name);
  const bytes = readFileSync(copy);
  bytes[100] ^= 1;
  writeFileSync(copy, bytes);
  await enter("cash_flow", "price", "6.70");
  await compute("cash_flow");
  const reblocked = await waitFor(`!!${panel("cash_flow")}?.querySelector("[data-calc-blocked]")`, 15000);
  check("(the results release changed while the page was open) computing blocks it, and the page reads again: base "
    + "figures and the lines that name the release are withheld",
    reblocked && await evaluate(`(() => { const p = ${panel("cash_flow")}; const t = p.innerText;
      return p.querySelector("[data-calc-blocked]").innerText.includes("changed") && !t.includes("6.50") && !t.includes("$75")
        && !t.includes("linear use") && [...p.querySelectorAll("[data-base] .co-fig")].every((f) => f.dataset.state === "withheld")
        && document.querySelector("[data-read]").dataset.verified === "2"; })()`));
  // The same, with the 409 arriving late: a request is held, its input changes, the release changes (the same temporary
  // copy), and only then is the request sent. Its reply is for inputs no longer on the page, yet it must still make
  // the page read again, so nothing that rests on the release stays on screen as verified.
  bytes[100] ^= 1;
  writeFileSync(copy, bytes);  // the copy as retained again
  const restored = await load("/companies/fcx#scenarios:cash-flow", `!!${inPanel("cash_flow", "[data-scenario-form]")}`)
    && await evaluate(`document.querySelector("[data-read]").dataset.verified === "3"`);
  await evaluate(harness);
  await evaluate(`window.__hold = 1; true`);
  await enter("cash_flow", "price", "6.70");
  await compute("cash_flow");  // held: sent for 6.70
  await sleep(300);
  await enter("cash_flow", "price", "6.80");  // the input changes while the request is held
  bytes[100] ^= 1;
  writeFileSync(copy, bytes);  // and the release changes before it is sent
  const readsBeforeLate = reads();
  await evaluate(`(() => { const f = window.__held.shift(); f(); return true; })()`);
  const late = await waitFor(`window.__heldStatus === 409`, 15000);
  const lateBlocked = await waitFor(`${["price_volume", "cash_flow"].map((c) => `!!${inPanel(c, "[data-calc-blocked]")}`)
    .join(" && ")} && document.querySelector("[data-read]")?.dataset.verified === "2"`, 15000);
  check("(the results release changed while a request was held and its input changed) the late 409 still makes the page "
    + "read again: both calculations blocked, and the release's figures and lines withheld",
    restored && late && lateBlocked && reads() > readsBeforeLate && await evaluate(`["price_volume", "cash_flow"].every((c) => {
      const p = document.querySelector('[data-calc="' + c + '"]'); const t = p.innerText;
      return p.querySelector("[data-calc-blocked]").innerText.includes("changed") && !p.querySelector("input, [data-result]")
        && !t.includes("6.50") && !t.includes("875") && !t.includes("$75") && !t.includes("6.80")
        && [...p.querySelectorAll("[data-base] .co-fig")].every((f) => f.dataset.state === "withheld"); })`),
    q({ restored, late, lateBlocked, reads: reads() - readsBeforeLate }));

  // ---------------------------------------------------------------- access
  at = await startServer("retained", true);
  const body = JSON.stringify({ mode: "price_volume", price: "6.60", volume: "875" });
  const writeHeaders = { Origin: at, "Content-Type": "application/json", "X-Second-Order-Scenario": "1" };
  const signedOut = await fetch(`${at}${ROUTE}`, { method: "POST", headers: writeHeaders, body });
  const sessionHeaders = { Origin: at, "Content-Type": "application/json", "X-Second-Order-Session": "1" };
  const signIn = async (username) => {
    const reply = await fetch(`${at}/api/session/login`, { method: "POST", headers: sessionHeaders,
      body: JSON.stringify({ username, password: PASSWORDS[username] }) });
    return (reply.headers.get("set-cookie") ?? "").split(";")[0];
  };
  const asReader = await fetch(`${at}${ROUTE}`, { method: "POST", headers: { ...writeHeaders, Cookie: await signIn("reader-a") },
    body });
  const readerText = await asReader.text();
  const asAdmin = await fetch(`${at}${ROUTE}`, { method: "POST", headers: { ...writeHeaders, Cookie: await signIn("admin") },
    body });
  const adminBody = await asAdmin.json();
  check("signed out 401, a reader 403 with no result, an admin 200 with the exact result",
    signedOut.status === 401 && asReader.status === 403 && !readerText.includes("5775") && asAdmin.status === 200
      && adminBody.result?.value === "5775", `${signedOut.status} ${asReader.status} ${asAdmin.status}`);
  const crossSite = await fetch(`${at}${ROUTE}`, { method: "POST", headers: { ...writeHeaders, Origin: "http://elsewhere.test",
    Cookie: await signIn("admin") }, body });
  check("a request from another origin is refused", crossSite.status === 403);
  close();

  check("the retained documents and the research folder are unchanged after every calculation",
    same(tree(data), dataBefore) && same(tree(research), researchBefore));

  async function takeShots(prefix, mode) {
    mkdirSync(shots, { recursive: true });
    const shot = async (name, width, height, mobile, path, steps) => {
      await size(width, height, mobile);
      await load(path, `!!${panel("price_volume")}`);
      await evaluate(harness);
      if (steps) await steps();
      await sleep(500);
      const image = await send("Page.captureScreenshot", { format: "png" });
      writeFileSync(join(shots, `scenarios-${prefix}${name}.png`), Buffer.from(image.data, "base64"));
    };
    const scroll = (selector) => evaluate(`(() => { document.querySelector(${q(selector)})?.scrollIntoView({ block: "start" });
      return true; })()`);
    if (mode !== "retained") {
      await shot("desktop-price-volume", 1280, 900, false, "/companies/fcx#scenarios", () => scroll(".co-calc-tabs"));
      await shot("phone-price-volume", 390, 844, true, "/companies/fcx#scenarios", () => scroll(".co-calc-tabs"));
      return;
    }
    await shot("desktop-1-price-volume-base", 1280, 900, false, "/companies/fcx#scenarios");
    await shot("desktop-2-price-volume-result", 1280, 900, false, "/companies/fcx#scenarios", async () => {
      await run("price_volume", "6.60", "900"); await scroll(".co-calc-tabs"); });
    await shot("desktop-3-price-volume-folds", 1280, 900, false, "/companies/fcx#scenarios", async () => {
      await evaluate(`${panel("price_volume")}.querySelectorAll("details").forEach((d) => { d.open = true; }); true`);
      await scroll('[data-calc="price_volume"] details[data-part="pv-formulas"]'); });
    await shot("desktop-4-cash-flow-result", 1280, 900, false, "/companies/fcx#scenarios:cash-flow", async () => {
      await run("cash_flow", "6.60"); await scroll(".co-calc-tabs"); });
    await shot("desktop-5-cash-flow-folds", 1280, 900, false, "/companies/fcx#scenarios:cash-flow", async () => {
      await evaluate(`${panel("cash_flow")}.querySelectorAll("details").forEach((d) => { d.open = true; }); true`);
      await scroll('[data-calc="cash_flow"] details[data-part="cf-versus"]'); });
    await shot("desktop-7-cash-flow-five-steps", 1280, 900, false, "/companies/fcx#scenarios:cash-flow", async () => {
      await run("cash_flow", "7.00"); await scroll('[data-calc="cash_flow"] [data-scenario-form]'); });
    await shot("desktop-6-bad-input", 1280, 900, false, "/companies/fcx#scenarios", async () => {
      await enter("price_volume", "price", "14330"); await compute("price_volume"); await sleep(200);
      await scroll(".co-calc-tabs"); });
    await shot("phone-1-price-volume-base", 390, 844, true, "/companies/fcx#scenarios", () => scroll(".co-calc-tabs"));
    await shot("phone-2-price-volume-result", 390, 844, true, "/companies/fcx#scenarios", async () => {
      await run("price_volume", "6.60", "900"); await scroll('[data-calc="price_volume"] [data-result]'); });
    await shot("phone-3-cash-flow-result", 390, 844, true, "/companies/fcx#scenarios:cash-flow", async () => {
      await run("cash_flow", "6.60"); await scroll('[data-calc="cash_flow"] [data-result]'); });
    await shot("phone-4-cash-flow-notes", 390, 844, true, "/companies/fcx#scenarios:cash-flow", async () => {
      await scroll('[data-calc="cash_flow"] [data-scenario-form]'); });
  }
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
