import assert from "node:assert/strict";
import { test } from "node:test";
import { barrelGeometry, BODY_PATH, sparklinePath, spreadLabels, VIEWBOX, Y_FULL, Y_ZERO } from "../src/fuelsBarrel.ts";

test("the approved constants", () => {
  assert.equal(BODY_PATH, "M170,40 Q158,170 170,300 Q245,314 320,300 Q332,170 320,40 Q245,52 170,40 Z");
  assert.equal(VIEWBOX, "0 0 340 330");
  assert.equal(Y_ZERO, 306);
  assert.equal(Y_FULL, 46);
});

test("basket 112 over Brent 80: full barrel, line at 80/112 of the height", () => {
  const g = barrelGeometry(112, 80);
  assert.equal(g.drawable, true);
  assert.equal(g.fillTop, Y_FULL);
  assert.ok(Math.abs(g.lineY! - (306 - (80 / 112) * 260)) < 1e-9);
  assert.deepEqual(g.band, { top: g.fillTop, bottom: g.lineY });
  assert.equal(g.lineAboveFill, false);
  assert.equal(g.note, null);
});

test("zero crack: the line sits exactly at the basket level, no band", () => {
  const g = barrelGeometry(100, 100);
  assert.equal(g.lineY, g.fillTop);
  assert.equal(g.band, null);
  assert.equal(g.lineAboveFill, false);
});

test("negative crack: the line is above the fill, no band", () => {
  const g = barrelGeometry(112, 115);
  assert.equal(g.lineY, Y_FULL);
  assert.ok(g.fillTop! > g.lineY!);
  assert.equal(g.band, null);
  assert.equal(g.lineAboveFill, true);
});

test("non-positive or missing values are not drawable", () => {
  for (const [basket, brent] of [[0, 80], [112, -5], [null, 80], [112, null], [Infinity, 80], [112, NaN]] as const) {
    const g = barrelGeometry(basket, brent);
    assert.equal(g.drawable, false);
    assert.equal(g.band, null);
    assert.equal(g.note, "Cannot be drawn to scale from zero");
  }
});

test("labels never overlap and keep their order", () => {
  assert.deepEqual(spreadLabels([46, 47, 47], 40, 20, 320), [46, 86, 126]);
  assert.deepEqual(spreadLabels([300, 310, 315], 40, 20, 320), [240, 280, 320]);
  assert.deepEqual(spreadLabels([100, 200, 300], 40, 20, 320), [100, 200, 300]);
  assert.deepEqual(spreadLabels([], 40, 20, 320), []);
});

test("a run too long for the span stays no higher than the top", () => {
  assert.deepEqual(spreadLabels([30, 31, 32], 40, 20, 90), [20, 60, 100]);
});

test("a gap breaks the sparkline and nothing is padded", () => {
  const path = sparklinePath([["2026-01-01", "1"], ["2026-01-02", "3"], ["2026-01-03", null], ["2026-01-05", "2"],
    ["2026-01-06", "3"]], 100, 50);
  assert.equal(path, "M0,50 L20,0 M80,25 L100,0");
});

test("x follows calendar days, and a flat series sits mid-height", () => {
  assert.equal(sparklinePath([["2026-01-01", "5"], ["2026-01-11", "5"]], 100, 40), "M0,20 L100,20");
});

test("fewer than two valued points gives an empty path", () => {
  assert.equal(sparklinePath([], 100, 50), "");
  assert.equal(sparklinePath([["2026-01-01", "1"]], 100, 50), "");
  assert.equal(sparklinePath([["2026-01-01", "1"], ["2026-01-02", null]], 100, 50), "");
});

test("a point isolated by gaps draws no mark of its own", () => {
  const path = sparklinePath([["2026-01-01", "1"], ["2026-01-02", null], ["2026-01-03", "2"], ["2026-01-04", null],
    ["2026-01-05", "3"], ["2026-01-06", "4"]], 40, 30);
  assert.equal(path, "M32,10 L40,0");
});
