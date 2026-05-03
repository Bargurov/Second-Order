/**
 * Pure derivation logic for the revisit timeline display.
 *
 * Maps raw RevisitSnapshot data to display-ready state:
 *   - Per-horizon summary (avg return, supporting/total, verdict)
 *   - Per-ticker rows with return and direction
 *   - Overall thesis trajectory across available horizons
 */

import type { RevisitSnapshot, RevisitTicker } from "./api";

// ---------------------------------------------------------------------------
// Per-ticker display row
// ---------------------------------------------------------------------------

export interface RevisitTickerRow {
  symbol: string;
  role: string;
  returnValue: number | null;
  direction: "supports" | "contradicts" | "neutral";
}

// ---------------------------------------------------------------------------
// Per-horizon summary
// ---------------------------------------------------------------------------

export type HorizonVerdict = "validated" | "contradicted" | "mixed" | "no_data";

export interface HorizonSummary {
  day: number;
  label: string;
  available: boolean;
  capturedAt: string | null;
  avgReturn: number | null;
  supporting: number;
  contradicting: number;
  total: number;
  verdict: HorizonVerdict;
  tickers: RevisitTickerRow[];
}

// ---------------------------------------------------------------------------
// Overall trajectory
// ---------------------------------------------------------------------------

export type ThesisTrajectory =
  | "holding"       // latest horizon still validated
  | "fading"        // was validated, latest is mixed or no data
  | "reversed"      // latest horizon contradicted
  | "too_early"     // no horizons available yet
  | "mixed";        // some validated, some contradicted

// ---------------------------------------------------------------------------
// Derivation
// ---------------------------------------------------------------------------

const _DAY_LABELS: Record<number, string> = { 1: "1 Day", 5: "5 Day", 20: "20 Day", 60: "60 Day" };
const _HORIZONS = [1, 5, 20, 60] as const;

function _classifyDirection(ticker: RevisitTicker, day: number): "supports" | "contradicts" | "neutral" {
  // Prefer the day-specific return when available: the stored `direction` field is
  // r5-based (from followup_check) and is inaccurate for 1d / 20d / 60d horizons.
  const ret = ticker[`return_${day}d`] as number | null;
  if (ret != null) {
    const positive = ret > 0;
    if (ticker.role === "beneficiary") return positive ? "supports" : "contradicts";
    if (ticker.role === "loser") return positive ? "contradicts" : "supports";
    return "neutral";
  }
  // Fall back to stored direction string (pre-computed by backend).
  const dir = (ticker.direction ?? "") as string;
  if (dir.startsWith("supports")) return "supports";
  if (dir.startsWith("contradicts")) return "contradicts";
  return "neutral";
}

function _deriveVerdict(supporting: number, contradicting: number, total: number): HorizonVerdict {
  if (total === 0) return "no_data";
  if (supporting > 0 && contradicting === 0) return "validated";
  if (contradicting > 0 && supporting === 0) return "contradicted";
  return "mixed";
}

export function deriveHorizonSummary(
  snapshots: RevisitSnapshot[],
  day: number,
): HorizonSummary {
  const snap = snapshots.find((s) => s.day === day);
  const label = _DAY_LABELS[day] ?? `${day}D`;

  if (!snap || snap.tickers.length === 0) {
    return {
      day, label, available: false, capturedAt: null,
      avgReturn: null, supporting: 0, contradicting: 0, total: 0,
      verdict: "no_data", tickers: [],
    };
  }

  const returnKey = `return_${day}d`;
  const rows: RevisitTickerRow[] = [];
  const returns: number[] = [];
  let supporting = 0;
  let contradicting = 0;

  for (const t of snap.tickers) {
    const ret = t[returnKey] as number | null;
    const dir = _classifyDirection(t, day);
    rows.push({ symbol: t.symbol, role: t.role, returnValue: ret, direction: dir });
    if (ret != null) returns.push(ret);
    if (dir === "supports") supporting++;
    else if (dir === "contradicts") contradicting++;
  }

  const avgReturn = returns.length > 0
    ? returns.reduce((a, b) => a + b, 0) / returns.length
    : null;

  return {
    day, label, available: true,
    capturedAt: snap.captured_at,
    avgReturn,
    supporting,
    contradicting,
    total: rows.length,
    verdict: _deriveVerdict(supporting, contradicting, rows.length),
    tickers: rows,
  };
}

export function deriveAllHorizons(snapshots: RevisitSnapshot[]): HorizonSummary[] {
  return _HORIZONS.map((day) => deriveHorizonSummary(snapshots, day));
}

export function deriveTrajectory(horizons: HorizonSummary[]): ThesisTrajectory {
  const available = horizons.filter((h) => h.available);
  if (available.length === 0) return "too_early";

  const verdicts = available.map((h) => h.verdict);
  const latest = verdicts[verdicts.length - 1]!;

  if (latest === "contradicted") return "reversed";
  if (verdicts.every((v) => v === "validated")) return "holding";
  if (latest === "validated") return "holding";
  if (verdicts.some((v) => v === "validated") && verdicts.some((v) => v === "contradicted"))
    return "mixed";
  return "fading";
}
