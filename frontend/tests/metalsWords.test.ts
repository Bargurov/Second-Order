// The metals page's short words (metalsWords.ts): a cell that shows no figure gives a short label, and its full reason
// stays one click away; the label never adds a claim the reason does not make.
import assert from "node:assert/strict";
import { test } from "node:test";
import { YEARS_UNDER_ONE } from "../src/metals.ts";
import { shortReason, yearsText } from "../src/metalsWords.ts";

const UNIT = "Unit in doubt: the printed USGS chapter (Mineral Commodity Summaries 2026, vanadium, page 2) gives these "
  + "reserves in thousand metric tons, while this data file labels them metric tons.";

test("a unit issue reads as such wherever it reaches, with or without its series' name", () => {
  assert.equal(shortReason(`Reserves: ${UNIT}`, "years"), "Unit in doubt");
  assert.equal(shortReason(`Production: ${UNIT}`, "years"), "Unit in doubt");
  assert.equal(shortReason(UNIT, "rank"), "Unit in doubt");
});

test("each reason the server gives has its short label", () => {
  const cases: [string, "rank" | "years" | "share", string][] = [
    ["United States is printed as “W”, so the order is unknown", "rank", "Order unknown"],
    ["Congo (Kinshasa) is printed as “NA”, so the order is unknown", "rank", "Order unknown"],
    ["The world total is printed as “>85,000,000”, not as a number", "rank", "World total not a number"],
    ["Reserves: The world total is printed as “>85,000,000”, not as a number", "years", "World total not a number"],
    ["The world total is printed as “0”, so no share can be computed", "share", "World total is zero"],
    ["USGS prints no world total for this series", "rank", "No world total"],
    ["USGS prints more than one world total for this series", "share", "Two world totals"],
    ["USGS prints no country for this series", "rank", "No countries named"],
    ["No countries are named", "rank", "No countries named"],
    ["Fewer than three countries are named", "rank", "Fewer than three named"],
    ["Printed as “W”", "share", "Printed as “W”"],
    ["Printed as “—”", "share", "Printed as “—”"],
    ["Not computed: no 2025 reserves series matches this stage", "years", "No matching series"],
    ["No matching 2025 reserves series", "rank", "No matching series"],
  ];
  for (const [reason, kind, label] of cases) assert.equal(shortReason(reason, kind), label, reason);
});

test("a research link's figure that is not shown gets a label that says no more than its reason", () => {
  const withheld = "The retained file's size or SHA-256 differs from its acquisition record; it is not used.";
  const cases: [string, string][] = [
    [`The USGS part is withheld: ${withheld}`, "Withheld"],
    [`The IEA part is withheld: ${withheld}`, "Withheld"],
    ["The USGS part is withheld", "Withheld"],
    ["USGS prints no 2025 production series at the refining stage for this metal", "No such stage"],
    ["USGS prints no 2025 net import reliance for this metal", "Not printed"],
    ["No years figure for this pair", "No years figure"],
    ["The IEA lists no Electric vehicles use for Cobalt in this table", "Not in the IEA table"],
    ["The IEA's table gives no technology split for Cadmium", "No technology split"],
    ["The IEA's 2025 energy-technology total for Neodymium is not positive, so no share is computed", "No share"],
    ["United States is printed as “W”, so the order is unknown", "Order unknown"],
    ["Fewer than three countries are named", "Fewer than three named"],
  ];
  for (const [reason, label] of cases) assert.equal(shortReason(reason, "figure"), label, reason);
  // A part's withheld words never read as a ranking that failed.
  assert.notEqual(shortReason(`The USGS part is withheld: ${withheld}`, "rank"), "Not ranked");
  assert.equal(shortReason("The USGS part is withheldx", "figure"), "Not shown");
});

test("an unknown reason gets a plain label by its kind", () => {
  assert.equal(shortReason("Something new", "rank"), "Not ranked");
  assert.equal(shortReason("Something new", "years"), "Not computed");
  assert.equal(shortReason("Something new", "share"), "No share");
  assert.equal(shortReason("Something new", "figure"), "Not shown");
  assert.equal(shortReason("", "rank"), "Not ranked");
});

test("a years figure as words", () => {
  assert.equal(yearsText("43"), "43 years");
  assert.equal(yearsText("1"), "1 year");
  assert.equal(yearsText(YEARS_UNDER_ONE), "less than 1 year");
});
