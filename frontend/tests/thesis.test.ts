// Committed theses, against replies the backend serves (captured by tests/test_thesis_api.py into
// fixtures/thesis-*.json): the SYNTHETIC copper thesis with every retained source present, the same with one changed
// source and one passage no longer found where cited (mover-2), with no retained sources at all, version 1, a draft
// version 2, and the catalog. Replies are read fail-closed, and every refusal names the place and rule that refused
// it, so each test below proves the rule it is about rather than some other rule tripping on the same change.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { matchRoute } from "../src/routes.ts";
import {
  THESIS_VIEW_VERSION, dayText, elementsOf, fetchThesis, figureText, isThesisView, periodText, thesisHref,
  thesisRefusal, transcriptionText, type Figure, type ThesisView,
} from "../src/thesis.ts";
import { fetchThesisCatalog, isThesisCatalog, type ThesisCatalog } from "../src/thesisCatalog.ts";
import { comparisonText, editionText, readAsText, withinOneEdition } from "../src/thesisComparison.ts";
import { difference, displayedPattern, displayedValue, halfEven, plainDecimal, printed } from "../src/thesisNumbers.ts";

const fixture = <T>(name: string): T => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));
const available = fixture<ThesisView>("thesis-available.json");
const revalidation = fixture<ThesisView>("thesis-revalidation.json");
const unavailable = fixture<ThesisView>("thesis-unavailable.json");
const first = fixture<ThesisView>("thesis-version-1.json");
const draft = fixture<ThesisView>("thesis-draft.json");
const catalog = fixture<ThesisCatalog>("thesis-catalog.json");
const SYNTHETIC = "synthetic-copper";
const copy = <T>(value: T): T => structuredClone(value);
type Change = (view: ThesisView) => void;

/** The refusal of a changed copy of a served reply, or null when the copy is read. */
function refusalOf(base: ThesisView, change: Change, version: number | null = null): string | null {
  const changed = copy(base);
  change(changed);
  return thesisRefusal(changed, SYNTHETIC, version);
}

/** The changed copy is refused by the rule at `place` (the refusal reads "<place>: <rule>"). */
function refusedAt(place: string, base: ThesisView, change: Change, version: number | null = null): void {
  const refusal = refusalOf(base, change, version);
  assert.ok(refusal?.startsWith(`${place}: `), `expected a refusal at ${place}, got ${refusal}`);
}

/** Applies one change to every copy of a figure in the reply, so that the figure still reads the same everywhere. */
function everywhere(node: unknown, id: string, change: (figure: Figure) => void): number {
  if (Array.isArray(node)) return node.reduce((sum: number, item) => sum + everywhere(item, id, change), 0);
  if (typeof node !== "object" || node === null) return 0;
  const record = node as Record<string, unknown>;
  if (record.id === id && "as_shown" in record) {
    change(record as unknown as Figure);
    return 1;
  }
  return Object.values(record).reduce((sum: number, value) => sum + everywhere(value, id, change), 0);
}

const reason = (view: ThesisView, id: string) => view.reasons.find((item) => item.id === id)!;
const risk = (view: ThesisView, id: string) => view.risks.find((item) => item.id === id)!;
const table = (view: ThesisView, id: string) => view.balance.tables.find((item) => item.id === id)!;
const clean = (view: ThesisView) => view.reasons[0];  // clean-tech-demand: strengthening, 7.4 %, material 5 %.
const STEPS = "balance.tables[balance-steps]";
const CLEAN = "reasons[clean-tech-demand]";

async function withFetch<T>(status: number, body: unknown, run: () => Promise<T>, seen: string[] = []): Promise<T> {
  const original = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    seen.push(String(input));
    return new Response(JSON.stringify(body), { status });
  }) as typeof fetch;
  try {
    return await run();
  } finally {
    globalThis.fetch = original;
  }
}

