import { cn } from "@/lib/utils";
import { Clock, Zap, Snowflake, AlertTriangle, RefreshCw } from "lucide-react";
import type { MarketResult, FreshnessBlock } from "@/lib/api";

// ---------------------------------------------------------------------------
// Pure status derivation — exported for tests.
// ---------------------------------------------------------------------------

export interface ValidationStatus {
  /** Short human label. */
  label: string;
  /** Tonal class key for styling. */
  tone: "live" | "refreshed" | "stale" | "frozen" | "error";
  /** How long ago the last check ran, in human-friendly form. */
  age: string | null;
  /** Extra context line (e.g. degraded quality explanation). */
  detail: string | null;
}

/**
 * Format a duration in minutes into a compact human string.
 * Exported for tests.
 */
export function formatAge(mins: number): string {
  if (mins <= 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

/**
 * Derive the validation status from market + freshness fields.
 *
 * All inputs are optional — degrades gracefully to null (no badge).
 */
export function deriveValidationStatus(
  market?: MarketResult | null,
  freshness?: FreshnessBlock | null,
  now?: number, // ms epoch, injectable for tests
): ValidationStatus | null {
  if (!market) return null;

  const staleness = market.market_check_staleness;
  const checkAt = market.last_market_check_at;
  const quality = market.data_quality;
  const qualityNote = market.data_quality_note;
  const isFrozen = freshness?.is_frozen ?? false;

  // 1. Error state — upstream failure
  if (staleness === "error") {
    return {
      label: "Data error",
      tone: "error",
      age: null,
      detail: qualityNote || "Upstream provider failed — showing last known data",
    };
  }

  // 2. Frozen archive
  if (staleness === "frozen" || isFrozen) {
    const ageDays = freshness?.event_age_days ?? market.event_age_days;
    return {
      label: "Archived",
      tone: "frozen",
      age: ageDays != null ? `${ageDays}d old` : null,
      detail: null,
    };
  }

  // Compute minutes since last check
  let mins: number | null = null;
  if (checkAt) {
    const then = new Date(checkAt).getTime();
    const ref = now ?? Date.now();
    if (!Number.isNaN(then)) {
      mins = Math.max(0, Math.round((ref - then) / 60_000));
    }
  }

  // 3. Just refreshed (stale_refreshed, legacy_refreshed, forced_refreshed)
  if (
    staleness === "stale_refreshed" ||
    staleness === "legacy_refreshed" ||
    staleness === "forced_refreshed"
  ) {
    const detail =
      quality === "degraded" && qualityNote
        ? qualityNote
        : staleness === "forced_refreshed"
          ? "Force-refreshed past freeze window"
          : null;
    return {
      label: "Refreshed",
      tone: "refreshed",
      age: mins != null ? formatAge(mins) : null,
      detail,
    };
  }

  // 4. Fresh cache hit
  if (staleness === "fresh") {
    const isRecent = mins != null && mins <= 30;
    const detail = quality === "degraded" && qualityNote ? qualityNote : null;
    return {
      label: isRecent ? "Live" : "Cached",
      tone: isRecent ? "live" : "stale",
      age: mins != null ? formatAge(mins) : null,
      detail,
    };
  }

  // 5. No staleness field but we have a timestamp — legacy path
  if (mins != null) {
    const detail = quality === "degraded" && qualityNote ? qualityNote : null;
    return {
      label: mins <= 30 ? "Live" : "Stale",
      tone: mins <= 30 ? "live" : "stale",
      age: formatAge(mins),
      detail,
    };
  }

  // 6. Nothing available
  return null;
}

// ---------------------------------------------------------------------------
// Tone → visual mapping (design-system tokens only)
// ---------------------------------------------------------------------------

const TONE_MAP: Record<
  ValidationStatus["tone"],
  {
    icon: React.ElementType;
    dot: string;
    text: string;
    bg: string;
  }
> = {
  live: {
    icon: Zap,
    dot: "bg-primary",
    text: "text-primary",
    bg: "bg-primary/8",
  },
  refreshed: {
    icon: RefreshCw,
    dot: "bg-primary/60",
    text: "text-primary/80",
    bg: "bg-primary/6",
  },
  stale: {
    icon: Clock,
    dot: "bg-on-surface-variant/40",
    text: "text-on-surface-variant",
    bg: "bg-on-surface-variant/6",
  },
  frozen: {
    icon: Snowflake,
    dot: "bg-[#7ba4c9]",
    text: "text-[#7ba4c9]",
    bg: "bg-[#7ba4c9]/8",
  },
  error: {
    icon: AlertTriangle,
    dot: "bg-error-dim",
    text: "text-error-dim",
    bg: "bg-error-dim/8",
  },
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MarketValidationStatus({
  market,
  freshness,
}: {
  market?: MarketResult | null;
  freshness?: FreshnessBlock | null;
}) {
  const status = deriveValidationStatus(market, freshness);
  if (!status) return null;

  const t = TONE_MAP[status.tone];
  const Icon = t.icon;

  return (
    <div className="flex items-center gap-2 min-w-0">
      <div
        className={cn(
          "inline-flex items-center gap-1.5 h-5 px-2 rounded-full shrink-0",
          t.bg,
        )}
      >
        <span className={cn("w-[5px] h-[5px] rounded-full shrink-0", t.dot)} />
        <Icon className={cn("w-2.5 h-2.5 shrink-0", t.text)} />
        <span className={cn("text-[9px] font-bold uppercase tracking-[0.08em] leading-none", t.text)}>
          {status.label}
        </span>
        {status.age && (
          <span className="text-[9px] font-mono tabular-nums text-on-surface-variant/35 leading-none">
            {status.age}
          </span>
        )}
      </div>
      {status.detail && (
        <span className="text-[9px] text-on-surface-variant/40 truncate min-w-0" title={status.detail}>
          {status.detail}
        </span>
      )}
    </div>
  );
}
