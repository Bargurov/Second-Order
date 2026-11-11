// The fuels page's Stage 2 wording (spec 2026-11-06-fuels-stage-2-design.md, sections 3, 4 and 7): the Situation Now
// summary, what it can and cannot show, its notes and its to-scale split bars, then the fixed copy of the Market
// Drivers, Economic Transmission and Method additions. Pure functions over the checked reply (fuels.ts): every figure
// printed here is a shown text the reader has already recomputed, nothing here rounds, and the bar geometry is for
// drawing only. The copy is general and conditional: a split is an identity, never a cause.
import { formatDay } from "./format.ts";
import type {
  DriverItem, MechanismFile, RowView, SectorItem, SituationView, SourceItem, SplitView, WindowView,
} from "./fuels.ts";
import { changeMoney, lastPlace, level, under } from "./fuelsText.ts";

type Label = SplitView["label"];
type WindowId = WindowView["id"];

/** The windows by name, as the table and the bars head them. */
export const WINDOW_LABEL = {
  previous: "Since the previous observation", week: "About a week", month: "About a month",
} as const;
/** The summary's lead names the window's end date, so an old snapshot never reads as the past week. */
const WINDOW_LEAD: Record<WindowId, (to: string) => string> = {
  previous: (to) => `From the previous observation to ${to}`,
  week: (to) => `Over about a week to ${to}`,
  month: (to) => `Over about a month to ${to}`,
};
const SUMMARY: Record<Label, string> = {
  unchanged: "neither Brent nor the crack changed, so the basket did not change.",
  offsetting: "Brent and the crack moved in opposite directions.",
  mostly_crude: "the basket's change was mostly in Brent.",
  mostly_crack: "the basket's change was mostly in the crack.",
  both: "the basket's change was shared between Brent and the crack.",
};
/** The summary's ending when its window has no split. */
export const NO_COMPARISON = "there is no valid comparison.";
const CAN_LABEL: Record<Label, string> = {
  unchanged: "Brent and the crack did not change over this window, so there is nothing to split.",
  offsetting: "Brent and the crack moved in opposite directions, so the basket did not follow Brent one for one over "
    + "this window.",
  mostly_crude: "A change mostly in Brent is consistent with drivers that act mainly on crude, or on both (see Market "
    + "Drivers); this does not show that any of them moved it.",
  mostly_crack: "A change mostly in the crack is consistent with drivers that act mainly on the crack, or on both (see "
    + "Market Drivers); this does not show that any of them moved it.",
  both: "A change shared between Brent and the crack is consistent with drivers that act mainly on crude, on the "
    + "crack, or on both (see Market Drivers); this does not show that any of them moved it.",
};
/** What the split can never show, whatever its label (spec section 4). */
export const CANNOT_ALWAYS = [
  "The split is an accounting identity: the basket's change equals Brent's change plus the crack's change. It does "
    + "not say why either part moved.",
  "The crack is a gross benchmark spread, not a refiner's margin: it leaves out refining costs and each refinery's "
    + "own crude and product mix.",
  "Nothing here says whether a move will continue.",
] as const;
const CANNOT_LABEL: Record<Label, string> = {
  unchanged: "It does not show that the market was still: gasoline and diesel can move in opposite directions and "
    + "leave the basket unchanged.",
  offsetting: "It does not show that one part pulled the other, or why the two parts moved apart.",
  mostly_crude: "It does not show that any driver moved Brent: a driver that acts mainly on crude and a move in Brent "
    + "over the same window can coincide without one producing the other.",
  mostly_crack: "It does not show that any driver moved the crack: a driver that acts mainly on the crack and a move "
    + "in the crack over the same window can coincide without one producing the other.",
  both: "It does not show whether the two parts share a driver: Brent and the crack can move the same way for "
    + "unrelated reasons.",
};

