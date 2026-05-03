/** Resolve the API base URL from build-time env, with a safe same-origin
 *  fallback.
 *
 *  Resolution order:
 *    1. ``VITE_API_BASE_URL`` (set at ``vite build`` / ``vite dev`` time)
 *       — honoured verbatim when non-empty.  Use this to point a
 *       deployed static frontend at a separate API origin, e.g.
 *       ``VITE_API_BASE_URL=https://api.example.com`` — or to an
 *       origin-local path prefix other than ``/api``.
 *    2. ``/api`` — the default.  In local development this is handled
 *       by the Vite dev-server proxy in ``vite.config.ts``.  In a
 *       same-origin production deploy this works when a reverse
 *       proxy (nginx, Render, Cloudflare) rewrites ``/api/*`` to the
 *       backend.
 *
 *  A trailing slash on the env value is stripped so path composition
 *  is predictable ("https://api.example.com/" + "/health" would emit
 *  a double slash otherwise).  Exported so unit tests (and dev tools)
 *  can assert the resolution contract without re-implementing it.
 */
export function resolveApiBase(
  envValue: string | undefined = import.meta.env.VITE_API_BASE_URL as
    | string
    | undefined,
): string {
  const raw = (envValue ?? "").trim();
  if (!raw) return "/api";
  return raw.replace(/\/+$/, "");
}

const BASE = resolveApiBase();

/** Structured error thrown by the api client.
 *
 *  Pages can render `error.message` directly — it's already a short,
 *  user-facing string ("Cannot reach the backend.", "Server error.",
 *  etc.) — and inspect `status` if they need to branch on the HTTP
 *  code.  ``detail`` carries the raw FastAPI ``{"detail": ...}`` body
 *  (or response text) for debugging contexts that want it. */
