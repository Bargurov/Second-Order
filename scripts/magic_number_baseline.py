"""Read-only empirical baseline for magic-number risks.

Inventory companion: see docs/magic_numbers_inventory.md.
Output target: docs/magic_number_validation_baseline.md.

This script:
  - Opens events.db read-only.
  - Computes feature distributions used by the cluster ranking weights
    (`_RANK_W_*` in routes/movers.py).
  - Computes the pairwise headline-Jaccard distribution that the
    `_DEDUP_THRESHOLD` / `_RELATED_THRESHOLD` / `_ANALOG_THRESHOLD`
    family is applied against.
  - Computes the headline_registry low-impact age distribution that
    `_DEFAULT_TTL_DAYS` controls.
  - Writes nothing. Calls no providers.

Regex/weight constants below are pasted verbatim from
routes/movers.py:614-679 with the source line numbers cited so a
future reader can verify nothing has drifted.
"""
from __future__ import annotations

import json
import re
import sqlite3
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# Allow `from token_norm import ...` etc. when invoked from scripts/.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DB_PATH = "C:/Users/Bar/desktop/geo_mechanism_project/events.db"

# ---------------------------------------------------------------------------
# Constants verbatim from routes/movers.py:614-679 (DO NOT EDIT here — edit
# the source if these need to change; this script is read-only and only
# mirrors them so the baseline can be reproduced without a circular import).
# ---------------------------------------------------------------------------
_RANK_W_SOURCE_COUNT_PER     = 1.0
_RANK_SOURCE_COUNT_CAP       = 8
_RANK_W_HIGH_TIER_PER        = 1.5
_RANK_W_ASSET_TERMS          = 1.5
_RANK_W_MACRO_POLICY         = 3.0
_RANK_W_GEOPOLITICAL         = 2.5
_RANK_W_COMMODITY_POLICY     = 2.5
_RANK_W_CORPORATE_ACTION     = 1.0
_RANK_W_GENERIC_NOISE        = -3.0

_MACRO_POLICY_RE = re.compile(
    r"\b("
    r"federal\s+reserve|fed(?:eral)?\b|fomc|"
    r"ecb|boj|boe|pboc|snb|rba|rbnz|bank\s+of\s+(?:england|japan|canada|korea)|"
    r"central\s+bank|monetary\s+policy|rate\s+(?:cut|hike|decision|hold)s?|"
    r"interest\s+rate(?:s)?|cpi|ppi|pce|nonfarm|payrolls|jobs\s+report|"
    r"inflation|unemployment|gdp|recession|stimulus|quantitative"
    r")\b",
    re.IGNORECASE,
)
_GEOPOLITICAL_RE = re.compile(
    r"\b("
    r"sanction(?:s|ed|ing)?|embargo(?:es|ed)?|tariff(?:s)?|export\s+control|"
    r"missile|airstrike|invasion|escalat(?:e|es|ed|ion)|retaliat(?:e|es|ed|ion)|"
    r"strait\s+of\s+hormuz|red\s+sea|suez|blockade|"
    r"nato|kremlin|white\s+house|pentagon|brussels|"
    r"ceasefire|truce|treaty|annex(?:ed|ation)?"
    r")\b",
    re.IGNORECASE,
)
_COMMODITY_POLICY_RE = re.compile(
    r"\b("
    r"opec(?:\+|plus)?|crude(?:\s+oil)?|brent|wti|natural\s+gas|lng|"
    r"oil\s+(?:output|production|export|price|embargo|sanction)|"
    r"rare\s+earth(?:s)?|lithium|cobalt|copper|nickel|uranium|"
    r"semiconductor(?:s)?|chip\s+(?:export|import|ban)|wafer|foundry|"
    r"wheat|grain|fertili[sz]er"
    r")\b",
    re.IGNORECASE,
)
_CORPORATE_ACTION_RE = re.compile(
    r"\b("
    r"merger|acquisition|acquires?|takeover|buyback|repurchase|"
    r"ipo\b|listing|spin[\s\-]?off|"
    r"earnings|guidance|profit\s+warning|"
    r"dividend\s+(?:cut|raise|hike)|"
    r"layoffs?|restructur(?:e|ing)"
    r")\b",
    re.IGNORECASE,
)
_GENERIC_FINANCE_NOISE_RE = re.compile(
    r"\b("
    r"market\s+wrap|markets?\s+(?:close|open)|"
    r"stocks?\s+(?:open|close|edge|ease|rise|fall|slip|gain|drop)|"
    r"shares?\s+(?:open|close|edge|ease|rise|fall|slip|gain|drop)|"
    r"wall\s+street\s+(?:close|open|wrap|recap|edges?)|"
    r"asia\s+(?:close|opens?)|europe\s+(?:close|opens?)|"
    r"yields?\s+(?:tick|edge|drift|inch)|"
    r"recap\b|roundup\b|wrap[\s\-]?up\b|"
    r"light\s+trading|quiet\s+trading|range[\s\-]bound"
    r")\b",
    re.IGNORECASE,
)

