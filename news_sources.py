# news_sources.py
# Re-export facade — preserves the original public API while the
# implementation lives in focused modules:
#   news_fetch.py       — sources, tiers, aliases, loading, fetch_all
#   news_relevance.py   — keyword-based headline relevance filter
#   news_clustering.py  — TF-IDF clustering, polarity, similarity
#   news_consensus.py   — structured consensus extraction, summaries

# Fetch layer
from news_fetch import (                                  # noqa: F401
    _SOURCE_TIERS, _TIER_RANK,
    source_tier,
    _SOURCE_ALIASES, normalize_source,
    _DATE_FORMATS, _normalize_timestamp,
    _ATTRIBUTION_RE, _PREFIX_RE, _strip_attribution,
    normalize_headline, _make_record,
    LOCAL_FILE, load_local,
    DEFAULT_FEEDS, load_rss,
    _dedup_key,
    fetch_all,
)

# Relevance layer
from news_relevance import (                              # noqa: F401
    RELEVANCE_KEYWORDS,
    _WORD_BOUNDARY_KW, _WB_PATTERN,
    _NEEDS_ECONOMIC_CONTEXT, _NEC_PATTERN,
    _ECON_CONTEXT_KW,
    _REJECT_PATTERNS, _ECONOMIC_CHANNEL_KW,
    is_relevant,
)

# Clustering layer
from news_clustering import (                             # noqa: F401
    _POLARITY_POS, _POLARITY_NEG,
    _headline_polarity,
    _CLUSTER_THRESHOLD, _AGREEMENT_THRESHOLD,
    _tokenize,
    _build_tfidf_vectors,
    _cosine_sim,
    _jaccard,
    _headline_words,
    cluster_headlines,
)

# Consensus layer
from news_consensus import (                              # noqa: F401
    _ACTOR_KEYWORDS, _ACTION_KEYWORDS,
    _SECTOR_KEYWORDS, _ACTOR_REGION,
    _scan_keywords, _scan_action,
    extract_consensus,
    _build_summary, _build_evidence,
)

# Token normalization (re-exported for backward compat)
from token_norm import (                                  # noqa: F401
    _STOP_WORDS, _normalize_token, _tokenize as _tokenize,
)
