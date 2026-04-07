import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type StressComponentDetail, type StressRegime } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { ChevronDown } from "lucide-react";

// ---------------------------------------------------------------------------
// Status dot colour — matches Stitch reference exactly
// ---------------------------------------------------------------------------

function statusDot(status: string): string {
  if (status === "stressed") return "bg-error";
  if (status === "watch") return "bg-[#facc15]";
  return "bg-primary";
}

// Regime dot + label colour
function regimeColor(regime: string): { dot: string; text: string; badge: string; badgeBorder: string } {
  if (regime.toLowerCase().includes("systemic") || regime.toLowerCase().includes("stress")) {
    return { dot: "bg-error", text: "text-error", badge: "bg-error-container/20", badgeBorder: "border-error-dim/30" };
  }
  if (regime.toLowerCase().includes("undercurrent") || regime.toLowerCase().includes("watch")) {
    return { dot: "bg-[#facc15]", text: "text-[#facc15]", badge: "bg-[#facc15]/10", badgeBorder: "border-[#facc15]/30" };
  }
  return { dot: "bg-primary", text: "text-primary", badge: "bg-primary-container/20", badgeBorder: "border-primary/30" };
}

// ---------------------------------------------------------------------------
// Indicator card — matches Stitch reference: bg-surface-container-highest p-4
// ---------------------------------------------------------------------------

