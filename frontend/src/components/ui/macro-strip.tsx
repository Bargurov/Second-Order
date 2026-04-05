import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";

function fmtVal(v: number | null, unit: string): string {
  if (v == null) return "\u2014";
  if (unit === "%") return `${v.toFixed(2)}%`;
  return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtChg(v: number | null): string {
  if (v == null) return "";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

const MIN_USEFUL = 2;

interface MacroStripProps {
  eventDate?: string | null;
}

export function MacroStrip({ eventDate }: MacroStripProps) {
  const dateKey = eventDate ?? undefined;

  const { data: entries = [], isLoading } = useQuery({
    queryKey: qk.macro(dateKey),
    queryFn: () => api.macro(dateKey),
    staleTime: 300_000,
  });

  const usable = entries.filter((e) => e.value != null);

  if (isLoading) {
    return (
      <div className="flex gap-1.5 overflow-x-auto pb-0.5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-9 w-16 shrink-0 rounded" />
        ))}
      </div>
    );
  }

  if (usable.length < MIN_USEFUL) return null;

  return (
    <div className="flex gap-1 overflow-x-auto pb-0.5">
      {usable.map((e) => (
        <div
          key={e.label}
          className="shrink-0 flex flex-col items-center rounded border border-border bg-card px-2 py-1 min-w-[3.5rem]"
        >
          <span className="text-2xs text-muted-foreground">{e.label}</span>
          <span className="font-num text-2xs font-medium">
            {fmtVal(e.value, e.unit)}
          </span>
          {e.change_5d != null && (
            <span className={cn(
              "font-num text-[10px]",
              e.change_5d > 0 && "val-pos",
              e.change_5d < 0 && "val-neg",
              e.change_5d === 0 && "val-flat",
            )}>
              {fmtChg(e.change_5d)}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
