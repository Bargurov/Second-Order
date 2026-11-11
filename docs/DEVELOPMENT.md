# Second Order: development and operations guide

How to install, run, test and operate Second Order, and how each screen and command behaves. The
[README](../README.md) is the short overview; [SPEC.md](../SPEC.md) is the specification, with every rule
and version, and [AGENTS.md](../AGENTS.md) holds the project rules. This guide was the README until
2026-11-08; its sections are unchanged apart from this introduction, the paths of its links and the
verification note under Run.

The application runs locally. Start with [Run](#run) for the requirements and the first run.

## Contents

- [What the app contains](#what-the-app-contains)
- [Run](#run)
- [Accounts, credits and daily limits](#accounts-credits-and-daily-limits)
- [News: stories, shared briefs and Go deeper](#news-stories-shared-briefs-and-go-deeper)
- [Offline Dossier](#offline-dossier)
- [What is implemented](#what-is-implemented)
- [Model drafting adapter (offline)](#model-drafting-adapter-offline)
- [Market snapshots (FRED)](#market-snapshots-fred)
- [Market snapshots from a kept H.15 release package](#market-snapshots-from-a-kept-h15-release-package)
- [Freezing from the interface (Hypotheses)](#freezing-from-the-interface-hypotheses)
- [Assessing from the interface (Hypotheses)](#assessing-from-the-interface-hypotheses)
- [Reading a score](#reading-a-score)
- [Fixture limitations and provenance](#fixture-limitations-and-provenance)
- [Scope](#scope)

## What the app contains

Second Order freezes an economic hypothesis, then measures whether later market observations are
consistent with it. Around that core it holds research views of releases, commodities and one company.

This repository contains a small offline research core and local screens:

- for a signed-in user, the Client: News at `/` and `/news` (stories from the feeds, shared
  briefs prepared by the editors, ongoing topics, and Go deeper into an analysis of one's own;
  see **News: stories, shared briefs and Go deeper**), and their own sources and analyses at
  `/sources` and `/analyses`;
- the Tracker at `/`, which lists prepared cases (the operator's build);
- the Dossier at `/h/:id`, shown here for two manually reconstructed showcase replays of
  fictional events;
- the Case library at `/library`: twenty-seven retrospective editorial case studies of
  official releases and news items, twelve macro releases from 2025, twelve 2026 releases
  across five sectors and three 2026 WTO news items;
- a research view at `/library/research/semiconductor-policy`: a retrospective comparison
  of ten selected BIS releases on advanced chips and chip-making equipment, every quoted
  passage checked against the retained sources;
- a copper thesis at `/theses/copper`: a versioned research view of copper's physical supply
  and demand, with the status of each reason and risk and who is exposed, every source
  checked against its acquisition record on each read (listed in the Case library);
- the Method page at `/method`, which explains the implemented measurement rules and
  their limits;
- My analyses at `/analyses`;
- Hypotheses at `/hypotheses`: freeze a manual hypothesis or a reviewed model draft on the
  Board's H.15 yields with one explicit approval, and reopen frozen records read-only;
- Market context at `/market-context`;
- a private overview of one event at `/events/…`, and an evidence-first research analysis of
  a saved event at `/events/capture/:id/research`;
- the retained BIS snapshot at `/inbox/bis-snapshot`: BIS's News & Updates page as retained
  once, browsed as local records and imported into the Event inbox only on request.

The Tracker's Event inbox lists official monetary-policy, employment and inflation
releases, energy analysis articles and international trade news from five publisher
feeds, refreshed only on request. It can start the Analyze an event form from an entry,
and it keeps headlines locally after they leave their feeds. Headline triage sorts a
selection of its entries, reusing saved results and requesting only missing work after
an explicit approval. Market context shows daily Treasury yields around selected Federal
Reserve and BLS events from local data, and requests missing data only after an explicit
approval.

An offline Claude drafting adapter exists. Its live paths are a gated pilot on synthetic
cases, one explicitly approved Tracker request per captured event, and one approved
headline-triage request per prepared selection. Each path is available only on a server
started for it, and the tests exercise them against simulated providers. Single real
runs were made on the author's machine:

- one paid draft (2026-10-05);
- one paid headline-triage request (2026-10-09);
- one keyless Board download (2026-10-10, after an earlier attempt returned an empty
  page);
- one keyless download of the Board's H.15 release package (2026-10-10 UTC), made by a
  standalone, separately approved source-inspection script, not by the app. The app's
  own package transport has not sent a real request;
- one explicitly authorized Event inbox refresh through the app's own refresh route
  (2026-10-12 19:27 UTC): one request each to the Federal Reserve, EIA and WTO feeds (three
  in all; the BLS feeds were not requested), each answered 200 and kept with its retrieval
  record. The Federal Reserve and WTO responses were byte for byte the ones retrieved on
  2026-10-08, so all 25 of their entries were reused; EIA listed one new entry beside its 14
  earlier ones. That entry's feed timestamp gives no year, so no date was taken from it.
  Nothing was triaged or analyzed.

Their records are private local data, not part of the repository. They show that each
path ran once, not model quality or that live sources will keep working. There is no
validated prospective track record yet.

## Run

Requirements:

- Python 3.12 or newer for the core and the server.
- Node 22.6 or newer for the frontend unit tests: `npm test` runs TypeScript through
  Node's `--experimental-strip-types`, which Node added in 22.6.
- Google Chrome for the browser checks; set `SECOND_ORDER_CHROME` if it is not in a
  standard place.

These steps were last checked on 2026-11-08 on Windows 11 with Python 3.12.8 and Node 24.14.1,
in a new worktree: the install into a fresh virtual environment, `demo` and `prepare` from it,
the unit tests (2,433 run, 45 skipped; the two named below passed once the files had LF endings),
`npm ci`, `npm test` (675 tests) and `npm run build`.
`accounts add-admin` and `serve` were not part of that check. Older versions were not tested.
The CI file names Python 3.12 and Node 22, but it was not run for this checkpoint.

On Windows, check the repository out with LF line endings, for example
`git clone -c core.autocrlf=input <repository>`. With `core.autocrlf=true` the files arrive with
CRLF, and two tests that compare committed files byte for byte
(`test_company_research.CommittedPackage` and `test_metals_api.Committed`) fail although
nothing changed.

`frontend/package-lock.json` pins the client's dependencies. `requirements.txt` pins only
`pandas_market_calendars` (5.4.0): its version is part of each market snapshot's recorded
calendar identity, and so of the committed test fixtures. It gives the other packages as
version ranges, so a later install can resolve to different versions of them.

First run, from the repository root (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests
python -m second_order demo
cd frontend; npm ci; npm test; npm run build; cd ..
python -m second_order prepare
python -m second_order accounts add-admin --username operator
python -m second_order serve
```

`prepare` is the one explicit evaluation step: it scores the committed fictional showcase
fixtures into `data/prepared/`. `accounts add-admin` creates the accounts store
(`data/accounts/accounts.db`) and the first administrator; it asks for the password at a
prompt and never reads one from a file, an argument or the environment. A store made before
self-registration or before the usage limits (an accounts-1 or accounts-2 store) is upgraded
once with `python -m second_order accounts upgrade`, which keeps every account and record;
`serve` refuses an unupgraded store and says so. `serve` listens on
http://127.0.0.1:8000, accepts only local addresses, needs that store (it refuses to start
without it and never creates it), asks everyone to sign in, and starts with paid drafts,
paid triage, market retrieval and publication import off. It creates, prepares, refreshes and fetches nothing on
its own.

The browser checks start their own servers in temporary folders, using `python` from
`PATH`; set `SECOND_ORDER_PYTHON` to the virtual environment's interpreter if another
`python` comes first.

To start again later: activate the environment, run `python -m second_order serve`, and
rebuild the client (`cd frontend; npm run build`) after the client changes. Each opt-in
is a server flag:

- `--enable-paid-drafts` and `--enable-paid-triage` need `SECOND_ORDER_ANTHROPIC_API_KEY`
  and send only approved requests;
- `--enable-market-retrieval` allows one approved, keyless download of the Board's H.15
  release package per previewed plan;
- `--enable-publication-import` lets a user's explicit import preview request one
  allowlisted official publication page (keyless, no redirects or retries), counted against
  the usage limits' daily publication fetches. Without it nothing is requested and users
  paste the text instead.
- `--enable-paid-briefs` needs `SECOND_ORDER_ANTHROPIC_API_KEY` and lets the News desk send
  one explicitly approved model draft of a shared brief per previewed request. Without it
  briefs are written by the editors or compiled from the reports' own words at $0.

`python -m second_order market-packages validate` validates kept release packages
locally and fetches nothing (see **Market context for selected events**).

`npm run build` writes two builds: the Admin build (every operator page and the Admin
screens) to `frontend/dist/` and the user Client build to `frontend/dist-client/`; the server
gives each role only its own build (`--static` and `--client-static` name other folders,
`--accounts` another store). See **Accounts, credits and daily limits**.

## Accounts, credits and daily limits

The server knows two roles. An **administrator** signs in to every existing operator page,
unchanged, plus the Admin screens at `/admin`: Users (accounts, balances, daily limits,
grants and corrections), Credits & holds (the ledger and the attempts to resolve), Actions
(every research request and attempt with its account, model, Effort, measured timing,
reported usage, planning estimate and usage-derived cost), Policy & settings and Usage & limits
(the usage limits, today's counts per account and the server's fetch and refresh budgets). A **user**
signs in to the Client: their own sources, evidence-first research analyses, quotes, results
and reviews, through `/api/user/*` only. The API is fixed in
[docs/admin-user-contract.md](admin-user-contract.md) (user-api-0.3, admin-api-0.2),
[docs/onboarding-contract.md](onboarding-contract.md) (onboarding-api-0.1, the public pages),
[docs/account-binding-contract.md](account-binding-contract.md) and
[docs/news-usage-contract.md](news-usage-contract.md) (user-api-0.4 and admin-api-0.3: current
official news by interests from the cached Event Inbox, a deliberate counted search, explicit
publication import, and the administrator's usage limits). Every user and administrator
write names the account its page was opened for (`X-Second-Order-Account`); a page left open after
another sign-in in the same browser is refused before anything is read or written, never acted on
as the account now signed in.
A source's text may have 50,000 characters in any script, and its headline 1,500. UTF-8 takes
one to four bytes for a character, so the server reads a source form of up to 270,000 bytes;
the operator's Tracker form keeps 120,000.

- Visitors: signed out, `/` is the landing page, `/register` the registration and `/credits`
  the credit terms; any other address asks for sign-in and then opens it, so research bookmarks
  keep working. A registration is an ordinary user account that cannot sign in until an
  administrator approves it on Registrations (`/admin/registrations`), once, with a reason.
  Approval only activates it: credits and a daily limit stay separate actions on Users, and the
  store refuses them (and any quote or attempt) before approval. Users points out the
  registrations waiting for a decision and the active accounts with nothing allocated yet;
  Registrations names the administrator behind each decision and links an approved account
  with nothing allocated to its panel on Users (`/admin?manage=<username>`), where the initial
  allocation can fill the two forms. Pointing out and opening a panel change nothing. Signing
  in with the right password of a waiting or rejected registration shows its own status,
  nothing more. There is no e-mail, payment or password reset.
- Credits are points: one credit is one point of application usage on this server, with no
  money value. `GET /api/public/credit-terms` (and the `/credits` pages) show the active policy
  in points, Effort and source size, with three synthetic examples quoted by the same formula
  as a real quote, or say that no terms are set. Size matters only under a policy with size
  rates (credits per 1,000 input or output tokens): then size is the saved request's UTF-8
  bytes, so a Hebrew or emoji source needs more points than an English one of the same length.
  Under the selected flat pilot terms (size rates 0) every accepted source, of any length or
  language, is quoted the same points at a given Effort; the source limits still apply. The Policy
  screen previews a draft's example quotes without recording anything; publishing a version is
  separate.
- The operator's selected pilot terms are presets, never applied by the server. On Policy &
  settings, "Fill the draft with these terms" sets flat points by Effort for any accepted
  source, whatever its length or language: Low 10, Medium 15, High 20, Extra High 25,
  Maximum 30. The per-request planning limit and quote validity stay the administrator's
  (kept from the active version, else empty), and publishing is the separate action. On Users,
  an approved account with nothing allocated can have its two forms filled with the selected
  initial allocation, 100 credits once and 3 analyses a day; the grant and the limit are still
  submitted one at a time, each with a reason. Startup, registration and approval apply
  nothing, and nothing refills credits.
- Sessions are server-side; the cookie is HttpOnly and SameSite=Strict, and a session ends
  at sign-out, when its account is deactivated, or after 12 hours. The local Host,
  same-origin and action-header checks stay in place for every route.
- Every existing record (captures, requests, attempts, responses, reviews) stays the
  administrator's, and every existing account keeps its identity and status. An administrator may assign one capture to one user, once, with a reason.
- Nothing has a built-in number. Until an administrator publishes usage limits on Usage &
  limits (each typed: daily searches, imports, new sources and prepared analyses per account,
  what an account may hold, protective request limits, and the server's daily publication
  fetches, feed refreshes and the wait between refreshes), users cannot read the news, search,
  import, add sources or prepare analyses, and the Event Inbox refresh is refused. Until an
  administrator also publishes a credit policy (which model, which Effort levels, whole-number
  credit rates, the largest planning estimate per request, how long a quote stays valid),
  grants credits and sets a user's daily limit, users cannot run analyses. Usage counts are
  per quota day, reset at local midnight, and count nothing for a refusal; they are this
  server's own counts, not billing.
- Effort is chosen before an analysis is prepared; each level is its own immutable request.
  The levels offered are those the policy enables among the ones the model accepts (low,
  medium, high, xhigh, max for claude-sonnet-5-5, checked against the provider's
  documentation without a request).
- A run needs the user's explicit approval of a quote. It reserves the credits, the day's
  slot (days follow the quota time zone, initially Asia/Jerusalem, which is fixed once the
  first run is counted) and the request's single attempt in one transaction, then sends the
  exact saved bytes once, only on a server started with `--enable-paid-drafts`. A recorded
  response is charged its quote; a run that provably sent nothing is returned; anything
  uncertain stays held until an administrator charges part or all of it or returns it.
  Nothing is refunded or retried automatically.
- While a worker runs an attempt it holds the attempt's execution lock, so no administrator
  can resolve it until that worker has stopped, however long it takes; a stopped or
  restarted server releases the lock. An attempt's age alone never authorizes a refund.
- These are this application's controls, not a verified billing ceiling. Usage-derived costs
  are local calculations at published rates; the provider's Console is authoritative.

Browser checks (synthetic accounts and a fake provider; nothing leaves the machine): the
Admin screens (including registrations, decided once each, and the policy preview), and the joint check of the built Admin and Client against the real server
(sign-in and expiry, the whole analysis flow, refusals, lost replies, replays, two users at
the daily and DST boundaries, a restart, held and killed workers, and every kind of
reconciliation). The joint check drives a test-only clock and holds runs at set points
through controls that exist only in the test launcher, on their own loopback port.

The connected entry gate is the joint check followed by the public journey. The journey
runs against the real server, which starts with synthetic accounts, no policy and nothing
allocated: a visitor sees that no terms are set; the administrator publishes the selected
pilot preset; a registration is approved and given the initial allocation as two actions;
then one analysis at High is quoted 20, run once on the fake, reviewed and exported. The
public pages' and the Client's own checks run against mocks: they prove the pages, not the
server.

```powershell
cd frontend; npm run build; npm run test:browser:admin; npm run test:browser:entry-gate; cd ..
cd frontend; npm run test:browser:public-entry; npm run test:browser:client-flow; npm run test:browser:client-recovery; cd ..
```

## News: stories, shared briefs and Go deeper

News is a signed-in user's home ([docs/news-stories-contract.md](news-stories-contract.md),
user-api-0.5 and admin-api-0.4). `/` and `/news` open **Hot now**; Latest, Topics and Your
interests are the other views, and the wordmark leads back to News. A story is one
development, covered by one or more reports from the feeds; clicking a headline opens the
story's own page, never the publisher's. There the story's **shared brief**, prepared in advance
by the editors and the same for every user, keeps what was reported (each fact citing its
report) apart from why it may matter (possibilities, never causes, predictions or advice),
names sectors, companies or themes where the reports support them, and says what is uncertain
or missing; its provenance names the method, version, times and the material it rests on. The
**Sources** section lists every report with its publisher and its own link, and says how
coverage was counted: reports by one publisher, or several carrying one wire text, count once,
and a company's press release is labelled as the company's statement. Related developments
and the ongoing topic, with its timeline, are linked. Reading any of this contacts no
publisher, calls no model and uses no credits.

**Go deeper** shows exactly what material a deeper analysis would use and what it leaves out,
the source text it becomes and an Effort; one explicit Prepare saves that text as the user's
own source and prepares its analysis (one new source and one preparation of the day's
allowance), and the analysis page then shows the credit quote. Nothing runs until the user
approves it there, under every existing credit, limit, ownership and single-attempt rule. The
shared brief is never changed by it, and another account never sees it. The analysis may quote
only the publishers' own words in that source (each headline, feed excerpt and publication
text): Go deeper records where they are, and a reply that quotes Second Order's framing,
labels or notes, or runs from one passage into the next, is refused as a whole.

Sources (news-registry-0.2, read 2026-10-25 from each publisher's own pages): only official
releases whose terms allow reuse may be summarised or analysed. Those are the five official
feeds of the Event Inbox (public domain, or WTO's reuse with its credit) and four official
publishers connected for the news: the White House's news feed (fact sheets, presidential
actions and statements; U.S. government work), USTR's press releases (U.S. government work),
the European Commission's press corner (CC BY 4.0) and the ECB's press releases and speeches
(free use with the ECB cited; its feed gives headlines only). TechCrunch is connected for
display only (headline, link and the feed's excerpt, unmodified and credited) and PR
Newswire's general business releases for headlines and links only, labelled as company
statements; neither may be summarised or sent for analysis under its terms. CNBC, Bloomberg,
Reuters, AP, Investing.com, the Financial Times and FreightWaves need an agreement, the
Guardian credentials and a commercial licence, Yahoo Finance's feeds are not connected, and
the SEC, BEA and the Bank of England are recorded with what they would need; the News desk
lists each. A story whose reports' publishers allow no summary says so instead of showing
one.

Newsrooms (news-registry-0.5, read 2026-10-26; docs/news-newsroom-sources-2026-10-26.md (private; not in the public repository)):
Voice of America (its own text is public domain; wire copy is skipped before it is kept) and
Global Voices (CC BY 3.0, each report credited to its author; republished partner articles
skipped) may be summarised and analysed; Inter Press Service is connected for headlines and
links only. Of the 56 publishers examined that day, none of the commercial financial
newsrooms, broadcasters or specialist market publishers allows this service to use its feed
without an agreement (docs/news-source-access.md); tests/test_news_newsroom_sources.py covers
the rules on SYNTHETIC feeds.

Economic explanations (econ-explanation-0.3; docs/news-economics-2026-10-26.md (private; not in the public repository),
docs/news-economics-review-2026-10-26.md (private; not in the public repository) and docs/news-economics-coverage-2026-10-26.md (private; not in the public repository)): a shared
brief may carry an explanation of what changed, why it matters, the channels and who may be
affected, conditional second-order effects, alternatives and what to watch, prepared by the
same batches (`news batch preview --backfill`, `news batch import --check`). Figures are quoted
from the evidence with units, periods, nominal or real basis, seasonal adjustment and vintage;
derived figures are computed in code (econ_calc), keeping each figure's quoted sign, its bound
("more than 95%") and its statistic (mean, median), and setting stocks against flows as periods
of that flow; each channel says what supports it (a sourced framework note bound to the kinds of
development it applies to, the story's own sources, or a bounded inference with its
assumptions); an explanation keeps the exact notes it used, so a later change to
econ_framework.json never rewrites it but marks it outdated (earlier frameworks are archived
by hash in second_order/econ_framework_archive/); extra evidence comes only from explicit
context bundles (`news context build`, `--methodology` for a series' notes from
econ_methodology.json, `--earlier-release` for the previous release of the same feed and title,
`news context suggest` to see the options), whose items each say their role, why they are
relevant and when they were published against the story (later context is labelled and never
what happened); newer context makes an explanation outdated until it is prepared again, and a
page says precisely what was read. `news baseline record|progress|list` reports a piece of work
on the stories listed at a cutoff, with later stories apart. Its checks catch defined mistakes in
words and numbers; they do not show that an explanation is right (docs/economic-review-rubric.md).

An update run (`news update plan|start|refresh|texts|relevance|context|briefs|report`, or the
Update run panel on /admin/news; docs/news-update-workflow-2026-10-27.md (private; not in the public repository)) takes fresh material
through those steps for the run's stories only. It records a cutoff and requests each connected
feed once, telling newly published reports from older ones discovered late and from those with
no stated time. It previews the existing batches (a model batch saves its exact requests and
planning estimate and sends nothing until its own approval) and reports what completed, what
needs an editor or an approval, and what failed. A story page lists the brief's earlier published
versions and what the current one changed. `news drafting preview STORY` records one story's exact
model-draft request and `news drafting approve DRAFT …` sends it once, repeating its SHA-256 and
estimate (the key from the environment; docs/news-live-trial-proposal-2026-10-27.md (private; not in the public repository)).

A report's time is the one its feed states; a feed that states only a date (WTO), or a time
whose zone contradicts its date (EIA's "EST" in October), is shown by that date and ranked no
later than its end, so a release first retrieved days later is not taken for new. Hot now
leaves to Latest a story covered only by a company's own statement, and one that names none
of the news's subjects (a ceremonial proclamation, say), unless the editors mark it major.

The operator curates on the **News desk** (`/admin/news`): refresh the publisher feeds (each
connected feed once, under the usage limits' refresh cooldown and daily budget), group new
reports (only a repeated headline joins a story by itself; pairs that share distinctive words
are suggested, never merged), merge, detach and retitle stories, create topics and link their
developments, mark a story or topic as major for at most seven days, and prepare briefs: a $0
draft compiled from the reports' own words, completed and saved as a version, checked by a
fixed guard against advice and causal claims, and published or withdrawn as its own action. A
paid model draft is optional: `serve --enable-paid-briefs` (with the key) shows the exact
request's planning estimate and sends it once only after an explicit approval. Every decision
is an append-only row of `data/newsroom/newsroom.db` with who, when and why.

```powershell
python -m second_order news status            # each source's freshness and the newsroom's counts (read-only)
python -m second_order news refresh           # each connected publisher feed once (explicit; keyless and free)
python -m second_order news refresh --official  # the same, and the Event Inbox's official feeds once each
python -m second_order news group             # put new reports into stories (local; requests nothing)
python -m second_order news stories --view hot  # story IDs, material and brief state (read-only)
python -m second_order news draft STORY_ID    # the $0 draft from a story's material (read-only)
python -m second_order news curate --plan FILE --check  # check a curation plan and its briefs; writes nothing
python -m second_order news curate --plan FILE  # apply it as the local operator (idempotent, recorded)
python -m second_order news backup --to FILE  # copy the newsroom store; restore by copying it back, server stopped
```

A curation plan (news-curation-plan-0.1, see the contract) writes the desk's actions (merges,
headlines, topics and their links, briefs and their publication, priorities) into one file, so
the operator at the machine can prepare and apply them; each is recorded like the desk's own.

**Preparing briefs for the important stories** (contract section 10). The operator first
retrieves the full text of official publications where their terms and page layout allow it
(the White House, USTR, EIA, the ECB, the WTO and the Fed's press releases), so briefs and
deeper analyses rest on the publication rather than its feed excerpt; then previews a bounded
batch of Hot now's stories that need a brief; prepares it with the AI model in this application
(a paid request per story, sent once only after the batch's total estimate is approved; needs
`serve --enable-paid-briefs` or the command line with the key) or with an AI assistant or editor
outside it (a packet to write from, and an import); and publishes the versions the guard allows as
its own step. A brief says who prepared it (an editor, the AI model, an AI assistant) and whether
an editor read it, which only an explicit review records; a story whose material is too thin says
so instead of carrying a thin brief.

```powershell
python -m second_order news upgrade                 # once: newsroom-1 -> newsroom-2 (after news backup)
python -m second_order news texts --hot --check     # which official texts would be requested or reused
python -m second_order news texts --hot             # retrieve them (explicit; keyless and free; once each)
python -m second_order news coverage                # how many important stories have a current brief, and why not
python -m second_order news batch preview --method model --limit 10     # paid: exact requests and the total estimate
python -m second_order news batch approve BATCH --estimated-max-usd-total X --approve-paid-requests
python -m second_order news batch preview --method assisted --limit 10  # or: written with an assistant or an editor
python -m second_order news batch packet BATCH > packet.json
python -m second_order news batch import BATCH --drafts drafts.json --assistant-tool NAME [--assistant-model NAME]
python -m second_order news batch publish BATCH --reason "..." [--reviewed]
```

The next financial source needs a licence: the contract names Dow Jones Factiva's GenAI-licensed
content and what its agreement must grant; Reuters and AP publish no developer terms for AI
summaries of current stories.

**Economic relevance** (contract section 11). The news lists a story only when an assessment of
what its sources report (by the AI model in this application, or an AI assistant outside it,
checked against the material) or an editor establishes that it is an economic development;
current headlines still awaiting that are listed apart, and stories assessed as outside the scope
keep their pages but leave the lists. Publishers whose terms forbid use by a model are never sent;
only an editor judges their headlines.

```powershell
python -m second_order news relevance queue                          # every current story's relevance (read-only)
python -m second_order news relevance preview --method model         # paid: exact requests and the total estimate
python -m second_order news relevance approve RBATCH --estimated-max-usd-total X --approve-paid-requests
python -m second_order news relevance preview --method assisted      # or: annotated with an AI assistant
python -m second_order news relevance packet RBATCH > packet.json
python -m second_order news relevance import RBATCH --annotations FILE --assistant-tool NAME [--assistant-model NAME]
python -m second_order news relevance review STORY --verdict outside_scope --reason "..."   # an editor's judgement
python -m second_order news relevance eval baseline --set dev        # the keyword rule on the labelled cases
python -m second_order news relevance eval baseline --set sample     # the public fictional sample (not a holdout)
python -m second_order news relevance eval measure --set dev --annotations FILE --annotator NAME --record
```

Coverage by other publishers and different headlines about one development (docs/news-stories-contract.md, section 12):

```bash
python -m second_order news match suggestions              # pairs of current stories that may be one development (read-only)
python -m second_order news match decide A B --decision same|related|different --reason "..." [--topic-title "..."]
python -m second_order news index lookup --story STORY     # one request to the GDELT index (explicit; keyless and free)
python -m second_order news index lookup --story STORY --words wind turbines imports   # the operator's query words
python -m second_order news index lookups STORY            # what was recorded, and which articles the rule accepts
python -m second_order news index attach STORY LOOKUP --reason "..."   # add the accepted articles as headline-only reports
python -m second_order news index status                   # the cooldown after GDELT's 429s and each story's kept coverage (read-only)
```

After a 429 the index is not asked again before a recorded cooldown ends (15 minutes after a first 429, doubled for
each further one in a row, or longer if GDELT's Retry-After asks; at most 24 hours); a lookup asked for meanwhile is
refused before any request. Articles already attached are kept whatever later lookups answer.

SEC press releases and the ONS release calendar are requested only when the operator sets
`SECOND_ORDER_FEED_CONTACT` (an e-mail address or URL their terms require automated clients to declare). Turning on Go
deeper for real readers needs decisions only the operator can take: see docs/news-reader-activation.md (private; not in the public repository).

The browser check `npm run test:browser:news-stories` walks the whole journey against the real
server (tests/news_desk_server.py) with SYNTHETIC accounts and SYNTHETIC publishers whose
reports are dated relative to the start, curated through the server's own actions; it is part
of the local live gate. The same launcher serves a local demo over copies of a real data
folder's caches (`--records data`) and, with `--newsroom data/newsroom/newsroom.db`, a copy of
the real newsroom's stories, topics and briefs, every SYNTHETIC story marked as such on every
page; it never writes to the real data folder.

## Offline Dossier

Building the client needs Node and npm (see **Run**); serving needs only Python:

```powershell
python -m second_order prepare
cd frontend; npm ci; npm run build; cd ..
python -m second_order serve
```

Open http://127.0.0.1:8000 for the Tracker. It separates prospective cases from
retrospective replays and shows each case's usage, publication date and recorded
evaluation status: "Not yet evaluated" when no evaluation is stored, otherwise the
recorded result, which can itself be "Pending" when the scored window was incomplete.
Research intake is shown as closed, and no support or contradiction rates are
computed from showcase cases. Each row links to its Dossier.

`prepare` is the explicit evaluation step: it scores the two showcase replays on
the committed fictional demonstration series and writes read-only views to `data/prepared/`.
The Dossier and Method routes are read-only, and every GET stays inert: no read
evaluates, prepares, fetches or calls a provider.

Writes are explicit local actions from this server's own page, for example capturing an
event, recording a mock response or saving a review. Only these contact the network, and
each only when you choose it:

- **Refresh events** requests the five fixed publisher feeds.
- A paid draft or a paid headline-triage request sends one approved Claude request,
  only on a server started with `--enable-paid-drafts` or `--enable-paid-triage`.
- Market context sends one approved keyless download of the Board's H.15 release
  package, only on a server started with `--enable-market-retrieval`.

None of these evaluates or freezes anything, so a missing preparation is reported, not
repaired. The Hypotheses page's actions (upgrading the store, importing a kept package,
previewing, approving one freeze) are local and contact no network; only an approved
freeze writes a hypothesis, and nothing evaluates or prepares a Dossier on its own (see
**Freezing from the interface**).
The tests and the committed content need no credentials, network connection or existing
database; fonts are bundled. For client development, run `serve` and `npm run dev` (port
5173 proxies `/api`).

Every HTTP route checks the Host, including read-only API routes and client files. The
accepted names are `127.0.0.1`, `localhost` and `[::1]`, with or without a valid port;
this does not change the server's listening address. A foreign, missing or malformed
Host is refused before records are read. Reads need no Origin or action header. Writes
still require the server's own Origin and their custom JSON-action header.

To include frozen cases from a store, prepare with `--db`. The store is opened
read-only. Cases without a stored evaluation appear as "Not yet evaluated". A case
with several stored evaluations needs `--evaluation <hypothesis-id>=<evaluation-id>`:

```powershell
python -m second_order prepare --db second-order.db
```

A stored case shows its recorded evaluation exactly as stored, or "Not yet evaluated"
with no chart or ranking. Its FRED observations are drawn and labelled by New York
observation date, and a Data provenance card lists the baseline and outcome snapshots,
the recorded rules, the measurement convention and FRED's attribution.

Each Dossier shows the frozen hypothesis map, the selected leg's recorded result,
the observation series with publication, scoring anchor and horizon end marked,
and the exact reference distribution the scorer ranked against. The browser only
draws prepared values; it does not recompute scores.

### Case library

The Tracker's **Case library** section, and the **Library** link in the top bar, open
twenty-seven close readings: twenty-four official US releases and three WTO news items. The
selection rule for the releases is consecutive releases, not interest or later market
outcomes.

Twelve macro cases from the first half of 2025, four in each of three topics:

- Monetary policy: the first four scheduled FOMC statements of 2025, January 29, March
  19, May 7 and June 18 (each at 2:00 p.m.; EST in January, EDT afterwards).
- Employment: the Employment Situation for March, April, May and June 2025, released
  April 4, May 2, June 6 and July 3 (8:30 a.m. ET).
- Inflation: the CPI for March, April, May and June 2025, released April 10, May 13,
  June 11 and July 15 (8:30 a.m. ET).

Twelve sector cases from 2026: in each of four source families, the last three
consecutive releases or announcements published on or before 30 September 2026:

- EIA Today in Energy (topic Energy analysis): the last three articles in EIA's own
  archive, whatever their subject, published September 22, 25 and 30.
- BIS press releases (topic Export controls): the last three press releases with their
  own text on bis.gov that name semiconductors, semiconductor manufacturing equipment,
  chips or advanced computing items, published February 12, June 17 and July 10.
  Listings that only link an enforcement order or another agency's release have no such
  text and are not included.
- Federal Reserve G.17, Industrial Production and Capacity Utilization (topic Industrial
  production): the releases of July 17, August 18 and September 18 (reference months June,
  July and August 2026).
- Federal Reserve H.8, Assets and Liabilities of Commercial Banks in the United States
  (topic Bank balance sheets): the weekly releases of September 11, 18 and 25.

Each sector case is listed under one or more of five sectors: Energy, Technology &
semiconductors, Manufacturing & automotive, Banking & credit, and Mining & materials. A
case is listed under a sector when at least one of its key facts and one of its channels
concern that sector. Membership is additive: the three G.17 releases sit under three
sectors each (all under Manufacturing & automotive and Mining & materials, the July and
September releases also under Energy and the August release under Technology &
semiconductors), the BIS penalty on Bosch under Technology & semiconductors and
Manufacturing & automotive, and EIA's article on electric vehicles' electricity use under
Energy and Manufacturing & automotive; each is stored and listed once. The sector counts
are 5, 4, 5, 3 and 3, more than the twelve sector cases. Each sector states what it covers
and what it does not (Banking & credit, for example, is the aggregate balance sheet of all
commercial banks, not individual banks or loan quality). Sectors are separate from a
case's topic and from the Event inbox's topics.

Mining & materials (added 14 October 2026) adds no release and no case: it lists the same
three G.17 releases, selected under Manufacturing & automotive, so the library still holds
twenty-seven cases. It uses the release's own categories: mining is all industries in NAICS
sector 21, as the release defines it, and materials is the release's market group of that
name, which the pages read do not define further. It covers US reported output and
capacity utilization only; the library holds no commodity or metal prices, mining
companies' results, security returns or market reactions for it. The three G.17 case files
changed by addition only: the new sector at the end of their sector lists, and appended key
facts, a channel (August and September; July already had one), a competing explanation, an
assumption and a missing-information item, all taken from release pages each case already
lists as read. Every added figure was checked against privately retained copies of those
pages (acquisition `g17-release-tables-01`). Later revisions are given as revisions, with
their release dates, never written over the figures a release first published, and
removing the additions gives back the earlier content exactly. A library sector does not
widen live ingestion or what the research analysis measures.

None of the sector sources states a publication time with a time zone: the G.17 schedule
gives 9:15 a.m. and the H.8 page "generally at 4:15 p.m.", both without a zone, and the
EIA and BIS pages give a date. These cases therefore record the publication date only,
and their pages say "date only: the source states no time". On a shared date, a case with
a stated time is listed before date-only ones.

This is an editorial collection, not a preregistered research cohort. The Tracker shows
the latest case in each topic and links to the full library, to each topic and to each
sector. At `/library`, a search box matches case titles, summaries, topics and publishers
(it does not search the full text of each case); topic controls and sector controls each
narrow the list, and all three combine. Every control shows how many cases it would show
with the other choices kept. The page shows how many cases match, states a chosen
sector's coverage and selection rule, explains an empty result (with each filter's count
on its own) and offers a reset; an address naming a sector the library does not have says
so and shows every case. Cases are always ordered by publication date, oldest first. The
search, topic and sector live in the address (`/library?q=…&category=…&sector=…`), so a
reload, a shared link or Back from a case restores them, and the controls work from the
keyboard.

Each case at `/library/<case>` gives the release's facts as first published, with the
basis of each figure (seasonal adjustment, monthly or yearly change, revisions); possible
channels (to Treasury yields for a macro case, within its sectors for a sector case), each
separating what the release says from a conditional interpretation; competing explanations; assumptions, missing information and what would
weaken the reading; an editorial critique; source notes, including later revisions and
the official links; and its authorship. Cases can be opened, reloaded and moved between
(previous and next in publication order, Back) entirely in the app. Where a release
repeats earlier language or figures, the case says what changed and what did not. The
April 2025 jobs release was reissued by BLS on June 3, 2025, and its case says so. A
sector case shows its sectors as links back to the library.

These are retrospective, AI-assisted editorial illustrations, written by Claude after
publication from the archived official releases. Nobody has reviewed them; their
critique is part of the prepared text and is separate from saved human reviews. No case
uses a contemporaneous expectations benchmark, so none says whether a release was a
surprise, and no case measures a market reaction or shows a magnitude or outcome label.
Every macro case has a descriptive Market context section with daily Treasury yields (see
**Market context** below), and none of it is a measured reaction. The sector cases show no
market series and say so: Treasury yields do not measure activity in those sectors, and
the library holds no sector price or return series. They are not hypotheses:
they have no map, legs, freeze, evaluation or score and never enter research summaries.

The content is committed in `content/case-library/`: `collection.json` and one JSON file
per case. `second_order/case_library.py` checks every file strictly and refuses the whole
library on any problem. A case must name an official source, list the sources read, carry
the fixed AI-assisted, not-reviewed and research-excluded labels, and use no expectations
benchmark. The twelve macro case files are unchanged at version `case-library-0.1`, where
the source needs a publication time with an explicit UTC offset. Version
`case-library-0.2` adds the collection's declared sectors and each sector case's sector
list (non-empty, distinct and declared) and lets a source state its date only; only a case
with a publication time can declare market context. The collection must list its cases in
publication order. Version `case-library-0.3` (the three WTO entries, topic International
trade) adds www.wto.org as a source, an entry kind (a forecast, or meeting proceedings that
list no market channels rather than invent one), the date basis (the pages state no
publication date, so the date is the one WTO's own news feed lists, never presented as a
stated time; meeting days are kept apart) and the record of the privately retained copy each
was written from (approval `wto-trade-sources-01`, SHA-256, size, retrieval time, declared
charset); the copies are never served, and each figure was checked against them in a private
acceptance record. The WTO entries are: the October 2026 trade forecast update (merchandise
and services trade volume projections for 2026-2027 against the March forecast, attributed
to WTO economists), the Committee on Trade and Environment meeting of 28-29 September 2026
and the General Council meeting of 5-6 October 2026 (interim arrangements for the Agreement
on Electronic Commerce: support and concerns, no decision reported). Adding them left the
twenty-four earlier case files byte-identical; the later Mining & materials additions (above)
changed only the three G.17 files. `GET /api/case-library` and `GET /api/case-library/<case>` only read
those files, with no prepared files, runtime records, keys or network; searching and
filtering happen in the page. A browser check covers discovery, all twenty-seven cases
(with the source check on the two enriched BIS cases),
search, topic and sector filters, their counts, cases under two or three sectors, the empty states
and reset, an unknown sector, the address across a reload and Back, keyboard use,
date-only publication dates, a direct reload, the source links, a phone-width layout and
the absence of external requests:

```powershell
cd frontend; npm run build; npm run test:browser:library; cd ..
```

Two BIS cases, `bis-2026-07-10` (the UAE easing) and `bis-2026-02-12` (the Applied Materials
penalty), carry a source check and reading aid (`case-enrichment-0.1`) kept beside the case in
`content/case-library/enrichments/`, never in it. Each file is bound to the SHA-256 of the
unchanged case file: if the case changes, the check is not shown and the page says why
(`.gitattributes` keeps the case files at LF on every checkout, `text eol=lf`, so a Windows
clone with `core.autocrlf=true` reads the same bytes; the news-relevance sets, bound by their
bytes too, are kept at CRLF, `text eol=crlf`, the bytes their recorded measurement read). It
was written only from privately retained copies of the two press releases and of BIS's News &
Updates page (approval `bis-semis-sources-01`) and shows where the announcement sits in the
semiconductor chain (always labelled as the curator's reading); its instrument, scope, timing
and conditions, each statement marked as stated, not stated, or left to a document the release
itself names and that was not read; those unread documents; the observations that would be
needed to examine each of the case's channels (none is held here); a check of the case's
title, summary, key facts and channel statements against the retained source; and a limited
comparison with the October 2022 historical case. Two claims differ from the retained sources
and are flagged where they appear: the UAE case says BIS conditions the new status on the
UAE's commitment to preventing diversion, where the release gives that commitment as a reason
for the status; and the Applied Materials case dates BIS's January 2026 licensing revision
January 14, where BIS's listing gives January 13. The case text is unchanged; a correction
would be a separate, versioned change. `GET /api/case-library/<case>/enrichment` only reads;
the retained copies are checked against their records when present and never served. The
other twenty-five cases have none. These are historical announcements, not current rules or
legal guidance.

### Market context

Every macro case also has a **Market context** section, listed on the page after the
channels; the sector cases have none (see **Case library** above). It shows the Federal Reserve Board's daily 2-year and 10-year Treasury
constant-maturity yields from the H.15 release (series `RIFLGFCY02_N.B` and
`RIFLGFCY10_N.B`: percent per year, business-day frequency; the Board gives the U.S.
Treasury as their source) for every calendar date from 14 days before to 14 days after
the release's New York publication date. FRED republishes the same two series as DGS2
and DGS10, per the Board's DDP-FRED crosswalk, but no value here came from FRED. The
section has a two-line chart with a legend, a percent axis, a calendar-date axis and the
publication date marked, and a table of all 29 dates.

It is description only. No change over a horizon is computed, nothing is attributed to
the release or labelled as support or contradiction, and it is not a hypothesis, an
event study or a score. Each value has a date but no time of day, so the chart cannot
show whether a value came before or after the release; the marker shows the publication
date, not a moment in the series. The values are the Board's as published when they were
downloaded, not a historical vintage: the Data Download Program offers no earlier
vintages, and whether any value was revised is not known.

Dates are New York calendar dates and are never converted through the reader's time
zone. Every date is one of four things: an observed session; an expected session with
no value (`ND` in the source, or a missing row; marked on the chart, which breaks the
line there); a SIFMA holiday; or a weekend. Nothing is interpolated or carried forward.
In all twelve windows every expected session has both values. The only rows without a
value are SIFMA holidays, which the Board marks `ND`: Martin Luther King Jr. Day, Good
Friday, Memorial Day, Juneteenth and Independence Day 2025. Where windows overlap (18
pairs, 340 shared values), they agree exactly. The section also gives the provenance:

- the series' identifiers, description, units, frequency, rights, citations and FRED
  equivalents;
- the window rule, the request and receipt times, HTTP status, server date, the
  acquisition run and its method, any replies discarded before the kept one, and the
  calendar used;
- the source file's rows, range, size, SHA-256 and download address;
- the hashes of the prepared view, the run's acquisition record and manifest, and the
  index of runs.

The bundle is committed in `content/market-context/`, so a clean checkout serves it with
no private database or runtime record. It was downloaded in two separate acquisition
runs, both on October 7, 2026 (UTC), and each stays verifiable on its own:

| Run | Cases | Requested (UTC) | Files |
|---|---|---|---|
| 1 | The March 19 FOMC statement and the jobs and CPI reports of July 3 and 15 | 22:07:04–22:07:15 | `manifest.json`, `sources/acquisition.json` |
| 2 | The other nine cases | 22:48:24–22:50:20 | `manifest-2.json`, `sources/acquisition-2.json` |

`sources/` holds every Board download byte for byte (one per case, both series) and each
run's acquisition record. Each run's manifest binds its acquisition record and its
views to their hashes, and `index.json` lists the runs in order with each manifest's
SHA-256. Run 1's eight files are exactly as first prepared; adding run 2 changed none of
them. Run 2's acquisition record also lists the six first attempts that received an
empty reply and were discarded; run 1's method text describes its two. `.gitattributes`
marks the folder `-text`, so line-ending conversion never changes the hashed bytes.

The files were downloaded with curl, one keyless request per case window, from the
Data Download Program's direct-download address for a package of exactly the two
series. The source is the Board rather than FRED because FRED's terms of use prohibit
storing FRED content or incorporating it in a compilation, and using it in connection
with developing software or AI systems. The Board's website says its information is in
the public domain and may be copied and distributed without permission, with the Board
cited as the source; it excepts non-Board material marked as copyrighted or trademarked
and the Board's seals and logos, none of which are used, and nothing here implies the
Board's endorsement. The Board plans to remove the Program's build-your-package option
the week of November 9, 2026, so the recorded addresses may stop working; the retained
bytes remain the record.

Preparing the bundle is an explicit offline step from files already downloaded; the app
never downloads anything. `prepare` starts a bundle with run 1; `append` adds the next
run for declared cases the bundle does not hold yet, copying every existing file byte
for byte, verifying the whole result, and only then replacing the bundle:

`prepare` and `append` share a cross-process write lock from the initial read through
publication. A concurrent writer is refused, not queued or retried. The lock lives in
a persistent `.<bundle-name>.lock` sidecar outside the replaced folder (the default
`content/.market-context.lock` is git-ignored); do not delete it while writers may run.
The OS releases it if its owner exits. Reads never acquire this lock or create its file,
and an `append` refused for a missing or mistyped bundle path creates nothing. `append`
rechecks the live bundle before publication and refuses an external edit instead of
overwriting it; `prepare` without `--replace` likewise refuses, and leaves alone, a
destination that another process filled while it worked.

**Publication and interruptions.** Publication is two directory renames: the live
bundle moves aside into a folder beside it, the new folder moves into place, and the
moved-aside copy is removed. The moved-aside folder's name records its owner and its
time, and nothing is written into it:
`.market-context-previous-<UTC time to the microsecond>-<8 hex digits>-<bundle folder name>`,
for example `…-20261008T091500123456Z-3fa9c2d1-market-context`. The owner is matched
exactly, so `market-context` never claims a copy of `market-context-b`. Each outcome is
stated, never left as a traceback:

- if the bundle cannot be moved aside, nothing is published and it is unchanged;
- if the new folder cannot be moved into place, the original is moved back, and the
  error says so; if that also fails, the error names the preserved original and how
  to restore it;
- if the old copy cannot be removed afterwards, the publication stands: the command
  succeeds with a warning that names what is left.

The two renames are not crash-atomic. Between them the bundle path is briefly absent,
so a reader at that instant finds no market context. Ctrl-C is held until both renames,
or the restoration, have finished, and then takes effect. A hard kill, a power loss or
a crash between the renames cannot be held: the bundle path then stays missing while
the original stays intact in its moved-aside folder.

Recovery then keeps three things apart:

- **Ownership.** Only folders whose names record this bundle are its copies. Another
  bundle's folders are counted as unrelated; folders whose names record no owner (made
  by an earlier version) are listed as of unknown origin, never as this bundle's.
- **Order.** Its copies are listed by recorded time, newest first. The most recent one is
  named only when it alone has the latest time; copies recorded at the same time stay
  unordered.
- **Integrity.** Each copy's runs, cases and acquisition methods, and whether its files
  verify, are reported. Verification never chooses a copy: if the most recent one does
  not verify, it is still the one named, with a warning that it is not safe to restore
  as it is, and older copies are earlier states, not replacements.

Reads then say only that a publication may have been interrupted, naming no folder.
`check` prints the full report. While copies recorded as this bundle's exist, `append`
and `prepare` refuse with it. Other bundles' folders and folders of unknown owner never
block a new bundle or count as its predecessor. Nothing restores, deletes or overwrites
a folder for you. If you decide to restore one, rename it back to
`content/market-context`, then run `check`. Working copies (`.market-context-<letters>`)
and moved-aside folders under `content/` are git-ignored, so an interrupted operation
cannot ship them.

```powershell
python -m second_order.market_context urls --missing   # the exact Board downloads still needed; fetches nothing
python -m second_order.market_context append --staging <folder> --method "<how they were obtained>"
python -m second_order.market_context check            # verifies every declared case; reads only
```

The staging folder holds `<case>.csv` for each case and `acquisition.json`: a `tool`, one
record per kept download with exactly `case`, `file`, `url`, `requested_at` and
`received_at` (ISO times with offsets), `http_status`, `content_type`, `response_date`
(the HTTP Date header), `bytes` and `sha256`, and optionally `discarded`: the refused
replies, each with what was received and the `reason`. Preparation refuses the whole run
on:

- a file that is not recorded, or a record without its file;
- an address other than the case's expected one;
- a reply that is not a 200 `text/csv`, or times that disagree;
- bytes that do not match their record;
- a discarded reply that is incomplete or names another case or address;
- a header naming other series, units or multipliers;
- rows that do not cover the window;
- a case already in the bundle, or an existing bundle that does not verify.

`GET /api/case-library/<case>/market-context` verifies the whole chain on every read:

- the index, every manifest's hash, and that each case belongs to exactly one run;
- the run's acquisition record and the view's hashes;
- the source file's hash and size, and its download record;
- the series' identifiers, description, unit, multiplier and currency in the source's
  own header;
- the window, re-derived from the case's own publication time;
- every value and status, re-derived from the raw rows.

Any mismatch refuses the context. The API answers 404 for a case without context, 503
when no bundle is prepared, and 500 when the bundle does not verify. The page then
says why and shows no substitute data; the rest of the case reads as before.

The unit tests are in `tests/test_market_context.py`:

- Synthetic rows in the Board's format cover parsing, classification, preparation,
  appending a run, and every refusal.
- The committed bundle is checked separately: every served value against its raw source
  row with a separate minimal reader, the sessions against the real SIFMA calendar,
  run 1's pinned hashes, the separation of the runs, the overlapping windows, and that
  the collection's availability claim matches the verified contexts.

`frontend/tests/fixtures/market-context-*.json` are the twelve served views captured
from the bundle, and a backend test keeps them equal. A browser check runs in two
phases, and both check that the pages only read and request nothing outside the local
server:

- The committed bundle, all twelve macro cases: chart and table agreement, windows, holidays
  and weekends, provenance and runs, other browser time zones, keyboard access, a
  reload, a phone-width layout, and the files left unchanged.
- A clearly labelled synthetic bundle: missing sessions, a changed source, and no
  bundle at all.

```powershell
cd frontend; npm run build; npm run test:browser:context; cd ..
```

### Event inbox

The Tracker's **Event inbox** lists entries from five fixed feeds, each listed in its
publisher's own feed catalogue. Each source has a topic and says what kind of entries it
lists; only the BLS entries are formal statistical releases:

| Source | Topic | Kind | Feed | Format | Catalogue |
|---|---|---|---|---|---|
| Federal Reserve monetary-policy press releases | Monetary policy | Policy announcement | `https://www.federalreserve.gov/feeds/press_monetary.xml` | RSS 2.0 | <https://www.federalreserve.gov/feeds/feeds.htm> |
| BLS, The Employment Situation | Employment | Statistical release | `https://www.bls.gov/feed/empsit.rss` | Atom | <https://www.bls.gov/feed/> |
| BLS, Consumer Price Index | Inflation | Statistical release | `https://www.bls.gov/feed/cpi.rss` | Atom | <https://www.bls.gov/feed/> |
| EIA, Today in Energy | Energy | Analysis article | `https://www.eia.gov/rss/todayinenergy.xml` | RSS 2.0, ISO-8859-1 | <https://www.eia.gov/tools/rssfeeds/> |
| WTO, Latest news | International trade | News announcement | `https://www.wto.org/library/rss/latest_news_e.xml` | RSS 2.0 | <https://www.wto.org/english/res_e/webcas_e/rss_e.htm> |

The energy and trade sources were verified on 2026-10-08 before they were enabled. Their
publishers' documentation was read:

- **EIA.** The catalogue lists the feed on `www.eia.gov`. EIA's content is public domain
  (<https://www.eia.gov/about/copyrights_reuse.php>), credited as "Source: U.S. Energy
  Information Administration", without its logo.
- **WTO.** The catalogue lists the feed as "All WTO news" at an `http` address; the
  inbox uses the same path over `https` on the same host, which the server answers
  directly, with no redirect. The WTO encourages dissemination of its news credited as
  "WTO news", without its logo
  (<https://www.wto.org/english/info_e/copyrights_permissions_e.htm>).

The inbox shows each credit on its source's card and on each of its entries.

One bounded preflight request per feed was then made outside the app's data, with the
inbox's own client rules (no redirects, no environment proxy, the 1 MB cap, no retry). It
recorded the following; it is a one-time observation, not a guarantee that either feed
stays the same:

- **EIA.** A 200 `text/xml` reply of 9,129 bytes, declaring ISO-8859-1, with 14 items.
  The items had no GUID; every link was an `https` address on `www.eia.gov`. Every
  `pubDate` read 09:00:00 EST, including September and October dates, when US Eastern time
  is EDT. On the day of the most recent item, the file was last modified at 12:45 GMT,
  before the 14:00 GMT its stamp implies, so the time looks like a fixed label rather
  than a publication time.
- **WTO.** A 200 `text/xml` reply of 74,861 bytes in UTF-8, with 10 items. Each GUID was
  its `https` link on `www.wto.org`, and every item was stamped 00:00:00 GMT on its date.
  Each item also carries the full article in a `content` element, which the inbox never
  reads.
- **Parsing.** The inbox's parser read every preflight item (14 and 10, none skipped) and
  offered a time for none of them.

The simulated tests below prove only the code's handling of these shapes. Whether the
live feeds keep working is known only after a real refresh.

It is discovery, not analysis. **Refresh events** is the only action that contacts the
publishers. It requests each feed once, one after another, with no retry, and nothing
refreshes in the background. Loading or reloading the page, and choosing an entry, only
read the local cache. **Analyze this event** fills the Analyze an event form below it;
nothing is captured, sent, drafted, frozen or evaluated until you preview and approve
there, exactly as for an event typed in by hand. On Federal Reserve and BLS entries,
**Market context** opens daily Treasury yields around a date you confirm (see **Market
context for selected events**); energy and trade entries say that they are outside it.

Each entry shows the publisher's own title, topic, kind, publisher (with the credit its
terms ask for, where checked), official link and excerpt as plain text, never as HTML, with no model-written summary (Headline triage, below, adds
suggestions only in its own panel, after an approved response). It also shows the feed's timestamp
exactly as given, with the element it came from (RSS `pubDate`, Atom `published`, or
Atom `updated` when there is no `published`), and when its source was last retrieved. A
feed's timestamp is not a verified release time. The BLS feeds, for example, have stamped
some releases around 07:50 ET although they are published at 8:30 a.m. When the inbox first
retrieved an entry is shown as that, never as a publication time.

Each entry also says which texts it holds: the headline as supplied or shortened at 300
characters, and the feed's excerpt as supplied, shortened at 1,200 characters, absent, or only
repeating the headline. An excerpt is never presented as the article, and no article is
retrieved. A chip says what the local records show was done with the entry: **Not
processed** (a valid state), simulated or model triage, failed or uncertain triage, or how
many saved events recorded it as their origin (`GET /api/events/processing`, read-only).

Choosing an entry fills only the headline and the official link. The date, time, offset
and published text stay empty for you to supply:

- **Timestamp suggestion.** When the timestamp states a date, time and UTC offset
  unambiguously, the form offers it as a suggestion, as the feed states it (any fraction
  of a second is dropped, and the form says so). If you use it, you must confirm you
  checked it against the release before previewing.
- **Ambiguous or missing timestamps.** These give no suggestion and no UTC instant. The
  cases are:
  - a missing value, `-0000`, or a zone name RFC 822 does not define;
  - a weekday that contradicts the date;
  - a US zone name that contradicts the daylight-saving status of its date and time, such
    as EST in October. EST, EDT, CST, CDT, MDT, PST and PDT are checked; MST is not,
    because Arizona keeps it all year. EIA's fixed 09:00:00 EST is therefore ambiguous
    from March to November and offered, as stated, in winter;
  - for the WTO alone, its 00:00:00 placeholder time. Such an entry gives its date, in
    the explanation, and no time.

  Nothing is ever filled from the refresh time or the browser's time zone.
- **Excerpt.** It is shown apart from the form and never becomes the published text.
  Paste the release's text yourself; linked articles are never downloaded.

If the form has unsaved edits, or a saved preview is open, choosing another entry asks
first. Replacing clears any mock or paid confirmations and closes the preview; its saved
capture and records are kept and listed under Saved events. While a capture, mock, paid
send, publication or check is in flight, no entry can be chosen. A saved capture never
changes when a feed changes later, and sending still uses the exact saved, explicitly
approved request, once.

**Local cache.** The cache is `data/event-inbox/` (ignored by git), one JSON record per
source, each written atomically. A record keeps the last successful retrieval and the
latest attempt separately, so the page shows:

- each source's last successful retrieval and latest attempt, with any error;
- a failed source's earlier entries, marked as such;
- a source whose last attempt failed or was not made, never presented as live.

Each source's list keeps at most 50 entries from its latest successful refresh, in the
order the feed lists them.

**Filters.** **Topic** and **Source** narrow the current entries and the retained
headlines to what you choose; **Show all entries** clears both. They read only what the
page already holds: filtering requests no feed, calls no API and writes nothing. A
selected entry that a filter hides stays selected for triage, and the count under the
filters says so.

**Local archive (retained history).** Each successful refresh also adds what it retrieved
to `data/event-inbox/archive/<source>.json`:

- An entry keeps its stable source identity. While its meaningful content (title, link,
  excerpt, feed timestamp and their truncation marks) is unchanged, only its last-seen
  time moves. A refresh that only retrieves it again makes no new version.
- When the content changes, a new version is added and the earlier one is kept as it was.
- An entry that leaves its feed stays in the archive. **Show retained headlines (N)** lists
  it in the inbox with when it was last seen, and it can be selected for triage or
  analyzed like any other entry.
- Nothing expires, nothing is deleted, and nothing is fetched to fill the archive. It holds
  only metadata and excerpts that refreshes already validated.
- **Raw feed copies.** Each accepted response body, from every source, is also kept as this
  client received it, after undoing any gzip encoding the server applied (the retrieval
  record names it), under `data/event-inbox/raw/<source>/<sha256>.xml`, once per SHA-256
  and read-only, so unchanged feeds share one file. The WTO feed's full-article content
  element stays in its copy, unread. Storage only: no extra request, no article fetch, no
  model, and items, their fingerprints and triage inputs are unchanged. Earlier retrievals
  have no copy and none is reconstructed. A missing archive starts from the source's
  existing record on the next refresh.
- An archive that cannot be read is reported on its source's card and left exactly as it
  is; a refresh never writes over it.

**Retrieval records.** Every request a refresh makes, accepted or not, leaves one numbered,
write-once, read-only record under `data/event-inbox/acquisitions/<source>/` (version
inbox-acquisition-0.1). A source that is not requested (BLS without a contact) gets none.
Each record holds:

- the exact endpoint and that the request was a plain GET: no cache validators sent, no
  redirect followed, no retry;
- when it started and finished;
- the HTTP status and version, a fixed list of headers (the validators ETag and
  Last-Modified among them), the other header names without values, and how many
  Set-Cookie headers came (never their values);
- the body: complete, partial (with the count and SHA-256 of what arrived), not read (an
  error status or redirect) or none, any content encoding the server applied, and the
  kept copy's file name;
- for an accepted response, the parser version (`event-inbox-parser-0.1`) and its counts,
  and each kept entry's stable ID, content fingerprint, feed position and whether its
  headline or excerpt was shortened;
- how its entries compared with what was held before: new, changed or unchanged, by stable
  identity and content (never by title), and which entries the feed no longer lists.

Each source card shows its latest record: for example "Request 1, 2026-10-12 19:27 UTC: HTTP
200, body received complete, 9,649 bytes after undoing the server's gzip encoding (SHA-256 …),
kept privately. … Entries: 0 new, 15 unchanged, 0 changed." After **Refresh events**, the message lists what each source added,
reused, changed or refused, and says that nothing was triaged or analyzed. A record that
cannot be read is reported and never used or rewritten; a new request takes the next number.
Retrieval time, feed order and last-seen time never change an entry's content fingerprint or
its triage input, so an unchanged refresh adds no version and makes no saved result
outdated.

**Retained BIS snapshot.** BIS's News & Updates page, retained once under approval
`bis-semis-sources-01`, is also a local source of records, at `/inbox/bis-snapshot` (linked
from the Event inbox). It is a snapshot of what the page listed on 12 October 2026, not a live
feed: nothing on the page, in its index or on import requests anything, and nothing is
classified, summarized or analyzed. The retained bytes are used only when they match their
acquisition record (complete-body SHA-256, size, address, HTTP 200, `text/html; charset=utf-8`,
no content encoding); a changed byte is refused. Its embedded Next.js data is parsed as JSON
within fixed bounds, without running anything: 435 press-release records, each a distinct
address (no duplicate copies; five titles are shared by twelve different documents, which stay
separate), 432 with a listing timestamp and 3 without, 353 with text and 82 title only.
Each record keeps BIS's own fields (title, topics, country tags, summary, text as plain
paragraphs), the listing's metadata (its publication timestamp, and apart from it the CMS
creation and update times, which are never used as publication times) and two keyword
filters this application applies (the Related Cases word lists: semiconductors and advanced
computing, 65 records; export-control terms, 309), which are not classifications. Where the
same acquisition retained a record's release page (the UAE easing and the Applied Materials
penalty), the listing's text was compared with it: identical, paragraph for paragraph, without
the release's dateline header, whose date is kept separately. That covers those two records
only; every other text is labelled as the listing's, not checked.

Choosing **Open the retained snapshot** builds a local index once (`data/bis-snapshot/index/`,
named by the package's SHA-256 and the extractor version) and reuses it on every later read and
restart. Records can be searched, filtered, inspected and selected (at most 25). **Preview
import** sorts the selection into new records, existing ones (reused), changed ones (a newer
source version than the one imported: keep it, or add the new one as a version beside it;
nothing is replaced) and unusable ones, with reasons, and writes nothing. **Import** is local
and free: each record becomes an Event inbox entry `bis-snapshot:<key>` (its key from its
address), written once under `data/event-inbox/imports/bis-snapshot/` with its full text, its
extracted fields, the snapshot's SHA-256, the extractor and index versions and an import
record. Repeating an import, clicking twice, two concurrent submissions or a restart reuse what
is held and write nothing. Imported entries are listed apart from the feeds' entries, labelled
as snapshot records; their timestamp is the listing's, never a suggested publication time.
They are not offered for headline triage (its prompt names the five feeds), so no saved triage
result or fingerprint changes, and market context does not cover them. The event overview,
Related research and Related Cases treat them as Inbox entries under their unchanged rules.

```powershell
cd frontend; npm run build; npm run test:browser:snapshot; cd ..
```

**Refusals and limits.** A record that cannot be read is reported and left exactly as it
is; it is neither repaired nor refreshed over (move it aside to refresh that source).
Every response is checked, and refused if:

- it is not a 200 response;
- it redirects (redirects are never followed);
- it is larger than 1 MB, or slower than 30 seconds;
- it is not XML in RSS 2.0 or Atom, in UTF-8. The EIA feed alone may also declare
  ISO-8859-1, which it does; it is decoded as declared, and no other encoding is guessed;
- it contains a DTD or entity declaration;
- it lists more than 200 entries.

Some entries are skipped and counted, while the feed's other entries and the other
sources are still read:

- an entry whose link is not an `https` address on the publisher's own host;
- an entry whose title or excerpt holds markup that cannot be read as text;
- in the ISO-8859-1 feed, an entry whose text holds bytes 0x80 to 0x9F. ISO-8859-1 does
  not print those bytes; they are often Windows-1252 punctuation. The entry is skipped
  rather than guessed at or silently shortened. Entries are identified
by their GUID or Atom id (or link), never by title, so two releases with the same title
stay separate. Entries with a timestamp come first, newest first; ties keep the source
order and the feed's own order.

**BLS access.** BLS's robot policy (<https://www.bls.gov/bls/pss.htm>) reserves the
right to block automated requests that give no way to contact their owner, and its
blocking is not predictable. On 2026-10-07 one contact-free request from curl was
answered `403 Access Denied`, while one from this inbox's own client got the feed.
To follow the policy, the inbox sends your contact in its User-Agent and requests the
BLS feeds only when you have set one. It never disguises itself as a browser. Set the
contact in the shell that starts the server, then restart it:

```powershell
$env:SECOND_ORDER_FEED_CONTACT = "you@example.org"   # an address or URL you choose; one line, at most 200 characters
python -m second_order serve
```

Without it, the BLS sources show "Not requested" and the other feeds still refresh. BLS
and Federal Reserve content is public domain; cite the publisher (BLS emblems and Board
seals are not used). Neither the EIA nor the WTO feed asks for a contact; their credits
are above, and no logo of either is used.

**API.**

- `GET /api/inbox` returns the cached view, with the archive's retained entries and each
  source's latest retrieval record, read-only.
- `GET /api/events/processing` returns, per entry, whether saved triage or a verified
  capture exists, read-only.
- `POST /api/inbox/refresh` takes only an empty JSON object, from this server's own page,
  with the `X-Second-Order-Inbox` header and the same local Host and Origin checks as the
  other actions.
- A second refresh while one is running is refused with 409.

**Tests.** `tests/test_event_inbox.py` serves synthetic feeds through a fake network and
covers parsing, unsafe input, timestamps, failures, the cache, the API checks,
concurrency, and a saved capture left unchanged by a later refresh.
`tests/test_inbox_acquisitions.py` covers the retrieval records: headers, validators and
Set-Cookie handling, complete, partial and unread bodies, refused and failed requests next to
independent successful ones, unchanged, reordered, added, old-dated, changed and same-title
entries, damaged records, and refreshes that never triage, with saved results still reused
after one new entry and after a restart. `tests/test_inbox_raw.py` covers the kept copies. The browser check
covers the whole journey with simulated feeds, from Refresh events to a saved review and
a reload. It also covers a refusal, an entry without a timestamp, the edit and preview
protections, a partly failed second refresh, and the absence of outside requests:

```powershell
cd frontend; npm run build; npm run test:browser:inbox; cd ..
```

`tests/test_inbox_sources.py` covers the energy and trade sources with synthetic feeds
shaped like the real ones:

- the five-source allowlist, and the encoding and placeholder-time allowances, each
  limited to its own source;
- malformed and foreign links, daylight-saving contradictions and placeholder times;
- one request per feed with no retry, and a failed source that keeps its entries without
  blocking the others;
- retained history, and unchanged refreshes that add no version;
- triage: earlier entries keep their fingerprints and results when the sources are
  added, and no pair crosses publishers.

The sources browser check covers this in the page: the source cards and their credits,
labels, filters, a failed trade refresh, retained energy history, simulated triage and
Analyze this event:

```powershell
cd frontend; npm run build; npm run test:browser:sources; cd ..
```

#### Headline triage

Headline triage helps you browse fewer repetitive headlines and choose which entry deserves
a full analysis. Tick **Select for triage** on up to 25 entries, current or retained, and
choose **Preview triage**. Each entry gets:

- a **category** from a small taxonomy: Policy decision, Meeting minutes or record, Data
  release, Forecast or projection, Analysis or report, Update or correction, Announcement or
  notice, Other, and Insufficient information;
- an **event type**, such as "FOMC statement", only when its title or excerpt supports one,
  with the meeting date or reporting period when the text states it;
- a **summary** of about 25 words of what its title, excerpt and metadata say. A few more
  words are fine when accuracy or clarity needs them: 25 is a brevity target, not a
  rejection threshold. When only a headline was supplied, the summary stays short and
  limited to it. When the text says too little, the category is Insufficient information
  and the summary says so.

Since prompt triage-prompt-4, *Data release* means only a formal statistical release that
publishes new official figures. An article that analyzes or cites figures is *Analysis or
report*, and projections, forecasts or an outlook are *Forecast or projection*. The prompt
also states each source's kind of item; only the BLS sources publish formal statistical
releases.

No category was removed or renamed, so results saved under earlier versions stay valid.
These changes were made because the first paid trial put an EIA analysis article, the FOMC's
economic projections and a WTO trade outlook under *Data release*. Offline tests prove only
that the software states and enforces this; whether the real model now classifies and
summarizes better is unknown until another real trial.

Relations between entries may also be suggested: *Possibly the same event*, *Possible
update or correction*, or *Similar, but separate releases*. It is discovery support only:
no hypothesis, market impact, importance, score, ranking or trading view.

**Nothing runs on its own.** Refreshing feeds only discovers entries; it never triages
them. Opening the page, reloading, navigating, waiting and restarting the server request
nothing. Model work happens only after Preview triage, a visible plan and its own explicit
approval, and no request is ever retried, by this code or by its HTTP client.

**Saved results are reused; only missing work is requested.** Each successful result is
saved against the entry's input fingerprint and the configuration:

- the fingerprint covers exactly what the request sends for the entry: source identity,
  title, link, feed timestamp, excerpt and their marks; retrieval time, order and page
  state are not part of it;
- the configuration is the model, effort, thinking, prompt version and schema version.

An identical title on another date is a different entry with a different fingerprint, and
missing dates never merge anything. Before anything is prepared, every selected entry is
resolved locally and shown as one of:

- **Saved result reused**: never requested again. This holds after reopening, a server
  restart, selecting the same entries in any order, or a refresh that brings them back
  unchanged.
- **Needs a result**: a new entry, or a changed one (its new version has its own
  fingerprint; the earlier version and its result are kept).
- **Saved result from an earlier version**, after a model, prompt or schema change: shown
  with its provenance. It is regenerated only if you tick **Regenerate with the current
  version**; an upgrade never starts paid work on its own.
- **Earlier attempt unresolved**: an earlier request claimed it without an accepted result
  (failed, refused, in flight or uncertain). It stays visible and is requested again only
  if you tick **Request again**.

The plan states how many entries are reused, how many need a result, how many earlier
entries come along only as comparison context, how many are unresolved, the number of
planned requests (none or one) and the estimate. When every entry has a saved result and
every candidate pair was compared, nothing is requested at all and the saved results are
shown. Adding one headline to an earlier selection triages only that headline.

**Grouping is narrowed and never chained.** A relation is concluded by one response and
shown only for a selection that holds every entry it names, each with the content it had
then. Only candidate pairs are compared: the same publisher, with feed dates at most 10 days
apart or either date missing. Entries with a date but no usable instant (the WTO's
placeholder times, and EIA's EST stamps during daylight saving) count as missing, so every
pair of them from one publisher within a selection is a candidate. Entries from different
publishers are never compared, so duplicate coverage across publishers is not detected:
an EIA article and a WTO item about the same event, or a Federal Reserve release and an
EIA article about it, stay separate entries with no relation. When a new entry has
candidates among earlier ones, those
come along as **comparison context** only: ID, source, publisher, title, link and feed
date, with no excerpt and no new result requested. Context still costs input tokens, and
the plan and the estimate say how many.

**The comparison scope is enforced.** The candidate pairs a request still needs are its
comparison scope:

- they are listed in the request itself, so they are part of its SHA-256;
- they are shown with the plan, and the approval must repeat them exactly;
- the prompt names them as the only pairs the model may relate.

On receipt, a reply is rejected whole, and nothing in it is dropped or repaired, if it
relates any other two items. That covers items across publishers, items outside the
window, and a group containing an unlisted pair: listed pairs A–B and B–C never allow
relating A and C. A request with no pairs, which classifies entries only, must suggest no
relation at all.

Afterwards, only the listed pairs count as compared. Entries that merely appeared
together in a request were not compared, so their pair is still open. The pairs' sorted
order says nothing about which item updates which. In the results:

- a *Possibly the same event* group is shown exactly as its response stated it, collapsed,
  with its feed dates and the request it came from;
- a group from another response that shares an entry is never merged with it; it stays a
  note;
- updates, corrections and look-alike releases stay separate entries with notes;
- a response that puts one entry in two groups, or the same entries in a group and in
  *separate releases*, is refused whole;
- **Every entry, ungrouped** lists every selected entry once, with its status, result,
  provenance, official release link and **Analyze this event**.

**Inputs.** Only recorded inbox data is sent, labelled as such; feed timestamps are feed
metadata, never verified publication times. No feed is refreshed and no linked article is
fetched. The feed's own category is known, so it is context and never asked of the model.
Entry text is untrusted data: it travels as one JSON object in the user turn, and the
prompt says never to follow instructions in it.

**The request.** Model `claude-haiku-5-5`, `output_config.effort: "low"`, adaptive
thinking stated explicitly, `max_tokens` of 4,000 plus 320 per entry (12,000 at 25
entries; thinking and the structured reply together), and a JSON schema output format
(`output_config.format`) whose result IDs are an enum of the entries and whose relation IDs
are an enum of the IDs in the comparison scope (every supplied ID when the scope is empty;
the check on receipt decides). The system prompt states
its prompt and schema versions, so a version change always changes the request. No tools,
sampling parameters (they return 400 on this model), assistant prefill (also 400) or
fallback models. The limits are stated in the prompt and checked after receipt, because
structured outputs reject length limits. They are checked under a named validation policy,
recorded with every attempt:

- `triage-validation-3`, the current one, aims summaries at about 25 words and relation
  reasons at about 30. It rejects either only past a technical limit of 60 words or 600
  characters (prompt triage-prompt-5 states both targets);
- `triage-validation-2` relaxed only summaries and kept a hard 30-word limit for reasons;
- `triage-validation-1` treated 25 and 30 words as hard limits;
- event types keep a hard 8-word limit under all three.

This contract and the prices were checked on 2026-10-08 against Anthropic's documentation:

- <https://platform.claude.com/docs/en/about-claude/pricing>
- <https://platform.claude.com/docs/en/models/haiku-5-5/overview>
- <https://platform.claude.com/docs/en/build-with-claude/effort>
- <https://platform.claude.com/docs/en/build-with-claude/structured-outputs>

**Estimate.** Input is the request's size at 2 bytes per token plus 1,000 tokens the API
adds; output is `max_tokens`. Prices are $0.10 and $0.50 per million input and output
tokens, or $0.50 and $2.50 above 100,000 prompt tokens. It is a planning estimate, not a
billing ceiling. For the synthetic test feeds it is $0.0038 for seven new entries and $0.0026
for one new entry with two earlier ones as context. At 25 entries the 12,000-token output
cap alone is $0.0060, before input.

**Approval and sending.** When a request is planned, Preview saves its exact entries and
bytes first and shows them with the SHA-256, the settings and the estimate. Choose the
response before previewing:

- **Local simulation**, the default: $0. The server's in-process simulation answers; no
  provider is contacted and no model reads the entries, so its placeholder results say
  only that. Simulated results never count as paid ones.
- **Paid**: offered only on a server started with
  `python -m second_order serve --enable-paid-triage` and the key in
  `SECOND_ORDER_ANTHROPIC_API_KEY`, a separate opt-in from `--enable-paid-drafts`. The
  approval repeats the estimate, and the server checks it.

Comparison work is tracked apart from classification work. A comparison is identified by
both entries' input fingerprints in canonical order, the mode and the configuration, so
reversing the selection or adding unrelated entries never makes it new. A changed entry
never reuses an older comparison, and each relation keeps its own wording and member order.
The approval names the comparisons its preview planned. When it arrives, the server
recomputes the request's comparison work. An approval naming any pairs other than the
request's saved comparison pairs is refused. If the work is no longer exactly those pairs
(done, reserved or left unresolved by another request in the meantime), the approval is
refused before anything is reserved. Preview again: the remaining work is a new request
with its own pairs. Saved bytes and their pairs are never rewritten to fit.

Before anything is reserved, every entry to triage and every planned comparison is claimed
for that mode in a file created exclusively. A second click, another tab or another server
process therefore cannot send the same entry or the same comparison again: work with a saved
result is refused, and work claimed by an earlier request needs your explicit re-request of
one of its entries. A request is attempted once per mode.
A later attempt exists only when none was accepted and the approval re-requests every
entry. The saved bytes are posted once per attempt, never rebuilt. A lost paid reply is
shown as an unknown outcome that may have been billed. Failed and uncertain attempts stay
listed under **Saved requests** and never return to the queue on their own.

**Local re-check.** A recorded response that was not accepted can be re-checked under the
current validation policy, by explicit action: **Re-check … locally** under **Saved
requests**. It sends nothing and regenerates nothing. It parses the saved response bytes
again, with the request's own entries, comparison pairs and model, and records the outcome
apart, in `<attempt>/revalidations/<policy>.json`, created once.

The attempt's own request, response and rejection record never change. A response accepted
on a re-check is reused like any result, labelled as accepted on a local re-check and not
regenerated, and it still carries its original request's prompt version. After a send, the
banner reports the attempt's recorded outcome, never an inference from an empty plan.

A response is accepted only whole. A malformed, truncated, refused or incomplete reply, one
with a missing, repeated or unknown entry ID, or one relating items outside its request's
comparison pairs is kept in its own file, and nothing from it is shown. It is never sent
again on its own.

**Earlier requests.** Requests prepared under the earlier contract (headline-triage-0.2)
carry no comparison pairs, and their replies' relations were not limited to planned
comparisons. They stay readable under **Saved requests** with their provenance and
whatever they recorded, but they are never sent, in either mode. Their results show as
from an earlier version. Their relations are labelled as not limited to planned
comparisons, and nothing is regenerated on its own. A summary or event type stating a number that its entry's own title and
excerpt do not is flagged for you to check.

**Records.** Everything is private, under `data/headline-triage/` (ignored by git), apart
from captures, attempts, drafts and reviews; triage never uses a capture's attempt and
leaves the Sonnet drafting path unchanged.

- `requests/<triage-id>/` holds `selection.json` (entries, context and comparison pairs,
  as sent), `request.json` (the exact bytes) and `prepared.json` (configuration, comparison
  pairs, hashes, estimate).
- One folder per attempt (`simulated`, `paid`, `paid-2`, ...) holds a reservation, the send
  record, the exact response and a manifest written last: outcome, provenance, usage and
  cost when reported.
- `claims/<mode>/<fingerprint>-<configuration>/<n>.json` records which attempt claimed an
  entry, and `claims/<mode>/pairs/<both fingerprints>-<configuration>/<n>.json` which
  attempt claimed a comparison.

Results are read from the saved responses themselves, re-verified on every read, so
nothing is copied twice. A record that does not verify is reported and left alone. No key
or secret header is ever written.

**API.** Every write needs this page's `X-Second-Order-Triage` header and the usual local
Host and Origin checks:

- `GET /api/triage/selection?mode=…&ids=…&reprocess=…` returns the plan and saved results;
  read only;
- `GET /api/triage` and `GET /api/triage/<id>` list and show saved requests; read only;
- `POST /api/triage` takes `{"item_ids", "mode", "reprocess_ids"}`; it saves a request only
  when one is planned;
- `POST /api/triage/<id>/simulated` takes
  `{"request_sha256", "approve_simulated_response": true, "reprocess_ids", "comparison_pairs"}`;
- `POST /api/triage/<id>/paid` takes
  `{"request_sha256", "approve_paid_request": true, "estimated_max_usd", "reprocess_ids", "comparison_pairs"}`.

In both approvals, `comparison_pairs` must be exactly the request's saved pairs, in any
order. `POST /api/triage/<id>/<attempt>/revalidate` takes `{"response_sha256"}`, naming the
attempt's saved response; it re-checks it locally and calls nothing.

**Tests.** `tests/test_headline_triage.py` and `tests/test_inbox_archive.py` use synthetic
feeds and a fake provider that counts every request it receives; `tests/test_triage_scope.py`
covers the comparison scope (in-scope and refused relations, empty scopes, tampered and
stale approvals, reuse accounting and earlier requests), and `tests/test_triage_quality.py`
the summary target, the taxonomy, local re-checks and version changes that start nothing.
They prove zero
additional calls after unchanged refreshes, reopening, restarts and repeated selections,
and that one added entry is triaged alone. They also cover:

- all-cached selections, comparison-only requests and narrowing;
- concurrent and overlapping approvals that cannot double-send an entry or a comparison,
  across threads and across separate processes, and stale approvals refused before sending;
- unresolved entries that are never re-queued, and prompt upgrades that never reprocess;
- retained history, kept versions and offline reads;
- every refused response shape.

The browser check covers the same journey in the page, counting the fake's records:

```powershell
cd frontend; npm run build; npm run test:browser:triage; cd ..
```

**Not yet done.** No real provider request has been made with this path; a separately
approved trial is the next step. Validation proves structure, not that a summary is
faithful or a suggested group is right, so check each against its official release.

### Drafts for review

The Tracker's **Analyze an event** action is the UI path into this section. Enter a
headline, source URL, publication time and published text. The publication time is a
date, a time of day and a UTC offset chosen from a list (−12:00 to +14:00 in 15-minute
steps; there is no default, and +00:00 is UTC). It is entered as the publication states
it and is never taken from the computer's time zone. For example, 14:00 at UTC−04:00 on
4 October 2026 is sent as `2026-10-04T14:00:00-04:00` and saved in the request as
`2026-10-04T18:00:00Z`. The server refuses impossible dates and times, other formats and
offsets outside that list, rather than adjusting them. The server validates the inputs,
stores an immutable capture under `data/intake/`, and shows the exact saved Sonnet 5.5
request, its SHA-256, model settings and a planning cost estimate. The preview shows the
publication time exactly as supplied beside the UTC instant read from the saved request,
so the instant can be checked before approval. The response source is a local mock by
default: after a separate checkbox confirmation, it copies the already-saved request
bytes into one local attempt and records either a deterministic mock draft or a mock
decline. It contacts no provider and costs $0. A paid Claude request is possible only
on a server started for it (see **Paid requests** below). Neither path rebuilds the
approved request, retries, falls back, freezes or evaluates. New captures are saved under
the H.15 drafting contract (draft-prompt-6): the same instructions as draft-prompt-5, but
offering the Board's H.15 observable IDs. A capture saved earlier keeps draft-prompt-5 and
its FRED IDs; its saved bytes are never rebuilt or remapped.

The resulting draft, decline or failure is published to `data/tracker-drafts/` and
opened in the existing review panel. Notes, judgment and supported corrections can then
be saved through the same UI. If a review there has unsaved edits, the page asks before
opening the new draft; declining keeps the edits, and the new draft waits in the list.
A list refresh that is slow or fails never closes the open review.

Draft folders have one owner each. `prepare-drafts` owns `data/prepared-drafts/` and
replaces its index with exactly the attempts it is given, as before. The Tracker owns
`data/tracker-drafts/`: one immutable file per published draft, created exclusively
and never replaced, with no index file to rewrite. The Tracker lists both folders, so
running `prepare-drafts` never hides a Tracker draft or its saved reviews.

Each capture gets at most one attempt, mock or paid, under
`data/tracker-attempts/<capture>/`. Its files are written whole and the manifest last.
If a reply is lost or the server reports an error, the page reads what was recorded
instead of offering to run again: no attempt (approving again is allowed), an
interrupted attempt (kept as recorded; it blocks another attempt, so capture the event
again), a recorded response awaiting publication (offered as **Publish the recorded
response**, which uses the saved request and response and sends or generates nothing),
or a result ready for review.

A saved event can be resumed after a reload or a server restart. Under the form,
**Saved events** lists every capture, newest first; one whose saved files no longer
verify is listed as such and cannot be opened. **Open** reads the capture's verified
saved request (`GET /api/intake/<capture>`) and then what its attempt recorded
(`GET /api/intake/<capture>/attempt`). An open preview has **Refresh saved preview**,
which repeats both reads, so the sending modes of a server restarted with
`--enable-paid-drafts` appear without recapturing; a refresh refuses a request whose
hash differs from the one shown. Opening and refreshing are reads only: nothing is
captured, rebuilt, sent, reserved or approved, and the review panel is not switched.
Both clear any approval and select the local mock. Approval is offered only when both
reads verify and no attempt is recorded. An existing attempt, an attempt state that
cannot be read and one that does not verify all block it. A failed refresh keeps the
old preview, marked as possibly out of date, with approval blocked until a refresh
succeeds, and a reply to an earlier selection is ignored.

#### Paid requests (off unless the server enables them)

There are three distinct levels, and only the last one sends anything:

1. **Mock operation** (the default): `python -m second_order serve`. The preview offers
   the paid option disabled, with the reason. Nothing can reach a provider.
2. **Live operation enabled**: put the key in `SECOND_ORDER_ANTHROPIC_API_KEY` in your
   own terminal, then run `python -m second_order serve --enable-paid-drafts`. Without a
   well-formed key the server refuses to start. Starting it sends nothing, and each
   capture still opens with the local mock selected. A preview already open in the page
   keeps the modes it last read until **Refresh saved preview** or **Open** reads them
   again.
3. **An approved send**: in a capture's preview, choose **One paid claude-sonnet-5-5
   request**, read the cost decision, tick its separate approval and click **Send one
   paid request**. That sends exactly one request for that capture.

The preview says the same in its data. The capture response and `GET /api/intake/<capture>`
report `provider_called: false`, because previewing reads the saved request and sends
nothing. `modes` is the one statement of what the server offers: `mock` always, `paid`
only at level 2. An offered mode is not an approval; only level 3 sends.

The cost decision shows a planning estimate for the exact saved bytes and how it was
computed. It is not a billing ceiling. It assumes Sonnet 5.5 at $2 per million input
tokens and $10 per million output tokens (read on 2026-10-05 from
<https://platform.claude.com/docs/en/about-claude/pricing>). Input tokens are taken as
the saved request's size at 2 bytes per token (deliberately high), plus 286 tool-use
system tokens and 1,000 for the thinking prompt. Output tokens are taken at the
request's `max_tokens` (16,000, thinking included). It assumes standard global routing.
The Console's usage is authoritative.

Before anything is reserved, the server refuses the send unless all of these hold:
paid sending is enabled; the key is present and well formed; the approval names the
saved request's SHA-256, says `approve_paid_request: true` and repeats the estimate
shown; the capture still verifies; and the request does not carry the key. The
reservation and the exact request bytes are then written. The send is recorded as
started, and the saved bytes are posted once to the Messages API, with the key only in
the `x-api-key` header. Nothing is rebuilt or reserialized, and there are no retries,
redirects, proxies from the environment, fallbacks or repair requests.

The response bytes, HTTP status, `request-id` and usage are recorded as received; a
cost is shown only when the response reports usage. An error body is not kept, and a
reply that echoes the key is not kept at all. No saved file is ever allowed to contain
the key. A timeout or lost connection after sending is recorded as an unknown outcome,
since the provider may have received and billed the request; it is opened for review
as a failure and never sent again. Reading the attempt state never sends. If
publishing fails, **Publish the recorded response** uses the saved records without
contacting the provider. Drafts from a paid request are attributed to the model. Mock
drafts say they came from a local fixture, and record no HTTP status or request ID.

`npm run test:browser:resume` checks resuming in the browser. It captures an event,
reloads and reopens it, then restarts its test server from mock-only to paid-enabled
(the same simulated provider) over the same temporary records and refreshes the open
preview. It sends the reopened capture once and reviews the result, and confirms that
opening and refreshing write nothing and clear approvals. It also covers an attempted,
an unreadable and an invalid capture, a failed refresh and an out-of-order reply.

`npm run test:browser:paid` checks the whole paid path in the browser against a
simulated provider: an in-process fake with a dummy key, started by the test server
only. It covers the cost decision, the approval, a draft, a refusal, an invalid
response, a provider error, a timeout, a lost reply and a credential echo, each opened
and reviewed. No real request is made by any test.

**Verification status.** The paid path is implemented but has never sent a real request.

- Verified offline, against an injected fake transport with a dummy key (unit tests and
  `npm run test:browser:paid`): the saved bytes are posted once, unchanged; a missing
  flag or key, a wrong hash, a changed estimate or a request carrying the key is refused
  before any reservation; concurrent or repeated approvals, and switching between mock
  and paid, make at most one transport call per capture; drafts, declines, invalid
  responses, provider errors, timeouts, interruptions, lost replies and credential
  echoes are recorded and open for review; recovery publishes from the saved records
  without the provider; reads and previews never send or reserve, with paid sending
  enabled or not; no saved file or API response carries the key.
- Verified on the production client over an in-process network
  (`tests/test_paid_transport.py`): sends use `live_client` unchanged, and only the
  connection pool's network layer is replaced. A refused connection is attempted once,
  with no retry. A 307 to the same host or another host is not followed: the target gets
  no request and no key, and the redirect is recorded as a provider error, opens for
  review and blocks another attempt. Changing `live_client` to retry or follow redirects
  fails these tests. Its other settings (no proxies from the environment, a 10-minute
  read timeout) are fixed in code; none of this has run over a real network.
- Not verified at all: anything that needs the real Claude API. That includes whether it
  accepts these exact bytes (model ID, effort, thinking and tool settings),
  authentication with a real key, TLS and network behavior, the real response, usage
  and `request-id` formats, a real timeout or disconnect, and how the planning estimate
  compares with the usage the Console bills.
- Known limitations: the estimate is a planning figure, not a billing ceiling; an
  unknown outcome is never retried, so its billing must be checked in the Console; an
  interrupted capture must be captured again. A first real single-event trial is
  deferred and needs its own approval.

Saved pilot attempts can be reviewed in a separate "Drafts for review" section of the
Tracker. Preparation is explicit and offline; name each saved attempt directory:

```powershell
python -m second_order prepare-drafts --attempt data\pilot\<run>\<case> --attempt data\pilot\<run>\<case>
python -m second_order serve
```

Preparation reads only each attempt's original `request.json`, `response.json` and
`manifest.json`, checks the recorded hashes and refuses any mismatch or ambiguous
source; it never rebuilds inputs from the current cases or prompt. It writes sanitized
views to `data/prepared-drafts/` (git-ignored), which `serve` exposes at `/api/drafts`.
A view holds the source as recorded (shown as plain text), the model's draft or its
public explanation for declining, and selected provenance (model, prompt version and
hash, request ID, timestamps). It never holds thinking, the system prompt, headers or
the raw records. Drafts load even when no Dossier has been prepared.

Each draft is labelled "Not frozen · Requires human review", with the source and the
model's interpretation side by side and a short generic review checklist. A decline
shows as "No draft"; invalid responses and technical failures are shown separately.
The model's proposal is never edited, and nothing is approved, frozen, evaluated or
scored; checks on a draft's structure do not verify its reasoning. This is a review
workflow, not evidence of predictive accuracy. A reviewed draft can be frozen only from the
Hypotheses page, by its own explicit approval (see **Freezing from the interface**).

Under "Your review" you can save notes and mark a draft "Needs revision" or
"Human-reviewed". These labels record your judgment only: they do not verify the
model's reasoning or make a draft eligible for research. For a draft outcome you can
also correct the summary and each leg's reasoning, falsifier and
`headline_reports_move` flag; the map, observables, directions, horizons and primary
leg stay as the model proposed them. Corrections are shown beside the model's
original and attributed to you. Declines and failures take notes and a judgment, never
corrections, so no draft is invented for them.

Each save is an explicit action that appends a new, immutable version under
`data/draft-reviews/<draft id>/` (git-ignored). The server stamps the time and records
the parent version and the hashes of the prepared view, the recorded request and the
recorded response; earlier versions, pilot records and prepared views are never
rewritten. A draft is served with the fingerprint (SHA-256) of its exact bytes, and a
save must name the fingerprint of the view the page loaded: if the prepared view has
changed since, even with the same prompt and response hashes, the save is refused and
nothing is appended. A save based on an outdated version is refused rather than
merged. Versions saved against an earlier prepared view stay listed, marked as such,
but their judgment and corrections are not applied to the view shown now. The save
endpoint accepts only JSON sent from this server's own page on a local address.

Unsaved changes are marked. The page asks before they are discarded by switching
drafts, following a link to the Method page or a Dossier, using Back or Forward, or
closing the page. Edits made while a save is in flight are kept for the next version. A
refused save keeps your edits. If no readable reply arrives, the page says the save is
not confirmed (it may or may not have been recorded), keeps your edits and offers to
check the saved versions; nothing is sent again automatically. If your save was
recorded but a newer version followed it, the page says so; it shows the newer version
only when you reload, which discards edits made on the page since.

A browser check drives these cases (leaving with unsaved edits, a delayed save, lost
replies and a prepared view that changes under the page) in headless Chrome, against
synthetic drafts served from a temporary folder. It needs Chrome (or
`SECOND_ORDER_CHROME`) and a built client:

```powershell
cd frontend; npm run build; node tests/browser/review-check.mjs; cd ..
```

The intake acceptance check drives the complete zero-cost path through the browser:
form entry, exact saved-request preview, explicit mock approval, the prepared draft and
one saved human-review version, with the attempt request byte-identical to the approved
saved request. It then drives the failure paths: unsaved review edits while a new draft
arrives (declined, and through a slow and a failed list refresh), a lost dispatch reply,
a publication failure recovered from the saved records, an interrupted attempt, a
refusal reviewed across a refresh, and `prepare-drafts` run while Tracker drafts exist.
Test-only failures are injected by the test server, not by the application:

```powershell
cd frontend; npm run test:browser:intake; cd ..
```

The demo works without credentials, a network connection or an existing database.
It evaluates two fictional events: the fictional Central Bank of Demoland lowers its policy
rate, in June and in October 2024. Their market data are FICTIONAL demonstration series
(`fixtures/demo-market.json`, demo-market-0.1), every number invented by
`second_order/demo_market.py`; nothing in them is a market observation. Their hypotheses are
manual retrospective illustrations, tagged replay/showcase. Their outcomes are recomputed
from the fixture by the ordinary scorer; the generator places invented moves after the two
events, so the labels are a demonstration of the procedure, not a finding. Both research
scoreboards remain empty. The records are not evidence of model performance.
Their prompt hash identifies the committed manual_recipe.txt text, not a live model request.

### My analyses

**My analyses** (`/analyses`, in the site navigation) is your private, local work library
of the Tracker's analyses: every event you analyzed whose response is recorded and
published for review. For each one it shows:

- the headline and a link to the recorded source address;
- the publication time in the offset you entered, beside the same instant in UTC;
- the recorded outcome (Draft, No draft, Invalid response or Technical failure);
- the response mode from the attempt's own records: a local mock, which contacts no
  provider, or a paid provider response with its model and HTTP status;
- your review status and the start of your latest note, kept apart from a short preview
  of the model's own words.

Search covers headlines, source addresses, the model's output and your latest notes;
filters narrow by outcome, response mode and review status. Both are kept in the address,
so a reload, Back or a shared link restores them. **Open review** opens the analysis in
the existing Drafts for review screen, which keeps the model's proposal and your
corrections as separate layers. Saving there is the same explicit, versioned save as
before, and **← Back to My analyses** returns to the same filtered list with the updated
status.

The review status comes only from versions saved against the exact view shown now: a
version saved against an earlier view never makes the current one count as reviewed
("Not reviewed for this view"), and a history that does not verify is shown as
unreadable, never as "Not reviewed". "Human-reviewed" records that a person reviewed the
content; it does not confirm a mechanism, make a draft research evidence, show that a
forecast succeeded or recommend a trade.

Only analyses read through the verified readers are listed (the capture, the attempt
rebuilt and compared with its published view, and the review history). A record that
does not verify is listed under "Records that could not be read" with the reason; it is
never repaired or dropped. Saved events with no published review view stay under Saved
events and are only counted, as are the prepared pilot drafts, which remain in Drafts for
review. The page reads `GET /api/analyses`, which writes nothing, sends nothing and keeps
the local Host check. Nothing in this library is copied into the committed case library.

```powershell
cd frontend; npm run build; npm run test:browser:analyses; cd ..
```

### Market context for selected events

**Market context** (`/market-context`, in the site navigation) shows the Federal Reserve
Board's daily H.15 2-year and 10-year Treasury yields around selected macro events. It is
private and local: its records stay under `data/market-context/` (git-ignored), never in
the committed case library or its bundle, which are unchanged.

Supported in this first slice:

- Event inbox entries from the Federal Reserve's monetary-policy press releases and the
  BLS Employment Situation and CPI feeds, current or retained. Each has a **Market
  context** button beside **Analyze this event**.
- Saved events from Analyze an event whose official link is a Federal Reserve
  monetary-policy press release (`www.federalreserve.gov/newsevents/pressreleases/monetary…`)
  or a BLS Employment Situation or CPI release (`www.bls.gov/news.release/…`). They are
  listed on the Market context page automatically.
- Energy (EIA) and trade (WTO) entries are outside the slice. Their entries say so, and
  no yields are attached to them.

Nothing here needs a model draft, headline triage or a human review, and nothing changes
draft views, their fingerprints or review records.

**The context date** is a New York calendar date (convention `new-york-calendar-date-1`):

- A saved event keeps the publication time and UTC offset entered with it. Its context
  date is that instant's New York date; there is nothing to confirm.
- An Inbox entry's feed timestamp is metadata, not a verified publication instant. The
  page suggests the New York date of the feed's timestamp when the timestamp states an
  instant, and suggests nothing otherwise; no time or offset is invented. Nothing is
  saved until you confirm a date and tick the convention. Each confirmation is a new
  numbered version under `data/market-context/events/<event>/`, and earlier versions
  stay. A confirmation belongs to the entry version it was made for: if the entry's
  content changes, the page says the date was confirmed for an earlier version, and no
  date applies until you confirm one for the version held now.

**The view** covers every calendar date from 14 days before to 14 days after the context
date, as a chart and a table. Each value is either observed or has a stated reason:

- ND or no row in the source on an expected session;
- a SIFMA holiday, or a weekend;
- not in the local data, or after the last date its retrieval returned;
- today or later;
- retrieval versions that disagree.

Descriptive changes run from the expected session immediately before the context date to
the first and the fifth expected sessions strictly after it (SIFMA calendar). They are
differences in basis points, computed from the exact published decimals, not bond
returns, and the table shows each endpoint's date and value. A missing endpoint stays
unavailable with its reason: no other date is chosen, and nothing is interpolated or
carried forward. These are descriptive observations, not an intraday reaction, a causal
attribution, a hypothesis confirmation, a trading signal or a research score, and the
values are current downloads, not historical vintages. The "Show weekends and holidays"
setting only filters the table on the page.

**Observations are kept apart from events** and reused. Three kinds are read:

- The committed case-library downloads, read in place and never copied. They cover
  15 January to 12 February and 5 March to 29 July 2025.
- Earlier private retrievals under `data/market-context/retrievals/<id>/`: the Data
  Download Program's two-series CSV, as approved requests saved it before requests moved
  to the release package. They are still read, unchanged; nothing writes new ones.
- Kept release packages under `data/market-context/packages/<id>/`: the Board's H.15 XML
  package exactly as received (`package.zip`), its acquisition record, and one
  validation record per parser version, each written once and read-only. A package is
  used only when the validation for the current parser version accepted it.

Every read verifies each retrieval again. For a CSV: its address, recorded HTTP reply,
size and SHA-256, the series in its header and its range. For a package: its acquisition
record against the package's size and SHA-256, and its validation record's versions,
package identity and every row and count. One that does not verify is listed with its
reason and not used; it is never repaired or replaced. Where several retrievals state a
date, they are combined only when they agree exactly. Otherwise the date shows every
version and no value, so a package and an earlier CSV that disagree stay a conflict.

**Before any request** the page shows:

- the source and series, the exact address and what the download contains;
- the requested coverage (the events' windows) and what is held locally;
- the retrievals reused, the sessions missing, and any kept package that is not used;
- the exact number of requests: 0 or 1;
- that no key and no charge apply, the Board's terms, and its announced changes to its
  downloads.

The one request downloads the Board's complete H.15 release package
(`https://www.federalreserve.gov/releases/h15/data/FRB_h15_xml.zip`): every series of the
release over its full history, not a two-series or date-bounded download. The package
retained on 10 October 2026 was 4,285,147 bytes, about 71 MB of XML once decompressed.
Only the two series are read from it, and it is kept, so later selections it covers need
no request. Sessions on or after today are never requested.

**Sending.** Only a server started with `--enable-market-retrieval` sends an approved
request; otherwise the page says so and sends nothing. An approval names the plan's
SHA-256, its events and the attempt number. Under a cross-process lock, the plan is
computed again from the local data immediately before sending, and any difference
refuses the approval with nothing sent. The attempt's start is recorded before the
request goes out, and its outcome after. Each attempt number can be started once, so a
double click, another tab or another server process cannot send it twice. Plans are
versioned (`market-retrieval-plan-0.2` names the package), so an approval of an earlier
plan for the two-series CSV cannot send this request.

The fetcher requests only the fixed package address, with `Accept: */*`,
`Accept-Encoding: identity` and this app's User-Agent. It sends no cookie, keeps no
Set-Cookie value, follows no redirect and refuses any content encoding instead of
decoding it. It streams the raw bytes to a private staging file and never holds the
archive in memory. Limits: 200 MB transferred, a 10-second connect and 60-second read
timeout, and a 10-minute deadline. An error reply's body is read only up to 4 KiB, kept
as an untrusted excerpt. There are no timers, background refreshes, fetches on reads or
automatic retries. A failed or uncertain attempt stays listed, and another attempt needs
its own approval.

**Retention is separate from acceptance.** A complete reply whose archive passes the
safeguards is kept as acquired but unvalidated. Its data is then read, and the result is
recorded once as accepted or refused. The safeguards apply to the actual bytes, and
nothing is extracted to disk:

- at most 50 entries, with unique relative names (no absolute path, drive, backslash,
  parent reference or control character);
- no symbolic link, no encryption, and only stored or deflated entries;
- at most 512 MB per entry and 1 GB in all when decompressed, at most 200:1 expansion,
  and every entry's CRC.

`<!DOCTYPE` or `<!ENTITY` byte patterns in any entry are recorded, not acted on: the entry,
the marker, its offset and up to 200 bytes of context, at most 20 excerpts. A byte
pattern does not show what the text is. A reply that fails a safeguard is not kept.

**The data entry is read under the parser's protections**, not trusted. Only
`H15_data.xml` is parsed, as a stream through expat, with these refusals:

- DOCTYPE, entity, notation and unparsed-entity declarations are refused;
- parameter entities are never parsed;
- every external reference is refused, so no DTD, schema or other resource is read or
  fetched, local files included.

The package's structure entries (`H15_struct.xml`, `frb_common.xsd`) begin with a DOCTYPE
declaration. They are never parsed, and nothing needs them.

The data entry must name the H15 release and hold each series exactly once in the H15
dataset, with exactly the expected attributes (currency `NA`, frequency code `9`,
instrument `TCMNOM`, the maturity, unit `Percent:_Per_Year`, multiplier `1`) and
descriptions. Observations must be on weekdays, in strictly increasing order:

- status `A` carries a plain decimal, kept as its exact text;
- status `ND` carries `-9999` and is stated as ND, the CSV download's no-value marker.

Any other status, a duplicate or out-of-order date, a weekend, or a date after the day of
the request refuses the package's data. The frequency code's label is defined in the
structure entries, which are not parsed. So the business-day frequency is checked from
the observations themselves and from the series names' `.B` suffix.

**The derived index** is the validation record: the two series' rows, counts and
coverage, tied to the package's SHA-256 and the parser version
(`h15-release-xml-parser-0.1`). It is checked again on every read. A record for other
bytes or another parser version, or whose rows or counts do not match, is not used, and
nothing is repaired. A package states the dates both series cover, from the later of
their first observations to the earlier of their last.

**Validating a kept package locally.** A package kept outside the app, or one read by an
earlier parser version, is listed as not yet validated and is not used. Validate it with:

```powershell
python -m second_order market-packages validate
```

It checks the archive, parses the data entry under the same policy, writes one
validation record per package, and fetches nothing. `market-packages list` only reads.

**Source choice.** The Board announced on 16 July 2026 that it will remove the Data
Download Program's "Build Your Package" option the week of 9 November 2026, and later
its preformatted packages, before retiring the program
(<https://www.federalreserve.gov/data/data-download-fred-information.htm>). It directs
users to FRED or to the XML file on each release page. New requests use that XML file.
The committed bundle and the earlier CSV retrievals, made with Build Your Package, stay
as they are. If the package's address stops working, the attempt fails and is shown as
failed, and nothing switches to another source. Not used:

- FRED: its terms, and it needs a key.
- Treasury's own par-yield data: a different publisher and provenance.

**What is verified, and what is not.** The package format was checked on real bytes from
one keyless download on 10 October 2026 (UTC). That download was approved for source
inspection and made by a standalone script, not by this app. The package was kept
privately as acquired but unvalidated, then validated locally with the command above:

- its two series parse completely under the policy (13,138 and 16,898 observations
  through 8 October 2026);
- an independent reader that shares no code with the parser extracts the same rows;
- all 546 values and ND markers of the committed and private CSV downloads match the
  package's text.

The app's own package transport has not sent a real request. Its first approved request
will be the first live check of that path, and the synthetic tests do not establish that
the live source stays compatible.

**Activating it** is a separate, explicit step:

1. Start `python -m second_order serve --enable-market-retrieval` (no key and no
   environment variable are needed).
2. Open Market context for a supported event whose window needs sessions that no kept
   package holds, confirm its date and read the plan.
3. Approve its one request, only if you choose to.

The tests use synthetic packages in the inspected format, through a fake transport that
counts every request (`tests/test_market_package.py`, `tests/test_market_retrieval.py`,
`tests/test_event_market_context.py`). They prove that:

- cached work, reopening, a server restart and selections a kept package covers send
  nothing;
- concurrent or repeated approvals send at most once, and an approval of an earlier plan
  version sends nothing;
- unsafe, corrupt or oversized archives are not kept, and data the parser refuses is
  kept but never used;
- the parser refuses declarations, external resources and unexpected metadata or
  observations;
- a tampered or mismatched index is not used;
- earlier CSV records still read, and disagreements with a package stay conflicts;
- failures are recorded and never retried, and no cookie is sent or kept.

They also cover dates, time zones, weekends and holidays, partial windows, missing
endpoints, basis points and corrupted records. The independent reader also runs,
read-only, against a real kept package when `SECOND_ORDER_H15_PACKAGE` names its folder.
The browser check runs the whole journey, labelled synthetic data included, against the
committed bundle's real values for 18 June 2025:

```powershell
cd frontend; npm run build; npm run test:browser:context-events; cd ..
```

### Event overview

**Event overview** puts one event's local records on a single private page:
`/events/inbox/<entry>` for an Event inbox entry, `/events/capture/<capture>` for a saved
event from Analyze an event. Each Event inbox entry, each My analyses card, and each
saved market-context entry and page has an **Event overview** link. It is not the
research Dossier at `/h/:id`: nothing on it is frozen, evaluated or scored, and it never
enters research summaries. Every section reads the existing verified records; when one
has nothing, it says why and links to the existing workflow, and nothing is generated to
fill it.

0. **Processing history.** A compact, dated list of what was done with the event, read
   from the records each step already keeps (version event-history-0.1), with a link to
   each existing record rather than a copy of it:
   - **Source and retained versions:** each archived version, when it was first and last
     seen, its feed timestamp and texts, and how many retrieval records listed it (and
     kept its response); versions first seen before records existed say so.
   - **Headline triage:** every saved request that carried the entry, at any version, as
     an entry to classify or only as comparison context, with each attempt's outcome
     (accepted, accepted on a local re-check, not accepted, provider error, no reply,
     interrupted or uncertain) and the result.
   - **Analysis requests and outcomes:** each saved event that recorded the entry as its
     origin, with its one attempt: none (captured, nothing sent), a mock or paid draft, no
     draft, an invalid or uncertain send.
   - **Human reviews:** each review version, current only when saved against the view
     served now.
   - **Use in a frozen hypothesis:** freezes from those drafts, found only through
     verified freeze records in the research store. Research intake is closed, so a freeze
     is a prospective showcase, never research use.

   "Not processed" is a valid state. Costs keep apart the planning estimate (an upper
   bound made before sending, for the whole request), the cost derived from the usage the
   provider reported, and billing, which no local record verifies; an unknown amount stays
   unknown and an uncertain send may have been billed. **What this history cannot show**
   lists the gaps: saved events without a recorded origin (never matched by headline, date
   or link), unreadable records, retrievals before records existed, and that keyword
   matches, related-research links and opened pages are not processing steps.

1. **Source.**
   - For an entry: the feed's headline, publisher, official link, excerpt and timestamp,
     labelled as feed metadata (not a verified publication instant), with every archived
     version of the entry.
   - For a saved event: the publication time as its operator supplied it, the captured
     text, when it was captured, and its Inbox origin, or that none is recorded.
   - No article text is downloaded.
2. **Saved headline triage.** Saved results for that exact entry version: category, event
   type and summary, with the response's model, prompt and configuration. A result kept
   under an earlier configuration, or accepted on a local re-check, is labelled as such.
   Results saved for other versions of the entry are counted, never shown as this one's.
   Suggested relations to other entries are shown as suggestions from one response, not
   as proof that two entries are one event.
3. **Draft and human review.**
   - A saved event's draft, refusal or recorded failure appears beside your review, read
     by the same reader as My analyses: the model's words in one layer, your judgment in
     another.
   - A review counts as current only when it was saved against the exact draft-view
     fingerprint served now. **Open review** opens the existing review editor, whose
     **← Back to the event overview** returns to the same event. Saving there stays the
     explicit, versioned save it was.
   - For an entry, this section lists the saved events whose capture recorded that entry
     as its origin.
4. **Market context.** The market-context view (chart, table, descriptive basis-point
   changes and provenance), or the reason it is missing: an unsupported topic, no
   confirmed date, a date confirmed for an earlier version of the entry, no local data,
   or a partial window. **Open its market-context page** leads to the existing
   confirmation and approval steps; opening it requests nothing.
5. **Treasury findings.** The occasion this event belongs to in the latest findings check
   (below), with its count of findings or why it was not measured, and a link to it.

**Identity and links.** An overview is anchored on the entry's feed identity or the
capture's ID. Records are joined only through those identities and an explicit,
recorded link, never by headline, date, similarity or retrieval time:

- When **Analyze this event** fills the form and you capture it, the capture action names
  that entry and the exact version it showed (its content fingerprint). The server checks
  that the version is held locally, or captures nothing.
- The origin is then recorded once in `data/event-links/<capture>.json`, beside the
  capture: the capture, its request bytes and any approval are unchanged, and the request
  is the same with or without an origin.
- Captures made before origins were recorded, or typed by hand, have no origin and show
  that gap. This includes the two saved captures of the 17 September 2025 FOMC statement:
  each keeps its own draft and review, and sharing the same market data does not link
  them.
- Repeated release titles stay separate events, and several captures of one statement
  stay separate records.
- When an entry's content changes, its triage, its links and any confirmed market-context
  date stay with the version they were made for; a new version gets none of them until
  you act on it.

`GET /api/events/inbox/<entry>` and `GET /api/events/capture/<capture>` only read: they
fetch, write, repair, reserve and regenerate nothing.

The tests use temporary folders and counting fakes for the feeds, the model and the
Board (`tests/test_event_overview.py`). They cover:

- capture-only and entry-only events, and origins and their refusals;
- reviewed, stale and unreadable reviews, a refusal and an unfinished attempt;
- an earlier-configuration triage result accepted on a local re-check;
- unsupported, missing and complete market context;
- recurring identical titles, a changed entry, and several captures of one entry;
- corrupt and missing linked records;
- reads and restarts that send and write nothing.

`tests/test_event_history.py` covers the processing history: a not-processed entry,
retrievals before records existed, simulated, paid, rejected, lost and context-only triage
with their costs, a changed entry's results kept on their own version, a capture with a mock
draft and review, captures without an origin never attributed, an unsent capture and a lost
paid send, a freeze found only through a verified record, and reads that write and request
nothing.

The browser check runs the whole flow in temporary storage: Inbox, Analyze this event,
capture, mock draft, review from the overview and back, reload, and Back, with the processing
history before and after.

```powershell
cd frontend; npm run build; npm run test:browser:overview; cd ..
```

### Treasury findings

The Treasury part of **Findings** (`/findings`) adds quantified context around retained official releases
without asking you to write a hypothesis or a note. It is a **retrospective, single-market
pilot**: daily Treasury yields from the Board's H.15 around Federal Reserve
monetary-policy releases and BLS employment and CPI releases. It is not cross-sector
discovery, not research evidence and not a measure of forecasting performance, and
nothing from it enters hypotheses, evaluations or research summaries. There is no model
and no provider: every number is computed by code, and every sentence comes from a fixed
template filled with those numbers.

**Check retained evidence** is the one action. It reads the newest accepted H.15 release
package kept under `data/market-context/` and the retained events (saved events, Event
inbox entries and the case library's cases), measures every dated occasion, and
writes only under `data/insights/` (private, never committed). It downloads, refreshes and
calls nothing. Opening the pages only reads. A newer package is used only by the next
check: a result whose exact observations, date and definitions are unchanged is reused,
and the check records the newer package beside it.

**Events.** Records of one release are joined only when publisher, canonical address and
date agree, and each keeps its link to its originating records; recurring titles stay
separate. The two saved captures of the 17 September 2025 FOMC statement therefore count
as one release with two records. Each date shows its basis: supplied when captured,
confirmed by you in the Inbox, the publisher's feed timestamp (unconfirmed metadata), or
recorded by the case library's editor (not independently verified). Entries without a
usable date, entries whose sources disagree on the date, and energy, trade and sector
entries are listed with the reason they were not measured. Releases dated the same New
York day form one **occasion** and share one measurement, because daily data cannot tell
them apart.

**Measurements.** Seven series of the package, each with its exact Board ID:

| Series | Board ID | Use |
| --- | --- | --- |
| 3-month, 2-, 5- and 10-year nominal constant maturity | `RIFLGFCM03_N.B`, `RIFLGFCY02_N.B`, `RIFLGFCY05_N.B`, `RIFLGFCY10_N.B` | yields, slope, breakevens |
| 5- and 10-year inflation-indexed constant maturity | `RIFLGFCY05_XII_N.B`, `RIFLGFCY10_XII_N.B` | real yields, breakevens |
| Discount window primary credit rate | `RIFSRP_F02_N.B` | context only |

All are percent per year, daily, as the Board published them (no vintage). Breakevens are
nominal minus inflation-indexed yield, and the 2s10s slope is the 10-year minus the
2-year yield. For an event date, W1 runs from the session before it to the first session
after it and W5 to the fifth; both include the event date's own session, so they show
everything that moved yields then and never isolate a response to the announcement. PRE
covers the five sessions before. Changes are exact, in basis points; a missing endpoint
leaves a change unavailable (no interpolation, no shifted date). Each change is ranked by
absolute size against the 250 windows of the same span that end on or before the measured
window's start: rank = (smaller + ½ × equal) ÷ eligible windows, with at least 200
eligible windows required.

**Rules.** Four exploratory rules, designed after inspecting this dataset, give twelve
checks per occasion: R1 offsetting real-yield and breakeven changes under an ordinary
nominal change; R2 one component dominating a large nominal change (both components in
bp and the dominant share stated); R3 a large 2s10s slope change; R4 a large move before
the event with an ordinary one after, or the reverse. A met check becomes a **finding**
with its observations and series IDs, the comparison, what it adds beyond the headline
and the 2-year/10-year context, an inference labelled as not observed, alternatives, and
what would strengthen or weaken it. An occasion where nothing is met says so and keeps
its numbers. Beside each finding, how often the same check is met on 200 **comparison
sessions** (a recorded seed over 2005 to 2025, excluding sessions whose windows contain an
occasion's date) describes how common the pattern is; it is not a p-value or a chance
probability. The yields are one lineage (Treasury curves republished by the Board and
FRED), so they never corroborate each other.

Every event overview shows its occasion's status in a **Treasury findings** band.
`GET /api/insights`, `/api/insights/occasions/<date>` and
`/api/insights/events/(inbox|capture)/<id>` only read; `POST /api/insights/checks` is the
check, from this origin only.

Reads verify what they show: a result is recomputed from its own stored observations
and is refused, not shown, if it differs.

The tests use SYNTHETIC packages and temporary folders (`tests/test_insight_rules.py`,
`tests/test_insights.py`): windows on sessions, weekends and holidays, exact changes,
gaps, ranks and ties, minimum coverage, every rule, event identity and date conflicts,
reuse across packages, changed observations, concurrent checks, restarts, tampered
records and reads that send and write nothing. The browser check runs the flow in
temporary storage:

```powershell
cd frontend; npm run build; npm run test:browser:findings; cd ..
```

### Industry findings (G.17)

The second part of **Findings** answers two questions from retained Federal Reserve G.17
releases (industrial production), without a hypothesis or note: which industries moved
against their parent or the total in the same reporting month, and which revisions
changed the previously reported direction for the same industry and month. It is a
separate evidence type from the Treasury findings, retrospective and descriptive; nothing
from it enters hypotheses, evaluations or research summaries.

**Evidence.** Table 1 ("Industrial Production: Market and Industry Group Summary") and
the release summary of each release kept privately under `data/sector-sources/g17/` by
the approved acquisitions (`g17-release-tables-01`, `g17-industry-tables-01`). Only
files named by those acquisitions' records are used, each with its recorded SHA-256.
Rows and columns are resolved through the tables' own `id`/`headers` attributes, never by
position. A page is refused when its G.17 identity, release date (matching its archive
folder), last-update date, heading, units ("Percent change, seasonally adjusted"), six
consecutive monthly columns marked [r] then [p], row hierarchy or values do not check out,
or when Table 1's Total IP, Manufacturing, Mining and Utilities differ from the release
summary. A blank stays missing. Table 2 is retained but not used.

**Comparisons.** Rows are identified by their full path (section and parent rows) and
NAICS code; broad Manufacturing (which includes other, non-NAICS manufacturing) and
Manufacturing (NAICS) are different rows. Values are the published seasonally adjusted
monthly rates as printed, compared with exact decimals for the same reference month.
Within one release: Manufacturing, Mining and Utilities against Total IP, and each NAICS
subsector against its durable or nondurable parent (opposing, same direction, no
direction, or not printed). A printed 0.0 has no resolvable direction and is never
treated as exactly zero. Across consecutive releases: the same row and month as a strict
reversal, a change to or from a printed 0.0, a same-direction revision or unchanged, with
the revision in percentage points. Nothing uses index levels, weights or contributions.

**Output.** Cards show what diverged or changed, both published rates with their row
path, NAICS code, column, release date and Table 1 source, what the comparison adds, an
interpretation labelled as not observed, and limitations. Divergence cards use the latest
release printing each month (ordered by month, then gap); revision cards are strict
reversals (ordered by size); totals are always shown, zero is a valid outcome, and
changes to or from a printed 0.0 are listed apart. `/findings/g17` has every comparison
and every row's estimates release by release, the sources with their hashes and the
explicit links to the three G.17 case-library cases (matched by source address).
Release dates are as published; no time zone is invented.

**Check retained G.17 releases** is the one action: local, $0, no network. Records are
written once under `data/insights/g17/` (extracts, release results keyed by extract and
definitions, revision results keyed by release pair, check records without timestamps in
their IDs), so a repeat writes nothing, a changed selection reuses every unchanged result,
and a new release adds work without touching old results. `GET /api/insights/g17` and
`/api/insights/g17/tables` verify the records by recomputing them in memory and never
write; `POST /api/insights/g17/checks` is the check.

**Manufacturing breadth.** The same check also counts, for each release and reference
month, how many of the 19 NAICS manufacturing subsectors (11 durable, 8 nondurable, by
path and code; parent rows are not counted) were printed up, down, 0.0 (no direction) or
not printed, beside the Manufacturing (NAICS) rate. Shares of the 19 and majorities (10
or more) appear only when all 19 are printed; otherwise the partial counts and coverage
are shown without them. Three comparisons stay separate: the aggregate against more than
half of the subsectors in one release and month; consecutive months within one release
(never months of different releases joined together); and the same month in consecutive
releases, with count changes and the subsectors that switched direction (strict reversals
apart from changes to or from 0.0, including switches under unchanged counts). The
G.17 section shows the latest retained release's composition with a legend and an
accessible counts table, and `/findings/g17` shows every release and revision. Breadth is
unweighted: not a contribution, a weight or the whole economy; mining, utilities and
other (non-NAICS) manufacturing are outside its universe. Its records, with their own
definitions (g17-breadth-0.1), are written once under `data/insights/g17/breadth/` and
never change an industry record; unchanged inputs are reused and reads only verify.

The tests use SYNTHETIC pages shaped like the Board's (`tests/test_g17.py`,
`tests/test_g17_breadth.py`), with all 19 subsectors:

```powershell
cd frontend; npm run build; npm run test:browser:findings-g17; cd ..
```

### Electricity by sector (EIA)

The third part of **Findings** shows differences that total electricity sales hide: in
which months retail sales to residential, commercial and industrial customers moved in
opposite directions against the same month a year earlier. It is a separate evidence type
from the Treasury and G.17 findings, retrospective and descriptive; nothing from it enters
hypotheses, evaluations or research summaries.

**Evidence.** The EIA Monthly Energy Review Table 7.6 kept privately under
`data/sector-sources/eia-mer/` by the approved acquisitions (`eia-mer-table76-01` for the
CSV and the printed table, `eia-mer-inspection-01` for the Monthly Energy Review page).
Only files named by those records are used, each with its recorded SHA-256. The CSV is
the only source of values and is refused unless it carries exactly the eight published
series (code, column order, description, unit million kilowatthours), one row per series
and date, monthly rows apart from annual totals (YYYY13), and every value a plain decimal
or "Not Available"; exponents, NaN, infinities and other tokens are refused. The table's
definitions and footnotes were transcribed from the PDF's page image and are bound to its
SHA-256, so another PDF is refused. The PDF's printed edition (September 2026) and the
page's release-date statements describe those files; the CSV states no edition and none
is assigned to it.

**Comparisons (fixed before any result was seen).** Each month from July 2025 to June
2026 against the same month a year earlier, and January–June 2026 against January–June
2025 with each sector summed over the six months first (monthly rates are never
averaged): the change in million kWh and percent, exact decimals. Up is +1% or more, down
is −1% or less (both inclusive, decided on exact values; shown percentages are truncated
toward zero so they never cross the band), anything between is little changed; a missing
value or a non-positive prior makes a comparison unavailable. A month is a finding when
one analyzed sector is up and another down, with one card per month. The 1% band is a
transparent product filter, not statistical significance, not calibrated and not proof
of materiality; zero findings is a valid result. Transportation (railway sales only) and
total retail sales are context; direct use, total end use and electric vehicle estimates
are excluded. The four sales sectors are checked against total retail sales within
0.0025 million kWh (five values, each published to 0.001); a larger residual is shown,
and contributions to the change in the total are computed only where every month
involved reconciles.

**Output.** A coverage statement (months compared, the file's range, retrieval time, and
that the last month in the file is not called current), each source with its own
provenance, a twelve-month table with each sector's change and class and a one-axis
picture, a card per diverging month and for January–June when it diverges, the
January–June table, the reconciliation and the method with the table's footnotes. Every
card states its observations, what it adds to the total, an interpretation labelled as
not observed, contributions with the rounding residual, and six disclosures: retail sales,
not total consumption; not weather- or calendar-adjusted; no price normalization or
inference about output; preliminary status not marked; a single acquisition, not a
revision history; no cause established.

**Compute from retained files** is the one action: local, $0, no API call and no network.
The result is written once under `data/insights/electricity/results/`, keyed by the
source hashes (through the extract), the extract, rules and result versions, the
definitions and the fixed scope; an unchanged repeat reuses it, and a result under another
version, scope or source is kept but not shown. `GET /api/insights/electricity` validates
the sources and recomputes the result in memory, showing it only when the stored result is
exactly that; it never writes. `POST /api/insights/electricity/checks` is the action.

The tests use SYNTHETIC files shaped like the retained ones (`tests/test_electricity.py`,
`tests/electricity_fakes.py`); the served view is captured into
`frontend/tests/fixtures/electricity-view.json` for the client's tests:

```powershell
cd frontend; npm run build; npm run test:browser:findings-electricity; cd ..
```

### Cross-source comparisons (G.17 and EIA)

A last part of **Findings** sets the two retained sources side by side for the same
periods. They are descriptive comparisons, not transmission findings: nothing here says
one series explains the other.

- **Industrial electricity retail sales and manufacturing output**: EIA Table 7.6's
  industrial class (ESICPUS) beside G.17 Table 1's Manufacturing (NAICS 31-33).
- **Electric utility output and the customer breakdown of electricity retail sales**:
  G.17's Utilities / Electric (NAICS 2211) beside EIA total retail sales and its four
  customer classes.

**Periods.** The fourth quarters of 2023, 2024 and 2025 against the previous fourth
quarter, and each 12-month period a retained G.17 release prints. On the EIA side a
fourth quarter is the October–December total (all three months needed in both years); a
12-month period compares that month with the same month a year earlier. A period the
retained EIA file does not reach is shown as not covered, and no other month is used in
its place. G.17 values come from Table 1's "Fourth quarter to fourth quarter" and 12-month
columns, read through the table's own header structure (`g17_columns.py`, its own version;
the industry findings' extracts and IDs are unchanged): the latest retained release that
prints a fourth quarter, with every release's value beside it, and for a 12-month period
the release whose 12-month column is exactly that month, with its preliminary marker.

**Signs.** "Same sign", "opposite signs" or "no direction" describe only whether each
reported change is above or below zero, with no threshold; they are not the ±1% categories
of Electricity by sector, and a G.17 rate printed as 0.0 has no direction. No growth rates
are subtracted or combined. The customer breakdown decomposes EIA total retail sales only
(four classes plus the rounding residual, when every month reconciles); it does not show
what drove G.17 utility output.

**Not the same measurement.** Retail purchases are not total consumption; an output index
is not kilowatthours; G.17 is seasonally adjusted and the EIA sales are not; the EIA
industrial class is not NAICS manufacturing; the vintages differ. Whether the Federal
Reserve's measures draw on EIA data is not stated in the retained material, so agreement is
not treated as corroboration. Table 7.6's direct use is one aggregate and cannot show
industrial self-generation. Industry mix, weather, irrigation and self-generation are listed
as possibilities these observations do not establish.

**Compute from retained files** is the one action: local, $0, no API call. The result is
written once under `data/insights/cross-source/results/`, keyed by both sources' extract
IDs, the versions, definitions and scope; an unchanged repeat reuses it, and reads
recompute it in memory and never write. `GET /api/insights/cross-source` reads;
`POST /api/insights/cross-source/checks` is the action. Tested with synthetic pages and
files (`tests/test_cross_source.py`); the served view is captured into
`frontend/tests/fixtures/cross-source-view.json`:

```powershell
cd frontend; npm run build; npm run test:browser:findings-cross-source; cd ..
```

### Related cases (historical announcements)

Related cases helps move from an event to relevant historical cases. It is research
navigation: not a prediction, a trading signal or a score.

**Two historical cases** are listed in the **Case library** under "Historical policy
announcements", each with its own page at `/library/historical/:id`:

- Treasury's 28 January 2019 sanctions on PdVSA, Venezuela's state-owned oil company
  (designation under E.O. 13850, blocking, concurrent general licenses, a stated condition
  for relief);
- Commerce/BIS's 7 October 2022 export controls on advanced computing and semiconductor
  manufacturing items for the PRC (items, end uses, foreign-produced items, U.S. persons,
  licensing policy, a temporary general license, effective dates of 7, 12 and 21 October).

Each was written only from one official press release retained privately under the approved
acquisition `related-cases-sources-01`. A case keeps **source facts** (each quoting the
page verbatim), **interpretation** (labelled, AI-assisted, without figures) and **review
status** (AI-assisted, not reviewed by a person, excluded from research use, historical:
not current law or policy) apart. Announcement, action, effective, publication and deadline
dates are separate, date-only, and unknown where the release does not state them. Linked
rule texts and general licenses were not acquired, so their terms stay unknown. The content
is committed under `content/related-cases/`; the retained pages stay private (git-ignored,
never served). When a page is present on the machine, a case page checks it: size and
SHA-256, every quoted passage within one text block, and the acquisition record. Every
number a fact states must appear in the quotes it cites.

Coverage is a first version, not broad: tariffs and trade, competition and regulation, and
labor disruptions have no case yet, because their planned official pages were not
retained (an access-check redirect, a bot-verification page and an HTTP 403). The case
library says so.

**On an event's overview** (`/events/inbox/:id`, `/events/capture/:id`), the "Related
historical cases" section compares the event's own text (an Inbox entry's title and feed
excerpt; a capture's headline, supplied text and source address) with the cases' tags by
a fixed word list: policy instrument, sector, country and issuing agency. A case is shown
as related only when the event names its instrument and also its sector or country; a
shared topic alone (such as oil) is listed as "checked, not related". Each related case
says why it matches (the terms and where they were found), what differs (only from what the
event names), what is unknown, and which of the case's points the check did not compare.
An accepted paid headline classification of that exact entry version may add terms, always
marked as a hint; simulated triage results are never used. No match is a normal result.

**Find related historical cases** is the one action: local, $0, no model, network or
embedding. The result is written once under `data/related-cases/matches/`, keyed by the
event's identity and content fingerprint, the hint used, the case content digest and the
rule versions (never retrieval time or page state); a repeat reuses it, a restart reads it,
and a changed entry, hint, case or rule needs a new check while earlier records are kept.
Headline-triage records are only read. `GET /api/related-cases`, `GET
/api/related-cases/:id` and `GET /api/related-cases/events/:kind/:id` read;
`POST /api/related-cases/events/:kind/:id/matches` with `{"find_related_cases": true}` is
the action. Tested with synthetic events (`tests/test_related_cases.py`; the served views
are captured into `frontend/tests/fixtures/related-*.json`); the committed cases are
checked against the retained pages only on explicit opt-in:

```powershell
$env:SECOND_ORDER_RELATED_SOURCES = "data\sector-sources\related-cases"
python -m unittest discover -s tests -p test_related_cases.py
cd frontend; npm run build; npm run test:browser:related-cases; cd ..
```

### Related research (event overview)

Below **Related historical cases**, an event's overview has a compact **Related research** section: links to cases
already in the Case library, each labelled with how it relates, one explanation, the date and document differences,
and what kind of content it is (an editorial, AI-assisted case not reviewed by a person and not research evidence, or a
historical case with its source-check state, and when it was written: always after the fact). It is navigation, kept
apart from the strict historical matching above: not a comparison of mechanisms, a prediction or evidence of cause.

- **Coverage of this event**: the event's address names one document (an article or release page, its query kept;
  never a landing page or a page reused for every release), exactly one case cites it, and every event holding that
  address states the case's publication date. Headlines never identify an event; a conflicting or missing date
  prevents the label, and that case is then not offered under a weaker label either.
- **Same release family**: the event's own title and its address place it in a named family (FOMC statements, minutes
  and projections; the Employment Situation; CPI; G.17; H.8), linked to the latest case of that family published on or
  before the event's date, with the document type and the time between them. A shared publisher is not a family.
- **Related research topic**: a small vocabulary of concrete subjects tied to existing cases (US natural gas prices,
  production and storage; who produces US crude oil and natural gas; electricity used by electric vehicles; trade and
  environment work at the WTO). Every term group must appear in the event's own text, and in the case's own title or
  summary. The WTO topic links the co-sponsor initiatives' news (TESSD, the plastics dialogue) to the Committee on
  Trade and Environment entry and says that the forums differ.

Family and topic links go only to cases published on or before the event's date; an undated event gets neither. At
most four links, strongest first, each case once; a case already shown as related in the historical section is not
repeated. Saved headline classifications are not used. "No related research" is a normal result. The links are
selected on each read from local records: nothing is stored, fetched or sent. `GET
/api/related-research/events/:kind/:id`; there is no write route. Tested with synthetic events
(`tests/test_related_research.py`; served views captured into `frontend/tests/fixtures/related-research-*.json`):

```powershell
cd frontend; npm run build; npm run test:browser:related-research; cd ..
```

### Semiconductor policy evolution (research view)

The Case library lists a research view at `/library/research/semiconductor-policy`. It
compares ten BIS press releases on advanced chips and chip-making equipment, from October
2022 to February 2026, as read from the retained BIS snapshot. It is a retrospective
comparison of selected retained publications: not a complete or current policy monitor,
not legal or compliance guidance, and not evidence of effects. Ten releases by one
publisher are one account, not independent corroboration.

The selection: the October 2022 rules; the October 2023 updates; the April 2024
clarifications; the September 2024 data-center Validated End User (VEU) program; the
December 2024 equipment, design-software and memory package; the January 2025 framework
for advanced chips and AI model weights; the May 2025 announced rescission of that
framework; the August 2025 end of VEU authorizations for foreign-owned fabs in China; the
January 2026 license-review revision for certain chips to China; and the February 2026
Applied Materials penalty. Records the snapshot's keyword filter matched but that were left
out are listed with their reasons (some are not semiconductor-policy publications at all).

Each release is described in seven dimensions: instrument, stated relation to earlier
publications, technology or product scope, jurisdictions/actors/end uses, supply-chain
stages, dates and conditions. Every statement is labelled: **publisher statement** (quoted,
with its paragraph), **curator interpretation** (the stage an item belongs to is always
this), **not stated in this source** (about the retained text only) or **in a linked
document not retained**. Listing times, CMS times, release datelines and dates the text
states stay separate, each with its precision; a dateline is shown only from a separately
retained release page that verifies (two releases have one). The January 2026 date
discrepancy (case note January 14; listing 2026-01-13 23:00 UTC; CMS creation January 14)
stays unresolved.

Seven comparisons each name the releases compared, the supported observation, the quoted
evidence with paragraph locators, why the distinction helps (interpretation) and what
remains unknown, with the evidence that would settle more. They make these distinctions
easier to see: a change the later release itself states (October 2023 against October
2022); a clarification set beside new controls (April 2024); an announced rescission
against a published one (May 2025); a case-by-case policy (January 2026) that is not shown
to reverse the earlier presumption of denial, because the item sets are not shown to be the
same; one program name for two subjects (data-center and fab VEUs); an enforcement case
about 2021–2022 shipments against later equipment controls (ion implanters); and which date
belongs to which field.

The content is committed under `content/research/semiconductor-policy/research.json`
(policy-research-0.1) and never regenerated. Each read verifies the retained snapshot
against its acquisition record and every quoted passage against its record, in memory: a
missing source makes the affected comparisons **unavailable**, a changed one makes them
**need revalidation**, and either way their observations and evidence are withheld.
Nothing is written, fetched or sent; `GET /api/research` and `GET /api/research/:id` are the
only routes. Tested with synthetic sources (`tests/test_policy_research.py`; served views
captured into `frontend/tests/fixtures/policy-research-*.json`); the committed file is checked
against the retained sources only on explicit opt-in:

```powershell
$env:SECOND_ORDER_POLICY_RESEARCH_SOURCES = "data\sector-sources"
python -m unittest discover -s tests -p test_policy_research.py
cd frontend; npm run build; npm run test:browser:policy-research; cd ..
```

### Copper thesis (physical balance, status and exposure)

The Case library lists a thesis at `/theses/copper`; each version also has its own address,
`/theses/copper/versions/:n`. A thesis is a stated research view on one topic, kept in
versions: the view, the balance in numbers, where it differs from what others publish, the
reasons it rests on and the risks to it (each with a status), what would change it, who is
exposed, a dated log, a price record, a plain-language note under each heading and the
claims it does not make. Version 1 was published on 2026-11-03. It reads copper's physical
supply and demand from retained IEA, USGS, World Bank and company sources. It is not a view
on the price, not a monitor of current markets and not evidence of effects.

Claims not made:

- no price target, price forecast or trading signal;
- no recommendation to buy or sell any company, security or commodity;
- no claim that the balance will cause any change in the copper price.

The view, in short (the author's reading of the IEA Critical Minerals Dataset 2026): under
Stated Policies, demand grows from 2030 to 2035 while the dataset's base case for mine
supply falls, and base-case refined supply stays above demand, so the constraint the dataset
shows is at the mine, not the refinery. Five reasons (electricity networks, electric
vehicles, the counted mine pipeline, Southern Copper's production plans and world mine
output) and four risks (aluminium substitution, more recycling, slower building in China,
and demand outside energy technologies) each state a status; every reason, and every risk
with a retained measure, compares a latest figure with a previous one. Two conditions name
the later IEA figures that would change the view. Freeport-McMoRan, Southern Copper, Mueller
Industries and Tesla appear under exposure, each as its own annual report states it.

The "Who is exposed" section opens with an exposure map, ahead of its two tables, which are
unchanged. Each company the thesis moves has a lane that starts from a change in the copper
price, whatever its cause, and keeps the places it can reach apart: a producer's revenue,
margin and operating cash flow; a user's input cost, its own selling prices, margin and
operating cash flow. Under them is what the company's filing states, with its status and the
figures and passages to open. A company that moves a reason is linked to it as the reason's
measure when it cites the reason's latest measured figure (Southern Copper's guidance in
version 1), and as related otherwise (Freeport-McMoRan, Tesla): one company's result is not
a market measure. Short notes explain incidence, pass-through and operating exposure, and a
legend names the three kinds of line (stated in a source, conditional mechanism, not
measured). The map computes nothing and places no figure on a stage, because the thesis does
not say where a figure sits in a company's accounts; a withheld part shows only its frame.
See `docs/copper-exposure-map.md`.

How a status is read: a reason is **strengthening** when its latest figure differs from the
previous one by at least the material change (5% for every measure in version 1, in percent
of the previous figure) in the direction the reason needs, **weakening** when it differs by
at least that much the other way, and **unchanged** when the change is smaller in either
direction. A risk reads **materialising**, **receding** or **unchanged** the same way; a risk
with no retained measure is **not tracked**. A condition has **happened** only when its
figure is past the threshold; a figure equal to it has not. The page says which comparison
each status makes: two years within one edition of a publication, or two editions. It shows
the change rounded to one decimal, while the status is read from the exact figures. In
version 1, four reasons read strengthening and world mine output unchanged; recycling reads
materialising, demand outside energy technologies unchanged, and the other two risks are not
tracked; neither condition has happened.

Version 1 states its limits. No balance table computes a surplus or deficit: the IEA table
sets demand per scenario beside one base case for supply, with no figure for recycled
supply, and the United States table is one importing country's context, met by trade and
stocks. No copper cost per electric vehicle is computed. Four IEA comparisons (three reasons
and the risk on demand outside energy technologies) compare projection years within one
edition, so their statuses show the shape of one projection. The 5% material change was set
after the figures were read, and two statuses sit near it: Southern Copper's -5.6% reads
strengthening, just past it, and demand outside energy technologies, +2.7%, would read
receding at half of it. Figures and passages from a PDF were transcribed from its text
layer. The price record is one USGS annual average for 2025 (490 US cents per pound, an
estimate), shown as a record beside the view and not as evidence that it is right.

The content is committed under `content/theses/copper/` (`index.json` and `v1.json`,
thesis-0.1) and never regenerated: a new version is a new file, and its log keeps every
earlier entry. Each read checks every retained file against its acquisition record
(attempt, address, retrieval time, size and SHA-256), then looks for each figure and passage
where it is cited: a paragraph of a filing, a cell of the IEA workbook or a row of the USGS
data release. Figures and passages from a PDF (the USGS chapters and the World Bank outlook
page) are bound to the PDF by its SHA-256 only. A missing source makes the parts that use it
**unavailable**; a changed source, or a figure not found where cited, makes them **need
revalidation**; either way their text, figures and statuses, and a condition's threshold, are
withheld and the problems are listed. Nothing is written, fetched or sent; `GET /api/theses`,
`GET /api/theses/:id` and `GET /api/theses/:id/versions/:n` are the only routes.

The sources come from six approvals, retained under `data/sector-sources/copper/` (local,
not committed): `copper-worldbank-01`, `copper-usgs-01`, `copper-iea-2021-01` and
`copper-sec-01` (14 single GETs; the eight SEC requests declared a contact, which the records
note only as declared), and `copper-usgs-csv-01` and `copper-iea-dataset-01` (three files
the owner downloaded, the USGS ones recorded only on a size and MD5 match with their
published records). Version 1 cites 13 of the 17 retained files. It does not cite the World
Bank's monthly copper series (third-party data that, under the World Bank's terms, may not be
reused without its provider's consent), the terms page read for that decision, the IEA's 2021
report (all rights reserved) or the USGS 2025 data file (no measure needs it). See
`docs/copper-thesis-sources.md` for the terms read and each decision.

Tested with synthetic sources and two synthetic versions (`tests/test_thesis_*.py`,
`tests/thesis_fakes.py`; served replies captured into `frontend/tests/fixtures/thesis-*.json`);
`npm run test:browser:thesis` checks the page. The committed thesis is checked against the
retained sources only on explicit opt-in. The opt-in test also checks each USGS data-release
figure against its row's country, statistic, year, unit and estimate note, and each IEA
figure against its column's year and scenario. Set an absolute path, because the browser
check resolves the folder from `frontend`:

```powershell
$env:SECOND_ORDER_THESIS_SOURCES = (Resolve-Path "data\sector-sources\copper").Path
python -m unittest discover -s tests -p test_thesis_api.py
cd frontend; npm run build; npm run test:browser:thesis; cd ..
Remove-Item Env:SECOND_ORDER_THESIS_SOURCES
```

### Evidence-first research analysis (saved events)

A second analysis mode for a saved event, beside the market-hypothesis draft. After an
event is captured in **Analyze an event**, its preview offers an explicit **Analysis mode**:
the market-hypothesis draft (the saved request, unchanged and still the default) or the
evidence-first research analysis, which has its own page at `/events/capture/:id/research`
(also linked from the event overview). Opening it prepares and sends nothing.

The research request asks for what the source establishes, each statement supported by
exact quotes; one separately labelled interpretation, or **no additional finding** (an
acceptable result); its assumptions and competing explanations; missing information; and
checks that would test it. It asks for no direction, horizon, forecast, trade or observable.
A publisher's forecast stays the publisher's attributed forecast. No earlier baseline
publication is supplied, so no comparison with one is made, and the analysis is
retrospective, not an out-of-sample test.

Each part has its own versioned contract; nothing reinterprets a hypothesis draft:

- **Request** (research-request-0.1; claude-sonnet-5-5, effort medium, max_tokens 16,000;
  prompt research-prompt-2 since 2026-10-26: the analysis is the response itself in the JSON
  output format, with no tool; research-prompt-1, whose strict tool `submit_research_analysis`
  carried it, is kept so its records read as before): prepared
  once per capture under `data/research-analyses/requests/`, read-only and never overwritten.
  It is bound to the capture's own request and source hashes and to its recorded Inbox origin
  (the origin record's SHA-256 and entry version), all checked again on every read. The
  capture and its saved hypothesis request are only read.
- **Result** (research-result-view-0.1): built on every read from the attempt's saved files.
  Every quote must be found in the captured text (exactly, or after making quotation marks,
  dashes and spaces plain); its paragraph and character locators are computed by code, and
  the page shows the source's own wording with the quoted passages marked in the captured
  text. A reply with any quote that is not there is refused as a whole.
- **Review** (research-review-0.1): append-only versions bound to the result shown.

Sending keeps the Tracker's safeguards: the planning estimate with this mode's output-limit
assumption (not a billing ceiling), an explicit approval naming the request's SHA-256 (for a
paid send also the estimate, on a server started with `--enable-paid-drafts`), one exclusive
reservation per request in either mode, the exact saved bytes posted once with no retry or
fallback, and no freeze or evaluation. The local mock ($0) records synthetic content labelled
as such. The event overview's processing history lists research requests, results and
reviews apart from drafts.

Automated tests use only fake transports and synthetic records:
`tests/test_research_analysis.py` (served payloads captured into
`frontend/tests/fixtures/research-analysis-*.json`), `tests/test_research_format_contract.py`
and `tests/test_research_reply_contract.py` (the two prompt versions' requests and replies),
`frontend/tests/researchAnalysis.test.ts` and the browser check below; simulated replies
verify the workflow, not the quality of an analysis. Separately, one approved retrospective
pilot on a single saved event has sent a real research request through this path, once with
no retry, and recorded the response and a human review. The reply was accepted as an
analysis, which means it met the contract (structure, and every quote found in the captured
text); the review asks for revision. This is not evidence of general model quality,
forecasting performance, mechanism confirmation or verified billing.

```powershell
python -m unittest discover -s tests -p test_research_analysis.py
cd frontend; npm run build; npm run test:browser:research-analysis; cd ..
```

### Market-implied rate path (saved FOMC statements)

For a saved Federal Reserve monetary-policy statement, the event overview and the research
page show a compact **Market-implied rate path** panel: the first four three-month SOFR
reference windows that the Atlanta Fed's Market Probability Tracker lists on the last
observation date before the statement, each with mean average SOFR and the 25th–75th
percentile range, read from its historical-data workbook (estimated from CME 3-month SOFR
options). Pricing for the meeting's own decision is shown as unavailable: the workbook has
none. Window dates are not meeting dates, average SOFR is not the target rate, the workbook's
cut and hike probabilities are neither kept nor shown, and nothing is compared with the
decision.

The workbook is used only as a file the operator already holds; nothing here downloads it.
Two explicit local commands write private records under `data/rate-context/`; opening a page
never does:

```powershell
python -m second_order rate-context retain --workbook <path> --sha256 <expected> --obtained-on <YYYY-MM-DD> --method "<how it was obtained>"
python -m second_order rate-context prepare --capture <capture ID>
python -m second_order rate-context show --capture <capture ID>   # what the pages read; read-only
```

`retain` keeps the exact bytes only after they match the SHA-256 you name and pass the reader
(the license statement, the dictionary's definitions, every DATA row), with an acquisition
record that leaves the HTTP status, headers and publication time unknown. `prepare` binds one
capture, its recorded Inbox origin and the workbook; run again, it re-derives the record and
compares. The observation is the latest one strictly before the statement's New York
publication date; one dated that day is never used, since the workbook's dates carry no time
of day. The context is a separate record: no model request carries it, and the research page
says so. Limits: historical estimates obtained after the event, with no time of day,
publication time or vintage; the workbook's license permits personal and educational use only.

Verified with synthetic workbooks (`tests/rate_fakes.py`): `tests/test_rate_context.py`
(served payloads captured into `frontend/tests/fixtures/rate-path-*.json`),
`frontend/tests/ratePath.test.ts` and the browser check below.

```powershell
python -m unittest discover -s tests -p test_rate_context.py
cd frontend; npm run build; npm run test:browser:rate-path; cd ..
```

### Metals page (production, reserves and research layer)

The Metals page at `/metals` (admin build; reached from the case library's copper entry and the copper thesis) compares
the 45 chapters of the USGS Mineral Commodity Summaries 2026 data release and, kept apart, the IEA Critical Minerals
Dataset 2026: where each metal is mined and refined, who holds the known reserves, how concentrated both are (the
largest named country, the three largest and the HHI as two bounds with its coverage), US import reliance, the IEA's
energy-technology demand, and assistant-written transmission chains whose links are labelled measured, stated by a
source or hypothesis. Both files are verified against their acquisition records on every read; a file that fails is
withheld with its reason, and nothing is fetched, estimated or sent to a model. Events come only from dated passages of
retained reports, each dated as its quote dates it. The details are in `docs/metals-comparison.md`.

```powershell
python -m unittest discover -s tests -p "test_metals_*.py"
cd frontend; npm run build; npm run test:browser:metals; cd ..
```

The real files are checked only on request and read-only: set `SECOND_ORDER_THESIS_SOURCES` to the retained
`data/sector-sources/copper` folder before the same commands.

### Copper event chains (past events, mechanisms and the owner's readings)

The page at `/theses/copper/events` (admin build) shows three chains from a retained event to a reason or risk of the
copper thesis. The assistant writes chains and mechanisms as content in the working session; the app reads them and
writes only `data/event-chains/reviews/<chain>/` and `data/event-chains/readings/<chain>/`. A chain version's evidence is
filled by one command, which copies the live records it rests on and adds the version to the chain's index:

```powershell
python -m second_order event-chains pin --chain <chain id> --version <N, the next after the index> --published-on <YYYY-MM-DD>
```

The command refuses a version already in the index, and the date is the publication date. The retained sources are
optional for the default tests; the real folders are checked only on request and read-only, with
`SECOND_ORDER_THESIS_SOURCES` set to the retained `data/sector-sources/copper` folder and `SECOND_ORDER_FCX_SOURCES` set
to the retained `data/company-sources/fcx` folder:

```powershell
python -m unittest discover -s tests -p "test_event_chain_*.py"
cd frontend; npm test; npm run build; npm run test:browser:copper-events; cd ..
```

The browser check starts `tests/review_browser_server.py --copper-events synthetic` (with `--company-fcx synthetic` and
`--metals synthetic`), which writes a SYNTHETIC world of one chain below its temporary root; the check reviews,
approves and records a reading, edits one cited record, flips one byte of a retained file, restores both, and uses the
keyboard and phone width. Do not run it at the same time as the unit tests in one clone. Details are in `SPEC.md`
("Event chains (copper thesis)").

### Copper research (the desk, publication comparisons and the owner's notes)

The copper desk at `/copper` (admin build, "Copper" in the top bar) links the five copper pages, lists the publication
comparisons and holds the owner's research notes; `/copper/comparisons/<id>` shows one comparison. The assistant writes
a comparison as content in the working session, with `"evidence": null`; one command copies the publications, passages
and acquisition records it rests on and adds the version to the comparison's index:

```powershell
python -m second_order comparisons pin --comparison <comparison id> --version <N, the next after the index> --published-on <YYYY-MM-DD>
```

The command refuses a version already in the index and a row whose line is not a passage of the publication it is filed
under. A row never holds a change between its two lines; the loader refuses any such field. The app writes only the
owner's notes, one file each, under `data/research-notes/copper/`. Run the commands below one after the other; the real
FCX folder is checked only on request and read-only, with `SECOND_ORDER_FCX_SOURCES` set to the retained
`data/company-sources/fcx` folder:

```powershell
python -m unittest discover -s tests -p "test_publication_comparison.py"
python -m unittest discover -s tests -p "test_research_notes.py"
python -m unittest discover -s tests -p "test_copper_research_api.py"
cd frontend; npm test; npm run build; npm run test:browser:copper-desk; cd ..
```

The browser check uses the same SYNTHETIC world as the event chains check (`--copper-events synthetic`), which now also
holds one comparison; notes go to `research-notes/` below the check's temporary root. The frontend fixtures
`copper-research-*.json` are captured from the routes: regenerate them with
`SECOND_ORDER_WRITE_FRONTEND_FIXTURES=1 python -m unittest discover -s tests -p test_copper_research_api.py`. Details are
in `SPEC.md` ("Copper research").

### Fuels page (reference, personal use)

The Fuels page at `/fuels` (admin build, between Market context and Library) shows Brent, New York Harbor gasoline and
diesel spot prices from the U.S. Energy Information Administration (EIA), a barrel drawn to scale from zero with the
computed 3-2-1 crack (before refining costs),
WTI and Henry Hub, a short "situation now" note written from public agency material, and a log of snapshots. It is a
reference page for personal and educational use, not for redistribution. The crack is computed and labelled so; it is
not a refinery's profit and not a research observable.

Prices enter only through one explicit command, which the owner runs. It needs an EIA API key (a free key from
https://www.eia.gov/opendata/register.php), requests the five daily spot series from EIA's open data API (about 400
days of each, paged until EIA's stated row count is reached) and writes one snapshot. The key is never written to a
file, a snapshot, a report or an error: EIA echoes it in each reply, and the refresh drops it before anything is kept.

Store the key once in Windows Credential Manager (through the `keyring` package in `requirements.txt`); every refresh
then reads it from there. `fuels key set` asks for it twice at a hidden prompt, so it is never on a command line, in
PowerShell's history or on screen. It runs only in a real terminal window; never paste the key into a chat. Saving
the key requests nothing and does not refresh:

```powershell
python -m second_order fuels key set
python -m second_order fuels refresh
python -m second_order fuels status
```

`fuels key status` says only whether a key is stored and whether `EIA_API_KEY` is set, never the key.
`fuels key replace` stores a new key in place of the old one and `fuels key delete` removes it. The entry is named
"second-order-v2 EIA API key" and belongs to the Windows user, so every checkout and worktree on this account reads
the same key. The server, the page and the snapshots never read it. Only Windows Credential Manager is used: if
keyring points to any other store, the key commands, and a refresh without `EIA_API_KEY`, refuse it before touching
it. `EIA_API_KEY` still works and, when set, is used instead of the stored key (the refresh then never reads the
store); the refresh report's `key_from` names which one was used, never the key:

```powershell
$env:EIA_API_KEY = Read-Host "EIA API key"
python -m second_order fuels refresh
Remove-Item Env:EIA_API_KEY
```

The refresh prints, per series, `stored` or `refused` with the reason (for example, units that differ from the
committed record, or a reply that did not come back whole), and never a price. EIA's API gives no publication date,
so the page shows "publication date not given by EIA" rather than guessing one. Until 0.5.39 the page read FRED;
FRED's API terms bar storing or archiving its content, which these snapshots do, so the page now reads EIA, the
original publisher. A FRED snapshot left on a machine is kept and listed, and its prices are withheld.

`fuels status` reads the local snapshots and notes and prints states, dates and counts, never a price value. Neither
command prints a price. Snapshots live in `data/fuels/snapshots/` as write-once files named by their SHA-256; `data/` is
gitignored, so snapshots are never committed. The page reads them and never fetches. Notes are committed under
`content/fuels/notes/` (the procedure is in `docs/fuels-situation-note.md`). Tests use only synthetic values. Since
0.5.41 a note can be an analysis (fuels-note-0.2): a visible summary, then what happened, what it may mean, who it may
touch and what to check next behind one button ("Read the analysis"), opening under the summary and the barrel,
every figure and date filled from the snapshot it was written for. A
Claude session drafts it from the verified EIA snapshot; it never reads the key (from `EIA_API_KEY` or Credential
Manager), runs `fuels key` or a refresh, or opens a FRED-era snapshot, and it marks its notes "Claude
(AI-drafted)", unreviewed.

Three more sections sit below the barrel. Situation Now compares the latest day on which Brent, gasoline and diesel all
have a value with the previous one and with about a week and a month earlier, and splits the basket's change into a
Brent part and a crack part (an accounting identity, not a cause). Market Drivers and Economic Transmission are general
economic mechanisms written conditionally, committed in `content/fuels/drivers.json` and
`content/fuels/transmission.json`; they hold no figures and no attribution or forecast phrasing, a file that breaks
those rules makes the page show an error, and no current events are connected yet. The prose is AI-drafted and
unreviewed. It is reviewed and revised in place: to mark a file reviewed, read it, set `review.state` to `reviewed` and
`review.reviewed_on` to the day (on or after `prepared_on`), set `author` to `Owner` if you rewrote it, and commit. Git
history is the version record for this prose; the rule that new versions append governs frozen research inputs, not
explanatory content. Writing conditionally is a drafting rule checked in review; the loader does not enforce it.

A verified price more than ten days older than the newest price on the page stays, with its own date and a line
saying how far behind it is; what is computed from it (the barrel, the crack and Situation now, for Brent, gasoline or
diesel) is withheld, since prices from different dates are never combined. A change too small for its last shown place
shows its direction and `<` that place (for example `−<0.01`); `0.00` is only a true zero.

Snapshots are per checkout, and a note binds only where its snapshot file is present. When working from a worktree, run
`fuels refresh` and `fuels status` with `--snapshots <main checkout>/data/fuels/snapshots` (the
main checkout's folder), and start a worktree's server with `serve --fuels-snapshots` and that folder; otherwise the
snapshot is lost when the worktree is removed. A snapshot file can also be copied between checkouts as is: its name is
its hash, so a copy verifies itself.

```powershell
python -m unittest discover -s tests -p "test_fuels_*.py"
cd frontend; npm run build; npm run test:browser:fuels; cd ..
```

## What is implemented

- Immutable Pydantic hypotheses, a closed observable registry and strict JSON parsing.
  Every leg must state `headline_reports_move`; there is no default.
- A versioned copper thesis: the physical balance from retained sources, reasons and risks
  whose statuses are computed on every read, exposure from company filings, and parts
  withheld when a source is missing or changed (see **Copper thesis (physical balance,
  status and exposure)**).
- A source-grounded research view comparing ten retained BIS semiconductor-policy releases:
  labelled publisher statements, curator interpretation and unknowns, quoted passages
  checked against the retained sources on every read, and comparisons withheld when a
  source is missing or changed (see **Semiconductor policy evolution (research view)**).
- Regular-session equity anchors: the last close before an out-of-session freeze,
  or the first close after an in-session freeze. This is close-to-close
  regular-session measurement; extended-hours trading may already have reacted.
  Futures and other instruments use the first observation after the freeze, and
  replays use an explicit publication-time anchor.
- Event reference windows end at the pre-publication event anchor, so the
  initial reaction never enters the ordinary comparison history.
- Signed percentile scoring, ties, availability and elapsed-horizon checks.
- A new alpha/beta market model, fitted on 250 returns ending 10 observations
  before the event anchor however late the freeze; equities use cumulative daily
  abnormal returns, and each equity record keeps its fitted window and parameters.
- Fifty deterministic historical placebo dates, each with its own trailing baseline.
- Append-only SQLite hypotheses and evaluation records.
- An explicit CLI, full-suite CI definition and two sourced offline showcases.
- Prepared Dossier views, a local FastAPI layer and a React/TypeScript Dossier.
- An offline Claude drafting adapter with strict validation, tested on mocked transports.
- A Tracker path from an entered event to human review: the exact saved request, a $0
  local mock by default, and one explicitly approved paid request on a server started
  for it, tested only against a simulated provider.
- A case library of twenty-seven retrospective, AI-assisted editorial case studies:
  twelve 2025 macro releases (four FOMC statements, four jobs reports, four CPI reports),
  twelve 2026 sector releases (three each from EIA Today in Energy, BIS export-control press
  releases, the Federal Reserve's G.17 and its H.8) under five sectors, and three 2026 WTO
  news items written from privately retained copies (a trade forecast and two meetings), with search, topic and sector filters, strictly validated, read-only and
  excluded from every research summary. Two BIS cases carry a source check and reading aid
  bound to the unchanged case file, with two claims flagged where the retained sources differ.
- Descriptive market context for all twelve macro cases: the Board's daily H.15 2-year and
  10-year Treasury yields around each publication date, from a committed bundle of
  downloaded source files in two separately recorded acquisition runs, verified on
  every read.
- An Event inbox of five fixed publisher feeds: the Federal Reserve's monetary-policy
  releases, the BLS Employment Situation and CPI releases, EIA's Today in Energy articles
  and WTO news. It is refreshed only by an explicit local action into a local cache,
  read-only otherwise, filterable by topic and source, and able to start the Analyze an
  event form. It is tested with simulated feeds. The release feeds were also tested
  against the real feeds once; the energy and trade feeds had one preflight request each
  (see **Event inbox**).
- Headline triage of up to 25 selected inbox entries, current or retained: categories,
  short summaries and conservative "possibly the same event" suggestions. Saved per-entry
  results are reused, and only missing work goes into at most one explicitly approved
  Claude Haiku 5.5 request (a $0 local simulation by default; paid only on a server
  started for it). Every entry and source is kept. Tested only against simulated
  responses (see **Headline triage**).
- A local archive of every inbox entry version retrieved by a refresh, so headlines stay
  available after they leave their feeds, with a write-once retrieval record of every feed
  request (status, headers and cache validators, body completeness and SHA-256, parser
  version, item provenance and new, unchanged, changed and refused counts) and each accepted
  response kept as received (see **Event inbox**).
- My analyses: a private, local, searchable library of the Tracker's published analyses
  with their outcome, response mode and review status bound to the current view, read
  only through the verified readers (see **My analyses**).
- Private market context for selected Federal Reserve and BLS events: the Board's daily
  2-year and 10-year yields around a confirmed or supplied New York date, with
  descriptive basis-point changes. Observations are reused from the committed bundle and
  from private retrievals, and missing data comes only through one explicitly approved
  request on a server started for it. Tested only against a synthetic Board server (see
  **Market context for selected events**).
- Interface freezes (Hypotheses): a manual hypothesis or a reviewed H.15 model draft,
  an explicit local baseline import, a write-free preview bound by its SHA-256, one
  explicit approval stamped by the server and stored atomically and idempotently,
  freshness policy B for every new freeze, and read-only reopening. Tested only with
  synthetic data and a fake provider (see **Freezing from the interface**).
- Interface assessments (Hypotheses): outcome readiness with its states kept apart, an
  explicit outcome import, one approved download of the release package for selected
  hypotheses, a write-free preview with a cutoff the server derives from the inputs, one
  explicit "Evaluate and prepare Dossier" approval recorded atomically and idempotently
  (reassessments append), one prepared Dossier per assessment, the lifecycle journal, and
  freeze links on drafts. Tested only with synthetic data and fake transports (see
  **Assessing from the interface**).
- A private event overview of one Inbox entry or saved event: a processing history from
  retrieval to triage, analysis, review and freeze, then source, saved headline triage,
  draft and human review, and market context, joined only through stable IDs and
  explicitly recorded Inbox origins, read from local records only (see **Event
  overview**).
- An evidence-first research analysis of a saved event, chosen explicitly beside the
  market-hypothesis draft: its own request, result and review contracts, quotes located in
  the captured text by code, interpretation and unknowns labelled apart, one approved send
  (see **Evidence-first research analysis (saved events)**).
- A market-implied rate path for a saved FOMC statement: the first four three-month
  average-SOFR windows from a retained Atlanta Fed Market Probability Tracker workbook,
  prepared by explicit local commands as a separate record, with meeting-specific pricing
  shown as unavailable (see **Market-implied rate path (saved FOMC statements)**).
- Related research on the event overview: labelled navigation to existing library cases
  (coverage of the same event by address and date, the same named release family, or a concrete research topic), with
  differences and content status, selected on read from local records (see **Related research (event overview)**).
- Related cases: two historical announcements (OFAC's 2019 PdVSA sanctions, BIS's 2022
  advanced computing and semiconductor export controls) built from retained official pages,
  with quoted source facts, labelled interpretation and review status, and a local,
  write-once match of an Inbox entry or capture against them by instrument, sector, country
  and agency (see **Related cases (historical announcements)**).
- Cross-source comparisons: EIA industrial retail electricity sales beside G.17
  manufacturing output, and G.17 electric utility output beside the customer breakdown of
  EIA total retail sales, for the fourth quarters of 2023–2025 and each 12-month period
  printed, with explicit not-covered periods, sign-only descriptions, per-value sources and
  a write-once result. Local and $0 (see **Cross-source comparisons (G.17 and EIA)**).
- Electricity by sector from retained EIA Table 7.6: residential, commercial and
  industrial retail sales against the same month a year earlier (July 2025 to June 2026)
  and January–June, with a fixed, inclusive ±1% band, transportation and total sales as
  context, reconciliation within rounding, a write-once result reused when inputs are
  unchanged, and verifying reads. Local and $0; tested with synthetic files (see
  **Electricity by sector (EIA)**).
- Industry findings from retained G.17 releases: industries against their parent or the
  total, revisions of the same month, and manufacturing breadth across the 19 NAICS
  subsectors, from validated Table 1 pages with exact published rates, write-once results
  reused when inputs are unchanged, and verifying reads. Local and $0; tested with
  synthetic pages (see **Industry findings (G.17)**).
- Treasury findings: a retrospective, single-market pilot that measures daily H.15
  Treasury yields around retained Federal Reserve and BLS releases from a kept package,
  with deterministic exploratory rules, write-once results reused when their inputs are
  unchanged, and zero-finding occasions shown as such. Local and $0; tested only with
  synthetic packages (see **Treasury findings**).

`python -m second_order schema` prints the input contract. Invalid model output
fails explicitly. Live model calls are limited to the gated pilot described below, the
Tracker's paid path (see **Paid requests**) and paid headline triage (see **Headline
triage**), each available only when explicitly enabled. The one market-data request path is
the keyless Board download of the H.15 release package, for market context and for frozen
hypotheses' outcome data, also only when explicitly enabled.

## Model drafting adapter (offline)

The adapter turns your event metadata and source text into a strictly validated
hypothesis draft for review. The command is offline: it never creates an HTTP client,
and only previews the request or validates a saved response. Tests use mocked
transports. The adapter's send function is not intrinsically offline (given a real
client and key it would make a billed request); only the gated pilot's `send` and a
server started with `serve --enable-paid-drafts` pass one. The request
follows the Claude Opus 5.5 contract: one strict tool with tool_choice `auto` and an
explicit effort, since forced tool choice is rejected. The model drafts only when the
source text is sufficient and the event has a defensible connection to the offered
yields; otherwise it may decline in a few sentences, which produces no draft.

```powershell
python -m second_order model-draft --event event.json --source source.txt --print-request
python -m second_order model-draft --event event.json --source source.txt --response response.json
```

`event.json` holds `headline`, `source_url`, `published_at` and `story_id`. The model
supplies only the summary, map and legs; code sets the class, usage and engine record,
and a draft has no freeze time. A replayed response is recorded as `offline-replay`
because its origin is not verified. The freeze helper (`freeze-draft`) refuses model
drafts; the lower-level `freeze` command does not check the provider. The Hypotheses page
freezes a reviewed model draft only under the conditions in **Freezing from the
interface**. See SPEC.md for the full contract.

Apart from the Tracker's paid path, the only live path is a pilot on Claude Sonnet 5.5
over synthetic review cases. Each run
has its own identity, directory and prompt version: pilot-1 and pilot-2 covered
clear-policy and insufficient-source, pilot-3 covered the other six cases under
draft-prompt-4, and the current run, pilot-4, reruns conflicting-labor-inflation,
ambiguous-wording and headline-reports-move under draft-prompt-5. Earlier runs' records
are kept unchanged. `preview` sends
and writes nothing; `send` needs
the key in `SECOND_ORDER_ANTHROPIC_API_KEY` and the hash the preview printed, reserves
the case so it is attempted at most once, makes one request without retries and keeps
the exact exchange privately under `data/pilot/`. The hash covers the exact request
body only, not the code; the code identity is recorded before sending. Running it is a
separate, explicit decision.

```powershell
python -m second_order.draft_pilot preview conflicting-labor-inflation
python -m second_order.draft_pilot status
```

To keep demo records, use `python -m second_order demo --db second-order-demo.db`.
Use a new v2 database; do not point the command at v1's database.
`freeze` records a supplied JSON hypothesis; `evaluate` explicitly reevaluates
stored records: baseline-bound ones against the outcome snapshot named with `--outcome`, and
those whose legs are all fictional demonstration series against the committed demo fixture.
Every other unbound record is reported as skipped, and no evaluation is appended for it. The
demo fixture is invented and ends on 2024-12-31, so it never supplies market evaluation.

`python -m second_order scoreboard --db <path>` lists the rules configurations in
a store without writing to it; add `--rules-hash <hash>` to summarize exactly one.
Configurations are never pooled.

## Market snapshots (FRED)

Treasury 2- and 10-year constant-maturity yields (FRED DGS2/DGS10) can be imported
as pinned, append-only snapshots. The import requests FRED over the network and
reads an API key; it is the only command that reads `FRED_API_KEY` (`fuels refresh` reads `EIA_API_KEY` or the
EIA key stored by `fuels key set`; see **Fuels page**). Register a free FRED key, set it yourself in the shell
environment as `FRED_API_KEY` (never in a file in this repository), then:

```powershell
python -m second_order market import --db second-order.db --start 2023-01-02
python -m second_order market snapshots --db second-order.db
python -m second_order market diff --db second-order.db <older-id> <newer-id>
python -m second_order market readiness --db second-order.db --snapshot <id> --published <YYYY-MM-DD>
```

Each snapshot records the observation dates, the requested FRED vintage and our
retrieval time as separate facts; see SPEC.md. A stored snapshot is not
automatically enough history: the import and `market readiness` report usable
reference windows and placebo coverage under the active rules, and a freeze
refuses a baseline that cannot score every leg. An outcome snapshot must be
requested from a start on or before the event's publication date. A schema-1 store needs
`python -m second_order store migrate --db <path>` once before any write. Schema-2 and
schema-3 stores accept every command-line write; the same command (or the Hypotheses page's
explicit upgrade) brings a store to schema 4, adding the freeze-action and assessment-action
tables that interface freezes and assessments need, and leaves every existing row unchanged.
New stores start at schema 4.

A prospective hypothesis on these yields binds a baseline snapshot at freeze and is
evaluated against a named outcome snapshot imported after its horizon. For a manual
prospective showcase, write a draft: the hypothesis JSON without `frozen_at`,
`replay_as_of` or `supersedes` (see `python -m second_order schema`). The helper
stamps the current UTC time, runs every freeze check and prints the hypothesis ID
and recorded timestamps. It never edits the draft, and a draft that was already
frozen is refused rather than restamped. "Manual" means outside the project's model
adapter, not "no AI": record any AI assistance in `engine.model`, and set
`engine.prompt_hash` to the SHA-256 of the exact authoring recipe or prompt file.

```powershell
python -m second_order freeze-draft draft.json --db second-order.db --baseline <snapshot-id>
python -m second_order evaluate --db second-order.db --as-of <iso-time> --outcome <snapshot-id>
```

Every new freeze applies freshness policy B: the baseline must classify, for every leg,
the last expected session before the publication date. A FRED import made the evening
before a morning release usually ends a day earlier, so that freeze is refused until a
newer baseline is imported. Records frozen before the policy are read and evaluated
exactly as stored.

These yields are measured by date only (a daily convention, no verified intraday
time), so they cannot enter research summaries; research intake stays closed.

This product uses the FRED® API but is not endorsed or certified by the Federal
Reserve Bank of St. Louis.

## Market snapshots from a kept H.15 release package

The same 2- and 10-year constant-maturity yields can also be pinned from a release
package already kept and validated under **Market context for selected events**. The
import copies the two series locally. It never fetches, and repeating it writes nothing:

```powershell
python -m second_order market-packages list
python -m second_order market import-package --db second-order.db --package <package-id> --start 2023-01-02
python -m second_order market readiness --db second-order.db --snapshot <id> --published <YYYY-MM-DD>
```

- **Separate observables.** Snapshots of this provider (`board-h15`) serve only the
  registry's H.15 entries, `yield:ust2y_cmt_h15` and `yield:ust10y_cmt_h15` (the Board's
  series `RIFLGFCY02_N.B` and `RIFLGFCY10_N.B`). The FRED entries keep their meaning. A
  leg is never measured on another provider's baseline or outcome, a hypothesis cannot mix
  providers, and `market diff` compares snapshots of one provider only. The observables
  offered to the model are unchanged (FRED's).
- **Checked first.** The package's acquisition record, size and SHA-256, and its
  validation record for the current parser version, which must have accepted it and must
  recompute exactly. No date may follow the day the package was requested. An
  unvalidated, refused or altered package is refused, as is a start before either
  series' first observation or after their common coverage. Nothing is written then, and
  a failed write leaves no partial snapshot.
- **Recorded.** The package's ID, address, receipt time and SHA-256; the validation
  record's SHA-256 and the parser and import versions; the Board's series identifiers,
  descriptions and units; every date from the start to each series' last row, with its
  exact decimal text or ND and its calendar status; each series' coverage; the calendar's
  identity; and when the snapshot was built. The copied rows are also kept with their
  SHA-256, so the snapshot does not depend on the package folder.
- **Possession, not vintage.** The receipt time is when the values were held, not when
  they first became public. The package has no historical vintage: it holds the Board's
  values as published when it was received. The snapshot's vintage is therefore none,
  never a date. The data entry's "prepared" time is kept exactly as stated; it names no
  time zone and is used as neither an observation nor a possession time.
- **Dates only**, under the same daily convention as FRED; nothing is interpolated or
  filled, and these legs cannot enter research summaries either.

A repeat of the same package, start and calendar finds its snapshot. Another
acquisition, even of identical bytes, keeps its own receipt time as a separate snapshot.
The existing freeze and evaluation commands accept these snapshots as they accept
FRED's, with freshness policy B (above). Source: Board of Governors of the Federal Reserve
System, H.15 Selected Interest Rates.

## Freezing from the interface (Hypotheses)

The **Hypotheses** page (`/hypotheses`, in the site navigation) freezes one H.15-bound
prospective showcase hypothesis per explicit approval, without JSON files or commands. The
server reads and writes one research store, chosen when it starts (`serve --store`,
default `data/real/second-order.db`); a page never chooses a path. Four steps:

1. **What to freeze.** Either a manual hypothesis, entered in a structured form on the two
   registered H.15 observables (you choose each leg's direction, horizon, link, channel,
   rationale, falsifier and headline flag, and the primary leg; nothing is preselected),
   or a reviewed model draft. A manual hypothesis's engine record says how it was
   authored, in your words, and its prompt hash is the SHA-256 of the exact submitted
   input, which is kept with the freeze. A model draft is eligible only when it is a real
   provider draft built under draft-prompt-6, with a draft outcome and a current review
   (saved against the exact view served now) marked Human-reviewed. Mock drafts,
   declines, invalid responses, failures, drafts saved under draft-prompt-5 and missing or
   stale reviews are listed with the reason and cannot be chosen. Only the corrections
   review permits are applied; the model's output, its engine record and every draft and
   review record stay unchanged. Human review is not approval to freeze.
2. **Baseline.** A Board H.15 snapshot in the store, or an explicit import of a kept,
   validated release package (see the section above; a repeat reuses the snapshot).
   Retrieving a newer package is a separate approved action under Market context; the
   freeze never downloads. An older store is upgraded (to schema 4) only by its own explicit
   button.
3. **Preview.** Writes nothing. It shows the exact effective hypothesis and its SHA-256,
   the event as supplied (a time with its UTC offset; a date-only source is not supported,
   because no time is invented), the origin, the baseline's provider, possession time,
   coverage and absent vintage, freshness policy B, readiness, the expected scoring window
   from the New York freeze date, the limitations and the classification, and anything
   that blocks a freeze. Changing any input voids the preview.
4. **Approve one freeze.** The approval names the preview's SHA-256, which binds the
   effective hypothesis, its origin (draft, view fingerprint and review version, or the
   manual input), the baseline, the source bindings, the freshness policy and the New York
   freeze date. The server recomputes the preview; if anything changed (a new review
   version, edited content, another baseline, or a new day in New York, which moves the
   scoring anchor), nothing is frozen and the new preview is shown to approve or not. The
   server stamps the freeze time. The hypothesis, its baseline binding and the freeze
   action are written in one transaction; repeating the approval (a double click, a
   second tab or worker) returns the original freeze, and a different approval of the
   same request is refused. After a lost reply the page reads whether the approval froze
   anything and never sends it again.

A frozen record reopens at `/hypotheses/<id>` as "Frozen · Not evaluated", read-only, with
its content and fingerprints, origin, baseline, freshness check, scoring window and
classification; it survives reloads and restarts. Records frozen outside the interface
(the existing FRED case) are listed too, unchanged. Everything frozen here is a
prospective showcase: H.15 observations are dated, not timed, so they do not meet the
research timestamp gate, research intake is closed, and showcase cases never enter
research summaries or rates. A freeze evaluates nothing, prepares no Dossier, acquires no
outcome data and calls no model; assessing is a separate explicit step (next section).

The flow is tested with temporary stores, SYNTHETIC packages and a fake provider
(`npm run test:browser:freeze` drives it in a browser). No real hypothesis has been frozen
from the interface, and the model path has not been run against a live provider.

### Before a freeze: readiness

"What can I freeze prospectively now, what is missing, and what would make the next case
possible?" is answered by one read-only check, on the Hypotheses page ("Before a freeze:
readiness") and on the command line:

```
python -m second_order research-readiness [--db <store>] [--published <YYYY-MM-DD>] [--packages-dir <dir>]
```

For a publication date (default: today in New York) it lists every registry entry and keeps
three questions apart. **Freeze readiness**: whether a held snapshot of the entry's provider,
received before now, classifies the last expected session before that date (freshness policy
B) and gives the scorer's reference windows under the active rules; a provider is ready only
when one snapshot serves all of its observables, because a hypothesis binds one baseline.
**Outcome data**: the expected scoring window from the SIFMA calendar; outcome data cannot exist
before their target dates end, so their absence never blocks a freeze. **Research use**: shown
separately, with the reasons it is not possible today (INCLUSION.md's status, the showcase-only
freeze paths, and the research timestamp gate on dated-only observations). Registry concepts
without a provider (`yield:us2y`, `yield:us10y`, `index:dxy`, `fx:usdils`, the futures and the
equity families) are listed as concepts, never as operational, and no data for them are held;
the offline demo's fictional demonstration series are reported apart, as covering no registry
concept. Each entry names its next explicit action
(an approved download, a local validation or import, an upgrade, or an owner decision); the check
itself downloads, imports, upgrades and freezes nothing, and reads no key from the environment.
The Board posts H.15 on business days at 4:15 p.m. New York time with the previous business day's
values, so an H.15 download is proposed only from that time on the weekday after the session a
baseline must state; before then the check says to wait for that release.
`npm run test:browser:readiness` (after `npm run build`, in `frontend`) checks the card in a
browser on a SYNTHETIC store and fixed clock: the date choice, the connected observables apart
from the registry concepts, the not-ready and waiting states, research use answered apart from
freeze readiness (still not possible where a freeze is ready), and that checking leaves every
served file unchanged.
A draft protocol for a first prospective pilot built on this answer is in
`docs/research-pilot-protocol-draft-2026-11-04.md` (private; not in the public repository) (draft, not active; revised on 2026-11-07 after
a check of one real package). A SYNTHETIC rehearsal of one pilot night, from readiness to the
assessment, runs with `python -m unittest discover -s tests -p test_pilot_rehearsal.py`. The same case can be
practised by hand, SYNTHETIC and isolated (a temporary folder outside every checkout with its own store, a simulated
clock and a fake Board server, on port 8765): `python tests/pilot_drill.py start`, with the steps in Hebrew in
`docs/pilot/fomc-pilot-drill.he.md`; `npm run test:browser:pilot-drill` walks the same steps in a browser, and
`npm run test:browser:lifecycle-mobile` checks that the freeze, record and assessment views fit a 375 and 390 px phone.
The protocol, approved by the owner on 2026-11-07 as a showcase pilot starting at
2026-12-01T00:00:00+00:00, is `docs/pilot/fomc-pilot-protocol.md`, with a Hebrew checklist and journal
beside it. The pilot's
ledger, one case per scheduled statement by its first freeze, is read with
`python -m second_order pilot-ledger --table`.

## Assessing from the interface (Hypotheses)

A frozen hypothesis is assessed only by an explicit approval on its page
(`/hypotheses/<id>`), and every assessment is kept. Nothing is downloaded, imported,
evaluated or prepared automatically, and opening a page writes nothing.

- **Readiness.** The page shows separately whether the horizon has elapsed and whether
  outcome data are held. Expected dates come from the freeze's scoring window on the SIFMA
  calendar; the dates an assessment would measure come from the engine's own anchors on the
  pinned series. States: horizon not elapsed (a target date has not ended in New York: a
  date-only observation counts only after its date ends, and when the publisher supplies
  it is not known); outcome data missing; outcome data held with a genuine gap (the source
  states no value for a session a leg needs, so that leg will be recorded as unavailable;
  nothing is filled); ready; and recorded.
- **Outcome data.** A compatible outcome is a snapshot of the hypothesis's own provider that
  verifies (its ID, copied source bytes and classified rows are checked against what its
  import recorded), classifies each leg's series from on or before the publication date,
  and was received after the baseline. The baseline bound at freeze is never an outcome,
  and outcome data never fill or replace its history. An H.15 outcome is imported by an
  explicit click from a kept, accepted release package, from the publication date; an
  existing snapshot of that package that already serves is reused. A FRED-bound
  hypothesis (such as the existing FRED case) is measured only on local FRED snapshots:
  the page never fetches FRED data and never substitutes H.15, and says so.
- **Retrieval.** The Outcome data card on the Hypotheses page plans one download of the
  Board's release package for the hypotheses you select (none is preselected). It lists
  every expected session from each publication date to its latest expected target, split
  into future sessions (never requested or presented as obtainable), sessions held by a
  snapshot or a kept package, past sessions awaiting the Board's release (H.15 is posted
  at 4:15 p.m. New York time on the next business day; listed with the moment they can be
  obtained, never requested), and missing past sessions. One request serves every selected
  hypothesis; a covered selection needs none. The approval has its own scope
  (lifecycle-outcome-plan-0.2; an event's market-context plan covers only fourteen days
  either side of its date) and the market retrieval's fetcher and safeguards: a server
  started with `--enable-market-retrieval`, the plan recomputed under the write lock, a
  numbered attempt recorded before the request, no redirect, retry or fallback, transfer
  and archive limits, and failed or uncertain attempts left visible.
- **Preview.** Writes and evaluates nothing. It binds the hypothesis (its ID is the SHA-256
  of the stored record), the baseline and outcome snapshots, the active rules and their
  hash, the cutoff, each leg's dates, readiness and gaps, the assessments already recorded
  and whether this is a reassessment, and lists the records and the file the approval will
  create. The freeze record pins no scoring rules, and the preview says so; the rules
  applied are recorded with the assessment. The server sets the cutoff from the inputs:
  the latest of the outcome's receipt time, the freeze time and the end (23:59:59 New
  York) of each leg's target date. A preview therefore has no time-based expiry, while any
  change in what it binds changes its SHA-256. It shows what will be assessed, not the
  result: the verdict is computed only when an approval is recorded.
- **Evaluate and prepare Dossier.** One approval of one preview. The server recomputes the
  preview (a difference is refused, with the new preview), evaluates only the selected
  hypothesis on the bound inputs, and records the evaluation and its approval in one
  transaction (store schema 4). A double click, another tab or worker, or a repeated
  approval returns the saved result; an identical assessment is never recorded twice or
  recomputed; a further assessment (on another outcome snapshot) is an explicit
  reassessment that appends and never overwrites. Then that one assessment's Dossier is
  prepared beside the store (`<store name>-dossiers/<hypothesis>/<assessment>.json`); if
  preparation fails, the reply says "Evaluation saved; Dossier not prepared" and a
  separate Prepare Dossier action completes it without evaluating again. After a lost
  reply the page reads the outcome and never sends the approval again.
- **Journal.** The Hypotheses page lists every frozen hypothesis with its lifecycle state,
  origin and provider, and every recorded assessment by record time (none is selected for
  its result), each with its own page and Dossier. A Dossier is read from its prepared
  file, checked against its fingerprint and the stored assessment; it shows whether the
  snapshots still verify and, separately, whether the raw release package is held here (a
  snapshot's observations are copied in the store, so it does not need the package).
- **Drafts.** A Tracker draft frozen on this page shows the freeze in its review panel and
  in My analyses, derived from the verified freeze record and joined only by the draft ID
  it recorded. The draft, its published view, its saved request and its reviews are never
  rewritten, and a review saved after the freeze is named apart from the one used at
  freeze.

Everything assessed here is a prospective showcase: no success rate, research denominator
or claim of validated forecasting performance. The workflow is tested with temporary
stores, SYNTHETIC packages and fake transports (`npm run test:browser:assessment` drives it
in a browser). No real outcome download, evaluation or Dossier preparation has been made
from the interface, and the existing FRED case has no local outcome snapshot.

## Reading a score

The measured move is multiplied by the expected direction and ranked against
same-horizon historical moves transformed in the same way. Support requires a
positive signed move and rank >= 0.80; contradiction requires a negative signed
move and rank <= 0.20. These are descriptive evidence labels, not significance
tests or evidence that the event caused the move.

The research scoreboard uses research primary legs only. Replay and prospective
results have separate baselines and separate summaries. Story groups and
non-overlapping reference windows describe dependence; they do not establish
statistical independence.

## Fixture limitations and provenance

The offline demo's market data are FICTIONAL demonstration series. `fixtures/demo-market.json`
is written by `second_order/demo_market.py` (version demo-market-0.1) from invented
piecewise-linear paths, a fixed integer recurrence (a linear congruential generator seeded with
20261110) and two invented moves after the two fictional events; a test checks that the
committed file equals the generator's output byte for byte. The series are `demo:rate` (a
fictional interest rate in percent) and `demo:fx-index` (a fictional currency index), provider
`fictional-demo`, tickers `DEMO-RATE` and `DEMO-FX`, price basis `fictional`, on business days
from 2022-01-03 to 2024-12-31. No number is, copies or approximates a market observation, and no
capture, provider or vintage stands behind it.

The two showcase events are fictional (the Central Bank of Demoland), with `example.org` links,
and their hypotheses were newly written for the demo. The registry keeps the demo IDs in a
separate table: they resolve for measurement but are not registry entries, are bound to no
provider, and a research hypothesis cannot name them; the research scoreboard ignores any
hypothesis with a demo leg. The UTC day-end timestamps are an explicit illustration convention
(timestamp basis `fictional_daily`), and the code refuses them for a research score.

## Scope

See [SPEC.md](../SPEC.md), [INCLUSION.md](../INCLUSION.md) and [PORTING.md](../PORTING.md).
The v1 Research Lab remains in the sibling geo_mechanism_project repository.
Its source snapshot for this build is a36960107e02bc7144c733381fda706ae540a9e0.
A public repository URL/tag can be added when v1 is published.
