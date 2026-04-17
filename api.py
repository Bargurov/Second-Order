"""
Thin FastAPI layer over the existing backend.

Run with:  uvicorn api:app --reload
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Optional
import io
import json as _json
import logging
import re
import time
import zipfile

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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from db import (
    init_db, load_recent_events, load_events_since, load_event_by_id,
    save_event, update_review, delete_event,
    find_related_events, load_news_cache, save_news_cache, find_cached_analysis,
    load_low_signal_headlines, find_historical_analogs, compute_track_record,
    append_revisit_snapshot, load_revisit_snapshots,
    get_confidence_calibration_stats,
)
from classify import classify_stage, classify_persistence
from analyze_event import (
    analyze_event, is_mock as _is_mock_analysis, _DEFAULT_MODEL,
    _normalize_if_persists, _normalize_currency_channel,
    AnalysisResult, PERSISTED_OVERLAY_FIELDS,
)
from market_check import (
    market_check, followup_check, macro_snapshot, ticker_chart, ticker_info,
    compute_stress_regime, compute_rates_context, classify_decay,
    classify_policy_sensitivity,
    classify_inventory_context,
    build_macro_context_for_prompt,
    _suppress_duplicate_tickers,
    _scrub_implausible_ticker_returns,
    normalize_spark,
)
from market_check_freshness import refresh_market_for_saved_event
import movers_cache
from real_yield_context import build_real_yield_context, sanitize_real_yield_context_block
from policy_constraint import compute_policy_constraint
from shock_decomposition import compute_shock_decomposition, sanitize_shock_decomposition_block
from reaction_function_divergence import compute_reaction_function_divergence
from narrative_divergence import compute_narrative_divergence
from regime_vector import build_regime_vector
from surprise_vs_anticipation import compute_surprise_vs_anticipation
from terms_of_trade import compute_terms_of_trade
from reserve_stress_overlay import compute_reserve_stress
import os
from news_sources import fetch_all, cluster_headlines, normalize_headline

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
# CORS — env-driven so local dev, same-origin deploys, and split-origin
# deploys all work from the same codebase.
#
# Resolution rules (``CORS_ALLOWED_ORIGINS``):
#   - unset or empty string  → no CORS middleware registered.  Safe
#                              default for same-origin deploys where the
#                              frontend is served from the same host as
#                              the API (via a reverse-proxy rewrite or a
#                              static-file mount), and for local dev
#                              where Vite's ``/api`` proxy keeps every
#                              request same-origin already.
#   - ``*``                  → wildcard (any origin).  Use only for
#                              smoke-testing public read-only endpoints;
#                              it disables credentialed CORS.
#   - comma-separated list   → exact origin allowlist, e.g.
#                              ``https://app.example.com,https://staging.example.com``.
#
# Credentialed requests are enabled for exact allowlists so cookies /
# Authorization headers work in split-origin deploys.  Wildcard mode
# keeps credentials off per the CORS spec.
# ---------------------------------------------------------------------------


def _resolve_cors_origins() -> list[str]:
    """Parse ``CORS_ALLOWED_ORIGINS`` into a clean list of allowed origins.

    Pure helper — unit-tested directly.  Returns ``[]`` when the env
    var is missing, empty, or whitespace-only (caller interprets this
    as "do not register CORSMiddleware").  Returns ``["*"]`` for the
    wildcard case.  Otherwise returns the comma-split, whitespace-
    trimmed, empty-filtered list of exact origins.
    """
    raw = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return []
    if raw == "*":
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


_cors_origins = _resolve_cors_origins()
if _cors_origins:
    # Wildcard disables credentials per the CORS spec; exact allowlists
    # turn them on so cookies / Authorization headers pass through.
    _wildcard = _cors_origins == ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=not _wildcard,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )


# ---------------------------------------------------------------------------
# Two-layer news cache: in-memory (hot) + SQLite (persistent across restarts)
# ---------------------------------------------------------------------------

_NEWS_TTL_SECONDS = 300  # 5 minutes
_news_cache: dict[str, Any] = {"data": None, "ts": 0.0}

# Guard against overlapping / spammed refresh calls.
# _refresh_lock prevents concurrent refreshes from doing duplicate work.
# _REFRESH_COOLDOWN_SECONDS returns the last result if called again within the window.
import threading as _threading
_refresh_lock = _threading.Lock()
_REFRESH_COOLDOWN_SECONDS = 10
_last_refresh_at: float = 0.0          # monotonic timestamp of last completed refresh
_last_refresh_payload: dict | None = None

_api_log = logging.getLogger("second_order.news")


def _fetch_fresh_news() -> dict:
    """Fetch, cluster, and return a fresh news payload. Updates both caches.

    The clustering step runs through the persisted ``news_cluster_store``
    so only genuinely new (unassigned) headlines are reclustered; every
    already-seen headline just updates the last-seen timestamp on its
    existing cluster.  A cold DB bootstraps cleanly because the store's
    first call finds zero assignments and clusters the full batch once.

    refresh_meta.status:
      "ok"       — fetch + cluster succeeded normally
      "degraded" — partial feed failure or cluster fallback, but some data returned
      "error"    — total fetch failure; returning last-known cached clusters
    """
    import news_cluster_store

    t0 = time.monotonic()

    # --- Fetch headlines from all feeds ---
    try:
        records, feed_status = fetch_all()
    except Exception:
        _log.error("_fetch_fresh_news: fetch_all() failed completely", exc_info=True)
        # Return last-known data so the UI isn't blank
        last = _news_cache.get("data")
        if last is None:
            try:
                last = load_news_cache(max_age_seconds=86400)
            except Exception:
                last = None
        if last and last.get("clusters"):
            prev_ts = (last.get("refresh_meta") or {}).get("last_successful_refresh")
            last["refresh_meta"] = {
                "status": "error", "source": "cached_fallback",
                "known": 0, "new": 0, "merged": 0, "created": 0,
                "reused": len(last["clusters"]),
                "ok_feeds": 0, "fail_feeds": 0,
                "error": "Feed fetch failed — showing last known data",
                "last_successful_refresh": prev_ts,
                "freshness": "stale",
            }
            return last
        return {
            "clusters": [], "total_headlines": 0, "feed_status": [],
            "refresh_meta": {
                "status": "error", "source": "empty",
                "known": 0, "new": 0, "merged": 0, "created": 0, "reused": 0,
                "ok_feeds": 0, "fail_feeds": 0,
                "error": "Feed fetch failed and no cached data available",
                "last_successful_refresh": None,
                "freshness": "stale",
            },
        }

    ok_feeds = sum(1 for f in feed_status if f.get("ok"))
    fail_feeds = sum(1 for f in feed_status if not f.get("ok"))

    # --- Cluster ---
    refresh_meta: dict = {}
    try:
        clusters = news_cluster_store.refresh_clusters(
            records, cluster_fn=cluster_headlines, meta=refresh_meta,
        )
    except Exception:
        _log.warning(
            "news_cluster_store.refresh_clusters failed; "
            "falling back to full recluster",
            exc_info=True,
        )
        clusters = cluster_headlines(records)
        refresh_meta = {"source": "full_recluster", "known": 0, "new": len(records),
                        "merged": 0, "created": len(clusters), "reused": 0}

    elapsed = time.monotonic() - t0

    # Determine overall status
    if fail_feeds > 0 and ok_feeds == 0:
        refresh_meta["status"] = "error"
        refresh_meta["error"] = "All feeds failed"
    elif fail_feeds > 0:
        refresh_meta["status"] = "degraded"
        refresh_meta["error"] = f"{fail_feeds} of {ok_feeds + fail_feeds} feeds failed"
    else:
        refresh_meta["status"] = "ok"
    refresh_meta["ok_feeds"] = ok_feeds
    refresh_meta["fail_feeds"] = fail_feeds

    _api_log.info(
        "[refresh] done in %.1fs — %d feeds OK, %d failed, %d headlines → %d clusters",
        elapsed, ok_feeds, fail_feeds, len(records), len(clusters),
    )

    # Tag clusters whose headline was previously analyzed as low_signal
    low_headlines = load_low_signal_headlines()
    for c in clusters:
        c["low_signal"] = c.get("headline", "") in low_headlines

    now_iso = datetime.now().replace(microsecond=0).isoformat()
    if refresh_meta.get("status") == "ok":
        refresh_meta["last_successful_refresh"] = now_iso
        refresh_meta["freshness"] = "fresh"
    elif refresh_meta.get("status") == "degraded":
        refresh_meta["last_successful_refresh"] = now_iso
        refresh_meta["freshness"] = "degraded"
    else:
        # error — preserve the previous success timestamp if available
        prev = (_news_cache.get("data") or {}).get("refresh_meta", {})
        refresh_meta["last_successful_refresh"] = prev.get("last_successful_refresh")
        refresh_meta["freshness"] = "stale"

    payload = {
        "clusters": clusters,
        "total_headlines": len(records),
        "feed_status": feed_status,
        "refresh_meta": refresh_meta,
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


def compute_news_uncertainty() -> dict:
    """Aggregate cluster-level uncertainty by sector from the news cache.

    Returns the same shape as uncertainty_concentration._empty() on any failure.
    """
    from uncertainty_concentration import compute_uncertainty_concentration
    try:
        clusters = _get_news_cached().get("clusters", [])
        return compute_uncertainty_concentration(clusters)
    except Exception:
        _log.warning("compute_news_uncertainty failed", exc_info=True)
        return {"uncertainty_scope": "global", "sector_uncertainty": [], "lead_sector": None}


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


def _sanitize_floats(obj: Any) -> Any:
    """Recursively replace NaN / ±inf with None so json.dumps never raises.

    FastAPI's JSONResponse uses stdlib json which rejects non-finite floats.
    Market-data helpers (yfinance, custom computations) can produce NaN when
    a ticker has no price history — especially in test environments that don't
    hit the network.  This scrubber is the last line of defence before any
    dict leaves the API layer.
    """
    import math
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_floats(v) for v in obj]
    return obj


def _mock_failure_response(headline: str, analysis: dict, effective_date: str) -> dict:
    """Build a stable failure response when the LLM returns a mock/fallback.

    Does NOT run market_check, overlays, or persist anything.  Returns
    the same top-level keys as a normal /analyze response so the
    frontend can rely on the shape, plus ``analysis_failed: true`` and
    a human-readable ``failure_reason``.
    """
    # Extract the mock reason from "[mock: <reason>]"
    raw = analysis.get("what_changed") or ""
    reason = raw.replace("[mock:", "").rstrip("]").strip() if "[mock:" in raw else "model unavailable"
    return {
        "headline":       headline,
        "stage":          "",
        "persistence":    "",
        "analysis":       {},
        "market":         {"note": "", "details": {}, "tickers": []},
        "freshness":      {},
        "is_mock":        True,
        "event_date":     effective_date,
        "analysis_failed": True,
        "failure_reason":  reason,
    }


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
    # Defensive emission: scrub implausibly large persisted return
    # values (the +1348% XLE bug from corrupt price_cache bars) and
    # suppress cross-contaminated rows where two distinct symbols
    # share byte-identical (return_5d, spark) data.  Both run on
    # fresh-copy dicts; neither mutates upstream payloads.
    tickers = _scrub_implausible_ticker_returns(
        market_block.get("tickers", [])
    )
    tickers = _suppress_duplicate_tickers(tickers)

    mech_text = f"{cached.get('what_changed', '')} {cached.get('mechanism_summary', '')}"
    inv_text = f"{headline} {mech_text}"

    if is_frozen_archive:
        # ----- Frozen-archive branch: reuse stored values, skip recomputes ---
        inventory_context = cached.get("inventory_context") or {}
        policy_sensitivity = cached.get("policy_sensitivity") or {}
        real_yield_ctx = sanitize_real_yield_context_block(
            cached.get("real_yield_context") or {}
        )
        policy_constraint_ctx = cached.get("policy_constraint") or {}
        # Scrub persisted shock-decomposition blocks: events saved before the
        # nominal-yield unit fix may carry move_5d values like +2680% from
        # _safe_pct applied to near-zero historical ^TNX cache rows.
        shock_decomp_ctx = sanitize_shock_decomposition_block(
            cached.get("shock_decomposition") or {}
        )
        reaction_div_ctx = cached.get("reaction_function_divergence") or {}
        surprise_ctx = cached.get("surprise_vs_anticipation") or {}
        terms_of_trade_ctx = cached.get("terms_of_trade") or {}
        reserve_stress_ctx = cached.get("reserve_stress") or {}
        narrative_div_ctx = cached.get("narrative_divergence") or {}
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

        try:
            narrative_div_ctx = compute_narrative_divergence(
                tickers,
                cached.get("confidence", "low"),
                get_confidence_calibration_stats(),
            )
        except Exception:
            _log.warning("narrative_divergence failed (cached rebuild)", exc_info=True)
            narrative_div_ctx = {}

    response = {
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
            "narrative_divergence": narrative_div_ctx,
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
            # Data-quality signal — present on fresh responses; forward it
            # unchanged so the frontend degraded-data notice fires on cache
            # hits too.  Falls back to "ok" when the market block predates
            # the field (legacy stored rows).
            "data_quality": market_block.get("data_quality", "ok"),
            "data_quality_note": market_block.get("data_quality_note"),
        },
        "freshness": _freshness_payload(age_classification),
        "is_mock":     False,
        "event_date":  effective_date,
    }
    return _sanitize_floats(response)


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
    analysis: AnalysisResult, mkt: dict, effective_date: str,
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
        # Macro overlays — driven by PERSISTED_OVERLAY_FIELDS so adding a new
        # field to the registry automatically flows through without touching this
        # function.  Each defaults to {} if not yet computed for this event.
        **{field: analysis.get(field, {}) for field in PERSISTED_OVERLAY_FIELDS},
    }
    try:
        save_event(event_record)
        # Bust the today-movers in-memory cache so /movers/today reflects
        # the new event without waiting for the 5-minute TTL to expire.
        _TODAYS_MOVERS_CACHE["data"] = None
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
    event_id: Optional[int] = Field(
        None, ge=1,
        description=(
            "When provided, load this specific event by primary key instead of "
            "doing a headline-string lookup.  Guarantees correct routing when "
            "two near-duplicate headlines share the same anchor date."
        ),
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

def _sse_event(phase: str, data: dict) -> str:
    """Format one SSE event line."""
    payload = _json.dumps({"_phase": phase, **data}, default=str)
    return f"data: {payload}\n\n"


@app.get("/health")
def health():
    return {"status": "ok"}


def _derive_health_overall(meta: dict) -> str:
    """Derive overall pipeline health from a refresh_meta dict.

    Exported for tests — pure function, no I/O.
    """
    status    = meta.get("status", "ok")
    freshness = meta.get("freshness", "fresh")
    if status == "error":
        return "error"
    if status == "degraded" or freshness in ("degraded", "stale"):
        return "degraded"
    return "ok"


@app.get("/health/detail")
def health_detail():
    """Structured pipeline-health snapshot for the in-app health panel.

    Reads the in-memory refresh cache (with a SQLite fallback) — no new
    I/O, no state mutations.  Returns feed counts, failing feed names, last
    refresh timestamp, and a single ``overall`` verdict.
    """
    from datetime import datetime as _dt

    payload = _last_refresh_payload
    if payload is None:
        try:
            payload = load_news_cache(max_age_seconds=86400)
        except Exception:
            payload = None

    if not payload:
        return {
            "api_status": "ok",
            "refresh_at": None,
            "refresh_age_seconds": None,
            "feed_health": {"ok": 0, "failed": 0, "total": 0, "failing": []},
            "pipeline": {"clusters_cached": 0, "total_headlines": 0, "freshness": None},
            "overall": "no_data",
        }

    meta        = payload.get("refresh_meta") or {}
    feed_status = payload.get("feed_status") or []

    ok_feeds   = meta.get("ok_feeds",   sum(1 for f in feed_status if f.get("ok")))
    fail_feeds = meta.get("fail_feeds", sum(1 for f in feed_status if not f.get("ok")))

    failing = [
        {"name": f["name"], "error": f.get("error") or "unknown"}
        for f in feed_status if not f.get("ok")
    ]

    refresh_at = meta.get("last_successful_refresh")
    refresh_age_seconds: Optional[int] = None
    if refresh_at:
        try:
            age = (_dt.now() - _dt.fromisoformat(refresh_at)).total_seconds()
            refresh_age_seconds = max(0, int(age))
        except Exception:
            pass

    return {
        "api_status": "ok",
        "refresh_at": refresh_at,
        "refresh_age_seconds": refresh_age_seconds,
        "feed_health": {
            "ok":     ok_feeds,
            "failed": fail_feeds,
            "total":  ok_feeds + fail_feeds,
            "failing": failing,
        },
        "pipeline": {
            "clusters_cached": len(payload.get("clusters") or []),
            "total_headlines": payload.get("total_headlines", 0),
            "freshness": meta.get("freshness"),
        },
        "overall": _derive_health_overall(meta),
    }





def _build_event_text_memo(ev: dict) -> str:
    """Render a saved event dict as a plain-text research memo."""
    SEP = "\u2500" * 52
    lines: list[str] = []

    lines.append("SECOND ORDER \u2014 RESEARCH NOTE")
    lines.append(SEP)
    lines.append(f"Event:   {ev.get('headline', '')}")
    if ev.get("event_date"):
        lines.append(f"Date:    {ev['event_date']}")
    meta = " \u00b7 ".join(filter(None, [
        ev.get("stage"), ev.get("persistence"),
        f"{ev['confidence']} confidence" if ev.get("confidence") else None,
    ]))
    lines.append(f"Stage:   {meta}")
    lines.append(f"Saved:   {(ev.get('timestamp') or '')[:16].replace('T', ' ')} UTC")
    lines.append("")

    if ev.get("what_changed"):
        lines.append("WHAT CHANGED")
        lines.append(ev["what_changed"])
        lines.append("")

    if ev.get("mechanism_summary"):
        lines.append("MECHANISM")
        lines.append(ev["mechanism_summary"])
        lines.append("")

    bens = ev.get("beneficiaries") or []
    losers = ev.get("losers") or []
    if bens:
        lines.append(f"BENEFICIARIES:  {', '.join(bens)}")
    if losers:
        lines.append(f"LOSERS:         {', '.join(losers)}")
    if bens or losers:
        lines.append("")

    tickers = ev.get("market_tickers") or []
    if tickers:
        def _pct(v):
            if v is None:
                return "  \u2014  "
            return f"{'+' if v >= 0 else ''}{v:.2f}%"
        def _vol(v):
            return f"{v:.1f}x" if v is not None else "\u2014"
        lines.append("MARKET CHECK")
        lines.append(
            f"  {'Ticker':<8} {'Role':<14} {'1d':>8}  {'5d':>8}  {'20d':>8}  {'Vol':>5}  Signal"
        )
        lines.append(
            f"  {'\u2500'*8} {'\u2500'*14} {'\u2500'*8}  {'\u2500'*8}  {'\u2500'*8}  {'\u2500'*5}  {'\u2500'*14}"
        )
        for t in tickers:
            lines.append(
                f"  {t.get('symbol',''):<8} {(t.get('role') or ''):<14}"
                f" {_pct(t.get('return_1d')):>8}  {_pct(t.get('return_5d')):>8}"
                f"  {_pct(t.get('return_20d')):>8}  {_vol(t.get('volume_ratio')):>5}"
                f"  {t.get('direction_tag') or 'pending'}"
            )
        if ev.get("market_note"):
            lines.append(f"  Note: {ev['market_note']}")
        lines.append("")

    if ev.get("rating") or ev.get("notes"):
        lines.append("REVIEW")
        if ev.get("rating"):
            lines.append(f"  Rating: {ev['rating']}")
        if ev.get("notes"):
            lines.append(f"  Notes:  {ev['notes']}")
        lines.append("")

    lines.append(SEP)
    from datetime import datetime, timezone
    lines.append(f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")
    return "\n".join(lines)




def _build_event_markdown_memo(ev: dict) -> str:
    """Render a saved event dict as a compact Markdown research memo.

    Section order is fixed so downstream consumers (tests, tooling)
    can rely on heading positions.
    """
    lines: list[str] = []

    # --- Header ---
    lines.append(f"# {ev.get('headline', 'Untitled Event')}")
    lines.append("")
    meta_parts = []
    if ev.get("event_date"):
        meta_parts.append(f"**Date:** {ev['event_date']}")
    stage_parts = " · ".join(filter(None, [
        ev.get("stage"), ev.get("persistence"),
        f"{ev['confidence']} confidence" if ev.get("confidence") else None,
    ]))
    if stage_parts:
        meta_parts.append(f"**Stage:** {stage_parts}")
    saved_ts = (ev.get("timestamp") or "")[:16].replace("T", " ")
    if saved_ts:
        meta_parts.append(f"**Saved:** {saved_ts} UTC")
    if meta_parts:
        lines.append(" · ".join(meta_parts))
        lines.append("")

    # --- What Changed ---
    if ev.get("what_changed"):
        lines.append("## What Changed")
        lines.append("")
        lines.append(ev["what_changed"])
        lines.append("")

    # --- Mechanism ---
    if ev.get("mechanism_summary"):
        lines.append("## Mechanism")
        lines.append("")
        lines.append(ev["mechanism_summary"])
        lines.append("")

    # --- Affected Assets ---
    bens = ev.get("beneficiaries") or []
    losers = ev.get("losers") or []
    if bens or losers:
        lines.append("## Affected Assets")
        lines.append("")
        if bens:
            lines.append(f"**Beneficiaries:** {', '.join(bens)}")
        if losers:
            lines.append(f"**Losers:** {', '.join(losers)}")
        lines.append("")

    # --- Market Check ---
    tickers = ev.get("market_tickers") or []
    if tickers:
        def _pct(v):
            if v is None:
                return "—"
            return f"{'+' if v >= 0 else ''}{v:.2f}%"

        lines.append("## Market Check")
        lines.append("")
        lines.append("| Ticker | Role | 1d | 5d | 20d | Signal |")
        lines.append("|--------|------|---:|---:|----:|--------|")
        for t in tickers:
            lines.append(
                f"| {t.get('symbol', '')} "
                f"| {t.get('role', '')} "
                f"| {_pct(t.get('return_1d'))} "
                f"| {_pct(t.get('return_5d'))} "
                f"| {_pct(t.get('return_20d'))} "
                f"| {t.get('direction_tag') or 'pending'} |"
            )
        if ev.get("market_note"):
            lines.append("")
            lines.append(f"> {ev['market_note']}")
        lines.append("")

    # --- Review ---
    if ev.get("rating") or ev.get("notes"):
        lines.append("## Review")
        lines.append("")
        if ev.get("rating"):
            lines.append(f"**Rating:** {ev['rating']}")
        if ev.get("notes"):
            lines.append("")
            lines.append(ev["notes"])
        lines.append("")

    # --- Footer ---
    lines.append("---")
    from datetime import datetime, timezone
    lines.append(f"*Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC · Second Order*")
    return "\n".join(lines)




def _build_event_research_memo(ev: dict) -> str:
    """Render a saved event as a clean research memo in Markdown.

    Sections: Thesis, Mechanism, Beneficiaries / Losers,
              Market Validation, Key Context.
    Each section is silently omitted when source data is absent.
    """
    lines: list[str] = []

    # --- Header ---
    lines.append(f"# {ev.get('headline', 'Untitled Event')}")
    lines.append("")
    meta_parts = []
    if ev.get("event_date"):
        meta_parts.append(f"**Date:** {ev['event_date']}")
    stage_parts = " · ".join(filter(None, [
        ev.get("stage"), ev.get("persistence"),
        f"{ev['confidence']} confidence" if ev.get("confidence") else None,
    ]))
    if stage_parts:
        meta_parts.append(f"**Stage:** {stage_parts}")
    saved_ts = (ev.get("timestamp") or "")[:16].replace("T", " ")
    if saved_ts:
        meta_parts.append(f"**Saved:** {saved_ts} UTC")
    if meta_parts:
        lines.append(" · ".join(meta_parts))
        lines.append("")

    # --- Thesis ---
    if ev.get("what_changed"):
        lines.append("## Thesis")
        lines.append("")
        lines.append(ev["what_changed"])
        lines.append("")

    # --- Mechanism ---
    if ev.get("mechanism_summary"):
        lines.append("## Mechanism")
        lines.append("")
        lines.append(ev["mechanism_summary"])
        lines.append("")

    # --- Beneficiaries / Losers ---
    bens = ev.get("beneficiaries") or []
    losers = ev.get("losers") or []
    if bens or losers:
        lines.append("## Beneficiaries / Losers")
        lines.append("")
        if bens:
            lines.append(f"**Beneficiaries:** {', '.join(bens)}")
        if losers:
            lines.append(f"**Losers:** {', '.join(losers)}")
        lines.append("")

    # --- Market Validation ---
    tickers = ev.get("market_tickers") or []
    if tickers:
        def _pct(v):
            if v is None:
                return "—"
            return f"{'+' if v >= 0 else ''}{v:.2f}%"

        lines.append("## Market Validation")
        lines.append("")
        lines.append("| Ticker | Role | 1d | 5d | 20d | Signal |")
        lines.append("|--------|------|---:|---:|----:|--------|")
        for t in tickers:
            lines.append(
                f"| {t.get('symbol', '')} "
                f"| {t.get('role', '')} "
                f"| {_pct(t.get('return_1d'))} "
                f"| {_pct(t.get('return_5d'))} "
                f"| {_pct(t.get('return_20d'))} "
                f"| {t.get('direction_tag') or 'pending'} |"
            )
        if ev.get("market_note"):
            lines.append("")
            lines.append(f"> {ev['market_note']}")
        lines.append("")

    # --- Key Context ---
    ctx_lines: list[str] = []

    sd = ev.get("shock_decomposition") or {}
    if sd.get("primary_label"):
        ctx_lines.append(f"**Shock type:** {sd['primary_label']}")

    sva = ev.get("surprise_vs_anticipation") or {}
    if sva.get("regime_label") and sva.get("rationale"):
        ctx_lines.append(f"**Priced-in:** {sva['regime_label']} — {sva['rationale']}")

    ps = ev.get("policy_sensitivity") or {}
    if ps.get("stance") and ps.get("regime") and ps.get("explanation"):
        ctx_lines.append(
            f"**Policy stance:** {ps['stance']} ({ps['regime']}) — {ps['explanation']}"
        )

    ryc = ev.get("real_yield_context") or {}
    if ryc.get("thesis") and ryc.get("explanation"):
        ctx_lines.append(f"**Rates alignment:** {ryc['thesis']} — {ryc['explanation']}")

    if ctx_lines:
        lines.append("## Key Context")
        lines.append("")
        lines.extend(ctx_lines)
        lines.append("")

    # --- Footer ---
    lines.append("---")
    from datetime import datetime, timezone
    lines.append(
        f"*Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC · Second Order*"
    )
    return "\n".join(lines)


def _build_portfolio_markdown(evs: list[dict]) -> str:
    """Render a list of saved events as a portfolio-style Markdown report.

    Adds a cover page (title, generated timestamp, event count, table of
    contents) then appends the individual markdown memos separated by
    horizontal rules.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    n = len(evs)

    lines: list[str] = []
    lines.append("# Second Order — Research Portfolio")
    lines.append("")
    lines.append(f"**Generated:** {now} UTC · **Events:** {n}")
    lines.append("")
    lines.append("---")
    lines.append("")

    if n > 0:
        lines.append("## Contents")
        lines.append("")
        for i, ev in enumerate(evs, 1):
            headline = ev.get("headline", "Untitled")
            date = ev.get("event_date") or (ev.get("timestamp") or "")[:10]
            stage = ev.get("stage") or ""
            conf = ev.get("confidence") or ""
            meta_parts = list(filter(None, [stage, f"{conf} confidence" if conf else None, date]))
            meta = " · ".join(meta_parts)
            lines.append(f"{i}. {headline}" + (f" — {meta}" if meta else ""))
        lines.append("")
        lines.append("---")
        lines.append("")
        memos = [_build_event_markdown_memo(ev) for ev in evs]
        lines.append("\n\n---\n\n".join(memos))

    return "\n".join(lines)