function IndicatorCard({ detail }: { detail: StressComponentDetail }) {
  const [open, setOpen] = useState(false);
  const dot = statusDot(detail.status);

  // Build value line
  let valueLine = "";
  let subLine = "";
  if (detail.label === "Volatility" || detail.label === "VIX") {
    valueLine = detail.value != null ? `VIX ${detail.value}` : "";
    subLine = detail.avg20 != null ? `vs 20d avg ${detail.avg20}` : "";
  } else if (detail.label === "Term Structure") {
    valueLine = detail.value != null && detail.vix3m != null
      ? `Ratio ${(detail.value / detail.vix3m).toFixed(2)}`
      : detail.value != null ? `${detail.value}` : "";
    subLine = detail.vix3m != null ? "VIX / VIX3M" : "";
  } else if (detail.label === "Credit Stress" || detail.label === "Credit") {
    valueLine = "HYG/SHY";
    subLine = detail.spread_5d != null ? `5d: ${detail.spread_5d >= 0 ? "+" : ""}${detail.spread_5d.toFixed(2)}%` : "";
  } else if (detail.label === "Safe Haven" || detail.label === "Safe Havens") {
    valueLine = "Gold/DXY/TLT";
    subLine = detail.inflow_count != null ? `${detail.inflow_count} of 3 in safety mode` : "";
  } else if (detail.label === "Breadth" || detail.label === "Market Breadth") {
    valueLine = "RSP / SPY";
    subLine = detail.gap_5d != null ? `Gap 5d: ${detail.gap_5d >= 0 ? "+" : ""}${detail.gap_5d.toFixed(2)}%` : "";
  } else {
    valueLine = detail.value != null ? String(detail.value) : "";
  }

  // Expanded detail lines
  const detailLines: string[] = [];
  if (detail.value != null && detail.avg20 != null)
    detailLines.push(`Current: ${detail.value}  |  20d avg: ${detail.avg20}`);
  if (detail.change_5d != null)
    detailLines.push(`5d change: ${detail.change_5d >= 0 ? "+" : ""}${detail.change_5d.toFixed(2)}%`);
  if (detail.vix3m != null)
    detailLines.push(`VIX3M (3-month): ${detail.vix3m}`);
  if (detail.spread_5d != null)
    detailLines.push(`Credit spread 5d: ${detail.spread_5d >= 0 ? "+" : ""}${detail.spread_5d.toFixed(2)}%`);
  if (detail.gap_5d != null)
    detailLines.push(`Breadth gap 5d: ${detail.gap_5d >= 0 ? "+" : ""}${detail.gap_5d.toFixed(2)}%`);
  if (detail.assets) {
    const assetLines = Object.entries(detail.assets)
      .map(([name, val]) => `${name}: ${val != null ? `${val >= 0 ? "+" : ""}${val.toFixed(2)}%` : "n/a"}`)
      .join("  |  ");
    detailLines.push(assetLines);
  }
  if (detail.inflow_count != null)
    detailLines.push(`Safe havens with inflows: ${detail.inflow_count} of 3`);

  return (
    <button
      onClick={() => setOpen((o) => !o)}
      className="bg-surface-container-highest p-4 text-left w-full"
    >
      <div className="flex justify-between items-start mb-2">
        <span className="text-[10px] text-on-surface-variant font-bold uppercase tracking-wider">
          {detail.label}
        </span>
        <div className={cn("w-2 h-2 rounded-full shrink-0", dot)} />
      </div>
      {valueLine && (
        <div className="text-xl font-bold tnum text-on-surface">{valueLine}</div>
      )}
      {subLine && (
        <div className="text-[10px] text-on-surface-variant mb-3 italic">{subLine}</div>
      )}
      <p className="text-[11px] text-on-surface-variant leading-tight">{detail.explanation}</p>

      {/* Expanded detail */}
      <div className={cn(
        "overflow-hidden transition-all duration-200 ease-in-out",
        open ? "max-h-40 opacity-100 mt-3" : "max-h-0 opacity-0",
      )}>
        {detailLines.length > 0 && (
          <div className="border-t border-outline-variant/20 pt-2 space-y-0.5">
            {detailLines.map((line, i) => (
              <p key={i} className="font-num text-[10px] text-on-surface-variant">{line}</p>
            ))}
          </div>
        )}
      </div>
      {detailLines.length > 0 && (
        <ChevronDown className={cn(
          "h-3 w-3 text-on-surface-variant/40 mt-1 mx-auto transition-transform duration-200",
          open && "rotate-180",
        )} />
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Two-column Uncertainty section — matches Stitch reference exactly
// ---------------------------------------------------------------------------

interface UncertaintySectionProps {
  /** When provided (parent-driven), this stress regime is rendered directly
   *  and no internal fetch is made.  When omitted (standalone usage), the
   *  component falls back to its own /stress query for backward compat. */
  stress?: StressRegime | null;
  isLoading?: boolean;
}

export function UncertaintySection({ stress, isLoading: parentLoading }: UncertaintySectionProps = {}) {
  // Parent-provided data takes precedence; only fetch when nothing was passed in.
  const enabled = stress === undefined;
  const { data: fetched, isLoading: fetchedLoading } = useQuery({
    queryKey: qk.stress(),
    queryFn: () => api.stress(),
    staleTime: 600_000,
    enabled,
  });

  const data = enabled ? fetched : (stress ?? undefined);
  const isLoading = enabled ? fetchedLoading : (parentLoading ?? false);

  if (isLoading) {
    return (
      <section className="mt-4 mb-8">
        <div className="bg-surface-container-low rounded-xl p-6 shadow-2xl border border-outline-variant/20">
          <div className="flex flex-col lg:flex-row gap-8 items-start">
            <div className="lg:w-1/4 shrink-0 space-y-3">
              <Skeleton className="h-6 w-24 bg-surface-container-highest" />
              <Skeleton className="h-10 w-48 bg-surface-container-highest" />
              <Skeleton className="h-12 w-full bg-surface-container-highest" />
            </div>
            <div className="flex-1 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-px bg-outline-variant/20 rounded-lg overflow-hidden">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-32 bg-surface-container-highest" />
              ))}
            </div>
          </div>
        </div>
      </section>
    );
  }

  if (!data) return null;

  const rc = regimeColor(data.regime);
  const detail = data.detail ?? {};
  const detailKeys = ["volatility", "term_structure", "credit", "safe_haven", "breadth"] as const;

  // Short label for regime
  const regimeLabel = data.regime.toUpperCase();

  return (
    <section className="mt-4 mb-8">
      <div className="bg-surface-container-low rounded-xl p-6 shadow-2xl border border-outline-variant/20 relative overflow-hidden">
        {/* Carbon fibre texture */}
        <div className="absolute inset-0 opacity-5 pointer-events-none carbon-texture" />

        <div className="flex flex-col lg:flex-row gap-8 items-start relative z-10">
          {/* Left Badge — lg:w-1/4 */}
          <div className="lg:w-1/4 shrink-0">
            <div className={cn(
              "inline-flex items-center gap-2 px-3 py-1 rounded-full border",
              rc.badge, rc.badgeBorder,
            )}>
              <span className="relative flex h-2.5 w-2.5">
                <span className={cn("animate-ping absolute inline-flex h-full w-full rounded-full opacity-75", rc.dot)} />
                <span className={cn("relative inline-flex rounded-full h-2.5 w-2.5", rc.dot)} />
              </span>
              <span className={cn("font-bold text-xs tracking-widest uppercase", rc.text)}>{regimeLabel}</span>
            </div>
            <h2 className="text-3xl font-headline font-extrabold mt-4 tracking-tighter leading-tight text-white">
              Uncertainty &amp; Market Instability
            </h2>
            {data.summary && (
              <p className="text-on-surface-variant text-sm mt-3 leading-relaxed">{data.summary}</p>
            )}
          </div>

          {/* Right — 5 indicator cards in gap-px grid */}
          <div className="flex-1 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-px bg-outline-variant/20 rounded-lg overflow-hidden">
            {detailKeys.map((k) => {
              const d = detail[k];
              if (!d) return null;
              return <IndicatorCard key={k} detail={d} />;
            })}
          </div>
        </div>
      </div>
    </section>
  );
}

export { UncertaintySection as StressStrip };
