"""
calibration_report.py
=====================
Unified calibration harness + report generator.

Measures and documents six calibration surfaces:

  1. Clustering threshold quality       (news_clustering._CLUSTER_THRESHOLD)
  2. Sector-uncertainty keyword match   (news_consensus._SECTOR_KEYWORDS vs
                                          sector_uncertainty.SECTOR_ETFS)
  3. Confidence calibration bucket depth (db.get_confidence_calibration_stats)
  4. Plausible-range guard drift         (delegates to calibrate_thresholds.py)
  5. Relevance filter behavior           (news_sources.is_relevant)
  6. Live threshold registry             (_VERIFY_MOVE_THRESHOLD, _TIGHT_THRESHOLD,
                                          _COMFORT_THRESHOLD, _MOVER_THRESHOLD — imported
                                          direct so drift is visible in one place)

Writes CALIBRATION_REPORT.md at repo root.

Run:
    python calibration_report.py              # offline, ~1 second
    python calibration_report.py --run-guards # also runs live yfinance pulls
    python calibration_report.py --out custom.md
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
from datetime import datetime, timezone

# Windows-console UTF-8 safety.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from news_sources import (
    is_relevant,
    _build_tfidf_vectors,
    _cosine_sim,
    _tokenize,
    _headline_polarity,
    _scan_keywords,
    _SECTOR_KEYWORDS,
    _CLUSTER_THRESHOLD,
)
from sector_uncertainty import SECTOR_ETFS

# Reuse the existing labeled corpus instead of inventing a new one.
from tools.headline_threshold_validation import _BUILT_IN as _HEADLINE_CORPUS


# ---------------------------------------------------------------------------
# Sector keyword corpus — headline -> set of expected canonical sectors
# ---------------------------------------------------------------------------

_SECTOR_CORPUS: list[tuple[str, set[str]]] = [
    ("TSMC delays Arizona chip fab amid equipment shortage",   {"semiconductors"}),
    ("ASML ships new EUV lithography system to Samsung",        {"semiconductors"}),
    ("OPEC+ agrees to cut oil output by 1 million bpd",         {"energy"}),
    ("Brent crude rises on Middle East tensions",               {"energy"}),
    ("US tariffs on Chinese steel and aluminum imports",        {"metals"}),
    ("Copper prices jump on Chinese stimulus hopes",            {"metals"}),
    ("Germany boosts defence spending to €100bn",               {"defense"}),
    ("Lockheed wins $2bn missile contract",                     {"defense"}),
    ("Houthi attacks on Red Sea shipping disrupt freight",      {"shipping"}),
    ("Maersk reroutes container ships around Cape of Good Hope",{"shipping"}),
    ("China restricts rare earth exports to US",                {"critical minerals"}),
    ("Lithium miners rally on EV demand forecasts",             {"critical minerals"}),
    ("Russia ban on wheat exports tightens global grain supply",{"agriculture"}),
    ("Treasury yields surge as inflation data spooks banks",    {"finance"}),
    ("Fed signals pause in rate-hike cycle",                    set()),  # no sector match expected
    ("Pope meets cardinals in Rome",                            set()),
]


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------

def _md_line(buf: io.StringIO, s: str = "") -> None:
    buf.write(s + "\n")


# ---------- Section 1: clustering threshold quality ------------------------

def _section_clustering(buf: io.StringIO) -> None:
    _md_line(buf, "## 1. Clustering threshold quality")
    _md_line(buf)
    _md_line(buf, f"Active threshold `_CLUSTER_THRESHOLD = {_CLUSTER_THRESHOLD:.2f}`  ")
    _md_line(buf, "TF-IDF cosine over `_BUILT_IN` corpus (30+ representative headlines).")
    _md_line(buf)

    titles = [t for (t, _src, _d, _n) in _HEADLINE_CORPUS]
    vecs, _ = _build_tfidf_vectors(titles)
    pols = [_headline_polarity(_tokenize(t)) for t in titles]

    pairs: list[tuple[int, int, float]] = []
    for i in range(len(titles)):
        for j in range(i + 1, len(titles)):
            pairs.append((i, j, _cosine_sim(vecs[i], vecs[j])))

    # Cosine distribution
    bins = [(0.00, 0.05), (0.05, 0.10), (0.10, 0.15),
            (0.15, 0.20), (0.20, 0.25), (0.25, 0.40), (0.40, 1.01)]
    counts = [0] * len(bins)
    for _, _, c in pairs:
        for k, (lo, hi) in enumerate(bins):
            if lo <= c < hi:
                counts[k] += 1
                break

    total = len(pairs)
    _md_line(buf, f"Pairs evaluated: **{total}**")
    _md_line(buf)
    _md_line(buf, "| cosine range | pairs | share |")
    _md_line(buf, "|---|---:|---:|")
    for (lo, hi), n in zip(bins, counts):
        pct = (n / total * 100) if total else 0
        _md_line(buf, f"| [{lo:.2f}, {hi:.2f}) | {n} | {pct:.1f}% |")
    _md_line(buf)

    # Threshold sensitivity at ±0.05
    def _merged_pairs(th: float) -> int:
        m = 0
        for i, j, c in pairs:
            if c < th:
                continue
            pi, pj = pols[i], pols[j]
            if pi and pj and pi != pj:
                continue
            m += 1
        return m

    t_lo = _CLUSTER_THRESHOLD - 0.05
    t_hi = _CLUSTER_THRESHOLD + 0.05
    _md_line(buf, "**Sensitivity (merged pair count vs threshold):**")
    _md_line(buf)
    _md_line(buf, f"- `{t_lo:.2f}` -> {_merged_pairs(t_lo)} pairs")
    _md_line(buf, f"- `{_CLUSTER_THRESHOLD:.2f}` -> {_merged_pairs(_CLUSTER_THRESHOLD)} pairs  **(active)**")
    _md_line(buf, f"- `{t_hi:.2f}` -> {_merged_pairs(t_hi)} pairs")
    _md_line(buf)

    # Borderline pairs in [threshold-0.05, threshold+0.05]
    borderline = sorted(
        [(i, j, c) for i, j, c in pairs if t_lo <= c <= t_hi],
        key=lambda x: x[2], reverse=True,
    )[:8]
    if borderline:
        _md_line(buf, f"**Borderline pairs within ±0.05 of threshold ({len(borderline)} shown):**")
        _md_line(buf)
        for i, j, c in borderline:
            _md_line(buf, f"- `{c:.3f}`  *{titles[i][:60]}*  ↔  *{titles[j][:60]}*")
        _md_line(buf)


# ---------- Section 2: sector-uncertainty keyword matching -----------------

def _section_sector_keywords(buf: io.StringIO) -> None:
    _md_line(buf, "## 2. Sector-uncertainty keyword matching quality")
    _md_line(buf)
    _md_line(buf, "Two checks:")
    _md_line(buf, "**(a)** precision / recall of `_SECTOR_KEYWORDS` on a labeled corpus.")
    _md_line(buf, "**(b)** coverage gap between `news_consensus._SECTOR_KEYWORDS` and "
                  "`sector_uncertainty.SECTOR_ETFS`.")
    _md_line(buf)

    # (a) precision/recall per sector
    per_sector_tp: dict[str, int] = {}
    per_sector_fp: dict[str, int] = {}
    per_sector_fn: dict[str, int] = {}

    for headline, expected in _SECTOR_CORPUS:
        predicted = set(_scan_keywords(headline, _SECTOR_KEYWORDS))
        for s in predicted & expected:
            per_sector_tp[s] = per_sector_tp.get(s, 0) + 1
        for s in predicted - expected:
            per_sector_fp[s] = per_sector_fp.get(s, 0) + 1
        for s in expected - predicted:
            per_sector_fn[s] = per_sector_fn.get(s, 0) + 1

    sectors = sorted(set(per_sector_tp) | set(per_sector_fp) | set(per_sector_fn))
    _md_line(buf, f"**(a) Keyword matcher on {len(_SECTOR_CORPUS)} labeled headlines:**")
    _md_line(buf)
    _md_line(buf, "| sector | TP | FP | FN | precision | recall |")
    _md_line(buf, "|---|---:|---:|---:|---:|---:|")
    for s in sectors:
        tp = per_sector_tp.get(s, 0)
        fp = per_sector_fp.get(s, 0)
        fn = per_sector_fn.get(s, 0)
        p = tp / (tp + fp) if (tp + fp) else float("nan")
        r = tp / (tp + fn) if (tp + fn) else float("nan")
        p_s = f"{p:.2f}" if p == p else "—"
        r_s = f"{r:.2f}" if r == r else "—"
        _md_line(buf, f"| {s} | {tp} | {fp} | {fn} | {p_s} | {r_s} |")
    _md_line(buf)

    # (b) coverage gap between keyword sectors and ETF sectors
    news_sectors = set(_SECTOR_KEYWORDS.values())
    # Map ETF sectors to canonical lowercase for comparison
    etf_sectors_raw = set(SECTOR_ETFS.keys())
    etf_sectors_norm = {
        "semiconductors": "Semiconductors",
        "energy":         "Energy",
        "defense":        "Defense",
        "finance":        "Financials",
        "metals":         "Materials",   # closest ETF proxy
    }
    _md_line(buf, "**(b) News-consensus sector  →  sector_uncertainty ETF universe:**")
    _md_line(buf)
    _md_line(buf, "| news-consensus sector | mapped ETF group | covered? |")
    _md_line(buf, "|---|---|---|")
    uncovered: list[str] = []
    for s in sorted(news_sectors):
        mapped = etf_sectors_norm.get(s)
        ok = mapped in etf_sectors_raw if mapped else False
        _md_line(buf, f"| {s} | {mapped or '—'} | {'✓' if ok else '✗'} |")
        if not ok:
            uncovered.append(s)
    _md_line(buf)

    unused_etf = etf_sectors_raw - set(etf_sectors_norm.values())
    _md_line(buf, f"Sectors tagged by news but **not tracked** by sector-uncertainty ETF vol: "
                  f"{', '.join(uncovered) or 'none'}")
    _md_line(buf, f"ETF sectors **not reachable** via news keyword tagging: "
                  f"{', '.join(sorted(unused_etf)) or 'none'}")
    _md_line(buf)


# ---------- Section 3: confidence-calibration bucket depth -----------------

def _section_confidence_buckets(buf: io.StringIO) -> None:
    _md_line(buf, "## 3. Confidence-calibration bucket depth")
    _md_line(buf)

    try:
        import db
        db.init_db()
        stats = db.get_confidence_calibration_stats(min_events=1)
    except Exception as e:
        _md_line(buf, f"_DB unavailable: {e}_")
        _md_line(buf)
        return

    # Raw bucket totals (regardless of usable outcomes)
    import sqlite3
    raw_totals: dict[str, int] = {"low": 0, "medium": 0, "high": 0}
    try:
        with db.connect_db() as conn:
            for conf, n in conn.execute(
                "SELECT confidence, COUNT(*) FROM events "
                "WHERE confidence IN ('low','medium','high') "
                "GROUP BY confidence"
            ):
                raw_totals[conf] = n
    except Exception:
        pass

    _md_line(buf, f"DB file: `{db.get_db_path()}`")
    _md_line(buf)
    _md_line(buf, "| bucket | total events | with directional outcome | hit rate | depth verdict |")
    _md_line(buf, "|---|---:|---:|---:|---|")
    for bucket in ("low", "medium", "high"):
        total = raw_totals.get(bucket, 0)
        calib = stats.get(bucket, {})
        n_cal = calib.get("n", 0)
        rate = calib.get("hit_rate")
        rate_s = f"{rate:.2%}" if isinstance(rate, (int, float)) else "—"
        verdict = "OK" if n_cal >= 20 else ("THIN" if n_cal >= 5 else "UNUSABLE")
        _md_line(buf, f"| {bucket} | {total} | {n_cal} | {rate_s} | {verdict} |")
    _md_line(buf)
    _md_line(buf, "Buckets with <5 usable events should not be surfaced as track-record claims.")
    _md_line(buf, "Buckets with 5-20 are directional only. 20+ supports a quoted hit rate.")
    _md_line(buf)


# ---------- Section 4: plausible-range guard drift -------------------------

def _section_guards(buf: io.StringIO, run_live: bool) -> None:
    _md_line(buf, "## 4. Plausible-range guard drift")
    _md_line(buf)
    _md_line(buf, "Guards under audit (see `calibrate_thresholds.py` for authoritative logic):")
    _md_line(buf)
    _md_line(buf, "- `_PRICE_FLOORS` in `market_check.py` — 8 tickers (HYG, SHY, RSP, SPY, "
                  "GLD, DX-Y.NYB, TLT, TIP)")
    _md_line(buf, "- `_MACRO_PRICE_FLOORS` — DXY, CL, BZ=F, ^VIX")
    _md_line(buf, "- Signal thresholds — VIX ratio, credit spread, safe-haven avg, "
                  "breadth gap, high-volume")
    _md_line(buf, "- Pass-2 thresholds — `shock_decomposition._CHANNEL_SCALE`, "
                  "`reaction_function_divergence`, `reserve_stress_overlay`, "
                  "`real_yield_context`, `surprise_vs_anticipation`")
    _md_line(buf)

    if not run_live:
        _md_line(buf, "_Guard-drift check skipped (requires yfinance network pulls, ~1-3 min)._  ")
        _md_line(buf, "Run `python calibration_report.py --run-guards` to include, or invoke")
        _md_line(buf, "`python calibrate_thresholds.py` and `python calibrate_thresholds_pass2.py` directly.")
        _md_line(buf)
        return

    for script in ("calibrate_thresholds.py", "calibrate_thresholds_pass2.py"):
        _md_line(buf, f"### `{script}` output")
        _md_line(buf)
        try:
            proc = subprocess.run(
                [sys.executable, script],
                capture_output=True, text=True, timeout=300,
                cwd=os.path.dirname(os.path.abspath(__file__)),
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            out = out.strip()
        except subprocess.TimeoutExpired:
            out = "(timed out after 300s)"
        except Exception as e:
            out = f"(subprocess error: {e})"

        _md_line(buf, "```")
        # Truncate extremely long output so the report stays readable.
        if len(out) > 12000:
            out = out[:12000] + "\n... (truncated)"
        _md_line(buf, out)
        _md_line(buf, "```")
        _md_line(buf)


# ---------- Section 5: relevance filter behavior ---------------------------

def _section_relevance(buf: io.StringIO) -> None:
    _md_line(buf, "## 5. Relevance filter behavior")
    _md_line(buf)

    pos = [(t, src, note) for (t, src, d, note) in _HEADLINE_CORPUS if d == "keep"]
    neg = [(t, src, note) for (t, src, d, note) in _HEADLINE_CORPUS if d == "drop"]
    amb = [(t, src, note) for (t, src, d, note) in _HEADLINE_CORPUS if d == "?"]

    tp = sum(1 for (t, _, _) in pos if is_relevant(t))
    fn = len(pos) - tp
    tn = sum(1 for (t, _, _) in neg if not is_relevant(t))
    fp = len(neg) - tn

    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall    = tp / (tp + fn) if (tp + fn) else float("nan")
    f1 = (2 * precision * recall / (precision + recall)
          if precision == precision and recall == recall and (precision + recall) else float("nan"))

    _md_line(buf, f"Labeled corpus: **{len(pos)} positives**, **{len(neg)} negatives**, "
                  f"**{len(amb)} ambiguous** (excluded from score).")
    _md_line(buf)
    _md_line(buf, "| metric | value |")
    _md_line(buf, "|---|---:|")
    _md_line(buf, f"| True positives | {tp} |")
    _md_line(buf, f"| False negatives | {fn} |")
    _md_line(buf, f"| True negatives | {tn} |")
    _md_line(buf, f"| False positives | {fp} |")
    _md_line(buf, f"| Precision | {precision:.2%} |" if precision == precision else "| Precision | — |")
    _md_line(buf, f"| Recall | {recall:.2%} |" if recall == recall else "| Recall | — |")
    _md_line(buf, f"| F1 | {f1:.2%} |" if f1 == f1 else "| F1 | — |")
    _md_line(buf)

    fn_items = [(t, note) for (t, _, note) in pos if not is_relevant(t)]
    fp_items = [(t, note) for (t, _, note) in neg if is_relevant(t)]

    if fn_items:
        _md_line(buf, "**False negatives (expected keep, dropped):**")
        for t, note in fn_items:
            _md_line(buf, f"- *{t}* — `{note}`")
        _md_line(buf)

    if fp_items:
        _md_line(buf, "**False positives (expected drop, kept):**")
        for t, note in fp_items:
            _md_line(buf, f"- *{t}* — `{note}`")
        _md_line(buf)

    if amb:
        _md_line(buf, "**Ambiguous outcomes (not scored):**")
        for t, _src, note in amb:
            verdict = "keep" if is_relevant(t) else "drop"
            _md_line(buf, f"- [{verdict}] *{t}* — `{note}`")
        _md_line(buf)


# ---------- Section 6: live threshold registry -----------------------------

def _section_live_thresholds(buf: io.StringIO) -> None:
    """Pin the runtime cutoffs that don't live in any of the above sections.

    Each value is imported directly from its defining module so the report
    will raise on rename instead of silently staying stale.  Drift between
    doc and code is loud, not silent.
    """
    _md_line(buf, "## 6. Live threshold registry")
    _md_line(buf)
    _md_line(buf, "Runtime cutoffs that aren't sampled elsewhere in this report, "
                  "imported directly from their defining module so rename / removal "
                  "surfaces here as an `import failed:` row instead of silently rotting.")
    _md_line(buf)

    rows: list[tuple[str, str, str, str, str]] = []

    try:
        from market_check import _VERIFY_MOVE_THRESHOLD
        rows.append((
            "`_VERIFY_MOVE_THRESHOLD`", f"{_VERIFY_MOVE_THRESHOLD:.2f}", "%",
            "market_check.py",
            "`|return_5d|` above this triggers a secondary-provider verification "
            "round inside `_verify_ticker_return_impl`.",
        ))
    except Exception as e:
        rows.append(("`_VERIFY_MOVE_THRESHOLD`", "—", "—", "market_check.py",
                     f"import failed: {e}"))

    try:
        from market_check import _TIGHT_THRESHOLD
        rows.append((
            "`_TIGHT_THRESHOLD`", f"{_TIGHT_THRESHOLD:+.2f}", "% (20d)",
            "market_check.py",
            "Commodity-proxy 20d return above this flags a supply-tightening "
            "regime in `classify_inventory_context`.",
        ))
    except Exception as e:
        rows.append(("`_TIGHT_THRESHOLD`", "—", "—", "market_check.py",
                     f"import failed: {e}"))

    try:
        from market_check import _COMFORT_THRESHOLD
        rows.append((
            "`_COMFORT_THRESHOLD`", f"{_COMFORT_THRESHOLD:+.2f}", "% (20d)",
            "market_check.py",
            "Commodity-proxy 20d return below this flags a supply-easing "
            "regime in `classify_inventory_context`.",
        ))
    except Exception as e:
        rows.append(("`_COMFORT_THRESHOLD`", "—", "—", "market_check.py",
                     f"import failed: {e}"))

    try:
        from api import _MOVER_THRESHOLD
        rows.append((
            "`_MOVER_THRESHOLD`", f"{_MOVER_THRESHOLD:.2f}", "%",
            "api.py",
            "`|return_5d|` below this disqualifies an event from the "
            "Market Movers surface in `api._score_event`.",
        ))
    except Exception as e:
        rows.append(("`_MOVER_THRESHOLD`", "—", "—", "api.py",
                     f"import failed: {e}"))

    _md_line(buf, "| symbol | value | unit | defined in | purpose |")
    _md_line(buf, "|---|---:|---|---|---|")
    for name, value, unit, source, purpose in rows:
        _md_line(buf, f"| {name} | {value} | {unit} | `{source}` | {purpose} |")
    _md_line(buf)
    _md_line(buf, "To change any value: edit the named module, re-run "
                  "`python calibration_report.py`, and diff this section.")
    _md_line(buf)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_report(run_guards: bool = False) -> str:
    buf = io.StringIO()
    _md_line(buf, "# Second Order — Calibration Report")
    _md_line(buf)
    _md_line(buf, f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    _md_line(buf)
    _section_clustering(buf)
    _section_sector_keywords(buf)
    _section_confidence_buckets(buf)
    _section_guards(buf, run_live=run_guards)
    _section_relevance(buf)
    _section_live_thresholds(buf)
    return buf.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default="CALIBRATION_REPORT.md",
                        help="output markdown path (default: CALIBRATION_REPORT.md)")
    parser.add_argument("--run-guards", action="store_true",
                        help="invoke calibrate_thresholds*.py for section 4 (needs network)")
    args = parser.parse_args()

    report = build_report(run_guards=args.run_guards)

    out_path = os.path.abspath(args.out)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"Wrote {out_path}  ({len(report):,} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
