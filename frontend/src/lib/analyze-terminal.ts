/**
 * P2-2 — runtime validation of a streamed analysis TERMINAL payload.
 *
 * A `_phase === "complete"` label alone is NOT proof of completion: a
 * syntactically valid but structurally invalid complete event must not
 * authorize successful EOF.  This is the single runtime validator shared by
 * the stream reader (`api.analyzeStream`) and the reducer
 * (`analysisStreamReducer`) so all three (reader, reducer, settlement) agree
 * by construction.
 *
 * Two valid terminal outcomes, matching the three backend-owned `complete`
 * payloads (routes/analyze.py + api._build_cached_response / _mock_failure_response):
 *   - success          — normal / cached completion: identity + a populated analysis.
 *   - handled_failure  — mock / analysis_failed completion: a valid terminal
 *                        transport event with an empty analysis and a reason;
 *                        it settles as a failure, never as a finished analysis.
 *
 * Checks are runtime type guards, never a TypeScript cast used as validation.
 * The lone `as AnalyzeResponse` runs only AFTER the shape is proven at runtime.
 * Field requirements are deliberately bounded to what distinguishes the three
 * real payloads and what the completed UI reads — over-strict validation would
 * mislabel a genuine success as incomplete.
 */
import type { AnalyzeResponse } from "./api";

export type TerminalOutcome = "success" | "handled_failure";

export interface ValidatedTerminal {
  readonly outcome: TerminalOutcome;
  readonly payload: AnalyzeResponse;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/**
 * Returns the validated terminal (with its outcome) when `payload` is a
 * structurally valid canonical `complete` event, or `null` when it is not.
 */
export function validateTerminalAnalyzePayload(payload: unknown): ValidatedTerminal | null {
  if (!isRecord(payload)) return null;
  if (payload._phase !== "complete") return null;

  // Identity / status fields present on every owned complete payload.
  if (typeof payload.headline !== "string" || payload.headline.length === 0) return null;
  if (typeof payload.is_mock !== "boolean") return null;
  if (!(typeof payload.event_date === "string" || payload.event_date === null)) return null;
  if (!isRecord(payload.market)) return null;

  // Handled terminal FAILURE — mock / analysis_failed.  Valid transport event,
  // empty analysis body, carries a human-readable reason.  Never a UI success.
  if (payload.analysis_failed === true || payload.is_mock === true) {
    if (typeof payload.failure_reason !== "string" || payload.failure_reason.length === 0) {
      return null;
    }
    return { outcome: "handled_failure", payload: payload as unknown as AnalyzeResponse };
  }

  // Successful completion — identity + a populated analysis the UI can render.
  // `build_analysis_dict` guarantees confidence (string) and beneficiaries /
  // losers (arrays) on every real analysis; an empty {} or malformed analysis
  // fails here.  Present-and-typed only — not non-empty — so a genuine result
  // is never mislabelled incomplete.
  if (typeof payload.stage !== "string") return null;
  if (typeof payload.persistence !== "string") return null;
  if (!isRecord(payload.analysis)) return null;
  const analysis = payload.analysis;
  if (typeof analysis.confidence !== "string") return null;
  if (!Array.isArray(analysis.beneficiaries)) return null;
  if (!Array.isArray(analysis.losers)) return null;

  return { outcome: "success", payload: payload as unknown as AnalyzeResponse };
}
