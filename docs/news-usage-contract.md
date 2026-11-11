# Current news, interests, publication import and usage limits: user-api-0.4 and admin-api-0.3

Status: **implemented** (branch `admin/ops-polish`; the contract checkpoint `2c56167` preceded the server so the
Client could build against it). The routes are `second_order/news_api.py`, the limits `second_order/usage.py`, the
Admin screen `frontend/src/admin/AdminUsage.tsx`; `tests/test_news_api.py` and `tests/test_usage_limits.py` exercise
them on the real application with SYNTHETIC accounts, limits and feeds. Types, fail-closed readers and bound request helpers are in `frontend/src/contracts/news.ts` (the new
refusal codes and their fields in `frontend/src/contracts/user.ts`); SYNTHETIC fixtures are
`frontend/tests/fixtures/news-contract-*.json` and the new refusals in `user-contract-errors.json`, written by
`tests/news_contract_fixtures.py` from the data owner's real functions over synthetic feeds and pages. It amends `docs/admin-user-contract.md` (with `docs/onboarding-contract.md` and
`docs/account-binding-contract.md`). The news, search, import and quality payloads are the data owner's
(`NEWS_DATA_REQUIREMENTS.md` with its Amendment 1: `user_news`, `publication_import`, `research_quality`); this
contract adopts them unchanged and adds the routes, interests, idempotency and usage limits.

Everything here is for an **active, approved user** with a session; a pending, rejected or deactivated account has no
session and gets `401`. Every write names its account (`X-Second-Order-Account`, account binding). No route here
contacts a publisher or a model on a read or a search. A feed excerpt or headline is discovery metadata, never a
publication: research runs only on a saved source.

## 1. Routes (user-api-0.4)

| Operation | Method and path | Body | Reply | Counted |
| --- | --- | --- | --- | --- |
| News | `GET /api/user/news?scope=interests\|all` | – | `200 {contract, news: NewsView}` | never |
| Interests | `GET /api/user/news/interests` | – | `200 {contract, interests: Interests}` | never |
| Save interests | `POST /api/user/news/interests` | `{interests, expected_version}` | `201 {contract, interests, changed: true}`; the same selection `200 {… changed: false}` | never |
| Search | `POST /api/user/news/searches` | `{query, interests, sources, listing, request_key}` | `201 {contract, view_version, search, entries, statement, counted: true, quota: QuotaNow}`; a repeat `200 {… counted: false}` | `search` |
| Import preview | `POST /api/user/news/imports` | `{entry_id, version_sha256}` | `201 {contract, import: ImportPreview, created: true, quota: QuotaNow}`; the account's earlier preview of that version `200 {… created: false}` | `import` |
| One import | `GET /api/user/news/imports/{import_id}` | – | `200 {contract, import}` | never |
| Confirm import | `POST /api/user/news/imports/{import_id}/confirmation` | `{text_sha256, confirm: true}` | `201 {contract, import, source: Source, created: true}`; a repeat `200 {… created: false}` | `source` |
| Limits | `GET /api/user/limits` | – | `200 {contract, limits: Limits}` | never |
| Research checks | `GET /api/user/analyses/{analysis_id}/quality` | – | `200 {contract, quality: Quality \| null}` | never |

The existing `POST /api/user/sources` counts as `source` and `POST /api/user/analyses` as `preparation` (section 3).
Quotes, runs (credits and the daily analysis limit, unchanged), reviews, exports and every read are not counted.

### NewsView (user-news-view-0.1, data owner)

`{view_version, vocabulary_version: "news-interests-0.1", scope, interests: [slug], sources: [NewsSource],
entries: [NewsEntry], notes: [text], statement}`.

- **NewsSource**: `source` (`fed-monetary`, `bls-empsit`, `bls-cpi`, `eia-todayinenergy`, `wto-news`), `label`,
  `publisher`, `interest`, `kind`, `attribution` (empty when none is verified), `catalogue_url`, `terms_url`, `state`
  (`never_refreshed`, `ok`, `failed`, `not_requested`, `unreadable`), `last_success_at` (time or null),
  `last_attempt` (`{at, outcome: ok|failed|not_requested, detail: text|null}` or null), `note` (text or null),
  `stale` (entries come from an earlier success), `entries` (current entries held), `importable`.
