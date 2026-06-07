/**
 * Claim-language copy — single source of truth (F1).
 *
 * The product surfaces two different kinds of market evidence side by side,
 * and they must not be confused:
 *
 *   - Raw event-window returns (1d/5d/20d price move from the event date,
 *     un-adjusted) — a descriptive tape read, NOT inference.
 *   - The event-study readout (benchmark-adjusted abnormal return) — still
 *     descriptive point estimates at n=1, never a verdict.
 *
 * The old "Market Validation" header posed the raw returns as statistical
 * validation.  These constants reframe it honestly and bound the scored
 * validation_status_v2 verdict, so SharePage and AnalysisView stay in sync
 * and a later sweep (F2) can extend from one place.
 */

/** Header for the raw event-window return section (was "Market Validation"). */
export const MARKET_REACTION_LABEL = "Market reaction (raw)";

/** One-line sublabel under the raw-return header. */
export const MARKET_REACTION_SUBLABEL =
  "Event-window price move over 1d / 5d / 20d — raw, not benchmark-adjusted. " +
  "See the event-study readout for abnormal return.";

/**
 * Scope caveat appended under the scored validation_status_v2 verdict.
 * Additive only — it bounds the "Validated / Contradicted" label without
 * changing the score, the data contract, or the project-wide taxonomy.
 */
export const VALIDATION_V2_SCOPE_CAVEAT =
  "Tape-direction agreement on scored directional names — descriptive, " +
  "not benchmark-adjusted event-study inference.";

/**
 * Explicit claim-boundary line shown next to the scored validation verdict
 * (R2A).  States what the verdict does NOT assert, so a reader sees the
 * boundary without a guided tour.  Kept banned-word-clean (no proof / proven /
 * confirmed / significant / alpha) and free of any forward / permanent-forecast
 * framing — "significance" here is an explicit non-claim, not an assertion.
 */
export const VALIDATION_V2_NOT_CLAIMED =
  "Not claimed: statistical significance, benchmark-adjusted inference, or a " +
  "permanent asset forecast.";
