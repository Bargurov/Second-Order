import { cn } from "@/lib/utils";
import { AlertTriangle } from "lucide-react";
import type { MarketResult, AnalysisDetail, MarketContext } from "@/lib/api";

// ---------------------------------------------------------------------------
// Pure derivation — exported for tests.
// ---------------------------------------------------------------------------

export interface DegradedNotice {
  /** Short label — always present when notice fires. */
  label: string;
  /** Optional supporting detail line. */
  detail: string | null;
  /** Severity drives visual weight. */
  severity: "warn" | "info";
}

/**
 * Derive a degraded-data notice from market + analysis fields.
 *
 * Returns null when everything is healthy — the component renders nothing.
 * Multiple signals are merged into one concise notice (no stacking).
 */
export function deriveDegradedNotice(
  market?: MarketResult | null,
  analysis?: AnalysisDetail | null,
): DegradedNotice | null {
  // Priority 1: market data quality is degraded (most visible impact)
  if (market?.data_quality === "degraded") {
    return {
      label: "Partial market data",
      detail: market.data_quality_note || null,
      severity: "warn",
    };
  }

  // Priority 2: analysis was degraded (missing overlays/context)
  if (analysis?.degraded) {
    const warnings = analysis.validation_warnings;
    const detail = warnings && warnings.length > 0
      ? warnings.length === 1
        ? warnings[0] ?? null
        : `${warnings.length} validation issues`
      : null;
    return {
      label: "Partial analysis",
      detail,
      severity: "info",
    };
  }

  // Priority 3: validation warnings without the degraded flag
  if (analysis?.validation_warnings && analysis.validation_warnings.length > 0) {
    return {
      label: "Data caveats",
      detail: analysis.validation_warnings.length === 1
        ? analysis.validation_warnings[0] ?? null
        : `${analysis.validation_warnings.length} items`,
      severity: "info",
    };
  }

  // Priority 4: all tickers lack return data
  if (market && market.tickers.length > 0) {
    const withData = market.tickers.filter(
      (t) => t.return_5d != null && t.label !== "needs more evidence",
    ).length;
    if (withData === 0) {
      return {
        label: "No ticker data",
        detail: "All tickers returned without price data",
        severity: "warn",
      };
    }
  }

  return null;
}

/**
 * Derive a degraded-data notice from MarketContext (overview page).
 *
 * Checks snapshot staleness and provider availability signals.
 */
export function deriveContextDegradedNotice(
  ctx?: MarketContext | null,
): DegradedNotice | null {
  if (!ctx) return null;

  const { stale, unavailable, total } = ctx.snapshots_meta;

  // Many snapshots unavailable — provider may be down
  if (total > 0 && unavailable > total / 2) {
    return {
      label: "Provider issues",
      detail: `${unavailable}/${total} snapshots unavailable`,
      severity: "warn",
    };
  }

  // Majority of snapshots stale
  if (total > 0 && stale > total / 2) {
    return {
      label: "Stale snapshots",
      detail: `${stale}/${total} benchmarks outdated`,
      severity: "info",
    };
  }

  // Stress or rates data unavailable
  if (ctx.stress && ctx.stress.available === false && ctx.rates && ctx.rates.available === false) {
    return {
      label: "Limited context",
      detail: "Stress & rates data unavailable",
      severity: "info",
    };
  }

  return null;
}

// ---------------------------------------------------------------------------
// Severity → colour mapping (design-system tokens)
// ---------------------------------------------------------------------------

const SEV = {
  warn: {
    border: "border-error-dim/20",
    bg: "bg-error-container/10",
    icon: "text-error-dim/60",
    label: "text-error-dim/80",
    detail: "text-error-dim/40",
  },
  info: {
    border: "border-on-surface-variant/10",
    bg: "bg-surface-container-highest/50",
    icon: "text-on-surface-variant/40",
    label: "text-on-surface-variant/70",
    detail: "text-on-surface-variant/40",
  },
};

// ---------------------------------------------------------------------------
// Component — renders inline, 24px tall, or null.
// ---------------------------------------------------------------------------

export function DegradedDataNotice({
  market,
  analysis,
  className,
}: {
  market?: MarketResult | null;
  analysis?: AnalysisDetail | null;
  className?: string;
}) {
  const notice = deriveDegradedNotice(market, analysis);
  if (!notice) return null;

  const s = SEV[notice.severity];

  return (
    <div
      className={cn(
        "flex items-center gap-2 px-3 h-6 rounded-md border",
        s.border,
        s.bg,
        className,
      )}
      data-testid="degraded-notice"
    >
      <AlertTriangle className={cn("w-3 h-3 shrink-0", s.icon)} />
      <span className={cn("text-[9px] font-bold uppercase tracking-[0.08em] leading-none", s.label)}>
        {notice.label}
      </span>
      {notice.detail && (
        <>
          <span className="text-on-surface-variant/15 text-[9px]">/</span>
          <span
            className={cn("text-[9px] leading-none truncate min-w-0", s.detail)}
            title={notice.detail}
          >
            {notice.detail}
          </span>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Context variant — for Market Overview (MarketContext instead of MarketResult).
// ---------------------------------------------------------------------------

export function DegradedContextNotice({
  ctx,
  className,
}: {
  ctx?: MarketContext | null;
  className?: string;
}) {
  const notice = deriveContextDegradedNotice(ctx);
  if (!notice) return null;

  const s = SEV[notice.severity];

  return (
    <div
      className={cn(
        "flex items-center gap-2 px-3 h-6 rounded-md border",
        s.border,
        s.bg,
        className,
      )}
      data-testid="degraded-context-notice"
    >
      <AlertTriangle className={cn("w-3 h-3 shrink-0", s.icon)} />
      <span className={cn("text-[9px] font-bold uppercase tracking-[0.08em] leading-none", s.label)}>
        {notice.label}
      </span>
      {notice.detail && (
        <>
          <span className="text-on-surface-variant/15 text-[9px]">/</span>
          <span
            className={cn("text-[9px] leading-none truncate min-w-0", s.detail)}
            title={notice.detail}
          >
            {notice.detail}
          </span>
        </>
      )}
    </div>
  );
}
