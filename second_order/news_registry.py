"""The news-source registry (news-registry-0.1): every publisher the news reads or was evaluated for, with what its
own terms allow.

Each entry states, separately and as verified (the date and the pages read are in ``checked``):

- ``headlines``: how its headlines and links can be had (a public feed, an API with a key, a licence, or none);
- ``full_text``: whether the article's text is available, and how;
- ``display``: what this application may show users of a feed entry: the headline, link and the feed's excerpt as
  supplied (``headline_excerpt``), or the headline and link only (``headline``);
- ``material``: whether the entry may be used to prepare a shared brief or sent for a user's deeper analysis
  (``permitted``: a public-domain official release, or one whose publisher encourages reuse with its credit; ``none``:
  the terms grant no such use, so the entry is listed and linked but never summarised or sent to a model);
- ``credentials`` and ``agreement``: what a connection would need that this application does not have;
- ``status``: ``connected`` (requested by the operator's explicit refresh, live access verified on the date given),
  ``needs_agreement``, ``needs_credentials``, ``not_connected`` (for another reason, stated), or ``fixture_only``
  (exercised by tests with SYNTHETIC feeds only).

Public feed availability is not permission: an entry is connected only when the publisher's own terms allow showing its
feed, and its material is used only when they allow that use. Nothing here fetches anything. The five official feeds
are the Event Inbox's own (event_inbox.SOURCES) and stay there as supporting evidence; every other connected feed,
official or not (news-registry-0.2 adds four official publishers whose terms allow reuse with a credit), is read by
news_feeds into its own cache. A publisher whose entries span many subjects has no ``interest``: each entry's interests
are found by its words alone.
"""
from dataclasses import dataclass

from . import event_inbox

REGISTRY_VERSION = "news-registry-0.5"
ROLES = ("official", "news", "company")
ROLE_LABEL = {"official": "Official release", "news": "News report", "company": "Company statement"}
DISPLAY = ("headline_excerpt", "headline")
MATERIAL = ("permitted", "none")
STATUSES = ("connected", "needs_agreement", "needs_credentials", "not_connected", "fixture_only")


@dataclass(frozen=True)
class Publisher:
    key: str
    name: str
    role: str
    interest: str | None  # The news interest (user_news) its every entry concerns; None: found by each entry's words.
    headlines: str
    full_text: str
    display: str
    material: str
    status: str
    terms_url: str
    checked: str  # When and on which pages the access conditions were read.
    attribution: str = ""
    credentials: str | None = None
    agreement: str | None = None
    feed: event_inbox.Source | None = None  # The feed news_feeds requests when connected; None otherwise.
    note: str = ""
    live_verified: str | None = None  # The date a live retrieval through the operator's refresh succeeded.
    synthetic: bool = False  # SYNTHETIC test and demo publishers only; never in the production registry.
    material_basis: str = ""  # Why the material may be used (its terms), when it may.


OFFICIAL_TERMS = {
    "fed-monetary": ("Public domain: \"Please cite to the Board as the source of the information\" "
                     "(https://www.federalreserve.gov/disclaimer.htm, read 2026-10-14)."),
    "bls-empsit": "U.S. government work in the public domain (https://www.bls.gov/bls/linksite.htm).",
    "bls-cpi": "U.S. government work in the public domain (https://www.bls.gov/bls/linksite.htm).",
    "eia-todayinenergy": ("Public domain, credit \"Source: U.S. Energy Information Administration\" "
                          "(https://www.eia.gov/about/copyrights_reuse.php, read 2026-10-08)."),
    "wto-news": ("Dissemination encouraged with the attribution \"WTO news\", without the logo "
                 "(https://www.wto.org/english/info_e/copyrights_permissions_e.htm, read 2026-10-08)."),
}
OFFICIAL_INTEREST = {"fed-monetary": "monetary-policy", "bls-empsit": "employment", "bls-cpi": "inflation",
                     "eia-todayinenergy": "energy", "wto-news": "trade"}
LIVE_OFFICIAL = {"fed-monetary": "2026-10-25", "eia-todayinenergy": "2026-10-25", "wto-news": "2026-10-25"}
ATTRIBUTION = {"fed-monetary": "Source: Board of Governors of the Federal Reserve System"}


def _official(source: event_inbox.Source) -> Publisher:
    contact = source.contact_required
    return Publisher(
        source.key, source.publisher, "official", OFFICIAL_INTEREST[source.key], "public_feed",
        "public_page", "headline_excerpt", "permitted", "connected", source.terms_url,
        "Event Inbox source, checked against its feed catalogue and terms when it was added.",
        attribution=source.attribution or ATTRIBUTION.get(source.key, ""),
        note=("Requested only when the operator's contact is set (its robot policy)." if contact else ""),
        live_verified=LIVE_OFFICIAL.get(source.key), material_basis=OFFICIAL_TERMS[source.key])


