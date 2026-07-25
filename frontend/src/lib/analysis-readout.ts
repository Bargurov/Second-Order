/**
 * analysis-readout.ts — pure presentation model for the mechanism and
 * resolution readout (A1-3).
 *
 * WHAT THIS DOES
 * --------------
 * Reorganizes fields the analysis engine ALREADY returned into the frozen
 * research chain:
 *
 *     mechanism → exposure → counterforces → falsifiers → resolution → limits
 *
 * WHAT THIS DOES NOT DO
 * ---------------------
 * No analysis, no scoring, no ranking, no fallback content, no merging of
 * things the contract keeps apart.  An indirect channel is not a primary
 * asset; a monitoring item is not a falsifier; a competing thesis is not a
 * footnote on the primary one.  A field the engine did not return reads as
 * explicitly unavailable — never as an empty success, and never as evidence
 * that the question was considered and came back clean.
 *
 * The input is never mutated.
 */

/** The frozen order.  Rendering follows this; nothing reorders it. */
export const READOUT_SECTION_ORDER = [
  "mechanism", "exposure", "counterforces", "falsifiers", "resolution", "limits",
] as const;
export type ReadoutSection = (typeof READOUT_SECTION_ORDER)[number];

/** Rendered wherever the mechanism is shown. */
export const MECHANISM_NON_CLAIM =
  "This is a structured mechanism hypothesis, not a causal estimate.";

/** Attached to free-form text the model wrote rather than a validated field. */
export const MODEL_GENERATED_LABEL =
  "Model-generated challenge text — not a validated field.";

/** A single value that may be absent.  `available` is never inferred. */
export interface Field<T> {
  available: boolean;
  value: T | null;
}

/** A list that may be absent.  Empty and absent are the same honest state. */
export interface ListField {
  available: boolean;
  values: string[];
  /** `role` = an economic actor; `asset` = a named instrument.  Kept apart. */
  kind: "role" | "asset" | "channel" | "item";
}

export interface PathStep {
  step: number | null;
  node: string;
  soWhat: string | null;
}

export interface Counterforce {
  force: string;
  effect: string | null;
  likelihood: string | null;
}

export interface HorizonItem {
  horizon: string;
  detail: string;
}

export interface StatusField {
  available: boolean;
  label: string;
}

export interface AnalysisReadout {
  mechanism: {
    summary: Field<string>;
    path: PathStep[];
    pathLabel: string;
    transmissionType: Field<string>;
    bottleneckType: Field<string>;
  };
  exposure: {
    directPositive: ListField;
    directNegative: ListField;
    primaryAssets: ListField;
    secondaryAssets: ListField;
    hedgeOrSignal: ListField;
    indirectChannels: ListField;
  };
  counterforces: {
    forces: { available: boolean; values: Counterforce[] };
    substitutionBarriers: ListField;
    escapePath: Field<string>;
    competingThesis: Field<Record<string, string>>;
    adversarialChallenge: Field<string> & { provenanceLabel: string };
  };
  falsifiers: {
    keyFalsifiers: ListField;
    minimumProof: ListField;
    criticalBreakpoints: ListField;
    proofStatus: StatusField;
    falsifierStatus: StatusField;
  };
  resolution: {
    horizons: HorizonItem[];
    monitorPlan: ListField;
    confirmingEvidence: ListField;
    evidenceToRevisit: ListField;
  };
  limits: {
    qualityTier: Field<string>;
    qualityWarnings: ListField;
    validationWarnings: ListField;
    degraded: boolean;
    sourceQuality: Field<string>;
    evidenceLimitations: ListField;
    regimeCaveat: Field<string>;
    /** True when a degraded state or any warning exists — the surface must
     *  not tuck these behind a disclosure when this is set. */
    prominent: boolean;
  };
}

// ---------------------------------------------------------------------------
// Primitives
// ---------------------------------------------------------------------------

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function field(value: unknown): Field<string> {
  const ok = typeof value === "string" && value.trim() !== "";
  return { available: ok, value: ok ? (value as string) : null };
}

