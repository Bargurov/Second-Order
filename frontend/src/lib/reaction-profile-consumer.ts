/**
 * Pure consumer contract for the Reaction Profile readout (P2).
 *
 * The frozen composer (reaction_profile.py) computes per-ticker path
 * facts: returns, peak move, time-to-peak, and a raw-price
 * `hold / fade / reverse / flat / insufficient` label per classified
 * horizon.  This module decides only what a consumer may present:
 *
 *   - which horizon is active (longest genuinely scorable, 20d → 5d → 1d);
 *   - which horizons are selectable at all;
 *   - how non-available horizons are described (never hidden);
 *   - whether classifications disagree across horizons or bases;
 *   - whether an endpoint peak is right-censored (peak on the final
 *     observed session ⇒ no observed post-peak path inside the window).
 *
 * It never re-classifies a path, introduces a threshold, or computes a
 * new basis: every figure is read verbatim from the payload.  All
 * functions are deterministic, React-free, fetch-free, and never mutate
 * their input.  Malformed input fails closed to an explicit
 * unavailable state.
 */

import type { ReactionProfileTicker } from "@/lib/api";

// ---------------------------------------------------------------------------
// Horizon registry
// ---------------------------------------------------------------------------

/** The three frozen display horizons, shortest first. */
export const FROZEN_DISPLAY_HORIZONS = ["1d", "5d", "20d"] as const;

/** Active-horizon preference: longest scorable wins. */
export const ACTIVE_HORIZON_ORDER = ["20d", "5d", "1d"] as const;

export type ReactionHorizonId = (typeof FROZEN_DISPLAY_HORIZONS)[number];

/** Horizons that carry a path classification in the frozen composer.
 *  1d has a single forward bar — no path to classify.  60d ships in the
 *  payload but stays outside the frozen display triple; it is listed in
 *  the across-horizon comparison when scorable so a disagreeing label
 *  is never hidden, and it can never become the active horizon. */
export type ClassifiedHorizonId = "5d" | "20d" | "60d";

export type DisplayHorizonId = ReactionHorizonId | "60d";

/** Forward bars per classified horizon — mirrors the frozen composer's
 *  `_HORIZONS` registry.  Window-definition knowledge, not a threshold:
 *  a time-to-peak equal to the bar count means the peak sits on the
 *  final observed session of the window. */
export const HORIZON_FORWARD_BARS: Record<ClassifiedHorizonId, number> = {
  "5d": 5,
  "20d": 20,
  "60d": 60,
};

/** The composer's scorable label vocabulary (everything else fails closed). */
export const SCORABLE_LABELS = ["hold", "fade", "reverse", "flat"] as const;

export type ScorableLabel = (typeof SCORABLE_LABELS)[number];

// ---------------------------------------------------------------------------
// Display copy — single source for every consumer.
// ---------------------------------------------------------------------------

export const RAW_PATH_CLASSIFICATION_LABEL = "Raw-price path classification";

export const RAW_PATH_BASIS_NOTE =
  "Labels classify the raw price path of each ticker over the active "
  + "horizon; benchmark-relative returns are shown for comparison and are "
  + "not the source of the label.";

export const RIGHT_CENSORED_LABEL = "Endpoint peak / right-censored";

export const RIGHT_CENSORED_NOTE =
  "No post-peak path is available inside this horizon.";

export const MIXED_HORIZONS_LABEL = "Mixed across horizons";

export const BASIS_SENSITIVE_LABEL = "Basis-sensitive readout";

export const NO_CLASSIFICATION_AT_1D =
  "No path classification is defined at 1d; the window has a single "
  + "forward session.";

const MALFORMED_REASON = "malformed horizon data";

// ---------------------------------------------------------------------------
// Availability model
// ---------------------------------------------------------------------------

/**
 * Classification availability for one (ticker, horizon) pair:
 *
 *   - "available"    — a scorable label with all companion fields intact;
 *   - "insufficient" — the composer's own `insufficient` (window not
 *                      filled by observed sessions);
 *   - "unavailable"  — nothing usable: stale / unscorable /
 *                      same-day-fallback basis, or malformed fields
 *                      (fail closed);
 *   - "structural"   — 1d only: the return exists but no path
 *                      classification is defined at this horizon.
 */
export type HorizonAvailability =
  | "available"
  | "insufficient"
  | "unavailable"
  | "structural";

