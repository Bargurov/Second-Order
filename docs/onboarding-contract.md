# Onboarding contract (onboarding-api-0.1) and the user-api-0.2 amendment

Status: **foundation** (branch `entry/onboarding-logic`). It fixes the visitor, registration and credit-explanation
behavior that the public pages are built against, and the amendment to the active-user contract
(`docs/admin-user-contract.md`). The foundation commit (`2f863d0`) published this contract with the server already
answering in user-api-0.2 (section 5); the next commit implements registration, the decisions, the store's registration
tables and the public routes, and `tests/test_registration.py` checks the real server against the fixtures. A
mock-backed page proves the page only, never server enforcement.

Self-registration extends the existing accounts store: a registration is an ordinary `user` account that cannot sign
in until an administrator approves it. There is no second identity, session or billing system, no e-mail, payment,
hosting or password reset in this slice.

## 1. Account lifecycle

The server derives one status per account. A client never sends a status, role, credit, limit or owner.

| Status | How it arises | Can sign in | Research routes | Credits, daily limit, ownership |
| --- | --- | --- | --- | --- |
| `pending` | public registration | no (see section 4) | no | refused (`account_not_approved`) |
| `rejected` | an administrator rejected the registration | no | no | refused |
| `active` | an administrator approved the registration, or created the account (as before) | yes | per role | allowed (explicit admin actions) |
| `disabled` | an administrator deactivated an active account (as before) | no (`invalid_credentials`, as before) | no | allowed, as before |

- Approval and rejection are one decision per registration, made only by an administrator, with a reason, recorded
  durably with the administrator and the time. A decision never changes; a second or concurrent decision is refused
  with the one that applied (`409 already_decided`). Rejection is final for that username, which stays reserved.
- Approval only activates the account. It grants no credits, sets no daily limit, assigns no record and issues no
  quote. Those stay separate, explicit, attributed admin actions (admin-api, section 6).
- A pending or rejected account is never activated through the status action (`409 not_approved`): approval is the only
  way in. Active and disabled accounts, and every account created before this contract, keep their behavior and IDs.
- A registration is created with the `user` role only. No route, field or decision makes it an administrator.
- The store enforces this too: triggers refuse a registration's activation without an approval, and any credit entry,
  daily limit, record owner, quote or attempt for a registration that is not approved. A store made before this
  contract (`accounts-1`) is upgraded by the operator with `python -m second_order accounts upgrade`, which adds the
  registration tables and keeps every existing row; a server refuses to start on an unupgraded store.

## 2. Credits in plain terms

The rules below are the server's own wording (`rules` in section 3) and hold for every policy:

- A credit is one point of application usage on this server. It has no fixed money value and cannot be bought, sold or
  exchanged here.
- Before any analysis runs you get a quote: the exact number of points for that prepared analysis, its Effort and its
  source, under one credit-policy version, valid until a stated time. Nothing runs until you approve that quote.
- Approving reserves the quoted points and one run of today's daily allowance. When a result is recorded the quoted
  points are charged; if nothing was sent they are returned. If the server cannot tell whether a run was sent, the
  points stay held until an administrator settles them. You are never charged more than the quote you approved.
- The daily allowance counts new runs per calendar day; it is separate from points. A run uses one allowance slot
  whatever its points; a run that was returned releases its slot.
- Points do not buy a running time or a better result. Higher Effort lets the analysis spend more of its output
  allowance on reasoning and can need more points.
- Reading, reviewing and exporting saved results, adding a source, preparing an analysis and asking for a quote use no
  points and no allowance.

The numbers come only from the server: the active policy's quotes and the examples in section 3. A page must not show a
price, a points-per-analysis equivalence or rates that the server did not return. The operator's selected pilot terms
are an Admin preset, not active terms: a page shows them only when the active policy quotes them, and an account's
balance and limit only as the account reports them.

## 3. Public endpoints

