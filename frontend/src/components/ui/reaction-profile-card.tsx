/**
 * Shared Reaction Profile readout (P2) — the single mounted consumer of
 * `reaction_profile_v1` (fresh Analyze and the Archive-detail cached
 * restore both render this card).
 *
 * Consumer-correctness contract (lib/reaction-profile-consumer.ts):
 *
 *   - the active horizon is the longest genuinely scorable one
 *     (20d → 5d → 1d), never a hardcoded 20d;
 *   - all three frozen horizons stay visible with explicit availability
 *     states; unscorable horizons are disabled, and a fallback from a
 *     longer horizon is explained in plain text, not a tooltip;
 *   - the classification is labeled as a raw-price path read; the
 *     benchmark-relative return is a comparison, never the label source;
 *   - horizon and basis disagreement are listed, never averaged, voted,
 *     or collapsed into a score;
 *   - an endpoint peak (peak on the final observed session) carries a
 *     first-class right-censoring qualifier adjacent to the label;
 *   - missing data renders an explicit state — no zeros, no defaults,
 *     no NaN, no fallback to a stale selection from a prior event.
 *
 * Purely presentational: no fetch, no mutation, no new classification —
 * every figure is read verbatim from the payload.
 */

import { useState } from "react";

import { cn } from "@/lib/utils";
import type { ReactionProfileTicker, ReactionProfileV1Block } from "@/lib/api";
import {
  BASIS_SENSITIVE_LABEL,
  FROZEN_DISPLAY_HORIZONS,
  HORIZON_FORWARD_BARS,
  MIXED_HORIZONS_LABEL,
  NO_CLASSIFICATION_AT_1D,
  RAW_PATH_BASIS_NOTE,
  RAW_PATH_CLASSIFICATION_LABEL,
  RIGHT_CENSORED_LABEL,
  RIGHT_CENSORED_NOTE,
  type HorizonState,
  type ReactionHorizonId,
  classifyTickerHorizon,
  describeHorizonFallback,
  detectBasisDisagreement,
  detectHorizonDisagreement,
  formatSignedPct,
  isHorizonSelectable,
  resolveActiveHorizon,
} from "@/lib/reaction-profile-consumer";

// Style tokens — mirror analysis-view.tsx so the card sits flush inside
// the Analyze grid (same pattern as engine-phase-summary.tsx).
const SECTION_CARD = "bg-surface-container-low rounded-lg";
const INNER_CARD = "bg-surface-container-highest rounded-md";

const CHIP =
  "rounded-sm border border-[color:var(--so-rule)] px-1.5 py-0.5 "
  + "font-mono text-[9px] uppercase tracking-[0.08em] text-[var(--so-ink-2)]";

const MAX_TICKER_ROWS = 4;

function _labelize(value: string | null | undefined, fallback = "Unknown"): string {
  if (!value) return fallback;
  return value
    .replace(/_/g, " ")
    .replace(/(?:^|\s)\w/g, (c) => c.toUpperCase());
}

function _pctOrDash(v: number | null | undefined): string {
  return formatSignedPct(v) ?? "—";
}

/** Chip sub-label summarizing one horizon's state across the tickers. */
function _controlState(
  tickers: readonly ReactionProfileTicker[],
  horizon: ReactionHorizonId,
): string {
  if (isHorizonSelectable(tickers, horizon)) {
    return horizon === "1d" ? "return only" : "available";
  }
  const allInsufficient =
    tickers.length > 0
    && tickers.every(
      (t) => classifyTickerHorizon(t, horizon).availability === "insufficient",
    );
  return allInsufficient ? "insufficient observations" : "unavailable";
}

/** Short display token for one horizon state in the comparison list. */
function _stateToken(state: HorizonState): string {
  switch (state.availability) {
    case "available":
      return _labelize(state.label, "—");
    case "insufficient":
      return "insufficient observations";
    case "structural":
      return "no classification";
    default:
      return "unavailable";
  }
}

export interface ReactionProfileCardProps {
  block: ReactionProfileV1Block;
  /** Optional starting selection; re-resolved against the current
   *  tickers, so an unscorable request can never become active. */
  initialHorizon?: ReactionHorizonId;
}

