// Exact decimals for the thesis reader (thesis.ts). Numbers travel as strings and are compared and rounded as BigInt
// over scaled decimals, never as floating point, as second_order/thesis_arithmetic.py does with Decimal. These are pure
// functions: they refuse nothing themselves, and thesis.ts turns a null or a mismatch into a refusal with its place.

/** The value n / 10^s. */
export interface Dec { n: bigint; s: number }

const PLAIN = /^-?\d+(?:\.\d+)?$/;
/** One grouping character per value, used for every group: comma, space, no-break space, narrow no-break space or thin
 * space (thesis_arithmetic.shown_value). */
const GROUPED = /^-?\d{1,3}(?:([, \u00a0\u202f\u2009])\d{3}(?:\1\d{3})*)?(?:\.\d+)?$/;

export const pow10 = (places: number) => 10n ** BigInt(places);
export const abs = (n: bigint) => (n < 0n ? -n : n);
/** The value's n at `places` decimals (places >= value.s). */
export const scaled = (value: Dec, places: number) => value.n * pow10(places - value.s);
export const sign = (value: Dec) => (value.n > 0n ? 1 : value.n < 0n ? -1 : 0);

function parsed(value: string): Dec {
  const [whole, fraction = ""] = value.replace(/^-/, "").split(".");
  const magnitude = BigInt(whole + fraction);
  return { n: value.startsWith("-") ? -magnitude : magnitude, s: fraction.length };
}

/** A plain decimal as the server writes values (-?digits with an optional fraction), else null. */
export function plainDecimal(value: unknown): Dec | null {
  return typeof value === "string" && PLAIN.test(value) ? parsed(value) : null;
}

/** A figure as its source prints it ("23,000", "$410", "12%"), by the server's grammar (shown_value), else null. */
export function printed(value: string): Dec | null {
  const rest = value.replace(/^\$/, "").replace(/%$/, "");
  return GROUPED.test(rest) || PLAIN.test(rest) ? parsed(rest.replace(/[, \u00a0\u202f\u2009]/g, "")) : null;
}

export function difference(a: Dec, b: Dec): Dec {
  const s = Math.max(a.s, b.s);
  return { n: scaled(a, s) - scaled(b, s), s };
}

/** How the server displays a number (thesis_arithmetic.display): comma thousands and exactly `places` decimals. */
export const displayedPattern = (places: number) =>
  new RegExp(`^-?(?:0|[1-9]\\d{0,2}(?:,\\d{3})*)${places > 0 ? `\\.\\d{${places}}` : ""}$`);

/** A displayed number (one that matches displayedPattern) as an integer scaled by 10^places. */
export function displayedValue(value: string): bigint {
  const magnitude = BigInt(value.replace(/[-,.]/g, ""));
  return value.startsWith("-") ? -magnitude : magnitude;
}

/** num / den (den > 0) rounded half-even to `places` decimals and scaled by 10^places, as the server rounds. */
export function halfEven(num: bigint, den: bigint, places: number): bigint {
  const whole = abs(num) * pow10(places);
  let quotient = whole / den;
  const twice = 2n * (whole - quotient * den);
  if (twice > den || (twice === den && quotient % 2n === 1n)) quotient += 1n;
  return num < 0n ? -quotient : quotient;
}
