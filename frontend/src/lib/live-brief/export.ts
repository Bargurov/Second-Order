/**
 * export.ts — deterministic Markdown / JSON export and fail-closed import.
 *
 * Determinism: the export timestamp is an explicit argument (never read from a
 * clock), and every object is rebuilt in a fixed field order, so identical
 * input yields byte-identical output.  Import is fail-closed: malformed text or
 * a brief that does not pass the exact validator is rejected whole, so the
 * caller can preserve the existing briefs untouched.
 *
 * Both formats carry the full record: schema version, every hypothesis,
 * falsifier and follow-up, the complete revision log, the claim ceiling, the
 * non-claim, visible missingness, and the export timestamp.
 */
import {
  BRIEF_FIELD_ORDER,
  HISTORICAL_CONTEXT_DISCLAIMER,
  NO_COMPARABLE_COHORT,
  STAGE_LABELS,
  type AssetRoleRow,
  type Brief,
  type Falsifier,
  type FollowUp,
  type Hypothesis,
  type MarketReaction,
  type Revision,
  type SourceReference,
  type TypedEntry,
} from "./types";
import { overdueFollowUps } from "./operations";
import { validateBrief } from "./validate";

// ---------------------------------------------------------------------------
// Canonicalisers — rebuild each record in a fixed field order so serialisation
// is independent of the input object's key order.
// ---------------------------------------------------------------------------

const canonSource = (s: SourceReference): SourceReference => ({
  id: s.id,
  label: s.label,
  url: s.url,
  note: s.note,
});

const canonEntry = (e: TypedEntry): TypedEntry => ({
  id: e.id,
  type: e.type,
  text: e.text,
  source_reference: e.source_reference,
  source_note: e.source_note,
  as_of: e.as_of,
});

const canonHyp = (h: Hypothesis): Hypothesis => ({
  hypothesis_id: h.hypothesis_id,
  name: h.name,
  mechanism_path: h.mechanism_path,
  supporting_facts: [...h.supporting_facts],
  contradicting_facts: [...h.contradicting_facts],
  unknowns: [...h.unknowns],
  expected_asset_roles: [...h.expected_asset_roles],
  falsifiers: [...h.falsifiers],
  current_state: h.current_state,
});

const canonAsset = (a: AssetRoleRow): AssetRoleRow => ({
  id: a.id,
  asset: a.asset,
  role: a.role,
  benchmark: a.benchmark,
  sector_or_relative_lens: a.sector_or_relative_lens,
  expected_channel: a.expected_channel,
  observed_move: a.observed_move,
  window: a.window,
  basis: a.basis,
  as_of: a.as_of,
  limitations: a.limitations,
});

const canonReaction = (m: MarketReaction): MarketReaction => ({
  id: m.id,
  horizon: m.horizon,
  value: m.value,
  unit: m.unit,
  basis: m.basis,
  window: m.window,
  as_of: m.as_of,
  source: m.source,
});

const canonFalsifier = (f: Falsifier): Falsifier => ({
  falsifier_id: f.falsifier_id,
  statement: f.statement,
  linked_hypothesis: f.linked_hypothesis,
  observable: f.observable,
  evaluation_window: f.evaluation_window,
  status: f.status,
  evidence: f.evidence,
  as_of: f.as_of,
});

const canonFollowUp = (f: FollowUp): FollowUp => ({
  follow_up_id: f.follow_up_id,
  question: f.question,
  linked_hypothesis: f.linked_hypothesis,
  due_stage: f.due_stage,
  status: f.status,
  result: f.result,
  as_of: f.as_of,
});

const canonRevision = (r: Revision): Revision => ({
  id: r.id,
  timestamp: r.timestamp,
  stage: r.stage,
  what_changed: r.what_changed,
  why_it_changed: r.why_it_changed,
  linked_fact_or_falsifier: r.linked_fact_or_falsifier,
});

const CANON: { [K in keyof Brief]: (b: Brief) => Brief[K] } = {
  brief_id: (b) => b.brief_id,
  schema_version: (b) => b.schema_version,
  title: (b) => b.title,
  event_family: (b) => b.event_family,
  event_type: (b) => b.event_type,
  event_date: (b) => b.event_date,
  scheduled_timestamp: (b) => b.scheduled_timestamp,
  timezone: (b) => b.timezone,
  current_stage: (b) => b.current_stage,
  created_at: (b) => b.created_at,
  updated_at: (b) => b.updated_at,
  source_references: (b) => b.source_references.map(canonSource),
  fact_summary: (b) => b.fact_summary.map(canonEntry),
  delta_vs_prior: (b) => ({
    previous_state: b.delta_vs_prior.previous_state,
    new_information: b.delta_vs_prior.new_information,
    unchanged_information: b.delta_vs_prior.unchanged_information,
    unresolved_information: b.delta_vs_prior.unresolved_information,
    operator_delta_summary: b.delta_vs_prior.operator_delta_summary,
  }),
  known_unknowns: (b) => b.known_unknowns.map(canonEntry),
  mechanism_hypotheses: (b) => b.mechanism_hypotheses.map(canonHyp),
  asset_roles: (b) => b.asset_roles.map(canonAsset),
  market_reactions: (b) => b.market_reactions.map(canonReaction),
  historical_context: (b) => ({
    comparable_cohort: b.historical_context.comparable_cohort,
    notes: b.historical_context.notes,
  }),
  falsifiers: (b) => b.falsifiers.map(canonFalsifier),
  follow_up_checks: (b) => b.follow_up_checks.map(canonFollowUp),
  revision_log: (b) => b.revision_log.map(canonRevision),
  claim_ceiling: (b) => b.claim_ceiling,
  non_claim: (b) => b.non_claim,
};

