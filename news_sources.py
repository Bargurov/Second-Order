# news_sources.py
# Loads headlines from local JSON and RSS feeds, normalizes them to a common
# shape, and deduplicates obvious repeats.
#
# Each headline record looks like:
#   {"source": str, "title": str, "published_at": str, "url": str}
#
# No database writes happen here — this module just collects and returns.

import json
import logging
import os
import re
import socket
from datetime import datetime
from email.utils import parsedate_to_datetime

_log = logging.getLogger("second_order.news")

# Maximum seconds to wait for any single RSS feed before skipping it.
_FEED_TIMEOUT = 8

# ---------------------------------------------------------------------------
# Source reliability tiers
# ---------------------------------------------------------------------------
# Used to pick the best headline per cluster and to order sources in merged
# output.  "high" = major wire / broadsheet with editorial standards and
# fact-checking.  "medium" = reputable but narrower editorial scope or
# regional.  "low" = user-submitted / unverified.

_SOURCE_TIERS: dict[str, str] = {
    # Wire services & broadsheets
    "BBC Business":          "high",
    "BBC World":             "high",
    "Reuters World":         "high",
    "The Guardian Business":  "high",
    "The Guardian World":     "high",
    "WSJ World News":         "high",
    "AP News":                "high",
    "FT World":               "high",
    "AFP World":              "high",
    "NPR World":              "high",
    # Financial / markets
    "CNBC World":             "high",
    "MarketWatch":            "medium",
    "Yahoo Finance":          "medium",
    "Investing.com":          "medium",
    # Geopolitical
    "Al Jazeera Economy":     "medium",
    "Al Jazeera":             "medium",
    # Energy / commodities
    "OilPrice.com":           "medium",
    "Rigzone":                "medium",
    "S&P Global Commodities": "high",
    # Asia / emerging markets
    "Bloomberg Markets":      "high",
    "Nikkei Asia":            "high",
    "SCMP Economy":           "medium",
    # Defense
    "Defense News":           "medium",
    # Government / policy
    "OFAC Sanctions":         "medium",
    "EIA Energy":             "medium",
    "USTR Trade Policy":      "high",
    "Fed Press Releases":     "high",
    "ECB Press Releases":     "high",
    "local":                  "low",
}

_TIER_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}


def source_tier(name: str) -> str:
    """Return the reliability tier for a named source."""
    return _SOURCE_TIERS.get(name, "low")


# ---------------------------------------------------------------------------
# Normalized record shape
# ---------------------------------------------------------------------------

# Common date formats found in RSS feeds and local JSON files.
# Tried in order; the first successful parse wins.
_DATE_FORMATS: list[str] = [
    "%Y-%m-%dT%H:%M:%S",       # 2026-04-05T14:30:00
    "%Y-%m-%dT%H:%M:%S%z",     # 2026-04-05T14:30:00+00:00
    "%Y-%m-%d %H:%M:%S",       # 2026-04-05 14:30:00
    "%Y-%m-%d",                 # 2026-04-05
    "%B %d, %Y",               # April 5, 2026
    "%b %d, %Y",               # Apr 5, 2026
    "%d %B %Y",                # 5 April 2026
    "%d %b %Y",                # 5 Apr 2026
]


def _normalize_timestamp(raw: str) -> str:
    """Best-effort parse of a raw timestamp string into ISO format.

    Tries RFC 2822 (email.utils) first — this covers the common RSS format
    'Sat, 05 Apr 2026 10:30:00 GMT'.  Then falls through strptime patterns.
    Returns the original string if nothing works, keeping the record usable.
    """
    if not raw or not raw.strip():
        return ""
    raw = raw.strip()

    # Already valid ISO — fast path
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", raw):
        return raw

    # RFC 2822 (most RSS published strings)
    try:
        dt = parsedate_to_datetime(raw)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        pass

    # Strptime fallbacks
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue

    # Unparseable — return as-is so the record isn't lost
    return raw


import re as _re_mod

# Common trailing source attributions added by Google News proxies and RSS feeds.
# Matched case-insensitively at the end of the headline string.
_ATTRIBUTION_RE = _re_mod.compile(
    r"\s*(?:[-–—|])\s*"
    r"(?:Reuters|AP News|Associated Press|AFP|France24[\w\s]*|"
    r"BBC[\w\s]*|The Guardian[\w\s]*|NPR[\w\s]*|"
    r"Al Jazeera[\w\s]*|Financial Times|FT[\w\s]*|WSJ[\w\s]*|"
    r"The Wall Street Journal|Bloomberg[\w\s]*|CNN[\w\s]*|"
    r"New York Times|The New York Times|CNBC[\w\s]*|"
    r"MarketWatch[\w\s]*|Yahoo Finance[\w\s]*|Investing\.com[\w\s]*|"
    r"OilPrice\.com[\w\s]*|Rigzone[\w\s]*|S&P Global[\w\s]*|"
    r"Bloomberg[\w\s]*|Nikkei[\w\s]*|South China Morning Post[\w\s]*|"
    r"Defense News[\w\s]*|"
    r"Federal Reserve[\w\s]*|ECB[\w\s]*|"
    r"[A-Z][\w\s,]{2,50}\(\.gov\)|"                      # "Office of Foreign Assets Control (.gov)"
    r"[A-Z][\w\s,]{2,40}\.(?:com|org|gov|co\.uk|net))"   # "corporatecomplianceinsights.com"
    r"\s*$",
    _re_mod.IGNORECASE,
)


def _strip_attribution(title: str) -> str:
    """Remove trailing '- Reuters', '| BBC News', etc. from a headline."""
    return _ATTRIBUTION_RE.sub("", title).strip()


def _make_record(source: str, title: str, published_at: str, url: str = "") -> dict:
    """Build one normalized headline record."""
    return {
        "source":       source,
        "title":        _strip_attribution(title.strip()),
        "published_at": _normalize_timestamp(published_at),
        "url":          url.strip(),
    }


# ---------------------------------------------------------------------------
# Source 1: Local JSON file
# ---------------------------------------------------------------------------

LOCAL_FILE = "news_inbox.json"

