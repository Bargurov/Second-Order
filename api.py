"""
Thin FastAPI layer over the existing backend.

Run with:  uvicorn api:app --reload
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, NamedTuple, Optional
import io
import json as _json
import logging
import re
import time
import zipfile

# Configure news/cluster loggers to emit at INFO under uvicorn.
# Attach a stderr handler so messages appear in the console even when
# the root logger has no handler configured (common under uvicorn).
# ``propagate = False`` keeps these emissions from also reaching the
# structured root handler installed by ``logging_config.setup_logging``
# below, so the existing human-friendly bracketed format isn't doubled.
_so_handler = logging.StreamHandler()
_so_handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
for _ln in ("second_order.news", "second_order.cluster"):
    _lgr = logging.getLogger(_ln)
    _lgr.setLevel(logging.INFO)
    if not _lgr.handlers:
        _lgr.addHandler(_so_handler)
    _lgr.propagate = False

# Install the shared key=value root handler.  Idempotent — safe to
# import api.py from multiple entry points (tests, scripts, uvicorn)
# without stacking handlers.  Loggers that already have their own
# handler (the two above) keep their existing format.
from logging_config import setup_logging as _setup_logging  # noqa: E402
_setup_logging()

from fastapi import FastAPI, HTTPException, Query, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from db import (
    init_db, load_recent_events, load_events_since,
    load_events_market_checked_since, load_event_by_id,
    save_event, update_review, delete_event,
    find_related_events, load_news_cache, save_news_cache, find_cached_analysis,
    load_low_signal_headlines, find_historical_analogs, compute_track_record,
    append_revisit_snapshot, load_revisit_snapshots,
    get_confidence_calibration_stats,
    events_db_override, db_binding_is_live, get_db_path,
    link_candidate_analysis, load_analysis_result_snapshot,
    get_candidate_analysis_link, load_analysis_provenance,
)
from analysis_result_snapshot import apply_result_snapshot
from classify import classify_stage, classify_persistence
from analyze_event import (
    analyze_event, is_mock as _is_mock_analysis, _DEFAULT_MODEL,
    _normalize_if_persists, _normalize_currency_channel,
    AnalysisResult, PERSISTED_OVERLAY_FIELDS, build_analysis_dict,
)
from market_check import (
    market_check, followup_check, macro_snapshot, ticker_chart, ticker_info,
    compute_stress_regime, compute_rates_context, classify_decay,
    classify_policy_sensitivity,
    classify_inventory_context,
    build_macro_context_for_prompt,
    compute_pre_event_drift,
    _suppress_duplicate_tickers,
    _scrub_implausible_ticker_returns,
    normalize_spark,
)
from market_check_freshness import refresh_market_for_saved_event
import movers_cache
from real_yield_context import build_real_yield_context, sanitize_real_yield_context_block, classify_thesis
from overlay_sanitize import sanitize_overlay_block, sanitize_mover_card
from cross_asset_confirmation import compute_cross_asset_confirmation
from credit_regime import classify_credit_regime
from credit_transmission import compute_credit_transmission
from sector_passthrough import compute_sector_passthrough
from policy_constraint import compute_policy_constraint
from shock_decomposition import compute_shock_decomposition, sanitize_shock_decomposition_block
from reaction_function_divergence import compute_reaction_function_divergence
from narrative_divergence import compute_narrative_divergence
from regime_vector import build_regime_vector
from surprise_vs_anticipation import compute_surprise_vs_anticipation
from terms_of_trade import compute_terms_of_trade
from reserve_stress_overlay import compute_reserve_stress
import os
import hmac
from news_sources import fetch_all, cluster_headlines, normalize_headline

_log = logging.getLogger("second_order.api")

# ---------------------------------------------------------------------------
# Admin-token guard (Q4) — protects the paid /analyze and the mutating routes
# (events / portfolio / curated) on a public deploy.  The guard is INERT when
# ``SECOND_ORDER_ADMIN_TOKEN`` is unset (local dev / the existing test suite),
# so nothing else changes; set the token on a deploy to activate it (see
# render.yaml, where it is marked required).  No accounts, no sessions — a
# single shared secret compared in constant time.
# ---------------------------------------------------------------------------

_ADMIN_TOKEN_HEADER = "X-Second-Order-Admin-Token"


def _admin_token_configured() -> str:
    """The configured admin token, or "" when the guard is unconfigured."""
    return (os.getenv("SECOND_ORDER_ADMIN_TOKEN") or "").strip()


def _paid_analysis_enabled() -> bool:
    """True only when ENABLE_PAID_ANALYSIS is explicitly 'true'."""
    return (os.getenv("ENABLE_PAID_ANALYSIS") or "").strip().lower() == "true"


def _real_api_key_present() -> bool:
    """True when the SELECTED analysis provider (anthropic default or
    openai via ``ANALYSIS_PROVIDER``) has a real (non-placeholder) key —
    i.e. the process CAN make a billed call.  Uses the same provider
    resolution as dispatch (one source of truth), so the guard can never
    disagree with ``analyze_event`` about which key matters."""
    from analyze_event import resolve_provider_configuration
    return resolve_provider_configuration().billable


def require_admin_token(
    x_admin_token: str | None = Header(default=None, alias=_ADMIN_TOKEN_HEADER),
) -> None:
    """Guard for protected (mutating) operations.

    Inert when ``SECOND_ORDER_ADMIN_TOKEN`` is unset.  When set, the
    ``X-Second-Order-Admin-Token`` header must match it (constant-time) or the
    request is rejected with 403 before the handler runs.
    """
    admin = _admin_token_configured()
    if not admin:
        return
    if not x_admin_token or not hmac.compare_digest(x_admin_token, admin):
        raise HTTPException(status_code=403, detail="admin token required")


def require_paid_analysis(
    x_admin_token: str | None = Header(default=None, alias=_ADMIN_TOKEN_HEADER),
) -> None:
    """Fail-CLOSED guard for the paid ``/analyze`` endpoints.

    The ONLY unauthenticated path is local mock mode — no real (billable)
    key for the SELECTED analysis provider AND no configured admin token —
    where ``/analyze`` returns a mock and can never bill, so local dev /
    the test suite stay open.  Applies identically to every supported
    provider (anthropic and openai).

    In every other state the route CAN bill (a real key is present) or the
    deploy is protected (an admin token is configured), so BOTH conditions are
    required, checked before any provider call:
      * ``ENABLE_PAID_ANALYSIS=true`` (explicit opt-in), AND
      * a configured ``SECOND_ORDER_ADMIN_TOKEN`` matched by the request header.

    A missing admin token is NEVER a free pass when a real key is present —
    that was the prior fail-OPEN bug (it returned early when the token was
    unset, leaving a billable key unprotected).
    """
    admin = _admin_token_configured()
    if not _real_api_key_present() and not admin:
        # Local mock mode: no billing risk, no deploy protection expected.
        return
    if not _paid_analysis_enabled():
        raise HTTPException(
            status_code=403,
            detail="paid analysis disabled (set ENABLE_PAID_ANALYSIS=true)",
        )
    if not admin:
        raise HTTPException(
            status_code=403,
            detail="paid analysis requires SECOND_ORDER_ADMIN_TOKEN",
        )
    if not x_admin_token or not hmac.compare_digest(x_admin_token, admin):
        raise HTTPException(status_code=403, detail="admin token required")


# ---------------------------------------------------------------------------
# App & startup
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    # Dev / verification DB safety: when EVENTS_DB_FILE is unset the backend
    # falls back to the live events.db archive — warn so that live binding is
    # never silent.  Gated on db_binding_is_live() so the test-suite isolation
    # harness (which rebinds db.DB_FILE to a temp path) stays quiet, and an
    # explicit EVENTS_DB_FILE=events.db (a deliberate choice) does not warn.
    if events_db_override() is None and db_binding_is_live():
        _log.warning(
            "EVENTS_DB_FILE is unset — bound to the live events.db archive at "
            "%s. Set EVENTS_DB_FILE to a copy for dev / verification runs "
            "(see README 'Dev / verification DB safety').",
            get_db_path(),
        )
    # Q4 deploy-posture warning: serving with a real (billable) API key but no
    # admin token means the mutating + paid routes are UNPROTECTED.  Acceptable
    # for local dev; on a public deploy set SECOND_ORDER_ADMIN_TOKEN (render.yaml).
    if _real_api_key_present() and not _admin_token_configured():
        _log.warning(
            "Serving with a billable API key but SECOND_ORDER_ADMIN_TOKEN is "
            "unset — mutation and /analyze routes are UNPROTECTED. Set the "
            "token to protect a public deploy (see render.yaml).",
        )
    # Optional background snapshot refresh — gated by env var so the test
    # suite (which uses TestClient) does not spin up a background thread.
    if os.environ.get("MARKET_SNAPSHOTS_ENABLED", "").lower() in ("1", "true", "yes"):
        from market_snapshots import start_background_refresh
        try:
            interval = int(os.environ.get("MARKET_SNAPSHOTS_INTERVAL", "60"))
        except ValueError:
            interval = 60
        start_background_refresh(interval=interval)
    # Optional automatic revisit-snapshot collection.  Same opt-in pattern as
    # MARKET_SNAPSHOTS_ENABLED so test suites / local dev stay single-threaded
    # unless the operator explicitly enables the loop.
    if os.environ.get("AUTO_REVISIT_ENABLED", "").lower() in ("1", "true", "yes"):
        from auto_revisit import start_background_refresh as _start_revisit
        try:
            revisit_interval = int(os.environ.get("AUTO_REVISIT_INTERVAL", "3600"))
        except ValueError:
            revisit_interval = 3600
        _start_revisit(interval=revisit_interval)
    # Auto-backfill scheduler — dry-run only, disabled by default.  Both
    # ENABLE_AUTO_BACKFILL and ENABLE_PAID_ANALYSIS must be true for the
    # scheduler to start; otherwise this is a no-op.  Boot failures are
    # logged and swallowed so the app keeps serving requests.  The
    # contract is pinned in tests/test_auto_backfill_lifespan_wiring.py
    # (real api.app) and tests/test_auto_backfill_lifespan_plan.py
    # (harness-level spec).
    _start_auto_backfill_scheduler(app)
    yield
    # Stop background threads cleanly on shutdown (no-op if they never started).
    from market_snapshots import stop_background_refresh
    stop_background_refresh()
    from auto_revisit import stop_background_refresh as _stop_revisit
    _stop_revisit()
    _stop_auto_backfill_scheduler(app)


def _start_auto_backfill_scheduler(app: FastAPI) -> None:
    """Boot the dry-run auto-backfill scheduler under both env gates.

    No-op when:
      * ``ENABLE_AUTO_BACKFILL`` is unset / false → ``effective_status="disabled"``
      * ``ENABLE_PAID_ANALYSIS`` is unset / false → ``effective_status="blocked_paid_guard"``

    On a successful start, the scheduler is published to
    ``app.state.auto_backfill_scheduler`` so the shutdown half can stop
    it.  Pre-start ordering is load-bearing: the attribute is set ONLY
    after :func:`start_auto_backfill_scheduler` returns, so a start
    exception leaves nothing for the shutdown half to touch.

    Boot failures (config load, factory raise, start raise) are logged
    and swallowed; the app keeps serving requests.
    """
    try:
        from auto_backfill_config import load_auto_backfill_config
        cfg = load_auto_backfill_config()
    except Exception:
        _log.warning(
            "auto_backfill: config load failed; app continues",
            exc_info=True,
        )
        return

    if cfg.effective_status != "configured":
        if cfg.effective_status == "blocked_paid_guard":
            _log.warning(
                "auto_backfill: ENABLE_AUTO_BACKFILL=true but "
                "ENABLE_PAID_ANALYSIS is false; not scheduling.",
            )
        return

    try:
        from auto_backfill_scheduler import (
            create_auto_backfill_scheduler,
            start_auto_backfill_scheduler,
        )
        scheduler = create_auto_backfill_scheduler(config=cfg)
        start_auto_backfill_scheduler(scheduler)
    except Exception:
        _log.warning(
            "auto_backfill: scheduler boot failed; app continues",
            exc_info=True,
        )
        return

    # Pre-start ordering: publish to app.state ONLY after start
    # returned successfully.  A half-started scheduler must never
    # land here.
    app.state.auto_backfill_scheduler = scheduler


def _stop_auto_backfill_scheduler(app: FastAPI) -> None:
    """Stop the auto-backfill scheduler if one was published at boot.

    No-op when no scheduler was created (disabled / paid-guard / boot
    failure).  ``stop`` exceptions are logged and swallowed so a buggy
    shutdown does not crash the FastAPI shutdown path.
    """
    scheduler = getattr(app.state, "auto_backfill_scheduler", None)
    if scheduler is None:
        return
    try:
        from auto_backfill_scheduler import stop_auto_backfill_scheduler
        stop_auto_backfill_scheduler(scheduler)
    except Exception:
        _log.warning(
            "auto_backfill: scheduler stop raised; ignoring",
            exc_info=True,
        )
    finally:
        # Drop the reference so a follow-on lifespan boot starts clean.
        # Starlette's ``State.__delattr__`` raises ``KeyError`` on a
        # missing key (not ``AttributeError``); guard both so the
        # cleanup is a true no-op when nothing was published.
        try:
            delattr(app.state, "auto_backfill_scheduler")
        except (AttributeError, KeyError):
            pass


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

# ---------------------------------------------------------------------------
# News cache shape guard
# ---------------------------------------------------------------------------
# The news payload is persisted to SQLite and reloaded on process start.  If
# the payload shape drifts (cluster list renamed, missing meta keys) a stale
# cache row can silently break the Headlines flow — the route keeps serving
# the degraded dict until a manual refresh.  _NEWS_CACHE_VERSION + the
# _is_valid_news_payload guard catch that on load so a shape mismatch
# triggers a refresh instead of leaking into the UI.

_NEWS_CACHE_VERSION = 1

# The one key that must be present AND list-shaped.  ``clusters`` is the
# only field the /news route iterates directly — if it's missing or the
# wrong type, the route silently degrades to an empty response and the
# Headlines UI goes blank.  Every other field (feed_status, refresh_meta,
# total_headlines) is tolerate-missing because the route synthesizes
# sensible defaults for them via ``.get(..., default)``.
_NEWS_PAYLOAD_REQUIRED_LIST_KEYS: tuple[str, ...] = (
    "clusters",
)


def _is_valid_news_payload(payload: Any) -> bool:
    """Shape guard for cached news payloads.

    A payload passes when ``clusters`` is present as a list and the
    ``_schema_version`` (when present) matches the current
    ``_NEWS_CACHE_VERSION``.  The version field is tolerated-missing
    on legacy rows so a one-way upgrade works: a cache written before
    the guard shipped is treated as version 1 if its shape checks out.

    Deliberately narrow.  The /news route tolerates every other field
    being missing via ``.get(..., default)``; a guard that forces a
    refresh whenever a legacy row omits one of those would re-fetch
    on every boot without any real integrity benefit.
    """
    if not isinstance(payload, dict):
        return False
    for key in _NEWS_PAYLOAD_REQUIRED_LIST_KEYS:
        if not isinstance(payload.get(key), list):
            return False
    stamped = payload.get("_schema_version")
    if stamped is not None and stamped != _NEWS_CACHE_VERSION:
        return False
    return True

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

    if not clusters and records:
        _log.warning(
            "incremental refresh returned 0 clusters from %d records; "
            "falling back to full recluster",
            len(records),
        )
        clusters = cluster_headlines(records)
        refresh_meta = {"source": "full_recluster_fallback", "known": 0,
                        "new": len(records), "merged": 0,
                        "created": len(clusters), "reused": 0}

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
        # Shape-guard stamp — see _is_valid_news_payload.  Bump
        # _NEWS_CACHE_VERSION whenever the payload contract changes so stale
        # rows from prior shapes are discarded on load.
        "_schema_version": _NEWS_CACHE_VERSION,
    }
    _news_cache["data"] = payload
    _news_cache["ts"] = time.monotonic()
    try:
        save_news_cache(payload)
    except Exception as e:
        print(f"[api] save_news_cache failed: {e}")
    return payload


class NewsCacheState(NamedTuple):
    """Read-only snapshot of the LOCAL news cache — never refreshes or writes.

    ``availability``:
      "available"   — a shape-valid payload within the freshness TTL
      "stale"       — a shape-valid payload past the TTL (still served)
      "unavailable" — no shape-valid local payload (missing or malformed)
    ``source`` is ``"memory"`` / ``"persisted"`` / ``"none"``;
    ``refresh_required`` is True whenever availability is not "available".
    """

    availability: str
    payload: dict | None
    source: str
    last_updated_at: str | None
    refresh_required: bool


def _payload_last_updated(payload: dict) -> str | None:
    return (payload.get("refresh_meta") or {}).get("last_successful_refresh")


def _safe_load_news_cache(max_age_seconds: int | None) -> dict | None:
    """load_news_cache that swallows failures — a read must never raise.

    ``max_age_seconds=None`` reads the stored payload at any age (used for the
    stale fallback: age never turns a shape-valid local payload unavailable).
    """
    try:
        return load_news_cache(max_age_seconds=max_age_seconds)
    except Exception:
        _log.warning("load_news_cache failed during cache-only read",
                     exc_info=True)
        return None


def read_news_cache_state() -> NewsCacheState:
    """Inspect the local news cache WITHOUT refreshing, fetching, or writing.

    Checks the in-memory hot layer, then the persistent SQLite layer, each
    validated by ``_is_valid_news_payload``.  A shape-valid payload within the
    TTL is "available"; a shape-valid but older payload is "stale" and still
    served; a missing or malformed payload is "unavailable".  The refresh
    owner (``_fetch_fresh_news`` via ``POST /news/refresh``) is NEVER invoked
    here — that is what makes every GET consumer cache-only, and what closes
    the prior read-through that reached RSS and wrote SQLite from a GET.

    Pure: it reads module/DB state but mutates nothing (no cache warming, no
    SQLite/cache write, no refresh-lock).
    """
    now = time.monotonic()
    hot = _news_cache.get("data")
    hot_ts = _news_cache.get("ts", 0.0)
    hot_valid = hot is not None and _is_valid_news_payload(hot)
    if hot_valid and (now - hot_ts) < _NEWS_TTL_SECONDS:
        return NewsCacheState("available", hot, "memory",
                              _payload_last_updated(hot), False)

    fresh = _safe_load_news_cache(_NEWS_TTL_SECONDS)
    if fresh is not None and _is_valid_news_payload(fresh):
        return NewsCacheState("available", fresh, "persisted",
                              _payload_last_updated(fresh), False)

    # Read the persisted payload at ANY age: a shape-valid row past the TTL is
    # served as stale regardless of how old it is — age never turns valid local
    # evidence into "unavailable".  Only a missing or shape-invalid row is.
    stored = _safe_load_news_cache(None)
    if stored is not None and _is_valid_news_payload(stored):
        return NewsCacheState("stale", stored, "persisted",
                              _payload_last_updated(stored), True)

    if hot_valid:
        # Persistent layer unusable, but a shape-valid (older) hot payload
        # exists — serve it as stale rather than claim unavailable.
        return NewsCacheState("stale", hot, "memory",
                              _payload_last_updated(hot), True)

    return NewsCacheState("unavailable", None, "none", None, True)


def _unavailable_news_payload() -> dict:
    """Empty, shape-valid payload for the 'no valid local cache' state.

    Kept shape-identical to a normal payload (clusters / total_headlines /
    feed_status / refresh_meta / _schema_version) so the non-route consumers
    that read only ``clusters`` stay byte-stable.  ``refresh_meta.status`` is
    ``"error"`` with an explicit message so the existing frontend renders it
    as not-successful (never a silent empty feed); the /news route also
    surfaces ``availability="unavailable"`` as the authoritative signal.
    """
    return {
        "clusters": [],
        "total_headlines": 0,
        "feed_status": [],
        "refresh_meta": {
            "status": "error", "source": "none",
            "known": 0, "new": 0, "merged": 0, "created": 0, "reused": 0,
            "ok_feeds": 0, "fail_feeds": 0,
            "error": "No local news cache — POST /news/refresh to load",
            "last_successful_refresh": None, "freshness": "stale",
        },
        "_schema_version": _NEWS_CACHE_VERSION,
    }


def _get_news_cached() -> dict:
    """Return the best available LOCAL news payload WITHOUT ever refreshing.

    Cache-only: delegates to ``read_news_cache_state`` and never calls
    ``_fetch_fresh_news`` (no RSS ``fetch_all``, no cluster-store write, no
    SQLite/cache write, no refresh-lock).  All five GET consumers share this
    reader, so the GET/provider boundary holds everywhere; refresh ownership
    stays with ``POST /news/refresh``.  When no shape-valid local payload
    exists the return is an explicit empty payload (``clusters == []``); the
    /news route surfaces the honest availability separately so an empty valid
    feed is never confused with unavailable local data.
    """
    state = read_news_cache_state()
    if state.payload is not None:
        return state.payload
    return _unavailable_news_payload()


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
    """Return the model ID that analyze_event will use.

    Delegates to ``analyze_event._selected_model`` so provider/model
    selection has one source of truth (no drifting inline copy here).
    """
    from analyze_event import _selected_model
    return _selected_model()


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
    # A message-less provider exception reaches _mock(str(e)) with str(e) == "",
    # producing what_changed == "[mock: ]" and an empty extracted reason.  The
    # streamed handled-failure terminal must always carry a non-empty,
    # human-readable failure_reason: the frontend validator rejects an empty one
    # (a genuine handled failure would otherwise be demoted to an invalid/
    # incomplete terminal), so never emit an empty reason.
    reason = reason or "model unavailable"
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
        # Persisted overlays flow through _sanitize_floats at the read boundary
        # (not just the response wrap) so any NaN/inf carried on a legacy row
        # is neutralised on every frozen read, consistent with the block-level
        # magnitude sanitizers for shock_decomposition / real_yield_context.
        # Every persisted overlay flows through sanitize_overlay_block so
        # frozen-archive reads carry the same { available, stale, degraded,
        # degraded_reason } contract as live composer output.  Silent empty
        # dicts are replaced with explicit degraded markers so the UI can
        # render a consistent "data unavailable" pill instead of skipping.
        #
        # The two overlays with block-specific magnitude caps
        # (shock_decomposition, real_yield_context) still run their own
        # scrubbers first; the generic layer then adds the marker fields
        # on top.
        inventory_context = sanitize_overlay_block(
            cached.get("inventory_context"), name="inventory_context",
        )
        policy_sensitivity = sanitize_overlay_block(
            cached.get("policy_sensitivity"), name="policy_sensitivity",
        )
        real_yield_ctx = sanitize_overlay_block(
            sanitize_real_yield_context_block(cached.get("real_yield_context") or {}),
            name="real_yield_context",
        )
        policy_constraint_ctx = sanitize_overlay_block(
            cached.get("policy_constraint"), name="policy_constraint",
        )
        # Scrub persisted shock-decomposition blocks: events saved before the
        # nominal-yield unit fix may carry move_5d values like +2680% from
        # _safe_pct applied to near-zero historical ^TNX cache rows.
        shock_decomp_ctx = sanitize_overlay_block(
            sanitize_shock_decomposition_block(cached.get("shock_decomposition") or {}),
            name="shock_decomposition",
        )
        reaction_div_ctx = sanitize_overlay_block(
            cached.get("reaction_function_divergence"),
            name="reaction_function_divergence",
        )
        surprise_ctx = sanitize_overlay_block(
            cached.get("surprise_vs_anticipation"), name="surprise_vs_anticipation",
        )
        terms_of_trade_ctx = sanitize_overlay_block(
            cached.get("terms_of_trade"), name="terms_of_trade",
        )
        reserve_stress_ctx = sanitize_overlay_block(
            cached.get("reserve_stress"), name="reserve_stress",
        )
        narrative_div_ctx = sanitize_overlay_block(
            cached.get("narrative_divergence"), name="narrative_divergence",
        )
        # Credit regime — persisted; serve the reading captured at analysis time.
        credit_regime_ctx = sanitize_overlay_block(
            cached.get("credit_regime"), name="credit_regime",
        )
        # Credit transmission — persisted alongside credit_regime; frozen events
        # served the reading captured at analysis time (equity-vs-credit and
        # funding-stress verdicts derived from that day's stress + rates tape).
        credit_transmission_ctx = sanitize_overlay_block(
            cached.get("credit_transmission"), name="credit_transmission",
        )
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
        # Shock-decomposition first so its rates_pack is available for the
        # policy_constraint front-end-repricing detector.
        try:
            shock_decomp_ctx = compute_shock_decomposition(
                rates_live, stress_live, snapshots=None,
            )
        except Exception:
            _log.warning("shock_decomposition failed (cached rebuild)", exc_info=True)
            shock_decomp_ctx = {}
        # Macro-release enrichment — best-effort; policy_constraint still
        # works without it.
        _macro_releases_live: list | None = None
        try:
            from macro_calendar import get_macro_releases
            from macro_surprise import classify_macro_surprise
            _releases = get_macro_releases()
            _clusters = (_get_news_cached() or {}).get("clusters") or []
            _macro_releases_live = classify_macro_surprise(_releases, _clusters)
        except Exception:
            _log.warning(
                "policy_constraint: macro-release enrichment failed (cached rebuild)",
                exc_info=True,
            )
            _macro_releases_live = None
        try:
            policy_constraint_ctx = compute_policy_constraint(
                headline, mech_text, rates_live, stress_live, snapshots=None,
                macro_releases=_macro_releases_live,
                rates_pack=(shock_decomp_ctx or {}).get("rates_pack"),
            )
        except Exception:
            _log.warning("policy_constraint failed (cached rebuild)", exc_info=True)
            policy_constraint_ctx = {}
        try:
            reaction_div_ctx = compute_reaction_function_divergence(
                headline, mech_text, rates_live, stress_live, snapshots=None,
            )
        except Exception:
            _log.warning("reaction_function_divergence failed (cached rebuild)", exc_info=True)
            reaction_div_ctx = {}

        # Credit regime needs to feed build_regime_vector's new `credit`
        # axis, so classify it here instead of waiting for the
        # reserve-stress block below.  The rebuild block further down
        # re-reads analysis-level credit_regime_ctx from this same value.
        try:
            _raw_live_pre = (stress_live or {}).get("raw") or {}
            _pre_credit_regime = classify_credit_regime(
                hy_5d=_raw_live_pre.get("hyg_5d"),
                ig_5d=_raw_live_pre.get("lqd_5d"),
                shy_5d=_raw_live_pre.get("shy_5d"),
            )
        except Exception:
            _log.warning("credit_regime pre-pass failed (cached rebuild)", exc_info=True)
            _pre_credit_regime = None

        try:
            current_regime_vec = build_regime_vector(
                rates_live, stress_live, None,
                credit_regime=_pre_credit_regime,
            )
        except Exception:
            _log.warning("regime_vector failed (cached rebuild)", exc_info=True)
            current_regime_vec = None

        # Compound regime + transition detection using the last ~25 saved
        # events as baseline.  Additive enrichment: the underlying vector
        # is already usable for rerank; this layer adds the macro-real
        # label (reflation / stagflation pulse / …) and the
        # stable/shifting/flipping transition verdict.
        try:
            from regime_compound import (
                baseline_from_events, enrich_with_compound_regime,
            )
            _baseline = baseline_from_events(load_recent_events(limit=25))
            current_regime_vec = enrich_with_compound_regime(
                current_regime_vec, _baseline,
            )
        except Exception:
            _log.warning("compound_regime enrichment failed (cached rebuild)",
                         exc_info=True)

        # Pre-event drift leading up to the stored event_date — empirically
        # grounds the "already priced" read rather than leaning on stage alone.
        pre_drift_live: dict[str, float] = {}
        try:
            drift_symbols = [t.get("symbol") for t in tickers
                             if isinstance(t, dict) and t.get("symbol")]
            if drift_symbols:
                pre_drift_live = compute_pre_event_drift(
                    drift_symbols, cached.get("event_date"),
                )
        except Exception:
            _log.warning("compute_pre_event_drift failed (cached rebuild)", exc_info=True)
            pre_drift_live = {}

        try:
            surprise_ctx = compute_surprise_vs_anticipation(
                cached.get("stage", ""),
                tickers=tickers,
                stress_regime=stress_live,
                pre_event_drift=pre_drift_live,
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

        # Credit regime — already classified above for the regime_vector
        # credit axis.  Reuse the same dict so the reserve-stress pressure
        # score and the stored credit_regime both reflect the identical
        # live HY/IG/SHY tape.  Falls back to the cached value only when
        # the pre-pass genuinely failed.
        credit_regime_ctx = _pre_credit_regime or cached.get("credit_regime") or {}

        # Reserve-stress overlay — pure composer over the terms-of-trade,
        # rates, stress, and credit_regime blocks we already have.
        try:
            reserve_stress_ctx = compute_reserve_stress(
                headline,
                mech_text,
                terms_of_trade=terms_of_trade_ctx,
                rates_context=rates_live,
                stress_regime=stress_live,
                credit_regime=credit_regime_ctx,
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

        # Credit transmission — refresh the funding-stress / equity-vs-credit
        # read against today's stress + rates context, using the regenerated
        # credit_regime above.
        try:
            credit_transmission_ctx = compute_credit_transmission(
                credit_regime=credit_regime_ctx,
                stress_regime=stress_live,
                rates_context=rates_live,
            )
        except Exception:
            _log.warning("credit_transmission failed (cached rebuild)", exc_info=True)
            credit_transmission_ctx = cached.get("credit_transmission") or {}

    # Cross-asset confirmation — compute on every cache read from whichever
    # shock_decomposition/thesis inputs are in hand.  Not persisted separately
    # because it's a pure function of already-persisted inputs.
    try:
        _sd_for_cx = shock_decomp_ctx or {}
        _thesis = classify_thesis(headline, mech_text).get("thesis", "none")
        cross_asset_ctx = compute_cross_asset_confirmation(
            _thesis,
            _sd_for_cx.get("channels") or {},
            rates_pack=_sd_for_cx.get("rates_pack"),
        )
    except Exception:
        _log.warning("cross_asset_confirmation failed (cached rebuild)", exc_info=True)
        cross_asset_ctx = {}

    # Sector passthrough — derived from already-persisted inputs (tickers +
    # mechanism text + shock_decomposition primary).  Computed on every cache
    # read so the downstream cascade reflects the same mechanism as the
    # stored event.
    try:
        sector_passthrough_ctx = compute_sector_passthrough(
            beneficiary_tickers=cached.get("beneficiary_tickers") or [],
            loser_tickers=cached.get("loser_tickers") or [],
            mechanism_text=mech_text,
            shock_primary=(shock_decomp_ctx or {}).get("primary"),
        )
    except Exception:
        _log.warning("sector_passthrough failed (cached rebuild)", exc_info=True)
        sector_passthrough_ctx = {}

    # Assemble the analysis block via the shared registry-driven builder so
    # every PERSISTED_OVERLAY_FIELD flows through consistently on both the
    # frozen-archive and live-recompute branches.  Overrides carry the
    # (possibly recomputed) overlay values; anything not overridden falls back
    # to the stored event's decoded dict.  regime_snapshot stays on `cached`
    # intentionally — current_regime_vec is only used for analog re-ranking
    # and must not clobber the stored historical snapshot.
    overlay_overrides = {
        "policy_sensitivity":           policy_sensitivity,
        "inventory_context":            inventory_context,
        "real_yield_context":           real_yield_ctx,
        "policy_constraint":            policy_constraint_ctx,
        "shock_decomposition":          shock_decomp_ctx,
        "reaction_function_divergence": reaction_div_ctx,
        "surprise_vs_anticipation":     surprise_ctx,
        "terms_of_trade":               terms_of_trade_ctx,
        "reserve_stress":               reserve_stress_ctx,
        "narrative_divergence":         narrative_div_ctx,
        "credit_regime":                credit_regime_ctx,
        "credit_transmission":          credit_transmission_ctx,
    }
    analysis_block = build_analysis_dict(cached, overlay_overrides)
    # Derived fields that depend on live ticker data / historical analogs are
    # injected after the registry-driven build.
    analysis_block["beneficiary_tickers"] = [
        t["symbol"] for t in tickers if t.get("role") == "beneficiary"
    ]
    analysis_block["loser_tickers"] = [
        t["symbol"] for t in tickers if t.get("role") == "loser"
    ]
    # Macro release context — persisted on the row; coerced to canonical
    # shape so the frontend sees the same keyset on cache hits as on fresh
    # /analyze responses.
    try:
        from macro_surprise import coerce_macro_release_context
        analysis_block["macro_release_context"] = coerce_macro_release_context(
            cached.get("macro_release_context"),
        )
    except Exception:
        analysis_block["macro_release_context"] = {}
    # Policy timing context — same coercion pattern.
    try:
        from policy_timing import coerce_policy_timing_context
        analysis_block["policy_timing_context"] = coerce_policy_timing_context(
            cached.get("policy_timing_context"),
        )
    except Exception:
        analysis_block["policy_timing_context"] = {}
    # Country vulnerability context — same coercion pattern.
    try:
        from country_backdrop import coerce_country_vulnerability_context
        analysis_block["country_vulnerability_context"] = (
            coerce_country_vulnerability_context(
                cached.get("country_vulnerability_context"),
            )
        )
    except Exception:
        analysis_block["country_vulnerability_context"] = {}
    analysis_block["cross_asset_confirmation"] = cross_asset_ctx
    analysis_block["sector_passthrough"] = sector_passthrough_ctx
    _raw_analogs = find_historical_analogs(
        headline,
        mechanism=cached.get("mechanism_summary", ""),
        stage=cached.get("stage", ""),
        persistence=cached.get("persistence", ""),
        exclude_headline=headline,
        current_regime_vector=current_regime_vec,
        current_event_mechanism={
            "mechanism_family": cached.get("mechanism_family"),
            "transmission_path": cached.get("transmission_path"),
            "expected_first_order_channels": cached.get("expected_first_order_channels"),
        },
    )
    # Enrich each analog with structured match dimensions (mechanism
    # family, overall regime, inflation/rates, credit) + a topic-vs-regime
    # mismatch flag so the UI can render "why this analog rhymes (or
    # doesn't)" without parsing the legacy match_reason prose.
    try:
        from analog_explainer import explain_analogs as _explain_analogs
        analysis_block["historical_analogs"] = _explain_analogs(
            _raw_analogs,
            current_regime=current_regime_vec,
            current_mechanism_family=cached.get("mechanism_family") or "none",
        )
    except Exception:
        _log.warning("analog_explainer failed (cached rebuild); "
                     "serving raw analogs", exc_info=True)
        analysis_block["historical_analogs"] = _raw_analogs

    # Sibling evidence blocks for the saved-event restore — the same
    # reads GET /events/{id} attaches, so a saved event re-opened in
    # AnalysisView shows the same validation / reaction-profile blocks
    # (and the F1 v2 caveat) as event detail.  Read-only:
    # score_validation_status is a pure tape read of the stored
    # market_tickers; build_reaction_profile_v1 hydrates per-ticker
    # profiles from the price_cache (read_window_no_fetch — no provider,
    # no DB write).  Nested under ``analysis`` (not a new top-level key)
    # so the fresh/cached top-level key-parity contract
    # (test_freeze_policy_contract) stays intact; the frontend reads them
    # via result.analysis.validation_status_v2 / .reaction_profile_v1.
    # Unwrapped to mirror the detail route (routes/events.get_event_detail).
    from validation_status import score_validation_status
    from reaction_profile_hydration import build_reaction_profile_v1
    analysis_block["validation_status_v2"] = score_validation_status(cached)
    analysis_block["reaction_profile_v1"] = build_reaction_profile_v1(cached)

    # A1-3R: restore the saved mechanism-and-resolution output.  Applied LAST
    # so the saved values win over the empty column defaults a legacy write
    # left behind — but only over the snapshot's own fields, so the macro
    # overlay freeze policy and the detail-read blocks above are untouched.
    # An absent or tampered snapshot leaves the legacy columns speaking for
    # themselves; nothing is recomputed and no provider is reached.
    analysis_block = apply_result_snapshot(
        analysis_block, load_analysis_result_snapshot(cached.get("id")))

    response = {
        "headline":    headline,
        "stage":       cached["stage"],
        "persistence": cached["persistence"],
        "analysis":    analysis_block,
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
        # Cached responses never re-attempt persistence, so these always
        # report a clean state.  Carrying the keys keeps the cached/fresh
        # parity contract (test_freeze_policy_contract) intact.
        "persistence_failed": False,
        "persistence_error":  None,
        # The row this response was restored from.  A free read links
        # nothing — an inbox candidate is linked only by the run that
        # actually produced the analysis — so candidate_link stays None.
        "analysis_event_id": cached.get("id"),
        "candidate_link": None,
        # A1-2 Analysis Basis.  Attached HERE rather than at each call site so
        # both cached paths (by event_id and by headline) and the fresh path
        # carry the same top-level keys by construction — the fresh/cached
        # parity contract has no exceptions to remember.
        "provenance": provenance_summary_for_event(cached.get("id")),
    }
    return _sanitize_floats(response)


def provenance_summary_for_event(analysis_event_id: object) -> dict:
    """Read-only Analysis Basis summary for one saved analysis.

    Never calls a provider and never writes: it reads the stored snapshot,
    rebuilds the CURRENT basis from local state, and reports the comparison.
    A stale or invalid result is surfaced as-is, never repaired and never
    used to trigger a re-run.
    """
    import analysis_provenance as _ap

    def _legacy() -> dict:
        return _ap.summarize_for_response(
            None, _ap.derive_provenance_state(None, None))

    if analysis_event_id is None:
        return _legacy()
    try:
        import db as _dbm
        stored = _dbm.load_analysis_provenance(int(analysis_event_id))
    except Exception:
        _log.warning("provenance read failed", exc_info=True)
        return _legacy()
    if stored is None:
        return _legacy()

    current = None
    if not _ap.verify_provenance(stored):
        # Only worth rebuilding the current basis for an intact record — a
        # tampered one is INVALID regardless of what current state says.
        try:
            from analyze_event import (
                SYSTEM_PROMPT, render_analysis_prompt,
                resolve_provider_configuration,
            )
            from event_inbox import read_cluster_rows
            import db as _dbm
            rows, _reason = read_cluster_rows(_dbm.DB_FILE)
            snapshot = None
            if rows is not None:
                snapshot = _ap.build_candidate_snapshot(
                    rows, stored.get("parent_cluster_id"),
                    stored.get("title_key"))
            if snapshot is not None:
                current = _ap.current_analysis_basis(
                    candidate_snapshot=snapshot,
                    candidate_context_snapshot=stored.get("candidate_context_snapshot", ""),
                    macro_context_snapshot=stored.get("macro_context_snapshot", ""),
                    provider=resolve_provider_configuration().provider,
                    model=_active_model(),
                    system_prompt_snapshot=SYSTEM_PROMPT,
                    rendered_user_prompt_snapshot=render_analysis_prompt(
                        headline=stored.get("candidate_headline", ""),
                        stage=stored.get("stage", ""),
                        persistence=stored.get("persistence", ""),
                        event_context=stored.get("candidate_context_snapshot", ""),
                        macro_context=stored.get("macro_context_snapshot", ""),
                    ),
                )
        except Exception:
            _log.warning("current provenance basis rebuild failed", exc_info=True)
            current = None
    return _ap.summarize_for_response(
        stored, _ap.derive_provenance_state(stored, current))


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
) -> tuple[str | None, int | None]:
    """Build an event record from analysis results and save to the DB.

    Returns ``(error, analysis_event_id)`` — ``(None, id)`` on success, or
    ``(short error string, None)`` on failure.  The id is what the candidate
    linkage is stamped with, so a failed save can never produce one.

    Existing callers (``/analyze``, ``/analyze/stream``, movers backfill)
    rely on this function never raising past its
    boundary, so the failure is surfaced via the return value instead
    — callers can surface it as a ``persistence_failed`` flag.

    Every macro overlay block the /analyze pipeline produces is
    persisted so the frozen-cached response path can surface the
    exact macro snapshot the event was analysed under — without
    re-running live-macro computations against the current tape.
    """
    event_record = _build_event_record(
        headline, stage, persistence, analysis, mkt, effective_date,
        model=model)
    try:
        saved_id = save_event(event_record)
    except Exception as e:
        # Caller (typically /analyze or /analyze/stream) surfaces
        # this as ``persistence_failed: True`` so the response is
        # never silently reported as a clean save.  The exception is
        # NOT re-raised — every existing caller depends on this
        # function not raising past its boundary.
        _log.warning("save_event failed: %s", e, exc_info=True)
        return f"{type(e).__name__}: {e}", None
    # Bust the today-movers in-memory cache so /movers/today reflects
    # the new event without waiting for the 5-minute TTL to expire.
    _TODAYS_MOVERS_CACHE["data"] = None
    return None, saved_id


def _build_event_record(
    headline: str, stage: str, persistence: str,
    analysis: AnalysisResult, mkt: dict, effective_date: str,
    model: str | None = None,
) -> dict:
    """Assemble the ``events`` row payload from one analysis result.

    Extracted from :func:`_persist_event` so the A1-2 candidate path — which
    inserts the row and its provenance snapshot in one transaction — builds
    the SAME record, rather than maintaining a second copy that could drift.
    Pure: builds and returns, never writes.
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
    # Per-event macro-release context — best-effort build from the
    # calendar + release-facts cache.  Headlines that don't map to an
    # in-window release persist as ``{}`` and get coerced to the
    # stable empty shape at the HTTP boundary.  Also mirrored onto
    # the in-memory ``analysis`` dict so the fresh /analyze response
    # surfaces the block alongside the cached-reconstruction path.
    try:
        from macro_surprise import build_event_macro_release_context
        _block = build_event_macro_release_context(
            {"headline": headline, "event_date": effective_date},
        )
        event_record["macro_release_context"] = _block
        if isinstance(analysis, dict):
            analysis["macro_release_context"] = _block
    except Exception:
        _log.warning(
            "persist: macro_release_context build failed", exc_info=True,
        )
        event_record["macro_release_context"] = {}
    # Per-event policy timing context — same contract: best-effort
    # build, headlines with no tracked-policy keyword land as ``{}``,
    # coerced at the HTTP boundary.  Mirrored onto ``analysis`` so the
    # fresh /analyze response carries the block alongside the cached
    # path (handled in _build_cached_response).
    try:
        from policy_timing import build_event_policy_timing_context
        _pt_block = build_event_policy_timing_context(
            {"headline": headline, "event_date": effective_date},
        )
        event_record["policy_timing_context"] = _pt_block
        if isinstance(analysis, dict):
            analysis["policy_timing_context"] = _pt_block
    except Exception:
        _log.warning(
            "persist: policy_timing_context build failed", exc_info=True,
        )
        event_record["policy_timing_context"] = {}
    # Per-event country vulnerability context — scan headline + mechanism
    # summary for a profiled country; unmatched rows persist as ``{}``.
    try:
        from country_backdrop import build_event_country_vulnerability_context
        _cv_block = build_event_country_vulnerability_context({
            "headline":          headline,
            "mechanism_summary": (analysis or {}).get("mechanism_summary", "")
            if isinstance(analysis, dict) else "",
        })
        event_record["country_vulnerability_context"] = _cv_block
        if isinstance(analysis, dict):
            analysis["country_vulnerability_context"] = _cv_block
    except Exception:
        _log.warning(
            "persist: country_vulnerability_context build failed",
            exc_info=True,
        )
        event_record["country_vulnerability_context"] = {}
    return event_record


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
    confirm_paid: bool = Field(
        False,
        description=(
            "Explicit operator confirmation that a provider call may be made. "
            "A cache MISS without this fails closed with "
            "'paid_confirmation_required' and never reaches a provider; a "
            "cache hit is served regardless because it costs nothing."
        ),
    )
    candidate_id: Optional[str] = Field(
        None, max_length=128,
        description=(
            "Strict Automatic Event Inbox candidate identity (``aei-*``). "
            "Never a substitute for the numeric ``event_id``."
        ),
    )
    parent_cluster_id: Optional[int] = Field(
        None, ge=1,
        description="Stored semantic-parent cluster id — provenance only.",
    )
    title_key: Optional[str] = Field(
        None, max_length=500,
        description="Strict ``_dedup_key`` identity the candidate partition uses.",
    )
    force: bool = Field(
        False,
        description=(
            "Bypass the event-age freeze policy on cached responses. "
            "Use when an archive review needs the full live macro recompute."
        ),
    )

    @model_validator(mode="after")
    def _candidate_identity_is_all_or_none(self) -> "AnalyzeRequest":
        """Candidate identity is a unit: partial identity is rejected.

        A half-supplied identity would let the route link an analysis to a
        candidate it cannot verify, so the boundary refuses it (422) rather
        than guessing.  ``candidate_id`` must also recompute from
        ``(parent_cluster_id, title_key)`` — it is derived, never asserted.
        """
        present = [f for f in ("candidate_id", "parent_cluster_id", "title_key")
                   if getattr(self, f) is not None]
        if present and len(present) != 3:
            raise ValueError(
                "candidate_id, parent_cluster_id and title_key must be "
                "supplied together (got: " + ", ".join(sorted(present)) + ")")
        if present:
            from event_inbox import candidate_event_id
            expected = candidate_event_id(self.parent_cluster_id, self.title_key)
            if self.candidate_id != expected:
                raise ValueError(
                    "candidate_id does not recompute from parent_cluster_id "
                    "and title_key")
        return self


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: Optional[str] = Field(None, pattern=r"^(good|mixed|poor)$")
    notes: Optional[str] = Field(None, max_length=5000)