test("the served replies are read and their states reconcile", () => {
  assert.equal(available.view_version, THESIS_VIEW_VERSION);
  for (const [name, reply, version] of [["available", available, null], ["revalidation", revalidation, null],
    ["unavailable", unavailable, null], ["draft", draft, null], ["draft, by number", draft, 2],
    ["version 1", first, 1], ["available, by number", available, 2]] as const) {
    assert.equal(thesisRefusal(reply, SYNTHETIC, version), null, name);
    assert.equal(isThesisView(reply, SYNTHETIC, version), true, name);
  }
  assert.deepEqual(available.counts.elements, { available: 18, needs_revalidation: 0, unavailable: 0 });
  assert.deepEqual(revalidation.counts.elements, { available: 8, needs_revalidation: 10, unavailable: 0 });
  assert.deepEqual(unavailable.counts.elements, { available: 0, needs_revalidation: 0, unavailable: 18 });
  const mover = revalidation.exposure.movers[1];  // Its source verifies, but its passage is not found where cited.
  assert.deepEqual([mover.state, mover.not_found, mover.through],
    ["needs_revalidation", ["maker-deliveries-2025"], null]);
  assert.equal(revalidation.sources.find((item) => item.id === mover.sources[0])!.state, "verified");
  for (const reply of [available, revalidation, unavailable]) {
    const states = elementsOf(reply).map((item) => item.state);
    assert.deepEqual(states.length, 18);
    for (const state of ["available", "needs_revalidation", "unavailable"] as const) {
      assert.equal(states.filter((item) => item === state).length, reply.counts.elements[state]);
    }
  }
  assert.equal(isThesisView(available, "copper", null), false);  // A reply for another thesis is not this one.
  assert.ok(thesisRefusal(available, "copper", null)!.startsWith("id: "));
  refusedAt("version", first, () => {}, null);  // Version 1 is not the latest.
  refusedAt("version", available, () => {}, 1);
});

test("a withheld element that shows content is refused", () => {
  refusedAt(`${CLEAN}.statement`, unavailable, (view) => { clean(view).statement = available.reasons[0].statement; });
  refusedAt("exposure.movers[mover-2].through", revalidation, (view) => {
    view.exposure.movers[1].through = "Synthetic: shown anyway.";
  });
  refusedAt(`${STEPS}.rows`, revalidation, (view) => {
    table(view, "balance-steps").rows = available.balance.tables[0].rows;
  });
  // A withheld title or series shows no digits (they may state the withheld figures); a shown one is text.
  refusedAt(`${STEPS}.title`, unavailable, (view) => {
    table(view, "balance-steps").title = "Synthetic balance to 2035";
  });
  refusedAt("price_record.series", unavailable, (view) => { view.price_record.series = "Synthetic 2026 price"; });
  refusedAt(`${STEPS}.title`, available, (view) => { table(view, "balance-steps").title = null; });
  assert.equal(refusalOf(unavailable, (view) => { table(view, "balance-steps").title = null; }), null);
  refusedAt(`${CLEAN}.title`, unavailable, (view) => { clean(view).title = "Synthetic \u0663 units"; });  // Not ASCII.
});

test("an element's state follows from its sources and the items not found where cited", () => {
  refusedAt("exposure.movers[mover-2].state", revalidation, (view) => {
    view.exposure.movers[1].state = "available";
    view.counts.elements.available += 1;
    view.counts.elements.needs_revalidation -= 1;
  });
  refusedAt("view.state", unavailable, (view) => {
    view.view.state = "needs_revalidation";
    view.counts.elements.needs_revalidation += 1;
    view.counts.elements.unavailable -= 1;
  });
  refusedAt("view.state", available, (view) => {  // A changed source: the view is not available any more.
    view.sources[2].state = "changed";
    view.counts.sources = { verified: 8, changed: 1, missing: 0 };
  });
  refusedAt("view.not_found", revalidation, (view) => { view.view.not_found = ["iea26-demand-2030"]; });  // Not read.
  refusedAt(`${CLEAN}.not_found`, available, (view) => { clean(view).not_found = ["usgs26-mine-2024"]; });
  refusedAt("view.sources", available, (view) => { view.view.sources = ["iea-2025", "iea-2026"]; });
  refusedAt(`${CLEAN}.items`, available, (view) => { clean(view).items.reverse(); });
  refusedAt("exposure.movers[mover-2].problems", revalidation, (view) => {
    view.exposure.movers[1].problems = ["maker-purchases-2025: not found where cited (paragraph 5)"];
  });
  refusedAt("view.problems", revalidation, (view) => { view.view.problems = ["iea-2026: Synthetic other detail."]; });
  refusedAt("view.problems", revalidation, (view) => { view.view.problems = []; });
  refusedAt(`${CLEAN}.problems`, available, (view) => { clean(view).problems = ["Synthetic."]; });
});