Both are public (no session needed). Replies carry `"contract": "onboarding-api-0.1"`; refusals use the error shape of
the user contract (`{contract, code, detail, ...}`). The write needs this server's own page: its `Origin`,
`Sec-Fetch-Site` same-origin when sent, `application/json` and `X-Second-Order-Session: 1`. Both answer
`503 accounts_unavailable` on a server without accounts.

### `GET /api/public/credit-terms`

```json
{"contract": "onboarding-api-0.1", "state": "configured", "detail": null, "policy_version": "credit-policy-1",
 "efforts": [{"effort": "low", "label": "Low"}, {"effort": "medium", "label": "Medium"}, {"effort": "high", "label": "High"}],
 "effort_note": "Higher Effort lets the analysis spend more of its output allowance on reasoning. ...",
 "size_note": "Longer sources need more points: about one more point for each 2,000 characters of plain English text. Characters of other scripts count more (Hebrew letters about twice as much, emoji about four times), and your own quote gives the exact number.",
 "examples": [{"example": "short", "label": "Short synthetic source", "characters": 2000,
               "quotes": [{"effort": "low", "credits": 7}, {"effort": "medium", "credits": 8}, {"effort": "high", "credits": 9}]},
              {"example": "medium", "...": "..."}, {"example": "long", "...": "..."}],
 "rules": ["A credit is one point of application usage on this server. ...", "..."]}
```

(Numbers from the synthetic test policy of the fixtures, not a tariff.)

- `state`: `configured`, `no_credit_policy` or `no_effort_enabled`. Otherwise `policy_version` is null, `efforts` and
  `examples` are empty and `detail` says why ("No credit terms are set on this server yet.").
- `examples`: three fixed SYNTHETIC sources, always in this order (`short` 2,000, `medium` 12,000 and `long` 48,000
  characters of plain text), each quoted at every offered Effort, in order, by the same estimator and formula a real
  quote uses, under the active policy at the time of the read. They are the quotes this server would issue now for those synthetic sources; a
  user's own source gets its own quote. They change when the policy changes, so a page must read them, never copy them.
- `size_note` is derived from the active policy (a policy with no size rate says size does not change the quote).
  Size is measured as the UTF-8 bytes of the saved request, as the quote measures it: one byte per plain English
  character, two per Hebrew letter, four per emoji. The 50,000-character source limit is therefore not one size: the
  same number of characters can need very different points, although any script fits the form (user contract,
  section 6, Source).
- `quote_valid_seconds`: how long a quote stays valid under the active policy (null when not configured).
- No field carries money, a currency, a model or provider name, a token count or a planning estimate.

### `POST /api/public/registrations`

Body, exactly these fields: `{"username", "display_name", "password", "note"}`. `username` follows the existing
account rule (3 to 40 lowercase letters, digits, dots, hyphens or underscores, starting with a letter or digit);
`display_name` 1 to 80 characters; `password` 10 to 256 characters; `note` 0 to 500 characters for the administrator
(may be empty). None may contain control characters. Any other field (a role, status, credits, limit, owner, user ID)
refuses the whole body.

| Reply | When |
| --- | --- |
| `201 {contract, duplicate: false, registration: Registration}` | A pending account was created. |
| `200 {contract, duplicate: true, registration: Registration}` | The username is already a pending registration with this password (a resubmission or a lost reply). Nothing new was recorded; the reply shows the registration as first recorded. |
| `409 username_unavailable` | The username belongs to any other account or is reserved. One message whatever that account's status or role. |
| `422 invalid_registration` | A field breaks its rule; `field` names it (`username`, `display_name`, `password` or `note`) and `detail` states the rule, never another account. |
| `422 invalid_request` | The body is not exactly the four fields, or not JSON. |
| `413 payload_too_large`, `403 forbidden`, `503 accounts_unavailable`, `500 internal_error` | As in the user contract. |

No cookie is set and nothing is sent anywhere. Registration:

```json
{"username": "reader-c", "display_name": "Reader C", "status": "pending", "submitted_at": "2026-10-14T09:30:00+00:00",
 "decided_at": null, "detail": "Your registration is waiting for an administrator's approval. Sign in later to see its status."}
```