class NewsRefreshRequest(BaseModel):
    """Body schema for POST /news/refresh. The endpoint takes no arguments;
    the strict schema (extra='forbid') rejects unknown fields at the boundary
    instead of silently ignoring them."""
    model_config = ConfigDict(extra="forbid")


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





def _format_horizon_checkpoints_text(hc: dict) -> list[str]:
    """Render horizon_checkpoints as plain-text lines.  Returns [] when
    the block is missing or empty so callers can skip the section."""
    if not isinstance(hc, dict):
        return []
    horizons = hc.get("horizons") or []
    if not isinstance(horizons, list) or not horizons:
        return []
    lines: list[str] = ["HORIZON CHECKPOINTS"]
    tp = hc.get("timing_profile")
    if tp and tp != "unknown":
        lines.append(f"  Timing profile: {tp}")
    for h in horizons:
        if not isinstance(h, dict):
            continue
        name = h.get("horizon") or "?"
        lines.append(f"  [{name}]")
        for key, label in (
            ("expected",     "expected"),
            ("confirms_if",  "confirms if"),
            ("falsifies_if", "falsifies if"),
        ):
            items = h.get(key) or []
            if not items:
                continue
            lines.append(f"    {label}:")
            for it in items:
                lines.append(f"      - {it}")
    return lines


