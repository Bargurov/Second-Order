import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type MarketSnapshot } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";

/**
 * BenchmarkSnapshotsStrip
 * ------------------------
 * Renders the 8 liquid market snapshots (ES, NQ, RTY, CL, GC, DXY, 2Y, 10Y)
 * from /snapshots.  Prefers warm cached snapshots from the background refresh
 * thread; degrades quietly when individual markets are stale or unavailable.
 *
 * Visual states per cell:
 *   - fresh:        full opacity, coloured change
 *   - stale:        slightly dimmed value + small "stale" tag
 *   - unavailable:  em-dash placeholder, no change indicator
 */

// Canonical display order — matches LIQUID_MARKETS in market_universe.py.
const MARKET_ORDER = ["ES", "NQ", "RTY", "CL", "GC", "DXY", "2Y", "10Y"] as const;

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

interface CellProps {
  snap: MarketSnapshot | undefined;
  market: string;
  isFirst: boolean;
}

function SnapshotCell({ snap, market, isFirst }: CellProps) {
  // Treat missing/errored/null-value snapshots as unavailable
  const unavailable = !snap || snap.value == null || snap.error != null;
  const change = snap?.change_5d ?? null;
  const stale = snap?.stale ?? false;

  return (
    <div className="flex items-center gap-6">
      {!isFirst && <div className="w-px h-8 bg-outline-variant/20" />}
      <div className="flex flex-col min-w-[60px]">
        <div className="flex items-center gap-1">
          <span className="text-[10px] uppercase tracking-widest text-on-surface-variant font-bold">
            {snap?.label ?? market}
          </span>
          {stale && !unavailable && (
            <span
              title={`Last refreshed ${snap?.fetched_at ?? "unknown"}`}
              className="text-[8px] uppercase tracking-widest text-on-surface-variant/40 font-bold"
            >
              · stale
            </span>
          )}
        </div>
        <div className="flex items-baseline gap-1.5">
          <span
            className={cn(
              "text-lg font-headline font-bold tracking-tighter font-num",
              unavailable
                ? "text-on-surface-variant/30"
                : stale
                ? "text-on-surface/70"
                : "text-on-surface",
            )}
          >
            {fmtVal(snap?.value ?? null, snap?.unit ?? "")}
          </span>
          {!unavailable && change != null && (
            <span
              className={cn(
                "text-[10px] font-bold font-num",
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
        </div>
      </div>
    </div>
  );
}

interface BenchmarkSnapshotsStripProps {
  /** When provided (parent-driven), these snapshots are rendered directly
   *  and no internal fetch is made.  When omitted (standalone usage), the
   *  component falls back to its own /snapshots query for backward compat. */
  snapshots?: MarketSnapshot[] | null;
  isLoading?: boolean;
}

export function BenchmarkSnapshotsStrip({
  snapshots: parentSnapshots,
  isLoading: parentLoading,
}: BenchmarkSnapshotsStripProps = {}) {
  // Parent-provided data takes precedence; only fetch when nothing was passed in.
  const enabled = parentSnapshots === undefined;
  const {
    data: fetched,
    isLoading: fetchedLoading,
    isError,
  } = useQuery({
    queryKey: qk.snapshots(),
    queryFn: () => api.snapshots(),
    // Refetch every 60s so the UI tracks the background refresh cadence
    refetchInterval: 60_000,
    staleTime: 30_000,
    enabled,
  });

  const data = enabled ? fetched : (parentSnapshots ?? undefined);
  const isLoading = enabled ? fetchedLoading : (parentLoading ?? false);

  if (isLoading) {
    return (
      <section className="bg-surface-container-low rounded-xl p-5 mb-8">
        <div className="flex items-center gap-6">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton
              key={i}
              className="h-10 w-20 bg-surface-container-highest"
            />
          ))}
        </div>
      </section>
    );
  }

  // Hide the section entirely if the endpoint is unreachable or returns nothing.
  // This keeps Market Overview clean when the background thread is disabled.
  if (isError || !data || data.length === 0) {
    return null;
  }

  // Build a market → snapshot lookup so we can render in canonical order
  // even if the API returns them in a different sequence.
  const byMarket: Record<string, MarketSnapshot> = {};
  for (const snap of data) {
    byMarket[snap.market] = snap;
  }

  // Count how many snapshots are usable (have a value).  Hide the strip
  // when nothing useful is available — partial availability is fine.
  const usableCount = data.filter(
    (s) => s.value != null && s.error == null,
  ).length;
  if (usableCount === 0) return null;

  return (
    <section className="bg-surface-container-low rounded-xl p-5 mb-8">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant flex items-center gap-2">
          <span className="w-1 h-3 bg-primary rounded-full" />
          Liquid Benchmarks
        </h3>
        {usableCount < MARKET_ORDER.length && (
          <span className="text-[9px] text-on-surface-variant/40 font-bold uppercase tracking-widest">
            {usableCount}/{MARKET_ORDER.length}
          </span>
        )}
      </div>
      <div className="flex items-center gap-6 flex-wrap">
        {MARKET_ORDER.map((market, i) => (
          <SnapshotCell
            key={market}
            snap={byMarket[market]}
            market={market}
            isFirst={i === 0}
          />
        ))}
      </div>
    </section>
  );
}
