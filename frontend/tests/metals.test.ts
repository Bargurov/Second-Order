// The metals reader (metals.ts) against replies captured from the server (tests/fixtures/metals-*.json).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { METAL_IDS, metalsRefusal, reservesFor, UNIT_ISSUES, YEARS_UNDER_ONE } from "../src/metals.ts";

const fixture = (name: string) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf-8"));
const refusal = (change: (body: any) => void, name = "metals-view.json") => {
  const body = fixture(name);
  change(body);
  return metalsRefusal(body);
};
const chapter = (body: any, id: string) => body.usgs.chapters.find((c: any) => c.id === id);
const withTop3 = (body: any) => body.usgs.chapters.flatMap((c: any) => c.series).find((s: any) => s.top3.countries.length === 3);

test("the captured replies pass", () => {
  for (const name of ["metals-view.json", "metals-usgs-changed.json", "metals-unavailable.json"])
    assert.equal(metalsRefusal(fixture(name)), null, name);
  assert.equal(METAL_IDS.length, 45);
});

test("a share that does not follow its numbers is refused, naming its place", () => {
  const message = refusal((body) => {
    const series = chapter(body, "cobalt").series.find((s: any) => s.countries.some((c: any) => c.country.startsWith("Congo")));
    series.countries.find((c: any) => c.country.startsWith("Congo")).share.shown = "74.3";
  });
  assert.match(message ?? "", /usgs\.cobalt\..*share/);
  assert.ok(!(message ?? "").includes("74.3"));
});

test("a withheld part that carries a value is refused", () => {
  assert.ok(refusal((body) => { body.usgs.chapters[0].series = []; }, "metals-unavailable.json"));
  assert.ok(refusal((body) => { body.iea.minerals[0].demand = {}; }, "metals-unavailable.json"));
});

test("a part shown as available over a source that did not verify is refused", () => {
  assert.match(refusal((body) => { body.sources[0].state = "changed"; }) ?? "", /usgs\.state/);
  assert.match(refusal((body) => { body.sources[1].state = "missing"; }) ?? "", /iea\.state/);
});

test("a number that is not what is printed is refused", () => {
  const message = refusal((body) => {
    const series = body.usgs.chapters.flatMap((c: any) => c.series)[0];
    series.world.value = "W";
    series.world.number = "0";
  });
  assert.match(message ?? "", /number/);
});

test("a top-3 out of order is refused", () => {
  const message = refusal((body) => {
    const names = withTop3(body).top3.countries;
    [names[0], names[1]] = [names[1], names[0]];
  });
  assert.match(message ?? "", /top3\.countries/);
});

test("a top-3 total, a years figure or a provider call that is not as recomputed is refused", () => {
  assert.match(refusal((body) => { withTop3(body).top3.shown = "99.9"; }) ?? "", /top3\.shown/);
  assert.match(refusal((body) => {
    body.usgs.chapters.find((c: any) => c.years_of_reserves.length).years_of_reserves[0].shown = "1";
  }) ?? "", /years_of_reserves/);
  assert.match(refusal((body) => { body.provider_called = true; }) ?? "", /provider_called/);
});

test("an IEA share or published top-3 that is not recomputed is refused", () => {
  assert.match(refusal((body) => { body.iea.minerals[0].supply[0].countries[0].shares["2025"] = "50.1"; }) ?? "",
    /iea\.copper\..*shares/);
  assert.match(refusal((body) => { body.iea.minerals[0].supply[0].top3_published["2025"] = "86.80"; }) ?? "",
    /top3_published/);
  assert.match(refusal((body) => { body.iea.minerals[0].supply[0].total["2025"] = "0"; }) ?? "", /total/);
});

const mine = (body: any, id: string) => chapter(body, id).series.find((s: any) => s.statistic === "Production");

test("a leader whose share or name is not as recomputed is refused, naming its place without the value", () => {
  const shown = refusal((body) => { mine(body, "cobalt").leader.shown = "74.3"; });
  assert.match(shown ?? "", /^usgs\.cobalt\.series\[0\]\.leader\.shown: /);
  assert.ok(!(shown ?? "").includes("74.3") && !(shown ?? "").includes("74.2"));
  const name = refusal((body) => { mine(body, "cobalt").leader.countries = ["Indonesia"]; });
  assert.match(name ?? "", /^usgs\.cobalt\.series\[0\]\.leader\.countries: /);
  assert.ok(!(name ?? "").includes("Indonesia"));
});

test("a country printed as a dash counts as zero in the order; any other print still blocks it", () => {
  const tin = mine(fixture("metals-view.json"), "tin");
  assert.equal(tin.countries[0].value, "—");
  assert.deepEqual(tin.countries[0].share, { shown: null, reason: "Printed as “—”" });
  assert.deepEqual(tin.leader.countries, ["Kappa"]);
  assert.deepEqual(tin.top3.countries, ["Kappa", "Omega", "Sigma"]);
  // The dash's name comes first, but it never outranks a positive value.
  assert.match(refusal((body) => { mine(body, "tin").leader.countries = ["Delta"]; }) ?? "", /tin\..*leader\.countries/);
  // A padded dash is still a dash.
  assert.equal(refusal((body) => { mine(body, "tin").countries[0].value = " — "; }), null);
  // Printed "W" (or as a word), the order is unknown, so a leader shown is refused.
  for (const printed of ["W", "NA", "-"]) {
    assert.match(refusal((body) => { mine(body, "tin").countries[0].value = printed; }) ?? "", /tin\..*leader/, printed);
  }
});

