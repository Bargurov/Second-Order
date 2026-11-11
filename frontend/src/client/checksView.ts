// What the Client says about the research checks of a recorded analysis (GET /api/user/analyses/{id}/quality,
// docs/news-usage-contract.md): lexical checks that ask a person to look. Every check's name and rule come from the
// server's payload (its `checks` and each finding's `rule`), so a new rubric version needs no change here. Nothing here
// scores, grades, passes or approves an analysis, and no flag, or the absence of one, is presented as a verdict.
import type { Quality, QualityFinding } from "../contracts/news.ts";

/** A check's name as a reader sees it, from its identifier in the payload ("number_not_in_source" -> "Number not in
 * source"). */
export function checkName(check: string): string {
  const words = check.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Where a finding points, in the result's own terms; the statement's anchor when it names one. An unrecognised place
 * is shown as the server wrote it, never hidden. */
export function locationOf(where: string): { label: string; anchor: string | null } {
  const statement = /^established\[(\d+)\]$/.exec(where);
  if (statement) return { label: `Statement ${statement[1]}`, anchor: `#statement-${statement[1]}` };
  const missing = /^missing_information\[(\d+)\]$/.exec(where);
  if (missing) return { label: `Missing information, item ${missing[1]}`, anchor: null };
  const named: Record<string, string> = { interpretation: "The interpretation", analysis: "The analysis as a whole",
                                          source: "The source text" };
  return { label: named[where] ?? where, anchor: null };
}

/** The checks the server ran, by name, with their rules, in the payload's order. */
export const checksRun = (quality: Quality): { name: string; rule: string }[] =>
  Object.entries(quality.checks).map(([check, rule]) => ({ name: checkName(check), rule }));

/** The findings in the order the server listed them, each with its check's name and the place it points to. */
export const findingsShown = (quality: Quality):
  (QualityFinding & { name: string; place: { label: string; anchor: string | null } })[] =>
  quality.findings.map((finding) => ({ ...finding, name: checkName(finding.check), place: locationOf(finding.where) }));

/** Said beside every result's checks, flagged or not: what a flag and its absence do not mean. */
export const CHECKS_LIMITS = "A flag can be wrong, and a mistake can go unflagged: these checks compare words and " +
  "figures, not meaning. Read each flagged place against your source, and judge the rest yourself.";

/** When nothing was flagged. */
export const NOTHING_FLAGGED = "No check flagged anything in this result. That is not a confirmation that the " +
  "analysis is correct.";

/** When the result has no analysis to check (the server's null). */
export const NO_CHECKS = "There are no checks for this result: it holds no analysis to check.";

/** Reading the checks is a read: it contacts no publisher, runs nothing and uses no credits. */
export const CHECKS_READ = "Reading these checks contacts no publisher, runs no analysis and uses no credits.";
