/**
 * A1-4R local-basis-unavailable PARITY — cross-layer regression.
 *
 * ``fixtures/durable-lookup-basis-unavailable-complete.json`` is the EXACT
 * ``complete`` frame the REAL backend generator emits when the durable request
 * basis cannot be reconstructed from local data.  Its fidelity is proven on the
 * backend side by
 * ``tests/test_api.py::TestAnalyzeStream::test_stream_basis_unavailable_matches_frontend_fixture``,
 * which deep-equals the live generator's output against THIS SAME file — so
 * this is not a hand-reconstructed approximation.
 *
 * What this pins: the state is a VALID TERMINAL, never a truncated stream.  The
 * frontend needs no new display branch — the payload is shaped as a handled
 * terminal failure, so the existing validator/reader/reducer/settlement path
 * carries it end to end and the UI never shows a half-applied analysis.
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
import REAL_BASIS_UNAVAILABLE from "./fixtures/durable-lookup-basis-unavailable-complete.json";

const enc = new TextEncoder();
const REAL_REASON = REAL_BASIS_UNAVAILABLE.failure_reason;

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

const REAL_COMPLETE = `data: ${JSON.stringify(REAL_BASIS_UNAVAILABLE)}\n\n`;
const asEvent = (data: unknown) =>
  ({ type: "event", stage: "complete", data: data as AnalyzeResponse } as const);

afterEach(() => vi.unstubAllGlobals());

describe("basis-unavailable parity — the real backend payload across all layers", () => {
  it("fixture states the unavailable outcome, not a cache miss", () => {
    expect(REAL_BASIS_UNAVAILABLE._phase).toBe("complete");
    expect(REAL_BASIS_UNAVAILABLE.status).toBe("durable_lookup_basis_unavailable");
    expect(REAL_BASIS_UNAVAILABLE.status).not.toBe("paid_confirmation_required");
    expect(typeof REAL_REASON).toBe("string");
    expect(REAL_REASON.length).toBeGreaterThan(0);
  });

  it("declares that nothing external was contacted", () => {
    expect(REAL_BASIS_UNAVAILABLE.provider_called).toBe(false);
    expect(REAL_BASIS_UNAVAILABLE.is_mock).toBe(false);
  });

  it("carries no analysis body — the UI can never render a partial readout", () => {
    expect(REAL_BASIS_UNAVAILABLE.analysis).toEqual({});
    expect(REAL_BASIS_UNAVAILABLE.market.tickers).toEqual([]);
  });

  it("discloses no path, cache internal, credential or raw exception text", () => {
    const blob = JSON.stringify(REAL_BASIS_UNAVAILABLE).toLowerCase();
    for (const leak of [".db", "sqlite", "traceback", "c:\\", "/users/", "api_key", "token"]) {
      expect(blob).not.toContain(leak);
    }
  });

  it("validator accepts it as a terminal, classified as a handled failure", () => {
    expect(validateTerminalAnalyzePayload(REAL_BASIS_UNAVAILABLE)?.outcome).toBe(
      "handled_failure",
    );
  });

  it("analyzeStream resolves it as a valid terminal — never a truncated stream", async () => {
    const f = stubFetch([REAL_COMPLETE]);
    const completes: Record<string, unknown>[] = [];
    await expect(
      api.analyzeStream({ headline: "h" }, (stage, data) => {
        if (stage === "complete") completes.push(data);
      }),
    ).resolves.toBeUndefined();
    expect(f).toHaveBeenCalledTimes(1); // exactly one fetch, no automatic retry
    expect(completes).toHaveLength(1);
    expect(completes[0]).toMatchObject({
      status: "durable_lookup_basis_unavailable",
      provider_called: false,
    });
  });

  it("reducer ends idle with the real reason and no completed analysis body", () => {
    const s = [
      { type: "submit", headline: "h" } as const,
      asEvent(REAL_BASIS_UNAVAILABLE),
    ].reduce(analysisStreamReducer, INITIAL_ANALYSIS_STREAM_STATE);
    expect(s.phase).toBe("idle");
    expect(s.error).toBe(REAL_REASON);
    expect((s.result as AnalyzeResponse | null)?.analysis).toBeUndefined();
  });

  it("settles the Inbox row as a failure, never as a success", () => {
    const outcome = validateTerminalAnalyzePayload(REAL_BASIS_UNAVAILABLE)!.outcome;
    expect(rowSettlementFor(outcome)).toBe("failed");
  });

  it("preserves rejection when the SAME real shape is emptied of its reason", () => {
    const emptied = { ...REAL_BASIS_UNAVAILABLE, failure_reason: "" };
    expect(validateTerminalAnalyzePayload(emptied)).toBeNull();
    const s = analysisStreamReducer(INITIAL_ANALYSIS_STREAM_STATE, asEvent(emptied));
    expect(s.phase).toBe("idle");
    expect(s.result).toBeNull();
  });
});
