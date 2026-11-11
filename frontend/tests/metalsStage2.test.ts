// The metals reader's risk, uses and research checks (metalsStage2.ts, called from metalsRefusal) against replies
// captured from the server (tests/fixtures/metals-*.json): each new field is changed once per rule, and the reply must
// be refused with a message naming the place and never the value.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { metalsRefusal, UNIT_ISSUES } from "../src/metals.ts";
import { stageOf } from "../src/metalsStage2.ts";

const FIXTURES = ["metals-view.json", "metals-usgs-changed.json", "metals-iea-changed.json", "metals-unavailable.json"];
const WRITTEN_BY = "Written by the assistant from the figures on this page and retained sources; not reviewed by the "
  + "owner.";
const RESEARCH_PROBLEM = "The research notes are not in the shape this version reads";
const fixture = (name: string) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf-8"));
const refusal = (change: (body: any) => void, name = "metals-view.json") => {
  const body = fixture(name);
  change(body);
  return metalsRefusal(body);
};
/** The message names `place` and holds none of `values`. */
const refused = (message: string | null, place: RegExp, ...values: string[]) => {
  assert.match(message ?? "", place);
  for (const value of values) assert.ok(!(message ?? "").includes(value), `${message} holds ${value}`);
};
const chapter = (body: any, id: string) => body.usgs.chapters.find((c: any) => c.id === id);
const risk = (body: any, id: string) => body.risk.chapters.find((c: any) => c.id === id);
/** The indicators of a chapter's series at `at` (its index in the USGS chapter, the place the reader names). */
const indicator = (body: any, id: string, at: number) => risk(body, id).series[chapter(body, id).series[at].id];
const link = (body: any, metal: string, at: number) => body.research.metals[metal].chains[0].links[at];

test("the four captured replies pass with their risk, uses and research parts", () => {
  for (const name of FIXTURES) assert.equal(metalsRefusal(fixture(name)), null, name);
  const states = (name: string) => ["usgs", "risk", "iea", "uses", "research"].map((key) => fixture(name)[key].state);
  assert.deepEqual(states("metals-usgs-changed.json"), ["withheld", "withheld", "available", "available", "available"]);
  assert.deepEqual(states("metals-iea-changed.json"), ["available", "available", "withheld", "withheld", "available"]);
});

test("each concentration indicator is recomputed from the series cells, naming its place without the value", () => {
  const cases: [string, unknown, string][] = [["named_share", "37.5", "37.5"], ["over_total", true, "true"],
    ["hhi_low", "738", "738"], ["hhi_high", "4658", "4658"], ["named", 3, "named: 3"]];
  for (const [field, value, shown] of cases) {
    refused(refusal((body) => { indicator(body, "copper", 0)[field] = value; }),
      new RegExp(`^risk\\.copper\\.series\\[0\\]\\.${field}: `), shown);
  }
  // The reserves and the refinery series have their own indicators, at their own places.
  refused(refusal((body) => { indicator(body, "copper", 2).hhi_high = "4349"; }), /^risk\.copper\.series\[2\]\.hhi_high: /);
  // A dash counts as zero: tin names four countries, one printed "—", so three hold a share of the sum.
  assert.equal(indicator(fixture("metals-view.json"), "tin", 0).named, 3);
  refused(refusal((body) => { indicator(body, "tin", 0).named = 4; }), /^risk\.tin\.series\[0\]\.named: /);
  // Named shares over the world total are flagged.
  refused(refusal((body) => { indicator(body, "manganese", 0).over_total = false; }), /^risk\.manganese\.series\[0\]\.over_total: /);
  // A series whose order is unknown carries no figure, and its reason is the series' own.
  refused(refusal((body) => { indicator(body, "nickel", 0).hhi_low = "5000"; }), /^risk\.nickel\.series\[0\]\.hhi_low: /, "5000");
  refused(refusal((body) => { indicator(body, "nickel", 0).reason = "Unknown order"; }), /^risk\.nickel\.series\[0\]\.reason: /);
  refused(refusal((body) => { indicator(body, "gallium", 0).reason = null; }), /^risk\.gallium\.series\[0\]\.reason: /);
  // Exactly the chapter's 2025 production and reserves series carry indicators.
  refused(refusal((body) => { delete risk(body, "copper").series["copper/reserves/reserves/metric-tons/2025"]; }),
    /^risk\.copper\.series: /);
  refused(refusal((body) => { risk(body, "aluminum").series = { "aluminum/production/x/metric-tons/2025": {} }; }),
    /^risk\.aluminum\.series: /);
});