TECHCRUNCH = event_inbox.Source(
    "techcrunch", "TechCrunch: latest", "TechCrunch", "Technology", "https://techcrunch.com/feed/",
    "https://techcrunch.com/subscribing/", "https://techcrunch.com/rss-terms-of-use/", "techcrunch.com", False,
    kind="News report", attribution="TechCrunch", keep_raw=False)
PR_NEWSWIRE = event_inbox.Source(
    "prnewswire-business", "PR Newswire: general business news releases", "PR Newswire", "Company statements",
    "https://www.prnewswire.com/rss/general-business-latest-news/general-business-latest-news-list.rss",
    "https://www.prnewswire.com/rss/", "https://www.prnewswire.com/terms-of-use/", "www.prnewswire.com", False,
    kind="Company statement", attribution="PR Newswire", keep_raw=False, excerpts=False)
# news-registry-0.2: official publishers outside the Event Inbox whose terms allow reuse with a credit. Each feed was
# requested once through this application's own fetcher and parser on 2026-10-25 (HTTP 200, every entry accepted); its
# complete responses are not kept (the White House's runs to about 650 kB).
WHITE_HOUSE = event_inbox.Source(
    "whitehouse-news", "The White House: news (fact sheets, presidential actions, statements)", "The White House",
    "U.S. administration", "https://www.whitehouse.gov/news/feed/", "https://www.whitehouse.gov/news/",
    "https://www.whitehouse.gov/copyright/", "www.whitehouse.gov", False, kind="Official statement",
    attribution="The White House", keep_raw=False)
USTR = event_inbox.Source(
    "ustr-press", "USTR: press releases and news", "Office of the United States Trade Representative", "Trade",
    "https://ustr.gov/rss.xml", "https://ustr.gov/about-us/policy-offices/press-office/press-releases",
    "https://ustr.gov/privacy-legal", "ustr.gov", False, kind="Press release", attribution="USTR", keep_raw=False)
EU_COMMISSION = event_inbox.Source(
    "ec-press", "European Commission: press corner", "European Commission", "EU policy",
    "https://ec.europa.eu/commission/presscorner/api/rss?language=en&pagesize=20",
    "https://ec.europa.eu/commission/presscorner/home/en", "https://commission.europa.eu/legal-notice_en",
    "ec.europa.eu", False, kind="Press release or speech", attribution="European Commission (© European Union)",
    keep_raw=False)
ECB = event_inbox.Source(
    "ecb-press", "ECB: press releases, speeches and interviews", "European Central Bank", "Monetary policy",
    "https://www.ecb.europa.eu/rss/press.html", "https://www.ecb.europa.eu/home/html/rss.en.html",
    "https://www.ecb.europa.eu/services/disclaimer/html/index.en.html", "www.ecb.europa.eu", False,
    kind="Press release, speech or interview", attribution="Source: European Central Bank", keep_raw=False)

# news-registry-0.3 (2026-10-25): four more official publishers whose terms allow reuse with a credit, chosen because
# they report on the same developments as the official sources above (competition cases, central banks, securities
# enforcement, statistics). Each feed was requested once from this machine through curl without a key; the SEC's and
# the ONS's fair-access rules ask automated requests to carry the operator's contact, so they are requested only with
# one (SECOND_ORDER_FEED_CONTACT), like BLS.
DOJ_ANTITRUST = event_inbox.Source(
    "doj-antitrust", "U.S. Department of Justice: Antitrust Division news", "U.S. Department of Justice",
    "Competition", "https://www.justice.gov/news/rss?type%5B0%5D=image_gallery&type%5B1%5D=press_release&type%5B2%5D="
    "speech&type%5B3%5D=youtube_video&field_component=376&search_api_language=en&show_public_archived=0&require_all=0",
    "https://www.justice.gov/atr/news-feeds", "https://www.justice.gov/legalpolicies", "www.justice.gov", False,
    kind="Press release or speech", attribution="U.S. Department of Justice", keep_raw=False)
BANK_OF_CANADA = event_inbox.Source(
    "boc-press", "Bank of Canada: press releases", "Bank of Canada", "Monetary policy",
    "https://www.bankofcanada.ca/content_type/press-releases/feed/", "https://www.bankofcanada.ca/rss-feeds/",
    "https://www.bankofcanada.ca/terms/", "www.bankofcanada.ca", False, kind="Press release",
    attribution="Source: Bank of Canada", keep_raw=False)
SEC_PRESS = event_inbox.Source(
    "sec-press", "SEC: press releases", "U.S. Securities and Exchange Commission", "Markets",
    "https://www.sec.gov/news/pressreleases.rss", "https://www.sec.gov/about/rss-feeds",
    "https://www.sec.gov/privacy", "www.sec.gov", True, policy_url="https://www.sec.gov/os/webmaster-faq",
    kind="Press release", attribution="Source: U.S. Securities and Exchange Commission", keep_raw=False)
