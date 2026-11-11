// The Situation Now wording and bar geometry (fuelsSituation.ts), the signed money and lead-sentence helpers
// (fuelsText.ts), and a copy lint over every fixed string of the Stage 2 sections, on captured SYNTHETIC replies.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import type { RowView, SituationView, SplitView, WindowView } from "../src/fuels.ts";
import * as situationModule from "../src/fuelsSituation.ts";
import {
  CANNOT_ALWAYS, canSay, cannotSay, labelLineIsExplanation, levelText, mainWindow, MECHANISMS_NOTE, mechanismSources,
  mechanismsNote, METHOD_COPY, newerText, NO_COMPARISON, SITUATION_COPY, splitBar, splitDescription, splitScale,
  staleText, summaryLine, TRANSMISSION_COPY, unavailableText, WINDOW_LABEL, windowDates,
} from "../src/fuelsSituation.ts";
import * as textModule from "../src/fuelsText.ts";
import { GLOSSARY, leadAndRest, signedMoney } from "../src/fuelsText.ts";

const MINUS = "−";
const LABELS = ["unchanged", "offsetting", "mostly_crude", "mostly_crack", "both"] as const;
const IDS = ["previous", "week", "month"] as const;
const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf-8");
const fixture = (name: string) => JSON.parse(read(`./fixtures/${name}`));
const situation = (name = "fuels-view.json"): SituationView => fixture(name).situation;
const windowOf = (id: string, name = "fuels-view.json"): WindowView =>
  situation(name).windows.find((w) => w.id === id) as WindowView;
const unavailable = (w: WindowView): WindowView =>
  ({ ...w, state: "unavailable", reason: "No common observation within 3 days before 27 Oct 2026", from: null,
     rows: null, split: null });
const pair = (value: string) => ({ value, shown: value });
const split = (crude: string, crack: string, basket: string, label: SplitView["label"]): SplitView =>
  ({ crude: pair(crude), crack: pair(crack), basket: pair(basket), gasoline_part: pair("0"), diesel_part: pair("0"),
     label });
const NOT_WRITTEN = { state: "not_written" } as const;
const reviewedOn = (part: any, day: string | null = "2026-11-20") => ({ ...part, review: { state: "reviewed",
  reviewed_on: day } });
const byOwner = (part: any) => ({ ...part, author: "Owner" });
/** The mechanism files in every author, review and written state the note must word correctly. */
const noteCases = (view: any): Record<string, [any, any]> => {
  const [d, t] = [view.drivers, view.transmission];
  return { drafts: [d, t], reviewed: [reviewedOn(d), reviewedOn(t)], undated: [reviewedOn(d, null), reviewedOn(t, null)],
    owner: [byOwner(d), byOwner(t)], mixed: [reviewedOn(d), t], driversOnly: [d, NOT_WRITTEN],
    transmissionOnly: [NOT_WRITTEN, reviewedOn(t)], none: [NOT_WRITTEN, NOT_WRITTEN] };
};
const near = (actual: number, expected: number, what: string) =>
  assert.ok(Math.abs(actual - expected) < 1e-9, `${what}: ${actual} is not ${expected}`);

test("signedMoney marks a rise with plus, a fall with the true minus sign, and no change with neither", () => {
  assert.equal(signedMoney("6.54"), "+$6.54");
  assert.equal(signedMoney("-0.04"), `${MINUS}$0.04`);
  assert.equal(signedMoney("0.00"), "$0.00");
  assert.equal(signedMoney("-0.00"), "$0.00");
  assert.equal(signedMoney("-0.001"), `${MINUS}$0.001`);
});

