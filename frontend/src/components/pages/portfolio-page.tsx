import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type ArchiveDriftResponse,
  type CohortComparisonDimension,
  type CohortComparisonResponse,
  type CohortPackSummary,
  type CohortResearchResponse,
  type EventGraphEdge,
  type EventGraphNode,
  type EventGraphResponse,
  type PortfolioEntry,
  type PersistenceSignal,
  type RegimeDriftEntry,
  type SimulatePortfolioResponse,
  type SimulatePosition,
  type SimulateWarning,
  type ThemeTrendEntry,
  type TrackRecordBreakdown,
  type TrackRecordBreakdownBucket,
  type CrossEventStudiesResponse,
  type CrossEventFamilyPair,
  type CrossEventSectorPair,
  type CrossEventPathCluster,
  type CrossEventCombination,
  type SavedStudy,
  type SavedStudyType,
  type SaveStudyRequest,
  type SavedStudiesListResponse,
  type ResearchExportStudyInline,
  type PortfolioFilters,
  type MarketMover,
  hasActivePortfolioFilters,
  unwrapPortfolioItems,
  getStaleDisplay,
} from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { ResearchPageShell } from "@/components/ui/research-page-shell";
import {
  BookOpen,
  TrendingUp,
  TrendingDown,
  CheckCircle2,
  XCircle,
  Circle,
  Minus,
  RefreshCw,
  Bookmark,
  BookmarkPlus,
  Trash2,
  FolderOpen,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Design constants — matches analysis-view tonal hierarchy
// ---------------------------------------------------------------------------

const SECTION_CARD =
  "bg-surface-container-low rounded-lg";

// ---------------------------------------------------------------------------
// Simulator pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/** Group positions by event_id, preserving insertion order. */
export function groupPositionsByEvent(
  positions: SimulatePosition[],
): Map<number, SimulatePosition[]> {
  const map = new Map<number, SimulatePosition[]>();
  for (const pos of positions) {
    const existing = map.get(pos.event_id);
    if (existing) {
      existing.push(pos);
    } else {
      map.set(pos.event_id, [pos]);
    }
  }
  return map;
}

/** Format a nullable return value as "+4.2%" / "-2.1%" / "—". */
export function formatReturn(r: number | null): string {
  if (r === null) return "—";
  const sign = r >= 0 ? "+" : "";
  return `${sign}${r.toFixed(1)}%`;
}

// ---------------------------------------------------------------------------
// Engine-phase compact signals — pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/** Compact quality-tier label used on portfolio rows. */
export function formatQualityTier(
  tier: PortfolioEntry["quality_tier"] | undefined,
): string | null {
  switch (tier) {
    case "actionable":
      return "high-quality";
    case "watch_only":
      return "watch";
    case "low_information":
      return "low info";
    default:
      return null;
  }
}

/** Normalised subtype for display — strips a redundant family prefix. */
export function formatSubtype(
  subtype: string | null | undefined,
  family: string | null | undefined,
): string | null {
  if (!subtype) return null;
  const trimmed = String(subtype).trim();
  if (!trimmed || trimmed.toLowerCase() === "none") return null;
  const fam = (family || "").trim().toLowerCase();
  const sub = trimmed.toLowerCase();
  if (fam && sub === fam) return null;
  return trimmed.replace(/_/g, " ");
}

/** Tradable read derived from actionability_check; null when unknown. */
export function tradableFlag(
  block: PortfolioEntry["actionability_check"] | undefined,
): boolean | null {
  if (!block || typeof block !== "object") return null;
  const v = (block as { tradable?: boolean | null }).tradable;
  return typeof v === "boolean" ? v : null;
}

/** True when the row landed on the engine's ``low_information`` tier.
 *  Drives the muted / diagnostic styling — a low-info read isn't a
 *  bearish thesis call; it's a *no call*, so loser icons, contradicting
 *  ticker chips, and the validation badge get suppressed or dimmed
 *  rather than rendered in the standard bearish red. */
export function isLowInfoRow(
  tier: PortfolioEntry["quality_tier"] | undefined,
): boolean {
  return tier === "low_information";
}

/** Filter quality_warnings down to a renderable list (deduped, capped). */
export function compactWarnings(
  warnings: string[] | null | undefined,
  cap: number = 3,
): string[] {
  if (!Array.isArray(warnings)) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const w of warnings) {
    if (typeof w !== "string") continue;
    const t = w.trim();
    if (!t || seen.has(t)) continue;
    seen.add(t);
    out.push(t);
    if (out.length >= cap) break;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Engine-field filter helpers (exported for tests)
// ---------------------------------------------------------------------------

export type QualityTierFilter = "all" | "actionable" | "watch_only" | "low_information";
export type TradableFilter = "all" | "tradable" | "not_tradable" | "unknown";

export interface EngineFilters {
  qualityTier: QualityTierFilter;
  tradable: TradableFilter;
  /** Subtype label as displayed by `formatSubtype` (post-normalisation) or "all". */
  subtype: string;
}

export const ENGINE_FILTERS_DEFAULT: EngineFilters = {
  qualityTier: "all",
  tradable:    "all",
  subtype:     "all",
};

export function isEngineFilterActive(f: EngineFilters): boolean {
  return (
    f.qualityTier !== "all" ||
    f.tradable !== "all" ||
    f.subtype !== "all"
  );
}

/** Apply the three engine filters in-memory.  Skips unknown filter values. */
export function applyEngineFilters(
  entries: PortfolioEntry[] | null | undefined,
  filters: EngineFilters,
): PortfolioEntry[] {
  if (!Array.isArray(entries)) return [];
  if (!isEngineFilterActive(filters)) return entries.slice();

  return entries.filter((e) => {
    if (filters.qualityTier !== "all") {
      if ((e.quality_tier ?? null) !== filters.qualityTier) return false;
    }
    if (filters.tradable !== "all") {
      const t = tradableFlag(e.actionability_check);
      if (filters.tradable === "tradable" && t !== true) return false;
      if (filters.tradable === "not_tradable" && t !== false) return false;
      if (filters.tradable === "unknown" && t !== null) return false;
    }
    if (filters.subtype !== "all") {
      const fam = (e as { mechanism_family?: string | null }).mechanism_family;
      const s = formatSubtype(e.mechanism_subtype, fam);
      if (s !== filters.subtype) return false;
    }
    return true;
  });
}

/** Unique sorted subtype labels present in the input — applies the same
 *  normalisation as the row chip so the dropdown matches what the user sees. */
export function collectSubtypes(
  entries: PortfolioEntry[] | null | undefined,
): string[] {
  if (!Array.isArray(entries)) return [];
  const seen = new Set<string>();
  for (const e of entries) {
    const fam = (e as { mechanism_family?: string | null }).mechanism_family;
    const s = formatSubtype(e.mechanism_subtype, fam);
    if (s) seen.add(s);
  }
  return Array.from(seen).sort((a, b) => a.localeCompare(b));
}

// ---------------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------------

function ValidationBadge({
  outcome,
  ratio,
}: {
  outcome: PortfolioEntry["validation_outcome"];
  ratio: number | null;
}) {
  const cfg = {
    validated: {
      label: "Validated",
      color: "text-[#6ec6a5]",
      bg: "bg-[#6ec6a5]/10",
      Icon: CheckCircle2,
    },
    contradicted: {
      label: "Contradicted",
      color: "text-[#ee7d77]",
      bg: "bg-[#ee7d77]/10",
      Icon: XCircle,
    },
    unresolved: {
      label: "Unresolved",
      color: "text-muted-foreground",
      bg: "bg-surface-container",
      Icon: Circle,
    },
    no_data: {
      label: "No market data",
      color: "text-muted-foreground/50",
      bg: "bg-surface-container",
      Icon: Minus,
    },
  } as const;

  const { label, color, bg, Icon } = cfg[outcome];
  const pct =
    ratio !== null && outcome !== "no_data" && outcome !== "unresolved"
      ? ` · ${Math.round(ratio * 100)}%`
      : "";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
        bg,
        color,
      )}
    >
      <Icon className="h-3 w-3 shrink-0" />
      {label}
      {pct && <span className="opacity-60">{pct}</span>}
    </span>
  );
}

function ConfidenceChip({ value }: { value: string | null }) {
  if (!value) return null;
  const color: Record<string, string> = {
    high: "text-[#6ec6a5]",
    medium: "text-[#a89f91]",
    low: "text-[#c07070]",
  };
  return (
    <span
      className={cn(
        "text-[11px] font-medium capitalize",
        color[value] ?? "text-muted-foreground",
      )}
    >
      {value}
    </span>
  );
}

function RatingBadge({ value }: { value: string | null }) {
  if (!value) return null;
  const cfg: Record<string, { label: string; color: string }> = {
    good:  { label: "Good",  color: "text-[#6ec6a5]/70" },
    mixed: { label: "Mixed", color: "text-[#a89f91]/70" },
    poor:  { label: "Poor",  color: "text-[#c07070]/70" },
  };
  const c = cfg[value];
  if (!c) return null;
  return (
    <span className={cn("text-[10px] font-medium uppercase tracking-wider", c.color)}>
      {c.label}
    </span>
  );
}

function RevisitDots({ snapshots }: { snapshots: PortfolioEntry["revisit_snapshots"] }) {
  const capturedDays = new Set(snapshots.map((s) => s.day));
  return (
    <div className="flex items-center gap-1">
      {([1, 5, 20] as const).map((d) => (
        <span
          key={d}
          title={`Day ${d} revisit`}
          className={cn(
            "inline-flex h-4 min-w-[20px] items-center justify-center rounded px-1 text-[10px] font-medium tabular-nums",
            capturedDays.has(d)
              ? "bg-primary/15 text-primary"
              : "bg-surface-container text-muted-foreground/30",
          )}
        >
          {d}d
        </span>
      ))}
    </div>
  );
}

