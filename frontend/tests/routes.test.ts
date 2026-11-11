// Route parsing: malformed addresses are Not Found pages, valid deep links and ?leg= keep working.
import assert from "node:assert/strict";
import { test } from "node:test";
import { matchRoute, requestedLeg, safeDecode } from "../src/routes.ts";

const ID = "1499697aff5a1af3abe29c51a9f01e24f3e1481de69b50ba240c334a4d25b551";

test("valid deep links resolve to the dossier ID", () => {
  assert.deepEqual(matchRoute("/"), { page: "index" });
  assert.deepEqual(matchRoute(`/h/${ID}`), { page: "dossier", id: ID });
  assert.deepEqual(matchRoute(`/h/${ID}/`), { page: "dossier", id: ID });
  assert.deepEqual(matchRoute("/h/%31%3499"), { page: "dossier", id: "1499" });
  assert.deepEqual(matchRoute("/h/abc%20def"), { page: "dossier", id: "abc def" });
});

test("invalid percent escapes are a Not Found address, not an exception", () => {
  for (const path of ["/h/%", "/h/%Z1", "/h/abc%", "/h/%%41", "/h/%4"]) {
    assert.doesNotThrow(() => matchRoute(path), path);
    assert.deepEqual(matchRoute(path), { page: "not-found", reason: "malformed" }, path);
  }
});

test("invalid UTF-8 sequences are a Not Found address", () => {
  // Bad continuation, truncated sequence, invalid byte, encoded surrogate, overlong encoding.
  for (const path of ["/h/%C3%28", "/h/%E0%A4", "/h/%FF", "/h/%ED%A0%80", "/h/%C0%AF"]) {
    assert.deepEqual(matchRoute(path), { page: "not-found", reason: "malformed" }, path);
  }
});

test("the Method page has one address, with or without a trailing slash", () => {
  assert.deepEqual(matchRoute("/method"), { page: "method" });
  assert.deepEqual(matchRoute("/method/"), { page: "method" });
});

test("the fuels page has one address, with or without a trailing slash", () => {
  assert.deepEqual(matchRoute("/fuels"), { page: "fuels" });
  assert.deepEqual(matchRoute("/fuels/"), { page: "fuels" });
  for (const path of ["/fuels/x", "/Fuels", "/fuel"]) {
    assert.deepEqual(matchRoute(path), { page: "not-found", reason: "unknown" }, path);
  }
});

test("unknown paths stay Not Found", () => {
  for (const path of ["/x", "/h", "/h/", `/h/${ID}/extra`, "/methods", "/method/x", "/Method"]) {
    assert.deepEqual(matchRoute(path), { page: "not-found", reason: "unknown" }, path);
  }
});

test("only URIError is treated as a malformed address", () => {
  assert.equal(safeDecode("%E2%82%AC"), "€");
  assert.equal(safeDecode("%E2%82"), null);
});

test("the ?leg= selection survives refresh and tolerates malformed escapes", () => {
  assert.equal(requestedLeg("?leg=secondary"), "secondary");
  assert.equal(requestedLeg("?leg=primary&x=1"), "primary");
  assert.equal(requestedLeg(""), null);
  assert.doesNotThrow(() => requestedLeg("?leg=%"));
  assert.doesNotThrow(() => requestedLeg("?leg=%C3%28"));
});

test("market context has a list address and one address per saved event or Inbox entry", () => {
  assert.deepEqual(matchRoute("/market-context"), { page: "market-context" });
  assert.deepEqual(matchRoute("/market-context/"), { page: "market-context" });
  assert.deepEqual(matchRoute("/market-context/inbox/fed-monetary%3A0123456789abcdef0123"),
                   { page: "market-context-event", kind: "inbox", id: "fed-monetary:0123456789abcdef0123" });
  assert.deepEqual(matchRoute("/market-context/capture/20261005T080159226239Z-fcf7bcfead4c/"),
                   { page: "market-context-event", kind: "capture", id: "20261005T080159226239Z-fcf7bcfead4c" });
  assert.deepEqual(matchRoute("/market-context/inbox/%E0%A4"), { page: "not-found", reason: "malformed" });
  for (const path of ["/market-context/other/x", "/market-context/inbox", "/market-context/inbox/a/b", "/Market-context"]) {
    assert.deepEqual(matchRoute(path), { page: "not-found", reason: "unknown" }, path);
  }
});

