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

export interface MarketResult {
  note: string;
  details: Record<string, unknown>;
  tickers: Ticker[];
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

  backtest: (eventId: number) =>
    request<BacktestResult>(`/events/${eventId}/backtest`),

  backtestBatch: (eventIds: number[]) =>
    request<BacktestResult[]>("/backtest/batch", {
      method: "POST",
      body: JSON.stringify({ event_ids: eventIds }),
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
