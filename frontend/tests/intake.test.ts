import assert from "node:assert/strict";
import test from "node:test";
import {
  INTAKE_FLOW_VERSION, dispatchMock, dispatchPaid, fetchAttemptState, fetchCaptures, publishRecorded, reopenCapture,
} from "../src/api.ts";
import {
  UTC_OFFSETS, intakePayload, mayApprove, offsetLabel, outcomeText, publishedAt, requestPublishedAt,
  type AttemptState, type IntakeFields,
} from "../src/intake.ts";

const state = (name: AttemptState["state"]): AttemptState => ({
  flow_version: INTAKE_FLOW_VERSION, capture_id: "20261005T093000000000Z-0123456789ab", state: name, files: [],
  detail: "", mode: null, sent: false, provider_called: false,
});

async function withFetch<T>(fake: typeof fetch, run: () => Promise<T>): Promise<T> {
  const original = globalThis.fetch;
  globalThis.fetch = fake;
  try {
    return await run();
  } finally {
    globalThis.fetch = original;
  }
}

const reply = (status: number, body: unknown, sent: { url: string; init?: RequestInit }[] = []) =>
  (async (url: string, init?: RequestInit) => {
    sent.push({ url, init });
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  }) as typeof fetch;

const FIELDS: IntakeFields = {
  headline: "Headline", sourceUrl: "https://example.com", publishedDate: "2026-10-04", publishedTime: "14:30",
  publishedOffset: "-04:00", sourceText: "Published text",
};

/** The zone this process started in. Deleting TZ does not make Node resolve its zone again, so it is set back by name. */
const STARTING_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;
const STARTING_TZ = process.env.TZ;
const ZONES = ["America/Los_Angeles", "America/New_York", "Asia/Jerusalem", "Asia/Tokyo", "Pacific/Kiritimati",
               "Pacific/Pago_Pago", "UTC"];

/** Runs `body` with this process's time zone set to `zone` (Node applies a set TZ immediately), then restores both
 * the zone and the TZ variable. */
function inZone<T>(zone: string, body: () => T): T {
  const original = process.env.TZ;
  process.env.TZ = zone;
  try {
    return body();
  } finally {
    process.env.TZ = original ?? STARTING_ZONE;  // Setting TZ makes Node resolve the zone again.
    if (original === undefined) delete process.env.TZ;  // Deleting does not, so the starting zone stays in force.
  }
}

/** Later tests in this file must run in the zone the process started in, with TZ as it was. */
function assertRestored(): void {
  assert.equal(Intl.DateTimeFormat().resolvedOptions().timeZone, STARTING_ZONE);
  assert.equal(process.env.TZ, STARTING_TZ);
}

test("the intake form normalizes metadata but preserves source text and the supplied time exactly", () => {
  const source = "  Published text begins with spaces.\nSecond line.  ";
  const result = intakePayload({ ...FIELDS, headline: "  Synthetic event headline  ",
                                 sourceUrl: " https://example.com/statement ", sourceText: source });
  assert.equal(result.problem, null);
  assert.deepEqual(result.payload, {
    headline: "Synthetic event headline",
    source_url: "https://example.com/statement",
    published_at: "2026-10-04T14:30:00-04:00",
    source_text: source,
  });
});

test("the same explicit time gives the same payload under any time zone of this computer", () => {
  // The defect being prevented: a bare local date-time read by Date lands on a different instant in each zone.
  const local = ZONES.map((zone) => inZone(zone, () => new Date("2026-10-04T14:30").toISOString()));
  assert.equal(new Set(local).size, ZONES.length, "the time zone override must take effect for this test to mean anything");
  for (const zone of ZONES) {
    assert.equal(inZone(zone, () => intakePayload(FIELDS).payload?.published_at), "2026-10-04T14:30:00-04:00", zone);
  }
  assertRestored();
});

