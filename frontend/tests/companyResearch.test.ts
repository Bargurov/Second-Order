// The FCX company page's reader (companyResearch.ts) against replies captured from the server
// (tests/fixtures/company-fcx-*.json, written by tests/test_company_research.py).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { cellText, companyRefusal, evaluate, figureKind, figureText, printedRat, typedNumber } from "../src/companyResearch.ts";
import { halfEven, ofPlain } from "../src/copperNumbers.ts";

const fixture = (name: string) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf-8"));
const refusal = (change: (body: any) => void, name = "company-fcx-view.json") => {
  const body = fixture(name);
  change(body);
  return companyRefusal(body);
};

test("the captured replies pass", () => {
  for (const name of ["company-fcx-view.json", "company-fcx-news-changed.json", "company-fcx-unavailable.json"]) {
    assert.equal(companyRefusal(fixture(name)), null, name);
  }
});

test("a computed figure that does not recompute is refused, naming its place and not its value", () => {
  const message = refusal((body) => { body.records["c-yoy-revenues-q3-2026"].value = "8.3"; });
  assert.match(message ?? "", /records\.c-yoy-revenues-q3-2026: it does not recompute/);
  assert.ok(!(message ?? "").includes("8.3"));
});

test("a published figure that does not read as its value is refused", () => {
  const message = refusal((body) => { body.records["r3-cu-sales-q3-2026"].value = "750"; });
  assert.match(message ?? "", /r3-cu-sales-q3-2026: its printed figure does not read as its value/);
});

test("a withheld figure that still carries a value or a quote is refused", () => {
  assert.match(refusal((body) => { body.records["nr-bagdad-capex-estimate"].value = "4.5"; },
    "company-fcx-news-changed.json") ?? "", /nr-bagdad-capex-estimate: withheld but carries a value/);
  assert.match(refusal((body) => { body.records["nr-bagdad-capex-estimate"].quote = "approximate $4.5 billion"; },
    "company-fcx-news-changed.json") ?? "", /withheld but carries a value/);
});

test("a figure shown though its source is not verified is refused", () => {
  const message = refusal((body) => {
    body.sources.find((s: any) => s.id === "release-2026q3").state = "changed";
    body.verified = 3;
  });
  assert.match(message ?? "", /shown though its source is not verified/);
});

test("a computed figure resting on a withheld input is refused", () => {
  const message = refusal((body) => {
    const input = body.records["r3-capex-9m-2026"];
    for (const key of ["row", "column", "note"]) delete input[key];
    Object.assign(input, { state: "withheld", value: null, display: null, quote: null, problem: "test" });
  });
  assert.match(message ?? "", /input .* is withheld/);
});

test("a mix of bases without a stated reason is refused", () => {
  const message = refusal((body) => { delete body.records["c-bagdad-cu-increment-share-fy2025"].basis_mix; });
  assert.match(message ?? "", /mixes bases without saying why/);
});

test("a text block shown though it names something withheld is refused, and the reverse", () => {
  assert.match(refusal((body) => {
    const block = body.page.summary[2];
    Object.assign(block, { state: "available", segments: block.refs.map((ref: string) => ({ ref, mode: null })) });
  }, "company-fcx-news-changed.json") ?? "", /page\.summary\[2\]: shown though it names something withheld/);
  assert.match(refusal((body) => { Object.assign(body.page.summary[0], { state: "withheld", segments: null }); }) ?? "",
    /page\.summary\[0\]: withheld with nothing withheld/);
});

test("a typed number in a text, or an unknown record, is refused", () => {
  assert.match(refusal((body) => { body.page.summary[0].segments[0].text = "Copper was 75 percent of "; }) ?? "",
    /a number is typed in the text/);
  assert.match(refusal((body) => { body.page.tiles[0].value = "r3-no-such-record"; }) ?? "",
    /tiles\[0\]\.value: names a record that is not in the reply/);
  assert.equal(typedNumber("The 10-Q and the 10-K of 2026"), false);
  assert.equal(typedNumber("about 3 years"), true);
});

test("a table row that mixes bases is refused", () => {
  const message = refusal((body) => {
    body.page.numbers.views[0].main.rows[0].ids[1] = "r3-ni-common-is-q3-2025";
  });
  assert.match(message ?? "", /a row mixes bases/);
});

