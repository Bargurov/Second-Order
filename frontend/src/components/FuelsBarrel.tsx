import { useId } from "react";
import { formatDay } from "../format";
import type { BarrelView } from "../fuels";
import { BODY_PATH, spreadLabels, VIEWBOX, Y_FULL, type Geometry } from "../fuelsBarrel";
import { BARREL_LABELS, changeNumber, crackLabel, money, shownNegative } from "../fuelsText";
import { Kind } from "./CopperBits";

const HEIGHT = 330;  // VIEWBOX height
const LABEL_GAP = 40;
/** The lowest a label's anchor may sit (each target is clamped to it): the last label hangs below its anchor and must
 * end inside the drawing. Only a Brent or basket under about a ninth of the other reaches it. */
const LABEL_BOTTOM = 276;
/** Label anchors when the barrel cannot be drawn to scale (an input missing, or a price at or below zero). */
const UNPLACED = [86, 156, 226];
/** The fill runs below the curved floor; the body's clip path trims it. */
const FILL_FLOOR = 316;
const BRACKET_MIN = 4;
const LINE_UNDER_LABELS = 34;
const LINE_AT_BARREL = 150;
/** How far the Brent label may be spread from its line for the line still to run under the labels: the crack label
 * centred 40 above ends about 24 above its centre, so the line stays clear of it. */
const LINE_REACH = 12;

type Key = keyof typeof BARREL_LABELS;
/** The first label sits above its height, the middle one is centred on it, the last hangs below it; with anchors at
 * least LABEL_GAP apart the three never overlap, whichever way the crack's sign orders them. */
const ANCHORS = ["above", "middle", "below"] as const;

interface Label { key: Key; y: number; anchor: (typeof ANCHORS)[number]; value: string | null; change: string | null }

const fixed = (value: number) => Number(value.toFixed(2));

function labelsOf(barrel: BarrelView, geometry: Geometry): Label[] {
  const { crack, change, previous_date: previous } = barrel;
  const values: Record<Key, string | null> = {
    basket: barrel.basket ? money(barrel.basket.shown) : null,
    crack: crack ? crackLabel(crack) : null,
    brent: barrel.inputs ? money(barrel.inputs.brent.shown) : null,
  };
  const order: Key[] = geometry.lineAboveFill ? ["brent", "crack", "basket"] : ["basket", "crack", "brent"];
  const { fillTop, lineY } = geometry;
  const levels: Record<Key, number> | null = geometry.drawable && fillTop !== null && lineY !== null
    ? { basket: fillTop, crack: (fillTop + lineY) / 2, brent: lineY } : null;
  const targets = (levels ? order.map((key) => levels[key]) : UNPLACED).map((y) => Math.min(y, LABEL_BOTTOM));
  const placed = spreadLabels(targets, LABEL_GAP, Y_FULL, LABEL_BOTTOM);
  return order.map((key, index) => ({
    key, y: placed[index], anchor: ANCHORS[index], value: values[key],
    change: key === "brent" && change && previous ? `${changeNumber(change.brent)} since ${formatDay(previous)}` : null,
  }));
}

function describe(barrel: BarrelView, geometry: Geometry): string {
  const { basket, crack, inputs } = barrel;
  if (!basket || !crack || !inputs) return "Barrel outline: prices missing";
  const brent = money(inputs.brent.shown);
  const spread = money(crack.shown);
  if (!geometry.drawable) {
    return `Barrel outline only, as it cannot be drawn to scale from zero: ${BARREL_LABELS.basket} ${money(basket.shown)}, `
      + `${BARREL_LABELS.brent} ${brent}, crack ${spread}.`;
  }
  const head = `Barrel drawn to scale from zero: the fill is the ${BARREL_LABELS.basket}, ${money(basket.shown)}; `
    + `the dashed line is ${BARREL_LABELS.brent}, ${brent}`;
  if (crack.sign === "negative") {
    return `${head}, above the fill; the crack is ${spread}${shownNegative(crack) ? " (negative)" : ""}, so there is no band.`;
  }
  if (crack.sign === "zero") return `${head}, level with the fill; the crack is ${spread}, so there is no band.`;
  return `${head}; the band between them is the crack 3-2-1 before refining costs, ${spread}.`;
}

/**
 * The engraved barrel (spec section 8; approved rendering hero-barrel-v4.html), drawn to scale from zero: the fill is the
 * 3-2-1 basket value, the dashed line is Brent spot and the band between them is the positive crack. A missing input
 * or a price at or below zero leaves only the outline. Labels are HTML laid over the drawing at the heights they
 * describe, spread so they never overlap. Pattern and clip ids come from useId, so two barrels can share a page.
 */
