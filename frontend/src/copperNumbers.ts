// Exact fractions for the copper tools' reader (copperTools.ts): values travel as plain decimal strings and every
// computed value is recomputed here as a BigInt fraction, never as floating point, then shown by the server's own
// display rules (second_order/copper_coverage.shown_kt, copper_producers.half_even). Pure functions: they refuse
// nothing themselves; the reader turns a null or a mismatch into a refusal with its place.
import { plainDecimal, type Dec } from "./thesisNumbers.ts";

/** n / d with d > 0, in lowest terms. */
export interface Rat { n: bigint; d: bigint }

const abs = (n: bigint) => (n < 0n ? -n : n);
function gcd(a: bigint, b: bigint): bigint {
  let x = abs(a);
  let y = abs(b);
  while (y !== 0n) [x, y] = [y, x % y];
  return x === 0n ? 1n : x;
}

export function make(n: bigint, d: bigint): Rat {
  if (d === 0n) throw new RangeError("division by zero");
  const sign = d < 0n ? -1n : 1n;
  const g = gcd(n, d);
  return { n: (sign * n) / g, d: (sign * d) / g };
}

export const int = (value: number | bigint): Rat => make(BigInt(value), 1n);
export const ofDec = (value: Dec): Rat => make(value.n, 10n ** BigInt(value.s));
/** A plain decimal string as the server writes values, else null. */
export function ofPlain(value: unknown): Rat | null {
  const dec = plainDecimal(value);
  return dec === null ? null : ofDec(dec);
}
export const add = (a: Rat, b: Rat) => make(a.n * b.d + b.n * a.d, a.d * b.d);
export const sub = (a: Rat, b: Rat) => make(a.n * b.d - b.n * a.d, a.d * b.d);
export const mul = (a: Rat, b: Rat) => make(a.n * b.n, a.d * b.d);
export const div = (a: Rat, b: Rat) => make(a.n * b.d, a.d * b.n);
export const neg = (a: Rat): Rat => ({ n: -a.n, d: a.d });
export const sum = (values: Rat[]) => values.reduce(add, int(0));
export const equal = (a: Rat, b: Rat) => a.n === b.n && a.d === b.d;
export const isZero = (a: Rat) => a.n === 0n;
export const lessThan = (a: Rat, b: Rat) => a.n * b.d < b.n * a.d;
export function pow(a: Rat, k: number): Rat {
  let out = int(1);
  for (let i = 0; i < k; i += 1) out = mul(out, a);
  return out;
}

/** The exact kilograms in a pound, by definition. */
export const POUND_KG = make(45359237n, 100000000n);

function grouped(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** ROUND_HALF_EVEN to `places` decimals, comma-grouped, never "-0" (copper_producers.half_even). */
export function halfEven(value: Rat, places: number): string {
  const scale = 10n ** BigInt(places);
  const scaled = value.n * scale;
  let whole = scaled / value.d;
  if (scaled % value.d !== 0n && scaled < 0n) whole -= 1n; // Floor, as the server's numerator // denominator.
  const rest = make(scaled - whole * value.d, value.d);
  const half = make(1n, 2n);
  if (lessThan(half, rest) || (equal(rest, half) && abs(whole) % 2n === 1n)) whole += 1n;
  const sign = whole < 0n ? "-" : "";
  const digits = abs(whole).toString().padStart(places + 1, "0");
  const integer = places ? digits.slice(0, digits.length - places) : digits;
  return sign + grouped(integer) + (places ? `.${digits.slice(digits.length - places)}` : "");
}

/** The number of decimals a value has when written exactly, or null when it has more than `limit`. */
export function exactPlaces(value: Rat, limit: number): number | null {
  for (let places = 0; places <= limit; places += 1) {
    if ((value.n * 10n ** BigInt(places)) % value.d === 0n) return places;
  }
  return null;
}

/** A kt value as the server shows it: exact up to five decimals, else to the tonne (three decimals), half-even. */
export function shownKt(value: Rat): { shown: string; rounded: boolean } {
  const places = exactPlaces(value, 5);
  return places === null ? { shown: halfEven(value, 3), rounded: true } : { shown: halfEven(value, places), rounded: false };
}
