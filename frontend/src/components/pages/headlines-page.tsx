import { useState, useRef, useEffect, useCallback } from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  FlaskConical, Newspaper, Search, Loader2, EyeOff, RefreshCw, AlertTriangle, RotateCw, CalendarClock, Scale, TrendingUp,
} from "lucide-react";
import { api, type NewsCluster, type NewsResponse, type RefreshMeta, type MacroRelease, type PolicyItem, type NewsTrend } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { buildClusterContext } from "@/lib/cluster-context";

const PAGE_SIZE = 30;

/**
 * Pure pagination helper — extracted so the contract is unit-testable.
 *
 * Returns the offset for the next page, or `undefined` when all pages
 * are loaded.  Guards against:
 *   - `p.clusters` missing (malformed page) → counts as 0
 *   - `lastPage.total_count` missing → 0, terminates the query
 *   - pages array containing undefined entries
 */
export function _getNextPageParam(
  lastPage: NewsResponse | undefined,
  allPages: Array<NewsResponse | undefined>,
): number | undefined {
  const loaded = allPages.reduce(
    (n, p) => n + (p?.clusters?.length ?? 0),
    0,
  );
  const total = lastPage?.total_count ?? 0;
  if (total === 0 || loaded >= total) return undefined;
  return loaded;
}

// ---------------------------------------------------------------------------
// Macro calendar strip
// ---------------------------------------------------------------------------

const _MACRO_LABELS: Record<string, string> = {
  Unemployment: "U-Rate",
};

function _relativeLabel(days: number): string {
  if (days === 0) return "Today";
  if (days === 1) return "Tomorrow";
  if (days > 1) return `in ${days}d`;
  if (days === -1) return "Yesterday";
  return `${Math.abs(days)}d ago`;
}

function MacroReleaseChip({ r }: { r: MacroRelease }) {
  const upcoming = r.status === "upcoming" || r.status === "today";
  const label = _MACRO_LABELS[r.name] ?? r.name;

  return (
    <div className={cn(
      "flex items-center gap-2 rounded px-2.5 py-1.5 shrink-0 border",
      upcoming
        ? "bg-[#242533] border-[#93d1d3]/20"
        : "bg-[#13131a] border-border/20 opacity-55",
    )}>
      <span className={cn(
        "h-1.5 w-1.5 rounded-full shrink-0",
        r.status === "today" ? "bg-[#93d1d3]"
          : upcoming ? "bg-[#93d1d3]/50"
          : "bg-muted-foreground/30",
      )} />
      <span className="text-[11px] font-semibold text-foreground/80 tracking-tight">{label}</span>
      <span className="text-[10px] text-muted-foreground/55">{r.period}</span>
      <span className={cn(
        "text-[10px] font-num shrink-0 tabular-nums",
        r.status === "today" ? "text-[#93d1d3]"
          : upcoming ? "text-[#93d1d3]/65"
          : "text-muted-foreground/45",
      )}>
        {_relativeLabel(r.days_until)}
      </span>
    </div>
  );
}

