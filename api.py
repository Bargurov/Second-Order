"""
Thin FastAPI layer over the existing backend.

Run with:  uvicorn api:app --reload
"""

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from db import init_db, load_recent_events, save_event, update_review
from classify import classify_stage, classify_persistence
from analyze_event import analyze_event
from market_check import market_check
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
# Request / response models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    headline: str = Field(..., min_length=1, max_length=500)
    event_date: Optional[str] = Field(
        None, pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Optional YYYY-MM-DD anchor date for market check",
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
    stage = classify_stage(headline)
    persistence = classify_persistence(headline)
    analysis = analyze_event(headline, stage, persistence)
    mock = "[mock:" in analysis.get("what_changed", "")
    mkt = market_check(
        analysis.get("beneficiary_tickers", []),
        analysis.get("loser_tickers", []),
        event_date=req.event_date,
    )

    # Persist unless it's a mock/fallback response.
    if not mock:
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
            "event_date":        req.event_date,
            "notes":             "",
        }
        try:
            save_event(event_record)
        except Exception:
            pass  # DB save is best-effort

    return {
        "headline":    headline,
        "stage":       stage,
        "persistence": persistence,
        "analysis":    analysis,
        "market":      mkt,
        "is_mock":     mock,
        "event_date":  req.event_date,
    }


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


@app.get("/news")
def news():
    """Fetch headlines from all sources, cluster, and return."""
    records = fetch_all()
    clusters = cluster_headlines(records)
    return {
        "clusters": clusters,
        "total_headlines": len(records),
    }
