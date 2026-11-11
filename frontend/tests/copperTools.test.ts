// The copper tools' fail-closed readers (copperTools.ts, copperActions.ts) against replies captured from the server
// on SYNTHETIC sources (tests/test_copper_tools_api.py writes the fixtures), and the Part 0 box's links.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { checkPanel, checkResult, crf, type Panel, type Preview, type Saved } from "../src/copperActions.ts";
import { div, halfEven, int, make, ofPlain, shownKt, sub } from "../src/copperNumbers.ts";
import { CHAIN, CHAIN_LINKS, LINK_STATUSES } from "../src/copperQuestion.ts";
import { copperRefusal, statementDate, type CopperToolsView } from "../src/copperTools.ts";
import { matchRoute } from "../src/routes.ts";

const fixture = (name: string) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf-8"));
const view = (): CopperToolsView => fixture("copper-tools-view.json");
const refusal = (change: (body: any) => void, fixtureName = "copper-tools-view.json") => {
  const body = fixture(fixtureName);
  change(body);
  return copperRefusal(body);
};
const baseline = (body: any, scenario: string, year: string) =>
  body.coverage.baselines.find((b: any) => b.scenario === scenario && b.year === year);

test("the captured replies pass", () => {
  assert.equal(copperRefusal(view()), null);
  assert.equal(copperRefusal(fixture("copper-tools-unavailable.json")), null);
});

test("the worked example is what the reader recomputes", () => {
  const steps = baseline(view(), "steps", "2035");
  assert.equal(steps.coverage.residual.shown, "12,789");
  assert.equal(steps.coverage.share_pct.shown, "38.2");
  assert.equal(steps.decomposition.residual_change.value, "8241");
  assert.equal(steps.epsilon.value, "-2.0132");
});

test("a computed value that does not follow its figures is refused, naming its place", () => {
  const message = refusal((body) => { baseline(body, "steps", "2035").coverage.residual.value = "12790"; });
  assert.match(message ?? "", /coverage\.baselines\.steps-2035\.coverage\.residual/);
  assert.doesNotMatch(message ?? "", /12790/);
  assert.notEqual(refusal((body) => { baseline(body, "steps", "2035").coverage.share_pct.shown = "38.1"; }), null);
  assert.notEqual(refusal((body) => { baseline(body, "hd", "2040").decomposition.demand_rows[0].change.shown = "1"; }),
                  null);
  assert.notEqual(refusal((body) => { baseline(body, "cps", "2040").delta.value = "0"; }), null);
});

test("a figure changed without its outputs is refused", () => {
  assert.notEqual(refusal((body) => { body.figures["iea-demand-total-steps-2035"].value = "33523";
    body.figures["iea-demand-total-steps-2035"].as_shown = "33,523"; }), null);
  assert.notEqual(refusal((body) => { body.figures["iea-demand-total-steps-2035"].as_shown = "33,523"; }), null);
});

test("a value or text that is not verified is never shown", () => {
  const body = fixture("copper-tools-unavailable.json");
  body.figures["iea-demand-ev-2025"].value = "794";
  assert.notEqual(copperRefusal(body), null);
  assert.notEqual(refusal((b) => { b.passages["iea-supply-note-pipeline"].text = "x"; },
                          "copper-tools-unavailable.json"), null);
  assert.notEqual(refusal((b) => { b.coverage.baselines[0].coverage.residual.value = "1"; },
                          "copper-tools-unavailable.json"), null);
  assert.notEqual(refusal((b) => { b.figures["iea-demand-ev-2025"].state = "verified"; },
                          "copper-tools-unavailable.json"), null);
});

test("perturbations keep their fixed order and kinds", () => {
  assert.notEqual(refusal((body) => { baseline(body, "steps", "2035").perturbations.reverse(); }), null);
  assert.notEqual(refusal((body) => { baseline(body, "cps", "2035").perturbations.splice(2, 0,
    baseline(body, "steps", "2035").perturbations[2]); }), null);
});

test("producer rows reconcile or are withheld, and Southern Copper's margin is not shown", () => {
  assert.notEqual(refusal((body) => { body.producers.rows[0].reconciles = false; }), null);
  assert.notEqual(refusal((body) => { body.figures["fcx-us-treatment-2025"].value = "0.14";
    body.figures["fcx-us-treatment-2025"].as_shown = "0.14"; }), null);
  assert.notEqual(refusal((body) => { body.producers.margins.at(-1).shown = "1.00"; }), null);
  assert.notEqual(refusal((body) => { body.producers.capital_panel.rate_pct = "8"; }), null);
  assert.notEqual(refusal((body) => { body.producers.projects[0].capital_per_annual_tonne[0].shown = "38,580"; }),
                  null);
});