function MacroCalendarStrip({ releases }: { releases: MacroRelease[] }) {
  // Show today + upcoming + recent; omit past (> 2 days ago)
  const visible = releases.filter((r) => r.status !== "past");
  if (visible.length === 0) return null;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground/50 uppercase tracking-widest">
        <CalendarClock className="h-3 w-3" />
        <span>Macro Calendar</span>
      </div>
      <div className="flex gap-1.5 overflow-x-auto pb-0.5 scrollbar-none">
        {visible.map((r) => (
          <MacroReleaseChip key={`${r.name}-${r.release_date}`} r={r} />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Policy tracker strip
// ---------------------------------------------------------------------------

const _POLICY_TYPE_LABEL: Record<string, string> = {
  tariff:          "Tariff",
  sanction:        "Sanction",
  regulation:      "Rule",
  executive_order: "EO",
  rate_decision:   "Rate",
};

const _POLICY_TYPE_COLOR: Record<string, string> = {
  tariff:          "text-[#ee7d77]",
  sanction:        "text-[#ee7d77]",
  regulation:      "text-muted-foreground/60",
  executive_order: "text-[#facc15]/80",
  rate_decision:   "text-[#93d1d3]",
};

function _revisitLabel(days: number): string {
  if (days > 1) return `revisit in ${days}d`;
  if (days === 1) return "revisit tomorrow";
  if (days === 0) return "revisit today";
  return `revisit ${Math.abs(days)}d ago`;
}

function PolicyItemChip({ item }: { item: PolicyItem }) {
  const isAnnounced  = item.status === "announced";
  const isPreEff     = item.status === "pre_effective";
  const isRevisitDue = item.status === "revisit_due";

  const typeLabel = _POLICY_TYPE_LABEL[item.policy_type] ?? item.policy_type;
  const typeColor = _POLICY_TYPE_COLOR[item.policy_type] ?? "text-muted-foreground/60";

  const timingLabel = (isAnnounced || isPreEff)
    ? item.days_until === 1 ? "Tomorrow"
      : item.days_until === 0 ? "Today"
      : `in ${item.days_until}d`
    : _revisitLabel(item.days_until_revisit);

  return (
    <div
      title={item.description}
      className={cn(
        "flex items-center gap-2 rounded px-2.5 py-1.5 shrink-0 border",
        isRevisitDue ? "bg-[#242533] border-[#ee7d77]/25"
          : isPreEff ? "bg-[#242533] border-[#facc15]/25"
          : isAnnounced ? "bg-[#13131a] border-border/15 opacity-75"
          : "bg-[#13131a] border-border/20 opacity-65",
      )}
    >
      <span className={cn(
        "h-1.5 w-1.5 rounded-full shrink-0",
        isRevisitDue ? "bg-[#ee7d77]"
          : isPreEff  ? "bg-[#facc15]"
          : isAnnounced ? "bg-[#93d1d3]/30"
          : "bg-muted-foreground/25",
      )} />
      <span className={cn("text-[9px] font-bold uppercase tracking-wider shrink-0", typeColor)}>
        {typeLabel}
      </span>
      <span className="text-[9px] font-bold text-muted-foreground/45 shrink-0 uppercase tracking-wide">
        {item.jurisdiction}
      </span>
      <span className="text-[11px] font-semibold text-foreground/80 max-w-[160px] truncate">
        {item.name}
      </span>
      <span className={cn(
        "text-[10px] font-num shrink-0 tabular-nums",
        isRevisitDue ? "text-[#ee7d77]/80"
          : isPreEff  ? "text-[#facc15]/80"
          : "text-muted-foreground/40",
      )}>
        {timingLabel}
      </span>
    </div>
  );
}

function PolicyTrackerStrip({ items }: { items: PolicyItem[] }) {
  const visible = items.filter((i) => i.status !== "past");
  if (visible.length === 0) return null;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground/50 uppercase tracking-widest">
        <Scale className="h-3 w-3" />
        <span>Policy Tracker</span>
      </div>
      <div className="flex gap-1.5 overflow-x-auto pb-0.5 scrollbar-none">
        {visible.map((item) => (
          <PolicyItemChip key={`${item.policy_type}-${item.effective_date}-${item.name}`} item={item} />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Trending themes strip
// ---------------------------------------------------------------------------

function _trendSearchTerm(headline: string): string {
  return headline.split(/\s+/).slice(0, 4).join(" ");
}

function TrendingThemesStrip({
  trends,
  onSelect,
}: {
  trends: NewsTrend[];
  onSelect: (term: string) => void;
}) {
  if (trends.length === 0) return null;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground/50 uppercase tracking-widest">
        <TrendingUp className="h-3 w-3" />
        <span>Trending Themes</span>
      </div>
      <div className="flex gap-1.5 overflow-x-auto pb-0.5 scrollbar-none">
        {trends.map((t) => (
          <button
            key={t.headline}
            onClick={() => onSelect(_trendSearchTerm(t.headline))}
            title={t.headline}
            className={cn(
              "flex items-center gap-1.5 rounded px-2.5 py-1.5 shrink-0 border",
              "bg-[#242533] border-[#93d1d3]/15 hover:border-[#93d1d3]/35 transition-colors",
            )}
          >
            <span className="h-1.5 w-1.5 rounded-full shrink-0 bg-[#93d1d3]/50" />
            <span className="text-[11px] font-semibold text-foreground/80 max-w-[200px] truncate">
              {t.headline}
            </span>
            <span className="text-[10px] font-num tabular-nums text-[#93d1d3]/60 shrink-0">
              {t.source_count}s
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Headline row
// ---------------------------------------------------------------------------

/**
 * Derive the row action state from the headline's failure status.
 *
 * Exported for tests — pure function, no React dependencies.
 */
export type HeadlineRowState = "normal" | "failed";

export function deriveRowState(
  headline: string,
  failedHeadlines?: Set<string>,
): HeadlineRowState {
  if (failedHeadlines?.has(headline)) return "failed";
  return "normal";
}

function HeadlineRow({
  c, onAnalyze, muted, failed,
}: {
  c: NewsCluster;
  onAnalyze?: (headline: string, opts?: { eventId?: number; context?: string }) => void;
  muted?: boolean;
  failed?: boolean;
}) {
  return (
    <div
      className={cn(
        "group flex items-center gap-3 rounded-lg border bg-card px-3 py-2 transition-colors",
        failed
          ? "border-error-dim/20 hover:border-error-dim/40"
          : "border-border hover:border-foreground/15",
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
      {failed && (
        <span className="shrink-0 flex items-center gap-1 text-[9px] font-bold text-error-dim/70">
          <AlertTriangle className="h-3 w-3" />
          <span className="hidden sm:inline">Failed</span>
        </span>
      )}
      {onAnalyze && (
        <Button
          variant="ghost"
          size="sm"
          className={cn(
            "shrink-0 transition-opacity text-muted-foreground hover:text-foreground",
            !failed && "opacity-0 group-hover:opacity-100",
          )}
          onClick={() => onAnalyze(c.headline, { context: buildClusterContext(c) })}
        >
          {failed ? (
            <>
              <RotateCw className="h-3 w-3" />
              <span className="hidden sm:inline ml-1">Retry</span>
            </>
          ) : (
            <>
              <FlaskConical className="h-3 w-3" />
              <span className="hidden sm:inline ml-1">Analyze</span>
            </>
          )}
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
  /** Headlines whose analysis returned failed/mock — hidden for this session. */
  failedHeadlines?: Set<string>;
}

function _refreshLabel(meta: RefreshMeta): string {
  if (meta.status === "throttled") return "Refresh in progress — try again shortly";
  if (meta.status === "recent") return "Already refreshed — data is current";
  if (meta.status === "error")
    return meta.error ?? "Refresh failed — showing last known data";
  if (meta.status === "degraded") {
    const base = meta.error ?? `${meta.fail_feeds ?? 0} feeds failed`;
    const count = meta.created + meta.merged + meta.reused;
    return count > 0 ? `${base} — ${count} clusters available` : base;
  }
  if (meta.source === "empty") return "No headlines found";
  if (meta.source === "stored" || meta.source === "stored_fallback")
    return `${meta.reused} stored cluster${meta.reused !== 1 ? "s" : ""} reused — nothing new`;
  // incremental or full_recluster
  const parts: string[] = [];
  if (meta.created > 0) parts.push(`${meta.created} new`);
  if (meta.merged > 0) parts.push(`${meta.merged} merged`);
  if (meta.reused > 0) parts.push(`${meta.reused} reused`);
  return parts.join(", ") || "Refreshed";
}

function _refreshDotClass(meta: RefreshMeta): string {
  if (meta.status === "error") return "bg-destructive";
  if (meta.status === "degraded") return "bg-[#facc15]";
  if (meta.status === "throttled" || meta.status === "recent") return "bg-muted-foreground/40";
  if (meta.new > 0) return "bg-primary";
  return "bg-muted-foreground/40";
}

export function HeadlinesPage({ onAnalyze, failedHeadlines }: HeadlinesPageProps) {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [showLowSignal, setShowLowSignal] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [lastMeta, setLastMeta] = useState<RefreshMeta | null>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);

  // Monotonic counter + AbortController: prevents out-of-order responses
  // from overwriting newer state, and cancels in-flight requests on
  // unmount or when a newer refresh supersedes.
  const refreshSeqRef = useRef(0);
  const refreshAbortRef = useRef<AbortController | null>(null);

  const handleRefresh = useCallback(async () => {
    // Abort any in-flight refresh before starting a new one
    refreshAbortRef.current?.abort();
    const ctrl = new AbortController();
    refreshAbortRef.current = ctrl;

    const seq = ++refreshSeqRef.current;
    setRefreshing(true);
    try {
      const res = await api.newsRefresh(ctrl.signal);
      if (seq !== refreshSeqRef.current) return; // stale response — discard
      const meta = res.refresh_meta;
      if (meta) {
        setLastMeta(meta);
        // Only invalidate the query cache when the refresh actually
        // produced a successful payload — avoids blanking the cluster
        // list during degraded/error transitions.
        if (meta.status === "ok" || meta.status === "recent") {
          queryClient.invalidateQueries({ queryKey: ["news"] });
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return; // silent
      if (seq !== refreshSeqRef.current) return;
      // Network failure: keep the last good meta visible, just mark status
      setLastMeta((prev) =>
        prev ? { ...prev, status: "error", freshness: "stale", error: "Network error" } : null,
      );
    } finally {
      if (seq === refreshSeqRef.current) setRefreshing(false);
    }
  }, [queryClient]);

  // Abort in-flight refresh on unmount
  useEffect(() => {
    return () => { refreshAbortRef.current?.abort(); };
  }, []);

  const { data: trendsData } = useQuery({
    queryKey: qk.newsTrends(),
    queryFn: () => api.newsTrends(),
    staleTime: 300_000,
  });
  const trends = trendsData ?? [];

  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading, isError } = useInfiniteQuery({
    queryKey: qk.newsPaginated(PAGE_SIZE),
    queryFn: ({ pageParam }: { pageParam: number }) => api.news(PAGE_SIZE, pageParam),
    getNextPageParam: _getNextPageParam,
    initialPageParam: 0,
    staleTime: 300_000,
  });

  // IntersectionObserver for infinite scroll
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => { if (entries[0]?.isIntersecting && hasNextPage && !isFetchingNextPage) fetchNextPage(); },
      { rootMargin: "200px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  // Guard: p.clusters may be undefined if a page came back malformed.
  // flatMap preserves undefined entries which then crash c.headline access.
  const allClusters = data?.pages.flatMap((p) => p?.clusters ?? []) ?? [];
  const totalCount = data?.pages[0]?.total_count ?? 0;
  // Effective refresh metadata: prefer the manual-refresh result, fall back
  // to the initial page load's refresh_meta so the status shows on cold start.
  const effectiveMeta = lastMeta ?? data?.pages[0]?.refresh_meta ?? null;
  // Macro releases come from the first page (static calendar data, same on every page)
  const macroReleases = data?.pages[0]?.macro_releases ?? [];
  const policyItems   = data?.pages[0]?.policy_items   ?? [];

  // Auto-refresh once on page load when news data is stale or degraded.
  const autoRefreshedRef = useRef(false);
  useEffect(() => {
    if (autoRefreshedRef.current || refreshing || !effectiveMeta) return;
    const f = effectiveMeta.freshness;
    if (f === "stale" || f === "degraded") {
      autoRefreshedRef.current = true;
      handleRefresh();
    }
  }, [effectiveMeta, refreshing, handleRefresh]);

  // Client-side search filter — failed headlines stay visible (inline state)
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
        <Button
          variant="ghost"
          size="sm"
          onClick={handleRefresh}
          disabled={refreshing}
          className="ml-auto h-7 px-2 text-[10px] text-muted-foreground"
        >
          <RefreshCw className={cn("h-3 w-3 mr-1", refreshing && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {/* Refresh status — shown on initial load (from GET /news) and after manual refresh */}
      {effectiveMeta && (
        <div className={cn(
          "flex items-center gap-2 text-[10px]",
          effectiveMeta.status === "error" ? "text-destructive/80" :
          effectiveMeta.status === "degraded" ? "text-[#facc15]/80" :
          "text-muted-foreground/70",
        )}>
          <span className={cn("inline-block w-1.5 h-1.5 rounded-full shrink-0", _refreshDotClass(effectiveMeta))} />
          <span>{_refreshLabel(effectiveMeta)}</span>
          {effectiveMeta.last_successful_refresh && (
            <span className="text-muted-foreground/40 ml-1">
              · as of {new Date(effectiveMeta.last_successful_refresh).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
        </div>
      )}

      {/* Macro calendar strip */}
      {macroReleases.length > 0 && <MacroCalendarStrip releases={macroReleases} />}

      {/* Policy tracker strip */}
      {policyItems.length > 0 && <PolicyTrackerStrip items={policyItems} />}

      {/* Trending themes */}
      {trends.length > 0 && (
        <TrendingThemesStrip trends={trends} onSelect={(term) => setSearch(term)} />
      )}

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

      {/* Error fallback — query failed and no cached data */}
      {isError && !isLoading && allClusters.length === 0 && (
        <div className="py-8 text-center">
          <p className="text-sm text-muted-foreground">Unable to load headlines.</p>
          <p className="text-xs text-muted-foreground/50 mt-1">
            Check that the backend is running, then refresh.
          </p>
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
            {normal.map((c) => (
              <HeadlineRow
                key={c.headline}
                c={c}
                onAnalyze={onAnalyze}
                failed={deriveRowState(c.headline, failedHeadlines) === "failed"}
              />
            ))}
          </div>

          {showLowSignal && lowSignal.length > 0 && (
            <div className="space-y-1.5 pt-1">
              <span className="text-[10px] text-muted-foreground/50 uppercase tracking-widest">Low signal</span>
              <div className="grid gap-1.5 xl:grid-cols-2">
                {lowSignal.map((c) => (
                  <HeadlineRow
                    key={c.headline}
                    c={c}
                    onAnalyze={onAnalyze}
                    muted
                    failed={deriveRowState(c.headline, failedHeadlines) === "failed"}
                  />
                ))}
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
