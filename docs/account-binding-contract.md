# Account binding: user-api-0.3 and admin-api-0.2

Status: **checkpoint for the Client** (branch `admin/ops-polish`). The server enforces it and the shared request helpers
in `frontend/src/contracts/user.ts` send it; the Client adopts it by building its helpers with its account (section 5).
It amends `docs/admin-user-contract.md` (user-api-0.2 with `docs/onboarding-contract.md`) and admin-api-0.1. Payload
shapes do not change.

## 1. Why

A browser keeps one session cookie for all its tabs. A tab opened for reader-a and left open while another tab signs out
and signs in as reader-b sends reader-b's cookie with its next request. Before this amendment the server could not tell:
the old tab's unsaved source was saved into reader-b's account, and the old tab then showed reader-b's records under
reader-a's name (QA-2, reproduced on the real server). A check the page makes before writing cannot close this, because
the sign-in elsewhere can happen between that check and the write. The server must know which account the request was
made for.

## 2. The binding

A page names the account it was opened for in one request header:

```
X-Second-Order-Account: <user_id>
```

`<user_id>` is the `user.user_id` of the session the page was opened with (`GET /api/session` or the sign-in reply). It
is not a secret and grants nothing: the session cookie still decides who is asking, and the server compares the two.

| Request | Binding |
| --- | --- |
| Every write (`POST`) to `/api/user/*` | **required** |
| Every write (`POST`) to `/api/admin/*` | **required** |
| Reads (`GET`) of `/api/user/*`, `/api/admin/*` and the operator's routes; operator writes | checked when sent |
| `POST /api/session/logout` | checked when sent; not required |
| `GET /api/session`, `POST /api/session/login`, `GET /api/public/credit-terms`, `POST /api/public/registrations` | ignored |
| Pages and built files | ignored |
| A server without an accounts store (local-operator mode) | ignored |

"Checked" means: when the header is sent, it must name the session's account. A header sent twice, or empty, names no
account and is refused like a mismatch.

## 3. Refusals

Both are in the route's contract shape `{contract, code, detail}` and carry nothing else: no account, record or field
of either account. Both are decided before the route runs, so the request read and wrote nothing (no row, no record
file, no quote, reservation, send or review).

| Status | Code | When | Default `detail` |
| --- | --- | --- | --- |
| 401 | `account_changed` | the binding names another account than the session's (or the header is repeated or empty) | "This page was opened for another account than the one now signed in on this browser. Nothing was read or changed. Reload the page to continue as the account now signed in." |
| 428 | `account_binding_required` | a required binding is missing | "This request did not say which account it was made for, so nothing was changed. Reload the page and try again." |

Order: a missing or expired session is refused first (401 `not_signed_in` or `session_expired`, unchanged); then a
mismatched binding (401 `account_changed`); then the role (403 `forbidden`, unchanged); then a missing required binding
(428). So a page opened for a user meets an administrator's session as a changed account, not a forbidden page.

Signing out does not need the binding: ending a session writes nothing to any account. When a page sends it and it no
longer matches, sign-out is refused and the session stays, so an old tab does not end someone else's session unseen.

## 4. What is unchanged

- Payloads, fixtures and every other code. Replies on the user routes say `"contract": "user-api-0.3"`, admin replies
  `"admin-api-0.2"`. The readers in `frontend/src/contracts/user.ts` accept user-api-0.1, 0.2 and 0.3.
- Host, Origin, `Sec-Fetch-Site`, Content-Type and the route headers (`X-Second-Order-User: 1`,
  `X-Second-Order-Admin: 1`, `X-Second-Order-Session: 1`): still required exactly as before. The binding is in
  addition.
- A plain link (the export download) carries no header. An export of another account's analysis is Not Found, as
  before.
- Operator pages in the Admin build do not send the binding, so operator writes are checked only when a binding is sent.
  Two administrators in one browser could still act under each other's session on those pages; every Admin screen sends
  it.

## 5. What a page does (Client and Admin)

- Build the request helpers from the signed-in session: `userApi(fetch, { account: session.user.user_id })`. Every user
  read and write, and sign-out, then names the account; the session read and sign-in never do. An unbound
  `userApi()` can still read the session, sign in and register; its user writes are refused (428).
- On `account_changed` (helper `bindingRefusal(reply)`): stop. Do not adopt, render or keep acting on what the server
  now says about the account signed in, under the old account's name. Keep the old account's unsaved text bound to the
  old account (never submit it for, or restore it into, another account), and offer to reload or sign in again.
- On `account_binding_required`: the page was built without its account; reload. Never retry by itself.
- The Admin build binds itself: `bindAdminAccount(session.user.user_id)` in `AdminApp`, before any screen reads.

## 6. Tests

`tests/test_account_binding.py` reproduces QA-2 on the real application (a stale tab's source, preparation, quote, run
and review in another account are refused, with every store row, record file and the fake provider unchanged), walks
every write route for a mismatched and a missing binding, and checks reads, sign-out, the public routes and
local-operator mode. `frontend/tests/user-contract.test.ts` and `frontend/tests/admin-format.test.ts` check that the
helpers send the binding where the table above says, and read both refusals.

## 7. Change note

- user-api-0.3: the account binding (sections 2 to 5); codes `account_changed` and `account_binding_required`.
- admin-api-0.2: the same binding on every Admin read and write.
- A client built for user-api-0.2 reads 0.3 replies as another contract version and its user writes are refused (428)
  until it sends the binding: there is no fallback that accepts an unbound write.