/** Situation Now's fixed copy. The kicker, title and intro carry no digit, so a withheld section shows no number. */
export const SITUATION_COPY = {
  kicker: "Situation now · computed from the verified prices",
  title: "What moved, and over which window",
  intro: "Changes in the three spot prices, the basket and the crack over three windows, on the dates all three "
    + "inputs share. The basket's change is then split into the part that went with Brent and the part that went "
    + "with the crack: an accounting identity, not a cause.",
  noWindow: "None of the three windows has a valid comparison yet, so there is nothing to split.",
  tableLabel: "Changes over each window, with the percent change in small type where it is defined",
  columns: { window: "Window", brent: "Brent", gasoline: "Gasoline", diesel: "Diesel", basket: "Basket", crack: "Crack" },
  units: { brent: "$/bbl", gasoline: "$/gal", diesel: "$/gal", basket: "$/bbl", crack: "$/bbl" },
  cellTitle: "Computed from",
  levelsSummary: "Levels at both dates",
  levelsLabel: "The values each window compares, from its start date to its end date",
  levelsPublishedTitle: "Published by EIA: the spot price on the window's start and end dates, as EIA's file held it "
    + "when retrieved",
  levelsTitle: "Computed: the basket or crack on the window's start and end dates, from the three published prices",
  splitHead: "The basket's change, split, in $/bbl",
  barKey: "Each bar is drawn to one scale from the zero line. The dark hatch is the part that went with Brent and the "
    + "mustard hatch the part that went with the crack; a part below zero runs left of the line, and the mark under "
    + "the bar is the basket's change.",
  parts: { crude: "Brent", crack: "Crack", basket: "Basket" },
  canSummary: "What this shows and what it cannot show",
  canHead: "What it shows",
  cannotHead: "What it cannot show",
  computedTitle: "Computed by fixed code from the verified prices",
  labelTitle: "Computed: the split label follows fixed rules",
  ageTitle: "Computed: days from the latest common observation to the retrieval",
  small: "+<0.01 or −<0.01: a rise or a fall smaller than the last shown place, kept exact in the arithmetic and the "
    + "label; 0.00 is no change.",
} as const;

/** The window the summary speaks for: the week when it is computed, else the previous observation, else none. */
export function mainWindow(s: SituationView): WindowView | null {
  if (s.state !== "computed") return null;
  const computed = (id: WindowId) => s.windows.find((w) => w.id === id && w.state === "computed" && w.split) ?? null;
  return computed("week") ?? computed("previous");
}

const PART_NAME = { crude: "Brent", crack: "the crack" } as const;

/** "the crack fell by less than $0.01" for each of the split's two parts that is not zero but shows as zero. */
function smallParts(split: SplitView): string[] {
  return (["crude", "crack"] as const).flatMap((part) => {
    const direction = under(split[part]);
    return direction ? [`${PART_NAME[part]} ${direction < 0 ? "fell" : "rose"} by less than `
      + `$${lastPlace(split[part].shown)}`] : [];
  });
}

/** "Over about a week to 3 Nov 2026, the basket's change was mostly in the crack.": a templated label, not prose. A
 * part too small to show is named with its direction, so an offsetting label never sits beside a bare $0.00. */
export function summaryLine(w: WindowView): string {
  const lead = WINDOW_LEAD[w.id](formatDay(w.to));
  if (!w.split) return `${lead}, ${NO_COMPARISON}`;
  const small = smallParts(w.split);
  const said = SUMMARY[w.split.label];
  return `${lead}, ${small.length ? `${said.slice(0, -1)}; ${small.join(" and ")}.` : said}`;
}

/** Whether any computed window shows a change too small for its last place, so the key below the table applies. */
export function smallShown(windows: WindowView[]): boolean {
  return windows.some((w) => {
    if (!w.rows || !w.split) return false;
    const rows = Object.values(w.rows).some((row) => under(row.change) !== 0
      || (row.pct !== null && !/[1-9]/.test(row.pct.shown) && !/^-?0*\.?0*$/.test(row.change.value)));
    const split = (["crude", "crack", "basket", "gasoline_part", "diesel_part"] as const)
      .some((part) => under(w.split![part]) !== 0);
    return rows || split;
  });
}

/** A split amount in dollars per barrel of crude: "+$4.26/bbl", "−<$0.01/bbl". */
const perBarrel = (pair: { value: string; shown: string }) => `${changeMoney(pair)}/bbl`;
/** Whole cents of a shown two-decimal amount, for comparing shown sums. */
const cents = (shown: string) => Math.round(Number(shown) * 100);
/** Added to the product line when the two shown parts do not add up to the shown basket change. */
export const PRODUCT_ROUNDING = "Rounded for display, the two parts differ from the basket's change by a cent.";

/** What the window's split shows: its numbers per barrel, its product parts, then one line for its label. The product
 * parts are per barrel of crude too (28 and 14 times the per-gallon changes), so they are never read as $/gal. */
export function canSay(w: WindowView): string[] {
  const s = w.split;
  if (!s) return [];
  const rounded = cents(s.gasoline_part.shown) + cents(s.diesel_part.shown) !== cents(s.basket.shown);
  return [
    `Over this window the basket moved ${perBarrel(s.basket)}: ${perBarrel(s.crude)} with Brent and `
      + `${perBarrel(s.crack)} with the crack.`,
    `By product, the same change is ${perBarrel(s.gasoline_part)} from gasoline and `
      + `${perBarrel(s.diesel_part)} from diesel, at the 3-2-1 weights: 28 times gasoline's $/gal change and `
      + `14 times diesel's.${rounded ? ` ${PRODUCT_ROUNDING}` : ""}`,
    CAN_LABEL[s.label],
  ];
}

