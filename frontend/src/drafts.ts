// Pure logic for saved drafts awaiting human review. A draft is not frozen, has no evaluation and is never
// scored here. Its structure was checked when it was saved; whether its reasoning holds is for a person to
// judge, so nothing below labels a model statement as a fact.

import type { DraftContent, DraftIndex, DraftOutcome, DraftReviewView, DraftSummaryRow } from "./draftTypes";

export const REVIEW_STATUS = "Not frozen · Requires human review";
export const PREPARE_DRAFTS_COMMAND = "python -m second_order prepare-drafts --attempt <saved attempt directory>";

export const OUTCOME_INFO: Record<DraftOutcome, { label: string; className: string; meaning: string }> = {
  draft: {
    label: "Draft",
    className: "outcome-draft",
    meaning: "The model proposed a hypothesis. Its structure passed the drafting contract's checks; that says " +
      "nothing about whether its reasoning is sound.",
  },
  no_draft: {
    label: "No draft",
    className: "outcome-no-draft",
    meaning: "The model declined to propose a hypothesis. Its public explanation is shown as it gave it.",
  },
  invalid: {
    label: "Invalid response",
    className: "outcome-invalid",
    meaning: "The response broke the drafting contract, so none of its content is shown.",
  },
  technical_failure: {
    label: "Technical failure",
    className: "outcome-failure",
    meaning: "No usable model response was recorded. The recorded problem is shown below.",
  },
};

/** A short, generic prompt for the reviewer. Nothing on the page records, scores or approves a review. */
export const REVIEW_CHECKLIST: { topic: string; question: string }[] = [
  { topic: "Source support",
    question: "Is each claim in the summary, reasoning and falsifiers stated in, or directly implied by, the source?" },
  { topic: "Unsupported assumptions",
    question: "What does the draft assume that the source does not say, such as market pricing, timing or size?" },
  { topic: "Distinct channels",
    question: "Does each named channel describe its own path, with its own direction and reasoning, rather than " +
      "a generic list of risks?" },
  { topic: "Already-reported moves",
    question: "Does the source already report a move in a proposed observable, and does that leg's " +
      "headline_reports_move flag say so?" },
];

const DRAFT_ID = /^[a-f0-9]{64}$/;

/** The ?draft= selection, if it names a well-formed ID. URLSearchParams never throws on malformed escapes. */
export function requestedDraft(search: string): string | null {
  const id = new URLSearchParams(search).get("draft");
  return id !== null && DRAFT_ID.test(id) ? id : null;
}

/** Most recently sent first. */
export function draftRows(index: DraftIndex): DraftSummaryRow[] {
  return [...index.drafts].sort((a, b) => Date.parse(b.sent_at) - Date.parse(a.sent_at) || a.id.localeCompare(b.id));
}

export interface LegRow {
  id: string;
  role: "Primary" | "Secondary";
  node: string;
  observable: string;
  direction: string;
  horizon: string;
  link: string;
  channel: string;
  reportsMove: string;
  rationale: string;
  falsifier: string;
}

/** Each proposed leg in display words; the values are the model's, unchanged. */
export function legRows(draft: DraftContent): LegRow[] {
  const labels = new Map(draft.nodes.map((node) => [node.id, node.label]));
  return [...draft.legs]
    .sort((a, b) => Number(b.primary) - Number(a.primary))
    .map((leg) => ({
      id: leg.id,
      role: leg.primary ? "Primary" : "Secondary",
      node: labels.get(leg.node_id) ?? leg.node_id,
      observable: leg.observable_id,
      direction: leg.expected === "up" ? "Up" : "Down",
      horizon: `${leg.horizon} observation${leg.horizon === 1 ? "" : "s"} after the scoring anchor`,
      link: leg.link === "direct" ? "Direct" : "Proxy",
      channel: leg.channel,
      reportsMove: leg.headline_reports_move ? "Yes, the model says the source reports this move" : "No, per the model",
      rationale: leg.rationale,
      falsifier: leg.falsifier,
    }));
}

/**
 * Problems that make a prepared view internally inconsistent. The panel refuses such a view rather than
 * repairing it; an empty list means the view can be shown.
 */
export function viewProblems(view: DraftReviewView): string[] {
  const problems: string[] = [];
  if (view.review_status !== REVIEW_STATUS) problems.push("The view does not carry the review status.");
  if (!(view.outcome in OUTCOME_INFO)) return [...problems, `Unknown outcome ${String(view.outcome)}.`];
  if ((view.outcome === "draft") !== (view.draft !== null)) problems.push("Only a draft outcome carries a draft.");
  if ((view.outcome === "no_draft") !== (view.explanation !== null)) {
    problems.push("Only a declined draft carries an explanation.");
  }
  const failed = view.outcome === "invalid" || view.outcome === "technical_failure";
  if (failed !== (typeof view.problem === "string")) problems.push("Only a failed attempt carries a problem.");
  for (const field of ["headline", "source_url", "published_at", "text"] as const) {
    if (typeof view.source?.[field] !== "string") problems.push(`The source has no ${field}.`);
  }
  if (view.draft) {
    const kinds = new Map(view.draft.nodes.map((node) => [node.id, node.kind]));
    if (kinds.size !== view.draft.nodes.length) problems.push("Two map nodes share an ID.");
    if (view.draft.edges.some((edge) => !kinds.has(edge.source) || !kinds.has(edge.target))) {
      problems.push("An edge names an unknown node.");
    }
    if (view.draft.legs.some((leg) => kinds.get(leg.node_id) !== "observable")) {
      problems.push("A leg does not point at an observable node.");
    }
    if (view.draft.legs.filter((leg) => leg.primary).length !== 1) problems.push("A draft needs exactly one primary leg.");
  }
  return problems;
}
