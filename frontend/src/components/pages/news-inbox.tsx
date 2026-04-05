import { useState, useRef, useCallback, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { RefreshCw, FlaskConical, Newspaper, ArrowUp } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type NewsCluster, type NewsResponse } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { MarketMovers } from "@/components/pages/market-movers";
import { StressStrip } from "@/components/ui/stress-strip";

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

const POLL_MS = 5 * 60 * 1000;

function ClusterSkeleton() {
  return (
    <div className="rounded-xl border border-border bg-card px-3 py-3 space-y-2">
      <Skeleton className="h-3.5 w-4/5" />
      <Skeleton className="h-3 w-2/5" />
      <div className="flex gap-1.5 pt-0.5">
        <Skeleton className="h-4 w-14 rounded" />
        <Skeleton className="h-3 w-16" />
      </div>
    </div>
  );
}

function headlineSet(clusters: NewsCluster[]): Set<string> {
  return new Set(clusters.map((c) => c.headline));
}

interface NewsInboxProps {
  onAnalyze?: (headline: string, context?: string) => void;
}

export function NewsInbox({ onAnalyze }: NewsInboxProps) {
  const queryClient = useQueryClient();

  // Displayed clusters — separate from the query data so we can diff for "new stories"
  const [displayed, setDisplayed] = useState<NewsCluster[]>([]);
  const [displayedTotal, setDisplayedTotal] = useState(0);
  const displayedRef = useRef<Set<string>>(new Set());

  const [pendingData, setPendingData] = useState<NewsResponse | null>(null);
  const [newCount, setNewCount] = useState(0);

  const { data: queryData, isLoading, error, isFetching } = useQuery({
    queryKey: qk.news(),
    queryFn: () => api.news(),
    refetchInterval: POLL_MS,
    refetchIntervalInBackground: false,
  });

  // Sync query data → displayed state
  const dataUpdatedAt = queryData ? JSON.stringify(queryData.clusters.length) : "";
  useEffect(() => {
    if (!queryData) return;
    if (displayed.length === 0) {
      // Initial load
      setDisplayed(queryData.clusters);
      setDisplayedTotal(queryData.total_headlines);
      displayedRef.current = headlineSet(queryData.clusters);
    } else {
      // Background refetch — diff for new stories
      const incoming = headlineSet(queryData.clusters);
      let count = 0;
      for (const h of incoming) {
        if (!displayedRef.current.has(h)) count++;
      }
      if (count > 0) {
        setPendingData(queryData);
        setNewCount(count);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataUpdatedAt]);

  const applyPending = useCallback(() => {
    if (!pendingData) return;
    setDisplayed(pendingData.clusters);
    setDisplayedTotal(pendingData.total_headlines);
    displayedRef.current = headlineSet(pendingData.clusters);
    setPendingData(null);
    setNewCount(0);
  }, [pendingData]);

  const refresh = useCallback(() => {
    setPendingData(null);
    setNewCount(0);
    // Force refetch — onSuccess will update displayed since we clear it first
    setDisplayed([]);
    queryClient.invalidateQueries({ queryKey: qk.news() });
  }, [queryClient]);

  const loading = isLoading || (isFetching && displayed.length === 0);
  const errMsg = error instanceof Error ? error.message : error ? String(error) : null;

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="soft-panel flex shrink-0 flex-col gap-3 rounded-[22px] px-4 py-4 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0 space-y-1">
          <p className="section-kicker">Coverage</p>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate text-lg font-semibold tracking-[-0.02em] text-foreground">Feed</h2>
            <span className="metric-chip">
              <span className="font-num">{displayedTotal}</span>
              headline{displayedTotal !== 1 && "s"}
            </span>
          </div>
          <p className="max-w-3xl text-[12px] leading-5 text-foreground/78">
            Curated policy, macro, energy, trade, and geopolitical coverage merged with your local inbox and clustered into review candidates.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="hidden rounded-full border border-border bg-secondary px-2.5 py-1 text-[11px] font-medium text-foreground/80 md:inline-flex">
            {loading ? "Refreshing feeds" : "Polling every 5 minutes"}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={refresh}
            disabled={loading}
            className="shrink-0 disabled:border-border disabled:bg-secondary disabled:text-foreground/50"
          >
            <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
            <span className="hidden sm:inline">Refresh inbox</span>
          </Button>
        </div>
      </div>

      {newCount > 0 && (
        <button
          onClick={applyPending}
          className="fade-in flex shrink-0 items-center justify-center gap-1.5 rounded-[16px] border border-sidebar-primary/25 bg-card px-3 py-2 text-2xs font-semibold text-sidebar-primary shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-colors hover:bg-sidebar-primary/5"
        >
          <ArrowUp className="h-3 w-3" />
          View <span className="font-num">{newCount}</span> new stor{newCount === 1 ? "y" : "ies"}
        </button>
      )}

      {errMsg && (
        <Card className="shrink-0 border-destructive/30 bg-destructive/5">
          <CardContent className="flex items-start gap-3 py-4 text-destructive">
            <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white">
              <Newspaper className="h-4 w-4" />
            </div>
            <div className="space-y-1">
              <p className="text-[12px] font-medium">Inbox unavailable</p>
              <p className="text-2xs leading-5 text-destructive/90">{errMsg}</p>
            </div>
          </CardContent>
        </Card>
      )}

      {loading && displayed.length === 0 && (
        <div className="min-h-0 flex-1 space-y-1.5">
          {Array.from({ length: 8 }).map((_, i) => (
            <ClusterSkeleton key={i} />
          ))}
        </div>
      )}

      {!loading && !errMsg && displayed.length === 0 && (
        <Card className="empty-surface flex flex-1 items-center justify-center">
          <CardContent className="flex max-w-md flex-col items-center gap-3 py-12 text-center text-muted-foreground">
            <div className="flex h-14 w-14 items-center justify-center rounded-full border border-border bg-white">
              <Newspaper className="h-6 w-6 opacity-70" />
            </div>
            <div className="space-y-1.5">
              <p className="text-sm font-medium text-foreground">No headlines available</p>
              <p className="text-[12px] leading-5 text-foreground/72">
                Start the API, check feed connectivity, or add entries to the local inbox before refreshing.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {displayed.length > 0 && (
        <ScrollArea className="min-h-0 flex-1">
          <div className="pr-2 space-y-5">
          {/* Stress regime */}
          <StressStrip />

          {/* Market Movers section */}
          <MarketMovers />

          {/* Headline feed section */}
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Newspaper className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs font-semibold">Headlines</span>
              <span className="text-[10px] text-muted-foreground">
                Clustered from {displayed.length} source{displayed.length !== 1 && "s"}
              </span>
            </div>
            <div className="fade-in grid gap-2 xl:grid-cols-2">
            {displayed.map((c) => (
              <Card
                key={c.headline}
                className="group overflow-hidden border-border bg-card transition-colors hover:border-foreground/15 hover:bg-card"
              >
                <CardHeader className="gap-3 border-b border-border bg-secondary/35 px-4 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <CardTitle className="text-[14px] leading-6 font-semibold text-foreground">
                      {c.headline}
                    </CardTitle>
                    {onAnalyze && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="shrink-0 text-foreground/85 hover:text-foreground"
                        onClick={() => onAnalyze(c.headline, buildClusterContext(c))}
                      >
                        <FlaskConical className="h-3 w-3" />
                        <span className="hidden sm:inline">Open analysis</span>
                      </Button>
                    )}
                  </div>
                </CardHeader>
                <CardContent className="flex items-center justify-between gap-3 py-3">
                  <p className="text-[12px] leading-5 text-foreground/76">
                    Reported by <span className="font-num">{c.source_count}</span> source{c.source_count !== 1 && "s"}. Consolidated for quick review so overlapping coverage becomes one event candidate.
                  </p>
                  {onAnalyze && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="shrink-0 md:hidden"
                      onClick={() => onAnalyze(c.headline, buildClusterContext(c))}
                    >
                      Analyze
                    </Button>
                  )}
                </CardContent>
              </Card>
            ))}
            </div>
          </div>
          </div>
        </ScrollArea>
      )}
    </div>
  );
}