/** Whether the label's line (the last of canSay) is a possible explanation: the lines that point to the Market Drivers
 * say what a change is consistent with, so they carry an E badge; the unchanged and offsetting lines only restate the
 * split. */
export function labelLineIsExplanation(label: Label): boolean {
  return label === "mostly_crude" || label === "mostly_crack" || label === "both";
}

/** The badge of the label's line: E when it points to the Market Drivers, else C (it restates the fixed-rule label). */
export function labelLineKind(label: Label): "explanation" | "computed" {
  return labelLineIsExplanation(label) ? "explanation" : "computed";
}

type RowName = keyof NonNullable<WindowView["rows"]>;
/** The rows whose levels are spot prices as published; the basket and the crack are computed from them. */
const PUBLISHED_LEVELS: ReadonlySet<RowName> = new Set(["brent", "gasoline", "diesel"]);

/** One Situation Now figure's badge. A spot price's level on a date is published (P); the basket and the crack on that
 * date are computed from the three prices, and every change over a window is computed (C). The title is also the
 * badge's accessible name. */
export function figureBadge(name: RowName, what: "level" | "change", row: RowView):
  { kind: "published" | "computed"; title: string } {
  const C = SITUATION_COPY;
  if (what === "change") {
    const title = `${C.cellTitle} ${level(row.from.shown)} to ${level(row.to.shown)} ${C.units[name]}`;
    return { kind: "computed", title };
  }
  return PUBLISHED_LEVELS.has(name) ? { kind: "published", title: C.levelsPublishedTitle }
    : { kind: "computed", title: C.levelsTitle };
}

/** A row's two shown levels, "79.04 → 80.00", "33.00 → −3.00": the start and end values the window compares. */
export function levelText(row: RowView): string {
  return `${level(row.from.shown)} → ${level(row.to.shown)}`;
}

/** What it cannot show: the three fixed lines, then one line for the label. */
export function cannotSay(label: Label): string[] {
  return [...CANNOT_ALWAYS, CANNOT_LABEL[label]];
}

/** "27 Oct 2026 → 3 Nov 2026"; an unavailable window has no start. */
export function windowDates(w: WindowView): string {
  return w.from ? `${formatDay(w.from)} → ${formatDay(w.to)}` : `ending ${formatDay(w.to)}`;
}

/** Why a window is unavailable, as a sentence. */
export function unavailableText(w: WindowView): string {
  const reason = w.reason ?? "This window is unavailable";
  return /[.!?]$/.test(reason) ? reason : `${reason}.`;
}

/** The staleness note, only when the latest common observation is more than ten days before the retrieval. */
/** Under the windows: every value comes from one refresh, so an earlier date shows EIA's figure as its file held it
 * then, which EIA may have revised since it first published it. */
export function retrievalText(retrievedAt: string | null): string | null {
  if (retrievedAt === null) return null;
  return `Every value here comes from one refresh, retrieved ${formatDay(retrievedAt)}: the earlier dates show EIA's `
    + "figures as its file held them then, not necessarily as EIA first published them.";
}

export function staleText(s: SituationView, retrievedAt: string | null): string | null {
  if (!s.stale || s.age_days === null || s.date === null || retrievedAt === null) return null;
  return `The latest common observation, ${formatDay(s.date)}, is ${s.age_days} days before the retrieval on `
    + `${formatDay(retrievedAt)}: older than one EIA weekly cycle plus the usual publication lag.`;
}

/** A series whose latest observation is newer than the common date the comparison uses. */
export function newerText(label: string, date: string, common: string): string {
  return `${label} has a newer observation, ${formatDay(date)}; the comparison stays on ${formatDay(common)}, the `
    + "latest date Brent, gasoline and diesel share.";
}

/** The bar's accessible label: the window, its dates and the three figures in words. */
export function splitDescription(w: WindowView): string {
  const s = w.split;
  if (!s || !w.from) return `${WINDOW_LABEL[w.id]}: ${unavailableText(w)}`;
  return `${WINDOW_LABEL[w.id]}, from ${formatDay(w.from)} to ${formatDay(w.to)}, in dollars per barrel: the basket `
    + `moved ${changeMoney(s.basket)}, ${changeMoney(s.crude)} with Brent and ${changeMoney(s.crack)} `
    + "with the crack. Drawn to scale from a zero line; a part below zero runs left.";
}

