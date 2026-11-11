// The onboarding contract (onboarding-api-0.1) against its SYNTHETIC fixtures (frontend/tests/fixtures/onboarding-
// *.json): every fixture reads, tampered or contradictory payloads are refused, nothing public carries money, a model,
// a provider, a token count or a planning estimate, a registration never carries an account ID, role or password, and
// the request helpers send exactly the documented requests. Owned by the logic conversation with
// src/contracts/onboarding.ts. The example numbers in the fixtures come from a synthetic test policy, not a tariff.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { test } from "node:test";
import {
  ONBOARDING_CONTRACT, ONBOARDING_ERROR_CODES, onboardingApi, readCreditTerms, readOnboardingError, readRegistration,
  registrationFormProblem, type CreditTerms, type RegistrationForm,
} from "../src/contracts/onboarding.ts";
import { SESSION_HEADER, readError, type Read } from "../src/contracts/user.ts";

const fixtures = new URL("./fixtures/", import.meta.url);
const load = <T = Record<string, unknown>>(name: string): T =>
  JSON.parse(readFileSync(new URL(`onboarding-${name}.json`, fixtures), "utf8"));
const problem = <T>(read: Read<T>) => (read.ok ? null : read.problem);
const FORM: RegistrationForm = { username: "reader-c", display_name: "Reader C", password: "synthetic-pass", note: "" };

const READERS: Record<string, (body: unknown) => Read<unknown>> = {
  "credit-terms": readCreditTerms, "credit-terms-none": readCreditTerms, "registration-created": readRegistration,
  "registration-duplicate": readRegistration,
};

test("every published fixture has a reader, and reads", () => {
  const published = readdirSync(fixtures).filter((name) => name.startsWith("onboarding-") && name !== "onboarding-errors.json")
    .map((name) => name.slice("onboarding-".length, -".json".length)).sort();
  assert.deepEqual(published, Object.keys(READERS).sort());
  for (const [name, read] of Object.entries(READERS)) assert.equal(problem(read(load(name))), null, name);
  assert.equal(load<{ duplicate: boolean }>("registration-duplicate").duplicate, true);
});

test("every onboarding refusal has a readable example", () => {
  const errors = load<Record<string, unknown>>("errors");
  assert.deepEqual(Object.keys(errors).sort(), [...ONBOARDING_ERROR_CODES].sort());
  for (const [code, body] of Object.entries(errors)) assert.equal(problem(readOnboardingError(body)), null, code);
  const invalid = errors.invalid_registration as Record<string, unknown>;
  assert.equal(invalid.field, "password");
  assert.ok(problem(readOnboardingError({ ...invalid, field: undefined })));
  assert.ok(problem(readOnboardingError({ ...invalid, field: "role" })));
  assert.ok(problem(readOnboardingError({ ...(errors.username_unavailable as object), field: "username" })));
  assert.ok(problem(readOnboardingError({ contract: ONBOARDING_CONTRACT, code: "registration_pending", detail: "x" })));
});

test("nothing public carries money, a model, a provider, tokens or an administrator-only field", () => {
  for (const name of readdirSync(fixtures).filter((file) => file.startsWith("onboarding-"))) {
    const raw = readFileSync(new URL(name, fixtures), "utf8");
    assert.doesNotMatch(raw, /claude|sonnet|opus|haiku|anthropic|\busd\b|\$|token|dollar|price/i, name);
    assert.doesNotMatch(raw, /"(user_id|role|password|reason|planning_estimate_usd|input_tokens_assumed)":/, name);
  }
  const leaked = { ...load("credit-terms"), planning_estimate_usd: 0.2 };
  assert.match(problem(readCreditTerms(leaked)) ?? "", /administrator-only/);
});