test("the case library has a list address and one address per case", () => {
  assert.deepEqual(matchRoute("/library"), { page: "library" });
  assert.deepEqual(matchRoute("/library/"), { page: "library" });
  assert.deepEqual(matchRoute("/library/fomc-2025-03-19"), { page: "library-case", id: "fomc-2025-03-19" });
  assert.deepEqual(matchRoute("/library/cpi-2025-07-15/"), { page: "library-case", id: "cpi-2025-07-15" });
  assert.deepEqual(matchRoute("/library/%E0%A4"), { page: "not-found", reason: "malformed" });
  for (const path of ["/library/a/b", "/libraries", "/Library"]) {
    assert.deepEqual(matchRoute(path), { page: "not-found", reason: "unknown" }, path);
  }
});

test("historical cases have their own address under the case library", () => {
  assert.deepEqual(matchRoute("/library/historical/bis-2022-10-07"), { page: "historical-case", id: "bis-2022-10-07" });
  assert.deepEqual(matchRoute("/library/historical/bis-2022-10-07/"), { page: "historical-case", id: "bis-2022-10-07" });
  assert.deepEqual(matchRoute("/library/historical/%E0%A4"), { page: "not-found", reason: "malformed" });
  assert.deepEqual(matchRoute("/library/fomc-2025-01-29"), { page: "library-case", id: "fomc-2025-01-29" });
  assert.deepEqual(matchRoute("/library/historical/a/b"), { page: "not-found", reason: "unknown" });
});

test("the metals comparison has one address, with or without a trailing slash", () => {
  assert.deepEqual(matchRoute("/metals"), { page: "metals" });
  assert.deepEqual(matchRoute("/metals/"), { page: "metals" });
  for (const path of ["/metals/x", "/metals/copper/", "/Metals", "/metal"]) {
    assert.deepEqual(matchRoute(path), { page: "not-found", reason: "unknown" }, path);
  }
});

test("the FCX company page has one address, with or without a trailing slash", () => {
  assert.deepEqual(matchRoute("/companies/fcx"), { page: "company" });
  assert.deepEqual(matchRoute("/companies/fcx/"), { page: "company" });
  for (const path of ["/companies", "/companies/", "/companies/FCX", "/companies/fcx/x", "/companies/scco"]) {
    assert.deepEqual(matchRoute(path), { page: "not-found", reason: "unknown" }, path);
  }
});

test("the copper event chains page has one address, with or without a trailing slash", () => {
  assert.deepEqual(matchRoute("/theses/copper/events"), { page: "copper-events" });
  assert.deepEqual(matchRoute("/theses/copper/events/"), { page: "copper-events" });
  for (const path of ["/theses/copper/events/x", "/theses/copper/event", "/theses/Copper/events"]) {
    assert.notDeepEqual(matchRoute(path), { page: "copper-events" }, path);
  }
  assert.deepEqual(matchRoute("/theses/copper/events/x"), { page: "not-found", reason: "unknown" });
});

test("the copper desk has one address, and each comparison one address under it", () => {
  assert.deepEqual(matchRoute("/copper"), { page: "copper-desk" });
  assert.deepEqual(matchRoute("/copper/"), { page: "copper-desk" });
  assert.deepEqual(matchRoute("/copper/comparisons/synthetic-annual-to-quarter"),
                   { page: "copper-comparison", id: "synthetic-annual-to-quarter" });
  assert.deepEqual(matchRoute("/copper/comparisons/fcx-10k-2025-to-10q-2026q3/"),
                   { page: "copper-comparison", id: "fcx-10k-2025-to-10q-2026q3" });
  assert.deepEqual(matchRoute("/copper/comparisons/%61bc"), { page: "copper-comparison", id: "abc" });
  for (const path of ["/Copper", "/copper/x", "/copper/comparisons", "/copper/comparisons/", "/copper/comparisons/a/b",
    "/copper/notes"]) {
    assert.deepEqual(matchRoute(path), { page: "not-found", reason: "unknown" }, path);
  }
});

test("a malformed comparison id is a Not Found address, never a comparison page", () => {
  // An id is lower-case letters and digits in words joined by single hyphens; anything else is not served.
  for (const path of ["/copper/comparisons/Annual-to-quarter", "/copper/comparisons/a--b", "/copper/comparisons/-a",
    "/copper/comparisons/a-", "/copper/comparisons/a_b", "/copper/comparisons/a.b", "/copper/comparisons/a%20b",
    "/copper/comparisons/..%2Fnotes", "/copper/comparisons/%D7%90"]) {
    assert.deepEqual(matchRoute(path), { page: "not-found", reason: "unknown" }, path);
  }
  for (const path of ["/copper/comparisons/%", "/copper/comparisons/%E0%A4", "/copper/comparisons/a%ZZ"]) {
    assert.deepEqual(matchRoute(path), { page: "not-found", reason: "malformed" }, path);
  }
});