- **NewsEntry**: `entry_id` (`<source>:<20 hex>`), `version_sha256` (64 hex: what an import binds), `source`, `title`,
  `title_shortened`, `excerpt` (feed text or null, never a publication), `excerpt_shortened`, `excerpt_repeats_title`,
  `link` (https), `published` (`{state: stated|date_only|unstated, as_stated, element, utc, date, note}`; only
  `stated` has `utc`; a retrieval time is never a publication time), `first_retrieved_at`, `last_retrieved_at`,
  `listing` (`current` or `retained`: no longer in the feed), `stale`, `topics`
  (`[{interest, basis: source|terms, terms: [{term, field: title|excerpt}]}]`), `matches_interests`, `import`
  (`{state: supported|unsupported|imported, reason: text|null, source_ids: [source_id]}`).
- Order: current entries first (stated instants newest first, then the rest in the feed's order), then retained
  entries (most recently seen first, at most 50 per source; the rest are counted in `notes`). No score.
- An empty or failed source is shown as it is: never filled in with other or invented entries.

### Interests (news-interests-0.1)

`{vocabulary_version, rule, vocabulary: [{interest, label, sources: [source], terms: [text]}], selected: [slug],
version: n|null, saved_at: time|null}`. Slugs: `monetary-policy`, `employment`, `inflation`, `energy`, `trade`.
`selected` holds 0 to 5 distinct slugs in vocabulary order. Saving sends the whole selection and the `version` the page
loaded (`expected_version`, null when none was saved): another tab's newer save is refused (`409 interests_changed`,
with the current `interests`) instead of overwritten. Versions are kept (append-only); a save changes nothing else.

### Search (user-news-search-0.1)

Body: `query` (1 to 200 characters, 1 to 8 words of letters or digits), `interests` (null or slugs), `sources` (null
or a non-empty list of source keys), `listing` (`current` or `all`), `request_key` (8 to 80 of `A-Z a-z 0-9 _ -`,
new for each deliberate search). Reply: `search` (`{query, words, interests, sources, listing, matched, shown,
limit: 100}`), `entries` (NewsEntry, at most 100), `statement`, `counted`, `quota`. An entry matches when every query
word is a whole word of its title or excerpt (NFKC, case-folded). The search reads the cache only.

### ImportPreview (publication-import-0.1, data owner)

`{import_version, import_id ("imp-" + 16 hex), state (ready|confirming|confirmed|interrupted|unreadable), problem,
created_at, entry: {entry_id, version_sha256, source, title, link, publisher, attribution}, publication: {url,
retrieved_at, retrieval: fetched|reused, bytes, sha256, last_modified, extractor, terms_url}, proposed_source:
{headline, source_url, published_at, published_basis, characters, paragraphs, text_sha256, text (null when
unreadable)}, left_out: [{kind, text}], linked_documents: [{title, url}] (named, never retrieved), source_id (after
confirmation), statements: [text]}`.

Only Federal Reserve press-release pages are importable now (`fed-press-release-extract-0.1`); any other entry says
why in `import.reason` and offers the existing paste step. A preview reads the publication at most once per server
(a kept copy is reused) and never retries. Confirmation saves exactly the previewed text as the user's source through
the same path and limits as a pasted source (headline 1,500 and text 50,000 characters), with the entry version as its
Inbox origin. Nothing is analysed, quoted or sent by an import.

### Quality (research-quality-0.3, data owner)

`{rubric_version, rejected: [], rejected_note, findings: [{check, level: "flagged", where, detail, rule}], flagged,
checks: {check: rule}, human_review: [text], statement}`, or `null` when no analysis was recorded. Lexical checks
that ask a person to look; never a score, a pass mark or a confirmation. Computed on read; `result` and
`result_sha256` are unchanged.

### Limits

The word `usage` is reserved for administrator payloads (token usage), so a user's figures are `limits` and
`quota`.

```
Limits = {state: "set" | "no_policy", detail: text|null, policy_version: text|null,
         day, timezone, resets_at,
         operations: [QuotaNow],                // search, import, source, preparation, in that order
         storage: {sources: {used, limit|null}, source_bytes: {used, limit|null}},
         rate: {requests_per_minute: n|null, concurrent_requests: n|null}}
QuotaNow = {operation, label, limit: n|null, used, remaining: n|null}   // remaining = max(0, limit - used)
```

`limit` and `remaining` are null only when `state` is `no_policy` (then nothing counted is allowed). Figures are the
server's at the reply; the server checks them again on every counted request.

## 2. Usage policy (admin-api-0.3)

One server-wide policy, versioned and append-only like the credit policy, published only by an administrator's explicit
action with a reason. **No numeric value is selected here**: the administrator types each one (tests use SYNTHETIC
values). Every field is required; 0 means none is allowed.

