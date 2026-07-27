/**
 * Mechanism & Resolution Readout — pure presentation model (A1-3, repaired in
 * A2-1 to consume the REAL finalized analysis contract).
 *
 * The backend finalizer (`analyze_event._finalize_analysis`) emits typed
 * structures: transmission hops `{hop, action, channel, actor,
 * expected_market_effect, timing}`, counterforces with a `kind`
 * (counterforce | blocker) and an optional `chain_hop` link, barrier
 * `{barrier, kind, severity}`, structured breakpoints / proof / confirming
 * evidence, ranked asset objects, the canonical `{timing_profile, horizons}`
 * checkpoint shape, the monitor-plan dict, regime-caveat entries and the
 * `source_quality` block.  This adapter consumes exactly those shapes — the
 * committed fixture `__tests__/fixtures/finalized-analysis-readout.json` is
 * proven byte-equal to real finalizer output by
 * `tests/test_readout_fixture_fidelity.py`, so producer and consumer cannot
 * drift apart silently.
 *
 * Honesty rules: availability is never inferred; a malformed entry is skipped,
 * never repaired; legacy plain-string entries in list fields stay readable as
 * observation-only items; nothing here upgrades a hypothesis into a finding.
 */

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

/** One transmission hop as the finalizer emits it, in declared order. */
export interface TransmissionStep {
  /** 1-based declared position — order IS the stated hypothesis. */
  sequence: number;
  action: string;
  actor: string | null;
  /** Typed channel token; `unclassified` reads as null (no pseudo-type). */
  channel: string | null;
  expectedMarketEffect: string | null;
  timing: string | null;
}

export interface CounterforceItem {
  force: string;
  actor: string | null;
  likelihood: string | null;
  /** `blocker` interrupts the chain itself; `counterforce` weakens it after. */
  kind: "counterforce" | "blocker";
  /** Free-text pointer to the transmission step a blocker hits, when given. */
  linkedHop: string | null;
}

export interface BarrierItem {
  barrier: string;
  /** Typed kind; `unclassified` reads as null. */
  kind: string | null;
  severity: string | null;
}

export interface BreakpointItem {
  observation: string;
  channel: string | null;
  threshold: string | null;
  timing: string | null;
  condition: string | null;
  thresholdOrObservation: string | null;
  whyItChangesThesis: string | null;
  linkedProofOrFalsifier: string | null;
}

export interface ProofItem {
  observation: string;
  channel: string | null;
  threshold: string | null;
  timing: string | null;
}

export interface EvidenceItem {
  observation: string;
  channel: string | null;
}

export interface RankedAsset {
  symbol: string;
  rank: number | null;
  rationale: string | null;
}

export interface HorizonCheckpoint {
  horizon: string;
  expected: string[];
  confirmsIf: string[];
  falsifiesIf: string[];
}

export interface MonitorTell {
  observation: string;
  channel: string | null;
  whatItMeans: string | null;
}

export interface NoCallSignal {
  observation: string;
  channel: string | null;
  whyNoCall: string | null;
}

