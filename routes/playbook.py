"""Route handler for GET /regime-playbook — past high-quality validated events
surfaced as a regime-aware macro playbook panel on Market Overview."""

from fastapi import APIRouter, Query

from db import load_recent_events
import api as _api

router = APIRouter()

# Keyword sets used to loosely bias event selection toward regime-relevant events.
# Keys match the regime strings returned by classify_regime().
_REGIME_KEYWORDS: dict[str, list[str]] = {
    "Systemic Stress": [
        "bank", "credit", "financ", "lend", "default", "contagion",
        "liquidity", "systemic", "bailout", "collapse", "debt", "solvency",
        "yield spread", "recession", "downturn",
    ],
    "Geopolitical Stress": [
        "war", "conflict", "sanction", "military", "troops", "invasion",
        "geopolit", "terror", "missile", "nuclear", "embargo", "blockade",
        "escalat", "nato", "coup", "alliance",
    ],
    "Calm with Undercurrent": [],  # no keyword bias — return quality events
    "Calm": [],
}


def _validation_outcome(tickers: list) -> tuple[str, float | None]:
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


def _quality_score(ev: dict) -> float:
    """Lightweight quality score — validation + confidence + revisits."""
    score = 0.0
    conf_map = {"high": 3.0, "medium": 2.0, "low": 1.0}
    score += conf_map.get(str(ev.get("confidence") or "").lower(), 0.0)
    tickers = ev.get("market_tickers") or []
    tags = [(t.get("direction_tag") or "") for t in tickers if isinstance(t, dict)]
    with_tag = [t for t in tags if t]
    if with_tag:
        score += 2.0
        score += sum(1 for t in with_tag if t.startswith("supports")) / len(with_tag)
    revisits = ev.get("revisit_snapshots") or []
    score += min(len(revisits) * 0.5, 1.5)
    return score


def _regime_relevance(ev: dict, keywords: list[str]) -> bool:
    """Return True when the event is loosely relevant to the given regime keywords."""
    if not keywords:
        return True  # no filter — all events pass
    text = " ".join([
        (ev.get("headline") or ""),
        (ev.get("mechanism_summary") or ""),
    ]).lower()
    return any(kw in text for kw in keywords)


@router.get("/regime-playbook")
def get_regime_playbook(
    regime: str = Query("", description="Current stress regime label"),
    limit: int = Query(4, ge=1, le=10),
):
    """Return compact high-quality past events relevant to the current regime.

    Since regime_snapshot columns are empty on existing events, relevance is
    approximated via:
      1. Quality filter — validated, high/medium confidence, not low_signal, not mock.
      2. Regime keyword bias — headline + mechanism text matched against a keyword
         set for the given regime.  Falls back to pure quality order when no
         keyword matches exist (e.g. "Calm with Undercurrent").
    """
    keywords = _REGIME_KEYWORDS.get(regime, [])

    # Pull a broad candidate pool for scoring and filtering.
    events = load_recent_events(limit=200)

    entries = []
    for ev in events:
        # Skip mocks and low-signal noise.
        mechanism = ev.get("mechanism_summary") or ""
        if mechanism.startswith("[mock:") or not mechanism.strip():
            continue
        if ev.get("low_signal"):
            continue

        tickers = ev.get("market_tickers") or []
        outcome, support_ratio = _validation_outcome(tickers)

        # Only include events with actual market validation.
        if outcome not in ("validated", "contradicted"):
            continue

        # Regime keyword relevance check.
        if not _regime_relevance(ev, keywords):
            continue

        score = _quality_score(ev)

        # Pick the single "lead" ticker for the compact chip.
        lead = None
        for t in tickers:
            if not isinstance(t, dict):
                continue
            tag = t.get("direction_tag") or ""
            if tag.startswith("supports"):
                lead = t
                break
        if lead is None and tickers:
            lead = tickers[0] if isinstance(tickers[0], dict) else None

        entries.append({
            "_score": score,
            "id": ev["id"],
            "headline": ev.get("headline", ""),
            "event_date": ev.get("event_date"),
            "stage": ev.get("stage"),
            "persistence": ev.get("persistence"),
            "mechanism_summary": mechanism,
            "confidence": ev.get("confidence"),
            "validation_outcome": outcome,
            "support_ratio": support_ratio,
            "lead_ticker": {
                "symbol": lead.get("symbol"),
                "return_5d": lead.get("return_5d"),
                "direction_tag": lead.get("direction_tag"),
            } if lead else None,
            "revisit_count": len(ev.get("revisit_snapshots") or []),
        })

    entries.sort(key=lambda x: x["_score"], reverse=True)
    for e in entries:
        del e["_score"]

    # When no regime-specific matches exist, fall back to pure quality ranking
    # so the panel never returns empty (unless the archive itself is empty).
    if not entries and keywords:
        return get_regime_playbook(regime="", limit=limit)

    return _api._sanitize_floats(entries[:limit])
