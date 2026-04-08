"""
Thin FastAPI layer over the existing backend.

Run with:  uvicorn api:app --reload
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Optional
import json as _json
import logging
import re
import time

# Configure news/cluster loggers to emit at INFO under uvicorn.
# Attach a stderr handler so messages appear in the console even when
# the root logger has no handler configured (common under uvicorn).
_so_handler = logging.StreamHandler()
_so_handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
for _ln in ("second_order.news", "second_order.cluster"):
    _lgr = logging.getLogger(_ln)
    _lgr.setLevel(logging.INFO)
    if not _lgr.handlers:
        _lgr.addHandler(_so_handler)

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from db import (
    init_db, load_recent_events, load_event_by_id, save_event, update_review,
    find_related_events, load_news_cache, save_news_cache, find_cached_analysis,
    load_low_signal_headlines, find_historical_analogs,
)
from classify import classify_stage, classify_persistence
from analyze_event import analyze_event, _DEFAULT_MODEL, _normalize_if_persists, _normalize_currency_channel
from market_check import (
    market_check, followup_check, macro_snapshot, ticker_chart, ticker_info,
    compute_stress_regime, compute_rates_context, classify_decay,
    classify_policy_sensitivity,
    classify_inventory_context,
)
from market_check_freshness import refresh_market_for_saved_event
import movers_cache
from real_yield_context import build_real_yield_context
from policy_constraint import compute_policy_constraint
from shock_decomposition import compute_shock_decomposition
from reaction_function_divergence import compute_reaction_function_divergence
from regime_vector import build_regime_vector
from surprise_vs_anticipation import compute_surprise_vs_anticipation
from terms_of_trade import compute_terms_of_trade
from reserve_stress_overlay import compute_reserve_stress
import os
from news_sources import fetch_all, cluster_headlines

_log = logging.getLogger("second_order.api")

# ---------------------------------------------------------------------------
# App & startup
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    # Optional background snapshot refresh — gated by env var so the test
    # suite (which uses TestClient) does not spin up a background thread.
    if os.environ.get("MARKET_SNAPSHOTS_ENABLED", "").lower() in ("1", "true", "yes"):
        from market_snapshots import start_background_refresh
        try:
            interval = int(os.environ.get("MARKET_SNAPSHOTS_INTERVAL", "60"))
        except ValueError:
            interval = 60
        start_background_refresh(interval=interval)
    yield
    # Stop the thread cleanly on shutdown (no-op if it never started)
    from market_snapshots import stop_background_refresh
    stop_background_refresh()


app = FastAPI(title="Second Order API", version="0.1.0", lifespan=_lifespan)


# ---------------------------------------------------------------------------
# Two-layer news cache: in-memory (hot) + SQLite (persistent across restarts)
# ---------------------------------------------------------------------------

_NEWS_TTL_SECONDS = 300  # 5 minutes
_news_cache: dict[str, Any] = {"data": None, "ts": 0.0}


_api_log = logging.getLogger("second_order.news")


def _fetch_fresh_news() -> dict:
    """Fetch, cluster, and return a fresh news payload. Updates both caches.

    The clustering step runs through the persisted ``news_cluster_store``
    so only genuinely new (unassigned) headlines are reclustered; every
    already-seen headline just updates the last-seen timestamp on its
    existing cluster.  A cold DB bootstraps cleanly because the store's
    first call finds zero assignments and clusters the full batch once.
    """
    import news_cluster_store

    t0 = time.monotonic()
    records, feed_status = fetch_all()

    # The incremental store delegates to api.cluster_headlines as its
    # default ``cluster_fn``, which keeps the /news test mocks working.
    # We pass it through explicitly so the api-module-level patch is
    # visible inside the store.
    try:
        clusters = news_cluster_store.refresh_clusters(
            records, cluster_fn=cluster_headlines,
        )
    except Exception:
        _log.warning(
            "news_cluster_store.refresh_clusters failed; "
            "falling back to full recluster",
            exc_info=True,
        )
        clusters = cluster_headlines(records)

    elapsed = time.monotonic() - t0

    ok_feeds = sum(1 for f in feed_status if f.get("ok"))
    fail_feeds = sum(1 for f in feed_status if not f.get("ok"))
    _api_log.info(
        "[refresh] done in %.1fs — %d feeds OK, %d failed, %d headlines → %d clusters",
        elapsed, ok_feeds, fail_feeds, len(records), len(clusters),
    )

    # Tag clusters whose headline was previously analyzed as low_signal
    low_headlines = load_low_signal_headlines()
    for c in clusters:
        c["low_signal"] = c.get("headline", "") in low_headlines

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
        _log.warning("load_news_cache failed, falling back to fresh fetch", exc_info=True)
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


def _classify_for_effective_date(
    effective_date: str, *, force: bool = False,
) -> dict:
    """Classify a not-yet-saved /analyze request using only its effective date.

    Fresh /analyze and /analyze/stream calls don't have a persisted
    event row yet, but the cached path returns a ``freshness`` block
    built via ``event_age_policy.classify_event_age`` off the stored
    row.  To keep the fresh and cached response shapes identical we
    build the same classification from a synthetic event dict that
    only carries ``event_date`` and ``timestamp``.
    """
    import event_age_policy

    synthetic = {
        "event_date": effective_date,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    return event_age_policy.classify_event_age(synthetic, force=force)


def _freshness_payload(classification: dict) -> dict:
    """Project a classify_event_age dict into the /analyze freshness shape."""
    return {
        "bucket":         classification.get("bucket"),
        "natural_bucket": classification.get("natural_bucket"),
        "event_age_days": classification.get("event_age_days"),
        "is_frozen":      classification.get("is_frozen", False),
        "force_bypassed": classification.get("force_bypassed", False),
    }


def _augment_market_freshness(
    mkt: dict,
    classification: dict,
    *,
    last_market_check_at: Optional[str] = None,
) -> dict:
    """Return ``mkt`` enriched with the same freshness fields the cached
    response writes.

    * ``last_market_check_at``: ISO timestamp of the refresh.  On a
      fresh analyse this is "now" — market_check has just run.
    * ``market_check_staleness``: label mirrors the
      ``market_check_freshness`` taxonomy.  A fresh /analyze is always
      "fresh" because the ticker data was just fetched.
    * ``event_age_days``: straight from the classification.

    The helper never mutates the input — returns a shallow copy with
    the extra keys merged in.
    """
    out = dict(mkt or {})
    out["last_market_check_at"] = (
        last_market_check_at
        or datetime.now().replace(microsecond=0).isoformat()
    )
    # The fresh path has just fetched the returns — they are, by
    # definition, fresh regardless of bucket.
    out.setdefault("market_check_staleness", "fresh")
    out["event_age_days"] = classification.get("event_age_days")
    return out


def _build_cached_response(
    cached: dict,
    headline: str,
    effective_date: str,
    *,
    force: bool = False,
) -> dict:
    """Reconstruct the full /analyze response shape from a saved event.

    Recomputes inventory_context and policy_sensitivity on-the-fly if
    the cached row is missing them (pre-migration data).  The market
    block is routed through ``refresh_market_for_saved_event`` so stale
    rows pick up fresh returns via the SQLite-cached provider path.

    Event-age-aware freeze policy
    -----------------------------
    For events past the frozen cutoff (> 30d old), the live-macro
    overlays — real_yield_context, policy_constraint, shock_decomposition,
    reaction_function_divergence, surprise_vs_anticipation, terms_of_trade,
    regime_vector — are NOT recomputed against the current macro tape.
    Frozen events are archived: the historical macro context they were
    analysed under is what matters, and dragging the current backdrop
    onto a 6-month-old event would misrepresent it.  We surface stored
    values when they exist on the row, otherwise empty dicts so the
    response shape stays stable.

    Pass ``force=True`` to bypass the freeze and run the full macro
    recompute even for frozen events (used by archive-review flows).
    """
    import event_age_policy

    # Classify the event's age once and route every recompute branch
    # off the resulting bucket.  Legacy / hot / warm / stable events
    # all do the full live recompute; only frozen events skip it.
    # The cached path operates on a persisted row, so the classifier
    # reads the event_date / timestamp straight from it — we don't
    # need the effective_date synthetic shim used by the fresh path.
    age_classification = event_age_policy.classify_event_age(
        cached, force=force,
    )
    is_frozen_archive = age_classification["natural_bucket"] == "frozen" and not force

    # Event-age-aware freshness: returns the stored tickers for fresh /
    # frozen rows, runs followup_check / market_check for stale ones, and
    # persists the refreshed data back onto the saved event.  We pass the
    # api-level function references so test suites patching
    # ``api.followup_check`` or ``api.market_check`` still see their mocks
    # land inside the freshness refresh path.
    try:
        market_block = refresh_market_for_saved_event(
            cached,
            force=force,
            followup_check_fn=followup_check,
            market_check_fn=market_check,
        )
    except Exception:
        _log.warning(
            "refresh_market_for_saved_event failed; falling back to stored payload",
            exc_info=True,
        )
        market_block = {
            "tickers": cached.get("market_tickers", []),
            "note": cached.get("market_note", ""),
            "details": {},
            "last_market_check_at": cached.get("last_market_check_at"),
            "market_check_staleness": "error",
        }
    tickers = market_block.get("tickers", [])

    mech_text = f"{cached.get('what_changed', '')} {cached.get('mechanism_summary', '')}"
    inv_text = f"{headline} {mech_text}"

    if is_frozen_archive:
        # ----- Frozen-archive branch: reuse stored values, skip recomputes ---
        inventory_context = cached.get("inventory_context") or {}
        policy_sensitivity = cached.get("policy_sensitivity") or {}
        real_yield_ctx = cached.get("real_yield_context") or {}
        policy_constraint_ctx = cached.get("policy_constraint") or {}
        shock_decomp_ctx = cached.get("shock_decomposition") or {}
        reaction_div_ctx = cached.get("reaction_function_divergence") or {}
        surprise_ctx = cached.get("surprise_vs_anticipation") or {}
        terms_of_trade_ctx = cached.get("terms_of_trade") or {}
        reserve_stress_ctx = cached.get("reserve_stress") or {}
        # build_regime_vector against None inputs returns an "unavailable"
        # marker; that's the right thing for a frozen event whose macro
        # backdrop is no longer the relevant live state.
        try:
            current_regime_vec = build_regime_vector(None, None, None)
        except Exception:
            current_regime_vec = None
    else:
        # ----- Live branch: recompute everything against the current tape --
        inventory_context = cached.get("inventory_context") or {}
        if not inventory_context:
            try:
                inventory_context = classify_inventory_context(inv_text)
            except Exception:
                _log.warning("classify_inventory_context failed (cached rebuild)", exc_info=True)
                inventory_context = {}

        policy_sensitivity = cached.get("policy_sensitivity") or {}
        real_yield_ctx = {}
        policy_constraint_ctx = {}
        rates_live: Optional[dict] = None
        stress_live: Optional[dict] = None
        try:
            rates_live = compute_rates_context()
            if not policy_sensitivity:
                policy_sensitivity = classify_policy_sensitivity(rates_live["regime"], mech_text)
            real_yield_ctx = build_real_yield_context(headline, mech_text, rates_live)
        except Exception:
            _log.warning("rates/real-yield context failed (cached rebuild)", exc_info=True)
            if not policy_sensitivity:
                policy_sensitivity = {}
            real_yield_ctx = build_real_yield_context(headline, mech_text, None)
        try:
            stress_live = compute_stress_regime()
        except Exception:
            _log.warning("stress_regime failed (cached rebuild)", exc_info=True)
            stress_live = None
        try:
            policy_constraint_ctx = compute_policy_constraint(
                headline, mech_text, rates_live, stress_live, snapshots=None,
            )
        except Exception:
            _log.warning("policy_constraint failed (cached rebuild)", exc_info=True)
            policy_constraint_ctx = {}
        try:
            shock_decomp_ctx = compute_shock_decomposition(
                rates_live, stress_live, snapshots=None,
            )
        except Exception:
            _log.warning("shock_decomposition failed (cached rebuild)", exc_info=True)
            shock_decomp_ctx = {}
        try:
            reaction_div_ctx = compute_reaction_function_divergence(
                headline, mech_text, rates_live, stress_live, snapshots=None,
            )
        except Exception:
            _log.warning("reaction_function_divergence failed (cached rebuild)", exc_info=True)
            reaction_div_ctx = {}

        try:
            current_regime_vec = build_regime_vector(rates_live, stress_live, None)
        except Exception:
            _log.warning("regime_vector failed (cached rebuild)", exc_info=True)
            current_regime_vec = None

        try:
            surprise_ctx = compute_surprise_vs_anticipation(
                cached.get("stage", ""),
                tickers=tickers,
                stress_regime=stress_live,
            )
        except Exception:
            _log.warning("surprise_vs_anticipation failed (cached rebuild)", exc_info=True)
            surprise_ctx = {}

        try:
            terms_of_trade_ctx = compute_terms_of_trade(
                headline,
                mech_text,
                inventory_context=inventory_context,
                snapshots=None,
                stress_regime=stress_live,
            )
        except Exception:
            _log.warning("terms_of_trade failed (cached rebuild)", exc_info=True)
            terms_of_trade_ctx = {}

        # Reserve-stress overlay — pure composer over the terms-of-trade,
        # rates and stress blocks we already have.  Runs last because it
        # reads from all three.
        try:
            reserve_stress_ctx = compute_reserve_stress(
                headline,
                mech_text,
                terms_of_trade=terms_of_trade_ctx,
                rates_context=rates_live,
                stress_regime=stress_live,
            )
        except Exception:
            _log.warning("reserve_stress failed (cached rebuild)", exc_info=True)
            reserve_stress_ctx = {}

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
            "if_persists": cached.get("if_persists", {}),
            "currency_channel": cached.get("currency_channel", {}),
            "policy_sensitivity": policy_sensitivity,
            "inventory_context": inventory_context,
            "real_yield_context": real_yield_ctx,
            "policy_constraint": policy_constraint_ctx,
            "shock_decomposition": shock_decomp_ctx,
            "reaction_function_divergence": reaction_div_ctx,
            "surprise_vs_anticipation": surprise_ctx,
            "terms_of_trade": terms_of_trade_ctx,
            "reserve_stress": reserve_stress_ctx,
            "historical_analogs": find_historical_analogs(
                headline,
                mechanism=cached.get("mechanism_summary", ""),
                stage=cached.get("stage", ""),
                persistence=cached.get("persistence", ""),
                exclude_headline=headline,
                current_regime_vector=current_regime_vec,
            ),
        },
        "market": {
            "note":    market_block.get("note", cached.get("market_note", "")),
            "details": {},
            "tickers": tickers,
            # Small freshness field — lets the frontend show a "refreshed
            # N minutes ago" indicator without adding new endpoints.  All
            # keys are optional and default to reasonable fallbacks.
            "last_market_check_at": market_block.get("last_market_check_at"),
            "market_check_staleness": market_block.get("market_check_staleness"),
            "event_age_days": market_block.get("event_age_days"),
        },
        "freshness": _freshness_payload(age_classification),
        "is_mock":     False,
        "event_date":  effective_date,
    }


def _is_low_signal(analysis: dict) -> bool:
    """Detect events with insufficient analytical content.

    An event is low-signal when ALL of these are true:
      - confidence is "low" OR mechanism contains "insufficient evidence"
      - no real mechanism (empty or "insufficient evidence")
      - no beneficiaries
      - no losers
      - no transmission chain
    """
    mech = (analysis.get("mechanism_summary") or "").strip()
    confidence = (analysis.get("confidence") or "").lower()
    has_insufficient = "insufficient evidence" in mech.lower()
    has_no_mechanism = not mech or has_insufficient

    if confidence != "low" and not has_insufficient:
        return False

    bens = analysis.get("beneficiaries", [])
    losers = analysis.get("losers", [])
    chain = analysis.get("transmission_chain", [])
    return has_no_mechanism and len(bens) == 0 and len(losers) == 0 and len(chain) == 0


def _persist_event(
    headline: str, stage: str, persistence: str,
    analysis: dict, mkt: dict, effective_date: str,
    model: str | None = None,
) -> None:
    """Build an event record from analysis results and save to the DB.

    Every macro overlay block the /analyze pipeline produces is
    persisted so the frozen-cached response path can surface the
    exact macro snapshot the event was analysed under — without
    re-running live-macro computations against the current tape.
    """
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
        "if_persists": analysis.get("if_persists", {}),
        "currency_channel": analysis.get("currency_channel", {}),
        "policy_sensitivity": analysis.get("policy_sensitivity", {}),
        "inventory_context": analysis.get("inventory_context", {}),
        "regime_snapshot": analysis.get("regime_snapshot", {}),
        "low_signal": 1 if _is_low_signal(analysis) else 0,
        # Macro overlays — persisted for the frozen-archive reuse path.
        "real_yield_context":           analysis.get("real_yield_context", {}),
        "policy_constraint":            analysis.get("policy_constraint", {}),
        "shock_decomposition":          analysis.get("shock_decomposition", {}),
        "reaction_function_divergence": analysis.get("reaction_function_divergence", {}),
        "surprise_vs_anticipation":     analysis.get("surprise_vs_anticipation", {}),
        "terms_of_trade":               analysis.get("terms_of_trade", {}),
        "reserve_stress":               analysis.get("reserve_stress", {}),
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
    force: bool = Field(
        False,
        description=(
            "Bypass the event-age freeze policy on cached responses. "
            "Use when an archive review needs the full live macro recompute."
        ),
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
        return _build_cached_response(
            cached, headline, effective_date, force=req.force,
        )

    stage = classify_stage(headline)
    persistence = classify_persistence(headline)
    analysis = analyze_event(headline, stage, persistence,
                             event_context=req.event_context or "")
    analysis["if_persists"] = _normalize_if_persists(analysis.get("if_persists"))
    analysis["currency_channel"] = _normalize_currency_channel(analysis.get("currency_channel"))

    # Compute policy sensitivity + real-yield context + policy constraint
    # from a single rates fetch and a single stress fetch.
    mech_text = f"{analysis.get('what_changed', '')} {analysis.get('mechanism_summary', '')}"
    rates_for_overlays: Optional[dict] = None
    stress_for_overlays: Optional[dict] = None
    try:
        rates_for_overlays = compute_rates_context()
        analysis["policy_sensitivity"] = classify_policy_sensitivity(
            rates_for_overlays["regime"], mech_text,
        )
    except Exception:
        _log.warning("policy_sensitivity computation failed", exc_info=True)
        analysis["policy_sensitivity"] = {}

    try:
        analysis["real_yield_context"] = build_real_yield_context(
            headline, mech_text, rates_for_overlays,
        )
    except Exception:
        _log.warning("real_yield_context computation failed", exc_info=True)
        analysis["real_yield_context"] = {}

    try:
        stress_for_overlays = compute_stress_regime()
    except Exception:
        _log.warning("stress_regime computation failed (analyze)", exc_info=True)
        stress_for_overlays = None

    try:
        analysis["policy_constraint"] = compute_policy_constraint(
            headline, mech_text, rates_for_overlays, stress_for_overlays,
            snapshots=None,
        )
    except Exception:
        _log.warning("policy_constraint computation failed", exc_info=True)
        analysis["policy_constraint"] = {}

    try:
        analysis["shock_decomposition"] = compute_shock_decomposition(
            rates_for_overlays, stress_for_overlays, snapshots=None,
        )
    except Exception:
        _log.warning("shock_decomposition computation failed", exc_info=True)
        analysis["shock_decomposition"] = {}

    try:
        analysis["reaction_function_divergence"] = compute_reaction_function_divergence(
            headline, mech_text, rates_for_overlays, stress_for_overlays,
            snapshots=None,
        )
    except Exception:
        _log.warning("reaction_function_divergence computation failed", exc_info=True)
        analysis["reaction_function_divergence"] = {}

    # Build the current regime vector.  Reused below for analog rerank
    # and persisted on the saved event so future analog searches can
    # diff against the regime backdrop at the time of analysis.
    try:
        current_regime_vec = build_regime_vector(
            rates_for_overlays, stress_for_overlays, None,
        )
    except Exception:
        _log.warning("regime_vector computation failed", exc_info=True)
        current_regime_vec = None
    analysis["regime_snapshot"] = current_regime_vec or {}

    # Compute inventory / supply context — include headline for keyword matching
    # so commodity events are detected even when mechanism text is sparse/mock
    inv_text = f"{headline} {mech_text}"
    try:
        analysis["inventory_context"] = classify_inventory_context(inv_text)
    except Exception:
        _log.warning("inventory_context computation failed", exc_info=True)
        analysis["inventory_context"] = {}

    # Historical analogs from archive — rerank by regime when the current
    # macro backdrop is usable; otherwise fall through to topic-only.
    analysis["historical_analogs"] = find_historical_analogs(
        headline,
        mechanism=analysis.get("mechanism_summary", ""),
        stage=stage,
        persistence=persistence,
        exclude_headline=headline,
        current_regime_vector=current_regime_vec,
    )

    mock = "[mock:" in analysis.get("what_changed", "")
    mkt = market_check(
        analysis.get("beneficiary_tickers", []),
        analysis.get("loser_tickers", []),
        event_date=req.event_date,
    )

    # Surprise vs Anticipation decomposition needs the realised ticker
    # returns, so it runs AFTER market_check.  Stage and stress were
    # fetched upstream and are reused here — no extra I/O.
    try:
        analysis["surprise_vs_anticipation"] = compute_surprise_vs_anticipation(
            stage,
            tickers=mkt.get("tickers", []),
            stress_regime=stress_for_overlays,
        )
    except Exception:
        _log.warning("surprise_vs_anticipation computation failed", exc_info=True)
        analysis["surprise_vs_anticipation"] = {}

    # Terms-of-Trade / external vulnerability layer.  Pure composer that
    # reuses the already-computed inventory_context + stress_regime; no
    # new I/O introduced.
    try:
        analysis["terms_of_trade"] = compute_terms_of_trade(
            headline,
            mech_text,
            inventory_context=analysis.get("inventory_context", {}),
            snapshots=None,
            stress_regime=stress_for_overlays,
        )
    except Exception:
        _log.warning("terms_of_trade computation failed", exc_info=True)
        analysis["terms_of_trade"] = {}

    # Current-account + FX-reserve stress overlay.  Pure composer over
    # the terms-of-trade block, the rates context and the stress regime
    # — reuses everything already computed, no new I/O.
    try:
        analysis["reserve_stress"] = compute_reserve_stress(
            headline,
            mech_text,
            terms_of_trade=analysis.get("terms_of_trade", {}),
            rates_context=rates_for_overlays,
            stress_regime=stress_for_overlays,
        )
    except Exception:
        _log.warning("reserve_stress computation failed", exc_info=True)
        analysis["reserve_stress"] = {}

    if not mock:
        _persist_event(headline, stage, persistence, analysis, mkt,
                       effective_date, model=model)

    # Parity with the cached-response path: build the same freshness
    # classification and market-freshness metadata.  Fresh analyses
    # are never forced (nothing to bypass yet) so force=False.
    age_classification = _classify_for_effective_date(
        effective_date, force=False,
    )
    mkt_with_freshness = _augment_market_freshness(mkt, age_classification)

    return {
        "headline":    headline,
        "stage":       stage,
        "persistence": persistence,
        "analysis":    analysis,
        "market":      mkt_with_freshness,
        "freshness":   _freshness_payload(age_classification),
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
            yield _sse_event(
                "complete",
                _build_cached_response(cached, headline, effective_date, force=req.force),
            )
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
        analysis["if_persists"] = _normalize_if_persists(analysis.get("if_persists"))
        analysis["currency_channel"] = _normalize_currency_channel(analysis.get("currency_channel"))
        mech_text = f"{analysis.get('what_changed', '')} {analysis.get('mechanism_summary', '')}"
        rates_for_overlays: Optional[dict] = None
        stress_for_overlays: Optional[dict] = None
        try:
            rates_for_overlays = compute_rates_context()
            analysis["policy_sensitivity"] = classify_policy_sensitivity(
                rates_for_overlays["regime"], mech_text,
            )
        except Exception:
            _log.warning("policy_sensitivity failed (stream)", exc_info=True)
            analysis["policy_sensitivity"] = {}
        try:
            analysis["real_yield_context"] = build_real_yield_context(
                headline, mech_text, rates_for_overlays,
            )
        except Exception:
            _log.warning("real_yield_context failed (stream)", exc_info=True)
            analysis["real_yield_context"] = {}
        try:
            stress_for_overlays = compute_stress_regime()
        except Exception:
            _log.warning("stress_regime failed (stream)", exc_info=True)
            stress_for_overlays = None
        try:
            analysis["policy_constraint"] = compute_policy_constraint(
                headline, mech_text, rates_for_overlays, stress_for_overlays,
                snapshots=None,
            )
        except Exception:
            _log.warning("policy_constraint failed (stream)", exc_info=True)
            analysis["policy_constraint"] = {}
        try:
            analysis["shock_decomposition"] = compute_shock_decomposition(
                rates_for_overlays, stress_for_overlays, snapshots=None,
            )
        except Exception:
            _log.warning("shock_decomposition failed (stream)", exc_info=True)
            analysis["shock_decomposition"] = {}
        try:
            analysis["reaction_function_divergence"] = compute_reaction_function_divergence(
                headline, mech_text, rates_for_overlays, stress_for_overlays,
                snapshots=None,
            )
        except Exception:
            _log.warning("reaction_function_divergence failed (stream)", exc_info=True)
            analysis["reaction_function_divergence"] = {}
        try:
            current_regime_vec = build_regime_vector(
                rates_for_overlays, stress_for_overlays, None,
            )
        except Exception:
            _log.warning("regime_vector failed (stream)", exc_info=True)
            current_regime_vec = None
        analysis["regime_snapshot"] = current_regime_vec or {}
        inv_text = f"{headline} {mech_text}"
        try:
            analysis["inventory_context"] = classify_inventory_context(inv_text)
        except Exception:
            _log.warning("inventory_context failed (stream)", exc_info=True)
            analysis["inventory_context"] = {}
        analysis["historical_analogs"] = find_historical_analogs(
            headline,
            mechanism=analysis.get("mechanism_summary", ""),
            stage=stage,
            persistence=persistence,
            exclude_headline=headline,
            current_regime_vector=current_regime_vec,
        )
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

        # Surprise vs Anticipation needs the realised ticker returns —
        # runs after market_check but reuses the stage + stress already
        # computed upstream.  Attach to analysis so it rides through on
        # the 'complete' frame without a new SSE phase.
        try:
            analysis["surprise_vs_anticipation"] = compute_surprise_vs_anticipation(
                stage,
                tickers=mkt.get("tickers", []),
                stress_regime=stress_for_overlays,
            )
        except Exception:
            _log.warning("surprise_vs_anticipation failed (stream)", exc_info=True)
            analysis["surprise_vs_anticipation"] = {}

        try:
            analysis["terms_of_trade"] = compute_terms_of_trade(
                headline,
                mech_text,
                inventory_context=analysis.get("inventory_context", {}),
                snapshots=None,
                stress_regime=stress_for_overlays,
            )
        except Exception:
            _log.warning("terms_of_trade failed (stream)", exc_info=True)
            analysis["terms_of_trade"] = {}

        try:
            analysis["reserve_stress"] = compute_reserve_stress(
                headline,
                mech_text,
                terms_of_trade=analysis.get("terms_of_trade", {}),
                rates_context=rates_for_overlays,
                stress_regime=stress_for_overlays,
            )
        except Exception:
            _log.warning("reserve_stress failed (stream)", exc_info=True)
            analysis["reserve_stress"] = {}

        if not mock:
            _persist_event(headline, stage, persistence, analysis, mkt,
                           effective_date, model=model)

        age_classification = _classify_for_effective_date(
            effective_date, force=False,
        )
        mkt_with_freshness = _augment_market_freshness(mkt, age_classification)

        yield _sse_event("complete", {
            "headline":    headline,
            "stage":       stage,
            "persistence": persistence,
            "analysis":    analysis,
            "market":      mkt_with_freshness,
            "freshness":   _freshness_payload(age_classification),
            "is_mock":     mock,
            "event_date":  effective_date,
        })

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/events")
def events(limit: int = 25):
    """Return recently saved events, newest first."""
    return load_recent_events(limit=min(limit, 100))


@app.get("/events/export")
def events_export(
    format: str = Query("json", pattern="^(json|csv)$"),
    limit: int = Query(10000, ge=1, le=100000),
):
    """Export the saved event archive as JSON or CSV.

    Fields exported cover everything useful for research/review: analysis
    text, classification, stored labels (rating, notes, low_signal, model),
    the full ``market_tickers`` payload, and a small derived
    ``follow_through`` block (best 5d/20d return by magnitude) sourced from
    the same tickers so no new market pipeline is needed.

    Empty archives return a well-formed empty payload — never 404.
    """
    from events_export import (
        build_csv_export,
        build_json_export,
        load_events_for_export,
    )

    evs = load_events_for_export(limit=limit)
    if format == "csv":
        body = build_csv_export(evs)
        return Response(
            content=body,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="events_export.csv"',
            },
        )
    return build_json_export(evs)


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


def _backtest_one(event_id: int, force: bool = False) -> dict:
    """Core backtest logic for a single event. Returns the result dict or None.

    Honours the event-age-aware freshness rule: rows whose last market
    check is still within the refresh window reuse the persisted tickers
    instead of re-pulling forward returns.  ``force=True`` bypasses the
    frozen cutoff (> 30 days) so archive reviews can still request fresh
    numbers on demand.
    """
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

    # Resolve the event_date onto the dict we hand to the freshness
    # layer so rows that fall back to timestamp still take the
    # followup_check path instead of rolling market_check.
    target_for_refresh = dict(target)
    target_for_refresh["event_date"] = event_date

    # Route through the freshness layer.  For fresh/frozen rows this is
    # a pure read of the stored returns; for stale rows it re-runs
    # followup_check via the SQLite price cache and persists the result.
    # Inject the api-level function references so test patches land.
    try:
        market_block = refresh_market_for_saved_event(
            target_for_refresh,
            force=force,
            followup_check_fn=followup_check,
            market_check_fn=market_check,
        )
    except Exception:
        _log.warning(
            "backtest: freshness refresh failed for event %d; "
            "falling back to direct followup_check", event_id, exc_info=True,
        )
        market_block = None

    if market_block is not None:
        refreshed_tickers = market_block.get("tickers") or tickers
        outcomes: list[dict] = []
        for t in refreshed_tickers:
            symbol = t.get("symbol")
            if not symbol:
                continue
            outcomes.append({
                "symbol": symbol,
                "role": t.get("role", "beneficiary"),
                "return_1d": t.get("return_1d"),
                "return_5d": t.get("return_5d"),
                "return_20d": t.get("return_20d"),
                "direction": t.get("direction_tag"),
                "anchor_date": t.get("anchor_date"),
            })
    else:
        outcomes = followup_check(tickers, event_date)

    with_dir = [o for o in outcomes if o.get("direction") is not None]
    supporting = [o for o in with_dir if "supports" in (o.get("direction") or "")]
    score = None
    if with_dir:
        score = {"supporting": len(supporting), "total": len(with_dir)}
    result = {"event_id": event_id, "outcomes": outcomes, "score": score}
    if market_block is not None:
        result["market_check_staleness"] = market_block.get("market_check_staleness")
        result["last_market_check_at"] = market_block.get("last_market_check_at")
    return result


@app.get("/events/{event_id}/backtest")
def backtest(
    event_id: int,
    force: bool = Query(
        False,
        description="Bypass the frozen-age cutoff and force a fresh refresh.",
    ),
):
    """Run a follow-up check on a saved event's tickers from its event date.

    Honours event-age-aware freshness: a fresh row reuses the persisted
    numbers instead of re-pulling the provider.  Pass ``force=1`` to force
    a refresh on events past the frozen cutoff (> 30 days old).
    """
    result = _backtest_one(event_id, force=force)
    if result.get("error") == "not found":
        raise HTTPException(404, f"Event {event_id} not found.")
    return result


class BatchBacktestRequest(BaseModel):
    event_ids: list[int] = Field(..., max_length=50)
    force: bool = Field(
        False,
        description="Bypass the frozen-age cutoff and force a refresh on every row.",
    )


@app.post("/backtest/batch")
def backtest_batch(req: BatchBacktestRequest):
    """Backtest multiple events in one request. Returns results in input order.

    Honours event-age-aware freshness per row: recent rows refresh on the
    4h rule, older rows on the 24h rule, > 30-day-old rows are frozen
    unless ``force=True`` is set on the request body.
    """
    results = []
    for eid in req.event_ids:
        try:
            results.append(_backtest_one(eid, force=req.force))
        except Exception:
            _log.warning("backtest failed for event_id=%d", eid, exc_info=True)
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
            _log.warning("macro_snapshot failed for date=%s", d, exc_info=True)
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
        _log.warning("ticker headlines: news cache unavailable for %s", symbol, exc_info=True)
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


@app.get("/stress")
def stress():
    """Return the current market stress regime and signal breakdown."""
    return compute_stress_regime()


@app.get("/rates-context")
def rates_context():
    """Return a compact inflation/rates context snapshot."""
    return compute_rates_context()


@app.get("/snapshots")
def snapshots(refresh: bool = False):
    """Return current liquid market snapshots with freshness metadata.

    By default returns whatever the background refresh thread has populated.
    Pass ?refresh=true to force a synchronous refresh first (useful when the
    background thread is disabled or you want fresh data right now).
    """
    from market_snapshots import get_all_snapshots, refresh_all
    if refresh:
        refresh_all()
    return [s.to_dict() for s in get_all_snapshots()]


@app.get("/market-context")
def market_context(highlight_limit: int = 3):
    """Return one normalized market context combining benchmarks + stress + highlights.

    All three sections degrade independently when their underlying data
    source fails — partial results are returned, never a 500.
    No new cold-fetch logic: snapshots come from the warm SnapshotStore,
    stress and movers reuse the existing TTL-cached pipelines.
    """
    from market_context import compose_market_context
    from market_snapshots import get_all_snapshots

    # 1. Snapshots — warm path
    snaps_list: list[dict] = []
    try:
        snaps_list = [s.to_dict() for s in get_all_snapshots()]
    except Exception:
        _log.warning("market_context: snapshots fetch failed", exc_info=True)

    # 2. Stress regime — already self-degrading per signal
    stress_dict: dict | None = None
    try:
        stress_dict = compute_stress_regime()
    except Exception:
        _log.warning("market_context: stress fetch failed", exc_info=True)

    # 3. Highlights — top recent movers, reuses /movers/today logic
    highlights: list[dict] = []
    try:
        highlights = movers_today(limit=highlight_limit)
    except Exception:
        _log.warning("market_context: highlights fetch failed", exc_info=True)

    return compose_market_context(snaps_list, stress_dict, highlights)


_MOVER_THRESHOLD = 1.5  # abs(return_5d) minimum for Market Movers qualification


def _build_mover_summary(ev: dict, big_moves: list[dict], support_ratio: float) -> dict:
    """Build a single Market Mover summary dict from an event and its qualifying tickers."""
    max_move = max(abs(t["return_5d"]) for t in big_moves)
    impact = max_move * (1.0 + support_ratio)

    big_moves.sort(key=lambda t: abs(t.get("return_5d") or 0), reverse=True)
    ticker_summaries = []
    for t in big_moves[:3]:
        r5 = t.get("return_5d")
        r20 = t.get("return_20d")
        decay = classify_decay(r5, r20)
        ticker_summaries.append({
            "symbol": t.get("symbol", "?"),
            "role": t.get("role", "?"),
            "return_5d": r5,
            "return_20d": r20,
            "direction": t.get("direction_tag"),
            "spark": t.get("spark", []),
            "decay": decay["label"],
            "decay_evidence": decay["evidence"],
        })

    return {
        "event_id": ev["id"],
        "headline": ev["headline"],
        "mechanism_summary": ev.get("mechanism_summary", ""),
        "event_date": ev.get("event_date", ""),
        "stage": ev.get("stage", ""),
        "persistence": ev.get("persistence", ""),
        "impact": round(impact, 2),
        "support_ratio": round(support_ratio, 2),
        "tickers": ticker_summaries,
        "transmission_chain": ev.get("transmission_chain", []),
        "if_persists": ev.get("if_persists", {}),
    }


def _score_event(ev: dict, threshold: float) -> dict | None:
    """Score an event for Market Movers qualification. Returns None if it doesn't qualify."""
    tickers = ev.get("market_tickers", [])
    if not tickers:
        return None

    big_moves = [
        t for t in tickers
        if t.get("return_5d") is not None and abs(t["return_5d"]) >= threshold
    ]
    if not big_moves:
        return None

    with_dir = [t for t in tickers if t.get("direction_tag") is not None]
    supporting = [
        t for t in with_dir
        if "supports" in (t.get("direction_tag") or "")
    ]
    support_ratio = len(supporting) / len(with_dir) if with_dir else 0.0

    return _build_mover_summary(ev, big_moves, support_ratio)


