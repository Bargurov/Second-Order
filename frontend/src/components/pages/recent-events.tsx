import { useState, useCallback, useMemo, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { qk } from "@/lib/queryKeys";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  RefreshCw,
  ChevronRight,
  ChevronDown,
  ArrowLeft,
  Star,
  StickyNote,
  TrendingUp,
  TrendingDown,
  Minus,
  ShieldCheck,
  Shield,
  ShieldAlert,
  Calendar,
  Clock,
  Network,
  Save,
  Loader2,
  Archive,
  Search,
  Trash2,
  FileDown,
  Pin,
  CheckSquare,
  Square,
  PackageOpen,
} from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Sparkline } from "@/components/ui/sparkline";
import { api, ApiError, type SavedEvent, type Ticker, type ExportFormat, type CascadeNode, type PersistenceSignal, getStaleDisplay, type EventsQuery, type EventsPage, type ArchiveQuality, type ValidationStatusV2 } from "@/lib/api";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Skeletons
// ---------------------------------------------------------------------------

function EventRowSkeleton() {
  return (
    <div className="rounded border border-transparent px-2.5 py-2">
      <div className="flex items-start gap-2.5">
        <Skeleton className="mt-0.5 hidden h-6 w-6 rounded sm:block" />
        <div className="min-w-0 flex-1 space-y-1.5">
          <Skeleton className="h-3.5 w-4/5" />
          <div className="flex gap-1">
            <Skeleton className="h-3.5 w-14 rounded" />
            <Skeleton className="h-3.5 w-16 rounded" />
            <Skeleton className="h-3.5 w-12 rounded" />
          </div>
          <Skeleton className="h-3 w-28" />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const RATING_META: Record<string, { icon: React.ElementType; color: string; bg: string }> = {
  good:  { icon: TrendingUp,   color: "val-pos",        bg: "bg-emerald-500/10 border-emerald-500/20" },
  mixed: { icon: Minus,        color: "text-gray-400", bg: "bg-gray-500/10 border-gray-500/20" },
  poor:  { icon: TrendingDown, color: "val-neg",        bg: "bg-red-400/10 border-red-400/20" },
};

const CONFIDENCE_META: Record<string, { icon: React.ElementType; color: string }> = {
  high:   { icon: ShieldCheck, color: "val-pos" },
  medium: { icon: Shield,      color: "text-gray-400" },
  low:    { icon: ShieldAlert, color: "val-neg" },
};

const QUALITY_FILTERS: readonly { value: ArchiveQuality | null; label: string }[] = [
  { value: null, label: "Default" },
  { value: "pending", label: "Pending" },
  { value: "degraded", label: "Degraded" },
  { value: "no_tickers", label: "No tickers" },
  { value: "market_checked", label: "Checked" },
  { value: "clean", label: "Clean" },
];

const VALIDATION_V2_FILTERS: readonly { value: ValidationStatusV2; label: string }[] = [
  { value: "pending", label: "Pending" },
  { value: "unresolved", label: "Unresolved" },
  { value: "validated", label: "Validated" },
  { value: "contradicted", label: "Contradicted" },
];

function pct(v: number | null | undefined): string {
  if (v == null) return "\u2014";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function directionIcon(tag: string | null) {
  switch (tag) {
    case "supporting":
      return <TrendingUp className="h-3 w-3 val-pos" />;
    case "contradicting":
      return <TrendingDown className="h-3 w-3 val-neg" />;
    default:
      return <Minus className="h-3 w-3 val-flat" />;
  }
}

function LifecycleBadge({ sig }: { sig: PersistenceSignal }) {
  if (sig.status === "watching") return null;
  const cfg = {
    active:   { color: "text-[#93d1d3]", bg: "bg-[#93d1d3]/10 border-[#93d1d3]/20" },
    fading:   { color: "text-[#ee7d77]", bg: "bg-[#ee7d77]/10 border-[#ee7d77]/20" },
    resolved: { color: "text-muted-foreground", bg: "bg-surface-container-highest border-border/30" },
  } as const;
  const { color, bg } = cfg[sig.status];
  return (
    <span
      className={cn("inline-flex items-center rounded-full border px-1.5 py-px text-[9px] font-medium", color, bg)}
      title={sig.evidence}
    >
      {sig.label}
    </span>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.18em] text-on-surface-variant">
      <span className="h-3 w-0.5 rounded-full bg-primary" />
      {children}
    </h3>
  );
}

function formatTimestamp(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleDateString("en-GB", {
      day: "numeric", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

// ---------------------------------------------------------------------------
// Client-side filter — pure function, exported for tests
// ---------------------------------------------------------------------------

export interface ArchiveFilters {
  search: string;
  stage: string | null;
  confidence: string | null;
  persistence?: string | null;
  rating?: string | null;
  dateFrom?: string | null;
  dateTo?: string | null;
}

export function filterEvents(
  events: SavedEvent[],
  filters: ArchiveFilters,
): SavedEvent[] {
  let result = events;
  const q = filters.search.toLowerCase().trim();
  if (q) {
    result = result.filter(
      (e) =>
        e.headline.toLowerCase().includes(q) ||
        (e.mechanism_summary || "").toLowerCase().includes(q),
    );
  }
  if (filters.stage) {
    result = result.filter((e) => e.stage === filters.stage);
  }
  if (filters.confidence) {
    result = result.filter((e) => e.confidence === filters.confidence);
  }
  if (filters.persistence) {
    result = result.filter((e) => e.persistence === filters.persistence);
  }
  if (filters.rating) {
    result = result.filter((e) => (e.rating ?? "") === filters.rating);
  }
  if (filters.dateFrom) {
    const from = filters.dateFrom;
    result = result.filter((e) => {
      const d = e.event_date ?? e.timestamp.slice(0, 10);
      return d >= from;
    });
  }
  if (filters.dateTo) {
    const to = filters.dateTo;
    result = result.filter((e) => {
      const d = e.event_date ?? e.timestamp.slice(0, 10);
      return d <= to;
    });
  }
  return result;
}

// ---------------------------------------------------------------------------
// Client-side sort — pure function, exported for tests
// ---------------------------------------------------------------------------

export type SortKey = "newest" | "oldest" | "impact" | "confidence";

const _CONF_RANK: Record<string, number> = { high: 0, medium: 1, low: 2 };

function _maxAbsReturn(e: SavedEvent): number {
  let best = 0;
  for (const t of e.market_tickers) {
    const r = t.return_5d;
    if (r != null) {
      const a = Math.abs(r);
      if (a > best) best = a;
    }
  }
  return best;
}

export function sortEvents(events: SavedEvent[], key: SortKey): SavedEvent[] {
  const copy = [...events];
  switch (key) {
    case "newest":
      // Sort by id DESC — matches the server's ``ORDER BY id DESC`` used by
      // /events, so pagination stays consistent page-to-page.  id is the
      // auto-increment primary key, so newer events always have higher ids
      // and ties cannot occur.  ``timestamp`` is a secondary key only for
      // legacy rows lacking id.
      copy.sort((a, b) => {
        if (b.id !== a.id) return b.id - a.id;
        return b.timestamp > a.timestamp ? 1 : b.timestamp < a.timestamp ? -1 : 0;
      });
      break;
    case "oldest":
      copy.sort((a, b) => {
        if (a.id !== b.id) return a.id - b.id;
        return a.timestamp > b.timestamp ? 1 : a.timestamp < b.timestamp ? -1 : 0;
      });
      break;
    case "impact":
      // Page-local sort: the server paginates in id DESC so switching to an
      // impact ranking re-orders the current page only.  This is intentional —
      // server-side impact sort is out of scope here.
      copy.sort((a, b) => _maxAbsReturn(b) - _maxAbsReturn(a));
      break;
    case "confidence":
      // Page-local sort (see impact comment above).
      copy.sort((a, b) => (_CONF_RANK[a.confidence] ?? 3) - (_CONF_RANK[b.confidence] ?? 3));
      break;
  }
  return copy;
}

// ---------------------------------------------------------------------------
// Delete row state — exported for tests
// ---------------------------------------------------------------------------

export type DeleteRowState = "idle" | "confirm" | "deleting" | "error";

export interface PendingDelete {
  id: number;
  phase: "confirm" | "deleting" | "error";
}

export function deriveDeleteState(
  eventId: number,
  pending: PendingDelete | null,
): DeleteRowState {
  if (pending?.id === eventId) return pending.phase;
  return "idle";
}

// ---------------------------------------------------------------------------
// Export row state — exported for tests
// ---------------------------------------------------------------------------

export type ExportRowState = "idle" | "exporting" | "error";

export function deriveExportState(
  eventId: number,
  exportingId: number | null,
  exportErrorId: number | null,
): ExportRowState {
  if (exportingId === eventId) return "exporting";
  if (exportErrorId === eventId) return "error";
  return "idle";
}

// ---------------------------------------------------------------------------
// Export format helpers — exported for tests
// ---------------------------------------------------------------------------

const _EXPORT_EXT: Record<ExportFormat, string> = {
  text: "txt",
  markdown: "md",
  csv: "csv",
  json: "json",
};

const _EXPORT_LABEL: Record<ExportFormat, string> = {
  text: "txt",
  markdown: "md",
  csv: "csv",
  json: "json",
};

export const EXPORT_FORMATS: readonly ExportFormat[] = ["text", "markdown", "csv", "json"] as const;

/** Derive the download filename for a single-event export. Pure — no I/O. */
export function deriveExportFilename(eventId: number, headline: string, format: ExportFormat): string {
  const safe = headline.slice(0, 40).replace(/[^a-zA-Z0-9_-]/g, "_");
  return `event_${eventId}_${safe}.${_EXPORT_EXT[format]}`;
}

/** Derive the download filename for a bulk export. Pure — no I/O. */
export function deriveBulkExportFilename(format: "csv" | "json"): string {
  return `events_export.${format}`;
}

/** Returns true when eventId's format-picker menu is open. */
export function deriveExportMenuOpen(eventId: number, menuId: number | null): boolean {
  return menuId === eventId;
}

// ---------------------------------------------------------------------------
// Preview open state — exported for tests
// ---------------------------------------------------------------------------

export function derivePreviewOpen(eventId: number, expandedIds: Set<number>): boolean {
  return expandedIds.has(eventId);
}

// ---------------------------------------------------------------------------
// Local pin state — exported for tests
// ---------------------------------------------------------------------------

export const PINS_LS_KEY = "so_archive_pins";

type MinStorage = Pick<Storage, "getItem" | "setItem">;

function _getStorage(): MinStorage | null {
  try {
    return typeof localStorage !== "undefined" ? localStorage : null;
  } catch {
    return null;
  }
}

export function loadPins(storage: MinStorage | null = _getStorage()): Set<number> {
  if (!storage) return new Set();
  try {
    const raw = storage.getItem(PINS_LS_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return new Set();
    return new Set(arr.filter((v): v is number => typeof v === "number" && Number.isInteger(v)));
  } catch {
    return new Set();
  }
}

export function savePins(pinnedIds: Set<number>, storage: MinStorage | null = _getStorage()): void {
  if (!storage) return;
  try {
    storage.setItem(PINS_LS_KEY, JSON.stringify([...pinnedIds]));
  } catch { /* storage unavailable */ }
}

export function isPinned(eventId: number, pinnedIds: Set<number>): boolean {
  return pinnedIds.has(eventId);
}

/** Stable sort: pinned rows first, then unpinned in their existing order. */
export function applyPinSort(events: SavedEvent[], pinnedIds: Set<number>): SavedEvent[] {
  if (pinnedIds.size === 0) return events;
  const pinned = events.filter((e) => pinnedIds.has(e.id));
  const rest = events.filter((e) => !pinnedIds.has(e.id));
  return [...pinned, ...rest];
}

// ---------------------------------------------------------------------------
// Inline preview panel — compact summary of already-loaded data
// ---------------------------------------------------------------------------

function EventPreview({ event }: { event: SavedEvent }) {
  const topTickers = [...event.market_tickers]
    .filter((t) => t.return_5d != null)
    .sort((a, b) => Math.abs(b.return_5d ?? 0) - Math.abs(a.return_5d ?? 0))
    .slice(0, 3);

  return (
    <div className="mt-1 rounded-[14px] border border-border/30 bg-surface-container-highest/50 px-3 py-2.5 text-[12px]">
      {event.mechanism_summary && (
        <p className="leading-relaxed text-muted-foreground line-clamp-3">
          {event.mechanism_summary}
        </p>
      )}
      {(event.beneficiaries.length > 0 || event.losers.length > 0) && (
        <div className="mt-2 flex flex-wrap gap-1">
          {event.beneficiaries.slice(0, 4).map((b) => (
            <span
              key={b}
              className="inline-flex items-center gap-0.5 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-700"
            >
              <TrendingUp className="h-2.5 w-2.5" />
              {b}
            </span>
          ))}
          {event.losers.slice(0, 4).map((l) => (
            <span
              key={l}
              className="inline-flex items-center gap-0.5 rounded-full border border-red-400/25 bg-red-400/10 px-2 py-0.5 text-[10px] text-red-600"
            >
              <TrendingDown className="h-2.5 w-2.5" />
              {l}
            </span>
          ))}
        </div>
      )}
      {topTickers.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {topTickers.map((t) => (
            <span
              key={t.symbol}
              className={cn(
                "font-num rounded border px-1.5 py-0.5 text-[10px]",
                (t.return_5d ?? 0) >= 0
                  ? "border-emerald-500/20 bg-emerald-500/8 text-emerald-700"
                  : "border-red-400/20 bg-red-400/8 text-red-600",
              )}
            >
              {t.symbol} {pct(t.return_5d)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Completeness badges — pure derivation, exported for tests
// ---------------------------------------------------------------------------

export interface CompletenessSignals {
  /** At least one ticker has return_5d data. */
  hasMarketData: boolean;
  /** Number of tickers with non-null return_5d. */
  tickerCount: number;
  /** User has assigned a rating. */
  hasRating: boolean;
  /** User has written research notes. */
  hasNotes: boolean;
  /** Event has a mechanism summary (not empty/mock). */
  hasMechanism: boolean;
}

export function deriveCompleteness(event: SavedEvent): CompletenessSignals {
  const withReturn = event.market_tickers.filter(
    (t) => t.return_5d != null,
  );
  return {
    hasMarketData: withReturn.length > 0,
    tickerCount: withReturn.length,
    hasRating: event.rating != null && event.rating !== "",
    hasNotes: event.notes != null && event.notes !== "",
    hasMechanism:
      event.mechanism_summary != null
      && event.mechanism_summary !== ""
      && !event.mechanism_summary.startsWith("[mock:"),
  };
}

// ---------------------------------------------------------------------------
// Event row — compact
// ---------------------------------------------------------------------------

function EventRow({
  event,
  onClick,
  deleteState,
  onDeleteRequest,
  onDeleteConfirm,
  onDeleteCancel,
  exportState,
  exportMenuOpen,
  onToggleExportMenu,
  onExportFormat,
  isExpanded,
  onTogglePreview,
  pinned,
  onTogglePin,
  selectionMode = false,
  selected = false,
  onToggleSelect,
}: {
  event: SavedEvent;
  onClick: () => void;
  deleteState: DeleteRowState;
  onDeleteRequest: () => void;
  onDeleteConfirm: () => void;
  onDeleteCancel: () => void;
  exportState: ExportRowState;
  exportMenuOpen: boolean;
  onToggleExportMenu: () => void;
  onExportFormat: (format: ExportFormat) => void;
  isExpanded: boolean;
  onTogglePreview: () => void;
  pinned: boolean;
  onTogglePin: () => void;
  selectionMode?: boolean;
  selected?: boolean;
  onToggleSelect?: () => void;
}) {
  const conf = CONFIDENCE_META[event.confidence] ?? { icon: ShieldAlert, color: "val-neg" };
  const ConfIcon = conf.icon;
  const rating = event.rating ? (RATING_META[event.rating] ?? null) : null;
  const RatingIcon = rating?.icon ?? Star;
  const signals = deriveCompleteness(event);
  const stale = getStaleDisplay(event.stale_signal);
  const qc = useQueryClient();
  const { mutate: doRefresh, isPending: refreshing } = useMutation({
    mutationFn: () => api.refreshMarket(event.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["events"] });
    },
  });

  return (
    <div className="group relative">
      <button
        onClick={selectionMode ? onToggleSelect : onClick}
        disabled={deleteState === "deleting"}
        className={cn(
          "w-full rounded-[18px] border bg-card px-3 py-3 pr-24 text-left shadow-[inset_0_0_0_1px_rgba(71,70,86,0.18),0_1px_3px_rgba(0,0,0,0.08)] transition-all hover:-translate-y-px hover:shadow-[inset_0_0_0_1px_rgba(71,70,86,0.3),0_4px_12px_rgba(0,0,0,0.14)] active:bg-secondary disabled:pointer-events-none disabled:opacity-50",
          selected
            ? "border-primary/40 bg-primary/5"
            : pinned
              ? "border-teal-400/40 hover:border-teal-400/60"
              : "border-border/60 hover:border-border",
        )}
      >
        <div className="flex items-start gap-2.5">
          {selectionMode ? (
            <div className="mt-0.5 hidden h-7 w-7 shrink-0 items-center justify-center sm:flex">
              {selected
                ? <CheckSquare className="h-4 w-4 text-primary" />
                : <Square className="h-4 w-4 text-on-surface-variant/30" />}
            </div>
          ) : (
          <div
            className={cn(
              "mt-0.5 hidden h-7 w-7 shrink-0 items-center justify-center rounded-xl border sm:flex",
              rating ? rating.bg : "bg-surface-container-highest border-border/50",
            )}
          >
            <RatingIcon className={cn("h-3 w-3", rating?.color ?? "text-muted-foreground")} />
          </div>
          )}

          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-medium leading-snug line-clamp-2">
              {event.headline}
            </p>
            <div className="mt-1 flex flex-wrap items-center gap-1">
              <Badge variant="outline">{event.stage}</Badge>
              <Badge variant="outline">{event.persistence}</Badge>
              <span className={cn("inline-flex items-center gap-0.5 text-2xs", conf.color)}>
                <ConfIcon className="h-2.5 w-2.5" />
                {event.confidence}
              </span>
              {signals.hasMarketData && (
                <span className="inline-flex items-center gap-0.5 rounded-full border border-emerald-500/20 bg-emerald-500/8 px-1.5 py-px text-[9px] font-medium text-emerald-700" title={`${signals.tickerCount} ticker${signals.tickerCount !== 1 ? "s" : ""} with data`}>
                  {signals.tickerCount}t
                </span>
              )}
              {signals.hasRating && (
                <span className="inline-flex items-center rounded-full border border-amber-500/20 bg-amber-500/8 px-1.5 py-px text-[9px] font-medium text-amber-700" title="Rated">
                  <Star className="h-2 w-2" />
                </span>
              )}
              {signals.hasNotes && (
                <span title="Has notes"><StickyNote className="h-2.5 w-2.5 text-muted-foreground" /></span>
              )}
              {!signals.hasMechanism && (
                <span className="inline-flex items-center rounded-full border border-red-400/20 bg-red-400/8 px-1.5 py-px text-[9px] font-medium text-red-500" title="Missing mechanism">
                  thin
                </span>
              )}
              {event.persistence_signal && (
                <LifecycleBadge sig={event.persistence_signal} />
              )}
              {rating && (
                <Badge variant="outline" className={cn("sm:hidden", rating.color)}>
                  {event.rating}
                </Badge>
              )}
            </div>
            <p className="mt-0.5 font-num text-2xs text-muted-foreground">
              {formatTimestamp(event.timestamp)}
            </p>
          </div>

          <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
        </div>
        {stale.showIndicator && (
          <div className="mt-1.5 flex items-center gap-1.5">
            <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", stale.dotClass)} />
            <span className="text-[10px] text-muted-foreground/60">{stale.label}</span>
          </div>
        )}
      </button>

      {/* Row actions — absolutely positioned to avoid nesting inside the row button */}
      <div className="absolute right-2.5 top-1/2 -translate-y-1/2 flex items-center gap-1">
        {/* Refresh market data */}
        {stale.showRefresh && (
          <button
            onClick={(e) => { e.stopPropagation(); doRefresh(); }}
            title="Refresh market data"
            disabled={refreshing}
            className={cn(
              "rounded p-1 transition-all text-muted-foreground/50 hover:text-amber-400",
              refreshing ? "opacity-100" : "opacity-0 group-hover:opacity-100",
            )}
          >
            <RefreshCw className={cn("h-3 w-3", refreshing && "animate-spin")} />
          </button>
        )}
        {/* Pin */}
        <button
          onClick={(e) => { e.stopPropagation(); onTogglePin(); }}
          title={pinned ? "Unpin" : "Pin to top"}
          className={cn(
            "rounded p-1 transition-all",
            pinned
              ? "text-teal-500 opacity-100 hover:text-teal-400"
              : "opacity-0 group-hover:opacity-100 text-muted-foreground/50 hover:text-teal-500",
          )}
        >
          <Pin className={cn("h-3 w-3", pinned && "fill-teal-500/30")} />
        </button>

        {/* Preview toggle */}
        <button
          onClick={(e) => { e.stopPropagation(); onTogglePreview(); }}
          title={isExpanded ? "Collapse preview" : "Quick preview"}
          className={cn(
            "rounded p-1 text-muted-foreground/50 hover:text-foreground transition-all",
            isExpanded ? "opacity-100 text-foreground/70" : "opacity-0 group-hover:opacity-100",
          )}
        >
          <ChevronDown className={cn("h-3 w-3 transition-transform duration-150", isExpanded && "rotate-180")} />
        </button>

        {/* Export */}
        {exportState === "idle" && (
          <button
            onClick={(e) => { e.stopPropagation(); onToggleExportMenu(); }}
            title={exportMenuOpen ? "Close export menu" : "Export"}
            className={cn(
              "rounded p-1 transition-all",
              exportMenuOpen
                ? "opacity-100 text-foreground/70"
                : "opacity-0 group-hover:opacity-100 text-muted-foreground/50 hover:text-foreground",
            )}
          >
            <FileDown className="h-3 w-3" />
          </button>
        )}
        {exportState === "exporting" && (
          <Loader2 className="h-3 w-3 animate-spin text-muted-foreground/50" />
        )}
        {exportState === "error" && (
          <button
            onClick={(e) => { e.stopPropagation(); onToggleExportMenu(); }}
            title="Export failed — retry"
            className="rounded p-1 text-destructive/60 hover:text-destructive transition-colors"
          >
            <FileDown className="h-3 w-3" />
          </button>
        )}

        {/* Delete */}
        {deleteState === "idle" && (
          <button
            onClick={(e) => { e.stopPropagation(); onDeleteRequest(); }}
            title="Delete event"
            className="opacity-0 group-hover:opacity-100 rounded p-1 text-muted-foreground/50 hover:text-destructive transition-all"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        )}
        {deleteState === "confirm" && (
          <div className="flex items-center gap-1 rounded-lg bg-background border border-destructive/30 px-1.5 py-0.5 shadow-sm">
            <button
              onClick={(e) => { e.stopPropagation(); onDeleteConfirm(); }}
              className="text-[10px] font-semibold text-destructive hover:text-destructive/80"
            >
              Delete?
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); onDeleteCancel(); }}
              className="text-[10px] text-muted-foreground hover:text-foreground leading-none"
            >
              ×
            </button>
          </div>
        )}
        {deleteState === "deleting" && (
          <Loader2 className="h-3 w-3 animate-spin text-muted-foreground/50" />
        )}
        {deleteState === "error" && (
          <span
            title="Delete failed — try again"
            className="flex items-center gap-1 rounded-lg bg-destructive/8 border border-destructive/20 px-1.5 py-0.5"
          >
            <Trash2 className="h-3 w-3 text-destructive/70" />
            <button
              onClick={(e) => { e.stopPropagation(); onDeleteRequest(); }}
              className="text-[10px] text-destructive/80 hover:text-destructive"
            >
              Retry
            </button>
          </span>
        )}
      </div>

      {isExpanded && <EventPreview event={event} />}

      {exportMenuOpen && exportState !== "exporting" && (
        <div className="mt-1 flex flex-wrap items-center gap-1.5 rounded-[12px] border border-border/40 bg-surface-container px-3 py-2 shadow-sm">
          <span className="text-[9px] uppercase tracking-widest text-muted-foreground/40 mr-0.5">
            Export as
          </span>
          {EXPORT_FORMATS.map((fmt) => (
            <button
              key={fmt}
              onClick={(e) => { e.stopPropagation(); onExportFormat(fmt); }}
              className="rounded border border-border/50 bg-secondary/40 px-2 py-0.5 text-[10px] font-medium text-foreground/70 hover:border-foreground/20 hover:bg-secondary hover:text-foreground transition-colors"
            >
              {_EXPORT_LABEL[fmt]}
            </button>
          ))}
          {exportState === "error" && (
            <span className="ml-1 text-[10px] text-destructive">Failed — pick a format to retry</span>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Market table — compact (same pattern as analysis view)
// ---------------------------------------------------------------------------

function MarketTable({ tickers }: { tickers: Ticker[] }) {
  if (tickers.length === 0) return null;

  return (
    <div className="overflow-x-auto rounded border">
      <table className="w-full text-2xs">
        <thead>
          <tr className="border-b bg-secondary/50 text-muted-foreground">
            <th className="whitespace-nowrap px-2.5 py-1.5 text-left font-medium">Symbol</th>
            <th className="whitespace-nowrap px-2.5 py-1.5 text-center font-medium">20d</th>
            <th className="hidden whitespace-nowrap px-2.5 py-1.5 text-left font-medium sm:table-cell">Role</th>
            <th className="whitespace-nowrap px-2.5 py-1.5 text-center font-medium">Dir</th>
            <th className="whitespace-nowrap px-2.5 py-1.5 text-right font-medium">1d</th>
            <th className="whitespace-nowrap px-2.5 py-1.5 text-right font-medium">5d</th>
            <th className="hidden whitespace-nowrap px-2.5 py-1.5 text-right font-medium md:table-cell">20d</th>
            <th className="hidden whitespace-nowrap px-2.5 py-1.5 text-right font-medium md:table-cell">Vol</th>
          </tr>
        </thead>
        <tbody>
          {tickers.map((t) => (
            <tr key={t.symbol} className="border-b last:border-0 hover:bg-secondary/30">
              <td className="whitespace-nowrap px-2.5 py-1.5 font-num font-semibold">{t.symbol}</td>
              <td className="px-2.5 py-1">
                <Sparkline
                  data={t.spark ?? []}
                  width={48}
                  height={16}
                  direction={t.return_20d}
                />
              </td>
              <td className="hidden whitespace-nowrap px-2.5 py-1.5 sm:table-cell">
                <Badge variant={t.role === "beneficiary" ? "secondary" : "outline"}>{t.role}</Badge>
              </td>
              <td className="px-2.5 py-1.5">
                <div className="flex items-center justify-center gap-1">
                  {directionIcon(t.direction_tag)}
                  <span>{t.label}</span>
                </div>
              </td>
              <td className={cn("whitespace-nowrap px-2.5 py-1.5 text-right font-num",
                (t.return_1d ?? 0) > 0 && "val-pos", (t.return_1d ?? 0) < 0 && "val-neg")}>{pct(t.return_1d)}</td>
              <td className={cn("whitespace-nowrap px-2.5 py-1.5 text-right font-num",
                (t.return_5d ?? 0) > 0 && "val-pos", (t.return_5d ?? 0) < 0 && "val-neg")}>{pct(t.return_5d)}</td>
              <td className={cn("hidden whitespace-nowrap px-2.5 py-1.5 text-right font-num md:table-cell",
                (t.return_20d ?? 0) > 0 && "val-pos", (t.return_20d ?? 0) < 0 && "val-neg")}>{pct(t.return_20d)}</td>
              <td className="hidden whitespace-nowrap px-2.5 py-1.5 text-right font-num md:table-cell">
                {t.volume_ratio != null ? `${t.volume_ratio.toFixed(1)}x` : "\u2014"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cascade graph view
// ---------------------------------------------------------------------------

function _cascadeDaysDelta(rootTs: string, nodeTs: string): string {
  try {
    const diff = Math.round(
      (new Date(nodeTs).getTime() - new Date(rootTs).getTime()) / 86_400_000,
    );
    if (diff === 0) return "same day";
    return diff > 0 ? `+${diff}d` : `${diff}d`;
  } catch {
    return "";
  }
}

function CascadeNodeCard({
  node,
  rootTs,
  dim = false,
}: {
  node: CascadeNode;
  rootTs: string;
  dim?: boolean;
}) {
  const ts = node.event_date || node.timestamp;
  const delta = ts ? _cascadeDaysDelta(rootTs, ts) : "";

  return (
    <div className={cn(
      "rounded-[6px] border px-3 py-2",
      dim
        ? "border-border/25 bg-background"
        : "border-[#93d1d3]/12 bg-[#13131a]",
    )}>
      <p className={cn(
        "text-[12px] font-medium leading-snug",
        dim && "text-foreground/65",
      )}>
        {node.headline}
      </p>
      <div className="mt-1 flex flex-wrap items-center gap-1">
        <Badge variant="outline" className={cn("text-[9px]", dim && "opacity-60")}>{node.stage}</Badge>
        {!dim && (
          <Badge variant="outline" className="text-[9px]">{node.persistence}</Badge>
        )}
        {delta && (
          <span className={cn(
            "font-num text-[10px] tabular-nums",
            dim ? "text-muted-foreground/40" : "text-[#93d1d3]/60",
          )}>
            {delta}
          </span>
        )}
      </div>
    </div>
  );
}

function CascadeView({ event }: { event: SavedEvent }) {
  const { data: cascadeData } = useQuery({
    queryKey: qk.cascade(event.id),
    queryFn: () => api.cascadeGraph(event.id),
  });

  const nodes = cascadeData?.nodes ?? [];
  if (nodes.length === 0) return null;

  const rootTs = event.event_date || event.timestamp;
  const hop1 = nodes.filter((n) => n.hop === 1);

  // Group hop-2 by parent
  const hop2Map = new Map<number, CascadeNode[]>();
  nodes.filter((n) => n.hop === 2).forEach((n) => {
    const list = hop2Map.get(n.parent_id) ?? [];
    list.push(n);
    hop2Map.set(n.parent_id, list);
  });

  const hasChildren = hop1.some((n) => (hop2Map.get(n.id)?.length ?? 0) > 0);

  return (
    <>
      <Separator />
      <div className="space-y-2">
        <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground/50 uppercase tracking-widest">
          <Network className="h-3 w-3" />
          <span>Event Cascade</span>
          <span className="text-muted-foreground/30">
            · {nodes.length} linked{hasChildren ? ", 2 levels" : ""}
          </span>
        </div>

        <div className="space-y-1.5">
          {hop1.map((node) => {
            const children = hop2Map.get(node.id) ?? [];
            return (
              <div key={node.id}>
                <CascadeNodeCard node={node} rootTs={rootTs} />
                {children.length > 0 && (
                  <div className="ml-4 mt-1 space-y-1 border-l border-border/25 pl-3">
                    {children.map((child) => (
                      <CascadeNodeCard key={child.id} node={child} rootTs={rootTs} dim />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Detail panel
// ---------------------------------------------------------------------------

function EventDetail({
  event,
  onBack,
  onRatingChange,
  onNotesChange,
}: {
  event: SavedEvent;
  onBack: () => void;
  onRatingChange: (event: SavedEvent) => void;
  onNotesChange: (event: SavedEvent) => void;
}) {
  // related events loaded via useQuery below
  const [editingNotes, setEditingNotes] = useState(false);
  const [noteDraft, setNoteDraft] = useState(event.notes ?? "");
  const [savingNotes, setSavingNotes] = useState(false);
  const [savingRating, setSavingRating] = useState<string | null>(null);
  const [memoExporting, setMemoExporting] = useState(false);
  const [memoError, setMemoError] = useState(false);

  const conf = CONFIDENCE_META[event.confidence] ?? { icon: ShieldAlert, color: "val-neg" };
  const ConfIcon = conf.icon;
  const rating = event.rating ? (RATING_META[event.rating] ?? null) : null;


  const setRating = async (r: string) => {
    const newRating = r === event.rating ? undefined : r;
    setSavingRating(r);
    try {
      await api.updateReview(event.id, { rating: newRating ?? "" });
      onRatingChange({ ...event, rating: newRating ?? null });
    } catch { /* ignore */ }
    setSavingRating(null);
  };

  const handleExportMemo = async () => {
    setMemoExporting(true);
    setMemoError(false);
    try {
      const blob = await api.downloadEventBlob(event.id, "markdown");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = deriveExportFilename(event.id, event.headline, "markdown");
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      setMemoError(true);
      setTimeout(() => setMemoError(false), 3000);
    }
    setMemoExporting(false);
  };

  const saveNotes = async () => {
    setSavingNotes(true);
    try {
      await api.updateReview(event.id, { notes: noteDraft });
      onNotesChange({ ...event, notes: noteDraft });
      setEditingNotes(false);
    } catch { /* ignore */ }
    setSavingNotes(false);
  };

  return (
    // Page-level scroll: detail view is plain flow.  The sticky back
    // button stays accessible while reading long event details — it
    // pins under the (also sticky) shell TopBar at top-14.
    <div className="page-enter flex flex-col">
      <div className="sticky top-14 z-20 -mx-3 -mt-3 mb-2 px-3 py-2 bg-background/85 backdrop-blur-sm md:-mx-5 md:-mt-4 md:px-5">
        <div className="flex items-center justify-between">
          <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2">
            <ArrowLeft className="h-3 w-3" />
            Back
          </Button>
          <button
            onClick={handleExportMemo}
            disabled={memoExporting}
            title={memoError ? "Export failed — try again" : "Export as markdown memo"}
            className={cn(
              "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-medium transition-colors disabled:pointer-events-none",
              memoError
                ? "border border-destructive/30 bg-destructive/8 text-destructive"
                : "bg-surface-container-highest text-on-surface-variant/60 hover:text-on-surface-variant",
            )}
          >
            {memoExporting
              ? <Loader2 className="h-3 w-3 animate-spin" />
              : <FileDown className="h-3 w-3" />}
            {memoError ? "Failed" : "Export memo"}
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1">
        <div className="fade-in space-y-3 pb-4 pr-2">
          {/* Header */}
          <Card className="overflow-hidden border-border/40 bg-surface-container-low shadow-[inset_0_0_0_1px_rgba(71,70,86,0.28),0_4px_12px_rgba(0,0,0,0.18)]">
            <CardHeader className="gap-3 border-b border-border/40 bg-surface-container-highest/70">
              <p className="section-kicker">Saved research</p>
              <CardTitle className="text-sm leading-snug">{event.headline}</CardTitle>
              <CardDescription className="flex flex-wrap items-center gap-1.5 pt-1">
                <Badge variant="outline">{event.stage}</Badge>
                <Badge variant="outline">{event.persistence}</Badge>
                <Badge variant="secondary" className={cn("gap-1", conf.color)}>
                  <ConfIcon className="h-3 w-3" />
                  {event.confidence}
                </Badge>
                {event.event_date && (
                  <span className="inline-flex items-center gap-1 font-num text-2xs text-muted-foreground">
                    <Calendar className="h-3 w-3" />
                    {event.event_date}
                  </span>
                )}
                <span className="inline-flex items-center gap-1 font-num text-2xs text-muted-foreground">
                  <Clock className="h-3 w-3" />
                  {formatTimestamp(event.timestamp)}
                </span>
              </CardDescription>
            </CardHeader>
          </Card>

          {/* Rating */}
          <Card className="overflow-hidden">
            <CardHeader className="border-b border-border/40 bg-surface-container-highest/60"><SectionLabel>Review Rating</SectionLabel></CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-1.5">
                {(["good", "mixed", "poor"] as const).map((r) => {
                  const meta = RATING_META[r]!;
                  const Icon = meta.icon;
                  const active = event.rating === r;
                  return (
                    <Button
                      key={r}
                      variant={active ? "secondary" : "outline"}
                      size="sm"
                      className={cn("capitalize", active && meta.bg)}
                      onClick={() => setRating(r)}
                      disabled={savingRating !== null}
                    >
                      {savingRating === r ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Icon className={cn("h-3 w-3", meta.color)} />
                      )}
                      {r}
                    </Button>
                  );
                })}
                {!rating && (
                  <span className="self-center text-2xs text-muted-foreground ml-1">
                    No review rating yet
                  </span>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Mechanism grid */}
          <div className="grid gap-3 lg:grid-cols-3">
            <div className="space-y-3 lg:col-span-2">
              {event.what_changed && (
                <Card className="overflow-hidden">
                  <CardHeader className="border-b border-border/40 bg-surface-container-highest/60"><SectionLabel>What Changed</SectionLabel></CardHeader>
                  <CardContent>
                    <p className="text-[13px] leading-relaxed">{event.what_changed}</p>
                  </CardContent>
                </Card>
              )}
              {event.mechanism_summary && (
                <Card className="overflow-hidden">
                  <CardHeader className="border-b border-border/40 bg-surface-container-highest/60"><SectionLabel>Mechanism Summary</SectionLabel></CardHeader>
                  <CardContent>
                    <p className="text-[13px] leading-relaxed whitespace-pre-line">{event.mechanism_summary}</p>
                  </CardContent>
                </Card>
              )}
            </div>

            <div className="space-y-3">
              <Card className="overflow-hidden">
                <CardHeader className="border-b border-border/40 bg-surface-container-highest/60"><SectionLabel>Beneficiaries</SectionLabel></CardHeader>
                <CardContent>
                  {event.beneficiaries.length > 0 ? (
                    <ul className="space-y-0.5">
                      {event.beneficiaries.map((b) => (
                        <li key={b} className="flex items-center gap-1.5 text-[13px]">
                          <TrendingUp className="h-3 w-3 shrink-0 val-pos" />{b}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-2xs text-muted-foreground">No clear beneficiaries identified.</p>
                  )}
                </CardContent>
              </Card>
              <Card className="overflow-hidden">
                <CardHeader className="border-b border-border/40 bg-surface-container-highest/60"><SectionLabel>Losers</SectionLabel></CardHeader>
                <CardContent>
                  {event.losers.length > 0 ? (
                    <ul className="space-y-0.5">
                      {event.losers.map((l) => (
                        <li key={l} className="flex items-center gap-1.5 text-[13px]">
                          <TrendingDown className="h-3 w-3 shrink-0 val-neg" />{l}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-2xs text-muted-foreground">No clear losers identified.</p>
                  )}
                </CardContent>
              </Card>
              {event.assets_to_watch.length > 0 && (
                <Card className="overflow-hidden">
                  <CardHeader className="border-b border-border/40 bg-surface-container-highest/60"><SectionLabel>Assets to Watch</SectionLabel></CardHeader>
                  <CardContent>
                    <div className="flex flex-wrap gap-1">
                      {event.assets_to_watch.map((a) => (
                        <Badge key={a} variant="outline" className="font-num">{a}</Badge>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          </div>

          {/* Market */}
          {event.market_tickers.length > 0 && (
            <>
              <Separator />
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <SectionLabel>Market Check</SectionLabel>
                  <span className="font-num text-2xs text-muted-foreground">
                    {event.market_tickers.length} ticker{event.market_tickers.length !== 1 && "s"}
                  </span>
                </div>
                {event.market_note && (
                  <p className="text-2xs text-muted-foreground">{event.market_note}</p>
                )}
                <MarketTable tickers={event.market_tickers} />
              </div>
            </>
          )}

          {/* Notes */}
          <Separator />
          <Card className="overflow-hidden">
            <CardHeader>
              <div className="flex items-center justify-between">
                <SectionLabel>Research Notes</SectionLabel>
                {!editingNotes && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-5 text-2xs"
                    onClick={() => { setNoteDraft(event.notes ?? ""); setEditingNotes(true); }}
                  >
                    {event.notes ? "Edit notes" : "Add notes"}
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent>
              {editingNotes ? (
                <div className="space-y-2">
                  <textarea
                    value={noteDraft}
                    onChange={(e) => setNoteDraft(e.target.value)}
                    rows={3}
                    className="w-full rounded border bg-background px-2.5 py-1.5 text-[13px] placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring resize-y"
                    placeholder="Add research notes, follow-ups, or observations..."
                    autoFocus
                  />
                  <div className="flex gap-1.5">
                    <Button size="sm" onClick={saveNotes} disabled={savingNotes}>
                      {savingNotes ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                      Save
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setEditingNotes(false)}>Cancel</Button>
                  </div>
                </div>
              ) : event.notes ? (
                <p className="text-[13px] leading-relaxed whitespace-pre-line">{event.notes}</p>
              ) : (
                <p className="text-2xs text-muted-foreground">No research notes yet.</p>
              )}
            </CardContent>
          </Card>

          {/* Cascade view */}
          <CascadeView event={event} />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

export function RecentEvents() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [validationFilter, setValidationFilter] = useState<"validated" | "contradicted" | "unresolved" | null>(null);
  const [validationV2Filter, setValidationV2Filter] = useState<ValidationStatusV2 | null>(null);
  const [qualityFilter, setQualityFilter] = useState<ArchiveQuality | null>(null);
  const [includeMock, setIncludeMock] = useState(false);
  const [offset, setOffset] = useState(0);
  const [stageFilter, setStageFilter] = useState<string | null>(null);
  const [confFilter, setConfFilter] = useState<string | null>(null);
  const [persistenceFilter, setPersistenceFilter] = useState<string | null>(null);
  const [ratingFilter, setRatingFilter] = useState<string | null>(null);
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const [sortKey, setSortKey] = useState<SortKey>("newest");
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);
  const [exportingId, setExportingId] = useState<number | null>(null);
  const [exportErrorId, setExportErrorId] = useState<number | null>(null);
  const [exportMenuId, setExportMenuId] = useState<number | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [pinnedIds, setPinnedIds] = useState<Set<number>>(() => loadPins());
  const [bulkMenuOpen, setBulkMenuOpen] = useState(false);
  const [bulkExporting, setBulkExporting] = useState<"csv" | "json" | null>(null);
  const [bulkExportError, setBulkExportError] = useState(false);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [selectionExporting, setSelectionExporting] = useState<"portfolio" | "zip" | null>(null);
  const [selectionExportError, setSelectionExportError] = useState(false);

  // Debounce the search input so the query doesn't fire on every keystroke.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Reset to page 0 whenever any filter changes.
  useEffect(() => {
    setOffset(0);
  }, [debouncedSearch, stageFilter, confFilter, persistenceFilter, ratingFilter, dateFrom, dateTo, validationFilter, validationV2Filter, qualityFilter, includeMock]);

  const PAGE_SIZE = 25;

  const query: EventsQuery = {
    limit:       PAGE_SIZE,
    offset,
    search:      debouncedSearch || undefined,
    stage:       stageFilter     ?? undefined,
    persistence: persistenceFilter ?? undefined,
    confidence:  confFilter      ?? undefined,
    rating:      ratingFilter    ?? undefined,
    date_from:   dateFrom        || undefined,
    date_to:     dateTo          || undefined,
    validated:   validationFilter ?? undefined,
    validation_status_v2: validationV2Filter ?? undefined,
    quality:     qualityFilter   ?? undefined,
    include_mock: includeMock || undefined,
  };

  const hasActiveFilters = Boolean(
    search
    || stageFilter
    || confFilter
    || persistenceFilter
    || ratingFilter
    || dateFrom
    || dateTo
    || validationFilter
    || validationV2Filter
    || qualityFilter
    || includeMock,
  );

  const { data, isLoading: loading, error: queryError, refetch } = useQuery({
    queryKey: qk.events(query),
    queryFn:  () => api.events(query),
    retry: (failureCount, err) =>
      !(err instanceof ApiError && err.status >= 500) && failureCount < 1,
  });
  const error = queryError instanceof Error ? queryError.message : queryError ? String(queryError) : null;

  const events = data?.items ?? [];
  const total  = data?.total ?? 0;

  // Sort and pin are client-side refinements on the server-returned page.
  const displayed = useMemo(
    () => applyPinSort(sortEvents(events, sortKey), pinnedIds),
    [events, sortKey, pinnedIds],
  );

  const pinnedCount = useMemo(
    () => displayed.filter((e) => pinnedIds.has(e.id)).length,
    [displayed, pinnedIds],
  );

  const selectedEvent = events.find((e) => e.id === selectedId) ?? null;

  const updateEvent = useCallback((updated: SavedEvent) => {
    queryClient.setQueriesData<EventsPage>(
      { queryKey: ["events"] },
      (old) => old ? { ...old, items: old.items.map((e) => (e.id === updated.id ? updated : e)) } : old,
    );
  }, [queryClient]);

  const handleDeleteRequest = useCallback((id: number) => {
    setPendingDelete((prev) =>
      // Second click on same row cancels; first click arms confirm.
      prev?.id === id && prev.phase === "confirm" ? null : { id, phase: "confirm" },
    );
  }, []);

  const handleDeleteConfirm = useCallback(async (id: number) => {
    setPendingDelete({ id, phase: "deleting" });
    try {
      await api.deleteEvent(id);
      queryClient.setQueriesData<EventsPage>(
        { queryKey: ["events"] },
        (old) => old
          ? { ...old, items: old.items.filter((e) => e.id !== id), total: old.total - 1 }
          : old,
      );
      setPendingDelete(null);
    } catch {
      setPendingDelete({ id, phase: "error" });
    }
  }, [queryClient]);

  const handleDeleteCancel = useCallback(() => {
    setPendingDelete(null);
  }, []);

  const handleTogglePreview = useCallback((id: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const handleTogglePin = useCallback((id: number) => {
    setPinnedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      savePins(next);
      return next;
    });
  }, []);

  const handleExportFormat = useCallback(async (ev: SavedEvent, format: ExportFormat) => {
    setExportMenuId(null);
    setExportingId(ev.id);
    setExportErrorId(null);
    try {
      const blob = await api.downloadEventBlob(ev.id, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = deriveExportFilename(ev.id, ev.headline, format);
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setExportingId(null);
    } catch {
      setExportingId(null);
      setExportErrorId(ev.id);
      setExportMenuId(ev.id); // re-open menu so user can retry
    }
  }, []);

  const handleBulkExport = useCallback(async (format: "csv" | "json") => {
    setBulkMenuOpen(false);
    setBulkExporting(format);
    setBulkExportError(false);
    try {
      const blob = await api.downloadBulkExport(format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = deriveBulkExportFilename(format);
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setBulkExporting(null);
    } catch {
      setBulkExporting(null);
      setBulkExportError(true);
    }
  }, []);

  const toggleSelect = useCallback((id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(displayed.map((e) => e.id)));
  }, [displayed]);

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set());
    setSelectionMode(false);
  }, []);

  const handleSelectionExport = useCallback(async (format: "portfolio" | "zip") => {
    if (selectedIds.size === 0) return;
    setSelectionExporting(format);
    setSelectionExportError(false);
    const ids = [...selectedIds];
    try {
      let blob: Blob;
      let filename: string;
      if (format === "portfolio") {
        blob = await api.downloadPortfolio(ids);
        filename = "research_portfolio.md";
      } else {
        blob = await api.downloadSelectionZip(ids);
        filename = "research_packet.zip";
      }
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      setSelectionExportError(true);
      setTimeout(() => setSelectionExportError(false), 3000);
    }
    setSelectionExporting(null);
  }, [selectedIds]);

  if (selectedEvent) {
    return (
      <EventDetail
        event={selectedEvent}
        onBack={() => setSelectedId(null)}
        onRatingChange={updateEvent}
        onNotesChange={updateEvent}
      />
    );
  }

  return (
    // Page-level scroll: list view is plain flow.
    <div className="flex flex-col gap-3">
      <div className="flex shrink-0 flex-col gap-3 px-1 pb-1 pt-1 md:flex-row md:items-end md:justify-between">
        <div className="flex min-w-0 items-end gap-3">
          <div className="min-w-0">
            <h2 className="font-headline truncate text-[22px] font-bold leading-tight tracking-[-0.015em] text-on-surface">
              Archive
            </h2>
            <p className="mt-1 text-[12.5px] text-on-surface-variant/75">
              {loading ? "Loading archive…"
                : error ? "Could not load archive."
                : <><span className="font-mono tabular-nums text-on-surface">{total}</span> saved event{total !== 1 ? "s" : ""}{total > 0 ? " with notes, ratings, and linked follow-ups." : "."}</>}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {/* Bulk export */}
          {total > 0 && (
            <div className="relative">
              {bulkExporting ? (
                <Button variant="outline" size="sm" disabled className="shrink-0">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  <span className="hidden sm:inline">{bulkExporting.toUpperCase()}…</span>
                </Button>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => { setBulkMenuOpen((v) => !v); setBulkExportError(false); }}
                  className="shrink-0"
                >
                  <FileDown className="h-3 w-3" />
                  <span className="hidden sm:inline">Export all</span>
                </Button>
              )}
              {bulkMenuOpen && (
                <div className="absolute right-0 top-full z-20 mt-1 flex items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 py-1.5 shadow-md">
                  <span className="text-[9px] uppercase tracking-widest text-muted-foreground/40 mr-0.5">as</span>
                  {(["csv", "json"] as const).map((fmt) => (
                    <button
                      key={fmt}
                      onClick={() => handleBulkExport(fmt)}
                      className="rounded border border-border/50 bg-secondary/40 px-2 py-0.5 text-[10px] font-medium hover:bg-secondary hover:border-foreground/20 transition-colors"
                    >
                      {fmt}
                    </button>
                  ))}
                </div>
              )}
              {bulkExportError && !bulkMenuOpen && (
                <p className="mt-1 text-[10px] text-destructive text-right">Export failed</p>
              )}
            </div>
          )}
          {total > 0 && (
            <Button
              variant={selectionMode ? "secondary" : "outline"}
              size="sm"
              onClick={() => { setSelectionMode((v) => !v); setSelectedIds(new Set()); }}
              className="shrink-0"
            >
              <CheckSquare className="h-3 w-3" />
              <span className="hidden sm:inline">{selectionMode ? "Cancel" : "Select"}</span>
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => refetch()} disabled={loading} className="shrink-0">
            <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
            <span className="hidden sm:inline">Refresh archive</span>
          </Button>
        </div>
      </div>

      {error && (
        <Card className="shrink-0 border-destructive/30 bg-destructive/5">
          <CardContent className="flex items-center justify-between py-3">
            <span className="text-2xs leading-5 text-destructive">{error}</span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => refetch()}
              disabled={loading}
              className="ml-3 shrink-0 text-destructive/70 hover:text-destructive"
            >
              <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
              Try again
            </Button>
          </CardContent>
        </Card>
      )}

      {loading && events.length === 0 && (
        <div className="min-h-0 flex-1 space-y-0.5">
          {Array.from({ length: 6 }).map((_, i) => <EventRowSkeleton key={i} />)}
        </div>
      )}

      {/* Search + filters */}
      {!loading && !error && (
        <div className="flex flex-col gap-2.5 rounded-lg bg-card px-3.5 py-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-on-surface-variant/55" />
            <input
              type="text"
              placeholder="Search headlines…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full rounded-md bg-white/[0.025] pl-9 pr-3 py-2 text-[13px] text-on-surface placeholder:text-on-surface-variant/55 focus:outline-none focus:ring-1 focus:ring-primary/40"
            />
          </div>
          {/* Filter pills: Stage, Persistence, Confidence, Rating */}
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[10px] font-medium uppercase tracking-[0.12em] text-on-surface-variant/55 mr-1">Stage</span>
            {["developing", "realized", "anticipated"].map((s) => (
              <button
                key={s}
                onClick={() => setStageFilter(stageFilter === s ? null : s)}
                className={cn(
                  "rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
                  stageFilter === s
                    ? "bg-primary/[0.12] text-primary"
                    : "bg-white/[0.03] text-on-surface-variant hover:bg-white/[0.06] hover:text-on-surface",
                )}
              >
                {s}
              </button>
            ))}
            <span className="ml-2 text-[10px] font-medium uppercase tracking-[0.12em] text-on-surface-variant/55">Persist</span>
            {["low", "medium", "high"].map((p) => (
              <button
                key={p}
                onClick={() => setPersistenceFilter(persistenceFilter === p ? null : p)}
                className={cn(
                  "rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
                  persistenceFilter === p
                    ? "bg-primary/[0.12] text-primary"
                    : "bg-white/[0.03] text-on-surface-variant hover:bg-white/[0.06] hover:text-on-surface",
                )}
              >
                {p}
              </button>
            ))}
            <span className="ml-2 text-[10px] font-medium uppercase tracking-[0.12em] text-on-surface-variant/55">Conf</span>
            {["high", "medium", "low"].map((c) => (
              <button
                key={c}
                onClick={() => setConfFilter(confFilter === c ? null : c)}
                className={cn(
                  "rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
                  confFilter === c
                    ? "bg-primary/[0.12] text-primary"
                    : "bg-white/[0.03] text-on-surface-variant hover:bg-white/[0.06] hover:text-on-surface",
                )}
              >
                {c}
              </button>
            ))}
            <span className="ml-2 text-[10px] font-medium uppercase tracking-[0.12em] text-on-surface-variant/55">Rating</span>
            {["good", "mixed", "poor"].map((r) => (
              <button
                key={r}
                onClick={() => setRatingFilter(ratingFilter === r ? null : r)}
                className={cn(
                  "rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
                  ratingFilter === r
                    ? "bg-primary/[0.12] text-primary"
                    : "bg-white/[0.03] text-on-surface-variant hover:bg-white/[0.06] hover:text-on-surface",
                )}
              >
                {r}
              </button>
            ))}
            <span className="ml-2 text-[10px] font-medium uppercase tracking-[0.12em] text-on-surface-variant/55">Validated</span>
            {(["validated", "contradicted", "unresolved"] as const).map((v) => (
              <button
                key={v}
                onClick={() => setValidationFilter(validationFilter === v ? null : v)}
                className={cn(
                  "rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
                  validationFilter === v
                    ? "bg-primary/[0.12] text-primary"
                    : "bg-white/[0.03] text-on-surface-variant hover:bg-white/[0.06] hover:text-on-surface",
                )}
              >
                {v}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[10px] font-medium uppercase tracking-[0.12em] text-on-surface-variant/55 mr-1">Quality</span>
            {QUALITY_FILTERS.map(({ value, label }) => (
              <button
                key={value ?? "default"}
                onClick={() => setQualityFilter(value)}
                className={cn(
                  "rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
                  qualityFilter === value
                    ? "bg-primary/[0.12] text-primary"
                    : "bg-white/[0.03] text-on-surface-variant hover:bg-white/[0.06] hover:text-on-surface",
                )}
                title={value === null ? "Current archive default: excludes mock, demo, and degraded rows." : undefined}
              >
                {label}
              </button>
            ))}
            <button
              onClick={() => setIncludeMock((v) => !v)}
              className={cn(
                "ml-1 rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
                includeMock
                  ? "bg-amber-500/[0.12] text-amber-500"
                  : "bg-white/[0.03] text-on-surface-variant hover:bg-white/[0.06] hover:text-on-surface",
              )}
              title="Separate opt-in for mock and demo rows."
            >
              Include mock/demo
            </button>
            <span className="ml-2 text-[10px] font-medium uppercase tracking-[0.12em] text-on-surface-variant/55">Evidence</span>
            {VALIDATION_V2_FILTERS.map(({ value, label }) => (
              <button
                key={value}
                onClick={() => setValidationV2Filter(validationV2Filter === value ? null : value)}
                className={cn(
                  "rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
                  validationV2Filter === value
                    ? "bg-primary/[0.12] text-primary"
                    : "bg-white/[0.03] text-on-surface-variant hover:bg-white/[0.06] hover:text-on-surface",
                )}
                title="Filters the live validation_status_v2 read on archive rows."
              >
                {label}
              </button>
            ))}
          </div>
          {/* Sort + date range + active count */}
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[10px] font-medium uppercase tracking-[0.12em] text-on-surface-variant/55 mr-1">Sort</span>
            {(["newest", "oldest", "impact", "confidence"] as SortKey[]).map((k) => (
              <button
                key={k}
                onClick={() => setSortKey(k)}
                className={cn(
                  "rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
                  sortKey === k
                    ? "bg-primary/[0.12] text-primary"
                    : "bg-white/[0.03] text-on-surface-variant hover:bg-white/[0.06] hover:text-on-surface",
                )}
              >
                {k}
              </button>
            ))}
            <span className="ml-2 text-[10px] font-medium uppercase tracking-[0.12em] text-on-surface-variant/55">From</span>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="rounded-md bg-white/[0.03] px-2 py-1 text-[11px] text-on-surface focus:outline-none focus:ring-1 focus:ring-primary/40"
            />
            <span className="text-[10px] font-medium uppercase tracking-[0.12em] text-on-surface-variant/55">To</span>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="rounded-md bg-white/[0.03] px-2 py-1 text-[11px] text-on-surface focus:outline-none focus:ring-1 focus:ring-primary/40"
            />
            {hasActiveFilters && (
              <span className="ml-auto font-mono text-[10.5px] tabular-nums text-on-surface-variant/55">
                {total} result{total !== 1 ? "s" : ""}
              </span>
            )}
          </div>
        </div>
      )}

      {!loading && !error && total === 0 && !hasActiveFilters && (
        <Card className="empty-surface flex flex-1 items-center justify-center bg-transparent">
          <CardContent className="flex max-w-md flex-col items-center gap-3 py-12 text-center text-muted-foreground">
            <div className="flex h-14 w-14 items-center justify-center rounded-full border border-border/50 bg-surface-container-highest">
              <Archive className="h-6 w-6 opacity-70" />
            </div>
            <div className="space-y-1.5">
              <p className="text-sm font-medium text-foreground">No saved events yet</p>
              <p className="text-[12px] leading-5">Run an analysis and save the result to start building the archive.</p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Selection action bar */}
      {selectionMode && (
        <div className={cn(
          "flex items-center gap-2 rounded-[16px] border px-3 py-2 transition-colors",
          selectedIds.size > 0
            ? "border-primary/25 bg-primary/5"
            : "border-border/30 bg-surface-container-low",
        )}>
          <button
            onClick={selectAll}
            className="flex items-center gap-1 text-[10px] text-on-surface-variant/70 hover:text-foreground transition-colors"
          >
            <CheckSquare className="h-3 w-3" />
            All
          </button>
          <div className="h-3 w-px bg-border/40" />
          {selectedIds.size > 0 ? (
            <>
              <span className="font-num text-[11px] font-semibold text-primary">{selectedIds.size}</span>
              <span className="text-[11px] text-on-surface-variant">selected</span>
              <div className="ml-auto flex items-center gap-1.5">
                {selectionExportError && (
                  <span className="text-[10px] text-destructive mr-1">Export failed</span>
                )}
                <button
                  onClick={() => handleSelectionExport("portfolio")}
                  disabled={selectionExporting !== null}
                  className="flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/8 px-2.5 py-1 text-[10px] font-medium text-primary transition-colors hover:bg-primary/15 disabled:opacity-50"
                >
                  {selectionExporting === "portfolio"
                    ? <Loader2 className="h-3 w-3 animate-spin" />
                    : <PackageOpen className="h-3 w-3" />}
                  Portfolio .md
                </button>
                <button
                  onClick={() => handleSelectionExport("zip")}
                  disabled={selectionExporting !== null}
                  className="flex items-center gap-1.5 rounded-full border border-border/60 bg-surface-container-highest px-2.5 py-1 text-[10px] font-medium text-on-surface-variant/70 transition-colors hover:text-foreground disabled:opacity-50"
                >
                  {selectionExporting === "zip"
                    ? <Loader2 className="h-3 w-3 animate-spin" />
                    : <FileDown className="h-3 w-3" />}
                  .zip
                </button>
                <button
                  onClick={clearSelection}
                  className="ml-1 text-[10px] text-on-surface-variant/50 hover:text-foreground transition-colors"
                >
                  Clear
                </button>
              </div>
            </>
          ) : (
            <span className="text-[11px] text-on-surface-variant/50">Click rows to select</span>
          )}
        </div>
      )}

      {displayed.length > 0 && (
        <div className="fade-in space-y-2 pr-2">
          {displayed.map((ev, idx) => (
            <div key={ev.id}>
              {idx === pinnedCount && pinnedCount > 0 && pinnedCount < displayed.length && (
                <div className="flex items-center gap-2 py-1">
                  <div className="h-px flex-1 bg-border/40" />
                  <span className="text-[9px] uppercase tracking-widest text-muted-foreground/40">archive</span>
                  <div className="h-px flex-1 bg-border/40" />
                </div>
              )}
              <EventRow
                event={ev}
                onClick={() => setSelectedId(ev.id)}
                deleteState={deriveDeleteState(ev.id, pendingDelete)}
                onDeleteRequest={() => handleDeleteRequest(ev.id)}
                onDeleteConfirm={() => handleDeleteConfirm(ev.id)}
                onDeleteCancel={handleDeleteCancel}
                exportState={deriveExportState(ev.id, exportingId, exportErrorId)}
                exportMenuOpen={deriveExportMenuOpen(ev.id, exportMenuId)}
                onToggleExportMenu={() => setExportMenuId((prev) => prev === ev.id ? null : ev.id)}
                onExportFormat={(fmt) => handleExportFormat(ev, fmt)}
                isExpanded={derivePreviewOpen(ev.id, expandedIds)}
                onTogglePreview={() => handleTogglePreview(ev.id)}
                pinned={isPinned(ev.id, pinnedIds)}
                onTogglePin={() => handleTogglePin(ev.id)}
                selectionMode={selectionMode}
                selected={selectedIds.has(ev.id)}
                onToggleSelect={() => toggleSelect(ev.id)}
              />
            </div>
          ))}
        </div>
      )}

      {total === 0 && hasActiveFilters && (
        <p className="py-8 text-center text-[12px] text-muted-foreground/50">
          No events match the current filters.
        </p>
      )}

      {total > 0 && displayed.length === 0 && (
        <p className="py-8 text-center text-[12px] text-muted-foreground/50">
          No events match the current filters.
        </p>
      )}

      {/* Pagination — only shown when there are more results than one page */}
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between px-1 py-2 text-[11px] text-muted-foreground">
          <button
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            className="disabled:opacity-30 hover:text-foreground transition-colors"
          >
            ← Prev
          </button>
          <span className="font-num tabular-nums">
            {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
          </span>
          <button
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
            className="disabled:opacity-30 hover:text-foreground transition-colors"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
