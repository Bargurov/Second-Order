// The fuels page's fixed copy (spec sections 5.0, 6.2 and 9) and its money formatting. Shown values arrive from the
// server as half-even text that is never "-0"; these functions only add the dollar sign and the true minus sign, so
// nothing here rounds or computes. leadAndRest splits mechanism prose into its visible first sentence and the rest.
// A change whose exact value is not zero but shows as zero reads as its direction and "<" the last shown place
// ("−<0.01"), so it is never mistaken for no change; a true zero shows as "0.00".
import { formatDay } from "./format.ts";

const MINUS = "−";

/** The caption under the barrel, verbatim. */
export const CAPTION = "Drawn to scale from zero. The line is the Brent spot price. The band is the 3-2-1 crack: how "
  + "much a benchmark basket of two barrels of New York Harbor gasoline and one of diesel is worth above three barrels "
  + "of crude, per barrel, before any refining costs. It approximates a refinery's gross margin; it is not any "
  + "refinery's profit.";

/** The three barrel labels, verbatim. */
export const BARREL_LABELS = {
  basket: "3-2-1 basket value",
  crack: "Crack 3-2-1 (before refining costs)",
  brent: "Brent spot",
} as const;

/** What the crack is not (spec 6.2). */
export const NOT_LIST = [
  "The 2:1 product mix approximates a refinery's output; it is not its yield.",
  "The geography and the crude and product grades are one chosen benchmark, not a universal refinery margin.",
  "The spread is gross: before refining operating costs and every other variable and fixed cost.",
];

/** Term → text, in reading order. */
export const GLOSSARY: Record<string, string> = {
  "Crack spread": "The value of refined products minus the price of the crude they are made from, per barrel. Here it "
    + "is computed from spot prices, before any refining costs.",
  "3-2-1": "A benchmark that treats three barrels of crude as making two of gasoline and one of diesel. It "
    + "approximates an output mix; actual yields differ by refinery and crude.",
  "Brent and WTI": "Two crude benchmarks. Brent is a North Sea crude that serves as the main international benchmark; "
    + "WTI is US crude priced at Cushing, Oklahoma. Their prices differ with location, transport and quality.",
  "Spot and futures": "A spot price is for prompt physical delivery; a futures price is for delivery in a named later "
    + "month. This page uses spot prices only.",
  "Backwardation and contango": "Near-month futures above later months is backwardation; below them, contango. This "
    + "page has no futures curve yet.",
  MMBtu: "One million British thermal units, the unit US natural gas is priced in.",
  Kinds: "P measured: published in a retained source, with its dates; C computed by fixed code; E a possible "
    + "explanation: a general economic mechanism stated conditionally, not a finding about the current move; S a "
    + "sourced claim, attributed to a named source with its date (only the situation note at the top carries such "
    + "claims, attributed in its text; none in the sections below); A your assumption (none on this page yet); M "
    + "missing, so no value is shown.",
};

/** The use scope of every series in the source-terms record (scope personal_and_private_demo, public not_assessed). */
export const SCOPE_TEXT = "Assessed for personal use and private demonstration; public use not assessed";

/** The mark the page carries when the review server serves its SYNTHETIC world (the reply's synthetic: true): a
 * banner above the barrel and a stamp in the sticky section nav, so a screenshot of any section says so. */
export const SYNTHETIC_TEXT = {
  stamp: "Synthetic prices",
  head: "Synthetic test data",
  body: "Every price, change, split and note on this page is made up to check the page: these are not market prices. "
    + "Real prices appear only after the operator's EIA refresh.",
} as const;

/** A unit as printed after a value. */
export const UNIT_SHORT: Record<string, string> = { usd_per_bbl: "$/bbl", usd_per_gal: "$/gal", usd_per_mmbtu: "$/MMBtu" };

const isZero = (shown: string) => !/[1-9]/.test(shown);
const digitsOf = (shown: string) => shown.replace(/^[-+]/, "");

/** "80.00" → "$80.00"; "-3.00" → "−$3.00". */
export function money(shown: string): string {
  const negative = shown.startsWith("-") && !isZero(shown);
  return `${negative ? MINUS : ""}$${digitsOf(shown)}`;
}

/** Whether a crack reads as negative: a negative sign and a shown figure that is not zero. A crack within half a cent
 * below zero shows $0.00 and is not called negative. */
export function shownNegative(crack: { sign: string; shown: string }): boolean {
  return crack.sign === "negative" && !isZero(crack.shown);
}