ONS_PUBLICATIONS = event_inbox.Source(
    "ons-publications", "ONS: publications", "Office for National Statistics", "Statistics",
    "https://www.ons.gov.uk/publications?rss", "https://www.ons.gov.uk/help/terms-conditions",
    "https://www.ons.gov.uk/help/termsandconditions", "www.ons.gov.uk", True,
    policy_url="https://developer.ons.gov.uk/bots/", kind="Statistical publication",
    attribution="Contains public sector information licensed under the Open Government Licence v3.0", keep_raw=False)

RBA_RELEASES = event_inbox.Source(
    "rba-releases", "Reserve Bank of Australia: media releases", "Reserve Bank of Australia", "Monetary policy",
    "https://www.rba.gov.au/rss/rss-cb-media-releases.xml", "https://www.rba.gov.au/rss/",
    "https://www.rba.gov.au/copyright/", "www.rba.gov.au", False, kind="Official release",
    attribution="Source: Reserve Bank of Australia; summary by Second Order (CC BY 4.0)", keep_raw=False)
CENSUS_INDICATORS = event_inbox.Source(
    "census-indicators", "U.S. Census Bureau: economic indicators", "U.S. Census Bureau", "Economy",
    "https://www.census.gov/economic-indicators/indicator.xml", "https://www.census.gov/about/contact-us/feeds.html",
    "https://www.census.gov/about/policies/citation.html", "www.census.gov", False,
    attribution="Source: U.S. Census Bureau; interpretation by Second Order", keep_raw=False)

# news-registry-0.5 (2026-10-26): three newsrooms whose own terms allow a service like this one to use their feeds,
# checked against the publishers' pages that day (docs/news-source-access.md). Each feed skips the entries it carries
# for other publishers before anything of them is kept (event_inbox.Source.excluded_credits and excluded_markers).
VOA_NEWS = event_inbox.Source(
    "voa-news", "Voice of America: top stories", "Voice of America", "World news", "https://www.voanews.com/api/",
    "https://www.voanews.com/rssfeeds", "https://www.voanews.com/p/5338.html", "www.voanews.com", False,
    kind="News report", attribution="Voice of America (voanews.com)", keep_raw=False,
    excluded_credits=("Associated Press", "AP", "Reuters", "Agence France-Presse", "AFP"))
GLOBAL_VOICES = event_inbox.Source(
    "globalvoices", "Global Voices: latest stories", "Global Voices", "World news", "https://globalvoices.org/feed/",
    "https://globalvoices.org/about/global-voices-attribution-policy/",
    "https://globalvoices.org/about/global-voices-attribution-policy/", "globalvoices.org", False,
    kind="News report", attribution="Global Voices (CC BY 3.0, https://creativecommons.org/licenses/by/3.0/)",
    keep_raw=False, full_text_element=True, credit_creator=True,
    excluded_markers=(r"content[- ](?:sharing|partnership) agreement", r"republished (?:here|on Global Voices)",
                      r"(?:originally|first) published (?:in|on|by) (?!Global Voices)"))
IPS_ECONOMY = event_inbox.Source(
    "ips-economy", "Inter Press Service: economy and trade", "Inter Press Service", "Development economics",
    "https://www.ipsnews.net/news/economy-trade/feed/", "https://www.ipsnews.net/rss-feeds/",
    "https://www.ipsnews.net/rss-feeds/", "www.ipsnews.net", False, kind="News report",
    attribution="IPS News Agency (ipsnews.net)", keep_raw=False, excerpts=False, full_text_element=True,
    excluded_credits=("External Source",))

CHECKED = "Read 2026-10-25 (official pages; no sign-up, credential or purchase)."
CHECKED_NEWSROOMS = "Read 2026-10-26 (the publisher's own pages and robots.txt; no sign-up, credential or purchase)."
OFFICIAL_FEED_NOTE = ("An official release: the publisher's own words, credited and linked. Its headline and the "
                      "feed's excerpt may be material for a shared brief or a deeper analysis.")
