# uncertainty_concentration.py
# Aggregate per-cluster news uncertainty by sector to identify WHERE
# informational uncertainty is concentrated across the news landscape.
# Pure function — no I/O, no caching.

_UNCERTAINTY_WEIGHTS: dict[str, int] = {"high": 2, "medium": 1, "low": 0}
SOURCE_CAP: int = 4
MIN_SECTOR_SCORE: int = 4
SECTOR_THRESHOLD: float = 0.55
TOP_N: int = 5


def compute_uncertainty_concentration(clusters: list[dict]) -> dict:
    """Aggregate cluster-level uncertainty by sector.

    Parameters
    ----------
    clusters : list of cluster dicts, each with ``consensus`` sub-dict
               containing ``sector`` (str) and ``uncertainty`` (str),
               plus ``source_count`` (int).

    Returns
    -------
    dict with keys:
        uncertainty_scope  : "global" | "sector" | "mixed"
        sector_uncertainty : list of top-N sector score dicts
        lead_sector        : str | None  (set only when scope == "sector")
    """
    if not clusters:
        return _empty()

    sector_buckets: dict[str, dict] = {}
    total_score: int = 0

    for cluster in clusters:
        consensus = cluster.get("consensus") or {}
        sector = (consensus.get("sector") or "unknown").strip().lower()
        uncertainty = (consensus.get("uncertainty") or "low").lower()
        source_count = max(1, int(cluster.get("source_count") or 1))

        weight = _UNCERTAINTY_WEIGHTS.get(uncertainty, 0)
        score = weight * min(source_count, SOURCE_CAP)
        total_score += score

        # Unknown clusters contribute to denominator but not sector buckets
        if not sector or sector == "unknown":
            continue

        if sector not in sector_buckets:
            sector_buckets[sector] = {"score": 0, "cluster_count": 0, "high_count": 0}

        b = sector_buckets[sector]
        b["score"] += score
        b["cluster_count"] += 1
        if uncertainty == "high":
            b["high_count"] += 1

    ranked = sorted(sector_buckets.items(), key=lambda kv: kv[1]["score"], reverse=True)

    top_sectors = [
        {
            "sector": name,
            "score": d["score"],
            "cluster_count": d["cluster_count"],
            "high_fraction": round(d["high_count"] / d["cluster_count"], 2)
            if d["cluster_count"] else 0.0,
        }
        for name, d in ranked[:TOP_N]
        if d["score"] > 0
    ]

    top_score = ranked[0][1]["score"] if ranked else 0
    top_name = ranked[0][0] if ranked else None

    scope = _classify_scope(top_score, total_score)
    lead_sector = top_name if scope == "sector" else None

    return {
        "uncertainty_scope": scope,
        "sector_uncertainty": top_sectors,
        "lead_sector": lead_sector,
    }


def _classify_scope(top_score: int, total_score: int) -> str:
    if total_score == 0 or top_score < MIN_SECTOR_SCORE:
        return "global"
    if top_score / total_score >= SECTOR_THRESHOLD:
        return "sector"
    return "mixed"


def _empty() -> dict:
    return {"uncertainty_scope": "global", "sector_uncertainty": [], "lead_sector": None}