export function FuelsBarrel({ barrel, geometry }: { barrel: BarrelView; geometry: Geometry }) {
  const id = useId().replace(/[^A-Za-z0-9_-]/g, "");
  const crude = `fu-crude-${id}`;
  const crackFill = `fu-crack-${id}`;
  const body = `fu-body-${id}`;
  const { drawable, fillTop, lineY, band } = geometry;
  const shown = barrel.state === "computed";
  // The crude fills only to the line, so on load it rises to the line and the crack band then fills above it; with no
  // band (a zero or negative crack) the crude is the whole fill. The end state equals one fill to the basket value.
  const crudeTop = !drawable || fillTop === null ? null : band ? band.bottom : fillTop;
  const labels = labelsOf(barrel, geometry);
  // The line runs under the labels to its own label (as in the mockup) only when that label sits at or just below the
  // line's height; a label spread further down would put the line through the crack label above it, and a label
  // lifted above its line (near the floor) would put the line through itself.
  const brentLabel = labels.find((label) => label.key === "brent");
  const spread = lineY !== null && brentLabel ? brentLabel.y - lineY : null;
  const lineFrom = spread !== null && spread >= 0 && spread <= LINE_REACH ? LINE_UNDER_LABELS : LINE_AT_BARREL;
  return (
    <div className="fu-barrel" data-drawable={String(drawable)}>
      <div className="fu-barrel-drawing">
        <svg viewBox={VIEWBOX} role="img" aria-label={describe(barrel, geometry)} data-drawable={String(drawable)}
             data-fill-top={fillTop === null ? undefined : fixed(fillTop)}
             data-line-y={lineY === null ? undefined : fixed(lineY)} data-band={band ? "yes" : "no"}
             data-line-above={String(geometry.lineAboveFill)}>
          <defs>
            <pattern id={crude} width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="4" height="4" className="fu-crude-ground" />
              <line x1="0" y1="0" x2="0" y2="4" className="fu-crude-hatch" />
            </pattern>
            <pattern id={crackFill} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">
              <rect width="5" height="5" className="fu-crack-ground" />
              <line x1="0" y1="0" x2="0" y2="5" className="fu-crack-hatch" />
            </pattern>
            <clipPath id={body}><path d={BODY_PATH} /></clipPath>
          </defs>
          <path d={BODY_PATH} className="fu-body" />
          <g clipPath={`url(#${body})`}>
            {crudeTop !== null && <rect className="fu-fill" x="150" width="190" y={fixed(crudeTop)}
                                        height={fixed(FILL_FLOOR - crudeTop)} fill={`url(#${crude})`} />}
            {band && <rect className="fu-band" x="150" width="190" y={fixed(band.top)}
                           height={fixed(band.bottom - band.top)} fill={`url(#${crackFill})`} />}
            <path className="fu-hoop" d="M150,82 Q245,96 340,82" />
            <path className="fu-hoop" d="M150,87 Q245,101 340,87" />
            <path className="fu-hoop fu-hoop-low" d="M150,252 Q245,266 340,252" />
            <path className="fu-hoop fu-hoop-low" d="M150,257 Q245,271 340,257" />
          </g>
          <path d={BODY_PATH} className="fu-outline" />
          <ellipse cx="245" cy="40" rx="75" ry="11" className="fu-outline" />
          <ellipse cx="282" cy="38" rx="9" ry="3" className="fu-bung" />
          {drawable && fillTop !== null && <line className="fu-tick" x1="150" y1={fixed(fillTop)} x2="166"
                                                 y2={fixed(fillTop)} />}
          {band && band.bottom - band.top >= BRACKET_MIN && <path className="fu-bracket"
            d={`M164,${fixed(band.top + 2)} L158,${fixed(band.top + 2)} L158,${fixed(band.bottom - 2)} L164,${fixed(band.bottom - 2)}`} />}
          {drawable && lineY !== null && <line className="fu-line" x1={lineFrom} y1={fixed(lineY)} x2="334"
                                               y2={fixed(lineY)} />}
        </svg>
        <div className="fu-labels">
          {labels.map((label) => (
            <p key={label.key} className="fu-label" data-label={label.key} data-anchor={label.anchor}
               data-sign={label.key === "crack" ? barrel.crack?.sign : undefined}
               style={{ top: `${((label.y / HEIGHT) * 100).toFixed(3)}%` }}>
              <span className="fu-label-k">{BARREL_LABELS[label.key]}</span>
              {label.value === null
                ? <span className="fu-label-n"><Kind kind="missing" title="Missing: no verified price" /></span>
                : <span className="fu-label-n">{label.value}</span>}
              {label.change && <span className="fu-label-change">{label.change}</span>}
            </p>
          ))}
        </div>
      </div>
      {shown && !drawable && geometry.note && (
        <p className="fu-barrel-note">{geometry.note}: Brent or the basket value is zero or below. The numbers stand as
          text.</p>
      )}
    </div>
  );
}
