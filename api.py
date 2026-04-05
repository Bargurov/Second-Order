"""
Thin FastAPI layer over the existing backend.

Run with:  uvicorn api:app --reload
"""

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Optional
import json as _json
import re
import time

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from db import (
    init_db, load_recent_events, load_event_by_id, save_event, update_review,
    find_related_events, load_news_cache, save_news_cache, find_cached_analysis,
)
from classify import classify_stage, classify_persistence
from analyze_event import analyze_event, _DEFAULT_MODEL
from market_check import market_check, followup_check, macro_snapshot, ticker_chart, ticker_info
import os
from news_sources import fetch_all, cluster_headlines

# ---------------------------------------------------------------------------
# App & startup
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Second Order API", version="0.1.0", lifespan=_lifespan)


# ---------------------------------------------------------------------------
# Two-layer news cache: in-memory (hot) + SQLite (persistent across restarts)
# ---------------------------------------------------------------------------

_NEWS_TTL_SECONDS = 300  # 5 minutes
_news_cache: dict[str, Any] = {"data": None, "ts": 0.0}


def _fetch_fresh_news() -> dict:
    """Fetch, cluster, and return a fresh news payload. Updates both caches."""
    records, feed_status = fetch_all()
    clusters = cluster_headlines(records)
    payload = {
        "clusters": clusters,
        "total_headlines": len(records),
        "feed_status": feed_status,
    }
    _news_cache["data"] = payload
    _news_cache["ts"] = time.monotonic()
    try:
        save_news_cache(payload)
    except Exception as e:
        print(f"[api] save_news_cache failed: {e}")
    return payload


def _get_news_cached() -> dict:
    """Return news from the fastest available source."""
    now = time.monotonic()
    if _news_cache["data"] is not None and (now - _news_cache["ts"]) < _NEWS_TTL_SECONDS:
        return _news_cache["data"]
    try:
        db_payload = load_news_cache(max_age_seconds=_NEWS_TTL_SECONDS)
    except Exception:
        db_payload = None
    if db_payload is not None:
        _news_cache["data"] = db_payload
        _news_cache["ts"] = now
        return db_payload
    return _fetch_fresh_news()


# ---------------------------------------------------------------------------
# Shared helpers for /analyze and /analyze/stream
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _active_model() -> str:
    """Return the model ID that analyze_event will use."""
    return os.getenv("ANTHROPIC_MODEL", _DEFAULT_MODEL)


def _build_cached_response(cached: dict, headline: str, effective_date: str) -> dict:
    """Reconstruct the full /analyze response shape from a saved event."""
    tickers = cached.get("market_tickers", [])
    return {
        "headline":    headline,
        "stage":       cached["stage"],
        "persistence": cached["persistence"],
        "analysis": {
            "what_changed":      cached.get("what_changed", ""),
            "mechanism_summary": cached.get("mechanism_summary", ""),
            "beneficiaries":     cached.get("beneficiaries", []),
            "losers":            cached.get("losers", []),
            "beneficiary_tickers": [t["symbol"] for t in tickers if t.get("role") == "beneficiary"],
            "loser_tickers":       [t["symbol"] for t in tickers if t.get("role") == "loser"],
            "assets_to_watch":   cached.get("assets_to_watch", []),
            "confidence":        cached.get("confidence", "low"),
            "transmission_chain": cached.get("transmission_chain", []),
        },
        "market": {
            "note":    cached.get("market_note", ""),
            "details": {},
            "tickers": tickers,
        },
        "is_mock":     False,
        "event_date":  effective_date,
    }


def _persist_event(
    headline: str, stage: str, persistence: str,
    analysis: dict, mkt: dict, effective_date: str,
    model: str | None = None,
) -> None:
    """Build an event record from analysis results and save to the DB."""
    event_record = {
        "timestamp":         datetime.now().isoformat(timespec="seconds"),
        "headline":          headline,
        "stage":             stage,
        "persistence":       persistence,
        "what_changed":      analysis.get("what_changed", ""),
        "mechanism_summary": analysis.get("mechanism_summary", ""),
        "beneficiaries":     analysis.get("beneficiaries", []),
        "losers":            analysis.get("losers", []),
        "assets_to_watch":   analysis.get("assets_to_watch", []),
        "confidence":        analysis.get("confidence", "low"),
        "market_note":       mkt["note"],
        "market_tickers":    mkt.get("tickers", []),
        "event_date":        effective_date,
        "notes":             "",
        "model":             model,
        "transmission_chain": analysis.get("transmission_chain", []),
    }
    try:
        save_event(event_record)
    except Exception as e:
        print(f"[api] save_event failed: {e}")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    headline: str = Field(..., min_length=1, max_length=500)
    event_date: Optional[str] = Field(
        None, pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Optional YYYY-MM-DD anchor date for market check",
    )
    event_context: Optional[str] = Field(
        None, max_length=5000,
        description="Optional multi-source context from inbox clustering",
    )


