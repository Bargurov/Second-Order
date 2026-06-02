import { cn } from "@/lib/utils";
import type { AnalyzeResponse, Ticker } from "@/lib/api";

// ---------------------------------------------------------------------------
// Evidence-quality computation — pure functions, no API calls.
// ---------------------------------------------------------------------------

export interface QualitySignal {
  label: string;
  value: string;
  tone: "positive" | "neutral" | "warn";
}

function isSupporting(t: Ticker): boolean {
  return (
    t.direction_tag === "supporting" ||
    (t.direction_tag?.startsWith("supports") ?? false)
  );
}
function isContradicting(t: Ticker): boolean {
  return (
    t.direction_tag === "contradicting" ||
    (t.direction_tag?.startsWith("contradicts") ?? false)
  );
}

/** Build the array of quality signals from a completed analysis response. */
export function buildQualitySignals(result: AnalyzeResponse): QualitySignal[] {
  const signals: QualitySignal[] = [];
  const tickers = result.market?.tickers ?? [];

  // 1. Market tape-alignment ratio (supporting vs contradicting tickers) —
  //    "Aligned", not "Confirmed": tape direction agreement is descriptive,
  //    not thesis confirmation or event-study inference.
  if (tickers.length > 0) {
    const supporting = tickers.filter(isSupporting).length;
    const contradicting = tickers.filter(isContradicting).length;
    const assessed = supporting + contradicting;
    if (assessed > 0) {
      const ratio = supporting / assessed;
      const pct = Math.round(ratio * 100);
      signals.push({
        label: "Aligned",
        value: `${pct}%`,
        tone: ratio >= 0.6 ? "positive" : ratio >= 0.3 ? "neutral" : "warn",
      });
    } else {
      signals.push({ label: "Aligned", value: "—", tone: "neutral" });
    }
  }

  // 2. Ticker depth
  if (tickers.length > 0) {
    const withData = tickers.filter(
      (t) => t.return_5d != null && t.label !== "needs more evidence",
    ).length;
    signals.push({
      label: "Tickers",
      value: `${withData}/${tickers.length}`,
      tone: withData >= 3 ? "positive" : withData >= 1 ? "neutral" : "warn",
    });
  }

  // 3. Analog coverage
  const analogCount = result.analysis?.historical_analogs?.length ?? 0;
  signals.push({
    label: "Analogs",
    value: analogCount > 0 ? `${analogCount}` : "none",
    tone: analogCount >= 2 ? "positive" : analogCount === 1 ? "neutral" : "warn",
  });

  // 4. Market freshness
  const staleness = result.market?.market_check_staleness;
  const checkAt = result.market?.last_market_check_at;
  if (staleness === "frozen") {
    signals.push({ label: "Data", value: "frozen", tone: "warn" });
  } else if (staleness === "error") {
    signals.push({ label: "Data", value: "error", tone: "warn" });
  } else if (checkAt) {
    const ago = minutesAgo(checkAt);
    signals.push({
      label: "Data",
      value: ago <= 1 ? "live" : `${ago}m ago`,
      tone: ago <= 30 ? "positive" : ago <= 120 ? "neutral" : "warn",
    });
  }

  // 5. Frozen-archive flag
  if (result.freshness?.is_frozen) {
    signals.push({ label: "Archive", value: "frozen", tone: "warn" });
  }

  return signals;
}

/** Minutes between an ISO timestamp and now, floored to 0. */
export function minutesAgo(iso: string): number {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return 999;
  return Math.max(0, Math.round((Date.now() - then) / 60_000));
}

// ---------------------------------------------------------------------------
// Tone → colour mapping using the existing design-system tokens.
// ---------------------------------------------------------------------------

const TONE_CLASSES: Record<
  QualitySignal["tone"],
  { dot: string; value: string }
> = {
  positive: { dot: "bg-primary/70", value: "text-primary" },
  neutral: { dot: "bg-on-surface-variant/30", value: "text-on-surface-variant" },
  warn: { dot: "bg-error-dim/60", value: "text-error-dim" },
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function EvidenceQualityStrip({
  result,
}: {
  result: AnalyzeResponse;
}) {
  const signals = buildQualitySignals(result);
  if (signals.length === 0) return null;

  return (
    <div
      className={cn(
        "flex items-center gap-px rounded-lg overflow-hidden",
        "bg-surface-container-highest/50",
        "h-7",
      )}
    >
      {signals.map((s, i) => {
        const tone = TONE_CLASSES[s.tone];
        return (
          <div
            key={s.label}
            className={cn(
              "flex items-center gap-1.5 px-3 h-full",
              "bg-surface-container-highest/60",
              i > 0 && "border-l border-outline-variant/10",
            )}
          >
            <span className={cn("w-1 h-1 rounded-full shrink-0", tone.dot)} />
            <span className="text-[9px] font-bold uppercase tracking-[0.08em] text-on-surface-variant/50">
              {s.label}
            </span>
            <span
              className={cn(
                "text-[10px] font-mono font-semibold tabular-nums",
                tone.value,
              )}
            >
              {s.value}
            </span>
          </div>
        );
      })}
    </div>
  );
}
