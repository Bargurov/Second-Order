// Browser acceptance check for market context on the twelve macro case pages (the sector cases have none), in two
// phases with one headless Chrome and tests/review_browser_server.py serving an empty temporary folder:
//
// A. The committed bundle of real H.15 downloads in two acquisition runs (--market-context committed), read-only as in
//    production: the section and its table-of-contents entry; that the chart and the table show exactly the served
//    values; the publication-date marker; the exact windows; weekends and SIFMA holidays; that dates do not move with
//    the browser's time zone; provenance, the acquisition run, discarded replies and limits; reaching a case through
//    search and a category; keyboard access to the data; a direct reload; narrow screens; and that the committed files
//    are byte-for-byte unchanged afterwards.
// B. A bundle prepared from SYNTHETIC rows (--market-context synthetic; invented values, labelled so on the page) for
//    what real data cannot show: missing expected sessions, a source changed after preparation, no bundle at all.
//
// Both phases check that the pages only read and that nothing outside the local server is requested.
//
//   cd frontend; npm run build; npm run test:browser:context
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync, rmSync, writeFileSync } from "node:fs";
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
if (!existsSync(join(repo, "frontend/dist/index.html"))) throw new Error("Build the client first: npm run build");

const TWO = "RIFLGFCY02_N.B";
const TEN = "RIFLGFCY10_N.B";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const label = (iso) => { const [year, month, day] = iso.split("-").map(Number); return `${day} ${MONTHS[month - 1]} ${year}`; };
/** A case: its New York publication date, window, SIFMA holidays, acquisition run and discarded replies in that run. */
const make = (id, day, start, end, holidays, run, discarded, synthetic = []) =>
  ({ id, day, start, end, holidays, run, discarded, synthetic, label: label(day), range: `${label(start)} to ${label(end)}` });
const CONTEXT = [
  make("fomc-2025-01-29", "2025-01-29", "2025-01-15", "2025-02-12", ["2025-01-20"], 2, 1),
  make("fomc-2025-03-19", "2025-03-19", "2025-03-05", "2025-04-02", [], 1, 0),
  make("empsit-2025-04-04", "2025-04-04", "2025-03-21", "2025-04-18", ["2025-04-18"], 2, 1),
  make("cpi-2025-04-10", "2025-04-10", "2025-03-27", "2025-04-24", ["2025-04-18"], 2, 0),
  make("empsit-2025-05-02", "2025-05-02", "2025-04-18", "2025-05-16", ["2025-04-18"], 2, 1),
  make("fomc-2025-05-07", "2025-05-07", "2025-04-23", "2025-05-21", [], 2, 1),
  make("cpi-2025-05-13", "2025-05-13", "2025-04-29", "2025-05-27", ["2025-05-26"], 2, 1),
  make("empsit-2025-06-06", "2025-06-06", "2025-05-23", "2025-06-20", ["2025-05-26", "2025-06-19"], 2, 1),
  make("cpi-2025-06-11", "2025-06-11", "2025-05-28", "2025-06-25", ["2025-06-19"], 2, 0),
  make("fomc-2025-06-18", "2025-06-18", "2025-06-04", "2025-07-02", ["2025-06-19"], 2, 0),
  make("empsit-2025-07-03", "2025-07-03", "2025-06-19", "2025-07-17", ["2025-06-19", "2025-07-04"], 1, 0,
       [{ series: TEN, date: "2025-07-08", status: "session_missing",
          note: "10-year: missing: expected session, the source gives no value" }]),
  make("cpi-2025-07-15", "2025-07-15", "2025-07-01", "2025-07-29", ["2025-07-04"], 1, 0,
       [{ series: TWO, date: "2025-07-22", status: "session_absent", note: "Missing: expected session, no row in the source" },
        { series: TEN, date: "2025-07-22", status: "session_absent", note: "Missing: expected session, no row in the source" }]),
];
if (CONTEXT.length !== 12) throw new Error("Every macro library case has market context.");
const SECTIONS = ["overview", "facts", "channels", "context", "competing", "limits", "critique", "sources", "provenance"];
const COMMITTED = join(repo, "content", "market-context");

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const root = mkdtempSync(join(tmpdir(), "second-order-context-check-"));
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
/** Every file in a folder with its SHA-256: reading pages must leave all of them unchanged. */
const fingerprint = (folder) => readdirSync(folder, { recursive: true, withFileTypes: true })
  .filter((entry) => entry.isFile())
  .map((entry) => { const path = join(entry.parentPath ?? entry.path, entry.name);
    return `${path.slice(folder.length)} ${createHash("sha256").update(readFileSync(path)).digest("hex")}`; })
  .sort().join("\n");