def _format_thesis_scorecard_text(sc: dict) -> list[str]:
    """Render thesis_scorecard as plain-text lines."""
    if not isinstance(sc, dict) or not sc.get("available"):
        return []
    agg = sc.get("aggregate") or {}
    lines: list[str] = ["THESIS SCORECARD"]
    status = agg.get("status") or "pending"
    resolved = agg.get("resolved_horizons", 0)
    pending = agg.get("pending_horizons", 0)
    lines.append(f"  Aggregate: {status}  ({resolved} resolved / {pending} pending)")
    if agg.get("rationale"):
        lines.append(f"  {agg['rationale']}")
    for h in sc.get("per_horizon") or []:
        if not isinstance(h, dict):
            continue
        lines.append(
            f"    {h.get('horizon', '?'):>4}: {h.get('status', '?'):<10}"
            f"  — {h.get('rationale', '')}"
        )
    return lines


def _build_event_text_memo(ev: dict) -> str:
    """Render a saved event dict as a plain-text research memo."""
    # Attach derived macro-engine blocks (thesis_scorecard etc.) so the
    # memo reflects the deeper engine output even when the caller just
    # loaded the row from the DB.  Idempotent — safe to call even on
    # already-enriched events.
    try:
        from events_export import enrich_event_with_derived
        ev = enrich_event_with_derived(ev)
    except Exception:
        pass

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
        # Pre-compute the ruler characters so the f-string below doesn't
        # inline a backslash-escape inside an expression (Python 3.11
        # PEP 701 rejects that).
        rule = "\u2500"
        r8, r14, r5 = rule * 8, rule * 14, rule * 5
        lines.append(
            f"  {'Ticker':<8} {'Role':<14} {'1d':>8}  {'5d':>8}  {'20d':>8}  {'Vol':>5}  Signal"
        )
        lines.append(
            f"  {r8} {r14} {r8}  {r8}  {r8}  {r5}  {r14}"
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

    # Horizon checkpoints — persisted directly from the LLM.  Rendered
    # before the thesis scorecard so the reader sees the EXPECTATION
    # first and the VERDICT second.
    hc_lines = _format_horizon_checkpoints_text(ev.get("horizon_checkpoints"))
    if hc_lines:
        lines.extend(hc_lines)
        lines.append("")

    # Thesis scorecard — derived from horizon_checkpoints + tickers +
    # revisit snapshots.  Caller is responsible for attaching it
    # (events_export.enrich_event_with_derived); missing block is
    # silently skipped.
    sc_lines = _format_thesis_scorecard_text(ev.get("thesis_scorecard"))
    if sc_lines:
        lines.extend(sc_lines)
        lines.append("")

    mrc_lines = _format_macro_release_block(
        ev.get("macro_release_context"), style="text",
    )
    if mrc_lines:
        lines.extend(mrc_lines)

    pt_lines = _format_policy_timing_block(
        ev.get("policy_timing_context"), style="text",
    )
    if pt_lines:
        lines.extend(pt_lines)

    cv_lines = _format_country_vulnerability_block(
        ev.get("country_vulnerability_context"), style="text",
    )
    if cv_lines:
        lines.extend(cv_lines)

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




def _format_macro_release_block(block: dict, *, style: str) -> list[str]:
    """Render the macro_release_context block for export.

    ``style`` selects the renderer: ``"markdown"`` emits a level-2
    Markdown section; ``"text"`` emits a plain-text block matching
    the SECOND ORDER memo aesthetics.  Returns an empty list when the
    block is missing or carries no ``release_key`` (the canonical
    "no mapping" signal).
    """
    if not isinstance(block, dict):
        return []
    key = block.get("release_key")
    if not key:
        return []

    def _fmt_num(value):
        if value is None:
            return "—"
        if isinstance(value, bool):
            return str(value)
        if isinstance(value, (int, float)):
            return f"{value:g}"
        return str(value)

    actual    = _fmt_num(block.get("actual"))
    consensus = _fmt_num(block.get("consensus"))
    prior     = _fmt_num(block.get("prior"))
    revised   = block.get("revised_prior")
    if revised is not None:
        prior_disp = f"{prior} → {_fmt_num(revised)}"
    else:
        prior_disp = prior
    label  = block.get("surprise_label") or "—"
    rt     = block.get("release_time") or "—"
    source = block.get("source") or "—"

    if style == "markdown":
        return [
            "## Macro Release",
            "",
            f"**Release:** `{key}` · **Time:** {rt} · **Source:** {source}",
            "",
            "| Actual | Consensus | Prior | Surprise |",
            "|---:|---:|---:|---|",
            f"| {actual} | {consensus} | {prior_disp} | `{label}` |",
            "",
        ]
    # plain text
    return [
        "MACRO RELEASE",
        f"  Release:    {key}",
        f"  Time:       {rt}",
        f"  Source:     {source}",
        f"  Actual:     {actual}    Consensus: {consensus}    Prior: {prior_disp}",
        f"  Surprise:   {label}",
        "",
    ]


def _format_country_vulnerability_block(block: dict, *, style: str) -> list[str]:
    """Render the country_vulnerability_context block for export.

    ``style`` selects the renderer: ``"markdown"`` emits a level-2
    Markdown section; ``"text"`` emits a plain-text block.  Returns
    an empty list when the block is missing or carries no ``country``
    (canonical "no match" signal).
    """
    if not isinstance(block, dict):
        return []
    country = block.get("country")
    if not country:
        return []

    ext  = block.get("external_balance_risk") or "—"
    imp  = block.get("import_shock_risk") or "—"
    cmdy = block.get("commodity_dependence") or "—"
    over = block.get("overall_vulnerability") or "—"
    rat  = block.get("rationale") or ""

    if style == "markdown":
        lines = [
            "## Country Vulnerability",
            "",
            f"**Country:** {country} · **Overall:** `{over}`",
            "",
            "| External Balance | Import Shock | Commodity Dependence |",
            "|---|---|---|",
            f"| `{ext}` | `{imp}` | `{cmdy}` |",
            "",
        ]
        if rat:
            lines.append(f"> {rat}")
            lines.append("")
        return lines
    # plain text
    lines = [
        "COUNTRY VULNERABILITY",
        f"  Country:      {country}",
        f"  Overall:      {over}",
        f"  External:     {ext}    Imports: {imp}    Commodity: {cmdy}",
    ]
    if rat:
        lines.append(f"  Rationale:    {rat}")
    lines.append("")
    return lines


def _format_policy_timing_block(block: dict, *, style: str) -> list[str]:
    """Render the policy_timing_context block for export.

    ``style`` selects the renderer: ``"markdown"`` emits a level-2
    Markdown section; ``"text"`` emits a plain-text block matching
    the SECOND ORDER memo aesthetics.  Returns an empty list when the
    block is missing or carries no ``policy_key`` (canonical "no match"
    signal).
    """
    if not isinstance(block, dict):
        return []
    key = block.get("policy_key")
    if not key:
        return []

    announced = block.get("announced_date") or "—"
    effective = block.get("effective_date") or "—"
    review    = block.get("review_date") or "—"
    status    = block.get("status") or "—"
    source    = block.get("source") or "—"

    if style == "markdown":
        return [
            "## Policy Timing",
            "",
            f"**Policy:** `{key}` · **Source:** {source}",
            "",
            "| Announced | Effective | Review | Status |",
            "|---|---|---|---|",
            f"| {announced} | {effective} | {review} | `{status}` |",
            "",
        ]
    # plain text
    return [
        "POLICY TIMING",
        f"  Policy:      {key}",
        f"  Source:      {source}",
        f"  Announced:   {announced}    Effective: {effective}    Review: {review}",
        f"  Status:      {status}",
        "",
    ]


def _format_horizon_checkpoints_markdown(hc: dict) -> list[str]:
    """Render horizon_checkpoints as markdown lines."""
    if not isinstance(hc, dict):
        return []
    horizons = hc.get("horizons") or []
    if not isinstance(horizons, list) or not horizons:
        return []
    lines: list[str] = ["## Horizon Checkpoints", ""]
    tp = hc.get("timing_profile")
    if tp and tp != "unknown":
        lines.append(f"*Timing profile: {tp}*")
        lines.append("")
    for h in horizons:
        if not isinstance(h, dict):
            continue
        name = h.get("horizon") or "?"
        lines.append(f"**{name}**")
        for key, label in (
            ("expected",     "Expected"),
            ("confirms_if",  "Confirms if"),
            ("falsifies_if", "Falsifies if"),
        ):
            items = h.get(key) or []
            if not items:
                continue
            lines.append(f"- *{label}:*")
            for it in items:
                lines.append(f"  - {it}")
        lines.append("")
    return lines


def _format_thesis_scorecard_markdown(sc: dict) -> list[str]:
    """Render thesis_scorecard as markdown lines."""
    if not isinstance(sc, dict) or not sc.get("available"):
        return []
    agg = sc.get("aggregate") or {}
    lines: list[str] = ["## Thesis Scorecard", ""]
    status = agg.get("status") or "pending"
    resolved = agg.get("resolved_horizons", 0)
    pending = agg.get("pending_horizons", 0)
    lines.append(
        f"**Aggregate:** `{status}` "
        f"— {resolved} resolved / {pending} pending"
    )
    if agg.get("rationale"):
        lines.append("")
        lines.append(f"> {agg['rationale']}")
    lines.append("")
    lines.append("| Horizon | Status | Rationale |")
    lines.append("|---|---|---|")
    for h in sc.get("per_horizon") or []:
        if not isinstance(h, dict):
            continue
        lines.append(
            f"| {h.get('horizon', '?')} "
            f"| `{h.get('status', '?')}` "
            f"| {h.get('rationale', '')} |"
        )
    lines.append("")
    return lines


def _format_actionability_markdown(block: dict) -> list[str]:
    """Render actionability_check as compact markdown."""
    if not isinstance(block, dict) or not block:
        return []
    why = (block.get("why_tradable_or_not") or "").strip()
    sizing = (block.get("sizing_caveat") or "").strip()
    invalidation = (block.get("invalidation_trigger") or "").strip()
    required = block.get("required_confirmation") or []
    risk = (block.get("risk_level") or "").strip()
    ceiling = (block.get("max_confidence_before_confirmation") or "").strip()
    if not (why or sizing or invalidation or required or risk):
        return []
    tradable = block.get("tradable")
    tradable_str = "yes" if tradable else "no" if tradable is False else "—"
    lines: list[str] = ["## Actionability", ""]
    badges: list[str] = [f"**Tradable:** {tradable_str}"]
    if risk:
        badges.append(f"**Risk:** `{risk}`")
    if ceiling:
        badges.append(f"**Confidence ceiling:** `{ceiling}`")
    lines.append(" · ".join(badges))
    lines.append("")
    if why:
        lines.append(f"> {why}")
        lines.append("")
    if required and isinstance(required, list):
        lines.append("**Required confirmation:**")
        for item in required:
            if isinstance(item, str) and item.strip():
                lines.append(f"- {item.strip()}")
        lines.append("")
    if invalidation:
        lines.append(f"**Invalidation trigger:** {invalidation}")
        lines.append("")
    if sizing:
        lines.append(f"*Sizing:* {sizing}")
        lines.append("")
    return lines


def _format_counterfactual_markdown(block: dict) -> list[str]:
    """Render counterfactual_check as compact markdown."""
    if not isinstance(block, dict) or not block:
        return []
    what = (block.get("what_should_not_happen") or "").strip()
    why = (block.get("why_it_would_break_thesis") or "").strip()
    evidence = block.get("evidence_to_watch") or []
    has_evidence = (
        isinstance(evidence, list)
        and any(isinstance(e, str) and e.strip() for e in evidence)
    )
    if not (what or why or has_evidence):
        return []
    lines: list[str] = ["## Counterfactual", ""]
    if what:
        lines.append(f"**What should not happen:** {what}")
        lines.append("")
    if why:
        lines.append(f"> {why}")
        lines.append("")
    if has_evidence:
        lines.append("**Evidence to watch:**")
        for item in evidence:
            if isinstance(item, str) and item.strip():
                lines.append(f"- {item.strip()}")
        lines.append("")
    return lines


def _format_thesis_timing_markdown(block: dict) -> list[str]:
    """Render thesis_timing as a compact one-line markdown block."""
    if not isinstance(block, dict) or not block:
        return []
    reaction = (block.get("expected_reaction_window") or "").strip()
    follow = (block.get("follow_through_window") or "").strip()
    stale = (block.get("stale_after") or "").strip()
    rationale = (block.get("timing_rationale") or "").strip()
    if not (reaction or follow or stale or rationale):
        return []
    lines: list[str] = ["## Thesis Timing", ""]
    parts: list[str] = []
    if reaction:
        parts.append(f"**Reaction:** `{reaction}`")
    if follow:
        parts.append(f"**Follow-through:** `{follow}`")
    if stale:
        parts.append(f"**Stale after:** `{stale}`")
    if parts:
        lines.append(" · ".join(parts))
        lines.append("")
    if rationale:
        lines.append(f"*{rationale}*")
        lines.append("")
    return lines


def _format_critical_breakpoints_markdown(items: list) -> list[str]:
    """Render critical_breakpoints as a compact bullet list."""
    if not isinstance(items, list) or not items:
        return []
    rendered: list[str] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        signal = (entry.get("observation") or entry.get("signal") or "").strip()
        if not signal:
            continue
        meta_bits: list[str] = []
        for k in ("channel", "timing", "threshold"):
            v = entry.get(k)
            if isinstance(v, str) and v.strip():
                meta_bits.append(f"{k}: `{v.strip()}`")
        condition = (entry.get("condition") or "").strip()
        why = (entry.get("why_it_changes_thesis") or "").strip()
        line = f"- **{signal}**"
        if meta_bits:
            line += " — " + " · ".join(meta_bits)
        rendered.append(line)
        if condition:
            rendered.append(f"  - *If:* {condition}")
        if why:
            rendered.append(f"  - *Why:* {why}")
    if not rendered:
        return []
    return ["## Critical Breakpoints", "", *rendered, ""]


def _format_evidence_sources_markdown(items: list) -> list[str]:
    """Render evidence_sources as a compact bullet list."""
    if not isinstance(items, list) or not items:
        return []
    rendered: list[str] = []
    for src in items:
        if not isinstance(src, dict):
            continue
        field = (src.get("field_used") or src.get("source_type") or "").strip()
        if not field:
            continue
        direction = (src.get("supports_or_contradicts") or "").strip()
        limitation = (src.get("limitation") or "").strip()
        line = f"- `{field}`"
        if direction:
            line += f" — {direction}"
        if limitation:
            line += f" *({limitation})*"
        rendered.append(line)
    if not rendered:
        return []
    return ["## Evidence Sources", "", *rendered, ""]


def _build_event_markdown_memo(ev: dict) -> str:
    """Render a saved event dict as a compact Markdown research memo.

    Section order is fixed so downstream consumers (tests, tooling)
    can rely on heading positions.
    """
    try:
        from events_export import enrich_event_with_derived
        ev = enrich_event_with_derived(ev)
    except Exception:
        pass
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

    # --- Macro Release ---
    mrc_lines = _format_macro_release_block(
        ev.get("macro_release_context"), style="markdown",
    )
    if mrc_lines:
        lines.extend(mrc_lines)

    # --- Policy Timing ---
    pt_lines = _format_policy_timing_block(
        ev.get("policy_timing_context"), style="markdown",
    )
    if pt_lines:
        lines.extend(pt_lines)

    # --- Country Vulnerability ---
    cv_lines = _format_country_vulnerability_block(
        ev.get("country_vulnerability_context"), style="markdown",
    )
    if cv_lines:
        lines.extend(cv_lines)

    # --- Horizon Checkpoints ---
    hc_lines = _format_horizon_checkpoints_markdown(ev.get("horizon_checkpoints"))
    if hc_lines:
        lines.extend(hc_lines)

    # --- Thesis Scorecard ---
    sc_lines = _format_thesis_scorecard_markdown(ev.get("thesis_scorecard"))
    if sc_lines:
        lines.extend(sc_lines)

    # --- Engine-phase sections (skip empties cleanly) ---
    timing_block = ev.get("thesis_timing")
    if not isinstance(timing_block, dict) or not timing_block:
        ct = ev.get("competing_thesis")
        if isinstance(ct, dict):
            timing_block = ct.get("thesis_timing") or {}
        else:
            timing_block = {}
    tt_lines = _format_thesis_timing_markdown(timing_block)
    if tt_lines:
        lines.extend(tt_lines)

    breakpoints = ev.get("critical_breakpoints")
    if not isinstance(breakpoints, list) or not breakpoints:
        hm = ev.get("hidden_mechanism")
        if isinstance(hm, dict):
            breakpoints = hm.get("critical_breakpoints") or []
        else:
            breakpoints = []
    cb_lines = _format_critical_breakpoints_markdown(breakpoints)
    if cb_lines:
        lines.extend(cb_lines)

    ac_lines = _format_actionability_markdown(ev.get("actionability_check") or {})
    if ac_lines:
        lines.extend(ac_lines)

    cf_lines = _format_counterfactual_markdown(ev.get("counterfactual_check") or {})
    if cf_lines:
        lines.extend(cf_lines)

    es = ev.get("evidence_sources")
    if not isinstance(es, list) or not es:
        ct = ev.get("competing_thesis")
        if isinstance(ct, dict):
            es = ct.get("evidence_sources") or []
        else:
            es = []
    es_lines = _format_evidence_sources_markdown(es)
    if es_lines:
        lines.extend(es_lines)

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
              Market reaction (raw), Key Context.
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

    # --- Market reaction (raw) ---
    tickers = ev.get("market_tickers") or []
    if tickers:
        def _pct(v):
            if v is None:
                return "—"
            return f"{'+' if v >= 0 else ''}{v:.2f}%"

        lines.append("## Market reaction (raw)")
        lines.append("")
        lines.append("_Raw event-window returns (1d/5d/20d) — not benchmark-adjusted._")
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

    # --- Macro Release ---
    mrc_lines = _format_macro_release_block(
        ev.get("macro_release_context"), style="markdown",
    )
    if mrc_lines:
        lines.extend(mrc_lines)

    # --- Policy Timing ---
    pt_lines = _format_policy_timing_block(
        ev.get("policy_timing_context"), style="markdown",
    )
    if pt_lines:
        lines.extend(pt_lines)

    # --- Country Vulnerability ---
    cv_lines = _format_country_vulnerability_block(
        ev.get("country_vulnerability_context"), style="markdown",
    )
    if cv_lines:
        lines.extend(cv_lines)

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






# Base (non-overlay) keys emitted by the single-event JSON export.  The
# overlay key set is imported from events_export.EXPORT_OVERLAY_FIELDS so
# there is exactly one registry governing which persisted overlays flow
# into any export format.  New persisted overlays added to
# analyze_event.PERSISTED_OVERLAY_FIELDS appear in every export path
# without further edits.
from events_export import EXPORT_OVERLAY_FIELDS as _EXPORT_OVERLAY_FIELDS

_JSON_EXPORT_BASE_KEYS: tuple[str, ...] = (
    "id", "timestamp", "headline", "event_date",
    "stage", "persistence", "confidence",
    "what_changed", "mechanism_summary",
    "beneficiaries", "losers", "assets_to_watch",
    "market_note", "market_tickers",
    "transmission_chain", "if_persists", "currency_channel",
    # Horizon-aware thesis structure (persisted).
    "horizon_checkpoints",
    # Derived macro-engine blocks — attached by
    # events_export.enrich_event_with_derived during the JSON build.
    # ``thesis_scorecard`` is computed from persisted inputs; the
    # ``finance_playbook`` block degrades gracefully when live-macro
    # composers (sector_rotation, funding_stress_mode) are unavailable.
    "thesis_scorecard",
    "finance_playbook",
    # Engine-phase blocks — pure-read composers over already-persisted
    # fields.  All nine carry a stable empty shape on absent data so the
    # JSON envelope is byte-stable across actionable / watch_only /
    # low_information rows.  ``thesis_timing`` /
    # ``critical_breakpoints`` / ``evidence_sources`` are lifted out of
    # ``competing_thesis`` / ``hidden_mechanism`` for top-level access;
    # the nested copies stay in place inside those blocks.
    "quality_tier",
    "quality_warnings",
    "actionability_check",
    "counterfactual_check",
    "thesis_timing",
    "critical_breakpoints",
    "evidence_sources",
    "confidence_rationale",
    "validation_rationale",
    # Per-event macro release context — populated for events that map
    # to a CPI / PPI / NFP / Unemployment / PCE release; stable empty
    # shape otherwise.  See macro_surprise.coerce_macro_release_context.
    "macro_release_context",
    # Per-event policy timing context — populated for events that
    # match a tracked regulatory / trade / rate policy; stable empty
    # shape otherwise.  See policy_timing.coerce_policy_timing_context.
    "policy_timing_context",
    # Per-event country vulnerability context — populated when the
    # event mentions a country profiled in country_backdrop; stable
    # empty shape otherwise.
    "country_vulnerability_context",
    "rating", "notes",
)

# Stable key list for the JSON event export.  Order matters — it defines
# the key order in the response so downstream consumers can rely on it.
# Overlay keys land at the tail of the tuple so base-key order stays
# identical to the pre-registry contract.
_JSON_EXPORT_KEYS: tuple[str, ...] = _JSON_EXPORT_BASE_KEYS + _EXPORT_OVERLAY_FIELDS


def _build_event_json_export(ev: dict) -> dict:
    """Project a saved event dict to the stable JSON export shape.

    Only keys listed in ``_JSON_EXPORT_KEYS`` are emitted, in that
    fixed order.  Internal-only fields (``low_signal``, ``model``,
    ``regime_snapshot``, ``last_market_check_at``) are excluded.

    Persisted overlays are passed through ``sanitize_overlay_block`` so a
    missing / empty overlay carries the explicit degraded contract instead
    of silently being emitted as ``{}`` — frozen archive rebuilds and
    exports see the same availability signal as the live analysis path.

    ``thesis_scorecard`` and ``finance_playbook`` are derived — attached
    via ``events_export.enrich_event_with_derived`` so the export always
    reflects the deeper macro engine, not only the raw persisted fields.
    """
    from events_export import enrich_event_with_derived
    enriched = enrich_event_with_derived(ev)

    overlay_set = frozenset(_EXPORT_OVERLAY_FIELDS)
    out: dict = {}
    for k in _JSON_EXPORT_KEYS:
        if k in overlay_set:
            out[k] = sanitize_overlay_block(enriched.get(k), name=k)
        elif k == "macro_release_context":
            from macro_surprise import coerce_macro_release_context
            out[k] = coerce_macro_release_context(enriched.get(k))
        elif k == "policy_timing_context":
            from policy_timing import coerce_policy_timing_context
            out[k] = coerce_policy_timing_context(enriched.get(k))
        elif k == "country_vulnerability_context":
            from country_backdrop import coerce_country_vulnerability_context
            out[k] = coerce_country_vulnerability_context(enriched.get(k))
        else:
            out[k] = enriched.get(k)
    return out



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


@app.get("/stats/coverage")
def stats_coverage():
    """Event-study readiness coverage — COUNTS only, a separate gate.

    Reports how many archived analysis-stage events are event-study-ready
    (per-event abnormal-return / SAR / CAR computable through the gated
    single-event validator) versus not, plus the blocking-reason buckets
    the gate already aggregates.

    This is ONE eligibility gate, computed independently.  It is NOT a
    stage in a single linear funnel, is NOT combined with track-record
    coverage, and NEVER reads or merges the closed Phase 1 / Phase 2 FDR
    pools (which keep their own separate denominators).

    Read-only: delegates to the read-only coverage summarizer, which loops
    ``event_study_validation.build_event_study_validation`` (plain
    ``price_cache`` SELECTs, the same gate the single-event
    ``/events/{id}/event-study`` route uses) over the analysis-stage
    archive.  No provider / network / yfinance / LLM call and no DB
    mutation.  ``limit=0`` keeps the payload counts-only — the per-event
    lists the CLI report carries are dropped.
    """
    from scripts.event_study_coverage_report import (
        summarize_event_study_coverage,
    )
    report = summarize_event_study_coverage(limit=0)
    return _sanitize_floats({
        "ok":                            True,
        "section":                       "event_study_coverage",
        "schema_version":                "v1",
        "total_events":                  report["total_events"],
        "event_study_ready_count":       report["event_study_available_count"],
        "unavailable_count":             report["insufficient_data_count"],
        "curated_intake_excluded_count": report["curated_intake_excluded_count"],
        "blocking_reasons":              report["blocking_reasons"],
        "not_a_funnel_note": (
            "Event-study readiness is one eligibility gate, computed "
            "independently. It is not a stage in a single linear funnel, is "
            "not combined with track-record coverage, and never reads or "
            "merges the closed Phase 1 / Phase 2 FDR pools."
        ),
        "non_claims":                    report["non_claims"],
    })


@app.get("/stats/confidence-calibration")
def confidence_calibration():
    """Historical any-supporting rate per confidence bucket (low/medium/high).

    Returns per-bucket hit_rate — the OR-rule fraction of events with ≥1
    supporting ticker (descriptive context, not a confirmed validation rate) —
    and sample size n.  Buckets with fewer than 3 usable events are omitted.
    """
    return _sanitize_floats(get_confidence_calibration_stats())


@app.get("/stats/track-record/breakdown")
def track_record_breakdown():
    """Mechanism-family + regime + compound-regime performance summaries.

    Slices the same outcome counts as /stats/track-record three ways so a
    portfolio or research surface can render "which mechanism families
    have actually worked" without rescanning the event table.  Pure
    composer on top of the recent events — no new provider calls.
    """
    from track_record_breakdown import compute_track_record_breakdown
    # Load the most recent 500 events so the breakdown covers the same
    # horizon as compute_track_record / find_historical_analogs.
    events = load_recent_events(limit=500)
    return _sanitize_floats(compute_track_record_breakdown(events))


@app.get("/stats/track-record/breakdown/export")
def track_record_breakdown_export(format: str = "json"):
    """Export the mechanism-family + regime breakdown for memo / report flows.

    ``format`` picks the serializer:
      * ``json``     — research-friendly envelope (default).  Same payload
                       as /stats/track-record/breakdown wrapped with a
                       schema tag and summary block.
      * ``csv``      — multi-section CSV: summary, by_mechanism_family,
                       by_regime, by_compound_regime.
      * ``markdown`` — desk-note style memo with GitHub-flavor tables per
                       dimension.
    """
    from fastapi import HTTPException
    from fastapi.responses import Response
    from track_record_breakdown import compute_track_record_breakdown
    from track_record_export import (
        build_breakdown_json,
        build_breakdown_csv,
        build_breakdown_markdown,
    )

    fmt = (format or "json").strip().lower()
    if fmt not in ("json", "csv", "markdown"):
        raise HTTPException(422, "format must be json, csv, or markdown")

    events = load_recent_events(limit=500)
    breakdown = compute_track_record_breakdown(events)

    if fmt == "json":
        return _sanitize_floats(build_breakdown_json(breakdown))
    if fmt == "csv":
        body = build_breakdown_csv(breakdown)
        return Response(
            content=body, media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition":
                     'attachment; filename="track_record_breakdown.csv"'},
        )
    # markdown
    body = build_breakdown_markdown(breakdown)
    return Response(
        content=body, media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition":
                 'attachment; filename="track_record_breakdown.md"'},
    )




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


