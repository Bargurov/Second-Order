// The fuels page's fixed copy and its money formatting (fuelsText.ts).
import assert from "node:assert/strict";
import { test } from "node:test";
import { CAPTION, crackLabel, GLOSSARY, money, NOT_LIST, shownNegative, signed } from "../src/fuelsText.ts";

test("money adds the dollar sign, and a negative takes the true minus sign before it", () => {
  assert.equal(money("80.00"), "$80.00");
  assert.equal(money("-3.00"), "−$3.00");
  assert.equal(money("0.00"), "$0.00");
  assert.equal(money("1,234.50"), "$1,234.50");
  assert.equal(money("2.500"), "$2.500");
});

test("signed marks a rise with plus, a fall with the true minus sign, and no change with neither", () => {
  assert.equal(signed("0.96"), "+0.96");
  assert.equal(signed("-0.04"), "−0.04");
  assert.equal(signed("0.00"), "0.00");
  assert.equal(signed("-0.00"), "0.00");
});

test("the crack label says negative only when its shown figure is below zero", () => {
  assert.equal(crackLabel({ sign: "negative", shown: "-3.00" }), "Crack −$3.00 (negative)");
  assert.equal(crackLabel({ sign: "negative", shown: "-0.01" }), "Crack −$0.01 (negative)");
  assert.equal(crackLabel({ sign: "negative", shown: "0.00" }), "Crack $0.00");  // within half a cent below zero
  assert.equal(crackLabel({ sign: "zero", shown: "0.00" }), "$0.00");
  assert.equal(crackLabel({ sign: "positive", shown: "32.00" }), "$32.00");
  assert.equal(shownNegative({ sign: "negative", shown: "-3.00" }), true);
  assert.equal(shownNegative({ sign: "negative", shown: "0.00" }), false);
  assert.equal(shownNegative({ sign: "zero", shown: "0.00" }), false);
});

test("the fixed copy is verbatim and never says today", () => {
  assert.equal(CAPTION, "Drawn to scale from zero. The line is the Brent spot price. The band is the 3-2-1 crack: how much "
    + "a benchmark basket of two barrels of New York Harbor gasoline and one of diesel is worth above three barrels of "
    + "crude, per barrel, before any refining costs. It approximates a refinery's gross margin; it is not any refinery's "
    + "profit.");
  assert.equal(NOT_LIST.length, 3);
  assert.deepEqual(Object.keys(GLOSSARY), ["Crack spread", "3-2-1", "Brent and WTI", "Spot and futures",
    "Backwardation and contango", "MMBtu", "Kinds"]);
  for (const text of [CAPTION, ...NOT_LIST, ...Object.values(GLOSSARY)]) assert.doesNotMatch(text, /today/i);
});