test("a stage is tagged from its detail: mine, else refinery or smelter, else other", () => {
  assert.deepEqual(["Mine production", "Mine production: Ilmenite", "Smelter production", "Refinery production, primary",
    "Primary production", "Mines", "Undermine", "Bauxite mine production"].map(stageOf),
  ["mining", "mining", "refining", "refining", "other", "other", "other", "mining"]);
});

test("an export series is no stage, before the mine test (mercury's \"Mine production: exports\")", () => {
  assert.deepEqual(["Mine production: exports", "Smelter production, Exports of refined", "Mine production: expected",
    "Reexport"].map(stageOf), ["other", "other", "mining", "other"]);
});

test("the stage ladder follows the 2025 production series: tag, order, leader copies and missing stages", () => {
  refused(refusal((b) => { risk(b, "copper").stages[0].stage = "refining"; }), /^risk\.copper\.stages\[0\]\.stage: /);
  refused(refusal((b) => { risk(b, "gallium").stages[0].stage = "refining"; }), /^risk\.gallium\.stages\[0\]\.stage: /);
  refused(refusal((b) => { const s = risk(b, "copper").stages; [s[0], s[1]] = [s[1], s[0]]; }),
    /^risk\.copper\.stages\[0\]\.series: /);
  refused(refusal((b) => { risk(b, "copper").stages[0].detail = "Mine output"; }), /^risk\.copper\.stages\[0\]\.detail: /);
  refused(refusal((b) => { risk(b, "copper").stages[1].leader.shown = "44.5"; }), /^risk\.copper\.stages\[1\]\.leader: /,
    "44.5");
  refused(refusal((b) => { risk(b, "cobalt").stages[0].top3.countries.reverse(); }), /^risk\.cobalt\.stages\[0\]\.top3: /);
  refused(refusal((b) => { risk(b, "copper").stages.pop(); }), /^risk\.copper\.stages: /);
  refused(refusal((b) => { risk(b, "copper").missing_stages = ["refining"]; }), /^risk\.copper\.missing_stages: /);
  refused(refusal((b) => { risk(b, "aluminum").missing_stages = ["mining"]; }), /^risk\.aluminum\.missing_stages: /);
});

test("leaders_differ and most_concentrated follow the stage leaders", () => {
  refused(refusal((b) => { risk(b, "copper").leaders_differ = false; }), /^risk\.copper\.leaders_differ: /);
  // Cobalt has no refining stage, so whether the leaders differ is unknown.
  refused(refusal((b) => { risk(b, "cobalt").leaders_differ = false; }), /^risk\.cobalt\.leaders_differ: /);
  refused(refusal((b) => { risk(b, "copper").most_concentrated = "copper/production/mine-production/metric-tons/2025"; }),
    /^risk\.copper\.most_concentrated: /);
  // Nickel's leader is withheld, so no stage is the most concentrated.
  refused(refusal((b) => { risk(b, "nickel").most_concentrated = "nickel/production/mine-production/metric-tons/2025"; }),
    /^risk\.nickel\.most_concentrated: /);
});

test("possible alternative sources compare the paired shown shares exactly", () => {
  assert.deepEqual(risk(fixture("metals-view.json"), "manganese").alternatives,
    [{ country: "Beta", reserves: "60.0", production: "50.0" }]);
  refused(refusal((b) => { risk(b, "manganese").alternatives[0].reserves = "60.1"; }), /^risk\.manganese\.alternatives: /,
    "60.1");
  refused(refusal((b) => { risk(b, "vanadium").alternatives = []; }), /^risk\.vanadium\.alternatives: /);
  refused(refusal((b) => { risk(b, "manganese").reserves_only = []; }), /^risk\.manganese\.reserves_only: /);
  refused(refusal((b) => { risk(b, "copper").reserves_only.push({ country: "Chile", reserves: "19.4" }); }),
    /^risk\.copper\.reserves_only: /);
  // Cobalt has no years pair, so there is nothing to compare.
  refused(refusal((b) => { risk(b, "cobalt").alternatives = []; }), /^risk\.cobalt\.alternatives: /);
});

