import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type StressComponentDetail, type StressRegime, type SectorVolEntry, type NewsSectorUncertaintyEntry, type NewsUncertaintyConcentration, type FundingStressMode } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { ChevronDown, AlertTriangle } from "lucide-react";
import { deriveStressDegraded, deriveIndicatorDegraded } from "@/lib/macro-degraded";

// ---------------------------------------------------------------------------
// Status dot colour — matches Stitch reference exactly
// ---------------------------------------------------------------------------

function statusDot(status: string): string {
  if (status === "stressed") return "bg-error";
  if (status === "watch") return "bg-[#facc15]";
  return "bg-primary";
}

// Regime dot + label colour
function regimeColor(regime: string): { dot: string; text: string; badge: string; badgeBorder: string } {
  if (regime.toLowerCase().includes("systemic") || regime.toLowerCase().includes("stress")) {
    return { dot: "bg-error", text: "text-error", badge: "bg-error-container/20", badgeBorder: "border-error-dim/30" };
  }
  if (regime.toLowerCase().includes("undercurrent") || regime.toLowerCase().includes("watch")) {
    return { dot: "bg-[#facc15]", text: "text-[#facc15]", badge: "bg-[#facc15]/10", badgeBorder: "border-[#facc15]/30" };
  }
  return { dot: "bg-primary", text: "text-primary", badge: "bg-primary-container/20", badgeBorder: "border-primary/30" };
}

// ---------------------------------------------------------------------------
// Indicator card — matches Stitch reference: bg-surface-container-highest p-4
// ---------------------------------------------------------------------------

