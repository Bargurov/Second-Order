// Private market context for selected events: the words the page shows before and after any request, read from
// SYNTHETIC replies shaped like the server's (invented values; nothing here is an H.15 observation).
import assert from "node:assert/strict";
import test from "node:test";
import {
  OUTSIDE_SHORT, SUPPORTED_SOURCES, attemptLine, changeRows, eventHref, formatBp, listedStatus, packageStatus,
  planSentences, resultMessage, timeNote, type Attempt, type EventDefinition, type EventView, type KeptPackage,
  type Plan,
} from "../src/eventContext.ts";
import { BREAKS, GAPS, STATUS_LABEL, chartModel, contextRows } from "../src/marketContext.ts";

const TWO = "RIFLGFCY02_N.B";
const TEN = "RIFLGFCY10_N.B";

function observation(status: string, raw: string | null = null) {
  return { raw, value: raw !== null && status === "session_value" ? Number(raw) : null, status, retrievals: [] };
}

function day(date: string, weekday: string, session: boolean, two: ReturnType<typeof observation>,
             ten = two) {
  return { date, weekday, session, observations: { [TWO]: two, [TEN]: ten } };
}

const VIEW = {
  view_version: "event-market-context-view-0.1", key: "inbox-fed-monetary-0123456789abcdef0123", as_of: "2026-10-09",
  context: { date: "2026-10-02", basis: "confirmed", convention: { id: "new-york-calendar-date-1", statement: "" },
             window: { start: "2026-09-30", end: "2026-10-06", days_before: 2, days_after: 4 } },
  publication: { new_york_date: "2026-10-02" },
  window: { start: "2026-09-30", end: "2026-10-06", days_before: 2, days_after: 4 },
  series: [{ id: TWO, label: "2-year Treasury yield", short_label: "2-year" },
           { id: TEN, label: "10-year Treasury yield", short_label: "10-year" }],
  days: [
    day("2026-09-30", "Wed", true, observation("session_value", "3.50"), observation("session_value", "4.10")),
    day("2026-10-01", "Thu", true, observation("conflict"), observation("session_value", "4.12")),
    day("2026-10-02", "Fri", true, observation("session_value", "3.55"), observation("session_value", "4.15")),
    day("2026-10-03", "Sat", false, observation("weekend")),
    day("2026-10-04", "Sun", false, observation("weekend")),
    day("2026-10-05", "Mon", true, observation("after_retrieval")),
    day("2026-10-06", "Tue", true, observation("future")),
  ],
  endpoints: {
    rule: { id: "endpoint-rule-1", statement: "rule" }, base: "2026-10-01", after_1: "2026-10-05", after_5: null,
    changes: [
      { series: TWO, short_label: "2-year", horizon: 1, from: "2026-10-01", to: "2026-10-05", from_raw: null, to_raw: null,
        change_bp: null, unavailable: "the start session (2026-10-01): retrieval versions disagree" },
      { series: TEN, short_label: "10-year", horizon: 1, from: "2026-10-01", to: "2026-10-05", from_raw: "4.12",
        to_raw: "4.00", change_bp: "-12", unavailable: null },
      { series: TEN, short_label: "10-year", horizon: 5, from: "2026-10-01", to: null, from_raw: null, to_raw: null,
        change_bp: null, unavailable: "the end session is outside the window" },
    ],
  },
  conflicts: [], status_counts: {}, complete: false, retrievals: [], store_problems: [], limits: [],
} as unknown as EventView;

const PLAN: Plan = {
  plan_version: "market-retrieval-plan-0.2", plan_sha256: "a".repeat(64), as_of: "2026-10-09",
  source: {} as Plan["source"],
  events: [{ key: "k1", title: "One", context_date: "2026-07-29", start: "2026-07-15", end: "2026-08-12" },
           { key: "k2", title: "Two", context_date: "2026-09-16", start: "2026-09-02", end: "2026-09-30" }],
  needed_sessions: 40, held_sessions: 0, missing_sessions: [],
  missing_ranges: [{ start: "2026-07-15", end: "2026-08-12", sessions: 20 },
                   { start: "2026-09-02", end: "2026-09-30", sessions: 20 }],
  future_sessions: [], reuse: [], requests: 1,
  request: { url: "https://www.federalreserve.gov/releases/h15/data/FRB_h15_xml.zip", download: "full_release_package",
             missing_sessions: 40, missing_from: "2026-07-15", missing_to: "2026-09-30" },
  next_attempt: 1, packages_not_used: [],
};
const KEPT = { id: "package:p1", package_id: "p1", status: "acquired_unvalidated", detail: null, url: "u",
               requested_at: "2026-10-10T21:56:27.734177+00:00", bytes: 4285147, sha256: "b".repeat(64),
               last_modified: null, acquisition_method: "m", client: { user_agent: "a", transport: "network: x" },
               parser_version: "h15-release-xml-parser-0.1", validated_at: null, release_prepared: null, coverage: null,
               other_validations: [], marker_findings: 2 } as KeptPackage;