test("each US import group's indicators are recomputed from its rows; reliance is the chapter's first 2025 row", () => {
  const cases: [string, unknown][] = [["leader", { country: "Finland", value: "30" }], ["top3", "80.1"],
    ["hhi_low", "2601"], ["hhi_high", "3001"], ["named_share", "80.1"]];
  for (const [field, value] of cases) {
    refused(refusal((b) => { risk(b, "cobalt").us.imports[0][field] = value; }),
      new RegExp(`^risk\\.cobalt\\.us\\.imports\\[0\\]\\.${field}: `), "80.1", "2601", "3001", "Finland");
  }
  refused(refusal((b) => { risk(b, "cobalt").us.imports[1].reason = "A named source is printed as “X”"; }),
    /^risk\.cobalt\.us\.imports\[1\]\.reason: /);
  refused(refusal((b) => { risk(b, "cobalt").us.imports[1].hhi_low = "2500"; }), /^risk\.cobalt\.us\.imports\[1\]\.hhi_low: /);
  refused(refusal((b) => { risk(b, "rare-earths").us.imports[0].top3 = "83.0"; }),
    /^risk\.rare-earths\.us\.imports\[0\]\.top3: /);
  refused(refusal((b) => { risk(b, "cobalt").us.imports.pop(); }), /^risk\.cobalt\.us\.imports: /);
  refused(refusal((b) => { risk(b, "rare-earths").us.reliance.value = "95"; }), /^risk\.rare-earths\.us\.reliance: /);
  refused(refusal((b) => { risk(b, "copper").us.reliance = { detail: "Net import reliance", value: "45" }; }),
    /^risk\.copper\.us\.reliance: /);
  // The headline names its commodity as printed: two 2025 rows under one detail are told apart by it alone.
  const titanium = "titanium-and-titanium-dioxide";
  assert.equal(risk(fixture("metals-view.json"), titanium).us.reliance.commodity, "Titanium sponge metal");
  refused(refusal((b) => { risk(b, titanium).us.reliance.commodity = "TiO2 pigment"; }),
    /^risk\.titanium-and-titanium-dioxide\.us\.reliance: /);
  refused(refusal((b) => { delete risk(b, titanium).us.reliance.commodity; }),
    /^risk\.titanium-and-titanium-dioxide\.us\.reliance: /);
  refused(refusal((b) => { risk(b, "copper").us.secondary[0].value = 820; }), /^risk\.copper\.us\.secondary\[0\]\.value: /);
});

test("the risk part is available exactly when the USGS part is, and withheld it holds the 45 frames only", () => {
  refused(refusal((b) => { b.risk.state = "withheld"; }), /^risk\.state: /);
  refused(refusal((b) => { b.risk.engine = "metals-risk-0.2"; }), /^risk\.engine: /);
  refused(refusal((b) => { b.risk.chapters.pop(); }), /^risk\.chapters: /);
  refused(refusal((b) => { b.risk.problem = "Another problem"; }, "metals-usgs-changed.json"), /^risk\.problem: /);
  refused(refusal((b) => { b.risk.chapters[0].series = {}; }, "metals-usgs-changed.json"), /^risk\.chapters\[0\]: /);
  refused(refusal((b) => { b.risk.chapters[1].name = "Bauxite"; }, "metals-usgs-changed.json"), /^risk\.chapters\[1\]\.name: /);
  refused(refusal((b) => { b.risk.leak = "4,657"; }, "metals-usgs-changed.json"), /^risk: /, "4,657");
});