test("leadAndRest splits at the first sentence end and loses no text", () => {
  assert.deepEqual(leadAndRest("Oil demand tends to rise. It varies by fuel."), ["Oil demand tends to rise.",
    "It varies by fuel."]);
  assert.deepEqual(leadAndRest("One sentence only."), ["One sentence only.", ""]);
  assert.deepEqual(leadAndRest("The U.S. Energy agency publishes it. Next."), ["The U.S. Energy agency publishes it.",
    "Next."]);
  const drivers = JSON.parse(read("../../content/fuels/drivers.json"));
  const sectors = JSON.parse(read("../../content/fuels/transmission.json"));
  const texts = [...drivers.items.map((item: any) => item.mechanism), ...sectors.items.map((item: any) => item.effect_text)];
  assert.equal(texts.length, 15);
  for (const text of texts) {
    const [lead, rest] = leadAndRest(text);
    assert.match(lead, /[.!?]$/);
    assert.ok(lead.length < text.length, `the lead keeps more to say: ${lead}`);
    assert.equal(`${lead} ${rest}`, text);
  }
});

test("mainWindow takes the week when computed, else the previous observation, else nothing", () => {
  const s = situation();
  assert.equal(mainWindow(s)?.id, "week");
  const noWeek = { ...s, windows: s.windows.map((w) => (w.id === "week" ? unavailable(w) : w)) };
  assert.equal(mainWindow(noWeek)?.id, "previous");
  assert.equal(mainWindow({ ...s, windows: s.windows.map(unavailable) }), null);
  assert.equal(mainWindow(situation("fuels-view-missing.json")), null);
});

test("summaryLine is a templated label for each window and each split label, naming the window's end date", () => {
  assert.equal(summaryLine(windowOf("week")),
    "Over about a week to 3 Nov 2026, the basket's change was mostly in the crack.");
  assert.equal(summaryLine(windowOf("previous")),
    "From the previous observation to 3 Nov 2026, Brent and the crack moved in opposite directions.");
  const month = windowOf("month");
  const withLabel = (label: SplitView["label"]) => summaryLine({ ...month, split: { ...month.split!, label } });
  assert.equal(withLabel("offsetting"), "Over about a month to 3 Nov 2026, Brent and the crack moved in opposite directions.");
  assert.equal(withLabel("mostly_crude"), "Over about a month to 3 Nov 2026, the basket's change was mostly in Brent.");
  assert.equal(withLabel("both"),
    "Over about a month to 3 Nov 2026, the basket's change was shared between Brent and the crack.");
  assert.match(withLabel("unchanged"), /^Over about a month to 3 Nov 2026, .*the basket did not change\.$/);
  // A stale snapshot (retrieved 20 Nov) still names its own end date, so it never reads as the past week.
  assert.match(summaryLine(windowOf("week", "fuels-view-stale.json")), /^Over about a week to 3 Nov 2026, /);
  const lines = LABELS.map(withLabel);
  assert.equal(new Set(lines).size, LABELS.length);
  assert.deepEqual(WINDOW_LABEL, { previous: "Since the previous observation", week: "About a week",
    month: "About a month" });
});

test("canSay fills the window's numbers per barrel, with the true minus sign for a fall", () => {
  const previous = canSay(windowOf("previous"));
  assert.equal(previous[0], `Over this window the basket moved ${MINUS}$0.04/bbl: +$0.96/bbl with Brent and `
    + `${MINUS}$1.00/bbl with the crack.`);
  assert.ok(previous.join(" ").includes(`${MINUS}$0.03/bbl from gasoline`), previous.join(" | "));
  assert.equal(canSay(windowOf("week"))[0],
    "Over this window the basket moved +$6.54/bbl: +$1.74/bbl with Brent and +$4.80/bbl with the crack.");
  const flat = { ...windowOf("week"), split: split("0.00", "0.00", "0.00", "unchanged") };
  assert.equal(canSay(flat)[0],
    "Over this window the basket moved $0.00/bbl: $0.00/bbl with Brent and $0.00/bbl with the crack.");
  assert.ok(canSay(windowOf("previous")).every((line) => !/(?<!\d)-[$\d]/.test(line)), "a hyphen-minus is never a sign");
  assert.deepEqual(canSay(unavailable(windowOf("week"))), []);
});

