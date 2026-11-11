// The public pages' rules (src/public/*.ts) against the SYNTHETIC onboarding and user-contract fixtures: which page an
// address shows and where a sign-in leads, the registration form (its checks, the one body it sends, every reply, the
// password kept only while the form is live and cleared after any refusal, nothing sent again on its own), what a
// sign-in reply means, a registrant's own status, and the credit terms exactly as the server states them. Page rules
// only: what the server enforces is proved by the backend tests and the joint browser journey, not here.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import type { CreditTerms, OnboardingError, RegistrationReply } from "../src/contracts/onboarding.ts";
import type { ApiError, RegistrationStatus, Reply, Session } from "../src/contracts/user.ts";
import {
  draftProblems, emptyRegister, reduceRegister, toSend, type RegisterEvent, type RegisterState,
} from "../src/public/registerForm.ts";
import { afterSignIn, publicRoute } from "../src/public/route.ts";
import { signInOutcome } from "../src/public/signIn.ts";
import { statusView } from "../src/public/status.ts";
import { EXAMPLES_CAPTION, termsView, validityText } from "../src/public/terms.ts";

const load = <T>(name: string): T =>
  JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8"));
const terms = load<CreditTerms>("onboarding-credit-terms");
const none = load<CreditTerms>("onboarding-credit-terms-none");
const created = load<RegistrationReply>("onboarding-registration-created");
const duplicate = load<RegistrationReply>("onboarding-registration-duplicate");
const onboardingErrors = load<Record<string, OnboardingError>>("onboarding-errors");
const userErrors = load<Record<string, ApiError>>("user-contract-errors");
const signedIn = load<Session>("user-contract-session-signed-in");
const signedOut = load<Session>("user-contract-session-signed-out");
const pending = userErrors.registration_pending.registration as RegistrationStatus;
const rejected = userErrors.registration_rejected.registration as RegistrationStatus;

const FILLED = { username: "reader-c", display_name: "Reader C (synthetic)", password: "synthetic-pass-1",
                 repeat: "synthetic-pass-1", note: "SYNTHETIC note for the administrator" };
const edits = (draft: Partial<typeof FILLED>): RegisterEvent[] =>
  Object.entries(draft).map(([field, value]) => ({ type: "edit", field: field as keyof typeof FILLED, value }));
const run = (events: RegisterEvent[], from: RegisterState = emptyRegister) => events.reduce(reduceRegister, from);
const sending = run([...edits(FILLED), { type: "submit" }]);
const ok = (body: RegistrationReply, status = 201): Reply<RegistrationReply, OnboardingError> =>
  ({ state: "ok", status, data: body });
const refused = (code: string, status = 422): Reply<RegistrationReply, OnboardingError> =>
  ({ state: "refused", status, error: onboardingErrors[code] });
const lost: Reply<RegistrationReply, OnboardingError> =
  { state: "unconfirmed", status: null, message: "No reply arrived from the server.", error: null };

test("addresses: the four public pages, trailing slashes, and every other address is sign-in at that address", () => {
  const expected: Record<string, string> = { "/": "landing", "/client.html": "landing", "/register": "register",
    "/register/": "register", "/sign-in": "sign-in", "/sign-in/": "sign-in", "/credits": "credits",
    "/credits/": "credits", "/sources": "other", "/sources/new": "other", "/analyses/a.b": "other", "/admin": "other",
    "/registered": "other", "/credits/x": "other" };
  for (const [path, route] of Object.entries(expected)) assert.equal(publicRoute(path), route, path);
});

test("after signing in from the landing, registration or sign-in page the Client opens at home; elsewhere it stays", () => {
  for (const path of ["/", "/register", "/sign-in", "/sign-in/"]) assert.equal(afterSignIn(path), "/", path);
  for (const path of ["/credits", "/sources/x", "/analyses/a.b", "/no-such-page"]) assert.equal(afterSignIn(path), null, path);
});

test("the form checks each field by the server's rules before anything is sent", () => {
  assert.deepEqual(draftProblems(FILLED), {});
  const bad = draftProblems({ username: "Reader C", display_name: " ", password: "short", repeat: "other",
                              note: "x".repeat(501) });
  // The repeat is compared only with a password that meets the rules: one mark per mistake.
  assert.deepEqual(Object.keys(bad).sort(), ["display_name", "note", "password", "username"]);
  for (const username of ["ab", "-reader", "reader c", "READER", "a".repeat(41)]) {
    assert.ok(draftProblems({ ...FILLED, username }).username, username);
  }
  for (const username of ["abc", "reader.c", "reader_c-2", "9reader", "a".repeat(40)]) {
    assert.equal(draftProblems({ ...FILLED, username }).username, undefined, username);
  }
  assert.ok(draftProblems({ ...FILLED, display_name: "x".repeat(81) }).display_name);
  assert.ok(draftProblems({ ...FILLED, password: "x".repeat(257), repeat: "x".repeat(257) }).password);
  assert.ok(draftProblems({ ...FILLED, password: "synthetic\u0007pass", repeat: "synthetic\u0007pass" }).password);
  assert.equal(draftProblems({ ...FILLED, note: "" }).note, undefined);  // The note is optional.
  assert.equal(draftProblems({ ...FILLED, repeat: "synthetic-pass-2" }).repeat, "The two passwords differ.");
});

