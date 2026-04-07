import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { Sparkline } from "@/components/ui/sparkline";
import { ArrowRight } from "lucide-react";
import { api, type MarketMover } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { pct } from "@/lib/ticker-utils";
import { UncertaintySection } from "@/components/ui/stress-strip";
import { BenchmarkSnapshotsStrip } from "@/components/ui/benchmark-snapshots-strip";

// ---------------------------------------------------------------------------
// "Still Moving Markets" hero card — matches Stitch reference exactly
// bg-surface-container-low rounded-xl p-6 border border-transparent hover:border-outline-variant
// ---------------------------------------------------------------------------

function PersistentCard({ mover, onAnalyze }: {
  mover: MarketMover;
  onAnalyze?: (headline: string) => void;
}) {
  const days = mover.days_since_event ?? 0;
  const agreement = Math.round(mover.support_ratio * 100);
  const mech = mover.mechanism_summary || "";
  const snippet = mech.length > 140 ? mech.slice(0, 137) + "..." : mech;

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
          <div className="text-right">
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
        {/* Ticker pills: bg-surface-container-highest px-3 py-2 rounded-lg */}
        <div className="flex items-center gap-3 overflow-x-auto pb-2">
          {mover.tickers.slice(0, 4).map((t) => (
            <div key={t.symbol} className="bg-surface-container-highest px-3 py-2 rounded-lg flex items-center gap-4 shrink-0">
              <span className="text-xs font-bold text-white tracking-wider">{t.symbol}</span>
              {t.spark && t.spark.length > 2 && (
                <div className="w-12 h-6">
                  <Sparkline data={t.spark} width={48} height={24} direction={t.return_5d} />
                </div>
              )}
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
        {/* Trajectory badge + arrow */}
        <div className="flex justify-between items-center pt-4 border-t border-outline-variant/20">
          <span className="bg-primary-container/20 text-primary text-[10px] font-bold px-2 py-1 rounded-full uppercase tracking-widest">
            {trajectory}
          </span>
          {onAnalyze ? (
            <button
              onClick={() => onAnalyze(mover.headline)}
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
  onAnalyze?: (headline: string) => void;
}) {
  const filtered = movers
    ?.filter((m) => !m.mechanism_summary?.toLowerCase().includes("insufficient evidence"))
    .slice(0, 4);

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
// "This Week's Moves" card — bg-surface-container-highest p-5 rounded-lg
// ---------------------------------------------------------------------------

function WeeklyCard({ mover, onAnalyze }: {
  mover: MarketMover;
  onAnalyze?: (headline: string) => void;
}) {
  const pctVal = Math.round(mover.support_ratio * 100);
  return (
    <div
      className="bg-surface-container-highest p-5 rounded-lg cursor-pointer transition-all shadow-[inset_0_0_0_1px_rgba(71,70,86,0.15)] hover:shadow-[inset_0_0_0_1px_rgba(71,70,86,0.4)]"
      onClick={() => onAnalyze?.(mover.headline)}
    >
      <div className="flex justify-between items-start mb-4">
        <h3 className="text-sm font-bold text-white leading-tight pr-4 line-clamp-2">
          {mover.headline}
        </h3>
        <span className="text-primary font-bold text-xs tnum shrink-0">{pctVal}%</span>
      </div>
      <div className="flex justify-between items-end">
        <div className="flex flex-wrap gap-2">
          {mover.tickers.slice(0, 4).map((t) => (
            <span key={t.symbol} className="text-[10px] font-bold text-on-surface-variant bg-surface-container px-2 py-0.5 rounded">
              {t.symbol}
            </span>
          ))}
        </div>
        <span className="text-[9px] text-on-surface-variant/60 font-medium shrink-0">{mover.event_date}</span>
      </div>
    </div>
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
    <div className="absolute bottom-0 left-0 right-0 h-14 bg-surface-container border-t border-outline-variant/10 z-40 overflow-hidden flex items-center">
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
// Main page
// ---------------------------------------------------------------------------

export function MarketOverview({ onAnalyze }: { onAnalyze?: (headline: string) => void }) {
  // Single normalized market context fetch — replaces the previous separate
  // /snapshots, /stress, and /movers/today queries.  Stress + benchmarks +
  // today's highlights all come from one request, with consistent freshness.
  const { data: ctx, isLoading: ctxLoading } = useQuery({
    queryKey: qk.marketContext(),
    queryFn: () => api.marketContext(10),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  // Persistent movers stays on its own endpoint — different selection algorithm
  // than today's highlights, so it cannot share /market-context.
  const { data: persistent, isLoading: persistentLoading } = useQuery({
    queryKey: qk.moversPersistent(),
    queryFn: () => api.moversPersistent(),
    staleTime: 1_800_000,
  });

  const { data: weekly, isLoading: weeklyLoading } = useQuery({
    queryKey: qk.moversWeekly(),
    queryFn: () => api.moversWeekly(),
    staleTime: 1_800_000,
  });

  // Distribute the unified context to child components.
  const stress = ctx?.stress ?? null;
  const snapshots = ctx?.snapshots ?? null;
  const todaysHighlights = ctx?.highlights ?? [];

  return (
    <div className="relative flex h-full flex-col">
      <div className="flex-1 overflow-y-auto px-0 pb-24">
        {/* 1. Uncertainty & Market Instability */}
        <UncertaintySection stress={stress} isLoading={ctxLoading} />

        {/* 2. Liquid Benchmark Snapshots — warm cached, hides cleanly when empty */}
        <BenchmarkSnapshotsStrip snapshots={snapshots} isLoading={ctxLoading} />

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
                <WeeklyCard key={m.event_id} mover={m} onAnalyze={onAnalyze} />
              ))}
            </div>
          </section>
        ) : null}
      </div>

      {/* 4. Today — fixed bottom strip, fed from /market-context highlights */}
      <TodayStrip movers={todaysHighlights} isLoading={ctxLoading} />
    </div>
  );
}