# Asset-term regexes mirrored verbatim from routes/movers.py:580-586.
_ASSET_TERM_RE = re.compile(
    r"\b(?:NYSE|NASDAQ|AMEX|ETF|Inc\.?|Corp\.?|Ltd\.?|PLC|SA|AG|Holdings|"
    r"shares|stock|ticker|earnings|dividend|buyback|IPO|listing|index|bonds?|"
    r"yield|spread|treasur(?:y|ies))\b",
    re.IGNORECASE,
)
_ASSET_TICKER_RE = re.compile(r"\$[A-Z]{2,5}\b|\([A-Z]{2,5}(?:[.\-][A-Z]{1,3})?\)")


def _has_asset_terms(headline: str) -> bool:
    if not headline:
        return False
    return bool(_ASSET_TICKER_RE.search(headline) or _ASSET_TERM_RE.search(headline))


def _high_tier_count(sources: list) -> int:
    if not isinstance(sources, list):
        return 0
    n = 0
    for s in sources:
        tier = ""
        if isinstance(s, dict):
            tier = str(s.get("tier") or "").lower()
        if tier == "high":
            n += 1
    return n


def _signals(headline: str) -> dict:
    text = headline or ""
    return {
        "macro_policy":          bool(_MACRO_POLICY_RE.search(text)),
        "geopolitical":          bool(_GEOPOLITICAL_RE.search(text)),
        "commodity_policy":      bool(_COMMODITY_POLICY_RE.search(text)),
        "corporate_action":      bool(_CORPORATE_ACTION_RE.search(text)),
        "generic_finance_noise": bool(_GENERIC_FINANCE_NOISE_RE.search(text)),
    }


def _score(cluster: dict) -> tuple[float, dict]:
    sc = int(cluster.get("source_count") or 0)
    ht = _high_tier_count(cluster.get("sources"))
    asset = _has_asset_terms(str(cluster.get("headline") or ""))
    sig = _signals(cluster.get("headline") or "")
    score = 0.0
    score += min(sc, _RANK_SOURCE_COUNT_CAP) * _RANK_W_SOURCE_COUNT_PER
    score += ht * _RANK_W_HIGH_TIER_PER
    if asset: score += _RANK_W_ASSET_TERMS
    if sig["macro_policy"]:          score += _RANK_W_MACRO_POLICY
    if sig["geopolitical"]:          score += _RANK_W_GEOPOLITICAL
    if sig["commodity_policy"]:      score += _RANK_W_COMMODITY_POLICY
    if sig["corporate_action"]:      score += _RANK_W_CORPORATE_ACTION
    if sig["generic_finance_noise"]: score += _RANK_W_GENERIC_NOISE
    return score, {"source_count": sc, "high_tier": ht, "has_asset_terms": asset, **sig}


# ---------------------------------------------------------------------------
# Quantile + summary helpers
# ---------------------------------------------------------------------------

def quantiles(xs: list[float], qs=(0.05, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99)) -> dict:
    if not xs:
        return {}
    s = sorted(xs)
    out = {}
    for q in qs:
        idx = int(round(q * (len(s) - 1)))
        out[f"p{int(q*100)}"] = s[idx]
    return out


# ---------------------------------------------------------------------------
# Risk 1: cluster ranking-weight feature distribution
# ---------------------------------------------------------------------------