class ReviewRequest(BaseModel):
    rating: Optional[str] = Field(None, pattern=r"^(good|mixed|poor)$")
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    """Classify, analyze via LLM, and run market check for one headline."""
    headline = req.headline.strip()
    effective_date = req.event_date or datetime.now().strftime("%Y-%m-%d")
    model = _active_model()

    cached = find_cached_analysis(headline, event_date=effective_date, model=model)
    if cached is not None:
        return _build_cached_response(cached, headline, effective_date)

    stage = classify_stage(headline)
    persistence = classify_persistence(headline)
    analysis = analyze_event(headline, stage, persistence,
                             event_context=req.event_context or "")
    mock = "[mock:" in analysis.get("what_changed", "")
    mkt = market_check(
        analysis.get("beneficiary_tickers", []),
        analysis.get("loser_tickers", []),
        event_date=req.event_date,
    )

    if not mock:
        _persist_event(headline, stage, persistence, analysis, mkt,
                       effective_date, model=model)

    return {
        "headline":    headline,
        "stage":       stage,
        "persistence": persistence,
        "analysis":    analysis,
        "market":      mkt,
        "is_mock":     mock,
        "event_date":  effective_date,
    }


def _sse_event(phase: str, data: dict) -> str:
    """Format one SSE event line."""
    payload = _json.dumps({"_phase": phase, **data}, default=str)
    return f"data: {payload}\n\n"


@app.post("/analyze/stream")
def analyze_stream(req: AnalyzeRequest):
    """Progressive analysis via Server-Sent Events.

    Yields events: classify → analysis → complete.
    Cached headlines emit a single 'complete' event instantly.
    """
    headline = req.headline.strip()
    effective_date = req.event_date or datetime.now().strftime("%Y-%m-%d")
    model = _active_model()

    def generate():
        cached = find_cached_analysis(headline, event_date=effective_date, model=model)
        if cached is not None:
            yield _sse_event("complete", _build_cached_response(cached, headline, effective_date))
            return

        stage = classify_stage(headline)
        persistence = classify_persistence(headline)
        yield _sse_event("classify", {
            "headline": headline,
            "stage": stage,
            "persistence": persistence,
        })

        analysis = analyze_event(headline, stage, persistence,
                                 event_context=req.event_context or "")
        mock = "[mock:" in analysis.get("what_changed", "")
        yield _sse_event("analysis", {
            "analysis": analysis,
            "is_mock": mock,
        })

        mkt = market_check(
            analysis.get("beneficiary_tickers", []),
            analysis.get("loser_tickers", []),
            event_date=req.event_date,
        )

        if not mock:
            _persist_event(headline, stage, persistence, analysis, mkt,
                           effective_date, model=model)

        yield _sse_event("complete", {
            "headline":    headline,
            "stage":       stage,
            "persistence": persistence,
            "analysis":    analysis,
            "market":      mkt,
            "is_mock":     mock,
            "event_date":  effective_date,
        })

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/events")
def events(limit: int = 25):
    """Return recently saved events, newest first."""
    return load_recent_events(limit=min(limit, 100))


@app.patch("/events/{event_id}/review")
def review(event_id: int, req: ReviewRequest):
    """Update rating and/or notes on a saved event."""
    if req.rating is None and req.notes is None:
        raise HTTPException(400, "Provide at least one of rating or notes.")
    updated = update_review(event_id, rating=req.rating, notes=req.notes)
    if not updated:
        raise HTTPException(404, f"Event {event_id} not found.")
    return {"ok": True, "event_id": event_id}


@app.get("/events/{event_id}/related")
def related(event_id: int):
    """Return events related to the given one by headline similarity."""
    target = load_event_by_id(event_id)
    if not target:
        raise HTTPException(404, f"Event {event_id} not found.")
    return find_related_events(event_id, target["headline"])


def _backtest_one(event_id: int) -> dict:
    """Core backtest logic for a single event. Returns the result dict or None."""
    target = load_event_by_id(event_id)
    if not target:
        return {"event_id": event_id, "outcomes": [], "score": None, "error": "not found"}
    event_date = target.get("event_date")
    if not event_date:
        ts = target.get("timestamp", "")
        if ts:
            event_date = ts[:10]
    tickers = target.get("market_tickers", [])
    if not event_date or not tickers:
        return {"event_id": event_id, "outcomes": [], "score": None}
    outcomes = followup_check(tickers, event_date)
    with_dir = [o for o in outcomes if o.get("direction") is not None]
    supporting = [o for o in with_dir if "supports" in (o.get("direction") or "")]
    score = None
    if with_dir:
        score = {"supporting": len(supporting), "total": len(with_dir)}
    return {"event_id": event_id, "outcomes": outcomes, "score": score}


@app.get("/events/{event_id}/backtest")
def backtest(event_id: int):
    """Run a follow-up check on a saved event's tickers from its event date."""
    result = _backtest_one(event_id)
    if result.get("error") == "not found":
        raise HTTPException(404, f"Event {event_id} not found.")
    return result


