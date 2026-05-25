# news_sources.py
# Loads headlines from local JSON and RSS feeds, normalizes them to a common
# shape, and deduplicates obvious repeats.
#
# Each headline record looks like:
#   {"source": str, "title": str, "published_at": str, "url": str}
#
# No database writes happen here — this module just collects and returns.

import hashlib
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
    # Expanded coverage
    "Mining.com":             "medium",
    "Freight & Shipping":     "medium",
    "Economic Times":         "medium",
    "LatAm Economy":          "medium",
    "IMF News":               "high",
    "World Bank":             "high",
    "Semiconductor Trade":    "medium",
    "Africa Economy":         "medium",
    "local":                  "low",
}

_TIER_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}


def source_tier(name: str) -> str:
    """Return the reliability tier for a named source."""
    return _SOURCE_TIERS.get(name, "low")


_SOURCE_ALIASES: dict[str, str] = {
    "BBC Business": "BBC", "BBC World": "BBC",
    "The Guardian Business": "The Guardian", "The Guardian World": "The Guardian",
    "Al Jazeera Economy": "Al Jazeera",
}


def normalize_source(name: str) -> str:
    """Return the canonical publisher name for dedup/counting purposes."""
    return _SOURCE_ALIASES.get(name, name)


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


_PREFIX_RE = re.compile(
    r"^(?:"
    r"Breaking|Update|Exclusive|Watch|Analysis|Opinion|Live"
    r"|Reuters|AP News|Associated Press|AFP|Bloomberg"
    r"|BBC[\w\s]*|The Guardian[\w\s]*|NPR[\w\s]*|CNN[\w\s]*"
    r"|Financial Times|FT|WSJ|The Wall Street Journal"
    r"|CNBC[\w\s]*|MarketWatch[\w\s]*|Yahoo Finance[\w\s]*"
    r"|Al Jazeera[\w\s]*|Nikkei[\w\s]*|Defense News[\w\s]*"
    r")\s*[:\-\u2013\u2014]\s*",
    re.IGNORECASE,
)


def normalize_headline(title: str) -> str:
    """Strip common prefixes and trailing source attributions from a headline."""
    t = _PREFIX_RE.sub("", title.strip(), count=1)
    return _strip_attribution(t).strip()


def _candidate_id(source: str, title: str, published_at: str, url: str) -> str:
    """Deterministic candidate_id derived from (source, title, published_at, url).

    The id is stable across runs given the same logical row, and stable
    under cosmetic variants the normalizers already collapse: source
    aliases (``normalize_source``) and prefix/attribution noise on the
    headline (``normalize_headline``).  It lets the daily artifact gate
    look up ``analyzed_event_artifact_<candidate_id>.json`` by id rather
    than by headline string.

    Returned as the first 16 hex characters of a SHA-256 digest — 64
    bits of entropy, comfortable headroom for any plausible inbox
    population.
    """
    parts = (
        normalize_source(source or ""),
        normalize_headline(title or ""),
        (published_at or "").strip(),
        (url or "").strip(),
    )
    joined = "\x1f".join(parts)  # ASCII unit-separator never appears in feed content
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def _make_record(source: str, title: str, published_at: str, url: str = "") -> dict:
    """Build one normalized headline record."""
    norm_title = normalize_headline(title)
    norm_pub = _normalize_timestamp(published_at)
    norm_url = url.strip()
    return {
        "source":       source,
        "title":        norm_title,
        "published_at": norm_pub,
        "url":          norm_url,
        "candidate_id": _candidate_id(source, title, norm_pub, norm_url),
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
# 35 feeds across wire services, geopolitical, financial, energy/commodities,
# central bank, defense, Asia/emerging-market, metals/mining, shipping/freight,
# South Asia, LatAm, Africa, multilateral institutions, and tech/supply-chain.
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
    # --- Commodities / Metals / Shipping ---
    {
        "name": "Mining.com",
        "url":  "https://www.mining.com/feed/",
    },
    {
        "name": "Freight & Shipping",
        "url":  "https://news.google.com/rss/search?q=%22Baltic+dry%22+OR+%22shipping+rates%22+OR+%22freight+rates%22+OR+%22container+shipping%22&hl=en&gl=US&ceid=US:en",
    },
    # --- Emerging Markets / South Asia ---
    {
        "name": "Economic Times",
        "url":  "https://economictimes.indiatimes.com/rssfeedstopstories.cms",
    },
    {
        "name": "LatAm Economy",
        "url":  "https://news.google.com/rss/search?q=site:reuters.com+%22Latin+America%22+OR+Brazil+OR+Mexico+economy+OR+%22central+bank%22&hl=en&gl=US&ceid=US:en",
    },
    {
        "name": "Africa Economy",
        "url":  "https://news.google.com/rss/search?q=Africa+economy+OR+%22sub-Saharan%22+OR+%22African+Union%22+trade+OR+%22African+Development+Bank%22&hl=en&gl=US&ceid=US:en",
    },
    # --- Multilateral / Policy ---
    {
        "name": "IMF News",
        "url":  "https://www.imf.org/en/News/rss?language=eng",
    },
    {
        "name": "World Bank",
        "url":  "https://news.google.com/rss/search?q=site:worldbank.org+economy+OR+%22developing+markets%22+OR+%22emerging+markets%22&hl=en&gl=US&ceid=US:en",
    },
    # --- Tech / Supply Chain ---
    {
        "name": "Semiconductor Trade",
        "url":  "https://news.google.com/rss/search?q=semiconductor+chips+%22export+controls%22+OR+%22chip+ban%22+OR+%22supply+chain%22+trade&hl=en&gl=US&ceid=US:en",
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
        from feed_registry import get_active_feeds
        feeds = get_active_feeds()

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
    # normalize_headline() is applied before hashing so that source-prefixed
    # variants ("Reuters: X" vs "X" from the same feed) collapse to one key.
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for rec in all_records:
        key = (normalize_source(rec["source"]), _dedup_key(normalize_headline(rec["title"])))
        if key in seen:
            continue
        seen.add(key)
        unique.append(rec)

    # Drop headlines that don't match any domain keyword
    from news_relevance import is_relevant
    relevant = [rec for rec in unique if is_relevant(rec["title"])]

    _log.info("[refresh] %d raw → %d unique → %d relevant", len(all_records), len(unique), len(relevant))

    # Sort newest-first; records without a timestamp go to the end
    relevant.sort(key=lambda r: r["published_at"] or "", reverse=True)
    return relevant, feed_status


# ---------------------------------------------------------------------------