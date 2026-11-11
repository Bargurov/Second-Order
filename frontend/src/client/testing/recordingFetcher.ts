// TEST TRANSPORT ONLY. A fetch implementation for the contract's `userApi(fetcher)` that answers from a function the
// test supplies (usually built from the SYNTHETIC user-contract fixtures) and records every request. No module under
// src/client outside this folder imports it (frontend/tests/client-isolation.test.ts checks), so it is never bundled.
import type { Fetcher } from "../../contracts/user.ts";

export const TEST_TRANSPORT_MARK = "client-test-transport";

export interface Recorded { method: string; path: string; headers: Record<string, string>; body: unknown }
export type Answer = { status: number; body: unknown } | "no-reply";

export function recordingFetcher(answer: (request: Recorded) => Answer): { fetcher: Fetcher; requests: Recorded[] } {
  const requests: Recorded[] = [];
  const fetcher: Fetcher = async (input, init) => {
    const headers = Object.fromEntries(Object.entries((init.headers ?? {}) as Record<string, string>)
      .map(([key, value]) => [key.toLowerCase(), value]));
    const recorded: Recorded = { method: init.method ?? "GET", path: input, headers,
                                 body: typeof init.body === "string" ? JSON.parse(init.body) : null };
    requests.push(recorded);
    const reply = answer(recorded);
    if (reply === "no-reply") throw new TypeError(`${TEST_TRANSPORT_MARK}: no reply`);
    return new Response(JSON.stringify(reply.body), { status: reply.status,
                                                      headers: { "Content-Type": "application/json" } });
  };
  return { fetcher, requests };
}
