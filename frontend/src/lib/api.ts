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
  historical_analogs?: HistoricalAnalog[];
  /** True when the analysis was degraded (missing overlays/context). */
  degraded?: boolean;
  /** Validation warnings from rule checks (only present when non-empty). */
  validation_warnings?: string[];
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

export interface PolicySensitivity {
  stance?: "reinforced" | "fighting" | "neutral";
  explanation?: string;
  regime?: string;
}

export interface InventoryContext {
  status?: "tight" | "comfortable" | "neutral";
  proxy?: string;
  proxy_label?: string;
  return_20d?: number;
  explanation?: string;
}

export interface RealYieldContext {
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

export interface PolicyConstraint {
  binding?: PolicyConstraintId;
  binding_label?: string;
  secondary?: PolicyConstraintSecondary[];
  policy_room?: "ample" | "limited" | "constrained" | "mixed" | "unknown";
  why?: string;
  reaction_function?: string;
  key_markets?: string[];
  signals?: Record<string, number>;
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

export interface ShockDecomposition {
  primary?: ShockChannelId;
  primary_label?: string;
  secondary?: ShockSecondary[];
  rationale?: string;
  macro_read?: string;
  key_markets?: string[];
  channels?: Record<string, ShockChannelEntry>;
  available?: boolean;
  stale?: boolean;
}

export type ReactionDirection = "hawkish" | "dovish" | "neutral";
export type ReactionDivergence = "aligned" | "mild" | "sharp";

export interface ReactionFunctionDivergence {
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

export interface SurpriseVsAnticipation {
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

export interface TermsOfTrade {
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

export interface ReserveStress {
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

export interface NarrativeDivergence {
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
  available: boolean;
  stale?: boolean;
}

export interface MarketContext {
  built_at: string;
  source: string;
  snapshots: MarketSnapshot[];
  snapshots_meta: SnapshotsMeta;
  /** Backend always sends stress/rates/regime_vector (with available:false when degraded). */
  stress: StressRegime & { available?: boolean };
  rates: RatesContext & { available?: boolean };
  regime_vector: RegimeVector;
  highlights: MarketMover[];
  highlights_meta: HighlightsMeta;
  uncertainty_concentration?: NewsUncertaintyConcentration;
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

export interface NewsCluster {
  headline: string;
  summary?: string;
  consensus?: Record<string, unknown>;
  sources: { name: string; tier?: string }[];
  source_count: number;
  low_signal?: boolean;
  agreement?: string;
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
  total_headlines: number;
  total_count: number;
  feed_status?: unknown[];
  refresh_meta?: RefreshMeta;
  macro_releases?: MacroRelease[];
  policy_items?: PolicyItem[];
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
 * Uses explicit `!== undefined` checks so that offset=0 (first page of an
 * infinite query) is included in the URL just like offset=30 (second page).
 * The previous `if (offset)` check silently dropped offset=0, making
 * first-page and next-page request URLs structurally inconsistent.
 *
 * Exported for unit tests.
 */
export function _buildNewsPath(limit?: number, offset?: number): string {
  const params = new URLSearchParams();
  if (limit !== undefined) params.set("limit", String(limit));
  if (offset !== undefined) params.set("offset", String(offset));
  const qs = params.toString();
  return qs ? `/news?${qs}` : "/news";
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

  events: (limit = 25) =>
    request<SavedEvent[]>(`/events?limit=${limit}`),

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

  marketMovers: () => request<MarketMover[]>("/market-movers"),

  moversToday: () => request<MarketMover[]>("/movers/today"),
  moversWeekly: () => request<MarketMover[]>("/movers/weekly"),
  moversYearly: () => request<MarketMover[]>("/movers/yearly"),
  moversPersistent: () => request<MarketMover[]>("/movers/persistent"),

  trackRecord: () => request<TrackRecord>("/stats/track-record"),

  confidenceCalibration: () => request<ConfidenceCalibration>("/stats/confidence-calibration"),

  portfolio: (limit = 20) =>
    request<PortfolioEntry[]>(`/portfolio?limit=${limit}`),

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

  news: (limit?: number, offset?: number) =>
    request<NewsResponse>(_buildNewsPath(limit, offset)),

  newsRefresh: (signal?: AbortSignal) =>
    request<NewsResponse>("/news/refresh", { method: "POST", signal }),

  newsTrends: () => request<NewsTrend[]>("/news/trends"),

  simulatePortfolio: (body: SimulatePortfolioRequest) =>
    request<SimulatePortfolioResponse>("/portfolio/simulate", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