test("IEA uses: every number plain and normalised, every share recomputed, the mapping fixed", () => {
  // entries: 0 Cadmium, 1 Copper, 2 Iridium, 3 PGMs (other than iridum), 4 Lithium, 5 Neodymium, 6 Total rare earths.
  refused(refusal((b) => { b.uses.entries[1].total["2025"] = "1,000"; }), /^uses\.entries\[1\]\.total\.2025: is not a plain/);
  refused(refusal((b) => { b.uses.entries[0].total["hd-2050"] = "5.0"; }), /^uses\.entries\[0\]\.total\.hd-2050: is not normal/);
  refused(refusal((b) => { b.uses.entries[1].technologies[0].values["cps-2030"] = "1e2"; }),
    /^uses\.entries\[1\]\.technologies\[0\]\.values\.cps-2030: /);
  refused(refusal((b) => { delete b.uses.entries[1].total["hd-2050"]; }), /^uses\.entries\[1\]\.total: /);
  refused(refusal((b) => { b.uses.entries[1].technologies[0].share_2025 = "10.1"; }),
    /^uses\.entries\[1\]\.technologies\[0\]\.share_2025: /, "10.1");
  refused(refusal((b) => { b.uses.entries[1].total["2025"] = "900"; }), /^uses\.entries\[1\]\.technologies\[0\]\.share_2025: /);
  // Neodymium's 2025 total is zero, so no share is computed.
  refused(refusal((b) => { b.uses.entries[5].technologies[0].share_2025 = "0.0"; }),
    /^uses\.entries\[5\]\.technologies\[0\]\.share_2025: /);
  refused(refusal((b) => { b.uses.entries[1].chapter = "copper-ore"; }), /^uses\.entries\[1\]\.chapter: /);
  refused(refusal((b) => { b.uses.entries[4].scope_note = null; }), /^uses\.entries\[4\]\.scope_note: /);
  refused(refusal((b) => { b.uses.entries[0].scope_note = "Cadmium content"; }), /^uses\.entries\[0\]\.scope_note: /);
  refused(refusal((b) => { b.uses.entries[0].name = "Boron"; }), /^uses\.entries\[0\]\.name: /, "Boron");
  refused(refusal((b) => { b.uses.entries.push(structuredClone(b.uses.entries[0])); }), /^uses\.entries\[7\]\.name: /);
  refused(refusal((b) => { b.uses.entries[1].technologies[0].label = 7; }), /^uses\.entries\[1\]\.technologies\[0\]\.label: /);
});

test("the uses part reads only over a verified IEA source, and withheld it holds one frame per mapped name", () => {
  const view = fixture("metals-view.json");
  refused(refusal((b) => { b.uses = view.uses; }, "metals-iea-changed.json"), /^uses\.state: /);
  refused(refusal((b) => { b.uses.engine = "metals-iea-uses-0.2"; }), /^uses\.engine: /);
  refused(refusal((b) => { b.uses.problem = "Another problem"; }, "metals-iea-changed.json"), /^uses\.problem: /);
  refused(refusal((b) => { b.uses.entries[0].total = view.uses.entries[0].total; }, "metals-iea-changed.json"),
    /^uses\.entries\[0\]: /);
  refused(refusal((b) => { b.uses.entries[2].chapter = "platinum"; }, "metals-iea-changed.json"),
    /^uses\.entries\[2\]\.chapter: /);
  refused(refusal((b) => { b.uses.entries.pop(); }, "metals-iea-changed.json"), /^uses\.entries: /);
});

test("a measured link is resolved again from the reply, naming its place without the value", () => {
  refused(refusal((b) => { link(b, "copper", 0).shown = "Chile 23.1%"; }), /^research\.copper\.chains\[0\]\.links\[0\]\.shown: /,
    "23.1", "Chile");
  refused(refusal((b) => { link(b, "cobalt", 1).shown = "5706–5839"; }), /^research\.cobalt\.chains\[0\]\.links\[1\]\.shown: /,
    "5706");
  refused(refusal((b) => { link(b, "lithium", 3).shown = "75.0% of 2025 energy-technology demand (150 kt)"; }),
    /^research\.lithium\.chains\[0\]\.links\[3\]\.shown: /, "150");
  refused(refusal((b) => { link(b, "lithium", 3).shown = "75.0% of 2025 energy-technology demand (150 kt of 201 kt)"; }),
    /^research\.lithium\.chains\[0\]\.links\[3\]\.shown: /, "201");
  refused(refusal((b) => { link(b, "nickel", 1).unavailable = "Not shown"; }),
    /^research\.nickel\.chains\[0\]\.links\[1\]\.unavailable: /);
  refused(refusal((b) => { link(b, "copper", 0).ref = { stage: "refining", figure: "leader" }; }),
    /^research\.copper\.chains\[0\]\.links\[0\]\.shown: /);
  // Over a withheld part, a link is unavailable with the part's problem.
  refused(refusal((b) => { Object.assign(link(b, "copper", 0), { shown: "Chile 23.0%", unavailable: null }); },
    "metals-usgs-changed.json"), /^research\.copper\.chains\[0\]\.links\[0\]\.shown: /);
  refused(refusal((b) => { link(b, "copper", 3).unavailable = "The IEA part is withheld"; }, "metals-iea-changed.json"),
    /^research\.copper\.chains\[0\]\.links\[3\]\.unavailable: /);
  // A ref is one of the three shapes, with the fixed words.
  refused(refusal((b) => { link(b, "copper", 0).ref = { stage: "smelting", figure: "leader" }; }),
    /^research\.copper\.chains\[0\]\.links\[0\]\.ref\.stage: /);
  refused(refusal((b) => { link(b, "copper", 0).ref = { stage: "mining", figure: "years" }; }),
    /^research\.copper\.chains\[0\]\.links\[0\]\.ref\.figure: /);
  refused(refusal((b) => { link(b, "copper", 3).ref.iea = "Cobalt"; }), /^research\.copper\.chains\[0\]\.links\[3\]\.ref\.iea: /);
  refused(refusal((b) => { link(b, "cobalt", 3).ref = { reliance: "2024" }; }),
    /^research\.cobalt\.chains\[0\]\.links\[3\]\.ref\.reliance: /);
  refused(refusal((b) => { link(b, "cobalt", 3).ref = { reliance: "2025", year: "2025" }; }),
    /^research\.cobalt\.chains\[0\]\.links\[3\]\.ref: /);
});

