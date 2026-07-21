/**
 * validate.ts — the one exact validator for stored and imported briefs.
 *
 * Fail-closed and non-permissive: a value is a valid ``live-event-brief-v1``
 * brief only when every required field is present, correctly typed, and drawn
 * from the frozen vocabulary.  There is no partial parsing and no silent
 * coercion — a malformed brief is rejected whole, with a list of reasons.
 *
 * The validator is the shared gate for storage load, JSON import, and the
 * export round-trip, so the clean-clone browser and the maintainer machine
 * evaluate exactly the same contract.
 */
import {
  AGGREGATE_MISSION_LABELS,
  ASSET_ROLES,
  COMPARABLE_COHORTS,
  ENTRY_TYPES,
  FALSIFIER_STATUSES,
  FOLLOW_UP_STAGES,
  FOLLOW_UP_STATUSES,
  HYPOTHESIS_STATES,
  MAX_ACTIVE_HYPOTHESES,
  NON_CLAIM,
  REACTION_HORIZONS,
  SCHEMA_VERSION,
  STAGES,
  type Brief,
} from "./types";

export type ValidationResult =
  | { ok: true; brief: Brief }
  | { ok: false; errors: string[] };

// ---------------------------------------------------------------------------
// Small predicates
// ---------------------------------------------------------------------------

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}
function isString(v: unknown): v is string {
  return typeof v === "string";
}
function isNonEmpty(v: unknown): v is string {
  return typeof v === "string" && v.trim().length > 0;
}
function isStringArray(v: unknown): v is string[] {
  return Array.isArray(v) && v.every(isString);
}
function inSet<T extends string>(v: unknown, set: readonly T[]): v is T {
  return typeof v === "string" && (set as readonly string[]).includes(v);
}

/**
 * True when ``token`` appears in ``text`` as a standalone token (not merged
 * into a longer word).  Case-sensitive, so an injected uppercase frozen label
 * is caught while ordinary lowercase prose ("volatility was elevated") is not.
 */
function hasStandaloneToken(text: string, token: string): boolean {
  if (!text || !token) return false;
  const isWord = (c: string) => /[A-Za-z0-9_]/.test(c);
  let from = 0;
  for (;;) {
    const idx = text.indexOf(token, from);
    if (idx === -1) return false;
    const before = idx > 0 ? text[idx - 1] ?? "" : "";
    const after = idx + token.length < text.length ? text[idx + token.length] ?? "" : "";
    if (!isWord(before) && !isWord(after)) return true;
    from = idx + 1;
  }
}

/** Any frozen aggregate Mission label present as a standalone token. */
function carriesAggregateLabel(text: unknown): boolean {
  if (!isString(text)) return false;
  return AGGREGATE_MISSION_LABELS.some((label) => hasStandaloneToken(text, label));
}

// ---------------------------------------------------------------------------
// Validator
// ---------------------------------------------------------------------------