test("a note typed or pasted on several lines becomes one paragraph, as the server accepts it", () => {
  const state = run(edits({ note: "first line\nsecond\r\nthird\tfourth" }));
  assert.equal(state.draft.note, "first line second third fourth");
});

test("a submit with problems marks the fields and sends nothing; a clean submit sends exactly four fields once", () => {
  const blocked = run([...edits({ ...FILLED, repeat: "different-pass" }), { type: "submit" }]);
  assert.equal(blocked.phase, "editing");
  assert.equal(toSend(blocked), null);
  assert.deepEqual(Object.keys(blocked.errors), ["repeat"]);
  assert.equal(blocked.draft.password, FILLED.password);  // Not sent, so nothing was refused: the typing stays.
  assert.equal(sending.phase, "sending");
  assert.deepEqual(toSend(sending), { username: "reader-c", display_name: "Reader C (synthetic)",
                                      password: "synthetic-pass-1", note: "SYNTHETIC note for the administrator" });
  assert.equal(run([{ type: "submit" }], sending).phase, "sending");  // A second press while sending changes nothing.
  assert.deepEqual(run(edits({ username: "other" }), sending).draft, sending.draft);
  const fixed = run([{ type: "edit", field: "repeat", value: FILLED.password }], blocked);
  assert.equal(fixed.errors.repeat, undefined);  // Editing a field clears its own mark.
});

test("a received registration shows the server's record and drops everything typed, the password included", () => {
  const done = reduceRegister(sending, { type: "reply", reply: ok(created) });
  assert.equal(done.phase, "received");
  assert.deepEqual(done.received, { registration: created.registration, duplicate: false });
  assert.deepEqual(done.draft, emptyRegister.draft);
  assert.equal(toSend(done), null);
  const repeat = reduceRegister(sending, { type: "reply", reply: ok(duplicate, 200) });
  assert.deepEqual(repeat.received, { registration: duplicate.registration, duplicate: true });
});

test("every refusal keeps what was typed except the password, which is cleared, and nothing is resent", () => {
  for (const [code, field] of [["username_unavailable", "username"], ["invalid_registration", "password"]] as const) {
    const after = reduceRegister(sending, { type: "reply", reply: refused(code, code === "username_unavailable" ? 409 : 422) });
    assert.equal(after.phase, "editing", code);
    assert.equal(after.errors[field], onboardingErrors[code].detail, code);
    assert.deepEqual([after.draft.password, after.draft.repeat], ["", ""], code);
    assert.deepEqual([after.draft.username, after.draft.display_name, after.draft.note],
                     [FILLED.username, FILLED.display_name, FILLED.note], code);
    assert.match(after.notice!.detail, /Nothing was recorded/, code);
    assert.equal(toSend(after), null, code);
  }
  const titles: Record<string, RegExp> = { invalid_request: /malformed/, payload_too_large: /too large/,
    forbidden: /not accepted/, accounts_unavailable: /does not take registrations/ };
  for (const [code, title] of Object.entries(titles)) {
    const status = { payload_too_large: 413, forbidden: 403, accounts_unavailable: 503 }[code] ?? 422;
    const after = reduceRegister(sending, { type: "reply", reply: refused(code, status) });
    assert.match(after.notice!.title, title, code);
    assert.ok(after.notice!.detail.includes(onboardingErrors[code].detail), code);
    assert.deepEqual([after.phase, after.draft.password, after.draft.repeat, after.draft.username],
                     ["editing", "", "", FILLED.username], code);
  }
});

test("an unconfirmed reply proves nothing: both password fields are cleared and nothing is sent again by itself", () => {
  const unreadable: Reply<RegistrationReply, OnboardingError> = { state: "unconfirmed", status: 201, error: null,
    message: "The server replied, but the reply could not be read: The registration is not readable." };
  for (const reply of [lost, { ...lost, status: 500, error: onboardingErrors.internal_error }, unreadable] as const) {
    const unsure = reduceRegister(sending, { type: "reply", reply });
    assert.deepEqual([unsure.phase, unsure.unconfirmed], ["editing", true]);
    assert.deepEqual([unsure.draft.password, unsure.draft.repeat], ["", ""]);  // No secret is kept to replay.
    assert.deepEqual([unsure.draft.username, unsure.draft.display_name, unsure.draft.note],
                     [FILLED.username, FILLED.display_name, FILLED.note]);
    assert.equal(toSend(unsure), null);  // Never resent on its own.
    assert.match(unsure.notice!.detail, /signing in/);
    assert.match(unsure.notice!.detail, /type the password again/);
    const blank = reduceRegister(unsure, { type: "submit" });  // A fresh submit needs the password typed again.
    assert.deepEqual([toSend(blank), Object.keys(blank.errors)], [null, ["password"]]);
    const retyped = run([...edits({ password: FILLED.password, repeat: FILLED.password }), { type: "submit" }], blank);
    assert.deepEqual(toSend(retyped), toSend(sending));  // The same four fields, because the person typed them.
    assert.equal(retyped.unconfirmed, false);
  }
});