test("the refining series is shown under its source name with its unknowns", () => {
  assert.notEqual(refusal((body) => { body.coverage.refining.source_name = "Refining capacity"; }), null);
  assert.notEqual(refusal((body) => { body.coverage.refining.unknowns.pop(); }), null);
});

test("a saved record shows a result only when verified", () => {
  assert.notEqual(refusal((body) => { body.scenarios.records[0].state = "needs_revalidation"; }), null);
});

test("the preview and the saved record recompute exactly, flags included", () => {
  const preview: Preview = fixture("copper-preview.json");
  checkResult(preview.result, view());
  assert.equal(preview.result.residual.value, "12622.8350405");
  assert.equal(preview.result.residual.shown, "12,622.835");
  const saved: Saved = fixture("copper-saved.json");
  checkResult({ ...saved.record.result, scenario: saved.record.baseline.scenario, year: saved.record.baseline.year,
                assumptions: saved.record.assumptions } as any, view());
  const flags = structuredClone(preview.result);
  flags.flags.pop();
  assert.throws(() => checkResult(flags, view()));
  const changed = structuredClone(preview.result);
  changed.residual.value = "12622.835";  // The shown value fed back as exact: refused.
  assert.throws(() => checkResult(changed, view()));
});

const CURRENT = "bagdad-2026-11-04";
const project = (body: any, id: string) => body.producers.projects.find((item: any) => item.id === id);

test("the two Bagdad statements are read as captured", () => {
  const body = view() as any;
  assert.equal(body.view_version, "copper-tools-view-0.2");
  assert.equal(body.linked.state, "available");
  assert.deepEqual(body.producers.projects.slice(0, 2).map((item: any) => item.id), [CURRENT, "bagdad"]);
  assert.equal(project(body, CURRENT).capital_per_annual_tonne[0].shown, "44,092");
  assert.equal(copperRefusal(fixture("copper-tools-unavailable.json")), null);
});

test("break-even stays apart, and a pair or a passage never spans the two statements", () => {
  const cases: [(body: any) => void, string][] = [
    [(body) => { project(body, CURRENT).incentive = ["nr-bagdad-breakeven-cu"]; },
      "an incentive price is never a break-even record"],
    [(body) => { project(body, CURRENT).break_even = ["fcx-bagdad-incentive-2025"]; },
      "break-even comes only from break-even records"],
    [(body) => { project(body, "bagdad").capital_per_annual_tonne[0].uses = ["fcx-bagdad-capital-2025",
      "nr-bagdad-cu-increment"]; }, "a pair spans two statements"],
    [(body) => { project(body, "bagdad").passages.push("nr-p-schedule"); }, "a passage comes from another statement"],
    [(body) => { body.linked.records["nr-bagdad-capex-estimate"].state = "withheld"; },
      "a withheld entry carries a value"],
    [(body) => { body.view_version = "copper-tools-view-0.1"; }, "expected copper-tools-view-0.2"],
  ];
  for (const [change, rule] of cases) {
    const message = refusal(change);
    assert.ok(message?.includes(rule), `${rule}: ${message}`);
  }
});

test("a linked figure's printed figure is its value", () => {
  const capex = (body: any) => body.linked.records["nr-bagdad-capex-estimate"];
  const rule = "linked.nr-bagdad-capex-estimate: its printed figure is not its value";
  for (const change of [(body: any) => { capex(body).display = "999.9"; },
    (body: any) => { capex(body).display = null; }, (body: any) => { capex(body).value = null; },
    (body: any) => { capex(body).display = "about 4.5"; }]) {
    const message = refusal(change);
    assert.ok(message?.includes(rule), `${rule}: ${message}`);
  }
  assert.equal(refusal((body) => { capex(body).display = "4.50"; }), null);
});