`status` is `pending` or `rejected` (an approved account simply signs in). `decided_at` is null while pending. The
administrator's reason is internal and never shown; `detail` is user-safe text. The reply never carries a user ID,
role, password, credits or limit.

A refusal below 500 means nothing was recorded. A lost reply or a 5xx proves nothing: submitting the same form again is
safe, because a pending registration with the same username and password answers as a duplicate.

## 4. Session and the registrant's own status (user-api-0.2)

There is no session for a pending or rejected account. A registrant sees their status by signing in:

- `POST /api/session/login` with the right password of a pending or rejected registration answers
  `403 registration_pending` or `403 registration_rejected` with `registration` (section 3). No cookie is set.
- A wrong password, an unknown username or a disabled account answers `401 invalid_credentials`, one message for all,
  exactly as before. Status is never available by username alone.
- An approved account signs in as any active user. `GET /api/session` is unchanged; a registrant is `signed_out`.

## 5. Amendment: user-api-0.2

Changes from user-api-0.1 (`docs/admin-user-contract.md` section 12):

1. Every `/api/session` and `/api/user/*` reply carries `"contract": "user-api-0.2"`. Readers also accept a
   `user-api-0.1` payload: 0.2 only adds codes, reasons and fields, so a 0.1 payload is a valid 0.2 payload.
2. New error codes: `registration_pending` and `registration_rejected` (403, sign-in only, extra field `registration`).
3. `Account.analysis.reason` gains `no_credits_allocated` (approved, but the administrator has recorded no credit
   entry for the account yet) and `no_credits_available` (credits were allocated, none are available now; held credits
   are reported in `credits.held`). The order, when several apply: `sending_disabled`, `no_credit_policy`,
   `no_effort_enabled`, `no_daily_limit`, `no_credits_allocated`, `no_credits_available`.
4. Additive: `Account.analysis.reasons`, every applicable reason in that order as `{reason, detail}` (empty when
   available; its first entry is `reason`). A page can show every missing step at once.

Nothing else in the user contract changes: quotes, runs, settlement, reviews, exports and every refusal keep their
meaning. `analysis.available` still describes the server's state; quote and run recheck everything.

## 6. Admin additions (admin-api-0.1, additive)

| Operation | Method and path |
| --- | --- |
| Registrations (filter by status) | `GET /api/admin/registrations?status=pending` |
| Approve or reject one | `POST /api/admin/registrations/{user_id}/decision` `{decision: "approve" or "reject", reason}` |
| Preview a policy (writes nothing) | `POST /api/admin/policy/preview` `{policy}` |

- `GET /api/admin/users` rows gain `status` and `registration` (null for accounts an administrator created; otherwise
  `{submitted_at, note, decision}`).
- A decision answers `201 {applied: true, decision, user}`; `409 already_decided` carries the decision that applied;
  `404 not_found` for an account that is not a registration.
- Credits, daily limits and ownership for a pending or rejected account: `409 account_not_approved`. The status
  action on one: `409 not_approved`.
- Policy preview validates a policy body exactly as a new version would and returns the section 3 examples under it,
  with the admin-only planning estimate and whether `max_request_usd` would refuse each. Activation stays the
  existing explicit `POST /api/admin/policy` (a new version, with a reason). The server still ships with no policy,
  grant or limit and applies none on the operator's behalf: the selected pilot terms (flat 10 to 30 points by Effort;
  100 credits once and 3 analyses a day) are Admin presets that fill a draft or a form (admin-user-contract.md,
  section 10).

## 7. Front-end mount boundary

- Client build (`client.html` → `src/shell/clientMain.tsx`): the shell reads `GET /api/session`. A signed-in user
  gets `ClientApp` (unchanged props). A signed-out visitor gets `PublicApp(props: PublicAppProps)` from
  `src/public/PublicApp.tsx`. The Admin build keeps the shell's plain sign-in form for a session that ends.
