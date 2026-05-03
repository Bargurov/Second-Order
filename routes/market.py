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
    return _api._sanitize_floats(result)


@router.get("/macro")
def macro(
    event_date: Optional[str] = Query(
        None, pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Optional YYYY-MM-DD date for anchored macro context",
    ),
):
    return _api._sanitize_floats(macro_snapshot(event_date=event_date))


@router.get("/ticker/{symbol}/chart")
def get_ticker_chart(
    symbol: str,
    event_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    symbol = _clean_fetch_symbol(symbol)
    if not symbol:
        return []
    return _api._sanitize_floats(ticker_chart(symbol, event_date))


@router.get("/ticker/{symbol}/info")
def get_ticker_info(symbol: str):
    symbol = _clean_fetch_symbol(symbol)
    if not symbol:
        return {}
    return _api._sanitize_floats(ticker_info(symbol))


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
    # Pass through the same numeric scrub every other /ticker/* route uses so
    # an upstream change that starts leaking a float field (e.g. a cluster
    # carrying a stale cached score) cannot ship NaN/inf to the browser.
    return _api._sanitize_floats(matches)


@router.get("/stress")
def stress():
    from sector_uncertainty import compute_sector_uncertainty
    result = dict(_api.compute_stress_regime())
    # Track which enrichment blocks failed so the frontend can surface an
    # explicit "degraded" state instead of rendering the fallback as fact.
    degraded_fields: list[str] = []
    try:
        result["sector_uncertainty"] = compute_sector_uncertainty()
    except Exception:
        _api._log.warning("stress: sector_uncertainty failed", exc_info=True)
        result["sector_uncertainty"] = {"available": False}
        degraded_fields.append("sector_uncertainty")
    try:
        result["news_uncertainty"] = _api.compute_news_uncertainty()
    except Exception:
        _api._log.warning("stress: news_uncertainty failed", exc_info=True)
        result["news_uncertainty"] = {"uncertainty_scope": "global", "sector_uncertainty": [], "lead_sector": None}
        degraded_fields.append("news_uncertainty")
    result["data_quality"] = "degraded" if degraded_fields else "ok"
    result["degraded_fields"] = degraded_fields
    # _sanitize_floats is a last-line scrub for NaN/inf in the raw block —
    # it operates on the same dict that already carries data_quality /
    # degraded_fields, so those markers pass through unchanged.
    return _api._sanitize_floats(result)


@router.get("/rates-context")
def rates_context():
    return _api._sanitize_floats(_api.compute_rates_context())


def _padded_snapshots_payload(*, refresh_if_empty: bool = False) -> list[dict]:
    """Return one shaped row per liquid market.

    Consumers (BenchmarkSnapshotsStrip, /market-context) rely on the
    endpoint always returning the current 8-market contract — never an
    empty list, regardless of whether the warm store has been populated
    yet.  Markets missing from the store surface as shaped rows with
    ``error='not_refreshed'`` so the frontend can render a placeholder
    cell instead of dropping the whole strip.

    When ``refresh_if_empty`` is true, a cold or partially populated store
    gets one synchronous refresh attempt before padding.  Successful
    provider reads become real benchmark rows; provider failures are stored
    as explicit per-market error rows by ``market_snapshots.refresh_all``.
    """
    from market_snapshots import (
        _build_empty_snapshot,
        get_all_snapshots,
        refresh_all,
    )
    from market_universe import LIQUID_MARKETS, resolve_symbol

    def _row_market(s) -> str | None:
        if isinstance(s, dict):
            key = s.get("market")
        else:
            key = getattr(s, "market", None)
        return key if isinstance(key, str) and key else None

    def _row_to_dict(s, market: str) -> dict:
        if isinstance(s, dict):
            row = dict(s)
        elif hasattr(s, "to_dict"):
            try:
                row = s.to_dict()
            except Exception:
                row = {}
        else:
            row = {}

        if not isinstance(row, dict):
            row = {}
        if not row:
            return _build_empty_snapshot(
                market, resolve_symbol(market), "not_refreshed",
            ).to_dict()

        # Never invent live-looking values for partial fixture rows. Fill
        # only identity/freshness keys; missing numeric fields remain None.
        empty = _build_empty_snapshot(
            market, resolve_symbol(market), "not_refreshed",
        ).to_dict()
        empty.update(row)
        empty["market"] = market
        if not empty.get("symbol"):
            empty["symbol"] = resolve_symbol(market)
        return empty

    def _index(snaps) -> dict:
        # Tolerate test fakes / partial snapshot rows that may lack a
        # ``.market`` attribute — skip them rather than crashing the
        # whole endpoint with AttributeError.
        out: dict = {}
        for s in snaps or []:
            key = _row_market(s)
            if key:
                out[key] = s
        return out

    existing = _index(get_all_snapshots())
    if refresh_if_empty and len(existing) < len(LIQUID_MARKETS):
        try:
            refresh_all()
        except Exception:
            _api._log.warning("snapshots: synchronous refresh failed", exc_info=True)
        existing = _index(get_all_snapshots())

    rows: list[dict] = []
    for market in LIQUID_MARKETS:
        snap = existing.get(market)
        if snap is None:
            snap = _build_empty_snapshot(
                market, resolve_symbol(market), "not_refreshed",
            )
        rows.append(_row_to_dict(snap, market))
    return rows


@router.get("/snapshots")
def snapshots(refresh: bool = False):
    from market_snapshots import refresh_all
    if refresh:
        refresh_all()
    return _api._sanitize_floats(_padded_snapshots_payload(refresh_if_empty=True))


@router.get("/market-context")
def market_context(highlight_limit: int = 3):
    from market_context import compose_market_context

    snaps_list: list[dict] = []
    try:
        # Cold-start auto-warm — when the SnapshotStore is empty (or
        # partially populated), trigger one synchronous refresh so the
        # response reflects warmed values instead of placeholder rows.
        # Provider failures still surface as ``error='fetch error: ...''
        # per-market rows (the truthful "this market couldn't refresh"
        # signal stays visible).  ``/snapshots`` remains the explicit
        # refresh surface for callers that want to force a re-fetch on
        # an already-populated store.
        snaps_list = _padded_snapshots_payload(refresh_if_empty=True)
    except Exception:
        _api._log.warning("market_context: snapshots fetch failed", exc_info=True)

    stress_dict: dict | None = None
    try:
        stress_dict = _api.compute_stress_regime()
    except Exception:
        _api._log.warning("market_context: stress fetch failed", exc_info=True)

    rates_dict: dict | None = None
    try:
        rates_dict = _api.compute_rates_context()
    except Exception:
        _api._log.warning("market_context: rates fetch failed", exc_info=True)

    # --- Deeper engine composers -- pure over rates + stress + news, no
    # new provider calls.  Each is guarded so one failure never breaks
    # the rest of the response.

    # Credit regime from the HY/IG/SHY 5d moves already in stress.raw.
    credit_regime: dict | None = None
    try:
        _raw = (stress_dict or {}).get("raw") or {}
        credit_regime = _api.classify_credit_regime(
            hy_5d=_raw.get("hyg_5d"),
            ig_5d=_raw.get("lqd_5d"),
            shy_5d=_raw.get("shy_5d"),
        )
    except Exception:
        _api._log.warning("market_context: credit_regime classify failed", exc_info=True)

    # Axis regime vector + compound / transition enrichment using the
    # recent archive as baseline so the transition read is grounded in
    # what the engine has actually been seeing.
    regime_vec: dict | None = None
    try:
        regime_vec = _api.build_regime_vector(
            rates_dict, stress_dict, None,
            credit_regime=credit_regime,
        )
    except Exception:
        _api._log.warning("market_context: regime_vector build failed", exc_info=True)
    try:
        from regime_compound import baseline_from_events, enrich_with_compound_regime
        baseline = baseline_from_events(_api.load_recent_events(limit=25))
        regime_vec = enrich_with_compound_regime(regime_vec, baseline)
    except Exception:
        _api._log.warning("market_context: compound_regime enrichment failed", exc_info=True)

    # Funding / liquidity stress mode decomposition.
    funding_mode: dict | None = None
    try:
        from funding_stress_classifier import classify_funding_stress
        # Shock decomposition is not recomputed here — fx_pack left None;
        # classifier falls back to stress.detail.safe_haven.Dollar.
        funding_mode = classify_funding_stress(
            rates_context=rates_dict,
            stress_regime=stress_dict,
            credit_regime=credit_regime,
            fx_pack=None,
        )
    except Exception:
        _api._log.warning("market_context: funding_stress classify failed", exc_info=True)

    # Sector rotation read — deterministic macro→sector playbook.
    sector_rotation_block: dict | None = None
    try:
        from sector_rotation import compute_sector_rotation
        _raw = (stress_dict or {}).get("raw") or {}
        _nominal = ((rates_dict or {}).get("nominal") or {}).get("change_5d")
        _be = ((rates_dict or {}).get("breakeven_proxy") or {}).get("change_5d")
        _dxy = (((stress_dict or {}).get("detail") or {})
                .get("safe_haven") or {}).get("assets", {}).get("Dollar")
        sector_rotation_block = compute_sector_rotation(
            rates_5d_pp=_nominal,
            breakeven_5d_pp=_be,
            credit_regime=credit_regime,
            dxy_5d_pct=_dxy,
            crude_5d_pct=_raw.get("crude_5d"),
            gold_5d_pct=_raw.get("gold_5d"),
            funding_stress_mode=funding_mode,
        )
    except Exception:
        _api._log.warning("market_context: sector_rotation failed", exc_info=True)

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

    # Market-level finance playbook synthesis — the same composer the
    # analyze pipeline uses per-event, but here fed a pseudo-analysis
    # with just the macro blocks; thesis_scorecard and historical_analogs
    # are intentionally absent, so those lines degrade to "unavailable".
    playbook: dict | None = None
    try:
        from finance_playbook import compose_finance_playbook
        playbook = compose_finance_playbook({
            "regime_snapshot":     regime_vec,
            "funding_stress_mode": funding_mode,
            "sector_rotation":     sector_rotation_block,
            "credit_regime":       credit_regime,
        })
    except Exception:
        _api._log.warning("market_context: finance_playbook compose failed", exc_info=True)

    return _api._sanitize_floats(compose_market_context(
        snaps_list, stress_dict, highlights,
        rates=rates_dict, regime_vector=regime_vec,
        uncertainty_concentration=uc,
        credit_regime=credit_regime,
        funding_stress_mode=funding_mode,
        sector_rotation=sector_rotation_block,
        finance_playbook=playbook,
    ))
