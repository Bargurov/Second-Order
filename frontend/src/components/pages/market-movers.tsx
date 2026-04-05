import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Sparkline } from "@/components/ui/sparkline";
import { Skeleton } from "@/components/ui/skeleton";
import { TickerDetailPanel } from "@/components/ui/ticker-detail-panel";
import { api, type MarketMover, type BacktestResult, type BacktestOutcome } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { pct } from "@/lib/ticker-utils";
import { TrendingUp, TrendingDown, Zap, ChevronDown, Activity } from "lucide-react";

// ---------------------------------------------------------------------------
// Live "since event" lookup — maps event_id:symbol → BacktestOutcome
// ---------------------------------------------------------------------------

type LiveMap = Map<string, BacktestOutcome>;

function buildLiveMap(results: BacktestResult[]): LiveMap {
  const m = new Map<string, BacktestOutcome>();
  for (const r of results) {
    for (const o of r.outcomes) {
      m.set(`${r.event_id}:${o.symbol}`, o);
    }
  }
  return m;
}

// ---------------------------------------------------------------------------
// Since-event badge — compact inline return from event date to today
// ---------------------------------------------------------------------------

function SinceEventBadge({ outcome }: { outcome: BacktestOutcome | undefined }) {
  if (!outcome) return null;
  // Use the longest available window: prefer 20d, then 5d, then 1d
  const val = outcome.return_20d ?? outcome.return_5d ?? outcome.return_1d;
  if (val == null) return null;
  const up = val > 0;
  const down = val < 0;
  return (
    <span className={cn(
      "font-num text-[9px] font-medium px-1 py-px rounded border",
      up && "border-emerald-200 bg-emerald-50 text-emerald-700",
      down && "border-red-200 bg-red-50 text-red-700",
      !up && !down && "border-border bg-secondary/40 text-muted-foreground",
    )}>
      now {pct(val)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// MoverCard
// ---------------------------------------------------------------------------

function MoverCard({ mover, liveMap }: { mover: MarketMover; liveMap: LiveMap | null }) {
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null);
  const mechanism = mover.mechanism_summary || "";
  const truncMech = mechanism.length > 120 ? mechanism.slice(0, 117) + "..." : mechanism;

  return (
    <Card className="shrink-0 w-[340px] md:w-auto md:shrink">
      <CardHeader className="pb-0">
        <div className="flex items-start gap-2">
          <CardTitle className="text-[13px] leading-snug line-clamp-2">
            {mover.headline}
          </CardTitle>
          <Badge variant="outline" className="shrink-0 font-num">
            {Math.round(mover.support_ratio * 100)}%
          </Badge>
        </div>
        {truncMech && (
          <p className="text-[11px] leading-relaxed text-muted-foreground mt-1 line-clamp-2">
            {truncMech}
          </p>
        )}
      </CardHeader>
      <CardContent className="pt-2">
        {/* Ticker chips */}
        <div className="flex flex-wrap gap-1.5">
          {mover.tickers.map((t) => {
            const up = t.return_5d != null && t.return_5d > 0;
            const down = t.return_5d != null && t.return_5d < 0;
            const selected = expandedSymbol === t.symbol;
            const live = liveMap?.get(`${mover.event_id}:${t.symbol}`);
            return (
              <button
                key={t.symbol}
                onClick={() => setExpandedSymbol((s) => (s === t.symbol ? null : t.symbol))}
                className={cn(
                  "flex items-center gap-1.5 rounded-lg border px-2 py-1 text-left transition-colors",
                  "border-border bg-secondary/40 hover:border-border/80",
                  selected && "border-sidebar-primary/50 bg-sidebar-primary/5",
                )}
              >
                <span className="font-num text-xs font-semibold">{t.symbol}</span>
                {up && <TrendingUp className="h-3 w-3 val-pos" />}
                {down && <TrendingDown className="h-3 w-3 val-neg" />}
                <span className={cn(
                  "font-num text-[11px]",
                  up && "val-pos",
                  down && "val-neg",
                )}>
                  {pct(t.return_5d)}
                </span>
                {t.spark && t.spark.length > 2 && (
                  <Sparkline
                    data={t.spark}
                    width={32}
                    height={12}
                    direction={t.return_5d}
                  />
                )}
                <SinceEventBadge outcome={live} />
                {t.decay && t.decay !== "Unknown" && !live && (
                  <span className={cn(
                    "text-[9px] font-medium px-1 py-px rounded",
                    t.decay === "Accelerating" && "bg-red-100 text-red-700",
                    t.decay === "Holding" && "bg-amber-100 text-amber-700",
                    t.decay === "Fading" && "bg-emerald-100 text-emerald-700",
                    t.decay === "Reversed" && "bg-purple-100 text-purple-700",
                  )}>
                    {t.decay}
                  </span>
                )}
                <ChevronDown className={cn(
                  "h-2.5 w-2.5 shrink-0 text-muted-foreground transition-transform",
                  selected && "rotate-180",
                )} />
              </button>
            );
          })}
        </div>

        {/* Expanded ticker detail */}
        {expandedSymbol && (() => {
          const t = mover.tickers.find((x) => x.symbol === expandedSymbol);
          if (!t) return null;
          return (
            <div className="mt-2">
              <TickerDetailPanel
                ticker={t}
                eventDate={mover.event_date}
                moverExtra={{ decay: t.decay, decay_evidence: t.decay_evidence }}
              />
            </div>
          );
        })()}

        {/* Meta */}
        <div className="mt-2 flex items-center gap-2 text-[10px] text-muted-foreground">
          <Badge variant="outline">{mover.stage}</Badge>
          <Badge variant="outline">{mover.persistence}</Badge>
          <span className="font-num">{mover.event_date}</span>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// MarketMovers (parent)
// ---------------------------------------------------------------------------

export function MarketMovers() {
  const { data: movers, isLoading } = useQuery({
    queryKey: qk.marketMovers(),
    queryFn: () => api.marketMovers(),
    staleTime: 120_000, // 2 min
  });

  // Derive event IDs for the live backtest batch query.
  const eventIds = useMemo(
    () => (movers ?? []).map((m) => m.event_id),
    [movers],
  );

  // Fire a batch backtest to get fresh since-event returns.
  // Depends on movers being loaded and having at least one entry.
  const { data: liveResults } = useQuery({
    queryKey: qk.backtestBatch(eventIds),
    queryFn: () => api.backtestBatch(eventIds),
    enabled: eventIds.length > 0,
    staleTime: 300_000, // 5 min — live data but not hyper-real-time
  });

  const liveMap = useMemo(
    () => (liveResults ? buildLiveMap(liveResults) : null),
    [liveResults],
  );

  // Hide entirely when nothing qualifies or loading
  if (isLoading) {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Zap className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold">Market Movers</span>
        </div>
        <div className="flex gap-3 overflow-hidden">
          <Skeleton className="h-32 w-[340px] shrink-0 rounded-2xl" />
          <Skeleton className="h-32 w-[340px] shrink-0 rounded-2xl" />
        </div>
      </div>
    );
  }

  if (!movers || movers.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-dashed border-border px-4 py-3">
        <Zap className="h-3.5 w-3.5 text-muted-foreground/50" />
        <span className="text-xs text-muted-foreground">No confirmed market movers right now</span>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Zap className="h-3.5 w-3.5 text-amber-500" />
        <span className="text-xs font-semibold">Market Movers</span>
        <span className="text-[10px] text-muted-foreground">
          Events with confirmed &gt;3% ticker moves
        </span>
        {liveResults && (
          <span className="flex items-center gap-0.5 text-[9px] text-muted-foreground/60 ml-auto">
            <Activity className="h-2.5 w-2.5" />
            live
          </span>
        )}
      </div>
      <div className="flex gap-3 overflow-x-auto pb-1 md:grid md:grid-cols-2 lg:grid-cols-3 md:overflow-visible">
        {movers.map((m) => (
          <MoverCard key={m.event_id} mover={m} liveMap={liveMap} />
        ))}
      </div>
    </div>
  );
}
