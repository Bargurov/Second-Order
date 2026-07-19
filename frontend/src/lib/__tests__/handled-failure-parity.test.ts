/**
 * P2-2 handled-failure PARITY — cross-layer regression.
 *
 * ``fixtures/handled-failure-complete.json`` is the EXACT ``complete`` frame the
 * REAL backend generator emits on a handled failure.  Its fidelity is proven on
 * the backend side by
 * ``tests/test_api.py::TestAnalyzeStream::test_stream_handled_failure_matches_frontend_fixture``,
 * which deep-equals the live generator's output against THIS SAME file — so this
 * is not a hand-reconstructed approximation.  Here we drive that one real
 * payload through every frontend layer, proving the two sides agree by
 * construction:
 *
 *   real backend handled-failure `complete`
 *     → validateTerminalAnalyzePayload  = handled_failure
 *     → analyzeStream resolves (valid terminal transport), onEvent applied once
 *     → reducer → failure state (idle, no analysis body, error = real reason)
 *     → rowSettlementFor("handled_failure") = "failed"  (⇒ onAnalysisFailed)
 *     → no completed UI / export (phase !== "complete")
 *
 * No real network: ``fetch`` is stubbed to return a Web ``ReadableStream``.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { api, type AnalyzeResponse } from "../api";
import { validateTerminalAnalyzePayload } from "../analyze-terminal";
import {
  analysisStreamReducer,
  INITIAL_ANALYSIS_STREAM_STATE,
  rowSettlementFor,
} from "../analysis-stream";
import REAL_HANDLED_FAILURE from "./fixtures/handled-failure-complete.json";

const enc = new TextEncoder();
const REAL_REASON = REAL_HANDLED_FAILURE.failure_reason; // "model unavailable"

function streamFrom(chunks: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(c) {
      for (const s of chunks) c.enqueue(enc.encode(s));
      c.close();
    },
  });
}
function stubFetch(chunks: string[]): ReturnType<typeof vi.fn> {
  const f = vi.fn(async () => ({ ok: true, body: streamFrom(chunks), text: async () => "" }));
  vi.stubGlobal("fetch", f);
  return f;
}

const CLASSIFY = `data: ${JSON.stringify({ _phase: "classify", stage: "", persistence: "" })}\n\n`;
const REAL_COMPLETE = `data: ${JSON.stringify(REAL_HANDLED_FAILURE)}\n\n`;
const asEvent = (data: unknown) =>
  ({ type: "event", stage: "complete", data: data as AnalyzeResponse } as const);

afterEach(() => vi.unstubAllGlobals());

describe("handled-failure parity — the real backend payload across all layers", () => {
  it("fixture IS a handled failure carrying a non-empty reason", () => {
    expect(REAL_HANDLED_FAILURE._phase).toBe("complete");
    expect(REAL_HANDLED_FAILURE.analysis_failed).toBe(true);
    expect(REAL_HANDLED_FAILURE.is_mock).toBe(true);
    expect(typeof REAL_REASON).toBe("string");
    expect(REAL_REASON.length).toBeGreaterThan(0);
  });

  it("validator classifies the real payload as handled_failure", () => {
    expect(validateTerminalAnalyzePayload(REAL_HANDLED_FAILURE)?.outcome).toBe("handled_failure");
  });

  it("analyzeStream resolves it as a valid terminal and applies onEvent exactly once", async () => {
    const f = stubFetch([CLASSIFY, REAL_COMPLETE]);
    const completes: Record<string, unknown>[] = [];
    await expect(
      api.analyzeStream({ headline: "h" }, (stage, data) => {
        if (stage === "complete") completes.push(data);
      }),
    ).resolves.toBeUndefined();
    expect(f).toHaveBeenCalledTimes(1);        // exactly one fetch, no auto-retry
    expect(completes).toHaveLength(1);          // terminal applied exactly once
    expect(completes[0]).toMatchObject({ analysis_failed: true, failure_reason: REAL_REASON });
  });

  it("reducer enters the failure state (idle, no analysis body) with the real reason", () => {
    // Faithful flow: submit → classify → the real handled-failure complete.
    const s = [
      { type: "submit", headline: "h" } as const,
      { type: "event", stage: "classify", data: { stage: "", persistence: "" } } as const,
      asEvent(REAL_HANDLED_FAILURE),
    ].reduce(analysisStreamReducer, INITIAL_ANALYSIS_STREAM_STATE);
    expect(s.phase).toBe("idle");                                   // NOT "complete"
    expect(s.error).toBe(REAL_REASON);                              // real reason surfaced
    expect((s.result as AnalyzeResponse | null)?.analysis).toBeUndefined(); // no completed body
  });

  it("settles the Inbox row as a failure (⇒ onAnalysisFailed), never success", () => {
    const outcome = validateTerminalAnalyzePayload(REAL_HANDLED_FAILURE)!.outcome;
    expect(rowSettlementFor(outcome)).toBe("failed");
    expect(rowSettlementFor("success")).toBe("succeeded"); // contrast: only success settles succeeded
  });

  it("preserves rejection when the SAME real shape is emptied of its reason (item 8)", () => {
    const emptied = { ...REAL_HANDLED_FAILURE, failure_reason: "" };
    expect(validateTerminalAnalyzePayload(emptied)).toBeNull();
    const s = analysisStreamReducer(INITIAL_ANALYSIS_STREAM_STATE, asEvent(emptied));
    expect(s.phase).toBe("idle");        // invalid terminal → never completed UI
    expect(s.result).toBeNull();
  });
});
