// Market context helpers: dates stay calendar dates, gaps stay gaps, and the chart shows exactly what the table shows.
// The first tests use a small SYNTHETIC view; the last ones read the views captured from the committed bundle of real
// H.15 downloads (see tests/test_market_context.py, which keeps the captures equal to what the server serves).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  CHART, CHART_NARROW, MARKET_CONTEXT_VIEW_VERSION, STATUS_LABEL, chartModel, contextRows, dayNumber,
  discardedNote, formatContextDate, gapCounts, type ContextDay, type MarketContextView,
} from "../src/marketContext.ts";

const TWO = "RIFLGFCY02_N.B";
const TEN = "RIFLGFCY10_N.B";

/** The zone this process started in. Deleting TZ does not make Node resolve its zone again, so it is set back by name. */
const STARTING_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;
const STARTING_TZ = process.env.TZ;

/** Runs `body` with this process's time zone set to `zone`, then restores both the zone and the TZ variable. */
function inZone<T>(zone: string, body: () => T): T {
  const original = process.env.TZ;
  process.env.TZ = zone;
  try {
    return body();
  } finally {
    process.env.TZ = original ?? STARTING_ZONE;  // Setting TZ makes Node resolve the zone again.
    if (original === undefined) delete process.env.TZ;  // Deleting does not, so the starting zone stays in force.
  }
}

const observed = (raw: string) => ({ raw, value: Number(raw), status: "session_value" });
const none = (status: string, raw: string | null = null) => ({ raw, value: null, status });
const day = (date: string, weekday: string, session: boolean, two: object, ten: object): ContextDay =>
  ({ date, weekday, session, observations: { [TWO]: two, [TEN]: ten } as ContextDay["observations"] });

/** Synthetic: a Friday holiday, a weekend, a missing 10-year value on Tuesday. */
const DAYS: ContextDay[] = [
  day("2025-07-02", "Wed", true, observed("3.78"), observed("4.26")),
  day("2025-07-03", "Thu", true, observed("3.88"), observed("4.35")),
  day("2025-07-04", "Fri", false, none("calendar_holiday", "ND"), none("calendar_holiday", "ND")),
  day("2025-07-05", "Sat", false, none("not_a_session"), none("not_a_session")),
  day("2025-07-06", "Sun", false, none("not_a_session"), none("not_a_session")),
  day("2025-07-07", "Mon", true, observed("3.90"), observed("4.40")),
  day("2025-07-08", "Tue", true, observed("3.91"), none("session_missing", "ND")),
  day("2025-07-09", "Wed", true, observed("3.86"), observed("4.34")),
];
const VIEW = {
  view_version: MARKET_CONTEXT_VIEW_VERSION, case_id: "empsit-2025-07-03",
  publication: { published_at: "2025-07-03T08:30:00-04:00", new_york_date: "2025-07-03" },
  window: { start: "2025-07-02", end: "2025-07-09", days_before: 14, days_after: 14 },
  series: [{ id: TWO, label: "2-year Treasury yield", short_label: "2-year" },
           { id: TEN, label: "10-year Treasury yield", short_label: "10-year" }],
  days: DAYS,
} as unknown as MarketContextView;

const load = (caseId: string): MarketContextView =>
  JSON.parse(readFileSync(new URL(`./fixtures/market-context-${caseId}.json`, import.meta.url), "utf-8"));
