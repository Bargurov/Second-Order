# news_clustering.py
# TF-IDF cosine similarity, polarity detection, union-find clustering.

from news_fetch import source_tier, normalize_source, _TIER_RANK
from news_consensus import extract_consensus, _build_summary, _build_evidence, _scan_action, _scan_keywords, _SECTOR_KEYWORDS

# Headline clustering
# ---------------------------------------------------------------------------
# Groups near-duplicate headlines from different publishers into a single
# "event cluster" with one representative headline and a ranked source list.
# Uses TF-IDF cosine similarity — rare/distinctive words matter more than
# common ones, catching cross-source rewording that pure word-overlap misses.

import math as _math
import logging as _logging

from token_norm import _STOP_WORDS, _normalize_token, _headline_words, _tokenize

_cluster_log = _logging.getLogger("second_order.cluster")


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


# ---------------------------------------------------------------------------
# Mechanism conflict guard
# ---------------------------------------------------------------------------
# Action types that are compatible and should NOT block a merge.
# E.g. "tariffs" and "trade policy" describe the same broad mechanism.
_RELATED_ACTION_PAIRS: frozenset[frozenset] = frozenset({
    frozenset({"tariffs", "trade policy"}),
    frozenset({"sanctions", "export restrictions"}),
})

# If cosine meets or exceeds this, merge regardless of mechanism conflict.
# High similarity (≥0.40) indicates near-duplicate wording — same event.
_MECHANISM_OVERRIDE_THRESHOLD: float = 0.40


def _extract_mechanism(title: str) -> tuple[str, str]:
    """Return (action, sector) fingerprint for a headline."""
    action = _scan_action(title)
    sectors = _scan_keywords(title, _SECTOR_KEYWORDS)
    sector = sectors[0] if sectors else "unknown"
    return (action, sector)


def _mechanisms_conflict(a: tuple[str, str], b: tuple[str, str]) -> bool:
    """True if action types differ and are not in a known-related pair."""
    action_a, _ = a
    action_b, _ = b
    if action_a == "unknown" or action_b == "unknown":
        return False
    if action_a == action_b:
        return False
    if frozenset({action_a, action_b}) in _RELATED_ACTION_PAIRS:
        return False
    return True


# ---------------------------------------------------------------------------
# Synonym expansion for TF-IDF only (NOT for polarity detection or Jaccard)
# ---------------------------------------------------------------------------
# Maps financial paraphrases to canonical tokens so TF-IDF cosine catches
# cross-source rewording: "duty/levy" → "tariff", "crude" → "oil", etc.
# Applied only in _tfidf_tokens(); _tokenize() stays stable for polarity
# detection and existing test assertions.
_MECHANISM_SYNONYM_MAP: dict[str, str] = {
    "duty":      "tariff",
    "levy":      "tariff",
    "levied":    "tariff",
    "output":    "production",
    "crude":     "oil",
    "petroleum": "oil",
    "curb":      "cut",
}


def _tfidf_tokens(title: str) -> list[str]:
    """Tokenize for TF-IDF: normalize then apply mechanism synonyms.

    Applies AFTER stop-word removal. Does NOT affect polarity detection.
    """
    return [_MECHANISM_SYNONYM_MAP.get(t, t) for t in _tokenize(title)]


# Cosine similarity threshold for merging into the same cluster.
# TF-IDF cosine on short (5-10 word) headlines runs lower than Jaccard
# because IDF penalises common cross-headline terms.  Calibrated on
# live feeds 2026-04: 0.20 catches cross-source rewording (e.g.
# "fuel prices surge Iran war" ↔ "oil highest price Iran war") while
# keeping unrelated stories apart (cosine ≈ 0 when no content overlap).
_CLUSTER_THRESHOLD: float = 0.20

# If any pair inside a cluster falls below this, flag agreement as "mixed".
_AGREEMENT_THRESHOLD: float = 0.12

# Mechanism-aided merge floor: when both headlines have a recognized matching
# action type, allow merging at this lower cosine (catches paraphrase pairs
# that synonym expansion alone doesn't fully bridge).
_MECH_COSINE_FLOOR: float = 0.10


# Action types excluded from the mechanism floor path: they're too often
# background context (e.g. "despite the Iran war") rather than the primary
# economic mechanism, causing false merges between unrelated stories.
_FLOOR_EXCLUDED_ACTIONS: frozenset[str] = frozenset({"military action", "de-escalation"})


def _mechanism_match(a: tuple[str, str], b: tuple[str, str]) -> bool:
    """True when both headlines share a recognized, compatible action type.

    Requires both actions to be non-'unknown' and not in the excluded set.
    Conservative to avoid false positives from sparse mechanism extraction.
    """
    action_a, _ = a
    action_b, _ = b
    if action_a == "unknown" or action_b == "unknown":
        return False
    if action_a in _FLOOR_EXCLUDED_ACTIONS or action_b in _FLOOR_EXCLUDED_ACTIONS:
        return False
    if action_a == action_b:
        return True
    if frozenset({action_a, action_b}) in _RELATED_ACTION_PAIRS:
        return True
    return False