def baseline_risk1(con) -> dict:
    rows = con.execute(
        "SELECT id, headline, payload_json FROM news_clusters"
    ).fetchall()
    n = len(rows)
    fired = Counter()
    feats = {"source_count": [], "high_tier": [], "scores": []}
    score_caused_by = Counter()  # which weight contributed the largest absolute slice
    skipped_payload = 0
    for cid, headline, pj in rows:
        try:
            payload = json.loads(pj) if pj else {}
        except Exception:
            skipped_payload += 1
            continue
        cluster = {
            "headline": payload.get("headline") or headline or "",
            "source_count": payload.get("source_count") or 0,
            "sources": payload.get("sources") or [],
        }
        s, f = _score(cluster)
        feats["source_count"].append(f["source_count"])
        feats["high_tier"].append(f["high_tier"])
        feats["scores"].append(s)
        for k in ("has_asset_terms", "macro_policy", "geopolitical",
                  "commodity_policy", "corporate_action", "generic_finance_noise"):
            if f[k]:
                fired[k] += 1
        # Largest weight contributor
        contribs = {
            "source_count":     min(f["source_count"], _RANK_SOURCE_COUNT_CAP) * _RANK_W_SOURCE_COUNT_PER,
            "high_tier":        f["high_tier"] * _RANK_W_HIGH_TIER_PER,
            "asset_terms":      _RANK_W_ASSET_TERMS if f["has_asset_terms"] else 0.0,
            "macro_policy":     _RANK_W_MACRO_POLICY if f["macro_policy"] else 0.0,
            "geopolitical":     _RANK_W_GEOPOLITICAL if f["geopolitical"] else 0.0,
            "commodity_policy": _RANK_W_COMMODITY_POLICY if f["commodity_policy"] else 0.0,
            "corporate_action": _RANK_W_CORPORATE_ACTION if f["corporate_action"] else 0.0,
            "generic_noise":    _RANK_W_GENERIC_NOISE if f["generic_finance_noise"] else 0.0,
        }
        # winner = max by absolute value (negative penalty can dominate)
        winner = max(contribs.items(), key=lambda kv: abs(kv[1]))
        if winner[1] != 0:
            score_caused_by[winner[0]] += 1
        else:
            score_caused_by["__zero_score__"] += 1
    return {
        "n_clusters": n,
        "skipped_payload_parse_failures": skipped_payload,
        "fired_counts": dict(fired),
        "fired_rates": {k: round(v / n, 4) for k, v in fired.items()},
        "source_count_q": quantiles(feats["source_count"]),
        "source_count_above_cap_count": sum(1 for x in feats["source_count"] if x > _RANK_SOURCE_COUNT_CAP),
        "high_tier_q": quantiles(feats["high_tier"]),
        "high_tier_eq0_count": sum(1 for x in feats["high_tier"] if x == 0),
        "score_q": quantiles(feats["scores"]),
        "score_mean": statistics.mean(feats["scores"]) if feats["scores"] else None,
        "score_negative_count": sum(1 for x in feats["scores"] if x < 0),
        "score_zero_count":     sum(1 for x in feats["scores"] if x == 0),
        "dominant_contributor_counts": dict(score_caused_by),
    }


# ---------------------------------------------------------------------------
# Risk 2: pairwise headline-Jaccard distribution over saved events
# ---------------------------------------------------------------------------
# We import the live tokenizer/jaccard so we measure exactly what the
# product code measures.  These are leaf modules and import cleanly.
from token_norm import _headline_words  # noqa: E402
from db import _jaccard, _short_headline_guard  # noqa: E402

_DEDUP_THRESHOLD: float = 0.65
_DEDUP_DATE_WINDOW_DAYS: int = 2
_RELATED_THRESHOLD: float = 0.35
_ANALOG_THRESHOLD: float = 0.15


def _date_close(d1, d2) -> bool:
    if not d1 or not d2:
        return False
    try:
        a = datetime.fromisoformat(d1).date()
        b = datetime.fromisoformat(d2).date()
        return abs((a - b).days) <= _DEDUP_DATE_WINDOW_DAYS
    except Exception:
        return d1 == d2


def baseline_risk2(con) -> dict:
    rows = con.execute(
        "SELECT id, headline, event_date, timestamp FROM events"
    ).fetchall()
    headlines = [(r[0], r[1] or "", r[2], r[3]) for r in rows]
    n = len(headlines)
    word_sets = [_headline_words(h) for _, h, _, _ in headlines]

    sims_all: list[float] = []
    sims_in_window: list[float] = []
    above_dedup = 0
    above_dedup_with_guard = 0
    above_dedup_in_window_with_guard = 0
    above_related = 0
    above_analog = 0
    n_pairs = 0
    n_pairs_in_window = 0

    for i in range(n):
        wi = word_sets[i]
        if not wi:
            continue
        di = headlines[i][2]
        for j in range(i + 1, n):
            wj = word_sets[j]
            if not wj:
                continue
            n_pairs += 1
            sim = _jaccard(wi, wj)
            sims_all.append(sim)
            if sim >= _ANALOG_THRESHOLD:    above_analog += 1
            if sim >= _RELATED_THRESHOLD:   above_related += 1
            if sim >= _DEDUP_THRESHOLD:
                above_dedup += 1
                if _short_headline_guard(wi, wj):
                    above_dedup_with_guard += 1
            dj = headlines[j][2]
            if _date_close(di, dj):
                n_pairs_in_window += 1
                sims_in_window.append(sim)
                if sim >= _DEDUP_THRESHOLD and _short_headline_guard(wi, wj):
                    above_dedup_in_window_with_guard += 1

    return {
        "n_events": n,
        "n_pairs_total": n_pairs,
        "n_pairs_within_2d_window": n_pairs_in_window,
        "sim_quantiles_all_pairs": quantiles(sims_all),
        "sim_max_all_pairs": max(sims_all) if sims_all else None,
        "sim_quantiles_within_window": quantiles(sims_in_window),
        "above_analog_threshold_0p15": above_analog,
        "above_related_threshold_0p35": above_related,
        "above_dedup_threshold_0p65_no_guard": above_dedup,
        "above_dedup_threshold_0p65_with_short_guard": above_dedup_with_guard,
        "above_dedup_threshold_0p65_in_window_with_guard": above_dedup_in_window_with_guard,
        "above_analog_rate":  round(above_analog  / n_pairs, 6) if n_pairs else None,
        "above_related_rate": round(above_related / n_pairs, 6) if n_pairs else None,
        "above_dedup_rate":   round(above_dedup   / n_pairs, 6) if n_pairs else None,
    }