export interface RegimeCaveatItem {
  condition: string;
  effectOnThesis: string | null;
  evidenceToRevisit: string | null;
  domain: string | null;
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
    path: TransmissionStep[];
    pathLabel: string;
    transmissionType: Field<string>;
    bottleneckType: Field<string>;
  };
  exposure: {
    directPositive: ListField;
    directNegative: ListField;
    primaryAssets: { available: boolean; values: RankedAsset[] };
    secondaryAssets: { available: boolean; values: RankedAsset[] };
    hedgeOrSignal: { available: boolean; values: RankedAsset[] };
    indirectChannels: ListField;
  };
  counterforces: {
    forces: { available: boolean; values: CounterforceItem[] };
    substitutionBarriers: { available: boolean; values: BarrierItem[] };
    escapePath: Field<string>;
    competingThesis: Field<Record<string, string>>;
    adversarialChallenge: Field<string> & { provenanceLabel: string };
  };
  falsifiers: {
    keyFalsifiers: ListField;
    minimumProof: { available: boolean; values: ProofItem[] };
    criticalBreakpoints: { available: boolean; values: BreakpointItem[] };
    proofStatus: StatusField;
    falsifierStatus: StatusField;
  };
  resolution: {
    horizons: {
      timingProfile: string | null;
      checkpoints: HorizonCheckpoint[];
      /** Legacy flat `{horizon: detail}` entries from older saved rows. */
      legacy: HorizonItem[];
    };
    monitorPlan: {
      available: boolean;
      tell: MonitorTell | null;
      noCallSignals: NoCallSignal[];
    };
    confirmingEvidence: { available: boolean; values: EvidenceItem[] };
    evidenceToRevisit: { available: boolean; values: RegimeCaveatItem[] };
  };
  limits: {
    qualityTier: Field<string>;
    qualityWarnings: ListField;
    validationWarnings: ListField;
    degraded: boolean;
    sourceQuality: Field<string>;
    sourceSpecificity: Field<string>;
    sourceUncertainty: Field<string>;
    /** The finalizer emits one bounded sentence, not a list. */
    evidenceLimitations: Field<string>;
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

function str(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
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

/** The sanitizer's "no semantics promised" token reads as absent. */
function typedToken(value: unknown): string | null {
  const s = str(value);
  return s && s !== "unclassified" ? s : null;
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
// Structured builders — one per finalized producer shape
// ---------------------------------------------------------------------------

/** `transmission_path` — hop dicts in causal order; strings stay readable. */
function buildPath(value: unknown): TransmissionStep[] {
  if (!Array.isArray(value)) return [];
  const out: TransmissionStep[] = [];
  for (const raw of value) {
    if (typeof raw === "string" && raw.trim()) {
      out.push({
        sequence: out.length + 1, action: raw, actor: null, channel: null,
        expectedMarketEffect: null, timing: null,
      });
      continue;
    }
    if (!isRecord(raw)) continue;
    const action = str(raw.action) ?? str(raw.hop);
    if (!action) continue;
    out.push({
      sequence: out.length + 1,
      action,
      actor: str(raw.actor),
      channel: typedToken(raw.channel),
      expectedMarketEffect: str(raw.expected_market_effect),
      timing: str(raw.timing),
    });
  }
  return out;
}

function buildForces(value: unknown): CounterforceItem[] {
  if (!Array.isArray(value)) return [];
  const out: CounterforceItem[] = [];
  for (const raw of value) {
    if (!isRecord(raw)) continue;
    const force = str(raw.force);
    if (!force) continue;
    out.push({
      force,
      actor: str(raw.actor),
      likelihood: str(raw.likelihood),
      kind: raw.kind === "blocker" ? "blocker" : "counterforce",
      linkedHop: str(raw.chain_hop),
    });
  }
  return out;
}

function buildBarriers(value: unknown): BarrierItem[] {
  if (!Array.isArray(value)) return [];
  const out: BarrierItem[] = [];
  for (const raw of value) {
    if (typeof raw === "string" && raw.trim()) {
      out.push({ barrier: raw, kind: null, severity: null });
      continue;
    }
    if (!isRecord(raw)) continue;
    const barrier = str(raw.barrier);
    if (!barrier) continue;
    out.push({
      barrier,
      kind: typedToken(raw.kind),
      severity: str(raw.severity),
    });
  }
  return out;
}

/** Breakpoint / proof entries carry the observation under `observation` or
 *  the legacy `signal` key — the finalizer preserves whichever it received. */
function buildBreakpoints(value: unknown): BreakpointItem[] {
  if (!Array.isArray(value)) return [];
  const out: BreakpointItem[] = [];
  for (const raw of value) {
    if (typeof raw === "string" && raw.trim()) {
      out.push({
        observation: raw, channel: null, threshold: null, timing: null,
        condition: null, thresholdOrObservation: null,
        whyItChangesThesis: null, linkedProofOrFalsifier: null,
      });
      continue;
    }
    if (!isRecord(raw)) continue;
    const observation = str(raw.observation) ?? str(raw.signal);
    if (!observation) continue;
    out.push({
      observation,
      channel: str(raw.channel),
      threshold: str(raw.threshold),
      timing: str(raw.timing),
      condition: str(raw.condition),
      thresholdOrObservation: str(raw.threshold_or_observation),
      whyItChangesThesis: str(raw.why_it_changes_thesis),
      linkedProofOrFalsifier: str(raw.linked_proof_or_falsifier),
    });
  }
  return out;
}

function buildProof(value: unknown): ProofItem[] {
  if (!Array.isArray(value)) return [];
  const out: ProofItem[] = [];
  for (const raw of value) {
    if (typeof raw === "string" && raw.trim()) {
      out.push({ observation: raw, channel: null, threshold: null, timing: null });
      continue;
    }
    if (!isRecord(raw)) continue;
    const observation = str(raw.observation) ?? str(raw.signal);
    if (!observation) continue;
    out.push({
      observation,
      channel: str(raw.channel),
      threshold: str(raw.threshold),
      timing: str(raw.timing),
    });
  }
  return out;
}

function buildEvidence(value: unknown): EvidenceItem[] {
  if (!Array.isArray(value)) return [];
  const out: EvidenceItem[] = [];
  for (const raw of value) {
    if (typeof raw === "string" && raw.trim()) {
      out.push({ observation: raw, channel: null });
      continue;
    }
    if (!isRecord(raw)) continue;
    const observation = str(raw.observation) ?? str(raw.signal);
    if (!observation) continue;
    out.push({ observation, channel: str(raw.channel) });
  }
  return out;
}

function buildRankedAssets(value: unknown): RankedAsset[] {
  if (!Array.isArray(value)) return [];
  const out: RankedAsset[] = [];
  for (const raw of value) {
    if (typeof raw === "string" && raw.trim()) {
      out.push({ symbol: raw, rank: null, rationale: null });
      continue;
    }
    if (!isRecord(raw)) continue;
    const symbol = str(raw.symbol);
    if (!symbol) continue;
    out.push({
      symbol,
      rank: typeof raw.rank === "number" ? raw.rank : null,
      rationale: str(raw.rationale),
    });
  }
  return out;
}

/** Horizon keys in the order a reviewer reads them; unknown keys follow. */
const _HORIZON_ORDER = ["1d", "5d", "20d", "60d", "90d"];

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string" && v.trim() !== "")
    : [];
}

function buildHorizons(value: unknown): AnalysisReadout["resolution"]["horizons"] {
  if (!isRecord(value)) return { timingProfile: null, checkpoints: [], legacy: [] };

  // Canonical finalizer shape: {timing_profile, horizons: [...]}.
  if (Array.isArray(value.horizons)) {
    const checkpoints: HorizonCheckpoint[] = [];
    for (const raw of value.horizons) {
      if (!isRecord(raw)) continue;
      const horizon = str(raw.horizon);
      if (!horizon) continue;
      const cp: HorizonCheckpoint = {
        horizon,
        expected: strings(raw.expected),
        confirmsIf: strings(raw.confirms_if),
        falsifiesIf: strings(raw.falsifies_if),
      };
      if (cp.expected.length || cp.confirmsIf.length || cp.falsifiesIf.length) {
        checkpoints.push(cp);
      }
    }
    const profile = str(value.timing_profile);
    return {
      timingProfile: profile && profile !== "unknown" ? profile : null,
      checkpoints,
      legacy: [],
    };
  }

  // Legacy flat `{horizon: detail}` entries from older saved rows.
  const legacy: HorizonItem[] = [];
  for (const [horizon, detail] of Object.entries(value)) {
    if (typeof detail !== "string" || !detail.trim()) continue;
    legacy.push({ horizon, detail });
  }
  legacy.sort((a, b) => {
    const ia = _HORIZON_ORDER.indexOf(a.horizon);
    const ib = _HORIZON_ORDER.indexOf(b.horizon);
    if (ia === -1 && ib === -1) return a.horizon.localeCompare(b.horizon);
    if (ia === -1) return 1;
    if (ib === -1) return -1;
    return ia - ib;
  });
  return { timingProfile: null, checkpoints: [], legacy };
}

function buildMonitorPlan(value: unknown): AnalysisReadout["resolution"]["monitorPlan"] {
  // Legacy saved rows may carry a flat list of strings; keep them readable.
  if (Array.isArray(value)) {
    const noCall = strings(value).map((observation) => ({
      observation, channel: null, whyNoCall: null,
    }));
    return { available: noCall.length > 0, tell: null, noCallSignals: noCall };
  }
  if (!isRecord(value)) return { available: false, tell: null, noCallSignals: [] };

  let tell: MonitorTell | null = null;
  if (isRecord(value.first_decisive_tell)) {
    const observation = str(value.first_decisive_tell.observation);
    if (observation) {
      tell = {
        observation,
        channel: str(value.first_decisive_tell.channel),
        whatItMeans: str(value.first_decisive_tell.what_it_means),
      };
    }
  }
  const noCallSignals: NoCallSignal[] = [];
  if (Array.isArray(value.no_call_signals)) {
    for (const raw of value.no_call_signals) {
      if (!isRecord(raw)) continue;
      const observation = str(raw.observation);
      if (!observation) continue;
      noCallSignals.push({
        observation,
        channel: str(raw.channel),
        whyNoCall: str(raw.why_no_call),
      });
    }
  }
  return {
    available: tell !== null || noCallSignals.length > 0,
    tell,
    noCallSignals,
  };
}

function buildRegimeCaveats(value: unknown): RegimeCaveatItem[] {
  if (!Array.isArray(value)) return [];
  const out: RegimeCaveatItem[] = [];
  for (const raw of value) {
    if (!isRecord(raw)) continue;
    const condition = str(raw.condition);
    if (!condition) continue;
    out.push({
      condition,
      effectOnThesis: str(raw.effect_on_thesis),
      evidenceToRevisit: str(raw.evidence_to_revisit),
      domain: str(raw.domain),
    });
  }
  return out;
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

  const qualityWarnings = list(a.quality_warnings, "item");
  const validationWarnings = list(a.validation_warnings, "item");
  const degraded = a.degraded === true;

  const forces = buildForces(a.counterforces);
  const barriers = buildBarriers(a.substitution_barriers);
  const breakpoints = buildBreakpoints(hidden.critical_breakpoints);
  const proof = buildProof(a.minimum_proof_set);
  const confirming = buildEvidence(hidden.optional_confirming_evidence);
  const caveats = buildRegimeCaveats(hidden.regime_caveats);
  const primaryAssets = buildRankedAssets(a.primary_assets);
  const secondaryAssets = buildRankedAssets(a.secondary_assets);
  const hedgeAssets = buildRankedAssets(a.hedge_or_signal_assets);

  return {
    mechanism: {
      summary: field(a.mechanism_summary),
      path: buildPath(a.transmission_path),
      // Deliberately not "causal chain": the engine emits an ordered
      // hypothesis, and the label must not upgrade it.
      pathLabel: "Ordered transmission steps as stated by the analysis",
      transmissionType: field(typedToken(hidden.transmission_type) ?? undefined),
      bottleneckType: field(typedToken(hidden.bottleneck_type) ?? undefined),
    },
    exposure: {
      directPositive: list(a.beneficiaries, "role"),
      directNegative: list(a.losers, "role"),
      primaryAssets: { available: primaryAssets.length > 0, values: primaryAssets },
      secondaryAssets: { available: secondaryAssets.length > 0, values: secondaryAssets },
      hedgeOrSignal: { available: hedgeAssets.length > 0, values: hedgeAssets },
      indirectChannels: list(a.expected_second_order_channels, "channel"),
    },
    counterforces: {
      forces: { available: forces.length > 0, values: forces },
      substitutionBarriers: { available: barriers.length > 0, values: barriers },
      escapePath: field(hidden.substitution_escape_path),
      competingThesis: competingThesis(a.competing_thesis),
      adversarialChallenge: {
        ...field(a.adversarial_challenge),
        provenanceLabel: MODEL_GENERATED_LABEL,
      },
    },
    falsifiers: {
      keyFalsifiers: list(a.key_falsifiers, "item"),
      minimumProof: { available: proof.length > 0, values: proof },
      criticalBreakpoints: { available: breakpoints.length > 0, values: breakpoints },
      proofStatus: status(a.proof_status),
      falsifierStatus: status(a.falsifier_status),
    },
    resolution: {
      horizons: buildHorizons(a.horizon_checkpoints),
      monitorPlan: buildMonitorPlan(a.monitor_plan),
      confirmingEvidence: { available: confirming.length > 0, values: confirming },
      evidenceToRevisit: { available: caveats.length > 0, values: caveats },
    },
    limits: {
      qualityTier: field(a.quality_tier),
      qualityWarnings,
      validationWarnings,
      degraded,
      sourceQuality: field(sourceQuality.source_type),
      sourceSpecificity: field(sourceQuality.specificity),
      sourceUncertainty: field(sourceQuality.uncertainty_level),
      evidenceLimitations: field(sourceQuality.evidence_limitations),
      regimeCaveat: field(a.regime_conditioned_caveat),
      prominent: degraded || qualityWarnings.available || validationWarnings.available,
    },
  };
}