# ---------------------------------------------------------------------------
# Generic-document title guard
# ---------------------------------------------------------------------------
# Static documents and repository entries (research reports, working papers,
# data-portal pages, World Bank Google-News proxies) bridge into live-news
# clusters two ways: shared boilerplate tokens push pairwise cosine above
# _CLUSTER_THRESHOLD even when substantive content is unrelated, and the
# generic actions extracted from their titles match live-news mechanism
# floors.  Both paths chain unrelated stories via union-find.
#
# This guard blocks both PRIMARY and FLOOR merges when exactly one side of
# a pair is a generic document.  When both sides are documents, it requires
# near-duplicate cosine so two versions of the same publication still
# cluster while two unrelated docs sharing only boilerplate do not.
# See tests/test_news_clustering.py.

# Cosine floor for merging two generic-document titles with each other.
# Higher than _CLUSTER_THRESHOLD so boilerplate-only overlap does not
# qualify; only near-duplicate substantive content does.
_GENERIC_DOC_NEAR_DUP_THRESHOLD: float = 0.50

# Substring phrases (matched case-insensitively, after strip+lower).
# Conservative list — narrow document/repository markers only; avoids
# broad words like "report" alone that would catch legitimate news.
# Excluded by design: "fact sheet" and "technical note" — both overlap
# with FDA/regulatory press releases that ARE market news.
_GENERIC_DOC_PHRASES: tuple[str, ...] = (
    "trade summary",
    "doing business",
    "connecting to compete",
    "world development report",
    "development report",
    "annual report",
    "working paper",
    "policy research working paper",
    "open knowledge",
    "data bank",
    "databank",
)

# Suffixes (matched against the stripped-lowercased title).  Capture the
# shapes the World Bank Google-News proxy and similar repository feeds
# emit, where the document type is hidden in the trailing boilerplate.
_GENERIC_DOC_SUFFIXES: tuple[str, ...] = (
    "- world bank group",
    "- world bank open data",
    "| world bank group",
    "| world bank open data",
)


def _is_generic_document_title(title: str) -> bool:
    """Return True for generic document/report/repository titles.

    Used to block bridge merges between static publication titles and
    live news inside ``cluster_headlines`` and ``news_cluster_store``.
    Returns False on empty/None input.
    """
    if not title:
        return False
    low = title.strip().lower()
    if not low:
        return False
    for suf in _GENERIC_DOC_SUFFIXES:
        if low.endswith(suf):
            return True
    for phrase in _GENERIC_DOC_PHRASES:
        if phrase in low:
            return True
    return False


# _tokenize imported from token_norm — single source of truth


def _build_tfidf_vectors(titles: list[str]) -> tuple[list[dict[str, float]], dict[str, float]]:
    """Build TF-IDF vectors for a list of titles.

    Returns (vectors, idf_map) where each vector is a dict mapping
    token → TF-IDF weight.  Uses log-IDF with add-one smoothing.
    """
    n = len(titles)
    token_lists = [_tfidf_tokens(t) for t in titles]

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
    mechanisms = [_extract_mechanism(t) for t in titles]
    is_doc = [_is_generic_document_title(t) for t in titles]

    for i in range(n):
        for j in range(i + 1, n):
            sim = _cosine_sim(tfidf_vecs[i], tfidf_vecs[j])
            # Generic-document guard: prevent bridge merges between static
            # publications and live news (and between unrelated docs that
            # share only boilerplate).  Applied before both merge paths.
            if is_doc[i] != is_doc[j]:
                _cluster_log.info(
                    "BLOCK-GENDOC cos=%.3f one-sided\n  A: %s\n  B: %s",
                    sim, titles[i], titles[j],
                )
                continue
            if is_doc[i] and is_doc[j] and sim < _GENERIC_DOC_NEAR_DUP_THRESHOLD:
                _cluster_log.info(
                    "BLOCK-GENDOC cos=%.3f both-docs-below-near-dup\n  A: %s\n  B: %s",
                    sim, titles[i], titles[j],
                )
                continue
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
                # Block merge if mechanisms clearly conflict and cosine is not
                # high enough to override (near-duplicate wording overrides).
                if _mechanisms_conflict(mechanisms[i], mechanisms[j]) and sim < _MECHANISM_OVERRIDE_THRESHOLD:
                    _cluster_log.info(
                        "BLOCK-MECH cos=%.3f action=%s/%s\n  A: %s\n  B: %s",
                        sim, mechanisms[i][0], mechanisms[j][0], titles[i], titles[j],
                    )
                    continue
                _cluster_log.info(
                    "MERGE cos=%.3f\n  A: %s\n  B: %s",
                    sim, titles[i], titles[j],
                )
                _union(i, j)
            elif sim >= _MECH_COSINE_FLOOR and _mechanism_match(mechanisms[i], mechanisms[j]):
                # Low cosine but matching action type: merge if no polarity conflict.
                pi, pj = polarities[i], polarities[j]
                if pi != 0 and pj != 0 and pi != pj:
                    continue
                _cluster_log.info(
                    "MERGE-MECH cos=%.3f action=%s\n  A: %s\n  B: %s",
                    sim, mechanisms[i][0], titles[i], titles[j],
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

        # -- Sources: deduplicate by canonical publisher, sort by tier then alphabetical --
        seen_publishers: set[str] = set()
        sources: list[dict] = []
        for r in recs:
            canon = normalize_source(r["source"])
            if canon in seen_publishers:
                continue
            seen_publishers.add(canon)
            sources.append({
                "name": r["source"],
                "tier": source_tier(r["source"]),
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