test("a status that disagrees with its change is refused", () => {
  refusedAt(`${CLEAN}.status`, available, (view) => { clean(view).status = "weakening"; });
  refusedAt("reasons[mine-supply-slow].status", available, (view) => {
    reason(view, "mine-supply-slow").status = "strengthening";
  });
  refusedAt("risks[primary-supply-projections].status", available, (view) => {
    risk(view, "primary-supply-projections").status = "materialising";
  });
  refusedAt("risks[construction-slowdown].status", available, (view) => {
    risk(view, "construction-slowdown").status = "unchanged";  // No measure: not tracked.
  });
  refusedAt(`${CLEAN}.change_pct`, available, (view) => { clean(view).change_pct = "7.5"; });
  refusedAt(`${CLEAN}.moved_by`, available, (view) => { clean(view).moved_by!.edition = "2025"; });
  // Exact values decide, not the rounded display: 4.96 % against a material 5 % is unchanged although it shows "5.0".
  const nearly: Change = (view) => {
    const copies = everywhere(view, "iea26-clean-2030", (figure) => {
      Object.assign(figure, { value: "9866.24", as_shown: "9,866.24" });
    });
    assert.ok(copies > 1);
    clean(view).change_pct = "5.0";
  };
  assert.equal(refusalOf(available, (view) => { nearly(view); clean(view).status = "unchanged"; }), null);
  refusedAt(`${CLEAN}.status`, available, (view) => { nearly(view); });  // Still "strengthening": refused.
  // A change of exactly the material size is a change.
  const exactly: Change = (view) => {
    everywhere(view, "iea26-clean-2030", (figure) => { figure.value = "9870"; figure.as_shown = "9,870"; });
    clean(view).change_pct = "5.0";
  };
  assert.equal(refusalOf(available, exactly), null);
  refusedAt(`${CLEAN}.status`, available, (view) => { exactly(view); clean(view).status = "unchanged"; });
  // The shown change rounds half-even, as the server does: (2,149 - 2,000) / 2,000 is exactly 7.45 % and shows "7.4".
  const half: Change = (view) => {
    everywhere(view, "iea26-clean-2030", (figure) => { figure.value = "2149"; figure.as_shown = "2,149"; });
    everywhere(view, "iea25-clean-2030", (figure) => { figure.value = "2000"; figure.as_shown = "2,000"; });
  };
  assert.equal(refusalOf(available, (view) => { half(view); clean(view).change_pct = "7.4"; }), null);
  refusedAt(`${CLEAN}.change_pct`, available, (view) => { half(view); clean(view).change_pct = "7.5"; });
});

test("a measure compares a later year within one edition, or a later edition with an earlier one (ruling R12)", () => {
  const WITHIN = "reasons[total-demand-rising]";
  const within = (view: ThesisView) => reason(view, "total-demand-rising").measure!;
  const m = within(available);  // Read with the rest of the reply in the first test.
  assert.deepEqual([m.latest.source, m.previous.source, m.latest.year, m.previous.year, m.compare],
    ["iea-2026", "iea-2026", "2035", "2030", "period"]);
  // Within one edition only a later year is compared: never one year revised, an earlier year or the same year.
  refusedAt(`${WITHIN}.measure.compare`, available, (view) => { within(view).compare = "revision"; });
  refusedAt(`${WITHIN}.measure.compare`, available, (view) => {
    const measure = within(view);
    [measure.latest, measure.previous] = [measure.previous, measure.latest];
  });
  refusedAt(`${WITHIN}.measure.compare`, available, (view) => {
    within(view).previous = { ...within(view).latest, id: "synthetic-same-year" };
  });
  refusedAt(`${WITHIN}.measure`, available, (view) => { within(view).previous = within(view).latest; });
  // Across editions every earlier rule holds: a later edition, one year revised or a later year, one measure.
  refusedAt(`${CLEAN}.measure.compare`, available, (view) => { clean(view).measure!.compare = "period"; });
  refusedAt("risks[mine-output-rising].measure.compare", available, (view) => {
    risk(view, "mine-output-rising").measure!.compare = "revision";
  });
  refusedAt(`${CLEAN}.measure`, available, (view) => {
    view.sources.find((item) => item.id === "iea-2025")!.edition_date = "2026-08-01";
  });
  // Either way the two figures share measure, unit, basis and scenario: each one differing is refused by that rule.
  const differing = { measure: "Synthetic other measure", unit: "t", basis: "Synthetic refined",
    scenario: "Synthetic APS" };
  for (const [key, value] of Object.entries(differing)) {
    assert.equal(refusalOf(available, (view) => {
      everywhere(view, "iea25-clean-2030", (figure) => { Object.assign(figure, { [key]: value }); });
    }), `${CLEAN}.measure: the latest and previous figures differ in ${key}`, key);
  }
  // A year is four ASCII digits, as the server reads it: another script's digits are refused where first shown.
  refusedAt(`${CLEAN}.statement.figures[1].year`, available, (view) => {
    everywhere(view, "iea25-clean-2030", (figure) => { figure.year = "٢٠٣٠"; });
  });
});