export function validateBrief(value: unknown): ValidationResult {
  const errors: string[] = [];
  const err = (m: string) => errors.push(m);

  if (!isObject(value)) {
    return { ok: false, errors: ["brief is not an object"] };
  }
  const b = value as Record<string, unknown>;

  // --- identity + schema version ------------------------------------------
  if (b.schema_version !== SCHEMA_VERSION) {
    err(`schema_version must be "${SCHEMA_VERSION}"`);
  }
  if (!isNonEmpty(b.brief_id)) err("brief_id is missing or empty");

  // --- simple string fields -----------------------------------------------
  for (const f of [
    "title",
    "event_family",
    "event_type",
    "event_date",
    "scheduled_timestamp",
    "timezone",
    "claim_ceiling",
  ] as const) {
    if (!isString(b[f])) err(`${f} must be a string`);
  }

  // --- timestamps ----------------------------------------------------------
  if (!isNonEmpty(b.created_at)) err("created_at is missing or empty");
  if (!isNonEmpty(b.updated_at)) err("updated_at is missing or empty");

  // --- stage ---------------------------------------------------------------
  if (!inSet(b.current_stage, STAGES)) err("current_stage is not a valid stage");

  // --- non-claim (exact, always present) ----------------------------------
  if (b.non_claim !== NON_CLAIM) err("non_claim is missing or altered");

  // --- source references ---------------------------------------------------
  if (!Array.isArray(b.source_references)) {
    err("source_references must be an array");
  } else {
    b.source_references.forEach((s, i) => {
      if (!isObject(s)) return err(`source_references[${i}] is not an object`);
      if (!isNonEmpty(s.id)) err(`source_references[${i}].id is missing`);
      for (const f of ["label", "url", "note"] as const) {
        if (!isString(s[f])) err(`source_references[${i}].${f} must be a string`);
      }
    });
  }

  // --- typed entries (fact_summary + known_unknowns) ----------------------
  const validateEntries = (key: "fact_summary" | "known_unknowns") => {
    const arr = b[key];
    if (!Array.isArray(arr)) return err(`${key} must be an array`);
    arr.forEach((e, i) => {
      if (!isObject(e)) return err(`${key}[${i}] is not an object`);
      if (!isNonEmpty(e.id)) err(`${key}[${i}].id is missing`);
      if (!inSet(e.type, ENTRY_TYPES)) {
        err(`${key}[${i}].type must be one of ${ENTRY_TYPES.join(" / ")}`);
      }
      if (!isString(e.text)) err(`${key}[${i}].text must be a string`);
      if (!isString(e.source_reference)) err(`${key}[${i}].source_reference must be a string`);
      if (!isString(e.source_note)) err(`${key}[${i}].source_note must be a string`);
      if (!isNonEmpty(e.as_of)) err(`${key}[${i}].as_of is missing`);
      // A FACT must carry a source reference or an explicit "no source yet" note.
      if (e.type === "FACT" && !isNonEmpty(e.source_reference) && !isNonEmpty(e.source_note)) {
        err(`${key}[${i}] is a FACT with no source_reference and no source_note`);
      }
      if (carriesAggregateLabel(e.text)) {
        err(`${key}[${i}].text injects an aggregate Mission label as a live verdict`);
      }
    });
  };
  validateEntries("fact_summary");
  validateEntries("known_unknowns");

  // --- delta_vs_prior ------------------------------------------------------
  if (!isObject(b.delta_vs_prior)) {
    err("delta_vs_prior must be an object");
  } else {
    const d = b.delta_vs_prior;
    for (const f of [
      "previous_state",
      "new_information",
      "unchanged_information",
      "unresolved_information",
      "operator_delta_summary",
    ] as const) {
      if (!isString(d[f])) err(`delta_vs_prior.${f} must be a string`);
    }
    if (carriesAggregateLabel(d.operator_delta_summary)) {
      err("delta_vs_prior.operator_delta_summary injects an aggregate Mission label");
    }
  }

  // --- mechanism hypotheses ------------------------------------------------
  if (!Array.isArray(b.mechanism_hypotheses)) {
    err("mechanism_hypotheses must be an array");
  } else {
    const ids = new Set<string>();
    let active = 0;
    b.mechanism_hypotheses.forEach((h, i) => {
      if (!isObject(h)) return err(`mechanism_hypotheses[${i}] is not an object`);
      if (!isNonEmpty(h.hypothesis_id)) {
        err(`mechanism_hypotheses[${i}].hypothesis_id is missing`);
      } else {
        if (ids.has(h.hypothesis_id)) err(`duplicate hypothesis_id "${h.hypothesis_id}"`);
        ids.add(h.hypothesis_id);
      }
      if (!isString(h.name)) err(`mechanism_hypotheses[${i}].name must be a string`);
      if (!isString(h.mechanism_path)) err(`mechanism_hypotheses[${i}].mechanism_path must be a string`);
      for (const f of [
        "supporting_facts",
        "contradicting_facts",
        "unknowns",
        "expected_asset_roles",
        "falsifiers",
      ] as const) {
        if (!isStringArray(h[f])) err(`mechanism_hypotheses[${i}].${f} must be a string[]`);
      }
      if (!inSet(h.current_state, HYPOTHESIS_STATES)) {
        err(`mechanism_hypotheses[${i}].current_state is not a valid hypothesis state`);
      } else if (h.current_state !== "FALSIFIED") {
        active += 1;
      }
      if (carriesAggregateLabel(h.name) || carriesAggregateLabel(h.mechanism_path)) {
        err(`mechanism_hypotheses[${i}] injects an aggregate Mission label as a live verdict`);
      }
    });
    if (active > MAX_ACTIVE_HYPOTHESES) {
      err(`more than ${MAX_ACTIVE_HYPOTHESES} active (non-falsified) hypotheses`);
    }
  }

  // --- asset roles ---------------------------------------------------------
  if (!Array.isArray(b.asset_roles)) {
    err("asset_roles must be an array");
  } else {
    b.asset_roles.forEach((a, i) => {
      if (!isObject(a)) return err(`asset_roles[${i}] is not an object`);
      if (!isNonEmpty(a.id)) err(`asset_roles[${i}].id is missing`);
      if (!isString(a.asset)) err(`asset_roles[${i}].asset must be a string`);
      if (!inSet(a.role, ASSET_ROLES)) err(`asset_roles[${i}].role is not a supported asset role`);
      for (const f of [
        "benchmark",
        "sector_or_relative_lens",
        "expected_channel",
        "observed_move",
        "window",
        "basis",
        "limitations",
      ] as const) {
        if (!isString(a[f])) err(`asset_roles[${i}].${f} must be a string`);
      }
      if (!isNonEmpty(a.as_of)) err(`asset_roles[${i}].as_of is missing`);
      if (carriesAggregateLabel(a.observed_move)) {
        err(`asset_roles[${i}].observed_move injects an aggregate Mission label`);
      }
    });
  }

  // --- market reactions ----------------------------------------------------
  if (!Array.isArray(b.market_reactions)) {
    err("market_reactions must be an array");
  } else {
    b.market_reactions.forEach((m, i) => {
      if (!isObject(m)) return err(`market_reactions[${i}] is not an object`);
      if (!isNonEmpty(m.id)) err(`market_reactions[${i}].id is missing`);
      if (!inSet(m.horizon, REACTION_HORIZONS)) {
        err(`market_reactions[${i}].horizon is not a valid horizon`);
      }
      const value = m.value;
      const numeric = typeof value === "number" && Number.isFinite(value);
      if (value !== null && !numeric) {
        err(`market_reactions[${i}].value must be a finite number or null`);
      }
      for (const f of ["unit", "basis", "window", "source"] as const) {
        if (!isString(m[f])) err(`market_reactions[${i}].${f} must be a string`);
      }
      if (!isNonEmpty(m.as_of)) err(`market_reactions[${i}].as_of is missing`);
      // A numeric observation must state its basis.
      if (numeric && !isNonEmpty(m.basis)) {
        err(`market_reactions[${i}] has a numeric value but no basis`);
      }
      if (carriesAggregateLabel(m.source) || carriesAggregateLabel(m.basis)) {
        err(`market_reactions[${i}] injects an aggregate Mission label`);
      }
    });
  }

  // --- historical context --------------------------------------------------
  if (!isObject(b.historical_context)) {
    err("historical_context must be an object");
  } else {
    if (!inSet(b.historical_context.comparable_cohort, COMPARABLE_COHORTS)) {
      err("historical_context.comparable_cohort is not a valid cohort declaration");
    }
    if (!isString(b.historical_context.notes)) {
      err("historical_context.notes must be a string");
    }
  }

  // --- falsifiers ----------------------------------------------------------
  if (!Array.isArray(b.falsifiers)) {
    err("falsifiers must be an array");
  } else {
    const ids = new Set<string>();
    b.falsifiers.forEach((f, i) => {
      if (!isObject(f)) return err(`falsifiers[${i}] is not an object`);
      if (!isNonEmpty(f.falsifier_id)) {
        err(`falsifiers[${i}].falsifier_id is missing`);
      } else {
        if (ids.has(f.falsifier_id)) err(`duplicate falsifier_id "${f.falsifier_id}"`);
        ids.add(f.falsifier_id);
      }
      for (const k of ["statement", "linked_hypothesis", "observable", "evaluation_window", "evidence"] as const) {
        if (!isString(f[k])) err(`falsifiers[${i}].${k} must be a string`);
      }
      if (!inSet(f.status, FALSIFIER_STATUSES)) {
        err(`falsifiers[${i}].status is not a valid falsifier status`);
      }
      if (!isNonEmpty(f.as_of)) err(`falsifiers[${i}].as_of is missing`);
      if (carriesAggregateLabel(f.statement) || carriesAggregateLabel(f.evidence)) {
        err(`falsifiers[${i}] injects an aggregate Mission label`);
      }
    });
  }

  // --- follow-up checks ----------------------------------------------------
  if (!Array.isArray(b.follow_up_checks)) {
    err("follow_up_checks must be an array");
  } else {
    const ids = new Set<string>();
    b.follow_up_checks.forEach((f, i) => {
      if (!isObject(f)) return err(`follow_up_checks[${i}] is not an object`);
      if (!isNonEmpty(f.follow_up_id)) {
        err(`follow_up_checks[${i}].follow_up_id is missing`);
      } else {
        if (ids.has(f.follow_up_id)) err(`duplicate follow_up_id "${f.follow_up_id}"`);
        ids.add(f.follow_up_id);
      }
      if (!isString(f.question)) err(`follow_up_checks[${i}].question must be a string`);
      if (!isString(f.linked_hypothesis)) err(`follow_up_checks[${i}].linked_hypothesis must be a string`);
      if (!isString(f.result)) err(`follow_up_checks[${i}].result must be a string`);
      if (!inSet(f.due_stage, FOLLOW_UP_STAGES)) {
        err(`follow_up_checks[${i}].due_stage is not a valid follow-up stage`);
      }
      if (!inSet(f.status, FOLLOW_UP_STATUSES)) {
        err(`follow_up_checks[${i}].status is not a valid follow-up status`);
      }
      if (!isNonEmpty(f.as_of)) err(`follow_up_checks[${i}].as_of is missing`);
      if (carriesAggregateLabel(f.result)) {
        err(`follow_up_checks[${i}].result injects an aggregate Mission label`);
      }
    });
  }

  // --- revision log --------------------------------------------------------
  if (!Array.isArray(b.revision_log)) {
    err("revision_log must be an array");
  } else {
    b.revision_log.forEach((r, i) => {
      if (!isObject(r)) return err(`revision_log[${i}] is not an object`);
      if (!isNonEmpty(r.id)) err(`revision_log[${i}].id is missing`);
      if (!isNonEmpty(r.timestamp)) err(`revision_log[${i}].timestamp is missing`);
      if (!inSet(r.stage, STAGES)) err(`revision_log[${i}].stage is not a valid stage`);
      for (const k of ["what_changed", "why_it_changed", "linked_fact_or_falsifier"] as const) {
        if (!isString(r[k])) err(`revision_log[${i}].${k} must be a string`);
      }
    });
  }

  // --- claim ceiling never widens past the fixed non-claim -----------------
  if (isString(b.claim_ceiling) && carriesAggregateLabel(b.claim_ceiling)) {
    err("claim_ceiling injects an aggregate Mission label as a live verdict");
  }

  if (errors.length > 0) return { ok: false, errors };
  return { ok: true, brief: value as unknown as Brief };
}

/** Type-guard convenience over {@link validateBrief}. */
export function isValidBrief(value: unknown): value is Brief {
  return validateBrief(value).ok;
}
