const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export interface AnalyzeRequest {
  headline: string;
  event_date?: string;
  event_context?: string;
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
  bucket?: FreshnessBucket;
  /** The unforced classification — "frozen" when force_bypassed is true. */
  natural_bucket?: FreshnessBucket;
  event_age_days?: number | null;
  is_frozen?: boolean;
  force_bypassed?: boolean;
}

export interface AnalysisDetail {
  what_changed: string;
  mechanism_summary: string;
  beneficiaries: string[];
  losers: string[];
  beneficiary_tickers: string[];
  loser_tickers: string[];
  assets_to_watch: string[];
  confidence: string;
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
  historical_analogs?: HistoricalAnalog[];
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

export interface MarketContext {
  built_at: string;
  source: string;
  snapshots: MarketSnapshot[];
  snapshots_meta: SnapshotsMeta;
  stress: StressRegime & { available?: boolean };
  highlights: MarketMover[];
  highlights_meta: HighlightsMeta;
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

export interface MarketMover {
  event_id: number;
  headline: string;
  mechanism_summary: string;
  event_date: string;
  stage: string;
  persistence: string;
  impact: number;
  support_ratio: number;
  tickers: {
    symbol: string;
    role: string;
    return_5d: number | null;
    return_20d?: number | null;
    direction: string | null;
    spark: number[];
    decay?: string;
    decay_evidence?: string;
  }[];
  transmission_chain?: string[];
  if_persists?: IfPersists;
  currency_channel?: CurrencyChannel;
  policy_sensitivity?: PolicySensitivity;
  inventory_context?: InventoryContext;
  real_yield_context?: RealYieldContext;
  policy_constraint?: PolicyConstraint;
  days_since_event?: number;
}

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

export interface NewsResponse {
  clusters: NewsCluster[];
  total_headlines: number;
  total_count: number;
  feed_status?: unknown[];
}

export const api = {
  health: () => request<{ status: string }>("/health"),

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

  relatedEvents: (eventId: number) =>
    request<RelatedEvent[]>(`/events/${eventId}/related`),

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

  tickerChart: (symbol: string, eventDate: string) =>
    request<ChartPoint[]>(`/ticker/${encodeURIComponent(symbol)}/chart?event_date=${eventDate}`),

  tickerInfo: (symbol: string) =>
    request<TickerInfo>(`/ticker/${encodeURIComponent(symbol)}/info`),

  tickerHeadlines: (symbol: string) =>
    request<TickerHeadline[]>(`/ticker/${encodeURIComponent(symbol)}/headlines`),

  news: (limit?: number, offset?: number) => {
    const params = new URLSearchParams();
    if (limit) params.set("limit", String(limit));
    if (offset) params.set("offset", String(offset));
    const qs = params.toString();
    return request<NewsResponse>(`/news${qs ? `?${qs}` : ""}`);
  },
};
