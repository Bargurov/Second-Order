/**
 * EventIntelligenceCard — reusable event card primitive.
 *
 * Abstracts the PersistentCard ("Still Moving Markets") and WeeklyCard
 * ("This Week's Moves") layouts into one component driven by `variant`.
 *
 *   variant="hero"    → bg-surface-container-low, full-height, trajectory badge
 *   variant="compact" → bg-surface-container-highest, dense, click-to-analyze
 */

import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { pct } from "@/lib/ticker-utils";
import type { MoverTicker } from "@/lib/api";

export interface EventIntelligenceCardProps {
  headline: string;
  tickers: MoverTicker[];
  /** 0–1 fraction of qualifying tickers whose direction matches the thesis. */
  supportRatio: number;
  /** Decay labels from tickers — used to derive trajectory in hero variant. */
  decays?: string[];
  anchorDate?: string | null;
  asOf?: string | null;
  /** Days since the originating event — badge shown in hero variant only. */
  daysAgo?: number;
  variant?: "hero" | "compact";
  onAnalyze?: () => void;
  className?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TRAJECTORY_MAP: Record<string, string> = {
  Accelerating: "Still Accelerating",
  Holding:      "Still Holding",
  Fading:       "Fading",
};

function deriveTrajectory(decays: string[]): string {
  for (const key of ["Accelerating", "Holding", "Fading"]) {
    if (decays.includes(key)) return TRAJECTORY_MAP[key]!;
  }
  return "Monitoring";
}

function TickerChip({ t, size }: { t: MoverTicker; size: "sm" | "xs" }) {
  const r5 = t.return_5d;
  return (
    <div
      className={cn(
        "flex items-center gap-2 shrink-0",
        size === "sm"
          ? "bg-surface-container-highest px-3 py-2 rounded-lg"
          : "bg-surface-container px-2 py-1 rounded",
      )}
    >
      <span
        className={cn(
          "font-bold text-white tracking-wider",
          size === "sm" ? "text-xs" : "text-[10px]",
        )}
      >
        {t.symbol}
      </span>
      {r5 != null && (
        <span
          className={cn(
            "font-bold tnum",
            size === "sm" ? "text-xs" : "text-[10px]",
            r5 > 0 ? "text-primary" : r5 < 0 ? "text-error-dim" : "text-on-surface-variant",
          )}
        >
          {pct(r5)}
        </span>
      )}
    </div>
  );
}

function AnchorFooter({
  anchorDate,
  asOf,
}: {
  anchorDate?: string | null;
  asOf?: string | null;
}) {
  if (!anchorDate && !asOf) return null;
  return (
    <div className="flex items-center justify-between gap-2 text-[9px] text-on-surface-variant/60 font-medium uppercase tracking-widest">
      {anchorDate ? (
        <span title="Forward returns measured from this anchor date">
          Anchor <span className="tnum text-on-surface-variant/80">{anchorDate}</span>
        </span>
      ) : (
        <span />
      )}
      {asOf && (
        <span title="Most recent provider refresh">
          As of <span className="tnum text-on-surface-variant/80">{asOf}</span>
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function EventIntelligenceCard({
  headline,
  tickers,
  supportRatio,
  decays = [],
  anchorDate,
  asOf,
  daysAgo,
  variant = "compact",
  onAnalyze,
  className,
}: EventIntelligenceCardProps) {
  const agreement = Math.round(supportRatio * 100);

  if (variant === "hero") {
    const trajectory = deriveTrajectory(decays);
    return (
      <div
        className={cn(
          "bg-surface-container-low rounded-xl p-6 flex flex-col justify-between transition-all",
          "shadow-[inset_0_0_0_1px_rgba(71,70,86,0.25),0_10px_15px_-3px_rgba(0,0,0,0.12)]",
          "hover:shadow-[inset_0_0_0_1px_rgba(71,70,86,0.5),0_10px_15px_-3px_rgba(0,0,0,0.15)]",
          className,
        )}
      >
        <div>
          <div className="flex justify-between items-start mb-4">
            {daysAgo != null && (
              <span className="bg-surface-container-highest text-on-surface-variant text-[10px] font-bold px-2 py-1 rounded tracking-widest uppercase">
                {daysAgo} DAYS AGO
              </span>
            )}
            <div
              className="text-right"
              title={`${agreement}% — fraction of qualifying tickers matching the hypothesis`}
            >
              <span className="text-xl font-bold text-primary tnum">{agreement}%</span>
              <p className="text-[10px] text-on-surface-variant uppercase font-bold tracking-widest">
                Agreement
              </p>
            </div>
          </div>
          <h3 className="text-lg font-headline font-bold text-white mb-6 leading-snug line-clamp-2">
            {headline}
          </h3>
        </div>
        <div className="space-y-4">
          <div className="flex items-center gap-3 overflow-x-auto pb-2">
            {tickers.slice(0, 4).map((t) => (
              <TickerChip key={t.symbol} t={t} size="sm" />
            ))}
          </div>
          <AnchorFooter anchorDate={anchorDate} asOf={asOf} />
          <div className="flex justify-between items-center pt-4 border-t border-outline-variant/20">
            <span className="bg-primary-container/20 text-primary text-[10px] font-bold px-2 py-1 rounded-full uppercase tracking-widest">
              {trajectory}
            </span>
            <button
              onClick={onAnalyze}
              className="text-on-surface-variant hover:text-primary transition-colors"
            >
              <ArrowRight className="h-[18px] w-[18px]" />
            </button>
          </div>
        </div>
      </div>
    );
  }

  // compact
  return (
    <div
      className={cn(
        "bg-surface-container-highest p-5 rounded-lg cursor-pointer transition-all",
        "shadow-[inset_0_0_0_1px_rgba(71,70,86,0.15)] hover:shadow-[inset_0_0_0_1px_rgba(71,70,86,0.4)]",
        className,
      )}
      onClick={onAnalyze}
    >
      <div className="flex justify-between items-start mb-4">
        <h3 className="text-sm font-bold text-white leading-tight pr-4 line-clamp-2">
          {headline}
        </h3>
        <span
          className="text-primary font-bold text-xs tnum shrink-0"
          title={`${agreement}% — fraction of qualifying tickers matching the hypothesis`}
        >
          {agreement}%
        </span>
      </div>
      <div className="flex flex-wrap gap-2 mb-3">
        {tickers.slice(0, 4).map((t) => (
          <TickerChip key={t.symbol} t={t} size="xs" />
        ))}
      </div>
      <AnchorFooter anchorDate={anchorDate} asOf={asOf} />
    </div>
  );
}