test("exact formulas and half-even rounding, as the server rounds", () => {
  const v = (text: string) => ofPlain(text)!;
  assert.equal(halfEven(evaluate("(a / b - 1) * 100", { a: v("7546"), b: v("6972") })!, 1), "8.2");
  assert.equal(halfEven(evaluate("c * (100 - a - h) / 100", { c: v("4.5"), a: v("20"), h: v("35") })!, 3), "2.025");
  assert.equal(halfEven(v("0.125"), 2), "0.12");
  assert.equal(halfEven(v("-2.5"), 0), "-2");
  assert.equal(evaluate("a +", { a: v("1") }), null);
  assert.equal(evaluate("import(x)", {}), null);
  assert.equal(evaluate("a / b", { a: v("1"), b: v("0") }), null);
  assert.deepEqual(printedRat("(1,061)"), ofPlain("-1061"));
  assert.deepEqual(printedRat("0.43%"), ofPlain("0.43"));
  assert.equal(printedRat("1,06"), null);
});

test("figures read with their units and signs", () => {
  const records = fixture("company-fcx-view.json").records;
  assert.equal(figureText(records["r3-revenues-q3-2026"]), "$7,546 million");
  assert.equal(figureText(records["r3-cu-sales-q3-2026"]), "749 million pounds");
  assert.equal(figureText(records["r3-cu-price-q3-2026"]), "$6.54");
  assert.equal(figureText(records["c-rev-bridge-volume-q3-2026"], "signed"), "−$1,813 million");
  assert.equal(figureText(records["c-rev-bridge-price-q3-2026"], "signed"), "+$1,656 million");
  assert.equal(figureText(records["r3-cf-dist-nci-9m-2026"], "size"), "$625 million");
  assert.equal(figureText(records["c-common-share-ni-q3-2026"]), "69.5%");
  assert.equal(cellText(records["r3-ni-nci-q3-2026"]), "(514)");
  assert.equal(cellText(records["c-yoy-revenues-q3-2026"], true), "+8.2%");
  assert.equal(figureKind(records["r3-out-capex-fy2026"]), "estimate");
  assert.equal(figureKind(records["r3-cu-sales-q3-2026"]), "published");
  assert.equal(figureKind(records["c-ocf-less-capex-9m-2026"]), "computed");
});

test("a withheld figure sends only what identifies it: a note, explanation or label is refused by field name", () => {
  const record = (body: any) => body.records["r3-ocf-9m-2026"];
  const note = "cash used for working capital was $0.8 billion";
  const message = refusal((body) => { record(body).note = note; }, "company-fcx-unavailable.json");
  assert.match(message ?? "", /records\.r3-ocf-9m-2026: withheld but carries note/);
  assert.ok(!(message ?? "").includes("working capital"));
  assert.match(refusal((body) => { body.records["c-bagdad-funding-2027"].unit_mix = "USD billions x percent"; },
    "company-fcx-news-changed.json") ?? "", /c-bagdad-funding-2027: withheld but carries unit_mix/);
  assert.match(refusal((body) => { record(body).row = "Operating cash flows"; }, "company-fcx-unavailable.json") ?? "",
    /withheld but carries row/);
});

test("a figure named with a percentage is refused, naming the field and never the figure", () => {
  const withheld = refusal((body) => { body.records["r3-ocf-9m-2026"].metric = "Operating cash flows (48.76%)"; },
    "company-fcx-unavailable.json");
  assert.match(withheld ?? "", /records\.r3-ocf-9m-2026: its metric carries a percentage/);
  assert.ok(!(withheld ?? "").includes("48.76"));
  assert.match(refusal((body) => { body.records["r3-cu-sales-q3-2026"].location = "Selected Operating Data (48.76%)"; })
    ?? "", /records\.r3-cu-sales-q3-2026: its location carries a percentage/);
  assert.match(refusal((body) => { body.records["r3-cu-sales-q3-2026"].period.label = "Q3 2026 at 48.76 %"; }) ?? "",
    /records\.r3-cu-sales-q3-2026: its period label carries a percentage/);
});

test("a measure's definition in a name is not a percentage: the sensitivities pass", () => {
  const body = fixture("company-fcx-view.json");
  const names = Object.values(body.records).map((record: any) => record.metric ?? "");
  assert.ok(names.some((name) => name.includes("per $0.10/lb change")), "a sensitivity with its definition is in the reply");
  assert.equal(companyRefusal(body), null);
});

test("a withheld assumption that carries its statement, or a withheld line that carries its words, is refused", () => {
  assert.match(refusal((body) => { body.records["a-bagdad-funding-arithmetic"].statement = "its $4.5 billion estimate"; },
    "company-fcx-news-changed.json") ?? "", /a-bagdad-funding-arithmetic: a withheld assumption carries its statement/);
  assert.match(refusal((body) => {
    const block = body.page.summary[2];
    block.segments = [{ text: "In November the board approved a " }, { ref: block.refs[0], mode: null }];
  }, "company-fcx-news-changed.json") ?? "", /page\.summary\[2\]: withheld but carries its words/);
});
