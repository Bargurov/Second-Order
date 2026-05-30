/**
 * DegradedBanner — data-quality banner for the Analyze surface.
 *
 * Styled to the Direction-C `az-banner` rhythm (charcoal, hairline,
 * uppercase mono stamp + serif explanation).  Analyze-only; it renders
 * inside the `.az-canvas` scope, so the `--so-*` palette resolves.
 *
 * Severity:
 *   "warn"  → amber stamp (degraded / partial / held — kit: amber = held /
 *             incomplete / degraded)
 *   "info"  → slate stamp (non-critical)
 */

import { useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export interface DegradedBannerProps {
  /** Short one-line title — shown as the stamp at the left. */
  title: string;
  /** Optional secondary sentence (the serif explanation). */
  detail?: string;
  /** Specific stale/error sources — rendered as inline chips. */
  items?: string[];
  severity?: "warn" | "info";
  /** If provided, an ✕ button appears and calls this; also controls dismiss. */
  onDismiss?: () => void;
  className?: string;
}

const SEV = {
  warn: {
    root:  "border-[color:rgba(200,151,89,0.40)] bg-[rgba(200,151,89,0.05)]",
    stamp: "border-[color:var(--so-amber)] text-[var(--so-amber)]",
    chip:  "border-[color:rgba(200,151,89,0.35)] text-[var(--so-amber)]",
  },
  info: {
    root:  "border-[color:var(--so-rule-hi)] bg-[rgba(255,255,255,0.012)]",
    stamp: "border-[color:var(--so-rule-hi)] text-[var(--so-slate)]",
    chip:  "border-[color:var(--so-rule)] text-[var(--so-ink-3)]",
  },
} as const;

export function DegradedBanner({
  title,
  detail,
  items,
  severity = "warn",
  onDismiss,
  className,
}: DegradedBannerProps) {
  const [dismissed, setDismissed] = useState(false);
  if (dismissed) return null;

  const s = SEV[severity];

  const handleDismiss = () => {
    setDismissed(true);
    onDismiss?.();
  };

  return (
    <div
      role="alert"
      className={cn(
        "flex items-center gap-3.5 rounded-[4px] border px-3.5 py-2.5",
        s.root,
        className,
      )}
    >
      <span
        className={cn(
          "shrink-0 self-start rounded-[2px] border px-[7px] py-0.5 font-mono text-[10px] font-medium uppercase tracking-[0.16em]",
          s.stamp,
        )}
      >
        {title}
      </span>

      {detail && (
        <span className="min-w-0 flex-1 font-[family-name:var(--so-serif)] text-[12.5px] font-light italic leading-snug text-[var(--so-ink-2)]">
          {detail}
        </span>
      )}

      {items && items.length > 0 && (
        <span className="ml-auto flex shrink-0 flex-wrap gap-1">
          {items.map((item, i) => (
            <span
              key={i}
              className={cn(
                "rounded-[2px] border px-1.5 py-px font-mono text-[9px] uppercase tracking-[0.1em]",
                s.chip,
              )}
            >
              {item}
            </span>
          ))}
        </span>
      )}

      {onDismiss && (
        <button
          onClick={handleDismiss}
          aria-label="Dismiss"
          className="shrink-0 self-start text-[var(--so-ink-3)] transition-colors hover:text-[var(--so-ink-1)]"
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}