test("a condition's status follows from its figure and threshold", () => {
  const PLACE = "conditions[supply-above]";
  refusedAt(`${PLACE}.status`, available, (view) => { view.conditions[0].status = "happened"; });
  refusedAt(`${PLACE}.threshold`, available, (view) => { view.conditions[0].threshold = "29,600"; });
  refusedAt(`${PLACE}.threshold_value`, available, (view) => { view.conditions[0].threshold_value = "29,500"; });
  const equal: Change = (view) => {
    Object.assign(view.conditions[0], { threshold_value: "28700", threshold: "28,700" });
  };
  assert.equal(refusalOf(available, equal), null);  // A figure equal to the threshold is not past it.
  refusedAt(`${PLACE}.status`, available, (view) => { equal(view); view.conditions[0].status = "happened"; });
  refusedAt(`${PLACE}.status`, available, (view) => { view.conditions[0].comparator = "below"; });
  assert.equal(refusalOf(available, (view) => {
    view.conditions[0].comparator = "below";
    view.conditions[0].status = "happened";
  }), null);
  // A withheld condition's threshold is withheld with it (final review M4): null, as the server serves it, and refused
  // when shown; an available condition's threshold is still read and checked.
  assert.deepEqual([unavailable.conditions[0].threshold_value, revalidation.conditions[0].threshold_value],
    [null, null]);
  refusedAt(`${PLACE}.threshold_value`, unavailable, (view) => { view.conditions[0].threshold_value = "29500"; });
  refusedAt(`${PLACE}.threshold_value`, available, (view) => { view.conditions[0].threshold_value = null; });
});

test("a gap label that disagrees with its sign is refused", () => {
  const steps = (view: ThesisView) => table(view, "balance-steps").rows!;
  refusedAt(`${STEPS}.rows[0].label`, available, (view) => { steps(view)[0].label = "surplus"; });
  refusedAt(`${STEPS}.rows[0].gap`, available, (view) => { steps(view)[0].gap = "-400"; });
  refusedAt(`${STEPS}.rows[0].gap`, available, (view) => { steps(view)[0].gap = "-500.0"; });
  refusedAt(`${STEPS}.rows[0].weeks`, available, (view) => { steps(view)[0].weeks = "1.1"; });
  const SIDE = "balance.tables[balance-side-by-side]";
  refusedAt(`${SIDE}.rows[0].weeks`, available, (view) => {
    table(view, "balance-side-by-side").rows![0].weeks = "1.0";
  });
  refusedAt(`${STEPS}.why_not`, available, (view) => { table(view, "balance-steps").why_not = "Synthetic."; });
  refusedAt(`${STEPS}.rows[1].year`, available, (view) => { steps(view).reverse(); });
  refusedAt(`${STEPS}.rows[0]`, available, (view) => {  // A row's figures are of its year.
    everywhere(view, "iea26-other-2025", (figure) => { figure.year = "2026"; });
  });
  refusedAt(STEPS, available, (view) => {  // A computed gap draws every figure from one source, basis, scenario, unit.
    assert.ok(everywhere(view, "iea26-other-2025", (figure) => { figure.unit = "t"; }) > 0);
  });
  // A balanced row: the gap is zero and the label says so.
  assert.equal(refusalOf(available, (view) => {
    everywhere(view, "iea26-supply-2025", (figure) => { figure.value = "26500"; figure.as_shown = "26,500"; });
    Object.assign(steps(view)[0], { gap: "0", label: "balanced", weeks: "0.0" });
  }), null);
});

test("weeks of demand are the exact half-even value of |gap| x 52 / demand", () => {
  const row = (supply: string, demand: string, gap: string, weeks: string): Change => (view) => {
    everywhere(view, "iea26-supply-2025", (figure) => { Object.assign(figure, { value: supply, as_shown: supply }); });
    everywhere(view, "iea26-demand-2025", (figure) => { Object.assign(figure, { value: demand, as_shown: demand }); });
    Object.assign(table(view, "balance-steps").rows![0], { gap, label: "deficit", weeks });
  };
  // 350 x 52 / 28,000 is exactly 0.65: only the producer's half-even 0.6 is read.
  assert.equal(refusalOf(available, row("27650", "28000", "-350", "0.6")), null);
  refusedAt(`${STEPS}.rows[0].weeks`, available, row("27650", "28000", "-350", "0.7"));
  // 21 x 52 / 208 is exactly 5.25: 5.2, never the 5.3 that dividing first produced (ruling R10).
  assert.equal(refusalOf(available, row("187", "208", "-21", "5.2")), null);
  refusedAt(`${STEPS}.rows[0].weeks`, available, row("187", "208", "-21", "5.3"));
});

