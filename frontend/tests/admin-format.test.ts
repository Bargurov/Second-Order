// The Admin screens' wording and requests: a missing cost, usage or time is said to be missing (never $0 or 0), the
// /admin paths map to their screens and leave every operator page alone, reads are plain GETs, writes carry the admin
// header, and a reply that is not an administrator payload is refused.
import assert from "node:assert/strict";
import { test } from "node:test";
import { ADMIN_HEADER, adminGet, adminPaths, adminPost, bindAdminAccount, newKey, type ActionRow } from "../src/admin/adminApi.ts";
import { ACCOUNT_HEADER } from "../src/contracts/user.ts";
import {
  adminScreen, allowance, count, credits, emptyUsageForm, manageHref, manageTarget, nameOf, needsAttention,
  offersInitialAllocation, presetDraft, presetPoints, requester, seconds, unapproved, usage, usageDraft, usageFormFrom, usd,
  when,
} from "../src/admin/adminFormat.ts";
import type { AdminUser, Policy, PolicyPreset, UsageLimits } from "../src/admin/adminApi.ts";

test("unknown cost, usage and timing are never shown as zero", () => {
  assert.equal(usd(null), "Unknown");
  assert.equal(usd(undefined), "Unknown");
  assert.equal(usd(0), "$0.0000");
  assert.equal(usd(0.0112), "$0.0112");
  assert.equal(usd(0.000123), "$0.000123");
  assert.equal(usage(null), "Not reported");
  assert.equal(usage({}), "Not reported");
  assert.equal(usage({ input_tokens: 2100, output_tokens: 700 }), "2,100 in · 700 out");
  assert.equal(seconds(null), "Not recorded");
  assert.equal(seconds(0.25), "250 ms");
  assert.equal(seconds(12.34), "12.3 s");
  assert.equal(when(null), "Not recorded");
  assert.equal(when("2026-10-14T09:00:00+00:00"), "2026-10-14 09:00:00 UTC");
});

test("rows name who asked and what the credits did", () => {
  const operator = { request_id: "x", capture_id: "c", action: "local_mock", requested_by: { kind: "operator" },
                     entitlement: null } as ActionRow;
  assert.equal(requester(operator), "Operator");
  assert.equal(credits(operator), "Operator: no credits");
  const user = { ...operator, action: "provider_call",
    requested_by: { kind: "user", user_id: "u-0000000000000001", username: "reader-a", display_name: "Reader A" },
    entitlement: { credits_quoted: 8, credits_charged: null, state: "needs_review" } } as unknown as ActionRow;
  assert.equal(requester(user), "Reader A (reader-a)");
  assert.equal(credits(user), "8 quoted · Needs review");
});

test("only /admin paths are Admin screens", () => {
  assert.equal(adminScreen("/admin"), "users");
  assert.equal(adminScreen("/admin/"), "users");
  assert.equal(adminScreen("/admin/credits"), "credits");
  assert.equal(adminScreen("/admin/actions/"), "actions");
  assert.equal(adminScreen("/admin/policy"), "policy");
  assert.equal(adminScreen("/admin/registrations"), "registrations");
  assert.equal(adminScreen("/admin/usage"), "usage");
  for (const path of ["/", "/analyses", "/administration", "/admin/unknown", "/library/admin", "/admin/users/x"]) {
    assert.equal(adminScreen(path), null, path);
  }
});

test("reads are GETs, writes carry the admin header, and replies must be admin payloads", async () => {
  const seen: { url: string; init?: RequestInit }[] = [];
  const original = globalThis.fetch;
  let reply: unknown = { contract: "admin-api-0.4", users: [] };
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    seen.push({ url, init });
    return new Response(JSON.stringify(reply), { status: 200 });
  }) as typeof fetch;
  try {
    assert.equal((await adminGet(adminPaths.users)).state, "ready");
    assert.equal(seen[0].init?.method, undefined);
    reply = { contract: "user-api-0.1" };
    assert.equal((await adminGet(adminPaths.users)).state, "error");
    reply = { contract: "admin-api-0.3", users: [] };  // The previous version, before the News desk, is not read.
    assert.equal((await adminGet(adminPaths.users)).state, "error");
    reply = { contract: "admin-api-0.4" };
    await adminPost(adminPaths.user("u-1/2", "credits"), { kind: "grant" });
    const post = seen.at(-1)!;
    assert.equal(post.url, "/api/admin/users/u-1%2F2/credits");
    assert.equal(post.init?.method, "POST");
    assert.equal((post.init?.headers as Record<string, string>)[ADMIN_HEADER], "1");
  } finally {
    globalThis.fetch = original;
  }
  assert.notEqual(newKey(), newKey());
  assert.match(newKey(), /^key-[0-9a-f]{32}$/);
});

