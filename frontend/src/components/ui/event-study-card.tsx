/**
 * Event-study readout card — shared, presentational.
 *
 * Renders the gated single-event event-study payload
 * (``EventStudyBlock`` from GET /events/{id}/event-study): AR / SAR / CAR
 * point estimates per 1d / 5d / 20d horizon when computable, else an
 * explicit "not computable" block with the engine's blocking reasons.
 *
 * Research-craft discipline (do not soften):
 *  - Point estimates only at n = 1 — no confidence interval, p-value, or
 *    false-discovery control, and never a pass/fail verdict.  The card is
 *    a descriptive tape read, not a confirmation of any mechanism.
 *
 * Self-contained styling: the Direction-C ``--so-*`` tokens and the
 * ``az-card-title`` helper live under the ``.az-canvas`` scope in
 * ``analyze-canvas.css``, so the card wraps itself in that scope and
 * imports the stylesheet.  This lets read-only surfaces (the /share
 * snapshot, the archive detail panel) render the identical card without
 * sitting inside the analyze page's canvas.
 */

import "@/styles/analyze-canvas.css";
import { cn } from "@/lib/utils";
import type { EventStudyBlock } from "@/lib/api";

// Shared card class for big section cards (bg-surface-container-low).
const SECTION_CARD = "bg-surface-container-low rounded-lg";

function labelize(value: string | null | undefined, fallback = "Unknown"): string {
  if (!value) return fallback;
  return value
    .replace(/_/g, " ")
    .replace(/(?:^|\s)\w/g, (c) => c.toUpperCase());
}

// Event-study readout formatters — AR / CAR are fractional returns shown
// as signed percent; SAR is a standardized value shown as a signed number.
// Tone is directional only (teal up / coral down / muted null) — a
// descriptive readout, never a pass/fail verdict, so no status badge.
function esTone(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "text-[var(--so-ink-3)]";
  if (v > 0) return "text-[var(--so-jade-ink)]";
  if (v < 0) return "text-[var(--so-rust-ink)]";
  return "text-[var(--so-ink-2)]";
}

function esPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
}

function esNum(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}`;
}

export function EventStudyCard({ block }: { block: EventStudyBlock }) {
  const available = block.status === "event_study_available";
  const horizons = block.per_horizon ?? [];
  const reasons = block.blocking_reasons ?? [];

  return (
    // ``display: contents`` (Tailwind ``contents``) makes this wrapper
    // layout-transparent: it provides the ``.az-canvas`` variable scope and
    // descendant-selector context (both DOM-based, unaffected by
    // ``display: contents``) without generating its own box.  So the inner
    // <section> stays the direct layout child of whatever renders the card —
    // e.g. it remains the grid item inside the analyze view's two-column
    // panel, with no height-stretch regression.
    <div className="contents az-canvas">
      <section className={cn(SECTION_CARD, "p-5")}>
        <p className="az-card-title">Event-study readout</p>
        <p className="mb-4 mt-2 font-mono text-[9px] uppercase tracking-[0.14em] text-[var(--so-ink-3)]">
          Single event · n = 1 · point estimates only
        </p>

        {available ? (
          <div>
            <div className="grid grid-cols-[44px_1fr_1fr_1fr] items-baseline gap-3 border-b border-[color:var(--so-rule)] pb-1.5">
              <span />
              {(["AR", "SAR", "CAR"] as const).map((h) => (
                <span
                  key={h}
                  className="text-right font-mono text-[8.5px] uppercase tracking-[0.1em] text-[var(--so-ink-3)]"
                >
                  {h}
                </span>
              ))}
            </div>
            {horizons.map((row) => (
              <div
                key={row.horizon}
                className="grid grid-cols-[44px_1fr_1fr_1fr] items-baseline gap-3 border-b border-[color:var(--so-rule)] py-2 last:border-b-0"
              >
                <span className="font-mono text-[12px] text-[var(--so-ink-0)]">{row.horizon}d</span>
                <span className={cn("text-right font-mono text-[12px] tabular-nums", esTone(row.abnormal_return))}>
                  {esPct(row.abnormal_return)}
                </span>
                <span className={cn("text-right font-mono text-[12px] tabular-nums", esTone(row.sar))}>
                  {esNum(row.sar)}
                </span>
                <span className={cn("text-right font-mono text-[12px] tabular-nums", esTone(row.car))}>
                  {esPct(row.car)}
                </span>
              </div>
            ))}
            <p className="mt-3 font-mono text-[9.5px] uppercase tracking-[0.08em] text-[var(--so-ink-3)]">
              vs {block.benchmark || "SPY"}
              {block.estimation_window_used != null ? ` · ${block.estimation_window_used}-bar window` : ""}
            </p>
          </div>
        ) : (
          <div>
            <p className="mb-2 font-[family-name:var(--so-serif)] text-[12.5px] font-light italic leading-relaxed text-[var(--so-ink-2)]">
              Not computable for this event.
            </p>
            {reasons.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {reasons.map((r) => (
                  <span
                    key={r}
                    className="rounded bg-[rgba(122,134,148,0.10)] px-1.5 py-0.5 font-mono text-[9.5px] uppercase tracking-[0.06em] text-[var(--so-ink-3)]"
                  >
                    {labelize(r)}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        <p className="mt-4 border-t border-[color:var(--so-rule)] pt-3 font-[family-name:var(--so-serif)] text-[11px] font-light italic leading-relaxed text-[var(--so-ink-3)]">
          Abnormal return (AR), standardized AR (SAR), and cumulative AR (CAR) vs
          SPY over 1d / 5d / 20d, against a 60-bar estimation window. Descriptive
          point estimates for one event — no confidence interval, p-value, or
          false-discovery control at n = 1. Not a pass/fail verdict.
        </p>
      </section>
    </div>
  );
}
