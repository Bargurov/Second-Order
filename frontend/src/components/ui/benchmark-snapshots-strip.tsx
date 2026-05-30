import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type MarketSnapshot } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";

/**
 * BenchmarkSnapshotsStrip
 * ------------------------
 * Renders the 8 liquid market snapshots (ES, NQ, RTY, CL, GC, DXY, 2Y, 10Y)
 * from /snapshots as the design package's hairline-gridded mono row
 * (`.mo-snaps`). Prefers warm cached snapshots from the background refresh
 * thread; degrades quietly when individual markets are stale or unavailable.
 *
 * Colours come from the design palette (CSS vars set by the Market Overview
 * page root): jade for up moves, rust for down, dim ink for flat/stale.
 *
 * Visual states per cell:
 *   - fresh:        full opacity, sign-coloured 5d change
 *   - stale:        slightly dimmed value + small "stale" tag
 *   - unavailable:  em-dash placeholder, no change indicator
 */

// Canonical display order — matches LIQUID_MARKETS in market_universe.py.
const MARKET_ORDER = ["ES", "NQ", "RTY", "CL", "GC", "DXY", "2Y", "10Y"] as const;

function fmtVal(v: number | null, unit: string): string {
  if (v == null) return "—";
  if (unit === "%") return `${v.toFixed(2)}%`;
  return v.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function fmtChg(v: number | null): string {
  if (v == null) return "";
  const sign = v >= 0 ? "+" : "−"; // U+2212 math minus
  return `${sign}${Math.abs(v).toFixed(2)}%`;
}

function SnapshotCell({
  snap,
  market,
}: {
  snap: MarketSnapshot | undefined;
  market: string;
}) {
  // Treat missing/errored/null-value snapshots as unavailable.
  const unavailable = !snap || snap.value == null || snap.error != null;
  const change = snap?.change_5d ?? null;
  const stale = snap?.stale ?? false;

  return (
    <div className="bg-[var(--so-bg-1)] px-3.5 py-3">
      <div className="flex items-center gap-1">
        <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--so-ink-3)]">
          {snap?.label ?? market}
        </span>
        {stale && !unavailable && (
          <span
            title={`Last refreshed ${snap?.fetched_at ?? "unknown"}`}
            className="font-mono text-[8px] uppercase tracking-[0.14em] text-[var(--so-ink-4)]"
          >
            · stale
          </span>
        )}
      </div>
      <div
        className={cn(
          "mt-1.5 font-mono text-[17px] leading-none tracking-tight tabular-nums",
          unavailable
            ? "text-[var(--so-ink-4)]"
            : stale
            ? "text-[var(--so-ink-2)]"
            : "text-[var(--so-ink-0)]",
        )}
      >
        {fmtVal(snap?.value ?? null, snap?.unit ?? "")}
      </div>
      {!unavailable && change != null ? (
        <div
          className={cn(
            "mt-1.5 font-mono text-[11px] tabular-nums",
            change > 0
              ? "text-[var(--so-jade-ink)]"
              : change < 0
              ? "text-[var(--so-rust-ink)]"
              : "text-[var(--so-ink-3)]",
          )}
        >
          {fmtChg(change)}
        </div>
      ) : (
        // Keep cell heights even when a market shows no signed change.
        <div className="mt-1.5 h-[14px]" />
      )}
    </div>
  );
}

function SnapshotsFrame({
  status,
  children,
}: {
  status?: string;
  children: ReactNode;
}) {
  // Hairline grid: a faint rule shows through the 1px gaps and the border, so
  // the cells read as a single mono row (`.mo-snaps`) with no card nesting.
  return (
    <section className="mb-8">
      {status && (
        <div className="mb-1.5 text-right font-mono text-[9px] uppercase tracking-[0.16em] text-[var(--so-ink-3)]">
          {status}
        </div>
      )}
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[4px] border border-[color:var(--so-rule)] bg-[color:var(--so-rule)] sm:grid-cols-4 lg:grid-cols-8">
        {children}
      </div>
    </section>
  );
}

function UnavailableSnapshotStrip({ isError }: { isError?: boolean }) {
  return (
    <SnapshotsFrame status={isError ? "Degraded" : "Unavailable"}>
      {MARKET_ORDER.map((market) => (
        <SnapshotCell key={market} snap={undefined} market={market} />
      ))}
    </SnapshotsFrame>
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
    // Refetch every 60s so the UI tracks the background refresh cadence.
    refetchInterval: 60_000,
    staleTime: 30_000,
    enabled,
  });

  const data = enabled ? fetched : (parentSnapshots ?? undefined);
  const isLoading = enabled ? fetchedLoading : (parentLoading ?? false);

  if (isLoading) {
    return (
      <SnapshotsFrame>
        {MARKET_ORDER.map((market) => (
          <div key={market} className="bg-[var(--so-bg-1)] px-3.5 py-3">
            <Skeleton className="h-3 w-10 bg-[var(--so-bg-2)]" />
            <Skeleton className="mt-2 h-4 w-14 bg-[var(--so-bg-2)]" />
          </div>
        ))}
      </SnapshotsFrame>
    );
  }

  // Keep the row visible and truthful when provider data is unavailable.
  // Missing benchmark data should read as Unavailable, not disappear or fall
  // back to sample-looking numbers.
  if (isError || !data || data.length === 0) {
    return <UnavailableSnapshotStrip isError={isError} />;
  }

  // Build a market → snapshot lookup so we can render in canonical order
  // even if the API returns them in a different sequence.
  const byMarket: Record<string, MarketSnapshot> = {};
  for (const snap of data) {
    byMarket[snap.market] = snap;
  }

  // Count how many snapshots are usable (have a value).  Show an Unavailable
  // grid when nothing useful is available — partial availability is fine.
  const usableCount = data.filter(
    (s) => s.value != null && s.error == null,
  ).length;
  if (usableCount === 0) return <UnavailableSnapshotStrip />;

  return (
    <SnapshotsFrame
      status={
        usableCount < MARKET_ORDER.length
          ? `${usableCount}/${MARKET_ORDER.length}`
          : undefined
      }
    >
      {MARKET_ORDER.map((market) => (
        <SnapshotCell key={market} snap={byMarket[market]} market={market} />
      ))}
    </SnapshotsFrame>
  );
}