- `PublicAppProps` (in `src/contracts/onboarding.ts`):

  ```ts
  interface PublicAppProps {
    reason: SignedOutReason;                  // not_signed_in, session_expired or signed_out
    onSignedIn: (session: Session) => void;   // hand the signed-in session to the shell, which mounts the role's app
  }
  ```

- Paths, for each reader (the server sends the Client build for every non-API path to both):

  | Path | Signed-out visitor (`PublicApp`) | Signed-in user (`ClientApp`) |
  | --- | --- | --- |
  | `/` | landing page | the user's analyses (unchanged) |
  | `/register` | registration | "You are signed in", with a link to the analyses |
  | `/sign-in` | sign-in | "You are signed in", with a link to the analyses |
  | `/credits` | how credits work (public terms) | the user's credits: public terms and their own allowance |
  | `/sources`, `/sources/new`, `/sources/<id>`, `/analyses/<id>` and any other path | sign-in, staying on the address | unchanged (research bookmarks and Not found as before) |

  After a sign-in that started on `/`, `/register` or `/sign-in`, PublicApp navigates to `/` before calling
  `onSignedIn`; on any other path it stays there, so a bookmarked research page opens after sign-in, as before.
  Admins keep the Admin build at every path, as before.
- There is no session, and so no signed-in page, for a pending or rejected registration: a sign-in attempt with the
  right password returns the registration's status (section 4), which PublicApp shows signed out. A rejected username
  cannot register again; the person can register under another username.
- PublicApp calls only `GET /api/session`, `POST /api/session/login`, `GET /api/public/credit-terms` and
  `POST /api/public/registrations`, through `src/contracts/user.ts` and `src/contracts/onboarding.ts`. It imports no
  Admin module. It never stores a password (not in drafts, storage, logs or a recovery screen), and a registration or
  sign-in is sent only on the person's explicit submit, never retried automatically.
- The server is unchanged here: signed-out visitors and users already receive the Client build for every non-API path.
- The foundation's `src/public/PublicApp.tsx`, `src/client/components/CreditsPage.tsx` and the signed-in notice are
  SCAFFOLDING: the smallest working pages, so the boundary can be exercised. The UX conversation replaces them.

## 8. Fixtures

SYNTHETIC fixtures, generated from the real server over a temporary store with the tests' synthetic policy:
`onboarding-credit-terms.json`, `onboarding-credit-terms-none.json`, `onboarding-registration-created.json`,
`onboarding-registration-duplicate.json` and `onboarding-errors.json` (every onboarding refusal), plus
`user-contract-account-unallocated.json` and the two registration refusals in `user-contract-errors.json`.
`frontend/tests/onboarding-contract.test.ts` reads each one; the backend tests check the real server's payloads
against their structure and the readers (`tests/test_user_research.py` for user-api-0.2 from this commit on, and the
registration tests for the onboarding fixtures once the routes exist). The numbers in them are synthetic and are not a
tariff.

## 9. Ownership from the foundation commit

| Owner | Files |
| --- | --- |
| UX conversation | `frontend/src/public/**`, `frontend/src/client/**`, `frontend/src/shell/Shell.tsx`, `frontend/src/shell/SignIn.tsx`, `frontend/src/shell/shell.css`, its dedicated tests and browser checks (`frontend/tests/client-*`, `frontend/tests/public-*`, `frontend/tests/browser/client-*`, `frontend/tests/browser/public-*`) and their fixtures (`client-*`, `public-*`) |
| Logic conversation | `second_order/**`, backend `tests/**`, `frontend/src/contracts/**`, `frontend/src/admin/**`, `frontend/src/shell/clientMain.tsx`, `frontend/src/main.tsx`, `frontend/src/router.tsx`, global CSS, package/build configuration and HTML entries, contract documents, README and SPEC, `user-contract-*` and `onboarding-*` fixtures and their tests, the Admin check and the joint checks (`frontend/tests/browser/admin-*.mjs`, `tests/integration_controls.py`, `tests/review_browser_server.py`) |

Shell.tsx keeps the boundary in section 7 (session check, role check, one reload toward the right build). A change
either side needs from the other is a small integration request through the operator; nobody edits the other's files.