test("credit terms must agree with their state, the offered Effort and the order of sizes", () => {
  const terms = () => structuredClone(load<CreditTerms>("credit-terms"));
  const cases: [string, (value: CreditTerms) => void, RegExp][] = [
    ["unknown state", (t) => { (t as { state: string }).state = "draft"; }, /not readable/],
    ["a quote for an Effort not offered", (t) => { t.examples[0].quotes[0].effort = "max"; }, /every offered Effort/],
    ["a missing quote", (t) => { t.examples[1].quotes.pop(); }, /every offered Effort/],
    ["a fractional quote", (t) => { t.examples[2].quotes[0].credits = 1.5; }, /every offered Effort/],
    ["sizes out of order", (t) => { t.examples[0].characters = 99_999; }, /order of size/],
    ["no policy version", (t) => { t.policy_version = null; }, /configured credit terms/],
    ["no quote validity", (t) => { t.quote_valid_seconds = null; }, /configured credit terms/],
    ["another contract", (t) => { (t as { contract: string }).contract = "user-api-0.2"; }, /contract/],
  ];
  for (const [name, change, expected] of cases) {
    const value = terms();
    change(value);
    assert.match(problem(readCreditTerms(value)) ?? "", expected, name);
  }
  const none = load<CreditTerms>("credit-terms-none");
  assert.equal(none.state, "no_credit_policy");
  assert.match(problem(readCreditTerms({ ...none, examples: terms().examples })) ?? "", /cannot carry/);
});

test("a registration shows the registrant's own status and nothing else", () => {
  const created = load<{ registration: Record<string, unknown> }>("registration-created");
  for (const [field, value] of [["user_id", "u-0000000000000000"], ["role", "admin"], ["password", "x"],
                                ["credits", 10]] as const) {
    const tampered = structuredClone(created);
    tampered.registration[field] = value;
    assert.match(problem(readRegistration(tampered)) ?? "", /unexpected field/, field);
  }
  const decided = structuredClone(created);
  decided.registration.decided_at = "2026-10-14T10:00:00+00:00";
  assert.ok(problem(readRegistration(decided)));
  const rejected = structuredClone(created);
  rejected.registration.status = "rejected";
  rejected.registration.decided_at = "2026-10-14T10:00:00+00:00";
  assert.match(problem(readRegistration(rejected)) ?? "", /pending/);
});

test("the sign-in refusals of a registration carry its own status (user-api-0.2)", () => {
  const errors = JSON.parse(readFileSync(new URL("user-contract-errors.json", fixtures), "utf8"));
  for (const code of ["registration_pending", "registration_rejected"]) {
    const read = readError(errors[code]);
    assert.ok(read.ok, code);
    assert.equal(read.ok && read.value.registration?.status, code.slice("registration_".length));
  }
  assert.ok(problem(readError({ ...errors.registration_pending, registration: undefined })));
  assert.ok(problem(readError({ ...errors.invalid_credentials, registration: errors.registration_pending.registration })));
  assert.ok(problem(readError({ ...errors.registration_rejected, registration: errors.registration_pending.registration })));
});

test("a form is checked before sending, with the server's own rules", () => {
  assert.equal(registrationFormProblem(FORM), null);
  for (const change of [{ username: "Reader" }, { username: "ab" }, { display_name: " " }, { password: "short" },
                        { note: "x".repeat(501) }, { note: "two\nlines" }]) {
    assert.ok(registrationFormProblem({ ...FORM, ...change }), JSON.stringify(change));
  }
});

function transport(status: number, body: unknown, seen: { url: string; init: RequestInit }[]) {
  return async (url: string, init: RequestInit) => {
    seen.push({ url, init });
    return new Response(JSON.stringify(body), { status });
  };
}

test("the terms are a plain GET; a registration is one JSON POST with the session header, never retried", async () => {
  const seen: { url: string; init: RequestInit }[] = [];
  const terms = await onboardingApi(transport(200, load("credit-terms"), seen)).creditTerms();
  assert.equal(terms.state, "ok");
  assert.deepEqual([seen[0].url, seen[0].init.method, seen[0].init.body], ["/api/public/credit-terms", "GET", undefined]);
  const created = await onboardingApi(transport(201, load("registration-created"), seen)).register(FORM);
  assert.equal(created.state, "ok");
  assert.deepEqual([seen[1].url, seen[1].init.method], ["/api/public/registrations", "POST"]);
  assert.equal((seen[1].init.headers as Record<string, string>)[SESSION_HEADER], "1");
  assert.deepEqual(JSON.parse(String(seen[1].init.body)), FORM);
  const errors = load<Record<string, unknown>>("errors");
  const refused = await onboardingApi(transport(409, errors.username_unavailable, seen)).register(FORM);
  assert.equal(refused.state === "refused" && refused.error.code, "username_unavailable");
  const failed = await onboardingApi(transport(500, errors.internal_error, seen)).register(FORM);
  assert.equal(failed.state, "unconfirmed");
  const lost = await onboardingApi(async () => { throw new TypeError("network"); }).register(FORM);
  assert.equal(lost.state, "unconfirmed");
  assert.equal(seen.length, 4);
});