class SavedStudyCreate(BaseModel):
    study_type: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field("", max_length=500)
    config: dict = Field(default_factory=dict)
    overwrite: bool = Field(False)


class SavedStudyUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    config: dict | None = Field(None)


class ResearchExportStudyInline(BaseModel):
    study_type: str = Field(..., min_length=1, max_length=64)
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    config: dict = Field(default_factory=dict)


class ResearchExportRequest(BaseModel):
    # Either or both populated; route unions them into one study list.
    saved_study_ids: list[int] = Field(default_factory=list, max_length=32)
    studies:         list[ResearchExportStudyInline] = Field(
        default_factory=list, max_length=32,
    )
    format:          str = Field("json", pattern=r"^(json|markdown)$")
    limit:           int = Field(500, ge=50, le=1000)
















_MOVER_THRESHOLD = 1.5  # abs(return_5d) minimum for Market Movers qualification

# Maximum number of preview ticker chips a mover card emits.  Bumped
# from 3 → 4 so the persistent / weekly cards can carry richer
# evidence (one classic 2x2 grid of winner/loser/winner/loser shapes
# without dropping the second-best loser).
_MOVER_PREVIEW_LIMIT = 4


def _compute_support_ratio(
    tickers: list[dict], *, mechanism_family: str | None = None,
) -> float:
    """Agreement-percent computation — delegated to the upgraded engine.

    Canonical outputs (all tickers support → 1.0; all contradict →
    0.0; evenly split → 0.5) are preserved, so existing pill displays
    and unit-test expectations continue to hold.  The weighted,
    mechanism-aware engine additionally rescues the "partially right"
    mid-band that the naive count used to collapse to 0% / 100%.

    Callers that want the richer verdict (direct vs second-order
    counts, confirmed / partial / mixed / weak / contradicted, and a
    human-readable reason) should call
    ``agreement_engine.compute_agreement_verdict`` directly.
    """
    from agreement_engine import compute_support_ratio as _impl
    return _impl(tickers, mechanism_family=mechanism_family)


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

    # Agreement verdict — the richer, mechanism-family-aware read that
    # distinguishes direct from second-order confirmation and attaches
    # a human-readable reason.  The raw ``support_ratio`` float above
    # stays as the legacy pill input; the ``agreement`` block is the
    # new finance-real surface consumers should prefer.
    from agreement_engine import compute_agreement_verdict
    agreement = compute_agreement_verdict(
        big_moves,
        mechanism_family=ev.get("mechanism_family") or None,
        # Mechanism structure — lets the engine identify bottleneck
        # proxies (tickers named in the transmission path, substitution
        # barriers, or beneficiaries/losers text) and weight them above
        # generic sector proxies.
        transmission_path=ev.get("transmission_path") or None,
        substitution_barriers=ev.get("substitution_barriers") or None,
        beneficiaries_text=ev.get("beneficiaries") or None,
        losers_text=ev.get("losers") or None,
        # Hedge / signal exposures — UUP, VIX, TLT, inverse ETFs.  The
        # engine demotes their per-ticker weight so a contradicting
        # hedge ETF weighs less than a contradicting primary.
        hedge_or_signal_assets=ev.get("hedge_or_signal_assets") or None,
    )

    # Tier-aware ranking — replaces the naive ``max_move * (1 +
    # support_ratio)`` formula so a 3% move with contradicting direct
    # proxies doesn't rank ahead of a 2% move with a clean alpha hit.
    # persistence_signal is already decoded on the event row by
    # db.load_recent_events (key ``persistence_signal``).
    from movers_ranking import build_why_still_moving, compute_rank_score
    persistence_sig = ev.get("persistence_signal") or None
    rank = compute_rank_score(
        agreement, max_move, persistence_signal=persistence_sig,
    )
    why = build_why_still_moving(
        ev, agreement, big_moves,
        persistence_signal=persistence_sig,
        decay_info=(ticker_summaries[0] if ticker_summaries else None),
    )

    # Evidence-ladder read — compact 5-rung tier + reason_code +
    # narrative.  Rides alongside the 7-tier movers_ranking.tier so
    # downstream consumers can choose the grain they want: the
    # richer movers_ranking tiers for ordering, the tighter evidence
    # ladder for telemetry / share text.
    from evidence_ladder import classify_evidence
    evidence = classify_evidence(
        agreement, persistence_signal=persistence_sig,
    )

    # Conviction ranking — combined evidence-quality × persistence-
    # quality score.  This is what Still Moving Markets now sorts on:
    # primary + durable follow-through dominates, noisy mixed cases
    # get docked.  The ``impact`` field the movers-cache sort reads is
    # set to ``conviction_score`` so the surface ordering changes
    # without any callsite edits.
    #
    # weighted_evidence / proof_status / thesis_state are threaded
    # through so the impact_level categorical gate can enforce
    # must-not-promote rules (low_info / contradictory / mixed cannot
    # claim "high" from move size alone), and the thesis_state
    # multiplier dampens the numeric score on falsified / stale /
    # weakening / low_information rows.
    from movers_ranking import compute_conviction_rank
    _weighted_for_rank = _derive_mover_weighted_evidence(
        tickers=big_moves, ev=ev,
    )
    _thesis_for_rank = _derive_mover_thesis_state(ev)
    conviction = compute_conviction_rank(
        evidence, max_move,
        persistence_signal=persistence_sig,
        weighted_evidence=_weighted_for_rank,
        proof_status=ev.get("proof_status") or None,
        thesis_state=_thesis_for_rank,
    )

    # Evidence-attribution layer — dominant confirming / contradiction /
    # missing proof / channel contribution breakdown.  Turns the
    # aggregate agreement score into a readable "evidence memo" with
    # a confirmation_shape that names HOW the thesis is earning (or
    # losing) its score: single_decisive_channel vs broad_confirmation
    # vs scattered_weak vs mixed_offset vs unilateral_contradiction.
    try:
        from evidence_attribution import compute_evidence_attribution
        attribution = compute_evidence_attribution(
            big_moves, mechanism_family=ev.get("mechanism_family") or None,
        )
    except Exception:
        _log.warning("evidence_attribution failed", exc_info=True)
        attribution = {}

    # Evidence-quality layer — tiers each ticker into
    # high-quality / provisional / low-quality based on alpha vs beta,
    # magnitude vs noise floor, and volume liquidity.  Emits a
    # confidence_basis ("strong_evidence" / "mixed_quality" /
    # "fragile_basket" / "thin") so the UI can render whether the
    # read rests on clean evidence or fragile noise.
    try:
        from evidence_quality import classify_evidence_quality
        quality = classify_evidence_quality(big_moves)
    except Exception:
        _log.warning("evidence_quality failed", exc_info=True)
        quality = {}

    # Historical-calibration layer — anchors the raw agreement score
    # to saved outcomes for the same (family, compound_regime,
    # confidence) cohort.  Distinguishes "weak thesis" (score lagging
    # a strong cohort) from "noisy pattern" (coin-flip cohort).
    try:
        from agreement_calibration import (
            build_historical_tree, calibrate_agreement,
        )
        from db import collect_calibration_samples
        _tree = build_historical_tree(collect_calibration_samples())
        _regime_snap = ev.get("regime_snapshot") or {}
        _compound = (_regime_snap.get("compound") or {}) if isinstance(_regime_snap, dict) else {}
        _compound_label = _compound.get("label") if isinstance(_compound, dict) else None
        calibration = calibrate_agreement(
            agreement,
            mechanism_family=ev.get("mechanism_family"),
            compound_regime=_compound_label,
            confidence=ev.get("confidence"),
            calibration_tree=_tree,
        )
    except Exception:
        _log.warning("agreement calibration failed", exc_info=True)
        calibration = {}

    # Channel-timing layer — respect that rates/vol confirm at 1-3d,
    # commodities/fx at 3-10d, credit at 5-12d, and downstream equities
    # at 7-20d.  The aggregate status distinguishes early_confirming /
    # in_window_confirming / delayed_on_track / late_and_failing so a
    # thesis is not mis-flagged as broken merely because a slow channel
    # hasn't cascaded yet.
    try:
        from channel_timing import classify_thesis_timing, score_channel_observation
        from agreement_engine import _channel_for_sector
        # Event age (calendar days) — prefer persistence_signal's
        # ``days_elapsed`` when present; fall back to event_age_policy.
        _age = None
        if isinstance(persistence_sig, dict):
            _age = persistence_sig.get("days_elapsed")
        if _age is None:
            try:
                import event_age_policy
                from datetime import datetime
                _age = event_age_policy.event_age_days(ev, datetime.now())
            except Exception:
                _age = 0
        fam = ev.get("mechanism_family") or None
        _observations = []
        for _t in big_moves:
            _ch = _channel_for_sector(_t.get("benchmark_sector"))
            if _ch is None:
                continue
            _dir = 0.0
            _vq = (_t.get("validation_quality") or "").lower()
            if _vq in ("alpha_support", "beta_aligned"):
                _dir = +1.0
            elif _vq in ("alpha_contradicts", "beta_contradicts"):
                _dir = -1.0
            else:
                _dt = (_t.get("direction_tag") or "").lower()
                if _dt.startswith("supports"):
                    _dir = +1.0
                elif _dt.startswith("contradicts"):
                    _dir = -1.0
            _observations.append(score_channel_observation(
                channel=_ch, days_elapsed=_age,
                direction_sign=_dir, mechanism_family=fam,
            ))
        channel_timing = classify_thesis_timing(_age, _observations)
    except Exception:
        _log.warning("channel_timing classification failed", exc_info=True)
        channel_timing = {}

    return {
        "event_id": ev["id"],
        "headline": ev["headline"],
        "mechanism_summary": ev.get("mechanism_summary", ""),
        "event_date": ev.get("event_date", ""),
        "stage": ev.get("stage", ""),
        "persistence": ev.get("persistence", ""),
        # Ranking: the surface sorts on ``impact``.  Conviction score
        # combines evidence-quality (from the 5-rung evidence ladder)
        # with persistence-quality (from the repricing-state block in
        # persistence_signal) so primary + durable-follow-through
        # dominates noisy-mixed + flat-follow-through.
        "impact": conviction["conviction_score"],
        "support_ratio": round(support_ratio, 2),
        "agreement": agreement,
        "agreement_tier":       rank["tier"],
        "agreement_tier_label": rank["tier_label"],
        "rank_score":           rank["rank_score"],
        "rank_rationale":       rank["rationale"],
        "why_still_moving":     why,
        # Evidence-ladder read — the finance-desk-quotable tier + reason
        # code + one-line narrative.  Summary consumers should prefer
        # ``evidence.narrative`` over the legacy support_ratio for the
        # card's headline explanation.
        "evidence":             evidence,
        # Conviction ranking — evidence × persistence.  The surface
        # orders cards by conviction_score (the ``impact`` field
        # above); ``why_ranks_here`` explains to the reader WHY a
        # given card sits where it does.
        "conviction":           conviction,
        # Channel-timing — the time-aware status respecting that rates /
        # FX / commodities / credit / equities / downstream-equities
        # confirm on different timelines.  The status band is the
        # surface-level read; ``observations`` carries the per-channel
        # phases for drill-down.
        "channel_timing":       channel_timing,
        # Historical calibration — anchors the agreement score to
        # saved outcomes; carries ``cohort_reliability`` +
        # ``thesis_vs_cohort`` so consumers can distinguish a weak
        # thesis from a noisy pattern.
        "calibration":          calibration,
        # Evidence-attribution — "evidence memo" surface: dominant
        # confirming / contradiction / missing proof / per-channel
        # contribution breakdown + a confirmation_shape that names
        # HOW the thesis earns its score (single decisive channel vs
        # broad confirmation vs scattered weak evidence).
        "attribution":          attribution,
        # Evidence-quality tiers — per-ticker high / provisional /
        # low classification + confidence_basis.  Separates evidence
        # STRENGTH from directional coincidence.
        "quality":              quality,
        "tickers": ticker_summaries,
        "transmission_chain": ev.get("transmission_chain", []),
        "if_persists": ev.get("if_persists", {}),
        # Per-card freshness header — surfaced to the frontend so
        # cards display "as of HH:MM" / staleness state.  These
        # come straight from the persisted event row; on legacy rows
        # they default to None and the frontend hides the indicator.
        "last_market_check_at": ev.get("last_market_check_at"),
        # --- UI-ready normaliser inputs ---
        # Additive fields consumed by ``mover_card_normalizer.to_ui_card``
        # so every mover surface projects onto one canonical card
        # shape.  Nothing here changes ranking; these are passthrough
        # reads from the event row (or a deterministic derivation)
        # packaged so the normaliser doesn't need to re-fetch the
        # event at route time.
        "mechanism_family":   ev.get("mechanism_family") or "none",
        "thesis_state":          _derive_mover_thesis_state(ev),
        "thesis_state_reason":   _derive_mover_thesis_state_reason(ev),
        "validation_rationale":  _derive_mover_validation_rationale(ev),
        "weighted_evidence":  _derive_mover_weighted_evidence(tickers=big_moves, ev=ev),
        "proof_status":       ev.get("proof_status") or {},
        "stale_signal":       ev.get("stale_signal"),
    }


