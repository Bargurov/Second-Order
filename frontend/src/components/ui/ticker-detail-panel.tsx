import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { TickerChart } from "@/components/ui/ticker-chart";
import { api, type TickerBase } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { pct, fmtMktCap, fmtVol, RetVal } from "@/lib/ticker-utils";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface AnalysisExtra {
  label?: string;
  direction_tag?: string | null;
  return_1d?: number | null;
  volume_ratio?: number | null;
  vs_xle_5d?: number | null;
}

interface MoverExtra {
  decay?: string;
  decay_evidence?: string;
}

interface TickerDetailPanelProps {
  ticker: TickerBase;
  eventDate?: string;
  /** Present when rendered from the Analysis view. */
  extra?: AnalysisExtra;
  /** Present when rendered from Market Movers. */
  moverExtra?: MoverExtra;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isSupporting(extra?: AnalysisExtra): boolean {
  const d = extra?.direction_tag;
  return d === "supporting" || (d?.startsWith("supports") ?? false);
}

function isContradicting(extra?: AnalysisExtra): boolean {
  const d = extra?.direction_tag;
  return d === "contradicting" || (d?.startsWith("contradicts") ?? false);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TickerDetailPanel({ ticker, eventDate, extra, moverExtra }: TickerDetailPanelProps) {
  const supports = isSupporting(extra);
  const contradicts = isContradicting(extra);
  const vol = extra?.volume_ratio ?? null;
  const volHigh = vol != null && vol >= 1.25;

  const { data: chartData, isLoading: chartLoading } = useQuery({
    queryKey: qk.tickerChart(ticker.symbol, eventDate ?? ""),
    queryFn: () => api.tickerChart(ticker.symbol, eventDate!),
    enabled: !!eventDate,
    staleTime: 600_000,
  });

  const { data: info, isLoading: infoLoading } = useQuery({
    queryKey: qk.tickerInfo(ticker.symbol),
    queryFn: () => api.tickerInfo(ticker.symbol),
    staleTime: 3_600_000,
  });

  const { data: headlines } = useQuery({
    queryKey: qk.tickerHeadlines(ticker.symbol),
    queryFn: () => api.tickerHeadlines(ticker.symbol),
    staleTime: 300_000,
  });

  const hasInfo = info && (info.name || info.sector || info.market_cap);
  const hasChart = chartData && chartData.length > 2 && eventDate;
  const hasHeadlines = headlines && headlines.length > 0;

  // Build the return cells for the data strip.
  const returnCells: [string, number | null | undefined][] = [];
  if (extra) {
    returnCells.push(["1d", extra.return_1d]);
  }
  returnCells.push(["5d", ticker.return_5d]);
  returnCells.push(["20d", ticker.return_20d]);

  return (
    <div className="fade-in rounded-2xl border border-border bg-card shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      {/* Header row */}
      <div className="flex items-center gap-3 px-4 py-2.5">
        <span className={cn(
          "h-2 w-2 shrink-0 rounded-full",
          supports && "bg-[#15803d]",
          contradicts && "bg-[#b91c1c]",
          !supports && !contradicts && "bg-border",
        )} />
        <span className="font-num text-sm font-semibold">{ticker.symbol}</span>
        {info?.name && (
          <span className="truncate text-xs text-muted-foreground">{info.name}</span>
        )}
        <Badge variant={ticker.role === "beneficiary" ? "secondary" : "outline"}>
          {ticker.role === "beneficiary" ? "long" : "short"}
        </Badge>
        {extra?.label && (
          <span className="ml-auto text-2xs text-muted-foreground">{extra.label}</span>
        )}
        {!extra?.label && moverExtra?.decay && moverExtra.decay !== "Unknown" && (
          <span className={cn(
            "ml-auto text-[10px] font-medium px-1.5 py-0.5 rounded",
            moverExtra.decay === "Accelerating" && "bg-red-100 text-red-700",
            moverExtra.decay === "Holding" && "bg-amber-100 text-amber-700",
            moverExtra.decay === "Fading" && "bg-emerald-100 text-emerald-700",
            moverExtra.decay === "Reversed" && "bg-purple-100 text-purple-700",
          )}>
            {moverExtra.decay}
          </span>
        )}
      </div>

      {/* Company info strip */}
      {infoLoading && (
        <div className="flex gap-3 border-t border-border px-4 py-1.5">
          <Skeleton className="h-3 w-16" /><Skeleton className="h-3 w-20" /><Skeleton className="h-3 w-14" />
        </div>
      )}
      {!infoLoading && hasInfo && (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 border-t border-border px-4 py-1.5 text-[10px] text-muted-foreground">
          {info!.sector && <span>{info!.sector}</span>}
          {info!.industry && <span>· {info!.industry}</span>}
          {info!.market_cap && <span className="font-num">Mkt cap {fmtMktCap(info!.market_cap)}</span>}
          {info!.avg_volume && <span className="font-num">Avg vol {fmtVol(info!.avg_volume)}</span>}
        </div>
      )}
      {!infoLoading && !hasInfo && (
        <div className="border-t border-border px-4 py-1.5">
          <span className="text-[10px] text-muted-foreground/60">Company info unavailable</span>
        </div>
      )}

      {/* Event-anchored chart */}
      {chartLoading && eventDate && (
        <div className="border-t border-border px-4 py-3">
          <Skeleton className="h-[100px] w-full rounded-lg" />
        </div>
      )}
      {!chartLoading && hasChart && (
        <div className="border-t border-border px-3 py-2">
          <TickerChart
            data={chartData!}
            eventDate={eventDate!}
            width={440}
            height={100}
            className="w-full"
          />
        </div>
      )}
      {!chartLoading && !hasChart && eventDate && (
        <div className="border-t border-border px-4 py-2">
          <span className="text-[10px] text-muted-foreground/60">Price chart unavailable for this date range</span>
        </div>
      )}

      {/* Data strip */}
      <div className="flex border-t border-border">
        {returnCells.map(([label, val]) => (
          <div key={label} className="flex-1 flex items-center justify-center gap-1 py-1.5 border-r border-border">
            <span className="text-[10px] text-muted-foreground">{label}</span>
            <span className={cn(
              "font-num text-2xs font-medium",
              val != null && val > 0 && "val-pos",
              val != null && val < 0 && "val-neg",
              val == null && "text-muted-foreground",
            )}>
              {pct(val)}
            </span>
          </div>
        ))}
        {extra && (
          <div className="flex-1 flex items-center justify-center gap-1 py-1.5 border-r border-border">
            <span className="text-[10px] text-muted-foreground">Vol</span>
            <span className={cn("font-num text-2xs font-medium", volHigh && "text-foreground")}>
              {vol != null ? `${vol.toFixed(1)}x` : "\u2014"}
            </span>
          </div>
        )}
        {extra?.vs_xle_5d != null && (
          <div className="flex-1 flex items-center justify-center gap-1 py-1.5">
            <span className="text-[10px] text-muted-foreground">vs Bench</span>
            <RetVal v={extra.vs_xle_5d} className="font-medium" />
          </div>
        )}
      </div>

      {/* Verdict / Decay */}
      <div className="px-4 py-1.5 border-t border-border">
        <p className="text-2xs text-muted-foreground">
          {extra && (
            <>
              {supports && "Supports hypothesis \u2014 "}
              {contradicts && "Contradicts hypothesis \u2014 "}
              {!supports && !contradicts && "Inconclusive \u2014 "}
            </>
          )}
          {ticker.return_5d != null && ticker.return_5d > 0 ? "up" : ticker.return_5d != null && ticker.return_5d < 0 ? "down" : "flat"}{" "}
          <RetVal v={ticker.return_5d} /> over 5 days
          {volHigh && <>, elevated volume ({vol?.toFixed(1)}x avg)</>}
          {extra?.vs_xle_5d != null && (
            <>, <RetVal v={extra.vs_xle_5d} /> relative to sector</>
          )}
          {moverExtra?.decay && moverExtra.decay !== "Unknown" && (
            <> · Shock trajectory: {moverExtra.decay.toLowerCase()}
              {moverExtra.decay_evidence && <> ({moverExtra.decay_evidence})</>}
            </>
          )}
        </p>
      </div>

      {/* Related headlines */}
      {hasHeadlines && (
        <div className="border-t border-border px-4 py-2 space-y-1">
          <span className="text-[10px] font-medium uppercase tracking-widest text-muted-foreground">
            Related headlines
          </span>
          {headlines!.map((h, i) => (
            <div key={i} className="flex items-baseline gap-2 text-xs text-muted-foreground">
              <span className="shrink-0 font-num text-[10px]">
                {h.source_count > 1 ? `${h.source_count}src` : ""}
              </span>
              <span className="leading-snug">{h.headline}</span>
            </div>
          ))}
        </div>
      )}
      {!hasHeadlines && !headlines && (
        <div className="border-t border-border px-4 py-2">
          <span className="text-[10px] text-muted-foreground/60">No related headlines found</span>
        </div>
      )}
    </div>
  );
}
