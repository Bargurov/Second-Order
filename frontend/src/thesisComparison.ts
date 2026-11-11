// Which comparison a reason's or risk's measure makes (ruling R12), the rule its status is read by, and how a source's
// edition is named, in plain words for the thesis page, derived from the served reply alone: two figures from one
// source are two years within one edition; figures from two sources are two editions of one series, one year revised
// (revision) or a later year (period). thesis.ts checks the rule and the status themselves.
import type { Figure, Reason, Risk, ThesisSource } from "./thesis.ts";

export interface Compared { latest: Figure; previous: Figure; compare: "revision" | "period" }

/** A source's edition as the page names it: its edition text, followed by its title when another source the version
 * lists has the same publisher and edition text (copper v1: the MCS 2026 data release and the MCS 2026 copper chapter
 * both read "U.S. Geological Survey 2026"), so figure and passage lines from the two read apart. */
export function editionText(source: Pick<ThesisSource, "id" | "publisher" | "edition" | "title">,
                            listed: readonly Pick<ThesisSource, "id" | "publisher" | "edition">[]): string {
  const twin = listed.some((other) => other.id !== source.id && other.publisher === source.publisher &&
    other.edition === source.edition);
  return twin ? `${source.edition} (${source.title})` : source.edition;
}

/** True when both figures come from one source: two years within one edition. */
export const withinOneEdition = (measure: Compared) => measure.latest.source === measure.previous.source;

/** "Compares 2035 with 2030 within the same edition (Synthetic IEA, 2026)"; across editions "Compares the 2026 edition
 * with the 2025 edition, both for 2030" (one year revised) or "Compares 2025 in the 2026 edition with 2024 in the 2025
 * edition" (a later year). The sources are required, so a raw source id is never reader text. */
export function comparisonText(measure: Compared,
                               sources: ReadonlyMap<string, Pick<ThesisSource, "publisher" | "edition">>): string {
  const { latest, previous } = measure;
  const newer = sources.get(latest.source)!;
  if (withinOneEdition(measure)) {
    return `Compares ${latest.year} with ${previous.year} within the same edition (${newer.publisher}, ${newer.edition})`;
  }
  const older = sources.get(previous.source)!;
  return measure.compare === "revision"
    ? `Compares the ${newer.edition} edition with the ${older.edition} edition, both for ${latest.year}`
    : `Compares ${latest.year} in the ${newer.edition} edition with ${previous.year} in the ${older.edition} edition`;
}

/** The status rule with its exact conditions (thesis_arithmetic.reason_state / risk_state: a change, in percent of the
 * previous figure, strictly smaller than the material change in either direction is unchanged; at least it, in the
 * direction named, is the one status, and in the other direction the other), in the reply's own status words (each
 * label's name before its colon): "A change of less than 5% in either direction reads as Unchanged; Strengthening when
 * the latest figure is higher than the previous one by at least 5%, Weakening when it is lower by at least 5%. The
 * change is shown rounded to one decimal; the status is read from the exact figures." The last sentence keeps a shown
 * "+5.0%" beside "Unchanged" (an exact 4.96%) from reading as a contradiction. */
export function readAsText(measure: NonNullable<Reason["measure"] | Risk["measure"]>,
                           labels: Readonly<Record<string, string>>): string {
  const risk = "grows_when" in measure;
  const wanted = risk ? measure.grows_when : measure.supports_when;
  const [toward, away] = risk ? ["materialising", "receding"] : ["strengthening", "weakening"];
  const word = (key: string) => labels[key].split(":")[0];
  const x = `${measure.material_change_pct}%`;
  return `A change of less than ${x} in either direction reads as ${word("unchanged")}; ${word(toward)} when the ` +
    `latest figure is ${wanted} than the previous one by at least ${x}, ${word(away)} when it is ` +
    `${wanted === "higher" ? "lower" : "higher"} by at least ${x}. The change is shown rounded to one decimal; the ` +
    "status is read from the exact figures.";
}