@app.get("/market-movers")
def market_movers(limit: int = 5):
    """Return saved events with confirmed market moves, ranked by impact.

    Uses the market data already saved at analysis time (return_5d, direction_tag,
    spark) — not followup_check, which requires forward trading days.

    Qualifying rules:
    - Event has market_tickers with return data
    - At least one ticker with abs(5d return) >= 1.5%
    - Ranked by impact = max_abs_move * (1 + hypothesis_support_ratio)
    """
    events = load_recent_events(limit=50)
    scored = [s for ev in events if (s := _score_event(ev, _MOVER_THRESHOLD)) is not None]
    scored.sort(key=lambda x: x["impact"], reverse=True)
    return scored[:limit]


# ---------------------------------------------------------------------------
# Today's biggest movers — last 24 hours, lower bar
# ---------------------------------------------------------------------------

_TODAYS_MOVERS_CACHE: dict = {"data": None, "ts": 0.0}
_TODAYS_MOVERS_TTL = 300  # 5 minutes


@app.get("/movers/today")
def movers_today(limit: int = 10):
    """Return analyzed events from the last 24 hours with any confirmed ticker move.

    Lower bar than /market-movers: any non-null return_5d qualifies (no minimum).
    Sorted by abs(max ticker return) descending. Cached for 5 minutes.
    """
    now = time.monotonic()
    if _TODAYS_MOVERS_CACHE["data"] is not None and (now - _TODAYS_MOVERS_CACHE["ts"]) < _TODAYS_MOVERS_TTL:
        return _TODAYS_MOVERS_CACHE["data"][:limit]

    cutoff = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
    events = load_recent_events(limit=100)

    seen_headlines: set[str] = set()
    scored: list[dict] = []
    for ev in events:
        ts = ev.get("timestamp", "")
        if ts < cutoff:
            continue
        hl = ev.get("headline", "")
        if hl in seen_headlines:
            continue
        seen_headlines.add(hl)

        tickers = ev.get("market_tickers", [])
        if not tickers:
            continue

        with_return = [t for t in tickers if t.get("return_5d") is not None]
        if not with_return:
            continue

        with_dir = [t for t in tickers if t.get("direction_tag") is not None]
        supporting = [t for t in with_dir if "supports" in (t.get("direction_tag") or "")]
        support_ratio = len(supporting) / len(with_dir) if with_dir else 0.0

        scored.append(_build_mover_summary(ev, with_return, support_ratio))

    scored.sort(key=lambda x: x["impact"], reverse=True)
    _TODAYS_MOVERS_CACHE["data"] = scored
    _TODAYS_MOVERS_CACHE["ts"] = now
    return scored[:limit]


