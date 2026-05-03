/**
 * Three distinct visual treatments for the Market Overview movers chapter.
 * Maps to the Second Order design package:
 *   - TodayMoverCard       (tm-card): 4-up grid, big move number, urgent
 *   - WeeklyMoverCard      (wm-card): 2-up grid, sparkline, editorial
 *   - PersistentMoverRow   (pm-row):  horizontal row, days-active anchor,
 *                                     5d / 20d / weighted columns + spark
 *
 * All three consume the existing MarketMover wire shape — no new backend
 * fields are required.  Optional enrichment blocks (thesis_state,
 * weighted_evidence, evidence) are used when present and fall back to the
 * always-populated ``support_ratio`` / ticker arrays otherwise.
 */

import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { pct } from "@/lib/ticker-utils";
import type {
  MarketMover,
  MoverThesisState,
  MoverTicker,
  MoverWeightedEvidence,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Shared helpers + small primitives
// ---------------------------------------------------------------------------

type Direction = "up" | "dn" | "flat";

function _dir(value: number | null | undefined): Direction {
  if (value == null) return "flat";
  if (value > 0) return "up";
  if (value < 0) return "dn";
  return "flat";
}

const _MOVE_TONE: Record<Direction, string> = {
  up: "text-primary",
  dn: "text-error-dim",
  flat: "text-on-surface-variant",
};

/** Pick the lead ticker for the headline number — first entry wins. */
function _leadTicker(tickers: MoverTicker[]): MoverTicker | null {
  return tickers.length > 0 ? tickers[0]! : null;
}

/** Truncate a mechanism summary for compact card chrome. */
function _truncate(text: string | null | undefined, max: number): string {
  const t = (text ?? "").trim();
  if (!t) return "";
  return t.length > max ? t.slice(0, max - 1).trimEnd() + "…" : t;
}

/** Derive the design-package thesis_state label from the wire field, with a
 *  support_ratio fallback so legacy mover rows still get a sensible pill. */
function deriveThesisState(m: MarketMover): MoverThesisState {
  if (m.thesis_state) return m.thesis_state;
  const sr = m.support_ratio ?? 0;
  if (sr >= 0.7) return "confirming";
  if (sr >= 0.4) return "partial";
  if (sr <= 0.2) return "weakening";
  return "watching";
}

const _THESIS_LABEL: Record<MoverThesisState, string> = {
  confirming: "Confirming",
  partial: "Partial",
  watching: "Watching",
  weakening: "Weakening",
  falsified: "Falsified",
  stale: "Stale",
  low_information: "Low info",
  unknown: "—",
};

const _THESIS_TONE: Record<MoverThesisState, string> = {
  confirming: "bg-primary/15 text-primary",
  partial: "bg-primary/8 text-primary/80",
  watching: "bg-surface-container-highest text-on-surface-variant/80",
  weakening: "bg-error-dim/12 text-error-dim/85",
  falsified: "bg-error-dim/18 text-error-dim",
  stale: "bg-surface-container-highest text-on-surface-variant/55",
  low_information: "bg-surface-container-highest text-on-surface-variant/55",
  unknown: "bg-surface-container-highest text-on-surface-variant/55",
};

function ThesisPill({ state }: { state: MoverThesisState }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-bold uppercase tracking-[0.12em]",
        _THESIS_TONE[state],
      )}
    >
      <span
        className={cn(
          "h-1 w-1 rounded-full",
          state === "confirming" || state === "partial" ? "bg-primary" :
          state === "weakening" || state === "falsified" ? "bg-error-dim" :
          "bg-on-surface-variant/40",
        )}
      />
      {_THESIS_LABEL[state]}
    </span>
  );
}

type EvidenceLabel = NonNullable<MoverWeightedEvidence["evidence_label"]>;

/** Extract the weighted-evidence label, defaulting to insufficient. */
function deriveEvidenceLabel(m: MarketMover): EvidenceLabel {
  return m.weighted_evidence?.evidence_label ?? "insufficient";
}