export interface Segment { x: number; w: number }
/** A drawing `width` wide holding `neg` dollars left of the zero line and `pos` dollars right of it. */
export interface SplitScale { width: number; neg: number; pos: number }

const partsOf = (split: SplitView) => [Number(split.crude.value), Number(split.crack.value)];

/** One scale for every bar, so bars compare across windows: the widest reach on each side of zero. */
export function splitScale(splits: SplitView[], width: number): SplitScale {
  let neg = 0;
  let pos = 0;
  for (const split of splits) {
    const parts = partsOf(split);
    pos = Math.max(pos, parts.filter((v) => v > 0).reduce((a, b) => a + b, 0));
    neg = Math.max(neg, parts.filter((v) => v < 0).reduce((a, b) => a - b, 0));
  }
  return { width, neg, pos };
}

/** The split's two segments, to scale from the zero line: rises stack rightwards and falls leftwards, crude first, so
 * same-sign parts sit end to end and offsetting parts pull apart. netX marks the basket's change. */
export function splitBar(split: SplitView, scale: SplitScale): { crude: Segment; crack: Segment; zeroX: number;
  netX: number } {
  const total = scale.neg + scale.pos;
  const k = total > 0 ? scale.width / total : 0;
  const zeroX = total > 0 ? scale.neg * k : scale.width / 2;
  let right = zeroX;
  let left = zeroX;
  const place = (value: number): Segment => {
    const w = Math.abs(value) * k;
    if (value >= 0) {
      right += w;
      return { x: right - w, w };
    }
    left -= w;
    return { x: left, w };
  };
  const [crude, crack] = partsOf(split).map(place);
  return { crude, crack, zeroX, netX: zeroX + Number(split.basket.value) * k };
}

// ---------- The mechanism sections ----------

/** "Acts mainly on: …". */
export const ACTS_ON_TEXT = { crude: "crude", crack: "the crack", both: "both crude and the crack" } as const;
/** The possible effect, in words. */
export const EFFECT_TEXT = { negative: "negative", positive: "positive", mixed: "mixed" } as const;

export const SOURCE_COPY = {
  heading: "Sources",
  none: "No source attached yet",
  checked: "checked",
  prepared: "prepared",
  explanationLabel: "possible explanation",
  explanationTitle: "Possible explanation: a general mechanism stated conditionally, not a finding about the current move",
} as const;

export const DRIVERS_COPY = {
  kicker: "Market drivers · general mechanisms",
  title: "What can move crude and the crack",
  intro: "Standing economic mechanisms, each stated conditionally, with the part of the barrel it acts on mainly. They "
    + "meet the split above only as possibilities: none is a finding about the current move.",
  actsOn: "Acts mainly on",
  more: "Direction, conditions and sources",
  direction: "Possible direction",
  changesWhen: "What can change or reverse it",
  watch: "What to watch",
  notWritten: "These explanations have not been written yet.",
  eventsHead: "Current events",
} as const;

export const TRANSMISSION_COPY = {
  kicker: "Economic transmission · general mechanisms",
  title: "How a fuel price change can pass to other sectors",
  intro: "Conditional chains from a named fuel price to a sector, each with its possible effect in words, what can flip "
    + "it and how long it can take. Effects are stated for a rise in the starting price; a fall tends to work in "
    + "reverse, though not always symmetrically. One card opens at a time.",
  startsFrom: "Starts from",
  possibleEffect: "Possible effect",
  chain: "The chain",
  secondOrder: "Second-order effects",
  flipsWhen: "What can flip the direction",
  lag: "Lag",
  notSourced: "not sourced",
  notWritten: "These explanations have not been written yet.",
} as const;