def _derive_mover_thesis_state(ev: dict) -> str:
    """Late-import wrapper for ``thesis_state.derive_thesis_state``.

    Kept local so ``api`` doesn't grow a new top-level import for a
    helper that's only needed by one card-building path.
    """
    try:
        from thesis_state import derive_thesis_state
        return derive_thesis_state(ev)
    except Exception:
        return "unknown"


def _derive_mover_thesis_state_reason(ev: dict) -> str:
    """Mirror of ``_derive_mover_thesis_state`` for the additive
    ``thesis_state_reason`` field.  Returns an empty string on
    failure so the response shape stays stable (no missing key)."""
    try:
        from thesis_state import derive_thesis_state_reason
        return derive_thesis_state_reason(ev)
    except Exception:
        return ""


def _derive_mover_weighted_evidence(tickers: list, ev: dict | None = None) -> dict:
    """Late-import wrapper for ``validation_outcome.score_weighted_evidence``.

    ``ev`` (when supplied) provides the event context used to extract the
    explicit primary-asset set so weighted scoring respects the
    analyst's committed direct picks instead of defaulting unmapped
    tickers to primary weight.
    """
    try:
        from validation_outcome import _extract_primary_set, score_weighted_evidence
        return score_weighted_evidence(
            tickers or [],
            explicit_primary=_extract_primary_set(ev) if ev else None,
        )
    except Exception:
        return {}