function LifecycleBadge({ sig }: { sig: PersistenceSignal }) {
  if (sig.status === "watching") return null;
  const cfg = {
    active:   { color: "text-[#93d1d3]", bg: "bg-[#93d1d3]/10" },
    fading:   { color: "text-[#ee7d77]", bg: "bg-[#ee7d77]/10" },
    resolved: { color: "text-muted-foreground", bg: "bg-surface-container" },
  } as const;
  const { color, bg } = cfg[sig.status];
  return (
    <span
      className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium", color, bg)}
      title={sig.evidence}
    >
      {sig.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Simulator subcomponents
// ---------------------------------------------------------------------------

function PickRow({
  entry,
  selected,
  onToggle,
}: {
  entry: PortfolioEntry;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      className={cn(
        "w-full rounded-lg p-2.5 text-left transition-all",
        "shadow-[inset_0_0_0_1px_rgba(71,70,86,0.35)]",
        selected &&
          "bg-primary/5 shadow-[inset_0_0_0_1px_rgba(147,209,211,0.25)]",
      )}
    >
      <div className="flex items-start gap-2.5">
        {/* Checkbox */}
        <div
          className={cn(
            "mt-0.5 flex h-3 w-3 shrink-0 items-center justify-center rounded border",
            selected
              ? "border-primary/50 bg-primary/15"
              : "border-outline-variant/40 bg-transparent",
          )}
        >
          {selected && (
            <span className="block h-1.5 w-1.5 rounded-sm bg-primary" />
          )}
        </div>
        {/* Content */}
        <div className="min-w-0 flex-1">
          <p
            className={cn(
              "line-clamp-2 text-[10px] font-semibold leading-snug",
              selected ? "text-on-surface" : "text-on-surface/50",
            )}
          >
            {entry.headline}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <ValidationBadge
              outcome={entry.validation_outcome}
              ratio={null}
            />
            <ConfidenceChip value={entry.confidence} />
          </div>
        </div>
      </div>
    </button>
  );
}

function SnapshotStrip({
  summary,
}: {
  summary: SimulatePortfolioResponse["summary"];
}) {
  const metrics: Array<{
    label: string;
    value: string;
    positive?: boolean;
    negative?: boolean;
  }> = [
    {
      label: "Return",
      value:
        summary.portfolio_return !== null
          ? formatReturn(summary.portfolio_return)
          : "—",
      positive:
        summary.portfolio_return !== null && summary.portfolio_return >= 0,
      negative:
        summary.portfolio_return !== null && summary.portfolio_return < 0,
    },
    {
      label: "Win Rate",
      value:
        summary.win_rate !== null
          ? `${Math.round(summary.win_rate * 100)}%`
          : "—",
    },
    {
      label: "Coverage",
      value: `${Math.round(summary.data_coverage * 100)}%`,
    },
    {
      label: "Positions",
      value: String(summary.positions_total),
    },
  ];

  return (
    <div className={cn(SECTION_CARD, "px-4 py-3")}>
      <p className="section-kicker mb-3">
        Portfolio Snapshot · {summary.events_contributing} positions
      </p>
      <div className="flex gap-6">
        {metrics.map((m) => (
          <div key={m.label} className="flex flex-col items-center gap-0.5">
            <span
              className={cn(
                "text-[20px] font-bold tabular-nums leading-none",
                m.positive
                  ? "text-[#6ec6a5]"
                  : m.negative
                    ? "text-[#ee7d77]"
                    : "text-primary",
              )}
            >
              {m.value}
            </span>
            <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-muted-foreground">
              {m.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function EventOutcomes({
  positions,
  entries,
}: {
  positions: SimulatePosition[];
  entries: PortfolioEntry[];
}) {
  const grouped = useMemo(() => groupPositionsByEvent(positions), [positions]);
  const entryMap = useMemo(
    () => new Map(entries.map((e) => [e.id, e])),
    [entries],
  );

  return (
    <div className={cn(SECTION_CARD, "px-4 py-3")}>
      <p className="section-kicker mb-3">Per-event outcomes</p>
      <div className="space-y-3">
        {Array.from(grouped.entries()).map(([eventId, eventPositions]) => {
          const entry = entryMap.get(eventId);
          const headline = eventPositions[0]?.event_headline ?? "";
          const allMissing = eventPositions.every(
            (p) => p.return_source === "missing",
          );

          return (
            <div
              key={eventId}
              className="flex items-start gap-3 border-b border-border/20 pb-3 last:border-0 last:pb-0"
            >
              {/* Status dot */}
              <span
                className={cn(
                  "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full",
                  entry?.validation_outcome === "validated"
                    ? "bg-[#6ec6a5]"
                    : entry?.validation_outcome === "contradicted"
                      ? "bg-[#ee7d77]"
                      : "bg-muted-foreground/30",
                )}
              />
              <div className="min-w-0 flex-1">
                <p className="mb-1.5 line-clamp-1 text-[10.5px] font-semibold text-on-surface">
                  {headline}
                </p>
                {allMissing ? (
                  <span className="text-[10px] text-muted-foreground/50">
                    No data
                  </span>
                ) : (
                  <div className="flex flex-wrap gap-1">
                    {eventPositions.map((pos) => (
                      <span
                        key={`${pos.symbol}-${pos.direction_tag ?? "n"}`}
                        className={cn(
                          "inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 font-mono text-[10px] font-medium",
                          pos.gross_return === null
                            ? "bg-surface-container text-muted-foreground/50"
                            : pos.gross_return >= 0
                              ? "bg-[#6ec6a5]/10 text-[#6ec6a5]"
                              : "bg-[#ee7d77]/10 text-[#ee7d77]",
                        )}
                      >
                        {pos.symbol}
                        <span className="opacity-70">
                          {formatReturn(pos.gross_return)}
                        </span>
                      </span>
                    ))}
                  </div>
                )}
              </div>
              {entry && (
                <ValidationBadge
                  outcome={entry.validation_outcome}
                  ratio={null}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function WarningsList({ warnings }: { warnings: SimulateWarning[] }) {
  if (warnings.length === 0) return null;

  return (
    <div className={cn(SECTION_CARD, "px-4 py-3")}>
      <p className="section-kicker mb-3">Overlap & concentration</p>
      <div className="space-y-2">
        {warnings.map((w, i) => (
          <div
            key={i}
            className={cn(
              "rounded-md px-3 py-2 text-[11px]",
              w.type === "concentration"
                ? "border border-[#ee7d77]/18 bg-[#ee7d77]/6 text-[#ee7d77]"
                : "bg-surface-container text-muted-foreground",
            )}
          >
            {w.type === "concentration" && (
              <span className="mr-1">⚠</span>
            )}
            {w.message}
          </div>
        ))}
      </div>
    </div>
  );
}

function SimResults({
  selectedIds,
  entries,
}: {
  selectedIds: Set<number>;
  entries: PortfolioEntry[];
}) {
  const sortedIds = useMemo(
    () => [...selectedIds].sort((a, b) => a - b),
    [selectedIds],
  );

  const { data, isLoading, isError } = useQuery({
    queryKey: qk.simulate(sortedIds),
    queryFn: () =>
      api.simulatePortfolio({
        event_ids: sortedIds,
        horizon: "5d",
        direction_filter: "supporting",
        include_shorts: false,
      }),
    enabled: sortedIds.length > 0,
    staleTime: 2 * 60_000,
  });

  if (sortedIds.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center text-center">
        <p className="text-[12px] text-muted-foreground/50">
          Select positions from the left to run a simulation
        </p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-20 w-full rounded-xl" />
        <Skeleton className="h-36 w-full rounded-xl" />
        <Skeleton className="h-20 w-full rounded-xl" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className={cn(SECTION_CARD, "p-6 text-center")}>
        <p className="text-[12px] text-muted-foreground">
          Simulation failed — try again
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <SnapshotStrip summary={data.summary} />
      {data.positions.length > 0 && (
        <EventOutcomes positions={data.positions} entries={entries} />
      )}
      <WarningsList warnings={data.warnings} />
    </div>
  );
}

function SimulatorTab({
  entries,
  selectedIds,
  onToggle,
}: {
  entries: PortfolioEntry[];
  selectedIds: Set<number>;
  onToggle: (id: number) => void;
}) {
  return (
    <div className="grid grid-cols-[260px_1fr] gap-4">
      {/* LEFT: pick list */}
      <div>
        <p className="section-kicker mb-2">
          Select positions ({selectedIds.size} / {entries.length})
        </p>
        <div className="space-y-1.5">
          {entries.map((entry) => (
            <PickRow
              key={entry.id}
              entry={entry}
              selected={selectedIds.has(entry.id)}
              onToggle={() => onToggle(entry.id)}
            />
          ))}
        </div>
      </div>

      {/* RIGHT: results */}
      <SimResults selectedIds={selectedIds} entries={entries} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Research analytics — mechanism-family + regime track record
// ---------------------------------------------------------------------------
//
// Renders the three slices produced by /stats/track-record/breakdown in a
// dense, research-oriented layout: overall strip + three tables.  Every
// numeric is tabular-nums; hit rates are colour-coded using the same
// muted teal (supporting) / coral (contradicting) palette used elsewhere.
// Falls back to a friendly empty state when the archive has no
// resolvable outcomes yet.

/** Render a signed-percent return with consistent sign-leading format. */
function _fmtPct(v: number | null, digits = 1): string {
  if (v === null || v === undefined) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

/** Render hit rate as "56% · 18 events" — the two numbers that matter
 *  for a research desk in one compact string.  Hides the rate when
 *  the bucket has no directional outcomes. */
function _fmtHitRate(rate: number | null, n: number): string {
  if (rate === null || n === 0) return `— · ${n}`;
  return `${Math.round(rate * 100)}% · ${n}`;
}

/** Tone for a hit rate — green when the bucket is beating 50%, coral
 *  when worse than a coinflip, neutral otherwise.  `n` gates: buckets
 *  with fewer than 3 resolved directional outcomes stay neutral even
 *  at 100% / 0% because sample depth doesn't support a call yet. */
function _hitRateTone(rate: number | null, n: number): string {
  if (rate === null || n < 3) return "text-muted-foreground/70";
  if (rate >= 0.55) return "text-[#6ec6a5]";
  if (rate <= 0.45) return "text-[#ee7d77]";
  return "text-muted-foreground/70";
}

function _returnTone(v: number | null): string {
  if (v === null) return "text-muted-foreground/40";
  if (v >= 0) return "text-[#6ec6a5]";
  return "text-[#ee7d77]";
}

/** Pick the canonical label for a breakdown bucket — the three slice
 *  types populate different identifier keys. */
function _bucketLabel(b: TrackRecordBreakdownBucket): string {
  if (b.family_label) return b.family_label;
  if (b.family) return b.family.replace(/_/g, " ");
  if (b.label) return b.label;
  if (b.state) return b.state.replace(/_/g, " ");
  if (b.regime_key) return b.regime_key.replace(/\//g, " / ").replace(/_/g, " ");
  return "—";
}

function _bucketKey(b: TrackRecordBreakdownBucket, prefix: string): string {
  return `${prefix}:${b.family ?? b.state ?? b.regime_key ?? "unk"}`;
}

/** Resolution-mix bar — three width-proportional segments showing
 *  validated / contradicted / unresolved counts.  Mirrors the design
 *  package ``.resolution`` strip.  Renders nothing when the bucket has
 *  no events.  Width is fixed (80px) so columns align across rows. */
function _ResolutionBar({
  validated,
  contradicted,
  unresolved,
  width = 80,
}: {
  validated: number;
  contradicted: number;
  unresolved: number;
  width?: number;
}) {
  const total = validated + contradicted + unresolved;
  if (total === 0) {
    return <span className="inline-block h-1.5 w-[80px] rounded-sm bg-white/[0.04]" />;
  }
  const v = Math.round((validated / total) * width);
  const c = Math.round((contradicted / total) * width);
  const u = Math.max(0, width - v - c);
  return (
    <span
      className="inline-flex h-1.5 overflow-hidden rounded-sm bg-white/[0.04] align-middle"
      style={{ width }}
      aria-hidden
    >
      <span className="bg-[#93d1d3]/75" style={{ width: `${v}px` }} />
      <span className="bg-[#ee7d77]/75" style={{ width: `${c}px` }} />
      <span className="bg-white/15" style={{ width: `${u}px` }} />
    </span>
  );
}

/** Hit-rate progress bar — design package ``.hit-bar``.  Subdued teal
 *  fill, dim when below 0.5 to flag a coin-flip bucket at a glance. */
function _HitRateBar({
  rate,
  width = 56,
}: {
  rate: number | null;
  width?: number;
}) {
  if (rate === null) {
    return <span className="inline-block h-1.5 w-[56px] rounded-sm bg-white/[0.04]" />;
  }
  const fillWidth = Math.max(2, Math.min(width, rate * width));
  return (
    <span
      className="inline-block h-1.5 overflow-hidden rounded-sm bg-white/[0.04] align-middle"
      style={{ width }}
      aria-hidden
    >
      <span
        className={cn(
          "block h-full rounded-sm",
          rate < 0.5 ? "bg-[#93d1d3]/35" : "bg-[#93d1d3]/75",
        )}
        style={{ width: `${fillWidth}px` }}
      />
    </span>
  );
}

function ResearchHeadlineStrip({ data }: { data: TrackRecordBreakdown }) {
  const directional = data.validated_total + data.contradicted_total;
  const hitRatePct = data.hit_rate !== null ? Math.round(data.hit_rate * 100) : null;

  // Secondary metrics — kept inline so the hero number reads first.
  const metrics: Array<{ label: string; value: string; tone?: string }> = [
    { label: "Validated",    value: String(data.validated_total), tone: "text-[#93d1d3]" },
    { label: "Contradicted", value: String(data.contradicted_total), tone: "text-[#ee7d77]" },
    { label: "Events",       value: String(data.total_events) },
    { label: "Revisits",     value: String(data.revisit_scored) },
  ];

  return (
    <div className={cn(SECTION_CARD, "px-4 py-3")}>
      <div className="flex items-baseline justify-between gap-3 mb-3">
        <p className="section-kicker">
          Research &amp; track record
        </p>
        <span className="text-[11px] text-muted-foreground/55">
          sliced by mechanism &amp; regime
        </span>
      </div>
      <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
        {/* Hero metric — hit rate dominates so the page reads "did the
            discipline pay" before any breakdown row competes for attention. */}
        <div className="flex flex-col gap-1 pr-6 border-r border-white/[0.06]">
          <div className="flex items-baseline gap-3">
            <span
              className={cn(
                "font-headline font-extrabold text-[28px] leading-none tracking-tight tabular-nums",
                _hitRateTone(data.hit_rate, directional),
              )}
            >
              {hitRatePct !== null ? `${hitRatePct}%` : "—"}
            </span>
            <_HitRateBar rate={data.hit_rate} width={88} />
          </div>
          <span className="text-[11px] font-bold uppercase tracking-[0.15em] text-muted-foreground/70">
            Hit rate · {directional} resolved
          </span>
        </div>
        {/* Secondary metrics */}
        {metrics.map((m) => (
          <div key={m.label} className="flex flex-col gap-0.5">
            <span
              className={cn(
                "text-[18px] font-semibold tabular-nums leading-none",
                m.tone ?? "text-on-surface/90",
              )}
            >
              {m.value}
            </span>
            <span className="text-[11px] font-bold uppercase tracking-[0.15em] text-muted-foreground/65">
              {m.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function BreakdownTable({
  title,
  kicker,
  keyPrefix,
  buckets,
  emptyHint,
}: {
  title: string;
  kicker: string;
  keyPrefix: string;
  buckets: TrackRecordBreakdownBucket[];
  emptyHint: string;
}) {
  return (
    <div className={cn(SECTION_CARD, "px-4 py-3")}>
      <p className="section-kicker mb-0.5">{title}</p>
      <p className="mb-3 text-[10px] text-muted-foreground/50">
        {kicker}
      </p>

      {buckets.length === 0 ? (
        <p className="py-4 text-center text-[11px] text-muted-foreground/55">
          {emptyHint}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-[10px] font-bold uppercase tracking-[0.15em] text-muted-foreground/65">
                <th className="pb-2 text-left">Bucket</th>
                <th className="pb-2 pl-3 text-right tabular-nums">N</th>
                <th className="pb-2 pl-3 text-left">Resolution</th>
                <th className="pb-2 pl-3 text-right">Hit rate</th>
                <th className="pb-2 pl-3 text-right">Avg 5d</th>
                <th className="pb-2 pl-3 text-right">Avg 20d</th>
                <th className="pb-2 pl-3 text-right">Revisits</th>
              </tr>
            </thead>
            <tbody>
              {buckets.map((b) => {
                const directional = b.validated + b.contradicted;
                return (
                  <tr
                    key={_bucketKey(b, keyPrefix)}
                    className="border-t border-white/[0.05] hover:bg-white/[0.015] transition-colors"
                  >
                    <td className="py-2 pr-2">
                      <span className="font-medium capitalize text-on-surface/90">
                        {_bucketLabel(b)}
                      </span>
                    </td>
                    <td className="py-2 pl-3 text-right font-mono text-[11px] tabular-nums text-on-surface/80">
                      {b.total}
                    </td>
                    <td className="py-2 pl-3">
                      <div className="flex items-center gap-3">
                        <_ResolutionBar
                          validated={b.validated}
                          contradicted={b.contradicted}
                          unresolved={b.unresolved}
                        />
                        <span className="font-mono text-[11px] tabular-nums text-muted-foreground/65 whitespace-nowrap">
                          <span className="text-[#93d1d3]">{b.validated}</span>
                          <span className="text-muted-foreground/35">/</span>
                          <span className="text-[#ee7d77]">{b.contradicted}</span>
                          <span className="text-muted-foreground/35">/{b.unresolved}</span>
                        </span>
                      </div>
                    </td>
                    <td className="py-2 pl-3">
                      <div className="flex items-center justify-end gap-2">
                        <_HitRateBar rate={b.hit_rate} />
                        <span
                          className={cn(
                            "font-mono text-[11px] tabular-nums w-[58px] text-right",
                            _hitRateTone(b.hit_rate, directional),
                          )}
                        >
                          {_fmtHitRate(b.hit_rate, directional)}
                        </span>
                      </div>
                    </td>
                    <td
                      className={cn(
                        "py-2 pl-3 text-right font-mono text-[11px] tabular-nums",
                        _returnTone(b.avg_return_5d),
                      )}
                    >
                      {_fmtPct(b.avg_return_5d)}
                    </td>
                    <td
                      className={cn(
                        "py-2 pl-3 text-right font-mono text-[11px] tabular-nums",
                        _returnTone(b.avg_return_20d),
                      )}
                    >
                      {_fmtPct(b.avg_return_20d)}
                    </td>
                    <td className="py-2 pl-3 text-right font-mono text-[11px] tabular-nums text-muted-foreground/70">
                      {b.revisit_scored}/{b.total}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scenario-pack research grid — cohort batch research across archetypes
// ---------------------------------------------------------------------------

const PACK_LABELS: Record<string, string> = {
  tariff_cycle:       "Tariff Cycles",
  sanction_cycle:     "Sanction Cycles",
  supply_squeeze:     "Supply Squeezes",
  supply_relief:      "Supply Relief",
  funding_squeeze:    "Funding Squeezes",
  policy_surprise:    "Policy Surprises",
  inflation_pressure: "Inflation Pressure",
  de_escalation:      "De-escalations",
};

function _basisTone(basis: string): string {
  if (basis === "deep")   return "text-[#93d1d3]";
  if (basis === "medium") return "text-on-surface/80";
  return "text-muted-foreground/55";
}

function _repricingTone(label: string): string {
  const l = (label || "").toLowerCase();
  if (l === "holding" || l === "accelerating") return "text-[#93d1d3]";
  if (l === "fading" || l === "reversed" || l === "negligible") return "text-[#ee7d77]";
  return "text-on-surface/80";
}

function _failureTone(rate: number, scored: number): string {
  if (scored < 3) return "text-muted-foreground/55";
  if (rate >= 0.4) return "text-[#ee7d77]";
  if (rate <= 0.15) return "text-[#93d1d3]";
  return "text-on-surface/80";
}

function _holdTone(rate: number, scored: number): string {
  if (scored < 3) return "text-muted-foreground/55";
  if (rate >= 0.6) return "text-[#93d1d3]";
  if (rate <= 0.3) return "text-[#ee7d77]";
  return "text-on-surface/80";
}

function _fmtSignedPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}%`;
}

function ScenarioPackCard({ pack }: { pack: CohortPackSummary }) {
  const { persistence, repricing_path: rep, falsification: fals } = pack;
  const label = PACK_LABELS[pack.pack] ?? pack.pack;
  const isThin = pack.confidence_basis === "thin" || pack.size < 3;

  return (
    <div
      id={`scenario-pack-${pack.pack}`}
      className={cn(
        SECTION_CARD,
        "flex flex-col gap-3 px-4 py-3 scroll-mt-4",
        isThin && "opacity-70",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-0.5">
          <p className="section-kicker">{label}</p>
          <p className="text-[10px] text-muted-foreground/60">
            {pack.families.join(" · ")}
          </p>
        </div>
        <div className="flex flex-col items-end gap-0.5">
          <span className="text-[18px] font-bold tabular-nums leading-none text-on-surface">
            {pack.size}
          </span>
          <span className={cn("nav-kicker", _basisTone(pack.confidence_basis))}>
            {pack.confidence_basis}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <div className="flex flex-col gap-0.5">
          <span className="nav-kicker text-muted-foreground/60">Repricing</span>
          <span
            className={cn(
              "text-[12px] font-medium capitalize leading-tight",
              _repricingTone(rep.typical),
            )}
          >
            {rep.typical}
          </span>
          <span className="text-[10px] text-muted-foreground/50 tabular-nums">
            {rep.scored > 0
              ? `${Math.round(rep.typical_share * 100)}% · n=${rep.scored}`
              : "no data"}
          </span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="nav-kicker text-muted-foreground/60">Held 20d</span>
          <span
            className={cn(
              "text-[12px] font-medium leading-tight tabular-nums",
              _holdTone(persistence.hold_rate, persistence.scored),
            )}
          >
            {persistence.scored > 0
              ? `${Math.round(persistence.hold_rate * 100)}%`
              : "—"}
          </span>
          <span className="text-[10px] text-muted-foreground/50 tabular-nums">
            μ {_fmtSignedPct(persistence.mean_20d)}
          </span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="nav-kicker text-muted-foreground/60">Falsified</span>
          <span
            className={cn(
              "text-[12px] font-medium leading-tight tabular-nums",
              _failureTone(fals.event_failure_rate, fals.scored_events),
            )}
          >
            {fals.scored_events > 0
              ? `${Math.round(fals.event_failure_rate * 100)}%`
              : "—"}
          </span>
          <span className="text-[10px] text-muted-foreground/50 tabular-nums">
            {fals.failed_events}/{fals.scored_events}
          </span>
        </div>
      </div>

      <p className="text-[11px] leading-snug text-on-surface/75">
        {pack.summary}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Archive drift — theme trends + regime drift
// ---------------------------------------------------------------------------

const REGIME_AXIS_LABELS: Record<string, string> = {
  inflation:       "Inflation",
  policy_stance:   "Policy",
  fx:              "FX",
  growth_stress:   "Growth",
  credit:          "Credit",
  curve_shape:     "Curve",
  inflation_path:  "Inflation path",
};

function _trendTone(direction: string, magnitude: string): string {
  if (magnitude === "noise") return "text-muted-foreground/55";
  if (direction === "up")   return "text-[#93d1d3]";
  if (direction === "down") return "text-[#ee7d77]";
  return "text-on-surface/80";
}

function _driftTone(direction: string): string {
  if (direction === "shifted")    return "text-[#ee7d77]";
  if (direction === "stable")     return "text-[#93d1d3]";
  return "text-muted-foreground/55";
}

function _fmtSharePp(delta: number): string {
  const sign = delta > 0 ? "+" : "";
  return `${sign}${(delta * 100).toFixed(1)}pp`;
}

function ThemeTrendsCard({ trends }: { trends: ThemeTrendEntry[] }) {
  const meaningful = trends.filter(
    (t) => t.magnitude !== "noise" && t.direction !== "flat",
  );
  const rows = meaningful.length > 0 ? meaningful.slice(0, 6) : trends.slice(0, 6);

  return (
    <div className={cn(SECTION_CARD, "px-4 py-3")}>
      <div className="flex items-baseline justify-between mb-3">
        <p className="section-kicker">Theme Trends</p>
        <p className="text-[11px] text-muted-foreground/55">
          30d vs 30–90d · share
        </p>
      </div>
      {rows.length === 0 ? (
        <p className="py-2 text-[11px] text-muted-foreground/55">
          No family-tagged events in the recent window.
        </p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {rows.map((t) => (
            <div
              key={t.family}
              className="flex items-center justify-between gap-3 text-[11px]"
            >
              <span className="font-medium capitalize text-on-surface/90">
                {t.family.replace(/_/g, " ")}
              </span>
              <div className="flex items-center gap-3 tabular-nums">
                <span className="text-muted-foreground/55">
                  {Math.round(t.prior_share * 100)}%
                </span>
                <span className="text-muted-foreground/35">→</span>
                <span className="text-on-surface/80">
                  {Math.round(t.recent_share * 100)}%
                </span>
                <span
                  className={cn(
                    "min-w-[56px] text-right font-mono font-semibold",
                    _trendTone(t.direction, t.magnitude),
                  )}
                >
                  {_fmtSharePp(t.delta)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function RegimeDriftCard({ drift }: { drift: RegimeDriftEntry[] }) {
  // Show only axes with data; hide "unavailable" rows to keep the card
  // tight on archives without full regime_snapshot coverage.
  const rows = drift.filter((d) => d.direction !== "unavailable");

  return (
    <div className={cn(SECTION_CARD, "px-4 py-3")}>
      <div className="flex items-baseline justify-between mb-3">
        <p className="section-kicker">Regime Drift</p>
        <p className="text-[11px] text-muted-foreground/55">
          axis · recent vs prior
        </p>
      </div>
      {rows.length === 0 ? (
        <p className="py-2 text-[11px] text-muted-foreground/55">
          No regime snapshots available in the recent windows.
        </p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {rows.map((d) => {
            const label = REGIME_AXIS_LABELS[d.axis] ?? d.axis;
            const showArrow = d.direction === "shifted";
            return (
              <div
                key={d.axis}
                className="flex items-center justify-between gap-3 text-[11px]"
              >
                <span className="font-medium text-on-surface/85">{label}</span>
                <div className="flex items-center gap-2 tabular-nums">
                  <span className="text-muted-foreground/55 capitalize">
                    {d.prior ?? "—"}
                  </span>
                  <span className={cn(
                    "text-muted-foreground/35",
                    showArrow && "text-[#ee7d77]/80",
                  )}>
                    →
                  </span>
                  <span
                    className={cn(
                      "capitalize",
                      _driftTone(d.direction),
                    )}
                  >
                    {d.recent ?? "—"}
                  </span>
                  <span className="min-w-[36px] text-right text-muted-foreground/55">
                    {Math.round(d.recent_share * 100)}%
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ArchiveDriftSection() {
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.archiveDrift(),
    queryFn: () => api.archiveDrift(),
    staleTime: 5 * 60_000,
  });

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <Skeleton className="h-48 w-full rounded-xl" />
        <Skeleton className="h-48 w-full rounded-xl" />
      </div>
    );
  }

  if (isError || !data) return null;
  const drift = data as ArchiveDriftResponse;

  if (!drift.available) {
    return (
      <div className={cn(SECTION_CARD, "px-4 py-3")}>
        <p className="section-kicker mb-2">Archive Drift</p>
        <p className="text-[11px] text-muted-foreground/55">
          Not enough dated events yet to compute theme trends or regime drift.
        </p>
      </div>
    );
  }

  const recent = drift.windows[0];
  const prior = drift.windows[1];

  return (
    <div className="space-y-2">
      <div className={cn(SECTION_CARD, "px-4 py-2.5")}>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <p className="section-kicker">Archive Drift</p>
            <p className="text-[10px] text-muted-foreground/50">
              How the archive's macro structure is moving
            </p>
          </div>
          <div className="flex items-center gap-3 text-[10px] tabular-nums">
            {recent && (
              <span className="text-muted-foreground/65">
                recent <span className="text-on-surface/80">{recent.size}</span>
              </span>
            )}
            {prior && (
              <span className="text-muted-foreground/65">
                prior <span className="text-on-surface/80">{prior.size}</span>
              </span>
            )}
            <span
              className={cn(
                "nav-kicker",
                drift.confidence_basis === "deep"
                  ? "text-[#93d1d3]"
                  : drift.confidence_basis === "medium"
                    ? "text-on-surface/80"
                    : "text-muted-foreground/55",
              )}
            >
              {drift.confidence_basis}
            </span>
          </div>
        </div>
        <p className="mt-2 text-[11px] leading-snug text-on-surface/75">
          {drift.summary}
        </p>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <ThemeTrendsCard trends={drift.theme_trends} />
        <RegimeDriftCard drift={drift.regime_drift} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Event graph — cross-event cascade + spillover
// ---------------------------------------------------------------------------

function _edgeWeightTone(weight: number, active: boolean): string {
  if (!active) return "text-muted-foreground/55";
  if (weight >= 0.5) return "text-[#ee7d77]";
  if (weight >= 0.25) return "text-on-surface/85";
  return "text-[#93d1d3]";
}

function _componentChipTone(component: string): string {
  switch (component) {
    case "path_cluster":  return "bg-[#93d1d3]/10 text-[#93d1d3]";
    case "family_shared": return "bg-on-surface/10 text-on-surface/80";
    case "asset_overlap": return "bg-[#ee7d77]/10 text-[#ee7d77]";
    case "sector_overlap": return "bg-on-surface/05 text-on-surface/65";
    default:              return "bg-surface-container text-muted-foreground";
  }
}

function _componentLabel(component: string): string {
  switch (component) {
    case "path_cluster":   return "path";
    case "family_shared":  return "family";
    case "asset_overlap":  return "assets";
    case "sector_overlap": return "sector";
    default:               return component;
  }
}

function _truncateHeadline(h: string, max: number = 56): string {
  if (!h) return "—";
  return h.length <= max ? h : h.slice(0, max - 1).trimEnd() + "…";
}

function ActiveEdgesTable({
  edges,
  nodesById,
}: {
  edges: EventGraphEdge[];
  nodesById: Map<number, EventGraphNode>;
}) {
  const active = edges
    .filter((e) => e.active)
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 8);

  return (
    <div className={cn(SECTION_CARD, "px-4 py-3")}>
      <p className="section-kicker mb-0.5">Active Spillover Edges</p>
      <p className="mb-3 text-[10px] text-muted-foreground/50">
        Parent → child links above the active threshold · decay-adjusted weights
      </p>
      {active.length === 0 ? (
        <p className="py-2 text-[11px] text-muted-foreground/55">
          No active spillovers in the current window.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-[9px] font-bold uppercase tracking-[0.15em] text-muted-foreground/60">
                <th className="pb-2 text-left">Parent → Child</th>
                <th className="pb-2 pl-3 text-right">Age</th>
                <th className="pb-2 pl-3 text-right">Weight</th>
                <th className="pb-2 pl-3 text-left">Components</th>
              </tr>
            </thead>
            <tbody>
              {active.map((e) => {
                const parent = nodesById.get(e.parent_id);
                const child = nodesById.get(e.child_id);
                return (
                  <tr
                    key={`${e.parent_id}-${e.child_id}`}
                    className="border-t border-border/20"
                  >
                    <td className="py-1.5 pr-2">
                      <div className="flex flex-col gap-0.5">
                        <span className="text-on-surface/85">
                          {_truncateHeadline(parent?.headline ?? `#${e.parent_id}`)}
                        </span>
                        <span className="text-muted-foreground/45">→</span>
                        <span className="text-on-surface/85">
                          {_truncateHeadline(child?.headline ?? `#${e.child_id}`)}
                        </span>
                      </div>
                    </td>
                    <td className="py-1.5 pl-3 text-right font-mono tabular-nums text-muted-foreground/70">
                      {e.age_days}d
                    </td>
                    <td
                      className={cn(
                        "py-1.5 pl-3 text-right font-mono tabular-nums",
                        _edgeWeightTone(e.weight, e.active),
                      )}
                    >
                      {e.weight.toFixed(2)}
                    </td>
                    <td className="py-1.5 pl-3">
                      <div className="flex flex-wrap gap-1">
                        {e.components_list.slice(0, 4).map((c) => (
                          <span
                            key={c.component}
                            className={cn(
                              "inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-[0.05em]",
                              _componentChipTone(c.component),
                            )}
                            title={`${c.component} · ${c.contribution}`}
                          >
                            {_componentLabel(c.component)}
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

interface CascadeHub {
  parent: EventGraphNode;
  children: Array<{ edge: EventGraphEdge; child: EventGraphNode }>;
  maxWeight: number;
}

function _buildCascadeHubs(
  edges: EventGraphEdge[],
  nodesById: Map<number, EventGraphNode>,
): CascadeHub[] {
  const byParent = new Map<number, EventGraphEdge[]>();
  for (const e of edges) {
    if (!e.active) continue;
    const arr = byParent.get(e.parent_id);
    if (arr) arr.push(e);
    else byParent.set(e.parent_id, [e]);
  }
  const hubs: CascadeHub[] = [];
  for (const [parentId, parentEdges] of byParent) {
    if (parentEdges.length < 2) continue;
    const parent = nodesById.get(parentId);
    if (!parent) continue;
    const children = parentEdges
      .sort((a, b) => b.weight - a.weight)
      .map((edge) => ({ edge, child: nodesById.get(edge.child_id) }))
      .filter((r): r is { edge: EventGraphEdge; child: EventGraphNode } => !!r.child);
    if (children.length === 0) continue;
    const maxWeight = Math.max(...children.map((c) => c.edge.weight));
    hubs.push({ parent, children, maxWeight });
  }
  hubs.sort(
    (a, b) =>
      b.children.length * b.maxWeight - a.children.length * a.maxWeight,
  );
  return hubs.slice(0, 6);
}

function CascadeHubsCard({
  edges,
  nodesById,
}: {
  edges: EventGraphEdge[];
  nodesById: Map<number, EventGraphNode>;
}) {
  const hubs = useMemo(
    () => _buildCascadeHubs(edges, nodesById),
    [edges, nodesById],
  );

  return (
    <div className={cn(SECTION_CARD, "px-4 py-3")}>
      <p className="section-kicker mb-0.5">Cascade Hubs</p>
      <p className="mb-3 text-[10px] text-muted-foreground/50">
        Parents with ≥2 active children · the archive's propagation spines
      </p>
      {hubs.length === 0 ? (
        <p className="py-2 text-[11px] text-muted-foreground/55">
          No events have spawned multiple active spillovers yet.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {hubs.map((hub) => (
            <div
              key={hub.parent.id}
              className="rounded-lg bg-surface-container/35 px-3 py-2"
            >
              <div className="flex items-start justify-between gap-3">
                <p className="text-[11px] font-medium text-on-surface/90">
                  {_truncateHeadline(hub.parent.headline, 72)}
                </p>
                <span className="whitespace-nowrap text-[9px] uppercase tracking-[0.1em] text-muted-foreground/55 tabular-nums">
                  {hub.children.length} children
                </span>
              </div>
              <p className="mb-2 text-[10px] text-muted-foreground/55 capitalize">
                {hub.parent.mechanism_family.replace(/_/g, " ")}
                {hub.parent.event_date ? ` · ${hub.parent.event_date}` : ""}
              </p>
              <div className="flex flex-col gap-1">
                {hub.children.slice(0, 4).map(({ edge, child }) => (
                  <div
                    key={`${edge.parent_id}-${edge.child_id}`}
                    className="flex items-center justify-between gap-2 text-[10.5px]"
                  >
                    <span className="flex-1 truncate text-on-surface/75">
                      → {_truncateHeadline(child.headline, 60)}
                    </span>
                    <span className="whitespace-nowrap font-mono tabular-nums text-muted-foreground/55">
                      {edge.age_days}d
                    </span>
                    <span
                      className={cn(
                        "whitespace-nowrap font-mono tabular-nums",
                        _edgeWeightTone(edge.weight, edge.active),
                      )}
                    >
                      {edge.weight.toFixed(2)}
                    </span>
                  </div>
                ))}
                {hub.children.length > 4 && (
                  <span className="text-[10px] text-muted-foreground/45">
                    +{hub.children.length - 4} more children
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function EventGraphSection() {
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.eventGraph(),
    queryFn: () => api.eventGraph(),
    staleTime: 5 * 60_000,
  });

  if (isLoading) {
    return (
      <div className={cn(SECTION_CARD, "px-4 py-3")}>
        <p className="section-kicker mb-3">Event Graph</p>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <Skeleton className="h-56 w-full rounded-xl" />
          <Skeleton className="h-56 w-full rounded-xl" />
        </div>
      </div>
    );
  }

  if (isError || !data) return null;
  const graph = data as EventGraphResponse;

  if (graph.total_events === 0) {
    return (
      <div className={cn(SECTION_CARD, "px-4 py-3")}>
        <p className="section-kicker mb-2">Event Graph</p>
        <p className="text-[11px] text-muted-foreground/55">
          No dated events in the archive to link yet.
        </p>
      </div>
    );
  }

  const nodesById = new Map(graph.nodes.map((n) => [n.id, n]));
  const activeShare = graph.total_edges > 0
    ? graph.active_edges / graph.total_edges
    : 0;

  return (
    <div id="event-graph-section" className="space-y-2">
      <div className={cn(SECTION_CARD, "px-4 py-2.5")}>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <p className="section-kicker">Event Graph</p>
            <p className="text-[10px] text-muted-foreground/50">
              Parent → child spillovers across the archive · half-life{" "}
              {graph.decay_half_life_days}d · window {graph.pair_window_days}d
            </p>
          </div>
          <div className="flex items-center gap-4 text-[10px] tabular-nums">
            <div className="flex flex-col items-end">
              <span className="nav-kicker text-muted-foreground/55">Events</span>
              <span className="text-[15px] font-bold leading-none text-on-surface">
                {graph.total_events}
              </span>
            </div>
            <div className="flex flex-col items-end">
              <span className="nav-kicker text-muted-foreground/55">Active edges</span>
              <span className="text-[15px] font-bold leading-none text-[#93d1d3]">
                {graph.active_edges}
                <span className="ml-1 text-[10px] font-normal text-muted-foreground/55">
                  / {graph.total_edges}
                </span>
              </span>
            </div>
            <div className="flex flex-col items-end">
              <span className="nav-kicker text-muted-foreground/55">Live share</span>
              <span className="text-[15px] font-bold leading-none text-on-surface/85">
                {Math.round(activeShare * 100)}%
              </span>
            </div>
          </div>
        </div>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <ActiveEdgesTable edges={graph.edges} nodesById={nodesById} />
        <CascadeHubsCard edges={graph.edges} nodesById={nodesById} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cohort comparison — side-by-side scenario-pack diff
// ---------------------------------------------------------------------------

const AXIS_LABELS: Record<string, string> = {
  repricing_path:     "Repricing path",
  hold_rate:          "Held 20d",
  failure_rate:       "Falsification",
  mean_20d:           "Mean 20d",
  mechanism_family:   "Family mix",
  stage:              "Stage mix",
  persistence_label:  "Persistence mix",
  regime:             "Regime mix",
};

const OUTCOME_AXES = new Set([
  "repricing_path", "hold_rate", "failure_rate", "mean_20d",
]);

function _magnitudeTone(mag: string): string {
  if (mag === "large")  return "text-[#ee7d77]";
  if (mag === "medium") return "text-on-surface/85";
  if (mag === "small")  return "text-on-surface/70";
  return "text-muted-foreground/55";
}

function _fmtCellValue(
  axis: string,
  side: "a" | "b",
  d: CohortComparisonDimension,
): string {
  if (!OUTCOME_AXES.has(axis)) {
    const top = side === "a" ? d.a_top : d.b_top;
    const share = side === "a" ? d.a_top_share : d.b_top_share;
    if (!top) return "—";
    return `${String(top).replace(/_/g, " ")} · ${Math.round((share ?? 0) * 100)}%`;
  }
  const v = side === "a" ? d.a_value : d.b_value;
  if (v === null || v === undefined) return "—";
  if (axis === "repricing_path") {
    const share = side === "a" ? d.a_share : d.b_share;
    const label = String(v).replace(/_/g, " ");
    return share !== undefined ? `${label} · ${Math.round(share * 100)}%` : label;
  }
  if (axis === "hold_rate" || axis === "failure_rate") {
    return `${Math.round(Number(v) * 100)}%`;
  }
  if (axis === "mean_20d") {
    const n = Number(v);
    const sign = n > 0 ? "+" : "";
    return `${sign}${n.toFixed(1)}%`;
  }
  return String(v);
}

function _divergenceTone(score: number): string {
  if (score >= 0.5) return "text-[#ee7d77]";
  if (score >= 0.25) return "text-on-surface/85";
  return "text-[#93d1d3]";
}

function ComparisonRow({ dim }: { dim: CohortComparisonDimension }) {
  const label = AXIS_LABELS[dim.axis] ?? dim.axis;
  const isOutcome = OUTCOME_AXES.has(dim.axis);
  return (
    <tr className="border-t border-border/20">
      <td className="py-1.5 pr-2 text-on-surface/85">
        <span className="font-medium">{label}</span>
        {!isOutcome && (
          <span className="ml-1.5 text-[9px] uppercase tracking-[0.1em] text-muted-foreground/45">
            structural
          </span>
        )}
      </td>
      <td className="py-1.5 pl-3 text-right font-mono tabular-nums text-on-surface/80">
        {_fmtCellValue(dim.axis, "a", dim)}
      </td>
      <td className="py-1.5 pl-3 text-right font-mono tabular-nums text-on-surface/80">
        {_fmtCellValue(dim.axis, "b", dim)}
      </td>
      <td
        className={cn(
          "py-1.5 pl-3 text-right font-mono tabular-nums text-[10px] uppercase tracking-[0.1em]",
          _magnitudeTone(dim.magnitude),
        )}
      >
        {dim.magnitude}
      </td>
    </tr>
  );
}

function CohortComparisonSection({
  packA,
  packB,
  setPackA,
  setPackB,
}: {
  packA: string;
  packB: string;
  setPackA: (v: string) => void;
  setPackB: (v: string) => void;
}) {

  const packOptionsQuery = useQuery({
    queryKey: qk.cohortResearch(),
    queryFn: () => api.cohortResearch(),
    staleTime: 5 * 60_000,
  });

  const { data, isLoading, isError } = useQuery({
    queryKey: qk.cohortComparison(packA, packB),
    queryFn: () => api.cohortComparison(packA, packB),
    staleTime: 5 * 60_000,
    enabled: packA !== packB,
  });

  const availablePacks = useMemo(() => {
    const live = packOptionsQuery.data?.packs
      ?.filter((p) => p.size > 0)
      .map((p) => p.pack)
      ?? [];
    // Fallback if cohort-research hasn't loaded yet.
    return live.length > 0
      ? live
      : ["tariff_cycle", "sanction_cycle", "supply_squeeze", "supply_relief",
         "funding_squeeze", "policy_surprise", "inflation_pressure", "de_escalation"];
  }, [packOptionsQuery.data]);

  const renderSelect = (
    value: string,
    setter: (v: string) => void,
    blocked: string,
  ) => (
    <select
      value={value}
      onChange={(e) => setter(e.target.value)}
      className={cn(
        "bg-surface-container-low rounded-md px-2 py-1 text-[11px]",
        "shadow-[inset_0_0_0_1px_rgba(71,70,86,0.35)]",
        "text-on-surface/90 capitalize focus:outline-none focus:shadow-[inset_0_0_0_1px_rgba(147,209,211,0.35)]",
      )}
    >
      {availablePacks.map((p) => (
        <option key={p} value={p} disabled={p === blocked}>
          {p.replace(/_/g, " ")}
        </option>
      ))}
    </select>
  );

  return (
    <div id="cohort-comparison-section" className={cn(SECTION_CARD, "px-4 py-3")}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="section-kicker">Side-by-side Cohort Comparison</p>
          <p className="text-[10px] text-muted-foreground/50">
            Diff two scenario packs across outcome + structural axes
          </p>
        </div>
        <div className="flex items-center gap-2 text-[11px]">
          {renderSelect(packA, setPackA, packB)}
          <span className="text-muted-foreground/45">vs</span>
          {renderSelect(packB, setPackB, packA)}
        </div>
      </div>

      {packA === packB ? (
        <p className="mt-4 text-[11px] text-muted-foreground/55">
          Pick two different packs to compare.
        </p>
      ) : isLoading ? (
        <div className="mt-3 space-y-2">
          <Skeleton className="h-6 w-full rounded" />
          <Skeleton className="h-32 w-full rounded" />
        </div>
      ) : isError || !data ? (
        <p className="mt-4 text-[11px] text-muted-foreground/55">
          Comparison failed to load.
        </p>
      ) : (
        <CohortComparisonBody data={data} />
      )}
    </div>
  );
}

function CohortComparisonBody({ data }: { data: CohortComparisonResponse }) {
  const { comparison } = data;
  const { a_label, b_label, a_size, b_size, divergence_score, headline_insight } = comparison;

  if (a_size === 0 || b_size === 0) {
    return (
      <div className="mt-3 rounded-lg bg-surface-container/40 px-3 py-2.5">
        <p className="text-[11px] text-muted-foreground/65">
          {headline_insight}
        </p>
      </div>
    );
  }

  return (
    <div className="mt-3 flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-surface-container/35 px-3 py-2">
        <p className="flex-1 min-w-[200px] text-[12px] leading-snug text-on-surface/80">
          {headline_insight}
        </p>
        <div className="flex items-center gap-4 text-[10px] tabular-nums">
          <div className="flex flex-col items-end">
            <span className="nav-kicker text-muted-foreground/55">Divergence</span>
            <span
              className={cn(
                "text-[15px] font-bold leading-none",
                _divergenceTone(divergence_score),
              )}
            >
              {divergence_score.toFixed(2)}
            </span>
          </div>
          <div className="flex flex-col items-end">
            <span className="nav-kicker text-muted-foreground/55">Confidence</span>
            <span
              className={cn(
                "text-[11px] font-semibold",
                comparison.confidence_basis === "deep"
                  ? "text-[#93d1d3]"
                  : comparison.confidence_basis === "medium"
                    ? "text-on-surface/80"
                    : "text-muted-foreground/55",
              )}
            >
              {comparison.confidence_basis}
            </span>
          </div>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-[9px] font-bold uppercase tracking-[0.15em] text-muted-foreground/60">
              <th className="pb-2 text-left">Axis</th>
              <th className="pb-2 pl-3 text-right">
                {a_label} <span className="text-muted-foreground/40">· n={a_size}</span>
              </th>
              <th className="pb-2 pl-3 text-right">
                {b_label} <span className="text-muted-foreground/40">· n={b_size}</span>
              </th>
              <th className="pb-2 pl-3 text-right">Δ</th>
            </tr>
          </thead>
          <tbody>
            {comparison.dimensions.map((d) => (
              <ComparisonRow key={d.axis} dim={d} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ScenarioPackGrid() {
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.cohortResearch(),
    queryFn: () => api.cohortResearch(),
    staleTime: 5 * 60_000,
  });

  if (isLoading) {
    return (
      <div className={cn(SECTION_CARD, "px-4 py-3")}>
        <p className="section-kicker mb-3">Scenario Pack Research</p>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-40 w-full rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  if (isError || !data) {
    return null;
  }

  const packs = (data as CohortResearchResponse).packs;
  const hasSignal = packs.some((p) => p.size > 0);

  if (!hasSignal) {
    return (
      <div className={cn(SECTION_CARD, "px-4 py-3")}>
        <p className="section-kicker mb-2">Scenario Pack Research</p>
        <p className="text-[11px] text-muted-foreground/55">
          No cohort matched any scenario pack yet — analyzed events will populate
          as mechanism families get tagged.
        </p>
      </div>
    );
  }

  const ordered = [...packs].sort((a, b) => b.size - a.size);

  return (
    <div className={cn(SECTION_CARD, "px-4 py-3")}>
      <p className="section-kicker mb-0.5">Scenario Pack Research</p>
      <p className="mb-3 text-[10px] text-muted-foreground/50">
        How each shock archetype actually repriced · {data.total_events} events scanned
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {ordered.map((p) => (
          <ScenarioPackCard key={p.pack} pack={p} />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cross-event correlation studies — research-workstation section
// ---------------------------------------------------------------------------
// Four compact panels in one card: family co-occurrence pairs, sector
// clusters, transmission-path signatures, and family × sector hit
// rates.  Deliberately dense — this is the archive-research cut, not a
// dashboard widget.

function _prettyFamily(fam: string): string {
  return fam
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function _prettySector(sec: string): string {
  return sec.charAt(0).toUpperCase() + sec.slice(1);
}

function _cesEmpty(hint: string) {
  return (
    <p className="py-3 text-center text-[10px] text-muted-foreground/40">
      {hint}
    </p>
  );
}

function FamilyCooccurrencePanel({ pairs }: { pairs: CrossEventFamilyPair[] }) {
  return (
    <div className="flex flex-col">
      <p className="section-kicker mb-0.5">Family Co-occurrence</p>
      <p className="mb-2 text-[10px] text-muted-foreground/45">
        Mechanism pairs clustering within a 7-day window
      </p>
      {pairs.length === 0 ? _cesEmpty("No recurring family pairs yet.") : (
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-[9px] font-bold uppercase tracking-[0.15em] text-muted-foreground/55">
              <th className="pb-2 text-left">Pair</th>
              <th className="pb-2 pl-3 text-right">n</th>
            </tr>
          </thead>
          <tbody>
            {pairs.map((p) => (
              <tr
                key={`${p.family_a}__${p.family_b}`}
                className="border-t border-border/20"
              >
                <td className="py-1.5 pr-2 text-on-surface/90">
                  <span className="font-medium">{_prettyFamily(p.family_a)}</span>
                  <span className="mx-1.5 text-muted-foreground/45">×</span>
                  <span className="font-medium">{_prettyFamily(p.family_b)}</span>
                </td>
                <td className="py-1.5 pl-3 text-right font-mono tabular-nums text-[#93d1d3]">
                  {p.count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function SectorClustersPanel({ pairs }: { pairs: CrossEventSectorPair[] }) {
  return (
    <div className="flex flex-col">
      <p className="section-kicker mb-0.5">Sector Clusters</p>
      <p className="mb-2 text-[10px] text-muted-foreground/45">
        Sector pairs co-appearing in the same event universe
      </p>
      {pairs.length === 0 ? _cesEmpty("No recurring sector pairs yet.") : (
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-[9px] font-bold uppercase tracking-[0.15em] text-muted-foreground/55">
              <th className="pb-2 text-left">Pair</th>
              <th className="pb-2 pl-3 text-right">n</th>
            </tr>
          </thead>
          <tbody>
            {pairs.map((p) => (
              <tr
                key={`${p.sector_a}__${p.sector_b}`}
                className="border-t border-border/20"
              >
                <td className="py-1.5 pr-2 text-on-surface/90">
                  <span className="font-medium">{_prettySector(p.sector_a)}</span>
                  <span className="mx-1.5 text-muted-foreground/45">+</span>
                  <span className="font-medium">{_prettySector(p.sector_b)}</span>
                </td>
                <td className="py-1.5 pl-3 text-right font-mono tabular-nums text-[#93d1d3]">
                  {p.count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function PathClustersPanel({ clusters }: { clusters: CrossEventPathCluster[] }) {
  return (
    <div className="flex flex-col">
      <p className="section-kicker mb-0.5">Path Signatures</p>
      <p className="mb-2 text-[10px] text-muted-foreground/45">
        Channel-only transmission paths that recur across events
      </p>
      {clusters.length === 0 ? _cesEmpty("No recurring path shapes yet.") : (
        <div className="flex flex-col gap-2">
          {clusters.map((c, i) => {
            const topFamilies = Object.entries(c.families)
              .sort((a, b) => b[1] - a[1])
              .slice(0, 3);
            return (
              <div
                key={`${c.signature.join("→")}__${i}`}
                className="border-t border-border/20 pt-1.5 first:border-t-0 first:pt-0"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-1 overflow-hidden">
                    {c.signature.map((ch, idx) => (
                      <span key={idx} className="flex items-center gap-1">
                        <span className="rounded-sm bg-surface-container px-1.5 py-0.5 text-[9.5px] font-medium tabular-nums text-on-surface/85">
                          {ch}
                        </span>
                        {idx < c.signature.length - 1 ? (
                          <span className="text-[9px] text-muted-foreground/40">→</span>
                        ) : null}
                      </span>
                    ))}
                  </div>
                  <span className="font-mono tabular-nums text-[11px] text-[#93d1d3]">
                    {c.count}
                  </span>
                </div>
                {topFamilies.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {topFamilies.map(([fam, cnt]) => (
                      <span
                        key={fam}
                        className="text-[9px] text-muted-foreground/55"
                      >
                        {_prettyFamily(fam)}
                        <span className="ml-1 text-muted-foreground/35">·{cnt}</span>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function CombinationOutcomesPanel({ rows }: { rows: CrossEventCombination[] }) {
  return (
    <div className="flex flex-col">
      <p className="section-kicker mb-0.5">Family × Sector Hit Rates</p>
      <p className="mb-2 text-[10px] text-muted-foreground/45">
        Cross-cut vs the per-family breakdown — the strongest signal combos
      </p>
      {rows.length === 0 ? _cesEmpty("No combinations with sufficient sample.") : (
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-[9px] font-bold uppercase tracking-[0.15em] text-muted-foreground/55">
              <th className="pb-2 text-left">Family · Sector</th>
              <th className="pb-2 pl-3 text-right">Hit · n</th>
              <th className="pb-2 pl-3 text-right">V / C</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const directional = r.validated + r.contradicted;
              return (
                <tr
                  key={`${r.mechanism_family}__${r.sector}`}
                  className="border-t border-border/20"
                >
                  <td className="py-1.5 pr-2">
                    <span className="font-medium text-on-surface/90">
                      {_prettyFamily(r.mechanism_family)}
                    </span>
                    <span className="mx-1.5 text-muted-foreground/45">·</span>
                    <span className="text-on-surface/75">{_prettySector(r.sector)}</span>
                  </td>
                  <td
                    className={cn(
                      "py-1.5 pl-3 text-right font-mono tabular-nums",
                      _hitRateTone(r.hit_rate, directional),
                    )}
                  >
                    {_fmtHitRate(r.hit_rate, directional)}
                  </td>
                  <td className="py-1.5 pl-3 text-right font-mono tabular-nums">
                    <span className="text-[#6ec6a5]">{r.validated}</span>
                    <span className="text-muted-foreground/40"> / </span>
                    <span className="text-[#ee7d77]">{r.contradicted}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

function CrossEventStudiesSection() {
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.crossEventStudies(),
    queryFn: () => api.crossEventStudies(),
    staleTime: 5 * 60_000,
  });

  if (isLoading) {
    return <Skeleton className="h-56 w-full rounded-xl" />;
  }

  if (isError || !data) {
    // Quiet failure — the surface degrades, doesn't dominate the research tab.
    return null;
  }

  const studies = data as CrossEventStudiesResponse;
  const allEmpty =
    studies.family_cooccurrence.length === 0
    && studies.sector_clusters.length === 0
    && studies.path_clusters.length === 0
    && studies.combination_outcomes.length === 0;

  // Collapse to nothing when the archive is too thin for any study —
  // "cross-event correlations" of 1 event is a box with four "no data"
  // rows, which adds noise without information.
  if (allEmpty) return null;

  return (
    <div id="cross-event-studies-section" className={cn(SECTION_CARD, "px-4 py-3")}>
      <div className="mb-3 flex items-baseline justify-between">
        <div>
          <p className="section-kicker mb-0.5">Cross-Event Correlations</p>
          <p className="text-[10px] text-muted-foreground/50">
            Archive-native research · {studies.total_events} events ·
            {` `}
            {studies.window_days}-day co-occurrence window
          </p>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
        <FamilyCooccurrencePanel pairs={studies.family_cooccurrence} />
        <SectorClustersPanel pairs={studies.sector_clusters} />
        <PathClustersPanel clusters={studies.path_clusters} />
        <CombinationOutcomesPanel rows={studies.combination_outcomes} />
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Saved Studies — compact, session-style cards for reusable research
// workflows (cohort comparison / correlation study / scenario pack /
// cascade view).  Clicking "Load" reopens the study by driving the
// matching section below: cohort_comparison sets the lifted packA/packB
// state, the others scroll to their anchor.  Nothing here executes the
// study — the downstream sections re-query against the stored config.
// ---------------------------------------------------------------------------

export const STUDY_TYPE_LABEL: Record<SavedStudyType, string> = {
  cohort_comparison:      "Cohort diff",
  correlation_study:      "Correlation",
  scenario_pack_research: "Scenario pack",
  cascade_view:           "Cascade",
  portfolio_view:         "Portfolio view",
};

export const STUDY_TYPE_ORDER: SavedStudyType[] = [
  "portfolio_view",
  "cohort_comparison",
  "scenario_pack_research",
  "correlation_study",
  "cascade_view",
];

/** Group saved studies by their ``study_type`` in the canonical
 *  {@link STUDY_TYPE_ORDER}.  Every type slot is initialised so consumers
 *  can iterate the order verbatim — empty types map to an empty array. */
export function groupSavedStudies(
  studies: SavedStudy[] | null | undefined,
): Map<SavedStudyType, SavedStudy[]> {
  const out = new Map<SavedStudyType, SavedStudy[]>();
  for (const t of STUDY_TYPE_ORDER) out.set(t, []);
  for (const s of studies ?? []) {
    out.get(s.study_type)?.push(s);
  }
  return out;
}

/** Turn "tariff_cycle" -> "tariff cycle" for chip labels. */
function _humanize(s: string): string {
  return s.replace(/_/g, " ");
}

/** Compact summary chips describing a study's config — visible on the card. */
export function _studyConfigChips(study: SavedStudy): string[] {
  const c = study.config ?? {};
  switch (study.study_type) {
    case "cohort_comparison": {
      const fa = (c.filter_a ?? {}) as Record<string, string>;
      const fb = (c.filter_b ?? {}) as Record<string, string>;
      const labelA = (c.label_a as string) ?? _summariseFilter(fa) ?? "all";
      const labelB = (c.label_b as string) ?? _summariseFilter(fb) ?? "all";
      return [`${labelA} vs ${labelB}`];
    }
    case "scenario_pack_research":
      return [_humanize((c.pack_name as string) ?? "—")];
    case "correlation_study":
      return [`limit ${(c.limit as number) ?? "default"}`];
    case "cascade_view": {
      const chips: string[] = [];
      if (c.family) chips.push(_humanize(c.family as string));
      if (c.focal_event_id) chips.push(`focal #${c.focal_event_id}`);
      if (typeof c.min_weight === "number")
        chips.push(`≥ ${(c.min_weight as number).toFixed(2)}`);
      if (c.active_only) chips.push("active only");
      return chips.length ? chips : ["all"];
    }
    case "portfolio_view": {
      // Mirror the validators in saved_studies._validate_portfolio_view —
      // every filter that is set becomes a chip; an all-empty config
      // means "default portfolio" so we render that explicitly.
      const chips: string[] = [];
      if (typeof c.quality_tier === "string") {
        // Show the same compact label the portfolio row renders so the
        // saved-view chip matches the engine-phase strip and keeps the raw
        // ``actionable`` engine token out of viewer-facing copy.
        chips.push(
          formatQualityTier(c.quality_tier as PortfolioEntry["quality_tier"]) ??
            _humanize(c.quality_tier),
        );
      }
      if (typeof c.tradable === "boolean") chips.push(c.tradable ? "tradable" : "not tradable");
      if (typeof c.mechanism_subtype === "string" && c.mechanism_subtype) {
        chips.push(_humanize(c.mechanism_subtype));
      }
      if (typeof c.queue === "string") chips.push(`queue: ${_humanize(c.queue)}`);
      if (typeof c.mover_window === "string") chips.push(`${c.mover_window} movers`);
      if (typeof c.thesis_state === "string") chips.push(_humanize(c.thesis_state));
      if (typeof c.proof_quality === "string") chips.push(_humanize(c.proof_quality));
      if (typeof c.low_information === "boolean") {
        chips.push(c.low_information ? "low-info only" : "exclude low-info");
      }
      return chips.length ? chips : ["default portfolio"];
    }
  }
}

/** Map a saved ``portfolio_view`` config into the typed
 *  {@link PortfolioFilters} shape consumed by ``api.portfolio``.  The
 *  config keys are validated server-side (see
 *  ``_validate_portfolio_view``) so we just narrow the types here. */
export function _portfolioViewConfigToFilters(
  config: Record<string, unknown>,
): PortfolioFilters {
  const out: PortfolioFilters = {};
  if (typeof config.thesis_state === "string") out.thesis_state = config.thesis_state;
  if (typeof config.proof_quality === "string") out.proof_quality = config.proof_quality;
  if (typeof config.low_information === "boolean") out.low_information = config.low_information;
  if (typeof config.queue === "string") out.queue = config.queue;
  if (
    config.mover_window === "today" ||
    config.mover_window === "weekly" ||
    config.mover_window === "persistent" ||
    config.mover_window === "market"
  ) {
    out.mover_window = config.mover_window;
  }
  if (
    config.quality_tier === "actionable" ||
    config.quality_tier === "watch_only" ||
    config.quality_tier === "low_information"
  ) {
    out.quality_tier = config.quality_tier;
  }
  if (typeof config.tradable === "boolean") out.tradable = config.tradable;
  if (typeof config.mechanism_subtype === "string" && config.mechanism_subtype) {
    out.mechanism_subtype = config.mechanism_subtype;
  }
  return out;
}

/** Stable string fingerprint for a {@link PortfolioFilters} value —
 *  used as the React Query cache key so different filter combos don't
 *  collide.  Returns empty string when no filters are set, which
 *  matches the bare-list cache slot. */
function _filtersFingerprint(f: PortfolioFilters): string {
  const keys = Object.keys(f).sort() as (keyof PortfolioFilters)[];
  const parts: string[] = [];
  for (const k of keys) {
    const v = f[k];
    if (v === undefined) continue;
    parts.push(`${k}=${String(v)}`);
  }
  return parts.join("|");
}

function _summariseFilter(f: Record<string, string>): string | null {
  const keys = Object.keys(f);
  if (keys.length === 0) return null;
  const parts = keys.slice(0, 2).map((k) => `${k.replace(/^regime_/, "")}=${_humanize(f[k] ?? "")}`);
  return parts.join(" · ");
}

function _formatUpdated(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const h = Math.floor(diffMs / 3_600_000);
    if (h < 1) return "just now";
    if (h < 24) return `${h}h ago`;
    const days = Math.floor(h / 24);
    if (days < 14) return `${days}d ago`;
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return iso.slice(0, 10);
  }
}

function SavedStudiesSection({
  packA,
  packB,
  onLoadCohortPair,
  onLoadScenarioPack,
  onLoadCorrelationStudy,
  onLoadCascadeView,
  onLoadPortfolioView,
}: {
  packA: string;
  packB: string;
  onLoadCohortPair: (a: string, b: string) => void;
  onLoadScenarioPack: (pack: string) => void;
  onLoadCorrelationStudy: () => void;
  onLoadCascadeView: () => void;
  /** Replay a saved ``portfolio_view`` — switches to the portfolio
   *  tab with the saved filters applied. */
  onLoadPortfolioView: (name: string, filters: PortfolioFilters) => void;
}) {
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.savedStudies(),
    queryFn: () => api.savedStudies(),
    staleTime: 60_000,
  });

  const [saveDialogOpen, setSaveDialogOpen] = useState(false);

  const saveMutation = useMutation({
    mutationFn: (body: SaveStudyRequest) => api.saveStudy(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolio", "saved-studies"] });
      setSaveDialogOpen(false);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteStudy(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolio", "saved-studies"] });
    },
  });

  const groups = useMemo(() => {
    const payload = data as SavedStudiesListResponse | undefined;
    return groupSavedStudies(payload?.studies);
  }, [data]);

  const handleLoad = (study: SavedStudy) => {
    const c = study.config as Record<string, unknown>;
    switch (study.study_type) {
      case "cohort_comparison": {
        const fa = (c.filter_a ?? {}) as Record<string, string>;
        const fb = (c.filter_b ?? {}) as Record<string, string>;
        if (fa.scenario_pack && fb.scenario_pack) {
          onLoadCohortPair(fa.scenario_pack, fb.scenario_pack);
        } else {
          onLoadCohortPair(packA, packB);
        }
        break;
      }
      case "scenario_pack_research":
        onLoadScenarioPack((c.pack_name as string) ?? "");
        break;
      case "correlation_study":
        onLoadCorrelationStudy();
        break;
      case "cascade_view":
        onLoadCascadeView();
        break;
      case "portfolio_view": {
        onLoadPortfolioView(study.name, _portfolioViewConfigToFilters(c));
        break;
      }
    }
  };

  const total = (data as SavedStudiesListResponse | undefined)?.studies.length ?? 0;

  return (
    <div className={cn(SECTION_CARD, "px-4 py-3")}>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex items-center gap-2">
          <Bookmark className="h-3.5 w-3.5 text-[#93d1d3]" />
          <div>
            <p className="section-kicker mb-0.5">Saved Study Views</p>
            <p className="text-[10px] text-muted-foreground/50">
              Reopen cohort diffs, correlations, scenario packs, and cascade
              views · {total} saved
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setSaveDialogOpen(true)}
          disabled={packA === packB}
          className={cn(
            "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11px]",
            "bg-surface-container-low text-on-surface/85",
            "shadow-[inset_0_0_0_1px_rgba(147,209,211,0.25)]",
            "hover:shadow-[inset_0_0_0_1px_rgba(147,209,211,0.55)]",
            "transition-shadow disabled:opacity-40 disabled:cursor-not-allowed",
          )}
          title="Save current cohort comparison as a view"
        >
          <BookmarkPlus className="h-3 w-3" />
          Save current pair
        </button>
      </div>

      {isLoading ? (
        <Skeleton className="h-20 w-full rounded-lg" />
      ) : isError ? (
        <p className="text-[11px] text-muted-foreground/55">
          Saved studies failed to load.
        </p>
      ) : total === 0 ? (
        <div className="rounded-lg bg-surface-container/40 px-3 py-6 text-center">
          <FolderOpen className="mx-auto mb-1.5 h-5 w-5 text-muted-foreground/25" />
          <p className="text-[11px] text-muted-foreground/60">
            No saved study views yet.
          </p>
          <p className="mt-0.5 text-[10px] text-muted-foreground/45">
            Save a cohort comparison, scenario pack, or cascade view to return
            to it in one click.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
          {STUDY_TYPE_ORDER.flatMap((t) =>
            (groups.get(t) ?? []).map((study) => (
              <SavedStudyCard
                key={study.id}
                study={study}
                onLoad={() => handleLoad(study)}
                onDelete={() => {
                  if (
                    window.confirm(
                      `Delete saved study "${study.name}"? This cannot be undone.`,
                    )
                  ) {
                    deleteMutation.mutate(study.id);
                  }
                }}
                deleting={
                  deleteMutation.isPending
                  && deleteMutation.variables === study.id
                }
              />
            )),
          )}
        </div>
      )}

      {saveDialogOpen && (
        <SaveCohortPairDialog
          packA={packA}
          packB={packB}
          onClose={() => setSaveDialogOpen(false)}
          onSubmit={(name, description, overwrite) =>
            saveMutation.mutate({
              study_type: "cohort_comparison",
              name,
              description,
              overwrite,
              config: {
                filter_a: { scenario_pack: packA },
                filter_b: { scenario_pack: packB },
                label_a: _humanize(packA),
                label_b: _humanize(packB),
              },
            })
          }
          error={
            saveMutation.error instanceof Error
              ? saveMutation.error.message
              : null
          }
          pending={saveMutation.isPending}
        />
      )}
    </div>
  );
}

function SavedStudyCard({
  study,
  onLoad,
  onDelete,
  deleting,
}: {
  study: SavedStudy;
  onLoad: () => void;
  onDelete: () => void;
  deleting: boolean;
}) {
  const chips = _studyConfigChips(study);
  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-lg bg-surface-container/40 px-3 py-2.5",
        "shadow-[inset_0_0_0_1px_rgba(71,70,86,0.25)]",
        "transition-shadow hover:shadow-[inset_0_0_0_1px_rgba(147,209,211,0.35)]",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-0.5">
          <p className="truncate text-[12px] font-semibold text-on-surface/90">
            {study.name}
          </p>
          <div className="flex flex-wrap items-center gap-1.5 text-[9px] uppercase tracking-[0.14em] text-muted-foreground/55">
            <span className="rounded bg-surface-container-low px-1.5 py-[1px] text-[#93d1d3]/80">
              {STUDY_TYPE_LABEL[study.study_type]}
            </span>
            <span className="text-muted-foreground/45">
              {_formatUpdated(study.updated_at)}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={onLoad}
            className={cn(
              "rounded-md px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]",
              "bg-[#004f51]/30 text-[#93d1d3]",
              "shadow-[inset_0_0_0_1px_rgba(147,209,211,0.35)]",
              "hover:bg-[#004f51]/55 transition-colors",
            )}
          >
            Load
          </button>
          <button
            type="button"
            onClick={onDelete}
            disabled={deleting}
            aria-label={`Delete saved study ${study.name}`}
            className={cn(
              "rounded-md p-1 text-muted-foreground/55",
              "hover:text-[#ee7d77] hover:bg-[#bb5551]/10",
              "disabled:opacity-30 disabled:cursor-not-allowed transition-colors",
            )}
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      </div>
      {study.description && (
        <p className="text-[11px] leading-snug text-muted-foreground/70 line-clamp-2">
          {study.description}
        </p>
      )}
      <div className="flex flex-wrap gap-1.5">
        {chips.map((chip, i) => (
          <span
            key={i}
            className="rounded-sm bg-surface-container-low px-1.5 py-[1px] text-[10px] capitalize text-on-surface/70"
          >
            {chip}
          </span>
        ))}
      </div>
    </div>
  );
}

function SaveCohortPairDialog({
  packA,
  packB,
  onClose,
  onSubmit,
  error,
  pending,
}: {
  packA: string;
  packB: string;
  onClose: () => void;
  onSubmit: (name: string, description: string, overwrite: boolean) => void;
  error: string | null;
  pending: boolean;
}) {
  const [name, setName] = useState(`${_humanize(packA)} vs ${_humanize(packB)}`);
  const [description, setDescription] = useState("");
  const [overwrite, setOverwrite] = useState(false);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className={cn(
          "w-full max-w-sm rounded-xl bg-card px-5 py-4",
          "shadow-[0_8px_32px_rgba(0,0,0,0.45),inset_0_0_0_1px_rgba(71,70,86,0.45)]",
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <p className="section-kicker mb-3">Save cohort pair</p>
        <div className="flex flex-col gap-2.5 text-[11px]">
          <label className="flex flex-col gap-1">
            <span className="nav-kicker text-muted-foreground/55">Name</span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={cn(
                "rounded-md bg-surface-container-low px-2 py-1.5 text-on-surface/90",
                "shadow-[inset_0_0_0_1px_rgba(71,70,86,0.35)]",
                "focus:outline-none focus:shadow-[inset_0_0_0_1px_rgba(147,209,211,0.45)]",
              )}
              autoFocus
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="nav-kicker text-muted-foreground/55">
              Description (optional)
            </span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              className={cn(
                "rounded-md bg-surface-container-low px-2 py-1.5 text-on-surface/90",
                "shadow-[inset_0_0_0_1px_rgba(71,70,86,0.35)]",
                "focus:outline-none focus:shadow-[inset_0_0_0_1px_rgba(147,209,211,0.45)]",
                "resize-none",
              )}
            />
          </label>
          <label className="flex items-center gap-2 text-muted-foreground/70">
            <input
              type="checkbox"
              checked={overwrite}
              onChange={(e) => setOverwrite(e.target.checked)}
            />
            Overwrite if a view with this name already exists
          </label>
          {error && (
            <p className="rounded bg-[#bb5551]/15 px-2 py-1 text-[10px] text-[#ee7d77]">
              {error}
            </p>
          )}
          <div className="mt-1 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md px-2.5 py-1 text-[11px] text-muted-foreground/70 hover:text-on-surface/90"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={pending || !name.trim()}
              onClick={() => onSubmit(name.trim(), description.trim(), overwrite)}
              className={cn(
                "rounded-md px-3 py-1 text-[11px] font-semibold",
                "bg-[#004f51]/50 text-[#93d1d3]",
                "shadow-[inset_0_0_0_1px_rgba(147,209,211,0.4)]",
                "hover:bg-[#004f51]/75 transition-colors",
                "disabled:opacity-40 disabled:cursor-not-allowed",
              )}
            >
              {pending ? "Saving…" : "Save view"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Research export — portable bundles for saved studies + ad-hoc runs
// ---------------------------------------------------------------------------

const AD_HOC_STUDIES: ResearchExportStudyInline[] = [
  {
    study_type: "scenario_pack_research",
    name: "Tariff cycle research",
    config: { pack_name: "tariff_cycle" },
  },
  {
    study_type: "scenario_pack_research",
    name: "Funding squeeze research",
    config: { pack_name: "funding_squeeze" },
  },
  {
    study_type: "correlation_study",
    name: "Cross-event correlation study",
    config: {},
  },
  {
    study_type: "cascade_view",
    name: "Active cascade view",
    config: { active_only: true },
  },
  {
    study_type: "cohort_comparison",
    name: "Tariff × Funding comparison",
    config: {
      filter_a: { scenario_pack: "tariff_cycle" },
      filter_b: { scenario_pack: "funding_squeeze" },
      label_a:  "Tariff cycles",
      label_b:  "Funding squeezes",
    },
  },
];

function _triggerDownload(content: string, mimeType: string, filename: string): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function ResearchExportBar() {
  const savedStudiesQuery = useQuery({
    queryKey: qk.savedStudies(),
    queryFn: () => api.savedStudies(),
    staleTime: 60_000,
  });

  const [busy, setBusy] = useState<null | "json" | "md">(null);
  const [error, setError] = useState<string | null>(null);

  const savedCount = savedStudiesQuery.data?.studies.length ?? 0;

  const buildRequestBody = () => {
    const savedIds = savedStudiesQuery.data?.studies.map((s) => s.id) ?? [];
    return savedIds.length > 0
      ? { saved_study_ids: savedIds }
      : { studies: AD_HOC_STUDIES };
  };

  const handleExport = async (format: "json" | "md") => {
    setError(null);
    setBusy(format);
    try {
      const body = buildRequestBody();
      const ts = new Date().toISOString().slice(0, 10);
      if (format === "md") {
        const md = await api.researchExportMarkdown(body);
        _triggerDownload(md, "text/markdown;charset=utf-8", `research_export_${ts}.md`);
      } else {
        const bundle = await api.researchExportJson(body);
        const pretty = JSON.stringify(bundle, null, 2);
        _triggerDownload(pretty, "application/json", `research_export_${ts}.json`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed.");
    } finally {
      setBusy(null);
    }
  };

  const savedPreview = savedStudiesQuery.data?.studies.slice(0, 4) ?? [];

  return (
    <div className={cn(SECTION_CARD, "px-4 py-2.5")}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex-1 min-w-[200px]">
          <p className="section-kicker">Research Export</p>
          <p className="text-[10px] text-muted-foreground/55">
            {savedCount > 0
              ? `Bundles ${savedCount} saved ${savedCount === 1 ? "study" : "studies"} against the live archive`
              : `No saved studies — exports a default ${AD_HOC_STUDIES.length}-study research bundle`}
          </p>
          {savedPreview.length > 0 && (
            <p className="mt-1 flex flex-wrap gap-1 text-[10px] text-muted-foreground/60">
              {savedPreview.map((s) => (
                <span
                  key={s.id}
                  className="inline-flex items-center rounded-full bg-surface-container px-2 py-0.5"
                >
                  {s.name}
                </span>
              ))}
              {savedCount > savedPreview.length && (
                <span className="text-muted-foreground/45">
                  +{savedCount - savedPreview.length} more
                </span>
              )}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            disabled={busy !== null}
            onClick={() => handleExport("json")}
            className={cn(
              "rounded-md px-2.5 py-1 text-[11px] font-medium",
              "shadow-[inset_0_0_0_1px_rgba(71,70,86,0.35)] text-on-surface/85",
              "hover:shadow-[inset_0_0_0_1px_rgba(147,209,211,0.35)]",
              busy === "json" && "opacity-60",
            )}
          >
            {busy === "json" ? "Exporting…" : "Download JSON"}
          </button>
          <button
            disabled={busy !== null}
            onClick={() => handleExport("md")}
            className={cn(
              "rounded-md px-2.5 py-1 text-[11px] font-medium",
              "bg-[#93d1d3]/12 text-[#93d1d3]",
              "hover:bg-[#93d1d3]/20",
              busy === "md" && "opacity-60",
            )}
          >
            {busy === "md" ? "Exporting…" : "Download Markdown"}
          </button>
        </div>
      </div>
      {error && (
        <p className="mt-2 text-[11px] text-[#ee7d77]">
          {error}
        </p>
      )}
    </div>
  );
}

function ResearchTab({
  onLoadPortfolioView,
}: {
  /** Replay a saved ``portfolio_view`` — caller is responsible for
   *  switching to the portfolio tab and applying the filters. */
  onLoadPortfolioView: (name: string, filters: PortfolioFilters) => void;
}) {
  // Cohort-comparison pack state is lifted so SavedStudiesSession can drive
  // it — "Load" on a saved cohort_comparison study sets these and the
  // comparison below re-queries against the stored filter.
  const [packA, setPackA] = useState<string>("tariff_cycle");
  const [packB, setPackB] = useState<string>("funding_squeeze");

  const { data, isLoading, isError } = useQuery({
    queryKey: qk.trackRecordBreakdown(),
    queryFn: () => api.trackRecordBreakdown(),
    staleTime: 5 * 60_000,
  });

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-20 w-full rounded-xl" />
        <Skeleton className="h-36 w-full rounded-xl" />
        <Skeleton className="h-36 w-full rounded-xl" />
        <Skeleton className="h-36 w-full rounded-xl" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className={cn(SECTION_CARD, "p-6 text-center")}>
        <p className="text-[12px] text-muted-foreground">
          Research analytics failed to load — check the backend is running.
        </p>
      </div>
    );
  }

  const directional = data.validated_total + data.contradicted_total;
  if (directional === 0) {
    return (
      <div className={cn(SECTION_CARD, "px-6 py-10 text-center")}>
        <BookOpen className="mx-auto mb-3 h-8 w-8 text-muted-foreground/20" />
        <p className="text-sm font-medium text-muted-foreground">
          No resolved outcomes yet.
        </p>
        <p className="mt-1 text-xs text-muted-foreground/50">
          Track record slices appear once analyzed events carry a directional
          follow-through read (revisit snapshot or market-check direction tag).
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <ResearchHeadlineStrip data={data} />
      <ResearchExportBar />
      <ArchiveDriftSection />
      <SavedStudiesSection
        packA={packA}
        packB={packB}
        onLoadCohortPair={(a, b) => {
          setPackA(a);
          setPackB(b);
          document
            .getElementById("cohort-comparison-section")
            ?.scrollIntoView({ behavior: "smooth", block: "start" });
        }}
        onLoadScenarioPack={(pack) => {
          document
            .getElementById(`scenario-pack-${pack}`)
            ?.scrollIntoView({ behavior: "smooth", block: "start" });
        }}
        onLoadCorrelationStudy={() =>
          document
            .getElementById("cross-event-studies-section")
            ?.scrollIntoView({ behavior: "smooth", block: "start" })
        }
        onLoadCascadeView={() =>
          document
            .getElementById("event-graph-section")
            ?.scrollIntoView({ behavior: "smooth", block: "start" })
        }
        onLoadPortfolioView={onLoadPortfolioView}
      />
      <ScenarioPackGrid />
      <EventGraphSection />
      <CohortComparisonSection
        packA={packA}
        packB={packB}
        setPackA={setPackA}
        setPackB={setPackB}
      />
      <CrossEventStudiesSection />

      {/* Track-record section header — gives the three breakdown tables
          a chapter rhythm matching the design package. */}
      <div className="flex items-baseline justify-between gap-3 pt-2 pb-1 border-b border-white/[0.05]">
        <h3 className="font-headline text-[16px] font-bold tracking-tight text-on-surface">
          Track record
        </h3>
        <span className="text-[11px] text-muted-foreground/55">
          how mechanisms, regimes, and proof disciplines actually resolved
        </span>
      </div>

      <BreakdownTable
        title="By Mechanism Family"
        kicker="Which archetypes have actually played out"
        keyPrefix="fam"
        buckets={data.by_mechanism_family}
        emptyHint="No family-tagged outcomes yet."
      />
      <BreakdownTable
        title="By Compound Regime"
        kicker="Reflation / stagflation / funding-stress / … performance"
        keyPrefix="comp"
        buckets={data.by_compound_regime}
        emptyHint="No compound-regime-tagged outcomes yet."
      />
      <BreakdownTable
        title="By Inflation × Policy Stance"
        kicker="Regime-vector axis pair — the oldest slice so sample is deepest"
        keyPrefix="reg"
        buckets={data.by_regime}
        emptyHint="No axis-regime-tagged outcomes yet."
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Portfolio card
// ---------------------------------------------------------------------------

function PortfolioCard({
  entry,
  onOpen,
}: {
  entry: PortfolioEntry;
  onOpen: (e: PortfolioEntry) => void;
}) {
  const bens = entry.beneficiaries.slice(0, 3);
  const los = entry.losers.slice(0, 3);
  const tickers = entry.market_tickers.slice(0, 7);
  const extraTickers = entry.market_tickers.length - tickers.length;

  const stale = getStaleDisplay(entry.stale_signal);
  const qc = useQueryClient();
  const { mutate: doRefresh, isPending: refreshing } = useMutation({
    mutationFn: () => api.refreshMarket(entry.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.portfolio() });
    },
  });

  const qualityLabel = formatQualityTier(entry.quality_tier);
  const tradable = tradableFlag(entry.actionability_check);
  const subtype = formatSubtype(
    entry.mechanism_subtype,
    (entry as { mechanism_family?: string | null }).mechanism_family,
  );
  const warnings = compactWarnings(entry.quality_warnings);
  const reason = (entry.thesis_state_reason || "").trim() || undefined;
  const tierTitle = reason
    ? `${qualityLabel ? qualityLabel + " — " : ""}${reason}`
    : undefined;
  const showEnginePhase =
    qualityLabel !== null ||
    tradable !== null ||
    subtype !== null ||
    warnings.length > 0;
  const tierToneClass =
    entry.quality_tier === "actionable"
      ? "text-[#93d1d3] border-[#93d1d3]/30"
      : entry.quality_tier === "watch_only"
        ? "text-muted-foreground/90"
        : entry.quality_tier === "low_information"
          ? "text-muted-foreground/60"
          : "";
  // Low-info reads are *no calls*, not bearish calls.  Suppress the
  // validation badge entirely (no thesis to validate) and dim the
  // bearish-coded loser block + contradicting ticker chips so the row
  // reads as diagnostic rather than as a failed directional bet.
  const lowInfo = isLowInfoRow(entry.quality_tier);

  return (
    <div className="relative group">
      <button
        onClick={() => onOpen(entry)}
        className="w-full text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 rounded-xl"
      >
      <div
        className={cn(
          SECTION_CARD,
          "p-4 transition-[box-shadow] hover:shadow-[inset_0_0_0_1px_rgba(147,209,211,0.25),0_6px_20px_rgba(0,0,0,0.3)]",
        )}
      >
        {/* ── Top row: date + classification ── */}
        <div className="mb-2.5 flex items-center justify-between gap-2">
          <span className="font-mono text-[11px] text-muted-foreground">
            {entry.event_date ?? "—"}
          </span>
          <div className="flex items-center gap-1.5 flex-wrap justify-end">
            {entry.stage && (
              <span className="metric-chip">{entry.stage}</span>
            )}
            {entry.persistence && (
              <span className="metric-chip">{entry.persistence}</span>
            )}
            {entry.rating && <RatingBadge value={entry.rating} />}
          </div>
        </div>

        {/* ── Engine-phase compact signals ── */}
        {showEnginePhase && (
          <div
            data-testid="engine-phase-strip"
            className="mb-2 flex flex-wrap items-center gap-1.5"
          >
            {qualityLabel && (
              <span
                title={tierTitle}
                className={cn(
                  "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.04em]",
                  "bg-surface-container",
                  tierToneClass,
                )}
              >
                {qualityLabel}
              </span>
            )}
            {tradable === true && (
              <span
                title="Actionability check: tradable"
                className="inline-flex items-center rounded-full bg-[#93d1d3]/10 px-2 py-0.5 text-[10px] font-semibold text-[#93d1d3]"
              >
                tradable
              </span>
            )}
            {tradable === false && (
              <span
                title="Actionability check: not tradable"
                className="inline-flex items-center rounded-full bg-surface-container px-2 py-0.5 text-[10px] font-semibold text-muted-foreground/70"
              >
                not tradable
              </span>
            )}
            {subtype && (
              <span
                title="mechanism subtype"
                className="inline-flex items-center rounded-full bg-surface-container px-2 py-0.5 text-[10px] font-medium text-muted-foreground/80"
              >
                {subtype}
              </span>
            )}
            {warnings.length > 0 && (
              <span
                data-testid="engine-phase-warnings"
                title={warnings.join(", ")}
                className="inline-flex items-center gap-1 rounded-full bg-[#ee7d77]/10 px-2 py-0.5 text-[10px] font-semibold text-[#ee7d77]"
              >
                <span aria-hidden="true">!</span>
                {warnings.length}
              </span>
            )}
          </div>
        )}

        {/* ── Headline ── */}
        <h3 className="mb-1.5 line-clamp-2 text-[13px] font-semibold leading-snug tracking-[-0.01em] transition-colors group-hover:text-primary/90">
          {entry.headline}
        </h3>

        {/* ── Mechanism summary ── */}
        <p className="mb-3 line-clamp-2 text-[12px] leading-relaxed text-muted-foreground">
          {entry.mechanism_summary}
        </p>

        {/* ── Winners / Losers ── */}
        {(bens.length > 0 || los.length > 0) && (
          <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1">
            {bens.length > 0 && (
              <div className="flex min-w-0 items-center gap-1.5">
                <TrendingUp className="h-3 w-3 shrink-0 text-[#6ec6a5]" />
                <span className="truncate text-[11px] text-[#6ec6a5]/80">
                  {bens.join(" · ")}
                  {entry.beneficiaries.length > 3 &&
                    ` +${entry.beneficiaries.length - 3}`}
                </span>
              </div>
            )}
            {los.length > 0 && (
              <div className="flex min-w-0 items-center gap-1.5">
                <TrendingDown
                  className={cn(
                    "h-3 w-3 shrink-0",
                    lowInfo ? "text-muted-foreground/40" : "text-[#ee7d77]",
                  )}
                />
                <span
                  className={cn(
                    "truncate text-[11px]",
                    lowInfo
                      ? "text-muted-foreground/55"
                      : "text-[#ee7d77]/80",
                  )}
                >
                  {los.join(" · ")}
                  {entry.losers.length > 3 &&
                    ` +${entry.losers.length - 3}`}
                </span>
              </div>
            )}
          </div>
        )}

        {/* ── Ticker chips ── */}
        {tickers.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-1">
            {tickers.map((t) => {
              const supported = t.direction_tag?.startsWith("supports");
              const contradicted = t.direction_tag?.startsWith("contradicts");
              // On a low-info row a "contradicts" tag isn't a thesis
              // failure (no thesis was committed) — render it as a
              // neutral diagnostic chip rather than bearish red.
              const showSupported = supported && !lowInfo;
              const showContradicted = contradicted && !lowInfo;
              return (
                <span
                  key={t.symbol}
                  className={cn(
                    "inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 font-mono text-[10px] font-medium",
                    showSupported &&
                      "bg-[#6ec6a5]/10 text-[#6ec6a5]",
                    showContradicted &&
                      "bg-[#ee7d77]/10 text-[#ee7d77]",
                    !showSupported &&
                      !showContradicted &&
                      "bg-surface-container text-muted-foreground",
                  )}
                >
                  {t.symbol}
                  {t.return_5d !== null && (
                    <span className="opacity-60">
                      {t.return_5d >= 0 ? "+" : ""}
                      {t.return_5d.toFixed(1)}%
                    </span>
                  )}
                </span>
              );
            })}
            {extraTickers > 0 && (
              <span className="self-center text-[10px] text-muted-foreground/50">
                +{extraTickers}
              </span>
            )}
          </div>
        )}

        {/* ── Bottom strip: validation + lifecycle | freshness · revisit · confidence
              Two logical groups separated by a centered divider so five
              signals at 10–11px don't blur together.  ValidationBadge is
              suppressed on low-info rows (no thesis to validate against). */}
        <div className="flex items-center justify-between gap-2 border-t border-border/30 pt-2.5">
          <div className="flex items-center gap-2 min-w-0 flex-wrap">
            {!lowInfo && (
              <ValidationBadge
                outcome={entry.validation_outcome}
                ratio={entry.support_ratio}
              />
            )}
            {entry.persistence_signal && (
              <LifecycleBadge sig={entry.persistence_signal} />
            )}
          </div>
          <div className="flex items-center gap-2">
            {stale.showIndicator && (
              <div className="flex items-center gap-1">
                <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", stale.dotClass)} />
                <span className="text-[10px] text-muted-foreground/75">{stale.label}</span>
              </div>
            )}
            {stale.showIndicator && (
              <span className="h-3 w-px bg-border/40" aria-hidden="true" />
            )}
            <RevisitDots snapshots={entry.revisit_snapshots} />
            <span className="h-3 w-px bg-border/40" aria-hidden="true" />
            <ConfidenceChip value={entry.confidence} />
          </div>
        </div>

      </div>
    </button>

    {/* Refresh button — outside the main button to avoid nesting */}
    {stale.showRefresh && (
      <button
        onClick={(e) => { e.stopPropagation(); doRefresh(); }}
        title="Refresh market data"
        disabled={refreshing}
        className={cn(
          "absolute top-2 right-2 rounded p-1 transition-all text-muted-foreground/50 hover:text-amber-400",
          refreshing ? "opacity-100" : "opacity-0 group-hover:opacity-100",
        )}
      >
        <RefreshCw className={cn("h-3 w-3", refreshing && "animate-spin")} />
      </button>
    )}
  </div>
  );
}

// ---------------------------------------------------------------------------
// Engine-field filter bar
// ---------------------------------------------------------------------------

const QUALITY_TIER_OPTIONS: ReadonlyArray<{
  value: QualityTierFilter;
  label: string;
}> = [
  { value: "all",             label: "All" },
  { value: "actionable",      label: "High-quality" },
  { value: "watch_only",      label: "Watch" },
  { value: "low_information", label: "Low info" },
];

const TRADABLE_OPTIONS: ReadonlyArray<{
  value: TradableFilter;
  label: string;
}> = [
  { value: "all",          label: "All" },
  { value: "tradable",     label: "Tradable" },
  { value: "not_tradable", label: "Not tradable" },
  { value: "unknown",      label: "Unknown" },
];

function EngineFilterBar({
  filters,
  onChange,
  subtypeOptions,
  totalCount,
  filteredCount,
}: {
  filters: EngineFilters;
  onChange: (next: EngineFilters) => void;
  subtypeOptions: string[];
  totalCount: number;
  filteredCount: number;
}) {
  const active = isEngineFilterActive(filters);
  const selectClass = cn(
    "h-7 rounded-full bg-white/[0.03] px-3 text-[11.5px] font-medium",
    "text-on-surface-variant hover:text-on-surface hover:bg-white/[0.06]",
    "transition-colors focus:outline-none focus:ring-1 focus:ring-primary/40",
    "border-0 appearance-none cursor-pointer",
  );
  return (
    <div
      data-testid="engine-filter-bar"
      className="flex flex-wrap items-center gap-2 text-[11px]"
    >
      <span className="text-on-surface-variant/55 text-[10px] font-medium uppercase tracking-[0.12em] mr-1">
        Filter
      </span>
      <select
        data-testid="engine-filter-quality-tier"
        aria-label="Filter by quality tier"
        className={selectClass}
        value={filters.qualityTier}
        onChange={(e) =>
          onChange({
            ...filters,
            qualityTier: e.target.value as QualityTierFilter,
          })
        }
      >
        {QUALITY_TIER_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.value === "all" ? "Tier · all" : o.label}
          </option>
        ))}
      </select>
      <select
        data-testid="engine-filter-tradable"
        aria-label="Filter by tradable"
        className={selectClass}
        value={filters.tradable}
        onChange={(e) =>
          onChange({
            ...filters,
            tradable: e.target.value as TradableFilter,
          })
        }
      >
        {TRADABLE_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.value === "all" ? "Tradable · all" : o.label}
          </option>
        ))}
      </select>
      <select
        data-testid="engine-filter-subtype"
        aria-label="Filter by mechanism subtype"
        className={selectClass}
        disabled={subtypeOptions.length === 0}
        value={filters.subtype}
        onChange={(e) =>
          onChange({ ...filters, subtype: e.target.value })
        }
      >
        <option value="all">
          {subtypeOptions.length === 0 ? "Subtype · n/a" : "Subtype · all"}
        </option>
        {subtypeOptions.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      {active && (
        <>
          <span className="font-mono text-[10.5px] text-on-surface-variant/60 tabular-nums">
            {filteredCount}/{totalCount}
          </span>
          <button
            type="button"
            data-testid="engine-filter-clear"
            onClick={() => onChange(ENGINE_FILTERS_DEFAULT)}
            className="text-[11px] text-on-surface-variant/70 hover:text-on-surface underline-offset-2 hover:underline"
          >
            clear
          </button>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

interface PortfolioPageProps {
  onAnalyze: (headline: string, opts?: { eventId?: number }) => void;
}

// ---------------------------------------------------------------------------
// LandingMoversRail — top-of-workspace "Still Moving Markets" strip.
// ---------------------------------------------------------------------------
//
// Approved design package landing priority #1: surface event-linked
// movers above the ranked portfolio feed so the user lands on what's
// actively moving, not on a chronological wall.  Reads /movers/persistent
// (already gated to high-conviction items by ``is_high_conviction_persistent``
// on the backend) — no new endpoint, no new filter.  Renders nothing
// when the surface is empty so the rail can't push the ranked feed
// below the fold on cold-start installs.

function _moverPctTone(v: number | null | undefined): string {
  if (v == null) return "text-on-surface-variant/45";
  if (v > 0) return "text-primary";
  if (v < 0) return "text-error-dim";
  return "text-on-surface-variant/45";
}

function _fmtMoverPct(v: number | null | undefined): string {
  if (v == null) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}%`;
}

function LandingMoverRow({
  mover,
  onAnalyze,
}: {
  mover: MarketMover;
  onAnalyze: (headline: string, opts?: { eventId?: number; context?: string }) => void;
}) {
  const lead = mover.tickers[0];
  const days = mover.days_since_event ?? 0;
  return (
    <button
      type="button"
      onClick={() => onAnalyze(mover.headline, { eventId: mover.event_id })}
      className={cn(
        "group w-full flex items-center gap-3 px-3 py-2 rounded-md text-left",
        "bg-surface-container-low",
        "shadow-[inset_0_0_0_1px_rgba(71,70,86,0.18)]",
        "hover:shadow-[inset_0_0_0_1px_rgba(147,209,211,0.32)] hover:bg-surface-container-low/70",
        "transition-shadow",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40",
      )}
    >
      <span className="inline-flex items-center gap-1.5 px-1.5 py-0.5 text-[11px] font-bold uppercase tracking-[0.16em] text-on-surface-variant/80">
        <span className="h-1 w-1 rotate-45 bg-primary" />
        Persist
      </span>
      <span className="font-mono tabular-nums text-[11px] text-primary/75 shrink-0">
        {days}d
      </span>
      <span className="min-w-0 flex-1 text-[12px] text-on-surface/90 line-clamp-1">
        {mover.headline}
      </span>
      {lead && (
        <span className="font-mono text-[11px] text-on-surface-variant/85 shrink-0">
          {lead.symbol}
        </span>
      )}
      {lead && (
        <span
          className={cn(
            "font-mono tabular-nums text-[12px] font-semibold w-[58px] text-right shrink-0",
            _moverPctTone(lead.return_5d),
          )}
        >
          {_fmtMoverPct(lead.return_5d)}
        </span>
      )}
    </button>
  );
}

function LandingMoversRail({
  onAnalyze,
}: {
  onAnalyze: (headline: string, opts?: { eventId?: number; context?: string }) => void;
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.moversPersistent(),
    queryFn: () => api.moversPersistent(),
    staleTime: 30 * 60_000,
  });

  // Soft-fail: a movers backend issue must not block the landing — the
  // ranked portfolio feed below is still useful on its own.
  if (isError) return null;

  if (isLoading) {
    return (
      <div className="space-y-2">
        <div className="flex items-baseline justify-between">
          <p className="section-kicker">Still moving markets</p>
          <span className="text-[11px] text-muted-foreground/55">loading…</span>
        </div>
        <Skeleton className="h-10 w-full rounded-md" />
        <Skeleton className="h-10 w-full rounded-md" />
        <Skeleton className="h-10 w-full rounded-md" />
      </div>
    );
  }

  const movers = (data ?? []).slice(0, 3);
  if (movers.length === 0) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <p className="section-kicker">Still moving markets</p>
          <p className="text-[11px] text-muted-foreground/55">
            High-conviction events beyond the initial reaction window
          </p>
        </div>
        <span className="font-mono tabular-nums text-[11px] text-muted-foreground/60">
          {data?.length ?? 0} active
        </span>
      </div>
      <div className="flex flex-col gap-1.5">
        {movers.map((m) => (
          <LandingMoverRow key={m.event_id} mover={m} onAnalyze={onAnalyze} />
        ))}
      </div>
    </div>
  );
}

export function PortfolioPage({ onAnalyze }: PortfolioPageProps) {
  const [activeTab, setActiveTab] = useState<
    "portfolio" | "research" | "simulator"
  >("portfolio");
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [engineFilters, setEngineFilters] = useState<EngineFilters>(
    ENGINE_FILTERS_DEFAULT,
  );
  /** Active saved-view replay.  When set, the portfolio query goes
   *  through the server-side filter envelope and the local
   *  EngineFilterBar is hidden — the view's filters drive the page. */
  const [replayedView, setReplayedView] = useState<
    { name: string; filters: PortfolioFilters } | null
  >(null);

  const replayActive = replayedView !== null
    && hasActivePortfolioFilters(replayedView.filters);
  const replayFingerprint = replayActive
    ? _filtersFingerprint(replayedView.filters)
    : "";

  const { data, isLoading, isError } = useQuery({
    queryKey: qk.portfolio(replayFingerprint || undefined),
    queryFn: () =>
      api.portfolio(
        replayActive ? { filters: replayedView!.filters } : {},
      ),
    staleTime: 5 * 60_000,
  });

  // Always extract the entry array regardless of whether the wire
  // returned a bare ``PortfolioEntry[]`` (no filters) or the
  // ``PortfolioFilteredResponse`` envelope (filters active).
  const entries = useMemo(() => unwrapPortfolioItems(data), [data]);

  const subtypeOptions = useMemo(() => collectSubtypes(entries), [entries]);
  const filteredEntries = useMemo(
    () => (replayActive ? entries : applyEngineFilters(entries, engineFilters)),
    [entries, engineFilters, replayActive],
  );
  const filtersActive = !replayActive && isEngineFilterActive(engineFilters);

  function switchTab(tab: "portfolio" | "research" | "simulator") {
    if (tab !== activeTab) setEngineFilters(ENGINE_FILTERS_DEFAULT);
    setActiveTab(tab);
  }

  function loadPortfolioView(name: string, filters: PortfolioFilters) {
    setEngineFilters(ENGINE_FILTERS_DEFAULT);
    setReplayedView({ name, filters });
    setActiveTab("portfolio");
  }

  function clearReplayedView() {
    setReplayedView(null);
  }

  function toggleId(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  return (
    <ResearchPageShell className="mx-auto max-w-3xl space-y-5">
      {/* ── Header ── */}
      <div className="flex items-end justify-between gap-4 pb-1">
        <div>
          <h2 className="font-headline text-[22px] font-bold leading-tight tracking-[-0.015em] text-on-surface">
            Research Portfolio
          </h2>
          <p className="mt-1 text-[12.5px] text-on-surface-variant/75">
            Strongest past analyses ranked by confidence, market validation,
            and follow-through.
          </p>
        </div>
        {entries.length > 0 && (
          <span
            className={cn(
              "shrink-0 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1",
              "bg-white/[0.04] text-[11px] font-medium text-on-surface-variant",
            )}
          >
            <span className="font-mono tabular-nums text-on-surface">{entries.length}</span>
            <span className="text-on-surface-variant/55">entries</span>
          </span>
        )}
      </div>

      {/* ── Saved-view replay banner ── Only renders when a saved
          ``portfolio_view`` is active.  Server-side filters drive
          ``entries``; the local EngineFilterBar is hidden so the two
          filter layers don't compete. */}
      {replayActive && (
        <div
          className={cn(
            SECTION_CARD,
            "px-3 py-2 flex items-center gap-3 flex-wrap",
            "shadow-[inset_0_0_0_1px_rgba(147,209,211,0.25)]",
          )}
        >
          <Bookmark className="h-3.5 w-3.5 text-[#93d1d3]" />
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-semibold text-on-surface/90 truncate">
              Saved view · {replayedView!.name}
            </p>
            <p className="text-[11px] text-muted-foreground/65 truncate">
              {Object.keys(replayedView!.filters).length} filter{Object.keys(replayedView!.filters).length === 1 ? "" : "s"} applied server-side · clear to return to the ranked default
            </p>
          </div>
          <button
            type="button"
            onClick={clearReplayedView}
            className={cn(
              "rounded-md px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.1em]",
              "bg-surface-container-low text-on-surface/85",
              "shadow-[inset_0_0_0_1px_rgba(71,70,86,0.4)]",
              "hover:shadow-[inset_0_0_0_1px_rgba(147,209,211,0.4)] transition-shadow",
            )}
          >
            Clear view
          </button>
        </div>
      )}

      {/* ── Tab bar (only once data is loaded) ── */}
      {entries.length > 0 && (
        <div className="inline-flex items-center gap-1 rounded-md bg-white/[0.04] p-[3px]">
          {(["portfolio", "research", "simulator"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => switchTab(tab)}
              className={cn(
                "rounded-[5px] px-3 py-1 text-[11.5px] font-medium capitalize transition-colors",
                activeTab === tab
                  ? "bg-accent text-on-surface"
                  : "text-on-surface-variant/70 hover:text-on-surface",
              )}
            >
              {tab}
            </button>
          ))}
        </div>
      )}

      {/* ── Still Moving Markets rail (portfolio tab, no saved view) ──
          Landing priority #1 per the approved design package.  Sits
          ABOVE the engine-quality filter bar so the user lands on
          event-linked movers first, the queue-style filters second,
          and the ranked feed third. */}
      {activeTab === "portfolio" && !replayActive && (
        <LandingMoversRail onAnalyze={onAnalyze} />
      )}

      {/* ── Engine-field filter bar (portfolio tab, no saved view active) ── */}
      {entries.length > 0 && activeTab === "portfolio" && !replayActive && (
        <EngineFilterBar
          filters={engineFilters}
          onChange={setEngineFilters}
          subtypeOptions={subtypeOptions}
          totalCount={entries.length}
          filteredCount={filteredEntries.length}
        />
      )}

      {/* ── Loading skeletons ── */}
      {isLoading && (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-40 w-full rounded-xl" />
          ))}
        </div>
      )}

      {/* ── Error ── */}
      {isError && (
        <div className={cn(SECTION_CARD, "p-6 text-center")}>
          <p className="text-sm text-muted-foreground">
            Failed to load portfolio — check the backend is running.
          </p>
        </div>
      )}

      {/* ── Empty state ── */}
      {!isLoading && !isError && entries.length === 0 && !replayActive && (
        <div className={cn(SECTION_CARD, "px-6 py-12 text-center")}>
          <BookOpen className="mx-auto mb-3 h-8 w-8 text-muted-foreground/20" />
          <p className="text-sm font-medium text-muted-foreground">
            No portfolio entries yet.
          </p>
          <p className="mt-1 text-xs text-muted-foreground/50">
            Analyze events with real headlines to build your research record.
          </p>
        </div>
      )}

      {/* ── Portfolio tab ── ranked event studies (landing priority #3).
          The Still Moving Markets rail (priority #1) and engine-quality
          facets (priority #2) render above this block. */}
      {activeTab === "portfolio" && (entries.length > 0 || replayActive) && (
        <div className="space-y-3">
          {filteredEntries.length === 0 ? (
            <div
              data-testid="engine-filter-empty"
              className={cn(SECTION_CARD, "px-6 py-8 text-center")}
            >
              <p className="text-sm font-medium text-muted-foreground">
                No portfolio entries match the current filters.
              </p>
              <p className="mt-1 text-[11px] text-muted-foreground/65">
                {replayActive
                  ? "Saved view returned no rows — clear the view or pick a different one."
                  : filtersActive
                    ? `0 of ${entries.length} entries — clear a filter to broaden the view.`
                    : null}
              </p>
            </div>
          ) : (
            filteredEntries.map((entry) => (
              <PortfolioCard
                key={entry.id}
                entry={entry}
                onOpen={(e) => onAnalyze(e.headline, { eventId: e.id })}
              />
            ))
          )}
        </div>
      )}

      {/* ── Research tab — mechanism-family + regime track record ── */}
      {entries.length > 0 && activeTab === "research" && (
        <ResearchTab onLoadPortfolioView={loadPortfolioView} />
      )}

      {/* ── Simulator tab ── */}
      {entries.length > 0 && activeTab === "simulator" && (
        <SimulatorTab
          entries={entries}
          selectedIds={selectedIds}
          onToggle={toggleId}
        />
      )}
    </ResearchPageShell>
  );
}