const _EVIDENCE_DOT: Record<EvidenceLabel, string> = {
  supportive: "bg-primary shadow-[0_0_4px_rgba(147,209,211,0.6)]",
  contradictory: "bg-error-dim",
  mixed: "bg-gradient-to-r from-primary to-error-dim",
  insufficient: "bg-on-surface-variant/35",
};

function EvidenceDot({ label }: { label: EvidenceLabel }) {
  return (
    <span
      title={label}
      className={cn("inline-block h-1.5 w-1.5 rounded-full shrink-0", _EVIDENCE_DOT[label])}
    />
  );
}

const _EVIDENCE_LBL_TONE: Record<EvidenceLabel, string> = {
  supportive: "text-primary",
  contradictory: "text-error-dim",
  mixed: "text-on-surface-variant",
  insufficient: "text-on-surface-variant/60",
};

function EvidenceLabel({ label }: { label: EvidenceLabel }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-[11px] font-bold uppercase tracking-[0.12em]",
        _EVIDENCE_LBL_TONE[label],
      )}
    >
      <EvidenceDot label={label} />
      {label}
    </span>
  );
}

function todayEvidenceRead(mover: MarketMover, label: EvidenceLabel): string {
  if (
    label === "insufficient"
    || mover.conviction?.conviction_class === "pending"
    || mover.evidence?.tier === "insufficient"
  ) {
    return "Pending / thin evidence";
  }
  if (label === "supportive") return "Supportive evidence";
  if (label === "contradictory") return "Contradictory evidence";
  return "Mixed evidence";
}

function TodayEvidenceRead({
  mover,
  label,
}: {
  mover: MarketMover;
  label: EvidenceLabel;
}) {
  return (
    <span
      className={cn(
        "inline-flex min-w-0 items-center gap-1 text-[11px] font-medium",
        _EVIDENCE_LBL_TONE[label],
      )}
    >
      <EvidenceDot label={label} />
      <span className="truncate">{todayEvidenceRead(mover, label)}</span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// MoverWindowBadge — visually distinguishes the three windows
// ---------------------------------------------------------------------------

type Window = "today" | "weekly" | "persistent";

const _WINDOW_LABEL: Record<Window, string> = {
  today: "Today",
  weekly: "Week",
  persistent: "Persist",
};

export function MoverWindowBadge({ w }: { w: Window }) {
  if (w === "today") {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-primary/14 text-primary text-[11px] font-bold uppercase tracking-[0.18em]">
        <span className="h-1.5 w-1.5 rounded-full bg-primary shadow-[0_0_6px_rgba(147,209,211,0.6)]" />
        {_WINDOW_LABEL[w]}
      </span>
    );
  }
  if (w === "weekly") {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-surface-container-highest text-on-surface-variant text-[11px] font-bold uppercase tracking-[0.18em]">
        {_WINDOW_LABEL[w]}
      </span>
    );
  }
  // persistent
  return (
    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 text-on-surface-variant/80 text-[11px] font-bold uppercase tracking-[0.18em]">
      <span className="h-1 w-1 rotate-45 bg-primary" />
      {_WINDOW_LABEL[w]}
    </span>
  );
}

// ---------------------------------------------------------------------------
// MoversChapterHead / MoversSectionHead — section chrome
// ---------------------------------------------------------------------------

export function MoversChapterHead() {
  return (
    <div className="mt-12 mb-6 pb-4 border-b border-outline-variant/10">
      <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-primary/70 mb-1">
        C · Movers
      </p>
      <h2 className="text-[22px] font-headline font-extrabold tracking-tight text-on-surface leading-tight">
        What's driving price right now
      </h2>
      <p className="text-[12px] text-on-surface-variant/70 mt-1 max-w-3xl leading-relaxed">
        Event-linked moves, separated by horizon. Each mover is a study — open one to see its full thesis.
      </p>
    </div>
  );
}