test("a valid ratio under one year is shown as less than 1, never withheld for its size", () => {
  const years = chapter(fixture("metals-view.json"), "silver").years_of_reserves[0];
  assert.deepEqual([years.shown, years.reason, YEARS_UNDER_ONE], ["less than 1", null, "less than 1"]);
  for (const shown of ["0", "1", "0.5"]) {
    assert.match(refusal((body) => { chapter(body, "silver").years_of_reserves[0].shown = shown; }) ?? "",
      /^usgs\.silver\.years_of_reserves\[0\]\.shown: /, shown);
  }
  assert.match(refusal((body) => {
    Object.assign(chapter(body, "silver").years_of_reserves[0], { shown: null, reason: "The units may differ" });
  }) ?? "", /^usgs\.silver\.years_of_reserves\[0\]\.shown: /);
});

const VANADIUM_RESERVES = "vanadium/reserves/reserves/metric-tons/2025";
const reservesOf = (body: any) => chapter(body, "vanadium").series.find((s: any) => s.id === VANADIUM_RESERVES);

test("a known unit issue is the fixed one for its series, and its years are withheld with it", () => {
  const body = fixture("metals-view.json");
  const issue = UNIT_ISSUES[VANADIUM_RESERVES];
  assert.match(issue, /^Unit in doubt: .*thousand metric tons.*metric tons/);
  assert.equal(reservesOf(body).unit_issue, issue);
  assert.equal(mine(body, "vanadium").unit_issue, null);
  const years = chapter(body, "vanadium").years_of_reserves[0];
  assert.deepEqual([years.shown, years.reason], [null, `Reserves: ${issue}`]);
  // The shares stay: a share divides two figures of the same column.
  assert.ok(reservesOf(body).countries.every((cell: any) => typeof cell.share.shown === "string"));
  assert.match(refusal((b) => { reservesOf(b).unit_issue = null; }) ?? "", /^usgs\.vanadium\.series\[\d\]\.unit_issue: /);
  assert.match(refusal((b) => { mine(b, "copper").unit_issue = issue; }) ?? "", /^usgs\.copper\.series\[0\]\.unit_issue: /);
  assert.match(refusal((b) => {
    Object.assign(chapter(b, "vanadium").years_of_reserves[0], { shown: "less than 1", reason: null });
  }) ?? "", /^usgs\.vanadium\.years_of_reserves\[0\]\.shown: /);
  assert.match(refusal((b) => { chapter(b, "vanadium").years_of_reserves[0].reason = "Not shown"; }) ?? "",
    /^usgs\.vanadium\.years_of_reserves\[0\]\.reason: /);
});

// metals_usgs.chapter_id, and a series id made the server's way from its own fields.
const slug = (name: string) => name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
const idOf = (body: any, id: string, series: any) =>
  [slug(chapter(body, id).chapter), slug(series.statistic), slug(series.detail), slug(series.unit), series.year].join("/");
/** Copper's years entry after `change` to its two series, each id made again from its fields and the entry pointed at
 * them, so only the pair itself can be wrong; the two world totals, and so the division, are untouched. */
const remade = (change: (reserves: any, production: any) => void) => refusal((body) => {
  const copper = chapter(body, "copper");
  const years = copper.years_of_reserves[0];
  const reserves = copper.series.find((s: any) => s.id === years.reserves);
  const production = copper.series.find((s: any) => s.id === years.production);
  change(reserves, production);
  reserves.id = years.reserves = idOf(body, "copper", reserves);
  production.id = years.production = idOf(body, "copper", production);
});

test("a series id is made from its chapter, statistic, detail, unit and year", () => {
  assert.equal(remade(() => {}), null);
  assert.match(refusal((body) => { mine(body, "copper").id = "copper/production/smelter-production/metric-tons/2025"; })
    ?? "", /^usgs\.copper\.series\[0\]\.id: /);
  // One field changed and the id left as it was (the independent review's audit): each is refused.
  for (const [field, value] of [["unit", "kilograms"], ["year", "2024"], ["statistic", "Production"],
    ["detail", "Refinery capacity"]]) {
    const message = refusal((body) => {
      const copper = chapter(body, "copper");
      copper.series.find((s: any) => s.id === copper.years_of_reserves[0].reserves)[field] = value;
    });
    assert.match(message ?? "", /^usgs\.copper\.series\[\d\]\.id: /, field);
    assert.ok(!(message ?? "").includes(value), field);
  }
});