/** The reply with only `metal` in the research, its one chain holding the measured link given. */
const alone = (body: any, metal: string, ref: object, shown: string | null, unavailable: string | null) => {
  const chain = structuredClone(body.research.metals.cobalt.chains[0]);
  chain.links = [{ text: "A figure on this page", kind: "measured", ref, shown, unavailable }];
  body.research.metals = { [metal]: { thesis: null, uses: [], substitution: [], recycling: [], events: [], chains: [chain] } };
};

test("reserves, years, HHI, top three and reliance read as the server writes them", () => {
  const cases: [string, object, string | null, string | null][] = [
    ["copper", { stage: "reserves", figure: "years" }, "43 years", null],
    ["manganese", { stage: "reserves", figure: "years" }, "1 year", null],
    ["silver", { stage: "reserves", figure: "years" }, "less than 1 year", null],
    ["vanadium", { stage: "reserves", figure: "years" }, null,
      `Reserves: ${UNIT_ISSUES["vanadium/reserves/reserves/metric-tons/2025"]}`],
    ["copper", { stage: "reserves", figure: "leader" }, "Chile 19.4%", null],
    ["manganese", { stage: "reserves", figure: "top3" }, "85.0% (Beta, Alpha, Gamma)", null],
    // Iron ore's only 2025 reserves series is not paired with its mine production.
    ["iron-ore", { stage: "reserves", figure: "leader" }, "Australia 30.5%", null],
    ["iron-ore", { stage: "reserves", figure: "years" }, null, "No years figure for this pair"],
    ["cobalt", { stage: "reserves", figure: "hhi" }, null, "No matching 2025 reserves series"],
    ["manganese", { stage: "mining", figure: "hhi" }, "6,100", null],
    ["copper", { stage: "refining", figure: "hhi" }, "2,030–4,348", null],
    ["copper", { stage: "reserves", figure: "hhi" }, "526–5,200", null],
    ["cobalt", { stage: "mining", figure: "top3" }, "88.5% (Congo (Kinshasa), Indonesia, United States)", null],
    ["copper", { stage: "mining", figure: "top3" }, null, "Fewer than three countries are named"],
    ["rare-earths", { reliance: "2025" }, ">95", null],
  ];
  for (const [metal, ref, shown, unavailable] of cases) {
    const label = `${metal} ${JSON.stringify(ref)}`;
    assert.equal(refusal((b) => alone(b, metal, ref, shown, unavailable)), null, label);
    refused(refusal((b) => alone(b, metal, ref, shown === null ? "0" : `${shown} `, unavailable)),
      new RegExp(`^research\\.${metal}\\.chains\\[0\\]\\.links\\[0\\]\\.shown: `), label);
  }
  // A reliance printed as a plain number gains "%"; the first 2025 row is the one shown.
  const plain = (b: any) => {
    chapter(b, "rare-earths").reliance[1].value = "57";
    risk(b, "rare-earths").us.reliance.value = "57";
  };
  assert.equal(refusal((b) => { plain(b); alone(b, "rare-earths", { reliance: "2025" }, "57%", null); }), null);
  refused(refusal((b) => { plain(b); alone(b, "rare-earths", { reliance: "2025" }, "57", null); }),
    /^research\.rare-earths\.chains\[0\]\.links\[0\]\.shown: /);
});