export function MoversSectionHead({
  window: w,
  title,
  sub,
  count,
}: {
  window: Window;
  title: string;
  sub: string;
  count: number;
}) {
  return (
    <div className="flex items-baseline gap-3 mb-3">
      <MoverWindowBadge w={w} />
      <h3 className="text-[16px] font-headline font-bold tracking-tight text-on-surface">
        {title}
      </h3>
      <span className="text-[11px] text-on-surface-variant/60">{sub}</span>
      <span className="ml-auto text-[11px] tabular-nums text-on-surface-variant/55">
        {count} {count === 1 ? "active" : "active"}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// TodayMoverCard — 4-up grid card, prominent move number
// ---------------------------------------------------------------------------

export function TodayMoverCard({
  mover,
  onAnalyze,
}: {
  mover: MarketMover;
  onAnalyze?: (headline: string, opts?: { eventId?: number }) => void;
}) {
  const lead = _leadTicker(mover.tickers);
  const r5 = lead?.return_5d ?? null;
  const dir = _dir(r5);
  const thesis = deriveThesisState(mover);
  const evidence = deriveEvidenceLabel(mover);
  const cluster = mover.tickers
    .slice(1, 5)
    .map((t) => t.symbol)
    .join(" · ");
  const since = mover.days_since_event != null
    ? mover.days_since_event === 0
      ? "today"
      : `${mover.days_since_event}d ago`
    : "";

  return (
    <button
      type="button"
      onClick={() => onAnalyze?.(mover.headline, { eventId: mover.event_id })}
      className={cn(
        "group bg-surface-container-low rounded-xl p-4 flex flex-col gap-3 text-left",
        "hover:ring-1 hover:ring-primary/25 transition-[box-shadow,background-color,transform]",
        "hover:bg-surface-container-low/70 transition-shadow",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40",
      )}
    >
      {/* Top: window badge · since · evidence dot */}
      <div className="flex items-center gap-2">
        <MoverWindowBadge w="today" />
        {since && (
          <span className="text-[11px] tabular-nums text-on-surface-variant/55 ml-auto">
            {since}
          </span>
        )}
        <EvidenceDot label={evidence} />
      </div>

      {/* Big move + lead ticker */}
      <div className="flex items-baseline gap-2">
        {r5 != null ? (
          <span
            className={cn(
              "font-headline font-extrabold text-[26px] leading-none tracking-tight tabular-nums",
              _MOVE_TONE[dir],
            )}
          >
            {pct(r5)}
          </span>
        ) : (
          <span className="font-headline font-extrabold text-[26px] leading-none tracking-tight text-on-surface-variant/30">
            —
          </span>
        )}
        {lead && (
          <span className="text-[12px] font-medium uppercase tracking-[0.12em] text-on-surface-variant/85">
            {lead.symbol}
          </span>
        )}
      </div>

      {/* Headline */}
      <p className="text-[13px] font-medium text-on-surface leading-snug line-clamp-2">
        {mover.headline}
      </p>

      {/* Mechanism summary */}
      {mover.mechanism_summary && (
        <p className="text-[11px] text-on-surface-variant/70 leading-relaxed line-clamp-2">
          {_truncate(mover.mechanism_summary, 120)}
        </p>
      )}

      {/* Footer: thesis pill + cluster tickers */}
      <div className="mt-auto flex items-center gap-2 pt-1">
        <ThesisPill state={thesis} />
        <TodayEvidenceRead mover={mover} label={evidence} />
        {cluster && (
          <span className="ml-auto text-[11px] tabular-nums text-on-surface-variant/45 truncate max-w-[120px]">
            {cluster}
          </span>
        )}
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// WeeklyMoverCard — 2-up grid card, sparkline + editorial note
// ---------------------------------------------------------------------------

function _Spark({
  series,
  dir,
  width = 120,
  height = 56,
}: {
  series: number[];
  dir: Direction;
  width?: number;
  height?: number;
}) {
  if (!series || series.length === 0) return null;
  const max = Math.max(...series);
  const cols = series.length;
  const colW = width / cols;
  const stroke =
    dir === "up" ? "rgb(147 209 211)" :
    dir === "dn" ? "rgb(187 85 81)" :
    "rgba(171,169,188,0.55)";
  const inactive =
    dir === "up" ? "rgba(147,209,211,0.28)" :
    dir === "dn" ? "rgba(238,125,119,0.28)" :
    "rgba(171,169,188,0.18)";
  return (
    <svg
      role="img"
      aria-label="recent move"
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      preserveAspectRatio="none"
    >
      {series.map((v, i) => {
        const h = max > 0 ? Math.max(2, (v / max) * height) : 2;
        const x = i * colW;
        const y = height - h;
        const isLast = i === series.length - 1;
        return (
          <rect
            key={i}
            x={x + 0.6}
            y={y}
            width={Math.max(1, colW - 1.5)}
            height={h}
            fill={isLast ? stroke : inactive}
          />
        );
      })}
    </svg>
  );
}

export function WeeklyMoverCard({
  mover,
  onAnalyze,
}: {
  mover: MarketMover;
  onAnalyze?: (headline: string, opts?: { eventId?: number }) => void;
}) {
  const lead = _leadTicker(mover.tickers);
  const r5 = lead?.return_5d ?? null;
  const dir = _dir(r5);
  const thesis = deriveThesisState(mover);
  const evidence = deriveEvidenceLabel(mover);
  const cluster = mover.tickers.slice(0, 5).map((t) => t.symbol);
  const spark = lead?.spark ?? [];
  const note = mover.thesis_state_reason
    || mover.evidence?.narrative
    || _truncate(mover.mechanism_summary, 160);

  return (
    <button
      type="button"
      onClick={() => onAnalyze?.(mover.headline, { eventId: mover.event_id })}
      className={cn(
        "group bg-surface-container-low rounded-xl p-5 flex flex-col gap-3 text-left",
        "hover:ring-1 hover:ring-primary/25 transition-[box-shadow,background-color,transform]",
        "hover:bg-surface-container-low/70 transition-shadow",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40",
      )}
    >
      {/* Top row: window + mech kicker + thesis pill */}
      <div className="flex items-center gap-2">
        <MoverWindowBadge w="weekly" />
        <span className="text-[11px] text-on-surface-variant/65 truncate max-w-[280px]">
          {_truncate(mover.mechanism_summary, 70)}
        </span>
        <span className="ml-auto">
          <ThesisPill state={thesis} />
        </span>
      </div>

      {/* Headline */}
      <h4 className="text-[15px] font-headline font-semibold tracking-tight text-on-surface leading-snug line-clamp-2">
        {mover.headline}
      </h4>

      {/* 2-col: 5d move + cluster | sparkline + evidence */}
      <div className="grid grid-cols-[1fr_auto] gap-5 items-end">
        <div className="min-w-0">
          <p className="text-[11px] font-bold uppercase tracking-[0.15em] text-on-surface-variant/55 mb-1">
            5d move{lead ? ` · ${lead.symbol}` : ""}
          </p>
          <p
            className={cn(
              "font-headline font-extrabold text-[28px] leading-none tracking-tight tabular-nums mb-2",
              _MOVE_TONE[dir],
            )}
          >
            {r5 != null ? pct(r5) : "—"}
          </p>
          <div className="flex flex-wrap gap-1">
            {cluster.map((sym) => (
              <span
                key={sym}
                className="text-[11px] tabular-nums px-1.5 py-0.5 rounded bg-surface-container-highest text-on-surface-variant"
              >
                {sym}
              </span>
            ))}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          {spark.length > 0 ? (
            <_Spark series={spark} dir={dir} />
          ) : (
            <div className="h-14 w-[120px] rounded bg-surface-container-highest/40" />
          )}
          <EvidenceLabel label={evidence} />
        </div>
      </div>

      {/* Editorial note */}
      {note && (
        <p className="text-[11px] italic text-on-surface-variant/75 leading-relaxed pt-2 border-t border-outline-variant/12">
          {note}
        </p>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// PersistentMoverRow — horizontal row with days-since anchor + 3 metrics
// ---------------------------------------------------------------------------

export function PersistentMoverRow({
  mover,
  onAnalyze,
}: {
  mover: MarketMover;
  onAnalyze?: (headline: string, opts?: { eventId?: number }) => void;
}) {
  const lead = _leadTicker(mover.tickers);
  const r5 = lead?.return_5d ?? null;
  const r20 = lead?.return_20d ?? null;
  const r5Dir = _dir(r5);
  const r20Dir = _dir(r20);
  const thesis = deriveThesisState(mover);
  const evidence = deriveEvidenceLabel(mover);
  const days = mover.days_since_event ?? 0;
  const weighted = mover.weighted_evidence?.evidence_score ?? null;
  const spark = lead?.spark ?? [];
  const note = mover.thesis_state_reason
    || mover.evidence?.narrative
    || _truncate(mover.mechanism_summary, 90);

  return (
    <button
      type="button"
      onClick={() => onAnalyze?.(mover.headline, { eventId: mover.event_id })}
      className={cn(
        "group w-full bg-surface-container-low rounded-xl p-4",
        "hover:ring-1 hover:ring-primary/25 transition-[box-shadow,background-color,transform]",
        "hover:bg-surface-container-low/70 transition-shadow text-left",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40",
      )}
    >
      <div className="flex items-center gap-5">
        {/* Days-active anchor */}
        <div className="flex flex-col items-center shrink-0 px-3 py-1 border-r border-outline-variant/15">
          <span className="font-headline font-extrabold text-[22px] leading-none tracking-tight text-primary tabular-nums">
            {days}
          </span>
          <span className="text-[11px] uppercase tracking-[0.15em] text-on-surface-variant/60 mt-1 text-center leading-tight">
            days<br />active
          </span>
        </div>

        {/* Mid: badge + mech, headline, discipline marks */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1">
            <MoverWindowBadge w="persistent" />
            <span className="text-[11px] text-on-surface-variant/60 truncate">
              {_truncate(mover.mechanism_summary, 80)}
            </span>
          </div>
          <h4 className="text-[15px] font-headline font-semibold tracking-tight text-on-surface leading-snug line-clamp-2 mb-1.5">
            {mover.headline}
          </h4>
          <div className="flex items-center gap-3 flex-wrap">
            <ThesisPill state={thesis} />
            <EvidenceLabel label={evidence} />
            {note && (
              <span className="text-[11px] text-on-surface-variant/60 line-clamp-1 max-w-[260px]">
                {note}
              </span>
            )}
          </div>
        </div>

        {/* Right: 3 numeric columns + sparkline */}
        <div className="flex items-end gap-5 shrink-0">
          <div className="flex flex-col items-end gap-0.5">
            <span className="text-[11px] uppercase tracking-[0.12em] text-on-surface-variant/55">
              5d
            </span>
            <span className={cn("text-[13px] tabular-nums font-semibold", _MOVE_TONE[r5Dir])}>
              {r5 != null ? pct(r5) : "—"}
            </span>
          </div>
          <div className="flex flex-col items-end gap-0.5">
            <span className="text-[11px] uppercase tracking-[0.12em] text-on-surface-variant/55">
              20d
            </span>
            <span
              className={cn(
                "font-headline font-extrabold text-[22px] leading-none tracking-tight tabular-nums",
                _MOVE_TONE[r20Dir],
              )}
            >
              {r20 != null ? pct(r20) : "—"}
            </span>
          </div>
          <div className="flex flex-col items-end gap-0.5 min-w-[60px]">
            <span className="text-[11px] uppercase tracking-[0.12em] text-on-surface-variant/55">
              Weighted
            </span>
            <span
              className={cn(
                "text-[14px] tabular-nums font-semibold",
                weighted == null
                  ? "text-on-surface-variant/40"
                  : weighted >= 0
                  ? "text-primary"
                  : "text-error-dim",
              )}
            >
              {weighted == null
                ? "—"
                : (weighted >= 0 ? "+" : "") + weighted.toFixed(2)}
            </span>
          </div>
          {spark.length > 0 && (
            <_Spark series={spark} dir={r20Dir} width={80} height={32} />
          )}
          <ArrowRight className="h-4 w-4 text-on-surface-variant/40 group-hover:text-primary transition-colors" />
        </div>
      </div>
    </button>
  );
}
