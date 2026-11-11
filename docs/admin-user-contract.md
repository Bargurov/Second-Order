# Admin and user contract (user-api-0.2)

Status: **implemented on the Admin branch** (see section 13). This document fixes the shared API the user Client is
built against. Version `user-api-0.2`. Any change is published as a versioned amendment (section 12) with updated
types and fixtures; neither side changes it silently.

**Current version: user-api-0.3 and admin-api-0.2**, which add the account binding: every user and administrator
write names the account its page was opened for, and a request bound to another account is refused before anything is
read or written. See [account-binding-contract.md](account-binding-contract.md). Payloads are unchanged.

## Changes in user-api-0.2 (amendment with the onboarding contract)

Public self-registration and the public credit terms are a separate contract, `onboarding-api-0.1`
(docs/onboarding-contract.md). It amends this one:

1. Replies carry `"contract": "user-api-0.2"`. Readers also accept `user-api-0.1` payloads, a subset of 0.2.
2. New sign-in refusals `403 registration_pending` and `403 registration_rejected`, for the right password of a
   registration that is not approved, with the registrant's own `registration` status (section 9). Nothing else about
   sign-in changes; a pending or rejected registration has no session.
3. `Account.analysis.reason` gains `no_credits_allocated` and `no_credits_available` (section 6), and the additive
   `Account.analysis.reasons` lists every reason that applies.
4. Admin (section 10, additive): account `status` and `registration`, the registrations list and decision, a
   policy preview that records nothing, and the operator's selected pilot terms as presets (`presets`,
   `allocation_presets`, each user row's `allocated`); credits, limits, ownership and the status action refuse a
   registration that is not approved.
5. A source's bounds are stated field by field (section 6, Source). Its text may have 50,000 characters in any script:
   the source route reads a form of up to 270,000 bytes. 0.1 limited it to 120,000 bytes, re-encoded with ASCII
   escapes (six bytes a Hebrew letter, twelve an emoji), so a source in another script was refused far below 50,000
   characters (`413 payload_too_large` or `422 invalid_source`). An unpaired surrogate escape is `422 invalid_source`
   instead of `500 internal_error`. No field or code changes.

The first flow is the evidence-first research analysis of a source the user supplies (see `research_analysis`). There is
no payment, checkout, hosting, data download or real model request in this milestone.

## 1. Roles, identity and ownership

- Two roles: `admin` and `user`. The server derives identity and role from the authenticated session on every request.
  A client never sends a role or a user ID that the server trusts; IDs in paths are checked against the session.
- Accounts are created by an admin (Admin screens) or, for the first admin only, by an explicit local command
  (`python -m second_order accounts add-admin --username NAME`, which prompts for the password; nothing is read from
  files, arguments or the environment).
- Every record a user creates (a source, its analyses, their reviews) is owned by that user. A user reads, quotes, runs,
  reviews and exports only records they own. A record owned by someone else answers exactly like a record that does
  not exist (`404 not_found`), so ownership cannot be probed.
- Existing operator records (captures, Tracker attempts, research requests and attempts, reviews, everything under
  `data/`) have no owner row and are **admin-owned**. Nothing is assigned to a user unless an admin explicitly assigns
  it (section 10, `POST /api/admin/ownership`), one capture at a time, with a reason; its existing analyses and reviews stay
  the operator's. Historical records are never rewritten; ownership lives beside them in the accounts store.
- An admin has every existing operator page and route, unchanged, plus the Admin screens. A user has only the Client
  and the `/api/user/*` routes.

## 2. Sessions and the local protections

- Sign-in sets one cookie, `second_order_session`: random, `HttpOnly`, `SameSite=Strict`, `Path=/`. The server stores
  only its SHA-256. Sessions end at sign-out or after an absolute lifetime (server setting, default 12 hours). The client
  never reads the cookie.
- The local protections stay: every route checks that the Host is a local address. Every write (`POST`) must come from
  this server's own page: the `Origin` must be this server's, `Sec-Fetch-Site` (when sent) `same-origin`, the body
  `application/json`, and a route-specific header must be `1`:
  - `X-Second-Order-Session: 1` for sign-in and sign-out,
  - `X-Second-Order-User: 1` for every `POST /api/user/*`,
  - `X-Second-Order-Admin: 1` for every `POST /api/admin/*`,
  - the existing headers (`X-Second-Order-Intake`, `-Research`, ...) for the existing operator routes.
