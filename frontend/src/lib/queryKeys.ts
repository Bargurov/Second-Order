import type { EventsQuery } from "@/lib/api";

/**
 * Centralised query key factory for React Query.
 * Using a factory keeps keys consistent and makes invalidation predictable.
 */
export const qk = {
  news:       () => ["news"] as const,
  events:     (query: EventsQuery) => ["events", query] as const,
  eventById:  (id: number) => ["events", id] as const,
  eventShare: (id: number) => ["events", id, "share"] as const,
  eventStudy: (id: number) => ["events", id, "event-study"] as const,
  related:    (id: number) => ["events", id, "related"] as const,
  cascade:    (id: number) => ["events", id, "cascade"] as const,
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
  validationStatusStats: () => ["diagnostics", "validation-status-stats"] as const,
  reactionProfileStats: () => ["diagnostics", "reaction-profile-stats"] as const,
  diagnosticsTrackRecord: () => ["diagnostics", "track-record"] as const,
  registryDiagnostics: () => ["registry", "diagnostics"] as const,
  registryCandidateQueue: (limit: number, sinceHours: number) =>
    ["registry", "candidate-queue", limit, sinceHours] as const,
  backfillPreview: (limit: number, sinceHours: number) =>
    ["movers", "backfill-preview", limit, sinceHours] as const,
  marketMovers:  () => ["market-movers"] as const,
  moversToday:   () => ["movers", "today"] as const,
  moversWeekly:  () => ["movers", "weekly"] as const,
  moversYearly:     () => ["movers", "yearly"] as const,
  moversPersistent: () => ["movers", "persistent"] as const,
  trackRecord:            () => ["stats", "track-record"] as const,
  trackedEvidenceSummary: () => ["evidence", "summary"] as const,
  missionGEvidence:       () => ["evidence", "mission-g"] as const,
  missionIEvidence:       () => ["evidence", "mission-i"] as const,
  missionJEvidence:       () => ["evidence", "mission-j"] as const,
  trackRecordBreakdown:   () => ["stats", "track-record", "breakdown"] as const,
  confidenceCalibration:  () => ["stats", "confidence-calibration"] as const,
  newsPaginated: (limit: number) => ["news", "paginated", limit] as const,
  newsTrends:    () => ["news", "trends"] as const,
  portfolio:         (filterFingerprint?: string) =>
    filterFingerprint
      ? (["portfolio", "filtered", filterFingerprint] as const)
      : (["portfolio"] as const),
  cohortResearch:    () => ["portfolio", "cohort-research"] as const,
  archiveDrift:      () => ["portfolio", "archive-drift"] as const,
  eventGraph:        () => ["portfolio", "event-graph"] as const,
  cohortComparison:  (a: string, b: string) => ["portfolio", "cohort-comparison", a, b] as const,
  crossEventStudies: () => ["portfolio", "cross-event-studies"] as const,
  savedStudies:      (studyType?: string | null) =>
    ["portfolio", "saved-studies", studyType ?? "all"] as const,
  simulate:          (ids: number[]) => ["portfolio", "simulate", ...ids] as const,
  refreshMarket: (id: number) => ["events", id, "refresh-market"] as const,
  regimePlaybook:    (regime: string) => ["regime-playbook", regime] as const,
  health:            () => ["health"] as const,
  healthDetail:      () => ["health", "detail"] as const,
};
