/**
 * Centralised query key factory for React Query.
 * Using a factory keeps keys consistent and makes invalidation predictable.
 */
export const qk = {
  news:       () => ["news"] as const,
  events:     (limit: number) => ["events", limit] as const,
  eventById:  (id: number) => ["events", id] as const,
  related:    (id: number) => ["events", id, "related"] as const,
  backtest:   (id: number) => ["backtest", id] as const,
  backtestBatch: (ids: number[]) => ["backtest", "batch", ...ids] as const,
  macroBatch: (dates: string[]) => ["macro", "batch", ...dates] as const,
  tickerChart: (symbol: string, date: string) => ["ticker", symbol, "chart", date] as const,
  tickerInfo:      (symbol: string) => ["ticker", symbol, "info"] as const,
  tickerHeadlines: (symbol: string) => ["ticker", symbol, "headlines"] as const,
  stress:        () => ["stress"] as const,
  ratesContext:  () => ["rates-context"] as const,
  snapshots:     () => ["snapshots"] as const,
  marketContext: () => ["market-context"] as const,
  marketMovers:  () => ["market-movers"] as const,
  moversToday:   () => ["movers", "today"] as const,
  moversWeekly:  () => ["movers", "weekly"] as const,
  moversYearly:     () => ["movers", "yearly"] as const,
  moversPersistent: () => ["movers", "persistent"] as const,
  newsPaginated: (limit: number) => ["news", "paginated", limit] as const,
  health:        () => ["health"] as const,
};