test("a years pair that differs in commodity, unit, year, statistic or stage is refused with the same division", () => {
  const cases: [string, (reserves: any, production: any) => void, RegExp][] = [
    ["commodity", (reserves) => { reserves.commodity = "Cobalt"; }, /different commodities/],
    ["unit", (reserves) => { reserves.unit = "kilograms"; }, /different units/],
    ["reserves year", (reserves) => { reserves.year = "2024"; }, /two 2025 series/],
    ["production year", (_r, production) => { production.year = "2024"; }, /two 2025 series/],
    ["statistic", (reserves) => { reserves.statistic = "Production"; }, /a reserves series with a production series/],
    ["reserves stage", (reserves) => { reserves.detail = "Refinery capacity"; }, /different stages/],
    ["production stage", (_r, production) => { production.detail = "Smelter production"; }, /different stages/],
    ["production qualifier", (_r, production) => { production.detail = "Mine production: Ilmenite"; }, /different stages/],
  ];
  for (const [name, change, rule] of cases) {
    const message = remade(change);
    assert.match(message ?? "", /^usgs\.copper\.years_of_reserves\[0\]: /, name);
    assert.match(message ?? "", rule, name);
    for (const value of ["43", "980000", "23000", "Cobalt", "kilograms", "2024"]) assert.ok(!(message ?? "").includes(value), name);
  }
});

test("a world total printed as zero carries its own reason", () => {
  const zero = (reason: string) => (body: any) => {
    const series = mine(body, "cobalt");
    Object.assign(series.world, { value: "0", number: "0" });
    series.no_shares = reason;
    for (const cell of [...series.countries, series.other]) cell.share = { shown: null, reason };
    series.leader = series.top3 = { countries: [], shown: null, reason };
    // What the server builds from this series is withheld with it: its indicators, its stage and the links on it.
    const risk = body.risk.chapters.find((c: any) => c.id === "cobalt");
    risk.series[series.id] = { named_share: null, over_total: null, hhi_low: null, hhi_high: null, named: null, reason };
    Object.assign(risk.stages[0], { leader: series.leader, top3: series.top3 });
    risk.most_concentrated = null;
    for (const link of body.research.metals.cobalt.chains[0].links.slice(0, 2)) {
      Object.assign(link, { shown: null, unavailable: reason });
    }
  };
  assert.equal(refusal(zero("The world total is printed as “0”, so no share can be computed")), null);
  assert.match(refusal(zero("The world total is printed as “0”, not as a number")) ?? "", /cobalt\..*no_shares/);
});

test("a world cell must say whether USGS rounded it", () => {
  const body = fixture("metals-view.json");
  assert.equal(mine(body, "cobalt").world.rounded, true);
  assert.equal(mine(body, "tin").world.rounded, false);
  assert.match(refusal((b) => { mine(b, "cobalt").world.rounded = "yes"; }) ?? "", /cobalt\..*world\.rounded/);
  assert.match(refusal((b) => { delete mine(b, "cobalt").world.rounded; }) ?? "", /world\.rounded/);
});

test("an IEA mineral's chapter and every withheld frame's words are the fixed constants", () => {
  assert.match(refusal((body) => { body.iea.minerals[4].chapter = "rare-earths-heavy"; }) ?? "",
    /^iea\.magnet-rare-earths\.chapter: /);
  assert.match(refusal((body) => { body.usgs.chapters[1].name = "Bauxite"; }, "metals-unavailable.json") ?? "",
    /^usgs\.chapters\[1\]\.name: /);
  assert.match(refusal((body) => { body.usgs.chapters[1].chapter = "BAUXITE"; }, "metals-unavailable.json") ?? "",
    /^usgs\.chapters\[1\]\.chapter: /);
  assert.match(refusal((body) => { body.iea.minerals[5].name = "Graphite"; }, "metals-unavailable.json") ?? "",
    /^iea\.minerals\[5\]\.name: /);
  assert.match(refusal((body) => { body.iea.minerals[5].chapter = "graphite"; }, "metals-unavailable.json") ?? "",
    /^iea\.minerals\[5\]\.chapter: /);
  const frames = fixture("metals-unavailable.json");
  assert.equal(frames.usgs.chapters[27].name, "Rare earths (heavy)");
  assert.equal(frames.iea.minerals[4].chapter, "rare-earths");
});

test("the reserves beside a production row: its pair, else the chapter's only 2025 reserves, else none", () => {
  const body = fixture("metals-view.json");
  const copper = chapter(body, "copper");
  const paired = reservesFor(copper, mine(body, "copper"));
  assert.deepEqual([paired?.series.id, paired?.paired], ["copper/reserves/reserves/metric-tons/2025", true]);
  const iron = chapter(body, "iron-ore");
  const only = reservesFor(iron, mine(body, "iron-ore"));
  assert.deepEqual([only?.series.detail, only?.paired], ["Reserves (million metric tons): Crude ore", false]);
  const second = { ...iron.series[1], id: "iron-ore/reserves/reserves-iron-content/metric-tons/2025",
    detail: "Reserves: Iron content" };
  assert.equal(reservesFor({ ...iron, series: [...iron.series, second] }, mine(body, "iron-ore")), null);
  assert.equal(reservesFor(chapter(body, "cobalt"), mine(body, "cobalt")), null);
});