test("only Federal Reserve and BLS sources offer market context; the others are explained", () => {
  assert.deepEqual([...SUPPORTED_SOURCES].sort(), ["bls-cpi", "bls-empsit", "fed-monetary"]);
  assert.match(OUTSIDE_SHORT, /not offered for energy or trade entries in this first slice/);
  assert.equal(eventHref("inbox", "fed-monetary:0123"), "/market-context/inbox/fed-monetary%3A0123");
});

test("basis points keep the server's exact difference, with a typographic minus", () => {
  assert.equal(formatBp("+12"), "+12 bp");
  assert.equal(formatBp("-2.5"), "−2.5 bp");
  assert.equal(formatBp("0"), "0 bp");
  assert.equal(formatBp(null), "Unavailable");
});

test("change rows show endpoints and values, or say exactly why a change is unavailable", () => {
  const rows = changeRows(VIEW);
  assert.deepEqual(rows.map((row) => [row.series, row.horizon, row.from, row.to, row.change, row.available]), [
    ["2-year", "1st session after", "1 Oct 2026", "5 Oct 2026", "Unavailable", false],
    ["10-year", "1st session after", "1 Oct 2026: 4.12%", "5 Oct 2026: 4.00%", "−12 bp", true],
    ["10-year", "5th session after", "1 Oct 2026", "Outside the window", "Unavailable", false],
  ]);
  assert.match(rows[0].unavailable!, /retrieval versions disagree/);
});

test("unheld, future and conflicting dates break the line; only gaps and conflicts are marked", () => {
  for (const status of ["not_held", "after_retrieval", "future", "conflict"]) {
    assert.ok(BREAKS.has(status), status);
    assert.ok(!GAPS.has(status), status);
    assert.ok(STATUS_LABEL[status], status);
  }
  const model = chartModel(VIEW);
  const two = model.lines.find((line) => line.id === TWO)!;
  assert.deepEqual(two.points.map((point) => point.date), ["2026-09-30", "2026-10-02"]);
  assert.equal(two.segments.length, 2);  // Broken at the conflict: never drawn across it.
  assert.deepEqual(two.conflicts, ["2026-10-01"]);
  assert.deepEqual(two.missing, []);
  assert.equal(model.marker.date, "2026-10-02");
  const rows = contextRows(VIEW);
  assert.equal(rows.find((row) => row.date === "2026-10-03")!.note, "No session: weekend");
  assert.equal(rows.find((row) => row.date === "2026-10-06")!.note, "Not yet available: today or later");
  assert.match(rows.find((row) => row.date === "2026-10-01")!.note, /^2-year: retrieval versions disagree/);
});

test("the plan says that one request downloads the full release package, not two date-bounded series", () => {
  const sentences = planSentences(PLAN);
  assert.equal(sentences[0], "These events need 40 expected sessions before today (9 Oct 2026, New York); 0 are " +
    "already held locally.");
  assert.equal(sentences[1], "Missing: 40 sessions (15 Jul 2026 to 12 Aug 2026; 2 Sep 2026 to 30 Sep 2026).");
  assert.equal(sentences.at(-1), "Planned: exactly 1 request, which downloads the Board's complete H.15 release " +
    "package: every series of the release over its full history, not a two-series or date-bounded download. Only the " +
    "2-year and 10-year series are read from it, and it is kept privately so that later selections reuse it.");
  const cached = planSentences({ ...PLAN, events: [PLAN.events[0]], requests: 0, request: null, held_sessions: 20,
                                 needed_sessions: 20, missing_ranges: [] });
  assert.equal(cached[0], "This event needs 20 expected sessions before today (9 Oct 2026, New York); 20 are already " +
    "held locally.");
  assert.equal(cached.at(-1), "Planned: no request. Everything these events need before today is already held.");
});

