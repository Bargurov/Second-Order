# Broader financial reporting: what access each examined source allows (checked 2026-10-25 and 2026-10-26)

## 2026-10-26 newsroom update (news-registry-0.5)

56 newsrooms and news publishers were examined on 2026-10-26 against their own feed catalogues, robots.txt and terms,
with at most one request per feed and no account, form, purchase or vendor contact. The service was treated as one that
may be commercial and serves many signed-in readers. Codes as below, plus **A-NC**: allowed for personal or
non-commercial use only. Silence is U, never A. Uses in order: Display (headline and link) / Excerpt / Classify (send
to an AI model) / Summarise. The record of the increment is `docs/news-newsroom-sources-2026-10-26.md` (private; not in the public repository).

**Connected** (each retrieved live through this application's fetcher on 2026-10-26):

| Publisher | Feed | Uses | Basis |
| --- | --- | --- | --- |
| Voice of America | `https://www.voanews.com/api/` | A / A / A / A for VOA's own text; wire copy N (skipped) | "All text, audio and video material produced exclusively by the Voice of America is in the public domain" ([copyright](https://www.voanews.com/p/5338.html)); AFP, AP and Reuters material excluded |
| Global Voices | `https://globalvoices.org/feed/` | A / A / A / A for GV's own content; partner articles U (skipped) | CC BY 3.0, "even commercially", credit with the author's name and the licence ([attribution policy](https://globalvoices.org/about/global-voices-attribution-policy/)) |
| Inter Press Service | `https://www.ipsnews.net/news/economy-trade/feed/` | A / U / U / AG | "You may use the feeds to download or publish IPS titles and headlines, provided you do not re-publish the complete story and you give IPS full credit for them" ([RSS](https://www.ipsnews.net/rss-feeds/)); other reuse by written agreement |

**Examined, not connected:**

| Publisher | D / E / C / S | Why (terms read 2026-10-26) |
| --- | --- | --- |
| Dow Jones (MarketWatch, WSJ, Barron's) | AG / AG / AG / N | RSS content not "in any commercial product or service" without written consent; no AI use; "Content" includes headlines ([terms](https://www.dowjones.com/terms-of-use/)) |
| Nasdaq.com | AG ×4 | personal, non-commercial; links only to the home page without an agreement ([legal](https://www.nasdaq.com/legal)) |
| Seeking Alpha | AG ×4 | personal noncommercial; republishing needs written consent; robots.txt excludes Claude-User ([terms](https://about.seekingalpha.com/terms)) |
| Business Insider / Markets Insider | N ×4 | personal non-commercial; no robots; no AI use including grounding and RAG ([terms](https://www.businessinsider.com/terms)) |
| Fortune | AG ×4 | RSS content not for commercial purposes without written authorisation ([terms](https://fortune.com/terms-of-use/)) |
| Forbes | AG ×4 | personal non-commercial; no storing in a database ([terms](https://www.forbes.com/terms-and-conditions/)) |
| CNBC (Versant) | AG / AG / AG / N | feed host disallows all; "No Commercial Use … whether for profit or for no profit" ([prohibited actions](https://www.versantmedia.com/terms/prohibited-actions)) |
| Bloomberg, Reuters | AG ×4 | no documented public feed; unchanged from 2026-10-25 |
| Investing.com | AG ×4 | "solely for your own personal use"; no automated extraction ([terms](https://cdn.investing.com/about-us/terms_and_conditions.html)) |
| Financial Times | A-NC / A-NC / AG / N | a website feed only if not "part of a paid for service or for other commercial gain"; no ML or AI use ([copyright policy](https://help.ft.com/legal-privacy/copyright-policy/)) |
| Yahoo Finance | A / A / AG / N | an RSS display clause, but its only working feed host disallows all robots and automated collection needs permission ([terms](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html)) |
| BBC | A-NC / A-NC / AG / AG | "For business use of our RSS feeds you'll need to get our permission, and there may be a fee to pay"; AI or computer analysis needs permission ([terms](https://www.bbc.co.uk/usingthebbc/terms-of-use/)) |
| NPR | A-NC / A-NC / AG / N | personal sites, or non-profits that are not news organisations; no derivative works ([terms](https://www.npr.org/about-npr/179876898/terms-of-use)) |
| Deutsche Welle | U / AG / AG / AG | publication on websites needs a licence ([licensing](https://corporate.dw.com/en/licensing-dw-content/a-77070261)) |
| CBC | A-NC / A-NC / AG / AG | feed "FOR PERSONAL USE ONLY"; commercial use by request form; its terms page could not be read |
| ABC Australia | AG ×4 | "personal, non-commercial use only" ([terms](https://help.abc.net.au/hc/en-us/articles/360001548096-ABC-Terms-of-Use)) |
| RNZ | N / N / AG / AG | "The RSS Feeds must not be used to aggregate content on other websites" ([legal](https://www.rnz.co.nz/about/legal)) |
| France 24 | AG ×4 | personal and private use only; TDM reserved ([legal notice](https://www.francemm.com/en/legal-notice)) |
| Al Jazeera | U ×4 | unreachable from this network (an ISP block page); not bypassed |
| CNA | N ×4 | "strictly for your personal and non-commercial uses only" ([RSS terms](https://www.channelnewsasia.com/rss/rssterms)) |
| NHK | N ×4 | RSS for individuals only |
| The Guardian (site RSS) | A-NC / A-NC / AG / AG | personal non-commercial; no AI, TDM or commercial use ([terms](https://www.theguardian.com/help/terms-of-service)) |
| CBS MoneyWatch | AG ×4 | "may not build a business or other enterprise utilizing any of the Content" ([terms](https://legal.paramount.com/us/en/cbsi/terms-of-use)) |
| Sky News | AG ×4 | no scripts to aggregate content "for any purpose"; no AI use ([terms](https://www.sky.com/help/articles/skycom-terms-and-conditions)) |
| FXStreet, Fox Business, Mint, Rigzone | A-NC / A-NC / AG / AG or N | free RSS for personal or non-commercial use only; Fox's market feeds are also disallowed by robots.txt |
| The Economic Times | N / N / AG / AG | "TIL forbids you from any attempts at displaying, hosting, aggregating … TIL's RSS feeds" ([RSS](https://economictimes.indiatimes.com/rss.cms)) |
| Business Standard | AG ×4 | reproducing headlines needs written permission; no AI or RAG use |
| Kitco, OilPrice.com, CoinDesk, Cointelegraph, Decrypt, The Motley Fool, Zacks, TheStreet | AG ×4 (Motley Fool, TheStreet: summaries N) | personal or non-commercial use; automated access needs written permission; OilPrice's llms.txt invites short excerpts but its terms say personal use only, so the terms decide |
| MINING.COM, Benzinga, Axios, Semafor, gCaptain, Splash247 | U ×4 | terms unreadable (403 or challenge), absent, or the feed disallowed (Axios) |
| The Conversation | A / A / U / N | each entry CC BY-ND 4.0; guidelines leave "commercial, non-journalism usage" to a fee discussion; robots.txt excludes Claude-User and Claude-Code. Recorded, not connected |
| Agência Brasil | A / A (journalistic) / U / U | Portuguese feeds only; commercial reproduction via EBC licensing. Recorded, not connected |
| RFE/RL | A / A / U / U | robots.txt disallows `/api/*`, every feed path |
| English Wikinews | A ×4 (CC BY) | closed: read-only since May 2026; feed paths disallowed |
| UN News | A / A / U / U | robots.txt allows the feed path only to Google's feed fetcher |
| ProPublica | U / N / U / N | CC BY-NC-ND: non-commercial, no automatic republication |
| Philippine News Agency, Xinhua | AG or U ×4 | no feed; commercial use needs written consent or no grant is published |

What this supports, and no more: among the examined commercial financial newsrooms, broadcasters and specialist
publishers (45), **none allows this service to show its feed without an agreement**; three public-domain or openly
licensed newsrooms do, and are connected. Providers not in these tables were not examined.

## 2026-10-26 connection update (official sources)

Two additional public sources were checked and connected: Census economic indicators (official RSS catalogue and
[citation/public-use policy](https://www.census.gov/about/policies/citation.html)) and RBA media releases (official
[RSS catalogue](https://www.rba.gov.au/rss/) and [copyright/attribution terms](https://www.rba.gov.au/copyright/)).
Only their permitted textual feed excerpts are used; neither connection grants rights in third-party material.
BEA remains disconnected: its feed host `apps.bea.gov/robots.txt` disallows the RSS path, independently of BEA's public
domain content policy. An initial adapter/probe was withdrawn after that check. Details and retained audit records
are in `docs/news-feed-expansion-2026-10-26.md` (private; not in the public repository). The earlier tables below retain their original dates and scope;
these two public connections do not resolve access to commercial financial journalism.

## Scope: what was examined, and what these conclusions do not cover

Each conclusion below is about **one named provider and the pages of its own that were read on 2026-10-25** (linked in
its row), plus one keyless request per API to see what it answers without credentials. No account was created,
nothing was bought, no paid request was made and no vendor was contacted. A provider that is not in these tables was
not examined, and nothing here says what its terms allow. Terms change; a row is only as current as its date. Where a
provider's terms page could not be read, the row says so and marks the use "U" rather than guessing.

Examined: 6 official or public sources (GDELT, DOJ Antitrust, Bank of Canada, SEC, ONS, European Commission), 7 more
official sources whose feeds or terms could not be used (listed under the first table), and 12 commercial or
journalism providers (second table). Not examined, among others: Bloomberg, the Financial Times, the Wall Street
Journal's own site licensing, CNBC, Nikkei, and any regional or non-English newswire.

The uses are kept apart because a source can allow one and forbid another:

- **Display**: show the headline and link (and an excerpt where stated).
- **Classify**: send the headline or text to an AI model to judge its economic relevance.
- **Text**: full article text is available.
- **Summarise**: an AI-written summary or analysis of the article may be shown to users.

A = allowed by the published terms read, N = forbidden by them, AG = needs an agreement, U = the pages read do not say
(or could not be read).

## Official and public sources (connected in this milestone: keyless, free)

| Source | Display | Classify | Text | Summarise | Conditions | Status here |
| --- | --- | --- | --- | --- | --- | --- |
| GDELT DOC 2.0 (other publishers' coverage) | A | A (titles) | none | titles only | cite the GDELT Project with a link to https://www.gdeltproject.org/ ([about](https://www.gdeltproject.org/about.html)) | connected (`news index`); rate-limited from this network: 18 of 22 recorded lookups answered 429, so a 429 now starts a recorded cooldown (`news index status`) |
| U.S. DOJ, Antitrust Division | A | A | A (pages) | A | public domain ([legal policies](https://www.justice.gov/legalpolicies)); robots crawl delay 10 s | connected, refreshed |
| Bank of Canada | A | A | A | A | credit the Bank and indicate changes ([terms](https://www.bankofcanada.ca/terms/)) | connected (RSS 1.0), refreshed |
| U.S. SEC press releases | A | A | A | A | a declared User-Agent with a contact address is required ([webmaster FAQ](https://www.sec.gov/os/webmaster-faq)) | connected, **not requested** until the operator sets `SECOND_ORDER_FEED_CONTACT` |
| UK ONS release calendar | A | A | A | A | Open Government Licence v3; User-Agent must give a company e-mail or URL ([bots](https://developer.ons.gov.uk/bots/)) | connected, **not requested** until the contact is set |
| European Commission full texts | A | A | A | A | CC BY 4.0, credit and changes indicated | text source added (documents service) |

Examined but not connected: FTC (its feeds answer 404 from this network, probably a geographic block), Eurostat
(robots.txt disallows the feed path), Council of the EU (its terms page could not be reached, so its terms are
unread), U.S. Treasury and BIS (no feed found), Commerce and USDA (blocked from this network).

## Commercial and journalism providers examined (none connected: each needs a key or an agreement)

| Provider | Display | Classify | Text | Summarise | Price | Pages read and what they say |
| --- | --- | --- | --- | --- | --- | --- |
| MT Newswires (enterprise) | AG | AG | AG | AG (offered) | not published | "purpose-built for licensed AI grounding and summarization … explicit permissions" ([AI enablement](https://www.mtnewswires.com/ai-enablement)); the $125–$250/month MCP plans are "personal, non-commercial" and "Within AI application only"; an enterprise tier exists "for any product or platform serving multiple users" ([plans](https://signup-mcp.mtnewswires.com/)) |
| Dow Jones Factiva (GenAI licence) | AG | AG | AG | AG (offered) | not published | "on-demand summarization or an approved chatbot", 8,000+ sources licensed for specific GenAI uses ([newswires for GenAI](https://www.dowjones.com/business-intelligence/newswires/products/newswires-for-genai/)); the standard terms forbid AI use without written permission ([terms §9.4.2](https://www.dowjones.com/terms-of-use/)) |
| Event Registry / NewsAPI.ai | A (paid plan) | A (paid plan) | returned, not republishable | its own outputs allowed; **publisher rights not licensed** | 5K plan $90/month | "Process the content with your own software and AI/LLM systems…", but "we cannot license publisher content" ([terms](https://newsapi.ai/terms), last updated 7 Oct 2026; [plans](https://newsapi.ai/plans)) |
| NewsAPI.org | U | U | N (200 characters) | U | $449/month (Business) | the Developer plan is "for development and testing … only"; `content` "is truncated to 200 chars"; no republishing; the terms are silent on AI ([terms](https://newsapi.org/terms), [pricing](https://newsapi.org/pricing)) |
| The Guardian Open Platform | AG | **N** | key | **N** | commercial: "Price dependent on usage" | clause 6(g) bars machine-learning and AI use ([access](https://open-platform.theguardian.com/access/)) |
| The New York Times APIs | N | **N** | N | **N** | non-commercial only | no commercial use; no use in an AI system ([terms](https://developer.nytimes.com/terms)) |
| Associated Press (Media API) | AG | U / AG | AG | AG | not published | content "depending on your contract terms"; AP sells human-written summaries as an "optional add-on" ([AP Media API](https://developer.ap.org/ap-media-api/), [FAQ](https://api.ap.org/media/v/docs/FrequentlyAskedQuestions.htm)) |
| Reuters / LSEG | AG | AG | AG | AG | not published | retrieval over "the latest Reuters stories" is offered for AI ([AI training and RAG](https://reutersagency.com/solutions/ai-training-rag/)); the brand guidelines forbid altering editorial meaning "including when … produced with the assistance of AI" ([attribution guidelines](https://reutersagency.com/brand-attribution-guidelines/)); robots.txt forbids automated collection without written consent |
| Benzinga News API | AG | U | AG | U | not published | licensing is by e-mail to its licensing desk; its licensing page answered 403, so **its terms are unread**; the API serves Benzinga's own content only |
| Alpha Vantage (NEWS_SENTIMENT) | AG | U | N | U / AG | $49.99–$249.99/month | "personal, non-commercial use, unless … agreed otherwise in writing" ([terms](https://www.alphavantage.co/terms_of_service/)) |
| Finnhub (company news) | AG | U | N | AG | Enterprise by quote | "strictly for personal use unless explicitly stated otherwise"; only Enterprise has "Commercial use. Redistribution right." ([terms](https://finnhub.io/terms-of-service)) |
| Marketaux | AG | U | N | U | $29–$199/month | "solely for your personal, non-commercial use"; no rights are granted in third-party content ([terms](https://www.marketaux.com/tos)) |

What this table supports, and no more: **among these 12 providers, none whose terms were read grants AI summaries of
its articles in a product serving many users without an agreement**. Two (MT Newswires enterprise, Factiva's GenAI
licence) offer that use under an agreement; two (the Guardian, the New York Times) forbid AI use; NewsAPI.org's terms
are silent on it; Event Registry allows AI processing under its own terms but states it cannot license publishers'
content; Benzinga's terms could not be read. It says nothing about providers that were not examined.

## The concrete option among the providers examined (not taken: it needs an agreement and money)

**MT Newswires enterprise** is the one examined provider whose own pages offer licensed AI summarization for a product
serving multiple users, from a single independent financial newswire (one counterparty). Verified requirements: contact
sales; the enterprise price is not published; the self-serve plans do not cover this use. **Dow Jones Factiva's GenAI
licence** is the examined alternative with many more publishers (see `docs/news-stories-contract.md`, section 10), also
by quote. **Event Registry** at $90/month would allow display and AI classification of many publishers' headlines and
excerpts under its own terms, but it states it cannot license publishers' content, so summaries of their articles
would still need the publishers' rights. Until one of these is agreed, independent journalism appears in Second Order
only as headlines and coverage counts (from GDELT), never as material for briefs or Go deeper.