def _safe_event_filename(event_id: int, headline: str, ext: str) -> str:
    """Build a filesystem-safe filename for an event export."""
    slug = (headline or "event")[:40].replace(" ", "_")
    slug = "".join(c for c in slug if c.isalnum() or c in "_-")
    return f"event_{event_id}_{slug}.{ext}"


class BulkExportRequest(BaseModel):
    event_ids: list[int] = Field(..., min_length=1, max_length=100)






# Stable key list for the JSON event export.  Order matters — it defines
# the key order in the response so downstream consumers can rely on it.
_JSON_EXPORT_KEYS: tuple[str, ...] = (
    "id", "timestamp", "headline", "event_date",
    "stage", "persistence", "confidence",
    "what_changed", "mechanism_summary",
    "beneficiaries", "losers", "assets_to_watch",
    "market_note", "market_tickers",
    "transmission_chain", "if_persists", "currency_channel",
    "policy_sensitivity", "inventory_context",
    "real_yield_context", "policy_constraint",
    "shock_decomposition", "reaction_function_divergence",
    "surprise_vs_anticipation", "terms_of_trade", "reserve_stress",
    "rating", "notes",
)


def _build_event_json_export(ev: dict) -> dict:
    """Project a saved event dict to the stable JSON export shape.

    Only keys listed in ``_JSON_EXPORT_KEYS`` are emitted, in that
    fixed order.  Internal-only fields (``low_signal``, ``model``,
    ``regime_snapshot``, ``last_market_check_at``) are excluded.
    """
    return {k: ev.get(k) for k in _JSON_EXPORT_KEYS}



