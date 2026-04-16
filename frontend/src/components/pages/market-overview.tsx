import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { ArrowRight, AlertTriangle, FlaskConical } from "lucide-react";
import { api, type MarketMover, type TrackRecord, type NewsCluster, type RegimeVector, type RefreshMeta, type PlaybookEntry } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { pct } from "@/lib/ticker-utils";
import { buildClusterContext } from "@/lib/cluster-context";
import { UncertaintySection } from "@/components/ui/stress-strip";
import { SystemHealthPanel } from "@/components/ui/system-health-panel";
import { BenchmarkSnapshotsStrip } from "@/components/ui/benchmark-snapshots-strip";
import { deriveContextDegradedNotice } from "@/components/ui/degraded-data-notice";
import { DegradedBanner } from "@/components/ui/degraded-banner";
import { MetricCard } from "@/components/ui/metric-card";
import { EventIntelligenceCard } from "@/components/ui/event-intelligence-card";

// ---------------------------------------------------------------------------
// Card-level helpers
// ---------------------------------------------------------------------------

/** Format an ISO timestamp as a compact "as of MMM D · HH:MM" string.
 *  Used by the per-card freshness footer so users can see when the
 *  ticker numbers were last refreshed against the provider. */
function _fmtAsOf(ts?: string | null): string | null {
  if (!ts) return null;
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Pick the canonical "anchor date" for a card.
 *
 *  Prefers the per-ticker ``anchor_date`` (the actual first trading
 *  bar the forward returns were measured from) when every emitted
 *  ticker agrees.  Falls back to the event_date if the per-ticker
 *  field is missing — legacy persisted rows don't carry it.  This
 *  is the value users see as "anchored YYYY-MM-DD" and explains why
 *  the same symbol can read differently across cards. */
function _cardAnchorDate(mover: MarketMover): string | null {
  const anchors = mover.tickers
    .map((t) => t.anchor_date)
    .filter((a): a is string => !!a);
  if (anchors.length > 0 && anchors.every((a) => a === anchors[0])) {
    return anchors[0] ?? null;
  }
  return mover.event_date || null;
}

// ---------------------------------------------------------------------------
// "Still Moving Markets" hero card — matches Stitch reference exactly
// bg-surface-container-low rounded-xl p-6 border border-transparent hover:border-outline-variant
// ---------------------------------------------------------------------------

function PersistentCard({ mover, onAnalyze }: {
  mover: MarketMover;
  onAnalyze?: (headline: string, opts?: { eventId?: number; context?: string }) => void;
}) {
  const days = mover.days_since_event ?? 0;
  const agreement = Math.round(mover.support_ratio * 100);
  const mech = mover.mechanism_summary || "";
  const snippet = mech.length > 140 ? mech.slice(0, 137) + "..." : mech;
  const anchorDate = _cardAnchorDate(mover);
  const asOf = _fmtAsOf(mover.last_market_check_at);

  // Trajectory from ticker decay values
  const decays = mover.tickers.map((t) => t.decay).filter(Boolean);
  const trajectory = decays.includes("Accelerating")
    ? "Still Accelerating"
    : decays.includes("Holding")
    ? "Still Holding"
    : decays.includes("Fading")
    ? "Fading"
    : "Monitoring";

  return (
    <div className="bg-surface-container-low rounded-xl p-6 flex flex-col justify-between transition-all shadow-[inset_0_0_0_1px_rgba(71,70,86,0.25),0_10px_15px_-3px_rgba(0,0,0,0.12)] hover:shadow-[inset_0_0_0_1px_rgba(71,70,86,0.5),0_10px_15px_-3px_rgba(0,0,0,0.15)]">
      <div>
        {/* Top row: days badge + agreement */}
        <div className="flex justify-between items-start mb-4">
          <span className="bg-surface-container-highest text-on-surface-variant text-[10px] font-bold px-2 py-1 rounded tracking-widest uppercase">
            {days} DAYS AGO
          </span>
          <div
            className="text-right"
            title={`${agreement}% — fraction of qualifying tickers whose realised direction matches the hypothesis`}
          >
            <span className="text-xl font-bold text-primary tnum">{agreement}%</span>
            <p className="text-[10px] text-on-surface-variant uppercase font-bold tracking-widest">Agreement</p>
          </div>
        </div>
        {/* Headline */}
        <h3 className="text-lg font-headline font-bold text-white mb-2 leading-snug line-clamp-2">
          {mover.headline}
        </h3>
        {/* Mechanism snippet */}
        {snippet && (
          <p className="text-sm text-on-surface-variant mb-6 leading-relaxed line-clamp-2">{snippet}</p>
        )}
      </div>
      <div className="space-y-4">
        {/* Ticker pills — symbol + return value only.  Mini sparklines
            were removed: they cluttered the preview and at this card
            scale (12px wide) carried no analytical weight.  Detailed
            charts live on the Analysis page where there's room to
            render them honestly. */}
        <div className="flex items-center gap-3 overflow-x-auto pb-2">
          {mover.tickers.slice(0, 4).map((t) => (
            <div key={t.symbol} className="bg-surface-container-highest px-3 py-2 rounded-lg flex items-center gap-3 shrink-0">
              <span className="text-xs font-bold text-white tracking-wider">{t.symbol}</span>
              {t.return_5d != null && (
                <span className={cn(
                  "text-xs font-bold tnum",
                  t.return_5d > 0 ? "text-primary" : t.return_5d < 0 ? "text-error-dim" : "text-on-surface-variant",
                )}>
                  {pct(t.return_5d)}
                </span>
              )}
            </div>
          ))}
        </div>
        {/* Anchor + as-of footer — explains why the same ticker can
            read differently across cards: each card's returns are
            measured forward from the event's anchor date, and the
            "as of" timestamp shows when the numbers were last
            refreshed.  Hidden cleanly when neither is present. */}
        {(anchorDate || asOf) && (
          <div className="flex items-center justify-between gap-2 text-[9px] text-on-surface-variant/60 uppercase tracking-widest font-medium">
            {anchorDate && (
              <span title="Forward returns measured from this anchor date">
                Anchor <span className="tnum text-on-surface-variant/80">{anchorDate}</span>
              </span>
            )}
            {asOf && (
              <span title="Most recent provider refresh for this card">
                As of <span className="tnum text-on-surface-variant/80">{asOf}</span>
              </span>
            )}
          </div>
        )}
        {/* Trajectory badge + arrow */}
        <div className="flex justify-between items-center pt-4 border-t border-outline-variant/20">
          <span className="bg-primary-container/20 text-primary text-[10px] font-bold px-2 py-1 rounded-full uppercase tracking-widest">
            {trajectory}
          </span>
          {onAnalyze ? (
            <button
              onClick={() => onAnalyze(mover.headline, { eventId: mover.event_id })}
              className="text-on-surface-variant hover:text-primary transition-colors"
            >
              <ArrowRight className="h-[18px] w-[18px]" />
            </button>
          ) : (
            <ArrowRight className="h-[18px] w-[18px] text-on-surface-variant" />
          )}
        </div>
      </div>
    </div>
  );
}

function StillMovingSection({ movers, isLoading, onAnalyze }: {
  movers: MarketMover[] | undefined;
  isLoading: boolean;
  onAnalyze?: (headline: string, opts?: { eventId?: number; context?: string }) => void;
}) {
  const filtered = movers?.slice(0, 4);

  if (isLoading) {
    return (
      <section className="mb-8">
        <div className="flex justify-between items-end mb-6">
          <div>
            <Skeleton className="h-7 w-80 bg-surface-container-highest" />
            <Skeleton className="h-4 w-64 bg-surface-container-highest mt-2" />
          </div>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Skeleton className="h-56 rounded-xl bg-surface-container-low" />
          <Skeleton className="h-56 rounded-xl bg-surface-container-low" />
        </div>
      </section>
    );
  }
  if (!filtered || filtered.length === 0) {
    return (
      <section className="mb-8">
        <div className="flex justify-between items-end mb-6">
          <div>
            <h2 className="text-xl font-headline font-bold text-white tracking-tight">Second Order Effects — Still Moving Markets</h2>
            <p className="text-sm text-on-surface-variant">Long-term macro catalysts and delayed reactive outcomes</p>
          </div>
        </div>
        <div className="rounded-xl border border-dashed border-outline-variant/30 px-6 py-4">
          <span className="text-sm text-on-surface-variant">No long-running effects detected right now</span>
        </div>
      </section>
    );
  }

  return (
    <section className="mb-8">
      <div className="flex justify-between items-end mb-6">
        <div>
          <h2 className="text-xl font-headline font-bold text-white tracking-tight">Second Order Effects — Still Moving Markets</h2>
          <p className="text-sm text-on-surface-variant">Long-term macro catalysts and delayed reactive outcomes</p>
        </div>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {filtered.map((m) => (
          <PersistentCard key={m.event_id} mover={m} onAnalyze={onAnalyze} />
        ))}
      </div>
    </section>
  );
}


// ---------------------------------------------------------------------------
// Today's Movers — fixed bottom strip, matches Stitch reference exactly
// ---------------------------------------------------------------------------

function TodayStrip({ movers, isLoading }: {
  movers: MarketMover[] | undefined;
  isLoading: boolean;
}) {
  if (isLoading || !movers || movers.length === 0) return null;

  return (
    // Inline footer strip — used to be absolute-positioned at the bottom
    // of the workspace (which forced the whole overview into a fixed-
    // height nested-scroll container).  Now it sits at the natural end
    // of the page so the whole document scrolls as one.  The full-bleed
    // background still extends to the workspace edges via the negative
    // margins below.
    <div className="-mx-3 md:-mx-5 mt-12 h-14 bg-surface-container border-t border-outline-variant/10 overflow-hidden flex items-center">
      {/* Label */}
      <div className="bg-primary/10 border-r border-outline-variant/30 px-6 flex items-center h-full shrink-0">
        <span className="text-[10px] font-bold text-primary tracking-[0.2em] uppercase">Today's Movers</span>
      </div>
      {/* Scrolling items */}
      <div className="flex-1 overflow-x-auto whitespace-nowrap py-3 flex gap-8 px-8 items-center">
        {movers.slice(0, 10).map((m, i) => {
          const topTicker = m.tickers[0];
          const trunc = m.headline.length > 40 ? m.headline.slice(0, 37) + "..." : m.headline;
          return (
            <div key={m.event_id} className="contents">
              {i > 0 && <div className="w-px h-4 bg-outline-variant/30 shrink-0" />}
              <div className="flex items-center gap-3 shrink-0">
                {topTicker && (
                  <>
                    <span className="text-xs font-bold text-white">{topTicker.symbol}</span>
                    {topTicker.return_5d != null && (
                      <span className={cn(
                        "text-xs font-bold tnum",
                        topTicker.return_5d > 0 ? "text-primary" : "text-error-dim",
                      )}>
                        {pct(topTicker.return_5d)}
                      </span>
                    )}
                  </>
                )}
                <span className="text-xs text-on-surface-variant truncate w-40">{trunc}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Trending Themes — derive dominant themes from recent clusters
// ---------------------------------------------------------------------------

export interface ThemeEntry {
  label: string;
  category: "action" | "sector";
  clusterCount: number;
  sourceWeight: number;
  regimeAligned: boolean;
}

const _THEME_ALIGNMENT_RULES: Array<{
  pattern: RegExp;
  check: (v: RegimeVector) => boolean;
}> = [
  {
    pattern: /tariff|trade|sanction|embargo/i,
    check: (v) =>
      v.fx === "dollar_strong" || v.fx === "dollar_weak" ||
      v.growth_stress === "stressed" || v.growth_stress === "watch",
  },
  {
    pattern: /rate|fed|monetary|hike|cut|pivot/i,
    check: (v) =>
      v.policy_stance === "hawkish" || v.policy_stance === "dovish" ||
      v.inflation === "hot" || v.inflation === "cool",
  },
  {
    pattern: /oil|energy|gas|commodit/i,
    check: (v) => v.inflation === "hot",
  },
  {
    pattern: /defense|military|war|conflict|geopolit/i,
    check: (v) => v.growth_stress === "stressed" || v.growth_stress === "watch",
  },
  {
    pattern: /dollar|currency|exchange|forex/i,
    check: (v) => v.fx === "dollar_strong" || v.fx === "dollar_weak",
  },
];

export function deriveThemes(
  clusters: NewsCluster[],
  regimeVec: RegimeVector | null,
): ThemeEntry[] {
  const counts = new Map<
    string,
    { label: string; category: "action" | "sector"; clusterCount: number; sourceWeight: number }
  >();

  for (const cluster of clusters) {
    if (cluster.low_signal) continue;
    const cons = cluster.consensus as Record<string, unknown> | null | undefined;
    if (!cons) continue;

    const pairs: Array<[unknown, "action" | "sector"]> = [
      [cons.action, "action"],
      [cons.sector, "sector"],
    ];

    for (const [raw, category] of pairs) {
      if (!raw || typeof raw !== "string") continue;
      const label = raw.trim().toLowerCase();
      if (!label || label === "unknown" || label === "none" || label === "n/a") continue;
      const key = `${category}:${label}`;
      const existing = counts.get(key);
      if (existing) {
        existing.clusterCount += 1;
        existing.sourceWeight += cluster.source_count ?? 0;
      } else {
        counts.set(key, { label, category, clusterCount: 1, sourceWeight: cluster.source_count ?? 0 });
      }
    }
  }

  const themes: ThemeEntry[] = [];
  for (const entry of counts.values()) {
    if (entry.clusterCount < 2 && entry.sourceWeight < 4) continue;
    const aligned =
      !!(regimeVec?.available) &&
      _THEME_ALIGNMENT_RULES.some(({ pattern, check }) => pattern.test(entry.label) && check(regimeVec!));
    themes.push({ ...entry, regimeAligned: aligned });
  }

  themes.sort((a, b) => {
    if (a.regimeAligned !== b.regimeAligned) return a.regimeAligned ? -1 : 1;
    return (b.clusterCount * 2 + b.sourceWeight) - (a.clusterCount * 2 + a.sourceWeight);
  });

  return themes.slice(0, 7);
}

function TrendingThemesPanel({
  clusters,
  regimeVec,
  isLoading,
}: {
  clusters: NewsCluster[];
  regimeVec: RegimeVector | null;
  isLoading: boolean;
}) {
  if (isLoading) return null;
  const themes = deriveThemes(clusters, regimeVec);
  if (themes.length === 0) return null;

  return (
    <section className="mb-6">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-on-surface-variant/40 mr-1">
          Trending Themes
        </span>
        {themes.map((t) => (
          <span
            key={`${t.category}:${t.label}`}
            className={cn(
              "inline-flex items-center px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider",
              t.regimeAligned
                ? "bg-primary/15 text-primary"
                : "bg-surface-container-highest text-on-surface-variant/60",
            )}
          >
            {t.label}
          </span>
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Market Regime — compact one-line summary of macro backdrop
// ---------------------------------------------------------------------------

const _AXIS_LABELS: Record<string, string> = {
  hot: "Inflation hot",
  cool: "Inflation cool",
  hawkish: "Policy hawkish",
  dovish: "Policy dovish",
  dollar_strong: "USD strong",
  dollar_weak: "USD weak",
  watch: "Growth watch",
  stressed: "Growth stressed",
};

function _axisChipClass(axis: string, value: string): string {
  if (axis === "inflation" && value === "hot") return "text-error-dim bg-error-dim/10";
  if (axis === "inflation" && value === "cool") return "text-primary bg-primary/10";
  if (axis === "policy_stance" && value === "hawkish") return "text-error-dim bg-error-dim/10";
  if (axis === "policy_stance" && value === "dovish") return "text-primary bg-primary/10";
  if (axis === "growth_stress" && value === "stressed") return "text-error-dim bg-error-dim/10";
  if (axis === "growth_stress" && value === "watch") return "text-[#facc15] bg-[#facc15]/10";
  return "text-on-surface-variant/60 bg-surface-container-highest";
}

function RegimeStrip({
  rates,
  regimeVec,
  isLoading,
}: {
  rates: (import("@/lib/api").RatesContext & { available?: boolean }) | null;
  regimeVec: import("@/lib/api").RegimeVector | null;
  isLoading: boolean;
}) {
  if (isLoading) return null;

  const hasRates = rates && rates.available !== false && rates.regime && rates.regime !== "Unknown";
  const hasVec = regimeVec && regimeVec.available;

  if (!hasRates && !hasVec) return null;

  const axes = hasVec
    ? (["inflation", "policy_stance", "fx", "growth_stress"] as const)
        .map((k) => ({ key: k, value: regimeVec[k] as string }))
        .filter((a) => a.value && a.value !== "neutral")
    : [];

  if (!hasRates && axes.length === 0) return null;

  return (
    <section className="mb-6">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-on-surface-variant/40 mr-1">
          Macro Regime
        </span>
        {hasRates && (
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider bg-surface-container-low text-on-surface-variant/70 shadow-[inset_0_0_0_1px_rgba(71,70,86,0.25)]">
            {rates.regime}
          </span>
        )}
        {axes.map((a) => (
          <span
            key={a.key}
            className={cn(
              "inline-flex items-center px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider",
              _axisChipClass(a.key, a.value),
            )}
          >
            {_AXIS_LABELS[a.value] ?? a.value.replace(/_/g, " ")}
          </span>
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Regime Playbook — compact panel of past high-quality validated events
// shown when the market is in an elevated stress regime.
// ---------------------------------------------------------------------------

function _pbValidationClass(outcome: PlaybookEntry["validation_outcome"]): string {
  if (outcome === "validated")   return "text-[#6ec6a5]";
  if (outcome === "contradicted") return "text-[#ee7d77]";
  return "text-on-surface-variant/40";
}

function RegimePlaybook({
  regime,
  onAnalyze,
}: {
  regime: string;
  onAnalyze?: (headline: string, opts?: { eventId?: number }) => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: qk.regimePlaybook(regime),
    queryFn: () => api.regimePlaybook(regime, 4),
    staleTime: 300_000,
    enabled: regime !== "Calm" && !!regime,
  });

  if (isLoading) return null;
  if (!data || data.length === 0) return null;

  return (
    <section className="mb-10">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-on-surface-variant/40">
          Regime Playbook
        </span>
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider bg-surface-container-low text-on-surface-variant/70 shadow-[inset_0_0_0_1px_rgba(71,70,86,0.25)]">
          {regime}
        </span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {data.map((entry) => (
          <button
            key={entry.id}
            onClick={() => onAnalyze?.(entry.headline, { eventId: entry.id })}
            className="group text-left bg-surface-container-low rounded-lg px-3 py-2.5 shadow-[inset_0_0_0_1px_rgba(71,70,86,0.2)] hover:shadow-[inset_0_0_0_1px_rgba(147,209,211,0.2)] transition-shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
          >
            {/* date + stage */}
            <div className="flex items-center justify-between gap-2 mb-1">
              <span className="font-mono text-[10px] text-on-surface-variant/50">
                {entry.event_date ?? "—"}
              </span>
              <div className="flex items-center gap-1.5">
                {entry.stage && (
                  <span className="metric-chip">{entry.stage}</span>
                )}
                {entry.persistence && (
                  <span className="metric-chip">{entry.persistence}</span>
                )}
              </div>
            </div>
            {/* headline */}
            <p className="text-[11px] font-semibold leading-snug line-clamp-2 group-hover:text-primary/80 transition-colors mb-1.5">
              {entry.headline}
            </p>
            {/* bottom row: validation + lead ticker */}
            <div className="flex items-center justify-between gap-2">
              <span className={cn(
                "text-[10px] font-medium",
                _pbValidationClass(entry.validation_outcome),
              )}>
                {entry.validation_outcome === "validated"
                  ? `Validated${entry.support_ratio !== null ? ` · ${Math.round(entry.support_ratio * 100)}%` : ""}`
                  : entry.validation_outcome === "contradicted"
                  ? "Contradicted"
                  : "Unresolved"}
              </span>
              {entry.lead_ticker?.symbol && (
                <div className="flex items-center gap-1 font-mono text-[10px]">
                  <span className="text-on-surface/70">{entry.lead_ticker.symbol}</span>
                  {entry.lead_ticker.return_5d !== null && (
                    <span className={cn(
                      "tabular-nums",
                      (entry.lead_ticker.return_5d ?? 0) >= 0
                        ? "text-primary/70" : "text-error-dim/70",
                    )}>
                      {(entry.lead_ticker.return_5d ?? 0) >= 0 ? "+" : ""}
                      {(entry.lead_ticker.return_5d ?? 0).toFixed(1)}%
                    </span>
                  )}
                </div>
              )}
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Track Record — hero achievement block
// ---------------------------------------------------------------------------

/** Compute display values for the track record strip.  Exported for tests. */
export function computeTrackRecordDisplay(data: TrackRecord) {
  const resolved = data.validated + data.contradicted;
  const hitRate = resolved > 0
    ? Math.round((data.validated / resolved) * 100)
    : null;
  const hitTone: "positive" | "neutral" | "warn" =
    hitRate === null ? "neutral" : hitRate >= 60 ? "positive" : hitRate >= 40 ? "neutral" : "warn";
  const avgSupport = data.avg_support_ratio !== null
    ? Math.round(data.avg_support_ratio * 100)
    : null;
  return { resolved, hitRate, hitTone, avgSupport };
}

function TrackRecordStrip({ data, isLoading }: { data?: TrackRecord; isLoading: boolean }) {
  if (isLoading) {
    return (
      <section className="mb-8">
        <Skeleton className="h-20 rounded-xl bg-surface-container-highest" />
      </section>
    );
  }
  if (!data || data.total === 0) return null;

  const { hitRate, hitTone, avgSupport } = computeTrackRecordDisplay(data);

  const hitColor = hitTone === "positive"
    ? "text-primary" : hitTone === "warn" ? "text-error-dim" : "text-on-surface-variant";
  const hitDot = hitTone === "positive"
    ? "bg-primary" : hitTone === "warn" ? "bg-error-dim" : "bg-on-surface-variant/40";

  return (
    <section className="mt-10 mb-8" data-testid="track-record">
      <div className="bg-surface-container-low rounded-xl shadow-[inset_0_0_0_1px_rgba(71,70,86,0.35),0_4px_12px_rgba(0,0,0,0.2)] px-5 py-3 md:px-6">

        {/* Row 1: compact inline metrics — hit rate same weight as peers */}
        <div className="flex items-center gap-5">

          {/* Lead stat: hit rate (or total if no resolved yet) */}
          {hitRate !== null ? (
            <div className="flex items-baseline gap-1.5 shrink-0">
              <span className={cn("w-1.5 h-1.5 rounded-full self-center shrink-0", hitDot)} />
              <span className={cn("text-[18px] font-headline font-extrabold tabular-nums leading-none tracking-tight", hitColor)}>
                {hitRate}%
              </span>
              <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-on-surface-variant/40 self-center">
                Hit Rate
              </span>
            </div>
          ) : (
            <div className="flex items-baseline gap-1.5 shrink-0">
              <span className="text-[18px] font-headline font-extrabold tabular-nums leading-none tracking-tight text-on-surface">
                {data.total}
              </span>
              <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-on-surface-variant/40 self-center">
                Analyzed
              </span>
            </div>
          )}

          {/* Thin divider */}
          <div className="w-px h-9 bg-outline-variant/15 shrink-0" />

          {/* Secondary breakdown — compact inline metrics */}
          <div className="flex items-center gap-3 md:gap-4 overflow-x-auto min-w-0">
            <MetricCard label="Analyzed" value={data.total} />
            <MetricCard label="Validated" value={data.validated} accent="text-primary" />
            <MetricCard label="Contradicted" value={data.contradicted} accent="text-error-dim" />
            <MetricCard label="Unresolved" value={data.unresolved} accent="text-on-surface-variant/40" />
            {avgSupport !== null && (
              <MetricCard label="Avg Support" value={`${avgSupport}%`} />
            )}
          </div>

          {/* Revisit badge — far right */}
          {data.revisit_scored > 0 && (
            <span className="ml-auto shrink-0 text-[9px] font-bold text-primary/40 uppercase tracking-[0.1em] hidden md:block">
              {data.revisit_scored} revisit-scored
            </span>
          )}
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// News freshness chip — pure derivation, exported for tests
// ---------------------------------------------------------------------------

export interface NewsFreshnessState {
  label: string;
  tone: "ok" | "warn" | "error" | "neutral";
}

export function deriveNewsFreshness(meta?: RefreshMeta | null): NewsFreshnessState {
  if (!meta) return { label: "No data", tone: "neutral" };

  if (meta.status === "error")
    return { label: "Feed error", tone: "error" };
  if (meta.status === "throttled")
    return { label: "Throttled", tone: "neutral" };
  if (meta.freshness === "stale")
    return { label: "Stale", tone: "warn" };
  if (meta.status === "degraded" || meta.freshness === "degraded")
    return { label: "Degraded", tone: "warn" };
  if (meta.status === "recent")
    return { label: "Cached", tone: "ok" };

  // status ok + freshness fresh (or missing)
  return { label: "Live", tone: "ok" };
}

const _FRESHNESS_TONE_CLASS: Record<NewsFreshnessState["tone"], string> = {
  ok:      "bg-primary/15 text-primary",
  warn:    "bg-error-dim/15 text-error-dim",
  error:   "bg-error-dim/20 text-error-dim",
  neutral: "bg-surface-container-highest text-on-surface-variant/50",
};

// ---------------------------------------------------------------------------
// Latest Headlines — compact cluster strip with analyze action
// ---------------------------------------------------------------------------

function LatestHeadlinesStrip({
  clusters,
  isLoading,
  onAnalyze,
  refreshMeta,
  failedHeadlines,
}: {
  clusters: NewsCluster[];
  isLoading: boolean;
  onAnalyze?: (headline: string, opts?: { eventId?: number; context?: string }) => void;
  refreshMeta?: RefreshMeta | null;
  failedHeadlines?: Set<string>;
}) {
  if (isLoading) {
    return (
      <section className="mb-10">
        <Skeleton className="h-5 w-40 bg-surface-container-highest mb-4" />
        <div className="space-y-2">
          {[1, 2, 3].map((k) => <Skeleton key={k} className="h-10 rounded-lg bg-surface-container-highest" />)}
        </div>
      </section>
    );
  }
  if (!clusters || clusters.length === 0) return null;

  // Show top 5 non-low-signal clusters — failed headlines stay visible
  // with an inline indicator (not hidden).
  const top = clusters.filter((c) => !c.low_signal).slice(0, 5);
  if (top.length === 0) return null;

  const freshness = deriveNewsFreshness(refreshMeta);

  return (
    <section className="mb-10">
      <div className="flex items-center gap-2 mb-3">
        <h2 className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant/50">
          Latest Headlines
        </h2>
        <span className={cn(
          "inline-flex items-center gap-1 rounded-full px-1.5 py-px text-[8px] font-bold uppercase tracking-widest leading-none",
          _FRESHNESS_TONE_CLASS[freshness.tone],
        )}>
          <span className={cn(
            "h-1 w-1 rounded-full",
            freshness.tone === "ok" && "bg-primary",
            freshness.tone === "warn" && "bg-error-dim",
            freshness.tone === "error" && "bg-error-dim",
            freshness.tone === "neutral" && "bg-on-surface-variant/30",
          )} />
          {freshness.label}
        </span>
      </div>
      <div className="space-y-1.5">
        {top.map((c, i) => {
          const isFailed = failedHeadlines?.has(c.headline);
          return (
            <div
              key={i}
              className={cn(
                "group flex items-center gap-3 rounded-lg bg-surface-container-low px-3 py-2 transition-shadow",
                isFailed
                  ? "shadow-[inset_0_0_0_1px_rgba(187,85,81,0.2)] hover:shadow-[inset_0_0_0_1px_rgba(187,85,81,0.4)]"
                  : "shadow-[inset_0_0_0_1px_rgba(71,70,86,0.2)] hover:shadow-[inset_0_0_0_1px_rgba(71,70,86,0.4)]",
              )}
            >
              <span className={cn(
                "flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[9px] font-bold tabular-nums",
                c.source_count >= 3 ? "bg-primary/15 text-primary" : "bg-surface-container-highest text-on-surface-variant/50",
              )}>
                {c.source_count}
              </span>
              <span className="min-w-0 flex-1 text-[12px] font-medium leading-snug text-on-surface line-clamp-1">
                {c.headline}
              </span>
              {isFailed && (
                <span className="shrink-0 flex items-center gap-1 text-[8px] font-bold text-error-dim/60">
                  <AlertTriangle className="h-2.5 w-2.5" />
                </span>
              )}
              {onAnalyze && (
                <button
                  onClick={() => onAnalyze(c.headline, { context: buildClusterContext(c) })}
                  className={cn(
                    "shrink-0 flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider transition-all",
                    isFailed
                      ? "text-on-surface-variant/50 hover:text-primary hover:bg-primary/10"
                      : "text-on-surface-variant/40 hover:text-primary hover:bg-primary/10 opacity-0 group-hover:opacity-100",
                  )}
                >
                  <FlaskConical className="h-3 w-3" />
                  {isFailed ? "Retry" : "Analyze"}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function MarketOverview({ onAnalyze, failedHeadlines }: {
  onAnalyze?: (headline: string, opts?: { eventId?: number; context?: string }) => void;
  failedHeadlines?: Set<string>;
}) {
  // Single normalized market context fetch — replaces the previous separate
  // /snapshots, /stress, and /movers/today queries.  Stress + benchmarks +
  // today's highlights all come from one request, with consistent freshness.
  const { data: ctx, isLoading: ctxLoading, error: ctxError } = useQuery({
    queryKey: qk.marketContext(),
    queryFn: () => api.marketContext(10),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  // Persistent movers stays on its own endpoint — different selection algorithm
  // than today's highlights, so it cannot share /market-context.
  const { data: persistent, isLoading: persistentLoading, error: persistentError } = useQuery({
    queryKey: qk.moversPersistent(),
    queryFn: () => api.moversPersistent(),
    staleTime: 1_800_000,
  });

  const { data: weekly, isLoading: weeklyLoading, error: weeklyError } = useQuery({
    queryKey: qk.moversWeekly(),
    queryFn: () => api.moversWeekly(),
    staleTime: 1_800_000,
  });

  const { data: trackRecord, isLoading: trackLoading } = useQuery({
    queryKey: qk.trackRecord(),
    queryFn: () => api.trackRecord(),
    staleTime: 300_000,
  });

  const { data: newsData, isLoading: newsLoading } = useQuery({
    queryKey: qk.newsPaginated(30),
    queryFn: () => api.news(30, 0),
    staleTime: 300_000,
  });

  // Distribute the unified context to child components.
  const stress = ctx?.stress ?? null;
  const rates = ctx?.rates ?? null;
  const regimeVec = ctx?.regime_vector ?? null;
  const snapshots = ctx?.snapshots ?? null;
  const uncertaintyConcentration = ctx?.uncertainty_concentration ?? null;
  const todaysHighlights = ctx?.highlights ?? [];

  // Surface a single inline error banner when any of the top-level queries
  // fail.  Without this, a backend that's unreachable on first start would
  // render the page completely blank (every section gracefully hides on
  // empty data) and the user would have no idea something went wrong.
  // Picks the first error so the banner is one line, not three.
  const firstError = ctxError ?? persistentError ?? weeklyError;
  const errorMessage = firstError instanceof Error ? firstError.message : null;

  // True cold-start empty: data loaded successfully on every channel but
  // the archive is empty.  Show a friendly first-run nudge instead of a
  // blank page.  Stress / snapshots can still be empty on a fresh clone,
  // so we gate purely on "all queries finished + no movers anywhere".
  const allLoaded = !ctxLoading && !persistentLoading && !weeklyLoading;
  const isColdStart =
    allLoaded
    && !firstError
    && (!persistent || persistent.length === 0)
    && (!weekly || weekly.length === 0)
    && todaysHighlights.length === 0;

  return (
    // Page-level flow: no nested overflow container, no h-full reliance.
    // The shell scrolls the whole document; this page just stacks its
    // sections.  TodayStrip used to be `position: absolute` inside a
    // fixed-height wrapper — that pattern is gone, the strip is now an
    // inline footer at the natural end of the overview content.
    <div className="space-y-0">
      {/* Inline error banner — only renders when one of the top-level
          queries failed.  Keeps the rest of the page rendering its own
          empty states so partial degradation still works. */}
      {errorMessage && (
        <div
          role="alert"
          className="mb-6 bg-error-container/15 rounded-xl p-4 flex items-start gap-3 shadow-[inset_0_0_0_1px_rgba(187,85,81,0.2)]"
        >
          <AlertTriangle className="h-4 w-4 text-error-dim shrink-0 mt-0.5" />
          <div className="min-w-0">
            <p className="text-[11px] font-bold text-error-dim">Market data unavailable</p>
            <p className="text-[10px] text-on-surface-variant mt-0.5 break-words">{errorMessage}</p>
          </div>
        </div>
      )}

      {/* Cold-start empty state — only when every channel loaded cleanly
          but there is genuinely nothing to show.  A first-run user sees
          a clear nudge instead of a stack of "no X detected" boxes. */}
      {isColdStart && (
        <div className="mb-6 bg-surface-container-low rounded-xl p-6 text-center">
          <p className="text-sm font-headline font-bold text-on-surface/80 mb-1">
            No archive yet
          </p>
          <p className="text-[11px] text-on-surface-variant/70 max-w-md mx-auto leading-relaxed">
            Run an analysis from the Headlines page to start populating Market Overview.
          </p>
        </div>
      )}

      {/* Degraded-context banner — fires when snapshots are stale or provider is down */}
      {ctx && (() => {
        const n = deriveContextDegradedNotice(ctx);
        return n ? (
          <DegradedBanner
            title={n.label}
            detail={n.detail ?? undefined}
            severity={n.severity}
            className="mb-4"
          />
        ) : null;
      })()}

      {/* 1. Uncertainty & Market Instability */}
      <UncertaintySection
        stress={stress}
        isLoading={ctxLoading}
        uncertaintyConcentration={uncertaintyConcentration}
      />

      {/* 1b. Macro Regime — rates regime + regime vector axes */}
      <RegimeStrip rates={rates} regimeVec={regimeVec} isLoading={ctxLoading} />

      {/* 1c. Trending Themes — dominant actions/sectors across recent clusters */}
      <TrendingThemesPanel clusters={newsData?.clusters ?? []} regimeVec={regimeVec} isLoading={newsLoading} />

      {/* 1d. Regime Playbook — past patterns in similar conditions */}
      {stress?.regime && stress.regime !== "Calm" && stress.available !== false && (
        <RegimePlaybook regime={stress.regime} onAnalyze={onAnalyze} />
      )}

      {/* 2. Liquid Benchmark Snapshots — warm cached, hides cleanly when empty */}
      <BenchmarkSnapshotsStrip snapshots={snapshots} isLoading={ctxLoading} />

      {/* 2b. Track Record — thesis outcome summary */}
      <div className="pt-10">
        <TrackRecordStrip data={trackRecord} isLoading={trackLoading} />
      </div>

      {/* 3. Still Moving Markets — hero cards */}
      <StillMovingSection movers={persistent} isLoading={persistentLoading} onAnalyze={onAnalyze} />

      {/* 3. This Week's Moves */}
      {weeklyLoading ? (
        <section className="mb-12">
          <Skeleton className="h-7 w-52 bg-surface-container-highest mb-6" />
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <Skeleton className="h-28 rounded-lg bg-surface-container-highest" />
            <Skeleton className="h-28 rounded-lg bg-surface-container-highest" />
            <Skeleton className="h-28 rounded-lg bg-surface-container-highest" />
          </div>
        </section>
      ) : weekly && weekly.length > 0 ? (
        <section className="mb-12">
          <h2 className="text-xl font-headline font-bold text-white tracking-tight mb-6">This Week's Moves</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {weekly.slice(0, 6).map((m) => (
              <EventIntelligenceCard
                key={m.event_id}
                variant="compact"
                headline={m.headline}
                tickers={m.tickers}
                supportRatio={m.support_ratio}
                anchorDate={_cardAnchorDate(m)}
                asOf={_fmtAsOf(m.last_market_check_at)}
                onAnalyze={() => onAnalyze?.(m.headline, { eventId: m.event_id })}
              />
            ))}
          </div>
        </section>
      ) : null}

      {/* 4. Latest Headlines — compact cluster strip with analyze action */}
      <LatestHeadlinesStrip
        clusters={newsData?.clusters ?? []}
        isLoading={newsLoading}
        onAnalyze={onAnalyze}
        refreshMeta={newsData?.refresh_meta}
        failedHeadlines={failedHeadlines}
      />

      {/* 5. Today — inline footer strip, fed from /market-context highlights */}
      <TodayStrip movers={todaysHighlights} isLoading={ctxLoading} />

      {/* 6. System Health — compact pipeline health panel */}
      <SystemHealthPanel />
    </div>
  );
}
