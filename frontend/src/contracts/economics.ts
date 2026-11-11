// A story's shared economic explanation (econ-explanation-0.5, docs/news-stories-contract.md), part of its published
// brief from story-brief-0.3. Owned by the logic conversation, like src/contracts/stories.ts, which imports it.
// 0.5 (docs/news-claims-conditions-2026-10-29.md (private; not in the public repository)): the stage "procedure" (an
// investigation or proceeding opened, no measure decided), "claim" references, and a figure's claim_label when its brief
// records who says what. 0.6 (docs/news-econ-consistency-2026-10-29.md (private; not in the public repository)): each
// alternative says what supports it (its sources, or an inference on stated assumptions) and the assumptions it rests on;
// an earlier alternative has neither and reads as it was.
//
// What the reader is shown keeps four kinds of statement apart: reported facts and figures (quoted from the story's
// sources), calculations made by the server (never written by hand), general economic reasoning (sourced framework
// notes, never evidence about the event) and conditional interpretations (channels, possible second-order effects,
// alternatives). The reader is fail-closed: an explanation that contradicts itself (an explained story without its
// summary, a citation of a report its brief's material does not hold, an insufficient one that still holds channels)
// is refused as unreadable rather than shown.
import { oneOf, record, text, texts } from "./user.ts";

export const ECONOMICS_VERSION = "econ-explanation-0.6";
/** Versions a published explanation may have been prepared under; older ones are read as they were saved. */
export const ECONOMICS_VERSIONS = ["econ-explanation-0.1", "econ-explanation-0.2", "econ-explanation-0.3",
  "econ-explanation-0.4", "econ-explanation-0.5", ECONOMICS_VERSION] as const;
/** Versions that record the form of evidence apart from the subject (0.4 and later): their summary names it. */
export const CLASSIFIED_VERSIONS: readonly string[] = ["econ-explanation-0.4", "econ-explanation-0.5",
  ECONOMICS_VERSION];
/** Versions whose alternatives say what supports them (0.6 and later). */
export const SUPPORTED_ALTERNATIVE_VERSIONS: readonly string[] = [ECONOMICS_VERSION];
/** What supports a channel (0.2): a sourced framework note, the story's own sources, or a bounded inference. */
export const SUPPORTS = ["framework", "event_evidence", "bounded_inference"] as const;
/** What supports an alternative (0.6): the story's own sources, or an inference on stated assumptions. */
export const ALTERNATIVE_SUPPORTS = ["event_evidence", "bounded_inference"] as const;
export const BOUNDS = ["exact", "lower_bound", "upper_bound", "approximate"] as const;
/** Where an explanation's framework notes come from: its own snapshot, the archived framework with its recorded
 * hash (an explanation saved before snapshots), or nowhere (said so, never replaced by today's notes). */
export const BACKGROUND_STATES = ["recorded", "recovered", "unavailable"] as const;
export const ECONOMICS_STATUSES = ["explained", "insufficient_evidence"] as const;
/** Whether a reader gets an explanation, and if not, why (news-explanations-0.1). */
export const EXPLANATION_STATES = ["ready", "insufficient", "drafted", "failed", "outdated", "pending", "restricted",
  "not_listed"] as const;
export const STAGES = ["proposal", "decision", "implementation", "observation", "forecast", "procedure"] as const;
export const HORIZONS = ["immediate", "weeks", "months", "quarters", "years", "unclear"] as const;
export const AFFECTED = ["households", "workers", "firms", "industry", "institutions", "government", "region"] as const;
export const REF_KINDS = ["fact", "report", "figure", "calculation", "context", "claim"] as const;
export const ALTERNATIVE_KINDS = ["competing_explanation", "offsetting_force"] as const;
export const CONTEXT_KINDS = ["publication", "observation", "expectation", "methodology"] as const;
/** What a context item is for (econ-context-0.2), and when it was published against the story's first report: an
 * item published after it is later context, labelled as such (``retrospective``). Items of 0.1 bundles have neither. */
