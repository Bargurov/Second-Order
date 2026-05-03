"""
token_norm.py

Canonical token-normalization helpers shared by db.py and news_sources.py.

Single source of truth for:
  - _STOP_WORDS      — finance-domain stopword set
  - _NONALNUM_RE     — compiled regex for character stripping
  - _normalize_token — per-token normalization (lowercase → possessive strip →
                       character strip → minimal plural stemming)
  - _headline_words  — normalized content-word set for a headline string

Both db.py (related-event matching) and news_sources.py (inbox clustering)
import from here.  Any change to stopwords or normalization rules goes here
once and applies to both pipelines automatically.
"""

import re as _re

_STOP_WORDS: set[str] = {
    # English function words
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or",
    "is", "are", "was", "were", "by", "with", "from", "as", "its", "it",
    "that", "this", "be", "has", "have", "had", "not", "but", "will",
    "would", "could", "should", "may", "might", "after", "before", "over",
    "new", "says", "said", "about", "into", "up", "out", "more", "than",
    # Financial/news domain words — high frequency, low discriminating power.
    # These inflate Jaccard similarity between unrelated financial headlines
    # (e.g. "China launches space module" matching "China imposes tariffs"
    # via shared "market" or "global" tokens).  Validated against 54 live
    # events: only 1 of 20 headlines contained any of these tokens.
    "market", "markets", "stock", "stocks", "shares", "index",
    "price", "prices", "trading", "traders",
    "global", "economy", "economic",
    "billion", "million", "trillion",
    "report", "reports", "reporting",
    "investors", "investor", "analysts", "analyst",
    # Additional finance-domain stopwords — generic tokens that appear in nearly
    # every financial headline but carry no topic identity.  Removing them forces
    # similarity to rest on named entities (countries, commodities, institutions)
    # and event-specific nouns, reducing false-positive related-event and
    # historical-analog matches between unrelated headlines.
    #
    # Stored as normalized base forms (plurals strip the trailing "s" via
    # _normalize_token before the stopword check, so "shows" → "show", etc.).
    # Directional price verbs (rise, fall, surge, drop) are intentionally
    # excluded: paired with a commodity/asset name they ARE discriminating
    # (e.g. "Oil surges" vs "Oil prices surge after OPEC cut").
    "data", "growth", "record", "level",          # generic measure/status
    "show", "warn", "signal", "plan", "expect",   # high-freq news/analysis verbs
    "year", "month", "week", "quarter",            # generic time references
}

# Compiled once: strips everything except lowercase alphanumeric + hyphens.
_NONALNUM_RE = _re.compile(r"[^a-z0-9-]")


def _normalize_token(raw: str) -> str:
    """Normalize a single headline token for stable similarity matching.

    Steps:
      1. Lowercase.
      2. Strip possessive ``'s`` / ``\\u2019s``.
      3. Keep only ``[a-z0-9-]`` (removes periods, commas, etc.) and strip
         edge hyphens.
      4. Minimal plural suffix stripping (only for tokens > 3 chars, to avoid
         mangling short words like "us", "gas"):
         - "…ies" (len > 5) → "…y"   (rallies → rally)
         - "…es"  (len > 4) → sibilant stem or drop one char
         - "…s"   (len > 3, not "…ss") → drop trailing s
    """
    w = raw.lower()
    if w.endswith("\u2019s") or w.endswith("'s"):
        w = w[:-2]
    w = _NONALNUM_RE.sub("", w).strip("-")
    if not w:
        return ""
    if len(w) > 5 and w.endswith("ies"):
        w = w[:-3] + "y"                         # rallies → rally
    elif len(w) > 4 and w.endswith("es"):
        stem = w[:-2]
        if (stem.endswith("ss") or stem.endswith("x")
                or stem.endswith("z") or stem.endswith("ch")
                or stem.endswith("sh")):
            w = stem                              # crashes → crash
        else:
            w = w[:-1]                            # causes → cause
    elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]                                # sanctions → sanction, cuts → cut
    return w


def _tokenize(title: str) -> list[str]:
    """Return a list of normalized content tokens from *title*.

    Same pipeline as ``_headline_words`` but preserves order and
    duplicates — needed by TF-IDF vectorization where term frequency
    matters.
    """
    tokens: list[str] = []
    for raw in title.split():
        cleaned = _normalize_token(raw)
        if cleaned and cleaned not in _STOP_WORDS:
            tokens.append(cleaned)
    return tokens


def _headline_words(title: str) -> set[str]:
    """Return the set of normalized content words from *title*.

    Convenience wrapper: ``set(_tokenize(title))``.  Used by Jaccard
    similarity and related-event matching in db.py.
    """
    return set(_tokenize(title))
