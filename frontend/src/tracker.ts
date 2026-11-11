// Pure Tracker logic over the prepared index: grouping and recorded evaluation status.
// It counts cases only. No support or contradiction rates are derived: showcase cases never enter
// research scores, and research intake is closed.

// Explicit .ts specifier: the Node test runner loads this module directly.
import { NOT_EVALUATED, VERDICT_LABEL, formatUtc } from "./format.ts";
import type { DossierIndex, DossierSummary } from "./types";

export interface EvaluationStatus {
  /** "not_evaluated": no evaluation is stored. "recorded": one is, whatever its result, pending included. */
  kind: "not_evaluated" | "recorded" | "inconsistent";
  label: string;
  className: string;
  detail: string;
}

export interface TrackerSections {
  prospective: DossierSummary[];
  replay: DossierSummary[];
  researchCases: number;
}

const newestFirst = (a: DossierSummary, b: DossierSummary) =>
  Date.parse(b.published_at) - Date.parse(a.published_at) || a.id.localeCompare(b.id);

/** Prospective cases and retrospective replays are kept apart, each newest first. */
export function trackerSections(index: DossierIndex): TrackerSections {
  const rows = index.dossiers;
  return {
    prospective: rows.filter((row) => row.evidence_class === "prospective").sort(newestFirst),
    replay: rows.filter((row) => row.evidence_class === "replay").sort(newestFirst),
    researchCases: rows.filter((row) => row.usage === "research").length,
  };
}

export const usageLabel = (usage: DossierSummary["usage"]) => (usage === "research" ? "Research" : "Showcase");

/**
 * What is recorded for a case. "Not yet evaluated" means no evaluation is stored; "Pending" is a stored
 * evaluation whose scored window was incomplete when it ran. A contradictory index row is shown as such.
 */
export function evaluationStatus(row: DossierSummary): EvaluationStatus {
  if (row.state === "not_evaluated" && row.verdict === null) {
    return { kind: "not_evaluated", label: NOT_EVALUATED, className: "state-unevaluated",
             detail: "No evaluation has been recorded." };
  }
  if (row.state !== "evaluated" || row.verdict === null || row.as_of === null) {
    return { kind: "inconsistent", label: "Inconsistent record", className: "state-inconsistent",
             detail: "The prepared index contradicts itself for this case; prepare it again." };
  }
  const recorded = `Evaluation recorded as of ${formatUtc(row.as_of)}${row.rules_version ? `, rules ${row.rules_version}` : ""}`;
  return {
    kind: "recorded",
    label: VERDICT_LABEL[row.verdict],
    className: `verdict-${row.verdict}`,
    detail: row.verdict === "pending"
      ? `${recorded}. The scored window was incomplete at that evaluation, so its result is pending.`
      : `${recorded}.`,
  };
}
