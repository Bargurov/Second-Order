#!/usr/bin/env python3
"""
Empirical evaluation of relevance filtering and clustering thresholds.

Pulls live RSS headlines (or reads a saved snapshot), runs them through the
current relevance filter and clustering pipeline, and prints a reviewable
report covering:

  1. Relevance filter: keep/drop decisions with matched keywords
  2. Cluster assignments: which headlines merged, Jaccard scores
  3. Agreement signals per cluster
  4. Threshold summary with current values

Usage:
  python scripts/eval_news_thresholds.py              # live RSS fetch
  python scripts/eval_news_thresholds.py --save       # save snapshot
  python scripts/eval_news_thresholds.py --load snap  # replay from file

Requires feedparser (pip install feedparser).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from news_sources import (
    is_relevant,
    cluster_headlines,
    RELEVANCE_KEYWORDS,
    _WORD_BOUNDARY_KW,
    _WB_PATTERN,
    _NEEDS_ECONOMIC_CONTEXT,
    _ECON_CONTEXT_KW,
    _REJECT_PATTERNS,
    _ECONOMIC_CHANNEL_KW,
    _CLUSTER_THRESHOLD,
    _AGREEMENT_THRESHOLD,
    _headline_words,
    _jaccard,
    DEFAULT_FEEDS,
)
from db import _RELATED_THRESHOLD


# ---------------------------------------------------------------------------
# Headline fetching
# ---------------------------------------------------------------------------

def fetch_live_headlines(max_per_feed: int = 20) -> list[dict]:
    """Fetch headlines from DEFAULT_FEEDS. Returns raw records."""
    import feedparser
    import socket

    records: list[dict] = []
    for feed in DEFAULT_FEEDS:
        try:
            prev = socket.getdefaulttimeout()
            socket.setdefaulttimeout(10)
            d = feedparser.parse(feed["url"])
            socket.setdefaulttimeout(prev)
        except Exception:
            print(f"  [skip] {feed['name']}: fetch failed")
            continue

        count = 0
        for entry in d.entries:
            title = (entry.get("title") or "").strip()
            # Strip Google News suffix
            if " - " in title:
                title = title.rsplit(" - ", 1)[0].strip()
            if not title:
                continue
            records.append({"title": title, "source": feed["name"]})
            count += 1
            if count >= max_per_feed:
                break
        print(f"  [{feed['name']}] {count} headlines")

    return records


# ---------------------------------------------------------------------------
# Relevance analysis
# ---------------------------------------------------------------------------

def analyze_relevance(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Classify each headline as keep or drop. Returns (kept, dropped)."""
    kept, dropped = [], []
    for rec in records:
        title = rec["title"]
        low = title.lower()
        result = is_relevant(title)

        # Determine which keywords matched
        substr_hits = [kw for kw in RELEVANCE_KEYWORDS if kw in low]
        wb_hits = _WB_PATTERN.findall(low)
        nec_hits = [kw for kw in _NEEDS_ECONOMIC_CONTEXT if kw in low.split()]
        econ_hits = [kw for kw in _ECON_CONTEXT_KW if kw in low] if nec_hits else []
        reject_hit = any(p.search(title) for p in _REJECT_PATTERNS)
        rescue_hit = [kw for kw in _ECONOMIC_CHANNEL_KW if kw in low] if reject_hit else []

        info = {
            **rec,
            "kept": result,
            "substr": substr_hits[:5],
            "wb": wb_hits[:5],
            "nec": nec_hits,
            "econ": econ_hits[:3],
            "reject": reject_hit,
            "rescue": rescue_hit[:3],
        }
        (kept if result else dropped).append(info)

    return kept, dropped


# ---------------------------------------------------------------------------
# Clustering analysis
# ---------------------------------------------------------------------------