/** All twelve captured views: window, New York publication date, SIFMA holidays, and the acquisition run. */
const REAL: Record<string, { start: string; end: string; day: string; holidays: string[]; run: number }> = {
  "fomc-2025-01-29": { start: "2025-01-15", end: "2025-02-12", day: "2025-01-29", holidays: ["2025-01-20"], run: 2 },
  "fomc-2025-03-19": { start: "2025-03-05", end: "2025-04-02", day: "2025-03-19", holidays: [], run: 1 },
  "empsit-2025-04-04": { start: "2025-03-21", end: "2025-04-18", day: "2025-04-04", holidays: ["2025-04-18"], run: 2 },
  "cpi-2025-04-10": { start: "2025-03-27", end: "2025-04-24", day: "2025-04-10", holidays: ["2025-04-18"], run: 2 },
  "empsit-2025-05-02": { start: "2025-04-18", end: "2025-05-16", day: "2025-05-02", holidays: ["2025-04-18"], run: 2 },
  "fomc-2025-05-07": { start: "2025-04-23", end: "2025-05-21", day: "2025-05-07", holidays: [], run: 2 },
  "cpi-2025-05-13": { start: "2025-04-29", end: "2025-05-27", day: "2025-05-13", holidays: ["2025-05-26"], run: 2 },
  "empsit-2025-06-06": { start: "2025-05-23", end: "2025-06-20", day: "2025-06-06", holidays: ["2025-05-26", "2025-06-19"],
                         run: 2 },
  "cpi-2025-06-11": { start: "2025-05-28", end: "2025-06-25", day: "2025-06-11", holidays: ["2025-06-19"], run: 2 },
  "fomc-2025-06-18": { start: "2025-06-04", end: "2025-07-02", day: "2025-06-18", holidays: ["2025-06-19"], run: 2 },
  "empsit-2025-07-03": { start: "2025-06-19", end: "2025-07-17", day: "2025-07-03", holidays: ["2025-06-19", "2025-07-04"],
                         run: 1 },
  "cpi-2025-07-15": { start: "2025-07-01", end: "2025-07-29", day: "2025-07-15", holidays: ["2025-07-04"], run: 1 },
};

test("calendar dates never move with the reader's time zone", () => {
  /** Everything the drawing places by date: ticks, marker and points, with their positions. */
  const drawn = () => {
    const model = chartModel(load("empsit-2025-07-03"));
    return { ticks: model.xTicks.map((t) => [t.date, t.label, t.x]), marker: model.marker,
             points: model.lines.map((line) => line.points.map((p) => [p.date, p.cx])) };
  };
  const reference = inZone("UTC", drawn);
  assert.deepEqual(reference.ticks.map(([date]) => date), ["2025-06-19", "2025-06-26", "2025-07-03", "2025-07-10", "2025-07-17"]);
  for (const zone of [STARTING_ZONE, "UTC", "America/New_York", "Asia/Jerusalem", "Asia/Tokyo", "Pacific/Kiritimati",
                      "Pacific/Pago_Pago"]) {
    inZone(zone, () => {
      assert.equal(dayNumber("2025-07-03"), 20272, zone);  // Days since 1970-01-01, whatever the zone.
      assert.equal(dayNumber("2025-07-03") - dayNumber("2025-07-02"), 1, zone);
      assert.equal(formatContextDate("2025-07-03"), "3 Jul 2025", zone);
      assert.equal(formatContextDate("2025-03-19"), "19 Mar 2025", zone);
      const model = chartModel(VIEW);
      assert.equal(model.marker.date, "2025-07-03", zone);
      assert.equal(model.marker.x, model.x(dayNumber("2025-07-03")), zone);
      assert.equal(model.xTicks[0].date, "2025-07-02", zone);
      assert.deepEqual(drawn(), reference, zone);
    });
  }
  assert.equal(Intl.DateTimeFormat().resolvedOptions().timeZone, STARTING_ZONE);  // Restored for the tests that follow.
  assert.equal(process.env.TZ, STARTING_TZ);
  assert.throws(() => dayNumber("2025-7-3"));
  assert.throws(() => dayNumber("2025-02-30"));
});