def load_local(path: str = LOCAL_FILE) -> list[dict]:
    """Load headlines from a local JSON file.

    Expected format — a list of objects, each with at least a "title" field:
      [
        {"title": "...", "source": "...", "published_at": "...", "url": "..."},
        ...
      ]

    Missing fields get sensible defaults. If the file doesn't exist, returns [].
    """
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            items = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    records = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = item.get("title", "").strip()
        if not title:
            continue
        records.append(_make_record(
            source=item.get("source", "local"),
            title=title,
            published_at=item.get("published_at", ""),
            url=item.get("url", ""),
        ))
    return records


# ---------------------------------------------------------------------------
# Source 2: RSS feeds
# ---------------------------------------------------------------------------

# Curated feeds — narrowed to business / world / politics / policy / energy
# sections to reduce general-news noise (sports, entertainment, lifestyle).
#
# 27 feeds across wire services, geopolitical, financial, energy/commodities,
# central bank, defense, and Asia/emerging-market sources.
#
# Feed selection notes:
#   - Reuters/AFP/Al Jazeera/MarketWatch/S&P Global via Google News RSS proxy:
#     these outlets block or gate their direct RSS but Google News exposes a
#     topic-filtered Atom feed that reliably surfaces their content.
#   - The Guardian: both /business/rss and /world/rss for trade/macro breadth.
#   - BBC: both /news/business and /news/world for geopolitical coverage.
#   - WSJ World News: financial + geopolitical, naturally filtered.
#   - Energy: OilPrice.com, Rigzone, S&P Global for commodity-specific depth.
#   - Central banks: Fed and ECB press releases for policy announcements.
DEFAULT_FEEDS: list[dict] = [
    {
        "name": "Reuters World",
        "url":  "https://news.google.com/rss/search?q=site:reuters.com+world+OR+business&hl=en&gl=US&ceid=US:en",
    },
    {
        "name": "The Guardian Business",
        "url":  "https://www.theguardian.com/business/rss",
    },
    {
        "name": "BBC Business",
        "url":  "https://feeds.bbci.co.uk/news/business/rss.xml",
    },
    {
        "name": "WSJ World News",
        "url":  "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
    },
    {
        "name": "AP News",
        "url":  "https://news.google.com/rss/search?q=site:apnews.com+economy+OR+trade+OR+sanctions&hl=en&gl=US&ceid=US:en",
    },
    {
        "name": "FT World",
        "url":  "https://www.ft.com/world?format=rss",
    },
    {
        "name": "OFAC Sanctions",
        "url":  "https://news.google.com/rss/search?q=OFAC+sanctions+designation&hl=en&gl=US&ceid=US:en",
    },
    {
        "name": "EIA Energy",
        "url":  "https://www.eia.gov/rss/todayinenergy.xml",
    },
    {
        "name": "USTR Trade Policy",
        "url":  "https://news.google.com/rss/search?q=site:ustr.gov+tariff+OR+trade+OR+%22executive+order%22&hl=en&gl=US&ceid=US:en",
    },
    # --- Wire services ---
    {
        "name": "AFP World",
        "url":  "https://news.google.com/rss/search?q=site:france24.com+economy+OR+trade+OR+sanctions&hl=en&gl=US&ceid=US:en",
    },
    # --- Geopolitical / general ---
    {
        "name": "Al Jazeera Economy",
        "url":  "https://news.google.com/rss/search?q=site:aljazeera.com+economy+OR+trade+OR+sanctions&hl=en&gl=US&ceid=US:en",
    },
    {
        "name": "BBC World",
        "url":  "https://feeds.bbci.co.uk/news/world/rss.xml",
    },
    {
        "name": "NPR World",
        "url":  "https://feeds.npr.org/1004/rss.xml",
    },
    {
        "name": "The Guardian World",
        "url":  "https://www.theguardian.com/world/rss",
    },
    # --- Financial / markets ---
    {
        "name": "MarketWatch",
        "url":  "https://news.google.com/rss/search?q=site:marketwatch.com+market+OR+economy+OR+fed&hl=en&gl=US&ceid=US:en",
    },
    {
        "name": "CNBC World",
        "url":  "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100727362",
    },
    {
        "name": "Yahoo Finance",
        "url":  "https://finance.yahoo.com/news/rssindex",
    },
    {
        "name": "Investing.com",
        "url":  "https://www.investing.com/rss/news.rss",
    },
    # --- Energy / commodities ---
    {
        "name": "OilPrice.com",
        "url":  "https://oilprice.com/rss/main",
    },
    {
        "name": "Rigzone",
        "url":  "https://www.rigzone.com/news/rss/rigzone_latest.aspx",
    },
    {
        "name": "S&P Global Commodities",
        "url":  "https://news.google.com/rss/search?q=site:spglobal.com+commodities+OR+oil+OR+gas&hl=en&gl=US&ceid=US:en",
    },
    # --- Central banks / macro ---
    {
        "name": "Fed Press Releases",
        "url":  "https://www.federalreserve.gov/feeds/press_all.xml",
    },
    {
        "name": "ECB Press Releases",
        "url":  "https://www.ecb.europa.eu/rss/press.html",
    },
    # --- Asia / emerging markets ---
    {
        "name": "Bloomberg Markets",
        "url":  "https://news.google.com/rss/search?q=site:bloomberg.com+economy+OR+market+OR+trade&hl=en&gl=US&ceid=US:en",
    },
    {
        "name": "Nikkei Asia",
        "url":  "https://news.google.com/rss/search?q=site:asia.nikkei.com+economy+OR+trade+OR+semiconductor&hl=en&gl=US&ceid=US:en",
    },
    {
        "name": "SCMP Economy",
        "url":  "https://news.google.com/rss/search?q=site:scmp.com+economy+OR+trade+OR+sanctions&hl=en&gl=US&ceid=US:en",
    },
    # --- Defense ---
    {
        "name": "Defense News",
        "url":  "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml",
    },
]