test("exact decimals parse and round as the server does", () => {
  assert.deepEqual(plainDecimal("-1.50"), { n: -150n, s: 2 });
  for (const text of ["1,5", "1.", ".5", "1e3", "", "+1", 15]) assert.equal(plainDecimal(text), null, String(text));
  const NBSP = String.fromCharCode(0xa0), NARROW = String.fromCharCode(0x202f), THIN = String.fromCharCode(0x2009);
  for (const [text, n, s] of [["23,000", 23000n, 0], ["23 000", 23000n, 0], [`23${NBSP}000`, 23000n, 0],
    [`23${NARROW}000`, 23000n, 0], [`23${THIN}000`, 23000n, 0], ["1,234.5", 12345n, 1], ["-400", -400n, 0],
    ["12%", 12n, 0], ["$9,500", 9500n, 0]] as const) {
    assert.deepEqual(printed(text), { n, s }, text);
  }
  for (const text of ["23 million", "1.2e3", "23,00", `23,000${NBSP}000`]) assert.equal(printed(text), null, text);
  assert.deepEqual(difference({ n: 28700n, s: 0 }, { n: 295000n, s: 1 }), { n: -8000n, s: 1 });
  assert.equal(halfEven(21n * 52n, 208n, 1), 52n);  // 5.25 -> 5.2
  assert.equal(halfEven(107n * 52n, 1040n, 1), 54n);  // 5.35 -> 5.4
  assert.equal(halfEven(-745n, 100n, 1), -74n);  // -7.45 -> -7.4
  assert.equal(halfEven(2n, 3n, 1), 7n);  // 0.666... -> 0.7
  assert.equal(displayedPattern(1).test("-1,234.5"), true);
  for (const text of ["1234.5", "1,234", "01.5", "1,23.5"]) assert.equal(displayedPattern(1).test(text), false, text);
  assert.equal(displayedValue("-1,234.5"), -12345n);
});

test("computed exposure amounts reconcile with the figures they come from", () => {
  const MOVED = "exposure.moved";
  refusedAt(`${MOVED}[moved-3].usd_per_unit`, available, (view) => { view.exposure.moved[2].usd_per_unit = "506"; });
  refusedAt(`${MOVED}[moved-3].share_pct`, available, (view) => { view.exposure.moved[2].share_pct = "1.2"; });
  refusedAt(`${MOVED}[moved-1].usd_per_unit`, available, (view) => { view.exposure.moved[0].usd_per_unit = "1"; });
  refusedAt("exposure.movers[mover-1].moves", available, (view) => { view.exposure.movers[0].moves = "not-a-reason"; });
  refusedAt("exposure.moved[moved-9].id", available, (view) => { view.exposure.moved[0].id = "moved-9"; });
  refusedAt("exposure.moved[moved-3].amount.per_unit.unit", available, (view) => {  // kg per unit x USD per tonne.
    everywhere(view, "iea21-ev-copper", (figure) => { figure.unit = "kg"; });
  });
});

test("statements and comparisons show exactly what they cite", () => {
  refusedAt("view.statement.cites", available, (view) => { view.view.statement!.status = "not_stated"; });
  refusedAt("view.statement", available, (view) => { view.view.statement!.figures.reverse(); });
  refusedAt("view.statement", available, (view) => { view.view.statement!.figures.pop(); });
  refusedAt("differs[differs-earlier-edition].others[0].cite", available, (view) => {
    view.differs[0].others![0].cite = "iea26-demand-2030";
  });
  refusedAt("differs[differs-earlier-edition].others[0]", available, (view) => {
    view.differs[0].others![0].passage = available.risks[2].statement!.passages[0];
  });
});

test("a figure reads the same wherever it is shown, and as its source prints it", () => {
  const VIEW_FIGURE = "view.statement.figures[0]";
  const figure = (view: ThesisView) => view.view.statement!.figures[0];
  refusedAt(`${STEPS}.rows[1].demand_total`, available, (view) => {
    Object.assign(figure(view), { value: "29600", as_shown: "29,600" });
  });
  refusedAt(`${VIEW_FIGURE}.as_shown`, available, (view) => { figure(view).as_shown = "29,600"; });
  refusedAt(`${VIEW_FIGURE}.as_shown`, available, (view) => { figure(view).as_shown = "29,50,0"; });
  refusedAt(`${VIEW_FIGURE}.quote`, available, (view) => { figure(view).quote = "Synthetic 29,500"; });
  refusedAt(`${VIEW_FIGURE}.where`, available, (view) => { figure(view).where = "paragraph 3"; });
  refusedAt(`${VIEW_FIGURE}.unit`, available, (view) => { (figure(view) as { unit: string }).unit = "bushels"; });
  refusedAt("risks[construction-slowdown].statement.passages[0].where", available, (view) => {
    view.sources.find((item) => item.id === "iea-2021")!.transcription!.pages = [1];
  });
  // Grouping as sources print it: "23 000" with a no-break space reads as 23000.
  assert.equal(refusalOf(available, (view) => {
    everywhere(view, "iea26-demand-2030", (item) => { item.as_shown = "29\u00a0500"; });
  }), null);
});