/** The crack's value on the barrel: "Crack −$3.00 (negative)", "Crack $0.00" for a crack within half a cent below
 * zero, otherwise the amount alone. */
export function crackLabel(crack: { sign: string; shown: string }): string {
  if (crack.sign !== "negative") return money(crack.shown);
  return `Crack ${money(crack.shown)}${shownNegative(crack) ? " (negative)" : ""}`;
}

/** A level as shown, with the true minus sign and no plus: "80.00" → "80.00"; "-3.00" → "−3.00". */
export function level(shown: string): string {
  const digits = digitsOf(shown);
  return shown.startsWith("-") && !isZero(digits) ? `${MINUS}${digits}` : digits;
}

/** "0.96" → "+0.96"; "-0.04" → "−0.04"; "0.00" → "0.00". */
export function signed(shown: string): string {
  const digits = digitsOf(shown);
  if (isZero(digits)) return digits;
  return `${shown.startsWith("-") ? MINUS : "+"}${digits}`;
}

/** A change in dollars: "6.54" → "+$6.54"; "-0.04" → "−$0.04"; "0.00" → "$0.00". */
export function signedMoney(shown: string): string {
  const digits = digitsOf(shown);
  if (isZero(digits)) return `$${digits}`;
  return `${shown.startsWith("-") ? MINUS : "+"}$${digits}`;
}

/** A shown figure's smallest step: "0.00" gives "0.01", "0.000" gives "0.001", "0.0" gives "0.1". */
export function lastPlace(shown: string): string {
  const places = (shown.split(".")[1] ?? "").length;
  return places ? `0.${"0".repeat(places - 1)}1` : "1";
}

/** The direction of a change that is not zero but shows as zero (-1 a fall, 1 a rise); 0 for every other change. */
export function under(pair: { value: string; shown: string }): -1 | 0 | 1 {
  if (!isZero(pair.shown) || isZero(pair.value)) return 0;
  return pair.value.startsWith("-") ? -1 : 1;
}

const way = (direction: -1 | 1) => (direction < 0 ? MINUS : "+");

/** A change as a signed figure: "+0.96", "−0.04", "0.00"; under the last shown place "−<0.01" or "+<0.01". */
export function changeNumber(pair: { value: string; shown: string }): string {
  const direction = under(pair);
  return direction ? `${way(direction)}<${lastPlace(pair.shown)}` : signed(pair.shown);
}

/** A change in dollars: "+$6.54", "−$0.04", "$0.00"; under the last shown place "−<$0.01" or "+<$0.01". */
export function changeMoney(pair: { value: string; shown: string }): string {
  const direction = under(pair);
  return direction ? `${way(direction)}<$${lastPlace(pair.shown)}` : signedMoney(pair.shown);
}

/** A percent change (shown only, without its %), its direction under the last place taken from the change itself:
 * "+1.2", "+<0.1" for a rise too small to show, "0.0" for no change. */
export function changePercent(pct: { shown: string }, change: { value: string; shown: string }): string {
  if (isZero(pct.shown) && !isZero(change.value)) {
    return `${way(change.value.startsWith("-") ? -1 : 1)}<${lastPlace(pct.shown)}`;
  }
  return signed(pct.shown);
}

/** The line under a verified series more than ten days behind the newest price on the page (the reply's behind). */
export function behindText(behind: { days: number; newest: string }, barrelInput: boolean): string {
  const head = `${behind.days} days behind the newest price on this page (${formatDay(behind.newest)}): `
    + "EIA's file held nothing newer for this series at the refresh. It is still a verified price";
  return barrelInput ? `${head}; the barrel, the crack and Situation now are not computed from it.` : `${head}.`;
}

/** A sentence ends at ".", "!" or "?" before a space and a capital, unless the stop closes a one-letter part ("U.S."). */
const SENTENCE_END = /[.!?](?=\s+[A-Z"“(])/g;

/** A prose text's first sentence and the rest ("" when it is one sentence); joined by one space they give it back. */
export function leadAndRest(text: string): [string, string] {
  for (const end of text.matchAll(SENTENCE_END)) {
    const at = end.index ?? 0;
    if (/(?:^|[\s.])[A-Za-z]$/.test(text.slice(0, at))) continue;
    return [text.slice(0, at + 1), text.slice(at + 1).trimStart()];
  }
  return [text, ""];
}