test("only observed values are drawn; gaps at missing sessions break the line, weekends and holidays do not", () => {
  const model = chartModel(VIEW);
  const two = model.lines.find((line) => line.id === TWO)!;
  const ten = model.lines.find((line) => line.id === TEN)!;
  assert.deepEqual(two.points.map((point) => point.date), ["2025-07-02", "2025-07-03", "2025-07-07", "2025-07-08", "2025-07-09"]);
  assert.equal(two.segments.length, 1);  // Holiday and weekend: not gaps in the series.
  assert.deepEqual(ten.points.map((point) => point.date), ["2025-07-02", "2025-07-03", "2025-07-07", "2025-07-09"]);
  assert.deepEqual(ten.segments.map((segment) => segment.map((point) => point.date)),
                   [["2025-07-02", "2025-07-03", "2025-07-07"], ["2025-07-09"]]);  // Tuesday's missing value: a break.
  assert.deepEqual(ten.missing, ["2025-07-08"]);
  assert.deepEqual(two.missing, []);
  assert.deepEqual([two.tag, ten.tag], ["2y", "10y"]);
  assert.deepEqual(gapCounts(VIEW).map(({ series, count }) => [series.id, count]), [[TWO, 0], [TEN, 1]]);
});

test("the value axis is labelled in percent and contains every value", () => {
  const model = chartModel(VIEW);
  assert.ok(model.yTicks.length >= 3);
  assert.ok(model.yTicks.every((tick) => /^\d+\.\d{2}%$/.test(tick.label)), model.yTicks.map((t) => t.label).join(","));
  const values = DAYS.flatMap((d) => [d.observations[TWO].value, d.observations[TEN].value]).filter((v) => v !== null);
  assert.ok(model.yDomain[0] <= Math.min(...values) && model.yDomain[1] >= Math.max(...values));
  assert.equal(model.xTicks[0].date, "2025-07-02");
});

test("a narrow chart keeps every point, tick and the marker inside its own plotting area", () => {
  for (const size of [CHART, CHART_NARROW]) {
    const model = chartModel(VIEW, size);
    const xs = [...model.lines.flatMap((line) => line.points.map((point) => point.cx)), ...model.xTicks.map((t) => t.x),
                model.marker.x];
    const ys = [...model.lines.flatMap((line) => line.points.map((point) => point.cy)), ...model.yTicks.map((t) => t.y)];
    assert.ok(xs.every((x) => x >= size.left && x <= size.width - size.right), `${size.width}: ${xs.join(",")}`);
    assert.ok(ys.every((y) => y >= size.top && y <= size.height - size.bottom), `${size.width}: ${ys.join(",")}`);
  }
  assert.ok(CHART_NARROW.width < CHART.width / 1.5);
});

test("the table shows the same values as the chart, and every status in words", () => {
  const rows = contextRows(VIEW);
  assert.equal(rows.length, DAYS.length);
  const fromChart = chartModel(VIEW).lines.flatMap((line) => line.points.map((point) => `${line.id}|${point.date}|${point.raw}`));
  const fromTable = rows.flatMap((row) => row.cells.filter((cell) => cell.observed)
    .map((cell) => `${cell.series}|${row.date}|${cell.text.replace("%", "")}`));
  assert.deepEqual([...fromChart].sort(), [...fromTable].sort());
  const tuesday = rows.find((row) => row.date === "2025-07-08")!;
  assert.equal(tuesday.cells.find((cell) => cell.series === TEN)!.text, "—");
  assert.equal(tuesday.note, "10-year: missing: expected session, the source gives no value");
  assert.equal(rows.find((row) => row.date === "2025-07-04")!.note, "No session: SIFMA holiday");
  assert.equal(rows.find((row) => row.date === "2025-07-05")!.note, "No session");
  assert.equal(rows.find((row) => row.date === "2025-07-03")!.publication, true);
  for (const status of ["session_value", "session_missing", "session_absent", "calendar_holiday", "not_a_session",
                        "unreconciled_value_on_calendar_holiday", "issuer_no_observation",
                        "issuer_observation_on_calendar_holiday"]) {
    assert.ok(STATUS_LABEL[status], status);
  }
});

