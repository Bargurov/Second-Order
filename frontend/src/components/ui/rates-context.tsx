import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type RatesContext as RatesContextType } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";

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

function fmtChange(v: number | null | undefined): string {
  if (v == null) return "\u2014";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

// ---------------------------------------------------------------------------
// Full strip — for Analysis results
// ---------------------------------------------------------------------------

export function RatesContextStrip() {
  const { data, isLoading } = useQuery({
    queryKey: qk.ratesContext(),
    queryFn: () => api.ratesContext(),
    staleTime: 600_000,
  });

  if (isLoading) return <Skeleton className="h-10 w-full rounded-xl" />;
  if (!data) return null;

  const style = REGIME_STYLE[data.regime] ?? REGIME_STYLE["Mixed"]!;
  const entries = [data.nominal, data.real_proxy, data.breakeven_proxy];

  return (
    <div className={cn(
      "flex items-center gap-4 rounded-xl border px-4 py-2.5",
      style.bg, style.border,
    )}>
      <span className={cn("text-xs font-bold shrink-0", style.color)}>
        {data.regime}
      </span>
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
  const { data } = useQuery({
    queryKey: qk.ratesContext(),
    queryFn: () => api.ratesContext(),
    staleTime: 600_000,
  });

  if (!data || data.regime === "Mixed") return null;

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
