import { useState, useRef, useCallback, useEffect } from "react";
import { useQuery, useQueryClient, useInfiniteQuery } from "@tanstack/react-query";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Sparkline } from "@/components/ui/sparkline";
import {
  RefreshCw, FlaskConical, Newspaper, EyeOff,
  Zap, Calendar, Clock, Loader2, TrendingUp, TrendingDown,
} from "lucide-react";
import { api, type NewsCluster, type MarketMover } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { pct } from "@/lib/ticker-utils";
import { StressStrip } from "@/components/ui/stress-strip";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildClusterContext(c: NewsCluster): string {
  const parts: string[] = [];
  if (c.source_count > 1) {
    const names = c.sources.map((s) => s.name).join(", ");
    parts.push(`Sources (${c.source_count}): ${names}`);
  }
  if (c.summary) parts.push(`Summary: ${c.summary}`);
  if (c.agreement) parts.push(`Agreement: ${c.agreement}`);
  if (c.consensus) {
    const con = c.consensus;
    const fields: string[] = [];
    if (con.actors) fields.push(`Actors: ${String(con.actors)}`);
    if (con.action) fields.push(`Action: ${String(con.action)}`);
    if (con.sector) fields.push(`Sector: ${String(con.sector)}`);
    if (con.geography) fields.push(`Geography: ${String(con.geography)}`);
    if (con.uncertainty) fields.push(`Uncertainty: ${String(con.uncertainty)}`);
    if (fields.length > 0) parts.push(fields.join(" | "));
  }
  return parts.join("\n");
}

const PAGE_SIZE = 30;

// ---------------------------------------------------------------------------
// Still Moving Markets — hero section (persistent shocks)
// ---------------------------------------------------------------------------

function PersistentCard({ mover }: { mover: MarketMover }) {
  const mech = mover.mechanism_summary || "";
  const snippet = mech.length > 120 ? mech.slice(0, 117) + "..." : mech;
  const days = mover.days_since_event ?? 0;

  return (
    <Card className="overflow-hidden border-l-[3px] border-l-border">
      <CardContent className="px-4 py-3 space-y-2">
        {/* Top: headline + days badge */}
        <div className="flex items-start gap-2">
          <h3 className="text-[14px] font-bold leading-snug line-clamp-2 text-foreground flex-1">
            {mover.headline}
          </h3>
          <div className="flex flex-col items-end gap-1 shrink-0">
            <Badge variant="outline" className="font-num text-[10px]">
              {Math.round(mover.support_ratio * 100)}% agreement
            </Badge>
            <span className="text-[10px] text-muted-foreground font-num">
              {days}d ago
            </span>
          </div>
        </div>

        {/* Snippet */}
        {snippet && (
          <p className="text-[11px] leading-relaxed text-muted-foreground line-clamp-2">{snippet}</p>
        )}

        {/* Ticker pills with returns + decay */}
        <div className="flex flex-wrap gap-1.5">
          {mover.tickers.slice(0, 3).map((t) => {
            const up = t.return_5d != null && t.return_5d > 0;
            const down = t.return_5d != null && t.return_5d < 0;
            return (
              <div
                key={t.symbol}
                className="flex items-center gap-1.5 rounded-lg border border-border bg-secondary/40 px-2 py-1"
              >
                <span className="font-num text-xs font-semibold">{t.symbol}</span>
                {up && <TrendingUp className="h-3 w-3 val-pos" />}
                {down && <TrendingDown className="h-3 w-3 val-neg" />}
                <span className={cn("font-num text-[11px]", up && "val-pos", down && "val-neg")}>
                  {pct(t.return_5d)}
                </span>
                {t.spark && t.spark.length > 2 && (
                  <Sparkline data={t.spark} width={28} height={10} direction={t.return_5d} />
                )}
                {t.decay && t.decay !== "Unknown" && (
                  <span className={cn(
                    "text-[9px] font-medium px-1 py-px rounded",
                    t.decay === "Accelerating" && "bg-red-900/30 text-red-400",
                    t.decay === "Holding" && "bg-gray-800/40 text-gray-400",
                  )}>
                    {t.decay}
                  </span>
                )}
              </div>
            );
          })}
        </div>

        {/* Event date */}
        <span className="text-[10px] text-muted-foreground/50 font-num">{mover.event_date}</span>
      </CardContent>
    </Card>
  );
}

