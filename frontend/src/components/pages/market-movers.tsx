import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Sparkline } from "@/components/ui/sparkline";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type MarketMover } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { TrendingUp, TrendingDown, Zap } from "lucide-react";

function pct(v: number | null): string {
  if (v == null) return "\u2014";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function MoverCard({ mover }: { mover: MarketMover }) {
  const mechanism = mover.mechanism_summary || "";
  const truncMech = mechanism.length > 120 ? mechanism.slice(0, 117) + "..." : mechanism;

  return (
    <Card className="shrink-0 w-[340px] md:w-auto md:shrink">
      <CardHeader className="pb-0">
        <div className="flex items-start gap-2">
          <CardTitle className="text-[13px] leading-snug line-clamp-2">
            {mover.headline}
          </CardTitle>
          <Badge variant="outline" className="shrink-0 font-num">
            {Math.round(mover.support_ratio * 100)}%
          </Badge>
        </div>
        {truncMech && (
          <p className="text-[11px] leading-relaxed text-muted-foreground mt-1 line-clamp-2">
            {truncMech}
          </p>
        )}
      </CardHeader>
      <CardContent className="pt-2">
        {/* Ticker chips */}
        <div className="flex flex-wrap gap-1.5">
          {mover.tickers.map((t) => {
            const up = t.return_5d != null && t.return_5d > 0;
            const down = t.return_5d != null && t.return_5d < 0;
            return (
              <div
                key={t.symbol}
                className="flex items-center gap-1.5 rounded-lg border border-border bg-secondary/40 px-2 py-1"
              >
                <span className="font-num text-xs font-semibold">{t.symbol}</span>
                {up && <TrendingUp className="h-3 w-3 val-pos" />}
                {down && <TrendingDown className="h-3 w-3 val-neg" />}
                <span className={cn(
                  "font-num text-[11px]",
                  up && "val-pos",
                  down && "val-neg",
                )}>
                  {pct(t.return_5d)}
                </span>
                {t.spark && t.spark.length > 2 && (
                  <Sparkline
                    data={t.spark}
                    width={32}
                    height={12}
                    direction={t.return_5d}
                  />
                )}
              </div>
            );
          })}
        </div>

        {/* Meta */}
        <div className="mt-2 flex items-center gap-2 text-[10px] text-muted-foreground">
          <Badge variant="outline">{mover.stage}</Badge>
          <Badge variant="outline">{mover.persistence}</Badge>
          <span className="font-num">{mover.event_date}</span>
        </div>
      </CardContent>
    </Card>
  );
}

export function MarketMovers() {
  const { data: movers, isLoading } = useQuery({
    queryKey: qk.marketMovers(),
    queryFn: () => api.marketMovers(),
    staleTime: 120_000, // 2 min
  });

  // Hide entirely when nothing qualifies or loading
  if (isLoading) {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Zap className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold">Market Movers</span>
        </div>
        <div className="flex gap-3 overflow-hidden">
          <Skeleton className="h-32 w-[340px] shrink-0 rounded-2xl" />
          <Skeleton className="h-32 w-[340px] shrink-0 rounded-2xl" />
        </div>
      </div>
    );
  }

  if (!movers || movers.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-dashed border-border px-4 py-3">
        <Zap className="h-3.5 w-3.5 text-muted-foreground/50" />
        <span className="text-xs text-muted-foreground">No confirmed market movers right now</span>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Zap className="h-3.5 w-3.5 text-amber-500" />
        <span className="text-xs font-semibold">Market Movers</span>
        <span className="text-[10px] text-muted-foreground">
          Events with confirmed &gt;3% ticker moves
        </span>
      </div>
      <div className="flex gap-3 overflow-x-auto pb-1 md:grid md:grid-cols-2 lg:grid-cols-3 md:overflow-visible">
        {movers.map((m) => (
          <MoverCard key={m.event_id} mover={m} />
        ))}
      </div>
    </div>
  );
}
