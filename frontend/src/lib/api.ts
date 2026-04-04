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
}

export interface Ticker {
  symbol: string;
  role: string;
  label: string;
  direction_tag: string | null;
  return_1d: number;
  return_5d: number;
  return_20d: number;
  volume_ratio: number;
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

export interface NewsCluster {
  headline: string;
  sources: { name: string }[];
  source_count: number;
}

export interface NewsResponse {
  clusters: NewsCluster[];
  total_headlines: number;
}

export const api = {
  health: () => request<{ status: string }>("/health"),

  analyze: (body: AnalyzeRequest) =>
    request<AnalyzeResponse>("/analyze", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  events: (limit = 25) =>
    request<SavedEvent[]>(`/events?limit=${limit}`),

  updateReview: (eventId: number, body: { rating?: string; notes?: string }) =>
    request<{ ok: boolean; event_id: number }>(
      `/events/${eventId}/review`,
      { method: "PATCH", body: JSON.stringify(body) },
    ),

  news: () => request<NewsResponse>("/news"),
};
