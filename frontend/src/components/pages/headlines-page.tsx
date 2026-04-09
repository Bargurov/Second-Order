import { useState, useRef, useEffect } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  FlaskConical, Newspaper, Search, Loader2, EyeOff,
} from "lucide-react";
import { api, type NewsCluster } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 30;

// ---------------------------------------------------------------------------
// Context builder (for passing to Analysis)
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

// ---------------------------------------------------------------------------
// Headline row
// ---------------------------------------------------------------------------

function HeadlineRow({
  c, onAnalyze, muted,
}: {
  c: NewsCluster;
  onAnalyze?: (headline: string, opts?: { eventId?: number; context?: string }) => void;
  muted?: boolean;
}) {
  return (
    <div
      className={cn(
        "group flex items-center gap-3 rounded-lg border border-border bg-card px-3 py-2 transition-colors hover:border-foreground/15",
        muted && "opacity-50",
      )}
    >
      <span className={cn(
        "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold font-num border",
        c.source_count >= 5 && "border-emerald-500/40 bg-emerald-950/30 text-emerald-400",
        c.source_count >= 3 && c.source_count < 5 && "border-gray-500/40 bg-gray-900/30 text-gray-400",
        c.source_count < 3 && "border-border bg-secondary/60 text-muted-foreground",
      )}>
        {c.source_count}
      </span>
      <span className="min-w-0 flex-1 text-[13px] font-medium leading-snug text-foreground line-clamp-2">
        {c.headline}
      </span>
      {onAnalyze && (
        <Button
          variant="ghost"
          size="sm"
          className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground"
          onClick={() => onAnalyze(c.headline, { context: buildClusterContext(c) })}
        >
          <FlaskConical className="h-3 w-3" />
          <span className="hidden sm:inline ml-1">Analyze</span>
        </Button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Headlines page
// ---------------------------------------------------------------------------

interface HeadlinesPageProps {
  onAnalyze?: (headline: string, opts?: { eventId?: number; context?: string }) => void;
}

export function HeadlinesPage({ onAnalyze }: HeadlinesPageProps) {
  const [search, setSearch] = useState("");
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

  // IntersectionObserver for infinite scroll
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

  // Client-side search filter
  const searchLower = search.toLowerCase().trim();
  const filtered = searchLower
    ? allClusters.filter((c) => c.headline.toLowerCase().includes(searchLower))
    : allClusters;

  const normal = filtered.filter((c) => !c.low_signal);
  const lowSignal = filtered.filter((c) => c.low_signal);
  const loadedCount = allClusters.length;

  return (
    // Page-level scroll: shell scrolls the document; this page is plain
    // flow.  Removed `h-full` + nested `overflow-auto` so the layout no
    // longer creates an inner scroll container.
    <div className="flex flex-col gap-3">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <Newspaper className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-lg font-semibold tracking-[-0.02em] text-foreground">Live Headlines</h2>
        <Badge variant="outline" className="font-num text-[10px]">{totalCount} clusters</Badge>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
        <input
          type="text"
          placeholder="Filter headlines..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full rounded-lg border border-input bg-background pl-9 pr-3 py-2 text-[13px] text-foreground placeholder:text-foreground/40 focus:outline-none focus:ring-1 focus:ring-ring"
        />
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="space-y-1.5">
          {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-10 w-full rounded-lg" />)}
        </div>
      )}

      {/* Headlines grid */}
      {!isLoading && (
        <>
          {/* Low-signal toggle */}
          {lowSignal.length > 0 && (
            <div className="flex justify-end">
              <button
                onClick={() => setShowLowSignal((s) => !s)}
                className="flex items-center gap-1 text-[10px] text-muted-foreground/60 hover:text-muted-foreground transition-colors"
              >
                <EyeOff className="h-3 w-3" />
                {showLowSignal ? "Hide" : "Show"} {lowSignal.length} low-signal
              </button>
            </div>
          )}

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

          {/* Sentinel + bottom status */}
          <div ref={sentinelRef} className="py-3 text-center">
            {isFetchingNextPage && (
              <div className="flex items-center justify-center gap-2 text-[11px] text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" /> Loading more headlines
              </div>
            )}
            {!hasNextPage && loadedCount > 0 && (
              <span className="text-[11px] text-muted-foreground/50">
                Showing {loadedCount} of {totalCount} headlines
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}
