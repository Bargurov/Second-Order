# news_sources.py
# Loads headlines from local JSON and RSS feeds, normalizes them to a common
# shape, and deduplicates obvious repeats.
#
# Each headline record looks like:
#   {"source": str, "title": str, "published_at": str, "url": str}
#
# No database writes happen here — this module just collects and returns.

import json
import os
import re
import socket
from datetime import datetime
from email.utils import parsedate_to_datetime

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
    "BBC Business":          "high",
    "BBC World":             "high",
    "Reuters World":         "high",
    "The Guardian Business":  "high",
    "The Guardian World":     "high",
    "WSJ World News":         "high",
    "Al Jazeera Economy":     "medium",
    "Al Jazeera":             "medium",
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


def _make_record(source: str, title: str, published_at: str, url: str = "") -> dict:
    """Build one normalized headline record."""
    return {
        "source":       source,
        "title":        title.strip(),
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

# Curated feeds — narrowed to business / world / politics / policy sections
# to reduce general-news noise (sports, entertainment, lifestyle, etc.).
#
# Feed selection notes:
#   - Reuters World via Google News RSS proxy — Reuters shut down their own
#     public feeds, but Google News exposes a topic-filtered Atom feed that
#     reliably surfaces Reuters world/business content.
#   - The Guardian uses /business/rss (not /world/rss) for better trade/macro.
#   - BBC uses /news/business to avoid lifestyle and sports stories.
#   - WSJ World News: financial + geopolitical, naturally filtered.
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

    records = []
    feed_status: list[dict] = []

    for feed_info in feeds:
        feed_name = feed_info["name"]
        # Apply a per-feed timeout using the stdlib socket default.
        # feedparser uses urllib internally, which respects this timeout,
        # so a slow or hanging feed is cut off after _FEED_TIMEOUT seconds.
        _prev_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(_FEED_TIMEOUT)
            parsed = feedparser.parse(feed_info["url"])
        except Exception:
            feed_status.append({"name": feed_name, "ok": False, "headlines": 0})
            continue
        finally:
            socket.setdefaulttimeout(_prev_timeout)

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
        feed_status.append({
            "name":      feed_name,
            "ok":        added > 0,
            "headlines": added,
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
# clustering.  Easy to tune: just add or remove words from the set.

RELEVANCE_KEYWORDS: set[str] = {
    # Geopolitics & conflict
    "geopolit", "sanction", "embargo", "tariff", "duties", "treaty",
    "ceasefire", "truce", "diplomacy", "diplomatic", "nato", "sovereignty",
    "annex", "territorial", "missile", "military", "defense", "defence",
    "weapons", "nuclear", "drone", "war ", "wartime", "conflict",
    "escalat", "de-escalat", "retaliat",
    # Trade & industrial policy
    "trade", "export", "import", "subsid", "quota", "dumping",
    "industrial policy", "supply chain", "reshoring", "nearshoring",
    "protectionism", "free trade", "trade war", "trade deal",
    # Energy & commodities
    "oil", "crude", "opec", "natural gas", "lng", "pipeline",
    "energy", "petroleum", "fuel", "refiner", "coal",
    "rare earth", "lithium", "cobalt", "mineral",
    "copper", "steel", "alumin", "metal",
    "wheat", "grain", "food security", "commodit",
    # Shipping & logistics
    "shipping", "maritime", "freight", "red sea", "suez",
    "strait of hormuz", "port", "blockade",
    # Central banks & monetary policy
    "central bank", "federal reserve", "interest rate", "rate hike",
    "rate cut", "inflation", "deflation", "monetary policy",
    "ecb", "boj", "pboc", "imf", "world bank",
    "quantitative", "stimulus",
    # Fiscal & regulation
    "fiscal", "budget", "spending", "debt ceiling", "sovereign debt",
    "regulat", "antitrust", "deregulat",
    # Markets & finance
    "market", "investor", "bond", "treasury", "yield",
    "equit", "stock", "index", "recession", "gdp",
    "currency", "dollar", "euro", "yuan", "yen",
    "crypto", "bitcoin",
    # Sectors
    "semiconductor", "chip", "tech sector", "pharma", "biotech",
    "aerospace", "auto industry", "automotive",
    # Key actors (catch headlines that name actors without other keywords)
    "white house", "kremlin", "beijing", "brussels",
    "pentagon", "congress", "parliament",
}


def is_relevant(title: str) -> bool:
    """Return True if the headline matches at least one domain keyword.

    Uses substring matching on the lowercased title so that stems like
    'sanction' catch 'sanctions', 'sanctioned', etc.
    """
    low = title.lower()
    return any(kw in low for kw in RELEVANCE_KEYWORDS)


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

    # Sort newest-first; records without a timestamp go to the end
    relevant.sort(key=lambda r: r["published_at"] or "", reverse=True)
    return relevant, feed_status


# ---------------------------------------------------------------------------
# Headline clustering
# ---------------------------------------------------------------------------
# Groups near-duplicate headlines from different publishers into a single
# "event cluster" with one representative headline and a ranked source list.
# Uses word-set Jaccard similarity — deterministic, no heavy dependencies.

_STOP_WORDS: set[str] = {
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or",
    "is", "are", "was", "were", "by", "with", "from", "as", "its", "it",
    "that", "this", "be", "has", "have", "had", "not", "but", "will",
    "would", "could", "should", "may", "might", "after", "before", "over",
    "new", "says", "said", "about", "into", "up", "out", "more", "than",
}

# Jaccard threshold for merging into the same cluster.  0.30 catches obvious
# overlapping stories without aggressively merging merely topical headlines.
_CLUSTER_THRESHOLD: float = 0.30

# If any pair inside a cluster falls below this, flag agreement as "mixed".
_AGREEMENT_THRESHOLD: float = 0.20


def _headline_words(title: str) -> set[str]:
    """Extract content words from a headline for similarity comparison."""
    return set(title.lower().split()) - _STOP_WORDS


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard index between two word sets.  Returns 0.0 when either is empty."""
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
    "rare earth": "critical minerals", "mineral": "critical minerals",
    "lithium": "critical minerals",
    "semiconductor": "technology", "chip": "technology",
    "oil": "energy", "crude": "energy", "petroleum": "energy",
    "opec": "energy", "gas": "energy", "lng": "energy",
    "steel": "metals", "aluminium": "metals", "aluminum": "metals",
    "copper": "metals", "metal": "metals",
    "defence": "defense", "defense": "defense",
    "weapon": "defense", "arms": "defense",
    "shipping": "logistics", "maritime": "logistics",
    "freight": "logistics", "red sea": "logistics",
    "wheat": "agriculture", "grain": "agriculture",
    "food": "agriculture",
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

    Uses pairwise Jaccard similarity with union-find so that clustering is
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

    word_sets = [_headline_words(rec["title"]) for rec in records]

    for i in range(n):
        for j in range(i + 1, n):
            if _jaccard(word_sets[i], word_sets[j]) >= _CLUSTER_THRESHOLD:
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

        # -- Agreement: check all pairs within cluster --
        agreement = "consistent"
        if len(recs) > 1:
            word_sets = [_headline_words(r["title"]) for r in recs]
            for i in range(len(word_sets)):
                for j in range(i + 1, len(word_sets)):
                    if _jaccard(word_sets[i], word_sets[j]) < _AGREEMENT_THRESHOLD:
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

    result.sort(key=lambda c: c["published_at"] or "", reverse=True)
    return result
