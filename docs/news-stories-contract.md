# News stories, shared briefs, topics and Go deeper: user-api-0.5 and admin-api-0.4

Status: **implemented** on branch `news/stories-mvp`. It amends `docs/news-usage-contract.md` (user-api-0.4, admin-api-0.3),
`docs/admin-user-contract.md`, `docs/onboarding-contract.md` and `docs/account-binding-contract.md`; every rule there
still holds. Readers accept user-api-0.1 to 0.5; existing payloads are unchanged except where section 8 says.

The modules are `news_registry.py` (sources), `news_feeds.py` (publisher feeds), `news_reports.py` (the report pool),
`newsroom_store.py` (the newsroom), `news_stories.py` (grouping and coverage), `news_rank.py` (ranking), `news_topics.py`
(topics and priority), `story_briefs.py` (briefs), `brief_drafting.py` (the paid draft), `news_views.py` (what users
read), `news_desk.py` (the Admin desk), `story_deeper.py` (Go deeper), `stories_api.py` and `news_admin_api.py`
(routes), `news_curation.py` (the operator's curation plan) and `news_cli.py` (commands). Types, fail-closed readers and request helpers are in
`frontend/src/contracts/stories.ts`; SYNTHETIC fixtures are `frontend/tests/fixtures/stories-contract-*.json`, written by
`tests/stories_contract_fixtures.py` from the real functions. `tests/test_news_stories.py` and
`tests/test_news_desk_api.py` exercise the modules and the routes on the real application with SYNTHETIC accounts,
publishers and feeds, and `tests/test_news_curation.py` the official publishers of news-registry-0.2, the subject rule
and dated report times of news-rank-0.2 and the curation plan; `frontend/tests/browser/news-stories-check.mjs` walks the journey in a browser.

## 1. What a user reads

The News home lists **stories**. A story is one development, covered by one or more **reports** (feed entries). Each
story may have a **shared brief**: a short summary and analysis prepared in advance by the editors and the same for
every user. Separate developments of one continuing subject belong to an ongoing **topic** with a timeline. Every read
below reads saved records only: no publisher is contacted, no model is called and nothing is counted or charged.

## 2. Sources (news-registry-0.2)

Every publisher the news reads or was evaluated for is in the registry with, separately: how headlines are had
(`public_feed`, `api_key`, `licence`), whether full text is available, what may be **shown** (`headline_excerpt`: the
headline, link and the feed's excerpt as supplied; `headline`: headline and link only), whether its entries may be
**material** for a shared brief or a deeper analysis (`permitted` or `none`), what credentials or agreement a
connection needs, and its status (`connected`, `needs_agreement`, `needs_credentials`, `not_connected`,
`fixture_only`), with the date and pages read.

Checked on 2026-10-25 against each publisher's own pages (no sign-up, credential or purchase). news-registry-0.2 adds
four official publishers whose terms allow reuse with a credit; each feed was requested once through this application's
own fetcher and parser that day (HTTP 200, every entry accepted), then by the operator's explicit refresh:

| Publisher | Status | Shown | Material | Why |
| --- | --- | --- | --- | --- |
| Federal Reserve, BLS (two), EIA, WTO | connected (Event Inbox) | headline and excerpt | permitted | public domain, or reuse encouraged with the credit "WTO news" |
| The White House (news: fact sheets, presidential actions, statements) | connected | headline and excerpt | permitted | "government-produced materials appearing on this site are not copyright protected"; the feed is the site's standard WordPress feed, not linked from the page |
| Office of the U.S. Trade Representative | connected | headline and excerpt | permitted | U.S. government work (17 U.S.C. 105); the site states no other terms |
| European Commission (press corner) | connected | headline and excerpt | permitted | CC BY 4.0: credit given and changes indicated (a brief is the editors' summary) |
| European Central Bank (press releases, speeches, interviews) | connected | headline (its feed has no excerpts) | permitted | free use with the ECB cited and modifications stated |
| U.S. Securities and Exchange Commission | not_connected | – | permitted | content may be copied with citation, but automated tools must declare a contact, which the publisher feeds do not yet send |
| U.S. Bureau of Economic Analysis | not_connected | – | permitted | the feed host's robots.txt allows only /api/ |
| Bank of England | needs_agreement | – | none | reuse granted for non-commercial purposes only |
| TechCrunch | connected | headline and excerpt | none | RSS terms allow showing the feed unmodified, credited and linked; personal, noncommercial use; no derivative works |
| PR Newswire (general business) | connected | headline only | none | personal, noncommercial use; no derivative works "in full text or in abstract"; labelled as company statements |
| FreightWaves | needs_agreement | – | none | personal use only; automated access forbidden |
| CNBC | needs_agreement | – | none | personal, non-commercial; robots and aggregation forbidden |
| Bloomberg | needs_agreement | – | none | no documented feed; caching forbidden |
| Reuters | needs_agreement | – | none | no public feed; text by Reuters Connect subscription |
| AP | needs_agreement | – | none | no public feed; licensing |
| Investing.com | needs_agreement | – | none | use or storage forbidden without written permission |
| Financial Times | needs_agreement | – | none | archiving, paid services and any AI use forbidden |
| The Guardian | needs_credentials | – | none | Open Platform key; AI and text-mining use forbidden without a commercial licence |
| Yahoo Finance | not_connected | – | none | undocumented per-ticker feeds; robots disallow; automated collection forbidden |

No third-party publisher grants use of its reports for shared summaries or model analysis; until one does, briefs and
deeper analyses use only the official releases' material. Third-party reports are listed and linked as sources. A
publisher whose entries span many subjects (the White House, the European Commission) has no single interest: each
entry's interests are found by its words. The Federal Register (which sends unrecognised clients to an unblock page) and
the U.S. Treasury (whose feed did not answer) were tried and are not listed.

## 3. Reports, stories, coverage and topics

- **Report** (news-report-0.1): an entry of the Event Inbox cache (the official feeds) or the publisher-feed cache
  (`data/news-feeds/`, refreshed only by the operator), current or retained. Its time is the instant its feed states
  (`at_basis` `published`); when the feed states a calendar date but no usable time (a date-only feed's placeholder
  time, or a time whose zone contradicts its date, as EIA's "EST" in October), the end of that date in UTC, or when
  this server first saw it if that was earlier (`dated`), so a release first retrieved days after its date is not
  taken for new; otherwise when this server first saw it (`first_seen`). Every view says which; a `dated` time is shown
  as its date alone. A retrieval time is never called a publication time.
- **Story** (story-match-0.1): every report belongs to one story once the operator groups the news. The only automatic
  rule is the same headline (the same words, at least 4, within 72 hours, a trailing publisher credit set aside).
  Shared keywords never merge stories: pairs of stories whose headlines share at least 3 distinctive words including a
  name or figure (Jaccard at least 0.5, within 48 hours) are listed for the operator, who merges, detaches or retitles
  explicitly. Every membership row records its rule and evidence, or the operator, the time and the reason. A story's ID
  is stable (`story-` and 16 hex digits); a merged story's address opens the story it joined (`merged: true`).
- **Coverage** (story-coverage-0.1): reports by one publisher count once; reports by different publishers with the same
  headline, nearly the same excerpt (Jaccard at least 0.8 over at least 12 words) or the same wire credit are one
  coverage unit. A company's statement is counted apart and never as independent confirmation.
- **Topic** (news-topic-0.1): an ongoing subject the operator creates; separate stories are linked to it as
  developments with a short label, in the order they were first reported.
- **Priority**: the operator may mark a story or topic as major until a time at most 7 days ahead; a later mark
  replaces it and level `none` clears it.

## 4. Ranking (news-rank-0.2; news-rank-0.3 in section 11)

Hot now lists stories with a report from the last 72 hours (and those marked major), by fixed points shown in words:
freshness (4 points halved every 12 hours since the latest report, halved once more when that report states no time
of day: `dated` or `first_seen`);
a new development (1 point when first reported in the last 24 hours, by a stated time); independent coverage (0.75 per
coverage unit after the first, up to 3); the editors' major mark (2 points while it lasts and the story has a report
from the last 7 days); and the newest development of an ongoing topic (1 point when the previous development is at most
7 days older). Ties go to the newer story, then the ID. A story covered only by companies' own statements, or one
that names none of the news's subjects (none is its publishers' own interest and none of the interests' terms is in its
reports' words, such as a ceremonial proclamation), is listed under Latest, not Hot now, unless the editors mark it as
major (signals `statements_only` and `no_subject`). Latest lists every story newest first, marking older ones. Nothing
counts readers, clicks, shares or market moves.

## 5. User routes (user-api-0.5)

Every route needs an approved user and a published usage policy (`409 no_usage_policy` otherwise), like the news.

| Operation | Method and path | Reply | Counted |
| --- | --- | --- | --- |
| Stories | `GET /api/user/news/stories?view=hot\|coverage\|latest\|interests` | `200 {contract, stories: StoriesView}` | never |
| A story | `GET /api/user/news/stories/{story_id}` | `200 {contract, story: StoryPage}` | never |
| Topics | `GET /api/user/news/topics` | `200 {contract, topics: TopicsView}` | never |
| A topic | `GET /api/user/news/topics/{topic_id}` | `200 {contract, topic: TopicPage}` | never |
| What Go deeper would use | `GET /api/user/news/stories/{story_id}/deeper` | `200 {contract, deeper: DeeperPreview}` | never |
| Go deeper | `POST /api/user/news/stories/{story_id}/deeper` `{material_sha256, effort}` | `201 {contract, deeper, created: true}`; a repeat `200 {… created: false}` | `source` once, `preparation` once |

- **StoriesView** (news-stories-view-0.2, section 10): `{view_version, view, as_of, rank: {rank_version, hot_hours, statement},
  interests, stories: [StoryCard], topics: [TopicCard], sources: [SourceRow], notes, statement}`. A StoryCard has its
  times and their basis, reports, publishers, coverage counts, interests, topics, `brief: {state, summary}`
  (`published`, `withdrawn`, `not_permitted`: no report may be summarised; `none`: none prepared), a feed excerpt only
  when no brief is published, `older`, `stale`, `synthetic` and the ranking `signals` in words.
- **StoryPage** (news-story-view-0.2, section 10): the card's facts, the full coverage with its units, `brief_state` with a
  `brief_note` when no brief is shown, `brief` (Brief or null), `sources` (each report: publisher, role label, kind,
  headline, the excerpt only where shown, its own https link, the feed's publication time, `use`: `material`,
  `permitted` or `listed`, and why it was counted with another), `topics`, `related` developments (newest first, each
  with its `first_at` and `first_basis`), `deeper: {available,
  material_reports, reason}` and the statement that reading contacted nothing.
- **Brief** (story-brief-0.2, section 10): `content: {headline, summary, facts: [{text, reports}], implications: [{text}], themes:
  [{kind: sector|company|theme, name, basis}], uncertainties, missing}`, `method` (`editorial`, `extract`, `model`,
  `synthetic`) with its label, version, prepared and published times, `material: {coverage, statement, reports,
  not_used}`, `reports_since` (reports arrived after preparation). Facts are reported facts citing material reports;
  implications are possibilities; no operator, key, history, model name, cost or unpublished version reaches a user.
- **DeeperPreview** (story-deeper-0.1, now story-deeper-0.2: section 13; its material and source text follow
  section 10): the material (only permitted
  reports, with each publication's retained text where there is one, otherwise as the feeds gave them), what is left out
  and why, the exact source text it becomes (headline, the earliest stated report's address and time, the text with
  its limits stated first), `material_sha256`, and the user's own earlier source and analyses from it (`existing`).
- **Go deeper** saves that text as the user's source through the existing source path and limits, records its origin in
  `data/story-deeper/<source ID>.json` (user, story, material, brief version, report versions; write-once, beside the
  capture), and prepares the analysis at the chosen Effort through the existing path. It quotes, sends and charges
  nothing: the analysis page shows the credit quote, and only the user's approval runs it, under every existing rule
  (credits, daily limit, ownership, one attempt). Repeating it with the same material reuses the user's source (and the
  prepared analysis); another account gets its own source and never sees this one's. Refusals: `story_changed` (the
  material changed since it was read), `deeper_unavailable` (no permitted material, or none with a stated time),
  `unsupported_effort`, and the source and preparation limits as before.

## 6. Administrator routes (admin-api-0.4)

Every write is one explicit POST with the admin header, the account binding and an idempotency key (8 to 80 of
`A-Z a-z 0-9 _ -`; the same key with another payload is `409 idempotency_conflict`), recorded with the administrator,
the time and a reason where it decides something. Without accounts, the local operator uses them.

| Operation | Method and path | Body |
| --- | --- | --- |
| The desk | `GET /api/admin/news` | – |
| Refresh publisher feeds | `POST /api/admin/news/feeds/refresh` | `{}`: each connected feed once; the usage policy's refresh cooldown and daily budget (shared with the Inbox) |
| Group new reports | `POST /api/admin/news/group` | `{idempotency_key}` (local) |
| Merge, detach, retitle | `POST /api/admin/news/stories/{id}/merge\|detach\|title` | `{into\|entry_id\|title, reason, idempotency_key}` |
| A $0 draft | `GET /api/admin/news/stories/{id}/draft` | – (the material's own words; records nothing) |
| Save a brief version | `POST /api/admin/news/stories/{id}/briefs` | `{content, method: editorial\|extract, based_on, idempotency_key}` |
| Publish or withdraw | `POST /api/admin/news/stories/{id}/publication` | `{version \| null, reason, idempotency_key}` |
| A topic; link a development | `POST /api/admin/news/topics`; `POST /api/admin/news/topics/{id}/links` | `{title, summary, reason, idempotency_key}`; `{story_id, action: link\|unlink, label, reason, idempotency_key}` |
| Priority | `POST /api/admin/news/priorities` | `{target_kind, target_id, level: major\|none, until, reason, idempotency_key}` |
| Paid draft preview | `POST /api/admin/news/stories/{id}/drafting` | `{}`: saves the exact request once; shows the model, output limit and planning estimate |
| Paid draft approval | `POST /api/admin/news/drafting/{draft_id}/approval` | `{request_sha256, approve_paid_request: true, estimated_max_usd}` |

The guard (brief-guard-0.1) records findings with every version and refuses publication (`409
brief_not_publishable` with `problems`) of advice to trade, causal claims the brief makes itself (a cause stated by
someone, "officials said…", is reported, not claimed), certainty or trading language in implications, and implications
without a possibility word; a published brief also needs at least one implication and one uncertainty or missing item.
A brief needs at least one material report (`409 no_material`). The paid draft runs only on a server started with
`serve --enable-paid-briefs`: one attempt per request, ever, posted once with no retry; a reply whose single tool call
passes the schema becomes an unpublished version (`model`), anything else is recorded and makes none; a reply carrying
the key is not kept.

### The same actions from the command line (news-curation-plan-0.1)

The local operator can take the desk's actions at the machine, recorded with the actor `local-operator`, its reason and
an idempotency key, through the same functions as the routes:

```powershell
python -m second_order news stories [--view latest|hot] [--limit N]  # IDs, times, publishers, material, brief state (read-only)
python -m second_order news draft STORY_ID                          # the $0 draft from the material's own words (read-only)
python -m second_order news curate --plan FILE --check              # check every action and each brief's guard; writes nothing
python -m second_order news curate --plan FILE                      # apply the plan in order; stops at the first refusal
python -m second_order news refresh [--official]                    # also the Event Inbox's official feeds, as its Admin refresh
```

A plan is `{plan_version: "news-curation-plan-0.1", reason, actions: [...]}`; each action has its own `key` (4 to 60
of `A-Z a-z 0-9 _ -`; the idempotency key is `plan-<key>`), `do` and an optional `reason`: `merge` (story, into),
`title` (story, title), `topic` (title, summary; later actions name it `"@<key>"`), `link`/`unlink` (topic, story,
label), `brief` (story, method `editorial`|`extract`, content, based_on, publish), `publish` (story, version),
`withdraw` (story) and `priority` (target, level, until). Applying a plan again changes nothing; an action changed
under a used key is refused (`idempotency_conflict`) and stops the plan, with the earlier actions recorded. `--check`
follows the plan's own merges and topics. Plans are the operator's files (for example `data/newsroom/plans/`); the
server never reads them.

## 7. The Client

`/` and `/news` open Hot now; `/news/latest`, `/news/topics` and `/news/for-you` the other views; the wordmark leads to
`/news`. A headline opens `/news/stories/{id}`, whose Sources section holds each publisher's own link;
`/news/stories/{id}/deeper` is the Go deeper decision; `/news/topics/{id}` a topic. Your analyses moved from `/` to
`/analyses`; `/news/reports` holds the feed entries with interests, search and import (formerly `/news`), whose
headlines now open their story. Analysis, source, import, credits and sign-in addresses are unchanged; signing in from
the landing, register or sign-in page opens the News home.

## 8. Changes to earlier payloads

- The interests vocabulary is news-interests-0.2: `markets`, `technology` and `companies` follow the five earlier
  interests, whose terms are unchanged; the new ones have no official source and are found by their terms (and, for
  stories, by their publisher's topic). Saved selections are unchanged.
- A NewsEntry (user-news-view-0.1) carries `story_id`: the story it is grouped into, or null.
- Every user reply names user-api-0.5 and every administrator reply admin-api-0.4.

## 9. Records and recovery

- `data/newsroom/newsroom.db` (newsroom-1): one SQLite file, apart from the accounts and research stores, created by the
  first explicit operator write and never by a read; every table is append-only (triggers refuse UPDATE and DELETE).
  `python -m second_order news backup --to FILE` copies it with SQLite's online backup; restoring is copying the file
  back while the server is stopped. Deleting it loses only the newsroom's decisions: reports, accounts, sources,
  analyses and research records are elsewhere.
- `data/news-feeds/`: the publisher-feed cache, with the Event Inbox's record, archive and retrieval-record formats;
  excerpts of headline-only publishers and complete third-party responses are not kept.
- `data/newsroom/drafting/<draft ID>/`: each paid draft's request, preview, attempt, send and outcome, write-once.
- `data/story-deeper/`: Go deeper's origin records, one per user source.
- No existing store needs an upgrade: the accounts store stays accounts-3 (saved interests remain valid slugs of
  news-interests-0.2) and the research store's schema is unchanged.
- No production limit, policy, grant or activation follows from this document. The SYNTHETIC publishers and briefs of
  the tests and the demo are labelled as such on every payload and page and are never in the production registry.
- The demo launcher (`tests/news_desk_server.py`) serves copies only: `--records FOLDER` copies a data folder's
  `event-inbox/` and `news-feeds/`, and `--newsroom FILE` starts from a copy of a real `newsroom.db` (SQLite online
  backup), so the operator's real stories, topics and briefs appear beside the SYNTHETIC ones, every SYNTHETIC one
  labelled. Nothing under the real data folder is written.

## 10. Prepared briefs, publication texts and coverage (the second milestone)

The aim: a reader opening an important story gets a useful prepared brief, honestly attributed, resting on the best
permitted material. Every read below still only reads saved records; nothing here makes a page read contact a
publisher or a model.

**Publication texts (news-texts-0.1, `news_texts.py`, `page_text.py`).** For official publishers whose terms allow
reuse and whose page layout is verified (the White House, USTR, EIA Today in Energy, the ECB and the WTO through
`page_text`'s layouts; the Fed's press releases through the user import's `fed_publication`), the operator retrieves
the full text of the pages a story's reports link to: `python -m second_order news texts --story ID | --hot [--limit N]
[--check]`, or the News desk (`GET|POST /api/admin/news/stories/{id}/texts`, the POST counted against the usage policy's
daily publication requests; refused whole when they do not fit). Each page is requested at most once per run (no
redirect, no retry, 2 MB, a pause per host, the ECB's 5-second crawl delay), every request leaves a write-once numbered
record, the accepted page's bytes are kept, and the text becomes a write-once snapshot under
`data/news-texts/texts/<source>/<entry>/<text SHA-256>.json` (address, retrieval time and record, page SHA-256, extractor
and version, printed title and date, length, attribution, terms basis, `full_text` or `partial_text` with the reason: a
table left out, a length cap). A kept snapshot or page is reused, never requested again. A page that is not the layout,
not its declared encoding, or holds too little text is refused with its reason, recorded beside the entry, and the
story keeps using the excerpt. The European Commission's press corner (rendered by script) and every third-party
publisher are not read.

**Material (story-material-0.2).** A material report names its retained text by SHA-256 (`text: {state, text_sha256,
characters, retrieved_at, url, extractor, partial_reason}`), and the material's `coverage` is `full_text`,
`partial_text`, `headlines_and_excerpts` or `headlines`, with a statement in words. A material without any text keeps
version 0.1 and its exact SHA-256, so adding texts changes only the stories that gained them. A story's sources carry
`text: {state, characters, retrieved_at, partial_reason, detail}` (`full_text`, `partial_text`, `failed`,
`not_retrieved`, `not_supported`). The paid draft's request (brief-prompt-2) carries each text (at most 20,000
characters of each, saying when cut) and may answer `insufficient_material` instead of a brief. Go deeper's source
carries the texts within the 50,000-character source limit (a text that does not fit is shortened at a paragraph and
says so), states what it holds, and never includes the shared brief: its implications are a reading, not evidence. Its
origin record names each report's text SHA-256.

**Authorship and review (story-brief-0.2, newsroom-2).** A version's `method` says who prepared it: `editorial` and
`extract` (a person), `model` (the AI model in this application; request, model and reported usage kept), `assisted` (an
AI assistant outside it; the tool and, only when the operator declares it, the model; no usage is invented). A reader's
Brief carries `authorship` (`editor`, `ai_model`, `ai_assistant`, `synthetic`), `review: {state, statement}`
(`written_by_editor`, `read_by_editor`, `not_reviewed`: only an explicit, recorded review says a person read it;
publishing is not reviewing), `current` (whether it was prepared from the story's material as it is now) and
`update_note`. The first read is the summary, up to three possible implications, what is uncertain or missing and the
sources it rests on; reported facts, themes and provenance follow under More detail. A brief holds at most three
implications. A version recorded under the wrong method is corrected by a correcting version with the same content and
material (`story_briefs.correct_authorship`, plan action `correct`); the corrected version stays as recorded. The
2026-10-25 local review corrected six briefs written with Claude Code but first saved as an editor's.

**Insufficient material.** A story whose material is headlines alone, or whose exact material (by SHA-256) was judged
too thin by an editor, a model reply or an assistant's import, is `insufficient` (`brief_state`, with the reason in
`brief_note`); a later judgement of the same material can reverse it, and new material clears it. Desk:
`POST /api/admin/news/stories/{id}/assessment` `{material_sha256, verdict, reason, idempotency_key}`; review:
`POST /api/admin/news/stories/{id}/reviews` `{version, note, idempotency_key}`.

**Coverage (news-coverage-0.1).** For each Hot now story, in order, and for every story: `ready`, `update` (a brief of
earlier material), `drafted`, `pending`, `insufficient`, `withdrawn` or `restricted` (no publisher allows a summary; still
listed), with counts, the material's coverage and texts, and the server's readiness (newsroom version, paid drafting,
credit terms). `python -m second_order news coverage`, `GET /api/admin/news/coverage`, and the News desk's coverage panel.

**Batches (news-batch-0.1, `news_batches.py`, `news_batch_api.py`).** A recorded preview selects Hot now's `pending` and
`update` stories in order (at most 25; 10 by default) or named stories, with each one's material and, for the paid
method, each exact saved request and the batch's total planning estimate (`news batch preview --method model|assisted
[--limit N] [--story ID]`; `POST /api/admin/news/batches {method, limit, story_ids}`). The batch ID comes from the
method and the stories' materials: the same selection is the same batch. Paid path: one approval repeating the batch ID
and total, with `approve_paid_requests: true` (`news batch approve ID --estimated-max-usd-total X
--approve-paid-requests`, which needs the key; `POST .../batches/{id}/approval`), sends each saved request at most once,
ever; approving again resumes and never resends; an item whose material changed is skipped. Assisted path: `news batch
packet ID` (the rules, the shape and the material with its texts), then `news batch import ID --drafts FILE
--assistant-tool NAME [--assistant-model NAME]`, saving each draft as an `assisted` version (or an insufficient-material
judgement); repeating an import saves nothing new. Publication is separate: `news batch publish ID --reason TEXT
[--reviewed]` (`POST .../batches/{id}/publication {reason, reviewed}`) publishes each item's version for the current
material that the guard allows, recording a review only with `reviewed`. Batch records live in
`data/newsroom/batches/<batch ID>/` (batch.json and approval.json, write-once); each request in the drafting folder.

**Go deeper readiness.** The Go deeper page names three stages from the account's own reasons: preparing (needs an Effort,
hence published credit terms), a quote (credit terms, a daily limit, credits) and a run (the server's paid sending and
the reader's approval). Without credit terms it says plainly that nothing can be prepared, quoted or run and that
nothing has been chosen for the reader; publishing terms is the administrator's decision under Policy & settings.

**The next financial publisher (access requirement).** Third-party publishers grant no use for shared AI summaries
without a licence (section 2). The most useful next source for current financial news under this product's model is
Dow Jones Factiva's GenAI-licensed content: in January 2026 Dow Jones said Factiva had GenAI-use licences from more than
8,000 sources, offered through its APIs for uses including article summarization. Reuters reportedly licenses only its
archive text for AI use and excludes live coverage, and AP's AI deal covers its archive; neither publishes developer
terms for AI summaries of current stories. Connecting Factiva needs an enterprise agreement whose licence explicitly
covers: retrieving current articles' full text by API; storing them for the brief's retention period; preparing AI
summaries and analyses and showing them to this product's signed-in users with attribution and links; and the
compensation model (Factiva compensates publishers per article access); restricted to the GenAI-licensed sources. It
needs API credentials kept as a server secret. Price is by quote from Dow Jones. Until that agreement exists, Factiva is
not in the registry and nothing is requested from it.

**Records.** `data/newsroom/newsroom.db` is newsroom-2 (`python -m second_order news upgrade`, after `news backup`,
adds `brief_reviews` and `material_assessments` in one transaction and keeps every row; a newsroom-1 store is read and
never written until then). `data/news-texts/` holds retrieval records, kept pages and text snapshots, all write-once.
Plans and draft files are the operator's (`data/newsroom/plans/`); the server never reads them.

## 11. Economic relevance (the third milestone)

The aim: the news is useful for what it includes and for what it leaves out. A story is listed as economic news only when
an assessment of what its sources report, or an editor, establishes that it is one. Publisher categories and keywords
decide nothing (news-rank-0.2's `no_subject` rule is gone). Every read below still only reads saved records.

**The annotation (relevance-annotation-0.1, `news_relevance.py`).** Prepared from the story's permitted material only
(reports whose publishers allow their use by a model; the same permission as for a summary), under the editorial scope
`economic-scope-0.1` stated in the prompt: `report_kind` (development, product_coverage, consumer_advice, opinion,
ceremonial, promotional, digest, other), `event_type` for a development (policy_decision, policy_proposal, enforcement,
official_data, official_statement, agreement, corporate_action, disruption, other_development), `change` with
`change_evidence`, `affected` (name, kind, evidence), `dimensions` (demand, revenue, costs, prices, production,
employment, financing, competition, regulation, trade, capacity; each with `how` and evidence), `scope` (reach and
stated magnitudes with evidence), `ambiguities`, `missing`, `verdict` (relevant, outside_scope,
insufficient_information) and `explanation`. Evidence is `{report, quote}`: `check_evidence` (relevance-evidence-0.1)
finds each quote in that report's headline, excerpt or retained text (NFKC, whitespace, typographic quotes and dashes,
case normalised; at least two words) and records where; a quote not found, or naming a report outside the material,
supports nothing. The annotation holds no number, score or confidence.

**The decisions (deterministic, versioned).** Relevance (relevance-decision-0.1): `relevant` only for a relevant verdict
on a reported development whose change is quoted and with at least one dimension supported by a quote; `outside_scope`
for an outside verdict, unless the item is a development whose sources support two or more dimensions; `insufficient`
for an insufficient verdict; any disagreement is `needs_review`. An editor's latest judgement (`relevance_reviews`,
with a reason; `cleared` withdraws it) decides instead. No permitted material: `restricted` (never sent to a model;
only an editor judges it). A failed attempt: `unavailable`, never outside the scope. Never assessed: `pending`. The
latest annotation of the current material decides; one of earlier material still decides, flagged `current: false`, and
the queue selects it again. Importance (news-importance-0.1): fixed points from the event type (policy_decision 1.0;
enforcement, official_data, agreement, disruption 0.75; corporate_action, policy_proposal 0.5; official_statement,
other 0.25), the reach (global or international 0.75, national 0.5, regional or sector 0.25) and 0.25 when a quoted
magnitude states its size. Freshness and topic priority are section 4's.

**Ranking (news-rank-0.3) and the views (news-stories-view-0.3, news-story-view-0.3).** Hot now holds current stories
established as relevant (or marked major by the editors), ordered by section 4's points plus the `importance` signal.
Latest and Your interests list relevant (or marked) stories. A view also carries `awaiting`: current stories (latest
report within HOT_HOURS) whose relevance is pending, restricted, needs_review, unavailable or insufficient, as cards
with `relevance: {state, statement}`, so nothing unprepared is hidden and nothing unassessed is presented as news; and
`left_out: {outside_scope, older_unassessed, statement}`. A story outside the scope keeps its page at its address. A
story page carries `relevance: {state, statement, basis (editor, model, assisted, synthetic or null), basis_label,
explanation, change, dimensions (supported ones only, for a relevant story), missing, current}`; Go deeper is
unavailable for a story outside the scope, and its source never includes the assessment (it is a reading, not
evidence). Brief batches take only listed stories; coverage adds `current_relevance` counts.

**Preparation (relevance_requests.py, relevance_batches.py, relevance_api.py).** The queue (`news relevance queue`,
`GET /api/admin/news/relevance`) lists every story with a report from the last 7 days, its state, basis, explanation,
importance and why a batch would select it next, with counts per state. A batch (`news relevance preview --method
model|assisted [--limit N] [--story ID] [--retry-failed]`, `POST /api/admin/news/relevance/batches {method, limit,
story_ids, retry_failed}`) selects, newest first, current permitted stories never assessed, assessed on earlier material
or under an earlier prompt (or failed ones when asked), or named ones, and is recorded write-once in
`data/newsroom/relevance-batches/<rbatch ID>/`. The paid method saves each exact request (relevance-prompt-1;
claude-sonnet-5-5, adaptive thinking, low effort, max_tokens 4,000, `output_config.format` = the annotation schema
without length limits, no tools, no sampling parameters, no fallback model; each text at most 12,000 characters) in
`data/newsroom/relevance-requests/<request ID>/` with its planning estimate; one approval repeating the batch ID and
total (`news relevance approve ID --estimated-max-usd-total X --approve-paid-requests`, `POST .../approval`) sends each
at most once, ever (resumable; a changed story is skipped). A reply is accepted only as one structured reply passing
the schema; anything else is recorded as a failed attempt. A new attempt is a new request in a new batch. The assisted
method exports a packet (`news relevance packet ID`: the same rules, format and material) and imports annotations
(`news relevance import ID --annotations FILE --assistant-tool NAME [--assistant-model NAME]`), refusing any that fail
the schema and recording the evidence check of the rest; the tool and model are as the operator declares, and no
usage or cost is invented. An editor's judgement: `news relevance review ID --verdict V --reason TEXT` or
`POST /api/admin/news/stories/{id}/relevance {verdict, reason, idempotency_key}`.

**Evaluation (relevance-eval-0.1, `relevance_eval.py`, `content/news-relevance/`).** `dev.json` (24 cases: real official
reports allowed for model use, frozen as their feeds gave them, and SYNTHETIC paired cases) and `sample.json` (24
fictional cases, a public sample for testing the tooling; it is not a holdout). Cases cover similar words with different
economic meaning, developments without financial terms, consumer coverage of large companies and ambiguous items. Pairs
never span the two sets. A holdout is a private, separate option: `--set holdout` reads only the file named by
`SECOND_ORDER_RELEVANCE_HOLDOUT` (or `content/news-relevance/private/holdout.json` when present) and refuses plainly
when there is none. Labels are `provisional` (the set author's judgement)
until an editor reviews them. `news relevance eval packet --set S` gives an annotator the material without labels;
`eval measure --set S --annotations FILE --annotator NAME [--record]` counts irrelevant items admitted, relevant items
excluded and held, lists every disagreement, and measures the keyword rule of news-rank-0.2 on the same cases. Editors'
corrections are kept with their reasons; turning one into a case is an explicit, versioned edit of a set. Nothing is
learned or adjusted automatically, and agreement on a small set with provisional labels is not calibrated accuracy.

**Records.** `data/newsroom/newsroom.db` is newsroom-3 (`news upgrade`, after `news backup`, adds `relevance_annotations`
and `relevance_reviews` in one transaction; older stores are read as they are and written only after it). Paid brief
requests are brief-prompt-3 (a structured output format; a brief-prompt-2 request, which forced a tool call that Claude
Sonnet 5.5 refuses, is never sent).

## 12. Breadth of coverage, matching and more sources (the fourth milestone)

The aim: a story says how many publishers and how many independent reporting origins cover it, breadth of independent
coverage counts in the order of the news, and different headlines about one development can be joined. Every read
below still only reads saved records; every request to a publisher or an index is an explicit operator action.

**Coverage (story-coverage-0.2, `news_stories.coverage`).** Publishers are counted apart from **reporting origins**. An
origin is one publisher, or several carrying one text (the same headline, nearly the same excerpt: Jaccard at least
0.8 over at least 12 words, or the same wire credit), recorded with `counted_together_because`. Each origin has a
`role`: `news` (a newsroom's reporting), `official` (a government or authority's own statement) or `company` (a
press release), and an `independence`: `established` when its text could be compared with the others, `unverified`
with `uncertain_because` when it could not (a headline-only newsroom, an indexed article). `possible_shared_origins`
lists pairs whose headlines or excerpts are similar (Jaccard at least 0.6) but not enough to join them. Counts:
`publishers`, `origins`, `news_origins`, `official_origins`, `company_origins`, `independent` (news and official
origins, whether or not their independence is established; renamed `reporting_origins` in story-coverage-0.3, which
also counts confirmed apart from possible origins: section 13), `uncertain`, plus section 3's `reports`, `repeats`, `official_releases` and `company_statements`. A card
(news-stories-view-0.4) carries the counts; a story page (news-story-view-0.4) also carries the units.

**Ranking (news-rank-0.4).** Section 4's points, with independent coverage replaced by **breadth**: each origin weighs
1 (a newsroom's reporting whose independence is established), 0.5 (unverified, or an official statement) or 0 (a
company's statement); the heaviest is dropped and every remaining unit of weight is 1 point, at most 3, as much as a day
of freshness. **Breaking**: 1 point for a new development of high assessed importance that at most one origin has
reported yet, so significant news first reported by one source is not outranked by older, wider coverage. Every
signal is shown to the reader in words.

**Matching (story-match-0.2, `news_matching.py`, newsroom-4).** Suggestions pair current stories (latest report within
7 days, first reports within 72 hours of each other) sharing at least 3 distinctive anchors and 3% of their anchors:
names from headlines and excerpts (generic official words and title-case headlines' capitals left out), figures (years
and small numbers left out) and the names a relevance annotation records as affected. A decision is explicit, with a
reason: `same` (the later story merges into the earlier), `related` (both linked to an ongoing topic, created or
named; separate developments stay separate) or `different` (recorded, never suggested again). `method` is `editor`, or
`assisted` with the assistant's tool and model as declared (only when both stories have permitted material).
`POST /api/admin/news/matches {story_a, story_b, decision, reason, topic_id?, topic_title?, idempotency_key}`; the desk
view lists `suggestions` and the last 30 `match_decisions`; `news match suggestions|decide`. Newsroom-4 adds the
append-only `match_decisions` table (`news upgrade`, after `news backup`; older stores read as they are).

**Sources (news-registry-0.3).** Adds the U.S. Department of Justice Antitrust Division (connected; public domain;
robots.txt crawl delay 10 s), the Bank of Canada (connected; RSS 1.0, read by `event_inbox`; reuse with credit and
changes indicated), and the SEC press releases and the UK ONS release calendar (connected, but requested only when the
operator declares a contact in `SECOND_ORDER_FEED_CONTACT`, which their terms require of automated clients; otherwise
`not_requested`). Material stays `permitted` only for official publishers whose terms allow reuse. Financial journalism
remains headline-only or not connected: among the 12 commercial and journalism providers whose terms were read on
2026-10-25 (docs/news-source-access.md), none grants AI summaries of its articles in a multi-user product without an
agreement; providers that were not examined are not covered by that finding.

**Other publishers' coverage through an index (news-index-0.1, `news_index.py`).** The GDELT Project's DOC 2.0 API
(free, keyless; display with a citation of GDELT) lists articles other publishers wrote. `news index lookup --story ID`
makes one request for one story: a query of the rarest content words of its own headline across current stories'
headlines (official boilerplate left out; at least 2), or, with `--words`, 2 or 3 words of the story's own headline or
excerpt chosen by the operator (`chosen_by: operator`; equally rare words cannot tell "wind turbines" from "parts"),
English-language coverage, from 1 day before the story's first report to 3 days after. The answer is recorded
write-once in `data/news-index/lookups/<story>/<lookup ID>.json` with every article and whether the matching rule
(news-index-match-0.2; 0.1 without plurals) accepts it: its title shares at least 2 query words, a word and its plural
alike,
or 1 and a figure of the story, or a proper name only this story names among current ones together with another word
of its headline; GDELT saw it within the window; https; not one of the story's own publishers. A 429 is recorded as
`rate_limited`, never retried automatically. `news index attach STORY LOOKUP --reason TEXT` adds the accepted articles
to the story as reports (source `gdelt-index`, publisher = the article's domain, material `none`, headline only, the
attribution "Indexed by the GDELT Project"). An indexed report never becomes material, never moves a story's times
and is `unverified` in coverage. `news index lookups STORY` lists the lookups. news-index-0.2 (section 13) records a
429's limit and the cooldown it starts.

**Official texts (news-texts-0.1, `ec-presscorner-text-0.1`).** The European Commission's press-corner pages are drawn
by a script, so their text is read from the press corner's documents service: for a page
`/commission/presscorner/detail/<lang>/<type>_<yy>_<n>` the one address requested is
`/commission/presscorner/api/documents?reference=<TYPE>/<yy>/<n>&language=en` (JSON; robots.txt does not disallow the
press corner; CC BY 4.0). The answer is kept under `raw/<sha256>.json`, and its title, publication date and HTML body
become a snapshot like any page's; attachments are named, not read. The fetcher sends the source's media type as
`Accept`.

## 13. Evidence that is the publishers' own, confirmed origins, and the index's limits (closing the fourth milestone)

**Go deeper's evidence (story-deeper-0.2, deeper-evidence-0.1, `story_deeper.assemble`, `deeper_evidence.py`).** A Go
deeper source holds the reports' own words between Second Order's framing: its opening lines (what it is, the story's
title, what is left out, and a new line saying that only the reports' own words can be quoted), each report's labels
(`Publisher:`, `Published (as the feed states it):`, `Address:`, `Headline:`, `Excerpt:`, `Text of the publication
(…):`, `Credit:`) and the note in square brackets on a shortened text. Only the publishers' words are evidence: each
headline after its label, each feed excerpt after its label, and each retained publication text (the part kept within
the source limit, never the note). `assemble` builds the text and records, in the same pass, where each passage is: a
span of `[start, end)` code-point offsets into the source text, the SHA-256 of the span's UTF-8 bytes, the report's
number, entry ID and publisher, and the part (`headline`, `excerpt` or `text`); the record also names the SHA-256 of the
whole text. Go deeper keeps it in the origin record (story-deeper-link-0.2: `evidence: {evidence_version,
source_sha256, spans}`, write-once) after checking it against the saved source.

**Binding and checking (research_analysis).** Preparing a research request of a capture that has a Go deeper origin
record copies the record's passages into the request's manifest (`evidence: {evidence_version, link_sha256,
source_sha256, spans}`), after checking them against the captured text. Every read of the request checks that binding
again: the origin record must still hash to `link_sha256`, its passages must still fit the captured text, and they must
equal the manifest's; otherwise the request does not verify (a user sees `internal_error`, and nothing is sent). A
reply to a bound request is read with those passages: each quote must lie **wholly inside one passage**, found exactly
or after making quotation marks, dashes and whitespace plain; an occurrence in the framing does not count, a quote that
runs from one passage into the next (across a label or a line between reports) does not count, and a quote found only
outside the passages refuses the whole reply ("not the publishers' own words"), as a quote that is not in the text at
all always has. The located quote is the first place inside a passage (so a headline the framing repeats is located in
its report), `occurrences` counts the places inside passages, and the quote carries `evidence: {report, publisher,
part}`; the Client's locator says "Report 2, Synthetic Ledger, its feed excerpt". The local mock and the browser
checks' simulated provider quote the passages too.

**What is unchanged.** A source the user pastes, types or imports has no Go deeper record: its whole captured text is
its evidence, its request manifest has no `evidence` field and its quotes have no `evidence` attribution, exactly as
before. Every request prepared before this change has no binding, and its recorded results are read exactly as they
were recorded (the same outcome, the same view and the same fingerprint, so reviews stay bound). A source Go deeper
saved under story-deeper-0.1 (no passages recorded; none exists on this server's real records) keeps its analyses and
results, but is not analysed again: preparing, quoting or running a request of it is refused with `source_unmarked`
(409; nothing is prepared, reserved, counted or sent), and Go deeper makes a new, marked source of the same material
instead of reusing it. Admin: an operator's mock or paid send of such a request is refused the same way.

**Confirmed and possible origins (story-coverage-0.3).** The reporting origins (news and official) are counted by
whether their independence is established: `confirmed_news`, `confirmed_official` (established) and `possible_news`,
`possible_official` (not established: a headline-only newsroom, an indexed article, an origin similar to another).
`independent` is renamed `reporting_origins` (news plus official origins), because it never meant that each was
independent. The card's sentence never calls an origin independent first and qualifies it afterwards: "4 reports from 4
publishers: 2 confirmed reporting origins (1 newsroom, 1 official statement) and 1 possible origin (1 newsroom) whose
independence is not established; 1 copy counted with its origin." A single origin is "1 reporting origin". The
ranking's coverage sentence follows the same order: "From 3 publishers: 1 confirmed reporting origin (1 official
statement) and 2 possible origins (2 newsrooms) whose independence is not established, which count half." The
weights (news-rank-0.4) are unchanged. The admin desk lists confirmed and possible origins.

**The index's limits (news-index-0.2).** A 429 is recorded with what the answer said (`rate_limit: {retry_after,
message, consecutive, cooldown_seconds, cooldown_until}`; at most the first 300 characters of the answer's text) and
starts a cooldown: 15 minutes after a first 429, twice as long after each further 429 in a row, or longer when the
answer's Retry-After asks (seconds or an HTTP date), at most 24 hours. Until `cooldown_until`, `news index lookup` is
refused before any request (`index_cooling_down`, naming the time; nothing is recorded), and a run of several stories
stops there; the first answer that is not a 429 ends the run of 429s. Lookups recorded before 0.2 have no `rate_limit`;
their cooldown is computed from their time by the same rule. `news index status` (read-only) shows the cooldown and,
for each looked-up story, its lookups, the articles attached from them, when the index last answered for it and its
newest lookup's outcome. Attached articles are kept whatever a later lookup answers, and a story page's indexed
source says it was kept from a lookup attached at a given time and is not checked again unless an editor looks the
story up again. Requests stay explicit operator actions: one request per lookup, no retry, no redirect, at least 6
seconds apart in a run.


## Coverage-order amendment (26 October 2026)

The additive `coverage` view and `/news/coverage` route appear as **Most covered**. It reads the same eligible set as
Hot now and orders by uncapped reporting-origin weight: confirmed newsroom 1, official or unverified possible 0.5,
company 0. Copies share a unit; publisher or article counts never break a tie. Ties use Hot now score, latest report,
then story ID. Hot now's ranking is unchanged and remains available for significant single-source news. The reply's
`rank.order_version` is `news-coverage-order-0.1`; `rank.statement` explains the order and its limits. Existing views
and `news-rank-0.4` points are unchanged. This is an additive view under user-api-0.5/news-stories-view-0.4: older
clients never request it, and updated clients continue reading the earlier views. Opening it sends only cached GETs.

Registry 0.4 adds Census economic indicators and RBA media releases, with attribution and the publishers' access
conditions. Feed dates retain their meaning, a new source never establishes relevance by itself, and every new entry
still needs an accepted assessment before appearing in the economic feed. See `news-feed-expansion-2026-10-26.md` (private; not in the public repository)
for the exact source checks, real-data import, AI-assisted/unreviewed briefs, the withdrawn BEA probe, and verification.

## Newsroom-sources amendment (26 October 2026)

**Registry (news-registry-0.5).** Three newsrooms are connected under their own terms: Voice of America
(`voa-news`, public domain: headline, excerpt and material), Global Voices (`globalvoices`, CC BY 3.0: headline,
excerpt and material, each report credited to its author) and Inter Press Service (`ips-economy`: headline and link
only, never material). A newsroom may be material only when its own text is public domain or openly licensed; company
statements never are. The Conversation and Agência Brasil are recorded as `not_connected` with their reasons. Sources
examined and the terms read: `docs/news-source-access.md`; the increment's evidence:
`docs/news-newsroom-sources-2026-10-26.md` (private; not in the public repository).

**Other publishers' work in a feed (event-inbox-parser-0.2, `feed_credits.py`).** A publisher feed may name creators whose entries are
not the publisher's own (`excluded_credits`, compared without case: VOA's wire agencies, IPS's "External Source") and
patterns marking republished partner work (`excluded_markers`: Global Voices). Such an entry is skipped before anything
of it is kept, with its reason in the retrieval record; a full-article element read to find a marker is never kept.
Every other source is parsed exactly as by event-inbox-parser-0.1, and each retrieval record names the version that
read it. A source whose licence asks for its creator to be credited (`credit_creator`) keeps `creator` with each entry
in its record and archive (part of the entry's fingerprint only where present; every existing record, archive and
fingerprint is unchanged), and its reports' `attribution` reads "By <creator> for <publisher's credit>".

**Interests on a story.** A story's interest found only by a word of its reports (`basis: terms`) whose economic
dimension the relevance assessment did not support is no longer listed when that assessment established the story as
relevant: "trade" needs the `trade` dimension and "employment" the `employment` dimension. A publisher's own topic, an
editor's judgement and an unassessed story keep every interest their words give. No payload shape changes; Your
interests filters on the same list.

## Economic-explanation amendment (26 October 2026)

`docs/news-economics-2026-10-26.md` (private; not in the public repository) has the full account.

**Versions.**
- story-brief-0.3: a brief's `content` may hold `economics` (econ-explanation-0.1, `second_order/story_economics.py`);
  versions without it keep their earlier shape.
- news-stories-view-0.5 and news-story-view-0.5:
  - story cards' `brief` adds `authorship`, `review` and `explained`;
  - source rows add `name`, distinct when a publisher has several feeds;
  - the story page adds `explanation: {state, statement, reason}` (news-explanations-0.1) and `brief.economics`, the
    reader view: rendered texts, each statement's kind, figures and calculations with units, periods, bases and
    vintages, framework notes with their sources, and cited context items.
- The Client's readers (`frontend/src/contracts/economics.ts`) refuse an explanation that contradicts itself.

**Evidence.**
- Figures must quote their evidence (the material's reports, or a context bundle's items, econ-context-0.1).
- Derived figures are computed by econ-calc-0.1.
- A channel's framework note (econ-framework-0.1) must apply to the story's instrument.
- econ-guard-0.1's findings are recorded with the version, under the brief guard's findings, and stop publication.
- Each version's `preparation.analysis` names the analysis, calculation, guard and framework versions, the framework's
  SHA-256 and the context bundle.

**Batches (news-batch-0.2).**
- Stories whose published brief lacks a current explanation are selected; the action is `explain`.
- `preview --backfill` selects listed stories newest first, bounded by `--limit`.
- `import --check` saves nothing; refused imports are recorded under `batches/<ID>/imports/`.
- Batch identity includes the analysis version, the framework and each item's context bundle.
- New commands: `news context build|show` and `news framework` (read-only).

**Paid path.** Model drafts use brief-prompt-4, whose output format includes `economics`, with max_tokens 12,000.
Requests saved under brief-prompt-3 are superseded.

**Wording.**
- The News lede describes the workflow.
- Card labels come from each brief's method and recorded reviews.
- Origin summaries keep confirmed apart from possible origins.
- Stories without a completed assessment say so.
- The guard's statement no longer claims that editors read every brief.

## Economic-explanation correction amendment (26 October 2026)

`docs/news-economics-review-2026-10-26.md` (private; not in the public repository) has the full account. Versions saved under the earlier amendment keep their
shape and are read as they were saved.

**Versions.**
- econ-explanation-0.2: each channel adds `support` (`framework`, `event_evidence` or `bounded_inference`), and an
  explained version embeds `framework`: the exact notes it used, with their sources, digests, the framework's version,
  statement and SHA-256. econ-explanation-0.1 versions are still read.
- econ-calc-0.2: figures add `sign` (`as_quoted` or `from_words`) with `sign_words`, `bound` (`exact`, `lower_bound`,
  `upper_bound`, `approximate`), `statistic` (`observed`, `mean`, `median`, `other_summary`, `not_stated`) and
  `stock_flow` (`stock`, `flow_per_month`, `flow_per_quarter`, `flow_per_year`, `flow_annual_rate`,
  `not_applicable`); the stored figure adds `direction_check`. Operations: `difference`, `percent_change`, `share`,
  `stock_to_flow` and `deflate` (observed values only); `ratio` is no longer accepted and is read only on older
  versions. Calculations add `bound` and `calc_version`.
- econ-guard-0.2 adds `sign_contradicted` and `sign_unclear`.
- econ-framework-0.2 (13 notes; adds `inventory-ratio`). Each framework version is archived as
  `second_order/econ_framework_archive/<SHA-256>.json` and recovered only when its content still has that SHA-256.
- news-explanations-0.2: an explanation is current only for the material it was prepared from, the current analysis,
  calculation and guard versions, and unchanged notes; otherwise `outdated`, with each reason.
- Reader view: `brief.economics.background: {state, framework_version, framework_sha256}`, where state is `recorded`
  (the version's own snapshot), `recovered` (the archived framework with the recorded SHA-256) or `unavailable` (said
  so; no notes are shown and today's notes are never substituted). Channels add `support` and `support_label`;
  figures add `statistic_label`, `stock_flow_label`, `bound`, `sign_basis` and `direction_warning`; calculations add
  `bound`.
- The Client's reader accepts both explanation versions and refuses an unreadable background, an `unavailable`
  background that shows notes, or an unknown support.

**Paid path.** brief-prompt-5 carries the 0.2 rules and output format; nothing was sent.

## Economic-explanation coverage amendment (26 October 2026)

`docs/news-economics-coverage-2026-10-26.md` (private; not in the public repository) has the full account. Earlier versions and bundles keep their shape and
are read as they were saved.

**Context (econ-context-0.2).**
- Every item has a `role`: `event_evidence`, `comparison`, `methodology` or `benchmark`.
- Every item has a `relevance` (why it is there) and a `timing` against the story's first report: `before`,
  `same_day`, `after` or `unknown`.
- Supplied and methodology items add `retrieved`. Publication items add `reported_at`, the other story's first report,
  used when a feed's date does not parse.
- A bundle adds `story_first_reported` and `cutoff`.
- Supplied items have exactly: `kind` (`observation`, `expectation` or `methodology`), `role`, `source`, `url`,
  `published`, `as_of`, `retrieved`, `text`, `terms` and `relevance`. Their role must fit their kind.
- `news context build` adds `--methodology` (the library's passages for the story's series), `--earlier-release` (the
  previous release of the same series, matched by feed and title) and a `--why` for each `--with-story`.
- `news context suggest STORY` is read-only.
- The methodology library is `second_order/econ_methodology.json` (econ-methodology-0.1), with three Census series.

**Explanations (econ-explanation-0.3, econ-guard-0.3, news-explanations-0.3).**
- A cited context item keeps `role`, `relevance`, `retrieved`, `timing` and `story_title`.
- The guard adds `retrospective_as_event`.
- A bundle built for the current material after an explanation was prepared makes it `outdated`, with the reason
  "newer context was gathered for this story after it was prepared".
- Reader view context rows add `role`, `role_label`, `relevance`, `retrieved`, `timing`, `timing_label` and
  `retrospective`. The brief view adds `context_statement` (null when the explanation used no context).
- The Client's reader accepts explanation versions 0.1 to 0.3. It refuses a context row with an unknown role or
  timing, a retrospective mark that disagrees with its timing, and a brief whose explanation cites context while
  `context_statement` is null.

**Coverage baselines (news-baseline-0.1).**
- Write-once records live in `data/newsroom/baselines/<baseline ID>.json`.
- Commands: `news baseline record --label …`, `news baseline progress ID` (read-only) and `news baseline list`
  (read-only).

**Paid path.** brief-prompt-6 adds the coherence, precise-reading and context rules. Requests state each item's role,
timing and relevance. Nothing was sent.

## Update-run amendment (27 October 2026)

`docs/news-update-workflow-2026-10-27.md` (private; not in the public repository) has the full account. Earlier records, batches and payloads keep their shape.

**Update runs (news-update-0.1).**
- A run is write-once under `data/newsroom/updates/<run ID>/`:
  - `run.json`: the cutoff, the reference time and its basis, its own coverage baseline, and the reports and stories
    held at the cutoff;
  - `refresh-started.json` and `refresh.json`: each source's outcome and the grouping;
  - `steps/*.json`: texts, relevance and brief previews, and context.
- The run ID is made from the start's idempotency key.

**Admin routes (admin-api-0.4).** Administrators only. Each write needs the admin header, the account binding and a
strict body.
- `GET /api/admin/news/updates`: the plan and the runs. Reads only.
- `POST /api/admin/news/updates` `{label, official, idempotency_key}`: starts a run (201, or 200 for the same key). A
  second run is refused while the latest has not refreshed (409 `update_open`).
- `GET /api/admin/news/updates/{run_id}`: the report. Reads only.
- `POST /api/admin/news/updates/{run_id}/refresh` `{}`: requests each planned source once, under the usage policy's
  refresh cooldown and budget.
  - Refused for a run that is not the latest (409 `not_latest_run`), a second time (409 `already_refreshed`), or after
    an interruption (409 `refresh_interrupted`).
  - A refused refresh is not counted against the budget.
- `POST /api/admin/news/updates/{run_id}/texts` `{}`: the run's permitted texts, counted against the daily publication
  requests, once per run.
- `POST /api/admin/news/updates/{run_id}/relevance` and `/briefs` `{method, limit}`: previews of the existing batches
  for the run's stories. Nothing is sent.
- `POST /api/admin/news/updates/{run_id}/context` `{}`: bundles from structural options.
- Approvals, imports and publications stay on the batch routes and commands.

**Report fields.**
- Each arrival's `class` is `published_since`, `published_before` or `time_unknown`.
- Each story's `kind` is `new_development`, `topic_development`, `additional_reporting`, `discovered_late`,
  `time_unknown` or `revised`.
- Each story carries its `tone` (`todo`, `attention`, `failed` or `done`), the `next` action and the `step` that does it.
- `completed`, `attention` and `failed` are lists of plain statements; `next` holds each action's command.
- `counts` holds `before`, `after` and `run`.
- `paid` holds every saved request with its `attempt` and `skipped` reason, `sendable` and `sendable_estimate_usd`.

**Matching (story-match-0.2, unchanged version).**
- `topic_candidates` lists ongoing topics a story may continue.
- A `related` decision with an existing topic links only the story not yet in it.

**Relevance selection.** A story whose latest attempt for its current material failed is selected again only with
`retry_failed`, even when an earlier material's annotation still decides its state.

**Story view (news-story-view-0.6).**
- The brief adds `revisions`, `{earlier, changes, updated_at}`:
  - `earlier` lists the versions readers were shown before, newest first, each with `version`, `published_at`,
    `prepared_at`, `method` and `authorship` as corrected, `recorded_as` (the method first recorded, when a correction
    changed it), `corrects`, `headline`, `summary`, `reports` and `explained`;
  - `changes` says what the current version changed against the last of them: the reports added or dropped, the texts
    used, the explanation, its context, who prepared it, or that it corrects authorship.
- The Client refuses revisions that contradict themselves:
  - earlier versions without changes or an update time;
  - the current version listed as an earlier one;
  - an authorship that disagrees with its method;
  - a "correction" to the same method.

**Rendering.** A figure whose bound the sentence already states ("up to {f1}") is shown without its own bound word in
that sentence.

## Brief-request repair amendment (27 October 2026)

After the T-MED trial's brief request was rejected (HTTP 400, `invalid_request_error`; see
`docs/news-live-trial-result-2026-10-27.md` (private; not in the public repository)). Earlier records keep their shape and are read as before.

**Provider-error diagnostics (provider-error-0.1).** A non-success reply is checked for the credential first, as
before. If it does not carry the key, an attempt keeps:
- `http_status` and `error_type` (a plain word);
- `message`: the provider's error message, with control characters and line breaks flattened, credential-shaped text
  replaced by `[redacted]`, and at most 500 characters (`message_truncated` says when it was cut). It is dropped
  whole if it still carries the key;
- `request_id`: the provider's request ID (`req_…`), from the `request-id` header or else the body;
- `body_bytes` and `body_readable`.

No other header, no authorization data and no raw body is kept. The text recorded as `detail` is unchanged. A reply
carrying the key is still refused and keeps nothing but its status.

**Where it is kept.**
- A brief draft's and a relevance request's `outcome.json` add:
  - `exchange`: `{request_sha256, sent_at, answered_at, http_status, request_id}`, for every attempt, successful or
    not;
  - `provider_error`: the diagnostics above, for a non-success reply.
- `attempt_state` adds `request_id` and `provider_error`. An outcome recorded before this amendment has neither,
  and reads as `null`.
- A research attempt's and a paid draft's manifest add `provider_error`.
- No attempt is retried, and the one-attempt rule is unchanged.

**Output-format check (output-schema-check-0.1, `second_order/output_schema.py`).** An offline check of every format
the project sends:
- the documented structured-output rules: supported keywords; `additionalProperties: false`; `minItems` 0 or 1;
  simple enum members; at most 16 unions and 24 optional parameters;
- the official Python SDK's rule that every node has a `type`, `anyOf` or `allOf`;
- a precaution: no union inside another union.

Passing the check does not show that the provider accepts a request.

**Brief request (brief-prompt-7).** Only the output format and the matching prompt sentences change:
- every enum states `"type": "string"`;
- `economics` is a required object. When the evidence cannot support an explanation, its status is
  `insufficient_evidence` (no longer `null`);
- `headline`, `summary` and `insufficient_material` are text, never `null`. An empty `insufficient_material` means the
  material was not judged insufficient.

The format has 8 unions, none nested (brief-prompt-6 had 12, 8 of them nested), and no optional parameter. The reply
is checked exactly as before:
- an empty headline or summary is refused, not filled;
- the explanation's rules, quotations, calculations and context boundaries are unchanged.

The planning estimate assumes 1,000 tokens for the output-format system prompt the provider adds, whose size is not
published. It previously counted the 286-token tool-use system prompt. The figure is still not a billing ceiling.
Requests saved under brief-prompt-6 or earlier are superseded (409 `request_superseded`) and never sent. The
refusal no longer says the model refuses their shape, which is unproven for brief-prompt-6.

**Update report (news-update-0.1, unchanged version).**
- A model brief batch saved under an earlier prompt no longer awaits approval, and its stories return to the briefs
  step.
- Each of its unsent requests is `skipped`, with the reason that an approval refuses its earlier request contract.
- The attention line says an approval "would send none" and names the reasons the server gives.
- The Admin paid line repeats those reasons instead of assuming the stories changed.

## Two-stage brief drafts amendment (27 October 2026)

After the provider rejected the single brief request's output grammar as too large twice (brief-prompt-7 and
brief-prompt-8; `docs/news-brief-wire-result-2026-10-27.md` (private; not in the public repository)), a model draft of a brief and its explanation takes two
requests, each approved on its own (brief-prompt-9, brief-stages-0.1, brief-drafting-0.2;
`docs/news-brief-stages-2026-10-27.md` (private; not in the public repository)). Earlier records keep their shape and read as before; the single requests up
to brief-prompt-8 are superseded (409 `request_superseded`) and never sent. The assisted packet's rules and content
shape (`brief_contract`) are unchanged, and every version still passes the same content checks.

**Story drafting (`POST /api/admin/news/stories/{story_id}/drafting`, `news drafting preview`).** The reply describes
the workflow: `state` (`awaiting_stage_1`, `awaiting_stage_2`, `complete`, `stopped`), `detail`, `next_stage`, and
`stages`, two rows each with `name`, `does`, `stage_version`, `draft_id`, `request_sha256`, `max_tokens`, `estimate`,
`estimate_kind` (`exact`, `planned` from the largest first stage the limits allow, or `not_needed`), `attempt`,
`usage_cost` and, for stage 1, its checked `foundations` (status, counts, directions the guard would stop) or, for
stage 2, `bound_to` (the first stage's request and foundations SHA-256). `combined` gives the planning estimate of both
stages, what remains to approve and the usage reported so far. The top-level `draft_id`, `stage`, `request_sha256`,
`max_tokens`, `estimate` and `attempt` are the request an approval would send now (or the last one attempted). The
preview saves that request once; it sends nothing.

**Approval (`POST /api/admin/news/drafting/{draft_id}/approval`, `news drafting approve`).** Serves either stage's
request (`brief-s1-…`, `brief-s2-…`) with the same fields as before; one attempt per exact request, ever. New refusals,
before anything is reserved: 409 `inputs_changed` (the context bundle, the framework notes or the validated first stage
changed since the request was prepared) and 409 `request_conflict` (different bytes under a saved ID). A validated
stage 1's reply adds `next`, the prepared stage 2 (not sent). Outcomes add `validated` (stage 1 passed; its
foundations are kept) and record `response_id`.

**Batches.** A model batch item's `draft` names its `stage`; the batch adds `stages` and
`followup_estimated_max_usd_total` (stage 2 of its stage-1 items, planned and not approved by it). A story whose draft
stopped is listed in `left` with `drafting`. Approval items add `stage` and `next`. A later preview of the same stories
makes a new batch of their stage-2 requests. The desk's `drafting` status gives `max_tokens_by_stage` instead of
`max_tokens`. The update plan's `paid.briefs` adds `stages`; report requests add `request_stage`, and a validated stage 1
counts as progress, not a failure.

**Versions.** A two-stage version's preparation records both stages: `model.draft_ids`, `model.stages` (each stage's
request, approval, estimate, response ID, usage and usage-derived cost) and `model.usage` (both together); `cost.stages`
and `cost.usage_cost` (both together). Its guard findings may add `placeholder_in_brief` and `unsourced_number` for the
brief's own texts (brief_stages.coherence); they stop publication, like the other findings.

## Economic-fidelity amendment (28 October 2026)

econ-fidelity-0.1 and brief-stages-0.2 / brief-prompt-10 (`docs/news-econ-fidelity-2026-10-28.md` (private; not in the public repository)). The analysis,
calculation, guard and framework versions are unchanged, so no published explanation becomes `outdated`.

**Reader view (`brief.economics`).**
- Each rendered text writes a figure or calculation with the qualifiers its sentence does not already state, from the
  figure's stated metadata only: an annual rate with its seasonal adjustment ("676,000 houses (seasonally adjusted
  annual rate)"), a seasonal adjustment, a stated nominal or inflation-adjusted basis, a summary statistic of survey
  answers, and a margin its quote writes beside the number ("stated margin ±13.8%, wider than the change").
- Compact references (`Ref.label`) carry the same qualifiers, with a figure's period and vintage label.
- Assumptions are rendered like the other explanation texts.
- Figures add `margin` (the margin as its quote writes it, or null). `basis_label` is null for "not stated" when
  nominal or real cannot apply: a quantity that is not money, a rate or a share. A stated basis is always shown.
- The Client accepts a figure without `margin` (saved before) and refuses one whose `margin` is not text or null.

**Versions.** A new version's `guard` adds `fidelity_version` and may add `unresolved_reference`, `reference_in_label`,
`category_not_in_evidence` and `scale_mismatch` (with `placeholder_in_brief` for a version of any method). They stop
publication like the other findings. A finding the two-stage coherence check also makes is recorded once. Earlier
versions keep the guard they were saved with.

**Drafting.** Requests saved under brief-stages-0.1 (`brief-evidence-1`, `brief-explanation-1`, `brief-summary-1`)
are superseded (409 `request_superseded`) and never sent; their records read and decode as before. A stage-2 request
lists only the framework notes that apply to its development's instrument. The assisted packet's contract
(`brief_contract`) is unchanged.

## Evidence-form amendment (28 October 2026)

econ-explanation-0.4, econ-framework-0.3, econ-calc-0.3, econ-fidelity-0.2, brief-stages-0.3 / brief-prompt-11 and
news-explanations-0.4 (`docs/news-econ-form-subject-2026-10-28.md` (private; not in the public repository)).

**What changed (`economics.change`).** From 0.4 it records three things apart:
- `instrument`: the subject, what the development changes or describes. `official_statistic` is no longer a subject. The
  new subjects are `economic_activity`, `labour_market`, `housing` and `inflation`.
- `form`: how the evidence was produced: `reported_observation`, `survey_answers`, `forecast_or_scenario`,
  `announcement_or_decision`, `statement` or `unclear`.
- `respondents`: whose answers a survey reports (`banks`, `firms`, `households`, `other`, `not_stated`), or null for
  any other form.

A form takes only the stages it can have; for example, a survey is an `observation` and a forecast is a `forecast`. A
framework note applies only where its subjects, forms and respondents all match. Under 0.4 a survey's net percentage
is figure measure `net_percentage`: in percent, `statistic` `other_summary`, and never a calculation's input. A
`share` lies between 0% and 100%.

**Reader view (`brief.economics`).**
- `summary` adds `form_label`, `respondents_label` and `classification_note`.
  - A 0.4 explanation always gives `form_label` and no note.
  - An earlier one gives no form and a `classification_note` saying its form and respondents were not recorded.
- The Client accepts all three missing (saved before 0.4).
- The Client refuses a 0.4 explanation without `form_label`, and any of the three that is not text or null.
- A net percentage's `statistic_label` says what it is, and rendered texts write it with "net percentage of
  respondents".
- `analysis_version` may be `econ-explanation-0.4`.

**Currentness (news-explanations-0.4).**
- An explanation saved under `econ-explanation-0.3` / `econ-calc-0.2` is read under that contract and is not outdated
  for its version alone.
- It is outdated only when, from what it recorded, a 0.4 rule shows it is affected:
  - a share outside 0% to 100%;
  - or a note it used that no longer applies to its recorded subject or stage.
- A note counts as revised when what readers read of it changed.
- A 0.4 explanation is outdated when a note it uses no longer applies to its subject, form and respondents.

**Versions.**
- **Guard:** a new version's `guard` records `fidelity_version` `econ-fidelity-0.2`, and may add
  `net_percentage_as_change` (a net percentage written as the size of a change).
- **Drafting:** requests saved under brief-stages-0.2 (`brief-evidence-2`, `brief-explanation-2`, and
  `brief-summary-2` saved under 0.2) are superseded. They are never sent, and their records decode with their own format
  (`STAGE_1_SCHEMAS`).
- **Assisted packet:** its contract (`brief_contract`) adds `form` and `respondents` to `change`. The batch packet lists
  `subjects`, `forms` and `respondents` in place of `instruments`.
- **Earlier checks:** `checked_content(…, analysis_version=)` reproduces an earlier check with that version's
  calculations and framework.

## Net-balance prose amendment (29 October 2026)

econ-fidelity-0.4, brief-stages-0.4 (`brief-evidence-4`, `brief-explanation-4`) and brief-prompt-12
(`docs/news-net-balance-prose-2026-10-29.md` (private; not in the public repository)). No reader field, API shape or Client contract changes. econ-fidelity-0.3
existed only at commit `3b31771` and was recorded by no saved version: it let any "of" after a balance pass, and 0.4
reads a change verb before the number first.

**Guard record.** A new version's `guard` records `fidelity_version` `econ-fidelity-0.4`. Two rules now read every
text of a version against its typed figures, not only the explanation's `{f1}`:
- `net_percentage_as_change`: a typed net percentage written as the size of a change, now also as a number in the
  brief's own texts (headline, summary, facts, implications, themes, uncertainties, missing items) and in names and
  observables.
- `net_percentage_reason_unattributed` (new): a sentence carrying a net percentage that gives a reason without saying
  who gives it.

Both stop publication only. A saved version keeps the guard it was recorded with, until an explicit revalidation
appends a new version.

**Drafting.**
- **First stage:** from `brief-evidence-4` a reply whose own facts, themes, missing items or what-changed text break
  either rule is refused (`invalid`) before any second stage is prepared. The rule it uses is pinned
  (`RETAINED_CHECKED`: `brief-evidence-4` → `econ-fidelity-0.4`).
- **Saved foundations:** they record the stages version of the contract they were checked under (`STAGES_OF`), so an
  earlier reply rechecked reproduces its record.
- **Earlier requests:** requests saved under brief-stages-0.3 (`brief-evidence-3`, `brief-explanation-3`) are
  superseded and never sent; their files stay as they were.
- **Formats:** both stages' output formats are unchanged, byte for byte.

## Claims, conditions and procedural stage amendment (29 October 2026)

story-brief-0.4, econ-explanation-0.5, econ-fidelity-0.5, brief-claims-0.1, brief-stages-0.5 (`brief-evidence-5`,
`brief-explanation-5`, `brief-summary-3`), brief-prompt-13 and brief-assisted-3
(`docs/news-claims-conditions-2026-10-29.md` (private; not in the public repository)).

**Brief content.** A version may record `claims` (at most six): `{id: "k1"…, holder, holder_name, modality, quote,
condition, source}`.
- `holder`: `issuer`, `speaker`, `interviewer`, `operative_text`, `respondents` or `other_party`.
- `modality`: `asserted`, `conditional`, `prospective`, `view` or `question`.
- `quote`: the claim's exact words in `source` (`report:<ID>` or `context:<ID>`).
- `condition`: words inside the quote, required for `conditional`, otherwise null unless the claim is a question or
  prospective.

Each fact of such a version names its claims (`facts[].claims`, possibly empty). A version without `claims` keeps the
earlier shape and reads as before; `facts[].claims` without `claims` is refused, and so is the reverse.

**Brief view.** `brief_version` is `story-brief-0.4`. For a version that records claims, the view adds `claims:
{claims_version: "brief-claims-0.1", statement, claims: [...]}`. Each row is the claim with `holder_label`,
`modality_label`, `reports`, `link` and `facts` (1-based numbers of the facts citing it). The key is absent for a version
that records none.

**Explanation.** `econ-explanation-0.5`:
- **Stage:** `procedure` (label "Procedure opened, no decision on a measure"); a conditional stage.
- **References:** `claim:kN` in any basis.
- **Figures:** a figure bound to a claim that is not stated as so adds `claim_label`, present only when the brief records
  claims.
- **Earlier versions:** econ-explanation-0.4 explanations are read as current, with their own stage table.

**Guard record.** A new version records `fidelity_version` `econ-fidelity-0.5`. Two new publication stops:
- `claim_only_number`: a number the evidence writes only inside claims that are not stated as so, in a headline (when
  they are questions, conditions or views) or in a fact or an explanation text with a basis that does not cite one of
  them.
- `bound_dropped`: a headline number equal to a typed bounded figure written without a bound of that kind.

**Drafting.**
- **First-stage facts:** in `brief-evidence-5` each fact carries `claim_holder`, `claim_holder_name`, `claim_modality`,
  `claim_quote` and `claim_condition` (each `""` when it records none). The claim's source is found by the application.
- **Earlier contracts:** `STAGE_1_SCHEMAS`, `ANALYSIS_OF` and `STAGES_OF` pin each earlier contract literally.
  Requests saved under brief-stages-0.4 are superseded and never sent.
- **Assisted packet:** brief-assisted-3 requires `claims` (possibly empty) and every fact's `claims`.
- **Revalidation:** an unchanged revalidation checks and records an explanation under the analysis version it was
  saved with.