def analyze_clusters(kept: list[dict]) -> list[dict]:
    """Run clustering and annotate with Jaccard details."""
    # Build records in the shape cluster_headlines expects
    cluster_input = [
        {"title": r["title"], "source": r["source"], "published_at": "", "url": ""}
        for r in kept
    ]
    clusters = cluster_headlines(cluster_input)

    # Annotate each cluster with pairwise Jaccard scores
    annotated = []
    for c in clusters:
        titles = [r["title"] for r in cluster_input if r["title"] in
                  [s.get("title", "") for s in c.get("evidence", [])]] or [c["headline"]]

        # Find all records that belong to this cluster by checking headline match
        word_sets = [_headline_words(c["headline"])]
        for r in cluster_input:
            if r["title"] != c["headline"]:
                sim = _jaccard(_headline_words(r["title"]), word_sets[0])
                if sim >= _CLUSTER_THRESHOLD:
                    word_sets.append(_headline_words(r["title"]))

        annotated.append({
            "headline": c["headline"],
            "source_count": c["source_count"],
            "agreement": c.get("agreement", "?"),
            "sources": [s["name"] for s in c.get("sources", [])],
        })

    return annotated


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(records, kept, dropped, clusters):
    width = 80
    print("=" * width)
    print("NEWS THRESHOLD EVALUATION REPORT")
    print("=" * width)

    print(f"\n--- Current Thresholds ---")
    print(f"  Cluster merge (Jaccard):    {_CLUSTER_THRESHOLD}")
    print(f"  Agreement (Jaccard):        {_AGREEMENT_THRESHOLD}")
    print(f"  Related events (Jaccard):   {_RELATED_THRESHOLD}")
    print(f"  Relevance keywords:         {len(RELEVANCE_KEYWORDS)} substr + {len(_WORD_BOUNDARY_KW)} word-boundary")
    print(f"  Reject patterns:            {len(_REJECT_PATTERNS)}")
    print(f"  Economic channel rescue:    {len(_ECONOMIC_CHANNEL_KW)} keywords")
    print(f"  Context-dependent (war):    {len(_NEEDS_ECONOMIC_CONTEXT)} keywords")

    print(f"\n--- Headlines ---")
    print(f"  Total fetched:  {len(records)}")
    print(f"  Kept:           {len(kept)} ({100*len(kept)//max(len(records),1)}%)")
    print(f"  Dropped:        {len(dropped)} ({100*len(dropped)//max(len(records),1)}%)")

    print(f"\n--- Relevance: KEPT ({len(kept)}) ---")
    for r in kept[:40]:
        tags = []
        if r["substr"]: tags.append(f"substr={r['substr']}")
        if r["wb"]: tags.append(f"wb={r['wb']}")
        if r["nec"]: tags.append(f"war+econ={r['econ']}")
        if r["reject"]: tags.append(f"reject→rescue={r['rescue']}")
        tag_str = "  ".join(tags) if tags else "matched"
        print(f"  KEEP  [{r['source'][:12]:12}] {r['title'][:65]}")
        print(f"        {tag_str}")

    print(f"\n--- Relevance: DROPPED ({len(dropped)}) ---")
    for r in dropped[:30]:
        reason = "no keyword match"
        if r["reject"]: reason = "reject pattern (no rescue)"
        if r["nec"] and not r["econ"]: reason = "war/conflict without economic context"
        print(f"  DROP  [{r['source'][:12]:12}] {r['title'][:65]}")
        print(f"        reason: {reason}")

    print(f"\n--- Clusters ({len(clusters)}) ---")
    multi = [c for c in clusters if c["source_count"] > 1]
    single = [c for c in clusters if c["source_count"] == 1]
    print(f"  Multi-source: {len(multi)}  Single-source: {len(single)}")
    for c in multi:
        print(f"  MERGED [{c['source_count']} src, {c['agreement']}] {c['headline'][:65]}")
        print(f"         sources: {', '.join(c['sources'])}")
    if single:
        print(f"\n  Single-source clusters (first 15):")
        for c in single[:15]:
            print(f"    [{c['sources'][0] if c['sources'] else '?':12}] {c['headline'][:65]}")

    # Flag potential issues
    print(f"\n--- Potential Issues ---")
    issues = 0
    # Check for suspicious keeps
    for r in kept:
        if not r["substr"] and not r["wb"] and not r["nec"]:
            print(f"  WARN: kept with no clear keyword match: {r['title'][:60]}")
            issues += 1
    # Check for suspicious drops
    for r in dropped:
        low = r["title"].lower()
        if any(w in low for w in ["tariff", "sanction", "opec", "central bank"]):
            print(f"  WARN: dropped despite strong keyword: {r['title'][:60]}")
            issues += 1
    if issues == 0:
        print("  None detected.")

    print(f"\n{'=' * width}")
    print("END OF REPORT")
    print(f"{'=' * width}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Evaluate news threshold quality")
    parser.add_argument("--save", action="store_true", help="Save fetched headlines to snapshot file")
    parser.add_argument("--load", type=str, help="Load headlines from snapshot file instead of fetching")
    args = parser.parse_args()

    if args.load:
        print(f"Loading headlines from {args.load}")
        with open(args.load, "r", encoding="utf-8") as f:
            records = json.load(f)
    else:
        print("Fetching live RSS headlines...")
        records = fetch_live_headlines(max_per_feed=15)

    if args.save:
        snap_path = "scripts/headline_snapshot.json"
        with open(snap_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        print(f"Saved {len(records)} headlines to {snap_path}")

    if not records:
        print("No headlines to evaluate.")
        return

    kept, dropped = analyze_relevance(records)
    clusters = analyze_clusters(kept)
    print_report(records, kept, dropped, clusters)


if __name__ == "__main__":
    main()
