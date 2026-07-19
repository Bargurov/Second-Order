/**
 * P2-2 — explicit state machine for a streamed analysis.
 *
 * This is the production source of truth for the Analyze view's stream state
 * (``AnalysisView`` consumes it via ``useReducer``).  It exists so the
 * completeness contract is testable in isolation: a streamed analysis reaches
 * ``complete`` ONLY through the canonical terminal-success event; a transport
 * that ends before that event (``incomplete``) drops the partial so it can
 * never be read, exported, or restored as a finished analysis.
 *
 * States (phase): idle → classify → analysis → market → complete, plus the
 * two off-ramps that never present as complete:
 *   - handled terminal FAILURE (mock / analysis_failed complete)  → idle + error
 *   - INCOMPLETE transport (EOF before the terminal event)         → idle + error, partial dropped
 *
 * Intentional user cancellation is handled by the caller (it simply stops
 * dispatching); it is never modelled as failure or success here.
 */
import type { AnalyzeResponse } from "./api";
import { validateTerminalAnalyzePayload } from "./analyze-terminal";

export type AnalysisPhase =
  | "idle"
  | "classify"
  | "analysis"
  | "market"
  | "complete";

export interface AnalysisStreamState {
  phase: AnalysisPhase;
  result: AnalyzeResponse | null;
  error: string | null;
}

export const INITIAL_ANALYSIS_STREAM_STATE: AnalysisStreamState = {
  phase: "idle",
  result: null,
  error: null,
};

export type AnalysisStreamAction =
  /** A new submission begins — reset to the classify phase. */
  | { type: "submit"; headline: string }
  /** A parsed SSE event (classify / analysis / complete). */
  | { type: "event"; stage: string; data: Record<string, unknown> }
  /** The stream ended before the terminal-success event (truncated / errored). */
  | { type: "incomplete"; message: string }
  /** Market-only refresh replaced the market block on an existing result. */
  | { type: "marketRefreshed"; market: AnalyzeResponse["market"] };

const DEFAULT_FAILURE = "Model unavailable — try again in a moment.";
const INVALID_TERMINAL = "Analysis returned an invalid result.";

export function analysisStreamReducer(
  state: AnalysisStreamState,
  action: AnalysisStreamAction,
): AnalysisStreamState {
  switch (action.type) {
    case "submit":
      return {
        phase: "classify",
        result: { headline: action.headline } as AnalyzeResponse,
        error: null,
      };

    case "event": {
      const { stage, data } = action;
      const prev = state.result ?? ({} as AnalyzeResponse);

      if (stage === "classify") {
        return {
          phase: "analysis",
          error: state.error,
          result: {
            ...prev,
            stage: data.stage as string,
            persistence: data.persistence as string,
          } as AnalyzeResponse,
        };
      }

      if (stage === "analysis") {
        return {
          phase: "market",
          error: state.error,
          result: {
            ...prev,
            analysis: data.analysis as AnalyzeResponse["analysis"],
            is_mock: data.is_mock as boolean,
          } as AnalyzeResponse,
        };
      }

      if (stage === "complete") {
        // Independently validate the terminal payload — the reducer never
        // trusts arbitrary `_phase:"complete"` data (the reader is the primary
        // gate; this guards other callers and future code paths).
        const validated = validateTerminalAnalyzePayload(data);
        if (!validated) {
          // Invalid terminal → never a completed UI; drop any partial.
          return { phase: "idle", result: null, error: INVALID_TERMINAL };
        }
        if (validated.outcome === "handled_failure") {
          // Handled terminal FAILURE — the stream completed, but this is not a
          // finished analysis.  Keep the identity chips (a mock/failed
          // ``complete`` carries no analysis body to render), surface the
          // reason, and land in idle so completed-only UI never appears.
          return {
            phase: "idle",
            result: state.result,
            error: validated.payload.failure_reason || DEFAULT_FAILURE,
          };
        }
        // The one true success path.
        return { phase: "complete", result: validated.payload, error: null };
      }

      return state;
    }

    case "incomplete":
      // Transport ended before the terminal-success event.  Drop the partial
      // entirely so nothing downstream can read/export/restore it as finished.
      return { phase: "idle", result: null, error: action.message };

    case "marketRefreshed":
      return state.result
        ? { ...state, result: { ...state.result, market: action.market } }
        : state;
  }
}

// ---------------------------------------------------------------------------
// Inbox row settlement — which failure/success callback a terminal outcome
// should invoke.  Extracted as the pure source of truth so the "exactly once"
// contract is testable without a DOM: a truncated / invalid stream settles the
// submitted headline as a failure (retryable), a success settles it as
// succeeded, and an intentional cancellation settles neither.
// ---------------------------------------------------------------------------

export type StreamOutcome = "success" | "handled_failure" | "incomplete" | "cancelled";
export type RowSettlement = "succeeded" | "failed" | "none";

export function rowSettlementFor(outcome: StreamOutcome): RowSettlement {
  switch (outcome) {
    case "success":
      return "succeeded";
    case "handled_failure":
    case "incomplete":
      return "failed";
    case "cancelled":
      return "none";
  }
}