export const CONTEXT_ROLES = ["event_evidence", "comparison", "methodology", "benchmark"] as const;
export const CONTEXT_TIMINGS = ["before", "same_day", "after", "unknown"] as const;

export interface Ref { kind: (typeof REF_KINDS)[number]; label: string; reports: string[] }
export interface Party { kind: (typeof AFFECTED)[number]; name: string; how: string }
export interface Channel {
  id: string; scope: "macro" | "micro"; scope_label: string; support?: (typeof SUPPORTS)[number] | null;
  support_label?: string | null; text: string; steps: string[]; affected: Party[];
  conditions: string | null; horizon: (typeof HORIZONS)[number]; horizon_label: string; kind: "interpretation";
  note: { id: string; title: string } | null; basis: Ref[]; assumptions: string[];
}
export interface SecondOrder {
  id: string; from: string; text: string; conditions: string; horizon: (typeof HORIZONS)[number];
  horizon_label: string; kind: "interpretation"; basis: Ref[]; assumptions: string[];
}
export interface Alternative {
  kind: (typeof ALTERNATIVE_KINDS)[number]; label: string; text: string; basis: Ref[];
  /** 0.6: what supports it and the assumptions it rests on (IDs); absent for an earlier explanation. */
  support?: (typeof ALTERNATIVE_SUPPORTS)[number]; support_label?: string; assumptions?: string[];
}
export interface Watch { observable: string; would: "support" | "weaken"; text: string }
export interface Figure {
  id: string; display: string; label: string; period: string; basis_label: string | null;
  seasonal_label: string | null; measure: string; quote: string;
  vintage: { source: string; published: string | null; label: string | null }; kind: "reported"; reports: string[];
  context: string | null; statistic_label?: string | null; stock_flow_label?: string | null;
  bound?: (typeof BOUNDS)[number]; sign_basis?: string | null; direction_warning?: string | null;
  /** The margin its quote writes beside the number, as written ("±13.8%"; econ-fidelity-0.1), or null. */
  margin?: string | null;
  /** What its claim is when its brief records who says what (0.5): "a stated expectation, plan or scenario, not an
   * observed outcome", "conditional: …"; null for a stated figure; absent for a brief that records no claims. */
  claim_label?: string | null;
}
export interface Calculation {
  id: string; display: string; label: string; formula: string; inputs: string[]; period: string;
  basis_label: string | null; kind: "derived"; bound?: (typeof BOUNDS)[number];
}
export interface Note {
  id: string; title: string; mechanism: string; limits: string; kind: "reasoning";
  sources: { title: string; publisher: string; year: number | null; url: string }[];
}
export interface ContextItem {
  item_id: string; kind: (typeof CONTEXT_KINDS)[number]; publisher: string; title: string | null; link: string;
  published: string | null; as_of: string | null; attribution: string | null;
  role?: (typeof CONTEXT_ROLES)[number] | null; role_label?: string | null; relevance?: string | null;
  retrieved?: string | null; timing?: (typeof CONTEXT_TIMINGS)[number] | null; timing_label?: string | null;
  retrospective?: boolean;
}
export interface EconomicsSummary {
  stage: (typeof STAGES)[number]; stage_label: string; instrument_label: string; what_changed: string;
  what_changed_basis: Ref[]; why_it_matters: string; why_basis: Ref[]; who: string[]; main_uncertainty: string;
  /** 0.4: the form of the evidence and a survey's respondents, apart from its subject (instrument_label); an earlier
   * explanation instead says that it did not record them (classification_note). */
  form_label?: string | null; respondents_label?: string | null; classification_note?: string | null;
}
export interface Economics {
  analysis_version: (typeof ECONOMICS_VERSIONS)[number]; status: (typeof ECONOMICS_STATUSES)[number];
  insufficient_reason: string | null; summary: EconomicsSummary | null; channels: Channel[];
  second_order: SecondOrder[]; alternatives: Alternative[]; watch: Watch[]; figures: Figure[];
  calculations: Calculation[]; assumptions: { id: string; text: string }[]; notes: Note[]; context: ContextItem[];
  statement: string | null; kinds: Record<string, string>;
  background?: { state: (typeof BACKGROUND_STATES)[number]; framework_version: string | null;
                 framework_sha256: string | null } | null;
}
export interface Explanation { state: (typeof EXPLANATION_STATES)[number]; statement: string | null; reason: string | null }