- Route access is fail-closed: a route is admin-only unless it is listed as public (`GET /api/session`,
  `POST /api/session/login`, `POST /api/session/logout`, the sign-in page and its assets) or user
  (`/api/user/*`). A user calling any other API route gets `403 forbidden`; a signed-out caller gets `401`.
- Static assets: the server serves the Admin build (`frontend/dist/`) only to admin sessions and the Client build
  (`frontend/dist-client/`) to user sessions and to signed-out visitors (whose page is the sign-in form). The Client
  build contains no Admin module, model or provider name, price table or cost text.

### Server modes

| Mode | When | Behavior |
| --- | --- | --- |
| `accounts` | `python -m second_order serve` (the accounts store is `data/accounts/accounts.db` unless `--accounts` names another) | Sign-in required; roles and ownership enforced as above. |
| `local-operator` | only a server built in code without an accounts store (unit tests of existing operator routes, the existing browser checks' launcher) | No sign-in; every request is the local operator with the `admin` role, exactly as before this milestone; `/api/user/*` answers `503 accounts_unavailable`. |

`GET /api/session` reports the mode. No command-line option selects `local-operator`.

## 3. Conventions

- Every `/api/session` and `/api/user/*` response body carries `"contract": "user-api-0.2"` (readers also accept
  `user-api-0.1`).
- Times are ISO 8601 in UTC, written with `+00:00` or `Z` (`2026-10-14T09:30:00+00:00`, `2026-10-13T07:00:00Z`),
  sometimes with microseconds. `published_at_as_supplied` is exactly what the user typed, with its own offset.
- Credits are non-negative integers. No user payload contains a monetary amount, a currency, a model or provider name,
  a token count, a provider request/response ID, raw request or response bytes, an HTTP status of a provider call or an
  operational log line.
- IDs are opaque strings. `source_id` matches `^\d{8}T\d{12}Z-[0-9a-f]{12}$`; `analysis_id` matches
  `^[A-Za-z0-9._-]{1,160}$`; `quote_id` and `review_id` match `^[A-Za-z0-9_-]{8,80}$`. Clients must not parse them.
- Errors have one shape, for every status:

```json
{"contract": "user-api-0.2", "code": "daily_limit_reached", "detail": "A sentence for the user.", "resets_at": "..."}
```

  `detail` is user-safe text; some codes add fields (section 9). Unknown fields must be ignored by the Client;
  missing required fields make a payload unreadable (fail closed).

## 4. Effort

- The provider vocabulary is `low`, `medium`, `high`, `xhigh`, `max`. These are the `output_config.effort` levels the
  configured model (the research-analysis model) accepts, verified from the provider's documentation during
  implementation, without a live request.
- The admin's credit policy (section 8) enables a subset. Every level has the same output bound, 16,000 tokens (the
  existing research request's bound; the transport is one non-streaming request). The server offers only levels that
  are both verified and enabled; `GET /api/user/account` lists them in order. An empty list means
  analyses are unavailable (`reason: "no_effort_enabled"`).
- Labels the Client may show: `low` "Low", `medium` "Medium", `high` "High", `xhigh` "Extra high", `max` "Maximum".
  The server's `effort_note` is the only description: more effort lets the analysis spend more of its output allowance
  on reasoning; it does not promise a better result or a fixed running time.
- Effort is chosen **before** a request is prepared. Each (source, Effort) pair has its own immutable prepared request
  and `analysis_id`. Choosing another Effort prepares (or reopens) another analysis; it never edits a prepared or
  attempted one, and a quote for one analysis can never run another. There is no fallback to another level or model.

## 5. Session endpoints

### `GET /api/session` (public)

```json
{"contract": "user-api-0.2", "mode": "accounts", "state": "signed_in",
 "user": {"user_id": "u-…", "username": "reader-a", "display_name": "Reader A", "role": "user"},
 "expires_at": "2026-10-14T21:30:00+00:00"}
```

Signed out: `"state": "signed_out"`, `"user": null`, `"expires_at": null` and `"reason"` one of `not_signed_in`,
`session_expired`, `signed_out`. In `local-operator` mode the user is `{"user_id": "local-operator", "username":
"operator", "display_name": "Local operator", "role": "admin"}` and `expires_at` is null.

### `POST /api/session/login`

Body `{"username": "...", "password": "..."}` with `X-Second-Order-Session: 1`. `200` returns the signed-in session and
sets the cookie. `401 invalid_credentials` for an unknown user, a wrong password or an inactive account (one message for
all three).

### `POST /api/session/logout`

Body `{}`. `200` returns the signed-out session (`reason: "signed_out"`) and clears the cookie.

## 6. User endpoints

All require a `user` session (an admin session gets `403 forbidden`; no session `401`).

| Operation | Method and path | Body | Success |
| --- | --- | --- | --- |
| Account and entitlements | `GET /api/user/account` | – | `200` Account |
| Add a source | `POST /api/user/sources` | SourceForm | `201` `{contract, source: Source}` |
| List my sources | `GET /api/user/sources` | – | `200` `{contract, sources: SourceSummary[]}` |
| One source | `GET /api/user/sources/{source_id}` | – | `200` `{contract, source: Source, analyses: AnalysisSummary[]}` |
| Prepare an analysis | `POST /api/user/analyses` | `{"source_id", "effort"}` | `201` (new) or `200` (already prepared) `{contract, created, analysis: Analysis}` |
| List my analyses | `GET /api/user/analyses` | – | `200` `{contract, analyses: AnalysisSummary[]}` |
| One analysis | `GET /api/user/analyses/{analysis_id}` | – | `200` `{contract, analysis: Analysis}` |
| Get a credit quote | `POST /api/user/analyses/{analysis_id}/quotes` | `{}` | `201` `{contract, quote: Quote, account: Account}` |
| Approve and run | `POST /api/user/analyses/{analysis_id}/runs` | RunApproval | `201` `{contract, duplicate: false, analysis, account}`; a repeat of the same approval `200` `{… duplicate: true …}` |
| Save my review | `POST /api/user/analyses/{analysis_id}/reviews` | ReviewForm | `201` `{contract, review: Review, analysis: Analysis}` |
| Export | `GET /api/user/analyses/{analysis_id}/export` | – | `200` `{contract, exported_at, analysis: Analysis}` as an attachment |

Reads (`GET`) never prepare, quote, reserve, send, retry or write anything, and never consume credits or allowance.
Opening, reviewing or exporting a saved result consumes nothing.

### Account

```json
{"contract": "user-api-0.2",
 "user": {"user_id": "u-…", "username": "reader-a", "display_name": "Reader A", "role": "user"},
 "credits": {"available": 34, "held": 6},
 "daily": {"timezone": "Asia/Jerusalem", "day": "2026-10-14", "limit": 3, "used": 1, "remaining": 2,
           "resets_at": "2026-10-14T21:00:00+00:00"},
 "efforts": [{"effort": "low", "label": "Low"}, {"effort": "high", "label": "High"}],
 "effort_note": "…",
 "analysis": {"available": true, "reason": null, "detail": null}}
```

- `credits.available` can be spent now; `credits.held` is reserved by analyses still running or awaiting an
  administrator's review. Both are integers ≥ 0.
- `daily`: the configured quota time zone, today's quota day there, the user's daily analysis limit (`null` when none is
  set), new analysis runs counted against today (released reservations do not count), `remaining` (`null` when `limit`
  is null) and when the next day starts (DST-aware). An analysis keeps the quota day it was reserved on.
- `analysis.available` is false with a `reason` of `sending_disabled`, `no_credit_policy`, `no_effort_enabled`,
  `no_daily_limit`, `no_credits_allocated` (no administrator credit entry exists for the account yet),
  `no_credits_available` (credits were allocated but none are available now) or `account_inactive`, and a user-safe
  `detail`; when several apply, the first in that order is given, and `reasons` lists every one that applies as
  `{reason, detail}` (empty when available). It describes the server's state; the server checks everything again at
  quote and run time.

### Source

SourceForm: `{"headline", "source_url", "published_at", "source_text"}`. `published_at` must carry an explicit offset.
Each field has its own limit, counted in characters, never in bytes:

- `source_text`: up to 50,000 characters in any script, never truncated; more is `422 invalid_source`, naming the
  count. A character is a Unicode code point, as `Array.from(text).length` and Python's `len` count it, so an emoji
  drawn from several code points (a flag, a skin tone, a family) counts as several. UTF-8 stores a character in one to
  four bytes (English one, Hebrew two, Chinese three, most emoji four): 50,000 characters are 50,000 to 200,000 bytes,
  and the quote, which counts bytes, grows with them.
- `headline`: 1 to 1,500 characters on one line; `source_url`: an http(s) address of at most 2,083 characters.
- The body is UTF-8 JSON as a browser sends it, characters beyond ASCII unescaped, read up to 270,000 bytes: the
  earlier 120,000 plus three for each of the 50,000 characters. Every form within the field limits fits: text and
  headline at their limits in four-byte characters with the longest address take about 208,000 bytes. A larger body
  is refused unread, `413 payload_too_large`. Only escapes add bytes: JSON writes control characters other than tab, line feed and
  carriage return as six-byte escapes, so a text holding tens of thousands of them can exceed it, and a client that
  escapes every character as `\uXXXX` sends six bytes for each (twelve for an emoji).
- An unpaired surrogate escape (`\ud800` to `\udfff`) is not a character: `422 invalid_source`.

```json
{"source_id": "20261014T093000000000Z-0123456789ab", "headline": "…", "source_url": "https://…",
 "published_at": "2026-10-13T18:00:00+00:00", "published_at_as_supplied": "2026-10-13T21:00:00+03:00",
 "captured_at": "2026-10-14T09:30:00+00:00", "characters": 1234, "text": "…"}
```

SourceSummary has the same fields without `text`.

### Analysis

```json
{"analysis_id": "…", "effort": "high", "prepared_at": "…",
 "source": {Source with text},
 "state": "recorded", "state_detail": "…",
 "quote": null,
 "charge": {"credits_reserved": 6, "credits_charged": 6, "credits_returned": 0, "state": "charged",
            "quota_day": "2026-10-14"},
 "result": {Result} ,
 "result_sha256": "…64 hex…",
 "reviews": [Review, …],
 "retrospective": "…", "baseline": {"state": "not_supplied", "note": "…"}}
```

`state`:

| State | Meaning | `result` | `charge.state` |
| --- | --- | --- | --- |
| `prepared` | Prepared, never run. A quote may exist. | null | null (charge null) |
| `running` | Reserved and being sent: a worker still holds the attempt's execution lock, or it is less than 15 minutes old. | null | `held` |
| `recorded` | A response was recorded: `result` holds its outcome (which may be a decline or an incomplete or invalid reply). | Result | `charged` (`under_review` if the server stopped between recording and settling; `returned` if an administrator returned the credits) |
| `failed` | The analysis service returned an error. Its billing is uncertain, so the credits stay held for an administrator. | null | `under_review`, later `charged` or `returned` |
| `unresolved` | The run stopped without recording an outcome (a lost reply or a stopped server): no worker holds the attempt's execution lock and at least 15 minutes have passed. Whether it was sent is in `state_detail`. It is never sent again; the credits stay held until an administrator resolves it (or, if an administrator charged or returned it before its send, as resolved). | null | `under_review`, later `charged` or `returned` |
| `not_sent` | The run was reserved but nothing was sent, so the credits and the daily slot were returned. This prepared request cannot be run again. | null | `returned` |

`charge` is null before any run. `credits_charged` and `credits_returned` are null while `held` or `under_review`;
`credits_charged + credits_returned = credits_reserved` once settled, and `credits_charged ≤ credits_reserved` always.

`quote` is the latest quote issued to this user for this analysis while the analysis is `prepared` (null otherwise).

### Result

```json
{"outcome": "analysis", "note": "…", "recorded_at": "…",
 "analysis": {"established": [{"number": 1, "statement": "…", "basis": "data",
                               "quotes": [{"text": "…", "match": "exact", "start": 0, "end": 42, "paragraphs": [1],
                                           "source_passage": "…", "occurrences": 1}]}],
              "interpretation": {"kind": "finding", "text": "…", "based_on": [1]},
              "assumptions": ["…"], "competing_explanations": [{"explanation": "…", "would_distinguish": "…"}],
              "missing_information": ["…"], "tests": [{"check": "…", "counts_against_if": "…"}]},
 "explanation": null}
```

- `outcome`: `analysis`, `no_additional_finding`, `declined`, `incomplete` or `invalid`. `analysis` is present only for
  the first two; `explanation` only for `declined` (the reply's own words, which may be null).
- Quote locators are computed by the server against `source.text` (`start`/`end` are code-point offsets,
  `paragraphs` 1-based); a Client may check that `source.text.slice(start, end)` (by code points) equals
  `source_passage` and refuse the result otherwise.
- `result_sha256` is the SHA-256 of the canonical JSON of `result` as the server built it; a review names it.

### Quote

```json
{"quote_id": "q-…", "analysis_id": "…", "effort": "high", "credits": 6, "policy_version": "credit-policy-2",
 "issued_at": "…", "expires_at": "…", "state": "active"}
```

`state`: `active`, `expired`, `used` or `superseded` (the policy or the Effort menu changed). A new quote supersedes
none of the earlier ones explicitly, but only an `active` quote can be approved. A quote binds the signed-in user, the
analysis (its exact saved request SHA-256 server-side), the Effort, the policy version, the credit amount and the
expiry.

### RunApproval

```json
{"quote_id": "q-…", "effort": "high", "credits": 6, "approve": true}
```

`approve` must be `true`, and `effort` and `credits` must repeat the quote exactly: the approval is the user's visible
credit decision. Immediately before any provider contact the server rechecks the session, ownership, the quote (user,
analysis, request SHA-256, Effort, policy version, credits, expiry, unused), the Effort's availability, the admin's
policy, the balance and the daily limit, then reserves the credits, today's daily slot and the analysis's single attempt
in one durable transaction. The run's response returns when the attempt is recorded (it can take minutes); meanwhile
`GET` of the analysis shows `running`.

Repeating an approval with the same `quote_id` (double click, lost reply, another tab) returns `200` with
`duplicate: true` and the analysis's current state: no second reservation, debit or provider call.

### Review

ReviewForm: `{"parent_review_id": null | "<review_id>", "result_sha256": "<the result_sha256 the page shows>",
"status": null | "needs_revision" | "human_reviewed", "notes": "…"}` (notes at most 20,000 characters; a status or
notes required).

```json
{"review_id": "…", "sequence": 1, "parent_review_id": null, "saved_at": "…", "status": "human_reviewed",
 "notes": "…", "result_sha256": "…", "reviewer": {"user_id": "u-…", "display_name": "Reader A"}}
```

Reviews are append-only versions; `parent_review_id` must name the latest version (null for the first).

### AnalysisSummary

```json
{"analysis_id": "…", "source": {"source_id": "…", "headline": "…", "published_at": "…"}, "effort": "high",
 "prepared_at": "…", "state": "recorded", "outcome": "analysis", "review_status": "human_reviewed",
 "credits_charged": 6}
```

`outcome` is null unless `recorded`; `review_status` is the latest review's status (null without one);
`credits_charged` is null until settled.

## 7. Credit quotes, reservations and settlement

1. Quote (`POST …/quotes`): needs a server that can send (else `503 sending_disabled`), an active credit policy that
   enables the analysis's Effort and an analysis without an attempt. The server computes the integer credits from the policy (section 8) and the saved request's size and Effort,
   stores the quote and returns it. Quoting does not reserve anything.
2. Run (`POST …/runs`): the checks above, then **one transaction** (SQLite `BEGIN IMMEDIATE`, safe across tabs,
   threads and server processes) that inserts the attempt (unique per analysis and per quote), the credit hold (a
   negative ledger entry of the quoted credits; the available balance can never go negative) and the daily slot (counted
   per user per quota day against the limit). Only then is the attempt folder reserved and the exact saved request bytes
   copied and sent once, with no retry, fallback or model substitution (the existing one-attempt safeguards).
3. The worker then takes the attempt's **execution lock** (an operating-system file lock per attempt, beside the
   accounts store) and holds it until the attempt is settled. While it holds it, nobody else can resolve the attempt,
   however long the send takes; the operating system releases it when the worker's process ends (a crash, a stop, a
   restart). Under the lock the send is recorded in the accounts store as started, in a transaction that refuses if the
   attempt was already resolved, before the transport is called. A returned or charged attempt is therefore never sent.
