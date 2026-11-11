// Which account a Client tab acts for (src/client/identity.ts) and the announcements the browser's tabs exchange about
// the session they share (src/shell/sessionChannel.ts). A tab opened for one account stops once the browser is signed in
// to another: from another tab's announcement or from any reply that carries another account. Page rules only, against
// the SYNTHETIC fixtures; the server's own refusal of a request bound to another account is not proved here.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import type { Account } from "../src/contracts/user.ts";
import { afterAnnouncement, BOUND, isOwn, maySend, type Identity } from "../src/client/identity.ts";
import { readNews } from "../src/shell/sessionChannel.ts";

const load = <T>(name: string): T =>
  JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8"));
const readerA = load<Account>("user-contract-account");
const readerB = load<Account>("client-account-reader-b");
const A = readerA.user.user_id;
const B = readerB.user.user_id;
const ELSEWHERE: Identity = { state: "elsewhere" };
const STOPPED: Identity = { state: "stopped" };

test("the SYNTHETIC accounts are two different users", () => {
  assert.notEqual(A, B);
});

test("another tab signing the browser in to another account stops this tab from sending", () => {
  assert.deepEqual(afterAnnouncement(BOUND, A, B), ELSEWHERE);
  assert.equal(maySend(afterAnnouncement(BOUND, A, B)), false);
  assert.deepEqual(afterAnnouncement(ELSEWHERE, A, B), ELSEWHERE);
});

test("signing in again as the same account lifts the warning; signing out elsewhere is left to the server's 401", () => {
  assert.deepEqual(afterAnnouncement(ELSEWHERE, A, A), BOUND);
  assert.deepEqual(afterAnnouncement(BOUND, A, A), BOUND);
  // Signed out elsewhere: no other account acts here; this tab's next request is answered as signed out, and the
  // session-end recovery keeps what was typed.
  assert.deepEqual(afterAnnouncement(BOUND, A, null), BOUND);
  assert.deepEqual(afterAnnouncement(ELSEWHERE, A, null), ELSEWHERE);
});

test("a stopped tab stays stopped, whoever signs in elsewhere", () => {
  for (const signedIn of [A, B, null]) assert.deepEqual(afterAnnouncement(STOPPED, A, signedIn), STOPPED);
  assert.equal(maySend(STOPPED), false);
  assert.equal(maySend(ELSEWHERE), false);
  assert.equal(maySend(BOUND), true);
});

test("an account a reply carries is adopted only when it is this tab's own", () => {
  assert.equal(isOwn(readerA, A), true);
  assert.equal(isOwn(readerB, A), false);
  assert.equal(isOwn(readerA, B), false);
});

test("only a well-formed announcement is heard: a user_id or nobody, nothing else", () => {
  assert.deepEqual(readNews({ signedIn: A }), { signedIn: A });
  assert.deepEqual(readNews({ signedIn: null }), { signedIn: null });
  for (const noise of [undefined, null, "", A, 42, {}, { signedIn: "" }, { signedIn: 7 }, { signedIn: undefined },
                       { user: A }]) {
    assert.equal(readNews(noise), null, JSON.stringify(noise));
  }
});
