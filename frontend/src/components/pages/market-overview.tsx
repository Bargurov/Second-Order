import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { ArrowRight, AlertTriangle } from "lucide-react";
import { api, type MarketMover, type MoverTicker } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { pct } from "@/lib/ticker-utils";
import { UncertaintySection } from "@/components/ui/stress-strip";
import { BenchmarkSnapshotsStrip } from "@/components/ui/benchmark-snapshots-strip";

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
    return anchors[0];
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

function WeeklyTickerChip({ t }: { t: MoverTicker }) {
  const r5 = t.return_5d;
  return (
    // Symbol + return only — mini sparklines removed alongside the
    // PersistentCard cleanup; at 32px wide they were noise.
    <div className="bg-surface-container px-2 py-1 rounded flex items-center gap-2 shrink-0">
      <span className="text-[10px] font-bold text-white tracking-wider">{t.symbol}</span>
      {r5 != null && (
        <span className={cn(
          "text-[10px] font-bold tnum",
          r5 > 0 ? "text-primary" : r5 < 0 ? "text-error-dim" : "text-on-surface-variant",
        )}>
          {pct(r5)}
        </span>
      )}
    </div>
  );
}

function WeeklyCard({ mover, onAnalyze }: {
  mover: MarketMover;
  onAnalyze?: (headline: string, opts?: { eventId?: number; context?: string }) => void;
}) {
  const pctVal = Math.round(mover.support_ratio * 100);
  const anchorDate = _cardAnchorDate(mover);
  const asOf = _fmtAsOf(mover.last_market_check_at);
  return (
    <div
      className="bg-surface-container-highest p-5 rounded-lg cursor-pointer transition-all shadow-[inset_0_0_0_1px_rgba(71,70,86,0.15)] hover:shadow-[inset_0_0_0_1px_rgba(71,70,86,0.4)]"
      onClick={() => onAnalyze?.(mover.headline, { eventId: mover.event_id })}
    >
      <div className="flex justify-between items-start mb-4">
        <h3 className="text-sm font-bold text-white leading-tight pr-4 line-clamp-2">
          {mover.headline}
        </h3>
        <span
          className="text-primary font-bold text-xs tnum shrink-0"
          title={`${pctVal}% — fraction of qualifying tickers whose realised direction matches the hypothesis`}
        >
          {pctVal}%
        </span>
      </div>
      {/* Enriched ticker chips: symbol + sparkline + return_5d so the
          weekly preview carries real evidence instead of a single
          thin chip with no values. */}
      <div className="flex flex-wrap gap-2 mb-3">
        {mover.tickers.slice(0, 4).map((t) => (
          <WeeklyTickerChip key={t.symbol} t={t} />
        ))}
      </div>
      {/* Anchor + as-of footer — same shape as PersistentCard so users
          can see why the same ticker can read differently across
          cards: forward returns are measured from the anchor date. */}
      <div className="flex items-center justify-between gap-2 text-[9px] text-on-surface-variant/60 font-medium uppercase tracking-widest">
        {anchorDate ? (
          <span title="Forward returns measured from this anchor date">
            Anchor <span className="tnum text-on-surface-variant/80">{anchorDate}</span>
          </span>
        ) : (
          <span />
        )}
        {asOf && (
          <span title="Most recent provider refresh for this card">
            As of <span className="tnum text-on-surface-variant/80">{asOf}</span>
          </span>
        )}
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
// Main page
// ---------------------------------------------------------------------------

export function MarketOverview({ onAnalyze }: { onAnalyze?: (headline: string, opts?: { eventId?: number; context?: string }) => void }) {
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

  // Distribute the unified context to child components.
  const stress = ctx?.stress ?? null;
  const snapshots = ctx?.snapshots ?? null;
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

      {/* 4. Today — inline footer strip, fed from /market-context highlights */}
      <TodayStrip movers={todaysHighlights} isLoading={ctxLoading} />
    </div>
  );
}