export function ReactionProfileCard({ block, initialHorizon }: ReactionProfileCardProps) {
  const tickers = block.tickers ?? [];
  const [requested, setRequested] = useState<ReactionHorizonId | null>(
    initialHorizon ?? null,
  );
  const active = resolveActiveHorizon(tickers, requested);
  const isUnscorable = !block.available;
  const scorable = !isUnscorable && tickers.length > 0 && active !== null;
  const fallbackNote = scorable ? describeHorizonFallback(tickers, active) : null;
  const displayTickers = tickers.slice(0, MAX_TICKER_ROWS);

  const activeStates = scorable
    ? displayTickers.map((t) => ({
        ticker: t,
        state: classifyTickerHorizon(t, active),
        basisDisagrees: detectBasisDisagreement(t, active),
      }))
    : [];
  const anyCensored = activeStates.some(({ state }) => state.rightCensored);

  // Unique per-horizon reasons for the limitation area — every
  // non-selectable frozen horizon states why, in text, on the card.
  const limitationLines: string[] = [];
  if (scorable) {
    for (const h of FROZEN_DISPLAY_HORIZONS) {
      if (isHorizonSelectable(tickers, h)) continue;
      const reasons = new Set(
        displayTickers
          .map((t) => classifyTickerHorizon(t, h).reason)
          .filter((r): r is string => typeof r === "string"),
      );
      for (const r of reasons) limitationLines.push(`${h}: ${r}`);
    }
  }

  return (
    <section className={cn(SECTION_CARD, "p-5")}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="az-card-title mb-2">Reaction profile</p>
          <div
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1",
              isUnscorable ? "bg-[rgba(122,134,148,0.10)]" : "bg-[rgba(152,194,173,0.10)]",
            )}
          >
            <span className={cn("h-1.5 w-1.5 rounded-full", isUnscorable ? "bg-[var(--so-slate)]" : "bg-[var(--so-jade-ink)]")} />
            <span
              className={cn(
                "text-[10px] font-bold uppercase tracking-[0.14em]",
                isUnscorable ? "text-[var(--so-slate)]" : "text-[var(--so-jade-ink)]",
              )}
            >
              {isUnscorable ? "Unscorable" : "Available"}
            </span>
          </div>
        </div>
        <div className="text-right">
          <p className="font-mono text-[9px] uppercase tracking-[0.14em] text-[var(--so-ink-3)]">
            Tickers
          </p>
          <p className="font-[family-name:var(--so-display)] text-[24px] font-normal leading-none tabular-nums text-[var(--so-ink-0)]">
            {block.n_tickers ?? tickers.length}
          </p>
        </div>
      </div>

      <p className="mb-4 font-[family-name:var(--so-serif)] text-[12.5px] font-light italic leading-relaxed text-[var(--so-ink-2)]">
        {block.reason || (isUnscorable ? "Not enough stored price history to score the reaction profile." : "Reaction profile computed.")}
      </p>

      {!scorable ? (
        <div className={cn(INNER_CARD, "px-3 py-2 text-[11px] text-on-surface-variant/60")}>
          {tickers.length === 0
            ? "No market tickers were stored for this event, so there is no per-ticker reaction profile."
            : "No horizon among 1d / 5d / 20d is scorable for this event; the states above say why. No classification is shown in its place."}
        </div>
      ) : (
        <div>
          {/* Active horizon + controls — all three frozen horizons stay
              visible; unscorable ones are disabled, never hidden. */}
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2 border-t border-[color:var(--so-rule)] pt-3">
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-[var(--so-ink-1)]">
              Active horizon: {active}
            </span>
            <div className="flex flex-wrap items-center gap-1.5">
              {FROZEN_DISPLAY_HORIZONS.map((h) => {
                const selectable = isHorizonSelectable(tickers, h);
                return (
                  <button
                    key={h}
                    type="button"
                    disabled={!selectable}
                    aria-pressed={h === active}
                    onClick={() => {
                      if (isHorizonSelectable(tickers, h)) setRequested(h);
                    }}
                    className={cn(
                      "flex items-baseline gap-1.5 rounded-sm border px-2 py-1 text-left",
                      h === active
                        ? "border-[color:var(--so-ink-2)]"
                        : "border-[color:var(--so-rule)]",
                      !selectable && "opacity-60",
                    )}
                  >
                    <span className="font-mono text-[10.5px] text-[var(--so-ink-0)]">{h}</span>
                    <span className="font-mono text-[8.5px] uppercase tracking-[0.06em] text-[var(--so-ink-3)]">
                      {_controlState(tickers, h)}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
          {fallbackNote && (
            <p className="mb-3 font-mono text-[10px] tracking-[0.02em] text-[var(--so-ink-1)]">
              {fallbackNote}
            </p>
          )}

          {/* Raw-price path classification at the active horizon. */}
          <p className="mt-1 font-mono text-[9px] uppercase tracking-[0.12em] text-[var(--so-ink-3)]">
            {RAW_PATH_CLASSIFICATION_LABEL} · {active}
          </p>
          <p className="mb-1 font-[family-name:var(--so-serif)] text-[11.5px] font-light italic leading-snug text-[var(--so-ink-2)]">
            {RAW_PATH_BASIS_NOTE}
          </p>

          {activeStates.map(({ ticker, state, basisDisagrees }, index) => (
            <div
              key={`${ticker.symbol ?? "ticker"}-${index}`}
              className="border-b border-[color:var(--so-rule)] py-2 last:border-b-0"
            >
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="w-[58px] shrink-0 font-mono text-[12px] text-[var(--so-ink-0)]">
                  {ticker.symbol || "—"}
                </span>
                <span className="min-w-0 truncate font-mono text-[9.5px] uppercase tracking-[0.06em] text-[var(--so-ink-3)]">
                  {_labelize(ticker.reaction_profile_basis, "no basis")}
                </span>
                {state.availability === "available" ? (
                  <span className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-[var(--so-ink-0)]">
                    {_labelize(state.label, "—")}
                  </span>
                ) : (
                  <span className="font-mono text-[9.5px] uppercase tracking-[0.06em] text-[var(--so-ink-2)]">
                    {_stateToken(state)}
                  </span>
                )}
                {state.rightCensored && (
                  <span className={CHIP}>{RIGHT_CENSORED_LABEL}</span>
                )}
                {basisDisagrees && <span className={CHIP}>{BASIS_SENSITIVE_LABEL}</span>}
              </div>
              <div className="mt-1 flex flex-wrap items-baseline gap-x-4 gap-y-0.5 pl-[58px] font-mono text-[10px] tabular-nums text-[var(--so-ink-1)]">
                <span>Raw {_pctOrDash(state.rawReturn)}</span>
                <span>Benchmark-relative {_pctOrDash(state.benchmarkRelativeReturn)}</span>
                {state.availability === "available" && active !== "1d" && (
                  <span>
                    Peak {_pctOrDash(state.peakMovePct)} · session {state.timeToPeakBars}
                    /{HORIZON_FORWARD_BARS[active]}
                  </span>
                )}
              </div>
            </div>
          ))}

          {tickers.length > MAX_TICKER_ROWS && (
            <p className="mt-1 font-mono text-[9px] uppercase tracking-[0.08em] text-[var(--so-ink-3)]">
              Showing first {MAX_TICKER_ROWS} of {tickers.length} tickers.
            </p>
          )}

          {anyCensored && (
            <p className="mt-2 font-[family-name:var(--so-serif)] text-[11.5px] font-light italic leading-snug text-[var(--so-ink-2)]">
              {RIGHT_CENSORED_LABEL}: the peak falls on the final observed
              session of the window. {RIGHT_CENSORED_NOTE}
            </p>
          )}

          {/* Across-horizon comparison — each horizon keeps its own
              state; disagreement is listed, never voted into a winner. */}
          <div className="mt-3 border-t border-[color:var(--so-rule)] pt-2">
            <p className="mb-1 font-mono text-[9px] uppercase tracking-[0.12em] text-[var(--so-ink-3)]">
              Across horizons
            </p>
            {displayTickers.map((ticker, index) => {
              const d = detectHorizonDisagreement(ticker);
              return (
                <div
                  key={`across-${ticker.symbol ?? "ticker"}-${index}`}
                  className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-1"
                >
                  <span className="w-[58px] shrink-0 font-mono text-[11px] text-[var(--so-ink-1)]">
                    {ticker.symbol || "—"}
                  </span>
                  {d.states.map((s) => (
                    <span
                      key={s.horizon}
                      className="flex items-baseline gap-1 font-mono text-[9.5px] uppercase tracking-[0.06em]"
                    >
                      <span className="text-[var(--so-ink-3)]">{s.horizon}</span>
                      <span className="text-[var(--so-ink-1)]">{_stateToken(s)}</span>
                      {s.rightCensored && (
                        <span className="text-[var(--so-ink-3)]">· right-censored</span>
                      )}
                    </span>
                  ))}
                  {d.mixed ? (
                    <span className={CHIP}>{MIXED_HORIZONS_LABEL}</span>
                  ) : (
                    d.availableLabels.length >= 2 && (
                      <span className="font-mono text-[9px] uppercase tracking-[0.06em] text-[var(--so-ink-3)]">
                        Available horizons agree
                      </span>
                    )
                  )}
                </div>
              );
            })}
          </div>

          {/* Limitations — availability reasons and the structural 1d
              boundary stay on the card, not in a tooltip. */}
          <div className="mt-2 border-t border-[color:var(--so-rule)] pt-2">
            {limitationLines.map((line) => (
              <p
                key={line}
                className="font-mono text-[9.5px] tracking-[0.02em] text-[var(--so-ink-2)]"
              >
                {line}
              </p>
            ))}
            <p className="font-[family-name:var(--so-serif)] text-[11px] font-light italic leading-snug text-[var(--so-ink-3)]">
              {NO_CLASSIFICATION_AT_1D}
            </p>
          </div>
        </div>
      )}
    </section>
  );
}
