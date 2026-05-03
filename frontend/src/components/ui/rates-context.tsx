import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type RatesContext } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { AlertTriangle } from "lucide-react";
import { deriveRatesDegraded } from "@/lib/macro-degraded";

const REGIME_STYLE: Record<string, { color: string; bg: string; border: string }> = {
  "Inflation pressure":      { color: "text-gray-400",      bg: "bg-secondary/30",  border: "border-border" },
  "Real-rate tightening":    { color: "text-red-400",       bg: "bg-red-950/30",    border: "border-red-800/40" },
  "Risk-off / growth scare": { color: "text-blue-400",      bg: "bg-blue-950/30",   border: "border-blue-800/40" },
  "Mixed":                   { color: "text-foreground/60",  bg: "bg-secondary/50",  border: "border-border" },
};

/** Short plain-language explanations for each rate metric. */
const ENTRY_HINTS: Record<string, string> = {
  "10Y yield":               "Nominal borrowing cost",
  "TIP (real yield proxy)":  "Inflation-adj. yield",
  "Breakeven proxy":         "Inflation expectation",
};

type RatesContextWithAvailability = RatesContext & { available?: boolean };

function fmtChange(v: number | null | undefined): string {
  if (v == null) return "\u2014";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function ratesUnavailable(data: RatesContextWithAvailability | null | undefined): boolean {
  if (!data) return true;
  if (data.available === true) return false;
  if (data.available === false) return true;
  const entries = [data.nominal, data.real_proxy, data.breakeven_proxy];
  return entries.every((e) => e.value == null && e.change_5d == null);
}

function RatesUnavailable({ compact = false }: { compact?: boolean }) {
  if (compact) {
    return (
      <span className="inline-flex items-center gap-1 text-[9px] font-medium px-1.5 py-0.5 rounded border bg-error-container/10 text-error-dim/70 border-error-dim/25">
        Rates unavailable
      </span>
    );
  }

  return (
    <div className="flex items-center gap-2 rounded-xl border border-error-dim/25 bg-error-container/10 px-4 py-2.5">
      <AlertTriangle className="h-3 w-3 text-error-dim/60 shrink-0" />
      <span className="text-xs font-bold text-error-dim/80 shrink-0">
        Rates unavailable
      </span>
      <span className="text-[10px] text-on-surface-variant/65">
        No live rates values are available.
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Full strip — for Analysis results
// ---------------------------------------------------------------------------

export function RatesContextStrip() {
  const { data, isLoading, isError } = useQuery<RatesContextWithAvailability>({
    queryKey: qk.ratesContext(),
    queryFn: () => api.ratesContext(),
    staleTime: 600_000,
  });

  if (isLoading) return <Skeleton className="h-10 w-full rounded-xl" />;
  if (isError || !data || ratesUnavailable(data)) return <RatesUnavailable />;

  const style = REGIME_STYLE[data.regime] ?? REGIME_STYLE["Mixed"]!;
  const entries = [data.nominal, data.real_proxy, data.breakeven_proxy];
  const degraded = deriveRatesDegraded(data);

  return (
    <div className={cn(
      "flex items-center gap-4 rounded-xl border px-4 py-2.5",
      style.bg, style.border,
    )}>
      <span className={cn("text-xs font-bold shrink-0", style.color)}>
        {data.regime}
      </span>
      {degraded && (
        <span className="flex items-center gap-1 shrink-0">
          <AlertTriangle className="h-3 w-3 text-error-dim/60" />
          <span className="text-[9px] text-error-dim/60">{degraded}</span>
        </span>
      )}
      <div className="flex items-center gap-4 overflow-x-auto text-[10px] text-muted-foreground">
        {entries.map((e) => {
          const chg = e.change_5d;
          const hint = ENTRY_HINTS[e.label];
          return (
            <div key={e.label} className="flex flex-col shrink-0">
              {hint && (
                <span className="text-[9px] text-muted-foreground/60 leading-none mb-0.5">{hint}</span>
              )}
              <div className="flex items-center gap-1">
                <span className="font-semibold text-foreground/70">{e.label}</span>
                {e.value != null && <span className="font-num">{e.value}</span>}
                <span className={cn(
                  "font-num font-medium",
                  chg != null && chg > 0 && "val-pos",
                  chg != null && chg < 0 && "val-neg",
                )}>
                  {fmtChange(chg)} 5d
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Compact inline — for Market Mover cards
// ---------------------------------------------------------------------------

export function RatesContextCompact() {
  const { data, isError } = useQuery<RatesContextWithAvailability>({
    queryKey: qk.ratesContext(),
    queryFn: () => api.ratesContext(),
    staleTime: 600_000,
  });

  if (isError || !data || ratesUnavailable(data)) return <RatesUnavailable compact />;
  if (data.regime === "Mixed") return null;

  const style = REGIME_STYLE[data.regime] ?? REGIME_STYLE["Mixed"]!;
  const nomChg = data.nominal.change_5d;
  const tipChg = data.real_proxy.change_5d;

  return (
    <span className={cn(
      "inline-flex items-center gap-1 text-[9px] font-medium px-1.5 py-0.5 rounded border",
      style.bg, style.color, style.border,
    )}>
      {data.regime}
      {nomChg != null && (
        <span className="font-num text-[8px] opacity-70">
          10Y {fmtChange(nomChg)}
        </span>
      )}
      {tipChg != null && (
        <span className="font-num text-[8px] opacity-70">
          TIP {fmtChange(tipChg)}
        </span>
      )}
    </span>
  );
}