def _build_event_csv_export(ev: dict) -> str:
    """Render one saved event as a single-row CSV.

    Delegates to the bulk ``build_csv_export`` so column order, derived
    follow-through fields, and cell encoding are identical to the archive
    export — only the row count differs (header + one data row).
    """
    from events_export import build_csv_export
    return build_csv_export([ev])




@app.get("/stats/track-record")
def track_record():
    """Aggregate thesis outcomes across all saved events."""
    return _sanitize_floats(compute_track_record())


@app.get("/stats/confidence-calibration")
def confidence_calibration():
    """Historical validation rate per confidence bucket (low/medium/high).

    Returns per-bucket hit_rate (fraction of events with ≥1 supporting ticker)
    and sample size n.  Buckets with fewer than 3 usable events are omitted.
    """
    return _sanitize_floats(get_confidence_calibration_stats())




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
        raw_tickers = market_block.get("tickers") or tickers
        # Mirror the live analysis path: scrub implausible persisted returns
        # and suppress cross-contaminated rows so backtest scores reflect
        # exactly what the product ships to the UI.
        cleaned = _scrub_implausible_ticker_returns(raw_tickers)
        cleaned = _suppress_duplicate_tickers(cleaned)
        outcomes: list[dict] = []
        for t in cleaned:
            symbol = t.get("symbol")
            if not symbol:
                continue
            outcomes.append({
                "symbol": symbol,
                "role": t.get("role", "beneficiary"),
                "return_1d": t.get("return_1d"),
                "return_5d": t.get("return_5d"),
                "return_20d": t.get("return_20d"),
                "return_60d": t.get("return_60d"),
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






# ---------------------------------------------------------------------------
# Revisit timeline — market follow-through snapshots
# ---------------------------------------------------------------------------

_REVISIT_DAYS = (1, 5, 20, 60)




class BatchBacktestRequest(BaseModel):
    event_ids: list[int] = Field(..., max_length=50)
    force: bool = Field(
        False,
        description="Bypass the frozen-age cutoff and force a refresh on every row.",
    )




class BatchMacroRequest(BaseModel):
    event_dates: list[str] = Field(..., max_length=50)


class SimulatePortfolioRequest(BaseModel):
    event_ids: list[int] = Field(..., min_length=1, max_length=50)
    horizon: str = Field("5d", pattern=r"^(1d|5d|20d)$")
    include_shorts: bool = Field(False)
    direction_filter: str = Field("all", pattern=r"^(all|supporting)$")
















_MOVER_THRESHOLD = 1.5  # abs(return_5d) minimum for Market Movers qualification

# Maximum number of preview ticker chips a mover card emits.  Bumped
# from 3 → 4 so the persistent / weekly cards can carry richer
# evidence (one classic 2x2 grid of winner/loser/winner/loser shapes
# without dropping the second-best loser).
_MOVER_PREVIEW_LIMIT = 4


def _compute_support_ratio(tickers: list[dict]) -> float:
    """Deterministic agreement-percent computation.

    The single source of truth for the "X% agreement" pill that every
    mover card surfaces.  Three different call sites used to compute
    this independently and inconsistently — _score_event over the
    suppressed list, movers_today over the suppressed list, and
    _persistent_summary over the raw market_tickers (skipping
    suppression entirely).  Same event → three different agreement
    percentages depending on which endpoint built the card.

    Contract:
      * Counts only tickers that carry BOTH a non-null direction_tag
        AND a non-null return_5d (the analytical denominator that
        users see as "ticker that actually moved with a verdict").
      * "Supporting" = direction_tag startswith ``"supports"`` —
        same predicate the score line and the analyse view use.
      * Returns a float in [0, 1].  Empty denominator → 0.0.
      * Caller is expected to pass the SUPPRESSED tickers list so
        cross-contaminated rows don't pollute the count.
    """
    eligible = [
        t for t in tickers
        if t.get("direction_tag") is not None
        and t.get("return_5d") is not None
    ]
    if not eligible:
        return 0.0
    supporting = sum(
        1 for t in eligible
        if (t.get("direction_tag") or "").startswith("supports")
    )
    return supporting / len(eligible)


def _build_mover_summary(ev: dict, big_moves: list[dict], support_ratio: float) -> dict:
    """Build a single Market Mover summary dict from an event and its qualifying tickers.

    Each emitted ticker carries:
      * Its own fresh ``spark`` list (no shared references with the
        input dicts so a downstream mutation of one card cannot leak
        into another).
      * The ``anchor_date`` field captured at analyse time, so the
        frontend can label cards with "anchored to YYYY-MM-DD" and
        users understand why the same ticker (e.g. XLE) shows
        different return windows on different cards: the windows are
        anchored to different event dates.

    The card-level header carries:
      * ``last_market_check_at`` — when the persisted ticker numbers
        were last refreshed against the provider, plumbed through
        from the saved event row.
      * ``event_age_days`` — for "anchored 12d ago" UI footers.

    Tickers are sorted with a deterministic key: largest absolute 5d
    move first, then alphabetical by symbol as a tiebreaker.  The
    preview is capped at ``_MOVER_PREVIEW_LIMIT`` chips so cards
    carry richer evidence than a single thin chip while still fitting
    the existing card layout.
    """
    max_move = max(abs(t["return_5d"]) for t in big_moves)
    impact = max_move * (1.0 + support_ratio)

    # Deterministic sort: largest abs(return_5d) first, then symbol
    # ascending as a stable tiebreaker.  Without the symbol tiebreaker
    # two tickers with identical absolute moves would land in
    # iteration order, which is non-deterministic across reload.
    big_moves_sorted = sorted(
        big_moves,
        key=lambda t: (-abs(t.get("return_5d") or 0.0), t.get("symbol", "")),
    )

    ticker_summaries = []
    for t in big_moves_sorted[:_MOVER_PREVIEW_LIMIT]:
        r5 = t.get("return_5d")
        r20 = t.get("return_20d")
        decay = classify_decay(r5, r20)
        # Fresh spark list per emitted card — never share the input
        # reference, so two adjacent cards can never end up bound to
        # the same underlying sequence.
        spark_src = t.get("spark") or []
        ticker_summaries.append({
            "symbol": t.get("symbol", "?"),
            "role": t.get("role", "?"),
            "return_5d": r5,
            "return_20d": r20,
            "direction": t.get("direction_tag"),
            "spark": normalize_spark(spark_src) if spark_src else [],
            "decay": decay["label"],
            "decay_evidence": decay["evidence"],
            # Anchor date — the first trading bar the forward returns
            # were measured from.  Lets the frontend show "anchored
            # YYYY-MM-DD" and explain why the same symbol can read
            # differently across cards anchored to different dates.
            "anchor_date": t.get("anchor_date"),
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
        # Per-card freshness header — surfaced to the frontend so
        # cards display "as of HH:MM" / staleness state.  These
        # come straight from the persisted event row; on legacy rows
        # they default to None and the frontend hides the indicator.
        "last_market_check_at": ev.get("last_market_check_at"),
    }


def _score_event(ev: dict, threshold: float) -> dict | None:
    """Score an event for Market Movers qualification. Returns None if it doesn't qualify."""
    # Reject mock/fallback rows — they carry placeholder tickers (GLD, USO)
    # that could have real return_5d values from yfinance and would otherwise
    # qualify as movers.
    from movers_cache import is_mock_event
    if is_mock_event(ev):
        return None
    # Scrub implausibly large persisted returns AND suppress cross-
    # contaminated rows BEFORE qualification.  A 1348% XLE row would
    # otherwise dominate the impact ranking with garbage data.
    tickers = _scrub_implausible_ticker_returns(ev.get("market_tickers", []))
    tickers = _suppress_duplicate_tickers(tickers)
    if not tickers:
        return None

    big_moves = [
        t for t in tickers
        if t.get("return_5d") is not None and abs(t["return_5d"]) >= threshold
    ]
    if not big_moves:
        return None

    support_ratio = _compute_support_ratio(tickers)
    return _build_mover_summary(ev, big_moves, support_ratio)




# ---------------------------------------------------------------------------
# Today's biggest movers — last 24 hours, lower bar
# ---------------------------------------------------------------------------

_TODAYS_MOVERS_CACHE: dict = {"data": None, "ts": 0.0}
_TODAYS_MOVERS_TTL = 300  # 5 minutes


def movers_today(limit: int = 10):
    """Return analyzed events from the last 24 hours with any confirmed ticker move.

    Lower bar than /market-movers: any non-null return_5d qualifies (no minimum).
    Sorted by abs(max ticker return) descending. Cached for 5 minutes.

    Candidate selection uses a 24-hour time window via ``load_events_since``
    (not a row-count limit) so a burst of low-value rows never pushes
    relevant events out of the candidate set.  Consistent with /market-movers.
    """
    now = time.monotonic()
    if _TODAYS_MOVERS_CACHE["data"] is not None and (now - _TODAYS_MOVERS_CACHE["ts"]) < _TODAYS_MOVERS_TTL:
        return _TODAYS_MOVERS_CACHE["data"][:limit]

    cutoff = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
    events = load_events_since(cutoff)

    seen_headlines: set[str] = set()
    scored: list[dict] = []
    for ev in events:
        hl = ev.get("headline", "")
        if hl in seen_headlines:
            continue
        seen_headlines.add(hl)

        # Skip low-signal OR irrelevant-headline events.  Uses the
        # unified gate from movers_cache which checks both the low_signal
        # column AND headline relevance via news_sources.is_relevant().
        from movers_cache import _is_event_low_signal
        if _is_event_low_signal(ev):
            continue

        # Scrub absurd return values, then suppress cross-
        # contaminated rows.  Order matters: scrubbing first nukes
        # garbage values to None so the dedup signature isn't
        # polluted by 1348%-style outliers.
        tickers = _scrub_implausible_ticker_returns(ev.get("market_tickers", []))
        tickers = _suppress_duplicate_tickers(tickers)
        if not tickers:
            continue

        with_return = [t for t in tickers if t.get("return_5d") is not None]
        if not with_return:
            continue

        # Use the unified deterministic helper so today's-movers
        # cards report the same agreement % as /market-movers and
        # /movers/persistent for the same event.
        support_ratio = _compute_support_ratio(tickers)
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

    def clear(self):
        super().clear()
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








def _persistent_summary(ev: dict, with_return: list[dict], now_dt) -> dict:
    """Build a mover summary with days_since_event for the persistent section.

    Computes ``support_ratio`` from the same cleaned ticker list
    (``with_return``) that the caller already scrubbed + suppressed.
    This guarantees the agreement % matches the tickers shown on
    the card.  The caller (``_compute_persistent_slice``) runs both
    ``_scrub_implausible_ticker_returns`` and
    ``_suppress_duplicate_tickers`` before filtering to non-null
    ``return_5d`` — so ``with_return`` is the single source of truth.
    """
    support_ratio = _compute_support_ratio(with_return)
    summary = _build_mover_summary(ev, with_return, support_ratio)
    event_date = ev.get("event_date") or ev.get("timestamp", "")[:10]
    try:
        days_since = (now_dt - datetime.fromisoformat(event_date)).days
    except (ValueError, TypeError):
        days_since = 0
    summary["days_since_event"] = days_since
    return summary






# ---------------------------------------------------------------------------
# Re-exports for test compatibility — tests call these as api.XXX()
# ---------------------------------------------------------------------------

def analyze(req):
    """Thin proxy so ``api.analyze()`` keeps working in tests."""
    from routes.analyze import analyze as _impl
    return _impl(req)


def market_movers(limit: int = 5):
    """Thin proxy so ``api.market_movers()`` keeps working in tests."""
    from routes.movers import market_movers as _impl
    return _impl(limit=limit)


def news(limit: int = 0, offset: int = 0):
    """Thin proxy so ``api.news()`` keeps working in tests."""
    from routes.news import news as _impl
    return _impl(limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Route modules — each file registers its own APIRouter; included here
# so api.app carries the full endpoint set.
# ---------------------------------------------------------------------------

from routes.analyze import router as _analyze_router
from routes.events import router as _events_router
from routes.market import router as _market_router
from routes.movers import router as _movers_router
from routes.news import router as _news_router
from routes.portfolio import router as _portfolio_router
from routes.playbook import router as _playbook_router

app.include_router(_analyze_router)
app.include_router(_events_router)
app.include_router(_market_router)
app.include_router(_movers_router)
app.include_router(_news_router)
app.include_router(_portfolio_router)
app.include_router(_playbook_router)
