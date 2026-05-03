# news_relevance.py
# Deterministic keyword allowlist for headline relevance filtering.

import re as _re

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
    # Industrial-policy specifics — large subsidy/capex mandates
    "inflation reduction act", "chips act", "ira funding",
    "tax credit", "investment credit", "production credit",
    "green transition", "green deal", "industrial strategy",
    "made in america", "made in china", "onshoring",
    "strategic investment", "capex incentive",
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
    "merger review", "merger block", "consent decree",
    "capital requirement", "stress test", "disclosure rule",
    "dodd-frank", "basel", "mifid", "gdpr fine",
    # External balance / EM funding stress
    "current account", "balance of payments", "capital flight",
    "forex reserves", "reserve drain", "swap line",
    "sovereign cds", "sovereign spread", "bailout package",
    "bop stress", "em funding", "hard currency debt",
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
    "fab capacity", "chip fab", "advanced node", "trailing edge node",
    "chip export", "chip import", "gate-all-around", "high-na",
    # Rate-sensitive sectors (flagged so we don't drop rotation stories)
    "rate sensitive", "duration trade", "long duration",
    "reit ", "utilities sector", "homebuilder",
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

# ---------------------------------------------------------------------------
# Calendar / schedule headline guard
# ---------------------------------------------------------------------------
# Wire feeds often publish schedule notices as headlines ("DIARY: Reuters
# schedule of upcoming events", "SCHEDULED: Fed meeting at 2pm").  These
# carry no economic signal and must not surface as related events.
#
# Only unambiguously schedule-only prefixes are rejected.  PREVIEW: and
# AGENDA: are excluded from this list because they sometimes carry editorial
# analysis worth keeping.
_CALENDAR_RE: _re.Pattern[str] = _re.compile(
    r"^(DIARY|SCHEDULED|CALENDAR|ADVISORY|WEEK\s+AHEAD|TABLE)\s*[:\-]",
    _re.IGNORECASE,
)


def _is_calendar_headline(title: str) -> bool:
    """Return True if the headline is a schedule/calendar notice, not a news item."""
    return bool(_CALENDAR_RE.match(title.strip()))


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
    if _is_calendar_headline(title):
        return False

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