test("an IEA link over an entry with no technology split says so; one whose split lacks the use says that", () => {
  const cadmium = { iea: "Cadmium", technology: "Wind" }, copper = { iea: "Copper", technology: "Hydrogen" };
  assert.equal(refusal((b) => alone(b, "cadmium", cadmium, null, "The IEA's table gives no technology split for Cadmium")),
    null);
  refused(refusal((b) => alone(b, "cadmium", cadmium, null, "The IEA lists no Wind use for Cadmium in this table")),
    /^research\.cadmium\.chains\[0\]\.links\[0\]\.unavailable: /);
  assert.equal(refusal((b) => alone(b, "copper", copper, null, "The IEA lists no Hydrogen use for Copper in this table")),
    null);
});

/** Every citation of passage `id` made verified, as the server shows a passage found where cited. */
const verify = (body: any, id: string) => {
  const visit = (value: any) => {
    if (Array.isArray(value)) value.forEach(visit);
    else if (value !== null && typeof value === "object") {
      if (value.evidence?.id === id) {
        value.evidence = { id, source: "usgs-2026", title: "Mineral Commodity Summaries 2026: Copper",
          publisher: "U.S. Geological Survey", edition: "2026", edition_date: "2026-02-01",
          quote: "Copper mine production fell in 2025.", where: "page 2", state: "verified", problem: null };
        if (value.kind === "stated") value.unavailable = null;
      }
      Object.values(value).forEach(visit);
    }
  };
  visit(body.research.metals);
};

test("a stated link and each cited passage carry the passage's checked fields and state", () => {
  assert.equal(refusal((b) => verify(b, "usgs26-mine-events")), null);
  const verified = (change: (b: any) => void) => refusal((b) => { verify(b, "usgs26-mine-events"); change(b); });
  refused(verified((b) => { link(b, "copper", 2).evidence.quote = null; }),
    /^research\.copper\.chains\[0\]\.links\[2\]\.evidence\.quote: /);
  refused(verified((b) => { link(b, "copper", 2).evidence.problem = "Not found"; }),
    /^research\.copper\.chains\[0\]\.links\[2\]\.evidence\.problem: /);
  refused(verified((b) => { link(b, "copper", 2).unavailable = "Not found"; }),
    /^research\.copper\.chains\[0\]\.links\[2\]\.unavailable: /);
  // The same passage shows the same fields wherever it is cited.
  refused(verified((b) => { link(b, "copper", 2).evidence.where = "page 3"; }),
    /^research\.copper\.chains\[0\]\.links\[2\]\.evidence: /);
  // A passage that is not verified withholds its quote and gives its problem to the link.
  refused(refusal((b) => { link(b, "copper", 2).evidence.quote = "Copper mine production fell."; }),
    /^research\.copper\.chains\[0\]\.links\[2\]\.evidence\.quote: /, "Copper mine");
  refused(refusal((b) => { link(b, "copper", 2).evidence.state = "lost"; }),
    /^research\.copper\.chains\[0\]\.links\[2\]\.evidence\.state: /);
  refused(refusal((b) => { link(b, "copper", 2).evidence.state = "verified"; }),
    /^research\.copper\.chains\[0\]\.links\[2\]\.evidence\.(source|quote): /);
  refused(refusal((b) => { link(b, "copper", 2).evidence.state = "missing"; }),
    /^research\.copper\.chains\[0\]\.links\[2\]\.evidence\.source: /);
  refused(refusal((b) => { link(b, "copper", 2).unavailable = null; }),
    /^research\.copper\.chains\[0\]\.links\[2\]\.unavailable: /);
  refused(refusal((b) => { link(b, "copper", 2).evidence.id = "usgs26-end-uses"; }),
    /^research\.copper\.chains\[0\]\.links\[2\]\.evidence\.id: /);
  refused(refusal((b) => { link(b, "copper", 2).passage = "nickel:usgs26-mine-events"; }),
    /^research\.copper\.chains\[0\]\.links\[2\]\.passage: /);
  refused(refusal((b) => { b.research.metals.copper.uses[0].evidence.problem = ""; }),
    /^research\.copper\.uses\[0\]\.evidence\.problem: /);
  refused(refusal((b) => { b.research.metals.copper.events[0].evidence.quote = "A strike."; }),
    /^research\.copper\.events\[0\]\.evidence\.quote: /, "A strike.");
  refused(refusal((b) => { const s = b.research.metals.copper.substitution; s[1] = structuredClone(s[0]); }),
    /^research\.copper\.substitution\[1\]: /);
});

