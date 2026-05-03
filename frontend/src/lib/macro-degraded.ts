/**
 * Pure derivation: detect degraded/missing state for macro sections.
 *
 * Each function returns null when the section is healthy, or a short
 * warning string when data is null/missing/degraded.  The UI renders
 * a compact inline notice using the returned message.
 */

import type { StressRegime, RatesContext, StressComponentDetail } from "./api";

export function deriveStressDegraded(
  stress: StressRegime | null | undefined,
): string | null {
  if (!stress) return "Stress data unavailable";
  const detail = stress.detail ?? {};
  const keys = ["volatility", "term_structure", "credit", "safe_haven", "breadth"] as const;
  const present = keys.filter((k) => {
    const d = detail[k] as StressComponentDetail | undefined;
    return d && d.status !== undefined;
  });
  if (present.length === 0) return "All stress signals unavailable";
  // Count how many have null primary values
  const missing = present.filter((k) => {
    const d = detail[k] as StressComponentDetail;
    return d.value == null && d.spread_5d == null && d.gap_5d == null && d.inflow_count == null;
  });
  if (missing.length === present.length) return "All stress values missing";
  if (missing.length > 0)
    return `${missing.length} of ${present.length} stress signals partial`;
  return null;
}

export function deriveRatesDegraded(
  rates: RatesContext | null | undefined,
): string | null {
  if (!rates) return "Rates data unavailable";
  const entries = [rates.nominal, rates.real_proxy, rates.breakeven_proxy];
  const allNull = entries.every((e) => e.value == null && e.change_5d == null);
  if (allNull) return "All rates data missing";
  const missing = entries.filter((e) => e.value == null && e.change_5d == null);
  if (missing.length > 0)
    return `${missing.length} of ${entries.length} rate metrics missing`;
  return null;
}

export function deriveIndicatorDegraded(
  detail: StressComponentDetail,
): string | null {
  // An indicator that has an explanation but no numeric value at all
  const hasValue = detail.value != null
    || detail.change_5d != null
    || detail.spread_5d != null
    || detail.gap_5d != null
    || detail.inflow_count != null;
  if (!hasValue) return "Data unavailable";
  return null;
}