# ---------------------------------------------------------------------------
# Weekly / yearly / persistent movers — persisted through movers_cache.
#
# Each endpoint is a thin adapter over ``movers_cache.get_slice`` which
# reads the precomputed payload from the ``movers_cache`` SQLite table,
# recomputes only when the cached row is missing, past its TTL, or the
# events fingerprint has changed.  The in-memory dicts below are kept
# as thin compatibility shims for tests that clear them between runs:
# clearing them now also invalidates the persisted slice.
# ---------------------------------------------------------------------------


class _LegacyMoverCacheShim(dict):
    """Backwards-compatible shim for the old ``_*_MOVERS_CACHE`` dicts.

    Tests (and the market-context code below) used to reach into
    ``_WEEKLY_MOVERS_CACHE["data"] = None`` to clear the cache.  With
    the persisted layer that assignment alone is not enough — the
    SQLite row has to go too.  This shim intercepts the reset and
    invalidates the persisted slice in one step so every existing test
    keeps working without changes.
    """

    def __init__(self, slice_name: str) -> None:
        super().__init__({"data": None, "ts": 0.0})
        self._slice_name = slice_name

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if key == "data" and value is None:
            try:
                movers_cache.invalidate(self._slice_name)
            except Exception:
                pass


_WEEKLY_MOVERS_CACHE: dict = _LegacyMoverCacheShim("weekly")
_YEARLY_MOVERS_CACHE: dict = _LegacyMoverCacheShim("yearly")
_PERSISTENT_MOVERS_CACHE: dict = _LegacyMoverCacheShim("persistent")
_WEEKLY_MOVERS_TTL = 3600   # 60 min — validated in tools/movers_cache_validation.py
_YEARLY_MOVERS_TTL = 7200   # 120 min
_PERSISTENT_MOVERS_TTL = 3600  # 60 min