function IndicatorCard({ detail }: { detail: StressComponentDetail }) {
  const [open, setOpen] = useState(false);
  const dot = statusDot(detail.status);
  const degraded = deriveIndicatorDegraded(detail);

  // Build value line
  let valueLine = "";
  let subLine = "";
  if (detail.label === "Volatility" || detail.label === "VIX") {
    valueLine = detail.value != null ? `VIX ${detail.value}` : "";
    subLine = detail.avg20 != null ? `vs 20d avg ${detail.avg20}` : "";
  } else if (detail.label === "Term Structure") {
    valueLine = detail.value != null && detail.vix3m != null
      ? `Ratio ${(detail.value / detail.vix3m).toFixed(2)}`
      : detail.value != null ? `${detail.value}` : "";
    subLine = detail.vix3m != null ? "VIX / VIX3M" : "";
  } else if (detail.label === "Credit Stress" || detail.label === "Credit") {
    valueLine = "HYG/SHY";
    subLine = detail.spread_5d != null ? `5d: ${detail.spread_5d >= 0 ? "+" : ""}${detail.spread_5d.toFixed(2)}%` : "";
  } else if (detail.label === "Safe Haven" || detail.label === "Safe Havens") {
    valueLine = "Gold/DXY/TLT";
    subLine = detail.inflow_count != null ? `${detail.inflow_count} of 3 in safety mode` : "";
  } else if (detail.label === "Breadth" || detail.label === "Market Breadth") {
    valueLine = "RSP / SPY";
    subLine = detail.gap_5d != null ? `Gap 5d: ${detail.gap_5d >= 0 ? "+" : ""}${detail.gap_5d.toFixed(2)}%` : "";
  } else {
    valueLine = detail.value != null ? String(detail.value) : "";
  }

  // Expanded detail lines
  const detailLines: string[] = [];
  if (detail.value != null && detail.avg20 != null)
    detailLines.push(`Current: ${detail.value}  |  20d avg: ${detail.avg20}`);
  if (detail.change_5d != null)
    detailLines.push(`5d change: ${detail.change_5d >= 0 ? "+" : ""}${detail.change_5d.toFixed(2)}%`);
  if (detail.vix3m != null)
    detailLines.push(`VIX3M (3-month): ${detail.vix3m}`);
  if (detail.spread_5d != null)
    detailLines.push(`Credit spread 5d: ${detail.spread_5d >= 0 ? "+" : ""}${detail.spread_5d.toFixed(2)}%`);
  if (detail.gap_5d != null)
    detailLines.push(`Breadth gap 5d: ${detail.gap_5d >= 0 ? "+" : ""}${detail.gap_5d.toFixed(2)}%`);
  if (detail.assets) {
    const assetLines = Object.entries(detail.assets)
      .map(([name, val]) => `${name}: ${val != null ? `${val >= 0 ? "+" : ""}${val.toFixed(2)}%` : "n/a"}`)
      .join("  |  ");
    detailLines.push(assetLines);
  }
  if (detail.inflow_count != null)
    detailLines.push(`Safe havens with inflows: ${detail.inflow_count} of 3`);

  return (
    <button
      onClick={() => setOpen((o) => !o)}
      className="bg-surface-container-highest p-4 text-left w-full"
    >
      <div className="flex justify-between items-start mb-2">
        <span className="text-[10px] text-on-surface-variant font-bold uppercase tracking-wider">
          {detail.label}
        </span>
        <div className={cn("w-2 h-2 rounded-full shrink-0", dot)} />
      </div>
      {degraded ? (
        <div className="flex items-center gap-1 mt-1 mb-3">
          <AlertTriangle className="h-3 w-3 text-on-surface-variant/40 shrink-0" />
          <span className="text-[10px] text-on-surface-variant/50">{degraded}</span>
        </div>
      ) : (
        <>
          {valueLine && (
            <div className="text-xl font-bold tnum text-on-surface">{valueLine}</div>
          )}
          {subLine && (
            <div className="text-[10px] text-on-surface-variant mb-3 italic">{subLine}</div>
          )}
        </>
      )}
      <p className="text-[11px] text-on-surface-variant leading-tight">{detail.explanation}</p>

      {/* Expanded detail */}
      <div className={cn(
        "overflow-hidden transition-all duration-200 ease-in-out",
        open ? "max-h-40 opacity-100 mt-3" : "max-h-0 opacity-0",
      )}>
        {detailLines.length > 0 && (
          <div className="border-t border-outline-variant/20 pt-2 space-y-0.5">
            {detailLines.map((line, i) => (
              <p key={i} className="font-num text-[10px] text-on-surface-variant">{line}</p>
            ))}
          </div>
        )}
      </div>
      {detailLines.length > 0 && (
        <ChevronDown className={cn(
          "h-3 w-3 text-on-surface-variant/40 mt-1 mx-auto transition-transform duration-200",
          open && "rotate-180",
        )} />
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Sector pressure row — compact chip strip shown when concentration is
// "concentrated" or "mixed". Hidden when diffuse or unavailable.
// ---------------------------------------------------------------------------

function sectorDot(status: SectorVolEntry["status"]): string {
  if (status === "stressed") return "bg-error";
  if (status === "watch")    return "bg-[#facc15]";
  return "bg-primary";
}

function SectorPressureRow({ sectors, spyVol }: {
  sectors: SectorVolEntry[];
  spyVol: number | undefined;
}) {
  // Only show elevated sectors (watch + stressed) capped at 8
  const elevated = sectors.filter((s) => s.vol_ratio >= 1.3).slice(0, 8);
  if (elevated.length === 0) return null;

  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1.5">
      <span className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant/60 shrink-0">
        Sector vol
      </span>
      {spyVol !== undefined && (
        <span className="text-[10px] text-on-surface-variant/50 shrink-0 font-mono">
          SPY {spyVol.toFixed(1)}%
        </span>
      )}
      <span className="text-on-surface-variant/20 shrink-0 text-[10px]">·</span>
      <div className="flex flex-wrap gap-1.5">
        {elevated.map((s) => (
          <span
            key={s.etf}
            title={`${s.sector}: ${s.vol_20d.toFixed(1)}% vol (${s.vol_ratio.toFixed(2)}× SPY)`}
            className={cn(
              "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium font-mono",
              s.status === "stressed" && "bg-error/10 text-error",
              s.status === "watch"    && "bg-[#facc15]/10 text-[#facc15]",
            )}
          >
            <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", sectorDot(s.status))} />
            {s.etf}
            <span className="opacity-60">{s.vol_ratio.toFixed(2)}×</span>
          </span>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sector lead row — shown when news-derived uncertainty_scope === "sector".
// Displays up to 3 top-scoring sectors with optional vol corroboration badge.
// ---------------------------------------------------------------------------

function SectorLeadRow({
  topSectors,
  volSectors,
}: {
  topSectors: NewsSectorUncertaintyEntry[];
  volSectors?: SectorVolEntry[];
}) {
  const displayed = topSectors.slice(0, 3);
  if (displayed.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      {displayed.map((s) => {
        const volEntry = volSectors?.find(
          (v) => v.sector.toLowerCase() === s.sector.toLowerCase(),
        );
        const hasBadge = volEntry != null && volEntry.vol_ratio >= 1.3;
        const isHigh = s.high_fraction > 0.5;

        return (
          <span
            key={s.sector}
            title={`${s.sector} — score ${s.score}, ${s.cluster_count} clusters, ${Math.round(s.high_fraction * 100)}% high-uncertainty`}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium border",
              isHigh
                ? "bg-error/10 text-error border-error-dim/20"
                : "bg-surface-container-highest text-on-surface-variant border-outline-variant/20",
            )}
          >
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full shrink-0",
                isHigh ? "bg-error" : "bg-on-surface-variant/40",
              )}
            />
            <span className="capitalize">{s.sector}</span>
            {hasBadge && (
              <span className="text-primary/80 font-mono text-[10px] opacity-80">
                {volEntry!.vol_ratio.toFixed(2)}×
              </span>
            )}
          </span>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Funding stress mode pill — surfaces the orthogonal mode classifier
// already computed by /market-context (duration_shock / credit_widening /
// dollar_shortage / liquidity_squeeze).  Renders only when a mode is
// actually firing so the surface stays quiet under calm conditions.
// ---------------------------------------------------------------------------

const _FUNDING_MODE_LABEL: Record<FundingStressMode["primary_mode"], string> = {
  none:              "none",
  duration_shock:    "duration shock",
  credit_widening:   "credit widening",
  dollar_shortage:   "dollar shortage",
  liquidity_squeeze: "liquidity squeeze",
};

function fundingPillTone(severity: FundingStressMode["composite_severity"]): {
  bg: string; text: string; dot: string;
} {
  if (severity === "acute") {
    return { bg: "bg-error-container/20", text: "text-error",       dot: "bg-error" };
  }
  if (severity === "elevated") {
    return { bg: "bg-error-dim/15",       text: "text-error-dim",   dot: "bg-error-dim" };
  }
  if (severity === "mild") {
    return { bg: "bg-error-dim/10",       text: "text-error-dim/85", dot: "bg-error-dim/70" };
  }
  return { bg: "bg-surface-container-highest", text: "text-on-surface-variant/70", dot: "bg-on-surface-variant/40" };
}

function isFundingModeFiring(mode: FundingStressMode | null | undefined): mode is FundingStressMode {
  if (!mode || mode.available === false) return false;
  if (!mode.primary_mode || mode.primary_mode === "none") return false;
  if (!mode.composite_severity || mode.composite_severity === "none") return false;
  return true;
}

function FundingModePill({ funding }: { funding: FundingStressMode }) {
  const tone  = fundingPillTone(funding.composite_severity);
  const label = _FUNDING_MODE_LABEL[funding.primary_mode] ?? funding.primary_mode.replace(/_/g, " ");
  return (
    <div
      title={funding.rationale || undefined}
      className={cn("inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full", tone.bg)}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", tone.dot)} />
      <span className={cn("font-bold text-[11px] tracking-[0.16em] uppercase", tone.text)}>
        {label}
      </span>
      <span className={cn("text-[10px] tracking-[0.12em] uppercase opacity-70", tone.text)}>
        · {funding.composite_severity}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Two-column Uncertainty section — matches Stitch reference exactly
// ---------------------------------------------------------------------------

interface UncertaintySectionProps {
  /** When provided (parent-driven), this stress regime is rendered directly
   *  and no internal fetch is made.  When omitted (standalone usage), the
   *  component falls back to its own /stress query for backward compat. */
  stress?: (StressRegime & { available?: boolean }) | null;
  isLoading?: boolean;
  /** News-derived sector uncertainty concentration from /market-context.
   *  When uncertainty_scope is "sector", the section leads with sector chips
   *  and the 5-signal grid becomes a secondary baseline. */
  uncertaintyConcentration?: NewsUncertaintyConcentration | null;
  /** Funding/liquidity stress-mode classifier output from /market-context.
   *  Rendered as a second pill next to the regime pill when a mode is
   *  firing, so the operator can see WHICH kind of stress is dominating —
   *  not just whether stress is elevated. */
  fundingStressMode?: FundingStressMode | null;
}

function UnavailableStressSection({ degraded }: { degraded?: boolean }) {
  return (
    <section className="mb-6">
      <div className="bg-surface-container-low rounded-lg p-4">
        <div className="flex flex-col lg:flex-row gap-6 items-start">
          <div className="lg:w-1/4 shrink-0 space-y-2">
            <p className="section-kicker">
              Interpretation environment <span className="font-normal normal-case tracking-normal text-muted-foreground/55">· cross-asset stress</span>
            </p>
            <div className="inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full bg-surface-container-highest">
              <AlertTriangle className="h-3 w-3 text-on-surface-variant/45" />
              <span className="font-bold text-[11px] tracking-[0.16em] uppercase text-on-surface-variant/65">
                {degraded ? "Degraded" : "Unavailable"}
              </span>
            </div>
            <p className="text-on-surface-variant/70 text-[12px] leading-relaxed">
              Stress signals are unavailable for this market snapshot.
            </p>
          </div>
          <div className="flex-1 rounded-lg bg-white/[0.02] px-4 py-6 text-[12px] text-on-surface-variant/65">
            No live stress values are available.
          </div>
        </div>
      </div>
    </section>
  );
}

export function UncertaintySection({ stress, isLoading: parentLoading, uncertaintyConcentration, fundingStressMode }: UncertaintySectionProps = {}) {
  // Parent-provided data takes precedence; only fetch when nothing was passed in.
  const enabled = stress === undefined;
  const { data: fetched, isLoading: fetchedLoading } = useQuery({
    queryKey: qk.stress(),
    queryFn: () => api.stress(),
    staleTime: 600_000,
    enabled,
  });

  const data: (StressRegime & { available?: boolean }) | undefined =
    enabled ? fetched : (stress ?? undefined);
  const isLoading = enabled ? fetchedLoading : (parentLoading ?? false);

  if (isLoading) {
    return (
      <section className="mb-6">
        <div className="bg-surface-container-low rounded-lg p-4">
          <div className="flex flex-col lg:flex-row gap-6 items-start">
            <div className="lg:w-1/4 shrink-0 space-y-2">
              <Skeleton className="h-4 w-20 bg-surface-container-highest" />
              <Skeleton className="h-5 w-40 bg-surface-container-highest" />
              <Skeleton className="h-10 w-full bg-surface-container-highest" />
            </div>
            <div className="flex-1 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-px bg-outline-variant/15 rounded-md overflow-hidden">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-24 bg-surface-container-highest" />
              ))}
            </div>
          </div>
        </div>
      </section>
    );
  }

  if (!data || data.available === false) {
    return <UnavailableStressSection degraded={data?.available === false} />;
  }

  const rc = regimeColor(data.regime);
  const detail = data.detail ?? {};
  const detailKeys = ["volatility", "term_structure", "credit", "safe_haven", "breadth"] as const;
  const sectionDegraded = deriveStressDegraded(data);
  const presentDetailKeys = detailKeys.filter((k) => detail[k]);

  if (presentDetailKeys.length === 0) {
    return <UnavailableStressSection degraded />;
  }

  // Short label for regime
  const regimeLabel = data.regime.toUpperCase();

  const isSectorLed =
    uncertaintyConcentration?.uncertainty_scope === "sector" &&
    (uncertaintyConcentration.sector_uncertainty?.length ?? 0) > 0;

  return (
    // Compact stress card per the approved design package — no hero
    // typography, no drop shadow, no 1px section border.  Tonal
    // layering on a surface-container-low base; the regime pill stays
    // as the only colour accent so the eye still finds it instantly.
    <section className="mb-6">
      <div className="bg-surface-container-low rounded-lg p-4">
        <div className="flex flex-col gap-4">
          {/* Top row: left card-title + regime pill | right indicator grid */}
          <div className="flex flex-col lg:flex-row gap-6 items-start">
            <div className="lg:w-1/4 shrink-0 space-y-2">
              <p className="section-kicker">
                Interpretation environment <span className="font-normal normal-case tracking-normal text-muted-foreground/55">· cross-asset stress</span>
              </p>
              <div className="flex flex-wrap items-center gap-1.5">
                {isSectorLed ? (
                  <div className={cn(
                    "inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full",
                    rc.badge,
                  )}>
                    <span className="relative flex h-1.5 w-1.5">
                      <span className={cn("animate-ping absolute inline-flex h-full w-full rounded-full opacity-75", rc.dot)} />
                      <span className={cn("relative inline-flex rounded-full h-1.5 w-1.5", rc.dot)} />
                    </span>
                    <span className={cn("font-bold text-[11px] tracking-[0.16em] uppercase", rc.text)}>
                      {uncertaintyConcentration!.lead_sector ?? "Sector"} · Concentration
                    </span>
                  </div>
                ) : (
                  <div className={cn(
                    "inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full",
                    rc.badge,
                  )}>
                    <span className="relative flex h-1.5 w-1.5">
                      <span className={cn("animate-ping absolute inline-flex h-full w-full rounded-full opacity-75", rc.dot)} />
                      <span className={cn("relative inline-flex rounded-full h-1.5 w-1.5", rc.dot)} />
                    </span>
                    <span className={cn("font-bold text-[11px] tracking-[0.16em] uppercase", rc.text)}>{regimeLabel}</span>
                  </div>
                )}
                {isFundingModeFiring(fundingStressMode) && (
                  <FundingModePill funding={fundingStressMode} />
                )}
              </div>
              {data.summary && (
                <p className="text-on-surface-variant/85 text-[12px] leading-relaxed">{data.summary}</p>
              )}
              <p className="text-[11px] leading-relaxed text-on-surface-variant/55">
                This describes the tape conditions around event reactions; it does not predict direction.
              </p>
              {sectionDegraded && (
                <div className="flex items-center gap-1.5">
                  <AlertTriangle className="h-3 w-3 text-error-dim/60 shrink-0" />
                  <span className="text-[11px] text-error-dim/65">{sectionDegraded}</span>
                </div>
              )}
            </div>

            {/* Right — sector chips (sector-led) or 5 indicator cards (global) */}
            {isSectorLed ? (
              <div className="flex-1 flex flex-col gap-3">
                <SectorLeadRow
                  topSectors={uncertaintyConcentration!.sector_uncertainty}
                  volSectors={data.sector_uncertainty?.sectors}
                />
                <div>
                  <span className="text-[9px] uppercase tracking-widest text-on-surface-variant/40 font-bold">
                    Baseline
                  </span>
                  <div className="mt-1 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-px bg-outline-variant/20 rounded-lg overflow-hidden opacity-50">
                    {presentDetailKeys.map((k) => {
                      const d = detail[k]!;
                      return <IndicatorCard key={k} detail={d} />;
                    })}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex-1 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-px bg-outline-variant/20 rounded-lg overflow-hidden">
                {presentDetailKeys.map((k) => {
                  const d = detail[k]!;
                  return <IndicatorCard key={k} detail={d} />;
                })}
              </div>
            )}
          </div>

          {/* Sector pressure row — vol-based, only in global mode when concentrated/mixed */}
          {!isSectorLed && (() => {
            const su = data.sector_uncertainty;
            if (!su?.available) return null;
            if (su.concentration === "diffuse") return null;
            return (
              <div className="border-t border-outline-variant/15 pt-4">
                <SectorPressureRow
                  sectors={su.sectors ?? []}
                  spyVol={su.spy_vol_20d}
                />
              </div>
            );
          })()}
        </div>
      </div>
    </section>
  );
}

export { UncertaintySection as StressStrip };