test("a sign-in reply: signed in, a registrant's own status, a refusal, or unconfirmed (never resent)", () => {
  assert.deepEqual(signInOutcome({ state: "ok", status: 200, data: signedIn }), { kind: "signed-in", session: signedIn });
  for (const code of ["registration_pending", "registration_rejected"]) {
    assert.deepEqual(signInOutcome({ state: "refused", status: 403, error: userErrors[code] }),
                     { kind: "registration", registration: userErrors[code].registration });
  }
  assert.deepEqual(signInOutcome({ state: "refused", status: 401, error: userErrors.invalid_credentials }),
                   { kind: "refused", detail: userErrors.invalid_credentials.detail });
  assert.equal(signInOutcome({ state: "ok", status: 200, data: signedOut }).kind, "refused");
  const unsure = signInOutcome({ state: "unconfirmed", status: null, message: "No reply arrived.", error: null });
  assert.equal(unsure.kind, "unconfirmed");
  assert.match((unsure as { detail: string }).detail, /not sent again/);
});

test("a registrant's own status shows only their registration, in the reader's time zone", () => {
  const waiting = statusView(pending, "Asia/Jerusalem");
  assert.equal(waiting.title, "Your registration is waiting for approval");
  assert.deepEqual(waiting.facts, [["Username", "reader-c"], ["Display name", "Reader C (synthetic)"],
    ["Submitted", "14 Oct 2026, 12:00 (Asia/Jerusalem)"], ["Status", "Waiting for approval"]]);
  assert.equal(waiting.detail, pending.detail);
  assert.match(waiting.next.join(" "), /allocates credits and a daily allowance separately/);
  const declined = statusView(rejected, "UTC");
  assert.equal(declined.title, "Your registration was not approved");
  assert.deepEqual(declined.facts.at(-1), ["Status", "Not approved"]);
  assert.ok(declined.facts.some(([label]) => label === "Decided"));
  assert.match(declined.next.join(" "), /cannot be registered again/);
  assert.match(declined.next.join(" "), /another username/);
});

test("credit terms: the server's rules and synthetic quotes exactly as read, labelled as synthetic", () => {
  const view = termsView(terms);
  assert.equal(view.configured, true);
  assert.deepEqual(view.rules, terms.rules);
  assert.deepEqual(view.columns, ["Low", "Medium", "High"]);
  assert.deepEqual(view.examples.map((row) => [row.label, row.characters, row.cells]),
    terms.examples.map((example) => [example.label, `${example.characters.toLocaleString("en")} characters`,
      example.quotes.map((quote) => String(quote.credits))]));
  assert.equal(view.validity, "15 minutes");
  assert.equal(view.sizeNote, terms.size_note);
  assert.match(EXAMPLES_CAPTION, /synthetic/);
  assert.match(EXAMPLES_CAPTION, /Your own source gets its own quote/);
  const changed = termsView({ ...terms, examples: terms.examples.map((example) =>
    ({ ...example, quotes: example.quotes.map((quote) => ({ ...quote, credits: quote.credits + 100 })) })) });
  assert.equal(changed.examples[0].cells[0], String(terms.examples[0].quotes[0].credits + 100));  // Read, never copied.
});

test("flat terms, read from the server: the Effort decides the quote and the length does not, said from the quotes", () => {
  // SYNTHETIC: the selected flat rates, computed by the server's own credit_terms code from an in-memory policy.
  const flat = load<CreditTerms>("public-credit-terms-flat");
  const view = termsView(flat);
  assert.equal(view.sizeNeutral, true);
  assert.deepEqual(view.columns, flat.efforts.map((option) => option.label));
  assert.deepEqual(view.perEffort, flat.efforts.map((option, index) =>
    ({ label: option.label, credits: String(flat.examples[0].quotes[index].credits) })));
  assert.equal(view.sizeNote, flat.size_note);
  // Size-dependent terms, or none, never claim it.
  assert.deepEqual([termsView(terms).sizeNeutral, termsView(terms).perEffort], [false, []]);
  assert.deepEqual([termsView(none).sizeNeutral, termsView(none).perEffort], [false, []]);
  const uneven = { ...flat, examples: flat.examples.map((example, index) => index === 2 ? { ...example,
    quotes: example.quotes.map((quote) => ({ ...quote, credits: quote.credits + 1 })) } : example) };
  assert.equal(termsView(uneven).sizeNeutral, false);
});

test("credit terms with no policy: the rules and the server's reason, and no number at all", () => {
  const view = termsView(none);
  assert.deepEqual([view.configured, view.examples, view.columns, view.validity, view.policy],
                   [false, [], [], null, null]);
  assert.equal(view.detail, none.detail);
  assert.deepEqual(view.rules, none.rules);
});

test("a quote's validity is said in plain units", () => {
  assert.deepEqual([60, 900, 3600, 7200, 5400, 90].map(validityText),
    ["1 minute", "15 minutes", "1 hour", "2 hours", "90 minutes", "1 minute 30 seconds"]);
});
