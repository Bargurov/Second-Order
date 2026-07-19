/**
 * P2-2 — transport-completeness contract for the real SSE reader
 * (``api.analyzeStream`` in ``src/lib/api.ts``).
 *
 * A streamed analysis becomes complete ONLY after a STRUCTURALLY VALID
 * canonical terminal event (`_phase === "complete"`) is validated and
 * successfully applied by the consumer.  Proven here against the REAL reader
 * (not a copy):
 *   - a valid success / handled-failure `complete` resolves;
 *   - clean/abnormal EOF before a valid terminal rejects (incomplete);
 *   - a phase-only or structurally invalid `complete` rejects;
 *   - a consumer (`onEvent`) that throws on `complete` rejects — distinct from
 *     a malformed-JSON frame, which is skipped fail-closed;
 *   - intentional cancellation resolves, never rejects;
 *   - every path issues exactly one fetch (no automatic retry).
 *
 * No real network: ``fetch`` is stubbed to return a Web ``ReadableStream``.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { api } from "../api";

const enc = new TextEncoder();

function streamFrom(chunks: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const s of chunks) controller.enqueue(enc.encode(s));
      controller.close();
    },
  });
}
function stubFetch(chunks: string[], ok = true): ReturnType<typeof vi.fn> {
  const f = vi.fn(async () => ({ ok, body: streamFrom(chunks), text: async () => "" }));
  vi.stubGlobal("fetch", f);
  return f;
}
function frame(phase: string, extra: Record<string, unknown> = {}): string {
  return `data: ${JSON.stringify({ _phase: phase, ...extra })}\n\n`;
}

const VALID_ANALYSIS = {
  what_changed: "x", mechanism_summary: "m",
  beneficiaries: ["A"], losers: ["B"],
  beneficiary_tickers: ["AAPL"], loser_tickers: ["MSFT"],
  assets_to_watch: ["AAPL"], confidence: "medium",
};
const MARKET = { note: "", details: {}, tickers: [] };
const SUCCESS = {
  headline: "h", stage: "initial", persistence: "short",
  analysis: VALID_ANALYSIS, market: MARKET, is_mock: false, event_date: "2026-01-01",
};
const FAILURE = {
  headline: "h", stage: "", persistence: "", analysis: {}, market: MARKET,
  is_mock: true, analysis_failed: true, failure_reason: "overloaded", event_date: "2026-01-01",
};

const CLASSIFY = frame("classify", { stage: "initial", persistence: "short" });
const ANALYSIS = frame("analysis", { analysis: VALID_ANALYSIS, is_mock: false });
const COMPLETE = frame("complete", SUCCESS);
const MOCK_COMPLETE = frame("complete", FAILURE);

afterEach(() => vi.unstubAllGlobals());

describe("analyzeStream — valid terminals resolve", () => {
  it("resolves and delivers every event on a valid success stream", async () => {
    stubFetch([CLASSIFY, ANALYSIS, COMPLETE]);
    const seen: string[] = [];
    await expect(api.analyzeStream({ headline: "h" }, (s) => seen.push(s))).resolves.toBeUndefined();
    expect(seen).toEqual(["classify", "analysis", "complete"]);
  });
  it("resolves for a valid handled-failure (mock) completion", async () => {
    stubFetch([CLASSIFY, MOCK_COMPLETE]);
    const seen: string[] = [];
    await expect(api.analyzeStream({ headline: "h" }, (s) => seen.push(s))).resolves.toBeUndefined();
    expect(seen).toContain("complete");
  });
  it("resolves when the terminal frame is split across chunks but fully received", async () => {
    const mid = Math.floor(COMPLETE.length / 2);
    stubFetch([CLASSIFY, COMPLETE.slice(0, mid), COMPLETE.slice(mid)]);
    await expect(api.analyzeStream({ headline: "h" }, () => {})).resolves.toBeUndefined();
  });
  it("skips a malformed non-terminal frame yet still completes on a valid terminal", async () => {
    // Malformed JSON is fail-closed SKIP, not fatal: a later valid complete wins.
    stubFetch([CLASSIFY, "data: {not json}\n\n", COMPLETE]);
    await expect(api.analyzeStream({ headline: "h" }, () => {})).resolves.toBeUndefined();
  });
});

describe("analyzeStream — EOF before a valid terminal rejects", () => {
  it("REJECTS on immediate EOF (headers then nothing)", async () => {
    stubFetch([]);
    await expect(api.analyzeStream({ headline: "h" }, () => {})).rejects.toThrow();
  });
  it("REJECTS on partial events then EOF (no complete)", async () => {
    stubFetch([CLASSIFY, ANALYSIS]);
    const seen: string[] = [];
    await expect(api.analyzeStream({ headline: "h" }, (s) => seen.push(s))).rejects.toThrow();
    expect(seen).toEqual(["classify", "analysis"]);
  });
  it("REJECTS when the terminal frame is split and TRUNCATED at EOF", async () => {
    stubFetch([CLASSIFY, ANALYSIS, 'data: {"_phase":"comp']);
    await expect(api.analyzeStream({ headline: "h" }, () => {})).rejects.toThrow();
  });
  it("REJECTS (fail closed) on a malformed JSON event followed by EOF", async () => {
    stubFetch([CLASSIFY, "data: {not valid json}\n\n"]);
    await expect(api.analyzeStream({ headline: "h" }, () => {})).rejects.toThrow();
  });
});

describe("analyzeStream — structurally invalid terminal rejects", () => {
  const rejectsAndNoComplete = async (chunks: string[]) => {
    stubFetch(chunks);
    const seen: string[] = [];
    await expect(api.analyzeStream({ headline: "h" }, (s) => seen.push(s))).rejects.toThrow();
    expect(seen).not.toContain("complete"); // terminal never recorded/delivered
  };

  it("REJECTS a phase-only complete payload", async () => {
    await rejectsAndNoComplete([CLASSIFY, frame("complete")]);
  });
  it("REJECTS a success complete missing analysis", async () => {
    const { analysis, ...noAnalysis } = SUCCESS; void analysis;
    await rejectsAndNoComplete([CLASSIFY, frame("complete", noAnalysis)]);
  });
  it("REJECTS a success complete with malformed analysis", async () => {
    await rejectsAndNoComplete([CLASSIFY, frame("complete", { ...SUCCESS, analysis: [] })]);
  });
  it("REJECTS a success complete missing identity/status fields", async () => {
    const { headline, ...noHeadline } = SUCCESS; void headline;
    await rejectsAndNoComplete([CLASSIFY, frame("complete", noHeadline)]);
  });
  it("REJECTS a handled-failure complete missing failure_reason", async () => {
    const { failure_reason, ...noReason } = FAILURE; void failure_reason;
    await rejectsAndNoComplete([CLASSIFY, frame("complete", noReason)]);
  });
  it("REJECTS a complete with wrong field types", async () => {
    await rejectsAndNoComplete([CLASSIFY, frame("complete", { ...SUCCESS, is_mock: "false" })]);
  });
});

describe("analyzeStream — consumer failure and safety", () => {
  it("REJECTS when the complete onEvent callback throws (not swallowed as malformed)", async () => {
    const f = stubFetch([CLASSIFY, COMPLETE]);
    const onEvent = (stage: string) => { if (stage === "complete") throw new Error("consumer boom"); };
    await expect(api.analyzeStream({ headline: "h" }, onEvent)).rejects.toThrow();
    expect(f).toHaveBeenCalledTimes(1);
  });
  it("issues EXACTLY ONE fetch on a truncated stream (no automatic retry)", async () => {
    const f = stubFetch([CLASSIFY, ANALYSIS]);
    await expect(api.analyzeStream({ headline: "h" }, () => {})).rejects.toThrow();
    expect(f).toHaveBeenCalledTimes(1);
  });
  it("issues EXACTLY ONE fetch when the terminal payload is invalid", async () => {
    const f = stubFetch([CLASSIFY, frame("complete")]);
    await expect(api.analyzeStream({ headline: "h" }, () => {})).rejects.toThrow();
    expect(f).toHaveBeenCalledTimes(1);
  });
  it("does NOT reject on intentional user cancellation (aborted signal)", async () => {
    const ctrl = new AbortController();
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      body: new ReadableStream<Uint8Array>({
        start(controller) { controller.enqueue(enc.encode(CLASSIFY)); /* left open */ },
      }),
      text: async () => "",
    })));
    const promise = api.analyzeStream({ headline: "h" }, () => ctrl.abort(), ctrl.signal);
    await expect(promise).resolves.toBeUndefined();
  });
});
