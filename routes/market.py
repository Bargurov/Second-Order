"""Route handlers for market data, macro, stress, rates, ticker, and backtest endpoints."""

from typing import Optional

from fastapi import APIRouter, Query

from market_check import macro_snapshot, ticker_chart, ticker_info, _clean_fetch_symbol

import api as _api

router = APIRouter()


@router.post("/backtest/batch")
def backtest_batch(req: _api.BatchBacktestRequest):
    results = []
    for eid in req.event_ids:
        try:
            results.append(_api._backtest_one(eid, force=req.force))
        except Exception:
            _api._log.warning("backtest failed for event_id=%d", eid, exc_info=True)
            results.append({"event_id": eid, "outcomes": [], "score": None, "error": "failed"})
    return _api._sanitize_floats(results)


@router.post("/macro/batch")
def macro_batch(req: _api.BatchMacroRequest):
    result: dict[str, list] = {}
    for d in req.event_dates:
        if d in result:
            continue
        try:
            result[d] = macro_snapshot(event_date=d)
        except Exception:
            _api._log.warning("macro_snapshot failed for date=%s", d, exc_info=True)
            result[d] = []
    return result


@router.get("/macro")
def macro(
    event_date: Optional[str] = Query(
        None, pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Optional YYYY-MM-DD date for anchored macro context",
    ),
):
    return macro_snapshot(event_date=event_date)


@router.get("/ticker/{symbol}/chart")
def get_ticker_chart(
    symbol: str,
    event_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    symbol = _clean_fetch_symbol(symbol)
    if not symbol:
        return []
    return ticker_chart(symbol, event_date)


@router.get("/ticker/{symbol}/info")
def get_ticker_info(symbol: str):
    symbol = _clean_fetch_symbol(symbol)
    if not symbol:
        return {}
    return ticker_info(symbol)


@router.get("/ticker/{symbol}/headlines")
def get_ticker_headlines(symbol: str, limit: int = 5):
    symbol = _clean_fetch_symbol(symbol)
    if not symbol:
        return []
    info = ticker_info(symbol)
    name = info.get("name") or ""
    sym_upper = symbol.upper()
    terms = [sym_upper]
    if name and len(name) > 3:
        for word in name.split():
            if len(word) > 3 and word not in ("The", "Inc.", "Corp.", "Ltd.", "Inc", "Corp", "Ltd"):
                terms.append(word)
                break
    try:
        data = _api._get_news_cached()
    except Exception:
        _api._log.warning("ticker headlines: news cache unavailable for %s", symbol, exc_info=True)
        return []
    matches: list[dict] = []
    for cluster in data.get("clusters", []):
        headline = cluster.get("headline", "")
        headline_upper = headline.upper()
        if any(t in headline_upper for t in [sym_upper]) or \
           any(t.lower() in headline.lower() for t in terms[1:]):
            matches.append({
                "headline": headline,
                "source_count": cluster.get("source_count", 0),
                "published_at": cluster.get("published_at", ""),
            })
        if len(matches) >= limit:
            break
    return matches


@router.get("/stress")
def stress():
    from sector_uncertainty import compute_sector_uncertainty
    result = dict(_api.compute_stress_regime())
    try:
        result["sector_uncertainty"] = compute_sector_uncertainty()
    except Exception:
        _api._log.warning("stress: sector_uncertainty failed", exc_info=True)
        result["sector_uncertainty"] = {"available": False}
    try:
        result["news_uncertainty"] = _api.compute_news_uncertainty()
    except Exception:
        _api._log.warning("stress: news_uncertainty failed", exc_info=True)
        result["news_uncertainty"] = {"uncertainty_scope": "global", "sector_uncertainty": [], "lead_sector": None}
    return result


@router.get("/rates-context")
def rates_context():
    return _api.compute_rates_context()


@router.get("/snapshots")
def snapshots(refresh: bool = False):
    from market_snapshots import get_all_snapshots, refresh_all
    if refresh:
        refresh_all()
    return [s.to_dict() for s in get_all_snapshots()]


@router.get("/market-context")
def market_context(highlight_limit: int = 3):
    from market_context import compose_market_context
    from market_snapshots import get_all_snapshots

    snaps_list: list[dict] = []
    try:
        snaps_list = [s.to_dict() for s in get_all_snapshots()]
    except Exception:
        _api._log.warning("market_context: snapshots fetch failed", exc_info=True)

    stress_dict: dict | None = None
    try:
        stress_dict = _api.compute_stress_regime()
    except Exception:
        _api._log.warning("market_context: stress fetch failed", exc_info=True)

    rates_dict: dict | None = None
    regime_vec: dict | None = None
    try:
        rates_dict = _api.compute_rates_context()
    except Exception:
        _api._log.warning("market_context: rates fetch failed", exc_info=True)
    try:
        regime_vec = _api.build_regime_vector(rates_dict, stress_dict, None)
    except Exception:
        _api._log.warning("market_context: regime_vector build failed", exc_info=True)

    highlights: list[dict] = []
    try:
        highlights = _api.movers_today(limit=highlight_limit)
    except Exception:
        _api._log.warning("market_context: highlights fetch failed", exc_info=True)

    uc: dict | None = None
    try:
        uc = _api.compute_news_uncertainty()
    except Exception:
        _api._log.warning("market_context: uncertainty_concentration failed", exc_info=True)

    return _api._sanitize_floats(compose_market_context(
        snaps_list, stress_dict, highlights,
        rates=rates_dict, regime_vector=regime_vec,
        uncertainty_concentration=uc,
    ))