| Field | Bounds | Meaning |
| --- | --- | --- |
| `account.searches_per_day` | 0 to 10,000 | counted searches per account per quota day |
| `account.imports_per_day` | 0 to 1,000 | counted import previews per account per quota day |
| `account.sources_per_day` | 0 to 1,000 | new sources (pasted or imported) per account per quota day |
| `account.preparations_per_day` | 0 to 1,000 | newly prepared analyses per account per quota day |
| `account.max_sources` | 0 to 100,000 | sources an account may hold |
| `account.max_source_bytes` | 0 to 1,000,000,000 | total UTF-8 bytes of an account's source texts |
| `account.requests_per_minute` | 1 to 10,000 | protective: an account's requests to user routes in any 60 seconds |
| `account.concurrent_requests` | 1 to 64 | protective: an account's user requests in progress at once |
| `server.publication_fetches_per_day` | 0 to 1,000 | publication pages this server may request per quota day, all accounts together |
| `server.refreshes_per_day` | 0 to 1,000 | feed refreshes per quota day, all operators together |
| `server.refresh_cooldown_seconds` | 0 to 86,400 | the least time between the starts of two feed refreshes |

| Operation | Method and path | Body | Reply |
| --- | --- | --- | --- |
| Usage policy | `GET /api/admin/usage-policy` | – | `200 {contract, current, versions, bounds}` |
| Publish a version | `POST /api/admin/usage-policy` | `{policy, reason, idempotency_key}` | `201 {contract, current, published, created: true}`; the same key and payload again `200 {… created: false}` (nothing new); the same key with another payload `409 idempotency_conflict` |
| Usage today | `GET /api/admin/usage` | – | `200 {contract, policy, day, timezone, resets_at, accounts: [{user_id, operations, storage}], server: {publication_fetches, refreshes, last_refresh_started_at, next_refresh_allowed_at}}` |

A new version applies from the moment it is published; today's counts continue under it (a lower limit refuses further
counted requests; nothing already done is undone).

## 3. Counting rules

- **Day and reset.** Counts are per quota day in the server's fixed quota time zone (the same days as the daily
  analysis limit; a 23- or 25-hour day is one day). They reset at the next local midnight (`resets_at`).
- **What counts, once each.**
  - `search`: a search with a new `request_key` that passes validation and the limit. Repeating the same key and body
    answers `200 counted: false` from the cache as it is now, at any later time. The same key with another body is
    refused (`409 request_key_reused`); nothing counts.
  - `import`: a preview the account did not have (`created: true`), and also a preview that requested the publisher's
    page but failed (`publication_unavailable`, `publication_unreadable`, `publication_too_long`,
    `publication_time_conflict` after a request), because a request was made. The account's earlier preview of the
    same entry version (`created: false`) and a refusal before any request (`not_found`, `entry_changed`,
    `import_unsupported`, `import_in_progress`, `invalid_request`) do not count.
  - `source`: a new source, pasted or confirmed from an import. A repeated confirmation (200) does not count. The
    form is checked by every rule of the capture before anything is reserved, and the capture is written inside the
    reservation's transaction, so a source refused `422 invalid_source` counts, reserves and writes nothing: an
    invalid form, the same source at the same instant, and the same capture written after those checks by another
    account or the operator's form (only the write finds it, and the count is rolled back with it).
  - `preparation`: a newly prepared analysis (`201`); reopening one already prepared (`200`) does not count.
