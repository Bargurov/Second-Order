import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Sparkline } from "@/components/ui/sparkline";
import { Skeleton } from "@/components/ui/skeleton";
import { TickerDetailPanel } from "@/components/ui/ticker-detail-panel";
import { TransmissionChainCompact } from "@/components/ui/transmission-chain";
import { IfPersistsCompact } from "@/components/ui/if-persists";
import { RatesContextCompact } from "@/components/ui/rates-context";
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
// Net direction for left-border color
// ---------------------------------------------------------------------------

function netDirection(tickers: MarketMover["tickers"]): "pos" | "neg" | "flat" {
  let sum = 0;
  for (const t of tickers) {
    if (t.return_5d != null) sum += t.return_5d;
  }
  if (sum > 0.5) return "pos";
  if (sum < -0.5) return "neg";
  return "flat";
}

// ---------------------------------------------------------------------------
// Since-event badge — compact inline return from event date to today
// ---------------------------------------------------------------------------

function SinceEventBadge({ outcome }: { outcome: BacktestOutcome | undefined }) {
  if (!outcome) return null;
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
// MoverCard — redesigned with visual hierarchy + left border color
// ---------------------------------------------------------------------------

const TICKER_VISIBLE_LIMIT = 3;

function MoverCard({ mover, liveMap }: { mover: MarketMover; liveMap: LiveMap | null }) {
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null);
  const [showAllTickers, setShowAllTickers] = useState(false);
  const mechanism = mover.mechanism_summary || "";
  const truncMech = mechanism.length > 140 ? mechanism.slice(0, 137) + "..." : mechanism;
  const dir = netDirection(mover.tickers);

  return (
    <Card className={cn(
      "shrink-0 w-[360px] md:w-auto md:shrink overflow-hidden border-l-[3px]",
      dir === "pos" && "border-l-emerald-500",
      dir === "neg" && "border-l-red-500",
      dir === "flat" && "border-l-border",
    )}>
      {/* Header: headline + agreement badge */}
      <div className="px-4 pt-3 pb-1">
        <div className="flex items-start gap-2">
          <h3 className="text-[15px] font-bold leading-snug line-clamp-2 text-foreground">
            {mover.headline}
          </h3>
          <Badge variant="outline" className="shrink-0 font-num text-[10px]">
            {Math.round(mover.support_ratio * 100)}% agreement
          </Badge>
        </div>
        {truncMech && (
          <p className="text-[11px] leading-relaxed text-muted-foreground mt-1 line-clamp-2">
            {truncMech}
          </p>
        )}
      </div>

      <CardContent className="pt-1.5 pb-3">
        {/* Compact transmission chain */}
        {mover.transmission_chain && mover.transmission_chain.length > 0 && (
          <div className="mb-2">
            <TransmissionChainCompact steps={mover.transmission_chain} />
          </div>
        )}
        {mover.if_persists && (
          <div className="mb-2">
            <IfPersistsCompact data={mover.if_persists} />
          </div>
        )}

        {/* Ticker pills — wrapping flex, collapse after 3 */}
        {(() => {
          const all = mover.tickers;
          const visible = showAllTickers ? all : all.slice(0, TICKER_VISIBLE_LIMIT);
          const hiddenCount = all.length - TICKER_VISIBLE_LIMIT;
          return (
            <div className="flex flex-wrap gap-1.5">
              {visible.map((t) => {
                const up = t.return_5d != null && t.return_5d > 0;
                const down = t.return_5d != null && t.return_5d < 0;
                const selected = expandedSymbol === t.symbol;
                const live = liveMap?.get(`${mover.event_id}:${t.symbol}`);
                const liveVal = live
                  ? (live.return_20d ?? live.return_5d ?? live.return_1d)
                  : null;
                const hasLiveReturn = liveVal != null;
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
                      <Sparkline data={t.spark} width={32} height={12} direction={t.return_5d} />
                    )}
                    {hasLiveReturn && <SinceEventBadge outcome={live} />}
                    {t.decay && t.decay !== "Unknown" && !hasLiveReturn && (
                      <span className={cn(
                        "text-[9px] font-medium px-1 py-px rounded",
                        t.decay === "Accelerating" && "bg-red-100 text-red-700",
                        t.decay === "Holding" && "bg-gray-800/40 text-gray-400",
                        t.decay === "Fading" && "bg-emerald-100 text-emerald-700",
                        t.decay === "Reversed" && "bg-purple-100 text-purple-700",
                      )}>
                        {t.decay}
                      </span>
                    )}
                    <ChevronDown className={cn(
                      "ml-auto h-2.5 w-2.5 shrink-0 text-muted-foreground transition-transform",
                      selected && "rotate-180",
                    )} />
                  </button>
                );
              })}
              {!showAllTickers && hiddenCount > 0 && (
                <button
                  onClick={() => setShowAllTickers(true)}
                  className="flex items-center rounded-lg border border-dashed border-border px-2 py-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
                >
                  +{hiddenCount} more
                </button>
              )}
            </div>
          );
        })()}

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
        <div className="mt-2 flex items-center gap-2 text-[10px] text-muted-foreground flex-wrap">
          <Badge variant="outline">{mover.stage}</Badge>
          <Badge variant="outline">{mover.persistence}</Badge>
          <span className="font-num">{mover.event_date}</span>
          <RatesContextCompact />
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
    staleTime: 120_000,
  });

  const eventIds = useMemo(
    () => (movers ?? []).map((m) => m.event_id),
    [movers],
  );

  const { data: liveResults } = useQuery({
    queryKey: qk.backtestBatch(eventIds),
    queryFn: () => api.backtestBatch(eventIds),
    enabled: eventIds.length > 0,
    staleTime: 300_000,
  });

  const liveMap = useMemo(
    () => (liveResults ? buildLiveMap(liveResults) : null),
    [liveResults],
  );

  if (isLoading) {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Zap className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold">Market Movers</span>
        </div>
        <div className="flex gap-3 overflow-hidden">
          <Skeleton className="h-36 w-[360px] shrink-0 rounded-2xl" />
          <Skeleton className="h-36 w-[360px] shrink-0 rounded-2xl" />
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
        <Zap className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold">Market Movers</span>
        <span className="text-[10px] text-muted-foreground">
          Events with confirmed &gt;1.5% ticker moves
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
