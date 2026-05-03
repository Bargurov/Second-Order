# news_consensus.py
# Structured consensus extraction.

import re
from news_fetch import source_tier, normalize_source, _TIER_RANK

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
    (["tariff", "tariffs", "duties", "duty", "levy", "levies"], "tariffs"),
    (["sanction", "sanctions", "embargo"],                       "sanctions"),
    (["restrict", "restriction", "bans", "ban"],                 "export restrictions"),
    (["production cut", "output cut",
      "production curb", "output curb",
      "curb output", "curb production"],                         "production cut"),
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

    Lazy imports to break news_clustering ↔ news_consensus cycle.

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
    from news_clustering import _headline_words, _jaccard
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
    from news_clustering import _headline_words, _jaccard
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