test("an event carries the date its quote gives: text with a year, and inside the quote once it is verified", () => {
  const event = (b: any) => b.research.metals.copper.events[0];
  assert.equal(event(fixture("metals-view.json")).when, "2025");
  // Unverified in the fixture: the date is checked for its shape only.
  refused(refusal((b) => { delete event(b).when; }), /^research\.copper\.events\[0\]: /);
  refused(refusal((b) => { event(b).when = "September"; }), /^research\.copper\.events\[0\]\.when: /, "September");
  refused(refusal((b) => { event(b).when = 2025; }), /^research\.copper\.events\[0\]\.when: /);
  refused(refusal((b) => { event(b).when = " 2025"; }), /^research\.copper\.events\[0\]\.when: /);
  refused(refusal((b) => { event(b).when = `In ${"x".repeat(40)} 2025`; }), /^research\.copper\.events\[0\]\.when: /);
  assert.equal(refusal((b) => { event(b).when = "March 2024"; }), null);
  // Verified: the quote must hold the date exactly.
  assert.equal(refusal((b) => verify(b, "usgs26-mine-events")), null);
  refused(refusal((b) => { verify(b, "usgs26-mine-events"); event(b).when = "2024"; }),
    /^research\.copper\.events\[0\]\.when: /, "2024");
});

test("a cited passage names its source (title, publisher, edition, edition date) in every state but unavailable", () => {
  const id = "usgs26-mine-events";
  /** Every citation of the passage verified, then changed by `change` (its stated links following its problem). */
  const restated = (change: (evidence: any) => void) => refusal((b) => {
    verify(b, id);
    const visit = (value: any) => {
      if (Array.isArray(value)) value.forEach(visit);
      else if (value !== null && typeof value === "object") {
        if (value.evidence?.id === id) {
          change(value.evidence);
          if (value.kind === "stated") value.unavailable = value.evidence.state === "verified" ? null : value.evidence.problem;
        }
        Object.values(value).forEach(visit);
      }
    };
    visit(b.research.metals);
  });
  const changed = (evidence: any) => Object.assign(evidence, { state: "changed", quote: null,
    problem: "usgs-2026: The retained file differs from its acquisition record" });
  assert.equal(restated(changed), null);  // Not verified on this read: its quote withheld, its source still named.
  for (const key of ["title", "publisher", "edition", "edition_date"]) {
    refused(restated((evidence) => { evidence[key] = null; }), new RegExp(`\\.evidence\\.${key}: must be text`));
    refused(restated((evidence) => { changed(evidence); evidence[key] = ""; }), new RegExp(`\\.evidence\\.${key}: `));
  }
  refused(restated((evidence) => { evidence.edition_date = "February 2026"; }), /\.evidence\.edition_date: /);
  refused(restated((evidence) => { delete evidence.publisher; }), /\.evidence: must hold exactly/);
  // The thesis cannot be read (the synthetic reply): no source is known, so every source field is empty.
  assert.equal(fixture("metals-view.json").research.metals.copper.uses[0].evidence.state, "unavailable");
  refused(refusal((b) => { b.research.metals.copper.uses[0].evidence.title = "Mineral Commodity Summaries 2026: Copper"; }),
    /^research\.copper\.uses\[0\]\.evidence\.title: /);
});

test("a hypothesis link carries only its text and kind; chains and metals keep their shape", () => {
  refused(refusal((b) => { link(b, "copper", 6).shown = "Chile 23.0%"; }), /^research\.copper\.chains\[0\]\.links\[6\]: /,
    "Chile");
  refused(refusal((b) => { link(b, "copper", 6).kind = "assumed"; }), /^research\.copper\.chains\[0\]\.links\[6\]\.kind: /);
  refused(refusal((b) => { b.research.metals.copper.chains[0].gains_losses[0].direction = "may win"; }),
    /^research\.copper\.chains\[0\]\.gains_losses\[0\]\.direction: /);
  refused(refusal((b) => { b.research.metals.copper.chains[0].value = "23.0"; }), /^research\.copper\.chains\[0\]: /);
  refused(refusal((b) => { b.research.metals.cobalt.chains[0].id = b.research.metals.copper.chains[0].id; }),
    /^research\.cobalt\.chains\[0\]\.id: /);
  refused(refusal((b) => { b.research.metals.copper.thesis = "nickel"; }), /^research\.copper\.thesis: /);
  refused(refusal((b) => { b.research.metals["copper-ore"] = b.research.metals.copper; }), /^research\.metals: /);
});