test("canSay's product line says the parts are per barrel of crude at the weights, and when rounding shows", () => {
  const week = windowOf("week");
  const line = canSay(week)[1];
  assert.match(line, /\/bbl from gasoline and .*\/bbl from diesel, at the 3-2-1 weights: 28 times gasoline's \$\/gal change and 14 times diesel's\.$/);
  assert.doesNotMatch(line, /by a cent/);
  const parts = { ...(week.split as SplitView), gasoline_part: pair("0.08"), diesel_part: pair("0.01"),
    basket: pair("0.10") };
  assert.match(canSay({ ...week, split: parts })[1], /Rounded for display, the two parts differ from the basket's change by a cent\.$/);
});

test("levels and change titles use the true minus sign, never a hyphen", () => {
  const row = { from: pair("33.00"), to: pair("-3.00"), change: pair("-36.00"), pct: null };
  assert.equal(levelText(row), `33.00 → ${MINUS}3.00`);
  const badge = (situationModule as any).figureBadge("crack", "change", row);
  assert.equal(badge.title, `Computed from 33.00 to ${MINUS}3.00 $/bbl`);
});

test("every label line in What it shows carries a badge: E when it points to the drivers, else C", () => {
  const kindOf = (situationModule as any).labelLineKind as ((label: string) => string) | undefined;
  assert.equal(typeof kindOf, "function", "fuelsSituation.ts exports labelLineKind");
  assert.deepEqual(LABELS.map((label) => kindOf!(label)),
    ["computed", "computed", "explanation", "explanation", "explanation"]);
  assert.doesNotMatch(cannotSay("offsetting")[3], /lag|reasons of their own/);
});

test("canSay's label line uses the drivers' own vocabulary and claims no cause", () => {
  const week = windowOf("week");
  const labelLine = (label: SplitView["label"]) => canSay({ ...week, split: { ...week.split!, label } })[2];
  assert.equal(labelLine("mostly_crack"), "A change mostly in the crack is consistent with drivers that act mainly on "
    + "the crack, or on both (see Market Drivers); this does not show that any of them moved it.");
  assert.equal(labelLine("mostly_crude"), "A change mostly in Brent is consistent with drivers that act mainly on "
    + "crude, or on both (see Market Drivers); this does not show that any of them moved it.");
  assert.match(labelLine("both"), /act mainly on crude, on the crack, or on both \(see Market Drivers\); this does not /);
  for (const label of ["mostly_crude", "mostly_crack"] as const) {
    assert.match(cannotSay(label)[3], /acts mainly on/);
  }
});

test("only the label lines that point to the Market Drivers are possible explanations (an E badge)", () => {
  assert.deepEqual(LABELS.filter(labelLineIsExplanation), ["mostly_crude", "mostly_crack", "both"]);
  const week = windowOf("week");
  for (const label of LABELS) {
    const last = canSay({ ...week, split: { ...week.split!, label } }).at(-1) ?? "";
    assert.equal(labelLineIsExplanation(label), last.includes("(see Market Drivers)"), label);
  }
});

test("the levels at both dates read from and to as shown, so a phone shows them without hovering", () => {
  const previous = windowOf("previous");
  assert.equal(levelText(previous.rows!.brent), "79.04 → 80.00");
  assert.equal(levelText(previous.rows!.gasoline), "2.501 → 2.500");
  assert.equal(levelText(previous.rows!.basket), `${previous.rows!.basket.from.shown} → ${previous.rows!.basket.to.shown}`);
  assert.equal(SITUATION_COPY.levelsSummary, "Levels at both dates");
  assert.doesNotMatch(SITUATION_COPY.levelsSummary + SITUATION_COPY.levelsLabel + SITUATION_COPY.levelsTitle, /\d/);
});

test("a published level is P and a computed change is C: the spot prices are published, the basket and crack computed", () => {
  type Badge = { kind: string; title: string };
  const figureBadge = (situationModule as Record<string, unknown>).figureBadge as
    ((name: string, what: "level" | "change", row: RowView) => Badge) | undefined;
  assert.equal(typeof figureBadge, "function", "fuelsSituation.ts exports figureBadge");
  const rows = windowOf("previous").rows!;
  for (const name of ["brent", "gasoline", "diesel"] as const) {
    const level = figureBadge!(name, "level", rows[name]);
    const change = figureBadge!(name, "change", rows[name]);
    assert.equal(level.kind, "published", `${name} level`);
    assert.match(level.title, /^Published by EIA/, `${name} level title`);
    assert.equal(change.kind, "computed", `${name} change`);
    assert.ok(change.title.startsWith(`Computed from ${rows[name].from.shown} to ${rows[name].to.shown}`),
      `${name} change title names both levels: ${change.title}`);
  }
  for (const name of ["basket", "crack"] as const) {
    for (const what of ["level", "change"] as const) {
      const badge = figureBadge!(name, what, rows[name]);
      assert.equal(badge.kind, "computed", `${name} ${what}`);
      assert.match(badge.title, /^Computed/, `${name} ${what} title`);
    }
  }
  // Kind uses the title as the accessible name too, so a published level's name must never say computed.
  assert.doesNotMatch(SITUATION_COPY.levelsPublishedTitle, /comput/i);
  assert.doesNotMatch(SITUATION_COPY.levelsPublishedTitle + SITUATION_COPY.levelsTitle, /\d/);
});

test("the fixed copy says what the review asked: the verified prices, a rise in the starting price, where S appears", () => {
  assert.equal(SITUATION_COPY.kicker, "Situation now · computed from the verified prices");
  assert.ok(TRANSMISSION_COPY.intro.includes("Effects are stated for a rise in the starting price; a fall tends to work in "
    + "reverse, though not always symmetrically."), TRANSMISSION_COPY.intro);
  const where = "Only the situation note at the top carries such claims, attributed in its text; none in the sections below.";
  assert.equal(METHOD_COPY.sourced, `a sourced claim, attributed to a named source with its date. ${where}`);
  assert.ok(GLOSSARY.Kinds.includes("S a sourced claim, attributed to a named source with its date (only the situation "
    + "note at the top carries such claims, attributed in its text; none in the sections below);"), GLOSSARY.Kinds);
  for (const text of [METHOD_COPY.sourced, GLOSSARY.Kinds]) assert.doesNotMatch(text, /connected yet/);
});

test("cannotSay always holds the three fixed lines, then one line for the label", () => {
  assert.equal(CANNOT_ALWAYS.length, 3);
  assert.match(CANNOT_ALWAYS[0], /identity/);
  assert.match(CANNOT_ALWAYS[0], /not say why/);
  assert.match(CANNOT_ALWAYS[1], /gross benchmark/);
  assert.match(CANNOT_ALWAYS[1], /not a refiner's margin/);
  assert.match(CANNOT_ALWAYS[2], /whether a move will continue/);
  const own = new Set<string>();
  for (const label of LABELS) {
    const lines = cannotSay(label);
    assert.equal(lines.length, 4);
    assert.deepEqual(lines.slice(0, 3), [...CANNOT_ALWAYS]);
    own.add(lines[3]);
  }
  assert.equal(own.size, LABELS.length);
});

test("splitBar: same-sign parts stack from the zero line, to scale", () => {
  const s = split("1.74", "4.798", "6.538", "mostly_crack");
  const scale = splitScale([s], 300);
  assert.deepEqual(scale, { width: 300, neg: 0, pos: 6.538 });
  const bar = splitBar(s, scale);
  near(bar.zeroX, 0, "zero");
  near(bar.crude.x, 0, "crude x");
  near(bar.crude.w, (1.74 / 6.538) * 300, "crude width");
  near(bar.crack.x, bar.crude.x + bar.crude.w, "crack starts where crude ends");
  near(bar.crack.w, (4.798 / 6.538) * 300, "crack width");
  near(bar.crack.w / bar.crude.w, 4.798 / 1.74, "the widths keep the parts' ratio");
  near(bar.netX, 300, "the net sits at the basket change");
  const down = splitBar(split("-2", "-1", "-3", "both"), { width: 300, neg: 3, pos: 0 });
  near(down.zeroX, 300, "zero on the right when every part falls");
  near(down.crude.x, 100, "crude runs left from zero");
  near(down.crude.w, 200, "crude width");
  near(down.crack.x, 0, "crack continues left of crude");
  near(down.crack.w, 100, "crack width");
  near(down.netX, 0, "net");
});

test("splitBar: offsetting parts pull in opposite directions from the zero line", () => {
  const s = split("0.96", "-1.002", "-0.042", "offsetting");
  const scale = splitScale([s], 300);
  assert.deepEqual(scale, { width: 300, neg: 1.002, pos: 0.96 });
  const bar = splitBar(s, scale);
  const k = 300 / (1.002 + 0.96);
  near(bar.zeroX, 1.002 * k, "zero");
  near(bar.crude.x, bar.zeroX, "crude starts at zero");
  near(bar.crude.w, 0.96 * k, "crude width");
  near(bar.crack.x + bar.crack.w, bar.zeroX, "crack ends at zero");
  near(bar.crack.w, 1.002 * k, "crack width");
  near(bar.netX, bar.zeroX - 0.042 * k, "the net sits just left of zero");
});

test("splitBar: one scale serves every window, and a zero change draws nothing", () => {
  const splits = situation().windows.map((w) => w.split as SplitView);
  const scale = splitScale(splits, 320);
  assert.deepEqual(scale, { width: 320, neg: 3.87, pos: 6.538 });
  const bars = splits.map((s) => splitBar(s, scale));
  for (const bar of bars) {
    near(bar.zeroX, (3.87 / (3.87 + 6.538)) * 320, "one zero line for all");
    for (const part of [bar.crude, bar.crack]) {
      assert.ok(part.w >= 0 && part.x >= -1e-9 && part.x + part.w <= 320 + 1e-9, JSON.stringify(part));
    }
  }
  near(bars[1].crude.w / bars[0].crude.w, 1.74 / 0.96, "widths compare across windows");
  const flat = split("0", "0", "0", "unchanged");
  const still = splitBar(flat, splitScale([flat], 320));
  assert.deepEqual([still.crude.w, still.crack.w], [0, 0]);
  near(still.zeroX, 160, "an all-zero scale centres the zero line");
  near(still.netX, 160, "net on zero");
});

test("the notes, dates and descriptions name their dates and numbers in words", () => {
  const stale = situation("fuels-view-stale.json");
  const note = staleText(stale, fixture("fuels-view-stale.json").snapshot.retrieved_at);
  assert.match(note ?? "", /17 days/);
  assert.match(note ?? "", /3 Nov 2026/);
  assert.match(note ?? "", /EIA weekly cycle/);
  assert.equal(staleText(situation(), fixture("fuels-view.json").snapshot.retrieved_at), null);
  assert.equal(newerText("Brent spot", "2026-11-05", "2026-11-03"),
    "Brent spot has a newer observation, 5 Nov 2026; the comparison stays on 3 Nov 2026, the latest date Brent, "
    + "gasoline and diesel share.");
  assert.equal(windowDates(windowOf("week")), "27 Oct 2026 → 3 Nov 2026");
  const gone = unavailable(windowOf("week"));
  assert.equal(unavailableText(gone), "No common observation within 3 days before 27 Oct 2026.");
  assert.equal(unavailableText({ ...gone, reason: "Already ends." }), "Already ends.");
  const described = splitDescription(windowOf("previous"));
  for (const part of ["Since the previous observation", "2 Nov 2026", "3 Nov 2026", `${MINUS}$0.04`, "+$0.96",
    `${MINUS}$1.00`, "zero", "dollars per barrel"]) {
    assert.ok(described.includes(part), `${part} in ${described}`);
  }
});

test("the mechanism note follows each file's author and review, and every source is listed once", () => {
  const view = fixture("fuels-view.json");
  const note = Object.fromEntries(Object.entries(noteCases(view)).map(([name, [d, t]]) => [name, mechanismsNote(d, t)]));
  const tail = "they are not findings about the current move.";
  assert.equal(note.drafts, "Drivers and transmission chains are general economic mechanisms drafted with AI and not "
    + `yet reviewed by the owner; ${tail}`);
  assert.equal(note.reviewed, "Drivers and transmission chains are general economic mechanisms drafted with AI and "
    + `reviewed by the owner on 20 Nov 2026; ${tail}`);
  assert.equal(note.undated, "Drivers and transmission chains are general economic mechanisms drafted with AI and "
    + `reviewed by the owner; ${tail}`);
  assert.equal(note.owner, `Drivers and transmission chains are general economic mechanisms written by the owner; ${tail}`);
  assert.equal(note.mixed, "Drivers are general economic mechanisms drafted with AI and reviewed by the owner on 20 Nov "
    + "2026; transmission chains are general economic mechanisms drafted with AI and not yet reviewed by the owner. "
    + "Neither is a finding about the current move.");
  assert.equal(note.driversOnly, "Drivers are general economic mechanisms drafted with AI and not yet reviewed by the "
    + `owner; ${tail} Transmission chains have not been written yet.`);
  assert.equal(note.transmissionOnly, "Transmission chains are general economic mechanisms drafted with AI and reviewed "
    + `by the owner on 20 Nov 2026; ${tail} Drivers have not been written yet.`);
  assert.equal(note.none, "Drivers and transmission chains have not been written yet.");
  const listed = mechanismSources(view.drivers, view.transmission);
  const all = [...view.drivers.items, ...view.transmission.items].flatMap((item: any) => item.sources);
  assert.equal(new Set(listed.map((entry) => entry.source.url)).size, listed.length);
  assert.equal(listed.length, new Set(all.map((source: any) => source.url)).size);
  const outages = listed.find((entry) => entry.source.title.startsWith("Refinery Outages"));
  assert.deepEqual(outages?.citedBy, ["Refining capacity, utilization and outages", "Seasonality in the Northern Hemisphere"]);
  assert.deepEqual(mechanismSources({ state: "not_written" }, { state: "not_written" }), []);
});

// The refused phrases of the Global Constraints, as second_order/fuels_mechanisms.py writes them (word-bounded, any
// case, any whitespace inside a phrase).
const REFUSED = ["caused", "causes", "drove", "driven by", "due to", "because of", "as a result of", "led to", "triggered",
  "will rise", "will fall", "will increase", "will decrease", "forecast", "expect", "expects", "expected"];
const REFUSED_PATTERN = new RegExp(`(?<!\\w)(?:${REFUSED.map((p) => p.split(" ").join("\\s+")).join("|")})(?!\\w)`, "i");
/** The AFFIRMATIVE list of tests/browser/fuels-check.mjs (the Stage 1 page check, which scans every page load), read
 * from its source so the two never drift: flagless /.../ literals, where a "/" inside a class or after a backslash does
 * not end one. Throws when the list is missing or empty. */
function readPageCheck(source: string): RegExp[] {
  const body = /const AFFIRMATIVE = \[([\s\S]*?)\r?\n\];/.exec(source)?.[1];
  if (body === undefined) throw new Error("fuels-check.mjs has no AFFIRMATIVE list");
  const patterns: RegExp[] = [];
  for (let index = 0; index < body.length; index++) {
    if (body[index] !== "/") continue;
    let text = "";
    let inClass = false;
    for (index++; body[index] !== "/" || inClass; index++) {
      if (body[index] === "\\") {
        text += body.slice(index, index + 2);
        index++;
        continue;
      }
      inClass = (inClass || body[index] === "[") && body[index] !== "]";
      text += body[index];
    }
    patterns.push(new RegExp(text));
  }
  if (patterns.length === 0) throw new Error("the AFFIRMATIVE list of fuels-check.mjs holds no pattern");
  return patterns;
}
const PAGE_CHECK = readPageCheck(read("./browser/fuels-check.mjs"));
const findings = (text: string) => {
  const lowered = text.toLowerCase().replace(/\s+/g, " ");
  return [...(REFUSED_PATTERN.test(text) ? [`refused: ${REFUSED_PATTERN.exec(text)?.[0]}`] : []),
    ...PAGE_CHECK.filter((pattern) => pattern.test(lowered)).map(String)];
};
const stringsIn = (value: unknown): string[] => {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(stringsIn);
  if (value && typeof value === "object") return Object.values(value).flatMap(stringsIn);
  return [];
};

test("the glossary's Kinds entry lists all six kinds, as the legend does", () => {
  const kinds = GLOSSARY.Kinds;
  const parts = ["P measured", "C computed", "E a possible explanation", "S a sourced claim", "A your assumption",
    "M missing"];
  for (const part of parts) assert.ok(kinds.includes(part), `${part} in ${kinds}`);
  assert.deepEqual(parts.map((part) => kinds.indexOf(part)), parts.map((part) => kinds.indexOf(part)).sort((a, b) => a - b));
});

test("the page check's phrasings are read from the browser check, never copied", () => {
  assert.ok(PAGE_CHECK.length >= 20, String(PAGE_CHECK.length));
  assert.equal(String(PAGE_CHECK[0]), String(/\b(?:we|i) (?:recommend|suggest|advise)\b/));
  assert.equal(String(PAGE_CHECK.at(-1)), String(/\btoday\b/));
  assert.deepEqual(readPageCheck("const AFFIRMATIVE = [\r\n  /a[/]b\\/c/, /\\bd\\b/,\r\n];").map(String),
    [String(/a[/]b\/c/), String(/\bd\b/)]);
  assert.throws(() => readPageCheck("const OTHER = [\n  /a/,\n];"));
  assert.throws(() => readPageCheck("const AFFIRMATIVE = [\n  'a',\n];"));
});

test("the copy lint finds the refused phrases and the page check's phrasings", () => {
  for (const bad of ["The crack drove it", "Prices were DRIVEN  BY demand", "Analysts expect more", "Brent today",
    "the upside case", "higher prices", "a move due to OPEC"]) {
    assert.ok(findings(bad).length > 0, bad);
  }
  for (const fine of ["unexpectedly", "forecasting desk", "the leader", "an expectation"]) {
    assert.equal(findings(fine).length, 0, fine);
  }
});

test("copy lint: no fixed string of the fuels page uses a refused phrase, the page check's phrasings or today", () => {
  const view = fixture("fuels-view.json");
  const generated = [
    ...IDS.flatMap((id) => LABELS.map((label) => {
      const w = windowOf(id);
      return { ...w, split: { ...(w.split as SplitView), label } };
    })).flatMap((w) => [summaryLine(w), ...canSay(w), splitDescription(w), windowDates(w)]),
    ...LABELS.flatMap(cannotSay),
    staleText(situation("fuels-view-stale.json"), fixture("fuels-view-stale.json").snapshot.retrieved_at) ?? "",
    newerText("Brent spot", "2026-11-05", "2026-11-03"),
    unavailableText(unavailable(windowOf("week"))),
    ...IDS.flatMap((id) => [splitDescription(unavailable(windowOf(id))), summaryLine(unavailable(windowOf(id)))]),
    ...Object.values(noteCases(view)).map(([d, t]) => mechanismsNote(d, t)),
  ];
  const fixed = [...stringsIn(Object.values(situationModule)), ...stringsIn(Object.values(textModule))];
  assert.ok(fixed.length > 40, `the modules export their copy (${fixed.length} strings)`);
  for (const text of [NO_COMPARISON, MECHANISMS_NOTE.reviewed, ...Object.values(MECHANISMS_NOTE)]) {
    assert.ok(fixed.includes(text), `the lint covers "${text}"`);
  }
  assert.ok(generated.includes(`About a month: No common observation within 3 days before 27 Oct 2026.`));
  const hits = [...fixed, ...generated].flatMap((text) => findings(text).map((hit) => `${hit} in "${text}"`));
  assert.deepEqual(hits, []);
});

test("copy lint: the Stage 2 components and the page source hold no refused phrase, page-check phrasing or today", () => {
  const files = ["FuelsSituation.tsx", "FuelsDrivers.tsx", "FuelsTransmission.tsx", "FuelsBits.tsx"]
    .map((name) => `../src/components/${name}`).concat("../src/pages/FuelsPage.tsx");
  const hits = files.flatMap((file) => findings(read(file)).map((hit) => `${hit} in ${file}`));
  assert.deepEqual(hits, []);
});
