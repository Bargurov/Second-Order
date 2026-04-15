import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type PortfolioEntry,
  type PersistenceSignal,
  type SimulatePortfolioResponse,
  type SimulatePosition,
  type SimulateWarning,
  getStaleDisplay,
} from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import {
  BookOpen,
  TrendingUp,
  TrendingDown,
  CheckCircle2,
  XCircle,
  Circle,
  Minus,
  RefreshCw,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Design constants — matches analysis-view tonal hierarchy
// ---------------------------------------------------------------------------

const SECTION_CARD =
  "bg-surface-container-low rounded-xl shadow-[inset_0_0_0_1px_rgba(71,70,86,0.35),0_4px_12px_rgba(0,0,0,0.2)]";

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
                        key={pos.symbol}
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
                <TrendingDown className="h-3 w-3 shrink-0 text-[#ee7d77]" />
                <span className="truncate text-[11px] text-[#ee7d77]/80">
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
              return (
                <span
                  key={t.symbol}
                  className={cn(
                    "inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 font-mono text-[10px] font-medium",
                    supported &&
                      "bg-[#6ec6a5]/10 text-[#6ec6a5]",
                    contradicted &&
                      "bg-[#ee7d77]/10 text-[#ee7d77]",
                    !supported &&
                      !contradicted &&
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

        {/* ── Bottom strip: validation + lifecycle + revisit + confidence ── */}
        <div className="flex items-center justify-between gap-2 border-t border-border/30 pt-2.5">
          <div className="flex items-center gap-2 min-w-0 flex-wrap">
            <ValidationBadge
              outcome={entry.validation_outcome}
              ratio={entry.support_ratio}
            />
            {entry.persistence_signal && (
              <LifecycleBadge sig={entry.persistence_signal} />
            )}
          </div>
          <div className="flex items-center gap-3">
            {stale.showIndicator && (
              <div className="flex items-center gap-1">
                <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", stale.dotClass)} />
                <span className="text-[10px] text-muted-foreground/60">{stale.label}</span>
              </div>
            )}
            <RevisitDots snapshots={entry.revisit_snapshots} />
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
// Page
// ---------------------------------------------------------------------------

interface PortfolioPageProps {
  onAnalyze: (headline: string, opts?: { eventId?: number }) => void;
}

export function PortfolioPage({ onAnalyze }: PortfolioPageProps) {
  const [activeTab, setActiveTab] = useState<"portfolio" | "simulator">(
    "portfolio",
  );
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  const { data, isLoading, isError } = useQuery({
    queryKey: qk.portfolio(),
    queryFn: () => api.portfolio(),
    staleTime: 5 * 60_000,
  });

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
    <div className="mx-auto max-w-3xl space-y-4">
      {/* ── Header ── */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-[15px] font-semibold tracking-[-0.01em]">
            Research Portfolio
          </h2>
          <p className="mt-0.5 text-[12px] text-muted-foreground">
            Strongest past analyses ranked by confidence, market validation,
            and follow-through.
          </p>
        </div>
        {data && data.length > 0 && (
          <span className="metric-chip mt-0.5 shrink-0">
            {data.length} entries
          </span>
        )}
      </div>

      {/* ── Tab bar (only once data is loaded) ── */}
      {data && data.length > 0 && (
        <div className="flex gap-0 border-b border-border/30">
          {(["portfolio", "simulator"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={cn(
                "-mb-px px-4 py-2 text-[11px] font-medium capitalize transition-colors",
                activeTab === tab
                  ? "border-b-2 border-primary text-primary"
                  : "text-muted-foreground hover:text-on-surface",
              )}
            >
              {tab}
            </button>
          ))}
        </div>
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
      {!isLoading && !isError && data?.length === 0 && (
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

      {/* ── Portfolio tab ── */}
      {data && data.length > 0 && activeTab === "portfolio" && (
        <div className="space-y-3">
          {data.map((entry) => (
            <PortfolioCard
              key={entry.id}
              entry={entry}
              onOpen={(e) => onAnalyze(e.headline, { eventId: e.id })}
            />
          ))}
        </div>
      )}

      {/* ── Simulator tab ── */}
      {data && data.length > 0 && activeTab === "simulator" && (
        <SimulatorTab
          entries={data}
          selectedIds={selectedIds}
          onToggle={toggleId}
        />
      )}
    </div>
  );
}