test("the real views: 29 New York dates, the publication date on the middle tick, holidays named, no gaps", () => {
  for (const [caseId, expected] of Object.entries(REAL)) {
    const view = load(caseId);
    assert.equal(view.view_version, MARKET_CONTEXT_VIEW_VERSION, caseId);
    assert.deepEqual([view.window.start, view.window.end, view.publication.new_york_date],
                     [expected.start, expected.end, expected.day], caseId);
    const rows = contextRows(view);
    assert.equal(rows.length, 29, caseId);
    assert.deepEqual(rows.filter((row) => row.note === "No session: SIFMA holiday").map((row) => row.date),
                     expected.holidays, caseId);
    assert.equal(rows.filter((row) => row.note === "No session").length, 8, caseId);  // Four weekends.
    assert.deepEqual(rows.filter((row) => row.publication).map((row) => row.date), [expected.day], caseId);
    const model = chartModel(view);
    assert.equal(model.xTicks[2].date, expected.day, caseId);
    assert.equal(model.marker.x, model.xTicks[2].x, caseId);
    assert.ok(model.lines.every((line) => line.missing.length === 0 && line.segments.length === 1), caseId);
    assert.ok(gapCounts(view).every(({ count }) => count === 0), caseId);
    assert.deepEqual(view.series.map((series) => [series.id, series.units_label, series.fred_equivalent]),
                     [[TWO, "Percent per year", "DGS2"], [TEN, "Percent per year", "DGS10"]], caseId);
    assert.deepEqual([view.provenance.run, view.provenance.runs, view.provenance.manifest],
                     [expected.run, 2, expected.run === 1 ? "manifest.json" : "manifest-2.json"], caseId);
    assert.ok(view.provenance.run_cases.includes(caseId), caseId);
  }
  assert.equal(Object.keys(REAL).length, 12);
});

test("refused replies are described in words, and none is presented as data", () => {
  assert.equal(discardedNote([]), "No reply to this address was discarded in its run.");
  const refused = { requested_at: "2026-10-07T22:48:24+00:00", http_status: 200, content_type: "text/html", bytes: 0,
                    reason: "an empty reply" };
  assert.equal(discardedNote([refused]), "Before it, one reply to this address was discarded: 2026-10-07T22:48:24+00:00, " +
    "an empty reply (HTTP 200, text/html, 0 bytes). Nothing from it is used.");
  assert.match(discardedNote([refused, { ...refused, http_status: null, content_type: null }]),
               /^Before it, 2 replies .*\(HTTP none, no content type, 0 bytes\)\. Nothing from them is used\.$/);
  const real = Object.keys(REAL).map((caseId) => [caseId, load(caseId).provenance.discarded.length]);
  assert.equal(real.reduce((total, [, count]) => total + Number(count), 0), 6);  // Run 2's six refused first attempts.
  assert.ok(real.every(([caseId, count]) => REAL[String(caseId)].run === 2 || count === 0));
});

test("the real views: the chart and the table show exactly the source's values, as written", () => {
  for (const caseId of Object.keys(REAL)) {
    const view = load(caseId);
    const fromView = view.days.flatMap((d) => view.series.flatMap((series) => {
      const observation = d.observations[series.id];
      return observation.value === null ? [] : [`${series.id}|${d.date}|${observation.raw}`];
    })).sort();
    const fromChart = chartModel(view).lines.flatMap((line) => line.points.map((p) => `${line.id}|${p.date}|${p.raw}`)).sort();
    const fromTable = contextRows(view).flatMap((row) => row.cells.filter((cell) => cell.observed)
      .map((cell) => `${cell.series}|${row.date}|${cell.text.replace(/%$/, "")}`)).sort();
    assert.ok(fromView.length >= 38, caseId);
    assert.deepEqual(fromChart, fromView, caseId);
    assert.deepEqual(fromTable, fromView, caseId);
    for (const d of view.days) {
      for (const series of view.series) {
        const observation = d.observations[series.id];
        if (observation.value !== null) assert.equal(String(observation.value), String(Number(observation.raw)));
      }
    }
    assert.ok(view.series.every((series) => series.values + series.no_value_rows === view.source.rows), caseId);
  }
});
