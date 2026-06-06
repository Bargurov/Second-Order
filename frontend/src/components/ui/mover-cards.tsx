/**
 * Market Overview movers — three windows ported from the Slice 02 design
 * package (`.mo-mover` / `.mo-persist`):
 *   - TodayMoverCard      4-up grid · ticker · signed move · serif event lead
 *   - WeeklyMoverCard     2-up grid · same shape + a quiet evidence chip
 *   - PersistentMoverRow  hairline rows · ticker / lead+mech / days / 20d move
 *
 * Mono tickers/labels, serif leads, jade/rust signed moves, citrine mechanism
 * tags — the design palette, inherited as CSS vars from the page root. No
 * sparklines, glow dots, or thesis pills; the page reports the read, it does
 * not grade direction. All three consume the existing MarketMover wire shape;
 * optional enrichment (`weighted_evidence`) feeds only the weekly evidence
 * chip and falls back to "insufficient".
 */

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { MarketMover, MoverTicker, MoverWeightedEvidence } from "@/lib/api";

type Direction = "up" | "dn" | "flat";

function _dir(value: number | null | undefined): Direction {
  if (value == null) return "flat";
  if (value > 0) return "up";
  if (value < 0) return "dn";
  return "flat";
}

const _DELTA_TONE: Record<Direction, string> = {
  up: "text-[var(--so-jade-ink)]",
  dn: "text-[var(--so-rust-ink)]",
  flat: "text-[var(--so-ink-3)]",
};

