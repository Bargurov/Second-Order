# Second Order v2 — specification 0.5.52

Changes in the next version (unnumbered until integration; rules unchanged at 0.5.0; store schema unchanged at 4; the
pilot protocol, its settings and the ledger unchanged): the news-relevance holdout leaves the public tree.
It is read only from the environment variable SECOND_ORDER_RELEVANCE_HOLDOUT or
content/news-relevance/private/holdout.json, a private option.
When the file is absent, the CLI refuses the private holdout with a message (EvalRefused) and its own test file skips.
A public, fictional 24-case `sample` set takes its place among the public sets, and the released QA research-quality set
is renamed from "holdout 1" to "released set 1".
The offline demo runs on FICTIONAL demonstration series instead of the third-party daily quotes it used before.
fixtures/demo-market.json (demo-market-0.1), written by second_order/demo_market.py from invented paths and a fixed
integer recurrence, replaces fixtures/market.json; the two showcase cases are fictional events (the fictional Central
Bank of Demoland lowers its policy rate, June and October 2024) with new identities, on the new IDs demo:rate and
demo:fx-index (sections "Immutable hypothesis" and "Prepared Dossier views").
The demo IDs are a separate registry table: they resolve for measurement but are not registry entries and are bound to
no provider; a research hypothesis cannot name them; the research scoreboard ignores any hypothesis with a demo leg; and
`evaluate --db` scores only hypotheses whose legs are all demo series, reporting every other unbound one as skipped with
no evaluation appended.
Dossier views name the series as fictional ("Fictional demonstration data" replaces "Current-vintage data"); research
readiness reports the demo fixture apart, as demonstration series that cover no registry concept, and concept rows no
longer show fixture coverage.
Versions: dossier-view-0.3 (a lifecycle Dossier file prepared at 0.2 is still read; a prepared folder at 0.2 waits for
`prepare`) and research-readiness-0.2 (the client refuses 0.1 and a reply without the demonstration block).
Nothing else changes: yield:us10y and index:dxy stay registered concept IDs, and the stored hypotheses and evaluations,
research scores and the pilot are as they were.
The test cases that quoted authored ECB texts (an interview and a keynote speech) are replaced by FICTIONAL cases (a
fictional central bank, newspaper and speakers, example.org links, marked "fictional": true) that keep each test's
purpose; the unused cases quoting two other ECB speeches are removed, and no rule, version or stored record changes.
The FCX research package (research/fcx) rests on SEC EDGAR copies only (sections "Company page (FCX, private)" and
"Copper tools"): the third-quarter 2026 10-Q and the two releases, each exhibit 99.1 to a Form 8-K (the Q3
results release furnished under Items 2.02 and 7.01, the Bagdad release attached under Item 8.01; approvals
fcx-sec-locate-02, fcx-sec-index-02 and fcx-sec-docs-02), replace the investor-relations copies, which are kept
privately with their records and no longer read. Every record and passage resting on them was matched against the
SEC text (research/fcx/sec-match.md, by research/fcx/tools/sec_match.py): 749 exact and 6 that differed only in
spacing, whose quotes now carry the SEC wording; none relaid, none not found, no definition changed; the facts
checker passes on the SEC copies. The page drops its note that the SEC copies were not read, and the later Bagdad
row of the copper producers states its source's terms as an SEC EDGAR copy. Access to the FCX page stays
administrators only, and no view, page or reader version changes.
The comparison fcx-annual-2025-to-q3-2026 and the chains grasberg-mud-rush and bagdad-expansion have a version 2
pinned to the SEC copies (published 2026-11-11, content unchanged; version 1 stays and its acquisitions read as
superseded), and the captured frontend fixtures are regenerated; the company-page fixtures represent the package as
the public tree holds it, without the earlier investor-relations acquisitions.

Changes in 0.5.52 (rules unchanged at 0.5.0; store schema unchanged at 4; the pilot protocol, its settings and the
ledger unchanged): the copper research loop (section "Copper research"). A copper desk at /copper ("Copper" in the top
bar) links the five copper pages with one line each; a publication comparison shows what two retained publications say
on the same matters, side by side, with pinned evidence and no computed change between two lines (the first, historical:
FCX's fiscal 2025 annual report against its third-quarter 2026 report); and the owner's research note is an append-only
personal record with an optional expectation and a question for the next check. The owner's decisions of 2026-11-10:
personal expectations are allowed, a price's direction included, apart from source wording, the assistant's drafts and
research scores; the claim-word and price-direction lists are lifted from the owner's reading line in the event chains
and stay on the assistant's text. Versions: publication-comparison-0.1, research-note-0.1, copper-research-view-0.1.
Nothing else changes: the copper thesis, the chains and their records, the FCX page, research scores and the pilot are
as they were.

Changes in 0.5.51 (rules unchanged at 0.5.0; store schema unchanged at 4; the pilot protocol, its settings and the
ledger unchanged): copper event chains, a private page at /theses/copper/events with three assistant-drafted chains from
a retained event to a reason or risk of the copper thesis, evidence pinned in each chain version, and the owner's
append-only reviews and readings (section "Event chains (copper thesis)"). The events register accepts `fcx:` passages
(metals-research-0.3, metals-view-0.5); a Hebrew word list joins the English text rules. Versions: event-chain-0.1,
event-chains-view-0.1. Nothing else changes: the copper thesis, the existing metals chains, the FCX page and the pilot
are as they were.

Changes in 0.5.50 (rules unchanged at 0.5.0; store schema unchanged at 4; the pilot protocol, its settings and the
ledger unchanged): the copper tools' project table shows Bagdad as two company statements, the later one first (section
"Copper tools", Projects). The later statement, the board's approval, is read live from the verified FCX research
records (copper_linked, through company_research_view.resolved()); the earlier one, the fiscal 2025 10-K, keeps its
catalogue figures, passages and computations unchanged. Break-even economics is a field and column of its own, never an
incentive price; the start of production is a passage and the long-term annual rate is never placed in a year. Any fault
in the FCX package withholds only the later row. Versions: copper-producers-0.2 and copper-tools-view-0.2. Nothing else
changes: the copper inputs catalogue and its digest, the coverage calculator, the scenario records (a record saved
before this change still verifies), the FCX page, the copper thesis and the pilot are as they were.

Changes in 0.5.49 (rules unchanged at 0.5.0; store schema unchanged at 4; the pilot protocol, its settings and the
ledger unchanged): stage 2 of the FCX company page, a Scenarios tab with two separate calculations on the company's Q4
2026 assumptions: copper price × volume sold, its change and that change split into a price and a volume effect; and the
October release's copper cash flow sensitivity applied linearly to a price change (section "Company page (FCX,
private)", Scenarios). POST /api/companies/fcx/scenario computes exactly and writes and stores nothing. The read is
company-research-0.2 (page.json company-page-0.2, with its scenarios texts); facts.json gains the company's Q4 2026
copper price and the sensitivity's $0.10 step as quoted records. Nothing else changes: the copper thesis, the copper
tools and their Bagdad figures, the metals and fuels pages and the pilot are as they were.

Changes in 0.5.48 (rules unchanged at 0.5.0; store schema unchanged at 4; the pilot protocol, its settings and the
ledger unchanged): a private company page, /companies/fcx, served from the committed FCX research package and its four
retained documents (section "Company page (FCX, private)"). What names a figure carries no percentage: FCX's ownership
share is a figure from the documents, shown only by its own record when that record's document is verified, never in
the name or accessible label of a withheld figure (the four Grasberg copper volumes had carried it). Nothing else
changes: the copper thesis, the copper tools, the metals and fuels pages and the pilot and its drill are as they were.

Changes in 0.5.47 (rules unchanged at 0.5.0; store schema unchanged at 4; the pilot protocol, its settings and the
ledger unchanged): the fuels page closes its two known edge cases, and a hand-run pilot drill is added.
- fuels-view-0.5: a verified series whose latest observation is more than ten days older than the newest latest
  observation on the page is behind. It keeps its price, its own date and its history, with how far behind it is;
  whatever is computed from it is withheld instead: the barrel, its crack history and Situation Now when it is Brent,
  gasoline or diesel (nothing on the page is computed from WTI or Henry Hub), and a note bound to a snapshot whose
  barrel input was behind. Prices from different dates are never combined and nothing is filled in; a snapshot or a
  source that fails verification still withholds every value as before. The reader recomputes `behind` from the
  latest dates and refuses a barrel computed beside an input that is behind.
- A change whose exact value is not zero but rounds to zero at its shown places is shown with its direction and as
  under the last shown place ("−<0.01", "+<$0.01", "+<0.1%"), with a one-line key; 0.00 is only a true zero. A note's
  filled prose says "fell less than $0.01 a barrel", "a fall of less than $0.01 a barrel" or "less than 0.1%" (a
  negative part under a cent had read "+$0.00"). The exact values and the split labels are unchanged.
- tests/pilot_drill.py: a SYNTHETIC practice of one pilot case by hand (docs/pilot/fomc-pilot-drill.he.md), in a
  temporary folder outside every checkout with its own store, a kept SYNTHETIC H.15 package and a copy of the pilot
  settings, on a simulated clock and a fake Board server that keeps the 4:15 p.m. posting time, at port 8765. It is
  test infrastructure, not part of the application.
- The Hypotheses lifecycle views fit a phone (display only; no computation, protocol, date or scoring rule changes).
  The freeze preview and its confirmation had made the page 166 px wider than a 375 px screen: the freeze steps were
  grid items that kept the legs table's width. Grid items now shrink, long identifiers and hashes wrap, and each of
  the four lifecycle tables (the legs, the assessment's leg dates, the recorded legs and the outcome plan) scrolls
  sideways only inside its own area, which is named and keyboard-focusable; nothing is clipped with overflow-x:
  hidden and no text is made smaller. `npm run test:browser:lifecycle-mobile` measures the freeze preview and
  confirmation, the frozen record, the outcome plan, the assessment preview and confirmation and the recorded
  assessment at 375, 390 and 1280 px.

Changes in 0.5.46 (rules unchanged at 0.5.0; store schema unchanged at 4): the FOMC pilot ledger
(fomc-pilot-ledger-0.3) states the pilot's phase: proposed; approved but not started ("starts at <start>, in the
future: nothing is counted before then"); running, through the last statement's New York date; or intake ended,
with outcomes tracked until every frozen case is assessed. Counting is unchanged.

Changes in 0.5.45 (rules unchanged at 0.5.0; store schema unchanged at 4; no code changes): the project owner
approved the FOMC pilot protocol on 2026-11-07 as a showcase pilot. It is now docs/pilot/fomc-pilot-protocol.md,
and content/pilot/fomc-pilot.json is approved with start_utc 2026-12-01T00:00:00+00:00. The approval covers the
eight statements, the 2-year primary and 10-year secondary legs at horizon 5, one case per statement by its first
freeze, deviations kept out of the summary, and outcome tracking past the last statement. Research intake stays
closed, and INCLUSION.md is unchanged.

Changes in 0.5.44 (rules unchanged at 0.5.0; store schema unchanged at 4; scoring, labels and every lifecycle
version unchanged): the FOMC pilot ledger is fomc-pilot-ledger-0.2. A case whose legs, roles or horizons differ
from the pilot definition (the primary and secondary observables by ID, each with its role and horizon, and no other
leg) is nonconforming. It stays the statement's case, frozen and covered, and is shown with its reasons and any
assessment, but it never enters the summary. A later conforming version does not replace it. Labels are read by
the definition's observable IDs, never by a record's primary flag. The start is an exact instant: start_utc must be
in UTC and before the first statement's expected publication (2:00 p.m. New York time on its date). A case's
stated publication time is compared with it as an instant, whatever the offsets, and a case published earlier is
before the start and never included. Counts reconcile: scheduled = not held + not started + before start +
upcoming + included; included = frozen + missed; frozen = pending + assessed + nonconforming. The protocol,
journal and checklist say so.

Changes in 0.5.43 (rules unchanged at 0.5.0; store schema unchanged at 4; lifecycle-freeze-0.1 and
lifecycle-assessment-0.1 unchanged; the outcome plan is now lifecycle-outcome-plan-0.2): one release-time rule for
baselines and outcomes. second_order/h15_release.py holds the Board's posting time (H.15 on business days at 4:15
p.m. New York time with the previous business day's values; a holiday or a closed Board only delays it), and research
readiness and the outcome plans both use it. The outcome plan splits ended sessions that are not held into missing
(the Board can already have posted them) and awaiting release (it cannot yet, with the moment from which it can);
only missing sessions justify the one request, and a session awaiting release never blocks a request that other
hypotheses' missing sessions justify. Held is decided first, by the verified local data, so a value posted early
counts. The plan version changed, so an approval of a 0.1 plan cannot authorize a request; the Hypotheses page shows
the awaiting sessions. The Market context page's event plans are unchanged. New: the FOMC pilot's ledger
(fomc-pilot-ledger-0.1, see FOMC pilot ledger below), a read-only count of one case per scheduled statement by its
first freeze, from content/pilot/fomc-pilot.json (eight dates, status proposed, no start timestamp). A proposed final
protocol (docs/pilot/fomc-pilot-protocol.md) and a Hebrew checklist and journal (docs/pilot/) await the
owner's approval; nothing is active, and research intake has not started.

Changes in 0.5.42 (rules unchanged at 0.5.0; store schema unchanged at 4; research-readiness-0.1,
lifecycle-freeze-0.1 and lifecycle-assessment-0.1 unchanged): research readiness knows when the Board can first
state a session. The Board posts the H.15 release on business days at 4:15 p.m. New York time with values through
the previous business day (its release page, checked 2026-11-07; a package received that day bore Last-Modified
16:15 New York time on 6 November and stated values through 5 November). Before 4:15 p.m. on the weekday after the
session a baseline must classify, the H.15 next action now says to wait for that release instead of proposing a
download that could only return an earlier session, and a waiting H.15 entry names that moment; FRED's wording is
unchanged. Only the action text changes: statuses, blockers and the freeze and assessment checks are as before. A
SYNTHETIC rehearsal of one pilot night on the pilot's own calendar (tests/test_pilot_rehearsal.py) runs readiness, a
stale baseline downloaded before the release, preview, freeze, repeated freezes, a changed package, the outcome
import and the assessment through the app's routes, plus a missing session in the scored window and a changed form
for the same statement, which is stored as a second hypothesis (the code refuses a repeated request, not a second
hypothesis on the same story; the protocol counts the first). The draft pilot protocol
(docs/research-pilot-protocol-draft-2026-11-04.md (private; not in the public repository)) was revised on 2026-11-07 from a check of one real H.15 package
in an isolated worktree; it is still a draft, and research intake has not started.

Changes in 0.5.41 (rules unchanged at 0.5.0; store schema unchanged at 4; accounts store unchanged at accounts-3): the
fuels page gains a short analysis over the verified EIA prices (see Fuels page, Notes, below). New: fuels-note-0.2,
which keeps a note's headline and lede (now the visible summary, forty to seventy words once filled) and replaces the
three columns with four short sections (what happened, what it may mean, who it may touch, what to check next) of
statements labelled observation, computed, hypothesis, sourced or source_projection, plus caveats; its placeholders
add Situation Now's week and month windows (dates, changes, percentages, directions and the split's words), so no
figure, date or direction is typed. fuels-view-0.4 passes each analysis with the title of each mechanism it names
and refuses one that names no committed mechanism. The page shows the headline and summary with one short button,
"Read the analysis", which opens the analysis in its own row under the summary and the barrel, so the barrel never
moves. The first analysis, content/fuels/notes/situation-0001.json, and its revision situation-0002.json (the weekly
report's inventory fall given as background, published after the window and naming no cause; no claim about idle
trucks) are bound to snapshot 9c94687f… (observation date 2026-11-03), written by Claude (AI-drafted) and
unreviewed; the page shows note 2. The
drafting procedure (docs/fuels-situation-note.md) drops its FRED-era limit: a session reads the verified EIA
snapshot's values, never the key (neither EIA_API_KEY nor the stored entry), `fuels key`, a refresh or a FRED-era
snapshot. fuels-note-0.1 notes read unchanged. No price,
calculation, snapshot, score, freeze, assessment, account or stored record changes.

Changes in 0.5.40 (rules unchanged at 0.5.0; store schema unchanged at 4; accounts store unchanged at accounts-3): the
EIA key can be stored once in Windows Credential Manager, through the keyring package (a new dependency), so a refresh
needs no typing (second_order/fuels_key.py). New commands: `fuels key set` (the key typed twice at a hidden prompt,
only at a real console; it refuses when a key is already stored), `fuels key replace`, `fuels key delete` and `fuels
key status` (whether a key is stored and whether EIA_API_KEY is set, never the key). `fuels refresh` uses EIA_API_KEY
when set, else the stored key, and its report names which (`key_from`). Only Windows Credential Manager is read,
written or cleared: any other keyring backend is refused before use. Saving a key requests nothing. The server, the
page and the snapshots never read the key. No score, freeze, assessment, account, snapshot or view changes.

Changes in 0.5.39 (rules unchanged at 0.5.0; store schema unchanged at 4; accounts store unchanged at accounts-3): the
fuels page reads its five spot prices from EIA's open data API instead of FRED (see Fuels page, below), after a
reading of FRED's terms found that its API terms bar storing or archiving FRED content and using it in software
development, which the page's write-once snapshots do. New: fuels-eia-0.1 (second_order/fuels_eia.py, replacing
fuels_import.py and fuels-fred-0.1), fuels-sources-0.2 (EIA series ids, routes, the description and units EIA must
give, the data vendor where EIA names one), fuels-snapshot-0.2 (provider eia; 0.1 files still read, never rewritten)
and fuels-view-0.3 (EIA's credit instead of FRED's notice; each snapshot's retrieval date and provider; no FRED
update column). `fuels refresh` reads EIA_API_KEY. EIA's API gives no publication date, so none is shown or inferred.
The crack, the situation windows, the mechanisms, the notes and their rules are unchanged. The Treasury yields'
FRED import (`market import`) is unchanged. No score, freeze, assessment, account or stored record changes.

Changes in 0.5.38 (rules unchanged at 0.5.0; store schema unchanged at 4; accounts store unchanged at accounts-3; no
version string of the app or of any engine, view or reply changes): the local integration of metals stage 2
(metals/stage-2, its entries 0.5.32 to 0.5.34 below) and the fuels page with its stage 2 (fuels/slice-1 and
fuels/stage-2) on integration/thesis-research-2026-11-05. The two lines had numbered their entries independently from
0.5.30: the metals entries keep their numbers (0.5.30 and 0.5.31 were already integrated), and the fuels entries are
renumbered 0.5.35 to 0.5.37 in their order, each naming the number it was written with. Both pages are kept whole:
/metals (GET /api/metals) and /fuels (GET /api/fuels) are separate admin routes with separate readers, `create_app`
takes both pages' folders, and the review server takes both --metals and --fuels. Fuels has a top-bar link; metals is
reached from the case library's copper entry and the copper thesis, as before. Nothing else changes.

Changes in 0.5.37 (written as 0.5.32 on fuels/stage-2; scoring rules unchanged at 0.5.0; store schema unchanged at 4; accounts store unchanged at accounts-3):
the fuels page's Stage 2 closeout (see Fuels page, below). In "Levels at both dates" the Brent, gasoline and diesel
levels are now P (published) and only the basket and crack levels C; every change stays C. Split amounts say "per
barrel"; levels use the true minus; the product line says when rounding moves a shown part by a cent; every label line
in "What it shows" carries a badge. Mechanism prose may no longer point at a time, narrate a price move or forecast
(the situation note keeps the shared phrase rule). A reply over the review server's SYNTHETIC world, or over a snapshot
from the test fake, carries `"synthetic": true`, and the page then marks itself as test data. fuels-view-0.2 gains that
optional key only. The browser check has 62 checks. No score, freeze, assessment, account or stored record changes.

Changes in 0.5.36 (written as 0.5.31 on fuels/stage-2; scoring rules unchanged at 0.5.0; store schema unchanged at 4; accounts store unchanged at accounts-3):
the fuels page gains three sections (see Fuels page, below): Situation Now (change windows and an exact split of the
basket's change), Market Drivers and Economic Transmission (committed mechanism prose). New: fuels-situation-0.1
(second_order/fuels_situation.py), fuels-mechanisms-0.1 (second_order/fuels_mechanisms.py; content/fuels/drivers.json and
content/fuels/transmission.json) and fuels-view-0.2, which replaces fuels-view-0.1 and keeps every Stage 1 key; the
interface fuels-event-0.1 is documented and not connected. The situation note's prose (fuels-note-0.1; none is
committed) now also refuses the mechanism files' refused phrases. Mechanism prose is reviewed and revised in place, with
git history as its version record. The browser check has 59 checks. No score, freeze, assessment, account or stored
record changes.

Changes in 0.5.35 (written as 0.5.30 on fuels/slice-1; scoring rules unchanged at 0.5.0; store schema unchanged at 4; accounts store unchanged at accounts-3):
the fuels page, a reference page for personal use (see Fuels page, below): Brent, New York Harbor gasoline and diesel
spot prices from FRED with a computed 3-2-1 crack, a notes column and a snapshot log. New: fuels-sources-0.1,
fuels-snapshot-0.1, fuels-fred-0.1, fuels-crack-0.1, fuels-note-0.1 and fuels-view-0.1; GET /api/fuels; the page /fuels;
the commands `fuels refresh` and `fuels status`; the `serve` option `--fuels-snapshots`. AGENTS.md rule 6 now reads:
"Keep scheduling and ingestion outside milestone 1. Crack spreads may appear only as explicitly refreshed, computed
reference figures on the fuels page; as research observables they wait for milestone 2." No score, freeze, assessment,
account or stored record changes.
Changes in 0.5.34 (rules unchanged at 0.5.0; store schema unchanged at 4; accounts store unchanged at accounts-3; no
version string of the app changes): the metals stage 2 review fixes (see Metals (stage 2), below). metals-research-0.2:
each event carries `when`, the date its quote gives ("2025", "September 2025"), which must be in its quote once that
quote is verified, and the page shows it in the event's caption under a note that these are past events, dated by
their sources, and not a news feed; an IEA measured link names its base ("56.8% of 2025 energy-technology demand (4544
kt of 8003 kt)"). metals-view-0.4 carries it. The Industrial uses IEA block says it covers energy technologies only;
each chain labels the lists after its links (exposed, may gain or lose, what could soften it) as the assistant's
reading; two chains' "what the data shows" now name only what their links show. The picker's list is one column, so it
reads top to bottom in the order the arrow keys and Tab follow.

Changes in 0.5.33 (rules unchanged at 0.5.0; store schema unchanged at 4; accounts store unchanged at accounts-3; no
version string of the app changes): stage 2 of the metals comparison, the research layer (see Metals (stage 2), below).
Three new engines and a new view version: metals-risk-0.1 (concentration and supply-chain indicators computed from the
USGS part), metals-iea-uses-0.1 (the IEA's energy-technology demand by mineral and technology) and
metals-research-0.1 (assistant-written transmission chains and sourced passages, resolved against the figures the page
holds), and metals-view-0.3, whose reply gains three parts, risk, uses and research. The page gains, per metal, a
snapshot and five folds (Supply chain, Concentration & risk, Industrial uses, Geopolitical exposure, Economic
transmission) and, in the Overview, a Leaders | Concentration switch. The reader checks each new part's figures again
from parts it has already read. Nothing is acquired, fetched or sent to a model, nothing is written, and the stage 1
parts (usgs, iea) and their rules are unchanged but for metals-usgs-0.3: each net import reliance row now carries its
commodity as printed, since a chapter can print two 2025 rows under one detail (bauxite and alumina; titanium sponge
and pigment).

Changes in 0.5.32 (rules unchanged at 0.5.0; store schema unchanged at 4; accounts store unchanged at accounts-3; no
version string of the app or of the metals engines and view changes): the metals page's presentation only (see Metals,
below). A closed picker with search replaces the grid of 45 checkboxes; three tabs (Overview, By metal, Method &
sources) keep the hash; the comparison gives short labels with a "Why?" button for the full reason and the years
caveat beside each figure; By metal opens one metal at a time with its parts closed. The reply, its reader, every
figure and the withholding rules are unchanged.

Changes in 0.5.31 (rules unchanged at 0.5.0; store schema unchanged at 4; accounts store unchanged at accounts-3; no
version string of the app changes): the metals comparison's review fixes (see Metals, below), metals-usgs-0.2 and
metals-view-0.2. A series whose unit the data file states in conflict with the printed USGS chapter carries a fixed
unit issue in words (one: vanadium's 2025 reserves, which the file labels metric tons and the chapter heads thousand
metric tons); its quantities and unit are not shown and no years figure is made from it, while its shares stay. The
rule that withheld every years figure under one is removed: a valid ratio under one year reads "less than 1". The
reader checks that each years pair is a 2025 Reserves and a 2025 mine Production series of the same commodity, unit
and stage, and that each series id is made from its own fields. Rankings say they are among the countries USGS names,
with "Other countries" one unsplit group.

Changes in 0.5.30 (rules unchanged at 0.5.0; store schema unchanged at 4; accounts store unchanged at accounts-3; no
version string of the app changes): stage 1 of the metals comparison (see Metals, below): a read-only page that lays
out the retained USGS Mineral Commodity Summaries 2026 data-release CSV (all 45 chapters) beside the retained IEA
Critical Minerals Dataset 2026 workbook (six minerals), for the metals a reader picks. New: metals-usgs-0.1,
metals-iea-0.1 and metals-view-0.1; one GET route, /api/metals; content/metals/sources.json (metals-sources-0.1);
the page /metals; a fail-closed reader and a browser check. Nothing is acquired, fetched or sent to a model, nothing is
written, and no earlier module or reply changes.

Changes in 0.5.29 (rules unchanged at 0.5.0; store schema unchanged at 4; accounts store unchanged at accounts-3; no
version string of the app changes): the copper thesis's exposure map is described (Theses, below; it was merged
beside 0.5.27 and 0.5.28 without a note of its own, and it changes no reply). A browser check of the readiness card (frontend/tests/browser/
readiness-check.mjs) pins the date choice, connected observables apart from registry concepts, the not-ready and
waiting states, research use apart from freeze readiness, and that checking writes nothing. `.gitattributes` fixes the
line endings of the two kinds of content bound by the SHA-256 of their bytes, so every checkout reads the bytes they
were bound to: content/case-library/*.json at LF (`text eol=lf`; the enrichments' case_file_sha256) and
content/news-relevance/*.json at CRLF (`text eol=crlf`; the recorded relevance measurement, made on a Windows
checkout, binds set_sha256 884ebecf… for dev; the private holdout, 41c10fc0…, keeps the same rule for its own folder).
Both are stored with LF, so no blob or record is rewritten; tests/test_line_endings.py pins the rules and the dev set
hash. A clean Windows clone with
core.autocrlf=true now passes the enrichment checks.

Changes in 0.5.28 (rules unchanged at 0.5.0; store schema unchanged at 4; accounts store unchanged at accounts-3):
Copper tools beside the copper thesis (see Copper tools, below): a coverage calculator on the IEA Critical Minerals
Dataset 2026 with three controls, write-once scenario records, and a published producer unit-cost comparison with
the company-stated projects and a capital-recovery panel. New: copper-inputs-0.1, copper-coverage-0.1,
copper-producers-0.1, copper-scenario-0.1 and copper-tools-view-0.1; two GET routes and three POST routes under
/api/tools/copper; the page /theses/copper/tools. The copper thesis (thesis-0.1, version 1) is unchanged; its page
and its library entry link to the tools.

Changes in 0.5.27 (rules unchanged at 0.5.0; store schema unchanged at 4; lifecycle-freeze-0.1 and
lifecycle-assessment-0.1 unchanged): research readiness (research-readiness-0.1, see Research readiness below), one
read-only check of what can be frozen prospectively for a publication date, what is missing and the next explicit
action, per registry entry: GET /api/lifecycle/readiness, the `research-readiness` command and a "Before a freeze:
readiness" card on the Hypotheses page. Freshness policy B's coverage test moved onto the stored snapshot
(Snapshot.coverage) so the freeze and the check share it; the freeze's checks, refusals and records are unchanged. A
draft pilot protocol (docs/research-pilot-protocol-draft-2026-11-04.md (private; not in the public repository)) proposes a first prospective pilot on scheduled
FOMC statements; it is not active, and research intake has not started.

Changes in 0.5.26 (rules unchanged at 0.5.0; store schema unchanged at 4; accounts store unchanged at accounts-3): the
thesis page names each balance table's demand and supply rows by the measure their figures state, never "Total demand"
and "Total supply" (copper v1: IEA base-case copper mine supply beside IEA total copper demand, and United States
refinery output beside reported refined consumption). Presentation only: the thesis files, the served replies and
thesis-view-0.1 are unchanged, and nothing is summed or subtracted. Separately, figure quotes in news explanations are
read under econ-calc-0.7 (docs/news-number-boundaries-2026-11-04.md (private; not in the public repository)).

Changes in 0.5.25 (rules unchanged at 0.5.0; store schema unchanged at 4; accounts store unchanged at accounts-3):
Theses, a versioned, source-grounded research view of one topic, the first on copper: its physical supply-demand
balance, the statuses of its reasons and risks, and who is exposed (see Theses, below). thesis-0.1 (index
thesis-index-0.1, catalog thesis-catalog-0.1, view thesis-view-0.1) commits one file per version under
content/theses/<id>/, written in a working session with no billed or in-app model request. Each read checks every
retained source against its acquisition record and every figure and passage it can read where it is cited, in memory,
and withholds any part whose sources do not check. Copper version 1 was published on 2026-11-03, from files retained
under data/sector-sources/copper/ (not committed) by six acquisition approvals: 14 single GETs and three files the
owner downloaded. GET /api/theses, /api/theses/{id} and /api/theses/{id}/versions/{n}; pages /theses/:id and
/theses/:id/versions/:n in the operator build, listed in the case library. The user and admin contracts (user-api-0.5,
admin-api-0.4), the Client, cases, research views, the Event Inbox and paid paths are unchanged; reads make no request.

Changes in 0.5.24 (rules unchanged at 0.5.0; store schema unchanged at 4; accounts store unchanged at accounts-3): a
news-first Client with shared briefs (docs/news-stories-contract.md: user-api-0.5 and admin-api-0.4, whose readers still
accept user-api-0.1 to 0.4). A source registry (news-registry-0.1) records, per publisher, what its terms allow to be
shown and whether its entries may be material for a summary or an analysis; TechCrunch and PR Newswire are connected
for display only, every other evaluated publisher needs an agreement or credentials, and only the official releases may
be material. Publisher feeds are refreshed only by the operator, through the Event Inbox's fetcher and records, into
their own cache. A separate newsroom store (newsroom-1, append-only) holds stories (same-headline grouping only, with
the operator's merges, detachments and headlines), ongoing topics with their developments, the editors' major marks
(at most seven days), brief versions and publications, each with who, when, why and an idempotency key. Coverage counts
a wire copy, and one publisher, once and never counts a company's statement. Ranking (news-rank-0.1) is fixed points
explained in words. A shared brief (story-brief-0.1) keeps reported facts, each citing its material reports, apart from
possible implications, records the material and its limits, and is published only by an explicit action after a
lexical guard (brief-guard-0.1) against advice, causal claims and certainty; a $0 draft compiles the reports' own
words, and a paid model draft needs `serve --enable-paid-briefs`, a cost preview and an explicit approval. Go deeper
(story-deeper-0.1) saves a story's permitted material as the user's own source and prepares its analysis through the
existing paths and limits; the run still needs the user's approval of its quote. News is the Client's home; Your
analyses moved to /analyses and the feed entries with search and import to /news/reports. The interests vocabulary is
news-interests-0.2 (three interests added), and each feed entry names its story. Reads never fetch, call a model or
charge.

Changes in 0.5.23 (rules unchanged at 0.5.0; store schema unchanged at 4): account binding, current news and usage
limits (docs/account-binding-contract.md; docs/news-usage-contract.md: user-api-0.4 and admin-api-0.3, whose readers
still accept user-api-0.1 to 0.3). Every user and administrator write names its page's account. The accounts store
becomes accounts-3: append-only publications (one per idempotency key, bound to the administrator and the canonical
payload, for credit and usage policies), usage policies, usage events and releases, and news interests. A user reads
the cached official news by interests, searches it (counted once per request key) and imports one allowlisted
publication by explicit preview and confirmation, only on a server started with `--enable-publication-import`. A
published usage policy is required for news, interests, searches, imports, new sources and preparations; each counts
once per quota day, storage is checked from the account's own sources, a refusal counts nothing, and the protective
request limits answer 429. The operator's feed refresh needs a usage policy, waits its cooldown and stops at its daily
budget. The Admin build gains Usage & limits. No limit value is selected: every one is the administrator's.

Changes in 0.5.22 (rules unchanged at 0.5.0; store schema unchanged at 4): self-registration and public credit terms
(docs/onboarding-contract.md: onboarding-api-0.1; the user contract is amended to user-api-0.2, whose readers still
accept 0.1). The accounts store becomes accounts-2: a registration is an inactive ordinary user row plus append-only
registrations and registration_decisions; `accounts upgrade` adds them to an accounts-1 store, keeping every row. A
pending or rejected registration has no session; the right password shows its own status. One attributed Admin
decision per registration; approval only activates, and triggers refuse credits, limits, ownership, quotes and
attempts before it. Accounts name every missing step (no_credits_allocated and no_credits_available are new reasons).
GET /api/public/credit-terms shows the active policy in points with three synthetic examples quoted by the real
formula; an Admin policy preview records nothing. The Client build shows signed-out visitors public pages at /,
/register, /sign-in and /credits. A user's source text may have 50,000 characters in any script: the source route
reads a form of up to 270,000 bytes (120,000 plus three for each character; 120,000 refused 50,000 Chinese characters or
emoji), the headline and address keep their own limits, an unpaired surrogate escape is refused, and the operator's
Tracker form keeps 120,000 bytes. The operator's selected pilot terms are Admin presets (credit_terms.py): flat points by
Effort (base 10, size rates 0, extras 0/5/10/15/20, so Low 10 to Maximum 30) fill a policy draft without a planning limit
or quote validity, and an initial allocation (100 credits once, 3 analyses a day) fills an approved, unallocated
account's two forms; only the existing explicit actions record anything.

Changes in 0.5.21 (rules unchanged at 0.5.0; store schema unchanged at 4): accounts, roles, credits and daily limits for
a first user flow, the evidence-first research analysis (docs/admin-user-contract.md: user-api-0.1 and admin-api-0.1).
A separate accounts store (accounts-1, data/accounts/accounts.db, created only by `accounts add-admin`) holds
identities, server-side sessions, record ownership, settings, admin credit policies, daily limits, quotes, attempt
reservations, resolutions and an append-only credit ledger. `serve` authenticates every request and enforces roles
(admin: every existing operator page plus the Admin screens; user: the Client build and /api/user/* only); each role is
served only its own build (frontend/dist, frontend/dist-client). A user's source is a capture they own; a user's
analysis is a research-request-0.2 (one per capture, prompt version and Effort) and their reviews research-review-0.2.
A run reserves the quoted credits, the daily slot and the attempt in one transaction before the existing one-attempt
send core posts the exact saved bytes once. Existing captures, requests, attempts, responses and reviews are unchanged
and stay the operator's; research_analysis's reply reading moved unchanged into research_reading.

Changes in 0.5.20 (rules unchanged at 0.5.0; store schema unchanged at 4): market-implied rate path for saved FOMC
statements, a separate private event record (rate-path-context-0.1, view rate-path-view-0.1) derived by explicit local
commands from a retained Atlanta Fed Market Probability Tracker workbook (rate-source-acquisition-0.1,
rate-source-validation-0.1, parser mpt-workbook-parser-0.1): the first four three-month average-SOFR reference windows
(mean, 25th–75th percentile) on the last observation date before the statement, on the event overview and the research
page, with meeting-specific pricing unavailable. GET /api/rate-context/capture/{id} only reads. Captures, origins,
research requests, attempts, responses, reviews, market context and every other record are unchanged; nothing is
downloaded.

Changes in 0.5.19 (rules unchanged at 0.5.0; store schema unchanged at 4): evidence-first research analysis, a second,
explicitly chosen analysis mode for a saved event with its own contracts: research-request-0.1 (research-prompt-1,
tool submit_research_analysis), research-result-view-0.1 and research-review-0.1, under data/research-analyses/. It
asks what the source establishes (exact quotes, located by code), one separately labelled interpretation or no
additional finding, assumptions, competing explanations, missing information and tests; no directions, horizons,
trades or observables. Sending reuses the Tracker's approval, reservation, exact-bytes and one-attempt safeguards. The
capture, its request, the hypothesis attempts, drafts, reviews and freezes are unchanged; the event history adds
research rows and three summary counts. No real request had been sent when this version was introduced (current
status: Verification under Evidence-first research analysis).

Changes in 0.5.18 (rules unchanged at 0.5.0; store schema unchanged at 4): current headlines -> persistent local
archive -> processing history. Every feed request a refresh makes leaves a write-once retrieval record
(inbox-acquisition-0.1; parser event-inbox-parser-0.1) and every accepted response is kept as received, for all five
sources; the inbox view adds each source's latest record and each entry's held texts, and a refresh reports what each
source added, reused, changed or refused. The event overview adds a processing history (event-history-0.1) and the
Inbox list a read-only processing index (event-processing-index-0.1). The source record, archive, feeds, request
headers, fingerprints, triage, capture, attempt, review and freeze records are unchanged, and a refresh still processes
nothing.

Changes in 0.5.17 (rules unchanged at 0.5.0; store schema unchanged at 4): Semiconductor policy evolution, a
source-grounded research view. policy-research-0.1 (view policy-research-view-0.1, catalog policy-research-catalog-0.1)
commits a retrospective comparison of ten BIS press releases read from the retained BIS snapshot; every quoted passage
is checked against the retained sources on each read, in memory. GET /api/research and /api/research/{id}; page
/library/research/:id, listed in the case library. Cases, enrichments, the snapshot and its index, imports, the Event
Inbox, triage, fingerprints and paid paths are unchanged; no request is made.

Changes in 0.5.16 (rules unchanged at 0.5.0; store schema unchanged at 4): Retained BIS snapshot -> preview -> explicit
Inbox import. bis-snapshot-index-0.1 (extractor bis-snapshot-extract-0.1, view bis-snapshot-view-0.1) reads the News &
Updates page retained under bis-semis-sources-01; inbox-import-0.1 adds explicitly imported records to the Event Inbox
view under "imported", apart from the feeds' entries. Feeds, refresh, triage, fingerprints, cases and enrichments are
unchanged; no request is made.

Changes in 0.5.15 (rules unchanged at 0.5.0; store schema unchanged at 4): Technology & Semiconductors Content Expansion
v1, Stage A. Case enrichments (case-enrichment-0.1, view case-enrichment-view-0.1) for two BIS cases, written from
pages retained under approval bis-semis-sources-01 and bound to the unchanged case files; GET
/api/case-library/{case}/enrichment. The 27 case files, the collection, the historical cases, Related Cases, Related
research and the Event Inbox are unchanged; no feed was added or fetched.

Changes in 0.5.14 (rules unchanged at 0.5.0; store schema unchanged at 4): WTO Trade Content Expansion v1. Case
library version case-library-0.3 (view case-library-view-0.3) with three WTO entries written from privately retained
pages (approval wto-trade-sources-01); Related research vocabulary related-research-0.2 with one topic (trade and
environment work at the WTO); raw copies of the WTO feed's complete response during explicit refreshes (inbox-raw-0.1).
The twenty-four earlier case files, Related Cases, stored matches and triage records are unchanged.

Changes in 0.5.13 (rules unchanged at 0.5.0; store schema unchanged at 4): Related research (related-research-0.1,
related-research-view-0.1): labelled navigation from an event's overview to existing case-library content, selected on
read from local records. Related Cases' rules, cases, records and IDs are unchanged.

Changes in 0.5.12 (rules unchanged at 0.5.0; store schema unchanged at 4): Related Cases
(related-cases-0.1, related-match-rules-0.1, related-match-0.1, related-cases-view-0.1,
related-match-view-0.1): two committed historical cases built from retained official pages,
listed in the case library, and one explicit local check matching an Inbox entry or capture
against them, with write-once records under data/related-cases/. No existing case, record,
rule or ID changes.

Changes in 0.5.11 (rules unchanged at 0.5.0; store schema unchanged at 4): cross-source
comparisons (g17-columns-0.1, cross-source-rules-0.1, cross-source-view-0.1), a last part
of the Findings page setting retained G.17 and EIA Table 7.6 figures side by side for the
same periods, with one write-once result under data/insights/cross-source/. The G.17 and
electricity findings' records, rules, versions and IDs are unchanged.

Changes in 0.5.10 (rules unchanged at 0.5.0; store schema unchanged at 4): electricity by
sector from retained EIA Monthly Energy Review Table 7.6 (eia-t76-extract-0.1,
electricity-rules-0.1, electricity-view-0.1), a third evidence type on the Findings page.
One explicit local action computes fixed year-over-year comparisons of residential,
commercial and industrial retail sales from the retained CSV and stores one write-once
result under data/insights/electricity/; reads verify it by recomputation.

Changes in 0.5.9 (rules unchanged at 0.5.0; store schema unchanged at 4): manufacturing
breadth in the industry findings (g17-breadth-0.1): counts of the 19 NAICS manufacturing
subsectors by printed direction for each release and month, set against Manufacturing
(NAICS), with three separate comparisons (aggregate against breadth, months within one
release, the same month across releases). Its records are written once under
data/insights/g17/breadth/ with their own definitions; no industry record or ID changes.

Changes in 0.5.8 (rules unchanged at 0.5.0; store schema unchanged at 4): industry
findings from retained G.17 releases (g17-rules-0.1, g17-view-0.1), a second evidence
type on the Findings page beside the Treasury findings. One explicit local check
validates the privately retained Table 1 and release-summary pages of the approved G.17
acquisitions and compares published monthly rates within a release (industries against
their parent or the total) and across consecutive releases (revisions of the same month);
write-once records under data/insights/g17/ only. The store, the acquisitions and every
existing record are only read.

Changes in 0.5.7 (rules unchanged at 0.5.0; store schema unchanged at 4): a Treasury
findings pilot (insight-rules-0.1, insight-view-0.1). One explicit local check measures
daily H.15 Treasury yields around retained Federal Reserve and BLS releases from the
newest kept package with deterministic, exploratory rules and fixed templates, writes
write-once records under data/insights/ only, and reuses a result whose exact
observations, date and definitions are unchanged. It is retrospective, descriptive and
separate from hypotheses, evaluations and research summaries; the store, packages and
every existing record are only read.

Changes in 0.5.6 (rules unchanged at 0.5.0; store schema 4): frozen hypotheses can be
assessed from the interface (Hypotheses): read-only outcome readiness with its states kept
apart, an explicit outcome import from a kept package, one approved download of the
Board's release package per lifecycle plan for selected hypotheses (fake transports only so
far), a write-free assessment preview with a cutoff the server derives from the inputs, and
one explicit "Evaluate and prepare Dossier" approval that records the evaluation with its
action in one transaction and prepares that assessment's Dossier. Reassessments append.
The Hypotheses list becomes a lifecycle journal, and drafts show the freezes that used
them, derived from verified freeze records. Store schema 4 adds the append-only
assessment_actions table, added to older stores only by explicit migration. Measurement
semantics, anchors, windows, placebo selection, research admission and evidence classes are
unchanged; evaluate_leg now takes its target from evaluation.scored_window, the one
definition readiness also uses, with identical results.

Changes in 0.5.5 (rules unchanged at 0.5.0; store schema 3): hypotheses can be frozen from
the interface (Hypotheses): a manual form or a reviewed H.15 model draft, an explicit local
baseline import, a write-free preview bound by its SHA-256, and one explicit approval that
the server stamps and stores with its freeze action in one transaction. Freshness policy B
now applies to every new source-bound prospective freeze. New Tracker requests use the H.15
drafting contract (draft-prompt-6); saved requests keep theirs. Store schema 3 adds the
append-only freeze_actions table, added to older stores only by explicit migration.
Anchors, windows, placebo selection, research admission and evidence classes are
unchanged, and records frozen before the policy are read and rebuilt exactly as stored.

Changes in 0.5.4 (rules unchanged at 0.5.0; store schema unchanged at 2): the Board's
H.15 release package becomes a second snapshot provider (`board-h15`), imported
locally from a kept, validated package with its own observable IDs. FRED IDs keep their
meaning, every consumer of the registry's bindings names its provider, and a leg is
never measured on another provider's data. Anchors, windows, placebo selection,
research admission and evidence classes are unchanged. The baseline-freshness question
is decided for the later freeze workflow (refusal); it is not implemented yet.

Changes in 0.5.3 (rules unchanged at 0.5.0): an offline Claude drafting adapter
turns operator event metadata and source text into a strictly validated draft for
review; it runs only on mocked transports and no command calls a model. Provider
`manual` is described as "outside the project's model adapter", not "no AI".
Baseline freshness is recorded as an open policy question; no gate changed.

Changes in 0.5.2 (adapter fred-3; rules unchanged at 0.5.0): outcome coverage is
checked against the stored classification boundary (the requested start), not the
first observation date, so a weekend or holiday publication with an outcome
requested from that date is accepted. Older snapshots without that guarantee fall
back to their first classified date.

Changes in 0.5.1 (adapter fred-2; rules unchanged at 0.5.0): snapshots classify
every expected session from the requested start, so missing leading dates are
recorded as missing; an outcome snapshot must cover the publication date or the
evaluation is refused. Readiness reports what history a snapshot gives the
scorer, and freeze refuses a baseline that cannot score every leg. Source-bound
replays are refused. This corrects an earlier claim of a fixed ~510-session
requirement, which was never enforced and does not describe this procedure.

Changes in 0.5 (rules 0.5.0, store schema 2): source-bound Treasury yield IDs
measured under a daily date convention, a documented calendar cross-check,
pinned FRED snapshots and freeze-time baseline binding (sections below). Fixture
observables, their anchors and the showcase verdicts are unchanged apart from
the rules identity. Research intake and its timestamp gate are unchanged.

Changes in 0.4 (rules 0.4.0): the equity market model is fitted before the
pre-publication event_anchor instead of the scoring anchor, so a late freeze can
never pull the event reaction into the fit. Scoring-anchor and horizon policies are
unchanged. Missing pre-event history is unavailable, never replaced by later data.
Equity evaluation records now carry the fitted window and parameters. Non-equity
records and the showcase verdicts are unchanged apart from the rules identity.
Research summaries now select exactly one rules configuration by its hash.

Changes in 0.3 (rules 0.3.0): equity anchors follow the regular-session rule
below, headline_reports_move is required, and event reference windows end at
event_anchor. The hypothesis schema_version stays 0.2 because every stored 0.2
record already carries the flag. Existing hypothesis and evaluation rows are
kept; new evaluations append under rules 0.3.0 and are never pooled with 0.2.0.

## Question and scope

Did subsequent market observations align with measurable implications of a
hypothesis frozen before the scored move?

Build a local research tool. Report evidence, uncertainty and contradictory
observations. A transmission map is a map of hypotheses, not a demonstrated
causal mechanism. Replay and prospective summaries are separate; their support
rates are not comparable when their anchor policies measure different responses.

## Immutable hypothesis

Event: headline, source URL, timezone-aware publication time.
Freeze: real frozen_at; replay also records simulated replay_as_of=published_at.
Class: prospective or replay. Usage: research or showcase. Manual story_id.
Engine: provider/model, prompt hash, schema version.
Map: event/channel/observable/explanatory nodes and acyclic edges.
Legs: 2–4 distinct observables, exactly one primary. Each specifies channel,
observable_id, direct/proxy link, expected up/down, one horizon (1/5/20),
falsifier text, rationale and a required headline_reports_move flag: whether the
headline already reports the measured move (no default; missing or null fails).
Falsifier text is explanatory in milestone 1; it is not automatically adjudicated.
The registry, not the model, owns measurement, units, benchmark and anchor policy.
A registry entry with a source is bound to exactly one provider series:
yield:ust2y_cmt and yield:ust10y_cmt are FRED DGS2 and DGS10 (H.15, source U.S.
Treasury); yield:ust2y_cmt_h15 and yield:ust10y_cmt_h15 are the Board's H.15 release
package series RIFLGFCY02_N.B and RIFLGFCY10_N.B (provider board-h15). Each consumer
of these bindings names its provider: the FRED import requests FRED's series only, the
model is offered FRED's IDs only (draft-prompt-5; another provider would need a new
prompt version), readiness reads a snapshot's own provider, and freeze and evaluation
refuse a leg whose provider differs from its baseline's or outcome's, or a hypothesis
that mixes providers. Entries without a source (yield:us2y, yield:us10y, index:dxy, ...) are
concept IDs: no provider supplies them, and they are never silently re-pointed to another
series. Two maturities of one yield curve are a lifecycle demonstration, not independent
evidence. The offline demo's FICTIONAL demonstration series, demo:rate (bp, yield_bp) and
demo:fx-index (%, return_pct), both measured from the next observation, are a separate table:
they resolve for measurement, but they are not registry entries (registry_ids), no provider
is bound to them (source_bound), and a hypothesis with usage=research cannot name them (the
schema refuses it).

## Anchors and clocks

event_anchor is the last supplied observation before publication.
Replay uses an explicit simulated freeze at publication and scores from event_anchor.
It remains subject to model-memory and data-vintage limitations.

Prospective equities/ETFs use regular-session measurement on the supplied calendar.
A freeze outside a regular session scores from the last regular-session close
strictly before the freeze. A freeze during a session, including at its close,
scores from the first regular-session close after the freeze. Every regular
session visible before the freeze therefore stays unscored. This is close-to-close
regular-session measurement: extended-hours trading before the freeze may already
have reacted. A missing observation at the anchoring close makes the leg unavailable.
Futures and all other instruments keep the conservative policy: the first
observation strictly after freeze. The event_anchor-to-score_anchor interval is
shown as unscored.

Daily date convention (anchor policy daily_ny_date, the source-bound yields):
Treasury documents quotes "at or near 3:30 PM" but no bound, so no intraday time is
claimed or used. Only America/New_York calendar dates are compared. event_anchor is
the last observation dated before the publication date, so the publication date
never enters reference history. A prospective leg scores from the first
observation dated strictly after the freeze date; a replay scores from
event_anchor. Records label this as a daily measurement convention, not a
verified timestamp; the research gate still requires observed timestamps, so
these legs cannot enter research summaries. A snapshot that does not yet contain
the scoring or horizon observation leaves the leg pending, not unavailable.

Calendar cross-check: SIFMA's recommended US bond-market schedule (via
pandas_market_calendars, version recorded) documents expected gaps; it is not
Treasury's observation or publication calendar. At import every provider date is
classified. Explained gaps leave the grid: a missing value on a SIFMA holiday, or
a case covered by a versioned exception citing issuer documentation
(market_calendar exceptions file). Everything else stays in the grid, and an
unexplained missing value, an absent session or a value on a SIFMA holiday
without such an exception is kept as missing. Horizons are never compressed.

Use supplied, verified session/settlement calendars. Do not invent business days,
ignore holidays or compress horizons around missing values. Observation timestamps
and source availability are distinct metadata that the live adapter must verify.

## Deterministic measurement

Equities and ETFs: adjusted prices and aligned SPY; estimate alpha/beta over
250 daily returns, ending 10 observations before event_anchor, whatever the
freeze time. If that pre-event history is unavailable the leg is unavailable;
later history is never substituted. Measure CAR from score_anchor: the sum of
daily asset returns minus alpha minus beta times SPY's daily return. The record
keeps the fitted window's first and last price timestamps, return count, alpha
and beta. This is relative-market evidence; it can differ from the asset's
absolute direction.

Other registry entries: percentage price/FX/index return or yield change in bp.
Futures require identified same-contract windows; unknown rolls are unavailable.
Crack spreads as research observables, their USD/barrel units and verified roll handling
wait for milestone 2. The fuels page's computed reference crack (Fuels page, below) is not an observable.

Multiply event and reference changes by the expected direction.
Use the preceding 250-session reference grid, ending at the pre-publication
event_anchor, so the event's initial reaction never becomes ordinary history.
Each reference window has the same horizon and transform. As a second guard, a
model fit must also end at or before the last observation available at effective freeze.
percentile_rank = (count(x < move) + 0.5 * count(x == move)) / n.
At least 120 usable comparison windows are required; this is availability only.

- supported: signed_move > 0 and percentile_rank >= 0.80.
- contradicted: signed_move < 0 and percentile_rank <= 0.20.
- inconclusive: otherwise.
- unavailable: insufficient/missing/unverified data, timestamps, model or calendar.
- pending: the scheduled horizon has not elapsed at the evaluation clock.
- excluded: the headline reports this measured move and the scoring and event anchors coincide.

The dossier follows its primary leg; supported plus a contradicted secondary is
mixed. Supported plus missing/pending/excluded secondary evidence is incomplete.
Other horizons may be shown descriptively later; they never change the scored label.

## Placebo and summaries

For each evaluated primary, deterministically select up to 50 evenly spaced
control anchors from the preceding calendar year, with endpoints before the
event anchor and an exclusion gap of at least h sessions. Dates are chosen by
calendar/history availability, never by favorable outcome. Each control refits
its own model, ending 10 observations before that control's own anchor, and uses
its own preceding 250-session reference.

Report selected/eligible/unavailable control counts and their measured rates.
20/60/20 is not an asserted market baseline or significance threshold.
Reference windows and control dates overlap; their count is not independent n.

Research summaries use primary legs and usage=research only. Keep evidence
classes separate. Show supported/contradicted/inconclusive rates with an explicit
eligible denominator, plus pending/excluded/unavailable coverage and story groups.
Every summary names exactly one rules configuration (64-character hash, echoed
with its version). Only evaluations under that configuration are considered,
including when picking each hypothesis's latest evaluation; an unknown hash gives
an empty summary. The stored configurations can be listed first; they are never
pooled. Repeated evaluations are not new hypotheses. Showcase cases and
superseded/post-outcome revisions cannot improve research scores, and a hypothesis with any
leg on a demonstration series never counts, whatever its recorded usage.

## Market data (FRED)

One adapter: the FRED API, series DGS2 and DGS10 for the source-bound yield IDs.
`market import` is the only network path. It runs only when invoked and reads
FRED_API_KEY from the environment; the key is sent as a request parameter only and
is never stored, logged, printed or included in an error. A missing key is refused
before any request or file is created.

Each import requests one pinned vintage for both series (realtime_start =
realtime_end = vintage date, default today in New York) and appends one snapshot
atomically, or nothing. A snapshot keeps the request without the key, gzipped raw
responses and their hashes, series metadata, the calendar identity and exceptions
version, and every date's classification. Units must be Percent and frequency daily;
a "Copyright" marker in the series notes stops the import.

Three facts stay separate. The observation date is FRED's row date. The vintage
date is the FRED real-time period requested; it is not the issuer's first
publication date, a row's realtime_start/realtime_end describe FRED's real-time
period only, and FRED may not keep past vintages for a daily series. retrieved_at
is our clock after every response arrived; it shows we possessed the values by
then, not when they first became public.

A re-import is a new snapshot. `market diff` lists dates whose stored value or
status changed or disappeared; nothing is overwritten.

Pinning: freezing a hypothesis whose legs are source-bound binds an existing
baseline snapshot in the same transaction (`freeze --baseline`). Every leg must be
source-bound, the snapshot must contain each series, and it must have been
retrieved before the freeze. The binding is append-only and cannot be changed.
Evaluation names an outcome snapshot explicitly (`evaluate --outcome`); it must be
retrieved no earlier than the baseline and no later than the evaluation clock.
Every date before the publication date (reference windows, placebo controls) comes
only from the baseline. Every date from the publication date on comes from the
outcome, so later revisions of pre-event history cannot change an evaluation. The
record names both snapshot IDs, and re-evaluating the same pair reproduces it
exactly. A bound hypothesis is skipped, with a reason, when no outcome is named. An unbound
hypothesis is evaluated against the committed demo fixture only when every leg is a
demonstration series; every other unbound one is skipped, with a reason, and no evaluation is
appended for it.
Source-bound replays are refused: a replay scores from the last date before
publication, which a baseline snapshot does not guarantee to contain.

Freshness policy B (freshness-b-1, store.check_freshness), applied by every new
source-bound prospective freeze, the commands and the interface alike: for every leg, the
baseline must classify the last expected SIFMA session before the publication date (its
recorded classification range for that series, from the classification boundary to the
last classified date, must contain it). Coverage is never inferred from acquisition or
retrieval time. A session the source states without a value is covered: it stays missing
and the readiness check still applies; nothing is filled, and reference history never
comes from outcome data. The refusal names the series, its coverage and the required
session. An existing record is never re-checked: re-freezing an identical stored
hypothesis returns it, and evaluation and preparation read stored records as they are.

Freeze helper (`freeze-draft`): accepts only manual, prospective, showcase drafts,
meaning a hypothesis without frozen_at, replay_as_of or supersedes. It stamps the
current UTC time, validates strictly, and stores the hypothesis and its baseline
binding through the ordinary append-only freeze, with every readiness, possession
and backdating check. It returns the hypothesis ID with frozen, recorded and bound
times. It never writes to the draft, and refuses a draft whose request (event,
engine, class, usage) is already frozen instead of restamping it.
Provider `manual` means the hypothesis was submitted outside the project's model
adapter; it does not mean no AI was involved. A manual draft may be AI-assisted, so
its engine model must say how it was authored and its prompt_hash must identify the
exact authoring recipe or prompt file.

Coverage: each series is classified from the requested observation_start to its
last returned row, so expected sessions a response omits at its start are
recorded as absent, never left out. The snapshot stores that boundary
(classified_from) separately from its first observation and first classified
date: a weekend or holiday at the start has no session to classify. An outcome
snapshot whose classification boundary is after the publication date is refused,
because sessions between the two would be invisible and would move the scoring
anchor and shorten the horizon. fred-2 snapshots are classified from their
requested start, and older ones fall back to their first classified date.
Coverage checks read only stored classifications; they never fetch data or
recompute a calendar. Interior
missing sessions stay missing (the leg is unavailable). Sessions after the last
returned row are not yet imported, so the leg is pending.

Readiness: storing a snapshot is not the same as having enough history to
evaluate. `market import` reports the stored snapshot and its readiness
separately, and `market readiness` (read-only) reports it for any snapshot and
publication date. Readiness runs the scorer's own reference-window and placebo
selection, under the active rules, at the event anchor an evaluation would use:
usable reference windows against min_windows, and selected and eligible placebo
controls. Freeze refuses a baseline that cannot give every leg's horizon its
required reference windows; partial placebo coverage is reported, not required.
There is no fixed session threshold. With gap-free daily history under rules
0.5.0, a leg becomes scorable from 120 + h sessions and all 50 placebo controls
become eligible from 301 + h sessions; missing values raise both numbers.

`market snapshots`, `market diff` and `market readiness` are read-only. FRED's
terms require this attribution wherever the data appears: "This product uses the
FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis."

## Market data (Board H.15 release package)

`market import-package --db --package <id> --start <date>`
(`second_order/package_snapshots.py`, adapter board-h15-package-import-0.1) copies the
two series of a kept package (see Release packages under Market context for selected
events) into one append-only store snapshot of provider `board-h15`. It reads the
package folder and writes only the store; it never fetches, validates or changes a
package, and reads (`market snapshots`, `market readiness`) never import.
- Checked first, as every read of a package is: the acquisition record against the
  folder, the package's size and SHA-256, and the validation record of the current parser
  version, which must have accepted the package and must recompute exactly; no
  observation may be dated after the day the package was requested. The start must not
  precede either series' first observation (so every expected session from it is stated)
  and must not follow their common coverage. Any refusal writes nothing; the snapshot,
  both series and every classified date are written in one transaction.
- Recorded apart: `retrieved_at` is the package's receipt time (possession, not first
  publication); `vintage_date` is null in the payload, because the package holds the
  Board's values as published when received and is not a historical vintage (the store's
  NOT NULL column holds the token `none`, never a date); `created_at` is when the
  snapshot was built; the data entry header's prepared time is kept exactly as stated
  (`prepared_as_stated`), names no time zone and is neither an observation nor a
  possession time. The payload also holds the package's ID, address, request time, size
  and SHA-256, the acquisition record's SHA-256, the validation record's version,
  parser, time, SHA-256 and rows SHA-256, the series' identifiers, attributes,
  descriptions and units, each series' package coverage and copied range, the calendar
  identity and the status counts.
- Observations are TIME_PERIOD dates (daily date convention, as for FRED). Each row keeps
  its exact decimal text or ND (`raw_value`); FRED's real-time columns stay null. Every
  date from the start to each series' last row is classified by `market_calendar`, with
  the calendar exceptions matched through the series' FRED crosswalk IDs as
  `event_context` matches them. Nothing is interpolated or filled. Each series' copied
  rows are also stored gzipped with their SHA-256, so the snapshot stands without the
  package folder.
- An import key (adapter, package ID and SHA-256, validation record SHA-256, parser
  version, start and calendar identity) is stored in the payload: repeating the same
  import returns the stored snapshot and writes nothing. Another package, even with
  identical bytes, is another acquisition and a separate snapshot.
- Store Dossiers of a `board-h15` case name the Board as provider and source, show no
  vintage ("None: no historical vintage") and caption each chart with the package's
  receipt date. FRED's views are unchanged.

## Persistence and actions

SQLite append-only hypotheses and evaluation rows. Changes create versions.
Store schema 2 adds append-only market snapshot and freeze-binding tables; schema 3 adds
the append-only freeze_actions table (action_id = the approved preview's SHA-256,
hypothesis_id unique, recorded_at, payload: the approval's binding, effective content
SHA-256, freshness and readiness reports and scoring window); schema 4 adds the append-only
assessment_actions table (action_id = the approved assessment preview's SHA-256,
hypothesis_id, evaluation_id unique, recorded_at, payload: the approval's binding and
approval), written in its evaluation's transaction (store.record_assessment). A new store
is created at schema 4. Write commands accept schema 2, 3 or 4; an interface freeze needs
schema 3 or 4 and an interface assessment schema 4. A store is upgraded only by the
explicit `store migrate` command (or the interface's explicit upgrade action): one
transaction that adds tables (schema 1 gains those of schemas 2 to 4, schema 2 gains
freeze_actions and assessment_actions, schema 3 gains assessment_actions) and proves every
existing row unchanged; store_meta keeps its earlier rows and gains the migration's own.
Read commands accept schemas 1 to 4 read-only and never migrate. Foreign databases are
refused by every path.
Hash the event date with input/engine provenance. Evaluation records include rule
configuration/hash, data hash, anchors, reference endpoint and the evaluation clock.
GET/read paths never fetch providers. Model calls are explicit billed actions;
the Tracker's paid path shows the cost decision before submitting a call.
Every HTTP route, static client files included, rejects a foreign, missing or malformed
Host before reading records. Plain reads need no Origin or action header; explicit
writes retain their additional same-origin JSON checks.

## Prepared Dossier views

`prepare` is the explicit step that writes Dossier views; GET routes only read the
prepared files. Fixture showcases, two fictional events, are evaluated offline from the
committed FICTIONAL demonstration series: fixtures/demo-market.json (demo-market-0.1), whose
every number second_order/demo_market.py invents (a test checks that the committed file equals
its output byte for byte; its timestamp basis is fictional_daily, never observed). Their views
carry the limitation "Fictional demonstration data", and each series caption names the
provider fictional-demo and the generator version.
`prepare --db` also reads the frozen, baseline-bound store cases through a
read-only connection, so the store is never written or migrated:
- A case with no stored evaluation is shown as "Not yet evaluated", with no
  evaluation, chart or reference distribution.
- A stored evaluation is authoritative: it is never rescored under the current
  rules and never re-pointed at a newer snapshot. If a case has several stored
  evaluations, one must be chosen (`--evaluation HYPOTHESIS=EVALUATION`) or
  preparation fails.
- The chart and reference distribution are rebuilt only from the pinned baseline
  and outcome snapshots, the recorded rules and the recorded evaluation clock. The
  rebuilt evaluation must equal the stored one exactly, or preparation fails and
  writes nothing.
- Views show baseline and outcome snapshot IDs, vintage dates and retrieval times,
  the recorded rules, the daily measurement convention, FRED observations as New
  York dates, and FRED's attribution.
Manual prospective cases are labelled as such, and the retrospective and fixture
caveats do not apply to them. View version: dossier-view-0.3 (0.3 changed only the fixture
showcases' series provenance, limitation and captions; a store case's view is as in 0.2).
A prepared folder written at 0.2 is refused by the client ("This client reads
dossier-view-0.3; …") until `prepare` rewrites it.

Per-assessment preparation (assessment_records.prepare_dossier, lifecycle-dossier-0.1)
builds the same store view for exactly one hypothesis and one of its stored evaluations,
with the same exact-reproduction check, and writes it once to
`<store stem>-dossiers/<hypothesis id>/<evaluation id>.json` beside the store (with the
view's SHA-256, the preparation time and its assessment action, if any); it never
rewrites that file, `data/prepared` or any other view, and records nothing in the store.
Reading it (GET) checks the file's fingerprint and identities and that its evaluation
equals the stored one (a file prepared at dossier-view-0.2 is still read, since the store
view is unchanged in 0.3; any other view version is a problem and is not shown), and
reports, separately, whether each pinned snapshot still verifies in the store
(snapshots.verify_snapshot) and whether its raw source file is held here; a snapshot's
observations are copied in the store, so it does not need the package folder. Reads never
evaluate, import, prepare or fetch.

The client refuses an internally inconsistent view rather than repairing it: a drawn
series or ranking before evaluation, a missing leg result, or a daily-date series
without its recorded New York anchor dates. Its tests read store-backed views
captured from the real preparation (`frontend/tests/fixtures/`); a backend test
fails when those captures drift from what `prepare` produces.

## Model drafting adapter (offline)

`second_order/model_draft.py` turns an operator's event (headline, source URL,
publication time, story_id) and source text into a hypothesis draft for review.
- Request (Claude Opus 5.5 migration guide): forced tool choice is rejected, so the
  request offers one tool, `submit_hypothesis_draft`, with `strict: true` and
  tool_choice `auto`, and sets effort explicitly (`output_config.effort`, medium).
  Drafting is conditional (prompt draft-prompt-5): the model calls the tool once, with
  no other text, only when the source text is sufficient and the event has a defensible
  connection to the offered observables; otherwise it may decline in a few sentences
  without calling the tool. A decline is the existing no-draft outcome: nothing is read
  from its prose and no draft is produced. Since draft-prompt-4 the prompt also says that
  a yield responding to a channel is a proxy for it, not a direct measure; that legs may
  use different horizons but move sizes are not compared across legs without support;
  that a forecaster survey is not market pricing; that each competing influence needs its
  channel and direction; and that unrelated news in the scored window belongs among the
  uncertainties. Draft-prompt-5 adds that legs may point in different directions, which is
  not a size comparison, though each direction needs its own rationale; that uncertainty
  alone is no reason to decline, while a missing or invented connection is; that unknown
  market pricing stays unknown; and that influences said to push either way need each
  one's channel and direction explained. These are instructions reviewed by a person, not
  structural checks. It sends no thinking or sampling fields; thinking is
  always on, and max_tokens (16,000) covers thinking plus the call. The tool schema
  omits keywords strict tool use rejects (string lengths, maxItems, minItems above 1);
  the prompt states those limits and the adapter enforces them after receipt.
- Ownership: the model supplies only the summary, nodes, edges and legs. Code sets the
  evidence class and usage (prospective, showcase) and the engine record: provider,
  the model that answered (exactly the requested ID), and prompt_hash, the SHA-256 of
  the exact canonical request body. A draft carries no freeze time.
- Observables: only registry entries with a prospective data path (DGS2, DGS10) are
  offered, as an enum in the tool schema. Observable nodes are the measured
  implications; channel and explanatory nodes are unscored and never have legs.
- Strictness: the response must be valid JSON with no repeated keys or non-standard
  constants, and its envelope fields must have their documented types (id, model and
  stop_reason strings, content a list). It must stop for the tool call and hold exactly
  one call of the draft tool; documented thinking and redacted_thinking blocks may
  accompany it, and any other block, text included, refuses the draft: no JSON is read
  from prose. Horizons must be the JSON integers 1, 5 or 20 (true and 5.0 are
  refused). The call input is validated in strict mode (no coercion or case folding;
  fields such as event or frozen_at are refused), then the composed draft is validated
  as a hypothesis frozen now. Any failure, including a refusal stop reason or a
  provider error, refuses the draft; nothing is repaired, retried or substituted.
- Credentials: every provider response, success or error, is checked for the API key,
  raw or JSON-escaped, before any field is read or quoted.
- Operator input is checked before any request: a publication time in the future is
  refused, and source text over 50,000 characters is refused, never truncated.
- Offline: the `model-draft` command never creates an HTTP client. It prints the exact
  request (`--print-request`) or validates a saved response (`--response`), recorded
  with provider `offline-replay` because its origin and its pairing with the request
  cannot be verified. The send function itself is not intrinsically offline: given a
  real HTTP client and key it would make a billed request. Only the pilot below passes
  one, and tests pass mocked transports.
  The freeze helper (`freeze-draft`) accepts manual drafts only; the lower-level
  `freeze` command does not check the provider, so it is not a gate against freezing a
  model hypothesis by hand. The interface freeze (below) accepts only eligible reviewed
  model drafts.
- Contracts (CONTRACTS): a prompt version names the provider whose source-bound IDs the
  request offers. draft-prompt-5 offers the FRED IDs and remains the adapter's default and
  the pilot's contract. draft-prompt-6 has draft-prompt-5's instructions word for word and
  offers the Board's H.15 IDs; the Tracker builds new requests under it. A saved request
  keeps its contract: verification never compares it with today's, the mock and paid paths
  read the offered IDs from the saved request, and nothing is rebuilt or remapped.
- Live pilot (`second_order/draft_pilot.py`): the only command that can send a model
  request. It runs synthetic review cases on Claude Sonnet 5.5, named by the pilot; the
  adapter's default model is unchanged. Each run has its own identity, directory and
  cases and is bound to one prompt version: pilot-1 (draft-prompt-3) and pilot-2
  (draft-prompt-4) covered clear-policy and insufficient-source and are complete, their
  records and an archived 401 attempt kept unchanged; pilot-3 covered the six other
  cases under draft-prompt-4 and is complete; pilot-4 reruns conflicting-labor-inflation,
  ambiguous-wording and headline-reports-move under draft-prompt-5 and refuses any other
  prompt version. Its case texts and prompt both changed since pilot-3, so a comparison
  cannot isolate the prompt's effect.
  `preview` prints the exact request, its hash and a cost estimate and sends nothing.
  `send` needs the key in SECOND_ORDER_ANTHROPIC_API_KEY and the previewed prompt hash,
  the SHA-256 of the exact canonical request body. The hash does not cover the code; the
  code identity (file hashes, git commit) is captured once before sending and kept with
  the reservation, and the final manifest repeats that captured identity.
  Before sending, the case is reserved by an atomic exclusive directory create that code
  never releases, so each case is attempted at most once, also after a timeout or crash.
  One attempt (no retry, no fallback, a 10-minute timeout). The exact request bytes, the
  exact response bytes after the credential check and a provenance manifest are kept
  under `data/pilot/` (git-ignored); nothing is frozen and no database is opened. Two
  synthetic cases establish neither forecasting accuracy nor model performance.

## Draft review views (offline)

`prepare-drafts --attempt <dir>` is the explicit step that turns selected saved pilot
attempts into read-only review views (view version draft-review-view-0.1), written to
`data/prepared-drafts/` (git-ignored); `/api/drafts` and `/api/drafts/{id}` only read
them, whether or not Dossiers are prepared.
- Ownership: `prepare-drafts` owns `data/prepared-drafts/` and replaces its index with
  exactly the views it is given. The Tracker (mock and paid attempts) owns
  `data/tracker-drafts/` beside it: each view is one file, written under a unique
  temporary name and linked into place exclusively, never replaced; that folder has
  no index file. Reads list
  and serve both folders. An ID present in both is served only if the two files are
  byte-identical; otherwise it is reported as inconsistent. Both folders serialize a
  view identically, so its fingerprint and any review bound to it do not depend on
  where it is stored.
- Records: only the attempt's original request.json, response.json and manifest.json
  (with reservation.json). The request bytes must match the recorded prompt hash, the
  response bytes the recorded response hash, the reservation the manifest, and the
  outcome re-derived through the adapter's strict validation the recorded outcome. The
  source is read from the recorded request's single user message; an ambiguous
  extraction, a missing record or any mismatch refuses the whole preparation and
  writes nothing. Inputs are never rebuilt from current fixtures or the current prompt.
- Exposure: the source (untrusted, shown as plain text), the public draft or the
  model's public decline text, and selected provenance (run, case, model, effort,
  max_tokens, prompt version and hash, request ID, timestamps, HTTP status, response
  hash). Thinking and redacted thinking, the system prompt, headers, credentials and
  raw records are never included; a credential-like string refuses the view.
- Outcomes: draft, no draft (a decline or refusal), invalid response and technical
  failure are distinct. A view has no freeze time, evaluation, chart or ranking; its
  map is labelled as proposed. Every view is labelled "Not frozen · Requires human
  review" and comes with a generic review checklist; nothing is approved or scored, a
  structural check does not verify reasoning, and only an explicit human review save
  (below) records anything.

## Tracker attempts: local mock and one paid request

A captured event gets at most one attempt under `data/tracker-attempts/<capture>/`
(git-ignored), whether mock or paid; the attempt folder is the reservation, created
exclusively and never released by code.
- Contract: new captures are built under draft-prompt-6 (H.15 IDs); captures saved
  earlier keep draft-prompt-5 (FRED IDs), and both remain attemptable.
- Mock (the default; run tracker-mock-1): a deterministic local fixture, recorded as
  synthetic with no HTTP status, request ID or provider cost, and labelled in review
  as generated by a local mock. Its legs use the maturity pair the saved request offers.
- Paid (run tracker-live-1): available only when `serve --enable-paid-drafts` builds a
  sender from `SECOND_ORDER_ANTHROPIC_API_KEY`. POST `/api/intake/{capture}/paid-drafts`
  requires the saved request's SHA-256, `approve_paid_request: true` and the planning
  estimate the preview showed. Configuration, key shape, approval, capture verification,
  model (claude-sonnet-5-5) and the absence of the key in the request are all checked
  before the reservation. The reservation, request bytes and a "sending" record are
  written before the provider is contacted. One POST to the Messages API carries
  exactly the saved bytes, with no retry, redirect, fallback or second call.
- Recorded as received: response bytes (after the credential check), HTTP status,
  `request-id`, usage and a usage-based cost when usage is reported. An error body is
  not kept, and no file may contain the key. A transport error after sending is an
  unknown outcome that may have been billed. Every outcome is published for review
  (a draft, a decline, an invalid response or a technical failure); none is frozen,
  evaluated or scored.
- Preview (the capture response and `GET /api/intake/{capture}`): `provider_called`
  is false, as for every action that sends nothing. `modes` alone states what the
  server offers (`mock` always; `paid` only when enabled), and an offered mode is not
  an approval. A preview never dispatches, reserves or rewrites anything.
- Resuming: the Tracker lists captures (`GET /api/intake`) and reopens one, or
  refreshes the one shown, with two reads only: the preview, then the attempt state. A
  refresh refuses a request hash other than the one shown. Both clear approvals and
  select the mock. Approval needs a verified preview and an attempt state of "none".
  An unreadable or invalid state blocks it, as does a failed refresh, which leaves the
  old preview marked stale. A reply to a superseded selection is ignored.
- Reads (`GET /api/intake/{capture}/attempt`) never send. They distinguish a paid
  attempt reserved but not sent from one sent without a recorded response. Recovery
  (`POST /api/intake/{capture}/publish`) uses only the saved records.
- Verification: the paid path has been exercised only through an injected fake
  transport with a dummy key, and through the production client (`live_client`,
  unchanged) over an in-process network backend: one connection attempt with no
  retry, and a 307 to any host not followed and recorded as a provider error. No real
  request has been sent from the Tracker, so the real API's acceptance of these bytes,
  authentication, network and timeout behavior, response formats and billed usage are
  unverified. A first real single-event trial is a separate, explicitly approved step.

## Evidence-first research analysis (saved events)

`second_order/research_analysis.py` and `research_analysis_api.py`; page `/events/capture/:id/research`. A second
analysis mode beside the market-hypothesis draft, chosen explicitly: the Tracker's saved-event preview offers an
"Analysis mode" (the hypothesis draft, unchanged, is the default; the research analysis links to its own page), and the
event overview links to it. Nothing is prepared, sent or saved on load.

- Request (research-request-0.1): `POST /api/research-analyses {"capture_id"}` prepares, once per capture and prompt
  version, `data/research-analyses/requests/<capture>.<prompt version>/` with `request.json` (canonical bytes) and
  `manifest.json`, staged and renamed into place, read-only, never overwritten; preparing again returns the saved one.
  The manifest binds the capture's own request and source SHA-256s and byte count, its event fields and its recorded
  Inbox origin (the link file's SHA-256, entry ID, version and fingerprint) or that it has none; an origin record that
  does not verify refuses preparation. Every read re-verifies the request's bytes, the capture, the read-back of its
  event and captured text from the user message, and the origin binding (a changed or newly appearing link refuses
  it). The capture and its saved hypothesis request are only read.
- Prompt: claude-sonnet-5-5, effort medium, max_tokens 16,000, the capture's framing (headline, source URL, UTC
  publication time, `<source_text>`). research-prompt-2 (since 2026-10-26, research_requests.py) asks for the analysis
  as the response itself in the JSON output format (`output_config.format`, type json_schema) and offers no tool; the
  reply must be exactly one JSON document in one text block beside thinking blocks, read with a strict parser and never
  extracted from prose, and a source that supports no analysis says so as no_additional_finding (no prose decline; a
  provider refusal stays a decline). Its manifest names `format: json_schema` where research-prompt-1's names the
  tool. research-prompt-1 (one strict tool submit_research_analysis, tool_choice auto) is kept byte for byte, and its
  saved requests and results read under it; both of its live replies of 2026-10-26 broke the strict schema in the
  tool-call layer (docs/news-mvp-closure.md (private; not in the public repository)). The schema is identical under both. The reply supplies: established
  statements (1–10; basis action, data, assessment or forecast; 1–2 exact quotes of 8–400 characters each); one
  interpretation (kind finding with the statements it relies on, or no_additional_finding, an acceptable result);
  assumptions, competing explanations, missing information and tests (up to 6 each). No direction, horizon, forecast,
  trade or observable field exists. The source is untrusted data; no memory of other documents or later events; no
  earlier baseline is supplied, so no comparison is made; the analysis is retrospective, not an out-of-sample test; a
  publisher's forecast stays an attributed forecast. Limits that structured outputs cannot carry are enforced on receipt.
- Cost: the Tracker's planning estimate for the saved bytes at max_tokens (under research-prompt-2 with an assumed
  1,000 tokens for the JSON output format's unpublished system prompt in place of the tool-use one), plus this mode's
  output-limit assumption
  (the reply's limits hold its text to at most 27,900 characters; the rest is thinking headroom). Not a billing ceiling.
- Sending: one attempt per research request, ever, mock or paid, reserved exclusively under
  `data/research-analyses/attempts/<request>/` (reservation, exact request copy, a "sending" record before contacting
  the provider, the response after the credential check, the manifest last). Mock (`POST …/{request}/mock`,
  research-mock-1): deterministic synthetic content quoting the captured text, $0, labelled synthetic. Paid
  (`POST …/{request}/paid`, research-live-1): only on a server started with `--enable-paid-drafts`; the approval names
  the request SHA-256, `approve_paid_request: true` and the previewed estimate; key shape, approval, verification and
  the key's absence from the request are checked before the reservation; exactly the saved bytes are posted once
  through the pilot client (no retry, redirect, fallback or regeneration). Nothing is frozen or evaluated.
- Result (research-result-view-0.1, built on every read from the attempt's files; never stored): outcomes analysis,
  no_additional_finding, declined (no tool call, or a refusal stop; its prose is shown as the model's own words),
  incomplete (max_tokens, context window, pause), invalid (any contract break: envelope, model, blocks, schema,
  numbering or an unresolved quote) or technical_failure (provider error, transport error that may have been billed,
  credential echo). Every quote is located in the captured text by code (exactly, or after making quotation marks,
  dashes and whitespace plain) with paragraph numbers and code-point offsets, and the source's own wording is shown; a
  single unresolved quote refuses the whole reply. The outcome is recomputed from the response bytes and must equal the
  recorded one. The client re-checks each locator against the captured text the request carries.
- Reviews (research-review-0.1): `POST …/{request}/reviews` appends `data/research-analyses/reviews/<request>/NNNNNN.json`
  (status null, needs_revision or human_reviewed; notes), following the latest version and bound to the result view's
  SHA-256, the request and response hashes; history verified by numbering, parent chain and content ID.
- Reads: `GET /api/research-analyses?capture_id=` and `GET /api/research-analyses/{request}` never send or write.
  The event history (event-history-0.1) adds research rows (prepared, outcome, uncertain or unverifiable attempts,
  review versions) and the summary counts research_requests, research_results and research_reviews; `reviews` and
  `drafts` still count hypothesis drafts only.
- Verification: automated tests use fake transports and synthetic records only; simulated replies verify the
  workflow, not the quality of a model's analysis. Separately, one approved retrospective pilot on a single saved event
  has sent a real research request through the paid path (one attempt, no retry) and recorded the response and a human
  review. The reply was accepted as an analysis: it met the contract (structure, and every quote located in the
  captured text). The latest review status is needs_revision. This is not evidence of general model quality,
  forecasting performance, mechanism confirmation or verified billing.

## Market-implied rate path (saved FOMC statements, private, descriptive)

`second_order/rate_workbook.py`, `rate_context.py` and `rate_context_api.py`; a panel on `/events/capture/:id` and
`/events/capture/:id/research`. Context for a saved Federal Reserve monetary-policy press release from the Atlanta Fed
Market Probability Tracker's historical workbook (estimated from CME 3-month SOFR options): a separate event record,
never part of a model request, never frozen, evaluated or scored.

- Source (rate-source-acquisition-0.1, rate-source-validation-0.1): `python -m second_order rate-context retain
  --workbook --sha256 --obtained-on --method` keeps a workbook the operator already holds and never downloads one. The
  file must match the named SHA-256 and pass the reader; `data/rate-context/sources/mpt-<16 hex>/` then holds its exact
  bytes, the acquisition record (HTTP status, headers, server time and publication time recorded as unknown; the date
  obtained and the method as the operator states them, the date not before the last observation) and the validation
  record (license paragraphs, the dictionary's description and definitions, header, row count, every observation
  date), staged and renamed into place, read-only. Retaining the same file with another statement is refused.
- Reader (mpt-workbook-parser-0.1): the H.15 package's archive safeguards and protected expat parsing (no DTD, entity
  or external reference). Sheets exactly LICENSE, DICTIONARY, DATA; the 1900 date system. The LICENSE text box's
  paragraphs (runs joined at the drawing's paragraph boundaries) must include the Atlanta Fed's use statement. The
  dictionary's description and the definitions of date, reference_start, target_range, field, value, Rate: mean, Rate:
  25th percentile, Rate: 75th percentile, Prob: cut and Prob: hike must equal the pinned wording; a name defined twice
  must agree. DATA starts with exactly the header; every row has a YYYY-MM-DD observation date, a whole date serial in a
  built-in date format, a target range "<n>bps - <m>bps" with n ≤ m, a statistic name and a plain decimal (no exponent,
  "+", NaN or infinity); no observation, reference start and statistic repeats. Any failure refuses the workbook.
- Context (rate-path-context-0.1): `rate-context prepare --capture <id> [--source <id>]` writes
  `data/rate-context/events/capture-<id>/<n>.json`, created once and read-only, only for a capture whose official link
  is a Federal Reserve monetary-policy press release. It binds the capture (request and source SHA-256, event fields,
  supplied publication time and its New York date), its recorded Inbox origin (link SHA-256, entry, version) or that it
  has none, and the source (workbook and validation-record SHA-256, parser version). Rule
  latest-observation-before-publication-date-1: the latest observation strictly before the publication's New York date,
  never one dated that day (the workbook's dates carry no time of day), and only when the workbook also holds an
  observation on or after it; otherwise no_coverage (none_before or none_on_or_after). The windows are the first four
  the workbook lists for that observation, by start date and labelled as it labels them, each with its Rate: mean, 25th
  and 75th percentile rows (row numbers and exact text); a statistic not listed stays null and no later window moves up.
  The observation's rows must state one target range, and the 25th percentile may not exceed the 75th. Cut and hike
  probabilities are never kept. Preparing again re-derives from the workbook: an identical result writes nothing, a
  difference under the same workbook is refused, and another workbook makes the next version.
- View (rate-path-view-0.1): `GET /api/rate-context/capture/{id}` (also `rate-context show`) never fetches, prepares or
  writes. States: unsupported, not_prepared, unreadable (with the problem; no value shown), no_coverage and available.
  Every read checks the workbook's bytes against their SHA-256, the acquisition and validation records, the capture and
  origin bindings, the selection against the recorded observation dates and every value's form; it does not parse the
  workbook again (preparing again does). Percent is the exact two-place decimal shift of basis points, never rounded.
  Meeting-specific pricing is always unavailable. The limits say that window dates are not meeting dates, average SOFR
  is not the target range, no decision probability or surprise measure is derived, and the workbook was obtained after
  the event without a time of day, publication time or vintage. The panel stays apart from Market context's Treasury
  yields; on the research page it says the analysis's request did not carry it and when it was prepared relative to
  the send. The client refuses a reply whose percents, selection, window order or count, provenance or meeting state
  break these rules.
- Verification: synthetic workbooks (tests/rate_fakes.py) in tests and the browser check. The retained workbook and
  derived records stay under data/, ignored by git; the workbook's license permits personal and educational use only.

## Accounts, credits and daily limits (user research analyses)

`second_order/accounts.py`, `registration.py`, `entitlements.py`, `credit_terms.py`, `auth.py`, `user_research.py`,
`user_api.py`, `onboarding_api.py`, `admin_api.py`, `admin_views.py`; the API contracts are docs/admin-user-contract.md
(user-api-0.3 for the Client, admin-api-0.2 for the Admin screens at `/admin`), docs/onboarding-contract.md
(onboarding-api-0.1 for the public pages), docs/news-usage-contract.md (user-api-0.4 and admin-api-0.3: news,
interests, search, publication import and usage limits; `news_api.py`, `usage.py`) and
docs/account-binding-contract.md (every user and administrator write
names the account its page was opened for; a request bound to another account than the session's is refused, 401
account_changed, before any route runs, and an unbound write 428 account_binding_required). No payment, purchase, e-mail or hosting; the server applies no grant, limit
or rate by itself: the operator's selected pilot terms are presets an administrator chooses explicitly (below).

- Store (accounts-3): one SQLite file beside the research data, separate from the research store, created only by
  `python -m second_order accounts add-admin --username NAME` (password typed at a prompt); an accounts-1 or accounts-2
  store is upgraded only by `python -m second_order accounts upgrade`, which adds the registration tables (to an
  accounts-1 store) and the publications, usage policies, usage events and news interests (all empty), keeping every
  row. A credit-policy publication carries an idempotency key bound to the administrator and the canonical payload:
  repeating it publishes nothing more, and any other use of the key is refused (409 idempotency_conflict). Every write is one
  `BEGIN IMMEDIATE` transaction, so tabs, threads and server processes are serialized; triggers make ownership,
  settings, policies, limits, quotes, attempts, sends, outcomes, resolutions and the ledger append-only, refuse a
  resolution above the reserved credits and require a return to release the daily slot. `serve` refuses to start
  without the store and never creates it.
- Identity: scrypt password hashes; random session tokens stored only as SHA-256; an HttpOnly, SameSite=Strict cookie;
  sessions end at sign-out, deactivation or after 12 hours. The role always comes from the store. Every API route is
  admin-only unless it is a session route (public) or `/api/user/*` (user); refusals of the access check use the user
  contract's error shape. The local Host, same-origin and custom-header checks are unchanged. A server built in code
  without the store (unit tests, the existing browser checks' launcher) is the local operator's, as before.
- Registration: `POST /api/public/registrations` (exactly username, display name, password and note; this page's
  Origin and session header) makes an inactive `user` row and a registrations row, nothing else; forged fields refuse
  the body, every taken or reserved name gets one `username_unavailable`, and the same username and password again is
  a duplicate. Statuses: pending, rejected, active, disabled. A pending or rejected registration cannot sign in; the
  right password answers `registration_pending`/`registration_rejected` with its own status (never the admin's
  reason). One admin decision per registration (registration_decisions' primary key; a second, concurrent or not, is
  `already_decided`); approval sets the account active and nothing else. Triggers refuse activation without an
  approval, a role change, and any ledger entry, daily limit, record owner, quote or attempt for an unapproved
  registration; the status action on one is `not_approved`.
- Source: `POST /api/user/sources` takes exactly headline (1 to 1,500 characters), source URL (at most 2,083),
  publication time (explicit offset) and text (at most 50,000 characters in any script, never truncated). Limits count
  characters; the body is read up to 270,000 bytes, which every form within them fits as a browser sends it (four
  bytes for a character at most). An unpaired surrogate escape is refused, as on the Tracker form.
- Ownership: a capture a user adds is theirs (record_owners). Captures without an owner row, and every existing record,
  stay the operator's; an admin may assign one capture to one user, once, with a reason. A record of another account
  answers exactly like a missing one.
- Effort: claude-sonnet-5-5 accepts low, medium, high, xhigh and max (verified from the provider's documentation, no
  live request); an admin policy enables a subset. A user's request is research-request-0.2,
  `<capture>.<prompt version>.<effort>` (research-prompt-2 since 2026-10-26), prepared once and immutable, identical
  to the operator's request under the same prompt version except
  `output_config.effort`, its manifest naming the preparing account. Changing Effort prepares another request. There is
  no fallback level or model. Operator routes refuse to mock, send or review a user's request.
- Policy and quotes: an admin policy version (credit-policy-N) names the model, the enabled levels with whole-number
  extra credits, the rates `base` (at least 1), `per_1k_input_tokens`, `per_1k_output_tokens`, the admin's per-request
  planning-estimate limit and the quote validity; settlement is "quoted". `credits = base + ceil(input_tokens_assumed /
  1000) * per_1k_input_tokens + ceil(16000 / 1000) * per_1k_output_tokens + extra_credits`, with the existing planning
  estimate's input count for the exact saved bytes. A quote binds user, request and its SHA-256, Effort, policy
  version, credits and expiry; a new policy version supersedes every earlier quote.
- Run: the approval repeats the quote's ID, Effort and credits with `approve: true`. One transaction rechecks the quote,
  policy, Effort, account, daily limit (count of unreleased attempts on the quota day in the configured zone, initially
  Asia/Jerusalem; day boundaries from the time zone database) and balance, then inserts the attempt (unique per request
  and per quote) and a hold of the quoted credits. A repeated approval returns that attempt. The send is recorded in the
  store before the transport is called (an attempt resolved first is never sent), then the existing send core reserves
  the attempt folder and posts the exact saved bytes once, recording the account in the reservation and manifest.
- Settlement: a recorded response of any outcome charges the quoted credits once; a run its own worker sees as never
  sent returns its credits and daily slot once; a provider or transport error, or a send without a recorded outcome,
  keeps its hold until an admin charges 0 to the quoted credits or returns them, once, with a reason. Nothing is
  refunded, cleared or retried automatically, and a new day releases nothing. The ledger reconciles: granted +
  corrections - charged - held = available.
- Execution lock (attempt_locks): the worker holds an operating-system file lock per attempt from before its send is
  recorded until it is settled; a process that ends releases it. An admin resolution takes the same lock, then rechecks
  in one write transaction that the attempt is unresolved, in the state the admin saw (send start and outcome) and has
  an outcome or is at least 15 minutes old; refusals report the actual state (already_resolved, state_changed,
  in_flight). Age alone never authorizes a refund; a returned or charged attempt is never sent. Runs use their own
  threads, so long sends never hold the threads other requests need.
- Credit terms: one credit is one point of application usage, with no money value. `GET /api/public/credit-terms`
  gives the active policy's version, offered Effort, quote validity, a size note and three SYNTHETIC examples (2,000,
  12,000 and 48,000 characters of plain text) quoted at each offered Effort by the same event construction, request,
  planning-estimate input count and formula a real quote uses, or the state no_credit_policy / no_effort_enabled.
  Size is the saved request's UTF-8 bytes (2 per assumed token), so other scripts need more points per character.
  `POST /api/admin/policy/preview` checks a draft exactly as a new version and returns the same examples with the
  admin-only planning estimate and whether the per-request limit refuses each; it records nothing.
- Presets: `GET /api/admin/policy` lists `presets` (the selected pilot terms: credits base 10, per_1k_input_tokens 0,
  per_1k_output_tokens 0, Effort extras 0/5/10/15/20) and `GET /api/admin/users` lists `allocation_presets` (100 credits,
  daily limit 3) and each user's `allocated`. A preset carries no model, quote validity or `max_request_usd` (none was
  selected; the field stays required). The Policy screen fills a draft from it, keeping the active version's limit and
  validity or leaving them empty; Users fills the credit and limit forms of an approved account with nothing allocated;
  each form is still its own POST, and a saved one is not filled again. Reads, startup, registration and approval apply
  nothing; nothing refills.
- Account: `analysis.reason` is the first applicable of sending_disabled, no_credit_policy, no_effort_enabled,
  no_daily_limit, no_credits_allocated (no grant or correction ever recorded) and no_credits_available, and
  `analysis.reasons` lists them all.
- Usage limits (usage-policy-N, `usage.py`): one server-wide, append-only policy of whole numbers the administrator
  types (per account: searches, imports, new sources and preparations per quota day, sources and source bytes held,
  requests per minute and in progress; per server: publication fetches and feed refreshes per quota day, refresh
  cooldown seconds), published once per idempotency key. Without one, news, interests, searches, imports, new sources
  and preparations are refused (no_usage_policy) and the feed refresh is refused. Each counted request reserves its
  usage event (and storage check, under a per-account lock) in one write transaction before it writes or requests
  anything and records a release row if it then writes nothing new, so concurrent requests at a limit never both pass;
  reopening an analysis is free. The protective limits live in the process's memory and answer 429 with a wait.
  Admin: `GET`/`POST /api/admin/usage-policy`, `GET /api/admin/usage` (today's counts per account and the server's
  budgets; local counts, not billing).
- News and research checks (the data owner's modules, `user_news.py`, `publication_import.py`, `research_quality.py`):
  user news (user-news-view-0.1) is a read-only projection of the operator's Event Inbox cache for approved users, with
  deterministic interests (news-interests-0.1) and a cache-only search; nothing on read or search contacts a publisher.
  Publication import (publication-import-0.1, publication-retrieval-0.1) reads one allowlisted Federal Reserve
  press-release page per explicit import, at most once per server, keeps its bytes, extracts the release's words
  (fed-press-release-extract-0.1) and saves them as the user's source only on confirmation of that exact text, with the
  entry version as its Inbox origin. The research-quality rubric (research-quality-0.3, computed on read) flags lexical
  mismatches between statements and their quotes for a person to look at; it rejects nothing, gives no score and is
  separate from results, reviews and evaluations.
- Quota zone: each run keeps its recorded quota day and zone; the zone may change only before the first run or usage
  event (a later change is refused in the reservations' transaction). User credit text follows the recorded resolution, and
  "sending disabled" means only the server's sending configuration.
- Projections: user payloads carry no model or provider name, money, token count, provider ID, request or response
  bytes, provider HTTP status or log; the Client's readers refuse any payload that does. Admin payloads add the actions
  view: per research request (operator and user) its type (local preparation, $0 mock, provider call), account, model,
  Effort, state, locally measured times with unavailable components named, reported usage, the planning estimate and
  the usage-derived cost (a local calculation, never verified billing; missing stays null). Reads, reviews and exports
  consume nothing. These limits govern this application, not a verified billing ceiling.
- Verification: unittest with synthetic accounts and a fake provider (roles on every route, ownership, projections,
  tampering, expiry, policy changes, thread and process races at the credit and daily boundaries, restarts, unsent and
  uncertain sends, idempotent resolutions, DST days), a check that real server payloads match the published contract
  fixtures and pass the Client's readers, and the admin browser check. No real request was sent. Registration
  (unittest): lifecycle, forged fields, duplicate and concurrent signups and decisions, restart, the upgrade, allocation
  reasons, an approved registrant's run, examples equal to real quotes, non-English sizes, the preview, real payloads
  against the onboarding fixtures and readers; the admin browser check decides registrations on the screen.

## Case library (editorial)

A small, committed collection of retrospective editorial case studies of official
releases and news items (collection version case-library-0.3), in `content/case-library/`:
`collection.json` (introduction, labels, selection statement, declared sectors, the
sector membership rule and the cases in publication order) and one `<case id>.json` per
case. Twenty-seven cases:

- Twelve macro cases (case version case-library-0.1, unchanged): the first four
  scheduled FOMC statements of 2025 (01-29, 03-19, 05-07, 06-18), and the Employment
  Situation (released 04-04, 05-02, 06-06, 07-03) and CPI (released 04-10, 05-13, 06-11,
  07-15) for reference months March to June 2025.
- Twelve sector cases (case version case-library-0.2), the last three consecutive
  releases or announcements published on or before 2026-09-30 in each source family:
  EIA Today in Energy articles (2026-09-22, 09-25, 09-30; topic Energy analysis); BIS
  press releases with their own bis.gov text naming semiconductors, semiconductor
  manufacturing equipment, chips or advanced computing items (2026-02-12, 06-17, 07-10;
  topic Export controls); Federal Reserve G.17 releases (2026-07-17, 08-18, 09-18; topic
  Industrial production); and Federal Reserve H.8 releases (2026-09-11, 09-18, 09-25;
  topic Bank balance sheets).

- Three WTO entries (case version case-library-0.3, topic International trade, no
  sector), written only from WTO news pages retained under approval wto-trade-sources-01:
  the trade forecast update listed 2026-10-08 (entry kind forecast), the Committee on Trade
  and Environment meeting listed 2026-09-28 and the General Council meeting listed
  2026-10-05 (entry kind proceedings, no channels). 0.3 adds www.wto.org as a source host,
  entry_kind (release, forecast, proceedings; channels may be empty only for proceedings),
  source.date_basis and source.retained {approval_id, sha256, bytes, retrieved_at, charset}
  (the copy itself stays private and is never served). The pages state no publication
  date: published_at is WTO's own news-feed listing date (date only; the feed's 00:00:00
  GMT is a placeholder), and meeting days are recorded in reference_period. A 0.3 entry may
  belong to no sector. A collection lists no case of a later version than its own.

The rule is consecutive releases per category or source family, not interest or later
market outcomes; it is an editorial collection, not a preregistered research cohort. The
WTO entries are three of the ten WTO news items in the Event Inbox, chosen for what they
explain (a forecast, a named agreement, trade-related climate measures).
- Sectors: energy, technology-semiconductors, manufacturing-automotive, banking-credit and
  mining-materials, each declared with a label, its coverage (including what it does not
  cover) and its selection. A sector case lists one or more declared sectors, distinct;
  it is listed under a sector when at least one key fact and one channel concern it.
  Membership is additive and stored once per case (two cases are under two sectors and the
  three G.17 cases under three; counts 5, 4, 5, 3, 3). Sectors are separate from topics
  (`category`) and from the Event inbox's topics. Macro cases have no sectors.
- Mining & materials (mining-materials, 2026-10-14): no new release or case. It lists the
  three G.17 cases selected under manufacturing-automotive, in G.17's own categories (mining:
  all industries in NAICS sector 21, as the release defines it; materials: the release's
  market group, not defined further in the pages read), covering US reported output and
  capacity utilization only, with no prices, company results, returns or market reactions.
  The three files changed by addition only: mining-materials last in `sectors`, and items
  appended at the end of key_facts, channels (08-18 and 09-18), competing_explanations,
  assumptions and missing_information, from release pages each case already lists in
  sources_read; their source, provenance and every earlier item and value are unchanged.
  Taking the additions off restores the earlier content exactly; tests pin both hashes,
  and the 24 other case files and the rest of the collection (all but its introduction and
  the appended sector) are unchanged. Later revisions appear as revisions with their release
  dates. A private matrix ties each added figure to a cell or sentence of a retained copy
  (acquisition g17-release-tables-01). A sector adds no live ingestion and no
  research-analysis capability.
- Publication precision: a 0.2 source states `published_precision` "time" (an explicit
  UTC offset, as in 0.1) or "date" (`published_at` is a date). No sector source states a
  time with a zone, so all twelve are date-only and are displayed as a date, never a
  time. Collection order is by date, then a stated time before date-only, then instant,
  then ID.
- A case is not a hypothesis. It has a source (official https address, publisher,
  publication time with an explicit UTC offset or a stated date only, as stated,
  reference period, retrieval date), an overview, key facts with their basis, channels
  (to Treasury yields for a macro case, within its sectors for a sector case) that each
  pair a source fact with a conditional interpretation, competing explanations,
  assumptions, missing information, observations that would weaken it, an editorial
  critique and source notes (limits and later revisions, with official links). It has no
  map, legs, observables, freeze, evaluation or verdict, and no market data of its own:
  market context, where the collection declares it, is a separate bundle (below).
- Fixed labels: AI-assisted, retrospective, prepared after publication, human review
  "not_reviewed" and research use "excluded". `expectations_benchmark` must be null, so
  no case says whether a release was a surprise. A later human review would need a new
  library version, not an edited label. The critique is prepared text, distinct from
  human review records.
- `second_order/case_library.py` (standard library only) validates every file strictly:
  exact fields, strict JSON, official hosts (the Board, BLS, EIA and BIS; only an EIA
  Today in Energy address may carry a query, its numeric id), offsets, dates in order,
  minimum section sizes, every cited source listed as read, declared sectors, market
  context only for cases with a publication time, a 0.1 collection listing only 0.1
  cases, and the collection in publication order. Any problem refuses the whole library.
  Nothing is repaired or partly served. `GET /api/case-library` and
  `GET /api/case-library/{case}` only read; they need no prepared files or runtime records.
- Cases never touch the store, prepared Dossiers or scoring, so they cannot enter any
  research denominator; research intake stays closed. Library counts are editorial
  counts, not research denominators.
- Browsing (client only, view case-library-view-0.3): `/library?q=…&category=…&sector=…`.
  The search is case-insensitive and needs every word to appear in a case's title,
  summary, topic or publisher; case bodies are not searched. The topic is all,
  monetary-policy, employment, inflation, energy-analysis, export-controls,
  industrial-production or bank-balance-sheets; the sector is all or a declared sector
  (an unknown one is reported and ignored). All three combine; each topic and sector
  count follows the other choices, a chosen sector states its coverage and selection,
  and an empty result explains itself with each filter's own count and offers a reset.
  The address is replaced as the filters change, so a reload or Back restores them. The
  Tracker shows the latest case per topic and links into the library by topic and by
  sector.
- Enrichments (case-enrichment-0.1; `second_order/case_enrichments.py`): an optional file
  `content/case-library/enrichments/<case>.json` beside a case, never inside it, bound by
  `case_file_sha256` to the case file's exact bytes (kept at LF on every checkout by
  `.gitattributes`). Present for bis-2026-07-10 and bis-2026-02-12. Fields: sources (`release`, required, whose address and stated date equal
  the case's, and optionally `listing`, BIS's News & Updates page; each with a retained record
  {approval_id bis-semis-sources-01, attempt, folder, sha256, bytes, retrieved_at, charset}),
  chain {placement, attribution "curator_interpretation", basis}, readout (statements with
  aspect instrument / scope / timing / conditions, each at least once, and status stated /
  not_stated / referenced_unread; at least one not_stated; a referenced_unread statement names
  a declared reference and no other status does), references (documents the source itself
  names or links, `read` false), claim_checks (target title, summary, key_facts[i],
  channels[i].source_fact, competing_explanations[i].detail or source_notes[i].detail, under
  the case's own label; status consistent / qualified / discrepancy / not_found, a note for
  every status but consistent; title, summary, every key fact and every channel's source
  statement are always checked), not_checked, examination (one entry per case channel, in
  order, by exact title, with the observations needed to examine it), comparison (null, or a
  historical case and ids of its facts) and provenance (AI-assisted, not_reviewed, excluded;
  prepared on or after its sources' retrieval). Any problem refuses that case's enrichment
  (500); the case itself is still served, unchanged.
- The enrichment view (`GET /api/case-library/{case}/enrichment`, read-only, 404 for an
  unknown case): state none, stale (the case file no longer has the bound bytes; nothing is
  shown and a note says why) or bound. A bound view adds counts derived from the checks, the
  historical comparison's facts and address, and one copy check per source against the
  retained folder (data/sector-sources/bis, git-ignored): verified (size and SHA-256 equal the
  record; the acquisition record matches or is absent), absent, or different (never trusted).
  The folder and attempt are never served. The case page shows a bound enrichment as one
  section, "Source check and reading aid", first in the case, lists each discrepancy at its
  top and flags the claim where it appears in the case; the client refuses a reply whose
  counts, statuses, references, sources or copies break this contract or whose checks do not
  address this case's claims under their own labels.

## Market context (case library, descriptive)

Manifest and view format market-context-0.1, index market-context-index-0.1, served view
market-context-view-0.2 (0.2 adds the acquisition run and the index hash), preparation
market-context-prep-0.1, committed in `content/market-context/` (marked `-text` in
`.gitattributes` so its hashed bytes survive any checkout). The cases with context are
those listed in the collection's `market_context` field. The field holds distinct IDs of
listed cases, and names the twelve macro cases; a test checks that it equals the cases
whose context verifies. Sector cases have no market context: Treasury yields do not
measure activity in those sectors, and the case page says so plainly.
- Series: the Federal Reserve Board's H.15 Treasury constant-maturity yields at 2 and 10
  years, `H15/H15/RIFLGFCY02_N.B` and `H15/H15/RIFLGFCY10_N.B` ("Market yield on U.S.
  Treasury securities at N-year constant maturity, quoted on investment basis"): unit
  `Percent:_Per_Year`, multiplier 1, business-day frequency, source U.S. Treasury. The
  Board's DDP-FRED crosswalk maps them to FRED DGS2 and DGS10, which are recorded as
  equivalents only; nothing is obtained from FRED, whose terms prohibit storing its
  content in a compilation and using it in connection with software development. The
  Board's website states that its information is in the public domain and may be copied
  and distributed without permission, citing the Board; it excepts non-Board material
  marked as copyrighted or trademarked and the Board's seals and logos, none of which
  are used, and nothing implies the Board's endorsement. There are no other assets, and
  no substitute series.
- Window: the publication instant, converted to America/New_York, gives the publication
  date. The window is that date plus or minus 14 calendar days, inclusive (29 dates). It
  is the same for every case and was fixed before any data were read.
- Sources: one Data Download Program CSV per case holding both series for exactly that
  window (the Program's direct-download address for the package of the two series,
  `Output.aspx?rel=H15&series=aa2b841a39cf82a8a04208d30ba16c2e&from=MM/DD/YYYY&to=…`),
  kept byte for byte. Parsing is strict:
  - six labelled header rows must name exactly the two series, each with its expected
    description, unit, multiplier, currency and column;
  - dates are YYYY-MM-DD and strictly increase;
  - `ND` (the source gives no value) is missing; every other value is a plain decimal,
    and the raw text is kept.
  Rows must lie inside the window and reach within 3 days of each edge.
- Acquisition runs: each staging folder is one run, downloaded together, with its own
  acquisition record and manifest. Run 1 is `manifest.json` with
  `sources/acquisition.json`; run N is `manifest-N.json` with `sources/acquisition-N.json`.
  `index.json` lists the runs in order, each with its manifest's SHA-256, and a case
  belongs to exactly one run. Runs made at different times are never merged or
  relabelled, and appending a run changes no existing file. The committed bundle has
  run 1 (2026-10-07 22:07 UTC: fomc-2025-03-19, empsit-2025-07-03, cpi-2025-07-15) and
  run 2 (22:48–22:50 UTC: the other nine).
- Acquisition record (kept byte for byte in `sources/`): a tool and one record per kept
  download with exactly case, file, url, requested_at and received_at (explicit
  offsets), http_status, content_type, response_date (HTTP Date), bytes and sha256. The
  address must be the case's expected one, the reply a 200 `text/csv`, the three times
  within five minutes of each other and in order, and the bytes those of the file. An
  optional `discarded` list records refused replies with exactly case, url, the times,
  status, type, response date, bytes, sha256 and a reason; each must name a case of the
  record and its address, and nothing from it is kept or served as data.
- Classification: the SIFMA US bond calendar and exceptions used by the research import
  (keyed by the FRED-equivalent IDs) give the expected sessions. Each date and series
  gets exactly one status: session_value, session_missing (an `ND` on a session),
  session_absent (no row), calendar_holiday, not_a_session (a weekend, with or without
  an `ND` row) or one of the calendar's documented exceptions. A value is shown only for
  session_value, or for a documented issuer observation on a holiday. Nothing is
  interpolated, filled, carried forward or moved.
- Preparation is explicit and offline; it never downloads. `prepare` starts a bundle
  with run 1; `append` adds the next run for declared cases the bundle does not hold.
  The staging folder must hold exactly one `<case>.csv` per case and an acquisition
  record with exactly one valid kept download for each. Anything missing, extra,
  mismatched or short refuses the whole run. `append` first copies the bundle byte for
  byte to a temporary folder and verifies every existing context there (a bundle from
  before the index is indexed as run 1, its manifest unchanged); it refuses cases
  already held or not declared, writes the new run beside the existing files without
  overwriting any, verifies every context again and that every existing file is
  byte-identical, and only then moves the result into place.
  - `prepare` and `append` hold one non-blocking cross-process write lock for the bundle
    from their initial read through publication. A concurrent writer is refused, never
    queued or retried. Its persistent sidecar is outside the replaced folder and is
    released by the OS on exit; reads neither acquire it nor create it. The default
    sidecar is git-ignored. Their read-only refusals are checked before the lock is
    taken and again under it, so a refused `append` to a missing path creates nothing.
  - `append` rechecks the live bundle before publication, including the index and file
    set, and refuses an external change. `prepare` without replace rechecks that its
    destination is still absent or empty, and otherwise refuses and leaves it as it is.
  - Publication (`second_order/context_publish.py`) is two renames: the bundle moves
    aside into `.market-context-previous-<UTC time, microseconds>-<8 hex>-<bundle folder
    name>` (its name records its exact owner and time; nothing is written into it), the
    new folder moves in, and the moved-aside copy is removed. Every outcome is a stated
    result, never a traceback: not moved aside (nothing published, bundle unchanged);
    not moved in (original moved back, and the error says so; if that fails too, the
    original is preserved, never deleted, and the error names it and how to restore
    it); old copy not removable (published, with a warning naming what is left).
  - The renames are not crash-atomic: between them a reader finds no bundle. Ctrl-C in
    the main thread is held until they, or the restoration, finish. A hard kill, power
    loss or crash between them leaves the bundle path missing and the original intact
    in its moved-aside folder.
  - Recovery keeps ownership, order and integrity apart. Ownership: only folders whose
    names record this bundle's exact folder name are its copies; other bundles' are
    counted as unrelated, and folders recording no owner (earlier versions) are listed
    as of unknown origin, never as its own. Order: its copies by recorded time, newest
    first; the most recent is named only when it alone has the latest time, and equal
    times stay unordered. Integrity: each copy's runs, cases, acquisition methods and
    verification are reported, and never choose a copy; a most recent copy that does
    not verify is still the one named, marked not safe to restore as it is, and older
    copies are described as earlier states, not replacements.
  - Reads (served) say only that a publication may have been interrupted, and only when
    copies recorded as this bundle's exist; they name no folder. `check` prints the
    operator's report; `append` and `prepare` refuse with it only while such copies
    exist, so other bundles' folders and folders of unknown owner never block a new
    bundle or count as its predecessor. Nothing chooses, restores, deletes or
    overwrites a folder. Working and moved-aside folders under `content/` are
    git-ignored.
  - The manifest records the source and terms, the series metadata and citations, the
    acquisition (method, tool, the record's path and SHA-256, vintage null and a vintage
    note), the calendar identity and each view's SHA-256.
  - Each view records its window, publication, expected sessions, source (file,
    SHA-256, bytes, address, requested and returned ranges, rows and the download
    record's times, status and type) and every day.
- Reading: `GET /api/case-library/{case}/market-context` runs `load_context`, which
  verifies everything again on each read. It never fetches, writes or repairs. It
  answers:
  - 404 when the case is not declared or not in the bundle;
  - 503 when there is no index;
  - 500 when the index, a run's manifest or its hash, a case listed by two runs, the
    version, source, terms, series metadata, citations, calendar exceptions, the run's
    own acquisition record, any hash or size, the download record, the source's own
    header, the window, the publication or the re-derived days disagree.
- Vintage: none is requested, and the Data Download Program offers none ("Pre-revision
  or real time data are not available"). Values are the Board's as published at
  retrieval and are labelled that way, never as a historical vintage; whether any was
  revised is not known.
- Descriptive only: no horizon change, reaction measure, attribution, verdict or score.
  Context never touches the store, Dossiers, scoring, research summaries or intake. The
  module imports only the standard library, the case library and the market calendar,
  and a test checks that the scoreboards are unchanged.
- Page: declared cases get a "Market context" section after the channels, with an entry
  in the page's contents. It contains:
  - a two-series chart: a legend, a percent axis, a calendar-date axis, the publication
    date marked as a date, and labelled marks at gaps; phones get a compact drawing;
  - a table of all 29 dates, with each status in words;
  - the provenance (including the acquisition run and any discarded replies), the
    citations and the limits, including how many expected sessions lack a value.
  Dates are formatted from their own digits, never through the browser's time zone. When
  the context cannot be served, the section gives the reason and shows no substitute
  data. Other cases say they show no market data.

## Event inbox (manual discovery; post-library milestone)

The operator started this milestone on 2026-10-08: manual event discovery and intake
prefill. It narrowly extends the earlier scope. Scheduling, background polling,
clustering, automatic analysis, article downloading and research intake stay out of
scope, and every earlier safeguard stays. Inbox version event-inbox-0.1, served view
event-inbox-view-0.1, in `second_order/event_inbox.py`.

- Sources: exactly five fixed feeds, each listed in its publisher's catalogue, in this
  order:
  - the Federal Reserve Board's monetary-policy press releases (`press_monetary.xml`,
    RSS 2.0);
  - the BLS Employment Situation and Consumer Price Index feeds (`empsit.rss`,
    `cpi.rss`, served as Atom);
  - EIA's Today in Energy (`https://www.eia.gov/rss/todayinenergy.xml`, RSS 2.0);
  - the WTO's latest news (`https://www.wto.org/library/rss/latest_news_e.xml`, RSS 2.0;
    the catalogue gives the `http` address, and the same path is served over `https` on
    the same host without a redirect).

  No URL comes from a request or a feed entry, and no linked article is fetched. The WTO
  feed's full-article `content` element is never read.
- Kinds and credits: each source has a topic (its entries' category) and a kind. The
  Federal Reserve's is Policy announcement, the BLS sources' Statistical release, EIA's
  Analysis article and the WTO's News announcement; only Statistical release is a formal
  statistical release.
  - EIA and WTO carry the credit their reuse terms ask for: "Source: U.S. Energy
    Information Administration" (public domain) and "WTO news", neither with a logo.
    They were checked on 2026-10-08.
  - The view gives the kind and credit on each source and entry. No credit is stated for
    sources whose terms were not checked for one.
- Verification of the energy and trade feeds (2026-10-08): their documentation was read
  and one bounded preflight request per feed was made outside the app's data. The results
  are recorded in docs/DEVELOPMENT.md (Event inbox); they are a one-time observation. The tests use synthetic
  feeds and prove only the handling of those shapes.
- Access: BLS's robot policy reserves the right to block automated requests that carry
  no contact for their owner. The operator's contact, from `SECOND_ORDER_FEED_CONTACT` (one line of
  printable text, at most 200 characters), goes in an honest User-Agent; without it the
  BLS sources are not requested. The client never presents itself as a browser.
- Refresh: `POST /api/inbox/refresh` is the only network action. It takes exactly `{}`
  under the local-write checks with the `X-Second-Order-Inbox` header. Each source is
  requested once, sequentially, with no retry and no redirect. Limits: 10-second
  connect, 20-second read, 30-second whole response, 1 MB, 200 entries. A refresh while
  one runs is refused with 409.
- Reading: `GET /api/inbox`, startup and page loads read the local cache only. They
  make no network request and no write, create no folder and repair nothing.
- Parsing: the document must be UTF-8 (a BOM is allowed); any other declared encoding
  is refused, with one exception. The EIA source alone may declare ISO-8859-1, and it is
  then decoded as declared; nothing is guessed, and a BOM still means UTF-8. In that
  encoding, an entry whose title or excerpt holds bytes 0x80 to 0x9F (not printable in
  ISO-8859-1, often Windows-1252 punctuation) is skipped and counted. A DTD or entity, element or attribute-list declaration refuses the whole
  document before parsing, as does malformed XML or a root that is neither RSS 2.0 nor
  Atom.
  - Titles and excerpts become plain text (HTML stripped, control characters removed)
    and are cut at 300 and 1,200 characters, with a mark. An entry whose title or
    excerpt markup the HTML parser cannot read (Python's parser refuses some malformed
    declarations, such as `<![bogus[`) is skipped and counted; the feed's other entries
    and the other sources are still read.
  - An entry needs an `https` link on its publisher's own host, with no user, no bare
    root and no port other than 443, the https default, which names the same
    destination; otherwise it is skipped and counted.
  - Identity is the GUID or Atom id, else the link, never the title. A repeat within a
    feed is dropped and counted.
- Timestamps: the raw value and its element (RSS `pubDate`, Atom `published`, or Atom
  `updated` when there is no `published`) are kept.
  - RSS: the date must have RFC 822 form. The zone must be a numeric offset other than
    `-0000`, or a name RFC 822 defines (UT, UTC, GMT, Z, and the US zones). Each of these
    gives no time:
    - any other name;
    - a weekday that contradicts the date;
    - an impossible date;
    - a US zone name whose offset is not its region's offset at that instant (by the
      IANA rules for New York, Chicago, Denver or Los Angeles). EST, EDT, CST, CDT, MDT,
      PST and PDT are checked; MST is not, because Arizona keeps it all year. EIA's fixed
      09:00:00 EST is therefore ambiguous under daylight saving.
  - Placeholder times: for a `date_only` source (the WTO alone), an exact 00:00:00 time
    gives no instant and no suggestion. The reason states the date.
  - Atom: RFC 3339 with an explicit offset.
  - A suggestion repeats the timestamp's own date, time and offset, only for an offset
    the intake form accepts. Fractional seconds are dropped and disclosed.
  - Otherwise the time stays unknown, with the reason. Nothing is filled from the
    retrieval time, the browser's zone or an assumed release time. A feed timestamp is
    never presented as a verified release time.
- Cache: `data/event-inbox/<source>.json` (ignored by git; `create_app(inbox=...)`
  overrides it for tests), one record per source.
  - Each record holds the last successful result (retrieval time, status, size,
    SHA-256, format, counts, items with their first-seen time) and the latest attempt
    (times, outcome `ok`, `failed` or `not_requested`, detail, status).
  - Writes are atomic: a temporary file is flushed and then replaces the record. A
    failure keeps the earlier result and never touches another source.
  - A record that is not exactly the expected shape is reported as unreadable, is not
    shown, and is neither repaired nor refreshed over.
- Retention and order: at most 50 entries per source from its latest successful
  refresh, in feed order. The view orders entries with a known instant first (newest
  first), then those without; ties keep source order, then feed position.
- Archive (`second_order/inbox_archive.py`, version event-inbox-archive-0.1):
  `data/event-inbox/archive/<source>.json`, written atomically after a successful
  refresh's record, never on a read or a failed refresh.
  - Entries keep their stable identity (GUID or Atom id, else link). Unchanged meaningful
    content (title, link, excerpt, feed timestamp, truncation marks) only moves its
    last-seen time; changed content appends a version and keeps the earlier one.
    Retrieval time alone never makes a version.
  - A missing archive starts from the source's existing record on the next refresh. An
    unreadable archive (bad JSON, fields, IDs, links, or a version whose content no longer
    matches its hash) is reported and never written over.
  - The view lists `retained`: archived entries no longer in the latest retrieval, at their
    latest version, with when they were last seen. Nothing expires, is deleted or is
    fetched for the archive.
- Raw copies (`second_order/inbox_raw.py`), for every source (keep_raw, on by default): after a
  successful refresh, the complete response bytes as received (within the fetch's own limits, after any content
  encoding the client undid) under `data/event-inbox/raw/<source>/<sha256>.xml`, written once and read-only and shared
  by identical retrievals; the retrieval record names the file. Storage only: nothing reads them to build the inbox;
  items, fingerprints and triage inputs are unchanged; no article is fetched; the WTO feed's full-article element
  stays in its copy, unread; a failure to keep a copy is a note, not a failed refresh; earlier retrievals have no copy
  and none is reconstructed. Records written under inbox-raw-0.1 (WTO only) are still read; none are written.
- Retrieval records (`second_order/inbox_acquisitions.py`, inbox-acquisition-0.1): one per request a refresh makes,
  accepted, refused (a response that was not a usable feed) or failed (no usable response), under
  `data/event-inbox/acquisitions/<source>/<n>.json`, numbered, created exclusively and read-only. A source that is not
  requested gets none. Fields: the exact endpoint; the request (GET, no validators sent, no redirect followed, no retry,
  whether the contact was sent); start and finish times; the HTTP status and version, the headers age, cache-control,
  content-encoding, content-length, content-type, date, etag, expires, last-modified, location, retry-after and vary
  (one line of at most 300 characters each), the other header names without values and the Set-Cookie count (never a
  value); the body's state (complete when the HTTP message ended as framed; partial with the count and SHA-256 of what
  arrived; not_read for an error status or redirect; none), its bytes, SHA-256, declared length, content encoding and
  kept file; for an accepted response the parser version (event-inbox-parser-0.1) and counts (listed, retained,
  beyond retention, repeated, skipped with reasons), each retained entry's ID, content fingerprint, feed position and
  text parts (title as_supplied or shortened; excerpt none, repeats_title, as_supplied or shortened), and changes: new,
  changed or unchanged by stable identity and then content fingerprint against the archive's latest versions (the
  previous retrieval when the archive is missing or unreadable), and the previous retrieval's entries no longer listed.
  A record that does not verify (fields, version, number, source, endpoint, outcome, body state, entries) is reported
  and never used or rewritten; a later request takes the next number. A failure to write one is a note, not a failed
  refresh. The view adds per source `full_text_element` and `acquisitions` (count, the newest readable record
  summarised with its counts and its kept copy checked against its SHA-256, and unreadable newer ones), per current or
  retained entry its `text` parts, and per refreshed source its record's summary. Retrieval time, display order and
  last-seen time are in no fingerprint; the first-seen time is shown as when the inbox first retrieved an entry, never
  as a publication time.
- View: per source, the state (never refreshed, ok, failed, not requested, unreadable),
  its topic, kind and credit, the last successful retrieval and the latest attempt with
  any error. Per entry, the title, topic (category), kind, publisher, credit, link,
  excerpt, feed timestamp, retrieval time and whether it comes from an earlier retrieval
  because the source's latest attempt did not succeed. Nothing is called live.
- Filters (client): topic and source narrow the current and retained entries the page
  already holds. They request nothing and write nothing, and a filtered-out selected
  entry stays selected.
- Intake prefill (client): "Analyze this event" fills only the headline and official
  link of the existing Analyze an event form; date, time, offset and published text
  stay empty.
  - The suggestion fills the time fields only on request. A filled-in suggestion must
    be confirmed as checked against the release before the existing preview.
  - The excerpt is shown apart from the form and never fills the published text.
  - Unsaved edits or a loaded preview are replaced only after the operator confirms.
    Replacing clears approvals, closes the preview (its capture stays in Saved events)
    and drops late replies to an earlier selection. Choosing is disabled while an
    action is in flight.
  - The rest is the existing workflow unchanged: exact saved request, explicit
    approval, one attempt, no retry, human review. A saved capture never changes when a
    feed does.
- Discovery is not analysis or research: the inbox never captures, drafts, sends,
  freezes, evaluates or scores, and never touches the store, research summaries or
  intake.

## Retained BIS snapshot (local records, explicit Inbox import)

- Source (`second_order/bis_snapshot.py`): the page https://www.bis.gov/news-updates retained under approval
  bis-semis-sources-01, located through its acquisition record (exactly one outcome for the address) and read only when
  the record describes a complete HTTP 200 `text/html; charset=utf-8` response without content encoding, retained at
  data/sector-sources/bis/news-updates/source.html, and the file's size and SHA-256 equal it (409 otherwise; 503 when
  absent). Release pages of the same acquisition are verified the same way before any comparison.
- Extraction (bis-snapshot-extract-0.1): exactly one `__NEXT_DATA__` script element, at most 4 MiB, strict JSON (no
  repeated key or non-standard constant; nesting errors refused), at most 1000 records under
  props.pageProps.pressReleaseTeasers. A usable record is a NodePressRelease marked published, with a title and a path
  matching /press-release/[a-z0-9][a-z0-9.-]* (no "..") on www.bis.gov; its identity is that address and its key the
  first 20 hex digits of the address's SHA-256. Text and summary are reduced to plain paragraphs by html.parser (block
  elements break; script, style, iframe, svg and similar elements and all markup dropped; entities decoded; at most 600
  paragraphs and 60,000 characters, cut flagged; a body over 200,000 characters is not read). An external link is kept
  only as a plain https address. Listing timestamps (publishedOn, created, changed) are listed (ISO time with offset,
  epoch seconds and zone agreeing, UTC), missing or ambiguous; created and changed are CMS metadata and never stand in for
  a publication time. Keyword filters use related_rules' semiconductors and export-controls word lists over title and
  text. An address listed twice is an identical copy (first kept) or, if the copies differ, withheld; the same title on
  different addresses is never merged. A record whose release page was retained is compared paragraph by paragraph
  (identical, differs or not compared), and that page's dateline is recorded apart. Text completeness: checked,
  checked_differs, listing_text, title_only or unreadable. record_sha256 covers identity, document UUID, publisher fields,
  text and the listing publication time (not CMS times, position or filters).
- Index (bis-snapshot-index-0.1): written once by the explicit open (POST /api/inbox/snapshots/bis/open, empty object)
  to data/bis-snapshot/index/<package sha256 prefix>-<extractor version>.json, read-only, with a content SHA-256; reused
  afterwards. GET routes never build or write; an index that does not verify is refused and left as it is.
- Imports (`second_order/inbox_imports.py`, inbox-import-0.1): under <inbox>/imports/bis-snapshot/,
  entries/<key>/<n>.json (inbox-import-entry-0.1: id bis-snapshot:<key>, version, import id and time, the Inbox content
  fields with content_sha256, the extracted record with record_sha256, the package, extractor and index versions and
  index SHA-256) and records/<import id>.json for each import that wrote anything. Writes are atomic creates that never
  overwrite, under one lock. A preview (POST .../preview, {keys}) classifies 1 to 25 distinct keys as new, existing
  (same record_sha256), changed (differs; the fields that differ are named) or unusable (with reasons) and writes
  nothing. An import (POST .../import, {keys, decisions}) needs a decision (keep or add_version) for every changed key or
  refuses (409) without writing; it adds new entries, adds a version for add_version, and otherwise writes nothing. Entry
  files that do not verify are reported and never overwritten.
- In the Inbox view, "imported" lists each entry's latest version (source bis-snapshot, kind Press release, category
  Export controls, position null, first_seen_at its first import), with its record and provenance, and "imports"
  summarizes the store. The excerpt is the first 1200 characters of the text; the feed timestamp is the listing's
  publishedOn (raw and instant) with no suggestion. Triage reads only "items" and "retained", so imported entries are
  never offered; event_key, the event overview (triage "not_offered", market "unsupported"), capture origins, Related
  research (date label "listing timestamp (retained snapshot)") and Related Cases accept them.
- The page /inbox/bis-snapshot opens, browses (search over title, opening text, topics and host; keyword filter,
  starting with semiconductors; BIS topic; text; import state), inspects (plain text; dates and their meanings;
  provenance), selects (at most 25), previews and imports; its client refuses replies whose counts do not reconcile or
  whose preview or import does not answer for exactly the selection.

## Headline triage (inbox discovery support)

The operator started this milestone on 2026-10-08. API efficiency is an acceptance requirement. It extends the
Event inbox; it is not another inbox. The request contract is in `second_order/headline_triage.py` (triage version
headline-triage-0.3, prompt triage-prompt-5, schema triage-schema-4, view headline-triage-view-0.4, validation
triage-validation-3). What to request
is in `second_order/triage_plan.py`. Records, claims, approval and sending are in `second_order/triage_flow.py`.

- Purpose: browse fewer repetitive headlines and choose which entry deserves a full analysis. Not hypothesis
  drafting, market-impact prediction, importance, scoring, ranking or trading guidance.
- No automatic processing: no timer, poll, schedule or model call on page load, navigation, feed refresh, restart or
  elapsed time. A refresh discovers entries only. Model work needs Preview triage, a visible plan and its own
  approval. No retry anywhere: the client has none, and code never re-sends.
- Selection: 1 to 25 entries, current or retained (archive). Entries are ordered by feed instant (newest first, none
  last), then source, then ID, so the order of a selection never changes a request.
- Inputs (recorded inbox data only): entry ID, source, publisher, feed category, title and whether it was shortened,
  official link, feed timestamp (raw, element, UTC instant when unambiguous), and excerpt and whether it was
  shortened. An excerpt that only repeats the title is sent as null. Retrieval times are not inputs.
- Per-entry reuse:
  - fingerprint: the SHA-256 of exactly the fields sent for the entry;
  - configuration: model, effort, thinking, prompt version and schema version, read at call time.
  A result is reused for the same fingerprint, configuration and mode (simulated results never count as paid ones),
  so reopening, restarting, reselecting in any order and unchanged refreshes request nothing. A changed entry is a
  new fingerprint; its earlier version and that version's result are kept. An identical title on another date is
  another fingerprint, and missing dates never merge anything.
- Statuses, resolved locally before anything is prepared:
  - reuse: a saved result for this configuration;
  - process: none yet, or explicitly re-requested;
  - earlier_version: a result only from another configuration. It is shown with provenance and regenerated only by
    explicit decision, so an upgrade never starts paid work on its own;
  - unresolved: an earlier request claimed it without an accepted result. It is never re-queued on its own.
- Comparisons are tracked apart from classification (`triage_plan.comparison_work`, shared by planning and dispatch).
  - Identity: both entries' fingerprints in canonical order, the mode and the configuration. Selection order and
    other selected entries never make a comparison new; a changed entry never reuses an older one. A relation keeps
    its own wording and member order.
  - Scope: the candidate pairs still needed are the request's comparison scope, canonical (each pair sorted, the list
    sorted; the order states no direction). It is saved in `selection.json` and `prepared.json`, carried in the
    request bytes as `comparison_pairs` (so it is part of the SHA-256), repeated by the approval and named by the
    prompt as the only pairs the model may relate.
  - A pair counts as compared only when it was in the scope of an accepted response under this configuration, with
    both versions. Entries merely appearing together in a request are not compared.
  - Candidate pairs: same publisher, and feed dates at most 10 days apart or either missing. Local metadata narrows;
    it never merges. A feed date without a usable instant counts as missing: the WTO's placeholder times, and EIA's
    stamps under daylight saving. Pairs across publishers are never compared, so duplicate coverage across
    publishers (an EIA article and a WTO item, or a Federal Reserve release and an EIA article, about one event) is
    not detected. That is a stated limit of this policy, not a finding of separate events.
  - A candidate pair not yet compared brings its earlier entry in as comparison context: ID, source, publisher,
    title, link and feed instant. No excerpt is sent and no new result is asked for it.
  - A pair claimed by an earlier request without an accepted result (in flight, failed or uncertain), or compared
    only under an earlier configuration, is not queued again unless one of its entries is explicitly re-requested.
- Plan: at most one request, holding every entry to process and the context its needed pairs require. With nothing
  to process and no needed pair, nothing is requested and saved results are shown. The plan reports the reused,
  processed, context, unresolved and earlier-version counts, the request count and the estimate. The estimate states
  the comparison context's share of input tokens.
- Output, validated whole after receipt:
  - exactly one result per entry, none for context, none missing, repeated or unknown;
  - a category from the documented taxonomy: Policy decision, Meeting minutes or record, Data release (formal
    statistical releases only), Forecast or projection, Analysis or report, Update or correction, Announcement or
    notice, Other, Insufficient information. Categories are only ever added, so earlier results stay valid;
  - an event type of at most 8 words, or null (always null when information is insufficient);
  - a summary aimed at about 25 words, grounded in the title, excerpt and metadata. Under triage-validation-2 and -3
    only one past 60 words or 600 characters is refused; triage-validation-1 refused anything past 25 words. Every
    attempt's manifest names the policy it was checked under.
  - Local re-check (`second_order/triage_recheck.py`, `POST /api/triage/<id>/<attempt>/revalidate` with the saved
    response's SHA-256): an explicit action that parses a not-accepted response again under the current policy, with
    its request's own entries, scope and model. Nothing is sent or regenerated. The outcome is written once to
    `<attempt>/revalidations/<policy>.json`, beside the unchanged original. A response accepted on a re-check is a
    usable result labelled as such, and blocks re-sending that request. 0.2 requests are not re-checked.
  Optional relations (`possibly_same_event`, `update_or_correction`, `separate_releases`) name two or more distinct
  supplied IDs (entries or context) and give a reason aimed at about 30 words: under triage-validation-3 only one past
  60 words or 600 characters is refused (triage-validation-1 and -2 refused anything past 30). Every two members of a
  relation must form one of the request's scope pairs (A-B and B-C never allow A-C), and an empty scope allows no
  relation; this is checked on receipt, not left to the prompt or schema. Within one response, an ID is in at most one
  same-event group. The same IDs may not be both one event and separate releases, and no relation may repeat.
- Refused whole, with nothing shown:
  - any content block other than thinking and exactly one structured text reply;
  - a stop reason other than `end_turn` (`max_tokens`; `refusal` with its category);
  - another model than the saved request named;
  - invalid or repeated-key JSON;
  - any rule above.
  Nothing is repaired, coerced, completed, merged or chained.
- Request:
  - `claude-haiku-5-5`; `output_config.effort` low; `thinking` adaptive, stated;
  - `max_tokens` 4,000 + 320 per entry (12,000 at 25), for thinking and the reply together;
  - `output_config.format`: a JSON schema whose result IDs are an enum of the entry IDs (no enum when there are no
    entries, and then no result is accepted) and whose relation IDs are an enum of the IDs in the scope (all supplied
    IDs when the scope is empty, since an empty enum is unusable; the check on receipt decides).
  The system prompt states its prompt and schema versions. No tools, sampling parameters, prefill or fallback models.
  Checked against Anthropic's documentation on 2026-10-08.
- Display: a relation is shown only for a selection holding every entry it names, with the fingerprints it had then,
  labelled with its request. Same-event groups are placed newest response first. One from another response that
  shares an entry is never merged or chained into a group; it stays a note. Updates, corrections and look-alike
  releases stay separate entries with notes. An ungrouped view lists every entry once. No entry or source is hidden,
  merged or deleted. A summary or event type stating a number absent from its entry's own title and excerpt is
  flagged, not refused.
- Records, under `data/headline-triage/` (ignored by git; `create_app(triage=...)` overrides it), apart from
  captures, attempts, drafts and reviews:
  - `requests/<triage-id>/`: the ID is `triage-` plus 24 hex digits of the request bytes' SHA-256. It holds
    `selection.json` (entry and context snapshots) and `request.json` (exact bytes), then `prepared.json` last
    (configuration, hashes, max_tokens, estimate). Files are written whole and never replaced; a different existing
    file is refused, and an identical plan reuses the record.
  - Attempt folders per mode: `simulated` or `paid`, then `paid-2` and so on. Each is created exclusively and holds
    `reservation.json`, `attempt.json` (sending), `response.json` (exact bytes; not kept for a paid reply that echoes
    the key) and `manifest.json` last (outcome, provenance, configuration, usage and cost when reported, attempts 1,
    retries 0, no fallback).
  - `claims/<mode>/<fingerprint>-<configuration key>/<n>.json` and
    `claims/<mode>/pairs/<hash of both fingerprints in canonical order>-<configuration key>/<n>.json`, each created
    exclusively before anything is reserved, name the request and attempt that claimed an entry or a comparison.
  Results and comparisons are read from the accepted responses and re-verified on every read; nothing is copied twice.
  A record that does not verify is listed and left alone.
- Approval and sending: `POST /api/triage` (`item_ids`, `mode`, `reprocess_ids`) plans and saves a request only when
  one is planned. `POST /api/triage/<id>/simulated` and `/paid` need the exact `request_sha256`, an explicit true,
  `reprocess_ids` and `comparison_pairs` (exactly the request's saved scope, in any order; anything else is refused);
  paid also repeats the planning estimate, which the server recomputes. All need the local-write checks with the
  `X-Second-Order-Triage` header.
  - Dispatch recomputes the request's comparison work as it stands. If it is no longer exactly the saved scope (work
    done, reserved or left unresolved by another request since the preview), or nothing at all remains, the approval
    is refused before anything is reserved and a fresh preview is needed; the remaining work is a new request with
    its own scope. Bytes and scope are never rewritten.
  - Claims cover exactly the saved scope's pairs, besides the entries.
  - Requests saved under headline-triage-0.2 have no scope. They are read as saved (their replies' relations
    unchecked, labelled as such) and never sent in either mode; their results are earlier-version results, and only
    the pairs their approval named count as compared under their own configuration. Nothing is regenerated on its
    own.
  - Every entry and every comparison is claimed before anything is reserved. Work with an accepted result is
    refused; work claimed before is refused unless one of its entries is re-requested. A concurrent claim fails
    exclusively, in this or another process, and a refusal removes only that call's own claims. Claims are never
    released once the attempt folder exists.
  - A second attempt of one request in one mode needs no accepted attempt and a re-request of every entry.
  - The saved bytes are posted once per attempt, never rebuilt. Simulated: an in-process transport with no network,
    whose placeholder results say no model read the entries, $0. Paid: only on `serve --enable-paid-triage` with the
    key in `SECOND_ORDER_ANTHROPIC_API_KEY` (a separate opt-in). A lost paid reply is recorded as an unknown outcome
    that may have been billed.
  Triage never consumes a capture's attempt and leaves the Sonnet drafting path unchanged.
- Estimate (planning only, not a billing ceiling): input is request bytes ÷ 2 + 1,000 tokens for the API's added
  prompts, output is `max_tokens`. Rates are $0.10/$0.50 per million input/output tokens, or $0.50/$2.50 above 100,000
  prompt tokens; no caching, batch or data-residency multiplier. Usage cost, when reported, uses the same rates.
- Reads: `GET /api/triage/selection` (plan and saved results), `GET /api/triage` (saved requests, newest first, failed
  and unreadable ones included) and `GET /api/triage/<id>` read only. They make no model call, network request or
  write, and create no folder.
- Client: an entry's "Select for triage" (at most 25, current or retained); the response mode; "Preview triage"; the
  plan; the entries and context exactly as sent; the exact request and hash; settings; the estimate with its
  assumptions; and an approval per planned request. Per entry, the results show its status, result, provenance,
  official link and "Analyze this event", which uses the held entry as it is now. They also offer "Request again" and
  "Regenerate with the current version" checkboxes, which need a new preview. A preview of another selection, mode or
  set of choices cannot be approved. Every server reply is verified before it is shown.
- Not yet done: no real provider request has been made with this path.

## Human review records

A person may save a review of a prepared draft view: notes, an optional status
("needs_revision" or "human_reviewed") and, for a draft outcome only, corrections to
the summary and to each leg's rationale, falsifier and headline_reports_move flag. The
graph, observable IDs, directions, horizons and primary leg are not editable. A status
records human judgment; it does not verify reasoning, establish research eligibility,
freeze or evaluate anything. Declines and failures take notes and a status only, so no
draft is invented for them.
- Records (record version draft-human-review-0.1): each save appends one immutable
  version under `data/draft-reviews/<draft id>/` (git-ignored), numbered and created
  exclusively, never rewritten. A version holds a server-stamped time, its parent
  version's ID, the attribution "local human reviewer", and the SHA-256 of the
  prepared view with its prompt hash, response hash and request ID. Its ID is the hash
  of its content. Corrections must differ from the model's values and are stored apart
  from them; the model's proposal, pilot records and prepared views are only read.
- Saves: POST `/api/drafts/{id}/reviews` is the only write route. It accepts strict JSON
  with exactly the documented fields, from a local Host, with this server's Origin, a
  same-origin fetch and a custom header that cross-site pages cannot send without a CORS
  preflight (never granted). GET `/api/drafts/{id}` sends each view with the SHA-256 of
  its exact bytes in the `X-Draft-View-SHA256` header, and a save's binding must name
  that fingerprint with the prompt and response hashes. A fingerprint that is not the
  current view's (even when those hashes still match), a parent that is not the latest
  version, or a save identical to the latest version saved against the same view is
  refused, and nothing is appended.
- History (view version draft-review-history-0.2): GET `/api/drafts/{id}/reviews` reads
  the versions verified (numbering, content IDs and parent chain) with the current
  view's fingerprint; an inconsistent history is reported, never repaired. A version
  bound to another fingerprint was saved against an earlier prepared view: the page
  lists it as such and never applies its corrections or treats its judgment as current.
  If the history's fingerprint differs from the view the page loaded, the page refuses to
  save until both are reloaded.
- Page: unsaved edits are guarded when switching drafts, following in-app links, using
  Back or Forward, and unloading the page. A save never replaces the form: edits made
  while it is in flight stay unsaved. A save without a readable reply is "not
  confirmed"; the page keeps the edits, offers no further save until the saved versions
  are checked, and settles the outcome from them without sending the save again: saved;
  saved but followed by a newer version (reported as saved, not refused; the newer
  version is shown only after an explicit reload, and a save from the outdated page is
  refused as a conflict); not saved; or replaced by a different version.

## My analyses (local work library)

`second_order/analysis_library.py` (view analysis-library-view-0.1), served read-only at
`GET /api/analyses` and shown at `/analyses`. It adds no records, schema or persistence.

- Entries: each capture from Analyze an event whose one attempt has a published review
  view in the Tracker's own folder. Each is read only through the verified readers:
  `event_intake.verified` (headline, source URL, publication time as supplied and in
  UTC), `analysis_flow.attempt_state` (the view rebuilt from the attempt's records and
  compared with the published bytes) and `human_review.history`. The recorded mode
  (reservation) must agree with the run the view records: the mock run and a synthetic
  case, or the paid run and a real one.
- Review state, against the fingerprint of the view served now: none; current (the
  latest version was saved against this exact view: its status or none, its notes'
  first 400 characters and how many fields it corrects); stale (the latest version was
  saved against another view, so this view has no current review); invalid (the history
  does not verify). An invalid history is never shown as unreviewed.
- Unreadable records (a capture that no longer verifies but has an attempt, an attempt
  state "invalid", a mode that contradicts the view, a Tracker view no verified capture
  and attempt produced) are listed with the reason, never dropped or repaired. Captures
  with no attempt, an unfinished attempt or a response awaiting publication, and the
  prepared pilot drafts, are only counted.
- The client re-checks every entry and moves one it cannot read to the unreadable
  records. Search (headline, source address, model output, latest current note) and the
  outcome, response-mode and review-status filters are kept in the address. "Open
  review" uses the Tracker's `/?draft=` link with a `from=` address of this page, which
  the review screen accepts only as `/analyses` or `/analyses?…` for its link back.

## Market context for selected events (private, descriptive)

`second_order/market_store.py` (CSV retrievals market-retrieval-0.1, read only; attempts
market-retrieval-attempt-0.2, with 0.1 still read), `market_package.py` (release packages market-package-0.1,
validation records market-package-validation-0.1, parser h15-release-xml-parser-0.1), `event_context.py`
(confirmations event-market-context-0.2, view event-market-context-view-0.1) and `market_retrieval.py` (plan
market-retrieval-plan-0.2, page event-market-context-page-0.2, list event-market-context-list-0.2, result
market-retrieval-result-0.2). Records live under `data/market-context/` (git-ignored); the case library and its
bundle are only read.

- Supported events: Event inbox entries of `fed-monetary`, `bls-empsit` and `bls-cpi` (current or retained), and
  verified captures whose source URL is an https `www.federalreserve.gov/newsevents/pressreleases/monetaryYYYYMMDDx.htm`
  or a `www.bls.gov/news.release/` Employment Situation or CPI release (`empsit.nr0`, `empsit.toc`,
  `archives/empsit_MMDDYYYY`, and the same for `cpi`). Energy and trade entries, and other captures, are outside
  this slice, with that reason; nothing is planned or shown for them.
- Context date (convention new-york-calendar-date-1): a capture's is the New York date of its supplied time and
  offset (`published_at_as_supplied`), unchanged and unconfirmed. An Inbox entry has none until the user confirms a
  date and the convention (`POST /api/market-context/inbox/<item>/confirm` with `{"context_date", "convention",
  "version"}`). The suggestion is the New York date of the feed's `instant_utc`, or nothing when the timestamp states
  no instant. Refused: a malformed or unreal date, a date after today's New York date, another convention, an
  unsupported source (422); a version other than the next one, or unreadable saved versions (409). A repeat of the
  current date for the same entry version writes nothing. Versions are `events/<key>/<n>.json`, created
  exclusively and read-only, each keeping the entry's metadata and content fingerprint so it reopens after the entry
  leaves the inbox; a confirmation applies only while the entry's content fingerprint is unchanged.
- Window: 14 calendar days either side of the context date. Sessions: the SIFMA calendar (market_calendar) with
  the versioned calendar exceptions.
- Retrievals: the committed bundle's downloads, read in place; earlier private CSV retrievals
  (`retrievals/<id>/source.csv` and `retrieval.json`), read and never written now; and kept release packages whose
  current validation accepted them (`packages/<id>/`). A CSV is verified on every read: the address must be exactly
  `market_context.export_url` of its range; an HTTP 200 text/csv reply whose request, receipt and server Date agree
  within 300 seconds; the size and SHA-256; `parse_h15_csv`; rows inside the requested range and not after the
  request's New York date. A package is verified as described under Release packages. A failing one is reported and
  unused. A CSV states a value, ND or no row for every date from its requested start to its last returned date, and
  nothing after it. A package states the dates both series cover (the later first observation to the earlier last
  one), and nothing from there to the day before its request.
- Statuses per date and series: the statements of every retrieval that states the date are combined only when
  identical (else `conflict`, with every version listed); an agreed statement is classified as
  `market_calendar.reconcile` does (`session_value`, `session_missing`, `session_absent`, `issuer_no_observation`,
  `calendar_holiday`, `issuer_observation_on_calendar_holiday`, `unreconciled_value_on_calendar_holiday`), with
  `weekend` named apart; a session no retrieval states is `future` (on or after today's New York date),
  `after_retrieval` (inside a retrieval's requested range after its last returned date) or `not_held`.
- Descriptive changes (endpoint-rule-1): from the last expected session before the context date to the first and
  the fifth expected sessions after it, per series: (end - start) x 100 basis points with Decimal arithmetic on the
  published text. Unavailable, with the reason, unless both endpoints are `session_value`.
- Plan: expected sessions in the events' windows before today, minus those any verified retrieval states; at most
  one request, for the release package (`request`: the fixed address, `download: "full_release_package"`, the
  number of missing sessions and the first and last). The plan's source says the download is the whole release
  (every series, full history), not two series or a date range. Its SHA-256 covers the plan version, source, events
  and context dates, missing sessions and address, so an approval of a 0.1 plan (the two-series CSV) never matches.
  The page and plan list kept packages that are not used (`packages_not_used`: not yet validated, or refused).
  `GET /api/market-context/plan?event=…` previews several saved events together.
- Dispatch (`POST /api/market-context/retrievals` with `{"plan_sha256", "events", "attempt"}`): only with a fetcher
  chosen at startup (`serve --enable-market-retrieval`, `ReleaseFetcher`); under the store's non-blocking
  cross-process lock (busy: 409); the plan recomputed from local data and required to match (else 409, nothing
  sent); a non-empty plan; the attempt number exactly the next one. `attempts/<plan>/<n>.started.json` is written
  exclusively before the request and `<n>.outcome.json` after (`saved`, `retained_not_accepted`, `refused_reply`,
  `no_reply` or `not_saved`); a start without an outcome is shown as unrecorded. The request: GET of the fixed
  address only, `Accept: */*`, `Accept-Encoding: identity`, the app's User-Agent, no cookie (refused before sending
  if one would be sent), no redirect, no retry, connect 10 s, read 60 s, a 600-second deadline, at most 200 MB
  (declared or streamed), raw bytes streamed to `packages/.staging-<hex>/package.zip`. Refused without keeping
  anything: a redirect, a non-200 (at most 4 KiB of its body kept as an untrusted excerpt, marked complete or not),
  any content encoding other than identity (never decoded), a type other than `application/zip` or
  `application/x-zip-compressed`, a short body, the deadline, or an archive that fails a safeguard. Set-Cookie
  values are never stored: only their presence and count. A kept package is validated at once: `saved` when
  accepted, `retained_not_accepted` (kept, listed, never used) when refused.
- Reads (`GET /api/market-context`, `/api/market-context/<inbox|capture>/<id>`, the plan) never contact the Board,
  write, lock or create a folder.
- Source: the Board's H.15 release package, `https://www.federalreserve.gov/releases/h15/data/FRB_h15_xml.zip`,
  which replaces the Data Download Program's two-series package (`DDP_PACKAGE`) for new requests: the Board
  announced (checked 2026-10-09) that "Build Your Package" is to be removed the week of 9 November 2026 and the
  program later retired, and directs users to the XML file on each release page. The plan states this; no other
  source is substituted, and a failing address is shown as a failed attempt.
- Release packages (`market_package`): `packages/<id>/` holds `package.zip` exactly as received and
  `acquisition.json` (written once, read-only: source, address, request and receipt times, HTTP status and
  version, response headers without Set-Cookie values, size, SHA-256, the archive inventory, the DOCTYPE/ENTITY
  byte-pattern findings, the client and approval, `validation_status: "acquired_unvalidated"`), and one
  `validation-<parser version>.json` per parser version (created exclusively). The ID is
  `p<request time, UTC, microseconds>Z-<first 12 hex of the SHA-256>`.
  - Archive safeguards, on the actual bytes and without extracting to disk: 1 to 50 entries; unique names; no
    absolute path, drive, backslash, `..` or control character; no symbolic link; no encryption flag; stored or
    deflated only; at most 512 MB per entry (declared and actual) and 1 GB in all decompressed; at most 200:1; every
    CRC. Byte patterns `<!DOCTYPE` and `<!ENTITY` are recorded per entry (offset, at most 200 bytes of untrusted
    context, at most 20 excerpts, the rest counted), never acted on.
  - Parsing: only `H15_data.xml`, streamed through expat with DOCTYPE, entity, notation and unparsed-entity
    declarations refused by handler, parameter entities never parsed and external entity references refused;
    depth, text and observation counts are bounded. Required: an SDMX `MessageGroup` whose header ID is `H15`; each
    of `RIFLGFCY02_N.B` and `RIFLGFCY10_N.B` exactly once, in the `H15` dataset (namespace
    `…/compact/H15_H15`), with exactly the attributes CURRENCY `NA`, FREQ `9`, INSTRUMENT `TCMNOM`, MATURITY `Y2` or
    `Y10`, SERIES_NAME, UNIT `Percent:_Per_Year`, UNIT_MULT `1`, the short description `<n>-year Treasury constant
    maturity` and the CSV header's long description (whitespace aside); observations with exactly OBS_STATUS,
    OBS_VALUE and TIME_PERIOD, real ISO dates, weekdays only, strictly increasing; status `A` with a plain decimal
    (kept as text) or `ND` with `-9999` (stated as `ND`); no observation after the request's New York date; a
    common date range. Anything else refuses the data, with the blocker recorded. FREQ `9` is checked as a code; its
    label lives in the DOCTYPE-bearing structure entries, which are not parsed, so the business-day frequency is
    checked from the observations. A weekday absent inside a series' range is no row (`missing_weekdays` counts
    them).
  - Validation record (market-package-validation-0.1): versions, package ID and SHA-256, time, the parser and its
    protections, status `accepted` or `refused` with the blocker; for accepted, the archive inventory and findings,
    the data entry's size, CRC and SHA-256, the header (ID, name, prepared time), each series' attributes,
    descriptions, first and last dates and counts, the common coverage, the rows and their SHA-256. Verified on
    every read against the package's SHA-256 and the current parser version, with every row, count and the
    coverage recomputed; a record for other bytes, another package or parser version, or with any difference, is
    not used. A package without a current record is `acquired_unvalidated` and not used.
  - `python -m second_order market-packages validate` validates each kept package without a current record, under
    the write lock, and fetches nothing; `market-packages list` reads only. GET routes never validate.

## Event overview (private, local)

`second_order/event_overview.py` (overview event-overview-0.1) and `event_links.py` (links event-link-0.1), served
read-only at `GET /api/events/inbox/<item>` and `GET /api/events/capture/<capture>` and shown at
`/events/(inbox|capture)/:id`. Not the research Dossier: nothing is frozen, evaluated or scored, and nothing enters
research summaries.

- Anchors: an Inbox entry ID (its feed identity) or a capture ID. An entry version is its content fingerprint
  (`inbox_archive.content_sha256`, now also on every item of the inbox view).
- Links: `POST /api/intake` may carry `"origin": {"item_id", "content_sha256"}` beside the four form fields. It is
  checked before capturing (the entry must be held, current or archived, at that exact version; else 409 or 422 and
  nothing is captured), removed from the form, and recorded after the capture as `data/event-links/<capture>.json`
  (created exclusively, read-only): the capture, its request SHA-256, the entry ID, version number and fingerprint,
  its title, link and raw timestamp, and whether the captured headline and source URL still matched. The capture's
  request is built from the form alone. A link is verified on every read against the capture's request SHA-256 and
  located among the entry's versions; one that does not verify is reported and left unchanged.
- Joins: only by these IDs and links. No headline, date, similarity or retrieval-time matching; several captures of
  one entry are listed separately; shared retrievals link nothing.
- Sections: source (feed metadata with every archived version, or the capture's supplied time, captured text and
  origin); triage (results in `triage_plan.build_index` for the exact `headline_triage.fingerprint` of the entry
  version: current or earlier configuration, re-check provenance, claims, a count of other versions with results,
  and relations from responses whose scope included this version, labelled as suggestions); draft and review
  (`analysis_library.capture_analysis`, the reader My analyses uses; a review is current only against the exact
  draft-view fingerprint); market context (`event_context` and `market_store` as the market-context page reads them:
  unsupported, unreadable, needs_date, stale_confirmation, no_data, partial or complete).
- Context-date confirmations (event-market-context-0.2) keep the entry version's content fingerprint; when the entry
  changes, the latest confirmation is reported as being for an earlier version and no context date applies until a
  new version is confirmed (a repeat of the same date for the same version writes nothing).
- Processing history (`second_order/event_history.py`, event-history-0.1), in both overviews as `history`: dated rows
  in five steps, each with a state, tone (info, done, warn), label, detail, version, link to the existing record and,
  for sent work, a cost. source: each archived version (first and last seen, feed timestamp, text parts, the retrieval
  records that listed it and kept its response; versions first seen before any record are stated as a limitation) or
  each imported version; for a capture, its origin entry's versions. triage: every verified saved request whose
  entries or comparison context hold the entry, mapped to a held version by its exact input fingerprint, with one row
  per attempt (accepted, accepted on a local re-check, not accepted, provider error, no reply, uncertain for a paid
  send without a recorded reply, interrupted, invalid) or "prepared; nothing was sent", and the entry's result when
  accepted; snapshot records are not offered. analysis: each capture whose origin link verifies, its capture row and
  its attempt's row (none: nothing was sent; mock or paid draft outcome; invalid; uncertain). review: each human-review
  version, current only when bound to the view served now. use: freezes from verified freeze records whose capture is
  linked (`assessment_records.draft_links`, store read-only; none checked without a store); research intake is
  closed, so a freeze is never research use. Costs keep apart the planning estimate (whole request), the usage-derived
  cost and billing, which is never verified locally; unknown stays null. State: not_processed (no attempt and no
  capture; a valid state), processed, or needs_attention (an uncertain send or a failed or unreadable step). Limitations
  name captures without a recorded origin (counted, never attributed), unreadable requests, links and records, and
  that keyword matches, related-research links and opened pages are not processing steps.
- Processing index (`GET /api/events/processing`, event-processing-index-0.1): per entry ID, whether a verified saved
  request asked for its result, whether one was accepted (model or simulated) or attempted without a usable result, and
  how many captures' origin links verify for it. Reads only; for the Inbox list's chip.
- The review screen's way back accepts only `/analyses…` or `/events/(inbox|capture)/<id>`.

## Interface freeze (Hypotheses)

`second_order/lifecycle.py` (version lifecycle-freeze-0.1) with `freeze_origins.py`,
served under `/api/lifecycle` for the one research store the server was started with
(`serve --store`, default `data/real/second-order.db`; `create_app` without a store
answers 503 on every lifecycle route). Reads: the store's state and frozen hypotheses,
baselines (the store's board-h15 snapshots and the kept packages), freezable drafts with
reasons, one frozen hypothesis, and one freeze action's outcome. Writes, each a same-origin
JSON POST with the lifecycle header: upgrade the store to schema 3, import a kept package
(package_snapshots; creating a schema-3 store when none exists), preview (writes nothing)
and approve one freeze.
- Manual origin: a strict form (headline, source URL, publication time with an explicit
  UTC offset, story ID, summary, authoring statement, and one leg per registered H.15
  observable with direction, horizon, link, channel, rationale, falsifier, headline flag
  and exactly one primary leg; no defaults). The map is built deterministically (event,
  one channel node per distinct channel, one observable node per leg). Engine: provider
  manual, model "Entered in the Second Order interface form; authoring as stated: …", and
  prompt_hash = SHA-256 of the exact submitted input (manual-hypothesis-input-0.1), which
  the freeze action keeps. Date-only publication times are refused (no time is invented).
- Model origin: a Tracker draft of the paid run (tracker-live-1), read through the
  verified readers (analysis_library), with a draft outcome, built under draft-prompt-6,
  whose latest review version is bound to the exact view fingerprint served now and has
  status human_reviewed. Mock drafts, declines, invalid responses, technical failures,
  draft-prompt-5 drafts and missing, stale, invalid or not-approved reviews are refused
  with their reasons. Only the review's permitted corrections are applied (summary; leg
  rationale, falsifier, headline_reports_move). The engine is the model's (provider
  anthropic, the answering model, prompt_hash = the saved request's SHA-256); the derivation
  (draft, capture, view fingerprint, prompt version, request/response hashes, model output
  SHA-256, review version and corrections) is recorded in the freeze action.
- Preview: validates the effective hypothesis as frozen now, requires every leg on the
  board-h15 provider and a baseline of that provider, then reports blockers rather than
  refusing: a schema-2 store, a baseline received after now, freshness policy B, readiness
  below min_windows, or the same request already frozen. Its binding (lifecycle version,
  freshness policy, effective hypothesis, origin, baseline, source bindings, New York
  freeze date) gives preview_sha256. It also shows the baseline's provenance, readiness,
  the expected scoring window from the SIFMA calendar (expected, not measured) and the
  classification.
- Freeze: the body names inputs, preview_sha256 and approve_freeze true (no freeze time
  field). A recorded action with that ID is returned as is. Otherwise the preview is
  recomputed at the server's clock; a different SHA-256 (review, content, baseline, policy
  or New York date) refuses with 409 and the new preview; a preview with blockers is
  refused unless this action was just recorded by another request. store.freeze_with_action
  then runs every freeze check inside BEGIN IMMEDIATE, refuses another approval of the same
  request (request_identity), and inserts the hypothesis, its binding and the freeze action
  together. Concurrent requests with one approval produce one freeze; the others return it.
- Lost reply: GET `/api/lifecycle/actions/<preview SHA-256>` reads whether that approval
  froze a hypothesis; the page never resends an approval by itself.
- Everything frozen here is a prospective showcase under the daily date convention:
  H.15 observations do not meet the research timestamp gate, and research intake stays
  closed. A freeze evaluates nothing, prepares no Dossier, acquires no outcome data and
  calls no model (assessment: next section); GETs and page loads write nothing.
- Verified with temporary stores, SYNTHETIC packages and a fake provider only; no real
  freeze or live model draft has gone through it.

## Interface assessment (Hypotheses)

`second_order/assessment.py` (lifecycle-assessment-0.1), `assessment_records.py` and
`outcome_retrieval.py`, served by `assessment_api.py` for the server's one store.
- Readiness (GET, reads only): the expected scoring window from the SIFMA calendar and
  the New York freeze date; for each candidate outcome, the dates the engine would
  measure, from evaluation.scored_window on the series pinned from the baseline and that
  outcome (history before the publication date from the baseline only). States:
  horizon_not_elapsed (a target date has not ended in New York; a date-only observation
  counts only after its date ends, and no publication time is promised), outcome_missing,
  missing_values (a source-stated gap in a leg's window, or another stated reason, will
  make that leg unavailable; nothing is filled), ready, recorded. The journal's own state
  comes from recorded metadata only (outcome_held, outcome_in_package for a kept package
  that needs only an import).
- Compatible outcome: a snapshot of the hypothesis's own provider that verifies (its ID is
  the SHA-256 of its payload; its copied source bytes match their recorded SHA-256; its
  classified rows match the recorded statuses, last date, source text and values), other
  than the baseline, received at or after the baseline and before now, classifying every
  leg's series from on or before the publication date. A FRED-bound hypothesis is offered
  only local FRED snapshots: nothing fetches FRED data or substitutes H.15.
- Outcome import (POST): one kept, accepted package, received after the baseline and
  covering the publication date, imported by package_snapshots from the publication date;
  an existing snapshot of that package that already serves is reused, and a repeat reuses
  its snapshot. A package that does not verify is refused with its problem.
- Preview (POST, writes and evaluates nothing): binds the assessment version, the
  hypothesis ID and the SHA-256 of its stored record, its request identity, provider,
  baseline and outcome IDs, the active rules and their hash, the cutoff and its rule, the
  readiness state, each leg's event anchor, scoring anchor, target, state and gaps, the
  stored evaluations of the hypothesis and whether this is a reassessment, giving
  preview_sha256. The cutoff is the latest of the outcome's receipt time, the effective
  freeze and the end (23:59:59 New York) of each leg's measured target date; it contains
  no clock reading, so a preview has no time-based expiry, and it must not be later than
  the server's clock. Blockers: a store below schema 4, readiness other than ready or
  missing_values, outcome problems, or an identical assessment already stored (same
  outcome, rules hash and cutoff). The freeze record pins no rules; the preview names the
  rules its freeze-time readiness check used, if recorded, and the active ones applied.
  The verdict and measured values are not computed or shown before approval.
- Assess (POST, "Evaluate and prepare Dossier"): the body names inputs, preview_sha256,
  approve_assessment true, reassessment (must equal whether evaluations are stored) and
  the previewed binding. A recorded action with that ID is returned as is; otherwise the
  preview is recomputed and any difference refuses with 409 and the new preview (unless
  this approval was just recorded elsewhere). evaluate_bound then evaluates only that
  hypothesis on the bound outcome, rules and cutoff; a pending leg or a date differing from
  the preview refuses with nothing recorded. store.record_assessment, in BEGIN IMMEDIATE,
  looks up the action, requires the stored evaluations to equal those the approval bound,
  refuses an identical evaluation, and inserts the evaluation and its action together.
  Then prepare_dossier prepares that assessment's Dossier; if it fails, the evaluation
  stays saved and the reply says "Evaluation saved; Dossier not prepared".
- Prepare (POST): prepares one stored evaluation's Dossier (from the interface or an
  offline command) without recording anything; an existing file that verifies is
  returned, one that does not is left alone and reported.
- Lost replies: GET `/api/lifecycle/assessment-actions/<preview SHA-256>` and
  `/api/lifecycle/retrievals/<plan SHA-256>/<attempt>` read what an approval recorded; the
  page never resends.
- Outcome retrieval (lifecycle-outcome-plan-0.2, its own approval scope): for 1 to 20
  selected H.15-bound frozen hypotheses, every expected session from each publication date
  to its latest expected target; sessions on or after today's New York date are listed and
  never requested; past sessions are held when a serving snapshot classifies them or an
  accepted kept package received after the hypothesis's baseline states them; past sessions
  not held that the Board's release cannot state yet (before 4:15 p.m. New York time on the
  weekday after them, h15_release) are listed as awaiting release, with the moment from
  which they can be obtained, and never requested; the other missing past sessions need one
  request for the whole release package, shared by every selected hypothesis. Dispatch
  reuses market_retrieval's fetcher and keep-and-validate path
  (`_send`) under the market store's write lock, on a server started with
  `--enable-market-retrieval`, with the plan recomputed before sending, an attempt record
  written before the request (market-context/lifecycle-attempts/, attempt version
  lifecycle-retrieval-attempt-0.1) and its outcome after, no redirect, retry or fallback,
  and the transfer and archive limits. The kept package records the lifecycle approval. A
  FRED-bound hypothesis is refused. Nothing is imported or assessed by a retrieval.
- Journal and reads: `/api/lifecycle` lists every frozen hypothesis with its lifecycle
  state, origin, provider, expected target and every stored evaluation by record time
  (none selected by result), with how it was recorded and its Dossier's state; GET routes
  serve one assessment exactly as stored and one prepared Dossier, verified.
- Draft links (GET `/api/lifecycle/draft-links`): from freeze actions whose identity is the
  SHA-256 of their binding, whose stored hypothesis rebuilds from the approved content at
  the recorded freeze time, and whose effective content matches its SHA-256; joined by the
  draft ID they recorded, with the review version used at freeze. Records that do not
  verify are reported, never linked. No draft, view, request or review is rewritten.
- Everything assessed here is a prospective showcase: no success rates, research
  denominators or claims of validated forecasting performance.
- Verified with temporary stores, SYNTHETIC packages and fake transports only; no real
  outcome download, evaluation or Dossier preparation has gone through it.

## Research readiness (Hypotheses, read-only)

`second_order/research_readiness.py` (research-readiness-0.2), served as GET `/api/lifecycle/readiness?published=`
for the server's one store and printed by `research-readiness [--db] [--published] [--packages-dir]`. For one
publication date (default: today in New York) it reports every registry entry and keeps three questions apart:
- Freeze readiness: a source-bound entry is ready when a snapshot of its provider verifies (verify_snapshot), was
  received before now, classifies the last expected session before the publication date (Snapshot.coverage, freshness
  policy B's own test) and gives at least one horizon the scorer's reference windows under the active rules
  (snapshot_readiness, as check_history uses it). No other threshold is applied. A provider is ready only when one
  snapshot serves all of its observables, because a hypothesis binds one provider and one baseline. Otherwise the
  entry is waiting (that session has not ended) or needs a baseline, with each blocker named, and the next explicit
  action: import a kept package that reaches the session, validate a kept package, approve one H.15 download, run a
  FRED import (network, key), or import again with an earlier start. An H.15 download is proposed only from 4:15
  p.m. New York time on the weekday after that session (h15_release, the rule the outcome plans share: the Board
  posts the release on business days at 4:15 p.m. with the previous business day's values, and a holiday or a
  closed Board only delays it); before then the action says to wait for that release, and a waiting H.15 entry names
  it.
- Outcome data: the expected scoring window on the SIFMA calendar for a freeze on the New York freeze date (the
  lifecycle's rule). Outcome data cannot exist before a target date ends, so their absence never blocks a freeze.
- Research use: not possible while INCLUSION.md's status (quoted from its Status line) is unchanged, the freeze-draft
  command and the interface freeze showcase drafts only, and every connected observable is dated, not timed (the
  research timestamp gate records such a research leg as unavailable).
- Registry concepts without a source (yield:us2y, yield:us10y, index:dxy, fx:usdils, the futures, us_equity and
  us_etf) are reported as concepts with no provider and no held data, never as operational: a freeze on them could be
  stored by the general freeze command, but every leg would be unavailable. The demo fixture is reported apart
  (`demonstration`, and provenance.fixture = demo-market.json): FICTIONAL demonstration series that cover no registry
  concept.
- Reads only: nothing is imported, validated, migrated, frozen, evaluated or fetched, and no key is read from the
  environment. Plain-language answers come first; the snapshots, packages, rules hash, calendar identity and policy are
  returned as technical provenance. The page refuses a reply whose parts disagree (a ready provider without a shared
  baseline, a registry concept with a provider, an entry that is not ready without a reason).
- Verified with temporary stores and SYNTHETIC packages, including a SYNTHETIC dry run from readiness through freeze
  to outcome readiness and a SYNTHETIC rehearsal of one pilot night through the assessment
  (tests/test_pilot_rehearsal.py); on the real store it was run read-only, with every file's hash, size and time
  unchanged.

## FOMC pilot ledger (read-only)

`second_order/pilot_ledger.py` (fomc-pilot-ledger-0.3), printed by `pilot-ledger [--db] [--definition] [--table]`.
It reads content/pilot/fomc-pilot.json (fomc-pilot-0.1: the scheduled statement dates, each with story ID
fomc-<date>; the start timestamp, null while the status is proposed and required once approved; the fixed legs; and
the owner's not-held, missed and note fields) and the research store, opened read-only.
- One case per statement: the story group's first freeze, ordered by freeze time and then hypothesis ID. Later
  versions (another direction, horizon or text) are listed as extra freezes, never counted, never a replacement;
  their assessments are listed, not counted. A first freeze outside the rules (another publication date, frozen
  after New York midnight, not a prospective showcase) makes the statement missed. A first freeze whose legs differ
  from the definition (identified by observable ID: a swapped primary, a missing or extra leg, another horizon) is
  nonconforming: frozen and shown with its reasons, never in the summary, never replaced. A hypothesis on a
  statement date under another story ID is listed as unmatched.
- The start: start_utc is a UTC instant before the first statement's expected publication (2:00 p.m. New York
  time). A case whose stated publication time is earlier, compared as instants, is before_start and never
  included; with no case, the expected publication is compared.
- States: not_started (no start timestamp), before_start, scheduled, open, pending, assessed (by the case's first
  evaluation), nonconforming, missed (the owner's reason or "no freeze recorded inside the window") and
  not_held. Counts reconcile: scheduled = not held + not started + before start + upcoming + included; included =
  frozen + missed; frozen = pending + assessed + nonconforming; extra freezes are listed apart. The summary
  (primary and secondary labels, eligible, and "k of E eligible primary legs had observations consistent with the
  frozen hypothesis") is built from the assessed, conforming cases only; labels are read by observable ID.
- Each statement's freeze window: from the Board's release of the session before it (h15_release) to New York
  midnight, in New York time and converted per date to Israel time.
- Reads only: nothing is written, frozen, assessed or fetched. Verified with SYNTHETIC hypotheses frozen through
  the app's routes and SYNTHETIC records in temporary stores (tests/test_pilot_ledger.py): later versions leave the
  count unchanged; a first freeze with horizon 1, a swapped primary, or a missing or extra leg stays out of the
  summary; publication before and after the start on the same day, in different offsets.
- Practice (0.5.47): tests/pilot_drill.py runs one SYNTHETIC case by hand, with the Hebrew steps in
  docs/pilot/fomc-pilot-drill.he.md: draft, preview, freeze, outcome download and import, assessment, and the journal.
  It is test infrastructure in a practice folder outside every checkout (default: second-order-pilot-drill in the
  system's temporary folder): its own store, one kept and validated SYNTHETIC H.15 package (through 2026-12-08,
  requested at 4:30 p.m. New York on 2026-12-09), the committed showcase Dossiers and a byte copy of
  content/pilot/fomc-pilot.json, which is only read. Its server answers on 127.0.0.1:8765 (port 8000 is refused) on a
  simulated clock (integration_controls.Clock; the computer's clock is neither used nor changed) that starts at 4:35
  p.m. New York on 2026-12-09 and moves by `clock night|outcome-early|outcome`; its outcome download goes to an
  in-process fake of the Board's server that answers only with the sessions posted by the simulated time (4:15 p.m.
  New York, the next weekday), and the Event Inbox's feeds refuse every request. `ledger` reads the drill's store and
  copy at the simulated time. tests/test_pilot_drill.py drives the whole case through the app's routes (every
  database it opens is in the practice folder, no socket is opened), and `npm run test:browser:pilot-drill` walks it
  in the pages at 1280 and 375 px, every step fitting a phone's width.

## Treasury findings pilot (retrospective, descriptive)

`second_order/insight_evidence.py`, `insight_events.py`, `insight_rules.py`,
`insight_text.py` and `insights.py`, served by `insight_api.py`. A retrospective,
single-market pilot: not cross-sector discovery, not research evidence, not a measure of
forecasting performance. No model, provider or network is involved; every number comes
from code and every sentence from a fixed template.
- Evidence (insight-evidence-0.1): the newest accepted kept H.15 release package, read
  through market_package's protected parser and member checks (no DTD, entity or external
  resource); the structure entries, which begin with a DOCTYPE, are never opened. Seven series, each required with its exact attributes
  (FREQ 9, Percent:_Per_Year, UNIT_MULT 1): nominal constant maturity RIFLGFCM03_N.B,
  RIFLGFCY02_N.B, RIFLGFCY05_N.B, RIFLGFCY10_N.B; inflation-indexed RIFLGFCY05_XII_N.B,
  RIFLGFCY10_XII_N.B; and the discount window primary credit rate RIFSRP_F02_N.B, read
  from its raw rows as context only. Each yield series is classified on the SIFMA
  calendar; a stated gap stays missing. A package has no vintage, and shared
  Treasury/Board/FRED lineage is a dependency, never corroboration.
- Events: captures (date basis supplied), Event inbox Federal Reserve and BLS entries
  (confirmed, else the New York date of the feed timestamp as unconfirmed metadata;
  ambiguous timestamps have no date), case library cases (editorial: recorded by an
  editor, not independently verified). Records join only when publisher, canonical URL
  (https, lowercase host, no query or fragment) and date agree, keeping every originating
  record; disagreeing dates are a date_conflict, recurring titles never merge. Supported
  families: Federal Reserve monetary policy, BLS Employment Situation, BLS CPI; others are
  listed as outside the pilot. An occasion is one New York date; co-dated releases share
  one measurement.
- Measurement (insight-rules-0.1): the grid is the union of the six yield grids. B1 and
  B6 are the last and sixth grid dates before the event date, A1 and A5 the first and
  fifth after it. W1 = B1 to A1 and W5 = B1 to A5 include the event date's own session
  when it is a grid date (span 2 for W1, else 1), so they never isolate an announcement;
  PRE = B6 to B1. Measures: the four nominal and two real yields, 5- and 10-year
  breakevens (nominal minus inflation-indexed) and the 2s10s slope (10-year minus
  2-year); W1 and W5 for all nine, PRE for the 2-year and 3-month yields. Changes are
  exact decimal bp; a missing endpoint leaves a change unavailable, with no interpolation
  or shifted date. Reference windows have the measured window's span and end at grid
  indexes m-249 to m (m = its start); rank = (smaller + 1/2 x equal absolute changes) /
  eligible windows, with at least 200 eligible.
- Rules (exploratory, designed after inspecting this dataset): R1 (5y and 10y, W1 and W5)
  nominal rank below 0.5 while real and breakeven ranks are 0.8 or more with opposite
  signs; R2 (same subjects) nominal rank 0.9 or more and the component with the larger
  absolute change has the nominal sign and at least 0.75 of the two components' combined
  absolute change, both components shown in bp (a zero nominal change or zero components is
  never met: no share is defined); R3 (W1, W5) 2s10s rank 0.9 or more; R4 (2-year, 3-month) PRE rank 0.9 or more
  with W5 below 0.5, or the reverse. Twelve checks per occasion, each met, not met or not
  evaluable.
- Comparison sessions (insight-comparison-0.1): 200 grid dates from 2005-01-03 to
  2025-12-31 ordered by SHA-256 of the recorded seed and date, excluding any whose B6..A5
  span contains an occasion's date; each check's met/evaluable counts there describe how
  common the pattern is, never a p-value or chance probability.
- Records (write-once, data/insights/): results/<id>.json, id = SHA-256 of the result
  version, definitions SHA-256, occasion date and the SHA-256 of the exact observations
  read (yields from the earliest reference start to A5, discount-rate rows of B6..A5),
  keeping the package it was first computed from; comparisons/<id>.json; checks/<id>.json
  with the package read, each event with its records, date and basis, and each occasion's
  result, its ID excluding the check time so an unchanged repeat writes nothing. Event
  membership, order, packages and timestamps never invalidate a result; a newer package is
  used only by the next explicit check. Reads verify check and comparison records against
  their IDs and recompute each result's evaluation and policy context from its stored
  inputs, refusing (never showing) any that differs or was computed under other
  definitions; comparison counts are bound only through their identity.
- Routes: GET /api/insights, /api/insights/occasions/<date>,
  /api/insights/events/(inbox|capture)/<id> read only; POST /api/insights/checks with
  exactly {"check_retained_evidence": true}, from this origin with the insights header,
  returns 201 when it wrote a check record and 200 otherwise; no kept package is a 409.
- Output: each finding shows its observations with series IDs and dates, the comparison,
  what it adds beyond the headline and the 2-year/10-year context, an inference labelled
  as not observed, alternatives, and what would strengthen or weaken it. A zero-finding
  occasion is stated with its numbers; unsupported, undated and unmeasurable entries are
  listed with their reasons.
- Verified with SYNTHETIC packages and temporary folders, and once against the retained
  real package in a bounded local retrospective exercise (private, not committed).

## Industry findings (G.17, retrospective, descriptive)

`second_order/g17_evidence.py` (g17-extract-0.1), `g17_rules.py` (g17-rules-0.1),
`g17_text.py` and `g17_insights.py`, served by `g17_api.py`. Separate from the Treasury
findings; not research evidence, not a measure of forecasting performance. No model,
provider or network is involved.
- Evidence: only files named by the outcome records of acquisitions g17-release-tables-01
  (release.html) and g17-industry-tables-01 (table1.htm): complete HTTP 200 responses with
  complete-response hashes, the file still at its recorded SHA-256, at most 2 MiB, under
  its release folder and archive address. Table 2, inspection reports and notes are not
  read. Rows and columns are resolved through the tables' id/headers attributes: a row's
  path is its section and ancestor rows (its indent class must agree), a value's column the
  header cells it names. Refused: no G.17 identity; a release date other than the folder's;
  a last update other than the release date; another heading, title or unit than "Table 1
  Industrial Production: Market and Industry Group Summary" / "Percent change, seasonally
  adjusted" (summary: "Seasonally adjusted"); monthly columns other than six consecutive
  months marked [r] with the last [p]; a repeated path or id; a value cell not naming its
  row; a value other than a one-decimal rate or blank (a blank stays missing); Table 1's
  Total IP, Manufacturing, Mining or Utilities differing from the release summary in any
  month, or months and markers differing. An extract's ID covers its content and source
  hashes, not retrieval times.
- Comparisons (exact decimals on printed rates; a printed 0.0 has no resolvable
  direction; blank = missing): within one release and reference month, Manufacturing,
  Mining (21) and Utilities (2211,2) against Total IP, and each NAICS-coded child of
  Durable or Nondurable manufacturing (under Manufacturing (NAICS), 31-33) against that
  parent: opposing, same, no_direction (which side printed 0.0) or unavailable, with the
  gap (row minus parent) in percentage points. Across two releases (earlier first): Total
  IP and every INDUSTRY GROUP row matched by path and code, each shared reference month:
  reversal (both directions known and opposite), to_printed_zero, from_printed_zero,
  same_direction, unchanged (equal printed values) or unavailable, with the revision in
  percentage points. Broad Manufacturing and Manufacturing (NAICS) are different rows;
  market groups, Table 2 aggregates, index levels, weights and contributions are not used.
- Records (write-once, data/insights/g17/): extracts/<extract id>; releases/<id> with id =
  SHA-256(result version, definitions SHA-256, extract id); revisions/<id> with id =
  SHA-256(version, definitions, earlier and later extract ids) for consecutive selected
  releases; checks/<id> with the selection and the records it maps to, id excluding the
  time. Every input is validated before anything is written; a repeat writes nothing, a
  changed selection reuses unchanged results, and a new release adds an extract, a release
  result and a revision pair without touching others. Reads verify every record against
  its ID and recompute the comparisons in memory; a mismatch is refused, and results under
  other definitions stay on disk but are shown only after a new explicit check.
- Output (g17-text-0.1): divergence cards from the latest selected release printing each
  month, opposing only, ordered by month (latest first), absolute gap, then path, at most
  six with totals; revision cards are strict reversals between consecutive releases,
  ordered by absolute revision, month, path; changes to or from a printed 0.0 are listed
  apart; parents printed 0.0 are listed as having no directional comparison. Each card
  states the observations (rates, path, code, column, release date as published, Table 1
  address and hash), what it adds, an interpretation labelled as not observed, and
  card-specific limitations. Library cases are linked when their source address is the
  release's (no title matching). No time zone is attributed to release dates.
- Routes: GET /api/insights/g17 and /api/insights/g17/tables read and verify only; POST
  /api/insights/g17/checks with {"check_retained_g17": true} and optionally "releases",
  from this origin with the insights header; 201 when a check record was written, 200
  otherwise; no retained release is a 409, an invalid one a 409 with its reason.
- Verified with SYNTHETIC pages shaped like the Board's, and once against the three
  retained real releases in a private local acceptance run (not committed).
- Manufacturing breadth (`g17_breadth.py`, g17-breadth-0.1; `g17_breadth_text.py`):
  universe = the 11 coded rows directly under Durable manufacturing and the 8 under
  Nondurable manufacturing, a fixed list of path and NAICS code; a release whose rows
  differ (missing, extra, moved or recoded) has breadth "unavailable" with the difference,
  and its industry findings stand. Per release and month: positive, negative, printed-zero
  (0.0 or -0.0) and missing counts, overall and by group, expected 19, members, and the
  Manufacturing (NAICS) printed rate. Shares (count / 19, printed zeros in the
  denominator) and states (majority_up or majority_down when count x 2 > 19, else
  no_majority) exist only when nothing is missing; otherwise the state is incomplete and
  the month enters no finding. Findings: aggregate_vs_breadth (complete; aggregate printed
  up or down; more than half printed the other way); breadth_shift (consecutive complete
  months of one release with different states); breadth_revision (the same complete month
  in consecutive releases with a different state or aggregate_vs_breadth condition). Every
  revised month records count changes, strict reversals, changes to or from a printed 0.0
  and coverage changes, and flags unchanged counts with switched members. Cards: one
  aggregate_vs_breadth card per month from the latest selected release printing it, shifts
  from the latest selected release only, revisions for every consecutive pair; ordered by
  kind then month; at most six with totals. Records (write-once): breadth/releases/<id>
  (id = SHA-256 of version, breadth definitions and extract ID), breadth/revisions/<id>
  (both extract IDs) and breadth/checks/<id> naming the G.17 check; the G.17 check reply
  reports breadth work created and reused; reads verify by recomputation; other breadth
  definitions are kept and shown only after a new explicit check. Unweighted counts, not
  contributions, weights or the whole economy.

## Electricity by sector (EIA Table 7.6, retrospective, descriptive)

`second_order/electricity_evidence.py` (eia-t76-extract-0.1), `electricity_rules.py`
(electricity-rules-0.1), `electricity_text.py` and `electricity_insights.py`, served by
`electricity_api.py`. Separate from the Treasury and G.17 findings; not research evidence,
not a forecast, not a recommendation. No model, provider or network is involved.
- Evidence: only files named by the outcome records of acquisitions eia-mer-table76-01
  (table76/T07.06.csv, at most 8 MiB; table76/sec7_19.pdf, at most 4 MiB; both with a
  passed format check) and eia-mer-inspection-01 (inspection/landing.html, context only):
  complete HTTP 200 responses from the expected addresses with complete-response hashes,
  each file still at its recorded SHA-256. The CSV is the only source of values: exactly
  the columns MSN, YYYYMM, Value, Column_Order, Description, Unit; exactly the eight
  published series (ESRCPUS, ESCCPUS, ESICPUS, ESACPUS, ESTCPUS, ELDUPUS, ELTCPUS,
  ESVHPUS) with their column order, description and unit (Million Kilowatthours); one row
  per series and YYYYMM; MM 01-12 monthly, 13 annual (kept apart, never a month); values a
  plain decimal or "Not Available" (missing). Anything else is refused. The definitions
  (title, unit, column footnotes a-j, markers, notes, printed edition) were transcribed
  from the PDF's page image and are bound to its SHA-256; another PDF is refused. The
  landing page's release-date statements are read from its bytes. Inspection reports are
  not read. The CSV's edition is never assigned; the extract ID covers its content and
  source hashes, not retrieval times.
- Rules (exact decimals): each month from 2025-07 to 2026-06 against the same month a year
  earlier, and 2026-01..06 against 2025-01..06 (each sector summed first, rates never
  averaged). Analyzed: residential, commercial, industrial retail sales; context:
  transportation (railways only) and total retail sales; excluded: direct use, total end
  use, electric vehicle use. Change in million kWh and percent of the prior; up when change
  x 100 >= prior, down when <= -prior (inclusive), otherwise little_changed; unavailable on
  a missing value or a prior of zero or less. Percentages are kept to two decimals
  truncated toward zero. A monthly finding needs an analyzed sector up and another down;
  one per month. Reconciliation: the four sales sectors against total retail sales,
  within_rounding when |residual| <= 0.0025 million kWh (five values each published to
  0.001), else beyond_rounding (shown, never forced); contributions to the change in the
  total (four sectors and the rounding residual) only when every month involved reconciles.
  The 1% band is a fixed product filter, not significance, calibration or materiality.
- Record (write-once, data/insights/electricity/results/<id>): id = SHA-256 of the result
  version, extract version, rules version, definitions SHA-256, scope and extract ID; it
  holds the definitions, the extract with provenance, the result and its computation time.
  An existing record is reused when it verifies and never overwritten; a concurrent action
  creates it once. A read validates the sources and recomputes the record in memory and
  shows it only when the stored record equals it apart from its time; other versions,
  scopes or sources are kept and not shown; changed or missing sources show a problem.
- Output (electricity-text-0.1): coverage (months compared, file range, retrieval time;
  the last month is never called current), sources with separate provenance and edition
  notes, twelve months with each comparison and class, one card per diverging month (latest
  first) and one for January-June when it diverges, each with observations, what it adds
  to the total, an interpretation labelled as not observed, contributions, a day-count note
  and six disclosures (retail sales not total consumption; not weather- or
  calendar-adjusted; no price normalization or output inference; preliminary status not
  marked; a single acquisition, not a revision history; no cause established), the
  January-June table, the reconciliation and the method with the footnotes.
- Routes: GET /api/insights/electricity reads and verifies only; POST
  /api/insights/electricity/checks with exactly {"check_retained_electricity": true}, from
  this origin with the insights header; 201 when the result was written, 200 when reused;
  unaccepted sources a 409 with the reason; a stored result that does not verify a 409.
- Verified with SYNTHETIC files shaped like the retained ones, and once against the
  retained real files in a private local acceptance run (not committed).

## Cross-source comparisons (G.17 and EIA Table 7.6, descriptive)

`second_order/g17_columns.py` (g17-columns-0.1), `crosssource_rules.py`
(cross-source-rules-0.1), `crosssource_text.py` and `crosssource_insights.py`, served by
`crosssource_api.py`. Descriptive comparisons, not transmission findings or research
evidence. No model, provider or network is involved.
- G.17 evidence: the same retained Table 1 pages and validation as the industry findings
  (acquisition record and SHA-256, identity, dates, title, unit, id/headers structure),
  then two rows by path and NAICS code (Manufacturing (NAICS) 31-33; Utilities / Electric
  2211) and two columns resolved through the header cells each value names: "Fourth quarter
  to fourth quarter" with one four-digit year, and the 12-month column, whose heading must
  be the release's latest monthly column against a year earlier. Values are one-decimal
  rates or blanks (missing); anything else refuses the release. Its own extract ID; the
  g17-extract-0.1 records and IDs are untouched.
- EIA evidence: the retained Table 7.6 CSV as in Electricity by sector (identities, units,
  monthly rows apart from annual totals, decimals or "Not Available"; definitions bound to
  the PDF), reading the five sales series for each fourth quarter and 12-month period.
- Rules: periods are the fourth quarters of 2023-2025 against the previous fourth quarter
  and each 12-month period a retained release prints. EIA: October-December totals (all
  three months in both years) or the month against the same month a year earlier; change in
  million kWh, percentage truncated toward zero to two decimals; "not_covered" outside the
  file's range, "unavailable" for a missing value or a prior total of zero or less. G.17:
  the latest retained release printing a fourth quarter (every release's value listed), or
  the release whose 12-month column is exactly that month (with its marker); no month is
  substituted. Signs (industrial comparison only): same_sign, opposite_signs or no_direction
  (an exact zero EIA change or a printed 0.0); no threshold; not the ±1% categories. No
  growth rates are subtracted or combined. The customer breakdown decomposes EIA total
  retail sales (four classes and the rounding residual) when every month reconciles within
  0.0025 million kWh; it is not a decomposition of G.17 output.
- Record (write-once, data/insights/cross-source/results/<id>): id = SHA-256 of the
  result, columns, extract and rules versions (including electricity-rules), definitions,
  scope, the EIA extract ID and every G.17 columns extract ID. Reused when it verifies,
  never overwritten; reads recompute and compare; other versions or sources are kept and
  not shown.
- Output (cross-source-text-0.1): coverage (EIA range, retrieval, unassigned edition, the
  G.17 releases), two tables with each value's release, marker and source, sign-only labels,
  measures, the differences that keep them from being the same measurement, possibilities
  labelled as not established, links to the G.17 and electricity parts, and limits
  (vintages differ; source dependence unresolved, so agreement is not corroboration; observed
  periods only; no cause).
- Routes: GET /api/insights/cross-source reads and verifies only; POST
  /api/insights/cross-source/checks with exactly {"check_cross_source": true}, from this
  origin with the insights header; 201 when written, 200 when reused; unaccepted sources and
  a stored result that does not verify are 409s.
- Verified with SYNTHETIC pages and files, and once against the retained real material in a
  private local acceptance run (not committed).

## Related Cases (historical announcements, local matching)

`second_order/related_cases.py` (related-cases-0.1, view related-cases-view-0.1),
`related_rules.py` (related-match-rules-0.1), `related_matches.py` (related-match-0.1, view
related-match-view-0.1), served by `related_api.py`. Research navigation, not prediction,
scoring or research evidence. No model, provider, embedding or network is involved.
- Cases: content/related-cases/collection.json and one file per case, read strictly (exact
  fields, strict JSON, one-line NFC text) and refused whole on any problem. Each case cites
  one retained source (approval related-cases-sources-01: request number, folder,
  SHA-256, bytes, media type, request and receipt times; retrieval times are never the
  release date). Facts have IDs and verbatim quotes (single spaces, at most 600
  characters). The summary, dates, scope notes, actors, tags and comparison points cite
  facts by ID; every digit sequence the summary, fact texts, date labels, scope notes,
  actors and comparison points state must appear in the quotes of the facts they cite.
  Interpretation states no digits: channel titles and texts (each channel cites facts) and the
  reading note. Dates are
  kinds announcement (exactly one), action, effective, publication or deadline; a stated
  date must appear in the source's own wording ("October 7, 2022") within a cited quote; an
  unstated date is null with a note. Provenance is fixed: ai_assisted true, human_review
  not_reviewed, research_use excluded, currency historical; prepared after the announcement;
  sources_read is exactly the case's source. Tags name values of the rules' vocabulary; a
  case needs an instrument, an agency, and a sector or a country. Cases are listed in
  announcement order; the collection lists the coverage not built.
- Source check (on every case read): when the retained page is on the machine, its size and
  SHA-256 must equal the record, every quoted passage (facts, title, dateline) must appear
  within one text block (stdlib HTML parser; script, style, noscript, svg, template and
  title skipped; whitespace collapsed; NFC; nothing executed), and the acquisition record,
  when present, must agree (outcome complete, HTTP 200, URL, hash, bytes, retained path,
  times, content type). States: verified, absent (served, saying the copy is not here),
  different (the size or hash differs, so quotes are not checked; or the quotes are found but
  the acquisition record disagrees). Missing quotes in a page with the recorded hash refuse
  the case (500). The page is never served.
- Inputs: an Inbox entry's current version (or latest archived one): title and feed
  excerpt (none when the excerpt repeats the title); a capture: headline, supplied source
  text and the host of its source address. Hint: the accepted paid headline-triage result
  for exactly that entry version's fingerprint (for a capture, its verified origin entry
  version), current configuration first; its event type and summary are scanned as hint
  fields. Simulated results are never hints.
- Rule (related-match-rules-0.1), pure:
  ```
  tag(fields): for each dimension d in (instrument, sector, geography, agency) and each value v
      of the fixed vocabulary, the whole-word, case-insensitive matches of v's patterns in each
      field (acronyms such as PRC, OFAC, DPRK, UAE and "Entity List" keep their case; a source
      host names an agency only through the fixed host list); each occurrence keeps its term,
      field and whether the field is a hint.
  for each case c in collection order:
      shared[d] = values of d in the event  intersect  c.tags[d]
      if shared[instrument] and (shared[sector] or shared[geography]):  related
      elif shared[instrument] or shared[sector] or shared[geography]:     overlap (listed, not related)
      else:                                                              not listed
  related order: number of non-empty shared[d] (agency included), descending; then collection order
  rests_on_hint(c) = every shared instrument occurrence is a hint, or every shared sector and
      country occurrence is a hint
  differs(c, d) for d with case values: "different" when the event names values of d and none
      is shared; "also_names" when it names others besides shared ones; unknown when it names none
  ```
  There is no score, threshold, probability or ranking beyond that order. "What differs" is
  stated only from values the event names; the case's comparison points are listed as not
  compared.
- Record (write-once, data/related-cases/matches/<id>.json): id = SHA-256 of the match,
  rules and collection versions, the collection content digest, the subject (inbox: entry ID
  and content SHA-256; capture: capture ID, request and source SHA-256) and the hint's
  identity (entry, fingerprint, mode, triage ID, configuration key, event type, summary).
  Stored: the inputs present, the tags with occurrences and the rule's result, plus
  computed_at. Reused when it verifies, never overwritten; a read recomputes and shows the
  stored record only when equal apart from computed_at; records under other bindings are
  counted and not shown. Headline-triage records are only read.
- Routes: GET /api/related-cases (collection), GET /api/related-cases/:id (case with source
  check), GET /api/related-cases/events/:kind/:id (stored match or not_checked) read only;
  POST /api/related-cases/events/:kind/:id/matches with exactly {"find_related_cases": true},
  from this origin with the x-second-order-related header; 201 when written, 200 when
  reused; a stored match that does not verify is a 409.
- Verified with SYNTHETIC events and stand-in pages; the committed cases against the
  retained pages on explicit opt-in (SECOND_ORDER_RELATED_SOURCES) and once in a private
  local acceptance run (not committed).

## Related research (navigation to library content)

`second_order/related_research.py` (related-research-0.1, view related-research-view-0.1), served by
`related_api.py` (GET only). Navigation to existing cases, apart from Related Cases' matching; never a comparison of
mechanisms, a prediction or evidence. Inputs: the event's own stored title (or headline), feed excerpt (or supplied
source text), address and stated date; saved headline classifications are not used. Targets: the case library's cases
and the historical cases. Nothing is stored or fetched; selection runs on each read. A case library that is not
installed gives no library links and a note; an invalid one is refused.
- Event date: the calendar date its feed timestamp or operator-supplied time states, as written (no zone conversion);
  unreadable or absent gives none.
- Event-specific address: https, no fragment, credentials or port, host and path in EVENT_ADDRESSES (EIA
  todayinenergy/detail.php with exactly id=<digits>; Federal Reserve press-release pages and dated G.17/H.8 release
  folders; BLS archived release pages; BIS press releases; Treasury press releases; WTO news pages), query kept exactly;
  anything else (landing pages, BLS's current-release pages) is not event-specific.
- Rules, in order:
  ```
  same_event(e): a = address(e) is event-specific; exactly one target cites a; date(e) is stated;
      every held event (Inbox items and retained entries, verified captures) citing a states date(e); date(e) = the
      target's publication date.  If a is cited but any condition fails: no link, a note, and the citing targets are
      held back from the weaker relations.
  release_family(e): family_of(title(e), url(e)) = (f, d) (the title names d's pattern and the address is on f's host
      and path); date(e) is stated; candidate = the latest target with family f and date <= date(e) (ties by ID); the
      link states d against the target's document, the time between them and the target's reference period.
  topic(e) for each topic t: every term group of t is found in e's own text (whole words, case-insensitive); date(e) is
      stated; t's case has date <= date(e).  Each topic's case must state every group in its own title or summary, or the
      vocabulary is refused (500).
  A topic may carry a stated difference that each of its links includes (trade-environment-wto: the forums differ).
  links: same_event, then release_family, then topics; each target once (strongest kept); historical targets the
      event's stored, verified historical match lists as related are dropped; at most MAX_LINKS = 4.
  ```
  Later targets are counted and noted, never suggested. Each link carries the target's status (editorial: AI-assisted,
  not human-reviewed, not research evidence, source read online and not retained; historical: facts quoted from a
  retained page, source-check state) and its writing date, marked as after the event when it is.
- Route: GET /api/related-research/events/:kind/:id; 404 for an unknown kind or event. Verified with SYNTHETIC events;
  the real collection was read once in a private local acceptance run (not committed).

## Research views (retrospective, source-grounded)

`second_order/policy_research.py` (policy-research-0.1, view policy-research-view-0.1, catalog
policy-research-catalog-0.1), served by `research_api.py` (GET only). One committed file per view,
content/research/<id>/research.json; the first, semiconductor-policy, compares ten BIS press releases (October 2022 to
February 2026) chosen by reading the records the snapshot's semiconductor keyword filter matched. It is a retrospective
comparison of selected retained publications: not a monitor of current policy, legal or compliance guidance, or
evidence of effects. Several releases of one publisher are not independent corroboration.
- Binding: the snapshot's approval, attempt, SHA-256, size, retrieval time and extractor version; per publication its
  address, record key (SHA-256 of the address, 20 hex), record SHA-256, paragraph count, title and listing times
  (published, CMS created, CMS changed); per release page its approval, attempt, folder, SHA-256, size, retrieval time
  and dateline.
- Seven dimensions per publication, none defaulted: instrument, stated relation to earlier publications, technology
  or product scope, jurisdictions/actors/end uses, supply-chain stages, announcement and effective dates, exceptions
  and conditions. Each holds a short label and statements with one status: stated (the publisher's words, at least
  one quote), interpretation (the curator's reading, at least one quote as its basis), not_stated (the retained text
  does not say it; no quote) or referenced_unread (the text names a document not retained; the reference is declared
  with the passage naming it). Supply-chain statements are always interpretation (or not_stated), each naming one stage
  of design_software, equipment, fabrication, memory, chips, computing_systems, ai_models.
- Quotes: {paragraph (1-based), quote}, 8–320 characters, one line, no markup, heading or table tokens. Every figure in
  a label, statement or observation must appear in the passages it cites (or, for labels and observations, in the
  compared publications' listing dates as a release prints them, UTC); "why this helps" states no figures. A fixed list
  of claim words (confirm, prove, cause, buy, sell, signal, recommend, repeal, forecast, mispricing, "does not exist")
  is refused anywhere in curator text except the list of claims not made; quotes are not scanned.
- Stated dates live only on stated timing statements: kind (effective, compliance, comment_deadline, license_deadline,
  issued, conduct, designation), precision day (YYYY-MM-DD equal to the quoted "Month D, YYYY"), year (a quoted year)
  or relative (no calendar value), and as_stated quoted from the statement's passages. A dateline is shown only from a
  release page that verifies; listing times are never presented as datelines.
- Comparisons: id, kind (stated_change, instrument, non_equivalent, different_subjects, dates), question, the compared
  publications in chronological order, observation, evidence (at least two items, every compared publication cited;
  each a quote, a listing field with its exact value, or a term reported absent from a publication's text), why,
  unknown and would_establish.
- On each read: the retained page is verified against its acquisition record (bis_snapshot.locate) and extracted in
  memory, memoized per verified SHA-256 (never written). A publication is verified when its record matches every bound
  field and every quote of its statements, references and comparison evidence lies in the stated paragraph; missing
  when the snapshot is not on the machine; changed otherwise (bytes differing from the acquisition record, another
  snapshot version or extractor, a differing record, a quote no longer found). A comparison is available only when all
  its publications verify and its absent terms are still absent; unavailable when one is missing; needs_revalidation
  otherwise. Unverified publications and comparisons that are not available withhold their statements, observation,
  evidence, why and unknowns, and list the problems. A release page (here the 2022 page retained under
  related-cases-sources-01 and the Applied Materials page under bis-semis-sources-01) is verified by size, SHA-256,
  acquisition record and dateline; the listing's paragraphs must then appear in order directly after the dateline
  (text status "checked"); a missing or changed page only withholds its dateline and check.
- Records considered and not included are listed with reasons and checked the same way (identity only); case links
  (library or historical) must name existing cases, or the view is refused.
- Routes: GET /api/research (the committed views, content only: no source is read) and GET /api/research/{id} (404
  for an unknown or malformed id; an invalid file or an unreadable case library refuses with 500). No POST.
- Verified with SYNTHETIC sources and a SYNTHETIC research file (tests/policy_research_fakes.py); the committed file is
  checked against the real retained sources only on explicit opt-in (SECOND_ORDER_POLICY_RESEARCH_SOURCES=<the
  retained data/sector-sources folder>). A private acceptance review of every comparison is kept under
  data/policy-research/ (not committed).

## Theses (copper: physical balance, status, exposure)

`second_order/thesis_schema.py` (thesis-0.1, index thesis-index-0.1, catalog thesis-catalog-0.1) and
`thesis_sections.py` load and check a thesis; `thesis_rules.py` holds its text rules, `thesis_arithmetic.py` its
decimal arithmetic and status rules, `thesis_sources.py` and `thesis_workbook.py` the checks and readers of retained
files, and `thesis_view.py` (thesis-view-0.1) builds the reply, served by `thesis_api.py` (GET only). A thesis is a
stated research view on one topic, kept in versions: the view, the balance in numbers, where it differs from what
others publish, reasons, risks, what would change the view, who is exposed, a view log, a price record, plain notes and
the claims not made. It is written in a working session and committed as content; the app never generates or edits
it. The first, copper, reads the physical copper balance from retained IEA, USGS, World Bank and company sources. It
is not a view on the price, not a monitor of current markets and not evidence of effects.
- Files and versions: content/theses/<id>/index.json (thesis-index-0.1) lists versions 1, 2, … in order, each
  {version, file v<n>.json, sha256 of the file's canonical JSON (a CRLF checkout still matches), published_on}.
  published_on is a date, or null for a draft, which only the last version may be; dates do not decrease, and a version
  is not published before its prepared_on. published_on lives only in the index, so publishing never changes a version
  file. Version n > 1 is valid only when version n-1 is: the same opened_on, n-1's log kept as an exact prefix, at
  least one new entry dated on or after n-1's publication, a new view entry when the view text changes and a new
  confidence entry when the confidence level changes. Files are strict UTF-8 JSON of at most 2,000,000 bytes; ids are
  lower-case ([a-z0-9]+ joined by hyphens).
- Current limits of the version chain, to be settled before version 2 is written: a log entry is required only when
  the view text or the confidence level changes, so a changed reason or risk status, a changed view status or view
  citations, or a changed confidence basis needs no entry; and every log entry's refs are checked against the current
  version's reasons and risks, so a reason or risk that a logged entry names cannot be retired in a later version (the
  kept entry would name an id the version no longer has, and the whole thesis would be refused).
- Version file: exactly 24 fields, each required and none defaulted: thesis_version, id, version, previous_version,
  title, topic, opened_on, prepared_on, confidence {level low|medium|high, basis}, sources, figures, passages, view,
  balance, differs, reasons, risks, conditions, exposure, log, price_record, plain, not_claimed and provenance
  {prepared_by, method, and the fixed ai_assisted true, human_review not_reviewed, research_use excluded}. Every listed
  source, figure and passage is used by some element, and the ids of tables, differs entries, reasons, risks and
  conditions are distinct.
- Sources: {id, kind (html, xlsx, csv, pdf), origin (get or owner_download), publisher, title, series, edition,
  edition_date, url (https, without credentials or a port), approval_id, attempt, folder, name (one file name),
  sha256, bytes, retrieved_at (an ISO time with an offset, not after prepared_on), terms {licence, note},
  transcription, encoding}; no two entries name one retained file or one acquisition attempt. A PDF's transcription is
  {pages, method}: exactly the pages its figures and passages cite, ascending, each once, and one of two methods,
  "transcribed from the page image" or "transcribed from the PDF's text layer", as used; no other kind has one. Only a
  CSV declares an encoding, utf-8 or windows-1252, read strictly and never guessed. edition_date is an ordering key
  only: the day the publisher states for that edition (on the retained file or in a publisher record kept in the
  acquisition folder), or the first day of a stated month or year, never an HTTP Last-Modified, upload or file-metadata
  date. The schema checks only that it is a date (a default-run test pins each copper date). The reply carries it;
  the page shows the edition text, never the date. Figure and passage lines, problems and balance-table bases name a
  source by publisher and edition text, adding its title where another listed source has the same publisher and
  edition (in copper v1, the MCS 2026 data release and the MCS 2026 copper chapter).
- Figures: {id, source, measure, unit, value (a plain decimal as text), as_shown, year (four ASCII digits, or null),
  period (null, a month YYYYMmm, a quarter YYYYQn or a day, within the year), basis, scenario (the publisher's name, as
  printed), locator}. as_shown is the value as printed (an optional $ or %; one grouping character used for every
  group: comma, space, no-break, narrow no-break or thin space) and must equal the value exactly. Units: kt,
  million_t, t, kg, kg_per_unit, usd_per_tonne, usd_per_lb, usd_cents_per_lb, usd, usd_million, percent and count,
  each shown with a label. Locators by kind: html {paragraph, quote} and pdf {page, quote} (a figure's quote holds its
  as_shown), xlsx {sheet, cell, label_cell, label}, csv {row (2 or more), column, label_column, label}. Quotes are 8–320
  characters, one line, not starting with #, without | or <. Passages {id, source, locator} quote an HTML page or a
  PDF only.
- Author text (the title and topic, statements, labels, a figure's measure and basis, why_not, through, the price
  record's series, plain notes, log entries, the confidence basis and the provenance's prepared_by and method) is one
  line within its limit, and is refused when it uses a claim word of Research views (above) or matches
  thesis_rules.PRICE_DIRECTION: a fixed set of market-view and valuation terms, and "price", "prices" or "pricing" with
  a word of movement, direction, pressure, tightness or support among the five words after it, or a word of direction
  or pressure (higher, lower, rising, falling, tighter, weaker, stronger and similar) among the five words before it.
  Neutral wording ("a change in the price") passes. Not scanned: not_claimed (where claim words and these phrasings
  belong), quotes, scenario names as printed, the source entries' fields and company names. A label of what others
  expect may name another institution's published expectation with the one claim word kept for that
  (thesis_sections.ATTRIBUTION_WORDS, singular or plural) and no other. A figure (digit run) in author text must appear
  in what the text cites (a figure's printed and plain value, year and period; a passage's whole quote; for the price
  record's series, its opening and latest figures) or among its element's computed outputs; text that cites nothing
  states none, and the thesis's own title and topic, the confidence basis, provenance, plain notes and log entries state
  no figures at all.
- Statements: {status, text, cites}: stated (a source statement), interpretation (the author's reading) or not_stated
  (not stated in the sources). not_stated cites nothing; the others cite at least one figure or passage, none twice.
- Sections. view: one statement. balance.tables (at least one): {id, title, gap computed|not_computed, why_not, rows};
  rows (at least one, years increasing) {year, kind historical|projection, demand_total (above 0), supply_total, lines
  [{label, figure}]}, every figure of the row's year and named once, a projection row's figures each with a scenario; a
  computed table draws every figure from one source, basis, scenario and unit and has no why_not, and a not_computed
  table says why not. differs (at least one): {id, about (a statement), others (at least one {cite, label}), differs
  (true or false)}. reasons (3 to 5) and risks (at least one): {id, title, statement, plain, measure}; only a risk's
  measure may be null (not tracked). conditions (at least one): {id, text, figure, comparator below|above, threshold
  (a plain decimal)}. exposure: movers (at least one) {company, moves (a reason's id), through, cites (at least one)};
  moved (at least one) {company, side producer|consumer, how (a statement), amount}, the amount stated {kind, figure}
  or computed {kind, per_unit (kg_per_unit), price (usd_per_tonne), unit_price (usd, or null)}, a computed amount's
  per_unit, price and unit_price (when given) each above 0. log (at least one): {date, kind
  opened|status|view|confidence|note, text, refs}; the first entry, and only it, is the opening, dated opened_on; dates
  do not decrease and are not after prepared_on; refs are distinct reason or risk ids, at least one for a status entry.
  price_record {series, opening, latest}: two figures (they may be one) from one source, in one unit, usd_per_tonne or
  usd_cents_per_lb (nothing is converted), each with a year and periods of one kind, the opening's not after the
  latest's. plain: nine notes (view, balance, differs, reasons, risks, conditions, exposure, log, price), beside each
  reason's and risk's own. not_claimed: at least one line. An element that cites no figure or passage is refused
  (ruling R15): the view through its statement (so a not_stated view, which cites nothing, is refused), a reason or
  risk through its statement or measure; every other kind is given its figures or passages by the fields its shape
  requires, and the page's reader refuses any element, of any kind, that lists no item.
- Comparisons: a reason's or risk's measure is {latest, previous, compare (revision or period), supports_when (a
  reason) or grows_when (a risk), each higher or lower, material_change_pct (above 0)}. Its two figures are distinct,
  of one measure, unit, basis and scenario, each with a year; years are compared as integers. From one source, that is
  one retained edition, compare must be period and the latest year after the previous one: a revision within one
  source (the same year) is refused. From two sources: one series and two editions, so the two sources' edition text
  differs (two files of one edition, such as a data release and a chapter of the same edition, are refused), the latest
  from a strictly later edition_date; revision compares the same year and the same period within it (both null, or the
  same month, quarter or day), period a later year. A period comparison, from one source or two, compares periods of
  one kind (years, quarters, months or days). A previous value of 0 is refused. The page states which comparison each
  status makes: two years within the same edition, or two editions, and the rule its status is read by, adding that
  the change is shown rounded to one decimal while the status is read from the exact figures. Preferring a previous
  edition when one is retained, and using one vintage where the latest edition restates the earlier year, are
  authoring practice, not schema rules.
- Statuses are computed on every read from the exact figures and never stored. change = (latest - previous) /
  |previous| x 100, in exact decimals. A reason is unchanged when the change is smaller than material_change_pct in
  either direction; otherwise it is strengthening when the latest figure is higher (or lower) than the previous one as
  supports_when names, and weakening when it moved the other way; a change equal to the threshold counts. A risk is
  likewise unchanged, materialising (the grows_when direction) or receding, and not_tracked without a measure. A
  condition has happened when its figure is strictly below (below) or strictly above (above) its threshold; a figure
  equal to the threshold has not.
- Computed values, by fixed code, ROUND_HALF_EVEN and comma-grouped, displayed exactly as author text is held to them:
  in a computed table, each row's gap = supply_total - demand_total at the precision of its figures, labelled surplus,
  deficit or balanced, and its weeks of demand = |gap| x 52 / demand_total, multiplied before dividing, to one decimal;
  a change in percent to one decimal; a condition's threshold at the precision written (threshold_value is the plain
  decimal; both are withheld with the condition); a computed amount's cost per unit = kg per unit x USD per tonne /
  1,000, in whole dollars, and, with a unit price, its share of that price from the whole-dollar cost, to one decimal.
  A not_computed table only sets published figures side by side; a stated amount computes nothing, and a computed one
  without a unit price computes no share.
  The page shows the served numbers; its fail-closed reader (frontend/src/thesis.ts) refuses a reply whose states,
  statuses, gaps, weeks, costs, shares or counts do not follow from its figures in exact decimals. It names a table's
  demand row and supply row by the measure every figure of the row states (their common leading comma-separated parts,
  so a qualifier only some add, such as ", estimated", stays on those figures; frontend/src/thesisTotals.ts), or by
  its side alone when they share none; a row is never called a total that its figures are not.
- Exposure map (presentation only; thesis-view-0.1 and the reply are unchanged; frontend/src/thesisExposureMap.ts,
  components/ThesisExposureMap.tsx and ThesisExposure.tsx; docs/copper-exposure-map.md): the "Who is exposed" section
  opens with a map ahead of its two exposure tables, which are unchanged. It gives plain notes on incidence,
  pass-through and operating exposure; one lane per company the thesis moves, on its served side, starting from a
  change in the copper price whatever its cause, with that side's stages kept apart (producer: revenue, margin,
  operating cash flow; user: input cost, its own selling prices, margin, operating cash flow) and, under them, the
  filing's statement with its served status, a stated figure's metric exactly as served, a computed amount as served,
  and the cited figures and passages to inspect; and one line per company that moves a reason, read only when the
  company and the reason are both available: the reason's measure (a stated line) when the ids it cites include the
  reason's latest measured figure, related to it (a not-measured line) otherwise. A legend names the three kinds of
  line in words (stated in a source, conditional mechanism, not measured); lines carry no arrowheads. The map reads
  only the reply's structured fields, names no company, reads no wording to decide a link and computes no number; no
  figure is placed on a stage, because thesis-0.1 does not say where a figure sits in the accounts. A withheld part
  gives the map its frame only (company, side and stages, or the reason it names with that reason's title as served,
  null when the title states a figure), never its statement, figure, metric, status or anything to inspect.
- On each read: each source is checked against data/sector-sources/copper/acquisitions/<approval_id>/
  outcome-<attempt>.json and its file <folder>/<name>. The record must state a complete acquisition with the entry's
  approval, attempt (the record's n), address, SHA-256, size and retained path; for a GET, HTTP 200, a
  complete-response hash, no other origin and body_completed_at equal to retrieved_at; for an owner download, origin
  owner_download, no HTTP status, an owner-file hash and recorded_at equal to retrieved_at. Then the file's size and
  SHA-256 must match. The source is verified, changed (anything differs, or the record is not one strict JSON object)
  or missing (the record or the file is absent). A verified file is read once, in memory, memoized per retained file
  and SHA-256 and never written: HTML as plain-text paragraphs (strict UTF-8; at most 60,000 paragraphs and 8,000,000
  characters), CSV as rows (strict quoting, in its declared encoding), XLSX one named sheet at a time without trusting
  the archive (thesis_workbook). A reader that meets a limit refuses the whole file, never reading part of it; only a
  workbook sheet whose own part fails is refused alone, leaving the other sheets usable. Each item is then located: an
  HTML item's quote in its paragraph (and a figure's as_shown in that quote); an XLSX figure's label cell reading its
  label and its cell holding the value (a text cell printing it exactly; a number cell storing a number that, rounded
  half-even to the value's precision, equals it); a CSV figure's label column reading its label and its column holding
  the value, in its row, under a header that names each of the two columns exactly once. Labels compare with
  whitespace collapsed. A PDF is never read: its figures and passages are transcriptions bound to the PDF by its
  verified SHA-256 only. A verified file that cannot be read keeps its state, and each item from it gets a problem
  naming the refusal. An item not found gets one problem naming its place ("not found where cited (sheet …, cell …)"),
  never the value or quote.
- Elements: the view; each balance table, differs entry, reason, risk and condition; each company that moves the thesis
  (mover-<n>) and each company it moves (moved-<n>), numbered from 1 in file order; and the price record. Each lists
  its items ({id, source}), its sources and not_found. It is unavailable when any of its sources is missing; it needs
  revalidation when any is changed or an item is not found or cannot be read; otherwise it is available, with no
  problems. An element that is not available shows its frame only (id, title, plain note, the table's gap mode,
  company, side, the reason it moves, the price series, its items); a title or series that contains a digit is
  withheld too, and every other field (texts, figures, a condition's threshold as written and as shown, computed
  values, statuses) is null, with its problems saying why. The reply counts sources and elements by state and
  carries "provider_called": false.
- Routes: GET /api/theses (each committed thesis's latest version, strictly loaded as content only: id, title, topic,
  latest_version, published_on and href /theses/<id>; no source is read), GET /api/theses/{id} (the latest version)
  and GET /api/theses/{id}/versions/{n}. 404 "No thesis has this id" for an unknown or malformed id; 404 "This thesis
  has no such version" for a version that is not 1 to 9999 in ASCII digits without a leading zero, or is not in the
  index. An invalid index, version file or chain refuses with 500, in the list too; a local read error is a 500
  naming only the error's type. No POST, PUT, PATCH or DELETE (405). Nothing is written, fetched or sent.
- Verified with SYNTHETIC retained files and two SYNTHETIC versions (tests/thesis_fakes.py: version 1 with a computed
  balance table and a computed exposure row, version 2 extending its log) in tests/test_thesis_*.py; the served
  replies are captured into frontend/tests/fixtures/thesis-*.json (available, version 1, catalog, draft, revalidation,
  unavailable) and read by the frontend's reader (frontend/tests/thesis.test.ts, thesisRulings.test.ts); `npm run
  test:browser:thesis` drives the page. The committed copper thesis is checked as content in the default run (valid
  and matching its index, published 2026-11-03, its edition dates, no contact address, every part unavailable without
  the retained sources). It is checked against the real retained sources only on explicit opt-in
  (SECOND_ORDER_THESIS_SOURCES=<the retained data/sector-sources/copper folder>, which the browser check also reads):
  every source verified and every element available, with the expected statuses; each figure from the MCS 2026 data
  release on a row whose Country, Statistics_detail, Year and Unit match it and whose Notes mark exactly the estimates,
  each described as an estimate; each IEA figure's cell under its year and scenario, inside the copper block; and
  reading changes nothing.
- Acquisitions, with records under data/sector-sources/copper/acquisitions/ and the retained files beside them (not
  committed): copper-worldbank-01 (three GETs: the Pink Sheet monthly workbook, the World Bank summary terms of use and
  the Commodity Markets Outlook of October 2026, PDF), copper-usgs-01 (two GETs: the Mineral Commodity Summaries 2026
  and 2025 copper chapters, PDF), copper-iea-2021-01 (one GET: the IEA's 2021 report on critical minerals, PDF),
  copper-sec-01 (eight GETs: the fiscal 2025 and 2024 10-Ks of Freeport-McMoRan, Southern Copper, Mueller Industries
  and Tesla, each request declaring a contact that the records note only as declared, never as an address),
  copper-usgs-csv-01 (two owner downloads, each recorded only on a size and MD5 match with its published item record:
  the MCS 2026 data release's commodities CSV and the MCS 2025 copper salient CSV) and copper-iea-dataset-01 (one owner
  download: the IEA Critical Minerals Dataset 2026; the 2025 edition is not offered). Version 1 cites 13 of the 17
  retained files. Not cited: the Pink Sheet's copper series (its Description sheet names third-party sources for it,
  and the retained World Bank terms say third-party data may not be reused without the provider's consent); the terms
  page itself, read for that decision; the IEA 2021 report (it states all rights reserved and restrictions on use and
  distribution, and its per-vehicle copper amounts are chart bars with no printed values); and the MCS 2025 salient
  CSV, which no measure needs once the latest release gives both years. docs/copper-thesis-sources.md records the
  terms read and each decision.

Copper version 1 (opened, prepared and published 2026-11-03; confidence medium) cites 13 sources (the IEA Critical
Minerals Dataset 2026; the USGS MCS 2026 data release and its 2026 and 2025 copper chapters; the World Bank's October
2026 Commodity Markets Outlook table; eight 10-Ks), 63 figures and 21 passages, in 23 elements. With the retained
sources, all 13 verify and all 23 elements are available; with none, all 23 are unavailable. The view (interpretation)
reads the IEA dataset: under Stated Policies, demand grows from 2030 to 2035 while the base case for mine supply falls,
base-case refined supply stays above demand, and the distance between demand and counted mine supply, already there
in the base year, widens after 2030, so the constraint the dataset shows is at the mine, not the refinery. Neither
differs entry departs from what others publish: one sets the dataset's other two scenarios beside Stated Policies, the
other quotes the World Bank's 2026 copper expectation with its label, as an expectation about the price and not about
the balance. Reasons: electricity networks +12.9%, electric vehicles +45.3% and the counted mine pipeline -15.6% (IEA
2035 against 2030, within one edition) and Southern Copper's expected production -5.6% (its fiscal 2025 and 2024
10-Ks) read strengthening; world mine output 0.0% (2025 against 2024 within the MCS 2026 data release) reads
unchanged. Risks: US copper recovered from old scrap +14.3% (the same release) reads materialising; demand outside
energy technologies +2.7% (IEA 2035 against 2030) reads unchanged; aluminium substitution and building in China are
not tracked. Neither condition (a later IEA edition putting 2035 base-case mine supply above, or refined supply below,
this edition's 2035 Stated Policies demand) has happened. Freeport-McMoRan, Southern Copper and Tesla move reasons;
Freeport-McMoRan and Southern Copper (producers) and Mueller Industries (consumer) are moved, each by an amount its
own filing states. The price record is the USGS U.S. producer cathode annual average (COMEX + premium) for 2025, 490 US
cents per pound, an estimate, as both opening and latest. The log holds the opening entry. Its stated limits: no table
computes a gap (the IEA table sets demand per scenario beside one base case for supply, with no figure for recycled
supply, and the United States refined table is one importing country's context, met by trade and stocks); no cost
per electric vehicle is computed, because no retained source prints a per-vehicle copper amount the thesis may use;
four IEA measures (three reasons and the other-uses risk) compare projection years within one edition, so their
statuses show the shape of one projection;
one material change, 5%, serves every measure and was set after the figures were read, and two statuses sit near it
(Southern Copper's -5.6% just past it; other uses' +2.7%, which half of it would read as receding); every PDF figure
and passage was read from the PDF's text layer, with no page image rendered (the one PDF figure is the World Bank's
expectation; the chapters supply passages only); and the price record is one USGS annual estimate, a record beside
the view, not evidence for it. Because no table computes a gap, the slice's planned minimum of one computed balance
table is not met; computed tables and computed exposure rows are tested only on the synthetic versions.

## Copper tools (coverage calculator and producer comparison)

`second_order/copper_inputs.py` (copper-inputs-0.1) loads the committed inputs catalogue and checks it against the
retained copper folder; `copper_coverage.py` (copper-coverage-0.1) is the coverage calculator; `copper_producers.py`
(copper-producers-0.2) the published producer unit-cost comparison, the company-stated projects and the
capital-recovery panel; `copper_scenarios.py` (copper-scenario-0.1) the write-once scenario records;
`copper_linked.py` reads Bagdad's later company statement from the verified FCX research; `copper_tools_view.py`
(copper-tools-view-0.2) builds the read and `copper_tools_api.py` serves it. They are tools beside the copper thesis,
not part of it: thesis v1 is unchanged, nothing here writes a view, and every number is a published figure, a user's
assumption or a value fixed code computed. Nothing is a projection by this project, a view on a price, a balance of
supply and demand, a cost curve or an incentive price of the project's own.
- Catalogue: content/tools/copper-coverage/inputs.json, exactly {catalog_version, id, prepared_on, sources, figures,
  passages}. Its five sources are copper v1's entries for the IEA Critical Minerals Dataset 2026 and the fiscal 2025 and
  2024 annual reports of Freeport-McMoRan and Southern Copper, unchanged (a default-run test compares them). Figures are
  thesis figures without a period, plus checks; units kt, t, t_per_year, mlb, mlb_per_year, blb, usd_per_lb,
  usd_million, usd_billion and percent. An XLSX figure's checks name further cells of its sheet that must read as stated
  (the year and the scenario above its column, its block, the sheet title). An HTML figure sits in running text
  {paragraph, quote} or in a table {paragraph, label_paragraph, label, column, header_paragraph, header}: every table
  cell is its own paragraph, the cell reads exactly as printed (an amount in parentheses is negative), it is the
  column-th number cell after its row label and at most 40 paragraphs after it, and a column header before the label
  reads as stated. Passages quote an HTML paragraph or the whole text of one workbook cell. The catalogue holds exactly
  the figures and passages the tools read (199 and 24): anything else refuses the read (500); a missing catalogue is 503.
- On every read each source is checked against its acquisition record (thesis_sources.verify) and each item located:
  verified, not_found, unreadable, source_changed or source_missing. Only a verified figure has a value and only a
  verified passage has text; a problem names the place, never the value. An output that uses an item that is not
  verified is withheld and names it.
- Coverage (exact Decimals): for 2030, 2035 or 2040 and one IEA scenario (Current Policies, Stated Policies, High
  Demand), R = D - M_c, demand not covered by the counted mine pipeline: the IEA's total copper demand less its
  base-case "Copper - Mining" supply. Also R as a share of D (one decimal), R's change since the dataset's base year 2025,
  and its exact decomposition into each published demand row's change, the change in the published non-additivity
  epsilon (the printed energy-technology total minus its printed parts) and delta (the printed total minus energy and
  other uses), and the change in counted mine supply. R is a requirement on other sources (recycling, mines not yet
  counted, stocks or lower demand), never called a deficit; nothing computes a gap, a balance or weeks of consumption.
  The IEA base-case "Copper - Refining" series is shown apart under its source name, with the supply sheet's two notes
  and three things they leave unknown (an output or a capacity basis, scrap refining, a check against feed); it is
  never added to mining supply or set against demand.
- Controls (three, all in kt, none with an invented default): copper used in electric vehicles and copper used in
  electricity networks, each a published scenario's value, the published "Wider direct current (DC) technology
  development" case (networks under Stated Policies and High Demand only) or an entered non-negative value; and a
  counted mine supply adjustment, a signed change in kt or a non-negative factor per country. A change is applied to the
  printed total, D' = D + the sum of (x' - x), never rebuilt from parts; M' = M + dM or M + the sum of (f - 1) M_c. A
  mine change may be tagged with one of two company reference magnitudes (Freeport-McMoRan's change in PTFI expected
  sales, 650 million pounds x 0.45359237 = 294.8350405 kt; Southern Copper's change in expected production, 54.4 kt) and
  must then equal it exactly. Flags: hybrid (a component from another scenario than the total), technology case, user
  value, outside all three IEA scenarios, reference magnitude. Inputs are plain decimals as text (at most 30
  characters and 10 decimals). Recycling is not an input in this version: a request naming recycling, scrap or
  secondary supply in any field is refused (422) before anything is read or written.
- Perturbations: one-at-a-time effects on R around the published baseline, in a fixed order (EV copper, networks, the
  networks technology case, the two reference magnitudes, an entered mine change when there is one, the joint
  published totals), each with its kind of range, never ranked and never given a probability.
- Display: a computed kt value is shown exactly up to five decimals, else to the tonne (three decimals,
  ROUND_HALF_EVEN) and marked rounded; the exact value is kept and feeds every later step.
- Producer comparison: Freeport-McMoRan's U.S., South America and Indonesia divisions and its consolidated figures, and
  Southern Copper's consolidated figures, for 2025, beside a fixed comparability matrix (period, unit, denominator,
  geography, by-product treatment, scope, integration, credits that move with other metals). A row with credits or
  charges is shown only when its figures before credits, its credits and its charges add exactly to its stated unit net
  cash cost; otherwise it is withheld. Cash margins (revenue per pound minus unit net cash cost) only for the three
  divisions whose own revenue per pound is retained; Southern Copper's is withheld. Fixed texts say what reported
  division averages can and cannot establish: they are not any mine's avoidable cost, so they say nothing about closure,
  new supply, the industry's marginal cost or an industry incentive price. Rows are not ranked or averaged.
- Projects: company-stated capacity, capital, timing passages and incentive prices for Bagdad, El Abra, Tia Maria, Los
  Chancas and Michiquillay, with capital per tonne of annual capacity (whole dollars) where both are stated; El Abra
  states no capital. Brownfield and greenfield values are not compared or averaged.
  - Bagdad is two rows, one per company statement, each computed on its own figures only (a pair never takes capital
    from one statement and capacity from the other; the reader refuses one that does). First, bagdad-2026-11-04, the
    company's estimates in its approval release, stamped "Company estimates · stated <date> · Freeport-McMoRan news
    release" with the documents' terms; second, bagdad, the 10-K statement as before, stamped "Earlier statement ·
    signed <date> · <the source's title>". Each stamp's date comes from its source's metadata.
  - The later row's records come from copper_linked's fixed table: nr-bagdad-capex-estimate (capital),
    nr-bagdad-cu-increment (the incremental long-term annual rate, labelled so; the total is not used because the
    capital is incremental), nr-bagdad-breakeven-cu with nr-bagdad-breakeven-mo as its condition (break-even
    economics), nr-bagdad-construction-years, and the passages nr-p-board-approval and q3-p-bagdad-approval (the
    approval, release and 10-Q), nr-p-schedule (the start of production, shown as words only) and the caveats
    nr-p-cost-risk and nr-p-estimates-change (under its capital). The reply's "linked" block holds them with the two
    sources' title, form and date. The reader refuses a linked figure whose printed figure does not read as its value,
    and a row that names a record outside its own statement or in another role: every id in a row's capital, capacity,
    incentive, break-even, construction, passages and caveats is a linked record with that field's role on the later
    row, and a catalogue figure or passage on any other row (break-even and construction only ever linked).
  - All or nothing: an unverified release or 10-Q, a table entry that differs in kind, unit, source or page, or an FCX
    package that cannot be read (CompanyRefused, OSError, KeyError, ValueError, TypeError or AttributeError, at that
    read only) withholds every linked entry with one reason; the later row then shows that reason and no value, and the
    earlier row, the other projects, the coverage view, the capital charge's other rows and the scenarios are served as
    usual (200). No 10-K figure is promoted to current.
  - Break-even economics is its own field and column ("Break-even economics, as stated"); incentive prices stay in
    theirs, and the reader refuses a break-even record among them. Two fixed notes follow the table: neither term is
    defined in these documents and neither is derived from the other; the company gives a first production target and
    a long-term annual rate but no year-by-year path, and nothing between them is shown or assumed. No Bagdad volume
    enters the coverage calculator.
  - Product code holds record ids, roles, unit codes and wording only: every number, date and quote of the later row
    comes from the records and the sources' metadata at read time (a default-run test scans the changed files). Until
    2026-11-11 the release and the 10-Q were retained from the company's investor-relations host for personal,
    non-commercial use, so no public output (the README, its images, a published screenshot or page) showed the later
    row. They are now read from their SEC EDGAR copies (exhibit 99.1 to a Form 8-K, and the 10-Q), and the row's
    stamp states its terms as "SEC EDGAR copy (exhibit 99.1 to Form 8-K); public filing". The earlier copies are
    kept privately and no longer read.
- Capital-recovery panel: no defaults. For an entered rate in percent (0 to 100, at most four decimals) and a whole
  number of years (1 to 100), CRF = r(1 + r)^n / ((1 + r)^n - 1) for r > 0 and 1/n at r = 0 (the capital recovered
  evenly, with no return), and each project's capital charge per pound of stated capacity, exact fractions until shown
  (CRF to six decimals, charges to three). It ignores construction-period interest, ramp-up, sustaining capital, taxes
  and royalties, and closure; it never solves for a price; its inputs are never stored. Each Bagdad row has its own
  charge, on its own statement's capital and capacity; the reader refuses a reply that withholds a row the loaded view
  shows ("reload the page").
- Records: copper-scenario-0.1 {record_version, engine_version, definitions_sha256, catalog {version, sha256}, label
  (1 to 80 characters, refused with a claim word or a view on a price's direction), baseline, assumptions, figures [{id,
  value, source, source_sha256}], result}, with no commentary field; its id is the SHA-256 of its canonical JSON. The
  file data/scenarios/copper/<id>.json, {id, created_at, record}, is written once with exclusive creation: 201 when
  new, 200 with nothing written when it exists, 409 when an existing file does not match its id (never overwritten) or
  the result has a withheld output. On read each record is verified (its figures unchanged and the engine reproducing its
  result exactly), unavailable (a source missing), needs revalidation (with its reasons) or invalid (kept, never used);
  records of another version are counted only. A future authored thesis version may cite a record's id.
- Routes (operator API): GET /api/tools/copper (the whole read) and GET /api/tools/copper/scenarios; POST
  /api/tools/copper/preview (a scenario and the record it would save; writes nothing), POST /api/tools/copper/scenarios
  (saves once) and POST /api/tools/copper/capital-charge (writes nothing). The POSTs accept only same-origin JSON with
  the header x-second-order-scenario: 1. Every reply carries provider_called false. create_app takes copper_inputs_dir,
  copper_sources_dir (default: the thesis's copper folder) and copper_scenarios_dir; the whole read and the capital
  charge also read company_research_dir and company_sources_dir (the FCX page's folders), and the preview, the save and
  the scenarios list never do.
- Tests: the default suite reads SYNTHETIC files whose numbers copy the published values (tests/copper_fakes.py), so the
  design's worked example reproduces; one opt-in class (SECOND_ORDER_THESIS_SOURCES=<the retained copper folder>)
  verifies the committed catalogue against the real sources, read-only, and proves the folder unchanged. The frontend
  reader is tested against replies captured from the server (frontend/tests/fixtures/copper-*.json), and
  copper-tools-check.mjs drives the page, with the same opt-in. Bagdad's later statement is read from a SYNTHETIC FCX
  package by default (tests/fcx_fakes.py: the committed research with made-up documents, and variants that change,
  remove or break one thing each, among them an unrelated record without a value); one opt-in class reads the retained
  FCX documents read-only, and the page check serves them with the review server's --company-fcx synthetic or
  retained. A record saved before this change (tests/fixtures/copper-record-87425ba.json) must still verify, and the
  catalogue's file hash and digest are pinned.
- Current limits: world recycling, stocks and the IEA's demand basis are not retained, so no balance is computed; the
  AI part of the question is named and not measured; two producers are not a cost curve; the reference magnitudes are
  company guidance, not projections; the IEA "Copper - Refining" series' basis is unknown.

## Metals (comparison, stage 1)

`second_order/metals_usgs.py` (metals-usgs-0.2 at stage 1, 0.3 with stage 2) reads the retained USGS data-release
CSV; `metals_iea.py`
(metals-iea-0.1) reads two sheets of the retained IEA workbook; `metals_view.py` (metals-view-0.2 at stage 1, 0.3 with
stage 2, below) verifies both files and builds the read, and `metals_api.py` serves it. The engines read no file: the view verifies each file against its
acquisition record (thesis_sources.verify) and passes the rows or cells in. Every figure is the file's own number, or a
share, rank or ratio computed from the file's own stated total; nothing is curated, estimated, projected or compared
across the two sources. USGS and IEA scopes differ (the IEA's magnet rare earths against USGS's all rare earths, the
IEA's lithium content, graphite by grade) and are shown apart, never compared. The reply carries provider_called false.
- Sources: content/metals/sources.json, exactly {sources_version "metals-sources-0.1", sources}, two entries with a
  source entry's fields and these ids in this order: usgs-csv-2026 (the commodities data file, CC0 1.0, edition date
  2026-02-06, windows-1252) and iea-dataset-2026 (CC BY 4.0, edition 2026). Both are the copper folder's retained files,
  looked up by the same acquisition records. A missing sources file is 503, an unreadable or differently shaped one 500.
- USGS reader: the header must be exactly the twelve columns and every row must have twelve, else the part is refused.
  The reply holds one chapter per name in a fixed list of 45, in that order, each with its id (the name lowercased,
  runs of other characters one hyphen), the display name, whether rows are present, the critical-mineral mark
  (Yes, No, or null when mixed), whether a world table exists, the distinct other notes, its series, its
  years-of-reserves entries, its import-source groups and its net import reliance rows ({commodity, detail, year,
  value} as printed; the commodity since metals-usgs-0.3). A world table is the rows whose
  section starts with "World". A series is one (commodity, statistic, detail without a trailing ", rounded", unit,
  year) of the world table, in file order, with its world and other-countries cells and its named countries; a series
  id is the chapter, statistic, detail, unit and year ids joined by "/", and two series sharing an id refuse the part.
  A cell is {value (as printed), number (the plain decimal when the print is a plain number with optional thousands
  commas and decimal part, else null), notes}; the world cell also carries rounded, true when the world row's detail
  ends in ": rounded" or ", rounded" (USGS rounds that total), and the page labels it "World total (rounded by USGS)".
  Each series also carries unit_issue: null, or the fixed words of metals_usgs.UNIT_ISSUES for its id.
- Unit issues: UNIT_ISSUES names, by series id, a series whose unit the data file states in conflict with the printed
  USGS chapter. One today: vanadium/reserves/reserves/metric-tons/2025, which the file gives in "metric tons" (world
  21,000) while the vanadium chapter of Mineral Commodity Summaries 2026, page 2, heads the same column "thousand
  metric tons" (a factor of 1,000). The chapter is not a retained, verified source, so nothing is converted and the CSV
  is unchanged: the series' words begin "Unit in doubt:", name the chapter and page, and say that the quantities and
  the years of reserves are not shown and that the shares do not depend on the unit. The page shows those words above
  the table, "unit not shown" in place of the unit and "Not shown: unit in doubt" in place of every printed quantity
  (the reply keeps the printed values so the reader can recompute the shares), and keeps every share and the ranking,
  since a share divides two figures of the same column. An issue applies to its exact id only: printed in another unit,
  the series has another id and no issue. A conversion needs the chapter retained with an acquisition record first.
- Shares: a share exists only when the series prints exactly one world total and it is a positive number; it is the
  cell's number over that total as a percent to one decimal, half to even, computed with exact fractions. A cell
  printed in any other way ("W", "NA", ">2,000,000") is shown as printed and its share is its reason, "Printed as
  “W”". When a share cannot exist, every cell's share (the countries' and the other-countries cell's) carries the
  series' no_shares reason: more than one world total, no world total, a world total printed other than as a number
  ("The world total is printed as “>2,000,000”, not as a number"), a world total printed as zero ("The world total is
  printed as “0”, so no share can be computed"), or, for a series with no country rows and no other-countries row,
  "USGS prints no country for this series". A share is of the world total as printed; USGS rounds most world totals,
  so the shares of one series may add up to more or less than 100.
- Concentration: leader (the largest named country) and top3 (the three largest named countries and their combined
  share) rank only the countries USGS names; the page says so in its headings ("Largest named producer", "Three
  largest named producers", "Largest named reserves holder"), in a line above the comparison, under each table
  ("Ranked among the countries USGS names", with the other-countries group's own share where it has one) and in the
  concentration note. "Other countries" is one group USGS does not split ("Other countries (one group, not split by
  USGS)" in each table): it is never ranked and can hold more than a named country, so the combined share is not a
  complete ranking of the world. They are shown only when shares exist, every named country is printed as a number or
  exactly as a dash ("—" after trimming, which the design reads as zero), and at least 1 country is named for the
  leader, at least 3 for the top3 ("No countries
  are named", "Fewer than three countries are named"). A dash counts as zero in the order and the combined share: it
  never outranks a positive value, ties at zero go by name, and its own share stays withheld ("Printed as “—”"). Any
  other print (W, NA, XX, s, a range, a bound or a word) withholds both with the reason in words (a country printed "W"
  is named with its print: that country's size is unknown, so the order is too). Countries are ordered by size, ties
  by name. The other-countries cell never enters a ranking.
- Years of reserves: for each 2025 reserves series paired with the 2025 mine-production series of the same commodity
  and unit whose detail names "mine production" with the same qualifier, reserves over production, world totals, to the
  nearest whole year, half to even, labelled "at the 2025 rate; not a depletion date"; an exact ratio below 1 is shown
  as "less than 1" (the page: "less than 1 year"), never withheld for its size. The reason, when no figure is shown,
  comes from each series in turn, the reserves first: its own world problem, then its unit issue ("Reserves: Unit in
  doubt: ..."; vanadium). It is not a depletion date, and no price, technology or discovery is assumed.
- IEA reader: the workbook's layout is checked cell by cell (the sheet titles, the 2025 and forecast-year headers, the
  three scenario names, the supply year headers, each mineral's block labels, "Total demand" and the share row, the
  "Top 3 share" row, a positive total); any mismatch refuses the whole IEA part with its sheet, cell and rule (no
  value). Six minerals in a fixed order: copper, cobalt, lithium, nickel, magnet rare earth elements (mapped to the
  USGS rare earths chapter, with a scope note), graphite (all grades; natural mining and battery-grade supply blocks).
  Demand: rows by technology for 2025 and 2030-2050 in the Current Policies, Stated Policies and High Demand scenarios
  (IEA projections, marked), and energy_share, the workbook's stored share x 100. Supply, base case, mining and refining
  apart, 2025-2040: each country's value and its share of the printed total to one decimal, half to even; the rest of
  world; the printed total; top3_published, the stored value x 100, the IEA's own figure. Numbers are the shortest
  decimal that round-trips the stored number. The notes under each sheet are carried with each mineral.
- View: GET /api/metals returns {view_version, provider_called, deep (the default picks: copper, lithium, cobalt,
  rare-earths, nickel, aluminum), sources (each with its shown source fields and its verified, changed or missing
  state and detail), usgs, iea}. Each part is {engine, state, problem, chapters (usgs) or minerals (iea)}: available
  with its list and no problem, or withheld when its file is missing or changed (the verification's detail), cannot be
  read, or has a layout the reader refuses, with its list holding frames only (id, name and chapter from this code's
  constants, never from the file) and its problem in words. A USGS layout refusal gives the fixed problem text
  USGS_LAYOUT_PROBLEM, because a refusal message may carry file labels. A withheld part leaves the other unaffected.
  There is no write route; no route fetches.
- Frontend: metals.ts reads the reply fail-closed. A part is available only over a verified source; a withheld part
  holds frames only; every share, ranking, top-3, years figure, IEA supply share and stored x 100 figure is recomputed
  with exact fractions by the engines' own rules and must equal what the server shows, else the whole read is refused
  naming the place and the rule, never a value. It also checks each series id against the series' own chapter,
  statistic, detail, unit and year (made the server's way), each series' unit_issue against its own copy of
  UNIT_ISSUES (so a flag can be neither dropped nor added), and each years entry's pair: a 2025 Reserves series and a
  2025 Production series whose detail names "mine production", of the same commodity and unit, with the same
  qualifier (stage), else the read is refused even when the division would give the same figure; a flagged pair must
  be withheld with the unit issue's words, and an unflagged ratio under one must read "less than 1". It also checks
  the world cell's rounded flag (true or false), the reason for a world total printed as zero, each IEA mineral's
  chapter against the fixed
  mapping (copper, cobalt, lithium, nickel, rare-earths, graphite-natural) the page joins on, and each withheld frame's
  name and chapter against the constants (the chapter's display name and name; the IEA demand title and the mapped
  chapter). The page (pages/MetalsPage.tsx; components/MetalPicker.tsx, MetalsCompare.tsx, MetalDetail.tsx,
  MetalsMethod.tsx and MetalsBits.tsx; metalsPicks.ts, metalsWords.ts; metals.css) computes nothing. It keeps the
  reader's picks in the address as ?m=a,b (known chapter ids only, the first occurrence of each, ignored ids counted;
  the six defaults when none is valid) and its tab in the hash (#by-metal, #by-metal:<picked id>, #method; none for
  the overview; anything else is the overview, and a hash never adds a pick). It opens on a short header (one line
  on the sources' state; the full sentences when a part is withheld), a closed picker and the Overview tab:
  - Picker: one button, closed by default, giving "<n> of 45" and the picked names; it opens a panel with a search
    box (name or id, ignoring case and punctuation), a checkbox per chapter in USGS order, Defaults, Clear and Done.
    Escape and Done close it and return focus to the button; a click outside or focus leaving it closes it; arrow keys
    move from the search box through the visible checkboxes, which stand in one column (0.5.34), so the list reads top
    to bottom in that order. The panel stays inside the screen at phone width.
  - Tabs (the ARIA tabs pattern: arrows, Home and End): Overview, By metal, Method & sources; only the selected
    tab's panel is rendered.
  - Overview: one row per picked metal and 2025 production stage (mine, smelter, refinery and the like, as printed),
    a pick with none getting one row that says so (stage, top named producer, three largest named, top named reserves
    holder, years of reserves). A figure that is not shown gives a short label (metalsWords.shortReason: "Order
    unknown", "World total not a number", "No matching series", "Unit in doubt" and the like, never a claim its reason
    does not make) and a "Why?" button that opens the full reason in place. Each years figure has the caveat "at the
    2025 rate; not a depletion date" in its heading and one click away beside it. A line under the title says the
    ranking is among the countries USGS names, with "Other countries" one unsplit group; "How to read this table"
    opens the longer words. A metal's name opens it under By metal. A withheld USGS part gives a banner and rows saying
    "Withheld", with the problem behind "Why?". Its reserves column uses the reserves series paired with the row's
    production by the years-of-reserves rule (reservesFor in metals.ts, from the years entries), else the chapter's
    only 2025 Reserves series, named by its printed detail, else "No matching 2025 reserves series".
  - By metal: the picked metals as tabs, one metal open at a time. Its USGS tables sit in parts closed on arrival
    (Production, Reserves, US imports and reliance, Notes in the USGS file; a part with a unit issue is flagged "Unit
    in doubt" before it is opened), and, for the six IEA minerals, the IEA part apart (its scope note, then Demand by
    technology, Supply by country and the workbook's notes, each closed).
  - Method & sources: this read's source sentences, the plain notes (metalsNotes.ts: they name no metal, company or
    country and state no price direction, forecast, recommendation or cause) and the Sources list with each file's
    terms. A chapter without a world table (germanium, rare earths (heavy), thallium) says so.
- Withholding: when a part is withheld, its regions of the page hold no value, share, country, detail, note or reason
  that only its file holds (not in rendered text, hidden or collapsed text, or any attribute); only frames (names) are
  shown, the other part's values stay, and the page's own words are the same as with both parts available.
- Tests: the default suite reads SYNTHETIC files (tests/metals_fakes.py) through test_metals_usgs.py,
  test_metals_iea.py and test_metals_api.py, which cover the shares, withheld prints, the reasons above, the layout
  refusals and the withheld parts; the frontend reader is tested against captured replies; and
  frontend/tests/browser/metals-check.mjs (with its plumbing in metals-kit.mjs) drives the page: the picker opened and
  closed by keyboard, click and focus, several picks, picks kept through a reload and a change of tab, the tabs and
  hash, each "Why?", one metal at a time, every metal visited with its parts open for the withholding checks (in every
  tab, hidden text and attributes included), accessible names, and phone width (npm run test:browser:metals; served
  by tests/review_browser_server.py --metals synthetic, or, as an opt-in, SECOND_ORDER_THESIS_SOURCES=<the retained
  copper folder> against the real files, read-only, proving the folder unchanged; SECOND_ORDER_SCREENSHOTS=<folder>
  saves desktop and phone screenshots).
- Current limits: the USGS code key (W, NA, E, XX, s and the like) is not retained, so a print is shown but not
  explained; only the dash is read, as zero, and only to order countries (the design's "a dash for zero"); no stocks,
  owners or by-products are shown (stage 3 of the design; stage 2, below, adds indicators, uses and cited events); a leader or top 3 is withheld where a named
  country is printed W or another non-number (NA, XX, s, a range, a bound or a word), for example lithium's 2025 mine
  production (United States, W), while a dash no longer withholds one (copper's 2025 mine production, Germany "—", now
  has its leader and top 3); vanadium's 2025 reserves carry a unit issue, so their quantities and years of reserves
  are not shown until the printed chapter is retained and verified; rankings cover named countries only, "Other
  countries" being unsplit; three chapters have no world table;
  the IEA covers six minerals; USGS and IEA scopes are never compared. See docs/metals-comparison.md.

## Metals (stage 2: research layer)

Stage 2 adds three engines and three parts to the reply (metals-view-0.3; 0.4 for metals-research-0.2's dated events)
and, for each metal, a snapshot and five folds
to the page. Read-only like stage 1: nothing is acquired, fetched or sent to a model, nothing is written, every reply
carries provider_called false, and no figure here is estimated, projected, scored or combined across the two sources.
- Reply: GET /api/metals now returns {view_version "metals-view-0.4", provider_called, deep, sources, usgs, iea, risk,
  uses, research}. Each new part is {engine, state, problem, ...}: risk (chapters), uses (entries) and research
  (written_by, metals). risk is available exactly when usgs is, and withheld with the USGS problem when it is; uses is
  read from the IEA workbook apart from the iea part, so a layout refusal there (metals_view.USES_LAYOUT_PROBLEM) never
  withholds the iea part, and its problem is the workbook's when the file is missing or changed; research is available
  unless its notes are not the shape this version reads (RESEARCH_PROBLEM). A withheld part holds frames only. A
  changed USGS file therefore makes every risk figure and every research link on it unavailable; a changed workbook
  does the same for uses and the links on it; the other part stays.
- metals-risk-0.1 (metals_risk.py): reads no file; it takes the usgs chapters and the same raw rows. Per chapter: for
  each 2025 Production and Reserves series, named_share (the named countries' figures added, over the printed world
  total, percent to one decimal), over_total (the named figures exceed the printed total, which USGS rounds), and the
  HHI as two bounds, hhi_low and hhi_high (the sum of each named country's squared share times 10,000; the low bound
  treats the unnamed "Other countries" as spread so thin it adds nothing, the high bound as one holder of all that
  remains), or a reason when the series has no shares or a named country is printed other than as a number or exactly a
  dash (a dash counts as zero). Exact fractions, half to even. stages: each 2025 production series with a stage read
  from its printed detail (other if the detail names an export, as mercury's "Mine production: exports" does; else
  mining if it names "mine", refining if "refin" or "smelt", else other) and the
  series' own leader (CR1) and top3 (CR3); missing_stages, the names among mining and refining with no 2025 production
  series, said so and never filled from another stage; leaders_differ, whether the first mining and first refining
  leaders are different countries (null when either is not shown); most_concentrated, the stage whose leader holds the
  largest share; alternatives and reserves_only, named countries whose share of world reserves is larger than their
  share of world mine output in the paired 2025 tables (and those named only in the reserves table), a comparison of
  shares and not a capacity; us: the chapter's first 2025 net import reliance row as printed, {commodity, detail,
  value}, each import-source table's largest source,
  three largest, and HHI bounds with coverage against 100 (a reason when a named source is printed other than as a
  number), and the US secondary-production rows. There is no composite score.
- metals-iea-uses-0.1 (metals_iea_uses.py): reads sheets 3.2 (energy demand by mineral, kt) and 3.1 (by technology) of
  the retained IEA workbook, the layout checked cell by cell, any mismatch refusing the whole part. Each entry is one IEA
  name mapped by a fixed table to a USGS chapter, with a scope note where the IEA's scope differs (lithium content,
  iridium apart from other PGMs, rare earth elements as the IEA lists them); the total of 2025 and of each scenario and
  year (Current Policies, Stated Policies, High Demand; 2030 to 2050, IEA projections), and, where sheet 3.1 splits it,
  each technology's values and its share of the 2025 total to one decimal, half to even. A technology block must print
  the same total as the mineral's row on every key, else the part is refused. Sheet 3.2's Boron and Total rows are
  skipped by name; any other label the mapping does not hold refuses the part at its cell, so a renamed or added IEA
  mineral never drops out unseen. Only energy technologies are covered; a metal with no entry says so.
- metals-research-0.2 (metals_research.py; 0.1 had no event dates and no IEA base): content/metals/research.json, exactly {research_version, written_by,
  metals}, per chapter id {thesis, uses, substitution, recycling, events, chains}, any other key or kind refusing the
  whole file (the research part is then withheld). Written by the assistant from the figures and retained sources, not
  reviewed by the owner (WRITTEN_BY, shown on every chain). A chain has a title, an assumed starting disruption, links,
  who is directly and indirectly exposed, who may gain or lose and through what, what could soften it, and what the data
  shows against what is assumed. Every link is one of three kinds, labelled on the page: measured (a ref naming a
  stage and figure, a reliance year, or an IEA name and technology: a figure the page already shows, or unavailable
  with that part's own reason, never a new number), stated by a source (a passage of the copper thesis, the only
  thesis cited, which thesis_view checks against its retained source on every read; each cited passage carries its
  source entry's title, publisher, edition and edition date, null only when the thesis cannot be read; shown as
  "Title · Publisher, edition · place" when verified, else withheld with the reason) or hypothesis (neither, labelled
  "Hypothesis — not measured or stated by a retained source"). An IEA link over an entry with no technology split says
  "The IEA's table gives no technology split for <name>"; an IEA link that is shown reads "<share>% of 2025
  energy-technology demand (<technology's kt> kt of <entry's total> kt)". Events are cited passages, each {passage,
  kind, when}: `when` is the event's date as its quote gives it (4 to 40 characters with a four-digit year), and once the
  quote is verified it must contain `when` exactly, else the file is refused; only an event whose quote is verified on
  this read is shown as an event.
  Today the notes hold chains for copper, cobalt, lithium, rare earths, nickel and aluminum, and copper's uses,
  substitution, recycling and two events.
- Reader (metalsStage2.ts, called by metalsRefusal after the usgs and iea parts pass): holds each event's `when` to the
  same rules (in its quote once verified); recomputes each risk figure from
  the series cells and import rows (exact fractions), each uses share from the entry's numbers, and each measured link
  from the reply in the server's own words; holds each cited passage's fields to its state (a verified passage has
  its quote, source, title, publisher, edition, edition date and place; one changed, missing or not found has all but
  its quote; one the unreadable thesis leaves unavailable has none); checks the frames of a withheld part. A mismatch
  refuses the whole
  read, naming a place and a rule, never a value.
- Page, per metal (By metal): a Snapshot, always open, whose items each name their source (largest named producer by
  stage; largest single-country share, by stage; largest named reserves holder with years of reserves; US net import
  reliance (the first 2025 row; where the chapter prints more than one, named by its commodity, "One of N 2025 figures
  USGS prints for this chapter" beside it, as in Supply chain and the Overview, which then also names its basis); the
  critical-minerals mark; a unit issue where there is one; the IEA's energy-technology demand for 2025), then folds
  closed on arrival, each with a line on what it holds and opened and closed with Enter or Space: Production and
  Reserves (stage 1), Supply chain, Concentration & risk, Industrial uses, Geopolitical exposure, Economic
  transmission, US imports, USGS notes and the IEA part. A fold's blocks are named by their source and set apart (USGS,
  IEA, quoted from retained sources) and never joined by country.
  - Supply chain: the printed 2025 stages, mining then refining then any other, each with its largest and three largest
    named countries; a missing stage reads exactly "USGS's file has no <mining|refining> table for this metal"; final
    products always read "Final products: no retained source covers this stage."; US import dependence and secondary
    production; possible alternative sources (a share comparison, not a capacity); the IEA's mining and refining by
    country in a block of its own, labelled a separate source and not re-ranked; recycling and substitution as quoted.
  - Concentration & risk: per 2025 production and reserves table, CR1 (the largest named country's share), CR3 (the three
    largest named, combined) and the HHI as its low-high range with the named countries' coverage beside it ("named
    countries 37.4% of the world total", or "..., over the printed total"), then the same for each US import-source
    table (coverage of US imports). Each indicator's heading has an About note (a button; its formula, source and
    data year). No score combines them.
  - Industrial uses: under the note "Demand from energy technologies only, as the IEA scopes them; other industrial
    uses of this metal are not in this table.", the IEA's energy-technology demand by technology for 2025, each technology's share of it and a
    chosen scenario and year (its own two selects), the share of energy technologies in the IEA's total demand for
    the six IEA minerals, end uses quoted from retained sources (copper only), and a note that industrial importance,
    strategic criticality and supply risk are different things.
  - Geopolitical exposure: structural indicators only (the largest named country at each stage and in reserves, whether
    one country is largest at several stages, the largest US import source of each table), and events only from a
    cited passage verified on this read, each quoted with its source's title, publisher and edition and its place,
    its caption giving its kind and date ("Supply disruption · September 2025"), under the note that each event is a
    past one, dated as its source dates it, and that this is not a news feed;
    otherwise exactly "No verified event is retained for this metal. Events appear here only from a retained primary
    source (an official publication or a filing), dated." A cited passage that is not verified is listed apart under
    "Cited, not verified on this read" with its reason and no kind or date. A value the source holds but that cannot be ranked
    or compared reads "Not shown" with its reason; "Not in the retained sources" is kept for data that is absent.
  - Economic transmission: the written-by sentence, then each chain with its links in order, each labelled Measured
    (its value, with the coverage beside an HHI; or why it is not shown), Stated by a source (the quote, source and
    place, or why it is withheld) or Hypothesis, then, under "The assistant's reading" ("Who is exposed, who may gain
    or lose and what could soften it: not measured, and not stated by a retained source."), the exposed, the
    may-gain-or-lose lists and what could soften it, then what the data shows and what is assumed. Copper's links to the copper thesis for company exposure.
  - Overview: a Leaders | Concentration switch (two buttons, aria-pressed): Concentration shows, per picked metal and 2025
    production stage, CR3, the HHI range with its coverage and US net import reliance as printed.
- Withholding (additional): with the USGS file changed, the snapshot, supply chain, concentration, exposure and every
  USGS link of research show the risk part's problem (in each block that holds USGS figures) and none of its values, words or reasons; with the IEA
  workbook changed, the same for uses and the IEA links; the other part stays. The browser check proves it by changing
  one byte of each synthetic retained file and scanning every metal, with every fold open, in every tab. The scan leaves
  out the page's own fixed words, each checked apart: the link badges, the About notes, the selects' options, each chain's
  link count, the five new folds' teasers, the Concentration view's scope words, the page's own IEA year labels where
  they stand (year headings, marked year labels, year-keyed attributes and the year a table frame's name ends with; a
  year printed anywhere else is scanned, which a negative control proves) and one-character values.
- Tests: tests/test_metals_risk.py, test_metals_iea_uses.py, test_metals_research.py and test_metals_api.py (synthetic
  files, tests/metals_fakes.py; the committed research.json against them); the frontend reader against captured
  replies (tests/fixtures); and frontend/tests/browser/metals-check.mjs with metals-kit.mjs (plumbing and the value
  lists of each part), metals-stage2.mjs (each part read off the page and compared with the reply, in any state of
  the sources), metals-controls.mjs (Enter and Space on each new fold, on copper and cobalt; six About notes driven from the keyboard on two metals; the uses
  selects set in code; the Overview switch with Tab, Enter and Space,
  and phone width) and metals-shots.mjs (screenshots): npm run test:browser:metals, synthetic (the server copies the
  committed research.json beside the synthetic sources, so copper's cited events stay unverified) or, opt-in,
  SECOND_ORDER_THESIS_SOURCES=<the retained copper folder> (copper's two events verified and quoted).
- Current limits: no retained source covers final products; the IEA's uses are energy technologies only, so uses
  outside them are quoted for copper alone; no official export-control or sanctions source is retained, so none is
  shown; events are copper's two cited passages only; the HHI is two bounds because "Other countries" is unsplit, not
  a point estimate; there is no composite score, ranking of metals or price view; the research notes are
  assistant-written and unreviewed by the owner, and their stated links rest on the copper thesis's retained sources
  alone (a passage not verified on this read is withheld). See docs/metals-comparison.md.

## Event chains (copper thesis)

One page, `/theses/copper/events` (admin only), shows three copper event chains: each is one possible path from a past
event on a retained official source to a reason or risk of the copper thesis, in three voices kept apart (the source's
words, a general conditional mechanism, the owner's reading). A chain is not evidence that the event caused anything and
is not a forecast; the owner's reading is the owner's own view. Chains and mechanisms are content written by the
assistant; the app reads them and writes only the owner's reviews and readings.
- Versions: event-chain-0.1 (a chain version), event-chain-index-0.1, event-mechanisms-0.1 and
  event-mechanisms-index-0.1 (the shared mechanism list), event-chain-review-0.1, event-chain-reading-0.1,
  event-chains-view-0.1 (the reply), metals-research-0.3 (the register accepts an `fcx:<passage id>` reference beside
  `copper:<passage id>`, verified through company_research_view on every read; the register gains one event, the
  Bagdad approval) and metals-view-0.5. research_use is "excluded" on every chain version, and nothing here enters the
  store, a score, readiness or a thesis status.
- Files: content/metals/mechanisms/index.json and v<n>.json (entries {id, text}; one line of at most 240 characters
  starting "When " or "If ", no digits, never a statement about one event); content/theses/copper/event-chains/<chain
  id>/index.json and v<n>.json (id, version, previous_version, title of at most 100 characters, event, target
  {kind reason|risk, id}, steps, evidence, change {answers_review, note} or null in version 1, provenance); a published
  version never changes. Steps in order: the event as a stated step, further stated steps (`copper:` or `fcx:`
  passages, each with a label of at most 80 characters), `not_stated` lines ("No retained source states ...", at most
  160 characters) and at least one mechanism. No measured or hypothesis steps. A label may hold a digit only if its
  quote holds it; titles, mechanisms, `not_stated` lines and change notes hold none. Modules: event_chain_schema.py,
  event_chain_evidence.py, event_chain_records.py, event_chain_price.py, event_chain_text.py, event_chain_view.py,
  event_chain_api.py, event_chain_cli.py. Records: data/event-chains/reviews/<chain id>/NNNNNN.json and
  data/event-chains/readings/<chain id>/NNNNNN.json, created exclusively and never rewritten; these are the only files
  the app writes. Reads never fetch, and GET routes and page loads write nothing.
- Evidence pin: `python -m second_order event-chains pin --chain ID --version N --published-on YYYY-MM-DD` (working
  session only; it fills a version's `evidence: null` from the live records, checks it as the app would load it, and
  appends the version to the index with its SHA-256; a version already indexed is refused). evidence is {event,
  passages, documents, thesis, mechanisms}: the register entry {passage, kind, when}; each cited passage once {ref,
  source, location, quote}; each retained document of the cited passages and of the target element {ref,
  acquisition} (the acquisition fields the verifier reads); the thesis {id, version, sha256}; the mechanism list
  {version, sha256}. Pinned and compared projections come from the raw files (thesis version file, facts.json, the
  register, sources.json), never from a served view that withholds, so a pin taken with a document missing equals one
  taken with it present. Only pinned items are compared, against the latest published thesis version (a draft is
  ignored; with none published the pin refuses and the target reads unavailable). An item is same, changed (any pinned
  field differs) or gone (the record or event is no longer there); an unreadable facts.json makes every `fcx:` item and
  document unreadable. A document is verified, changed, missing or superseded (the live source entry records another
  acquisition). A change to a record no chain cites affects no chain; a changed document affects every chain that
  cites it. A record's basis is verified through its pinned acquisition, never through the current source entry, so an
  older record stays readable while its old file and acquisition record remain.
- States. Chain (latest version), the first that applies in this order, every reason listed: unavailable (a document
  missing or unreadable, the target element unavailable, or no published thesis), needs_revalidation (a document
  changed or superseded, or a quote not found where cited), evidence_changed (documents verify but a pinned item
  changed or is gone), thesis_newer, else available. Invalid content (schema, index SHA-256, unknown event, mechanism or
  target, malformed evidence) refuses the whole read with 500; an invalid record history is shown on that chain only
  (history state "invalid", no approval state) and the page reads it as unverifiable. Approval: awaiting_review,
  needs_revision, approved, or approved_earlier_basis (names what differs). Reading: current, or earlier_basis (shown
  in the history with its basis and what differs now, never as current). The basis counts as current only while every
  item is same, every document is verified with the pinned SHA-256, the thesis version is the latest published and the
  target element is available; when a record changes back it is current again, with nothing written in between.
- Record bindings: a review {parent_review_id, chain_sha256, status approved|needs_revision, notes of at most 1,000
  characters} and a reading {parent_reading_id, chain_sha256, approval_id, short_term, long_term, line} (judgments
  supports, refutes, neither, not_sure, about the thesis read through the target reason or risk; short term is up to
  12 months after the event's date, long term more; the line is one line of 1 to 280 characters, Hebrew or English).
  The server copies into each record the `basis` of the version it verified ({chain {id, version, sha256},
  evidence_sha256, thesis, documents}), the reading's target (never from the request), the account ({user_id,
  username}, or `local-operator` without an accounts store) and its own clock. A review or reading is saved only on the
  latest version, with its evidence current and the chain available; a reading also only under the current approval
  and with content different from the latest current reading. A parent id must name the latest record of that kind
  (else 409 with the latest). Nothing counts, averages or scores readings.
- Text rules: the assistant's text (titles, labels, mechanisms, not-stated lines, change notes) uses thesis_rules
  (claim words and price direction) and the Hebrew list, `second_order/thesis_rules_he.py` (niqqud and cantillation
  removed, the maqaf turned into a space; up to three of the prefixes ו ה ב כ ל מ ש before a listed form; whole words;
  the same groups as the English list, with the ordinary Hebrew words for approval, reasons, sales, buyers,
  cancellation, contract and "expects" left unrefused; the repeal group is not mirrored). The owner's own words, the
  reading line and the review notes, are held to no word list (the owner's decisions of 2026-11-10: personal
  expectations are allowed, a price's direction included, and the two lists were lifted from the reading line, which
  had refused ordinary sentences such as "the company's forecast moved later" and the Hebrew unit "גרם").
- Personal expectations (the owner's decision of 2026-11-10). The owner may record personal expectations, including a
  price's direction. They are kept apart from source wording, from the assistant's drafts and from research scores;
  each carries the time it was actually saved, saved records are never rewritten, and the assistant never words a
  view in the owner's name. The assistant's text keeps the claim-word and price-direction rules, and the project's own
  text still claims no causality and recommends no trade. The overlap rule and the masking of figures below stay on
  every owner text, because they protect sources and not opinions. The record built for expectations is the research
  note (section "Copper research"). See section 2 of docs/superpowers/specs/2026-11-09-copper-event-chains-design.md (private; not in the public repository).
- The withholding guarantee and its limit. Source quotes, live or pinned, are withheld whole while their document does
  not verify with the pinned SHA-256, and captions and labels holding a digit are withheld with their source; a pinned
  superseded wording shows only in the history, beside the current one, and only while its document verifies. The
  owner's words are never shown as source text. Two rules keep that consistent. At save time, text that repeats six or
  more consecutive words of any quote in the version's evidence (live or pinned) or of the target element's cited
  passages is refused (422; NFKC, niqqud removed and the maqaf turned into a space, casefolded, plain quotes and dashes,
  words as letter-and-digit runs). At read time, while any document of a record's basis does not verify with the pinned
  SHA-256, every figure in the owner's text (`[0-9]+(?:[.,][0-9]+)*%?`) is replaced by "[figure withheld]" with the
  reason beside it, in a line and in review notes. A step reference (a number right after "step", "steps", or "שלב" or
  "שלבים" with up to three of the prefixes ו ה ב כ ל מ ש, that names one of the steps of the version the record rests
  on) is never a figure and never masked. Only the digits 0 to 9 make a figure or a step number, for the server
  (event_chain_text.py) and for the page's reader (eventChains.ts) alike: the reader refuses a reply that still shows a
  figure it expects masked, so the two must agree on every text, and both test suites read one table of texts,
  frontend/tests/fixtures/event-chain-masking.json. A line or review notes holding a decimal digit of another script
  (as in "٠3") are refused at save time (422), so no number is written outside these rules; in a record that holds one
  anyway, both sides leave that digit and mask the digits 0 to 9 around it. Not detected: a paraphrase, or fewer than
  six words of a source; the page says so beside the history. A digit run in the line must appear in the version's
  verified quotes or in what the thesis lets its own text state about the target element (thesis_sections.py): each
  served figure's printed and plain value, year and period, and the measure's computed change, all of which the card
  shows; a step reference is exempt.
- Measured block, beside a chain and never inside it: the target's own measure as the thesis serves it ("The thesis's
  own measure of this reason. It does not measure this event.") and "what the price did after" (event_chain_price.py),
  the USGS annual average U.S. producer cathode price (COMEX + premium), US cents per pound, from the retained MCS 2026
  data release, read by header name and verified against its acquisition record on every read. From the event year
  (the year in the event's `when`) each later year gives the change, exact decimals, half to even, one decimal, beside
  the series' earlier year-on-year changes. With no later year: "Not yet measured: the retained series ends at {year}",
  plus " (estimate)" when that row's Notes reads "Estimated."; the short term always reads "Not measured: no monthly or
  daily price source is retained".
- Routes (beside the thesis routes, not under /api/admin/, whose replies are reshaped to a contract with no code for a
  409): GET /api/theses/copper/event-chains returns {view_version, provider_called false, ...} and writes nothing; POST
  /api/theses/copper/event-chains/{chain id}/reviews and .../readings take strict same-origin JSON with exactly the
  documented fields, the local-write checks and the header `x-second-order-event-chain: 1`, and answer 201
  {"record": ...}. Refusals: 409 flat {"detail", "latest"} (a stale parent, a stale chain_sha256 or approval, evidence
  not current; nothing written); 422 and 404 {"detail"}; 401 (`account_changed` or no session) and 403 (`forbidden`)
  from the access check in its contract shape {contract, code, detail}; 428 `account_binding_required` raised as
  auth.ContractError, the same shape, when an accounts store is on and the write names no account (with an accounts
  store every /api/ route is admin-only; without one there is no binding and the account is the local identity). A save
  without a readable reply is settled from the history and never sent again automatically (saved, superseded,
  conflict, not saved, or unverifiable when the history is invalid), following `reconcile` in frontend/src/review.ts.
- The page (frontend/src/eventChains.ts, eventChainText.ts, pages/EventChainsPage.tsx, components/EventChainCard.tsx,
  EventChainForms.tsx): the fixed sentence "Each chain shows one possible path from a past event to a reason or risk of
  the copper thesis. A chain is not evidence that the event caused anything and is not a forecast. Your reading is your
  own view."; one card per
  chain: what the source says (quotes with document, place and state; a changed record shows the pinned and current
  wording side by side), what no retained source states, a conditional mechanism marked "General economics, not stated
  by any source about this event. Drafted by the assistant;" and what the owner's latest review of this version is
  ("awaiting your review", "approved by the owner on {date}", "approved by the owner on {date} on an earlier basis, not
  on this one", "you asked for a revision on {date}", or "your review of it cannot be verified" when the record
  history is invalid), what it bears on, the measured block, the reading with its form, and the history (versions,
  change notes, reviews, earlier readings, each with its basis and its state now). Steps are joined by words, never
  arrowheads. Unsaved text is guarded in both forms; the page works by keyboard and at phone width. Links to it: the
  thesis page, the thesis's library entry and copper's Economic transmission fold on the metals page.
- Cases: grasberg-mud-rush (event copper:fcx-mud-rush-2025; mechanisms output-offset and restart-timing; reason
  world-mine-output), us-ore-grades (copper:usgs26-mine-events; ore-grade, output-offset; world-mine-output) and
  bagdad-expansion (fcx:q3-p-bagdad-approval; expansion-counting; mine-pipeline; one not-stated line on whether the IEA
  base case counts the expansion).
- Tests: tests/test_event_chain_schema.py, _evidence.py, _records.py, _text.py, _view.py, _api.py and _content.py
  (SYNTHETIC retained files, tests/event_chain_fakes.py; the committed content valid and every chain unavailable
  without the retained sources; opt-in against the real copper and FCX folders, read-only, with
  SECOND_ORDER_THESIS_SOURCES and SECOND_ORDER_FCX_SOURCES), frontend/tests/eventChains.test.ts and
  eventChainText.test.ts, and frontend/tests/browser/copper-events-check.mjs with tests/event_chain_browser_helpers.py
  (npm run test:browser:copper-events; the server option `--copper-events synthetic` of
  tests/review_browser_server.py): review then a new version, approval, a reading, an edited cited record, a flipped
  byte, restoring, keyboard and phone width.
- Current limits: three chains; every "what the price did after" reads "Not yet measured" because the retained USGS
  series ends at 2025 (an estimate) and no later edition is retained; the short term is never measured; the FCX
  documents are SEC EDGAR copies; the page stays administrators only; the chains, mechanisms and labels
  are AI-drafted and await the owner's review, and a chain's approval and readings are the owner's alone.

## Copper research (the desk, publication comparisons and the owner's notes)

Two pages, admin only: `/copper` (the copper desk, "Copper" in the top bar) and `/copper/comparisons/<id>`. They join
what exists and add the owner's own record: from two retained publications to what changed between them, to the
owner's dated note, an expectation and a question for the next check. Nothing here is a research score, a forecast by
the project or a recommendation; research_use is "excluded" on every comparison version.
- Versions: publication-comparison-0.1 and publication-comparison-index-0.1 (content), research-note-0.1 (the owner's
  record), copper-research-view-0.1 (the reply). Modules: publication_comparison.py, publication_comparison_cli.py,
  research_notes.py, copper_research_view.py, copper_research_api.py. Records: data/research-notes/copper/NNNNNN.json,
  created exclusively and never rewritten; these are the only files these routes write. Reads never fetch, and GET
  routes and page loads write nothing.
- A comparison (content/theses/copper/comparisons/<id>/index.json and v<n>.json, written by the assistant, indexed as
  the chains are; a published version never changes): {id, version, previous_version, title, earlier {document}, later
  {document}, historical, rows, prices, evidence, change, provenance}. The two documents are `fcx:` documents of the FCX
  research. A row is exactly {id, label, earlier, later, same_measure, note}: one `fcx:` passage of the earlier
  document, one of the later, a label of at most 80 characters without a figure, same_measure (not_applicable for two
  statements with nothing to measure, not_established, or no) and, unless not applicable, the assistant's note of at
  most 300 characters on what each line measures and when. The assistant's text keeps the claim-word and price-direction
  rules; a title or note holds only figures of the publications' titles or of the row's two quotes, and repeats no six
  words of them.
- The assistant's words state no change either. A title, a label or a note holds no arrow and no word of a rise or a
  fall (fell, rose, drop, decline, decrease, increase, lower, higher, cut, reduce, shrink, grow, slip, gain, points, and
  "up" or "down" as words of their own, so a name such as "ramp-up" passes). The loader refuses one, so the pin command
  cannot publish it.
- No change between two lines. Comparing numbers needs matching units and a matching basis of measurement (the owner's
  clarification of 2026-11-10: the 85% and the 80% in the two descriptions of the return to operation are not
  necessarily one measure). A row therefore shows each line's own wording, place and date, and never an arithmetic fall
  or rise between them: a row has no field for one, and the page's reader refuses a reply that carries one. The page
  shows one fixed sentence per row: "Two statements, each shown as written.", "No retained source establishes that the
  two lines measure the same thing. No change is computed between them." or "The two lines are not the same measure. No
  change is computed between them."
- Evidence pin: `python -m second_order comparisons pin --comparison ID --version N --published-on YYYY-MM-DD` (working
  session only; it fills a version's `evidence: null` from the research files, checks it as the app would load it and
  appends the version to the index with its SHA-256; a version already indexed is refused; a row's line that is not a
  passage of the publication it is filed under is refused). evidence is {publications, passages, documents}: the two
  publications as the research lists them {ref, title, form, date, date_kind}, each cited passage once {ref, source,
  location, quote}, and each document's acquisition record. On every read each pinned item is same, changed, gone or
  unreadable and each document verified, changed, missing, superseded or unreadable (event_chain_evidence); the state is
  the first of unavailable, needs_revalidation and evidence_changed that applies, else available. A line is shown only
  while its document verifies and its record is unchanged; the assistant's note on a row says what each line states, so
  it is withheld with any withheld line of that row.
- Historical. A comparison prepared from publications already retained carries "Historical: both publications were
  already retained when this comparison was prepared."; a note saved on it on or after the later publication's date says
  "Written after both publications were known: saved on {day}, the later publication is dated {day}.", so hindsight is
  visible. An expectation reads "Not yet checked: nothing retained after this note was saved has been compared with it."
  (and that its check-by date has passed, when it has): nothing here settles or scores one.
- Retained prices, beside a comparison and never inside a row: the FCX records the version lists, read live through
  company_research_view.resolved() (a record whose document does not verify is withheld), and the last two years of the
  USGS annual average (event_chain_price.series), each with the period it covers; then "Retained prices cover up to
  {day}. No retained price covers a later date.", or "No retained price can be shown on this machine." when none is
  available. A listed price is a published figure of one of the two publications that names its measure and a period of
  real days in order (the pin refuses any other, and the view withholds one). Only retained sources are read; the
  retained World Bank monthly workbook stays unused (docs/copper-thesis-sources.md).
- A research note (research-note-0.1): {record_version, note_id, parent_note_id, sequence, about {kind
  comparison|chain|thesis, id}, follows, text, expectation, question, basis, account, saved_at}. The request is exactly
  {parent_note_id, about, subject_sha256, follows, text, expectation, question}: the note of 1 to 2,000 characters; an
  optional expectation {text of 1 to 500 characters, check_by YYYY-MM-DD or null, never before the saving day}; an
  optional question of 1 to 280 characters; optionally the id of an earlier note about the same subject that it follows.
  The server adds the basis of the subject it verified (the comparison, chain or thesis version with its SHA-256, the
  evidence digest, and each document with its pinned acquisition; a thesis note binds every source of the latest
  published version), the account and its own clock: a saving time is never taken from the request. Text rules: no
  control character but a line break, the digits 0 to 9, and no six consecutive words of the subject's quotes (for a
  comparison, of every recorded passage of its two publications, cited by a row or not); no word list. Text that could
  not be stored as it was sent (a lone surrogate, or U+001C to U+001F or U+0085, which Python strips and a browser
  keeps) is refused, never changed silently; the same holds for the event chains' line and notes. A note is saved only
  while the subject is available (every document of its basis verifies and no pinned item changed), on the subject
  version the page showed and after the latest note (else 409 with the latest note's id). A change of mind is a new
  note; nothing is edited or deleted, and the history is verified on every read and save (numbering, ids, the parent
  chain, each record's shape and form, a followed note being an earlier one about the same subject). A file edited by
  hand into an empty text or an unreadable saving time makes the history unverifiable; a stray file is reported without
  its name.
- The view, GET /api/theses/copper/research: {view_version, provider_called false, desk {pages}, comparisons, subjects,
  notes}. desk.pages are the five copper pages (thesis, tools, fcx, metals, events) with what each is and one status
  line from the view that page already serves (the thesis's published version, the FCX documents verified on this
  machine, the chains counted by review state: approved, approved on an earlier basis, with a revision asked, awaiting
  review, or with records that cannot be verified), or a fixed problem when a line cannot be read. subjects are what a
  note can be about now, each with the version, SHA-256 and state a save binds. notes is {state valid|invalid, problem,
  latest, items}; each note is served with its state now (current, or earlier_basis with what differs), its basis
  documents verified through their pinned acquisitions, and its figures masked while one of them does not verify (a
  chain note's step references are exempt, by the step count of the version it names). An invalid history is shown as
  such, with no notes, and the rest of the read goes on.
- Routes (beside the thesis routes): the GET above; POST /api/theses/copper/research/notes takes strict same-origin
  JSON, the local-write checks and the header `x-second-order-research-note: 1`, and answers 201 {"record": ...}.
  Refusals as for the event chains: 409 flat {"detail", "latest"}; 422, 404 and 500 {"detail"}; the local-write checks'
  403, 413 and 415 as plain {"detail"}; and, with an accounts store, 401 (`account_changed` or no session), 403
  (`forbidden`) and 428 `account_binding_required` in the access contract's shape.
- The pages (frontend/src/copperResearch.ts, pages/CopperDeskPage.tsx, pages/ComparisonPage.tsx,
  components/ResearchNotes.tsx): the desk shows the five pages with their lines, the comparisons, the open questions (a
  note's question until a later note about the same subject follows it, or follows a note saved after it: the form
  follows the latest note on a subject, so no question can be stranded), the notes and a note form with a subject
  selector; the comparison page shows both publications, each row's two lines side by side, the row's fixed sentence,
  the assistant's note, the retained prices, and the notes on it with their form. A note is shown under "Personal note:
  the owner's view. Not a source, not an AI draft, not part of any research score." Only the save button sends the form
  (Enter in the date field, the follows box or the selector does not), because a saved note cannot be changed. Each of
  the five copper pages links back to the desk.
- The first comparison, fcx-annual-2025-to-q3-2026, historical: the annual report for fiscal 2025 (signed 2026-02-13)
  against the quarterly report for the third quarter of 2026 (signed 2026-11-06), seven rows (the return of Grasberg to
  operation, the production blocks, the smelters, the insurance claim, the Bagdad decision, the mining licence and the
  outlook's price assumptions) and six realized-price records.
- Tests: tests/test_publication_comparison.py, test_research_notes.py and test_copper_research_api.py (the SYNTHETIC
  world of tests/event_chain_fakes.py with one comparison; the committed comparison valid and unavailable without the
  retained documents; opt-in against the real FCX folder, read-only, with SECOND_ORDER_FCX_SOURCES),
  frontend/tests/copperResearch.test.ts, and frontend/tests/browser/copper-desk-check.mjs (npm run
  test:browser:copper-desk, on `--copper-events synthetic`).
- Current limits: one comparison, of FCX passages only; no row computes a change, also where two lines are the same
  measure; expectations are recorded and never settled; no monthly or daily price is retained; a listed price is a
  figure of one of the two publications (the pin refuses any other and the view withholds one), while the USGS annual
  series shown beside them is not part of a comparison note's basis, so a figure of it typed into a note is not masked
  when that file fails; a question on a note whose subject is no longer published cannot be closed; the comparison's
  rows and notes are AI-drafted and unreviewed by the owner; the FCX documents are SEC EDGAR copies; the pages stay
  administrators only.

## Fuels page (reference, personal use)

`second_order/fuels_sources.py` (fuels-sources-0.2) checks the committed source-terms record;
`fuels_snapshots.py` (fuels-snapshot-0.2) writes and verifies the snapshot files; `fuels_eia.py` (fuels-eia-0.1) is the
only fuels module that touches the network; `fuels_crack.py` (fuels-crack-0.1) is the exact arithmetic;
`fuels_notes.py` (fuels-note-0.1 and 0.2) checks and fills the committed notes; `fuels_view.py` (fuels-view-0.5) joins them into
one read, `fuels_api.py` serves it and `fuels_cli.py` holds the two commands. Stage 2 adds `fuels_situation.py`
(fuels-situation-0.1, the windows and the split) and `fuels_mechanisms.py` (fuels-mechanisms-0.1, the checked
mechanism files). It is a reference page: the prices are published figures read from EIA's open data API (until
0.5.39, from FRED), the crack is computed and labelled so, and nothing here enters a research score, a freeze or an
assessment.
- Series and terms: content/fuels/sources.json, exactly {sources_version, prepared_on, page_label, credit, terms,
  series}, is checked strictly on every read (an unexpected or missing field refuses with 500 naming the field, never a
  value; a missing file is 503). Its five series are fixed in order, each with its EIA series id, API route and EIA
  page fixed in code, so no role can name a futures contract or a series of another definition: Brent RBRTE
  ("Europe Brent Spot Price FOB", usd_per_bbl), WTI RWTC ("Cushing, OK WTI Spot Price FOB", usd_per_bbl), New York
  Harbor gasoline EER_EPMRU_PF4_Y35NY_DPG ("New York Harbor Conventional Gasoline Regular Spot Price FOB") and diesel
  EER_EPD2DXL0_PF4_Y35NY_DPG ("New York Harbor Ultra-Low Sulfur No 2 Diesel Spot Price", usd_per_gal), all on the
  route petroleum/pri/spt, and Henry Hub RNGWHHD ("Henry Hub Natural Gas Spot Price", usd_per_mmbtu) on
  natural-gas/pri/fut. Each carries the description and units text EIA must give it, daily cadence, weekly
  publication, publisher, EIA's page, the data vendor where EIA names one (Henry Hub: "Refinitiv, an LSEG business", from
  EIA's natural gas price notes, which must be one of the series' listed terms; EIA's petroleum spot notes name none,
  so the four others carry none), the scope personal_and_private_demo, the basis of the use (it records that EIA calls
  government publications public domain and material licensed by others possibly protected, and does not call these
  series public domain), `public: not_assessed` and the ids of the listed terms (each with a title, URL and the date
  it was read: EIA's Copyrights and Reuse, its API Terms of Service Agreement and its two notes pages). The fixed
  credit reads "Spot prices from the U.S. Energy Information Administration (EIA), retrieved through its open data API.
  EIA does not endorse this page." Displayed values are rounded half-even to 2 places (per barrel and per mmbtu) or 3
  (per gallon).
- Refresh: `python -m second_order fuels refresh [--start YYYY-MM-DD]` is the only way a price enters. It uses
  EIA_API_KEY when set, else the stored key (below), and asks, per series, GET https://api.eia.gov/v2/<route>/data/
  with its series facet, frequency daily, data[0]=value, start (400 days before today's New York date unless
  `--start` is given) and end (that date), period ascending, length 5000 (EIA's maximum) and offset, paging until the
  reply's stated total is reached. It appends one
  snapshot file data/fuels/snapshots/<sha256 of its canonical JSON>.json, written by a temporary file and a rename
  (write-once; an identical refresh is not duplicated; reads ignore a `*.tmp` file). A series is kept only when it came
  back whole and is the series the record names; otherwise it is stored as `refused` with its problem and no
  observations, the other series still stored: a row of another series; another description or units (the problem
  names both); a reply that is not daily; a period that is not a day, lies outside the window or does not strictly
  increase; pages that overlap; a value that is neither a plain decimal in ASCII digits (kept as the exact text EIA
  sent, never passed through a binary float) nor null (a missing day, kept); a warning in the reply; a total that is
  missing, unreadable, more than the window's days or changes between pages; rows that end before the total or exceed it; no
  rows; a reply that is not JSON; or an HTTP error other than those that abort. A network error or HTTP 401, 403, 429 or
  5xx aborts the refresh with nothing written.
- The key: it is sent as the api_key parameter EIA requires and is never stored, logged, printed or put in an error
  message. EIA echoes it in `request.params`: that field is dropped before a reply is hashed or read, and a reply that
  holds the key anywhere else (or a reply that is not JSON and holds it) aborts the refresh with nothing written. A
  failed request is reported by its HTTP status and EIA's error code only when that code is a plain code that does not
  hold the key; a network error by its type only (httpx's text holds the URL, which holds the key).
- The stored key (0.5.40): `fuels key set` keeps the key as one entry, "second-order-v2 EIA API key" (user
  EIA_API_KEY), in Windows Credential Manager through keyring, never in a file of this program's own or under a key
  written in its code. It asks for the key twice at a hidden prompt, and only when stdin is a real console (on Windows,
  NUL also passes isatty() and would leave the prompt waiting, so the handle must answer GetConsoleMode); there is no
  argument that takes the key. It refuses, before asking, when a key is already stored (`fuels key replace` overwrites;
  `fuels key delete` removes); it refuses an empty entry, two entries that differ, one longer than 256 characters and
  one with a space or a character outside printable ASCII, and stores nothing then. Reading, storing and removing all
  pass one check first: a keyring backend other than Windows Credential Manager's is refused before any call on it (no
  plain-text fallback), so `fuels key status`, `set`, `replace` and `delete`, and a refresh without EIA_API_KEY, refuse
  it too; a refresh with EIA_API_KEY set never reaches the store. The stored key is read back to confirm it.
  `fuels key status` prints `stored`, `store`, `EIA_API_KEY_set`, `refresh_reads` and `next`, never the key. Saving
  requests nothing and refreshes nothing. `fuels refresh` takes EIA_API_KEY first, else the stored key, and adds
  `key_from` (EIA_API_KEY or Windows Credential Manager) to its report; without either it refuses, naming both. A
  credential store error is reported by its type only. Only the fuels commands import fuels_key; the server, the view,
  the snapshots and the sources never read the key.
- Dates: each stored series keeps the observation date (the trading day the price describes) apart from EIA's
  publication date, which EIA's API does not give, so it is stored as unknown (no release, no release dates) and shown
  as "not given by EIA", never inferred from the observation date or the retrieval; and from retrieved_at, our clock
  after the last reply (possession, not first public availability). The snapshot records retrieved_on (the New York
  date that ends the window), the window, the request's fixed parameters, per series EIA's route, series,
  description, units, frequency, total, page count and API version, the SHA-256 of each reply without its key, and
  the SHA-256 of the source record it was read under. A history is what EIA's file held when it was retrieved, not a
  record of what was known on the days it covers; the page says so under Situation Now. The report prints identities,
  dates, states and counts, never a price.
- Reads: `load_all` verifies every file (name equals content hash, strict JSON, a readable version:
  fuels-snapshot-0.2, or 0.1 as the FRED importer wrote it); one that fails makes the state `changed` and withholds
  every price, and no snapshot at all is `missing`. The latest snapshot is chosen by (retrieved_at, snapshot_id). A
  snapshot whose provider is not EIA (a 0.1 file) is kept as it is, verified and listed in the refresh log as "FRED
  (kept; prices withheld)", and every series of it is withheld as terms_changed with the reason that it came from FRED,
  which the page no longer reads; it is never rewritten or deleted. A series whose stored terms differ from the
  committed record is withheld as terms_changed; a refused series as refused. Reads never fetch.
- The crack: the 3-2-1 basket value is (2 × gasoline × 42 + 1 × diesel × 42) / 3 dollars per barrel of crude input; the
  crack is that value minus Brent spot. It is a chosen benchmark, not a measured refinery result: the 2:1 mix is not any
  refinery's yield, New York Harbor products against Brent is one choice among others, and it is gross, before every
  refining cost, so it is not a margin or profit and not a research observable. Arithmetic is exact (Fraction); display
  rounding is half-even and never feeds later arithmetic. The barrel is computed on the latest date on which all three
  inputs have a value, with the change since the previous such date; with no common date, an input that is not
  verified, or an input that is behind (below), it is withheld with a stated problem. `crack_history` covers exactly
  the dates the three shown input histories cover (the last 365 days of each snapshot's own coverage, never padded; a
  gap stays a gap).
- Kinds and withholding: a row is `published` (a verified value from the source) or `missing`; no value is estimated or
  carried forward. A missing input withholds every output that depends on it. A verified series whose latest
  observation is more than 10 days (one EIA weekly cycle plus the usual publication lag) older than the newest latest
  observation on the page is behind: an old price is still a verified price, so it keeps its value, its own date and
  its history, and the reply says how many days behind it is and the newest date (`behind`); every output computed
  from it is withheld, never computed on an older common date beside newer prices and never combined across dates.
  WTI and Henry Hub are retained and shown as their own rows; nothing on the page is computed from them. Europe
  natural gas, urea and helium are listed as not yet retained, each with its reason.
- Notes: content/fuels/notes/situation-NNNN.json (four ASCII digits; any other situation-* file there is refused with
  500 naming it, and other files are ignored), numbered from 1 with no gaps, each exactly {note_version, number,
  written_on, covers_through, snapshot_id, observation_date, author, review, headline, lede, columns {supply, demand,
  stocks}, sources}. A note is bound to the snapshot and observation date it was written for. Its prose never holds a
  price: the four placeholders {brent}, {basket}, {crack} and {brent_change} are filled by code from the bound barrel,
  and a digit rule refuses any digit in the prose other than inside a year (braces only form a listed placeholder).
  The refused phrases of the mechanism files (Text rules, below) are refused in the headline, lede and columns too,
  even inside an attribution (one shared rule, `fuels_notes.refused_phrase`). Every source carries a title, publisher, date, https URL and locator, and covers_through is the latest source date.
  The author is "Claude (AI-drafted)" or "Owner"; review is unreviewed or reviewed (with its date). A note is
  `current` when its snapshot is the latest, `earlier` when it is not (it then shows its prices then and now, or says why
  the latest barrel is withheld) and `unbound` when its snapshot is not verified, has no complete barrel or does not hold
  its observation date. Earlier notes are never edited; a revision is the next number (docs/fuels-situation-note.md).
  A fuels-note-0.2 (since 0.5.41) holds `analysis` {what_happened (one to four statements), meaning (one to six),
  relevance (one or two), watch (two or three), caveats (one to six texts, at most 300 characters, no placeholders)} in
  place of `columns`, and its lede is the visible summary (twenty-five to seventy words as written). Each statement is
  exactly {kind, text (at most 420 characters), sources (distinct indexes into the note's sources), mechanism}: kind
  is observation or computed (no sources: the figure comes from the snapshot or the engine), hypothesis (a reading or
  a general mechanism) or sourced or source_projection (at least one source); every source is cited at least once;
  mechanism is null, drivers:<id> or transmission:<id>, and a relevance statement names a transmission mechanism.
  The same phrase, digit and brace rules apply to every text. Its placeholders add, for the week and month windows of
  Situation Now computed from the bound snapshot, the two dates ({week_from}, {week_to}), the split's words
  ({week_split}), each product's part per barrel of crude ({week_gasoline_part}, {week_diesel_part}) and, for Brent,
  gasoline, diesel, the basket and the crack, the direction word, the change with its unit and (all but the crack)
  the percentage ({week_brent_move}, {week_brent_change}, {week_brent_pct}); likewise month_. A 0.2 note whose bound
  snapshot does not compute a window it names is `unbound`, and the page says why. The page shows the headline and
  summary and, under them, one button ("Read the analysis"; "Read the earlier analysis" when the note is
  earlier; aria-expanded, aria-controls) that opens the analysis in its own row of the barrel section, under the
  summary and the barrel and at most 760 px wide, so opening it never stretches the barrel's row: the four sections,
  each statement with its kind's badge and words, its sources by number and the mechanism it names (a link to the
  section), then "What this cannot tell" and the sources with their dates and locators. An unbound note shows no
  prose, as before.
- Situation Now (Stage 2, fuels-situation-0.1): computed (kind C) on the dates on which Brent, gasoline and diesel all
  have a value, from the same verified inputs as the barrel; it reads no file and fetches nothing. Three windows end on
  the latest common date D. `previous` compares with the previous common date. `week` compares with the latest common
  date on or before D minus 7 days and is valid only when that date is within 3 days of the target. `month` compares
  with the latest common date on or before D minus one calendar month (same day of the previous month, clamped to its
  length) and is valid only within 5 days of that target. A window without such a date is `unavailable` with its
  reason, naming the target date; it never falls back to an older date. With one common date every window is
  unavailable; when the barrel is withheld, or no common date exists, Situation Now is withheld with the problem. Each
  computed window gives Brent, gasoline, diesel, the basket and the crack, each from, to and change (with the percentage
  change for all but the crack); arithmetic is exact (Fraction) and display rounding is half-even and never feeds later
  arithmetic.
- The split: the basket's change equals the change in Brent plus the change in the crack, and equals 28 x the change in
  gasoline plus 14 x the change in diesel (the 2:1 weights per barrel of crude input). This is an accounting identity,
  not a cause: it shows where the arithmetic moved, not why. The label is `unchanged` (both parts zero), `offsetting`
  (the parts have opposite signs), `mostly_crude` (the crude part's share of the two absolute parts is at least 2/3),
  `mostly_crack` (at most 1/3) or `both`. The page gives every split amount in dollars per barrel of crude ("/bbl" in
  the text, "in $/bbl" over the bars, "in dollars per barrel" in the bars' accessible names), so the product parts (28
  and 14 times the per-gallon changes) are never read as $/gal; when the two shown product parts do not add up to the
  shown basket change, the line says they differ by a cent through rounding. A change that is not zero but shows as
  zero at its places is shown as its direction and "<" the last shown place (−<0.01 in the table, −<$0.01/bbl in the
  split, +<0.1% for a percentage), with a key under the table; the summary names a split part so shown ("the crack fell
  by less than $0.01"), and 0.00 is only a true zero. Levels and badge names use the true minus.
  In "What it shows", the lines with figures and the unchanged or offsetting label line are C; the line that points to
  the Market Drivers is E.
- Staleness: `age_days` is the days from the latest common date to the snapshot's retrieval date; above 10 days
  Situation Now still shows its windows and adds a plain note with the day count. A role (Brent, WTI, gasoline, diesel,
  Henry Hub) whose latest observation is newer than D is named with its date, because the comparison uses the common
  date only.
- Kinds on the page: P measured (a verified published value), C computed (fixed arithmetic on measured values), E
  possible explanation (a general mechanism, stated conditionally, not a finding about the current move), S sourced
  claim (attributed to a named external source with its date), A assumption and M missing. E marks the committed
  mechanism content and the Situation Now line that points to the Market Drivers. Only the situation note at the top
  carries sourced claims, attributed in its text; a fuels-note-0.1 keeps its Stage 1 labels, so no badge is drawn
  there, while a fuels-note-0.2's analysis badges each statement (observation P, computed C, hypothesis E, sourced
  claim and attributed projection S, each with its words); none of the sections below does. The Method legend lists all six and says so. Situation Now also shows each computed
  window's from and to values as text under a "Levels at both dates" disclosure, so they need no hover. There the
  Brent, gasoline and diesel levels are P (the published spot prices on those dates) and the basket and crack levels
  C; every change over a window is C. A badge's hover text is also its accessible name, so each says which it is.
- Synthetic mark: the reply carries `"synthetic": true` when the review server (tests/review_browser_server.py
  `--fuels synthetic`, which passes `create_app(fuels_synthetic=True)`; `serve` never does) says its world is
  SYNTHETIC, or when the shown snapshot came from the test fake (tests/fuels_fakes.py answers as API version
  "SYNTHETIC-…", which EIA's numbered versions never are; its FRED-era fake titled every series "SYNTHETIC …"), so a fake
  snapshot is marked wherever it is served. Otherwise the key is absent,
  and the reader refuses any other value. The page then shows a "Synthetic test data" banner above the barrel and a
  "Synthetic prices" stamp in the sticky section nav, so a screenshot of any section says so.
- Mechanism files: content/fuels/drivers.json and content/fuels/transmission.json, each exactly {mechanisms_version
  "fuels-mechanisms-0.1", kind, prepared_on, author, review {state, reviewed_on}, items}, are checked strictly on every
  read by `fuels_mechanisms.py`; a refusal names the file, item and field, never the text. drivers.json holds exactly
  eight items in this order: opec_supply, global_demand, inventories, refining, geopolitics, shipping,
  dollar_rates_growth, seasonality; each is {id, title, mechanism, acts_on (crude, crack or both), direction,
  changes_when, watch, sources}, where the three lists hold conditional statements, conditions and the names of
  publications or indicators (never values). transmission.json holds exactly seven in this order: aviation,
  shipping_logistics, refiners_energy, chemicals, agriculture, consumer_retail, inflation_policy; each is {id, sector,
  trigger (the price that starts the chain, named precisely), chain (at least three short steps), effect (negative,
  positive or mixed), effect_text, second_order, flips_when, lag, lag_sourced, sources}; `lag_sourced` is true only
  when a source is listed. An absent file reads as absent. Limits: title, sector and trigger at most 80 characters;
  mechanism and effect_text at most 600; each list entry and the lag at most 240; a chain step at most 60; a source's
  title, publisher and locator at most 200; at most 10 sources and at most 20 entries in a list; the file at most
  200,000 bytes.
- Text rules: in the project's own prose (everything but the source fields below) no digit other than a four-digit year
  (19xx or 20xx) and the token "3-2-1"; and none of these phrases, case-insensitive and word-bounded: caused, causes,
  drove, driven by, due to, because of, as a result of, led to, triggered, will rise, will fall, will increase, will
  decrease, forecast, expect, expects, expected. A source's title and locator quote the source verbatim, so they are
  exempt from the phrases and the digit rule; its publisher is exempt from the digit rule only. The digit rule lets any
  four-digit token from 1900 to 2099 through, even one that is a quantity rather than a year; review catches that
  misuse, and the rule is not narrowed. Numbers belong to code and retained sources. Mechanism prose (not the situation
  note, which describes the current prices by design) must also never read as the account of the current move, so it
  may not point at a time (recent, recently, currently, now, lately, latest, so far, amid, today, this week, this
  month, this quarter, this year, last week, last month, last quarter, last year, current move, current rise, current
  fall, current rally, current decline, current spike), narrate a price move in the past tense (rose, risen, fell,
  fallen, jumped, surged, plunged, slumped, soared, widened, narrowed, climbed, dropped, tumbled, spiked, rallied,
  lifted, pushed, spurred, sparked, fuelled, fueled, boosted) or attribute and forecast (on the back of, thanks to,
  owing to, resulted in, drives, will, likely to, set to, poised to). EIA's publication "This Week in Petroleum" is a
  name and passes.
- Drafting rules, checked in review and not enforced by the loader: mechanisms are written conditionally ("can", "tends
  to", "when", "if"), and E prose states a mechanism without attributing a finding to a named source or to "research";
  the item's sources carry the evidence.
- Sources of mechanism items: each is {title, publisher, date or null, url (https), checked_on, locator or null}. A
  source is listed only after its URL was opened and found to support the statement, and `checked_on` is that day (not
  after prepared_on). Sources are cited, not retained. An item may have none, and the page then says "No source
  attached yet". An invalid committed file makes GET /api/fuels answer 500 naming the file, item and field, and the page
  shows its error panel, never half-checked prose. A test scans the committed content with the page's phrase check.
- Review: the mechanism prose is "Claude (AI-drafted)" with review `unreviewed`, and the page says it is AI-drafted and
  not reviewed by the owner. The prose is reviewed and revised in place. To mark a file reviewed the owner sets
  `review.state` to "reviewed" and `review.reviewed_on` to the review date, which must be on or after `prepared_on`
  (the loader refuses an earlier date, a missing one when reviewed and any date while unreviewed); sets `author` to
  "Owner" if the owner rewrote the prose; and commits. Git history is the version record for this prose: AGENTS rule 3
  (new versions append) governs frozen research inputs, not explanatory content.
- Events (fuels-event-0.1, designed and not connected): the newsroom is not connected to the fuels page, so no event
  content exists, and the view carries events {state "not_connected", schema "fuels-event-0.1", text}. Market Drivers
  says that no verified current events are connected yet and that a driver's explanation is not a statement about
  current events. The future record is {id, date, headline, summary (attributed to its source), source {publisher,
  title, url, published_at, retained_sha256}, acts_on, drivers (driver ids), status}; only an event whose source is
  retained and verified may ever be shown, and then as kind S.
- Route and access: GET /api/fuels returns the whole view (view_version, provider_called false, the source record, the
  snapshot, the snapshot log, the five series with their history, the barrel and its crack history, the note and the
  note rows, the coverage list, a synthetic unit example, and since fuels-view-0.2 the situation, the drivers, the
  transmission and the events; since fuels-view-0.3 EIA's credit in place of FRED's notice, each series' data vendor,
  and each snapshot's retrieved_on and provider; since fuels-view-0.4 each fuels-note-0.2's filled analysis, each
  statement's mechanism with its title as mechanism_title, a note naming no committed mechanism refusing with 500;
  since fuels-view-0.5 each series' behind, null or its days behind and the newest date).
  The page /fuels, "Fuels" in the navigation between Market
  context and Library, is part of the admin build only. A refusal keeps its status; a local read error, or a malformed
  record that fails while the view is built (ValueError, KeyError or TypeError), is a 500 naming only the exception
  type. `create_app` reads no snapshot unless it is given `fuels_snapshots`; only `serve` passes a folder: this
  checkout's data/fuels/snapshots, which `.gitignore` excludes with data/, or the folder named by `--fuels-snapshots`
  (snapshots are per checkout, so a worktree's server can read the main checkout's folder). A refusal in `fuels
  status`, `fuels refresh` or `fuels key` prints "Failed: <message>".
- Wording: the page carries "Personal and educational use. Not for redistribution." and EIA's credit line, and each
  price its acknowledgment: "Source: U.S. Energy Information Administration, <EIA's description> [<series id>],
  retrieved <date>; <EIA's page>." with "Data: Refinitiv, an LSEG business, as EIA states." for Henry Hub. It says
  "since <date>" and never "today".
- Terms (read 2026-11-07): EIA's Copyrights and Reuse page says U.S. government publications are in the public domain,
  asks for an acknowledgment, and says material contributed or licensed by others may be protected; its API Terms of
  Service allow a service that searches, displays, analyzes and retrieves EIA data, with EIA named as the source and
  no implied endorsement; neither has an AI or a storage clause. The page no longer reads FRED: FRED's API terms
  (fred.stlouisfed.org/legal/terms/, "Prohibitions for FRED® API" (k) and (l)) bar using the API in connection with
  software development or storing, caching or archiving FRED content. Every test, fixture and browser check still uses
  synthetic values (tests/fuels_fakes.py); `fuels refresh` and `fuels status` print no price values; `create_app`
  reads no snapshot by default. The committed analysis note was drafted from the verified EIA snapshot (read through
  the review server; no key read, no refresh), and its figures are placeholders filled from that snapshot. The owner runs `fuels refresh` with their own key.
- Not assessed: use beyond personal and private demonstration. Whether the page may be public is not decided (design
  section 15); every series record states `public: not_assessed`.
- Tests: tests/test_fuels_sources.py, _snapshots.py, _eia.py (over a fake EIA transport: the key in replies and
  errors, paging and truncation, identity, values, dates and provider errors), _crack.py, _notes.py, _cli.py and _api.py,
  _key.py (the stored key over an in-memory store and a fake vault; keyring's own backend there is its fail backend,
  and CLI subprocesses run with its null backend, both refused by type before use, so no test reaches the real
  Credential Manager; a backend that records each call shows another store is refused with no call made on it),
  _situation.py, _mechanisms.py, _edges.py (a change under the last shown place: small rises and falls, true zero and
  the half-even boundaries, the exact values and labels kept; WTI or Henry Hub a year behind, each barrel input a year
  behind, a week behind, an equally old snapshot, and the binding refusals beside a series behind), and the frontend's
  fuels reader, edge-case and geometry tests; fuels-check.mjs (`npm run test:browser:fuels`, 85 checks) drives the
  page on synthetic snapshots, with no snapshot, a stale one, one with a refused series and a FRED-era one, and a
  fuels-note-0.2 analysis: current (closed, then open by click and by Enter, the barrel and summary not moving and the
  analysis below them, at 1280 and 375 px), earlier after a refresh and unbound without its snapshot, then a crack
  change under a cent, diesel a year behind and WTI a year behind. The Python and
  frontend phrase scans read the page check's AFFIRMATIVE list from fuels-check.mjs itself, so they cannot drift.
- Known gaps: (a) and (b), recorded at the stage 2 closeout (0.5.38), are closed in 0.5.47. (a) A crack change under
  a cent beside the `offsetting` label now shows its direction and "<$0.01" instead of $0.00; the label is still read
  from the exact parts. (b) A series about a year behind the others no longer makes the reader refuse the whole
  reply: its price stays with its date, and what is computed from it is withheld. The page has been checked on
  synthetic snapshots (marked as test data) and with no snapshot; since the owner's first refresh it has also been
  checked on the real EIA snapshot 9c94687f… (2026-11-07, at the activation of 0.5.39, and with the analysis at
  0.5.41). (c) Not yet seen
  in a real EIA reply, so built to refuse rather than guess: the exact description and units texts (checked against the record, so a difference refuses that series and names both), whether `total` and
  `value` come as numbers or text (both are accepted), the route of the Henry Hub spot series (natural-gas/pri/fut; a
  wrong route refuses that series), where EIA echoes the key (anywhere but `request.params` aborts the refresh), and
  how EIA states a warning.

## Company page (FCX, private)

`second_order/company_research_view.py` (company-research-0.2) builds the read and `company_research_api.py` serves it
at GET /api/companies/fcx: an /api route, so administrators only (401 signed out, 403 for a reader). The page is
/companies/fcx in the admin build. It reads the committed research package research/fcx (facts.json, sources.json,
page.json; acquisition/ holds the request records) and the four retained documents under data/company-sources/fcx
(private, ignored by Git). It writes, fetches and calls nothing; the reply carries provider_called false.
- **Provenance:** all four documents are SEC EDGAR copies: the 2025 10-K (copper-sec-01), and the third-quarter 2026
  10-Q and the two releases, each exhibit 99.1 to a Form 8-K (the results release furnished under Items 2.02 and
  7.01, the Bagdad release attached under Item 8.01; fcx-sec-docs-02, retained 2026-11-11). The 10-Q
  and the releases were first read from investor-relations copies; those copies and their request records are kept
  privately and no longer read, and every record and passage was matched against the SEC copies
  (research/fcx/sec-match.md).
- **Verification on every read:** each document must match its committed acquisition record (a complete HTTP 200 of
  the same address, retrieval time, size and SHA-256) and its sources.json entry, and the file on the machine must have
  that size and SHA-256. Otherwise it is missing or changed.
- **Withholding:** a withheld figure carries only what identifies it (id, kind, name, unit, period, basis, its source
  and page and location, or its formula, inputs and places) and why it is not shown: no value, printed figure, quote,
  note, explanation of a computation or printed row and column label. A published figure or passage from an
  unverified document is withheld. A computed figure is recomputed with exact decimals (ROUND_HALF_EVEN at its stated
  places) and is withheld when an input is withheld or when it does not recompute; a published figure whose printed
  form does not read as its value is withheld too. An assumption names the documents its statement describes
  (rests_on); its statement is withheld when one is not verified. A page text that names a withheld figure or passage
  is withheld whole and sends no words, only the ids it names. Reasons are fixed text that name the document, never a
  value.
- **Names:** what names a figure (name, unit, basis, location, period label) is sent even when it is withheld, and the
  page builds each figure's accessible label from it, so it carries no percentage. A share or rate from a document,
  such as FCX's ownership of PTFI, is a figure of its own record, shown only when that record's document is verified.
  A measure's definition ("per $0.10/lb change") is not a percentage and stays. The server refuses the read (500) and
  the research checker (research/fcx/tools/check_facts.py) fails on a name that carries one. A shown figure's detail
  still quotes the document's printed row label and quote.
- **Texts:** page.json is generated by research/fcx/tools/build_page.py. Its prose holds no digits but years and form
  names (every number is a placeholder filled from a record), no causal or forecast phrasing of its own (the fuels
  notes' phrase rule) and no valuation words; each text block carries its kind (reported, company's reason, company
  estimate, computed, AI reading, note). page.json holds no numbers.
- **The reader** (frontend companyResearch.ts) refuses a reply in which a published figure does not read as its value,
  a computed one does not recompute exactly (BigInt fractions), a mix of bases, periods or units is unstated, a withheld
  figure carries anything beyond what identifies it, a figure's name carries a percentage, a withheld assumption its
  statement or a withheld line its words, a text block's state disagrees with what it names, a text types a number, or
  a table row mixes bases.
- **Screen:** the first screen holds a short AI-drafted summary of three sentences (stamped "AI-drafted, not reviewed by
  the owner"; the fuller summary in a closed fold), six key figures and what changed in the latest quarter, in that
  order on a phone; the business, the Numbers views (quarter, nine months and year
  apart, with the company's revenue bridge and the 2025 operating cash flow difference shown beside its row), the
  mechanisms (published sensitivities as published; the Bagdad decision apart from the company's estimates), the open
  questions and the sources open by choice. Every figure opens its detail: source, date and its kind, page, location
  and quote, or formula, inputs and rounding. Badges: P reported, F company estimate, C computed, M withheld.
- **Scenarios** (stage 2, research/fcx/scenarios-spec.md): a tab after Mechanisms with two separate calculations,
  never added together, on the company's assumptions for Q4 2026 in the results release of 27 October 2026.
  `second_order/company_scenarios.py` (company-scenario-0.1) computes each with exact decimals on the records verified
  now, served at POST /api/companies/fcx/scenario: same-origin JSON with the scenario action header, administrators
  only; it writes, stores, fetches and calls nothing (stored false, provider_called false).
  - Price × volume: base r3-out-cu-price-q4-2026 and r3-out-cu-sales-q4-2026 (sales, not production). For an entered
    price P and volume V: S = P × V in US$ million, its change from P0 × V0 (c-q4-cu-sales-value-base), and the change
    split in one fixed order (a-price-volume-split): volume effect (V − V0) × P0, price effect (P − P0) × V, adding up
    exactly. Shown beside its definition: an approximate copper sales value, not reported revenue, earnings or cash flow.
  - Cash flow sensitivity: r3-sens-ocf-copper only, with its step r3-sens-ocf-copper-step: ΔOCF ≈ (P − P0) ÷ step ×
    sensitivity, as this project's linear use of the company's approximate figure, with volumes, costs and the
    company's other assumptions as stated. No range is presented as confirmed by the company; no volume change is
    added; the 10-K's full-year sensitivity is not used. A closed fold explains why a volume change gives no cash flow
    figure (no fixed and variable cost split; unit cost is not held constant).
  - Inputs are text: a price above 0 and at most 100 US$ per pound, to the cent (a larger one is refused with its
    unit); a volume above 0 and at most 5,000 million pounds, one decimal at most. Every result is then exact (at most
    three decimals): nothing is rounded. A bad input is refused (422) and named in the page before anything is sent.
  - A record a calculation uses that is withheld blocks it: 409 naming the document, the tab shows why instead of the
    inputs, and its explanations are withheld with it (a line that restates a document cites its passage). A 409
    while the page is open makes the page read everything again, also a late one sent for inputs that have changed
    since (its reply is not shown). The page's scenarios must name exactly the records
    each calculation uses, or the reader refuses the read. A price change of more than one step is said to be this
    project's arithmetic, not a range the company has confirmed.
  - The page (frontend companyScenarios.ts) checks each reply again with BigInt fractions against the records it already
    shows: the records and their values, the echoed inputs, each result and the split. A result is shown only for the
    inputs it was computed for: a changed input removes it, and a late reply for earlier inputs is never shown (the
    copper tools' tickets). Marks: F company assumption, "You" for an input, C computed by this project. Reset returns
    to the company's assumptions. Nothing is saved.
- **Links:** the library lists it under "Company research" (a static card), and the copper thesis links to it beside
  the copper tools and the metals page. No top-bar item.
- **Not here:** valuation, target price, share prices or advice; saved scenarios. Access stays administrators only.

## Open policy questions

None open for the freeze and assessment paths. Baseline freshness was decided on
2026-10-11 (policy B, under Market data) and is implemented for every new freeze.

## Screens

- / Tracker: headline action, pending/evaluated hypotheses and separate research tabs.
  Built so far (read-only, from the prepared index): prospective cases and
  retrospective replays in separate sections, each case's usage, publication date and
  recorded evaluation status, where "Not yet evaluated" (no stored evaluation) is
  distinct from a recorded "Pending" result. Research intake is shown as closed, no
  rates are computed from showcase cases, and every row links to its Dossier. The
  headline action and research tabs are not built. A separate "Drafts for review"
  section lists prepared draft review views (below) with a selectable panel; it loads
  independently of the Dossier index. Its "Your review" form saves human review
  versions explicitly, marks unsaved changes and asks before leaving them, and keeps
  edits when a save is refused, unconfirmed or still in flight. An "Analyze an event"
  panel captures an event, shows the exact saved request and the cost decision, and
  records one local mock or (on a server started for it) one paid attempt, which opens
  in that review panel. Its "Saved events" list reopens a capture after a reload, and
  "Refresh saved preview" re-reads the one shown, both with reads only. A "Case library"
  section lists the editorial cases (title, category, publication date, summary). An
  "Event inbox" section (above) lists cached official releases, energy articles and trade
  news with each source's state, topic, kind and credit, filterable by topic and source; "Refresh events" is its one network action, and "Analyze this event"
  fills the Analyze an event form, asking first before replacing work. Its "Headline
  triage" panel (above) previews up to 25 selected entries, reusing saved results and
  planning only missing work for an explicit approval, and shows categories,
  summaries and possible same-event groups. "Show retained headlines" lists archived
  entries no longer in their feeds. Each source card states its latest retrieval record (status, complete or partial
  body, SHA-256, kept copy, cache validators, parser, new, unchanged, changed and refused counts); a refresh lists those
  counts per source and says nothing was triaged or analyzed; each entry states its held texts, when the inbox first
  retrieved it (never a publication time), and a processing chip from the processing index ("Not processed" is a
  state).
- /analyses My analyses: the Tracker's published analyses (above) newest first, each with
  its headline and source link, publication time in its offset and in UTC, outcome,
  response mode and model provenance, review status and short previews of the model's
  words and the latest note as separate layers; search and filters in the address; empty,
  loading, failed and unreadable-record states; "Open review" into the Drafts for review
  panel, which a link brings into view, and a link back. Read-only. Not built: sorting
  other than newest sent first, paging for large collections (every load re-verifies each
  record), prepared pilot drafts (they stay in Drafts for review), and any export.
- /market-context and /market-context/(inbox|capture)/:id Market context (above): saved events with their
  context date, completeness and changes; local retrievals with their origin; every attempt. An event page has the
  date (supplied, or suggested and confirmed with the convention), the plan with its one approval, the attempts,
  then the descriptive changes, chart, table, provenance and limits. The Event inbox's Federal Reserve and BLS
  entries link to it; energy and trade entries say they are outside it. Not built: other series or sources,
  intraday data, exports, and any use in research summaries.
- /events/capture/:id/research Evidence-first research analysis (above): the separate request with its cost decision
  and exact bytes, one explicit mock or paid send, the result with the source's quoted words, the interpretation and
  the unknowns as separate sections and the quoted passages marked in the captured text, and the reviewer's versions;
  then the market-implied rate path panel (above), which says the analysis's request did not carry it.
- /events/inbox/:id and /events/capture/:id Event overview (above): a processing history (dated steps from retrieval
  to triage, analysis, review and freeze, with costs kept apart and what cannot be shown), then source (with the
  entry's held texts), saved headline triage, draft and human
  review, and market context of one entry or saved event (for a saved FOMC statement also the market-implied rate
  path, above), with an empty section's reason and a link to the existing
  workflow; "Open review" into the existing review screen and back. Linked from Event inbox entries, My analyses
  cards and market-context entries. Read-only, except the Related cases section's one explicit local check; a Related
  research section below it links to existing library cases (above). Not built: editing anything from it, and a list of
  all overviews.
- /library and /library/:id Case library: the collection's introduction, labels and
  selection rule, search, topic and sector filters kept in the address, and each case
  read in full, with previous/next navigation in publication order, a link to its topic
  and to each of its sectors, official source links and its provenance. Read-only; works
  without prepared files or runtime records. Every macro case adds a Market context
  section (above), or the reason it cannot be shown; a sector case states that no market
  series is attached. Below the release cases, the historical cases of Related Cases with the
  coverage not built yet; /library/historical/:id reads one, with its source facts and quotes,
  dates, scope, tags, labelled interpretation, unknowns, review status and source check.
  Below them, the theses (content only: each latest version's title, topic, version and publication date or draft,
  linking to /theses/:id; the list is hidden when there is none), then the research views
  (content only); /library/research/:id reads one (Research
  views, above): the question, scope and corpus limits, a legend of the statuses, the source
  check, a chronology keeping listing times, datelines and stated dates apart with their
  precision, a compact matrix (instrument, stated relation, jurisdictions/actors/end uses,
  scope), a stage grid, comparison cards with expandable evidence and paragraph locators,
  each release's statements and linked documents not retained, the records considered but
  not included, the claims not made and the sources and review status.
- /theses/:id and /theses/:id/versions/:n Thesis (Theses, above), in the operator build only: twelve numbered
  sections in order. The header gives the topic, opening date, last update (or the draft's preparation day and a draft
  banner), confidence and its basis, the versions and what this read found (parts available, sources matching their
  records). Then the view; the balance in numbers (years across, lines down, each figure's publication, scenario,
  basis and unit, a computed gap with weeks of demand or the reason none is computed, and where each figure is cited);
  where the view differs from what others expect; reasons and risks (status and change, the two figures, which
  comparison it makes, the exact rule it is read by and what moved it last); what would change the view; who is
  exposed (companies that move the thesis, and companies it moves with their side and a stated or computed amount);
  the view log; the price record, as a record with no score or verdict; the plain-language notes gathered; and the
  claims not made. A Sources footer gives each source's state on this read, edition, terms, retrieval and, for a PDF,
  the pages transcribed and the method. A part that is not available shows its problems in place of its content.
  Read-only; the page computes nothing. There is no /theses index page; the case library lists the theses.
- /metals Metals (above), in the operator build only, linked from the case library's copper entry and the copper
  thesis page: a picker of the 45 chapters (the six defaults, or ?m=), the comparison (one row per picked metal and
  2025 production stage, as printed; a pick with none gets one row saying so), a details block per pick (USGS series,
  import sources and reliance, the IEA demand by scenario and supply by country for the six minerals) and a Sources
  footer giving each file's publisher and title, edition, terms (licence and note), state on this read with its detail,
  and its address. A withheld part shows frames and its problem. Read-only; the page computes nothing.
- /theses/copper/tools Copper tools (above), in the operator build only, linked from the copper thesis's header and
  its library entry: the header with what this read found and a legend (published, assumption, computed, missing);
  the Part 0 box (eight links of the AI and electrification question, each with an evidence status, linking only to
  the semiconductor research view, the findings, the industry findings and the copper thesis); the accounting
  boundary; the published baseline for a chosen year and scenario (demand rows with epsilon and delta, counted
  mine supply by country, the refining series apart); the three controls; results (R, its share, its change and
  the decomposition, and with entered inputs R' with its flags, after an explicit Compute that writes nothing);
  perturbations; Save this scenario (an explicit action) and the records checked again; the producer comparison,
  margins, projects and the capital-recovery panel (empty inputs, an explicit Compute); what is not claimed; and
  the Sources. The page computes nothing itself; every reply passes the fail-closed reader first.
- /hypotheses and /hypotheses/:id Hypotheses (Interface freeze, above): the store's state and
  frozen hypotheses with their status, the four-step freeze (origin, baseline, preview,
  approval) and each frozen record read-only, with its content, fingerprints, origin,
  baseline, freshness check, scoring window, classification and limitations. The list is
  the lifecycle journal, with an Outcome data card for one approved retrieval, and a "Before a
  freeze: readiness" card for a chosen publication date (Research readiness, above); each record
  adds outcome readiness, explicit outcome import, the assessment preview and the one
  "Evaluate and prepare Dossier" approval (Interface assessment, above).
- /hypotheses/:id/assessments/:evaluation one recorded assessment as stored, with an
  explicit Prepare Dossier when it has none; /hypotheses/:id/dossiers/:evaluation its
  prepared Dossier, with snapshot reproducibility and raw-source availability.
- /findings and /findings/:date Treasury findings (above): the evidence read, the one
  check, dated occasions with their status, entries not measured with their reasons and
  the method; an occasion page with its releases and records, findings, measured changes,
  context in the same evidence, other checks, provenance and limitations. Each event
  overview adds a Treasury findings band. Not built: other markets, sources or
  frequencies, intraday data, exports, and any use in research summaries.
- /findings/g17 Industry comparisons (above): every release's comparisons by row and month,
  every industry row's estimates release by release with each change's kind, the sources
  with their hashes and retrieval times, and the case-library links. The Findings page has
  three labelled parts: Treasury yields (H.15), Industries and revisions (G.17), the
  second with its own check, a manufacturing breadth summary (latest retained release,
  legend, counts table, breadth cards), divergence and revision cards, totals and method;
  /findings/g17 adds breadth by release and revised breadth for the same month; and
  Electricity by sector (EIA Table 7.6), with its own action, coverage and sources,
  the twelve-month table with a one-axis picture, finding cards, the January-June table,
  the reconciliation and the method. A last part, Cross-source comparisons, has its own
  action, coverage, two comparison tables with sources and limits.
- /h/:id Dossier: event/freeze/provenance, hypothesis map, per-leg chart and reference histogram.
- /method: scoring rules, limitations, results and a v1 Research Lab link.
  Built (read-only, static text plus the active rules version from the prepared index):
  the question and why consistency is not causal proof; evidence classes and usage;
  primary and secondary legs, measured and explanatory nodes; anchors, horizons and the
  unscored initial reaction; every label and its exact conditions; "Not yet evaluated"
  versus a recorded "Pending"; snapshot pinning, overlapping windows and daily-date
  limits; the offline drafting adapter and the absence of a validated model track
  record; the Treasury findings pilot; the industry findings; the electricity findings; the
  cross-source comparisons. The documented rules are tested against rules recorded in real
  evaluations, and the findings section against the pilot's constants.
  There are no research results to show, and the v1 Research Lab is named as a local
  repository without a link, because no public URL exists.

## Build stages and completion

Stage 1: strict schema, registry, anchors, scoring/OLS/placebos, append-only core,
offline CLI, behavioral tests and two showcase illustrations (now fictional events on fictional demonstration
series).
Stage 2: dedicated price adapter/calendars, Claude structured-output adapter,
FastAPI read/action separation and three React routes. Stage 2 also resolves:
- Scoreboard selector (resolved in 0.4): research summaries select exactly one
  rules configuration by hash; a read-only reader lists the stored configurations.
- Late-freeze estimation (resolved in rules 0.4.0): the equity model is fitted
  before event_anchor, so a late freeze cannot include the event reaction.
Then record a truly prospective hypothesis and observe its scored windows.
The prospective run demonstrates lifecycle operation, not model performance. Freezing,
outcome acquisition, evaluation, Dossier preparation and the lifecycle journal are
available through the interface (Hypotheses), verified with synthetic data and fake
transports; a real prospective trial through it is a later, separately approved step.

MVP completion requires the three real routes, strict live model output, fixtures
that run on a clean clone, full-suite CI and a prospective lifecycle demonstration.
A screenshot goes into README when the Dossier exists.

Outside MVP: scheduler, automated ingestion/clustering, engine promotion,
LLM explanations of failures, crack-spread flagship and v1 overlays/apps. The one
exception the operator started is the manually refreshed Event inbox (above): explicit,
five fixed feeds, no automation. Its headline triage suggests possible same-event groups
within one explicitly approved selection; it is not automated clustering. Market context for
selected events (above) requests market data only on an explicit approval, from one fixed
source, and never scores, freezes or attributes anything. The event overview (above) only reads and joins records
through explicit links; it is not clustering. The Treasury findings pilot (above) runs
only on an explicit local check of already retained evidence and acquires nothing; so do
the industry findings (above), on G.17 pages retained by approved acquisitions, and the
electricity findings (above), on EIA Table 7.6 files retained by approved acquisitions;
and the cross-source comparisons (above), on both of those retained sources.
The fuels page (above) is a reference page: its spot prices are refreshed only by the explicit `fuels refresh` command, its
crack is computed and labelled so, and nothing on it enters research scores.
Review scope at roughly 800 lines per source file or 10K core lines.