test("every Admin read and write names the administrator the page was opened for", async () => {
  const seen: (RequestInit | undefined)[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = (async (_url: string, init?: RequestInit) => {
    seen.push(init);
    return new Response(JSON.stringify({ contract: "admin-api-0.4" }), { status: 200 });
  }) as typeof fetch;
  try {
    bindAdminAccount("u-0000000000000001");
    await adminGet(adminPaths.users);
    await adminPost(adminPaths.policy, {});
    bindAdminAccount(null);
    await adminGet(adminPaths.users);
  } finally {
    globalThis.fetch = original;
    bindAdminAccount(null);
  }
  const named = seen.map((init) => (init?.headers as Record<string, string>)[ACCOUNT_HEADER] ?? null);
  assert.deepEqual(named, ["u-0000000000000001", "u-0000000000000001", null]);
});

// The operator's selected pilot terms, as GET /api/admin/policy serves them (second_order/credit_terms.py).
const PILOT: PolicyPreset = { preset: "pilot-flat-1", label: "Selected pilot terms: flat points by Effort", note: "…",
  credits: { base: 10, per_1k_input_tokens: 0, per_1k_output_tokens: 0 },
  efforts: { low: { extra_credits: 0 }, medium: { extra_credits: 5 }, high: { extra_credits: 10 },
             xhigh: { extra_credits: 15 }, max: { extra_credits: 20 } } };
const EMPTY = { base: "", per_1k_input_tokens: "", per_1k_output_tokens: "", max_request_usd: "", quote_valid_seconds: "" };

test("a preset fills the rates and Effort extras, never the planning limit or the quote validity", () => {
  assert.equal(presetPoints(PILOT), "low 10 · medium 15 · high 20 · xhigh 25 · max 30");
  const fresh = presetDraft(PILOT, ["low", "medium", "high", "xhigh", "max"], null, EMPTY);
  assert.deepEqual(fresh.enabled, { low: "0", medium: "5", high: "10", xhigh: "15", max: "20" });
  assert.deepEqual(fresh.rates, { base: "10", per_1k_input_tokens: "0", per_1k_output_tokens: "0", max_request_usd: "",
                                  quote_valid_seconds: "" });  // Left for the administrator: no limit was selected.
  const current = { max_request_usd: 0.5, quote_valid_seconds: 600 } as Policy;
  const kept = presetDraft(PILOT, ["low", "high"], current, { ...EMPTY, quote_valid_seconds: "900" });
  assert.deepEqual(kept.enabled, { low: "0", high: "10" });  // Only what this model accepts.
  assert.equal(kept.rates.max_request_usd, "0.5");  // The active version's limit, retained.
  assert.equal(kept.rates.quote_valid_seconds, "900");  // What the administrator typed wins.
});

test("the initial allocation is offered only to an approved account with nothing allocated", () => {
  const user = { role: "user", status: "active", allocated: false, daily: { limit: null } } as unknown as AdminUser;
  assert.equal(offersInitialAllocation(user), true);
  assert.equal(offersInitialAllocation({ ...user, allocated: true }), false);
  assert.equal(offersInitialAllocation({ ...user, daily: { ...user.daily!, limit: 3 } }), false);
  for (const status of ["pending", "rejected", "disabled"] as const) {
    assert.equal(offersInitialAllocation({ ...user, status }), false, status);
  }
  assert.equal(offersInitialAllocation({ ...user, role: "admin" }), false);
});

test("what waits is read from the users list: registrations to decide, active accounts with nothing allocated", () => {
  const row = (username: string, status: AdminUser["status"], allocated: boolean, limit: number | null, role = "user") =>
    ({ user_id: `u-${username}`, username, display_name: `${username} (synthetic)`, role, status, allocated,
       daily: { limit } }) as unknown as AdminUser;
  const users = [row("admin", "active", false, null, "admin"), row("ana", "pending", false, null),
    row("ben", "active", false, null), row("cai", "rejected", false, null), row("dee", "active", true, 3),
    row("eve", "active", true, null), row("fay", "disabled", false, null), row("gus", "pending", false, null)];
  const { waiting, unallocated } = needsAttention(users);
  assert.deepEqual(waiting.map((user) => user.username), ["ana", "gus"]);
  assert.deepEqual(unallocated.map((user) => user.username), ["ben"]);  // Not an admin, a partial or a disabled account.
  assert.deepEqual(needsAttention([]), { waiting: [], unallocated: [] });
  assert.deepEqual(users.filter(unapproved).map((user) => user.username), ["ana", "cai", "gus"]);
  assert.equal(count(1, "registration is", "registrations are"), "1 registration is");
  assert.equal(count(2, "registration is", "registrations are"), "2 registrations are");
});

test("decisions name the administrator; an unknown account keeps its recorded ID", () => {
  const users = [{ user_id: "u-913e58027128cd72", display_name: "admin (synthetic)" }] as AdminUser[];
  assert.equal(nameOf("u-913e58027128cd72", users), "admin (synthetic)");
  assert.equal(nameOf("u-0000000000000000", users), "u-0000000000000000");
  assert.equal(nameOf("u-913e58027128cd72", []), "u-913e58027128cd72");
});

test("/admin?manage=<username> opens one account's panel; anything else opens none", () => {
  assert.equal(manageHref("ben.approved"), "/admin?manage=ben.approved");
  assert.equal(manageHref("a b&c"), "/admin?manage=a%20b%26c");
  assert.equal(adminScreen(new URL(manageHref("ben"), "http://x").pathname), "users");
  assert.equal(manageTarget("?manage=ben.approved"), "ben.approved");
  assert.equal(manageTarget(new URL(manageHref("a b&c"), "http://x").search), "a b&c");
  for (const search of ["", "?", "?manage=", "?other=ben"]) assert.equal(manageTarget(search), null, search);
  assert.equal(typeof manageTarget("?manage=%E0%A4%A"), "string");  // A malformed escape never throws.
});

test("a usage-limits form starts empty and never publishes a missing value as zero", () => {
  const empty = emptyUsageForm();
  assert.ok(Object.values(empty).every((value) => value === ""));
  const draft = usageDraft(empty);
  assert.ok([...Object.values(draft.account), ...Object.values(draft.server)].every((value) => value === null));
  assert.equal(JSON.stringify(usageDraft(empty)).includes(":0"), false);
  const typed = { ...empty, sources_per_day: " 25 ", max_source_bytes: "5.5", requests_per_minute: "-1",
                  refresh_cooldown_seconds: "0" };
  const read = usageDraft(typed);
  assert.equal(read.account.sources_per_day, 25);
  assert.equal(read.account.max_source_bytes, null);
  assert.equal(read.account.requests_per_minute, null);
  assert.equal(read.server.refresh_cooldown_seconds, 0);  // A typed zero is the administrator's choice.
});

test("a published version can start the next one, unchanged", () => {
  const limits: UsageLimits = {
    account: { searches_per_day: 1, imports_per_day: 2, sources_per_day: 3, preparations_per_day: 4, max_sources: 5,
               max_source_bytes: 6, requests_per_minute: 7, concurrent_requests: 8 },
    server: { publication_fetches_per_day: 9, refreshes_per_day: 10, refresh_cooldown_seconds: 11 },
  };
  assert.deepEqual(usageDraft(usageFormFrom(limits)), limits);
});

test("today's use says the limit, or that none is set", () => {
  assert.equal(allowance({ used: 3, limit: 10 }), "3 of 10");
  assert.equal(allowance({ used: 0, limit: 0 }), "0 of 0");
  assert.equal(allowance({ used: 1234, limit: null }, " bytes"), "1,234 bytes · no limit set");
  assert.equal(adminPaths.usagePolicy, "/api/admin/usage-policy");
  assert.equal(adminPaths.usage, "/api/admin/usage");
});