export const METHOD_COPY = {
  statements: "Statements are marked too:",
  explanation: "a possible explanation, a general economic mechanism stated conditionally and not a finding about the "
    + "current move;",
  sourced: "a sourced claim, attributed to a named source with its date. Only the situation note at the top carries such "
    + "claims, attributed in its text; none in the sections below.",
  rulesHead: "Situation now: the windows and the split",
  rules: [
    "Every comparison uses the dates on which Brent, gasoline and diesel all have a value, so each row compares like "
      + "with like; the latest of them is the barrel's date.",
    "Since the previous observation compares with the common date just before it.",
    "About a week compares with the latest common date on or before seven days earlier, and only if that date is at "
      + "most three days before the target; otherwise the window is unavailable and names the target.",
    "About a month does the same from the same day of the previous month (that month's last day when it is shorter), "
      + "within five days.",
    "Prices and the basket get a percent change to one decimal, only when the starting value is above zero; the crack "
      + "gets none, since it can be zero or negative.",
    "The split is an accounting identity: the basket is Brent plus the crack, so the basket's change is Brent's change "
      + "plus the crack's change. By product it is also 28 times the change in gasoline plus 14 times the change in "
      + "diesel, both in $/gal: the 3-2-1 weights in dollars per barrel of crude.",
    "The label follows fixed rules. Unchanged: neither part moved. Offsetting: the parts moved in opposite directions. "
      + "Otherwise Brent's share of the two parts' combined size decides: mostly Brent at two thirds or more, mostly "
      + "the crack at one third or less, shared in between.",
    "Values stay exact until display and are then rounded half to even, so shown parts can differ from a shown total "
      + "by a cent.",
    "When the latest common observation is more than ten days before the retrieval, the section says so; when a "
      + "series has an observation newer than the common date, the section names it.",
  ],
  sourcesHead: "Sources of the drivers and transmission chains",
  sourcesNote: "Cited, not retained: the drafter opened each one on the day shown as checked.",
  citedIn: "cited in",
  noSources: "No mechanism source is listed.",
} as const;

/** The parts of the Method's sentence on who stands behind the mechanism content. */
export const MECHANISMS_NOTE = {
  none: "Drivers and transmission chains have not been written yet.",
  both: "Drivers and transmission chains",
  notFindings: "they are not findings about the current move.",
  neither: "Neither is a finding about the current move.",
  notWritten: "have not been written yet.",
  are: "are general economic mechanisms",
  owner: "written by the owner",
  reviewed: "drafted with AI and reviewed by the owner",
  unreviewed: "drafted with AI and not yet reviewed by the owner",
} as const;
const PART_NAMES = { drivers: ["Drivers", "drivers"], transmission: ["Transmission chains", "transmission chains"] };

/** Who stands behind a written mechanism file, as authorship() says it for a note: the owner's own text, an AI draft
 * the owner reviewed (with the day), or an AI draft not yet reviewed. */
function standing(part: { author: string; review: { state: string; reviewed_on: string | null } }): string {
  if (part.author === "Owner") return MECHANISMS_NOTE.owner;
  if (part.review.state !== "reviewed") return MECHANISMS_NOTE.unreviewed;
  const day = part.review.reviewed_on;
  return day ? `${MECHANISMS_NOTE.reviewed} on ${formatDay(day)}` : MECHANISMS_NOTE.reviewed;
}

/** The Method's sentence on the mechanism content, from each file's author and review. One sentence covers both files
 * when they stand alike; otherwise each is named, and a file not written yet is said to be so, never covered. */
export function mechanismsNote(drivers: MechanismFile<DriverItem>, transmission: MechanismFile<SectorItem>): string {
  const N = MECHANISMS_NOTE;
  const parts = [[PART_NAMES.drivers, drivers], [PART_NAMES.transmission, transmission]] as const;
  const written = parts.flatMap(([names, part]) => (part.state === "written" ? [{ names, how: standing(part) }] : []));
  const missing = parts.flatMap(([names, part]) => (part.state === "written" ? [] : [names]));
  if (written.length === 0) return N.none;
  if (written.length === 2) {
    const [first, second] = written;
    if (first.how === second.how) return `${N.both} ${N.are} ${first.how}; ${N.notFindings}`;
    return `${first.names[0]} ${N.are} ${first.how}; ${second.names[1]} ${N.are} ${second.how}. ${N.neither}`;
  }
  return `${written[0].names[0]} ${N.are} ${written[0].how}; ${N.notFindings} ${missing[0][0]} ${N.notWritten}`;
}

export interface CitedSource { source: SourceItem; citedBy: string[] }

/** Every mechanism source once (by address), in reading order, with the drivers and sectors that cite it. */
export function mechanismSources(drivers: MechanismFile<DriverItem>,
                                 transmission: MechanismFile<SectorItem>): CitedSource[] {
  const cited: [string, SourceItem[]][] = [
    ...(drivers.state === "written" ? drivers.items.map((item): [string, SourceItem[]] => [item.title, item.sources]) : []),
    ...(transmission.state === "written"
      ? transmission.items.map((item): [string, SourceItem[]] => [item.sector, item.sources]) : []),
  ];
  const byUrl = new Map<string, CitedSource>();
  for (const [name, sources] of cited) {
    for (const source of sources) {
      const entry = byUrl.get(source.url) ?? { source, citedBy: [] };
      byUrl.set(source.url, entry);
      if (!entry.citedBy.includes(name)) entry.citedBy.push(name);
    }
  }
  return [...byUrl.values()];
}
