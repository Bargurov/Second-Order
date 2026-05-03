/**
 * DegradedBanner — prominent dismissible alert strip for data-quality issues.
 *
 * Sits above page content when one or more data sources are stale / errored.
 * More assertive than DegradedDataNotice (which is a tiny inline badge);
 * use DegradedBanner when the issue affects the whole surface, not one field.
 *
 * Severity:
 *   "warn"  → muted coral border (provider error / stale feeds)
 *   "info"  → outline-variant border (degraded but non-critical)
 */

import { useState } from "react";
import { AlertTriangle, Info, X } from "lucide-react";
import { cn } from "@/lib/utils";

export interface DegradedBannerProps {
  /** Short one-line title — shown bold at the left. */
  title: string;
  /** Optional secondary sentence. */
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
    root:   "border-error-dim/25 bg-error-container/8",
    accent: "bg-error-dim",
    icon:   "text-error-dim/60",
    title:  "text-error-dim/90",
    detail: "text-on-surface-variant/70",
    chip:   "bg-error-container/20 text-error-dim/70",
  },
  info: {
    root:   "border-outline-variant/30 bg-surface-container-highest/50",
    accent: "bg-on-surface-variant/30",
    icon:   "text-on-surface-variant/50",
    title:  "text-on-surface-variant/80",
    detail: "text-on-surface-variant/55",
    chip:   "bg-surface-container-highest text-on-surface-variant/60",
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
  const Icon = severity === "warn" ? AlertTriangle : Info;

  const handleDismiss = () => {
    setDismissed(true);
    onDismiss?.();
  };

  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-3 rounded-lg border px-3.5 py-2.5",
        s.root,
        className,
      )}
    >
      {/* Left accent bar */}
      <span className={cn("mt-0.5 w-0.5 self-stretch rounded-full shrink-0", s.accent)} />

      <Icon className={cn("h-3 w-3 shrink-0 mt-[3px]", s.icon)} />

      <div className="min-w-0 flex-1">
        <p className={cn("text-[11px] font-bold leading-none", s.title)}>{title}</p>
        {detail && (
          <p className={cn("text-[10px] mt-1 leading-relaxed", s.detail)}>{detail}</p>
        )}
        {items && items.length > 0 && (
          <ul className="mt-2 flex flex-wrap gap-1">
            {items.map((item, i) => (
              <li
                key={i}
                className={cn(
                  "inline-flex items-center gap-1 text-[9px] font-medium px-1.5 py-px rounded",
                  s.chip,
                )}
              >
                <span className={cn("w-1 h-1 rounded-full shrink-0", s.accent)} />
                {item}
              </li>
            ))}
          </ul>
        )}
      </div>

      {onDismiss && (
        <button
          onClick={handleDismiss}
          aria-label="Dismiss"
          className="shrink-0 mt-0.5 text-on-surface-variant/30 hover:text-on-surface-variant/60 transition-colors"
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}