test("the research part: the fixed written-by sentence, and withheld it holds no notes", () => {
  refused(refusal((b) => { b.research.written_by = "Written by the owner."; }), /^research\.written_by: /);
  refused(refusal((b) => { b.research.engine = "metals-research-0.1"; }), /^research\.engine: /);
  const withheld = { engine: "metals-research-0.3", state: "withheld", problem: RESEARCH_PROBLEM, written_by: WRITTEN_BY,
    metals: {} };
  assert.equal(refusal((b) => { b.research = structuredClone(withheld); }), null);
  refused(refusal((b) => { b.research = { ...structuredClone(withheld), metals: { copper: b.research.metals.copper } }; }),
    /^research\.metals: /);
  refused(refusal((b) => { b.research = { ...structuredClone(withheld), problem: "Another problem" }; }), /^research\.problem: /);
  refused(refusal((b) => { b.research = { ...structuredClone(withheld), written_by: "Written by the owner." }; }),
    /^research\.written_by: /);
  refused(refusal((b) => { b.research.problem = RESEARCH_PROBLEM; }), /^research\.problem: /);
});

/** The first copper event made an `fcx:` citation of a verified 10-Q passage dated "November 2026". The register's
 * own citation of that passage (unverified in the fixture) is dropped, so the passage is cited once. */
const fcxEvent = (body: any) => {
  const copper = body.research.metals.copper;
  copper.events = copper.events.filter((item: any, at: number) => at === 0 || item.passage !== "fcx:q3-p-bagdad-approval");
  const event = copper.events[0];
  event.passage = "fcx:q3-p-bagdad-approval";
  event.when = "November 2026";
  event.evidence = { id: "q3-p-bagdad-approval", source: "10q-2026q3", title: "Quarterly Report", publisher: "Freeport",
    edition: "10-Q", edition_date: "2026-11-06", quote: "In November 2026, our Board approved the program.",
    where: "page 23", state: "verified", problem: null };
  return event;
};

test("an event may cite an fcx passage, checked as a copper one is", () => {
  assert.equal(refusal((b) => { fcxEvent(b); }), null);
  refused(refusal((b) => { fcxEvent(b).when = "March 2026"; }), /^research\.copper\.events\[0\]\.when: /);
  refused(refusal((b) => { fcxEvent(b).passage = "nickel:q3-p-bagdad-approval"; }),
    /^research\.copper\.events\[0\]\.passage: /);
  refused(refusal((b) => { fcxEvent(b).evidence.id = "other"; }), /^research\.copper\.events\[0\]\.evidence\.id: /);
  // Unavailable carries the FCX reason, not the thesis's.
  const unavailable = (problem: string) => refusal((b) => {
    const event = fcxEvent(b);
    event.evidence = { id: event.evidence.id, source: null, title: null, publisher: null, edition: null,
      edition_date: null, quote: null, where: null, state: "unavailable", problem };
  });
  assert.equal(unavailable("The FCX research cannot be read on this machine"), null);
  refused(unavailable("The copper thesis cannot be read, so its passages are not shown"),
    /^research\.copper\.events\[0\]\.evidence\.problem: /);
});

test("a stated link may not cite an fcx passage", () => {
  refused(refusal((b) => { link(b, "copper", 2).passage = "fcx:q3-p-bagdad-approval"; }),
    /^research\.copper\.chains\[0\]\.links\[2\]\.passage: /);
});

test("the same passage id under copper: and fcx: are two passages, not one that differs", () => {
  assert.equal(refusal((b) => {
    const event = fcxEvent(b);
    const id = event.evidence.id;
    const copper = b.research.metals.copper.uses[0];
    copper.passage = "copper:" + id;
    copper.evidence = { ...copper.evidence, id };
  }), null);
});
