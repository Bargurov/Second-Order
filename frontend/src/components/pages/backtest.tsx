import { useQuery } from "@tanstack/react-query";
import { qk } from "@/lib/queryKeys";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Minus,
  ShieldCheck,
  Shield,
  ShieldAlert,
  Target,
  Loader2,
} from "lucide-react";
import { api, type SavedEvent, type BacktestResult, type MacroEntry } from "@/lib/api";
import { cn } from "@/lib/utils";

// Minimal inline macro display — takes pre-fetched entries, no fetch of its own.
function MacroCards({ entries }: { entries: MacroEntry[] }) {
  const usable = entries.filter((e) => e.value != null);
  if (usable.length < 2) return null;
  return (
    <div className="flex gap-1.5 overflow-x-auto pb-0.5">
      {usable.map((e) => (
        <div key={e.label} className="shrink-0 flex min-w-[4.25rem] flex-col items-center rounded-xl border border-border bg-card px-2.5 py-1.5">
          <span className="text-[10px] uppercase tracking-[0.16em] text-foreground/72">{e.label}</span>
          <span className="font-num text-2xs font-medium">
            {e.unit === "%" ? `${e.value!.toFixed(2)}%` : e.value!.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
          {e.change_5d != null && (
            <span className={cn("font-num text-[10px]",
              e.change_5d > 0 && "val-pos", e.change_5d < 0 && "val-neg",
            )}>
              {e.change_5d >= 0 ? "+" : ""}{e.change_5d.toFixed(2)}%
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pct(v: number | null | undefined): string {
  if (v == null) return "\u2014";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function dirIcon(dir: string | null) {
  if (!dir) return <Minus className="h-3 w-3 val-flat" />;
  if (dir.includes("supports") && dir.includes("\u2191"))
    return <TrendingUp className="h-3 w-3 val-pos" />;
  if (dir.includes("supports") && dir.includes("\u2193"))
    return <TrendingDown className="h-3 w-3 val-pos" />;
  if (dir.includes("contradicts"))
    return <TrendingDown className="h-3 w-3 val-neg" />;
  return <Minus className="h-3 w-3 val-flat" />;
}

const CONF_ICON: Record<string, React.ElementType> = {
  high: ShieldCheck,
  medium: Shield,
  low: ShieldAlert,
};

// ---------------------------------------------------------------------------
// Scorecard badge
// ---------------------------------------------------------------------------

function ScoreBadge({ score }: { score: { supporting: number; total: number } | null }) {
  if (!score || score.total === 0) return <Badge variant="outline">no data</Badge>;
  const ratio = score.supporting / score.total;
  const variant = ratio >= 0.6 ? "default" : ratio >= 0.4 ? "secondary" : "destructive";
  return (
    <Badge variant={variant} className="font-num">
      {score.supporting}/{score.total}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Row for a single event with its backtest result
// ---------------------------------------------------------------------------

function EventScorecard({
  event,
  result,
  loading,
  macroEntries,
}: {
  event: SavedEvent;
  result: BacktestResult | null;
  loading: boolean;
  macroEntries?: MacroEntry[];
}) {
  const ConfIcon = CONF_ICON[event.confidence] ?? ShieldAlert;
  const hasDate = !!event.event_date;

  return (
    <Card className="overflow-hidden border-border bg-card">
      <CardHeader className="gap-3 border-b border-border bg-secondary/35 pb-3">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-[13px] leading-snug font-medium">
            {event.headline}
          </CardTitle>
          {loading ? (
            <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" />
          ) : (
            <ScoreBadge score={result?.score ?? null} />
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1.5 pt-1 text-2xs text-foreground/72">
          <Badge variant="outline">{event.stage}</Badge>
          <Badge variant="outline">{event.persistence}</Badge>
          <ConfIcon className={cn("h-3 w-3",
            event.confidence === "high" && "val-pos",
            event.confidence === "medium" && "text-gray-400",
            event.confidence === "low" && "val-neg",
          )} />
          {event.event_date && (
            <span className="font-num">{event.event_date}</span>
          )}
          {event.rating && (
            <Badge variant={event.rating === "good" ? "default" : event.rating === "poor" ? "destructive" : "secondary"}>
              {event.rating}
            </Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-3 pt-3">
        {hasDate && macroEntries && (
          <MacroCards entries={macroEntries} />
        )}

        {!hasDate && (
          <p className="text-2xs leading-5 text-foreground/72">No event date saved. Backtest unavailable.</p>
        )}

        {hasDate && loading && (
          <div className="flex gap-2 pt-0.5">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-20 rounded" />
            ))}
          </div>
        )}

        {hasDate && !loading && result && result.outcomes.length > 0 && (
          <div className="flex gap-1.5 overflow-x-auto pb-0.5">
            {result.outcomes.map((o) => {
              const noData = o.return_5d == null;
              return (
                <div
                  key={o.symbol}
                  className={cn(
                    "shrink-0 flex items-center gap-1.5 rounded-xl border px-2.5 py-1.5",
                    noData
                      ? "border-border bg-secondary/45"
                      : "border-border bg-card",
                  )}
                >
                  <span className="font-num text-2xs font-semibold">{o.symbol}</span>
                  <Badge variant={o.role === "beneficiary" ? "secondary" : "outline"}>
                    {o.role === "beneficiary" ? "L" : "S"}
                  </Badge>
                  {!noData && (
                    <>
                      {dirIcon(o.direction)}
                      <span className={cn("font-num text-2xs",
                        o.return_5d != null && o.return_5d > 0 && "val-pos",
                        o.return_5d != null && o.return_5d < 0 && "val-neg",
                      )}>
                        {pct(o.return_5d)}
                      </span>
                    </>
                  )}
                  {noData && (
                    <span className="text-2xs text-foreground/55">\u2014</span>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {hasDate && !loading && result && result.outcomes.length === 0 && (
          <p className="text-2xs leading-5 text-foreground/72">No market tickers saved for this event.</p>
        )}

        {hasDate && !loading && !result && (
          <p className="text-2xs leading-5 text-foreground/72">Backtest results unavailable.</p>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Aggregate summary
// ---------------------------------------------------------------------------

function AggregateSummary({ results }: { results: Map<number, BacktestResult> }) {
  let totalSupporting = 0;
  let totalTickers = 0;
  let eventsScored = 0;

  for (const r of results.values()) {
    if (r.score) {
      totalSupporting += r.score.supporting;
      totalTickers += r.score.total;
      eventsScored++;
    }
  }

  if (eventsScored === 0) return null;

  const hitRate = totalTickers > 0 ? ((totalSupporting / totalTickers) * 100).toFixed(0) : "0";

  return (
    <Card className="overflow-hidden border-border bg-card">
      <CardContent className="flex items-center gap-3 px-4 py-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-border bg-secondary/35">
          <Target className="h-4 w-4 text-muted-foreground" />
        </div>
        <div className="space-y-0.5">
          <p className="section-kicker">Score overview</p>
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="font-num text-xl font-semibold text-foreground">{hitRate}%</span>
            <span className="text-[12px] leading-5 text-foreground/74">
              direction accuracy across <span className="font-num">{totalTickers}</span> tickers in{" "}
              <span className="font-num">{eventsScored}</span> scored events
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

export function Backtest() {
  // Load events list
  const { data: events = [], isLoading: eventsLoading, error: eventsError } = useQuery({
    queryKey: qk.events(50),
    queryFn: () => api.events(50),
  });

  const testable = events.filter((e) => e.event_date && e.market_tickers.length > 0);
  const testableIds = testable.map((e) => e.id);
  const testDates = [...new Set(testable.map((e) => e.event_date).filter(Boolean) as string[])];

  // Batch backtest — auto-runs when events load, keyed by the set of IDs
  const { data: batchResults, isLoading: running, refetch: rerunBatch } = useQuery({
    queryKey: qk.backtestBatch(testableIds),
    queryFn: () => api.backtestBatch(testableIds),
    enabled: testableIds.length > 0,
  });

  // Batch macro — keyed by the set of unique dates
  const { data: macroData = {} } = useQuery({
    queryKey: qk.macroBatch(testDates),
    queryFn: () => api.macroBatch(testDates),
    enabled: testDates.length > 0,
    staleTime: 300_000, // macro data: 5 min stale
  });

  // Build results map from batch array
  const results = new Map<number, BacktestResult>();
  if (batchResults) {
    for (const r of batchResults) {
      if (r.event_id != null) results.set(r.event_id, r);
    }
  }

  const loading = eventsLoading;
  const error = eventsError instanceof Error ? eventsError.message : eventsError ? String(eventsError) : null;

  const allTestable = events.filter((e) => e.event_date);
  const untestable = events.filter((e) => !e.event_date);

  return (
    // Page-level scroll: dropped `h-full` so the page is normal flow.
    <div className="flex flex-col gap-3">
      <div className="soft-panel flex shrink-0 flex-col gap-3 rounded-[22px] px-4 py-4 md:flex-row md:items-start md:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-border bg-white">
            <Target className="h-4 w-4 text-muted-foreground" />
          </div>
          <div className="min-w-0 space-y-1">
            <p className="section-kicker">Validation</p>
            <h2 className="truncate text-lg font-semibold tracking-[-0.02em] text-foreground">Backtest</h2>
            <p className="text-[12px] leading-5 text-foreground/78">
              {loading ? "Loading backtests..." : <><span className="font-num">{allTestable.length}</span> event{allTestable.length !== 1 && "s"} ready for dated review, with macro context alongside each scorecard.</>}
            </p>
          </div>
        </div>
        <div className="flex gap-1.5">
          <Button variant="outline" size="sm" onClick={() => rerunBatch()} disabled={running} className="shrink-0 disabled:border-border disabled:bg-secondary disabled:text-foreground/50">
            {running ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <RefreshCw className="h-3 w-3" />
            )}
            <span className="hidden sm:inline">Re-run backtests</span>
          </Button>
        </div>
      </div>

      {/* Aggregate summary */}
      <AggregateSummary results={results} />

      {error && (
        <Card className="shrink-0 border-destructive/30 bg-destructive/5">
          <CardContent className="py-4 text-2xs leading-5 text-destructive">{error}</CardContent>
        </Card>
      )}

      {loading && events.length === 0 && (
        <div className="min-h-0 flex-1 space-y-1.5">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="rounded-lg border px-3 py-2.5 space-y-1.5">
              <Skeleton className="h-3.5 w-4/5" />
              <Skeleton className="h-3 w-2/5" />
              <div className="flex gap-2 pt-0.5">
                <Skeleton className="h-8 w-20 rounded" />
                <Skeleton className="h-8 w-20 rounded" />
                <Skeleton className="h-8 w-20 rounded" />
              </div>
            </div>
          ))}
        </div>
      )}

      {!loading && events.length === 0 && (
        <Card className="empty-surface flex flex-1 items-center justify-center">
          <CardContent className="flex max-w-md flex-col items-center gap-3 py-12 text-center text-muted-foreground">
            <div className="flex h-14 w-14 items-center justify-center rounded-full border border-border bg-white">
              <Target className="h-6 w-6 opacity-70" />
            </div>
            <div className="space-y-1.5">
              <p className="text-sm font-medium text-foreground">No backtest set yet</p>
              <p className="text-[12px] leading-5 text-foreground/72">Run and save analyses first so dated events can be reviewed here.</p>
            </div>
          </CardContent>
        </Card>
      )}

      {events.length > 0 && (
        <ScrollArea className="min-h-0 flex-1">
          <div className="fade-in space-y-2.5 pr-2">
            {allTestable.map((ev) => (
              <EventScorecard
                key={ev.id}
                event={ev}
                result={results.get(ev.id) ?? null}
                loading={running && !results.has(ev.id)}
                macroEntries={ev.event_date ? macroData[ev.event_date] : undefined}
              />
            ))}
            {untestable.length > 0 && (
              <>
                <Separator className="my-2" />
                <p className="text-2xs leading-5 text-foreground/72 pb-1">
                  <span className="font-num">{untestable.length}</span> event{untestable.length !== 1 && "s"} without saved event dates
                </p>
                {untestable.map((ev) => (
                  <EventScorecard
                    key={ev.id}
                    event={ev}
                    result={null}
                    loading={false}
                  />
                ))}
              </>
            )}
          </div>
        </ScrollArea>
      )}
    </div>
  );
}