/** Rebuild a brief with every field in the canonical order. */
export function canonicalizeBrief(brief: Brief): Brief {
  const out = {} as Record<string, unknown>;
  for (const key of BRIEF_FIELD_ORDER) {
    out[key] = CANON[key](brief);
  }
  return out as unknown as Brief;
}

// ---------------------------------------------------------------------------
// JSON export / import
// ---------------------------------------------------------------------------

/** Deterministic JSON export: canonical brief + a sibling ``exported_at``. */
export function exportBriefJson(brief: Brief, exportedAt: string): string {
  return JSON.stringify({ ...canonicalizeBrief(brief), exported_at: exportedAt }, null, 2) + "\n";
}

export type ImportResult = { ok: true; brief: Brief } | { ok: false; errors: string[] };

/**
 * Parse and validate imported JSON.  Fail-closed: non-JSON or an out-of-
 * contract brief returns errors and leaves the caller's briefs untouched.  A
 * valid import is returned canonicalised, so a stray ``exported_at`` from a
 * prior export never persists.
 */
export function importBriefJson(text: string): ImportResult {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { ok: false, errors: ["import is not valid JSON"] };
  }
  const r = validateBrief(parsed);
  if (!r.ok) return { ok: false, errors: r.errors };
  return { ok: true, brief: canonicalizeBrief(r.brief) };
}

// ---------------------------------------------------------------------------
// Markdown export
// ---------------------------------------------------------------------------

const DASH = "—";
const NONE = "_(none recorded)_";

function orDash(s: string): string {
  return s.trim().length > 0 ? s.trim() : DASH;
}

/** Markdown table-cell escape (pipes only). */
function cell(s: string): string {
  return orDash(s).replace(/\|/g, "\\|").replace(/\n/g, " ");
}

function reactionValue(m: MarketReaction): string {
  if (m.value === null) return "unavailable";
  const unit = m.unit.trim();
  return `${m.value}${unit ? ` ${unit}` : ""}`;
}

