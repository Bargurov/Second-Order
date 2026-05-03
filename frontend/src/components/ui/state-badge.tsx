import { cn } from "@/lib/utils";

export type BadgeVariant =
  | "calm"
  | "elevated"
  | "stress"
  | "positive"
  | "negative"
  | "warning"
  | "live"
  | "offline"
  | "neutral"
  | "pending"
  // Validation-status pills used by mover / analysis surfaces — paired
  // with the design package's "Real-Time Market Validation" cards.
  // Confirmed = thesis-aligned alpha or aligned beta; Inverted = the
  // ticker is moving against the thesis (alpha_contradicts /
  // beta_contradicts).  Distinct names from positive/negative so the
  // semantic intent is explicit at the call site.
  | "confirmed"
  | "inverted";

const VARIANT: Record<
  BadgeVariant,
  { dot: string; label: string; bg: string; ring: string }
> = {
  calm:      { dot: "bg-primary",             label: "text-primary",             bg: "bg-primary/10",          ring: "border-primary/25" },
  elevated:  { dot: "bg-amber-400",           label: "text-amber-300",           bg: "bg-amber-400/10",        ring: "border-amber-400/25" },
  stress:    { dot: "bg-destructive",         label: "text-destructive",         bg: "bg-destructive/10",      ring: "border-destructive/25" },
  positive:  { dot: "bg-primary",             label: "text-primary",             bg: "bg-primary/10",          ring: "border-primary/25" },
  negative:  { dot: "bg-destructive",         label: "text-destructive",         bg: "bg-destructive/10",      ring: "border-destructive/25" },
  warning:   { dot: "bg-amber-400",           label: "text-amber-300",           bg: "bg-amber-400/10",        ring: "border-amber-400/25" },
  live:      { dot: "bg-primary",             label: "text-muted-foreground",    bg: "bg-secondary",           ring: "border-border" },
  offline:   { dot: "bg-destructive",         label: "text-muted-foreground",    bg: "bg-secondary",           ring: "border-border" },
  neutral:   { dot: "bg-muted-foreground/50", label: "text-muted-foreground",    bg: "bg-secondary",           ring: "border-border" },
  pending:   { dot: "bg-muted-foreground/30", label: "text-muted-foreground/60", bg: "bg-secondary",           ring: "border-border" },
  confirmed: { dot: "bg-primary",             label: "text-primary",             bg: "bg-primary-container/40", ring: "border-primary/25" },
  inverted:  { dot: "bg-error-dim",           label: "text-error-dim",           bg: "bg-error-container/30",   ring: "border-error-dim/25" },
};

interface StateBadgeProps {
  variant?: BadgeVariant;
  label: string;
  pulsing?: boolean;
  className?: string;
}

export function StateBadge({
  variant = "neutral",
  label,
  pulsing = false,
  className,
}: StateBadgeProps) {
  const v = VARIANT[variant];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-[3px]",
        "text-[11px] font-semibold leading-none",
        v.bg,
        v.ring,
        v.label,
        className,
      )}
    >
      <span
        className={cn(
          "h-[5px] w-[5px] rounded-full shrink-0",
          v.dot,
          pulsing && "animate-pulse",
        )}
      />
      {label}
    </span>
  );
}