// Signed, tabular delta with a real U+2212 minus — matches the kit's Delta.
function fmtDelta(value: number | null): string {
  if (value == null) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(2)}%`;
}

function _leadTicker(tickers: MoverTicker[]): MoverTicker | null {
  return tickers.length > 0 ? tickers[0]! : null;
}

function _since(days: number | null | undefined): string {
  if (days == null) return "";
  if (days === 0) return "today";
  return `${days}d ago`;
}

// ---------------------------------------------------------------------------
// Quiet evidence chip — the design's significance-chip slot on weekly cards.
// Reports the weighted-evidence read; never a directional verdict.
// ---------------------------------------------------------------------------

type EvidenceLabel = NonNullable<MoverWeightedEvidence["evidence_label"]>;

function deriveEvidenceLabel(m: MarketMover): EvidenceLabel {
  return m.weighted_evidence?.evidence_label ?? "insufficient";
}

const _EVIDENCE_CHIP: Record<EvidenceLabel, string> = {
  supportive: "border-[color:var(--so-bd-jade)] text-[var(--so-jade-ink)]",
  contradictory: "border-[color:var(--so-bd-rust)] text-[var(--so-rust-ink)]",
  mixed: "border-[color:var(--so-rule-hi)] text-[var(--so-slate)]",
  insufficient: "border-[color:var(--so-rule)] text-[var(--so-ink-3)]",
};

function EvidenceChip({ label }: { label: EvidenceLabel }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-[2px] border px-1.5 py-[2px] font-mono text-[9px] uppercase tracking-[0.1em]",
        _EVIDENCE_CHIP[label],
      )}
    >
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Section chrome — sub-window head (`.mo-subwin-head`): mono label, mono sub,
// citrine count.
// ---------------------------------------------------------------------------

export function MoversSectionHead({
  title,
  sub,
  count,
}: {
  title: string;
  sub: string;
  count: number;
}) {
  return (
    <div className="mb-2.5 flex items-baseline gap-3">
      <h3 className="shrink-0 font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-[var(--so-ink-1)]">
        {title}
      </h3>
      <span className="min-w-0 truncate font-mono text-[10px] tracking-[0.02em] text-[var(--so-ink-3)]">
        {sub}
      </span>
      <span className="ml-auto shrink-0 font-mono text-[11px] tabular-nums text-[var(--so-citrine)]">
        {count}
      </span>
    </div>
  );
}

// Dashed, serif-italic empty-state line — the design's `.mo-empty-line`.
export function MoverEmptyLine({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-[4px] border border-dashed border-[color:var(--so-rule)] bg-[rgba(255,255,255,0.008)] px-4 py-3 font-[family-name:var(--so-serif)] text-[13px] italic text-[var(--so-ink-3)]">
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Consolidated Event-Activity empty state.
//
// When all three mover windows (today / weekly / persistent) are empty, three
// separate dashed lines read as three disconnected "broken" empties.  The
// emptiness is HONEST — no recent events, and persistent is strict by design —
// so this collapses them into one coherent research-style block: a quiet,
// intentional read, never an error.  No fabricated movers, no buy/sell framing.
// ---------------------------------------------------------------------------

// True only when every mover window is empty.  Drives the consolidated empty
// state; any populated window keeps the per-window cards instead.
export function allMoverWindowsEmpty(
  today: MarketMover[],
  weekly: MarketMover[],
  persistent: MarketMover[],
): boolean {
  return today.length === 0 && weekly.length === 0 && persistent.length === 0;
}

const EVENT_ACTIVITY_EMPTY_TITLE =
  "No events currently qualify for these windows";

const EVENT_ACTIVITY_EMPTY_EXPLANATION =
  "Event activity surfaces analyzed events once their forward price windows " +
  "print. None fall inside the windows below right now — this is the " +
  "archive's current state, not a data error.";

const EVENT_ACTIVITY_EMPTY_ROWS = [
  "24h — no event-linked moves in the last trading day.",
  "5-day — no events with a settled five-day window in range.",
  "Persistent — no event meets the high-impact, still-moving bar " +
    "(strict by design; never backfilled).",
] as const;

const EVENT_ACTIVITY_EMPTY_FOOTER =
  "Movers reappear here automatically as newly analyzed events price into each window.";

export function EventActivityEmpty() {
  return (
    <div className="rounded-[4px] border border-dashed border-[color:var(--so-rule)] bg-[var(--so-bg-1)] px-5 py-5">
      <h3 className="font-[family-name:var(--so-display)] text-[14px] font-semibold tracking-[-0.01em] text-[var(--so-ink-1)]">
        {EVENT_ACTIVITY_EMPTY_TITLE}
      </h3>
      <p className="mt-2 max-w-[62ch] font-[family-name:var(--so-serif)] text-[13px] italic leading-[1.55] text-[var(--so-ink-2)]">
        {EVENT_ACTIVITY_EMPTY_EXPLANATION}
      </p>
      <div className="mt-3.5 border-t border-[color:var(--so-rule)]">
        {EVENT_ACTIVITY_EMPTY_ROWS.map((row) => (
          <p
            key={row}
            className="border-b border-[color:var(--so-rule)] py-2 font-[family-name:var(--so-serif)] text-[12.5px] italic leading-[1.5] text-[var(--so-ink-3)]"
          >
            {row}
          </p>
        ))}
      </div>
      <p className="mt-3.5 font-mono text-[10px] uppercase leading-relaxed tracking-[0.1em] text-[var(--so-ink-3)]">
        <span className="text-[var(--so-citrine)]">·</span> {EVENT_ACTIVITY_EMPTY_FOOTER}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// TodayMoverCard — 4-up · `.mo-mover`
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

  return (
    <button
      type="button"
      onClick={() => onAnalyze?.(mover.headline, { eventId: mover.event_id })}
      className={cn(
        "group flex flex-col rounded-[4px] border border-[color:var(--so-rule)] bg-[var(--so-bg-1)] px-3.5 py-3 text-left",
        "transition-colors hover:border-[color:var(--so-rule-hi)] hover:bg-[var(--so-bg-2)]",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color:var(--so-rule-hi)]",
      )}
    >
      <div className="flex items-baseline gap-2.5">
        <span className="font-mono text-[14px] font-medium tracking-[0.02em] text-[var(--so-ink-0)]">
          {lead?.symbol ?? "—"}
        </span>
        <span className={cn("ml-auto font-mono text-[14px] tabular-nums", _DELTA_TONE[dir])}>
          {fmtDelta(r5)}
        </span>
      </div>
      <p className="mt-2 line-clamp-2 font-[family-name:var(--so-serif)] text-[12.5px] leading-[1.4] text-[var(--so-ink-1)]">
        {mover.headline}
      </p>
      <div className="mt-auto flex items-baseline gap-2 pt-2.5 font-mono text-[9.5px] tracking-[0.06em]">
        {mover.mechanism_summary && (
          <span className="min-w-0 truncate text-[var(--so-citrine)]">{mover.mechanism_summary}</span>
        )}
        <span className="ml-auto shrink-0 uppercase tracking-[0.1em] text-[var(--so-ink-3)]">
          {_since(mover.days_since_event)}
        </span>
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// WeeklyMoverCard — 2-up · `.mo-mover` + evidence chip
// ---------------------------------------------------------------------------

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
  const evidence = deriveEvidenceLabel(mover);
  const cluster = mover.tickers.slice(1, 4).map((t) => t.symbol).join(" · ");

  return (
    <button
      type="button"
      onClick={() => onAnalyze?.(mover.headline, { eventId: mover.event_id })}
      className={cn(
        "group flex flex-col rounded-[4px] border border-[color:var(--so-rule)] bg-[var(--so-bg-1)] px-4 py-3.5 text-left",
        "transition-colors hover:border-[color:var(--so-rule-hi)] hover:bg-[var(--so-bg-2)]",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color:var(--so-rule-hi)]",
      )}
    >
      <div className="flex items-baseline gap-2.5">
        <span className="font-mono text-[14px] font-medium tracking-[0.02em] text-[var(--so-ink-0)]">
          {lead?.symbol ?? "—"}
        </span>
        <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-[var(--so-ink-3)]">
          5-day
        </span>
        <span className={cn("ml-auto font-mono text-[14px] tabular-nums", _DELTA_TONE[dir])}>
          {fmtDelta(r5)}
        </span>
      </div>
      <p className="mt-2 line-clamp-2 font-[family-name:var(--so-serif)] text-[13px] leading-[1.4] text-[var(--so-ink-1)]">
        {mover.headline}
      </p>
      {mover.mechanism_summary && (
        <p className="mt-1.5 line-clamp-2 font-[family-name:var(--so-serif)] text-[11.5px] leading-snug text-[var(--so-ink-2)]">
          {mover.mechanism_summary}
        </p>
      )}
      <div className="mt-auto flex items-center gap-2 pt-2.5">
        {cluster && (
          <span className="min-w-0 truncate font-mono text-[9.5px] tracking-[0.04em] text-[var(--so-ink-3)]">
            {cluster}
          </span>
        )}
        <span className="ml-auto shrink-0">
          <EvidenceChip label={evidence} />
        </span>
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// PersistentMoverRow — hairline row · `.mo-persist .prow`
// Rendered inside a single bordered container (see MoversChapter).
// ---------------------------------------------------------------------------

export function PersistentMoverRow({
  mover,
  onAnalyze,
}: {
  mover: MarketMover;
  onAnalyze?: (headline: string, opts?: { eventId?: number }) => void;
}) {
  const lead = _leadTicker(mover.tickers);
  const r20 = lead?.return_20d ?? null;
  const r20Dir = _dir(r20);
  const days = mover.days_since_event ?? 0;

  return (
    <button
      type="button"
      onClick={() => onAnalyze?.(mover.headline, { eventId: mover.event_id })}
      className={cn(
        "group grid w-full grid-cols-[52px_1fr_auto] items-center gap-4 px-4 py-3 text-left",
        "transition-colors hover:bg-[var(--so-bg-2)]",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-[color:var(--so-rule-hi)]",
      )}
    >
      <span className="font-mono text-[14px] font-medium text-[var(--so-ink-0)]">
        {lead?.symbol ?? "—"}
      </span>
      <div className="min-w-0">
        <p className="truncate font-[family-name:var(--so-serif)] text-[12.5px] text-[var(--so-ink-1)]">
          {mover.headline}
        </p>
        {mover.mechanism_summary && (
          <p className="mt-0.5 truncate font-mono text-[9.5px] uppercase tracking-[0.1em] text-[var(--so-citrine)]">
            {mover.mechanism_summary}
          </p>
        )}
      </div>
      <div className="flex items-center gap-5">
        <div className="text-right">
          <div className="font-mono text-[9px] uppercase tracking-[0.1em] text-[var(--so-ink-3)]">
            days
          </div>
          <div className="font-mono text-[12px] tabular-nums text-[var(--so-ink-2)]">{days}d</div>
        </div>
        <div className="min-w-[62px] text-right">
          <div className="font-mono text-[9px] uppercase tracking-[0.1em] text-[var(--so-ink-3)]">
            20d
          </div>
          <div className={cn("font-mono text-[14px] tabular-nums", _DELTA_TONE[r20Dir])}>
            {fmtDelta(r20)}
          </div>
        </div>
      </div>
    </button>
  );
}