export interface HorizonState {
  horizon: DisplayHorizonId;
  availability: HorizonAvailability;
  /** Verbatim engine label; only set when availability === "available". */
  label: ScorableLabel | null;
  /** Why the horizon is not available; null when it is. */
  reason: string | null;
  /** Peak sits on the final observed session of the window. */
  rightCensored: boolean;
  rawReturn: number | null;
  benchmarkRelativeReturn: number | null;
  peakMovePct: number | null;
  timeToPeakBars: number | null;
}

function _finite(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function _reasonFromBasis(basis: unknown): string {
  if (basis === "stale") return "stale ticker — forward path not scored";
  if (basis === "unscorable") return "no usable cached price path";
  if (basis === "same_day_fallback") {
    return "same-day fallback anchor — only the 1d return is scored";
  }
  return MALFORMED_REASON;
}

/** Describe one (ticker, horizon) pair.  Never throws; malformed input
 *  fails closed to an explicit "unavailable" state. */
export function classifyTickerHorizon(
  ticker: ReactionProfileTicker | null | undefined,
  horizon: DisplayHorizonId,
): HorizonState {
  const base: HorizonState = {
    horizon,
    availability: "unavailable",
    label: null,
    reason: MALFORMED_REASON,
    rightCensored: false,
    rawReturn: null,
    benchmarkRelativeReturn: null,
    peakMovePct: null,
    timeToPeakBars: null,
  };
  if (!ticker || typeof ticker !== "object") return base;

  const record = ticker as Record<string, unknown>;
  const rawReturn = _finite(record[`return_${horizon}`]);
  const bench = _finite(record[`benchmark_relative_return_${horizon}`]);

  if (horizon === "1d") {
    if (rawReturn !== null) {
      return {
        ...base,
        availability: "structural",
        reason: NO_CLASSIFICATION_AT_1D,
        rawReturn,
        benchmarkRelativeReturn: bench,
      };
    }
    return {
      ...base,
      reason: _reasonFromBasis(ticker.reaction_profile_basis),
      benchmarkRelativeReturn: bench,
    };
  }

  const basis = ticker.reaction_profile_basis;
  if (basis !== "forward_anchored") {
    return { ...base, reason: _reasonFromBasis(basis) };
  }

  const label = record[`fade_or_hold_label_${horizon}`];
  if (label === "insufficient") {
    return {
      ...base,
      availability: "insufficient",
      reason: "insufficient observations inside this horizon window",
      rawReturn,
      benchmarkRelativeReturn: bench,
    };
  }
  if (!(SCORABLE_LABELS as readonly unknown[]).includes(label)) {
    return base; // unknown vocabulary — fail closed
  }

  const peak = _finite(record[`peak_move_${horizon}`]);
  const ttp = record[`time_to_peak_${horizon}`];
  const bars = HORIZON_FORWARD_BARS[horizon];
  const ttpValid =
    typeof ttp === "number" && Number.isInteger(ttp) && ttp >= 1 && ttp <= bars;

  if (rawReturn === null || peak === null || !ttpValid) {
    // A label without its companion numbers is partially populated or
    // malformed — it must not count as scorable.
    return base;
  }

  return {
    horizon,
    availability: "available",
    label: label as ScorableLabel,
    reason: null,
    rightCensored: ttp === bars,
    rawReturn,
    benchmarkRelativeReturn: bench,
    peakMovePct: peak,
    timeToPeakBars: ttp,
  };
}

// ---------------------------------------------------------------------------
// Selection
// ---------------------------------------------------------------------------

function _tickerList(
  tickers: readonly ReactionProfileTicker[] | null | undefined,
): readonly ReactionProfileTicker[] {
  return Array.isArray(tickers) ? tickers : [];
}

/** A horizon is selectable when at least one ticker genuinely shows
 *  something there: a scorable classification (5d / 20d) or a real 1d
 *  return.  Presence of a horizon label alone never qualifies. */
export function isHorizonSelectable(
  tickers: readonly ReactionProfileTicker[] | null | undefined,
  horizon: ReactionHorizonId,
): boolean {
  const wanted = horizon === "1d" ? "structural" : "available";
  return _tickerList(tickers).some(
    (t) => classifyTickerHorizon(t, horizon).availability === wanted,
  );
}

/** Resolve the active horizon: an explicitly requested horizon wins only
 *  while it stays selectable for the CURRENT tickers (a stale selection
 *  carried over from another event re-resolves here); otherwise the
 *  longest scorable horizon; null when nothing is scorable. */
export function resolveActiveHorizon(
  tickers: readonly ReactionProfileTicker[] | null | undefined,
  requested?: ReactionHorizonId | null,
): ReactionHorizonId | null {
  const list = _tickerList(tickers);
  if (requested && isHorizonSelectable(list, requested)) return requested;
  for (const horizon of ACTIVE_HORIZON_ORDER) {
    if (isHorizonSelectable(list, horizon)) return horizon;
  }
  return null;
}

/** Visible explanation for why the active horizon fell back from a
 *  longer one.  Null when the active horizon is the longest scorable one
 *  (including a user-chosen shorter horizon while 20d stays scorable). */
export function describeHorizonFallback(
  tickers: readonly ReactionProfileTicker[] | null | undefined,
  active: ReactionHorizonId | null,
): string | null {
  if (!active) return null;
  const list = _tickerList(tickers);
  const activeIndex = ACTIVE_HORIZON_ORDER.indexOf(active);
  if (activeIndex <= 0) return null;
  const blocked = ACTIVE_HORIZON_ORDER.slice(0, activeIndex).filter(
    (h) => !isHorizonSelectable(list, h),
  );
  if (blocked.length === 0) return null;
  if (blocked.length === 1) {
    const h = blocked[0]!;
    const allInsufficient =
      list.length > 0
      && list.every(
        (t) => classifyTickerHorizon(t, h).availability === "insufficient",
      );
    return allInsufficient
      ? `Showing ${active} — ${h} has insufficient observations for this event.`
      : `Showing ${active} — ${h} is unavailable for this event.`;
  }
  return `Showing ${active} — ${blocked.join(" and ")} are unavailable for this event.`;
}

// ---------------------------------------------------------------------------
// Disagreement
// ---------------------------------------------------------------------------

export interface HorizonDisagreement {
  /** Per-horizon states in display order (1d, 5d, 20d, then 60d only
   *  when 60d carries a scorable classification). */
  states: HorizonState[];
  /** Labels of the available horizons only — the agreement arithmetic
   *  never counts unavailable or structural horizons. */
  availableLabels: ScorableLabel[];
  /** True when the available labels disagree.  No majority, vote or
   *  single blended label exists anywhere. */
  mixed: boolean;
}

export function detectHorizonDisagreement(
  ticker: ReactionProfileTicker | null | undefined,
): HorizonDisagreement {
  const states: HorizonState[] = FROZEN_DISPLAY_HORIZONS.map((h) =>
    classifyTickerHorizon(ticker, h),
  );
  const sixty = classifyTickerHorizon(ticker, "60d");
  if (sixty.availability === "available") states.push(sixty);

  const availableLabels = states
    .filter((s) => s.availability === "available" && s.label !== null)
    .map((s) => s.label as ScorableLabel);
  return {
    states,
    availableLabels,
    mixed: new Set(availableLabels).size > 1,
  };
}

/** Strict sign disagreement between the raw and benchmark-relative
 *  returns at one horizon.  Missing or non-finite values never
 *  disagree — an unavailable basis stays unavailable. */
export function detectBasisDisagreement(
  ticker: ReactionProfileTicker | null | undefined,
  horizon: DisplayHorizonId,
): boolean {
  const s = classifyTickerHorizon(ticker, horizon);
  const raw = s.rawReturn;
  const rel = s.benchmarkRelativeReturn;
  if (raw === null || rel === null) return false;
  return (raw > 0 && rel < 0) || (raw < 0 && rel > 0);
}

/** True when the horizon's peak sits on the final observed session of
 *  the window — there is no observed post-peak path inside the horizon,
 *  so the engine label must never be presented as a fully observed
 *  completed path. */
export function isEndpointPeakRightCensored(
  ticker: ReactionProfileTicker | null | undefined,
  horizon: DisplayHorizonId,
): boolean {
  if (horizon === "1d") return false;
  return classifyTickerHorizon(ticker, horizon).rightCensored;
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

/** Signed two-decimal percent, or null for anything non-finite —
 *  consumers render an explicit placeholder instead of a number. */
export function formatSignedPct(v: number | null | undefined): string | null {
  const n = _finite(v);
  if (n === null) return null;
  return n >= 0 ? `+${n.toFixed(2)}%` : `${n.toFixed(2)}%`;
}