test("a publication time is joined from date, time and an explicit offset, never rolled over", () => {
  const accepted: [string, string, string, string][] = [
    ["2026-10-04", "14:30", "-04:00", "2026-10-04T14:30:00-04:00"],
    ["2026-10-04", "14:30:05", "+05:30", "2026-10-04T14:30:05+05:30"],
    ["2024-02-29", "23:59:59", "+00:00", "2024-02-29T23:59:59+00:00"],
    ["2000-02-29", "00:00", "+14:00", "2000-02-29T00:00:00+14:00"],
    ["2026-12-31", "22:30", "-12:00", "2026-12-31T22:30:00-12:00"],
    // Wall-clock times that do not exist in New York (8 Mar 2026) or Jerusalem (27 Mar 2026), where clocks jumped
    // from 02:00 to 03:00. With an explicit offset they are valid instants and must be kept exactly as given.
    ["2026-03-08", "02:30", "-05:00", "2026-03-08T02:30:00-05:00"],
    ["2026-03-27", "02:30", "+02:00", "2026-03-27T02:30:00+02:00"],
  ];
  for (const zone of ZONES) {
    inZone(zone, () => {
      for (const [date, time, offset, expected] of accepted) {
        assert.deepEqual(publishedAt(date, time, offset), { value: expected }, `${zone}: ${date} ${time} ${offset}`);
      }
    });
  }
  assertRestored();
  const refused: [string, string, string, RegExp][] = [
    ["2026-02-29", "12:00", "+00:00", /not a calendar date/],  // 2026 is not a leap year.
    ["1900-02-29", "12:00", "+00:00", /not a calendar date/],  // Centuries are leap years only every 400 years.
    ["2026-02-30", "12:00", "+00:00", /not a calendar date/],
    ["2026-04-31", "12:00", "+00:00", /not a calendar date/],
    ["2026-13-01", "12:00", "+00:00", /not a calendar date/],
    ["2026-00-10", "12:00", "+00:00", /not a calendar date/],
    ["2026-10-4", "12:00", "+00:00", /Enter the publication date/],
    ["", "12:00", "+00:00", /Enter the publication date/],
    ["2026-10-04", "24:00", "+00:00", /not a time of day/],
    ["2026-10-04", "23:60", "+00:00", /not a time of day/],
    ["2026-10-04", "23:59:60", "+00:00", /not a time of day/],
    ["2026-10-04", "7:05", "+00:00", /Enter the publication time of day/],
    ["2026-10-04", "", "+00:00", /Enter the publication time of day/],
    ["2026-10-04", "12:00", "", /Choose the publication's UTC offset/],
    ["2026-10-04", "12:00", "-00:00", /not an accepted UTC offset/],
    ["2026-10-04", "12:00", "+15:00", /not an accepted UTC offset/],
    ["2026-10-04", "12:00", "-12:15", /not an accepted UTC offset/],
    ["2026-10-04", "12:00", "+05:07", /not an accepted UTC offset/],
    ["2026-10-04", "12:00", "+0400", /not an accepted UTC offset/],
    ["2026-10-04", "12:00", "Z", /not an accepted UTC offset/],
  ];
  for (const [date, time, offset, message] of refused) {
    const result = publishedAt(date, time, offset);
    assert.ok("problem" in result && message.test(result.problem), `${date} ${time} ${offset}: ${JSON.stringify(result)}`);
  }
});

test("the offered offsets run from -12:00 to +14:00 in 15-minute steps, with UTC labelled", () => {
  assert.equal(UTC_OFFSETS.length, 105);
  assert.deepEqual([UTC_OFFSETS[0], UTC_OFFSETS.at(-1)], ["-12:00", "+14:00"]);
  for (const offset of ["-09:30", "-04:00", "+00:00", "+05:30", "+05:45", "+08:45", "+12:45"]) {
    assert.ok(UTC_OFFSETS.includes(offset), offset);
  }
  assert.ok(!UTC_OFFSETS.includes("-00:00"));
  assert.equal(offsetLabel("+00:00"), "UTC+00:00 (UTC)");
  assert.equal(offsetLabel("-04:00"), "UTC−04:00");
});

test("the instant shown for approval is read from the saved request itself", () => {
  const content = "Instructions.\n\nHeadline: H\nSource URL: https://example.com\nPublished at (UTC): 2026-10-04T18:00:00Z\n\n" +
    "<source_text>\nPublished at (UTC): 1999-01-01T00:00:00Z appears in the text, after the field.\n</source_text>";
  assert.equal(requestPublishedAt({ messages: [{ role: "user", content }] }), "2026-10-04T18:00:00Z");
  assert.equal(requestPublishedAt({ messages: [{ role: "user", content: [{ type: "text", text: content }] }] }),
               "2026-10-04T18:00:00Z");
  assert.equal(requestPublishedAt({ messages: [{ role: "user", content: "No publication line." }] }), null);
  assert.equal(requestPublishedAt({ messages: [] }), null);
});

test("the intake form refuses incomplete or non-http input before submission", () => {
  for (const [field, value, message] of [
    ["headline", "", "Enter a headline."],
    ["sourceUrl", "file:///tmp/source", "The source must be an http or https URL."],
    ["publishedDate", "", "Enter the publication date."],
    ["publishedOffset", "", "Choose the publication's UTC offset; this computer's time zone is never used."],
    ["sourceText", "  ", "Paste the published text."],
  ] as const) {
    const result = intakePayload({ ...FIELDS, [field]: value });
    assert.equal(result.payload, null);
    assert.equal(result.problem, message);
  }
});

test("approving again is allowed only before any dispatch or when no attempt is recorded", () => {
  assert.equal(mayApprove(null), true);
  assert.equal(mayApprove(state("none")), true);
  for (const name of ["incomplete", "awaiting_publication", "ready", "invalid"] as const) {
    assert.equal(mayApprove(state(name)), false, name);
  }
  assert.equal(mayApprove("unreadable"), false);
});

test("a dispatch whose outcome is unknown is unconfirmed, never a plain failure", async () => {
  const lost = (async () => { throw new TypeError("network"); }) as typeof fetch;
  assert.equal((await withFetch(lost, () => dispatchMock("c", "h", "draft"))).state, "unconfirmed");
  const serverError = reply(500, { detail: "The mock response was recorded, but publishing it for review failed" });
  const failed = await withFetch(serverError, () => dispatchMock("c", "h", "draft"));
  assert.deepEqual(failed, { state: "unconfirmed",
                             message: "The mock response was recorded, but publishing it for review failed" });
  const refused = await withFetch(reply(409, { detail: "This capture already has an attempt" }),
                                  () => dispatchMock("c", "h", "draft"));
  assert.equal(refused.state, "failed");  // A 4xx is a refusal made before anything was written.
});

test("recovery publishes the recorded response with one explicit local POST", async () => {
  const sent: { url: string; init?: RequestInit }[] = [];
  const result = { flow_version: INTAKE_FLOW_VERSION, status: "prepared_for_human_review", draft_id: "d",
                   outcome: "draft", recovered: true };
  const published = await withFetch(reply(201, result, sent), () => publishRecorded("capture id", "a".repeat(64)));
  assert.equal(published.state, "saved");
  assert.equal(sent.length, 1);
  assert.equal(sent[0].url, "/api/intake/capture%20id/publish");
  assert.equal(sent[0].init?.method, "POST");
  assert.deepEqual(JSON.parse(String(sent[0].init?.body)), { request_sha256: "a".repeat(64) });
  assert.equal((sent[0].init?.headers as Record<string, string>)["X-Second-Order-Intake"], "1");
});

test("the attempt state is read with a GET and verified before it is trusted", async () => {
  const sent: { url: string; init?: RequestInit }[] = [];
  const read = await withFetch(reply(200, state("awaiting_publication"), sent), () => fetchAttemptState("c"));
  assert.deepEqual(read, { state: "ready", data: state("awaiting_publication") });
  assert.equal(sent[0].init?.method, undefined);  // A plain GET.
  const foreign = await withFetch(reply(200, { ...state("ready"), flow_version: "other" }), () => fetchAttemptState("c"));
  assert.equal(foreign.state, "error");
  const unreachable = await withFetch((async () => { throw new TypeError("network"); }) as typeof fetch,
                                      () => fetchAttemptState("c"));
  assert.equal(unreachable.state, "error");
});

test("the paid action is one explicit POST that repeats the hash and the estimate the preview showed", async () => {
  const sent: { url: string; init?: RequestInit }[] = [];
  const result = { flow_version: INTAKE_FLOW_VERSION, status: "prepared_for_human_review", draft_id: "d",
                   outcome: "draft", recorded_outcome: "draft", mode: "paid", provider_called: true };
  const paid = await withFetch(reply(201, result, sent), () => dispatchPaid("capture id", "a".repeat(64), 0.1688));
  assert.equal(paid.state, "saved");
  assert.equal(sent.length, 1);
  assert.equal(sent[0].url, "/api/intake/capture%20id/paid-drafts");
  assert.equal(sent[0].init?.method, "POST");
  assert.deepEqual(JSON.parse(String(sent[0].init?.body)),
                   { request_sha256: "a".repeat(64), approve_paid_request: true, estimated_max_usd: 0.1688 });
  assert.equal((sent[0].init?.headers as Record<string, string>)["X-Second-Order-Intake"], "1");
  const lost = await withFetch((async () => { throw new TypeError("network"); }) as typeof fetch,
                               () => dispatchPaid("c", "h", 0.1));
  assert.equal(lost.state, "unconfirmed");  // A lost reply is never a plain failure: it may have been sent.
  const serverError = await withFetch(reply(500, { detail: "The paid attempt was interrupted" }),
                                      () => dispatchPaid("c", "h", 0.1));
  assert.equal(serverError.state, "unconfirmed");
  const refused = await withFetch(reply(409, { detail: "Paid sending is not enabled on this server" }),
                                  () => dispatchPaid("c", "h", 0.1));
  assert.equal(refused.state, "failed");
});

test("outcome wording never claims more than the records show, and only paid requests can be billed", () => {
  assert.match(outcomeText("transport error", "paid"), /outcome is unknown: the provider may have received and billed/);
  assert.equal(outcomeText("draft", "paid"), "The model proposed a draft.");
  assert.equal(outcomeText("draft", "mock"), "The local mock produced a draft.");
  assert.equal(outcomeText("no draft", "mock"), "The local mock declined to draft.");
  for (const recorded of ["draft", "no draft", "refused", "provider error", "credential echo"]) {
    assert.doesNotMatch(outcomeText(recorded, "mock"), /billed/, recorded);
  }
});

// Reopening a saved capture: reads only, verified before anything is offered.
const CAPTURE = "20261005T093000000000Z-0123456789ab";
const HASH = "f".repeat(64);
const PREVIEW_URL = `/api/intake/${CAPTURE}`;
const ATTEMPT_URL = `/api/intake/${CAPTURE}/attempt`;
const MOCK_ONLY = { mock: { enabled: true, detail: "Local mock" }, paid: { enabled: false, detail: "Not enabled" } };
const preview = (changes: object = {}) => ({
  flow_version: INTAKE_FLOW_VERSION, capture_id: CAPTURE, request_sha256: HASH, provider_called: false,
  modes: MOCK_ONLY, ...changes,
});
const json = (status: number, body: unknown) => () =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const down = () => { throw new TypeError("network"); };

/** A fake local server answering by path; it records every request and fails any path it does not know. */
const routes = (answers: Record<string, () => Response>, sent: { url: string; init?: RequestInit }[] = []) =>
  (async (url: string, init?: RequestInit) => {
    sent.push({ url, init });
    if (!answers[url]) throw new TypeError(`unexpected request to ${url}`);
    return answers[url]();
  }) as typeof fetch;
const methods = (sent: { url: string; init?: RequestInit }[]) => sent.map(({ url, init }) => `${init?.method ?? "GET"} ${url}`);

test("reopening a saved capture reads its verified preview, then its attempt state, and nothing else", async () => {
  const sent: { url: string; init?: RequestInit }[] = [];
  const opened = await withFetch(routes({ [PREVIEW_URL]: json(200, preview()), [ATTEMPT_URL]: json(200, state("none")) },
                                        sent), () => reopenCapture(CAPTURE));
  assert.deepEqual(methods(sent), [`GET ${PREVIEW_URL}`, `GET ${ATTEMPT_URL}`]);
  assert.equal(opened.state, "ready");
  if (opened.state !== "ready") return;
  assert.equal(opened.preview.request_sha256, HASH);  // The server's verified saved request, as stored.
  assert.deepEqual(opened.attempt, state("none"));
  assert.equal(opened.problem, null);
  assert.equal(mayApprove(opened.attempt), true);
});

test("a refresh shows the server's current sending modes, but never a saved request whose hash changed", async () => {
  const paid = { ...MOCK_ONLY, paid: { enabled: true, detail: "Paid sending is enabled" } };
  const refreshed = await withFetch(routes({ [PREVIEW_URL]: json(200, preview({ modes: paid })),
                                             [ATTEMPT_URL]: json(200, state("none")) }), () => reopenCapture(CAPTURE, HASH));
  assert.equal(refreshed.state, "ready");
  if (refreshed.state === "ready") assert.equal(refreshed.preview.modes.paid.enabled, true);
  const sent: { url: string; init?: RequestInit }[] = [];
  const changed = await withFetch(routes({ [PREVIEW_URL]: json(200, preview({ request_sha256: "e".repeat(64) })),
                                           [ATTEMPT_URL]: json(200, state("none")) }, sent),
                                  () => reopenCapture(CAPTURE, HASH));
  assert.equal(changed.state, "error");
  if (changed.state === "error") assert.match(changed.message, /changed/);
  assert.deepEqual(methods(sent), [`GET ${PREVIEW_URL}`]);
});

test("a preview that cannot be read or verified is an error, so nothing is offered from it", async () => {
  const cases: Record<string, () => Response> = {
    "unreachable": down,
    "not found": json(404, { detail: "Unknown capture ID" }),
    "server error": json(500, { detail: "Internal error" }),
    "another flow": json(200, preview({ flow_version: "other" })),
    "another capture": json(200, preview({ capture_id: "20261005T093000000001Z-0123456789ab" })),
    "claims a provider call": json(200, preview({ provider_called: true })),
    "no sending modes": json(200, preview({ modes: undefined })),
    "malformed hash": json(200, preview({ request_sha256: "not-a-hash" })),
  };
  for (const [name, answer] of Object.entries(cases)) {
    const opened = await withFetch(routes({ [PREVIEW_URL]: answer, [ATTEMPT_URL]: json(200, state("none")) }),
                                   () => reopenCapture(CAPTURE));
    assert.equal(opened.state, "error", name);
  }
  const missing = await withFetch(routes({ [PREVIEW_URL]: json(404, { detail: "Unknown capture ID" }) }),
                                  () => reopenCapture(CAPTURE));
  assert.deepEqual(missing, { state: "error", message: "Unknown capture ID" });
});

test("an attempt state that cannot be read or verified blocks approval and is never taken as no attempt", async () => {
  const unreadable: Record<string, () => Response> = {
    "unreachable": down,
    "server error": json(500, { detail: "Internal error" }),
    "another flow": json(200, { ...state("none"), flow_version: "other" }),
    "another capture": json(200, { ...state("none"), capture_id: "20261005T093000000001Z-0123456789ab" }),
  };
  for (const [name, answer] of Object.entries(unreadable)) {
    const opened = await withFetch(routes({ [PREVIEW_URL]: json(200, preview()), [ATTEMPT_URL]: answer }),
                                   () => reopenCapture(CAPTURE));
    assert.equal(opened.state, "ready", name);  // The verified preview is shown...
    if (opened.state !== "ready") continue;
    assert.equal(opened.attempt, "unreadable", name);  // ...but what it recorded is unknown,
    assert.notEqual(opened.problem, null, name);
    assert.equal(mayApprove(opened.attempt), false, name);  // so nothing can be approved.
  }
  for (const recorded of ["incomplete", "awaiting_publication", "ready", "invalid"] as const) {
    const opened = await withFetch(routes({ [PREVIEW_URL]: json(200, preview()),
                                            [ATTEMPT_URL]: json(200, state(recorded)) }), () => reopenCapture(CAPTURE));
    assert.equal(opened.state === "ready" && mayApprove(opened.attempt), false, recorded);
  }
});

test("saved captures are listed with one GET, and a listing that cannot be verified is an error", async () => {
  const rows = [{ capture_id: CAPTURE, state: "verified · captured_not_sent", headline: "Headline",
                  published_at: "2026-10-04T18:30:00Z", captured_at: "2026-10-05T09:30:00+00:00", request_sha256: HASH },
                { capture_id: "20261005T093000000001Z-0123456789ab", state: "refused", problem: "source.txt changed" }];
  const sent: { url: string; init?: RequestInit }[] = [];
  const listed = await withFetch(reply(200, { flow_version: INTAKE_FLOW_VERSION, captures: rows }, sent),
                                 () => fetchCaptures());
  assert.deepEqual(listed, { state: "ready", data: rows });
  assert.deepEqual(methods(sent), ["GET /api/intake"]);
  for (const answer of [reply(200, { flow_version: "other", captures: rows }),
                        reply(200, { flow_version: INTAKE_FLOW_VERSION, captures: "none" }),
                        reply(500, { detail: "Internal error" }), (async () => down()) as typeof fetch]) {
    assert.equal((await withFetch(answer, () => fetchCaptures())).state, "error");
  }
});