const textOrNull = (value: unknown) => value === null || text(value);
const https = (value: unknown) => typeof value === "string" && value.startsWith("https://");
const list = (value: unknown, check: (row: Record<string, unknown>) => boolean) =>
  Array.isArray(value) && value.every((row) => record(row) && check(row));

function refs(value: unknown, used: Set<string>): boolean {
  return list(value, (row) => oneOf(REF_KINDS, row.kind) && text(row.label) && texts(row.reports) &&
    (row.reports as string[]).every((entry) => used.has(entry)));
}

function itemsProblem(value: Record<string, unknown>, used: Set<string>): string | null {
  if (!list(value.channels, (row) => text(row.id) && (row.scope === "macro" || row.scope === "micro") &&
      text(row.scope_label) && text(row.text) && texts(row.steps) && (row.steps as string[]).length > 0 &&
      list(row.affected, (party) => oneOf(AFFECTED, party.kind) && text(party.name) && text(party.how)) &&
      textOrNull(row.conditions) && oneOf(HORIZONS, row.horizon) && text(row.horizon_label) &&
      row.kind === "interpretation" && (row.note === null || (record(row.note) && text(row.note.id) &&
        text(row.note.title))) && refs(row.basis, used) && texts(row.assumptions))) {
    return "The explanation's channels are not readable.";
  }
  if (!list(value.second_order, (row) => text(row.id) && text(row.from) && text(row.text) && text(row.conditions) &&
      oneOf(HORIZONS, row.horizon) && text(row.horizon_label) && row.kind === "interpretation" &&
      refs(row.basis, used) && texts(row.assumptions)) ||
      !list(value.alternatives, (row) => oneOf(ALTERNATIVE_KINDS, row.kind) && text(row.label) && text(row.text) &&
        refs(row.basis, used) && (SUPPORTED_ALTERNATIVE_VERSIONS.includes(value.analysis_version as string)
          ? oneOf(ALTERNATIVE_SUPPORTS, row.support) && text(row.support_label) && texts(row.assumptions) &&
            (row.support !== "bounded_inference" || (row.assumptions as string[]).length > 0)
          : row.support === undefined && row.support_label === undefined && row.assumptions === undefined)) ||
      !list(value.watch, (row) => text(row.observable) && (row.would === "support" || row.would === "weaken") &&
        text(row.text))) {
    return "The explanation's effects, alternatives or observables are not readable.";
  }
  if (!list(value.figures, (row) => text(row.id) && text(row.display) && text(row.label) && text(row.period) &&
      textOrNull(row.basis_label) && textOrNull(row.seasonal_label) && text(row.quote) && row.kind === "reported" &&
      record(row.vintage) && text(row.vintage.source) && texts(row.reports) &&
      (row.reports as string[]).every((entry) => used.has(entry)) && textOrNull(row.context) &&
      (row.margin === undefined || textOrNull(row.margin)) &&
      (row.claim_label === undefined || textOrNull(row.claim_label))) ||
      !list(value.calculations, (row) => text(row.id) && text(row.display) && text(row.label) && text(row.formula) &&
        texts(row.inputs) && row.kind === "derived") ||
      !list(value.assumptions, (row) => text(row.id) && text(row.text))) {
    return "The explanation's figures, calculations or assumptions are not readable.";
  }
  if (!list(value.notes, (row) => text(row.id) && text(row.title) && text(row.mechanism) && text(row.limits) &&
      row.kind === "reasoning" && Array.isArray(row.sources) && row.sources.length > 0 &&
      list(row.sources, (source) => text(source.title) && text(source.publisher) && https(source.url))) ||
      !list(value.context, (row) => text(row.item_id) && oneOf(CONTEXT_KINDS, row.kind) && text(row.publisher) &&
        https(row.link))) {
    return "The explanation's background or context is not readable.";
  }
  if ((value.context as ContextItem[]).some((row) => (row.role != null && !oneOf(CONTEXT_ROLES, row.role)) ||
      (row.timing != null && !oneOf(CONTEXT_TIMINGS, row.timing)) ||
      (row.timing != null && row.retrospective !== (row.timing === "after")))) {
    return "A context item's role or timing is not readable.";
  }
  return null;
}