test("sources are https addresses and their states are counted", () => {
  refusedAt("sources[usgs-2026].url", available, (view) => { view.sources[0].url = "http://example.org/a.csv"; });
  refusedAt("sources[usgs-2026].url", available, (view) => { view.sources[0].url = "https://user@example.org/a.csv"; });
  refusedAt("sources[usgs-2026].url", available, (view) => { view.sources[0].url = "https://example.org:443/a.csv"; });
  refusedAt("sources[usgs-2026].transcription", available, (view) => {
    view.sources[0].transcription = { pages: [1], method: "transcribed from the page image" };
  });
  refusedAt("sources[usgs-2026].state", available, (view) => { Object.assign(view.sources[0], { state: "lost" }); });
  refusedAt("sources[usgs-2026].id", available, (view) => { view.sources[1].id = "usgs-2026"; });  // Listed twice.
});

test("counts that do not reconcile are refused", () => {
  refusedAt("counts.elements", available, (view) => { view.counts.elements.available = 16; });
  refusedAt("counts.elements", revalidation, (view) => {
    view.counts.elements.available += 1;
    view.counts.elements.needs_revalidation -= 1;
  });
  refusedAt("counts.sources", revalidation, (view) => {
    view.counts.sources = { verified: 9, changed: 0, missing: 0 };
  });
  refusedAt("counts.sources", available, (view) => { (view.counts.sources as Record<string, number>).other = 0; });
});

test("versions, the draft flag and the publication date agree", () => {
  assert.deepEqual([draft.draft, draft.published_on, draft.versions[1].published_on], [true, null, null]);
  refusedAt("draft", available, (view) => { view.draft = true; });
  refusedAt("draft", draft, (view) => { view.draft = false; });
  refusedAt("published_on", available, (view) => { view.versions[1].published_on = "2026-11-17"; });
  refusedAt("published_on", available, (view) => {  // Not published before it was prepared.
    view.published_on = "2026-11-15";
    view.versions[1].published_on = "2026-11-15";
  });
  refusedAt("versions[0].published_on", available, (view) => { view.versions[0].published_on = null; });
  refusedAt("versions[0].version", available, (view) => { view.versions.reverse(); });
  refusedAt("provider_called", available, (view) => { (view as { provider_called: boolean }).provider_called = true; });
  refusedAt("view_version", available, (view) => { view.view_version = "thesis-view-0.2"; });
  refusedAt("provenance", available, (view) => { Object.assign(view.provenance, { research_use: "included" }); });
});

test("ids are distinct among the thesis's own; fixed and positional ids may repeat one", () => {
  assert.equal(refusalOf(available, (view) => {
    reason(view, "recycling-limited").id = "view";
    risk(view, "construction-slowdown").id = "price-record";
    view.risks[0].id = "mover-1";
  }), null);
  refusedAt(`${CLEAN}.id`, available, (view) => { reason(view, "recycling-limited").id = "clean-tech-demand"; });
  refusedAt("reasons[balance-steps].id", available, (view) => {  // Author ids share one namespace across sections.
    reason(view, "recycling-limited").id = "balance-steps";
  });
  refusedAt("exposure.movers[mover-3].id", available, (view) => { view.exposure.movers[0].id = "mover-3"; });
  refusedAt("view.id", available, (view) => { (view.view as { id: string }).id = "the-view"; });
  refusedAt("log[1].refs", available, (view) => { view.log[1].refs = ["not-a-claim"]; });
  refusedAt("log[1].kind", available, (view) => { view.log[1].kind = "opened"; });
});

test("the client reads a thesis or says why it cannot", async () => {
  const signal = new AbortController().signal;
  const seen: string[] = [];
  assert.equal((await withFetch(200, available, () => fetchThesis(SYNTHETIC, null, signal), seen)).state, "ready");
  assert.equal((await withFetch(200, first, () => fetchThesis(SYNTHETIC, 1, signal), seen)).state, "ready");
  assert.deepEqual(seen, ["/api/theses/synthetic-copper", "/api/theses/synthetic-copper/versions/1"]);
  const missing = await withFetch(404, { detail: "No thesis has this id" }, () => fetchThesis("nope", null, signal));
  assert.deepEqual(missing, { state: "missing", message: "No thesis has this id" });
  const other = await withFetch(200, available, () => fetchThesis(SYNTHETIC, 1, signal));  // Version 2 served for 1.
  assert.deepEqual(other,
    { state: "error", message: "The reply could not be read by this page (version: is not the version asked for)." });
  const paid = await withFetch(200, { ...available, provider_called: true },
    () => fetchThesis(SYNTHETIC, null, signal));
  assert.equal(paid.state, "error");
  const none: string[] = [];
  const zero = await withFetch(200, available, () => fetchThesis(SYNTHETIC, 0, signal), none);
  assert.deepEqual([zero.state, none], ["missing", []]);  // No request for a version that cannot exist.
  const original = globalThis.fetch;
  globalThis.fetch = (async () => { throw new TypeError("connection refused"); }) as typeof fetch;
  try {
    const down = await fetchThesis(SYNTHETIC, null, signal);
    assert.deepEqual(down,
      { state: "error", message: "The local API did not answer. Start it with: python -m second_order serve" });
  } finally {
    globalThis.fetch = original;
  }
});