test("every record a row names exists in its own statement, in the role of its field", () => {
  const rule = (id: string, field: string, name: string) =>
    `producers.projects.${id}.${field}: names ${name}, not a record of its statement in this role`;
  const cases: [(body: any) => void, string][] = [
    [(body) => { project(body, CURRENT).incentive = ["fcx-bagdad-incentive-2025"]; },
      rule(CURRENT, "incentive", "fcx-bagdad-incentive-2025")],
    [(body) => { project(body, CURRENT).construction = "nr-bagdad-no-such-record"; },
      rule(CURRENT, "construction", "nr-bagdad-no-such-record")],
    [(body) => { project(body, CURRENT).construction = "nr-bagdad-capex-estimate"; },
      rule(CURRENT, "construction", "nr-bagdad-capex-estimate")],
    [(body) => { project(body, CURRENT).caveats = ["nr-p-schedule"]; }, rule(CURRENT, "caveats", "nr-p-schedule")],
    [(body) => { project(body, CURRENT).passages.push("nr-p-cost-risk"); },
      rule(CURRENT, "passages", "nr-p-cost-risk")],
    [(body) => { project(body, CURRENT).earlier_capital = "fcx-bagdad-capital-2025"; },
      rule(CURRENT, "earlier_capital", "fcx-bagdad-capital-2025")],
    [(body) => { project(body, "bagdad").incentive.push("fcx-no-such-figure"); },
      rule("bagdad", "incentive", "fcx-no-such-figure")],
    [(body) => { project(body, "bagdad").construction = "fcx-bagdad-capital-2025"; },
      rule("bagdad", "construction", "fcx-bagdad-capital-2025")],
  ];
  for (const [change, expected] of cases) {
    const message = refusal(change);
    assert.ok(message?.includes(expected), `${expected}: ${message}`);
  }
  const withheld = (change: (body: any) => void) => refusal(change, "copper-tools-unavailable.json");
  assert.ok(withheld((body) => { project(body, CURRENT).construction = "nr-bagdad-no-such-record"; })
    ?.includes(rule(CURRENT, "construction", "nr-bagdad-no-such-record")));
});

test("the stamps' dates are formatted from the ISO text, in any time zone", () => {
  const zone = process.env.TZ;
  try {
    for (const tz of ["UTC", "America/Los_Angeles", "Pacific/Kiritimati"]) {
      process.env.TZ = tz;
      assert.equal(statementDate("2026-11-04"), "4 Nov 2026");
      assert.equal(statementDate("2026-02-13"), "13 Feb 2026");
    }
  } finally {
    process.env.TZ = zone;
  }
  assert.equal(statementDate(null), "date not available");
});

test("a panel reply that withholds a row the loaded view shows is refused by name", () => {
  const panel: Panel = fixture("copper-capital-charge.json");
  const row = panel.projects.find((item) => item.project === CURRENT)!;
  row.charges[0] = { ...row.charges[0], value: null, shown: null, withheld: [...row.charges[0].uses] };
  assert.throws(() => checkPanel(panel, view(), "8", "20"), /withheld here but available in the loaded view; reload the page/);
});

test("the capital panel recomputes exactly, with the zero-rate limit", () => {
  const panel: Panel = fixture("copper-capital-charge.json");
  checkPanel(panel, view(), "8", "20");
  const zero: Panel = fixture("copper-capital-charge-zero.json");
  checkPanel(zero, view(), "0", "20");
  assert.equal(zero.method, "limit_at_zero_rate");
  assert.equal(zero.crf, "0.050000");
  assert.equal(zero.projects.find((row) => row.project === "tia-maria")?.charges[0].shown, "0.341");
  assert.throws(() => checkPanel({ ...zero, method: "annuity" }, view(), "0", "20"));
  assert.throws(() => checkPanel({ ...panel, crf: "0.101853" }, view(), "8", "20"));
  assert.throws(() => checkPanel(panel, view(), "8", "25"));
});

test("exact numbers", () => {
  assert.deepEqual(crf(int(0), 20), make(1n, 20n));
  const near = crf(make(1n, 10n ** 12n), 20);
  assert.ok(halfEven(sub(near, div(int(1), int(20))), 9) === "0.000000000");
  assert.equal(halfEven(crf(make(8n, 100n), 20), 6), "0.101852");
  assert.equal(halfEven(make(5n, 2n), 0), "2");
  assert.equal(halfEven(make(-5n, 2n), 0), "-2");
  assert.equal(halfEven(make(-1n, 1000n), 2), "0.00");
  assert.deepEqual(shownKt(ofPlain("12622.8350405")!), { shown: "12,622.835", rounded: true });
  assert.deepEqual(shownKt(ofPlain("-41.80585")!), { shown: "-41.80585", rounded: false });
});

test("the Part 0 box links only to pages that exist, with statuses from its vocabulary", () => {
  const hrefs = new Set(CHAIN.flatMap((link) => link.links.map((item) => item.href)));
  assert.deepEqual([...hrefs].sort(), [...CHAIN_LINKS].sort());
  for (const href of hrefs) assert.notEqual(matchRoute(href).page, "not-found", href);
  assert.deepEqual(CHAIN.map((link) => link.id), ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8"]);
  for (const link of CHAIN) assert.ok(link.status in LINK_STATUSES, link.id);
  const text = CHAIN.map((link) => link.text).join(" ");
  assert.doesNotMatch(text, /\d/);
  assert.doesNotMatch(text, /\b(causes?|drives?|proves?|confirms?)\b/i);
});