/** Deterministic Markdown export of the full brief. */
export function exportBriefMarkdown(brief: Brief, exportedAt: string): string {
  const b = canonicalizeBrief(brief);
  const L: string[] = [];
  const push = (s = "") => L.push(s);

  // Header + identity
  push(`# Live Event Brief — ${orDash(b.title)}`);
  push();
  push(`_${b.non_claim}_`);
  push();
  push(`**Schema:** \`${b.schema_version}\`  ·  **Brief id:** \`${b.brief_id}\``);
  push(`**Stage:** ${STAGE_LABELS[b.current_stage]} (\`${b.current_stage}\`)`);
  push(`**Family:** ${orDash(b.event_family)}  ·  **Type:** ${orDash(b.event_type)}`);
  push(`**Event date:** ${orDash(b.event_date)}  ·  **Scheduled / observed:** ${orDash(b.scheduled_timestamp)}  ·  **Timezone:** ${orDash(b.timezone)}`);
  push(`**Created:** ${b.created_at}  ·  **Last updated:** ${b.updated_at}`);
  push();

  // Sources
  push("## Sources");
  push();
  if (b.source_references.length === 0) push(NONE);
  else
    for (const s of b.source_references) {
      const url = s.url.trim() ? ` <${s.url.trim()}>` : "";
      const note = s.note.trim() ? ` — ${s.note.trim()}` : "";
      push(`- ${orDash(s.label)}${url}${note}`);
    }
  push();

  // Facts / interpretations / unknowns
  const renderEntries = (title: string, entries: TypedEntry[]) => {
    push(`## ${title}`);
    push();
    if (entries.length === 0) push(NONE);
    else
      for (const e of entries) {
        const src =
          e.source_reference.trim() || e.source_note.trim()
            ? ` _(source: ${orDash(e.source_reference || e.source_note)})_`
            : e.type === "FACT"
              ? " _(source: not attached)_"
              : "";
        push(`- **[${e.type}]** ${orDash(e.text)}${src}  ·  _as of ${e.as_of}_`);
      }
    push();
  };
  renderEntries("Facts, interpretations & unknowns", b.fact_summary);

  // What changed
  push("## What changed?");
  push();
  push(`- **Previous state:** ${orDash(b.delta_vs_prior.previous_state)}`);
  push(`- **New information:** ${orDash(b.delta_vs_prior.new_information)}`);
  push(`- **Unchanged:** ${orDash(b.delta_vs_prior.unchanged_information)}`);
  push(`- **Unresolved:** ${orDash(b.delta_vs_prior.unresolved_information)}`);
  push(`- **Operator delta summary:** ${orDash(b.delta_vs_prior.operator_delta_summary)}`);
  push();

  renderEntries("Known unknowns", b.known_unknowns);

  // Hypotheses
  push("## Competing mechanism hypotheses");
  push();
  if (b.mechanism_hypotheses.length === 0) push(NONE);
  else
    for (const h of b.mechanism_hypotheses) {
      push(`### ${orDash(h.name)} — \`${h.current_state}\``);
      push();
      push(`- **Mechanism path:** ${orDash(h.mechanism_path)}`);
      push(`- **Supporting facts:** ${h.supporting_facts.length ? h.supporting_facts.join("; ") : DASH}`);
      push(`- **Contradicting facts:** ${h.contradicting_facts.length ? h.contradicting_facts.join("; ") : DASH}`);
      push(`- **Unknowns:** ${h.unknowns.length ? h.unknowns.join("; ") : DASH}`);
      push(`- **Expected asset roles:** ${h.expected_asset_roles.length ? h.expected_asset_roles.join(", ") : DASH}`);
      push(`- **Falsifiers:** ${h.falsifiers.length ? h.falsifiers.join("; ") : DASH}`);
      push();
    }

  // Asset roles
  push("## Asset-role map");
  push();
  if (b.asset_roles.length === 0) push(NONE);
  else {
    push("| Asset | Role | Benchmark | Sector / lens | Expected channel | Observed move | Window | Basis | Limitations | As of |");
    push("|---|---|---|---|---|---|---|---|---|---|");
    for (const a of b.asset_roles) {
      push(
        `| ${cell(a.asset)} | ${cell(a.role)} | ${cell(a.benchmark)} | ${cell(a.sector_or_relative_lens)} | ${cell(a.expected_channel)} | ${cell(a.observed_move)} | ${cell(a.window)} | ${cell(a.basis)} | ${cell(a.limitations)} | ${cell(a.as_of)} |`,
      );
    }
  }
  push();

  // Market reactions
  push("## Market-reaction observations");
  push();
  if (b.market_reactions.length === 0) push(NONE);
  else {
    push("| Horizon | Value | Basis | Window | Source | As of |");
    push("|---|---|---|---|---|---|");
    for (const m of b.market_reactions) {
      push(`| ${cell(m.horizon)} | ${cell(reactionValue(m))} | ${cell(m.basis)} | ${cell(m.window)} | ${cell(m.source)} | ${cell(m.as_of)} |`);
    }
  }
  push();

  // Historical context
  push("## Historical research context");
  push();
  push(`_${HISTORICAL_CONTEXT_DISCLAIMER}_`);
  push();
  if (b.historical_context.comparable_cohort === "NONE") push(NO_COMPARABLE_COHORT);
  else push(`**Declared comparable cohort:** ${b.historical_context.comparable_cohort}`);
  push();
  push(`**Notes:** ${orDash(b.historical_context.notes)}`);
  push();

  // Falsifiers
  push("## Falsifiers");
  push();
  if (b.falsifiers.length === 0) push(NONE);
  else {
    push("| Statement | Linked hypothesis | Observable | Window | Status | Evidence | As of |");
    push("|---|---|---|---|---|---|---|");
    for (const f of b.falsifiers) {
      push(
        `| ${cell(f.statement)} | ${cell(f.linked_hypothesis)} | ${cell(f.observable)} | ${cell(f.evaluation_window)} | ${cell(f.status)} | ${cell(f.evidence)} | ${cell(f.as_of)} |`,
      );
    }
  }
  push();

  // Follow-up plan
  const overdue = new Set(overdueFollowUps(b).map((f) => f.follow_up_id));
  push("## Follow-up plan");
  push();
  if (b.follow_up_checks.length === 0) push(NONE);
  else {
    push("| Question | Linked hypothesis | Due stage | Status | Overdue | Result | As of |");
    push("|---|---|---|---|---|---|---|");
    for (const f of b.follow_up_checks) {
      const od = overdue.has(f.follow_up_id) ? "yes" : "no";
      push(`| ${cell(f.question)} | ${cell(f.linked_hypothesis)} | ${cell(f.due_stage)} | ${cell(f.status)} | ${od} | ${cell(f.result)} | ${cell(f.as_of)} |`);
    }
  }
  push();

  // Revision log
  push("## Revision log");
  push();
  if (b.revision_log.length === 0) push(NONE);
  else
    for (const r of b.revision_log) {
      const link = r.linked_fact_or_falsifier.trim() ? `  ·  link: ${r.linked_fact_or_falsifier.trim()}` : "";
      push(`- \`${r.timestamp}\` **[${r.stage}]** ${orDash(r.what_changed)} — ${orDash(r.why_it_changed)}${link}`);
    }
  push();

  // Claim ceiling + non-claim
  push("## Claim ceiling");
  push();
  push(orDash(b.claim_ceiling));
  push();
  push("## Non-claim");
  push();
  push(b.non_claim);
  push();

  push("---");
  push(`_Exported ${exportedAt} · Second Order — Live Event Brief (${b.schema_version})_`);

  return L.join("\n") + "\n";
}