@app.get("/movers/weekly")
def movers_weekly(limit: int = 10):
    """Return analyzed events from the last 7 days with any confirmed ticker move."""
    return movers_cache.get_slice(
        "weekly", limit=limit, ttl_seconds=_WEEKLY_MOVERS_TTL,
    )


@app.get("/movers/yearly")
def movers_yearly(limit: int = 10):
    """Return analyzed events from the last 365 days with any confirmed ticker move."""
    return movers_cache.get_slice(
        "yearly", limit=limit, ttl_seconds=_YEARLY_MOVERS_TTL,
    )


@app.get("/movers/persistent")
def movers_persistent(limit: int = 12):
    """Return events with lasting market impact — the flagship section.

    Primary: events older than 7 days with Accelerating or Holding decay.
    Fallback: if none found, include ALL events with confirmed ticker movement,
    sorted by impact, labeled as 'Monitoring' trajectory.  The hero section
    must not be empty — it's the product's core value proposition.
    """
    return movers_cache.get_slice(
        "persistent", limit=limit, ttl_seconds=_PERSISTENT_MOVERS_TTL,
    )


def _persistent_summary(ev: dict, with_return: list[dict], now_dt) -> dict:
    """Build a mover summary with days_since_event for the persistent section."""
    tickers = ev.get("market_tickers", [])
    with_dir = [t for t in tickers if t.get("direction_tag") is not None]
    supporting = [t for t in with_dir if "supports" in (t.get("direction_tag") or "")]
    support_ratio = len(supporting) / len(with_dir) if with_dir else 0.0
    summary = _build_mover_summary(ev, with_return, support_ratio)
    event_date = ev.get("event_date") or ev.get("timestamp", "")[:10]
    try:
        days_since = (now_dt - datetime.fromisoformat(event_date)).days
    except (ValueError, TypeError):
        days_since = 0
    summary["days_since_event"] = days_since
    return summary


@app.get("/news")
def news(limit: int = 0, offset: int = 0):
    """Fetch headlines from all sources, cluster, and return.

    Supports pagination: limit=30&offset=0 returns first 30 clusters.
    limit=0 (default) returns all clusters for backward compatibility.
    Always includes total_count for the frontend to know when to stop.
    """
    payload = _get_news_cached()
    clusters = payload.get("clusters", [])
    total = len(clusters)

    if limit > 0:
        page = clusters[offset:offset + limit]
    else:
        page = clusters

    return {
        "clusters": page,
        "total_headlines": payload.get("total_headlines", 0),
        "total_count": total,
        "feed_status": payload.get("feed_status", []),
    }


@app.post("/news/refresh")
def news_refresh():
    """Force a fresh fetch, bypassing both caches."""
    return _fetch_fresh_news()