def _derive_mover_validation_rationale(ev: dict) -> str:
    """Mirror of ``_derive_mover_thesis_state_reason`` for the additive
    ``validation_rationale`` field.  Returns an empty string on failure
    so the response shape stays stable (no missing key)."""
    try:
        from thesis_state import derive_validation_rationale
        return derive_validation_rationale(ev)
    except Exception:
        return ""


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

_TODAYS_MOVERS_CACHE: dict = {"data": None, "ts": 0.0, "window_hours": 24}
_TODAYS_MOVERS_TTL = 300  # 5 minutes


def _today_mover_candidate_events(cutoff_iso: str) -> list[dict]:
    """Return in-window today candidates from both eligibility anchors.

    Three sources are merged and deduped by (id, headline):

      1. ``load_events_since`` — rows whose ``timestamp`` is fresh
         (covers freshly persisted events).
      2. ``load_events_market_checked_since`` — rows whose
         ``last_market_check_at`` is fresh (covers backfill / freshness
         refresh paths that update an older event's market data without
         changing its original ``timestamp``).
      3. The most recent 500 rows filtered by
         ``event_matches_mover_window`` — preserves the
         ``active_mover_windows`` hint admitted by tests / replay paths.
    """
    events = load_events_since(cutoff_iso)
    seen: set[tuple[Any, str]] = {
        (ev.get("id"), ev.get("headline", "") or "")
        for ev in events if isinstance(ev, dict)
    }
    try:
        market_checked = load_events_market_checked_since(cutoff_iso)
    except Exception:
        market_checked = []
    for ev in market_checked:
        if not isinstance(ev, dict):
            continue
        key = (ev.get("id"), ev.get("headline", "") or "")
        if key in seen:
            continue
        seen.add(key)
        events.append(ev)
    try:
        recent = load_recent_events(500)
    except Exception:
        recent = []
    for ev in recent:
        if not isinstance(ev, dict):
            continue
        if not movers_cache.event_matches_mover_window(ev, "today", cutoff_iso):
            continue
        key = (ev.get("id"), ev.get("headline", "") or "")
        if key in seen:
            continue
        seen.add(key)
        events.append(ev)
    return events