function list(value: unknown, kind: ListField["kind"]): ListField {
  const values = Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string" && v.trim() !== "")
    : [];
  return { available: values.length > 0, values, kind };
}

/** Statuses are reported as the engine stated them; absence reads as unknown,
 *  which must never be presented as a passed or satisfied test. */
function status(value: unknown): StatusField {
  const raw = isRecord(value)
    ? value.status ?? value.state ?? null
    : typeof value === "string" ? value : null;
  if (typeof raw !== "string" || raw.trim() === "") {
    return { available: false, label: "Not reported" };
  }
  return { available: true, label: raw.replace(/_/g, " ") };
}

// ---------------------------------------------------------------------------
// Quality tier
// ---------------------------------------------------------------------------

/**
 * Display copy for the stored `quality_tier` enum.
 *
 * The API values are unchanged — only the reader-facing wording is translated,
 * because the stored token `actionable` reads as a trade instruction to a
 * finance reviewer and this surface makes no recommendations.  An unrecognized
 * tier passes through verbatim rather than being rounded to a nearby rating.
 */
export function qualityTierLabel(tier: string | null | undefined): string | null {
  if (typeof tier !== "string" || tier.trim() === "") return null;
  switch (tier) {
    case "low_information": return "Limited information";
    case "watch_only": return "Monitor / insufficiently resolved";
    case "actionable": return "Sufficiently specified for research review";
    default: return tier;
  }
}

// ---------------------------------------------------------------------------
// Builder
// ---------------------------------------------------------------------------

function buildPath(value: unknown): PathStep[] {
  if (!Array.isArray(value)) return [];
  const out: PathStep[] = [];
  for (const raw of value) {
    if (!isRecord(raw)) continue;
    const node = typeof raw.node === "string" ? raw.node
      : typeof raw.step_label === "string" ? raw.step_label : "";
    if (!node.trim()) continue;
    out.push({
      step: typeof raw.step === "number" ? raw.step : null,
      node,
      soWhat: typeof raw.so_what === "string" && raw.so_what.trim()
        ? raw.so_what : null,
    });
  }
  return out;
}

function buildForces(value: unknown): Counterforce[] {
  if (!Array.isArray(value)) return [];
  const out: Counterforce[] = [];
  for (const raw of value) {
    if (!isRecord(raw)) continue;
    const force = typeof raw.force === "string" ? raw.force
      : typeof raw.counterforce === "string" ? raw.counterforce : "";
    if (!force.trim()) continue;
    out.push({
      force,
      effect: typeof raw.effect === "string" && raw.effect.trim() ? raw.effect : null,
      likelihood: typeof raw.likelihood === "string" && raw.likelihood.trim()
        ? raw.likelihood : null,
    });
  }
  return out;
}

function buildBarriers(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const out: string[] = [];
  for (const raw of value) {
    if (typeof raw === "string" && raw.trim()) { out.push(raw); continue; }
    if (!isRecord(raw)) continue;
    const label = typeof raw.barrier === "string" ? raw.barrier : "";
    if (!label.trim()) continue;
    const severity = typeof raw.severity === "string" ? raw.severity : "";
    out.push(severity ? `${label} (${severity})` : label);
  }
  return out;
}

/** Horizon keys in the order a reviewer reads them; unknown keys follow. */
const _HORIZON_ORDER = ["1d", "5d", "20d", "60d", "90d"];

function buildHorizons(value: unknown): HorizonItem[] {
  if (!isRecord(value)) return [];
  const entries: HorizonItem[] = [];
  for (const [horizon, detail] of Object.entries(value)) {
    if (typeof detail !== "string" || !detail.trim()) continue;
    entries.push({ horizon, detail });
  }
  entries.sort((a, b) => {
    const ia = _HORIZON_ORDER.indexOf(a.horizon);
    const ib = _HORIZON_ORDER.indexOf(b.horizon);
    if (ia === -1 && ib === -1) return a.horizon.localeCompare(b.horizon);
    if (ia === -1) return 1;
    if (ib === -1) return -1;
    return ia - ib;
  });
  return entries;
}

