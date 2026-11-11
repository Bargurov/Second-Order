// Pure geometry for the fuels page: the to-scale barrel, label spreading and the sparkline path. Nothing here reads
// the reply or rounds a value for later arithmetic; the page passes numbers it has already checked with fuels.ts.

/** The approved barrel outline (hero-barrel-v4.html). */
export const BODY_PATH = "M170,40 Q158,170 170,300 Q245,314 320,300 Q332,170 320,40 Q245,52 170,40 Z";
export const VIEWBOX = "0 0 340 330";
/** The y of a value of zero (the barrel floor) and of the larger of the two values (the barrel top). */
export const Y_ZERO = 306;
export const Y_FULL = 46;
const NOT_DRAWABLE = "Cannot be drawn to scale from zero";

export interface Geometry {
  drawable: boolean;
  fillTop: number | null;
  lineY: number | null;
  band: { top: number; bottom: number } | null;
  lineAboveFill: boolean;
  note: string | null;
}

const positive = (value: number | null): value is number => value !== null && Number.isFinite(value) && value > 0;

/** The fill (basket) and the Brent line, both measured from zero on one scale; the band is the positive crack. */
export function barrelGeometry(basket: number | null, brent: number | null): Geometry {
  if (!positive(basket) || !positive(brent)) {
    return { drawable: false, fillTop: null, lineY: null, band: null, lineAboveFill: false, note: NOT_DRAWABLE };
  }
  const scaleMax = Math.max(basket, brent);
  const y = (value: number) => Y_ZERO - (value / scaleMax) * (Y_ZERO - Y_FULL);
  const fillTop = y(basket);
  const lineY = y(brent);
  return { drawable: true, fillTop, lineY, band: basket - brent > 0 ? { top: fillTop, bottom: lineY } : null,
    lineAboveFill: brent > basket, note: null };
}

/** Label heights in the input order: each at its target, pushed down to at least `minGap` below the one before; if the
 * last passes `bottom` the whole run moves up, but never above `top`. */
export function spreadLabels(targets: number[], minGap: number, top: number, bottom: number): number[] {
  const placed: number[] = [];
  for (const target of targets) {
    placed.push(placed.length === 0 ? target : Math.max(target, placed[placed.length - 1] + minGap));
  }
  if (placed.length === 0) return placed;
  const excess = placed[placed.length - 1] - bottom;
  if (excess <= 0) return placed;
  const shift = Math.min(excess, Math.max(0, placed[0] - top));
  return placed.map((value) => value - shift);
}

const DAY_MS = 86_400_000;
const dayOf = (iso: string) => Date.parse(`${iso}T00:00:00Z`) / DAY_MS;
const fixed = (value: number) => String(Number(value.toFixed(2)));

/** An SVG path of the valued points. x is proportional to calendar days from the first valued point to the last, y to
 * the value between the minimum and maximum (a flat series sits mid-height). A null breaks the line; nothing is
 * interpolated or padded, and a point with no neighbour on either side draws nothing. */
export function sparklinePath(points: [string, string | null][], width: number, height: number): string {
  const valued = points.filter((point): point is [string, string] => point[1] !== null)
    .map(([date, value]) => ({ day: dayOf(date), value: Number(value) }));
  if (valued.length < 2) return "";
  const first = valued[0].day;
  const span = valued[valued.length - 1].day - first;
  const low = Math.min(...valued.map((point) => point.value));
  const high = Math.max(...valued.map((point) => point.value));
  const x = (day: number) => (span === 0 ? 0 : ((day - first) / span) * width);
  const y = (value: number) => (high === low ? height / 2 : height - ((value - low) / (high - low)) * height);
  const segments: string[] = [];
  let run: string[] = [];
  const close = () => { if (run.length >= 2) segments.push(run.join(" ")); run = []; };
  for (const [date, value] of points) {
    if (value === null) { close(); continue; }
    run.push(`${run.length === 0 ? "M" : "L"}${fixed(x(dayOf(date)))},${fixed(y(Number(value)))}`);
  }
  close();
  return segments.join(" ");
}