test("reading aids name a figure by its source's publisher and edition, and its period", () => {
  const named = (figure: Figure) => figureText(figure, available.sources.find((item) => item.id === figure.source)!);
  const mine = available.reasons[1].measure!.latest;
  const usgs = available.sources.find((item) => item.id === "usgs-2026")!;
  assert.equal(named(mine), "22,900 kt · Synthetic USGS 2026 · 2024");
  assert.equal(named(available.price_record.latest!),
    "9,500 USD per tonne · Synthetic World Bank November 2026 · Oct 2026");
  const stated = available.exposure.moved[0].amount!;
  assert.equal(stated.kind === "stated" && named(stated.figure),
    "$410 million · Synthetic Producer Corp. Fiscal 2025 · 2026");
  const computed = available.exposure.moved[2].amount!;
  assert.equal(computed.kind === "computed" && named(computed.per_unit), "53.2 kg per unit · Synthetic IEA 2021");
  // The source is required: there is no fallback that would print a raw source id as reader text.
  assert.throws(() => figureText(mine, undefined as never), TypeError);
  assert.equal(periodText({ year: "2026", period: "2026Q3" }), "Q3 2026");
  assert.equal(periodText({ year: "2026", period: "2026-10-15" }), "15 Oct 2026");
  assert.equal(periodText({ year: null, period: null }), "");
  assert.equal(dayText("2026-11-16"), "16 Nov 2026");
  assert.equal(transcriptionText(available.sources.find((item) => item.id === "iea-2021")!),
    "transcribed from the page image (pages 1, 2 of the PDF)");
  assert.equal(transcriptionText(usgs), null);
  assert.equal(thesisHref(SYNTHETIC, null), "/theses/synthetic-copper");
  assert.equal(thesisHref(SYNTHETIC, 2), "/theses/synthetic-copper/versions/2");
});

test("reading aids say which comparison a measure makes, from the reply's own fields (ruling R12)", () => {
  const sources = new Map(available.sources.map((item) => [item.id, item]));
  const said = (measure: Parameters<typeof comparisonText>[0]) =>
    [withinOneEdition(measure), comparisonText(measure, sources)];
  assert.deepEqual(said(reason(available, "total-demand-rising").measure!),
    [true, "Compares 2035 with 2030 within the same edition (Synthetic IEA, 2026)"]);
  assert.deepEqual(said(clean(available).measure!),
    [false, "Compares the 2026 edition with the 2025 edition, both for 2030"]);
  assert.deepEqual(said(risk(available, "mine-output-rising").measure!),
    [false, "Compares 2025 in the 2026 edition with 2024 in the 2025 edition"]);
  // The source is required, as figureText requires it: no raw source id becomes reader text.
  assert.throws(() => comparisonText(clean(available).measure!, new Map()), TypeError);
});

test("the rule a measure is read by is stated with its exact conditions and the reply's own status words", () => {
  const { reason_states: reasons, risk_states: risks } = available.labels;
  // The shown change is rounded; the status is not (final review M5): "+5.0%" may sit beside "Unchanged".
  const ROUNDED = " The change is shown rounded to one decimal; the status is read from the exact figures.";
  assert.equal(readAsText(clean(available).measure!, reasons),
    "A change of less than 5% in either direction reads as Unchanged; Strengthening when the latest figure is higher " +
    `than the previous one by at least 5%, Weakening when it is lower by at least 5%.${ROUNDED}`);
  assert.equal(readAsText(reason(available, "mine-supply-slow").measure!, reasons),  // A reason that needs lower.
    "A change of less than 2% in either direction reads as Unchanged; Strengthening when the latest figure is lower " +
    `than the previous one by at least 2%, Weakening when it is higher by at least 2%.${ROUNDED}`);
  assert.equal(readAsText(risk(available, "primary-supply-projections").measure!, risks),
    "A change of less than 1% in either direction reads as Unchanged; Materialising when the latest figure is higher " +
    `than the previous one by at least 1%, Receding when it is lower by at least 1%.${ROUNDED}`);
  // The status words are the reply's labels, cut at their colon, never the page's own.
  const relabelled = { ...reasons, strengthening: "Firming: Synthetic.", unchanged: "Steady: Synthetic." };
  assert.equal(readAsText(clean(available).measure!, relabelled),
    "A change of less than 5% in either direction reads as Steady; Firming when the latest figure is higher than the " +
    `previous one by at least 5%, Weakening when it is lower by at least 5%.${ROUNDED}`);
});