def _today_window_qualify(tickers: list[dict]) -> list[dict]:
    """Project tickers for the /movers/today surface.

    The 24h window is younger than the 5-day return window by definition,
    so ``return_5d`` is rarely populated for events that are genuinely
    "today".  Fall back to ``return_1d`` when ``return_5d`` is None so a
    fresh event is still scoreable on its 1-day reaction.

    Returns fresh dicts (no shared references with the input) where
    ``return_5d`` carries the best-available return for ranking, and
    ``return_window`` ("5d" or "1d") records which window the value
    actually represents so downstream consumers don't conflate them.
    """
    out: list[dict] = []
    for t in tickers or []:
        if not isinstance(t, dict):
            continue
        r5 = t.get("return_5d")
        r1 = t.get("return_1d")
        if r5 is None and r1 is None:
            continue
        projected = dict(t)
        if r5 is None:
            projected["return_5d"] = r1
            projected["return_window"] = "1d"
        else:
            projected.setdefault("return_window", "5d")
        out.append(projected)
    return out


# Today-window cadence fallback ---------------------------------------------
# The strict 24h window is the right "today" semantics on a healthy ingestion
# cadence: fresh events analyzed and market-checked in the last day populate
# the surface naturally.  When analysis arrives in bursts (the LLM-batched
# operating mode) the most recent saves often carry empty ``market_tickers``
# (no market_check yet) while the prior batch with real returns sits at
# ~25–48h — just past the strict cutoff.  In that mode the strict 24h
# returns [] even though there ARE real, recently-checked event-linked moves
# the operator should see.  The fallback below extends the cutoff to 48h
# only when strict-24h yields zero qualified movers; if 48h is also empty,
# the response stays truthfully empty.  No filler is invented either way.
_TODAY_WINDOW_HOURS:   int = 24
_TODAY_FALLBACK_HOURS: int = 48


def _movers_today_compute(cutoff_hours: int) -> list[dict]:
    """Score today-eligible movers against a single cutoff window.

    Pure function: no caching, no fetches.  Re-used by ``movers_today``
    on its strict-24h pass and again on the 48h fallback.
    """
    cutoff = (
        datetime.now() - timedelta(hours=cutoff_hours)
    ).isoformat(timespec="seconds")
    events = _today_mover_candidate_events(cutoff)
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
        # Scrub absurd return values, then suppress cross-contaminated
        # rows.  Order matters: scrubbing first nukes garbage values to
        # None so the dedup signature isn't polluted by 1348%-outliers.
        tickers = _scrub_implausible_ticker_returns(ev.get("market_tickers", []))
        tickers = _suppress_duplicate_tickers(tickers)
        if not tickers:
            continue
        with_return = _today_window_qualify(tickers)
        if not with_return:
            continue
        # Unified deterministic helper so today / market-movers / persistent
        # report the same agreement % for the same event.
        support_ratio = _compute_support_ratio(tickers)
        scored.append(_build_mover_summary(ev, with_return, support_ratio))
    scored.sort(key=lambda x: x["impact"], reverse=True)
    return scored


def movers_today(limit: int = 10):
    """Return analyzed events with any confirmed ticker move.

    Strict-24h preferred, with a 48h fallback when 24h is empty so a
    bursty analysis cadence (yesterday's session market-checked, today's
    saves not yet market-checked) doesn't leave the surface empty when
    there are real recent moves to show.  ``return_1d`` is accepted as
    a fallback to ``return_5d`` so events younger than the 5-day window
    still score; ``return_window`` on each ticker records which window
    the displayed value came from.

    Candidate selection uses a time-window via ``load_events_since``
    (not a row-count limit) so a burst of low-value rows never pushes
    relevant events out of the candidate set.  Cached for 5 minutes.
    """
    now = time.monotonic()
    if _TODAYS_MOVERS_CACHE["data"] is not None and (now - _TODAYS_MOVERS_CACHE["ts"]) < _TODAYS_MOVERS_TTL:
        return _TODAYS_MOVERS_CACHE["data"][:limit]

    scored = _movers_today_compute(_TODAY_WINDOW_HOURS)
    window_used = _TODAY_WINDOW_HOURS
    if not scored and _TODAY_FALLBACK_HOURS > _TODAY_WINDOW_HOURS:
        # ``window_used`` reflects the widest cutoff actually attempted,
        # not the one that produced rows.  When 24h is empty the system
        # has consulted 48h regardless of outcome, and the operator
        # diagnostic should report that fact so a doubly-empty surface
        # reads as "no rows in 48h" rather than "narrow 24h gap".
        window_used = _TODAY_FALLBACK_HOURS
        fallback = _movers_today_compute(_TODAY_FALLBACK_HOURS)
        if fallback:
            scored = fallback

    _TODAYS_MOVERS_CACHE["data"] = scored
    _TODAYS_MOVERS_CACHE["ts"] = now
    _TODAYS_MOVERS_CACHE["window_hours"] = window_used
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
_MARKET_MOVERS_TTL = 300    #  5 min — short window (48h data), high UI-refresh visibility
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
    """Thin proxy so ``api.market_movers()`` keeps working in tests.

    The HTTP route also defaults to the historic bare-list shape.  Its
    diagnostics envelope is opt-in, so in-process callers and HTTP
    consumers share the same default contract.
    """
    from routes.movers import market_movers as _impl
    resp = _impl(limit=limit)
    if isinstance(resp, dict) and "items" in resp:
        return resp["items"]
    return resp


def news(limit: int = 0, cursor: str | None = None):
    """Thin proxy so ``api.news()`` keeps working in tests."""
    from routes.news import news as _impl
    return _impl(limit=limit, cursor=cursor)


# ---------------------------------------------------------------------------
# Route modules — each file registers its own APIRouter; included here
# so api.app carries the full endpoint set.
# ---------------------------------------------------------------------------

from routes.analyze import router as _analyze_router
from routes.archive_diagnostics import router as _archive_diagnostics_router
from routes.candidates import router as _candidates_router
from routes.curated import router as _curated_router
from routes.diagnostics import router as _diagnostics_router
from routes.events import router as _events_router
from routes.market import router as _market_router
from routes.movers import router as _movers_router
from routes.news import router as _news_router
from routes.portfolio import router as _portfolio_router
from routes.playbook import router as _playbook_router

app.include_router(_analyze_router)
app.include_router(_archive_diagnostics_router)
app.include_router(_candidates_router)
app.include_router(_curated_router)
app.include_router(_diagnostics_router)
app.include_router(_events_router)
app.include_router(_market_router)
app.include_router(_movers_router)
app.include_router(_news_router)
app.include_router(_portfolio_router)
app.include_router(_playbook_router)


# ---------------------------------------------------------------------------
# Demo Section C endpoints — read-only surfaces that wire the four
# ``routes/demo_*`` source modules under ``/demo/*``.  No DB writes,
# no provider / yfinance / LLM call, no artifact mutation.  Production
# ``/movers/*`` and ``/health`` endpoints are untouched.
#
# The demo Daily and Evidence Summary endpoints load from a stable
# on-disk demo artifact bundle.  By default the bundle is
# ``evidence_artifacts/section_c_v1/`` — a tracked input the operator can
# rely on even when the local ``artifacts/`` directory is empty.  An
# operator can point the demo backend at a different bundle (e.g. a
# local experiment) by exporting the ``SECOND_ORDER_DEMO_ARTIFACT_DIR``
# environment variable; the resolver reads the env var per request so
# a fresh export takes effect on the next call without a server
# restart.  Weekly and Still Moving do not consult this bundle — they
# read the production mover cache through their own source modules.
# ---------------------------------------------------------------------------

import os as _os
from pathlib import Path as _Path

from routes import (
    demo_daily as _demo_daily_mod,
    demo_evidence_summary as _demo_evidence_summary_mod,
    demo_still_moving as _demo_still_moving_mod,
    demo_weekly as _demo_weekly_mod,
    event_dossiers as _event_dossiers_mod,
    mission_g_evidence as _mission_g_evidence_mod,
    mission_i_evidence as _mission_i_evidence_mod,
    mission_j_evidence as _mission_j_evidence_mod,
    tracked_evidence as _tracked_evidence_mod,
)

_DEMO_ARTIFACT_DIR_ENV_VAR: str = "SECOND_ORDER_DEMO_ARTIFACT_DIR"
_DEMO_ARTIFACT_DIR_DEFAULT: _Path = (
    _Path(__file__).resolve().parent / "evidence_artifacts" / "section_c_v1"
)
_DEMO_FREEZE_ARTIFACT_FILENAME: str = "freeze_candidate_evidence.json"

_TRACKED_EVIDENCE_DIR_DEFAULT: _Path = (
    _Path(__file__).resolve().parent / "evidence_artifacts" / "section_c_v2"
)
_TRACKED_EVIDENCE_FREEZE_FILENAME:    str = "freeze_candidate_evidence.json"
_TRACKED_EVIDENCE_PHASE2_FILENAME:    str = "phase2_pool_v1.json"
_TRACKED_EVIDENCE_REJECTION_FILENAME: str = "rejection_log_summary_v1.json"


