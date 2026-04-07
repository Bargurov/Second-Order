import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type MarketSnapshot } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";

/**
 * MarketBackdropStrip
 * --------------------
 * Compact secondary block shown at the top of the analysis page to give
 * the reader a quick read on current market backdrop while studying an
 * event thesis.
 *
 * Reads from /market-context (the same shared surface Market Overview
 * uses) — no new parallel composition, no extra cold fetches.
 *
 * Renders three sub-pieces in one row:
 *   1. Regime chip (compact stress regime label)
 *   2. Five key benchmark values (ES, CL, GC, DXY, 10Y) with 5d change
 *   3. Optional one-line "top mover" callout
 *
 * Visual treatment is intentionally smaller than Market Overview's
 * BenchmarkSnapshotsStrip — this is secondary context, not the primary
 * focus of the analysis page.
 *
 * Hides cleanly when no data is available.  Stale snapshots are tagged
 * inline.  Partial availability degrades gracefully.
 */

// The 5 benchmarks the analysis backdrop shows.  Picked for breadth across
// asset classes (equity, oil, gold, FX, rates) without overwhelming the
// secondary strip.  Subset of LIQUID_MARKETS.
const BACKDROP_MARKETS = ["ES", "CL", "GC", "DXY", "10Y"] as const;

function fmtVal(v: number | null, unit: string): string {
  if (v == null) return "\u2014";
  if (unit === "%") return `${v.toFixed(2)}%`;
  return v.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function fmtChg(v: number | null): string {
  if (v == null) return "";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

// Compact regime → color mapping (mirrors stress-strip but more muted).
function regimeChipClass(regime: string): string {
  const r = regime.toLowerCase();
  if (r.includes("systemic")) return "bg-error/15 text-error border-error/30";
  if (r.includes("geopolit") || r.includes("undercurrent"))
    return "bg-[#facc15]/10 text-[#facc15] border-[#facc15]/30";
  if (r === "calm" || r.includes("calm"))
    return "bg-primary/10 text-primary border-primary/30";
  return "bg-surface-container text-on-surface-variant border-outline-variant/30";
}

export function MarketBackdropStrip() {
  const { data: ctx, isLoading, isError } = useQuery({
    queryKey: qk.marketContext(),
    queryFn: () => api.marketContext(1),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center gap-4">
        <Skeleton className="h-5 w-20 bg-surface-container-highest" />
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-5 w-16 bg-surface-container-highest" />
        ))}
      </div>
    );
  }

  // Hide entirely on error or empty context — analysis page already has
  // strong primary content; the backdrop is best omitted than rendered blank.
  if (isError || !ctx) return null;

  const snapshots = ctx.snapshots ?? [];
  const stress = ctx.stress;
  const highlights = ctx.highlights ?? [];
  const meta = ctx.snapshots_meta;

  // Build market → snapshot lookup
  const byMarket: Record<string, MarketSnapshot> = {};
  for (const s of snapshots) byMarket[s.market] = s;

  // Pick the backdrop subset; only render the strip when at least one
  // benchmark has a value or the regime is meaningful.
  const usableSnaps = BACKDROP_MARKETS.map((m) => byMarket[m]).filter(
    (s) => s && s.value != null && s.error == null,
  );
  const hasRegime =
    stress &&
    stress.available !== false &&
    stress.regime &&
    stress.regime !== "Unknown";
  const topHighlight = highlights[0];

  if (usableSnaps.length === 0 && !hasRegime && !topHighlight) {
    return null;
  }

  const staleCount = meta?.stale ?? 0;
  const unavailableCount = meta?.unavailable ?? 0;
  const source = ctx.source;

  return (
    <div className="space-y-2">
      {/* Top row: regime chip + benchmarks */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-[9px] font-bold uppercase tracking-[0.2em] text-on-surface-variant/60">
          Market Backdrop
        </span>

        {hasRegime && (
          <span
            className={cn(
              "inline-flex items-center px-2 py-0.5 rounded-full border text-[9px] font-bold uppercase tracking-widest",
              regimeChipClass(stress.regime),
            )}
          >
            {stress.regime}
          </span>
        )}

        {usableSnaps.length > 0 && (
          <div className="flex items-center gap-3 flex-wrap">
            {BACKDROP_MARKETS.map((market, i) => {
              const snap = byMarket[market];
              const unavailable = !snap || snap.value == null || snap.error != null;
              const stale = snap?.stale ?? false;
              const change = snap?.change_5d ?? null;

              return (
                <div
                  key={market}
                  className="flex items-center gap-1.5"
                >
                  {i > 0 && (
                    <span className="w-px h-3 bg-outline-variant/15" />
                  )}
                  <span className="text-[9px] uppercase tracking-widest text-on-surface-variant/50 font-bold">
                    {market}
                  </span>
                  <span
                    className={cn(
                      "text-[11px] font-num font-bold tabular-nums",
                      unavailable
                        ? "text-on-surface-variant/30"
                        : stale
                        ? "text-on-surface/60"
                        : "text-on-surface",
                    )}
                  >
                    {fmtVal(snap?.value ?? null, snap?.unit ?? "")}
                  </span>
                  {!unavailable && change != null && (
                    <span
                      className={cn(
                        "text-[9px] font-num font-bold tabular-nums",
                        change > 0
                          ? "text-primary"
                          : change < 0
                          ? "text-error-dim"
                          : "text-on-surface-variant",
                      )}
                    >
                      {fmtChg(change)}
                    </span>
                  )}
                  {stale && !unavailable && (
                    <span
                      title={`Last refreshed ${snap?.fetched_at ?? "unknown"}`}
                      className="text-[8px] uppercase tracking-widest text-on-surface-variant/35 font-bold"
                    >
                      stale
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Second row: top mover + quiet freshness footer */}
      {(topHighlight || staleCount > 0 || unavailableCount > 0) && (
        <div className="flex items-center justify-between gap-4 flex-wrap">
          {topHighlight ? (
            <p className="text-[10px] text-on-surface-variant/60 italic leading-tight truncate min-w-0 flex-1">
              <span className="text-on-surface-variant/40 font-bold uppercase tracking-widest not-italic mr-1">
                Top mover
              </span>
              {topHighlight.headline.length > 80
                ? topHighlight.headline.slice(0, 77) + "..."
                : topHighlight.headline}
              {topHighlight.tickers?.[0]?.return_5d != null && (
                <span
                  className={cn(
                    "ml-1.5 not-italic font-num font-bold tabular-nums",
                    topHighlight.tickers[0].return_5d > 0
                      ? "text-primary/80"
                      : "text-error-dim/80",
                  )}
                >
                  {topHighlight.tickers[0].symbol}{" "}
                  {topHighlight.tickers[0].return_5d >= 0 ? "+" : ""}
                  {topHighlight.tickers[0].return_5d.toFixed(2)}%
                </span>
              )}
            </p>
          ) : (
            <span />
          )}
          {(staleCount > 0 || unavailableCount > 0 || source) && (
            <span className="text-[8px] text-on-surface-variant/30 font-bold uppercase tracking-widest shrink-0">
              {source ? `src: ${source}` : ""}
              {staleCount > 0 ? ` · ${staleCount} stale` : ""}
              {unavailableCount > 0 ? ` · ${unavailableCount} n/a` : ""}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