# ---------------------------------------------------------------------------
# Risk 5: low-impact registry TTL age distribution
# ---------------------------------------------------------------------------

def baseline_risk5(con) -> dict:
    cols = [r[1] for r in con.execute("PRAGMA table_info(headline_registry)").fetchall()]
    needed = ["impact_level", "analyzed_at", "first_seen_at", "last_seen_at", "state", "expired_at"]
    missing = [c for c in needed if c not in cols]
    if missing:
        return {"insufficient_data": True, "missing_columns": missing, "available_columns": cols}

    rows = con.execute(
        "SELECT impact_level, analyzed_at, first_seen_at, last_seen_at, state, expired_at "
        "FROM headline_registry"
    ).fetchall()
    n = len(rows)
    by_impact = Counter()
    by_state = Counter()
    low_ages_days_anchor: list[float] = []  # analyzed_at preferred, fallback first_seen_at
    low_ages_days_first_seen: list[float] = []
    no_anchor_low = 0
    all_first_seen_ages: list[float] = []  # every row, so we can characterise corpus age
    now = datetime.now()

    def _to_dt(s):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            try:
                return datetime.fromisoformat(s.replace("Z", ""))
            except ValueError:
                return None

    for impact, analyzed_at, first_seen, last_seen, state, expired_at in rows:
        by_impact[impact or "<null>"] += 1
        by_state[state or "<null>"] += 1
        fs = _to_dt(first_seen)
        if fs is not None:
            all_first_seen_ages.append((now - fs).total_seconds() / 86400.0)
        if (impact or "").lower() != "low":
            continue
        anchor = _to_dt(analyzed_at) or fs
        if anchor is None:
            no_anchor_low += 1
            continue
        low_ages_days_anchor.append((now - anchor).total_seconds() / 86400.0)
        if fs is not None:
            low_ages_days_first_seen.append((now - fs).total_seconds() / 86400.0)

    def _bucket(ages: list[float]) -> dict:
        if not ages:
            return {}
        return {
            "lt_1d":   sum(1 for x in ages if x < 1),
            "lt_5d":   sum(1 for x in ages if x < 5),
            "ge_5d":   sum(1 for x in ages if x >= 5),
            "ge_10d":  sum(1 for x in ages if x >= 10),
            "ge_30d":  sum(1 for x in ages if x >= 30),
            "ge_90d":  sum(1 for x in ages if x >= 90),
        }

    insufficient = (by_impact.get("low", 0) == 0)
    return {
        "n_registry_rows": n,
        "by_impact_level": dict(by_impact),
        "by_state": dict(by_state),
        "low_impact_total":  by_impact.get("low", 0),
        "low_impact_no_anchor": no_anchor_low,
        "insufficient_data_for_ttl": insufficient,
        "insufficient_data_reason": (
            "0 rows in headline_registry have impact_level='low'; the TTL "
            "filter has nothing to fire on, so no empirical TTL distribution "
            "can be computed from the local archive."
            if insufficient else None
        ),
        "low_age_days_anchor_q":     quantiles(low_ages_days_anchor),
        "low_age_days_anchor_buckets": _bucket(low_ages_days_anchor),
        "low_age_days_first_seen_q": quantiles(low_ages_days_first_seen),
        "low_age_days_first_seen_buckets": _bucket(low_ages_days_first_seen),
        # Corpus-wide first_seen age — informational, characterises how much
        # registry history exists, independent of the impact_level pipeline.
        "all_rows_first_seen_age_q":       quantiles(all_first_seen_ages),
        "all_rows_first_seen_age_buckets": _bucket(all_first_seen_ages),
        "ttl_days_in_effect": 5,
        "ttl_note": (
            "ttl checks impact_level=='low' AND anchor < now - 5d, where "
            "anchor = analyzed_at, falling back to event timestamp / first_seen_at"
        ),
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> None:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    out = {
        "db_path": DB_PATH,
        "computed_at": datetime.now().isoformat(timespec="seconds"),
        "risk1_cluster_ranking_weights": baseline_risk1(con),
        "risk2_jaccard_family":          baseline_risk2(con),
        "risk5_low_impact_ttl":          baseline_risk5(con),
    }
    con.close()
    Path("baseline_output.json").write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