def load_rss(feeds: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    """Fetch headlines from RSS/Atom feeds.

    Each feed dict needs 'name' and 'url'.

    Returns
    -------
    (records, feed_status)
        records    : list of headline dicts (same shape as before).
        feed_status: one dict per feed attempted:
                     {"name": str, "ok": bool, "headlines": int}
    """
    try:
        import feedparser
    except ImportError:
        feed_status = [{"name": f["name"], "ok": False, "headlines": 0}
                       for f in (feeds or DEFAULT_FEEDS)]
        return [], feed_status

    if feeds is None:
        feeds = DEFAULT_FEEDS

    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    def _parse_one_feed(feed_info: dict) -> tuple[str, object, bool, str]:
        """Parse one feed via feedparser. Returns (name, parsed, ok, error)."""
        name = feed_info["name"]
        try:
            parsed = feedparser.parse(feed_info["url"])
            return (name, parsed, True, "")
        except Exception as e:
            return (name, None, False, str(e))

    # Fetch all feeds in parallel — worst case is ~_FEED_TIMEOUT, not N × _FEED_TIMEOUT.
    # Each feedparser.parse() does its own HTTP internally; the executor provides
    # parallelism without touching the process-global socket timeout.
    with ThreadPoolExecutor(max_workers=max(1, len(feeds))) as pool:
        futures = {pool.submit(_parse_one_feed, f): f for f in feeds}
        feed_results: list[tuple[str, object, bool, str]] = []
        for future in futures:
            try:
                feed_results.append(future.result(timeout=_FEED_TIMEOUT + 2))
            except (FuturesTimeout, Exception) as e:
                info = futures[future]
                feed_results.append((info["name"], None, False, f"timeout/exception: {e}"))

    records = []
    feed_status: list[dict] = []

    for feed_name, parsed, ok, err_msg in feed_results:
        if not ok or parsed is None:
            feed_status.append({
                "name": feed_name, "ok": False, "headlines": 0,
                "error": err_msg or "fetch failed",
            })
            _log.warning("[feed] %-30s  ERROR: %s", feed_name, err_msg or "fetch failed")
            continue

        count_before = len(records)
        for entry in parsed.entries:
            title = (entry.get("title") or "").strip()
            if not title:
                continue

            # published_parsed is a time.struct_time; fall back to empty string
            pub = ""
            if entry.get("published_parsed"):
                try:
                    pub = datetime(*entry.published_parsed[:6]).isoformat(timespec="seconds")
                except Exception:
                    pass
            elif entry.get("published"):
                pub = entry.published

            link = entry.get("link", "") or ""
            records.append(_make_record(
                source=feed_name,
                title=title,
                published_at=pub,
                url=link,
            ))

        added = len(records) - count_before
        if added == 0:
            _log.warning("[feed] %-30s  0 headlines (parsed OK but empty)", feed_name)
        feed_status.append({
            "name":      feed_name,
            "ok":        added > 0,
            "headlines": added,
            "error":     None if added > 0 else "0 entries after parse",
        })

    return records, feed_status


# ---------------------------------------------------------------------------
# Combine + deduplicate
# ---------------------------------------------------------------------------

def _dedup_key(title: str) -> str:
    """Lowercase, strip punctuation — catches obvious duplicates."""
    return "".join(ch for ch in title.lower() if ch.isalnum() or ch == " ").strip()


# ---------------------------------------------------------------------------
# Relevance filter — deterministic keyword allowlist
# ---------------------------------------------------------------------------
# Headlines must contain at least one domain keyword to pass.  This drops
# lifestyle, sports, entertainment, and other general-news noise before
# clustering.  Easy to tune: just add or remove words from the sets below.
#
# Two keyword tiers:
#   RELEVANCE_KEYWORDS  — safe for substring matching (multi-word phrases or
#                         long stems unlikely to false-positive).
#   _WORD_BOUNDARY_KW   — short/ambiguous words that need whole-word matching
#                         to avoid false positives ("oil" in "deported",
#                         "port" in "deported", "market" as a bazaar, etc.)

import re as _re

RELEVANCE_KEYWORDS: set[str] = {
    # Geopolitics & conflict
    "geopolit", "sanction", "embargo", "tariff", "duties", "treaty",
    "ceasefire", "truce", "diplomacy", "diplomatic", "nato", "sovereignty",
    "annex", "territorial", "missile", "military", "defense", "defence",
    "weapons", "nuclear", "drone", "wartime",
    "escalat", "de-escalat", "retaliat",
    # Trade & industrial policy
    "trade", "export", "subsid", "quota", "dumping",
    "industrial policy", "supply chain", "reshoring", "nearshoring",
    "protectionism", "free trade", "trade war", "trade deal",
    # Energy & commodities
    "crude", "opec", "natural gas", "lng", "pipeline",
    "petroleum", "refiner",
    "rare earth", "lithium", "cobalt",
    "copper", "steel", "alumin",
    "wheat", "grain", "food security", "commodit",
    "oil price", "oil output", "oil production", "oil embargo",
    "oil export", "oil import", "oil sanction",
    # Shipping & logistics
    "shipping", "maritime", "freight", "red sea", "suez",
    "strait of hormuz", "blockade", "dry bulk", "tanker rate",
    "container rate", "reroute",
    # Central banks & monetary policy
    "central bank", "federal reserve", "interest rate", "rate hike",
    "rate cut", "inflation", "deflation", "monetary policy",
    "ecb", "boj", "pboc", "imf", "world bank",
    "quantitative", "stimulus",
    # Fiscal & regulation
    "fiscal", "spending", "debt ceiling", "sovereign debt",
    "regulat", "antitrust", "deregulat",
    # Markets & finance
    "investor", "treasury", "recession",
    "equit", "stock market", "stock index",
    "currency", "crypto", "bitcoin",
    # Sectors
    "semiconductor", "tech sector", "pharma", "biotech",
    "aerospace", "auto industry", "automotive",
    # Semiconductors — supply chain specifics
    "foundry", "lithograph", "euv", "wafer", "fabricat",
    "hbm", "dram", "nand",
    # Defense — procurement & industrial
    "munition", "rearm", "fighter jet", "warship", "howitzer",
    "defense contract", "defence contract",
    # Key actors (catch headlines that name actors without other keywords)
    "white house", "kremlin", "brussels",
    "pentagon", "congress",
    # Key sector companies as substring (catches "Lockheed Martin", "ASML" etc.)
    "lockheed", "raytheon", "northrop", "rheinmetall",
    "asml", "tsmc",
    "maersk", "frontline",
}

# Short words that need word-boundary matching (\b...\b) to avoid false
# positives.  Each entry is compiled into a regex pattern at import time.
_WORD_BOUNDARY_KW: set[str] = {
    "oil", "gas", "coal", "fuel", "energy", "petrol", "diesel",
    "metal", "mineral",
    "port", "ports",
    "import", "imports",
    "chip", "chips",
    "bond", "bonds", "yield", "yields",
    "gdp", "budget",
    "market", "markets",
    "dollar", "euro", "yuan", "yen",
    "index",
    "beijing", "parliament",
}

_WB_PATTERN: _re.Pattern[str] = _re.compile(
    r"\b(?:" + "|".join(_re.escape(kw) for kw in _WORD_BOUNDARY_KW) + r")\b",
    _re.IGNORECASE,
)

# Keywords that pass the allowlist BUT only count as relevant when the headline
# also has a concrete economic/policy channel.  Without one, a "war" headline
# is just general conflict reporting (politics, casualties, opinion polls).
_NEEDS_ECONOMIC_CONTEXT: set[str] = {"war", "wars", "conflict"}

_NEC_PATTERN: _re.Pattern[str] = _re.compile(
    r"\b(?:" + "|".join(_re.escape(kw) for kw in _NEEDS_ECONOMIC_CONTEXT) + r")\b",
    _re.IGNORECASE,
)

# Economic context keywords that rescue a war/conflict headline.
_ECON_CONTEXT_KW: set[str] = {
    "oil", "gas", "fuel", "energy", "crude", "opec", "lng", "pipeline",
    "refiner", "commodit", "price", "prices", "cost", "costs",
    "trade", "tariff", "sanction", "embargo", "export", "import",
    "shipping", "freight", "blockade", "port", "ports", "supply chain",
    "inflation", "gdp", "recession", "interest rate", "central bank",
    "mortgage", "currency", "dollar", "euro", "yuan", "yen",
    "bond", "bonds", "yield", "treasury", "equit", "stock", "shares",
    "budget", "spending", "fiscal", "subsid", "regulat",
    "semiconductor", "chip", "chips", "foundry", "wafer", "fab",
    "defense spend", "defence spend", "munition", "rearm", "arms deal",
    "tanker", "dry bulk", "container", "reroute",
    "food", "wheat", "grain", "fertiliser", "fertilizer",
    "jobs", "employment", "unemployment", "growth", "economic",
    "business", "firms", "companies", "corporate",
    "petrol", "diesel",
}

# ---------------------------------------------------------------------------
# Rejection patterns — human-interest, casualty-only, symbolic/social
# ---------------------------------------------------------------------------
# If a headline matches one of these and has NO strong economic keyword beyond
# the ambiguous ones, it is rejected even if an allowlist keyword matched.

_REJECT_PATTERNS: list[_re.Pattern[str]] = [
    # Human-interest cost-of-living / personal hardship
    _re.compile(r"\b(couple|family|families|pensioner|elderly|resident)\b.*"
                r"\b(pay|paid|find|afford|cost|bill|heating|rent)\b", _re.I),
    # Casualty-only war reporting (killed/dead/wounded + no economic channel)
    _re.compile(r"\b(\d+\s+)?(killed|dead|die|dies|died|wounded|injured|"
                r"casualties|massacre|slain|bodies)\b", _re.I),
    # Religious, ceremonial, symbolic events
    _re.compile(r"\b(pope|pontiff|cardinal|bishop|sermon|prayer|prayers|"
                r"pilgrimage|liturgy|good friday|easter|christmas mass|"
                r"funeral service|vigil)\b", _re.I),
    # Purely social / human-rights framing with no policy mechanism
    _re.compile(r"\b(deported children|orphan|refugee camp|"
                r"missing persons?|stranded tourists?)\b", _re.I),
    # Human-interest war hardship (migrant workers, deadly risk, etc.)
    _re.compile(r"\bmigrant workers?\b.*\b(deadly|risk|danger|flee|stranded)\b", _re.I),
    # Prediction/betting markets — not financial markets
    _re.compile(r"\b(prediction market|betting market|gambling|wager)\b", _re.I),
]

# If a rejected headline also contains one of these, it survives because
# there is a concrete economic/policy transmission channel.
_ECONOMIC_CHANNEL_KW: set[str] = {
    "sanction", "embargo", "tariff", "trade", "export", "import",
    "pipeline", "crude", "opec", "lng", "refiner", "energy price",
    "oil price", "oil production", "oil output", "commodit",
    "shipping", "freight", "port closure", "blockade", "supply chain",
    "central bank", "interest rate", "inflation", "gdp", "fiscal",
    "subsid", "regulat", "infrastructure", "reconstruct",
    "defense spend", "defence spend", "military budget",
    "arms deal", "weapons contract", "semiconductor",
    "chip", "chips", "foundry", "wafer", "fab",
}


def is_relevant(title: str) -> bool:
    """Return True if the headline has an economic/policy transmission path.

    Four-stage filter:
    1. Check substring keywords (safe, unambiguous stems).
    2. Check word-boundary keywords (short words needing exact match).
    3. If the ONLY match is a context-dependent keyword (war, conflict),
       require a co-occurring economic channel word.
    4. Apply rejection patterns — if matched, require an economic channel
       keyword to survive.
    """
    low = title.lower()

    # Stage 1: check reject patterns first — these override everything.
    for pat in _REJECT_PATTERNS:
        if pat.search(title):
            if any(ch in low for ch in _ECONOMIC_CHANNEL_KW):
                return True
            return False

    # Stage 2: does the headline match any allowlist keyword?
    has_substr = any(kw in low for kw in RELEVANCE_KEYWORDS)
    has_wb = bool(_WB_PATTERN.search(low))

    if not has_substr and not has_wb:
        # Stage 3: check context-dependent keywords (war, conflict).
        # These only count if an economic context word is also present.
        if _NEC_PATTERN.search(low):
            return any(ek in low for ek in _ECON_CONTEXT_KW)
        return False

    return True


def fetch_all(local_path: str = LOCAL_FILE,
              feeds: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    """Load from all sources, merge, and deduplicate.

    Dedup removes same-source repeats (e.g. an RSS feed returning the same
    headline twice) but preserves identical titles from *different* sources
    so that clustering can count them as corroborating coverage.

    Returns
    -------
    (records, feed_status)
        records    : newest-first list of headline dicts.
        feed_status: per-feed status dicts from load_rss().
    """
    rss_records, feed_status = load_rss(feeds)

    # Log per-feed headline counts — every feed, not just successes
    for fs in feed_status:
        if fs.get("error") and fs["headlines"] == 0:
            _log.warning("[feed] %-30s  FAIL: %s", fs["name"], fs.get("error", "unknown"))
        elif fs["headlines"] == 0:
            _log.warning("[feed] %-30s  0 headlines", fs["name"])
        else:
            _log.info("[feed] %-30s  %3d headlines", fs["name"], fs["headlines"])

    all_records = load_local(local_path) + rss_records

    # Deduplicate by (source, normalized title) — same source + same title
    # is a true duplicate; different source + same title is corroboration.
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for rec in all_records:
        key = (rec["source"], _dedup_key(rec["title"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(rec)

    # Drop headlines that don't match any domain keyword
    relevant = [rec for rec in unique if is_relevant(rec["title"])]

    _log.info("[refresh] %d raw → %d unique → %d relevant", len(all_records), len(unique), len(relevant))

    # Sort newest-first; records without a timestamp go to the end
    relevant.sort(key=lambda r: r["published_at"] or "", reverse=True)
    return relevant, feed_status


# ---------------------------------------------------------------------------
# Headline clustering
# ---------------------------------------------------------------------------
# Groups near-duplicate headlines from different publishers into a single
# "event cluster" with one representative headline and a ranked source list.
# Uses TF-IDF cosine similarity — rare/distinctive words matter more than
# common ones, catching cross-source rewording that pure word-overlap misses.

import math as _math
import logging as _logging

_cluster_log = _logging.getLogger("second_order.cluster")

import re as _re_mod

_STOP_WORDS: set[str] = {
    # English function words
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or",
    "is", "are", "was", "were", "by", "with", "from", "as", "its", "it",
    "that", "this", "be", "has", "have", "had", "not", "but", "will",
    "would", "could", "should", "may", "might", "after", "before", "over",
    "new", "says", "said", "about", "into", "up", "out", "more", "than",
    # Financial/news domain words — high frequency, low discriminating power.
    "market", "markets", "stock", "stocks", "shares", "index",
    "price", "prices", "trading", "traders",
    "global", "economy", "economic",
    "billion", "million", "trillion",
    "report", "reports", "reporting",
    "investors", "investor", "analysts", "analyst",
}

_PUNCT_RE = _re_mod.compile(r"^[^\w]+|[^\w]+$")

# ---------------------------------------------------------------------------
# Polarity words — used to prevent clustering of opposite-direction headlines.
# "Stock markets rally after Fed decision" must NOT cluster with
# "Stock markets fall after Fed decision" even though cosine is very high.
# ---------------------------------------------------------------------------
_POLARITY_POS: frozenset[str] = frozenset({
    "surge", "surges", "soar", "soars", "rally", "rallies",
    "rise", "rises", "jump", "jumps", "gain", "gains",
    "boost", "climb", "climbs", "rebound", "rebounds",
    "strengthen", "strengthens", "recovery",
})
_POLARITY_NEG: frozenset[str] = frozenset({
    "drop", "drops", "fall", "falls", "crash", "crashes",
    "plunge", "plunges", "decline", "declines",
    "slump", "slumps", "sink", "sinks",
    "tumble", "tumbles", "weaken", "weakens",
    "selloff", "sell-off", "collapse",
})


def _headline_polarity(tokens: list[str] | set[str]) -> int:
    """Return +1 for positive, -1 for negative, 0 for neutral/mixed.

    Only fires when the headline has a clear single-direction signal.
    If both positive and negative words appear, returns 0 (ambiguous).
    """
    has_pos = any(t in _POLARITY_POS for t in tokens)
    has_neg = any(t in _POLARITY_NEG for t in tokens)
    if has_pos and not has_neg:
        return 1
    if has_neg and not has_pos:
        return -1
    return 0


# Cosine similarity threshold for merging into the same cluster.
# TF-IDF cosine on short (5-10 word) headlines runs lower than Jaccard
# because IDF penalises common cross-headline terms.  Calibrated on
# live feeds 2026-04: 0.20 catches cross-source rewording (e.g.
# "fuel prices surge Iran war" ↔ "oil highest price Iran war") while
# keeping unrelated stories apart (cosine ≈ 0 when no content overlap).
_CLUSTER_THRESHOLD: float = 0.20

# If any pair inside a cluster falls below this, flag agreement as "mixed".
_AGREEMENT_THRESHOLD: float = 0.12


def _headline_words(title: str) -> set[str]:
    """Extract content words from a headline for similarity comparison."""
    words: set[str] = set()
    for raw in title.lower().split():
        cleaned = _PUNCT_RE.sub("", raw)
        if cleaned and cleaned not in _STOP_WORDS:
            words.add(cleaned)
    return words


def _tokenize(title: str) -> list[str]:
    """Split a headline into lowercase, punctuation-stripped content tokens."""
    tokens: list[str] = []
    for raw in title.lower().split():
        cleaned = _PUNCT_RE.sub("", raw)
        if cleaned and cleaned not in _STOP_WORDS:
            tokens.append(cleaned)
    return tokens


def _build_tfidf_vectors(titles: list[str]) -> tuple[list[dict[str, float]], dict[str, float]]:
    """Build TF-IDF vectors for a list of titles.

    Returns (vectors, idf_map) where each vector is a dict mapping
    token → TF-IDF weight.  Uses log-IDF with add-one smoothing.
    """
    n = len(titles)
    token_lists = [_tokenize(t) for t in titles]

    # Document frequency: how many titles contain each token
    df: dict[str, int] = {}
    for tokens in token_lists:
        for w in set(tokens):
            df[w] = df.get(w, 0) + 1

    # IDF with add-one smoothing: log((n + 1) / (df + 1)) + 1
    idf: dict[str, float] = {}
    for w, count in df.items():
        idf[w] = _math.log((n + 1) / (count + 1)) + 1.0

    # TF-IDF vectors
    vectors: list[dict[str, float]] = []
    for tokens in token_lists:
        tf: dict[str, int] = {}
        for w in tokens:
            tf[w] = tf.get(w, 0) + 1
        vec = {w: tf[w] * idf.get(w, 1.0) for w in tf}
        vectors.append(vec)

    return vectors, idf


def _cosine_sim(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity between two sparse TF-IDF vectors."""
    if not a or not b:
        return 0.0
    # Dot product over shared keys
    shared = set(a) & set(b)
    if not shared:
        return 0.0
    dot = sum(a[k] * b[k] for k in shared)
    norm_a = _math.sqrt(sum(v * v for v in a.values()))
    norm_b = _math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard index between two word sets.  Kept for agreement checking."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------------------
# Structured consensus extraction
# ---------------------------------------------------------------------------
# Deterministic keyword-based extraction of actors, action, geography,
# sector, and uncertainty from the combined headline text of a cluster.
# No NLP deps — just curated lookup dicts.

# Longest keys checked first so "south korea" matches before "korea".
_ACTOR_KEYWORDS: dict[str, str] = {
    "united states": "United States", "u.s.": "United States",
    "white house": "United States",
    "us": "United States", "american": "United States",
    "european union": "European Union", "brussels": "European Union",
    "eu": "European Union",
    "china": "China", "chinese": "China", "beijing": "China",
    "russia": "Russia", "russian": "Russia", "moscow": "Russia",
    "kremlin": "Russia",
    "united kingdom": "United Kingdom", "britain": "United Kingdom",
    "british": "United Kingdom", "uk": "United Kingdom",
    "japan": "Japan", "japanese": "Japan", "tokyo": "Japan",
    "saudi arabia": "Saudi Arabia", "saudi": "Saudi Arabia",
    "riyadh": "Saudi Arabia",
    "iran": "Iran", "iranian": "Iran", "tehran": "Iran",
    "india": "India", "indian": "India",
    "germany": "Germany", "german": "Germany", "berlin": "Germany",
    "france": "France", "french": "France",
    "ukraine": "Ukraine", "ukrainian": "Ukraine", "kyiv": "Ukraine",
    "taiwan": "Taiwan", "taiwanese": "Taiwan",
    "south korea": "South Korea", "seoul": "South Korea",
    "north korea": "North Korea", "pyongyang": "North Korea",
    "israel": "Israel", "israeli": "Israel",
    "turkey": "Turkey", "turkish": "Turkey", "ankara": "Turkey",
    "houthis": "Houthis", "houthi": "Houthis",
    "nato": "NATO", "opec": "OPEC",
    "federal reserve": "Federal Reserve", "fed": "Federal Reserve",
    "ecb": "ECB", "imf": "IMF",
    "chevron": "Chevron", "boeing": "Boeing", "tsmc": "TSMC",
    "asml": "ASML", "nvidia": "NVIDIA", "intel": "Intel",
    "samsung": "Samsung", "sk hynix": "SK Hynix",
    "lockheed": "Lockheed Martin", "raytheon": "Raytheon",
    "northrop": "Northrop Grumman", "general dynamics": "General Dynamics",
    "rheinmetall": "Rheinmetall", "bae systems": "BAE Systems",
    "maersk": "Maersk", "frontline": "Frontline",
}

# Ordered by specificity — first match wins.
_ACTION_KEYWORDS: list[tuple[list[str], str]] = [
    (["tariff", "tariffs", "duties", "duty"],            "tariffs"),
    (["sanction", "sanctions", "embargo"],                "sanctions"),
    (["restrict", "restriction", "bans", "ban"],          "export restrictions"),
    (["production cut", "output cut"],                    "production cut"),
    (["ceasefire", "truce", "peace talks"],               "de-escalation"),
    (["attack", "strikes", "bombing", "missile", "war"],  "military action"),
    (["spending", "budget", "stimulus", "package"],       "fiscal policy"),
    (["rate cut", "rate hike", "interest rate", "inflation"], "monetary policy"),
    (["defence", "defense", "rearm"],                     "defense spending"),
    (["agreement", "deal", "pact", "treaty", "licence"],  "agreement"),
    (["export", "import", "trade"],                       "trade policy"),
]

_SECTOR_KEYWORDS: dict[str, str] = {
    # Critical minerals
    "rare earth": "critical minerals", "mineral": "critical minerals",
    "lithium": "critical minerals", "cobalt": "critical minerals",
    # Semiconductors
    "semiconductor": "semiconductors", "chip": "semiconductors",
    "foundry": "semiconductors", "lithography": "semiconductors",
    "wafer": "semiconductors", "fab": "semiconductors",
    "euv": "semiconductors", "dram": "semiconductors", "nand": "semiconductors",
    "hbm": "semiconductors",
    # Energy
    "oil": "energy", "crude": "energy", "petroleum": "energy",
    "opec": "energy", "gas": "energy", "lng": "energy",
    "refiner": "energy", "pipeline": "energy",
    # Metals
    "steel": "metals", "aluminium": "metals", "aluminum": "metals",
    "copper": "metals", "metal": "metals",
    # Defense
    "defence": "defense", "defense": "defense",
    "weapon": "defense", "arms": "defense", "munition": "defense",
    "rearm": "defense", "missile defense": "defense",
    # Shipping & logistics
    "shipping": "shipping", "maritime": "shipping",
    "freight": "shipping", "red sea": "shipping",
    "tanker": "shipping", "dry bulk": "shipping", "container": "shipping",
    "suez": "shipping", "strait of hormuz": "shipping",
    # Agriculture
    "wheat": "agriculture", "grain": "agriculture", "food": "agriculture",
    # Finance
    "treasury": "finance", "bank": "finance",
}

_ACTOR_REGION: dict[str, str] = {
    "United States": "North America",
    "European Union": "Europe", "Germany": "Europe", "France": "Europe",
    "United Kingdom": "Europe",
    "China": "East Asia", "Japan": "East Asia", "Taiwan": "East Asia",
    "South Korea": "East Asia", "North Korea": "East Asia", "TSMC": "East Asia",
    "Russia": "Eurasia", "Ukraine": "Eurasia",
    "Saudi Arabia": "Middle East", "Iran": "Middle East",
    "Israel": "Middle East", "Houthis": "Middle East", "Turkey": "Middle East",
    "India": "South Asia",
}


def _scan_keywords(text: str, keyword_map: dict[str, str]) -> list[str]:
    """Find all keyword matches in text; return unique canonical values.

    Checks longest keywords first so 'south korea' matches before 'korea'.
    Short pure-alpha keywords (e.g. 'us', 'eu') use word-boundary matching
    to avoid false positives like 'discuss' or 'reuters'.
    """
    text_lower = text.lower()
    seen: set[str] = set()
    found: list[str] = []
    for kw in sorted(keyword_map, key=len, reverse=True):
        canonical = keyword_map[kw]
        if canonical in seen:
            continue
        # Short alphabetic keywords need word-boundary matching to avoid
        # false positives (e.g. "us" inside "discuss", "eu" inside "reuters").
        if kw.isalpha() and len(kw) <= 3:
            if not re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
                continue
        else:
            if kw not in text_lower:
                continue
        seen.add(canonical)
        found.append(canonical)
    return found


def _scan_action(text: str) -> str:
    """Return the most specific action keyword match, or 'unknown'."""
    text_lower = text.lower()
    for keywords, label in _ACTION_KEYWORDS:
        if any(kw in text_lower for kw in keywords):
            return label
    return "unknown"


def extract_consensus(headline: str, all_titles: list[str],
                      sources: list[dict], agreement: str) -> dict:
    """Extract structured consensus fields from a headline cluster.

    Parameters
    ----------
    headline    : best headline (from highest-tier source)
    all_titles  : list of every headline in the cluster
    sources     : tier-sorted source list from cluster_headlines()
    agreement   : "consistent" or "mixed"

    Returns
    -------
    dict with keys: actors, action, geography, sector, uncertainty, consensus
    """
    # Combine all titles for broader keyword coverage
    combined = " ".join(all_titles)

    actors = _scan_keywords(combined, _ACTOR_KEYWORDS)
    action = _scan_action(combined)
    sector = _scan_keywords(combined, _SECTOR_KEYWORDS)

    # Derive geography from detected actors
    regions: list[str] = []
    seen_regions: set[str] = set()
    for actor in actors:
        region = _ACTOR_REGION.get(actor)
        if region and region not in seen_regions:
            seen_regions.add(region)
            regions.append(region)

    # Uncertainty: based on source quality, count, and agreement
    high_count = sum(1 for s in sources if s["tier"] == "high")
    if agreement == "mixed":
        uncertainty = "high"
    elif high_count >= 2:
        uncertainty = "low"
    elif high_count >= 1 or len(sources) >= 2:
        uncertainty = "medium"
    else:
        uncertainty = "high"

    return {
        "actors":       actors,
        "action":       action,
        "geography":    regions,
        "sector":       sector[0] if sector else "unknown",
        "uncertainty":  uncertainty,
        "consensus":    "consensus" if agreement == "consistent" else "mixed",
    }


def _build_summary(best_headline: str, best_source: str,
                    records: list[dict], sources: list[dict],
                    agreement: str) -> str:
    """Build a short merged summary for a headline cluster.

    Rules:
    - Single-source clusters get a one-liner.
    - Multi-source consistent clusters note corroboration.
    - Multi-source mixed clusters surface the most-different headline so the
      reader can see what the disagreement actually is.
    - The best (highest-tier) headline always leads; lower-tier sources are
      referenced by name but don't override the framing.
    """
    source_names = [s["name"] for s in sources]

    if len(records) == 1:
        tier = sources[0]["tier"] if sources else "low"
        label = {"high": "major outlet", "medium": "regional outlet",
                 "low": "single source"}[tier]
        return f"{best_headline} ({label}: {source_names[0]})."

    # Multi-source — list everyone except the lead source
    others = [n for n in source_names if n != best_source]
    others_str = ", ".join(others)

    if agreement == "consistent":
        return (
            f"{best_headline}. "
            f"Corroborated by {others_str}."
        )

    # Mixed agreement — find the most-different headline and surface it
    best_words = _headline_words(best_headline)
    most_different = None
    lowest_sim = 1.0
    for rec in records:
        if rec["title"] == best_headline:
            continue
        sim = _jaccard(best_words, _headline_words(rec["title"]))
        if sim < lowest_sim:
            lowest_sim = sim
            most_different = rec

    if most_different:
        return (
            f"{best_headline} (via {best_source}). "
            f"Also covered by {others_str}, but framing differs — "
            f"{most_different['source']} reports: "
            f"\"{most_different['title']}\"."
        )
    # Fallback: shouldn't happen, but safe
    return f"{best_headline}. Covered by {', '.join(source_names)}."


def _build_evidence(recs: list[dict], best_title: str,
                     agreement: str) -> list[dict]:
    """Return top 2-3 source evidence items, ranked by tier then recency.

    Each item: {"source", "tier", "title", "published_at", "note"}
    When agreement is "mixed", the most divergent headline gets a note.
    """
    best_words = _headline_words(best_title)

    # Sort: best tier first, then newest first within same tier.
    # Stable-sort trick: sort by recency desc, then stable-sort by tier asc.
    by_recency = sorted(recs, key=lambda r: r["published_at"] or "", reverse=True)
    ranked = sorted(by_recency, key=lambda r: _TIER_RANK.get(source_tier(r["source"]), 2))

    # Deduplicate by source name — keep first (best per source)
    seen: set[str] = set()
    unique: list[dict] = []
    for r in ranked:
        if r["source"] not in seen:
            seen.add(r["source"])
            unique.append(r)

    # Find the most divergent headline when mixed
    divergent_title: str | None = None
    if agreement == "mixed" and len(unique) > 1:
        lowest_sim = 1.0
        for r in unique[1:]:
            sim = _jaccard(best_words, _headline_words(r["title"]))
            if sim < lowest_sim:
                lowest_sim = sim
                divergent_title = r["title"]

    evidence: list[dict] = []
    for r in unique[:3]:
        note = ""
        if divergent_title and r["title"] == divergent_title:
            note = "framing differs"
        evidence.append({
            "source":       r["source"],
            "tier":         source_tier(r["source"]),
            "title":        r["title"],
            "published_at": r["published_at"],
            "note":         note,
        })

    return evidence


def cluster_headlines(records: list[dict]) -> list[dict]:
    """Group near-duplicate headlines into event clusters.

    Uses TF-IDF cosine similarity with union-find so that clustering is
    order-independent and transitive: if A≈B and B≈C, all three end up in
    one cluster regardless of input order.

    Parameters
    ----------
    records : list[dict]
        Output of fetch_all() — already deduped for exact matches.

    Returns
    -------
    list[dict]
        Newest-first list of clusters, each shaped:
        {
            "headline":     str,          # from the highest-tier source
            "summary":      str,          # merged 2-4 sentence summary
            "consensus":    dict,         # structured extraction (actors, action, …)
            "sources":      list[dict],   # [{"name", "tier", "url"}, ...], best first
            "published_at": str,          # most recent timestamp in cluster
            "source_count": int,
            "agreement":    "consistent" | "mixed",
        }
    """
    n = len(records)
    if n == 0:
        return []

    # -- Union-find for order-independent, transitive clustering --
    parent = list(range(n))

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]   # path compression
            x = parent[x]
        return x

    def _union(a: int, b: int) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[rb] = ra

    # Build TF-IDF vectors for cosine similarity
    titles = [rec["title"] for rec in records]
    tfidf_vecs, _ = _build_tfidf_vectors(titles)
    token_lists = [_tokenize(t) for t in titles]
    polarities = [_headline_polarity(toks) for toks in token_lists]

    for i in range(n):
        for j in range(i + 1, n):
            sim = _cosine_sim(tfidf_vecs[i], tfidf_vecs[j])
            if sim >= _CLUSTER_THRESHOLD:
                # Block merge if both headlines have clear but opposite polarity.
                # E.g. "Oil prices surge" vs "Oil prices drop" — high cosine
                # because they share subject words, but are different events.
                pi, pj = polarities[i], polarities[j]
                if pi != 0 and pj != 0 and pi != pj:
                    _cluster_log.info(
                        "BLOCK cos=%.3f polarity=%+d/%+d\n  A: %s\n  B: %s",
                        sim, pi, pj, titles[i], titles[j],
                    )
                    continue
                _cluster_log.info(
                    "MERGE cos=%.3f\n  A: %s\n  B: %s",
                    sim, titles[i], titles[j],
                )
                _union(i, j)

    # Group record indices by their root
    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = _find(i)
        groups.setdefault(root, []).append(i)

    clusters = [{"records": [records[i] for i in idxs]} for idxs in groups.values()]

    # Convert internal clusters to the output shape
    result: list[dict] = []
    for cluster in clusters:
        recs = cluster["records"]

        # -- Sources: deduplicate by name, sort by tier then alphabetical --
        seen_names: set[str] = set()
        sources: list[dict] = []
        for r in recs:
            name = r["source"]
            if name in seen_names:
                continue
            seen_names.add(name)
            sources.append({
                "name": name,
                "tier": source_tier(name),
                "url":  r.get("url", ""),
            })
        sources.sort(key=lambda s: (_TIER_RANK.get(s["tier"], 2), s["name"]))

        # -- Headline: pick from highest-tier source; break ties with longest --
        best_rec = min(recs, key=lambda r: (
            _TIER_RANK.get(source_tier(r["source"]), 2),
            -len(r["title"]),
        ))

        # -- Timestamp: most recent in cluster --
        pub_dates = [r["published_at"] for r in recs if r["published_at"]]
        published_at = max(pub_dates) if pub_dates else ""

        # -- Agreement: check all pairs within cluster via cosine --
        agreement = "consistent"
        if len(recs) > 1:
            cluster_titles = [r["title"] for r in recs]
            cluster_vecs, _ = _build_tfidf_vectors(cluster_titles)
            for i in range(len(cluster_vecs)):
                for j in range(i + 1, len(cluster_vecs)):
                    if _cosine_sim(cluster_vecs[i], cluster_vecs[j]) < _AGREEMENT_THRESHOLD:
                        agreement = "mixed"
                        break
                if agreement == "mixed":
                    break

        summary = _build_summary(
            best_rec["title"], best_rec["source"],
            recs, sources, agreement,
        )

        all_titles = [r["title"] for r in recs]
        consensus = extract_consensus(
            best_rec["title"], all_titles, sources, agreement,
        )

        evidence = _build_evidence(recs, best_rec["title"], agreement)

        result.append({
            "headline":     best_rec["title"],
            "summary":      summary,
            "consensus":    consensus,
            "sources":      sources,
            "published_at": published_at,
            "source_count": len(sources),
            "agreement":    agreement,
            "evidence":     evidence,
        })

    # Sort: multi-source clusters rank above single-source, then newest first
    # within the same source count. Python's sort is stable so the two-pass
    # approach preserves recency order within each source-count group.
    result.sort(key=lambda c: c["published_at"] or "", reverse=True)
    result.sort(key=lambda c: c["source_count"], reverse=True)

    multi = [c for c in result if c["source_count"] >= 2]
    triple = [c for c in result if c["source_count"] >= 3]
    _cluster_log.info(
        "[cluster] %d records → %d clusters (%d multi-source, %d with 3+ sources)",
        n, len(result), len(multi), len(triple),
    )
    for c in triple:
        srcs = ", ".join(s["name"] for s in c["sources"])
        _cluster_log.info(
            "[cluster] 3+ sources: %r  ← %s", c["headline"][:70], srcs,
        )

    return result