/** Whether an explanation can be shown; ``used`` holds the brief's material report IDs. */
export function economicsProblem(value: unknown, used: Set<string>): string | null {
  if (!record(value) || !oneOf(ECONOMICS_VERSIONS, value.analysis_version) || !oneOf(ECONOMICS_STATUSES, value.status) ||
      !textOrNull(value.insufficient_reason) || !textOrNull(value.statement) || !record(value.kinds)) {
    return "The economic explanation is not readable.";
  }
  const bad = itemsProblem(value, used);
  if (bad) return bad;
  if (value.status === "insufficient_evidence") {
    const empty = ["channels", "second_order", "alternatives", "watch", "figures", "calculations", "assumptions",
      "notes", "context"].every((key) => (value[key] as unknown[]).length === 0);
    return text(value.insufficient_reason) && value.summary === null && empty ? null
      : "An explanation of insufficient evidence holds an explanation.";
  }
  const summary = value.summary;
  if (value.insufficient_reason !== null || !record(summary) || !oneOf(STAGES, summary.stage) ||
      !text(summary.stage_label) || !text(summary.instrument_label) || !text(summary.what_changed) ||
      !refs(summary.what_changed_basis, used) || !text(summary.why_it_matters) || !refs(summary.why_basis, used) ||
      !texts(summary.who) || !text(summary.main_uncertainty) ||
      !["form_label", "respondents_label", "classification_note"].every((key) => summary[key] === undefined ||
        textOrNull(summary[key])) ||
      (CLASSIFIED_VERSIONS.includes(value.analysis_version as string) &&
        (!text(summary.form_label) || summary.classification_note))) {
    return "The economic explanation's summary is not readable.";
  }
  if ((value.channels as unknown[]).length === 0 || (value.watch as unknown[]).length === 0 ||
      (value.alternatives as unknown[]).length === 0) {
    return "An explanation names its channels, alternatives and what to watch.";
  }
  const background = value.background;
  if (background !== undefined && background !== null &&
      (!record(background) || !oneOf(BACKGROUND_STATES, background.state))) {
    return "The explanation's background is not readable.";
  }
  if (record(background) && background.state === "unavailable" && (value.notes as unknown[]).length > 0) {
    return "An explanation whose framework cannot be recovered shows notes.";
  }
  if ((value.channels as Channel[]).some((row) => row.support !== undefined && row.support !== null &&
      !oneOf(SUPPORTS, row.support))) return "A channel's support is not readable.";
  const ids = new Set((value.channels as Channel[]).map((row) => row.id));
  if ((value.second_order as SecondOrder[]).some((row) => !ids.has(row.from))) {
    return "A second-order effect follows from no channel of the explanation.";
  }
  const assumed = new Set((value.assumptions as { id: string }[]).map((row) => row.id));
  if ((value.alternatives as Alternative[]).some((row) => (row.assumptions ?? []).some((id) => !assumed.has(id)))) {
    return "An alternative rests on an assumption the explanation does not state.";
  }
  return /\{[fc]\d{1,2}\}/.test(JSON.stringify(value)) ? "The explanation shows an unrendered figure." : null;
}

export function explanationProblem(value: unknown): string | null {
  if (!record(value) || !oneOf(EXPLANATION_STATES, value.state) || !textOrNull(value.statement) ||
      !textOrNull(value.reason)) return "The story's explanation state is not readable.";
  return (value.state === "ready") === (value.statement === null) ? null
    : "The story's explanation state and its statement disagree.";
}