4. Settlement is idempotent (at most one resolution per attempt, enforced by the store):
   - a recorded provider response of any outcome → **charged** the quoted credits (policy `settlement: "quoted"`);
   - nothing sent (the worker, still holding the lock, sees no recorded send start) → **returned**: the credits and the
     daily slot are released once, with the reason recorded, unless the attempt was already resolved;
   - a provider error, a lost reply, or a send with no recorded outcome → **under_review**: nothing is refunded,
     cleared or retried automatically. An admin resolves it (section 10) by charging `0…quoted` credits or returning
     them, with a reason. A new calendar day does not release a hold.
5. A user is never charged more than the quote they approved. A provider cost above the admin's planning estimate is an
   operator risk, never an extra debit.
6. Every credit sentence a user sees (`state_detail`, and a run's refusal) is derived from the recorded resolution:
   held, charged (how many of the reserved credits, by whom) or returned. It is never inferred from a missing send time.
7. `sending_disabled` means only that the server cannot send (no paid sender or an unusable key). A saved request that no
   longer verifies is `internal_error`, an unknown one `not_found`, and an analysis that already has an attempt
   `already_attempted`; none reserves anything.

Limitation, stated plainly: a 15-minute age is only an age (the HTTP client's timeouts bound each read and connect, not
a whole call, and a process can pause). It never authorizes a refund by itself; only a free execution lock shows that no
worker can still send or record an attempt. A worker that is alive but hung keeps its attempt held until its process
ends.

## 8. Credit policy and daily limits (admin settings, no built-in values)

Numeric grants, daily limits and conversion rates are admin settings. The server ships with none: without a policy,
quoting is refused (`no_credit_policy`); without a daily limit for the user, running is refused (`no_daily_limit`).

A credit policy version (append-only; a new version supersedes the previous one and every quote issued under it):

```json
{"policy_version": "credit-policy-2", "flow": "research-analysis", "model": "<the verified research model>",
 "efforts": {"low": {"extra_credits": 0}, "high": {"extra_credits": 2}},
 "credits": {"base": 1, "per_1k_input_tokens": 1, "per_1k_output_tokens": 1},
 "max_request_usd": 0.25, "quote_valid_seconds": 900, "settlement": "quoted"}
```

`credits = base + ceil(input_tokens_assumed / 1000) × per_1k_input_tokens + ceil(max_tokens / 1000) ×
per_1k_output_tokens + extra_credits[effort]`, where `input_tokens_assumed` is the existing planning estimate's count
for the exact saved request bytes and `max_tokens` the request's output bound (16,000). Equal-Effort requests of
different sizes can therefore cost different credits. Only the levels listed in `efforts` are enabled. `max_request_usd`
is the admin's monetary decision: a request whose planning estimate exceeds it is refused before quoting. The values in
this example are synthetic.

Daily limits: one non-negative integer per user (append-only history), counted per calendar day in the quota time zone
(setting, initially `Asia/Jerusalem`). Times are recorded in UTC; day boundaries come from the time zone database, so a
day can be 23 or 25 hours long. Each run records its quota day and zone, and those never change. The zone can be set
only until the first run is counted: afterwards a change is refused (`409 quota_timezone_fixed`, admin contract),
because counting the same hours under another zone's days would create allowance. The refusal is checked in the same
serialized transaction as reservations, so a change and a reservation never interleave.

These limits govern use of this application. They are not a verified monetary billing ceiling.

## 9. Error codes

| Status | Code | When | Extra fields |
| --- | --- | --- | --- |
| 401 | `not_signed_in` | No session. | – |
| 401 | `session_expired` | The session ended (lifetime or sign-out elsewhere). | – |
| 401 | `invalid_credentials` | Sign-in failed. | – |
| 403 | `registration_pending` | Sign-in with the right password of a registration awaiting a decision. No session. | `registration` |
| 403 | `registration_rejected` | Sign-in with the right password of a rejected registration. No session. | `registration` |
| 403 | `forbidden` | Wrong role for the route, or a write without this page's Origin/header. | – |
| 404 | `not_found` | Unknown route or record, or a record owned by someone else. | – |
| 409 | `unsupported_effort` | The Effort is not offered (unknown, unverified or not enabled). | `efforts` |
| 409 | `no_credit_policy` | No credit policy is active. | – |
| 409 | `request_over_budget` | The request exceeds the administrator's per-request limit. | – |
| 409 | `already_attempted` | The analysis already has an attempt (from another quote). | – |
| 409 | `quote_expired` | The quote's validity ended. Ask for a new quote. | – |
| 409 | `quote_superseded` | The policy or Effort menu changed since the quote. Ask for a new quote. | – |
| 409 | `quote_mismatch` | The approval does not repeat the quote (Effort, credits, analysis) or the quote is not this user's. | – |
| 409 | `insufficient_credits` | Available credits are below the quote. | `credits` (Account.credits) |
| 409 | `no_daily_limit` | No daily limit is set for this user. | – |
| 409 | `daily_limit_reached` | Today's limit is used. | `daily` (Account.daily), `resets_at` |
| 409 | `result_changed` | The review names a result that is not the current one. Reload. | – |
| 409 | `review_conflict` | Another review version was saved since this one was loaded. Reload. | – |
| 409 | `no_result` | There is no recorded result to review. | – |
| 413 | `payload_too_large` | The body is too large. | – |
| 422 | `invalid_request` | The body is not the documented JSON (fields, types, `approve: true`). | – |
| 422 | `invalid_source` | The source form is not valid. | – |
| 422 | `invalid_review` | The review form is not valid, or nothing changed. | – |
| 503 | `sending_disabled` | This server cannot run analyses now. Nothing was reserved. | – |
| 503 | `accounts_unavailable` | The server runs without an accounts store. | – |
| 500 | `internal_error` | Anything else. The detail never carries internals. | – |

A refusal with status < 500 means nothing was reserved, sent or written by that call (a `5xx` from a run does not
prove what was recorded: read the analysis again; never retry automatically).

## 10. Admin endpoints (admin-api-0.1, admin sessions only; the Client never calls them)

All responses carry `"contract": "admin-api-0.1"`; writes need `X-Second-Order-Admin: 1`. A refusal of the access
check itself (no session, a user session) is in the user contract's shape on every route, so any client can read it. Admin payloads may contain
models, Effort, timings, usage, planning estimates and usage-derived costs; none of them appears in a user payload.

| Operation | Method and path |
| --- | --- |
| Users with balances, holds and limits | `GET /api/admin/users` |
| Create a user or admin | `POST /api/admin/users` `{username, display_name, role, password}` |
| Activate / deactivate (sessions revoked) | `POST /api/admin/users/{user_id}/status` `{active, reason}` |
| Grant or correct credits (ledger entry) | `POST /api/admin/users/{user_id}/credits` `{kind: "grant" or "correction", credits, reason, idempotency_key}` |
| Set the daily analysis limit | `POST /api/admin/users/{user_id}/daily-limit` `{limit, reason}` |
| Credit ledger and totals | `GET /api/admin/ledger?user_id=` |
| Holds and attempts needing review | `GET /api/admin/holds` |
| Resolve an attempt under review | `POST /api/admin/attempts/{attempt_id}/resolve` `{resolution: "charge" or "return", credits_charged, reason, observed: {sent_at, outcome}}` |
| Credit policy versions | `GET /api/admin/policy`, `POST /api/admin/policy` `{policy, reason, idempotency_key}` (a new version: `201 {contract, current, published, created: true}`; the same key and values again `200 {… created: false}` publish nothing; the key with other values or from another administrator `409 idempotency_conflict`, nothing written) |
| Settings (quota time zone; `fixed` once a run is counted) | `GET /api/admin/settings`, `POST /api/admin/settings` (unchanged: `200`, `changed: false`) |
| Actions | `GET /api/admin/actions` |
| Assign a capture's owner | `POST /api/admin/ownership` `{kind: "capture", record_id, user_id, reason}` |

Ledger entries (grants, corrections, holds, charges, returns) are append-only with actor, reason and UTC time; totals
reconcile as `granted + corrections − charged − held = available`.

Presets (additive): `GET /api/admin/policy` lists `presets`, the operator's selected pilot terms as
`{preset, label, note, credits, efforts}`: rates and Effort extras only (`pilot-flat-1`: base 10, both size rates 0,
extras low 0, medium 5, high 10, xhigh 15, max 20, so 10, 15, 20, 25 and 30 points for any accepted source). It carries
no model, quote validity or `max_request_usd`: no monetary limit was selected, and a new version still requires one.
`GET /api/admin/users` lists `allocation_presets` (`pilot-initial-1`: `{preset, label, note, credits: 100,
daily_limit: 3}`) and gives each user row `allocated` (any grant or correction ever recorded). A preset is data: the
Admin screens fill a draft or a form from it, and only the existing explicit POSTs record anything. Startup, reads,
registration and approval apply none, and nothing refills credits.

Resolving an attempt: `observed` repeats the attempt's `sent_at` and recorded `outcome` as the holds list showed them.
The server takes the attempt's execution lock (`409 in_flight` while a worker holds it), then, in one write transaction,
refuses an attempt already resolved (`409 already_resolved`, with the resolution that applied), one whose send start or
outcome changed since it was loaded (`409 state_changed`, with the current state) or one that is not yet eligible
(`409 in_flight`: no outcome is recorded and it is less than 15 minutes old). Only an applied resolution answers `201`
(`applied: true`); a repeat never reports success. Each holds row carries `observed`, `worker_active` and
`resolvable` (a hint; the resolution checks everything again).

An action row (first slice: every research-analysis request and attempt, user and operator) shows its type (`prepare`
local and free, `mock` local and $0, `provider_call`), user, model, Effort, state, the locally measured times (reserved,
sent, received, elapsed; provider-side components marked unavailable), input and output usage when the provider reported
it, the planning estimate, the usage-derived cost labelled as a local calculation (not verified billing; `null` when
usage is missing, never zero) and the credits quoted, held and charged.

## 11. Front-end boundary

- Two builds: `npm run build` writes the Admin build to `frontend/dist/` (entry `index.html` → `src/main.tsx`) and the
  Client build to `frontend/dist-client/` (entry `client.html` → `src/shell/clientMain.tsx`).
- Shared shell: `src/shell/` loads `GET /api/session`, shows the signed-out pages when signed out (the Client build's
  `src/public/PublicApp.tsx`, docs/onboarding-contract.md section 7; the Admin build's sign-in form), and mounts the
  role's app; `src/router.tsx` (`Link`, `navigate`, `useLocation`) and `src/styles.css` are shared and unchanged.
- `src/client/ClientApp.tsx` exports `ClientApp(props: ClientAppProps)`; `src/admin/AdminApp.tsx` exports
  `AdminApp(props: AdminAppProps)`. `ClientAppProps` (in `src/contracts/user.ts`):

  ```ts
  interface ClientAppProps {
    session: SignedInSession;                     // role "user", already validated
    signOut: () => Promise<void>;                 // ends the session, then shows the sign-in form
    sessionEnded: (reason: "not_signed_in" | "session_expired") => void;  // call on a 401 from any request
  }
  ```

- The Client owns every path the Client build serves (the server sends the Client build for all non-API paths to user
  sessions). It calls only `/api/session*` and `/api/user/*` through the helpers in `src/contracts/user.ts`, and keeps
  its styles under `src/client/`.
- `src/contracts/user.ts` holds the types, the fail-closed readers and the request helpers of this contract. Synthetic
  fixtures are `frontend/tests/fixtures/user-contract-*.json`; `frontend/tests/user-contract.test.ts` checks that every
  fixture reads. Fixture values are synthetic and may be regenerated from the real server under the same contract
  version; the Client must depend on fields and states, not on particular IDs, hashes or times.

## 12. Amendments

An amendment bumps the version (`user-api-0.2`, …), lists every changed field or code under "Changes" at the top of this
file, updates `src/contracts/user.ts` and the fixtures in the same commit, and is reported to the Client conversation by
commit SHA. Additive fields do not need a version bump if the readers ignore unknown fields; renamed, removed or
re-typed fields and new required fields do.

## 13. Development state

- Foundation commit `9eff882`: this contract, the user types and fixtures, the two entry points, the shared shell and
  `GET /api/session` in `local-operator` mode.
- Admin branch (`admin-backend`): the `accounts` mode, every user and admin endpoint above, credits, quotes, daily
  limits, reservations, settlement and reconciliation, the Admin screens and their browser check. Real server payloads
  from a synthetic scenario are tested against every published fixture's structure and against the readers in
  `src/contracts/user.ts` (tests/test_user_research.py).
- Onboarding branch (`entry/onboarding-logic`): user-api-0.2 with the onboarding contract (foundation `2f863d0`),
  then self-registration, the registration decisions, the public credit terms and the policy preview, a source
  of 50,000 characters in any script (tests/test_user_research.py), and the selected pilot presets
  (tests/test_pilot_preset.py and the admin browser check).
- The Client build's `ClientApp` remains the Client conversation's; end-to-end enforcement is proven only by the
  combined integration checks against this server, never by a mocked UI.

### Clarifications after the foundation commit (no field or code changes; still user-api-0.1)

- UTC times may be written with `Z` (section 3).
- A quote is refused with `503 sending_disabled` when the server cannot send (section 7).
- The order of `analysis.reason` when several apply (section 6).
- Access-check refusals are in the user contract's shape on admin and operator routes too (section 10).
- Ownership assignment covers captures only (sections 1 and 10).
- Signing in again in the same browser ends that browser's previous session.

### Corrections on the Admin branch (behavior only; user-api-0.1 fields and fixtures unchanged)

- The quota time zone is fixed once a run is counted (section 8).
- An attempt's execution lock, not its age, decides whether it can still send; `running` and `unresolved` follow it
  (sections 6 and 7). Admin resolutions repeat the observed state and never report an unapplied resolution as saved
  (section 10).
- Credit sentences follow the recorded resolution; refusal codes name the actual failure (section 7).