test("a kept package that is not used is named, with how to validate it locally", () => {
  const unused = planSentences({ ...PLAN, packages_not_used: [KEPT] });
  assert.equal(unused.at(-1), "1 kept release package is not used: p1 (acquired, not yet validated, so not used). A " +
    "package not yet validated can be validated locally with python -m second_order market-packages validate, which " +
    "fetches nothing, before approving another download.");
  assert.equal(packageStatus({ ...KEPT, status: "refused", detail: "H15_data.xml has a DOCTYPE declaration" }),
               "kept, but its validation refused its data, so not used: H15_data.xml has a DOCTYPE declaration");
  assert.equal(packageStatus({ ...KEPT, status: "accepted" }), "validated and used");
});

test("attempts and approvals are described from what was recorded, never assumed", () => {
  const earlier = { attempt_version: "market-retrieval-attempt-0.1", events: ["k1"], url: "u",
                    requested_start: "2026-09-02", requested_end: "2026-09-30",
                    started_at: "2026-10-09T15:00:00+00:00", client: { transport: "SYNTHETIC" } };
  const failed: Attempt = { plan_sha256: "a", number: 1, started: earlier, problem: null,
    outcome: { outcome: "refused_reply", detail: "A web page.", http_status: 200, finished_at: "x", retrieval_id: null } };
  assert.equal(attemptLine(failed), "Attempt 1, started 2026-10-09T15:00:00+00:00, the two-series download of 2 Sep " +
    "2026 to 30 Sep 2026: the reply was not kept (HTTP 200). A web page.");
  assert.match(attemptLine({ ...failed, outcome: null }), /no outcome was recorded/);
  const download = { attempt_version: "market-retrieval-attempt-0.2", events: ["k1"], url: "u",
                     download: "full_release_package" as const, started_at: "2026-10-09T15:00:00.000000+00:00",
                     client: { transport: "SYNTHETIC" } };
  const kept: Attempt = { plan_sha256: "a", number: 2, started: download, problem: null,
    outcome: { outcome: "retained_not_accepted", detail: "The package was kept privately, but its data was not accepted.",
               http_status: 200, finished_at: "x", package_id: "p1" } };
  assert.equal(attemptLine(kept), "Attempt 2, started 2026-10-09T15:00:00.000000+00:00, the full H.15 release package: " +
    "the package was kept, but its data was not accepted, so it is not used (HTTP 200). The package was kept privately, " +
    "but its data was not accepted.");
  const result = { result_version: "market-retrieval-result-0.2", plan_sha256: "a", attempt: 2, retries: 0 as const,
                   provider_called: true, package_id: null, validation: null, detail: "Timed out." };
  assert.deepEqual(resultMessage({ ...result, outcome: "no_reply" }),
                   { text: "Attempt 2: no reply was received. Timed out. Nothing was retried automatically.", tone: "error" });
  assert.equal(resultMessage({ ...result, outcome: "saved", package_id: "p1", validation: "accepted",
                               detail: "Kept and accepted." }).tone, "done");
  assert.equal(resultMessage({ ...result, outcome: "retained_not_accepted", package_id: "p1", validation: "refused",
                               detail: "Not accepted." }).tone, "error");
});

test("a capture's supplied time and an entry's feed timestamp are shown as such", () => {
  const capture = { supplied: { published_at_as_supplied: "2026-09-16T14:00:00-04:00", published_at: "x",
                                new_york_time: "14:00", new_york_offset: "-04:00", note: "Supplied by the operator." },
                    timestamp: null } as unknown as EventDefinition;
  assert.equal(timeNote(capture), "Publication time supplied with the saved event: 2026-09-16T14:00:00-04:00 (14:00 New " +
    "York time, UTC-04:00). Supplied by the operator.");
  const entry = { supplied: null, timestamp: { raw: "Wed, 16 Sep 2026 18:00:00 GMT", origin: "RSS pubDate" } } as
    unknown as EventDefinition;
  assert.match(timeNote(entry), /metadata, not a verified publication instant/);
  assert.equal(listedStatus({ key: "k", kind: "inbox", id: "i", title: "t", link: null, family_label: "x", supported: true,
                              outside: null, problem: null, context: null }), "No context date confirmed yet.");
  assert.equal(listedStatus({ key: "k", kind: "inbox", id: "i", title: "t", link: null, family_label: "x", supported: true,
                              outside: null, problem: null, context: VIEW.context, complete: false, missing_sessions: 1,
                              future_sessions: 5, conflicts: 0 }),
               "Partial window: 1 session not held locally; 5 sessions on or after today.");
});