- **Atomicity.** Each counted request reserves its count and checks storage in one serialized accounts-store
  transaction before it writes or requests anything (a new source's capture is written inside that transaction), and
  releases the reservation when it is refused without a write or a request. Two concurrent requests at a limit never
  both pass.
- **Storage.** `max_sources` and `max_source_bytes` are checked against the account's own sources as recorded
  (including sources from before the policy), with the new source's bytes, before it is written.
- **Shared publication budget.** A preview that needs to request a page (no kept copy) reserves one of
  `server.publication_fetches_per_day` before the request, kept once a request was made (whatever its outcome) and
  released when none was. Requests are serialized: one publication request at a time on the server. Only a server
  started with `serve --enable-publication-import` requests a page; on any other a preview that would need one is
  refused `publication_unavailable` (`paste_instead: true`, `requested: false`) before anything is counted.
- **Feed refresh.** The existing operator refresh (`POST /api/inbox/refresh`, administrators only) needs a usage
  policy, waits `refresh_cooldown_seconds` after the previous start and stops at `refreshes_per_day`; a refusal
  (`409` with the reason and, for the cooldown, the whole seconds to wait) requests nothing. A refresh that cannot start
  (no feed configuration) releases its count. It refreshes the shared cache that every user reads; users never refresh
  publishers.
- **Protective limits.** `requests_per_minute` and `concurrent_requests` count every request of the account to
  `/api/user/*` (reads included) on this server process. They protect the server; they are not charges, they are not
  durable across a restart, and they never refund or charge credits.
- **Quota zone.** Once anything is counted (a run or a usage event), the quota time zone is fixed, as before for
  runs (`409 quota_timezone_fixed`).
- **Records.** Versions, events and releases are append-only rows of the accounts store (`usage_policies`,
  `usage_events`, `usage_releases`; schema accounts-3): a released reservation keeps its event and gains a release
  row with the reason, so every count can be traced. Both are stamped by the server's clock.
- **No usage policy.** News reads, interests (read and saved), searches, imports, new sources and preparations are
  refused (`409 no_usage_policy`); a missing setting is never unlimited. Reads of the account's existing sources, analyses,
  reviews and exports stay available, as do quotes, runs and reviews under their existing rules.

## 4. Refusals (user error shape `{contract, code, detail, …}`; nothing written or requested unless stated)

| Status | Code | Extra fields | When |
| --- | --- | --- | --- |
| 409 | `no_usage_policy` | – | no usage policy is published |
| 409 | `usage_limit_reached` | `quota: {operation, limit, used, day, timezone, resets_at}` | the day's count is used |
| 409 | `storage_limit_reached` | `storage: {measure: sources\|source_bytes, limit, used, adding}` | the source would exceed what the account may hold |
| 409 | `fetch_budget_reached` | `resets_at` | the server's publication requests for today are used |
| 409 | `request_key_reused` | – | a search key was used with another body |
| 409 | `interests_changed` | `interests: Interests` | another save happened since the page loaded |
| 429 | `rate_limited` | `retry_after_seconds` | `requests_per_minute` is used |
| 429 | `too_many_requests` | `retry_after_seconds` | `concurrent_requests` are in progress |
| 404 | `not_found` | – | unknown entry or import, or another account's import |
| 409 | `entry_changed` | – | the entry version shown is no longer held; reload the news |
| 409 | `import_unsupported` | `paste_instead: true` | no reader for this publisher or address, or no stated publication time |
| 409 | `publication_unavailable` | `paste_instead: true` | the publisher refused, redirected, timed out or exceeded 2 MB (a request was made) |
| 409 | `publication_time_conflict` | – | the page's date or time disagrees with the feed's |
| 409 | `import_in_progress` | – | the same publication is being requested or confirmed now |
| 409 | `publication_changed` | – | a confirmation names another text than the preview |
| 409 | `import_interrupted` | – | an earlier confirmation stopped after its claim; nothing is created again |
| 422 | `publication_unreadable` | `paste_instead: true` | not readable as the release's text |
| 422 | `publication_too_long` | `paste_instead: true` | more than 50,000 characters; never truncated |

Every refusal of an import preview from the import itself (`not_found`, `entry_changed`, `import_unsupported`,
`import_in_progress` and the `publication_*` codes) also carries `requested: true | false`: whether the publisher's page
was requested for it, which is exactly when the preview counts (the data owner's Amendment 2).

The protective limits are decided before the route runs; `no_usage_policy` and the daily and storage limits before
anything is written or requested. A source form is checked before those three: an invalid one is refused
`invalid_source` for what it is, at a limit too. A Client never retries
any of them by itself; it shows the server's sentence and the figures it carries.

## 5. Admin (admin-api-0.3)

A Usage & limits screen (`/admin/usage`) shows the current version, then a form whose fields all start empty (the
administrator types each value, or copies the current version's on request) published as its own explicit action with
a reason and an idempotency key, one per intent, so a double click or a lost reply never publishes twice. It shows
today's counts for every user account (searches, imports, new sources and prepared analyses against their limits;
sources and source text held), the server's publication fetches and feed refreshes with the last and the next allowed
refresh, and the earlier versions. The counts are this server's own; they are not billing and verify no cost. The
Event Inbox's refresh shows a refusal's reason as before.

## 6. Change note

- user-api-0.4: the routes of section 1, the counted `POST /api/user/sources` and `POST /api/user/analyses`, the codes
  of section 4. Readers accept user-api-0.1 to 0.4; existing payloads are unchanged.
- admin-api-0.3: the usage policy and usage routes, and the Usage & limits screen.
- Accounts store accounts-3 (`accounts upgrade` brings an accounts-1 or accounts-2 store forward, keeping every row).
- `serve --enable-publication-import`: the only way a server requests a publication page; off by default.
- No production policy, limit, grant or activation follows from this document.