function competingThesis(value: unknown): Field<Record<string, string>> {
  if (!isRecord(value)) return { available: false, value: null };
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(value)) {
    if (typeof v === "string" && v.trim()) out[k] = v;
  }
  const ok = Object.keys(out).length > 0;
  return { available: ok, value: ok ? out : null };
}

/**
 * Build the presentation model from one analysis payload.
 *
 * Accepts anything: a malformed or absent payload yields a fully-unavailable
 * readout rather than throwing, because a reviewer seeing "unavailable" is
 * correct while a blank page is not.
 */
export function buildReadout(analysis: unknown): AnalysisReadout {
  const a: Record<string, unknown> = isRecord(analysis) ? analysis : {};
  const hidden: Record<string, unknown> =
    isRecord(a.hidden_mechanism) ? a.hidden_mechanism : {};
  const sourceQuality: Record<string, unknown> =
    isRecord(hidden.source_quality) ? hidden.source_quality : {};
  const regimeCaveats: Record<string, unknown> =
    isRecord(hidden.regime_caveats) ? hidden.regime_caveats : {};

  const qualityWarnings = list(a.quality_warnings, "item");
  const validationWarnings = list(a.validation_warnings, "item");
  const degraded = a.degraded === true;

  return {
    mechanism: {
      summary: field(a.mechanism_summary),
      path: buildPath(a.transmission_path),
      // Deliberately not "causal chain": the engine emits an ordered
      // hypothesis, and the label must not upgrade it.
      pathLabel: "Ordered transmission steps as stated by the analysis",
      transmissionType: field(hidden.transmission_type),
      bottleneckType: field(hidden.bottleneck_type),
    },
    exposure: {
      directPositive: list(a.beneficiaries, "role"),
      directNegative: list(a.losers, "role"),
      primaryAssets: list(a.primary_assets, "asset"),
      secondaryAssets: list(a.secondary_assets, "asset"),
      hedgeOrSignal: list(a.hedge_or_signal_assets, "asset"),
      indirectChannels: list(a.expected_second_order_channels, "channel"),
    },
    counterforces: {
      forces: {
        available: buildForces(a.counterforces).length > 0,
        values: buildForces(a.counterforces),
      },
      substitutionBarriers: {
        available: buildBarriers(a.substitution_barriers).length > 0,
        values: buildBarriers(a.substitution_barriers),
        kind: "item",
      },
      escapePath: field(hidden.substitution_escape_path),
      competingThesis: competingThesis(a.competing_thesis),
      adversarialChallenge: {
        ...field(a.adversarial_challenge),
        provenanceLabel: MODEL_GENERATED_LABEL,
      },
    },
    falsifiers: {
      keyFalsifiers: list(a.key_falsifiers, "item"),
      minimumProof: list(a.minimum_proof_set, "item"),
      criticalBreakpoints: list(hidden.critical_breakpoints, "item"),
      proofStatus: status(a.proof_status),
      falsifierStatus: status(a.falsifier_status),
    },
    resolution: {
      horizons: buildHorizons(a.horizon_checkpoints),
      monitorPlan: list(a.monitor_plan, "item"),
      confirmingEvidence: list(hidden.optional_confirming_evidence, "item"),
      evidenceToRevisit: list(regimeCaveats.evidence_to_revisit, "item"),
    },
    limits: {
      qualityTier: field(a.quality_tier),
      qualityWarnings,
      validationWarnings,
      degraded,
      sourceQuality: field(sourceQuality.tier),
      evidenceLimitations: list(sourceQuality.evidence_limitations, "item"),
      regimeCaveat: field(a.regime_conditioned_caveat),
      prominent: degraded || qualityWarnings.available || validationWarnings.available,
    },
  };
}
