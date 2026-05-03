"""
tools/headline_threshold_validation.py

One-time threshold validation for headline relevance and clustering.

Produces a plain-text report showing:
  1. Relevance filter audit -- which headlines are kept/dropped and why.
  2. Cluster grouping audit -- which headlines merged, cosine scores, polarity
     decisions, and agreement classification.
  3. Threshold sensitivity -- what changes if _CLUSTER_THRESHOLD moves ±0.05.

HOW TO RUN
----------
From the project root:

    # Built-in representative headlines (no DB needed):
    python -m tools.headline_threshold_validation

    # Pull live headlines from the SQLite DB instead:
    python -m tools.headline_threshold_validation --from-db

    # Read headlines from a JSON file (list of {title, source} dicts):
    python -m tools.headline_threshold_validation --input headlines.json

    # Save the report to a file:
    python -m tools.headline_threshold_validation > report.txt

HOW TO REVIEW THE OUTPUT
------------------------
Section 1 -- Relevance audit:
  Look at DROPPED headlines and ask: "should this have been kept?"
  Look at KEPT headlines tagged [warn] (reject-pattern + rescue) and ask:
    "is the economic channel here real, or a false positive?"
  The drop/keep counts at the top give a quick signal if the filter is
  too aggressive or too loose compared to your expectations.

Section 2 -- Cluster audit:
  For each cluster, check that all members are genuinely about the same
  story. Mixed-polarity pairs that were blocked show below the clusters.
  "BORDERLINE" pairs (cosine 0.12–0.27) are the most informative: these
  are just inside or just outside the merge threshold and reveal where
  the boundary sits.

Section 3 -- Sensitivity:
  See exactly which pairs flip between threshold 0.15 and 0.25. If a
  pair that should merge is listed under "separated at 0.20", that is a
  signal to lower the threshold. If a pair that should NOT merge is
  listed under "merged at 0.20", that is a signal to raise it.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys

# Reconfigure stdout to UTF-8 on Windows (cp1252 default rejects some chars).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from news_sources import (
    is_relevant,
    cluster_headlines,
    _build_tfidf_vectors,
    _cosine_sim,
    _tokenize,
    _headline_polarity,
    RELEVANCE_KEYWORDS,
    _WORD_BOUNDARY_KW,
    _REJECT_PATTERNS,
    _ECONOMIC_CHANNEL_KW,
    _NEEDS_ECONOMIC_CONTEXT,
    _ECON_CONTEXT_KW,
    _NEC_PATTERN,
    _WB_PATTERN,
    _CLUSTER_THRESHOLD,
    _AGREEMENT_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Built-in representative headlines
# ---------------------------------------------------------------------------
# Mix of clear keeps, clear drops, and edge cases.
# Format: (title, source, expected_decision, note)
# expected_decision: "keep", "drop", or "?" (genuinely ambiguous)

_BUILT_IN: list[tuple[str, str, str, str]] = [
    # --- Clear keeps ---
    ("Federal Reserve raises interest rates by 50 basis points",
     "Reuters World", "keep", "central bank / rate hike"),
    ("Fed hikes rates by half a point to fight inflation",
     "BBC Business", "keep", "fed / inflation"),
    ("US central bank increases borrowing costs 50bp",
     "WSJ World News", "keep", "central bank"),
    ("US imposes sweeping tariffs on Chinese steel imports",
     "FT World", "keep", "tariff / trade"),
    ("OPEC+ agrees to cut oil output by 1 million barrels per day",
     "Reuters World", "keep", "opec / oil output"),
    ("ECB raises borrowing costs 25bp, signals further hikes",
     "Bloomberg Markets", "keep", "ecb / rate hike"),
    ("China restricts rare earth exports amid semiconductor tech war",
     "Nikkei Asia", "keep", "rare earth / trade war"),
    ("US sanctions on Russian energy exports widen",
     "AP News", "keep", "sanction / energy"),
    ("Brent crude rises as Middle East tensions escalate",
     "OilPrice.com", "keep", "crude / escalat"),
    ("UK inflation falls to 3.4% as energy prices ease",
     "BBC World", "keep", "inflation / energy"),
    ("IMF cuts global growth forecast on trade war fears",
     "FT World", "keep", "imf / trade war / recession"),
    ("European Central Bank hikes borrowing costs by 25 basis points",
     "CNBC World", "keep", "ecb paraphrase -- should cluster with ECB raise"),
    ("Oil prices surge after OPEC+ output cut announcement",
     "MarketWatch", "keep", "oil / opec -- polarity positive"),
    ("Oil prices fall on demand concerns despite OPEC+ cut",
     "Yahoo Finance", "keep", "oil / demand -- polarity negative (should NOT cluster with above)"),
    ("Houthi missile strikes on Red Sea shipping disrupt global freight",
     "AP News", "keep", "missile / red sea / shipping / freight"),
    ("Ukraine war drives energy prices higher across Europe",
     "BBC World", "keep", "war + econ context (energy prices)"),
    ("Dollar strengthens as Treasury yields hit 16-year high",
     "WSJ World News", "keep", "dollar / treasury / yields"),
    ("Germany announces €100bn defence spending boost",
     "Reuters World", "keep", "defence / spending"),
    ("TSMC delays Arizona chip fab amid equipment shortage",
     "Nikkei Asia", "keep", "tsmc / chip / fab"),
    ("Bank of Japan ends negative rate policy in historic shift",
     "Bloomberg Markets", "keep", "boj / interest rate / monetary policy"),
    # --- Edge cases: reject-pattern + rescue ---
    ("Ukraine war kills 200 civilians in latest offensive",
     "BBC World", "drop", "casualty-only -- no economic channel"),
    ("War in Ukraine threatens wheat and grain supply chains",
     "Reuters World", "keep", "war + supply chain (rescue)"),
    ("12 soldiers killed in Gaza offensive",
     "AP News", "drop", "killed pattern -- no economic channel"),
    ("Sanctions on Iran disrupt oil tanker routes through Strait of Hormuz",
     "Reuters World", "keep", "casualty absent; sanction / oil / strait of hormuz"),
    # --- Clear drops ---
    ("Pope Francis meets with cardinals in Rome",
     "BBC World", "drop", "religious pattern"),
    ("Good Friday church services draw record crowds",
     "AP News", "drop", "religious pattern"),
    ("Local family faces rising heating bills this winter",
     "BBC World", "drop", "personal hardship pattern"),
    ("England beat France 2-1 in World Cup qualifier",
     "BBC World", "drop", "sports -- no domain keyword"),
    ("Oscar nominations announced for 2026 ceremony",
     "AP News", "drop", "entertainment -- no domain keyword"),
    ("Stranded tourists rescued from flooded resort",
     "BBC World", "drop", "tourist rescue pattern"),
    ("Prediction markets show 60% chance of Fed cut in June",
     "MarketWatch", "drop", "prediction market pattern"),
    # --- Ambiguous / false-positive risk ---
    ("Gold medal winner celebrates at Paris Olympics",
     "BBC World", "?", "gold = metal allowlist? should drop -- sports context"),
    ("Market town's new bus service gets green light",
     "BBC World", "?", "market = wb keyword but this is not a financial market"),
    ("Bond film returns to cinemas after 10-year gap",
     "BBC World", "?", "bond = wb keyword but this is not a financial bond"),
    ("Port authority approves new container terminal",
     "Reuters World", "?", "port + container -- logistics, keep or drop?"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _relevance_reason(title: str) -> str:
    """Return a short human-readable explanation for keep/drop."""
    low = title.lower()

    # Check reject patterns first
    for pat in _REJECT_PATTERNS:
        if pat.search(title):
            rescued = any(ch in low for ch in _ECONOMIC_CHANNEL_KW)
            if rescued:
                return f"[rescue] reject-pattern matched but economic channel keyword present"
            return f"[reject-pattern] '{pat.pattern[:60]}'"

    # Allowlist
    substr_hits = [kw for kw in RELEVANCE_KEYWORDS if kw in low]
    wb_hits = _WB_PATTERN.findall(low)

    if substr_hits or wb_hits:
        all_hits = substr_hits[:3] + list(set(wb_hits))[:3]
        return f"[allowlist] {', '.join(repr(h) for h in all_hits[:4])}"

    # Context-dependent (war/conflict)
    if _NEC_PATTERN.search(low):
        econ_hits = [ek for ek in _ECON_CONTEXT_KW if ek in low]
        if econ_hits:
            return f"[needs-econ-context] 'war/conflict' + {', '.join(repr(e) for e in econ_hits[:3])}"
        return "[needs-econ-context] 'war/conflict' present but NO economic channel => DROP"

    return "[no keyword match] => DROP"


def _pairwise_cosines(titles: list[str]) -> list[tuple[int, int, float, int, int]]:
    """Return (i, j, cosine, polarity_i, polarity_j) for all pairs."""
    if len(titles) < 2:
        return []
    vecs, _ = _build_tfidf_vectors(titles)
    tok_lists = [_tokenize(t) for t in titles]
    pols = [_headline_polarity(toks) for toks in tok_lists]
    pairs = []
    for i in range(len(titles)):
        for j in range(i + 1, len(titles)):
            cos = _cosine_sim(vecs[i], vecs[j])
            pairs.append((i, j, cos, pols[i], pols[j]))
    pairs.sort(key=lambda x: x[2], reverse=True)
    return pairs


def _cluster_at_threshold(records: list[dict], threshold: float) -> list[list[int]]:
    """Run union-find clustering at an arbitrary threshold. Returns groups of indices."""
    n = len(records)
    titles = [r["title"] for r in records]
    if n < 2:
        return [[i] for i in range(n)]
    vecs, _ = _build_tfidf_vectors(titles)
    tok_lists = [_tokenize(t) for t in titles]
    pols = [_headline_polarity(toks) for toks in tok_lists]
    parent = list(range(n))

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            if _cosine_sim(vecs[i], vecs[j]) >= threshold:
                pi, pj = pols[i], pols[j]
                if pi != 0 and pj != 0 and pi != pj:
                    continue
                ra, rb = _find(i), _find(j)
                if ra != rb:
                    parent[rb] = ra

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(_find(i), []).append(i)
    return list(groups.values())


# ---------------------------------------------------------------------------
# Section printers
# ---------------------------------------------------------------------------

def _section_relevance(records: list[dict], expected: dict[str, tuple[str, str]]) -> None:
    titles = [r["title"] for r in records]
    results = [(t, is_relevant(t)) for t in titles]

    kept = [(t, r) for t, r in results if r]
    dropped = [(t, r) for t, r in results if not r]

    print("=" * 72)
    print("SECTION 1 -- RELEVANCE FILTER AUDIT")
    print(f"  filter: 4-stage keyword filter  (no single tunable parameter)")
    print(f"  total: {len(titles)}  |  kept: {len(kept)} ({100*len(kept)//max(len(titles),1)}%)  |  dropped: {len(dropped)} ({100*len(dropped)//max(len(titles),1)}%)")
    print()

    mismatches: list[str] = []

    print("  KEPT")
    print("  " + "-" * 68)
    for title, _ in kept:
        exp_decision, note = expected.get(title, ("?", ""))
        flag = "  " if exp_decision in ("keep", "?") else "[!UNEXPECTED] "
        reason = _relevance_reason(title)
        warn = " <- [warn: check rescue logic]" if "[rescue]" in reason else ""
        print(f"  {flag}KEEP  {title}")
        print(f"         reason: {reason}{warn}")
        if note:
            print(f"         note:   {note}")
        if exp_decision == "drop":
            mismatches.append(f"  UNEXPECTED KEEP: {title}")
        print()

    print("  DROPPED")
    print("  " + "-" * 68)
    for title, _ in dropped:
        exp_decision, note = expected.get(title, ("?", ""))
        flag = "  " if exp_decision in ("drop", "?") else "[!UNEXPECTED] "
        reason = _relevance_reason(title)
        print(f"  {flag}DROP  {title}")
        print(f"         reason: {reason}")
        if note:
            print(f"         note:   {note}")
        if exp_decision == "keep":
            mismatches.append(f"  UNEXPECTED DROP: {title}")
        print()

    if mismatches:
        print("  *** DECISION MISMATCHES (expected vs actual) ***")
        for m in mismatches:
            print(m)
        print()


def _section_clustering(records: list[dict]) -> None:
    if not records:
        print("  (no records to cluster)")
        return

    titles = [r["title"] for r in records]
    clusters = cluster_headlines(records)
    all_pairs = _pairwise_cosines(titles)

    print("=" * 72)
    print("SECTION 2 -- CLUSTER GROUPING AUDIT")
    print(f"  _CLUSTER_THRESHOLD = {_CLUSTER_THRESHOLD}  |  _AGREEMENT_THRESHOLD = {_AGREEMENT_THRESHOLD}")
    print(f"  {len(records)} headlines -> {len(clusters)} clusters")
    print()

    print("  CLUSTERS")
    print("  " + "-" * 68)
    for idx, cl in enumerate(clusters, 1):
        sc = cl.get("source_count", 1)
        agreement = cl.get("agreement", "consistent")
        headline = cl.get("headline", "")
        sources = cl.get("sources", [])
        print(f"  [{idx}] ({sc} source{'s' if sc != 1 else ''}, {agreement})")
        print(f"      headline: {headline}")
        src_names = ", ".join(s["name"] for s in sources[:4])
        if len(sources) > 4:
            src_names += f" +{len(sources)-4}"
        print(f"      sources:  {src_names}")
        if sc > 1:
            # Show pairwise cosines for members of this cluster
            cl_titles = [s["name"] + ": ?" for s in sources]
            # Use the records we have
            member_titles = []
            for rec in records:
                if any(s["name"] == rec["source"] for s in sources):
                    member_titles.append(rec["title"])
            if len(member_titles) > 1:
                mem_pairs = _pairwise_cosines(member_titles)
                print(f"      member cosines:")
                for i, j, cos, pi, pj in mem_pairs[:6]:
                    pol_note = ""
                    if pi != 0 and pj != 0 and pi != pj:
                        pol_note = " [polarity conflict -- BLOCKED]"
                    print(f"        cos={cos:.3f}{pol_note}")
                    print(f"          A: {member_titles[i][:70]}")
                    print(f"          B: {member_titles[j][:70]}")
        print()

    # Polarity-blocked pairs
    blocked = [
        (i, j, cos, pi, pj)
        for i, j, cos, pi, pj in all_pairs
        if cos >= _CLUSTER_THRESHOLD and pi != 0 and pj != 0 and pi != pj
    ]
    if blocked:
        print("  POLARITY-BLOCKED PAIRS (similar but opposite direction -- correctly separated)")
        print("  " + "-" * 68)
        for i, j, cos, pi, pj in blocked:
            pol_str = f"+1/-1" if pi > 0 else "-1/+1"
            print(f"  cos={cos:.3f}  polarity={pol_str}")
            print(f"    A: {titles[i]}")
            print(f"    B: {titles[j]}")
            print()

    # Borderline pairs
    lo = _CLUSTER_THRESHOLD * 0.60
    hi = _CLUSTER_THRESHOLD * 1.35
    borderline = [
        (i, j, cos, pi, pj)
        for i, j, cos, pi, pj in all_pairs
        if lo <= cos <= hi
    ]
    if borderline:
        print(f"  BORDERLINE PAIRS (cosine {lo:.2f}–{hi:.2f}, near threshold {_CLUSTER_THRESHOLD})")
        print("  " + "-" * 68)
        for i, j, cos, pi, pj in borderline:
            pol_block = pi != 0 and pj != 0 and pi != pj
            decision = "MERGED" if (cos >= _CLUSTER_THRESHOLD and not pol_block) else "SEPARATED"
            print(f"  cos={cos:.3f} -> {decision}")
            print(f"    A: {titles[i]}")
            print(f"    B: {titles[j]}")
            print()


def _section_sensitivity(records: list[dict]) -> None:
    if len(records) < 2:
        return

    titles = [r["title"] for r in records]
    all_pairs = _pairwise_cosines(titles)
    candidates = [0.15, _CLUSTER_THRESHOLD, 0.25]

    print("=" * 72)
    print("SECTION 3 -- THRESHOLD SENSITIVITY")
    print(f"  current: _CLUSTER_THRESHOLD = {_CLUSTER_THRESHOLD}")
    print()

    for thr in candidates:
        groups = _cluster_at_threshold(records, thr)
        merged_pairs = sum(len(g) * (len(g) - 1) // 2 for g in groups if len(g) > 1)
        n_clusters = len(groups)
        marker = " <- current" if thr == _CLUSTER_THRESHOLD else ""
        print(f"  threshold={thr:.2f}: {n_clusters} clusters, {merged_pairs} merged pairs{marker}")

    # Pairs that flip between 0.15 and 0.25
    flip_pairs = [
        (i, j, cos, pi, pj)
        for i, j, cos, pi, pj in all_pairs
        if 0.15 <= cos <= 0.25 and not (pi != 0 and pj != 0 and pi != pj)
    ]
    if flip_pairs:
        print()
        print(f"  Pairs whose merge decision changes between threshold 0.15 and 0.25:")
        print("  " + "-" * 68)
        for i, j, cos, pi, pj in flip_pairs:
            at_15 = "MERGED" if cos >= 0.15 else "sep"
            at_20 = "MERGED" if cos >= _CLUSTER_THRESHOLD else "sep"
            at_25 = "MERGED" if cos >= 0.25 else "sep"
            print(f"  cos={cos:.3f}  [0.15:{at_15}] [0.20:{at_20}] [0.25:{at_25}]")
            print(f"    A: {titles[i][:75]}")
            print(f"    B: {titles[j][:75]}")
            print()


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------

def _load_from_db() -> list[dict]:
    """Pull the most recent 200 headlines from the DB news cache."""
    import db as _db
    try:
        conn = _db.get_connection()
        rows = conn.execute(
            "SELECT source, title, published_at, url "
            "FROM news_headlines "
            "ORDER BY published_at DESC LIMIT 200"
        ).fetchall()
        conn.close()
        return [{"source": r[0], "title": r[1], "published_at": r[2], "url": r[3]}
                for r in rows]
    except Exception as exc:
        print(f"[warn] DB load failed: {exc}. Falling back to built-in headlines.", file=sys.stderr)
        return []


def _load_from_file(path: str) -> list[dict]:
    with open(path) as fh:
        data = json.load(fh)
    if isinstance(data, list):
        # Accept both {title, source} and bare strings
        out = []
        for item in data:
            if isinstance(item, str):
                out.append({"title": item, "source": "local", "published_at": "", "url": ""})
            elif isinstance(item, dict):
                out.append({
                    "title":        item.get("title", ""),
                    "source":       item.get("source", "local"),
                    "published_at": item.get("published_at", ""),
                    "url":          item.get("url", ""),
                })
        return out
    raise ValueError("Input JSON must be a list")


def _load_built_in() -> tuple[list[dict], dict[str, tuple[str, str]]]:
    records = []
    expected: dict[str, tuple[str, str]] = {}
    for title, source, decision, note in _BUILT_IN:
        records.append({"title": title, "source": source, "published_at": "2026-04-14T00:00:00", "url": ""})
        expected[title] = (decision, note)
    return records, expected


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--from-db",  action="store_true", help="Pull headlines from the SQLite DB")
    src.add_argument("--input",    metavar="FILE",       help="Read headlines from a JSON file")
    args = parser.parse_args()

    expected: dict[str, tuple[str, str]] = {}

    if args.from_db:
        records = _load_from_db()
        if not records:
            print("[warn] No headlines from DB -- using built-in.", file=sys.stderr)
            records, expected = _load_built_in()
    elif args.input:
        records = _load_from_file(args.input)
    else:
        records, expected = _load_built_in()

    if not records:
        print("No headlines to process.", file=sys.stderr)
        sys.exit(1)

    print()
    print("HEADLINE THRESHOLD VALIDATION REPORT")
    print(f"input: {len(records)} headlines")
    print()

    _section_relevance(records, expected)
    print()

    # For clustering and sensitivity, use only the records that pass relevance
    relevant = [r for r in records if is_relevant(r["title"])]
    if not relevant:
        print("No relevant headlines -- skipping cluster sections.")
        return

    print(f"  (clustering {len(relevant)} relevant headlines)")
    print()
    _section_clustering(relevant)
    print()
    _section_sensitivity(relevant)
    print()
    print("=" * 72)
    print("END OF REPORT")
    print()


if __name__ == "__main__":
    main()
