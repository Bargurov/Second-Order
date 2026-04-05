import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { Activity } from "lucide-react";

const REGIME_STYLE: Record<string, { color: string; bg: string; dot: string }> = {
  "Calm":                   { color: "text-foreground/70", bg: "bg-secondary",         dot: "bg-emerald-500/60" },
  "Calm with Undercurrent": { color: "text-amber-700",     bg: "bg-amber-50",          dot: "bg-amber-500" },
  "Geopolitical Stress":    { color: "text-orange-700",    bg: "bg-orange-50",         dot: "bg-orange-500" },
  "Systemic Stress":        { color: "text-red-700",       bg: "bg-red-50",            dot: "bg-red-600" },
};

const SIGNAL_LABELS: Record<string, string> = {
  vix_elevated: "VIX elevated",
  term_inversion: "VIX term inverted",
  credit_widening: "Credit widening",
  safe_haven_bid: "Haven bid",
  breadth_deterioration: "Breadth weak",
};

export function StressStrip() {
  const { data, isLoading } = useQuery({
    queryKey: qk.stress(),
    queryFn: () => api.stress(),
    staleTime: 600_000, // 10 min
  });

  if (isLoading) {
    return <Skeleton className="h-8 w-full rounded-xl" />;
  }

  if (!data) return null;

  const style = REGIME_STYLE[data.regime] ?? REGIME_STYLE["Calm"]!;
  const activeSignals = Object.entries(data.signals)
    .filter(([, v]) => v)
    .map(([k]) => SIGNAL_LABELS[k] ?? k);

  return (
    <div className={cn(
      "flex items-center gap-2.5 rounded-xl border px-3.5 py-2",
      style.bg, "border-border",
    )}>
      <Activity className={cn("h-3.5 w-3.5 shrink-0", style.color)} />
      <div className="flex items-center gap-2 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className={cn("h-1.5 w-1.5 rounded-full", style.dot)} />
          <span className={cn("text-xs font-semibold", style.color)}>{data.regime}</span>
        </div>
        {activeSignals.length > 0 && (
          <span className="text-[10px] text-muted-foreground truncate">
            {activeSignals.join(" · ")}
          </span>
        )}
      </div>
      {data.raw.vix != null && (
        <span className="ml-auto shrink-0 font-num text-[10px] text-muted-foreground">
          VIX {data.raw.vix}
          {data.raw.vix_change_5d != null ? (
            <span className={cn(
              "ml-1",
              data.raw.vix_change_5d > 0 && "text-red-600",
              data.raw.vix_change_5d < 0 && "text-emerald-600",
            )}>
              {data.raw.vix_change_5d >= 0 ? "+" : ""}{data.raw.vix_change_5d.toFixed(1)}% 5d
            </span>
          ) : (
            <span className="ml-1 text-muted-foreground/50">n/a 5d</span>
          )}
        </span>
      )}
    </div>
  );
}