function StillMovingSection({ movers, isLoading }: { movers: MarketMover[] | undefined; isLoading: boolean }) {
  if (isLoading) {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-bold">Still Moving Markets</span>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <Skeleton className="h-32 rounded-2xl" />
          <Skeleton className="h-32 rounded-2xl" />
        </div>
      </div>
    );
  }
  if (!movers || movers.length === 0) {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4 text-muted-foreground/40" />
          <span className="text-sm font-bold text-muted-foreground/60">Still Moving Markets</span>
        </div>
        <div className="rounded-xl border border-dashed border-border px-4 py-3">
          <span className="text-xs text-muted-foreground">No long-running effects detected right now</span>
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Zap className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm font-bold">Still Moving Markets</span>
        <span className="text-[10px] text-muted-foreground">
          Second-order effects still active after 7+ days
        </span>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {movers.map((m) => (
          <PersistentCard key={m.event_id} mover={m} />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Compact mover list (weekly / today)
// ---------------------------------------------------------------------------

function MoverMiniList({
  title, icon, movers, isLoading,
}: {
  title: string;
  icon: React.ReactNode;
  movers: MarketMover[] | undefined;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">{icon}<span className="text-xs font-semibold">{title}</span></div>
        <div className="flex gap-3 overflow-hidden">
          <Skeleton className="h-16 w-[300px] shrink-0 rounded-xl" />
          <Skeleton className="h-16 w-[300px] shrink-0 rounded-xl" />
        </div>
      </div>
    );
  }
  if (!movers || movers.length === 0) return null;
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-xs font-semibold">{title}</span>
        <span className="text-[10px] text-muted-foreground">{movers.length} event{movers.length !== 1 && "s"}</span>
      </div>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {movers.slice(0, 5).map((m) => (
          <div key={m.event_id} className="shrink-0 w-[300px] rounded-xl border border-border bg-card px-3 py-2 space-y-1">
            <p className="text-[12px] font-semibold leading-snug line-clamp-2 text-foreground">{m.headline}</p>
            <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
              <Badge variant="outline" className="font-num text-[9px]">{Math.round(m.support_ratio * 100)}% agree</Badge>
              <span className="font-num">{m.event_date}</span>
              {m.tickers.length > 0 && (
                <span className="font-num">{m.tickers.map((t) => t.symbol).join(", ")}</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Headline row
// ---------------------------------------------------------------------------

function HeadlineRow({
  c, onAnalyze, muted,
}: {
  c: NewsCluster;
  onAnalyze?: (headline: string, context?: string) => void;
  muted?: boolean;
}) {
  return (
    <div
      className={cn(
        "group flex items-center gap-3 rounded-lg border border-border bg-card px-3 py-2 transition-colors hover:border-foreground/15",
        muted && "opacity-50",
      )}
    >
      <Badge
        variant="outline"
        className={cn(
          "shrink-0 font-num text-[10px] tabular-nums",
          !muted && c.source_count >= 3 && "border-gray-500/40 bg-gray-900/30 text-gray-400",
        )}
      >
        {c.source_count}
      </Badge>
      <span className="min-w-0 flex-1 text-[13px] font-medium leading-snug text-foreground line-clamp-2">
        {c.headline}
      </span>
      {onAnalyze && (
        <Button
          variant="ghost"
          size="sm"
          className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground"
          onClick={() => onAnalyze(c.headline, buildClusterContext(c))}
        >
          <FlaskConical className="h-3 w-3" />
          <span className="hidden sm:inline ml-1">Analyze</span>
        </Button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Paginated headlines with infinite scroll
// ---------------------------------------------------------------------------

function PaginatedHeadlines({ onAnalyze }: { onAnalyze?: (headline: string, context?: string) => void }) {
  const [showLowSignal, setShowLowSignal] = useState(false);
  const sentinelRef = useRef<HTMLDivElement>(null);

  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } = useInfiniteQuery({
    queryKey: qk.newsPaginated(PAGE_SIZE),
    queryFn: ({ pageParam = 0 }) => api.news(PAGE_SIZE, pageParam as number),
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((n, p) => n + p.clusters.length, 0);
      if (loaded >= lastPage.total_count) return undefined;
      return loaded;
    },
    initialPageParam: 0,
    staleTime: 300_000,
  });

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => { if (entries[0].isIntersecting && hasNextPage && !isFetchingNextPage) fetchNextPage(); },
      { rootMargin: "200px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const allClusters = data?.pages.flatMap((p) => p.clusters) ?? [];
  const totalCount = data?.pages[0]?.total_count ?? 0;
  const normal = allClusters.filter((c) => !c.low_signal);
  const lowSignal = allClusters.filter((c) => c.low_signal);

  if (isLoading) {
    return (
      <div className="space-y-1.5">
        {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-10 w-full rounded-lg" />)}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Newspaper className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold">Live Headlines</span>
        <span className="text-[10px] text-muted-foreground">
          {normal.length} of {totalCount} cluster{totalCount !== 1 && "s"}
        </span>
        {lowSignal.length > 0 && (
          <button
            onClick={() => setShowLowSignal((s) => !s)}
            className="ml-auto flex items-center gap-1 text-[10px] text-muted-foreground/60 hover:text-muted-foreground transition-colors"
          >
            <EyeOff className="h-3 w-3" />
            {showLowSignal ? "Hide" : "Show"} {lowSignal.length} low-signal
          </button>
        )}
      </div>
      <div className="fade-in grid gap-1.5 xl:grid-cols-2">
        {normal.map((c) => <HeadlineRow key={c.headline} c={c} onAnalyze={onAnalyze} />)}
      </div>
      {showLowSignal && lowSignal.length > 0 && (
        <div className="space-y-1.5 pt-1">
          <span className="text-[10px] text-muted-foreground/50 uppercase tracking-widest">Low signal</span>
          <div className="grid gap-1.5 xl:grid-cols-2">
            {lowSignal.map((c) => <HeadlineRow key={c.headline} c={c} onAnalyze={onAnalyze} muted />)}
          </div>
        </div>
      )}
      <div ref={sentinelRef} className="py-2 text-center">
        {isFetchingNextPage && (
          <div className="flex items-center justify-center gap-2 text-[11px] text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" /> Loading more headlines
          </div>
        )}
        {!hasNextPage && allClusters.length > 0 && (
          <span className="text-[11px] text-muted-foreground/50">No more headlines</span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Feed page
// ---------------------------------------------------------------------------

interface NewsInboxProps {
  onAnalyze?: (headline: string, context?: string) => void;
}

export function NewsInbox({ onAnalyze }: NewsInboxProps) {
  const queryClient = useQueryClient();

  const { data: initialData, isLoading: initialLoading, error } = useQuery({
    queryKey: qk.newsPaginated(1),
    queryFn: () => api.news(1, 0),
    staleTime: 300_000,
  });

  const { data: persistentMovers, isLoading: persistentLoading } = useQuery({
    queryKey: qk.moversPersistent(),
    queryFn: () => api.moversPersistent(),
    staleTime: 1_800_000,
  });

  const { data: weeklyMovers, isLoading: weeklyLoading } = useQuery({
    queryKey: qk.moversWeekly(),
    queryFn: () => api.moversWeekly(),
    staleTime: 1_800_000,
  });

  const { data: todayMovers, isLoading: todayLoading } = useQuery({
    queryKey: qk.moversToday(),
    queryFn: () => api.moversToday(),
    staleTime: 300_000,
  });

  const refresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["news"] });
    queryClient.invalidateQueries({ queryKey: ["movers"] });
  }, [queryClient]);

  const hasClusters = (initialData?.total_count ?? 0) > 0;
  const loading = initialLoading;
  const errMsg = error instanceof Error ? error.message : error ? String(error) : null;

  return (
    <div className="flex h-full flex-col gap-3">
      {/* Top bar */}
      <div className="soft-panel flex shrink-0 flex-col gap-3 rounded-[22px] px-4 py-4 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0 space-y-1">
          <p className="section-kicker">Coverage</p>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate text-lg font-semibold tracking-[-0.02em] text-foreground">Feed</h2>
            {initialData && (
              <span className="metric-chip">
                <span className="font-num">{initialData.total_headlines}</span> headline{initialData.total_headlines !== 1 && "s"}
              </span>
            )}
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={refresh} disabled={loading} className="shrink-0">
          <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
          <span className="hidden sm:inline">Refresh</span>
        </Button>
      </div>

      {errMsg && (
        <Card className="shrink-0 border-destructive/30 bg-destructive/5">
          <CardContent className="flex items-start gap-3 py-4 text-destructive">
            <Newspaper className="h-4 w-4 mt-0.5" />
            <div className="space-y-1">
              <p className="text-[12px] font-medium">Inbox unavailable</p>
              <p className="text-2xs leading-5 text-destructive/90">{errMsg}</p>
            </div>
          </CardContent>
        </Card>
      )}

      {loading && (
        <div className="min-h-0 flex-1 space-y-3">
          <Skeleton className="h-20 w-full rounded-2xl" />
          <Skeleton className="h-32 w-full rounded-2xl" />
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-10 w-full rounded-lg" />)}
        </div>
      )}

      {!loading && !errMsg && !hasClusters && (
        <Card className="empty-surface flex flex-1 items-center justify-center">
          <CardContent className="flex max-w-md flex-col items-center gap-3 py-12 text-center text-muted-foreground">
            <Newspaper className="h-6 w-6 opacity-70" />
            <p className="text-sm font-medium text-foreground">No headlines available</p>
            <p className="text-[12px] leading-5 text-foreground/72">Start the API or check feed connectivity.</p>
          </CardContent>
        </Card>
      )}

      {!loading && hasClusters && (
        <ScrollArea className="min-h-0 flex-1">
          <div className="pr-2 space-y-1">
            {/* 1. Uncertainty & Market Instability */}
            <StressStrip />
            <Separator className="my-3" />

            {/* 2. Still Moving Markets — hero */}
            <StillMovingSection movers={persistentMovers} isLoading={persistentLoading} />
            <Separator className="my-3" />

            {/* 3. This Week's Moves */}
            <MoverMiniList
              title="This Week's Moves"
              icon={<Calendar className="h-3.5 w-3.5 text-muted-foreground" />}
              movers={weeklyMovers}
              isLoading={weeklyLoading}
            />
            <Separator className="my-3" />

            {/* 4. Today */}
            <MoverMiniList
              title="Today"
              icon={<Clock className="h-3.5 w-3.5 text-muted-foreground" />}
              movers={todayMovers}
              isLoading={todayLoading}
            />
            <Separator className="my-3" />

            {/* 5. Live Headlines */}
            <PaginatedHeadlines onAnalyze={onAnalyze} />
          </div>
        </ScrollArea>
      )}
    </div>
  );
}