const committedBefore = fingerprint(COMMITTED);

/** Starts the launcher over a new empty folder; returns its base address and a stop function. */
async function startServer(mode) {
  const served = join(root, `served-${mode}`);
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    "--market-context", mode], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  let started = false;
  for (let i = 0; i < 150 && !started; i++) {
    try { started = (await fetch(`${base}/api/case-library`)).ok; } catch { await sleep(200); }
  }
  if (!started) throw new Error(`The review server (${mode}) did not start.`);
  return { base, served, stop: async () => { server.kill(); await sleep(400); } };
}

try {
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
  let requests = [];
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else if (message.method === "Network.requestWillBeSent") {
      requests.push({ url: message.params.request.url, method: message.params.request.method });
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
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);
  const press = async (key, code, keyCode, typed) => {
    await send("Input.dispatchKeyEvent", { type: "keyDown", key, code, windowsVirtualKeyCode: keyCode, text: typed });
    await send("Input.dispatchKeyEvent", { type: "keyUp", key, code, windowsVirtualKeyCode: keyCode });
  };
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  const viewport = (width, height, mobile) =>
    send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: mobile ? 2 : 1, mobile });
  await viewport(1280, 900, false);
  let base = "";
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete'");
  };
  const contextShown = (id) => `location.pathname === "/library/${id}" &&
    (!!document.querySelector(".context .context-table") || !!document.querySelector(".context-unavailable"))`;
  /** The served view, read by the page itself with a GET. */
  const servedView = (id) => evaluate(`fetch("/api/case-library/${id}/market-context").then((r) => r.json())`);
  /** What the page shows: the chart's points, gaps and marker, and the table's rows, read from the rendered DOM. */
  const readContext = () => evaluate(`(() => {
    const q = (s) => document.querySelector(s);
    const qa = (s) => [...document.querySelectorAll(s)];
    const svg = q(".context-chart svg");
    return {
      sections: qa(".library-section-block").map((e) => e.id),
      kicker: q("#context .kicker")?.textContent ?? "",
      toc: qa(".library-toc a").map((a) => [a.textContent, a.getAttribute("href")]),
      intro: q(".context > p")?.textContent ?? "",
      svgRole: svg?.getAttribute("role"), svgTitle: q("#context-chart-title")?.textContent ?? "",
      svgDesc: q("#context-chart-desc")?.textContent ?? "", labelledBy: svg?.getAttribute("aria-labelledby"),
      points: qa(".context-point").map((c) => ({ series: c.dataset.series, date: c.dataset.date, value: c.dataset.value,
                                                 cx: Number(c.getAttribute("cx")) })),
      lines: qa(".context-line").map((p) => ({ series: p.dataset.series, cls: p.getAttribute("class"),
                                               stroke: getComputedStyle(p).stroke, dash: getComputedStyle(p).strokeDasharray,
                                               fill: getComputedStyle(p).fill })),
      missingMarks: qa(".context-missing").map((e) => e.dataset.series + "|" + e.dataset.date),
      marker: { date: q(".context-publication")?.dataset.date, x: Number(q(".context-publication")?.getAttribute("x1")) },
      markerLabel: q(".context-chart .publication-label")?.textContent ?? "",
      xTicks: qa(".context-chart .axis-tick").map((g) => [g.dataset.date, g.textContent]),
      yTicks: qa(".context-chart .grid text").map((t) => t.textContent),
      axisLabel: q(".context-chart .axis-label")?.textContent ?? "",
      legend: qa(".context-legend li").map((li) => li.textContent),
      caption: q(".context-table caption")?.textContent ?? "",
      headers: qa(".context-table thead th").map((th) => th.textContent),
      rows: qa(".context-table tbody tr").map((tr) => ({
        date: tr.dataset.date, label: tr.querySelector("th")?.textContent ?? "", cls: tr.className,
        cells: [...tr.querySelectorAll("td[data-series]")].map((td) => ({ series: td.dataset.series, status: td.dataset.status,
                                                                             text: td.textContent })),
        note: tr.querySelector(".context-note")?.textContent ?? "" })),
      provenance: q(".context-provenance")?.textContent ?? "",
      links: qa(".context-provenance a").map((a) => [a.getAttribute("href"), a.getAttribute("target"), a.getAttribute("rel")]),
      citations: qa(".context-citations li").map((li) => li.textContent),
      limits: q(".context")?.textContent ?? "",
      benchmark: q(".library-benchmark")?.textContent ?? "",
      unavailable: q(".context-unavailable")?.textContent ?? "",
    };
  })()`);
  const dates = (start, end) => {
    const list = [];
    for (let day = Date.parse(`${start}T00:00:00Z`); day <= Date.parse(`${end}T00:00:00Z`); day += 86_400_000) {
      list.push(new Date(day).toISOString().slice(0, 10));
    }
    return list;
  };
  const SHOWN = new Set(["session_value", "issuer_observation_on_calendar_holiday"]);
  /** The checks shared by both phases: exact agreement with the served view, windows, calendar and drawing. */
  const agreement = async (expected, read, view, phase) => {
    const tag = `${phase} ${expected.id}`;
    check(`${tag}: the window is 14 calendar days either side of the New York date, every date listed once`,
      view.window.start === expected.start && view.window.end === expected.end &&
      view.publication.new_york_date === expected.day &&
      same(read.rows.map((row) => row.date), dates(expected.start, expected.end)) && read.rows.length === 29 &&
      read.caption.includes(expected.range) && read.svgTitle.includes(expected.range),
      `${view.window?.start}..${view.window?.end} rows=${read.rows.length}`);
    const served = view.days.flatMap((day) => view.series.map((series) => [series.id, day.date, day.observations[series.id]]));
    const fromView = served.filter(([, , o]) => SHOWN.has(o.status)).map(([s, d, o]) => `${s}|${d}|${o.raw}`).sort();
    const fromChart = read.points.map((p) => `${p.series}|${p.date}|${p.value}`).sort();
    const fromTable = read.rows.flatMap((row) => row.cells.filter((cell) => cell.text !== "—")
      .map((cell) => `${cell.series}|${row.date}|${cell.text.replace(/%$/, "")}`)).sort();
    check(`${tag}: the chart and the table show exactly the served values, as written in the source`,
      fromView.length >= 36 && same(fromChart, fromView) && same(fromTable, fromView),
      `view=${fromView.length} chart=${fromChart.length} table=${fromTable.length}`);
    const statuses = read.rows.flatMap((row) => row.cells.map((cell) => `${cell.series}|${row.date}|${cell.status}`)).sort();
    check(`${tag}: every cell carries the served status`,
      same(statuses, served.map(([s, d, o]) => `${s}|${d}|${o.status}`).sort()));
    const byDate = Object.fromEntries(read.points.filter((p) => p.series === TWO).map((p) => [p.date, p.cx]));
    const order = Object.keys(byDate).sort();
    check(`${tag}: points sit in calendar order along the date axis`,
      order.length > 15 && order.every((date, i) => i === 0 || byDate[date] > byDate[order[i - 1]]));
    const pubRow = read.rows.find((row) => row.date === expected.day);
    const pubPoint = read.points.find((p) => p.date === expected.day);
    check(`${tag}: the publication date is marked on the chart and highlighted in the table, as a date`,
      read.marker.date === expected.day && pubPoint && Math.abs(pubPoint.cx - read.marker.x) < 0.01 &&
      read.markerLabel === "Publication date" && pubRow?.cls === "is-publication" &&
      pubRow.label.includes(expected.label) && pubRow.label.includes("Publication date") &&
      read.legend.some((item) => item.includes(`Publication date, ${expected.label} (New York)`)) &&
      read.xTicks[2]?.[0] === expected.day, JSON.stringify(read.marker));
    check(`${tag}: a legend names both series, which are drawn differently, and the axes are in percent and dates`,
      read.legend.some((item) => item === `2-year Treasury yield (${TWO})`) &&
      read.legend.some((item) => item === `10-year Treasury yield (${TEN})`) &&
      new Set(read.lines.map((line) => `${line.stroke}|${line.dash}`)).size === 2 &&
      read.lines.every((line) => line.fill === "none") &&
      read.yTicks.length >= 3 && read.yTicks.every((tick) => /^\d+\.\d{2}%$/.test(tick)) &&
      read.axisLabel === "Yield, percent" && read.xTicks[0]?.[0] === expected.start &&
      read.xTicks.every(([, label]) => /^\d{1,2} [A-Z][a-z]{2}$/.test(label)) &&
      same(read.headers, ["Date", "2-year", "10-year", "Notes"]), JSON.stringify([read.yTicks, read.xTicks, read.legend]));
    const clipped = await evaluate(`(() => { const svg = document.querySelector(".context-chart svg").getBoundingClientRect();
      return [...document.querySelectorAll(".context-chart svg text")].map((t) => t.getBoundingClientRect())
        .filter((r) => r.left < svg.left - 0.5 || r.right > svg.right + 0.5).length; })()`);
    check(`${tag}: every chart label fits inside the drawing`, clipped === 0, String(clipped));
    const weekend = read.rows.filter((row) => /Sat|Sun/.test(row.label));
    check(`${tag}: weekends are listed as no session, never as missing`,
      weekend.length === 8 && weekend.every((row) => row.note === "No session" &&
        row.cells.every((cell) => cell.status === "not_a_session" && cell.text === "—")));
    check(`${tag}: SIFMA holidays are listed as no session, and are not gaps in the lines`,
      expected.holidays.every((date) => { const row = read.rows.find((r) => r.date === date);
        return row.note === "No session: SIFMA holiday" && row.cells.every((cell) => cell.status === "calendar_holiday" &&
          cell.text === "—"); }) &&
      read.rows.filter((row) => row.note === "No session: SIFMA holiday").length === expected.holidays.length &&
      read.missingMarks.every((mark) => !expected.holidays.some((date) => mark.endsWith(date))));
  };

  // A. The committed bundle of real H.15 downloads.
  let server = await startServer("committed");
  base = server.base;
  const baseline = {};
  for (const expected of CONTEXT) {
    await open(`/library/${expected.id}`);
    const shown = await waitFor(contextShown(expected.id));
    const read = await readContext();
    baseline[expected.id] = read;
    const view = await servedView(expected.id);
    check(`real ${expected.id}: a Market context section after the channels, numbered and listed on the page`,
      shown && same(read.sections, SECTIONS) && read.kicker === "04" && read.unavailable === "" &&
      read.toc.some(([title, href]) => title === "Market context" && href === "#context"), JSON.stringify(read.sections));
    check(`real ${expected.id}: the chart is labelled for assistive technology and points to the table`,
      read.svgRole === "img" && read.labelledBy === "context-chart-title context-chart-desc" &&
      read.svgDesc.includes(expected.label) && read.svgDesc.includes("table"));
    await agreement(expected, read, view, "real");
    check(`real ${expected.id}: every expected session has both values, so nothing is marked missing`,
      read.missingMarks.length === 0 && read.lines.length === 2 &&
      read.limits.includes("In this window every expected session has a value for both series."));
    const series = view.series;
    check(`real ${expected.id}: provenance names the Board's series, units, rights, retrieval, vintage, calendar and hashes`,
      read.provenance.includes("H15/H15/RIFLGFCY02_N.B") && read.provenance.includes("H15/H15/RIFLGFCY10_N.B") &&
      read.provenance.includes("percent per year (the source's unit: Percent:_Per_Year)") &&
      read.provenance.includes("Board of Governors of the Federal Reserve System, H.15 Selected Interest Rates") &&
      read.provenance.includes("is in the public domain and may be copied and distributed without permission") &&
      read.provenance.includes(`Requested ${view.source.requested_at}`) &&
      (expected.run === 1 ? /^2026-10-07T22:07:/ : /^2026-10-07T22:(48|49|50):/).test(view.source.requested_at) &&
      read.provenance.includes("nothing here is affiliated with or endorsed by the Board") &&
      read.provenance.includes("excepts non-Board material marked as copyrighted or trademarked") &&
      read.provenance.includes("Data Download Program") && !/synthetic/i.test(read.provenance) &&
      read.provenance.includes("pre-revision or real-time data are not available") &&
      read.provenance.includes("SIFMA") && read.provenance.includes(view.provenance.view_sha256) &&
      read.provenance.includes(view.provenance.manifest_sha256) && read.provenance.includes(view.provenance.acquisition_sha256) &&
      read.provenance.includes(view.source.sha256) && read.provenance.includes(view.source.url) &&
      view.source.url.startsWith("https://www.federalreserve.gov/datadownload/Output.aspx?rel=H15&") &&
      read.provenance.includes("no value here came from FRED") &&
      read.links.some(([href, target, rel]) => href === "https://fred.stlouisfed.org/series/DGS2" && target === "_blank" && rel === "noreferrer") &&
      read.links.some(([href]) => href === "https://fred.stlouisfed.org/series/DGS10") &&
      read.links.some(([href]) => href === "https://www.federalreserve.gov/disclaimer.htm") &&
      read.links.some(([href]) => href === "https://www.federalreserve.gov/data/documents/DDP-FRED%20Data%20Series%20Crosswalk.csv") &&
      series.every((item) => read.provenance.includes(item.description.split(/\s+/).join(" "))) &&
      read.provenance.includes("re-derived every value and status above from the source file") &&
      read.citations.length === 2 && read.citations.every((citation) => citation.includes("retrieved October 7, 2026 (UTC)")),
      read.provenance.slice(0, 400));
    check(`real ${expected.id}: the acquisition run, its own manifest and record, and any discarded replies are shown`,
      view.provenance.run === expected.run && view.provenance.runs === 2 &&
      read.provenance.includes(`Run ${expected.run} of 2, one of ${expected.run === 1 ? 3 : 9} downloads made together`) &&
      read.provenance.includes(`run manifest (${expected.run === 1 ? "manifest.json" : "manifest-2.json"})`) &&
      read.provenance.includes(`acquisition record (sources/${expected.run === 1 ? "acquisition.json" : "acquisition-2.json"})`) &&
      read.provenance.includes(view.provenance.index_sha256) && view.provenance.discarded.length === expected.discarded &&
      (expected.discarded === 0
        ? read.provenance.includes("No reply to this address was discarded in its run.")
        : read.provenance.includes("Before it, one reply to this address was discarded") &&
          read.provenance.includes("an empty reply (HTTP 200, text/html, 0 bytes). Nothing from it is used.")),
      JSON.stringify(view.provenance.discarded));
    check(`real ${expected.id}: it says what it is not: no attribution, no time of day, no score, not a vintage`,
      read.intro.includes("not intraday prices, transaction prices, bond returns or a measured reaction") &&
      read.intro.includes("the source gives no time of day") &&
      read.limits.includes("does not attribute any movement to the release") &&
      read.limits.includes("not a moment in the series") && read.limits.includes("not an event study, a hypothesis or a score") &&
      read.limits.includes("not a historical vintage") && read.limits.includes("nothing is interpolated") &&
      read.benchmark.includes("does not say whether the release was a surprise") &&
      read.benchmark.includes("description only"));
  }

  // Dates are calendar dates: another browser time zone shows the same rows, ticks, marker and points.
  // Minutes behind UTC on 3 Jul 2025, as getTimezoneOffset reports them: proof that each override took effect.
  const OFFSETS = { "UTC": 0, "America/New_York": 240, "Pacific/Kiritimati": -840, "Pacific/Pago_Pago": 660 };
  const startingOffset = await evaluate(`new Date("2025-07-03T12:00:00Z").getTimezoneOffset()`);
  for (const [zone, offset] of Object.entries(OFFSETS)) {
    await send("Emulation.setTimezoneOverride", { timezoneId: zone });
    for (const expected of CONTEXT) {
      await open(`/library/${expected.id}`);
      await waitFor(contextShown(expected.id));
      const read = await readContext();
      const zoneOffset = await evaluate(`new Date("2025-07-03T12:00:00Z").getTimezoneOffset()`);
      const was = baseline[expected.id];
      check(`real ${expected.id} in ${zone}: the same dates, labels, ticks, marker and points`,
        zoneOffset === offset && zoneOffset !== startingOffset && read.rows.length === 29 &&
        same(read.rows.map((r) => [r.date, r.label, r.note]), was.rows.map((r) => [r.date, r.label, r.note])) &&
        same(read.xTicks, was.xTicks) && same(read.marker, was.marker) && same(read.points, was.points),
        `${zoneOffset} ${JSON.stringify(read.marker)}`);
    }
  }
  await send("Emulation.setTimezoneOverride", { timezoneId: "" });

  // Keyboard: the table-of-contents entry and the skip link reach the section and the data.
  await open(`/library/${CONTEXT[1].id}`);
  await waitFor(contextShown(CONTEXT[1].id));
  await evaluate(`document.querySelector('.library-toc a[href="#context"]').focus()`);
  await press("Enter", "Enter", 13, "\r");
  check("the Market context entry on the page opens the section from the keyboard",
    await waitFor(`location.hash === "#context" && Math.abs(document.querySelector("#context").getBoundingClientRect().top) < 40`));
  await evaluate(`document.querySelector('.context-skip-row a').focus()`);
  await press("Enter", "Enter", 13, "\r");
  check("the data table is one keyboard step from the chart",
    await waitFor(`location.hash === "#context-data" && document.querySelector("#context-data").getBoundingClientRect().top < innerHeight`));

  // A direct reload shows the context again.
  await send("Page.reload", { ignoreCache: true });
  check("a direct reload of a case shows its market context again",
    await waitFor(contextShown(CONTEXT[1].id)) && (await readContext()).rows.length === 29);

  // Search and a category lead to a case, whose context shows; Back returns to the same filtered list.
  await open("/library?q=cpi&category=inflation");
  await waitFor(`document.querySelectorAll(".library-index .library-entry").length === 4`);
  const firstHref = await evaluate(`document.querySelector(".library-index .library-entry a")?.getAttribute("href")`);
  await evaluate(`document.querySelector(".library-index .library-entry a").click()`);
  const opened = await waitFor(contextShown("cpi-2025-04-10")) && (await readContext()).rows.length === 29;
  await send("Runtime.evaluate", { expression: "history.back()" });
  check("a search and a category lead to a case with its market context, and Back restores the filtered list",
    firstHref === "/library/cpi-2025-04-10" && opened &&
    await waitFor(`location.search === "?q=cpi&category=inflation" &&
      document.querySelectorAll(".library-index .library-entry").length === 4`), String(firstHref));
  const unknown = await evaluate(`fetch("/api/case-library/no-such-case/market-context").then((r) => r.status)`);
  check("an address that is not a case has no market context", unknown === 404, String(unknown));

  // Narrow screens: no sideways scrolling, readable text, the chart within the screen.
  await viewport(375, 812, true);
  for (const expected of CONTEXT) {
    await open(`/library/${expected.id}`);
    await waitFor(contextShown(expected.id));
    await sleep(700);  // Let the entrance animation and web fonts settle before measuring.
    const layout = await evaluate(`(() => {
      const wide = [...document.querySelectorAll("body *")].filter((e) => e.getBoundingClientRect().right > innerWidth + 1)
        .map((e) => e.tagName + "." + e.className).slice(0, 3);
      const sizes = [...document.querySelectorAll(".context p, .context li, .context-table td, .context-table th:not(thead th), .context-provenance dd")]
        .filter((e) => !e.closest("code")).map((e) => parseFloat(getComputedStyle(e).fontSize));
      const svg = document.querySelector(".context-chart svg");
      const chart = svg.getBoundingClientRect();
      const labels = [...svg.querySelectorAll("text")].map((t) => t.getBoundingClientRect());
      const ticks = [...svg.querySelectorAll(".axis-tick text")].map((t) => t.getBoundingClientRect());
      return { scroll: document.documentElement.scrollWidth, width: innerWidth, wide, smallest: Math.min(...sizes),
               chartRight: chart.right, chartWidth: chart.width, drawing: svg.dataset.width,
               // The rendered height of the date labels: what a reader sees after the drawing is scaled to the screen.
               tickHeight: Math.min(...ticks.map((r) => r.height)),
               inside: labels.every((r) => r.left >= chart.left - 0.5 && r.right <= chart.right + 0.5),
               overlap: ticks.some((r, i) => i > 0 && r.left < ticks[i - 1].right) };
    })()`);
    check(`narrow screen ${expected.id}: no sideways scrolling, text at least 13px, chart within the screen`,
      layout.scroll <= layout.width && layout.wide.length === 0 && layout.smallest >= 13 &&
      layout.chartRight <= layout.width && layout.chartWidth > 300, JSON.stringify(layout));
    check(`narrow screen ${expected.id}: a compact chart whose labels stay readable, inside it and apart`,
      layout.drawing === "360" && layout.tickHeight >= 11 && layout.inside && !layout.overlap, JSON.stringify(layout));
  }
  await viewport(1280, 900, false);
  const phaseA = requests;
  requests = [];
  await server.stop();
  check("reading every page left the committed bundle byte-for-byte unchanged", fingerprint(COMMITTED) === committedBefore);

  // B. A synthetic bundle: gaps, a changed source, no bundle.
  server = await startServer("synthetic");
  base = server.base;
  const bundle = join(server.served, "market-context");
  const before = fingerprint(bundle);
  for (const expected of CONTEXT) {
    await open(`/library/${expected.id}`);
    await waitFor(contextShown(expected.id));
    const read = await readContext();
    const view = await servedView(expected.id);
    check(`synthetic ${expected.id}: the page says the values are synthetic test data`,
      read.provenance.includes("SYNTHETIC TEST DATA") && read.provenance.includes("not H.15 observations"));
    await agreement(expected, read, view, "synthetic");
    const gapLines = (series) => read.lines.filter((line) => line.series === series).length;
    check(`synthetic ${expected.id}: a missing expected session stays missing, is marked on the chart and breaks only its line`,
      same(read.missingMarks.sort(), expected.synthetic.map((gap) => `${gap.series}|${gap.date}`).sort()) &&
      expected.synthetic.every((gap) => { const row = read.rows.find((r) => r.date === gap.date);
        const cell = row.cells.find((c) => c.series === gap.series);
        return cell.text === "—" && cell.status === gap.status && row.note === gap.note && gapLines(gap.series) === 2; }) &&
      [TWO, TEN].every((series) => expected.synthetic.some((gap) => gap.series === series) || gapLines(series) === 1) &&
      (expected.synthetic.length === 0
        ? read.limits.includes("every expected session has a value for both series")
        : read.limits.includes("Expected sessions without a value are marked on the chart and listed in the table")),
      JSON.stringify(read.missingMarks));
  }
  const source = join(bundle, "sources", "cpi-2025-07-15.csv");
  const original = readFileSync(source);
  writeFileSync(source, Buffer.from(original.toString("latin1").replace("2025-07-02,1.01", "2025-07-02,1.11"), "latin1"));
  await open("/library/cpi-2025-07-15");
  await waitFor(contextShown("cpi-2025-07-15"));
  let read = await readContext();
  check("a source file changed after preparation is refused with the reason, and no values are shown",
    (await evaluate(`document.querySelector(".context-unavailable")?.dataset.state`)) === "error" &&
    read.unavailable.includes("does not match its recorded SHA-256") && read.unavailable.includes("No substitute") &&
    read.points.length === 0 && read.rows.length === 0 && same(read.sections, SECTIONS) &&
    (await text("#overview")).length > 200, read.unavailable);
  writeFileSync(source, original);
  const unavailable = async (id) => {
    await open(`/library/${id}`);
    await waitFor(contextShown(id));
    return { state: await evaluate(`document.querySelector(".context-unavailable")?.dataset.state`), read: await readContext() };
  };
  renameSync(join(bundle, "manifest.json"), join(bundle, "manifest.json.away"));
  let shown = await unavailable("fomc-2025-03-19");
  check("a missing run manifest is refused with the reason, and no values are shown",
    shown.state === "error" && shown.read.unavailable.includes("manifest.json, the manifest of acquisition run 1, is missing") &&
    shown.read.points.length === 0 && shown.read.rows.length === 0 && same(shown.read.sections, SECTIONS), shown.read.unavailable);
  renameSync(join(bundle, "manifest.json.away"), join(bundle, "manifest.json"));
  const viewFile = join(bundle, "fomc-2025-06-18.json");
  const viewBytes = readFileSync(viewFile);
  writeFileSync(viewFile, "{ malformed");
  shown = await unavailable("fomc-2025-06-18");
  check("a malformed prepared view is refused with the reason, and no values are shown",
    shown.state === "error" && shown.read.unavailable.includes("does not match its recorded SHA-256") &&
    shown.read.points.length === 0 && shown.read.rows.length === 0, shown.read.unavailable);
  writeFileSync(viewFile, viewBytes);
  renameSync(join(bundle, "index.json"), join(bundle, "index.json.away"));
  shown = await unavailable("fomc-2025-03-19");
  check("without a prepared bundle (no index) the section says so and shows nothing in its place",
    shown.state === "not-prepared" && shown.read.unavailable.includes("Market context has not been prepared") &&
    shown.read.points.length === 0 && shown.read.rows.length === 0 && same(shown.read.sections, SECTIONS));
  renameSync(join(bundle, "index.json.away"), join(bundle, "index.json"));
  await open("/library/fomc-2025-03-19");
  check("restoring the files restores the context", await waitFor(`document.querySelectorAll(".context-table tbody tr").length === 29`));
  check("the synthetic bundle is byte-for-byte as prepared after the checks", fingerprint(bundle) === before);
  await server.stop();

  // Both phases: reads only, and nothing outside the local server.
  for (const [phase, list] of [["real", phaseA], ["synthetic", requests]]) {
    const writes = list.filter((request) => request.url.includes("/api/") && request.method !== "GET");
    check(`${phase}: the pages only read: every API request was a GET`, list.length > 20 && writes.length === 0,
      writes.map((r) => `${r.method} ${r.url}`).join(", "));
    const outside = list.filter(({ url }) => !url.startsWith("http://127.0.0.1:") && !url.startsWith("data:") && url !== "about:blank");
    check(`${phase}: nothing outside the local server was requested`, outside.length === 0, outside.map((r) => r.url).join(", "));
  }
  ws.close();
} catch (error) {
  check("the market context browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(500);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  check("the committed bundle is byte-for-byte unchanged at the end", fingerprint(COMMITTED) === committedBefore);
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