PUBLISHERS = {publisher.key: publisher for publisher in (
    *(_official(source) for source in event_inbox.SOURCES.values()),
    Publisher("rba-releases", "Reserve Bank of Australia", "official", None, "public_feed", "public_page",
              "headline_excerpt", "permitted", "connected", RBA_RELEASES.terms_url,
              "Read 2026-10-26: RBA material is CC BY 4.0 unless marked otherwise, excluding logos and third-party "
              "content; credit the RBA, indicate changes and imply no endorsement. Its RSS path is not disallowed "
              "by robots.txt. No key or fee.",
              attribution=RBA_RELEASES.attribution, feed=RBA_RELEASES, live_verified="2026-10-26",
              material_basis="RBA-authored material under CC BY 4.0, with attribution and summaries identified as "
                             "changes; no endorsement (https://www.rba.gov.au/copyright/).",
              note="Feed excerpts only in this slice; no logos or third-party material are imported."),
    Publisher("census-indicators", "U.S. Census Bureau", "official", None, "public_feed", "public_page",
              "headline_excerpt", "permitted", "connected", CENSUS_INDICATORS.terms_url,
              "Read 2026-10-26: the Census feed catalogue advertises Economic Indicators; its citation policy asks "
              "that original data be credited and interpretations attributed to their author. Government-produced "
              "statistical releases, not third-party material (17 U.S.C. 105). Robots allows this path. No key or fee.",
              attribution=CENSUS_INDICATORS.attribution, feed=CENSUS_INDICATORS, live_verified="2026-10-26",
              material_basis="Government-produced economic statistics; cite the Census Bureau as the data source "
                             "and distinguish Second Order's interpretation (https://www.census.gov/about/policies/citation.html).",
              note="Economic indicators, not the general Census newsroom. Feed excerpts only; dated releases are not made new by retrieval."),
    Publisher("techcrunch", "TechCrunch", "news", "technology", "public_feed", "not_in_feed", "headline_excerpt",
              "none", "connected", "https://techcrunch.com/rss-terms-of-use/",
              f"{CHECKED} https://techcrunch.com/subscribing/ names the feed; https://techcrunch.com/rss-terms-of-use/: "
              "\"you are only permitted to display the content that is provided in the feed, with attribution to "
              "TechCrunch, and you must link to the full article\"; the terms of service limit use to personal, "
              "noncommercial use and forbid derivative works. robots.txt allows /feed/.",
              attribution="TechCrunch", feed=TECHCRUNCH,
              note=("Shown unmodified, credited and linked. Not summarised in a shared brief or sent for analysis: "
                    "the terms grant no such use. Personal, noncommercial use only.")),
    Publisher("prnewswire-business", "PR Newswire", "company", "companies", "public_feed", "partner_programme",
              "headline", "none", "connected", "https://www.prnewswire.com/terms-of-use/",
              f"{CHECKED} https://www.prnewswire.com/rss/ lists the feed; the terms of use allow personal, "
              "noncommercial use and forbid derivative works \"in full text or in abstract\" without consent and use "
              "for training AI systems. robots.txt allows /rss/.",
              attribution="PR Newswire", feed=PR_NEWSWIRE,
              note=("Company press releases, labelled as company statements: the company's own words, not "
                    "independent reporting. Headline and link only; never summarised or sent for analysis.")),
    Publisher("voa-news", "Voice of America", "news", None, "public_feed", "public_page", "headline_excerpt",
              "permitted", "connected", VOA_NEWS.terms_url,
              f"{CHECKED_NEWSROOMS} https://www.voanews.com/p/5338.html: \"All text, audio and video material produced "
              "exclusively by the Voice of America is in the public domain. Credit for any use of VOA material should "
              "be given to voanews.com, Voice of America, or VOA.\" The same page excludes AFP, AP and Reuters "
              "material, which \"shall not be published … or redistributed\" and may not \"be stored in a computer "
              "except for personal and non-commercial use\", and material licensed for VOA programming only. "
              "https://www.voanews.com/rssfeeds lists the feed (its Economy feed's newest entry is from March 2025, so "
              "the top-stories feed is read); robots.txt allows /api/. No key or fee.",
              attribution=VOA_NEWS.attribution, feed=VOA_NEWS,
              material_basis=("Text produced exclusively by VOA is in the public domain, credited to Voice of America "
                              "(https://www.voanews.com/p/5338.html); entries credited to AP, Reuters or AFP are "
                              "skipped before anything of them is kept."),
              note=("A U.S. government-funded newsroom. Its feed spans every subject, so the relevance assessment "
                    "decides which entries are economic news. Wire stories it carries are never kept. Its trademarks "
                    "and logo are not used; its name appears only as the credit its terms ask for.")),
    Publisher("globalvoices", "Global Voices", "news", None, "public_feed", "in_feed", "headline_excerpt",
              "permitted", "connected", GLOBAL_VOICES.terms_url,
              f"{CHECKED_NEWSROOMS} https://globalvoices.org/about/global-voices-attribution-policy/: \"Unless "
              "otherwise stated, all content created by Global Voices is published under a Creative Commons "
              "Attribution-Only license\": anyone may \"Adapt — remix, transform, and build upon the material for any "
              "purpose, even commercially\" if they \"give appropriate credit, provide a link to the license, and "
              "indicate if changes were made\", with \"the name of the author\"; material from other creators may be "
              "under other terms. The site footer names CC BY 3.0. robots.txt allows /feed/ (crawl delay 10 seconds; "
              "one request per refresh). No key or fee.",
              attribution=GLOBAL_VOICES.attribution, feed=GLOBAL_VOICES,
              material_basis=("Content created by Global Voices is CC BY 3.0: credited with its author and the "
                              "licence's address, a brief or analysis saying it is a summary (a change). Partner "
                              "articles republished under content-sharing agreements are skipped."),
              note=("A non-profit citizen-media newsroom. Each entry is credited to its author as the licence asks. "
                    "Entries marked as republished from another publisher are skipped; its full-article element is "
                    "read only to find that mark and never kept. Photos are never imported.")),
    Publisher("ips-economy", "Inter Press Service", "news", None, "public_feed", "in_feed", "headline", "none",
              "connected", IPS_ECONOMY.terms_url,
              f"{CHECKED_NEWSROOMS} https://www.ipsnews.net/rss-feeds/: \"You may use the feeds to download or publish "
              "IPS titles and headlines, provided you do not re-publish the complete story and you give IPS full "
              "credit for them.\" https://www.ipsnews.net/reprinting-articles/: any other republication or "
              "distribution needs IPS's written agreement. robots.txt allows the feed path.",
              attribution=IPS_ECONOMY.attribution, feed=IPS_ECONOMY,
              agreement="IPS's written agreement for excerpts, summaries or analysis (not requested).",
              note=("A non-profit news agency. Headline and link only, credited to IPS: its feed's excerpts and full "
                    "text are never kept, summarised or sent for analysis, so its stories await an editor and are "
                    "listed apart. Entries it credits to \"External Source\" are skipped; it also carries pieces under "
                    "the names of UN agencies and other organisations, which are listed as IPS headlines.")),
    Publisher("the-conversation", "The Conversation", "news", None, "public_feed", "in_feed", "headline", "none",
              "not_connected", "https://theconversation.com/us/republishing-guidelines",
              f"{CHECKED_NEWSROOMS} Each feed entry is \"Licensed as Creative Commons – attribution, no derivatives\" "
              "(CC BY-ND 4.0), which allows sharing the headline and summary verbatim with credit but no adapted "
              "material; https://theconversation.com/us/republishing-guidelines: \"Commercial, non-journalism usage: "
              "license fees may apply. Contact us to discuss.\" and \"You can't systematically republish all of our "
              "articles.\"; the UK guidelines ask a licence fee for commercial use. Its robots.txt disallows about 150 "
              "AI agents by name, including Claude-User and Claude-Code.",
              agreement=("The owner's decision on its commercial-use question, and a refresh not driven by an AI "
                         "agent its robots.txt excludes."),
              note=("Not connected in this increment: its own guidelines leave commercial use to a fee discussion, and "
                    "its robots.txt excludes the AI agent that ran this increment's refreshes. No AI summary would be "
                    "allowed in any case (no derivatives).")),
    Publisher("agencia-brasil", "Agência Brasil", "news", None, "public_feed", "in_feed", "headline", "none",
              "not_connected", "https://agenciabrasil.ebc.com.br/sobre",
              f"{CHECKED_NEWSROOMS} https://agenciabrasil.ebc.com.br/sobre: \"Reprodução autorizada para veículos de "
              "comunicação com fins jornalísticos, mediante indicação da fonte\"; reproduction for commercial purposes "
              "goes to EBC's licensing desk. The site now states \"© Todos os direitos reservados pela EBC\". Its "
              "feeds are in Portuguese only; its English edition has none.",
              agreement="EBC's licensing desk for commercial use (not requested).",
              note=("Not connected: its feeds are Portuguese only, its English and Portuguese terms differ, and "
                    "commercial reproduction needs a licence.")),
    Publisher("whitehouse-news", "The White House", "official", None, "public_feed", "public_page",
              "headline_excerpt", "permitted", "connected", "https://www.whitehouse.gov/copyright/",
              f"{CHECKED} https://www.whitehouse.gov/copyright/: \"Pursuant to federal law, government-produced "
              "materials appearing on this site are not copyright protected\"; third-party content is CC BY 3.0. The "
              "feed is the site's standard WordPress feed of its news section (not linked from the page); robots.txt "
              "disallows only site search.",
              attribution="The White House", feed=WHITE_HOUSE, live_verified="2026-10-25",
              material_basis=("U.S. government work, not copyright protected "
                              "(https://www.whitehouse.gov/copyright/, read 2026-10-25)."),
              note=(f"{OFFICIAL_FEED_NOTE} Its entries span many subjects, so each one's interests come from its "
                    "words. A response over 1 MB is refused by the feed limits, and the earlier entries are kept.")),
    Publisher("ustr-press", "Office of the U.S. Trade Representative", "official", "trade", "public_feed",
              "public_page", "headline_excerpt", "permitted", "connected", "https://ustr.gov/privacy-legal",
              f"{CHECKED} https://ustr.gov/rss.xml is the site's feed; the privacy and legal page states no reuse "
              "terms, and USTR's own works are U.S. government works (17 U.S.C. 105). robots.txt allows the feed.",
              attribution="USTR", feed=USTR, live_verified="2026-10-25",
              material_basis="U.S. government work in the public domain (17 U.S.C. 105); no other terms are stated.",
              note=f"{OFFICIAL_FEED_NOTE} The feed also lists an archived 2009 page, shown as older news."),
    Publisher("ec-press", "European Commission", "official", None, "public_feed", "public_page",
              "headline_excerpt", "permitted", "connected", "https://commission.europa.eu/legal-notice_en",
              f"{CHECKED} https://commission.europa.eu/legal-notice_en: content owned by the EU is licensed under CC "
              "BY 4.0 (Decision 2011/833/EU): \"reuse is allowed, provided appropriate credit is given and changes are "
              "indicated\"; logos and third-party content are excluded. robots.txt allows the press corner.",
              attribution="European Commission (© European Union)", feed=EU_COMMISSION, live_verified="2026-10-25",
              material_basis=("CC BY 4.0, with credit and changes indicated "
                              "(https://commission.europa.eu/legal-notice_en, read 2026-10-25)."),
              note=(f"{OFFICIAL_FEED_NOTE} A brief says it is the editors' summary, which indicates the change the "
                    "licence asks to be indicated. Its entries span many subjects, so each one's interests come from "
                    "its words.")),
    Publisher("ecb-press", "European Central Bank", "official", "monetary-policy", "public_feed", "public_page",
              "headline_excerpt", "permitted", "connected",
              "https://www.ecb.europa.eu/services/disclaimer/html/index.en.html",
              f"{CHECKED} The disclaimer allows free use of the site's information when it appears accurately with the "
              "ECB cited as the source, and asks that modifications be stated explicitly; documents bearing authors' "
              "names need written permission to be republished. https://www.ecb.europa.eu/home/html/rss.en.html lists "
              "the feed; robots.txt allows it (crawl delay 5 seconds; one request per refresh).",
              attribution="Source: European Central Bank", feed=ECB, live_verified="2026-10-25",
              material_basis=("Free use with the ECB cited as the source and modifications stated "
                              "(https://www.ecb.europa.eu/services/disclaimer/html/index.en.html, read 2026-10-25)."),
              note=(f"{OFFICIAL_FEED_NOTE} Its feed gives headlines without excerpts, so a brief from it rests on the "
                    "headline alone and says so.")),
    Publisher("doj-antitrust", "U.S. Department of Justice (Antitrust Division)", "official", None, "public_feed",
              "public_page", "headline_excerpt", "permitted", "connected", "https://www.justice.gov/legalpolicies",
              f"{CHECKED} https://www.justice.gov/legalpolicies: material on the site is \"public domain and may be "
              "copied and distributed without permission\" (third-party photographs and seals excluded); the feed is "
              "linked from https://www.justice.gov/atr/news-feeds; robots.txt allows /news/rss (crawl delay 10 "
              "seconds; one request per refresh).",
              attribution="U.S. Department of Justice", feed=DOJ_ANTITRUST, live_verified="2026-10-25",
              material_basis="U.S. government work in the public domain (https://www.justice.gov/legalpolicies).",
              note=(f"{OFFICIAL_FEED_NOTE} The Antitrust Division's press releases and speeches: competition cases "
                    "that other authorities and news may report too. Each entry's interests come from its words.")),
    Publisher("boc-press", "Bank of Canada", "official", "monetary-policy", "public_feed", "public_page",
              "headline_excerpt", "permitted", "connected", "https://www.bankofcanada.ca/terms/",
              f"{CHECKED} https://www.bankofcanada.ca/terms/: its content may be freely used, copied, distributed and "
              "transmitted, crediting the Bank and indicating if changes were made; content resold in a paid service "
              "must say it is free on the Bank's site. robots.txt disallows only /wp-admin/. The feed is RSS 1.0.",
              attribution="Source: Bank of Canada", feed=BANK_OF_CANADA, live_verified="2026-10-25",
              material_basis=("Free use with credit to the Bank of Canada and changes indicated "
                              "(https://www.bankofcanada.ca/terms/, read 2026-10-25); a brief says it is a summary."),
              note=f"{OFFICIAL_FEED_NOTE} A brief or analysis of it says that it is a summary (a change)."),
    Publisher("ons-publications", "Office for National Statistics", "official", None, "public_feed", "public_page",
              "headline_excerpt", "permitted", "connected", "https://www.ons.gov.uk/help/termsandconditions",
              f"{CHECKED} https://www.ons.gov.uk/help/terms-conditions: content under the Open Government Licence v3.0, "
              "which allows commercial use with the attribution \"Contains public sector information licensed under "
              "the Open Government Licence v3.0\"; https://developer.ons.gov.uk/bots/ asks automated clients to "
              "name a company email or address in the User-Agent (not a personal email), at most 120 requests in 10 "
              "seconds. The feed answered 200 on 2026-10-25.",
              attribution="Contains public sector information licensed under the Open Government Licence v3.0",
              feed=ONS_PUBLICATIONS,
              material_basis="Open Government Licence v3.0, with its attribution.",
              note=(f"{OFFICIAL_FEED_NOTE} Requested only when the operator's contact is set "
                    "(SECOND_ORDER_FEED_CONTACT), as the ONS's bot rules ask.")),
    Publisher("gdelt-index", "GDELT Project (news index)", "news", None, "api_free", "not_in_index", "headline",
              "none", "connected", "https://www.gdeltproject.org/about.html",
              f"{CHECKED} https://www.gdeltproject.org/about.html: GDELT's datasets are \"available for unlimited and "
              "unrestricted use for any academic, commercial, or governmental use of any kind without fee\", and any "
              "use or redistribution \"must include a citation to the GDELT Project and a link to this website\". The "
              "DOC 2.0 API returns each article's address, title as indexed, domain, language, source country and when "
              "GDELT saw it, never its text; it asks for at most one request every five seconds (429 otherwise; from "
              "this machine it answered 429 often on 2026-10-25). The publishers' own terms for their articles are "
              "theirs, not GDELT's.",
              attribution="Indexed by the GDELT Project (https://www.gdeltproject.org/)",
              live_verified="2026-10-25",
              note=("An index of other publishers' coverage, looked up per story by the operator: each attached "
                    "article shows its indexed title and link, credited to its publisher and to GDELT, and counts as "
                    "that publisher's coverage. Nothing of it is sent to a model or summarised.")),
    Publisher("bea", "U.S. Bureau of Economic Analysis", "official", "markets", "public_feed", "public_page",
              "headline", "permitted", "not_connected", "https://www.bea.gov/help/guidelines-for-citing-bea",
              f"{CHECKED} https://apps.bea.gov/rss/rss.xml answers, but that host's robots.txt disallows everything "
              "except /api/; BEA's releases are U.S. government works.",
              agreement="BEA's permission for automated access to apps.bea.gov (its robots.txt allows only /api/).",
              material_basis="U.S. government work in the public domain (17 U.S.C. 105).",
              note="Not requested: its feed host asks robots not to read it."),
    Publisher("sec-press", "U.S. Securities and Exchange Commission", "official", "markets", "public_feed",
              "public_page", "headline_excerpt", "permitted", "connected", "https://www.sec.gov/privacy",
              f"{CHECKED} https://www.sec.gov/os/webmaster-faq: government-created content on sec.gov is free to access "
              "and reuse; https://www.sec.gov/privacy: it \"may be copied or further distributed\", citing the SEC, "
              "without its seal. Automated requests must declare a contact in the User-Agent (\"Sample Company Name "
              "AdminContact@<sample company domain>.com\"), at most 10 requests per second; an undeclared request is "
              "refused (403).",
              credentials="The operator's contact in the User-Agent (SECOND_ORDER_FEED_CONTACT), as the SEC asks.",
              feed=SEC_PRESS, attribution="Source: U.S. Securities and Exchange Commission",
              material_basis="Government-created content free to reuse, citing the SEC (https://www.sec.gov/privacy).",
              note=(f"{OFFICIAL_FEED_NOTE} Requested only when the operator's contact is set "
                    "(SECOND_ORDER_FEED_CONTACT).")),
    Publisher("bank-of-england", "Bank of England", "official", "monetary-policy", "public_feed", "public_page",
              "headline", "none", "needs_agreement", "https://www.bankofengland.co.uk/legal",
              f"{CHECKED} https://www.bankofengland.co.uk/rss/news answers; the legal page allows personal or internal "
              "use and says the Bank \"typically grants permission for non-commercial re-use\"; commercial reuse needs "
              "its permission.",
              agreement="The Bank of England's permission for reuse in this service.",
              note="Not connected: its terms grant non-commercial reuse only."),
    Publisher("freightwaves", "FreightWaves", "news", "trade", "public_feed", "in_feed", "headline", "none",
              "needs_agreement", "https://www.freightwaves.com/terms-of-use",
              f"{CHECKED} The feed https://www.freightwaves.com/feed exists, but the terms of use allow personal use "
              "only and forbid automated access for any purpose; no feed permission is published.",
              agreement="Written permission from FreightWaves for automated feed access.",
              note="Exercised with SYNTHETIC feeds only until FreightWaves grants permission."),
    Publisher("cnbc", "CNBC", "news", "markets", "public_feed", "not_in_feed", "headline", "none", "needs_agreement",
              "https://www.versantmedia.com/terms",
              f"{CHECKED} https://www.cnbc.com/rss-feeds/ lists feeds but grants no licence; the terms (Versant) allow "
              "personal, non-commercial use and forbid robots that aggregate content; the feed host's robots.txt "
              "disallows everything.",
              agreement="A content licence from CNBC (Versant Media)."),
    Publisher("bloomberg", "Bloomberg", "news", "markets", "licence", "paywalled", "headline", "none",
              "needs_agreement", "https://www.bloomberg.com/notices/tos/",
              f"{CHECKED} No documented public feed or news API; the terms allow \"your own noncommercial use\" and "
              "forbid caching or mirroring.", agreement="A Bloomberg content licence."),
    Publisher("reuters", "Reuters", "news", "markets", "licence", "licence", "headline", "none", "needs_agreement",
              "https://www.reutersconnect.com/plans-and-pricing",
              f"{CHECKED} No public feed; text is offered by subscription (\"please contact us\"); robots.txt forbids "
              "automated collection without written consent.", agreement="A Reuters Connect text subscription."),
    Publisher("ap", "The Associated Press", "news", "markets", "licence", "licence", "headline", "none",
              "needs_agreement", "https://www.ap.org/terms-and-conditions/",
              f"{CHECKED} No public feed (apnews.com disallows .rss in robots.txt); https://www.ap.org/content/ is a "
              "licensing contact page; the terms allow personal non-commercial use and forbid archiving.",
              agreement="An AP content licence."),
    Publisher("investing-com", "Investing.com", "news", "markets", "public_feed", "not_in_feed", "headline", "none",
              "needs_agreement", "https://www.investing.com/webmaster-tools/rss",
              f"{CHECKED} Feeds are listed, but the site forbids using, storing or displaying its data without written "
              "permission; most items are Reuters wire copy and the feed's times state no zone.",
              agreement="Written permission from Fusion Media (and the wire's licence)."),
    Publisher("financial-times", "Financial Times", "news", "markets", "public_feed", "paywalled", "headline",
              "none", "needs_agreement", "https://help.ft.com/legal-privacy/copyright-policy/",
              f"{CHECKED} Feeds exist; the copyright policy forbids archiving the feed, paid services and any machine "
              "learning or AI use of content or metadata.", agreement="An FT content licence."),
    Publisher("guardian", "The Guardian", "news", "markets", "api_key", "api_key", "headline", "none",
              "needs_credentials", "https://www.theguardian.com/open-platform/terms-and-conditions",
              f"{CHECKED} https://open-platform.theguardian.com/access/: a free developer key is for non-commercial "
              "use; its terms forbid keeping content over 24 hours and AI or text-mining use; the site terms forbid "
              "AI use of feeds and metadata.", credentials="An Open Platform key (developer or commercial).",
              agreement="A commercial Open Platform licence for AI-assisted use."),
    Publisher("yahoo-finance", "Yahoo Finance", "news", "markets", "public_feed", "not_in_feed", "headline", "none",
              "not_connected", "https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",
              f"{CHECKED} Per-ticker feeds exist but are undocumented; the terms allow unmodified display with "
              "attribution and forbid automated collection without permission; the feed host's robots.txt disallows "
              "everything; most links go to other publishers.",
              agreement="Yahoo's permission for automated collection, and each linked publisher's terms."),
)}


def connected() -> list[Publisher]:
    """The publisher feeds the operator's refresh requests (news_feeds); the Event Inbox's five official feeds have no
    ``feed`` here and are refreshed by the Inbox."""
    return [publisher for publisher in PUBLISHERS.values() if publisher.status == "connected" and
            publisher.feed is not None]


def entry_view(publisher: Publisher) -> dict:
    """What the registry says of one publisher, as every view shows it."""
    return {"source": publisher.key, "publisher": publisher.name, "role": publisher.role,
            "role_label": ROLE_LABEL[publisher.role], "interest": publisher.interest, "headlines": publisher.headlines,
            "full_text": publisher.full_text, "display": publisher.display, "material": publisher.material,
            "material_basis": publisher.material_basis, "status": publisher.status, "terms_url": publisher.terms_url,
            "checked": publisher.checked, "attribution": publisher.attribution, "credentials": publisher.credentials,
            "agreement": publisher.agreement, "note": publisher.note, "live_verified": publisher.live_verified,
            "synthetic": publisher.synthetic, "feed_url": publisher.feed.feed_url if publisher.feed else None}
