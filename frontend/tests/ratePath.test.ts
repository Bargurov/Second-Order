// The market-implied rate path reader (src/ratePath.ts) against the views the server actually serves (written by
// tests/test_rate_context.py into fixtures/rate-path-*.json from SYNTHETIC workbooks). Replies are read fail-closed: a
// percent that is not the exact shift of its basis points, an observation on or after the publication date, windows
// out of order or beyond four, a probability in the windows, or meeting-specific pricing that is not unavailable.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { MAX_WINDOWS, isRatePathView, prepareCommand, shiftPercent, strip, type RatePathView } from "../src/ratePath.ts";

const fixture = (name: string): RatePathView =>
  JSON.parse(readFileSync(new URL(`./fixtures/rate-path-${name}.json`, import.meta.url), "utf8"));
const available = fixture("available");
const states = { available, "no-coverage": fixture("no-coverage"), "not-prepared": fixture("not-prepared"),
                 unreadable: fixture("unreadable") };
const changed = (view: RatePathView, change: (copy: any) => void): unknown => {
  const copy = structuredClone(view);
  change(copy);
  return copy;
};

test("every served state reads, bound to its own capture", () => {
  for (const [name, view] of Object.entries(states)) {
    assert.ok(isRatePathView(view, view.capture_id), name);
    assert.equal(view.meeting_specific.state, "unavailable", name);
    assert.equal(isRatePathView(view, "20260101T000000000000Z-000000000000"), false, name);
  }
  assert.equal(available.state, "available");
  assert.equal(states["no-coverage"].state, "no_coverage");
  assert.equal(states["not-prepared"].state, "not_prepared");
  assert.equal(states.unreadable.state, "unreadable");
});

test("basis points become percent by an exact decimal shift, as the server computes it", () => {
  const cases: [string, string][] = [["315.50", "3.1550"], ["5.00", "0.0500"], ["300", "3.00"], ["-12.25", "-0.1225"],
    ["1234.5", "12.345"], ["0.00", "0.0000"], ["10.00", "0.1000"], ["-0.50", "-0.0050"]];
  for (const [bp, percent] of cases) assert.equal(shiftPercent(bp), percent, bp);
  for (const bad of ["", "4,25", "1e3", "+4.25", " 4.25", "NaN"]) assert.equal(shiftPercent(bad), null, bad);
  for (const window of available.windows) {
    for (const item of Object.values(window.statistics)) {
      if (item) assert.equal(item.percent, shiftPercent(item.bp));
    }
  }
});

test("the observation precedes the publication date and the windows are the first four, in order", () => {
  const selection = available.selection!;
  assert.ok(selection.observation_date! < selection.publication_new_york_date);
  assert.equal(selection.publication_new_york_date, available.publication.new_york_date);
  assert.ok(available.windows.length <= MAX_WINDOWS);
  const starts = available.windows.map((window) => window.reference_start);
  assert.deepEqual(starts, [...starts].sort());
  assert.equal(JSON.stringify(available.windows).toLowerCase().includes("prob"), false);
});

test("a reply that breaks the view's rules is refused as a whole", () => {
  const broken: Record<string, (copy: any) => void> = {
    "rounded percent": (copy) => { copy.windows[0].statistics.mean.percent = "3.16"; },
    "basis points unlike the raw cell": (copy) => { copy.windows[0].statistics.mean.bp = "315.60"; },
    "same-day observation": (copy) => {
      copy.selection.observation_date = copy.selection.publication_new_york_date;
      copy.selection.calendar_days_before = 0;
    },
    "observation after publication": (copy) => { copy.selection.observation_date = "2026-09-17"; },
    "miscounted days": (copy) => { copy.selection.calendar_days_before = 2; },
    "windows out of order": (copy) => { copy.windows.reverse(); },
    "a fifth window": (copy) => {
      copy.windows.push({ ...copy.windows[3], reference_start: "2027-12-15" });
      copy.windows_listed = 5;
    },
    "windows listed disagree": (copy) => { copy.windows_listed = 3; },
    "a probability in a window": (copy) => { copy.windows[0].statistics.prob_cut = null; },
    "percentiles crossed": (copy) => {
      copy.windows[0].statistics.p25 = { ...copy.windows[0].statistics.p75 };
      copy.windows[0].statistics.p75 = { bp: "100.00", percent: "1.0000", raw: " 100.00", row: 9 };
    },
    "meeting pricing claimed": (copy) => { copy.meeting_specific.state = "available"; },
    "an HTTP status never recorded": (copy) => { copy.provenance.http_status = 200; },
    "a provider call": (copy) => { copy.provider_called = true; },
    "a write": (copy) => { copy.written = true; },
    "target range text": (copy) => { copy.target_range.raw = "3.00% - 3.25%"; },
    "target range percent": (copy) => { copy.target_range.percent = ["3", "3.25"]; },
    "another record version": (copy) => { copy.provenance.record_version = 2; },
    "license without its statement": (copy) => { copy.license.paragraphs = ["SYNTHETIC"]; },
    "another view version": (copy) => { copy.view_version = "rate-path-view-0.2"; },
    "a problem beside values": (copy) => { copy.problem = "SYNTHETIC"; },
  };
  for (const [name, change] of Object.entries(broken)) {
    assert.equal(isRatePathView(changed(available, change)), false, name);
  }
  assert.equal(isRatePathView(changed(states.unreadable, (copy) => { copy.problem = null; })), false);
  assert.equal(isRatePathView(changed(states["not-prepared"], (copy) => { copy.provenance = available.provenance; })),
               false);
  assert.equal(isRatePathView(changed(states["no-coverage"], (copy) => { copy.windows = available.windows; })), false);
  assert.equal(isRatePathView(changed(states["no-coverage"], (copy) => { copy.selection.reason = null; })), false);
});

test("the strip places every window's range on one shared scale; the command is the explicit local one", () => {
  const place = strip(available.windows);
  const bars = available.windows.map(place);
  assert.ok(bars.every((bar) => bar && bar.low <= (bar.mean ?? bar.low) && bar.low <= bar.high));
  assert.equal(Math.min(...bars.map((bar) => bar!.low)), 0);
  assert.equal(Math.max(...bars.map((bar) => bar!.high)), 100);
  assert.equal(prepareCommand("ID"), "python -m second_order rate-context prepare --capture ID");
});
