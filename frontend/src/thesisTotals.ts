// The names of a balance table's demand and supply rows, from what their figures measure. A table's two sides are
// whatever its sources publish: copper v1 sets IEA demand against base-case MINE supply (refined supply is a line of
// its own), and United States reported refined CONSUMPTION against domestic REFINERY output (imports, exports and
// stocks are lines of their own). A fixed "Total supply" would name a quantity those figures are not, so each row is
// named by the measure every one of its figures states ("IEA base-case copper mine supply"); a qualifier only some of
// them add after a comma (", estimated") stays on those figures, in their own title and cited line.
import type { Figure } from "./thesis.ts";

type Measured = Pick<Figure, "measure">;

/** The measure all the figures state: their common leading comma-separated parts ("Refined use, reported" for
 * "Refined use, reported" and "Refined use, reported, estimated"); null when they share none, or there are none. */
export function sharedMeasure(figures: readonly Measured[]): string | null {
  if (figures.length === 0) return null;
  const parts = figures.map((figure) => figure.measure.split(", "));
  const shared: string[] = [];
  for (const [index, part] of parts[0].entries()) {
    if (!parts.every((other) => other[index] === part)) break;
    shared.push(part);
  }
  return shared.length > 0 ? shared.join(", ") : null;
}

/** The name of each side of a balance table, from the figures of its rows (null: no one measure to name it by). */
export function totalNames(rows: readonly { demand_total: Measured; supply_total: Measured }[]):
  { demand: string | null; supply: string | null } {
  return { demand: sharedMeasure(rows.map((row) => row.demand_total)),
    supply: sharedMeasure(rows.map((row) => row.supply_total)) };
}
