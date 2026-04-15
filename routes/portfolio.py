"""Route handler for GET /portfolio — ranked research portfolio."""

from fastapi import APIRouter, Query

from db import load_recent_events
import api as _api
from market_check_freshness import compute_staleness

router = APIRouter()


def _validation_outcome(tickers: list) -> tuple[str, float | None]:
    """Return (outcome_label, support_ratio) from a list of ticker dicts."""
    tags = [
        (t.get("direction_tag") or "")
        for t in tickers
        if isinstance(t, dict)
    ]
    with_tag = [t for t in tags if t]
    if not with_tag:
        return ("no_data", None)
    supporting = sum(1 for t in with_tag if t.startswith("supports"))
    ratio = supporting / len(with_tag)
    if supporting > 0:
        return ("validated", ratio)
    if any(t.startswith("contradicts") for t in with_tag):
        return ("contradicted", ratio)
    return ("unresolved", ratio)


def _portfolio_score(ev: dict) -> float:
    """Higher is better. Range roughly -3 to +8."""
    score = 0.0

    conf_map = {"high": 3.0, "medium": 2.0, "low": 1.0, "very_low": 0.0}
    score += conf_map.get(str(ev.get("confidence") or "").lower(), 0.0)

    tickers = ev.get("market_tickers") or []
    tags = [(t.get("direction_tag") or "") for t in tickers if isinstance(t, dict)]
    with_tag = [t for t in tags if t]
    if with_tag:
        score += 2.0
        supporting = sum(1 for t in with_tag if t.startswith("supports"))
        score += supporting / len(with_tag)

    rating_map = {"good": 2.0, "mixed": 0.5, "poor": -1.0}
    score += rating_map.get(str(ev.get("rating") or "").lower(), 0.0)

    revisits = ev.get("revisit_snapshots") or []
    score += min(len(revisits) * 0.5, 1.5)

    if ev.get("low_signal"):
        score -= 2.0

    return score


@router.get("/portfolio")
def get_portfolio(limit: int = Query(20, ge=1, le=50)):
    """Return the top-N events ranked by analysis quality for the portfolio page."""
    events = load_recent_events(limit=200)
    entries = []
    for ev in events:
        mechanism = ev.get("mechanism_summary") or ""
        if mechanism.startswith("[mock:") or not mechanism.strip():
            continue

        tickers = ev.get("market_tickers") or []
        outcome, support_ratio = _validation_outcome(tickers)
        score = _portfolio_score(ev)
        sig = compute_staleness(ev)

        entries.append({
            "_score": score,
            "id": ev["id"],
            "headline": ev.get("headline", ""),
            "event_date": ev.get("event_date"),
            "timestamp": ev.get("timestamp"),
            "stage": ev.get("stage"),
            "persistence": ev.get("persistence"),
            "mechanism_summary": mechanism,
            "beneficiaries": ev.get("beneficiaries") or [],
            "losers": ev.get("losers") or [],
            "market_tickers": [
                {
                    "symbol": t.get("symbol"),
                    "role": t.get("role"),
                    "direction_tag": t.get("direction_tag"),
                    "return_5d": t.get("return_5d"),
                }
                for t in tickers
                if isinstance(t, dict)
            ],
            "confidence": ev.get("confidence"),
            "rating": ev.get("rating"),
            "revisit_snapshots": ev.get("revisit_snapshots") or [],
            "validation_outcome": outcome,
            "support_ratio": support_ratio,
            "stale_signal": sig["status"],
            "hours_since_check": sig.get("hours_since_check"),
            "event_age_days": sig.get("event_age_days"),
        })

    entries.sort(key=lambda x: x["_score"], reverse=True)
    for e in entries:
        del e["_score"]
    return _api._sanitize_floats(entries[:limit])