class BatchBacktestRequest(BaseModel):
    event_ids: list[int] = Field(..., max_length=50)


@app.post("/backtest/batch")
def backtest_batch(req: BatchBacktestRequest):
    """Backtest multiple events in one request. Returns results in input order."""
    results = []
    for eid in req.event_ids:
        try:
            results.append(_backtest_one(eid))
        except Exception:
            results.append({"event_id": eid, "outcomes": [], "score": None, "error": "failed"})
    return results


class BatchMacroRequest(BaseModel):
    event_dates: list[str] = Field(..., max_length=50)


@app.post("/macro/batch")
def macro_batch(req: BatchMacroRequest):
    """Fetch macro context for multiple dates. Returns {date: entries} dict."""
    result: dict[str, list] = {}
    for d in req.event_dates:
        if d in result:
            continue  # dedup
        try:
            result[d] = macro_snapshot(event_date=d)
        except Exception:
            result[d] = []
    return result


@app.get("/macro")
def macro(
    event_date: Optional[str] = Query(
        None, pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Optional YYYY-MM-DD date for anchored macro context",
    ),
):
    """Return a compact macro context strip (DXY, yields, VIX, oil)."""
    return macro_snapshot(event_date=event_date)


@app.get("/ticker/{symbol}/chart")
def get_ticker_chart(
    symbol: str,
    event_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    """Return 60-day daily closes centered on event_date for charting."""
    return ticker_chart(symbol, event_date)


@app.get("/ticker/{symbol}/info")
def get_ticker_info(symbol: str):
    """Return compact company info (name, sector, industry, mkt cap, avg vol)."""
    return ticker_info(symbol)


@app.get("/ticker/{symbol}/headlines")
def get_ticker_headlines(symbol: str, limit: int = 5):
    """Return recent news headlines mentioning this ticker or its company name."""
    info = ticker_info(symbol)
    name = info.get("name") or ""
    sym_upper = symbol.upper()

    # Search terms: the ticker symbol itself + first word of company name if long enough
    terms = [sym_upper]
    if name and len(name) > 3:
        # Use the first substantive word (skip "The", "Inc", etc.)
        for word in name.split():
            if len(word) > 3 and word not in ("The", "Inc.", "Corp.", "Ltd.", "Inc", "Corp", "Ltd"):
                terms.append(word)
                break

    try:
        data = _get_news_cached()
    except Exception:
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


@app.get("/market-movers")
def market_movers(limit: int = 5):
    """Return saved events with confirmed market moves, ranked by impact.

    Uses the market data already saved at analysis time (return_5d, direction_tag,
    spark) — not followup_check, which requires forward trading days.

    Qualifying rules:
    - Event has market_tickers with return data
    - At least one ticker with abs(5d return) >= 3%
    - Ranked by impact = max_abs_move * (1 + hypothesis_support_ratio)
    """
    events = load_recent_events(limit=50)
    scored: list[dict] = []

    for ev in events:
        tickers = ev.get("market_tickers", [])
        if not tickers:
            continue

        # Use saved return_5d from analysis time
        big_moves = [
            t for t in tickers
            if t.get("return_5d") is not None and abs(t["return_5d"]) >= 3.0
        ]
        if not big_moves:
            continue

        # Hypothesis support from saved direction_tag
        with_dir = [t for t in tickers if t.get("direction_tag") is not None]
        supporting = [
            t for t in with_dir
            if "supports" in (t.get("direction_tag") or "")
        ]
        support_ratio = len(supporting) / len(with_dir) if with_dir else 0.0

        max_move = max(abs(t["return_5d"]) for t in big_moves)
        impact = max_move * (1.0 + support_ratio)

        # Top 3 tickers by absolute move
        big_moves.sort(key=lambda t: abs(t.get("return_5d") or 0), reverse=True)
        ticker_summaries = [
            {
                "symbol": t.get("symbol", "?"),
                "role": t.get("role", "?"),
                "return_5d": t.get("return_5d"),
                "direction": t.get("direction_tag"),
                "spark": t.get("spark", []),
            }
            for t in big_moves[:3]
        ]

        scored.append({
            "event_id": ev["id"],
            "headline": ev["headline"],
            "mechanism_summary": ev.get("mechanism_summary", ""),
            "event_date": ev.get("event_date", ""),
            "stage": ev.get("stage", ""),
            "persistence": ev.get("persistence", ""),
            "impact": round(impact, 2),
            "support_ratio": round(support_ratio, 2),
            "tickers": ticker_summaries,
        })

    scored.sort(key=lambda x: x["impact"], reverse=True)
    return scored[:limit]


@app.get("/news")
def news():
    """Fetch headlines from all sources, cluster, and return (5-min cache)."""
    return _get_news_cached()


@app.post("/news/refresh")
def news_refresh():
    """Force a fresh fetch, bypassing both caches."""
    return _fetch_fresh_news()