test("two listed sources of one publisher and edition are told apart by their titles (final review M9)", () => {
  const usgs = available.sources.find((item) => item.id === "usgs-2026")!;
  assert.equal(editionText(usgs, available.sources), "2026");  // No other synthetic source shares it.
  // As in copper v1, where the MCS 2026 data release and the MCS 2026 chapter both read "U.S. Geological Survey 2026".
  const chapter = { ...usgs, id: "usgs-2026-chapter", title: "Synthetic Mineral Commodity Summaries 2026: copper" };
  const listed = [...available.sources, chapter];
  assert.deepEqual([editionText(usgs, listed), editionText(chapter, listed)],
    [`2026 (${usgs.title})`, `2026 (${chapter.title})`]);
  // Another publisher with the same edition text, or another edition of the same publisher, is no twin.
  assert.equal(editionText(usgs, [...available.sources, { ...chapter, publisher: "Synthetic other" }]), "2026");
  assert.equal(editionText(usgs, [...available.sources, { ...chapter, edition: "2026 revised" }]), "2026");
  // The page names every source through it: figure lines, passage lines, problems and table bases.
  const sections = readFileSync(new URL("../src/components/ThesisSections.tsx", import.meta.url), "utf8");
  assert.match(sections, /edition: editionText\(source, r\.view\.sources\)/);
  assert.match(sections, /`\$\{source\.publisher\} \$\{editionText\(source, r\.view\.sources\)\}`/);
});

test("the price record's rows say which retained figure each is (final review M6)", () => {
  const sections = readFileSync(new URL("../src/components/ThesisSections.tsx", import.meta.url), "utf8");
  assert.match(sections, /<dt>Latest retained when the thesis opened<\/dt>/);
  assert.match(sections, /<dt>Latest retained<\/dt>/);
  assert.doesNotMatch(sections, /<dt>When the thesis opened<\/dt>/);
});

test("routes parse versions and refuse malformed ones", () => {
  assert.deepEqual(matchRoute("/theses/copper"), { page: "thesis", id: "copper", version: null });
  assert.deepEqual(matchRoute("/theses/copper/"), { page: "thesis", id: "copper", version: null });
  assert.deepEqual(matchRoute("/theses/copper/versions/2"), { page: "thesis", id: "copper", version: 2 });
  assert.deepEqual(matchRoute("/theses/copper/versions/9999/"), { page: "thesis", id: "copper", version: 9999 });
  assert.deepEqual(matchRoute("/theses/synthetic-copper/versions/1"),
    { page: "thesis", id: SYNTHETIC, version: 1 });
  for (const path of ["/theses/copper/versions/0", "/theses/copper/versions/x", "/theses/copper/versions/01",
    "/theses/copper/versions/10000", "/theses/copper/versions/-1", "/theses/copper/versions/1.0",
    "/theses/copper/versions/%D9%A3", "/theses/copper/versions/%E0%A4%A", "/theses/%E0%A4%A",
    "/theses/%E0%A4%A/versions/2"]) {
    assert.deepEqual(matchRoute(path), { page: "not-found", reason: "malformed" }, path);
  }
  for (const path of ["/theses", "/theses/", "/theses/copper/versions", "/theses/copper/versions/2/x"]) {
    assert.deepEqual(matchRoute(path), { page: "not-found", reason: "unknown" }, path);
  }
});

test("the catalog lists committed theses under their own addresses", async () => {
  assert.equal(isThesisCatalog(catalog), true);
  assert.deepEqual(catalog.theses.map((item) => item.href), [`/theses/${SYNTHETIC}`]);
  const changed = (change: (body: ThesisCatalog) => void) => {
    const body = copy(catalog);
    change(body);
    return isThesisCatalog(body);
  };
  assert.equal(changed((body) => { body.theses[0].published_on = null; }), true);  // The latest version is a draft.
  assert.equal(changed((body) => { body.theses[0].href = "/theses/other"; }), false);
  assert.equal(changed((body) => { (body as { provider_called: boolean }).provider_called = true; }), false);
  assert.equal(changed((body) => { body.theses.push(copy(body.theses[0])); }), false);
  assert.equal(changed((body) => { body.theses[0].latest_version = 0; }), false);
  // Exact keys, as the thesis reader checks them: nothing unexpected on the body or on an entry.
  assert.equal(changed((body) => { Object.assign(body, { note: "Synthetic." }); }), false);
  assert.equal(changed((body) => { Object.assign(body.theses[0], { note: "Synthetic." }); }), false);
  const signal = new AbortController().signal;
  assert.equal((await withFetch(200, catalog, () => fetchThesisCatalog(signal))).state, "ready");
  const wrong = await withFetch(200, { ...catalog, view_version: "x" }, () => fetchThesisCatalog(signal));
  assert.equal(wrong.state, "error");
});