export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(message: string, status: number, detail: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** Map an HTTP status code to a short, friendly user-facing message.
 *  status === 0 means the fetch itself failed (offline, CORS, server
 *  not running) — by far the most common first-run failure mode. */
function _friendlyMessage(status: number, detail: string): string {
  if (status === 0) return "Cannot reach the backend. Is the API server running?";
  if (status === 404) return "Not found.";
  if (status === 422) return detail || "Invalid request.";
  if (status >= 500) return "Server error. Please try again in a moment.";
  if (status >= 400) return detail || "Request failed.";
  return detail || `Unexpected response (${status}).`;
}

/** Try to pull a useful error string out of a FastAPI error body.
 *  FastAPI conventionally returns ``{"detail": "..."}`` for raised
 *  HTTPExceptions; for validation errors it's a list of dicts.  Falls
 *  back to the raw text if the body isn't JSON. */
function _extractDetail(body: string): string {
  if (!body) return "";
  try {
    const parsed = JSON.parse(body);
    if (typeof parsed?.detail === "string") return parsed.detail;
    if (Array.isArray(parsed?.detail) && parsed.detail.length > 0) {
      const first = parsed.detail[0];
      if (typeof first?.msg === "string") return first.msg;
    }
  } catch {
    /* not JSON — fall through */
  }
  return body.slice(0, 200);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch (e) {
    // Network failure: server unreachable, DNS, CORS, offline.
    // Surface a uniform friendly message instead of "TypeError: failed to fetch".
    throw new ApiError(
      _friendlyMessage(0, ""),
      0,
      e instanceof Error ? e.message : String(e),
    );
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    const detail = _extractDetail(body);
    throw new ApiError(_friendlyMessage(res.status, detail), res.status, detail);
  }
  try {
    return (await res.json()) as T;
  } catch (e) {
    // 200 OK but the body wasn't JSON — treat as a backend bug.
    throw new ApiError(
      "Server returned an invalid response.",
      res.status,
      e instanceof Error ? e.message : String(e),
    );
  }
}

export interface AnalyzeRequest {
  headline: string;
  event_date?: string;
  event_context?: string;
  /** When provided, the backend loads this specific event by primary key
   *  instead of doing a headline-string lookup.  This guarantees the
   *  correct event is opened when two near-duplicate headlines exist. */
  event_id?: number;
  /** Bypass the event-age freeze policy when re-running a cached
   *  archive event.  Only meaningful on /analyze cache hits; the
   *  fresh path ignores it.  Defaults to false. */
  force?: boolean;
}

/** Minimal shape shared by Ticker and MarketMover ticker entries. */
export interface TickerBase {
  symbol: string;
  role: string;
  return_5d: number | null;
  return_20d?: number | null;
  direction?: string | null;
  spark?: number[];
}

/** Rolled-up validation verdict for a single ticker, derived from its
 *  relative-to-benchmark move.  Lets the UI render "supported by alpha"
 *  vs "moved with the tape" without pattern-matching direction_tag. */
export type ThesisSupport =
  | "supported"
  | "ambiguous_beta"
  | "contradicted"
  | "flat"
  | "unavailable";

/** Richer validation-quality label emitted by relative_move.py.  The
 *  existing ``direction_tag`` stays as the absolute-return read for
 *  back-compat (movers, track-record); ``validation_quality`` is the
 *  benchmark-aware verdict new consumers should prefer. */
export type ValidationQuality =
  | "alpha_support"
  | "alpha_contradicts"
  | "beta_aligned"
  | "beta_contradicts"
  | "drift"
  | "flat"
  | "unavailable";

export interface Ticker extends TickerBase {
  label: string;
  direction_tag: string | null;
  return_1d: number | null;
  return_5d: number | null;
  return_20d: number | null;
  volume_ratio: number | null;
  vs_xle_5d: number | null;
  /** Backend always sends spark; override TickerBase optional. */
  spark: number[];
  /** True when the ticker's latest bar is stale (delisted / halted / data gap). */
  stale?: boolean;
  /** ISO date of the last available trading bar when stale is true. */
  last_trade_date?: string;
  /** Benchmark used for the relative-move comparison ("XLE", "SPY", ...). */
  benchmark_symbol?: string;
  /** Sector label associated with the benchmark ("energy", "market", ...). */
  benchmark_sector?: string;
  /** Benchmark's own 5d return — for UI context next to the spread. */
  benchmark_return_5d?: number | null;
  /** Ticker minus benchmark return at each tenor (percentage-point spread). */
  relative_return_1d?: number | null;
  relative_return_5d?: number | null;
  relative_return_20d?: number | null;
  /** Detailed validation-quality label (alpha / beta / drift taxonomy). */
  validation_quality?: ValidationQuality;
  validation_quality_label?: string;
  /** Summary rollup — the only label that counts as clean support is
   *  "supported" (alpha in thesis direction).  "ambiguous_beta" means
   *  the ticker rode the tape; it is NOT thesis validation. */
  thesis_support?: ThesisSupport;
  /** One-line human-readable rationale for the validation verdict. */
  validation_rationale?: string;
}

/** Freshness metadata attached to every /analyze response's market block.
 *  Populated identically on the fresh and cached paths so the frontend
 *  can render a "refreshed N minutes ago" indicator without branching. */
export interface MarketFreshness {
  /** ISO-8601 timestamp of the most recent provider refresh. */
  last_market_check_at?: string | null;
  /** Result of the market-check freshness layer.
   *  "fresh"            — cache hit, nothing was re-fetched
   *  "stale_refreshed"  — refresh window exceeded → just re-fetched
   *  "legacy_refreshed" — row pre-dated the freshness column
   *  "forced_refreshed" — force=True bypassed the freeze cutoff
   *  "frozen"           — archived, not refreshed (no force)
   *  "error"            — upstream failure, stored payload returned */
  market_check_staleness?:
    | "fresh"
    | "stale_refreshed"
    | "legacy_refreshed"
    | "forced_refreshed"
    | "frozen"
    | "error";
  /** Age of the underlying event in calendar days (>= 0). */
  event_age_days?: number | null;
}

export interface MarketResult extends MarketFreshness {
  note: string;
  details: Record<string, unknown>;
  tickers: Ticker[];
  /** "ok" when most tickers have data; "degraded" when ≥50% lack prices. */
  data_quality?: "ok" | "degraded";
  /** Human-readable explanation when data_quality is "degraded". */
  data_quality_note?: string;
}

/** Bucket classification for the event-age freeze policy.
 *  Mirrors ``event_age_policy.classify_event_age``. */
export type FreshnessBucket =
  | "hot"
  | "warm"
  | "stable"
  | "frozen"
  | "legacy";

export interface FreshnessBlock {
  /** Backend always sends all 5 fields from _freshness_payload(). */
  bucket: FreshnessBucket;
  /** The unforced classification — "frozen" when force_bypassed is true. */
  natural_bucket: FreshnessBucket;
  event_age_days: number;
  is_frozen: boolean;
  force_bypassed: boolean;
}

export type Confidence = "low" | "medium" | "high";

/** One hop in the structured transmission path — actor + channel + step. */
export interface TransmissionPathHop {
  hop: string;
  channel: string;
  actor: string;
}

/** One entry in the substitution-barrier list. */
export interface SubstitutionBarrier {
  barrier: string;
  kind: string;
  severity: "low" | "medium" | "high" | string;
}

/** One entry in the counterforces list. */
export interface Counterforce {
  force: string;
  actor: string;
  likelihood: "low" | "medium" | "high" | string;
}

export interface AnalysisDetail {
  what_changed: string;
  mechanism_summary: string;
  beneficiaries: string[];
  losers: string[];
  beneficiary_tickers: string[];
  loser_tickers: string[];
  assets_to_watch: string[];
  confidence: Confidence;
  transmission_chain?: string[];
  /** Structured version of transmission_chain — each hop carries channel + actor. */
  transmission_path?: TransmissionPathHop[];
  /** Concrete frictions that prevent the mechanism from self-healing via substitution. */
  substitution_barriers?: SubstitutionBarrier[];
  /** Specific forces that could blunt or reverse the thesis. */
  counterforces?: Counterforce[];
  /** Steel-manned counter-thesis — the strongest reason this mechanism might not play out. */
  adversarial_challenge?: string;
  if_persists?: IfPersists;
  currency_channel?: CurrencyChannel;
  policy_sensitivity?: PolicySensitivity;
  inventory_context?: InventoryContext;
  real_yield_context?: RealYieldContext;
  policy_constraint?: PolicyConstraint;
  shock_decomposition?: ShockDecomposition;
  reaction_function_divergence?: ReactionFunctionDivergence;
  surprise_vs_anticipation?: SurpriseVsAnticipation;
  terms_of_trade?: TermsOfTrade;
  reserve_stress?: ReserveStress;
  narrative_divergence?: NarrativeDivergence;
  credit_regime?: CreditRegime;
  credit_transmission?: CreditTransmission;
  cross_asset_confirmation?: CrossAssetConfirmation;
  horizon_checkpoints?: HorizonCheckpoints;
  sector_passthrough?: SectorPassthrough;
  /** Mechanism archetype the event fits — LLM-committed with a
   *  keyword-based fallback (``mechanism_family.classify_family``). */
  mechanism_family?: MechanismFamily;
  /** First-order channels the family's canonical playbook expects to
   *  move today/tomorrow.  Always a subset of ExpectedChannel. */
  expected_first_order_channels?: ExpectedChannel[];
  /** Second-order / cascade channels (5d–20d follow-through). */
  expected_second_order_channels?: ExpectedChannel[];
  /** One-sentence caveat on how the current macro regime bends the
   *  family's usual playbook.  Empty string when no backdrop applied. */
  regime_conditioned_caveat?: string;
  historical_analogs?: HistoricalAnalog[];
  /** Per-event macro release context — canonical empty shape when the
   *  event doesn't map to any known release (``release_key === null``). */
  macro_release_context?: EventMacroReleaseContext;
  /** Per-event policy timing context — canonical empty shape when the
   *  event doesn't match any tracked policy (``policy_key === null``). */
  policy_timing_context?: EventPolicyTimingContext;
  /** Per-event country vulnerability context — canonical empty shape
   *  when the event doesn't mention a profiled country (``country === null``). */
  country_vulnerability_context?: EventCountryVulnerabilityContext;
  /** True when the analysis was degraded (missing overlays/context). */
  degraded?: boolean;
  /** Validation warnings from rule checks (only present when non-empty). */
  validation_warnings?: string[];
  /** Engine-phase fields surfaced by ``engine_phase_surface.decorate_full``
   *  on every ``GET /events/{id}`` read.  Each field has a stable default
   *  shape — consumers branch on emptiness, not field presence.  See
   *  ``EnginePhaseSummary`` for the rendering contract. */
  mechanism_subtype?: string | null;
  quality_tier?: QualityTier;
  quality_warnings?: string[];
  actionability_check?: ActionabilityCheck;
  counterfactual_check?: CounterfactualCheck;
  thesis_timing?: ThesisTiming;
  critical_breakpoints?: CriticalBreakpoint[];
  evidence_sources?: EvidenceSource[];
  confidence_rationale?: string;
  validation_rationale?: string;
}

/** Engine evidence-quality tier — closed set from
 *  ``low_information_gate.evidence_quality_tier``. */
export type QualityTier = "actionable" | "watch_only" | "low_information";

/** Engine actionability composer output.  Always populated when the
 *  composer ran — empty ``{}`` only when the field is absent entirely. */
export interface ActionabilityCheck {
  tradable?: boolean;
  why_tradable_or_not?: string;
  required_confirmation?: string[];
  sizing_caveat?: string;
  risk_level?: "high" | "elevated" | "standard";
  max_confidence_before_confirmation?: string;
  invalidation_trigger?: string;
}

/** Engine counterfactual composer output. */
export interface CounterfactualCheck {
  what_should_not_happen?: string;
  why_it_would_break_thesis?: string;
  evidence_to_watch?: string[];
}

/** Stage / persistence-derived timing windows. */
export interface ThesisTiming {
  expected_reaction_window?: string;
  follow_through_window?: string;
  stale_after?: string;
  timing_rationale?: string;
}

/** Fast-falsifier breakpoint surfaced from ``hidden_mechanism``. */
export interface CriticalBreakpoint {
  signal?: string;
  observation?: string;
  channel?: string;
  threshold?: string;
  timing?: string;
  condition?: string;
  threshold_or_observation?: string;
  why_it_changes_thesis?: string;
  linked_proof_or_falsifier?: string;
}

/** Traceability entry composed by ``evidence_sources.make_source``. */
export interface EvidenceSource {
  source_type?: string;
  field_used?: string;
  supports_or_contradicts?: "supports" | "contradicts" | "neutral";
  limitation?: string;
  /** Free-form label / kind keys may be present on producer-attached
   *  sources (competing_thesis lift path). */
  label?: string;
  kind?: string;
}

/** Timing profile for the thesis's transmission path. */
export type TimingProfile =
  | "fast_shock"
  | "delayed_pass_through"
  | "slow_grind"
  | "unknown";

/** Mechanism-family archetypes (taxonomy in mechanism_family.py). */
export type MechanismFamily =
  | "tariff"
  | "sanction"
  | "supply_shock"
  | "ceasefire_deescalation"
  | "policy_surprise"
  | "fiscal_issuance"
  | "labor_inflation"
  | "bank_stress"
  | "commodity_squeeze"
  | "supply_normalization"
  | "none";

/** Canonical 6-channel universe used for first/second-order channel
 *  packs.  Must match ``mechanism_family.CHANNEL_IDS`` + the 6 channels
 *  in ``cross_asset_coherence``. */
export type ExpectedChannel =
  | "rates"
  | "fx"
  | "commodities"
  | "vol"
  | "credit"
  | "equities";

/** One horizon entry inside HorizonCheckpoints.horizons. */
export interface HorizonCheckpoint {
  horizon: "1d" | "5d" | "20d";
  /** Expected market observations at this horizon if the thesis is right. */
  expected: string[];
  /** Concrete observations that would confirm the thesis at this horizon. */
  confirms_if: string[];
  /** Concrete observations that would falsify the thesis at this horizon. */
  falsifies_if: string[];
}

/** Horizon-aware checkpoints + timing profile from analyze_event. */
export interface HorizonCheckpoints {
  timing_profile: TimingProfile;
  /** Always three entries, canonicalized to 1d / 5d / 20d in order. */
  horizons: HorizonCheckpoint[];
}

/** One downstream-cascade candidate from sector_passthrough. */
export interface SectorPassthroughEntry {
  /** Source sector that drives the cascade. */
  source: string;
  /** Downstream sector that should react. */
  target: string;
  /** Human-readable version of ``target``. */
  target_label: string;
  /** Expected lag before the cascade shows up. */
  lag: "immediate" | "days" | "weeks" | "quarters";
  /** Intensity of the expected downstream move. */
  intensity: "low" | "medium" | "high";
  /** Direction of the cascade relative to the source shock. */
  sign: "reinforcing" | "inverse" | "mixed";
  /** One-line mechanism description. */
  mechanism: string;
  /** Example tickers / ETFs that proxy the downstream sector. */
  example_proxies: string[];
}

/** Sector-to-sector passthrough + downstream-cascade read. */
export interface SectorPassthrough {
  /** Sectors the event directly hits (resolved from tickers / mechanism /
   *  shock primary).  Alpha should show up here within the direct window. */
  direct_sectors: string[];
  direct_sectors_label: string[];
  /** Downstream sectors that should lag-react if the mechanism plays through.
   *  Sorted highest-conviction / fastest-cascade first. */
  downstream: SectorPassthroughEntry[];
  /** Overall cascade speed profile. */
  timing_profile:
    | "fast_cascade"
    | "slow_cascade"
    | "mixed"
    | "no_downstream";
  /** Validation window for direct-hit tickers (e.g. "1-5d"). */
  direct_validation_window: string;
  /** Validation window for downstream cascade (e.g. "5-20d"). */
  downstream_validation_window: string;
  rationale: string;
  available: boolean;
  stale: boolean;
}

/**
 * Degraded-state contract carried by every persisted overlay block.
 *
 * Backend ``sanitize_overlay_block`` guarantees these four fields on
 * every overlay emitted from the API — including frozen-archive reads
 * that previously returned ``{}`` silently.  Consumers can rely on the
 * shape without importing a union helper.
 */
export interface OverlayDegradedMarkers {
  available?: boolean;
  stale?: boolean;
  degraded?: boolean;
  degraded_reason?: string;
}

/** HY/IG/SHY classifier output from credit_regime.py. */
export interface CreditRegime extends OverlayDegradedMarkers {
  regime:
    | "default_risk_widening"
    | "default_risk_tightening"
    | "duration_widening"
    | "duration_tightening"
    | "risk_on"
    | "risk_off"
    | "decoupled"
    | "quiet"
    | "unavailable";
  regime_label: string;
  rationale: string;
  hy_5d: number | null;
  ig_5d: number | null;
  shy_5d: number | null;
  hy_ig_differential_5d: number | null;
  default_risk_signal: "widening" | "tightening" | "quiet" | "unavailable";
  duration_signal: "rising_rates" | "falling_rates" | "quiet" | "unavailable";
  available: boolean;
  stale: boolean;
}

/** Credit / funding-stress transmission read from credit_transmission.py.
 *  Separates real credit deterioration from equity-only risk-off and flags
 *  which sectors are most exposed. */
export interface CreditTransmission extends OverlayDegradedMarkers {
  funding_stress:
    | "acute"
    | "elevated"
    | "contained"
    | "insulated"
    | "unavailable";
  funding_stress_label: string;
  equity_vs_credit:
    | "equity_only_riskoff"
    | "credit_only_deterioration"
    | "synchronized_stress"
    | "synchronized_calm"
    | "mixed"
    | "unavailable";
  equity_vs_credit_label: string;
  sector_exposures: string[];
  drivers: string[];
  rationale: string;
  signals: {
    default_risk_signal: "widening" | "tightening" | "quiet" | "unavailable";
    duration_signal:
      | "rising_rates"
      | "falling_rates"
      | "quiet"
      | "unavailable";
    hy_ig_differential_5d: number | null;
    vix_elevated: boolean;
    safe_haven_bid: boolean;
    real_yield_rising: boolean;
  };
  available: boolean;
  stale: boolean;
}

/** Per-channel confirm/disconfirm read, with separately-scored aggregates. */
export interface CrossAssetChannelRead {
  label: string;
  expected: "up" | "down" | "silent";
  observed: number | null;
  unit: string;
  z: number;
  observed_dir: "up" | "down" | "flat" | "unavailable";
  verdict: "confirm" | "disconfirm" | "silent";
  weight: number;
}

export interface CrossAssetConfirmation {
  thesis: string;
  channels: Record<string, CrossAssetChannelRead>;
  confirms: string[];
  disconfirms: string[];
  silent: string[];
  confirm_score: number;
  disconfirm_score: number;
  net_score: number;
  verdict:
    | "strong_confirm"
    | "weak_confirm"
    | "mixed"
    | "weak_disconfirm"
    | "strong_disconfirm"
    | "silent";
  verdict_label: string;
  rationale: string;
  curve_shape_read: "aligned" | "diverges" | "silent";
  available: boolean;
  stale: boolean;
}

export interface IfPersists {
  substitution?: string | null;
  delayed_winners?: string[];
  delayed_losers?: string[];
  horizon?: string | null;
}

export interface CurrencyChannel {
  pair?: string;
  mechanism?: string;
  beneficiaries?: string;
  squeezed?: string;
}

export interface PolicySensitivity extends OverlayDegradedMarkers {
  stance?: "reinforced" | "fighting" | "neutral";
  explanation?: string;
  regime?: string;
}

export interface InventoryContext extends OverlayDegradedMarkers {
  status?: "tight" | "comfortable" | "neutral";
  proxy?: string;
  proxy_label?: string;
  return_20d?: number;
  explanation?: string;
}

export interface RealYieldContext extends OverlayDegradedMarkers {
  thesis?: "inflationary" | "disinflationary" | "rate_pressure_up" | "rate_pressure_down" | "none";
  thesis_evidence?: string[];
  alignment?: "confirm" | "tension" | "neutral" | "stale";
  regime?: string | null;
  nominal_5d?: number | null;
  real_proxy_5d?: number | null;
  breakeven_proxy_5d?: number | null;
  explanation?: string;
  available?: boolean;
  stale?: boolean;
}

export type PolicyConstraintId =
  | "inflation"
  | "growth"
  | "financial_stability"
  | "external_balance"
  | "fiscal"
  | "none";

export interface PolicyConstraintSecondary {
  id: PolicyConstraintId;
  label: string;
  score: number;
  rationale: string;
}

/** Policy-room taxonomy.  The old 5-label set is widened with two poles
 *  that separate "authority is boxed in between mandates" from "authority
 *  has clean optionality to move on the binding constraint". */
export type PolicyRoom =
  | "free_to_respond"
  | "ample"
  | "limited"
  | "constrained"
  | "boxed_in"
  | "mixed"
  | "unknown";

/** One entry in PolicyConstraint.macro_surprise_signals. */
export interface PolicyMacroSurpriseSignal {
  indicator: "CPI" | "PPI" | "PCE" | "NFP" | "Unemployment" | string;
  signal: "beat" | "miss";
  constraint: PolicyConstraintId;
  points: number;
  days_until: number;
}

export interface PolicyConstraint extends OverlayDegradedMarkers {
  binding?: PolicyConstraintId;
  binding_label?: string;
  secondary?: PolicyConstraintSecondary[];
  policy_room?: PolicyRoom;
  why?: string;
  reaction_function?: string;
  key_markets?: string[];
  signals?: Record<string, number>;
  /** True when the 2Y has moved >= 15bps with the 2s10s slope twisting —
   *  markets have already repriced the expected policy path, leaving the
   *  authority less surprise room.  Downgrades ``policy_room`` by one
   *  notch when set. */
  front_end_repricing_active?: boolean;
  /** One-line rationale ("2Y +0.22pp / 5d with 2s10s +0.18pp — hikes priced")
   *  when front_end_repricing_active is true. */
  front_end_repricing_rationale?: string;
  /** Macro-calendar beats / misses that contributed to the scoring. */
  macro_surprise_signals?: PolicyMacroSurpriseSignal[];
  available?: boolean;
  stale?: boolean;
}

export type ShockChannelId =
  | "nominal_yield"
  | "real_yield"
  | "breakeven"
  | "fx"
  | "commodity"
  | "none";

export interface ShockChannelEntry {
  label: string;
  move_5d: number | null;
  available: boolean;
  z: number;
  crude_5d?: number;
  gold_5d?: number;
  leader?: string;
}

export interface ShockSecondary {
  id: ShockChannelId;
  label: string;
  move_5d: number | null;
  z: number;
}

export type CurveShape =
  | "bull_steepener"
  | "bear_steepener"
  | "bull_flattener"
  | "bear_flattener"
  | "parallel_up"
  | "parallel_down"
  | "flat"
  | "unavailable";

export type RegimeState =
  | "parallel_shift_up"
  | "parallel_shift_down"
  | "bear_steepener_whole"
  | "bull_steepener_whole"
  | "bear_flattener_whole"
  | "bull_flattener_whole"
  | "twist_short_steep_long_flat"
  | "twist_short_flat_long_steep"
  | "short_end_driven"
  | "long_end_driven"
  | "mixed"
  | "flat_quiet"
  | "unavailable";

export type RegimeClass =
  | "level_move"
  | "curve_move"
  | "partial"
  | "flat_quiet"
  | "mixed"
  | "unavailable";

export interface RatesPack {
  /** 2s10s section. */
  tenyr_5d_pp: number | null;
  twoy_5d_pp: number | null;
  slope_5d_pp: number | null;
  curve_shape: CurveShape;
  parallel_component_pp: number | null;
  twist_component_pp: number | null;
  driver: "long_end" | "short_end" | "both" | "flat" | "unavailable";
  magnitude_tier: "small" | "medium" | "large" | "unavailable";
  /** 5s30s section. */
  fiveyr_5d_pp: number | null;
  thirtyyr_5d_pp: number | null;
  long_slope_5d_pp: number | null;
  long_curve_shape: CurveShape;
  long_parallel_component_pp: number | null;
  long_twist_component_pp: number | null;
  long_magnitude_tier: "small" | "medium" | "large" | "unavailable";
  /** Combined 2s10s + 5s30s read. */
  regime_state: RegimeState;
  regime_state_label: string;
  regime_class: RegimeClass;
  available: boolean;
}

export interface ShockDecomposition extends OverlayDegradedMarkers {
  primary?: ShockChannelId;
  primary_label?: string;
  secondary?: ShockSecondary[];
  rationale?: string;
  macro_read?: string;
  key_markets?: string[];
  channels?: Record<string, ShockChannelEntry>;
  rates_pack?: RatesPack;
  /** Cross-rate FX decomposition — one entry per major pair. */
  fx_pack?: Record<string, unknown>;
  /** Per-tenor breakeven decomposition + inflation-path shape
   *  + policy-space read.  See BreakevenCurve. */
  breakeven_curve?: BreakevenCurve;
  available?: boolean;
  stale?: boolean;
}

/** Canonical tenors carried in the breakeven curve block. */
export type BreakevenTenor = "2Y" | "5Y" | "10Y" | "30Y";

export interface BreakevenTenorEntry {
  /** Nominal yield 5d change in percentage points. */
  nominal_5d_pp: number | null;
  /** Real yield 5d change in percentage points (derived from TIPS
   *  ETF via duration-inversion; proxy, not a direct print). */
  real_5d_pp: number | null;
  /** Fisher-derived breakeven 5d change in pp (nominal − real). */
  breakeven_5d_pp: number | null;
  /** True when both nominal and real inputs were usable. */
  available: boolean;
}

/** Shape of the inflation-path curve over 5d.  front_loaded means the
 *  short end moved MORE than the long end (immediate inflation
 *  concern); term_premium_like means the long end led (structural /
 *  fiscal pressure the Fed can look through). */
export type InflationPathShape =
  | "front_loaded"
  | "term_premium_like"
  | "parallel_up"
  | "parallel_down"
  | "twist"
  | "flat"
  | "unavailable";

/** Policy-space interpretation derived from curve shape + magnitudes. */
export type PolicySpaceRead =
  | "narrow_hawkish"
  | "look_through"
  | "ease_room"
  | "behind_the_curve"
  | "neutral"
  | "unavailable";

export interface BreakevenCurve {
  available: boolean;
  stale: boolean;
  tenors: Record<BreakevenTenor, BreakevenTenorEntry>;
  short_end_be_5d: number | null;
  long_end_be_5d: number | null;
  /** long_end - short_end; positive = long end moved more. */
  shape_change_5d: number | null;
  shape: InflationPathShape;
  shape_label: string;
  policy_space: PolicySpaceRead;
  policy_label: string;
  rationale: string;
}

export type ReactionDirection = "hawkish" | "dovish" | "neutral";
export type ReactionDivergence = "aligned" | "mild" | "sharp";

export interface ReactionFunctionDivergence extends OverlayDegradedMarkers {
  implied?: ReactionDirection;
  implied_label?: string;
  implied_basis?: string;
  priced?: ReactionDirection;
  priced_label?: string;
  priced_basis?: string;
  divergence?: ReactionDivergence;
  divergence_label?: string;
  rationale?: string;
  macro_read?: string;
  key_markets?: string[];
  available?: boolean;
  stale?: boolean;
}

export type SurpriseRegime =
  | "surprise_shock"
  | "anticipated_confirmation"
  | "uncertainty_resolution"
  | "mixed";

export interface SurpriseVsAnticipationSignals {
  intraday_share?: number | null;
  vix_change_5d?: number | null;
  stage?: string;
  ticker_move_count?: number;
}

export interface SurpriseVsAnticipation extends OverlayDegradedMarkers {
  regime?: SurpriseRegime;
  regime_label?: string;
  rationale?: string;
  priced_before?: string;
  changed_on_realization?: string;
  key_markets?: string[];
  available?: boolean;
  stale?: boolean;
  signals?: SurpriseVsAnticipationSignals;
}

export type TermsOfTradeChannel =
  | "oil_import"
  | "oil_export"
  | "usd_funding"
  | "food_import"
  | "industrial_metal"
  | "mixed"
  | "none";

export interface TermsOfTradeExposure {
  country: string;
  region: string;
  role: "winner" | "loser";
  channel: TermsOfTradeChannel;
  rationale: string;
}

export interface TermsOfTradeSignals {
  crude_5d?: number | null;
  dxy_5d?: number | null;
  matched_theme?: string;
  thresholds?: string;
}

export interface TermsOfTrade extends OverlayDegradedMarkers {
  exposures?: TermsOfTradeExposure[];
  external_winners?: string[];
  external_losers?: string[];
  dominant_channel?: TermsOfTradeChannel;
  dominant_channel_label?: string;
  rationale?: string;
  key_markets?: string[];
  available?: boolean;
  stale?: boolean;
  signals?: TermsOfTradeSignals;
}

// ---------------------------------------------------------------------------
// Current Account + FX Reserve Stress Overlay
// ---------------------------------------------------------------------------

export type ReserveStressChannel =
  | "dual_oil_dollar"
  | "oil_import_squeeze"
  | "usd_funding_stress"
  | "food_importer_stress"
  | "commodity_exporter_cushion"
  | "mixed"
  | "none";

export interface ReserveStressVulnerable {
  country: string;
  region: string;
  vulnerability: number;
  drivers: string[];
  rationale: string;
}

export interface ReserveStressInsulated {
  country: string;
  region: string;
  strength: number;
  drivers: string[];
  rationale: string;
}

export interface ReserveStressSignals {
  crude_5d?: number | null;
  dxy_5d?: number | null;
  credit_spread_5d?: number | null;
  real_yield_5d?: number | null;
  stress_regime?: string | null;
  matched_channel?: string;
  matched_theme?: string;
  thresholds?: string;
}

export interface ReserveStress extends OverlayDegradedMarkers {
  vulnerable?: ReserveStressVulnerable[];
  insulated?: ReserveStressInsulated[];
  dominant_channel?: ReserveStressChannel;
  dominant_channel_label?: string;
  pressure_score?: number;
  pressure_label?: "elevated" | "moderate" | "contained";
  rationale?: string;
  key_markets?: string[];
  available?: boolean;
  stale?: boolean;
  signals?: ReserveStressSignals;
}

export type NarrativeDivergenceLabel =
  | "confident_miss"
  | "surprise_validation"
  | "aligned"
  | "mixed"
  | "validated"
  | "contradicted";

export type NarrativeDivergenceSeverity = "none" | "mild" | "sharp";
export type RoleSignal = "aligned" | "contra" | "mixed" | "no_data";

export interface NarrativeDivergence extends OverlayDegradedMarkers {
  available: boolean;
  confidence?: string;
  actual_rate?: number;
  expected_rate?: number | null;
  gap?: number | null;
  label?: NarrativeDivergenceLabel;
  severity?: NarrativeDivergenceSeverity;
  rationale?: string | null;
  n_supporting?: number;
  n_contradicting?: number;
  n_total?: number;
  beneficiary_signal?: RoleSignal;
  loser_signal?: RoleSignal;
  n_calibration_events?: number | null;
}

/** One structured match dimension — produced by analog_explainer.py.
 *  Status is three-state: match / mismatch / partial / unknown.  Multi-axis
 *  dimensions (regime, inflation_rates) carry axes_matched / axes_comparable /
 *  match_ratio for the UI to render "3/5 axes agree" directly. */
export interface AnalogMatchDimension {
  dimension:
    | "mechanism_family"
    | "regime"
    | "inflation_rates"
    | "credit"
    | string;
  label: string;
  status: "match" | "mismatch" | "partial" | "unknown";
  note: string;
  current?: string;
  analog?: string;
  axes_matched?: number;
  axes_comparable?: number;
  match_ratio?: number;
}

export interface HistoricalAnalog {
  headline: string;
  event_date: string | null;
  stage: string;
  persistence: string;
  confidence: string;
  return_5d: number | null;
  return_20d: number | null;
  decay: string;
  similarity?: number;
  match_reason?: string;
  /** Mechanism archetype the analog was classified under (when persisted). */
  mechanism_family?: string;
  /** Structured per-dimension match read.  Present on every /analyze
   *  response after the regime-aware explainer shipped. */
  match_dimensions?: AnalogMatchDimension[];
  /** Finance-useful 1-2 sentence "why this analog" summary. */
  explainer?: string;
  /** True when topic similarity is strong but regime alignment is weak —
   *  the past case "rhymes on topic but not on setup". */
  topic_vs_regime_mismatch?: boolean;
  /** One-line reason the topic-vs-regime flag fired (null when inactive). */
  mismatch_note?: string | null;
}

export interface AnalyzeResponse {
  headline: string;
  stage: string;
  persistence: string;
  analysis: AnalysisDetail;
  market: MarketResult;
  /** Event-age freeze classification.  Present on both fresh and
   *  cached /analyze responses.  Undefined only on legacy clients
   *  that read pre-Task-J payloads. */
  freshness?: FreshnessBlock;
  is_mock: boolean;
  event_date: string | null;
  /** True when the LLM returned a mock/fallback — not a real analysis. */
  analysis_failed?: boolean;
  /** Human-readable reason for the failure (e.g. "anthropic overload"). */
  failure_reason?: string;
}

export interface PersistenceSignal {
  status: "watching" | "active" | "fading" | "resolved";
  label: string;
  evidence: string;
  horizon_days: number;
  days_elapsed: number;
}

export interface SavedEvent {
  id: number;
  timestamp: string;
  headline: string;
  stage: string;
  persistence: string;
  what_changed: string;
  mechanism_summary: string;
  beneficiaries: string[];
  losers: string[];
  assets_to_watch: string[];
  confidence: string;
  market_note: string;
  market_tickers: Ticker[];
  event_date: string | null;
  notes: string;
  rating: string | null;
  /** Staleness signal injected by the /events list endpoint. */
  stale_signal?: StaleSignal;
  hours_since_check?: number | null;
  event_age_days?: number | null;
  persistence_signal?: PersistenceSignal;
  validation_status?: "validated" | "contradicted" | "unresolved";
}

export interface EventsQuery {
  limit?:       number;
  offset?:      number;
  search?:      string;
  stage?:       string;
  persistence?: string;
  confidence?:  string;
  rating?:      string;
  date_from?:   string;
  date_to?:     string;
  validated?:   "validated" | "contradicted" | "unresolved";
}

export interface EventsPage {
  items:  SavedEvent[];
  total:  number;
  offset: number;
  limit:  number;
}

export interface RelatedEvent {
  id: number;
  headline: string;
  stage: string;
  persistence: string;
  confidence: string;
  timestamp: string;
  event_date: string | null;
}

export interface CascadeNode {
  id: number;
  headline: string;
  stage: string;
  persistence: string;
  confidence: string;
  timestamp: string;
  event_date: string | null;
  mechanism_summary: string;
  hop: number;
  parent_id: number;
  similarity: number;
}

export interface CascadeGraph {
  root: { id: number; headline: string } | null;
  nodes: CascadeNode[];
}

export interface BacktestOutcome {
  symbol: string;
  role: string;
  return_1d: number | null;
  return_5d: number | null;
  return_20d: number | null;
  direction: string | null;
  anchor_date: string | null;
}

export interface BacktestResult {
  event_id: number;
  outcomes: BacktestOutcome[];
  score: { supporting: number; total: number } | null;
  /** Result of the freshness layer for the backtest pull.  Omitted
   *  on the legacy fallback path when the freshness refresh raised. */
  market_check_staleness?:
    | "fresh"
    | "stale_refreshed"
    | "legacy_refreshed"
    | "forced_refreshed"
    | "frozen";
  last_market_check_at?: string | null;
  error?: string;
}

/** A single ticker's return at a specific revisit horizon. */
export interface RevisitTicker {
  symbol: string;
  role: string;
  direction: string | null;
  [key: string]: unknown; // return_1d / return_5d / return_20d
}

/** One revisit snapshot — a point-in-time capture at day N after event. */
export interface RevisitSnapshot {
  day: number;
  captured_at: string;
  tickers: RevisitTicker[];
}

export interface RevisitTimeline {
  event_id: number;
  snapshots: RevisitSnapshot[];
  note?: string;
}

export interface MacroEntry {
  label: string;
  value: number | null;
  change_5d: number | null;
  unit: string;
}

export interface MarketSnapshot {
  market: string;
  symbol: string | null;
  label: string;
  unit: string;
  asset_class: string;
  source: string;
  value: number | null;
  change_1d: number | null;
  change_5d: number | null;
  fetched_at: string | null;
  error: string | null;
  stale: boolean;
}

export interface SnapshotsMeta {
  total: number;
  fresh: number;
  stale: number;
  unavailable: number;
}

export interface HighlightsMeta {
  count: number;
  source: string;
}

export interface RegimeVector {
  inflation: string;
  policy_stance: string;
  fx: string;
  growth_stress: string;
  /** Breadth-expansion axes (regime_vector.py: ``credit``,
   *  ``curve_shape``, ``inflation_path``).  Optional in TS because
   *  older persisted snapshots predate them and the unavailable stub
   *  can omit them; backend ``build_regime_vector`` always emits them
   *  alongside the original four when ``available === true``. */
  credit?: string;
  curve_shape?: string;
  inflation_path?: string;
  available: boolean;
  stale?: boolean;
}

/** Compound regime + transition enrichment layered on top of the
 *  per-axis vector by regime_compound.enrich_with_compound_regime. */
export interface CompoundRegime {
  label: string;
  confidence: number;
  rationale: string;
}

export interface RegimeTransition {
  state: "stable" | "shifting" | "flipping" | "unavailable";
  changed_axes: Array<{
    axis: string;
    before: string;
    after: string;
    direction: string;
  }>;
  rationale: string;
}

/** Funding/liquidity mode classifier output — the macro engine's read
 *  of WHICH orthogonal stress mode is active. */
export interface FundingStressMode {
  available?: boolean;
  primary_mode: "none" | "duration_shock" | "credit_widening"
    | "dollar_shortage" | "liquidity_squeeze";
  composite_severity: "none" | "mild" | "elevated" | "acute";
  active_modes: string[];
  rationale: string;
  modes?: Record<string, {
    fired: boolean;
    severity: string;
    drivers: string[];
    rationale: string;
  }>;
}

/** Sector-rotation read from compute_sector_rotation — per-sector
 *  direction + broad market tilt, already sorted winners-first. */
export interface SectorRotationEntry {
  symbol: string;
  label: string;
  net_score: number;
  direction: "winner" | "loser" | "neutral";
  confidence: "low" | "medium" | "high";
  channels_direct: Array<{ channel: string; weight: number; tag: string }>;
  channels_second_order: Array<{ channel: string; weight: number; tag: string }>;
  rationale: string;
}

export interface SectorRotation {
  available?: boolean;
  broad_market_tilt: "risk_on" | "risk_off" | "mixed" | "neutral";
  broad_market_drivers: string[];
  sectors: SectorRotationEntry[];
  winners: { direct: string[]; second_order: string[] };
  losers:  { direct: string[]; second_order: string[] };
  rationale: string;
}

/** Market-level finance playbook synthesis. */
export interface FinancePlaybook {
  available?: boolean;
  headline: string;
  lines: {
    regime: string;
    funding: string;
    thesis: string;
    rotation: string;
    analogs: string;
  };
  base_case: {
    thesis_status: string;
    rationale: string;
    key_sectors: { long: string[]; short: string[] };
  };
  key_risks: Array<{ risk: string; driver: string; severity: string }>;
  what_would_change_the_read: string[];
  coherence_flags: string[];
  sources_used: string[];
}

export interface MarketContext {
  built_at: string;
  source: string;
  snapshots: MarketSnapshot[];
  snapshots_meta: SnapshotsMeta;
  /** Backend always sends stress/rates/regime_vector (with available:false when degraded). */
  stress: StressRegime & { available?: boolean };
  rates: RatesContext & { available?: boolean };
  regime_vector: RegimeVector & {
    compound?: CompoundRegime;
    transition?: RegimeTransition;
  };
  highlights: MarketMover[];
  highlights_meta: HighlightsMeta;
  uncertainty_concentration?: NewsUncertaintyConcentration;
  /** Deeper macro-engine blocks added to /market-context.  Each
   *  carries ``available`` so the frontend can skip the panel cleanly
   *  when the engine couldn't compute it from today's tape. */
  credit_regime?: {
    available?: boolean;
    regime?: string;
    regime_label?: string;
    rationale?: string;
    hy_ig_differential_5d?: number | null;
  };
  funding_stress_mode?: FundingStressMode;
  sector_rotation?: SectorRotation;
  finance_playbook?: FinancePlaybook;
}

export interface RegistryCandidate {
  headline: string;
  cluster_id?: number | string | null;
  source_count?: number | null;
  has_asset_terms?: boolean;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  last_skip_reason?: string | null;
  state?: string | null;
}

export interface RegistryDiagnostics {
  state_counts: Record<string, number>;
  skip_reason_counts: Record<string, number>;
  last_analyzed_at: string | null;
  expired_count_24h: number;
  eligible_unanalyzed_candidates: RegistryCandidate[];
}

export interface BackfillPreviewItem {
  headline: string;
  source_count?: number | null;
  published_at?: string | null;
  skip_reason?: string | null;
  already_analyzed: boolean;
  would_call_llm: boolean;
}

export interface BackfillPreviewResponse {
  items: BackfillPreviewItem[];
  counts: {
    scanned?: number;
    considered?: number;
    eligible?: number;
    already_analyzed?: number;
    would_call_llm?: number;
  };
  skip_reasons?: Record<string, number>;
  filters?: {
    limit?: number;
    since_hours?: number;
    include_low_signal?: boolean;
    force_reanalyze?: boolean;
  };
  news_source?: string;
  llm_available?: boolean;
  llm_provider?: string;
  analysis_model?: string;
  analysis_model_key?: string;
}

export interface ChartPoint {
  date: string;
  close: number;
}

export interface TickerInfo {
  symbol: string;
  name: string | null;
  sector: string | null;
  industry: string | null;
  market_cap: number | null;
  avg_volume: number | null;
}

export interface StressComponentDetail {
  label: string;
  status: "calm" | "watch" | "stressed";
  explanation: string;
  value?: number | null;
  avg20?: number | null;
  change_5d?: number | null;
  vix3m?: number | null;
  spread_5d?: number | null;
  gap_5d?: number | null;
  assets?: Record<string, number | null>;
  inflow_count?: number;
}

export interface SectorVolEntry {
  sector: string;
  etf: string;
  vol_20d: number;
  vol_ratio: number;
  status: "stressed" | "watch" | "calm";
}

export interface SectorUncertainty {
  available: boolean;
  spy_vol_20d?: number;
  concentration?: "concentrated" | "mixed" | "diffuse";
  lead_sector?: string | null;
  sectors?: SectorVolEntry[];
}

export interface NewsSectorUncertaintyEntry {
  sector: string;
  score: number;
  cluster_count: number;
  high_fraction: number;
}

export interface NewsUncertaintyConcentration {
  available: boolean;
  uncertainty_scope: "global" | "sector" | "mixed";
  sector_uncertainty: NewsSectorUncertaintyEntry[];
  lead_sector: string | null;
}

export interface StressRegime {
  regime: string;
  signals: {
    vix_elevated: boolean;
    term_inversion: boolean;
    credit_widening: boolean;
    safe_haven_bid: boolean;
    breadth_deterioration: boolean;
  };
  raw: Record<string, number>;
  detail?: Record<string, StressComponentDetail>;
  summary?: string;
  sector_uncertainty?: SectorUncertainty;
  /** "degraded" when one of the enrichment blocks fell back to defaults. */
  data_quality?: "ok" | "degraded";
  /** Names of the fields that fell back to defaults (e.g. "sector_uncertainty"). */
  degraded_fields?: string[];
}

export interface RatesContextEntry {
  label: string;
  value?: number | null;
  change_5d?: number | null;
}

export interface RatesContext {
  regime: string;
  nominal: RatesContextEntry;
  real_proxy: RatesContextEntry;
  breakeven_proxy: RatesContextEntry;
  raw: Record<string, number>;
}

/** One ticker chip on a Market Mover card. */
export interface MoverTicker {
  symbol: string;
  role: string;
  return_5d: number | null;
  return_20d?: number | null;
  direction: string | null;
  spark: number[];
  /** Backend always sends decay and decay_evidence on mover tickers. */
  decay: string;
  decay_evidence: string;
  /** First trading bar the forward returns were measured from.  Lets
   *  the UI label cards with "anchored YYYY-MM-DD" so users can see
   *  why the same symbol (e.g. XLE) reads differently across cards
   *  anchored to different event dates. */
  anchor_date?: string | null;
  /** Validation taxonomy emitted by relative_move.py — backend already
   *  populates this on /analyze tickers; mover tickers carry the same
   *  field when the validation pass ran on the underlying event. */
  validation_quality?: ValidationQuality;
  /** Rolled-up support verdict — same vocabulary as ``Ticker.thesis_support``. */
  thesis_support?: ThesisSupport;
}

// ---------------------------------------------------------------------------
// Mover-card enrichment blocks (additive, optional)
// ---------------------------------------------------------------------------
//
// Backend ``_build_mover_summary`` (and the route-level enrichment in
// ``mover_card_normalizer``) attach a number of synthesis blocks to
// every mover card.  They are present on the wire today but were not
// typed here.  Every field is optional so older payloads (and the
// existing tests) keep deserialising without change.

/** Conviction ranking — combined evidence × persistence score the
 *  Still Moving Markets surface sorts on. */
export interface MoverConviction {
  conviction_class: "conviction" | "secondary" | "lagging" | "noisy_mix" | "breaking" | "pending";
  conviction_label?: string;
  conviction_score?: number;
  evidence_quality?: number;
  persistence_quality?: number;
  repricing_state?: string | null;
  why_ranks_here?: string[];
  rationale?: string;
}

/** Validation-outcome aggregate — supportive / contradictory / mixed /
 *  insufficient.  Same vocabulary the thesis_state ladder reads. */
export interface MoverWeightedEvidence {
  evidence_label?: "supportive" | "contradictory" | "mixed" | "insufficient";
  evidence_score?: number;
  evidence_basis?: "evidence_scores" | "tags_only" | "mixed" | "unscorable";
  evidence_reasons?: string[];
  scored_tickers?: number;
  total_tickers?: number;
  tag_only_tickers?: number;
}

/** Evidence-ladder read — the 5-rung tier emitted by
 *  ``evidence_ladder.classify_evidence``.  Carries a one-line
 *  ``narrative`` consumers should prefer over ``support_ratio`` for
 *  the headline explanation. */
export interface MoverEvidenceLadder {
  tier?: "primary_confirmation" | "secondary_confirmation" | "lagging" | "mixed" | "contradicted" | "insufficient";
  reason_code?: string;
  reason_label?: string;
  narrative?: string;
}

/** Single thesis-state word + its short rationale — the same composer
 *  ``thesis_state.derive_thesis_state`` returns. */
export type MoverThesisState =
  | "confirming"
  | "partial"
  | "watching"
  | "weakening"
  | "falsified"
  | "stale"
  | "low_information"
  | "unknown";

/** Proof-discipline status block from ``proof_evaluator``. */
export interface MoverProofStatus {
  status?: "met" | "partial" | "unmet" | "none";
  items?: Array<{ channel?: string; status?: string }>;
}

/** Per-ticker / per-card evidence quality — high / provisional / low. */
export interface MoverEvidenceQuality {
  confidence_basis?: "strong_evidence" | "mixed_quality" | "fragile_basket" | "thin";
  per_ticker?: Array<Record<string, unknown>>;
}

/** Evidence-attribution — confirmation_shape + dominant signals. */
export interface MoverEvidenceAttribution {
  confirmation_shape?:
    | "single_decisive_channel"
    | "broad_confirmation"
    | "scattered_weak"
    | "mixed_offset"
    | "unilateral_contradiction";
  dominant_confirming?: string[];
  dominant_contradicting?: string[];
}

/** Channel-timing read — early_confirming / in_window_confirming /
 *  delayed_on_track / late_and_failing. */
export interface MoverChannelTiming {
  status?: string;
  observations?: Array<Record<string, unknown>>;
}

/** Historical calibration — anchors agreement to saved cohort outcomes. */
export interface MoverCalibration {
  cohort_reliability?: number | null;
  thesis_vs_cohort?: string | null;
}

/** Agreement engine verdict — direct vs second-order count + reason. */
export interface MoverAgreement {
  verdict?: string;
  reason?: string;
  direct_supports?: number;
  direct_contradicts?: number;
  second_order_supports?: number;
  second_order_contradicts?: number;
}

export interface MarketMover {
  event_id: number;
  headline: string;
  mechanism_summary: string;
  event_date: string;
  stage: string;
  persistence: string;
  impact: number;
  support_ratio: number;
  tickers: MoverTicker[];
  transmission_chain?: string[];
  if_persists?: IfPersists;
  days_since_event?: number;
  /** ISO timestamp of the most recent provider refresh for this
   *  event's ticker payload.  Surfaced on the card so users see
   *  "as of HH:MM" and understand the freshness of the numbers. */
  last_market_check_at?: string | null;
  /** Per-card data quality bucket emitted by the backend's
   *  ``sanitize_mover_card`` pass.  "ok" when the last market check
   *  is recent, "stale" when the check is older than the
   *  MOVER_STALE_AFTER_DAYS threshold, "degraded" when the timestamp
   *  itself is missing or unparseable. */
  data_quality?: "ok" | "stale" | "degraded";
  /** Human-readable reason string when data_quality !== "ok". */
  data_quality_reason?: string;
  /** Integer age in days since last_market_check_at.  Null when the
   *  timestamp is missing. */
  data_quality_age_days?: number | null;
  // ---------------------------------------------------------------
  // Enrichment blocks — additive, optional.  All emitted by the
  // backend's _build_mover_summary + mover_card_normalizer; the UI
  // can read whichever it needs for the surface being rendered.
  // ---------------------------------------------------------------
  conviction?: MoverConviction;
  weighted_evidence?: MoverWeightedEvidence;
  evidence?: MoverEvidenceLadder;
  thesis_state?: MoverThesisState;
  /** Short one-line rationale paired with thesis_state. */
  thesis_state_reason?: string;
  /** Names the dominant validation read (primary support / cross-asset
   *  rejection / signal-only / etc).  Distinct from thesis_state_reason
   *  — the rationale explains the *evidence* read, not the ladder step. */
  validation_rationale?: string;
  proof_status?: MoverProofStatus;
  /** Sanitiser stale tag forwarded to the UI ("ok" / "stale" / "legacy"). */
  stale_signal?: "ok" | "stale" | "legacy" | null;
  /** Mechanism family token used by guardrails / dedup. */
  mechanism_family?: string | null;
  agreement?: MoverAgreement;
  attribution?: MoverEvidenceAttribution;
  quality?: MoverEvidenceQuality;
  channel_timing?: MoverChannelTiming;
  calibration?: MoverCalibration;
}

/** Response-level meta block served alongside every mover surface
 *  ({@link MarketMover}).  Pinned fields mirror the backend contract
 *  in ``mover_card_normalizer.compute_mover_meta``. */
export interface MoverSurfaceMeta {
  surfaced_count: number;
  unique_clusters: number;
  unique_families: number;
}

/** Envelope returned by /market-movers, /movers/today, /movers/weekly,
 *  /movers/persistent and /movers/yearly.  Consumers that just want
 *  the cards use ``unwrapMoverSurface`` to collapse back to a plain
 *  ``MarketMover[]``. */
export interface MoverSurfaceResponse {
  items: MarketMover[];
  meta: MoverSurfaceMeta;
}

function unwrapMoverSurface(r: MoverSurfaceResponse | MarketMover[] | null | undefined): MarketMover[] {
  if (Array.isArray(r)) return r;
  if (r && Array.isArray((r as MoverSurfaceResponse).items)) {
    return (r as MoverSurfaceResponse).items;
  }
  return [];
}

export interface TrackRecord {
  total: number;
  validated: number;
  contradicted: number;
  unresolved: number;
  avg_support_ratio: number | null;
  /** Number of events scored from revisit follow-through data
   *  (1d/5d/20d snapshots) rather than initial market-check direction. */
  revisit_scored: number;
  rated_good: number;
  rated_mixed: number;
  rated_poor: number;
}

/** One bucket in the mechanism-family / regime / compound-regime
 *  track-record breakdown.  Same shape across all three breakdowns;
 *  the bucket-identifying keys (family / regime_key / state) differ
 *  per slice but every bucket carries the common counts + means. */
export interface TrackRecordBreakdownBucket {
  // Bucket identifiers — populated per slice type.  At least ONE of
  // these keys is always present; callers render whichever is non-null.
  family?: string;
  family_label?: string;
  regime_key?: string;
  inflation?: string;
  policy_stance?: string;
  state?: string;
  label?: string;
  // Common counts.
  total: number;
  validated: number;
  contradicted: number;
  unresolved: number;
  revisit_scored: number;
  // Derived stats.
  hit_rate: number | null;
  coverage: number | null;
  avg_return_5d: number | null;
  avg_return_20d: number | null;
  avg_support_ratio: number | null;
}

/** Response of GET /stats/track-record/breakdown — three slices of
 *  the same underlying outcome counts, sorted so the largest-sample
 *  buckets lead each list. */
export interface TrackRecordBreakdown {
  total_events: number;
  validated_total: number;
  contradicted_total: number;
  revisit_scored: number;
  hit_rate: number | null;
  by_mechanism_family: TrackRecordBreakdownBucket[];
  by_regime: TrackRecordBreakdownBucket[];
  by_compound_regime: TrackRecordBreakdownBucket[];
  generated_at: string;
}

export interface ConfidenceCalibrationBucket {
  /** Fraction of events with ≥1 supporting ticker (0.0–1.0). */
  hit_rate: number;
  /** Number of events with usable directional outcomes in this bucket. */
  n: number;
}

/** Historical validation rate per confidence bucket.
 *  A bucket is omitted when n < 3 (insufficient data). */
export type ConfidenceCalibration = Partial<Record<Confidence, ConfidenceCalibrationBucket>>;

export interface TickerHeadline {
  headline: string;
  source_count: number;
  published_at: string;
}

export type MacroSurpriseLabel = "beat" | "miss" | "in_line" | "unknown";

/** Compact macro block stamped on a cluster when stored release facts
 *  exist for the indicator the headline references.  Absent when the
 *  cluster is not tied to an official release in the cache. */
export interface ClusterMacroSurprise {
  release_key: string;
  release_time: string;
  actual: number | null;
  prior: number | null;
  revised_prior: number | null;
  consensus: number | null;
  surprise_label: MacroSurpriseLabel | null;
  source: string;
}

/** Per-event macro release context — populated when an analyzed event
 *  maps to a known macro release (CPI / PPI / NFP / Unemployment / PCE).
 *  The canonical empty shape carries ``release_key === null``; the UI
 *  should treat that as "no block to render". */
export interface EventMacroReleaseContext {
  release_key: string | null;
  release_time: string | null;
  actual: number | null;
  prior: number | null;
  revised_prior: number | null;
  consensus: number | null;
  surprise_label: MacroSurpriseLabel | null;
  source: string;
}

/** Per-event policy timing context — populated when an analyzed event's
 *  headline matches a tracked regulatory / trade / rate policy.  The
 *  canonical empty shape carries ``policy_key === null``; the UI
 *  should treat that as "no block to render". */
export interface EventPolicyTimingContext {
  policy_key: string | null;
  announced_date: string | null;
  effective_date: string | null;
  review_date: string | null;
  status: PolicyTimingStatus | null;
  source: string;
}

export type VulnerabilityTier =
  | "resilient" | "moderate" | "vulnerable" | "fragile";
export type CommodityTier =
  | "low" | "moderate" | "high" | "dominant";

/** Per-event country vulnerability context — populated when the event's
 *  text resolves to a country profiled in the backend country_backdrop
 *  fixture.  Canonical empty shape carries ``country === null``. */
export interface EventCountryVulnerabilityContext {
  country: string | null;
  external_balance_risk: VulnerabilityTier | null;
  import_shock_risk: VulnerabilityTier | null;
  commodity_dependence: CommodityTier | null;
  overall_vulnerability: VulnerabilityTier | null;
  rationale: string;
  stale: boolean;
}

/** Deterministic timing block attached to a cluster whose headline
 *  maps to a tracked regulatory / trade / rate policy.  Absent when
 *  no policy match exists — the UI strip must be gated on the block
 *  being present, never fabricated client-side. */
export type PolicyTimingStatus =
  | "announced"
  | "effective"
  | "under_review"
  | "expired";

export interface PolicyTiming {
  policy_key: string;
  announced_date: string;
  effective_date: string;
  review_date: string;
  status: PolicyTimingStatus;
  source: string;
}

export interface NewsCluster {
  headline: string;
  summary?: string;
  consensus?: Record<string, unknown>;
  sources: { name: string; tier?: string }[];
  source_count: number;
  low_signal?: boolean;
  agreement?: string;
  macro_surprise?: ClusterMacroSurprise;
  policy_timing?: PolicyTiming;
}

export type MacroStatus = "upcoming" | "today" | "recent" | "past";

export interface MacroRelease {
  name: string;
  release_date: string;
  period: string;
  status: MacroStatus;
  days_until: number;
}

export type PolicyType = "tariff" | "sanction" | "regulation" | "executive_order" | "rate_decision";
export type PolicyStatus = "announced" | "pre_effective" | "active" | "revisit_due" | "past";

export interface PolicyItem {
  name: string;
  policy_type: PolicyType;
  jurisdiction: string;
  effective_date: string;
  announcement_date: string;
  revisit_date: string;
  description: string;
  status: PolicyStatus;
  days_until: number;
  days_until_revisit: number;
}

export interface RefreshMeta {
  status?: "ok" | "degraded" | "error" | "recent" | "throttled";
  known: number;
  new: number;
  merged: number;
  created: number;
  reused: number;
  source: "incremental" | "stored" | "stored_fallback" | "full_recluster" | "cached_fallback" | "empty";
  ok_feeds?: number;
  fail_feeds?: number;
  error?: string;
  last_successful_refresh?: string | null;
  freshness?: "fresh" | "degraded" | "stale";
}

export interface NewsResponse {
  clusters: NewsCluster[];
  /** Opaque cursor for the next page, or null when no more pages. */
  next_cursor?: string | null;
  total_headlines: number;
  total_count: number;
  feed_status?: unknown[];
  refresh_meta?: RefreshMeta;
  macro_releases?: MacroRelease[];
  policy_items?: PolicyItem[];
  /** "degraded" when an enrichment block (macro_releases, policy_items, ...) fell back. */
  data_quality?: "ok" | "degraded";
  /** Names of the enrichment fields that fell back to defaults. */
  degraded_fields?: string[];
  /** Backend cache-shape stamp (``_NEWS_CACHE_VERSION``).  The guard on the
   *  backend discards any payload whose stamp doesn't match, so the frontend
   *  can treat this as advisory metadata — safe to ignore if absent. */
  _schema_version?: number;
}

/** Supported single-event export formats. Maps directly to API URL segments. */
export type ExportFormat = "text" | "markdown" | "csv" | "json";

/** Raw staleness classification from compute_staleness() on the backend. */
export type StaleSignal = "fresh" | "stale" | "frozen" | "legacy";

/** Maps a StaleSignal to display state for the Archive and Portfolio pages. */
export interface StaleDisplay {
  showIndicator: boolean;
  label: string;
  dotClass: string;
  showRefresh: boolean;
}

export function getStaleDisplay(signal: StaleSignal | undefined): StaleDisplay {
  if (!signal || signal === "fresh") {
    return { showIndicator: false, label: "", dotClass: "", showRefresh: false };
  }
  if (signal === "frozen") {
    return {
      showIndicator: true,
      label: "Archived",
      dotClass: "bg-muted-foreground/40",
      showRefresh: false,
    };
  }
  // stale | legacy
  return {
    showIndicator: true,
    label: "Data outdated",
    dotClass: "bg-amber-500/70",
    showRefresh: true,
  };
}

export interface PortfolioTicker {
  symbol: string;
  role: string;
  direction_tag: string | null;
  return_5d: number | null;
}

export interface PortfolioEntry {
  id: number;
  headline: string;
  event_date: string | null;
  timestamp: string | null;
  stage: string | null;
  persistence: string | null;
  mechanism_summary: string;
  beneficiaries: string[];
  losers: string[];
  market_tickers: PortfolioTicker[];
  confidence: string | null;
  rating: string | null;
  revisit_snapshots: RevisitSnapshot[];
  validation_outcome: "validated" | "contradicted" | "unresolved" | "no_data";
  support_ratio: number | null;
  /** Staleness signal injected by the /portfolio list endpoint. */
  stale_signal?: StaleSignal;
  hours_since_check?: number | null;
  event_age_days?: number | null;
  persistence_signal?: PersistenceSignal;
  /** Compact engine-phase signals decorated by /portfolio. */
  quality_tier?: "actionable" | "watch_only" | "low_information" | null;
  quality_warnings?: string[];
  actionability_check?: { tradable?: boolean | null } | null;
  mechanism_subtype?: string | null;
  /** One-line rationale derived alongside thesis_state. */
  thesis_state_reason?: string | null;
}

/** Server-side filters accepted by GET /portfolio.  Each is optional;
 *  when ALL are omitted the route returns a bare ``PortfolioEntry[]``
 *  for backward compatibility, otherwise it wraps the items in
 *  {@link PortfolioFilteredResponse} so facet counts can size the UI
 *  without a second request.  Mirrors the validators in
 *  ``saved_studies._validate_portfolio_view`` so a saved
 *  ``portfolio_view`` config can be fed verbatim into this shape. */
export interface PortfolioFilters {
  thesis_state?: string;
  proof_quality?: string;
  low_information?: boolean;
  queue?: string;
  mover_window?: "today" | "weekly" | "persistent" | "market";
  quality_tier?: "actionable" | "watch_only" | "low_information";
  tradable?: boolean;
  mechanism_subtype?: string;
}

/** True when at least one filter is set — drives the bare-list vs
 *  envelope contract on the wire. */
export function hasActivePortfolioFilters(f?: PortfolioFilters | null): boolean {
  if (!f) return false;
  return (
    f.thesis_state !== undefined ||
    f.proof_quality !== undefined ||
    f.low_information !== undefined ||
    f.queue !== undefined ||
    f.mover_window !== undefined ||
    f.quality_tier !== undefined ||
    f.tradable !== undefined ||
    (typeof f.mechanism_subtype === "string" && f.mechanism_subtype.length > 0)
  );
}

/** Envelope returned by GET /portfolio when at least one filter param
 *  is present.  ``items`` carries the post-filter rows; the count maps
 *  carry archive-wide (queue/mover/quality_tier) and post-filter
 *  (thesis_state/proof_quality/tradable/mechanism_subtype) facets. */
export interface PortfolioFilteredResponse {
  items: PortfolioEntry[];
  thesis_state_counts: Record<string, number>;
  proof_quality_counts: Record<string, number>;
  queue_counts: Record<string, number>;
  mover_window_counts: Record<string, number>;
  quality_tier_counts: Record<string, number>;
  tradable_counts: { true: number; false: number };
  mechanism_subtype_counts: Record<string, number>;
}

/** Type guard — true when the wire payload is the filtered envelope
 *  rather than a bare ``PortfolioEntry[]``. */
export function isPortfolioEnvelope(
  r: PortfolioEntry[] | PortfolioFilteredResponse | null | undefined,
): r is PortfolioFilteredResponse {
  return !!r && !Array.isArray(r) && Array.isArray((r as PortfolioFilteredResponse).items);
}

/** Always extract the ``PortfolioEntry[]`` regardless of which shape
 *  the wire returned.  Use at the consumer boundary so render code
 *  doesn't need to branch on bare vs envelope. */
export function unwrapPortfolioItems(
  r: PortfolioEntry[] | PortfolioFilteredResponse | null | undefined,
): PortfolioEntry[] {
  if (Array.isArray(r)) return r;
  if (isPortfolioEnvelope(r)) return r.items;
  return [];
}

export interface PlaybookLeadTicker {
  symbol: string | null;
  return_5d: number | null;
  direction_tag: string | null;
}

export interface PlaybookEntry {
  id: number;
  headline: string;
  event_date: string | null;
  stage: string | null;
  persistence: string | null;
  mechanism_summary: string;
  confidence: string | null;
  validation_outcome: "validated" | "contradicted" | "unresolved" | "no_data";
  support_ratio: number | null;
  lead_ticker: PlaybookLeadTicker | null;
  revisit_count: number;
}

export interface NewsTrend {
  headline: string;
  source_count: number;
  record_count: number;
  latest_published_at: string;
  score: number;
}

export interface CohortPersistence {
  distribution: { held: number; faded: number; unknown: number };
  scored: number;
  hold_rate: number;
  mean_20d: number | null;
  median_abs_20d: number | null;
}

export interface CohortRepricing {
  distribution: Record<string, number>;
  scored: number;
  typical: string;
  typical_share: number;
}

export interface CohortFalsification {
  scored_events: number;
  failed_events: number;
  event_failure_rate: number;
  scored_tickers: number;
  ticker_contradictions: number;
  ticker_failure_rate: number;
}

export interface CohortPackSummary {
  pack: string;
  families: string[];
  size: number;
  confidence_basis: "deep" | "medium" | "thin";
  persistence: CohortPersistence;
  repricing_path: CohortRepricing;
  falsification: CohortFalsification;
  summary: string;
  rationale: string;
}

export interface CohortResearchResponse {
  packs: CohortPackSummary[];
  total_events: number;
}

export interface ArchiveDriftWindow {
  label: string;
  start: string;
  end: string;
  size: number;
  family_distribution: Record<string, number>;
  regime: Record<string, {
    dominant: string | null;
    share: number;
    distribution: Record<string, number>;
  }>;
}

export interface ThemeTrendEntry {
  family: string;
  recent_share: number;
  prior_share: number;
  delta: number;
  direction: "up" | "down" | "flat";
  magnitude: "noise" | "small" | "medium" | "large";
  recent_count: number;
  prior_count: number;
}

export interface RegimeDriftEntry {
  axis: string;
  recent: string | null;
  recent_share: number;
  prior: string | null;
  prior_share: number;
  direction: "shifted" | "stable" | "unavailable";
  magnitude: "noise" | "small" | "medium" | "large";
}

export interface CohortComparisonDimension {
  axis: string;
  a_value?: string | number | null;
  b_value?: string | number | null;
  a_share?: number;
  b_share?: number;
  a_top?: string | null;
  b_top?: string | null;
  a_top_share?: number;
  b_top_share?: number;
  a_distribution?: Record<string, number>;
  b_distribution?: Record<string, number>;
  delta?: number | null;
  distance?: number;
  direction?: "a" | "b" | "tie";
  magnitude: "noise" | "small" | "medium" | "large";
}

export interface CohortComparison {
  a_label: string;
  b_label: string;
  a_size: number;
  b_size: number;
  confidence_basis: "deep" | "medium" | "thin";
  dimensions: CohortComparisonDimension[];
  divergence_score: number;
  headline_insight: string;
  rationale: string;
}

export interface CohortComparisonResponse {
  comparison: CohortComparison;
  a_report: CohortPackSummary & { summary: string; rationale: string };
  b_report: CohortPackSummary & { summary: string; rationale: string };
  available_packs: string[];
}

// ---------------------------------------------------------------------------
// Event graph — cross-event cascade + spillover
// ---------------------------------------------------------------------------

export interface EventGraphNode {
  id: number;
  headline: string;
  event_date: string | null;
  mechanism_family: string;
}

export interface EventGraphEdgeComponent {
  component: string;
  contribution: number;
  family?: string;
  signature?: string[];
  jaccard?: number;
  shared_tickers?: string[];
  shared_sectors?: string[];
}

export interface EventGraphEdge {
  parent_id: number;
  child_id: number;
  parent_date: string;
  child_date: string;
  age_days: number;
  weight: number;
  active: boolean;
  components: Record<string, EventGraphEdgeComponent>;
  components_list: EventGraphEdgeComponent[];
  rationale: string;
}

export interface EventGraphResponse {
  generated_at: string;
  total_events: number;
  decay_half_life_days: number;
  active_threshold: number;
  pair_window_days: number;
  active_edges: number;
  total_edges: number;
  nodes: EventGraphNode[];
  edges: EventGraphEdge[];
}

export interface ArchiveDriftResponse {
  available: boolean;
  anchor_date: string;
  windows: ArchiveDriftWindow[];
  theme_trends: ThemeTrendEntry[];
  regime_drift: RegimeDriftEntry[];
  confidence_basis: "deep" | "medium" | "thin";
  summary: string;
}

// ---------------------------------------------------------------------------
// Cross-event correlation studies
// ---------------------------------------------------------------------------
// Archive-native research surface — pairs of mechanism families that
// cluster in time, sector-pair co-occurrence across events, recurring
// transmission-path shapes, and family × sector hit-rate cross-cuts.
// Wrapped by `/portfolio/cross-event-studies`.

export interface CrossEventFamilyPair {
  family_a: string;
  family_b: string;
  count: number;
  window_days: number;
  event_ids: number[];
}

export interface CrossEventSectorPair {
  sector_a: string;
  sector_b: string;
  count: number;
  event_ids: number[];
}

export interface CrossEventPathCluster {
  signature: string[];
  count: number;
  families: Record<string, number>;
  event_ids: number[];
}

export interface CrossEventCombination {
  mechanism_family: string;
  sector: string;
  total: number;
  validated: number;
  contradicted: number;
  hit_rate: number | null;
  event_ids: number[];
}

export interface CrossEventStudiesResponse {
  generated_at: string;
  window_days: number;
  total_events: number;
  family_cooccurrence: CrossEventFamilyPair[];
  sector_clusters: CrossEventSectorPair[];
  path_clusters: CrossEventPathCluster[];
  combination_outcomes: CrossEventCombination[];
}

// Saved study views — persistent, deterministic research-workflow configs.
// Config shape varies per ``study_type``; the backend validates against a
// closed schema on save (see ``saved_studies.py``).  The UI treats ``config``
// as an opaque JSON blob and hands it back unchanged on reopen.
export type SavedStudyType =
  | "cohort_comparison"
  | "correlation_study"
  | "scenario_pack_research"
  | "cascade_view"
  | "portfolio_view";

export interface SavedStudy {
  id: number;
  study_type: SavedStudyType;
  name: string;
  description: string;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface SavedStudiesListResponse {
  studies: SavedStudy[];
}

export interface SaveStudyRequest {
  study_type: SavedStudyType;
  name: string;
  description?: string;
  config: Record<string, unknown>;
  overwrite?: boolean;
}

export interface ResearchExportStudyInline {
  study_type: SavedStudyType;
  name?: string;
  description?: string;
  config: Record<string, unknown>;
}

export interface ResearchExportRequest {
  saved_study_ids?: number[];
  studies?: ResearchExportStudyInline[];
  format?: "json" | "markdown";
  limit?: number;
}

export interface ResearchExportStudyOutput {
  id?: number;
  name?: string;
  description?: string;
  study_type: SavedStudyType | null;
  config: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  error: string | null;
}

export interface ResearchExportBundle {
  generated_at: string;
  total_events: number;
  studies: ResearchExportStudyOutput[];
  counts: { studies: number; errored: number; succeeded: number };
}

export interface SimulatePortfolioRequest {
  event_ids: number[];
  horizon?: "1d" | "5d" | "20d";
  include_shorts?: boolean;
  direction_filter?: "all" | "supporting";
}

export interface SimulatePosition {
  event_id: number;
  event_headline: string;
  event_date: string | null;
  event_confidence: string | null;
  symbol: string;
  role: string;
  direction_tag: string | null;
  weight: number;
  gross_return: number | null;
  portfolio_return: number | null;
  return_source: "revisit" | "market_check" | "missing";
  short: boolean;
}

export interface SimulateWarning {
  type: "concentration" | "missing_data" | "low_confidence";
  symbol?: string;
  event_count: number;
  total_weight?: number;
  message: string;
}

export interface SimulatePortfolioResponse {
  summary: {
    events_requested: number;
    events_contributing: number;
    events_with_data: number;
    positions_total: number;
    positions_with_data: number;
    portfolio_return: number | null;
    data_coverage: number;
    win_rate: number | null;
    horizon: string;
    include_shorts: boolean;
    direction_filter: string;
  };
  positions: SimulatePosition[];
  warnings: SimulateWarning[];
}

export interface HealthDetail {
  api_status: string;
  refresh_at: string | null;
  refresh_age_seconds: number | null;
  feed_health: {
    ok: number;
    failed: number;
    total: number;
    failing: { name: string; error: string }[];
  };
  pipeline: {
    clusters_cached: number;
    total_headlines: number;
    freshness: "fresh" | "degraded" | "stale" | null;
  };
  overall: "ok" | "degraded" | "error" | "no_data";
}

/**
 * Build the /news path with pagination params.
 *
 * Uses a stable server-issued cursor (opaque string) instead of offset so
 * that pagination is not corrupted when the cached cluster list shifts
 * between requests (cluster added/removed at the head).  Absence of
 * `cursor` means "first page".
 *
 * Exported for unit tests.
 */
export function _buildNewsPath(limit?: number, cursor?: string): string {
  const params = new URLSearchParams();
  if (limit !== undefined) params.set("limit", String(limit));
  if (cursor !== undefined && cursor !== "") params.set("cursor", cursor);
  const qs = params.toString();
  return qs ? `/news?${qs}` : "/news";
}

/**
 * Pure URL builder for ``GET /portfolio``.  Exported for unit tests so
 * the query-param contract for filters can be asserted without hitting
 * the network.  Mirrors the validators in
 * ``saved_studies._validate_portfolio_view``: every filter is optional
 * and only emitted when set.
 *
 * Always emits ``limit`` (default 20) so the caller never lands on the
 * bare ``/portfolio`` route — the route accepts no-args, but the
 * frontend pins the page size.
 */
export function _buildPortfolioPath(
  limit: number = 20,
  filters?: PortfolioFilters,
): string {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  const f = filters ?? {};
  if (f.thesis_state) params.set("thesis_state", f.thesis_state);
  if (f.proof_quality) params.set("proof_quality", f.proof_quality);
  if (f.low_information !== undefined) params.set("low_information", String(f.low_information));
  if (f.queue) params.set("queue", f.queue);
  if (f.mover_window) params.set("mover_window", f.mover_window);
  if (f.quality_tier) params.set("quality_tier", f.quality_tier);
  if (f.tradable !== undefined) params.set("tradable", String(f.tradable));
  if (f.mechanism_subtype) params.set("mechanism_subtype", f.mechanism_subtype);
  return `/portfolio?${params.toString()}`;
}

export const api = {
  health: () => request<{ status: string }>("/health"),
  healthDetail: () => request<HealthDetail>("/health/detail"),

  analyze: (body: AnalyzeRequest) =>
    request<AnalyzeResponse>("/analyze", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** Stream analysis via SSE. Calls onEvent for each stage.
   *  Pass an AbortSignal to cancel the stream (e.g. on re-submit or unmount). */
  analyzeStream: (
    body: AnalyzeRequest,
    onEvent: (stage: string, data: Record<string, unknown>) => void,
    signal?: AbortSignal,
  ): Promise<void> => {
    return new Promise((resolve, reject) => {
      fetch(`${BASE}/analyze/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal,
      }).then((res) => {
        if (!res.ok) {
          res.text().then((t) => reject(new Error(`${res.status}: ${t}`)));
          return;
        }
        const reader = res.body?.getReader();
        if (!reader) { reject(new Error("No response body")); return; }

        const decoder = new TextDecoder();
        let buf = "";

        function pump(): void {
          if (signal?.aborted) { reader!.cancel(); resolve(); return; }
          reader!.read().then(({ done, value }) => {
            if (done || signal?.aborted) { resolve(); return; }
            buf += decoder.decode(value, { stream: true });
            const lines = buf.split("\n");
            buf = lines.pop() ?? "";
            for (const line of lines) {
              if (line.startsWith("data: ")) {
                try {
                  const parsed = JSON.parse(line.slice(6));
                  onEvent(parsed._phase as string, parsed);
                } catch { /* skip malformed */ }
              }
            }
            pump();
          }).catch((e) => {
            if (signal?.aborted) { resolve(); return; }
            reject(e);
          });
        }
        pump();
      }).catch((e) => {
        if (signal?.aborted) { resolve(); return; }
        reject(e);
      });
    });
  },

  events: (query: EventsQuery = {}): Promise<EventsPage> => {
    const params = new URLSearchParams();
    if (query.limit   != null) params.set("limit",       String(query.limit));
    if (query.offset  != null) params.set("offset",      String(query.offset));
    if (query.search)          params.set("search",      query.search);
    if (query.stage)           params.set("stage",       query.stage);
    if (query.persistence)     params.set("persistence", query.persistence);
    if (query.confidence)      params.set("confidence",  query.confidence);
    if (query.rating)          params.set("rating",      query.rating);
    if (query.date_from)       params.set("date_from",   query.date_from);
    if (query.date_to)         params.set("date_to",     query.date_to);
    if (query.validated)       params.set("validated",   query.validated);
    const qs = params.toString();
    return request<EventsPage>(`/events${qs ? `?${qs}` : ""}`);
  },

  updateReview: (eventId: number, body: { rating?: string; notes?: string }) =>
    request<{ ok: boolean; event_id: number }>(
      `/events/${eventId}/review`,
      { method: "PATCH", body: JSON.stringify(body) },
    ),

  deleteEvent: (eventId: number) =>
    request<{ ok: boolean; event_id: number }>(
      `/events/${eventId}`,
      { method: "DELETE" },
    ),

  /** Fetch the text memo for one saved event as a Blob for browser download. */
  downloadEventText: async (eventId: number): Promise<Blob> => {
    const res = await fetch(`${BASE}/events/${eventId}/export/text`);
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new ApiError(
        res.status === 404 ? "Event not found." : "Export failed.",
        res.status,
        detail,
      );
    }
    return res.blob();
  },

  /** Fetch one saved event as a Blob in any supported format.
   *  The format maps directly to the URL segment: /events/{id}/export/{format}. */
  downloadEventBlob: async (eventId: number, format: ExportFormat): Promise<Blob> => {
    const res = await fetch(`${BASE}/events/${eventId}/export/${format}`);
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new ApiError(
        res.status === 404 ? "Event not found." : "Export failed.",
        res.status,
        detail,
      );
    }
    return res.blob();
  },

  /** Export selected events as a portfolio-style Markdown report with cover page. */
  downloadPortfolio: async (eventIds: number[]): Promise<Blob> => {
    const res = await fetch(`${BASE}/events/export/portfolio`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event_ids: eventIds }),
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new ApiError("Portfolio export failed.", res.status, detail);
    }
    return res.blob();
  },

  /** Export selected events as a zip of individual markdown memos. */
  downloadSelectionZip: async (eventIds: number[]): Promise<Blob> => {
    const res = await fetch(`${BASE}/events/export/zip`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event_ids: eventIds }),
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new ApiError("Zip export failed.", res.status, detail);
    }
    return res.blob();
  },

  /** Fetch the full event archive as a bulk export blob (CSV or JSON). */
  downloadBulkExport: async (format: "csv" | "json", limit = 10_000): Promise<Blob> => {
    const res = await fetch(`${BASE}/events/export?format=${format}&limit=${limit}`);
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new ApiError("Bulk export failed.", res.status, detail);
    }
    return res.blob();
  },

  relatedEvents: (eventId: number) =>
    request<RelatedEvent[]>(`/events/${eventId}/related`),

  cascadeGraph: (eventId: number) =>
    request<CascadeGraph>(`/events/${eventId}/cascade`),

  /** Re-run market check for a saved event without re-running LLM analysis.
   *  Returns the refreshed market block so the UI can update in place. */
  refreshMarket: (eventId: number) =>
    request<{ event_id: number; market: MarketResult }>(
      `/events/${eventId}/refresh-market`,
      { method: "POST" },
    ),

  /** Fetch stored revisit timeline snapshots for an event. */
  getRevisitTimeline: (eventId: number) =>
    request<RevisitTimeline>(`/events/${eventId}/revisit`),

  /** Capture a new revisit snapshot (1d/5d/20d follow-through). */
  captureRevisit: (eventId: number) =>
    request<RevisitTimeline>(`/events/${eventId}/revisit`, { method: "POST" }),

  /** Fetch a saved event as a structured JSON object for read-only views (e.g. share page). */
  getEventJson: (eventId: number) =>
    request<SavedEvent>(`/events/${eventId}/export/json`),

  backtest: (eventId: number, force = false) =>
    request<BacktestResult>(
      `/events/${eventId}/backtest${force ? "?force=true" : ""}`,
    ),

  backtestBatch: (eventIds: number[], force = false) =>
    request<BacktestResult[]>("/backtest/batch", {
      method: "POST",
      body: JSON.stringify({ event_ids: eventIds, force }),
    }),

  macroBatch: (eventDates: string[]) =>
    request<Record<string, MacroEntry[]>>("/macro/batch", {
      method: "POST",
      body: JSON.stringify({ event_dates: eventDates }),
    }),

  stress: () => request<StressRegime>("/stress"),

  ratesContext: () => request<RatesContext>("/rates-context"),

  snapshots: (refresh = false) =>
    request<MarketSnapshot[]>(`/snapshots${refresh ? "?refresh=true" : ""}`),

  marketContext: (highlightLimit = 3) =>
    request<MarketContext>(`/market-context?highlight_limit=${highlightLimit}`),

  registryDiagnostics: () =>
    request<RegistryDiagnostics>("/registry/diagnostics"),

  backfillPreview: (opts: { limit?: number; sinceHours?: number } = {}) => {
    const params = new URLSearchParams();
    params.set("limit", String(opts.limit ?? 5));
    params.set("since_hours", String(opts.sinceHours ?? 72));
    return request<BackfillPreviewResponse>(`/movers/backfill-preview?${params.toString()}`);
  },

  marketMovers: () =>
    request<MoverSurfaceResponse>("/market-movers").then(unwrapMoverSurface),

  moversToday: () =>
    request<MoverSurfaceResponse>("/movers/today").then(unwrapMoverSurface),
  moversWeekly: () =>
    request<MoverSurfaceResponse>("/movers/weekly").then(unwrapMoverSurface),
  moversYearly: () =>
    request<MoverSurfaceResponse>("/movers/yearly").then(unwrapMoverSurface),
  moversPersistent: () =>
    request<MoverSurfaceResponse>("/movers/persistent").then(unwrapMoverSurface),

  trackRecord: () => request<TrackRecord>("/stats/track-record"),

  trackRecordBreakdown: () =>
    request<TrackRecordBreakdown>("/stats/track-record/breakdown"),

  confidenceCalibration: () => request<ConfidenceCalibration>("/stats/confidence-calibration"),

  /** Fetch the ranked portfolio.  Without filters returns a bare
   *  ``PortfolioEntry[]`` (backward-compatible).  With filters the
   *  backend wraps the items in {@link PortfolioFilteredResponse}; use
   *  {@link unwrapPortfolioItems} on the consumer side to get a single
   *  item array regardless of which shape was returned. */
  portfolio: (
    opts: { limit?: number; filters?: PortfolioFilters } = {},
  ) =>
    request<PortfolioEntry[] | PortfolioFilteredResponse>(
      _buildPortfolioPath(opts.limit, opts.filters),
    ),

  cohortResearch: (limit = 500) =>
    request<CohortResearchResponse>(`/portfolio/cohort-research?limit=${limit}`),

  archiveDrift: (limit = 500) =>
    request<ArchiveDriftResponse>(`/portfolio/archive-drift?limit=${limit}`),

  eventGraph: (limit = 500) =>
    request<EventGraphResponse>(`/portfolio/event-graph?limit=${limit}`),

  cohortComparison: (a: string, b: string, limit = 500) =>
    request<CohortComparisonResponse>(
      `/portfolio/cohort-comparison?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}&limit=${limit}`,
    ),

  crossEventStudies: (limit = 500) =>
    request<CrossEventStudiesResponse>(
      `/portfolio/cross-event-studies?limit=${limit}`,
    ),

  savedStudies: (studyType?: SavedStudyType | null) =>
    request<SavedStudiesListResponse>(
      studyType
        ? `/portfolio/saved-studies?study_type=${encodeURIComponent(studyType)}`
        : `/portfolio/saved-studies`,
    ),

  savedStudy: (studyId: number) =>
    request<SavedStudy>(`/portfolio/saved-studies/${studyId}`),

  saveStudy: (body: SaveStudyRequest) =>
    request<SavedStudy>(`/portfolio/saved-studies`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  deleteStudy: (studyId: number) =>
    request<{ deleted: boolean; id: number }>(
      `/portfolio/saved-studies/${studyId}`,
      { method: "DELETE" },
    ),

  researchExportJson: (body: ResearchExportRequest) =>
    request<ResearchExportBundle>(`/portfolio/research-export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...body, format: "json" }),
    }),

  researchExportMarkdown: async (body: ResearchExportRequest): Promise<string> => {
    const res = await fetch(`${BASE}/portfolio/research-export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...body, format: "markdown" }),
    });
    if (!res.ok) {
      throw new Error(`Research export failed: ${res.status}`);
    }
    return res.text();
  },

  regimePlaybook: (regime: string, limit = 4) =>
    request<PlaybookEntry[]>(
      `/regime-playbook?regime=${encodeURIComponent(regime)}&limit=${limit}`,
    ),

  tickerChart: (symbol: string, eventDate: string) =>
    request<ChartPoint[]>(`/ticker/${encodeURIComponent(symbol)}/chart?event_date=${eventDate}`),

  tickerInfo: (symbol: string) =>
    request<TickerInfo>(`/ticker/${encodeURIComponent(symbol)}/info`),

  tickerHeadlines: (symbol: string) =>
    request<TickerHeadline[]>(`/ticker/${encodeURIComponent(symbol)}/headlines`),

  news: (limit?: number, cursor?: string) =>
    request<NewsResponse>(_buildNewsPath(limit, cursor)),

  newsRefresh: (signal?: AbortSignal) =>
    request<NewsResponse>("/news/refresh", { method: "POST", signal }),

  newsTrends: () => request<NewsTrend[]>("/news/trends"),

  simulatePortfolio: (body: SimulatePortfolioRequest) =>
    request<SimulatePortfolioResponse>("/portfolio/simulate", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