def _resolve_demo_artifact_dir() -> _Path:
    """Return the on-disk directory the demo Section C endpoints
    should load from.

    Default: ``evidence_artifacts/section_c_v1`` under the repo root.
    Override: the value of ``SECOND_ORDER_DEMO_ARTIFACT_DIR`` when
    set to a non-blank string.  Read at call time so an operator can
    swap bundles between requests; never cached at import time.
    """
    override = _os.environ.get(_DEMO_ARTIFACT_DIR_ENV_VAR, "")
    if isinstance(override, str) and override.strip():
        return _Path(override.strip())
    return _DEMO_ARTIFACT_DIR_DEFAULT


# The tracked-evidence endpoint deliberately does NOT resolve any
# environment variable. The Phase 4 contract requires the public
# tracked-evidence route to read only from the tracked
# ``evidence_artifacts/section_c_v2/`` bundle, never from a caller-supplied
# alternate path. An env-var override would let an operator repoint the
# route at a local / experimental bundle, which the contract forbids.
# Use ``_TRACKED_EVIDENCE_DIR_DEFAULT`` directly in the endpoint.


@app.get("/demo/daily-market")
def _demo_daily_market_endpoint():
    """Demo Daily Market — artifact-backed items only.

    Reads ``analyzed_event_artifact_*.json`` files from the demo
    artifact bundle resolved by :func:`_resolve_demo_artifact_dir`
    (default ``evidence_artifacts/section_c_v1``; honors the
    ``SECOND_ORDER_DEMO_ARTIFACT_DIR`` env var when set).  No DB
    write, no provider call, no LLM call, no artifact mutation.
    """
    return _demo_daily_mod.build_demo_daily_market(
        artifact_dir=_resolve_demo_artifact_dir(),
    )


@app.get("/demo/weekly-market")
def _demo_weekly_market_endpoint(
    limit: int = Query(10, ge=1, le=100),
):
    """Demo Weekly Market — production canonicalization helper.

    Reads the existing Weekly mover cache through the demo Weekly
    source's default loader.  Returns an ``ok=True`` envelope with
    ``count=0`` when no Weekly items are available.
    """
    return _demo_weekly_mod.build_demo_weekly_market(limit=limit)


@app.get("/demo/still-moving-market")
def _demo_still_moving_market_endpoint(
    limit: int = Query(12, ge=1, le=100),
):
    """Demo Still Moving Market — strict eligible items only.

    Reads the existing ``persistent`` slice from ``movers_cache``
    and applies the demo Still Moving source's strict gate.  Returns
    an ``ok=True`` envelope with ``count=0`` when no eligible
    candidates remain.
    """
    candidates = movers_cache.get_slice("persistent", limit=limit)
    return _demo_still_moving_mod.build_demo_still_moving_market(
        candidates=candidates,
    )


@app.get("/demo/evidence-summary")
def _demo_evidence_summary_endpoint():
    """Demo Evidence Summary — freeze-candidate evidence summary.

    Reads ``freeze_candidate_evidence.json`` from the demo artifact
    bundle resolved by :func:`_resolve_demo_artifact_dir` (default
    ``evidence_artifacts/section_c_v1``; honors the
    ``SECOND_ORDER_DEMO_ARTIFACT_DIR`` env var when set).
    """
    return _demo_evidence_summary_mod.build_demo_evidence_summary(
        artifact_path=(
            _resolve_demo_artifact_dir() / _DEMO_FREEZE_ARTIFACT_FILENAME
        ),
    )


_REPRESENTATIVE_CASE_ID_RE = re.compile(r"^aei-(\d+)-([0-9a-f]{8})$")


@app.get("/analysis/representative-case/{candidate_id}")
def _representative_case_endpoint(candidate_id: str):
    """Resolve one immutable candidate identity to its linked saved analysis.

    A provider-free, write-free orientation read for the Evidence Overview
    "Representative Live Case" entry point.  Deliberately NOT under
    ``/evidence/*`` — that lane stays tracked-only.  Returns only the fields
    the entry point displays; never the result snapshot body.  A missing or
    unlinked identity is an explicit availability state, never a substitute
    case, and nothing here can trigger generation or repair.
    """
    from event_inbox import candidate_event_id as _cand_id

    def _state(availability: str, **extra) -> dict:
        return {"availability": availability, "candidate_id": candidate_id,
                "analysis_event_id": None, **extra}

    m = _REPRESENTATIVE_CASE_ID_RE.match(candidate_id or "")
    if not m:
        return _state("INVALID")
    parent_cluster_id = int(m.group(1))

    # Recover the identity key: the id embeds a digest of the title_key, so
    # scan the registry keys recorded for this cluster and match exactly.
    try:
        import db as _dbm
        with _dbm._db_session() as conn:
            keys = [r[0] for r in conn.execute(
                "SELECT DISTINCT title_key FROM headline_registry"
                " WHERE cluster_id = ?", (parent_cluster_id,)).fetchall()]
    except Exception:
        _log.warning("representative-case registry read failed", exc_info=True)
        keys = []
    title_key = next((k for k in keys
                      if _cand_id(parent_cluster_id, k) == candidate_id), None)
    if title_key is None:
        return _state("CASE_NOT_FOUND")

    link = get_candidate_analysis_link(parent_cluster_id, title_key)
    if link.get("status") == "conflict":
        return _state("INVALID")
    event_id = link.get("analysis_event_id")
    if link.get("status") != "analyzed" or event_id is None:
        return _state("CASE_UNLINKED")

    event = load_event_by_id(int(event_id))
    if event is None:
        return _state("SAVED_ANALYSIS_UNAVAILABLE")

    provenance = provenance_summary_for_event(int(event_id))
    basis_status = (provenance or {}).get("status")

    # Source identities come from the CAPTURED provenance snapshot when it
    # exists — the exact records the analysis was produced from.
    sources: list = []
    stored = None
    try:
        stored = load_analysis_provenance(int(event_id))
        if stored:
            snap = stored.get("candidate_snapshot")
            if isinstance(snap, str):
                snap = _json.loads(snap)
            if isinstance(snap, dict):
                sources = [s for s in (snap.get("sources") or [])
                           if isinstance(s, str)]
    except Exception:
        _log.warning("representative-case provenance read failed",
                     exc_info=True)

    # Occurrence date: the SOURCE first-seen instant captured in immutable
    # saved provenance.  Never the saved events.event_date — in this flow
    # that is the analysis-record date, and relabeling it as the event date
    # misstates when the event occurred.  Never re-derived from the mutable
    # live registry either: the saved case's date must not move when feeds
    # refresh.  Absent provenance date => explicitly unavailable.
    occurrence_date = None
    occurrence_basis = "unavailable"
    if stored:
        first_seen = (stored.get("candidate_first_seen_at") or "").strip()
        if len(first_seen) >= 10:
            occurrence_date = first_seen[:10]
            occurrence_basis = "provenance_first_seen"

    snapshot = load_analysis_result_snapshot(int(event_id))
    base = {
        "candidate_id": candidate_id,
        "analysis_event_id": int(event_id),
        "headline": event.get("headline"),
        "occurrence_date": occurrence_date,
        "occurrence_date_basis": occurrence_basis,
        "sources": sources,
        "quality_tier": ((snapshot or {}).get("result") or {}).get(
            "quality_tier"),
        "basis_status": basis_status,
    }
    if snapshot is None:
        return {"availability": "SAVED_ANALYSIS_UNAVAILABLE", **base}
    if basis_status in (None, "LEGACY_PROVENANCE_UNAVAILABLE"):
        return {"availability": "PROVENANCE_UNAVAILABLE", **base}
    return {"availability": "AVAILABLE", **base}


@app.get("/evidence/summary")
def _evidence_summary_endpoint():
    """Tracked evidence summary — Phase 1 freeze + Phase 2 pool.

    Returns a per-phase summary of the tracked evidence layer:
    the Phase 1 freeze cohort, the closed Phase 2 BH/FDR pool, and
    the sanitized rejection / deferred-lesson summary. Phase 1 and
    Phase 2 are returned as separate top-level arrays; q-values are
    surfaced verbatim from each tracked artifact and are never
    recomputed across phases.

    Reads only from the tracked ``evidence_artifacts/section_c_v2/``
    bundle. The endpoint deliberately ignores the
    ``SECOND_ORDER_DEMO_ARTIFACT_DIR`` env var that the demo Section
    C endpoints honor; the tracked-evidence contract must not be
    repointed at a local or experimental directory.

    No DB write, no provider / yfinance / market_data / price_cache
    call, no LLM call, no artifact mutation.
    """
    base = _TRACKED_EVIDENCE_DIR_DEFAULT
    return _tracked_evidence_mod.build_tracked_evidence_summary(
        phase1_path=str(base / _TRACKED_EVIDENCE_FREEZE_FILENAME),
        phase2_path=str(base / _TRACKED_EVIDENCE_PHASE2_FILENAME),
        rejection_path=str(base / _TRACKED_EVIDENCE_REJECTION_FILENAME),
    )


@app.get("/evidence/mission-g")
def _mission_g_evidence_endpoint():
    """Mission G historical research record — tracked artifacts only.

    Structured summary of the completed Mission G record: separate
    evidence-lane denominators (accepted track record vs the two
    historical ledgers, never pooled), the broad FOMC null, the uniform
    stability diagnostics, the bounded OPEC association in its approved
    wording, the era-bounded secondary credit limitation, the G3B
    mechanism-comparability failure, and the six representative cases
    labeled as illustrations.

    Every computed research number is parsed at request time from the
    tracked ``stats/G*.md`` artifacts; artifact drift raises rather than
    serving stale numbers. No DB read or write, no provider / yfinance /
    market_data / price_cache call, no LLM call, no artifact mutation;
    works on a fresh clone with no local research state.
    """
    try:
        return _mission_g_evidence_mod.build_mission_g_evidence_summary()
    except ValueError:
        # Stable envelope: never leak artifact paths or parser internals
        # (the Mission I / Mission J drift-envelope convention).
        raise HTTPException(
            status_code=503,
            detail=("mission-g research record unavailable (tracked "
                    "artifact drift or unreadable source)"))


@app.get("/evidence/mission-i")
def _mission_i_evidence_endpoint():
    """Mission I published research record — tracked publications only.

    Structured summary of the completed Mission I ordinary-period
    comparison: the frozen question and estimand, the two separate family
    ledgers with per-horizon funnels (including the FOMC 20d structural
    infeasibility), the frozen 20-cell MEMP surface with calibration
    positions and per-cell falsifier overlays, the F1–F6 battery, the
    family/horizon interpretations, the knife-edge fragility record, the
    whole-mission conclusion with its required clarifier, and the
    permanent non-claims.

    Every research number is parsed at request time from the seven
    tracked Mission I publications; nothing is recomputed and the two
    families are never pooled. Artifact drift raises rather than serving
    stale, partial, or reinterpreted numbers. No DB read or write, no
    provider / yfinance / market_data / price_cache call, no LLM call,
    no artifact mutation; works on a fresh clone.
    """
    try:
        return _mission_i_evidence_mod.build_mission_i_evidence_summary()
    except ValueError:
        # Stable envelope: never leak artifact paths or parser internals.
        raise HTTPException(
            status_code=503,
            detail=("mission-i research record unavailable (tracked "
                    "artifact drift or unreadable source)"))


@app.get("/evidence/mission-j")
def _mission_j_evidence_endpoint():
    """Mission J published research record — tracked publications only.

    Structured summary of the completed and published Mission J record:
    the J1B 12-cell robustness surface with panel modifiers and
    denominators, the J2 timing surface (state-bearing cells plus
    descriptive-only diagnostics) with the exact-window collision
    register, and the final J3 node readings and edge states parsed from
    the tracked J3 publication — never re-adjudicated at request time.

    Every computed research number is parsed at request time from the
    tracked ``stats/J1B_*``, ``stats/J2_*``, and ``stats/J3_*``
    publications; artifact drift raises rather than serving stale,
    partial, or reinterpreted numbers. No DB read or write, no provider /
    yfinance / market_data / price_cache call, no LLM call, no artifact
    mutation; works on a fresh clone with no local research state.
    """
    try:
        return _mission_j_evidence_mod.build_mission_j_evidence_summary()
    except ValueError:
        # Stable envelope: never leak artifact paths or parser internals.
        raise HTTPException(
            status_code=503,
            detail=("mission-j research record unavailable (tracked "
                    "artifact drift or unreadable source)"))


@app.get("/evidence/event-dossiers")
def _event_dossier_index_endpoint():
    """Universal event dossier index — tracked publications only (U0).

    The complete published historical research universe: 97 events
    (65 FOMC + 32 OPEC), every one individually addressable in
    publication order — never selected, ranked, or curated, and never
    ordered by response, percentile, aggregate state, or completeness.
    Assembled at request time from the Mission I v2 event-level surface,
    the G1A / G1B identity-and-source ledgers, the Mission G / J
    aggregate builders, and the G6C publication (enrichment discovery
    only). Artifact drift raises rather than serving a stale or partial
    index. No DB read or write, no provider / yfinance / market_data /
    price_cache call, no LLM call, no artifact mutation; works on a
    fresh clone.
    """
    try:
        return _event_dossiers_mod.build_event_dossier_index()
    except ValueError:
        # Stable envelope: never leak artifact paths or parser internals.
        raise HTTPException(
            status_code=503,
            detail=("event dossier index unavailable (tracked artifact "
                    "drift or unreadable source)"))


@app.get("/evidence/event-dossiers/{candidate_id}")
def _event_dossier_detail_endpoint(candidate_id: str):
    """One universal event dossier — tracked publications only (U0).

    Explicit section states (available / structurally_unavailable /
    not_applicable / not_exposed / unresolved / contradictory), visible
    missingness, aggregate labels kept as aggregate context, and
    fail-closed CONTRADICTORY classification on identity disagreement.
    Unknown identifiers return a stable 404; artifact drift raises the
    same 503 envelope as the index. Read-only and tracked-only, exactly
    as the index endpoint.
    """
    try:
        dossier = _event_dossiers_mod.build_event_dossier(candidate_id)
    except ValueError:
        raise HTTPException(
            status_code=503,
            detail=("event dossier unavailable (tracked artifact drift "
                    "or unreadable source)"))
    if dossier is None:
        raise HTTPException(
            status_code=404,
            detail="event dossier not found: unknown candidate id")
    return dossier
