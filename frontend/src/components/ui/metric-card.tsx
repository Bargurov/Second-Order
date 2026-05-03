/**
 * MetricCard — compact single-metric display primitive.
 *
 * Dense by default. Use in flex rows (e.g. TrackRecordStrip) or a grid
 * column of mini-stats. Mirrors the design-system tone palette:
 *
 *   tone="positive" → primary (teal)
 *   tone="warn"     → error-dim (coral)
 *   tone="neutral"  → on-surface/90 (default)
 *
 * Pass `accent` to override tone with an explicit Tailwind color class.
 */

import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { cn } from "@/lib/utils";

export interface MetricCardProps {
  /** Short label rendered below/after the value. */
  label: string;
  /** Numeric or string value displayed prominently. */
  value: string | number;
  /** Optional unit or sub-label appended after the value, quieter. */
  sub?: string;
  /** Explicit Tailwind color class — overrides `tone`. */
  accent?: string;
  /** Semantic tone driving value color when `accent` is absent. */
  tone?: "positive" | "warn" | "neutral";
  /** Renders a small directional arrow icon alongside the value. */
  trend?: "up" | "down" | "flat";
  className?: string;
}

const TONE: Record<"positive" | "warn" | "neutral", string> = {
  positive: "text-primary",
  warn:     "text-error-dim",
  neutral:  "text-on-surface/90",
};

export function MetricCard({
  label,
  value,
  sub,
  accent,
  tone = "neutral",
  trend,
  className,
}: MetricCardProps) {
  const valueClass = accent ?? TONE[tone];

  const TrendIcon =
    trend === "up" ? TrendingUp
    : trend === "down" ? TrendingDown
    : trend === "flat" ? Minus
    : null;

  return (
    <div className={cn("flex items-baseline gap-1.5 shrink-0", className)}>
      <span
        className={cn(
          "text-sm font-bold tabular-nums font-headline leading-none",
          valueClass,
        )}
      >
        {value}
      </span>

      {sub && (
        <span className="text-[8px] font-medium text-on-surface-variant/40 leading-none">
          {sub}
        </span>
      )}

      {TrendIcon && (
        <TrendIcon
          className={cn("w-2.5 h-2.5 shrink-0 self-center opacity-60", valueClass)}
        />
      )}

      <span className="text-[8px] font-bold uppercase tracking-[0.12em] text-on-surface-variant/35 leading-none">
        {label}
      </span>
    </div>
  );
}
